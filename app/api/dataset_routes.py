from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import os
import re
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.db import Indexer, Show, User, Episode, Alias, QualityProfile, EpisodeStatus
from app.services.user_service import require_any_permission, get_current_user
from app.services.indexer_service import get_indexer_client
from app.services.parser import parse_episode, detect_season_label, ReleaseKind
from app.services.matcher import (
    is_non_video_release,
    match_release,
    build_alias_candidates,
    resolve_part_offset,
    normalize_title,
)
from app.services.decision_engine import DecisionEngine
from app.services.settings_service import get_settings

logger = logging.getLogger("aliasarr.dataset")

router = APIRouter(prefix="/api/v1/dataset", tags=["dataset"])

PRESET_ANIME = [
    "Re:Zero", "Клеватесс", "Табакошка", "Цугаи загробного мира", "Bleach",
    "Attack on Titan", "Mushoku Tensei", "Jujutsu Kaisen", "Sousou no Frieren",
    "Kimetsu no Yaiba", "Solo Leveling", "Oshi no Ko", "Chainsaw Man", "Vinland Saga",
    "Spy x Family", "One Piece", "Naruto", "Death Note", "Fate/stay night", "Monogatari",
    "Gintama", "Boku no Hero Academia", "Dungeon Meshi", "Hunter x Hunter", "Fullmetal Alchemist",
    "Overlord", "Konosuba", "Kaguya-sama", "Steins;Gate", "Code Geass"
]

PRESET_SERIES = [
    "Breaking Bad", "Game of Thrones", "The Boys", "House of the Dragon",
    "Stranger Things", "Fargo", "True Detective", "The Last of Us",
    "Severance", "Shogun", "Fallout", "Avatar: The Last Airbender",
    "Better Call Saul", "Dark", "Sherlock", "Peaky Blinders",
    "The Mandalorian", "Loki", "Succession", "The Witcher"
]

def _get_storage_path() -> str:
    if os.path.isdir("/config"):
        return "/config/dataset_records.json"
    local_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "data"))
    os.makedirs(local_dir, exist_ok=True)
    return os.path.join(local_dir, "dataset_records.json")


_HARVEST_STATE: dict[str, Any] = {
    "is_running": False,
    "cancel_requested": False,
    "progress_current": 0,
    "progress_total": 0,
    "current_query": "",
    "collected_count": 0,
    "last_run_at": None,
    "error": None,
}


def _load_stored_dataset() -> list[dict]:
    path = _get_storage_path()
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else data.get("records", [])
    except Exception as exc:
        logger.warning("Failed to load dataset: %s", exc)
        return []


def _save_stored_dataset(records: list[dict]) -> None:
    path = _get_storage_path()
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(records, f, ensure_ascii=False, indent=2)
    except Exception as exc:
        logger.error("Failed to save dataset: %s", exc)


def _analyze_record(r: dict) -> dict:
    title = r.get("title", "")
    is_nv = is_non_video_release(title, categories=r.get("categories"))
    if is_nv:
        return {
            "kind": "non_video",
            "is_video": False,
            "season": None,
            "episodes": [],
            "part": None,
            "status": "non_video",
            "status_text": "Не-видео (отфильтровано)",
        }

    p = parse_episode(title)
    s_lbl = detect_season_label(title)

    status = "parsed"
    status_text = "Распознано"
    if p.kind == ReleaseKind.UNKNOWN and s_lbl.get("type") == "none":
        status = "unknown"
        status_text = "Не распознано"

    return {
        "kind": p.kind.value if hasattr(p.kind, "value") else str(p.kind),
        "is_video": True,
        "season": p.season or (s_lbl.get("season") if s_lbl.get("type") == "numbered" else None),
        "episodes": p.episodes or [],
        "part": p.part,
        "total_in_part": p.total_in_part,
        "season_label": s_lbl,
        "status": status,
        "status_text": status_text,
    }


def _find_show_by_query(query: str, shows: list[Show]) -> Optional[Show]:
    norm_q = normalize_title(query)
    if not norm_q:
        return None
    for s in shows:
        if normalize_title(s.title) == norm_q:
            return s
        for a in (s.aliases or []):
            if normalize_title(a.text) == norm_q:
                return s
    return None


