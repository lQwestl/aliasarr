from __future__ import annotations

import datetime as dt
import ipaddress

try:
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.requests import Request
    from starlette.responses import JSONResponse, RedirectResponse
except ImportError:
    class BaseHTTPMiddleware:  # type: ignore
        def __init__(self, app=None):
            self.app = app
    Request = object  # type: ignore
    class JSONResponse:  # type: ignore
        def __init__(self, content, status_code=200, **kwargs):
            self.content = content
            self.status_code = status_code
            self.headers = {}
    class RedirectResponse:  # type: ignore
        def __init__(self, url, status_code=303, **kwargs):
            self.url = url
            self.status_code = status_code
            self.headers = {"location": url}

try:
    from app.database import SessionLocal
except ImportError:
    SessionLocal = lambda: None  # type: ignore

try:
    from app.services.settings_service import get_or_create_settings
except ImportError:
    get_or_create_settings = lambda db: None  # type: ignore

SESSION_COOKIE_NAME = "aliasarr_session"

# Пути, доступные без авторизации (только статус авторизации, логин и health probe)
_PUBLIC_PATHS_PREFIXES = (
    "/api/v1/health",
    "/api/v1/auth/status",
    "/api/v1/auth/login",
)


def get_client_ip(request: Request) -> str:
    """Извлекает IP клиента из заголовков прокси (CF-Connecting-IP, X-Forwarded-For, X-Real-IP) или request.client.host."""
    if not request:
        return "127.0.0.1"
    cf_ip = request.headers.get("CF-Connecting-IP")
    if cf_ip:
        return cf_ip.strip()
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip.strip()
    if getattr(request, "client", None) and getattr(request.client, "host", None):
        return request.client.host
    return "127.0.0.1"


_CGNAT_NET = ipaddress.ip_network("100.64.0.0/10")


def is_private_ip(ip_str: str | None) -> bool:
    """Проверяет, является ли IP адрес локальным / приватным (LAN, localhost, RFC 1918, RFC 4193 ULA, CGNAT)."""
    if not ip_str:
        return False
    clean_ip = ip_str.strip()
    # Очищаем от порта если передан host:port (IPv4:port или [IPv6]:port)
    if clean_ip.startswith("[") and "]" in clean_ip:
        clean_ip = clean_ip[1:clean_ip.index("]")]
    elif ":" in clean_ip and clean_ip.count(":") == 1:
        clean_ip = clean_ip.split(":")[0]

    if clean_ip.lower() in ("localhost", "aliasarr", "aliasarr.local", "127.0.0.1", "::1"):
        return True

    try:
        ip_obj = ipaddress.ip_address(clean_ip)
        if ip_obj.is_private or ip_obj.is_loopback or ip_obj.is_link_local or ip_obj.is_reserved:
            return True
        if isinstance(ip_obj, ipaddress.IPv4Address) and ip_obj in _CGNAT_NET:
            return True
        return False
    except ValueError:
        return False


def _get_valid_session_user(db, token: str | None):
    if not token:
        return False, None
    from app.models.db import Session as SessionModel, User

    row = db.query(SessionModel).filter(SessionModel.token == token).first()
    if not row:
        return False, None
    if row.expires_at < dt.datetime.utcnow():
        try:
            db.delete(row)
            db.commit()
        except Exception:
            db.rollback()
        return False, None

    user = None
    if row.user_id:
        user = db.get(User, row.user_id)
        if user and not user.enabled:
            return False, None
        if user:
            _ = (user.id, user.username, user.display_name, user.is_owner, user.is_admin, user.permissions, user.api_key)
            try:
                db.expunge(user)
            except Exception:
                pass
    return True, user


class ApiKeyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Общедоступные маршруты (статика css/js/шрифты, вход, проверка статуса сессии, health probe и корень /)
        if path == "/" or (path.startswith("/ui/static/") and not path.endswith(".html")) or any(path.startswith(p) for p in _PUBLIC_PATHS_PREFIXES):
            return await call_next(request)

        user = None
        is_authenticated = False
        forbidden_response = None
        unauthorized_response = None

        is_docs_request = path in ("/docs", "/redoc", "/openapi.json") or path.startswith(("/docs", "/redoc"))
        is_page_request = is_docs_request or path in ("/quality-guide", "/quality-guide.html") or path.startswith("/quality-guide") or path.endswith(".html")

        db = SessionLocal()
        try:
            settings = get_or_create_settings(db)

            # 1. Извлекаем токен сессии (из Cookie или заголовка Authorization)
            token = request.cookies.get(SESSION_COOKIE_NAME)
            if not token:
                auth_header = request.headers.get("Authorization", "")
                if auth_header.startswith("Bearer "):
                    token = auth_header[7:].strip()

            is_valid_session, user = _get_valid_session_user(db, token)
            if is_valid_session:
                is_authenticated = True
            else:
                # 2. Проверяем API-ключ
                provided_key = request.headers.get("X-Api-Key") or request.query_params.get("apikey")
                if provided_key:
                    from app.models.db import User
                    if provided_key == settings.api_key:
                        owner = db.query(User).filter(User.is_owner == True).first()  # noqa: E712
                        if owner:
                            _ = (owner.id, owner.username, owner.display_name, owner.is_owner, owner.is_admin, owner.permissions, owner.api_key)
                            try:
                                db.expunge(owner)
                            except Exception:
                                pass
                        user = owner
                        is_authenticated = True
                    else:
                        user_by_key = db.query(User).filter(User.api_key == provided_key, User.enabled == True).first()
                        if user_by_key:
                            is_allowed = user_by_key.is_owner or user_by_key.is_admin or (user_by_key.permissions or {}).get("use_api_key", False)
                            if not is_allowed:
                                forbidden_response = JSONResponse(
                                    {"error": "Использование API-ключа отключено для вашей учётной записи", "code": "api_key_forbidden"},
                                    status_code=403,
                                )
                            else:
                                _ = (user_by_key.id, user_by_key.username, user_by_key.display_name, user_by_key.is_owner, user_by_key.is_admin, user_by_key.permissions, user_by_key.api_key)
                                try:
                                    db.expunge(user_by_key)
                                except Exception:
                                    pass
                                user = user_by_key
                                is_authenticated = True
                        else:
                            unauthorized_response = JSONResponse(
                                {"error": "Неверный или отсутствующий API-ключ (заголовок X-Api-Key)", "code": "invalid_api_key"},
                                status_code=401,
                            )
                elif settings.login_enabled:
                    if is_page_request and path != "/openapi.json":
                        unauthorized_response = RedirectResponse(url="/", status_code=303)
                    else:
                        unauthorized_response = JSONResponse(
                            {"error": "Требуется вход в систему для доступа к API и справочникам", "code": "login_required"},
                            status_code=401,
                        )
                else:
                    # Если авторизация по паролю отключена в настройках, доступ предоставляется с правами владельца
                    from app.models.db import User
                    owner = db.query(User).filter(User.is_owner == True).first()  # noqa: E712
                    if owner:
                        _ = (owner.id, owner.username, owner.display_name, owner.is_owner, owner.is_admin, owner.permissions, owner.api_key)
                        try:
                            db.expunge(owner)
                        except Exception:
                            pass
                    user = owner
                    is_authenticated = True
        finally:
            db.close()

        if forbidden_response:
            return forbidden_response
        if unauthorized_response:
            return unauthorized_response

        request.state.user = user
        request.state.is_authenticated = is_authenticated
        return await call_next(request)
