# -*- coding: utf-8 -*-
from __future__ import annotations

import copy
import re
from typing import Any, Optional

try:
    from fastapi import FastAPI
    from fastapi.openapi.utils import get_openapi
except ImportError:
    FastAPI = Any  # type: ignore
    get_openapi = None  # type: ignore

from app.version import VERSION as APP_VERSION
from app.services.openapi_catalog import (
    COMMON_PARAM_DESCRIPTIONS,
    ENDPOINT_CATALOG,
    RESPONSES_EN,
    RESPONSES_RU,
)

# In-memory cache for OpenAPI schemas
_CACHED_SCHEMAS: dict[str, dict[str, Any]] = {}

TAGS_METADATA_RU = [
    {
        "name": "shows",
        "description": "Управление библиотекой: фильмы, сериалы, аниме, сезоны, эпизоды, мультиязычные алиасы и правила смещения (+Offset).",
    },
    {
        "name": "settings",
        "description": "Конфигурация системы: корневые папки библиотеки, профили качества, резервные копии, SSL и уведомления.",
    },
    {
        "name": "indexers",
        "description": "Управление торрент-индексаторами, протоколы Torznab/Newznab, профили поиска и интеллектуальный Rate Limiter.",
    },
    {
        "name": "download-clients",
        "description": "Подключение торрент-клиентов (qBittorrent, Transmission, Deluge, rTorrent) и персональные лимиты сидирования.",
    },
    {
        "name": "operations",
        "description": "Фоновые сервисные задачи: полное сканирование диска, автопоиск разыскиваемых серий (WANTED) и очистка мусора.",
    },
    {
        "name": "blocklist",
        "description": "Черный список нежелательных релизов, защита от даунгрейда качества и MediaProbe-проверки файлов.",
    },
    {
        "name": "collections",
        "description": "Саги и коллекции фильмов TMDb: пакетный мониторинг, автоматическое связывание и поиск частей саги.",
    },
    {
        "name": "custom_formats",
        "description": "Кастомные форматы (CF): правила скоринга релизов, ранжирование студий озвучки, видеокодеков и аудиодорожек.",
    },
    {
        "name": "audit",
        "description": "Журнал аудита безопасности: фиксация действий пользователей, изменений конфигурации и авторизаций.",
    },
    {
        "name": "release-logs",
        "description": "История парсинга и захвата релизов: детальные логи решений интеллектуального Decision Engine.",
    },
    {
        "name": "dataset",
        "description": "Импорт и экспорт эталонных наборов данных для валидации алгоритмов парсера названий и студий.",
    },
    {
        "name": "metadata",
        "description": "Внешние провайдеры метаданных: Kinopoisk, TMDb, TheTVDb, AniList, Shikimori и TVMaze.",
    },
    {
        "name": "users",
        "description": "Управление учётными записями, ролевой моделью доступа (RBAC), правами и персональными API-ключами.",
    },
    {
        "name": "auth",
        "description": "Аутентификация пользователей, управление активными сессиями, Cookie и двухфакторная защита (2FA TOTP).",
    },
    {
        "name": "system",
        "description": "Системные метрики, статус служб, перезагрузка сервиса Aliasarr, просмотр журналов логов и управление SSL.",
    },
]

TAGS_METADATA_EN = [
    {
        "name": "shows",
        "description": "Library management: movies, series, anime, seasons, episodes, multi-language aliases, and episode offset rules.",
    },
    {
        "name": "settings",
        "description": "System configuration: root library paths, quality profiles, automated backups, SSL, and notification channels.",
    },
    {
        "name": "indexers",
        "description": "Torrent indexers management, Torznab/Newznab protocols, search categories, and host rate limiting.",
    },
    {
        "name": "download-clients",
        "description": "Download client integration (qBittorrent, Transmission, Deluge, rTorrent) and seeding ratio/time limits.",
    },
    {
        "name": "operations",
        "description": "Background service jobs: disk library scan, WANTED episode auto-search, and debris directory cleanup.",
    },
    {
        "name": "blocklist",
        "description": "Release blocklist, quality downgrade protection, and automated MediaProbe stream verification.",
    },
    {
        "name": "collections",
        "description": "TMDb movie sagas and franchises: batch monitoring, automated linking, and missing installment searches.",
    },
    {
        "name": "custom_formats",
        "description": "Custom Formats (CF): release scoring rules, ranking preferred dubbing groups, video codecs, and audio formats.",
    },
    {
        "name": "audit",
        "description": "Security audit logs: tracking administrative changes, authentication events, and user actions.",
    },
    {
        "name": "release-logs",
        "description": "Release grab and parsing history: granular trace logs of Decision Engine candidate evaluations.",
    },
    {
        "name": "dataset",
        "description": "Import and export benchmark datasets for validating title parser expressions and dubbing rules.",
    },
    {
        "name": "metadata",
        "description": "External metadata providers: Kinopoisk, TMDb, TheTVDb, AniList, Shikimori, and TVMaze.",
    },
    {
        "name": "users",
        "description": "User accounts, role-based access control (RBAC), granular permissions, and personal API keys.",
    },
    {
        "name": "auth",
        "description": "User authentication, session tokens, secure cookies, and two-factor authentication (2FA TOTP).",
    },
    {
        "name": "system",
        "description": "System health metrics, service status, Aliasarr restart trigger, live logs viewer, and SSL management.",
    },
]

