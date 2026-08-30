"""
Источники метаданных: TMDB (themoviedb.org) и TVMaze (tvmaze.com).

Единый интерфейс MetadataClient.search(query) -> list[MetadataResult]
и .get_details(external_id) -> MetadataShowDetails (имя, AKA, сезоны/серии, даты,
рейтинг, страна, жанр, тип контента, сеть, дата премьеры — для карточек библиотеки).
"""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
from typing import Optional, List, Dict, Any

logger = logging.getLogger("aliasarr.metadata")

try:
    import httpx
except ImportError:
    httpx = None  # type: ignore

try:
    from app.models.db import Alias, AliasLanguage, Episode, EpisodeStatus, MetadataSource, Show
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

    def __init__(self, api_key: str = "", alias_countries: Optional[list[str]] = None):
        import os as _os
        self.api_key = (api_key or _os.getenv("TMDB_API_KEY", "") or self.DEFAULT_TOKEN).strip()
        self.alias_countries = [c.upper() for c in alias_countries] if alias_countries else None

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
                title=title,
                year=year,
                overview=item.get("overview"),
                poster_url=poster,
                rating=item.get("vote_average"),
                country=None,
                genre=None,
                content_type="movie" if media_type == "movie" else "series",
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
                params={"language": "en-US", "append_to_response": "alternative_titles,translations,release_dates"},
                headers=self._headers(),
            )
            resp.raise_for_status()
            data = resp.json()

        # Для совместимости с Jellyfin название и папки должны быть на английском
        raw_title = data.get("title") or data.get("original_title") or ""
        aliases = []
        ru_title = None
        eng_trans_title = None

        # Извлекаем русское и английское название и описание из переводов TMDB
        ru_overview = None
        eng_overview = None
        tr_raw = data.get("translations")
        tr_list = tr_raw.get("translations", []) if isinstance(tr_raw, dict) else (tr_raw if isinstance(tr_raw, list) else [])
        for tr in tr_list:
            if not isinstance(tr, dict):
                continue
            iso = tr.get("iso_639_1") or tr.get("language")
            tr_data = tr.get("data") if isinstance(tr.get("data"), dict) else tr
            if iso in ("ru", "rus", "russian"):
                ru_title = tr_data.get("title") or ru_title
                ru_overview = tr_data.get("overview") or ru_overview
            elif iso in ("en", "eng", "english"):
                eng_trans_title = tr_data.get("title") or eng_trans_title
                eng_overview = tr_data.get("overview") or eng_overview

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
            if iso in ("US", "GB") and is_latin_text(t_name):
                if t_name not in eng_candidates:
                    eng_candidates.append(t_name.strip())
            elif is_latin_text(t_name) and t_name.strip() not in eng_candidates:
                eng_candidates.append(t_name.strip())

        if is_latin_text(raw_title):
            title = raw_title
        elif eng_candidates:
            title = eng_candidates[0]
        else:
            title = raw_title

        # Добавляем все альтернативные и нелатинские названия в алиасы
        if raw_title and raw_title != title and raw_title not in aliases:
            aliases.append(raw_title)
        if ru_title and ru_title != title and ru_title not in aliases:
            aliases.append(ru_title)
        for t_name, iso in alt_titles:
            if t_name != title and t_name not in aliases:
                if self.alias_countries is not None and iso and iso not in self.alias_countries:
                    continue
                aliases.append(t_name)
                
        poster = data.get("poster_path")
        genres = [g["name"] for g in data.get("genres", [])]
        countries = [c["iso_3166_1"] for c in data.get("production_countries", [])]
        premiere = data.get("release_date") or None

        # Описание сюжета: Русский -> Английский -> Оригинал
        overview = ru_overview or data.get("overview") or eng_overview

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
        )

    async def _get_tv_details(self, tmdb_id: str) -> MetadataShowDetails:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"{self.BASE_URL}/tv/{tmdb_id}",
                params={"language": "en-US", "append_to_response": "alternative_titles,translations,external_ids"},
                headers=self._headers(),
            )
            resp.raise_for_status()
            show_data = resp.json()

            # Английские названия эпизодов (для совместимости с Jellyfin)
            episodes: list[MetadataEpisode] = []
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

        raw_title = show_data.get("name") or show_data.get("original_name") or ""
        aliases = []
        ru_title = None
        ru_overview = None
        eng_trans_title = None
        eng_overview = None

        # Извлекаем русское и английское название и описание из переводов TMDB
        for tr in (show_data.get("translations") or {}).get("translations", []):
            iso = tr.get("iso_639_1")
            if iso == "ru":
                ru_title = (tr.get("data") or {}).get("name")
                ru_overview = (tr.get("data") or {}).get("overview")
            elif iso == "en":
                eng_trans_title = (tr.get("data") or {}).get("name")
                eng_overview = (tr.get("data") or {}).get("overview")

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
            if iso in ("US", "GB") and is_latin_text(t_name):
                if t_name not in eng_candidates:
                    eng_candidates.append(t_name.strip())
            elif is_latin_text(t_name) and t_name.strip() not in eng_candidates:
                eng_candidates.append(t_name.strip())

        if is_latin_text(raw_title):
            title = raw_title
        elif eng_candidates:
            title = eng_candidates[0]
        else:
            title = raw_title

        # Добавляем все альтернативные и нелатинские названия в алиасы
        if raw_title and raw_title != title and raw_title not in aliases:
            aliases.append(raw_title)
        if ru_title and ru_title != title and ru_title not in aliases:
            aliases.append(ru_title)
        for t_name, iso in alt_titles:
            if t_name != title and t_name not in aliases:
                if self.alias_countries is not None and iso and iso not in self.alias_countries:
                    continue
                aliases.append(t_name)

        poster = show_data.get("poster_path")
        genres = [g["name"] for g in show_data.get("genres", [])]
        networks = [n["name"] for n in show_data.get("networks", [])]
        countries = show_data.get("origin_country", [])
        premiere = show_data.get("first_air_date") or None

        # Описание сюжета: Русский -> Английский -> Оригинал
        overview = ru_overview or show_data.get("overview") or eng_overview

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
    RADARR_URL = "https://radarr.servarr.com/v1/api"

    def __init__(self, api_key: str = "", alias_countries: Optional[list[str]] = None, base_url: str = ""):
        self.base_url = (base_url or self.BASE_URL).rstrip("/")
        self.alias_countries = [c.upper() for c in alias_countries] if alias_countries else None

    async def search(self, query: str) -> list[MetadataResult]:
        if not query or not query.strip():
            return []

        results: list[MetadataResult] = []
        seen_ids: set[str] = set()

        # 1. Поиск сериалов и аниме через Sonarr Skyhook
        async with httpx.AsyncClient(timeout=20, headers={"User-Agent": "Aliasarr/1.0.0 (Sonarr SkyHook Proxy)"}) as client:
            try:
                resp = await client.get(
                    f"{self.base_url}/search/en/",
                    params={"term": query.strip()},
                )
                if resp.status_code == 200:
                    items = resp.json()
                    if isinstance(items, list):
                        for item in items:
                            tvdb_id = item.get("tvdbId")
                            if not tvdb_id:
                                continue
                            ext_id = f"tvdb:{tvdb_id}"
                            if ext_id in seen_ids:
                                continue
                            seen_ids.add(ext_id)

                            poster_url = extract_skyhook_poster(item.get("images", []))

                            genres = item.get("genres", [])
                            country = item.get("originalCountry")
                            is_anime = ("Anime" in genres or "Animation" in genres) and (country in ("Japan", "JP", "JPN"))
                            c_type = "anime" if is_anime else "series"

                            rating_val = (item.get("rating") or {}).get("value")

                            results.append(MetadataResult(
                                external_id=ext_id,
                                title=item.get("title") or "",
                                year=item.get("year"),
                                overview=item.get("overview"),
                                poster_url=poster_url,
                                rating=float(rating_val) if rating_val is not None else None,
                                country=country,
                                genre=", ".join(genres) if genres else None,
                                content_type=c_type,
                            ))
            except Exception:
                pass

        return results

    async def get_details(self, external_id: str) -> MetadataShowDetails:
        """Получение полных деталей и списка всех эпизодов через SkyHook / Servarr."""
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
        elif ext_str.lower().startswith(("anilist:", "mal:", "imdb:", "tmdb:")):
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
            resp = await client.get(f"{self.base_url}/shows/en/{tvdb_id}")
            resp.raise_for_status()
            data = resp.json()

            # Получаем также русские алиасы и перевод, если доступен
            ru_data = None
            try:
                ru_resp = await client.get(f"{self.base_url}/shows/ru/{tvdb_id}")
                if ru_resp.status_code == 200:
                    ru_data = ru_resp.json()
            except Exception:
                pass

        raw_title = data.get("title") or ""
        aliases: list[str] = []

        # Алиасы из SkyHook
        for al in data.get("aliases", []):
            if isinstance(al, str) and al.strip() and al.strip() != raw_title and al.strip() not in aliases:
                aliases.append(al.strip())
            elif isinstance(al, dict) and al.get("title") and al["title"] not in aliases:
                aliases.append(al["title"])

        if ru_data and ru_data.get("title") and ru_data["title"] != raw_title and ru_data["title"] not in aliases:
            aliases.append(ru_data["title"])

        overview = (ru_data.get("overview") if ru_data and ru_data.get("overview") else None) or data.get("overview")

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
        )

    async def _get_movie_details(self, tmdb_id: str) -> MetadataShowDetails:
        radarr = RadarrClient(api_key="", alias_countries=self.alias_countries)
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

    def __init__(self, api_key: str = "", alias_countries: Optional[list[str]] = None, base_url: str = ""):
        self.base_url = (base_url or self.BASE_URL).rstrip("/")
        self.alias_countries = [c.upper() for c in alias_countries] if alias_countries else None

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
                            poster = f"https://image.tmdb.org/t/p/w500{item['poster_path']}" if item.get("poster_path") else None
                            results.append(MetadataResult(
                                external_id=ext_id,
                                title=item.get("title") or item.get("original_title") or "",
                                year=year,
                                overview=item.get("overview"),
                                poster_url=poster,
                                rating=item.get("vote_average"),
                                country=None,
                                genre=None,
                                content_type="movie",
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

        genres = m_item.get("genres", [])
        return MetadataResult(
            external_id=ext_id,
            title=m_item.get("title") or m_item.get("originalTitle") or "",
            year=m_item.get("year"),
            overview=m_item.get("overview"),
            poster_url=poster_url,
            rating=float(rating_val) if rating_val is not None else None,
            country=m_item.get("originalLanguage"),
            genre=", ".join(genres) if genres else None,
            content_type="movie",
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

        # 1. Приоритетный прямой запрос к TMDB с сервисным токеном Radarr (надёжно и полно)
        try:
            tmdb = TMDBClient(api_key=self.RADARR_TMDB_TOKEN, alias_countries=self.alias_countries)
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
                if original_title and original_title != title and original_title not in aliases:
                    aliases.append(original_title)

                # Собираем все alternativeTitles (Radarr)
                for alt in (data.get("alternativeTitles", []) or data.get("alternateTitles", [])):
                    t_name = alt.get("title") if isinstance(alt, dict) else str(alt)
                    if t_name and t_name.strip() and t_name.strip() != title and t_name.strip() not in aliases:
                        aliases.append(t_name.strip())

                # Собираем переводы (Translations)
                for tr in (data.get("translations", []) or []):
                    if isinstance(tr, dict):
                        tr_title = tr.get("title")
                        tr_lang = (tr.get("language") or "").lower()
                        if tr_title and tr_title.strip() and tr_title.strip() != title and tr_title.strip() not in aliases:
                            aliases.append(tr_title.strip())
                        if tr_lang in ("ru", "rus", "russian"):
                            if tr.get("overview"):
                                overview = tr.get("overview")

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
                    )

        # 3. Fallback на TMDB с сервисным токеном
        tmdb = TMDBClient(api_key=self.RADARR_TMDB_TOKEN, alias_countries=self.alias_countries)
        return await tmdb._get_movie_details(clean_id)


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

    def __init__(self, api_key: str = "", pin: str = "", alias_countries: Optional[list[str]] = None, base_url: str = ""):
        self.api_key = (api_key or "").strip()
        self.pin = (pin or "").strip()
        if ":" in self.api_key and not self.pin:
            self.api_key, self.pin = self.api_key.split(":", 1)
        self.alias_countries = [c.upper() for c in alias_countries] if alias_countries else None
        self.base_url = (base_url or self.BASE_URL).rstrip("/")
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

            # Поиск официального английского перевода TheTVDB
            eng_title = None
            eng_overview = None
            try:
                eng_resp = await self._authed_get(client, f"/series/{tvdb_id}/translations/eng")
                if eng_resp.status_code == 200:
                    eng_data = eng_resp.json().get("data") or {}
                    eng_title = eng_data.get("name")
                    eng_overview = eng_data.get("overview")
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
        aliases = []
        if raw_name and raw_name != title and raw_name not in aliases:
            aliases.append(raw_name)
        if ru_title and ru_title != title and ru_title not in aliases:
            aliases.append(ru_title)

        for a in (aliases_raw if isinstance(aliases_raw, list) else []):
            alias_name = (a.get("name") if isinstance(a, dict) else str(a) if a else "").strip()
            if alias_name and alias_name != title and alias_name not in aliases:
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

        # Описание сюжета: Русский -> Английский -> Оригинал
        overview = None
        if ru_overview and str(ru_overview).strip():
            overview = str(ru_overview).strip()
        elif eng_overview and str(eng_overview).strip():
            overview = str(eng_overview).strip()
        elif data.get("overview") and str(data.get("overview")).strip():
            overview = str(data.get("overview")).strip()

        raw_score = data.get("score")
        rating = None
        if raw_score is not None:
            try:
                rating = float(raw_score)
            except (ValueError, TypeError):
                rating = None

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
        )

    async def _get_movie_details(self, tvdb_id: str) -> MetadataShowDetails:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await self._authed_get(client, f"/movies/{tvdb_id}/extended")
            if resp.status_code != 200:
                resp = await self._authed_get(client, f"/movies/{tvdb_id}")
            if resp.status_code != 200:
                raise ValueError(f"TheTVDB movie {tvdb_id} not found (status {resp.status_code})")
            data = resp.json().get("data", {}) or {}

            # Поиск официального английского перевода TheTVDB
            eng_title = None
            eng_overview = None
            try:
                eng_resp = await self._authed_get(client, f"/movies/{tvdb_id}/translations/eng")
                if eng_resp.status_code == 200:
                    eng_data = eng_resp.json().get("data") or {}
                    eng_title = eng_data.get("name")
                    eng_overview = eng_data.get("overview")
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
        aliases = []
        if raw_name and raw_name != title and raw_name not in aliases:
            aliases.append(raw_name)
        if ru_title and ru_title != title and ru_title not in aliases:
            aliases.append(ru_title)

        for a in (aliases_raw if isinstance(aliases_raw, list) else []):
            alias_name = (a.get("name") if isinstance(a, dict) else str(a) if a else "").strip()
            if alias_name and alias_name != title and alias_name not in aliases:
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

        # Описание сюжета: Русский -> Английский -> Оригинал
        overview = None
        if ru_overview and str(ru_overview).strip():
            overview = str(ru_overview).strip()
        elif eng_overview and str(eng_overview).strip():
            overview = str(eng_overview).strip()
        elif data.get("overview") and str(data.get("overview")).strip():
            overview = str(data.get("overview")).strip()

        raw_score = data.get("score")
        rating = None
        if raw_score is not None:
            try:
                rating = float(raw_score)
            except (ValueError, TypeError):
                rating = None

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


def get_metadata_client(source_row) -> BaseMetadataClient:
    """source_row: модель MetadataSource из БД."""
    type_value = source_row.type.value if hasattr(source_row.type, "value") else str(source_row.type)
    
    # Извлекаем alias_countries и pin из field_mapping
    alias_countries = None
    pin = ""
    if isinstance(source_row.field_mapping, dict):
        alias_countries = source_row.field_mapping.get("alias_countries")
        pin = source_row.field_mapping.get("pin", "")
    
    if type_value in ("skyhook", "sonarr"):
        return SkyHookClient(source_row.api_key or "", alias_countries, base_url=source_row.base_url or "")
    elif type_value in ("radarr", "radarr_skyhook"):
        return RadarrClient(source_row.api_key or "", alias_countries, base_url=source_row.base_url or "")
    elif type_value == "tmdb":
        return TMDBClient(source_row.api_key or "", alias_countries)
    elif type_value == "tvmaze":
        return TVMazeClient(source_row.api_key or "", alias_countries)
    elif type_value == "thetvdb":
        return TheTVDBClient(source_row.api_key or "", pin=pin, alias_countries=alias_countries, base_url=source_row.base_url or "")
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
                episode.status = EpisodeStatus.UNAIRED if not already_released else EpisodeStatus.WANTED
                db.add(episode)
                changed = True
    else:
        for meta_ep in details.episodes:
            air_date = _parse_date(meta_ep.air_date)
            episode = (
                db.query(Episode)
                .filter(
                    Episode.show_id == show.id,
                    Episode.season_number == meta_ep.season_number,
                    Episode.episode_number == meta_ep.episode_number,
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
                    if episode.status in (EpisodeStatus.MISSING, EpisodeStatus.WANTED, EpisodeStatus.UNAIRED):
                        episode.status = EpisodeStatus.UNAIRED if air_date > now else EpisodeStatus.WANTED
                    db.add(episode)
                    changed = True
            elif meta_ep.episode_number:
                status = EpisodeStatus.UNAIRED if (air_date and air_date > now) else EpisodeStatus.WANTED
                db.add(Episode(
                    show_id=show.id,
                    season_number=meta_ep.season_number if meta_ep.season_number is not None else 1,
                    episode_number=meta_ep.episode_number,
                    absolute_number=meta_ep.absolute_number,
                    title=meta_ep.title,
                    air_date=air_date,
                    status=status,
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

    # 1. Разрешаем клиент источника метаданных
    client = None
    if getattr(show, "metadata_source", None):
        source = (
            db.query(MetadataSource)
            .filter(MetadataSource.type == show.metadata_source, MetadataSource.enabled == True)  # noqa: E712
            .first()
        )
        if source:
            try:
                client = get_metadata_client(source)
            except Exception:
                client = None

    if not client:
        client = RadarrClient() if is_movie else SkyHookClient()

    fallback_client = RadarrClient() if is_movie else SkyHookClient()
    details = None

    # 2. Пробуем получить детали по metadata_id
    if metadata_id:
        try:
            details = await client.get_details(str(metadata_id))
        except Exception as e:
            logger.debug("Failed to get details by metadata_id %s with %s for %s: %s", metadata_id, type(client).__name__, title, e)

        if (not details or (not is_movie and not details.episodes)) and client != fallback_client:
            try:
                details = await fallback_client.get_details(str(metadata_id))
            except Exception as e:
                logger.debug("Fallback client details failed for %s: %s", title, e)

    # 3. Если по metadata_id детали не получены — ищем по названию и алиасам
    search_candidates = []
    if title:
        search_candidates.append(title)
        # Если название содержит подзаголовки через двоеточие или дефис
        for sep in (":", "—", " - "):
            if sep in title:
                base_part = title.split(sep)[0].strip()
                if base_part and base_part not in search_candidates:
                    search_candidates.append(base_part)

    # Добавляем английские / ромадзи алиасы первыми кандидатами
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

    if not details or (not is_movie and not details.episodes):
        for candidate in search_candidates:
            if not candidate:
                continue
            for cl in (client, fallback_client):
                try:
                    results = await cl.search(candidate)
                    if results:
                        target_result = results[0]
                        ext_id = target_result.external_id or ""
                        if ext_id:
                            det = await cl.get_details(str(ext_id))
                            if det and (is_movie or det.episodes):
                                details = det
                                break
                except Exception as e:
                    logger.debug("Search candidate '%s' failed on %s: %s", candidate, type(cl).__name__, e)
            if details and (is_movie or details.episodes):
                break

    if not details:
        return {"updated": False, "show_id": show.id, "title": show.title, "reason": "No metadata found"}

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
    if not show.metadata_source:
        show.metadata_source = "radarr" if is_movie else "skyhook"
        changed = True

    # 4. Обновляем основные атрибуты тайтла
    if getattr(details, "overview", None) and show.overview != details.overview:
        show.overview = details.overview
        changed = True
    if getattr(details, "poster_url", None) and show.poster_url != details.poster_url:
        show.poster_url = details.poster_url
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
            for meta_ep in details.episodes:
                air_date = _parse_date(meta_ep.air_date)
                
                # Очищаем заглушки названий
                raw_ep_title = (meta_ep.title or "").strip()
                if raw_ep_title in ("None", "null", "TBA", "tba", ""):
                    raw_ep_title = None

                episode = (
                    db.query(Episode)
                    .filter(
                        Episode.show_id == show.id,
                        Episode.season_number == meta_ep.season_number,
                        Episode.episode_number == meta_ep.episode_number,
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
                        if episode.status in (EpisodeStatus.MISSING, EpisodeStatus.WANTED, EpisodeStatus.UNAIRED):
                            episode.status = EpisodeStatus.UNAIRED if air_date > now else EpisodeStatus.WANTED
                        ep_changed = True
                    if meta_ep.absolute_number is not None and episode.absolute_number != meta_ep.absolute_number:
                        episode.absolute_number = meta_ep.absolute_number
                        ep_changed = True
                    if ep_changed:
                        db.add(episode)
                        changed = True
                        episodes_updated += 1
                elif meta_ep.episode_number:
                    status = EpisodeStatus.UNAIRED if (air_date and air_date > now) else EpisodeStatus.WANTED
                    db.add(Episode(
                        show_id=show.id,
                        season_number=meta_ep.season_number if meta_ep.season_number is not None else 1,
                        episode_number=meta_ep.episode_number,
                        absolute_number=meta_ep.absolute_number,
                        title=raw_ep_title or "TBA",
                        air_date=air_date,
                        status=status,
                    ))
                    changed = True
                    episodes_added += 1

    # 6. Обновляем алиасы
    if details.aliases:
        existing_aliases = {a.text.lower().strip() for a in show.aliases}
        for alias_text in details.aliases:
            clean_alias = str(alias_text).strip()
            if clean_alias and clean_alias.lower() not in existing_aliases:
                existing_aliases.add(clean_alias.lower())
                db.add(Alias(
                    show_id=show.id,
                    text=clean_alias,
                    language=AliasLanguage.RU if any(ord(c) >= 0x0400 and ord(c) <= 0x04FF for c in clean_alias) else AliasLanguage.EN,
                    source="skyhook",
                ))
                changed = True

    show.last_metadata_refresh_at = now
    if changed:
        show.calendar_waiting_dismissed = False
        db.add(show)

    db.commit()
    db.refresh(show)

    return {
        "updated": changed,
        "show_id": show.id,
        "title": show.title,
        "episodes_updated": episodes_updated,
        "episodes_added": episodes_added,
    }


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
        # Проверяем наличие серий с заглушками
        has_placeholders = any(
            (not ep.title) or
            ep.title.strip().lower() in ("tba", "none", "null", "unknown", "") or
            ep.title.strip().lower().startswith(("episode ", "серия "))
            for ep in episodes
        )
        if has_placeholders:
            return True

        st = (getattr(show, "status", None) or "").lower()
        if st != "ended" and last_sync < now - _dt.timedelta(hours=6):
            return True

        aired_episodes = [ep for ep in episodes if ep.air_date]
        if aired_episodes:
            max_air_date = max(ep.air_date for ep in aired_episodes)
            if max_air_date > now - _dt.timedelta(days=30):
                return True

        if last_sync >= now - _dt.timedelta(hours=6):
            return False

        return False


async def refresh_all_shows_metadata(db, force: bool = False, username: str = "system") -> dict:
    """
    Фоновое регулярное обновление метаданных для библиотеки по алгоритму Sonarr/Radarr.
    Автоматически обновляет тайтлы, требующие синхронизации (невышедшие серии, TBA/Episode N, активные онгоинги).
    Отслеживается в task_manager и отображается в виджете фоновых операций.
    """
    from app.models.db import Show
    from app.services.audit import log_audit
    from app.services.task_manager import task_manager

    all_shows = db.query(Show).all()
    if not all_shows:
        return {"total": 0, "updated": 0, "message": "Библиотека пуста"}

    candidate_shows = [s for s in all_shows if should_refresh_show(s, db, force=force)]
    if not candidate_shows:
        logger.debug("Все %d тайтлов имеют актуальные метаданные (Sonarr/Radarr rate-limit). Пропуск.", len(all_shows))
        return {"total": len(all_shows), "updated": 0, "message": "Все метаданные актуальны"}

    task = task_manager.start_task(
        name="metadata_refresh",
        title="Обновление метаданных библиотеки",
        message=f"Подготовка к обновлению {len(candidate_shows)} тайтлов...",
        total_items=len(candidate_shows),
        current_item=0,
    )

    updated_count = 0
    errors_count = 0

    try:
        for i, show in enumerate(candidate_shows):
            task_manager.update_task(
                task.id,
                message=f"Обновление «{show.title}» ({i + 1}/{len(candidate_shows)})",
                progress=(i + 1) / len(candidate_shows),
                current_item=i + 1,
                total_items=len(candidate_shows),
                show_id=show.id,
            )
            try:
                res = await refresh_show_metadata(db, show)
                if res.get("updated"):
                    updated_count += 1
            except Exception as exc:
                errors_count += 1
                logger.warning("Ошибка обновления метаданных для тайтла %s (%s): %s", show.id, show.title, exc)

        summary_msg = f"Завершено: обновлено {updated_count} из {len(candidate_shows)} тайтлов"
        if errors_count:
            summary_msg += f" (ошибок: {errors_count})"

        task_manager.finish_task(task.id, message=summary_msg)
        log_audit(
            db,
            "metadata.refresh_all",
            f"Автоматическое обновление метаданных библиотеки (Sonarr/Radarr): обновлено {updated_count} из {len(candidate_shows)} тайтлов",
            username=username,
        )

        return {"total": len(candidate_shows), "updated": updated_count, "errors": errors_count, "message": summary_msg}
    except Exception as exc:
        task_manager.fail_task(task.id, error=str(exc))
        raise


def seed_default_metadata_sources(db) -> None:
    """Создаёт источники метаданных по умолчанию (TMDB, TVMaze, SkyHook, Radarr, TheTVDB),
    только при первичной инициализации приложения, сохраняя изменения и удалённые пользователем источники."""
    try:
        import os
        try:
            from app.models.db import MetadataSource, MetadataSourceType
        except ImportError:
            class MetadataSourceType:  # type: ignore
                SKYHOOK = "skyhook"
                RADARR = "radarr"
                TVMAZE = "tvmaze"
                TMDB = "tmdb"
                THETVDB = "thetvdb"
            class MetadataSource:  # type: ignore
                def __init__(self, **kwargs):
                    for k, v in kwargs.items():
                        setattr(self, k, v)

        from app.services.settings_service import get_or_create_settings

        settings = get_or_create_settings(db)
        if getattr(settings, "metadata_sources_seeded", False):
            return

        try:
            from sqlalchemy import text
            db.execute(text("DELETE FROM metadata_sources WHERE type IN ('omdb', 'kinopoisk')"))
            db.commit()
        except Exception:
            try:
                db.rollback()
            except Exception:
                pass

        existing_types = {getattr(s, "type", "") for s in db.query(MetadataSource).all()}
        if db.query(MetadataSource).count() == 0 or not existing_types:
            db.add(MetadataSource(
                name="SkyHook (Sonarr / TVDB Cloud)",
                type=getattr(MetadataSourceType, "SKYHOOK", "skyhook"),
                base_url="https://skyhook.sonarr.tv/v1/tvdb",
                api_key="",
                enabled=True,
            ))
            db.add(MetadataSource(
                name="Radarr SkyHook (Movie Cloud)",
                type=getattr(MetadataSourceType, "RADARR", "radarr"),
                base_url="https://api.radarr.video/v1",
                api_key="",
                enabled=True,
            ))
            db.add(MetadataSource(
                name="TVMaze",
                type=getattr(MetadataSourceType, "TVMAZE", "tvmaze"),
                base_url="https://api.tvmaze.com",
                api_key="",
                enabled=True,
            ))
            db.add(MetadataSource(
                name="TMDB (The Movie Database)",
                type=getattr(MetadataSourceType, "TMDB", "tmdb"),
                base_url="https://api.themoviedb.org/3",
                api_key=os.getenv("TMDB_API_KEY", ""),
                enabled=True,
            ))
            db.add(MetadataSource(
                name="TheTVDB v4",
                type=getattr(MetadataSourceType, "THETVDB", "thetvdb"),
                base_url="https://api4.thetvdb.com/v4",
                api_key=os.getenv("THETVDB_API_KEY", ""),
                enabled=True,
            ))

        settings.metadata_sources_seeded = True
        db.add(settings)
        db.commit()
        logger.info("Инициализированы источники метаданных по умолчанию")
    except Exception as exc:
        try:
            db.rollback()
        except Exception:
            pass
        logger.warning("Ошибка инициализации источников метаданных: %s", exc)