def _evaluate_record_against_show(
    show: Show,
    title: str,
    size_bytes: int,
    seeders: int,
    categories: list[int],
    db: Session,
    settings,
) -> dict:
    alias_candidates = build_alias_candidates(show, db=db)
    match = match_release(
        title,
        show.id,
        alias_candidates,
        content_type=show.content_type,
        categories=categories,
        show_year=getattr(show, "year", None),
    )

    qp = None
    if show.quality_profile_id:
        qp = db.get(QualityProfile, show.quality_profile_id)

    wanted_episodes = [
        ep for ep in (show.episodes or [])
        if getattr(ep, "status", None) in (EpisodeStatus.WANTED, EpisodeStatus.MISSING) and getattr(ep, "monitored", True)
    ]

    decision = DecisionEngine.evaluate_release(
        db=db,
        title=title,
        show=show,
        episodes=wanted_episodes if wanted_episodes else None,
        size_bytes=size_bytes,
        seeders=seeders,
        quality_profile=qp,
        settings=settings,
        categories=categories,
    )

    parsed = match.parsed
    rel_s = parsed.season if parsed.season is not None else 1
    part_offset = 0
    if parsed.part and parsed.part >= 2 and show.episodes:
        all_s_eps = [e for e in show.episodes if getattr(e, "season_number", None) == rel_s]
        wanted_s_eps = [e for e in wanted_episodes if getattr(e, "season_number", None) == rel_s]
        part_offset = resolve_part_offset(
            parsed.part,
            parsed.total_in_part,
            parsed.episodes,
            all_s_eps,
            wanted_s_eps,
        )

    covered_eps = []
    if show.content_type == "movie":
        if match.matched:
            covered_eps = list(show.episodes) if show.episodes else []
    elif parsed.kind == ReleaseKind.SEASON_PACK:
        target_s = parsed.season if parsed.season is not None else 1
        covered_eps = [e for e in show.episodes if getattr(e, "season_number", None) == target_s]
    elif parsed.seasons:
        covered_eps = [e for e in show.episodes if getattr(e, "season_number", None) in parsed.seasons]
    elif parsed.episodes:
        target_ep_set = set(parsed.episodes)
        offset_ep_set = {e + part_offset for e in parsed.episodes} if part_offset > 0 else set()
        for e in show.episodes:
            sn = getattr(e, "season_number", None)
            en = getattr(e, "episode_number", None)
            ab = getattr(e, "absolute_number", None)
            if sn == rel_s:
                if part_offset > 0:
                    if en in offset_ep_set:
                        covered_eps.append(e)
                else:
                    if en in target_ep_set:
                        covered_eps.append(e)
            elif ab is not None:
                if part_offset > 0:
                    if ab in offset_ep_set:
                        covered_eps.append(e)
                else:
                    if ab in target_ep_set:
                        covered_eps.append(e)

    wanted_count = sum(1 for e in covered_eps if getattr(e, "status", None) in (EpisodeStatus.WANTED, EpisodeStatus.MISSING))
    downloaded_count = sum(1 for e in covered_eps if getattr(e, "status", None) == EpisodeStatus.DOWNLOADED)

    if covered_eps:
        sorted_eps = sorted(covered_eps, key=lambda x: (getattr(x, "season_number", 0), getattr(x, "episode_number", 0)))
        s_num = getattr(sorted_eps[0], "season_number", 1)
        if len(sorted_eps) == 1:
            cov_summary = f"S{s_num:02d}E{sorted_eps[0].episode_number:02d}"
        else:
            cov_summary = f"S{s_num:02d}E{sorted_eps[0].episode_number:02d}-E{sorted_eps[-1].episode_number:02d} ({len(sorted_eps)} сер.)"
    else:
        cov_summary = "Серии не совпали"

    return {
        "show_id": show.id,
        "show_title": show.title,
        "matched_alias": match.alias_text,
        "match_score": round(match.score, 1),
        "is_title_matched": match.matched,
        "covered_summary": cov_summary,
        "covered_count": len(covered_eps),
        "wanted_overlap": wanted_count,
        "downloaded_overlap": downloaded_count,
        "part_offset": part_offset,
        "approved": decision.approved,
        "rejections": decision.rejections,
        "quality": decision.quality.name,
        "languages": decision.language_badges,
        "release_group": decision.release_group,
    }


