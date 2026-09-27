from __future__ import annotations

import datetime as dt
import ipaddress
import os
import secrets

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

# Пути, доступные без авторизации. Сопоставление должно быть только точным:
# префикс /api/v1/health не должен открывать /api/v1/health-check.
_PUBLIC_PATHS = frozenset((
    "/api/v1/health",
    "/api/v1/auth/status",
    "/api/v1/auth/login",
    "/api/v1/auth/login-2fa",
))
# Совместимость для импортирующих старое внутреннее имя тестов и расширений.
_PUBLIC_PATHS_PREFIXES = tuple(_PUBLIC_PATHS)


def _get_scope_path(request: Request) -> str:
    """Берёт маршрут из ASGI scope, не позволяя Host подменить URL path."""
    scope = getattr(request, "scope", None)
    if isinstance(scope, dict):
        path = scope.get("path")
        if isinstance(path, str):
            return path
    # Поддержка простых mock-объектов в unit-тестах; реальный Request всегда имеет scope.
    return request.url.path


def _trusted_proxy_networks() -> tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]:
    raw_value = os.getenv("ALIASARR_TRUSTED_PROXIES", "")
    networks = []
    for raw_item in raw_value.split(","):
        item = raw_item.strip()
        if not item:
            continue
        try:
            networks.append(ipaddress.ip_network(item, strict=False))
        except ValueError:
            continue
    return tuple(networks)


def _is_trusted_proxy(peer_ip: str) -> bool:
    try:
        address = ipaddress.ip_address(peer_ip)
    except ValueError:
        return False
    return any(address in network for network in _trusted_proxy_networks())


def _parse_ip(value: str | None) -> str:
    """Возвращает IP из значения заголовка (без порта) или пустую строку."""
    candidate = (value or "").strip().strip('"')
    if candidate.startswith("[") and "]" in candidate:
        candidate = candidate[1:candidate.index("]")]
    elif candidate.count(":") == 1:
        candidate = candidate.split(":", 1)[0]
    try:
        return str(ipaddress.ip_address(candidate))
    except ValueError:
        return ""


def _trust_cloudflare_header() -> bool:
    return os.getenv("ALIASARR_TRUST_CF_CONNECTING_IP", "").strip().lower() in ("1", "true", "yes", "on")


def get_client_ip(request: Request) -> str:
    """Return the client IP, trusting forwarding headers only from configured proxies.

    X-Forwarded-For is read right to left: every proxy appends the address it
    received the request from, so only the entries added by our own trusted
    proxies are reliable. The rightmost address that is not a trusted proxy is
    the client; anything to its left was supplied by the client itself and can
    be forged ("X-Forwarded-For: 192.168.1.10" from the internet).
    """
    if not request:
        return ""
    peer_ip = ""
    if getattr(request, "client", None) and getattr(request.client, "host", None):
        peer_ip = request.client.host.strip()

    if peer_ip and _is_trusted_proxy(peer_ip):
        # CF-Connecting-IP проходит через любой прокси без изменений, поэтому ему
        # можно верить, только если перед приложением действительно Cloudflare.
        if _trust_cloudflare_header():
            cf_ip = _parse_ip(request.headers.get("CF-Connecting-IP"))
            if cf_ip:
                return cf_ip
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            hops = [_parse_ip(item) for item in forwarded.split(",")]
            for hop in reversed(hops):
                if not hop:
                    # Нераспознаваемое значение: дальше влево доверять нечему.
                    return peer_ip
                if not _is_trusted_proxy(hop):
                    return hop
            return hops[0] or peer_ip
        real_ip = _parse_ip(request.headers.get("X-Real-IP"))
        if real_ip:
            return real_ip
    return peer_ip


# Имена хостов, которые не резолвятся в публичном DNS. Доверие к локальному IP
# (вход без пароля из LAN, режим без логина) опасно при DNS rebinding: чужой
# сайт привязывает свой домен к адресу Aliasarr, и браузер пользователя шлёт
# запросы «с того же origin». Такие запросы приходят с публичным именем в Host.
_LOCAL_HOST_SUFFIXES = (
    ".local", ".lan", ".home", ".home.arpa", ".internal", ".localdomain",
    ".localhost", ".test", ".intranet", ".corp", ".private",
)


def _extra_allowed_hosts() -> set[str]:
    raw = os.getenv("ALIASARR_ALLOWED_HOSTS", "")
    return {item.strip().lower().rstrip(".") for item in raw.split(",") if item.strip()}


def _host_without_port(host_header: str | None) -> str:
    host = (host_header or "").strip().lower()
    if host.startswith("[") and "]" in host:
        return host[1:host.index("]")]
    if host.count(":") == 1:
        host = host.split(":", 1)[0]
    return host.rstrip(".")


