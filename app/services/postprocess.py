"""
Пост-обработка скачанных файлов:
- Сопоставление медиафайлов с сериями или фильмом
- Извлечение технических метаданных (MediaInfo)
- Переименование по шаблону категории (Фильм/Сериал/Аниме)
- Перемещение файлов и сопутствующих субтитров/шрифтов в библиотеку
- Обновление статусов серий в базе данных и отправка уведомлений
"""

from __future__ import annotations

import datetime as dt
import os
import re
import shutil

try:
    from sqlalchemy.orm import Session
    from app.models.db import Episode, EpisodeStatus, Show
except ImportError:
    Session = object
    Episode = None
    EpisodeStatus = type("EpisodeStatus", (), {"DOWNLOADED": "downloaded"})
    Show = None

from app.services.parser import ReleaseKind, parse_episode
from app.services.quality import parse_quality, detect_file_quality

SUBTITLE_EXTENSIONS = {".srt", ".ass", ".ssa", ".sub", ".idx", ".vtt", ".smi"}
AUDIO_EXTENSIONS = {".mka", ".aac", ".ac3", ".dts", ".flac", ".mp3", ".m4a", ".wav", ".eac3", ".opus"}
FONT_EXTENSIONS = {".ttf", ".otf", ".ttc", ".woff", ".woff2", ".eot"}
VIDEO_EXTENSIONS = {
    ".mkv", ".mp4", ".avi", ".ts", ".m2ts", ".mts", ".mov", ".webm",
    ".m4v", ".wmv", ".flv", ".vob", ".ogv", ".divx", ".xvid", ".3gp",
    ".tp", ".trp", ".m2t", ".iso", ".strm"
}

# Папки, содержащие дополнительные материалы, опенинги, эндинги, трейлеры, бонусы
_EXTRA_DIR_PATTERNS = re.compile(
    r"(?:^|[\\/])(?:op[-_\s]?ed|openings?|endings?|ncop\d*|nced\d*|creditless|credits|theme[-_\s]?songs?|music[-_\s]?videos?|ost|extras?|bonus|featurettes?|behind[-_\s]the[-_\s]scenes|making[-_\s]of|trailers?|samples?|scans?|artworks?|soundtrack|menu|pv|cm|interviews?|deleted[-_\s]scenes?)(?:[\\/]|$)",
    re.IGNORECASE,
)

# Файлы опенингов, эндингов, бонусов, сэмплов, трейлеров, PV, CM
_EXTRA_FILE_PATTERNS = re.compile(
    r"\b(?:nc)?op\s*[-–_.]?\s*\d+\b|"             # OP - 01, OP01, NCOP1, OP.02
    r"\b(?:nc)?ed\s*[-–_.]?\s*\d+\b|"             # ED - 01, ED01, NCED1, ED.02
    r"\b(?:opening|ending)s?\s*[-–_.]?\s*\d*\b|"  # Opening 1, Endings
    r"\bcreditless\b|"                            # Creditless
    r"\b(?:ncop|nced)\d*\b|"                      # NCOP, NCED
    r"\b(?:sample|trailer|preview|teaser|menu|promo)\b|"  # Sample, Trailer, etc.
    r"\b(?:pv|cm)\s*[-–_.]?\s*\d*\b|"             # PV01, CM01, PV 1
    r"\b(?:extra|bonus|featurette|behind[-_\s]the[-_\s]scenes|making[-_\s]of|interview|deleted[-_\s]scene)\b|"
    r"\bclean[-_\s]?(?:op|ed|opening|ending)\b|"  # Clean OP, Clean ED
    r"\bins\s*[-–_.]?\s*\d+\b",                   # INS - 01 (insert song)
    re.IGNORECASE,
)

_SAMPLE_RE = _EXTRA_FILE_PATTERNS


def is_extra_or_sample(file_path: str, release_root: str = "") -> bool:
    """
    Проверяет, является ли файл опенингом (OP), эндингом (ED), сэмплом, трейлером,
    бонусом, PV/CM или другим дополнительным материалом (extras), который не должен
    считаться основным эпизодом сериала/аниме или фильмом.
    """
    fname = os.path.basename(file_path)
    # Если в имени явно указан сезон/серия, это точно основной эпизод!
    if re.search(r"\bS\d{1,2}\s*E\d{1,3}\b|\b\d{1,2}x\d{1,3}\b|\b(?:эпизод|серия|episode|ep)\.?\s*\d{1,3}\b", fname, re.IGNORECASE):
        return False

    if _EXTRA_FILE_PATTERNS.search(fname):
        return True

    rel_path = os.path.relpath(file_path, release_root) if release_root else file_path
    if _EXTRA_DIR_PATTERNS.search(rel_path):
        return True

    return False


def ensure_fonts_ignore(fonts_dir: str) -> bool:
    """
    Создаёт файл '.ignore' внутри папки fonts, если:
    - папка fonts существует (уже создана)
    - файл '.ignore' ещё не существует в ней

    Этот файл скрывает папку fonts из библиотеки Jellyfin.
    Возвращает True, если файл был создан, False — если уже существовал или папка не найдена.
    """
    if not fonts_dir or not os.path.isdir(fonts_dir):
        return False
    ignore_path = os.path.join(fonts_dir, ".ignore")
    if os.path.exists(ignore_path):
        return False
    try:
        with open(ignore_path, "w") as f:
            f.write("")
        try:
            os.chmod(ignore_path, 0o666)
        except Exception:
            pass
        return True
    except Exception:
        return False


def apply_media_permissions(
    path: str,
    is_dir: bool = False,
    file_mode: int = 0o666,
    dir_mode: int = 0o777,
    recursive: bool = False,
) -> dict[str, int]:
    """
    Устанавливает права доступа (chmod/chown), чтобы Jellyfin, Plex, Samba и другие сервисы
    в TrueNAS / Linux / Docker могли беспрепятственно читать и изменять файлы и папки.
    Возвращает словарь со статистикой: {"dirs": N, "files": M}.
    """
    stats = {"dirs": 0, "files": 0}
    if not path or not os.path.exists(path):
        return stats

    puid_str = os.getenv("PUID", "").strip()
    pgid_str = os.getenv("PGID", "").strip()
    puid = int(puid_str) if puid_str.isdigit() else -1
    pgid = int(pgid_str) if pgid_str.isdigit() else -1

    def _apply_single(target: str, is_target_dir: bool):
        try:
            if is_target_dir:
                os.chmod(target, dir_mode)
                stats["dirs"] += 1
            else:
                os.chmod(target, file_mode)
                stats["files"] += 1
            if puid >= 0 or pgid >= 0:
                os.chown(target, puid if puid >= 0 else -1, pgid if pgid >= 0 else -1)
        except Exception:
            pass

    try:
        if is_dir or os.path.isdir(path):
            _apply_single(path, True)
            if recursive:
                for root, dirs, files in os.walk(path):
                    for d in dirs:
                        _apply_single(os.path.join(root, d), True)
                    for f in files:
                        _apply_single(os.path.join(root, f), False)
        else:
            _apply_single(path, False)
            parent_dir = os.path.dirname(path)
            if parent_dir and os.path.isdir(parent_dir):
                _apply_single(parent_dir, True)
    except Exception:
        pass

    return stats


_INVALID_FS_CHARS = re.compile(r'[<>:"/\\|?*]')

