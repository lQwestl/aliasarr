"""
Модуль парсинга релиз-групп (на основе Sonarr ReleaseGroupParser.cs).
Извлекает релиз-группу или саб-группу из названия релиза.
"""

from __future__ import annotations

import os
import re
from typing import Optional

# Регулярки для аниме саб-групп в начале: [SubsPlease], [Erai-raws], [AniLibria], [Judas]
_ANIME_GROUP_RE = re.compile(r"^\[(?P<group>[^\]]+)\]", re.IGNORECASE)

# Регулярки для известных русскоязычных студий озвучки в скобках или в тексте
_RU_STUDIOS = [
    "LostFilm", "HDRezka", "Red Head Sound", "RHS", "NewStudio", "AlexFilm",
    "TVShows", "Кубик в Кубе", "Kubik v Kube", "Jaskier", "AniLibria", "AniMedia",
    "Shiza Project", "Studio Band", "DreamRecords", "Persona99", "ColdFilm",
    "BaibaKo", "Good People", "Пифагор", "Невафильм", "Кириллица", "Мосфильм"
]
_RU_STUDIO_PATTERN = re.compile(r"\b(?P<group>" + "|".join(re.escape(s) for s in _RU_STUDIOS) + r")\b", re.IGNORECASE)

# Регулярка для группы в конце релиза: -GROUPNAME[rarbg] или [GROUP] в конце
_TRAILING_GROUP_RE = re.compile(
    r"-(?P<group>[A-Za-z0-9]+(?:-[A-Za-z0-9]+)?)(?:\[[a-z0-9._-]+\])?$",
    re.IGNORECASE
)

_BRACKET_TRAILING_GROUP_RE = re.compile(r"\[(?P<group>[A-Za-z0-9_-]+)\]$", re.IGNORECASE)

_INVALID_GROUPS = {
    "hdtv", "sdtv", "webrip", "webdl", "dl", "web", "bluray", "dvd", "dvdrip", "remux",
    "x264", "x265", "hevc", "av1", "xvid", "divx", "1080p", "720p", "2160p", "480p",
    "aac", "flac", "mp3", "dts", "ac3", "eac3", "proper", "repack", "rus", "eng"
}


def parse_release_group(title: str) -> Optional[str]:
    """
    Извлекает имя релиз-группы из строки названия релиза/файла.
    """
    if not title:
        return None

    # Отрезаем расширение файла, если есть
    root, ext = os.path.splitext(title.strip())
    if ext.lower() in {".mkv", ".mp4", ".avi", ".ts", ".m2ts", ".torrent"}:
        title = root.strip()
    else:
        title = title.strip()

    # 1. Проверяем аниме группу в квадратных скобках в начале
    anime_match = _ANIME_GROUP_RE.match(title)
    if anime_match:
        grp = anime_match.group("group").strip()
        if grp.lower() not in _INVALID_GROUPS:
            return grp

    # 2. Проверяем наличие известной студии озвучки (LostFilm, AniLibria, RHS, HDRezka...)
    ru_match = _RU_STUDIO_PATTERN.search(title)
    if ru_match:
        return ru_match.group("group").strip()

    # 3. Проверяем суффикс через дефис в конце (-FLUX, -NTb, -CMRG, -ION10...)
    # Очищаем скобки типа [rarbg] или [eztv] на конце перед проверкой
    clean_end = re.sub(r"\[[a-z0-9._-]+\]$", "", title, flags=re.IGNORECASE).strip()
    if "-" in clean_end:
        last_part = clean_end.split("-")[-1].strip()
        last_part = re.sub(r"[\[\](){}<>]+", "", last_part).strip()
        # Если последний фрагмент валиден и не является суффиксом качества типа DL или Ray
        if last_part.lower() not in _INVALID_GROUPS and not last_part.isdigit() and len(last_part) >= 2:
            return last_part

    # 4. Проверяем группу в скобках на конце
    bracket_match = _BRACKET_TRAILING_GROUP_RE.search(title)
    if bracket_match:
        grp = bracket_match.group("group").strip()
        if grp.lower() not in _INVALID_GROUPS and not grp.isdigit():
            return grp

    return None
