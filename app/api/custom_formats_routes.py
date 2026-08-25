"""
Маршруты управления кастомными форматами (Sonarr Custom Formats API).
"""

from __future__ import annotations

from typing import Optional, List, Dict, Any

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
    return db.query(CustomFormat).order_by(CustomFormat.score.desc(), CustomFormat.id.desc()).all()


@router.post("", response_model=CustomFormatOut, status_code=201)
def create_custom_format(
    payload: CustomFormatCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_settings")),
):
    from sqlalchemy import func
    existing = db.query(CustomFormat).filter(func.lower(CustomFormat.name) == payload.name.strip().lower()).first()
    if existing:
        existing.score = payload.score
        existing.include_custom_format_when_renaming = payload.include_custom_format_when_renaming
        if payload.specifications:
            existing.specifications = payload.specifications
        db.add(existing)
        db.commit()
        db.refresh(existing)
        return existing

    specs = payload.specifications
    if not specs and payload.name:
        import re
        escaped = re.escape(payload.name.strip())
        specs = [{
            "name": f"{payload.name.strip()} Pattern",
            "implementation": "ReleaseTitleSpecification",
            "negate": False,
            "required": True,
            "fields": {"value": rf"\b{escaped}\b"},
        }]

    cf = CustomFormat(
        name=payload.name.strip(),
        score=payload.score,
        include_custom_format_when_renaming=payload.include_custom_format_when_renaming,
        is_builtin=payload.is_builtin,
        specifications=specs,
    )
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
    if "name" in data and data["name"] and data["name"].strip().lower() != cf.name.lower():
        from sqlalchemy import func
        existing = db.query(CustomFormat).filter(func.lower(CustomFormat.name) == data["name"].strip().lower()).first()
        if existing and existing.id != cf.id:
            raise HTTPException(400, "Формат качества с таким названием уже существует")

    for k, v in data.items():
        if k == "specifications" and not v and ("name" in data or cf.name):
            target_name = (data.get("name") or cf.name).strip()
            import re
            escaped = re.escape(target_name)
            v = [{
                "name": f"{target_name} Pattern",
                "implementation": "ReleaseTitleSpecification",
                "negate": False,
                "required": True,
                "fields": {"value": rf"\b{escaped}\b"},
            }]
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
        raise HTTPException(400, "Штатный формат качества нельзя удалить")
    db.delete(cf)
    db.commit()
