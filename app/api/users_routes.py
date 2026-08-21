from __future__ import annotations

import secrets
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.db import User
from app.services.audit_service import log_audit
from app.services.settings_service import get_or_create_settings, hash_password
from app.services.user_service import ALL_PERMISSIONS, require_permission

router = APIRouter(prefix="/api/v1/users", tags=["users"])


class UserCreate(BaseModel):
    username: str
    password: str
    display_name: str | None = None
    is_admin: bool = False
    permissions: dict[str, bool] | None = None
    enabled: bool = True
    session_timeout_minutes: int | None = 43200


class UserUpdate(BaseModel):
    display_name: str | None = None
    is_admin: bool | None = None
    permissions: dict[str, bool] | None = None
    enabled: bool | None = None
    session_timeout_minutes: int | None = None


class UserPasswordReset(BaseModel):
    new_password: str


class UserAvatarSet(BaseModel):
    avatar: str | None = None


def _format_user(u: User, viewer: User | None = None) -> dict[str, Any]:
    perms = u.permissions or {}
    if u.is_admin:
        perms = {perm: True for perm in ALL_PERMISSIONS}
    can_use_api_key = bool(u.is_owner or u.is_admin or perms.get("use_api_key"))
    
    # Пользователи не могут видеть api-key друг друга, кроме главного администратора (is_owner)
    api_key_val = None
    if viewer and (viewer.is_owner or viewer.id == u.id) and can_use_api_key:
        api_key_val = u.api_key

    return {
        "id": u.id,
        "username": u.username,
        "display_name": u.display_name or u.username,
        "is_admin": u.is_admin,
        "is_owner": u.is_owner,
        "avatar": u.avatar,
        "permissions": perms,
        "enabled": u.enabled,
        "session_timeout_minutes": getattr(u, "session_timeout_minutes", 43200) or 43200,
        "has_api_key": bool(u.api_key),
        "can_use_api_key": can_use_api_key,
        "api_key": api_key_val,
        "totp_enabled": bool(getattr(u, "totp_enabled", False)),
        "totp_confirmed_at": u.totp_confirmed_at.isoformat() if getattr(u, "totp_confirmed_at", None) else None,
        "created_at": u.created_at.isoformat() if u.created_at else None,
        "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
    }


@router.get("")
def list_users(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_users")),
):
    users = db.query(User).order_by(User.id.asc()).all()
    return [_format_user(u, viewer=current_user) for u in users]


@router.post("", status_code=201)
def create_user(
    payload: UserCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_users")),
):
    uname = payload.username.strip()
    if not uname:
        raise HTTPException(400, "Имя пользователя обязательно")
    if len(payload.password) < 4:
        raise HTTPException(400, "Пароль должен содержать минимум 4 символа")

    existing = db.query(User).filter(User.username == uname).first()
    if existing:
        raise HTTPException(409, f"Пользователь '{uname}' уже существует")

    perms = payload.permissions or {}
    if payload.is_admin:
        perms = {perm: True for perm in ALL_PERMISSIONS}

    new_user = User(
        username=uname,
        password_hash=hash_password(payload.password),
        display_name=payload.display_name or uname,
        is_admin=payload.is_admin,
        is_owner=False,
        permissions=perms,
        enabled=payload.enabled,
        session_timeout_minutes=payload.session_timeout_minutes or 43200,
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    log_audit(
        db,
        action="user.create",
        description=f"Создан пользователь '{new_user.username}' (роль: {'Admin' if new_user.is_admin else 'User'})",
        user=current_user,
        request=request,
        details={"created_user_id": new_user.id, "created_username": new_user.username},
    )
    return _format_user(new_user, viewer=current_user)


@router.get("/{user_id}")
def get_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_users")),
):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, "Пользователь не найден")
    return _format_user(user, viewer=current_user)


