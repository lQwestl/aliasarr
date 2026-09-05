"""
Сервис управления черным списком релизов (Blocklist / Blacklist).

Обеспечивает:
- Сохранение заблокированных релизов в базе данных
- Проверку кандидатов перед захватом
- Автоматическое связывание блокировок при удалении и повторном добавлении тайтлов по TMDB/IMDb ID
- Ручное управление черным списком через UI и API
"""

from __future__ import annotations

import datetime as dt
import logging
import os
import re
from typing import Optional, List, Dict, Any, Tuple

from sqlalchemy import or_, and_, func
from sqlalchemy.orm import Session

from app.models.db import Blocklist, Show

logger = logging.getLogger("aliasarr.blocklist")


def add_to_blocklist(
    db: Session,
    release_title: str,
    reason: str,
    show: Optional[Show] = None,
    show_id: Optional[int] = None,
    torrent_hash: Optional[str] = None,
    guid: Optional[str] = None,
    download_url: Optional[str] = None,
    indexer: Optional[str] = None,
    quality: Optional[str] = None,
    size: Optional[int] = None,
) -> Blocklist:
    """
    Добавляет релиз в черный список с сохранением метаданных тайтла.
    """
    if not show and show_id:
        show = db.get(Show, show_id)

    cur_show_id = show.id if show else show_id
    cur_show_title = show.title if show else None
    cur_tmdb_id = getattr(show, "tmdb_id", None) if show else None
    cur_imdb_id = getattr(show, "imdb_id", None) if show else None

    norm_hash = torrent_hash.lower().strip() if torrent_hash else None
    norm_guid = str(guid).lower().strip() if guid else None
    norm_url = str(download_url).strip() if download_url else None
    clean_title = release_title.strip() if release_title else "Unknown Release"

    q = db.query(Blocklist)
    conditions = []
    if norm_hash:
        conditions.append(func.lower(Blocklist.torrent_hash) == norm_hash)
    if norm_guid:
        conditions.append(func.lower(Blocklist.guid) == norm_guid)
    if cur_show_id:
        conditions.append(and_(Blocklist.show_id == cur_show_id, func.lower(Blocklist.release_title) == clean_title.lower()))
    elif cur_show_title:
        conditions.append(and_(func.lower(Blocklist.show_title) == cur_show_title.lower(), func.lower(Blocklist.release_title) == clean_title.lower()))

    if conditions:
        existing = q.filter(or_(*conditions)).first()
        if existing:
            if reason and not existing.reason:
                existing.reason = reason
            if not existing.torrent_hash and norm_hash:
                existing.torrent_hash = norm_hash
            if not existing.indexer and indexer:
                existing.indexer = indexer
            if not existing.quality and quality:
                existing.quality = quality
            if not existing.size and size:
                existing.size = size
            db.add(existing)
            try:
                db.commit()
                db.refresh(existing)
            except Exception:
                db.rollback()
            return existing

    entry = Blocklist(
        show_id=cur_show_id,
        show_title=cur_show_title,
        tmdb_id=cur_tmdb_id,
        imdb_id=cur_imdb_id,
        torrent_hash=norm_hash,
        guid=norm_guid,
        download_url=norm_url,
        release_title=clean_title,
        indexer=indexer,
        reason=reason or "Отклонено системой",
        quality=quality,
        size=size,
        created_at=dt.datetime.utcnow(),
    )
    db.add(entry)
    try:
        db.commit()
        db.refresh(entry)
        logger.info(
            "Релиз «%s» занесен в черный список (тайтл: %s, хэш: %s, причина: %s)",
            clean_title, cur_show_title or cur_show_id or "Global", norm_hash or "-", reason,
        )
    except Exception as exc:
        db.rollback()
        logger.warning("Не удалось сохранить запись в черный список: %s", exc)

    return entry


