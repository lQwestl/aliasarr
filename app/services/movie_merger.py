"""
Модуль для обнаружения и потокового (lossless) объединения многофайловых релизов фильмов.

Поддерживает:
1. Автоматическое распознавание частей фильма (Part 1/2, CD1/CD2, Disc 1/2, Pt 1/2).
2. Потоковую склейку без перекодирования через `mkvmerge` (MKVToolNix) — сохраняет все дорожки, субтитры и главы с автоматической синхронизацией таймкодов.
3. Резервную склейку через `ffmpeg -f concat -c copy`.
4. Безопасность: исходные файлы в папке загрузки читаются только на чтение (read-only), сидирование торрента не прерывается.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import tempfile
from typing import Callable, Optional

logger = logging.getLogger("aliasarr.movie_merger")

_PART_PATTERNS = [
    re.compile(r"(?:[-_.\s]|^)(?:part|cd|disc|disk|pt|часть|диск)\s*0*([1-9])\b", re.IGNORECASE),
    re.compile(r"(?:[-_.\s]|^)0*([1-9])\s*(?:из|of)\s*0*([1-9])\b", re.IGNORECASE),
    re.compile(r"(?:[-_.\s]|^)(?:dvd|bd)\s*0*([1-9])\b", re.IGNORECASE),
]


def extract_part_number(file_path: str) -> Optional[int]:
    """Извлекает номер части из имени файла (например, CD1 -> 1, Part 2 -> 2)."""
    base = os.path.basename(file_path)
    for pat in _PART_PATTERNS:
        m = pat.search(base)
        if m:
            try:
                return int(m.group(1))
            except (ValueError, IndexError):
                pass
    return None


def find_movie_parts(target: list[str] | str) -> list[str]:
    """
    Проверяет список видеофайлов или директорию на наличие последовательности частей фильма (CD1/CD2, Part 1/Part 2...).
    Возвращает отсортированный по порядку список частей [part1, part2, ...] или пустой список, если части не найдены.
    """
    if isinstance(target, str):
        if not os.path.exists(target):
            return []
        if os.path.isdir(target):
            video_exts = {".mkv", ".mp4", ".avi", ".ts", ".m2ts", ".m4v", ".mov", ".wmv", ".flv"}
            files = []
            for root, _, filenames in os.walk(target):
                for fn in filenames:
                    ext = os.path.splitext(fn)[1].lower()
                    if ext in video_exts and not fn.lower().startswith("sample") and "sample" not in fn.lower():
                        files.append(os.path.join(root, fn))
            video_files = sorted(files)
        else:
            video_files = [target]
    else:
        video_files = list(target or [])

    if not video_files or len(video_files) < 2:
        return []

    # Исключаем файлы нулевого размера, если они существуют
    valid_files = [f for f in video_files if (not os.path.exists(f) or os.path.getsize(f) > 0)]
    if len(valid_files) < 2:
        return []

    indexed_parts: list[tuple[int, str]] = []
    for f in valid_files:
        p_num = extract_part_number(f)
        if p_num is not None:
            indexed_parts.append((p_num, f))

    if len(indexed_parts) < 2:
        return []

    # Сортируем по номеру части
    indexed_parts.sort(key=lambda x: x[0])
    part_numbers = [p[0] for p in indexed_parts]

    # Проверяем последовательность частей: должно начинаться с 1 и идти последовательно (1, 2... или 1, 2, 3)
    if part_numbers[0] == 1 and part_numbers == list(range(1, len(part_numbers) + 1)):
        return [p[1] for p in indexed_parts]

    return []


def is_merge_tool_available() -> bool:
    """Проверяет наличие mkvmerge или ffmpeg в системе."""
    return bool(shutil.which("mkvmerge") or shutil.which("ffmpeg"))


def merge_movie_parts(
    source_files: list[str],
    dest_file: str,
    progress_callback: Optional[Callable[[float, str], None]] = None,
) -> list[str]:
    """
    Объединяет несколько частей видеофайла в один целевой файл без перекодирования.
    Если утилиты mkvmerge/ffmpeg установлены, выполняет склейку и возвращает [dest_file].
    Если утилиты недоступны или склейка не удалась, создает структурированные файлы частей
    по стандарту Plex/Jellyfin (напр., Movie - part1.mkv, Movie - part2.mkv) и возвращает их список.
    """
    if not source_files or len(source_files) < 2:
        return []

    # Проверяем, доступны ли утилиты для склейки
    if is_merge_tool_available():
        dest_dir = os.path.dirname(os.path.abspath(dest_file))
        if dest_dir:
            os.makedirs(dest_dir, exist_ok=True)
        total_src_size = sum(os.path.getsize(f) for f in source_files if os.path.exists(f))

        # 1. Попытка через mkvmerge (наиболее надежно для MKV, правит таймкоды всех треков)
        mkvmerge_bin = shutil.which("mkvmerge")
        if mkvmerge_bin:
            try:
                if progress_callback:
                    progress_callback(0.3, f"Склейка {len(source_files)} частей через mkvmerge...")

                cmd = [mkvmerge_bin, "-o", dest_file, source_files[0]]
                for part in source_files[1:]:
                    cmd.extend(["+", part])

                logger.info("MovieMerger: Запуск mkvmerge для %d частей -> %s", len(source_files), dest_file)
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
                if res.returncode in (0, 1) and os.path.exists(dest_file):
                    dest_size = os.path.getsize(dest_file)
                    if total_src_size == 0 or dest_size >= total_src_size * 0.85:
                        logger.info("MovieMerger: mkvmerge успешно объединил фильм (%d байт)", dest_size)
                        if progress_callback:
                            progress_callback(0.9, "Склейка частей завершена успешно")
                        return [dest_file]
                    else:
                        logger.warning("MovieMerger: Результирующий файл меньше ожидаемого (%d < %d)", dest_size, total_src_size)
                else:
                    logger.warning("MovieMerger: Ошибка mkvmerge (код %d): %s", res.returncode, res.stderr or res.stdout)
            except Exception as exc:
                logger.warning("MovieMerger: Исключение при выполнении mkvmerge: %s", exc)

        # 2. Попытка через FFmpeg concat demuxer
        ffmpeg_bin = shutil.which("ffmpeg")
        if ffmpeg_bin:
            tmp_txt = None
            try:
                if progress_callback:
                    progress_callback(0.3, f"Склейка {len(source_files)} частей через ffmpeg...")

                with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f_list:
                    tmp_txt = f_list.name
                    for sf in source_files:
                        f_list.write(f"file '{os.path.abspath(sf)}'\n")

                cmd = [
                    ffmpeg_bin,
                    "-y",
                    "-f", "concat",
                    "-safe", "0",
                    "-i", tmp_txt,
                    "-c", "copy",
                    dest_file,
                ]
                logger.info("MovieMerger: Запуск ffmpeg concat для %d частей -> %s", len(source_files), dest_file)
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
                if res.returncode == 0 and os.path.exists(dest_file):
                    dest_size = os.path.getsize(dest_file)
                    if total_src_size == 0 or dest_size >= total_src_size * 0.85:
                        logger.info("MovieMerger: ffmpeg успешно объединил фильм (%d байт)", dest_size)
                        if progress_callback:
                            progress_callback(0.9, "Склейка частей завершена успешно")
                        return [dest_file]
                logger.warning("MovieMerger: Ошибка ffmpeg concat (код %d): %s", res.returncode, res.stderr or res.stdout)
            except Exception as exc:
                logger.warning("MovieMerger: Исключение при выполнении ffmpeg: %s", exc)
            finally:
                if tmp_txt and os.path.exists(tmp_txt):
                    try:
                        os.remove(tmp_txt)
                    except OSError:
                        pass

        # Если склейка не удалась, очищаем поврежденный/неполный целевой файл
        if os.path.exists(dest_file):
            try:
                os.remove(dest_file)
            except OSError:
                pass

    # Резервный режим (Fallback): стандарт Plex/Jellyfin "- part1.ext", "- part2.ext"
    logger.info("MovieMerger: Применение резервного режима раздельных частей (Plex/Jellyfin naming standard)")
    dest_stem, default_ext = os.path.splitext(dest_file)
    result_parts = []
    for idx, part in enumerate(source_files, 1):
        ext = os.path.splitext(part)[1] or default_ext
        part_target = f"{dest_stem} - part{idx}{ext}"
        result_parts.append(part_target)
        try:
            target_dir = os.path.dirname(os.path.abspath(part_target))
            if target_dir:
                os.makedirs(target_dir, exist_ok=True)
            if os.path.exists(part) and not os.path.exists(part_target):
                try:
                    os.link(part, part_target)
                except Exception:
                    shutil.copy2(part, part_target)
            elif not os.path.exists(part):
                try:
                    os.link(part, part_target)
                except Exception:
                    pass
        except Exception as exc:
            logger.debug("MovieMerger fallback link note: %s", exc)

    return result_parts
