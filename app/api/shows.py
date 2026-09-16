from __future__ import annotations

from typing import Optional, List, Dict, Any

import datetime as dt
import logging
import os
import shutil

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, UploadFile, File
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import and_, func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import re

from app.database import get_db
from app.models.db import (
    Alias,
    DownloadClient,
    DownloadHistory,
    Episode,
    EpisodeStatus,
    MonitorStatus,
    ReleaseLog,
    SeasonSplit,
    SeasonSplitPart,
    Show,
    TrackedRelease,
    User,
)

logger = logging.getLogger(__name__)
from app.schemas import (
    AliasCreate,
    AliasOut,
    AliasUpdate,
    DeleteContentPayload,
    DeleteContentResponse,
    EpisodeOut,
    SeasonSplitCreate,
    SeasonSplitOut,
    SeasonSplitPartCreate,
    SeasonSplitPartOut,
    SeasonSplitUpdate,
    ShowCreate,
    ShowOut,
    ShowUpdate,
    SpecialsImportStatusOut,
)
from app.services.audit_service import log_audit
from app.services.parser import ParsedRelease, ReleaseKind, parse_episode
from app.services.postprocess import (
    _SAMPLE_RE,
    VIDEO_EXTENSIONS,
    apply_media_permissions,
    copy_file_with_progress,
    extract_companion_tag,
    find_release_files,
    find_video_files,
    get_show_default_path,
    match_companion_files_for_episode,
    move_file_with_progress,
    natural_sort_key,
    render_episode_template,
    render_movie_template,
    render_season_folder_template,
    sanitize_filename,
)
from app.services.matcher import build_alias_candidates, match_release
from app.services.quality import parse_quality, detect_file_quality
from app.services.organizer import clean_show_title_and_year
from app.services.settings_service import get_or_create_settings
from app.services.user_service import require_permission, require_any_permission, get_current_user
from app.services.metadata import get_metadata_client
from app.services.path_security import (
    UnsafeMediaPathError,
    require_library_descendant,
    require_library_descendants,
)

router = APIRouter(prefix="/api/v1/shows", tags=["shows"])

MAX_COVER_UPLOAD_BYTES = 10 * 1024 * 1024


async def _read_upload_with_limit(file: UploadFile, max_bytes: int = MAX_COVER_UPLOAD_BYTES) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(min(1024 * 1024, max_bytes + 1 - total))
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(status_code=413, detail="Файл обложки превышает лимит 10 МБ")
        chunks.append(chunk)
    return b"".join(chunks)


def _validate_destructive_media_paths(settings, paths: list[str | None]) -> None:
    try:
        require_library_descendants((path for path in paths if path), settings)
    except UnsafeMediaPathError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _attach_computed_fields(db: Session, shows: list[Show]) -> list[ShowOut]:
    """Добавляет к каждому шоу агрегаты для табличного вида библиотеки:
    количество сезонов/серий и дату ближайшего невышедшего эфира."""
    if not shows:
        return []

    # Обновляем дефолтные пути только если у каких-то шоу path отсутствует
    missing_paths = [s for s in shows if not s.path]
    if missing_paths:
        settings = get_or_create_settings(db)
        for s in missing_paths:
            def_path = get_show_default_path(s, settings)
            if def_path:
                s.path = def_path
                db.add(s)
        try:
            db.commit()
        except Exception:
            db.rollback()

    show_ids = [s.id for s in shows]
    now = dt.datetime.utcnow()

    # Объединяем 4 раздельных запроса подсчёта в один сверхбыстрый агрегирующий запрос
    from sqlalchemy import case

    dl_condition = or_(
        Episode.status == EpisodeStatus.DOWNLOADED,
        and_(Episode.file_path.isnot(None), Episode.file_path != "")
    )
    downloading_condition = (Episode.status == EpisodeStatus.DOWNLOADING)
    upgrade_condition = (Episode.upgrade_requested == True)

    stats_rows = (
        db.query(
            Episode.show_id,
            func.count(func.distinct(Episode.season_number)),
            func.count(Episode.id),
            func.sum(case((dl_condition, 1), else_=0)),
            func.sum(case((downloading_condition, 1), else_=0)),
            func.sum(case((upgrade_condition, 1), else_=0)),
        )
        .filter(Episode.show_id.in_(show_ids))
        .group_by(Episode.show_id)
        .all()
    )
    stats = {
        row[0]: (row[1] or 0, row[2] or 0, int(row[3] or 0), int(row[4] or 0), int(row[5] or 0))
        for row in stats_rows
    }

    next_airing_rows = (
        db.query(Episode.show_id, func.min(Episode.air_date))
        .filter(Episode.show_id.in_(show_ids), Episode.air_date.isnot(None), Episode.air_date >= now)
        .group_by(Episode.show_id)
        .all()
    )
    next_airing = dict(next_airing_rows)

    out = []
    for show in shows:
        item = ShowOut.model_validate(show)
        s_count, ep_c, dl_c, dling_c, upg_c = stats.get(show.id, (0, 0, 0, 0, 0))
        item.seasons_count = s_count
        item.episodes_count = ep_c
        item.downloaded_episodes_count = dl_c
        item.downloading_episodes_count = dling_c
        item.has_upgrade_pending = bool(getattr(show, "upgrade_requested", False) or upg_c > 0)
        item.upgrade_requested = bool(getattr(show, "upgrade_requested", False))
        item.next_airing = next_airing.get(show.id) or show.premiere_date
        item.collection_title = show.collection.title if getattr(show, "collection", None) else None
        item.collection_backdrop_url = show.collection.backdrop_url if (getattr(show, "collection", None) and show.collection.backdrop_url) else None

        from app.services.cover_service import attach_version_to_cover_url
        ts_obj = getattr(show, "last_metadata_refresh_at", None) or getattr(show, "created_at", None)
        item.poster_url = attach_version_to_cover_url(item.poster_url, ts_obj)
        if item.collection_backdrop_url:
            c_obj = getattr(show, "collection", None)
            c_ts = getattr(c_obj, "last_metadata_refresh_at", None) or getattr(c_obj, "created_at", None) if c_obj else None
            item.collection_backdrop_url = attach_version_to_cover_url(item.collection_backdrop_url, c_ts)

        out.append(item)
    return out


@router.get("", response_model=list[ShowOut])
def list_shows(db: Session = Depends(get_db), current_user: User = Depends(require_permission("view_library"))):
    shows = db.query(Show).order_by(func.lower(Show.title)).all()
    return _attach_computed_fields(db, shows)


def _find_duplicate_show(db: Session, title: str, metadata_source: Optional[str], metadata_id: Optional[str]) -> Optional[Show]:
    """Ищет существующий тайтл по metadata_id или нечувствительно к регистру названию."""
    if metadata_source and metadata_id:
        existing = (
            db.query(Show)
            .filter(Show.metadata_source == metadata_source, Show.metadata_id == metadata_id)
            .first()
        )
        if existing:
            return existing
    return db.query(Show).filter(func.lower(Show.title) == title.lower().strip()).first()


@router.post("", response_model=ShowOut, status_code=201)
async def create_show(
    payload: ShowCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_library")),
):
    clean_title, clean_year = clean_show_title_and_year(payload.title, payload.year)
    existing = _find_duplicate_show(db, clean_title, payload.metadata_source, payload.metadata_id)
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Тайтл «{clean_title}» уже есть в библиотеке (ID: {existing.id})",
        )

    settings = get_or_create_settings(db)
    qp_id = payload.quality_profile_id
    if qp_id is None:
        if payload.content_type == "movie":
            qp_id = getattr(settings, "default_quality_profile_movie_id", None)
        elif payload.content_type == "anime":
            qp_id = getattr(settings, "default_quality_profile_anime_id", None)
        else:
            qp_id = getattr(settings, "default_quality_profile_series_id", None)

    show = Show(
        title=clean_title,
        year=clean_year,
        metadata_source=payload.metadata_source,
        metadata_id=payload.metadata_id,
        overview=payload.overview,
        poster_url=payload.poster_url,
        path=payload.path,
        quality_profile_id=qp_id,
        content_type=payload.content_type,
        edition=payload.edition,
        collection_id=payload.collection_id,
        collection_order=payload.collection_order,
        imdb_id=payload.imdb_id,
        tmdb_id=payload.tmdb_id,
        tvdb_id=payload.tvdb_id,
        tvmaze_id=payload.tvmaze_id,
        mal_id=payload.mal_id,
        anilist_id=payload.anilist_id,
        anidb_id=payload.anidb_id,
        shikimori_id=payload.shikimori_id,
        trailer_url=payload.trailer_url,
    )
    if not show.path:
        show.path = get_show_default_path(show, settings)
    db.add(show)
    db.flush()  # получаем show.id до коммита

    added_aliases = set()
    current_p = 1
    for alias_in in payload.aliases:
        if alias_in.text.lower() not in added_aliases:
            added_aliases.add(alias_in.text.lower())
            p = alias_in.priority if alias_in.priority is not None else current_p
            db.add(Alias(
                show_id=show.id,
                text=alias_in.text,
                language=alias_in.language,
                source=alias_in.source,
                priority=p,
                season_number=alias_in.season_number,
                episode_start=alias_in.episode_start,
                episode_end=alias_in.episode_end,
                episode_offset=alias_in.episode_offset,
            ))
            current_p += 1

    clean_p_title = (payload.title or "").strip()
    clean_no_yr = re.sub(r"\s*\(\d{4}\)$|\s+\d{4}$", "", clean_p_title).strip()
    if clean_no_yr and clean_no_yr.lower() not in added_aliases:
        added_aliases.add(clean_no_yr.lower())
        db.add(Alias(show_id=show.id, text=clean_no_yr, language="en", source="auto", priority=1))

    # Для фильмов создаём одну запись Episode (S01E01) для мониторинга и поиска
    if payload.content_type == "movie":
        now = dt.datetime.utcnow()
        premiere = None
        status = EpisodeStatus.WANTED
        db.add(Episode(
            show_id=show.id, season_number=1, episode_number=1,
            title=payload.title, air_date=premiere, status=status,
        ))

    db.commit()
    db.refresh(show)

    if show.poster_url:
        p_raw = str(show.poster_url).strip()
        if p_raw.startswith(("http://", "https://", "data:image/")):
            if p_raw.startswith(("http://", "https://")):
                show.poster_source_url = p_raw
            from app.services.cover_service import download_and_store_show_cover
            local_cover = await download_and_store_show_cover(show.id, p_raw)
            if local_cover:
                show.poster_url = local_cover
                db.commit()
                db.refresh(show)

    from app.services.blocklist_service import relink_blocklist_for_show
    try:
        relink_blocklist_for_show(db, show)
    except Exception as exc:
        logger.debug("Ошибка привязки черного списка к новому шоу %s: %s", show.id, exc)

    from app.services.notifications import notify_all
    from app.services.show_links import build_series_add_notification_message
    try:
        msg = build_series_add_notification_message(db, show)
        await notify_all(
            db,
            "series_add",
            msg,
        )
    except Exception:
        pass

    return ShowOut.model_validate(show)


class BulkSwitchTitleLanguageRequest(BaseModel):
    show_ids: list[int]
    target_language: str  # "ru" | "en"


class UpdatedShowTitleItem(BaseModel):
    id: int
    title: str
    old_title: str


class BulkSwitchTitleLanguageResponse(BaseModel):
    total: int
    updated: int
    skipped: int
    not_found: int
    updated_shows: list[UpdatedShowTitleItem]


@router.post(
    "/bulk-switch-title-language",
    response_model=BulkSwitchTitleLanguageResponse,
    summary="Массовое переключение языка названий выбранных тайтлов (RU / EN)",
)
async def bulk_switch_title_language(
    payload: BulkSwitchTitleLanguageRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_library")),
):
    target_lang = (payload.target_language or "").strip().lower()
    if target_lang not in ("ru", "en"):
        raise HTTPException(400, "Поддерживаются только языки 'ru' и 'en'")

    updated_shows: list[UpdatedShowTitleItem] = []
    skipped_count = 0
    not_found_count = 0

    from app.services.metadata import SkyHookClient, RadarrClient

    for s_id in payload.show_ids:
        show = db.get(Show, s_id)
        if not show:
            continue

        curr_title = (show.title or "").strip()
        is_curr_cyrillic = any('\u0400' <= c <= '\u04ff' for c in curr_title)

        if target_lang == "ru":
            if is_curr_cyrillic:
                skipped_count += 1
                continue

            candidate_ru = None
            candidate_alias_obj = None
            for a in (show.aliases or []):
                if a.text and any('\u0400' <= c <= '\u04ff' for c in a.text):
                    candidate_ru = a.text.strip()
                    candidate_alias_obj = a
                    break

            if not candidate_ru:
                try:
                    ext_id = show.metadata_id or (f"tvdb:{show.tvdb_id}" if show.tvdb_id else None) or (f"tmdb:{show.tmdb_id}" if show.tmdb_id else None)
                    if ext_id:
                        if show.content_type == "movie":
                            client = RadarrClient(overview_language="ru", title_language="ru")
                        else:
                            client = SkyHookClient(overview_language="ru", title_language="ru")
                        details = await client.get_details(ext_id)
                        if details and details.titles_by_lang and details.titles_by_lang.get("ru"):
                            candidate_ru = details.titles_by_lang["ru"].strip()
                        elif details and details.title and any('\u0400' <= c <= '\u04ff' for c in details.title):
                            candidate_ru = details.title.strip()
                        elif details and details.original_title and any('\u0400' <= c <= '\u04ff' for c in details.original_title):
                            candidate_ru = details.original_title.strip()
                except Exception:
                    pass

            if candidate_ru and candidate_ru.lower() != curr_title.lower():
                old_title = show.title
                show.title = candidate_ru
                existing_texts = {a.text.strip().lower() for a in show.aliases}
                if old_title.strip().lower() not in existing_texts:
                    db.add(Alias(show_id=show.id, text=old_title, language="en"))
                if candidate_alias_obj:
                    db.delete(candidate_alias_obj)
                else:
                    for a in list(show.aliases):
                        if a.text.strip().lower() == candidate_ru.lower():
                            db.delete(a)
                db.add(show)
                updated_shows.append(UpdatedShowTitleItem(id=show.id, title=candidate_ru, old_title=old_title))
            else:
                not_found_count += 1

        elif target_lang == "en":
            if not is_curr_cyrillic:
                skipped_count += 1
                continue

            candidate_en = None
            candidate_alias_obj = None
            for a in (show.aliases or []):
                if a.text and not any('\u0400' <= c <= '\u04ff' for c in a.text):
                    candidate_en = a.text.strip()
                    candidate_alias_obj = a
                    break

            if not candidate_en:
                try:
                    ext_id = show.metadata_id or (f"tvdb:{show.tvdb_id}" if show.tvdb_id else None) or (f"tmdb:{show.tmdb_id}" if show.tmdb_id else None)
                    if ext_id:
                        if show.content_type == "movie":
                            client = RadarrClient(overview_language="en", title_language="en")
                        else:
                            client = SkyHookClient(overview_language="en", title_language="en")
                        details = await client.get_details(ext_id)
                        if details and details.titles_by_lang and details.titles_by_lang.get("en"):
                            candidate_en = details.titles_by_lang["en"].strip()
                        elif details and details.title and not any('\u0400' <= c <= '\u04ff' for c in details.title):
                            candidate_en = details.title.strip()
                        elif details and details.original_title and not any('\u0400' <= c <= '\u04ff' for c in details.original_title):
                            candidate_en = details.original_title.strip()
                except Exception:
                    pass

            if candidate_en and candidate_en.lower() != curr_title.lower():
                old_title = show.title
                show.title = candidate_en
                existing_texts = {a.text.strip().lower() for a in show.aliases}
                if old_title.strip().lower() not in existing_texts:
                    db.add(Alias(show_id=show.id, text=old_title, language="ru"))
                if candidate_alias_obj:
                    db.delete(candidate_alias_obj)
                else:
                    for a in list(show.aliases):
                        if a.text.strip().lower() == candidate_en.lower():
                            db.delete(a)
                db.add(show)
                updated_shows.append(UpdatedShowTitleItem(id=show.id, title=candidate_en, old_title=old_title))
            else:
                not_found_count += 1

    if updated_shows:
        db.commit()

    return BulkSwitchTitleLanguageResponse(
        total=len(payload.show_ids),
        updated=len(updated_shows),
        skipped=skipped_count,
        not_found=not_found_count,
        updated_shows=updated_shows,
    )


@router.get("/{show_id}", response_model=ShowOut, summary="Получить информацию о тайтле")
def get_show(show_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_permission("view_library"))):
    """Возвращает подробную информацию о тайтле со списком серий, алиасов и прогрессом скачивания."""
    show = db.get(Show, show_id)
    if not show:
        raise HTTPException(404, "Show not found")

    from app.services.metadata import trigger_show_metadata_refresh_if_needed
    trigger_show_metadata_refresh_if_needed(show.id, db)

    needs_commit = False
    try:
        today = dt.date.today()
        for ep in (getattr(show, "episodes", None) or []):
            air_d = getattr(ep, "air_date", None)
            if isinstance(air_d, dt.datetime):
                air_d = air_d.date()
            is_ep_ignored = (
                getattr(ep, "status", None) == EpisodeStatus.IGNORED
                or getattr(ep, "monitor_status", None) == MonitorStatus.IGNORED
                or not getattr(show, "monitored", True)
            )
            target_default_status = (
                EpisodeStatus.IGNORED
                if is_ep_ignored
                else (EpisodeStatus.UNAIRED if air_d and air_d > today else EpisodeStatus.WANTED)
            )
            if target_default_status == EpisodeStatus.UNAIRED and not getattr(ep, "file_path", None) and ep.status != EpisodeStatus.DOWNLOADED:
                if not ep.monitored:
                    ep.monitored = True
                    needs_commit = True

            # Проверяем физический файл серии на диске
            if getattr(ep, "file_path", None):
                file_exists = False
                try:
                    file_exists = os.path.exists(ep.file_path)
                except Exception:
                    file_exists = False

                if file_exists:
                    if ep.status != EpisodeStatus.DOWNLOADED and ep.status != EpisodeStatus.DOWNLOADING:
                        ep.status = EpisodeStatus.DOWNLOADED
                        ep.monitored = False
                        ep.download_progress = 1.0
                        needs_commit = True
                    if not ep.downloaded_quality and ep.file_path:
                        from app.services.quality import parse_quality
                        q_parsed = parse_quality(os.path.basename(ep.file_path))
                        if q_parsed and q_parsed.name:
                            ep.downloaded_quality = q_parsed.name
                            needs_commit = True
                else:
                    # Файл был удален с диска пользователем: сбрасываем путь, качество, MediaInfo и статус
                    ep.file_path = None
                    ep.downloaded_quality = None
                    ep.file_size_bytes = None
                    ep.video_codec = None
                    ep.audio_codec = None
                    ep.audio_channels = None
                    ep.dynamic_range = None
                    ep.release_group = None
                    ep.download_progress = 0.0
                    if ep.status == EpisodeStatus.DOWNLOADED:
                        ep.status = target_default_status
                    needs_commit = True
            else:
                # Файла нет: если серия не скачивается активно в данный момент, очищаем качество и MediaInfo
                is_active_download = ep.status == EpisodeStatus.DOWNLOADING and bool(getattr(ep, "torrent_hash", None))
                if not is_active_download:
                    if getattr(ep, "downloaded_quality", None) is not None or getattr(ep, "file_size_bytes", None) is not None or getattr(ep, "video_codec", None) is not None:
                        ep.downloaded_quality = None
                        ep.file_size_bytes = None
                        ep.video_codec = None
                        ep.audio_codec = None
                        ep.audio_channels = None
                        ep.dynamic_range = None
                        ep.release_group = None
                        needs_commit = True
                    if ep.status == EpisodeStatus.DOWNLOADED:
                        ep.status = target_default_status
                        ep.download_progress = 0.0
                        needs_commit = True
                    elif ep.status == EpisodeStatus.DOWNLOADING:
                        ep.status = target_default_status
                        ep.download_progress = 0.0
                        needs_commit = True

        if needs_commit:
            try:
                db.commit()
            except Exception:
                db.rollback()
    except Exception:
        pass

    return _attach_computed_fields(db, [show])[0]


