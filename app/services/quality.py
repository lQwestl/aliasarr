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
    # Low / CAM / Telesync
    "CAM-480p",
    "Telesync-480p",
    "Telecine-480p",
    "Workprint-480p",
    # SD (480p)
    "SDTV-480p",
    "TVRip-480p",
    "DVD-480p",
    "DVDRip-480p",
    "HDTV-480p",
    "WEBRip-480p",
    "WEBDL-480p",
    "Bluray-480p",
    # 720p
    "HDTV-720p",
    "WEBRip-720p",
    "WEBDL-720p",
    "Bluray-720p",
    # 1080p
    "HDTV-1080p",
    "WEBRip-1080p",
    "WEBDL-1080p",
    "Bluray-1080p",
    "Remux-1080p",
    # 2160p (4K UHD)
    "HDTV-2160p",
    "WEBRip-2160p",
    "WEBDL-2160p",
    "Bluray-2160p",
    "Remux-2160p",
]

QUALITY_ALIASES = {
    "CAM": "CAM-480p",
    "TELESYNC": "Telesync-480p",
    "TELECINE": "Telecine-480p",
    "WORKPRINT": "Workprint-480p",
    "SDTV": "SDTV-480p",
    "TVRIP": "TVRip-480p",
    "DVD": "DVD-480p",
    "DVDRIP": "DVDRip-480p",
    "BDRIP": "Bluray-480p",
    "BRRIP": "Bluray-480p",
    "BDRIP-480P": "Bluray-480p",
    "BDRIP-576P": "Bluray-480p",
    "BDRIP-720P": "Bluray-720p",
    "BDRIP-1080P": "Bluray-1080p",
    "BDRIP-2160P": "Bluray-2160p",
    "BLURAY-576P": "Bluray-480p",
    "HDTV-576P": "HDTV-480p",
    "WEBRIP-576P": "WEBRip-480p",
    "WEBDL-576P": "WEBDL-480p",
    "WEBDLRIP": "WEBDL-480p",
    "WEBDL-RIP": "WEBDL-480p",
    "WEB-DLRIP": "WEBDL-480p",
    "WEB-DL-RIP": "WEBDL-480p",
    "WEBRIP": "WEBRip-480p",
}

# Регулярные выражения источников (Sources)
_REMUX_RE = re.compile(r"\b(remux|bdremux|bd[-_. ]?remux|uhd[-_. ]?remux|4k[-_. ]?remux)\b", re.IGNORECASE)
_BDRIP_RE = re.compile(r"\b(bdrip|bd[-_. ]?rip)\b", re.IGNORECASE)
_BRRIP_RE = re.compile(r"\b(brrip|br[-_. ]?rip)\b", re.IGNORECASE)
_BLURAY_RE = re.compile(r"\b(bluray|blu-ray|bdmux|bd(?!$)|hd-?dvd|bdmv|uhd[-_. ]?disc|uhd[-_. ]?blu[-_. ]?ray|uhd[-_. ]?bd|4k[-_. ]?bluray|4k[-_. ]?blu-ray|bdiso|blurayiso)\b", re.IGNORECASE)
_WEBDL_RE = re.compile(r"\b(web[-_. ]?dl(?:mux|[-_. ]?rip)?|webdlrip|webdl|amazonhd|ituneshd|netflixu?hd|webhd|hbomaxhd|disneyhd|[. ]web[. ](?:[xh][ .]?26[456]|avc|hevc|ddp?[ .]?5[. ]1))\b", re.IGNORECASE)
_WEBRIP_RE = re.compile(r"\b(webrip|web-rip|web\b)", re.IGNORECASE)
_HDTV_RE = re.compile(r"\b(hdtv|pdtv|dsr)\b", re.IGNORECASE)
_TVRIP_RE = re.compile(r"\b(tvrip|satrip|dtvrip)\b", re.IGNORECASE)
_DVDRIP_RE = re.compile(r"\b(dvdrip|dvd-rip)\b", re.IGNORECASE)
_DVD_RE = re.compile(r"\b(dvd|dvd9|dvd5|dvd-r|ntsc|pal|xvidvd)\b", re.IGNORECASE)
_CAM_RE = re.compile(r"\b(camrip|cam|hdcam)\b", re.IGNORECASE)
_TELESYNC_RE = re.compile(r"\b(telesync|hdts|hd-ts|tsrip|telesync-rip)\b", re.IGNORECASE)
_TELECINE_RE = re.compile(r"\b(telecine|tc|hdtc)\b", re.IGNORECASE)
_WORKPRINT_RE = re.compile(r"\b(workprint|wp)\b", re.IGNORECASE)
_SDTV_RE = re.compile(r"\b(sdtv|sd)\b", re.IGNORECASE)

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
    has_explicit_quality: bool = False
    has_explicit_res: bool = False

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


