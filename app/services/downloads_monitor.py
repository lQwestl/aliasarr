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
    from sqlalchemy import and_, or_, func
    from sqlalchemy.orm import Session
    from app.database import SessionLocal
    from app.models.db import DownloadClient, Episode, EpisodeStatus, Show, DownloadHistory, Indexer, TrackedRelease
except ImportError:
    def and_(*args): return args
    def or_(*args): return args
    class _MockFunc:
        def lower(self, col): return col
    func = _MockFunc()
    Session = object
    SessionLocal = None
    class _MockCol:
        def __eq__(self, other): return self
        def __ne__(self, other): return self
        def isnot(self, other): return self
        def is_(self, other): return self
        def in_(self, other): return self
        def desc(self): return self
        def asc(self): return self

    class _MockModelMeta(type):
        def __getattr__(cls, name):
            return _MockCol()

    class _MockModel(metaclass=_MockModelMeta):
        def __getattr__(self, name):
            return _MockCol()

    DownloadClient = type("DownloadClient", (_MockModel,), {"id": _MockCol(), "name": _MockCol(), "type": _MockCol(), "enabled": _MockCol()})
    Episode = type("Episode", (_MockModel,), {"id": _MockCol(), "show_id": _MockCol(), "status": _MockCol(), "season_number": _MockCol(), "episode_number": _MockCol(), "file_path": _MockCol(), "torrent_hash": _MockCol(), "download_client_id": _MockCol(), "download_progress": _MockCol(), "air_date": _MockCol()})
    EpisodeStatus = type("EpisodeStatus", (), {"DOWNLOADING": "downloading", "DOWNLOADED": "downloaded", "WANTED": "wanted", "MISSING": "missing", "UNAIRED": "unaired"})
    Show = type("Show", (_MockModel,), {"id": _MockCol(), "title": _MockCol(), "content_type": _MockCol(), "path": _MockCol()})
    DownloadHistory = type("DownloadHistory", (_MockModel,), {"id": _MockCol(), "show_id": _MockCol(), "indexer_id": _MockCol(), "torrent_hash": _MockCol()})
    Indexer = type("Indexer", (_MockModel,), {"id": _MockCol(), "name": _MockCol(), "enable_seeding": _MockCol(), "seed_ratio_limit": _MockCol(), "seed_time_limit_hours": _MockCol()})
    TrackedRelease = type("TrackedRelease", (_MockModel,), {"id": _MockCol(), "show_id": _MockCol(), "indexer_id": _MockCol()})
from app.services.download_client import get_client
from app.services.postprocess import process_download, process_movie_download, VIDEO_EXTENSIONS
from app.services.release_log_service import log_release_event
from app.services.settings_service import get_or_create_settings
from app.services import blocklist_service

logger = logging.getLogger("aliasarr.downloads_monitor")

# Прогресс 100% для завершения раздачи
_COMPLETE_THRESHOLD = 1.0
_NOTIFIED_PENDING_SPECIALS: set[str] = set()
_RECONCILED_TORRENTS: set[str] = set()
_PENDING_MANUAL_IMPORT_TORRENTS: set[str] = set()


def mark_torrent_pending_manual_import(torrent_hash: str) -> None:
    """Регистрирует торрент как ожидающий ручного импорта.
    Фоновый монитор сидирования никогда не удалит файлы этого торрента до завершения импорта."""
    if torrent_hash:
        _PENDING_MANUAL_IMPORT_TORRENTS.add(torrent_hash.lower())


def unmark_torrent_pending_manual_import(torrent_hash: str) -> None:
    """Снимает защиту от удаления после успешного ручного импорта всех файлов."""
    if torrent_hash:
        _PENDING_MANUAL_IMPORT_TORRENTS.discard(torrent_hash.lower())


def is_torrent_pending_manual_import(torrent_hash: str) -> bool:
    """Проверяет, защищен ли торрент от удаления ради ручного импорта."""
    return bool(torrent_hash and torrent_hash.lower() in _PENDING_MANUAL_IMPORT_TORRENTS)


def clear_pending_manual_import_torrents() -> None:
    """Сбрасывает реестр (используется в тестах)."""
    _PENDING_MANUAL_IMPORT_TORRENTS.clear()



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
        aliases = build_alias_candidates(show)
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


