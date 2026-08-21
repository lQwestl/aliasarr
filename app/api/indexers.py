from __future__ import annotations

import asyncio
import datetime as dt
import logging
from typing import Any, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.db import DownloadClient, DownloadHistory, Episode, EpisodeStatus, Indexer, Show, User
from app.schemas import IndexerCreate, IndexerOut, SearchResultOut
from app.services.download_client import get_client
from app.services.indexer_service import get_indexer_client
from app.services.matcher import AliasCandidate, build_alias_candidates, match_release
from app.services.notifications import notify_all
from app.services.settings_service import get_or_create_settings
from app.services.torznab import TorznabClient
from app.services.user_service import require_permission, get_current_user

logger = logging.getLogger("aliasarr.indexers")

router = APIRouter(prefix="/api/v1/indexers", tags=["indexers"])


def _parse_release_age_and_date(pub_date_raw: Any) -> tuple[Optional[str], Optional[float]]:
    """Парсит дату публикации (RFC 2822, ISO, строки) и вычисляет возраст в днях (Sonarr ReleaseResource.Age)."""
    if not pub_date_raw:
        return None, None

    parsed_dt = None
    if isinstance(pub_date_raw, dt.datetime):
        parsed_dt = pub_date_raw.replace(tzinfo=None)
    elif isinstance(pub_date_raw, str):
        raw_str = pub_date_raw.strip()
        # 1. RFC 2822 (Torznab: "Wed, 19 Aug 2026 12:00:00 +0000")
        try:
            import email.utils
            p = email.utils.parsedate_to_datetime(raw_str)
            if p:
                parsed_dt = p.replace(tzinfo=None)
        except Exception:
            pass

        # 2. ISO 8601
        if not parsed_dt:
            try:
                clean_iso = raw_str.replace("Z", "+00:00").split("+")[0].strip()
                parsed_dt = dt.datetime.fromisoformat(clean_iso)
            except Exception:
                pass

        # 3. Custom date formats
        if not parsed_dt:
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d.%m.%Y %H:%M", "%d.%m.%Y"):
                try:
                    parsed_dt = dt.datetime.strptime(raw_str, fmt)
                    break
                except Exception:
                    pass

    if parsed_dt:
        delta = dt.datetime.utcnow() - parsed_dt
        age_days = max(0.0, round(delta.total_seconds() / 86400.0, 2))
        return parsed_dt.isoformat(), age_days

    return str(pub_date_raw), None


