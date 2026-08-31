"""
Универсальный парсер номеров серий.

Понимает форматы:
- S01E05, S01E05E06, S01E05-E07 (сезон+серия, вкл. мульти-серии)
- S01 без E (сезон-пак)
- 1x05, 01x05 (сезон x серия)
- E05, EP05, E01-E06, E01E02 (серии без явного сезона)
- [01-06], 01-06, "01-06 из 12" (диапазоны серий)
- "- 05" (аниме absolute номер после дефиса)
- Одинокое 1-3-значное число (fallback, absolute), с защитой от годов/разрешений

Порядок проверки важен: первое совпадение по приоритету побеждает.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class ReleaseKind(str, Enum):
    EPISODE = "episode"          # конкретная серия / диапазон серий одного сезона
    SEASON_PACK = "season_pack"  # весь сезон целиком
    ABSOLUTE = "absolute"        # абсолютный номер (типично для аниме, без сезона)
    UNKNOWN = "unknown"


@dataclass
class ParsedRelease:
    kind: ReleaseKind = ReleaseKind.UNKNOWN
    season: Optional[int] = None
    seasons: list[int] = field(default_factory=list)   # список сезонов для мульти-сезонных паков
    episodes: list[int] = field(default_factory=list)   # список серий (может быть один элемент)
    is_range: bool = False
    raw: str = ""
    matched_pattern: str = ""

    @property
    def episode(self) -> Optional[int]:
        """Первая серия из списка, для удобства когда важна только одна серия."""
        return self.episodes[0] if self.episodes else None


# ---------------------------------------------------------------------------
# Нормализация имени релиза перед парсингом
# ---------------------------------------------------------------------------

# Технический "мусор", который мешает парсингу диапазонов/чисел:
# разрешения, битрейты, кодеки, размеры файлов
_NOISE_PATTERNS = [
    r"\b\d{3,4}\s*[xхXХ]\s*\d{3,4}\b",  # 1920x1080, 1280x720, 3840x2160, 720x480
    r"\b\d{3,4}p\b",                    # 1080p, 720p, 2160p, 480p
    r"\b(?:x|h)\.?26[45]\b",            # x264, x265, h.264, h265
    r"\bhevc\b",
    r"\b\d+(?:\.\d+)?\s?(?:kbps|mbps|Mb|Gb|GB|MB)\b",
    r"\b(?:aac|ac3|dts|flac|mp3)\b",
    r"\b(?:web-?dl|webrip|bdrip|hdtv|dvdrip|bluray|remux)\b",
]

_NOISE_RE = re.compile("|".join(_NOISE_PATTERNS), re.IGNORECASE)

# Года выпуска (2019-2025 и т.п.) — НЕ путать с диапазоном серий
_YEAR_RANGE_RE = re.compile(r"\b(19|20)\d{2}\s*[-–]\s*(19|20)\d{2}\b")
_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")


def normalize(name: str) -> str:
    """Убирает технический шум (разрешения, кодеки, битрейты) перед парсингом."""
    cleaned = _NOISE_RE.sub(" ", name)
    cleaned = re.sub(r"[._]+", " ", cleaned)     # точки/подчёркивания -> пробелы
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
    return cleaned


# ---------------------------------------------------------------------------
# Регэкспы для каждого формата, в порядке приоритета
# ---------------------------------------------------------------------------

# S01E05, S01E05E06, S01E05-E07, S1E5 — а также кириллица "Сезон 1 Серия 5" /
# "Сез.1 Эп.05" и вариации с пробелами/точками/скобками между сезоном и серией
# (частый формат русских релиз-групп и трекеров), а также английские
# "Season 5 Episode 3" (без плотного "S01E05").
_SEASON_WORD = r"(?:S(?:easons?)?|Сез(?:он(?:ы|а)?)?|sezon(?:y|i|a)?|sez)"
_EPISODE_WORD_RU = r"(?:Сери[ияй]|Эпизод|Эп|seriy[ai]|seria|seriya|serii|seriy|ser|epizod|ep)"
_EPISODE_WORD_EN = r"(?:Episode|Ep)"

ROMAN_SEASON_MAP = {
    "i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5, "vi": 6, "vii": 7, "viii": 8, "ix": 9, "x": 10,
    "xi": 11, "xii": 12, "xiii": 13, "xiv": 14, "xv": 15, "xvi": 16, "xvii": 17, "xviii": 18, "xix": 19, "xx": 20,
}

_PART_WORD = r"(?:[\s._–-]*(?:part|часть|cour|кур|vol(?:ume)?|том)\.?[\s._–-]*\d+[\s._–-]*)?"

# Римские цифры сезонов: "I сезон", "II сезон", "III сезон", "IV сезон", "Season I", "Сезон II"
_RE_ROMAN_SEASON = re.compile(
    r"\b(?:(?:Season|Сезон|Сез|sezon)\.?\s*(i|ii|iii|iv|v|vi|vii|viii|ix|x|xi|xii|xiii|xiv|xv|xvi|xvii|xviii|xix|xx)|(i|ii|iii|iv|v|vi|vii|viii|ix|x|xi|xii|xiii|xiv|xv|xvi|xvii|xviii|xix|xx)\s*(?:сезон|сез|season|sezon))\b",
    re.IGNORECASE,
)

# Префиксные порядковые сезоны: "1st Season", "2nd Season", "3rd Season", "1-й сезон", "1 сезон", "01 сезон", "4th Season Part 1", "1.sezon"
_RE_PREFIX_SEASON = re.compile(
    r"(?:^|[\s_.\-\(\[])(\d{1,2})[\s._–-]*(?:st|nd|rd|th|[-–]?(?:й|ый|ой|ий|я|ая))?[\s._–-]*" + _SEASON_WORD + _PART_WORD + r"\b",
    re.IGNORECASE,
)

# Префиксные порядковые сезоны со списком серий: "5 сезон / 0, 10, 19 серия", "1-й сезон / 01, 03, 05 серии"
_RE_PREFIX_SEASON_EP_LIST = re.compile(
    r"(?:^|[\s_.\-\(\[/])(\d{1,2})[\s._–-]*(?:st|nd|rd|th|[-–]?(?:й|ый|ой|ий|я|ая))?[\s._–-]*" + _SEASON_WORD + _PART_WORD +
    r"[\s._/–-]+"
    r"((?:\d{1,4}\s*,\s*)+\d{1,4})\s*"
    r"(?:[\s._/–-]*(?:эп(?:изод(?:ов|а)?)?|сери[йия]|eps?|episodes?|выпуск(?:ов|а)?))?",
    re.IGNORECASE,
)

# Префиксные порядковые сезоны с диапазоном или одиночной серией:
# "2nd Season - 01", "2nd Season [01-12]", "2-й сезон - 02", "1st Season 05", "1.sezon.06.seriya.iz.20", "1.sezon.14.seriya"
_RE_PREFIX_SEASON_EP_RANGE = re.compile(
    r"(?:^|[\s_.\-\(\[])(\d{1,2})[\s._–-]*(?:st|nd|rd|th|[-–]?(?:й|ый|ой|ий|я|ая))?[\s._–-]*" + _SEASON_WORD + _PART_WORD +
    r"[\s._–-]+"
    r"(?:(?:" + _EPISODE_WORD_RU + "|" + _EPISODE_WORD_EN + r")[\s._–-]*)?"
    r"\[?\s*(\d{1,4})\s*[-–~]\s*(\d{1,4})(?:v\d)?\s*\]?"
    r"(?:[\s._–-]*" + _EPISODE_WORD_RU + r")?"
    r"(?:[\s._–-]*(?:из|of|iz|\/|\|)[\s._–-]*\d+)?"
    r"(?:[\s._–-]*(?:эп(?:изод(?:ов|а)?)?|сери[йия]|eps?|episodes?|выпуск(?:ов|а)?))?",
    re.IGNORECASE,
)
_RE_PREFIX_SEASON_EP_SINGLE = re.compile(
    r"(?:^|[\s_.\-\(\[])(\d{1,2})[\s._–-]*(?:st|nd|rd|th|[-–]?(?:й|ый|ой|ий|я|ая))?[\s._–-]*" + _SEASON_WORD + _PART_WORD +
    r"[\s._–-]+"
    r"(?:(?:" + _EPISODE_WORD_RU + "|" + _EPISODE_WORD_EN + r")[\s._–-]*)?"
    r"\[?\s*(\d{1,4})(?:v\d)?\s*\]?"
    r"(?:[\s._–-]*" + _EPISODE_WORD_RU + r")?"
    r"(?:[\s._–-]*(?:из|of|iz|\/|\|)[\s._–-]*\d+)?"
    r"(?:[\s._–-]*(?:эп(?:изод(?:ов|а)?)?|сери[йия]|eps?|episodes?|выпуск(?:ов|а)?))?",
    re.IGNORECASE,
)

# S-dash / Season-dash со списком серий: "Сезон 5 / 0, 10, 19", "Season 2 - 01, 02, 05"
_RE_S_DASH_EP_LIST = re.compile(
    r"\b(?:S|Season|Сезон|Сез|sezon)\.?\s*(\d{1,2})" + _PART_WORD + r"\s*(?:[-–~_:/]|\s+)\s*\[?\s*((?:\d{1,4}\s*,\s*)+\d{1,4})\s*\]?"
    r"(?:[\s._/–-]*(?:эп(?:изод(?:ов|а)?)?|сери[йия]|eps?|episodes?|выпуск(?:ов|а)?))?",
    re.IGNORECASE,
)

# S-dash / Season-dash с сериями: "S2 - 01", "S02 - 02", "Season 2 - 01", "Сезон 2 - 02", "S2 [01-12]", "Season 4 Part 1 - 04"
_RE_S_DASH_EP_RANGE = re.compile(
    r"\b(?:S|Season|Сезон|Сез|sezon)\.?\s*(\d{1,2})" + _PART_WORD + r"\s*(?:[-–~_:]|\s+)\s*\[?\s*(\d{1,4})\s*[-–~]\s*(\d{1,4})\s*\]?",
    re.IGNORECASE,
)
_RE_S_DASH_EP_SINGLE = re.compile(
    r"\b(?:S|Season|Сезон|Сез|sezon)\.?\s*(\d{1,2})" + _PART_WORD + r"\s*(?:[-–~_:]|\s+)\s*\[?\s*(\d{1,4})(?:v\d)?\s*\]?(?!\d)(?!\s*(?:из|of|iz|\/|\|)\s*(?:(?:ep|эп|сери[яи]|episode|e)\.?\s*)?\d)",
    re.IGNORECASE,
)

# Римские цифры сезонов с серией: "II сезон - 05", "Season II - 03", "Overlord IV Part 1 - 05", "Overlord IV - 05"
_RE_ROMAN_SEASON_EP = re.compile(
    r"\b(?:(?:Season|Сезон|Сез|sezon)\.?\s*(i|ii|iii|iv|v|vi|vii|viii|ix|x)|(i|ii|iii|iv|v|vi|vii|viii|ix|x)\s*(?:сезон|сез|season|sezon)?)" + _PART_WORD + r"\s*(?:[-–~_:]|\s+)\s*\[?\s*(\d{1,4})(?:v\d)?\s*\]?(?!\d)(?!\s*(?:из|of|iz|\/|\|)\s*(?:(?:ep|эп|сери[яи]|episode|e)\.?\s*)?\d)",
    re.IGNORECASE,
)

# Цифра сезона, за которой следует серия в скобках [01] или через дефис - 01:
# "Hell_Mode_Yarikomizuki_no_Gamer_wa_Hai_Sette_2_[04]_[HEVC].mkv", "KonoSuba 2 [05] [1080p].mkv"
_RE_SEASON_DIGIT_BRACKET_EP = re.compile(
    r"(?:[\s_.\-]|^)(\d{1,2})[\s_.\-]+\[\s*(?:(?:ep|эп|серия|episode|e)\.?\s*)?(\d{1,4})(?:v\d)?\s*\](?!\s*(?:из|of|iz|\/|\|)\s*(?:(?:ep|эп|сери[яи]|episode|e)\.?\s*)?\d)",
    re.IGNORECASE,
)
_RE_SEASON_DIGIT_DASH_EP = re.compile(
    r"(?:[\s_.\-]|^)(\d{1,2})[\s_.\-]+[-–]\s*(\d{1,4})(?:v\d)?\b(?!\d)(?!\s*(?:из|of|iz|\/|\|)\s*(?:(?:ep|эп|сери[яи]|episode|e)\.?\s*)?\d)",
    re.IGNORECASE,
)

# Одиночная серия в скобках: [01], [04], [EP02], [Ep.05], [01v2], [E05]
_RE_BRACKET_SINGLE_EP = re.compile(
    r"\[\s*(?:(?:ep|эп|сери[яи]|episode|e)\.?\s*)?(\d{1,4})(?:v\d)?\s*\]",
    re.IGNORECASE,
)

# Хвостовая цифра сезона перед группой/качеством в паках:
# "Hell Mode Yarikomizuki no Gamer wa Hai Sette 2 - AniLiberty [WEBRip 1080p HEVC]"
_RE_TRAILING_SEASON_DIGIT_PACK = re.compile(
    r"[\s_.\-](\d{1,2})\s*[-–]\s*(?:[A-Za-zА-Яа-я0-9_-]+)?\s*\[",
    re.IGNORECASE,
)

# S01E01-E10, S01E01-10, S01E01~E10, S01E01_E10
_RE_SXXEXX_RANGE = re.compile(
    r"\bS(\d{1,2})\s*E(\d{1,3})\s*(?:[-–~_]|to)\s*(?:E)?(\d{1,3})\b",
    re.IGNORECASE,
)

# 1x01-1x10, 1x01-10, 01x01-01x10
_RE_XFORMAT_RANGE = re.compile(
    r"\b(\d{1,2})x(\d{2,4})\s*(?:[-–~]|to)\s*(?:\d{1,2}x)?(\d{2,4})\b",
    re.IGNORECASE,
)

_RE_SXXEXX_MULTI = re.compile(
    r"\bS(\d{1,2})E(\d{1,3})(?:[-\s]?E(\d{1,3}))?(?:E(\d{1,3}))?\b",
    re.IGNORECASE,
)

# "Сезон: 2 / Серии: 1-18 (18)", "Сезон: 2 / Серии: 1-18 из 18", "Season 2 Episodes 1-18"
_RE_WORDY_SEASON_EP_RANGE = re.compile(
    r"(?:^|[\s_.\-\(\[])" + _SEASON_WORD + r"[:\.\s_–-]*(\d{1,3})\D{0,25}?(?:" + _EPISODE_WORD_RU + "|" + _EPISODE_WORD_EN + r")[:\.\s_–-]*(\d{1,4})\s*[-–~]\s*(\d{1,4})(?:\s*(?:\(\d+\)|\(\s*из\s*\d+\s*\)|из\s*\d+|of\s*\d+|iz\s*\d+))?",
    re.IGNORECASE,
)

# "Сезон 1 Серия 5" / "Сезон: 2 / Серия: 5" / "Season 5 Episode 3" — сезон и одиночная серия словами
_RE_WORDY_SEASON_EP_SINGLE = re.compile(
    r"(?:^|[\s_.\-\(\[])" + _SEASON_WORD + r"[:\.\s_–-]*(\d{1,3})\D{0,25}?(?:" + _EPISODE_WORD_RU + "|" + _EPISODE_WORD_EN + r")[:\.\s_–-]*(\d{1,4})(?:v\d)?(?:\s*(?:из|of|iz|\/|\|)\s*\d+)?",
    re.IGNORECASE,
)

# S01 без последующего E где-то рядом (сезон-пак): "Season 1", "S01", "[TV] S02",
# "(S01)", "Сезон 1", "Сезон: 2", "Сезон.01" — весь сезон целиком, без указания серии.
_RE_SEASON_PACK = re.compile(
    r"\b(?:S(?:easons?)?|Сез(?:он(?:ы|а)?)?|sezon(?:y|i|a)?|sez)[:\.]?\s*(\d{1,3})\b(?!\s*(?:E\.?\d|" + _EPISODE_WORD_RU + "|" + _EPISODE_WORD_EN + r"))",
    re.IGNORECASE,
)
_RE_SEASON_PACK_KEYWORDS = re.compile(
    r"\b(complete|full(?!\s*hd)|полный сезон|весь сезон|все сезоны|полный сериал|весь сериал|антология|anthology)\b|\[full\]|\(full\)",
    re.IGNORECASE,
)

# OVA/ONA/OAD/спешлы/фильмы — по общепринятой конвенции (как в Sonarr/большинстве трекеров)
# относятся к "сезону 0". Поддерживаются любые разделители: "OVA 3", "OVA-1", "OVA_01", "OVA.03", "SP01", "Special 1", "Movie 1", "Film 1".
_RE_OVA_ONA_RANGE = re.compile(
    r"\b(?:OVA|ONA|OAD|Special|Specials|Спешл(?:ы)?|Спецвыпуск(?:и)?|SP|Picture\s*Drama|Shorts?|Mini[-_\s]?Anime|Recap|Digest|Movie|Film|Фильм|Gekijouban|Gekijōban|劇場版)"
    r"[\s._–-]*"
    r"(?:\[|\()?"
    r"(?:#|№|ep|e)?[\s._–-]*"
    r"(\d{1,4})\s*[-–~]\s*(\d{1,4})"
    r"(?:\]|\))?",
    re.IGNORECASE,
)
_RE_OVA_ONA_EPISODE = re.compile(
    r"\b(?:OVA|ONA|OAD|Special|Specials|Спешл(?:ы)?|Спецвыпуск(?:и)?|SP|Picture\s*Drama|Shorts?|Mini[-_\s]?Anime|Recap|Digest|Movie|Film|Фильм|Gekijouban|Gekijōban|劇場版)"
    r"[\s._–-]*"
    r"(?:\[|\()?"
    r"(?:#|№|ep|e)?[\s._–-]*"
    r"(\d{1,4})\b"
    r"(?:\s*(?:\]|\)))?",
    re.IGNORECASE,
)
_RE_SEASON_SP = re.compile(
    r"(?:(?:\[|\()?\s*(?:Season|Сезон|S)?\s*(\d{1,2})\s*(?:\]|\))?[\s._–-]+(?:sp|special|спешл|ova|ona|recap)\b|"
    r"\b(?:Season|Сезон|S)\s*(\d{1,2})\s*[-_.\s]+(?:sp|special|спешл|ova|ona|recap)\b|"
    r"\b(\d{1,2})\s*[-_.\s]+(?:sp|special|спешл|ova|ona|recap)\b)",
    re.IGNORECASE,
)
_RE_OVA_ONA_PACK = re.compile(
    r"\b(?:OVA|ONA|OAD|Special|Specials|Спешл(?:ы)?|Спецвыпуск(?:и)?|SP|Picture\s*Drama|Shorts?|Recap|Movie|Film|Фильм|Gekijouban|Gekijōban|劇場版)\b|\[(?:sp|ova|ona|oad|special|movie|film)\]",
    re.IGNORECASE,
)

# 1x05, 01x05, 1x05-1x07
_RE_XFORMAT = re.compile(r"\b(\d{1,2})x(\d{2,4})\b", re.IGNORECASE)

# E05, EP05, E01-E06, E01E02 (без явного сезона)
_RE_E_ONLY = re.compile(
    r"(?<![Ss]\d)\bE(?:P)?\.?(\d{1,4})(?:\s?[-\s]\s?E(?:P)?\.?(\d{1,4}))?\b",
    re.IGNORECASE,
)

# Диапазоны в скобках или явные: [01-06], [1-6], [154-175], [E01-E12], [01-08 из 12], [E01-E12 of 12], (1-12 из 24)
_RE_BRACKET_RANGE = re.compile(
    r"\[\s*(?:(?:ep|эп|сери[ия]|episode|e)\.?\s*)?(\d{1,4})\s*[-–~]\s*(?:(?:ep|эп|сери[ия]|episode|e)\.?\s*)?(\d{1,4})(?:\s*(?:из|of|iz|\/|\|)\s*(?:(?:ep|эп|сери[ия]|episode|e)\.?\s*)?\d{1,4}\+?)?(?:\s*(?:эп(?:изод(?:ов|а)?)?|сери[йия]|eps?|episodes?|выпуск(?:ов|а)?))?\s*\]",
    re.IGNORECASE,
)
_RE_RANGE_IZ_N = re.compile(
    r"(?:\[|\(|\b)(?:(?:ep|эп|сери[ия]|episode|e)\.?\s*)?(\d{1,4})\s*(?:[-–~]|to)\s*(?:(?:ep|эп|сери[ия]|episode|e)\.?\s*)?(\d{1,4})\s*(?:из|of|iz|\/|\|)\s*(?:(?:ep|эп|сери[ия]|episode|e)\.?\s*)?(\d{1,4})\+?(?:\s*(?:эп(?:изод(?:ов|а)?)?|сери[йия]|eps?|episodes?|выпуск(?:ов|а)?))?(?:\]|\)|\b)",
    re.IGNORECASE,
)
_RE_SINGLE_IZ_N = re.compile(
    r"(?:\[|\()(?:(?:ep|эп|сери[яи]|episode|e)\.?\s*)?(\d{1,4})\s*(?:из|of|iz|\/|\|)\s*(?:(?:ep|эп|сери[яи]|episode|e)\.?\s*)?(\d{1,4})\+?(?:\s*(?:эп(?:изод(?:ов|а)?)?|сери[йия]|eps?|episodes?|выпуск(?:ов|а)?))?(?:\]|\))|"
    r"\b(?:(?:ep|эп|сери[яи]|episode|e)\.?\s*)(\d{1,4})\s*(?:из|of|iz|\/|\|)\s*(?:(?:ep|эп|сери[яи]|episode|e)\.?\s*)?(\d{1,4})\+?(?:\s*(?:эп(?:изод(?:ов|а)?)?|сери[йия]|eps?|episodes?|выпуск(?:ов|а)?))?\b|"
    r"\b(\d{1,4})\s*(?:из|of|iz)\s*(?:(?:ep|эп|сери[яи]|episode|e)\.?\s*)?(\d{1,4})\+?(?:\s*(?:эп(?:изод(?:ов|а)?)?|сери[йия]|eps?|episodes?|выпуск(?:ов|а)?))?\b",
    re.IGNORECASE,
)
_RE_PLAIN_RANGE = re.compile(r"\b(\d{1,4})\s*[-–~]\s*(\d{1,4})\b")

# Аниме absolute: "- 154", "- 05", "- 001", "- 00", "- 000", "- 05v2"
_RE_DASH_ABSOLUTE = re.compile(r"[-–]\s?(\d{1,4})(?:v\d)?\b(?!\d)")

# Fallback: одинокое 1-4 значное число
_RE_LONE_NUMBER = re.compile(r"(?<!\d)(\d{1,4})(?!\d)")

# Дополнительные материалы / опенинги / эндинги / трейлеры
_EXTRA_RELEASE_RE = re.compile(
    r"\b(?:nc)?(?:op|ed|pv|cm|ins)\s*[-–_./\s]?\s*\d*\b|"
    r"\b(?:opening|ending)s?\s*[-–_./\s]?\s*\d*\b|"
    r"\b(?:опенинг(?:и)?|эндинг(?:и)?)\s*[-–_./\s]?\s*\d*\b|"
    r"\b(?:creditless|ncop|nced)\s*\d*\b|"
    r"\b(?:op\s*[/&]\s*ed|ncop\s*[/&]\s*nced)\b|"
    r"\[(?:op[/&]ed|ncop[/&]nced|op|ed|pv|ost|soundtrack)\]|"
    r"\((?:op[/&]ed|ncop[/&]nced|op|ed|pv|ost|soundtrack)\)|"
    r"\b(?:theme\s*songs?|music\s*videos?|character\s*songs?|клипы?)\b|"
    r"\b(?:sample|trailer|preview|teaser|menu|promo|трейлер(?:ы)?|промо)\b|"
    r"\b(?:extra|bonus|featurette|behind[-_\s]the[-_\s]scenes|making[-_\s]of|interview|deleted[-_\s]scene|бонус(?:ы)?|допы|дополнительные\s*материалы)\b|"
    r"\bclean[-_\s]?(?:op|ed|opening|ending)\b|"
    r"\bopenings?\s*(?:&|and)\s*endings?\b",
    re.IGNORECASE,
)

# Релизы НЕ-видео контента (чистый звук, аудиодорожки, саундтреки, сабы, манга, артбуки и т.д.)
_NON_VIDEO_RELEASE_RE = re.compile(
    r"\b(?:rus|eng|jap|jpn|ukr|ger|fra|spa)?\s*(?:sound|audio|soundtracks?|ost|audio[-\s]?tracks?|чистый\s*звук|звуковые\s*дорожки|аудиодорожк[иа]|звуковые\s*файлы|sound\s*pack|audio\s*pack|только\s*звук|только\s*аудио|озвучка\s*отдельно)\b|"
    r"\[(?:audio|sound|soundtrack|ost|audio[-\s]?tracks?|звук|аудиодорожки|озвучка\s*отдельно)\]|"
    r"\((?:audio|sound|soundtrack|ost|audio[-\s]?tracks?|звук|аудиодорожки|озвучка\s*отдельно)\)|"
    r"\b(?:rus|eng|jap|jpn|ukr)?\s*(?:subs?\s*only|только\s*субтитры|только\s*сабы|subtitles?\s*pack|пак\s*субтитров)\b|"
    r"\[(?:subs\s*only|субтитры|сабы|пак\s*субтитров)\]|"
    r"\((?:subs\s*only|субтитры|сабы|пак\s*субтитров)\)|"
    r"\b(?:манг[аи]|manga|ранобэ|ранобе|light\s?novel|ranobe|артбук|art\s?book|саундтрек|soundtrack|ost|додзинси|doujin|scans?|сканы)\b|"
    r"\[flac\]|\[mp3\]|\[lossless\]|\bflac\s+pack\b|\bmp3\s+pack\b|"
    r"\.cbz\b|\.cbr\b|\.pdf\b|\.epub\b|\.fb2\b|\.djvu\b",
    re.IGNORECASE,
)

_RE_MULTI_SEASON_RANGE = re.compile(
    r"""
    (?:
        \b(?:S(?:easons?)?|Сез(?:он(?:ы|а)?)?|sezon(?:y|i|a)?|sez)[:\.]?\s*(\d{1,3})\s*[-–~]\s*(?:S(?:easons?)?|Сез(?:он(?:ы|а)?)?|sezon(?:y|i|a)?|sez)?[:\.]?\s*(\d{1,3})(?:(?=E\d)|(?=[\s_\-\[\(])|\b)
    |
        \b(\d{1,3})\s*[-–~]\s*(\d{1,3})\s*(?:сезон(?:ы|а)?|seasons?|sezon(?:y|i|a)?)\b
    |
        \(\s*S(\d{1,3})\s*[-–~]\s*S?(\d{1,3})\s*\)
    |
        \[\s*S(\d{1,3})\s*[-–~]\s*S?(\d{1,3})\s*\]
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)
_RE_MULTI_SEASON_LIST = re.compile(
    r"""
    (?:
        \b(?:Seasons?|Сезоны?|Сез(?:он(?:ы|а)?)?|sezon(?:y|i|a)?|sez)[:\.]?\s*(\d{1,3}(?:\s*,\s*\d{1,3})+)\b
    |
        \b(\d{1,3}(?:\s*,\s*\d{1,3})+)\s*(?:сезон(?:ы|а)?|seasons?|sezon(?:y|i|a)?)\b
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)

# S1-6E1-93 of 93 / S1-3E1-57 of 57 — мульти-сезон с диапазоном серий
_RE_MULTI_SEASON_EP_RANGE = re.compile(
    r"\bS(\d{1,2})\s*[-–~]\s*(\d{1,2})\s*E(\d{1,3})\s*[-–~]\s*(?:E)?(\d{1,3})\b",
    re.IGNORECASE,
)


def _season_pack_result(seasons: list[int] | int, raw: str, pattern: str) -> ParsedRelease:
    if isinstance(seasons, int):
        return ParsedRelease(
            kind=ReleaseKind.SEASON_PACK,
            season=seasons,
            seasons=[seasons],
            episodes=[],
            raw=raw,
            matched_pattern=pattern,
        )
    s_list = sorted(set(seasons))
    primary_season = s_list[0] if s_list else 1
    return ParsedRelease(
        kind=ReleaseKind.SEASON_PACK,
        season=primary_season,
        seasons=s_list,
        episodes=[],
        raw=raw,
        matched_pattern=pattern,
    )


def parse_episode(release_name: str) -> ParsedRelease:
    """
    Разбирает имя релиза и возвращает ParsedRelease.
    Пробует форматы по порядку приоритета, первое совпадение побеждает.
    """
    raw = release_name
    name = normalize(release_name)

    # 0. Исключение не-видео релизов (аудиодорожки, саундтреки, сабы, манга и т.п.)
    if _NON_VIDEO_RELEASE_RE.search(raw):
        return ParsedRelease(kind=ReleaseKind.UNKNOWN, raw=raw, matched_pattern="non_video_ignored")

    # Защита: если во всём имени встречается диапазон годов (2019-2025) —
    # временно "выжигаем" его, чтобы не спутать с диапазоном серий
    protected = _YEAR_RANGE_RE.sub(lambda m: "#" * len(m.group(0)), name)
    protected = _YEAR_RE.sub(lambda m: "#" * len(m.group(0)), protected)

    # Если релиз является опенингом/эндингом/бонусом/сэмплом и не содержит явного S01E01
    has_explicit_s_e = (
        _RE_MULTI_SEASON_EP_RANGE.search(protected) or
        _RE_SXXEXX_RANGE.search(protected) or _RE_SXXEXX_MULTI.search(protected) or
        _RE_XFORMAT_RANGE.search(protected) or _RE_WORDY_SEASON_EP_RANGE.search(protected) or
        _RE_WORDY_SEASON_EP_SINGLE.search(protected) or _RE_XFORMAT.search(protected)
    )
    if not has_explicit_s_e and _EXTRA_RELEASE_RE.search(raw):
        return ParsedRelease(kind=ReleaseKind.UNKNOWN, raw=raw, matched_pattern="extra_ignored")

    # 0б. Мультисезонный диапазон с общим счётчиком серий: S1-6E1-93 of 93 / S1-3E1-57 of 57
    m_multi_s_ep = _RE_MULTI_SEASON_EP_RANGE.search(protected)
    if m_multi_s_ep:
        s1, s2 = int(m_multi_s_ep.group(1)), int(m_multi_s_ep.group(2))
        e1, e2 = int(m_multi_s_ep.group(3)), int(m_multi_s_ep.group(4))
        if 1 <= s1 <= s2 <= 100:
            s_list = list(range(s1, s2 + 1))
            ep_list = list(range(e1, e2 + 1)) if e1 <= e2 else [e1]
            return ParsedRelease(
                kind=ReleaseKind.SEASON_PACK,
                season=s1,
                seasons=s_list,
                episodes=ep_list,
                is_range=True,
                raw=raw,
                matched_pattern="multi_season_ep_range",
            )

    # 1. S01E01-E10 диапазон серий (S01E01-E10, S01E01-10, S01E01~E10, S01E01-E10 COMPLETE)
    m_range_ep = _RE_SXXEXX_RANGE.search(protected)
    if m_range_ep:
        s = int(m_range_ep.group(1))
        start, end = int(m_range_ep.group(2)), int(m_range_ep.group(3))
        if start <= end and (end - start) < 300:
            return ParsedRelease(
                kind=ReleaseKind.EPISODE, season=s, episodes=list(range(start, end + 1)),
                is_range=True, raw=raw, matched_pattern="SxxExx_range",
            )

    # 1б. S01E05 (+ мульти-серии / диапазон E-E)
    m = _RE_SXXEXX_MULTI.search(protected)
    if m:
        season = int(m.group(1))
        eps = [int(m.group(2))]
        if m.group(3):
            start, end = int(m.group(2)), int(m.group(3))
            eps = list(range(start, end + 1))
        if m.group(4):
            eps.append(int(m.group(4)))
        return ParsedRelease(
            kind=ReleaseKind.EPISODE, season=season, episodes=eps,
            is_range=len(eps) > 1, raw=raw, matched_pattern="SxxExx",
        )

    # 1в. 1x01-1x10 диапазон серий (1x01-1x10, 1x01-10, 01x01-01x10)
    m_x_range = _RE_XFORMAT_RANGE.search(protected)
    if m_x_range:
        s = int(m_x_range.group(1))
        start, end = int(m_x_range.group(2)), int(m_x_range.group(3))
        if start <= end and (end - start) < 300:
            return ParsedRelease(
                kind=ReleaseKind.EPISODE, season=s, episodes=list(range(start, end + 1)),
                is_range=True, raw=raw, matched_pattern="1x01_range",
            )

    # 1г. "Сезон: 2 / Серии: 1-18 (18)" / "Season 2 Episodes 1-18" — сезон и диапазон серий словами
    m_w_range = _RE_WORDY_SEASON_EP_RANGE.search(protected)
    if m_w_range:
        s = int(m_w_range.group(1))
        start, end = int(m_w_range.group(2)), int(m_w_range.group(3))
        if start <= end and (end - start) < 300:
            return ParsedRelease(
                kind=ReleaseKind.EPISODE, season=s, episodes=list(range(start, end + 1)),
                is_range=True, raw=raw, matched_pattern="wordy_season_ep_range",
            )

    # 1д. "Сезон 1 Серия 5" / "Сезон: 2 / Серия: 5" / "Season 5 Episode 3" — сезон и серия словами (не слитно)
    m = _RE_WORDY_SEASON_EP_SINGLE.search(protected)
    if m:
        return ParsedRelease(
            kind=ReleaseKind.EPISODE, season=int(m.group(1)), episodes=[int(m.group(2))],
            raw=raw, matched_pattern="wordy_season_episode",
        )

    # 1е. OVA/ONA/OAD/спешл/фильм с диапазоном серий (сезон 0)
    m_ova_range = _RE_OVA_ONA_RANGE.search(protected)
    if m_ova_range:
        start, end = int(m_ova_range.group(1)), int(m_ova_range.group(2))
        if start <= end and (end - start) < 300:
            return ParsedRelease(
                kind=ReleaseKind.EPISODE, season=0, episodes=list(range(start, end + 1)),
                is_range=True, raw=raw, matched_pattern="ova_ona_range",
            )

    # 1е2. OVA/ONA/OAD/спешл/фильм с номером серии (сезон 0)
    m_ova_ep = _RE_OVA_ONA_EPISODE.search(protected)
    if m_ova_ep:
        return ParsedRelease(
            kind=ReleaseKind.EPISODE, season=0, episodes=[int(m_ova_ep.group(1))],
            raw=raw, matched_pattern="ova_ona_episode",
        )

    # 1е3. Сезонный спешл без номера ("Season 2 SP", "2 sp.avi", "S01 Special")
    m_s_sp = _RE_SEASON_SP.search(protected)
    if m_s_sp:
        s_num = next((int(g) for g in m_s_sp.groups() if g is not None), 1)
        return ParsedRelease(
            kind=ReleaseKind.EPISODE, season=0, episodes=[1],
            raw=raw, matched_pattern=f"season_{s_num}_special",
        )

    # 1ж. Префиксные сезоны с сериями: "2nd Season - 01", "2nd Season [01-12]", "2-й сезон - 02", "1st Season 05", "5 сезон / 0, 10, 19 серия"
    m_pref_list = _RE_PREFIX_SEASON_EP_LIST.search(protected)
    if m_pref_list:
        s = int(m_pref_list.group(1))
        raw_eps = m_pref_list.group(2)
        eps = [int(x.strip()) for x in raw_eps.split(',') if x.strip().isdigit()]
        if eps:
            return ParsedRelease(
                kind=ReleaseKind.EPISODE, season=s, episodes=eps,
                is_range=False, raw=raw, matched_pattern="prefix_season_ep_list",
            )

    m_pref_range = _RE_PREFIX_SEASON_EP_RANGE.search(protected)
    if m_pref_range:
        s = int(m_pref_range.group(1))
        start, end = int(m_pref_range.group(2)), int(m_pref_range.group(3))
        if start <= end and (end - start) < 300:
            return ParsedRelease(
                kind=ReleaseKind.EPISODE, season=s, episodes=list(range(start, end + 1)),
                is_range=True, raw=raw, matched_pattern="prefix_season_ep_range",
            )

    m_pref_single = _RE_PREFIX_SEASON_EP_SINGLE.search(protected)
    if m_pref_single:
        return ParsedRelease(
            kind=ReleaseKind.EPISODE, season=int(m_pref_single.group(1)), episodes=[int(m_pref_single.group(2))],
            raw=raw, matched_pattern="prefix_season_ep_single",
        )

    # 1з. S-dash / Season-dash с сериями: "S2 - 01", "S02 - 02", "Season 2 - 01", "Сезон 2 - 02", "S2 [01-12]"
    m_sd_list = _RE_S_DASH_EP_LIST.search(protected)
    if m_sd_list:
        s = int(m_sd_list.group(1))
        raw_eps = m_sd_list.group(2)
        eps = [int(x.strip()) for x in raw_eps.split(',') if x.strip().isdigit()]
        if eps:
            return ParsedRelease(
                kind=ReleaseKind.EPISODE, season=s, episodes=eps,
                is_range=False, raw=raw, matched_pattern="s_dash_ep_list",
            )

    m_sd_range = _RE_S_DASH_EP_RANGE.search(protected)
    if m_sd_range:
        s = int(m_sd_range.group(1))
        start, end = int(m_sd_range.group(2)), int(m_sd_range.group(3))
        if start <= end and (end - start) < 300:
            return ParsedRelease(
                kind=ReleaseKind.EPISODE, season=s, episodes=list(range(start, end + 1)),
                is_range=True, raw=raw, matched_pattern="s_dash_ep_range",
            )

    m_sd_single = _RE_S_DASH_EP_SINGLE.search(protected)
    if m_sd_single:
        return ParsedRelease(
            kind=ReleaseKind.EPISODE, season=int(m_sd_single.group(1)), episodes=[int(m_sd_single.group(2))],
            raw=raw, matched_pattern="s_dash_ep_single",
        )

    # 1и. Римские цифры сезонов с серией: "II сезон - 05", "Season II - 03"
    m_roman_ep = _RE_ROMAN_SEASON_EP.search(protected)
    if m_roman_ep:
        r_val = (m_roman_ep.group(1) or m_roman_ep.group(2)).lower()
        if r_val in ROMAN_SEASON_MAP:
            return ParsedRelease(
                kind=ReleaseKind.EPISODE, season=ROMAN_SEASON_MAP[r_val], episodes=[int(m_roman_ep.group(3))],
                raw=raw, matched_pattern="roman_season_ep",
            )

    # 1к. Цифра сезона + серия в скобках [01] или через дефис - 01:
    # "Hell_Mode_Yarikomizuki_no_Gamer_wa_Hai_Sette_2_[04]_[HEVC].mkv", "KonoSuba 2 [05] [1080p].mkv"
    m_s_br = _RE_SEASON_DIGIT_BRACKET_EP.search(protected)
    if m_s_br:
        prefix_before = protected[:m_s_br.start(1)].lower().strip(" _.-")
        if not re.search(r"\b(?:part|часть|cour|кур|vol|volume|том)$", prefix_before, re.IGNORECASE):
            return ParsedRelease(
                kind=ReleaseKind.EPISODE, season=int(m_s_br.group(1)), episodes=[int(m_s_br.group(2))],
                raw=raw, matched_pattern="season_digit_bracket_ep",
            )

    m_s_dash = _RE_SEASON_DIGIT_DASH_EP.search(protected)
    if m_s_dash:
        prefix_before = protected[:m_s_dash.start(1)].lower().strip(" _.-")
        if not re.search(r"\b(?:part|часть|cour|кур|vol|volume|том)$", prefix_before, re.IGNORECASE):
            return ParsedRelease(
                kind=ReleaseKind.EPISODE, season=int(m_s_dash.group(1)), episodes=[int(m_s_dash.group(2))],
                raw=raw, matched_pattern="season_digit_dash_ep",
            )

    # 2a. Мульти-сезонный диапазон (Сезон: 1-3, Сезоны 1-5, S01-S05, Seasons 1-5, 1-10 сезоны, 1-100 сезоны) — ДО единичного сезона!
    m_range = _RE_MULTI_SEASON_RANGE.search(protected)
    if m_range:
        s1 = m_range.group(1) or m_range.group(3) or m_range.group(5) or m_range.group(7)
        s2 = m_range.group(2) or m_range.group(4) or m_range.group(6) or m_range.group(8)
        if s1 and s2:
            s_start, s_end = int(s1), int(s2)
            if 1 <= s_start <= s_end <= 999 and (s_end - s_start) < 200:
                return _season_pack_result(list(range(s_start, s_end + 1)), raw, "season_pack:multi_range")

    m_list = _RE_MULTI_SEASON_LIST.search(protected)
    if m_list:
        raw_list = m_list.group(1) or m_list.group(2)
        s_nums = sorted({int(x.strip()) for x in raw_list.split(",") if x.strip().isdigit()})
        if s_nums:
            return _season_pack_result(s_nums, raw, "season_pack:multi_list")

    # Вспомогательная проверка: содержит ли релиз явный диапазон/номер серии
    def _extract_embedded_episodes(text_to_check: str) -> list[int]:
        m_iz_sub = _RE_RANGE_IZ_N.search(text_to_check)
        if m_iz_sub:
            s_ep, e_ep = int(m_iz_sub.group(1)), int(m_iz_sub.group(2))
            if 0 <= s_ep <= e_ep <= 9999 and (e_ep - s_ep) < 10000:
                return list(range(s_ep, e_ep + 1))
        m_e_sub = re.search(r"\bE(?:P)?\.?(\d{1,4})\s*[-–~]\s*E?(?:P)?\.?(\d{1,4})\b", text_to_check, re.IGNORECASE)
        if m_e_sub:
            s_ep, e_ep = int(m_e_sub.group(1)), int(m_e_sub.group(2))
            if 0 <= s_ep <= e_ep <= 9999 and (e_ep - s_ep) < 10000:
                return list(range(s_ep, e_ep + 1))
        m_br_sub = _RE_BRACKET_RANGE.search(text_to_check)
        if m_br_sub:
            s_ep, e_ep = int(m_br_sub.group(1)), int(m_br_sub.group(2))
            if 0 <= s_ep <= e_ep <= 9999 and (e_ep - s_ep) < 10000:
                return list(range(s_ep, e_ep + 1))
        m_s_iz_sub = _RE_SINGLE_IZ_N.search(text_to_check)
        if m_s_iz_sub:
            curr_ep = int(next(g for g in m_s_iz_sub.groups() if g is not None))
            if 1 <= curr_ep <= 9999:
                return list(range(1, curr_ep + 1))
        m_s_br_sub = _RE_BRACKET_SINGLE_EP.search(text_to_check)
        if m_s_br_sub:
            s_ep = int(m_s_br_sub.group(1))
            if 0 <= s_ep <= 9999:
                return [s_ep]
        return []

    # 2б. Римские цифры сезонов: "I сезон", "II сезон", "III сезон", "Season IV", "Сезон V"
    m_roman = _RE_ROMAN_SEASON.search(protected)
    if m_roman:
        val = (m_roman.group(1) or m_roman.group(2)).lower()
        if val in ROMAN_SEASON_MAP:
            s_num = ROMAN_SEASON_MAP[val]
            embedded_eps = _extract_embedded_episodes(protected)
            if embedded_eps:
                return ParsedRelease(
                    kind=ReleaseKind.EPISODE, season=s_num, episodes=embedded_eps,
                    is_range=len(embedded_eps) > 1, raw=raw, matched_pattern="season_roman_plus_range",
                )
            return _season_pack_result(s_num, raw, "season_pack:roman")

    # 2в. Префиксные порядковые сезоны: "1st Season", "2nd Season", "3rd Season", "1-й сезон", "1 сезон", "01 сезон"
    m_prefix = _RE_PREFIX_SEASON.search(protected)
    if m_prefix:
        s_num = int(m_prefix.group(1))
        embedded_eps = _extract_embedded_episodes(protected)
        if embedded_eps:
            return ParsedRelease(
                kind=ReleaseKind.EPISODE, season=s_num, episodes=embedded_eps,
                is_range=len(embedded_eps) > 1, raw=raw, matched_pattern="season_prefix_plus_range",
            )
        return _season_pack_result(s_num, raw, "season_pack:prefix")

    # 2г. Единичный сезон-пак: S01/Сезон 01 без серии, либо ключевые слова "complete"/"полный сезон"
    m = _RE_SEASON_PACK.search(protected)
    if m:
        s_num = int(m.group(1))
        embedded_eps = _extract_embedded_episodes(protected)
        if embedded_eps:
            return ParsedRelease(
                kind=ReleaseKind.EPISODE, season=s_num, episodes=embedded_eps,
                is_range=len(embedded_eps) > 1, raw=raw, matched_pattern="season_plus_range",
            )
        if not re.search(r"E\.?\d", protected[m.end():m.end() + 6], re.IGNORECASE):
            return _season_pack_result(s_num, raw, "season_pack:Sxx")

    # OVA/ONA/спешл без номера серии — весь блок спешлов целиком (сезон 0).
    # Если в названии присутствует номер серии (например, "13 Robot Chicken ATM Christmas Special.mkv" или "OVA 02"),
    # определяем его как отдельную серию, а не пустой сезон-пак без номеров серий.
    if _RE_OVA_ONA_PACK.search(protected):
        m_lead = re.match(r"^(?:\[[^\s\]]+\][\s._-]*)?(\d{1,3})(?:[\s._-]+|\b)", name)
        if m_lead:
            ep_num = int(m_lead.group(1))
            return ParsedRelease(
                kind=ReleaseKind.EPISODE, season=None, episodes=[ep_num],
                raw=raw, matched_pattern="leading_num_special",
            )
        embedded_eps = _extract_embedded_episodes(protected)
        if embedded_eps:
            return ParsedRelease(
                kind=ReleaseKind.EPISODE, season=0, episodes=embedded_eps,
                is_range=len(embedded_eps) > 1, raw=raw, matched_pattern="ova_embedded_eps",
            )
        m_e = _RE_E_ONLY.search(protected)
        if m_e:
            start = int(m_e.group(1))
            eps = list(range(start, int(m_e.group(2)) + 1)) if m_e.group(2) else [start]
            return ParsedRelease(
                kind=ReleaseKind.EPISODE, season=0, episodes=eps,
                is_range=len(eps) > 1, raw=raw, matched_pattern="ova_e_only",
            )
        m_dash = _RE_DASH_ABSOLUTE.search(protected)
        if m_dash:
            return ParsedRelease(
                kind=ReleaseKind.EPISODE, season=0, episodes=[int(m_dash.group(1))],
                raw=raw, matched_pattern="ova_dash_ep",
            )
        m_lone = _RE_LONE_NUMBER.search(protected)
        if m_lone:
            return ParsedRelease(
                kind=ReleaseKind.EPISODE, season=0, episodes=[int(m_lone.group(1))],
                raw=raw, matched_pattern="ova_lone_num",
            )
        return _season_pack_result(0, raw, "season_pack:ova_ona")

    # "Complete" — сезон-пак, но только если нет явного диапазона серий рядом
    has_explicit_range = (
        _RE_BRACKET_RANGE.search(protected) or _RE_RANGE_IZ_N.search(protected) or _RE_SINGLE_IZ_N.search(protected)
    )
    if _RE_SEASON_PACK_KEYWORDS.search(protected) and not has_explicit_range:
        season_num_match = re.search(r"\d{1,2}", protected)
        season = int(season_num_match.group(0)) if season_num_match else 1
        return _season_pack_result(season, raw, "season_pack:keyword")

    # 2д. Хвостовая цифра сезона перед релиз-группой/качеством в паках:
    # "Hell Mode Yarikomizuki no Gamer wa Hai Sette 2 - AniLiberty [WEBRip 1080p HEVC]"
    m_trail_s = _RE_TRAILING_SEASON_DIGIT_PACK.search(protected)
    if m_trail_s and not (_RE_BRACKET_RANGE.search(protected) or _RE_RANGE_IZ_N.search(protected) or _RE_SINGLE_IZ_N.search(protected) or _RE_BRACKET_SINGLE_EP.search(protected)):
        return _season_pack_result(int(m_trail_s.group(1)), raw, "season_pack:trailing_digit")

    # 3. 1x05
    m = _RE_XFORMAT.search(protected)
    if m:
        return ParsedRelease(
            kind=ReleaseKind.EPISODE, season=int(m.group(1)), episodes=[int(m.group(2))],
            raw=raw, matched_pattern="1x05",
        )

    # 4. Диапазоны и серии N of TOTAL / N из TOTAL:
    # [E01-E12 of 12], [01-12 из 12], [E12 of 12], [E12 of E12], [12 of 12], [E12 из 12], [E06 of 12], [12/12], E12 of 12
    # В конвенциях трекеров [E12 of 12] / [12 of 12] означает 12 серий из 12 (пак серий с 1 по 12).
    m = _RE_RANGE_IZ_N.search(protected)
    if m:
        start, end = int(m.group(1)), int(m.group(2))
        if 0 <= start <= end <= 9999 and (end - start) < 10000:
            return ParsedRelease(
                kind=ReleaseKind.EPISODE, episodes=list(range(start, end + 1)),
                is_range=True, raw=raw, matched_pattern="range_iz_n",
            )

    m = _RE_SINGLE_IZ_N.search(protected)
    if m:
        curr_ep = int(next(g for g in m.groups() if g is not None))
        if 1 <= curr_ep <= 9999:
            ep_list = list(range(1, curr_ep + 1))
            return ParsedRelease(
                kind=ReleaseKind.EPISODE, episodes=ep_list,
                is_range=len(ep_list) > 1, raw=raw, matched_pattern="single_iz_n_range",
            )
        elif curr_ep == 0:
            return ParsedRelease(
                kind=ReleaseKind.EPISODE, episodes=[0],
                is_range=False, raw=raw, matched_pattern="single_iz_n_zero",
            )

    m = _RE_BRACKET_RANGE.search(protected)
    if m:
        start, end = int(m.group(1)), int(m.group(2))
        if 0 <= start <= end <= 9999 and (end - start) < 10000:
            return ParsedRelease(
                kind=ReleaseKind.EPISODE, episodes=list(range(start, end + 1)),
                is_range=True, raw=raw, matched_pattern="[range]",
            )

    # 5. E05 / EP05 (+ диапазон без 'of'/'из')
    m = _RE_E_ONLY.search(protected)
    if m:
        start = int(m.group(1))
        eps = [start]
        if m.group(2):
            eps = list(range(start, int(m.group(2)) + 1))
        return ParsedRelease(
            kind=ReleaseKind.EPISODE, season=None, episodes=eps,
            is_range=len(eps) > 1, raw=raw, matched_pattern="Exx",
        )

    # 6. Одиночная серия в скобках [01] и обычные диапазоны
    m = _RE_BRACKET_SINGLE_EP.search(protected)
    if m:
        ep_num = int(m.group(1))
        if 0 <= ep_num <= 9999:
            return ParsedRelease(
                kind=ReleaseKind.EPISODE, episodes=[ep_num],
                is_range=False, raw=raw, matched_pattern="[single]",
            )
    m = _RE_PLAIN_RANGE.search(protected)
    if m:
        prefix_before = protected[:m.start(1)].lower().strip(" _.-")
        if not re.search(r"\b(?:part|часть|cour|кур|vol|volume|том)$", prefix_before, re.IGNORECASE):
            start, end = int(m.group(1)), int(m.group(2))
            if 0 <= start <= end <= 9999 and (end - start) < 10000:
                return ParsedRelease(
                    kind=ReleaseKind.EPISODE, episodes=list(range(start, end + 1)),
                    is_range=True, raw=raw, matched_pattern="plain_range",
                )

    # 7. Аниме absolute: "- 154", "- 05", "- 001", "- 00", "- 000"
    m = _RE_DASH_ABSOLUTE.search(protected)
    if m:
        return ParsedRelease(
            kind=ReleaseKind.ABSOLUTE, episodes=[int(m.group(1))],
            raw=raw, matched_pattern="dash_absolute",
        )

    # 8. Fallback: одинокое число (защищённая строка исключает года/разрешения)
    m = _RE_LONE_NUMBER.search(protected)
    if m:
        num = int(m.group(1))
        if 0 <= num <= 9999:
            return ParsedRelease(
                kind=ReleaseKind.ABSOLUTE, episodes=[num],
                raw=raw, matched_pattern="lone_number",
            )

    return ParsedRelease(kind=ReleaseKind.UNKNOWN, raw=raw, matched_pattern="none")


# ---------------------------------------------------------------------------
# Определение «метки сезона» для валидации релизов при автоматическом поиске
# ---------------------------------------------------------------------------

# Мультисезонные диапазоны:
# Сезон: 1-3, Сезоны: 1-3, Season: 1-10, S01-S05, S1-S5, 1-10 сезоны, 1-100 сезоны
_SEASON_LABEL_RANGE_RE = _RE_MULTI_SEASON_RANGE
_SEASON_LABEL_LIST_RE = _RE_MULTI_SEASON_LIST

# Явный номер сезона во всех вариациях:
# S01, S1, (S01), (S1), s01, Season 1, Season.1, Season_1,
# Сезон 1, Сезон: 2, Сезон.1, Сез. 1, Сез.1, сезон_01 и т.д.
_SEASON_LABEL_NUMBERED_RE = re.compile(
    r"""
    (?:
        \(\s*S(\d{1,3})\s*\)                                # (S01) или (S1)
    |
        (?:S(?:easons?)?|Сез(?:он(?:ы|а)?)?|sezon(?:y|i|a)?|sez) # S / Season / Seasons / Сезон / Сезоны / Сез / Sezon
        [:\.\s_]*                                           # разделитель (включая двоеточие!)
        (\d{1,3})                                           # номер сезона
        \b
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)

# «Final Season», «Last Season», «Финальный сезон», «Последний сезон», «Final Arc»
_SEASON_LABEL_FINAL_RE = re.compile(
    r"""
    \b(?:
        Final      [\s_\-]+  (?:Season|Arc|Part|Chapter|Cour)
    |   Last       [\s_\-]+  (?:Season|Arc|Part)
    |   Финальн\w+ [\s_\-]+  Сезон\w*
    |   Последн\w+ [\s_\-]+  Сезон\w*
    |   Fin\b                                # совсем короткий суффикс-тег некоторых групп
    )\b
    """,
    re.IGNORECASE | re.VERBOSE,
)

# «Complete Series / Collection / Pack», «Full Series», «Полная коллекция / серия», «Full», «Complete», «TV+OVA»
_SEASON_LABEL_COMPLETE_RE = re.compile(
    r"""
    (?:
        \bComplete(?!\s*(?:edition|remix|version))\b  [\s_\-]*  (?:Series|Collection|Box[\s_\-]?Set|Pack|Season)?
    |   \bFull\b(?!\s*(?:HD|High|Speed|SBS|OU))        [\s_\-]*  (?:Series|Collection|Pack|Season|Set)?
    |   \bПолн\w+                                     [\s_\-]+  (?:коллекц\w+|сери\w+|сезон\w*|пак\w*)
    |   \bВесь                                        [\s_\-]+  сериал
    |   \bПолный                                      [\s_\-]+  (?:сезон|сериал)
    |   \bВсе                                         [\s_\-]+  сезоны
    |   \b(?:Антология|Anthology)\b
    |   \bTV\s*[\+_&]\s*(?:OVA|ONA|OAD|SP|Specials?|Спешл\w*)\b
    |   \[TV\s*[\+_&]\s*(?:OVA|ONA|OAD|SP|Specials?|Спешл\w*)\]
    |   \(TV\s*[\+_&]\s*(?:OVA|ONA|OAD|SP|Specials?|Спешл\w*)\)
    |   \b\d{1,4}\s*[-–~]\s*\d{1,4}\s*\+\s*\d{1,3}\b
    |   \[Full\]
    |   \(Full\)
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)

# OVA / ONA / Special / Спешл — традиционно сезон 0
_SEASON_LABEL_OVA_RE = re.compile(
    r"\b(OVA|ONA|Special|Спешл)\b",
    re.IGNORECASE,
)

_NOISE_FOR_SEASON_DIGIT_RE = re.compile(
    r"""
    \[[^\]]*\]
    |
    \([^\)]*(?:из|of|\b\d+[-–~]\d+\b|сери|эпизод|eps?|1080p|720p|2160p|web|rip|dl|tv|bd|dvd|dub|sub|rus|jap|eng)[^\)]*\)
    |
    \b\d{1,4}\s*[-–~]\s*\d{1,4}\s*(?:из|of|iz|\/|\|)\s*\d{1,4}\+?\b
    |
    \b\d{1,4}\s*[-–~]\s*\d{1,4}\b
    |
    \b(?:из|of|iz)\s*\d{1,4}\+?\b
    |
    \b\d{1,4}\s*(?:эп(?:изод(?:ов|а)?)?|сери[йия]|eps?|episodes?|выпуск(?:ов|а)?)\b
    |
    \b(?:lvl?|level|уров(?:ень|ня|ню|нем|не))\s*[:\.]?\s*\d+\b
    |
    \b\d+\s*уров(?:ень|ня|ню|нем|не)\b
    |
    \b(?:19|20)\d{2}\b
    |
    \b\d+[-._ ]?bit\b
    |
    \b(?:5\.1|7\.1|2\.0)\b
    |
    \b\d+\s*(?:fps|hz)\b
    |
    \b(?:2160p|1080p|720p|480p|576p|hevc|x264|x265|h264|h265|av1|bluray|bdrip|web-?dl|webrip|hdtv|remux)\b
    |
    \b(?:movie\s*\d*|film\s*\d*|фильм\s*\d*|the\s+movie|ova\s*\d*|ona\s*\d*|special\s*\d*|спешл\s*\d*)\b
    """,
    re.IGNORECASE | re.VERBOSE,
)
_SEASON_LABEL_TRAILING_DIGIT_RE = re.compile(
    r"""
    (?:
        \b(?:Part|Часть|Книга|Book|Cour|Кур)\s*[:\.]?\s*([1-9]|1[0-9]|20)\b
    |
        (?:^|\s|[._\-])(?:TV[-._ ]?|S)?([2-9]|1[0-9]|20)\b\s*$
    |
        \b(?:Season|Сезон|Сез)\.?\s*([1-9]|1[0-9]|20)\b
    )
    """,
    re.IGNORECASE | re.VERBOSE,
)


def detect_season_label(release_name: str) -> dict:
    """
    Определяет «метку сезона» из названия релиза для последующей валидации
    при автопоиске — чтобы не захватывать релизы чужого сезона.

    Возвращает один из словарей:
    - {"type": "range", "seasons": [1, 2, 3, ...]} — мультисезонный диапазон (Сезоны 1-5, S01-S05, Сезон: 1-3, 1-100 сезоны)
    - {"type": "numbered", "season": N}             — явный номер сезона (S01, Season 1, 1st Season, 1 сезон, I сезон, S01 Complete, S01 Batch и т.д.)
    - {"type": "final"}                              — «Final Season», «Финальный сезон» и т.п.
    - {"type": "complete"}                           — «Complete Series», «Full», «Полная коллекция», «Все сезоны»
    - {"type": "ova_ona"}                            — OVA/ONA/Special/Movie (сезон 0)
    - {"type": "none"}                               — сезон в названии не указан

    Порядок: range/list → roman → prefix → numbered/sxx_range → wordy → complete → final → ova_ona → trailing_digit → none.
    """
    name = release_name or ""

    m_multi_s_ep = _RE_MULTI_SEASON_EP_RANGE.search(name)
    if m_multi_s_ep:
        s1, s2 = int(m_multi_s_ep.group(1)), int(m_multi_s_ep.group(2))
        if 1 <= s1 <= s2 <= 100:
            return {"type": "range", "seasons": list(range(s1, s2 + 1))}

    # 1. Мультисезонный диапазон (Сезон: 1-3, Сезоны 1-5, S01-S05, Seasons 1-10, 1-100 сезоны) — проверяем ДО единичного сезона!
    m_range = _SEASON_LABEL_RANGE_RE.search(name)
    if m_range:
        start_raw = m_range.group(1) or m_range.group(3) or m_range.group(5) or m_range.group(7)
        end_raw = m_range.group(2) or m_range.group(4) or m_range.group(6) or m_range.group(8)
        if start_raw and end_raw:
            start, end = int(start_raw), int(end_raw)
            if 1 <= start <= end <= 999:
                return {"type": "range", "seasons": list(range(start, end + 1))}

    m_list = _SEASON_LABEL_LIST_RE.search(name)
    if m_list:
        raw_list = m_list.group(1) or m_list.group(2)
        s_nums = sorted({int(x.strip()) for x in raw_list.split(",") if x.strip().isdigit()})
        if s_nums:
            return {"type": "range", "seasons": s_nums}

    # 2. Римские цифры сезонов: "I сезон", "II сезон", "III сезон", "Season IV", "Сезон V"
    m_roman = _RE_ROMAN_SEASON.search(name)
    if m_roman:
        val = (m_roman.group(1) or m_roman.group(2)).lower()
        if val in ROMAN_SEASON_MAP:
            return {"type": "numbered", "season": ROMAN_SEASON_MAP[val]}

    # 3. Префиксные порядковые сезоны: "1st Season", "2nd Season", "1 сезон", "2-й сезон", "01 сезон"
    m_prefix = _RE_PREFIX_SEASON.search(name)
    if m_prefix:
        return {"type": "numbered", "season": int(m_prefix.group(1))}

    # 4. Явный номер сезона со словом S/Season/Сезон (S01, Season 1, Сезон 1, S01 COMPLETE, S01 Full Season, S01 Pack, S01 Batch)
    m = _SEASON_LABEL_NUMBERED_RE.search(name)
    if m:
        raw_num = m.group(1) or m.group(2)
        return {"type": "numbered", "season": int(raw_num)}

    # 4б. SxxExx-Exx / 1x01-1x10 / S01E01 явный сезон перед сериями
    m_sxx = _RE_SXXEXX_RANGE.search(name) or _RE_XFORMAT_RANGE.search(name) or _RE_SXXEXX_MULTI.search(name)
    if m_sxx:
        return {"type": "numbered", "season": int(m_sxx.group(1))}

    # 4в. "Сезон 1 Серия 5" / "Сезон: 2 / Серии: 1-18"
    m_wordy = _RE_WORDY_SEASON_EP_RANGE.search(name) or _RE_WORDY_SEASON_EP_SINGLE.search(name)
    if m_wordy:
        return {"type": "numbered", "season": int(m_wordy.group(1))}

    # 5. «Complete Series» / «Full Series» / «Все сезоны» / «Полный сериал» / «Anthology»
    if _SEASON_LABEL_COMPLETE_RE.search(name):
        return {"type": "complete"}

    # 6. «Final Season»
    if _SEASON_LABEL_FINAL_RE.search(name):
        return {"type": "final"}

    # 7. OVA / ONA / Special / Movie / Фильм
    if _SEASON_LABEL_OVA_RE.search(name) or re.search(r"\b(?:movie|film|фильм|the\s+movie)\b", name, re.IGNORECASE):
        return {"type": "ova_ona"}

    # 8. Одиночная цифра сезона/части в названии тайтла («Re:Zero 3», «Bleach 3», «Пацаны 4», «Fargo 5», «TV-2»)
    segments = re.split(r"\s*[/|]\s*", name)
    for seg in segments:
        cleaned = _NOISE_FOR_SEASON_DIGIT_RE.sub(" ", seg)
        cleaned = re.sub(r"[\[\](){}]", " ", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        m_digit = _SEASON_LABEL_TRAILING_DIGIT_RE.search(cleaned)
        if m_digit:
            s_val = int(m_digit.group(1) or m_digit.group(2) or m_digit.group(3))
            if 1 <= s_val <= 20:
                return {"type": "numbered", "season": s_val}

    return {"type": "none"}