def _compute_stats(records: list[dict]) -> dict:
    total = len(records)
    video_titles = 0
    non_video_count = 0
    parsed_success = 0
    unknown_count = 0
    multi_part_count = 0
    season_packs = 0
    ranges_count = 0
    single_eps = 0
    absolute_eps = 0
    movies_count = 0

    approved_count = 0
    rejected_count = 0
    matched_shows_count = 0
    wanted_overlap_count = 0

    for r in records:
        analysis = r.get("analysis") or _analyze_record(r)
        if not analysis.get("is_video"):
            non_video_count += 1
            continue

        video_titles += 1
        kind = analysis.get("kind")
        eps = analysis.get("episodes") or []

        if analysis.get("part") and analysis.get("part") >= 2:
            multi_part_count += 1

        if analysis.get("status") == "parsed":
            parsed_success += 1
            if kind == "season_pack":
                season_packs += 1
            elif kind == "episode":
                if len(eps) > 1:
                    ranges_count += 1
                else:
                    single_eps += 1
            elif kind == "absolute":
                absolute_eps += 1
            elif kind == "movie":
                movies_count += 1
        else:
            unknown_count += 1

        db_m = r.get("db_match")
        if db_m:
            if db_m.get("is_title_matched"):
                matched_shows_count += 1
            if db_m.get("approved") is True:
                approved_count += 1
            elif db_m.get("approved") is False:
                rejected_count += 1
            if (db_m.get("wanted_overlap") or 0) > 0:
                wanted_overlap_count += 1

    acc = round((parsed_success / video_titles * 100), 1) if video_titles > 0 else 100.0

    return {
        "total_records": total,
        "video_titles": video_titles,
        "non_video_filtered": non_video_count,
        "parsed_success": parsed_success,
        "accuracy_pct": acc,
        "unknown_total": unknown_count,
        "multi_part_detected": multi_part_count,
        "season_packs": season_packs,
        "episode_ranges": ranges_count,
        "single_episodes": single_eps,
        "absolute_episodes": absolute_eps,
        "movies_detected": movies_count,
        "approved_count": approved_count,
        "rejected_count": rejected_count,
        "matched_shows_count": matched_shows_count,
        "wanted_overlap_count": wanted_overlap_count,
    }


class HarvestRequest(BaseModel):
    preset: str = "anime"  # anime | series | all | db | show | custom
    show_id: Optional[int] = None
    custom_queries: Optional[str] = None
    indexer_id: Optional[int] = None


async def _run_harvest_task(targets: list[dict], indexer_id: Optional[int]):
    global _HARVEST_STATE
    _HARVEST_STATE["is_running"] = True
    _HARVEST_STATE["cancel_requested"] = False
    _HARVEST_STATE["progress_current"] = 0
    _HARVEST_STATE["progress_total"] = len(targets)
    _HARVEST_STATE["collected_count"] = 0
    _HARVEST_STATE["error"] = None

    from app.database import SessionLocal
    db = SessionLocal()

    try:
        settings = get_settings(db)
        if indexer_id:
            idx_list = db.query(Indexer).filter(Indexer.id == indexer_id, Indexer.enabled == True).all()
        else:
            idx_list = db.query(Indexer).filter(Indexer.enabled == True).all()

        if not idx_list:
            _HARVEST_STATE["error"] = "Нет активных индексаторов (Jackett / Prowlarr / Torznab)"
            return

        clients = [(idx, get_indexer_client(idx)) for idx in idx_list]

        all_shows = db.query(Show).all()
        show_by_id = {s.id: s for s in all_shows}

        existing_records = _load_stored_dataset()
        seen_guids = {r.get("guid") for r in existing_records if r.get("guid")}
        seen_titles = {r.get("title") for r in existing_records if r.get("title")}
        new_records = []

        for idx_t, target in enumerate(targets, 1):
            if _HARVEST_STATE["cancel_requested"]:
                logger.info("Harvest cancelled by user")
                break

            q = target.get("query", "")
            target_show_id = target.get("show_id")

            _HARVEST_STATE["progress_current"] = idx_t
            _HARVEST_STATE["current_query"] = q

            target_show = show_by_id.get(target_show_id) if target_show_id else _find_show_by_query(q, all_shows)

            for indexer_row, client in clients:
                if _HARVEST_STATE["cancel_requested"]:
                    break
                try:
                    releases = await asyncio.wait_for(client.search(q), timeout=client.timeout or 15)
                    for rel in releases:
                        title = getattr(rel, "title", "").strip()
                        guid = getattr(rel, "guid", "") or title
                        if not title or title in seen_titles or guid in seen_guids:
                            continue
                        seen_titles.add(title)
                        seen_guids.add(guid)

                        size_bytes = getattr(rel, "size_bytes", 0) or 0
                        seeders = getattr(rel, "seeders", 0) or 0
                        categories = getattr(rel, "categories", []) or []

                        rec = {
                            "title": title,
                            "guid": guid,
                            "indexer": indexer_row.name,
                            "size_bytes": size_bytes,
                            "categories": categories,
                            "query": q,
                            "created_at": dt.datetime.utcnow().isoformat() + "Z",
                        }
                        rec["analysis"] = _analyze_record(rec)

                        # Безопасная симуляция (Dry-run): сопоставление с тайтлом и сериями без скачивания
                        if target_show:
                            rec["db_match"] = _evaluate_record_against_show(
                                target_show,
                                title,
                                size_bytes,
                                seeders,
                                categories,
                                db,
                                settings,
                            )
                        else:
                            rec["db_match"] = None

                        new_records.append(rec)
                        _HARVEST_STATE["collected_count"] += 1
                except Exception as exc:
                    logger.debug("Indexer %s search '%s' error: %s", indexer_row.name, q, exc)

        all_data = existing_records + new_records
        _save_stored_dataset(all_data)
        _HARVEST_STATE["last_run_at"] = dt.datetime.utcnow().isoformat() + "Z"

    except Exception as exc:
        logger.exception("Harvest task failed: %s", exc)
        _HARVEST_STATE["error"] = str(exc)
    finally:
        db.close()
        _HARVEST_STATE["is_running"] = False


