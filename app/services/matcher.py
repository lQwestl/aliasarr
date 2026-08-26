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
    r"\b(?:rus|eng|jap|jpn|ukr|ger|fra|spa)?\s*(?:sound|audio|soundtracks?|ost|audio[-\s]?tracks?|чистый\s*звук|звуковые\s*дорожки|аудиодорожк[иа]|звуковые\s*файлы|sound\s*pack|audio\s*pack|только\s*звук|только\s*аудио|озвучка\s*отдельно)\b|"
    r"\[(?:audio|sound|soundtrack|ost|audio[-\s]?tracks?|звук|аудиодорожки|озвучка\s*отдельно)\]|"
    r"\((?:audio|sound|soundtrack|ost|audio[-\s]?tracks?|звук|аудиодорожки|озвучка\s*отдельно)\)|"
    r"\b(?:rus|eng|jap|jpn|ukr)?\s*(?:subs?\s*only|только\s*субтитры|только\s*сабы|subtitles?\s*pack|пак\s*субтитров)\b|"
    r"\[(?:subs\s*only|субтитры|сабы|пак\s*субтитров)\]|"
    r"\((?:subs\s*only|субтитры|сабы|пак\s*субтитров)\)|"
    r"додзинси|doujin|"
    r"комикс(?:ы)?|comic(?!s? *tv)|"
    r"\bscans?\b|\bсканы\b|"
    r"\[flac\]|\[mp3\]|\[lossless\]|\bflac\s+pack\b|\bmp3\s+pack\b|"
    r"\.cbz\b|\.cbr\b|\.pdf\b|\.epub\b|\.fb2\b|\.djvu\b|"
    # Игры, консоли, платформы, ROM, образы дисков, репаки и софт:
    r"\b(?:nintendo(?:\s*(?:wii(?:\s*u)?|switch|nsw|3ds|nds|ds|gba|gbc|gamecube|ngc|n64|snes|nes|virtual\s*boy))?)\b|"
    r"\[(?:nintendo(?:\s*wii)?|wii|wii-u|wiiu|switch|nsw|3ds|nds|gba|gbc|gamecube|ngc|n64|snes|nes|ps[1-5]|psx|psp|ps\s*vita|psvita|xbox|xbox360|xbox\s*360|xbox\s*one|xbox\s*series|x360|xone|pc|mac|linux|android|ios|win/mac)\]|"
    r"\((?:nintendo(?:\s*wii)?|wii|wii-u|wiiu|switch|nsw|3ds|nds|gba|gbc|gamecube|ngc|n64|snes|nes|ps[1-5]|psx|psp|ps\s*vita|psvita|xbox|xbox360|xbox\s*360|xbox\s*one|xbox\s*series|x360|xone|win/mac)\)|"
    r"\b(?:wii|wii-u|wiiu|gamecube|ngc|n64|gba|nds|3ds|snes|nes)\b|"
    r"\[[^\]]*\b(?:ntsc|pal|ntsc-u|ntsc-j|pal-e|pal/eng|ntsc/eng|ntsc/rus|pal/rus|region\s*free)\b[^\]]*\]|"
    r"\([^)]*\b(?:ntsc|pal|ntsc-u|ntsc-j|pal-e|pal/eng|ntsc/eng|ntsc/rus|pal/rus|region\s*free)\b[^)]*\)|"
    r"\b(?:playstation(?:\s*[1-5]|\s*portable|\s*vita)?|ps[1-5]|psx|psp|ps\s*vita|psvita)\b(?=.*(?:\[|\b(?:game|iso|rom|pkg|ntsc|pal|cusa\d+|usa|eur|jpn)\b))|"
    r"\b(?:xbox(?:\s*360|\s*one|\s*series\s*[xs])?|x360|xone)\b(?=.*(?:\[|\b(?:game|iso|rom|jtag|rgh|god|xex|pal|ntsc)\b))|"
    r"\b(?:pc\s*games?|pc\s*iso|pc\s*rip|mac\s*games?|linux\s*games?|android\s*games?|ios\s*games?)\b|"
    r"\b(?:steam[-_\s]?rip|gog\s*rip|gog\s*edition|full\s*game|game\s*rip)\b|"
    r"\b(?:nsp|xci|cia|vpk|wbfs|gcm|nkit|rvz|chd|pbp|xex|god|cso)\b|"
    r"\[(?:iso|cso|wbfs|nsp|xci|cia|vpk|gcm|nkit|rvz|chd|pbp|xex|god|rom|bin|cue|nds|3ds|gba|nes|sfc|smc|wad|pkg|prototype|beta|alpha|devbuild|debug|trainer|cheat|homebrew|rom\s*hack|crack|keygen|patch|activator)\]|"
    r"\((?:iso|cso|wbfs|nsp|xci|cia|vpk|gcm|nkit|rvz|chd|pbp|xex|god|rom|bin|cue|nds|3ds|gba|nes|sfc|smc|wad|pkg|prototype|beta|alpha|devbuild|debug|trainer|cheat|homebrew|rom\s*hack|crack|keygen|patch|activator)\)|"
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


