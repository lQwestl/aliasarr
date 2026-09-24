import os
import io
import shutil
import base64
import asyncio
import ipaddress
import logging
import socket
from typing import Optional, Any
from urllib.parse import urljoin, urlsplit

logger = logging.getLogger(__name__)

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False


def get_media_cover_dir() -> str:
    """
    Возвращает базовую директорию для хранения обложек MediaCover.
    В Docker-окружении: /config/MediaCover
    В локальном окружении: ./config/MediaCover
    """
    env_dir = os.getenv("ALIASARR_MEDIA_COVER_DIR") or os.getenv("MEDIA_COVER_DIR")
    if env_dir:
        return os.path.abspath(env_dir)

    is_docker = os.path.exists("/.dockerenv") or os.getenv("ALIASARR_DOCKER") == "true"
    base_config = "/config" if (is_docker or os.path.exists("/config")) else os.path.abspath("./config")
    return os.path.join(base_config, "MediaCover")


def get_show_poster_dir(show_id: int) -> str:
    return os.path.join(get_media_cover_dir(), "shows", str(show_id))


def get_show_poster_path(show_id: int) -> str:
    return os.path.join(get_show_poster_dir(show_id), "poster.jpg")


def get_collection_poster_dir(collection_id: int) -> str:
    return os.path.join(get_media_cover_dir(), "collections", str(collection_id))


def get_collection_poster_path(collection_id: int) -> str:
    return os.path.join(get_collection_poster_dir(collection_id), "poster.jpg")


def get_collection_backdrop_path(collection_id: int) -> str:
    return os.path.join(get_collection_poster_dir(collection_id), "backdrop.jpg")


class NotAnImageError(ValueError):
    """Загруженные или скачанные байты не являются изображением."""


COVER_DOWNLOAD_MAX_BYTES = 15 * 1024 * 1024
COVER_DOWNLOAD_MAX_REDIRECTS = 3