async def _check_seeding_torrents(db: Session, active_clients: list[DownloadClient]) -> None:
    """
    Проверяет активные раздачи в торрент-клиентах, которые продолжают сидироваться после импорта.
    Когда раздача достигает лимита ratio или времени (заданных в настройках трекера / клиента)
    или завершается клиентом, раздача удаляется из клиента вместе с временными файлами из /data/downloads,
    ПРИ УСЛОВИИ, что для этой раздачи не осталось неимпортированных серий/спешлов, ожидающих ручного импорта.
    Файлы в медиатеке (хардлинки) остаются в 100% сохранности.
    """
    if not active_clients:
        return

    for dc_row in active_clients:
        try:
            client = get_client(dc_row)
            torrents = await client.list_torrents()
            for t in torrents:
                if not getattr(t, "hash", None):
                    continue
                th_lower = t.hash.lower()
                state_str = str(getattr(t, "state", "")).lower()

                # 1. Если торрент зарегистрирован в _PENDING_MANUAL_IMPORT_TORRENTS — строго запрещено удалять!
                if is_torrent_pending_manual_import(th_lower):
                    continue

                # 2. Проверяем, есть ли неимпортированные серии в статусе DOWNLOADING для этого torrent_hash
                pending_eps_count = 0
                try:
                    c_val = (
                        db.query(Episode)
                        .filter(
                            func.lower(Episode.torrent_hash) == th_lower,
                            Episode.status == EpisodeStatus.DOWNLOADING,
                        )
                        .count()
                    )
                    if isinstance(c_val, (int, float)):
                        pending_eps_count = int(c_val)
                except Exception:
                    pending_eps_count = 0

                if pending_eps_count > 0:
                    # Раздача содержит неимпортированные файлы (например, спешлы), ожидающие ручного импорта.
                    mark_torrent_pending_manual_import(th_lower)
                    continue

                # 3. Ищем запись в DownloadHistory или серии тайтла
                dh = (
                    db.query(DownloadHistory)
                    .filter(
                        func.lower(DownloadHistory.torrent_hash) == th_lower,
                    )
                    .order_by(DownloadHistory.id.desc())
                    .first()
                )
                show_id = dh.show_id if (dh and getattr(dh, "show_id", None)) else None
                if not show_id:
                    try:
                        any_ep = db.query(Episode).filter(func.lower(Episode.torrent_hash) == th_lower).first()
                        if any_ep:
                            show_id = any_ep.show_id
                    except Exception:
                        pass

                if show_id:
                    # Проверяем, есть ли у шоу неимпортированные спецвыпуски
                    try:
                        unimported_specials_count = (
                            db.query(Episode)
                            .filter(
                                Episode.show_id == show_id,
                                Episode.season_number == 0,
                                Episode.status.in_([EpisodeStatus.DOWNLOADING, EpisodeStatus.WANTED]),
                                Episode.file_path.is_(None),
                            )
                            .count()
                        )
                        if isinstance(unimported_specials_count, (int, float)) and unimported_specials_count > 0:
                            mark_torrent_pending_manual_import(th_lower)
                            continue
                    except Exception:
                        pass

                    # Проверяем наличие неимпортированных видеофайлов на диске в торренте
                    try:
                        settings = get_or_create_settings(db)
                        show_obj = db.get(Show, show_id)
                        if show_obj and hasattr(show_obj, "title"):
                            _, t_files = _resolve_torrent_files_and_path(t, settings, show_obj)
                            if t_files:
                                from app.services.postprocess import VIDEO_EXTENSIONS
                                video_t_files = [
                                    f for f in t_files
                                    if os.path.splitext(f)[1].lower() in VIDEO_EXTENSIONS and os.path.exists(f)
                                ]
                                if video_t_files:
                                    show_eps = (
                                        db.query(Episode)
                                        .filter(Episode.show_id == show_id, Episode.file_path.isnot(None))
                                        .all()
                                    )
                                    show_file_paths = [os.path.abspath(ep.file_path) for ep in show_eps if getattr(ep, "file_path", None)]

                                    def _file_is_imported(f_path: str) -> bool:
                                        f_abs = os.path.abspath(f_path)
                                        for lib_fp in show_file_paths:
                                            if f_abs == lib_fp:
                                                return True
                                            try:
                                                if os.path.exists(lib_fp) and os.path.samefile(f_abs, lib_fp):
                                                    return True
                                            except (OSError, ValueError):
                                                pass
                                        return False

                                    unimported_disk_files = [f for f in video_t_files if not _file_is_imported(f)]
                                    if unimported_disk_files:
                                        mark_torrent_pending_manual_import(th_lower)
                                        logger.info(
                                            "DownloadsMonitor: Раздача «%s» содержит %d неимпортированных видеофайлов на диске. "
                                            "Удаление заблокировано до завершения ручного импорта.",
                                            getattr(t, "name", t.hash), len(unimported_disk_files),
                                        )
                                        continue
                    except Exception as disk_chk_err:
                        logger.debug("DownloadsMonitor: Ошибка проверки файлов на диске: %s", disk_chk_err)

                indexer = db.get(Indexer, dh.indexer_id) if (dh and getattr(dh, "indexer_id", None)) else None
                if not indexer and show_id:
                    try:
                        tr = (
                            db.query(TrackedRelease)
                            .filter(TrackedRelease.show_id == show_id)
                            .order_by(TrackedRelease.id.desc())
                            .first()
                        )
                        if tr and getattr(tr, "indexer_id", None):
                            potential_idx = db.get(Indexer, tr.indexer_id)
                            if isinstance(potential_idx, Indexer):
                                indexer = potential_idx
                    except Exception:
                        pass

                is_seeding_enabled = bool(indexer and getattr(indexer, "enable_seeding", False))

                if not is_seeding_enabled:
                    # Если сидирование для трекера выключено (или трекер не задан), но раздача оставалась в клиенте
                    # ради ручного импорта (который теперь завершен — все серии импортированы):
                    has_downloaded_eps = False
                    try:
                        has_downloaded_eps = (
                            db.query(Episode)
                            .filter(
                                func.lower(Episode.torrent_hash) == th_lower,
                                Episode.status == EpisodeStatus.DOWNLOADED,
                            )
                            .count() > 0
                        )
                    except Exception:
                        has_downloaded_eps = False

                    if has_downloaded_eps:
                        try:
                            await client.remove_torrent(t.hash, delete_files=True)
                            logger.info(
                                "DownloadsMonitor: Раздача «%s» удалена из клиента после завершения всех импортов (сидирование отключено).",
                                getattr(t, "name", t.hash),
                            )
                        except Exception as rem_err:
                            logger.debug("DownloadsMonitor: Не удалось удалить завершенный торрент %s: %s", t.hash, rem_err)
                    continue

                # Проверяем лимиты для сидируемой раздачи
                ratio_limit = getattr(indexer, "seed_ratio_limit", None)
                time_hours_limit = getattr(indexer, "seed_time_limit_hours", None)
                current_ratio = getattr(t, "ratio", 0.0) or 0.0
                seeding_sec = getattr(t, "seeding_time", 0) or 0

                reached_ratio = ratio_limit is not None and ratio_limit > 0 and current_ratio >= ratio_limit
                reached_time = time_hours_limit is not None and time_hours_limit > 0 and seeding_sec >= (time_hours_limit * 3600)
                is_stopped_by_client = state_str in ("pausedup", "completed", "stopped", "finished", "seed_wait") and (
                    (ratio_limit is not None and current_ratio >= ratio_limit) or
                    (time_hours_limit is not None and seeding_sec >= (time_hours_limit * 3600)) or
                    (ratio_limit is None and time_hours_limit is None and (current_ratio >= 1.0 or seeding_sec > 0))
                )

                if reached_ratio or reached_time or is_stopped_by_client:
                    try:
                        await client.remove_torrent(t.hash, delete_files=True)
                        logger.info(
                            "DownloadsMonitor: Лимит сидирования достигнут для «%s» (ratio: %.2f/%s, время: %.1f/%sч). Раздача и временные файлы удалены.",
                            getattr(t, "name", t.hash), current_ratio, ratio_limit, seeding_sec / 3600, time_hours_limit,
                        )
                        show = db.get(Show, dh.show_id) if (dh and dh.show_id) else None
                        log_release_event(
                            stage="download",
                            level="success",
                            show_title=getattr(show, "title", None) if show else None,
                            show_id=dh.show_id if dh else None,
                            release_title=getattr(t, "name", t.hash),
                            indexer=getattr(indexer, "name", "Indexer"),
                            message=(
                                f"Сидирование раздачи «{getattr(t, 'name', t.hash)}» успешно завершено по достижению лимита "
                                f"(ratio: {current_ratio:.2f}{f'/{ratio_limit}' if ratio_limit else ''}, "
                                f"время: {seeding_sec / 3600:.1f}{f'/{time_hours_limit}' if time_hours_limit else ''} ч). "
                                "Временные файлы загрузки очищены, файлы в медиатеке в полной сохранности."
                            ),
                            details={
                                "torrent_hash": t.hash,
                                "ratio": current_ratio,
                                "ratio_limit": ratio_limit,
                                "seeding_hours": seeding_sec / 3600,
                                "time_hours_limit": time_hours_limit,
                            },
                            db=db,
                        )
                    except Exception as rem_err:
                        logger.debug("DownloadsMonitor: Не удалось удалить завершенный сидируемый торрент %s: %s", t.hash, rem_err)
        except Exception as exc:
            logger.debug("DownloadsMonitor: Ошибка в _check_seeding_torrents для %s: %s", dc_row.name, exc)


