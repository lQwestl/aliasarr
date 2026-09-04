from __future__ import annotations

import datetime as dt
import io
import json
import logging
import os
import zipfile
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.db import (
    AppSettings,
    DownloadClient,
    Indexer,
    LogEntry,
    MetadataSource,
    NotificationConfig,
    QualityProfile,
    User,
)
from app.services.log_service import purge_old_logs
from app.services.settings_service import get_or_create_settings
from app.services.user_service import require_permission, require_any_permission, get_current_user

import platform
import sqlite3
import sys
import time

router = APIRouter(prefix="/api/v1", tags=["system"])
logger = logging.getLogger("aliasarr.system")

BACKUP_DIR = os.getenv("ALIASARR_BACKUP_DIR", "/config/backups")
APP_START_TIME = time.time()


@router.get("/system/about")
def get_system_about(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_permission("view_dashboard", "manage_settings")),
):
    """
    Информация о программе и среде выполнения (как About в Sonarr/Radarr):
    версия, сборка, рантайм, ОС, база данных, аптайм, пути и режим работы.
    """
    settings = get_or_create_settings(db)

    from app.services.backup_service import _get_sqlite_db_path
    db_path = _get_sqlite_db_path() or "/config/aliasarr.db"
    db_size_bytes = os.path.getsize(db_path) if (db_path and os.path.exists(db_path)) else 0

    if db_size_bytes >= 1024 * 1024 * 1024:
        db_size_fmt = f"{db_size_bytes / (1024 ** 3):.2f} GB"
    elif db_size_bytes >= 1024 * 1024:
        db_size_fmt = f"{db_size_bytes / (1024 ** 2):.1f} MB"
    elif db_size_bytes > 0:
        db_size_fmt = f"{db_size_bytes / 1024:.1f} KB"
    else:
        db_size_fmt = "0 B"

    uptime_sec = int(time.time() - APP_START_TIME)
    days, rem = divmod(uptime_sec, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, _ = divmod(rem, 60)

    uptime_ru_parts = []
    if days > 0:
        uptime_ru_parts.append(f"{days} дн.")
    if hours > 0 or days > 0:
        uptime_ru_parts.append(f"{hours} ч.")
    uptime_ru_parts.append(f"{minutes} мин.")
    uptime_ru = " ".join(uptime_ru_parts)

    uptime_en_parts = []
    if days > 0:
        uptime_en_parts.append(f"{days}d")
    if hours > 0 or days > 0:
        uptime_en_parts.append(f"{hours}h")
    uptime_en_parts.append(f"{minutes}m")
    uptime_en = " ".join(uptime_en_parts)

    is_docker = os.path.exists("/.dockerenv") or os.environ.get("DOCKER_CONTAINER") == "true" or os.path.exists("/app/run.py")
    is_ssl = getattr(settings, "ssl_enabled", False)
    port = int(os.getenv("PORT", getattr(settings, "ssl_port", 8989) if is_ssl else 8989))

    py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    arch = platform.machine()
    os_sys = platform.system()

    return {
        "app_name": "Aliasarr",
        "version": "2.1.0",
        "package_version": "2.1.0 (main)",
        "branch": "main",
        "python_version": py_ver,
        "os_name": os_sys,
        "os_version": f"{os_sys} {platform.release()}",
        "architecture": arch,
        "is_docker": is_docker,
        "runtime": f"Docker (Linux {arch})" if is_docker else f"{os_sys} ({arch})",
        "database_type": "SQLite",
        "database_version": sqlite3.sqlite_version,
        "database_path": db_path,
        "database_size_bytes": db_size_bytes,
        "database_size_formatted": db_size_fmt,
        "config_directory": "/config" if (is_docker or os.path.exists("/config")) else os.path.abspath("./config"),
        "uptime_seconds": uptime_sec,
        "uptime_formatted": uptime_ru,
        "uptime_formatted_en": uptime_en,
        "timezone": settings.timezone or "UTC",
        "ssl_enabled": is_ssl,
        "mode": f"HTTPS (порт {port})" if is_ssl else f"HTTP (порт {port})",
        "mode_en": f"HTTPS (port {port})" if is_ssl else f"HTTP (port {port})",
        "port": port,
        "authentication": "Форма входа" if getattr(settings, "login_enabled", True) else "Отключена",
    }


# ---------------------------------------------------------------------------
# Журнал и события системы
# ---------------------------------------------------------------------------

EVENT_LEVELS = ["info", "warning", "error"]
JOURNAL_LEVELS = ["debug", "info", "warning", "error"]


class LogEntryOut(BaseModel):
    id: int
    created_at: dt.datetime
    level: str
    component: str
    message: str

    class Config:
        from_attributes = True


class LogsPageOut(BaseModel):
    items: list[LogEntryOut]
    total: int
    page: int
    page_size: int


def _query_logs(db: Session, levels: Optional[list[str]], page: int, page_size: int, sort: str):
    q = db.query(LogEntry)
    if levels:
        q = q.filter(LogEntry.level.in_(levels))
    total = q.count()
    order_col = LogEntry.created_at.desc() if sort != "asc" else LogEntry.created_at.asc()
    items = q.order_by(order_col).offset((page - 1) * page_size).limit(page_size).all()
    return items, total


@router.get("/events", response_model=LogsPageOut)
def list_events(
    level: str = "all",
    page: int = 1,
    page_size: int = 50,
    sort: str = "desc",
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("view_events")),
):
    """Раздел "События": все | Информация | Предупреждения | Ошибки."""
    levels = None if level == "all" else [level]
    if levels and levels[0] not in EVENT_LEVELS:
        raise HTTPException(400, "Некорректный уровень события")
    items, total = _query_logs(db, levels or EVENT_LEVELS, page, max(1, page_size), sort)
    return LogsPageOut(items=items, total=total, page=page, page_size=page_size)


