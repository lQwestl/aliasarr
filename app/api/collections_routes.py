from __future__ import annotations

import datetime as dt
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, or_, and_
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.user_service import require_permission, get_current_user
from app.models.db import Show, MovieCollection, Episode, EpisodeStatus, User
from app.schemas import (
    MovieCollectionCreate,
    MovieCollectionUpdate,
    MovieCollectionOut,
    ShowOut,
)
from app.api.shows import _attach_computed_fields

logger = logging.getLogger("aliasarr.collections")

router = APIRouter(prefix="/api/v1/collections", tags=["collections"])


class FranchisePart(BaseModel):
    tmdb_id: int
    title: str
    year: Optional[int] = None
    release_date: Optional[str] = None
    overview: Optional[str] = None
    poster_url: Optional[str] = None
    rating: Optional[float] = None
    in_library: bool = False
    show_id: Optional[int] = None
    show_status: Optional[str] = None


class MovieCollectionDetailOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    tmdb_collection_id: Optional[int] = None
    title: str
    overview: Optional[str] = None
    poster_url: Optional[str] = None
    backdrop_url: Optional[str] = None
    monitored: bool = True
    quality_profile_id: Optional[int] = None
    root_folder: Optional[str] = None
    created_at: Optional[dt.datetime] = None
    shows_count: int = 0
    parts_count: Optional[int] = 0
    downloaded_count: int = 0
    missing_count: int = 0
    shows: list[ShowOut] = []
    franchise_parts: list[FranchisePart] = []


class ImportMissingPayload(BaseModel):
    tmdb_id: Optional[int] = None
    tmdb_ids: Optional[list[int]] = None
    quality_profile_id: Optional[int] = None
    root_folder: Optional[str] = None
    monitored: bool = True
    auto_search: bool = True


@router.get("", response_model=list[MovieCollectionOut])
def list_collections(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("view_library")),
):
    """Список всех киноколлекций и франшиз с агрегированной статистикой."""
    collections = db.query(MovieCollection).order_by(func.lower(MovieCollection.title)).all()
    if not collections:
        return []

    coll_ids = [c.id for c in collections]

    # Считаем количество фильмов в каждой коллекции
    shows_in_colls = db.query(Show.id, Show.collection_id).filter(Show.collection_id.in_(coll_ids)).all()
    show_to_coll = {s[0]: s[1] for s in shows_in_colls}
    show_ids = list(show_to_coll.keys())

    coll_shows_count = {}
    for s_id, c_id in shows_in_colls:
        coll_shows_count[c_id] = coll_shows_count.get(c_id, 0) + 1

    coll_downloaded_count = {}
    if show_ids:
        dl_episodes = (
            db.query(Episode.show_id)
            .filter(
                Episode.show_id.in_(show_ids),
                or_(
                    Episode.status == EpisodeStatus.DOWNLOADED,
                    and_(Episode.file_path.isnot(None), Episode.file_path != ""),
                ),
            )
            .all()
        )
        for ep in dl_episodes:
            c_id = show_to_coll.get(ep.show_id)
            if c_id:
                coll_downloaded_count[c_id] = coll_downloaded_count.get(c_id, 0) + 1

    out: list[MovieCollectionOut] = []
    for c in collections:
        shows_in_lib = coll_shows_count.get(c.id, 0)
        dl_s = coll_downloaded_count.get(c.id, 0)
        total_parts = c.parts_count or shows_in_lib
        out.append(
            MovieCollectionOut(
                id=c.id,
                tmdb_collection_id=c.tmdb_collection_id,
                title=c.title,
                overview=c.overview,
                poster_url=c.poster_url,
                backdrop_url=c.backdrop_url,
                monitored=c.monitored,
                quality_profile_id=c.quality_profile_id,
                root_folder=c.root_folder,
                created_at=c.created_at,
                shows_count=shows_in_lib,
                parts_count=total_parts,
                downloaded_count=dl_s,
                missing_count=max(0, total_parts - shows_in_lib),
            )
        )

    return out


