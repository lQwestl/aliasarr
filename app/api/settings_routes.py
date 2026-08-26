from __future__ import annotations

from typing import Optional, Any
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.settings_service import get_or_create_settings, is_api_key_from_env, regenerate_api_key

router = APIRouter(prefix="/api/v1/settings", tags=["settings"])


class SettingsOut(BaseModel):
    api_key: Optional[str] = None
    api_key_source: Optional[str] = None  # "env" | "generated" | None

    # Шаблоны переименования по категориям контента
    rename_template: str          # legacy, равнозначен rename_template_series
    rename_template_movie: str
    rename_template_series: str
    rename_template_anime: str

    # Шаблоны папок сезонов для сериалов и аниме
    season_folder_template_series: str = "Сезон {season}"
    season_folder_template_anime: str = "Сезон {season}"

    # Папки по категориям (слева — куда качает загрузчик из download client'ов,
    # справа — куда переносится и переименовывается готовое видео)
    root_folder: str              # legacy общая папка
    root_folder_movies: str
    root_folder_series: str
    root_folder_anime: str
    download_folder_movies: str
    download_folder_series: str
    download_folder_anime: str

    import_extra_files: bool = True
    extra_file_extensions: str = "srt, ass, sub, idx, vtt, nfo, mka, ttf, otf, woff"

    auth_enabled: bool
    login_enabled: bool
    username: str

    language: str   # ru | en
    theme: str      # dark | light

    min_seeds: int
    prefer_most_seeded: bool

    monitor_interval_minutes: int
    download_check_interval_minutes: int
    download_check_interval_seconds: int = 30
    tracker_check_interval_minutes: int = 30
    unaired_check_interval_minutes: int = 10

    indexer_check_enabled: bool
    indexer_check_interval_minutes: int
    indexer_check_retries: int
    indexer_check_retry_delay_seconds: int

    log_retention_days: int
    events_page_size: int

    timezone: str
    calendar_poll_enabled: bool
    calendar_poll_interval_minutes: int
    calendar_metadata_source: str  # auto | tmdb | tvmaze | skyhook | radarr
    calendar_metadata_source_series: str = "skyhook"
    calendar_metadata_source_movie: str = "radarr"
    metadata_auto_refresh_enabled: bool = True
    metadata_refresh_interval_hours: int = 12

    session_timeout_minutes: int
    backup_interval_days: int = 7
    backup_retention_count: int = 10
    backup_default_type: str = "full"


class SettingsUpdate(BaseModel):
    rename_template: Optional[str] = None
    rename_template_movie: Optional[str] = None
    rename_template_series: Optional[str] = None
    rename_template_anime: Optional[str] = None

    season_folder_template_series: Optional[str] = None
    season_folder_template_anime: Optional[str] = None

    root_folder: Optional[str] = None
    root_folder_movies: Optional[str] = None
    root_folder_series: Optional[str] = None
    root_folder_anime: Optional[str] = None
    download_folder_movies: Optional[str] = None
    download_folder_series: Optional[str] = None
    download_folder_anime: Optional[str] = None

    import_extra_files: Optional[bool] = None
    extra_file_extensions: Optional[str] = None

    auth_enabled: Optional[bool] = None

    language: Optional[str] = None
    theme: Optional[str] = None

    min_seeds: Optional[int] = None
    prefer_most_seeded: Optional[bool] = None

    monitor_interval_minutes: Optional[int] = None
    download_check_interval_minutes: Optional[int] = None
    download_check_interval_seconds: Optional[int] = None
    tracker_check_interval_minutes: Optional[int] = None
    unaired_check_interval_minutes: Optional[int] = None

    indexer_check_enabled: Optional[bool] = None
    indexer_check_interval_minutes: Optional[int] = None
    indexer_check_retries: Optional[int] = None
    indexer_check_retry_delay_seconds: Optional[int] = None

    log_retention_days: Optional[int] = None
    events_page_size: Optional[int] = None

    timezone: Optional[str] = None
    calendar_poll_enabled: Optional[bool] = None
    calendar_poll_interval_minutes: Optional[int] = None
    calendar_metadata_source: Optional[str] = None
    calendar_metadata_source_series: Optional[str] = None
    calendar_metadata_source_movie: Optional[str] = None
    metadata_auto_refresh_enabled: Optional[bool] = None
    metadata_refresh_interval_hours: Optional[int] = None

    session_timeout_minutes: Optional[int] = None
    backup_interval_days: Optional[int] = None
    backup_retention_count: Optional[int] = None
    backup_default_type: Optional[str] = None


