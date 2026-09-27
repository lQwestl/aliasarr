from __future__ import annotations

import datetime as dt
import secrets
import time
from typing import Optional, Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth import SESSION_COOKIE_NAME, _get_valid_session_user, _session_token
from app.database import get_db
from app.models.db import Session as SessionModel, User
from app.services.audit_service import log_audit
from app.services.settings_service import get_or_create_settings, hash_password, verify_password
from app.services.user_service import (
    ALL_PERMISSIONS,
    authenticate_user,
    create_user_session,
    detect_user_role,
    ensure_master_admin,
    get_current_user,
    revoke_user_sessions,
)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


# Временные токены для шага 2FA (хранятся 5 минут): token -> (user_id, expires_at)
_PRE_AUTH_TOKENS: dict[str, tuple[int, dt.datetime]] = {}


def _create_pre_auth_token(user_id: int) -> str:
    now = dt.datetime.utcnow()
    # Очищаем просроченные токены
    for k in list(_PRE_AUTH_TOKENS.keys()):
        if _PRE_AUTH_TOKENS[k][1] < now:
            _PRE_AUTH_TOKENS.pop(k, None)
    t = secrets.token_urlsafe(32)
    _PRE_AUTH_TOKENS[t] = (user_id, now + dt.timedelta(minutes=5))
    return t


def _get_pre_auth_user_id(token: str) -> Optional[int]:
    now = dt.datetime.utcnow()
    item = _PRE_AUTH_TOKENS.pop(token, None)
    if not item:
        return None
    user_id, expires_at = item
    if expires_at < now:
        return None
    return user_id


# ---------------------------------------------------------------------------
# Защита входа
# ---------------------------------------------------------------------------

MIN_PASSWORD_LENGTH = 8
# Год. Больше — фактически бессрочная сессия, а у timedelta есть предел.
MAX_SESSION_TIMEOUT_MINUTES = 525600

_LOGIN_WINDOW_SECONDS = 15 * 60
_LOGIN_MAX_FAILURES_PER_IP = 10
_LOGIN_MAX_FAILURES_PER_USERNAME = 5
_LOGIN_FAILURES: dict[str, list[float]] = {}


def _failure_keys(client_ip: str, username: str) -> list[tuple[str, int]]:
    keys = [(f"ip:{client_ip or 'unknown'}", _LOGIN_MAX_FAILURES_PER_IP)]
    if username:
        keys.append((f"user:{username.strip().lower()}", _LOGIN_MAX_FAILURES_PER_USERNAME))
    return keys


def _recent_failures(key: str, now: float) -> list[float]:
    attempts = [ts for ts in _LOGIN_FAILURES.get(key, []) if now - ts < _LOGIN_WINDOW_SECONDS]
    if attempts:
        _LOGIN_FAILURES[key] = attempts
    else:
        _LOGIN_FAILURES.pop(key, None)
    return attempts


def _enforce_login_throttle(client_ip: str, username: str) -> None:
    """Перебор паролей и кодов 2FA ограничен по IP и по имени пользователя."""
    now = time.monotonic()
    for key, limit in _failure_keys(client_ip, username):
        attempts = _recent_failures(key, now)
        if len(attempts) >= limit:
            retry_after = int(_LOGIN_WINDOW_SECONDS - (now - attempts[0])) + 1
            raise HTTPException(
                429,
                f"Слишком много неудачных попыток входа. Повторите через {max(1, retry_after // 60)} мин.",
                headers={"Retry-After": str(retry_after)},
            )


def _register_login_failure(client_ip: str, username: str) -> None:
    now = time.monotonic()
    if len(_LOGIN_FAILURES) > 10000:
        for key in list(_LOGIN_FAILURES):
            _recent_failures(key, now)
    for key, _limit in _failure_keys(client_ip, username):
        _LOGIN_FAILURES.setdefault(key, []).append(now)


def _clear_login_failures(client_ip: str, username: str) -> None:
    for key, _limit in _failure_keys(client_ip, username):
        _LOGIN_FAILURES.pop(key, None)


def reset_login_throttle() -> None:
    """Сбрасывает счётчики неудачных входов (используется в тестах)."""
    _LOGIN_FAILURES.clear()