def is_local_host_header(host_header: str | None) -> bool:
    """True, если Host — IP-адрес, однословное или внутреннее имя, либо явно разрешён."""
    host = _host_without_port(host_header)
    if not host:
        return False
    if host in _extra_allowed_hosts():
        return True
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        pass
    if "." not in host:
        return True
    return host.endswith(_LOCAL_HOST_SUFFIXES)


def is_cross_site_request(request: Request) -> bool:
    """True, если браузер сообщил, что запрос инициирован другим сайтом.

    Современные браузеры сами проставляют Sec-Fetch-Site, и прокси его не
    переписывают: «same-origin» — запрос со страницы самого Aliasarr, «none» —
    пользователь открыл адрес сам. «same-site» тоже отклоняется: соседнее
    приложение на другом порту того же NAS — это другой сайт с точки зрения
    доверия. Для старых браузеров сравниваются Origin и Host. Запросы без этих
    заголовков — curl, скрипты и интеграции; для них CSRF невозможен.
    """
    fetch_site = (request.headers.get("Sec-Fetch-Site") or "").strip().lower()
    if fetch_site:
        return fetch_site not in ("same-origin", "none")

    origin = (request.headers.get("Origin") or "").strip()
    if not origin:
        return False
    if origin == "null":
        return True
    try:
        from urllib.parse import urlsplit
        origin_host = (urlsplit(origin).netloc or "").lower()
    except ValueError:
        return True
    request_hosts = {(request.headers.get("Host") or "").strip().lower()}
    forwarded_host = (request.headers.get("X-Forwarded-Host") or "").split(",")[0].strip().lower()
    if forwarded_host:
        request_hosts.add(forwarded_host)
    return not origin_host or origin_host not in request_hosts


def keys_match(provided: str | None, expected: str | None) -> bool:
    """Сравнение секретов за постоянное время."""
    if not provided or not expected:
        return False
    return secrets.compare_digest(str(provided).encode("utf-8"), str(expected).encode("utf-8"))


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


import time

_SESSION_USER_CACHE: dict[str, tuple[float, bool, any]] = {}  # token -> (timestamp, is_valid, user)
_SESSION_CACHE_TTL = 10.0  # Кэшируем сессию на 10 секунд в памяти для разгрузки БД
# Кэш пополняется и несуществующими токенами (чтобы не ходить в БД на каждый
# мусорный запрос), поэтому его размер ограничен: иначе поток случайных токенов
# растил бы память процесса без предела.
_SESSION_CACHE_MAX_ENTRIES = 5000


def invalidate_session_cache(token: str | None = None) -> None:
    if token:
        _SESSION_USER_CACHE.pop(token, None)
    else:
        _SESSION_USER_CACHE.clear()