def _is_public_address(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    return ip.is_global and not ip.is_multicast


async def _resolve_host(host: str, port: int) -> set[str]:
    infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return {info[4][0] for info in infos}


async def _require_public_host(url: str) -> None:
    """Постеры берутся из публичных CDN. Адрес, который резолвится в локальную
    сеть, loopback или метаданные облака, означает попытку SSRF: сервер пошёл бы
    туда от своего имени, а тело ответа потом отдавалось бы через /poster."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError("Недопустимый адрес изображения")
    if parts.username or parts.password:
        raise ValueError("Адрес изображения не должен содержать учётные данные")
    host = parts.hostname
    port = parts.port or (443 if parts.scheme == "https" else 80)
    addresses = await _resolve_host(host, port)
    if not addresses or not all(_is_public_address(addr) for addr in addresses):
        raise ValueError(f"Адрес изображения {host} указывает не в интернет")


async def fetch_remote_image(url: str) -> Optional[bytes]:
    """Скачивает изображение по публичному адресу с ограничением размера.

    Каждый переход по редиректу проверяется заново: иначе публичный адрес мог бы
    перенаправить запрос во внутреннюю сеть.
    """
    import httpx

    current = url
    async with httpx.AsyncClient(timeout=20, follow_redirects=False, headers={"User-Agent": "Aliasarr/1.0.0"}) as client:
        for _ in range(COVER_DOWNLOAD_MAX_REDIRECTS + 1):
            await _require_public_host(current)
            async with client.stream("GET", current) as resp:
                if resp.status_code in (301, 302, 303, 307, 308):
                    location = resp.headers.get("location")
                    if not location:
                        return None
                    current = urljoin(current, location)
                    continue
                if resp.status_code != 200:
                    logger.debug("Failed to download image from %s: HTTP %s", current, resp.status_code)
                    return None
                declared = resp.headers.get("content-length")
                if declared and declared.isdigit() and int(declared) > COVER_DOWNLOAD_MAX_BYTES:
                    raise ValueError("Изображение слишком большое")
                chunks = []
                total = 0
                async for chunk in resp.aiter_bytes():
                    total += len(chunk)
                    if total > COVER_DOWNLOAD_MAX_BYTES:
                        raise ValueError("Изображение слишком большое")
                    chunks.append(chunk)
                return b"".join(chunks)
    return None


def optimize_image(
    image_bytes: bytes,
    max_width: int = 600,
    max_height: int = 900,
    quality: int = 85,
) -> bytes:
    """
    Оптимизирует изображение постера:
    - Масштабирует до стандартного размера (ширина до max_width, высота до max_height);
    - Приводит альфа-канал к нейтральному темному фону (для PNG/WebP с прозрачностью);
    - Сжимает в формате JPEG с progressive=True, optimize=True и качеством quality.

    Байты, которые не удаётся разобрать как изображение, отклоняются (NotAnImageError),
    а не сохраняются как есть: иначе ответ произвольного адреса, указанного вместо
    ссылки на постер, становился доступен для чтения через эндпоинт постера.
    """
    if not image_bytes:
        raise NotAnImageError("Пустое изображение")
    if not HAS_PIL:
        return image_bytes

    try:
        with Image.open(io.BytesIO(image_bytes)) as img:
            # 1. Приведение цветового режима к RGB (удаление альфа-канала)
            if img.mode in ("RGBA", "LA", "P"):
                bg = Image.new("RGB", img.size, (20, 24, 33))  # нейтральный темный фон под стиль интерфейса
                if img.mode == "P":
                    img = img.convert("RGBA")
                mask = img.split()[-1] if len(img.split()) == 4 else None
                bg.paste(img, (0, 0), mask)
                img = bg
            elif img.mode != "RGB":
                img = img.convert("RGB")

            # 2. Пропорциональное масштабирование
            w, h = img.size
            if w > max_width or h > max_height:
                img.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)

            # 3. Сохранение в буфер JPEG
            out_buf = io.BytesIO()
            img.save(out_buf, format="JPEG", quality=quality, optimize=True, progressive=True)
            return out_buf.getvalue()
    except Exception as e:
        raise NotAnImageError(f"Файл не является изображением: {e}") from e


def attach_version_to_cover_url(url: Optional[str], timestamp_obj: Optional[Any] = None) -> Optional[str]:
    """
    Добавляет параметр ?v={timestamp} к локальному URL обложки или фона.
    Если параметр версии уже присутствует или URL внешний, возвращает исходный URL.
    При отсутствии переданного timestamp_obj пытается взять время модификации mtime файла с диска.
    """
    if not url or not isinstance(url, str):
        return url
    trimmed = url.strip()
    if "?" in trimmed:
        return trimmed

    # Проверяем, локальный ли это URL постера или бэкдропа
    mtime = None
    if timestamp_obj:
        try:
            mtime = int(timestamp_obj.timestamp())
        except Exception:
            mtime = None

    if mtime is None:
        try:
            if trimmed.startswith("/api/v1/shows/") and trimmed.endswith("/poster"):
                sid = int(trimmed.split("/")[4])
                p_path = get_show_poster_path(sid)
                if os.path.isfile(p_path):
                    mtime = int(os.path.getmtime(p_path))
            elif trimmed.startswith("/api/v1/collections/") and trimmed.endswith("/poster"):
                cid = int(trimmed.split("/")[4])
                p_path = get_collection_poster_path(cid)
                if os.path.isfile(p_path):
                    mtime = int(os.path.getmtime(p_path))
            elif trimmed.startswith("/api/v1/collections/") and trimmed.endswith("/backdrop"):
                cid = int(trimmed.split("/")[4])
                b_path = get_collection_backdrop_path(cid)
                if os.path.isfile(b_path):
                    mtime = int(os.path.getmtime(b_path))
        except Exception:
            mtime = None

    if mtime is not None:
        return f"{trimmed}?v={mtime}"
    return trimmed


async def save_show_poster(show_id: int, image_bytes: bytes) -> str:
    """
    Оптимизирует и сохраняет постер тайтла на диск в /config/MediaCover/shows/{show_id}/poster.jpg.
    Возвращает локальный URL эндпоинта /api/v1/shows/{show_id}/poster с версией ?v={mtime}.
    """
    opt_bytes = optimize_image(image_bytes)
    poster_dir = get_show_poster_dir(show_id)
    os.makedirs(poster_dir, exist_ok=True)
    poster_path = get_show_poster_path(show_id)
    with open(poster_path, "wb") as f:
        f.write(opt_bytes)
    try:
        mtime = int(os.path.getmtime(poster_path))
        return f"/api/v1/shows/{show_id}/poster?v={mtime}"
    except Exception:
        return f"/api/v1/shows/{show_id}/poster"


async def save_collection_poster(collection_id: int, image_bytes: bytes) -> str:
    """
    Оптимизирует и сохраняет постер коллекции на диск в /config/MediaCover/collections/{collection_id}/poster.jpg.
    Возвращает локальный URL эндпоинта /api/v1/collections/{collection_id}/poster с версией ?v={mtime}.
    """
    opt_bytes = optimize_image(image_bytes)
    poster_dir = get_collection_poster_dir(collection_id)
    os.makedirs(poster_dir, exist_ok=True)
    poster_path = get_collection_poster_path(collection_id)
    with open(poster_path, "wb") as f:
        f.write(opt_bytes)
    try:
        mtime = int(os.path.getmtime(poster_path))
        return f"/api/v1/collections/{collection_id}/poster?v={mtime}"
    except Exception:
        return f"/api/v1/collections/{collection_id}/poster"


async def download_and_store_show_cover(show_id: int, remote_url_or_data: str) -> Optional[str]:
    """
    Скачивает постер по внешнему URL (CDN) или декодирует Base64 DataURL,
    сохраняет оптимизированный файл на диск и возвращает локальный URL с параметром версии ?v={mtime}.
    """
    if not remote_url_or_data or not str(remote_url_or_data).strip():
        return None

    raw_val = str(remote_url_or_data).strip()

    # 1. Если это уже локальный эндпоинт и файл существует на диске
    if raw_val.startswith(f"/api/v1/shows/{show_id}/poster"):
        poster_path = get_show_poster_path(show_id)
        if os.path.isfile(poster_path):
            if "?" not in raw_val:
                try:
                    return f"/api/v1/shows/{show_id}/poster?v={int(os.path.getmtime(poster_path))}"
                except Exception:
                    pass
            return raw_val

    # 2. Если это DataURL Base64 (ручная загрузка пользователем)
    if raw_val.startswith("data:image/"):
        try:
            _, encoded = raw_val.split(",", 1)
            image_bytes = base64.b64decode(encoded)
            if image_bytes:
                return await save_show_poster(show_id, image_bytes)
        except Exception as e:
            logger.debug("Failed to decode base64 cover for show %s: %s", show_id, e)
        return None

    # 3. Если это внешняя HTTP/HTTPS ссылка на CDN
    if raw_val.startswith(("http://", "https://")):
        try:
            content = await fetch_remote_image(raw_val)
            if content:
                return await save_show_poster(show_id, content)
        except Exception as e:
            logger.debug("Error downloading cover for show %s from %s: %s", show_id, raw_val, e)

    return None


async def download_and_store_collection_cover(collection_id: int, remote_url_or_data: str) -> Optional[str]:
    """
    Скачивает постер коллекции по внешнему URL (TMDb) или декодирует Base64,
    сохраняет файл на диск и возвращает локальный URL с параметром версии ?v={mtime}.
    """
    if not remote_url_or_data or not str(remote_url_or_data).strip():
        return None

    raw_val = str(remote_url_or_data).strip()

    if raw_val.startswith(f"/api/v1/collections/{collection_id}/poster"):
        c_path = get_collection_poster_path(collection_id)
        if os.path.isfile(c_path):
            if "?" not in raw_val:
                try:
                    return f"/api/v1/collections/{collection_id}/poster?v={int(os.path.getmtime(c_path))}"
                except Exception:
                    pass
            return raw_val

    if raw_val.startswith("data:image/"):
        try:
            _, encoded = raw_val.split(",", 1)
            image_bytes = base64.b64decode(encoded)
            if image_bytes:
                return await save_collection_poster(collection_id, image_bytes)
        except Exception as e:
            logger.debug("Failed to decode base64 cover for collection %s: %s", collection_id, e)
        return None

    if raw_val.startswith(("http://", "https://")):
        try:
            content = await fetch_remote_image(raw_val)
            if content:
                return await save_collection_poster(collection_id, content)
        except Exception as e:
            logger.debug("Error downloading cover for collection %s from %s: %s", collection_id, raw_val, e)

    return None


async def save_collection_backdrop(collection_id: int, image_bytes: bytes) -> str:
    """
    Оптимизирует и сохраняет фоновое изображение (backdrop) коллекции на диск в
    /config/MediaCover/collections/{collection_id}/backdrop.jpg.
    Возвращает локальный URL эндпоинта /api/v1/collections/{collection_id}/backdrop с версией ?v={mtime}.
    """
    opt_bytes = optimize_image(image_bytes, max_width=1280, max_height=720, quality=80)
    poster_dir = get_collection_poster_dir(collection_id)
    os.makedirs(poster_dir, exist_ok=True)
    backdrop_path = get_collection_backdrop_path(collection_id)
    with open(backdrop_path, "wb") as f:
        f.write(opt_bytes)
    try:
        mtime = int(os.path.getmtime(backdrop_path))
        return f"/api/v1/collections/{collection_id}/backdrop?v={mtime}"
    except Exception:
        return f"/api/v1/collections/{collection_id}/backdrop"


async def download_and_store_collection_backdrop(collection_id: int, remote_url_or_data: str) -> Optional[str]:
    """
    Скачивает фон коллекции по внешнему URL (TMDb) или декодирует Base64,
    сохраняет файл на диск и возвращает локальный URL с параметром версии ?v={mtime}.
    """
    if not remote_url_or_data or not str(remote_url_or_data).strip():
        return None

    raw_val = str(remote_url_or_data).strip()

    if raw_val.startswith(f"/api/v1/collections/{collection_id}/backdrop"):
        b_path = get_collection_backdrop_path(collection_id)
        if os.path.isfile(b_path):
            if "?" not in raw_val:
                try:
                    return f"/api/v1/collections/{collection_id}/backdrop?v={int(os.path.getmtime(b_path))}"
                except Exception:
                    pass
            return raw_val

    if raw_val.startswith("data:image/"):
        try:
            _, encoded = raw_val.split(",", 1)
            image_bytes = base64.b64decode(encoded)
            if image_bytes:
                return await save_collection_backdrop(collection_id, image_bytes)
        except Exception as e:
            logger.debug("Failed to decode base64 backdrop for collection %s: %s", collection_id, e)
        return None

    if raw_val.startswith(("http://", "https://")):
        try:
            content = await fetch_remote_image(raw_val)
            if content:
                return await save_collection_backdrop(collection_id, content)
        except Exception as e:
            logger.debug("Error downloading backdrop for collection %s from %s: %s", collection_id, raw_val, e)

    return None


def delete_show_cover(show_id: int) -> bool:
    """Удаляет директорию с локальными обложками тайтла при удалении карточки."""
    poster_dir = get_show_poster_dir(show_id)
    if os.path.exists(poster_dir):
        try:
            shutil.rmtree(poster_dir, ignore_errors=True)
            return True
        except Exception as e:
            logger.debug("Failed to delete cover dir for show %s: %s", show_id, e)
    return False


def delete_collection_cover(collection_id: int) -> bool:
    """Удаляет директорию с локальными обложками коллекции при удалении."""
    poster_dir = get_collection_poster_dir(collection_id)
    if os.path.exists(poster_dir):
        try:
            shutil.rmtree(poster_dir, ignore_errors=True)
            return True
        except Exception as e:
            logger.debug("Failed to delete cover dir for collection %s: %s", collection_id, e)
    return False


def get_cover_etag(file_path: str) -> Optional[str]:
    """Генерирует ETag для заголовков HTTP-кэширования."""
    if os.path.isfile(file_path):
        try:
            st = os.stat(file_path)
            return f'"{int(st.st_mtime)}-{st.st_size}"'
        except Exception:
            return None
    return None


async def backfill_existing_covers(db) -> dict:
    """
    Фоновая миграция существующих тайтлов и киноколлекций:
    - Находит тайтлы и саги, у которых poster_url/backdrop_url начинаются с http или data:image;
    - Скачивает/декодирует их и сохраняет в /config/MediaCover/...;
    - Сохраняет оригинальную ссылку в *_source_url и переключает на локальные эндпоинты.
    """
    from app.models.db import Show, MovieCollection
    try:
        shows = db.query(Show).all()
    except Exception as e:
        logger.debug("backfill_existing_covers query shows failed: %s", e)
        shows = []

    migrated = 0
    for show in shows:
        target_path = get_show_poster_path(show.id)
        needs_migration = False
        url = show.poster_url or getattr(show, "poster_source_url", None)
        if not url:
            continue
        raw_url = str(url).strip()
        if raw_url.startswith(("http://", "https://", "data:image/")):
            needs_migration = True
        elif not os.path.isfile(target_path) and getattr(show, "poster_source_url", None):
            needs_migration = True
            raw_url = str(show.poster_source_url).strip()

        if needs_migration and raw_url:
            if raw_url.startswith(("http://", "https://")):
                show.poster_source_url = raw_url
            res = await download_and_store_show_cover(show.id, raw_url)
            if res:
                show.poster_url = res
                migrated += 1

    try:
        colls = db.query(MovieCollection).all()
    except Exception as e:
        logger.debug("backfill_existing_covers query collections failed: %s", e)
        colls = []

    for coll in colls:
        # 1. Постер коллекции
        p_path = get_collection_poster_path(coll.id)
        p_url = coll.poster_url or getattr(coll, "poster_source_url", None)
        if p_url:
            raw_p = str(p_url).strip()
            needs_p = raw_p.startswith(("http://", "https://", "data:image/")) or (not os.path.isfile(p_path) and getattr(coll, "poster_source_url", None))
            if needs_p:
                if raw_p.startswith(("http://", "https://")):
                    coll.poster_source_url = raw_p
                res_p = await download_and_store_collection_cover(coll.id, raw_p)
                if res_p:
                    coll.poster_url = res_p
                    migrated += 1

        # 2. Фон коллекции
        b_path = get_collection_backdrop_path(coll.id)
        b_url = coll.backdrop_url or getattr(coll, "backdrop_source_url", None)
        if b_url:
            raw_b = str(b_url).strip()
            needs_b = raw_b.startswith(("http://", "https://", "data:image/")) or (not os.path.isfile(b_path) and getattr(coll, "backdrop_source_url", None))
            if needs_b:
                if raw_b.startswith(("http://", "https://")):
                    coll.backdrop_source_url = raw_b
                res_b = await download_and_store_collection_backdrop(coll.id, raw_b)
                if res_b:
                    coll.backdrop_url = res_b
                    migrated += 1

    if migrated:
        try:
            db.commit()
        except Exception as e:
            logger.debug("backfill_existing_covers commit error: %s", e)

    return {"total": len(shows) + len(colls), "migrated": migrated}
