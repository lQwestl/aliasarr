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
    # Low / Telesync / CAM
    "CAM",
    "Telesync",
    "Telecine",
    "Workprint",
    # SD / TV / DVD / Rips
    "SDTV",
    "TVRip",
    "DVD",
    "DVDRip",
    "BDRip",
    "BRRip",
    "HDTV-480p",
    "HDTV-576p",
    "WEBRip-480p",
    "WEBRip-576p",
    "WEBDL-480p",
    "WEBDL-576p",
    "BDRip-480p",
    "BDRip-576p",
    "Bluray-480p",
    "Bluray-576p",
    # 720p
    "HDTV-720p",
    "WEBRip-720p",
    "WEBDL-720p",
    "BDRip-720p",
    "Bluray-720p",
    # 1080p
    "HDTV-1080p",
    "WEBRip-1080p",
    "WEBDL-1080p",
    "BDRip-1080p",
    "Bluray-1080p",
    "Remux-1080p",
    # 2160p (4K UHD)
    "HDTV-2160p",
    "WEBRip-2160p",
    "WEBDL-2160p",
    "BDRip-2160p",
    "Bluray-2160p",
    "Remux-2160p",
]

# Регулярные выражения источников (Sources)
_REMUX_RE = re.compile(r"\b(remux|bdremux|bd[-_. ]?remux|uhd[-_. ]?remux|4k[-_. ]?remux)\b", re.IGNORECASE)
_BDRIP_RE = re.compile(r"\b(bdrip|bd[-_. ]?rip)\b", re.IGNORECASE)
_BRRIP_RE = re.compile(r"\b(brrip|br[-_. ]?rip)\b", re.IGNORECASE)
_BLURAY_RE = re.compile(r"\b(bluray|blu-ray|bdmux|bd(?!$)|hd-?dvd|bdmv|uhd[-_. ]?disc|uhd[-_. ]?blu[-_. ]?ray|uhd[-_. ]?bd|4k[-_. ]?bluray|4k[-_. ]?blu-ray|bdiso|blurayiso)\b", re.IGNORECASE)
_WEBDL_RE = re.compile(r"\b(web[-_. ]?dl(?:mux)?|webdl|amazonhd|ituneshd|netflixu?hd|webhd|hbomaxhd|disneyhd|[. ]web[. ](?:[xh][ .]?26[456]|avc|hevc|ddp?[ .]?5[. ]1))\b", re.IGNORECASE)
_WEBRIP_RE = re.compile(r"\b(webrip|web-rip|web\b)", re.IGNORECASE)
_HDTV_RE = re.compile(r"\b(hdtv|pdtv|dsr)\b", re.IGNORECASE)
_TVRIP_RE = re.compile(r"\b(tvrip|satrip|dtvrip)\b", re.IGNORECASE)
_DVDRIP_RE = re.compile(r"\b(dvdrip|dvd-rip)\b", re.IGNORECASE)
_DVD_RE = re.compile(r"\b(dvd|dvd9|dvd5|dvd-r|ntsc|pal|xvidvd)\b", re.IGNORECASE)
_CAM_RE = re.compile(r"\b(camrip|cam|hdcam)\b", re.IGNORECASE)
_TELESYNC_RE = re.compile(r"\b(telesync|hdts|hd-ts|tsrip|telesync-rip)\b", re.IGNORECASE)
_TELECINE_RE = re.compile(r"\b(telecine|tc|hdtc)\b", re.IGNORECASE)
_WORKPRINT_RE = re.compile(r"\b(workprint|wp)\b", re.IGNORECASE)

# Разрешения
_RES_RE = re.compile(r"\b(?P<res>2160p|1080p|1080i|720p|576p|576i|480p|480i|360p|4k|uhd|fhd)\b", re.IGNORECASE)

# Кодеки видео
_VCODEC_RE = re.compile(r"\b(?P<vcodec>x265|h265|hevc|x264|h264|avc|av1|xvid|divx|vc-?1|mpeg2|mpeg-h)\b", re.IGNORECASE)