@router.get("/status")
def get_harvest_status():
    records = _load_stored_dataset()
    stats = _compute_stats(records)
    return {
        "state": _HARVEST_STATE,
        "stats": stats,
    }


@router.post("/harvest")
def start_harvest(
    req: HarvestRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_permission("manual_search", "manage_settings")),
):
    if _HARVEST_STATE["is_running"]:
        raise HTTPException(status_code=409, detail="Процесс сбора уже запущен")

    targets: list[dict] = []

    if req.preset == "show":
        if not req.show_id:
            raise HTTPException(status_code=400, detail="Выберите тайтл из библиотеки")
        show = db.get(Show, req.show_id)
        if not show:
            raise HTTPException(status_code=404, detail="Тайтл не найден")
        queries = [show.title]
        for a in (show.aliases or []):
            if a.text and a.text not in queries:
                queries.append(a.text)
        for q in queries:
            targets.append({"query": q, "show_id": show.id})

    elif req.preset == "db":
        shows = db.query(Show).all()
        if not shows:
            raise HTTPException(status_code=400, detail="В библиотеке Aliasarr пока нет добавленных тайтлов")
        for s in shows:
            if s.title:
                targets.append({"query": s.title, "show_id": s.id})

    elif req.preset == "custom":
        if req.custom_queries:
            raw_items = re.split(r"[,\n\r]+", req.custom_queries)
            raw_queries = [it.strip() for it in raw_items if it.strip()]
            all_shows = db.query(Show).all()
            for q in raw_queries:
                matched_s = _find_show_by_query(q, all_shows)
                targets.append({"query": q, "show_id": matched_s.id if matched_s else None})
        if not targets:
            raise HTTPException(status_code=400, detail="Укажите хотя бы один тайтл для поиска")

    else:
        raw_queries = []
        if req.preset == "anime":
            raw_queries = PRESET_ANIME
        elif req.preset == "series":
            raw_queries = PRESET_SERIES
        elif req.preset == "all":
            raw_queries = PRESET_ANIME + PRESET_SERIES

        all_shows = db.query(Show).all()
        for q in raw_queries:
            matched_s = _find_show_by_query(q, all_shows)
            targets.append({"query": q, "show_id": matched_s.id if matched_s else None})

    background_tasks.add_task(_run_harvest_task, targets, req.indexer_id)
    return {
        "success": True,
        "message": f"Запущен сбор раздач для {len(targets)} запросов (симуляция сопоставления без скачивания)",
        "total_queries": len(targets),
    }


@router.post("/stop")
def stop_harvest(
    current_user: User = Depends(require_any_permission("manual_search", "manage_settings")),
):
    if not _HARVEST_STATE["is_running"]:
        return {"success": True, "message": "Сбор не запущен"}
    _HARVEST_STATE["cancel_requested"] = True
    return {"success": True, "message": "Запрос на остановку отправлен"}