def is_release_blocked(
    db: Session,
    show: Optional[Show] = None,
    show_id: Optional[int] = None,
    title: Optional[str] = None,
    torrent_hash: Optional[str] = None,
    guid: Optional[str] = None,
    download_url: Optional[str] = None,
    release_title: Optional[str] = None,
) -> Tuple[bool, Optional[str]]:
    """
    Проверяет, заблокирован ли кандидат в черном списке для данного тайтла (или глобально).
    Возвращает (is_blocked: bool, reason: str | None).
    """
    if not title and release_title:
        title = release_title
    if not show and show_id:
        show = db.get(Show, show_id)

    cur_show_id = show.id if show else show_id
    cur_tmdb_id = getattr(show, "tmdb_id", None) if show else None
    cur_imdb_id = getattr(show, "imdb_id", None) if show else None
    cur_show_title = show.title if show else None

    norm_hash = torrent_hash.lower().strip() if torrent_hash else None
    norm_guid = str(guid).lower().strip() if guid else None
    norm_url = str(download_url).lower().strip() if download_url else None
    clean_title = title.strip().lower() if title else None

    filters = []

    if norm_hash:
        filters.append(func.lower(Blocklist.torrent_hash) == norm_hash)

    if norm_guid:
        filters.append(func.lower(Blocklist.guid) == norm_guid)

    if norm_url:
        filters.append(func.lower(Blocklist.download_url) == norm_url)

    if clean_title:
        title_conds = [func.lower(Blocklist.release_title) == clean_title]
        show_match_conds = []
        if cur_show_id:
            show_match_conds.append(Blocklist.show_id == cur_show_id)
        if cur_tmdb_id:
            show_match_conds.append(Blocklist.tmdb_id == cur_tmdb_id)
        if cur_imdb_id:
            show_match_conds.append(Blocklist.imdb_id == cur_imdb_id)
        if cur_show_title:
            show_match_conds.append(func.lower(Blocklist.show_title) == cur_show_title.lower())

        if show_match_conds:
            filters.append(and_(or_(*title_conds), or_(*show_match_conds)))
        else:
            filters.append(and_(or_(*title_conds), Blocklist.show_id.is_(None)))

    if not filters:
        return False, None

    match = db.query(Blocklist).filter(or_(*filters)).first()
    if match:
        return True, match.reason or "Заблокировано в черном списке"

    return False, None


def relink_blocklist_for_show(db: Session, show: Show) -> int:
    """
    При добавлении нового шоу или обновлении метаданных привязывает
    существующие записи в черном списке по TMDB ID, IMDb ID или названию тайтла.
    """
    if not show or not show.id:
        return 0

    relink_conditions = []
    if getattr(show, "tmdb_id", None):
        relink_conditions.append(Blocklist.tmdb_id == show.tmdb_id)
    if getattr(show, "imdb_id", None):
        relink_conditions.append(Blocklist.imdb_id == show.imdb_id)
    if show.title:
        relink_conditions.append(func.lower(Blocklist.show_title) == show.title.lower().strip())

    if not relink_conditions:
        return 0

    unlinked = db.query(Blocklist).filter(
        Blocklist.show_id.is_(None),
        or_(*relink_conditions),
    ).all()

    count = 0
    for item in unlinked:
        item.show_id = show.id
        if not item.show_title and show.title:
            item.show_title = show.title
        if not item.tmdb_id and getattr(show, "tmdb_id", None):
            item.tmdb_id = show.tmdb_id
        if not item.imdb_id and getattr(show, "imdb_id", None):
            item.imdb_id = show.imdb_id
        db.add(item)
        count += 1

    if count > 0:
        try:
            db.commit()
            logger.info("Подключено %d записей черного списка к тайтлу «%s» (ID: %d)", count, show.title, show.id)
        except Exception as exc:
            db.rollback()
            logger.debug("Ошибка связывания черного списка для шоу %s: %s", show.id, exc)

    return count


