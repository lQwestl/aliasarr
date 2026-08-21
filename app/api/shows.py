import datetime as dt
import os
import shutil

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

import re

from app.database import get_db
from app.models.db import Alias, Episode, EpisodeStatus, Show, User
from app.schemas import AliasCreate, AliasOut, AliasUpdate, EpisodeOut, ShowCreate, ShowOut, ShowUpdate
from app.services.audit_service import log_audit
from app.services.parser import ReleaseKind, parse_episode
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
from app.services.quality import parse_quality
from app.services.settings_service import get_or_create_settings
from app.services.user_service import require_permission, get_current_user

router = APIRouter(prefix="/api/v1/shows", tags=["shows"])


def _attach_computed_fields(db: Session, shows: list[Show]) -> list[ShowOut]:
    """Добавляет к каждому шоу агрегаты для табличного вида библиотеки:
    количество сезонов/серий и дату ближайшего невышедшего эфира."""
    if not shows:
        return []

    settings = get_or_create_settings(db)
    has_path_updates = False
    for s in shows:
        if not s.path:
            def_path = get_show_default_path(s, settings)
            if def_path:
                s.path = def_path
                db.add(s)
                has_path_updates = True
    if has_path_updates:
        try:
            db.commit()
        except Exception:
            db.rollback()

    show_ids = [s.id for s in shows]
    now = dt.datetime.utcnow()

    counts = dict(
        db.query(Episode.show_id, func.count(func.distinct(Episode.season_number)))
        .filter(Episode.show_id.in_(show_ids))
        .group_by(Episode.show_id)
        .all()
    )
    ep_counts = dict(
        db.query(Episode.show_id, func.count(Episode.id))
        .filter(Episode.show_id.in_(show_ids))
        .group_by(Episode.show_id)
        .all()
    )
    dl_counts = dict(
        db.query(Episode.show_id, func.count(Episode.id))
        .filter(Episode.show_id.in_(show_ids), Episode.status == EpisodeStatus.DOWNLOADED)
        .group_by(Episode.show_id)
        .all()
    )
    downloading_counts = dict(
        db.query(Episode.show_id, func.count(Episode.id))
        .filter(Episode.show_id.in_(show_ids), Episode.status == EpisodeStatus.DOWNLOADING)
        .group_by(Episode.show_id)
        .all()
    )
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
        item.seasons_count = counts.get(show.id, 0)
        item.episodes_count = ep_counts.get(show.id, 0)
        item.downloaded_episodes_count = dl_counts.get(show.id, 0)
        item.downloading_episodes_count = downloading_counts.get(show.id, 0)
        item.next_airing = next_airing.get(show.id) or show.premiere_date
        out.append(item)
    return out


@router.get("", response_model=list[ShowOut])
def list_shows(db: Session = Depends(get_db), current_user: User = Depends(require_permission("view_library"))):
    shows = db.query(Show).all()
    return _attach_computed_fields(db, shows)


def _find_duplicate_show(db: Session, title: str, metadata_source: str | None, metadata_id: str | None) -> Show | None:
    if metadata_source and metadata_id:
        existing = (
            db.query(Show)
            .filter(Show.metadata_source == metadata_source, Show.metadata_id == metadata_id)
            .first()
        )
        if existing:
            return existing
    normalized = title.strip().lower()
    if not normalized:
        return None
    return db.query(Show).filter(func.lower(Show.title) == normalized).first()


