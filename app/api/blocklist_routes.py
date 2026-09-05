"""
Маршруты API для управления черным списком релизов (Blocklist / Blacklist).
"""

from __future__ import annotations

import logging
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.services import blocklist_service
from app.services.audit_service import log_audit

logger = logging.getLogger("aliasarr.api.blocklist")

router = APIRouter(prefix="/api/v1/blocklist", tags=["blocklist"])


class ManualBlockRequest(BaseModel):
    release_title: str
    reason: Optional[str] = "Заблокировано вручную пользователем"
    show_id: Optional[int] = None
    torrent_hash: Optional[str] = None
    guid: Optional[str] = None
    download_url: Optional[str] = None
    indexer: Optional[str] = None
    quality: Optional[str] = None
    size: Optional[int] = None


@router.get("")
def list_blocklist_entries(
    show_id: Optional[int] = Query(None, description="Фильтр по ID тайтла"),
    query: Optional[str] = Query(None, description="Поиск по названию или хэшу"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """Возвращает постраничный список записей в черном списке."""
    items, total = blocklist_service.get_blocklist_entries(
        db, show_id=show_id, query=query, limit=limit, offset=offset
    )
    return {
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/shows")
def get_blocked_shows_summary(db: Session = Depends(get_db)):
    """Возвращает список тайтлов, содержащих заблокированные релизы (для группировки на UI)."""
    return blocklist_service.get_blocked_shows_summary(db)


@router.post("")
def add_manual_block(
    req: ManualBlockRequest,
    db: Session = Depends(get_db),
):
    """Вручную добавляет релиз в черный список."""
    if not req.release_title or not req.release_title.strip():
        raise HTTPException(status_code=400, detail="Укажите название релиза")

    entry = blocklist_service.add_to_blocklist(
        db=db,
        release_title=req.release_title.strip(),
        reason=req.reason or "Заблокировано вручную пользователем",
        show_id=req.show_id,
        torrent_hash=req.torrent_hash,
        guid=req.guid,
        download_url=req.download_url,
        indexer=req.indexer,
        quality=req.quality,
        size=req.size,
    )

    log_audit(
        db,
        action="blocklist_add",
        description=f"Релиз «{req.release_title}» добавлен в черный список",
        details={"id": entry.id, "show_id": req.show_id, "hash": req.torrent_hash},
    )

    return {"status": "ok", "id": entry.id, "message": "Релиз добавлен в черный список"}


@router.delete("")
def delete_blocklist_bulk(
    show_id: Optional[str | int] = Query(None),
    db: Session = Depends(get_db),
    **kwargs,
):
    """Очистить черный список (целиком или для указанного тайтла через ?show_id=)."""
    if show_id:
        count = blocklist_service.clear_blocklist_for_show(db, show_id)
        action_name = "blocklist_clear_show"
        desc = f"Очищен черный список для тайтла {show_id} ({count} записей)"
        msg = f"Черный список для тайтла очищен ({count} записей)"
    else:
        count = blocklist_service.clear_all_blocklist(db)
        action_name = "blocklist_clear_all"
        desc = f"Полная очистка черного списка ({count} записей)"
        msg = f"Весь черный список очищен ({count} записей)"

    log_audit(db, action=action_name, description=desc)
    return {"status": "ok", "success": True, "deleted_count": count, "message": msg}


@router.delete("/clear-all")
def clear_entire_blocklist(db: Session = Depends(get_db), **kwargs):
    """Полная очистка всего черного списка."""
    count = blocklist_service.clear_all_blocklist(db)
    log_audit(
        db,
        action="blocklist_clear_all",
        description=f"Полная очистка черного списка ({count} записей)",
    )
    return {"status": "ok", "success": True, "deleted_count": count, "message": f"Весь черный список очищен ({count} записей)"}


@router.delete("/show/{show_id_or_title}")
def clear_show_blocklist(
    show_id_or_title: str,
    db: Session = Depends(get_db),
    **kwargs,
):
    """Очистка черного списка для конкретного тайтла."""
    count = blocklist_service.clear_blocklist_for_show(db, show_id_or_title)
    log_audit(
        db,
        action="blocklist_clear_show",
        description=f"Очищен черный список для тайтла {show_id_or_title} ({count} записей)",
    )
    return {"status": "ok", "success": True, "deleted_count": count}


@router.delete("/{item_id}")
def remove_blocklist_item(
    item_id: Optional[int] = None,
    entry_id: Optional[int] = None,
    db: Session = Depends(get_db),
    **kwargs,
):
    """Удаляет конкретную запись из черного списка (разблокирует релиз)."""
    target_id = item_id if item_id is not None else entry_id
    success = blocklist_service.remove_from_blocklist(db, target_id)
    if not success:
        raise HTTPException(status_code=404, detail="Запись в черном списке не найдена")

    log_audit(
        db,
        action="blocklist_remove",
        description=f"Запись #{target_id} удалена из черного списка",
        details={"item_id": target_id},
    )
    return {"status": "ok", "success": True, "message": "Релиз удален из черного списка"}


# Совместимые псевдонимы для обратной совместимости и юнит-тестов
delete_blocklist_entry = remove_blocklist_item
clear_blocklist = delete_blocklist_bulk