def make_canonical_quality(
    source: str,
    resolution: str,
    has_explicit_res: bool = True,
    is_rip: bool = False,
) -> tuple[str, int]:
    """
    Формирует каноническое имя качества (например Bluray-1080p, WEBDL-720p, SDTV-480p)
    и возвращает кортеж (canonical_name, rank).
    """
    src = source or "SDTV"
    res = resolution or "480p"

    if src == "Remux":
        canonical_name = "Remux-2160p" if res == "2160p" else "Remux-1080p"
    elif src == "Bluray":
        if has_explicit_res and res in ("720p", "1080p", "2160p", "480p"):
            canonical_name = f"Bluray-{res}"
        elif not has_explicit_res:
            canonical_name = "Bluray-480p"
        else:
            canonical_name = f"Bluray-{res}"
    elif src in ("WEBDL", "WEBRip", "HDTV"):
        if has_explicit_res:
            canonical_name = f"{src}-{res}"
        else:
            if is_rip and src in ("WEBDL", "WEBRip"):
                canonical_name = f"{src}-480p"
            else:
                canonical_name = f"{src}-1080p" if src != "HDTV" else "HDTV-720p"
    elif src in ("DVDRip", "DVD", "TVRip", "SDTV", "CAM", "Telesync", "Telecine", "Workprint"):
        canonical_name = f"{src}-480p"
    else:
        canonical_name = f"{src}-{res}"

    canonical_name = QUALITY_ALIASES.get(canonical_name.upper(), canonical_name)

    if canonical_name not in QUALITY_ORDER:
        if res == "2160p":
            canonical_name = "WEBDL-2160p"
        elif res == "1080p":
            canonical_name = "WEBDL-1080p"
        elif res == "720p":
            canonical_name = "WEBDL-720p"
        else:
            canonical_name = "SDTV-480p"

    try:
        rank = QUALITY_ORDER.index(canonical_name)
    except ValueError:
        rank = 0

    return canonical_name, rank


def parse_quality(release_name: str) -> QualityInfo:
    """
    Разбирает строку названия релиза на качество, кодеки, HDR и модификаторы.
    """
    if not release_name:
        return QualityInfo(
            name="SDTV-480p",
            rank=QUALITY_ORDER.index("SDTV-480p"),
            source="SDTV",
            resolution="480p",
            has_explicit_quality=False,
            has_explicit_res=False,
        )

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
    elif raw_res in ("576p", "576i", "480p", "480i", "360p"):
        resolution = "480p"
    else:
        resolution = "480p"

    # 2. Источник
    has_explicit_source = True
    if _REMUX_RE.search(release_name):
        source = "Remux"
    elif _BDRIP_RE.search(release_name) or _BRRIP_RE.search(release_name) or _BLURAY_RE.search(release_name):
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
    elif _SDTV_RE.search(release_name):
        source = "SDTV"
    else:
        has_explicit_source = False
        source = "HDTV" if (has_explicit_res and resolution in ("720p", "1080p", "2160p")) else "SDTV"

    is_rip = bool(
        re.search(
            r"\b(web[-_. ]?dl[-_. ]?rip|webdlrip|web[-_. ]?rip|webrip|rip|xvid|divx|\.avi)\b",
            release_name,
            re.IGNORECASE,
        )
    )

    canonical_name, rank = make_canonical_quality(
        source=source,
        resolution=resolution,
        has_explicit_res=has_explicit_res,
        is_rip=is_rip,
    )
    has_explicit_quality = has_explicit_res or has_explicit_source

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
        has_explicit_quality=has_explicit_quality,
        has_explicit_res=has_explicit_res,
    )


