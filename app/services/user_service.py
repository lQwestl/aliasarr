from __future__ import annotations

import datetime as dt
import logging
import secrets
from typing import Any, Callable, Optional

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.auth import SESSION_COOKIE_NAME, _get_valid_session_user
from app.database import get_db
from app.models.db import AppSettings, Session as SessionModel, User
from app.services.settings_service import get_or_create_settings, hash_password, verify_password

logger = logging.getLogger(__name__)

# Полный список поддерживаемых прав системы (RBAC)
ALL_PERMISSIONS = {
    "view_dashboard": "Просмотр дашборда",
    "view_library": "Просмотр библиотеки",
    "manage_library": "Управление библиотекой (добавление, редактирование, удаление)",
    "manual_search": "Ручной поиск и захват релизов",
    "view_calendar": "Просмотр календаря",
    "manage_calendar": "Управление датами в календаре",
    "view_activity": "Просмотр активности и очереди загрузок",
    "manage_activity": "Управление загрузками (удаление раздач)",
    "view_history": "Просмотр истории загрузок",
    "view_events": "Просмотр системных событий",
    "view_journal": "Просмотр журнала логов",
    "manage_journal": "Очистка и скачивание журнала",
    "view_release_logs": "Просмотр логов релизов",
    "manage_release_logs": "Управление логами релизов (очистка, экспорт)",
    "view_audit": "Просмотр журнала аудита",
    "manage_settings": "Управление настройками приложения",
    "manage_indexers": "Управление индексаторами / трекерами",
    "manage_downloaders": "Управление download-клиентами",
    "manage_users": "Управление пользователями",
    "manage_backups": "Управление резервными копиями (Бэкап)",
    "use_api_key": "Создание и использование персонального API-ключа",
}


def ensure_master_admin(db: Session) -> User:
    """Гарантирует существование мастер-администратора в таблице users."""
    settings = get_or_create_settings(db)
    owner = db.query(User).filter(User.is_owner == True).first()  # noqa: E712
    if owner:
        return owner

    # Проверяем, есть ли пользователь с именем из settings.username
    admin_user = db.query(User).filter(User.username == (settings.username or "admin")).first()
    if admin_user:
        admin_user.is_admin = True
        admin_user.is_owner = True
        admin_user.enabled = True
        db.commit()
        return admin_user

    p_hash = settings.password_hash or hash_password("admin")
    owner = User(
        username=settings.username or "admin",
        password_hash=p_hash,
        display_name="Administrator",
        is_admin=True,
        is_owner=True,
        enabled=True,
        permissions={perm: True for perm in ALL_PERMISSIONS},
    )
    db.add(owner)
    db.commit()
    db.refresh(owner)
    return owner


def authenticate_user(db: Session, username: str, password: str) -> Optional[User]:
    """Проверяет учетные данные пользователя и возвращает объект User при успешной проверке."""
    uname = (username or "").strip()
    if not uname or not password:
        return None

    settings = get_or_create_settings(db)

    # 1. Поиск в таблице users по точному логину
    user = db.query(User).filter(User.username == uname).first()
    # 2. Если не найден — без учета регистра
    if not user:
        user = db.query(User).filter(User.username.ilike(uname)).first()

    # 3. Fallback на мастера-администратора
    if not user and (uname == (settings.username or "admin") or uname.lower() == (settings.username or "admin").lower()):
        owner = ensure_master_admin(db)
        if owner.username.lower() == uname.lower():
            user = owner

    if not user:
        return None

    if not user.enabled:
        return None

    # 4. Проверка пароля пользователя
    is_valid = False
    if user.password_hash:
        is_valid = verify_password(password, user.password_hash)

    # 5. Если пароль не подошел, но это мастер-администратор — fallback на settings.password_hash
    if not is_valid and user.is_owner and settings.password_hash:
        if verify_password(password, settings.password_hash):
            user.password_hash = settings.password_hash
            db.commit()
            is_valid = True

    if not is_valid:
        return None

    return user


