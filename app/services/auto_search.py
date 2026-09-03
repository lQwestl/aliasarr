"""
Автоматический поиск, сопоставление и отправка в загрузчик разыскиваемых серий и фильмов (WANTED / Upgrades).

Фоновый процесс:
1. Находит все Episode со статусом WANTED у мониторящихся тайтлов
2. Ищет релизы по настроенным алиасам во всех активных индексаторах с учётом приоритетов
3. Сопоставляет релизы с тайтлом (matcher.py), фильтрует по профилю качества и числу сидов
4. Группирует кандидатов с защитой от дублирования раздач
5. Отправляет лучший релиз в торрент-клиент и переводит статус серий в DOWNLOADING
6. Создаёт записи в истории загрузок и отправляет уведомления
"""

from __future__ import annotations

from typing import Optional, List, Dict, Any

import asyncio
import datetime as dt
import logging
import os
import re
import uuid

try:
    from sqlalchemy import and_, or_
    from sqlalchemy.orm import Session
    from app.models.db import (
        DownloadClient,
        DownloadHistory,
        Episode,
        EpisodeStatus,
        Indexer,
        QualityProfile,
        Show,
        TrackedRelease,
    )
except ImportError:
    and_ = None
    or_ = None
    Session = object
    DownloadClient = None
    DownloadHistory = None
    Episode = None
    EpisodeStatus = type("EpisodeStatus", (), {"DOWNLOADED": "downloaded", "WANTED": "wanted", "DOWNLOADING": "downloading", "IGNORED": "ignored", "MISSING": "missing", "UNAIRED": "unaired"})
    Indexer = None
    QualityProfile = None
    Show = None
    TrackedRelease = None

from app.services.download_client import get_client
from app.services.matcher import build_alias_candidates, match_release, score_candidate
from app.services.notifications import notify_all
from app.services.parser import ReleaseKind, detect_season_label, parse_episode
from app.services.quality import is_allowed, parse_quality
from app.services.indexer_service import get_indexer_client
from app.services.release_log_service import log_release_event
from app.services.settings_service import get_or_create_settings
from app.services.torznab import TorznabClient

logger = logging.getLogger("aliasarr.auto_search")

# Кэш хэшей раздач по ID тайтла, которые были признаны неподходящими (например, внутри торрента отсутствуют нужные серии)
_SHOW_REJECTED_HASHES: dict[int, set[str]] = {}


def add_rejected_release_for_show(show_id: int, identifier: str) -> None:
    if show_id and identifier:
        _SHOW_REJECTED_HASHES.setdefault(show_id, set()).add(identifier.lower())


def is_release_rejected_for_show(
    show_id: int,
    infohash: Optional[str] = None,
    guid: Optional[str] = None,
    download_url: Optional[str] = None,
    title: Optional[str] = None,
) -> bool:
    if not show_id or show_id not in _SHOW_REJECTED_HASHES:
        return False
    rejected = _SHOW_REJECTED_HASHES[show_id]
    if infohash and infohash.lower() in rejected:
        return True
    if guid and str(guid).lower() in rejected:
        return True
    if download_url and str(download_url).lower() in rejected:
        return True
    if title and title.lower().strip() in rejected:
        return True
    return False


def clear_rejected_cache_for_show(show_id: int) -> None:
    if show_id:
        _SHOW_REJECTED_HASHES.pop(show_id, None)


def _get_show_max_season(db: Session, show: Show) -> int:
    """Возвращает максимальный номер сезона среди всех серий шоу в БД.
    Возвращает 1, если серий нет (безопасный дефолт)."""
    from sqlalchemy import func as _func
    result = db.query(_func.max(Episode.season_number)).filter(Episode.show_id == show.id).scalar()
    return result or 1