@router.get("/journal", response_model=LogsPageOut)
def list_journal(
    level: str = "all",
    search: Optional[str] = None,
    page: int = 1,
    page_size: int = 100,
    sort: str = "desc",
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("view_journal")),
):
    """Раздел "Журнал": info/warn/debug/error логи самого приложения."""
    levels = None if level == "all" else [level]
    if levels and levels[0] not in JOURNAL_LEVELS:
        raise HTTPException(400, "Некорректный уровень лога")
    
    q = db.query(LogEntry)
    if levels:
        q = q.filter(LogEntry.level.in_(levels))
    elif JOURNAL_LEVELS:
        q = q.filter(LogEntry.level.in_(JOURNAL_LEVELS))
        
    if search and search.strip():
        term = f"%{search.strip()}%"
        q = q.filter(
            or_(
                LogEntry.message.ilike(term),
                LogEntry.component.ilike(term),
            )
        )
        
    total = q.count()
    order_col = LogEntry.created_at.desc() if sort != "asc" else LogEntry.created_at.asc()
    items = q.order_by(order_col).offset((page - 1) * page_size).limit(page_size).all()
    return LogsPageOut(items=items, total=total, page=page, page_size=page_size)


@router.get("/journal/download")
def download_journal(
    level: str = "all",
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_journal")),
):
    levels = None if level == "all" else [level]
    q = db.query(LogEntry).filter(LogEntry.level.in_(levels or JOURNAL_LEVELS))
    rows = q.order_by(LogEntry.created_at.asc()).all()
    lines = [
        f"{r.created_at.isoformat()}  [{r.level.upper():7}]  {r.component}: {r.message}"
        for r in rows
    ]
    content = "\n".join(lines) + "\n"
    filename = f"aliasarr_journal_{dt.datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.txt"
    return Response(
        content=content,
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.delete("/journal")
def clear_journal(
    mode: str = "all",  # "all" or "debug"
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_journal")),
):
    """Очистка журнала: mode='all' (все логи) или mode='debug' (только debug)."""
    if mode == "debug":
        deleted = db.query(LogEntry).filter(LogEntry.level == "debug").delete()
    else:
        deleted = db.query(LogEntry).delete()
    db.commit()
    return {"success": True, "deleted": deleted}


@router.post("/journal/purge-old")
def purge_journal(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_journal")),
):
    settings = get_or_create_settings(db)
    deleted = purge_old_logs(db, settings.log_retention_days or 14)
    return {"deleted": deleted}


# ---------------------------------------------------------------------------
# Backup & Restore (Современное резервное копирование и восстановление)
# ---------------------------------------------------------------------------

from app.services.backup_service import (
    BACKUP_DIR,
    create_backup as service_create_backup,
    delete_backups as service_delete_backups,
    get_backup_summary_stats,
    inspect_backup as service_inspect_backup,
    list_backups as service_list_backups,
    restore_backup as service_restore_backup,
)


class BackupStatsOut(BaseModel):
    shows: int = 0
    episodes: int = 0
    custom_formats: int = 0
    quality_profiles: int = 0
    indexers: int = 0
    download_clients: int = 0
    metadata_sources: int = 0
    notifications: int = 0
    users: int = 0


class BackupOut(BaseModel):
    name: str
    size_bytes: int
    created_at: dt.datetime
    backup_type: str = "full"
    app_version: str = "2.1.0"
    stats: Optional[dict] = None


class BackupCreateIn(BaseModel):
    backup_type: str = "full"  # "full" | "config"


class BackupSummaryStatsOut(BaseModel):
    total_count: int
    total_size_bytes: int
    latest_backup: Optional[BackupOut] = None
    backup_interval_days: int = 7
    backup_retention_count: int = 10
    backup_dir: str


@router.get("/backups", response_model=list[BackupOut])
def list_backups(current_user: User = Depends(require_permission("manage_backups"))):
    return service_list_backups()


@router.get("/backups/stats", response_model=BackupSummaryStatsOut)
def get_backups_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_backups")),
):
    return get_backup_summary_stats(db)


