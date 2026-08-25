from __future__ import annotations

import asyncio
import datetime as dt
import logging
import os

try:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
except ImportError:
    class AsyncIOScheduler:  # type: ignore
        def __init__(self, *args, **kwargs): pass
        def start(self): pass
        def shutdown(self): pass
        def add_job(self, *args, **kwargs): pass

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.api import (
    audit_routes,
    auth_routes,
    custom_formats_routes,
    download_clients,
    indexers,
    metadata_routes,
    operations,
    release_logs_routes,
    settings_routes,
    shows,
    system_routes,
    users_routes,
)
from app.auth import ApiKeyMiddleware
from app.database import SessionLocal, init_db
from app.models.db import Indexer, MetadataSource, MetadataSourceType, User
from app.services.auto_search import run_wanted_search
from app.services.custom_formats import seed_default_custom_formats
from app.services.downloads_monitor import check_downloads
from app.services.log_service import install_db_log_handler, purge_old_logs
from app.services.settings_service import get_or_create_settings, hash_password, write_api_key_file
from app.services.tracker import recheck_all_active
from app.services.user_service import ensure_master_admin, get_current_user_optional

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("aliasarr.main")

_active_server = None
_restart_requested = False

from fastapi.openapi.utils import get_openapi

app = FastAPI(
    title="Aliasarr",
    description="*arr-подобный менеджер фильмов/сериалов/аниме с алиасами, "
                 "универсальным парсером серий и слежением за раздачей",
    version="1.2.0",
)


def custom_openapi():
    lang = "ru"
    try:
        from app.database import SessionLocal
        with SessionLocal() as db:
            s = get_or_create_settings(db)
            lang = s.language or "ru"
    except Exception:
        pass

    if lang == "en":
        desc = "*arr-like movie/series/anime manager with multi-language aliases, universal episode parser and release tracker"
    else:
        desc = "*arr-подобный менеджер фильмов/сериалов/аниме с алиасами, универсальным парсером серий и слежением за раздачей"

    schema = get_openapi(
        title="Aliasarr",
        version="1.2.0",
        description=desc,
        routes=app.routes,
    )
    schema["components"] = schema.get("components", {})
    schema["components"]["securitySchemes"] = {
        "ApiKeyAuth": {
            "type": "apiKey",
            "in": "header",
            "name": "X-Api-Key",
            "description": "Системный или пользовательский API-ключ Aliasarr",
        },
        "CookieAuth": {
            "type": "apiKey",
            "in": "cookie",
            "name": "aliasarr_session",
            "description": "Сессионный Cookie после авторизации в веб-интерфейсе",
        },
    }
    schema["security"] = [{"ApiKeyAuth": []}, {"CookieAuth": []}]
    return schema


app.openapi = custom_openapi

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(ApiKeyMiddleware)


