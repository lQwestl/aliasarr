import logging
import os

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from app.models.db import Base

logger = logging.getLogger("aliasarr.database")

# По умолчанию SQLite в /config (том Docker), опционально Postgres через DATABASE_URL
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:////config/aliasarr.db")

is_sqlite = DATABASE_URL.startswith("sqlite")

if is_sqlite:
    # Для SQLite используем NullPool (исключает QueuePool timeout) и включаем WAL-режим
    # с busy_timeout=60000 мс (60 сек) для бесконфликтной многопоточной работы
    connect_args = {"check_same_thread": False, "timeout": 60}
    engine = create_engine(
        DATABASE_URL,
        connect_args=connect_args,
        poolclass=NullPool,
    )

    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        try:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=60000")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.close()
        except Exception:
            pass
else:
    engine = create_engine(
        DATABASE_URL,
        pool_size=20,
        max_overflow=30,
        pool_timeout=60,
        pool_pre_ping=True,
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def _migrate_add_missing_columns() -> None:
    """
    Лёгкая "миграция без Alembic": на существующей базе (созданной прежней версией
    приложения) сравниваем колонки, которые ожидает текущая модель
    (`app/models/db.py`), с тем, что реально есть в таблицах БД, и добавляем
    недостающие через `ALTER TABLE ... ADD COLUMN`.
    Каждая колонка мигрируется в изолированной транзакции.
    """
    try:
        inspector = inspect(engine)
        existing_tables = set(inspector.get_table_names())
    except Exception as exc:
        logger.warning("DB-миграция: не удалось получить список таблиц: %s", exc)
        return

    for table in Base.metadata.sorted_tables:
        if table.name not in existing_tables:
            continue  # новая таблица — её создаст create_all()

        try:
            inspector = inspect(engine)
            existing_columns = {col["name"] for col in inspector.get_columns(table.name)}
        except Exception:
            existing_columns = set()

        for column in table.columns:
            if column.name in existing_columns:
                continue
            try:
                col_type = column.type.compile(dialect=engine.dialect)
            except Exception:
                col_type = "TEXT"

            default_sql = ""
            val = None
            if column.default is not None:
                arg = getattr(column.default, "arg", None)
                if callable(arg):
                    try:
                        val = arg(None)
                    except Exception:
                        val = None
                else:
                    val = arg

            if val is not None:
                if isinstance(val, bool):
                    default_sql = f" DEFAULT {1 if val else 0}"
                elif isinstance(val, (int, float)):
                    default_sql = f" DEFAULT {val}"
                elif isinstance(val, str):
                    clean_str = str(val).replace("'", "''")
                    default_sql = f" DEFAULT '{clean_str}'"
            elif not column.nullable:
                if "INT" in str(col_type).upper() or "BOOL" in str(col_type).upper():
                    default_sql = " DEFAULT 0"
                elif "FLOAT" in str(col_type).upper() or "NUMERIC" in str(col_type).upper():
                    default_sql = " DEFAULT 0.0"
                else:
                    default_sql = " DEFAULT ''"

            ddl = f"ALTER TABLE {table.name} ADD COLUMN {column.name} {col_type}{default_sql}"
            try:
                with engine.begin() as conn:
                    conn.execute(text(ddl))
                logger.info("DB-миграция: добавлена колонка %s.%s (%s)", table.name, column.name, default_sql.strip())
            except Exception as exc:
                logger.warning("DB-миграция: не удалось добавить %s.%s (%s)", table.name, column.name, exc)


def init_db() -> None:
    try:
        if DATABASE_URL.startswith("sqlite:////config"):
            os.makedirs("/config", exist_ok=True)
    except Exception:
        pass

    try:
        Base.metadata.create_all(bind=engine)
    except Exception as exc:
        logger.warning("Ошибка Base.metadata.create_all: %s", exc)

    try:
        _migrate_add_missing_columns()
    except Exception as exc:
        logger.warning("Ошибка _migrate_add_missing_columns: %s", exc)

    try:
        Base.metadata.create_all(bind=engine)
    except Exception as exc:
        logger.warning("Ошибка повторного Base.metadata.create_all: %s", exc)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
