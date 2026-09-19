"""Массовый импорт тайтлов из существующих папок на диске.

Повторяет логику «Library Import» из Sonarr и Radarr: сканирование корневой
папки, разбор имени каждой подпапки, поиск кандидатов в источниках метаданных
и ранжирование их по близости к имени папки.

Модуль сознательно не зависит от FastAPI и БД: он оперирует строками и
результатами метаданных, поэтому легко тестируется отдельно.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any, Iterable, Optional

from app.services.matcher import normalize_title

# Расширения видеофайлов нужны, чтобы отличить папку с медиа от служебной.
try:  # pragma: no cover - подстраховка на случай циклического импорта
    from app.services.postprocess import VIDEO_EXTENSIONS
except Exception:  # pragma: no cover
    VIDEO_EXTENSIONS = {".mkv", ".mp4", ".avi", ".m4v", ".ts", ".mov", ".wmv", ".flv", ".webm", ".mpg", ".mpeg"}


# Папки, которые никогда не являются тайтлом и отбрасываются при сканировании.
IGNORED_FOLDER_NAMES = {
    "$recycle.bin",
    "#recycle",
    ".actors",
    ".appledouble",
    ".grab",
    "@eadir",
    "extras",
    "lost+found",
    "sample",
    "samples",
    "subs",
    "subtitles",
    "system volume information",
    "fonts",
    "featurettes",
    "trailers",
    "behind the scenes",
    "deleted scenes",
    "other",
    "specials",
    "сезон 1",
    "сезоны",
    "субтитры",
}

# Технический «мусор» в имени папки. Всё, что начинается с первого такого токена,
# отбрасывается — так же поступает парсер Sonarr перед обращением к SkyHook.
_JUNK_TOKEN_PATTERNS = [
    r"(?:19|20)\d{2}",  # год — дальше него название не продолжается
    r"s\d{1,3}(?:\s*-\s*s?\d{1,3})?(?:e\d{1,4})?",
    r"season[\s._-]*\d{1,3}",
    r"сезон[ы]?[\s._-]*\d{0,3}",
    r"\d{1,3}[\s._-]*сезон",
    r"(?:2160|1080|720|576|480|360)[pi]",
    r"4k|uhd|hdr10\+?|hdr|dolby[\s._-]*vision|dovi",
    r"blu[\s._-]*ray|bd(?:rip|remux)?|b[dr]rip|web[\s._-]*dl|web[\s._-]*rip|webrip|web|hdtv|dvd(?:rip|scr)?|hdrip|remux|camrip|ts|tc",
    r"x\.?26[45]|h\.?26[45]|hevc|avc|xvid|divx|vp9|av1",
    r"dts(?:[\s._-]*hd)?(?:[\s._-]*ma)?|true[\s._-]*hd|atmos|ddp?\d?(?:[\s._-]*\d)?|e?ac[\s._-]*3|aac|flac|opus|mp3",
    r"\d[\s._-]*ch\b|[257][\s._-]*[01]\b",
    r"10[\s._-]*bit|8[\s._-]*bit",
    r"proper|repack|rerip|internal|limited|unrated|uncut|remastered|extended|imax|theatrical",
    r"complete|full|trilogy|duology|collection",
    r"dub(?:bed)?|sub(?:bed|s)?|multi|dual[\s._-]*audio|rus|eng|ukr|jap|subbed",
    r"лицензия|дублирование|дубляж|многоголосый|озвучка|перевод",
]

_JUNK_RE = re.compile(
    r"(?<![\w])(?:" + "|".join(_JUNK_TOKEN_PATTERNS) + r")(?![\w])",
    re.IGNORECASE,
)

# Год в скобках/квадратных скобках — самый надёжный источник года для папки.
_BRACKETED_YEAR_RE = re.compile(r"[\(\[\{]\s*((?:19|20)\d{2})\s*[\)\]\}]")
_BARE_YEAR_RE = re.compile(r"(?<![\w])((?:19|20)\d{2})(?![\w])")

# Хвостовая релиз-группа: «... [RARBG]», «... -FLUX», «... (LostFilm)».
_TRAILING_GROUP_RE = re.compile(r"[\(\[\{][^\(\)\[\]\{\}]{1,40}[\)\]\}]\s*$")

# Любая группа в скобках — кандидат на альтернативное название
# («Мандалорец (The Mandalorian)» — распространённый формат на русских раздачах).
_BRACKET_GROUP_RE = re.compile(r"[\(\[\{]([^\(\)\[\]\{\}]{2,80})[\)\]\}]")

# Доля, которую более короткое название обязано занимать в более длинном, чтобы
# вхождение считалось совпадением, а не случайным префиксом.
PREFIX_MATCH_MIN_COVERAGE = 0.6

_SEPARATOR_RE = re.compile(r"[._]+")
_MULTISPACE_RE = re.compile(r"\s{2,}")


@dataclass
class ParsedFolder:
    """Результат разбора имени папки."""

    name: str
    title: str
    year: Optional[int] = None
    # Альтернативные варианты названия (например, «Мандалорец / The Mandalorian»).
    alternative_titles: list[str] = field(default_factory=list)

    @property
    def search_terms(self) -> list[str]:
        """Поисковые запросы в порядке убывания приоритета, без дублей."""
        terms: list[str] = []
        for candidate in [self.title, *self.alternative_titles]:
            clean = (candidate or "").strip()
            if clean and clean.lower() not in {t.lower() for t in terms}:
                terms.append(clean)
        return terms


def _strip_year(text: str) -> tuple[str, Optional[int]]:
    """Вырезает год из имени папки и возвращает остаток и сам год."""
    year: Optional[int] = None

    bracketed = _BRACKETED_YEAR_RE.search(text)
    if bracketed:
        year = int(bracketed.group(1))
        text = text[: bracketed.start()] + " " + text[bracketed.end():]
        return text, year

    bare = list(_BARE_YEAR_RE.finditer(text))
    if bare:
        # Год в самом начале почти всегда часть названия («2012», «1917»),
        # поэтому такой вариант не считаем годом выпуска.
        for match in reversed(bare):
            if match.start() == 0:
                continue
            year = int(match.group(1))
            text = text[: match.start()] + " " + text[match.end():]
            break
    return text, year


def _normalize_separators(text: str) -> str:
    text = _SEPARATOR_RE.sub(" ", text)
    text = text.replace("_", " ")
    text = _MULTISPACE_RE.sub(" ", text)
    return text.strip(" -–—,:;·")


def parse_folder_name(name: str) -> ParsedFolder:
    """Разбирает имя папки в «чистое» название и год.

    >>> parse_folder_name("The.Office.US.2005.S01-S09.1080p.WEB-DL").title
    'The Office US'
    >>> parse_folder_name("Во все тяжкие (2008)").year
    2008
    """
    raw = (name or "").strip().strip("/\\")
    raw = os.path.basename(raw)
    if not raw:
        return ParsedFolder(name=name or "", title="")

    working = _TRAILING_GROUP_RE.sub(" ", raw) if _BRACKETED_YEAR_RE.search(raw) is None else raw
    working, year = _strip_year(working)
    working, bracket_titles = _extract_bracket_titles(working)

    # Отсекаем всё начиная с первого технического токена.
    spaced = _normalize_separators(working)
    junk = _JUNK_RE.search(spaced)
    if junk and junk.start() > 0:
        spaced = spaced[: junk.start()]
    elif junk and junk.start() == 0:
        # Имя целиком начинается с мусора — оставляем исходную строку без года.
        spaced = _normalize_separators(working)

    spaced = _normalize_separators(spaced)

    # Двуязычные имена: «Мандалорец | The Mandalorian».
    parts = [p.strip() for p in re.split(r"\s*\|\s*", spaced) if p.strip()]
    title = parts[0] if parts else spaced
    alternatives = parts[1:] if len(parts) > 1 else []
    alternatives.extend(bracket_titles)

    if not title:
        title = alternatives.pop(0) if alternatives else _normalize_separators(raw)

    return ParsedFolder(name=raw, title=title, year=year, alternative_titles=alternatives)


def _has_cyrillic(text: str) -> bool:
    return bool(re.search(r"[\u0400-\u04ff]", text or ""))


def _extract_bracket_titles(text: str) -> tuple[str, list[str]]:
    """Выносит из скобок осмысленные альтернативные названия.

    «Мандалорец (The Mandalorian)» → ("Мандалорец", ["The Mandalorian"]).
    Технические скобки вроде «(BDRip 1080p)» или «(LostFilm)» отбрасываются.
    Название на другом алфавите считается альтернативным даже из одного слова:
    именно так оформлено большинство русских раздач — «Дюна (Dune)».
    """
    outer = _normalize_separators(_BRACKET_GROUP_RE.sub(" ", text))
    outer_is_cyrillic = _has_cyrillic(outer)
    titles: list[str] = []

    def _replace(match: "re.Match[str]") -> str:
        inner = _normalize_separators(match.group(1))
        if not inner or len(inner) < 2:
            return " "
        if not re.search(r"[^\W\d_]", inner, flags=re.UNICODE):
            return " "
        if _JUNK_RE.search(inner):
            return " "
        different_script = _has_cyrillic(inner) != outer_is_cyrillic
        if not different_script and " " not in inner and len(inner) <= 12:
            # Одно короткое слово на том же алфавите — почти всегда релиз-группа.
            return " "
        titles.append(inner)
        return " "

    return _BRACKET_GROUP_RE.sub(_replace, text), titles


def _similarity(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    return SequenceMatcher(None, left, right).ratio()


def _candidate_titles(candidate: Any) -> list[str]:
    """Собирает все известные варианты названия кандидата."""
    titles: list[str] = []

    def _add(value: Any) -> None:
        if isinstance(value, str) and value.strip():
            titles.append(value.strip())

    _add(_get(candidate, "title"))
    _add(_get(candidate, "original_title"))
    by_lang = _get(candidate, "titles_by_lang") or {}
    if isinstance(by_lang, dict):
        for value in by_lang.values():
            _add(value)
    return titles


def _get(obj: Any, attr: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(attr, default)
    return getattr(obj, attr, default)


def score_candidate(parsed: ParsedFolder, candidate: Any, content_type: Optional[str] = None) -> float:
    """Оценивает кандидата от 0 до 1 по близости к имени папки.

    Учитывается лучшее совпадение среди всех языковых вариантов названия,
    точное совпадение года и соответствие запрошенной категории.
    """
    folder_variants = [normalize_title(t) for t in parsed.search_terms]
    folder_variants = [v for v in folder_variants if v]
    if not folder_variants:
        return 0.0

    best = 0.0
    for cand_title in _candidate_titles(candidate):
        norm_cand = normalize_title(cand_title)
        if not norm_cand:
            continue
        for norm_folder in folder_variants:
            ratio = _similarity(norm_folder, norm_cand)
            if ratio > best:
                best = ratio
            # Папка часто содержит уточнения, которых нет в базе
            # («The Office US» против «The Office»), и наоборот. Но вхождение
            # засчитывается, только если строки сопоставимы по длине: иначе
            # короткая папка «Decoded» цепляет любой тайтл, который с неё
            # начинается, вплоть до «Decoded: Dan Brown's Lost Symbol».
            if norm_folder and norm_cand and (
                norm_folder.startswith(norm_cand) or norm_cand.startswith(norm_folder)
            ):
                shorter, longer = sorted((len(norm_folder), len(norm_cand)))
                if longer and shorter / longer >= PREFIX_MATCH_MIN_COVERAGE:
                    best = max(best, 0.9)

    score = best * 0.8

    cand_year = _get(candidate, "year")
    if parsed.year and cand_year:
        year_gap = abs(int(cand_year) - int(parsed.year))
        if year_gap == 0:
            score += 0.2
        elif year_gap == 1:
            # Даты релиза в разных базах расходятся на год чаще, чем хотелось бы.
            score += 0.1
        elif year_gap == 2:
            score -= 0.15
        else:
            # Разница в три года и больше — это уже другой тайтл, а не расхождение
            # источников. Прежний мягкий штраф оставлял такие пары выше порога.
            score -= 0.35
    elif not parsed.year:
        score += 0.05

    cand_type = _get(candidate, "content_type")
    if content_type and cand_type:
        wanted = "movie" if content_type == "movie" else "series"
        actual = "movie" if cand_type == "movie" else "series"
        if wanted == actual:
            score += 0.05
        else:
            score -= 0.25
        if content_type == "anime" and cand_type == "anime":
            score += 0.05

    return max(0.0, min(1.0, score))


def rank_candidates(
    parsed: ParsedFolder,
    candidates: Iterable[Any],
    content_type: Optional[str] = None,
    limit: int = 20,
) -> list[tuple[Any, float]]:
    """Сортирует кандидатов по убыванию оценки совпадения."""
    scored = [(c, score_candidate(parsed, c, content_type)) for c in candidates]
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return scored[:limit]


def folder_has_media(path: str, max_depth: int = 3) -> bool:
    """Проверяет, есть ли внутри папки видеофайлы (ограниченная глубина обхода)."""
    root_depth = path.rstrip(os.sep).count(os.sep)
    try:
        for dirpath, dirnames, filenames in os.walk(path):
            if dirpath.rstrip(os.sep).count(os.sep) - root_depth >= max_depth:
                dirnames[:] = []
            for filename in filenames:
                if os.path.splitext(filename)[1].lower() in VIDEO_EXTENSIONS:
                    return True
    except OSError:
        return False
    return False


def is_ignored_folder(name: str) -> bool:
    lowered = (name or "").strip().lower()
    if not lowered or lowered.startswith("."):
        return True
    return lowered in IGNORED_FOLDER_NAMES