async def check_downloads(db: Session) -> list[dict]:
    settings = get_or_create_settings(db)
    downloading = (
        db.query(Episode)
        .filter(Episode.status == EpisodeStatus.DOWNLOADING, Episode.torrent_hash.isnot(None))
        .all()
    )

    # Собираем все торренты со всех активных загрузчиков
    active_clients = db.query(DownloadClient).filter(DownloadClient.enabled == True).all()  # noqa: E712
    if not active_clients:
        return []

    if not downloading:
        await _check_seeding_torrents(db, active_clients)
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
        th = getattr(ep, "torrent_hash", None)
        if th:
            episodes_by_hash.setdefault(th.lower(), []).append(ep)

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
                        if getattr(e, "torrent_hash", None) == torrent_hash or e.status in (EpisodeStatus.DOWNLOADING, EpisodeStatus.WANTED, EpisodeStatus.UNAIRED)
                    ] if all_show_eps else eps

                    t_name = getattr(full_t, "name", "") or getattr(t, "name", "") or ""

                    # Определение смещения и привязанного сезона сматченного алиаса
                    alias_offset = 0
                    scoped_season = None
                    if show_obj:
                        from app.services.matcher import build_alias_candidates, match_release
                        show_aliases = build_alias_candidates(show_obj, db=db)
                        m_res = match_release(
                            t_name,
                            show_obj.id,
                            show_aliases,
                            content_type=getattr(show_obj, "content_type", "series") or "series",
                        )
                        if m_res and m_res.matched and m_res.alias_candidate:
                            alias_offset = m_res.alias_candidate.episode_offset or 0
                            scoped_season = m_res.alias_candidate.season_number

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
                            torrent_name=t_name,
                            all_show_episodes=all_show_eps,
                            out_matched_episodes=matched_eps,
                            show_words=show_words,
                            alias_offset=alias_offset,
                            scoped_season=scoped_season,
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
                            if m_ep.status == EpisodeStatus.WANTED or (m_ep.status == EpisodeStatus.DOWNLOADING and not getattr(m_ep, "torrent_hash", None)):
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

                        if show_obj:
                            log_release_event(
                                stage="download",
                                level="warning",
                                show_title=show_obj.title,
                                show_id=show_obj.id,
                                release_title=getattr(t, "name", torrent_hash),
                                indexer="DownloadsMonitor",
                                message=f"Раздача «{getattr(t, 'name', torrent_hash)}» удалена из загрузчика и добавлена в черный список: файлы раздачи не содержат нужных серий для «{show_obj.title}». Запущен повторный автопоиск...",
                                details={"torrent_hash": torrent_hash, "reason": "Раздача не содержит ни одной нужной серии для тайтла"},
                                db=db,
                            )
                            # Запускаем автопоиск серий этого шоу в фоне
                            async def _trigger_auto_search(s_id: int, u_ids: set[int]):
                                try:
                                    from app.database import SessionLocal
                                    from app.services.auto_search import search_and_grab_show
                                    with SessionLocal() as s_session:
                                        r_show = s_session.get(Show, s_id)
                                        if r_show:
                                            await search_and_grab_show(s_session, r_show, episode_ids=u_ids if u_ids else None, wanted_only=True)
                                except Exception as retry_err:
                                    logger.debug("DownloadsMonitor: Ошибка повторного автопоиска: %s", retry_err)

                            uncovered_ids = {u.id for u in uncovered if getattr(u, "id", None)}
                            asyncio.create_task(_trigger_auto_search(show_obj.id, uncovered_ids))

                    if progress_changed:
                        db.commit()
                    eps = [e for e in all_show_eps if getattr(e, "torrent_hash", None) == torrent_hash and e.status == EpisodeStatus.DOWNLOADING]
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
            mark_torrent_pending_manual_import(torrent_hash)
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

                # Отправляем уведомление об успешном скачивании и импорте, либо очищаем отклонённый торрент
                imported_items = [r for r in (import_results or []) if r.get("status") == "imported" and r.get("dest")]

                # Определяем неимпортированные видеофайлы из результатов (например, спешлы или файлы без номера серии)
                from app.services.postprocess import VIDEO_EXTENSIONS
                unimported_video_results = [
                    r for r in (import_results or [])
                    if r.get("status") in ("skipped", "failed")
                    and os.path.splitext(r.get("file", ""))[1].lower() in VIDEO_EXTENSIONS
                    and not (
                        "уже скачана" in (r.get("reason") or "").lower()
                        or "лучшее качество" in (r.get("reason") or "").lower()
                    )
                ]

                # Проверяем, остались ли в базе серии со статусом DOWNLOADING для этого торрента
                pending_downloading_count = 0
                if show and torrent_hash:
                    try:
                        c_val = (
                            db.query(Episode)
                            .filter(
                                Episode.show_id == show.id,
                                Episode.status == EpisodeStatus.DOWNLOADING,
                                func.lower(Episode.torrent_hash) == torrent_hash.lower(),
                            )
                            .count()
                        )
                        if isinstance(c_val, (int, float)):
                            pending_downloading_count = int(c_val)
                    except Exception:
                        pending_downloading_count = 0

                if unimported_video_results and show and torrent_hash:
                    # Привязываем неимпортированные спецвыпуски шоу к этому торренту,
                    # чтобы в интерфейсе они отображались как 100% скачанные и готовые к ручному импорту,
                    # а не «в поиске», и фоновый монитор сидирования не удалил раздачу
                    show_specials = (
                        db.query(Episode)
                        .filter(
                            Episode.show_id == show.id,
                            Episode.season_number == 0,
                            Episode.status.in_([EpisodeStatus.WANTED, EpisodeStatus.UNAIRED, EpisodeStatus.DOWNLOADING]),
                        )
                        .all()
                    )
                    for sp_ep in show_specials:
                        if not getattr(sp_ep, "file_path", None):
                            sp_ep.status = EpisodeStatus.DOWNLOADING
                            sp_ep.torrent_hash = torrent_hash
                            sp_ep.download_progress = 1.0
                            if dc_row:
                                sp_ep.download_client_id = dc_row.id
                            db.add(sp_ep)
                    if show_specials:
                        progress_changed = True
                        db.commit()
                        pending_downloading_count = len(show_specials)

                has_pending_eps = pending_downloading_count > 0
                has_unimported_content = bool(unimported_video_results or has_pending_eps)

                if has_unimported_content and torrent_hash:
                    mark_torrent_pending_manual_import(torrent_hash)

                if imported_items:
                    from app.services.notifications import notify_all
                    has_upgrade = any(r.get("is_upgrade") for r in imported_items)
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
                    if has_unimported_content:
                        header += " (часть файлов ожидает ручного сопоставления)"

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
                    if has_unimported_content:
                        # Файлы скачаны, но не удалось автоматически сопоставить серии (например, спецвыпуски или нестандартные имена).
                        # Раздачу НЕ удаляем, в черный список НЕ добавляем, серии НЕ сбрасываем.
                        t_task.complete(f"Скачано файлов: {len(unimported_video_results)} (ожидают сопоставления в «Ручном импорте»)")
                        log_release_event(
                            stage="import",
                            level="warning",
                            show_title=show.title if show else None,
                            show_id=show.id if show else None,
                            release_title=getattr(torrent_obj, "name", torrent_hash),
                            indexer="DownloadsMonitor",
                            message=(
                                f"Раздача «{getattr(torrent_obj, 'name', torrent_hash)}» скачана, но файлы требуют ручного сопоставления "
                                f"({len(unimported_video_results)} видеофайлов). Раздача сохранена в папке загрузок."
                            ),
                            details={"torrent_hash": torrent_hash, "unimported_files": [r.get("file") for r in unimported_video_results]},
                            db=db,
                        )
                    else:
                        t_task.complete("Нет новых файлов для импорта")
                        today = dt.date.today()
                        skip_reasons = [r.get("reason") for r in (import_results or []) if r.get("reason")]
                        primary_reason = skip_reasons[0] if skip_reasons else "Раздача не содержала подходящих серий или качество хуже имеющегося"

                        for ep in eps:
                            ep_status = getattr(ep, "status", None)
                            ep_th = getattr(ep, "torrent_hash", None)
                            if ep_status == EpisodeStatus.DOWNLOADING and (
                                not ep_th or (torrent_hash and ep_th.lower() == torrent_hash.lower())
                            ):
                                fp = getattr(ep, "file_path", None)
                                has_existing_file = bool(fp and os.path.exists(fp))
                                if has_existing_file:
                                    ep.status = EpisodeStatus.DOWNLOADED
                                    ep.download_progress = 0.0
                                    ep.torrent_hash = None
                                    ep.download_client_id = None
                                    ep.upgrade_requested = False
                                    db.add(ep)
                                else:
                                    air_d = getattr(ep, "air_date", None)
                                    if isinstance(air_d, dt.datetime):
                                        air_d = air_d.date()
                                    ep.status = EpisodeStatus.UNAIRED if (air_d and air_d > today) else EpisodeStatus.WANTED
                                    ep.torrent_hash = None
                                    ep.download_client_id = None
                                    ep.download_progress = 0.0
                                    db.add(ep)

                        if show:
                            try:
                                remaining_upg = (
                                    db.query(Episode)
                                    .filter(Episode.show_id == show.id, Episode.upgrade_requested == True)
                                    .count()
                                )
                                if isinstance(remaining_upg, int) and remaining_upg == 0 and getattr(show, "upgrade_requested", False):
                                    show.upgrade_requested = False
                                    db.add(show)
                            except Exception:
                                pass

                        try:
                            blocklist_service.add_to_blocklist(
                                db,
                                release_title=getattr(torrent_obj, "name", torrent_hash),
                                reason=f"Отклонено при импорте: {primary_reason}",
                                show=show,
                                show_id=show.id if show else None,
                                torrent_hash=torrent_hash,
                                size=getattr(torrent_obj, "size", None),
                            )
                        except Exception as b_err:
                            logger.debug("DownloadsMonitor: Не удалось добавить раздачу %s в черный список: %s", torrent_hash, b_err)
                        try:
                            client = get_client(dc_row)
                            await client.remove_torrent(torrent_hash, delete_files=True)
                            logger.info(
                                "DownloadsMonitor: Раздача %s не содержала новых/лучших файлов для «%s» (%s), удалена из клиента и добавлена в черный список.",
                                torrent_hash, show.title if show else "show", primary_reason,
                            )
                        except Exception as rem_err:
                            logger.debug("DownloadsMonitor: Не удалось удалить ненужную раздачу %s: %s", torrent_hash, rem_err)

                        if show:
                            log_release_event(
                                stage="import",
                                level="warning",
                                show_title=show.title,
                                show_id=show.id,
                                release_title=getattr(torrent_obj, "name", torrent_hash),
                                indexer="DownloadsMonitor",
                                message=f"Раздача «{getattr(torrent_obj, 'name', torrent_hash)}» отклонена и добавлена в черный список: {primary_reason}. Запущен повторный автопоиск...",
                                details={"torrent_hash": torrent_hash, "reason": primary_reason},
                                db=db,
                            )
                            # Запускаем повторный автопоиск для поиска подходящего релиза
                            async def _trigger_auto_search_after_import_skip(s_id: int, ep_ids: set[int]):
                                try:
                                    from app.database import SessionLocal
                                    from app.services.auto_search import search_and_grab_show
                                    with SessionLocal() as s_session:
                                        r_show = s_session.get(Show, s_id)
                                        if r_show:
                                            await search_and_grab_show(s_session, r_show, episode_ids=ep_ids if ep_ids else None, wanted_only=True)
                                except Exception as retry_err:
                                    logger.debug("DownloadsMonitor: Ошибка повторного автопоиска: %s", retry_err)

                            wanted_reset_ids = {e.id for e in eps if getattr(e, "id", None) and e.status in (EpisodeStatus.WANTED, EpisodeStatus.UNAIRED)}
                            asyncio.create_task(_trigger_auto_search_after_import_skip(show.id, wanted_reset_ids))

                # Проверка сидирования и лимитов раздачи ПОСЛЕ завершения импорта
                if imported_items or has_unimported_content:
                    indexer_row = None
                    if torrent_hash:
                        try:
                            dh = (
                                db.query(DownloadHistory)
                                .filter(
                                    func.lower(DownloadHistory.torrent_hash) == torrent_hash.lower(),
                                    DownloadHistory.indexer_id.isnot(None),
                                )
                                .order_by(DownloadHistory.id.desc())
                                .first()
                            )
                            if dh and getattr(dh, "indexer_id", None):
                                potential_idx = db.get(Indexer, dh.indexer_id)
                                if isinstance(potential_idx, Indexer):
                                    indexer_row = potential_idx
                        except Exception:
                            pass

                    if not indexer_row and show:
                        try:
                            tr = (
                                db.query(TrackedRelease)
                                .filter(TrackedRelease.show_id == show.id)
                                .order_by(TrackedRelease.id.desc())
                                .first()
                            )
                            if tr and getattr(tr, "indexer_id", None):
                                potential_idx = db.get(Indexer, tr.indexer_id)
                                if isinstance(potential_idx, Indexer):
                                    indexer_row = potential_idx
                        except Exception:
                            pass

                    is_seeding_enabled = bool(indexer_row and getattr(indexer_row, "enable_seeding", False))
                    state_str = str(getattr(torrent_obj, "state", "")).lower()

                    if has_unimported_content:
                        # ЗАЩИТА: В раздаче остались неимпортированные файлы (спешлы / ручной импорт).
                        # НЕ удаляем раздачу и файлы из папки загрузок!
                        mark_torrent_pending_manual_import(torrent_hash)
                        try:
                            client = get_client(dc_row)
                            if not is_seeding_enabled and hasattr(client, "pause_torrent"):
                                await client.pause_torrent(torrent_hash)
                        except Exception as p_err:
                            logger.debug("DownloadsMonitor: Не удалось приостановить раздачу %s: %s", torrent_hash, p_err)

                        logger.info(
                            "DownloadsMonitor: В раздаче «%s» остались неимпортированные файлы (%d файлов, %d ожидающих серий). Файлы сохранены в папке загрузок.",
                            getattr(torrent_obj, "name", torrent_hash), len(unimported_video_results), pending_downloading_count,
                        )
                        log_release_event(
                            stage="import",
                            level="warning",
                            show_title=show.title if show else None,
                            show_id=show.id if show else None,
                            release_title=getattr(torrent_obj, "name", torrent_hash),
                            indexer="DownloadsMonitor",
                            message=(
                                f"В раздаче «{getattr(torrent_obj, 'name', torrent_hash)}» остались неимпортированные видеофайлы "
                                f"({len(unimported_video_results)} шт., например спецвыпуски). Раздача и файлы в папке загрузки сохранены "
                                f"для сопоставления в «Ручном импорте»."
                            ),
                            details={
                                "torrent_hash": torrent_hash,
                                "unimported_files": [r.get("file") for r in unimported_video_results],
                                "pending_downloading_eps": pending_downloading_count,
                            },
                            db=db,
                        )
                    elif is_seeding_enabled:
                        # Сидирование включено для этого трекера
                        ratio_lim = getattr(indexer_row, "seed_ratio_limit", None)
                        time_hrs_lim = getattr(indexer_row, "seed_time_limit_hours", None)
                        curr_ratio = getattr(t, "ratio", 0.0) or 0.0
                        seeding_sec = getattr(t, "seeding_time", 0) or 0

                        reached_ratio = ratio_lim is not None and ratio_lim > 0 and curr_ratio >= ratio_lim
                        reached_time = time_hrs_lim is not None and time_hrs_lim > 0 and seeding_sec >= (time_hrs_lim * 3600)
                        is_stopped = state_str in ("pausedup", "completed", "stopped", "finished", "seed_wait") and (
                            (ratio_lim is not None and curr_ratio >= ratio_lim) or
                            (time_hrs_lim is not None and seeding_sec >= (time_hrs_lim * 3600)) or
                            (ratio_lim is None and time_hrs_lim is None and (curr_ratio >= 1.0 or seeding_sec > 0))
                        )

                        if reached_ratio or reached_time or is_stopped:
                            try:
                                client = get_client(dc_row)
                                await client.remove_torrent(torrent_hash, delete_files=True)
                                logger.info(
                                    "DownloadsMonitor: Лимит сидирования достигнут для «%s» сразу после импорта (ratio: %.2f/%s). Раздача удалена.",
                                    getattr(t, "name", torrent_hash), curr_ratio, ratio_lim,
                                )
                            except Exception as rem_e:
                                logger.debug("DownloadsMonitor: Ошибка удаления завершенного сидирования %s: %s", torrent_hash, rem_e)
                        else:
                            logger.info(
                                "DownloadsMonitor: Раздача «%s» успешно импортирована и продолжает сидироваться (трекер: %s, ratio лимит: %s, время: %sч).",
                                getattr(t, "name", torrent_hash), getattr(indexer_row, "name", "Indexer"), ratio_lim, time_hrs_lim,
                            )
                    elif indexer_row is not None:
                        # Сидирование для данного трекера явно отключено -> удаляем торрент из клиента
                        try:
                            client = get_client(dc_row)
                            await client.remove_torrent(torrent_hash, delete_files=True)
                            logger.info("DownloadsMonitor: Раздача %s удалена из клиента после импорта (сидирование отключено).", torrent_hash)
                        except Exception as rem_e:
                            logger.debug("DownloadsMonitor: Ошибка удаления торрента %s после импорта: %s", torrent_hash, rem_e)
                    else:
                        # Трекер не привязан: проверяем общие настройки клиента dc_row (seed_time_limit / seed_ratio_limit)
                        dc_time_limit_min = getattr(dc_row, "seed_time_limit", None)
                        dc_ratio_limit = getattr(dc_row, "seed_ratio_limit", None)
                        if dc_time_limit_min is not None or dc_ratio_limit is not None:
                            seeding_sec = getattr(t, "seeding_time", 0) or 0
                            curr_ratio = getattr(t, "ratio", 0.0) or 0.0
                            time_reached = (dc_time_limit_min is not None and dc_time_limit_min > 0 and seeding_sec >= dc_time_limit_min * 60) or (dc_time_limit_min == 0)
                            ratio_reached = (dc_ratio_limit is not None and dc_ratio_limit > 0 and curr_ratio >= dc_ratio_limit)
                            if time_reached or ratio_reached:
                                try:
                                    client = get_client(dc_row)
                                    if hasattr(client, "pause_torrent"):
                                        await client.pause_torrent(torrent_hash)
                                    else:
                                        await client.remove_torrent(torrent_hash, delete_files=True)
                                    logger.info("Торрент %s достиг лимита раздачи клиента (%s мин / ratio %s).", torrent_hash, dc_time_limit_min, dc_ratio_limit)
                                except Exception as e:
                                    logger.debug("DownloadsMonitor: Не удалось остановить торрент %s: %s", torrent_hash, e)
                        else:
                            try:
                                client = get_client(dc_row)
                                await client.remove_torrent(torrent_hash, delete_files=True)
                                logger.info("DownloadsMonitor: Раздача %s удалена из клиента после импорта (сидирование отключено).", torrent_hash)
                            except Exception as rem_e:
                                logger.debug("DownloadsMonitor: Ошибка удаления торрента %s после импорта: %s", torrent_hash, rem_e)

            except Exception as exc:
                logger.exception("Ошибка постобработки для видео %s: %s", show.id, exc)
                t_task.fail(error=str(exc))
            finally:
                _RECONCILED_TORRENTS.discard(torrent_hash)

    if active_clients:
        await _check_seeding_torrents(db, active_clients)

    if progress_changed or results:
        try:
            db.commit()
        except Exception:
            db.rollback()

    return results
