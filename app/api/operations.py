from __future__ import annotations

import datetime as dt
import os
import shutil
from typing import Optional, List, Dict, Any, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.db import (
    DownloadClient,
    DownloadHistory,
    Episode,
    EpisodeStatus,
    Indexer,
    MetadataSource,
    NotificationConfig,
    QualityProfile,
    Show,
    TrackedRelease,
    User,
)
from app.services.auto_search import run_wanted_search
from app.services.download_client import get_client
from app.services.notifications import REQUIRED_NOTIFICATION_FIELDS, notify_all, send_notification
from app.services.user_service import require_permission, require_any_permission, get_current_user

router = APIRouter(prefix="/api/v1", tags=["operations"])


# ---------------------------------------------------------------------------
# Dashboard stats
# ---------------------------------------------------------------------------

@router.get("/stats")
def get_stats(db: Session = Depends(get_db), current_user: User = Depends(require_permission("view_dashboard"))):
    total_shows = db.query(Show).count()
    movies_count = db.query(Show).filter(Show.content_type == "movie").count()
    anime_count = db.query(Show).filter(Show.content_type == "anime").count()
    series_count = db.query(Show).filter(Show.content_type == "series").count()

    monitored_count = db.query(Show).filter(Show.monitored == True).count()  # noqa: E712
    unmonitored_count = db.query(Show).filter(Show.monitored == False).count()  # noqa: E712

    status_counts = dict(
        db.query(Episode.status, func.count(Episode.id)).group_by(Episode.status).all()
    )

    total_episodes = db.query(Episode).count()

    episodes_with_files = (
        db.query(Episode.file_path)
        .filter(Episode.file_path.isnot(None))
        .all()
    )

    total_files = 0
    total_size_bytes = 0
    seen_paths = set()
    for (fpath,) in episodes_with_files:
        if fpath and fpath not in seen_paths:
            seen_paths.add(fpath)
            if os.path.exists(fpath):
                total_files += 1
                try:
                    total_size_bytes += os.path.getsize(fpath)
                except OSError:
                    pass
            else:
                total_files += 1

    downloaded_eps = status_counts.get(EpisodeStatus.DOWNLOADED, 0)
    if total_files < downloaded_eps:
        total_files = downloaded_eps

    now = dt.datetime.utcnow()
    continuing_shows = 0
    ended_shows = 0
    shows = db.query(Show).all()
    for s in shows:
        ep_count = db.query(Episode).filter(Episode.show_id == s.id).count()
        dl_count = db.query(Episode).filter(Episode.show_id == s.id, Episode.status == EpisodeStatus.DOWNLOADED).count()
        if s.content_type == "movie":
            if dl_count > 0:
                ended_shows += 1
            else:
                continuing_shows += 1
        else:
            has_future_eps = db.query(Episode).filter(Episode.show_id == s.id, Episode.air_date.isnot(None), Episode.air_date >= now).first() is not None
            if has_future_eps:
                continuing_shows += 1
            elif ep_count > 0 and dl_count >= ep_count:
                ended_shows += 1
            else:
                continuing_shows += 1

    return {
        "total_shows": total_shows,
        "series": series_count,
        "movies": movies_count,
        "anime": anime_count,
        "monitored": monitored_count,
        "unmonitored": unmonitored_count,
        "ended": ended_shows,
        "continuing": continuing_shows,
        "total_episodes": total_episodes,
        "total_files": total_files,
        "total_size_bytes": total_size_bytes,
        "wanted": status_counts.get(EpisodeStatus.WANTED, 0),
        "downloading": status_counts.get(EpisodeStatus.DOWNLOADING, 0),
        "downloaded": status_counts.get(EpisodeStatus.DOWNLOADED, 0),
        "missing": status_counts.get(EpisodeStatus.MISSING, 0),
        "unaired": status_counts.get(EpisodeStatus.UNAIRED, 0),
        "indexers_count": db.query(Indexer).filter(Indexer.enabled == True).count(),  # noqa: E712
        "download_clients_count": db.query(DownloadClient).filter(DownloadClient.enabled == True).count(),  # noqa: E712
    }


