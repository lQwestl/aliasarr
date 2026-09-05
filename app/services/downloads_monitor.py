"""
Мониторинг активных загрузок в торрент-клиентах и автоматический импорт завершённых файлов.

Фоновый процесс:
1. Опрашивает торрент-клиенты по сохранённому torrent_hash активных загрузок
2. Обновляет процент выполнения для отображения прогресса в интерфейсе
3. При завершении загрузки (100% / seeding) выполняет переименование и перемещение файлов в библиотеку
4. Переводит статус в DOWNLOADED и отправляет уведомление о завершении импорта
"""

from __future__ import annotations

from typing import Optional, List, Dict, Any

import asyncio
import datetime as dt
import logging
import os

try:
    from sqlalchemy import and_, or_
    from sqlalchemy.orm import Session
    from app.database import SessionLocal
    from app.models.db import DownloadClient, Episode, EpisodeStatus, Show
except ImportError:
    def and_(*args): return args
    def or_(*args): return args
    Session = object
    SessionLocal = None
    class _MockCol:
        def __eq__(self, other): return self
        def __ne__(self, other): return self
        def isnot(self, other): return self
        def is_(self, other): return self
        def in_(self, other): return self
    DownloadClient = type("DownloadClient", (), {"id": _MockCol(), "name": _MockCol(), "type": _MockCol(), "enabled": _MockCol()})
    Episode = type("Episode", (), {"id": _MockCol(), "show_id": _MockCol(), "status": _MockCol(), "torrent_hash": _MockCol(), "download_client_id": _MockCol(), "download_progress": _MockCol()})
    EpisodeStatus = type("EpisodeStatus", (), {"DOWNLOADING": "downloading", "DOWNLOADED": "downloaded", "WANTED": "wanted", "MISSING": "missing", "UNAIRED": "unaired"})
    Show = type("Show", (), {"id": _MockCol(), "title": _MockCol(), "content_type": _MockCol(), "path": _MockCol()})
from app.services.download_client import get_client
from app.services.postprocess import process_download, process_movie_download
from app.services.release_log_service import log_release_event
from app.services.settings_service import get_or_create_settings

logger = logging.getLogger("aliasarr.downloads_monitor")

# Прогресс 100% для завершения раздачи
_COMPLETE_THRESHOLD = 1.0
_NOTIFIED_PENDING_SPECIALS: set[str] = set()
_RECONCILED_TORRENTS: set[str] = set()


def _folder_and_template(settings, content_type: str) -> tuple[str, str, str]:
    if content_type == "movie":
        return settings.root_folder_movies or settings.root_folder, settings.rename_template_movie, ""
    if content_type == "anime":
        return (
            settings.root_folder_anime or settings.root_folder,
            settings.rename_template_anime,
            getattr(settings, "season_folder_template_anime", "Сезон {season}") or "Сезон {season}",
        )
    return (
        settings.root_folder_series or settings.root_folder,
        settings.rename_template_series,
        getattr(settings, "season_folder_template_series", "Сезон {season}") or "Сезон {season}",
    )


