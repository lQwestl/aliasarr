"""
Захват и сохранение логов приложения в базе данных для системного журнала и событий.

Подключается как специализированный logging.Handler к логгеру "aliasarr" и его подсистемам.
"""

from __future__ import annotations

import datetime as dt
import logging

from app.database import SessionLocal

_LEVEL_MAP = {
    logging.DEBUG: "debug",
    logging.INFO: "info",
    logging.WARNING: "warning",
    logging.ERROR: "error",
    logging.CRITICAL: "error",
}


class DBLogHandler(logging.Handler):
    """Пишет каждую запись лога в таблицу log_entries отдельной короткой транзакцией."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            from app.models.db import LogEntry  # локальный импорт — избегаем циклических импортов

            level = _LEVEL_MAP.get(record.levelno, "info")
            message = self.format(record) if self.formatter else record.getMessage()
            
            # Защита от утечки секретов и API-ключей в журнал логов
            if "API-ключ (из " in message or "X-Api-Key:" in message:
                message = "Системный API-ключ инициализирован (секрет скрыт)"

            db = SessionLocal()
            try:
                db.add(LogEntry(
                    created_at=dt.datetime.utcnow(),
                    level=level,
                    component=record.name,
                    message=message[:4000],
                ))
                db.commit()
            finally:
                db.close()
        except Exception:
            # Логирование никогда не должно ронять приложение
            pass


def install_db_log_handler() -> None:
    handler = DBLogHandler(level=logging.DEBUG)
    handler.setFormatter(logging.Formatter("%(message)s"))
    for name in ("aliasarr",):
        logging.getLogger(name).addHandler(handler)
        logging.getLogger(name).setLevel(logging.DEBUG)


def sanitize_legacy_log_entries(db) -> None:
    """Очищает устаревшие записи логов, в которых мог содержаться сырой API-ключ."""
    from app.models.db import LogEntry
    try:
        entries = db.query(LogEntry).filter(
            (LogEntry.message.like("%API-ключ (из %")) |
            (LogEntry.message.like("%X-Api-Key:%"))
        ).all()
        for e in entries:
            e.message = "Системный API-ключ инициализирован (секрет скрыт)"
        db.commit()
    except Exception:
        db.rollback()


def purge_old_logs(db, retention_days: int = 14) -> int:
    from app.models.db import LogEntry

    cutoff = dt.datetime.utcnow() - dt.timedelta(days=retention_days)
    deleted = db.query(LogEntry).filter(LogEntry.created_at < cutoff).delete()
    db.commit()
    return deleted