@router.get("/health-check", summary="Расширенный статус здоровья и метрики системы")
def get_health_check(db: Session = Depends(get_db)):
    """Расширенные проверки здоровья и метрики системы для дашборда."""
    checks = []

    # 1. Дисковое пространство (/data, /downloads, /config)
    paths_to_check = [
        ("/data", "Медиатека (/data)"),
        ("/downloads", "Загрузки (/downloads)"),
        ("/config", "Конфигурация (/config)"),
    ]
    seen_mounts = set()
    for p_path, p_label in paths_to_check:
        target_dir = p_path if os.path.exists(p_path) else os.getcwd()
        try:
            usage = shutil.disk_usage(target_dir)
            mount_id = (usage.total, usage.free)
            if mount_id in seen_mounts and p_path != "/data":
                continue
            seen_mounts.add(mount_id)

            total_gb = usage.total / (1024 ** 3)
            free_gb = usage.free / (1024 ** 3)
            used_pct = round(((usage.total - usage.free) / usage.total) * 100, 1) if usage.total > 0 else 0
            free_pct = (usage.free / usage.total) * 100 if usage.total > 0 else 0

            lvl = "ok"
            if free_pct < 5.0 or free_gb < 2.0:
                lvl = "error"
            elif free_pct < 15.0 or free_gb < 10.0:
                lvl = "warn"

            def _fmt_sz(gb: float) -> str:
                if gb >= 1024:
                    return f"{gb / 1024:.2f} TB"
                return f"{gb:.1f} GB"

            checks.append({
                "key": f"disk_{p_path}",
                "level": lvl,
                "title": f"Диск: {p_label}",
                "message": f"Свободно {_fmt_sz(free_gb)} из {_fmt_sz(total_gb)} ({used_pct}% занято)",
                "used_pct": used_pct,
            })
        except Exception:
            pass

    # 2. Индексаторы
    idx_total = db.query(Indexer).count()
    indexers_enabled = db.query(Indexer).filter(Indexer.enabled == True).count()  # noqa: E712
    checks.append({
        "key": "indexers",
        "level": "ok" if indexers_enabled else "warn",
        "title": "Индексаторы",
        "message": f"Включено {indexers_enabled} из {idx_total} трекеров" if indexers_enabled
        else "Нет ни одного включённого индексатора — поиск релизов не работает",
    })

    # 3. Загрузчики (Download Clients)
    dc_total = db.query(DownloadClient).count()
    dc_enabled = db.query(DownloadClient).filter(DownloadClient.enabled == True).count()  # noqa: E712
    checks.append({
        "key": "download_clients",
        "level": "ok" if dc_enabled else "warn",
        "title": "Загрузчики",
        "message": f"Включено {dc_enabled} из {dc_total} клиентов загрузки" if dc_enabled
        else "Нет активных download-клиентов — захваченные релизы не будут скачиваться",
    })

    # 4. Источники метаданных
    md_total = db.query(MetadataSource).count()
    md_enabled = db.query(MetadataSource).filter(MetadataSource.enabled == True).count()  # noqa: E712
    checks.append({
        "key": "metadata",
        "level": "ok" if md_enabled else "warn",
        "title": "Метаданные",
        "message": f"Активно {md_enabled} источников (SkyHook, TheTVDB, TVMaze, TMDB)" if md_enabled
        else "Нет активных источников метаданных",
    })

    # 5. Планировщик фоновых задач
    checks.append({
        "key": "scheduler",
        "level": "ok",
        "title": "Фоновый мониторинг",
        "message": "Служба автоматической проверки загрузок и трекеров работает",
    })

    # 6. Профили качества
    shows_without_profile = db.query(Show).filter(Show.quality_profile_id.is_(None)).count()
    if shows_without_profile:
        checks.append({
            "key": "profiles",
            "level": "warn",
            "title": "Профили качества",
            "message": f"Видео без профиля качества: {shows_without_profile} (разрешено любое качество)",
        })
    else:
        checks.append({
            "key": "profiles",
            "level": "ok",
            "title": "Профили качества",
            "message": "Все тайтлы библиотеки привязаны к профилям качества",
        })

    has_error = any(c.get("level") == "error" for c in checks)
    has_warn = any(c.get("level") == "warn" for c in checks)
    overall_status = "error" if has_error else ("warn" if has_warn else "ok")

    return {"status": overall_status, "checks": checks}


# ---------------------------------------------------------------------------
# Quality profiles
# ---------------------------------------------------------------------------

class QualityProfileIn(BaseModel):
    name: str
    allowed_qualities: list[str] = []
    min_size_mb: Optional[int] = None
    max_size_mb: Optional[int] = None
    upgrade_allowed: bool = True


class QualityProfileOut(QualityProfileIn):
    id: int

    class Config:
        from_attributes = True