def _resolve_torrent_files_and_path(t, settings, show: Optional[Show] = None) -> tuple[str, list[str]]:
    """
    Определяет точный путь к завершённой раздаче и конкретный список файлов торрента.
    Гарантирует 100% изоляцию импорта: если скачивался один файл или конкретная папка,
    импортируются ТОЛЬКО файлы из этого торрента, без сканирования сторонних папок и релизов.
    """
    content_type = getattr(show, "content_type", "series") if show else "series"
    candidates_base = []
    if t.save_path:
        candidates_base.append(t.save_path)

    # Категорийные папки загрузок
    cat_folder = ""
    if content_type == "movie":
        cat_folder = getattr(settings, "download_folder_movies", "")
    elif content_type == "anime":
        cat_folder = getattr(settings, "download_folder_anime", "")
    else:
        cat_folder = getattr(settings, "download_folder_series", "")

    if cat_folder:
        candidates_base.append(cat_folder)

    content_path = getattr(t, "content_path", "") or ""
    if content_path and os.path.exists(content_path):
        if os.path.isfile(content_path):
            return content_path, [content_path]
        elif os.path.isdir(content_path):
            candidates_base.insert(0, content_path)

    # 1. Если клиент вернул список файлов торрента (t.files) — находим их точные пути на диске
    if getattr(t, "files", None):
        resolved_files = []
        for tf in t.files:
            if getattr(tf, "priority", 1) == 0:
                continue
            fname = getattr(tf, "name", "")
            if not fname:
                continue
            found = False
            for b_dir in candidates_base:
                p1 = os.path.join(b_dir, fname)
                if os.path.exists(p1) and os.path.isfile(p1):
                    resolved_files.append(p1)
                    found = True
                    break
                p2 = os.path.join(b_dir, os.path.basename(fname))
                if os.path.exists(p2) and os.path.isfile(p2):
                    resolved_files.append(p2)
                    found = True
                    break
            if not found and content_path and os.path.isdir(content_path):
                p3 = os.path.join(content_path, fname)
                if os.path.exists(p3) and os.path.isfile(p3):
                    resolved_files.append(p3)

        if resolved_files:
            if len(resolved_files) == 1:
                return resolved_files[0], resolved_files
            try:
                common_dir = os.path.commonpath(resolved_files)
                return common_dir, resolved_files
            except Exception:
                return os.path.dirname(resolved_files[0]), resolved_files

    # 2. Проверяем конкретную папку или файл os.path.join(save_path, name)
    for b_dir in candidates_base:
        if t.name:
            target = os.path.join(b_dir, t.name)
            if os.path.exists(target):
                if os.path.isfile(target):
                    return target, [target]
                return target, []

    # 3. Если content_path существует на диске
    if content_path and os.path.exists(content_path):
        if os.path.isfile(content_path):
            return content_path, [content_path]
        return content_path, []

    # 4. Fallback: если список файлов не был получен, ищем в корне save_path файлы, матчащиеся с тайтлом шоу
    if show and t.save_path and os.path.isdir(t.save_path):
        from app.services.matcher import build_alias_candidates, best_alias_match
        aliases = build_alias_candidates(show, db=db)
        matched_items = []
        try:
            for item in os.listdir(t.save_path):
                item_path = os.path.join(t.save_path, item)
                b_alias, b_score = best_alias_match(item, aliases, threshold=65)
                if b_alias and b_score >= 65:
                    if os.path.isfile(item_path):
                        matched_items.append(item_path)
                    elif os.path.isdir(item_path):
                        return item_path, []
            if matched_items:
                if len(matched_items) == 1:
                    return matched_items[0], matched_items
                return t.save_path, matched_items
        except Exception:
            pass

    # 5. Крайний fallback
    direct = os.path.join(t.save_path, t.name) if t.save_path and t.name else (t.save_path or "")
    return direct, []


def _resolve_download_path(t, settings, content_type: str) -> str:
    """Определяет реальный путь к файлам завершённой раздачи на диске (совместимость)."""
    p, _ = _resolve_torrent_files_and_path(t, settings, None)
    return p


def _run_postprocess_in_thread(
    show_id: int,
    download_path: str,
    template: str,
    root_folder: str,
    season_template: str,
    is_movie: bool,
    specific_files: Optional[list[str]] = None,
    torrent_hash: Optional[str] = None,
    task_id: Optional[str] = None,
) -> list[dict]:
    """Выполняет перемещение файлов и обновление БД в отдельном потоке,
    чтобы не блокировать asyncio event loop и веб-интерфейс GUI."""
    def cb(pct: float, msg: str):
        if task_id:
            try:
                from app.services.task_manager import task_manager
                task_manager.update_task(task_id, progress=pct, message=msg)
            except Exception:
                pass

    thread_db = SessionLocal()
    try:
        show_obj = thread_db.get(Show, show_id)
        if not show_obj:
            return []
        if is_movie:
            return process_movie_download(
                thread_db,
                show_obj,
                download_path,
                template,
                root_folder,
                specific_files=specific_files,
                torrent_hash=torrent_hash,
                progress_callback=cb,
            )
        else:
            return process_download(
                thread_db,
                show_obj,
                download_path,
                template,
                root_folder,
                season_folder_template=season_template,
                specific_files=specific_files,
                torrent_hash=torrent_hash,
                progress_callback=cb,
            )
    except Exception as exc:
        logger.exception("Ошибка в _run_postprocess_in_thread для шоу %s: %s", show_id, exc)
        raise
    finally:
        thread_db.close()


_MISSING_TORRENT_POLL_COUNTS: dict[str, int] = {}


