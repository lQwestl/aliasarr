"""
Продвинутый органайзер и генератор имён файлов/путей (на основе Sonarr FileNameBuilder.cs).
Поддерживает стандартные токены Sonarr для сериалов, фильмов и аниме.
"""

from __future__ import annotations

import re
from typing import List, Optional

from app.services.custom_formats import MatchedCustomFormat
from app.services.quality import QualityInfo


# Очистка запрещённых символов в путях файловой системы
_INVALID_CHARS_RE = re.compile(r'[<>:"/\\|?*]')


def clean_filename(name: str) -> str:
    """Очищает строку от запрещённых символов файловой системы."""
    if not name:
        return ""
    cleaned = _INVALID_CHARS_RE.sub("", name).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip(" .")


def clean_title(title: str) -> str:
    """
    Создаёт безопасное имя тайтла без спецсимволов и знаков препинания.
    """
    if not title:
        return ""
    cleaned = re.sub(r"['`’]", "", title)
    cleaned = re.sub(r"[^\w\s\d.-]", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def title_the(title: str) -> str:
    """
    Переносит артикль The в конец: 'The Series' -> 'Series, The'.
    """
    if not title:
        return ""
    if title.lower().startswith("the "):
        return f"{title[4:]}, The"
    if title.lower().startswith("a "):
        return f"{title[2:]}, A"
    if title.lower().startswith("an "):
        return f"{title[3:]}, An"
    return title


def clean_show_title_and_year(title: str, year: Optional[int] = None) -> tuple[str, Optional[int]]:
    """
    Удаляет дублирующийся год из названия тайтла, если год уже указан отдельно или извлекается из названия.
    Например:
      'Severance (2022)', 2022 -> ('Severance', 2022)
      'Severance (2022)', None -> ('Severance', 2022)
      'Blade Runner 2049', 2017 -> ('Blade Runner 2049', 2017)
      '2001: A Space Odyssey', 1968 -> ('2001: A Space Odyssey', 1968)
    """
    if not title:
        return "", year
    t = title.strip()
    m = re.search(r"\s+[\(\[](\d{4})[\)\]]$", t)
    if m:
        extracted = int(m.group(1))
        if 1900 <= extracted <= 2100:
            if year is None or year == extracted:
                return t[:m.start()].strip(), year or extracted
    return t, year


class FileNameBuilder:
    @staticmethod
    def build_file_name(
        template: str,
        title: str,
        year: Optional[int] = None,
        season_number: Optional[int] = 1,
        episode_number: Optional[int] = 1,
        absolute_number: Optional[int] = None,
        episode_title: Optional[str] = None,
        quality: Optional[QualityInfo] = None,
        release_group: Optional[str] = None,
        custom_formats: Optional[List[MatchedCustomFormat]] = None,
        content_type: str = "series",
        extension: str = ".mkv",
    ) -> str:
        """
        Формирует имя файла на основе шаблона и токенов.
        """
        if not template:
            if content_type == "movie":
                template = "{Movie Title} ({Release Year}) {Quality Full}"
            else:
                template = "{Series Title} - S{season:00}E{episode:00} - {Episode Title} {Quality Full}"

        res = template

        # Токены сериала / фильма
        clean_t = clean_title(title)
        title_with_the = title_the(title)
        yr_str = str(year) if year else ""
        title_yr = f"{title} ({yr_str})" if yr_str else title

        res = re.sub(r"\{Series Title\}", clean_filename(title), res, flags=re.IGNORECASE)
        res = re.sub(r"\{Series CleanTitle\}", clean_filename(clean_t), res, flags=re.IGNORECASE)
        res = re.sub(r"\{Series TitleThe\}", clean_filename(title_with_the), res, flags=re.IGNORECASE)
        res = re.sub(r"\{Series TitleYear\}", clean_filename(title_yr), res, flags=re.IGNORECASE)

        res = re.sub(r"\{Movie Title\}", clean_filename(title), res, flags=re.IGNORECASE)
        res = re.sub(r"\{Movie CleanTitle\}", clean_filename(clean_t), res, flags=re.IGNORECASE)
        res = re.sub(r"\{Release Year\}", yr_str, res, flags=re.IGNORECASE)

        # Токены сезона и серий
        s_num = season_number if season_number is not None else 1
        e_num = episode_number if episode_number is not None else 1
        abs_num = absolute_number if absolute_number is not None else e_num

        res = re.sub(r"\{season:00\}", f"{s_num:02d}", res, flags=re.IGNORECASE)
        res = re.sub(r"\{season:0\}", f"{s_num:01d}", res, flags=re.IGNORECASE)
        res = re.sub(r"\{season\}", f"{s_num}", res, flags=re.IGNORECASE)

        res = re.sub(r"\{episode:000\}", f"{e_num:03d}", res, flags=re.IGNORECASE)
        res = re.sub(r"\{episode:00\}", f"{e_num:02d}", res, flags=re.IGNORECASE)
        res = re.sub(r"\{episode:0\}", f"{e_num:01d}", res, flags=re.IGNORECASE)
        res = re.sub(r"\{episode\}", f"{e_num}", res, flags=re.IGNORECASE)

        res = re.sub(r"\{absolute:000\}", f"{abs_num:03d}", res, flags=re.IGNORECASE)
        res = re.sub(r"\{absolute:00\}", f"{abs_num:02d}", res, flags=re.IGNORECASE)
        res = re.sub(r"\{absolute\}", f"{abs_num}", res, flags=re.IGNORECASE)

        ep_title_clean = clean_filename(episode_title or f"Episode {e_num}")
        res = re.sub(r"\{Episode Title\}", ep_title_clean, res, flags=re.IGNORECASE)
        res = re.sub(r"\{Episode CleanTitle\}", clean_title(episode_title or ""), res, flags=re.IGNORECASE)

        # Качество и MediaInfo
        q_name = quality.name if quality else "WEBDL-1080p"
        q_full = f"{q_name} {quality.modifier}" if quality and quality.modifier else q_name
        vcodec = (quality.video_codec if quality else None) or "x264"
        acodec = (quality.audio_codec if quality else None) or "AAC"
        achannels = (quality.audio_channels if quality else None) or "2.0"
        hdr = (quality.dynamic_range if quality else None) or ""

        res = re.sub(r"\{Quality Full\}", q_full, res, flags=re.IGNORECASE)
        res = re.sub(r"\{Quality Title\}", q_name, res, flags=re.IGNORECASE)
        res = re.sub(r"\{MediaInfo VideoCodec\}", vcodec, res, flags=re.IGNORECASE)
        res = re.sub(r"\{MediaInfo AudioCodec\}", acodec, res, flags=re.IGNORECASE)
        res = re.sub(r"\{MediaInfo AudioChannels\}", achannels, res, flags=re.IGNORECASE)
        res = re.sub(r"\{MediaInfo VideoDynamicRange\}", hdr, res, flags=re.IGNORECASE)

        # Релиз группа
        grp = release_group or "Aliasarr"
        res = re.sub(r"\{Release Group\}", clean_filename(grp), res, flags=re.IGNORECASE)

        # Кастомные форматы
        cf_tags = ""
        if custom_formats:
            cf_names = [cf.name for cf in custom_formats if cf.include_custom_format_when_renaming]
            if cf_names:
                cf_tags = " " + " ".join(f"[{cf}]" for cf in cf_names)
        res = re.sub(r"\{Custom Formats\}", cf_tags.strip(), res, flags=re.IGNORECASE)

        # Финальная очистка
        res = re.sub(r"\s+", " ", res).strip()
        res = clean_filename(res)

        if extension:
            ext = extension if extension.startswith(".") else f".{extension}"
            res = f"{res}{ext}"

        return res

    @staticmethod
    def build_season_folder_name(template: str, season_number: int) -> str:
        if not template:
            template = "Сезон {season}"
        res = template
        res = re.sub(r"\{season:00\}", f"{season_number:02d}", res, flags=re.IGNORECASE)
        res = re.sub(r"\{season\}", f"{season_number}", res, flags=re.IGNORECASE)
        return clean_filename(res)