@router.post("/backups", response_model=BackupOut, status_code=201)
def create_backup(
    payload: Optional[BackupCreateIn] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_backups")),
):
    from app.services.task_manager import task_manager
    b_type = payload.backup_type if payload else "full"
    type_title = "Полный бэкап" if b_type == "full" else "Бэкап настроек"
    with task_manager.track_sync("backup_create", f"Создание бэкапа ({type_title})", "Сбор данных и упаковка...") as b_task:
        result = service_create_backup(db, backup_type=b_type, task=b_task)
        return result


@router.get("/backups/{name}/download")
def download_backup(name: str, current_user: User = Depends(require_permission("manage_backups"))):
    safe_name = os.path.basename(name)
    path = os.path.join(BACKUP_DIR, safe_name)
    if not os.path.isfile(path):
        raise HTTPException(404, "Резервная копия не найдена")
    with open(path, "rb") as f:
        data = f.read()
    return Response(
        content=data, media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}"'},
    )


@router.get("/backups/{name}/inspect")
def inspect_existing_backup(name: str, current_user: User = Depends(require_permission("manage_backups"))):
    safe_name = os.path.basename(name)
    path = os.path.join(BACKUP_DIR, safe_name)
    if not os.path.isfile(path):
        raise HTTPException(404, "Резервная копия не найдена")
    meta = service_inspect_backup(path)
    if not meta.get("valid"):
        raise HTTPException(400, meta.get("error", "Некорректный бэкап"))
    return meta


@router.post("/backups/inspect")
async def inspect_uploaded_backup(
    file: UploadFile = File(...),
    current_user: User = Depends(require_permission("manage_backups")),
):
    try:
        raw = await file.read()
        meta = service_inspect_backup(raw)
        if not meta.get("valid"):
            raise HTTPException(400, meta.get("error", "Некорректный файл резервной копии"))
        return meta
    except Exception as exc:
        raise HTTPException(400, f"Ошибка чтения файла: {exc}")


class RestoreExistingIn(BaseModel):
    name: str
    mode: str = "auto"  # "auto" | "full" | "config_only"


@router.post("/backups/restore-existing")
def restore_existing_backup(
    payload: RestoreExistingIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_backups")),
):
    from app.services.task_manager import task_manager
    safe_name = os.path.basename(payload.name)
    path = os.path.join(BACKUP_DIR, safe_name)
    if not os.path.isfile(path):
        raise HTTPException(404, "Резервная копия не найдена")

    with task_manager.track_sync("backup_restore", f"Восстановление бэкапа: {safe_name}", "Применение данных...") as r_task:
        res = service_restore_backup(db, path, mode=payload.mode, task=r_task)
        return res


