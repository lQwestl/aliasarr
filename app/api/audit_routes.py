from __future__ import annotations

import datetime as dt
from typing import Optional, Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.db import AuditLog, User
from app.services.audit_service import log_audit
from app.services.user_service import require_permission

router = APIRouter(prefix="/api/v1/audit", tags=["audit"])


@router.get("")
def list_audit_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    user_id: Optional[int] = None,
    username: Optional[str] = None,
    action: Optional[str] = None,
    search: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("view_audit")),
):
    query = db.query(AuditLog)

    if user_id is not None:
        query = query.filter(AuditLog.user_id == user_id)
    if username:
        query = query.filter(AuditLog.username.ilike(f"%{username.strip()}%"))
    if action:
        query = query.filter(AuditLog.action == action.strip())
    if search:
        s = f"%{search.strip()}%"
        query = query.filter((AuditLog.description.ilike(s)) | (AuditLog.username.ilike(s)) | (AuditLog.action.ilike(s)))

    total = query.count()
    items = query.order_by(AuditLog.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()

    return {
        "items": [
            {
                "id": a.id,
                "created_at": a.created_at.isoformat() if a.created_at else None,
                "user_id": a.user_id,
                "username": a.username,
                "action": a.action,
                "description": a.description,
                "details": a.details,
                "ip_address": a.ip_address,
            }
            for a in items
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size if total > 0 else 1,
    }


@router.post("/clear")
def clear_audit_logs(
    days: int = Query(30, ge=1),
    request: Request = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_settings")),
):
    cutoff = dt.datetime.utcnow() - dt.timedelta(days=days)
    deleted = db.query(AuditLog).filter(AuditLog.created_at < cutoff).delete()
    db.commit()

    log_audit(
        db,
        action="audit.clear",
        description=f"Очищены записи аудита старше {days} дней ({deleted} записей)",
        user=current_user,
        request=request,
    )
    return {"success": True, "deleted_count": deleted}