_KNOWN_LANG_TAGS = {
    "rus": "rus", "ru": "rus", "russian": "rus", "рус": "rus", "русский": "rus",
    "eng": "eng", "en": "eng", "english": "eng", "анг": "eng", "английский": "eng",
    "jpn": "jpn", "ja": "jpn", "japanese": "jpn", "яп": "jpn", "японский": "jpn",
    "ukr": "ukr", "uk": "ukr", "ukrainian": "ukr", "укр": "ukr",
    "ita": "ita", "it": "ita", "italian": "ita",
    "spa": "spa", "es": "spa", "spanish": "spa",
    "ger": "ger", "de": "ger", "german": "ger",
    "fra": "fra", "fr": "fra", "french": "fra",
    "chi": "chi", "zh": "chi", "chinese": "chi",
    "kor": "kor", "ko": "kor", "korean": "kor",
    "signs": "signs", "надписи": "signs",
    "full": "full", "полные": "full",
    "forced": "forced", "sdh": "sdh", "cc": "cc",
    "dub": "dub", "sub": "sub", "dvo": "dvo", "mvo": "mvo", "avo": "avo",
}


def natural_sort_key(s: str) -> list[int | str]:
    """Разбивает строку на цифры и буквы для естественной числовой сортировки (1, 2, ... 10, 11)."""
    return [int(text) if text.isdigit() else text.lower() for text in re.split(r"(\d+)", s or "")]


def sanitize_filename(name: str) -> str:
    return _INVALID_FS_CHARS.sub("", name or "").strip()


def get_show_default_path(show: Show, settings) -> str:
    if show.path and show.path.strip():
        return show.path.strip()
    if show.content_type == "movie":
        root = settings.root_folder_movies or settings.root_folder or ""
        folder = f"{sanitize_filename(show.title)} ({show.year})" if show.year else sanitize_filename(show.title)
    elif show.content_type == "anime":
        root = settings.root_folder_anime or settings.root_folder or ""
        folder = sanitize_filename(show.title)
    else:
        root = settings.root_folder_series or settings.root_folder or ""
        folder = sanitize_filename(show.title)
    if not root:
        return ""
    return os.path.join(root, folder)


def _clean_title(title: str) -> str:
    s = sanitize_filename(title or "")
    s = re.sub(r"[^\w\s\-']", "", s)
    return re.sub(r"\s+", " ", s).strip()


def _title_the(title: str) -> str:
    t = (title or "").strip()
    if t.lower().startswith("the "):
        return f"{t[4:].strip()}, The"
    return t


def _title_without_year(title: str) -> str:
    return re.sub(r"\s*\(\d{4}\)$|\s+\d{4}$", "", (title or "")).strip()


def render_sonarr_token(
    raw_token: str,
    *,
    show_title: str,
    year: Optional[int] = None,
    season: Optional[int] = None,
    episode: Optional[int] = None,
    episode_title: str = "",
    absolute: Optional[int] = None,
    quality: str = "",
    original_title: str = "",
    original_filename: str = "",
    imdb_id: str = "",
    tvdb_id: str = "",
    tmdb_id: str = "",
    tvmaze_id: str = "",
    air_date: Optional[dt.date] = None,
    release_group: str = "",
    custom_formats: str = "",
) -> str:
    max_len = None
    from_start = False
    token = raw_token.strip()

    if not re.match(r"^(season|episode|absolute):\d+[a-z]?$", token, re.IGNORECASE):
        m_len = re.match(r"^(.+?):(-?\d+)$", token)
        if m_len:
            token = m_len.group(1).strip()
            num = int(m_len.group(2))
            max_len = abs(num)
            from_start = (num < 0)

    token_norm = token.replace(".", " ").strip().lower()
    val = ""

    if token_norm in ("series title", "show title", "show_title", "show", "series", "movie title", "title"):
        val = show_title
    elif token_norm in ("series cleantitle", "movie cleantitle"):
        val = _clean_title(show_title)
    elif token_norm in ("series titleyear", "movie titleyear"):
        val = f"{show_title} ({year})" if year else show_title
    elif token_norm in ("series cleantitleyear", "movie cleantitleyear"):
        val = f"{_clean_title(show_title)} {year}" if year else _clean_title(show_title)
    elif token_norm == "series titlewithoutyear":
        val = _title_without_year(show_title)
    elif token_norm == "series cleantitlewithoutyear":
        val = _clean_title(_title_without_year(show_title))
    elif token_norm == "series titlethe":
        val = _title_the(show_title)
    elif token_norm == "series cleantitlethe":
        val = _clean_title(_title_the(show_title))
    elif token_norm == "series titletheyear":
        val = f"{_title_the(_title_without_year(show_title))} ({year})" if year else _title_the(show_title)
    elif token_norm == "series cleantitletheyear":
        val = f"{_clean_title(_title_the(_title_without_year(show_title)))} {year}" if year else _clean_title(_title_the(show_title))
    elif token_norm == "series titlethewithoutyear":
        val = _title_the(_title_without_year(show_title))
    elif token_norm == "series cleantitlethewithoutyear":
        val = _clean_title(_title_the(_title_without_year(show_title)))
    elif token_norm == "series titlefirstcharacter":
        val = show_title[0].upper() if show_title else ""
    elif token_norm in ("series year", "release year", "year"):
        val = str(year) if year else ""
    elif token_norm == "imdbid":
        val = imdb_id or ""
    elif token_norm == "tvdbid":
        val = tvdb_id or ""
    elif token_norm == "tmdbid":
        val = tmdb_id or ""
    elif token_norm == "tvmazeid":
        val = tvmaze_id or ""
    elif token_norm in ("season:0", "season"):
        val = str(season) if season is not None else ""
    elif token_norm in ("season:00", "season:02d"):
        val = f"{season:02d}" if season is not None else ""
    elif token_norm in ("episode:0", "episode"):
        val = str(episode) if episode is not None else ""
    elif token_norm in ("episode:00", "episode:02d"):
        val = f"{episode:02d}" if episode is not None else ""
    elif token_norm in ("absolute:0", "absolute"):
        val = str(absolute if absolute is not None else (episode or 0))
    elif token_norm in ("absolute:00",):
        val = f"{(absolute if absolute is not None else (episode or 0)):02d}"
    elif token_norm in ("absolute:000", "absolute:03d"):
        val = f"{(absolute if absolute is not None else (episode or 0)):03d}"
    elif token_norm == "air-date":
        val = air_date.strftime("%Y-%m-%d") if air_date else ""
    elif token_norm == "air date":
        val = air_date.strftime("%Y %m %d") if air_date else ""
    elif token_norm in ("episode title", "episode_title"):
        val = episode_title or ""
    elif token_norm == "episode cleantitle":
        val = _clean_title(episode_title)
    elif token_norm in ("quality full", "quality title", "quality"):
        val = quality or ""
    elif token_norm == "mediainfo simple":
        val = "x264 DTS"
    elif token_norm == "mediainfo full":
        val = "x264 DTS [EN+RU]"
    elif token_norm == "mediainfo audiocodec":
        val = "DTS"
    elif token_norm == "mediainfo audiochannels":
        val = "5.1"
    elif token_norm == "mediainfo audiolanguages":
        val = "[EN+RU]"
    elif token_norm == "mediainfo subtitlelanguages":
        val = "[RU]"
    elif token_norm == "mediainfo videocodec":
        val = "x264"
    elif token_norm == "mediainfo videobitdepth":
        val = "10"
    elif token_norm == "mediainfo videodynamicrange":
        val = "HDR"
    elif token_norm == "mediainfo videodynamicrangetype":
        val = "DV HDR10"
    elif token_norm == "release group":
        val = release_group or ""
    elif token_norm == "custom formats":
        val = custom_formats or ""
    elif token_norm == "original title":
        val = original_title or show_title
    elif token_norm == "original filename":
        val = original_filename or show_title
    else:
        return f"{{{raw_token}}}"

    if max_len is not None and len(val) > max_len:
        if from_start:
            val = "..." + val[-(max_len - 3):] if max_len > 3 else val[-max_len:]
        else:
            val = val[:(max_len - 3)] + "..." if max_len > 3 else val[:max_len]

    return sanitize_filename(val)