@router.get("/{collection_id}", response_model=MovieCollectionDetailOut)
async def get_collection_detail(
    collection_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("view_library")),
):
    """Подробная информация о киноколлекции со всеми фильмами саги (в библиотеке и отсутствующими)."""
    coll = db.get(MovieCollection, collection_id)
    if not coll:
        raise HTTPException(404, "Movie collection not found")

    shows = db.query(Show).filter(Show.collection_id == coll.id).order_by(Show.collection_order, Show.year).all()
    shows_out = _attach_computed_fields(db, shows)

    shows_by_tmdb_id = {}
    for s in shows:
        clean_id = (s.metadata_id or "").replace("movie:", "").replace("tmdb:", "").strip()
        if clean_id.isdigit():
            shows_by_tmdb_id[int(clean_id)] = s

    franchise_parts: list[FranchisePart] = []
    if coll.tmdb_collection_id:
        try:
            from app.services.metadata import RadarrClient
            client = RadarrClient()
            data = await client.get_collection_details(coll.tmdb_collection_id)
            for part in data.get("parts", []):
                tmdb_id = part.get("tmdb_id")
                matched_show = shows_by_tmdb_id.get(tmdb_id)
                in_lib = matched_show is not None
                show_st = None
                show_id_val = None
                if matched_show:
                    show_id_val = matched_show.id
                    ep = db.query(Episode).filter(Episode.show_id == matched_show.id).first()
                    show_st = ep.status if ep else "wanted"

                franchise_parts.append(
                    FranchisePart(
                        tmdb_id=tmdb_id,
                        title=part.get("title") or "",
                        year=part.get("year"),
                        release_date=part.get("release_date"),
                        overview=part.get("overview"),
                        poster_url=part.get("poster_url"),
                        rating=part.get("rating"),
                        in_library=in_lib,
                        show_id=show_id_val,
                        show_status=show_st,
                    )
                )
        except Exception as e:
            logger.debug("Failed to fetch live franchise parts for collection %s: %s", coll.id, e)

    total_parts = len(franchise_parts) if franchise_parts else len(shows)
    if coll.tmdb_collection_id and total_parts and coll.parts_count != total_parts:
        coll.parts_count = total_parts
        db.add(coll)
        db.commit()

    if coll.quality_profile_id is None and shows:
        for s in shows:
            if s.quality_profile_id:
                coll.quality_profile_id = s.quality_profile_id
                db.add(coll)
                db.commit()
                break

    total_s = len(shows)
    dl_s = sum(1 for s in shows_out if s.downloaded_episodes_count > 0)
    missing_cnt = max(0, total_parts - total_s)

    return MovieCollectionDetailOut(
        id=coll.id,
        tmdb_collection_id=coll.tmdb_collection_id,
        title=coll.title,
        overview=coll.overview,
        poster_url=coll.poster_url,
        backdrop_url=coll.backdrop_url,
        monitored=coll.monitored,
        quality_profile_id=coll.quality_profile_id,
        root_folder=coll.root_folder,
        created_at=coll.created_at,
        shows_count=total_s,
        parts_count=total_parts,
        downloaded_count=dl_s,
        missing_count=missing_cnt,
        shows=shows_out,
        franchise_parts=franchise_parts,
    )


@router.post("", response_model=MovieCollectionOut, status_code=201)
def create_collection(
    payload: MovieCollectionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_library")),
):
    """Создать новую коллекцию фильмов вручную или по TMDb Collection ID."""
    if payload.tmdb_collection_id:
        existing = db.query(MovieCollection).filter(MovieCollection.tmdb_collection_id == payload.tmdb_collection_id).first()
        if existing:
            raise HTTPException(409, f"Коллекция «{existing.title}» уже существует (ID: {existing.id})")

    coll = MovieCollection(
        tmdb_collection_id=payload.tmdb_collection_id,
        title=payload.title.strip(),
        overview=payload.overview,
        poster_url=payload.poster_url,
        backdrop_url=payload.backdrop_url,
        monitored=payload.monitored,
        quality_profile_id=payload.quality_profile_id,
        root_folder=payload.root_folder,
    )
    db.add(coll)
    db.commit()
    db.refresh(coll)
    return MovieCollectionOut.model_validate(coll)


@router.put("/{collection_id}", response_model=MovieCollectionOut)
def update_collection(
    collection_id: int,
    payload: MovieCollectionUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_library")),
):
    """Обновить параметры коллекции (название, мониторинг, профиль качества, корневую папку)."""
    coll = db.get(MovieCollection, collection_id)
    if not coll:
        raise HTTPException(404, "Movie collection not found")

    dumped = payload.model_dump(exclude_unset=True)
    for k, v in dumped.items():
        setattr(coll, k, v)

    db.add(coll)
    db.commit()
    db.refresh(coll)
    return MovieCollectionOut.model_validate(coll)


@router.delete("/{collection_id}", status_code=204)
def delete_collection(
    collection_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_library")),
):
    """Удалить коллекцию (фильмы остаются в библиотеке, но отвязываются от саги)."""
    coll = db.get(MovieCollection, collection_id)
    if not coll:
        raise HTTPException(404, "Movie collection not found")

    # Отвязываем связанные фильмы
    db.query(Show).filter(Show.collection_id == coll.id).update(
        {"collection_id": None, "collection_order": None},
        synchronize_session=False,
    )
    db.delete(coll)
    db.commit()


