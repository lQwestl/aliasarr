"""
Сервис резервного копирования и восстановления (Backup & Restore Service).
Поддерживает:
- Полные резервные копии всей библиотеки (Show, Episode, Alias, History) + настроек.
- Резервные копии только конфигурации (Settings, Custom Formats, Quality Profiles, Indexers, Clients, etc.).
- SQLite WAL-безопасные снимки и универсальный кроссплатформенный JSON-дамп.
- Автоматические снимки безопасности перед восстановлением (Safety Rollback Snapshot).
- Ротацию и авто-очистку устаревших копий (Retention policy).
- Уведомления и журнал аудита при операциях бэкапа.
"""

from __future__ import annotations

import datetime as dt
import io
import json
import logging
import os
import shutil
import sqlite3
import zipfile
from typing import Any, List, Optional

try:
    from sqlalchemy import inspect, text
    from sqlalchemy.orm import Session
    from app.models.db import (
        Alias,
        AppSettings,
        CustomFormat,
        DownloadClient,
        DownloadHistory,
        Episode,
        Indexer,
        MetadataSource,
        NotificationConfig,
        QualityProfile,
        Show,
        TrackedRelease,
        User,
    )
except ImportError:
    Session = Any  # type: ignore
    inspect = Any  # type: ignore
    text = Any  # type: ignore
    Alias = AppSettings = CustomFormat = DownloadClient = DownloadHistory = Episode = Indexer = MetadataSource = NotificationConfig = QualityProfile = Show = TrackedRelease = User = Any  # type: ignore

from app.services.audit_service import log_audit
from app.services.notifications import notify_all_sync
from app.services.settings_service import get_or_create_settings

logger = logging.getLogger("aliasarr.backup")

BACKUP_DIR = os.getenv("ALIASARR_BACKUP_DIR", "/config/backups")
APP_VERSION = "2.3.0"

CONFIG_TABLES = {
    "app_settings": AppSettings,
    "quality_profiles": QualityProfile,
    "custom_formats": CustomFormat,
    "indexers": Indexer,
    "download_clients": DownloadClient,
    "metadata_sources": MetadataSource,
    "notification_configs": NotificationConfig,
    "users": User,
}

LIBRARY_TABLES = {
    "shows": Show,
    "aliases": Alias,
    "episodes": Episode,
    "tracked_releases": TrackedRelease,
    "download_history": DownloadHistory,
}


def _ensure_backup_dir() -> str:
    os.makedirs(BACKUP_DIR, exist_ok=True)
    return BACKUP_DIR


def _row_to_dict(row) -> dict:
    out = {}
    for col in row.__table__.columns:
        val = getattr(row, col.name)
        if isinstance(val, (dt.datetime, dt.date)):
            val = val.isoformat()
        out[col.name] = val
    return out


def _get_sqlite_db_path() -> Optional[str]:
    """Определяет путь к файлу базы данных SQLite, если используется SQLite."""
    db_url = os.getenv("DATABASE_URL", "sqlite:////config/aliasarr.db")
    if not db_url.startswith("sqlite:"):
        return None
    # sqlite:////config/aliasarr.db -> /config/aliasarr.db
    # sqlite:///config/aliasarr.db -> config/aliasarr.db
    # sqlite:///aliasarr.db -> aliasarr.db
    raw_path = db_url.replace("sqlite:////", "/").replace("sqlite:///", "")
    if os.path.isabs(raw_path):
        return raw_path if os.path.exists(raw_path) else None
    
    # Check relative to cwd or /config
    for cand in [raw_path, os.path.join("/config", raw_path), os.path.abspath(raw_path)]:
        if os.path.exists(cand):
            return cand
    return None