def render_season_folder_template(
    template: str,
    *,
    season: int,
    show_title: str = "",
    year: Optional[int] = None,
) -> str:
    """
    Рендерит имя папки сезона для сериалов и аниме:
    "Сезон {season}" -> "Сезон 1"
    "Сезон {season:00}" -> "Сезон 01"
    "Season {season}" -> "Season 1"
    "Season {season:00}" -> "Season 01"
    "S{season:00}" -> "S01"
    "S{season}" -> "S1"
    """
    if not template or not template.strip():
        return ""

    def _replacer(m):
        raw = m.group(1)
        return render_sonarr_token(
            raw,
            show_title=show_title,
            year=year,
            season=season,
        )

    res = re.sub(r"\{([^}]+)\}", _replacer, template)
    clean = re.sub(r"\s+", " ", res).strip()
    return sanitize_filename(clean)


def render_episode_template(
    template: str, *, show_title: str, season: int, episode: int,
    episode_title: str, absolute: Optional[int] = None, quality: str = "",
    year: Optional[int] = None,
) -> str:
    """
    Рендерит шаблон для сериала/аниме в Sonarr-формате:
    "{Series Title} - S{season:00}E{episode:00} - {Episode Title} {Quality Full}"
    """
    def _replacer(m):
        raw = m.group(1)
        return render_sonarr_token(
            raw,
            show_title=show_title,
            year=year,
            season=season,
            episode=episode,
            episode_title=episode_title,
            absolute=absolute,
            quality=quality,
        )

    res = re.sub(r"\{([^}]+)\}", _replacer, template or "")
    return re.sub(r"\s+", " ", res).strip()


def render_movie_template(template: str, *, show_title: str, year: Optional[int], quality: str) -> str:
    """Рендерит шаблон для фильма, например: "{Movie Title} ({Release Year}) {Quality Full}"."""
    def _replacer(m):
        raw = m.group(1)
        return render_sonarr_token(
            raw,
            show_title=show_title,
            year=year,
            quality=quality,
        )

    res = re.sub(r"\{([^}]+)\}", _replacer, template or "")
    return re.sub(r"\s+", " ", res).strip()


def copy_file_with_progress(
    src: str,
    dst: str,
    callback=None,
    chunk_size: int = 4 * 1024 * 1024,
) -> None:
    """
    Копирует файл по чанкам (4 МБ) с вызовом callback(bytes_copied, total_bytes)
    для плавного и точного отображения прогресса в реальном времени.
    """
    total_size = os.path.getsize(src) if os.path.exists(src) else 0
    copied = 0
    with open(src, "rb") as fsrc, open(dst, "wb") as fdst:
        while True:
            buf = fsrc.read(chunk_size)
            if not buf:
                break
            fdst.write(buf)
            copied += len(buf)
            if callback and total_size > 0:
                callback(copied, total_size)
    try:
        shutil.copystat(src, dst)
    except Exception:
        pass
    apply_media_permissions(dst, is_dir=False)


def move_file_with_progress(
    src: str,
    dst: str,
    callback=None,
    chunk_size: int = 4 * 1024 * 1024,
) -> None:
    """
    Перемещает файл с отображением прогресса.
    Если файлы на одном диске/файловой системе — атомарный перенос с вызовом callback (0% -> 100%).
    Если на разных дисках — копирование по чанкам с callback и последующее удаление источника.
    """
    src_stat = os.stat(src)
    dst_dir = os.path.dirname(dst)
    os.makedirs(dst_dir, exist_ok=True)
    apply_media_permissions(dst_dir, is_dir=True)
    dst_dir_stat = os.stat(dst_dir)

    if src_stat.st_dev == dst_dir_stat.st_dev:
        if callback:
            callback(0, src_stat.st_size)
        os.replace(src, dst)
        if callback:
            callback(src_stat.st_size, src_stat.st_size)
        apply_media_permissions(dst, is_dir=False)
    else:
        copy_file_with_progress(src, dst, callback=callback, chunk_size=chunk_size)
        try:
            os.remove(src)
        except Exception:
            pass
        apply_media_permissions(dst, is_dir=False)


def find_release_files(root: str, specific_files: Optional[list[str]] = None) -> dict[str, list[str]]:
    """
    Сканирует путь загрузки (или обрабатывает строго список файлов из торрента) и группирует файлы по типам:
    - video: видеофайлы (.mkv, .mp4, .avi, etc.)
    - subtitle: субтитры (.srt, .ass, .ssa, etc.)
    - audio: внешние аудиодорожки (.mka, .ac3, .flac, etc.)
    - font: шрифты (.ttf, .otf, etc.)
    - extras: опенинги, эндинги, сэмплы, трейлеры
    - other: прочие файлы (.nfo, .txt, etc.)
    """
    files_by_type: dict[str, list[str]] = {
        "video": [],
        "subtitle": [],
        "audio": [],
        "font": [],
        "extras": [],
        "other": [],
    }

    if specific_files:
        for fpath in specific_files:
            if not os.path.exists(fpath):
                continue
            if os.path.isdir(fpath):
                sub_res = find_release_files(fpath)
                for k, v in sub_res.items():
                    files_by_type[k].extend(v)
                continue

            ext = os.path.splitext(fpath)[1].lower()
            if ext in VIDEO_EXTENSIONS:
                if is_extra_or_sample(fpath, os.path.dirname(fpath)):
                    files_by_type["extras"].append(fpath)
                else:
                    files_by_type["video"].append(fpath)
            elif ext in SUBTITLE_EXTENSIONS:
                files_by_type["subtitle"].append(fpath)
            elif ext in AUDIO_EXTENSIONS:
                files_by_type["audio"].append(fpath)
            elif ext in FONT_EXTENSIONS:
                files_by_type["font"].append(fpath)
            else:
                files_by_type["other"].append(fpath)

        # Если найдены видеофайлы, но нет субтитров/аудио в списке торрента —
        # ищем внешние сабы/аудио в той же конкретной папке рядом с видео
        if files_by_type["video"] and not files_by_type["subtitle"] and not files_by_type["audio"]:
            for v_path in files_by_type["video"]:
                v_dir = os.path.dirname(v_path)
                v_stem = os.path.splitext(os.path.basename(v_path))[0].lower()
                try:
                    for sibling in os.listdir(v_dir):
                        sib_path = os.path.join(v_dir, sibling)
                        if os.path.isfile(sib_path) and sib_path not in specific_files:
                            s_ext = os.path.splitext(sibling)[1].lower()
                            s_stem = os.path.splitext(sibling)[0].lower()
                            if s_stem.startswith(v_stem) or v_stem.startswith(s_stem):
                                if s_ext in SUBTITLE_EXTENSIONS:
                                    files_by_type["subtitle"].append(sib_path)
                                elif s_ext in AUDIO_EXTENSIONS:
                                    files_by_type["audio"].append(sib_path)
                except Exception:
                    pass

        return files_by_type

    if os.path.isfile(root):
        ext = os.path.splitext(root)[1].lower()
        if ext in VIDEO_EXTENSIONS:
            if is_extra_or_sample(root):
                files_by_type["extras"].append(root)
            else:
                files_by_type["video"].append(root)
        elif ext in SUBTITLE_EXTENSIONS:
            files_by_type["subtitle"].append(root)
        elif ext in AUDIO_EXTENSIONS:
            files_by_type["audio"].append(root)
        elif ext in FONT_EXTENSIONS:
            files_by_type["font"].append(root)
        else:
            files_by_type["other"].append(root)

        # Поиск субтитров/аудио с совпадающим именем рядом с одиночным файлом
        v_dir = os.path.dirname(root)
        v_stem = os.path.splitext(os.path.basename(root))[0].lower()
        try:
            for sibling in os.listdir(v_dir):
                sib_path = os.path.join(v_dir, sibling)
                if os.path.isfile(sib_path) and sib_path != root:
                    s_ext = os.path.splitext(sibling)[1].lower()
                    s_stem = os.path.splitext(sibling)[0].lower()
                    if s_stem.startswith(v_stem) or v_stem.startswith(s_stem):
                        if s_ext in SUBTITLE_EXTENSIONS:
                            files_by_type["subtitle"].append(sib_path)
                        elif s_ext in AUDIO_EXTENSIONS:
                            files_by_type["audio"].append(sib_path)
        except Exception:
            pass

        return files_by_type

    for dirpath, _dirs, filenames in os.walk(root):
        for fname in filenames:
            ext = os.path.splitext(fname)[1].lower()
            fpath = os.path.join(dirpath, fname)
            if ext in VIDEO_EXTENSIONS:
                if is_extra_or_sample(fpath, root):
                    files_by_type["extras"].append(fpath)
                else:
                    files_by_type["video"].append(fpath)
            elif ext in SUBTITLE_EXTENSIONS:
                files_by_type["subtitle"].append(fpath)
            elif ext in AUDIO_EXTENSIONS:
                files_by_type["audio"].append(fpath)
            elif ext in FONT_EXTENSIONS:
                files_by_type["font"].append(fpath)
            else:
                files_by_type["other"].append(fpath)
    return files_by_type