# Кодеки аудио
_ACODEC_RE = re.compile(r"\b(?P<acodec>truehd(?:\.atmos)?|atmos|dts-hd(?:\.ma)?|dts-x|dts|eac3|ddp(?:\+)?|dd\+?|ac3|flac|aac|mp3|pcm|lpcm)\b", re.IGNORECASE)
_ACHANNELS_RE = re.compile(r"\b(?P<channels>7\.1|5\.1|2\.0|2ch|6ch|8ch)\b", re.IGNORECASE)

# HDR и Dynamic Range
_HDR_RE = re.compile(r"\b(?P<hdr>dv(?:\.hdr)?|dolby[-_. ]?vision|hdr10\+|hdr10|hdr|hlg|bt\.?2020|10[-_. ]?bits?)\b", re.IGNORECASE)

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
        return QualityInfo(name="SDTV", rank=QUALITY_ORDER.index("SDTV"), source="SDTV", resolution="480p")

    # 1. Разрешение
    res_match = _RES_RE.search(release_name)
    has_explicit_res = res_match is not None
    raw_res = res_match.group("res").lower() if res_match else ""
    if raw_res in ("2160p", "4k", "uhd"):
        resolution = "2160p"
    elif raw_res in ("1080p", "1080i", "fhd"):
        resolution = "1080p"
    elif raw_res == "720p":
        resolution = "720p"
    elif raw_res in ("576p", "576i"):
        resolution = "576p"
    elif raw_res in ("480p", "480i"):
        resolution = "480p"
    elif raw_res == "360p":
        resolution = "360p"
    else:
        resolution = "480p"

    # 2. Источник
    if _REMUX_RE.search(release_name):
        source = "Remux"
    elif _BDRIP_RE.search(release_name):
        source = "BDRip"
    elif _BRRIP_RE.search(release_name):
        source = "BRRip"
    elif _BLURAY_RE.search(release_name):
        source = "Bluray"
    elif _WEBDL_RE.search(release_name):
        source = "WEBDL"
    elif _WEBRIP_RE.search(release_name):
        source = "WEBRip"
    elif _HDTV_RE.search(release_name):
        source = "HDTV"
    elif _TVRIP_RE.search(release_name):
        source = "TVRip"
    elif _DVDRIP_RE.search(release_name):
        source = "DVDRip"
    elif _DVD_RE.search(release_name):
        source = "DVD"
    elif _CAM_RE.search(release_name):
        source = "CAM"
    elif _TELESYNC_RE.search(release_name):
        source = "Telesync"
    elif _TELECINE_RE.search(release_name):
        source = "Telecine"
    elif _WORKPRINT_RE.search(release_name):
        source = "Workprint"
    else:
        source = "HDTV" if (has_explicit_res and resolution in ("720p", "1080p", "2160p")) else "SDTV"

    # 3. Формирование канонического имени качества
    if source == "Remux":
        canonical_name = "Remux-2160p" if resolution == "2160p" else "Remux-1080p"
    elif source == "BDRip":
        if has_explicit_res and resolution in ("720p", "1080p", "2160p", "480p", "576p"):
            canonical_name = f"BDRip-{resolution}"
        else:
            canonical_name = "BDRip"
    elif source == "BRRip":
        if has_explicit_res and resolution in ("720p", "1080p", "2160p", "480p", "576p"):
            canonical_name = f"BDRip-{resolution}"
        else:
            canonical_name = "BRRip"
    elif source == "Bluray":
        if has_explicit_res and resolution in ("720p", "1080p", "2160p", "480p", "576p"):
            canonical_name = f"Bluray-{resolution}"
        else:
            canonical_name = "Bluray-1080p"
    elif source in ("WEBDL", "WEBRip", "HDTV"):
        if has_explicit_res:
            canonical_name = f"{source}-{resolution}"
        else:
            canonical_name = f"{source}-1080p" if source != "HDTV" else "HDTV-720p"
    elif source in ("DVDRip", "DVD", "TVRip", "SDTV", "CAM", "Telesync", "Telecine", "Workprint"):
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
        elif resolution == "576p":
            canonical_name = "WEBDL-576p"
        elif resolution == "480p":
            canonical_name = "WEBDL-480p"
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


