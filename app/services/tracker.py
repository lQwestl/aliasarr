"""
Отслеживание обновляемых раздач (онгоингов) на трекерах.

Сохраняет guid и URL раздачи (например, на RuTracker, где автор добавляет новые серии в ту же тему).
Периодическая задача перепроверяет раздачу и при появлении новых серий инициирует выборочную докачку.
"""

from __future__ import annotations

from typing import Optional, List, Dict, Any

import datetime as dt
import hashlib
import logging

from sqlalchemy.orm import Session

from app.models.db import Episode, EpisodeStatus, Indexer, Show, TrackedRelease
from app.services.parser import parse_episode
from app.services.torznab import TorznabClient
from app.services.indexer_service import get_indexer_client
from app.services.log_safety import redact_sensitive_data

logger = logging.getLogger("aliasarr.tracker")


async def _release_fingerprint(release) -> str:
    """Prefer the torrent infohash: the topic URL and title can stay unchanged."""
    from app.services.download_client import (
        _fetch_torrent_content_if_url,
        extract_info_hash_from_torrent_bytes,
        extract_info_hash_from_url_or_magnet,
    )

    infohash = getattr(release, "infohash", None) or extract_info_hash_from_url_or_magnet(release.download_url or "")
    if not infohash and release.download_url:
        try:
            content, resolved_url = await _fetch_torrent_content_if_url(release.download_url)
            infohash = extract_info_hash_from_torrent_bytes(content) if content else extract_info_hash_from_url_or_magnet(resolved_url)
        except Exception as exc:
            logger.warning("Не удалось прочитать хэш обновляемой раздачи: %s", redact_sensitive_data(exc))
    if infohash:
        return f"btih:{str(infohash).lower()}"
    fallback = f"{release.title}|{release.size_bytes}|{release.pub_date}"
    return "metadata:" + hashlib.sha256(fallback.encode("utf-8")).hexdigest()


async def _recheck_favorite(db: Session, tracked: TrackedRelease, indexer: Indexer, show: Show) -> dict:
    """Follow exactly one pinned topic on its original indexer."""
    now = dt.datetime.utcnow()
    tracked.last_checked_at = now
    if not getattr(indexer, "enabled", True):
        tracked.last_check_status = "indexer_disabled"
        db.commit()
        return {"updated": False, "reason": "indexer_disabled"}

    client = get_indexer_client(indexer)
    queries = [tracked.favorite_query, show.title, tracked.favorite_title]
    match = None
    try:
        for query in dict.fromkeys(q for q in queries if q):
            releases = await client.search(query)
            match = next((release for release in releases if (
                release.guid == tracked.topic_guid
                or (tracked.topic_url and release.page_url == tracked.topic_url)
            )), None)
            if match:
                break
    except Exception as exc:
        tracked.last_check_status = "search_failed"
        db.commit()
        logger.warning("Проверка закреплённой раздачи %s: %s", tracked.id, redact_sensitive_data(exc))
        return {"updated": False, "reason": "search_failed"}
    if not match:
        tracked.last_check_status = "topic_not_found"
        db.commit()
        return {"updated": False, "reason": "topic_not_found"}

    fingerprint = await _release_fingerprint(match)
    if fingerprint == tracked.last_seen_fingerprint:
        tracked.last_check_status = "unchanged"
        db.commit()
        return {"updated": False, "reason": "unchanged"}

    wanted = db.query(Episode).filter(
        Episode.show_id == show.id,
        Episode.season_number == tracked.favorite_season,
        Episode.monitored == True,  # noqa: E712
        Episode.status == EpisodeStatus.WANTED,
    ).all()
    if not wanted:
        tracked.last_check_status = "no_wanted_episodes"
        db.commit()
        return {"updated": False, "reason": "no_wanted_episodes"}

    from app.services.auto_search import search_and_grab_show
    try:
        result = await search_and_grab_show(
            db, show, episode_ids={ep.id for ep in wanted},
            wanted_only=True, pinned_release=(indexer, match),
        )
    except Exception as exc:
        db.rollback()
        tracked.last_check_status = "grab_failed"
        db.commit()
        logger.warning("Не удалось захватить обновление закреплённой раздачи %s: %s", tracked.id, redact_sensitive_data(exc))
        return {"updated": False, "reason": "grab_failed"}
    grabbed = result.get("grabbed") or []
    if result.get("reason") in ("already_searching", "error", "no_wanted_episodes"):
        status = {
            "already_searching": "busy",
            "error": "grab_failed",
            "no_wanted_episodes": "no_wanted_episodes",
        }[result["reason"]]
        tracked.last_check_status = status
        db.commit()
        return {"updated": False, "reason": status}
    if grabbed:
        tracked.last_seen_fingerprint = fingerprint
        tracked.last_updated_at = now
    tracked.last_check_status = "grabbed" if grabbed else "release_rejected"
    db.add(tracked)
    db.commit()
    return {"updated": bool(grabbed), "new_episodes": [ep.episode_number for ep in wanted] if grabbed else [],
            "reason": "grabbed" if grabbed else "release_rejected"}