def evaluate_torrent_file_priority(
    file_name: str,
    file_index: int,
    target_episodes: list[Episode],
    import_extra_files: bool = True,
    extra_extensions: Optional[set[str]] = None,
    content_type: str = "series",
    ova_mode: str = "auto",
    torrent_name: str = "",
) -> int:
    """
    Определяет приоритет скачивания файла торрента (1 = скачивать, 0 = не скачивать).
    Учитывает:
    - Для фильмов (content_type == "movie"): все видеофайлы и сопутствующие файлы скачиваются.
    - Для сериалов/аниме:
      - Сезон и номер серии (season_number, episode_number)
      - Абсолютную / сквозную нумерацию (absolute_number), актуально для мультсериалов и аниме
      - Формат 3-4 цифры (501 -> S05E01)
      - Имя торрента (torrent_name) при отсутствии явного сезона в имени файла
      - Дополнительные файлы: субтитры (.ass/.srt), аудиодорожки (.mka), шрифты (Fonts/ .ttf/.otf), NFO.
    """
    import os
    import re

    AUDIO_EXTS = {".mka", ".aac", ".ac3", ".dts", ".eac3", ".flac", ".mp3", ".m4a", ".wav", ".opus"}
    FONT_EXTS = {".ttf", ".otf", ".ttc", ".woff", ".woff2", ".eot"}
    SUB_EXTS = {".srt", ".ass", ".sub", ".idx", ".vtt", ".nfo"}
    ALL_EXTRA_EXTS = SUB_EXTS | AUDIO_EXTS | FONT_EXTS

    if extra_extensions is None:
        extra_extensions = set(ALL_EXTRA_EXTS)
    else:
        extra_extensions = set(extra_extensions) | ALL_EXTRA_EXTS

    file_name = file_name.replace("\\", "/")
    ext = os.path.splitext(file_name)[1].lower()
    fname_lower = file_name.lower()

    # Для фильмов: все видеофайлы скачиваются (приоритет 1). Исключаются только сэмплы.
    if content_type == "movie":
        if ext in {".mkv", ".mp4", ".avi", ".ts", ".m2ts", ".mov", ".webm"}:
            if "/sample" in fname_lower or fname_lower.endswith("-sample.mkv"):
                return 0
            return 1
        if ext in extra_extensions or "/fonts/" in fname_lower or fname_lower.startswith("fonts/") or "/attachments/" in fname_lower:
            return 1 if import_extra_files else 0
        return 0

    # 1. Шрифты для субтитров аниме и сериалов — всегда оставляем, если включен импорт доп. файлов
    if ext in FONT_EXTS or "/fonts/" in fname_lower or fname_lower.startswith("fonts/") or "/attachments/" in fname_lower:
        return 1 if import_extra_files else 0

    # Проверяем, является ли это папкой с аудио/озвучкой/звуком (Sound [...], Audio [...], Озвучка [...], Звук [...], OST)
    is_audio_folder = any(
        kw in fname_lower for kw in (
            "/sound", "sound/", "/audio", "audio/", "/озвучк", "озвучк/", "/звук", "звук/", "/ost", "ost/", "/soundtrack", "soundtrack/"
        )
    )

    target_keys = {(ep.season_number, ep.episode_number) for ep in target_episodes}
    target_abs = {ep.absolute_number for ep in target_episodes if ep.absolute_number is not None}
    target_seasons = {ep.season_number for ep in target_episodes}
    has_wanted_specials = any(ep.season_number == 0 for ep in target_episodes)

    base_name = os.path.basename(file_name)
    dir_name = os.path.dirname(file_name)

    # 1. Сначала разбираем имя самого файла (basename)
    parsed = parse_episode(base_name)
    episodes = parsed.episodes if (parsed and parsed.episodes) else []
    season = parsed.season if (parsed and parsed.season is not None) else None

    # Проверяем, находится ли файл в подпапке Part 2 / Cour 2 / Сезон X
    is_part_2 = False
    if dir_name:
        dir_lower = dir_name.lower()
        if re.search(r"\b(?:part|часть|cour|кур)\s*2\b", dir_lower):
            is_part_2 = True
        if season is None:
            dir_parsed = parse_episode(dir_name)
            if dir_parsed and dir_parsed.season is not None:
                season = dir_parsed.season
            else:
                s_lbl = detect_season_label(dir_name)
                if s_lbl["type"] == "numbered":
                    season = s_lbl["season"]

    # Если сезон не определен ни из basename, ни из dir_name, пробуем определить из torrent_name
    if season is None and torrent_name:
        t_parsed = parse_episode(torrent_name)
        if t_parsed and t_parsed.season is not None:
            season = t_parsed.season
        else:
            s_lbl = detect_season_label(torrent_name)
            if s_lbl["type"] == "numbered":
                season = s_lbl["season"]

    # Если в basename номер серии не найден, пробуем по полному относительному пути
    if not episodes:
        parsed_full = parse_episode(file_name)
        if parsed_full and parsed_full.episodes:
            episodes = parsed_full.episodes
            if season is None and parsed_full.season is not None:
                season = parsed_full.season

    is_special_file = (
        (parsed and (parsed.season == 0 or parsed.matched_pattern in ("season_pack:ova_ona", "leading_num_special"))) or
        any(kw in base_name.lower() for kw in ("ova", "ona", "oad", "special", "specials", "спешл", "sp", "bonus")) or
        (episodes and 0 in episodes)
    )

    # 2. Не-видео файлы (субтитры, аудиодорожки, nfo, папки Sound / Audio / OST)
    if ext in extra_extensions or is_audio_folder:
        if not import_extra_files:
            return 0
        if not episodes:
            # Общие субтитры/аудио/nfo без явного номера серии в названии (например, общая папка Sound / Subs / OST)
            return 1

        for ep_num in episodes:
            if 101 <= ep_num <= 9999:
                s_div, e_mod = divmod(ep_num, 100)
                if (s_div, e_mod) in target_keys:
                    return 1

            if is_special_file:
                allow_ova_as_s1 = (ova_mode == "season_1") or (
                    ova_mode == "auto" and not has_wanted_specials and any(sn == 1 for sn, _ in target_keys)
                )
                if allow_ova_as_s1 and ((1, ep_num) in target_keys or ep_num in target_abs):
                    return 1
                if (0, ep_num) in target_keys or has_wanted_specials:
                    return 1
            elif season is not None:
                if season in target_seasons:
                    if (season, ep_num) in target_keys:
                        return 1
                    if ep_num in target_abs:
                        return 1
                    if is_part_2 and 1 <= ep_num <= 12:
                        if (season, ep_num + 12) in target_keys:
                            return 1
            else:
                if ep_num in target_abs:
                    return 1
                for s in target_seasons:
                    if s > 0 and (s, ep_num) in target_keys:
                        return 1
                if is_part_2 and 1 <= ep_num <= 12:
                    for s in target_seasons:
                        if s > 0 and ((s, ep_num + 12) in target_keys or (ep_num + 12) in target_abs):
                            return 1
        return 0

    # 3. Видеофайлы (.mkv, .mp4, .avi, .ts, etc.)
    if ext in {".mkv", ".mp4", ".avi", ".ts", ".m2ts", ".mov", ".webm"}:
        if is_special_file:
            allow_ova_as_s1 = (ova_mode == "season_1") or (
                ova_mode == "auto" and not has_wanted_specials and any(sn == 1 for sn, _ in target_keys)
            )
            if allow_ova_as_s1 and episodes:
                for ep_num in episodes:
                    if (1, ep_num) in target_keys or ep_num in target_abs:
                        return 1
            if not has_wanted_specials:
                return 0
            if episodes:
                for ep_num in episodes:
                    if (0, ep_num) in target_keys:
                        return 1
            # Если OVA/Special без явного номера серии в названии (например 'Dakara Boku wa, H ga Dekinai - OVA.avi')
            return 1 if has_wanted_specials else 0

        # Основной сезон (Season 1..N)
        if not episodes:
            # Если не удалось спарсить номер серии, но разыскивается 1 серия и в имени нет чужих меток
            if len(target_episodes) == 1 and not re.search(r"\bs\d+|\be\d+|\bep\d+", fname_lower):
                return 1
            return 0

        for ep_num in episodes:
            # 1. Формат 3-4 цифры (501 -> Сезон 5 Серия 1, 1204 -> Сезон 12 Серия 4)
            if 101 <= ep_num <= 9999:
                s_div, e_mod = divmod(ep_num, 100)
                if (s_div, e_mod) in target_keys:
                    return 1

            # 2. При известном сезоне (проверяем только если сезон среди разыскиваемых)
            if season is not None:
                if season in target_seasons:
                    if (season, ep_num) in target_keys:
                        return 1
                    if ep_num in target_abs:
                        return 1
                    if is_part_2 and 1 <= ep_num <= 12:
                        if (season, ep_num + 12) in target_keys:
                            return 1
            else:
                # 3. Если сезон не указан явно в имени файла, сопоставляем по сквозной нумерации или регулярным сезонам (s > 0)
                if ep_num in target_abs:
                    return 1
                for s in target_seasons:
                    if s > 0 and (s, ep_num) in target_keys:
                        return 1
                if is_part_2 and 1 <= ep_num <= 12:
                    for s in target_seasons:
                        if s > 0 and ((s, ep_num + 12) in target_keys or (ep_num + 12) in target_abs):
                            return 1
        return 0

    # Все прочие неизвестные файлы
    return 0


async def _ensure_movie_files_wanted(dl_client, torrent_hash: str) -> None:
    """Гарантирует, что для фильма в Transmission / qBittorrent / Deluge включены все видеофайлы и субтитры (галочки проставлены)."""
    import os
    for attempt in range(15):
        try:
            torrent = await dl_client.get_torrent(torrent_hash)
            if torrent and torrent.files:
                allowed_exts = {
                    ".mkv", ".mp4", ".avi", ".ts", ".m2ts", ".mov", ".webm",
                    ".srt", ".ass", ".sub", ".idx", ".vtt", ".nfo",
                    ".mka", ".aac", ".ac3", ".dts", ".eac3", ".flac", ".mp3", ".m4a", ".wav", ".opus",
                    ".ttf", ".otf", ".ttc"
                }
                wanted_indices = []
                for f in torrent.files:
                    f_ext = os.path.splitext(f.name)[1].lower()
                    f_name_lower = f.name.lower().replace("\\", "/")
                    if f_ext in allowed_exts:
                        if not ("/sample" in f_name_lower or f_name_lower.endswith("-sample.mkv")):
                            wanted_indices.append(f.index)
                if not wanted_indices:
                    wanted_indices = [f.index for f in torrent.files]
                await dl_client.set_file_priorities(torrent_hash, wanted_indices, 1)
                try:
                    await dl_client.recheck_torrent(torrent_hash)
                except Exception:
                    pass
                await dl_client.resume_torrent(torrent_hash)
                logger.info("Для фильма в торренте %s успешно включены все файлы (%d шт) и возобновлено скачивание", torrent_hash, len(wanted_indices))
                return
        except Exception as exc:
            logger.debug("Ожидание метаданных торрента фильма %s: %s", torrent_hash, exc)
        await asyncio.sleep(1.5)