@router.get("/quality-profiles", response_model=list[QualityProfileOut])
def list_quality_profiles(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return db.query(QualityProfile).all()


@router.post("/quality-profiles", response_model=QualityProfileOut, status_code=201)
def create_quality_profile(
    payload: QualityProfileIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_settings")),
):
    profile = QualityProfile(**payload.model_dump())
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return profile


@router.delete("/quality-profiles/{profile_id}", status_code=204)
def delete_quality_profile(
    profile_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_settings")),
):
    profile = db.get(QualityProfile, profile_id)
    if not profile:
        raise HTTPException(404, "Profile not found")
    db.delete(profile)
    db.commit()


@router.put("/quality-profiles/{profile_id}", response_model=QualityProfileOut)
def update_quality_profile(
    profile_id: int,
    payload: QualityProfileIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_settings")),
):
    profile = db.get(QualityProfile, profile_id)
    if not profile:
        raise HTTPException(404, "Profile not found")
    for field, value in payload.model_dump().items():
        setattr(profile, field, value)
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return profile


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------

class NotificationIn(BaseModel):
    name: str
    type: str
    settings: dict = {}
    enabled: bool = True
    on_grab: bool = True
    on_import: bool = True
    on_upgrade: bool = True
    on_rename: bool = False
    on_series_add: bool = False
    on_series_delete: bool = False
    on_episode_file_delete: bool = False
    on_episode_file_delete_for_upgrade: bool = False
    on_health_issue: bool = True
    on_health_restored: bool = False
    on_application_update: bool = False
    on_manual_interaction_required: bool = True
    on_backup: bool = False


class NotificationOut(NotificationIn):
    id: int

    class Config:
        from_attributes = True


@router.get("/notifications", response_model=list[NotificationOut])
def list_notifications(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return db.query(NotificationConfig).all()


@router.post("/notifications", response_model=NotificationOut, status_code=201)
def create_notification(
    payload: NotificationIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_settings")),
):
    config = NotificationConfig(**payload.model_dump())
    db.add(config)
    db.commit()
    db.refresh(config)
    return config


@router.delete("/notifications/{config_id}", status_code=204)
def delete_notification(
    config_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_settings")),
):
    config = db.get(NotificationConfig, config_id)
    if not config:
        raise HTTPException(404, "Notification config not found")
    db.delete(config)
    db.commit()


@router.put("/notifications/{config_id}", response_model=NotificationOut)
def update_notification(
    config_id: int,
    payload: NotificationIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_settings")),
):
    config = db.get(NotificationConfig, config_id)
    if not config:
        raise HTTPException(404, "Notification config not found")
    for field, value in payload.model_dump().items():
        setattr(config, field, value)
    db.add(config)
    db.commit()
    db.refresh(config)
    return config


@router.post("/notifications/{config_id}/test")
async def test_notification(
    config_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_settings")),
):
    config = db.get(NotificationConfig, config_id)
    if not config:
        raise HTTPException(404, "Notification config not found")

    missing = [f for f in REQUIRED_NOTIFICATION_FIELDS.get(config.type, []) if not config.settings.get(f)]
    if missing:
        return {"success": False, "message": f"В настройках не заполнено: {', '.join(missing)}"}

    try:
        await send_notification(config, "🔔 Тестовое уведомление от Aliasarr — всё работает!", "test", db=db)
        return {"success": True, "message": "Тестовое уведомление отправлено"}
    except Exception as exc:
        return {"success": False, "message": f"Ошибка отправки: {exc}"}


class AdHocNotificationTestIn(BaseModel):
    """Тестовая отправка несохранённой конфигурации уведомления."""
    type: str
    settings: dict = {}


@router.post("/notifications/test")
async def test_notification_adhoc(
    payload: AdHocNotificationTestIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_settings")),
):
    if payload.type not in REQUIRED_NOTIFICATION_FIELDS:
        return {"success": False, "message": "Неизвестный тип уведомления"}
    missing = [f for f in REQUIRED_NOTIFICATION_FIELDS[payload.type] if not payload.settings.get(f)]
    if missing:
        return {"success": False, "message": f"В настройках не заполнено: {', '.join(missing)}"}

    class _AdHocConfig:
        type = payload.type
        settings = payload.settings
        name = "тест"

    try:
        await send_notification(_AdHocConfig(), "🔔 Тестовое уведомление от Aliasarr — всё работает!", "test", db=db)
        return {"success": True, "message": "Тестовое уведомление отправлено"}
    except Exception as exc:
        return {"success": False, "message": f"Ошибка отправки: {exc}"}


# ---------------------------------------------------------------------------
# Календарь релизов и расписание
# ---------------------------------------------------------------------------

# Статусы событий календаря для фильтрации и цветовой индикации
CALENDAR_STATUSES = [
    "unaired", "unmonitored", "on_air", "missing", "downloading", "downloaded", "premiere",
]


def _calendar_status(show: Show, episode: Optional[Episode], air_date: Optional[dt.datetime], entry_type: str) -> str:
    """Определяет статус события календаря на основе состояния шоу и серии."""
    if entry_type == "premiere":
        return "premiere"
    if show and not show.monitored:
        return "unmonitored"
    if episode is not None:
        if episode.status == EpisodeStatus.DOWNLOADED:
            return "downloaded"
        if episode.status == EpisodeStatus.DOWNLOADING:
            return "downloading"
        if air_date and air_date.date() == dt.datetime.utcnow().date():
            return "on_air"
        if episode.status == EpisodeStatus.MISSING:
            return "missing"
        if episode.status == EpisodeStatus.UNAIRED:
            return "unaired"
    if air_date and air_date.date() == dt.datetime.utcnow().date():
        return "on_air"
    if air_date and air_date > dt.datetime.utcnow():
        return "unaired"
    return "missing"


class CalendarEntryOut(BaseModel):
    show_id: int
    episode_id: Optional[int] = None
    show_title: str
    poster_url: Optional[str] = None
    season: Optional[int] = None
    episode: Optional[int] = None
    absolute_episode: Optional[int] = None
    title: Optional[str] = None
    air_date: Optional[dt.datetime] = None
    status: str
    entry_type: str = "episode"  # "episode" | "premiere"
    content_type: str = "series"  # "series" | "movie" | "anime"
    monitored: bool = True
    overview: Optional[str] = None
    rating: Optional[float] = None
    year: Optional[int] = None
    release_types: list[str] = []  # ["cinemas", "digital", "physical"]


class CalendarWaitingOut(BaseModel):
    show_id: int
    show_title: str
    poster_url: Optional[str] = None
    content_type: str = "series"
    expected_year: Optional[int] = None
    expected_quarter: Optional[int] = None
    monitored: bool = True


class CalendarSearchMissingIn(BaseModel):
    days_forward: int = 60
    days_back: int = 14
    content_type: str = "all"  # "all" | "series" | "movie" | "anime"
    monitored_only: bool = True


@router.get("/calendar", response_model=list[CalendarEntryOut])
async def get_calendar(
    days_forward: int = 60,
    days_back: int = 14,
    monitored_only: bool = False,
    content_type: str = "all",
    status_filter: str = "all",
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("view_calendar")),
):
    from app.services.metadata import should_refresh_show, refresh_show_metadata

    start = dt.datetime.utcnow() - dt.timedelta(days=days_back)
    end = dt.datetime.utcnow() + dt.timedelta(days=days_forward)

    episodes_q = (
        db.query(Episode)
        .join(Show, Episode.show_id == Show.id)
        .filter(Episode.air_date.isnot(None), Episode.air_date >= start, Episode.air_date <= end)
        .filter(Show.in_calendar.is_(True))
    )
    if monitored_only:
        episodes_q = episodes_q.filter(Show.monitored.is_(True))
    if content_type and content_type != "all":
        episodes_q = episodes_q.filter(Show.content_type == content_type)

    episodes = episodes_q.order_by(Episode.air_date).all()

    # Автоматически обновляем метаданные тайтлов в календаре, если у них есть серии с TBA/заглушками или истекло время
    cal_show_ids = {ep.show_id for ep in episodes}
    for sid in cal_show_ids:
        s = db.get(Show, sid)
        if s and should_refresh_show(s, db):
            try:
                await refresh_show_metadata(db, s)
            except Exception as e:
                logger.debug("On-demand calendar refresh failed for show %s: %s", sid, e)

    episodes = episodes_q.order_by(Episode.air_date).all()

    out: list[CalendarEntryOut] = []
    shows_with_episode_entries: set[int] = set()
    for ep in episodes:
        show = db.get(Show, ep.show_id)
        if not show:
            continue
        shows_with_episode_entries.add(ep.show_id)
        st = _calendar_status(show, ep, ep.air_date, "episode")
        if status_filter != "all" and st != status_filter:
            continue

        rel_types = []
        if show.content_type == "movie":
            rel_types = ["cinemas"]

        out.append(CalendarEntryOut(
            show_id=ep.show_id, episode_id=ep.id, show_title=show.title, poster_url=show.poster_url,
            season=ep.season_number, episode=ep.episode_number, absolute_episode=ep.absolute_number, title=ep.title,
            air_date=ep.air_date, status=st,
            entry_type="episode", content_type=show.content_type, monitored=show.monitored,
            overview=show.overview, rating=show.rating, year=show.year,
            release_types=rel_types,
        ))

    # Премьеры фильмов/анонсированных шоу без серий:
    premiering_q = (
        db.query(Show)
        .filter(Show.premiere_date.isnot(None), Show.premiere_date >= start, Show.premiere_date <= end)
        .filter(Show.in_calendar.is_(True))
    )
    if monitored_only:
        premiering_q = premiering_q.filter(Show.monitored.is_(True))
    if content_type and content_type != "all":
        premiering_q = premiering_q.filter(Show.content_type == content_type)

    for show in premiering_q.all():
        if show.id in shows_with_episode_entries:
            continue  # уже показано через собственные серии
        st = _calendar_status(show, None, show.premiere_date, "premiere")
        if status_filter != "all" and st != status_filter:
            continue

        rel_types = ["cinemas"] if show.content_type == "movie" else []

        out.append(CalendarEntryOut(
            show_id=show.id, show_title=show.title, poster_url=show.poster_url,
            season=None, episode=None, absolute_episode=None, title=None,
            air_date=show.premiere_date,
            status=st,
            entry_type="premiere", content_type=show.content_type, monitored=show.monitored,
            overview=show.overview, rating=show.rating, year=show.year,
            release_types=rel_types,
        ))

    out.sort(key=lambda e: e.air_date or dt.datetime.min)
    return out


@router.post("/calendar/search-missing")
async def search_missing_calendar(
    payload: CalendarSearchMissingIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_permission("manage_calendar", "manage_library")),
):
    """
    Запускает автоматический поиск релизов для всех отсутствующих серий и фильмов,
    попадающих в выбранный интервал дат календаря (аналог SearchForMissing в Sonarr/Radarr).
    """
    from app.services.auto_search import search_and_grab_show

    start = dt.datetime.utcnow() - dt.timedelta(days=payload.days_back)
    end = dt.datetime.utcnow() + dt.timedelta(days=payload.days_forward)

    # 1. Серии со статусом WANTED или MISSING
    episodes_q = (
        db.query(Episode)
        .join(Show, Episode.show_id == Show.id)
        .filter(Episode.air_date.isnot(None), Episode.air_date >= start, Episode.air_date <= end)
        .filter(Show.in_calendar.is_(True))
        .filter(Episode.status.in_([EpisodeStatus.MISSING, EpisodeStatus.WANTED]))
    )
    if payload.monitored_only:
        episodes_q = episodes_q.filter(Show.monitored.is_(True))
    if payload.content_type != "all":
        episodes_q = episodes_q.filter(Show.content_type == payload.content_type)

    missing_episodes = episodes_q.all()
    show_episode_map: dict[int, set[int]] = {}
    for ep in missing_episodes:
        show_episode_map.setdefault(ep.show_id, set()).add(ep.id)

    # 2. Фильмы в статусе WANTED / MISSING
    if payload.content_type in ("all", "movie"):
        movies_q = (
            db.query(Show)
            .filter(Show.content_type == "movie")
            .filter(Show.in_calendar.is_(True))
            .filter(Show.premiere_date.isnot(None), Show.premiere_date >= start, Show.premiere_date <= end)
        )
        if payload.monitored_only:
            movies_q = movies_q.filter(Show.monitored.is_(True))
        for m in movies_q.all():
            m_ep = db.query(Episode).filter(Episode.show_id == m.id).first()
            if not m_ep or m_ep.status in (EpisodeStatus.MISSING, EpisodeStatus.WANTED):
                if m.id not in show_episode_map:
                    show_episode_map[m.id] = {m_ep.id} if m_ep else set()

    if not show_episode_map:
        return {
            "searched_shows": 0,
            "episodes_count": 0,
            "total_targets": 0,
            "message": "Отсутствующих серий и фильмов за выбранный период не найдено",
        }

    from app.services.task_manager import task_manager
    from app.database import SessionLocal

    async def _run_calendar_search_bg(targets: dict[int, set[int]]):
        async with task_manager.track(
            name="calendar_search",
            title="Поиск отсутствующих в календаре",
            message=f"Подготовка к поиску для {len(targets)} тайтлов...",
        ) as t_task:
            total_grabbed = 0
            from app.services.auto_search import search_and_grab_show
            for idx, (s_id, ep_ids) in enumerate(targets.items(), 1):
                with SessionLocal() as bg_db:
                    s_obj = bg_db.get(Show, s_id)
                    if not s_obj:
                        continue
                    t_task.update(
                        message=f"Поиск ({idx}/{len(targets)}): «{s_obj.title}»...",
                        progress=round(idx / max(1, len(targets)), 2),
                    )
                    try:
                        res = await search_and_grab_show(bg_db, s_obj, episode_ids=ep_ids if ep_ids else None, wanted_only=True)
                        if res.get("grabbed"):
                            total_grabbed += len(res["grabbed"])
                    except Exception:
                        pass
            if total_grabbed > 0:
                t_task.complete(f"Завершено: захвачено {total_grabbed} релиз(ов)")
            else:
                t_task.complete("Поиск завершён: подходящих релизов не найдено")

    import asyncio
    asyncio.create_task(_run_calendar_search_bg(show_episode_map))

    return {
        "searched_shows": len(show_episode_map),
        "episodes_count": len(missing_episodes),
        "total_targets": len(show_episode_map),
        "message": f"Поиск запущен для {len(show_episode_map)} тайтлов ({len(missing_episodes)} серий/фильмов)",
    }



