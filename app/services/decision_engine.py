"""
Движок принятия решений (Decision Engine) на основе архитектуры Sonarr DecisionEngine.
Отвечает за оценку каждого релиза по набору спецификаций:
- Качество разрешено в профиле (QualityAllowedSpecification)
- Размер укладывается в допустимые лимиты (AcceptableSizeSpecification)
- Достаточное количество сидов (SeedersSpecification)
- Правила апгрейда качества и очков кастомных форматов (UpgradableSpecification)
- Достижение порогов Cutoff (CutoffSpecification)
- Протокол и блокировки (ProtocolSpecification, ReleaseRestrictionsSpecification)
"""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
import re
from typing import Any, List, Optional

logger = logging.getLogger("aliasarr.decision_engine")

try:
    from sqlalchemy.orm import Session
    from app.models.db import AppSettings, Episode, EpisodeStatus, QualityProfile, Show
except (ImportError, Exception):
    Session = Any  # type: ignore
    AppSettings = Any  # type: ignore
    Episode = Any  # type: ignore
    class EpisodeStatus:  # type: ignore
        DOWNLOADED = "downloaded"
        WANTED = "wanted"
        DOWNLOADING = "downloading"
    QualityProfile = Any  # type: ignore
    Show = Any  # type: ignore
from app.services.custom_formats import MatchedCustomFormat, calculate_custom_formats_for_release
from app.services.language_parser import Language, get_language_badges, parse_languages
from app.services.quality import QualityInfo, is_allowed, parse_quality, size_limit_rejection, upgrade_rejection
from app.services.release_group_parser import parse_release_group


@dataclass
class DecisionResult:
    approved: bool
    rejections: List[str] = field(default_factory=list)
    quality: QualityInfo = field(default_factory=lambda: QualityInfo(name="SDTV", rank=0))
    languages: List[Language] = field(default_factory=list)
    language_badges: List[str] = field(default_factory=list)
    release_group: Optional[str] = None
    custom_formats: List[MatchedCustomFormat] = field(default_factory=list)
    custom_format_score: int = 0

    def to_dict(self) -> dict:
        return {
            "approved": self.approved,
            "rejections": self.rejections,
            "quality": self.quality.name,
            "quality_rank": self.quality.rank,
            "quality_details": self.quality.to_dict(),
            "languages": [l.value for l in self.languages],
            "language_badges": self.language_badges,
            "release_group": self.release_group,
            "custom_formats": [
                {"id": cf.id, "name": cf.name, "score": cf.score}
                for cf in self.custom_formats
            ],
            "custom_format_score": self.custom_format_score,
        }


