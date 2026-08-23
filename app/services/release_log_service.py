from __future__ import annotations

import datetime as dt
import logging
from typing import Any, Optional

try:
    from sqlalchemy.orm import Session
    from app.database import SessionLocal
    from app.models.db import ReleaseLog
except ImportError:
    Session = object
    SessionLocal = None
    ReleaseLog = None

logger = logging.getLogger("aliasarr.release_log")


def log_release_event(
    stage: str,
    level: str,
    message: str,
    show_title: Optional[str] = None,
    show_id: Optional[int] = None,
    release_title: Optional[str] = None,
    indexer: Optional[str] = None,
    details: Optional[dict[str, Any]] = None,
    db: Optional[Session] = None,
) -> None:
    """
    Записывает событие логики релизов в базу данных.
    Работает безопасно в отдельной транзакции (если db не передан).
    """
    close_db = False
    if db is None:
        db = SessionLocal()
        close_db = True

    try:
        entry = ReleaseLog(
            created_at=dt.datetime.utcnow(),
            stage=stage,
            level=level,
            show_id=show_id,
            show_title=show_title,
            release_title=release_title,
            indexer=indexer,
            message=message[:4000],
            details=details,
        )
        db.add(entry)
        db.commit()
    except Exception as exc:
        try:
            db.rollback()
        except Exception:
            pass
        logger.debug("Ошибка записи release log: %s", exc)
    finally:
        if close_db:
            db.close()


def purge_old_release_logs(db: Session, retention_days: int = 30) -> int:
    cutoff = dt.datetime.utcnow() - dt.timedelta(days=retention_days)
    deleted = db.query(ReleaseLog).filter(ReleaseLog.created_at < cutoff).delete()
    db.commit()
    return deleted
