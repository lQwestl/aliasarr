"""
Alias-matcher: сопоставляет имя релиза (топика с трекера) с шоу по списку
алиасов (рус/eng/jp/romaji), с учётом парсинга номера серии.

Использует rapidfuzz для нечёткого сравнения нормализованных строк.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from typing import Iterable, Optional

try:
    from rapidfuzz import fuzz
except ImportError:
    class FuzzFallback:
        @staticmethod
        def partial_ratio(s1: str, s2: str) -> float:
            return 100.0 if s1 and s2 and (s1 in s2 or s2 in s1) else 0.0

        @staticmethod
        def token_set_ratio(s1: str, s2: str) -> float:
            w1, w2 = set(s1.split()), set(s2.split())
            if not w1 or not w2:
                return 0.0
            return (len(w1 & w2) / max(len(w1), len(w2))) * 100.0

        @staticmethod
        def token_sort_ratio(s1: str, s2: str) -> float:
            return 100.0 if " ".join(sorted(s1.split())) == " ".join(sorted(s2.split())) else 0.0

    fuzz = FuzzFallback

from app.services.parser import ParsedRelease, ReleaseKind, parse_episode

# Порог уверенности fuzzy-совпадения имени (0-100)
DEFAULT_FUZZY_THRESHOLD = 82


@dataclass
class AliasCandidate:
    alias_id: int
    text: str
    language: str = "ru"
    priority: int = 100


@dataclass
class MatchResult:
    matched: bool
    show_id: Optional[int]
    alias_id: Optional[int]
    alias_text: Optional[str]
    score: float
    parsed: ParsedRelease


_JUNK_WORDS = {
    "webrip", "webdl", "web", "dl", "hdtv", "bdrip", "bluray", "remux",
    "rus", "eng", "sub", "dub", "dubbed", "subbed", "vo", "многоголосый",
    "закадровый", "перевод", "озвучка", "субтитры", "hevc", "aac",
}

# Ключевые слова релизов НЕ-видео контента (игры, консоли, ROM, софт, манга, артбуки, саундтреки, чистый звук, дорожки, сабы, музыка и т.д.),
# а также опенинги, эндинги, трейлеры, бонусы и спешлы, не являющиеся регулярными видео-сериями или фильмами.
NON_VIDEO_KEYWORDS = re.compile(
    r"("
    r"манг[аи]|manga|"
    r"ранобэ|ранобе|light\s?novel|ranobe|"
    r"артбук|art\s?book|"
    r"саундтрек(?:и)?|soundtracks?|\bost\b|"
    r"\b(?:wavpack|ape|alac|dxd|sacd|dsd\d*|vinyl|audio\s*cd|maxi[-_\s]?single|single|mini[-_\s]?album)\b|\[ep\]|\(ep\)|"
    r"\b(?:tracks\+?\.?cue|image\+?\.?cue|lossless|flac\s*\(tracks\)|flac\s*\(image|discography|дискография)\b|"
    r"\[(?:32/\d+|24/\d+|12\"|dxd|tr\d+|vinyl|lp|cd)\]|"
    r"\((?:12\"|32/\d+|24/\d+|tracks|image\+\.cue|tracks\+\.cue|wavpack|flac)\)|"
    r"\b(?:death\s*metal|black\s*metal|heavy\s*metal|hard\s*rock|prog\s*rock|krautrock|psychedelic|occult\s*rock|euro[-_\s]?disco|synth[-_\s]?pop|ambient|trance|hip[-_\s]?hop)\b|"
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
    r"\bopenings?\s*(?:&|and)\s*endings?\b|"
    r"\b(?:rus|eng|jap|jpn|ukr|ger|fra|spa)?\s*(?:soundtracks?|\bost\b|audio[-\s]?tracks?|чистый\s*звук|звуковые\s*дорожки|звуковая\s*дорожка|переводы\s*\(аниме\)|аудиодорожк[иа]|звуковые\s*файлы|sound\s*pack|audio\s*pack|только\s*звук|только\s*аудио|sound\s*only|audio\s*only|озвучка\s*отдельно|аудиокниг[иа]|audiobooks?)\b|"
    r"\[(?:audio|sound|soundtrack|ost|audio[-\s]?tracks?|звук|аудиодорожки|звуковые\s*дорожки|озвучка\s*отдельно|art|арт|сканы|scans|wallpapers|обои|jpg|png)\]|"
    r"\((?:audio|sound|soundtrack|ost|audio[-\s]?tracks?|звук|аудиодорожки|звуковые\s*дорожки|озвучка\s*отдельно|art|арт|сканы|scans|wallpapers|обои)\)|"
    r"\b(?:rus|eng|jap|jpn|ukr)?\s*(?:subs?\s*only|только\s*субтитры|только\s*сабы|subtitles?\s*pack|пак\s*субтитров)\b|"
    r"\[(?:subs\s*only|субтитры|сабы|пак\s*субтитров)\]|"
    r"\((?:subs\s*only|субтитры|сабы|пак\s*субтитров)\)|"
    r"додзинси|doujin|"
    r"комикс(?:ы)?|comic(?!s? *tv)|"
    r"\bscans?\b|\bсканы\b|"
    r"\[flac\]|\[mp3\]|\[lossless\]|\[aac\]|\[аас\]|\[ac3\]|\[dts\]|\bflac\s+pack\b|\bmp3\s+pack\b|"
    r"\[(?:19|20)\d{2},\s*(?:[АаAa][АаAa][СсCc]|AAC|AC3|DTS|FLAC|MP3|WAV|Аудио)[^\]]*\]|"
    r"\b\d+\s*kbps\b|\b(?:mp3|flac)\s*\([^)]*tracks[^)]*\)|\b(?:mp3|flac)\s*,\s*\d+\s*kbps\b|"
    r"\b(?:manga|манга|манхва|маньхуа|manhwa|manhua|webtoon|ранобэ|ranobe|light\s*novel|light\s*novels|ln|новелл[аы]|артбук[иа]?|artbooks?|e-?books?|audiobooks?|аудиокниг[иа]|журналы?)\b|"
    r"\b(?:epub|fb2|mobi|azw3?|djvu|cbr|cbz|pdf)\b|"
    r"\[(?:epub|fb2|pdf|djvu|cbr|cbz|mobi|azw3?|manga|манга|ранобэ|ln|light\s*novel|artbook|артбук|книга|книги|тома|том|главы|глава|арка|арки|vol|vols)[^\]]*\]|"
    r"\((?:epub|fb2|pdf|djvu|cbr|cbz|mobi|azw3?|manga|манга|ранобэ|ln|light\s*novel|artbook|артбук|книга|книги|тома|том|главы|глава|арка|арки|vol|vols)[^\)]*\)|"
    r"\b(?:тома|том|главы|глава|арка|арки)\s*\d+\b|"
    r"\bvols?\.?\s*\d+\s*[-–~]\s*\d+\b|"
    r"\.cbz\b|\.cbr\b|\.pdf\b|\.epub\b|\.fb2\b|\.djvu\b|"
    r"\[(?:ли)\]|\((?:ли)\)|"
    # Игры, консоли, платформы, ROM, образы дисков, репаки и софт:
    r"\b(?:nintendo(?:\s*(?:wii(?:\s*u)?|switch|nsw|3ds|nds|ds|gba|gbc|gamecube|ngc|n64|snes|nes|virtual\s*boy))?)\b|"
    r"\[(?:nintendo(?:\s*wii)?|wii|wii-u|wiiu|switch|nsw|3ds|nds|gba|gbc|gamecube|ngc|n64|snes|nes|ps[1-5]|psx|psp|ps\s*vita|psvita|xbox|xbox360|xbox\s*360|xbox\s*one|xbox\s*series|x360|xone|pc|mac|linux|android|ios|win/mac|p|scene)\]|"
    r"\((?:nintendo(?:\s*wii)?|wii|wii-u|wiiu|switch|nsw|3ds|nds|gba|gbc|gamecube|ngc|n64|snes|nes|ps[1-5]|psx|psp|ps\s*vita|psvita|xbox|xbox360|xbox\s*360|xbox\s*one|xbox\s*series|x360|xone|win/mac)\)|"
    r"\b(?:wii|wii-u|wiiu|gamecube|ngc|n64|gba|nds|3ds|snes|nes)\b|"
    r"\[[^\]]*\b(?:ntsc|pal|ntsc-u|ntsc-j|pal-e|pal/eng|ntsc/eng|ntsc/rus|pal/rus|region\s*free)\b[^\]]*\]|"
    r"\([^)]*\b(?:ntsc|pal|ntsc-u|ntsc-j|pal-e|pal/eng|ntsc/eng|ntsc/rus|pal/rus|region\s*free)\b[^)]*\)|"
    r"\b(?:playstation(?:\s*[1-5]|\s*portable|\s*vita)?|ps[1-5]|psx|psp|ps\s*vita|psvita)\b(?=.*(?:\[|\b(?:game|iso|rom|pkg|ntsc|pal|cusa\d+|usa|eur|jpn)\b))|"
    r"\b(?:xbox(?:\s*360|\s*one|\s*series\s*[xs])?|x360|xone)\b(?=.*(?:\[|\b(?:game|iso|rom|jtag|rgh|god|xex|pal|ntsc)\b))|"
    r"\b(?:pc\s*games?|pc\s*iso|pc\s*rip|mac\s*games?|linux\s*games?|android\s*games?|ios\s*games?)\b|"
    r"\b(?:steam[-_\s]?rip|gog\s*rip|gog\s*edition|full\s*game|game\s*rip)\b|"
    r"\b(?:nsp|xci|cia|vpk|wbfs|gcm|nkit|rvz|chd|pbp|xex|god|cso)\b|"
    r"\[(?:iso|cso|wbfs|nsp|xci|cia|vpk|gcm|nkit|rvz|chd|pbp|xex|god|rom|bin|cue|nds|3ds|gba|nes|sfc|smc|wad|pkg|prototype|beta|alpha|devbuild|debug|trainer|cheat|homebrew|rom\s*hack|crack|keygen|patch|activator|repack|duplex|codex|skidrow|flt|rune|tenoke|dlc|portable|game|vn|rpg|wall|wallpapers?|calendars?|dl)\]|"
    r"\((?:iso|cso|wbfs|nsp|xci|cia|vpk|gcm|nkit|rvz|chd|pbp|xex|god|rom|bin|cue|nds|3ds|gba|nes|sfc|smc|wad|pkg|prototype|beta|alpha|devbuild|debug|trainer|cheat|homebrew|rom\s*hack|crack|keygen|patch|activator|repack|duplex|codex|skidrow|flt|rune|tenoke|dlc|portable)\)|"
    r"\[(?:eur|usa|jpn|us|jp|eu|asia)/(?:rus|eng|jap|multi)\]|"
    r"pc\s*\|\s*(?:пиратка|лицензия|repack|portable)|"
    r"\b(?:repack|русификатор|gamesvoice|ps\s*vr|steam|gog|duplex|codex|tenoke|razor1911|dlc|eshop|portable|suxxors|strike|playasia|insaneramzes|pSyPSP|unlimited|arcade\s*games?|игров(?:ой\s+автомат|ые\s+автоматы))\b|"
    r"\[(?:игровой\s+автомат|arcade\s*game)\]|"
    r"\b(?:electro\s*house|house|trance|synthwave|techno|classical)\b|"
    r"\b(?:автоспорт|мотоспорт|motorsport|drag\s*racing|formula\s*1|f1|ufc|mma|бокс)\b|"
    r"\b(?:обои|wallpapers?|календар(?:ь|и)|calendars?)\b|"
    r"\.(?:iso|cso|wbfs|nsp|xci|cia|vpk|gcm|nkit|rvz|chd|pbp|xex|god|rom|nds|3ds|gba|nes|sfc|smc|wad|pkg|exe|msi|apk|ipa)\b|"
    r"\b(?:fitgirl|dodi|codex|skidrow|flt|empress|plaza|rune|cpy|hoodlum|xatab|decepticon|chikibriki|igruha|хатаб|механики)\b|"
    r"\b(?:repack\s+by|repack\s+от|репак\s+от|rip\s+by)\b|"
    r"\b(?:trainer|cheat\s*table|homebrew|rom\s*hack|savegame|game\s*save)\b|"
    r"\b(?:prototype|devbuild|debug\s*build)\b"
    r")",
    re.IGNORECASE,
)

NON_VIDEO_CATEGORY_RANGES = [
    (1000, 1999),  # Console / Games
    (4000, 4999),  # PC Software / Games
    (7000, 7999),  # Books / Comics / EBooks
]

NON_VIDEO_EXACT_CATEGORIES = {
    3010, 3030, 3040, 3050, 3060,  # Audio non-video (MP3, Audiobooks, Lossless)
    8000, 8010, 8020,              # Other non-video
}

VIDEO_CATEGORY_RANGES = [
    (2000, 2999),  # Movies
    (5000, 5999),  # TV / Anime
]


def is_non_video_release(title: str, categories: Optional[list[int]] = None) -> bool:
    """True, если релиз похож на не-видео контент (игры/консоли/ROM/софт/манга/артбук/саундтрек и т.п.)."""
    if NON_VIDEO_KEYWORDS.search(title or ""):
        return True

    if categories:
        has_video_cat = False
        all_non_video = True
        for cat in categories:
            is_video = any(start <= cat <= end for start, end in VIDEO_CATEGORY_RANGES) or cat == 3020
            if is_video:
                has_video_cat = True
                all_non_video = False
                break
            is_non_video = (
                any(start <= cat <= end for start, end in NON_VIDEO_CATEGORY_RANGES)
                or cat in NON_VIDEO_EXACT_CATEGORIES
            )
            if not is_non_video:
                all_non_video = False

        if not has_video_cat and all_non_video:
            return True

    return False


def build_alias_candidates(show, db=None) -> list[AliasCandidate]:
    """
    Формирует список кандидатов для поиска и сопоставления.
    Включает основное название тайтла и все пользовательские/автоматические алиасы из БД.
    Автоматически расщепляет составные алиасы (содержащие слэши или пайпы) на отдельные под-алиасы.
    Список отсортирован по приоритету: меньшее число = опрашивается раньше.
    """
    seen_normalized: set[str] = set()
    candidates: list[AliasCandidate] = []

    show_title = (getattr(show, "title", "") or "").strip()
    title_parts = [show_title] if show_title else []
    if "/" in show_title or "|" in show_title:
        title_parts.extend([p.strip() for p in re.split(r"\s*[/|]\s*", show_title) if p.strip()])

    # Если название шоу содержит год (например "Scrubs (2026)"), автоматически добавляем чистое имя ("Scrubs")
    for tp in list(title_parts):
        no_yr = re.sub(r"\s*\(\d{4}\)$|\s+\d{4}$", "", tp).strip()
        if no_yr and no_yr != tp and no_yr not in title_parts:
            title_parts.append(no_yr)

    for tp in title_parts:
        title_norm = normalize_title(tp)
        if title_norm and title_norm not in seen_normalized:
            seen_normalized.add(title_norm)
            candidates.append(AliasCandidate(alias_id=0, text=tp, language="en", priority=0))

    # Извлекаем все алиасы напрямую из БД, если передан db, чтобы избежать устаревшего кэша SQLAlchemy
    aliases = []
    if db is not None and getattr(show, "id", None):
        try:
            from app.models.db import Alias
            aliases = db.query(Alias).filter(Alias.show_id == show.id).all()
        except Exception:
            aliases = getattr(show, "aliases", []) or []
    else:
        aliases = getattr(show, "aliases", []) or []

    for alias in aliases:
        a_text = (getattr(alias, "text", "") or "").strip()
        if not a_text:
            continue

        sub_parts = [a_text]
        if "/" in a_text or "|" in a_text:
            sub_parts.extend([p.strip() for p in re.split(r"\s*[/|]\s*", a_text) if p.strip()])

        for part in list(sub_parts):
            no_yr = re.sub(r"\s*\(\d{4}\)$|\s+\d{4}$", "", part).strip()
            if no_yr and no_yr != part and no_yr not in sub_parts:
                sub_parts.append(no_yr)

        lang_str = alias.language.value if hasattr(getattr(alias, "language", None), "value") else (str(alias.language) if getattr(alias, "language", None) else "ru")
        prio = getattr(alias, "priority", 100) or 100

        for part in sub_parts:
            norm = normalize_title(part)
            if not norm or norm in seen_normalized:
                continue
            seen_normalized.add(norm)
            candidates.append(AliasCandidate(
                alias_id=getattr(alias, "id", 0) or 0,
                text=part,
                language=lang_str,
                priority=prio,
            ))

    # Приоритет — единственный фактор порядка (НЕ язык): меньше число = ищем раньше.
    candidates.sort(key=lambda c: c.priority)
    return candidates


def normalize_title(text: str) -> str:
    """Приводит название к сравнимому виду: нижний регистр, без пунктуации и шумовых слов."""
    text = text.lower()
    text = re.sub(r"['’`´]s\b", "", text)
    text = re.sub(r"[._\[\](){}\-–—/|]", " ", text)
    text = re.sub(r"[^\w\s]", " ", text, flags=re.UNICODE)
    words = [w for w in text.split() if w not in _JUNK_WORDS]
    return " ".join(words).strip()


_TITLE_STOPWORDS = {"the", "a", "an", "of", "and", "in", "on", "at", "to", "for", "with", "by", "tv", "hd"}


def _clean_stopwords(text: str) -> str:
    """Убирает вспомогательные артикли и предлоги для сравнения заголовков."""
    words = [w for w in text.split() if w not in _TITLE_STOPWORDS]
    return " ".join(words).strip()


def extract_title_segments(release_name: str) -> list[str]:
    """
    Извлекает сегменты названий тайтла из имени релиза (русское / английское / оригинальное),
    отсекая технический мусор, скобки релиз-групп, указания сезонов, года и разрешения.
    """
    s = re.sub(r"^\s*(?:\[[^\]]*\]|\([^\)]*\))\s*", "", release_name or "")
    raw_parts = re.split(r"\s*[/|]\s*", s)
    cut_re = re.compile(
        r"""
        (?:
            \s*\(|\s*\[|\s*[-–]\s*\d
        |   [._\s]\b(?:S\d{1,3}(?:[-_.\s]*E\d{1,3})?|E\d{1,3}|EP\d{1,3}|Seasons?[-_.:\s]*\d|Сез(?:он(?:ы|а|ов)?)?[-_.:\s]*\d)\b
        |   \b(?:\d{1,3}(?:st|nd|rd|th|[-–]?(?:й|ый|ой|ий|я|ая))?\s*(?:[-–~]\s*\d{1,3})?\s*(?:сезон(?:ы|а|ов)?|seasons?|sezon(?:y|i|a)?))\b
        |   \b(?:Season|Сезон|sezon)\s*\d{1,3}\b
        |   \b(?:ТВ|TV)[\s\-_]?\d{1,2}\b
        |   \b(?:Part|Часть|Cour|Кур)\s*\d{1,2}\b
        |   [._\s]\b(?:Complete|Full\b|19\d\d|20\d\d|1080p|720p|2160p|480p|576p|BDRip|WEB-?DL|WEBRip|HDTV|Remux)\b
        )
        """,
        re.IGNORECASE | re.VERBOSE,
    )
    clean_segments: list[str] = []
    for p in raw_parts:
        m = cut_re.search(p)
        if m:
            p = p[:m.start()]
        cleaned = normalize_title(p)
        if cleaned:
            clean_segments.append(cleaned)

    full_norm = normalize_title(release_name)
    if full_norm and full_norm not in clean_segments:
        clean_segments.append(full_norm)

    return clean_segments


def best_alias_match(
    release_name: str,
    aliases: Iterable[AliasCandidate],
    threshold: int = DEFAULT_FUZZY_THRESHOLD,
) -> tuple[Optional[AliasCandidate], float]:
    """
    Находит алиас с максимальным fuzzy-скором против имени релиза.
    Точно проверяет совпадение сегментов тайтла и штрафует лишние слова (например, "Comet Lucifer" != "Lucifer").
    """
    segments = extract_title_segments(release_name)
    if not segments:
        return None, 0.0

    best: Optional[AliasCandidate] = None
    best_score = 0.0

    for alias in aliases:
        norm_alias = normalize_title(alias.text)
        if not norm_alias:
            continue

        alias_words = set(norm_alias.split())
        alias_clean = _clean_stopwords(norm_alias)

        for seg in segments:
            seg_words = set(seg.split())
            seg_clean = _clean_stopwords(seg)

            # 1. Точное совпадение сегмента с алиасом (с учётом или без стоп-слов)
            if seg == norm_alias or (alias_clean and seg_clean == alias_clean):
                score = 100.0
                if score > best_score:
                    best_score = score
                    best = alias
                continue

            # 2. Нечёткое сравнение полного сегмента
            sort_ratio = fuzz.token_sort_ratio(norm_alias, seg)
            ratio = fuzz.ratio(norm_alias, seg) if hasattr(fuzz, "ratio") else fuzz.token_sort_ratio(norm_alias, seg)
            base_score = max(ratio, sort_ratio)

            # Для коротких алиасов (1 слово или длина <= 8 символов) не допускаем подмену слова (например, Luzifer != Lucifer)
            if len(alias_words) == 1 and len(seg_words) == 1:
                if norm_alias != seg:
                    if len(norm_alias) <= 8 or base_score < 95.0:
                        continue

            # Проверяем наличие лишних значимых слов (например: "comet lucifer" против "lucifer")
            extra_words = seg_words - alias_words - _TITLE_STOPWORDS
            missing_words = alias_words - seg_words - _TITLE_STOPWORDS

            if extra_words:
                # Сильный штраф за посторонние слова в названии
                penalty = len(extra_words) * 35.0
                score = max(0.0, base_score - penalty)
            elif missing_words:
                penalty = len(missing_words) * 30.0
                score = max(0.0, base_score - penalty)
            else:
                score = base_score

            if score > best_score:
                best_score = score
                best = alias

    if best is not None and best_score >= threshold:
        return best, best_score
    return None, best_score


MOVIE_KEYWORDS = re.compile(
    r"\b(movie|film|фильм|полнометражный\s*фильм|телефильм|the\s+movie)\b",
    re.IGNORECASE,
)


DORAMA_KEYWORDS = re.compile(
    r"\b(?:дорам[аыеу]|дорама|dorama|live[-_\s]*action|j[-_\s]*dorama|k[-_\s]*dorama|тв-дорама)\b",
    re.IGNORECASE,
)

RAW_DISC_KEYWORDS = re.compile(
    r"(?<![a-z0-9])(?:\d+\s*x\s*DVD[59]?|\d+\s*x\s*BD(?:25|50)?|\d+\s*x\s*DVD|DVD9|DVD5|BDMV|2x\s*DVD9\s*\+\s*8x\s*DVD5)(?![a-z0-9])",
    re.IGNORECASE,
)


def match_release(
    release_name: str,
    show_id: int,
    aliases: Iterable[AliasCandidate],
    threshold: int = DEFAULT_FUZZY_THRESHOLD,
    content_type: str = "series",
    categories: Optional[list[int]] = None,
    show_year: Optional[int] = None,
) -> MatchResult:
    """Полный матчинг релиза: алиас (fuzzy) + парсинг номера серии + проверка типа контента и года."""
    alias, score = best_alias_match(release_name, aliases, threshold)
    parsed = parse_episode(release_name)

    # Отсеиваем не-видео релизы (игры, консоли, ROM, софт, манга, артбуки, OST/саундтреки)
    if is_non_video_release(release_name, categories=categories):
        return MatchResult(
            matched=False, show_id=None, alias_id=None, alias_text=None,
            score=score, parsed=parsed,
        )

    # Отсеиваем сырые многодисковые образы (10x DVD9, 8x DVD5, BDMV) для сериалов/аниме
    if content_type in ("series", "anime") and RAW_DISC_KEYWORDS.search(release_name):
        return MatchResult(
            matched=False, show_id=None, alias_id=None, alias_text=None,
            score=score, parsed=parsed,
        )

    # Отсеиваем дорамы / live-action при поиске аниме
    if content_type == "anime" and DORAMA_KEYWORDS.search(release_name):
        return MatchResult(
            matched=False, show_id=None, alias_id=None, alias_text=None,
            score=score, parsed=parsed,
        )

    # Проверка соответствия года выхода (исключает ремейки, перезапуски и одноименные фильмы других годов)
    if isinstance(show_year, int) and show_year > 1900:
        clean_rel = re.sub(r"\b(1080|2160|1440|720|480|360|240)[pi]?\b", "", release_name, flags=re.IGNORECASE)
        rel_years = [int(y) for y in re.findall(r"\b(19\d\d|20\d\d)\b", clean_rel)]
        if rel_years:
            if content_type == "movie":
                has_matching_year = any(abs(y - show_year) <= 1 for y in rel_years)
            else:
                from app.services.parser import detect_season_label
                s_lbl = detect_season_label(release_name)
                s_num = parsed.season or (s_lbl.get("season") if s_lbl.get("type") == "numbered" else None)
                s_list = parsed.seasons or (s_lbl.get("seasons") if s_lbl.get("type") == "range" else [])
                is_subsequent_season = bool((s_num and s_num >= 2) or any(s >= 2 for s in s_list))

                if is_subsequent_season:
                    # Для сезонов 2+ (S2, S3, S4) релиз закономерно выходит в более поздние годы (например, 2024 при старте в 2016).
                    has_matching_year = any(y >= (show_year - 2) for y in rel_years)
                else:
                    # Для 1-го сезона / сериала без указания сезона — год должен соответствовать году выхода сериала (±1 год).
                    has_matching_year = any(abs(y - show_year) <= 1 for y in rel_years)

            if not has_matching_year:
                return MatchResult(
                    matched=False, show_id=None, alias_id=None, alias_text=None,
                    score=score, parsed=parsed,
                )

    if alias is None:
        return MatchResult(
            matched=False, show_id=None, alias_id=None, alias_text=None,
            score=score, parsed=parsed,
        )

    # Защита от фильмов и спин-оффов при поиске сериала / аниме-сериала
    if content_type in ("series", "anime"):
        # Если релиз помечен как отдельный фильм (Movie / Film / Фильм)
        if MOVIE_KEYWORDS.search(release_name):
            alias_has_movie = bool(MOVIE_KEYWORDS.search(alias.text))
            if not alias_has_movie:
                # Проверяем, есть ли явная метка сезона (например, Season 1)
                from app.services.parser import detect_season_label
                s_lbl = detect_season_label(release_name)
                if s_lbl["type"] not in ("numbered", "range", "complete", "final"):
                    return MatchResult(
                        matched=False, show_id=None, alias_id=None, alias_text=None,
                        score=score, parsed=parsed,
                    )

        # Если релиз не имеет ни сезона, ни серий, ни меток пака (одиночный фильм)
        from app.services.parser import detect_season_label
        s_lbl = detect_season_label(release_name)
        if parsed.kind == ReleaseKind.UNKNOWN and s_lbl["type"] == "none":
            # Для сериалов/аниме одиночные релизы без сезонов/серий не должны матчиться
            return MatchResult(
                matched=False, show_id=None, alias_id=None, alias_text=None,
                score=score, parsed=parsed,
            )

        # Защита от спин-офф префиксов ("El Camino: A Breaking Bad Movie", "Better Call Saul: ...")
        # Если до двоеточия или тире идёт заголовок другого тайтла, которого нет среди алиасов
        if ":" in release_name or " - " in release_name:
            norm_rel_lower = release_name.lower()
            prefix_part = norm_rel_lower.split(":", 1)[0] if ":" in norm_rel_lower else norm_rel_lower.split(" - ", 1)[0]
            norm_prefix = normalize_title(prefix_part)
            if len(norm_prefix) >= 4:
                prefix_matches_any_alias = any(
                    normalize_title(a.text) in norm_prefix or norm_prefix in normalize_title(a.text)
                    for a in aliases
                )
                if not prefix_matches_any_alias:
                    if s_lbl["type"] not in ("numbered", "range", "complete", "final"):
                        return MatchResult(
                            matched=False, show_id=None, alias_id=None, alias_text=None,
                            score=score, parsed=parsed,
                        )

    # Для фильмов: номера в названии («Эпизод 4», «Часть 2») — часть названия франшизы, а не серии сериала
    if content_type == "movie":
        parsed = ParsedRelease(
            kind=ReleaseKind.EPISODE,
            season=None,
            episodes=[],
            raw=release_name,
            matched_pattern="movie",
        )

    return MatchResult(
        matched=True, show_id=show_id, alias_id=alias.alias_id, alias_text=alias.text,
        score=score, parsed=parsed,
    )


def score_candidate(
    match: MatchResult,
    seeders: int = 0,
    quality_rank: int = 0,
    size_bytes: int = 0,
    preferred_size_bytes: Optional[int] = None,
) -> float:
    """
    Скоринг релиза-кандидата для выбора лучшего среди совпавших.
    Простая взвешенная сумма: совпадение имени + сиды + качество + близость к целевому размеру.
    """
    if not match.matched:
        return -1.0

    name_component = match.score  # 0-100
    seed_component = min(seeders, 200) / 2  # 0-100, насыщение на 200 сидах
    quality_component = quality_rank * 10  # предполагается 0-10 ранг качества

    size_component = 0.0
    if preferred_size_bytes and size_bytes:
        diff_ratio = abs(size_bytes - preferred_size_bytes) / preferred_size_bytes
        size_component = max(0.0, 100 - diff_ratio * 100)

    return (
        name_component * 0.4
        + seed_component * 0.25
        + quality_component * 0.2
        + size_component * 0.15
    )


def match_special_episode(filepath_or_name: str, specials: list, parsed_ep: Optional[ParsedRelease] = None):
    """
    Интеллектуальное сопоставление файла/папки спецвыпуска с серией из Сезона 0 (Specials).
    Учитывает:
    1. Названия арок / подзаголовки спешлов (fuzzy & semantic match).
    2. Прямой номер спешла SP xx (SP 01 -> Episode 1).
    3. OVA-индекс (OVA 1-5 -> сопоставление с OVA-сериями спешлов).
    4. Сезонный спешл (Season 1 SP, Season 2 SP).
    """
    if not specials:
        return None

    try:
        path_lower = filepath_or_name.lower().replace("\\", "/")
        fname = os.path.basename(path_lower)
        fstem = os.path.splitext(fname)[0]

        # Справочник распространенных ключевых слов и переводов арок спешлов
        SECTOR_KEYWORDS = {
            "coleus": ["coleus", "koriusu", "колеус", "кориус", "コリウス"],
            "guren": ["guren", "scarlet", "kizuna", "гурен", "алые узы", "紅蓮"],
            "veldora": ["veldora", "verudora", "вельдор"],
            "hinata": ["hinata", "хината"],
            "diablo": ["diablo", "диабло"],
            "luminous": ["luminous", "luminus", "люминус"],
            "teacher": ["teacher", "glamorous", "учител"],
            "tragedy": ["tragedy", "трагеди"],
            "butts": ["butts", "butt", "трусик"],
        }

        # 1. Поиск совпадений по ключевым аркам
        for kw_key, kw_list in SECTOR_KEYWORDS.items():
            if any(k in path_lower for k in kw_list):
                m_num = re.search(r"(?:0?([1-9]))(?:\.avi|\.mkv|\.mp4|\b)", fname)
                sub_idx = int(m_num.group(1)) if m_num else 1
                matching_eps = [
                    e for e in specials
                    if any(k in (getattr(e, "title", None) or "").lower() for k in kw_list)
                ]
                if matching_eps:
                    if len(matching_eps) >= sub_idx:
                        return matching_eps[sub_idx - 1]
                    return matching_eps[0]

        # 2. Нечеткое сопоставление по полному названию серии и ключевым словам спешла
        best_ep = None
        best_score = 0.0

        # Очищаем имя файла от технических тегов качества/кодеков для чистого сравнения названий
        clean_path = re.sub(r"\b(?:1080p|720p|2160p|4k|web-?dl|bluray|hdtv|hevc|x264|x265|aac|ac3|dts|flac|rus|eng|sub|subs|lostfilm|tvshows|hdrezka|alexfilm)\b", " ", path_lower)
        clean_path = re.sub(r"[\._\-\(\)\[\]:;!\?']+", " ", clean_path)

        GENERIC_SPECIAL_WORDS = {"special", "specials", "спешл", "спешлы", "спецвыпуск", "спецвыпуски", "ova", "ona", "oad", "episode", "episodes", "season", "сезон", "part", "часть", "фильм", "movie", "film"}

        for ep in specials:
            title = (getattr(ep, "title", None) or "").strip().lower()
            if not title:
                continue
            clean_title = re.sub(r"[\._\-\(\)\[\]:;!\?']+", " ", title).strip()
            
            words = [w for w in clean_title.split() if len(w) >= 3 and w not in GENERIC_SPECIAL_WORDS]
            token_score = fuzz.token_set_ratio(clean_title, clean_path)
            partial_score = fuzz.partial_ratio(clean_title, clean_path) if len(clean_title) >= 6 else 0
            
            if words:
                matching = [w for w in words if w in clean_path]
                word_ratio = len(matching) / len(words)
                effective_score = (word_ratio * 70.0) + (max(token_score, partial_score) * 0.3)
                if word_ratio >= 0.8:
                    effective_score = max(effective_score, 85.0)
            else:
                effective_score = max(token_score, partial_score)

            if effective_score > best_score and effective_score >= 60.0:
                best_score = effective_score
                best_ep = ep

        if best_ep and best_score >= 60.0:
            return best_ep

        # 3. Сезонный спешл/рекап (Season 1 SP, S11E00, S11 Special, [1] ... [sp], Season 2 SP, 2 sp)
        if "[1]" in path_lower and "sp" in path_lower:
            recaps_s1 = [e for e in specials if "2" not in (getattr(e, "title", None) or "")]
            if recaps_s1:
                return recaps_s1[0]

        # Распознавание SxxE00 / SxxE0 (например S11E00)
        m_s_e00 = re.search(r"\bs(\d{1,2})e0{1,2}\b", path_lower)
        if m_s_e00:
            s_num = int(m_s_e00.group(1))
            # Ищем спешл, относящийся к этому сезону
            s_cand = [
                e for e in specials
                if f"season {s_num}" in (getattr(e, "title", None) or "").lower()
                or f"s{s_num}" in (getattr(e, "title", None) or "").lower()
                or f"сезон {s_num}" in (getattr(e, "title", None) or "").lower()
            ]
            if s_cand:
                return s_cand[0]
            # Если среди спешлов есть серия с номером 0
            ep0 = next((e for e in specials if getattr(e, "episode_number", None) == 0), None)
            if ep0:
                return ep0

        m_s_sp = re.search(r"(?:\[|\()?\s*(?:season|сезон|s)?\s*(\d{1,2})\s*(?:\]|\))?[\s._–-]+(?:sp|special|спешл)\b|\b(\d{1,2})\s*[-_.\s]+(?:sp|special|спешл)\b", path_lower)
        if m_s_sp:
            groups = [g for g in m_s_sp.groups() if g is not None]
            if groups:
                s_num = int(groups[0])
                if s_num == 1 and specials:
                    return specials[0]
                elif s_num == 2 and len(specials) >= 7:
                    s2_cand = [e for e in specials if getattr(e, "episode_number", 0) in [7, 8]]
                    if s2_cand:
                        return s2_cand[0]

        # 4. OVA 1..N сопоставление
        m_ova = re.search(r"(?:ova|ona|oad)[-_.\s]?(\d{1,2})", path_lower)
        if m_ova:
            ova_num = int(m_ova.group(1))
            ova_candidates = [
                e for e in specials
                if getattr(e, "episode_number", 0) in range(2, 7) or "ova" in (getattr(e, "title", None) or "").lower() or "extra" in (getattr(e, "title", None) or "").lower()
            ]
            if len(ova_candidates) >= ova_num:
                return ova_candidates[ova_num - 1]
            elif len(specials) >= ova_num:
                return specials[ova_num - 1]

        # 5. Прямой номер SP 01 / S00E01
        m_sp = re.search(r"(?:sp|s00e|00x)[\s._–-]*(\d{1,3})", path_lower)
        if m_sp:
            sp_num = int(m_sp.group(1))
            matched = next((e for e in specials if getattr(e, "episode_number", None) == sp_num), None)
            if matched:
                return matched

        # 6. Если передан parsed_ep с season=0 и номером серии
        if parsed_ep and (parsed_ep.season == 0 or (parsed_ep.episodes and parsed_ep.episodes[0] == 0)) and parsed_ep.episodes:
            target_num = parsed_ep.episodes[0]
            matched = next((e for e in specials if getattr(e, "episode_number", None) == target_num), None)
            if matched:
                return matched
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("match_special_episode error: %s", exc)

    return None


def resolve_part_offset(
    part_num: Optional[int],
    total_in_part: Optional[int],
    parsed_episodes: list[int],
    all_season_episodes: Optional[list] = None,
    wanted_season_episodes: Optional[list] = None,
) -> int:
    """
    Вычисляет смещение номеров серий (offset) для раздельных куров/частей сезона (Split-Cour / Part 2 / Part 3).
    Например, для Re:Zero S02 Part 2 [12 из 12] при 25 сериях в сезоне смещение = 13 (серии 14..25).
    """
    if not part_num or part_num < 2 or not parsed_episodes:
        return 0

    # Если номера серий уже сквозные для сезона (например, [14..25]), смещение не требуется
    if min(parsed_episodes) > 12:
        return 0

    sorted_all = sorted(all_season_episodes, key=lambda e: getattr(e, "episode_number", 0)) if all_season_episodes else []
    total_season_eps = len(sorted_all)

    # 1. Поиск разрыва в датах выхода (air_date gap > 45 дней) между частями сплит-кура
    if sorted_all:
        gaps = []
        for i in range(len(sorted_all) - 1):
            e1, e2 = sorted_all[i], sorted_all[i + 1]
            ad1 = getattr(e1, "air_date", None)
            ad2 = getattr(e2, "air_date", None)
            if ad1 and ad2:
                try:
                    days = (ad2 - ad1).days
                    if days > 45:
                        gaps.append(getattr(e1, "episode_number", 0))
                except Exception:
                    pass

        if part_num == 2 and len(gaps) >= 1 and gaps[0] > 0:
            return gaps[0]
        elif part_num == 3 and len(gaps) >= 2 and gaps[1] > 0:
            return gaps[1]

    # 2. Вычисление по общему количеству серий сезона и размеру части (total_season_eps - total_in_part)
    if total_in_part and total_season_eps and total_season_eps > total_in_part:
        if part_num == 2:
            offset = total_season_eps - total_in_part
            if offset > 0:
                return offset

    # 3. Проверка стартового номера разыскиваемых серий (если 1-я часть уже скачана)
    if wanted_season_episodes:
        wanted_nums = [getattr(e, "episode_number", 0) for e in wanted_season_episodes if getattr(e, "episode_number", 0) > 0]
        if wanted_nums:
            min_wanted = min(wanted_nums)
            if min_wanted > 1 and (min_wanted - 1) in range(10, 30):
                return min_wanted - 1

    # 4. Стандартный размер аниме-кура (12-13 серий)
    if total_season_eps >= 22:
        cour_len = total_season_eps // 2
        return cour_len * (part_num - 1)

    return 0


_ROMAN_TO_ARABIC = {
    "i": "1", "ii": "2", "iii": "3", "iv": "4", "v": "5",
    "vi": "6", "vii": "7", "viii": "8", "ix": "9", "x": "10",
}


def normalize_title_words(text: Optional[str]) -> list[str]:
    """
    Нормализует строку заголовка серии/файла в список значимых слов:
    - переводит в нижний регистр
    - заменяет римские цифры на арабские (I..X -> 1..10)
    - фильтрует стоп-слова (the, a, an, of, in, on, and, or, to, for, vs, part)
    """
    if not text or len(text.strip()) < 2:
        return []
    raw = re.sub(r"[^\w\s]", " ", text.lower()).split()
    clean = []
    for raw_w in raw:
        w = _ROMAN_TO_ARABIC.get(raw_w, raw_w)
        if (len(w) > 1 or w.isdigit()) and w not in {
            "the", "a", "an", "of", "in", "on", "and", "or", "to", "for", "vs", "part"
        }:
            clean.append(w)
    return clean


def calc_title_match(ep_title: Optional[str], fname_words: set[str]) -> tuple[float, int]:
    """
    Вычисляет долю совпадения слов названия эпизода в множестве слов имени файла.
    Возвращает (score, matched_words_count).
    """
    words = normalize_title_words(ep_title)
    if not words:
        return (0.0, 0)
    matched = sum(1 for w in words if w in fname_words)
    return (matched / len(words), matched)