def find_video_files(root: str) -> list[str]:
    """Рекурсивно находит видеофайлы в папке загрузки (без опенингов, эндингов и сэмплов)."""
    return find_release_files(root)["video"]


def extract_companion_tag(
    companion_fpath: str,
    video_fpath: str = "",
    ep_num: Optional[int] = None,
    release_root: str = "",
) -> str:
    """
    Извлекает понятный суффикс/тег для субтитров или аудио (язык, озвучка, студия),
    например: "rus.2x2.mvo", "rus.Jetix.dub", "eng.dub", "rus.2nd_Life", "rus.Alex_Julia".
    Анализирует как имя файла, так и относительный путь к файлу внутри раздачи.
    """
    base = os.path.splitext(os.path.basename(companion_fpath))[0]

    # Слова из названия видео, которые не должны попадать в тег субтитров/аудио
    video_stem_words = set()
    if video_fpath:
        vbase = os.path.splitext(os.path.basename(video_fpath))[0].lower()
        for w in re.split(r"[._\-\s\[\]\(\)]+", vbase):
            if w and w not in _KNOWN_LANG_TAGS:
                video_stem_words.add(w)

    rel_path = companion_fpath
    if release_root:
        try:
            rel_path = os.path.relpath(companion_fpath, release_root)
        except Exception:
            rel_path = companion_fpath

    path_parts = [p for p in re.split(r"[\\/]", os.path.dirname(rel_path)) if p and p != "."]
    ignored_dir_names = {"subs", "subtitles", "субтитры", "audio", "sound", "звук", "озвучка", "downloads", "data", "fonts"}

    lang_tags: list[str] = []
    author_tags: list[str] = []
    type_tags: list[str] = []

    for part in path_parts:
        part_clean = part.strip()
        if part_clean.lower() in ignored_dir_names:
            continue

        bracketed = re.findall(r"\[([^\]]+)\]|\(([^)]+)\)", part_clean)
        for b_group in bracketed:
            for b_item in b_group:
                if not b_item:
                    continue
                b_clean = b_item.strip()
                if re.match(r"^[\d\s,–\-]+$", b_clean):
                    continue
                for sub_tok in re.split(r"[+&/,\s]+", b_clean):
                    sub_tok_clean = sub_tok.strip().lower()
                    if not sub_tok_clean:
                        continue
                    if sub_tok_clean in _KNOWN_LANG_TAGS:
                        val = _KNOWN_LANG_TAGS[sub_tok_clean]
                        if val in ("dub", "mvo", "dvo", "avo", "sub", "signs", "full", "forced", "sdh", "cc"):
                            if val not in type_tags:
                                type_tags.append(val)
                        else:
                            if val not in lang_tags:
                                lang_tags.append(val)
                    elif len(sub_tok) >= 2 and not sub_tok.isdigit():
                        sanitized = sanitize_filename(sub_tok).replace(" ", "_")
                        if sanitized.lower() not in [t.lower() for t in author_tags] and sanitized.lower() not in [t.lower() for t in lang_tags] and sanitized.lower() not in [t.lower() for t in type_tags]:
                            author_tags.append(sanitized)

        unbracketed = re.sub(r"\[[^\]]+\]|\([^)]+\)", " ", part_clean)
        for word in re.split(r"[._\-\s]+", unbracketed):
            w_clean = word.strip().lower()
            if not w_clean or w_clean in ignored_dir_names or w_clean in video_stem_words:
                continue
            if re.match(r"^[\d,–\-]+$", w_clean):
                continue
            if w_clean in _KNOWN_LANG_TAGS:
                val = _KNOWN_LANG_TAGS[w_clean]
                if val in ("dub", "mvo", "dvo", "avo", "sub", "signs", "full", "forced", "sdh", "cc"):
                    if val not in type_tags:
                        type_tags.append(val)
                else:
                    if val not in lang_tags:
                        lang_tags.append(val)
            elif len(word) >= 2 and not word.isdigit():
                sanitized = sanitize_filename(word).replace(" ", "_")
                if sanitized.lower() not in [t.lower() for t in author_tags] and sanitized.lower() not in [t.lower() for t in lang_tags] and sanitized.lower() not in [t.lower() for t in type_tags]:
                    author_tags.append(sanitized)

    raw_tokens = re.split(r"[._\-\s\[\]\(\)]+", base)
    for tok in raw_tokens:
        tok_clean = tok.strip().lower()
        if not tok_clean or tok_clean in video_stem_words:
            continue
        if re.match(r"^\d+$|^s\d+e\d+$|^e\d+$|^ep\d+$", tok_clean):
            continue
        if tok_clean in ("1080p", "720p", "2160p", "4k", "hevc", "x264", "x265", "10bit", "webdl", "bluray", "hdtv", "proper", "repack", "vfr", "flac"):
            continue
        if tok_clean in _KNOWN_LANG_TAGS:
            val = _KNOWN_LANG_TAGS[tok_clean]
            if val in ("dub", "mvo", "dvo", "avo", "sub", "signs", "full", "forced", "sdh", "cc"):
                if val not in type_tags:
                    type_tags.append(val)
            else:
                if val not in lang_tags:
                    lang_tags.append(val)
        elif len(tok) >= 2 and not tok.isdigit():
            clean_val = sanitize_filename(tok).replace(" ", "_")
            if clean_val.lower() not in [t.lower() for t in author_tags] and clean_val.lower() not in [t.lower() for t in lang_tags] and clean_val.lower() not in [t.lower() for t in type_tags]:
                author_tags.append(clean_val)

    combined = []
    if lang_tags:
        combined.append(lang_tags[0])
    if author_tags:
        combined.append(author_tags[0])
    if type_tags:
        combined.append(type_tags[0])

    if combined:
        return ".".join(combined)

    return ""


def match_companion_files_for_episode(
    companion_files: list[str],
    ep_num: int,
    season_num: int,
    video_fpath: str,
    total_video_count: int,
) -> list[str]:
    """
    Определяет, какие файлы субтитров или аудиодорожек из раздачи относятся к данному эпизоду.
    """
    if not companion_files:
        return []

    matched = []
    video_stem = os.path.splitext(os.path.basename(video_fpath))[0].lower()

    ep_patterns = [
        re.compile(rf"(?:s0?{season_num})?[._\-\s]e0?{ep_num}(?:[._\-\s]|$)", re.IGNORECASE),
        re.compile(rf"(?:ep|серия|эпизод)[._\-\s]*0?{ep_num}(?:[._\-\s]|$)", re.IGNORECASE),
        re.compile(rf"[._\-\s\[\(]0?{ep_num}[._\-\]\)\s]", re.IGNORECASE),
        re.compile(rf"[-–]\s*0*{ep_num}(?:[._\-\s\[\(]|$)", re.IGNORECASE),
        re.compile(rf"^0*{ep_num}[._\-\s]"),
        re.compile(rf"[._\-\s]0*{ep_num}$"),
    ]

    for cf in companion_files:
        fname = os.path.basename(cf)
        fstem = os.path.splitext(fname)[0].lower()

        if fstem == video_stem or (fstem.startswith(video_stem) and not any(p.search(fstem[len(video_stem):]) for p in ep_patterns)):
            matched.append(cf)
            continue

        parsed = parse_episode(fname)
        if parsed and parsed.episodes and ep_num in parsed.episodes:
            if parsed.season is None or parsed.season == season_num:
                matched.append(cf)
                continue

        if any(p.search(fname) for p in ep_patterns):
            matched.append(cf)
            continue

    return matched