DESCRIPTION_RU = f"""
Добро пожаловать в официальную документацию REST API системы **Aliasarr** (версия {APP_VERSION}).

API предоставляет полный программный доступ ко всем функциям системы: управлению медиатекой, мониторингу торрент-клиентов, настройке индексаторов, планировщику автоматического поиска и проверке качества релизов.

---

### Аутентификация

Для выполнения запросов к защищенным эндпоинтам поддерживаются два способа:
1. **API-ключ (Header или Query)**:
   - Заголовок: `X-Api-Key: <ВАШ_API_КЛЮЧ>`
   - Параметр URL: `?apikey=<ВАШ_API_КЛЮЧ>`
2. **Сессионный Cookie**:
   - Cookie `aliasarr_session`, устанавливаемый автоматически при входе через веб-интерфейс или эндпоинт `/api/v1/auth/login`.

---

### Формат ответов и коды состояния
- `200 OK` / `201 Created` — успешное выполнение запроса.
- `400 Bad Request` — ошибка валидации переданных параметров.
- `401 Unauthorized` — не передан или недействителен API-ключ / сессия.
- `403 Forbidden` — у пользователя недостаточно прав (RBAC) для выполнения операции.
- `404 Not Found` — запрашиваемый ресурс (тайтл, серия, индексатор) не найден.
- `409 Conflict` — конфликт состояния (например, дубликат тайтла в библиотеке).
- `429 Too Many Requests` — превышение лимита запросов (Rate Limiter).
""".strip()

DESCRIPTION_EN = f"""
Welcome to the official REST API documentation for **Aliasarr** (version {APP_VERSION}).

The API grants complete programmatic control over every system capability: media library indexing, download client lifecycle, indexer proxies, scheduled WANTED auto-search, and release quality verification.

---

### Authentication

Two authentication methods are supported for secure endpoints:
1. **API Key (Header or Query)**:
   - Header: `X-Api-Key: <YOUR_API_KEY>`
   - Query parameter: `?apikey=<YOUR_API_KEY>`
2. **Session Cookie**:
   - The `aliasarr_session` cookie created automatically upon login via the web UI or the `/api/v1/auth/login` endpoint.

---

### Response Codes & Formats
- `200 OK` / `201 Created` — Request completed successfully.
- `400 Bad Request` — Payload or parameter validation error.
- `401 Unauthorized` — Missing or invalid API key / session token.
- `403 Forbidden` — Insufficient role permissions (RBAC) to execute this operation.
- `404 Not Found` — Requested entity (show, episode, indexer) was not found.
- `409 Conflict` — State conflict (e.g. show already exists in the library).
- `429 Too Many Requests` — Rate limit exceeded.
""".strip()

# Backward-compatible summary overrides: (path, method) -> (ru_summary, en_summary)
ENDPOINT_SUMMARIES: dict[tuple[str, str], tuple[str, str]] = {
    key: (val[0], val[1]) for key, val in ENDPOINT_CATALOG.items()
}


def _humanize_func_name(func_name: str, lang: str) -> str:
    """Fallback generator for summaries based on function name."""
    clean = re.sub(r"^([a-z]+)_route$", r"\1", func_name)
    parts = clean.split("_")
    verb = parts[0] if parts else ""
    rest = " ".join(parts[1:]) if len(parts) > 1 else ""

    verbs_ru = {
        "list": "Список",
        "get": "Получить",
        "create": "Создать",
        "add": "Добавить",
        "update": "Обновить",
        "delete": "Удалить",
        "remove": "Удалить",
        "clear": "Очистить",
        "refresh": "Обновить",
        "search": "Поиск",
        "test": "Проверить",
        "scan": "Сканировать",
        "download": "Скачать",
        "export": "Экспортировать",
        "import": "Импортировать",
        "trigger": "Запустить",
        "check": "Проверить",
        "setup": "Настроить",
        "confirm": "Подтвердить",
        "disable": "Отключить",
    }

    if lang == "en":
        return " ".join(word.capitalize() for word in parts)
    else:
        ru_verb = verbs_ru.get(verb, verb.capitalize())
        return f"{ru_verb} {rest}".strip()