async def _limit_torrent_files_to_episodes(
    dl_client,
    torrent_hash: str,
    wanted_episodes: list[Episode],
    db: Session = None,
    explicit_episode_ids: Optional[set[int]] = None,
    content_type: str = "series",
) -> None:
    """Выключает в загрузчике файлы, не относящиеся к переданным сериям (Sonarr selective download).
    
    Гарантирует, что полный пак или сезонный батч не будет качать чужие сезоны/серии."""
    if content_type == "movie":
        # Для фильмов гарантируем, что все файлы фильма включены (галочки стоят)
        await _ensure_movie_files_wanted(dl_client, torrent_hash)
        return

    target_eps = [
        ep for ep in wanted_episodes
        if explicit_episode_ids is None or ep.id in explicit_episode_ids
    ]
    if not target_eps:
        target_eps = wanted_episodes

    torrent = None
    for attempt in range(40):  # до ~60 секунд ожидания метаданных торрента
        try:
            torrent = await dl_client.get_torrent(torrent_hash)
            if torrent and torrent.files:
                break
        except Exception:
            pass
        await asyncio.sleep(1.5)

    if not torrent or not torrent.files:
        logger.warning(
            "Не удалось получить список файлов раздачи %s — метаданные торрента ещё не загружены",
            torrent_hash,
        )
        return

    import_extras = True
    extra_exts = None
    try:
        if db and hasattr(db, "is_active") and db.is_active:
            settings = get_or_create_settings(db)
        else:
            from app.database import SessionLocal
            with SessionLocal() as s_db:
                settings = get_or_create_settings(s_db)
        import_extras = getattr(settings, "import_extra_files", True)
        raw_exts = getattr(settings, "extra_file_extensions", "")
        if raw_exts:
            extra_exts = {f".{e.strip().lstrip('.')}".lower() for e in raw_exts.split(",") if e.strip()}
    except Exception as exc:
        logger.debug("Настройки доп. файлов не загружены, используются по умолчанию: %s", exc)

    show_obj = None
    if target_eps:
        try:
            show_id = target_eps[0].show_id
            if db and hasattr(db, "is_active") and db.is_active:
                show_obj = db.get(Show, show_id)
            else:
                from app.database import SessionLocal
                with SessionLocal() as s_db:
                    show_obj = s_db.get(Show, show_id)
        except Exception:
            pass
    show_ova_mode = getattr(show_obj, "ova_mode", "auto") or "auto"

    unwanted_indices = []
    wanted_indices = []

    t_name = getattr(torrent, "name", "") or ""
    for f in torrent.files:
        prio = evaluate_torrent_file_priority(
            file_name=f.name,
            file_index=f.index,
            target_episodes=target_eps,
            import_extra_files=import_extras,
            extra_extensions=extra_exts,
            content_type=content_type,
            ova_mode=show_ova_mode,
            torrent_name=t_name,
        )
        if prio > 0:
            wanted_indices.append(f.index)
        else:
            unwanted_indices.append(f.index)

    if wanted_indices:
        await dl_client.set_files_wanted_unwanted(torrent_hash, wanted_indices, unwanted_indices)
        logger.info(
            "Раздача %s: выбрано серий %d из %d файлов (остальные %d файлов отключены)",
            torrent_hash, len(wanted_indices), len(torrent.files), len(unwanted_indices),
        )
        try:
            # Запускаем проверку целостности (verify / recheck) и возобновляем раздачу,
            # чтобы клиент обнаружил отсутствие файлов на диске (если они ранее перемещались/удалялись)
            # и скачал их заново.
            await dl_client.recheck_torrent(torrent_hash)
            await dl_client.resume_torrent(torrent_hash)
        except Exception as exc:
            logger.warning("Не удалось запустить проверку/возобновить раздачу %s: %s", torrent_hash, exc)

        logger.info(
            "Раздача %s: скачивание ограничено выбранными сериями (%d шт), отключено файлов: %d, включено: %d",
            torrent_hash, len(target_eps), len(unwanted_indices), len(wanted_indices)
        )
    else:
        # wanted_indices пуст.
        # Собираем все видеофайлы в раздаче
        video_files = [
            f for f in torrent.files
            if os.path.splitext(f.name.replace("\\", "/"))[1].lower() in {".mkv", ".mp4", ".avi", ".ts", ".m2ts", ".mov", ".webm"}
            and not ("/sample" in f.name.lower().replace("\\", "/") or f.name.lower().endswith("-sample.mkv"))
        ]

        # Проверяем, есть ли файлы с ЧЕТКО определенными номерами серий, не пересекающимися с запрошенными
        # (например, скачали Part 1 с сериями 1-12 при запросе серий 23-24).
        disjoint_episodes = set()
        for f in video_files:
            p = parse_episode(os.path.basename(f.name.replace("\\", "/")))
            if p and p.episodes:
                disjoint_episodes.update(p.episodes)

        is_explicitly_wrong_part = bool(
            disjoint_episodes and not any(
                (ep.episode_number in disjoint_episodes or (ep.absolute_number and ep.absolute_number in disjoint_episodes))
                for ep in target_eps
            ) and any(kw in t_name.lower() for kw in ("part 1", "part 2", "part 3", "part 4", "cour 1", "cour 2", "часть 1", "часть 2"))
        )

        if video_files and not is_explicitly_wrong_part:
            logger.warning(
                "Раздача %s (%s): пофайловое отключение пропущено (не удалось определить номера серий в именах файлов). Оставляем все видеофайлы (%d шт) включенными.",
                torrent_hash, t_name, len(video_files)
            )
            v_indices = [f.index for f in video_files]
            unw_indices = [f.index for f in torrent.files if f.index not in v_indices]
            await dl_client.set_files_wanted_unwanted(torrent_hash, v_indices, unw_indices)
            try:
                await dl_client.recheck_torrent(torrent_hash)
                await dl_client.resume_torrent(torrent_hash)
            except Exception as exc:
                logger.warning("Не удалось возобновить раздачу %s: %s", torrent_hash, exc)
            return

        # Раздача действительно не содержит запрошенных серий (например, Part 1 при поиске Part 2).
        # Помещаем хэш в список исключений, удаляем неподходящую раздачу из загрузчика, возвращаем серии в статус WANTED
        # и автоматически запускаем поиск следующего кандидата.
        file_sample = [f.name.replace("\\", "/") for f in torrent.files][:15]
        requested_ep_str = ", ".join(f"S{ep.season_number}E{ep.episode_number}" for ep in target_eps)
        logger.warning(
            "Раздача %s: ни один файл в раздаче не соответствует запрошенным сериям (%s). Файлы: %s. Раздача отменена и удалена из загрузчика.",
            torrent_hash, requested_ep_str, file_sample
        )

        try:
            await dl_client.remove_torrent(torrent_hash, delete_files=True)
        except Exception as exc:
            logger.warning("Не удалось удалить неподходящую раздачу %s: %s", torrent_hash, exc)

        show_id = None
        target_db_ids: set[int] = set()
        try:
            if db and hasattr(db, "is_active") and db.is_active:
                for ep in target_eps:
                    db_ep = db.get(Episode, ep.id)
                    if db_ep and db_ep.status == EpisodeStatus.DOWNLOADING and db_ep.torrent_hash == torrent_hash:
                        show_id = db_ep.show_id
                        target_db_ids.add(db_ep.id)
                        db_ep.status = EpisodeStatus.WANTED
                        db_ep.torrent_hash = None
                        db_ep.download_client_id = None
                        db_ep.download_progress = 0.0
                        db.add(db_ep)
                db.commit()
            else:
                from app.database import SessionLocal
                with SessionLocal() as s_db:
                    for ep in target_eps:
                        db_ep = s_db.get(Episode, ep.id)
                        if db_ep and db_ep.status == EpisodeStatus.DOWNLOADING and db_ep.torrent_hash == torrent_hash:
                            show_id = db_ep.show_id
                            target_db_ids.add(db_ep.id)
                            db_ep.status = EpisodeStatus.WANTED
                            db_ep.torrent_hash = None
                            db_ep.download_client_id = None
                            db_ep.download_progress = 0.0
                            s_db.add(db_ep)
                    s_db.commit()
        except Exception as exc:
            logger.debug("Ошибка сброса статуса серий для неподходящей раздачи: %s", exc)

        # Логируем событие и автоматически запускаем поиск следующего кандидата
        if show_id and target_db_ids:
            if torrent_hash:
                add_rejected_release_for_show(show_id, torrent_hash)
            t_name = getattr(torrent, "name", "")
            if t_name:
                add_rejected_release_for_show(show_id, t_name)
            try:
                from app.database import SessionLocal
                with SessionLocal() as s_db:
                    db_show = s_db.get(Show, show_id)
                    if db_show:
                        log_release_event(
                            stage="grab",
                            level="warning",
                            show_title=db_show.title,
                            show_id=db_show.id,
                            release_title=getattr(torrent, "name", "") or torrent_hash,
                            indexer="DownloadClient",
                            message=(
                                f"Раздача '{getattr(torrent, 'name', '') or torrent_hash}' удалена: файлы внутри не соответствуют запрошенным сериям ({requested_ep_str}). "
                                "Автоматический поиск следующего подходящего релиза..."
                            ),
                            details={"torrent_hash": torrent_hash, "requested_episodes": requested_ep_str, "files": file_sample},
                            db=s_db,
                        )

                async def _retry_next_candidate(s_id: int, ep_ids: set[int]):
                    try:
                        from app.database import SessionLocal
                        with SessionLocal() as retry_db:
                            r_show = retry_db.get(Show, s_id)
                            if r_show:
                                await search_and_grab_show(retry_db, r_show, episode_ids=ep_ids)
                    except Exception as e:
                        logger.debug("Повторный автопоиск кандидата: %s", e)

                asyncio.create_task(_retry_next_candidate(show_id, explicit_episode_ids or target_db_ids))
            except Exception as exc:
                logger.debug("Не удалось запланировать автопоиск следующего кандидата: %s", exc)