def create_backup(
    db: Session,
    backup_type: str = "full",
    custom_name: Optional[str] = None,
    task: Optional[Any] = None,
) -> dict:
    """
    Создаёт резервную копию Aliasarr (полную или только настроек).
    """
    _ensure_backup_dir()
    settings = get_or_create_settings(db)
    timestamp_str = dt.datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    
    if task:
        task.update(message="Сбор статистики и данных...", progress=0.1)

    # 1. Подсчёт статистики
    stats = {
        "shows": db.query(Show).count(),
        "episodes": db.query(Episode).count(),
        "custom_formats": db.query(CustomFormat).count(),
        "quality_profiles": db.query(QualityProfile).count(),
        "indexers": db.query(Indexer).count(),
        "download_clients": db.query(DownloadClient).count(),
        "metadata_sources": db.query(MetadataSource).count(),
        "notifications": db.query(NotificationConfig).count(),
        "users": db.query(User).count(),
    }

    # 2. Формирование структуры данных
    tables_to_dump = dict(CONFIG_TABLES)
    if backup_type == "full":
        tables_to_dump.update(LIBRARY_TABLES)

    tables_data = {}
    for table_key, model_cls in tables_to_dump.items():
        try:
            rows = db.query(model_cls).all()
            tables_data[table_key] = [_row_to_dict(r) for r in rows]
        except Exception as e:
            logger.warning("Не удалось сериализовать таблицу %s: %s", table_key, e)
            tables_data[table_key] = []

    # 3. Манифест
    manifest = {
        "app": "Aliasarr",
        "version": APP_VERSION,
        "backup_type": backup_type,
        "created_at": dt.datetime.utcnow().isoformat(),
        "stats": stats,
    }

    payload = {
        "manifest": manifest,
        "app_settings": _row_to_dict(settings),
        "tables": tables_data,
    }

    # 4. Имя файла архива
    if custom_name:
        filename = custom_name if custom_name.endswith(".zip") else f"{custom_name}.zip"
    else:
        filename = f"aliasarr_backup_{backup_type}_{timestamp_str}.zip"

    archive_path = os.path.join(BACKUP_DIR, filename)

    if task:
        task.update(message="Создание zip-архива...", progress=0.5)

    # 5. Упаковка в ZIP
    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as zf:
        # manifest.json
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        # database_export.json
        zf.writestr("database_export.json", json.dumps(payload, ensure_ascii=False, indent=2))
        # settings.json (legacy compatibility)
        zf.writestr("settings.json", json.dumps(payload, ensure_ascii=False, indent=2))

        # 6. SQLite snapshot if available
        sqlite_file = _get_sqlite_db_path()
        if sqlite_file and backup_type == "full":
            try:
                # Flush WAL via checkpoint
                try:
                    db.execute(text("PRAGMA wal_checkpoint(PASSIVE);"))
                except Exception:
                    pass
                zf.write(sqlite_file, arcname="aliasarr.db")
            except Exception as exc:
                logger.warning("Не удалось упаковать бинарный файл SQLite: %s", exc)

    stat = os.stat(archive_path)
    file_size = stat.st_size

    # 7. Ротация и удаление старых копий
    retention_count = getattr(settings, "backup_retention_count", 10) or 10
    cleanup_old_backups(retention_count)

    # 8. Лог аудита и уведомление
    log_audit(db, "backup", f"Создана резервная копия ({backup_type}): {filename} ({file_size / (1024*1024):.2f} МБ)")
    try:
        notify_all_sync(
            db=None,
            event_type="backup",
            message=f"📦 Создана резервная копия Aliasarr: {filename} ({backup_type}). Размер: {file_size / (1024*1024):.2f} МБ",
        )
    except Exception:
        pass

    if task:
        task.complete(f"Бэкап создан: {filename}")

    return {
        "name": filename,
        "size_bytes": file_size,
        "created_at": dt.datetime.utcfromtimestamp(stat.st_mtime).isoformat(),
        "backup_type": backup_type,
        "app_version": APP_VERSION,
        "stats": stats,
    }


def list_backups() -> list[dict]:
    """Возвращает список всех существующих резервных копий с метаданными."""
    _ensure_backup_dir()
    out = []
    for name in sorted(os.listdir(BACKUP_DIR), reverse=True):
        if not name.endswith(".zip"):
            continue
        path = os.path.join(BACKUP_DIR, name)
        try:
            stat = os.stat(path)
            meta = inspect_backup(path)
            out.append({
                "name": name,
                "size_bytes": stat.st_size,
                "created_at": dt.datetime.utcfromtimestamp(stat.st_mtime).isoformat(),
                "backup_type": meta.get("backup_type", "full"),
                "app_version": meta.get("app_version", APP_VERSION),
                "stats": meta.get("stats", {}),
            })
        except Exception as e:
            logger.warning("Ошибка при чтении бэкапа %s: %s", name, e)
    return out