async def recheck_tracked_release(db: Session, tracked: TrackedRelease) -> dict:
    """
    Перепроверяет один отслеживаемый топик.
    Возвращает summary: {"updated": bool, "new_episodes": [...]}
    """
    indexer = db.get(Indexer, tracked.indexer_id)
    if not indexer:
        if getattr(tracked, "favorite_season", None) is not None:
            tracked.last_check_status = "indexer_missing"
            db.commit()
        return {"updated": False, "reason": "indexer_missing"}

    show = getattr(tracked, "show", None) or (db.get(Show, tracked.show_id) if getattr(tracked, "show_id", None) else None)
    if show is not None and getattr(show, "monitored", True) is False:
        if getattr(tracked, "favorite_season", None) is not None:
            tracked.last_check_status = "show_unmonitored"
            db.commit()
            return {"updated": False, "reason": "show_unmonitored"}
        tracked.active = False
        db.add(tracked)
        try:
            db.commit()
        except Exception:
            pass
        return {"updated": False, "reason": "show_unmonitored"}

    if getattr(tracked, "favorite_season", None) is not None:
        return await _recheck_favorite(db, tracked, indexer, show)

    client = TorznabClient(indexer.base_url, indexer.api_key, indexer.timeout_seconds)

    # Ищем топик заново по его же guid/url через тот же индексатор.
    # Для реального трекера обычно есть отдельный "details"-запрос по guid;
    # здесь — упрощённый поиск для демонстрации архитектуры.
    try:
        releases = await client.search(tracked.topic_guid)
        if not releases and tracked.show_id:
            show = db.get(Show, tracked.show_id)
            if show:
                releases = await client.search(show.title)
    except Exception as exc:
        return {"updated": False, "reason": f"search_failed: {exc}"}

    match = next(
        (r for r in releases if r.guid == tracked.topic_guid or (tracked.topic_url and r.page_url == tracked.topic_url) or (tracked.infohash and getattr(r, 'infohash', None) == tracked.infohash)),
        None,
    )
    if match is None:
        return {"updated": False, "reason": "topic_not_found"}

    parsed = parse_episode(match.title)
    already_downloaded = {(e["season"], e["episode"]) for e in tracked.downloaded_episodes}

    new_episode_numbers = [
        ep for ep in parsed.episodes
        if (parsed.season, ep) not in already_downloaded
    ]

    tracked.last_checked_at = dt.datetime.utcnow()

    if not new_episode_numbers:
        db.add(tracked)
        db.commit()
        return {"updated": False, "new_episodes": []}

    tracked.last_updated_at = dt.datetime.utcnow()

    # Помечаем новые серии как wanted, если они мониторятся
    wanted_episodes = []
    for ep_num in new_episode_numbers:
        episode = (
            db.query(Episode)
            .filter_by(show_id=tracked.show_id, season_number=parsed.season or 0, episode_number=ep_num)
            .first()
        )
        if episode and episode.status != EpisodeStatus.DOWNLOADED:
            episode.status = EpisodeStatus.WANTED
            db.add(episode)
            wanted_episodes.append(ep_num)

    db.add(tracked)
    db.commit()

    return {
        "updated": True,
        "new_episodes": wanted_episodes,
        "download_url": match.download_url,
        "note": "Требуется selective download только новых файлов через клиент (qBittorrent API)",
    }