_SHOW_SEARCH_LOCKS: dict[int, asyncio.Lock] = {}


def _get_show_lock(show_id: int) -> asyncio.Lock:
    if show_id not in _SHOW_SEARCH_LOCKS:
        _SHOW_SEARCH_LOCKS[show_id] = asyncio.Lock()
    return _SHOW_SEARCH_LOCKS[show_id]


async def search_and_grab_show(
    db: Session,
    show: Show,
    episode_ids: Optional[set[int]] = None,
    wanted_only: bool = False,
) -> dict:
    """Ищет и захватывает лучший релиз для wanted-серий данного шоу.

    episode_ids: если задан — ищет релизы только для указанных серий.
    wanted_only: если True — искать только разыскиваемые (WANTED) серии и не выполнять апгрейд качества."""
    lock = _get_show_lock(show.id)
    if lock.locked():
        logger.info("Поиск для шоу %d уже выполняется в другом запросе, пропускаем дублирующий запуск", show.id)
        return {"show_id": show.id, "grabbed": [], "reason": "already_searching"}

    async with lock:
        show.is_searching = True
        db.add(show)
        db.commit()

        try:
            result = await _do_search_and_grab(db, show, episode_ids, wanted_only=wanted_only)
            grabbed_count = len(result.get("grabbed", []))
            reason = result.get("reason")
            if reason == "no_enabled_indexers":
                show.last_search_result = "Нет включённых индексаторов"
            elif reason == "no_wanted_episodes":
                show.last_search_result = "Нет серий в статусе «разыскивается»"
            elif grabbed_count:
                show.last_search_result = f"Захвачено релизов: {grabbed_count}"
            else:
                criteria = result.get("criteria")
                if criteria:
                    show.last_search_result = (
                        "Подходящих релизов не найдено. Искали по: " + criteria
                    )
                else:
                    show.last_search_result = "Подходящих релизов не найдено"
            return result
        except Exception as exc:
            try:
                db.rollback()
            except Exception:
                pass
            show.last_search_result = f"Ошибка поиска: {exc}"
            logger.exception("Ошибка автопоиска для видео %s", show.id)
            return {"show_id": show.id, "grabbed": [], "reason": "error"}
        finally:
            try:
                show.is_searching = False
                show.last_search_at = dt.datetime.utcnow()
                db.add(show)
                db.commit()
            except Exception as e:
                try:
                    db.rollback()
                except Exception:
                    pass
                logger.warning("Не удалось обновить статус поиска для шоу %s: %s", show.id, e)


class CandidateList(list):
    """Список кандидатов с сохранённым списком сгенерированных поисковых запросов."""
    def __init__(self, items=(), query_terms=None):
        super().__init__(items)
        self.query_terms = query_terms or []


def _extract_core_title(text: str) -> Optional[str]:
    """Извлекает короткое ядро тайтла (например, 'Re:Zero' из 'Re: ZERO, Starting Life in Another World')."""
    if not text:
        return None
    cleaned = re.sub(r"\s*\((?:тв|tv)[\s\-]?\d+\)", "", text.strip(), flags=re.IGNORECASE).strip()

    # Спец-обработка для Re:Zero, Fate/Stay и т.п.
    if re.match(r"^(?:re|fate)\s*[:/]", cleaned, re.IGNORECASE):
        parts = re.split(r"\s*[:/]\s*", cleaned, maxsplit=2)
        if len(parts) >= 2:
            prefix = f"{parts[0]}:{parts[1]}"
            prefix = re.split(r"\s*[,—–]\s*", prefix)[0].strip()
            if prefix.lower() != text.strip().lower():
                return prefix

    # Обычный сплит по двоеточию, длинному тире, запятой
    m_sep = re.split(r"\s*[:—–,]\s*", cleaned)
    if len(m_sep) > 1 and len(m_sep[0]) >= 3:
        cand = m_sep[0].strip()
        if cand.lower() != text.strip().lower():
            return cand
    return None


