"""
Модель данных (SQLAlchemy 2.x, SQLite по умолчанию / Postgres опционально).

Ключевые сущности:
- Show: шоу (сериал/аниме)
- Alias: альтернативное имя шоу (рус/eng/jp/romaji)
- Season / Episode: структура сезонов и серий
- Indexer: подключённый источник поиска (Jackett/Prowlarr/Torznab)
- MetadataSource: подключаемый источник метаданных (TVDB/IMDb/TMDB/кастом)
- TrackedRelease: раздача, за которой следим (слежение за топиком, п.4.8/5.5)
- QualityProfile: профиль качества
"""

from __future__ import annotations

from typing import Optional, List, Dict, Any

import datetime as dt
import enum

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum as SAEnum,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class MonitorStatus(str, enum.Enum):
    MONITORED = "monitored"
    IGNORED = "ignored"


class EpisodeStatus(str, enum.Enum):
    UNAIRED = "unaired"      # дата выхода в будущем
    MISSING = "missing"      # дата выхода прошла, но серии нет и она не разыскивается
    WANTED = "wanted"        # разыскивается автопоиском
    DOWNLOADING = "downloading"
    DOWNLOADED = "downloaded"
    IGNORED = "ignored"


class AliasLanguage(str, enum.Enum):
    RU = "ru"
    EN = "en"
    JP = "jp"
    ROMAJI = "romaji"
    OTHER = "other"


class IndexerType(str, enum.Enum):
    """Поддерживаемые типы индексаторов:
    - torznab: Torznab-совместимые API (Prowlarr, Jackett, трекеры)
    - newznab: Usenet / Newznab API
    - nyaa: Nyaa.si аниме-трекер
    - torrent_rss: Универсальный Torrent RSS-фид
    - iptorrents: IPTorrents API / RSS
    - torrentleech: TorrentLeech RSS
    """
    TORZNAB = "torznab"
    NEWZNAB = "newznab"
    NYAA = "nyaa"
    TORRENT_RSS = "torrent_rss"
    IPTORRENTS = "iptorrents"
    TORRENTLEECH = "torrentleech"


class MetadataSourceType(str, enum.Enum):
    SKYHOOK = "skyhook"
    RADARR = "radarr"
    TMDB = "tmdb"
    TVMAZE = "tvmaze"
    THETVDB = "thetvdb"
    CUSTOM = "custom"


class ContentCategory(str, enum.Enum):
    """Категория видео — определяет корневую папку медиатеки и шаблон переименования."""
    MOVIE = "movie"
    SERIES = "series"
    ANIME = "anime"


class Show(Base):
    __tablename__ = "shows"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    year: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    metadata_source: Mapped[str] = mapped_column(String(50), default="tmdb")
    metadata_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    overview: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    poster_url: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    path: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)  # папка на диске
    monitored: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    quality_profile_id: Mapped[Optional[int]] = mapped_column(ForeignKey("quality_profiles.id"), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow)
    last_search_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime, nullable=True)
    last_search_result: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    is_searching: Mapped[bool] = mapped_column(Boolean, default=False)

    # Расширенные метаданные контента
    network: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)  # Сеть/сервис вещания (Netflix, HBO, Tokyo MX...)
    rating: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    country: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    genre: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    content_type: Mapped[str] = mapped_column(String(20), default="series", index=True)  # movie | series | anime (см. ContentCategory)
    ova_mode: Mapped[str] = mapped_column(String(20), default="auto")  # auto | season_1 | specials
    premiere_date: Mapped[Optional[dt.datetime]] = mapped_column(DateTime, nullable=True)
    # Ожидаемый год/квартал выхода (когда точной даты премьеры ещё нет в метаданных)
    expected_year: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    expected_quarter: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # 1-4
    in_calendar: Mapped[bool] = mapped_column(Boolean, default=True)
    # Флаг скрытия из списка неанонсированных тайтлов в календаре без удаления из библиотеки
    calendar_waiting_dismissed: Mapped[bool] = mapped_column(Boolean, default=False)
    # Время последней полной синхронизации метаданных из сети
    last_metadata_refresh_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime, nullable=True)
    # Флаг явного запроса на улучшение качества (автопоиск лучшего качества до достижения Cutoff)
    upgrade_requested: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    aliases: Mapped[list["Alias"]] = relationship(back_populates="show", cascade="all, delete-orphan")
    episodes: Mapped[list["Episode"]] = relationship(back_populates="show", cascade="all, delete-orphan")
    tracked_releases: Mapped[list["TrackedRelease"]] = relationship(back_populates="show", cascade="all, delete-orphan")
    download_history: Mapped[list["DownloadHistory"]] = relationship(back_populates="show", cascade="all, delete-orphan")
    blocklist_entries: Mapped[list["Blocklist"]] = relationship(
        "Blocklist",
        back_populates="show",
        foreign_keys="Blocklist.show_id",
        primaryjoin="Show.id == foreign(Blocklist.show_id)",
    )