def _request_is_https(request: Request) -> bool:
    from app.auth import _is_trusted_proxy

    if request.url.scheme == "https":
        return True
    peer = request.client.host if request.client else ""
    forwarded_proto = (request.headers.get("X-Forwarded-Proto") or "").split(",")[0].strip().lower()
    return bool(peer and _is_trusted_proxy(peer) and forwarded_proto == "https")


def _set_session_cookie(response: Response, request: Request, token: str, max_age: int) -> None:
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        secure=_request_is_https(request),
        max_age=max_age,
        path="/",
    )


def _validate_new_password(password: str) -> None:
    if len(password or "") < MIN_PASSWORD_LENGTH:
        raise HTTPException(400, f"Пароль должен содержать не менее {MIN_PASSWORD_LENGTH} символов")


class LoginRequest(BaseModel):
    username: str
    password: str


class Login2FARequest(BaseModel):
    temp_token: str
    code: str


class Disable2FARequest(BaseModel):
    password: Optional[str] = None


class Setup2FAConfirmRequest(BaseModel):
    secret: str
    code: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class AvatarUpdateRequest(BaseModel):
    avatar: Optional[str] = None  # Data-URL string (base64) or None to clear


class ProfileUpdateRequest(BaseModel):
    display_name: Optional[str] = None
    avatar: Optional[str] = None
    session_timeout_minutes: Optional[int] = None


class CredentialsUpdate(BaseModel):
    login_enabled: bool
    username: str
    display_name: Optional[str] = None
    password: Optional[str] = None
    auth_disabled_for_local_addresses: Optional[bool] = None
    totp_2fa_enabled: Optional[bool] = None
    totp_2fa_policy: Optional[str] = None  # "users_choice" | "enforce_all"


def _format_user_out(user: User, include_key: bool = False) -> dict[str, Any]:
    perms = user.permissions or {}
    if user.is_admin:
        # Админ всегда имеет все права
        perms = {perm: True for perm in ALL_PERMISSIONS}
    can_use_api_key = bool(user.is_owner or user.is_admin or perms.get("use_api_key"))
    res = {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name or user.username,
        "is_admin": user.is_admin,
        "is_owner": user.is_owner,
        "role": detect_user_role(user),
        "avatar": user.avatar,
        "permissions": perms,
        "enabled": user.enabled,
        "session_timeout_minutes": getattr(user, "session_timeout_minutes", 43200) or 43200,
        "has_api_key": bool(user.api_key),
        "can_use_api_key": can_use_api_key,
        "totp_enabled": bool(getattr(user, "totp_enabled", False)),
        "totp_confirmed_at": user.totp_confirmed_at.isoformat() if getattr(user, "totp_confirmed_at", None) else None,
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
    }
    if include_key and can_use_api_key:
        res["api_key"] = user.api_key
    return res


