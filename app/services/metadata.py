"""
Источники метаданных: TMDB (themoviedb.org) и TVMaze (tvmaze.com).

Единый интерфейс MetadataClient.search(query) -> list[MetadataResult]
и .get_details(external_id) -> MetadataShowDetails (имя, AKA, сезоны/серии, даты,
рейтинг, страна, жанр, тип контента, сеть, дата премьеры — для карточек библиотеки).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import datetime as dt
import logging
import os
import threading
import time
from typing import Optional, List, Dict, Any

try:
    from sqlalchemy.orm import Session
except ImportError:
    Session = Any  # type: ignore

# In-memory кеш для информации о коллекциях/сагах TMDb (24 часа)
_COLLECTION_DETAILS_CACHE: dict[str, tuple[float, dict]] = {}

logger = logging.getLogger("aliasarr.metadata")

try:
    import httpx
except ImportError:
    httpx = None  # type: ignore

try:
    from app.models.db import Alias, AliasLanguage, Episode, EpisodeStatus, MetadataSource, MetadataSourceType, Show, MovieCollection, AppSettings
except ImportError:
    class _DummyExpr:
        def __eq__(self, other): return self
        def __ne__(self, other): return self
        def is_(self, other): return self
        def isnot(self, other): return self
        def in_(self, other): return self
        def asc(self): return self
        def desc(self): return self

    class EpisodeStatus:  # type: ignore
        UNAIRED = "unaired"
        MISSING = "missing"
        WANTED = "wanted"
        DOWNLOADING = "downloading"
        DOWNLOADED = "downloaded"
        UPGRADING = "upgrading"
        IGNORED = "ignored"

    class AliasLanguage:  # type: ignore
        RU = "ru"
        EN = "en"

    class MetadataSourceType:  # type: ignore
        SKYHOOK = "skyhook"
        RADARR = "radarr"
        TMDB = "tmdb"
        TVMAZE = "tvmaze"
        THETVDB = "thetvdb"
        SHIKIMORI = "shikimori"
        ANILIST = "anilist"

    class Alias:  # type: ignore
        show_id = _DummyExpr()
        text = _DummyExpr()
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)

    class Episode:  # type: ignore
        show_id = _DummyExpr()
        season_number = _DummyExpr()
        episode_number = _DummyExpr()
        air_date = _DummyExpr()
        status = _DummyExpr()
        id = _DummyExpr()
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)

    class MetadataSource:  # type: ignore
        type = _DummyExpr()
        enabled = _DummyExpr()

    class Show:  # type: ignore
        metadata_id = _DummyExpr()
        metadata_source = _DummyExpr()
        content_type = _DummyExpr()
        id = _DummyExpr()

    class MovieCollection:  # type: ignore
        id = _DummyExpr()
        tmdb_collection_id = _DummyExpr()
        title = _DummyExpr()

    class AppSettings:  # type: ignore
        id = _DummyExpr()
        metadata_overview_language = "ru"


@dataclass
class MetadataResult:
    external_id: str
    title: str
    year: Optional[int]
    overview: Optional[str] = None
    poster_url: Optional[str] = None
    rating: Optional[float] = None
    country: Optional[str] = None
    genre: Optional[str] = None
    content_type: Optional[str] = None  # "series" | "movie"
    original_title: Optional[str] = None
    titles_by_lang: dict[str, str] = field(default_factory=dict)


@dataclass
class MetadataEpisode:
    season_number: int
    episode_number: int
    title: Optional[str] = None
    air_date: Optional[str] = None
    absolute_number: Optional[int] = None


@dataclass
class MetadataShowDetails:
    external_id: str
    title: str
    aliases: list[str] = field(default_factory=list)  # AKA / альтернативные названия
    overview: Optional[str] = None
    poster_url: Optional[str] = None
    episodes: list[MetadataEpisode] = field(default_factory=list)
    rating: Optional[float] = None
    country: Optional[str] = None
    genre: Optional[str] = None
    network: Optional[str] = None
    year: Optional[int] = None
    content_type: Optional[str] = None  # "series" | "movie"
    premiere_date: Optional[str] = None  # ISO-дата премьеры/выхода
    in_cinemas_date: Optional[str] = None
    digital_release_date: Optional[str] = None
    physical_release_date: Optional[str] = None
    edition: Optional[str] = None
    collection_tmdb_id: Optional[int] = None
    collection_name: Optional[str] = None
    collection_overview: Optional[str] = None
    original_title: Optional[str] = None
    titles_by_lang: dict[str, str] = field(default_factory=dict)
    collection_poster_url: Optional[str] = None
    collection_backdrop_url: Optional[str] = None
    collection_order: Optional[int] = None
    imdb_id: Optional[str] = None
    tmdb_id: Optional[int] = None
    tvdb_id: Optional[int] = None
    tvmaze_id: Optional[int] = None
    mal_id: Optional[int] = None
    anilist_id: Optional[int] = None
    anidb_id: Optional[int] = None
    shikimori_id: Optional[str] = None
    trailer_url: Optional[str] = None

    def __post_init__(self):
        if self.episodes:
            deduped: list[MetadataEpisode] = []
            seen: dict[tuple[int, int], int] = {}
            for ep in self.episodes:
                if not isinstance(ep, MetadataEpisode) or ep.episode_number is None:
                    continue
                try:
                    s_num = int(ep.season_number) if ep.season_number is not None else 1
                    e_num = int(ep.episode_number)
                except (ValueError, TypeError):
                    continue
                k = (s_num, e_num)
                if k in seen:
                    existing = deduped[seen[k]]
                    if not existing.title and ep.title:
                        existing.title = ep.title
                    if not existing.air_date and ep.air_date:
                        existing.air_date = ep.air_date
                    if existing.absolute_number is None and ep.absolute_number is not None:
                        existing.absolute_number = ep.absolute_number
                    continue
                seen[k] = len(deduped)
                deduped.append(ep)
            self.episodes = deduped


import re

_NON_LATIN_CHAR_RE = re.compile(
    r'[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uff66-\uff9f\uac00-\ud7af\u0400-\u04ff\u0600-\u06ff\u0590-\u05ff\u0370-\u03ff\u0e00-\u0e7f]'
)


def has_non_latin_script(text: str) -> bool:
    """True если строка содержит иероглифы (CJK), кириллицу, арабский, корейский, японский и др."""
    if not text:
        return False
    return bool(_NON_LATIN_CHAR_RE.search(str(text)))


def is_latin_text(text: str) -> bool:
    """True если строка состоит из латиницы/ASCII без CJK/кириллицы."""
    if not text or not str(text).strip():
        return False
    return not has_non_latin_script(str(text))


COUNTRY_TO_LANG_MAP: dict[str, str] = {
    "US": "en", "GB": "en", "CA": "en", "AU": "en", "NZ": "en", "IE": "en",
    "RU": "ru", "SU": "ru", "BY": "ru", "KZ": "ru", "UA": "uk",
    "JP": "ja", "KR": "ko", "CN": "zh", "TW": "zh", "HK": "zh",
    "FR": "fr", "DE": "de", "IT": "it", "ES": "es", "PT": "pt", "BR": "pt",
    "HU": "hu", "PL": "pl", "CZ": "cs", "TR": "tr", "AZ": "az", "ID": "id",
    "NL": "nl", "SE": "sv", "NO": "no", "DK": "da", "FI": "fi", "GR": "el",
    "IL": "he", "IN": "hi", "TH": "th", "VN": "vi", "AR": "es", "MX": "es",
    "CL": "es", "CO": "es", "PE": "es", "RO": "ro", "BG": "bg", "RS": "sr",
}

# Стандартные 2- и 3-буквенные ISO-коды языков (ISO 639-1 / 639-2 / 639-3) и их словесные названия.
# Языковые коды имеют абсолютный приоритет над кодами стран ISO-3166
# (например: 'uk' — украинский язык, а не UK/Великобритания; 'ar' — арабский язык, а не AR/Аргентина).
LANGUAGE_CODE_NORM_MAP: dict[str, str] = {
    # 2-буквенные ISO 639-1
    "en": "en", "ru": "ru", "uk": "uk", "ja": "ja", "ko": "ko", "zh": "zh",
    "fr": "fr", "de": "de", "it": "it", "es": "es", "pt": "pt", "hu": "hu",
    "pl": "pl", "cs": "cs", "tr": "tr", "az": "az", "id": "id", "nl": "nl",
    "sv": "sv", "no": "no", "da": "da", "fi": "fi", "el": "el", "he": "he",
    "hi": "hi", "th": "th", "vi": "vi", "ar": "ar", "ro": "ro", "bg": "bg",
    "sr": "sr", "hr": "hr", "sk": "sk", "sl": "sl", "et": "et", "lv": "lv",
    "lt": "lt", "fa": "fa", "ka": "ka", "hy": "hy", "be": "be", "kk": "kk",
    "uz": "uz",
    # 3-буквенные ISO 639-2 / 639-3
    "eng": "en", "rus": "ru", "ukr": "uk", "jpn": "ja", "kor": "ko", "zho": "zh", "chi": "zh",
    "fra": "fr", "fre": "fr", "deu": "de", "ger": "de", "ita": "it", "spa": "es",
    "por": "pt", "hun": "hu", "pol": "pl", "ces": "cs", "cze": "cs", "tur": "tr",
    "aze": "az", "ind": "id", "nld": "nl", "dut": "nl", "swe": "sv", "nor": "no",
    "dan": "da", "fin": "fi", "ell": "el", "gre": "el", "heb": "he", "hin": "hi",
    "tha": "th", "vie": "vi", "ara": "ar", "ron": "ro", "rum": "ro", "bul": "bg",
    "srp": "sr", "hrv": "hr", "slk": "sk", "slo": "sk", "slv": "sl", "est": "et",
    "lav": "lv", "lit": "lt", "fas": "fa", "per": "fa", "kat": "ka", "geo": "ka",
    "hye": "hy", "arm": "hy", "bel": "be", "kaz": "kk", "uzb": "uz",
    # Английские названия языков
    "english": "en", "russian": "ru", "ukrainian": "uk", "japanese": "ja", "korean": "ko",
    "chinese": "zh", "french": "fr", "german": "de", "italian": "it", "spanish": "es",
    "portuguese": "pt", "hungarian": "hu", "polish": "pl", "czech": "cs", "turkish": "tr",
    "azerbaijani": "az", "indonesian": "id", "dutch": "nl", "swedish": "sv", "norwegian": "no",
    "danish": "da", "finnish": "fi", "greek": "el", "hebrew": "he", "hindi": "hi",
    "thai": "th", "vietnamese": "vi", "arabic": "ar", "romanian": "ro", "bulgarian": "bg",
    "serbian": "sr", "croatian": "hr", "slovak": "sk", "slovenian": "sl", "estonian": "et",
    "latvian": "lv", "lithuanian": "lt", "persian": "fa", "georgian": "ka", "armenian": "hy",
    "belarusian": "be", "kazakh": "kk", "uzbek": "uz",
}

LANGUAGE_NAME_TO_CODE = LANGUAGE_CODE_NORM_MAP


def normalize_metadata_lang_code(raw_val: Any) -> str:
    """Приводит код страны, название языка или ISO-код к единому 2-буквенному ISO-639-1 коду языка."""
    if not raw_val:
        return ""
    if isinstance(raw_val, dict):
        if raw_val.get("iso_639_1") or raw_val.get("language"):
            raw_val = raw_val.get("iso_639_1") or raw_val.get("language")
        else:
            raw_val = raw_val.get("iso_3166_1") or raw_val.get("country") or raw_val.get("code") or raw_val.get("name") or ""
    raw_str = str(raw_val).strip()
    if not raw_str:
        return ""

    # 1. Если передана 2-буквенная заглавная страна (ISO 3166-1, e.g. "US", "RU", "UA", "GB", "AR", "MX")
    # исключая ошибочный псевдокод "UK", который в языковых метаданных является украинским языком uk
    if len(raw_str) == 2 and raw_str.isupper() and raw_str != "UK":
        if raw_str in COUNTRY_TO_LANG_MAP:
            return COUNTRY_TO_LANG_MAP[raw_str]

    s = raw_str.lower().split("-")[0].split("_")[0]
    if not s:
        return ""

    # 2. Проверяем языковые коды и названия языков (ISO 639-1 / 639-2 / 639-3)
    if s in LANGUAGE_CODE_NORM_MAP:
        return LANGUAGE_CODE_NORM_MAP[s]

    # 3. Резервный поиск по странам
    upper_c = s.upper()
    if upper_c != "UK" and upper_c in COUNTRY_TO_LANG_MAP:
        return COUNTRY_TO_LANG_MAP[upper_c]

    return s


LANGUAGE_SPECIFIC_CHARS: list[tuple[set[str], set[str]]] = [
    ({"de", "deu", "german"}, set("ß")),
    ({"es", "spa", "spanish"}, set("ñÑ¿¡")),
    ({"pl", "pol", "polish"}, set("łŁąĄęĘżŻźŹ")),
    ({"hu", "hun", "hungarian"}, set("őŐűŰ")),
    ({"cs", "ces", "cze", "czech", "sk", "slk", "slovak"}, set("řŘůŮěĚďť")),
    ({"tr", "tur", "turkish", "az", "aze"}, set("ğĞşŞı")),
    ({"ro", "ron", "romanian"}, set("șȘțȚăĂ")),
]


def detect_alias_language(text: str, default: str = "en") -> str:
    """Определяет код языка для алиаса по символам и алфавиту."""
    if not text:
        return default
    t = str(text).strip()
    # Cyrillic -> ru
    if any('\u0400' <= c <= '\u04ff' for c in t):
        return "ru"
    # Japanese (Hiragana / Katakana) -> ja
    if any(('\u3040' <= c <= '\u309f') or ('\u30a0' <= c <= '\u30ff') for c in t):
        return "ja"
    # Korean (Hangul) -> ko
    if any('\uac00' <= c <= '\ud7af' for c in t):
        return "ko"
    # Chinese (Kanji/Hanzi without Kana) -> zh
    if any('\u4e00' <= c <= '\u9fff' for c in t):
        return "zh"
    # Arabic -> ar
    if any('\u0600' <= c <= '\u06ff' for c in t):
        return "ar"
    # German ß -> de
    if any(c in "ß" for c in t):
        return "de"
    # Spanish ñ -> es
    if any(c in "ñÑ¿¡" for c in t):
        return "es"
    # Polish -> pl
    if any(c in "łŁąĄęĘżŻźŹ" for c in t):
        return "pl"
    # Hungarian -> hu
    if any(c in "őŐűŰ" for c in t):
        return "hu"
    # Czech/Slovak -> cs
    if any(c in "řŘůŮěĚ" for c in t):
        return "cs"
    # Turkish -> tr
    if any(c in "ğĞşŞı" for c in t):
        return "tr"
    # Romanian -> ro
    if any(c in "șȘțȚăĂ" for c in t):
        return "ro"
    return default


def is_alias_allowed(
    title: str,
    iso_or_lang: Any,
    allowed_langs: set[str],
    original_lang: Optional[str] = None,
) -> bool:
    """
    Проверяет, разрешено ли добавление альтернативного названия согласно списку языков пользователя.
    allowed_langs: множество разрешенных кодов языков (например, {'en', 'eng', 'ru', 'rus'}).
    """
    if not title or not str(title).strip():
        return False

    t_clean = str(title).strip()
    norm_lang = normalize_metadata_lang_code(iso_or_lang)

    # 1. Если язык явно указан в источнике (например 'zh', 'ko', 'ja', 'it', 'de')
    if norm_lang:
        # Если язык явно не входит в разрешенные и не является разрешенным оригинальным языком тайтла -> отклоняем
        is_orig_allowed = bool(original_lang and norm_lang == original_lang and original_lang in allowed_langs)
        if norm_lang not in allowed_langs and not is_orig_allowed:
            return False

    # 2. Проверка специфических символов алфавитов
    # Кириллица: допустима ТОЛЬКО если разрешен русский/украинский/белорусский
    if any('\u0400' <= c <= '\u04ff' for c in t_clean):
        return bool(allowed_langs.intersection({"ru", "rus", "russian", "uk", "ukr", "be"}))

    # Корейский алфавит (Hangul)
    has_hangul = any(
        ('\uac00' <= c <= '\ud7af') or
        ('\u1100' <= c <= '\u11ff') or
        ('\u3130' <= c <= '\u318f')
        for c in t_clean
    )
    if has_hangul:
        return bool(allowed_langs.intersection({"ko", "kor", "korean"}))

    # Японская слоговая азбука (Hiragana / Katakana)
    has_kana = any(
        ('\u3040' <= c <= '\u309f') or
        ('\u30a0' <= c <= '\u30ff')
        for c in t_clean
    )
    if has_kana:
        return bool(allowed_langs.intersection({"ja", "jp", "jpn", "japanese"}))

    # Китайские иероглифы (Hanzi) / Японские иероглифы (Kanji без каны)
    has_han = any('\u4e00' <= c <= '\u9fff' for c in t_clean)
    if has_han:
        # Если язык явно помечен как японский, проверяем японский
        if norm_lang in ("ja", "jp", "jpn", "japanese"):
            return bool(allowed_langs.intersection({"ja", "jp", "jpn", "japanese"}))
        # Иначе для иероглифов требуется китайский язык
        if bool(allowed_langs.intersection({"zh", "zho", "chi", "chinese"})):
            return True
        # Если китайский не разрешен, но разрешен японский и текст японского происхождения
        if bool(allowed_langs.intersection({"ja", "jp", "jpn", "japanese"})) and norm_lang in ("ja", "jp", "jpn", "japanese"):
            return True
        return False

    # Арабская вязь
    if any('\u0600' <= c <= '\u06ff' for c in t_clean):
        return bool(allowed_langs.intersection({"ar", "ara", "arabic"}))

    # Специфические символы европейских языков (не встречающиеся в стандартных английских словах)
    for lang_set, char_set in LANGUAGE_SPECIFIC_CHARS:
        if any(c in char_set for c in t_clean):
            if not allowed_langs.intersection(lang_set):
                return False

    # 3. Если язык был явно указан и прошел проверку
    if norm_lang:
        return norm_lang in allowed_langs or bool(original_lang and norm_lang == original_lang and original_lang in allowed_langs)

    # 4. Латиница и цифры без указания конкретного языка (считаем допустимым для английского/оригинала)
    if is_latin_text(t_clean) and bool(allowed_langs.intersection({"en", "eng", "english"})):
        return True

    return False


def get_allowed_metadata_languages(db=None, show=None) -> set[str]:
    """
    Возвращает множество кодов разрешенных языков для алиасов на основе
    настроек источника метаданных (field_mapping['alias_languages']) и дефолтных источников.
    Всегда включает базовый английский ('en', 'eng').
    Фильмы строго привязываются к провайдеру фильмов (Radarr SkyHook).
    """
    try:
        from app.models.db import MetadataSource, MetadataSourceType
    except (ImportError, Exception):
        MetadataSource = None
        MetadataSourceType = None

    custom_langs: set[str] = set()
    source = None
    if db and MetadataSource:
        try:
            content_type = getattr(show, "content_type", None) if show else None
            is_movie = content_type == "movie"
            is_anime = content_type == "anime"

            # 1. Приоритетный подбор источника по категории контента
            if is_movie:
                # Фильмы всегда берут настройки из провайдера фильмов Radarr SkyHook
                radarr_type = getattr(MetadataSourceType, "RADARR", "radarr")
                source = (
                    db.query(MetadataSource)
                    .filter(
                        MetadataSource.type.in_([radarr_type, "radarr"]),
                        MetadataSource.enabled == True,
                    )
                    .first()
                )
                if not source:
                    source = (
                        db.query(MetadataSource)
                        .filter(
                            MetadataSource.type.in_([radarr_type, "radarr", getattr(MetadataSourceType, "TMDB", "tmdb"), "tmdb"]),
                            MetadataSource.enabled == True,
                        )
                        .first()
                    )
            elif is_anime:
                # Аниме: специализированные источники (Shikimori, AniList) либо SkyHook
                if show and getattr(show, "metadata_source", None) in ("shikimori", "anilist", "skyhook"):
                    source = (
                        db.query(MetadataSource)
                        .filter(MetadataSource.type == show.metadata_source, MetadataSource.enabled == True)
                        .first()
                    )
                if not source:
                    skyhook_type = getattr(MetadataSourceType, "SKYHOOK", "skyhook")
                    source = (
                        db.query(MetadataSource)
                        .filter(
                            MetadataSource.type.in_([skyhook_type, "skyhook"]),
                            MetadataSource.enabled == True,
                        )
                        .first()
                    )
            elif show and getattr(show, "metadata_source", None):
                # Сериалы или тайтлы с явно заданным валидным источником
                source = (
                    db.query(MetadataSource)
                    .filter(MetadataSource.type == show.metadata_source, MetadataSource.enabled == True)
                    .first()
                )

            # 2. Резервный подбор источника
            if not source:
                if is_movie:
                    source = (
                        db.query(MetadataSource)
                        .filter(
                            MetadataSource.type.in_(["radarr", "tmdb"]),
                            MetadataSource.enabled == True,
                        )
                        .first()
                    )
                else:
                    source = (
                        db.query(MetadataSource)
                        .filter(
                            MetadataSource.type.in_(["skyhook", "thetvdb", "tvmaze"]),
                            MetadataSource.enabled == True,
                        )
                        .first()
                    )

            if not source:
                for s in db.query(MetadataSource).filter(MetadataSource.enabled == True).all():
                    if is_movie and s.type not in ("radarr", getattr(MetadataSourceType, "RADARR", "radarr")):
                        continue
                    if isinstance(getattr(s, "field_mapping", None), dict) and s.field_mapping.get("alias_languages"):
                        source = s
                        break
        except Exception:
            source = None

    if source and isinstance(getattr(source, "field_mapping", None), dict) and source.field_mapping.get("alias_languages"):
        for l in source.field_mapping["alias_languages"]:
            if l:
                custom_langs.add(str(l).lower().strip())

    if not custom_langs:
        custom_langs = {"ru"}

    # Нормализуем и добавляем варианты (ru -> rus, en -> eng и т.п.)
    result = {"en", "eng"}
    for l in custom_langs:
        norm = normalize_metadata_lang_code(l)
        if norm:
            result.add(norm)
            if norm == "ru":
                result.add("rus")
            elif norm == "ja":
                result.add("jpn")
            elif norm == "zh":
                result.add("chi")
            elif norm == "ko":
                result.add("kor")
            elif norm == "de":
                result.add("deu")
            elif norm == "fr":
                result.add("fra")
            elif norm == "es":
                result.add("spa")
            elif norm == "it":
                result.add("ita")
            elif norm == "pl":
                result.add("pol")
    return result


from difflib import SequenceMatcher


def _safe_int_year(val: Any) -> Optional[int]:
    if val is None or isinstance(val, bool):
        return None
    if hasattr(val, "_mock_return_value") or hasattr(val, "_mock_wraps"):
        return None
    if isinstance(val, int):
        return val
    if isinstance(val, str) and val.strip().isdigit():
        return int(val.strip())
    try:
        if isinstance(val, float):
            return int(val)
    except Exception:
        pass
    return None


def _clean_metadata_title(title: str) -> str:
    if not title:
        return ""
    # Удаляем скобки с годом и служебные знаки
    cleaned = re.sub(r"\s*\(\d{4}\)$|\s+\d{4}$", "", str(title))
    cleaned = re.sub(r"[^\w\s\d]+", " ", cleaned.lower())
    return re.sub(r"\s+", " ", cleaned).strip()


def calc_metadata_match_score(
    candidate: Any,
    target_title: str,
    target_year: Optional[int] = None,
    target_aliases: Optional[list[str]] = None,
) -> float:
    """
    Вычисляет уверенность сопоставления метаданных (0.0 .. 1.0).
    Учитывает сходство названий (основного и алиасов) и штрафует за несовпадение года.
    """
    if not candidate:
        return 0.0

    raw_cand_title = getattr(candidate, "title", None)
    cand_title = str(raw_cand_title) if raw_cand_title and not hasattr(raw_cand_title, "_mock_return_value") else ""
    cand_aliases = getattr(candidate, "aliases", None)
    if not isinstance(cand_aliases, (list, tuple, set)):
        cand_aliases = []

    t_year = _safe_int_year(target_year)
    c_year = _safe_int_year(getattr(candidate, "year", None))

    all_cand_titles = [cand_title] + [str(a) for a in cand_aliases if a and not hasattr(a, "_mock_return_value")]
    target_aliases_list = target_aliases if isinstance(target_aliases, (list, tuple, set)) else []
    all_target_titles = [str(target_title or "")] + [str(a) for a in target_aliases_list if a and not hasattr(a, "_mock_return_value")]

    clean_cand_titles = [_clean_metadata_title(t) for t in all_cand_titles if t]
    clean_target_titles = [_clean_metadata_title(t) for t in all_target_titles if t]

    if not clean_cand_titles or not clean_target_titles:
        return 0.0

    best_sim = 0.0
    for ct in clean_cand_titles:
        for tt in clean_target_titles:
            if not ct or not tt:
                continue
            if ct == tt:
                sim = 1.0
            elif ct in tt or tt in ct:
                ratio = len(min(ct, tt, key=len)) / max(1, len(max(ct, tt, key=len)))
                sim = max(0.85, ratio)
            else:
                sim = SequenceMatcher(None, ct, tt).ratio()
            if sim > best_sim:
                best_sim = sim

    # Проверка года
    if t_year is not None and c_year is not None:
        year_diff = abs(t_year - c_year)
        if year_diff == 0:
            best_sim = min(1.0, best_sim + 0.05)
        elif year_diff == 1:
            pass
        elif year_diff <= 3:
            best_sim -= 0.20
        else:
            best_sim -= 0.45

    return max(0.0, min(1.0, best_sim))


def select_overview(
    overviews_by_lang: dict[str, Optional[str]],
    original_overview: Optional[str] = None,
    preferred_lang: str = "ru",
) -> Optional[str]:
    """
    Выбирает наилучший синопсис (overview) на основе предпочтительного языка пользователя
    с цепочкой надежных фоллбэков.
    preferred_lang:
      - 'original' -> original_overview -> en -> ru -> любой
      - 'ru' -> ru -> original_overview -> en -> любой
      - 'en' -> en -> original_overview -> ru -> любой
      - '<other>' -> <other> -> en -> original_overview -> ru -> любой
    """
    clean_dict: dict[str, str] = {}
    for k, v in (overviews_by_lang or {}).items():
        if k and v and str(v).strip():
            clean_dict[str(k).strip().lower()] = str(v).strip()

    orig = str(original_overview).strip() if original_overview and str(original_overview).strip() else None
    pref = (preferred_lang or "ru").strip().lower()

    if pref == "original":
        candidates = [orig, clean_dict.get("en"), clean_dict.get("eng"), clean_dict.get("ru"), clean_dict.get("rus")]
        for c in candidates:
            if c:
                return c
        return next(iter(clean_dict.values()), None)

    norm_pref = normalize_metadata_lang_code(pref) or pref

    # Ищем совпадение с предпочитаемым языком (по коду или нормализации)
    pref_overview = clean_dict.get(norm_pref) or clean_dict.get(pref)
    if not pref_overview:
        for k, v in clean_dict.items():
            if normalize_metadata_lang_code(k) == norm_pref:
                pref_overview = v
                break

    if pref_overview:
        return pref_overview

    en_overview = clean_dict.get("en") or clean_dict.get("eng")
    ru_overview = clean_dict.get("ru") or clean_dict.get("rus")

    if norm_pref in ("ru", "rus"):
        candidates = [orig, en_overview]
    elif norm_pref in ("en", "eng"):
        candidates = [orig, ru_overview]
    else:
        candidates = [en_overview, orig, ru_overview]

    for c in candidates:
        if c:
            return c

    return next(iter(clean_dict.values()), None)


class BaseMetadataClient:
    async def search(self, query: str) -> list[MetadataResult]:
        raise NotImplementedError

    async def get_details(self, external_id: str) -> MetadataShowDetails:
        raise NotImplementedError

class TMDBClient(BaseMetadataClient):
    """
    TMDB (The Movie Database) — themoviedb.org.

    Аутентификация: Bearer-токен (Read Access Token из личного кабинета TMDB:
    themoviedb.org → Settings → API → Read Access Token (длинная строка eyJ...).
    Вставлять именно Read Access Token, а не короткий API Key v3.

    Поиск: /search/multi → фильмы и сериалы одновременно.
    Детали: /tv/{id} + /tv/{id}/season/{n} для каждого сезона.
    Изображения: https://image.tmdb.org/t/p/w500/{poster_path}.
    """

    BASE_URL = "https://api.themoviedb.org/3"
    IMAGE_BASE = "https://image.tmdb.org/t/p/w500"
    DEFAULT_TOKEN = "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJhdWQiOiIxYTczNzMzMDE5NjFkMDNmOTdmODUzYTg3NmRkMTIxMiIsInN1YiI6IjU4NjRmNTkyYzNhMzY4MGFiNjAxNzUzNCIsInNjb3BlcyI6WyJhcGlfcmVhZCJdLCJ2ZXJzaW9uIjoxfQ.gh1BwogCCKOda6xj9FRMgAAj_RYKMMPC3oNlcBtlmwk"

    def __init__(
        self,
        api_key: str = "",
        alias_countries: Optional[list[str]] = None,
        alias_languages: Optional[list[str]] = None,
        overview_language: str = "ru",
        title_language: str = "ru",
    ):
        import os as _os
        self.api_key = (api_key or _os.getenv("TMDB_API_KEY", "") or self.DEFAULT_TOKEN).strip()
        langs = []
        if alias_languages:
            langs = [l.lower() for l in alias_languages if l and l.lower() != "en"]
        elif alias_countries:
            langs = [c.lower() for c in alias_countries if c and c.lower() != "en"]
        if not langs:
            langs = ["ru"]
        self.alias_languages = langs
        self.alias_countries = [c.upper() for c in alias_countries] if alias_countries else None
        self.overview_language = (overview_language or "ru").strip().lower()
        self.title_language = (title_language or "ru").strip().lower()

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "accept": "application/json",
        }

    async def search(self, query: str) -> list[MetadataResult]:
        if not self.api_key:
            self.api_key = self.DEFAULT_TOKEN
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(
                f"{self.BASE_URL}/search/multi",
                params={"query": query, "language": "ru-RU", "include_adult": "false"},
                headers=self._headers(),
            )
            resp.raise_for_status()
            data = resp.json()

        results = []
        for item in data.get("results", []):
            media_type = item.get("media_type")
            if media_type not in ("movie", "tv"):
                continue
            title = item.get("title") or item.get("name") or ""
            orig_title = item.get("original_title") or item.get("original_name") or ""
            titles_by_lang: dict[str, str] = {}
            if title:
                if any('\u0400' <= c <= '\u04ff' for c in title):
                    titles_by_lang["ru"] = title
                elif is_latin_text(title):
                    titles_by_lang["en"] = title
            if orig_title:
                titles_by_lang["original"] = orig_title
                if "en" not in titles_by_lang and is_latin_text(orig_title):
                    titles_by_lang["en"] = orig_title
                elif "ru" not in titles_by_lang and any('\u0400' <= c <= '\u04ff' for c in orig_title):
                    titles_by_lang["ru"] = orig_title

            norm_t_pref = normalize_metadata_lang_code(self.title_language) or self.title_language
            display_title = title
            if norm_t_pref in ("en", "eng") and titles_by_lang.get("en"):
                display_title = titles_by_lang["en"]
            elif norm_t_pref in ("ru", "rus") and titles_by_lang.get("ru"):
                display_title = titles_by_lang["ru"]
            elif norm_t_pref in ("original", "orig") and orig_title:
                display_title = orig_title

            year = None
            date_str = item.get("release_date") or item.get("first_air_date") or ""
            if date_str and len(date_str) >= 4:
                try:
                    year = int(date_str[:4])
                except ValueError:
                    pass
            poster = item.get("poster_path")
            if poster:
                poster = f"{self.IMAGE_BASE}{poster}"
            results.append(MetadataResult(
                external_id=f"{media_type}:{item['id']}",
                title=display_title,
                year=year,
                overview=item.get("overview"),
                poster_url=poster,
                rating=item.get("vote_average"),
                country=None,
                genre=None,
                content_type="movie" if media_type == "movie" else "series",
                original_title=orig_title or None,
                titles_by_lang=titles_by_lang,
            ))
        return results

    async def get_details(self, external_id: str) -> MetadataShowDetails:
        """external_id: «tv:12345» или «movie:67890» или просто «12345» (TV по умолчанию)."""
        if ":" in external_id:
            media_type, tmdb_id = external_id.split(":", 1)
        else:
            media_type = "tv"
            tmdb_id = external_id

        if media_type == "movie":
            return await self._get_movie_details(tmdb_id)
        return await self._get_tv_details(tmdb_id)

    async def _get_movie_details(self, tmdb_id: str) -> MetadataShowDetails:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(
                f"{self.BASE_URL}/movie/{tmdb_id}",
                params={"language": "en-US", "append_to_response": "alternative_titles,translations,release_dates,external_ids,videos"},
                headers=self._headers(),
            )
            resp.raise_for_status()
            data = resp.json()

        allowed_langs = {"en", "eng"} | {l.lower() for l in (self.alias_languages or ["ru"])}

        # Для совместимости с Jellyfin название и папки должны быть на английском
        raw_title = data.get("title") or data.get("original_title") or ""
        aliases = []
        ru_title = None
        eng_trans_title = None
        extra_lang_titles = []

        # Извлекаем названия и описания из переводов TMDB строго для разрешенных языков
        overviews_by_lang: dict[str, str] = {}
        if data.get("overview") and str(data.get("overview")).strip():
            overviews_by_lang["en"] = str(data.get("overview")).strip()
        tr_raw = data.get("translations")
        tr_list = tr_raw.get("translations", []) if isinstance(tr_raw, dict) else (tr_raw if isinstance(tr_raw, list) else [])
        for tr in tr_list:
            if not isinstance(tr, dict):
                continue
            iso = normalize_metadata_lang_code(tr.get("iso_639_1") or tr.get("language") or "")
            tr_data = tr.get("data") if isinstance(tr.get("data"), dict) else tr
            t_t = tr_data.get("title")
            ov = tr_data.get("overview")
            if iso and ov and str(ov).strip():
                overviews_by_lang[iso] = str(ov).strip()
            if iso in ("ru", "rus", "russian"):
                ru_title = t_t or ru_title
            elif iso in ("en", "eng", "english"):
                eng_trans_title = t_t or eng_trans_title
            elif iso in allowed_langs and t_t and t_t.strip():
                extra_lang_titles.append(t_t.strip())

        orig_title_val = data.get("original_title") or ""
        orig_lang = data.get("original_language") or ""
        if not ru_title and (orig_lang == "ru" or any('\u0400' <= c <= '\u04ff' for c in orig_title_val)):
            ru_title = orig_title_val

        # Альтернативные названия
        alt_titles = []
        at_raw = data.get("alternative_titles") or data.get("alternativeTitles") or data.get("alternateTitles")
        at_list = at_raw.get("titles", []) if isinstance(at_raw, dict) else (at_raw if isinstance(at_raw, list) else [])
        for at in at_list:
            if isinstance(at, dict):
                t_name = at.get("title")
                iso = (at.get("iso_3166_1") or at.get("country") or at.get("language") or "").upper()
                if t_name:
                    alt_titles.append((t_name, iso))
            elif isinstance(at, str) and at.strip():
                alt_titles.append((at.strip(), ""))

        # Приоритет выбора английского названия для Jellyfin
        eng_candidates = []
        if eng_trans_title and is_latin_text(eng_trans_title):
            eng_candidates.append(eng_trans_title.strip())
        for t_name, iso in alt_titles:
            norm_l = normalize_metadata_lang_code(iso)
            if (iso in ("US", "GB", "CA", "AU", "NZ", "IE") or norm_l == "en") and is_latin_text(t_name):
                if t_name.strip() not in eng_candidates:
                    eng_candidates.append(t_name.strip())
            elif not norm_l and is_latin_text(t_name) and t_name.strip() not in eng_candidates:
                eng_candidates.append(t_name.strip())

        titles_by_lang: dict[str, str] = {}
        if ru_title:
            titles_by_lang["ru"] = ru_title
        if eng_candidates:
            titles_by_lang["en"] = eng_candidates[0]
        elif is_latin_text(raw_title):
            titles_by_lang["en"] = raw_title
        if orig_title_val:
            titles_by_lang["original"] = orig_title_val
        elif raw_title:
            titles_by_lang["original"] = raw_title

        if is_latin_text(raw_title):
            title = raw_title
        elif eng_candidates:
            title = eng_candidates[0]
        else:
            title = raw_title

        # Добавляем все альтернативные и разрешенные названия в алиасы
        orig_lang = data.get("original_language") or ""
        if raw_title and raw_title != title and raw_title not in aliases:
            aliases.append(raw_title)
        if ru_title and ru_title != title and ru_title not in aliases and ("ru" in allowed_langs or "rus" in allowed_langs):
            aliases.append(ru_title)
        for ext_t in extra_lang_titles:
            if ext_t != title and ext_t not in aliases:
                aliases.append(ext_t)
        for t_name, iso in alt_titles:
            if t_name != title and t_name not in aliases:
                # Включаем только если язык/страна входит в разрешенные
                if not is_alias_allowed(t_name, iso, allowed_langs, original_lang=orig_lang):
                    continue
                if self.alias_countries is not None and iso and iso not in self.alias_countries:
                    continue
                aliases.append(t_name)
                
        poster = data.get("poster_path")
        genres = [g["name"] for g in data.get("genres", [])]
        countries = [c["iso_3166_1"] for c in data.get("production_countries", [])]
        premiere = data.get("release_date") or None

        # Описание сюжета на основе предпочтительного языка с фоллбэками
        overview = select_overview(overviews_by_lang, data.get("overview"), self.overview_language)

        # Внешние идентификаторы и трейлер
        ext_ids = data.get("external_ids") or {}
        imdb_id_val = data.get("imdb_id") or ext_ids.get("imdb_id")
        tmdb_id_int = int(tmdb_id) if str(tmdb_id).isdigit() else None
        trailer_url_val = None
        for vid in (data.get("videos") or {}).get("results", []):
            if isinstance(vid, dict) and vid.get("site") == "YouTube" and vid.get("key"):
                trailer_url_val = f"https://www.youtube.com/watch?v={vid['key']}"
                if vid.get("type") == "Trailer":
                    break

        # Раздельные даты релиза (Radarr / TMDb Release Dates: Theatrical, Digital, Physical)
        in_cinemas_date = None
        digital_release_date = None
        physical_release_date = None
        rel_results = (data.get("release_dates") or {}).get("results", [])
        if isinstance(rel_results, list):
            cinemas_dates = []
            digital_dates = []
            physical_dates = []
            for country_obj in rel_results:
                if not isinstance(country_obj, dict):
                    continue
                for rd in country_obj.get("release_dates", []):
                    if not isinstance(rd, dict):
                        continue
                    rd_type = rd.get("type")
                    rd_date = str(rd.get("release_date") or "")[:10]
                    if not rd_date:
                        continue
                    if rd_type in (1, 2, 3):  # Premiere, Theatrical limited, Theatrical
                        cinemas_dates.append(rd_date)
                    elif rd_type == 4:  # Digital
                        digital_dates.append(rd_date)
                    elif rd_type == 5:  # Physical
                        physical_dates.append(rd_date)
            if cinemas_dates:
                in_cinemas_date = min(cinemas_dates)
            if digital_dates:
                digital_release_date = min(digital_dates)
            if physical_dates:
                physical_release_date = min(physical_dates)

        if not in_cinemas_date and premiere:
            in_cinemas_date = str(premiere)[:10]

        # Киноколлекция / Франшиза (TMDb Collection)
        coll_data = data.get("belongs_to_collection")
        coll_tmdb_id = None
        coll_name = None
        coll_poster_url = None
        coll_backdrop_url = None
        if isinstance(coll_data, dict):
            coll_tmdb_id = coll_data.get("id")
            coll_name = coll_data.get("name")
            cp = coll_data.get("poster_path")
            if cp:
                coll_poster_url = f"{self.IMAGE_BASE}{cp}"
            cb = coll_data.get("backdrop_path")
            if cb:
                coll_backdrop_url = f"{self.IMAGE_BASE}{cb}"

        return MetadataShowDetails(
            external_id=f"movie:{tmdb_id}",
            title=title,
            aliases=aliases,
            overview=overview,
            poster_url=f"{self.IMAGE_BASE}{poster}" if poster else None,
            episodes=[],
            rating=data.get("vote_average"),
            country=", ".join(countries) if countries else None,
            genre=", ".join(genres) if genres else None,
            content_type="movie",
            premiere_date=premiere,
            in_cinemas_date=in_cinemas_date,
            digital_release_date=digital_release_date,
            physical_release_date=physical_release_date,
            collection_tmdb_id=coll_tmdb_id,
            collection_name=coll_name,
            collection_poster_url=coll_poster_url,
            collection_backdrop_url=coll_backdrop_url,
            imdb_id=imdb_id_val,
            tmdb_id=tmdb_id_int,
            trailer_url=trailer_url_val,
            original_title=raw_title or None,
            titles_by_lang=titles_by_lang,
        )

    async def get_collection_details(
        self,
        tmdb_collection_id: int | str,
        lang: Optional[str] = None,
        bypass_cache: bool = False,
    ) -> dict:
        """Получить полный список фильмов киноколлекции/саги из TMDb API (с кешированием на 24ч и таймаутом 6с)."""
        chosen_lang = (lang or self.overview_language or "ru").strip().lower()
        norm_lang = normalize_metadata_lang_code(chosen_lang) or "ru"
        if norm_lang in ("ru", "rus"):
            target_lang = "ru-RU"
        elif norm_lang in ("en", "eng"):
            target_lang = "en-US"
        elif norm_lang == "original":
            target_lang = "en-US"
        elif len(norm_lang) == 2:
            target_lang = f"{norm_lang}-{norm_lang.upper()}"
        else:
            target_lang = norm_lang

        cache_key = f"{tmdb_collection_id}_{target_lang}"
        now = time.time()
        if not bypass_cache:
            cached = _COLLECTION_DETAILS_CACHE.get(cache_key)
            if cached and (now - cached[0]) < 86400:
                return cached[1]

        async with httpx.AsyncClient(timeout=6) as client:
            resp = await client.get(
                f"{self.BASE_URL}/collection/{tmdb_collection_id}",
                params={"language": target_lang},
                headers=self._headers(),
            )
            resp.raise_for_status()
            data = resp.json()

        # Fallback на английский язык, если целевой язык не en-US (для синопсиса и англоязычного названия)
        c_overview = (data.get("overview") or "").strip()
        fallback_data = None
        if target_lang != "en-US":
            try:
                async with httpx.AsyncClient(timeout=6) as client:
                    f_resp = await client.get(
                        f"{self.BASE_URL}/collection/{tmdb_collection_id}",
                        params={"language": "en-US"},
                        headers=self._headers(),
                    )
                    if f_resp.status_code == 200:
                        fallback_data = f_resp.json()
            except Exception as ex:
                logger.debug("TMDb collection fallback fetch failed: %s", ex)

        # Если целевой язык en-US, пробуем подтянуть русскую локализацию
        ru_data = None
        if target_lang == "en-US":
            try:
                async with httpx.AsyncClient(timeout=6) as client:
                    ru_resp = await client.get(
                        f"{self.BASE_URL}/collection/{tmdb_collection_id}",
                        params={"language": "ru-RU"},
                        headers=self._headers(),
                    )
                    if ru_resp.status_code == 200:
                        ru_data = ru_resp.json()
            except Exception as ex:
                logger.debug("TMDb collection RU fetch failed: %s", ex)

        # Сбор словаря названий на разных языках (RU, EN, translations)
        titles_by_lang: dict[str, str] = {}
        has_cyrillic = lambda s: any('\u0400' <= ch <= '\u04ff' for ch in (s or ""))
        orig_name = (data.get("name") or "").strip()
        orig_lang = (data.get("original_language") or "").strip().lower()

        if target_lang != "en-US":
            if orig_name:
                if norm_lang in ("ru", "rus"):
                    if has_cyrillic(orig_name):
                        titles_by_lang["ru"] = orig_name
                    elif orig_lang and orig_lang not in titles_by_lang:
                        titles_by_lang[orig_lang] = orig_name
                else:
                    titles_by_lang[norm_lang] = orig_name
            if fallback_data and fallback_data.get("name"):
                titles_by_lang["en"] = fallback_data.get("name").strip()
        else:
            if orig_name:
                titles_by_lang["en"] = orig_name
            if ru_data and ru_data.get("name"):
                ru_cand = ru_data.get("name").strip()
                if has_cyrillic(ru_cand):
                    titles_by_lang["ru"] = ru_cand
                elif orig_lang and orig_lang not in titles_by_lang:
                    titles_by_lang[orig_lang] = ru_cand

        # Дополнительно опрашиваем эндпоинт переводов TMDb для максимального охвата языков
        try:
            async with httpx.AsyncClient(timeout=6) as client:
                tr_resp = await client.get(
                    f"{self.BASE_URL}/collection/{tmdb_collection_id}/translations",
                    headers=self._headers(),
                )
                if tr_resp.status_code == 200:
                    for item in tr_resp.json().get("translations", []):
                        iso = (item.get("iso_639_1") or "").lower()
                        t_obj = item.get("data") or {}
                        t_title = t_obj.get("title") or t_obj.get("name")
                        if iso and t_title and t_title.strip():
                            clean_t = t_title.strip()
                            if iso == "ru":
                                if has_cyrillic(clean_t):
                                    titles_by_lang["ru"] = clean_t
                            elif iso not in titles_by_lang or not titles_by_lang[iso]:
                                titles_by_lang[iso] = clean_t
        except Exception as ex:
            logger.debug("TMDb collection translations fetch failed: %s", ex)

        fallback_parts_map = {}
        fallback_overview = None
        if fallback_data and isinstance(fallback_data, dict):
            fallback_overview = (fallback_data.get("overview") or "").strip() or None
            for fp in fallback_data.get("parts", []):
                if isinstance(fp, dict) and fp.get("id"):
                    fallback_parts_map[fp["id"]] = fp

        parts = []
        for p in data.get("parts", []):
            if not isinstance(p, dict):
                continue
            p_id = p.get("id")
            fb_part = fallback_parts_map.get(p_id) if fallback_parts_map else None

            p_title = p.get("title") or p.get("original_title") or (fb_part.get("title") if fb_part else None) or ""
            p_rel = p.get("release_date") or (fb_part.get("release_date") if fb_part else "") or ""
            p_year = int(p_rel[:4]) if p_rel and len(p_rel) >= 4 and p_rel[:4].isdigit() else None
            poster = p.get("poster_path") or (fb_part.get("poster_path") if fb_part else None)
            p_ov = (p.get("overview") or "").strip()
            if not p_ov and fb_part:
                p_ov = (fb_part.get("overview") or "").strip()

            parts.append({
                "tmdb_id": p_id,
                "title": p_title,
                "year": p_year,
                "release_date": p_rel[:10] if p_rel else None,
                "overview": p_ov or None,
                "poster_url": f"{self.IMAGE_BASE}{poster}" if poster else None,
                "rating": p.get("vote_average") or (fb_part.get("vote_average") if fb_part else None),
            })
        parts.sort(key=lambda x: x.get("release_date") or "9999")

        c_poster = data.get("poster_path") or (fallback_data.get("poster_path") if fallback_data else None)
        c_backdrop = data.get("backdrop_path") or (fallback_data.get("backdrop_path") if fallback_data else None)
        chosen_name = None
        if norm_lang in ("ru", "rus"):
            chosen_name = titles_by_lang.get("ru") or titles_by_lang.get("en") or (fallback_data.get("name") if fallback_data else None) or data.get("name")
        elif norm_lang in ("en", "eng"):
            chosen_name = titles_by_lang.get("en") or data.get("name") or (fallback_data.get("name") if fallback_data else None)
        else:
            chosen_name = titles_by_lang.get(norm_lang) or titles_by_lang.get("en") or data.get("name") or (fallback_data.get("name") if fallback_data else None)

        result = {
            "id": data.get("id"),
            "name": chosen_name or data.get("name") or (fallback_data.get("name") if fallback_data else None),
            "titles_by_lang": titles_by_lang,
            "overview": c_overview or fallback_overview,
            "poster_url": f"{self.IMAGE_BASE}{c_poster}" if c_poster else None,
            "backdrop_url": f"{self.IMAGE_BASE}{c_backdrop}" if c_backdrop else None,
            "parts": parts,
        }
        _COLLECTION_DETAILS_CACHE[cache_key] = (now, result)
        return result

    async def _get_tv_details(self, tmdb_id: str, fetch_episodes: bool = True) -> MetadataShowDetails:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"{self.BASE_URL}/tv/{tmdb_id}",
                params={"language": "en-US", "append_to_response": "alternative_titles,translations,external_ids,videos"},
                headers=self._headers(),
            )
            resp.raise_for_status()
            show_data = resp.json()

            # Английские названия эпизодов (для совместимости с Jellyfin)
            episodes: list[MetadataEpisode] = []
            if fetch_episodes:
                seasons_info = show_data.get("seasons") or []
                season_numbers = [s.get("season_number") for s in seasons_info if s.get("season_number") is not None]
                if not season_numbers:
                    season_count = show_data.get("number_of_seasons", 0)
                    season_numbers = list(range(1, season_count + 1))
                season_numbers = sorted(set(season_numbers))

                genres = [str(g.get("name", "")).lower() for g in (show_data.get("genres") or [])]
                countries = [(c or "").upper() for c in (show_data.get("origin_country") or [])]
                is_anime = ("anime" in genres or "animation" in genres) and ("JP" in countries or "JPN" in countries)

                running_abs = 1
                for snum in season_numbers:
                    try:
                        sr = await client.get(
                            f"{self.BASE_URL}/tv/{tmdb_id}/season/{snum}",
                            params={"language": "en-US"},
                            headers=self._headers(),
                        )
                        if sr.status_code != 200:
                            continue
                        for ep in sr.json().get("episodes", []):
                            ep_season = ep.get("season_number", snum)
                            ep_num = ep.get("episode_number", 0)
                            abs_num = None
                            if is_anime and ep_season > 0 and ep_num > 0:
                                abs_num = running_abs
                                running_abs += 1
                            episodes.append(MetadataEpisode(
                                season_number=ep_season,
                                episode_number=ep_num,
                                title=ep.get("name"),
                                air_date=ep.get("air_date"),
                                absolute_number=abs_num,
                            ))
                    except Exception as e:
                        logger.debug("Failed to fetch TMDb season %s for %s: %s", snum, tmdb_id, e)

        allowed_langs = {"en", "eng"} | {l.lower() for l in (self.alias_languages or ["ru"])}
        raw_title = show_data.get("name") or show_data.get("original_name") or ""
        aliases = []
        ru_title = None
        eng_trans_title = None
        extra_lang_titles = []
        # Извлекаем русское и английское название и описания из переводов TMDB
        overviews_by_lang: dict[str, str] = {}
        if show_data.get("overview") and str(show_data.get("overview")).strip():
            overviews_by_lang["en"] = str(show_data.get("overview")).strip()
        for tr in (show_data.get("translations") or {}).get("translations", []):
            if not isinstance(tr, dict):
                continue
            iso = normalize_metadata_lang_code(tr.get("iso_639_1") or tr.get("language") or "")
            tr_data = tr.get("data") if isinstance(tr.get("data"), dict) else tr
            t_t = tr_data.get("name") or tr_data.get("title")
            ov = tr_data.get("overview")
            if iso and ov and str(ov).strip():
                overviews_by_lang[iso] = str(ov).strip()
            if iso in ("ru", "rus", "russian"):
                ru_title = t_t or ru_title
            elif iso in ("en", "eng", "english"):
                eng_trans_title = t_t or eng_trans_title
            elif iso in allowed_langs and t_t and t_t.strip():
                extra_lang_titles.append(t_t.strip())

        orig_name = show_data.get("original_name") or ""
        orig_lang = show_data.get("original_language") or ""
        if not ru_title and (orig_lang == "ru" or any('\u0400' <= c <= '\u04ff' for c in orig_name)):
            ru_title = orig_name

        # Альтернативные названия
        alt_titles = []
        for at in (show_data.get("alternative_titles") or {}).get("results", []):
            t_name = at.get("title")
            if t_name:
                alt_titles.append((t_name, (at.get("iso_3166_1") or "").upper()))

        # Приоритет выбора английского названия для Jellyfin
        eng_candidates = []
        if eng_trans_title and is_latin_text(eng_trans_title):
            eng_candidates.append(eng_trans_title.strip())
        for t_name, iso in alt_titles:
            norm_l = normalize_metadata_lang_code(iso)
            if (iso in ("US", "GB", "CA", "AU", "NZ", "IE") or norm_l == "en") and is_latin_text(t_name):
                if t_name.strip() not in eng_candidates:
                    eng_candidates.append(t_name.strip())
            elif not norm_l and is_latin_text(t_name) and t_name.strip() not in eng_candidates:
                eng_candidates.append(t_name.strip())

        titles_by_lang: dict[str, str] = {}
        if ru_title:
            titles_by_lang["ru"] = ru_title
        if eng_candidates:
            titles_by_lang["en"] = eng_candidates[0]
        elif is_latin_text(raw_title):
            titles_by_lang["en"] = raw_title
        if orig_name:
            titles_by_lang["original"] = orig_name
        elif raw_title:
            titles_by_lang["original"] = raw_title

        if is_latin_text(raw_title):
            title = raw_title
        elif eng_candidates:
            title = eng_candidates[0]
        else:
            title = raw_title

        # Добавляем все альтернативные и нелатинские названия в алиасы
        if raw_title and raw_title != title and raw_title not in aliases:
            aliases.append(raw_title)
        if orig_name and orig_name != title and orig_name not in aliases:
            if is_alias_allowed(orig_name, orig_lang, allowed_langs, original_lang=orig_lang):
                aliases.append(orig_name)
        if ru_title and ru_title != title and ru_title not in aliases and ("ru" in allowed_langs or "rus" in allowed_langs):
            aliases.append(ru_title)
        for ext_t in extra_lang_titles:
            if ext_t != title and ext_t not in aliases:
                aliases.append(ext_t)
        for t_name, iso in alt_titles:
            if t_name != title and t_name not in aliases:
                if not is_alias_allowed(t_name, iso, allowed_langs, original_lang=orig_lang):
                    continue
                if self.alias_countries is not None and iso and iso not in self.alias_countries:
                    continue
                aliases.append(t_name)

        poster = show_data.get("poster_path")
        genres = [g["name"] for g in show_data.get("genres", [])]
        networks = [n["name"] for n in show_data.get("networks", [])]
        countries = show_data.get("origin_country", [])
        premiere = show_data.get("first_air_date") or None

        # Описание сюжета на основе предпочтительного языка с фоллбэками
        overview = select_overview(overviews_by_lang, show_data.get("overview"), self.overview_language)

        # Внешние идентификаторы и трейлер
        ext_ids = show_data.get("external_ids") or {}
        imdb_id_val = ext_ids.get("imdb_id")
        tvdb_id_raw = ext_ids.get("tvdb_id")
        tvdb_id_int = int(tvdb_id_raw) if str(tvdb_id_raw or "").isdigit() else None
        tvmaze_id_raw = ext_ids.get("tvmaze_id")
        tvmaze_id_int = int(tvmaze_id_raw) if str(tvmaze_id_raw or "").isdigit() else None
        tmdb_id_int = int(tmdb_id) if str(tmdb_id).isdigit() else None
        trailer_url_val = None
        for vid in (show_data.get("videos") or {}).get("results", []):
            if isinstance(vid, dict) and vid.get("site") == "YouTube" and vid.get("key"):
                trailer_url_val = f"https://www.youtube.com/watch?v={vid['key']}"
                if vid.get("type") == "Trailer":
                    break

        return MetadataShowDetails(
            external_id=f"tv:{tmdb_id}",
            title=title,
            aliases=aliases,
            overview=overview,
            poster_url=f"{self.IMAGE_BASE}{poster}" if poster else None,
            episodes=episodes,
            rating=show_data.get("vote_average"),
            country=", ".join(countries) if countries else None,
            genre=", ".join(genres) if genres else None,
            network=", ".join(networks) if networks else None,
            content_type="series",
            premiere_date=premiere,
            imdb_id=imdb_id_val,
            tmdb_id=tmdb_id_int,
            tvdb_id=tvdb_id_int,
            tvmaze_id=tvmaze_id_int,
            trailer_url=trailer_url_val,
            original_title=orig_name or None,
            titles_by_lang=titles_by_lang,
        )


class TVMazeClient(BaseMetadataClient):
    """
    TVMaze — tvmaze.com.

    Публичный API работает БЕЗ ключа (поиск шоу, эпизоды, расписание).
    Для Premium-функций (отслеживание, отметка просмотров) нужны
    username + API key из личного кабинета: tvmaze.com → My Profile → API Key.

    В данной интеграции используется только публичный API (метаданные, серии, AKA).
    api_key в настройках источника опционален — можно оставить пустым.
    """

    BASE_URL = "https://api.tvmaze.com"

    def __init__(self, api_key: str = "", alias_countries: Optional[list[str]] = None):
        # api_key хранится, но для публичного API не нужен.
        # Формат: «username:api_key» для Premium-авторизации (Basic Auth).
        self.api_key = (api_key or "").strip()
        self.alias_countries = [c.upper() for c in alias_countries] if alias_countries else None

    def _headers(self) -> dict:
        return {"Accept": "application/json"}

    def _auth(self):
        """Basic Auth для Premium-функций (user:key). None если ключ не задан."""
        if ":" in self.api_key:
            username, key = self.api_key.split(":", 1)
            return (username.strip(), key.strip())
        return None

    @staticmethod
    def _strip_html(text: Optional[str]) -> Optional[str]:
        """Убирает HTML-теги из текстовых полей TVMaze (summary обёрнут в <p>...)."""
        if not text:
            return None
        import re as _re
        return _re.sub(r"<[^>]+>", "", text).strip() or None

    async def search(self, query: str) -> list[MetadataResult]:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(
                f"{self.BASE_URL}/search/shows",
                params={"q": query},
                headers=self._headers(),
            )
            resp.raise_for_status()
            data = resp.json()

        results = []
        for item in data:
            show = item.get("show", {})
            year = None
            premiere = show.get("premiered") or ""
            if premiere and len(premiere) >= 4:
                try:
                    year = int(premiere[:4])
                except ValueError:
                    pass

            image = show.get("image") or {}
            poster = image.get("original") or image.get("medium")
            genres = show.get("genres", [])
            network = show.get("network") or show.get("webChannel") or {}
            country = (network.get("country") or {}).get("code")
            network_name = network.get("name")

            # TVMaze: Animation обычно аниме, Scripted — сериал
            show_type = (show.get("type") or "").lower()
            content_type = "anime" if "animation" in show_type else "series"

            results.append(MetadataResult(
                external_id=str(show.get("id")),
                title=show.get("name") or "",
                year=year,
                overview=self._strip_html(show.get("summary")),
                poster_url=poster,
                rating=(show.get("rating") or {}).get("average"),
                country=country,
                genre=", ".join(genres) if genres else None,
                content_type=content_type,
            ))
        return results

    async def get_details(self, external_id: str) -> MetadataShowDetails:
        if str(external_id).startswith("movie:"):
            raise ValueError(f"TVMaze не поддерживает фильмы (ID: {external_id})")
        clean_id = str(external_id).replace("tv:", "").strip()
        if not clean_id.isdigit():
            raise ValueError(f"Некорректный ID для TVMaze: {external_id}")

        async with httpx.AsyncClient(timeout=30) as client:
            # Основная информация о шоу
            resp = await client.get(
                f"{self.BASE_URL}/shows/{clean_id}",
                headers=self._headers(),
            )
            resp.raise_for_status()
            data = resp.json()

            # Все эпизоды (включая спешлы через specials=1)
            ep_resp = await client.get(
                f"{self.BASE_URL}/shows/{clean_id}/episodes",
                params={"specials": "1"},
                headers=self._headers(),
            )
            raw_episodes = ep_resp.json() if ep_resp.status_code == 200 else []

            # Альтернативные названия (AKA)
            aka_resp = await client.get(
                f"{self.BASE_URL}/shows/{clean_id}/akas",
                headers=self._headers(),
            )
            akas = aka_resp.json() if aka_resp.status_code == 200 else []

        episodes: list[MetadataEpisode] = []
        for ep in raw_episodes:
            # airstamp — ISO 8601 datetime, airdate — просто дата
            air_date = ep.get("airstamp") or ep.get("airdate") or None
            if air_date:
                air_date = str(air_date)[:10]  # Берём только дату YYYY-MM-DD
            episodes.append(MetadataEpisode(
                season_number=ep.get("season", 0),
                episode_number=ep.get("number") or 0,
                title=ep.get("name"),
                air_date=air_date,
            ))

        # AKA
        show_name = data.get("name") or ""
        aliases = []
        for aka in akas:
            name = aka.get("name")
            if name and name != show_name:
                aliases.append(name)

        image = data.get("image") or {}
        poster = image.get("original") or image.get("medium")
        genres = data.get("genres", [])
        network = data.get("network") or data.get("webChannel") or {}
        country = (network.get("country") or {}).get("code")
        network_name = network.get("name")
        premiere = data.get("premiered") or None

        show_type = (data.get("type") or "").lower()
        content_type = "anime" if "animation" in show_type else "series"

        externals = data.get("externals") or {}
        tvmaze_id_int = int(clean_id) if clean_id.isdigit() else None
        imdb_id_val = externals.get("imdb")
        tvdb_id_raw = externals.get("thetvdb")
        tvdb_id_val = int(tvdb_id_raw) if str(tvdb_id_raw or "").isdigit() else None

        return MetadataShowDetails(
            external_id=external_id,
            title=show_name,
            aliases=aliases,
            overview=self._strip_html(data.get("summary")),
            poster_url=poster,
            episodes=episodes,
            rating=(data.get("rating") or {}).get("average"),
            country=country,
            genre=", ".join(genres) if genres else None,
            network=network_name,
            content_type=content_type,
            premiere_date=premiere,
            imdb_id=imdb_id_val,
            tvdb_id=tvdb_id_val,
            tvmaze_id=tvmaze_id_int,
        )


def extract_skyhook_poster(images: list) -> Optional[str]:
    if not images or not isinstance(images, list):
        return None

    def _resolve_url(raw_url: str) -> Optional[str]:
        if not raw_url:
            return None
        raw_url = str(raw_url).strip()
        if raw_url.startswith("http://") or raw_url.startswith("https://"):
            return raw_url
        if raw_url.startswith("/"):
            if not raw_url.lower().startswith("/mediacover"):
                return f"https://image.tmdb.org/t/p/w500{raw_url}"
            return f"https://artworks.thetvdb.com{raw_url}"
        return f"https://artworks.thetvdb.com/{raw_url}"

    # 1. Поиск постера (case-insensitive)
    for img in images:
        if not isinstance(img, dict):
            continue
        c_type = (img.get("coverType") or img.get("cover_type") or img.get("type") or "").lower()
        if c_type in ("poster", "cover", "default"):
            raw_url = img.get("remoteUrl") or img.get("url")
            resolved = _resolve_url(raw_url)
            if resolved:
                return resolved

    # 2. Fallback на любое изображение (fanart, banner)
    for img in images:
        if not isinstance(img, dict):
            continue
        raw_url = img.get("remoteUrl") or img.get("url")
        resolved = _resolve_url(raw_url)
        if resolved:
            return resolved

    return None


class SkyHookClient(BaseMetadataClient):
    """
    SkyHook Proxy — официальный облачный сервис метаданных Sonarr (skyhook.sonarr.tv).
    Работает «из коробки» БЕЗ необходимости вводить API-ключи.
    Предоставляет данные TheTVDB, TMDB, AniList, MyAnimeList для сериалов и аниме.
    Для фильмов осуществляет поиск через Radarr Servarr Cloud / TMDB fallback.
    """

    BASE_URL = "https://skyhook.sonarr.tv/v1/tvdb"
    BACKUP_URL = "https://skyhook.servarr.com/v1/tvdb"
    RADARR_URL = "https://radarr.servarr.com/v1/api"
    TMDB_URL = "https://api.themoviedb.org/3"
    TMDB_TOKEN = "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJhdWQiOiIxYTczNzMzMDE5NjFkMDNmOTdmODUzYTg3NmRkMTIxMiIsInN1YiI6IjU4NjRmNTkyYzNhMzY4MGFiNjAxNzUzNCIsInNjb3BlcyI6WyJhcGlfcmVhZCJdLCJ2ZXJzaW9uIjoxfQ.gh1BwogCCKOda6xj9FRMgAAj_RYKMMPC3oNlcBtlmwk"

    def __init__(
        self,
        api_key: str = "",
        alias_countries: Optional[list[str]] = None,
        base_url: str = "",
        alias_languages: Optional[list[str]] = None,
        overview_language: str = "ru",
        title_language: str = "ru",
    ):
        self.base_url = (base_url or self.BASE_URL).rstrip("/")
        langs = []
        if alias_languages:
            langs = [l.lower() for l in alias_languages if l and l.lower() != "en"]
        elif alias_countries:
            langs = [c.lower() for c in alias_countries if c and c.lower() != "en"]
        if not langs:
            langs = ["ru"]
        self.alias_languages = langs
        self.alias_countries = [c.upper() for c in alias_countries] if alias_countries else None
        self.overview_language = (overview_language or "ru").strip().lower()
        self.title_language = (title_language or "ru").strip().lower()

    def _map_skyhook_item(
        self,
        item: dict,
        seen_ids: set[str],
        tmdb_map: dict[int, dict],
        tmdb_name_map: dict[str, dict],
    ) -> Optional[MetadataResult]:
        tvdb_id = item.get("tvdbId")
        if not tvdb_id:
            return None
        ext_id = f"tvdb:{tvdb_id}"
        if ext_id in seen_ids:
            return None
        seen_ids.add(ext_id)

        poster_url = extract_skyhook_poster(item.get("images", []))
        genres = item.get("genres", [])
        country = item.get("originalCountry")
        is_anime = ("Anime" in genres or "Animation" in genres) and (country in ("Japan", "JP", "JPN"))
        c_type = "anime" if is_anime else "series"
        rating_val = (item.get("rating") or {}).get("value")

        raw_title = item.get("title") or ""
        orig_title = item.get("originalTitle") or ""
        tmdb_id_item = item.get("tmdbId")

        # Поиск локализации в TMDb данных
        tmdb_match = None
        if tmdb_id_item and int(tmdb_id_item) in tmdb_map:
            tmdb_match = tmdb_map[int(tmdb_id_item)]
        elif raw_title.lower() in tmdb_name_map:
            tmdb_match = tmdb_name_map[raw_title.lower()]
        elif orig_title and orig_title.lower() in tmdb_name_map:
            tmdb_match = tmdb_name_map[orig_title.lower()]

        ru_title = None
        ru_overview = None
        if tmdb_match:
            t_n = tmdb_match.get("name")
            t_orig = tmdb_match.get("original_name")
            if t_n and (any('\u0400' <= c <= '\u04ff' for c in t_n) or not raw_title):
                ru_title = t_n
            elif t_orig and any('\u0400' <= c <= '\u04ff' for c in t_orig):
                ru_title = t_orig
            t_ov = tmdb_match.get("overview")
            if t_ov and str(t_ov).strip():
                ru_overview = str(t_ov).strip()
            if not orig_title and tmdb_match.get("original_name"):
                orig_title = tmdb_match.get("original_name")

        if not ru_title and orig_title and any('\u0400' <= c <= '\u04ff' for c in orig_title):
            ru_title = orig_title

        titles_by_lang: dict[str, str] = {}
        if raw_title:
            titles_by_lang["en"] = raw_title
        if ru_title:
            titles_by_lang["ru"] = ru_title
        if orig_title:
            titles_by_lang["original"] = orig_title

        norm_ov_pref = normalize_metadata_lang_code(self.overview_language) or self.overview_language
        norm_title_pref = normalize_metadata_lang_code(self.title_language) or self.title_language
        display_title = raw_title
        if norm_title_pref in ("ru", "rus") and ru_title:
            display_title = ru_title
        elif norm_title_pref in ("original", "orig") and orig_title:
            display_title = orig_title
        elif norm_title_pref in ("en", "eng") and raw_title:
            display_title = raw_title

        display_overview = ru_overview if (norm_ov_pref in ("ru", "rus") and ru_overview) else item.get("overview")

        return MetadataResult(
            external_id=ext_id,
            title=display_title,
            year=item.get("year"),
            overview=display_overview,
            poster_url=poster_url,
            rating=float(rating_val) if rating_val is not None else None,
            country=country,
            genre=", ".join(genres) if genres else None,
            content_type=c_type,
            original_title=orig_title or None,
            titles_by_lang=titles_by_lang,
        )

    async def search(self, query: str) -> list[MetadataResult]:
        if not query or not query.strip():
            return []

        clean_query = query.strip()
        results: list[MetadataResult] = []
        seen_ids: set[str] = set()

        if httpx is None:
            return results

        # 1. Поиск сериалов и аниме через официальный Sonarr Skyhook
        async with httpx.AsyncClient(timeout=25, headers={"User-Agent": "Aliasarr/1.0.0 (Sonarr SkyHook Proxy)"}) as client:
            norm_ov_lang = normalize_metadata_lang_code(self.overview_language) or self.overview_language
            needs_tmdb = norm_ov_lang in ("ru", "rus") or any('\u0400' <= c <= '\u04ff' for c in clean_query)

            tmdb_map: dict[int, dict] = {}
            tmdb_name_map: dict[str, dict] = {}

            skyhook_task = client.get(f"{self.base_url}/search/en/", params={"term": clean_query})
            tmdb_task = client.get(
                f"{self.TMDB_URL}/search/tv",
                params={"query": clean_query, "language": "ru-RU", "include_adult": "false"},
                headers={"Authorization": f"Bearer {self.TMDB_TOKEN}", "accept": "application/json"},
            ) if needs_tmdb else None

            resp = None
            if tmdb_task:
                gather_res = await asyncio.gather(skyhook_task, tmdb_task, return_exceptions=True)
                resp = gather_res[0] if not isinstance(gather_res[0], Exception) else None
                tmdb_resp = gather_res[1] if not isinstance(gather_res[1], Exception) else None
                if tmdb_resp and hasattr(tmdb_resp, "status_code") and tmdb_resp.status_code == 200:
                    try:
                        t_data = tmdb_resp.json()
                        t_results = t_data.get("results", []) if isinstance(t_data, dict) else (t_data if isinstance(t_data, list) else [])
                        for t_item in t_results:
                            if isinstance(t_item, dict):
                                tid = t_item.get("id") or t_item.get("tmdbId")
                                if tid:
                                    tmdb_map[int(tid)] = t_item
                                t_name = (t_item.get("name") or t_item.get("title") or "").strip().lower()
                                t_orig = (t_item.get("original_name") or t_item.get("originalTitle") or "").strip().lower()
                                if t_name:
                                    tmdb_name_map[t_name] = t_item
                                if t_orig:
                                    tmdb_name_map[t_orig] = t_item
                    except Exception:
                        pass
            else:
                try:
                    resp = await skyhook_task
                except Exception as e:
                    logger.warning("Skyhook search error on %s for '%s': %s", self.base_url, clean_query, e)

            if resp and hasattr(resp, "status_code") and resp.status_code == 200:
                items = resp.json()
                if isinstance(items, list):
                    unmatched_tmdb_ids = [
                        int(item["tmdbId"]) for item in items
                        if item.get("tmdbId") and str(item["tmdbId"]).isdigit() and int(item["tmdbId"]) not in tmdb_map
                    ]
                    if unmatched_tmdb_ids and needs_tmdb:
                        async def fetch_tmdb_tv_info(tmdb_id: int):
                            try:
                                tr = await client.get(
                                    f"{self.TMDB_URL}/tv/{tmdb_id}",
                                    params={"language": "ru-RU"},
                                    headers={"Authorization": f"Bearer {self.TMDB_TOKEN}", "accept": "application/json"},
                                )
                                if tr.status_code == 200:
                                    return tmdb_id, tr.json()
                            except Exception:
                                pass
                            return tmdb_id, None

                        id_fetches = [fetch_tmdb_tv_info(tid) for tid in unmatched_tmdb_ids[:8]]
                        id_results = await asyncio.gather(*id_fetches, return_exceptions=True)
                        for id_res in id_results:
                            if isinstance(id_res, tuple) and id_res[1]:
                                tid, t_data = id_res
                                tmdb_map[tid] = t_data
                                t_name = (t_data.get("name") or t_data.get("title") or "").strip().lower()
                                t_orig = (t_data.get("original_name") or t_data.get("originalTitle") or "").strip().lower()
                                if t_name:
                                    tmdb_name_map[t_name] = t_data
                                if t_orig:
                                    tmdb_name_map[t_orig] = t_data

                    for item in items:
                        r = self._map_skyhook_item(item, seen_ids, tmdb_map, tmdb_name_map)
                        if r:
                            results.append(r)

            # 2. Резервный шлюз Skyhook Servarr
            if not results and self.BACKUP_URL != self.base_url:
                try:
                    resp = await client.get(
                        f"{self.BACKUP_URL}/search/en/",
                        params={"term": clean_query},
                    )
                    if resp.status_code == 200:
                        items = resp.json()
                        if isinstance(items, list):
                            unmatched_tmdb_ids = [
                                int(item["tmdbId"]) for item in items
                                if item.get("tmdbId") and str(item["tmdbId"]).isdigit() and int(item["tmdbId"]) not in tmdb_map
                            ]
                            if unmatched_tmdb_ids and needs_tmdb:
                                async def fetch_backup_tmdb_tv_info(tmdb_id: int):
                                    try:
                                        tr = await client.get(
                                            f"{self.TMDB_URL}/tv/{tmdb_id}",
                                            params={"language": "ru-RU"},
                                            headers={"Authorization": f"Bearer {self.TMDB_TOKEN}", "accept": "application/json"},
                                        )
                                        if tr.status_code == 200:
                                            return tmdb_id, tr.json()
                                    except Exception:
                                        pass
                                    return tmdb_id, None

                                id_fetches = [fetch_backup_tmdb_tv_info(tid) for tid in unmatched_tmdb_ids[:8]]
                                id_results = await asyncio.gather(*id_fetches, return_exceptions=True)
                                for id_res in id_results:
                                    if isinstance(id_res, tuple) and id_res[1]:
                                        tid, t_data = id_res
                                        tmdb_map[tid] = t_data
                                        t_name = (t_data.get("name") or t_data.get("title") or "").strip().lower()
                                        t_orig = (t_data.get("original_name") or t_data.get("originalTitle") or "").strip().lower()
                                        if t_name:
                                            tmdb_name_map[t_name] = t_data
                                        if t_orig:
                                            tmdb_name_map[t_orig] = t_data

                            for item in items:
                                r = self._map_skyhook_item(item, seen_ids, tmdb_map, tmdb_name_map)
                                if r:
                                    results.append(r)
                except Exception as e:
                    logger.warning("Skyhook backup search error on %s for '%s': %s", self.BACKUP_URL, clean_query, e)

            # 3. Мгновенный CDN Fallback на TMDb TV (для сериалов и аниме)
            if not results:
                try:
                    resp = await client.get(
                        f"{self.TMDB_URL}/search/tv",
                        params={"query": clean_query, "language": "ru-RU", "include_adult": "false"},
                        headers={"Authorization": f"Bearer {self.TMDB_TOKEN}", "accept": "application/json"},
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        for item in data.get("results", []):
                            tmdb_id = item.get("id")
                            if not tmdb_id:
                                continue
                            ext_id = f"tv:{tmdb_id}"
                            if ext_id in seen_ids:
                                continue
                            seen_ids.add(ext_id)

                            year = None
                            d_str = item.get("first_air_date") or ""
                            if d_str and len(d_str) >= 4:
                                try:
                                    year = int(d_str[:4])
                                except ValueError:
                                    pass

                            origin_countries = item.get("origin_country") or []
                            is_anime = ("JP" in origin_countries or "JPN" in origin_countries)
                            c_type = "anime" if is_anime else "series"

                            poster = f"https://image.tmdb.org/t/p/w500{item['poster_path']}" if item.get("poster_path") else None

                            ru_title = item.get("name") or ""
                            orig_name = item.get("original_name") or ""
                            titles_by_lang: dict[str, str] = {}
                            if ru_title:
                                if any('\u0400' <= c <= '\u04ff' for c in ru_title):
                                    titles_by_lang["ru"] = ru_title
                                else:
                                    titles_by_lang["en"] = ru_title
                            if orig_name:
                                titles_by_lang["original"] = orig_name
                            if "en" not in titles_by_lang and orig_name and is_latin_text(orig_name):
                                titles_by_lang["en"] = orig_name

                            results.append(MetadataResult(
                                external_id=ext_id,
                                title=ru_title or orig_name or "",
                                year=year,
                                overview=item.get("overview"),
                                poster_url=poster,
                                rating=item.get("vote_average"),
                                country=", ".join(origin_countries) if origin_countries else None,
                                genre=None,
                                content_type=c_type,
                                original_title=orig_name or None,
                                titles_by_lang=titles_by_lang,
                            ))
                except Exception as e:
                    logger.warning("TMDb TV search fallback error for '%s': %s", clean_query, e)

        return results

    async def get_details(self, external_id: str) -> MetadataShowDetails:
        """Получение полных деталей и списка всех эпизодов через SkyHook / Servarr / TMDb."""
        ext_str = str(external_id or "").strip()
        if not ext_str:
            raise ValueError("external_id is empty")

        clean_id = ext_str
        for prefix in ("tvdb:", "sonarr:", "skyhook:"):
            if clean_id.lower().startswith(prefix):
                clean_id = clean_id[len(prefix):].strip()
                break

        if clean_id.startswith("movie:"):
            return await self._get_movie_details(clean_id[6:])
        elif clean_id.isdigit():
            return await self._get_series_details(clean_id)
        elif ext_str.lower().startswith(("anilist:", "mal:", "imdb:", "tmdb:", "tv:")):
            clean_tv = ext_str.split(":", 1)[1].strip() if ":" in ext_str else ext_str
            if ext_str.lower().startswith(("tv:", "tmdb:")) and clean_tv.isdigit():
                try:
                    tmdb = TMDBClient(api_key=self.TMDB_TOKEN, overview_language=self.overview_language)
                    return await tmdb._get_tv_details(clean_tv)
                except Exception as e:
                    logger.warning("Failed fetching TV details via TMDb for %s: %s", ext_str, e)

            # SkyHook Sonarr API умеет искать по anilist:id, mal:id, imdb:id, tmdb:id
            results = await self.search(ext_str)
            if results and results[0].external_id:
                target_ext = results[0].external_id
                target_clean = target_ext.replace("tvdb:", "").replace("sonarr:", "").replace("skyhook:", "")
                if target_clean.isdigit():
                    return await self._get_series_details(target_clean)
            return await self._get_series_details(clean_id)
        else:
            return await self._get_series_details(clean_id)

    async def _get_series_details(self, tvdb_id: str) -> MetadataShowDetails:
        async with httpx.AsyncClient(timeout=30, headers={"User-Agent": "Aliasarr/1.0.0 (Sonarr SkyHook Proxy)"}) as client:
            resp = None
            try:
                resp = await client.get(f"{self.base_url}/shows/en/{tvdb_id}")
                resp.raise_for_status()
            except Exception as e:
                logger.warning("Skyhook shows/en failed on %s: %s. Trying backup...", self.base_url, e)
                if self.BACKUP_URL != self.base_url:
                    resp = await client.get(f"{self.BACKUP_URL}/shows/en/{tvdb_id}")
                    resp.raise_for_status()
                else:
                    raise
            data = resp.json()

        raw_title = data.get("title") or ""
        aliases: list[str] = []
        allowed_langs = {"en", "eng"} | {l.lower() for l in (self.alias_languages or ["ru"])}

        # Алиасы и альтернативные названия из SkyHook (проверяем на соответствие разрешенным языкам)
        for item in (data.get("aliases") or []) + (data.get("alternativeTitles") or []):
            if isinstance(item, str) and item.strip():
                t = item.strip()
                if t != raw_title and t not in aliases:
                    if is_alias_allowed(t, None, allowed_langs):
                        aliases.append(t)
            elif isinstance(item, dict):
                t = (item.get("title") or item.get("cleanTitle") or "").strip()
                lang = item.get("language") or item.get("country") or item.get("iso_3166_1") or item.get("iso_639_1") or None
                if t and t != raw_title and t not in aliases:
                    if is_alias_allowed(t, lang, allowed_langs):
                        aliases.append(t)

        overviews_by_lang: dict[str, str] = {}
        if data.get("overview") and str(data.get("overview")).strip():
            overviews_by_lang["en"] = str(data.get("overview")).strip()

        # Запрашиваем переводы для настроенных языков пользователя и предпочитаемого языка описания
        req_langs = list(self.alias_languages or ["ru"])
        norm_overview_lang = normalize_metadata_lang_code(self.overview_language) or self.overview_language
        if norm_overview_lang and norm_overview_lang not in ("en", "original") and norm_overview_lang not in [l.lower() for l in req_langs]:
            req_langs.append(norm_overview_lang)

        async with httpx.AsyncClient(timeout=15, headers={"User-Agent": "Aliasarr/1.0.0 (Sonarr SkyHook Proxy)"}) as client:
            for lang in req_langs:
                if not lang or lang.lower() == "en":
                    continue
                try:
                    lang_resp = await client.get(f"{self.base_url}/shows/{lang.lower()}/{tvdb_id}")
                    if lang_resp.status_code != 200 and self.BACKUP_URL != self.base_url:
                        lang_resp = await client.get(f"{self.BACKUP_URL}/shows/{lang.lower()}/{tvdb_id}")
                    if lang_resp.status_code == 200:
                        lang_data = lang_resp.json()
                        lt = lang_data.get("title")
                        if lt and lt.strip() and lt.strip() != raw_title and lt.strip() not in aliases:
                            if is_alias_allowed(lt.strip(), lang, allowed_langs):
                                aliases.append(lt.strip())
                        lo = lang_data.get("overview")
                        if lo and str(lo).strip():
                            overviews_by_lang[normalize_metadata_lang_code(lang) or lang.lower()] = str(lo).strip()
                except Exception:
                    pass

        overview = select_overview(overviews_by_lang, data.get("overview"), self.overview_language)

        # Постер
        poster_url = extract_skyhook_poster(data.get("images", []))

        # Эпизоды
        genres = data.get("genres", [])
        country = data.get("originalCountry")
        is_anime = ("Anime" in genres or "Animation" in genres) and (country in ("Japan", "JP", "JPN"))
        c_type = "anime" if is_anime else "series"

        episodes: list[MetadataEpisode] = []
        running_abs = 1

        for ep in data.get("episodes", []):
            s_num = ep.get("seasonNumber", 1)
            e_num = ep.get("episodeNumber", 1)
            abs_num = ep.get("absoluteEpisodeNumber")
            if abs_num is None and is_anime and s_num > 0 and e_num > 0:
                abs_num = running_abs
                running_abs += 1

            episodes.append(
                MetadataEpisode(
                    season_number=s_num,
                    episode_number=e_num,
                    title=ep.get("title"),
                    air_date=ep.get("airDate") or ep.get("airDateUtc"),
                    absolute_number=abs_num,
                )
            )

        rating_val = (data.get("rating") or {}).get("value")
        premiere = data.get("firstAired")

        tvdb_id_int = int(tvdb_id) if str(tvdb_id).isdigit() else None
        tvmaze_id_val = int(data.get("tvMazeId")) if str(data.get("tvMazeId") or "").isdigit() else None
        imdb_id_val = data.get("imdbId")
        tmdb_id_val = int(data.get("tmdbId")) if str(data.get("tmdbId") or "").isdigit() else None

        orig_title = data.get("originalTitle") or ""
        tmdb_details = None

        # Обогащение переводами и алиасами на всех настроенных языках (RU, JA, ZH, KO и др.) через TMDb
        if tmdb_id_val:
            try:
                tmdb = TMDBClient(
                    api_key=RadarrClient.RADARR_TMDB_TOKEN,
                    alias_languages=self.alias_languages,
                    overview_language=self.overview_language,
                )
                tmdb_details = await tmdb._get_tv_details(str(tmdb_id_val), fetch_episodes=False)
                if tmdb_details:
                    for a in tmdb_details.aliases:
                        if a and a != raw_title and a not in aliases:
                            if is_alias_allowed(a, None, allowed_langs):
                                aliases.append(a)
                    if tmdb_details.original_title and not orig_title:
                        orig_title = tmdb_details.original_title
                    if tmdb_details.titles_by_lang:
                        for k, v in tmdb_details.titles_by_lang.items():
                            if v and v not in aliases and v != raw_title:
                                if is_alias_allowed(v, k, allowed_langs):
                                    aliases.append(v)
                    # Если TMDb предоставил локализованное описание на выбранном языке
                    norm_pref = normalize_metadata_lang_code(self.overview_language) or self.overview_language
                    if tmdb_details.overview:
                        if norm_pref in ("ru", "rus"):
                            if any('\u0400' <= c <= '\u04ff' for c in tmdb_details.overview):
                                overview = tmdb_details.overview
                        elif norm_pref not in ("en", "original"):
                            overview = tmdb_details.overview
                        elif not overview:
                            overview = tmdb_details.overview
            except Exception as e:
                logger.debug("TMDb TV enrichment failed for tvdb %s (tmdb %s): %s", tvdb_id, tmdb_id_val, e)

        orig_title = orig_title or data.get("originalTitle") or ""
        titles_by_lang: dict[str, str] = {}
        if raw_title:
            titles_by_lang["en"] = raw_title
        if orig_title:
            titles_by_lang["original"] = orig_title

        ru_title = None
        for a in aliases:
            if any('\u0400' <= c <= '\u04ff' for c in a):
                ru_title = a
                break
        if not ru_title and tmdb_details and tmdb_details.titles_by_lang.get("ru"):
            ru_title = tmdb_details.titles_by_lang["ru"]
        if not ru_title and orig_title and any('\u0400' <= c <= '\u04ff' for c in orig_title):
            ru_title = orig_title
        if ru_title:
            titles_by_lang["ru"] = ru_title
            if ru_title not in aliases and ru_title != raw_title:
                aliases.append(ru_title)

        chosen_title = raw_title
        norm_pref = normalize_metadata_lang_code(self.overview_language) or self.overview_language
        if norm_pref in ("ru", "rus") and ru_title:
            chosen_title = ru_title
        elif norm_pref == "original" and orig_title:
            chosen_title = orig_title

        return MetadataShowDetails(
            external_id=f"tvdb:{tvdb_id}",
            title=raw_title,
            aliases=aliases,
            overview=overview,
            poster_url=poster_url,
            episodes=episodes,
            rating=float(rating_val) if rating_val is not None else None,
            country=country,
            genre=", ".join(genres) if genres else None,
            network=data.get("network"),
            content_type=c_type,
            premiere_date=premiere,
            imdb_id=imdb_id_val,
            tmdb_id=tmdb_id_val,
            tvdb_id=tvdb_id_int,
            tvmaze_id=tvmaze_id_val,
            original_title=orig_title or None,
            titles_by_lang=titles_by_lang,
        )

    async def _get_movie_details(self, tmdb_id: str) -> MetadataShowDetails:
        radarr = RadarrClient(api_key="", alias_languages=self.alias_languages, overview_language=self.overview_language)
        return await radarr.get_details(f"movie:{tmdb_id}")


class RadarrClient(BaseMetadataClient):
    """
    Radarr SkyHook Proxy — официальный облачный сервис метаданных Radarr (api.radarr.video).
    Работает «из коробки» БЕЗ необходимости вводить персональные API-ключи.
    Предоставляет полные данные TMDb / IMDb для фильмов, включая AlternativeTitles и Translations
    на всех языках для точного сопоставления и автопоиска торрент-релизов.
    """

    BASE_URL = "https://api.radarr.video/v1"
    BACKUP_URL = "https://radarr.servarr.com/v1/api"
    TMDB_URL = "https://api.themoviedb.org/3"
    # Встроенный сервисный Bearer-токен TMDb из Radarr для прямого резервного поиска
    RADARR_TMDB_TOKEN = "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJhdWQiOiIxYTczNzMzMDE5NjFkMDNmOTdmODUzYTg3NmRkMTIxMiIsInN1YiI6IjU4NjRmNTkyYzNhMzY4MGFiNjAxNzUzNCIsInNjb3BlcyI6WyJhcGlfcmVhZCJdLCJ2ZXJzaW9uIjoxfQ.gh1BwogCCKOda6xj9FRMgAAj_RYKMMPC3oNlcBtlmwk"

    def __init__(
        self,
        api_key: str = "",
        alias_countries: Optional[list[str]] = None,
        base_url: str = "",
        alias_languages: Optional[list[str]] = None,
        overview_language: str = "ru",
        title_language: str = "ru",
    ):
        self.base_url = (base_url or self.BASE_URL).rstrip("/")
        langs = []
        if alias_languages:
            langs = [l.lower() for l in alias_languages if l and l.lower() != "en"]
        elif alias_countries:
            langs = [c.lower() for c in alias_countries if c and c.lower() != "en"]
        if not langs:
            langs = ["ru"]
        self.alias_languages = langs
        self.alias_countries = [c.upper() for c in alias_countries] if alias_countries else None
        self.overview_language = (overview_language or "ru").strip().lower()
        self.title_language = (title_language or "ru").strip().lower()

    async def search(self, query: str) -> list[MetadataResult]:
        if not query or not query.strip():
            return []

        clean_query = query.strip()
        if clean_query.lower().startswith("imdb:") or clean_query.lower().startswith("imdbid:"):
            imdb_id = clean_query.split(":", 1)[1].strip()
            movie = await self._get_movie_by_imdb(imdb_id)
            return [movie] if movie else []

        if clean_query.lower().startswith("tmdb:") or clean_query.lower().startswith("tmdbid:"):
            tmdb_id = clean_query.split(":", 1)[1].strip()
            if tmdb_id.isdigit():
                details = await self.get_details(f"movie:{tmdb_id}")
                if details:
                    return [MetadataResult(
                        external_id=details.external_id,
                        title=details.title,
                        year=int(details.premiere_date[:4]) if details.premiere_date and len(details.premiere_date) >= 4 else None,
                        overview=details.overview,
                        poster_url=details.poster_url,
                        rating=details.rating,
                        country=details.country,
                        genre=details.genre,
                        content_type="movie",
                    )]
            return []

        results: list[MetadataResult] = []
        seen_ids: set[str] = set()

        if httpx is None:
            return results

        async with httpx.AsyncClient(timeout=25, headers={"User-Agent": "Aliasarr/1.0.0 (Radarr Movie Cloud Proxy)"}) as client:
            # 1. Запрос к официальному Radarr SkyHook
            try:
                resp = await client.get(f"{self.base_url}/search", params={"q": clean_query})
                if resp.status_code == 200:
                    items = resp.json()
                    if isinstance(items, list):
                        for m_item in items:
                            r = self._map_movie_to_result(m_item)
                            if r and r.external_id not in seen_ids:
                                seen_ids.add(r.external_id)
                                results.append(r)
            except Exception as e:
                logger.debug("Radarr search error on %s: %s", self.base_url, e)

            # 2. Резервный Servarr шлюз
            if not results:
                try:
                    resp = await client.get(f"{self.BACKUP_URL}/search", params={"term": clean_query})
                    if resp.status_code == 200:
                        items = resp.json()
                        if isinstance(items, list):
                            for m_item in items:
                                r = self._map_movie_to_result(m_item)
                                if r and r.external_id not in seen_ids:
                                    seen_ids.add(r.external_id)
                                    results.append(r)
                except Exception:
                    pass

            # 3. Прямой fallback на TMDb через токен Radarr
            if not results:
                try:
                    resp = await client.get(
                        f"{self.TMDB_URL}/search/movie",
                        params={"query": clean_query, "language": "ru-RU", "include_adult": "false"},
                        headers={"Authorization": f"Bearer {self.RADARR_TMDB_TOKEN}", "accept": "application/json"},
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        for item in data.get("results", []):
                            tmdb_id = item.get("id")
                            if not tmdb_id:
                                continue
                            ext_id = f"movie:{tmdb_id}"
                            if ext_id in seen_ids:
                                continue
                            seen_ids.add(ext_id)
                            year = None
                            d_str = item.get("release_date") or ""
                            if d_str and len(d_str) >= 4:
                                try:
                                    year = int(d_str[:4])
                                except ValueError:
                                    pass
                            t_title = item.get("title") or ""
                            t_orig = item.get("original_title") or ""
                            titles_by_lang: dict[str, str] = {}
                            if t_title:
                                if any('\u0400' <= c <= '\u04ff' for c in t_title):
                                    titles_by_lang["ru"] = t_title
                                else:
                                    titles_by_lang["en"] = t_title
                            if t_orig:
                                titles_by_lang["original"] = t_orig
                                if "en" not in titles_by_lang and is_latin_text(t_orig):
                                    titles_by_lang["en"] = t_orig
                            poster_path = item.get("poster_path")
                            poster = f"https://image.tmdb.org/t/p/w500{poster_path}" if poster_path else None

                            results.append(MetadataResult(
                                external_id=ext_id,
                                title=t_title or t_orig or "",
                                year=year,
                                overview=item.get("overview"),
                                poster_url=poster,
                                rating=item.get("vote_average"),
                                country=item.get("original_language"),
                                genre=None,
                                content_type="movie",
                                original_title=t_orig or None,
                                titles_by_lang=titles_by_lang,
                            ))
                except Exception:
                    pass

        return results

    def _map_movie_to_result(self, m_item: dict) -> Optional[MetadataResult]:
        tmdb_id = m_item.get("tmdbId")
        if not tmdb_id:
            return None
        ext_id = f"movie:{tmdb_id}"
        poster_url = extract_skyhook_poster(m_item.get("images", []))
        ratings = m_item.get("ratings") or m_item.get("movieRatings") or {}
        rating_val = None
        if isinstance(ratings, dict):
            rating_val = ratings.get("value") or (ratings.get("tmdb") or {}).get("value")
        elif isinstance(ratings, list) and ratings:
            rating_val = ratings[0].get("value")

        m_title = m_item.get("title") or ""
        m_orig = m_item.get("originalTitle") or ""
        titles_by_lang: dict[str, str] = {}
        if m_title:
            if any('\u0400' <= c <= '\u04ff' for c in m_title):
                titles_by_lang["ru"] = m_title
            else:
                titles_by_lang["en"] = m_title
        if m_orig:
            titles_by_lang["original"] = m_orig
            if "en" not in titles_by_lang and is_latin_text(m_orig):
                titles_by_lang["en"] = m_orig

        for tr in (m_item.get("translations") or []):
            if isinstance(tr, dict):
                tr_l = (tr.get("language") or tr.get("iso_639_1") or "").lower()
                tr_t = tr.get("title") or tr.get("name")
                if tr_t and tr_l in ("ru", "rus") and "ru" not in titles_by_lang:
                    titles_by_lang["ru"] = tr_t.strip()
                elif tr_t and tr_l in ("en", "eng") and "en" not in titles_by_lang:
                    titles_by_lang["en"] = tr_t.strip()

        norm_title_pref = normalize_metadata_lang_code(self.title_language) or self.title_language
        display_title = m_title or m_orig or ""
        if norm_title_pref in ("ru", "rus") and titles_by_lang.get("ru"):
            display_title = titles_by_lang["ru"]
        elif norm_title_pref in ("original", "orig") and titles_by_lang.get("original"):
            display_title = titles_by_lang["original"]
        elif norm_title_pref in ("en", "eng") and titles_by_lang.get("en"):
            display_title = titles_by_lang["en"]

        genres = m_item.get("genres", [])
        return MetadataResult(
            external_id=ext_id,
            title=display_title,
            year=m_item.get("year"),
            overview=m_item.get("overview"),
            poster_url=poster_url,
            rating=float(rating_val) if rating_val is not None else None,
            country=m_item.get("originalLanguage"),
            genre=", ".join(genres) if genres else None,
            content_type="movie",
            original_title=m_orig or None,
            titles_by_lang=titles_by_lang,
        )

    async def _get_movie_by_imdb(self, imdb_id: str) -> Optional[MetadataResult]:
        if httpx is None:
            return None
        async with httpx.AsyncClient(timeout=20, headers={"User-Agent": "Aliasarr/1.0.0 (Radarr Movie Cloud Proxy)"}) as client:
            try:
                resp = await client.get(f"{self.base_url}/movie/imdb/{imdb_id}")
                if resp.status_code == 200:
                    items = resp.json()
                    if isinstance(items, list) and items:
                        return self._map_movie_to_result(items[0])
                    elif isinstance(items, dict):
                        return self._map_movie_to_result(items)
            except Exception:
                pass
        return None

    async def get_details(self, external_id: str) -> MetadataShowDetails:
        clean_id = str(external_id).replace("movie:", "").replace("tmdb:", "").strip()
        if not clean_id.isdigit():
            if clean_id.startswith("tt"):
                res = await self._get_movie_by_imdb(clean_id)
                if res:
                    clean_id = res.external_id.replace("movie:", "")

        if httpx is None:
            return MetadataShowDetails(external_id=f"movie:{clean_id}", title=clean_id, content_type="movie")

        allowed_langs = {"en", "eng"} | {l.lower() for l in (self.alias_languages or ["ru"])}

        # 1. Приоритетный прямой запрос к TMDB с сервисным токеном Radarr (надёжно и полно)
        try:
            tmdb = TMDBClient(api_key=self.RADARR_TMDB_TOKEN, alias_languages=self.alias_languages, overview_language=self.overview_language)
            details = await tmdb._get_movie_details(clean_id)
            if details and details.title and details.title.strip():
                return details
        except Exception as e:
            logger.debug("TMDb direct details lookup failed for %s: %s", clean_id, e)

        # 2. Запрос через Radarr Movie API
        async with httpx.AsyncClient(timeout=30, headers={"User-Agent": "Aliasarr/1.0.0 (Radarr Movie Cloud Proxy)"}) as client:
            data = None
            try:
                resp = await client.get(f"{self.base_url}/movie/{clean_id}")
                if resp.status_code == 200:
                    data = resp.json()
            except Exception as e:
                logger.debug("Radarr movie details error on %s: %s", self.base_url, e)

            # 2. Резервный Servarr
            if not data:
                try:
                    resp = await client.get(f"{self.BACKUP_URL}/movie/lookup/tmdb", params={"tmdbId": clean_id})
                    if resp.status_code == 200:
                        data = resp.json()
                except Exception:
                    pass

            if data and isinstance(data, dict):
                title = data.get("title") or data.get("originalTitle") or ""
                original_title = data.get("originalTitle")
                overview = data.get("overview")

                aliases: list[str] = []
                orig_lang = data.get("originalLanguage")
                if isinstance(orig_lang, dict):
                    orig_lang = orig_lang.get("name") or orig_lang.get("code") or ""
                orig_lang = str(orig_lang or "")

                if original_title and original_title != title and original_title not in aliases:
                    aliases.append(original_title)

                # Собираем alternativeTitles строго на разрешенных языках
                for alt in (data.get("alternativeTitles", []) or data.get("alternateTitles", [])):
                    if isinstance(alt, dict):
                        t_name = alt.get("title") or alt.get("cleanTitle")
                        raw_lang = alt.get("language") or alt.get("country") or ""
                        if not t_name or not t_name.strip():
                            continue
                        t_clean = t_name.strip()
                        if t_clean == title or t_clean in aliases:
                            continue
                        if not is_alias_allowed(t_clean, raw_lang, allowed_langs, original_lang=orig_lang):
                            continue
                        aliases.append(t_clean)
                    elif isinstance(alt, str) and alt.strip():
                        t_clean = alt.strip()
                        if t_clean != title and t_clean not in aliases:
                            if is_alias_allowed(t_clean, "", allowed_langs, original_lang=orig_lang):
                                aliases.append(t_clean)

                # Собираем переводы (Translations) и описания на разрешенных языках
                overviews_by_lang: dict[str, str] = {}
                titles_by_lang: dict[str, str] = {}
                if title:
                    if any('\u0400' <= c <= '\u04ff' for c in title):
                        titles_by_lang["ru"] = title
                    else:
                        titles_by_lang["en"] = title
                if original_title:
                    titles_by_lang["original"] = original_title
                    if "en" not in titles_by_lang and is_latin_text(original_title):
                        titles_by_lang["en"] = original_title

                for tr in (data.get("translations", []) or []):
                    if isinstance(tr, dict):
                        tr_title = tr.get("title") or tr.get("name")
                        raw_lang = tr.get("language") or tr.get("iso_639_1") or ""
                        norm_tr_lang = normalize_metadata_lang_code(raw_lang)
                        if norm_tr_lang in allowed_langs and tr_title and tr_title.strip():
                            tr_clean = tr_title.strip()
                            if tr_clean != title and tr_clean not in aliases:
                                aliases.append(tr_clean)
                            if norm_tr_lang in ("ru", "rus") and "ru" not in titles_by_lang:
                                titles_by_lang["ru"] = tr_clean
                            elif norm_tr_lang in ("en", "eng") and "en" not in titles_by_lang:
                                titles_by_lang["en"] = tr_clean
                        tr_ov = tr.get("overview")
                        if norm_tr_lang and tr_ov and str(tr_ov).strip():
                            overviews_by_lang[norm_tr_lang] = str(tr_ov).strip()

                norm_pref = normalize_metadata_lang_code(self.overview_language) or self.overview_language
                chosen_title = title
                if norm_pref in ("ru", "rus") and titles_by_lang.get("ru"):
                    chosen_title = titles_by_lang["ru"]
                elif norm_pref == "original" and titles_by_lang.get("original"):
                    chosen_title = titles_by_lang["original"]

                overview = select_overview(overviews_by_lang, data.get("overview"), self.overview_language)

                poster_url = extract_skyhook_poster(data.get("images", []))
                ratings = data.get("ratings") or data.get("movieRatings") or {}
                rating_val = None
                if isinstance(ratings, dict):
                    rating_val = ratings.get("value") or (ratings.get("tmdb") or {}).get("value")
                elif isinstance(ratings, list) and ratings:
                    rating_val = ratings[0].get("value")

                premiere = (
                    data.get("digitalRelease")
                    or data.get("physicalRelease")
                    or data.get("inCinema")
                    or data.get("inCinemas")
                    or data.get("premier")
                )

                genres = data.get("genres", [])
                genres_str = ", ".join(genres) if isinstance(genres, list) else str(genres or "")

                tmdb_id_val = int(clean_id) if str(clean_id).isdigit() else (int(data.get("tmdbId")) if str(data.get("tmdbId") or "").isdigit() else None)
                imdb_id_val = data.get("imdbId")
                yt_id = data.get("youTubeTrailerId")
                trailer_url_val = f"https://www.youtube.com/watch?v={yt_id}" if yt_id else None

                in_cinemas_val = str(data.get("inCinemas") or data.get("inCinema") or "")[:10] or None
                digital_rel_val = str(data.get("digitalRelease") or "")[:10] or None
                physical_rel_val = str(data.get("physicalRelease") or "")[:10] or None

                coll_data = data.get("collection")
                coll_tmdb_id_val = data.get("collectionTmdbId") or (coll_data.get("tmdbId") if isinstance(coll_data, dict) else None)
                coll_title_val = data.get("collectionTitle") or (coll_data.get("title") or coll_data.get("name") if isinstance(coll_data, dict) else None)

                if title and title.strip():
                    return MetadataShowDetails(
                        external_id=f"movie:{clean_id}",
                        title=title,
                        aliases=aliases,
                        overview=overview,
                        poster_url=poster_url,
                        episodes=[],
                        rating=float(rating_val) if rating_val is not None else None,
                        country=data.get("originalLanguage"),
                        genre=genres_str or None,
                        network=data.get("studio"),
                        content_type="movie",
                        premiere_date=str(premiere)[:10] if premiere else None,
                        in_cinemas_date=in_cinemas_val,
                        digital_release_date=digital_rel_val,
                        physical_release_date=physical_rel_val,
                        collection_tmdb_id=coll_tmdb_id_val,
                        collection_name=coll_title_val,
                        imdb_id=imdb_id_val,
                        tmdb_id=tmdb_id_val,
                        trailer_url=trailer_url_val,
                        original_title=original_title or None,
                        titles_by_lang=titles_by_lang,
                    )

        # 3. Fallback на TMDB с сервисным токеном
        tmdb = TMDBClient(api_key=self.RADARR_TMDB_TOKEN, alias_languages=self.alias_languages, overview_language=self.overview_language)
        return await tmdb._get_movie_details(clean_id)

    async def get_collection_details(
        self,
        tmdb_collection_id: int | str,
        lang: Optional[str] = None,
        bypass_cache: bool = False,
    ) -> dict:
        """Получить киноколлекцию через TMDb API с сервисным токеном Radarr."""
        chosen_lang = lang or self.overview_language
        tmdb = TMDBClient(
            api_key=self.RADARR_TMDB_TOKEN,
            alias_languages=self.alias_languages,
            overview_language=chosen_lang,
        )
        return await tmdb.get_collection_details(
            tmdb_collection_id,
            lang=chosen_lang,
            bypass_cache=bypass_cache,
        )


def _tvdb_3_letter_code(lang: str) -> str:
    m = {
        "ru": "rus", "rus": "rus", "russian": "rus",
        "en": "eng", "eng": "eng", "english": "eng",
        "de": "deu", "deu": "deu", "german": "deu",
        "fr": "fra", "fra": "fra", "french": "fra",
        "es": "spa", "spa": "spa", "spanish": "spa",
        "it": "ita", "ita": "ita", "italian": "ita",
        "ja": "jpn", "jpn": "jpn", "japanese": "jpn",
        "ko": "kor", "kor": "kor", "korean": "kor",
        "zh": "zho", "zho": "zho", "chinese": "zho",
        "uk": "ukr", "ukr": "ukr", "ukrainian": "ukr",
        "pt": "por", "por": "por", "portuguese": "por",
    }
    return m.get((lang or "").lower(), (lang or "").lower())


class TheTVDBClient(BaseMetadataClient):
    """
    TheTVDB API v4 (api4.thetvdb.com/v4).

    Аутентификация: POST /login с {"apikey": api_key, "pin": pin (опционально)}.
    Возвращает Bearer-токен, действительный 1 месяц.
    
    Для совместимости с Jellyfin все названия фильмов/сериалов и серий
    сохраняются на английском языке, а русские и альтернативные названия
    помещаются в список алиасов для точного поиска торрентов на трекерах.
    """

    BASE_URL = "https://api4.thetvdb.com/v4"
    ARTWORK_BASE = "https://artworks.thetvdb.com"

    def __init__(
        self,
        api_key: str = "",
        pin: str = "",
        alias_countries: Optional[list[str]] = None,
        base_url: str = "",
        alias_languages: Optional[list[str]] = None,
        overview_language: str = "ru",
        title_language: str = "ru",
    ):
        self.api_key = (api_key or "").strip()
        self.pin = (pin or "").strip()
        if ":" in self.api_key and not self.pin:
            self.api_key, self.pin = self.api_key.split(":", 1)
        self.alias_countries = [c.upper() for c in alias_countries] if alias_countries else None
        self.alias_languages = [l.lower() for l in alias_languages] if alias_languages else None
        self.base_url = (base_url or self.BASE_URL).rstrip("/")
        self.overview_language = (overview_language or "ru").strip().lower()
        self.title_language = (title_language or "ru").strip().lower()
        self._token: Optional[str] = None
        self._token_expires_at: Optional[float] = None

    async def _get_token(self, client: httpx.AsyncClient) -> str:
        import time
        now = time.time()
        if self._token and self._token_expires_at and now < (self._token_expires_at - 86400):
            return self._token

        if not self.api_key:
            raise ValueError(
                "Не указан TheTVDB API Key v4. "
                "Получите ключ на thetvdb.com и введите его в Настройках -> Источники метаданных."
            )

        payload = {"apikey": self.api_key}
        if self.pin:
            payload["pin"] = self.pin

        resp = await client.post(
            f"{self.base_url}/login",
            json=payload,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        if resp.status_code != 200:
            err_msg = resp.text
            try:
                err_msg = resp.json().get("message", resp.text)
            except Exception:
                pass
            raise ValueError(f"Ошибка авторизации TheTVDB v4: {err_msg}")

        data = resp.json()
        token = (data.get("data") or {}).get("token")
        if not token:
            raise ValueError("TheTVDB /login не вернул токен авторизации")

        self._token = token
        self._token_expires_at = now + 2592000  # 30 days
        return self._token

    async def _authed_get(self, client: httpx.AsyncClient, path: str, params: Optional[dict] = None) -> httpx.Response:
        token = await self._get_token(client)
        url = f"{self.base_url}{path}" if path.startswith("/") else f"{self.base_url}/{path}"
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        resp = await client.get(url, params=params, headers=headers)
        if resp.status_code == 401:
            self._token = None
            token = await self._get_token(client)
            headers["Authorization"] = f"Bearer {token}"
            resp = await client.get(url, params=params, headers=headers)
        return resp

    async def search(self, query: str) -> list[MetadataResult]:
        if not query or not query.strip():
            return []
        async with httpx.AsyncClient(timeout=25) as client:
            resp = await self._authed_get(client, "/search", params={"query": query.strip()})
            resp.raise_for_status()
            data = resp.json()

        results = []
        for item in data.get("data", []):
            item_type = (item.get("type") or "").lower()
            if item_type not in ("series", "movie"):
                continue

            raw_id = item.get("tvdb_id") or item.get("id") or item.get("objectID") or ""
            clean_id = str(raw_id).split("-")[-1].strip()
            if not clean_id:
                continue

            ext_id = f"{item_type}:{clean_id}"
            raw_title = item.get("name") or item.get("title") or ""
            translated_title = item.get("name_translated") or ""

            # Ищем наилучшее английское/латинское название для Jellyfin
            candidates = []
            translations = item.get("translations") or {}
            if isinstance(translations, dict):
                for lang_code in ("eng", "en", "usa", "gbr"):
                    if translations.get(lang_code):
                        candidates.append(str(translations[lang_code]).strip())
            
            for al in item.get("aliases") or []:
                if isinstance(al, str) and al.strip():
                    candidates.append(al.strip())
                elif isinstance(al, dict) and al.get("name"):
                    candidates.append(str(al["name"]).strip())

            latin_candidates = [c for c in candidates if is_latin_text(c)]
            
            if is_latin_text(raw_title):
                title = raw_title
            elif latin_candidates:
                title = latin_candidates[0]
            elif is_latin_text(translated_title):
                title = translated_title
            else:
                title = raw_title or translated_title

            year = None
            raw_year = item.get("year") or item.get("first_air_time") or ""
            if raw_year and len(str(raw_year)) >= 4:
                try:
                    year = int(str(raw_year)[:4])
                except ValueError:
                    pass

            poster = item.get("image_url") or item.get("poster") or item.get("thumbnail")
            if poster and not poster.startswith("http"):
                poster = f"{self.ARTWORK_BASE}/{poster.lstrip('/')}"

            genres = item.get("genres") or []
            if isinstance(genres, list):
                genre_str = ", ".join(str(g) for g in genres if g)
            else:
                genre_str = str(genres) if genres else None

            content_type = item_type
            if item_type == "series":
                genres_lower = [str(g).lower() for g in (genres if isinstance(genres, list) else [])]
                if "anime" in genres_lower or "animation" in genres_lower:
                    if (item.get("country") or "").lower() in ("jpn", "japan", "jp"):
                        content_type = "anime"

            results.append(MetadataResult(
                external_id=ext_id,
                title=title,
                year=year,
                overview=item.get("overview"),
                poster_url=poster,
                rating=None,
                country=item.get("country"),
                genre=genre_str or None,
                content_type=content_type,
            ))
        return results

    async def get_details(self, external_id: str) -> MetadataShowDetails:
        clean_ext = str(external_id).strip()
        if clean_ext.startswith("tvdb:"):
            clean_ext = clean_ext[5:].strip()

        media_type = None
        if ":" in clean_ext:
            media_type, tvdb_id = clean_ext.split(":", 1)
        else:
            tvdb_id = clean_ext

        tvdb_id = str(tvdb_id).split("-")[-1].strip()

        if media_type == "movie":
            try:
                return await self._get_movie_details(tvdb_id)
            except Exception as e:
                logger.warning("TheTVDB _get_movie_details failed for %s, trying series fallback: %s", tvdb_id, e)
                return await self._get_series_details(tvdb_id)
        elif media_type == "series":
            try:
                return await self._get_series_details(tvdb_id)
            except Exception as e:
                logger.warning("TheTVDB _get_series_details failed for %s, trying movie fallback: %s", tvdb_id, e)
                return await self._get_movie_details(tvdb_id)
        else:
            try:
                return await self._get_series_details(tvdb_id)
            except Exception:
                return await self._get_movie_details(tvdb_id)

    async def _get_series_details(self, tvdb_id: str) -> MetadataShowDetails:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await self._authed_get(client, f"/series/{tvdb_id}/extended")
            if resp.status_code != 200:
                resp = await self._authed_get(client, f"/series/{tvdb_id}")
            if resp.status_code != 200:
                raise ValueError(f"TheTVDB series {tvdb_id} not found (status {resp.status_code})")
            data = resp.json().get("data", {}) or {}

            # Эпизоды с английскими названиями и абсолютной нумерацией (для Jellyfin / аниме)
            episodes: list[MetadataEpisode] = []

            # 1. Сначала берём полные данные эпизодов из /extended
            extended_episodes = data.get("episodes") or []
            for ep in (extended_episodes if isinstance(extended_episodes, list) else []):
                if not isinstance(ep, dict):
                    continue
                s_num = ep.get("seasonNumber")
                if s_num is None:
                    s_num = 0
                e_num = ep.get("number") or 0
                if not e_num and s_num == 0:
                    e_num = 1
                if e_num:
                    abs_num = ep.get("absoluteNumber")
                    if abs_num is not None:
                        try:
                            abs_num = int(abs_num)
                            if abs_num <= 0:
                                abs_num = None
                        except (ValueError, TypeError):
                            abs_num = None
                    aired = ep.get("aired")
                    if aired:
                        aired = str(aired)[:10]
                    episodes.append(MetadataEpisode(
                        season_number=s_num,
                        episode_number=e_num,
                        title=ep.get("name") or f"Episode {e_num}",
                        air_date=aired,
                        absolute_number=abs_num,
                    ))

            # 2. Если в /extended не было списка серий, опрашиваем /episodes/default/eng
            if not episodes:
                try:
                    ep_resp = await self._authed_get(client, f"/series/{tvdb_id}/episodes/default/eng")
                    if ep_resp.status_code == 200:
                        ep_data = ep_resp.json().get("data") or {}
                        ep_list = ep_data.get("episodes", []) if isinstance(ep_data, dict) else (ep_data if isinstance(ep_data, list) else [])
                        for ep in ep_list:
                            if not isinstance(ep, dict):
                                continue
                            s_num = ep.get("seasonNumber")
                            if s_num is None:
                                s_num = 0
                            e_num = ep.get("number") or 0
                            if not e_num and s_num == 0:
                                e_num = 1
                            if e_num:
                                abs_num = ep.get("absoluteNumber")
                                if abs_num is not None:
                                    try:
                                        abs_num = int(abs_num)
                                        if abs_num <= 0:
                                            abs_num = None
                                    except (ValueError, TypeError):
                                        abs_num = None
                                aired = ep.get("aired")
                                if aired:
                                    aired = str(aired)[:10]
                                episodes.append(MetadataEpisode(
                                    season_number=s_num,
                                    episode_number=e_num,
                                    title=ep.get("name") or f"Episode {e_num}",
                                    air_date=aired,
                                    absolute_number=abs_num,
                                ))
                except Exception:
                    pass

            overviews_by_lang: dict[str, str] = {}
            # Поиск официального английского перевода TheTVDB
            eng_title = None
            eng_overview = None
            try:
                eng_resp = await self._authed_get(client, f"/series/{tvdb_id}/translations/eng")
                if eng_resp.status_code == 200:
                    eng_data = eng_resp.json().get("data") or {}
                    eng_title = eng_data.get("name")
                    eng_overview = eng_data.get("overview")
                    if eng_overview and str(eng_overview).strip():
                        overviews_by_lang["en"] = str(eng_overview).strip()
            except Exception:
                pass

            # Поиск русского названия и описания в переводах
            ru_title = None
            ru_overview = None
            try:
                ru_resp = await self._authed_get(client, f"/series/{tvdb_id}/translations/rus")
                if ru_resp.status_code == 200:
                    ru_data = ru_resp.json().get("data") or {}
                    ru_title = ru_data.get("name")
                    ru_overview = ru_data.get("overview")
                    if ru_overview and str(ru_overview).strip():
                        overviews_by_lang["ru"] = str(ru_overview).strip()
            except Exception:
                pass

            # Поиск перевода для стороннего предпочтительного языка
            norm_ov = normalize_metadata_lang_code(self.overview_language) or self.overview_language
            if norm_ov and norm_ov not in ("en", "ru", "original"):
                code_3 = _tvdb_3_letter_code(norm_ov)
                if code_3:
                    try:
                        tr_resp = await self._authed_get(client, f"/series/{tvdb_id}/translations/{code_3}")
                        if tr_resp.status_code == 200:
                            tr_data = tr_resp.json().get("data") or {}
                            tr_ov = tr_data.get("overview")
                            if tr_ov and str(tr_ov).strip():
                                overviews_by_lang[norm_ov] = str(tr_ov).strip()
                    except Exception:
                        pass

        raw_name = (data.get("name") or "").strip()
        aliases_raw = data.get("aliases") or []

        # Выбираем наилучшее английское название для Jellyfin
        if eng_title and is_latin_text(eng_title):
            title = eng_title.strip()
        elif is_latin_text(raw_name):
            title = raw_name
        else:
            # Нелатинский оригинал (напр. Японский «ヤニねこ») — ищем английский алиас
            eng_alias = None
            for a in (aliases_raw if isinstance(aliases_raw, list) else []):
                a_name = (a.get("name") if isinstance(a, dict) else str(a) if a else "").strip()
                a_lang = (a.get("language") if isinstance(a, dict) else "").lower()
                if not a_name or not is_latin_text(a_name):
                    continue
                if a_lang in ("eng", "en", "usa", "gbr", "romaji", "lat"):
                    eng_alias = a_name
                    break
                elif not eng_alias:
                    eng_alias = a_name
            title = eng_alias or raw_name or ru_title or f"Series {tvdb_id}"

        # Собираем ВСЕ алиасы для поиска торрентов на трекерах
        allowed_langs = {"en", "eng"} | {l.lower() for l in (self.alias_languages or ["ru"])}
        aliases = []
        if raw_name and raw_name != title and raw_name not in aliases:
            aliases.append(raw_name)
        if ru_title and ru_title != title and ru_title not in aliases and ("ru" in allowed_langs or "rus" in allowed_langs):
            aliases.append(ru_title)

        for a in (aliases_raw if isinstance(aliases_raw, list) else []):
            alias_name = (a.get("name") if isinstance(a, dict) else str(a) if a else "").strip()
            alias_lang = (a.get("language") if isinstance(a, dict) else "")
            if alias_name and alias_name != title and alias_name not in aliases:
                if not is_alias_allowed(alias_name, alias_lang, allowed_langs):
                    continue
                aliases.append(alias_name)

        poster = data.get("image")
        if poster and not str(poster).startswith("http"):
            poster = f"{self.ARTWORK_BASE}/{str(poster).lstrip('/')}"
        elif not poster:
            for art in (data.get("artworks") or []):
                if isinstance(art, dict) and art.get("type") in (2, "2", "poster") and art.get("image"):
                    art_img = str(art["image"])
                    poster = art_img if art_img.startswith("http") else f"{self.ARTWORK_BASE}/{art_img.lstrip('/')}"
                    break

        genres = []
        for g in (data.get("genres") or []):
            if isinstance(g, dict) and g.get("name"):
                genres.append(str(g["name"]))
            elif isinstance(g, str) and g.strip():
                genres.append(g.strip())

        orig_network = data.get("originalNetwork") if isinstance(data.get("originalNetwork"), dict) else {}
        latest_network = data.get("latestNetwork") if isinstance(data.get("latestNetwork"), dict) else {}
        network = orig_network.get("name") or latest_network.get("name")
        country = data.get("originalCountry")
        premiere = data.get("firstAired")
        if premiere:
            premiere = str(premiere)[:10]

        content_type = "series"
        genres_lower = [str(g).lower() for g in genres]
        if "anime" in genres_lower or "animation" in genres_lower:
            if (country or "").lower() in ("jpn", "japan", "jp"):
                content_type = "anime"

        # Описание сюжета на основе предпочтительного языка с фоллбэками
        overview = select_overview(overviews_by_lang, data.get("overview"), self.overview_language)

        raw_score = data.get("score")
        rating = None
        if raw_score is not None:
            try:
                rating = float(raw_score)
            except (ValueError, TypeError):
                rating = None

        tvdb_id_int = int(tvdb_id) if str(tvdb_id).isdigit() else None

        return MetadataShowDetails(
            external_id=f"series:{tvdb_id}",
            title=title,
            aliases=aliases,
            overview=overview,
            poster_url=poster,
            episodes=episodes,
            rating=rating,
            country=country,
            genre=", ".join(genres) if genres else None,
            network=network,
            content_type=content_type,
            premiere_date=premiere,
            tvdb_id=tvdb_id_int,
        )

    async def _get_movie_details(self, tvdb_id: str) -> MetadataShowDetails:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await self._authed_get(client, f"/movies/{tvdb_id}/extended")
            if resp.status_code != 200:
                resp = await self._authed_get(client, f"/movies/{tvdb_id}")
            if resp.status_code != 200:
                raise ValueError(f"TheTVDB movie {tvdb_id} not found (status {resp.status_code})")
            data = resp.json().get("data", {}) or {}

            overviews_by_lang: dict[str, str] = {}
            # Поиск официального английского перевода TheTVDB
            eng_title = None
            eng_overview = None
            try:
                eng_resp = await self._authed_get(client, f"/movies/{tvdb_id}/translations/eng")
                if eng_resp.status_code == 200:
                    eng_data = eng_resp.json().get("data") or {}
                    eng_title = eng_data.get("name")
                    eng_overview = eng_data.get("overview")
                    if eng_overview and str(eng_overview).strip():
                        overviews_by_lang["en"] = str(eng_overview).strip()
            except Exception:
                pass

            # Поиск русского названия и описания в переводах
            ru_title = None
            ru_overview = None
            try:
                ru_resp = await self._authed_get(client, f"/movies/{tvdb_id}/translations/rus")
                if ru_resp.status_code == 200:
                    ru_data = ru_resp.json().get("data") or {}
                    ru_title = ru_data.get("name")
                    ru_overview = ru_data.get("overview")
                    if ru_overview and str(ru_overview).strip():
                        overviews_by_lang["ru"] = str(ru_overview).strip()
            except Exception:
                pass

            # Поиск перевода для стороннего предпочтительного языка
            norm_ov = normalize_metadata_lang_code(self.overview_language) or self.overview_language
            if norm_ov and norm_ov not in ("en", "ru", "original"):
                code_3 = _tvdb_3_letter_code(norm_ov)
                if code_3:
                    try:
                        tr_resp = await self._authed_get(client, f"/movies/{tvdb_id}/translations/{code_3}")
                        if tr_resp.status_code == 200:
                            tr_data = tr_resp.json().get("data") or {}
                            tr_ov = tr_data.get("overview")
                            if tr_ov and str(tr_ov).strip():
                                overviews_by_lang[norm_ov] = str(tr_ov).strip()
                    except Exception:
                        pass

        raw_name = (data.get("name") or "").strip()
        aliases_raw = data.get("aliases") or []

        # Выбираем наилучшее английское название для Jellyfin
        if eng_title and is_latin_text(eng_title):
            title = eng_title.strip()
        elif is_latin_text(raw_name):
            title = raw_name
        else:
            eng_alias = None
            for a in (aliases_raw if isinstance(aliases_raw, list) else []):
                a_name = (a.get("name") if isinstance(a, dict) else str(a) if a else "").strip()
                a_lang = (a.get("language") if isinstance(a, dict) else "").lower()
                if not a_name or not is_latin_text(a_name):
                    continue
                if a_lang in ("eng", "en", "usa", "gbr", "romaji", "lat"):
                    eng_alias = a_name
                    break
                elif not eng_alias:
                    eng_alias = a_name
            title = eng_alias or raw_name or ru_title or f"Movie {tvdb_id}"

        # Собираем ВСЕ алиасы для поиска торрентов на трекерах
        allowed_langs = {"en", "eng"} | {l.lower() for l in (self.alias_languages or ["ru"])}
        aliases = []
        if raw_name and raw_name != title and raw_name not in aliases:
            aliases.append(raw_name)
        if ru_title and ru_title != title and ru_title not in aliases and ("ru" in allowed_langs or "rus" in allowed_langs):
            aliases.append(ru_title)

        for a in (aliases_raw if isinstance(aliases_raw, list) else []):
            alias_name = (a.get("name") if isinstance(a, dict) else str(a) if a else "").strip()
            alias_lang = (a.get("language") if isinstance(a, dict) else "")
            if alias_name and alias_name != title and alias_name not in aliases:
                if not is_alias_allowed(alias_name, alias_lang, allowed_langs):
                    continue
                aliases.append(alias_name)

        poster = data.get("image")
        if poster and not str(poster).startswith("http"):
            poster = f"{self.ARTWORK_BASE}/{str(poster).lstrip('/')}"
        elif not poster:
            for art in (data.get("artworks") or []):
                if isinstance(art, dict) and art.get("type") in (2, "2", "poster") and art.get("image"):
                    art_img = str(art["image"])
                    poster = art_img if art_img.startswith("http") else f"{self.ARTWORK_BASE}/{art_img.lstrip('/')}"
                    break

        genres = []
        for g in (data.get("genres") or []):
            if isinstance(g, dict) and g.get("name"):
                genres.append(str(g["name"]))
            elif isinstance(g, str) and g.strip():
                genres.append(g.strip())

        country = data.get("originalCountry")
        first_rel = data.get("first_release")
        premiere = None
        if isinstance(first_rel, dict):
            premiere = first_rel.get("date")
        elif isinstance(first_rel, list) and first_rel and isinstance(first_rel[0], dict):
            premiere = first_rel[0].get("date")
        elif isinstance(first_rel, str):
            premiere = first_rel
        if not premiere:
            premiere = data.get("year") or data.get("release")
        if premiere:
            premiere = str(premiere)[:10]

        # Описание сюжета на основе предпочтительного языка с фоллбэками
        overview = select_overview(overviews_by_lang, data.get("overview"), self.overview_language)

        raw_score = data.get("score")
        rating = None
        if raw_score is not None:
            try:
                rating = float(raw_score)
            except (ValueError, TypeError):
                rating = None

        tvdb_movie_id_int = int(tvdb_id) if str(tvdb_id).isdigit() else None

        return MetadataShowDetails(
            external_id=f"movie:{tvdb_id}",
            title=title,
            aliases=aliases,
            overview=overview,
            poster_url=poster,
            episodes=[],
            rating=rating,
            country=country,
            genre=", ".join(genres) if genres else None,
            network=None,
            content_type="movie",
            premiere_date=premiere,
        )


class DummyClient(BaseMetadataClient):
    async def search(self, query: str) -> list[MetadataResult]:
        return []
    async def get_details(self, external_id: str) -> MetadataShowDetails:
        raise NotImplementedError("Этот источник устарел и больше не поддерживается.")


def get_metadata_client(source_row, overview_language: Optional[str] = None, title_language: Optional[str] = None) -> BaseMetadataClient:
    """source_row: модель MetadataSource из БД."""
    type_value = source_row.type.value if hasattr(source_row.type, "value") else str(source_row.type)
    
    # Извлекаем alias_languages, alias_countries и pin из field_mapping
    alias_languages = None
    alias_countries = None
    pin = ""
    if isinstance(source_row.field_mapping, dict):
        alias_languages = source_row.field_mapping.get("alias_languages")
        alias_countries = source_row.field_mapping.get("alias_countries")
        pin = source_row.field_mapping.get("pin", "")
    
    ov_lang = overview_language or "ru"
    t_lang = title_language or "ru"
    if type_value in ("skyhook", "sonarr"):
        return SkyHookClient(source_row.api_key or "", alias_countries=alias_countries, base_url=source_row.base_url or "", alias_languages=alias_languages, overview_language=ov_lang, title_language=t_lang)
    elif type_value in ("radarr", "radarr_skyhook"):
        return RadarrClient(source_row.api_key or "", alias_countries=alias_countries, base_url=source_row.base_url or "", alias_languages=alias_languages, overview_language=ov_lang, title_language=t_lang)
    elif type_value == "tmdb":
        return TMDBClient(source_row.api_key or "", alias_countries=alias_countries, alias_languages=alias_languages, overview_language=ov_lang, title_language=t_lang)
    elif type_value == "tvmaze":
        return TVMazeClient(source_row.api_key or "", alias_countries)
    elif type_value == "thetvdb":
        return TheTVDBClient(source_row.api_key or "", pin=pin, alias_countries=alias_countries, base_url=source_row.base_url or "", alias_languages=alias_languages, overview_language=ov_lang, title_language=t_lang)
    return DummyClient()



async def refresh_show_release_dates(db, show, override_source_type: Optional[str] = None) -> bool:
    """
    Запрос к источнику метаданных для получения актуальных дат выхода серий и фильмов.
    Используется как при ручном обновлении из календаря, так и в периодической фоновой задаче.

    override_source_type: если задан — переопределяет источник данных (например, skyhook или radarr).
    Возвращает True, если даты были обновлены.
    """
    import datetime as _dt

    from app.models.db import Episode, EpisodeStatus, MetadataSource

    if not show.metadata_id:
        return False

    # Выбираем источник метаданных для календаря:
    # По умолчанию для фильмов используется Radarr Movie Cloud, а для сериалов/аниме — Sonarr SkyHook Proxy.
    default_src = "radarr" if show.content_type == "movie" else "skyhook"
    source_type = default_src

    if override_source_type and override_source_type != "auto":
        if show.content_type == "movie":
            if override_source_type in ("radarr", "tmdb"):
                source_type = override_source_type
        else:
            if override_source_type in ("skyhook", "sonarr", "thetvdb", "tvmaze", "tmdb"):
                source_type = override_source_type
    elif show.metadata_source:
        source_type = show.metadata_source

    source = (
        db.query(MetadataSource)
        .filter(MetadataSource.type == source_type, MetadataSource.enabled == True)  # noqa: E712
        .first()
    )
    if not source and show.metadata_source and show.metadata_source != source_type:
        source = (
            db.query(MetadataSource)
            .filter(MetadataSource.type == show.metadata_source, MetadataSource.enabled == True)  # noqa: E712
            .first()
        )

    client = None
    if source:
        client = get_metadata_client(source)
    else:
        # Прямой клиент по умолчанию (без необходимости создания записи в БД)
        if source_type in ("radarr", "radarr_skyhook") or show.content_type == "movie":
            client = RadarrClient()
        elif source_type in ("skyhook", "sonarr"):
            client = SkyHookClient()
        elif source_type == "tvmaze":
            client = TVMazeClient()
        elif source_type == "thetvdb":
            client = TheTVDBClient()
        elif source_type == "tmdb":
            client = TMDBClient()

    if not client:
        return False

    details = None
    try:
        details = await client.get_details(show.metadata_id)
    except Exception as e:
        logger.debug("Failed getting details from client %s: %s", type(client).__name__, e)
        # При ошибке пробуем запасной шлюз
        if show.content_type == "movie" and not isinstance(client, RadarrClient):
            try:
                details = await RadarrClient().get_details(show.metadata_id)
            except Exception:
                pass
        elif show.content_type != "movie" and not isinstance(client, SkyHookClient):
            try:
                details = await SkyHookClient().get_details(show.metadata_id)
            except Exception:
                pass

    if not details:
        return False


    now = _dt.datetime.utcnow()
    changed = False

    def _parse_date(raw):
        if not raw:
            return None
        if isinstance(raw, _dt.datetime):
            return raw
        try:
            return _dt.datetime.fromisoformat(str(raw)[:10])
        except ValueError:
            return None

    new_premiere = _parse_date(details.premiere_date)
    if new_premiere and new_premiere != show.premiere_date:
        show.premiere_date = new_premiere
        changed = True

    if show.content_type == "movie":
        episode = db.query(Episode).filter(Episode.show_id == show.id).order_by(Episode.id).first()
        if episode and new_premiere:
            already_released = new_premiere <= now
            new_air_date = None if already_released else new_premiere
            if episode.air_date != new_air_date:
                episode.air_date = new_air_date
                # Скачанный или игнорируемый фильм остаётся таким, даже если у источника
                # сдвинулась дата премьеры: иначе он снова уходил в поиск и перекачивался.
                has_file = episode.status == EpisodeStatus.DOWNLOADED or bool(getattr(episode, "file_path", None))
                if not has_file and episode.status != EpisodeStatus.IGNORED:
                    episode.status = EpisodeStatus.UNAIRED if not already_released else EpisodeStatus.WANTED
                db.add(episode)
                changed = True
    else:
        # Сериалы и аниме. Раньше этот цикл по ошибке находился внутри ветки фильмов,
        # и опрос календаря никогда не обновлял даты выхода серий.
        future_seasons = set()
        for me in details.episodes:
            mad = _parse_date(me.air_date)
            ms = me.season_number if me.season_number is not None else 1
            if mad and mad > now:
                future_seasons.add(ms)

        seen_added_keys = set()
        for meta_ep in details.episodes:
            if meta_ep.episode_number is None:
                continue
            s_num = meta_ep.season_number if meta_ep.season_number is not None else 1
            e_num = meta_ep.episode_number
            ep_key = (s_num, e_num)
            if ep_key in seen_added_keys:
                continue

            air_date = _parse_date(meta_ep.air_date)
            is_unaired = bool(
                (air_date and air_date > now)
                or (air_date is None and (s_num in future_seasons or (show.premiere_date and show.premiere_date > now)))
            )
            episode = (
                db.query(Episode)
                .filter(
                    Episode.show_id == show.id,
                    Episode.season_number == s_num,
                    Episode.episode_number == e_num,
                )
                .first()
            )
            if episode:
                if meta_ep.absolute_number is not None and episode.absolute_number != meta_ep.absolute_number:
                    episode.absolute_number = meta_ep.absolute_number
                    changed = True
                if meta_ep.title and episode.title != meta_ep.title:
                    episode.title = meta_ep.title
                    changed = True
                if air_date and episode.air_date != air_date:
                    episode.air_date = air_date
                    changed = True
                if is_unaired and episode.status not in (EpisodeStatus.IGNORED, EpisodeStatus.DOWNLOADED) and not getattr(episode, "file_path", None):
                    # Мониторинг существующих серий не трогаем: пользователь мог снять
                    # его намеренно, а обновление метаданных идёт каждые несколько часов.
                    if episode.status != EpisodeStatus.UNAIRED:
                        episode.status = EpisodeStatus.UNAIRED
                        changed = True
                elif air_date and episode.status in (EpisodeStatus.MISSING, EpisodeStatus.WANTED, EpisodeStatus.UNAIRED):
                    target_status = EpisodeStatus.UNAIRED if air_date > now else EpisodeStatus.WANTED
                    if episode.status != target_status:
                        episode.status = target_status
                        changed = True
                db.add(episode)
            elif e_num:
                seen_added_keys.add(ep_key)
                status = EpisodeStatus.UNAIRED if is_unaired else EpisodeStatus.WANTED
                monitored = True if is_unaired else getattr(show, "monitored", True)
                db.add(Episode(
                    show_id=show.id,
                    season_number=s_num,
                    episode_number=e_num,
                    absolute_number=meta_ep.absolute_number,
                    title=meta_ep.title,
                    air_date=air_date,
                    status=status,
                    monitored=monitored,
                ))
                changed = True

    if changed:
        show.calendar_waiting_dismissed = False  # раз дата нашлась — не прячем от календаря
        db.add(show)
        db.commit()
    return changed


async def resolve_show_cover(show, db=None) -> tuple[Optional[str], Optional[str]]:
    """
    Поиск актуального постера для карточки из соответствующего поставщика метаданных:
    - Фильмы (content_type == 'movie' или category == 'movies') -> RadarrClient / TMDB
    - Сериалы и аниме -> SkyHookClient (Sonarr) / TheTVDB / TVMaze
    Возвращает кортеж (poster_url, source_name).
    """
    is_movie = getattr(show, "content_type", None) == "movie" or getattr(show, "category", None) == "movies"
    query = (getattr(show, "title", None) or "").strip()
    metadata_id = getattr(show, "metadata_id", None)
    if not query and metadata_id:
        query = str(metadata_id).strip()

    if not query:
        return None, None

    if is_movie:
        # 1. Поиск для фильма: сначала официальный Radarr SkyHook
        radarr = RadarrClient()
        if metadata_id and (str(metadata_id).startswith(("movie:", "radarr:", "tmdb:")) or str(metadata_id).isdigit()):
            try:
                det = await radarr.get_details(str(metadata_id))
                if det and det.poster_url:
                    return det.poster_url, "Radarr SkyHook (Movie Cloud)"
            except Exception:
                pass

        if query:
            try:
                results = await radarr.search(query)
                found = next((r for r in results if r.poster_url and (not r.content_type or r.content_type == "movie")), None)
                if found and found.poster_url:
                    return found.poster_url, "Radarr SkyHook (Movie Cloud)"
            except Exception:
                pass

        # 2. Если не найден в Radarr — пробуем активные источники TMDB из БД
        if db is not None:
            try:
                from app.models.db import MetadataSource
                tmdb_sources = db.query(MetadataSource).filter(
                    MetadataSource.enabled == True,
                    MetadataSource.type == "tmdb",
                ).all()
                for s in tmdb_sources:
                    try:
                        client = get_metadata_client(s)
                        results = await client.search(query)
                        found = next((r for r in results if r.poster_url and (not r.content_type or r.content_type == "movie")), None)
                        if found and found.poster_url:
                            return found.poster_url, s.name
                    except Exception:
                        pass
            except Exception:
                pass

    else:
        # 1. Поиск для сериала/аниме: сначала официальный Sonarr SkyHook
        skyhook = SkyHookClient()
        if metadata_id and (str(metadata_id).startswith(("tvdb:", "sonarr:", "skyhook:")) or str(metadata_id).isdigit()):
            try:
                det = await skyhook.get_details(str(metadata_id))
                if det and det.poster_url:
                    return det.poster_url, "Sonarr SkyHook"
            except Exception:
                pass

        if query:
            try:
                results = await skyhook.search(query)
                found = next((r for r in results if r.poster_url and (not r.content_type or r.content_type != "movie")), None)
                if found and found.poster_url:
                    return found.poster_url, "Sonarr SkyHook"
            except Exception:
                pass

        # 2. Если не найден в Skyhook — пробуем остальные сериальные источники из БД
        if db is not None:
            try:
                from app.models.db import MetadataSource
                tv_sources = db.query(MetadataSource).filter(
                    MetadataSource.enabled == True,
                    MetadataSource.type.in_(["thetvdb", "tvmaze", "tmdb"]),
                ).all()
                for s in tv_sources:
                    try:
                        client = get_metadata_client(s)
                        results = await client.search(query)
                        found = next((r for r in results if r.poster_url and (not r.content_type or r.content_type != "movie")), None)
                        if found and found.poster_url:
                            return found.poster_url, s.name
                    except Exception:
                        pass
            except Exception:
                pass

    return None, None


async def refresh_show_metadata(db, show) -> dict:
    """
    Полное обновление метаданных тайтла из SkyHook (Sonarr/Radarr) / TVDB / TMDB / TVMaze:
    - Обновление названий всех серий (замена Episode X / TBA на официальные имена).
    - Обновление дат премьеры/выхода (кинотеатр, цифровой релиз, эфир).
    - Добавление новых анонсированных серий и сезонов.
    - Обновление абсолютных номеров серий (для аниме).
    - Обновление синопсиса (overview), постера, жанров, студии, года, статуса.
    - Добавление новых локализованных алиасов.
    """
    import datetime as _dt

    is_movie = getattr(show, "content_type", None) == "movie" or getattr(show, "category", None) == "movies"
    metadata_id = getattr(show, "metadata_id", None)
    title = (getattr(show, "title", None) or "").strip()
    # 0. Загружаем глобальную настройку языка описания (синопсиса)
    app_settings = None
    if db:
        try:
            from app.models.db import AppSettings as _AppSettingsModel
            app_settings = db.query(_AppSettingsModel).filter(getattr(_AppSettingsModel, "id", None) == 1).first()
        except Exception:
            app_settings = None
    overview_lang = getattr(app_settings, "metadata_overview_language", "ru") if app_settings else "ru"
    overview_lang = overview_lang or "ru"

    # 1. Разрешаем клиент источника метаданных
    client = None
    source = None
    if is_movie:
        source = (
            db.query(MetadataSource)
            .filter(
                MetadataSource.type.in_(["radarr", getattr(MetadataSourceType, "RADARR", "radarr")]),
                MetadataSource.enabled == True,
            )
            .first()
        )
        if source:
            try:
                client = get_metadata_client(source, overview_language=overview_lang)
            except Exception:
                client = None
    elif getattr(show, "metadata_source", None):
        source = (
            db.query(MetadataSource)
            .filter(MetadataSource.type == show.metadata_source, MetadataSource.enabled == True)  # noqa: E712
            .first()
        )
        if source:
            try:
                client = get_metadata_client(source, overview_language=overview_lang)
            except Exception:
                client = None

    alias_langs = None
    if source and isinstance(source.field_mapping, dict):
        alias_langs = source.field_mapping.get("alias_languages")
    if not alias_langs:
        for s in db.query(MetadataSource).filter(MetadataSource.enabled == True).all():
            if is_movie and s.type not in ("radarr", getattr(MetadataSourceType, "RADARR", "radarr")):
                continue
            if isinstance(s.field_mapping, dict) and s.field_mapping.get("alias_languages"):
                alias_langs = s.field_mapping["alias_languages"]
                break

    if not client:
        client = RadarrClient(alias_languages=alias_langs, overview_language=overview_lang) if is_movie else SkyHookClient(alias_languages=alias_langs, overview_language=overview_lang)

    fallback_client = RadarrClient(alias_languages=alias_langs, overview_language=overview_lang) if is_movie else SkyHookClient(alias_languages=alias_langs, overview_language=overview_lang)
    details = None

    # 2. Пробуем получить детали по metadata_id
    if metadata_id:
        try:
            details = await client.get_details(str(metadata_id))
        except Exception as e:
            logger.debug("Failed to get details by metadata_id %s with %s for %s: %s", metadata_id, type(client).__name__, title, e)

        if not details and client != fallback_client:
            try:
                details = await fallback_client.get_details(str(metadata_id))
            except Exception as e:
                logger.debug("Fallback client details failed for %s: %s", title, e)

        # Валидируем, что полученные по ID детали действительно соответствуют нашему тайтлу
        if details:
            aliases_list = [a.text for a in getattr(show, "aliases", []) or [] if getattr(a, "text", None)]
            det_score = calc_metadata_match_score(details, title, getattr(show, "year", None), aliases_list)
            if det_score < 0.50:
                logger.warning(
                    "Детали по metadata_id=%s ('%s', %s) не соответствуют тайтлу '%s' (%s, score=%.2f). Отклоняем неверный ID.",
                    metadata_id, details.title, details.year, title, getattr(show, "year", None), det_score,
                )
                details = None

    # 3. Если по metadata_id детали не получены — ищем по названию и алиасам со СТРОГОЙ валидацией
    if not details:
        search_candidates = []
        if title:
            search_candidates.append(title)
            for sep in (":", "—", " - "):
                if sep in title:
                    base_part = title.split(sep)[0].strip()
                    if base_part and base_part not in search_candidates:
                        search_candidates.append(base_part)

        aliases_list = [a.text for a in getattr(show, "aliases", []) or [] if getattr(a, "text", None)]
        if getattr(show, "aliases", None):
            en_aliases = [
                a.text.strip() for a in show.aliases
                if a.text and getattr(a, "language", None) in (AliasLanguage.EN, "en", "romaji", "jp")
            ]
            for ea in en_aliases:
                if ea and ea not in search_candidates:
                    search_candidates.insert(0, ea)
            for a in show.aliases:
                at = a.text.strip() if a.text else ""
                if at and at not in search_candidates:
                    search_candidates.append(at)

        for candidate in search_candidates:
            if not candidate:
                continue
            for cl in (client, fallback_client):
                try:
                    results = await cl.search(candidate)
                    if results:
                        # Ищем только кандидатов, прошедших порог уверенности (score >= 0.75)
                        best_cand = None
                        best_score = 0.0
                        for r in results:
                            # Проверяем совместимость типа контента
                            if is_movie and r.content_type and r.content_type not in ("movie",):
                                continue
                            if not is_movie and r.content_type == "movie":
                                continue

                            score = calc_metadata_match_score(r, title, getattr(show, "year", None), aliases_list)
                            if score >= 0.75 and score > best_score:
                                best_score = score
                                best_cand = r

                        if best_cand:
                            ext_id = best_cand.external_id or ""
                            if ext_id:
                                det = await cl.get_details(str(ext_id))
                                if det:
                                    det_score = calc_metadata_match_score(det, title, getattr(show, "year", None), aliases_list)
                                    if det_score >= 0.70:
                                        details = det
                                        break
                except Exception as e:
                    logger.debug("Search candidate '%s' failed on %s: %s", candidate, type(cl).__name__, e)
            if details:
                break

    if not details:
        return {"updated": False, "show_id": show.id, "title": show.title, "reason": "No confident metadata match found"}

    now = _dt.datetime.utcnow()
    changed = False
    episodes_updated = 0
    episodes_added = 0

    def _parse_date(raw):
        if not raw:
            return None
        if isinstance(raw, _dt.datetime):
            return raw
        try:
            return _dt.datetime.fromisoformat(str(raw)[:10])
        except ValueError:
            return None

    # Привязываем актуальный metadata_id, если он не был задан или обновился
    if details.external_id and show.metadata_id != details.external_id:
        show.metadata_id = details.external_id
        changed = True
    if not show.metadata_source or (is_movie and show.metadata_source not in ("radarr", "tmdb")):
        show.metadata_source = "radarr" if is_movie else "skyhook"
        changed = True

    # 4. Обновляем основные атрибуты тайтла
    if getattr(details, "overview", None) and show.overview != details.overview:
        show.overview = details.overview
        changed = True
    if getattr(details, "poster_url", None):
        det_poster = str(details.poster_url).strip()
        from app.services.cover_service import download_and_store_show_cover, get_show_poster_path
        if getattr(show, "poster_source_url", None) != det_poster or not os.path.isfile(get_show_poster_path(show.id)):
            if det_poster.startswith(("http://", "https://")):
                show.poster_source_url = det_poster
            local_url = await download_and_store_show_cover(show.id, det_poster)
            target_url = local_url or f"/api/v1/shows/{show.id}/poster"
            if show.poster_url != target_url:
                show.poster_url = target_url
                changed = True
        elif not show.poster_url or str(show.poster_url).startswith(("http://", "https://")):
            show.poster_url = f"/api/v1/shows/{show.id}/poster"
            changed = True
    if getattr(details, "rating", None) and show.rating != details.rating:
        show.rating = details.rating
        changed = True
    if getattr(details, "genre", None) and show.genre != details.genre:
        show.genre = details.genre
        changed = True
    if getattr(details, "network", None) and show.network != details.network:
        show.network = details.network
        changed = True
    if getattr(details, "year", None) and show.year != details.year:
        show.year = details.year
        changed = True

    new_premiere = _parse_date(details.premiere_date)
    if new_premiere and show.premiere_date != new_premiere:
        show.premiere_date = new_premiere
        changed = True

    new_in_cinemas = _parse_date(getattr(details, "in_cinemas_date", None))
    if new_in_cinemas and getattr(show, "in_cinemas_date", None) != new_in_cinemas:
        show.in_cinemas_date = new_in_cinemas
        changed = True

    new_digital = _parse_date(getattr(details, "digital_release_date", None))
    if new_digital and getattr(show, "digital_release_date", None) != new_digital:
        show.digital_release_date = new_digital
        changed = True

    new_physical = _parse_date(getattr(details, "physical_release_date", None))
    if new_physical and getattr(show, "physical_release_date", None) != new_physical:
        show.physical_release_date = new_physical
        changed = True

    # Movie Collection auto-link/creation
    coll_tmdb_id = getattr(details, "collection_tmdb_id", None)
    coll_name = getattr(details, "collection_name", None)
    if is_movie and (coll_tmdb_id or coll_name):
        try:
            from app.models.db import MovieCollection
            coll = None
            if coll_tmdb_id:
                coll = db.query(MovieCollection).filter(MovieCollection.tmdb_collection_id == coll_tmdb_id).first()
            if not coll and coll_name:
                coll = db.query(MovieCollection).filter(MovieCollection.title == coll_name).first()
            if not coll and coll_name:
                coll = MovieCollection(
                    tmdb_collection_id=coll_tmdb_id,
                    title=coll_name,
                    overview=getattr(details, "collection_overview", None),
                    poster_url=getattr(details, "collection_poster_url", None),
                    backdrop_url=getattr(details, "collection_backdrop_url", None),
                )
                db.add(coll)
                db.flush()
            if coll and coll.tmdb_collection_id and hasattr(client, "get_collection_details"):
                if not getattr(coll, "parts_cache", None) or coll.parts_count is None:
                    try:
                        from app.models.db import AppSettings
                        app_settings = db.query(AppSettings).filter(getattr(AppSettings, "id", None) == 1).first()
                        c_lang = getattr(app_settings, "metadata_collection_title_language", "ru") if app_settings else "ru"
                        c_lang = (c_lang or "ru").strip().lower()

                        c_det = await client.get_collection_details(coll.tmdb_collection_id, lang=c_lang)
                        if c_det and c_det.get("parts"):
                            import json
                            coll.parts_count = len(c_det["parts"])
                            coll.parts_cache = json.dumps(c_det["parts"], ensure_ascii=False)
                            coll.last_metadata_refresh_at = dt.datetime.utcnow()
                            if c_det.get("overview"):
                                coll.overview = c_det.get("overview")
                            
                            tbl = c_det.get("titles_by_lang") or {}
                            if tbl:
                                coll.titles_cache = json.dumps(tbl, ensure_ascii=False)
                            
                            pref_title = None
                            if c_lang in ("ru", "rus"):
                                pref_title = tbl.get("ru") or (c_det.get("name") if any('\u0400' <= ch <= '\u04ff' for ch in (c_det.get("name") or "")) else None)
                            elif c_lang in ("en", "eng"):
                                pref_title = tbl.get("en")
                            else:
                                pref_title = tbl.get(c_lang)
                            if pref_title and pref_title.strip():
                                coll.title = pref_title.strip()
                            elif c_det.get("name") and not coll.title:
                                coll.title = c_det.get("name").strip()

                            if c_det.get("poster_url"):
                                coll.poster_source_url = c_det.get("poster_url")
                                from app.services.cover_service import download_and_store_collection_cover
                                c_loc = await download_and_store_collection_cover(coll.id, c_det.get("poster_url"))
                                coll.poster_url = c_loc or c_det.get("poster_url")
                            if c_det.get("backdrop_url"):
                                coll.backdrop_source_url = c_det.get("backdrop_url")
                                from app.services.cover_service import download_and_store_collection_backdrop
                                b_loc = await download_and_store_collection_backdrop(coll.id, c_det.get("backdrop_url"))
                                coll.backdrop_url = b_loc or c_det.get("backdrop_url")
                            db.add(coll)
                    except Exception as e:
                        logger.debug("Failed to prefetch collection parts for %s: %s", coll.title, e)
            if coll and show.collection_id != coll.id:
                show.collection_id = coll.id
                changed = True
            if coll and getattr(details, "collection_order", None) is not None and show.collection_order != details.collection_order:
                show.collection_order = details.collection_order
                changed = True
        except Exception as e:
            logger.debug("Failed to link movie collection for %s: %s", show.title, e)

    # 5. Обновляем серии
    if is_movie:
        ep = db.query(Episode).filter(Episode.show_id == show.id).order_by(Episode.id).first()
        if ep:
            if details.title and ep.title != details.title:
                ep.title = details.title
                changed = True
            if new_premiere:
                already_released = new_premiere <= now
                new_air_date = None if already_released else new_premiere
                if ep.air_date != new_air_date:
                    ep.air_date = new_air_date
                    if ep.status in (EpisodeStatus.UNAIRED, EpisodeStatus.MISSING, EpisodeStatus.WANTED):
                        ep.status = EpisodeStatus.UNAIRED if not already_released else EpisodeStatus.WANTED
                    db.add(ep)
                    changed = True
                    episodes_updated += 1
        elif new_premiere or details.title:
            already_released = bool(new_premiere and new_premiere <= now)
            status = EpisodeStatus.UNAIRED if (new_premiere and new_premiere > now) else EpisodeStatus.WANTED
            db.add(Episode(
                show_id=show.id,
                season_number=1,
                episode_number=1,
                title=details.title or show.title,
                air_date=None if already_released else new_premiere,
                status=status,
            ))
            changed = True
            episodes_added += 1
    else:
        if details.episodes:
            future_seasons = set()
            for me in details.episodes:
                mad = _parse_date(me.air_date)
                ms = me.season_number if me.season_number is not None else 1
                if mad and mad > now:
                    future_seasons.add(ms)

            seen_added_keys = set()
            for meta_ep in details.episodes:
                if meta_ep.episode_number is None:
                    continue
                s_num = meta_ep.season_number if meta_ep.season_number is not None else 1
                e_num = meta_ep.episode_number
                ep_key = (s_num, e_num)
                if ep_key in seen_added_keys:
                    continue

                air_date = _parse_date(meta_ep.air_date)
                is_unaired = bool(
                    (air_date and air_date > now)
                    or (air_date is None and (s_num in future_seasons or (show.premiere_date and show.premiere_date > now)))
                )
                
                # Очищаем заглушки названий
                raw_ep_title = (meta_ep.title or "").strip()
                if raw_ep_title in ("None", "null", "TBA", "tba", ""):
                    raw_ep_title = None

                episode = (
                    db.query(Episode)
                    .filter(
                        Episode.show_id == show.id,
                        Episode.season_number == s_num,
                        Episode.episode_number == e_num,
                    )
                    .first()
                )
                
                # Для аниме fallback поиск по абсолютному номеру, если по сезону/эпизоду не нашлось
                if not episode and getattr(meta_ep, "absolute_number", None) is not None and getattr(show, "content_type", None) == "anime":
                    episode = (
                        db.query(Episode)
                        .filter(
                            Episode.show_id == show.id,
                            Episode.absolute_number == meta_ep.absolute_number,
                        )
                        .first()
                    )

                if episode:
                    ep_changed = False
                    # Обновляем название, если в метаданных появилось нормальное имя
                    if raw_ep_title and episode.title != raw_ep_title:
                        episode.title = raw_ep_title
                        ep_changed = True
                    elif not raw_ep_title and (not episode.title or episode.title.strip().lower().startswith(("episode ", "серия "))):
                        episode.title = "TBA"
                        ep_changed = True
                    if air_date and episode.air_date != air_date:
                        episode.air_date = air_date
                        ep_changed = True
                    if is_unaired and episode.status not in (EpisodeStatus.IGNORED, EpisodeStatus.DOWNLOADED) and not getattr(episode, "file_path", None):
                        # Мониторинг существующих серий не трогаем (см. выше).
                        if episode.status != EpisodeStatus.UNAIRED:
                            episode.status = EpisodeStatus.UNAIRED
                            ep_changed = True
                    elif air_date and episode.status in (EpisodeStatus.MISSING, EpisodeStatus.WANTED, EpisodeStatus.UNAIRED):
                        target_status = EpisodeStatus.UNAIRED if air_date > now else EpisodeStatus.WANTED
                        if episode.status != target_status:
                            episode.status = target_status
                            ep_changed = True
                    if meta_ep.absolute_number is not None and episode.absolute_number != meta_ep.absolute_number:
                        episode.absolute_number = meta_ep.absolute_number
                        ep_changed = True
                    if ep_changed:
                        db.add(episode)
                        changed = True
                        episodes_updated += 1
                elif e_num:
                    seen_added_keys.add(ep_key)
                    status = EpisodeStatus.UNAIRED if is_unaired else EpisodeStatus.WANTED
                    monitored = True if is_unaired else getattr(show, "monitored", True)
                    db.add(Episode(
                        show_id=show.id,
                        season_number=s_num,
                        episode_number=e_num,
                        absolute_number=meta_ep.absolute_number,
                        title=raw_ep_title or "TBA",
                        air_date=air_date,
                        status=status,
                        monitored=monitored,
                    ))
                    changed = True
                    episodes_added += 1

    # 6. Обновляем алиасы
    refresh_aliases_enabled = True
    try:
        from app.services.settings_service import get_or_create_settings
        settings = get_or_create_settings(db)
        refresh_aliases_enabled = getattr(settings, "metadata_refresh_aliases", True)
    except Exception:
        pass
    allowed_langs = get_allowed_metadata_languages(db, show)

    show_aliases = list(getattr(show, "aliases", None) or [])
    if refresh_aliases_enabled and details.aliases:
        existing_aliases = {a.text.lower().strip() for a in show_aliases}
        cur_max_p = max([a.priority for a in show_aliases if getattr(a, "priority", None) is not None] or [0])
        for alias_text in details.aliases:
            clean_alias = str(alias_text).strip()
            if clean_alias and clean_alias.lower() not in existing_aliases:
                # Строгая проверка разрешенных языков
                if not is_alias_allowed(clean_alias, None, allowed_langs):
                    continue
                existing_aliases.add(clean_alias.lower())
                cur_max_p += 1
                det_lang = detect_alias_language(clean_alias)
                db.add(Alias(
                    show_id=show.id,
                    text=clean_alias,
                    language=det_lang,
                    source="radarr" if is_movie else "skyhook",
                    priority=cur_max_p,
                ))
                changed = True

    # Очистка неактуальных авто-алиасов тайтла (если включено обновление алиасов)
    if refresh_aliases_enabled:
        for a in show_aliases:
            if getattr(a, "source", None) != "manual" and (getattr(a, "text", "") or "").strip().lower() != (show.title or "").strip().lower():
                if not is_alias_allowed(getattr(a, "text", ""), getattr(a, "language", None), allowed_langs):
                    db.delete(a)
                    changed = True

    show.last_metadata_refresh_at = now
    if changed:
        show.calendar_waiting_dismissed = False
        db.add(show)

    db.commit()
    db.refresh(show)

    try:
        from app.services.blocklist_service import relink_blocklist_for_show
        relink_blocklist_for_show(db, show)
    except Exception as exc:
        logger.debug("Ошибка связывания черного списка для шоу %s: %s", show.id, exc)

    return {
        "updated": changed,
        "show_id": show.id,
        "title": show.title,
        "episodes_updated": episodes_updated,
        "episodes_added": episodes_added,
    }


_REFRESHING_SHOW_IDS: set[int] = set()
_REFRESHING_LOCK = threading.Lock()


async def _bg_refresh_show_task(show_id: int):
    with _REFRESHING_LOCK:
        if show_id in _REFRESHING_SHOW_IDS:
            return
        _REFRESHING_SHOW_IDS.add(show_id)
    try:
        from app.database import SessionLocal
        from app.models.db import Show
        bg_db = SessionLocal()
        try:
            show = bg_db.get(Show, show_id)
            if show:
                await refresh_show_metadata(bg_db, show)
        finally:
            bg_db.close()
    except Exception as e:
        logger.debug("Background metadata refresh failed for show %s: %s", show_id, e)
    finally:
        with _REFRESHING_LOCK:
            _REFRESHING_SHOW_IDS.discard(show_id)


def trigger_show_metadata_refresh_if_needed(show_id: int, db: Session) -> None:
    """
    Проверяет необходимость обновления метаданных по правилам Sonarr/Radarr
    и запускает асинхронную фоновую задачу БЕЗ блокировки текущего HTTP-запроса и транзакции БД.
    """
    try:
        from app.models.db import Show
        show = db.get(Show, show_id)
        if not show or not should_refresh_show(show, db):
            return

        with _REFRESHING_LOCK:
            if show_id in _REFRESHING_SHOW_IDS:
                return

        import asyncio
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_bg_refresh_show_task(show_id))
        except RuntimeError:
            t = threading.Thread(target=lambda: asyncio.run(_bg_refresh_show_task(show_id)), daemon=True)
            t.start()
    except Exception as e:
        logger.debug("trigger_show_metadata_refresh_if_needed error for show %s: %s", show_id, e)


def sync_refresh_show_metadata(db, show) -> dict:
    """Синхронный запуск refresh_show_metadata для вызова из синхронных эндпоинтов/тестов."""
    import asyncio
    import concurrent.futures
    try:
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    return pool.submit(asyncio.run, refresh_show_metadata(db, show)).result()
            else:
                return loop.run_until_complete(refresh_show_metadata(db, show))
        except RuntimeError:
            return asyncio.run(refresh_show_metadata(db, show))
    except Exception as e:
        logger.debug("sync_refresh_show_metadata failed: %s", e)
        return {"updated": False, "error": str(e)}


def should_refresh_show(show, db, force: bool = False) -> bool:
    """
    Точная реализация ShouldRefreshSeries (Sonarr) и ShouldRefreshMovie (Radarr):
    - force == True: всегда True
    - Если show.last_metadata_refresh_at отсутствует: всегда True
    - Для сериалов и аниме (Sonarr):
      1. Прошло >30 дней с последней синхронизации -> True
      2. Есть хотя бы одна серия с плейсхолдером (Episode X, Серия X, TBA, None, пустой title) -> True
      3. Сериал продолжается (status != 'ended') и прошло >=6 часов -> True
      4. Последняя вышедшая серия вышла менее 30 дней назад или еще не вышла -> True
      5. Прошло <6 часов -> False
    - Для фильмов (Radarr):
      1. Прошло >180 дней -> True
      2. Прошло <12 часов -> False
      3. Статус фильма 'announced' или 'in_cinemas' -> True
      4. Премьера/релиз был менее 30 дней назад или еще в будущем -> True
    """
    if force or not getattr(show, "last_metadata_refresh_at", None):
        return True

    import datetime as _dt
    now = _dt.datetime.utcnow()
    last_sync = show.last_metadata_refresh_at

    # Защита от спама/зацикливания: если синхронизация была менее 15 минут назад, повторно не запрашиваем
    if last_sync >= now - _dt.timedelta(minutes=15):
        return False

    is_movie = getattr(show, "content_type", None) == "movie" or getattr(show, "category", None) == "movies"

    if is_movie:
        # Radarr ShouldRefreshMovie:
        if last_sync < now - _dt.timedelta(days=180):
            return True
        if last_sync >= now - _dt.timedelta(hours=12):
            return False
        st = (getattr(show, "status", None) or "").lower()
        if st in ("announced", "in_cinemas", "incinemas"):
            return True
        if show.premiere_date and show.premiere_date >= now - _dt.timedelta(days=30):
            return True
        return False
    else:
        # Sonarr ShouldRefreshSeries:
        if last_sync < now - _dt.timedelta(days=30):
            return True

        episodes = db.query(Episode).filter(Episode.show_id == show.id).all()
        has_placeholders = any(
            (not getattr(ep, "title", None)) or
            str(ep.title).strip().lower() in ("tba", "none", "null", "unknown", "") or
            str(ep.title).strip().lower().startswith(("episode ", "серия "))
            for ep in episodes
        )
        if has_placeholders and last_sync <= now - _dt.timedelta(minutes=30):
            return True

        st = (getattr(show, "status", None) or "").lower()
        if st != "ended" and last_sync < now - _dt.timedelta(hours=6):
            return True

        aired_episodes = [ep for ep in episodes if isinstance(getattr(ep, "air_date", None), _dt.datetime)]
        if aired_episodes:
            max_air_date = max(ep.air_date for ep in aired_episodes)
            if max_air_date > now - _dt.timedelta(days=30):
                return True

        if last_sync >= now - _dt.timedelta(hours=6):
            return False

        return False


async def refresh_all_shows_metadata(
    db=None,
    force: bool = False,
    username: str = "system",
    task_handle=None,
) -> dict:
    """
    Фоновое регулярное обновление метаданных для библиотеки по алгоритму Sonarr/Radarr.
    Автоматически обновляет тайтлы, требующие синхронизации (невышедшие серии, TBA/Episode N, активные онгоинги).
    Отслеживается в task_manager и отображается в виджете фоновых операций.
    """
    from app.models.db import Show
    from app.services.audit_service import log_audit
    from app.services.task_manager import task_manager
    from app.database import SessionLocal

    needs_close = False
    init_db = db
    if init_db is None:
        init_db = SessionLocal()
        needs_close = True

    try:
        all_shows = init_db.query(Show).all()
        if not all_shows:
            return {"total": 0, "updated": 0, "message": "Библиотека пуста"}

        candidate_shows = [s for s in all_shows if should_refresh_show(s, init_db, force=force)]
    finally:
        if needs_close:
            init_db.close()
            init_db = None

    if not candidate_shows:
        logger.debug("Все %d тайтлов имеют актуальные метаданные (Sonarr/Radarr rate-limit). Пропуск.", len(all_shows))
        return {"total": len(all_shows), "updated": 0, "message": "Все метаданные актуальны"}

    task = task_handle or task_manager.start_task(
        name="metadata_refresh",
        title="Обновление метаданных библиотеки",
        message=f"Подготовка к обновлению {len(candidate_shows)} тайтлов...",
        total_items=len(candidate_shows),
        current_item=0,
    )

    updated_count = 0
    errors_count = 0

    try:
        from app.database import SessionLocal
        for i, show in enumerate(candidate_shows):
            if not task_manager.is_active(task.id):
                return {
                    "total": len(candidate_shows),
                    "updated": updated_count,
                    "errors": errors_count,
                    "cancelled": True,
                    "message": "Обновление метаданных отменено",
                }
            task_manager.update_task(
                task.id,
                message=f"Обновление «{show.title}» ({i + 1}/{len(candidate_shows)})",
                progress=(i + 1) / len(candidate_shows),
                current_item=i + 1,
                total_items=len(candidate_shows),
                show_id=show.id,
            )
            s_db = SessionLocal()
            try:
                s_show = s_db.get(Show, show.id)
                if s_show:
                    res = await refresh_show_metadata(s_db, s_show)
                    if res.get("updated"):
                        updated_count += 1
            except Exception as exc:
                errors_count += 1
                logger.warning("Ошибка обновления метаданных для тайтла %s (%s): %s", show.id, show.title, exc)
            finally:
                s_db.close()

            # Даём паузу циклу событий и SQLite для обработки других входящих запросов
            await asyncio.sleep(0.1)

        summary_msg = f"Завершено: обновлено {updated_count} из {len(candidate_shows)} тайтлов"
        if errors_count:
            summary_msg += f" (ошибок: {errors_count})"

        # Также обновляем метаданные и названия киноколлекций/саг
        try:
            coll_res = await refresh_all_collections_metadata(None, force=force)
            if coll_res and coll_res.get("updated"):
                summary_msg += f", саг: {coll_res['updated']}"
        except Exception as c_err:
            logger.debug("Ошибка обновления саг при общем обновлении метаданных: %s", c_err)

        task_manager.finish_task(task.id, message=summary_msg)
        audit_db = db or SessionLocal()
        try:
            log_audit(
                audit_db,
                "metadata.refresh_all",
                f"Автоматическое обновление метаданных библиотеки (Sonarr/Radarr): обновлено {updated_count} из {len(candidate_shows)} тайтлов",
                username=username,
            )
        finally:
            if audit_db is not db:
                audit_db.close()

        return {"total": len(candidate_shows), "updated": updated_count, "errors": errors_count, "message": summary_msg}
    except Exception as exc:
        task_manager.fail_task(task.id, error=str(exc))
        raise


async def refresh_all_collections_metadata(db=None, force: bool = False) -> dict:
    """
    Фоновое регулярное обновление метаданных киноколлекций/саг из TMDb.
    Синхронизирует список частей франшизы, названия на выбранном языке, постеры и описания в БД.
    """
    try:
        from app.models.db import MovieCollection as _MC, AppSettings as _AS
        MovieCollClass = _MC
        AppSettingsClass = _AS
    except ImportError:
        MovieCollClass = MovieCollection
        AppSettingsClass = AppSettings
    import json
    try:
        from app.database import SessionLocal
    except ImportError:
        SessionLocal = None

    needs_close = False
    init_db = db
    if init_db is None:
        if SessionLocal:
            init_db = SessionLocal()
            needs_close = True
        else:
            return {"total": 0, "updated": 0}

    try:
        colls = init_db.query(MovieCollClass).filter(MovieCollClass.tmdb_collection_id.isnot(None)).all()
        if not colls:
            return {"total": 0, "updated": 0}

        now = dt.datetime.utcnow()
        candidates = []
        for c in colls:
            if force or not getattr(c, "parts_cache", None) or not getattr(c, "last_metadata_refresh_at", None):
                candidates.append(c)
            elif not getattr(c, "titles_cache", None):
                candidates.append(c)
            elif (now - c.last_metadata_refresh_at).days >= 7:
                candidates.append(c)

        if not candidates:
            return {"total": len(colls), "updated": 0}

        app_settings = init_db.query(AppSettingsClass).filter(getattr(AppSettingsClass, "id", None) == 1).first()
        overview_lang = getattr(app_settings, "metadata_overview_language", "ru") if app_settings else "ru"
        overview_lang = (overview_lang or "ru").strip().lower()
        coll_title_lang = getattr(app_settings, "metadata_collection_title_language", "ru") if app_settings else "ru"
        coll_title_lang = (coll_title_lang or "ru").strip().lower()
    finally:
        if needs_close and init_db:
            init_db.close()
            init_db = None

    client = RadarrClient(overview_language=overview_lang)
    updated = 0
    for coll in candidates:
        s_db = db if db is not None else (SessionLocal() if SessionLocal else None)
        if s_db is None:
            continue
        try:
            db_coll = None
            if hasattr(s_db, "get"):
                db_coll = s_db.get(MovieCollClass, coll.id)
            if not db_coll:
                db_coll = coll
            if not db_coll or not getattr(db_coll, "tmdb_collection_id", None):
                continue
            c_det = await client.get_collection_details(db_coll.tmdb_collection_id, lang=coll_title_lang, bypass_cache=force)
            if c_det and c_det.get("parts"):
                db_coll.parts_count = len(c_det["parts"])
                db_coll.parts_cache = json.dumps(c_det["parts"], ensure_ascii=False)
                db_coll.last_metadata_refresh_at = dt.datetime.utcnow()
                if c_det.get("overview"):
                    db_coll.overview = c_det.get("overview")

                tbl = c_det.get("titles_by_lang") or {}
                if tbl:
                    db_coll.titles_cache = json.dumps(tbl, ensure_ascii=False)

                pref_title = None
                if coll_title_lang in ("ru", "rus"):
                    pref_title = tbl.get("ru")
                    if not pref_title and any('\u0400' <= ch <= '\u04ff' for ch in (c_det.get("name") or "")):
                        pref_title = c_det.get("name")
                    if not pref_title:
                        pref_title = tbl.get("en") or c_det.get("name")
                elif coll_title_lang in ("en", "eng"):
                    pref_title = tbl.get("en") or c_det.get("name")
                else:
                    pref_title = tbl.get(coll_title_lang) or tbl.get("en") or c_det.get("name")

                if pref_title and pref_title.strip():
                    db_coll.title = pref_title.strip()

                if c_det.get("poster_url"):
                    db_coll.poster_source_url = c_det.get("poster_url")
                    from app.services.cover_service import download_and_store_collection_cover
                    c_loc = await download_and_store_collection_cover(db_coll.id, c_det.get("poster_url"))
                    db_coll.poster_url = c_loc or c_det.get("poster_url")
                if c_det.get("backdrop_url"):
                    db_coll.backdrop_source_url = c_det.get("backdrop_url")
                    from app.services.cover_service import download_and_store_collection_backdrop
                    b_loc = await download_and_store_collection_backdrop(db_coll.id, c_det.get("backdrop_url"))
                    db_coll.backdrop_url = b_loc or c_det.get("backdrop_url")
                if hasattr(s_db, "add"):
                    s_db.add(db_coll)
                if hasattr(s_db, "commit"):
                    s_db.commit()
                updated += 1
        except Exception as e:
            logger.debug("Failed to background refresh collection %s: %s", coll.id, e)
        finally:
            if db is None and s_db and hasattr(s_db, "close"):
                s_db.close()
        await asyncio.sleep(0.1)

    return {"total": len(colls), "updated": updated}


def seed_default_metadata_sources(db) -> None:
    """Создаёт источники метаданных по умолчанию (Sonarr SkyHook и Radarr SkyHook),
    только при первичной инициализации приложения, удаляя устаревшие провайдеры."""
    try:
        try:
            from app.models.db import MetadataSource, MetadataSourceType
        except ImportError:
            class MetadataSourceType:  # type: ignore
                SKYHOOK = "skyhook"
                RADARR = "radarr"
            class MetadataSource:  # type: ignore
                type = _DummyExpr()
                def __init__(self, **kwargs):
                    for k, v in kwargs.items():
                        setattr(self, k, v)

        from app.services.settings_service import get_or_create_settings

        settings = get_or_create_settings(db)
        if getattr(settings, "metadata_sources_seeded", False):
            return

        # Удаляем устаревшие типы источников
        try:
            from sqlalchemy import text
            db.execute(text("DELETE FROM metadata_sources WHERE type IN ('omdb', 'kinopoisk', 'tvmaze', 'tmdb', 'thetvdb')"))
            db.commit()
        except Exception:
            try:
                db.rollback()
            except Exception:
                pass

        existing_types = {getattr(s, "type", "") for s in db.query(MetadataSource).all()}
        if db.query(MetadataSource).count() == 0 or not existing_types:
            db.add(MetadataSource(
                name="Sonarr SkyHook (Сериалы / Аниме)",
                type=getattr(MetadataSourceType, "SKYHOOK", "skyhook"),
                base_url="https://skyhook.sonarr.tv/v1/tvdb",
                api_key="",
                field_mapping={"alias_languages": ["ru"]},
                enabled=True,
            ))
            db.add(MetadataSource(
                name="Radarr SkyHook (Фильмы)",
                type=getattr(MetadataSourceType, "RADARR", "radarr"),
                base_url="https://api.radarr.video/v1",
                api_key="",
                field_mapping={"alias_languages": ["ru"]},
                enabled=True,
            ))

        settings.metadata_sources_seeded = True
        db.add(settings)
        db.commit()
        logger.info("Инициализированы официальные источники метаданных Sonarr и Radarr SkyHook")
    except Exception as exc:
        try:
            db.rollback()
        except Exception:
            pass
        logger.warning("Ошибка инициализации источников метаданных: %s", exc)