@router.post("", response_model=ShowOut, status_code=201, summary="Добавить тайтл в библиотеку")
async def create_show(
    payload: ShowCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_library")),
):
    """
    Добавление нового фильма, сериала или аниме в библиотеку.
    Автоматически создаёт служебную запись серии для фильмов и сохраняет алиасы на всех языках.
    """
    duplicate = _find_duplicate_show(db, payload.title, payload.metadata_source, payload.metadata_id)
    if duplicate:
        raise HTTPException(409, f"Шоу «{duplicate.title}» уже добавлено в библиотеку (id={duplicate.id})")

    if payload.content_type not in ("movie", "series", "anime"):
        raise HTTPException(400, "content_type должен быть movie, series или anime")

    settings = get_or_create_settings(db)
    final_path = payload.path or get_show_default_path(
        Show(title=payload.title, year=payload.year, content_type=payload.content_type),
        settings,
    )

    show = Show(
        title=payload.title,
        year=payload.year,
        metadata_source=payload.metadata_source,
        metadata_id=payload.metadata_id,
        overview=payload.overview,
        poster_url=payload.poster_url,
        path=final_path,
        quality_profile_id=payload.quality_profile_id,
        content_type=payload.content_type,
    )
    db.add(show)
    db.flush()  # получаем show.id до коммита

    added_aliases = set()
    for alias_in in payload.aliases:
        if alias_in.text.lower() not in added_aliases:
            added_aliases.add(alias_in.text.lower())
            db.add(Alias(show_id=show.id, text=alias_in.text, language=alias_in.language, source=alias_in.source))

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

    from app.services.notifications import notify_all
    try:
        await notify_all(
            db,
            "series_add",
            f"🎬 В библиотеку добавлен тайтл: {show.title}{f' ({show.year})' if show.year else ''}",
        )
    except Exception:
        pass

    return ShowOut.model_validate(show)


@router.get("/{show_id}", response_model=ShowOut, summary="Получить информацию о тайтле")
def get_show(show_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_permission("view_library"))):
    """Возвращает подробную информацию о тайтле со списком серий, алиасов и прогрессом скачивания."""
    show = db.get(Show, show_id)
    if not show:
        raise HTTPException(404, "Show not found")

    needs_commit = False
    today = dt.date.today()
    for ep in show.episodes:
        air_d = ep.air_date
        if isinstance(air_d, dt.datetime):
            air_d = air_d.date()
        target_default_status = (
            EpisodeStatus.IGNORED
            if getattr(ep, "monitor_status", None) == MonitorStatus.IGNORED or not getattr(show, "monitored", True)
            else (EpisodeStatus.UNAIRED if air_d and air_d > today else EpisodeStatus.WANTED)
        )

        # Проверяем физический файл серии на диске
        if ep.file_path:
            if os.path.exists(ep.file_path):
                if ep.status != EpisodeStatus.DOWNLOADED:
                    ep.status = EpisodeStatus.DOWNLOADED
                    ep.download_progress = 1.0
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
            # Файла нет: очищаем качество и MediaInfo, если они случайно остались
            if ep.downloaded_quality is not None or ep.file_size_bytes is not None or ep.video_codec is not None:
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
            elif ep.status == EpisodeStatus.DOWNLOADING and not ep.torrent_hash:
                ep.status = target_default_status
                ep.download_progress = 0.0
                needs_commit = True

    if needs_commit:
        try:
            db.commit()
            db.refresh(show)
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
        # 1. Удаляем отдельные файлы серий
        for ep in episodes:
            if ep.file_path and os.path.isfile(ep.file_path):
                try:
                    os.remove(ep.file_path)
                except Exception as exc:
                    pass
        # 2. Удаляем папку тайтла, если существует
        if show_path and os.path.isdir(show_path):
            try:
                shutil.rmtree(show_path, ignore_errors=True)
            except Exception as exc:
                pass

    db.delete(show)
    db.commit()

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


