"""
Инспекция медиафайлов: извлечение реального разрешения, видео/аудио кодеков,
числа каналов и HDR/цветового диапазона напрямую из файла на диске.

Поддерживает:
1. Запуск системного `ffprobe` (если установлен в системе/контейнере).
2. Встроенный чистый Python-парсер контейнеров (MKV/WebM EBML, MP4/MOV atoms, AVI RIFF),
   не требующий внешних зависимостей и читающий только первые 1-2 МБ файла.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import struct
import subprocess
from typing import Optional, Dict, Any

logger = logging.getLogger("aliasarr.media_probe")


def classify_resolution(width: Optional[int], height: Optional[int]) -> Optional[str]:
    """
    Классифицирует разрешение на основе ширины и высоты кадра.
    Учитывает анаморфное и 4:3 видео (например, 1440x1080 -> 1080p, 960x720 -> 720p).
    """
    if not width and not height:
        return None

    w = width or 0
    h = height or 0

    # 4K / 2160p
    if h >= 1440 or w >= 3000:
        return "2160p"
    # Full HD / 1080p (включая 1440x1080, 1920x800, 1920x1080)
    if h >= 800 or (w >= 1400 and h >= 700):
        return "1080p"
    # HD / 720p (включая 1280x720, 960x720, 1280x534)
    if h >= 600 or (w >= 1000 and h >= 500):
        return "720p"
    # PAL / 576p
    if h >= 540 or (w >= 720 and h >= 500):
        return "576p"
    # SD / 480p
    if h > 0 or w > 0:
        return "480p"
    return None


def _map_vcodec(raw_codec: str) -> Optional[str]:
    """Нормализует имя видеокодека."""
    if not raw_codec:
        return None
    c = raw_codec.lower().strip()
    if c in ("h264", "avc", "avc1", "x264", "v_mpeg4/iso/avc"):
        return "x264"
    if c in ("hevc", "h265", "hev1", "hvc1", "x265", "v_mpegh/iso/hevc"):
        return "HEVC"
    if c in ("av1", "av01", "v_av1"):
        return "AV1"
    if c in ("vp9", "vp09", "v_vp9"):
        return "VP9"
    if c in ("vc1", "vc-1", "wvc1", "v_ms/vfw/fourcc/wvc1"):
        return "VC-1"
    if c in ("mpeg2", "mpeg2video", "mp2v", "v_mpeg2"):
        return "MPEG2"
    if c in ("xvid", "divx", "dx50"):
        return "XviD"
    return raw_codec.upper()


def _map_acodec(raw_codec: str) -> Optional[str]:
    """Нормализует имя аудиокодека."""
    if not raw_codec:
        return None
    c = raw_codec.lower().strip()
    if "truehd" in c or "a_truehd" in c:
        return "TrueHD"
    if "dts-hd" in c or "dtshd" in c:
        return "DTS-HD MA"
    if "dts" in c or "dca" in c or "a_dts" in c:
        return "DTS"
    if "eac3" in c or "ec-3" in c or "ddp" in c or "a_eac3" in c:
        return "EAC3"
    if "ac3" in c or "ac-3" in c or "dd" in c or "a_ac3" in c:
        return "AC3"
    if "flac" in c or "a_flac" in c:
        return "FLAC"
    if "aac" in c or "mp4a" in c or "a_aac" in c:
        return "AAC"
    if "opus" in c or "a_opus" in c:
        return "Opus"
    if "mp3" in c or "mp3a" in c or "a_mpeg/l3" in c:
        return "MP3"
    if "pcm" in c or "lpcm" in c:
        return "PCM"
    return raw_codec.upper()


def _map_channels(channels: Optional[int]) -> Optional[str]:
    """Преобразует число каналов в стандартную строку (2.0, 5.1, 7.1)."""
    if channels is None:
        return None
    if channels >= 8:
        return "7.1"
    if channels >= 6:
        return "5.1"
    if channels == 2:
        return "2.0"
    if channels == 1:
        return "1.0"
    return f"{channels}.0"


def _probe_via_ffprobe(file_path: str) -> Optional[Dict[str, Any]]:
    """Пытается получить метаданные медиафайла через ffprobe."""
    ffprobe_bin = shutil.which("ffprobe")
    if not ffprobe_bin:
        return None

    try:
        cmd = [
            ffprobe_bin,
            "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            "-show_streams",
            file_path,
        ]
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5, check=False)
        if res.returncode != 0 or not res.stdout:
            return None

        data = json.loads(res.stdout.decode("utf-8", errors="ignore"))
        streams = data.get("streams", [])
        if not streams:
            return None

        v_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
        a_streams = [s for s in streams if s.get("codec_type") == "audio"]

        width = v_stream.get("width") if v_stream else None
        height = v_stream.get("height") if v_stream else None
        vcodec_raw = v_stream.get("codec_name") if v_stream else None
        video_codec = _map_vcodec(vcodec_raw) if vcodec_raw else None

        # Определение HDR / Dynamic Range
        dynamic_range = None
        if v_stream:
            color_transfer = str(v_stream.get("color_transfer") or "").lower()
            color_primaries = str(v_stream.get("color_primaries") or "").lower()
            pix_fmt = str(v_stream.get("pix_fmt") or "").lower()
            bits = v_stream.get("bits_per_raw_sample")

            # Проверяем Dolby Vision side data
            side_data_list = v_stream.get("side_data_list", [])
            has_dovi = any("dovi" in str(sd.get("side_data_type", "")).lower() or "dolby vision" in str(sd.get("side_data_type", "")).lower() for sd in side_data_list)

            if has_dovi:
                dynamic_range = "DV HDR" if "smpte2084" in color_transfer else "DV"
            elif "smpte2084" in color_transfer or "bt2020" in color_primaries:
                dynamic_range = "HDR10"
            elif "arib-std-b67" in color_transfer or "hlg" in color_transfer:
                dynamic_range = "HLG"
            elif "10" in pix_fmt or bits == 10:
                dynamic_range = "10bit"

        # Аудио метаданные
        audio_codec = None
        audio_channels = None
        if a_streams:
            best_a = max(a_streams, key=lambda a: a.get("channels") or 0)
            audio_codec = _map_acodec(best_a.get("codec_name") or "")
            audio_channels = _map_channels(best_a.get("channels"))

        file_size = None
        fmt = data.get("format", {})
        if fmt.get("size"):
            try:
                file_size = int(fmt["size"])
            except (ValueError, TypeError):
                pass

        resolution = classify_resolution(width, height)

        return {
            "width": width,
            "height": height,
            "resolution": resolution,
            "video_codec": video_codec,
            "audio_codec": audio_codec,
            "audio_channels": audio_channels,
            "dynamic_range": dynamic_range,
            "file_size_bytes": file_size,
            "source_method": "ffprobe",
        }
    except Exception as exc:
        logger.debug("ffprobe failed for %s: %s", file_path, exc)
        return None


def _read_ebml_vint(data: bytes, offset: int) -> tuple[int, int, int]:
    """
    Читает EBML Variable Length Integer.
    Возвращает (значение, длина_vint, новый_offset).
    """
    if offset >= len(data):
        return 0, 0, offset
    first_byte = data[offset]
    if first_byte == 0:
        return 0, 1, offset + 1

    mask = 0x80
    length = 1
    while not (first_byte & mask) and length <= 8:
        mask >>= 1
        length += 1

    if length > 8 or offset + length > len(data):
        return 0, 1, offset + 1

    val = first_byte & (~mask)
    for i in range(1, length):
        val = (val << 8) | data[offset + i]
    return val, length, offset + length


def _read_ebml_id(data: bytes, offset: int) -> tuple[int, int]:
    """Читает EBML Element ID (сохраняя ведущую маску)."""
    if offset >= len(data):
        return 0, offset
    first_byte = data[offset]
    if first_byte == 0:
        return 0, offset + 1
    mask = 0x80
    length = 1
    while not (first_byte & mask) and length <= 4:
        mask >>= 1
        length += 1

    if length > 4 or offset + length > len(data):
        return 0, offset + 1

    val = 0
    for i in range(length):
        val = (val << 8) | data[offset + i]
    return val, offset + length


def _probe_mkv_pure_python(file_path: str) -> Optional[Dict[str, Any]]:
    """
    Чистый Python-парсер заголовков Matroska / WebM (EBML).
    Сканирует первые 2 МБ файла для извлечения TrackEntry:
    PixelWidth (0xB0), PixelHeight (0xBA), CodecID (0x86), AudioChannels (0x9F), BitDepth (0x6264).
    """
    try:
        with open(file_path, "rb") as f:
            header = f.read(2 * 1024 * 1024)
        if len(header) < 16 or not header.startswith(b"\x1a\x45\xdf\xa3"):
            return None

        width = None
        height = None
        vcodec = None
        acodec = None
        channels = None
        bit_depth = None

        pos = 0
        total_len = len(header)

        while pos < total_len - 4:
            elem_id, pos = _read_ebml_id(header, pos)
            elem_size, _, pos = _read_ebml_vint(header, pos)
            if elem_id == 0 or pos > total_len:
                break

            # Если это контейнер верхнего уровня (EBML, Segment, Tracks, TrackEntry, Video, Audio), углубляемся
            if elem_id in (0x1A45DFA3, 0x18538067, 0x1654AE6B, 0xAE, 0xE0, 0xE1, 0x55B0):
                continue

            content_end = min(pos + elem_size, total_len)
            content = header[pos:content_end]

            # PixelWidth = 0xB0
            if elem_id == 0xB0 and elem_size in (1, 2, 3, 4) and len(content) >= elem_size:
                val = int.from_bytes(content[:elem_size], "big")
                if 100 <= val <= 10000:
                    width = val
            # PixelHeight = 0xBA
            elif elem_id == 0xBA and elem_size in (1, 2, 3, 4) and len(content) >= elem_size:
                val = int.from_bytes(content[:elem_size], "big")
                if 100 <= val <= 10000:
                    height = val
            # CodecID = 0x86
            elif elem_id == 0x86 and 1 <= elem_size <= 64:
                codec_str = content.decode("ascii", errors="ignore").strip("\x00")
                if codec_str.startswith("V_"):
                    vcodec = _map_vcodec(codec_str)
                elif codec_str.startswith("A_") and not acodec:
                    acodec = _map_acodec(codec_str)
            # Audio Channels = 0x9F
            elif elem_id == 0x9F and elem_size in (1, 2) and len(content) >= elem_size:
                channels = int.from_bytes(content[:elem_size], "big")
            # BitDepth = 0x6264 or 0x55B2
            elif elem_id in (0x6264, 0x55B2) and elem_size in (1, 2) and len(content) >= elem_size:
                bit_depth = int.from_bytes(content[:elem_size], "big")

            pos = content_end

            # Если нашли и видео, и аудио — можно завершать
            if width and height and vcodec and acodec:
                break

        if not width and not height and not vcodec:
            return None

        dynamic_range = "10bit" if bit_depth == 10 else None
        resolution = classify_resolution(width, height)

        return {
            "width": width,
            "height": height,
            "resolution": resolution,
            "video_codec": vcodec,
            "audio_codec": acodec,
            "audio_channels": _map_channels(channels),
            "dynamic_range": dynamic_range,
            "file_size_bytes": os.path.getsize(file_path) if os.path.exists(file_path) else None,
            "source_method": "pure_python_mkv",
        }
    except Exception as exc:
        logger.debug("MKV pure python probe failed for %s: %s", file_path, exc)
        return None


def _probe_mp4_pure_python(file_path: str) -> Optional[Dict[str, Any]]:
    """
    Чистый Python-парсер контейнеров MP4 / M4V / MOV (ISO Base Media File Format).
    Рекурсивно сканирует атомы: `moov` -> `trak` -> `tkhd` (размеры видео), `stsd` (кодеки).
    """
    try:
        with open(file_path, "rb") as f:
            header = f.read(2 * 1024 * 1024)
        if len(header) < 16:
            return None

        width = None
        height = None
        vcodec = None
        acodec = None

        def walk_atoms(offset: int, limit: int, depth: int = 0):
            nonlocal width, height, vcodec, acodec
            if depth > 10:
                return
            pos = offset
            while pos + 8 <= limit:
                atom_size = struct.unpack(">I", header[pos:pos+4])[0]
                atom_type = header[pos+4:pos+8]

                if atom_size == 0:
                    break
                if atom_size == 1:
                    if pos + 16 > limit:
                        break
                    atom_size = struct.unpack(">Q", header[pos+8:pos+16])[0]
                    hdr_size = 16
                else:
                    hdr_size = 8

                if atom_size < hdr_size or pos + atom_size > limit:
                    break

                if atom_type in (b"moov", b"trak", b"mdia", b"minf", b"stbl"):
                    walk_atoms(pos + hdr_size, pos + atom_size, depth + 1)
                elif atom_type == b"tkhd":
                    tkhd_data = header[pos+hdr_size : pos+atom_size]
                    if len(tkhd_data) >= 84:
                        version = tkhd_data[0]
                        off = 76 if version == 0 else 88
                        if len(tkhd_data) >= off + 8:
                            w_val = struct.unpack(">I", tkhd_data[off:off+4])[0] >> 16
                            h_val = struct.unpack(">I", tkhd_data[off+4:off+8])[0] >> 16
                            if w_val > 0 and h_val > 0 and (not width or w_val > width):
                                width = w_val
                                height = h_val
                elif atom_type == b"stsd":
                    stsd_data = header[pos+hdr_size : pos+atom_size]
                    stsd_str = stsd_data.decode("latin1", errors="ignore")
                    for candidate in ("avc1", "hev1", "hvc1", "av01", "vp09", "mp4v"):
                        if candidate in stsd_str and not vcodec:
                            vcodec = _map_vcodec(candidate)
                            break
                    for candidate in ("mp4a", "ac-3", "ec-3", "dts ", "flac", "opus"):
                        if candidate in stsd_str and not acodec:
                            acodec = _map_acodec(candidate)
                            break

                pos += atom_size

        walk_atoms(0, len(header))

        if not width and not height and not vcodec:
            return None

        resolution = classify_resolution(width, height)
        return {
            "width": width,
            "height": height,
            "resolution": resolution,
            "video_codec": vcodec,
            "audio_codec": acodec,
            "audio_channels": None,
            "dynamic_range": None,
            "file_size_bytes": os.path.getsize(file_path) if os.path.exists(file_path) else None,
            "source_method": "pure_python_mp4",
        }
    except Exception as exc:
        logger.debug("MP4 pure python probe failed for %s: %s", file_path, exc)
        return None


def _probe_avi_pure_python(file_path: str) -> Optional[Dict[str, Any]]:
    """Чистый Python-парсер RIFF AVI заголовков."""
    try:
        with open(file_path, "rb") as f:
            header = f.read(64 * 1024)
        if len(header) < 64 or not header.startswith(b"RIFF") or b"AVI " not in header[:16]:
            return None

        # Ищем блок avih (AVI Main Header)
        # avih (4) + size (4) + 32 bytes dwMicroSecPerFrame... + dwWidth (4) + dwHeight (4)
        avih_idx = header.find(b"avih")
        if avih_idx != -1 and avih_idx + 48 <= len(header):
            width = struct.unpack("<I", header[avih_idx+40 : avih_idx+44])[0]
            height = struct.unpack("<I", header[avih_idx+44 : avih_idx+48])[0]
            if 50 <= width <= 10000 and 50 <= height <= 10000:
                resolution = classify_resolution(width, height)
                return {
                    "width": width,
                    "height": height,
                    "resolution": resolution,
                    "video_codec": "XviD",
                    "audio_codec": None,
                    "audio_channels": None,
                    "dynamic_range": None,
                    "file_size_bytes": os.path.getsize(file_path) if os.path.exists(file_path) else None,
                    "source_method": "pure_python_avi",
                }
    except Exception as exc:
        logger.debug("AVI pure python probe failed for %s: %s", file_path, exc)
    return None


def probe_media_file(file_path: str) -> Optional[Dict[str, Any]]:
    """
    Основная точка входа для инспекции медиафайла.
    1. Пробует системный ffprobe (если доступен).
    2. Если ffprobe нет или он завершился ошибкой — использует встроенные pure-Python парсеры.
    """
    if not file_path or not os.path.isfile(file_path):
        return None

    # 1. Системный ffprobe
    res = _probe_via_ffprobe(file_path)
    if res and res.get("resolution"):
        return res

    # 2. Pure-Python парсеры по расширению файла
    ext = os.path.splitext(file_path)[1].lower()
    if ext in (".mkv", ".webm"):
        py_res = _probe_mkv_pure_python(file_path)
        if py_res:
            return py_res
    elif ext in (".mp4", ".m4v", ".mov"):
        py_res = _probe_mp4_pure_python(file_path)
        if py_res:
            return py_res
    elif ext == ".avi":
        py_res = _probe_avi_pure_python(file_path)
        if py_res:
            return py_res

    # Пробуем форматы по сигнатуре данных
    py_res = _probe_mkv_pure_python(file_path)
    if py_res:
        return py_res
    py_res = _probe_mp4_pure_python(file_path)
    if py_res:
        return py_res

    return res