@router.get("/data")
def get_dataset_data(
    filter: str = "all",  # all | approved | rejected | wanted_eps | video | non_video | unknown | multi_part
    query: Optional[str] = None,
    page: int = 1,
    page_size: int = 50,
):
    records = _load_stored_dataset()
    stats = _compute_stats(records)

    filtered = []
    query_lower = query.strip().lower() if query else None

    for r in reversed(records):
        analysis = r.get("analysis") or _analyze_record(r)
        r["analysis"] = analysis
        db_m = r.get("db_match") or {}

        if filter == "video" and not analysis.get("is_video"):
            continue
        if filter == "non_video" and analysis.get("is_video"):
            continue
        if filter == "unknown" and analysis.get("status") != "unknown":
            continue
        if filter == "multi_part" and not (analysis.get("part") and analysis.get("part") >= 2):
            continue
        if filter == "approved" and db_m.get("approved") is not True:
            continue
        if filter == "rejected" and db_m.get("approved") is not False:
            continue
        if filter == "wanted_eps" and (db_m.get("wanted_overlap") or 0) <= 0:
            continue

        if query_lower:
            t = r.get("title", "").lower()
            idx = r.get("indexer", "").lower()
            q_src = r.get("query", "").lower()
            s_name = (db_m.get("show_title") or "").lower()
            if (
                query_lower not in t
                and query_lower not in idx
                and query_lower not in q_src
                and query_lower not in s_name
            ):
                continue

        filtered.append(r)

    total = len(filtered)
    start_idx = (page - 1) * page_size
    items = filtered[start_idx : start_idx + page_size]

    return {
        "stats": stats,
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


class DiagnoseRequest(BaseModel):
    title: str
    show_id: Optional[int] = None
    size_bytes: Optional[int] = 0
    seeders: Optional[int] = 10
    categories: Optional[list[int]] = None


@router.post("/diagnose")
def diagnose_release(
    req: DiagnoseRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_permission("manual_search", "manage_settings")),
):
    settings = get_settings(db)
    target_show = None
    if req.show_id:
        target_show = db.get(Show, req.show_id)
    if not target_show:
        all_shows = db.query(Show).all()
        target_show = _find_show_by_query(req.title, all_shows)

    analysis = _analyze_record({"title": req.title, "categories": req.categories or []})
    db_match = None
    if target_show:
        db_match = _evaluate_record_against_show(
            target_show,
            req.title,
            req.size_bytes or 0,
            req.seeders or 10,
            req.categories or [],
            db,
            settings,
        )

    return {
        "title": req.title,
        "analysis": analysis,
        "db_match": db_match,
    }


@router.get("/export")
def export_dataset(
    filter: str = "all",  # all | unknown | approved | rejected | wanted_eps | video | non_video
    current_user: User = Depends(require_any_permission("manual_search", "manage_settings")),
):
    records = _load_stored_dataset()
    stats = _compute_stats(records)

    filtered_records = []
    for r in records:
        analysis = r.get("analysis") or _analyze_record(r)
        db_m = r.get("db_match") or {}

        if filter == "unknown" and analysis.get("status") != "unknown":
            continue
        if filter == "video" and not analysis.get("is_video"):
            continue
        if filter == "non_video" and analysis.get("is_video"):
            continue
        if filter == "approved" and db_m.get("approved") is not True:
            continue
        if filter == "rejected" and db_m.get("approved") is not False:
            continue
        if filter == "wanted_eps" and (db_m.get("wanted_overlap") or 0) <= 0:
            continue
        filtered_records.append(r)

    payload = {
        "exported_at": dt.datetime.utcnow().isoformat() + "Z",
        "filter": filter,
        "stats": stats,
        "records_count": len(filtered_records),
        "records": filtered_records,
    }
    content = json.dumps(payload, ensure_ascii=False, indent=2)
    prefix = "aliasarr_unknown_titles" if filter == "unknown" else "aliasarr_dataset"
    filename = f"{prefix}_{dt.datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json"
    return Response(
        content=content,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.delete("")
def clear_dataset(
    current_user: User = Depends(require_any_permission("manage_settings")),
):
    path = _get_storage_path()
    if os.path.exists(path):
        try:
            os.remove(path)
        except Exception as exc:
            logger.error("Failed to delete dataset file: %s", exc)
    return {"success": True, "message": "Собранные данные успешно удалены"}