class Alias(Base):
    __tablename__ = "aliases"
    __table_args__ = (UniqueConstraint("show_id", "text", name="uq_alias_show_text"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    show_id: Mapped[int] = mapped_column(ForeignKey("shows.id"), nullable=False, index=True)
    text: Mapped[str] = mapped_column(String(500), nullable=False, index=True)
    language: Mapped[AliasLanguage] = mapped_column(SAEnum(AliasLanguage), default=AliasLanguage.RU)
    source: Mapped[str] = mapped_column(String(50), default="manual")  # manual | tmdb | tvmaze | thetvdb | skyhook | custom
    # Приоритет перебора алиасов при поиске: меньшее число = опрашивается раньше
    priority: Mapped[int] = mapped_column(Integer, default=1)

    show: Mapped["Show"] = relationship(back_populates="aliases")


class Episode(Base):
    __tablename__ = "episodes"
    __table_args__ = (UniqueConstraint("show_id", "season_number", "episode_number", name="uq_episode"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    show_id: Mapped[int] = mapped_column(ForeignKey("shows.id"), nullable=False, index=True)
    season_number: Mapped[int] = mapped_column(Integer, nullable=False)
    episode_number: Mapped[int] = mapped_column(Integer, nullable=False)
    absolute_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    title: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    air_date: Mapped[Optional[dt.date]] = mapped_column(DateTime, nullable=True, index=True)
    status: Mapped[EpisodeStatus] = mapped_column(SAEnum(EpisodeStatus), default=EpisodeStatus.MISSING, index=True)
    monitored: Mapped[bool] = mapped_column(Boolean, default=True)
    upgrade_requested: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    file_path: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)

    # Привязка к активной загрузке в клиенте
    download_client_id: Mapped[Optional[int]] = mapped_column(ForeignKey("download_clients.id", ondelete="SET NULL"), nullable=True)
    torrent_hash: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    download_progress: Mapped[float] = mapped_column(Float, default=0.0)  # 0..1 для прогресс-бара
    downloaded_quality: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # Технические свойства медиафайла
    video_codec: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    audio_codec: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    audio_channels: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    dynamic_range: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    release_group: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    languages: Mapped[list] = mapped_column(JSON, default=list)
    custom_format_score: Mapped[int] = mapped_column(Integer, default=0)
    file_size_bytes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    show: Mapped["Show"] = relationship(back_populates="episodes")


class CustomFormat(Base):
    """Кастомный формат релиза (Sonarr v4/v5 Custom Formats).
    Содержит правила скоринга для выбора релизов (HDR, TrueHD, Preferred Groups, Repack и т.д.).
    """
    __tablename__ = "custom_formats"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    score: Mapped[int] = mapped_column(Integer, default=0)
    include_custom_format_when_renaming: Mapped[bool] = mapped_column(Boolean, default=False)
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False)
    specifications: Mapped[list] = mapped_column(JSON, default=list)


class QualityProfile(Base):
    __tablename__ = "quality_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    allowed_qualities: Mapped[list] = mapped_column(JSON, default=list)  # напр. ["1080p","720p"]
    min_size_mb: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    max_size_mb: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    upgrade_allowed: Mapped[bool] = mapped_column(Boolean, default=True)
    cutoff_quality: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    cutoff_score: Mapped[int] = mapped_column(Integer, default=0)
    format_items: Mapped[list] = mapped_column(JSON, default=list)  # [{"format_id": 1, "name": "HDR10+", "score": 100}]


class Indexer(Base):
    __tablename__ = "indexers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    type: Mapped[IndexerType] = mapped_column(SAEnum(IndexerType), nullable=False)
    base_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    api_key: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    categories: Mapped[list] = mapped_column(JSON, default=list)
    priority: Mapped[int] = mapped_column(Integer, default=25)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=30)

    # Настройки сидирования и сохранения раздачи (для приватных трекеров с рейтингом)
    enable_seeding: Mapped[bool] = mapped_column(Boolean, default=False)
    seed_ratio_limit: Mapped[Optional[float]] = mapped_column(Float, nullable=True, default=None)
    seed_time_limit_hours: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, default=None)

    # Статус доступности torznab-эндпоинта
    last_check_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime, nullable=True)
    last_check_ok: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)  # None = ещё не проверялось
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)


