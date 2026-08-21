"""
Определение качества релиза по имени файла/топика и ранжирование
относительно allowed_qualities в QualityProfile (на основе правил Sonarr QualityParser.cs).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional

# Порядок от худшего к лучшему — индекс используется как ранг (0-N)
QUALITY_ORDER = [
    "SDTV",
    "DVD",
    "DVDRip",
    "HDTV-720p",
    "WEBRip-720p",
    "WEBDL-720p",
    "Bluray-720p",
    "HDTV-1080p",
    "WEBRip-1080p",
    "WEBDL-1080p",
    "Bluray-1080p",
    "Remux-1080p",
    "HDTV-2160p",
    "WEBRip-2160p",
    "WEBDL-2160p",
    "Bluray-2160p",
    "Remux-2160p",
]

# Регулярные выражения источников (Sources)
_REMUX_RE = re.compile(r"\b(remux|bdremux|uhd[-_. ]?remux)\b", re.IGNORECASE)
_BLURAY_RE = re.compile(r"\b(bluray|blu-ray|bdrip|brrip|bdmux|bd(?!$)|hd-?dvd)\b", re.IGNORECASE)
_WEBDL_RE = re.compile(r"\b(web[-_. ]?dl(?:mux)?|webdl|amazonhd|ituneshd|netflixu?hd|webhd|hbomaxhd|disneyhd|[. ]web[. ](?:[xh][ .]?26[456]|avc|hevc|ddp?[ .]?5[. ]1))\b", re.IGNORECASE)
_WEBRIP_RE = re.compile(r"\b(webrip|web-rip|web\b)", re.IGNORECASE)
_HDTV_RE = re.compile(r"\b(hdtv|pdtv|dsr|tvrip)\b", re.IGNORECASE)
_DVDRIP_RE = re.compile(r"\b(dvdrip|dvd-rip)\b", re.IGNORECASE)
_DVD_RE = re.compile(r"\b(dvd|dvd9|dvd5|ntsc|pal|xvidvd)\b", re.IGNORECASE)

# Разрешения
_RES_RE = re.compile(r"\b(?P<res>2160p|1080p|1080i|720p|576p|480p|480i|360p|4k|uhd|fhd)\b", re.IGNORECASE)

# Кодеки видео
_VCODEC_RE = re.compile(r"\b(?P<vcodec>x265|h265|hevc|x264|h264|avc|av1|xvid|divx|vc-?1|mpeg2)\b", re.IGNORECASE)

# Кодеки аудио
_ACODEC_RE = re.compile(r"\b(?P<acodec>truehd(?:\.atmos)?|atmos|dts-hd(?:\.ma)?|dts-x|dts|eac3|ddp(?:\+)?|dd\+?|ac3|flac|aac|mp3|pcm|lpcm)\b", re.IGNORECASE)
_ACHANNELS_RE = re.compile(r"\b(?P<channels>7\.1|5\.1|2\.0|2ch|6ch|8ch)\b", re.IGNORECASE)

# HDR и Dynamic Range
_HDR_RE = re.compile(r"\b(?P<hdr>dv(?:\.hdr)?|dolby[-_. ]?vision|hdr10\+|hdr10|hdr|hlg)\b", re.IGNORECASE)

# Модификаторы качества (Proper, Repack, Real, v2, v3...)
_MODIFIER_RE = re.compile(r"\b(?P<mod>proper|repack\d?|rerip\d?|real|v[2-4])\b", re.IGNORECASE)


@dataclass
class QualityInfo:
    name: str
    rank: int  # индекс в QUALITY_ORDER, выше = лучше
    source: str = "SDTV"
    resolution: str = "480p"
    modifier: Optional[str] = None
    video_codec: Optional[str] = None
    audio_codec: Optional[str] = None
    audio_channels: Optional[str] = None
    dynamic_range: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "rank": self.rank,
            "source": self.source,
            "resolution": self.resolution,
            "modifier": self.modifier,
            "video_codec": self.video_codec,
            "audio_codec": self.audio_codec,
            "audio_channels": self.audio_channels,
            "dynamic_range": self.dynamic_range,
        }


def parse_quality(release_name: str) -> QualityInfo:
    """
    Разбирает строку названия релиза на качество, кодеки, HDR и модификаторы.
    """
    if not release_name:
        return QualityInfo(name="SDTV", rank=0, source="SDTV", resolution="480p")

    # 1. Разрешение
    res_match = _RES_RE.search(release_name)
    raw_res = res_match.group("res").lower() if res_match else ""
    if raw_res in ("2160p", "4k", "uhd"):
        resolution = "2160p"
    elif raw_res in ("1080p", "1080i", "fhd"):
        resolution = "1080p"
    elif raw_res == "720p":
        resolution = "720p"
    elif raw_res in ("576p", "480p", "480i"):
        resolution = "480p"
    elif raw_res == "360p":
        resolution = "360p"
    else:
        resolution = "480p"

    # 2. Источник
    if _REMUX_RE.search(release_name):
        source = "Remux"
    elif _BLURAY_RE.search(release_name):
        source = "Bluray"
    elif _WEBDL_RE.search(release_name):
        source = "WEBDL"
    elif _WEBRIP_RE.search(release_name):
        source = "WEBRip"
    elif _HDTV_RE.search(release_name):
        source = "HDTV"
    elif _DVDRIP_RE.search(release_name):
        source = "DVDRip"
    elif _DVD_RE.search(release_name):
        source = "DVD"
    else:
        source = "HDTV" if resolution in ("720p", "1080p", "2160p") else "SDTV"

    # 3. Формирование канонического имени качества
    if source in ("DVDRip", "DVD", "SDTV"):
        canonical_name = source
    else:
        canonical_name = f"{source}-{resolution}"

    # Если такого качества нет в QUALITY_ORDER, подбираем ближайшее
    if canonical_name not in QUALITY_ORDER:
        if resolution == "2160p":
            canonical_name = "WEBDL-2160p"
        elif resolution == "1080p":
            canonical_name = "WEBDL-1080p"
        elif resolution == "720p":
            canonical_name = "WEBDL-720p"
        else:
            canonical_name = "SDTV"

    try:
        rank = QUALITY_ORDER.index(canonical_name)
    except ValueError:
        rank = 0

    # 4. Видеокодек
    vcodec_match = _VCODEC_RE.search(release_name)
    video_codec = vcodec_match.group("vcodec").upper() if vcodec_match else None
    if video_codec:
        if video_codec in ("X265", "H265"):
            video_codec = "HEVC"
        elif video_codec in ("X264", "H264"):
            video_codec = "x264"

    # 5. Аудиокодек и каналы
    acodec_match = _ACODEC_RE.search(release_name)
    audio_codec = acodec_match.group("acodec").upper() if acodec_match else None
    if audio_codec:
        if "ATMOS" in audio_codec:
            audio_codec = "Atmos"
        elif "TRUEHD" in audio_codec:
            audio_codec = "TrueHD"
        elif "DTS-HD" in audio_codec:
            audio_codec = "DTS-HD MA"
        elif audio_codec in ("EAC3", "DDP", "DD+"):
            audio_codec = "EAC3"
        elif audio_codec in ("AC3", "DD"):
            audio_codec = "AC3"

    achannels_match = _ACHANNELS_RE.search(release_name)
    audio_channels = achannels_match.group("channels") if achannels_match else None

    # 6. Dynamic Range (HDR / Dolby Vision)
    hdr_match = _HDR_RE.search(release_name)
    dynamic_range = None
    if hdr_match:
        raw_hdr = hdr_match.group("hdr").upper()
        if "DV" in raw_hdr or "DOLBY" in raw_hdr:
            dynamic_range = "DV" if "HDR" not in raw_hdr else "DV HDR"
        elif "HDR10+" in raw_hdr:
            dynamic_range = "HDR10+"
        elif "HDR10" in raw_hdr:
            dynamic_range = "HDR10"
        elif "HDR" in raw_hdr:
            dynamic_range = "HDR"
        elif "HLG" in raw_hdr:
            dynamic_range = "HLG"

    # 7. Модификатор (Proper, Repack, Real, v2)
    mod_match = _MODIFIER_RE.search(release_name)
    modifier = mod_match.group("mod").capitalize() if mod_match else None

    return QualityInfo(
        name=canonical_name,
        rank=rank,
        source=source,
        resolution=resolution,
        modifier=modifier,
        video_codec=video_codec,
        audio_codec=audio_codec,
        audio_channels=audio_channels,
        dynamic_range=dynamic_range,
    )


def is_allowed(quality: QualityInfo, allowed_qualities: List[str]) -> bool:
    """Пусто в allowed_qualities = разрешено всё."""
    if not allowed_qualities:
        return True
    return quality.name in allowed_qualities


def is_upgrade(current: QualityInfo, candidate: QualityInfo, allowed_qualities: Optional[List[str]] = None) -> bool:
    """
    Возвращает True, если candidate лучше current по рангу и разрешен в профиле.
    """
    if allowed_qualities and not is_allowed(candidate, allowed_qualities):
        return False
    return candidate.rank > current.rank