def inspect_backup(zip_path_or_bytes: str | bytes | io.BytesIO) -> dict:
    """Анализирует содержимое файла бэкапа и извлекает метаданные и статистику."""
    try:
        if isinstance(zip_path_or_bytes, str):
            zf = zipfile.ZipFile(zip_path_or_bytes, "r")
        elif isinstance(zip_path_or_bytes, bytes):
            zf = zipfile.ZipFile(io.BytesIO(zip_path_or_bytes), "r")
        else:
            zf = zipfile.ZipFile(zip_path_or_bytes, "r")

        with zf:
            file_names = set(zf.namelist())
            
            # 1. Попытка прочитать manifest.json
            if "manifest.json" in file_names:
                manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
                manifest["valid"] = True
                manifest["has_database_dump"] = "aliasarr.db" in file_names
                return manifest

            # 2. Fallback на database_export.json или settings.json
            export_name = "database_export.json" if "database_export.json" in file_names else "settings.json"
            if export_name in file_names:
                payload = json.loads(zf.read(export_name).decode("utf-8"))
                manifest = payload.get("manifest", {})
                if manifest:
                    manifest["valid"] = True
                    manifest["has_database_dump"] = "aliasarr.db" in file_names
                    return manifest
                
                # Infer stats
                tables = payload.get("tables", {})
                stats = {k: len(v) for k, v in tables.items()}
                backup_type = "full" if "shows" in tables else "config"
                return {
                    "valid": True,
                    "app": "Aliasarr",
                    "version": APP_VERSION,
                    "backup_type": backup_type,
                    "created_at": payload.get("created_at", dt.datetime.utcnow().isoformat()),
                    "stats": stats,
                    "has_database_dump": "aliasarr.db" in file_names,
                }
    except Exception as exc:
        return {"valid": False, "error": str(exc)}

    return {"valid": False, "error": "Не найден манифест или файл настроек в архиве"}


def restore_backup(
    db: Session,
    zip_path_or_bytes: str | bytes | io.BytesIO,
    mode: str = "auto",
    task: Optional[Any] = None,
) -> dict:
    """
    Восстанавливает данные из резервной копии.
    Перед восстановлением создаёт аварийный снимок отката (Safety Snapshot).
    """
    meta = inspect_backup(zip_path_or_bytes)
    if not meta.get("valid"):
        raise ValueError(f"Некорректный архив резервной копии: {meta.get('error', 'unknown error')}")

    if task:
        task.update(message="Создание защитного снимка перед восстановлением...", progress=0.1)

    # 1. Автоматический снимок безопасности перед накатом изменений
    try:
        safety_name = f"safety_snapshot_before_restore_{dt.datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.zip"
        create_backup(db, backup_type="full", custom_name=safety_name)
    except Exception as exc:
        logger.warning("Не удалось создать safety snapshot: %s", exc)

    if task:
        task.update(message="Чтение данных из бэкапа...", progress=0.3)

    if isinstance(zip_path_or_bytes, str):
        zf = zipfile.ZipFile(zip_path_or_bytes, "r")
    elif isinstance(zip_path_or_bytes, bytes):
        zf = zipfile.ZipFile(io.BytesIO(zip_path_or_bytes), "r")
    else:
        zf = zipfile.ZipFile(zip_path_or_bytes, "r")

    with zf:
        export_name = "database_export.json" if "database_export.json" in zf.namelist() else "settings.json"
        payload = json.loads(zf.read(export_name).decode("utf-8"))

    # 2. Восстановление настроек AppSettings
    if task:
        task.update(message="Восстановление настроек приложения...", progress=0.5)

    settings = get_or_create_settings(db)
    saved_api_key = settings.api_key
    app_settings_data = payload.get("app_settings", {})
    for field, value in app_settings_data.items():
        if field in ("id", "api_key"):
            continue
        if hasattr(settings, field):
            setattr(settings, field, value)
    settings.api_key = saved_api_key
    db.add(settings)

    # 3. Восстановление конфигурационных таблиц
    for key, model_cls in CONFIG_TABLES.items():
        if key == "app_settings":
            continue
        rows_data = payload.get("tables", {}).get(key, [])
        if rows_data or key in payload.get("tables", {}):
            db.query(model_cls).delete()
            for row in rows_data:
                row_dict = dict(row)
                row_dict.pop("id", None)
                _deserialize_datetime_fields(row_dict)
                db.add(model_cls(**row_dict))

    # 4. Восстановление библиотеки (если полный бэкап и режим не config_only)
    is_full_backup = (meta.get("backup_type") == "full" or "shows" in payload.get("tables", {}))
    if is_full_backup and mode != "config_only":
        if task:
            task.update(message="Восстановление медиатеки и эпизодов...", progress=0.7)
        
        # Очистка старых данных библиотеки
        for key in ("download_history", "tracked_releases", "episodes", "aliases", "shows"):
            model_cls = LIBRARY_TABLES.get(key)
            if model_cls:
                db.query(model_cls).delete()

        # Восстановление Show
        shows_data = payload.get("tables", {}).get("shows", [])
        for row in shows_data:
            r = dict(row)
            _deserialize_datetime_fields(r)
            db.add(Show(**r))
        db.flush()

        # Восстановление Aliases
        aliases_data = payload.get("tables", {}).get("aliases", [])
        for row in aliases_data:
            r = dict(row)
            _deserialize_datetime_fields(r)
            db.add(Alias(**r))

        # Восстановление Episodes
        episodes_data = payload.get("tables", {}).get("episodes", [])
        for row in episodes_data:
            r = dict(row)
            _deserialize_datetime_fields(r)
            db.add(Episode(**r))

        # Восстановление History & Tracked
        for key, model_cls in [("tracked_releases", TrackedRelease), ("download_history", DownloadHistory)]:
            items_data = payload.get("tables", {}).get(key, [])
            for row in items_data:
                r = dict(row)
                _deserialize_datetime_fields(r)
                db.add(model_cls(**r))

    db.commit()
    log_audit(db, "backup", f"Успешно восстановлена конфигурация из бэкапа ({meta.get('backup_type', 'full')})")
    
    if task:
        task.complete("Восстановление успешно завершено")

    return {
        "success": True,
        "backup_type": meta.get("backup_type"),
        "created_at": meta.get("created_at"),
        "stats": meta.get("stats", {}),
    }