def detect_file_quality(file_path: str, context_hints: Optional[List[str]] = None) -> QualityInfo:
    """
    Интеллектуально определяет качество файла, анализируя:
    1. Имя самого файла
    2. Все родительские директории в пути к файлу (от папки файла до корня раздачи)
    3. Дополнительные контекстные подсказки (название раздачи, TrackedRelease, заголовок топика)
    4. Особенности контейнеров (BDMV, .m2ts, .iso, VIDEO_TS)
    """
    import os

    candidates: List[str] = []
    if file_path:
        # 1. Имя файла
        candidates.append(os.path.basename(file_path))

        # 2. Все родительские папки
        curr_p = os.path.abspath(file_path) if os.path.isabs(file_path) else file_path
        for _ in range(5):
            parent = os.path.dirname(curr_p)
            if not parent or parent == curr_p or parent in ("/", "\\", ".", ""):
                break
            b_name = os.path.basename(parent)
            if b_name and b_name not in ("STREAM", "PLAYLIST", "CLIPINF", "BACKUP", "BDMV", "VIDEO_TS"):
                candidates.append(b_name)
            elif b_name:
                candidates.append(b_name)
            curr_p = parent

    if context_hints:
        for ch in context_hints:
            if ch and isinstance(ch, str) and ch.strip():
                candidates.append(ch.strip())

    parsed_list = [parse_quality(c) for c in candidates if c]

    # Ищем качество с наивысшим рангом (не-SDTV)
    best_q = None
    for q in parsed_list:
        if q.name != "SDTV":
            if best_q is None or q.rank > best_q.rank:
                best_q = q

    # Объединяем дополнительные метаданные (видеокодек, аудиокодек, HDR, каналы), если они найдены в других частях пути
    vcodec = next((q.video_codec for q in parsed_list if q.video_codec), None)
    acodec = next((q.audio_codec for q in parsed_list if q.audio_codec), None)
    achannels = next((q.audio_channels for q in parsed_list if q.audio_channels), None)
    hdr = next((q.dynamic_range for q in parsed_list if q.dynamic_range), None)
    mod = next((q.modifier for q in parsed_list if q.modifier), None)

    if best_q is not None:
        return QualityInfo(
            name=best_q.name,
            rank=best_q.rank,
            source=best_q.source,
            resolution=best_q.resolution,
            modifier=best_q.modifier or mod,
            video_codec=best_q.video_codec or vcodec,
            audio_codec=best_q.audio_codec or acodec,
            audio_channels=best_q.audio_channels or achannels,
            dynamic_range=best_q.dynamic_range or hdr,
        )

    # Fallback для BDMV / .m2ts / .iso
    raw_full = " ".join(candidates).lower()
    if ".m2ts" in raw_full or "bdmv" in raw_full:
        is_4k = "2160p" in raw_full or "4k" in raw_full or "uhd" in raw_full
        q_name = "Bluray-2160p" if is_4k else "Bluray-1080p"
        try:
            rank = QUALITY_ORDER.index(q_name)
        except ValueError:
            rank = 10
        return QualityInfo(
            name=q_name,
            rank=rank,
            source="Bluray",
            resolution="2160p" if is_4k else "1080p",
            modifier=mod,
            video_codec=vcodec or ("HEVC" if is_4k else "x264"),
            audio_codec=acodec,
            audio_channels=achannels,
            dynamic_range=hdr,
        )

    if ".iso" in raw_full or "video_ts" in raw_full:
        return QualityInfo(
            name="DVD",
            rank=1,
            source="DVD",
            resolution="480p",
            modifier=mod,
            video_codec=vcodec,
            audio_codec=acodec,
            audio_channels=achannels,
            dynamic_range=hdr,
        )

    # Крайний fallback
    base_q = parsed_list[0] if parsed_list else QualityInfo(name="SDTV", rank=0, source="SDTV", resolution="480p")
    return QualityInfo(
        name=base_q.name,
        rank=base_q.rank,
        source=base_q.source,
        resolution=base_q.resolution,
        modifier=base_q.modifier or mod,
        video_codec=base_q.video_codec or vcodec,
        audio_codec=base_q.audio_codec or acodec,
        audio_channels=base_q.audio_channels or achannels,
        dynamic_range=base_q.dynamic_range or hdr,
    )