def _to_settings_out(settings, is_owner: bool = False) -> SettingsOut:
    return SettingsOut(
        api_key=settings.api_key if is_owner else None,
        api_key_source=("env" if is_api_key_from_env() else "generated") if is_owner else None,
        rename_template=settings.rename_template_series or settings.rename_template,
        rename_template_movie=settings.rename_template_movie,
        rename_template_series=settings.rename_template_series,
        rename_template_anime=settings.rename_template_anime,
        season_folder_template_series=getattr(settings, "season_folder_template_series", "Сезон {season}") or "Сезон {season}",
        season_folder_template_anime=getattr(settings, "season_folder_template_anime", "Сезон {season}") or "Сезон {season}",
        root_folder=settings.root_folder,
        root_folder_movies=settings.root_folder_movies,
        root_folder_series=settings.root_folder_series,
        root_folder_anime=settings.root_folder_anime,
        download_folder_movies=settings.download_folder_movies,
        download_folder_series=settings.download_folder_series,
        download_folder_anime=settings.download_folder_anime,
        import_extra_files=getattr(settings, "import_extra_files", True),
        extra_file_extensions=getattr(settings, "extra_file_extensions", "srt, ass, sub, idx, vtt, nfo, mka, ttf, otf, woff") or "srt, ass, sub, idx, vtt, nfo, mka, ttf, otf, woff",
        auth_enabled=settings.auth_enabled,
        login_enabled=settings.login_enabled,
        username=settings.username,
        language=settings.language,
        theme=settings.theme,
        min_seeds=settings.min_seeds,
        prefer_most_seeded=settings.prefer_most_seeded,
        monitor_interval_minutes=settings.monitor_interval_minutes,
        download_check_interval_minutes=settings.download_check_interval_minutes,
        download_check_interval_seconds=getattr(settings, "download_check_interval_seconds", 30) or 30,
        tracker_check_interval_minutes=getattr(settings, "tracker_check_interval_minutes", 30) or 30,
        unaired_check_interval_minutes=getattr(settings, "unaired_check_interval_minutes", 10) or 10,
        indexer_check_enabled=settings.indexer_check_enabled,
        indexer_check_interval_minutes=settings.indexer_check_interval_minutes,
        indexer_check_retries=settings.indexer_check_retries,
        indexer_check_retry_delay_seconds=settings.indexer_check_retry_delay_seconds,
        log_retention_days=settings.log_retention_days,
        events_page_size=settings.events_page_size,
        timezone=settings.timezone,
        calendar_poll_enabled=settings.calendar_poll_enabled,
        calendar_poll_interval_minutes=settings.calendar_poll_interval_minutes,
        calendar_metadata_source=getattr(settings, "calendar_metadata_source", "auto"),
        calendar_metadata_source_series=getattr(settings, "calendar_metadata_source_series", "skyhook") or "skyhook",
        calendar_metadata_source_movie=getattr(settings, "calendar_metadata_source_movie", "radarr") or "radarr",
        metadata_auto_refresh_enabled=getattr(settings, "metadata_auto_refresh_enabled", True),
        metadata_refresh_interval_hours=getattr(settings, "metadata_refresh_interval_hours", 12) or 12,
        session_timeout_minutes=getattr(settings, "session_timeout_minutes", 43200) or 43200,
        backup_interval_days=getattr(settings, "backup_interval_days", 7) or 7,
        backup_retention_count=getattr(settings, "backup_retention_count", 10) or 10,
        backup_default_type=getattr(settings, "backup_default_type", "full") or "full",
    )


from app.models.db import User
from app.services.user_service import require_permission, get_current_user