@router.get("/status")
def auth_status(request: Request, db: Session = Depends(get_db)):
    from app.auth import get_client_ip, is_local_host_header, is_private_ip
    settings = get_or_create_settings(db)
    client_ip = get_client_ip(request)
    is_private = is_private_ip(client_ip)
    local_bypass_allowed = is_private and is_local_host_header(request.headers.get("Host"))
    auth_disabled_local = getattr(settings, "auth_disabled_for_local_addresses", True)
    totp_2fa_enabled = getattr(settings, "totp_2fa_enabled", False)
    totp_2fa_policy = getattr(settings, "totp_2fa_policy", "users_choice")

    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:].strip()

    is_valid, user = _get_valid_session_user(db, token)
    if is_valid and user:
        return {
            "login_required": False,
            "auth_required": False,
            "authenticated": True,
            "is_authenticated": True,
            "is_local": is_private,
            "client_ip": client_ip,
            "auth_disabled_for_local_addresses": auth_disabled_local,
            "totp_2fa_enabled": totp_2fa_enabled,
            "totp_2fa_policy": totp_2fa_policy,
            "user": _format_user_out(user),
            "username": settings.username,
        }

    if settings.login_enabled and auth_disabled_local and local_bypass_allowed:
        master = ensure_master_admin(db)
        return {
            "login_required": False,
            "auth_required": False,
            "authenticated": True,
            "is_authenticated": True,
            "is_local": True,
            "client_ip": client_ip,
            "auth_disabled_for_local_addresses": True,
            "totp_2fa_enabled": totp_2fa_enabled,
            "totp_2fa_policy": totp_2fa_policy,
            "user": _format_user_out(master),
            "username": settings.username,
        }

    # Если обязательная авторизация отключена в настройках:
    if not settings.login_enabled:
        master = ensure_master_admin(db)
        return {
            "login_required": False,
            "auth_required": False,
            "authenticated": True,
            "is_authenticated": True,
            "is_local": is_private,
            "client_ip": client_ip,
            "auth_disabled_for_local_addresses": auth_disabled_local,
            "totp_2fa_enabled": totp_2fa_enabled,
            "totp_2fa_policy": totp_2fa_policy,
            "user": _format_user_out(master),
            "username": settings.username,
        }

    # Если сессии нет, включен вход и не действует локальное исключение — требуется пароль.
    return {
        "login_required": True,
        "auth_required": True,
        "authenticated": False,
        "is_authenticated": False,
        "is_local": is_private,
        "client_ip": client_ip,
        "auth_disabled_for_local_addresses": auth_disabled_local,
        "totp_2fa_enabled": totp_2fa_enabled,
        "totp_2fa_policy": totp_2fa_policy,
        "user": None,
        # Имя владельца до входа не раскрываем: это половина пары логин/пароль.
        "username": None,
    }


@router.post("/login")
def login(payload: LoginRequest, response: Response, request: Request, db: Session = Depends(get_db)):
    from app.auth import get_client_ip, is_private_ip
    settings = get_or_create_settings(db)
    client_ip = get_client_ip(request)
    _enforce_login_throttle(client_ip, payload.username)
    user = authenticate_user(db, payload.username.strip(), payload.password)
    if not user:
        _register_login_failure(client_ip, payload.username)
        log_audit(
            db,
            action="auth.login_failed",
            description=f"Неудачная попытка входа под именем '{payload.username.strip()}'",
            username=payload.username.strip(),
            request=request,
        )
        raise HTTPException(401, "Неверное имя пользователя или пароль")

    _clear_login_failures(client_ip, payload.username)
    is_private = is_private_ip(client_ip)

    # 2FA TOTP:
    # Запрос 2FA происходит ТОЛЬКО для пользователей, которые авторизуются через внешний IP-адрес.
    # Если вход по приватному IP, 2FA не запрашивается.
    user_2fa_enabled = bool(getattr(user, "totp_enabled", False))
    global_2fa_enforced = bool(getattr(settings, "totp_2fa_enabled", False) and getattr(settings, "totp_2fa_policy", "users_choice") == "enforce_all")
    has_totp_secret = bool(getattr(user, "totp_secret", None))
    if not is_private and global_2fa_enforced and not has_totp_secret:
        # Политика «2FA для всех» не должна молча пропускать тех, кто её ещё не
        # настроил: вход извне без второго фактора и есть то, что она запрещает.
        log_audit(
            db,
            action="auth.login_2fa_required",
            description=f"Вход '{user.username}' извне отклонён: политика требует 2FA, а она не настроена",
            user=user,
            request=request,
        )
        raise HTTPException(
            403,
            "Для входа из внешней сети требуется двухфакторная аутентификация. "
            "Настройте 2FA в профиле, войдя из локальной сети, или попросите администратора.",
        )
    requires_2fa = not is_private and (user_2fa_enabled or global_2fa_enforced) and has_totp_secret

    if requires_2fa:
        temp_token = _create_pre_auth_token(user.id)
        return {
            "success": False,
            "requires_2fa": True,
            "temp_token": temp_token,
            "username": user.username,
            "display_name": user.display_name or user.username,
        }

    # Прямой вход (без 2FA или при локальном подключении)
    user.last_login_at = dt.datetime.utcnow()
    db.commit()

    token = create_user_session(db, user, request=request, is_local_permanent=False)
    max_age = (user.session_timeout_minutes or 43200) * 60
    _set_session_cookie(response, request, token, max_age)

    log_audit(
        db,
        action="auth.login",
        description=f"Пользователь '{user.username}' успешно вошел в систему" + (" (локальная сеть)" if is_private else ""),
        user=user,
        request=request,
    )

    return {
        "success": True,
        "requires_2fa": False,
        "token": token,
        "user": _format_user_out(user, include_key=True),
    }


