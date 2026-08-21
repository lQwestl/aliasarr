"""
Маршруты управления кастомными форматами (Sonarr Custom Formats API).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.db import CustomFormat, User
from app.schemas import CustomFormatCreate, CustomFormatOut, CustomFormatUpdate
from app.services.custom_formats import (
    DEFAULT_FORMAT_NAMES,
    reset_custom_format_to_default,
    seed_default_custom_formats,
)
from app.services.user_service import get_current_user, require_permission

router = APIRouter(prefix="/api/v1/custom-formats", tags=["custom_formats"])


@router.get("", response_model=list[CustomFormatOut])
def list_custom_formats(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    seed_default_custom_formats(db)
    return db.query(CustomFormat).all()


@router.post("", response_model=CustomFormatOut, status_code=201)
def create_custom_format(
    payload: CustomFormatCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_settings")),
):
    existing = db.query(CustomFormat).filter(CustomFormat.name == payload.name).first()
    if existing:
        raise HTTPException(400, "Custom format with this name already exists")

    cf = CustomFormat(**payload.model_dump())
    db.add(cf)
    db.commit()
    db.refresh(cf)
    return cf


@router.get("/{format_id}", response_model=CustomFormatOut)
def get_custom_format(
    format_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cf = db.get(CustomFormat, format_id)
    if not cf:
        raise HTTPException(404, "Custom format not found")
    return cf


@router.put("/{format_id}", response_model=CustomFormatOut)
def update_custom_format(
    format_id: int,
    payload: CustomFormatUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_settings")),
):
    cf = db.get(CustomFormat, format_id)
    if not cf:
        raise HTTPException(404, "Custom format not found")

    data = payload.model_dump(exclude_unset=True)
    if "name" in data and data["name"] != cf.name:
        existing = db.query(CustomFormat).filter(CustomFormat.name == data["name"]).first()
        if existing:
            raise HTTPException(400, "Custom format with this name already exists")

    for k, v in data.items():
        setattr(cf, k, v)

    db.add(cf)
    db.commit()
    db.refresh(cf)
    return cf


@router.post("/{format_id}/reset", response_model=CustomFormatOut)
def reset_custom_format(
    format_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_settings")),
):
    cf = db.get(CustomFormat, format_id)
    if not cf:
        raise HTTPException(404, "Custom format not found")

    if not reset_custom_format_to_default(cf):
        raise HTTPException(400, f"Формат '{cf.name}' не является штатным и не может быть сброшен")

    db.add(cf)
    db.commit()
    db.refresh(cf)
    return cf


@router.delete("/{format_id}", status_code=204)
def delete_custom_format(
    format_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_settings")),
):
    cf = db.get(CustomFormat, format_id)
    if not cf:
        raise HTTPException(404, "Custom format not found")
    if getattr(cf, "is_builtin", False) or cf.name in DEFAULT_FORMAT_NAMES:
        raise HTTPException(400, "Штатный кастомный формат нельзя удалить")
    db.delete(cf)
    db.commit()