@router.post("/{collection_id}/import-missing", status_code=200)
async def import_missing_collection_movies(
    collection_id: int,
    payload: ImportMissingPayload = ImportMissingPayload(),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_library")),
):
    """Массовый или точечный импорт недостающих фильмов саги/франшизы из TMDb в Aliasarr."""
    coll = db.get(MovieCollection, collection_id)
    if not coll:
        raise HTTPException(404, "Movie collection not found")
    if not coll.tmdb_collection_id:
        raise HTTPException(400, "Коллекция не привязана к TMDb Collection ID")

    from app.services.metadata import RadarrClient, refresh_show_metadata
    from app.services.settings_service import get_or_create_settings
    from app.services.postprocess import get_show_default_path
    from app.services.organizer import clean_show_title_and_year

    client = RadarrClient()
    try:
        data = await client.get_collection_details(coll.tmdb_collection_id)
    except Exception as e:
        raise HTTPException(502, f"Не удалось получить список фильмов коллекции из TMDb: {e}")

    parts_list = data.get("parts", [])
    if parts_list and coll.parts_count != len(parts_list):
        coll.parts_count = len(parts_list)
        db.add(coll)
        db.commit()

    settings = get_or_create_settings(db)
    from app.models.db import QualityProfile
    qp_id = payload.quality_profile_id or coll.quality_profile_id
    if qp_id is None:
        # 1. Проверяем профиль у уже добавленных фильмов этой коллекции
        existing_coll_show = (
            db.query(Show.quality_profile_id)
            .filter(Show.collection_id == coll.id, Show.quality_profile_id.isnot(None))
            .first()
        )
        if existing_coll_show and existing_coll_show[0]:
            qp_id = existing_coll_show[0]
        else:
            # 2. Берем первый профиль качества в системе
            default_qp = db.query(QualityProfile).first()
            if default_qp:
                qp_id = default_qp.id

    if qp_id and coll.quality_profile_id != qp_id:
        coll.quality_profile_id = qp_id
        db.add(coll)
        db.commit()

    existing_tmdb_ids = set()
    existing_shows = db.query(Show).all()
    for s in existing_shows:
        cid = (s.metadata_id or "").replace("movie:", "").replace("tmdb:", "").strip()
        if cid.isdigit():
            existing_tmdb_ids.add(int(cid))

    added_shows: list[dict] = []
    order_idx = 1

    for part in parts_list:
        tmdb_id = part.get("tmdb_id")
        if not tmdb_id or tmdb_id in existing_tmdb_ids:
            order_idx += 1
            continue

        if payload.tmdb_id and tmdb_id != payload.tmdb_id:
            order_idx += 1
            continue
        if payload.tmdb_ids and tmdb_id not in payload.tmdb_ids:
            order_idx += 1
            continue

        p_title = (part.get("title") or "").strip()
        p_year = part.get("year")
        p_overview = part.get("overview")
        p_poster = part.get("poster_url")

        clean_p_title, clean_p_year = clean_show_title_and_year(p_title, p_year)

        show = Show(
            title=clean_p_title,
            year=clean_p_year,
            metadata_source="tmdb",
            metadata_id=f"movie:{tmdb_id}",
            overview=p_overview,
            poster_url=p_poster,
            quality_profile_id=qp_id,
            content_type="movie",
            monitored=payload.monitored,
            collection_id=coll.id,
            collection_order=order_idx,
        )

        custom_root = payload.root_folder or coll.root_folder
        if custom_root:
            from app.services.postprocess import sanitize_filename, _title_without_year
            folder_name = f"{sanitize_filename(_title_without_year(clean_p_title))} ({clean_p_year})" if clean_p_year else sanitize_filename(clean_p_title)
            import os
            show.path = os.path.join(custom_root, folder_name)
        else:
            show.path = get_show_default_path(show, settings)

        db.add(show)
        db.flush()

        # Создаем запись Episode S01E01 для фильма
        db.add(Episode(
            show_id=show.id,
            season_number=1,
            episode_number=1,
            title=clean_p_title,
            status=EpisodeStatus.WANTED if payload.monitored else EpisodeStatus.IGNORED,
        ))
        db.commit()
        db.refresh(show)

        existing_tmdb_ids.add(tmdb_id)
        added_shows.append({"id": show.id, "title": show.title, "year": show.year})
        order_idx += 1

        # Фоновое обновление метаданных
        try:
            await refresh_show_metadata(db, show)
            db.commit()
        except Exception as e:
            logger.debug("Failed to refresh metadata on imported movie %s: %s", show.id, e)

    # Запускаем фоновый автопоиск через безопасную отдельную сессию БД
    if payload.auto_search and payload.monitored and added_shows:
        import asyncio
        from app.database import SessionLocal
        from app.services.auto_search import search_and_grab_show

        for s_info in added_shows:
            target_id = s_info["id"]

            async def _bg_search(sid=target_id):
                bg_db = SessionLocal()
                try:
                    s_obj = bg_db.get(Show, sid)
                    if s_obj:
                        await search_and_grab_show(bg_db, s_obj)
                except Exception as exc:
                    logger.debug("Background auto-search on movie %s failed: %s", sid, exc)
                finally:
                    bg_db.close()

            asyncio.create_task(_bg_search())

    return {
        "success": True,
        "collection_id": coll.id,
        "collection_title": coll.title,
        "added_count": len(added_shows),
        "added_shows": added_shows,
    }
