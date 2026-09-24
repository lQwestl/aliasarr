"""
Отслеживание обновляемых раздач (онгоингов) на трекерах.

Сохраняет guid и URL раздачи (например, на RuTracker, где автор добавляет новые серии в ту же тему).
Периодическая задача перепроверяет раздачу и при появлении новых серий инициирует выборочную докачку.
"""

from __future__ import annotations

from typing import Optional, List, Dict, Any

import datetime as dt

from sqlalchemy.orm import Session

from app.models.db import Episode, EpisodeStatus, Indexer, Show, TrackedRelease
from app.services.parser import parse_episode
from app.services.torznab import TorznabClient


async def recheck_tracked_release(db: Session, tracked: TrackedRelease) -> dict:
    """
    Перепроверяет один отслеживаемый топик.
    Возвращает summary: {"updated": bool, "new_episodes": [...]}
    """
    indexer = db.get(Indexer, tracked.indexer_id)
    if not indexer:
        return {"updated": False, "reason": "indexer_missing"}

    show = getattr(tracked, "show", None) or (db.get(Show, tracked.show_id) if getattr(tracked, "show_id", None) else None)
    if show is not None and getattr(show, "monitored", True) is False:
        tracked.active = False
        db.add(tracked)
        try:
            db.commit()
        except Exception:
            pass
        return {"updated": False, "reason": "show_unmonitored"}

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
    already_seen = {(e.get("season"), e.get("episode")) for e in (tracked.downloaded_episodes or [])}

    new_episode_numbers = [
        ep for ep in parsed.episodes
        if (parsed.season, ep) not in already_seen
    ]

    tracked.last_checked_at = dt.datetime.utcnow()

    if not new_episode_numbers:
        db.add(tracked)
        db.commit()
        return {"updated": False, "new_episodes": []}

    tracked.last_updated_at = dt.datetime.utcnow()

    # Помечаем новые серии как wanted, только если их действительно нужно искать
    wanted_episodes = []
    for ep_num in new_episode_numbers:
        episode = _find_topic_episode(db, tracked.show_id, parsed, ep_num)
        if episode is not None and _can_become_wanted(episode):
            episode.status = EpisodeStatus.WANTED
            db.add(episode)
            wanted_episodes.append(ep_num)

    # Запоминаем все увиденные в теме серии, иначе те же «новые» серии
    # находились бы на каждой проверке и снова сбрасывали статусы.
    seen = list(tracked.downloaded_episodes or [])
    seen.extend({"season": parsed.season, "episode": ep_num} for ep_num in new_episode_numbers)
    tracked.downloaded_episodes = seen

    db.add(tracked)
    db.commit()

    return {
        "updated": True,
        "new_episodes": wanted_episodes,
        "download_url": match.download_url,
        "note": "Требуется selective download только новых файлов через клиент (qBittorrent API)",
    }


def _find_topic_episode(db: Session, show_id: int, parsed, ep_num: int) -> Optional[Episode]:
    """Находит серию тайтла по номеру из обновлённой темы.

    Номер без сезона — это абсолютная нумерация (типично для аниме), а не
    сезон 0: сезон 0 содержит спецвыпуски, и серия 2 основной нумерации
    не имеет отношения к спецвыпуску 2.
    """
    query = db.query(Episode).filter(Episode.show_id == show_id)
    if parsed.season is not None:
        return query.filter(
            Episode.season_number == parsed.season,
            Episode.episode_number == ep_num,
        ).first()

    by_absolute = query.filter(Episode.absolute_number == ep_num).first()
    if by_absolute is not None:
        return by_absolute

    regular_seasons = {
        row[0] for row in db.query(Episode.season_number).filter(
            Episode.show_id == show_id, Episode.season_number > 0,
        ).distinct().all()
    }
    if len(regular_seasons) == 1:
        return query.filter(
            Episode.season_number == next(iter(regular_seasons)),
            Episode.episode_number == ep_num,
        ).first()
    return None


def _can_become_wanted(episode: Episode) -> bool:
    """Серию можно вернуть в поиск, только если у неё нет файла, она не качается
    прямо сейчас и пользователь не исключил её из мониторинга."""
    if getattr(episode, "file_path", None):
        return False
    if not getattr(episode, "monitored", True):
        return False
    return episode.status not in (
        EpisodeStatus.DOWNLOADED,
        EpisodeStatus.DOWNLOADING,
        EpisodeStatus.IGNORED,
        EpisodeStatus.WANTED,
    )


def _deactivate_duplicate_topics(db: Session, tracked_list: list) -> list:
    """Каждый захват создаёт запись отслеживания. Для одной и той же темы
    достаточно самой свежей записи: остальные лишь повторяют запросы к
    индексатору и работают по устаревшему списку серий."""
    newest: dict[tuple, TrackedRelease] = {}
    for tracked in sorted(tracked_list, key=lambda t: t.id or 0, reverse=True):
        if getattr(tracked, "favorite_season", None) is not None:
            continue
        key = (tracked.show_id, tracked.indexer_id, tracked.topic_guid)
        if key in newest:
            tracked.active = False
            db.add(tracked)
        else:
            newest[key] = tracked
    return [t for t in tracked_list if t.active]


async def recheck_all_active(db: Session) -> list[dict]:
    """Перепроверяет все активные отслеживаемые раздачи (вызывается из APScheduler)."""
    tracked_list = db.query(TrackedRelease).filter(TrackedRelease.active == True).all()  # noqa: E712
    if not tracked_list:
        return []
    tracked_list = _deactivate_duplicate_topics(db, tracked_list)

    active_tracked = []
    for tracked in tracked_list:
        show = getattr(tracked, "show", None) or (db.get(Show, tracked.show_id) if getattr(tracked, "show_id", None) else None)
        if show is not None and getattr(show, "monitored", True) is False:
            tracked.active = False
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
            if not has_needed_episodes and show_status in ("ended", "canceled", "complete", "completed"):
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
