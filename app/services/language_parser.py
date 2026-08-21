"""
Модуль парсинга языков релизов (на основе правил Sonarr LanguageParser.cs).
Распознаёт аудиодорожки и субтитры в названиях релизов и торрентов.
"""

from __future__ import annotations

import enum
import re
from typing import List, Set


class Language(str, enum.Enum):
    UNKNOWN = "Unknown"
    ENGLISH = "English"
    RUSSIAN = "Russian"
    JAPANESE = "Japanese"
    GERMAN = "German"
    FRENCH = "French"
    SPANISH = "Spanish"
    ITALIAN = "Italian"
    CHINESE = "Chinese"
    KOREAN = "Korean"
    UKRAINIAN = "Ukrainian"
    PORTUGUESE = "Portuguese"
    POLISH = "Polish"
    DUTCH = "Dutch"
    CZECH = "Czech"
    HUNGARIAN = "Hungarian"
    TURKISH = "Turkish"
    MULTI = "Multi"
    DUAL = "Dual Audio"
    ORIGINAL = "Original"


# Регулярные выражения для распознавания языков в релизах
_LANG_PATTERNS = [
    (Language.MULTI, re.compile(r"\b(multi(?:[-_. ]?(?:audio|lang|languages?|\d+))?|multisubs?|мульти(?:озвучка|голосый)?)\b", re.IGNORECASE)),
    (Language.DUAL, re.compile(r"\b(dual[-_. ]?audio|2audio|двухголосый|двуязычный)\b", re.IGNORECASE)),
    (Language.RUSSIAN, re.compile(r"\b(rus(?:sian)?|ru|рус(?:ский)?|дубляж|дублированный|мво|пво|дво|lostfilm|red\s*head\s*sound|hdrezka|anilibria|animedia|shiza\s*project|flame\s*dub|studio\s*band)\b", re.IGNORECASE)),
    (Language.ENGLISH, re.compile(r"\b(eng(?:lish)?|en|англ(?:ийский)?|vo)\b", re.IGNORECASE)),
    (Language.JAPANESE, re.compile(r"\b(jap(?:anese)?|jp|jpn|япон(?:ский)?)\b", re.IGNORECASE)),
    (Language.UKRAINIAN, re.compile(r"\b(ukr(?:ainian)?|ua|укр(?:аинский)?)\b", re.IGNORECASE)),
    (Language.GERMAN, re.compile(r"\b(ger(?:man)?|de|deutsch)\b", re.IGNORECASE)),
    (Language.FRENCH, re.compile(r"\b(fre(?:nch)?|fra|vff|vfq|truefrench|french)\b", re.IGNORECASE)),
    (Language.SPANISH, re.compile(r"\b(spa(?:nish)?|esp(?:añol)?|castellano)\b", re.IGNORECASE)),
    (Language.ITALIAN, re.compile(r"\b(ita(?:lian)?)\b", re.IGNORECASE)),
    (Language.CHINESE, re.compile(r"\b(chi(?:nese)?|zho|mandarin|cantonese|\[(?:ch[st]|big5|gb)\]|简|繁|国语)\b", re.IGNORECASE)),
    (Language.KOREAN, re.compile(r"\b(kor(?:ean)?|корейский)\b", re.IGNORECASE)),
    (Language.POLISH, re.compile(r"\b(pol(?:ish)?|pl|pldub|lekpl)\b", re.IGNORECASE)),
    (Language.PORTUGUESE, re.compile(r"\b(por(?:tuguese)?|pt|pt-br)\b", re.IGNORECASE)),
]


def parse_languages(title: str) -> List[Language]:
    """
    Извлекает список языков из названия релиза.
    """
    if not title:
        return [Language.UNKNOWN]

    found: Set[Language] = set()

    for lang, pattern in _LANG_PATTERNS:
        if pattern.search(title):
            found.add(lang)

    if not found:
        # Если кириллический заголовок без явных меток — по умолчанию содержит русский
        if re.search(r"[\u0400-\u04ff]", title):
            found.add(Language.RUSSIAN)
        else:
            found.add(Language.ENGLISH)

    return sorted(list(found), key=lambda x: x.value)


def get_language_badges(languages: List[Language]) -> List[str]:
    """
    Возвращает список коротких кодов для UI (напр. ['RU', 'EN', 'JP']).
    """
    mapping = {
        Language.RUSSIAN: "RU",
        Language.ENGLISH: "EN",
        Language.JAPANESE: "JP",
        Language.MULTI: "MULTI",
        Language.DUAL: "DUAL",
        Language.UKRAINIAN: "UA",
        Language.GERMAN: "DE",
        Language.FRENCH: "FR",
        Language.SPANISH: "ES",
        Language.ITALIAN: "IT",
        Language.CHINESE: "ZH",
        Language.KOREAN: "KO",
        Language.PORTUGUESE: "PT",
        Language.POLISH: "PL",
    }
    badges = []
    for l in languages:
        code = mapping.get(l)
        if code and code not in badges:
            badges.append(code)
    return badges or ["EN"]
