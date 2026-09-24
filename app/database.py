from __future__ import annotations

import json
import logging
import os

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from app.models.db import Base

logger = logging.getLogger("aliasarr.database")

# По умолчанию SQLite в /config (том Docker), опционально Postgres через DATABASE_URL
def _get_default_database_url() -> str:
    url = os.getenv("DATABASE_URL")
    if url:
        return url
    if os.path.isdir("/config"):
        return "sqlite:////config/aliasarr.db"
    data_dir = os.path.join(os.getcwd(), "data")
    if os.path.isdir(data_dir):
        return f"sqlite:///{os.path.join(data_dir, 'aliasarr.db')}"
    return "sqlite:///aliasarr.db"


DATABASE_URL = _get_default_database_url()

is_sqlite = DATABASE_URL.startswith("sqlite")

if is_sqlite:
    import sqlite3
    logger.info("[DB] Initialized SQLite runtime engine v%s (WAL mode, Cache 64MB, MMAP 256MB)", getattr(sqlite3, "sqlite_version", "unknown"))
    # Для SQLite используем пул с повторным использованием соединений и оптимизированные PRAGMA:
    # 64MB RAM кэш, 256MB mmap, synchronous=NORMAL и busy_timeout=60с
    connect_args = {"check_same_thread": False, "timeout": 60}
    engine = create_engine(
        DATABASE_URL,
        connect_args=connect_args,
        pool_size=10,
        max_overflow=20,
        pool_timeout=60,
        pool_recycle=1800,
    )

    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        try:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA busy_timeout=60000")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA cache_size=-64000")      # 64 MB кэш в оперативной памяти
            cursor.execute("PRAGMA temp_store=MEMORY")      # Временные таблицы и индексы в RAM
            cursor.execute("PRAGMA mmap_size=268435456")   # 256 MB memory-mapped I/O для чтения на скорости RAM
            cursor.execute("PRAGMA foreign_keys=ON")
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
                elif isinstance(val, (list, dict)):
                    clean_json = json.dumps(val, ensure_ascii=False).replace("'", "''")
                    default_sql = f" DEFAULT '{clean_json}'"
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

    # Очищаем устаревшие 0 значения лимитов сидирования (0 трактуется как без лимита / NULL)
    try:
        with engine.begin() as conn:
            conn.execute(text("UPDATE indexers SET seed_time_limit_hours = NULL WHERE seed_time_limit_hours = 0"))
            conn.execute(text("UPDATE indexers SET seed_ratio_limit = NULL WHERE seed_ratio_limit = 0"))
    except Exception:
        pass

    # Older installations may already have received the JSON column from a
    # pre-release build without a server default.  Normalize those rows too;
    # otherwise response validation and path mapping expect a list but get NULL.
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE download_clients SET remote_path_mappings = '[]' "
                    "WHERE remote_path_mappings IS NULL "
                    "OR CAST(remote_path_mappings AS TEXT) = ''"
                )
            )
    except Exception:
        pass


def _ensure_performance_indexes() -> None:
    """Создаёт критически важные индексы для мгновенного выполнения запросов и устранения full table scan."""
    indexes = [
        ("idx_episodes_show_id", "episodes", "show_id"),
        ("idx_episodes_status", "episodes", "status"),
        ("idx_episodes_air_date", "episodes", "air_date"),
        ("idx_episodes_torrent_hash", "episodes", "torrent_hash"),
        ("idx_episodes_show_status", "episodes", "show_id, status"),
        ("idx_shows_monitored", "shows", "monitored"),
        ("idx_shows_content_type", "shows", "content_type"),
        ("idx_aliases_show_id", "aliases", "show_id"),
        ("idx_aliases_text", "aliases", "text"),
        ("idx_tracked_releases_show_id", "tracked_releases", "show_id"),
        ("idx_tracked_releases_active", "tracked_releases", "active"),
        ("idx_download_history_show_id", "download_history", "show_id"),
        ("idx_download_history_created_at", "download_history", "created_at"),
        ("idx_download_history_torrent_hash", "download_history", "torrent_hash"),
        ("idx_episodes_upgrade_requested", "episodes", "upgrade_requested"),
        ("idx_shows_upgrade_requested", "shows", "upgrade_requested"),
        ("idx_background_tasks_status_available", "background_tasks", "status, available_at"),
        ("idx_background_tasks_name_status", "background_tasks", "name, status"),
        ("idx_background_tasks_ended_at", "background_tasks", "ended_at"),
        ("idx_show_tags_tag_show", "show_tags", "tag_id, show_id"),
        ("idx_indexer_tags_tag_indexer", "indexer_tags", "tag_id, indexer_id"),
        ("idx_delay_profiles_tag_enabled", "delay_profiles", "tag_id, enabled"),
        ("idx_import_lists_enabled_due", "import_lists", "enabled, last_synced_at"),
    ]
    try:
        with engine.begin() as conn:
            for idx_name, table_name, cols in indexes:
                try:
                    conn.execute(text(f"CREATE INDEX IF NOT EXISTS {idx_name} ON {table_name}({cols})"))
                except Exception as e:
                    logger.debug("Индекс %s уже существует или таблица %s не готова: %s", idx_name, table_name, e)
            conn.execute(text(
                "CREATE UNIQUE INDEX IF NOT EXISTS ux_tracked_favorite_show_season "
                "ON tracked_releases(show_id, favorite_season)"
            ))
    except Exception as exc:
        logger.debug("Ошибка в _ensure_performance_indexes: %s", exc)


def init_db() -> None:
    try:
        if DATABASE_URL.startswith("sqlite:////config"):
            os.makedirs("/config", exist_ok=True)
    except Exception:
        pass

    if is_sqlite:
        try:
            with engine.connect() as conn:
                conn.execute(text("PRAGMA journal_mode=WAL"))
                conn.commit()
        except Exception as exc:
            logger.warning("Ошибка установки PRAGMA journal_mode=WAL: %s", exc)

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

    try:
        _ensure_performance_indexes()
    except Exception as exc:
        logger.warning("Ошибка _ensure_performance_indexes: %s", exc)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def optimize_and_checkpoint_db(db_engine=None) -> None:
    """Выполняет регламентное обслуживание SQLite: сброс WAL и оптимизацию индексов."""
    if not is_sqlite:
        return
    eng = db_engine or engine
    try:
        with eng.connect() as conn:
            conn.execute(text("PRAGMA wal_checkpoint(PASSIVE)"))
            conn.execute(text("PRAGMA optimize"))
            conn.commit()
    except Exception as exc:
        logger.debug("Ошибка optimize_and_checkpoint_db: %s", exc)