@router.delete("/{show_id}", status_code=204, summary="Удалить тайтл из библиотеки")
async def delete_show(
    show_id: int,
    delete_files: bool = Query(False, description="Удалить карточку вместе с физическими файлами и директорией на диске"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_library")),
):
    """
    Удаление карточки тайтла из библиотеки.
    Если delete_files=True, безвозвратно удаляет физические файлы серий и корневую папку тайтла на диске.
    Если delete_files=False, удаляется только запись из базы данных, а файлы на диске сохраняются.
    """
    show = db.get(Show, show_id)
    if not show:
        raise HTTPException(404, "Show not found")

    show_title = show.title
    show_path = show.path
    episodes = db.query(Episode).filter_by(show_id=show.id).all()

    if delete_files:
        settings = get_or_create_settings(db)
        _validate_destructive_media_paths(
            settings,
            [show_path, *(ep.file_path for ep in episodes)],
        )

        def _remove_files_sync(f_paths: list[str], s_path: Optional[str]):
            for f in f_paths:
                if f and os.path.isfile(f):
                    try:
                        os.remove(f)
                    except Exception:
                        pass
            if s_path and os.path.isdir(s_path):
                try:
                    shutil.rmtree(s_path, ignore_errors=True)
                except Exception:
                    pass

        import asyncio
        file_paths_to_delete = [ep.file_path for ep in episodes if ep.file_path]
        await asyncio.to_thread(_remove_files_sync, file_paths_to_delete, show_path)

    # 3. Очищаем зависимые записи истории загрузок, слежения и логов перед удалением шоу
    try:
        from app.models.db import DownloadHistory, TrackedRelease, ReleaseLog
        db.query(DownloadHistory).filter(DownloadHistory.show_id == show.id).delete(synchronize_session=False)
        db.query(TrackedRelease).filter(TrackedRelease.show_id == show.id).delete(synchronize_session=False)
        db.query(ReleaseLog).filter(ReleaseLog.show_id == show.id).delete(synchronize_session=False)
    except Exception:
        pass

    coll_id = getattr(show, "collection_id", None)

    db.delete(show)
    db.commit()

    if coll_id:
        from app.services.collection_service import cleanup_empty_collections
        cleanup_empty_collections(db, coll_id)

    from app.services.auto_search import clear_rejected_cache_for_show
    clear_rejected_cache_for_show(show_id)

    from app.services.cover_service import delete_show_cover
    delete_show_cover(show_id)

    log_audit(
        db,
        "show.delete",
        f"Удалена карточка «{show_title}» (удаление файлов с диска: {'да' if delete_files else 'нет'})",
        username=getattr(current_user, "username", "admin"),
        user=current_user,
    )

    from app.services.notifications import notify_all
    msg = f"🗑 Удалена карточка «{show_title}» (вместе с файлами на диске)" if delete_files else f"🗑 Удалена карточка «{show_title}» (файлы сохранены на диске)"
    try:
        await notify_all(db, "series_delete", msg)
    except Exception:
        pass


@router.post("/{show_id}/delete-content", response_model=DeleteContentResponse, summary="Гранулярное удаление тайтла, сезонов или серий")
async def delete_content(
    show_id: int,
    payload: DeleteContentPayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_library")),
):
    """
    Гранулярное удаление контента:
    - delete_mode='show': удаляет тайтл целиком (с файлами или без)
    - delete_mode='seasons': удаляет файлы выбранных сезонов, сбрасывает статус серий в WANTED (В поиске)
    - delete_mode='episodes': удаляет файлы выбранных серий, сбрасывает статус серий в WANTED (В поиске)
    """
    show = db.get(Show, show_id)
    if not show:
        raise HTTPException(404, "Show not found")

    deleted_files = 0
    affected_eps = 0

    if payload.delete_mode == "show":
        show_title = show.title
        show_path = show.path
        episodes = db.query(Episode).filter_by(show_id=show.id).all()
        affected_eps = len(episodes)

        if payload.delete_files:
            settings = get_or_create_settings(db)
            _validate_destructive_media_paths(
                settings,
                [show_path, *(ep.file_path for ep in episodes)],
            )

            def _remove_files_sync(f_paths: list[str], s_path: Optional[str]) -> int:
                count = 0
                for f in f_paths:
                    if f and os.path.isfile(f):
                        try:
                            os.remove(f)
                            count += 1
                        except Exception:
                            pass
                if s_path and os.path.isdir(s_path):
                    try:
                        shutil.rmtree(s_path, ignore_errors=True)
                    except Exception:
                        pass
                return count

            import asyncio
            file_paths_to_delete = [ep.file_path for ep in episodes if ep.file_path]
            deleted_files = await asyncio.to_thread(_remove_files_sync, file_paths_to_delete, show_path)

        # Очищаем зависимые записи истории загрузок, слежения и логов перед удалением шоу
        try:
            from app.models.db import DownloadHistory, TrackedRelease, ReleaseLog
            db.query(DownloadHistory).filter(DownloadHistory.show_id == show.id).delete(synchronize_session=False)
            db.query(TrackedRelease).filter(TrackedRelease.show_id == show.id).delete(synchronize_session=False)
            db.query(ReleaseLog).filter(ReleaseLog.show_id == show.id).delete(synchronize_session=False)
        except Exception:
            pass

        coll_id = getattr(show, "collection_id", None)

        db.delete(show)
        db.commit()

        if coll_id:
            from app.services.collection_service import cleanup_empty_collections
            cleanup_empty_collections(db, coll_id)

        from app.services.auto_search import clear_rejected_cache_for_show
        clear_rejected_cache_for_show(show_id)

        from app.services.cover_service import delete_show_cover
        delete_show_cover(show_id)

        log_audit(
            db,
            "show.delete",
            f"Удалена карточка «{show_title}» (удаление файлов с диска: {'да' if payload.delete_files else 'нет'})",
            username=getattr(current_user, "username", "admin"),
            user=current_user,
        )

        from app.services.notifications import notify_all
        msg = f"🗑 Удалена карточка «{show_title}» (вместе с файлами на диске)" if payload.delete_files else f"🗑 Удалена карточка «{show_title}» (файлы сохранены на диске)"
        try:
            await notify_all(db, "series_delete", msg)
        except Exception:
            pass

        return DeleteContentResponse(
            success=True,
            delete_mode="show",
            deleted_files_count=deleted_files,
            episodes_affected_count=affected_eps,
            message=f"Тайтл «{show_title}» успешно удален",
        )

    elif payload.delete_mode == "seasons":
        target_seasons = set(payload.season_numbers or [])
        if not target_seasons:
            raise HTTPException(400, "Не указаны номера сезонов для удаления")

        episodes = db.query(Episode).filter(
            Episode.show_id == show.id,
            Episode.season_number.in_(target_seasons)
        ).all()
        affected_eps = len(episodes)

        if payload.delete_files:
            settings = get_or_create_settings(db)
            _validate_destructive_media_paths(
                settings,
                [ep.file_path for ep in episodes],
            )

        season_folders_to_check = set()

        for ep in episodes:
            if ep.file_path:
                if payload.delete_files and os.path.isfile(ep.file_path):
                    try:
                        # Удаляем файл серии
                        fpath = ep.file_path
                        os.remove(fpath)
                        deleted_files += 1
                        season_folders_to_check.add(os.path.dirname(fpath))

                        # Удаляем сопутствующие файлы субтитров/аудио
                        fstem = os.path.splitext(fpath)[0]
                        parent_dir = os.path.dirname(fpath)
                        if os.path.isdir(parent_dir):
                            for sibling in os.listdir(parent_dir):
                                s_full = os.path.join(parent_dir, sibling)
                                if os.path.isfile(s_full) and s_full.startswith(fstem) and s_full != fpath:
                                    try:
                                        os.remove(s_full)
                                    except Exception:
                                        pass
                    except Exception:
                        pass

                ep.file_path = None
                ep.file_size = 0
                ep.quality = None
                ep.custom_formats = None
                ep.languages = None
                ep.progress = 0

            if payload.reset_to_wanted:
                ep.status = EpisodeStatus.WANTED
                ep.monitored = True

            db.add(ep)

        # Удаляем пустые папки сезонов
        if payload.delete_files:
            for s_dir in season_folders_to_check:
                if s_dir and os.path.isdir(s_dir):
                    try:
                        remaining_files = [f for f in os.listdir(s_dir) if not f.startswith(".")]
                        if not remaining_files:
                            shutil.rmtree(s_dir, ignore_errors=True)
                    except Exception:
                        pass

        db.commit()

        s_str = ", ".join(str(s) for s in sorted(target_seasons))
        log_audit(
            db,
            "show.delete_seasons",
            f"Удалены файлы сезонов {s_str} тайтла «{show.title}» ({affected_eps} серий, удалено файлов: {deleted_files}, сброс в поиск: {'да' if payload.reset_to_wanted else 'нет'})",
            username=getattr(current_user, "username", "admin"),
            user=current_user,
        )

        return DeleteContentResponse(
            success=True,
            delete_mode="seasons",
            deleted_files_count=deleted_files,
            episodes_affected_count=affected_eps,
            message=f"Сезоны {s_str} успешно удалены ({affected_eps} серий переведено в поиск)",
        )

    elif payload.delete_mode == "episodes":
        target_ep_ids = set(payload.episode_ids or [])
        if not target_ep_ids:
            raise HTTPException(400, "Не указаны ID серий для удаления")

        episodes = db.query(Episode).filter(
            Episode.show_id == show.id,
            Episode.id.in_(target_ep_ids)
        ).all()
        affected_eps = len(episodes)

        if payload.delete_files:
            settings = get_or_create_settings(db)
            _validate_destructive_media_paths(
                settings,
                [ep.file_path for ep in episodes],
            )

        for ep in episodes:
            if ep.file_path:
                if payload.delete_files and os.path.isfile(ep.file_path):
                    try:
                        fpath = ep.file_path
                        os.remove(fpath)
                        deleted_files += 1

                        # Удаляем сопутствующие файлы субтитров/аудио
                        fstem = os.path.splitext(fpath)[0]
                        parent_dir = os.path.dirname(fpath)
                        if os.path.isdir(parent_dir):
                            for sibling in os.listdir(parent_dir):
                                s_full = os.path.join(parent_dir, sibling)
                                if os.path.isfile(s_full) and s_full.startswith(fstem) and s_full != fpath:
                                    try:
                                        os.remove(s_full)
                                    except Exception:
                                        pass
                    except Exception:
                        pass

                ep.file_path = None
                ep.file_size = 0
                ep.quality = None
                ep.custom_formats = None
                ep.languages = None
                ep.progress = 0

            if payload.reset_to_wanted:
                ep.status = EpisodeStatus.WANTED
                ep.monitored = True

            db.add(ep)

        db.commit()

        log_audit(
            db,
            "show.delete_episodes",
            f"Удалены файлы {affected_eps} серий тайтла «{show.title}» (удалено файлов: {deleted_files}, сброс в поиск: {'да' if payload.reset_to_wanted else 'нет'})",
            username=getattr(current_user, "username", "admin"),
            user=current_user,
        )

        return DeleteContentResponse(
            success=True,
            delete_mode="episodes",
            deleted_files_count=deleted_files,
            episodes_affected_count=affected_eps,
            message=f"{affected_eps} серий успешно удалены и переведены в поиск",
        )

    else:
        raise HTTPException(400, f"Неизвестный режим удаления: {payload.delete_mode}")


@router.put("/{show_id}", response_model=ShowOut)
async def update_show(
    show_id: int,
    payload: ShowUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_library")),
):
    show = db.get(Show, show_id)
    if not show:
        raise HTTPException(404, "Show not found")
    dumped = payload.model_dump(exclude_unset=True)
    if "poster_url" in dumped and dumped["poster_url"]:
        p_val = str(dumped["poster_url"]).strip()
        if p_val.startswith("data:image/"):
            from app.services.cover_service import download_and_store_show_cover
            local_url = await download_and_store_show_cover(show.id, p_val)
            if local_url:
                dumped["poster_url"] = local_url
        elif p_val.startswith(("http://", "https://")):
            show.poster_source_url = p_val
            from app.services.cover_service import download_and_store_show_cover
            local_url = await download_and_store_show_cover(show.id, p_val)
            if local_url:
                dumped["poster_url"] = local_url
    if "title" in dumped or "year" in dumped:
        new_title, new_year = clean_show_title_and_year(dumped.get("title", show.title), dumped.get("year", show.year))
        if "title" in dumped:
            old_title = (show.title or "").strip()
            dumped["title"] = new_title
            if old_title and new_title and old_title.lower() != new_title.lower():
                existing_texts = {a.text.strip().lower() for a in show.aliases}
                if old_title.lower() not in existing_texts:
                    old_lang = "ru" if any('\u0400' <= c <= '\u04ff' for c in old_title) else "en"
                    db.add(Alias(show_id=show.id, text=old_title, language=old_lang))
                for a in list(show.aliases):
                    if a.text.strip().lower() == new_title.lower():
                        db.delete(a)
        if "year" in dumped:
            dumped["year"] = new_year
    old_coll_id = getattr(show, "collection_id", None)
    for field, value in dumped.items():
        setattr(show, field, value)
    if "ova_mode" in dumped or "content_type" in dumped:
        from app.services.auto_search import clear_rejected_cache_for_show
        clear_rejected_cache_for_show(show.id)
    db.add(show)
    db.commit()
    db.refresh(show)

    if old_coll_id and "collection_id" in dumped and dumped["collection_id"] != old_coll_id:
        from app.services.collection_service import cleanup_empty_collections
        cleanup_empty_collections(db, old_coll_id)

    return _attach_computed_fields(db, [show])[0]


@router.post("/{show_id}/aliases", response_model=AliasOut, status_code=201)
def add_alias(
    show_id: int,
    payload: AliasCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_library")),
):
    show = db.get(Show, show_id)
    if not show:
        raise HTTPException(404, "Show not found")
    
    clean_text = (payload.text or "").strip()
    if not clean_text:
        raise HTTPException(400, "Текст алиаса не может быть пустым")

    # Проверяем, существует ли уже такой алиас у тайтла
    existing_alias = (
        db.query(Alias)
        .filter(Alias.show_id == show_id, func.lower(Alias.text) == clean_text.lower())
        .first()
    )
    if existing_alias:
        if payload.language:
            existing_alias.language = payload.language
        if payload.source:
            existing_alias.source = payload.source
        if payload.priority is not None:
            existing_alias.priority = payload.priority
        if payload.season_number is not None:
            existing_alias.season_number = payload.season_number
        if payload.episode_start is not None:
            existing_alias.episode_start = payload.episode_start
        if payload.episode_end is not None:
            existing_alias.episode_end = payload.episode_end
        if payload.episode_offset is not None:
            existing_alias.episode_offset = payload.episode_offset
        db.commit()
        db.refresh(existing_alias)
        from app.services.auto_search import clear_rejected_cache_for_show
        clear_rejected_cache_for_show(show_id, db)
        return existing_alias

    # Приоритет по умолчанию — в конец очереди поиска
    priority = payload.priority
    if priority is None:
        max_priority = db.query(func.max(Alias.priority)).filter(Alias.show_id == show_id).scalar()
        priority = (max_priority or 0) + 1
    alias = Alias(
        show_id=show_id,
        text=clean_text,
        language=payload.language,
        source=payload.source,
        priority=priority,
        season_number=payload.season_number,
        episode_start=payload.episode_start,
        episode_end=payload.episode_end,
        episode_offset=payload.episode_offset,
    )
    try:
        db.add(alias)
        db.commit()
        db.refresh(alias)
    except IntegrityError:
        db.rollback()
        existing = (
            db.query(Alias)
            .filter(Alias.show_id == show_id, func.lower(Alias.text) == clean_text.lower())
            .first()
        )
        if existing:
            return existing
        raise HTTPException(400, "Алиас с таким названием уже существует для этого тайтла")

    from app.services.auto_search import clear_rejected_cache_for_show
    clear_rejected_cache_for_show(show_id, db)
    return alias


@router.put("/{show_id}/aliases/{alias_id}", response_model=AliasOut)
def update_alias(
    show_id: int,
    alias_id: int,
    payload: AliasUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_library")),
):
    """Редактирование текста и приоритета поискового алиаса."""
    alias = db.get(Alias, alias_id)
    if not alias or alias.show_id != show_id:
        raise HTTPException(404, "Alias not found")
    dumped = payload.model_dump(exclude_unset=True)
    if "text" in dumped:
        text = (dumped["text"] or "").strip()
        if not text:
            raise HTTPException(400, "Текст алиаса не может быть пустым")
        duplicate = (
            db.query(Alias)
            .filter(
                Alias.show_id == show_id,
                func.lower(Alias.text) == text.lower(),
                Alias.id != alias_id,
            )
            .first()
        )
        if duplicate:
            raise HTTPException(400, "Алиас с таким текстом уже существует для этого тайтла")
        alias.text = text
    if "language" in dumped:
        alias.language = dumped["language"]
    if "priority" in dumped:
        alias.priority = dumped["priority"]
    for field in ("season_number", "episode_start", "episode_end", "episode_offset"):
        if field in dumped:
            setattr(alias, field, dumped[field])
    try:
        db.add(alias)
        db.commit()
        db.refresh(alias)
    except IntegrityError:
        db.rollback()
        raise HTTPException(400, "Алиас с таким текстом уже существует для этого тайтла")

    from app.services.auto_search import clear_rejected_cache_for_show
    clear_rejected_cache_for_show(show_id, db)
    return alias


@router.delete("/{show_id}/aliases/{alias_id}", status_code=204)
def delete_alias(
    show_id: int,
    alias_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_library")),
):
    """Удаление поискового алиаса."""
    alias = db.get(Alias, alias_id)
    if not alias or alias.show_id != show_id:
        raise HTTPException(404, "Alias not found")
    db.delete(alias)
    db.commit()
    from app.services.auto_search import clear_rejected_cache_for_show
    clear_rejected_cache_for_show(show_id, db)


# --- Разделитель сезона (Season Splitter) ---


@router.get("/{show_id}/season-splits", response_model=list[SeasonSplitOut])
def list_season_splits(
    show_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("view_library")),
):
    show = db.get(Show, show_id)
    if not show:
        raise HTTPException(404, "Show not found")
    return db.query(SeasonSplit).filter(SeasonSplit.show_id == show_id).order_by(SeasonSplit.season_number).all()