def _ordinal_en(n: int) -> str:
    if 11 <= (n % 100) <= 13:
        return f"{n}th"
    return f"{n}" + {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")


def _generate_season_queries(base: str, sn: int) -> list[str]:
    """Генерирует умный и компактный список сезонных запросов (включая ТВ-X, 4 сезон, 4th Season, S04, паки)."""
    ord_en = _ordinal_en(sn)
    terms = [
        f"{base} (ТВ-{sn})",
        f"{base} ТВ-{sn}",
        f"{base} {sn} сезон",
        f"{base} S{sn:02d}",
        f"{base} {ord_en} Season",
    ]
    if sn > 1:
        terms.extend([
            f"{base} 1-{sn} сезон",
            f"{base} S01-S{sn:02d}",
        ])
    return terms


async def _collect_candidates(
    db: Session,
    show: Show,
    indexers: list[Indexer],
    wanted_episodes: Optional[list[Episode]] = None,
) -> list[dict]:
    """Собирает все релизы по всем алиасам во всех индексаторах (по приоритету), дедуп по guid."""
    quality_profile = db.get(QualityProfile, show.quality_profile_id) if show.quality_profile_id else None
    allowed_qualities = quality_profile.allowed_qualities if quality_profile else []
    alias_candidates = build_alias_candidates(show, db=db)

    # Формируем компактный и результативный список поисковых запросов (не более 12-14)
    query_terms: list[str] = []
    seen_queries: set[str] = set()

    def _add_query(q: str):
        q = q.strip()
        if q and q.lower() not in seen_queries:
            seen_queries.add(q.lower())
            query_terms.append(q)

    # 1. Извлекаем короткие ядра и чистые алиасы
    cores: list[str] = []
    clean_bases: list[str] = []
    for alias in alias_candidates:
        clean_a = re.sub(r"\s*\((?:тв|tv)[\s\-]?\d+\)", "", alias.text, flags=re.IGNORECASE).strip()
        if clean_a:
            if clean_a.lower() not in [b.lower() for b in clean_bases]:
                clean_bases.append(clean_a)
            core_a = _extract_core_title(clean_a)
            if core_a and core_a.lower() not in [c.lower() for c in cores]:
                cores.append(core_a)

    key_bases = cores + [cb for cb in clean_bases if cb.lower() not in [c.lower() for c in cores]]

    # 2. Сезонные запросы (ТВ-X, X сезон, SX, Xth Season, паки) для разыскиваемых сезонов
    if wanted_episodes:
        wanted_seasons = {
            ep.season_number
            for ep in wanted_episodes
            if ep.season_number is not None and ep.season_number > 0
        }
        for sn in sorted(wanted_seasons):
            season_query_lists = [_generate_season_queries(b, sn) for b in key_bases]
            if season_query_lists:
                max_sq = max(len(l) for l in season_query_lists)
                for idx in range(max_sq):
                    for q_list in season_query_lists:
                        if idx < len(q_list):
                            _add_query(q_list[idx])

    # 3. Базовые названия (без сезона)
    for b in key_bases:
        _add_query(b)

    # 4. Полные оригинальные алиасы
    for alias in alias_candidates:
        _add_query(alias.text)

    # 5. Конкретные серии при небольшом количестве
    if wanted_episodes and len(wanted_episodes) <= 6:
        for ep in wanted_episodes:
            for b in key_bases[:2]:
                if ep.absolute_number is not None:
                    for fmt in (f"{b} {ep.absolute_number}", f"{b} {ep.absolute_number:02d}", f"{b} - {ep.absolute_number}"):
                        _add_query(fmt)
                elif ep.season_number == 0:
                    for fmt in (f"{b} OVA", f"{b} Special", f"{b} S00E{ep.episode_number:02d}"):
                        _add_query(fmt)
                else:
                    for fmt in (f"{b} S{ep.season_number:02d}E{ep.episode_number:02d}", f"{b} {ep.episode_number:02d}"):
                        _add_query(fmt)

    seen_guids: set[str] = set()
    candidates: list[dict] = []

    active_queries = query_terms[:16]

    # Опрашиваем индексаторы параллельно с пулом семафора, собирая все полученные результаты
    sem = asyncio.Semaphore(8)

    async def _fetch_indexer_term(idx: Indexer, q_term: str):
        async with sem:
            try:
                client = get_indexer_client(idx)
                rels = await asyncio.wait_for(client.search(q_term), timeout=10.0)
                return (idx, rels)
            except Exception as exc:
                logger.debug("Индексатор %s запрос «%s»: %s", getattr(idx, "name", idx), q_term, exc)
                return (idx, [])

    tasks = []
    for indexer in sorted(indexers, key=lambda i: i.priority):
        for term in active_queries:
            tasks.append(_fetch_indexer_term(indexer, term))

    fetched_batches = await asyncio.gather(*tasks, return_exceptions=True)

    for item in fetched_batches:
        if not isinstance(item, tuple):
            continue
        indexer, releases = item
        for rel in releases:
            if not rel or not getattr(rel, "guid", None):
                continue
            if rel.guid in seen_guids:
                continue
            seen_guids.add(rel.guid)

            # Проверяем, не был ли этот релиз ранее отклонён для этого тайтла
            infohash = getattr(rel, "infohash", None)
            guid_str = str(rel.guid) if getattr(rel, "guid", None) else None
            dl_url = str(getattr(rel, "download_url", "")) if getattr(rel, "download_url", None) else None
            if is_release_rejected_for_show(
                show.id,
                infohash=infohash,
                guid=guid_str,
                download_url=dl_url,
                title=getattr(rel, "title", None),
            ):
                continue

            match = match_release(
                rel.title,
                show.id,
                alias_candidates,
                content_type=show.content_type,
                categories=getattr(rel, "categories", None),
                show_year=getattr(show, "year", None),
            )
            if not match.matched:
                continue

            quality = parse_quality(rel.title)
            if not is_allowed(quality, allowed_qualities):
                continue

            candidates.append({
                "rel": rel, "match": match, "quality": quality, "indexer": indexer,
            })

    return CandidateList(candidates, query_terms=query_terms)


async def _do_search_and_grab(
    db: Session,
    show: Show,
    episode_ids: Optional[set[int]] = None,
    wanted_only: bool = False,
) -> dict:
    if episode_ids:
        wanted_episodes = db.query(Episode).filter(Episode.show_id == show.id, Episode.id.in_(episode_ids)).all()
    else:
        if show.content_type == "movie":
            # Для фильмов: если шоу отслеживается (monitored), поиск должен охватывать фильм
            # независимо от того, наступила ли уже дата премьеры (WANTED или UNAIRED)
            quality_profile = db.get(QualityProfile, show.quality_profile_id) if show.quality_profile_id else None
            upgrade_allowed = getattr(quality_profile, "upgrade_allowed", False) if quality_profile else False
            if show.monitored:
                if upgrade_allowed:
                    status_filter = or_(
                        Episode.status.in_([EpisodeStatus.WANTED, EpisodeStatus.UNAIRED]),
                        and_(Episode.status == EpisodeStatus.DOWNLOADED, Episode.monitored == True),
                    )
                else:
                    status_filter = Episode.status.in_([EpisodeStatus.WANTED, EpisodeStatus.UNAIRED])
            else:
                status_filter = Episode.status == EpisodeStatus.WANTED
        elif wanted_only:
            status_filter = Episode.status == EpisodeStatus.WANTED
        else:
            quality_profile = db.get(QualityProfile, show.quality_profile_id) if show.quality_profile_id else None
            upgrade_allowed = getattr(quality_profile, "upgrade_allowed", False) if quality_profile else False
            if show.monitored and upgrade_allowed:
                status_filter = or_(
                    Episode.status == EpisodeStatus.WANTED,
                    and_(Episode.status == EpisodeStatus.DOWNLOADED, Episode.monitored == True),
                )
            else:
                status_filter = Episode.status == EpisodeStatus.WANTED
        wanted_episodes = db.query(Episode).filter(Episode.show_id == show.id, status_filter).all()
    if not wanted_episodes:
        return {"show_id": show.id, "grabbed": [], "reason": "no_wanted_episodes"}

    indexers = db.query(Indexer).filter(Indexer.enabled == True).all()  # noqa: E712
    if not indexers:
        return {"show_id": show.id, "grabbed": [], "reason": "no_enabled_indexers"}

    settings = get_or_create_settings(db)
    alias_candidates = build_alias_candidates(show, db=db)
    search_terms = ", ".join(f"«{a.text}»" for a in alias_candidates)

    candidates = await _collect_candidates(db, show, indexers, wanted_episodes=wanted_episodes)
    query_terms = getattr(candidates, "query_terms", [])

    # Фильтр по минимальному числу сидов
    if settings.min_seeds and settings.min_seeds > 0:
        candidates = [c for c in candidates if c["rel"].seeders >= settings.min_seeds]

    sample_queries = ", ".join(f"«{q}»" for q in query_terms[:4])
    if len(query_terms) > 4:
        sample_queries += f" (+ещё {len(query_terms) - 4})"
    query_info = f" по {len(query_terms)} запросам ({sample_queries})" if query_terms else f" по алиасам ({search_terms})"

    log_release_event(
        stage="search",
        level="info" if candidates else "warning",
        show_title=show.title,
        show_id=show.id,
        message=f"Поиск{query_info} в {len(indexers)} трекерах: найдено {len(candidates)} подходящих кандидатов",
        details={
            "candidates_count": len(candidates),
            "indexers_count": len(indexers),
            "wanted_episodes_count": len(wanted_episodes),
            "queries": query_terms[:25] if query_terms else [a.text for a in alias_candidates],
        },
        db=db,
    )

    if not candidates:
        return {"show_id": show.id, "grabbed": [], "criteria": search_terms}

    # Подсчитываем сколько всего серий в каждом сезоне, и сколько мы ищем,
    # чтобы не скачивать целый season-pack, если разыскивается лишь 1-2 серии (bugfix)
    total_episodes_by_season = {}
    wanted_count_by_season = {}
    for ep in wanted_episodes:
        if ep.season_number not in total_episodes_by_season:
            total_episodes_by_season[ep.season_number] = db.query(Episode).filter_by(
                show_id=show.id, season_number=ep.season_number
            ).count()
        wanted_count_by_season[ep.season_number] = wanted_count_by_season.get(ep.season_number, 0) + 1

    # Для каждой wanted-серии находим кандидатов, которые её покрывают
    episodes_by_key: dict[tuple[int, int], Episode] = {
        (ep.season_number, ep.episode_number): ep for ep in wanted_episodes
    }

    def covers(c, ep: Episode) -> bool:
        """
        Проверяет, покрывает ли кандидат (c) конкретную серию (ep).
        """
        rel = c["rel"]
        match_result = c["match"]
        parsed = match_result.parsed

        # Исключаем опенинги, эндинги, трейлеры, бонусы и не-видео материалы
        if parsed.matched_pattern in ("extra_ignored", "non_video_ignored"):
            return False
        from app.services.matcher import is_non_video_release
        if is_non_video_release(rel.title, categories=getattr(rel, "categories", None)):
            return False

        # Фильмы: ориентируемся только на совпадение по алиасу.
        if show.content_type == "movie":
            return True

        # Вычисляем смещение для Part 2 / Cour 2 (Split-Cour)
        part_offset = 0
        if parsed.part and parsed.part >= 2 and parsed.episodes:
            from app.services.matcher import resolve_part_offset
            all_s_eps = [e for e in getattr(show, "episodes", []) if getattr(e, "season_number", None) == ep.season_number]
            part_offset = resolve_part_offset(
                parsed.part,
                parsed.total_in_part,
                parsed.episodes,
                all_s_eps,
                wanted_episodes,
            )

        def _has_ep_match():
            if not parsed.episodes:
                return True
            ep_n = ep.episode_number
            ep_abs = ep.absolute_number
            if ep_n in parsed.episodes or (part_offset > 0 and (ep_n - part_offset) in parsed.episodes):
                return True
            if ep_abs is not None and (ep_abs in parsed.episodes or (part_offset > 0 and (ep_abs - part_offset) in parsed.episodes)):
                return True
            return False

        # 1. Проверяем точное совпадение по absolute_number (для аниме)
        if ep.absolute_number is not None and parsed.episodes:
            if ep.absolute_number in parsed.episodes or (part_offset > 0 and (ep.absolute_number - part_offset) in parsed.episodes):
                if parsed.season is not None and parsed.season != ep.season_number:
                    pass
                else:
                    return True

        # 2. Определяем метку сезона из заголовка релиза
        season_label = detect_season_label(rel.title)
        label_type = season_label["type"]

        # Обработка OVA согласно настройке тайтла ova_mode (auto | season_1 | specials)
        ova_mode = getattr(show, "ova_mode", "auto") or "auto"
        is_ova_release = (
            label_type == "ova_ona"
            or parsed.season == 0
            or (parsed.matched_pattern and "ova" in parsed.matched_pattern.lower())
            or re.search(r"\[ova(?:[-_ ]?\d+)?\]|\bova\b", rel.title, re.IGNORECASE) is not None
        )

        remap_to_season_1 = False
        if is_ova_release and show.content_type in ("series", "anime") and ova_mode != "specials":
            if ova_mode == "season_1":
                remap_to_season_1 = True
            elif ova_mode == "auto":
                show_all_eps = getattr(show, "episodes", []) or []
                s0_count = sum(1 for e in show_all_eps if getattr(e, "season_number", None) == 0)
                s1_count = sum(1 for e in show_all_eps if getattr(e, "season_number", None) == 1)
                if parsed.episodes:
                    max_ep = max(parsed.episodes)
                    if max_ep > s0_count and max_ep <= s1_count:
                        remap_to_season_1 = True
                    elif wanted_episodes and 0 not in {getattr(e, "season_number", None) for e in wanted_episodes} and 1 in {getattr(e, "season_number", None) for e in wanted_episodes}:
                        remap_to_season_1 = True
                elif parsed.kind == ReleaseKind.SEASON_PACK and s0_count <= 1 and s1_count >= 2:
                    remap_to_season_1 = True

        if remap_to_season_1:
            if ep.season_number != 1:
                return False
            if parsed.episodes:
                return ep.episode_number in parsed.episodes
            return True

        # --- Случай 0: Мультисезонный диапазон (Сезоны 1-5, S01-S05, Seasons 1-5) ---
        if label_type == "range":
            if ep.season_number not in season_label.get("seasons", []):
                return False
            return _has_ep_match()

        # --- Случай 0б: Мультисезонный список из parsed.seasons ---
        if parsed.seasons and len(parsed.seasons) > 1:
            if ep.season_number not in parsed.seasons:
                return False
            return _has_ep_match()

        # --- Случай 1: явный номер сезона в названии релиза ---
        if label_type == "numbered":
            label_season = season_label["season"]
            if label_season != ep.season_number:
                # Если в базе у шоу нет такого сезона (например, цифра 2 была частью названия аниме/арки, а не номером сезона)
                # и разыскивается сезон 1, проверяем не является ли это серией/паком для сезона 1
                has_label_season_in_db = (
                    total_episodes_by_season.get(label_season, 0) > 0
                )
                if not has_label_season_in_db and ep.season_number == 1:
                    return _has_ep_match()
                return False
            return _has_ep_match()

        # --- Случай 2: «Final Season» ---
        if label_type == "final":
            max_s = _get_show_max_season(db, show)
            if max_s > 1 and ep.season_number != max_s:
                return False
            return _has_ep_match()

        # --- Случай 3: «Complete Series» / «Все сезоны» ---
        if label_type == "complete":
            return _has_ep_match()

        # --- Случай 4: OVA/ONA/Special — сезон 0 ---
        if label_type == "ova_ona" or parsed.season == 0:
            if ep.season_number != 0:
                return False
            if parsed.episodes:
                return ep.episode_number in parsed.episodes
            return True

        # --- Случай 5: сезон в названии релиза указан через parse_episode ---
        parsed_season = parsed.season
        if parsed_season is not None:
            if parsed_season != ep.season_number:
                return False
            return _has_ep_match()

        # --- Случай 6: сезон в названии релиза не указан (аниме absolute / lone number / диапазон серий) ---
        if parsed.episodes:
            if ep.absolute_number is not None:
                return ep.absolute_number in parsed.episodes or (part_offset > 0 and (ep.absolute_number - part_offset) in parsed.episodes)
            return (ep.episode_number in parsed.episodes or (part_offset > 0 and (ep.episode_number - part_offset) in parsed.episodes)) and ep.season_number in (0, 1)

        # --- Случай 7: релиз без явного указания серий и сезона (полный пак / аниме сериал целиком) ---
        if not parsed.episodes and parsed.season is None and label_type == "none":
            s1_total = total_episodes_by_season.get(1, 0)
            if s1_total > 1:
                is_pack_title = bool(re.search(
                    r"\b(?:complete|collection|коллекция|полная\s+серия|все\s+серии|пак|pack|season|сезон)\b",
                    rel.title,
                    re.IGNORECASE,
                ))
                if not is_pack_title:
                    return False
            if ep.season_number == 1:
                return True

        return False

    # Строим для каждого кандидата множество wanted-серий, которые он закрывает,
    # вычисляем Custom Formats score и скор соответствия.
    from app.services.quality import parse_quality, is_upgrade, QUALITY_ALIASES
    from app.services.custom_formats import calculate_custom_formats_for_release
    from app.services.language_parser import parse_languages
    from app.services.release_group_parser import parse_release_group
    
    quality_profile = db.get(QualityProfile, show.quality_profile_id) if show.quality_profile_id else None
    allowed_qualities = quality_profile.allowed_qualities if quality_profile else []

    def get_quality_preference(q_info, allowed):
        norm_name = QUALITY_ALIASES.get(q_info.name.upper(), q_info.name)
        for idx, a in enumerate(allowed):
            if a == q_info.name or a == norm_name or QUALITY_ALIASES.get(a.upper(), a) == norm_name:
                return len(allowed) - idx
        return q_info.rank

    scored_candidates = []
    for c in candidates:
        covered = [ep for ep in wanted_episodes if covers(c, ep)]
        
        final_covered = []
        for ep in covered:
            if ep.status == EpisodeStatus.DOWNLOADED:
                if wanted_only:
                    continue
                if not getattr(ep, "monitored", True):
                    continue
                if not quality_profile or not getattr(quality_profile, "upgrade_allowed", False):
                    continue
                
                # Определяем текущее качество имеющегося файла
                current_quality_name = ep.downloaded_quality
                if not current_quality_name and ep.file_path and os.path.exists(ep.file_path):
                    current_quality_name = parse_quality(os.path.basename(ep.file_path)).name
                
                if not current_quality_name:
                    # Если файл физически есть на диске, но качество неизвестно — не заменяем вслепую
                    if getattr(ep, "has_file", False) or (ep.file_path and os.path.exists(ep.file_path)):
                        continue
                    current_quality_name = "SDTV"

                current_quality = parse_quality(current_quality_name)
                
                # Проверка достижения порога качества (cutoff_quality)
                if getattr(quality_profile, "cutoff_quality", None):
                    cutoff = parse_quality(quality_profile.cutoff_quality)
                    if current_quality.rank >= cutoff.rank:
                        continue

                if not is_upgrade(current_quality, c["quality"], allowed_qualities):
                    continue
            final_covered.append(ep)
            
        if not final_covered:
            continue

        # Вычисляем кастомные форматы (CF score)
        rel_langs = parse_languages(c["rel"].title)
        rel_group = parse_release_group(c["rel"].title)
        cf_score, _ = calculate_custom_formats_for_release(
            db=db,
            title=c["rel"].title,
            quality=c["quality"],
            languages=rel_langs,
            release_group=rel_group,
            quality_profile=quality_profile,
        )

        score = score_candidate(c["match"], seeders=c["rel"].seeders, quality_rank=c["quality"].rank)
        scored_candidates.append({
            **c,
            "covered": final_covered,
            "score": score,
            "cf_score": cf_score,
        })

    if not scored_candidates:
        log_release_event(
            stage="decision",
            level="warning",
            show_title=show.title,
            show_id=show.id,
            message=f"Найдено {len(candidates)} кандидатов, но ни один не подошёл для захвата (не покрывают разыскиваемые серии или отклонены профилем качества)",
            details={
                "candidates": [
                    {
                        "title": c["rel"].title,
                        "quality": c["quality"].name,
                        "seeders": c["rel"].seeders,
                        "indexer": getattr(c["indexer"], "name", "Indexer"),
                    }
                    for c in candidates[:6]
                ]
            },
            db=db,
        )
        return {"show_id": show.id, "grabbed": [], "criteria": search_terms}

    # Многоуровневая сортировка кандидатов:
    # 1. Приоритет качества из профиля (Quality Preference: наивысшее качество из профиля побеждает всегда!)
    # 2. Очки кастомных форматов (CF Score)
    # 3. Флаг Full/Complete (1 если полный пак / закрывает все нужные серии на этом уровне качества)
    # 4. Количество закрываемых серий (coverage_count)
    # 5. Приоритет индексатора (0 — высший приоритет, 100 — низший)
    # 6. Число сидеров (seeders)
    # 7. Скор соответствия названия (match.score)
    def candidate_sort_key(c):
        quality_pref = get_quality_preference(c["quality"], allowed_qualities) if c.get("quality") else 0
        cf_score = c.get("cf_score") or 0
        season_lbl = detect_season_label(c["rel"].title) if c.get("rel") else {"type": "none"}
        is_full = 1 if (
            season_lbl["type"] == "complete" or
            c["match"].parsed.matched_pattern in ("season_pack:complete", "season_pack:multi_range") or
            len(c.get("covered", [])) >= len(wanted_episodes)
        ) else 0
        coverage_count = len(c.get("covered", []))
        indexer_priority = getattr(c.get("indexer"), "priority", 100) or 100
        seeders = getattr(c.get("rel"), "seeders", 0) or 0
        match_score = c.get("score") or 0
        return (quality_pref or 0, cf_score, is_full, coverage_count, -indexer_priority, seeders, match_score)

    scored_candidates.sort(key=candidate_sort_key, reverse=True)

    # Жадный алгоритм захвата без дубликатов:
    # - Если один релиз закрывает все сезоны/серии, он скачивается в единственном экземпляре.
    # - Если полного пака нет, последовательно берутся лучшие паки по сезонам с приоритетных трекеров,
    #   а недостающие сезоны добираются со следующих трекеров.
    # - Железная гарантия: ровно один релиз на каждый сезон (никаких параллельных дублей).
    download_client_row = (
        db.query(DownloadClient).filter(DownloadClient.enabled == True).order_by(  # noqa: E712
            DownloadClient.is_default.desc()
        ).first()
    )
    if download_client_row is None:
        logger.warning("Нет доступного download client для видео %s", show.id)
        log_release_event(
            stage="grab",
            level="error",
            show_title=show.title,
            show_id=show.id,
            message="Не удалось отправить релиз в загрузчик: нет активного/включенного клиента загрузки (Download Client). Включите загрузчик в Настройки -> Загрузчики.",
            details={"scored_candidates_count": len(scored_candidates)},
            db=db,
        )
        return {"show_id": show.id, "grabbed": [], "criteria": search_terms}

    # Динамический алгоритм захвата с автоматическим переходом к следующему релизу при сбое:
    # - Если захват первого по приоритету релиза падает (например, 404 у трекера или ошибка сети),
    #   серии не сбрасываются, и система автоматически пробует захватить следующий подходящий релиз.
    # - Железная гарантия: ровно один успешно захваченный релиз на каждый сезон (никаких параллельных дублей).
    remaining = dict(episodes_by_key)  # (season, ep) -> Episode ещё не закрыт релизом
    grabbed_seasons: set[int] = set()
    grabbed = []
    dl_client = get_client(download_client_row)

    for c in scored_candidates:
        if not remaining:
            break

        still_covered = [
            ep for ep in c["covered"]
            if (ep.season_number, ep.episode_number) in remaining
        ]
        if not still_covered:
            continue

        # Проверяем, не закрыт ли уже этот сезон другим ранее успешно захваченным релизом
        candidate_seasons = {ep.season_number for ep in still_covered}
        if not (candidate_seasons - grabbed_seasons) and len(candidate_seasons) == 1:
            continue

        rel, match, indexer, covered = c["rel"], c["match"], c["indexer"], still_covered
        # Папка временного скачивания для соответствующей категории контента
        if show.content_type == "movie":
            save_path = settings.download_folder_movies
        elif show.content_type == "anime":
            save_path = settings.download_folder_anime
        else:
            save_path = settings.download_folder_series

        # Находим старые торрент-хэши для этих серий (если раздача заменяется/апгрейдится),
        # чтобы удалить старый дубликат из торрент-клиента и не качать дважды
        old_hashes_to_cleanup = {
            ep.torrent_hash for ep in covered
            if ep.torrent_hash and ep.status == EpisodeStatus.DOWNLOADING
        }

        try:
            torrent_hash = await dl_client.add_torrent(rel.download_url, download_client_row.category, save_path)
            if not torrent_hash:
                raise RuntimeError(f"Загрузчик '{download_client_row.name}' не подтвердил добавление раздачи (хэш не получен)")
            is_movie = show.content_type == "movie"
            yr_str = f" ({show.year})" if show.year else ""
            if is_movie:
                grab_msg = f"Релиз успешно захвачен для фильма «{show.title}»{yr_str} и передан в '{download_client_row.name}' (хэш: {torrent_hash or 'n/a'}, сиды: {rel.seeders}, качество: {c['quality'].name})"
                ep_details = ["Фильм"]
            else:
                ep_details = [f"S{ep.season_number:02d}E{ep.episode_number:02d}" for ep in covered]
                grab_msg = f"Релиз успешно захвачен и передан в '{download_client_row.name}' (хэш: {torrent_hash or 'n/a'}). Закрывает серии: {', '.join(ep_details)}"

            log_release_event(
                stage="grab",
                level="success",
                show_title=show.title,
                show_id=show.id,
                release_title=rel.title,
                indexer=getattr(indexer, "name", "Torznab"),
                message=grab_msg,
                details={
                    "torrent_hash": torrent_hash,
                    "save_path": save_path,
                    "episodes": ep_details,
                    "seeders": rel.seeders,
                    "quality": c["quality"].name,
                    "client": download_client_row.name,
                    "page_url": getattr(rel, "page_url", None),
                    "download_url": getattr(rel, "download_url", None),
                },
                db=db,
            )

            # Удаляем старые дублирующие раздачи из торрент-клиента
            for old_hash in old_hashes_to_cleanup:
                if old_hash != torrent_hash:
                    try:
                        await dl_client.remove_torrent(old_hash, delete_files=True)
                        logger.info("Удалена старая дублирующая раздача %s из загрузчика", old_hash)
                    except Exception as exc:
                        logger.warning("Не удалось удалить старую раздачу %s: %s", old_hash, exc)

            for ep in covered:
                ep.status = EpisodeStatus.DOWNLOADING
                ep.download_client_id = download_client_row.id
                ep.torrent_hash = torrent_hash
                remaining.pop((ep.season_number, ep.episode_number), None)
                grabbed_seasons.add(ep.season_number)
                db.add(ep)

            # Для сериалов/аниме запускаем selective download в фоне, для фильмов — гарантируем включение всех файлов
            if torrent_hash:
                try:
                    if show.content_type == "movie":
                        asyncio.create_task(_ensure_movie_files_wanted(dl_client, torrent_hash))
                    else:
                        target_eps_data = [
                            Episode(
                                id=ep.id,
                                season_number=ep.season_number,
                                episode_number=ep.episode_number,
                                absolute_number=ep.absolute_number,
                            )
                            for ep in covered
                        ]
                        asyncio.create_task(
                            _limit_torrent_files_to_episodes(
                                dl_client,
                                torrent_hash,
                                target_eps_data,
                                None,
                                explicit_episode_ids=episode_ids,
                                content_type=show.content_type,
                            )
                        )
                except Exception as exc:
                    logger.warning("Не удалось запланировать обработку файлов раздачи: %s", exc)

            topic_guid = rel.guid or rel.download_url or rel.infohash or str(uuid.uuid4())
            topic_url = rel.page_url or rel.download_url or ""
            tracked = TrackedRelease(
                show_id=show.id,
                indexer_id=indexer.id,
                topic_guid=topic_guid,
                topic_url=topic_url,
                infohash=torrent_hash or rel.infohash,
                downloaded_episodes=[{"season": ep.season_number, "episode": ep.episode_number} for ep in covered],
                last_checked_at=dt.datetime.utcnow(),
            )
            db.add(tracked)

            if covered:
                db.add(DownloadHistory(
                    show_id=show.id, episode_id=covered[0].id, release_title=rel.title,
                    indexer_id=indexer.id, event_type="grabbed",
                    matched_alias=match.alias_text, show_title_snapshot=show.title,
                ))
            db.commit()

            is_upgrade = any(ep.status == EpisodeStatus.DOWNLOADED for ep in covered)
            title_linked = f'<a href="{rel.guid}">«{show.title}»</a>' if rel.guid else f"«{show.title}»"

            if show.content_type == "movie":
                yr_str = f" ({show.year})" if show.year else ""
                action_text = "Обнаружено лучшее качество и начато скачивание для фильма" if is_upgrade else "Захвачен релиз для фильма"
                notify_msg = f"{action_text} {title_linked}{yr_str}, сиды: {rel.seeders}: {rel.title}"
            else:
                ep_list = ", ".join(f"S{ep.season_number:02d}E{ep.episode_number:02d}" for ep in covered)
                action_text = "Обнаружено лучшее качество и начато скачивание для" if is_upgrade else "Захвачен релиз для"
                notify_msg = f"{action_text} {title_linked} ({ep_list}), сиды: {rel.seeders}: {rel.title}"

            try:
                await notify_all(db, "grab", notify_msg)
            except Exception as exc:
                logger.warning("Не удалось отправить уведомление о захвате: %s", exc)

            for ep in covered:
                grabbed.append({
                    "episode_id": ep.id, "season": ep.season_number, "episode": ep.episode_number,
                    "release": rel.title, "score": c["score"], "seeders": rel.seeders,
                })

        except Exception as exc:
            logger.error("Не удалось отправить релиз '%s' в download client: %s", rel.title, exc)
            log_release_event(
                stage="grab",
                level="error",
                show_title=show.title,
                show_id=show.id,
                release_title=rel.title,
                indexer=getattr(indexer, "name", "Torznab"),
                message=f"Ошибка отправки релиза в загрузчик '{download_client_row.name}': {exc}. Пробуем следующий доступный релиз...",
                details={
                    "error": str(exc),
                    "download_url": getattr(rel, "download_url", None),
                    "page_url": getattr(rel, "page_url", None),
                    "client": download_client_row.name,
                },
                db=db,
            )
            continue

    if not grabbed:
        log_release_event(
            stage="decision",
            level="warning",
            show_title=show.title,
            show_id=show.id,
            message="Ни один из кандидатов не был успешно захвачен (ошибки добавления в загрузчик или разыскиваемые серии уже закрыты)",
            details={"scored_candidates_count": len(scored_candidates)},
            db=db,
        )

    from app.services.task_manager import task_manager
    async with task_manager.track(
        name="show_search",
        title=f"Поиск релизов: {show.title}",
        message="Опрос трекеров и сопоставление алиасов...",
    ) as s_task:
        if not grabbed:
            s_task.complete("Релизов не найдено")
            return {"show_id": show.id, "grabbed": [], "criteria": search_terms}

        s_task.complete(f"Захвачено {len(grabbed)} релиз(ов)")
        return {"show_id": show.id, "grabbed": grabbed}


async def run_wanted_search(db: Session) -> list[dict]:
    """Запускает поиск/захват для всех мониторящихся шоу с wanted-сериями."""
    from app.services.task_manager import task_manager
    async with task_manager.track(
        name="wanted_search",
        title="Автопоиск разыскиваемых релизов (Wanted)",
        message="Проверка библиотеки...",
    ) as w_task:
        wanted_shows_ids = [
            r[0] for r in db.query(Episode.show_id).join(Show, Show.id == Episode.show_id).filter(
                Show.monitored == True,  # noqa: E712
                Episode.status == EpisodeStatus.WANTED,
            ).distinct().all()
        ]
        if not wanted_shows_ids:
            w_task.complete("Поиск завершён: нет разыскиваемых релизов (Wanted)")
            return []

        shows = db.query(Show).filter(Show.id.in_(wanted_shows_ids)).all()
        w_task.update(message=f"Поиск для {len(shows)} тайтлов с разыскиваемыми сериями...")
        results = []
        total_grabbed = 0
        for idx, show in enumerate(shows, 1):
            w_task.update(
                message=f"Обработка ({idx}/{len(shows)}): «{show.title}»...",
                progress=round(idx / max(1, len(shows)), 2),
            )
            try:
                result = await search_and_grab_show(db, show, wanted_only=True)
                if result.get("grabbed"):
                    results.append(result)
                    total_grabbed += len(result["grabbed"])
            except Exception as exc:
                logger.warning("Ошибка при поиске шоу %s (%s) в wanted_search: %s", show.id, show.title, exc)
        if total_grabbed > 0:
            w_task.complete(f"Завершено: захвачено {total_grabbed} релиз(ов)")
        else:
            w_task.complete("Поиск завершён: новых релизов не обнаружено")
        return results
