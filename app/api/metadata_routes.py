from __future__ import annotations

from typing import Optional, List, Dict, Any

import asyncio
import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.db import Alias, Episode, EpisodeStatus, MetadataSource, MetadataSourceType, Show, User
from app.services.metadata import MetadataResult, RadarrClient, SkyHookClient, get_metadata_client
from app.services.user_service import require_permission, get_current_user
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/metadata-sources", tags=["metadata"])


def _normalize_source_type(val: str | MetadataSourceType) -> MetadataSourceType:
    if isinstance(val, MetadataSourceType):
        return val
    try:
        return MetadataSourceType(str(val).lower())
    except Exception:
        return MetadataSourceType.TMDB


class MetadataSourceIn(BaseModel):
    name: str
    type: str  # tmdb|tvmaze|custom
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    field_mapping: dict = {}
    enabled: bool = True


class MetadataSourceOut(BaseModel):
    id: int
    name: str
    type: str
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    field_mapping: dict = {}
    enabled: bool = True

    class Config:
        from_attributes = True


class MetadataSearchResultOut(BaseModel):
    external_id: str
    title: str
    year: Optional[int]
    overview: Optional[str] = None
    poster_url: Optional[str] = None
    rating: Optional[float] = None
    country: Optional[str] = None
    genre: Optional[str] = None
    content_type: Optional[str] = None
    already_added: bool = False
    existing_show_id: Optional[int] = None


class ImportShowRequest(BaseModel):
    source_id: Optional[int] = None
    external_id: str
    path: Optional[str] = None
    # Категория контента (movie | series | anime), выбранная пользователем при добавлении
    content_type: Optional[str] = None


def _parse_date(value: Optional[str]) -> Optional[dt.datetime]:
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _find_existing_show(
    db: Session,
    *,
    metadata_source: Optional[str] = None,
    metadata_id: Optional[str] = None,
    title: str,
    year: Optional[int] = None,
    content_type: Optional[str] = None,
    imdb_id: Optional[str] = None,
    tmdb_id: Optional[int] = None,
    tvdb_id: Optional[int] = None,
) -> Optional[Show]:
    """Ищет уже добавленное шоу.
    1. Точное совпадение по metadata_source + metadata_id.
    2. Прямое совпадение по metadata_id или числовому ID.
    3. Совпадение по глобальным уникальным ID (tmdb_id, tvdb_id, imdb_id).
    4. Совпадение по названию ТОЛЬКО при условии совпадения типа контента (movie/series)
       И совпадения года выпуска (если год известен для обоих).
    """
    if metadata_source and metadata_id:
        existing = (
            db.query(Show)
            .filter(Show.metadata_source == metadata_source, Show.metadata_id == metadata_id)
            .first()
        )
        if existing:
            return existing

    if metadata_id:
        existing = db.query(Show).filter(Show.metadata_id == metadata_id).first()
        if existing:
            return existing

        clean_id_str = metadata_id.split(":")[-1].strip()
        if clean_id_str.isdigit():
            num_id = int(clean_id_str)
            if metadata_id.startswith(("movie:", "radarr:", "tmdb:")) or content_type == "movie":
                existing = db.query(Show).filter(
                    or_(
                        Show.tmdb_id == num_id,
                        Show.metadata_id.in_([f"movie:{num_id}", f"radarr:{num_id}", f"tmdb:{num_id}", str(num_id)]),
                    )
                ).first()
                if existing:
                    return existing
            elif metadata_id.startswith(("tvdb:", "skyhook:")) or content_type in ("series", "anime"):
                existing = db.query(Show).filter(
                    or_(
                        Show.tvdb_id == num_id,
                        Show.metadata_id.in_([f"tvdb:{num_id}", f"skyhook:{num_id}", str(num_id)]),
                    )
                ).first()
                if existing:
                    return existing

    if tmdb_id:
        existing = db.query(Show).filter(Show.tmdb_id == tmdb_id).first()
        if existing:
            return existing
    if tvdb_id:
        existing = db.query(Show).filter(Show.tvdb_id == tvdb_id).first()
        if existing:
            return existing
    if imdb_id:
        existing = db.query(Show).filter(Show.imdb_id == imdb_id).first()
        if existing:
            return existing

    normalized = (title or "").strip().lower()
    if not normalized:
        return None

    candidates = db.query(Show).filter(func.lower(Show.title) == normalized).all()
    if not candidates:
        return None

    for c in candidates:
        if content_type:
            c_type = c.content_type or "series"
            req_type = "movie" if content_type == "movie" else "series"
            cand_type = "movie" if c_type == "movie" else "series"
            if req_type != cand_type:
                continue

        if year is not None and c.year is not None:
            if c.year != year:
                continue

        return c

    return None