@router.post("/login-2fa")
def login_2fa(payload: Login2FARequest, response: Response, request: Request, db: Session = Depends(get_db)):
    import urllib.parse
    from app.services.totp_service import verify_totp_code
    from app.auth import get_client_ip

    client_ip = get_client_ip(request)
    user_id = _get_pre_auth_user_id(payload.temp_token.strip())
    if not user_id:
        raise HTTPException(401, "Срок действия временного токена истёк или токен недействителен. Пожалуйста, выполните вход заново.")

    user = db.get(User, user_id)
    if not user or not user.enabled:
        raise HTTPException(401, "Учётная запись недоступна или заблокирована")

    if not user.totp_secret:
        raise HTTPException(400, "Двухфакторная аутентификация не настроена для данной учётной записи")

    _enforce_login_throttle(client_ip, user.username)
    code = payload.code.strip()
    # Если передан QR-код / otpauth URI со значением code
    if "code=" in code or "secret=" in code:
        try:
            parsed = urllib.parse.parse_qs(urllib.parse.urlparse(code).query)
            code = parsed.get("code", [code])[0]
        except Exception:
            pass

    is_valid = verify_totp_code(user.totp_secret, code)
    if not is_valid:
        _register_login_failure(client_ip, user.username)
        log_audit(
            db,
            action="auth.login_2fa_failed",
            description=f"Неверный 2FA TOTP код для пользователя '{user.username}'",
            username=user.username,
            user_id=user.id,
            request=request,
        )
        raise HTTPException(401, "Неверный код двухфакторной аутентификации")

    _clear_login_failures(client_ip, user.username)
    user.last_login_at = dt.datetime.utcnow()
    db.commit()

    token = create_user_session(db, user, request=request, is_local_permanent=False)
    max_age = (user.session_timeout_minutes or 43200) * 60
    _set_session_cookie(response, request, token, max_age)

    log_audit(
        db,
        action="auth.login_2fa_success",
        description=f"Пользователь '{user.username}' успешно подтвердил вход через 2FA TOTP",
        user=user,
        request=request,
    )

    return {
        "success": True,
        "requires_2fa": False,
        "token": token,
        "user": _format_user_out(user, include_key=True),
    }