def is_allowed(quality: QualityInfo, allowed_qualities: List[str]) -> bool:
    """Пусто в allowed_qualities = разрешено всё."""
    if not allowed_qualities:
        return True
    norm_q = QUALITY_ALIASES.get(quality.name.upper(), quality.name)
    norm_allowed = {QUALITY_ALIASES.get(a.upper(), a) for a in allowed_qualities}
    return norm_q in norm_allowed or quality.name in allowed_qualities or quality.name in norm_allowed


def is_upgrade(current: QualityInfo, candidate: QualityInfo, allowed_qualities: Optional[List[str]] = None) -> bool:
    """
    Возвращает True, если candidate лучше current по рангу и разрешен в профиле.
    """
    if allowed_qualities and not is_allowed(candidate, allowed_qualities):
        return False
    return candidate.rank > current.rank


def detect_file_quality(
    file_path: str,
    context_hints: Optional[List[str]] = None,
    probe_file: bool = True,
) -> QualityInfo:
    """
    Интеллектуально определяет качество файла, строго соблюдая иерархию источников:
    1. Имя самого файла (наивысший приоритет тегов качества: SDTV-480p, WEBDL-1080p и т.д.)
    2. Родительские папки в пути (для файлов без явного качества, например 01.mkv)
    3. Особенности дисковых контейнеров (BDMV, .m2ts, .iso, VIDEO_TS)
    4. Внешние контекстные подсказки (строго fallback, когда нет данных в файле/папке)
    5. Физическая инспекция медиафайла на диске (ffprobe / media_probe), определяющая истинное
       разрешение видеопотока и кодеки.
    """
    import os

    file_basename = os.path.basename(file_path) if file_path else ""
    file_q = parse_quality(file_basename) if file_basename else None

    # Родительские папки (до 5 уровней вверх)
    parent_dirs: List[str] = []
    if file_path:
        curr_p = os.path.abspath(file_path) if os.path.isabs(file_path) else file_path
        for _ in range(5):
            parent = os.path.dirname(curr_p)
            if not parent or parent == curr_p or parent in ("/", "\\", ".", ""):
                break
            b_name = os.path.basename(parent)
            if b_name and b_name not in ("STREAM", "PLAYLIST", "CLIPINF", "BACKUP", "BDMV", "VIDEO_TS"):
                parent_dirs.append(b_name)
            curr_p = parent

    folder_qs = [parse_quality(p) for p in parent_dirs if p]
    hint_qs = [parse_quality(ch.strip()) for ch in (context_hints or []) if ch and isinstance(ch, str) and ch.strip()]

    raw_full = f"{file_path or ''} {' '.join(parent_dirs)}".lower()
    is_bdmv = ".m2ts" in raw_full or "bdmv" in raw_full
    is_dvd_iso = ".iso" in raw_full or "video_ts" in raw_full

    base_q: Optional[QualityInfo] = None

    # 1. Если в имени файла есть явные теги качества — это высший приоритет
    if file_q and file_q.has_explicit_quality:
        base_q = file_q

    # 2. Если в имени файла нет явного качества, проверяем папки пути
    elif folder_qs:
        for fq in folder_qs:
            if fq.has_explicit_quality:
                base_q = fq
                break

    # 3. Дисковые структуры
    if base_q is None:
        if is_bdmv:
            is_4k = "2160p" in raw_full or "4k" in raw_full or "uhd" in raw_full
            c_name = "Bluray-2160p" if is_4k else "Bluray-1080p"
            base_q = QualityInfo(
                name=c_name,
                rank=QUALITY_ORDER.index(c_name),
                source="Bluray",
                resolution="2160p" if is_4k else "1080p",
                has_explicit_quality=True,
                has_explicit_res=True,
            )
        elif is_dvd_iso:
            base_q = QualityInfo(
                name="DVD-480p",
                rank=QUALITY_ORDER.index("DVD-480p"),
                source="DVD",
                resolution="480p",
                has_explicit_quality=True,
                has_explicit_res=True,
            )

    # 4. Внешние подсказки (только как fallback, когда в пути файла нет качества)
    if base_q is None and hint_qs:
        best_hint = None
        for hq in hint_qs:
            if hq.has_explicit_quality:
                if best_hint is None or hq.rank > best_hint.rank:
                    best_hint = hq
        if best_hint is not None:
            base_q = best_hint

    # 5. Крайний fallback
    if base_q is None:
        base_q = file_q or QualityInfo(
            name="SDTV-480p",
            rank=QUALITY_ORDER.index("SDTV-480p"),
            source="SDTV",
            resolution="480p",
        )

    # Сбор дополнительных метаданных из всех источников (кодеки, каналы, HDR, модификаторы)
    all_parsed = ([file_q] if file_q else []) + folder_qs + hint_qs
    vcodec = next((q.video_codec for q in all_parsed if q.video_codec), None)
    acodec = next((q.audio_codec for q in all_parsed if q.audio_codec), None)
    achannels = next((q.audio_channels for q in all_parsed if q.audio_channels), None)
    hdr = next((q.dynamic_range for q in all_parsed if q.dynamic_range), None)
    mod = next((q.modifier for q in all_parsed if q.modifier), None)

    # Физическая инспекция файла через media_probe / ffprobe
    probed_info = None
    if probe_file and file_path and os.path.isfile(file_path):
        try:
            from app.services.media_probe import probe_media_file
            probed_info = probe_media_file(file_path)
        except Exception:
            probed_info = None

    if probed_info:
        vcodec = probed_info.get("video_codec") or vcodec
        acodec = probed_info.get("audio_codec") or acodec
        achannels = probed_info.get("audio_channels") or achannels
        hdr = probed_info.get("dynamic_range") or hdr
        probed_res = probed_info.get("resolution")

        if probed_res:
            # Если реальное разрешение файла отличается от предполагаемого base_q
            if base_q.resolution != probed_res:
                final_source = base_q.source if base_q.source not in ("SDTV", None) else ("HDTV" if probed_res in ("720p", "1080p", "2160p") else "SDTV")

                ext = os.path.splitext(file_path)[1].lower() if file_path else ""
                is_avi_or_xvid = ext == ".avi" or (vcodec and vcodec.upper() in ("XVID", "DIVX"))

                if is_avi_or_xvid and probed_res in ("480p", "576p"):
                    if final_source in ("Bluray", "Remux", "HDTV"):
                        final_source = "SDTV"
                    elif final_source in ("WEBDL", "WEBRip"):
                        final_source = "WEBDL"

                c_name, rank = make_canonical_quality(final_source, probed_res, has_explicit_res=True)
                return QualityInfo(
                    name=c_name,
                    rank=rank,
                    source=final_source,
                    resolution=probed_res,
                    modifier=base_q.modifier or mod,
                    video_codec=vcodec,
                    audio_codec=acodec,
                    audio_channels=achannels,
                    dynamic_range=hdr,
                    has_explicit_quality=True,
                    has_explicit_res=True,
                )
    else:
        # Без физической пробы: проверка ограничений контейнера (.avi)
        ext = os.path.splitext(file_path)[1].lower() if file_path else ""
        if ext == ".avi" and base_q.resolution in ("1080p", "2160p", "720p"):
            final_source = "SDTV" if base_q.source in ("Bluray", "Remux", "HDTV") else base_q.source
            c_name, rank = make_canonical_quality(final_source, "480p", has_explicit_res=True)
            return QualityInfo(
                name=c_name,
                rank=rank,
                source=final_source,
                resolution="480p",
                modifier=base_q.modifier or mod,
                video_codec=vcodec or "XviD",
                audio_codec=acodec,
                audio_channels=achannels,
                dynamic_range=hdr,
                has_explicit_quality=base_q.has_explicit_quality,
                has_explicit_res=True,
            )

    return QualityInfo(
        name=base_q.name,
        rank=base_q.rank,
        source=base_q.source,
        resolution=base_q.resolution,
        modifier=base_q.modifier or mod,
        video_codec=vcodec or base_q.video_codec,
        audio_codec=acodec or base_q.audio_codec,
        audio_channels=achannels or base_q.audio_channels,
        dynamic_range=hdr or base_q.dynamic_range,
        has_explicit_quality=base_q.has_explicit_quality,
        has_explicit_res=base_q.has_explicit_res,
    )