def build_alias_candidates(show) -> list[AliasCandidate]:
    """
    Формирует список кандидатов для поиска и сопоставления.
    Включает основное название тайтла и все пользовательские/автоматические алиасы.
    Список отсортирован по приоритету: меньшее число = опрашивается раньше.
    """
    seen_normalized: set[str] = set()
    candidates: list[AliasCandidate] = []

    title_norm = normalize_title(show.title)
    if title_norm:
        seen_normalized.add(title_norm)
        candidates.append(AliasCandidate(alias_id=0, text=show.title, language="en", priority=0))

    for alias in show.aliases:
        norm = normalize_title(alias.text)
        if not norm or norm in seen_normalized:
            continue
        lang_str = alias.language.value if hasattr(alias.language, "value") else (str(alias.language) if alias.language else "ru")
        candidates.append(AliasCandidate(
            alias_id=alias.id, text=alias.text, language=lang_str,
            priority=getattr(alias, "priority", 100) or 100,
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
        |   [._\s]\b(?:S\d{1,3}(?:[-_.\s]*E\d{1,3})?|E\d{1,3}|EP\d{1,3}|Seasons?[-_.:\s]*\d|Сез(?:он(?:ы|а)?)?[-_.:\s]*\d)\b
        |   \b(?:\d{1,3}(?:\s*[-–~]\s*\d{1,3})?\s*(?:сезон(?:ы|а)?|seasons?))\b
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


def match_release(
    release_name: str,
    show_id: int,
    aliases: Iterable[AliasCandidate],
    threshold: int = DEFAULT_FUZZY_THRESHOLD,
    content_type: str = "series",
    categories: Optional[list[int]] = None,
) -> MatchResult:
    """Полный матчинг релиза: алиас (fuzzy) + парсинг номера серии + проверка типа контента."""
    alias, score = best_alias_match(release_name, aliases, threshold)
    parsed = parse_episode(release_name)

    # Отсеиваем не-видео релизы (игры, консоли, ROM, софт, манга, артбуки, OST/саундтреки)
    if is_non_video_release(release_name, categories=categories):
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

        # 2. Нечеткое сопоставление по полному названию серии
        best_ep = None
        best_score = 0.0
        for ep in specials:
            title = (getattr(ep, "title", None) or "").strip().lower()
            if not title:
                continue
            # Проверяем вхождение значимых слов названия
            words = [w for w in re.split(r"[\s:;,\-\.\?!\(\)]+", title) if len(w) > 3]
            if words and all(w in path_lower for w in words[:2]):
                score = fuzz.token_set_ratio(title, path_lower)
                if score > best_score and score >= 60:
                    best_score = score
                    best_ep = ep

        if best_ep and best_score >= 65:
            return best_ep

        # 3. Сезонный спешл/рекап (Season 1 SP, [1] ... [sp], Season 2 SP, 2 sp)
        if "[1]" in path_lower and "sp" in path_lower:
            recaps_s1 = [e for e in specials if "2" not in (getattr(e, "title", None) or "")]
            if recaps_s1:
                return recaps_s1[0]

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
        if parsed_ep and parsed_ep.season == 0 and parsed_ep.episodes:
            target_num = parsed_ep.episodes[0]
            matched = next((e for e in specials if getattr(e, "episode_number", None) == target_num), None)
            if matched:
                return matched
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("match_special_episode error: %s", exc)

    return None

