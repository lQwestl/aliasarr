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

router = APIRouter(prefix="/api/v1", tags=["system"])
logger = logging.getLogger("aliasarr.system")

BACKUP_DIR = os.getenv("ALIASARR_BACKUP_DIR", "/config/backups")


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


def _query_logs(db: Session, levels: list[str] | None, page: int, page_size: int, sort: str):
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
    page: int = 1,
    page_size: int = 100,
    sort: str = "desc",
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("view_journal")),
):
    """Раздел "Журнал": info/warn/debug логи самого приложения."""
    levels = None if level == "all" else [level]
    if levels and levels[0] not in JOURNAL_LEVELS:
        raise HTTPException(400, "Некорректный уровень лога")
    items, total = _query_logs(db, levels or JOURNAL_LEVELS, page, max(1, page_size), sort)
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
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_journal")),
):
    # Удаляем только debug логи, чтобы не стирать важные события (info, warning, error)
    db.query(LogEntry).filter(LogEntry.level == "debug").delete()
    db.commit()
    return {"success": True}


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
    app_version: str = "2.0.0"
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
    parent: str | None
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
    except OSError as exc:
        raise HTTPException(400, f"Не удалось создать папку: {exc}")
    return {"success": True, "path": target}