@router.post("/{show_id}/season-splits", response_model=SeasonSplitOut, status_code=201)
def create_season_split(
    show_id: int,
    payload: SeasonSplitCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_library")),
):
    show = db.get(Show, show_id)
    if not show:
        raise HTTPException(404, "Show not found")

    split_name = payload.name.strip() or f"S{payload.season_number:02d} Split"
    split = SeasonSplit(
        show_id=show_id,
        name=split_name,
        season_number=payload.season_number,
    )
    db.add(split)
    db.flush()

    for p in payload.parts:
        part = SeasonSplitPart(
            split_id=split.id,
            part_type=p.part_type or "season",
            target_number=p.target_number or 1,
            episode_start=p.episode_start or 1,
            episode_end=p.episode_end or 1,
            episode_offset=p.episode_offset if p.episode_offset is not None else 0,
            aliases=(p.aliases or "").strip(),
        )
        db.add(part)

    db.commit()
    db.refresh(split)
    from app.services.auto_search import clear_rejected_cache_for_show
    clear_rejected_cache_for_show(show_id, db)
    return split


@router.put("/{show_id}/season-splits/{split_id}", response_model=SeasonSplitOut)
def update_season_split(
    show_id: int,
    split_id: int,
    payload: SeasonSplitUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_library")),
):
    split = db.get(SeasonSplit, split_id)
    if not split or split.show_id != show_id:
        raise HTTPException(404, "SeasonSplit not found")

    if payload.name is not None:
        split.name = payload.name.strip()
    if payload.season_number is not None:
        split.season_number = payload.season_number

    if payload.parts is not None:
        # Обновляем relationship как единое целое. Bulk DELETE оставляет уже
        # загруженные объекты в split.parts и последующий db.add(split) пытается
        # повторно сохранить экземпляры, помеченные как deleted.
        split.parts.clear()
        db.flush()
        for p in payload.parts:
            part = SeasonSplitPart(
                part_type=p.part_type or "season",
                target_number=p.target_number or 1,
                episode_start=p.episode_start or 1,
                episode_end=p.episode_end or 1,
                episode_offset=p.episode_offset if p.episode_offset is not None else 0,
                aliases=(p.aliases or "").strip(),
            )
            split.parts.append(part)

    db.add(split)
    db.commit()
    db.refresh(split)
    from app.services.auto_search import clear_rejected_cache_for_show
    clear_rejected_cache_for_show(show_id, db)
    return split


@router.delete("/{show_id}/season-splits/{split_id}", status_code=204)
def delete_season_split(
    show_id: int,
    split_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_library")),
):
    split = db.get(SeasonSplit, split_id)
    if not split or split.show_id != show_id:
        raise HTTPException(404, "SeasonSplit not found")
    db.delete(split)
    db.commit()
    from app.services.auto_search import clear_rejected_cache_for_show
    clear_rejected_cache_for_show(show_id, db)


@router.get("/{show_id}/episodes", response_model=list[EpisodeOut])
def list_episodes(show_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_permission("view_library"))):
    show = db.get(Show, show_id)
    if not show:
        raise HTTPException(404, "Show not found")

    from app.services.metadata import trigger_show_metadata_refresh_if_needed
    trigger_show_metadata_refresh_if_needed(show.id, db)

    episodes = (
        db.query(Episode)
        .filter(Episode.show_id == show_id)
        .order_by(Episode.season_number, Episode.episode_number)
        .all()
    )
    needs_commit = False
    today = dt.date.today()
    out = []
    for ep in episodes:
        air_d = getattr(ep, "air_date", None)
        if isinstance(air_d, dt.datetime):
            air_d = air_d.date()
        is_ep_ignored = (
            getattr(ep, "status", None) == EpisodeStatus.IGNORED
            or getattr(ep, "monitor_status", None) == MonitorStatus.IGNORED
            or not getattr(show, "monitored", True)
        )
        target_default_status = (
            EpisodeStatus.IGNORED
            if is_ep_ignored
            else (EpisodeStatus.UNAIRED if air_d and air_d > today else EpisodeStatus.WANTED)
        )
        if target_default_status == EpisodeStatus.UNAIRED and not getattr(ep, "file_path", None) and ep.status != EpisodeStatus.DOWNLOADED:
            if not ep.monitored:
                ep.monitored = True
                needs_commit = True

        has_real_file = False
        if getattr(ep, "file_path", None):
            try:
                has_real_file = os.path.exists(ep.file_path)
            except Exception:
                has_real_file = False

        if getattr(ep, "file_path", None) and not has_real_file:
            ep.file_path = None
            ep.downloaded_quality = None
            ep.file_size_bytes = None
            ep.video_codec = None
            ep.audio_codec = None
            ep.audio_channels = None
            ep.dynamic_range = None
            ep.release_group = None
            ep.download_progress = 0.0
            if ep.status == EpisodeStatus.DOWNLOADED:
                ep.status = target_default_status
            needs_commit = True
        elif getattr(ep, "file_path", None) and has_real_file:
            if not ep.downloaded_quality:
                from app.services.quality import parse_quality
                q_parsed = parse_quality(os.path.basename(ep.file_path))
                if q_parsed and q_parsed.name:
                    ep.downloaded_quality = q_parsed.name
                    needs_commit = True
        elif not getattr(ep, "file_path", None):
            if getattr(ep, "downloaded_quality", None) is not None or getattr(ep, "video_codec", None) is not None:
                ep.downloaded_quality = None
                ep.file_size_bytes = None
                ep.video_codec = None
                ep.audio_codec = None
                ep.audio_channels = None
                ep.dynamic_range = None
                ep.release_group = None
                needs_commit = True
            if ep.status == EpisodeStatus.DOWNLOADED:
                ep.status = target_default_status
                ep.download_progress = 0.0
                needs_commit = True
            elif ep.status == EpisodeStatus.DOWNLOADING:
                if not getattr(ep, "torrent_hash", None):
                    ep.status = target_default_status
                    ep.download_progress = 0.0
                    needs_commit = True

        ep_out = EpisodeOut.model_validate(ep)
        ep_out.has_file = has_real_file
        if not has_real_file:
            ep_out.downloaded_quality = None
            ep_out.video_codec = None
            ep_out.audio_codec = None
            ep_out.dynamic_range = None
            ep_out.release_group = None
            ep_out.file_path = None
        out.append(ep_out)

    if needs_commit:
        try:
            db.commit()
        except Exception:
            db.rollback()
    return out


@router.put("/{show_id}/monitor")
def set_show_monitored(
    show_id: int,
    monitored: bool,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_library")),
):
    show = db.get(Show, show_id)
    if not show:
        raise HTTPException(404, "Show not found")
    show.monitored = monitored
    db.add(show)
    if not monitored:
        from app.models.db import TrackedRelease
        db.query(TrackedRelease).filter(TrackedRelease.show_id == show_id).update({TrackedRelease.active: False}, synchronize_session=False)
    if getattr(show, "content_type", None) == "movie":
        for ep in (getattr(show, "episodes", None) or []):
            ep.monitored = monitored
            db.add(ep)
    db.commit()
    return {"show_id": show_id, "monitored": monitored}


@router.put("/{show_id}/all_seasons/monitor", summary="Массово изменить статус мониторинга всех сезонов")
def set_all_seasons_monitored(
    show_id: int,
    monitored: bool,
    include_unaired: bool = Query(True, description="Переводить невышедшие серии в статус WANTED (в поиске)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_library")),
):
    """Массово переключает статус всех сезонов и серий тайтла (WANTED <-> IGNORED)."""
    show = db.get(Show, show_id)
    if not show:
        raise HTTPException(404, "Show not found")

    show.monitored = monitored
    db.add(show)
    if not monitored:
        from app.models.db import TrackedRelease
        db.query(TrackedRelease).filter(TrackedRelease.show_id == show_id).update({TrackedRelease.active: False}, synchronize_session=False)

    episodes = db.query(Episode).filter(Episode.show_id == show_id).all()
    today = dt.date.today()
    affected = 0
    for ep in episodes:
        ep.monitored = monitored
        file_path = getattr(ep, "file_path", None)
        has_file = False
        if file_path:
            try:
                has_file = os.path.exists(file_path)
            except Exception:
                has_file = False

        status = getattr(ep, "status", None)
        if status in (EpisodeStatus.DOWNLOADED, EpisodeStatus.DOWNLOADING, "downloaded", "downloading") or has_file:
            # Скачанные или скачивающиеся серии сохраняют свой статус, обновляется только флаг monitored
            if has_file and status not in (EpisodeStatus.DOWNLOADING, "downloading"):
                ep.status = EpisodeStatus.DOWNLOADED
        else:
            if monitored:
                air_d = getattr(ep, "air_date", None)
                if isinstance(air_d, dt.datetime):
                    air_d = air_d.date()
                if air_d and air_d > today:
                    ep.status = EpisodeStatus.UNAIRED
                else:
                    ep.status = EpisodeStatus.WANTED
            else:
                ep.status = EpisodeStatus.IGNORED
            affected += 1
        db.add(ep)

    db.commit()
    return {"show_id": show_id, "monitored": monitored, "affected": affected}