def remove_from_blocklist(db: Session, item_id: int) -> bool:
    """Удаляет запись из черного списка по её ID."""
    item = db.get(Blocklist, item_id)
    if not item:
        return False
    db.delete(item)
    try:
        db.commit()
        logger.info("Запись #%d («%s») удалена из черного списка", item_id, item.release_title)
        return True
    except Exception as exc:
        db.rollback()
        logger.warning("Не удалось удалить запись #%d из черного списка: %s", item_id, exc)
        return False


def update_blocklist_entry(
    db: Session,
    item_id: int,
    release_title: Optional[str] = None,
    reason: Optional[str] = None,
    show_id: Optional[int] = None,
    clear_show_id: bool = False,
    torrent_hash: Optional[str] = None,
    clear_torrent_hash: bool = False,
    guid: Optional[str] = None,
    download_url: Optional[str] = None,
    indexer: Optional[str] = None,
    quality: Optional[str] = None,
    size: Optional[int] = None,
) -> Optional[Blocklist]:
    """Обновляет существующую запись в черном списке."""
    item = db.get(Blocklist, item_id)
    if not item:
        return None

    if release_title is not None and release_title.strip():
        item.release_title = release_title.strip()
    if reason is not None:
        item.reason = reason.strip()
    if clear_torrent_hash:
        item.torrent_hash = None
    elif torrent_hash is not None:
        item.torrent_hash = torrent_hash.strip().lower() if torrent_hash.strip() else None
    if guid is not None:
        item.guid = str(guid).strip().lower() if str(guid).strip() else None
    if download_url is not None:
        item.download_url = str(download_url).strip() if str(download_url).strip() else None
    if indexer is not None:
        item.indexer = str(indexer).strip() if str(indexer).strip() else None
    if quality is not None:
        item.quality = str(quality).strip() if str(quality).strip() else None
    if size is not None:
        item.size = size

    # Обновление привязки к тайтлу
    if clear_show_id or (show_id is not None and (show_id in (0, -1) or str(show_id) in ("0", ""))):
        item.show_id = None
        item.show_title = None
        item.tmdb_id = None
        item.imdb_id = None
    elif show_id is not None:
        show = db.get(Show, int(show_id))
        if show:
            item.show_id = show.id
            item.show_title = show.title
            item.tmdb_id = getattr(show, "tmdb_id", None)
            item.imdb_id = getattr(show, "imdb_id", None)
        else:
            item.show_id = int(show_id)

    db.add(item)
    try:
        db.commit()
        db.refresh(item)
        logger.info("Запись #%d в черном списке обновлена", item_id)
        return item
    except Exception as exc:
        db.rollback()
        logger.warning("Не удалось обновить запись #%d в черном списке: %s", item_id, exc)
        return None


def clear_blocklist_for_show(db: Session, show_id_or_title: Optional[str | int] = None, *, show_id: Optional[int] = None) -> int:
    """Удаляет все записи черного списка для конкретного шоу."""
    target = show_id if show_id is not None else show_id_or_title
    if target is None:
        return 0

    if isinstance(target, int) or (isinstance(target, str) and str(target).isdigit()):
        sid = int(target)
        filt = or_(Blocklist.show_id == sid, Blocklist.tmdb_id == sid)
    else:
        title_str = str(target).strip().lower()
        filt = func.lower(Blocklist.show_title) == title_str

    try:
        count = db.query(Blocklist).filter(filt).delete()
        db.commit()
        logger.info("Удалено %d записей черного списка для тайтла %s", count, target)
        return count
    except Exception as exc:
        db.rollback()
        try:
            items = db.query(Blocklist).filter(filt).all()
            count = len(items)
            for it in items:
                db.delete(it)
            if count > 0:
                db.commit()
            return count
        except Exception:
            logger.warning("Ошибка очистки черного списка: %s", exc)
            return 0