def _deserialize_datetime_fields(data: dict) -> None:
    """Преобразует ISO-строки дат обратно в объекты datetime."""
    for key, val in list(data.items()):
        if isinstance(val, str) and (key.endswith("_at") or key.endswith("_date") or key == "air_date"):
            try:
                data[key] = dt.datetime.fromisoformat(val)
            except Exception:
                data[key] = None


def cleanup_old_backups(retention_count: int = 10) -> int:
    """Удаляет старые бэкапы сверх заданного лимита хранения."""
    if retention_count <= 0:
        return 0
    _ensure_backup_dir()
    zip_files = [
        os.path.join(BACKUP_DIR, f)
        for f in os.listdir(BACKUP_DIR)
        if f.endswith(".zip") and not f.startswith("safety_")
    ]
    zip_files.sort(key=lambda x: os.path.getmtime(x), reverse=True)
    
    deleted_count = 0
    if len(zip_files) > retention_count:
        to_delete = zip_files[retention_count:]
        for path in to_delete:
            try:
                os.remove(path)
                deleted_count += 1
            except Exception:
                pass
    return deleted_count


def delete_backups(names: list[str]) -> list[str]:
    """Удаляет выбранные резервные копии."""
    _ensure_backup_dir()
    deleted = []
    for name in names:
        safe_name = os.path.basename(name)
        path = os.path.join(BACKUP_DIR, safe_name)
        if os.path.isfile(path):
            try:
                os.remove(path)
                deleted.append(name)
            except Exception as e:
                logger.warning("Ошибка при удалении бэкапа %s: %s", name, e)
    return deleted


def get_backup_summary_stats(db: Session) -> dict:
    """Возвращает сводную статистику раздела бэкапов для карточек дашборда."""
    _ensure_backup_dir()
    backups = list_backups()
    total_size = sum(b.get("size_bytes", 0) for b in backups)
    latest = backups[0] if backups else None
    
    settings = get_or_create_settings(db)
    interval_days = getattr(settings, "backup_interval_days", 7) or 7
    retention_count = getattr(settings, "backup_retention_count", 10) or 10

    return {
        "total_count": len(backups),
        "total_size_bytes": total_size,
        "latest_backup": latest,
        "backup_interval_days": interval_days,
        "backup_retention_count": retention_count,
        "backup_dir": BACKUP_DIR,
    }