@router.put("/{show_id}/unaired/monitor", summary="Массово изменить статус мониторинга невышедших серий")
def set_unaired_monitored(
    show_id: int,
    monitored: bool = Query(True, description="True = WANTED (в поиске), False = IGNORED"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_library")),
):
    """Переводит все будущие/невышедшие серии тайтла в статус UNAIRED/WANTED или IGNORED."""
    show = db.get(Show, show_id)
    if not show:
        raise HTTPException(404, "Show not found")

    if monitored:
        show.monitored = True
        db.add(show)

    today = dt.date.today()
    episodes = db.query(Episode).filter(Episode.show_id == show_id).all()
    affected = 0
    for ep in episodes:
        status = getattr(ep, "status", None)
        file_path = getattr(ep, "file_path", None)
        if status in (EpisodeStatus.DOWNLOADED, EpisodeStatus.DOWNLOADING, "downloaded", "downloading") or (file_path and os.path.exists(file_path)):
            continue
        air_d = getattr(ep, "air_date", None)
        if isinstance(air_d, dt.datetime):
            air_d = air_d.date()
        is_unaired = (air_d and air_d > today) or status in (EpisodeStatus.UNAIRED, "unaired")
        if is_unaired:
            ep.monitored = monitored
            if monitored:
                ep.status = EpisodeStatus.UNAIRED
            else:
                ep.status = EpisodeStatus.IGNORED
            db.add(ep)
            affected += 1

    db.commit()
    return {"show_id": show_id, "monitored": monitored, "affected": affected}


@router.put("/{show_id}/seasons/{season_number}/monitor")
def set_season_monitored(
    show_id: int,
    season_number: int,
    monitored: bool,
    include_unaired: bool = Query(True, description="Включать невышедшие серии в статус WANTED"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_library")),
):
    """Массово включает/выключает мониторинг всех серий сезона (переключает WANTED <-> IGNORED)."""
    episodes = (
        db.query(Episode)
        .filter(Episode.show_id == show_id, Episode.season_number == season_number)
        .all()
    )
    if not episodes:
        raise HTTPException(404, "Season not found")

    today = dt.date.today()
    affected = 0
    for ep in episodes:
        ep.monitored = monitored
        file_path = getattr(ep, "file_path", None)
        has_file = False
        if file_path:
            try:
                has_file = os.path.exists(file_path)
            except Exception:
                has_file = False

        status = getattr(ep, "status", None)
        if status in (EpisodeStatus.DOWNLOADED, EpisodeStatus.DOWNLOADING, "downloaded", "downloading") or has_file:
            if has_file and status not in (EpisodeStatus.DOWNLOADING, "downloading"):
                ep.status = EpisodeStatus.DOWNLOADED
        else:
            if monitored:
                air_d = getattr(ep, "air_date", None)
                if isinstance(air_d, dt.datetime):
                    air_d = air_d.date()
                if air_d and air_d > today:
                    ep.status = EpisodeStatus.UNAIRED
                else:
                    ep.status = EpisodeStatus.WANTED
            else:
                ep.status = EpisodeStatus.IGNORED
            affected += 1
        db.add(ep)
    db.commit()
    return {"show_id": show_id, "season": season_number, "monitored": monitored, "affected": affected}


@router.post("/{show_id}/search")
@router.post("/{show_id}/auto-search")
async def force_search_show(
    show_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manual_search")),
):
    """
    Принудительный автопоиск: сразу ищет и захватывает лучшие релизы для всех
    wanted-серий этого шоу, не дожидаясь плановой джобы (каждые 15 минут).
    """
    from app.services.auto_search import search_and_grab_show, clear_rejected_cache_for_show

    show = db.get(Show, show_id)
    if not show:
        raise HTTPException(404, "Show not found")

    clear_rejected_cache_for_show(show_id, db)

    try:
        result = await search_and_grab_show(db, show)
        try:
            db.refresh(show)
        except Exception:
            pass
        return {
            "show_id": show_id,
            "grabbed": result.get("grabbed", []),
            "status": show.last_search_result,
            "last_search_at": show.last_search_at,
        }
    except Exception as exc:
        try:
            db.rollback()
        except Exception:
            pass
        logger.exception("Ошибка принудительного автопоиска шоу %s: %s", show_id, exc)
        return {
            "show_id": show_id,
            "grabbed": [],
            "status": f"Ошибка поиска: {exc}",
            "last_search_at": None,
        }


class SearchEpisodesIn(BaseModel):
    episode_ids: list[int]


@router.post("/{show_id}/search-episode")
@router.post("/{show_id}/search-episodes")
async def search_selected_episodes(
    show_id: int,
    payload: SearchEpisodesIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manual_search")),
):
    """Поиск и скачивание ТОЛЬКО выбранных пользователем серий (не всего сезона) —
    отмечаются флажками в карточке видео."""
    from app.services.auto_search import search_and_grab_show, clear_rejected_cache_for_show

    show = db.get(Show, show_id)
    if not show:
        raise HTTPException(404, "Show not found")
    if not payload.episode_ids:
        raise HTTPException(400, "Не выбрано ни одной серии")

    clear_rejected_cache_for_show(show_id, db)

    episodes = db.query(Episode).filter(Episode.id.in_(payload.episode_ids), Episode.show_id == show_id).all()
    if not episodes:
        raise HTTPException(404, "Серии не найдены")

    today = dt.date.today()
    for ep in episodes:
        ep.monitored = True
        ep_air = getattr(ep, "air_date", None)
        if isinstance(ep_air, dt.datetime):
            ep_air = ep_air.date()
        is_ep_future = bool(ep_air and ep_air > today)
        if ep.status in (EpisodeStatus.IGNORED, EpisodeStatus.MISSING) and not is_ep_future:
            ep.status = EpisodeStatus.WANTED
        db.add(ep)
    db.commit()

    try:
        result = await search_and_grab_show(db, show, episode_ids=set(payload.episode_ids))
        try:
            db.refresh(show)
        except Exception:
            pass
        grabbed_ids = {g["episode_id"] for g in result.get("grabbed", [])}
        is_movie = getattr(show, "content_type", "series") == "movie"
        is_all_future = all(
            ep.status == EpisodeStatus.UNAIRED or (ep.air_date and ((ep.air_date.date() if isinstance(ep.air_date, dt.datetime) else ep.air_date) > today))
            for ep in episodes
        )
        if is_movie:
            if grabbed_ids:
                message = "Захвачен фильм"
            elif is_all_future:
                message = "Фильм ещё не вышел"
            else:
                message = "Подходящих релизов для фильма не найдено"
        else:
            if grabbed_ids:
                if len(grabbed_ids) == 1 and len(payload.episode_ids) == 1:
                    message = "Захвачена 1 серия"
                else:
                    message = f"Захвачено серий: {len(grabbed_ids)} из {len(payload.episode_ids)}"
            elif is_all_future:
                message = "Выбранная серия ещё не вышла (ожидает премьеры)" if len(payload.episode_ids) == 1 else "Выбранные серии ещё не вышли (ожидают премьеры)"
            else:
                message = "Подходящих релизов для выбранных серий не найдено"

        return {
            "show_id": show_id,
            "grabbed": result.get("grabbed", []),
            "requested": len(payload.episode_ids),
            "success": bool(grabbed_ids),
            "message": message,
        }
    except Exception as exc:
        try:
            db.rollback()
        except Exception:
            pass
        logger.exception("Ошибка поиска серий шоу %s: %s", show_id, exc)
        return {
            "show_id": show_id,
            "grabbed": [],
            "requested": len(payload.episode_ids),
            "success": False,
            "message": f"Ошибка поиска: {exc}",
        }


@router.post("/{show_id}/search-season/{season_number}")
async def search_season_episodes(
    show_id: int,
    season_number: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manual_search")),
):
    """
    Автоматический поиск и скачивание ВСЕХ серий указанного сезона (Sonarr Season Search).
    Если находится полный пак или сезон-пак, загрузчик скачивает только серии этого сезона.
    """
    from app.services.auto_search import search_and_grab_show, clear_rejected_cache_for_show

    show = db.get(Show, show_id)
    if not show:
        raise HTTPException(404, "Show not found")

    clear_rejected_cache_for_show(show_id, db)

    season_episodes = (
        db.query(Episode)
        .filter(Episode.show_id == show_id, Episode.season_number == season_number)
        .all()
    )
    if not season_episodes:
        raise HTTPException(404, f"Серии сезона {season_number} не найдены")

    # Выбираем для поиска неотслеживаемые / разыскиваемые серии сезона, которые ещё не скачаны
    target_episodes = [
        ep for ep in season_episodes
        if (ep.monitored or ep.status == EpisodeStatus.WANTED) and ep.status != EpisodeStatus.DOWNLOADED
    ]
    if not target_episodes:
        target_episodes = [ep for ep in season_episodes if ep.status != EpisodeStatus.DOWNLOADED]

    if not target_episodes:
        return {
            "show_id": show_id,
            "season_number": season_number,
            "success": True,
            "message": f"Все серии сезона {season_number} уже скачаны",
            "grabbed": [],
        }

    try:
        target_ids = {ep.id for ep in target_episodes}
        result = await search_and_grab_show(db, show, episode_ids=target_ids)
        try:
            db.refresh(show)
        except Exception:
            pass
        today = dt.date.today()
        is_season_all_future = all(
            ep.status == EpisodeStatus.UNAIRED or (ep.air_date and ((ep.air_date.date() if isinstance(ep.air_date, dt.datetime) else ep.air_date) > today))
            for ep in target_episodes
        )
        if grabbed_ids:
            season_msg = f"Сезон {season_number}: захвачено серий {len(grabbed_ids)} из {len(season_episodes)}"
        elif is_season_all_future:
            downloaded_in_season = [ep for ep in season_episodes if ep.status == EpisodeStatus.DOWNLOADED or bool(getattr(ep, "file_path", None))]
            if downloaded_in_season:
                season_msg = f"Сезон {season_number}: все вышедшие серии скачаны (оставшиеся ещё не вышли)"
            else:
                season_msg = f"Сезон {season_number}: серии ещё не вышли"
        else:
            season_msg = f"Сезон {season_number}: подходящих релизов не найдено"

        return {
            "show_id": show_id,
            "season_number": season_number,
            "grabbed": result.get("grabbed", []),
            "requested": len(season_episodes),
            "success": bool(grabbed_ids),
            "message": season_msg,
        }
    except Exception as exc:
        try:
            db.rollback()
        except Exception:
            pass
        logger.exception("Ошибка поиска сезона шоу %s: %s", show_id, exc)
        return {
            "show_id": show_id,
            "season_number": season_number,
            "grabbed": [],
            "requested": len(season_episodes),
            "success": False,
            "message": f"Ошибка поиска сезона: {exc}",
        }
    
@router.post("/{show_id}/sync_disk")
def sync_show_disk(
    show_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_library")),
):
    """
    Импорт библиотеки / Синхронизация с диском (Sonarr Rescan & Update Library):
    Сканирует директорию видео, распознаёт файлы, считывает MediaInfo и обновляет статусы серий.
    """
    show = db.get(Show, show_id)
    if not show:
        raise HTTPException(404, "Show not found")

    settings = get_or_create_settings(db)
    if not show.path:
        show.path = get_show_default_path(show, settings)
        if show.path:
            db.add(show)
            db.commit()

    if not show.path:
        raise HTTPException(400, "У данного видео не задана директория (настройте папки библиотек в Настройки -> Папки)")

    if not os.path.exists(show.path):
        raise HTTPException(400, f"Директория «{show.path}» не существует на диске")

    video_files = find_video_files(show.path)
    imported_count = 0
    episodes = db.query(Episode).filter_by(show_id=show.id).all()
    today = dt.date.today()
    matched_episodes_set = set()

    if not video_files:
        for ep in episodes:
            is_active_download = ep.status == EpisodeStatus.DOWNLOADING and bool(getattr(ep, "torrent_hash", None))
            if is_active_download:
                continue
            air_d = getattr(ep, "air_date", None)
            if isinstance(air_d, dt.datetime):
                air_d = air_d.date()
            is_ep_ignored = (
                getattr(ep, "status", None) == EpisodeStatus.IGNORED
                or getattr(ep, "monitor_status", None) == MonitorStatus.IGNORED
                or not getattr(show, "monitored", True)
            )
            target_default_status = (
                EpisodeStatus.IGNORED
                if is_ep_ignored
                else (EpisodeStatus.UNAIRED if air_d and air_d > today else EpisodeStatus.WANTED)
            )
            ep.file_path = None
            ep.downloaded_quality = None
            ep.file_size_bytes = None
            ep.video_codec = None
            ep.audio_codec = None
            ep.audio_channels = None
            ep.dynamic_range = None
            ep.release_group = None
            ep.download_progress = 0.0
            if ep.status == EpisodeStatus.DOWNLOADED:
                ep.status = target_default_status
            db.add(ep)
        try:
            db.commit()
        except Exception:
            db.rollback()
        return {"imported_count": 0, "path": show.path, "message": f"Видеофайлы не найдены в {show.path}. Статусы сброшены."}

    show_hints = [show.title, os.path.basename(show.path or "")]
    try:
        from app.models.db import DownloadHistory, TrackedRelease
        hist = db.query(DownloadHistory).filter_by(show_id=show.id).order_by(DownloadHistory.id.desc()).first()
        if hist and hist.release_title:
            show_hints.append(hist.release_title)
        tr = db.query(TrackedRelease).filter_by(show_id=show.id).order_by(TrackedRelease.id.desc()).first()
        if tr and tr.topic_guid:
            show_hints.append(tr.topic_guid)
    except Exception:
        pass

    if show.content_type == "movie":
        non_samples = [f for f in video_files if not _SAMPLE_RE.search(os.path.basename(f))]
        target_files = non_samples if non_samples else video_files
        if target_files:
            main_file = max(target_files, key=lambda f: os.path.getsize(f) if os.path.exists(f) else 0)
            q_info = detect_file_quality(main_file, show_hints)
            episode = next((e for e in episodes if e.season_number == 1 and e.episode_number == 1), None)
            if not episode and episodes:
                episode = episodes[0]
            if not episode:
                episode = Episode(show_id=show.id, season_number=1, episode_number=1, title=show.title)
            is_active_download = (
                episode.status == EpisodeStatus.DOWNLOADING
                or bool(getattr(episode, "torrent_hash", None))
            )
            if not is_active_download:
                episode.status = EpisodeStatus.DOWNLOADED
                episode.monitored = False
                episode.download_progress = 1.0
            episode.file_path = main_file
            episode.downloaded_quality = q_info.name
            episode.video_codec = q_info.video_codec
            episode.audio_codec = q_info.audio_codec
            episode.audio_channels = q_info.audio_channels
            episode.dynamic_range = q_info.dynamic_range
            episode.file_size_bytes = os.path.getsize(main_file) if os.path.exists(main_file) else None
            db.add(episode)
            matched_episodes_set.add(episode.id)
            imported_count += 1
    else:
        for file_path in video_files:
            filename = os.path.basename(file_path)
            parsed = parse_episode(filename)
            q_info = detect_file_quality(file_path, show_hints)

            matched_ep = None
            if show.content_type == "anime" and parsed.kind == ReleaseKind.ABSOLUTE and parsed.episodes:
                abs_num = parsed.episodes[0]
                matched_ep = next((e for e in episodes if e.absolute_number == abs_num), None)
                if not matched_ep:
                    matched_ep = next((e for e in episodes if e.season_number == 1 and e.episode_number == abs_num), None)
            elif parsed.season is not None and parsed.episodes:
                matched_ep = next((e for e in episodes if e.season_number == parsed.season and e.episode_number in parsed.episodes), None)
            elif parsed.episodes:
                matched_ep = next((e for e in episodes if e.absolute_number == parsed.episodes[0]), None)
                if not matched_ep:
                    matched_ep = next((e for e in episodes if e.episode_number == parsed.episodes[0]), None)

            if not matched_ep:
                specials = [e for e in episodes if e.season_number == 0]
                if specials:
                    from app.services.matcher import match_special_episode
                    matched_ep = match_special_episode(file_path, specials, parsed)

            if matched_ep:
                is_active_download = (
                    matched_ep.status == EpisodeStatus.DOWNLOADING
                    or bool(getattr(matched_ep, "torrent_hash", None))
                )
                if not is_active_download:
                    matched_ep.status = EpisodeStatus.DOWNLOADED
                    matched_ep.monitored = False
                    matched_ep.download_progress = 1.0
                matched_ep.file_path = file_path
                matched_ep.downloaded_quality = q_info.name
                matched_ep.video_codec = q_info.video_codec
                matched_ep.audio_codec = q_info.audio_codec
                matched_ep.audio_channels = q_info.audio_channels
                matched_ep.dynamic_range = q_info.dynamic_range
                matched_ep.file_size_bytes = os.path.getsize(file_path) if os.path.exists(file_path) else None
                db.add(matched_ep)
                matched_episodes_set.add(matched_ep.id)
                imported_count += 1

    # Для всех серий, которые НЕ были найдены на диске — сбрасываем путь, качество, MediaInfo и статус
    for ep in episodes:
        if ep.id not in matched_episodes_set:
            has_real_file = False
            if getattr(ep, "file_path", None):
                try:
                    has_real_file = os.path.exists(ep.file_path)
                except Exception:
                    has_real_file = False

            if getattr(ep, "file_path", None) and not has_real_file:
                air_d = getattr(ep, "air_date", None)
                if isinstance(air_d, dt.datetime):
                    air_d = air_d.date()
                is_ep_ignored = (
                    getattr(ep, "status", None) == EpisodeStatus.IGNORED
                    or getattr(ep, "monitor_status", None) == MonitorStatus.IGNORED
                    or not getattr(show, "monitored", True)
                )
                target_default_status = (
                    EpisodeStatus.IGNORED
                    if is_ep_ignored
                    else (EpisodeStatus.UNAIRED if air_d and air_d > today else EpisodeStatus.WANTED)
                )
                ep.file_path = None
                ep.downloaded_quality = None
                ep.file_size_bytes = None
                ep.video_codec = None
                ep.audio_codec = None
                ep.audio_channels = None
                ep.dynamic_range = None
                ep.release_group = None
                if ep.status != EpisodeStatus.DOWNLOADING:
                    ep.download_progress = 0.0
                if ep.status == EpisodeStatus.DOWNLOADED:
                    ep.status = target_default_status
                db.add(ep)
            elif not getattr(ep, "file_path", None):
                if getattr(ep, "downloaded_quality", None) is not None or getattr(ep, "video_codec", None) is not None:
                    ep.downloaded_quality = None
                    ep.file_size_bytes = None
                    ep.video_codec = None
                    ep.audio_codec = None
                    ep.audio_channels = None
                    ep.dynamic_range = None
                    ep.release_group = None
                    db.add(ep)

    try:
        db.commit()
    except Exception:
        db.rollback()

    # После синхронизации проверяем все папки fonts в директории шоу и добавляем .ignore
    # (нужно для тайтлов, импортированных вручную до появления этого функционала)
    try:
        from app.services.postprocess import ensure_fonts_ignore
        for dirpath, dirnames, _ in os.walk(show.path):
            for dirname in dirnames:
                if dirname.lower() == "fonts":
                    ensure_fonts_ignore(os.path.join(dirpath, dirname))
    except Exception:
        pass

    return {"imported_count": imported_count, "path": show.path, "message": f"Синхронизировано серий: {imported_count}"}


# ---------------------------------------------------------------------------
# Ручной и интерактивный импорт медиафайлов
# ---------------------------------------------------------------------------

class ManualImportScanIn(BaseModel):
    folder_path: Optional[str] = None


class ManualImportFileCandidate(BaseModel):
    file_path: str
    relative_path: str
    filename: str
    size_bytes: int
    detected_quality: str
    parsed_season: Optional[int] = None
    parsed_episode: Optional[int] = None
    parsed_absolute: Optional[int] = None
    matched_episode_id: Optional[int] = None
    existing_file: Optional[str] = None


class ManualImportScanOut(BaseModel):
    show_id: int
    show_title: Optional[str] = None
    show_year: Optional[int] = None
    content_type: str = "series"
    folder_path: str
    files: list[ManualImportFileCandidate]
    episodes: list[EpisodeOut]


class ManualImportItemIn(BaseModel):
    file_path: str
    episode_id: int
    quality: Optional[str] = None


class ManualImportExecuteIn(BaseModel):
    import_mode: str = "move"  # "move" | "hardlink" | "copy"
    items: list[ManualImportItemIn]


class GlobalManualImportFileCandidate(BaseModel):
    file_path: str
    relative_path: str
    filename: str
    size_bytes: int
    detected_quality: str
    matched_show_id: Optional[int] = None
    matched_show_title: Optional[str] = None
    parsed_season: Optional[int] = None
    parsed_episode: Optional[int] = None
    parsed_absolute: Optional[int] = None
    matched_episode_id: Optional[int] = None
    existing_file: Optional[str] = None


class GlobalManualImportScanOut(BaseModel):
    folder_path: str
    files: list[GlobalManualImportFileCandidate]
    shows: list[dict]
    episodes_by_show: dict[int, list[EpisodeOut]]


class GlobalManualImportItemIn(BaseModel):
    file_path: str
    show_id: int
    episode_id: int
    quality: Optional[str] = None


class GlobalManualImportExecuteIn(BaseModel):
    import_mode: str = "move"  # "move" | "hardlink" | "copy"
    items: list[GlobalManualImportItemIn]


@router.get("/{show_id}/specials-import-status", response_model=SpecialsImportStatusOut)
async def get_specials_import_status(
    show_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("view_library")),
):
    """
    Проверяет, есть ли завершенные или ожидающие ручного импорта спецвыпуски для данного шоу.
    Готовыми к импорту считаются спецвыпуски, если:
    1. Они ещё не импортированы в библиотеку (status != DOWNLOADED и нет file_path).
    2. Раздача реально существует в торрент-клиенте и завершена на 100%.
    """
    show = db.get(Show, show_id)
    if not show:
        raise HTTPException(404, "Show not found")

    # Ищем спецвыпуски, которые ещё НЕ скачаны/импортированы
    specials = (
        db.query(Episode)
        .filter(Episode.show_id == show.id, Episode.season_number == 0)
        .all()
    )

    pending_specials = [
        ep for ep in specials
        if ep.status != EpisodeStatus.DOWNLOADED
        and not getattr(ep, "file_path", None)
        and (
            ep.status == EpisodeStatus.DOWNLOADING
            or (ep.torrent_hash and (ep.download_progress or 0) >= 0.99)
        )
    ]

    if not pending_specials:
        return SpecialsImportStatusOut(has_pending_specials=False, pending_folder=None, pending_count=0)

    # Собираем все уникальные torrent_hash для неимпортированных спецвыпусков
    target_hashes = []
    for ep in pending_specials:
        if ep.torrent_hash and ep.torrent_hash not in target_hashes:
            target_hashes.append(ep.torrent_hash)

    if not target_hashes:
        return SpecialsImportStatusOut(has_pending_specials=False, pending_folder=None, pending_count=0)

    settings = get_or_create_settings(db)
    clients = db.query(DownloadClient).filter_by(enabled=True).all()
    completed_folder = None
    confirmed_hash = None

    for thash in target_hashes:
        for dc in clients:
            try:
                from app.services.download_client import get_client
                cl = get_client(dc)
                t = await cl.get_torrent(thash)
                if t:
                    # Раздача должна реально существовать в клиенте и быть завершена на 100%
                    is_completed = (
                        (t.progress or 0.0) >= 0.999
                        or str(getattr(t, "state", "")).lower() in ("seeding", "completed", "complete", "uploading")
                    )
                    if is_completed:
                        from app.services.downloads_monitor import _resolve_torrent_files_and_path
                        p, _ = _resolve_torrent_files_and_path(t, settings, show)
                        completed_folder = p or show.path
                        confirmed_hash = thash
                        break
            except Exception:
                pass
        if completed_folder:
            break

    if completed_folder and confirmed_hash:
        return SpecialsImportStatusOut(
            has_pending_specials=True,
            pending_folder=completed_folder,
            pending_count=len(pending_specials),
            torrent_hash=confirmed_hash,
        )

    return SpecialsImportStatusOut(has_pending_specials=False, pending_folder=None, pending_count=0)


@router.post("/{show_id}/manual-import/scan", response_model=ManualImportScanOut)
def scan_for_manual_import(
    show_id: int,
    payload: Optional[ManualImportScanIn] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_library")),
):
    """
    Сканирует выбранную директорию (или текущую папку тайтла/загрузок),
    распознаёт сезоны/серии/качество и автоматически сопоставляет видеофайлы с эпизодами в базе.
    """
    show = db.get(Show, show_id)
    if not show:
        raise HTTPException(404, "Show not found")

    episodes = (
        db.query(Episode)
        .filter(Episode.show_id == show.id)
        .order_by(Episode.season_number, Episode.episode_number)
        .all()
    )

    settings = get_or_create_settings(db)
    folder_path = (payload.folder_path if payload and payload.folder_path else "").strip()
    if not folder_path:
        folder_path = show.path
        if not folder_path:
            folder_path = get_show_default_path(show, settings)

    if not folder_path:
        folder_path = ""

    episodes_out = [EpisodeOut.model_validate(e) for e in episodes]

    if not folder_path or not os.path.exists(folder_path):
        return ManualImportScanOut(
            show_id=show.id,
            show_title=show.title,
            show_year=show.year,
            content_type=show.content_type,
            folder_path=folder_path,
            files=[],
            episodes=episodes_out,
        )

    base_dir = os.path.dirname(folder_path) if os.path.isfile(folder_path) else folder_path

    try:
        release_files = find_release_files(folder_path)
    except Exception as exc:
        logger.warning("find_release_files failed for %s: %s", folder_path, exc)
        release_files = {"video": [], "extras": [], "other": []}

    seen_paths = set()
    video_files = []
    # Собираем абсолютно ВСЕ видеофайлы (основные + extras/бонусы/спешлы),
    # чтобы ни один скачанный эпизод не был утерян
    for f in release_files.get("video", []) + release_files.get("extras", []):
        if f not in seen_paths:
            seen_paths.add(f)
            video_files.append(f)

    # Дополнительно проверяем файлы из 'other' на наличие видео-расширения
    for f in release_files.get("other", []):
        ext = os.path.splitext(f)[1].lower()
        if ext in VIDEO_EXTENSIONS and f not in seen_paths:
            seen_paths.add(f)
            video_files.append(f)

    # Сортируем файлы в естественном числовом порядке
    video_files.sort(key=lambda p: natural_sort_key(os.path.relpath(p, base_dir) if os.path.exists(p) else p))

    file_candidates: list[ManualImportFileCandidate] = []
    used_scan_ep_ids: set[int] = set()

    for file_path in video_files:
        filename = os.path.basename(file_path)
        try:
            rel_path = os.path.relpath(file_path, base_dir) if os.path.exists(file_path) else filename
            if rel_path == ".":
                rel_path = filename
        except Exception:
            rel_path = filename

        size_bytes = os.path.getsize(file_path) if os.path.exists(file_path) else 0
        try:
            quality = detect_file_quality(file_path, [show.title, os.path.basename(base_dir)]).name
        except Exception:
            quality = parse_quality(filename).name

        try:
            parsed = parse_episode(filename)
        except Exception:
            parsed = ParsedRelease(title=filename, kind=ReleaseKind.UNKNOWN)

        # 1. Если по имени файла не распознан сезон/серия, пробуем имя родительской папки
        parent_dir = os.path.basename(os.path.dirname(file_path))
        if (parsed.kind == ReleaseKind.UNKNOWN or not parsed.episodes or parsed.season is None) and parent_dir and parent_dir != os.path.basename(base_dir):
            try:
                parent_parsed = parse_episode(parent_dir + " " + filename)
                if parent_parsed.episodes or parent_parsed.season is not None:
                    if not parsed.episodes:
                        parsed.episodes = parent_parsed.episodes
                    if parsed.season is None:
                        parsed.season = parent_parsed.season
                    if parsed.kind == ReleaseKind.UNKNOWN:
                        parsed.kind = parent_parsed.kind
            except Exception:
                pass

        # 2. Если сезон всё ещё None, ищем номер сезона в иерархии папок (напр. "Season 2", "S02", "Спецвыпуски", "Specials")
        if parsed.season is None:
            try:
                path_parts = [p for p in re.split(r"[\\/]", os.path.dirname(rel_path)) if p and p != "."]
                for part in reversed(path_parts):
                    part_lower = part.lower()
                    if any(kw in part_lower for kw in ("special", "спец", "ova", "ona", "extra", "бонус")):
                        parsed.season = 0
                        break
                    p_parsed = parse_episode(part)
                    if p_parsed.season is not None:
                        parsed.season = p_parsed.season
                        break
            except Exception:
                pass

        matched_ep = None
        p_season = parsed.season
        p_episode = parsed.episodes[0] if parsed.episodes else None
        p_abs = parsed.episodes[0] if (parsed.kind == ReleaseKind.ABSOLUTE and parsed.episodes) else None

        if show.content_type == "movie":
            matched_ep = next((e for e in episodes if e.season_number == 1 and e.episode_number == 1), None)
            if not matched_ep and episodes:
                matched_ep = episodes[0]
        else:
            # 0. Приоритетное сопоставление по названию серии (актуально при несовпадении нумерации в релизах)
            from app.services.matcher import normalize_title_words, calc_title_match, get_show_title_words
            fname_no_ext = os.path.splitext(filename)[0]
            fname_words = set(normalize_title_words(fname_no_ext))
            show_words = get_show_title_words(show)
            if len(fname_words) >= 1:
                candidate_pool = [e for e in episodes if e.id not in used_scan_ep_ids]
                target_s = parsed.season
                if target_s is not None:
                    candidate_pool.sort(key=lambda e: (0 if e.season_number == target_s else 1, e.episode_number))
                best_match_key = (0.0, 0)
                best_scan_ep = None
                for ep in candidate_pool:
                    if ep.title and len(ep.title.strip()) >= 3:
                        score, matched_count = calc_title_match(ep.title, fname_words, show_words=show_words)
                        match_key = (score, matched_count)
                        if score >= 0.7 and match_key > best_match_key:
                            best_match_key = match_key
                            best_scan_ep = ep
                if best_scan_ep is not None:
                    matched_ep = best_scan_ep

            # 1. Явный сезон и номер серии
            if not matched_ep and parsed.season is not None and parsed.episodes:
                matched_ep = next((e for e in episodes if e.id not in used_scan_ep_ids and e.season_number == parsed.season and e.episode_number in parsed.episodes), None)

            # 2. Аниме absolute / lone number
            if not matched_ep and parsed.kind == ReleaseKind.ABSOLUTE and parsed.episodes:
                abs_num = parsed.episodes[0]
                matched_ep = next((e for e in episodes if e.absolute_number == abs_num), None)
                if not matched_ep:
                    target_s = parsed.season if parsed.season is not None else 1
                    matched_ep = next((e for e in episodes if e.season_number == target_s and e.episode_number == abs_num), None)

            # 3. Номер серии без явного сезона (или с предполагаемым сезоном)
            if not matched_ep and parsed.episodes:
                target_s = parsed.season if parsed.season is not None else 1
                matched_ep = next((e for e in episodes if e.season_number == target_s and e.episode_number == parsed.episodes[0]), None)
                if not matched_ep:
                    matched_ep = next((e for e in episodes if e.absolute_number == parsed.episodes[0]), None)

            if not matched_ep:
                specials = [e for e in episodes if e.season_number == 0]
                if specials:
                    try:
                        from app.services.matcher import match_special_episode
                        matched_ep = match_special_episode(file_path, specials, parsed)
                        if matched_ep:
                            p_season = matched_ep.season_number
                            p_episode = matched_ep.episode_number
                    except Exception:
                        matched_ep = None

        if matched_ep and getattr(matched_ep, "id", None) is not None:
            used_scan_ep_ids.add(matched_ep.id)

        file_candidates.append(
            ManualImportFileCandidate(
                file_path=file_path,
                relative_path=rel_path,
                filename=filename,
                size_bytes=size_bytes,
                detected_quality=quality,
                parsed_season=p_season,
                parsed_episode=p_episode,
                parsed_absolute=p_abs,
                matched_episode_id=matched_ep.id if matched_ep else None,
                existing_file=matched_ep.file_path if (matched_ep and matched_ep.file_path and os.path.exists(matched_ep.file_path)) else None,
            )
        )

    return ManualImportScanOut(
        show_id=show.id,
        show_title=show.title,
        show_year=show.year,
        content_type=show.content_type,
        folder_path=folder_path,
        files=file_candidates,
        episodes=episodes_out,
    )


@router.post("/{show_id}/manual-import/execute")
def execute_manual_import(
    show_id: int,
    payload: ManualImportExecuteIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_library")),
):
    """
    Выполняет импорт (перемещение или копирование) выбранных видеофайлов с их привязкой
    к указанным эпизодам карточки, переименованием по шаблону, переносом дорожек/субтитров/шрифтов
    и выставлением правильных прав доступа.
    """
    from app.services.task_manager import task_manager

    show = db.get(Show, show_id)
    if not show:
        raise HTTPException(404, "Show not found")

    settings = get_or_create_settings(db)
    show_root = show.path or get_show_default_path(show, settings)
    if not show_root:
        raise HTTPException(400, "Укажите корневую папку шоу в настройках")

    os.makedirs(show_root, exist_ok=True)
    apply_media_permissions(show_root, is_dir=True)

    season_template = (
        (getattr(settings, "season_folder_template_anime", None) if show.content_type == "anime" else getattr(settings, "season_folder_template_series", None))
        or getattr(settings, "media_naming_season_folder", None)
        or "Season {season:02d}"
    )
    if show.content_type == "movie":
        rename_template = getattr(settings, "rename_template_movie", None) or getattr(settings, "media_naming_movie", None) or "{Movie Title} ({Release Year}) {Quality Full}"
    elif show.content_type == "anime":
        rename_template = getattr(settings, "rename_template_anime", None) or getattr(settings, "media_naming_episode", None) or "{Series Title} - S{season:02d}E{episode:02d} - {Episode Title}"
    else:
        rename_template = getattr(settings, "rename_template_series", None) or getattr(settings, "media_naming_episode", None) or "{Series Title} - S{season:02d}E{episode:02d} - {Episode Title}"

    imported_count = 0
    errors: list[str] = []
    total_items = len(payload.items)

    def _manual_item_sort_key(it):
        ep_obj = db.get(Episode, it.episode_id) if getattr(it, "episode_id", None) else None
        s_num = ep_obj.season_number if ep_obj else (getattr(it, "season_number", 999) or 999)
        e_num = ep_obj.episode_number if ep_obj else (getattr(it, "episode_number", 9999) or 9999)
        return (s_num, e_num, natural_sort_key(os.path.basename(it.file_path or "")))

    sorted_payload_items = sorted(payload.items, key=_manual_item_sort_key)
    valid_items = [it for it in sorted_payload_items if os.path.exists(it.file_path)]
    total_bytes = sum(os.path.getsize(it.file_path) for it in valid_items) or 1
    overall_bytes_copied = 0
    used_dest_paths: set[str] = set()
    just_written_files: set[str] = set()
    today = dt.date.today()

    with task_manager.track_sync(
        name="manual_import",
        title=f"Ручной импорт: {show.title}",
        message=f"Подготовка к импорту {total_items} файлов...",
        progress=0.0,
        show_id=show.id,
        total_items=total_items,
        current_item=0,
    ) as m_task:
        for idx, item in enumerate(sorted_payload_items, 1):
            file_name = os.path.basename(item.file_path)
            if not os.path.exists(item.file_path):
                errors.append(f"Файл не найден: {item.file_path}")
                continue

            file_size = os.path.getsize(item.file_path)

            episode = db.get(Episode, item.episode_id)
            if not episode or episode.show_id != show.id:
                errors.append(f"Серия ID={item.episode_id} не найдена для данного шоу")
                continue

            # Папка сезона
            season_folder = ""
            if show.content_type != "movie" and season_template and season_template.strip():
                season_folder = render_season_folder_template(
                    season_template,
                    season=episode.season_number,
                    show_title=show.title,
                    year=show.year,
                )

            target_dir = os.path.join(show_root, season_folder) if season_folder else show_root
            os.makedirs(target_dir, exist_ok=True)
            apply_media_permissions(target_dir, is_dir=True)

            quality = item.quality or parse_quality(os.path.basename(item.file_path)).name

            ext = os.path.splitext(item.file_path)[1]
            if show.content_type == "movie":
                target_stem = render_movie_template(
                    rename_template,
                    show_title=show.title,
                    year=show.year,
                    quality=quality,
                )
            else:
                target_stem = render_episode_template(
                    rename_template,
                    show_title=getattr(show, "title", "") or "",
                    season=getattr(episode, "season_number", 1),
                    episode=getattr(episode, "episode_number", 1),
                    episode_title=getattr(episode, "title", "") or "",
                    absolute=getattr(episode, "absolute_number", None) or getattr(episode, "episode_number", 1),
                    quality=quality,
                    year=getattr(show, "year", None),
                )
            dest_video_path = os.path.join(target_dir, target_stem + ext)
            dest_abs = os.path.abspath(dest_video_path)

            if dest_abs in used_dest_paths:
                target_stem_unique = f"{target_stem}_part{idx}"
                dest_video_path = os.path.join(target_dir, target_stem_unique + ext)
                dest_abs = os.path.abspath(dest_video_path)
                errors.append(f"Внимание: файл {file_name} сопоставлен с дублирующейся серией и сохранен как {target_stem_unique}{ext}")

            def _progress_cb(copied_in_file, total_in_file):
                current_total = overall_bytes_copied + copied_in_file
                ratio = min(0.99, current_total / max(1, total_bytes))
                mb_copied = current_total / (1024 * 1024)
                mb_total = total_bytes / (1024 * 1024)
                m_task.update(
                    message=f"Перенос ({idx}/{total_items}): {file_name} ({mb_copied:.1f}/{mb_total:.1f} МБ)",
                    progress=round(ratio, 3),
                    current_item=idx,
                    total_items=total_items,
                    show_id=show.id,
                )

            _progress_cb(0, file_size)

            try:
                # Если перезаписываем старый файл с другим именем
                if episode.file_path and os.path.exists(episode.file_path) and os.path.abspath(episode.file_path) not in just_written_files and os.path.abspath(episode.file_path) != dest_abs:
                    try:
                        os.remove(episode.file_path)
                    except Exception:
                        pass

                if payload.import_mode == "move":
                    if os.path.abspath(item.file_path) != dest_abs:
                        move_file_with_progress(item.file_path, dest_video_path, callback=_progress_cb)
                elif payload.import_mode == "hardlink":
                    if os.path.abspath(item.file_path) != dest_abs:
                        try:
                            if os.path.exists(dest_video_path):
                                try:
                                    os.remove(dest_video_path)
                                except OSError:
                                    pass
                            os.link(item.file_path, dest_video_path)
                            logger.info("Ручной импорт: хардлинк успешно создан %s -> %s", item.file_path, dest_video_path)
                            _progress_cb(0, file_size)
                            _progress_cb(file_size, file_size)
                        except OSError as link_err:
                            logger.warning(
                                "Ручной импорт: не удалось создать хардлинк (%s), переключаемся на копирование: %s -> %s",
                                link_err, item.file_path, dest_video_path,
                            )
                            copy_file_with_progress(item.file_path, dest_video_path, callback=_progress_cb)
                else:
                    if os.path.abspath(item.file_path) != dest_abs:
                        copy_file_with_progress(item.file_path, dest_video_path, callback=_progress_cb)

                used_dest_paths.add(dest_abs)
                just_written_files.add(dest_abs)

                overall_bytes_copied += file_size
                _progress_cb(file_size, file_size)
                apply_media_permissions(dest_video_path, is_dir=False)

                # Перенос/копирование дорожек, субтитров и шрифтов из папки источника
                src_dir = os.path.dirname(item.file_path)
                if os.path.isdir(src_dir):
                    source_release = find_release_files(src_dir)
                    companion_subs = match_companion_files_for_episode(
                        source_release.get("subtitle", []),
                        episode.episode_number,
                        episode.season_number,
                        item.file_path,
                        len(source_release.get("video", [])),
                    )
                    for sf in companion_subs:
                        sub_ext = os.path.splitext(sf)[1]
                        sub_tag = extract_companion_tag(sf, item.file_path, episode.episode_number, release_root=src_dir)
                        dest_sub_name = f"{target_stem}.{sub_tag}{sub_ext}" if sub_tag else f"{target_stem}{sub_ext}"
                        dest_sub_path = os.path.join(target_dir, dest_sub_name)
                        try:
                            if payload.import_mode == "move":
                                shutil.move(sf, dest_sub_path)
                            elif payload.import_mode == "hardlink":
                                try:
                                    if os.path.exists(dest_sub_path):
                                        os.remove(dest_sub_path)
                                    os.link(sf, dest_sub_path)
                                except OSError:
                                    shutil.copy2(sf, dest_sub_path)
                            else:
                                shutil.copy2(sf, dest_sub_path)
                            apply_media_permissions(dest_sub_path, is_dir=False)
                        except Exception:
                            pass

                    companion_audios = match_companion_files_for_episode(
                        source_release.get("audio", []),
                        episode.episode_number,
                        episode.season_number,
                        item.file_path,
                        len(source_release.get("video", [])),
                    )
                    for af in companion_audios:
                        aud_ext = os.path.splitext(af)[1]
                        aud_tag = extract_companion_tag(af, item.file_path, episode.episode_number, release_root=src_dir)
                        dest_aud_name = f"{target_stem}.{aud_tag}{aud_ext}" if aud_tag else f"{target_stem}{aud_ext}"
                        dest_aud_path = os.path.join(target_dir, dest_aud_name)
                        try:
                            if payload.import_mode == "move":
                                shutil.move(af, dest_aud_path)
                            elif payload.import_mode == "hardlink":
                                try:
                                    if os.path.exists(dest_aud_path):
                                        os.remove(dest_aud_path)
                                    os.link(af, dest_aud_path)
                                except OSError:
                                    shutil.copy2(af, dest_aud_path)
                            else:
                                shutil.copy2(af, dest_aud_path)
                            apply_media_permissions(dest_aud_path, is_dir=False)
                        except Exception:
                            pass

                    if source_release.get("font"):
                        season_fonts_dir = os.path.join(target_dir, "fonts")
                        os.makedirs(season_fonts_dir, exist_ok=True)
                        apply_media_permissions(season_fonts_dir, is_dir=True)
                        for ff in source_release["font"]:
                            dest_ff = os.path.join(season_fonts_dir, os.path.basename(ff))
                            try:
                                shutil.copy2(ff, dest_ff)
                                apply_media_permissions(dest_ff, is_dir=False)
                            except Exception:
                                pass
                        # Скрываем папку fonts из библиотеки Jellyfin через .ignore
                        from app.services.postprocess import ensure_fonts_ignore
                        ensure_fonts_ignore(season_fonts_dir)

                # Проверяем наличие .ignore в уже существующих fonts-папках тайтла
                try:
                    from app.services.postprocess import ensure_fonts_ignore
                    for fonts_candidate in [
                        os.path.join(target_dir, "fonts"),
                        os.path.join(show_root, "fonts"),
                    ]:
                        ensure_fonts_ignore(fonts_candidate)
                except Exception:
                    pass

                q_info = parse_quality(os.path.basename(dest_video_path))
                episode.status = EpisodeStatus.DOWNLOADED
                episode.monitored = False
                episode.file_path = dest_video_path
                episode.download_progress = 1.0
                episode.downloaded_quality = quality
                episode.video_codec = q_info.video_codec
                episode.audio_codec = q_info.audio_codec
                episode.audio_channels = q_info.audio_channels
                episode.dynamic_range = q_info.dynamic_range
                episode.file_size_bytes = os.path.getsize(dest_video_path) if os.path.exists(dest_video_path) else None
                db.add(episode)
                try:
                    db.commit()
                except Exception:
                    pass
                imported_count += 1

                # Отправляем уведомление в мессенджеры для каждой импортированной серии
                try:
                    from app.services.notifications import notify_all_sync
                    if episode.season_number == 0:
                        ep_title = f" — «{episode.title}»" if episode.title else ""
                        sp_num_str = f"{episode.episode_number:02d}" if (episode.episode_number is not None and isinstance(episode.episode_number, int)) else str(episode.episode_number or "01")
                        notif_msg = (
                            f"📥 Импорт спецвыпуска для «{show.title}»:\n"
                            f"Серия: SP {sp_num_str}{ep_title}\n"
                            f"Файл: {file_name}\n"
                            f"Качество: {quality}"
                        )
                    elif show.content_type == "movie":
                        notif_msg = (
                            f"📥 Импорт фильма «{show.title}»:\n"
                            f"Файл: {file_name}\n"
                            f"Качество: {quality}"
                        )
                    else:
                        ep_title = f" — «{episode.title}»" if episode.title else ""
                        s_num_str = f"{episode.season_number:02d}" if (episode.season_number is not None and isinstance(episode.season_number, int)) else str(episode.season_number or "01")
                        e_num_str = f"{episode.episode_number:02d}" if (episode.episode_number is not None and isinstance(episode.episode_number, int)) else str(episode.episode_number or "01")
                        notif_msg = (
                            f"📥 Импорт серии для «{show.title}»:\n"
                            f"Серия: S{s_num_str}E{e_num_str}{ep_title}\n"
                            f"Файл: {file_name}\n"
                            f"Качество: {quality}"
                        )
                    notify_all_sync(db=None, event_type="import", message=notif_msg)
                except Exception:
                    pass
            except Exception as exc:
                errors.append(f"Ошибка при импорте {item.file_path}: {exc}")

        if imported_count > 0:
            apply_media_permissions(show_root, is_dir=True, recursive=True)

        db.commit()

        # Снимаем защиту ручного импорта для торрентов, у которых больше не осталось неимпортированных серий
        try:
            from app.services.downloads_monitor import unmark_torrent_pending_manual_import
            affected_hashes = set()
            for it in payload.items:
                ep_obj = db.get(Episode, it.episode_id) if getattr(it, "episode_id", None) else None
                if ep_obj and getattr(ep_obj, "torrent_hash", None):
                    affected_hashes.add(ep_obj.torrent_hash.lower())

            # Также проверяем историю загрузок шоу
            dh_list = db.query(DownloadHistory).filter(DownloadHistory.show_id == show.id).all()
            for dh in dh_list:
                if getattr(dh, "torrent_hash", None):
                    affected_hashes.add(dh.torrent_hash.lower())

            for th in affected_hashes:
                rem_downloading = (
                    db.query(Episode)
                    .filter(
                        func.lower(Episode.torrent_hash) == th,
                        Episode.status == EpisodeStatus.DOWNLOADING,
                    )
                    .count()
                )
                rem_specials = (
                    db.query(Episode)
                    .filter(
                        Episode.show_id == show.id,
                        Episode.season_number == 0,
                        Episode.status.in_([EpisodeStatus.DOWNLOADING, EpisodeStatus.WANTED]),
                        Episode.file_path.is_(None),
                    )
                    .count()
                )
                if rem_downloading == 0 and rem_specials == 0:
                    unmark_torrent_pending_manual_import(th)
        except Exception as unmark_err:
            logger.debug("Ошибка unmark_torrent_pending_manual_import: %s", unmark_err)

        log_audit(
            db,
            "manual_import",
            f"Импортировано файлов: {imported_count} для шоу {show.title}",
            username=current_user.username,
            user=current_user,
        )

        if errors:
            m_task.complete(f"Импортировано: {imported_count} из {total_items} (ошибок: {len(errors)})")
        else:
            m_task.complete(f"Успешно импортировано: {imported_count} файл(ов)")

    return {
        "success": True,
        "imported_count": imported_count,
        "errors": errors,
        "message": f"Успешно импортировано файлов: {imported_count}",
    }


@router.post("/manual-import/scan-all", response_model=GlobalManualImportScanOut)
def scan_for_global_manual_import(
    payload: Optional[ManualImportScanIn] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_library")),
):
    """
    Глобальный ручной импорт (Sonarr Wanted -> Manual Import):
    Сканирует выбранную директорию (или общую папку загрузок/библиотеки),
    автоматически распознаёт и сопоставляет файлы со всеми тайтлами в библиотеке.
    """
    settings = get_or_create_settings(db)
    folder_path = (payload.folder_path if payload and payload.folder_path else "").strip()
    if not folder_path:
        folder_path = getattr(settings, "root_folder_series", "") or getattr(settings, "root_folder_anime", "") or "/downloads"
        if not os.path.exists(folder_path):
            folder_path = os.getcwd()

    if not os.path.exists(folder_path):
        raise HTTPException(404, f"Папка «{folder_path}» не существует на диске")

    release_files = find_release_files(folder_path)
    seen_paths = set()
    video_files = []
    for f in release_files.get("video", []) + release_files.get("extras", []):
        if f not in seen_paths:
            seen_paths.add(f)
            video_files.append(f)

    for f in release_files.get("other", []):
        ext = os.path.splitext(f)[1].lower()
        if ext in VIDEO_EXTENSIONS and f not in seen_paths:
            seen_paths.add(f)
            video_files.append(f)

    video_files.sort(key=lambda p: natural_sort_key(os.path.relpath(p, folder_path) if os.path.exists(p) else p))

    all_shows = db.query(Show).order_by(Show.title).all()
    shows_out = [
        {"id": s.id, "title": s.title, "year": s.year, "content_type": s.content_type}
        for s in all_shows
    ]

    all_episodes = db.query(Episode).order_by(Episode.season_number, Episode.episode_number).all()
    episodes_by_show_db: dict[int, list[Episode]] = {}
    episodes_by_show_out: dict[int, list[EpisodeOut]] = {}
    for ep in all_episodes:
        episodes_by_show_db.setdefault(ep.show_id, []).append(ep)
        episodes_by_show_out.setdefault(ep.show_id, []).append(EpisodeOut.model_validate(ep))

    file_candidates: list[GlobalManualImportFileCandidate] = []

    shows_with_aliases = []
    for s in all_shows:
        aliases = build_alias_candidates(s, db=db)
        shows_with_aliases.append((s, aliases))

    for file_path in video_files:
        filename = os.path.basename(file_path)
        try:
            rel_path = os.path.relpath(file_path, folder_path)
        except Exception:
            rel_path = filename

        size_bytes = os.path.getsize(file_path) if os.path.exists(file_path) else 0
        parent_dir_name = os.path.basename(os.path.dirname(file_path))
        grandparent_dir_name = os.path.basename(os.path.dirname(os.path.dirname(file_path)))
        quality = detect_file_quality(file_path, [parent_dir_name, grandparent_dir_name, os.path.basename(folder_path)]).name
        parsed = parse_episode(filename)
        search_names = [filename, parent_dir_name, grandparent_dir_name, rel_path]

        # 1. Если по имени файла не распознан сезон/серия, пробуем имя родительской папки
        if (parsed.kind == ReleaseKind.UNKNOWN or not parsed.episodes or parsed.season is None) and parent_dir_name and parent_dir_name != os.path.basename(folder_path):
            parent_parsed = parse_episode(parent_dir_name + " " + filename)
            if parent_parsed.episodes or parent_parsed.season is not None:
                if not parsed.episodes:
                    parsed.episodes = parent_parsed.episodes
                if parsed.season is None:
                    parsed.season = parent_parsed.season
                if parsed.kind == ReleaseKind.UNKNOWN:
                    parsed.kind = parent_parsed.kind

        # 2. Если сезон всё ещё None, ищем номер сезона в иерархии папок
        if parsed.season is None:
            path_parts = [p for p in re.split(r"[\\/]", os.path.dirname(rel_path)) if p and p != "."]
            for part in reversed(path_parts):
                part_lower = part.lower()
                if any(kw in part_lower for kw in ("special", "спец", "ova", "ona", "extra", "бонус")):
                    parsed.season = 0
                    break
                p_parsed = parse_episode(part)
                if p_parsed.season is not None:
                    parsed.season = p_parsed.season
                    break

        matched_show = None
        matched_ep = None

        best_score = 0
        for s, aliases in shows_with_aliases:
            for s_name in search_names:
                if not s_name or s_name == ".":
                    continue
                match = match_release(s_name, s.id, aliases, content_type=s.content_type, show_year=getattr(s, "year", None))
                if match.matched and match.score > best_score:
                    best_score = match.score
                    matched_show = s

        if matched_show:
            show_eps = episodes_by_show_db.get(matched_show.id, [])
            p_season = parsed.season
            p_episode = parsed.episodes[0] if parsed.episodes else None
            p_abs = parsed.episodes[0] if (parsed.kind == ReleaseKind.ABSOLUTE and parsed.episodes) else None

            if matched_show.content_type == "movie":
                matched_ep = next((e for e in show_eps if e.season_number == 1 and e.episode_number == 1), None)
                if not matched_ep and show_eps:
                    matched_ep = show_eps[0]
            else:
                if parsed.season is not None and parsed.episodes:
                    matched_ep = next((e for e in show_eps if e.season_number == parsed.season and e.episode_number in parsed.episodes), None)

                if not matched_ep and parsed.kind == ReleaseKind.ABSOLUTE and parsed.episodes:
                    abs_num = parsed.episodes[0]
                    matched_ep = next((e for e in show_eps if e.absolute_number == abs_num), None)
                    if not matched_ep:
                        target_s = parsed.season if parsed.season is not None else 1
                        matched_ep = next((e for e in show_eps if e.season_number == target_s and e.episode_number == abs_num), None)

                if not matched_ep and parsed.episodes:
                    target_s = parsed.season if parsed.season is not None else 1
                    matched_ep = next((e for e in show_eps if e.season_number == target_s and e.episode_number == parsed.episodes[0]), None)
                    if not matched_ep:
                        matched_ep = next((e for e in show_eps if e.absolute_number == parsed.episodes[0]), None)

                if not matched_ep and show_eps:
                    specials = [e for e in show_eps if e.season_number == 0]
                    if specials:
                        from app.services.matcher import match_special_episode
                        matched_ep = match_special_episode(file_path, specials, parsed)
                        if matched_ep:
                            p_season = matched_ep.season_number
                            p_episode = matched_ep.episode_number
        else:
            p_season = parsed.season
            p_episode = parsed.episodes[0] if parsed.episodes else None
            p_abs = parsed.episodes[0] if (parsed.kind == ReleaseKind.ABSOLUTE and parsed.episodes) else None

        file_candidates.append(
            GlobalManualImportFileCandidate(
                file_path=file_path,
                relative_path=rel_path,
                filename=filename,
                size_bytes=size_bytes,
                detected_quality=quality,
                matched_show_id=matched_show.id if matched_show else None,
                matched_show_title=matched_show.title if matched_show else None,
                parsed_season=p_season,
                parsed_episode=p_episode,
                parsed_absolute=p_abs,
                matched_episode_id=matched_ep.id if matched_ep else None,
                existing_file=matched_ep.file_path if (matched_ep and matched_ep.file_path and os.path.exists(matched_ep.file_path)) else None,
            )
        )

    return GlobalManualImportScanOut(
        folder_path=folder_path,
        files=file_candidates,
        shows=shows_out,
        episodes_by_show=episodes_by_show_out,
    )


@router.post("/manual-import/execute-all")
def execute_global_manual_import(
    payload: GlobalManualImportExecuteIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_library")),
):
    """
    Выполняет импорт выбранных файлов в соответствующие тайтлы библиотеки.
    """
    from app.services.task_manager import task_manager

    settings = get_or_create_settings(db)
    imported_count = 0
    errors: list[str] = []
    total_items = len(payload.items)

    def _global_item_sort_key(it):
        ep_obj = db.get(Episode, it.episode_id) if getattr(it, "episode_id", None) else None
        s_num = ep_obj.season_number if ep_obj else (getattr(it, "season_number", 999) or 999)
        e_num = ep_obj.episode_number if ep_obj else (getattr(it, "episode_number", 9999) or 9999)
        return (it.show_id, s_num, e_num, natural_sort_key(os.path.basename(it.file_path or "")))

    sorted_payload_items = sorted(payload.items, key=_global_item_sort_key)
    valid_items = [it for it in sorted_payload_items if os.path.exists(it.file_path)]
    total_bytes = sum(os.path.getsize(it.file_path) for it in valid_items) or 1
    overall_bytes_copied = 0
    used_dest_paths: set[str] = set()
    just_written_files: set[str] = set()

    with task_manager.track_sync(
        name="global_manual_import",
        title="Глобальный ручной импорт",
        message=f"Подготовка к импорту {total_items} файлов...",
        progress=0.0,
        total_items=total_items,
        current_item=0,
    ) as m_task:
        for idx, item in enumerate(sorted_payload_items, 1):
            file_name = os.path.basename(item.file_path)
            if not os.path.exists(item.file_path):
                errors.append(f"Файл не найден: {item.file_path}")
                continue

            file_size = os.path.getsize(item.file_path)

            show = db.get(Show, item.show_id)
            if not show:
                errors.append(f"Шоу ID={item.show_id} не найдено")
                continue

            episode = db.get(Episode, item.episode_id)
            if not episode or episode.show_id != show.id:
                errors.append(f"Серия ID={item.episode_id} не найдена для шоу {show.title}")
                continue

            show_root = show.path or get_show_default_path(show, settings)
            if not show_root:
                errors.append(f"Не задана корневая папка для {show.title}")
                continue

            os.makedirs(show_root, exist_ok=True)
            apply_media_permissions(show_root, is_dir=True)

            season_template = (
                (getattr(settings, "season_folder_template_anime", None) if show.content_type == "anime" else getattr(settings, "season_folder_template_series", None))
                or getattr(settings, "media_naming_season_folder", None)
                or "Season {season:02d}"
            )
            if show.content_type == "movie":
                rename_template = getattr(settings, "rename_template_movie", None) or getattr(settings, "media_naming_movie", None) or "{Movie Title} ({Release Year}) {Quality Full}"
            elif show.content_type == "anime":
                rename_template = getattr(settings, "rename_template_anime", None) or getattr(settings, "media_naming_episode", None) or "{Series Title} - S{season:02d}E{episode:02d} - {Episode Title}"
            else:
                rename_template = getattr(settings, "rename_template_series", None) or getattr(settings, "media_naming_episode", None) or "{Series Title} - S{season:02d}E{episode:02d} - {Episode Title}"

            season_folder = ""
            if show.content_type != "movie" and season_template and season_template.strip():
                season_folder = render_season_folder_template(
                    season_template,
                    season=episode.season_number,
                    show_title=show.title,
                    year=show.year,
                )

            target_dir = os.path.join(show_root, season_folder) if season_folder else show_root
            os.makedirs(target_dir, exist_ok=True)
            apply_media_permissions(target_dir, is_dir=True)

            quality = item.quality or parse_quality(os.path.basename(item.file_path)).name
            ext = os.path.splitext(item.file_path)[1]
            if show.content_type == "movie":
                target_stem = render_movie_template(
                    rename_template,
                    show_title=show.title,
                    year=show.year,
                    quality=quality,
                )
            else:
                target_stem = render_episode_template(
                    rename_template,
                    show_title=getattr(show, "title", "") or "",
                    season=getattr(episode, "season_number", 1),
                    episode=getattr(episode, "episode_number", 1),
                    episode_title=getattr(episode, "title", "") or "",
                    absolute=getattr(episode, "absolute_number", None) or getattr(episode, "episode_number", 1),
                    quality=quality,
                    year=getattr(show, "year", None),
                )
            dest_video_path = os.path.join(target_dir, target_stem + ext)
            dest_abs = os.path.abspath(dest_video_path)

            if dest_abs in used_dest_paths:
                target_stem_unique = f"{target_stem}_part{idx}"
                dest_video_path = os.path.join(target_dir, target_stem_unique + ext)
                dest_abs = os.path.abspath(dest_video_path)
                errors.append(f"Внимание: файл {file_name} сопоставлен с дублирующейся серией и сохранен как {target_stem_unique}{ext}")

            def _progress_cb(copied_in_file, total_in_file):
                current_total = overall_bytes_copied + copied_in_file
                ratio = min(0.99, current_total / max(1, total_bytes))
                mb_copied = current_total / (1024 * 1024)
                mb_total = total_bytes / (1024 * 1024)
                m_task.update(
                    message=f"Перенос ({idx}/{total_items}): {file_name} ({mb_copied:.1f}/{mb_total:.1f} МБ)",
                    progress=round(ratio, 3),
                    current_item=idx,
                    total_items=total_items,
                    show_id=item.show_id,
                )

            _progress_cb(0, file_size)

            try:
                if episode.file_path and os.path.exists(episode.file_path) and os.path.abspath(episode.file_path) not in just_written_files and os.path.abspath(episode.file_path) != dest_abs:
                    try:
                        os.remove(episode.file_path)
                    except Exception:
                        pass

                if payload.import_mode == "move":
                    if os.path.abspath(item.file_path) != dest_abs:
                        move_file_with_progress(item.file_path, dest_video_path, callback=_progress_cb)
                elif payload.import_mode == "hardlink":
                    if os.path.abspath(item.file_path) != dest_abs:
                        try:
                            if os.path.exists(dest_video_path):
                                try:
                                    os.remove(dest_video_path)
                                except OSError:
                                    pass
                            os.link(item.file_path, dest_video_path)
                            logger.info("Глобальный ручной импорт: хардлинк успешно создан %s -> %s", item.file_path, dest_video_path)
                            _progress_cb(0, file_size)
                            _progress_cb(file_size, file_size)
                        except OSError as link_err:
                            logger.warning(
                                "Глобальный ручной импорт: не удалось создать хардлинк (%s), переключаемся на копирование: %s -> %s",
                                link_err, item.file_path, dest_video_path,
                            )
                            copy_file_with_progress(item.file_path, dest_video_path, callback=_progress_cb)
                else:
                    if os.path.abspath(item.file_path) != dest_abs:
                        copy_file_with_progress(item.file_path, dest_video_path, callback=_progress_cb)

                used_dest_paths.add(dest_abs)
                just_written_files.add(dest_abs)

                overall_bytes_copied += file_size
                _progress_cb(file_size, file_size)
                apply_media_permissions(dest_video_path, is_dir=False)

                # Перенос дорожек/субтитров/шрифтов
                src_dir = os.path.dirname(item.file_path)
                if os.path.isdir(src_dir):
                    source_release = find_release_files(src_dir)
                    companion_subs = match_companion_files_for_episode(
                        source_release.get("subtitle", []),
                        episode.episode_number,
                        episode.season_number,
                        item.file_path,
                        len(source_release.get("video", [])),
                    )
                    for sf in companion_subs:
                        sub_ext = os.path.splitext(sf)[1]
                        sub_tag = extract_companion_tag(sf, item.file_path, episode.episode_number, release_root=src_dir)
                        dest_sub_name = f"{target_stem}.{sub_tag}{sub_ext}" if sub_tag else f"{target_stem}{sub_ext}"
                        dest_sub_path = os.path.join(target_dir, dest_sub_name)
                        try:
                            if payload.import_mode == "move":
                                shutil.move(sf, dest_sub_path)
                            elif payload.import_mode == "hardlink":
                                try:
                                    if os.path.exists(dest_sub_path):
                                        os.remove(dest_sub_path)
                                    os.link(sf, dest_sub_path)
                                except OSError:
                                    shutil.copy2(sf, dest_sub_path)
                            else:
                                shutil.copy2(sf, dest_sub_path)
                            apply_media_permissions(dest_sub_path, is_dir=False)
                        except Exception:
                            pass

                    companion_audios = match_companion_files_for_episode(
                        source_release.get("audio", []),
                        episode.episode_number,
                        episode.season_number,
                        item.file_path,
                        len(source_release.get("video", [])),
                    )
                    for af in companion_audios:
                        aud_ext = os.path.splitext(af)[1]
                        aud_tag = extract_companion_tag(af, item.file_path, episode.episode_number, release_root=src_dir)
                        dest_aud_name = f"{target_stem}.{aud_tag}{aud_ext}" if aud_tag else f"{target_stem}{aud_ext}"
                        dest_aud_path = os.path.join(target_dir, dest_aud_name)
                        try:
                            if payload.import_mode == "move":
                                shutil.move(af, dest_aud_path)
                            elif payload.import_mode == "hardlink":
                                try:
                                    if os.path.exists(dest_aud_path):
                                        os.remove(dest_aud_path)
                                    os.link(af, dest_aud_path)
                                except OSError:
                                    shutil.copy2(af, dest_aud_path)
                            else:
                                shutil.copy2(af, dest_aud_path)
                            apply_media_permissions(dest_aud_path, is_dir=False)
                        except Exception:
                            pass

                q_info = parse_quality(os.path.basename(dest_video_path))
                episode.status = EpisodeStatus.DOWNLOADED
                episode.monitored = False
                episode.file_path = dest_video_path
                episode.download_progress = 1.0
                episode.downloaded_quality = quality
                episode.video_codec = q_info.video_codec
                episode.audio_codec = q_info.audio_codec
                episode.audio_channels = q_info.audio_channels
                episode.dynamic_range = q_info.dynamic_range
                episode.file_size_bytes = os.path.getsize(dest_video_path) if os.path.exists(dest_video_path) else None
                db.add(episode)
                try:
                    db.commit()
                except Exception:
                    pass
                imported_count += 1

                # Отправляем уведомление в мессенджеры для каждой импортированной серии
                try:
                    from app.services.notifications import notify_all_sync
                    if episode.season_number == 0:
                        ep_title = f" — «{episode.title}»" if episode.title else ""
                        sp_num_str = f"{episode.episode_number:02d}" if (episode.episode_number is not None and isinstance(episode.episode_number, int)) else str(episode.episode_number or "01")
                        notif_msg = (
                            f"📥 Импорт спецвыпуска для «{show.title}»:\n"
                            f"Серия: SP {sp_num_str}{ep_title}\n"
                            f"Файл: {file_name}\n"
                            f"Качество: {quality}"
                        )
                    elif show.content_type == "movie":
                        notif_msg = (
                            f"📥 Импорт фильма «{show.title}»:\n"
                            f"Файл: {file_name}\n"
                            f"Качество: {quality}"
                        )
                    else:
                        ep_title = f" — «{episode.title}»" if episode.title else ""
                        s_num_str = f"{episode.season_number:02d}" if (episode.season_number is not None and isinstance(episode.season_number, int)) else str(episode.season_number or "01")
                        e_num_str = f"{episode.episode_number:02d}" if (episode.episode_number is not None and isinstance(episode.episode_number, int)) else str(episode.episode_number or "01")
                        notif_msg = (
                            f"📥 Импорт серии для «{show.title}»:\n"
                            f"Серия: S{s_num_str}E{e_num_str}{ep_title}\n"
                            f"Файл: {file_name}\n"
                            f"Качество: {quality}"
                        )
                    notify_all_sync(db=None, event_type="import", message=notif_msg)
                except Exception:
                    pass
            except Exception as exc:
                errors.append(f"Ошибка при импорте {item.file_path}: {exc}")

        if imported_count > 0:
            # Применяем рекурсивные права ко всем затронутым шоу
            affected_show_ids = {it.show_id for it in payload.items}
            for s_id in affected_show_ids:
                s_obj = db.get(Show, s_id)
                if s_obj:
                    s_root = s_obj.path or get_show_default_path(s_obj, settings)
                    if s_root and os.path.exists(s_root):
                        apply_media_permissions(s_root, is_dir=True, recursive=True)

        db.commit()

        # Снимаем защиту ручного импорта для торрентов, у которых больше не осталось неимпортированных серий
        try:
            from app.services.downloads_monitor import unmark_torrent_pending_manual_import
            affected_hashes = set()
            affected_shows = set()
            for it in payload.items:
                if getattr(it, "show_id", None):
                    affected_shows.add(it.show_id)
                ep_obj = db.get(Episode, it.episode_id) if getattr(it, "episode_id", None) else None
                if ep_obj and getattr(ep_obj, "torrent_hash", None):
                    affected_hashes.add(ep_obj.torrent_hash.lower())

            for s_id in affected_shows:
                dh_list = db.query(DownloadHistory).filter(DownloadHistory.show_id == s_id).all()
                for dh in dh_list:
                    if getattr(dh, "torrent_hash", None):
                        affected_hashes.add(dh.torrent_hash.lower())

            for th in affected_hashes:
                rem_downloading = (
                    db.query(Episode)
                    .filter(
                        func.lower(Episode.torrent_hash) == th,
                        Episode.status == EpisodeStatus.DOWNLOADING,
                    )
                    .count()
                )
                if rem_downloading == 0:
                    unmark_torrent_pending_manual_import(th)
        except Exception as unmark_err:
            logger.debug("Ошибка unmark_torrent_pending_manual_import в global: %s", unmark_err)

        log_audit(
            db,
            "manual_import",
            f"Глобальный ручной импорт: {imported_count} файлов",
            username=current_user.username,
            user=current_user,
        )

        if errors:
            m_task.complete(f"Импортировано: {imported_count} из {total_items} (ошибок: {len(errors)})")
        else:
            m_task.complete(f"Успешно импортировано: {imported_count} файл(ов)")

    return {
        "success": True,
        "imported_count": imported_count,
        "errors": errors,
        "message": f"Успешно импортировано файлов: {imported_count}",
    }


@router.post("/{show_id}/fix-permissions")
def fix_show_permissions(
    show_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_permission("manage_library", "manage_settings")),
):
    """
    Принудительно рекурсивно устанавливает права доступа (0777 для папок, 0666 для файлов)
    для папки тайтла на диске, чтобы Jellyfin, Plex, Samba и DLNA могли беспрепятственно видеть и читать все файлы.
    """
    show = db.get(Show, show_id)
    if not show:
        raise HTTPException(404, "Шоу не найдено")

    settings = get_or_create_settings(db)
    show_root = show.path or get_show_default_path(show, settings)
    total_dirs = 0
    total_files = 0

    if show_root and os.path.exists(show_root):
        try:
            require_library_descendant(show_root, settings)
        except UnsafeMediaPathError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        stats = apply_media_permissions(show_root, is_dir=True, recursive=True)
        total_dirs += stats.get("dirs", 0)
        total_files += stats.get("files", 0)

    # Дополнительно проходим по всем файлам серий тайтла и их директориям
    for ep in (show.episodes or []):
        if ep.file_path and os.path.exists(ep.file_path):
            try:
                require_library_descendant(ep.file_path, settings)
            except UnsafeMediaPathError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            st = apply_media_permissions(ep.file_path, is_dir=False)
            total_files += st.get("files", 0)
            total_dirs += st.get("dirs", 0)

    if not show_root and total_files == 0 and total_dirs == 0:
        raise HTTPException(400, "Папка тайтла на диске не найдена")

    return {
        "success": True,
        "show_id": show_id,
        "path": show_root,
        "dirs_fixed": total_dirs,
        "files_fixed": total_files,
        "message": f"Права доступа успешно обновлены: папок — {total_dirs}, файлов — {total_files}",
    }


