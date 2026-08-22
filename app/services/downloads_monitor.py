"""
Мониторинг активных загрузок в торрент-клиентах и автоматический импорт завершённых файлов.

Фоновый процесс:
1. Опрашивает торрент-клиенты по сохранённому torrent_hash активных загрузок
2. Обновляет процент выполнения для отображения прогресса в интерфейсе
3. При завершении загрузки (100% / seeding) выполняет переименование и перемещение файлов в библиотеку
4. Переводит статус в DOWNLOADED и отправляет уведомление о завершении импорта
"""

from __future__ import annotations

import asyncio
import logging
import os

try:
    from sqlalchemy.orm import Session
    from app.database import SessionLocal
    from app.models.db import DownloadClient, Episode, EpisodeStatus, Show
except ImportError:
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
from app.services.settings_service import get_or_create_settings

logger = logging.getLogger("aliasarr.downloads_monitor")

# Прогресс 100% для завершения раздачи
_COMPLETE_THRESHOLD = 1.0


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


def _resolve_torrent_files_and_path(t, settings, show: Show | None = None) -> tuple[str, list[str]]:
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
    specific_files: list[str] | None = None,
    torrent_hash: str | None = None,
) -> list[dict]:
    """Выполняет перемещение файлов и обновление БД в отдельном потоке,
    чтобы не блокировать asyncio event loop и веб-интерфейс GUI."""
    thread_db = SessionLocal()
    try:
        show_obj = thread_db.get(Show, show_id)
        if not show_obj:
            return []
        if is_movie:
            return process_movie_download(
                thread_db, show_obj, download_path, template, root_folder, specific_files=specific_files,
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
            # Торрент действительно удален из загрузчика: сбрасываем в WANTED / UNAIRED
            import datetime as dt
            today = dt.date.today()
            for ep in eps:
                if ep.status == EpisodeStatus.DOWNLOADING:
                    ep.torrent_hash = None
                    ep.download_client_id = None
                    ep.download_progress = 0.0
                    air_d = ep.air_date
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

        for ep in eps:
            if abs((ep.download_progress or 0) - t.progress) > 0.001:
                ep.download_progress = t.progress
                progress_changed = True
            if not ep.download_client_id:
                ep.download_client_id = dc_row.id
                progress_changed = True
            db.add(ep)

        state_str = str(t.state).lower()
        _DOWNLOADING_STATES = {
            "downloading", "stalleddl", "forceddl", "queueddl", "checkingdl",
            "allocating", "metadl", "moving", "4", "checking", "check pending",
            "download", "download_wait", "check_wait", "stopped", "paused",
            "0", "1", "2", "3",
        }
        _SEEDING_COMPLETED_STATES = {
            "completed", "seeding", "pausedup", "stalledup", "forcedup",
            "queuedup", "uploading", "100%", "finished", "seed", "complete", "6", "5",
        }

        # Раздача завершена ТОЛЬКО если прогресс >= 0.999 (100%). Никакого импорта при progress < 100%!
        if state_str in _DOWNLOADING_STATES:
            is_done = False
        elif state_str in _SEEDING_COMPLETED_STATES:
            is_done = (t.progress >= 0.999)
        else:
            is_done = (t.progress >= 0.999)

        if not is_done:
            continue

        # Проверка лимита времени раздачи (Seed Time Limit / Ratio Limit)
        seed_time_limit_min = getattr(dc_row, "seed_time_limit", None)
        seed_ratio_limit = getattr(dc_row, "seed_ratio_limit", None)
        is_actively_seeding = state_str in ("seeding", "uploading", "forcedup", "queuedup", "stalledup", "seed")

        if is_actively_seeding:
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
            if has_any_limit:
                if not (time_reached or ratio_reached):
                    # Торрент ещё раздаётся для выполнения установленного лимита
                    continue
                else:
                    # Лимит времени или ratio достигнут — останавливаем раздачу
                    try:
                        client = get_client(dc_row)
                        await client.pause_torrent(torrent_hash)
                        logger.info(
                            "Торрент %s достиг лимита раздачи (%s мин / ratio %s). Раздача остановлена перед импортом.",
                            torrent_hash, seed_time_limit_min, seed_ratio_limit,
                        )
                    except Exception as e:
                        logger.debug("Не удалось поставить торрент %s на паузу: %s", torrent_hash, e)

        show = db.get(Show, eps[0].show_id)
        if not show:
            continue

        root_folder, template, season_template = _folder_and_template(settings, show.content_type)
        from app.services.task_manager import task_manager
        async with task_manager.track(
            name="import_files",
            title=f"Импорт и перенос: {show.title}",
            message=f"Перемещение и переименование файлов для «{show.title}»...",
        ) as t_task:
            try:
                # Запрашиваем полные метаданные и список файлов торрента из клиента
                full_torrent = None
                try:
                    client = get_client(dc_row)
                    full_torrent = await client.get_torrent(torrent_hash)
                except Exception as exc:
                    logger.debug("Не удалось получить детальные файлы торрента %s: %s", torrent_hash, exc)

                torrent_obj = full_torrent or t
                download_path, specific_files = _resolve_torrent_files_and_path(torrent_obj, settings, show)

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
                )
                results.append({"show_id": show.id, "torrent_hash": torrent_hash, "imported": import_results})

                # Обновляем статусы в текущей сессии db для сматченных серий
                for ep in eps:
                    try:
                        db.refresh(ep)
                    except Exception:
                        pass

                # Отправляем уведомление об успешном скачивании и импорте
                if import_results:
                    from app.services.notifications import notify_all
                    imported_items = [r for r in import_results if r.get("status") == "imported" and r.get("dest")]
                    has_upgrade = any(r.get("is_upgrade") for r in import_results)
                    header = (
                        f"Релиз скачан и произведена замена старого на новый: «{show.title}»"
                        if has_upgrade
                        else f"Релиз скачан и перенесен: «{show.title}»"
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

            except Exception as exc:
                logger.exception("Ошибка постобработки для видео %s: %s", show.id, exc)
                t_task.fail(error=str(exc))

    if progress_changed or results:
        try:
            db.commit()
        except Exception:
            db.rollback()

    return results