def process_download(
    db: Session,
    show: Show,
    download_path: str,
    rename_template: str,
    root_folder: str,
    season_folder_template: str = "Сезон {season}",
    specific_files: Optional[list[str]] = None,
    torrent_hash: Optional[str] = None,
    progress_callback: Optional[Callable[[float, str], None]] = None,
) -> list[dict]:
    """
    Обрабатывает завершённую загрузку для сериала/аниме:
    - находит видеофайлы, субтитры, аудиодорожки и шрифты в раздаче
    - исключает опенинги, эндинги, сэмплы и другие не-эпизодные файлы
    - создает целевую структуру папок (Папка тайтла -> Папка сезона)
    - переименовывает и переносит видеофайлы внутрь папки сезона
    - привязывает и переносит внешние субтитры (.ass, .srt), аудио (.mka) и шрифты (fonts/)
    - обновляет статус Episode -> DOWNLOADED, прогресс 100%, записывает file_path
    """
    results = []
    show_root = show.path or os.path.join(root_folder, sanitize_filename(show.title))
    os.makedirs(show_root, exist_ok=True)

    release_files = find_release_files(download_path, specific_files=specific_files)
    video_files = release_files["video"]
    subtitle_files = release_files["subtitle"]
    audio_files = release_files["audio"]
    font_files = release_files["font"]

    # Защита: если specific_files не указан и download_path является общей папкой,
    # фильтруем видеофайлы по соответствию названию шоу, чтобы не затронуть чужие релизы
    if not specific_files and len(video_files) > 1:
        from app.services.matcher import build_alias_candidates, best_alias_match
        aliases = build_alias_candidates(show, db=db)
        matched_videos = []
        for vf in video_files:
            b_alias, b_score = best_alias_match(os.path.basename(vf), aliases, threshold=60)
            if b_alias:
                matched_videos.append(vf)
        if matched_videos:
            video_files = matched_videos

    if not video_files:
        # Проверяем, возможно серии уже на месте в папках тайтла
        updated_any = False
        eps_for_show = db.query(Episode).filter_by(show_id=show.id).all()
        for ep in eps_for_show:
            if ep.file_path and os.path.exists(ep.file_path) and ep.status == EpisodeStatus.DOWNLOADING:
                ep.status = EpisodeStatus.DOWNLOADED
                ep.download_progress = 1.0
                db.add(ep)
                updated_any = True
        if updated_any:
            db.commit()

        import logging
        logging.getLogger("aliasarr.postprocess").warning(
            "Не найдено основных видеофайлов по пути: %s. Убедитесь, что папки примонтированы корректно.",
            download_path,
        )

    from app.services.settings_service import get_or_create_settings
    settings = get_or_create_settings(db) if db else None
    import_extras = getattr(settings, "import_extra_files", True) if settings else True

    # 1. Сохраняем шрифты в общую папку шоу /fonts
    if font_files and import_extras:
        show_fonts_dir = os.path.join(show_root, "fonts")
        os.makedirs(show_fonts_dir, exist_ok=True)
        apply_media_permissions(show_fonts_dir, is_dir=True)
        for ff in font_files:
            try:
                dest_ff = os.path.join(show_fonts_dir, os.path.basename(ff))
                shutil.copy2(ff, dest_ff)
                apply_media_permissions(dest_ff, is_dir=False)
            except Exception:
                pass
        # Скрываем папку fonts из библиотеки Jellyfin через .ignore
        ensure_fonts_ignore(show_fonts_dir)

    # Копируем NFO / текстовые описания в корень шоу
    if import_extras:
        for of in release_files.get("other", []):
            if os.path.splitext(of)[1].lower() in {".nfo", ".txt", ".sfv"}:
                try:
                    dest_of = os.path.join(show_root, os.path.basename(of))
                    if not os.path.exists(dest_of):
                        shutil.copy2(of, dest_of)
                        apply_media_permissions(dest_of, is_dir=False)
                except Exception:
                    pass

    total_videos = len(video_files)
    used_companions = set()

    dl_eps: list[Episode] = []
    if torrent_hash and db:
        try:
            dl_eps = (
                db.query(Episode)
                .filter(Episode.show_id == show.id, Episode.torrent_hash == torrent_hash)
                .order_by(Episode.season_number, Episode.episode_number)
                .all()
            )
        except Exception:
            dl_eps = []
    if not dl_eps and db:
        try:
            dl_eps = (
                db.query(Episode)
                .filter(Episode.show_id == show.id, Episode.status == EpisodeStatus.DOWNLOADING)
                .order_by(Episode.season_number, Episode.episode_number)
                .all()
            )
        except Exception:
            dl_eps = []

    context_hints = [os.path.basename(download_path), show.title]
    if db:
        try:
            from app.models.db import DownloadHistory
            if torrent_hash:
                hist = db.query(DownloadHistory).filter_by(show_id=show.id).order_by(DownloadHistory.id.desc()).first()
                if hist and hist.release_title:
                    context_hints.append(hist.release_title)
        except Exception:
            pass

    for v_idx, file_path in enumerate(video_files):
        filename = os.path.basename(file_path)
        start_pct = round(v_idx / max(1, total_videos), 3)
        if progress_callback:
            try:
                progress_callback(start_pct, f"Импорт ({v_idx+1}/{total_videos}): {filename}")
            except Exception:
                pass

        parsed = parse_episode(filename)
        q_info = detect_file_quality(file_path, context_hints)
        quality = q_info.name

        if parsed.kind not in (ReleaseKind.EPISODE, ReleaseKind.ABSOLUTE) or not parsed.episodes or parsed.season is None:
            parent_dir = os.path.basename(os.path.dirname(file_path))
            if parent_dir and parent_dir != os.path.basename(download_path):
                parent_parsed = parse_episode(parent_dir + " " + filename)
                if parent_parsed.kind == ReleaseKind.EPISODE and parent_parsed.episodes:
                    parsed = parent_parsed
                elif parsed.episodes and parsed.season is None:
                    from app.services.parser import detect_season_label
                    dir_s = detect_season_label(parent_dir)
                    if dir_s.get("type") == "numbered":
                        parsed.season = dir_s["season"]
                        parsed.kind = ReleaseKind.EPISODE

        if parsed.kind not in (ReleaseKind.EPISODE, ReleaseKind.ABSOLUTE) or not parsed.episodes:
            if len(video_files) == 1:
                # Если видеофайл один, проверяем ожидающие серии
                candidate_ep = None
                if dl_eps:
                    candidate_ep = dl_eps[0]
                elif db:
                    candidate_ep = (
                        db.query(Episode)
                        .filter(Episode.show_id == show.id, Episode.status.in_([EpisodeStatus.DOWNLOADING, EpisodeStatus.WANTED, EpisodeStatus.MISSING]))
                        .order_by(Episode.season_number, Episode.episode_number)
                        .first()
                    )
                if candidate_ep:
                    parsed.episodes = [candidate_ep.episode_number]
                    parsed.season = candidate_ep.season_number
                    parsed.kind = ReleaseKind.EPISODE

        if parsed.kind not in (ReleaseKind.EPISODE, ReleaseKind.ABSOLUTE) or not parsed.episodes:
            results.append({"file": file_path, "status": "skipped", "reason": "не удалось распознать номер серии"})
            continue

        ext = os.path.splitext(file_path)[1]

        for ep_num in parsed.episodes:
            episode = None

            # 1. Приоритетный поиск среди серий этой конкретной загрузки (dl_eps)
            if dl_eps:
                if parsed.season is not None:
                    episode = next(
                        (ep for ep in dl_eps if ep.season_number == parsed.season and (ep.episode_number == ep_num or ep.absolute_number == ep_num)),
                        None,
                    )
                else:
                    episode = next(
                        (ep for ep in dl_eps if ep.episode_number == ep_num or ep.absolute_number == ep_num),
                        None,
                    )

            # 2. Поиск по базе данных
            if episode is None and db:
                if parsed.season is not None:
                    episode = (
                        db.query(Episode)
                        .filter_by(show_id=show.id, season_number=parsed.season, episode_number=ep_num)
                        .first()
                    )
                else:
                    episode = (
                        db.query(Episode)
                        .filter_by(show_id=show.id, absolute_number=ep_num)
                        .first()
                    )
                    if episode is None and dl_eps:
                        episode = (
                            db.query(Episode)
                            .filter_by(show_id=show.id, season_number=dl_eps[0].season_number, episode_number=ep_num)
                            .first()
                        )

                # Если для серии в основном сезоне запись не найдена (например, S11E00, S11E21 Special, OVA, SP),
                # проверяем наличие подходящего спецвыпуска в Сезоне 0 (Specials)
                if episode is None:
                    specials_for_show = db.query(Episode).filter_by(show_id=show.id, season_number=0).order_by(Episode.episode_number).all()
                    if specials_for_show:
                        from app.services.matcher import match_special_episode
                        episode = match_special_episode(file_path, specials_for_show, parsed)

                if episode is None and parsed.season is None:
                    episode = (
                        db.query(Episode)
                        .filter_by(show_id=show.id, season_number=1, episode_number=ep_num)
                        .first()
                    )

            if episode:
                season_num = episode.season_number
                actual_ep_num = episode.episode_number
                episode_title = episode.title or ""
                absolute_num = episode.absolute_number if episode.absolute_number is not None else ep_num
            else:
                season_num = parsed.season if parsed.season is not None else (dl_eps[0].season_number if dl_eps else 1)
                actual_ep_num = ep_num
                episode_title = ""
                absolute_num = ep_num

            is_upgrade = episode is not None and episode.status == EpisodeStatus.DOWNLOADED

            # Определяем целевую папку сезона
            season_folder_name = ""
            if season_folder_template and season_folder_template.strip():
                season_folder_name = render_season_folder_template(
                    season_folder_template,
                    season=season_num,
                    show_title=show.title,
                    year=show.year,
                )

            target_dir = os.path.join(show_root, season_folder_name) if season_folder_name else show_root
            os.makedirs(target_dir, exist_ok=True)
            apply_media_permissions(show_root, is_dir=True)
            apply_media_permissions(target_dir, is_dir=True)

            # Копируем шрифты также в папку сезона
            if font_files:
                season_fonts_dir = os.path.join(target_dir, "fonts")
                os.makedirs(season_fonts_dir, exist_ok=True)
                apply_media_permissions(season_fonts_dir, is_dir=True)
                for ff in font_files:
                    try:
                        dest_ff = os.path.join(season_fonts_dir, os.path.basename(ff))
                        shutil.copy2(ff, dest_ff)
                        apply_media_permissions(dest_ff, is_dir=False)
                    except Exception:
                        pass
                # Скрываем папку fonts из библиотеки Jellyfin через .ignore
                ensure_fonts_ignore(season_fonts_dir)

            target_stem = render_episode_template(
                rename_template,
                show_title=show.title,
                season=season_num,
                episode=actual_ep_num,
                episode_title=episode_title,
                absolute=absolute_num,
                quality=quality,
                year=show.year,
            )
            dest_video_path = os.path.join(target_dir, target_stem + ext)

            try:
                # Если уже был старый файл (замена по качеству), удаляем его и старые субтитры
                if episode and episode.file_path and os.path.exists(episode.file_path):
                    try:
                        old_stem = os.path.splitext(episode.file_path)[0]
                        os.remove(episode.file_path)
                        old_dir = os.path.dirname(episode.file_path)
                        if os.path.isdir(old_dir):
                            for old_f in os.listdir(old_dir):
                                if old_f.startswith(os.path.basename(old_stem) + "."):
                                    try:
                                        os.remove(os.path.join(old_dir, old_f))
                                    except Exception:
                                        pass
                    except OSError:
                        pass

                try:
                    shutil.move(file_path, dest_video_path)
                except OSError:
                    shutil.copy2(file_path, dest_video_path)
                    try:
                        os.remove(file_path)
                    except OSError:
                        pass
                apply_media_permissions(dest_video_path, is_dir=False)
            except Exception as exc:
                results.append({"file": file_path, "status": "failed", "reason": str(exc)})
                continue

            # Переносим сматченные субтитры к этой серии
            matched_subs = match_companion_files_for_episode(
                subtitle_files, ep_num, season_num, file_path, total_videos
            )
            for idx, sf in enumerate(matched_subs):
                if sf in used_companions or not os.path.exists(sf):
                    continue
                sub_ext = os.path.splitext(sf)[1]
                sub_tag = extract_companion_tag(sf, file_path, ep_num, release_root=download_path)
                if sub_tag:
                    dest_sub_name = f"{target_stem}.{sub_tag}{sub_ext}"
                elif len(matched_subs) > 1:
                    dest_sub_name = f"{target_stem}.sub{idx+1}{sub_ext}"
                else:
                    dest_sub_name = f"{target_stem}{sub_ext}"

                dest_sub_path = os.path.join(target_dir, dest_sub_name)
                if os.path.exists(dest_sub_path) and dest_sub_path != sf:
                    c = 1
                    base_tag = sub_tag or "sub"
                    while os.path.exists(dest_sub_path) and dest_sub_path != sf:
                        dest_sub_name = f"{target_stem}.{base_tag}_{c}{sub_ext}"
                        dest_sub_path = os.path.join(target_dir, dest_sub_name)
                        c += 1

                try:
                    shutil.move(sf, dest_sub_path)
                    apply_media_permissions(dest_sub_path, is_dir=False)
                    used_companions.add(sf)
                except Exception:
                    try:
                        shutil.copy2(sf, dest_sub_path)
                        apply_media_permissions(dest_sub_path, is_dir=False)
                    except Exception:
                        pass

            # Переносим сматченные аудиодорожки к этой серии
            matched_audios = match_companion_files_for_episode(
                audio_files, ep_num, season_num, file_path, total_videos
            )
            for idx, af in enumerate(matched_audios):
                if af in used_companions or not os.path.exists(af):
                    continue
                audio_ext = os.path.splitext(af)[1]
                audio_tag = extract_companion_tag(af, file_path, ep_num, release_root=download_path)
                if audio_tag:
                    dest_audio_name = f"{target_stem}.{audio_tag}{audio_ext}"
                elif len(matched_audios) > 1:
                    dest_audio_name = f"{target_stem}.audio{idx+1}{audio_ext}"
                else:
                    dest_audio_name = f"{target_stem}{audio_ext}"

                dest_audio_path = os.path.join(target_dir, dest_audio_name)
                if os.path.exists(dest_audio_path) and dest_audio_path != af:
                    c = 1
                    base_tag = audio_tag or "audio"
                    while os.path.exists(dest_audio_path) and dest_audio_path != af:
                        dest_audio_name = f"{target_stem}.{base_tag}_{c}{audio_ext}"
                        dest_audio_path = os.path.join(target_dir, dest_audio_name)
                        c += 1

                try:
                    shutil.move(af, dest_audio_path)
                    apply_media_permissions(dest_audio_path, is_dir=False)
                    used_companions.add(af)
                except Exception:
                    try:
                        shutil.copy2(af, dest_audio_path)
                        apply_media_permissions(dest_audio_path, is_dir=False)
                    except Exception:
                        pass

            if episode:
                episode.status = EpisodeStatus.DOWNLOADED
                episode.file_path = dest_video_path
                episode.download_progress = 1.0
                episode.downloaded_quality = quality
                if q_info.video_codec:
                    episode.video_codec = q_info.video_codec
                if q_info.audio_codec:
                    episode.audio_codec = q_info.audio_codec
                if q_info.audio_channels:
                    episode.audio_channels = q_info.audio_channels
                if q_info.dynamic_range:
                    episode.dynamic_range = q_info.dynamic_range
                if os.path.exists(dest_video_path):
                    try:
                        episode.file_size_bytes = os.path.getsize(dest_video_path)
                    except Exception:
                        pass
                db.add(episode)

            end_pct = round((v_idx + 1) / max(1, total_videos), 2)
            if progress_callback:
                try:
                    progress_callback(end_pct, f"Импортировано ({v_idx+1}/{total_videos}): {os.path.basename(dest_video_path)}")
                except Exception:
                    pass

            results.append({
                "file": file_path,
                "status": "imported",
                "dest": dest_video_path,
                "season": season_num,
                "episode": actual_ep_num,
                "is_upgrade": is_upgrade,
            })

    # Сбрасываем серии, которые были привязаны к этой загрузке, ТОЛЬКО если хотя бы один файл был успешно импортирован
    # (т.е. раздача действительно завершилась и была обработана, а не упала с ошибкой или пустым списком файлов).
    imported_count = sum(1 for r in results if r.get("status") == "imported")
    if db and imported_count > 0:
        today = dt.date.today()
        unimported_query = db.query(Episode).filter(
            Episode.show_id == show.id,
            Episode.status == EpisodeStatus.DOWNLOADING,
        )
        if torrent_hash:
            unimported_query = unimported_query.filter(Episode.torrent_hash == torrent_hash)

        try:
            unimported_eps = unimported_query.all()
            for u_ep in unimported_eps:
                u_ep.torrent_hash = None
                u_ep.download_client_id = None
                u_ep.download_progress = 0.0
                air_d = u_ep.air_date
                if isinstance(air_d, dt.datetime):
                    air_d = air_d.date()
                if air_d and air_d > today:
                    u_ep.status = EpisodeStatus.UNAIRED
                else:
                    u_ep.status = EpisodeStatus.WANTED
                db.add(u_ep)
        except Exception:
            pass

    # Очищаем оставшиеся пустые поддиректории в download_path, если это была специальная папка раздачи
    # (НИ В КОЕМ СЛУЧАЕ не удаляем поддиректории в общих корневых папках загрузок!)
    if os.path.isdir(download_path):
        from app.services.settings_service import get_or_create_settings
        st = get_or_create_settings(db) if db else None
        root_dirs = {
            os.path.abspath(st.download_folder_movies) if st and st.download_folder_movies else "",
            os.path.abspath(st.download_folder_series) if st and st.download_folder_series else "",
            os.path.abspath(st.download_folder_anime) if st and st.download_folder_anime else "",
            os.path.abspath(st.root_folder) if st and st.root_folder else "",
            os.path.abspath(root_folder) if root_folder else "",
        }
        abs_dl = os.path.abspath(download_path)
        if abs_dl not in root_dirs and not any(abs_dl == r for r in root_dirs if r):
            for root_d, dirs, files in os.walk(download_path, topdown=False):
                for d in dirs:
                    dir_to_check = os.path.join(root_d, d)
                    try:
                        if not os.listdir(dir_to_check):
                            os.rmdir(dir_to_check)
                    except Exception:
                        pass
            try:
                if not os.listdir(download_path):
                    os.rmdir(download_path)
            except Exception:
                pass

    if imported_count > 0:
        apply_media_permissions(show_root, is_dir=True, recursive=True)

    db.commit()
    return results