def create_user_session(db: Session, user: User, request: Optional[Request] = None, is_local_permanent: bool = False) -> str:
    """Создает запись сессии в БД и возвращает токен сессии."""
    token = secrets.token_urlsafe(32)
    if is_local_permanent:
        # Для авторизованного пользователя в локальной сети сессия бессрочная (100 лет)
        timeout_minutes = 52560000
    else:
        timeout_minutes = getattr(user, "session_timeout_minutes", 43200) or 43200
        if timeout_minutes <= 0:
            timeout_minutes = 43200

    user_agent = None
    ip_addr = None
    if request:
        from app.auth import get_client_ip
        if "User-Agent" in request.headers:
            user_agent = request.headers.get("User-Agent", "")[:500]
        ip_addr = get_client_ip(request)

    session_row = SessionModel(
        token=token,
        user_id=user.id,
        created_at=dt.datetime.utcnow(),
        expires_at=dt.datetime.utcnow() + dt.timedelta(minutes=timeout_minutes),
        ip_address=ip_addr,
        user_agent=user_agent,
    )
    db.add(session_row)
    db.commit()
    return token


def get_current_user_optional(request: Request, db: Session = Depends(get_db)) -> Optional[User]:
    """Возвращает текущего пользователя из сессии или по API-ключу, привязанного к сессии БД."""
    if hasattr(request.state, "user") and request.state.user:
        user_id = getattr(request.state.user, "id", None)
        if user_id:
            db_user = db.get(User, user_id)
            if db_user:
                return db_user
        return request.state.user

    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:].strip()

    is_valid, user = _get_valid_session_user(db, token)
    if is_valid and user:
        return user

    provided_key = (
        request.headers.get("X-Api-Key")
        or request.query_params.get("apikey")
        or request.query_params.get("api_key")
        or request.query_params.get("token")
    )
    if provided_key:
        settings = get_or_create_settings(db)
        if provided_key == settings.api_key:
            return ensure_master_admin(db)
        user_by_key = db.query(User).filter(User.api_key == provided_key, User.enabled == True).first()
        if user_by_key:
            is_allowed = user_by_key.is_owner or user_by_key.is_admin or (user_by_key.permissions or {}).get("use_api_key", False)
            if is_allowed:
                return user_by_key

    settings = get_or_create_settings(db)
    if not settings.login_enabled:
        return ensure_master_admin(db)

    return None


def get_current_user(user: Optional[User] = Depends(get_current_user_optional)) -> User:
    """Строгая зависимость: требует авторизованного пользователя."""
    if not user:
        raise HTTPException(status_code=401, detail="Требуется авторизация")
    if not user.enabled:
        raise HTTPException(status_code=403, detail="Учётная запись отключена")
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    """Зависимость: требует права администратора."""
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Доступ запрещён: требуются права администратора")
    return user


def require_permission(permission_name: str) -> Callable:
    """Зависимость: проверяет наличие конкретного права у пользователя."""
    def dependency(user: User = Depends(get_current_user)) -> User:
        if user.is_admin:
            return user
        user_perms = user.permissions or {}
        if not user_perms.get(permission_name):
            raise HTTPException(
                status_code=403,
                detail=f"Доступ запрещён: отсутствует право '{ALL_PERMISSIONS.get(permission_name, permission_name)}'",
            )
        return user
    return dependency


def require_any_permission(*permission_names: str) -> Callable:
    """Зависимость: проверяет наличие хотя бы одного из указанных прав у пользователя."""
    def dependency(user: User = Depends(get_current_user)) -> User:
        if user.is_admin:
            return user
        user_perms = user.permissions or {}
        for p in permission_names:
            if user_perms.get(p):
                return user
        names_str = ", ".join(ALL_PERMISSIONS.get(p, p) for p in permission_names)
        raise HTTPException(
            status_code=403,
            detail=f"Доступ запрещён: требуется одно из прав: {names_str}",
        )
    return dependency