@router.put("/{show_id}", response_model=ShowOut)
def update_show(
    show_id: int,
    payload: ShowUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_library")),
):
    show = db.get(Show, show_id)
    if not show:
        raise HTTPException(404, "Show not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(show, field, value)
    db.add(show)
    db.commit()
    db.refresh(show)
    return show


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
    # Приоритет по умолчанию — в конец очереди поиска
    priority = payload.priority
    if priority is None:
        max_priority = db.query(func.max(Alias.priority)).filter(Alias.show_id == show_id).scalar()
        priority = (max_priority or 0) + 1
    alias = Alias(show_id=show_id, text=payload.text, language=payload.language, source=payload.source, priority=priority)
    db.add(alias)
    db.commit()
    db.refresh(alias)
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
    if payload.text is not None:
        text = payload.text.strip()
        if not text:
            raise HTTPException(400, "Текст алиаса не может быть пустым")
        alias.text = text
    if payload.language is not None:
        alias.language = payload.language
    if payload.priority is not None:
        alias.priority = payload.priority
    db.add(alias)
    db.commit()
    db.refresh(alias)
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


@router.get("/{show_id}/episodes", response_model=list[EpisodeOut])
def list_episodes(show_id: int, db: Session = Depends(get_db), current_user: User = Depends(require_permission("view_library"))):
    show = db.get(Show, show_id)
    if not show:
        raise HTTPException(404, "Show not found")
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
        air_d = ep.air_date
        if isinstance(air_d, dt.datetime):
            air_d = air_d.date()
        target_default_status = (
            EpisodeStatus.IGNORED
            if getattr(ep, "monitor_status", None) == MonitorStatus.IGNORED or not getattr(show, "monitored", True)
            else (EpisodeStatus.UNAIRED if air_d and air_d > today else EpisodeStatus.WANTED)
        )

        has_real_file = bool(ep.file_path and os.path.exists(ep.file_path))
        if ep.file_path and not has_real_file:
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
        elif not ep.file_path:
            if ep.downloaded_quality is not None or ep.video_codec is not None:
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
            pass
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
    db.commit()
    return {"show_id": show_id, "monitored": monitored}


@router.put("/{show_id}/seasons/{season_number}/monitor")
def set_season_monitored(
    show_id: int,
    season_number: int,
    monitored: bool,
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

    for ep in episodes:
        if ep.status == EpisodeStatus.DOWNLOADED:
            continue  # уже скачанные серии не трогаем
        ep.status = EpisodeStatus.WANTED if monitored else EpisodeStatus.IGNORED
        db.add(ep)
    db.commit()
    return {"show_id": show_id, "season": season_number, "monitored": monitored, "affected": len(episodes)}


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
    from app.services.auto_search import search_and_grab_show

    show = db.get(Show, show_id)
    if not show:
        raise HTTPException(404, "Show not found")

    result = await search_and_grab_show(db, show)
    db.refresh(show)
    return {
        "show_id": show_id,
        "grabbed": result.get("grabbed", []),
        "status": show.last_search_result,
        "last_search_at": show.last_search_at,
    }


class SearchEpisodesIn(BaseModel):
    episode_ids: list[int]


@router.post("/{show_id}/search-episodes")
async def search_selected_episodes(
    show_id: int,
    payload: SearchEpisodesIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manual_search")),
):
    """Поиск и скачивание ТОЛЬКО выбранных пользователем серий (не всего сезона) —
    отмечаются флажками в карточке видео."""
    from app.services.auto_search import search_and_grab_show

    show = db.get(Show, show_id)
    if not show:
        raise HTTPException(404, "Show not found")
    if not payload.episode_ids:
        raise HTTPException(400, "Не выбрано ни одной серии")

    episodes = db.query(Episode).filter(Episode.id.in_(payload.episode_ids), Episode.show_id == show_id).all()
    if not episodes:
        raise HTTPException(404, "Серии не найдены")

    # Автопоиск ищет только серии в статусе "разыскивается" — выбранные вручную серии,
    # которые ещё не в этом статусе (например, были проигнорированы), переводим в него.
    for ep in episodes:
        if ep.status in (EpisodeStatus.IGNORED, EpisodeStatus.MISSING, EpisodeStatus.UNAIRED):
            ep.status = EpisodeStatus.WANTED
            db.add(ep)
    db.commit()

    result = await search_and_grab_show(db, show, episode_ids=set(payload.episode_ids))
    db.refresh(show)
    grabbed_ids = {g["episode_id"] for g in result.get("grabbed", [])}
    return {
        "show_id": show_id,
        "grabbed": result.get("grabbed", []),
        "requested": len(payload.episode_ids),
        "success": bool(grabbed_ids),
        "message": (
            f"Захвачено серий: {len(grabbed_ids)} из {len(payload.episode_ids)}"
            if grabbed_ids else "Подходящих релизов для выбранных серий не найдено"
        ),
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
    from app.services.auto_search import search_and_grab_show

    show = db.get(Show, show_id)
    if not show:
        raise HTTPException(404, "Show not found")

    season_episodes = (
        db.query(Episode)
        .filter(Episode.show_id == show_id, Episode.season_number == season_number)
        .all()
    )
    if not season_episodes:
        raise HTTPException(404, f"Серии сезона {season_number} не найдены")

    # Переводим неотслеживаемые/пропущенные серии сезона в WANTED
    now = dt.datetime.utcnow()
    for ep in season_episodes:
        if ep.status in (EpisodeStatus.IGNORED, EpisodeStatus.MISSING) or (
            ep.status == EpisodeStatus.UNAIRED and (ep.air_date is None or ep.air_date <= now)
        ):
            ep.status = EpisodeStatus.WANTED
            db.add(ep)
    db.commit()

    target_ids = {ep.id for ep in season_episodes}
    result = await search_and_grab_show(db, show, episode_ids=target_ids)
    db.refresh(show)
    grabbed_ids = {g["episode_id"] for g in result.get("grabbed", [])}
    return {
        "show_id": show_id,
        "season_number": season_number,
        "grabbed": result.get("grabbed", []),
        "requested": len(season_episodes),
        "success": bool(grabbed_ids),
        "message": (
            f"Сезон {season_number}: захвачено серий {len(grabbed_ids)} из {len(season_episodes)}"
            if grabbed_ids else f"Сезон {season_number}: подходящих релизов не найдено"
        ),
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
            air_d = ep.air_date
            if isinstance(air_d, dt.datetime):
                air_d = air_d.date()
            target_default_status = (
                EpisodeStatus.IGNORED
                if getattr(ep, "monitor_status", None) == MonitorStatus.IGNORED or not getattr(show, "monitored", True)
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
        db.commit()
        return {"imported_count": 0, "path": show.path, "message": f"Видеофайлы не найдены в {show.path}. Статусы сброшены."}

    if show.content_type == "movie":
        non_samples = [f for f in video_files if not _SAMPLE_RE.search(os.path.basename(f))]
        target_files = non_samples if non_samples else video_files
        if target_files:
            main_file = max(target_files, key=lambda f: os.path.getsize(f) if os.path.exists(f) else 0)
            q_info = parse_quality(os.path.basename(main_file))
            episode = next((e for e in episodes if e.season_number == 1 and e.episode_number == 1), None)
            if not episode and episodes:
                episode = episodes[0]
            if not episode:
                episode = Episode(show_id=show.id, season_number=1, episode_number=1, title=show.title)
            episode.status = EpisodeStatus.DOWNLOADED
            episode.file_path = main_file
            episode.download_progress = 1.0
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
            q_info = parse_quality(filename)

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

            if matched_ep:
                matched_ep.status = EpisodeStatus.DOWNLOADED
                matched_ep.file_path = file_path
                matched_ep.download_progress = 1.0
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
            if ep.file_path and not os.path.exists(ep.file_path):
                air_d = ep.air_date
                if isinstance(air_d, dt.datetime):
                    air_d = air_d.date()
                target_default_status = (
                    EpisodeStatus.IGNORED
                    if getattr(ep, "monitor_status", None) == MonitorStatus.IGNORED or not getattr(show, "monitored", True)
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
            elif not ep.file_path:
                if ep.downloaded_quality is not None or ep.video_codec is not None:
                    ep.downloaded_quality = None
                    ep.file_size_bytes = None
                    ep.video_codec = None
                    ep.audio_codec = None
                    ep.audio_channels = None
                    ep.dynamic_range = None
                    ep.release_group = None
                    db.add(ep)

    db.commit()
    return {"imported_count": imported_count, "path": show.path, "message": f"Синхронизировано серий: {imported_count}"}


# ---------------------------------------------------------------------------
# Ручной и интерактивный импорт медиафайлов
# ---------------------------------------------------------------------------

class ManualImportScanIn(BaseModel):
    folder_path: str | None = None


class ManualImportFileCandidate(BaseModel):
    file_path: str
    relative_path: str
    filename: str
    size_bytes: int
    detected_quality: str
    parsed_season: int | None = None
    parsed_episode: int | None = None
    parsed_absolute: int | None = None
    matched_episode_id: int | None = None
    existing_file: str | None = None


class ManualImportScanOut(BaseModel):
    show_id: int
    show_title: str | None = None
    show_year: int | None = None
    content_type: str = "series"
    folder_path: str
    files: list[ManualImportFileCandidate]
    episodes: list[EpisodeOut]


class ManualImportItemIn(BaseModel):
    file_path: str
    episode_id: int
    quality: str | None = None


class ManualImportExecuteIn(BaseModel):
    import_mode: str = "move"  # "move" | "copy"
    items: list[ManualImportItemIn]


class GlobalManualImportFileCandidate(BaseModel):
    file_path: str
    relative_path: str
    filename: str
    size_bytes: int
    detected_quality: str
    matched_show_id: int | None = None
    matched_show_title: str | None = None
    parsed_season: int | None = None
    parsed_episode: int | None = None
    parsed_absolute: int | None = None
    matched_episode_id: int | None = None
    existing_file: str | None = None


class GlobalManualImportScanOut(BaseModel):
    folder_path: str
    files: list[GlobalManualImportFileCandidate]
    shows: list[dict]
    episodes_by_show: dict[int, list[EpisodeOut]]


class GlobalManualImportItemIn(BaseModel):
    file_path: str
    show_id: int
    episode_id: int
    quality: str | None = None


class GlobalManualImportExecuteIn(BaseModel):
    import_mode: str = "move"  # "move" | "copy"
    items: list[GlobalManualImportItemIn]


@router.post("/{show_id}/manual-import/scan", response_model=ManualImportScanOut)
def scan_for_manual_import(
    show_id: int,
    payload: ManualImportScanIn | None = None,
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

    settings = get_or_create_settings(db)
    folder_path = (payload.folder_path if payload and payload.folder_path else "").strip()
    if not folder_path:
        folder_path = show.path
        if not folder_path:
            folder_path = get_show_default_path(show, settings)

    if not folder_path:
        raise HTTPException(400, "Укажите папку для сканирования")

    if not os.path.exists(folder_path):
        raise HTTPException(404, f"Папка «{folder_path}» не существует на диске")

    release_files = find_release_files(folder_path)
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
    video_files.sort(key=lambda p: natural_sort_key(os.path.relpath(p, folder_path) if os.path.exists(p) else p))

    episodes = (
        db.query(Episode)
        .filter(Episode.show_id == show.id)
        .order_by(Episode.season_number, Episode.episode_number)
        .all()
    )

    file_candidates: list[ManualImportFileCandidate] = []

    for file_path in video_files:
        filename = os.path.basename(file_path)
        try:
            rel_path = os.path.relpath(file_path, folder_path)
        except Exception:
            rel_path = filename

        size_bytes = os.path.getsize(file_path) if os.path.exists(file_path) else 0
        quality = parse_quality(filename).name
        parsed = parse_episode(filename)

        # 1. Если по имени файла не распознан сезон/серия, пробуем имя родительской папки
        parent_dir = os.path.basename(os.path.dirname(file_path))
        if (parsed.kind == ReleaseKind.UNKNOWN or not parsed.episodes or parsed.season is None) and parent_dir and parent_dir != os.path.basename(folder_path):
            parent_parsed = parse_episode(parent_dir + " " + filename)
            if parent_parsed.episodes or parent_parsed.season is not None:
                if not parsed.episodes:
                    parsed.episodes = parent_parsed.episodes
                if parsed.season is None:
                    parsed.season = parent_parsed.season
                if parsed.kind == ReleaseKind.UNKNOWN:
                    parsed.kind = parent_parsed.kind

        # 2. Если сезон всё ещё None, ищем номер сезона в иерархии папок (напр. "Season 2", "S02", "Спецвыпуски", "Specials")
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

        matched_ep = None
        p_season = parsed.season
        p_episode = parsed.episodes[0] if parsed.episodes else None
        p_abs = parsed.episodes[0] if (parsed.kind == ReleaseKind.ABSOLUTE and parsed.episodes) else None

        if show.content_type == "movie":
            matched_ep = next((e for e in episodes if e.season_number == 1 and e.episode_number == 1), None)
            if not matched_ep and episodes:
                matched_ep = episodes[0]
        else:
            # 1. Явный сезон и номер серии
            if parsed.season is not None and parsed.episodes:
                matched_ep = next((e for e in episodes if e.season_number == parsed.season and e.episode_number in parsed.episodes), None)

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

    episodes_out = [EpisodeOut.model_validate(e) for e in episodes]
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
        (settings.season_folder_template_anime if show.content_type == "anime" else settings.season_folder_template_series)
        or "Season {season:02d}"
    )
    if show.content_type == "movie":
        rename_template = settings.rename_template_movie or "{Movie Title} ({Release Year}) {Quality Full}"
    elif show.content_type == "anime":
        rename_template = settings.rename_template_anime or "{Series Title} - S{season:02d}E{episode:02d} - {Episode Title}"
    else:
        rename_template = settings.rename_template_series or "{Series Title} - S{season:02d}E{episode:02d} - {Episode Title}"

    imported_count = 0
    errors: list[str] = []
    total_items = len(payload.items)
    valid_items = [it for it in payload.items if os.path.exists(it.file_path)]
    total_bytes = sum(os.path.getsize(it.file_path) for it in valid_items) or 1
    overall_bytes_copied = 0

    with task_manager.track_sync(
        name="manual_import",
        title=f"Ручной импорт: {show.title}",
        message=f"Подготовка к импорту {total_items} файлов...",
        progress=0.0,
        show_id=show.id,
        total_items=total_items,
        current_item=0,
    ) as m_task:
        for idx, item in enumerate(payload.items, 1):
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
                    show_title=show.title,
                    season=episode.season_number,
                    episode=episode.episode_number,
                    episode_title=episode.title or "",
                    absolute=episode.absolute_number or episode.episode_number,
                    quality=quality,
                    year=show.year,
                )
            dest_video_path = os.path.join(target_dir, target_stem + ext)

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
                if episode.file_path and os.path.exists(episode.file_path) and os.path.abspath(episode.file_path) != os.path.abspath(dest_video_path):
                    try:
                        os.remove(episode.file_path)
                    except Exception:
                        pass

                if payload.import_mode == "move":
                    if os.path.abspath(item.file_path) != os.path.abspath(dest_video_path):
                        move_file_with_progress(item.file_path, dest_video_path, callback=_progress_cb)
                else:
                    if os.path.abspath(item.file_path) != os.path.abspath(dest_video_path):
                        copy_file_with_progress(item.file_path, dest_video_path, callback=_progress_cb)

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

                episode.status = EpisodeStatus.DOWNLOADED
                episode.file_path = dest_video_path
                episode.download_progress = 1.0
                episode.downloaded_quality = quality
                db.add(episode)
                imported_count += 1
            except Exception as exc:
                errors.append(f"Ошибка при импорте {item.file_path}: {exc}")

        db.commit()
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
    payload: ManualImportScanIn | None = None,
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
        aliases = build_alias_candidates(s)
        shows_with_aliases.append((s, aliases))

    for file_path in video_files:
        filename = os.path.basename(file_path)
        try:
            rel_path = os.path.relpath(file_path, folder_path)
        except Exception:
            rel_path = filename

        size_bytes = os.path.getsize(file_path) if os.path.exists(file_path) else 0
        quality = parse_quality(filename).name
        parsed = parse_episode(filename)

        parent_dir_name = os.path.basename(os.path.dirname(file_path))
        grandparent_dir_name = os.path.basename(os.path.dirname(os.path.dirname(file_path)))
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
                match = match_release(s_name, s.id, aliases, content_type=s.content_type)
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
    valid_items = [it for it in payload.items if os.path.exists(it.file_path)]
    total_bytes = sum(os.path.getsize(it.file_path) for it in valid_items) or 1
    overall_bytes_copied = 0

    with task_manager.track_sync(
        name="global_manual_import",
        title="Глобальный ручной импорт",
        message=f"Подготовка к импорту {total_items} файлов...",
        progress=0.0,
        total_items=total_items,
        current_item=0,
    ) as m_task:
        for idx, item in enumerate(payload.items, 1):
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
                (settings.season_folder_template_anime if show.content_type == "anime" else settings.season_folder_template_series)
                or "Season {season:02d}"
            )
            if show.content_type == "movie":
                rename_template = settings.rename_template_movie or "{Movie Title} ({Release Year}) {Quality Full}"
            elif show.content_type == "anime":
                rename_template = settings.rename_template_anime or "{Series Title} - S{season:02d}E{episode:02d} - {Episode Title}"
            else:
                rename_template = settings.rename_template_series or "{Series Title} - S{season:02d}E{episode:02d} - {Episode Title}"

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
                    show_title=show.title,
                    season=episode.season_number,
                    episode=episode.episode_number,
                    episode_title=episode.title or "",
                    absolute=episode.absolute_number or episode.episode_number,
                    quality=quality,
                    year=show.year,
                )
            dest_video_path = os.path.join(target_dir, target_stem + ext)

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
                if episode.file_path and os.path.exists(episode.file_path) and os.path.abspath(episode.file_path) != os.path.abspath(dest_video_path):
                    try:
                        os.remove(episode.file_path)
                    except Exception:
                        pass

                if payload.import_mode == "move":
                    if os.path.abspath(item.file_path) != os.path.abspath(dest_video_path):
                        move_file_with_progress(item.file_path, dest_video_path, callback=_progress_cb)
                else:
                    if os.path.abspath(item.file_path) != os.path.abspath(dest_video_path):
                        copy_file_with_progress(item.file_path, dest_video_path, callback=_progress_cb)

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
                            else:
                                shutil.copy2(af, dest_aud_path)
                            apply_media_permissions(dest_aud_path, is_dir=False)
                        except Exception:
                            pass

                q_info = parse_quality(os.path.basename(dest_video_path))
                episode.status = EpisodeStatus.DOWNLOADED
                episode.file_path = dest_video_path
                episode.download_progress = 1.0
                episode.downloaded_quality = quality
                episode.video_codec = q_info.video_codec
                episode.audio_codec = q_info.audio_codec
                episode.audio_channels = q_info.audio_channels
                episode.dynamic_range = q_info.dynamic_range
                episode.file_size_bytes = os.path.getsize(dest_video_path) if os.path.exists(dest_video_path) else None
                db.add(episode)
                imported_count += 1
            except Exception as exc:
                errors.append(f"Ошибка при импорте {item.file_path}: {exc}")

        db.commit()
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

    show.poster_url = poster_url
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