def clear_all_blocklist(db: Session) -> int:
    """Полностью очищает весь черный список."""
    try:
        count = db.query(Blocklist).delete()
        db.commit()
        logger.info("Весь черный список очищен (%d записей удалено)", count)
        return count
    except Exception as exc:
        db.rollback()
        try:
            items = db.query(Blocklist).all()
            count = len(items)
            for it in items:
                db.delete(it)
            if count > 0:
                db.commit()
            return count
        except Exception:
            logger.warning("Ошибка очистки всего черного списка: %s", exc)
            return 0


def get_blocklist_entries(
    db: Session,
    show_id: Optional[int] = None,
    query: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> Tuple[List[Dict[str, Any]], int]:
    """
    Возвращает список записей черного списка с пагинацией и фильтрацией.
    """
    q = db.query(Blocklist)
    if show_id is not None:
        q = q.filter(Blocklist.show_id == show_id)

    if query and query.strip():
        q_term = f"%{query.strip().lower()}%"
        q = q.filter(
            or_(
                func.lower(Blocklist.release_title).like(q_term),
                func.lower(Blocklist.show_title).like(q_term),
                func.lower(Blocklist.reason).like(q_term),
                func.lower(Blocklist.indexer).like(q_term),
                func.lower(Blocklist.torrent_hash).like(q_term),
            )
        )

    total_count = q.count()
    items = q.order_by(Blocklist.created_at.desc()).offset(offset).limit(limit).all()

    result = []
    for it in items:
        show_obj = it.show if it.show else (db.get(Show, it.show_id) if it.show_id else None)
        poster_url = getattr(show_obj, "poster_url", None) if show_obj else None
        show_title = it.show_title or (show_obj.title if show_obj else "Глобальная блокировка")

        result.append({
            "id": it.id,
            "show_id": it.show_id,
            "show_title": show_title,
            "tmdb_id": it.tmdb_id,
            "imdb_id": it.imdb_id,
            "poster_url": poster_url,
            "torrent_hash": it.torrent_hash,
            "guid": it.guid,
            "download_url": it.download_url,
            "release_title": it.release_title,
            "indexer": it.indexer,
            "reason": it.reason,
            "quality": it.quality,
            "size": it.size,
            "created_at": it.created_at.isoformat() if it.created_at else None,
        })

    return result, total_count


def get_blocked_shows_summary(db: Session) -> List[Dict[str, Any]]:
    """
    Возвращает список всех тайтлов, у которых есть заблокированные релизы в черном списке,
    со счетчиками и метаданными для удобной группировки на UI.
    """
    items = db.query(Blocklist).all()
    grouped: dict[str, dict[str, Any]] = {}

    for it in items:
        key = f"id_{it.show_id}" if it.show_id else f"title_{it.show_title or 'global'}"
        if key not in grouped:
            show_obj = it.show if it.show else (db.get(Show, it.show_id) if it.show_id else None)
            poster_url = getattr(show_obj, "poster_url", None) if show_obj else None
            content_type = getattr(show_obj, "content_type", "series") if show_obj else "series"
            year = getattr(show_obj, "year", None) if show_obj else None
            title = it.show_title or (show_obj.title if show_obj else "Глобальная блокировка")

            grouped[key] = {
                "key": key,
                "show_id": it.show_id,
                "show_title": title,
                "tmdb_id": it.tmdb_id,
                "imdb_id": it.imdb_id,
                "poster_url": poster_url,
                "content_type": content_type,
                "year": year,
                "count": 0,
                "latest_blocked_at": it.created_at,
            }

        grouped[key]["count"] += 1
        if it.created_at and (not grouped[key]["latest_blocked_at"] or it.created_at > grouped[key]["latest_blocked_at"]):
            grouped[key]["latest_blocked_at"] = it.created_at

    result = list(grouped.values())
    result.sort(key=lambda x: (x["latest_blocked_at"] or dt.datetime.min), reverse=True)

    for r in result:
        if isinstance(r["latest_blocked_at"], dt.datetime):
            r["latest_blocked_at"] = r["latest_blocked_at"].isoformat()

    return result