class DecisionEngine:
    @staticmethod
    def evaluate_release(
        db: Session,
        title: str,
        show: Optional[Show] = None,
        episodes: Optional[List[Episode]] = None,
        size_bytes: int = 0,
        seeders: int = 0,
        settings: Optional[AppSettings] = None,
        quality_profile: Optional[QualityProfile] = None,
        categories: Optional[List[int]] = None,
        torrent_hash: Optional[str] = None,
        guid: Optional[str] = None,
        download_url: Optional[str] = None,
        precomputed_match: Optional[Any] = None,
    ) -> DecisionResult:
        """
        Полная оценка релиза по всем спецификациям Decision Engine.
        """
        rejections: List[str] = []

        # 0. Проверка на не-видео контент (игры, консоли, ROM, софт, музыка, манга, артбуки)
        from app.services.matcher import is_non_video_release, build_alias_candidates, match_release
        if is_non_video_release(title, categories=categories):
            rejections.append("Релиз не является видео-контентом (игры/консоли/ROM/софт/музыка/книги)")

        # 0.1. Проверка блокировок (ReleaseRestrictionsSpecification / Blocklist)
        from app.services.blocklist_service import is_release_blocked, extract_infohash
        eff_hash = extract_infohash(torrent_hash) or extract_infohash(guid) or extract_infohash(download_url)
        is_blocked, block_reason = is_release_blocked(
            db=db,
            show=show,
            title=title,
            torrent_hash=eff_hash,
            guid=guid,
            download_url=download_url,
        )
        if is_blocked:
            rejections.append(f"Релиз находится в черном списке: {block_reason}")

        # 1. Извлечение метаданных
        quality = parse_quality(title)
        languages = parse_languages(title)
        lang_badges = get_language_badges(languages)
        release_group = parse_release_group(title)

        # 2. Получение профиля качества
        if quality_profile is None and show and show.quality_profile_id:
            quality_profile = db.get(QualityProfile, show.quality_profile_id)

        # 3. Вычисление очков кастомных форматов
        cf_score, matched_cfs = calculate_custom_formats_for_release(
            db=db,
            title=title,
            quality=quality,
            languages=languages,
            release_group=release_group,
            size_bytes=size_bytes,
            quality_profile=quality_profile,
        )

        # 4. Проверка соответствия шоу и сезона/серий (Title & SeasonSpecification)
        if show:
            if precomputed_match is not None:
                match = precomputed_match
            else:
                aliases = build_alias_candidates(show, db=db)
                match = match_release(
                    title,
                    show.id,
                    aliases,
                    content_type=show.content_type,
                    categories=categories,
                    show_year=getattr(show, "year", None),
                )
            if not match.matched:
                rejections.append(f"Название релиза не соответствует тайтлу «{show.title}»")

            from app.services.parser import detect_season_label, ReleaseKind
            s_lbl = detect_season_label(title)

            if show.content_type in ("series", "anime"):
                # Обработка OVA согласно настройке тайтла ova_mode (auto | season_1 | specials)
                ova_mode = getattr(show, "ova_mode", "auto") or "auto"
                is_ova_release = (
                    s_lbl.get("type") == "ova_ona"
                    or (match.parsed.matched_pattern and "ova" in match.parsed.matched_pattern.lower())
                    or re.search(r"\[ova(?:[-_ ]?\d+)?\]|\bova\b", title, re.IGNORECASE) is not None
                )

                remap_to_season_1 = False
                if is_ova_release and ova_mode != "specials":
                    if ova_mode == "season_1":
                        remap_to_season_1 = True
                    elif ova_mode == "auto":
                        show_all_eps = getattr(show, "episodes", []) or []
                        s0_count = sum(1 for e in show_all_eps if getattr(e, "season_number", None) == 0)
                        s1_count = sum(1 for e in show_all_eps if getattr(e, "season_number", None) == 1)
                        if match.parsed.episodes:
                            max_ep = max(match.parsed.episodes)
                            if max_ep > s0_count and max_ep <= s1_count:
                                remap_to_season_1 = True
                            elif episodes and 0 not in {getattr(e, "season_number", None) for e in episodes} and 1 in {getattr(e, "season_number", None) for e in episodes}:
                                remap_to_season_1 = True
                        elif match.parsed.kind == ReleaseKind.SEASON_PACK and s0_count <= 1 and s1_count >= 2:
                            remap_to_season_1 = True

                if remap_to_season_1:
                    match.parsed.season = 1
                    s_lbl["season"] = 1
                    if s_lbl.get("type") == "ova_ona":
                        s_lbl["type"] = "numbered"

                if match.parsed.kind == ReleaseKind.UNKNOWN and s_lbl["type"] == "none":
                    rejections.append("Релиз не содержит информации о сезоне или сериях сериала")

                daily_date = getattr(match.parsed, "air_date", None)
                if daily_date and episodes:
                    def _iso(value):
                        if value is None:
                            return None
                        if hasattr(value, "date") and callable(value.date):
                            value = value.date()
                        return value.isoformat() if hasattr(value, "isoformat") else str(value)[:10]

                    if not any(_iso(getattr(ep, "air_date", None)) == daily_date for ep in episodes):
                        rejections.append(f"Выпуск от {daily_date} не относится к разыскиваемым сериям")

                if episodes:
                    target_seasons = {ep.season_number for ep in episodes}
                    target_ep_keys = {(ep.season_number, ep.episode_number) for ep in episodes}
                    target_abs = {ep.absolute_number for ep in episodes if ep.absolute_number is not None}
                    lbl_type = s_lbl["type"]
                    has_wanted_specials = (0 in target_seasons)
                    specials_in_target = [ep for ep in episodes if ep.season_number == 0] if has_wanted_specials else []

                    # Извлечение параметров области действия сматченного алиаса (Scoped Aliases)
                    alias_cand = getattr(match, "alias_candidate", None)
                    scoped_season = alias_cand.season_number if (alias_cand and alias_cand.season_number is not None) else None
                    alias_offset = (alias_cand.episode_offset or 0) if alias_cand else 0
                    alias_start = alias_cand.episode_start if (alias_cand and alias_cand.episode_start is not None) else None
                    alias_end = alias_cand.episode_end if (alias_cand and alias_cand.episode_end is not None) else None

                    # Проверка спецвыпуска по названию, арке или SxxE00
                    matched_sp_for_release = None
                    if has_wanted_specials and specials_in_target and not match.parsed.has_specials:
                        from app.services.matcher import match_special_episode
                        matched_sp_for_release = match_special_episode(title, specials_in_target, match.parsed)

                    if matched_sp_for_release:
                        # Релиз сопоставлен с разыскиваемым спецвыпуском Season 0
                        pass
                    elif match.parsed.has_specials:
                        # Комбинированный релиз TV + Special (покрывает TV сезон и Season 0)
                        rel_s = scoped_season if scoped_season is not None else (match.parsed.season if match.parsed.season is not None else 1)
                        covered_seasons = {rel_s, 0}
                        if not (covered_seasons & target_seasons):
                            min_tgt = min(target_seasons) if target_seasons else 0
                            rejections.append(f"Релиз относится к сезону S{rel_s:02d}+SP, а разыскивается S{min_tgt:02d}")
                        else:
                            has_matching_tv = any(
                                (rel_s, ep_n) in target_ep_keys
                                or (rel_s, ep_n + alias_offset) in target_ep_keys
                                or ep_n in target_abs
                                or (ep_n + alias_offset) in target_abs
                                for ep_n in match.parsed.episodes
                            ) if match.parsed.episodes else (rel_s in target_seasons)
                            has_matching_sp = any(
                                (0, ep_n) in target_ep_keys
                                for ep_n in match.parsed.special_episodes
                            ) if match.parsed.special_episodes else has_wanted_specials

                            if not (has_matching_tv or has_matching_sp):
                                eps_str = ", ".join(str(e) for e in match.parsed.episodes[:3])
                                rejections.append(f"Релиз содержит серии ({eps_str}) и спешлы, которые не выбраны для скачивания")
                    else:
                        # Проверка диапазона сезонов пака
                        if scoped_season is not None:
                            rel_s = scoped_season
                            parsed_s = match.parsed.season if match.parsed.season is not None else (s_lbl["season"] if lbl_type == "numbered" else None)
                            if alias_offset == 0 and parsed_s is not None and parsed_s != scoped_season and lbl_type not in ("range", "complete"):
                                rejections.append(f"Релиз относится к сезону S{parsed_s:02d}, а алиас «{getattr(alias_cand, 'text', '')}» относится к S{scoped_season:02d} без смещения")
                            elif rel_s not in target_seasons:
                                min_tgt = min(target_seasons) if target_seasons else 0
                                rejections.append(f"Релиз относится к сезону S{rel_s:02d} (по алиасу), а разыскивается S{min_tgt:02d}")
                        elif lbl_type == "range":
                            rel_seasons = set(s_lbl.get("seasons", []))
                            if not (rel_seasons & target_seasons):
                                min_rel = min(rel_seasons) if rel_seasons else 0
                                max_rel = max(rel_seasons) if rel_seasons else 0
                                min_tgt = min(target_seasons) if target_seasons else 0
                                rejections.append(f"Пак сезонов (S{min_rel:02d}-S{max_rel:02d}) не содержит разыскиваемый сезон S{min_tgt:02d}")
                        elif match.parsed.seasons and len(match.parsed.seasons) > 1:
                            rel_seasons = set(match.parsed.seasons)
                            if not (rel_seasons & target_seasons):
                                min_rel = min(rel_seasons) if rel_seasons else 0
                                max_rel = max(rel_seasons) if rel_seasons else 0
                                min_tgt = min(target_seasons) if target_seasons else 0
                                rejections.append(f"Пак сезонов (S{min_rel:02d}-S{max_rel:02d}) не содержит разыскиваемый сезон S{min_tgt:02d}")
                        elif lbl_type == "numbered":
                            rel_s = s_lbl["season"]
                            if rel_s not in target_seasons:
                                min_tgt = min(target_seasons) if target_seasons else 0
                                rejections.append(f"Релиз относится к сезону S{rel_s:02d}, а разыскивается S{min_tgt:02d}")
                        elif match.parsed.season is not None:
                            rel_s = match.parsed.season
                            if rel_s not in target_seasons:
                                min_tgt = min(target_seasons) if target_seasons else 0
                                rejections.append(f"Релиз относится к сезону S{rel_s:02d}, а разыскивается S{min_tgt:02d}")

                        # Проверка конкретных серий
                        if match.parsed.episodes and match.parsed.kind not in (ReleaseKind.SEASON_PACK, ReleaseKind.UNKNOWN):
                            rel_s = scoped_season if scoped_season is not None else (match.parsed.season if match.parsed.season is not None else (min(target_seasons) if target_seasons else 1))

                            # Расчёт смещения для multi-part / split-cour релизов (Part 2, Cour 2, часть 2)
                            effective_offset = alias_offset
                            if effective_offset == 0 and match.parsed.part and match.parsed.part >= 2 and show and getattr(show, "episodes", None):
                                all_season_eps = [e for e in show.episodes if getattr(e, "season_number", None) == rel_s]
                                wanted_season_eps = [e for e in episodes if getattr(e, "season_number", None) == rel_s] if episodes else []
                                from app.services.matcher import resolve_part_offset
                                effective_offset = resolve_part_offset(
                                    match.parsed.part,
                                    match.parsed.total_in_part,
                                    match.parsed.episodes,
                                    all_season_eps,
                                    wanted_season_eps,
                                    )

                            def _ep_in_scope(ep_n):
                                eff_n = ep_n + effective_offset
                                if alias_start is not None and eff_n < alias_start:
                                    return False
                                if alias_end is not None and eff_n > alias_end:
                                    return False
                                return True

                            has_matching_ep = any(
                                _ep_in_scope(ep_n) and (
                                    (rel_s, ep_n) in target_ep_keys
                                    or (rel_s, ep_n + effective_offset) in target_ep_keys
                                    or ep_n in target_abs
                                    or (ep_n + effective_offset) in target_abs
                                )
                                for ep_n in match.parsed.episodes
                            )
                            if not has_matching_ep:
                                eps_str = ", ".join(str(e) for e in match.parsed.episodes[:3])
                                rejections.append(f"Релиз содержит серии ({eps_str}), которые не выбраны для скачивания")
                        elif (match.parsed.kind == ReleaseKind.SEASON_PACK or not match.parsed.episodes) and (alias_start is not None or alias_end is not None):
                            rel_s = scoped_season if scoped_season is not None else (match.parsed.season if match.parsed.season is not None else (min(target_seasons) if target_seasons else 1))
                            has_matching_in_range = any(
                                ep.season_number == rel_s
                                and (alias_start is None or ep.episode_number >= alias_start)
                                and (alias_end is None or ep.episode_number <= alias_end)
                                for ep in episodes
                            )
                            if not has_matching_in_range:
                                rejections.append(f"Релиз покрывает диапазон серий {alias_start or 1}-{alias_end or '...'}, который не содержит разыскиваемых серий")

        # 5. Проверка качества в профиле (QualityAllowedSpecification)
        from app.services.parser import parse_episode as _parse_episode
        parsed_for_size = _parse_episode(title)
        if quality_profile:
            if not is_allowed(quality, quality_profile.allowed_qualities):
                rejections.append(f"Качество «{quality.name}» не разрешено в профиле «{quality_profile.name}»")

            # 5.1. Проверка Regex шаблона названия (ReleaseTitleRegexSpecification)
            regex_val = getattr(quality_profile, "release_title_regex", None)
            if isinstance(regex_val, str) and regex_val.strip():
                pat = regex_val.strip()
                try:
                    if not re.search(pat, title, re.IGNORECASE):
                        rejections.append(f"Название не соответствует фильтру Regex профиля «{quality_profile.name}» (шаблон: {pat})")
                except Exception as ex:
                    logger.warning("Ошибка проверки Regex '%s' профиля '%s': %s", pat, quality_profile.name, ex)
                    rejections.append(f"Ошибка проверки Regex профиля качества: {ex}")

            # 6. Проверка размера файла (AcceptableSizeSpecification) — на серию, как в автопоиске
            if show and show.content_type == "movie":
                release_episode_count = 1
            else:
                release_episode_count = len(parsed_for_size.episodes) if parsed_for_size.episodes else (len(episodes) if episodes else 1)
            size_reason = size_limit_rejection(size_bytes, quality_profile, release_episode_count)
            if size_reason:
                rejections.append(size_reason)

        # 7. Проверка сидов (SeedersSpecification)
        min_seeds = getattr(settings, "min_seeds", 0) if settings else 0
        if min_seeds > 0 and seeders < min_seeds:
            rejections.append(f"Количество сидов ({seeders}) меньше требуемого минимума ({min_seeds})")

        # 8. Проверка правил апгрейда (UpgradableSpecification / CutoffSpecification)
        if episodes:
            downloaded_episodes = [
                ep for ep in episodes
                if str(getattr(ep, "status", "")).lower() == "downloaded"
                or getattr(ep, "file_path", None)
            ]
            if downloaded_episodes:
                upgrade_allowed = quality_profile.upgrade_allowed if quality_profile else True
                if not upgrade_allowed:
                    rejections.append("Эпизод уже скачан, автоматический апгрейд качества выключен")
                else:
                    for ep in downloaded_episodes:
                        reason = upgrade_rejection(
                            parse_quality(ep.downloaded_quality or "SDTV"),
                            quality,
                            current_score=getattr(ep, "imported_cf_score", None),
                            candidate_score=cf_score,
                            cutoff_quality=quality_profile.cutoff_quality if quality_profile else None,
                            cutoff_score=(quality_profile.cutoff_score if quality_profile else 0) or 0,
                        )
                        if reason:
                            rejections.append(reason)
                            break

        approved = len(rejections) == 0

        return DecisionResult(
            approved=approved,
            rejections=rejections,
            quality=quality,
            languages=languages,
            language_badges=lang_badges,
            release_group=release_group,
            custom_formats=matched_cfs,
            custom_format_score=cf_score,
        )