@router.get("", response_model=list[IndexerOut])
def list_indexers(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return db.query(Indexer).all()


@router.post("", response_model=IndexerOut, status_code=201)
def create_indexer(
    payload: IndexerCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_indexers")),
):
    indexer = Indexer(**payload.model_dump())
    db.add(indexer)
    db.commit()
    db.refresh(indexer)
    return indexer


@router.put("/{indexer_id}", response_model=IndexerOut)
def update_indexer(
    indexer_id: int,
    payload: IndexerCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_indexers")),
):
    indexer = db.get(Indexer, indexer_id)
    if not indexer:
        raise HTTPException(404, "Indexer not found")
    for field, value in payload.model_dump().items():
        setattr(indexer, field, value)
    db.add(indexer)
    db.commit()
    db.refresh(indexer)
    return indexer


@router.delete("/{indexer_id}", status_code=204)
def delete_indexer(
    indexer_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_indexers")),
):
    indexer = db.get(Indexer, indexer_id)
    if not indexer:
        raise HTTPException(404, "Indexer not found")
    db.delete(indexer)
    db.commit()


@router.post("/{indexer_id}/test")
async def test_indexer(
    indexer_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_indexers")),
):
    """Проверка связи: делает тестовый запрос к индексатору и возвращает результат."""
    indexer = db.get(Indexer, indexer_id)
    if not indexer:
        raise HTTPException(404, "Indexer not found")

    client = get_indexer_client(indexer)
    try:
        releases = await client.search("test")
        return {"success": True, "message": f"Индексатор ответил, найдено релизов: {len(releases)}"}
    except Exception as exc:
        return {"success": False, "message": f"Не удалось подключиться: {exc}"}


@router.post("/test")
async def test_indexer_adhoc(
    payload: IndexerCreate,
    current_user: User = Depends(require_permission("manage_indexers")),
):
    """Проверка связи до сохранения индексатора."""
    client = get_indexer_client(payload)
    try:
        releases = await client.search("test")
        return {"success": True, "message": f"Индексатор ответил, найдено релизов: {len(releases)}"}
    except Exception as exc:
        return {"success": False, "message": f"Не удалось подключиться: {exc}"}


async def _probe_indexer_once(indexer: Indexer) -> bool:
    client = get_indexer_client(indexer)
    try:
        await client.search("test")
        return True
    except Exception:
        return False


@router.post("/{indexer_id}/check")
async def check_indexer_availability(
    indexer_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_indexers")),
):
    """Проверка доступности индексатора с несколькими повторными попытками."""
    indexer = db.get(Indexer, indexer_id)
    if not indexer:
        raise HTTPException(404, "Indexer not found")

    settings = get_or_create_settings(db)
    attempts = max(1, settings.indexer_check_retries or 3)
    delay = max(0, settings.indexer_check_retry_delay_seconds or 5)

    ok = False
    for attempt in range(1, attempts + 1):
        ok = await _probe_indexer_once(indexer)
        if ok:
            break
        if attempt < attempts and delay > 0:
            await asyncio.sleep(delay)

    indexer.last_check_at = dt.datetime.utcnow()
    indexer.last_check_ok = ok
    if ok:
        indexer.consecutive_failures = 0
    else:
        indexer.consecutive_failures = (indexer.consecutive_failures or 0) + 1

    db.add(indexer)
    db.commit()
    db.refresh(indexer)

    if ok:
        logger.info("Проверка индексатора %s: доступен", indexer.name)
        return {"success": True, "message": "Индексатор доступен"}
    else:
        logger.warning(
            "Проверка индексатора %s: недоступен (попыток: %s, подряд сбоев: %s)",
            indexer.name, attempts, indexer.consecutive_failures,
        )
        return {
            "success": False,
            "message": f"Индексатор недоступен после {attempts} попыток (подряд сбоев: {indexer.consecutive_failures})",
        }


# ---------------------------------------------------------------------------
# Ручной и интерактивный поиск релизов
# ---------------------------------------------------------------------------


from app.services.decision_engine import DecisionEngine
from app.services.language_parser import get_language_badges


@router.get("/search-custom", response_model=list[SearchResultOut])
async def search_custom_releases(
    query: str,
    show_id: int | None = None,
    season: int | None = None,
    episode: int | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manual_search")),
):
    """Выполняет ручной расширенный поиск по произвольному пользовательскому запросу на всех индексаторах."""
    if not query or not query.strip():
        return []

    indexers = db.query(Indexer).filter(Indexer.enabled == True).all()  # noqa: E712
    if not indexers:
        raise HTTPException(400, "Нет ни одного включённого индексатора")

    settings = get_or_create_settings(db)
    show = db.get(Show, show_id) if show_id else None
    alias_candidates = build_alias_candidates(show) if show else []

    target_episodes = []
    if show:
        if season is not None and episode is not None:
            ep = db.query(Episode).filter(Episode.show_id == show.id, Episode.season_number == season, Episode.episode_number == episode).first()
            if ep:
                target_episodes = [ep]
        elif season is not None:
            target_episodes = db.query(Episode).filter(Episode.show_id == show.id, Episode.season_number == season).all()
        else:
            target_episodes = db.query(Episode).filter(Episode.show_id == show.id).all()

    seen_guids: set[str] = set()
    results: list[SearchResultOut] = []

    for indexer in sorted(indexers, key=lambda i: i.priority):
        client = get_indexer_client(indexer)
        try:
            releases = await client.search(query.strip())
        except Exception:
            continue

        for rel in releases:
            if rel.guid in seen_guids:
                continue
            seen_guids.add(rel.guid)

            match = match_release(
                rel.title,
                show.id if show else 0,
                alias_candidates,
                content_type=show.content_type if show else "series",
                categories=getattr(rel, "categories", None),
            ) if show else None

            # Оценка через DecisionEngine
            decision = DecisionEngine.evaluate_release(
                db=db,
                title=rel.title,
                show=show,
                episodes=target_episodes if target_episodes else None,
                size_bytes=rel.size_bytes or 0,
                seeders=rel.seeders or 0,
                settings=settings,
                categories=getattr(rel, "categories", None),
            )

            pub_iso, age_days = _parse_release_age_and_date(getattr(rel, "pub_date", None))

            results.append(
                SearchResultOut(
                    title=rel.title,
                    indexer=indexer.name,
                    guid=rel.guid,
                    download_url=rel.download_url,
                    page_url=rel.page_url,
                    seeders=rel.seeders,
                    size_bytes=rel.size_bytes,
                    matched=match.matched if match else True,
                    matched_alias=match.alias_text if match else None,
                    match_score=match.score if match else 100.0,
                    parsed_season=match.parsed.season if match else None,
                    parsed_episodes=match.parsed.episodes if match else [],
                    parsed_kind=match.parsed.kind.value if match else "unknown",
                    quality=decision.quality.name,
                    quality_rank=decision.quality.rank,
                    quality_details=decision.quality.to_dict(),
                    languages=decision.language_badges,
                    release_group=decision.release_group,
                    custom_formats=[{"id": cf.id, "name": cf.name, "score": cf.score} for cf in decision.custom_formats],
                    custom_format_score=decision.custom_format_score,
                    approved=decision.approved,
                    rejections=decision.rejections,
                    publish_date=pub_iso,
                    age_days=age_days,
                )
            )

    results.sort(key=lambda r: (r.approved, r.matched, r.custom_format_score, r.quality_rank, r.seeders), reverse=True)
    return results


@router.get("/search/{show_id}", response_model=list[SearchResultOut])
async def search_releases_for_show(
    show_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manual_search")),
):
    """Выполняет поиск по всем включённым индексаторам для данного шоу с оценкой через DecisionEngine."""
    show = db.get(Show, show_id)
    if not show:
        raise HTTPException(404, "Show not found")

    indexers = db.query(Indexer).filter(Indexer.enabled == True).all()  # noqa: E712
    if not indexers:
        raise HTTPException(400, "Нет ни одного включённого индексатора")

    settings = get_or_create_settings(db)
    alias_candidates = build_alias_candidates(show)
    all_episodes = db.query(Episode).filter(Episode.show_id == show.id).all()

    query_terms: list[str] = []
    seen_queries: set[str] = set()
    for alias in alias_candidates:
        q = alias.text.strip()
        if q and q.lower() not in seen_queries:
            seen_queries.add(q.lower())
            query_terms.append(q)

    if show.content_type in ("series", "anime"):
        wanted_sample = [ep for ep in all_episodes if ep.status == EpisodeStatus.WANTED][:5]
        for ep in wanted_sample:
            for alias in alias_candidates[:2]:
                base = alias.text.strip()
                if ep.absolute_number is not None:
                    for fmt in (f"{base} {ep.absolute_number}", f"{base} {ep.absolute_number:02d}", f"{base} {ep.absolute_number:03d}"):
                        if fmt.lower() not in seen_queries:
                            seen_queries.add(fmt.lower())
                            query_terms.append(fmt)
                elif ep.season_number == 0:
                    for fmt in (f"{base} OVA", f"{base} Special"):
                        if fmt.lower() not in seen_queries:
                            seen_queries.add(fmt.lower())
                            query_terms.append(fmt)
    elif show.content_type == "movie" and show.year:
        for alias in alias_candidates[:2]:
            base = alias.text.strip()
            fmt = f"{base} {show.year}"
            if fmt.lower() not in seen_queries:
                seen_queries.add(fmt.lower())
                query_terms.append(fmt)

    seen_guids: set[str] = set()
    results: list[SearchResultOut] = []

    # Опрашиваем индексаторы по приоритету (меньшее число = опрашивается раньше)
    for indexer in sorted(indexers, key=lambda i: i.priority):
        client = get_indexer_client(indexer)
        for term in query_terms:
            try:
                releases = await client.search(term)
            except Exception:
                continue

            for rel in releases:
                if rel.guid in seen_guids:
                    continue
                seen_guids.add(rel.guid)

                match = match_release(
                    rel.title,
                    show_id,
                    alias_candidates,
                    content_type=show.content_type,
                    categories=getattr(rel, "categories", None),
                )

                # Оценка через DecisionEngine
                decision = DecisionEngine.evaluate_release(
                    db=db,
                    title=rel.title,
                    show=show,
                    episodes=all_episodes,
                    size_bytes=rel.size_bytes or 0,
                    seeders=rel.seeders or 0,
                    settings=settings,
                    categories=getattr(rel, "categories", None),
                )

                pub_iso, age_days = _parse_release_age_and_date(getattr(rel, "pub_date", None))

                results.append(
                    SearchResultOut(
                        title=rel.title,
                        indexer=indexer.name,
                        guid=rel.guid,
                        download_url=rel.download_url,
                        page_url=rel.page_url,
                        seeders=rel.seeders,
                        size_bytes=rel.size_bytes,
                        matched=match.matched,
                        matched_alias=match.alias_text,
                        match_score=match.score,
                        parsed_season=match.parsed.season,
                        parsed_episodes=match.parsed.episodes,
                        parsed_kind=match.parsed.kind.value,
                        quality=decision.quality.name,
                        quality_rank=decision.quality.rank,
                        quality_details=decision.quality.to_dict(),
                        languages=decision.language_badges,
                        release_group=decision.release_group,
                        custom_formats=[{"id": cf.id, "name": cf.name, "score": cf.score} for cf in decision.custom_formats],
                        custom_format_score=decision.custom_format_score,
                        approved=decision.approved,
                        rejections=decision.rejections,
                        publish_date=pub_iso,
                        age_days=age_days,
                    )
                )

    results.sort(key=lambda r: (r.approved, r.matched, r.custom_format_score, r.quality_rank, r.seeders), reverse=True)
    return results


class GrabRequest(BaseModel):
    show_id: int
    download_url: str
    release_title: str
    indexer_id: int | None = None
    episode_id: int | None = None
    matched_alias: str | None = None
    page_url: str | None = None
    season: int | None = None
    episode: int | None = None
    episode_ids: list[int] | None = None


@router.post("/grab")
async def grab_release(
    payload: GrabRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manual_search")),
):
    """Ручной захват конкретного релиза (из результатов поиска) в download client."""
    show = db.get(Show, payload.show_id)
    if not show:
        raise HTTPException(404, "Show not found")

    download_client_row = (
        db.query(DownloadClient)
        .filter(DownloadClient.enabled == True)  # noqa: E712
        .order_by(DownloadClient.is_default.desc())
        .first()
    )
    if not download_client_row:
        raise HTTPException(400, "Нет настроенного и включённого download client")

    client = get_client(download_client_row)
    settings = get_or_create_settings(db)
    if show.content_type == "movie":
        save_path = settings.download_folder_movies
    elif show.content_type == "anime":
        save_path = settings.download_folder_anime
    else:
        save_path = settings.download_folder_series
    try:
        torrent_hash = await client.add_torrent(payload.download_url, download_client_row.category, save_path)
    except Exception as exc:
        raise HTTPException(502, f"Не удалось отправить релиз в download client: {exc}")

    # Привязываем серии к торренту
    target_episodes: list[Episode] = []
    if payload.episode_id:
        ep = db.get(Episode, payload.episode_id)
        if ep:
            target_episodes.append(ep)
    elif payload.season is not None and payload.episode is not None:
        ep = (
            db.query(Episode)
            .filter(Episode.show_id == show.id, Episode.season_number == payload.season, Episode.episode_number == payload.episode)
            .first()
        )
        if ep:
            target_episodes.append(ep)
    elif payload.season is not None:
        target_episodes = (
            db.query(Episode)
            .filter(Episode.show_id == show.id, Episode.season_number == payload.season)
            .all()
        )
    elif payload.episode_ids:
        target_episodes = (
            db.query(Episode)
            .filter(Episode.show_id == show.id, Episode.id.in_(payload.episode_ids))
            .all()
        )

    for ep in target_episodes:
        ep.status = EpisodeStatus.DOWNLOADING
        ep.torrent_hash = torrent_hash
        ep.download_client_id = download_client_row.id
        db.add(ep)

    # Ограничиваем скачивание выбранными сериями для сериалов/аниме, для фильмов — гарантируем включение всех файлов
    if torrent_hash and target_episodes:
        if show.content_type == "movie":
            from app.services.auto_search import _ensure_movie_files_wanted
            try:
                background_tasks.add_task(_ensure_movie_files_wanted, client, torrent_hash)
            except Exception as exc:
                logger.warning("Не удалось запланировать включение файлов фильма: %s", exc)
        else:
            from app.services.auto_search import _limit_torrent_files_to_episodes
            try:
                target_eps_data = [
                    Episode(
                        id=ep.id,
                        season_number=ep.season_number,
                        episode_number=ep.episode_number,
                        absolute_number=ep.absolute_number,
                    )
                    for ep in target_episodes
                ]
                background_tasks.add_task(
                    _limit_torrent_files_to_episodes,
                    client,
                    torrent_hash,
                    target_eps_data,
                    None,
                    None,
                    show.content_type,
                )
            except Exception as exc:
                logger.warning("Не удалось запланировать ограничение файлов торрента: %s", exc)

    db.add(DownloadHistory(
        show_id=payload.show_id, episode_id=payload.episode_id or (target_episodes[0].id if target_episodes else None),
        release_title=payload.release_title,
        indexer_id=payload.indexer_id, event_type="grabbed",
        matched_alias=payload.matched_alias, show_title_snapshot=show.title,
    ))
    db.commit()

    title_linked = f'<a href="{payload.page_url}">«{show.title}»</a>' if payload.page_url else f"«{show.title}»"
    await notify_all(db, "grab", f"Захвачен релиз для {title_linked}: {payload.release_title}")

    # После захвата сразу запускаем автопоиск остальных wanted-серий этого шоу
    # в фоне, не дожидаясь плановой джобы (каждые 15 минут).
    background_tasks.add_task(_background_search_show, payload.show_id)

    return {"grabbed": True, "torrent_hash": torrent_hash}


def _background_search_show(show_id: int) -> None:
    """Обёртка для фонового автопоиска: открывает собственную сессию БД."""
    import asyncio

    from app.database import SessionLocal
    from app.services.auto_search import search_and_grab_show

    async def _run():
        session = SessionLocal()
        try:
            show = session.get(Show, show_id)
            if show:
                await search_and_grab_show(session, show)
        finally:
            session.close()

    asyncio.run(_run())