@router.post("/{show_id}/refresh-cover")
async def refresh_show_cover(
    show_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_library")),
):
    """
    Обновление постера карточки из правильного источника метаданных:
    - Для фильмов (category='movies' или content_type='movie') — исключительно из Radarr SkyHook (api.radarr.video) / TMDB.
    - Для сериалов и аниме (category in ('series', 'anime')) — исключительно из Sonarr SkyHook (skyhook.sonarr.tv) / TheTVDB / TVMaze.
    """
    from app.services.metadata import resolve_show_cover

    show = db.get(Show, show_id)
    if not show:
        raise HTTPException(404, "Карточка не найдена")

    is_movie = show.content_type == "movie" or show.category == "movies"
    poster_url, source_name = await resolve_show_cover(show, db=db)

    if not poster_url:
        target_service = "Radarr SkyHook (Movie Cloud)" if is_movie else "Sonarr SkyHook"
        raise HTTPException(404, f"Постер не найден в источниках метаданных ({target_service})")

    show.poster_source_url = poster_url
    from app.services.cover_service import download_and_store_show_cover
    local_url = await download_and_store_show_cover(show.id, poster_url)
    show.poster_url = local_url or poster_url
    db.commit()
    db.refresh(show)

    log_audit(
        db,
        "show.refresh_cover",
        f"Обновлен постер для карточки «{show.title}» из источника {source_name}",
        username=current_user.username,
        user=current_user,
    )

    return {
        "success": True,
        "poster_url": show.poster_url,
        "source_name": source_name or ("Radarr SkyHook" if is_movie else "Sonarr SkyHook"),
    }