def _build_ical_feed(entries: list[CalendarEntryOut], cal_name: str = "Aliasarr") -> str:
    """Генерирует стандартный iCalendar RFC 5545 фид."""
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Aliasarr//Calendar Feed//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{cal_name}",
        "X-WR-TIMEZONE:UTC",
    ]
    now_str = dt.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    for e in entries:
        if not e.air_date:
            continue
        dt_start = e.air_date.strftime("%Y%m%dT%H%M%SZ")
        dt_end = (e.air_date + dt.timedelta(hours=1)).strftime("%Y%m%dT%H%M%SZ")
        uid = f"aliasarr-{e.content_type}-{e.show_id}-{e.episode_id or 'prem'}@aliasarr"

        summary = e.show_title
        if e.content_type != "movie" and e.season is not None and e.episode is not None:
            summary += f" - S{e.season:02d}E{e.episode:02d}"
            if e.title:
                summary += f" - {e.title}"
        elif e.year:
            summary += f" ({e.year})"

        desc = f"Status: {e.status}\\nContent: {e.content_type}"
        if e.overview:
            clean_ov = e.overview.replace("\n", " ").replace("\r", "")
            desc += f"\\n\\n{clean_ov}"

        lines.append("BEGIN:VEVENT")
        lines.append(f"UID:{uid}")
        lines.append(f"DTSTAMP:{now_str}")
        lines.append(f"DTSTART:{dt_start}")
        lines.append(f"DTEND:{dt_end}")
        lines.append(f"SUMMARY:{summary}")
        lines.append(f"DESCRIPTION:{desc}")
        lines.append(f"CATEGORIES:{e.content_type.capitalize()},Aliasarr")
        lines.append("END:VEVENT")

    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