def _cache_session(token: str, now_ts: float, is_valid: bool, user) -> None:
    if len(_SESSION_USER_CACHE) >= _SESSION_CACHE_MAX_ENTRIES:
        for key, value in list(_SESSION_USER_CACHE.items()):
            if now_ts - value[0] >= _SESSION_CACHE_TTL:
                _SESSION_USER_CACHE.pop(key, None)
        if len(_SESSION_USER_CACHE) >= _SESSION_CACHE_MAX_ENTRIES:
            oldest = sorted(_SESSION_USER_CACHE.items(), key=lambda item: item[1][0])
            for key, _value in oldest[: len(oldest) // 2]:
                _SESSION_USER_CACHE.pop(key, None)
    _SESSION_USER_CACHE[token] = (now_ts, is_valid, user)


def _detach_user(db, user) -> None:
    _ = (user.id, user.username, user.display_name, user.is_owner, user.is_admin, user.permissions, user.api_key)
    try:
        db.expunge(user)
    except Exception:
        pass


def _get_valid_session_user(db, token: str | None):
    if not token:
        return False, None
    now_ts = time.time()
    cached = _SESSION_USER_CACHE.get(token)
    if cached and (now_ts - cached[0] < _SESSION_CACHE_TTL):
        return cached[1], cached[2]

    from app.models.db import Session as SessionModel, User

    row = db.query(SessionModel).filter(SessionModel.token == token).first()
    if not row:
        _cache_session(token, now_ts, False, None)
        return False, None
    if row.expires_at < dt.datetime.utcnow():
        try:
            db.delete(row)
            db.commit()
        except Exception:
            db.rollback()
        _cache_session(token, now_ts, False, None)
        return False, None

    user = None
    if row.user_id:
        user = db.get(User, row.user_id)
        if user and not user.enabled:
            _cache_session(token, now_ts, False, None)
            return False, None
        if user:
            _detach_user(db, user)
    _cache_session(token, now_ts, True, user)
    return True, user


def _session_token(request: Request) -> tuple[str | None, bool]:
    """Токен сессии и признак того, что он пришёл в cookie (а не в заголовке)."""
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if token:
        return token, True
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header[7:].strip() or None, False
    return None, False


def _is_unsafe_method(request: Request) -> bool:
    return request.method.upper() not in ("GET", "HEAD", "OPTIONS")


def _cross_site_response() -> JSONResponse:
    return JSONResponse(
        {
            "error": "Запрос отклонён: он отправлен со стороннего сайта",
            "code": "cross_site_request",
        },
        status_code=403,
    )


class ApiKeyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = _get_scope_path(request)

        # Общедоступные маршруты (статика css/js/шрифты, вход, проверка статуса сессии, health probe и корень /)
        if path == "/" or (path.startswith("/ui/static/") and not path.endswith(".html")) or path in _PUBLIC_PATHS:
            if path in _PUBLIC_PATHS and _is_unsafe_method(request) and is_cross_site_request(request):
                # Вход с чужого сайта (login CSRF) подменил бы сессию пользователя.
                return _cross_site_response()
            return await call_next(request)

        user = None
        is_authenticated = False
        # Способ аутентификации определяет, возможна ли подделка запроса чужим
        # сайтом: браузер сам прикладывает cookie, а доверие к IP вообще не
        # требует секретов. Ключ в заголовке X-Api-Key чужая страница задать не может.
        browser_ambient_auth = False
        forbidden_response = None
        unauthorized_response = None

        is_docs_request = (
            path in ("/docs", "/redoc", "/openapi.json", "/api/docs", "/api/docs.html")
            or path.startswith(("/docs", "/redoc", "/api/docs"))
        )
        is_page_request = (
            is_docs_request
            or path in ("/quality-guide", "/quality-guide.html", "/wiki", "/wiki.html")
            or path.startswith(("/quality-guide", "/wiki"))
            or path.endswith(".html")
        )

        # 1. Извлекаем токен сессии (из Cookie или заголовка Authorization)
        token, token_from_cookie = _session_token(request)

        # Fast-path: если сессия есть в кэше памяти и валидна, пропускаем без обращения к БД
        if token:
            now_ts = time.time()
            cached = _SESSION_USER_CACHE.get(token)
            if cached and (now_ts - cached[0] < _SESSION_CACHE_TTL) and cached[1]:
                if token_from_cookie and _is_unsafe_method(request) and is_cross_site_request(request):
                    return _cross_site_response()
                request.state.user = cached[2]
                request.state.is_authenticated = True
                return await call_next(request)

        db = SessionLocal()
        try:
            settings = get_or_create_settings(db)
            local_auth_bypass = bool(
                settings.login_enabled
                and getattr(settings, "auth_disabled_for_local_addresses", False)
                and is_private_ip(get_client_ip(request))
                and is_local_host_header(request.headers.get("Host"))
            )

            is_valid_session, user = _get_valid_session_user(db, token)
            if is_valid_session:
                is_authenticated = True
                browser_ambient_auth = token_from_cookie
            else:
                # 2. Проверяем API-ключ
                header_key = request.headers.get("X-Api-Key")
                provided_key = header_key or request.query_params.get("apikey")
                if provided_key:
                    from app.models.db import User
                    if keys_match(provided_key, settings.api_key):
                        owner = db.query(User).filter(User.is_owner == True).first()  # noqa: E712
                        if owner:
                            _detach_user(db, owner)
                        user = owner
                        is_authenticated = True
                    else:
                        user_by_key = db.query(User).filter(User.api_key == provided_key, User.enabled == True).first()  # noqa: E712
                        if user_by_key:
                            is_allowed = user_by_key.is_owner or user_by_key.is_admin or (user_by_key.permissions or {}).get("use_api_key", False)
                            if not is_allowed:
                                forbidden_response = JSONResponse(
                                    {"error": "Использование API-ключа отключено для вашей учётной записи", "code": "api_key_forbidden"},
                                    status_code=403,
                                )
                            else:
                                _detach_user(db, user_by_key)
                                user = user_by_key
                                is_authenticated = True
                        else:
                            unauthorized_response = JSONResponse(
                                {"error": "Неверный или отсутствующий API-ключ (заголовок X-Api-Key)", "code": "invalid_api_key"},
                                status_code=401,
                            )
                elif local_auth_bypass:
                    from app.models.db import User
                    owner = db.query(User).filter(User.is_owner == True).first()  # noqa: E712
                    if owner:
                        _detach_user(db, owner)
                    user = owner
                    is_authenticated = owner is not None
                    browser_ambient_auth = True
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
                        _detach_user(db, owner)
                    user = owner
                    is_authenticated = True
                    browser_ambient_auth = True
        finally:
            db.close()

        if forbidden_response:
            return forbidden_response
        if unauthorized_response:
            return unauthorized_response
        if browser_ambient_auth and _is_unsafe_method(request) and is_cross_site_request(request):
            return _cross_site_response()

        request.state.user = user
        request.state.is_authenticated = is_authenticated
        return await call_next(request)