class MetadataSource(Base):
    __tablename__ = "metadata_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    type: Mapped[str] = mapped_column(String(50), default="tmdb")
    base_url: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    api_key: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    field_mapping: Mapped[dict] = mapped_column(JSON, default=dict)  # маппинг полей ответа API
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class TrackedRelease(Base):
    """
    Слежение за раздачей (ключевая фича, п.4.8/5.5).
    Хранит, из какого топика скачаны какие серии, чтобы докачивать новые
    при обновлении раздачи на трекере (типично для rutracker).
    """

    __tablename__ = "tracked_releases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    show_id: Mapped[int] = mapped_column(ForeignKey("shows.id"), nullable=False, index=True)
    indexer_id: Mapped[Optional[int]] = mapped_column(ForeignKey("indexers.id", ondelete="CASCADE"), nullable=True)
    topic_guid: Mapped[str] = mapped_column(String(500), nullable=False)  # guid/id топика на трекере
    topic_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    infohash: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    downloaded_episodes: Mapped[list] = mapped_column(JSON, default=list)  # [{"season":1,"episode":5,"file":"..."}]
    last_checked_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime, nullable=True)
    last_updated_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime, nullable=True)  # когда топик обновился
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)

    show: Mapped["Show"] = relationship(back_populates="tracked_releases")


class DownloadHistory(Base):
    __tablename__ = "download_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    show_id: Mapped[int] = mapped_column(ForeignKey("shows.id", ondelete="CASCADE"), nullable=False, index=True)
    episode_id: Mapped[Optional[int]] = mapped_column(ForeignKey("episodes.id", ondelete="CASCADE"), nullable=True)
    release_title: Mapped[str] = mapped_column(String(1000), nullable=False)
    indexer_id: Mapped[Optional[int]] = mapped_column(ForeignKey("indexers.id", ondelete="SET NULL"), nullable=True)
    torrent_hash: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    event_type: Mapped[str] = mapped_column(String(50), default="grabbed")  # grabbed|imported|failed
    matched_alias: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)  # по какому алиасу нашли релиз
    show_title_snapshot: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)  # имя шоу на момент захвата
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow, index=True)

    show: Mapped[Optional["Show"]] = relationship(back_populates="download_history")


class DownloadClient(Base):
    __tablename__ = "download_clients"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    type: Mapped[str] = mapped_column(String(50), nullable=False)  # qbittorrent|transmission
    host: Mapped[str] = mapped_column(String(300), nullable=False)
    port: Mapped[int] = mapped_column(Integer, nullable=False)
    username: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    password: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    category: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, default="aliasarr")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    is_available: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True, default=None)
    last_checked_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    # Время раздачи скачанного контента перед импортом (в минутах; 0/None = импортировать сразу)
    seed_time_limit: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, default=None)
    # Коэффициент раздачи (Ratio limit; None/0 = без ограничения)
    seed_ratio_limit: Mapped[Optional[float]] = mapped_column(Float, nullable=True, default=None)


