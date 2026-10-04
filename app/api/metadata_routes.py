from __future__ import annotations

from typing import Optional, List, Dict, Any

import asyncio
import datetime as dt
from urllib.parse import urljoin, urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.db import Alias, AppSettings, Episode, EpisodeStatus, MetadataSource, MetadataSourceType, Show, User
from app.services.metadata import (
    MetadataResult,
    RadarrClient,
    SkyHookClient,
    TMDBClient,
    get_metadata_client,
    get_allowed_metadata_languages,
    is_alias_allowed,
    detect_alias_language,
    extract_imdb_id,
    normalize_metadata_lang_code,
    search_by_imdb_id,
)
from app.services.user_service import require_permission, get_current_user
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/metadata-sources", tags=["metadata"])

IMAGE_PROXY_MAX_BYTES = 10 * 1024 * 1024
IMAGE_PROXY_MAX_REDIRECTS = 3
IMAGE_PROXY_ALLOWED_DOMAINS = (
    "thetvdb.com",
    "tmdb.org",
    "tvmaze.com",
    "sonarr.tv",
    "servarr.com",
    "fanart.tv",
    "themoviedb.org",
)


def _validate_proxy_image_url(url: str) -> str:
    try:
        parsed = urlsplit((url or "").strip())
        port = parsed.port
    except ValueError as exc:
        raise HTTPException(400, "Invalid image URL") from exc

    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise HTTPException(400, "Invalid image URL")
    if parsed.username is not None or parsed.password is not None:
        raise HTTPException(403, "URL credentials are not allowed")
    if port not in (None, 80, 443):
        raise HTTPException(403, "Image proxy port is not allowed")

    hostname = parsed.hostname.rstrip(".").lower()
    if not any(
        hostname == domain or hostname.endswith(f".{domain}")
        for domain in IMAGE_PROXY_ALLOWED_DOMAINS
    ):
        raise HTTPException(403, "Domain not allowed for proxy")
    return parsed.geturl()


async def _read_limited_image_response(response, max_bytes: int = IMAGE_PROXY_MAX_BYTES) -> bytes:
    content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if not content_type.startswith("image/"):
        raise HTTPException(415, "Remote response is not an image")

    content_length = response.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > max_bytes:
                raise HTTPException(413, "Remote image is too large")
        except ValueError:
            pass

    chunks: list[bytes] = []
    total = 0
    async for chunk in response.aiter_bytes():
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(413, "Remote image is too large")
        chunks.append(chunk)
    return b"".join(chunks)


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
    original_title: Optional[str] = None
    titles_by_lang: dict[str, str] = {}


class MetadataDetailsOut(BaseModel):
    external_id: str
    title: str
    original_title: Optional[str] = None
    titles_by_lang: dict[str, str] = {}
    year: Optional[int] = None
    overview: Optional[str] = None
    poster_url: Optional[str] = None
    rating: Optional[float] = None
    country: Optional[str] = None
    genre: Optional[str] = None
    content_type: Optional[str] = None
    network: Optional[str] = None
    premiere_date: Optional[str] = None
    aliases: list[str] = []


class ImportShowRequest(BaseModel):
    source_id: Optional[int] = None
    external_id: str
    path: Optional[str] = None
    # Категория контента (movie | series | anime), выбранная пользователем при добавлении
    content_type: Optional[str] = None
    # Локализованное название, выбранное пользователем (RU / EN / Original)
    title: Optional[str] = None


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