@router.put("/{user_id}")
def update_user(
    user_id: int,
    payload: UserUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_users")),
):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, "Пользователь не найден")

    # Главного администратора (is_owner) может редактировать ТОЛЬКО он сам
    if user.is_owner and not current_user.is_owner:
        raise HTTPException(403, "Другие пользователи и администраторы не могут изменять данные главного администратора")

    if user.is_owner:
        if payload.is_admin is False or payload.enabled is False:
            raise HTTPException(400, "Нельзя отключить или ограничить главного администратора")

    # Пользователи и назначенные администраторы не могут изменять сами себе роль и права доступа
    if current_user.id == user.id and not current_user.is_owner:
        if payload.is_admin is not None and payload.is_admin != user.is_admin:
            raise HTTPException(400, "Вы не можете изменять собственную роль администратора")
        if payload.permissions is not None and payload.permissions != (user.permissions or {}):
            raise HTTPException(400, "Вы не можете изменять собственные права доступа")
        if payload.enabled is False:
            raise HTTPException(400, "Вы не можете отключить собственную учётную запись")

    if payload.display_name is not None:
        user.display_name = payload.display_name.strip() or user.username
    if payload.is_admin is not None and not user.is_owner and current_user.id != user.id:
        user.is_admin = payload.is_admin
    if payload.permissions is not None and (current_user.id != user.id or current_user.is_owner):
        user.permissions = payload.permissions
    if payload.enabled is not None and not user.is_owner and current_user.id != user.id:
        user.enabled = payload.enabled
    if payload.session_timeout_minutes is not None and payload.session_timeout_minutes > 0:
        user.session_timeout_minutes = payload.session_timeout_minutes

    db.commit()
    db.refresh(user)

    log_audit(
        db,
        action="user.update",
        description=f"Обновлены параметры пользователя '{user.username}'",
        user=current_user,
        request=request,
        details={"target_user_id": user.id},
    )
    return _format_user(user, viewer=current_user)


@router.post("/{user_id}/reset-password")
def reset_user_password(
    user_id: int,
    payload: UserPasswordReset,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_users")),
):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, "Пользователь не найден")

    # Другие пользователи и администраторы НЕ могут сменить пароль главному администратору
    if user.is_owner and not current_user.is_owner:
        raise HTTPException(403, "Другие пользователи и администраторы не могут менять пароль главному администратору")

    if len(payload.new_password) < 4:
        raise HTTPException(400, "Пароль должен содержать не менее 4 символов")

    new_hash = hash_password(payload.new_password)
    user.password_hash = new_hash
    if user.is_owner:
        settings = get_or_create_settings(db)
        settings.password_hash = new_hash
    db.commit()

    log_audit(
        db,
        action="user.password_reset",
        description=f"Администратор сбросил пароль пользователю '{user.username}'",
        user=current_user,
        request=request,
        details={"target_user_id": user.id},
    )
    return {"success": True, "message": f"Пароль пользователя '{user.username}' успешно обновлён"}


@router.delete("/{user_id}", status_code=204)
def delete_user(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_users")),
):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, "Пользователь не найден")

    if user.is_owner:
        raise HTTPException(400, "Нельзя удалить главного администратора системы")

    if user.id == current_user.id:
        raise HTTPException(400, "Вы не можете удалить свою собственную учётную запись")

    uname = user.username
    db.delete(user)
    db.commit()

    log_audit(
        db,
        action="user.delete",
        description=f"Удалён пользователь '{uname}' (id={user_id})",
        user=current_user,
        request=request,
        details={"deleted_user_id": user_id, "deleted_username": uname},
    )


@router.post("/{user_id}/avatar")
def set_user_avatar(
    user_id: int,
    payload: UserAvatarSet,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_users")),
):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, "Пользователь не найден")

    user.avatar = payload.avatar
    db.add(user)
    db.commit()
    db.refresh(user)

    log_audit(
        db,
        action="user.avatar_update",
        description=f"Обновлен аватар пользователя '{user.username}'",
        user=current_user,
        request=request,
        details={"target_user_id": user.id},
    )
    return {"success": True, "avatar": user.avatar}