@router.get("/calendar/aliasarr.ics")
@router.get("/calendar.ics")
def get_calendar_ical(
    days_forward: int = 90,
    days_back: int = 14,
    monitored_only: bool = True,
    content_type: str = "all",
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("view_calendar")),
):
    """
    Экспорт календаря в формате iCalendar (.ics) для синхронизации с
    Apple Calendar, Google Calendar, Outlook, Thunderbird.
    """
    entries = get_calendar(
        days_forward=days_forward,
        days_back=days_back,
        monitored_only=monitored_only,
        content_type=content_type,
        status_filter="all",
        db=db,
        current_user=current_user,
    )
    content = _build_ical_feed(entries, cal_name="Aliasarr Releases")
    return Response(
        content=content,
        media_type="text/calendar; charset=utf-8",
        headers={"Content-Disposition": "inline; filename=\"aliasarr.ics\""},
    )


@router.get("/calendar/waiting", response_model=list[CalendarWaitingOut])
def get_calendar_waiting(db: Session = Depends(get_db), current_user: User = Depends(require_permission("view_calendar"))):
    """
    Список релизов в ожидании точной даты выхода (или временно вынесенных из календаря).
    """
    shows = (
        db.query(Show)
        .filter((Show.in_calendar.is_(False)) | ((Show.premiere_date.is_(None))))
        .filter(Show.calendar_waiting_dismissed.is_(False))
        .all()
    )
    out = []
    for show in shows:
        # Если у шоу уже есть хотя бы одна серия с датой выхода, ей не место в "ожидании"
        has_dated_episode = (
            db.query(Episode.id)
            .filter(Episode.show_id == show.id, Episode.air_date.isnot(None))
            .first()
        )
        if has_dated_episode and show.in_calendar:
            continue
        # Если контент уже полностью скачан, скрываем его из списка ожидаемых
        has_downloaded_episode = (
            db.query(Episode.id)
            .filter(Episode.show_id == show.id, Episode.status == EpisodeStatus.DOWNLOADED)
            .first()
        )
        if has_downloaded_episode:
            continue
        out.append(CalendarWaitingOut(
            show_id=show.id, show_title=show.title, poster_url=show.poster_url,
            content_type=show.content_type, expected_year=show.expected_year,
            expected_quarter=show.expected_quarter, monitored=show.monitored,
        ))
    return out


class MoveToCalendarIn(BaseModel):
    air_date: dt.datetime


@router.post("/calendar/waiting/{show_id}/dismiss")
def dismiss_from_waiting(
    show_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_permission("manage_calendar", "manage_library")),
):
    """Скрывает видео из списка «В ожидании даты выхода» без удаления из медиатеки."""
    show = db.get(Show, show_id)
    if not show:
        raise HTTPException(404, "Видео не найдено")
    show.calendar_waiting_dismissed = True
    db.add(show)
    db.commit()
    return {"success": True}


@router.post("/calendar/waiting/{show_id}/restore")
def restore_to_waiting(
    show_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_permission("manage_calendar", "manage_library")),
):
    """Возвращает скрытое видео обратно в список «В ожидании даты выхода»."""
    show = db.get(Show, show_id)
    if not show:
        raise HTTPException(404, "Видео не найдено")
    show.calendar_waiting_dismissed = False
    db.add(show)
    db.commit()
    return {"success": True}


