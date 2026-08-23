from __future__ import annotations

import datetime as dt
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.db import ReleaseLog, User
from app.services.user_service import require_permission, get_current_user

router = APIRouter(prefix="/api/v1/release-logs", tags=["release-logs"])


class ReleaseLogOut(BaseModel):
    id: int
    created_at: dt.datetime
    stage: str
    level: str
    show_id: Optional[int] = None
    show_title: Optional[str] = None
    release_title: Optional[str] = None
    indexer: Optional[str] = None
    message: str
    details: Optional[dict[str, Any]] = None

    class Config:
        from_attributes = True


class ReleaseLogsPageOut(BaseModel):
    items: list[ReleaseLogOut]
    total: int
    page: int
    page_size: int


def _require_admin_or_owner(current_user: User = Depends(get_current_user)) -> User:
    # Доступ только главному админу (is_owner) или пользователю с правами manage_settings
    if not current_user.is_owner and not getattr(current_user, "perm_manage_settings", False):
        raise HTTPException(403, "Доступ к логам релизов разрешён только главному администратору")
    return current_user


@router.get("", response_model=ReleaseLogsPageOut)
def list_release_logs(
    stage: Optional[str] = None,
    level: Optional[str] = None,
    query: Optional[str] = None,
    show_id: Optional[int] = None,
    page: int = 1,
    page_size: int = 50,
    sort: str = "desc",
    db: Session = Depends(get_db),
    current_user: User = Depends(_require_admin_or_owner),
):
    """Получение журнала логики релизов с пагинацией и фильтрацией."""
    q = db.query(ReleaseLog)

    if stage and stage != "all":
        q = q.filter(ReleaseLog.stage == stage)

    if level and level != "all":
        q = q.filter(ReleaseLog.level == level)

    if show_id is not None:
        q = q.filter(ReleaseLog.show_id == show_id)

    if query:
        search_like = f"%{query.strip()}%"
        q = q.filter(
            (ReleaseLog.show_title.ilike(search_like)) |
            (ReleaseLog.release_title.ilike(search_like)) |
            (ReleaseLog.indexer.ilike(search_like)) |
            (ReleaseLog.message.ilike(search_like))
        )

    total = q.count()
    order_col = ReleaseLog.created_at.desc() if sort == "desc" else ReleaseLog.created_at.asc()
    items = q.order_by(order_col).offset((page - 1) * page_size).limit(page_size).all()

    return ReleaseLogsPageOut(items=items, total=total, page=page, page_size=page_size)


@router.delete("")
def clear_release_logs(
    db: Session = Depends(get_db),
    current_user: User = Depends(_require_admin_or_owner),
):
    """Очистить журнал релизов."""
    count = db.query(ReleaseLog).delete()
    db.commit()
    return {"success": True, "deleted": count, "message": f"Очищено записей: {count}"}


@router.get("/export")
def export_release_logs(
    db: Session = Depends(get_db),
    current_user: User = Depends(_require_admin_or_owner),
):
    """Выгрузить все логи релизов в текстовый файл (.txt) для анализа и отладки."""
    logs = db.query(ReleaseLog).order_by(ReleaseLog.created_at.asc()).limit(5000).all()
    lines = []
    lines.append("=== ALIASARR RELEASE LOGS DUMP ===")
    lines.append(f"Generated at: {dt.datetime.utcnow().isoformat()}Z")
    lines.append(f"Total entries: {len(logs)}\n" + "=" * 50 + "\n")

    for l in logs:
        ts = l.created_at.strftime("%Y-%m-%d %H:%M:%S")
        lines.append(f"[{ts}] [{l.level.upper()}] [{l.stage.upper()}]")
        if l.show_title:
            lines.append(f"  Show: {l.show_title}")
        if l.release_title:
            lines.append(f"  Release: {l.release_title}")
        if l.indexer:
            lines.append(f"  Indexer: {l.indexer}")
        lines.append(f"  Message: {l.message}")
        if l.details:
            import json
            try:
                lines.append(f"  Details: {json.dumps(l.details, ensure_ascii=False)}")
            except Exception:
                pass
        lines.append("-" * 40)

    content = "\n".join(lines)
    return Response(
        content=content,
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=aliasarr_release_logs.txt"}
    )