async def recheck_all_active(db: Session) -> list[dict]:
    """Перепроверяет все активные отслеживаемые раздачи (вызывается из APScheduler)."""
    tracked_list = db.query(TrackedRelease).filter(TrackedRelease.active == True).all()  # noqa: E712
    if not tracked_list:
        return []

    active_tracked = []
    for tracked in tracked_list:
        show = getattr(tracked, "show", None) or (db.get(Show, tracked.show_id) if getattr(tracked, "show_id", None) else None)
        if show is not None and getattr(show, "monitored", True) is False:
            if getattr(tracked, "favorite_season", None) is None:
                tracked.active = False
                db.add(tracked)
            else:
                tracked.last_check_status = "show_unmonitored"
                db.add(tracked)
            continue
        if not show:
            tracked.active = False
            db.add(tracked)
            continue

        # Фильмы: если фильм уже скачан, в раздаче не могут появиться новые серии
        if getattr(show, "content_type", None) == "movie":
            try:
                ep = db.query(Episode).filter_by(show_id=show.id).first()
                if ep and getattr(ep, "status", None) == EpisodeStatus.DOWNLOADED:
                    tracked.active = False
                    db.add(tracked)
                    continue
            except Exception:
                pass

        # Сериалы / Аниме: если все серии скачаны (нет WANTED/UNAIRED) и статус тайтла ended/completed/canceled,
        # раздача больше не требует постоянного опроса
        try:
            has_needed_episodes = db.query(Episode).filter(
                Episode.show_id == show.id,
                Episode.status.in_([EpisodeStatus.WANTED, EpisodeStatus.UNAIRED, EpisodeStatus.DOWNLOADING]),
            ).first() is not None

            show_status = (getattr(show, "status", None) or "").lower()
            if getattr(tracked, "favorite_season", None) is None and not has_needed_episodes and show_status in ("ended", "canceled", "complete", "completed"):
                tracked.active = False
                db.add(tracked)
                continue
        except Exception:
            pass

        active_tracked.append(tracked)

    try:
        db.commit()
    except Exception:
        pass

    if not active_tracked:
        return []

    total = len(active_tracked)
    from app.services.task_manager import task_manager
    async with task_manager.track(
        name="tracker_sync",
        title="Проверка отслеживаемых раздач",
        message=f"Проверка {total} онгоингов на трекерах...",
        total_items=total,
        current_item=0,
        progress=0.0,
    ) as t_task:
        results = []
        updated_count = 0
        for i, tracked in enumerate(active_tracked):
            show_title = (tracked.show.title if tracked.show else None) or (f"Show #{tracked.show_id}" if tracked.show_id else "раздача")
            t_task.update(
                progress=(i + 1) / total,
                current_item=i + 1,
                total_items=total,
                message=f"Проверка {i + 1} из {total}: {show_title}",
            )
            result = await recheck_tracked_release(db, tracked)
            result["tracked_release_id"] = tracked.id
            if result.get("updated"):
                updated_count += 1
            results.append(result)
        if updated_count > 0:
            t_task.complete(f"Обнаружено {updated_count} обновлений раздач")
        else:
            t_task.complete(f"Все {total} раздач актуальны")
        return results