@router.post("/calendar/waiting/{show_id}/refresh-release-date")
async def refresh_release_date(
    show_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_permission("manage_calendar", "manage_library")),
):
    """Повторный запрос к источникам метаданных для поиска актуальной даты премьеры."""
    from app.services.metadata import refresh_show_release_dates

    show = db.get(Show, show_id)
    if not show:
        raise HTTPException(404, "Видео не найдено")
    if not show.metadata_id:
        return {"success": False, "message": "Это видео добавлено вручную, без привязки к источнику метаданных — обновить дату неоткуда"}

    try:
        updated = await refresh_show_release_dates(db, show)
        if updated:
            return {"success": True, "message": "Дата выхода обновлена"}
        return {"success": False, "message": "Источник метаданных пока не сообщает точную дату выхода"}
    except Exception as exc:
        return {"success": False, "message": f"Ошибка обращения к источнику метаданных: {exc}"}


@router.post("/calendar/{show_id}/move-to-calendar")
def move_to_calendar(
    show_id: int,
    payload: MoveToCalendarIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_permission("manage_calendar", "manage_library")),
):
    """Ручной перенос тайтла из списка ожидания в календарь с указанной датой премьеры."""
    show = db.get(Show, show_id)
    if not show:
        raise HTTPException(404, "Шоу не найдено")
    show.premiere_date = payload.air_date
    show.in_calendar = True
    db.commit()
    return {"success": True}


@router.post("/calendar/{show_id}/move-to-waiting")
def move_to_waiting(
    show_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_permission("manage_calendar", "manage_library")),
):
    """Ручной перенос тайтла из календаря обратно в список ожидания."""
    show = db.get(Show, show_id)
    if not show:
        raise HTTPException(404, "Шоу не найдено")
    show.in_calendar = False
    show.premiere_date = None
    db.commit()
    return {"success": True}


class SetEpisodeAirDateIn(BaseModel):
    air_date: Optional[dt.datetime] = None  # None = убрать дату (вернуть в "неопределённую")


@router.put("/episodes/{episode_id}/air-date")
def set_episode_air_date(
    episode_id: int,
    payload: SetEpisodeAirDateIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_permission("manage_calendar", "manage_library")),
):
    """Ручная установка или снятие даты выхода для серии или фильма в календаре."""
    episode = db.get(Episode, episode_id)
    if not episode:
        raise HTTPException(404, "Серия не найдена")
    episode.air_date = payload.air_date
    if payload.air_date is None:
        if episode.status in (EpisodeStatus.UNAIRED, EpisodeStatus.WANTED):
            episode.status = EpisodeStatus.MISSING
    else:
        if episode.air_date > dt.datetime.utcnow() and episode.status in (EpisodeStatus.MISSING, EpisodeStatus.WANTED):
            episode.status = EpisodeStatus.UNAIRED
    db.add(episode)
    db.commit()
    return {"success": True}


class ScheduleWeeklyIn(BaseModel):
    season_number: int
    start_date: dt.datetime          # дата выхода первой серии
    weekday: Optional[int] = None       # 0=пн..6=вс; если не задан — берётся из start_date
    interval_days: int = 7           # обычно раз в неделю, но можно задать другой шаг
    only_undated: bool = True        # проставлять только сериям без текущей даты


@router.post("/calendar/{show_id}/schedule-weekly")
def schedule_weekly(
    show_id: int,
    payload: ScheduleWeeklyIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_permission("manage_calendar", "manage_library")),
):
    """Автоматическая расстановка дат выхода серий сезона с регулярным шагом."""
    show = db.get(Show, show_id)
    if not show:
        raise HTTPException(404, "Шоу не найдено")

    episodes = (
        db.query(Episode)
        .filter(Episode.show_id == show_id, Episode.season_number == payload.season_number)
        .order_by(Episode.episode_number)
        .all()
    )
    if not episodes:
        raise HTTPException(400, "У этого сезона ещё нет серий — сначала добавьте их через метаданные")

    if payload.only_undated:
        episodes = [ep for ep in episodes if ep.air_date is None]
    if not episodes:
        return {"updated": 0}

    start = payload.start_date
    now = dt.datetime.utcnow()
    updated = 0
    for i, ep in enumerate(episodes):
        ep.air_date = start + dt.timedelta(days=payload.interval_days * i)
        ep.status = EpisodeStatus.UNAIRED if ep.air_date > now else EpisodeStatus.MISSING
        db.add(ep)
        updated += 1

    show.in_calendar = True
    db.add(show)
    db.commit()
    return {"updated": updated}


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------

class HistoryEntryOut(BaseModel):
    id: int
    show_id: int
    show_title: str
    release_title: str
    event_type: str
    matched_alias: Optional[str] = None
    created_at: dt.datetime


@router.get("/history", response_model=list[HistoryEntryOut])
def get_history(
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("view_history")),
):
    entries = db.query(DownloadHistory).order_by(DownloadHistory.created_at.desc()).limit(limit).all()
    out = []
    for e in entries:
        show = db.get(Show, e.show_id)
        # show_title_snapshot фиксирует имя шоу на момент захвата — так история
        # остаётся понятной, даже если шоу потом переименовали или удалили.
        show_title = e.show_title_snapshot or (show.title if show else "? (видео удалено)")
        out.append(HistoryEntryOut(
            id=e.id, show_id=e.show_id, show_title=show_title,
            release_title=e.release_title, event_type=e.event_type,
            matched_alias=e.matched_alias, created_at=e.created_at,
        ))
    return out


# ---------------------------------------------------------------------------
# Queue / Activity — текущее состояние загрузок во всех download clients
# ---------------------------------------------------------------------------

class QueueItemOut(BaseModel):
    hash: str
    name: str
    progress: float
    state: str
    size: int
    download_client: str
    download_speed: int = 0
    upload_speed: int = 0
    eta: Optional[int] = None
    time_left: Optional[str] = None
    protocol: str = "torrent"
    show_id: Optional[int] = None
    show_title: Optional[str] = None
    episode_label: Optional[str] = None


