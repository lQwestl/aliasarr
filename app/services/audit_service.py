from __future__ import annotations

import datetime as dt
import logging
from typing import Optional, Any

try:
    from sqlalchemy.orm import Session
    from app.models.db import AuditLog
except ImportError:
    Session = object
    class AuditLog:
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)

logger = logging.getLogger(__name__)


def log_audit(
    db: Session,
    action: str,
    description: str = "",
    *,
    user: Any = None,
    username: Optional[str] = None,
    user_id: Optional[int] = None,
    details: Any = None,
    request: Any = None,
) -> Optional[AuditLog]:
    """Централизованное логирование действий пользователей и системы."""
    try:
        if not description:
            if isinstance(details, str):
                description = details
            else:
                description = f"Действие: {action}"
        req_ip = None
        if request:
            # Извлекаем IP из заголовков прокси или клиента
            forwarded = request.headers.get("X-Forwarded-For")
            if forwarded:
                req_ip = forwarded.split(",")[0].strip()
            elif request.headers.get("X-Real-IP"):
                req_ip = request.headers.get("X-Real-IP")
            elif getattr(request, "client", None):
                req_ip = request.client.host

            if not user and hasattr(request, "state") and hasattr(request.state, "user"):
                user = request.state.user

        final_user_id = user_id
        final_username = username

        if user:
            final_user_id = getattr(user, "id", final_user_id)
            final_username = getattr(user, "username", final_username) or getattr(user, "name", None)

        if not final_username:
            final_username = "admin" if (user and getattr(user, "is_admin", False)) else "system"

        entry = AuditLog(
            created_at=dt.datetime.utcnow(),
            user_id=final_user_id,
            username=final_username,
            action=action,
            description=description,
            details=details,
            ip_address=req_ip,
        )
        db.add(entry)
        db.commit()
        return entry
    except Exception as exc:
        logger.warning("Failed to record audit log: %s", exc)
        try:
            db.rollback()
        except Exception:
            pass
        return None