@router.get("", response_model=list[MetadataSourceOut])
def list_sources(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    sources = db.query(MetadataSource).all()
    # Гарантируем строковое представление type для Pydantic
    res = []
    for s in sources:
        type_str = s.type.value if hasattr(s.type, "value") else str(s.type)
        res.append(MetadataSourceOut(
            id=s.id,
            name=s.name,
            type=type_str,
            base_url=s.base_url,
            api_key=s.api_key,
            field_mapping=s.field_mapping or {},
            enabled=s.enabled,
        ))
    return res


@router.post("", response_model=MetadataSourceOut, status_code=201)
def create_source(
    payload: MetadataSourceIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_settings")),
):
    data = payload.model_dump()
    source_type = _normalize_source_type(data.get("type", "tmdb"))
    type_str = source_type.value if hasattr(source_type, "value") else str(source_type).lower()
    data["type"] = type_str
    if not data.get("base_url"):
        if type_str == "radarr":
            data["base_url"] = "https://api.radarr.video/v1"
        elif type_str == "tmdb":
            data["base_url"] = "https://api.themoviedb.org/3"
        elif type_str == "tvmaze":
            data["base_url"] = "https://api.tvmaze.com"
        elif type_str == "thetvdb":
            data["base_url"] = "https://api4.thetvdb.com/v4"

    source = MetadataSource(**data)
    db.add(source)
    db.commit()
    db.refresh(source)
    return MetadataSourceOut(
        id=source.id,
        name=source.name,
        type=str(source.type),
        base_url=source.base_url,
        api_key=source.api_key,
        field_mapping=source.field_mapping or {},
        enabled=source.enabled,
    )


@router.put("/{source_id}", response_model=MetadataSourceOut)
def update_source(
    source_id: int,
    payload: MetadataSourceIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_settings")),
):
    source = db.get(MetadataSource, source_id)
    if not source:
        raise HTTPException(404, "Source not found")
    data = payload.model_dump()
    if "type" in data:
        source_type = _normalize_source_type(data["type"])
        type_str = source_type.value if hasattr(source_type, "value") else str(source_type).lower()
        data["type"] = type_str
    else:
        type_str = str(source.type)

    if not data.get("base_url"):
        if type_str == "radarr":
            data["base_url"] = "https://api.radarr.video/v1"
        elif type_str == "tmdb":
            data["base_url"] = "https://api.themoviedb.org/3"
        elif type_str == "tvmaze":
            data["base_url"] = "https://api.tvmaze.com"
        elif type_str == "thetvdb":
            data["base_url"] = "https://api4.thetvdb.com/v4"

    for field_name, value in data.items():
        setattr(source, field_name, value)
    db.add(source)
    db.commit()
    db.refresh(source)
    return MetadataSourceOut(
        id=source.id,
        name=source.name,
        type=str(source.type),
        base_url=source.base_url,
        api_key=source.api_key,
        field_mapping=source.field_mapping or {},
        enabled=source.enabled,
    )


@router.post("/test")
async def test_metadata_source_config(
    payload: MetadataSourceIn,
    current_user: User = Depends(require_permission("manage_settings")),
):
    """Проверяет подключение к источнику метаданных по переданным параметрам."""
    source_type = _normalize_source_type(payload.type)
    type_str = source_type.value if hasattr(source_type, "value") else str(source_type).lower()
    temp_source = MetadataSource(
        name=payload.name,
        type=type_str,
        base_url=payload.base_url or ("https://api.radarr.video/v1" if type_str == "radarr" else ("https://api4.thetvdb.com/v4" if type_str == "thetvdb" else ("https://api.themoviedb.org/3" if type_str == "tmdb" else "https://api.tvmaze.com"))),
        api_key=payload.api_key,
        field_mapping=payload.field_mapping or {},
    )
    client = get_metadata_client(temp_source)
    try:
        if type_str == "thetvdb":
            import httpx
            async with httpx.AsyncClient(timeout=15) as http_c:
                await client._get_token(http_c)
        elif type_str == "tmdb":
            res = await client.search("Inception")
            if not res and not payload.api_key:
                raise ValueError("Не указан TMDB API Key")
        elif type_str == "radarr":
            await client.search("Inception")
        else:
            await client.search("test")
        return {"success": True, "message": "Подключение успешно установлено"}
    except Exception as e:
        logger.warning(f"Ошибка проверки источника метаданных {type_str}: {e}")
        return {"success": False, "message": f"Ошибка подключения к {payload.name or type_str}: {e}"}


@router.delete("/{source_id}", status_code=204)
def delete_source(
    source_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_settings")),
):
    source = db.get(MetadataSource, source_id)
    if not source:
        raise HTTPException(404, "Source not found")
    db.delete(source)
    db.commit()


@router.get("/search", response_model=list[MetadataSearchResultOut])
async def search_all_metadata_sources(
    query: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_library")),
):
    """
    Универсальный поиск по всем источникам метаданных «из коробки»:
    1. Первоочередный параллельный поиск по официальным hook'ам:
       - Radarr Movie Cloud (api.radarr.video) — для фильмов;
       - Sonarr SkyHook (skyhook.sonarr.tv) — для сериалов и аниме.
    2. Параллельный поиск по всем остальным включенным источникам в БД (TMDB, TheTVDB, TVMaze, Shikimori).
    3. Объединение, фильтрация дубликатов и выдача общего результирующего списка для выбора и добавления карточки.
    """
    clean_query = query.strip()
    if not clean_query:
        return []

    combined_results: list[MetadataSearchResultOut] = []
    seen_ids: set[str] = set()
    seen_keys: set[tuple[str, str, int | None]] = set()

    # 1. ПЕРВАЯ ОЧЕРЕДЬ: Radarr Cloud Hook (фильмы) + Sonarr SkyHook (сериалы/аниме)
    primary_tasks = [
        ("radarr", RadarrClient().search(clean_query)),
        ("skyhook", SkyHookClient().search(clean_query)),
    ]
    try:
        primary_responses = await asyncio.gather(*[t[1] for t in primary_tasks], return_exceptions=True)
    except Exception as e:
        logger.warning("Primary metadata hooks search gather error: %s", e)
        primary_responses = []

    for (source_type_str, _), resp in zip(primary_tasks, primary_responses):
        if isinstance(resp, list):
            for r in resp:
                uid = f"{r.external_id}"
                c_type = r.content_type or ("movie" if uid.startswith("movie:") or uid.startswith("radarr:") else "series")
                title_norm = (r.title or "").strip().lower()
                key = (c_type, title_norm, r.year)

                if uid in seen_ids or (title_norm and key in seen_keys):
                    continue
                seen_ids.add(uid)
                if title_norm:
                    seen_keys.add(key)

                existing = _find_existing_show(
                    db,
                    metadata_source=source_type_str,
                    metadata_id=r.external_id,
                    title=r.title,
                    year=r.year,
                    content_type=c_type,
                )
                combined_results.append(
                    MetadataSearchResultOut(
                        **r.__dict__,
                        already_added=existing is not None,
                        existing_show_id=existing.id if existing else None,
                    )
                )

    # 2. ВТОРАЯ ОЧЕРЕДЬ: Остальные настроенные и активные источники в БД
    db_sources = (
        db.query(MetadataSource)
        .filter(MetadataSource.enabled == True)
        .all()
    )
    secondary_sources = [
        s for s in db_sources
        if (s.type.value if hasattr(s.type, "value") else str(s.type)) not in ("skyhook", "radarr", "radarr_skyhook")
    ]

    if secondary_sources:
        sec_tasks = []
        for s in secondary_sources:
            try:
                client = get_metadata_client(s)
                sec_tasks.append((s, client.search(clean_query)))
            except Exception as e:
                logger.debug("Failed creating metadata client for source %s: %s", s.name, e)

        if sec_tasks:
            try:
                sec_responses = await asyncio.gather(*[t[1] for t in sec_tasks], return_exceptions=True)
            except Exception as e:
                logger.warning("Secondary metadata sources search gather error: %s", e)
                sec_responses = []

            for (source_row, _), resp in zip(sec_tasks, sec_responses):
                if isinstance(resp, list):
                    source_type_str = source_row.type.value if hasattr(source_row.type, "value") else str(source_row.type)
                    for r in resp:
                        uid = f"{r.external_id}"
                        c_type = r.content_type or ("movie" if uid.startswith("movie:") else "series")
                        title_norm = (r.title or "").strip().lower()
                        key = (c_type, title_norm, r.year)

                        if uid in seen_ids or (title_norm and key in seen_keys):
                            continue
                        seen_ids.add(uid)
                        if title_norm:
                            seen_keys.add(key)

                        existing = _find_existing_show(
                            db,
                            metadata_source=source_type_str,
                            metadata_id=r.external_id,
                            title=r.title,
                            year=r.year,
                            content_type=c_type,
                        )
                        combined_results.append(
                            MetadataSearchResultOut(
                                **r.__dict__,
                                already_added=existing is not None,
                                existing_show_id=existing.id if existing else None,
                            )
                        )

    return combined_results


@router.get("/{source_id}/search", response_model=list[MetadataSearchResultOut])
async def search_metadata(
    source_id: int,
    query: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_library")),
):
    source = db.get(MetadataSource, source_id)
    if not source:
        raise HTTPException(404, "Source not found")
    client = get_metadata_client(source)
    results: list[MetadataResult] = await client.search(query)

    source_type_str = source.type.value if hasattr(source.type, "value") else str(source.type)
    out = []
    for r in results:
        existing = _find_existing_show(
            db,
            metadata_source=source_type_str,
            metadata_id=r.external_id,
            title=r.title,
            year=r.year,
            content_type=r.content_type,
        )
        out.append(MetadataSearchResultOut(
            **r.__dict__,
            already_added=existing is not None,
            existing_show_id=existing.id if existing else None,
        ))
    return out


@router.post("/import", status_code=201)
async def import_show(
    payload: ImportShowRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_library")),
):
    """Создаёт шоу из результата метаданных, автонаполняя алиасы из AKA-списка источника."""
    try:
        ext_str = str(payload.external_id)
        source = None

        if ext_str.startswith("tvdb:") or ext_str.startswith("skyhook:"):
            source = db.query(MetadataSource).filter(MetadataSource.type.in_([MetadataSourceType.SKYHOOK, MetadataSourceType.THETVDB]), MetadataSource.enabled == True).first()
            if not source:
                source = MetadataSource(name="SkyHook (Sonarr)", type="skyhook", base_url="https://skyhook.sonarr.tv/v1/tvdb", enabled=True)
        elif ext_str.startswith("movie:") or ext_str.startswith("radarr:"):
            source = db.query(MetadataSource).filter(MetadataSource.type.in_([MetadataSourceType.RADARR, MetadataSourceType.SKYHOOK, MetadataSourceType.TMDB]), MetadataSource.enabled == True).first()
            if not source:
                source = MetadataSource(name="Radarr SkyHook (Movie Cloud)", type="radarr", base_url="https://api.radarr.video/v1", enabled=True)
        elif ext_str.startswith("tv:"):
            source = db.query(MetadataSource).filter(MetadataSource.type == MetadataSourceType.TMDB, MetadataSource.enabled == True).first()
        elif ext_str.startswith("tvmaze:"):
            source = db.query(MetadataSource).filter(MetadataSource.type == MetadataSourceType.TVMAZE, MetadataSource.enabled == True).first()
        elif ext_str.startswith("shiki:"):
            source = db.query(MetadataSource).filter(MetadataSource.type == MetadataSourceType.SHIKIMORI, MetadataSource.enabled == True).first()
        elif ext_str.startswith("anilist:"):
            source = db.query(MetadataSource).filter(MetadataSource.type == MetadataSourceType.ANILIST, MetadataSource.enabled == True).first()

        if not source and payload.source_id:
            source = db.get(MetadataSource, payload.source_id)

        if not source:
            if payload.content_type == "movie" or ext_str.startswith("movie:") or ext_str.startswith("radarr:"):
                source = MetadataSource(name="Radarr SkyHook (Movie Cloud)", type="radarr", base_url="https://api.radarr.video/v1", enabled=True)
            else:
                source = MetadataSource(name="SkyHook (Sonarr)", type="skyhook", base_url="https://skyhook.sonarr.tv/v1/tvdb", enabled=True)

        try:
            client = get_metadata_client(source)
            details = await client.get_details(payload.external_id)
        except Exception as exc:
            logger.warning("Ошибка получения деталей через %s (%s): %s. Пробуем fallback...", getattr(source, 'name', 'unknown'), payload.external_id, exc)
            if ext_str.startswith("movie:") or ext_str.startswith("radarr:") or payload.content_type == "movie":
                fallback_source = MetadataSource(name="Radarr SkyHook (Movie Cloud)", type="radarr", base_url="https://api.radarr.video/v1", enabled=True)
            else:
                fallback_source = MetadataSource(name="SkyHook (Sonarr)", type="skyhook", base_url="https://skyhook.sonarr.tv/v1/tvdb", enabled=True)
            client = get_metadata_client(fallback_source)
            details = await client.get_details(payload.external_id)

        # Гарантия наличия названия и метаданных для фильмов
        if (not details or not details.title or not details.title.strip()) and (ext_str.startswith("movie:") or payload.content_type == "movie"):
            clean_id = ext_str.replace("movie:", "").replace("tmdb:", "").strip()
            from app.services.metadata import TMDBClient, RadarrClient
            try:
                tmdb = TMDBClient(api_key=RadarrClient.RADARR_TMDB_TOKEN)
                details = await tmdb._get_movie_details(clean_id)
            except Exception as e:
                logger.warning("TMDb emergency details fetch failed: %s", e)

        content_type = payload.content_type or details.content_type or "series"
        if content_type not in ("movie", "series", "anime"):
            raise HTTPException(400, "content_type должен быть movie, series или anime")

        premiere_dt = _parse_date(details.premiere_date)
        show_year = premiere_dt.year if premiere_dt else None

        source_type_str = source.type.value if hasattr(source.type, "value") else str(source.type)
        existing = _find_existing_show(
            db,
            metadata_source=source_type_str,
            metadata_id=details.external_id,
            title=details.title,
            year=show_year,
            content_type=content_type,
            imdb_id=details.imdb_id,
            tmdb_id=details.tmdb_id,
            tvdb_id=details.tvdb_id,
        )
        if existing:
            raise HTTPException(
                409,
                f"Шоу «{existing.title}» уже добавлено в библиотеку (id={existing.id})",
            )

        from app.services.settings_service import get_or_create_settings
        from app.services.postprocess import get_show_default_path, sanitize_filename
        import os as _os
        import re as _re

        settings = get_or_create_settings(db)
        title_no_year = _re.sub(r"\s*\(\d{4}\)$|\s+\d{4}$", "", details.title or "").strip()
        if payload.path:
            p = payload.path.strip().rstrip("/\\")
            base_p = _os.path.basename(p).lower()
            if base_p in ("test", "movies", "films", "downloads", "data", "media", "video") or not base_p:
                subfolder = sanitize_filename(f"{title_no_year} ({show_year})" if show_year else details.title)
                final_path = _os.path.join(p, subfolder)
            else:
                final_path = payload.path.strip()
        else:
            final_path = get_show_default_path(
                Show(title=details.title, year=show_year, content_type=content_type),
                settings,
            )

        # Movie Collection auto-link/creation on import
        coll_tmdb_id = getattr(details, "collection_tmdb_id", None)
        coll_name = getattr(details, "collection_name", None)
        coll_id_to_set = None
        if content_type == "movie" and (coll_tmdb_id or coll_name):
            try:
                from app.models.db import MovieCollection
                coll = None
                if coll_tmdb_id:
                    coll = db.query(MovieCollection).filter(MovieCollection.tmdb_collection_id == coll_tmdb_id).first()
                if not coll and coll_name:
                    coll = db.query(MovieCollection).filter(MovieCollection.title == coll_name).first()
                if not coll and coll_name:
                    coll = MovieCollection(
                        tmdb_collection_id=coll_tmdb_id,
                        title=coll_name,
                        overview=getattr(details, "collection_overview", None),
                        poster_url=getattr(details, "collection_poster_url", None),
                        backdrop_url=getattr(details, "collection_backdrop_url", None),
                    )
                    db.add(coll)
                    db.flush()
                if coll:
                    coll_id_to_set = coll.id
                    if coll.tmdb_collection_id and hasattr(client, "get_collection_details"):
                        if not getattr(coll, "parts_cache", None) or coll.parts_count is None:
                            try:
                                c_det = await client.get_collection_details(coll.tmdb_collection_id)
                                if c_det and c_det.get("parts"):
                                    import json
                                    coll.parts_count = len(c_det["parts"])
                                    coll.parts_cache = json.dumps(c_det["parts"])
                                    coll.last_metadata_refresh_at = dt.datetime.utcnow()
                                    if not coll.overview and c_det.get("overview"):
                                        coll.overview = c_det.get("overview")
                                    if not coll.poster_url and c_det.get("poster_url"):
                                        coll.poster_url = c_det.get("poster_url")
                                    if not coll.backdrop_url and c_det.get("backdrop_url"):
                                        coll.backdrop_url = c_det.get("backdrop_url")
                                    db.add(coll)
                            except Exception as e:
                                logger.debug("Failed fetching collection details for %s: %s", coll.title, e)
            except Exception as e:
                logger.warning("Failed linking movie to collection during import: %s", e)

        # Назначаем профиль качества по умолчанию в зависимости от категории медиатеки
        target_qp_id = None
        if content_type == "movie":
            target_qp_id = getattr(settings, "default_quality_profile_movie_id", None)
        elif content_type == "anime":
            target_qp_id = getattr(settings, "default_quality_profile_anime_id", None)
        else:
            target_qp_id = getattr(settings, "default_quality_profile_series_id", None)

        show = Show(
            title=details.title,
            year=show_year,
            collection_id=coll_id_to_set,
            quality_profile_id=target_qp_id,
            metadata_source=source_type_str,
            metadata_id=details.external_id,
            overview=details.overview,
            poster_url=details.poster_url,
            path=final_path,
            rating=details.rating,
            country=details.country,
            genre=details.genre,
            network=details.network,
            content_type=content_type,
            premiere_date=premiere_dt,
            imdb_id=details.imdb_id,
            tmdb_id=details.tmdb_id,
            tvdb_id=details.tvdb_id,
            tvmaze_id=details.tvmaze_id,
            mal_id=details.mal_id,
            anilist_id=details.anilist_id,
            anidb_id=details.anidb_id,
            shikimori_id=details.shikimori_id,
            trailer_url=details.trailer_url,
        )
        db.add(show)
        db.flush()

        added_aliases = set()
        clean_title = (details.title or "").strip()
        if clean_title:
            db.add(Alias(show_id=show.id, text=clean_title, language="en", source=source_type_str, priority=1))
            added_aliases.add(clean_title.lower())
            if title_no_year and title_no_year.lower() not in added_aliases:
                added_aliases.add(title_no_year.lower())
                db.add(Alias(show_id=show.id, text=title_no_year, language="en", source=source_type_str, priority=1))

        for i, alias_text in enumerate(details.aliases):
            if alias_text and alias_text.strip() and alias_text.strip().lower() not in added_aliases:
                clean_alias = alias_text.strip()
                added_aliases.add(clean_alias.lower())
                is_cyrillic = any('\u0400' <= c <= '\u04ff' for c in clean_alias)
                lang = "ru" if is_cyrillic else "other"
                db.add(Alias(show_id=show.id, text=clean_alias, language=lang, source=source_type_str, priority=2 + i))


        now = dt.datetime.utcnow()
        episodes_imported = 0

        if content_type == "movie" or not details.episodes:
            # Для фильма создаём одну запись Episode, чтобы обеспечить мониторинг и автопоиск
            premiere = show.premiere_date
            already_released = bool(premiere and premiere <= now)
            status = EpisodeStatus.UNAIRED if (premiere and premiere > now) else EpisodeStatus.WANTED
            db.add(Episode(
                show_id=show.id, season_number=1, episode_number=1,
                title=details.title,
                # Если фильм уже вышел, дата выхода в календаре не фиксируется как будущее событие
                air_date=None if already_released else premiere,
                status=status,
            ))
            episodes_imported = 1
        else:
            seen_episodes = set()
            for ep in details.episodes:
                if ep.episode_number is None:
                    continue
                try:
                    s_num = int(ep.season_number) if ep.season_number is not None else 1
                    e_num = int(ep.episode_number)
                except (ValueError, TypeError):
                    continue
                if e_num <= 0 and s_num > 0:
                    continue
                
                ep_key = (s_num, e_num)
                if ep_key in seen_episodes:
                    continue
                seen_episodes.add(ep_key)

                air_date = _parse_date(ep.air_date)
                status = EpisodeStatus.UNAIRED if (air_date and air_date > now) else EpisodeStatus.WANTED
                db.add(Episode(
                    show_id=show.id,
                    season_number=s_num,
                    episode_number=e_num,
                    absolute_number=ep.absolute_number,
                    title=ep.title or f"Episode {e_num}",
                    air_date=air_date,
                    status=status,
                ))
                episodes_imported += 1

            if episodes_imported == 0:
                premiere = show.premiere_date
                already_released = bool(premiere and premiere <= now)
                status = EpisodeStatus.UNAIRED if (premiere and premiere > now) else EpisodeStatus.WANTED
                db.add(Episode(
                    show_id=show.id, season_number=1, episode_number=1,
                    title=details.title,
                    air_date=None if already_released else premiere,
                    status=status,
                ))
                episodes_imported = 1

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

        return {
            "show_id": show.id, "title": show.title,
            "aliases_imported": len(details.aliases), "episodes_imported": episodes_imported,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Ошибка при импорте шоу (external_id={payload.external_id}): {e}", exc_info=True)
        raise HTTPException(500, f"Внутренняя ошибка при импорте: {e}")


@router.get("/image-proxy")
async def proxy_image(url: str):
    """Проксирует и кэширует изображения постеров (TheTVDB artworks, TMDB, TVMaze) для обхода ограничений CORS / Referrer."""
    if not url or not url.startswith(("http://", "https://")):
        raise HTTPException(400, "Invalid image URL")

    allowed_domains = ("thetvdb.com", "tmdb.org", "tvmaze.com", "sonarr.tv", "servarr.com", "fanart.tv", "themoviedb.org")
    if not any(d in url.lower() for d in allowed_domains):
        raise HTTPException(403, "Domain not allowed for proxy")

    try:
        import httpx
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(url, headers={"User-Agent": "Aliasarr/1.0.0"})
            if resp.status_code == 200:
                media_type = resp.headers.get("content-type", "image/jpeg")
                return Response(
                    content=resp.content,
                    media_type=media_type,
                    headers={"Cache-Control": "public, max-age=86400, immutable"},
                )
    except Exception as e:
        logger.warning(f"Failed to proxy image {url}: {e}")

    raise HTTPException(502, "Failed to fetch remote image")