def _format_eta(seconds: Optional[int]) -> Optional[str]:
    if not seconds or seconds <= 0:
        return None
    if seconds >= 86400:
        return f"{seconds // 86400}d {(seconds % 86400) // 3600}h"
    if seconds >= 3600:
        return f"{seconds // 3600}h {(seconds % 3600) // 60}m"
    if seconds >= 60:
        return f"{seconds // 60}m {seconds % 60}s"
    return f"{seconds}s"


@router.get("/queue", response_model=list[QueueItemOut])
async def get_queue(db: Session = Depends(get_db), current_user: User = Depends(require_permission("view_activity"))):
    items: list[QueueItemOut] = []
    
    # Кэшируем серии по хэшам
    episodes_by_hash: dict[str, list[Episode]] = {}
    for ep in db.query(Episode).filter(Episode.torrent_hash.isnot(None)).all():
        h = (ep.torrent_hash or "").lower()
        if h:
            episodes_by_hash.setdefault(h, []).append(ep)

    show_cache: dict[int, Show] = {}
    progress_updated = False

    for dc in db.query(DownloadClient).filter(DownloadClient.enabled == True).all():  # noqa: E712
        try:
            client = get_client(dc)
            torrents = await client.list_torrents()
        except Exception as exc:
            logger.warning("Не удалось получить список торрентов у %s: %s", dc.name, exc)
            continue
        for t in torrents:
            t_hash_clean = t.hash.lower()
            matching_eps = episodes_by_hash.get(t_hash_clean, [])
            show_id = None
            show_title = None
            ep_label = None

            if matching_eps:
                s_id = matching_eps[0].show_id
                show_id = s_id
                if s_id not in show_cache:
                    show_cache[s_id] = db.get(Show, s_id)
                if show_cache[s_id]:
                    show_title = show_cache[s_id].title
                
                if len(matching_eps) == 1:
                    ep_label = f"S{matching_eps[0].season_number:02d}E{matching_eps[0].episode_number:02d}"
                else:
                    ep_label = f"{len(matching_eps)} eps"

                for ep in matching_eps:
                    if ep.status == EpisodeStatus.DOWNLOADING and abs((ep.download_progress or 0) - t.progress) > 0.001:
                        ep.download_progress = t.progress
                        db.add(ep)
                        progress_updated = True

            items.append(QueueItemOut(
                hash=t.hash, name=t.name, progress=t.progress, state=t.state,
                size=t.size, download_client=dc.name,
                download_speed=getattr(t, "download_speed", 0) or 0,
                upload_speed=getattr(t, "upload_speed", 0) or 0,
                eta=getattr(t, "eta", None),
                time_left=_format_eta(getattr(t, "eta", None)),
                protocol=getattr(t, "protocol", "torrent") or "torrent",
                show_id=show_id,
                show_title=show_title,
                episode_label=ep_label,
            ))

    if progress_updated:
        try:
            db.commit()
        except Exception:
            db.rollback()

    return items


@router.post("/queue/{torrent_hash}/pause")
async def pause_queue_item(
    torrent_hash: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_activity")),
):
    """Приостанавливает загрузку в download client."""
    paused_in = []
    for dc in db.query(DownloadClient).filter(DownloadClient.enabled == True).all():  # noqa: E712
        try:
            client = get_client(dc)
            await client.pause_torrent(torrent_hash)
            paused_in.append(dc.name)
        except Exception:
            continue
    if not paused_in:
        raise HTTPException(404, "Раздача не найдена в активных клиентах")
    return {"status": "paused", "clients": paused_in}


@router.post("/queue/{torrent_hash}/resume")
async def resume_queue_item(
    torrent_hash: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_activity")),
):
    """Возобновляет загрузку в download client."""
    resumed_in = []
    for dc in db.query(DownloadClient).filter(DownloadClient.enabled == True).all():  # noqa: E712
        try:
            client = get_client(dc)
            await client.resume_torrent(torrent_hash)
            resumed_in.append(dc.name)
        except Exception:
            continue
    if not resumed_in:
        raise HTTPException(404, "Раздача не найдена в активных клиентах")
    return {"status": "resumed", "clients": resumed_in}


@router.delete("/queue/{torrent_hash}")
async def delete_queue_item(
    torrent_hash: str,
    delete_files: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_any_permission("manage_activity", "manual_search")),
):
    """
    Удаляет загрузку из очереди активности и торрент-клиента.
    Параметр delete_files=True удаляет загруженные файлы с диска.
    """
    removed_from = []
    for dc in db.query(DownloadClient).filter(DownloadClient.enabled == True).all():  # noqa: E712
        try:
            client = get_client(dc)
            torrents = await client.list_torrents()
            if not any(t.hash.lower() == torrent_hash.lower() for t in torrents):
                continue
            await client.remove_torrent(torrent_hash, delete_files=delete_files)
            removed_from.append(dc.name)
        except Exception:
            continue

    affected_episodes = db.query(Episode).filter(Episode.torrent_hash == torrent_hash).all()
    for ep in affected_episodes:
        ep.status = EpisodeStatus.WANTED
        ep.torrent_hash = None
        ep.download_client_id = None
        ep.download_progress = 0.0
        db.add(ep)
    db.commit()

    if not removed_from:
        raise HTTPException(404, "Раздача не найдена ни в одном из включённых download client'ов")

    return {"removed_from": removed_from, "affected_episodes": len(affected_episodes)}


@router.post("/queue/check")
async def trigger_check_downloads(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_activity")),
):
    """Принудительно запускает проверку и перенос завершённых загрузок."""
    from app.services.downloads_monitor import check_downloads
    results = await check_downloads(db)
    return {"status": "ok", "processed": len(results), "results": results}