@router.get("/{show_id}/poster", summary="Получить локальную обложку тайтла")
async def get_show_poster(
    show_id: int,
    request: Request,
):
    """
    Отдает локальный файл постера из /config/MediaCover/shows/{show_id}/poster.jpg
    с поддержкой ETag и 304 Not Modified.
    Если файла на диске нет, пытается автоматически скачать его по исходной ссылке.
    """
    from app.services.cover_service import get_show_poster_path, get_cover_etag, download_and_store_show_cover

    poster_path = get_show_poster_path(show_id)
    if not os.path.isfile(poster_path):
        try:
            from app.database import SessionLocal
            with SessionLocal() as db:
                show = db.get(Show, show_id)
                if show:
                    src_url = getattr(show, "poster_source_url", None) or show.poster_url
                    if src_url and not str(src_url).startswith(f"/api/v1/shows/{show_id}/poster"):
                        await download_and_store_show_cover(show_id, str(src_url))
        except Exception:
            pass

    if not os.path.isfile(poster_path):
        raise HTTPException(404, "Обложка не найдена")

    etag = get_cover_etag(poster_path)
    if_none_match = request.headers.get("if-none-match")
    if etag and if_none_match and if_none_match.strip() == etag:
        return Response(status_code=304, headers={"ETag": etag, "Cache-Control": "no-cache, must-revalidate"})

    headers = {"Cache-Control": "no-cache, must-revalidate"}
    if etag:
        headers["ETag"] = etag

    return FileResponse(poster_path, media_type="image/jpeg", headers=headers)