@app.middleware("http")
async def add_no_cache_headers(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/ui/static") or request.url.path == "/":
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

app.include_router(shows.router)
app.include_router(indexers.router)
app.include_router(download_clients.router)
app.include_router(metadata_routes.router)
app.include_router(custom_formats_routes.router)
app.include_router(settings_routes.router)
app.include_router(operations.router)
app.include_router(auth_routes.router)
app.include_router(users_routes.router)
app.include_router(audit_routes.router)
app.include_router(system_routes.router)
app.include_router(release_logs_routes.router)

_WEB_DIR = os.path.join(os.path.dirname(__file__), "..", "web")
if os.path.isdir(_WEB_DIR):
    app.mount("/ui/static", StaticFiles(directory=_WEB_DIR), name="ui-static")

scheduler = AsyncIOScheduler()
app.state.scheduler = scheduler


def _seed_default_metadata_sources(db: Session) -> None:
    from app.services.metadata import seed_default_metadata_sources
    seed_default_metadata_sources(db)



@app.on_event("startup")
async def on_startup():
    # Устанавливаем umask (по умолчанию 0000), чтобы все создаваемые директории (0777) и файлы (0666)
    # были сразу доступны для чтения и записи Jellyfin, Plex, Samba, Transmission и qBittorrent.
    try:
        env_umask = os.getenv("UMASK", "0000").strip()
        os.umask(int(env_umask, 8))
    except Exception:
        try:
            os.umask(0o000)
        except Exception:
            pass

    init_db()
    install_db_log_handler()
    db = SessionLocal()
    try:
        settings = get_or_create_settings(db)
        ensure_master_admin(db)

        # 1. Проверка сброса пароля через переменную ALIASARR_ADMIN_PASSWORD
        env_admin_pass = os.getenv("ALIASARR_ADMIN_PASSWORD")
        if env_admin_pass:
            p_hash = hash_password(env_admin_pass.strip())
            owner = db.query(User).filter(User.is_owner == True).first()  # noqa: E712
            if owner:
                owner.password_hash = p_hash
                settings.password_hash = p_hash
                settings.login_enabled = True
                db.commit()
                logger.info("Пароль администратора успешно обновлён из переменной окружения ALIASARR_ADMIN_PASSWORD")

        # 2. Проверка сброса пароля через файл-триггер /config/reset_admin_password.txt
        reset_file = "/config/reset_admin_password.txt"
        if os.path.isfile(reset_file):
            try:
                with open(reset_file, "r", encoding="utf-8") as f:
                    new_pass = f.read().strip()
                if new_pass:
                    p_hash = hash_password(new_pass)
                    owner = db.query(User).filter(User.is_owner == True).first()  # noqa: E712
                    if owner:
                        owner.password_hash = p_hash
                        settings.password_hash = p_hash
                        settings.login_enabled = True
                        db.commit()
                        logger.info("Пароль администратора успешно сброшен из файла %s", reset_file)
                os.remove(reset_file)
            except Exception as exc:
                logger.warning("Не удалось сбросить пароль из %s: %s", reset_file, exc)

        # 3. SSL / HTTPS инициализация и автопродление сертификата
        try:
            from app.services.ssl_service import ensure_ssl_certificate
            if getattr(settings, "ssl_enabled", False) or getattr(settings, "ssl_auto_renew", True):
                ensure_ssl_certificate(settings.ssl_cert_path, settings.ssl_key_path)
        except Exception as exc:
            logger.warning("Ошибка инициализации SSL сертификата: %s", exc)

        source = "переменной окружения ALIASARR_API_KEY" if os.getenv("ALIASARR_API_KEY") else "автогенерации"
        logger.info("Системный API-ключ инициализирован (источник: %s)", source)
        write_api_key_file(settings.api_key)
        
        from app.services.log_service import sanitize_legacy_log_entries
        sanitize_legacy_log_entries(db)

        _seed_default_metadata_sources(db)
        seed_default_custom_formats(db)
        monitor_interval = settings.monitor_interval_minutes or 15
        tracker_interval = getattr(settings, "tracker_check_interval_minutes", 30) or 30
        unaired_interval = getattr(settings, "unaired_check_interval_minutes", 10) or 10
        download_check_sec = getattr(settings, "download_check_interval_seconds", 30) or (settings.download_check_interval_minutes * 60 if getattr(settings, "download_check_interval_minutes", None) else 30)
        indexer_check_interval = settings.indexer_check_interval_minutes or 30
        calendar_poll_interval = settings.calendar_poll_interval_minutes or 180
        metadata_refresh_hours = getattr(settings, "metadata_refresh_interval_hours", 12) or 12
    finally:
        db.close()

    _tracker_lock = asyncio.Lock()
    _wanted_lock = asyncio.Lock()
    _downloads_lock = asyncio.Lock()
    _indexer_lock = asyncio.Lock()
    _metadata_refresh_lock = asyncio.Lock()
    _calendar_lock = asyncio.Lock()
    _backup_lock = asyncio.Lock()

    async def _tracker_job():
        if _tracker_lock.locked():
            return
        async with _tracker_lock:
            db = SessionLocal()
            try:
                results = await recheck_all_active(db)
                if results:
                    updated = sum(1 for r in results if r.get("updated"))
                    if updated > 0:
                        logger.info("Проверка отслеживаемых раздач: обнаружено %d обновлений", updated)
                    else:
                        logger.debug("Проверка отслеживаемых раздач: проверено %d, обновлений нет", len(results))
            finally:
                db.close()

    async def _wanted_search_job():
        if _wanted_lock.locked():
            return
        async with _wanted_lock:
            db = SessionLocal()
            try:
                results = await run_wanted_search(db)
                if results:
                    logger.info("Авто-поиск wanted-серий: захвачено для %d видео", len(results))
            finally:
                db.close()

    async def _activate_unaired_job():
        """Переводит UNAIRED -> WANTED, как только наступает дата выхода серии или фильма."""
        from app.models.db import Episode, EpisodeStatus, Show
        db = SessionLocal()
        try:
            now = dt.datetime.utcnow()
            episodes = (
                db.query(Episode)
                .join(Show, Show.id == Episode.show_id)
                .filter(Episode.status == EpisodeStatus.UNAIRED, Episode.air_date <= now, Show.monitored == True)  # noqa: E712
                .all()
            )
            for ep in episodes:
                ep.status = EpisodeStatus.WANTED
                db.add(ep)
            if episodes:
                db.commit()
                logger.info("Переведено в 'разыскивается' серий/фильмов: %d", len(episodes))
        finally:
            db.close()

    async def _downloads_check_job():
        if _downloads_lock.locked():
            logger.debug("Проверка загрузок уже выполняется, пропускаем цикл.")
            return
        async with _downloads_lock:
            db = SessionLocal()
            try:
                results = await check_downloads(db)
                if results:
                    logger.info("Проверка загрузок: обработано завершённых торрентов — %d", len(results))
            finally:
                db.close()

    async def _indexer_availability_job():
        """Периодическая проверка доступности torznab-эндпоинтов активных индексаторов."""
        from app.api.indexers import _probe_indexer_once

        if _indexer_lock.locked():
            return
        async with _indexer_lock:
            db = SessionLocal()
            try:
                settings = get_or_create_settings(db)
                if not settings.indexer_check_enabled:
                    return
                attempts = max(1, settings.indexer_check_retries or 3)
                delay = max(0, settings.indexer_check_retry_delay_seconds or 5)
                indexers_list = db.query(Indexer).filter(Indexer.enabled == True).all()  # noqa: E712
                indexers_data = [
                    (idx.id, idx.name, idx.type, idx.base_url, idx.api_key, idx.categories, idx.last_check_ok, idx.consecutive_failures)
                    for idx in indexers_list
                ]
            finally:
                db.close()

        for idx_id, idx_name, idx_type, idx_base_url, idx_key, idx_cats, was_ok, cons_failures in indexers_data:
            temp_idx = Indexer(id=idx_id, name=idx_name, type=idx_type, base_url=idx_base_url, api_key=idx_key, categories=idx_cats)
            ok = False
            for attempt in range(1, attempts + 1):
                ok = await _probe_indexer_once(temp_idx)
                if ok:
                    break
                if attempt < attempts and delay > 0:
                    await asyncio.sleep(delay)

            db_update = SessionLocal()
            try:
                idx_row = db_update.get(Indexer, idx_id)
                if idx_row:
                    idx_row.last_check_at = dt.datetime.utcnow()
                    idx_row.last_check_ok = ok
                    idx_row.consecutive_failures = 0 if ok else (cons_failures + 1)
                    db_update.commit()
            except Exception:
                db_update.rollback()
            finally:
                db_update.close()

            if not ok and was_ok is not False:
                logger.warning("Индексатор «%s» недоступен после %d попыток (автопроверка)", idx_name, attempts)
            elif ok and was_ok is False:
                logger.info("Индексатор «%s» снова доступен", idx_name)

    async def _purge_logs_job():
        db = SessionLocal()
        try:
            settings = get_or_create_settings(db)
            deleted = purge_old_logs(db, settings.log_retention_days or 14)
            if deleted:
                logger.info("Журнал: удалено устаревших записей (старше %d дн.): %d",
                            settings.log_retention_days or 14, deleted)
        finally:
            db.close()

    async def _calendar_poll_job():
        """Периодический опрос источников метаданных для обновления дат выхода невышедших релизов."""
        if _calendar_lock.locked():
            return
        async with _calendar_lock:
            from app.models.db import Episode, EpisodeStatus, Show
            from app.services.metadata import refresh_show_release_dates

            db = SessionLocal()
            try:
                settings = get_or_create_settings(db)
                if not settings.calendar_poll_enabled:
                    return
                candidates = db.query(Show).filter(Show.metadata_id.isnot(None)).all()
                shows_to_check = []
                for show in candidates:
                    if show.content_type == "movie":
                        ep = db.query(Episode).filter(Episode.show_id == show.id).first()
                        if ep and ep.status == EpisodeStatus.DOWNLOADED:
                            continue
                    else:
                        still_unaired = (
                            db.query(Episode)
                            .filter(Episode.show_id == show.id, Episode.status.in_(
                                [EpisodeStatus.UNAIRED, EpisodeStatus.MISSING, EpisodeStatus.WANTED]))
                            .filter(Episode.air_date.is_(None))
                            .first()
                        )
                        if not still_unaired:
                            continue
                    shows_to_check.append(show.id)
            finally:
                db.close()

            if not shows_to_check:
                return

            updated_count = 0
            # Опрашиваем по очереди с обновлением в изолированной сессии
            for s_id in shows_to_check:
                s_db = SessionLocal()
                try:
                    s_settings = get_or_create_settings(s_db)
                    s_show = s_db.get(Show, s_id)
                    if not s_show:
                        continue
                    if s_show.content_type == "movie":
                        src_movie = getattr(s_settings, "calendar_metadata_source_movie", "radarr") or "radarr"
                        override = "radarr" if src_movie in ("auto", None) else src_movie
                    else:
                        src_series = getattr(s_settings, "calendar_metadata_source_series", "skyhook") or "skyhook"
                        override = "skyhook" if src_series in ("auto", None) else src_series
                    if await refresh_show_release_dates(s_db, s_show, override_source_type=override):
                        updated_count += 1
                except Exception as e:
                    logger.debug("Не удалось обновить дату выхода для видео %s: %s", s_id, e)
                finally:
                    s_db.close()

            if updated_count:
                logger.info("Опрос дат выхода: обновлено видео — %d", updated_count)

    async def _ssl_renew_job():
        db = SessionLocal()
        try:
            settings = get_or_create_settings(db)
            if getattr(settings, "ssl_auto_renew", True):
                from app.services.ssl_service import ensure_ssl_certificate
                ensure_ssl_certificate(settings.ssl_cert_path, settings.ssl_key_path)
        except Exception as exc:
            logger.warning("Ошибка авто-продления SSL сертификата: %s", exc)
        finally:
            db.close()

    def _sync_create_backup(b_type: str) -> None:
        b_db = SessionLocal()
        try:
            from app.services.backup_service import create_backup
            create_backup(b_db, backup_type=b_type)
        finally:
            b_db.close()

    async def _auto_backup_job():
        if _backup_lock.locked():
            return
        async with _backup_lock:
            db = SessionLocal()
            try:
                settings = get_or_create_settings(db)
                interval_days = getattr(settings, "backup_interval_days", 7) or 7
                if interval_days > 0:
                    b_type = getattr(settings, "backup_default_type", "full") or "full"
                    await asyncio.to_thread(_sync_create_backup, b_type)
            except Exception as exc:
                logger.warning("Ошибка автоматического создания бэкапа: %s", exc)
            finally:
                db.close()

    async def _refresh_metadata_job():
        """Автоматическое регулярное обновление метаданных библиотеки (Sonarr/Radarr Refresh Series/Movies)."""
        if _metadata_refresh_lock.locked():
            return
        async with _metadata_refresh_lock:
            db = SessionLocal()
            try:
                settings = get_or_create_settings(db)
                if not getattr(settings, "metadata_auto_refresh_enabled", True):
                    return
                from app.services.metadata import refresh_all_shows_metadata
                await refresh_all_shows_metadata(db, username="scheduler")
            except Exception as exc:
                logger.warning("Ошибка автоматического обновления метаданных библиотеки: %s", exc)
            finally:
                db.close()

    scheduler.add_job(_tracker_job, "interval", minutes=tracker_interval, id="recheck_tracked_releases")
    # Периодический поиск разыскиваемого контента
    scheduler.add_job(_wanted_search_job, "interval", minutes=monitor_interval, id="wanted_search")
    scheduler.add_job(_downloads_check_job, "interval", seconds=download_check_sec, id="downloads_check")
    scheduler.add_job(_activate_unaired_job, "interval", minutes=unaired_interval, id="activate_unaired")
    scheduler.add_job(_indexer_availability_job, "interval", minutes=indexer_check_interval, id="indexer_availability")
    scheduler.add_job(_purge_logs_job, "interval", hours=24, id="purge_old_logs")
    scheduler.add_job(_calendar_poll_job, "interval", minutes=calendar_poll_interval, id="calendar_poll")
    scheduler.add_job(_ssl_renew_job, "interval", hours=24, id="ssl_renew_check")
    scheduler.add_job(_auto_backup_job, "interval", hours=24, id="auto_backup_check")
    scheduler.add_job(_refresh_metadata_job, "interval", hours=metadata_refresh_hours, id="refresh_metadata")
    scheduler.start()
    logger.info(
        "Планировщик запущен: поиск wanted каждые %d мин, загрузки каждые %d сек, "
        "слежение за раздачами каждые %d мин, активация премьер каждые %d мин, проверка индексаторов каждые %d мин",
        monitor_interval, download_check_sec, tracker_interval, unaired_interval, indexer_check_interval,
    )


@app.on_event("shutdown")
async def on_shutdown():
    scheduler.shutdown()


@app.get("/api/v1/health")
def health():
    return {"status": "ok", "service": "aliasarr"}


@app.get("/quality-guide")
def quality_guide():
    return RedirectResponse(url="/wiki#section-qualities", status_code=302)


@app.get("/wiki")
@app.get("/wiki.html")
def wiki_page(request: Request):
    db = SessionLocal()
    try:
        settings = get_or_create_settings(db)
        if settings.login_enabled:
            user = get_current_user_optional(request, db)
            if not user:
                # Если включён вход по логину/паролю и пользователь не авторизован — перенаправляем на авторизацию
                return RedirectResponse(url="/?redirect=/wiki", status_code=302)

        wiki_path = os.path.join(_WEB_DIR, "wiki.html")
        if not os.path.isfile(wiki_path):
            raise HTTPException(404, "Wiki page not found")
        with open(wiki_path, encoding="utf-8") as f:
            html = f.read()

        import json
        lang = getattr(settings, "language", "ru") or "ru"
        theme = getattr(settings, "theme", "dark") or "dark"
        inject_script = (
            f'<script>'
            f'window.__ALIASARR_SETTINGS_LANG__ = {json.dumps(lang)};'
            f'window.__ALIASARR_SETTINGS_THEME__ = {json.dumps(theme)};'
        )
        if not settings.login_enabled:
            inject_script += f'window.__ALIASARR_BOOTSTRAP_KEY__ = {json.dumps(settings.api_key)};'
        inject_script += '</script>'
        html = html.replace("</head>", inject_script + "</head>")

        return HTMLResponse(html)
    finally:
        db.close()


@app.get("/")
def root_redirect():
    index_path = os.path.join(_WEB_DIR, "index.html")
    if not os.path.isfile(index_path):
        return {"service": "aliasarr", "ui": "not built", "docs": "/docs"}

    db = SessionLocal()
    try:
        settings = get_or_create_settings(db)
        with open(index_path, encoding="utf-8") as f:
            html = f.read()

        if not settings.login_enabled:
            # Браузер, обращающийся к серверу напрямую (тот же origin), и так имеет
            # полный доступ к контейнеру — не заставляем вручную вводить ключ,
            # который сервер и так знает. Если включён логин, ключ НЕ встраиваем:
            # доступ к странице до входа не должен раскрывать секрет.
            import json
            bootstrap_script = (
                f'<script>window.__ALIASARR_BOOTSTRAP_KEY__ = {json.dumps(settings.api_key)};</script>'
            )
            html = html.replace("</head>", bootstrap_script + "</head>")

        return HTMLResponse(html)
    finally:
        db.close()


if __name__ == "__main__":
    from run import run
    run()
