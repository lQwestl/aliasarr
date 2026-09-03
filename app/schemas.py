from __future__ import annotations

import datetime as dt
from typing import Optional

from pydantic import BaseModel, ConfigDict


class AliasCreate(BaseModel):
    text: str
    language: str = "ru"
    source: str = "manual"
    priority: Optional[int] = None  # если не задан — назначается автоматически (в конец очереди)


class AliasOut(AliasCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int
    show_id: int
    priority: int = 1


class AliasUpdate(BaseModel):
    text: Optional[str] = None
    language: Optional[str] = None
    priority: Optional[int] = None


class DeleteContentPayload(BaseModel):
    delete_mode: str = "show"  # "show" | "seasons" | "episodes"
    delete_files: bool = True
    season_numbers: list[int] = []
    episode_ids: list[int] = []
    reset_to_wanted: bool = True


class DeleteContentResponse(BaseModel):
    success: bool = True
    delete_mode: str
    deleted_files_count: int = 0
    episodes_affected_count: int = 0
    message: str = ""


class ShowCreate(BaseModel):
    title: str
    year: Optional[int] = None
    metadata_source: str = "tmdb"
    metadata_id: Optional[str] = None
    overview: Optional[str] = None
    poster_url: Optional[str] = None
    path: Optional[str] = None
    quality_profile_id: Optional[int] = None
    content_type: str = "series"  # movie | series | anime
    ova_mode: str = "auto"  # auto | season_1 | specials
    aliases: list[AliasCreate] = []


class ShowUpdate(BaseModel):
    title: Optional[str] = None
    path: Optional[str] = None
    overview: Optional[str] = None
    poster_url: Optional[str] = None
    quality_profile_id: Optional[int] = None
    monitored: Optional[bool] = None
    network: Optional[str] = None
    rating: Optional[float] = None
    country: Optional[str] = None
    genre: Optional[str] = None
    content_type: Optional[str] = None
    ova_mode: Optional[str] = None
    expected_year: Optional[int] = None
    expected_quarter: Optional[int] = None
    in_calendar: Optional[bool] = None


class ShowOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    title: str
    year: Optional[int] = None
    overview: Optional[str] = None
    poster_url: Optional[str] = None
    path: Optional[str] = None
    monitored: bool = True
    quality_profile_id: Optional[int] = None
    created_at: Optional[dt.datetime] = None
    last_search_at: Optional[dt.datetime] = None
    last_search_result: Optional[str] = None
    is_searching: bool = False
    network: Optional[str] = None
    rating: Optional[float] = None
    country: Optional[str] = None
    genre: Optional[str] = None
    content_type: str = "series"
    ova_mode: str = "auto"
    premiere_date: Optional[dt.datetime] = None
    expected_year: Optional[int] = None
    expected_quarter: Optional[int] = None
    in_calendar: bool = True
    # Вычисляемые поля для табличного вида библиотеки (п.9)
    seasons_count: int = 0
    episodes_count: int = 0
    downloaded_episodes_count: int = 0
    downloading_episodes_count: int = 0
    size_on_disk_bytes: int = 0
    next_airing: Optional[dt.datetime] = None
    aliases: list[AliasOut] = []


class EpisodeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    show_id: int
    season_number: int = 0
    episode_number: Optional[int] = 0
    absolute_number: Optional[int] = None
    title: Optional[str] = None
    air_date: Optional[dt.datetime] = None
    status: Optional[str] = "wanted"
    monitored: Optional[bool] = True
    download_progress: Optional[float] = 0.0
    torrent_hash: Optional[str] = None
    file_path: Optional[str] = None
    has_file: bool = False
    downloaded_quality: Optional[str] = None
    # MediaInfo и кастомные форматы
    video_codec: Optional[str] = None
    audio_codec: Optional[str] = None
    audio_channels: Optional[str] = None
    dynamic_range: Optional[str] = None
    release_group: Optional[str] = None
    languages: Optional[list[str]] = []
    custom_format_score: Optional[int] = 0
    file_size_bytes: Optional[int] = None


class CustomFormatCreate(BaseModel):
    name: str
    score: int = 0
    include_custom_format_when_renaming: bool = False
    is_builtin: bool = False
    specifications: list[dict] = []


class CustomFormatUpdate(BaseModel):
    name: Optional[str] = None
    score: Optional[int] = None
    include_custom_format_when_renaming: Optional[bool] = None
    is_builtin: Optional[bool] = None
    specifications: Optional[list[dict]] = None


class CustomFormatOut(CustomFormatCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int
    is_builtin: bool = False


class QualityProfileCreate(BaseModel):
    name: str
    allowed_qualities: list[str] = []
    min_size_mb: Optional[int] = None
    max_size_mb: Optional[int] = None
    upgrade_allowed: bool = True
    cutoff_quality: Optional[str] = None
    cutoff_score: int = 0
    format_items: list[dict] = []


class QualityProfileUpdate(BaseModel):
    name: Optional[str] = None
    allowed_qualities: Optional[list[str]] = None
    min_size_mb: Optional[int] = None
    max_size_mb: Optional[int] = None
    upgrade_allowed: Optional[bool] = None
    cutoff_quality: Optional[str] = None
    cutoff_score: Optional[int] = None
    format_items: Optional[list[dict]] = None


class QualityProfileOut(QualityProfileCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int


class IndexerCreate(BaseModel):
    name: str
    type: str = "torznab"
    base_url: str
    api_key: Optional[str] = None
    categories: list[int] = []
    priority: int = 25
    enabled: bool = True
    timeout_seconds: int = 30


class IndexerOut(IndexerCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int
    last_check_at: Optional[dt.datetime] = None
    last_check_ok: Optional[bool] = None
    consecutive_failures: int = 0


class SearchResultOut(BaseModel):
    """Результат поиска релиза с результатом матчинга, качеством, очками форматов и решением DecisionEngine."""
    title: str
    indexer: str
    guid: str
    download_url: Optional[str] = None
    page_url: Optional[str] = None
    seeders: int = 0
    size_bytes: int = 0
    matched: bool = False
    matched_alias: Optional[str] = None
    match_score: float = 0.0
    parsed_season: Optional[int] = None
    parsed_seasons: list[int] = []
    parsed_episodes: list[int] = []
    parsed_kind: str = "unknown"
    # Расширенные метаданные в стиле Sonarr InteractiveSearch
    quality: Optional[str] = None
    quality_rank: int = 0
    quality_details: Optional[dict] = None
    languages: list[str] = []
    release_group: Optional[str] = None
    custom_formats: list[dict] = []
    custom_format_score: int = 0
    approved: bool = True
    rejections: list[str] = []
    publish_date: Optional[str] = None
    age_days: Optional[float] = None


class RenamePreviewItem(BaseModel):
    episode_id: int
    season_number: int
    episode_number: int
    absolute_number: Optional[int] = None
    episode_title: Optional[str] = None
    existing_path: str
    existing_rel_path: str
    new_path: str
    new_rel_path: str
    needs_rename: bool


class RenamePreviewOut(BaseModel):
    show_id: int
    show_title: str
    show_path: str
    naming_template: str
    items: list[RenamePreviewItem] = []


class RenameExecuteRequest(BaseModel):
    episode_ids: list[int] = []


class RenameExecuteOut(BaseModel):
    success: bool = True
    renamed_count: int = 0
    errors: list[str] = []


class SpecialsImportStatusOut(BaseModel):
    has_pending_specials: bool = False
    pending_folder: Optional[str] = None
    pending_count: int = 0
    torrent_hash: Optional[str] = None