@router.post("/backups/restore")
async def restore_backup(
    file: UploadFile = File(...),
    mode: str = "auto",
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_backups")),
):
    from app.services.task_manager import task_manager
    try:
        raw = await file.read()
    except Exception as exc:
        raise HTTPException(400, f"Не удалось прочитать файл: {exc}")

    with task_manager.track_sync("backup_restore", f"Восстановление бэкапа: {file.filename}", "Применение данных...") as r_task:
        try:
            res = service_restore_backup(db, raw, mode=mode, task=r_task)
            return res
        except Exception as exc:
            logger.error("Ошибка восстановления: %s", exc, exc_info=True)
            raise HTTPException(400, f"Ошибка восстановления: {exc}")


class DeleteBackupsIn(BaseModel):
    names: list[str]


@router.delete("/backups")
def delete_backups(
    payload: DeleteBackupsIn,
    current_user: User = Depends(require_permission("manage_backups")),
):
    deleted = service_delete_backups(payload.names)
    return {"deleted": deleted}


# ---------------------------------------------------------------------------
# Обзор файловой системы
# ---------------------------------------------------------------------------

class DirEntryOut(BaseModel):
    name: str
    path: str


class BrowseDirOut(BaseModel):
    path: str
    parent: Optional[str]
    directories: list[DirEntryOut]


@router.get("/filesystem/browse", response_model=BrowseDirOut)
def browse_filesystem(
    path: str = "/",
    current_user: User = Depends(require_any_permission("manage_settings", "manage_library")),
):
    target = os.path.normpath(path or "/")
    if not target.startswith("/"):
        target = "/" + target
    if not os.path.isdir(target):
        raise HTTPException(404, f"Папка не найдена: {target}")

    try:
        entries = sorted(os.listdir(target))
    except PermissionError:
        raise HTTPException(403, f"Нет доступа к папке: {target}")

    directories = []
    for name in entries:
        if name.startswith("."):
            continue
        full = os.path.join(target, name)
        if os.path.isdir(full):
            directories.append(DirEntryOut(name=name, path=full))

    parent = os.path.dirname(target) if target != "/" else None
    return BrowseDirOut(path=target, parent=parent, directories=directories)


class CreateDirIn(BaseModel):
    path: str


@router.post("/filesystem/mkdir")
def create_directory(
    payload: CreateDirIn,
    current_user: User = Depends(require_permission("manage_settings")),
):
    """Создать новую папку прямо из окна выбора директории (удобно, если нужной
    папки ещё не существует)."""
    target = os.path.normpath(payload.path or "")
    if not target.startswith("/"):
        raise HTTPException(400, "Путь должен быть абсолютным")
    try:
        os.makedirs(target, exist_ok=True)
        from app.services.postprocess import apply_media_permissions
        apply_media_permissions(target, is_dir=True)
    except OSError as exc:
        raise HTTPException(400, f"Не удалось создать папку: {exc}")
    return {"success": True, "path": target}


@router.post("/system/fix-media-permissions")
def fix_all_media_permissions(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_settings")),
):
    """
    Принудительно рекурсивно устанавливает права доступа (0777 для папок, 0666 для файлов)
    на всех корневых директориях медиатеки и во всех существующих папках тайтлов.
    """
    from app.services.postprocess import apply_media_permissions, get_show_default_path
    from app.models.db import Show

    settings = get_or_create_settings(db)
    roots = set()
    for r in [settings.root_folder, settings.root_folder_movies, settings.root_folder_series, settings.root_folder_anime]:
        if r and os.path.isdir(r):
            roots.add(os.path.abspath(r))

    shows = db.query(Show).all()
    for s in shows:
        sp = s.path or get_show_default_path(s, settings)
        if sp and os.path.isdir(sp):
            roots.add(os.path.abspath(sp))

    total_dirs = 0
    total_files = 0
    for r in roots:
        stats = apply_media_permissions(r, is_dir=True, recursive=True)
        total_dirs += stats.get("dirs", 0)
        total_files += stats.get("files", 0)

    return {
        "success": True,
        "roots_processed": len(roots),
        "dirs_fixed": total_dirs,
        "files_fixed": total_files,
        "message": f"Права доступа обновлены для {len(roots)} путей ({total_dirs} папок, {total_files} файлов)",
    }

