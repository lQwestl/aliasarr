from __future__ import annotations

from typing import Optional, List, Dict, Any

import hashlib
import os
import secrets

try:
    from sqlalchemy.orm import Session
    from app.models.db import AppSettings
except ImportError:
    Session = object
    AppSettings = None

# Переменная окружения, через которую можно задать API-ключ при деплое
# (docker-compose), чтобы не приходилось доставать его из логов контейнера.
ENV_API_KEY_VAR = "ALIASARR_API_KEY"

# Старые "заглушки"-пути, которые раньше подставлялись по умолчанию в "Папки и
# переименование по категориям" ещё до того, как пользователь успевал задать
# свои реальные пути. Нажатие "Обзор" на них падало с "Папка не найдена",
# т.к. этих папок обычно нет в контейнере пользователя. Разово чистим их у
# уже существующих БД, обновлённых с более старой версии — новые инсталляции
# и так получают пустые значения по умолчанию (см. models/db.py).
_LEGACY_FOLDER_DEFAULTS = {
    "root_folder_movies": "/data/movies",
    "root_folder_series": "/data/series",
    "root_folder_anime": "/data/anime",
    "download_folder_movies": "/downloads/movies",
    "download_folder_series": "/downloads/series",
    "download_folder_anime": "/downloads/anime",
}

_OLD_SERIES_DEFAULTS = {
    "{show_title}/Season {season:02d}/{show_title} - S{season:02d}E{episode:02d} - {episode_title}",
    "{show_title} - S{season:02d}E{episode:02d} - {episode_title}",
}
_OLD_ANIME_DEFAULTS = {
    "{show_title}/Season {season:02d}/{show_title} - S{season:02d}E{episode:02d} - {absolute:03d} - {episode_title}",
}
_OLD_MOVIE_DEFAULTS = {
    "{show_title} ({year})/{show_title} ({year}) {quality}",
    "{show_title} ({year}) {quality}",
}


def _clear_legacy_folder_defaults(db: Session, settings: AppSettings) -> None:
    changed = False
    for field, legacy_value in _LEGACY_FOLDER_DEFAULTS.items():
        current = getattr(settings, field, None)
        if current == legacy_value and not os.path.isdir(current):
            setattr(settings, field, "")
            changed = True

    if getattr(settings, "rename_template_series", None) in _OLD_SERIES_DEFAULTS:
        settings.rename_template_series = "{Series Title} - S{season:00}E{episode:00} - {Episode Title} {Quality Full}"
        settings.rename_template = settings.rename_template_series
        changed = True
    if getattr(settings, "rename_template_anime", None) in _OLD_ANIME_DEFAULTS:
        settings.rename_template_anime = "{Series Title} - S{season:00}E{episode:00} - {Episode Title} {Quality Full}"
        changed = True
    if getattr(settings, "rename_template_movie", None) in _OLD_MOVIE_DEFAULTS:
        settings.rename_template_movie = "{Movie Title} ({Release Year}) {Quality Full}"
        changed = True

    if changed:
        db.add(settings)
        db.commit()
        db.refresh(settings)


_LEGACY_CHECKED = False


def get_or_create_settings(db: Session) -> AppSettings:
    global _LEGACY_CHECKED
    settings = db.get(AppSettings, 1)
    env_key = os.getenv(ENV_API_KEY_VAR, "").strip()

    if settings is None:
        settings = AppSettings(id=1, api_key=env_key or secrets.token_hex(16))
        db.add(settings)
        db.commit()
        db.refresh(settings)
    elif env_key and settings.api_key != env_key:
        # Ключ, заданный через переменную окружения, имеет приоритет —
        # это позволяет зафиксировать ключ в docker-compose.yml один раз.
        settings.api_key = env_key
        db.add(settings)
        db.commit()
        db.refresh(settings)

    if not _LEGACY_CHECKED:
        _clear_legacy_folder_defaults(db, settings)
        _LEGACY_CHECKED = True

    return settings


def is_api_key_from_env() -> bool:
    return bool(os.getenv(ENV_API_KEY_VAR, "").strip())


def regenerate_api_key(db: Session) -> AppSettings:
    if is_api_key_from_env():
        raise ValueError(
            f"Ключ задан через переменную окружения {ENV_API_KEY_VAR} — "
            "измените её в docker-compose.yml и перезапустите контейнер, "
            "либо уберите переменную, чтобы управлять ключом из интерфейса."
        )
    settings = get_or_create_settings(db)
    settings.api_key = secrets.token_hex(16)
    db.add(settings)
    db.commit()
    db.refresh(settings)
    write_api_key_file(settings.api_key)
    return settings


def write_api_key_file(api_key: str) -> None:
    try:
        os.makedirs("/config", exist_ok=True)
        with open("/config/api_key.txt", "w") as f:
            f.write(api_key + "\n")
    except OSError:
        pass  # напр. при локальном запуске без смонтированного /config


# ---------------------------------------------------------------------------
# Пароли для логина (PBKDF2, без внешних зависимостей вроде passlib)
# ---------------------------------------------------------------------------

_PBKDF2_ITERATIONS = 260_000


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), _PBKDF2_ITERATIONS)
    return f"{salt}${digest.hex()}"


def verify_password(password: str, password_hash: str) -> bool:
    try:
        salt, digest_hex = password_hash.split("$", 1)
    except (ValueError, AttributeError):
        return False
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), _PBKDF2_ITERATIONS)
    return secrets.compare_digest(digest.hex(), digest_hex)