@router.post("/{user_id}/regenerate-api-key")
def regenerate_user_api_key(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_users")),
):
    # Только главный администратор может генерировать ключи другим пользователям
    if not current_user.is_owner:
        raise HTTPException(403, "Только главный администратор может генерировать API-ключи другим пользователям")

    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, "Пользователь не найден")

    new_key = secrets.token_hex(32)
    user.api_key = new_key
    db.commit()
    db.refresh(user)

    log_audit(
        db,
        action="user.admin_regenerate_api_key",
        description=f"Главный администратор сгенерировал новый API-ключ для пользователя '{user.username}'",
        user=current_user,
        request=request,
        details={"target_user_id": user.id},
    )
    return {"api_key": user.api_key, "has_key": True}


@router.delete("/{user_id}/revoke-api-key")
def revoke_user_api_key(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_users")),
):
    # Только главный администратор может отзывать ключи у других пользователей
    if not current_user.is_owner:
        raise HTTPException(403, "Только главный администратор может отзывать API-ключи у других пользователей")

    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, "Пользователь не найден")

    user.api_key = None
    db.commit()
    db.refresh(user)

    log_audit(
        db,
        action="user.admin_revoke_api_key",
        description=f"Главный администратор отозвал API-ключ у пользователя '{user.username}'",
        user=current_user,
        request=request,
        details={"target_user_id": user.id},
    )
    return {"success": True, "has_key": False}


class AdminConfirm2FARequest(BaseModel):
    secret: str
    code: str


@router.post("/{user_id}/2fa/setup")
def admin_setup_user_2fa(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_users")),
):
    """Инициализация настройки 2FA TOTP для пользователя администратором."""
    from app.services.totp_service import generate_totp_secret, get_totp_auth_url, generate_qr_code_svg

    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, "Пользователь не найден")

    # Администраторы не могут управлять 2FA главного администратора
    if user.is_owner and not current_user.is_owner:
        raise HTTPException(403, "Администраторы не могут управлять 2FA главного администратора")

    secret = generate_totp_secret()
    auth_url = get_totp_auth_url(secret, user.username, issuer="Aliasarr")
    qr_svg = generate_qr_code_svg(auth_url)

    return {
        "user_id": user.id,
        "username": user.username,
        "secret": secret,
        "otpauth_url": auth_url,
        "qr_code_svg": qr_svg,
    }


@router.post("/{user_id}/2fa/confirm")
def admin_confirm_user_2fa(
    user_id: int,
    payload: AdminConfirm2FARequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_users")),
):
    """Подтверждение и сохранение 2FA TOTP для пользователя."""
    import datetime as dt
    from app.services.totp_service import verify_totp_code

    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, "Пользователь не найден")

    if user.is_owner and not current_user.is_owner:
        raise HTTPException(403, "Администраторы не могут управлять 2FA главного администратора")

    if not verify_totp_code(payload.secret, payload.code):
        raise HTTPException(400, "Неверный проверочный код TOTP. Проверьте правильность ввода кода.")

    user.totp_secret = payload.secret.strip()
    user.totp_enabled = True
    user.totp_confirmed_at = dt.datetime.utcnow()
    db.commit()
    db.refresh(user)

    log_audit(
        db,
        action="user.admin_enable_2fa",
        description=f"Администратор '{current_user.username}' настроил 2FA TOTP для пользователя '{user.username}'",
        user=current_user,
        request=request,
        details={"target_user_id": user.id},
    )
    return {
        "success": True,
        "message": f"2FA TOTP для пользователя '{user.username}' успешно включена",
        "user": _format_user(user, current_user),
    }


@router.post("/{user_id}/2fa/reset")
def admin_reset_user_2fa(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_users")),
):
    """Сброс и отключение 2FA TOTP для пользователя администратором."""
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, "Пользователь не найден")

    if user.is_owner and not current_user.is_owner:
        raise HTTPException(403, "Администраторы не могут сбрасывать 2FA главного администратора")

    user.totp_enabled = False
    user.totp_secret = None
    user.totp_confirmed_at = None
    db.commit()
    db.refresh(user)

    log_audit(
        db,
        action="user.admin_reset_2fa",
        description=f"Администратор '{current_user.username}' сбросил 2FA TOTP для пользователя '{user.username}'",
        user=current_user,
        request=request,
        details={"target_user_id": user.id},
    )
    return {
        "success": True,
        "message": f"2FA TOTP для пользователя '{user.username}' успешно отключена",
        "user": _format_user(user, current_user),
    }
