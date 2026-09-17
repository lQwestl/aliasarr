from __future__ import annotations

import asyncio
import datetime as dt
import logging
import os
from typing import Any, Optional

try:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
except ImportError:
    class AsyncIOScheduler:  # type: ignore
        def __init__(self, *args, **kwargs): pass
        def start(self): pass
        def shutdown(self): pass
        def add_job(self, *args, **kwargs): pass

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.api import (
    audit_routes,
    auth_routes,
    blocklist_routes,
    collections_routes,
    custom_formats_routes,
    dataset_routes,
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

try:
    os.umask(int(os.getenv("UMASK", "0022").strip(), 8))
except Exception:
    os.umask(0o022)

_active_server = None
_restart_requested = False

from app.services.openapi_service import get_localized_openapi

app = FastAPI(
    title="Aliasarr API",
    description="Backend API для Aliasarr — системы управления медиатекой с мультиязычными алиасами, парсером сезонов и контролем торрент-клиентов.",
    version="3.4.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    openapi_tags=None,
)


def custom_openapi():
    return get_localized_openapi(app, lang="ru")


app.openapi = custom_openapi


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Перехват HTTPException с обогащением диагностическими данными для 500+ ошибок."""
    if exc.status_code >= 500:
        logger.error(
            "HTTP %s ошибка при %s %s: %s",
            exc.status_code,
            request.method,
            request.url.path,
            exc.detail,
            exc_info=True,
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "detail": str(exc.detail),
                "error": str(exc.detail),
                "error_type": "HTTPException",
                "method": request.method,
                "path": request.url.path,
                "status_code": exc.status_code,
                "timestamp": dt.datetime.utcnow().isoformat() + "Z",
            },
            headers=getattr(exc, "headers", None),
        )
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
        headers=getattr(exc, "headers", None),
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Глобальный перехват всех необработанных исключений сервера (500 Internal Server Error)."""
    exc_name = exc.__class__.__name__
    exc_msg = str(exc) or "Внутренняя ошибка сервера"
    logger.error(
        "Необработанная ошибка сервера (500) при %s %s [%s]: %s",
        request.method,
        request.url.path,
        exc_name,
        exc_msg,
        exc_info=True,
    )
    return JSONResponse(
        status_code=500,
        content={
            "detail": f"Внутренняя ошибка сервера ({exc_name}): {exc_msg}",
            "error": exc_msg,
            "error_type": exc_name,
            "method": request.method,
            "path": request.url.path,
            "status_code": 500,
            "timestamp": dt.datetime.utcnow().isoformat() + "Z",
        },
    )


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
app.include_router(dataset_routes.router)
app.include_router(blocklist_routes.router)
app.include_router(collections_routes.router)

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
    # Безопасный umask по умолчанию запрещает запись для group/other. Права на медиафайлы,
    # которым нужен общий доступ, устанавливаются явно через apply_media_permissions.
    try:
        env_umask = os.getenv("UMASK", "0022").strip()
        os.umask(int(env_umask, 8))
    except Exception:
        try:
            os.umask(0o022)
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

        # 4. Разовая миграция: снятие мониторинга со скачанных серий без активного апгрейда
        if not getattr(settings, "unmonitor_downloaded_migrated", False):
            try:
                from app.models.db import Episode, EpisodeStatus
                updated_count = db.query(Episode).filter(
                    Episode.status == EpisodeStatus.DOWNLOADED,
                    Episode.upgrade_requested == False,
                ).update({Episode.monitored: False}, synchronize_session=False)
                settings.unmonitor_downloaded_migrated = True
                db.commit()
                if updated_count > 0:
                    logger.info("Миграция: успешно снят мониторинг с %d скачанных серий", updated_count)
            except Exception as e_mig:
                logger.warning("Ошибка при выполнении миграции unmonitor_downloaded: %s", e_mig)
                db.rollback()

        # 5. Автоматическое включение мониторинга для невышедших серий
        try:
            from app.models.db import Episode, EpisodeStatus, Show
            now_dt = dt.datetime.utcnow()
            monitored_shows = db.query(Show).filter(Show.monitored == True).all()
            monitored_show_ids = [s.id for s in monitored_shows if getattr(s, "id", None) is not None]
            unaired_updated = 0
            if monitored_show_ids:
                unaired_updated = (
                    db.query(Episode)
                    .filter(
                        Episode.show_id.in_(monitored_show_ids),
                        Episode.monitored == False,
                        Episode.file_path.is_(None),
                        Episode.status != EpisodeStatus.DOWNLOADED,
                        Episode.status != EpisodeStatus.IGNORED,
                        (Episode.status == EpisodeStatus.UNAIRED) | (Episode.air_date > now_dt),
                    )
                    .update({Episode.monitored: True, Episode.status: EpisodeStatus.UNAIRED}, synchronize_session=False)
                )
            if unaired_updated > 0:
                db.commit()
                logger.info("Синхронизация: включен мониторинг для %d невышедших серий", unaired_updated)
        except Exception as e_un:
            logger.warning("Ошибка при синхронизации мониторинга невышедших серий: %s", e_un)
            db.rollback()

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
        from app.database import optimize_and_checkpoint_db
        db = SessionLocal()
        try:
            settings = get_or_create_settings(db)
            deleted = purge_old_logs(db, settings.log_retention_days or 14)
            if deleted:
                logger.info("Журнал: удалено устаревших записей (старше %d дн.): %d",
                            settings.log_retention_days or 14, deleted)
        finally:
            db.close()
        try:
            await asyncio.to_thread(optimize_and_checkpoint_db)
        except Exception:
            pass

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
                if interval_days <= 0:
                    return

                from app.services.backup_service import list_backups
                backups = await asyncio.to_thread(list_backups)
                if backups:
                    latest = backups[0]
                    created_at_str = latest.get("created_at")
                    if created_at_str:
                        try:
                            created_dt = dt.datetime.fromisoformat(created_at_str)
                            elapsed_seconds = (dt.datetime.utcnow() - created_dt).total_seconds()
                            required_seconds = (interval_days * 86400) - 3600  # 1 hour margin
                            if elapsed_seconds < required_seconds:
                                logger.debug(
                                    "Пропуск автобэкапа: последний бэкап был %s, интервал %d дн.",
                                    created_at_str,
                                    interval_days,
                                )
                                return
                        except Exception as parse_err:
                            logger.debug("Не удалось распарсить дату последнего бэкапа: %s", parse_err)

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
            enabled = True
            try:
                settings = get_or_create_settings(db)
                enabled = getattr(settings, "metadata_auto_refresh_enabled", True)
            except Exception as exc:
                logger.warning("Ошибка проверки настроек обновления метаданных: %s", exc)
            finally:
                db.close()

            if not enabled:
                return

            try:
                from app.services.metadata import refresh_all_shows_metadata, refresh_all_collections_metadata
                await refresh_all_shows_metadata(None, username="scheduler")
                await refresh_all_collections_metadata(None)
            except Exception as exc:
                logger.warning("Ошибка автоматического обновления метаданных библиотеки: %s", exc)

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
    # Автоматическое обновление метаданных по алгоритму Sonarr/Radarr (каждые 6 часов)
    scheduler.add_job(_refresh_metadata_job, "interval", hours=6, id="refresh_metadata")
    scheduler.start()

    # Запускаем первичное фоновое обновление метаданных с задержкой (60 сек),
    # чтобы веб-интерфейс и страницы стартовали мгновенно без блокировок
    async def _delayed_initial_refresh():
        try:
            await asyncio.sleep(60)
            await _refresh_metadata_job()
        except Exception:
            pass

    asyncio.create_task(_delayed_initial_refresh())

    # Фоновая миграция существующих постеров в локальное хранилище /config/MediaCover
    async def _delayed_cover_backfill():
        try:
            await asyncio.sleep(10)
            from app.services.cover_service import backfill_existing_covers
            b_db = SessionLocal()
            try:
                res = await backfill_existing_covers(b_db)
                if res.get("migrated"):
                    logger.info("Миграция локальных обложек: сохранено локально %d обложек", res["migrated"])
            finally:
                b_db.close()
        except Exception as e:
            logger.debug("Ошибка фоновой миграции обложек: %s", e)

    asyncio.create_task(_delayed_cover_backfill())
    logger.info(
        "Планировщик запущен: поиск wanted каждые %d мин, загрузки каждые %d сек, "
        "слежение за раздачами каждые %d мин, активация премьер каждые %d мин, проверка индексаторов каждые %d мин, "
        "автоматическое обновление метаданных каждые 6 ч",
        monitor_interval, download_check_sec, tracker_interval, unaired_interval, indexer_check_interval,
    )


@app.on_event("shutdown")
async def on_shutdown():
    scheduler.shutdown()
    try:
        from app.services.log_service import stop_db_log_worker
        stop_db_log_worker()
    except Exception:
        pass


@app.get("/api/v1/health")
def health():
    return {"status": "ok", "service": "aliasarr"}


@app.get("/quality-guide")
def quality_guide():
    return RedirectResponse(url="/wiki#section-qualities", status_code=302)


@app.get("/wiki")
@app.get("/wiki.html")
@app.get("/docs")
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


@app.get("/api/docs")
@app.get("/api/docs.html")
def api_docs_page(request: Request):
    db = SessionLocal()
    try:
        settings = get_or_create_settings(db)
        user = None
        if settings.login_enabled:
            user = get_current_user_optional(request, db)
            if not user:
                return RedirectResponse(url="/?redirect=/api/docs", status_code=302)

        docs_path = os.path.join(_WEB_DIR, "api-docs.html")
        if not os.path.isfile(docs_path):
            raise HTTPException(404, "API Documentation page not found")
        with open(docs_path, encoding="utf-8") as f:
            html = f.read()

        import json
        lang = getattr(settings, "language", "ru") or "ru"
        theme = getattr(settings, "theme", "dark") or "dark"
        inject_script = (
            f'<script>'
            f'window.__ALIASARR_SETTINGS_LANG__ = {json.dumps(lang)};'
            f'window.__ALIASARR_SETTINGS_THEME__ = {json.dumps(theme)};'
        )
        if not settings.login_enabled and getattr(settings, "api_key", None):
            inject_script += f'window.__ALIASARR_BOOTSTRAP_KEY__ = {json.dumps(settings.api_key)};'
        elif user and getattr(user, "api_key", None):
            inject_script += f'window.__ALIASARR_BOOTSTRAP_KEY__ = {json.dumps(user.api_key)};'
        inject_script += '</script>'
        html = html.replace("</head>", inject_script + "</head>")

        return HTMLResponse(html)
    finally:
        db.close()


@app.get("/openapi.json", include_in_schema=False)
def openapi_json_endpoint(request: Request, lang: Optional[str] = None):
    target_lang = lang
    if not target_lang:
        target_lang = request.cookies.get("aliasarr_lang")
    if not target_lang:
        db = SessionLocal()
        try:
            settings = get_or_create_settings(db)
            target_lang = getattr(settings, "language", "ru") or "ru"
        except Exception:
            target_lang = "ru"
        finally:
            db.close()
    return JSONResponse(get_localized_openapi(app, lang=target_lang))


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