@router.get("", response_model=SettingsOut, summary="Получить настройки системы")
def get_settings(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Возвращает текущие настройки системы (шаблоны переименования, папки, интервалы, часовой пояс и др.)."""
    return _to_settings_out(get_or_create_settings(db), is_owner=bool(current_user and current_user.is_owner))


def _reschedule(
    request: Request,
    job_id: str,
    minutes: Optional[int] = None,
    seconds: Optional[int] = None,
    hours: Optional[int] = None,
) -> None:
    """Применяет новый интервал периодической задачи на лету без перезапуска."""
    scheduler = getattr(request.app.state, "scheduler", None)
    if scheduler is None:
        return
    job = scheduler.get_job(job_id)
    if job is not None:
        if seconds is not None:
            scheduler.reschedule_job(job_id, trigger="interval", seconds=seconds)
        elif hours is not None:
            scheduler.reschedule_job(job_id, trigger="interval", hours=hours)
        elif minutes is not None:
            scheduler.reschedule_job(job_id, trigger="interval", minutes=minutes)


@router.put("", response_model=SettingsOut, summary="Обновить настройки системы")
def update_settings(
    payload: SettingsUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_settings")),
):
    """Обновляет настройки системы и на лету пересчитывает расписание фоновых задач."""
    settings = get_or_create_settings(db)

    if payload.rename_template is not None:
        settings.rename_template = payload.rename_template
        settings.rename_template_series = payload.rename_template
    if payload.rename_template_series is not None:
        settings.rename_template_series = payload.rename_template_series
        settings.rename_template = payload.rename_template_series
    if payload.rename_template_movie is not None:
        settings.rename_template_movie = payload.rename_template_movie
    if payload.rename_template_anime is not None:
        settings.rename_template_anime = payload.rename_template_anime

    if payload.season_folder_template_series is not None:
        settings.season_folder_template_series = payload.season_folder_template_series
    if payload.season_folder_template_anime is not None:
        settings.season_folder_template_anime = payload.season_folder_template_anime

    if payload.root_folder is not None:
        settings.root_folder = payload.root_folder
    if payload.root_folder_movies is not None:
        settings.root_folder_movies = payload.root_folder_movies
    if payload.root_folder_series is not None:
        settings.root_folder_series = payload.root_folder_series
    if payload.root_folder_anime is not None:
        settings.root_folder_anime = payload.root_folder_anime
    if payload.download_folder_movies is not None:
        settings.download_folder_movies = payload.download_folder_movies
    if payload.download_folder_series is not None:
        settings.download_folder_series = payload.download_folder_series
    if payload.download_folder_anime is not None:
        settings.download_folder_anime = payload.download_folder_anime

    if payload.import_extra_files is not None:
        settings.import_extra_files = payload.import_extra_files
    if payload.extra_file_extensions is not None:
        settings.extra_file_extensions = payload.extra_file_extensions

    if payload.auth_enabled is not None:
        settings.auth_enabled = payload.auth_enabled

    if payload.language is not None:
        if payload.language not in ("ru", "en"):
            raise HTTPException(400, "language должен быть 'ru' или 'en'")
        settings.language = payload.language
    if payload.theme is not None:
        if payload.theme not in ("dark", "light", "dracula", "obsidian"):
            raise HTTPException(400, "theme должна быть 'dark', 'obsidian', 'dracula' или 'light'")
        settings.theme = payload.theme

    if payload.min_seeds is not None:
        if payload.min_seeds < 0:
            raise HTTPException(400, "min_seeds не может быть отрицательным")
        settings.min_seeds = payload.min_seeds
    if payload.prefer_most_seeded is not None:
        settings.prefer_most_seeded = payload.prefer_most_seeded

    if payload.monitor_interval_minutes is not None:
        if payload.monitor_interval_minutes < 1:
            raise HTTPException(400, "Интервал должен быть не меньше 1 минуты")
        settings.monitor_interval_minutes = payload.monitor_interval_minutes
        _reschedule(request, "wanted_search", minutes=payload.monitor_interval_minutes)
    if payload.download_check_interval_seconds is not None:
        if payload.download_check_interval_seconds < 5:
            raise HTTPException(400, "Интервал проверки загрузок должен быть не меньше 5 секунд")
        settings.download_check_interval_seconds = payload.download_check_interval_seconds
        settings.download_check_interval_minutes = max(1, round(payload.download_check_interval_seconds / 60))
        _reschedule(request, "downloads_check", seconds=payload.download_check_interval_seconds)
    elif payload.download_check_interval_minutes is not None:
        if payload.download_check_interval_minutes < 1:
            raise HTTPException(400, "Интервал должен быть не меньше 1 минуты")
        settings.download_check_interval_minutes = payload.download_check_interval_minutes
        settings.download_check_interval_seconds = payload.download_check_interval_minutes * 60
        _reschedule(request, "downloads_check", seconds=settings.download_check_interval_seconds)

    if payload.tracker_check_interval_minutes is not None:
        if payload.tracker_check_interval_minutes < 1:
            raise HTTPException(400, "Интервал слежения за раздачами должен быть не меньше 1 минуты")
        settings.tracker_check_interval_minutes = payload.tracker_check_interval_minutes
        _reschedule(request, "recheck_tracked_releases", minutes=payload.tracker_check_interval_minutes)

    if payload.unaired_check_interval_minutes is not None:
        if payload.unaired_check_interval_minutes < 1:
            raise HTTPException(400, "Интервал активации премьер должен быть не меньше 1 минуты")
        settings.unaired_check_interval_minutes = payload.unaired_check_interval_minutes
        _reschedule(request, "activate_unaired", minutes=payload.unaired_check_interval_minutes)

    if payload.indexer_check_enabled is not None:
        settings.indexer_check_enabled = payload.indexer_check_enabled
    if payload.indexer_check_interval_minutes is not None:
        if payload.indexer_check_interval_minutes < 1:
            raise HTTPException(400, "Интервал должен быть не меньше 1 минуты")
        settings.indexer_check_interval_minutes = payload.indexer_check_interval_minutes
        _reschedule(request, "indexer_availability", payload.indexer_check_interval_minutes)
    if payload.indexer_check_retries is not None:
        if payload.indexer_check_retries < 1:
            raise HTTPException(400, "Число попыток должно быть не меньше 1")
        settings.indexer_check_retries = payload.indexer_check_retries
    if payload.indexer_check_retry_delay_seconds is not None:
        settings.indexer_check_retry_delay_seconds = max(0, payload.indexer_check_retry_delay_seconds)

    if payload.log_retention_days is not None:
        if payload.log_retention_days < 1:
            raise HTTPException(400, "Срок хранения должен быть не меньше 1 дня")
        settings.log_retention_days = payload.log_retention_days
    if payload.events_page_size is not None:
        if payload.events_page_size < 5:
            raise HTTPException(400, "Размер страницы должен быть не меньше 5")
        settings.events_page_size = payload.events_page_size

    if payload.timezone is not None:
        settings.timezone = payload.timezone.strip() or "UTC"
    if payload.calendar_poll_enabled is not None:
        settings.calendar_poll_enabled = payload.calendar_poll_enabled
    if payload.calendar_poll_interval_minutes is not None:
        if payload.calendar_poll_interval_minutes < 5:
            raise HTTPException(400, "Интервал опроса должен быть не меньше 5 минут")
        settings.calendar_poll_interval_minutes = payload.calendar_poll_interval_minutes
        _reschedule(request, "calendar_poll", payload.calendar_poll_interval_minutes)
    if payload.calendar_metadata_source is not None:
        allowed = ("auto", "skyhook", "radarr", "tmdb", "thetvdb", "tvmaze")
        if payload.calendar_metadata_source not in allowed:
            raise HTTPException(400, f"calendar_metadata_source должен быть одним из: {', '.join(allowed)}")
        settings.calendar_metadata_source = payload.calendar_metadata_source
    if payload.calendar_metadata_source_series is not None:
        allowed_series = ("skyhook", "thetvdb", "tvmaze", "tmdb", "auto")
        if payload.calendar_metadata_source_series not in allowed_series:
            raise HTTPException(400, f"calendar_metadata_source_series должен быть одним из: {', '.join(allowed_series)}")
        settings.calendar_metadata_source_series = payload.calendar_metadata_source_series
    if payload.calendar_metadata_source_movie is not None:
        allowed_movie = ("radarr", "tmdb", "auto")
        if payload.calendar_metadata_source_movie not in allowed_movie:
            raise HTTPException(400, f"calendar_metadata_source_movie должен быть одним из: {', '.join(allowed_movie)}")
        settings.calendar_metadata_source_movie = payload.calendar_metadata_source_movie

    if payload.metadata_auto_refresh_enabled is not None:
        settings.metadata_auto_refresh_enabled = payload.metadata_auto_refresh_enabled
    if payload.metadata_refresh_interval_hours is not None:
        if payload.metadata_refresh_interval_hours < 1:
            raise HTTPException(400, "Интервал обновления метаданных должен быть не меньше 1 часа")
        settings.metadata_refresh_interval_hours = payload.metadata_refresh_interval_hours
        _reschedule(request, "refresh_metadata", payload.metadata_refresh_interval_hours * 60)

    if payload.session_timeout_minutes is not None:
        if payload.session_timeout_minutes < 5:
            raise HTTPException(400, "Таймаут сессии не может быть меньше 5 минут")
        settings.session_timeout_minutes = payload.session_timeout_minutes

    db.add(settings)
    db.commit()
    db.refresh(settings)

    from app.services.audit_service import log_audit
    log_audit(
        db,
        action="settings.update",
        description="Обновлены общие настройки системы",
        user=current_user,
        request=request,
    )
    return _to_settings_out(settings, is_owner=bool(current_user and current_user.is_owner))


@router.post("/regenerate-api-key", response_model=SettingsOut)
def regenerate_key(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_settings")),
):
    """Генерирует новый API-ключ прямо из интерфейса (старый ключ перестаёт действовать). Только для главного администратора."""
    if not current_user.is_owner:
        raise HTTPException(403, "Только главный администратор может генерировать системный API-ключ")

    try:
        settings = regenerate_api_key(db)
    except ValueError as exc:
        raise HTTPException(400, str(exc))

    from app.services.audit_service import log_audit
    log_audit(
        db,
        action="settings.regenerate_api_key",
        description="Сгенерирован новый системный API-ключ",
        user=current_user,
        request=request,
    )
    return _to_settings_out(settings, is_owner=True)


class SslSettingsUpdate(BaseModel):
    ssl_enabled: Optional[bool] = None
    ssl_port: Optional[int] = None
    ssl_auto_renew: Optional[bool] = None


@router.get("/ssl")
def get_ssl_settings(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_settings")),
):
    settings = get_or_create_settings(db)
    from app.services.ssl_service import ensure_ssl_certificate, get_ssl_certificate_info
    cert_info = ensure_ssl_certificate(settings.ssl_cert_path, settings.ssl_key_path) if settings.ssl_enabled else get_ssl_certificate_info(settings.ssl_cert_path, settings.ssl_key_path)
    return {
        "ssl_enabled": bool(getattr(settings, "ssl_enabled", False)),
        "ssl_port": getattr(settings, "ssl_port", 8989) or 8989,
        "ssl_cert_path": getattr(settings, "ssl_cert_path", "/config/ssl/cert.pem") or "/config/ssl/cert.pem",
        "ssl_key_path": getattr(settings, "ssl_key_path", "/config/ssl/key.pem") or "/config/ssl/key.pem",
        "ssl_auto_renew": bool(getattr(settings, "ssl_auto_renew", True)),
        "cert_info": cert_info,
    }


@router.post("/ssl")
def update_ssl_settings(
    payload: SslSettingsUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_settings")),
):
    settings = get_or_create_settings(db)
    from app.services.ssl_service import ensure_ssl_certificate, trigger_server_restart

    prev_ssl_enabled = bool(getattr(settings, "ssl_enabled", False))
    prev_ssl_port = int(getattr(settings, "ssl_port", 8989) or 8989)

    if payload.ssl_enabled is not None:
        settings.ssl_enabled = payload.ssl_enabled
        if settings.ssl_enabled:
            ensure_ssl_certificate(settings.ssl_cert_path, settings.ssl_key_path)
    if payload.ssl_port is not None:
        if payload.ssl_port < 1 or payload.ssl_port > 65535:
            raise HTTPException(400, "Порт должен быть в диапазоне 1-65535")
        settings.ssl_port = payload.ssl_port
    if payload.ssl_auto_renew is not None:
        settings.ssl_auto_renew = payload.ssl_auto_renew

    db.add(settings)
    db.commit()
    db.refresh(settings)

    from app.services.audit_service import log_audit
    log_audit(
        db,
        action="settings.ssl_update",
        description=f"Обновлены настройки SSL/HTTPS (включен: {settings.ssl_enabled}, порт: {settings.ssl_port})",
        user=current_user,
        request=request,
    )

    # Если изменился статус SSL или порт — перезапускаем сервер для немедленного применения
    if (payload.ssl_enabled is not None and payload.ssl_enabled != prev_ssl_enabled) or \
       (payload.ssl_port is not None and payload.ssl_port != prev_ssl_port):
        trigger_server_restart(delay_seconds=0.8)

    return get_ssl_settings(db=db, current_user=current_user)


@router.post("/ssl/regenerate")
def regenerate_ssl_cert(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("manage_settings")),
):
    settings = get_or_create_settings(db)
    from app.services.ssl_service import generate_self_signed_certificate
    cert_info = generate_self_signed_certificate(settings.ssl_cert_path, settings.ssl_key_path)

    from app.services.audit_service import log_audit
    log_audit(
        db,
        action="settings.ssl_regenerate",
        description="Перевыпущен самоподписанный SSL-сертификат Aliasarr",
        user=current_user,
        request=request,
    )
    return {
        "success": True,
        "message": "SSL-сертификат успешно перевыпущен",
        "cert_info": cert_info,
    }