@router.post("/2fa/setup")
def setup_2fa(request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from app.services.totp_service import generate_totp_secret, get_totp_auth_url, generate_qr_code_svg
    db_user = db.get(User, user.id) or user
    secret = generate_totp_secret()
    auth_url = get_totp_auth_url(secret, db_user.username, issuer="Aliasarr")
    qr_svg = generate_qr_code_svg(auth_url)
    return {
        "secret": secret,
        "otpauth_url": auth_url,
        "qr_code_svg": qr_svg,
        "username": db_user.username,
    }


@router.post("/2fa/confirm")
def confirm_2fa(payload: Setup2FAConfirmRequest, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from app.services.totp_service import verify_totp_code
    db_user = db.get(User, user.id) or user

    if not verify_totp_code(payload.secret, payload.code):
        raise HTTPException(400, "Неверный код подтверждения. Проверьте время на устройстве и введите текущий код из приложения-аутентификатора.")

    db_user.totp_secret = payload.secret.strip()
    db_user.totp_enabled = True
    db_user.totp_confirmed_at = dt.datetime.utcnow()
    db.commit()
    db.refresh(db_user)

    log_audit(
        db,
        action="user.2fa_enabled",
        description=f"Пользователь '{db_user.username}' включил двухфакторную аутентификацию 2FA TOTP",
        user=db_user,
        request=request,
    )
    return {
        "success": True,
        "message": "Двухфакторная аутентификация успешно активирована",
        "user": _format_user_out(db_user),
    }


@router.post("/2fa/disable")
def disable_2fa(
    request: Request,
    payload: Optional[Disable2FARequest] = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    db_user = db.get(User, user.id) or user
    # Второй фактор снимается только тем, кто знает пароль: иначе украденная
    # сессия первым делом отключала бы 2FA и закрепляла доступ.
    if db_user.password_hash:
        password = (payload.password if payload else None) or ""
        if not verify_password(password, db_user.password_hash):
            raise HTTPException(400, "Для отключения 2FA укажите текущий пароль")
    db_user.totp_enabled = False
    db_user.totp_secret = None
    db_user.totp_confirmed_at = None
    db.commit()
    db.refresh(db_user)

    log_audit(
        db,
        action="user.2fa_disabled",
        description=f"Пользователь '{db_user.username}' отключил двухфакторную аутентификацию 2FA TOTP",
        user=db_user,
        request=request,
    )
    return {
        "success": True,
        "message": "Двухфакторная аутентификация отключена",
        "user": _format_user_out(db_user),
    }


@router.post("/logout")
def logout(response: Response, request: Request, db: Session = Depends(get_db)):
    token = request.cookies.get(SESSION_COOKIE_NAME)
    user = None
    if token:
        from app.auth import invalidate_session_cache
        invalidate_session_cache(token)
        session_row = db.query(SessionModel).filter(SessionModel.token == token).first()
        if session_row:
            if session_row.user_id:
                user = db.get(User, session_row.user_id)
            db.delete(session_row)
            db.commit()

    response.delete_cookie(SESSION_COOKIE_NAME, path="/")

    log_audit(
        db,
        action="auth.logout",
        description=f"Пользователь '{user.username if user else 'anonymous'}' вышел из системы",
        user=user,
        request=request,
    )
    return {"success": True}


@router.get("/me")
def get_me(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    db_user = db.get(User, user.id) or user
    return _format_user_out(db_user)


@router.put("/me")
def update_me(payload: ProfileUpdateRequest, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    db_user = db.get(User, user.id) or user
    updated_fields = []
    if payload.display_name is not None:
        db_user.display_name = payload.display_name.strip() or db_user.username
        updated_fields.append(f"отображаемое имя: '{db_user.display_name}'")
    if payload.avatar is not None:
        db_user.avatar = payload.avatar
        updated_fields.append("аватар")
    if payload.session_timeout_minutes is not None and payload.session_timeout_minutes > 0:
        db_user.session_timeout_minutes = min(payload.session_timeout_minutes, MAX_SESSION_TIMEOUT_MINUTES)
        updated_fields.append(f"таймаут сессии: {db_user.session_timeout_minutes} мин")

    if updated_fields:
        db.add(db_user)
        db.commit()
        db.refresh(db_user)
        log_audit(
            db,
            action="user.update",
            description=f"Пользователь '{db_user.username}' обновил профиль ({', '.join(updated_fields)})",
            user=db_user,
            request=request,
        )
    return _format_user_out(db_user)


@router.post("/change-password")
def change_password(payload: ChangePasswordRequest, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    db_user = db.get(User, user.id) or user
    if not verify_password(payload.current_password, db_user.password_hash):
        raise HTTPException(400, "Текущий пароль указан неверно")

    _validate_new_password(payload.new_password)

    new_hash = hash_password(payload.new_password)
    db_user.password_hash = new_hash
    if db_user.is_owner:
        settings = get_or_create_settings(db)
        settings.password_hash = new_hash

    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    current_token, _from_cookie = _session_token(request)
    revoke_user_sessions(db, db_user.id, keep_token=current_token)

    log_audit(
        db,
        action="auth.password_change",
        description=f"Пользователь '{db_user.username}' сменил свой пароль",
        user=db_user,
        request=request,
    )
    return {"success": True, "message": "Пароль успешно изменён"}


@router.post("/me/avatar")
def update_my_avatar(payload: AvatarUpdateRequest, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    db_user = db.get(User, user.id) or user
    db_user.avatar = payload.avatar
    db.add(db_user)
    db.commit()
    db.refresh(db_user)

    log_audit(
        db,
        action="user.avatar_update",
        description=f"Пользователь '{user.username}' обновил аватар",
        user=user,
        request=request,
    )
    return {"success": True, "avatar": user.avatar}


@router.put("/credentials")
def update_credentials(payload: CredentialsUpdate, request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    settings = get_or_create_settings(db)
    owner = ensure_master_admin(db)

    # В безопасности снимать и ставить галочку с функцией 'Требовать вход по логину и паролю' может только главный администратор
    if not user.is_owner:
        raise HTTPException(403, "Только главный администратор может изменять параметры безопасности и требование входа по логину и паролю")

    if payload.login_enabled and not payload.password and not settings.password_hash and not owner.password_hash:
        raise HTTPException(400, "Укажите пароль, чтобы включить вход по логину/паролю")

    owner.username = payload.username.strip() or "admin"
    if payload.display_name is not None:
        owner.display_name = payload.display_name.strip() or owner.username
    settings.username = owner.username
    if payload.totp_2fa_policy is not None and payload.totp_2fa_policy not in ("users_choice", "enforce_all"):
        raise HTTPException(400, "Неизвестная политика 2FA")
    password_changed = False
    if payload.password:
        _validate_new_password(payload.password)
        p_hash = hash_password(payload.password)
        owner.password_hash = p_hash
        settings.password_hash = p_hash
        password_changed = True

    settings.login_enabled = payload.login_enabled
    if payload.auth_disabled_for_local_addresses is not None:
        settings.auth_disabled_for_local_addresses = payload.auth_disabled_for_local_addresses
    if payload.totp_2fa_enabled is not None:
        settings.totp_2fa_enabled = payload.totp_2fa_enabled
    if payload.totp_2fa_policy is not None:
        settings.totp_2fa_policy = payload.totp_2fa_policy
    db.commit()
    if password_changed:
        current_token, _from_cookie = _session_token(request)
        revoke_user_sessions(db, owner.id, keep_token=current_token if user.id == owner.id else None)

    log_audit(
        db,
        action="settings.security_update",
        description=f"Обновлены настройки аутентификации (вход по паролю: {payload.login_enabled}, отключение для локальных IP: {settings.auth_disabled_for_local_addresses}, 2FA: {settings.totp_2fa_enabled})",
        user=user,
        request=request,
    )
    return {
        "success": True,
        "login_enabled": settings.login_enabled,
        "auth_disabled_for_local_addresses": settings.auth_disabled_for_local_addresses,
        "totp_2fa_enabled": settings.totp_2fa_enabled,
        "totp_2fa_policy": settings.totp_2fa_policy,
        "username": settings.username,
        "display_name": owner.display_name,
    }


@router.get("/my-api-key")
def get_my_api_key(user: User = Depends(get_current_user)):
    perms = user.permissions or {}
    can_use = bool(user.is_owner or user.is_admin or perms.get("use_api_key"))
    if not can_use:
        raise HTTPException(403, "Использование API-ключа отключено для вашей учётной записи")
    return {
        "api_key": user.api_key,
        "has_key": bool(user.api_key),
    }


@router.post("/regenerate-my-api-key")
def regenerate_my_api_key(request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    perms = user.permissions or {}
    can_use = bool(user.is_owner or user.is_admin or perms.get("use_api_key"))
    if not can_use:
        raise HTTPException(403, "Использование API-ключа отключено для вашей учётной записи")

    new_key = secrets.token_hex(32)
    user.api_key = new_key
    db.commit()
    db.refresh(user)

    log_audit(
        db,
        action="user.regenerate_api_key",
        description=f"Пользователь '{user.username}' сгенерировал новый персональный API-ключ",
        user=user,
        request=request,
    )
    return {"api_key": user.api_key, "has_key": True}


@router.delete("/revoke-my-api-key")
def revoke_my_api_key(request: Request, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    perms = user.permissions or {}
    can_use = bool(user.is_owner or user.is_admin or perms.get("use_api_key"))
    if not can_use:
        raise HTTPException(403, "Использование API-ключа отключено для вашей учётной записи")

    user.api_key = None
    db.commit()
    db.refresh(user)

    log_audit(
        db,
        action="user.revoke_api_key",
        description=f"Пользователь '{user.username}' отозвал свой персональный API-ключ",
        user=user,
        request=request,
    )
    return {"success": True, "has_key": False}