@router.post("/{show_id}/upload-cover", summary="Загрузить локальную обложку для тайтла")
async def upload_show_cover(
    show_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_library")),
):
    """
    Прямая загрузка обложки пользователем:
    сохраняет файл на диск в /config/MediaCover/shows/{show_id}/poster.jpg,
    выполняя оптимизацию размера, и обновляет poster_url с версионированием.
    """
    from app.services.cover_service import save_show_poster

    show = db.get(Show, show_id)
    if not show:
        raise HTTPException(404, "Карточка не найдена")

    contents = await _read_upload_with_limit(file)
    if not contents:
        raise HTTPException(400, "Файл пуст")

    local_url = await save_show_poster(show.id, contents)
    show.last_metadata_refresh_at = dt.datetime.utcnow()
    show.poster_url = local_url
    db.commit()
    db.refresh(show)

    log_audit(
        db,
        "show.upload_cover",
        f"Загружена новая обложка для карточки «{show.title}»",
        username=current_user.username,
        user=current_user,
    )

    return {"success": True, "poster_url": show.poster_url}


@router.api_route("/{show_id}/refresh-metadata", methods=["GET", "POST"], summary="Обновление метаданных тайтла из сети")
async def refresh_single_show_metadata(
    show_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_library")),
):
    """
    Обновление метаданных конкретного тайтла из SkyHook / TVDB / TMDB:
    - Обновление официальных названий серий (замена Episode X на реальные имена).
    - Обновление дат выхода и появление новых анонсированных серий/сезонов.
    - Обновление постера, рейтинга, жанров и синопсиса.
    """
    from app.services.metadata import refresh_show_metadata

    show = db.get(Show, show_id)
    if not show:
        raise HTTPException(404, "Карточка не найдена")

    res = await refresh_show_metadata(db, show)

    log_audit(
        db,
        "show.refresh_metadata",
        f"Обновлены метаданные для тайтла «{show.title}»: обновлено серий {res.get('episodes_updated', 0)}, добавлено {res.get('episodes_added', 0)}",
        username=current_user.username,
        user=current_user,
    )

    return {
        "success": True,
        "updated": res.get("updated", False),
        "episodes_updated": res.get("episodes_updated", 0),
        "episodes_added": res.get("episodes_added", 0),
        "message": f"Метаданные обновлены: серий обновлено — {res.get('episodes_updated', 0)}, добавлено новых — {res.get('episodes_added', 0)}",
    }


class ShowRemapIn(BaseModel):
    external_id: Optional[str] = None
    new_metadata_id: Optional[str] = None
    source_type: Optional[str] = None
    cleanup_unlinked_episodes: bool = True
    update_title: bool = True


@router.post("/{show_id}/remap", summary="Смена привязки метаданных тайтла и очистка некорректных серий")
async def remap_show_metadata(
    show_id: int,
    payload: ShowRemapIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_library")),
):
    """
    Выполняет смену привязки тайтла к источнику метаданных (SkyHook/TVDB/TMDB/AniList/Shikimori/Radarr),
    очищает ошибочно подтянутые серии без файлов и загружает корректную структуру сезонов и серий.
    """
    from app.models.db import MetadataSource, MetadataSourceType, Episode, EpisodeStatus, Alias, AliasLanguage
    from app.services.metadata import SkyHookClient, RadarrClient

    show = db.get(Show, show_id)
    if not show:
        raise HTTPException(404, "Карточка не найдена")

    ext_str = str(payload.external_id or payload.new_metadata_id or "").strip()
    if not ext_str:
        raise HTTPException(400, "Не указан external_id / new_metadata_id метаданных")

    is_movie = getattr(show, "content_type", None) == "movie"
    source = None
    source_type_name = (payload.source_type or "").lower()

    if source_type_name:
        source = db.query(MetadataSource).filter(MetadataSource.type == source_type_name, MetadataSource.enabled == True).first()

    if not source:
        if ext_str.startswith("tvdb:") or ext_str.startswith("skyhook:") or source_type_name in ("skyhook", "thetvdb"):
            source = db.query(MetadataSource).filter(MetadataSource.type.in_([MetadataSourceType.SKYHOOK, MetadataSourceType.THETVDB]), MetadataSource.enabled == True).first()
            if not source:
                source = MetadataSource(name="SkyHook (Sonarr)", type="skyhook", base_url="https://skyhook.sonarr.tv/v1/tvdb", enabled=True)
        elif ext_str.startswith("movie:") or ext_str.startswith("radarr:") or source_type_name in ("radarr", "radarr_skyhook") or is_movie:
            source = db.query(MetadataSource).filter(MetadataSource.type.in_([MetadataSourceType.RADARR, MetadataSourceType.TMDB]), MetadataSource.enabled == True).first()
            if not source:
                source = MetadataSource(name="Radarr SkyHook (Movie Cloud)", type="radarr", base_url="https://api.radarr.video/v1", enabled=True)
        elif ext_str.startswith("tmdb:") or ext_str.startswith("tv:") or source_type_name == "tmdb":
            source = db.query(MetadataSource).filter(MetadataSource.type == MetadataSourceType.TMDB, MetadataSource.enabled == True).first()
            if not source:
                source = MetadataSource(name="TMDB", type="tmdb", base_url="https://api.themoviedb.org/3", enabled=True)
        else:
            source = MetadataSource(name="SkyHook (Sonarr)", type="skyhook", base_url="https://skyhook.sonarr.tv/v1/tvdb", enabled=True)

    from app.models.db import AppSettings
    app_settings = db.query(AppSettings).filter(AppSettings.id == 1).first()
    overview_lang = getattr(app_settings, "metadata_overview_language", "ru") or "ru"
    client = get_metadata_client(source, overview_language=overview_lang)
    fallback_client = RadarrClient(overview_language=overview_lang) if is_movie else SkyHookClient(overview_language=overview_lang)
    details = None

    try:
        details = await client.get_details(ext_str)
    except Exception as exc:
        logger.debug("Primary metadata client get_details failed for %s: %s", ext_str, exc)

    if not details and client != fallback_client:
        try:
            details = await fallback_client.get_details(ext_str)
        except Exception as exc:
            logger.debug("Fallback metadata client get_details failed for %s: %s", ext_str, exc)

    if not details:
        raise HTTPException(404, f"Не удалось найти метаданные для {ext_str}")

    now = dt.datetime.utcnow()
    show.metadata_id = details.external_id or ext_str
    show.metadata_source = source.type.value if hasattr(source.type, "value") else str(source.type)

    if payload.update_title and details.title:
        show.title = details.title
    if getattr(details, "overview", None):
        show.overview = details.overview
    if getattr(details, "poster_url", None):
        show.poster_url = details.poster_url
    if getattr(details, "rating", None) is not None:
        show.rating = details.rating
    if getattr(details, "genre", None):
        show.genre = details.genre
    if getattr(details, "network", None):
        show.network = details.network
    if getattr(details, "year", None):
        show.year = details.year
    if getattr(details, "imdb_id", None):
        show.imdb_id = details.imdb_id
    if getattr(details, "tmdb_id", None):
        show.tmdb_id = details.tmdb_id
    if getattr(details, "tvdb_id", None):
        show.tvdb_id = details.tvdb_id
    if getattr(details, "tvmaze_id", None):
        show.tvmaze_id = details.tvmaze_id
    if getattr(details, "mal_id", None):
        show.mal_id = details.mal_id
    if getattr(details, "anilist_id", None):
        show.anilist_id = details.anilist_id
    if getattr(details, "anidb_id", None):
        show.anidb_id = details.anidb_id
    if getattr(details, "shikimori_id", None):
        show.shikimori_id = details.shikimori_id
    if getattr(details, "trailer_url", None):
        show.trailer_url = details.trailer_url

    show.last_metadata_refresh_at = now

    existing_eps = db.query(Episode).filter(Episode.show_id == show.id).all()
    existing_by_key = {(ep.season_number, ep.episode_number): ep for ep in existing_eps}

    # Множество ключей серий из новых метаданных
    if is_movie:
        meta_keys = {(1, 1)}
    else:
        meta_keys = {
            (ep.season_number if ep.season_number is not None else 1, ep.episode_number)
            for ep in (details.episodes or [])
            if ep.episode_number is not None
        }

    deleted_episodes_count = 0
    if payload.cleanup_unlinked_episodes:
        eps_to_delete = []
        for key, ep in list(existing_by_key.items()):
            if key not in meta_keys:
                has_real_file = False
                if ep.file_path:
                    try:
                        has_real_file = os.path.exists(ep.file_path)
                    except Exception:
                        has_real_file = False
                is_active_download = (ep.status == EpisodeStatus.DOWNLOADING and bool(ep.torrent_hash))
                if not has_real_file and not is_active_download:
                    eps_to_delete.append(ep)
                    del existing_by_key[key]

        if eps_to_delete:
            ep_ids = [ep.id for ep in eps_to_delete if getattr(ep, "id", None) is not None]
            if ep_ids:
                try:
                    db.query(DownloadHistory).filter(DownloadHistory.episode_id.in_(ep_ids)).update(
                        {"episode_id": None}, synchronize_session=False
                    )
                except Exception as dh_exc:
                    logger.warning("Failed to unlink download_history for deleted episodes %s: %s", ep_ids, dh_exc)
            for ep in eps_to_delete:
                db.delete(ep)
                deleted_episodes_count += 1

    added_episodes_count = 0
    updated_episodes_count = 0

    if is_movie:
        ep_m = existing_by_key.get((1, 1))
        if ep_m:
            if details.title:
                ep_m.title = details.title
            db.add(ep_m)
            updated_episodes_count += 1
        else:
            new_ep = Episode(
                show_id=show.id,
                season_number=1,
                episode_number=1,
                title=details.title or show.title,
                status=EpisodeStatus.WANTED,
            )
            db.add(new_ep)
            existing_by_key[(1, 1)] = new_ep
            added_episodes_count += 1
    elif details.episodes:
        future_seasons = set()
        for me in details.episodes:
            if me.air_date:
                try:
                    mad = dt.datetime.fromisoformat(str(me.air_date)[:10])
                    if mad > now:
                        future_seasons.add(me.season_number if me.season_number is not None else 1)
                except Exception:
                    pass

        seen_added_keys = set()
        for meta_ep in details.episodes:
            if meta_ep.episode_number is None:
                continue
            s_num = meta_ep.season_number if meta_ep.season_number is not None else 1
            e_num = meta_ep.episode_number
            ep_key = (s_num, e_num)
            if ep_key in seen_added_keys:
                continue
            seen_added_keys.add(ep_key)

            air_date = None
            if meta_ep.air_date:
                try:
                    air_date = dt.datetime.fromisoformat(str(meta_ep.air_date)[:10])
                except ValueError:
                    air_date = None

            raw_ep_title = (meta_ep.title or "").strip()
            if raw_ep_title in ("None", "null", "TBA", "tba", ""):
                raw_ep_title = None

            is_unaired = bool(
                (air_date and air_date > now)
                or (air_date is None and (s_num in future_seasons or (show.premiere_date and show.premiere_date > now)))
            )

            ep_db = existing_by_key.get(ep_key)
            if ep_db:
                if raw_ep_title:
                    ep_db.title = raw_ep_title
                elif not ep_db.title:
                    ep_db.title = "TBA"
                if air_date:
                    ep_db.air_date = air_date
                if meta_ep.absolute_number is not None:
                    ep_db.absolute_number = meta_ep.absolute_number
                if is_unaired and ep_db.status not in (EpisodeStatus.IGNORED, EpisodeStatus.DOWNLOADED) and not getattr(ep_db, "file_path", None):
                    ep_db.status = EpisodeStatus.UNAIRED
                    ep_db.monitored = True
                elif air_date and ep_db.status in (EpisodeStatus.UNAIRED, EpisodeStatus.MISSING, EpisodeStatus.WANTED):
                    ep_db.status = EpisodeStatus.UNAIRED if air_date > now else EpisodeStatus.WANTED
                db.add(ep_db)
                updated_episodes_count += 1
            else:
                status = EpisodeStatus.UNAIRED if is_unaired else EpisodeStatus.WANTED
                monitored = True if is_unaired else getattr(show, "monitored", True)
                new_ep = Episode(
                    show_id=show.id,
                    season_number=s_num,
                    episode_number=e_num,
                    absolute_number=meta_ep.absolute_number,
                    title=raw_ep_title or "TBA",
                    air_date=air_date,
                    status=status,
                    monitored=monitored,
                )
                db.add(new_ep)
                existing_by_key[ep_key] = new_ep
                added_episodes_count += 1

    # Обновляем алиасы из источника
    if details.aliases:
        alias_rows = db.query(Alias).filter(Alias.show_id == show.id).all()
        existing_aliases = {
            getattr(a, "text", "").lower().strip()
            for a in alias_rows
            if getattr(a, "text", None)
        }
        all_priorities = [
            a.priority
            for a in alias_rows
            if getattr(a, "priority", None) is not None
        ]
        cur_max_p = max(all_priorities) if all_priorities else 0
        from app.services.metadata import get_allowed_metadata_languages, is_alias_allowed, detect_alias_language
        allowed_langs = get_allowed_metadata_languages(db, show)
        for alias_text in details.aliases:
            clean_alias = str(alias_text).strip()
            if clean_alias and clean_alias.lower() not in existing_aliases:
                if not is_alias_allowed(clean_alias, None, allowed_langs):
                    continue
                existing_aliases.add(clean_alias.lower())
                cur_max_p += 1
                det_lang = detect_alias_language(clean_alias)
                db.add(Alias(
                    show_id=show.id,
                    text=clean_alias,
                    language=det_lang,
                    source="remap",
                    priority=cur_max_p,
                ))

    try:
        db.commit()
        db.refresh(show)
    except Exception as commit_exc:
        db.rollback()
        logger.exception("Failed to commit show remap for show %s: %s", show.id, commit_exc)
        raise HTTPException(500, f"Ошибка сохранения новой привязки в базе данных: {commit_exc}")

    try:
        from app.services.blocklist_service import relink_blocklist_for_show
        relink_blocklist_for_show(db, show)
    except Exception:
        pass

    log_audit(
        db,
        "show.remap_metadata",
        f"Сменена привязка метаданных для «{show.title}» на {ext_str}. Очищено серий: {deleted_episodes_count}, добавлено: {added_episodes_count}",
        username=current_user.username,
        user=current_user,
    )

    return {
        "success": True,
        "message": f"Привязка успешно обновлена. Очищено серий: {deleted_episodes_count}, добавлено серий: {added_episodes_count}",
        "deleted_episodes": deleted_episodes_count,
        "added_episodes": added_episodes_count,
        "show_id": show.id,
    }