class OrganizerPreviewIn(BaseModel):
    template: str
    content_type: str = "series"  # series | movie | anime
    title: str = "Attack on Titan"
    year: int = 2013
    season_number: int = 1
    episode_number: int = 5
    absolute_number: Optional[int] = 5
    episode_title: str = "First Battle"
    quality: str = "Bluray-1080p"
    release_group: str = "LostFilm"


@router.post("/organizer/preview")
def preview_organizer_filename(
    payload: OrganizerPreviewIn,
    current_user: User = Depends(get_current_user),
):
    """Предпросмотр форматирования имени файла по шаблону токенов Sonarr."""
    from app.services.organizer import FileNameBuilder
    from app.services.quality import parse_quality

    q = parse_quality(payload.quality)
    result = FileNameBuilder.build_file_name(
        template=payload.template,
        title=payload.title,
        year=payload.year,
        season_number=payload.season_number,
        episode_number=payload.episode_number,
        absolute_number=payload.absolute_number,
        episode_title=payload.episode_title,
        quality=q,
        release_group=payload.release_group,
        content_type=payload.content_type,
        extension=".mkv",
    )
    return {"preview": result}


# ---------------------------------------------------------------------------
# Ручной запуск авто-поиска wanted-серий
# ---------------------------------------------------------------------------

@router.post("/search/wanted")
async def trigger_wanted_search(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manual_search")),
):
    """Запускает немедленный поиск/захват для всех wanted-серий (обычно работает по расписанию)."""
    results = await run_wanted_search(db)
    return {"triggered": True, "grabbed_shows": len(results), "details": results}


@router.put("/episodes/{episode_id}/monitor")
def set_episode_status(
    episode_id: int,
    status: Optional[str] = None,
    monitored: Optional[bool] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_library")),
):
    episode = db.get(Episode, episode_id)
    if not episode:
        raise HTTPException(404, "Episode not found")

    if monitored is not None:
        target_monitored = monitored
    elif status is not None:
        target_monitored = (status != "ignored")
    else:
        target_monitored = True

    episode.monitored = target_monitored

    file_path = getattr(episode, "file_path", None)
    has_file = False
    if file_path:
        try:
            has_file = os.path.exists(file_path)
        except Exception:
            has_file = False

    status = getattr(episode, "status", None)
    if status in (EpisodeStatus.DOWNLOADED, EpisodeStatus.DOWNLOADING, "downloaded", "downloading") or has_file:
        # Статус уже скачанной или скачивающейся серии сохраняется, меняется только флаг мониторинга (для апгрейдов)
        if has_file and status not in (EpisodeStatus.DOWNLOADING, "downloading"):
            episode.status = EpisodeStatus.DOWNLOADED
    else:
        today = dt.date.today()
        air_d = getattr(episode, "air_date", None)
        if isinstance(air_d, dt.datetime):
            air_d = air_d.date()
        if target_monitored:
            episode.status = EpisodeStatus.UNAIRED if (air_d and air_d > today) else EpisodeStatus.WANTED
        else:
            episode.status = EpisodeStatus.IGNORED

    db.add(episode)
    db.commit()
    return {"episode_id": episode_id, "status": episode.status.value, "monitored": episode.monitored}


@router.post("/episodes/{episode_id}/search")
async def search_and_grab_episode(
    episode_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manual_search")),
):
    """Ищет релиз именно для этой серии и захватывает лучший найденный вариант."""
    from app.services.auto_search import search_and_grab_show

    episode = db.get(Episode, episode_id)
    if not episode:
        raise HTTPException(404, "Episode not found")

    show = db.get(Show, episode.show_id)
    previous_status = episode.status
    episode.status = EpisodeStatus.WANTED
    db.add(episode)
    db.commit()

    result = await search_and_grab_show(db, show, episode_ids={episode_id})
    grabbed_this_episode = [g for g in result.get("grabbed", []) if g["episode_id"] == episode_id]

    if not grabbed_this_episode:
        db.refresh(episode)
        if episode.status == EpisodeStatus.WANTED:
            episode.status = previous_status
            db.add(episode)
            db.commit()
        return {"success": False, "message": "Подходящих релизов не найдено"}

    return {"success": True, "message": "Релиз найден и отправлен в загрузчик", "details": grabbed_this_episode[0]}


# ---------------------------------------------------------------------------
# Background Tasks Hub (Sonarr-style Command / Task indicator)
# ---------------------------------------------------------------------------

@router.get("/tasks", summary="Статус активных фоновых операций")
def get_tasks_status(
    current_user: User = Depends(get_current_user),
):
    """Возвращает статус активных фоновых операций и недавнюю историю."""
    from app.services.task_manager import task_manager
    return task_manager.get_status()


@router.post("/tasks/clear-history", summary="Очистить историю фоновых операций")
def clear_tasks_history(
    current_user: User = Depends(get_current_user),
):
    """Очищает историю завершённых задач."""
    from app.services.task_manager import task_manager
    task_manager.clear_history()
    return {"success": True}


@router.post("/operations/refresh-all-metadata", summary="Запуск полного обновления метаданных библиотеки")
async def trigger_refresh_all_metadata(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_library")),
):
    """
    Запуск полного фонового обновления метаданных для всех тайтлов в библиотеке
    (Sonarr/Radarr Refresh Series/Movies).
    """
    from app.services.metadata import refresh_all_shows_metadata
    from app.database import SessionLocal

    async def _runner():
        async_db = SessionLocal()
        try:
            await refresh_all_shows_metadata(async_db, force=True, username=current_user.username)
        finally:
            async_db.close()

    background_tasks.add_task(_runner)
    return {"success": True, "message": "Запущено фоновое обновление метаданных библиотеки"}