def get_localized_openapi(app: FastAPI, lang: str = "ru") -> dict[str, Any]:
    """Generates and returns a fully localized OpenAPI 3.1 schema for the requested language."""
    target_lang = "en" if str(lang).lower().startswith("en") else "ru"

    if target_lang in _CACHED_SCHEMAS:
        return copy.deepcopy(_CACHED_SCHEMAS[target_lang])

    title = "Aliasarr — Справочник API" if target_lang == "ru" else "Aliasarr — API Documentation"
    description = DESCRIPTION_RU if target_lang == "ru" else DESCRIPTION_EN
    tags_metadata = TAGS_METADATA_RU if target_lang == "ru" else TAGS_METADATA_EN

    # Generate base schema via FastAPI get_openapi
    schema = get_openapi(
        title=title,
        version=APP_VERSION,
        description=description,
        routes=app.routes,
        tags=tags_metadata,
    )

    # Localize security schemes
    schema["components"] = schema.get("components", {})
    if target_lang == "ru":
        api_key_desc = "Системный или персональный API-ключ Aliasarr (в заголовке X-Api-Key или параметре ?apikey=)"
        cookie_desc = "Сессионный Cookie (aliasarr_session), устанавливаемый после успешного входа в систему"
    else:
        api_key_desc = "System or personal Aliasarr API key (via X-Api-Key header or ?apikey= query param)"
        cookie_desc = "Session Cookie (aliasarr_session) issued after successful authentication"

    schema["components"]["securitySchemes"] = {
        "ApiKeyAuth": {
            "type": "apiKey",
            "in": "header",
            "name": "X-Api-Key",
            "description": api_key_desc,
        },
        "CookieAuth": {
            "type": "apiKey",
            "in": "cookie",
            "name": "aliasarr_session",
            "description": cookie_desc,
        },
    }
    schema["security"] = [{"ApiKeyAuth": []}, {"CookieAuth": []}]

    # Enhance and localize path operation summaries, descriptions, parameters, and responses
    paths = schema.get("paths", {})
    cyrillic_pattern = re.compile(r"[\u0400-\u04FF]")

    for path, path_item in paths.items():
        if not isinstance(path_item, dict):
            continue
        for method, operation in path_item.items():
            if method.lower() not in ("get", "post", "put", "delete", "patch"):
                continue
            if not isinstance(operation, dict):
                continue

            method_upper = method.upper()
            lookup_key = (path, method_upper)

            # 1. Exact match in explicit catalog
            if lookup_key in ENDPOINT_CATALOG:
                ru_summary, en_summary, ru_desc, en_desc = ENDPOINT_CATALOG[lookup_key]
                operation["summary"] = ru_summary if target_lang == "ru" else en_summary
                operation["description"] = ru_desc if target_lang == "ru" else en_desc
            elif lookup_key in ENDPOINT_SUMMARIES:
                ru_summary, en_summary = ENDPOINT_SUMMARIES[lookup_key]
                operation["summary"] = ru_summary if target_lang == "ru" else en_summary
                if target_lang == "en" and operation.get("description") and cyrillic_pattern.search(operation["description"]):
                    operation["description"] = en_summary
            else:
                # 2. Derive from operation_id or existing summary
                op_id = operation.get("operation_id", "")
                existing_summary = operation.get("summary", "")
                if existing_summary and target_lang == "en":
                    pass
                elif op_id:
                    operation["summary"] = _humanize_func_name(op_id, target_lang)

                if target_lang == "en" and operation.get("description") and cyrillic_pattern.search(operation["description"]):
                    operation["description"] = operation.get("summary", "")

            # 2. Sanitize English mode to ensure 100% Cyrillic-free output
            if target_lang == "en":
                if operation.get("summary") and cyrillic_pattern.search(operation["summary"]):
                    op_id = operation.get("operation_id", "")
                    operation["summary"] = _humanize_func_name(op_id, "en") if op_id else "API Operation"
                if operation.get("description") and cyrillic_pattern.search(operation["description"]):
                    operation["description"] = operation.get("summary", "")
            else:
                # In Russian mode, ensure non-empty description
                if not operation.get("description"):
                    operation["description"] = operation.get("summary", "")

            # 3. Localize parameters (path, query, header)
            parameters = operation.get("parameters", [])
            if isinstance(parameters, list):
                for param in parameters:
                    if not isinstance(param, dict):
                        continue
                    p_name = param.get("name", "")
                    if p_name in COMMON_PARAM_DESCRIPTIONS:
                        p_ru, p_en = COMMON_PARAM_DESCRIPTIONS[p_name]
                        param["description"] = p_ru if target_lang == "ru" else p_en
                    elif target_lang == "en" and param.get("description") and cyrillic_pattern.search(param["description"]):
                        param["description"] = f"Parameter '{p_name}'"

            # 4. Localize common responses
            responses = operation.get("responses", {})
            if isinstance(responses, dict):
                for code, resp in responses.items():
                    if not isinstance(resp, dict):
                        continue
                    if target_lang == "ru":
                        if code in RESPONSES_RU:
                            resp["description"] = RESPONSES_RU[code]
                    else:
                        if code in RESPONSES_EN:
                            resp["description"] = RESPONSES_EN[code]
                        elif resp.get("description") and cyrillic_pattern.search(resp["description"]):
                            resp["description"] = "Server response"

    _CACHED_SCHEMAS[target_lang] = schema
    return copy.deepcopy(schema)


def clear_openapi_cache() -> None:
    """Clears the cached schemas when routes or settings change."""
    _CACHED_SCHEMAS.clear()