class NotificationConfig(Base):
    __tablename__ = "notification_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    type: Mapped[str] = mapped_column(String(50), nullable=False)  # telegram|discord|gotify|ntfy|pushover|slack|webhook|email|pushbullet|apprise|script
    settings: Mapped[dict] = mapped_column(JSON, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    # События уведомлений (Sonarr-совместимые triggers)
    on_grab: Mapped[bool] = mapped_column(Boolean, default=True)
    on_import: Mapped[bool] = mapped_column(Boolean, default=True)
    on_upgrade: Mapped[bool] = mapped_column(Boolean, default=True)
    on_rename: Mapped[bool] = mapped_column(Boolean, default=False)
    on_series_add: Mapped[bool] = mapped_column(Boolean, default=False)
    on_series_delete: Mapped[bool] = mapped_column(Boolean, default=False)
    on_episode_file_delete: Mapped[bool] = mapped_column(Boolean, default=False)
    on_episode_file_delete_for_upgrade: Mapped[bool] = mapped_column(Boolean, default=False)
    on_health_issue: Mapped[bool] = mapped_column(Boolean, default=True)
    on_health_restored: Mapped[bool] = mapped_column(Boolean, default=False)
    on_application_update: Mapped[bool] = mapped_column(Boolean, default=False)
    on_manual_interaction_required: Mapped[bool] = mapped_column(Boolean, default=True)
    on_backup: Mapped[bool] = mapped_column(Boolean, default=False)


class AppSettings(Base):
    """Единственная строка глобальных настроек приложения."""

    __tablename__ = "app_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    api_key: Mapped[str] = mapped_column(String(100), nullable=False)

    # Шаблоны переименования по категории (Sonarr-формат)
    rename_template: Mapped[str] = mapped_column(
        String(500),
        default="{Series Title} - S{season:00}E{episode:00} - {Episode Title} {Quality Full}",
    )  # legacy, используется как шаблон "Сериал" для обратной совместимости
    rename_template_movie: Mapped[str] = mapped_column(
        String(500), default="{Movie Title} ({Release Year}) {Quality Full}",
    )
    rename_template_series: Mapped[str] = mapped_column(
        String(500),
        default="{Series Title} - S{season:00}E{episode:00} - {Episode Title} {Quality Full}",
    )
    rename_template_anime: Mapped[str] = mapped_column(
        String(500),
        default="{Series Title} - S{season:00}E{episode:00} - {Episode Title} {Quality Full}",
    )

    # Шаблоны папок сезонов для сериалов и аниме (например: "Сезон {season}", "Season {season:00}", "S{season:00}")
    season_folder_template_series: Mapped[str] = mapped_column(
        String(500), default="Сезон {season}",
    )
    season_folder_template_anime: Mapped[str] = mapped_column(
        String(500), default="Сезон {season}",
    )

    root_folder: Mapped[str] = mapped_column(String(1000), default="/data")  # legacy общая папка
    root_folder_movies: Mapped[str] = mapped_column(String(1000), default="")
    root_folder_series: Mapped[str] = mapped_column(String(1000), default="")
    root_folder_anime: Mapped[str] = mapped_column(String(1000), default="")

    # Папки для скачивания (куда загрузчик сохраняет временные файлы перед импортом в медиатеку)
    download_folder_movies: Mapped[str] = mapped_column(String(1000), default="")
    download_folder_series: Mapped[str] = mapped_column(String(1000), default="")
    download_folder_anime: Mapped[str] = mapped_column(String(1000), default="")

    # Управление медиа: импорт сопутствующих файлов (субтитры, озвучки, шрифты, NFO)
    import_extra_files: Mapped[bool] = mapped_column(Boolean, default=True)
    extra_file_extensions: Mapped[str] = mapped_column(
        String(500), default="srt, ass, sub, idx, vtt, nfo, mka, ttf, otf, woff",
    )
    # Использовать Hardlinks (жесткие ссылки) вместо копирования для сидируемых раздач (0 байт лишнего места)
    use_hardlinks: Mapped[bool] = mapped_column(Boolean, default=True)

    auth_enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    # Логин по паре логин/пароль (независимо от API-ключа)
    login_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    username: Mapped[str] = mapped_column(String(200), default="admin")
    password_hash: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)

    # Локализация и тема оформления
    language: Mapped[str] = mapped_column(String(5), default="ru")   # ru | en
    theme: Mapped[str] = mapped_column(String(20), default="dark")   # dark | light | dracula | obsidian
    scrollbar_mode: Mapped[str] = mapped_column(String(50), default="autohide")  # autohide | styled | hidden | native

    # Настройки выбора релиза при автопоиске
    min_seeds: Mapped[int] = mapped_column(Integer, default=0)              # 0 = без ограничения
    prefer_most_seeded: Mapped[bool] = mapped_column(Boolean, default=True)  # качать самый популярный релиз

    # Интервалы фоновых задач
    monitor_interval_minutes: Mapped[int] = mapped_column(Integer, default=15)
    download_check_interval_minutes: Mapped[int] = mapped_column(Integer, default=2)
    download_check_interval_seconds: Mapped[int] = mapped_column(Integer, default=30)
    tracker_check_interval_minutes: Mapped[int] = mapped_column(Integer, default=30)
    unaired_check_interval_minutes: Mapped[int] = mapped_column(Integer, default=10)

    # Проверка доступности индексаторов
    indexer_check_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    indexer_check_interval_minutes: Mapped[int] = mapped_column(Integer, default=30)
    indexer_check_retries: Mapped[int] = mapped_column(Integer, default=3)
    indexer_check_retry_delay_seconds: Mapped[int] = mapped_column(Integer, default=5)

    # Системный журнал — срок хранения записей (в днях)
    log_retention_days: Mapped[int] = mapped_column(Integer, default=14)
    events_page_size: Mapped[int] = mapped_column(Integer, default=50)

    # Часовой пояс приложения (хранится в формате IANA, например "Europe/Moscow"; даты в БД в UTC)
    timezone: Mapped[str] = mapped_column(String(64), default="UTC")

    # Периодический опрос дат выхода для невышедших серий и фильмов
    calendar_poll_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    calendar_poll_interval_minutes: Mapped[int] = mapped_column(Integer, default=180)

    # Источники данных для календаря
    calendar_metadata_source: Mapped[str] = mapped_column(String(20), default="auto")
    calendar_metadata_source_series: Mapped[str] = mapped_column(String(20), default="skyhook")
    calendar_metadata_source_movie: Mapped[str] = mapped_column(String(20), default="radarr")

    # Автоматическое регулярное обновление метаданных библиотеки
    metadata_auto_refresh_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    metadata_refresh_interval_hours: Mapped[int] = mapped_column(Integer, default=12)  # 6, 12, 24, 72, 168
    metadata_sources_seeded: Mapped[bool] = mapped_column(Boolean, default=False)

    # Таймаут сессии авторизации в минутах (по умолчанию 30 дней = 43200 минут)
    session_timeout_minutes: Mapped[int] = mapped_column(Integer, default=43200)

    # Разрешить беспарольный доступ из локальной/приватной сети
    auth_disabled_for_local_addresses: Mapped[bool] = mapped_column(Boolean, default=True)

    # SSL / HTTPS настройки (самоподписанный сертификат с авто-продлением)
    ssl_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    ssl_port: Mapped[int] = mapped_column(Integer, default=8989)
    ssl_cert_path: Mapped[str] = mapped_column(String(500), default="/config/ssl/cert.pem")
    ssl_key_path: Mapped[str] = mapped_column(String(500), default="/config/ssl/key.pem")
    ssl_auto_renew: Mapped[bool] = mapped_column(Boolean, default=True)

    # Двухфакторная аутентификация 2FA TOTP
    totp_2fa_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    totp_2fa_policy: Mapped[str] = mapped_column(String(50), default="users_choice")  # "users_choice" | "enforce_all"

    # Резервное копирование (Backup)
    backup_interval_days: Mapped[int] = mapped_column(Integer, default=7)       # 0 = выкл, 1 = ежедневно, 7 = еженедельно, 30 = ежемесячно
    backup_retention_count: Mapped[int] = mapped_column(Integer, default=10)    # сколько последних копий хранить
    backup_default_type: Mapped[str] = mapped_column(String(20), default="full")  # full | config