async def _imdb_search_results(db: Session, imdb_id: str, overview_lang: str, title_lang: str) -> list[MetadataSearchResultOut]:
    found = await search_by_imdb_id(imdb_id, overview_language=overview_lang, title_language=title_lang)
    results: list[MetadataSearchResultOut] = []
    for r in found:
        ext = str(r.external_id)
        source_type = "radarr" if ext.startswith("movie:") else ("skyhook" if ext.startswith("tvdb:") else "tmdb")
        existing = _find_existing_show(
            db,
            metadata_source=source_type,
            metadata_id=r.external_id,
            title=r.title,
            year=r.year,
            content_type=r.content_type,
            imdb_id=imdb_id,
        )
        results.append(MetadataSearchResultOut(
            **r.__dict__,
            already_added=existing is not None,
            existing_show_id=existing.id if existing else None,
        ))
    return results


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

    app_settings = db.query(AppSettings).filter(AppSettings.id == 1).first()
    overview_lang = getattr(app_settings, "metadata_overview_language", "ru") or "ru"
    title_lang = getattr(app_settings, "metadata_title_language", "ru") or "ru"

    # IMDb ID или ссылка на IMDb: текстовый поиск по такой строке бесполезен,
    # тайтл находится напрямую по внешнему ID.
    imdb_id = extract_imdb_id(clean_query)
    if imdb_id:
        return await _imdb_search_results(db, imdb_id, overview_lang, title_lang)

    # 1. ПЕРВАЯ ОЧЕРЕДЬ: Radarr Cloud Hook (фильмы) + Sonarr SkyHook (сериалы/аниме)
    primary_tasks = [
        ("radarr", RadarrClient(overview_language=overview_lang, title_language=title_lang).search(clean_query)),
        ("skyhook", SkyHookClient(overview_language=overview_lang, title_language=title_lang).search(clean_query)),
    ]
    try:
        primary_responses = await asyncio.gather(*[t[1] for t in primary_tasks], return_exceptions=True)
    except Exception as e:
        logger.warning("Primary metadata hooks search gather error: %s", e)
        primary_responses = []

    for (source_type_str, _), resp in zip(primary_tasks, primary_responses):
        if isinstance(resp, Exception):
            logger.warning("Primary metadata hook %s search error: %s", source_type_str, resp)
            continue
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
                client = get_metadata_client(s, overview_language=overview_lang, title_language=title_lang)
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

    # 3. СТРАХОВОЧНЫЙ МЕХАНИЗМ: если найдены только фильмы, а сериалов/аниме 0
    # (например, при крайне медленном соединении, сетевом сбое или таймауте внешних шлюзов SkyHook),
    # опрашиваем TMDb TV fallback, чтобы на экране поиска карточки фильмов и сериалов всегда отображались вместе
    has_series = any(item.content_type in ("series", "anime") for item in combined_results)
    if not has_series:
        try:
            tmdb_fallback = TMDBClient(api_key=RadarrClient.RADARR_TMDB_TOKEN)
            tv_results = await tmdb_fallback.search(clean_query)
            for r in tv_results:
                if r.content_type not in ("series", "anime"):
                    continue
                uid = f"{r.external_id}"
                c_type = r.content_type or "series"
                title_norm = (r.title or "").strip().lower()
                key = (c_type, title_norm, r.year)

                if uid in seen_ids or (title_norm and key in seen_keys):
                    continue
                seen_ids.add(uid)
                if title_norm:
                    seen_keys.add(key)

                existing = _find_existing_show(
                    db,
                    metadata_source="tmdb",
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
        except Exception as e:
            logger.debug("Emergency TMDb TV search fallback error in search_all: %s", e)

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
    app_settings = db.query(AppSettings).filter(AppSettings.id == 1).first()
    overview_lang = getattr(app_settings, "metadata_overview_language", "ru") or "ru"
    title_lang = getattr(app_settings, "metadata_title_language", "ru") or "ru"
    imdb_id = extract_imdb_id(query)
    if imdb_id:
        # Источник в выпадающем списке не важен: по IMDb ID тайтл находится однозначно.
        return await _imdb_search_results(db, imdb_id, overview_lang, title_lang)
    client = get_metadata_client(source, overview_language=overview_lang, title_language=title_lang)
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
        elif ext_str.startswith("movie:") or ext_str.startswith("radarr:") or payload.content_type == "movie":
            source = db.query(MetadataSource).filter(MetadataSource.type.in_([MetadataSourceType.RADARR, MetadataSourceType.TMDB]), MetadataSource.enabled == True).first()
            if not source:
                source = MetadataSource(name="Radarr SkyHook (Movie Cloud)", type="radarr", base_url="https://api.radarr.video/v1", enabled=True)
        elif ext_str.startswith("tv:") or (ext_str.startswith("tmdb:") and payload.content_type in ("series", "anime")):
            source = db.query(MetadataSource).filter(MetadataSource.type == MetadataSourceType.TMDB, MetadataSource.enabled == True).first()
            if not source:
                source = MetadataSource(name="TMDB", type="tmdb", base_url="https://api.themoviedb.org/3", api_key=RadarrClient.RADARR_TMDB_TOKEN, enabled=True)
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

        app_settings = db.query(AppSettings).filter(AppSettings.id == 1).first()
        overview_lang = getattr(app_settings, "metadata_overview_language", "ru") or "ru"

        try:
            client = get_metadata_client(source, overview_language=overview_lang)
            details = await client.get_details(payload.external_id)
        except Exception as exc:
            logger.warning("Ошибка получения деталей через %s (%s): %s. Пробуем fallback...", getattr(source, 'name', 'unknown'), payload.external_id, exc)
            if ext_str.startswith("movie:") or ext_str.startswith("radarr:") or payload.content_type == "movie":
                fallback_source = MetadataSource(name="Radarr SkyHook (Movie Cloud)", type="radarr", base_url="https://api.radarr.video/v1", enabled=True)
            else:
                fallback_source = MetadataSource(name="SkyHook (Sonarr)", type="skyhook", base_url="https://skyhook.sonarr.tv/v1/tvdb", enabled=True)
            client = get_metadata_client(fallback_source, overview_language=overview_lang)
            details = await client.get_details(payload.external_id)

        # Гарантия наличия названия и метаданных для фильмов
        if (not details or not details.title or not details.title.strip()) and (ext_str.startswith("movie:") or payload.content_type == "movie"):
            clean_id = ext_str.replace("movie:", "").replace("tmdb:", "").strip()
            try:
                tmdb = TMDBClient(api_key=RadarrClient.RADARR_TMDB_TOKEN, overview_language=overview_lang)
                details = await tmdb._get_movie_details(clean_id)
            except Exception as e:
                logger.warning("TMDb emergency details fetch failed: %s", e)

        # Гарантия наличия названия и метаданных для сериалов и аниме
        if (not details or not details.title or not details.title.strip()) and (ext_str.startswith("tv:") or payload.content_type in ("series", "anime")):
            clean_id = ext_str.replace("tv:", "").replace("tmdb:", "").strip()
            if clean_id.isdigit():
                try:
                    tmdb = TMDBClient(api_key=RadarrClient.RADARR_TMDB_TOKEN, overview_language=overview_lang)
                    details = await tmdb._get_tv_details(clean_id)
                except Exception as e:
                    logger.warning("TMDb emergency TV details fetch failed: %s", e)

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
        # Определение основного названия тайтла
        chosen_title = payload.title.strip() if (payload.title and payload.title.strip()) else None
        if not chosen_title:
            title_lang = getattr(app_settings, "metadata_title_language", "ru") or "ru"
            norm_t = normalize_metadata_lang_code(title_lang) or title_lang
            titles_map = getattr(details, "titles_by_lang", {}) or {}
            if norm_t in ("ru", "rus") and titles_map.get("ru"):
                chosen_title = titles_map["ru"]
            elif norm_t in ("en", "eng") and titles_map.get("en"):
                chosen_title = titles_map["en"]
            elif norm_t == "original" and titles_map.get("original"):
                chosen_title = titles_map["original"]
            else:
                chosen_title = details.title

        title_no_year = _re.sub(r"\s*\(\d{4}\)$|\s+\d{4}$", "", chosen_title or "").strip()
        if payload.path:
            p = payload.path.strip().rstrip("/\\")
            base_p = _os.path.basename(p).lower()
            if base_p in ("test", "movies", "films", "downloads", "data", "media", "video") or not base_p:
                subfolder = sanitize_filename(f"{title_no_year} ({show_year})" if show_year else chosen_title)
                final_path = _os.path.join(p, subfolder)
            else:
                final_path = payload.path.strip()
        else:
            final_path = get_show_default_path(
                Show(title=chosen_title, year=show_year, content_type=content_type),
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
                                c_lang = getattr(settings, "metadata_collection_title_language", "ru") if settings else "ru"
                                c_lang = (c_lang or "ru").strip().lower()
                                c_det = await client.get_collection_details(coll.tmdb_collection_id, lang=c_lang)
                                if c_det and c_det.get("parts"):
                                    import json
                                    coll.parts_count = len(c_det["parts"])
                                    coll.parts_cache = json.dumps(c_det["parts"], ensure_ascii=False)
                                    coll.last_metadata_refresh_at = dt.datetime.utcnow()
                                    if c_det.get("overview"):
                                        coll.overview = c_det.get("overview")
                                    tbl = c_det.get("titles_by_lang") or {}
                                    if tbl:
                                        coll.titles_cache = json.dumps(tbl, ensure_ascii=False)
                                    pref_title = None
                                    if c_lang in ("ru", "rus"):
                                        pref_title = tbl.get("ru") or (c_det.get("name") if any('\u0400' <= ch <= '\u04ff' for ch in (c_det.get("name") or "")) else None)
                                    elif c_lang in ("en", "eng"):
                                        pref_title = tbl.get("en")
                                    else:
                                        pref_title = tbl.get(c_lang)
                                    if pref_title and pref_title.strip():
                                        coll.title = pref_title.strip()
                                    elif c_det.get("name") and not coll.title:
                                        coll.title = c_det.get("name").strip()
                                    if c_det.get("poster_url") and not coll.poster_url:
                                        coll.poster_source_url = c_det.get("poster_url")
                                        from app.services.cover_service import download_and_store_collection_cover
                                        c_loc = await download_and_store_collection_cover(coll.id, c_det.get("poster_url"))
                                        coll.poster_url = c_loc or c_det.get("poster_url")
                                    if c_det.get("backdrop_url") and not coll.backdrop_url:
                                        coll.backdrop_source_url = c_det.get("backdrop_url")
                                        from app.services.cover_service import download_and_store_collection_backdrop
                                        b_loc = await download_and_store_collection_backdrop(coll.id, c_det.get("backdrop_url"))
                                        coll.backdrop_url = b_loc or c_det.get("backdrop_url")
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
            title=chosen_title,
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
        chosen_clean = (chosen_title or "").strip()

        # 1. Выбранное пользователем название (приоритет 1)
        if chosen_clean:
            ch_lang = detect_alias_language(chosen_clean)
            db.add(Alias(show_id=show.id, text=chosen_clean, language=ch_lang, source=source_type_str, priority=1))
            added_aliases.add(chosen_clean.lower())
            if title_no_year and title_no_year.lower() not in added_aliases:
                added_aliases.add(title_no_year.lower())
                db.add(Alias(show_id=show.id, text=title_no_year, language=ch_lang, source=source_type_str, priority=1))

        # 2. Исходное каноническое название details.title (приоритет 2)
        if clean_title and clean_title.lower() not in added_aliases:
            c_lang = detect_alias_language(clean_title)
            db.add(Alias(show_id=show.id, text=clean_title, language=c_lang, source=source_type_str, priority=2))
            added_aliases.add(clean_title.lower())

        # 3. Все альтернативные языковые версии из titles_by_lang (приоритет 3)
        for l_code, t_val in (getattr(details, "titles_by_lang", {}) or {}).items():
            if t_val and t_val.strip() and t_val.strip().lower() not in added_aliases:
                t_str = t_val.strip()
                added_aliases.add(t_str.lower())
                det_l = detect_alias_language(t_str)
                db.add(Alias(show_id=show.id, text=t_str, language=det_l, source=source_type_str, priority=3))

        allowed_langs = get_allowed_metadata_languages(db, show)
        for i, alias_text in enumerate(details.aliases):
            clean_alias = str(alias_text).strip() if alias_text else ""
            if clean_alias and clean_alias.lower() not in added_aliases:
                if not is_alias_allowed(clean_alias, None, allowed_langs):
                    continue
                added_aliases.add(clean_alias.lower())
                lang = detect_alias_language(clean_alias)
                db.add(Alias(show_id=show.id, text=clean_alias, language=lang, source=source_type_str, priority=4 + i))


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
            future_seasons = set()
            for ep in details.episodes:
                mad = _parse_date(ep.air_date)
                try:
                    s_n = int(ep.season_number) if ep.season_number is not None else 1
                except (ValueError, TypeError):
                    s_n = 1
                if mad and mad > now:
                    future_seasons.add(s_n)

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
                is_unaired = bool(
                    (air_date and air_date > now)
                    or (air_date is None and (s_num in future_seasons or (show.premiere_date and show.premiere_date > now)))
                )
                status = EpisodeStatus.UNAIRED if is_unaired else EpisodeStatus.WANTED
                monitored = True
                db.add(Episode(
                    show_id=show.id,
                    season_number=s_num,
                    episode_number=e_num,
                    absolute_number=ep.absolute_number,
                    title=ep.title or f"Episode {e_num}",
                    air_date=air_date,
                    status=status,
                    monitored=monitored,
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

        return {
            "show_id": show.id, "title": show.title,
            "aliases_imported": len(details.aliases), "episodes_imported": episodes_imported,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Ошибка при импорте шоу (external_id={payload.external_id}): {e}", exc_info=True)
        raise HTTPException(500, f"Внутренняя ошибка при импорте: {e}")


@router.get("/details", response_model=MetadataDetailsOut)
async def get_metadata_details(
    external_id: str,
    content_type: Optional[str] = None,
    source_id: Optional[int] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_library")),
):
    """Получение детальных локализованных метаданных тайтла для предпросмотра на шаге настройки."""
    ext_str = str(external_id).strip()
    source = None
    if ext_str.startswith("tvdb:") or ext_str.startswith("skyhook:"):
        source = db.query(MetadataSource).filter(MetadataSource.type.in_([MetadataSourceType.SKYHOOK, MetadataSourceType.THETVDB]), MetadataSource.enabled == True).first()
    elif ext_str.startswith("movie:") or ext_str.startswith("radarr:") or content_type == "movie":
        source = db.query(MetadataSource).filter(MetadataSource.type.in_([MetadataSourceType.RADARR, MetadataSourceType.TMDB]), MetadataSource.enabled == True).first()
    elif ext_str.startswith("tv:") or (ext_str.startswith("tmdb:") and content_type in ("series", "anime")):
        source = db.query(MetadataSource).filter(MetadataSource.type == MetadataSourceType.TMDB, MetadataSource.enabled == True).first()

    if not source and source_id:
        source = db.get(MetadataSource, source_id)

    if not source:
        if content_type == "movie" or ext_str.startswith("movie:") or ext_str.startswith("radarr:"):
            source = MetadataSource(name="Radarr SkyHook (Movie Cloud)", type="radarr", base_url="https://api.radarr.video/v1", enabled=True)
        else:
            source = MetadataSource(name="SkyHook (Sonarr)", type="skyhook", base_url="https://skyhook.sonarr.tv/v1/tvdb", enabled=True)

    app_settings = db.query(AppSettings).filter(AppSettings.id == 1).first()
    overview_lang = getattr(app_settings, "metadata_overview_language", "ru") or "ru"
    client = get_metadata_client(source, overview_language=overview_lang)
    details = await client.get_details(ext_str)

    titles_map = dict(getattr(details, "titles_by_lang", {}) or {})
    norm_ov = normalize_metadata_lang_code(overview_lang) or overview_lang
    display_title = details.title
    if norm_ov in ("ru", "rus") and titles_map.get("ru"):
        display_title = titles_map["ru"]
    elif norm_ov == "original" and titles_map.get("original"):
        display_title = titles_map["original"]

    return MetadataDetailsOut(
        external_id=details.external_id,
        title=display_title,
        original_title=getattr(details, "original_title", None),
        titles_by_lang=titles_map,
        year=details.year,
        overview=details.overview,
        poster_url=details.poster_url,
        rating=details.rating,
        country=details.country,
        genre=details.genre,
        content_type=details.content_type or content_type,
        network=details.network,
        premiere_date=details.premiere_date,
        aliases=details.aliases,
    )


# Совместимость для вызовов и тестов
get_source_details = get_metadata_details


@router.post("/cleanup-aliases")
async def cleanup_unallowed_aliases(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_settings")),
):
    """Очищает неактуальные/мусорные автосгенерированные алиасы во всей библиотеке согласно настройкам языков."""
    shows = db.query(Show).all()
    deleted_count = 0
    shows_affected = 0

    for show in shows:
        show_allowed_langs = get_allowed_metadata_languages(db, show)
        aliases = db.query(Alias).filter(Alias.show_id == show.id).all()
        show_deleted = 0
        for a in aliases:
            if a.source == "manual":
                continue
            if a.text.strip().lower() == (show.title or "").strip().lower():
                continue
            if not is_alias_allowed(a.text, a.language, show_allowed_langs):
                db.delete(a)
                deleted_count += 1
                show_deleted += 1
        if show_deleted > 0:
            shows_affected += 1

    db.commit()

    from app.services.audit_service import log_audit
    log_audit(
        db,
        action="metadata.cleanup_aliases",
        description=f"Очистка алиасов: удалено {deleted_count} неактуальных алиасов в {shows_affected} тайтлах",
        user=current_user,
        request=request,
    )

    return {
        "status": "ok",
        "deleted_count": deleted_count,
        "shows_affected": shows_affected,
        "message": f"Удалено {deleted_count} неактуальных алиасов в {shows_affected} тайтлах",
    }


@router.get("/image-proxy")
async def proxy_image(url: str):
    """Проксирует и кэширует изображения постеров (TheTVDB artworks, TMDB, TVMaze) для обхода ограничений CORS / Referrer."""
    current_url = _validate_proxy_image_url(url)

    try:
        import httpx
        async with httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
            for _ in range(IMAGE_PROXY_MAX_REDIRECTS + 1):
                current_url = _validate_proxy_image_url(current_url)
                async with client.stream(
                    "GET",
                    current_url,
                    headers={"User-Agent": "Aliasarr/1.0.0"},
                ) as resp:
                    if resp.status_code in (301, 302, 303, 307, 308):
                        location = resp.headers.get("location")
                        if not location:
                            break
                        current_url = urljoin(current_url, location)
                        continue
                    if resp.status_code == 200:
                        content = await _read_limited_image_response(resp)
                        media_type = resp.headers.get("content-type", "image/jpeg")
                        return Response(
                            content=content,
                            media_type=media_type,
                            headers={"Cache-Control": "public, max-age=86400, immutable"},
                        )
                    break
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"Failed to proxy image {url}: {e}")

    raise HTTPException(502, "Failed to fetch remote image")