async def check_downloads(db: Session) -> list[dict]:
    settings = get_or_create_settings(db)
    downloading = (
        db.query(Episode)
        .filter(Episode.status == EpisodeStatus.DOWNLOADING, Episode.torrent_hash.isnot(None))
        .all()
    )
    if not downloading:
        return []

    # Собираем все торренты со всех активных загрузчиков
    active_clients = db.query(DownloadClient).filter(DownloadClient.enabled == True).all()  # noqa: E712
    if not active_clients:
        return []

    torrents_by_hash: dict[str, tuple[any, DownloadClient]] = {}
    successful_clients: set[int] = set()
    for dc_row in active_clients:
        try:
            client = get_client(dc_row)
            torrents = await client.list_torrents()
            for t in torrents:
                if t.hash:
                    torrents_by_hash[t.hash.lower()] = (t, dc_row)
            successful_clients.add(dc_row.id)
        except Exception as exc:
            logger.warning("Не удалось получить список торрентов у %s: %s", dc_row.name, exc)

    # Группируем серии по хэшу торрента
    episodes_by_hash: dict[str, list[Episode]] = {}
    for ep in downloading:
        if ep.torrent_hash:
            episodes_by_hash.setdefault(ep.torrent_hash.lower(), []).append(ep)

    results = []
    progress_changed = False

    for torrent_hash, eps in episodes_by_hash.items():
        entry = torrents_by_hash.get(torrent_hash)
        show_id = eps[0].show_id if eps else None
        show_obj = db.get(Show, show_id) if show_id else None

        # Проверяем, не заблокирован ли данный торрент в черном списке (Blocklist)
        from app.services.blocklist_service import is_release_blocked
        is_blocked, block_reason = is_release_blocked(
            db,
            show=show_obj,
            show_id=show_id,
            torrent_hash=torrent_hash,
            title=getattr(entry[0], "name", None) if entry else None,
        )
        if is_blocked:
            logger.warning(
                "DownloadsMonitor: Раздача %s для тайтла «%s» находится в черном списке (%s). Немедленно удаляем из загрузчика.",
                torrent_hash, getattr(show_obj, "title", show_id), block_reason,
            )
            if entry:
                t, dc_row = entry
                try:
                    client = get_client(dc_row)
                    await client.remove_torrent(torrent_hash, delete_files=True)
                except Exception as rem_exc:
                    logger.debug("DownloadsMonitor: Не удалось удалить заблокированный торрент %s: %s", torrent_hash, rem_exc)

            today = dt.date.today()
            for ep in eps:
                if ep.status == EpisodeStatus.DOWNLOADING:
                    ep.torrent_hash = None
                    ep.download_client_id = None
                    ep.download_progress = 0.0
                    if getattr(ep, "file_path", None):
                        ep.status = EpisodeStatus.DOWNLOADED
                    else:
                        air_d = getattr(ep, "air_date", None)
                        if isinstance(air_d, dt.datetime):
                            air_d = air_d.date()
                        if air_d and air_d > today:
                            ep.status = EpisodeStatus.UNAIRED
                        else:
                            ep.status = EpisodeStatus.WANTED
                    db.add(ep)
                    progress_changed = True
            continue

        if not entry:
            # Если хотя бы один клиент не ответил (ошибка/таймаут), не сбрасываем серии — возможно раздача там
            client_id = eps[0].download_client_id if eps else None
            if client_id and client_id not in successful_clients:
                continue
            if not successful_clients:
                continue

            # Защита от кратковременных сбоев: сбрасываем статус только если раздача отсутствует 5 опросов подряд (~30-60 сек)
            missing_count = _MISSING_TORRENT_POLL_COUNTS.get(torrent_hash, 0) + 1
            _MISSING_TORRENT_POLL_COUNTS[torrent_hash] = missing_count
            if missing_count < 5:
                continue

            _MISSING_TORRENT_POLL_COUNTS.pop(torrent_hash, None)
            _RECONCILED_TORRENTS.discard(torrent_hash)
            # Торрент действительно удален из загрузчика: сбрасываем в WANTED / UNAIRED / DOWNLOADED
            today = dt.date.today()
            for ep in eps:
                if ep.status == EpisodeStatus.DOWNLOADING:
                    ep.torrent_hash = None
                    ep.download_client_id = None
                    ep.download_progress = 0.0
                    if getattr(ep, "file_path", None):
                        ep.status = EpisodeStatus.DOWNLOADED
                    else:
                        air_d = getattr(ep, "air_date", None)
                        if isinstance(air_d, dt.datetime):
                            air_d = air_d.date()
                        if air_d and air_d > today:
                            ep.status = EpisodeStatus.UNAIRED
                        else:
                            ep.status = EpisodeStatus.WANTED
                    db.add(ep)
                    progress_changed = True
            logger.info("Раздача %s удалена из загрузчика. Серии переведены в статус поиска.", torrent_hash)
            continue

        # Раздача найдена: сбрасываем счетчик пропущенных опросов
        _MISSING_TORRENT_POLL_COUNTS.pop(torrent_hash, None)
        t, dc_row = entry

        # Разовая сверка селективной загрузки активной раздачи
        if torrent_hash not in _RECONCILED_TORRENTS:
            try:
                client = get_client(dc_row)
                full_t = await client.get_torrent(torrent_hash)
                if full_t and full_t.files:
                    _RECONCILED_TORRENTS.add(torrent_hash)
                    from app.services.auto_search import evaluate_torrent_file_priority
                    from app.services.matcher import get_show_title_words
                    all_show_eps = db.query(Episode).filter(Episode.show_id == show_id).all() if show_id else eps
                    show_ova_mode = getattr(show_obj, "ova_mode", "auto") or "auto"
                    show_words = get_show_title_words(show_obj)

                    # Для сверки используем серии этой раздачи + нескачанные серии (WANTED/UNAIRED), исключая уже скачанные
                    target_reconcile_eps = [
                        e for e in all_show_eps
                        if e.torrent_hash == torrent_hash or e.status in (EpisodeStatus.DOWNLOADING, EpisodeStatus.WANTED, EpisodeStatus.UNAIRED)
                    ] if all_show_eps else eps

                    matched_eps = []
                    wanted_indices = []
                    unwanted_indices = []
                    for f in full_t.files:
                        prio = evaluate_torrent_file_priority(
                            file_name=f.name,
                            file_index=f.index,
                            target_episodes=target_reconcile_eps,
                            content_type=getattr(show_obj, "content_type", "series") if show_obj else "series",
                            ova_mode=show_ova_mode,
                            torrent_name=getattr(full_t, "name", "") or "",
                            all_show_episodes=all_show_eps,
                            out_matched_episodes=matched_eps,
                            show_words=show_words,
                        )
                        if prio > 0:
                            wanted_indices.append(f.index)
                        else:
                            unwanted_indices.append(f.index)

                    # Если в клиенте скачиваются нежелательные файлы, отключаем их
                    if unwanted_indices and hasattr(client, "set_files_wanted_unwanted"):
                        currently_wanted_unwanted = [
                            f.index for f in full_t.files
                            if f.index in unwanted_indices and getattr(f, "priority", 1) > 0
                        ]
                        if currently_wanted_unwanted:
                            try:
                                await client.set_files_wanted_unwanted(torrent_hash, wanted_indices, currently_wanted_unwanted)
                                logger.info(
                                    "DownloadsMonitor: В раздаче %s отключено %d нежелательных файлов в клиенте",
                                    torrent_hash, len(currently_wanted_unwanted),
                                )
                                log_release_event(
                                    stage="download",
                                    level="info",
                                    show_title=getattr(db.get(Show, eps[0].show_id), "title", None) if eps else None,
                                    show_id=eps[0].show_id if eps else None,
                                    release_title=getattr(t, "name", torrent_hash),
                                    indexer="DownloadsMonitor",
                                    message=(
                                        f"DownloadsMonitor: Самовосстановление: в раздаче «{getattr(t, 'name', torrent_hash)}» "
                                        f"обнаружено и отключено в клиенте {len(currently_wanted_unwanted)} нежелательных файлов."
                                    ),
                                    details={
                                        "torrent_hash": torrent_hash,
                                        "disabled_file_indices": currently_wanted_unwanted,
                                    },
                                    db=db,
                                )
                            except Exception as set_err:
                                logger.debug("DownloadsMonitor: Не удалось отключить файлы в %s: %s", torrent_hash, set_err)

                    actually_matched_ids: set[int] = set()
                    actually_matched_pairs: set[tuple[int, int]] = set()
                    if matched_eps:
                        actually_matched_ids = {e.id for e in matched_eps if getattr(e, "id", None) is not None}
                        actually_matched_pairs = {(e.season_number, e.episode_number) for e in matched_eps}

                        # 1. Восстанавливаем/привязываем серии, которые реально загружаются в клиенте, но не были привязаны к раздаче
                        for m_ep in matched_eps:
                            if m_ep.status == EpisodeStatus.WANTED or (m_ep.status == EpisodeStatus.DOWNLOADING and not m_ep.torrent_hash):
                                m_ep.status = EpisodeStatus.DOWNLOADING
                                m_ep.torrent_hash = torrent_hash
                                m_ep.download_client_id = dc_row.id
                                m_ep.download_progress = t.progress
                                db.add(m_ep)
                                progress_changed = True
                                logger.info(
                                    "DownloadsMonitor: Серия S%02dE%02d («%s») привязана к активной раздаче %s (прогресс %.1f%%)",
                                    m_ep.season_number, m_ep.episode_number, m_ep.title or "", torrent_hash, (t.progress or 0.0) * 100,
                                )

                    # 2. Серии из eps, которых реально нет в загружаемых файлах раздачи, возвращаем в WANTED/UNAIRED/DOWNLOADED
                    uncovered = [
                        e for e in eps
                        if (e.id and e.id not in actually_matched_ids) and (e.season_number, e.episode_number) not in actually_matched_pairs
                    ]
                    if uncovered:
                        today = dt.date.today()
                        for u_ep in uncovered:
                            air_d = getattr(u_ep, "air_date", None)
                            if isinstance(air_d, dt.datetime):
                                air_d = air_d.date()
                            if getattr(u_ep, "file_path", None):
                                u_ep.status = EpisodeStatus.DOWNLOADED
                            elif air_d and air_d > today:
                                u_ep.status = EpisodeStatus.UNAIRED
                            else:
                                u_ep.status = EpisodeStatus.WANTED
                            u_ep.torrent_hash = None
                            u_ep.download_client_id = None
                            u_ep.download_progress = 0.0
                            db.add(u_ep)
                            logger.info(
                                "DownloadsMonitor: Серия S%02dE%02d («%s») не загружается в раздаче %s — статус возвращен",
                                u_ep.season_number, u_ep.episode_number, getattr(u_ep, "title", "") or "", torrent_hash,
                            )
                        progress_changed = True

                    if not matched_eps:
                        # В раздаче вообще нет ни одной нужной серии для тайтла
                        from app.services import blocklist_service
                        try:
                            blocklist_service.add_to_blocklist(
                                db,
                                release_title=getattr(t, "name", torrent_hash),
                                reason="Раздача не содержит ни одной нужной серии для тайтла",
                                show=show_obj,
                                show_id=show_obj.id if show_obj else None,
                                torrent_hash=torrent_hash,
                                size=getattr(t, "size", None),
                            )
                        except Exception as b_err:
                            logger.debug("DownloadsMonitor: Не удалось занести в черный список: %s", b_err)
                        try:
                            await client.remove_torrent(torrent_hash, delete_files=True)
                            logger.warning(
                                "DownloadsMonitor: Раздача %s не содержит ни одной нужной серии для «%s». Раздача удалена из клиента и добавлена в черный список.",
                                torrent_hash, getattr(show_obj, "title", torrent_hash),
                            )
                        except Exception as rem_err:
                            logger.debug("DownloadsMonitor: Не удалось удалить пустую раздачу %s: %s", torrent_hash, rem_err)

                    if progress_changed:
                        db.commit()
                    eps = [e for e in all_show_eps if e.torrent_hash == torrent_hash and e.status == EpisodeStatus.DOWNLOADING]
            except Exception as rec_err:
                logger.debug("DownloadsMonitor: Ошибка при сверке файлов раздачи %s: %s", torrent_hash, rec_err)

        if not eps:
            continue

        for ep in eps:
            if abs((ep.download_progress or 0) - t.progress) > 0.001:
                ep.download_progress = t.progress
                progress_changed = True
            if not ep.download_client_id:
                ep.download_client_id = dc_row.id
                progress_changed = True
            db.add(ep)

        state_str = str(t.state).lower()
        _ACTIVELY_DOWNLOADING_STATES = {
            "downloading", "stalleddl", "forceddl", "queueddl", "checkingdl",
            "allocating", "metadl", "moving", "4", "checking", "check pending",
            "download", "download_wait", "check_wait", "1", "2", "3", "pauseddl"
        }
        _SEEDING_COMPLETED_STATES = {
            "completed", "seeding", "pausedup", "stalledup", "forcedup",
            "queuedup", "uploading", "100%", "finished", "seed", "complete", "6", "5",
        }
        _STOPPED_STATES = {"stopped", "paused", "0"}

        left_done = getattr(t, "left_until_done", None)
        # has_finished_bytes требует прогресс > 0.01 для отсечения отключенных раздач с 0% байт
        has_finished_bytes = (t.progress >= 0.999) or (left_done is not None and left_done == 0 and t.size > 0 and (t.progress or 0) > 0.01)

        # Раздача завершена:
        if state_str in _ACTIVELY_DOWNLOADING_STATES:
            is_done = False
        elif state_str in _SEEDING_COMPLETED_STATES:
            is_done = has_finished_bytes
        elif state_str in _STOPPED_STATES:
            is_done = has_finished_bytes
        else:
            is_done = has_finished_bytes

        if not is_done:
            continue

        show = db.get(Show, eps[0].show_id)
        if not show:
            continue

        log_release_event(
            stage="download",
            level="info",
            show_title=show.title,
            show_id=show.id,
            release_title=getattr(t, "name", torrent_hash),
            indexer="DownloadsMonitor",
            message=(
                f"DownloadsMonitor: Раздача «{getattr(t, 'name', torrent_hash)}» завершила загрузку байт (100%, "
                f"left_until_done={left_done if left_done is not None else 0}, клиент: {dc_row.name}, статус: {state_str}). "
                "Проверка файлов на диске перед запуском импорта..."
            ),
            details={
                "torrent_hash": torrent_hash,
                "progress": t.progress,
                "left_until_done": left_done,
                "state": state_str,
                "client": dc_row.name,
            },
            db=db,
        )

        is_specials_only = bool(eps and all(ep.season_number == 0 for ep in eps))
        if is_specials_only:
            # Спецвыпуски (Сезон 0) скачаны на 100%.
            # Чтобы исключить ошибки нумерации нестандартных OVA/SP, не выполняем автоматический
            # перенос файлов, а переводим прогресс в 100% и ожидаем подтверждения сопоставления
            # пользователем через кнопку «Импорт спецвыпусков».
            for ep in eps:
                if ep.download_progress != 1.0:
                    ep.download_progress = 1.0
                    db.add(ep)
            db.commit()

            release_name = getattr(t, "name", torrent_hash) or torrent_hash

            log_release_event(
                stage="download",
                level="info",
                show_title=show.title,
                show_id=show.id,
                release_title=release_name,
                message=f"Спецвыпуск «{release_name}» для «{show.title}» скачан на 100% и ожидает ручного импорта.",
                details={"torrent_hash": torrent_hash, "is_specials_pending": True},
                db=db,
            )

            # Отправка уведомления в мессенджеры о необходимости ручного импорта
            if torrent_hash not in _NOTIFIED_PENDING_SPECIALS:
                _NOTIFIED_PENDING_SPECIALS.add(torrent_hash)
                from app.services.notifications import notify_all
                msg = (
                    f"✨ Спецвыпуск «{release_name}» скачан и ожидает ручного импорта!\n"
                    f"Тайтл: «{show.title}»\n\n"
                    f"Откройте карточку тайтла в Aliasarr для сопоставления серий и подтверждения переноса."
                )
                await notify_all(db=db, event_type="import", message=msg)
                await notify_all(db=db, event_type="manual_interaction_required", message=msg)

            # Если часть серий из этой же группы уже импортирована вручную (статус DOWNLOADED),
            # а оставшиеся зависли на 100% downloading без файла — сбрасываем их в WANTED/UNAIRED
            today = dt.date.today()
            partially_imported = any(ep.status == EpisodeStatus.DOWNLOADED for ep in eps)
            if partially_imported:
                for ep in eps:
                    if ep.status == EpisodeStatus.DOWNLOADING and not ep.file_path:
                        air_d = ep.air_date
                        if isinstance(air_d, dt.datetime):
                            air_d = air_d.date()
                        ep.status = EpisodeStatus.UNAIRED if (air_d and air_d > today) else EpisodeStatus.WANTED
                        ep.download_progress = 0.0
                        ep.torrent_hash = None
                        ep.download_client_id = None
                        db.add(ep)
                db.commit()
            continue

        # Запрашиваем полные метаданные и список файлов торрента из клиента
        full_torrent = None
        client = None
        try:
            client = get_client(dc_row)
            full_torrent = await client.get_torrent(torrent_hash)
        except Exception as exc:
            logger.debug("Не удалось получить детальные файлы торрента %s: %s", torrent_hash, exc)

        torrent_obj = full_torrent or t
        download_path, specific_files = _resolve_torrent_files_and_path(torrent_obj, settings, show)

        # Проверяем реальное наличие файлов на диске перед запуском импорта
        has_actual_files = False
        if specific_files:
            has_actual_files = any(os.path.exists(f) and (os.path.isdir(f) or os.path.getsize(f) > 0) for f in specific_files)
        elif download_path and os.path.exists(download_path):
            if os.path.isfile(download_path):
                has_actual_files = os.path.getsize(download_path) > 0
            elif os.path.isdir(download_path):
                from app.services.postprocess import find_release_files
                rf = find_release_files(download_path)
                has_actual_files = bool(rf.get("video"))

        if not has_actual_files:
            logger.info(
                "Торрент %s («%s») завершён в клиенте (100%%), но целевые файлы отсутствуют на диске (%s). "
                "Запускаем принудительную перепроверку целостности (recheck) и возобновляем загрузку.",
                torrent_hash, show.title, download_path,
            )
            log_release_event(
                stage="download",
                level="warning",
                show_title=show.title,
                show_id=show.id,
                release_title=getattr(t, "name", torrent_hash),
                indexer="DownloadsMonitor",
                message=(
                    f"DownloadsMonitor: Внимание: раздача «{getattr(t, 'name', torrent_hash)}» завершена в клиенте, "
                    f"но видеофайлы на диске отсутствуют ({download_path}). "
                    "Запущена принудительная перепроверка (recheck) и возобновление раздачи."
                ),
                details={"torrent_hash": torrent_hash, "download_path": download_path},
                db=db,
            )
            if client:
                try:
                    await client.recheck_torrent(torrent_hash)
                    await client.resume_torrent(torrent_hash)
                except Exception as exc:
                    logger.warning("Не удалось запустить recheck для торрента %s: %s", torrent_hash, exc)

            # Сбрасываем прогресс серий, чтобы в интерфейсе не висело 100%
            for ep in eps:
                if ep.status == EpisodeStatus.DOWNLOADING and (ep.download_progress or 0) >= 0.99:
                    ep.download_progress = 0.0
                    db.add(ep)
            db.commit()
            continue

        root_folder, template, season_template = _folder_and_template(settings, show.content_type)
        from app.services.task_manager import task_manager
        async with task_manager.track(
            name="import_files",
            title=f"Импорт и перенос: {show.title}",
            message=f"Перемещение и переименование файлов для «{show.title}»...",
            show_id=show.id,
            progress=0.01,
        ) as t_task:
            try:
                logger.info(
                    "Запуск переноса завершённого торрента %s («%s») по пути: %s (файлов: %d)",
                    torrent_hash, show.title, download_path, len(specific_files),
                )
                # Выполняем тяжелый перенос и копирование файлов в отдельном пуле потоков
                import_results = await asyncio.to_thread(
                    _run_postprocess_in_thread,
                    show.id,
                    download_path,
                    template,
                    root_folder,
                    season_template,
                    show.content_type == "movie",
                    specific_files,
                    torrent_hash,
                    t_task.id,
                )
                results.append({"show_id": show.id, "torrent_hash": torrent_hash, "imported": import_results})

                # Обновляем статусы в текущей сессии db для сматченных серий
                for ep in eps:
                    try:
                        db.refresh(ep)
                    except Exception:
                        pass

                log_release_event(
                    stage="import",
                    level="success" if import_results else "info",
                    show_title=show.title,
                    show_id=show.id,
                    release_title=getattr(torrent_obj, "name", torrent_hash),
                    message=f"Импорт завершен: обработано {len(import_results)} файл(ов) для «{show.title}»",
                    details={"results": import_results, "torrent_hash": torrent_hash},
                    db=db,
                )

                # Отправляем уведомление об успешном скачивании и импорте
                if import_results:
                    from app.services.notifications import notify_all
                    imported_items = [r for r in import_results if r.get("status") == "imported" and r.get("dest")]
                    has_upgrade = any(r.get("is_upgrade") for r in import_results)
                    show_content_type = getattr(show, "content_type", "series")
                    show_year = getattr(show, "year", None)
                    is_movie = show_content_type == "movie"
                    yr_str = f" ({show_year})" if show_year else ""
                    type_prefix = "фильм " if is_movie else ("аниме " if show_content_type == "anime" else "сериал ")

                    header = (
                        f"Релиз скачан и произведена замена старого на новый: {type_prefix}«{show.title}»{yr_str}"
                        if has_upgrade
                        else f"Релиз скачан и перенесен: {type_prefix}«{show.title}»{yr_str}"
                    )

                    if len(imported_items) == 1:
                        fname = os.path.basename(imported_items[0]["dest"])
                        msg = f"{header}\nФайл: {fname}"
                        t_task.complete(f"Импортирован файл: {fname}")
                    elif len(imported_items) > 1:
                        lines = [header, "Файлы:"]
                        for it in imported_items[:10]:
                            fname = os.path.basename(it["dest"])
                            lines.append(f"• {fname}")
                        more = len(imported_items) - 10
                        if more > 0:
                            lines.append(f"• ...и ещё {more} файлов")
                        msg = "\n".join(lines)
                        t_task.complete(f"Импортировано {len(imported_items)} файлов")
                    else:
                        msg = header
                        t_task.complete("Файлы успешно обработаны")

                    try:
                        await notify_all(db, "import", msg)
                    except Exception as e:
                        logger.warning("Не удалось отправить уведомление об импорте: %s", e)
                else:
                    t_task.complete("Нет новых файлов для импорта")
                    today = dt.date.today()
                    for ep in eps:
                        if ep.status == EpisodeStatus.DOWNLOADING and ep.torrent_hash == torrent_hash:
                            air_d = ep.air_date
                            if isinstance(air_d, dt.datetime):
                                air_d = air_d.date()
                            ep.status = EpisodeStatus.UNAIRED if (air_d and air_d > today) else EpisodeStatus.WANTED
                            ep.torrent_hash = None
                            ep.download_client_id = None
                            ep.download_progress = 0.0
                            db.add(ep)
                    from app.services import blocklist_service
                    try:
                        blocklist_service.add_to_blocklist(
                            db,
                            release_title=getattr(t, "name", torrent_hash),
                            reason="Раздача не содержала запрошенных серий (все файлы уже скачаны или не запрошены)",
                            show=show,
                            show_id=show.id if show else None,
                            torrent_hash=torrent_hash,
                            size=getattr(t, "size", None),
                        )
                    except Exception as b_err:
                        logger.debug("DownloadsMonitor: Не удалось добавить раздачу %s в черный список: %s", torrent_hash, b_err)
                    try:
                        client = get_client(dc_row)
                        await client.remove_torrent(torrent_hash, delete_files=True)
                        logger.info(
                            "DownloadsMonitor: Раздача %s не содержала новых файлов для «%s», удалена из клиента и добавлена в черный список.",
                            torrent_hash, show.title,
                        )
                    except Exception as rem_err:
                        logger.debug("DownloadsMonitor: Не удалось удалить ненужную раздачу %s: %s", torrent_hash, rem_err)

                # Проверка лимита времени раздачи (Seed Time Limit / Ratio Limit) ПОСЛЕ завершения импорта
                state_str = str(getattr(t, "state", "")).lower()
                is_actively_seeding = state_str in ("seeding", "uploading", "forcedup", "queuedup", "stalledup", "seed", "6", "5")
                if is_actively_seeding:
                    seed_time_limit_min = getattr(dc_row, "seed_time_limit", None)
                    seed_ratio_limit = getattr(dc_row, "seed_ratio_limit", None)
                    time_reached = False
                    ratio_reached = False

                    if seed_time_limit_min is not None and seed_time_limit_min > 0:
                        seeding_sec = getattr(t, "seeding_time", 0) or 0
                        if seeding_sec >= seed_time_limit_min * 60:
                            time_reached = True
                    elif seed_time_limit_min == 0:
                        time_reached = True

                    if seed_ratio_limit is not None and seed_ratio_limit > 0:
                        current_ratio = getattr(t, "ratio", 0.0) or 0.0
                        if current_ratio >= seed_ratio_limit:
                            ratio_reached = True

                    has_any_limit = (seed_time_limit_min is not None and seed_time_limit_min > 0) or (seed_ratio_limit is not None and seed_ratio_limit > 0)
                    if has_any_limit and (time_reached or ratio_reached):
                        try:
                            client = get_client(dc_row)
                            await client.pause_torrent(torrent_hash)
                            logger.info(
                                "Торрент %s достиг лимита раздачи (%s мин / ratio %s). Раздача остановлена после импорта.",
                                torrent_hash, seed_time_limit_min, seed_ratio_limit,
                            )
                        except Exception as e:
                            logger.debug("Не удалось поставить торрент %s на паузу: %s", torrent_hash, e)

            except Exception as exc:
                logger.exception("Ошибка постобработки для видео %s: %s", show.id, exc)
                t_task.fail(error=str(exc))
            finally:
                _RECONCILED_TORRENTS.discard(torrent_hash)

    if progress_changed or results:
        try:
            db.commit()
        except Exception:
            db.rollback()

    return results