def process_movie_download(
    db: Session,
    show: Show,
    download_path: str,
    rename_template: str,
    root_folder: str,
    specific_files: Optional[list[str]] = None,
    progress_callback: Optional[Callable[[float, str], None]] = None,
) -> list[dict]:
    """
    Обрабатывает завершённую загрузку для фильма:
    - выбирает основной видеофайл фильма (игнорируя сэмплы/трейлеры/бонусы)
    - создает целевую папку фильма (Папка фильма)
    - переносит фильм и привязывает внешние субтитры, аудиодорожки и шрифты (fonts/)
    """
    if progress_callback:
        try:
            progress_callback(0.2, f"Поиск видеофайла фильма: {show.title}")
        except Exception:
            pass

    release_files = find_release_files(download_path, specific_files=specific_files)
    video_files = release_files["video"]
    movie_root = show.path or os.path.join(
        root_folder,
        f"{sanitize_filename(show.title)} ({show.year})" if show.year else sanitize_filename(show.title),
    )
    old_ep = db.query(Episode).filter_by(show_id=show.id, season_number=1, episode_number=1).first()

    if not video_files:
        # Проверяем, возможно файл уже был перенесён и находится в целевой папке фильма
        if old_ep and old_ep.file_path and os.path.exists(old_ep.file_path):
            old_ep.status = EpisodeStatus.DOWNLOADED
            old_ep.download_progress = 1.0
            db.add(old_ep)
            db.commit()
            return [{"file": old_ep.file_path, "status": "imported", "dest": old_ep.file_path, "season": 1, "episode": 1, "is_upgrade": False}]

        if os.path.isdir(movie_root):
            for f in os.listdir(movie_root):
                if os.path.splitext(f)[1].lower() in {".mkv", ".mp4", ".avi", ".ts", ".m2ts", ".mov"}:
                    full_p = os.path.join(movie_root, f)
                    if old_ep:
                        old_ep.status = EpisodeStatus.DOWNLOADED
                        old_ep.file_path = full_p
                        old_ep.download_progress = 1.0
                        old_ep.downloaded_quality = parse_quality(f).name
                        db.add(old_ep)
                        db.commit()
                        return [{"file": full_p, "status": "imported", "dest": full_p, "season": 1, "episode": 1, "is_upgrade": False}]

        return [{"file": download_path, "status": "skipped", "reason": "видеофайл не найден"}]

    os.makedirs(movie_root, exist_ok=True)
    apply_media_permissions(movie_root, is_dir=True)

    # Если specific_files не были переданы и найдено несколько файлов,
    # фильтруем файлы по совпадению с названием/алиасами фильма, чтобы не взять чужой файл!
    if not specific_files and len(video_files) > 1:
        from app.services.matcher import build_alias_candidates, best_alias_match
        aliases = build_alias_candidates(show, db=db)
        matched_videos = []
        for vf in video_files:
            b_alias, b_score = best_alias_match(os.path.basename(vf), aliases, threshold=60)
            if b_alias:
                matched_videos.append((vf, b_score))
        if matched_videos:
            matched_videos.sort(key=lambda x: (x[1], os.path.getsize(x[0]) if os.path.exists(x[0]) else 0), reverse=True)
            video_files = [x[0] for x in matched_videos]

    main_file = max(video_files, key=lambda f: os.path.getsize(f) if os.path.exists(f) else 0)
    ext = os.path.splitext(main_file)[1]

    context_hints = [os.path.basename(download_path), show.title]
    if db:
        try:
            from app.models.db import DownloadHistory, TrackedRelease
            hist = db.query(DownloadHistory).filter_by(show_id=show.id).order_by(DownloadHistory.id.desc()).first()
            if hist and hist.release_title:
                context_hints.append(hist.release_title)
            tr = db.query(TrackedRelease).filter_by(show_id=show.id).order_by(TrackedRelease.id.desc()).first()
            if tr and tr.topic_guid:
                context_hints.append(tr.topic_guid)
        except Exception:
            pass

    q_info = detect_file_quality(main_file, context_hints)
    quality = q_info.name

    target_stem = render_movie_template(
        rename_template,
        show_title=show.title,
        year=show.year,
        quality=quality,
    )
    dest_video_path = os.path.join(movie_root, target_stem + ext)

    if progress_callback:
        try:
            progress_callback(0.5, f"Перемещение фильма: {os.path.basename(main_file)}")
        except Exception:
            pass

    try:
        # Если уже был старый файл (замена по качеству), удаляем его
        old_ep = db.query(Episode).filter_by(show_id=show.id, season_number=1, episode_number=1).first()
        if old_ep and old_ep.file_path and os.path.exists(old_ep.file_path) and old_ep.file_path != dest_video_path:
            try:
                os.remove(old_ep.file_path)
            except OSError:
                pass
        try:
            shutil.move(main_file, dest_video_path)
        except OSError:
            shutil.copy2(main_file, dest_video_path)
            try:
                os.remove(main_file)
            except OSError:
                pass
        apply_media_permissions(dest_video_path, is_dir=False)
    except Exception as exc:
        return [{"file": main_file, "status": "failed", "reason": str(exc)}]

    # Копируем шрифты
    if release_files["font"]:
        fonts_dir = os.path.join(movie_root, "fonts")
        os.makedirs(fonts_dir, exist_ok=True)
        apply_media_permissions(fonts_dir, is_dir=True)
        for ff in release_files["font"]:
            try:
                dest_ff = os.path.join(fonts_dir, os.path.basename(ff))
                shutil.copy2(ff, dest_ff)
                apply_media_permissions(dest_ff, is_dir=False)
            except Exception:
                pass
        # Скрываем папку fonts из библиотеки Jellyfin через .ignore
        ensure_fonts_ignore(fonts_dir)

    # Переносим субтитры к фильму
    for idx, sf in enumerate(release_files["subtitle"]):
        if not os.path.exists(sf):
            continue
        sub_ext = os.path.splitext(sf)[1]
        sub_tag = extract_companion_tag(sf, main_file, release_root=download_path)
        dest_sub_name = f"{target_stem}.{sub_tag}{sub_ext}" if sub_tag else (
            f"{target_stem}.sub{idx+1}{sub_ext}" if len(release_files["subtitle"]) > 1 else f"{target_stem}{sub_ext}"
        )
        dest_sub_path = os.path.join(movie_root, dest_sub_name)
        if os.path.exists(dest_sub_path) and dest_sub_path != sf:
            c = 1
            base_tag = sub_tag or "sub"
            while os.path.exists(dest_sub_path) and dest_sub_path != sf:
                dest_sub_name = f"{target_stem}.{base_tag}_{c}{sub_ext}"
                dest_sub_path = os.path.join(movie_root, dest_sub_name)
                c += 1
        try:
            shutil.move(sf, dest_sub_path)
            apply_media_permissions(dest_sub_path, is_dir=False)
        except Exception:
            try:
                shutil.copy2(sf, dest_sub_path)
                apply_media_permissions(dest_sub_path, is_dir=False)
            except Exception:
                pass

    # Переносим аудиодорожки к фильму
    for idx, af in enumerate(release_files["audio"]):
        if not os.path.exists(af):
            continue
        audio_ext = os.path.splitext(af)[1]
        audio_tag = extract_companion_tag(af, main_file, release_root=download_path)
        dest_audio_name = f"{target_stem}.{audio_tag}{audio_ext}" if audio_tag else (
            f"{target_stem}.audio{idx+1}{audio_ext}" if len(release_files["audio"]) > 1 else f"{target_stem}{audio_ext}"
        )
        dest_audio_path = os.path.join(movie_root, dest_audio_name)
        if os.path.exists(dest_audio_path) and dest_audio_path != af:
            c = 1
            base_tag = audio_tag or "audio"
            while os.path.exists(dest_audio_path) and dest_audio_path != af:
                dest_audio_name = f"{target_stem}.{base_tag}_{c}{audio_ext}"
                dest_audio_path = os.path.join(movie_root, dest_audio_name)
                c += 1
        try:
            shutil.move(af, dest_audio_path)
            apply_media_permissions(dest_audio_path, is_dir=False)
        except Exception:
            try:
                shutil.copy2(af, dest_audio_path)
                apply_media_permissions(dest_audio_path, is_dir=False)
            except Exception:
                pass

    if not show.path and movie_root:
        show.path = movie_root
        db.add(show)

    # У фильма ровно одна "серия"-заглушка
    episode = db.query(Episode).filter_by(show_id=show.id, season_number=1, episode_number=1).first()
    is_upgrade = episode is not None and episode.status == EpisodeStatus.DOWNLOADED
    if not episode:
        episode = Episode(
            show_id=show.id,
            season_number=1,
            episode_number=1,
            title=show.title,
            status=EpisodeStatus.DOWNLOADED,
            file_path=dest_video_path,
            download_progress=1.0,
            downloaded_quality=quality,
            video_codec=q_info.video_codec,
            audio_codec=q_info.audio_codec,
            audio_channels=q_info.audio_channels,
            dynamic_range=q_info.dynamic_range,
            file_size_bytes=os.path.getsize(dest_video_path) if os.path.exists(dest_video_path) else None,
        )
        db.add(episode)
    else:
        episode.status = EpisodeStatus.DOWNLOADED
        episode.file_path = dest_video_path
        episode.download_progress = 1.0
        episode.downloaded_quality = quality
        if q_info.video_codec:
            episode.video_codec = q_info.video_codec
        if q_info.audio_codec:
            episode.audio_codec = q_info.audio_codec
        if q_info.audio_channels:
            episode.audio_channels = q_info.audio_channels
        if q_info.dynamic_range:
            episode.dynamic_range = q_info.dynamic_range
        if os.path.exists(dest_video_path):
            try:
                episode.file_size_bytes = os.path.getsize(dest_video_path)
            except Exception:
                pass
        db.add(episode)

    # Очищаем оставшиеся пустые поддиректории в download_path, если это была специальная папка раздачи
    # (НИ В КОЕМ СЛУЧАЕ не удаляем поддиректории в общих корневых папках загрузок!)
    if os.path.isdir(download_path):
        from app.services.settings_service import get_or_create_settings
        st = get_or_create_settings(db) if db else None
        root_dirs = {
            os.path.abspath(st.download_folder_movies) if st and st.download_folder_movies else "",
            os.path.abspath(st.download_folder_series) if st and st.download_folder_series else "",
            os.path.abspath(st.download_folder_anime) if st and st.download_folder_anime else "",
            os.path.abspath(st.root_folder) if st and st.root_folder else "",
            os.path.abspath(root_folder) if root_folder else "",
        }
        abs_dl = os.path.abspath(download_path)
        if abs_dl not in root_dirs and not any(abs_dl == r for r in root_dirs if r):
            for root_d, dirs, files in os.walk(download_path, topdown=False):
                for d in dirs:
                    dir_to_check = os.path.join(root_d, d)
                    try:
                        if not os.listdir(dir_to_check):
                            os.rmdir(dir_to_check)
                    except Exception:
                        pass
            try:
                if not os.listdir(download_path):
                    os.rmdir(download_path)
            except Exception:
                pass

    apply_media_permissions(movie_root, is_dir=True, recursive=True)

    db.commit()
    return [{"file": main_file, "status": "imported", "dest": dest_video_path, "season": 1, "episode": 1, "is_upgrade": is_upgrade}]