class User(Base):
    """Модель пользователя с поддержкой ролей и прав доступа (RBAC)."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(300), nullable=False)
    display_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    is_owner: Mapped[bool] = mapped_column(Boolean, default=False)  # Главный админ (нельзя удалить или заблокировать)
    avatar: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # Data-URL или путь
    permissions: Mapped[dict] = mapped_column(JSON, default=dict)    # {"manage_library": true, "manual_search": true, ...}
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    session_timeout_minutes: Mapped[int] = mapped_column(Integer, default=43200)
    api_key: Mapped[Optional[str]] = mapped_column(String(100), unique=True, index=True, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow)
    last_login_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime, nullable=True)

    # 2FA TOTP
    totp_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    totp_secret: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    totp_confirmed_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime, nullable=True)

    sessions: Mapped[list["Session"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class LogEntry(Base):
    """Таблица системных событий и диагностического журнала."""

    __tablename__ = "log_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow, index=True)
    level: Mapped[str] = mapped_column(String(20), default="info")  # debug|info|warning|error
    component: Mapped[str] = mapped_column(String(200), default="aliasarr")
    message: Mapped[str] = mapped_column(Text, default="")


class ReleaseLog(Base):
    """Журнал логики обработки релизов (поиск, сопоставление, парсинг, фильтрация, захват, загрузка, постобработка)."""

    __tablename__ = "release_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow, index=True)
    stage: Mapped[str] = mapped_column(String(50), default="search", index=True)  # search | match | filter | grab | download | import | error
    level: Mapped[str] = mapped_column(String(20), default="info", index=True)   # info | success | warning | error
    show_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    show_title: Mapped[Optional[str]] = mapped_column(String(300), nullable=True, index=True)
    release_title: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    indexer: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    message: Mapped[str] = mapped_column(Text, default="")
    details: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)


class AuditLog(Base):
    """Журнал аудита действий пользователей (входы, смены паролей, удаление/добавление шоу, настройки)."""

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow, index=True)
    user_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    username: Mapped[str] = mapped_column(String(100), default="system")
    action: Mapped[str] = mapped_column(String(100), index=True)
    description: Mapped[str] = mapped_column(String(1000), default="")
    details: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    ip_address: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)


class Session(Base):
    """Серверная сессия для браузерного логина."""

    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    token: Mapped[str] = mapped_column(String(200), unique=True, nullable=False, index=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow)
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime, nullable=False)
    ip_address: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    user: Mapped[Optional["User"]] = relationship(back_populates="sessions")


class Blocklist(Base):
    """Таблица заблокированных релизов (Черный список).
    
    Хранит информацию о релизах, которые были отклонены (например, фальшивые паки, битые торренты,
    или заблокированные вручную).
    При удалении тайтла записи сохраняются (show_id -> NULL, но tmdb_id, imdb_id и show_title остаются).
    При повторном добавлении тайтла записи автоматически привязываются обратно.
    """

    __tablename__ = "blocklist"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    show_id: Mapped[Optional[int]] = mapped_column(ForeignKey("shows.id", ondelete="SET NULL"), nullable=True, index=True)
    show_title: Mapped[Optional[str]] = mapped_column(String(500), nullable=True, index=True)
    tmdb_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    imdb_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)
    torrent_hash: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    guid: Mapped[Optional[str]] = mapped_column(String(500), nullable=True, index=True)
    page_url: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    download_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    release_title: Mapped[str] = mapped_column(String(1000), nullable=False, index=True)
    indexer: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    reason: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    quality: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    size: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow, index=True)

    show: Mapped[Optional["Show"]] = relationship("Show", back_populates="blocklist_entries")


# Alias for backward-compatibility and alternative naming
BlocklistEntry = Blocklist