@router.get("/{show_id}/rename/preview", summary="Предпросмотр переименования файлов тайтла")
def preview_rename_show(
    show_id: int,
    season: Optional[int] = Query(None, description="Номер сезона для фильтрации"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_library")),
):
    """
    Формирует diff предпросмотра упорядочивания и переименования файлов в стиле Sonarr/Radarr.
    """
    from app.services.organizer import FileNameBuilder
    from app.models.db import DownloadHistory, TrackedRelease

    show = db.get(Show, show_id)
    if not show:
        raise HTTPException(404, "Карточка не найдена")

    settings = get_or_create_settings(db)
    show_root = os.path.abspath(show.path) if show.path else ""

    if show.content_type == "movie":
        template = settings.rename_template_movie or "{Movie Title} ({Release Year}) {Quality Full}"
    elif show.content_type == "anime":
        template = settings.rename_template_anime or "{Series Title} - S{season:00}E{episode:00} - {Episode Title} {Quality Full}"
    else:
        template = settings.rename_template_series or "{Series Title} - S{season:00}E{episode:00} - {Episode Title} {Quality Full}"

    show_hints = [show.title, os.path.basename(show.path or "")]
    try:
        hist = db.query(DownloadHistory).filter_by(show_id=show.id).order_by(DownloadHistory.id.desc()).first()
        if hist and hist.release_title:
            show_hints.append(hist.release_title)
        tr = db.query(TrackedRelease).filter_by(show_id=show.id).order_by(TrackedRelease.id.desc()).first()
        if tr and tr.topic_guid:
            show_hints.append(tr.topic_guid)
    except Exception:
        pass

    q = db.query(Episode).filter(Episode.show_id == show.id)
    if season is not None:
        q = q.filter(Episode.season_number == season)
    episodes = q.order_by(Episode.season_number.asc(), Episode.episode_number.asc()).all()

    items = []

    for ep in episodes:
        if not ep.file_path or not os.path.exists(ep.file_path):
            continue

        old_full_path = os.path.abspath(ep.file_path)
        if show_root and old_full_path.startswith(show_root):
            try:
                old_rel_path = os.path.relpath(old_full_path, show_root)
            except Exception:
                old_rel_path = os.path.basename(old_full_path)
        else:
            old_rel_path = os.path.basename(old_full_path)

        q_info = detect_file_quality(old_full_path, show_hints)
        ext = os.path.splitext(old_full_path)[1]

        new_filename = FileNameBuilder.build_file_name(
            template=template,
            title=getattr(show, "title", ""),
            year=getattr(show, "year", None),
            season_number=getattr(ep, "season_number", 1) or 1,
            episode_number=getattr(ep, "episode_number", 1) or 1,
            absolute_number=getattr(ep, "absolute_number", None),
            episode_title=getattr(ep, "title", "") or f"Серия {getattr(ep, 'episode_number', 1)}",
            quality=q_info,
            content_type=getattr(show, "content_type", "series"),
            extension=ext,
        )

        if show.content_type == "movie":
            new_rel_path = new_filename
        else:
            old_rel_dir = os.path.dirname(old_rel_path)
            if old_rel_dir and old_rel_dir not in (".", ""):
                season_folder = old_rel_dir
            else:
                season_tpl = (
                    getattr(settings, "season_folder_template_anime", None)
                    if show.content_type == "anime"
                    else getattr(settings, "season_folder_template_series", None)
                ) or getattr(settings, "media_naming_season_folder", None) or "Сезон {season}"
                season_folder = FileNameBuilder.build_season_folder_name(season_tpl, getattr(ep, "season_number", 1) or 1)
            new_rel_path = os.path.normpath(os.path.join(season_folder, new_filename))

        new_full_path = os.path.abspath(os.path.join(show_root, new_rel_path)) if show_root else new_filename
        needs_rename = (old_full_path != new_full_path)

        items.append({
            "episode_id": ep.id,
            "season_number": getattr(ep, "season_number", 1) or 1,
            "episode_number": getattr(ep, "episode_number", 1) or 1,
            "absolute_number": getattr(ep, "absolute_number", None),
            "episode_title": ep.title,
            "existing_path": old_full_path,
            "existing_rel_path": old_rel_path,
            "new_path": new_full_path,
            "new_rel_path": new_rel_path,
            "needs_rename": needs_rename,
        })

    return {
        "show_id": show.id,
        "show_title": show.title,
        "show_path": show.path or "",
        "naming_template": template,
        "items": items,
    }


@router.post("/{show_id}/rename/execute", summary="Выполнить переименование выбранных файлов тайтла")
def execute_rename_show(
    show_id: int,
    payload: Dict[str, Any],
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_library")),
):
    """
    Переименовывает и перемещает файлы на диске, обновляя пути в базе данных.
    """
    from app.services.organizer import FileNameBuilder
    from app.models.db import DownloadHistory, TrackedRelease

    show = db.get(Show, show_id)
    if not show:
        raise HTTPException(404, "Карточка не найдена")

    settings = get_or_create_settings(db)
    show_root = os.path.abspath(show.path) if show.path else ""
    if not show_root or not os.path.exists(show_root):
        raise HTTPException(400, f"Директория тайтла не существует на диске: {show.path}")

    if show.content_type == "movie":
        template = settings.rename_template_movie or "{Movie Title} ({Release Year}) {Quality Full}"
    elif show.content_type == "anime":
        template = settings.rename_template_anime or "{Series Title} - S{season:00}E{episode:00} - {Episode Title} {Quality Full}"
    else:
        template = settings.rename_template_series or "{Series Title} - S{season:00}E{episode:00} - {Episode Title} {Quality Full}"

    show_hints = [show.title, os.path.basename(show.path or "")]
    try:
        hist = db.query(DownloadHistory).filter_by(show_id=show.id).order_by(DownloadHistory.id.desc()).first()
        if hist and hist.release_title:
            show_hints.append(hist.release_title)
        tr = db.query(TrackedRelease).filter_by(show_id=show.id).order_by(TrackedRelease.id.desc()).first()
        if tr and tr.topic_guid:
            show_hints.append(tr.topic_guid)
    except Exception:
        pass

    ep_ids = payload.get("episode_ids", [])
    target_ep_ids = set(ep_ids)
    if not target_ep_ids:
        return {"success": True, "renamed_count": 0, "errors": []}

    episodes = db.query(Episode).filter(Episode.show_id == show.id, Episode.id.in_(target_ep_ids)).all()

    renamed_count = 0
    errors: list[str] = []

    for ep in episodes:
        if not ep.file_path or not os.path.exists(ep.file_path):
            continue

        old_full_path = os.path.abspath(ep.file_path)
        try:
            old_rel_path = os.path.relpath(old_full_path, show_root)
        except Exception:
            old_rel_path = os.path.basename(old_full_path)

        q_info = detect_file_quality(old_full_path, show_hints)
        ext = os.path.splitext(old_full_path)[1]

        new_filename = FileNameBuilder.build_file_name(
            template=template,
            title=getattr(show, "title", ""),
            year=getattr(show, "year", None),
            season_number=getattr(ep, "season_number", 1) or 1,
            episode_number=getattr(ep, "episode_number", 1) or 1,
            absolute_number=getattr(ep, "absolute_number", None),
            episode_title=getattr(ep, "title", "") or f"Серия {getattr(ep, 'episode_number', 1)}",
            quality=q_info,
            content_type=getattr(show, "content_type", "series"),
            extension=ext,
        )

        if show.content_type == "movie":
            new_rel_path = new_filename
        else:
            old_rel_dir = os.path.dirname(old_rel_path)
            if old_rel_dir and old_rel_dir not in (".", ""):
                season_folder = old_rel_dir
            else:
                season_tpl = (
                    getattr(settings, "season_folder_template_anime", None)
                    if show.content_type == "anime"
                    else getattr(settings, "season_folder_template_series", None)
                ) or getattr(settings, "media_naming_season_folder", None) or "Сезон {season}"
                season_folder = FileNameBuilder.build_season_folder_name(season_tpl, ep.season_number or 1)
            new_rel_path = os.path.normpath(os.path.join(season_folder, new_filename))

        new_full_path = os.path.abspath(os.path.join(show_root, new_rel_path))
        if old_full_path == new_full_path:
            continue

        try:
            dest_dir = os.path.dirname(new_full_path)
            os.makedirs(dest_dir, exist_ok=True)

            # Переименовываем и переносим сопутствующие файлы (субтитры, озвучки .mka, nfo)
            old_dir = os.path.dirname(old_full_path)
            old_stem = os.path.splitext(os.path.basename(old_full_path))[0]
            new_stem = os.path.splitext(os.path.basename(new_full_path))[0]

            COMPANION_EXTS = {
                ".srt", ".ass", ".ssa", ".sub", ".idx", ".vtt",
                ".mka", ".ac3", ".dts", ".eac3", ".aac", ".flac", ".mp3", ".wav",
                ".nfo", ".txt"
            }

            moved_companions = set()

            # 1. Файлы в той же директории, начинающиеся с old_stem
            if os.path.exists(old_dir):
                for f_name in os.listdir(old_dir):
                    src_companion = os.path.join(old_dir, f_name)
                    if not os.path.isfile(src_companion) or src_companion == old_full_path:
                        continue
                    ext_c = os.path.splitext(f_name)[1].lower()
                    if f_name.startswith(old_stem) and ext_c in COMPANION_EXTS:
                        suffix = f_name[len(old_stem):]
                        dst_companion = os.path.join(dest_dir, f"{new_stem}{suffix}")
                        try:
                            shutil.move(src_companion, dst_companion)
                            apply_media_permissions(dst_companion, is_dir=False)
                            moved_companions.add(src_companion)
                        except Exception as c_err:
                            errors.append(f"Ошибка переноса {f_name}: {c_err}")

            # 2. Файлы в подпапках (Subs, Subtitles, Audio, Audios, Sound, Tracks) или по номеру серии
            potential_dirs = []
            if os.path.exists(old_dir):
                for sub_d in ["subs", "subtitles", "sub", "субтитры", "audio", "audios", "sound", "звук", "озвучка", "tracks", "rus", "eng", "jap"]:
                    d_p = os.path.join(old_dir, sub_d)
                    if os.path.isdir(d_p):
                        potential_dirs.append(d_p)

            ep_nums = {ep.episode_number}
            if ep.absolute_number is not None:
                ep_nums.add(ep.absolute_number)

            for p_dir in potential_dirs:
                if not os.path.exists(p_dir):
                    continue
                for f_name in os.listdir(p_dir):
                    src_companion = os.path.join(p_dir, f_name)
                    if not os.path.isfile(src_companion) or src_companion in moved_companions or src_companion == old_full_path:
                        continue
                    ext_c = os.path.splitext(f_name)[1].lower()
                    if ext_c not in COMPANION_EXTS:
                        continue

                    parsed_c = parse_episode(f_name)
                    is_match = False
                    if parsed_c and parsed_c.episodes and any(e in ep_nums for e in parsed_c.episodes):
                        if parsed_c.season is None or parsed_c.season == ep.season_number:
                            is_match = True
                    elif any(f"{n:02d}" in f_name or f"e{n:02d}" in f_name.lower() or f"- {n}" in f_name for n in ep_nums if n is not None):
                        is_match = True

                    if is_match:
                        tag = extract_companion_tag(src_companion, old_full_path, ep.episode_number or 1)
                        dst_name = f"{new_stem}.{tag}{ext_c}" if tag else f"{new_stem}{ext_c}"
                        dst_companion = os.path.join(dest_dir, dst_name)
                        try:
                            shutil.move(src_companion, dst_companion)
                            apply_media_permissions(dst_companion, is_dir=False)
                            moved_companions.add(src_companion)
                        except Exception as c_err:
                            errors.append(f"Ошибка переноса {f_name}: {c_err}")

            # Перемещаем основной видеофайл
            shutil.move(old_full_path, new_full_path)
            apply_media_permissions(new_full_path, is_dir=False)

            ep.file_path = new_full_path
            ep.downloaded_quality = q_info.name
            ep.video_codec = q_info.video_codec
            ep.audio_codec = q_info.audio_codec
            ep.audio_channels = q_info.audio_channels
            ep.dynamic_range = q_info.dynamic_range

            renamed_count += 1

            # Очищаем старую пустую папку, если она внутри show_root и не является самим show_root
            if old_dir != show_root and old_dir.startswith(show_root) and os.path.exists(old_dir):
                try:
                    if not os.listdir(old_dir):
                        os.rmdir(old_dir)
                except Exception:
                    pass

        except Exception as exc:
            errors.append(f"Ошибка переименования {os.path.basename(old_full_path)}: {exc}")

    db.commit()

    if renamed_count > 0:
        log_audit(
            db,
            "show.rename_files",
            f"Переименовано {renamed_count} файлов для «{show.title}»",
            username=current_user.username,
            user=current_user,
        )

    return {
        "success": len(errors) == 0,
        "renamed_count": renamed_count,
        "errors": errors,
    }
