from __future__ import annotations

from typing import Optional, List, Dict, Any

import datetime as dt
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.db import DownloadClient, Episode, User
from app.services.user_service import require_permission, get_current_user

router = APIRouter(prefix="/api/v1/download-clients", tags=["download-clients"])


class DownloadClientIn(BaseModel):
    name: str
    type: str  # qbittorrent|transmission
    host: str
    port: int
    username: Optional[str] = None
    password: Optional[str] = None
    category: Optional[str] = "aliasarr"
    enabled: bool = True
    is_default: bool = False
    seed_time_limit: Optional[int] = None
    seed_ratio_limit: Optional[float] = None


class DownloadClientOut(DownloadClientIn):
    id: int
    is_available: Optional[bool] = None
    last_checked_at: Optional[dt.datetime] = None
    last_error: Optional[str] = None

    class Config:
        from_attributes = True


@router.get("", response_model=list[DownloadClientOut], summary="Список загрузчиков")
def list_download_clients(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Возвращает список всех настроенных клиентов загрузки (qBittorrent, Transmission) и их доступность."""
    return db.query(DownloadClient).all()


@router.post("", response_model=DownloadClientOut, status_code=201, summary="Добавить загрузчик")
def create_download_client(
    payload: DownloadClientIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_downloaders")),
):
    """Создаёт нового клиента загрузки в системе."""
    dc = DownloadClient(**payload.model_dump())
    db.add(dc)
    db.commit()
    db.refresh(dc)
    return dc


@router.delete("/{dc_id}", status_code=204, summary="Удалить загрузчик")
def delete_download_client(
    dc_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_downloaders")),
):
    """Удаляет клиента загрузки по ID."""
    dc = db.get(DownloadClient, dc_id)
    if not dc:
        raise HTTPException(404, "Download client not found")

    try:
        # Обнуляем ссылки на загрузчик в сериях
        db.query(Episode).filter(Episode.download_client_id == dc_id).update({"download_client_id": None}, synchronize_session=False)

        db.delete(dc)
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(500, f"Не удалось удалить загрузчик: {exc}")


@router.put("/{dc_id}", response_model=DownloadClientOut, summary="Обновить загрузчик")
def update_download_client(
    dc_id: int,
    payload: DownloadClientIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_downloaders")),
):
    """Обновляет настройки существующего клиента загрузки."""
    dc = db.get(DownloadClient, dc_id)
    if not dc:
        raise HTTPException(404, "Download client not found")
    for field, value in payload.model_dump().items():
        setattr(dc, field, value)
    db.add(dc)
    db.commit()
    db.refresh(dc)
    return dc


@router.post("/{dc_id}/check", summary="Проверить доступность загрузчика")
async def check_download_client_availability(
    dc_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_downloaders")),
):
    """Проверка доступности загрузчика с сохранением статуса в БД."""
    from app.services.download_client import get_client

    dc = db.get(DownloadClient, dc_id)
    if not dc:
        raise HTTPException(404, "Download client not found")

    dc.last_checked_at = dt.datetime.utcnow()
    try:
        client = get_client(dc)
        torrents = await client.list_torrents()
        dc.is_available = True
        dc.last_error = None
        db.commit()
        db.refresh(dc)
        return {
            "success": True,
            "is_available": True,
            "message": f"Загрузчик доступен, активных торрентов: {len(torrents)}",
        }
    except Exception as exc:
        err_msg = str(exc)
        dc.is_available = False
        dc.last_error = err_msg
        db.commit()
        db.refresh(dc)
        return {
            "success": False,
            "is_available": False,
            "message": f"Загрузчик недоступен: {err_msg}",
        }


@router.post("/{dc_id}/test", summary="Тест подключения к загрузчику")
async def test_download_client(
    dc_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_downloaders")),
):
    """Проверка связи: пробует авторизоваться и получить список торрентов."""
    return await check_download_client_availability(dc_id=dc_id, db=db, current_user=current_user)


@router.post("/test", summary="Тест параметров подключения загрузчика (без сохранения)")
async def test_download_client_adhoc(
    payload: DownloadClientIn,
    current_user: User = Depends(require_permission("manage_downloaders")),
):
    """Проверка связи до сохранения настроек загрузчика."""
    from app.services.download_client import get_client

    try:
        client = get_client(payload)
        torrents = await client.list_torrents()
        return {"success": True, "message": f"Подключение успешно, активных торрентов: {len(torrents)}"}
    except Exception as exc:
        return {"success": False, "message": f"Не удалось подключиться: {exc}"}

