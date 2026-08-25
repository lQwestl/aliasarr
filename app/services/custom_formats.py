"""
Сервис вычисления кастомных форматов и скоринга релизов (Sonarr Custom Formats).
Позволяет пользователю задавать тонкие правила ранжирования (HDR10+, Dolby Vision, FLAC, Preferred Groups, Repacks и т.д.).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, List, Optional

try:
    from sqlalchemy.orm import Session
    from app.models.db import CustomFormat, QualityProfile
except ImportError:
    Session = Any  # type: ignore
    CustomFormat = Any  # type: ignore
    QualityProfile = Any  # type: ignore

from app.services.language_parser import Language, parse_languages
from app.services.quality import QualityInfo, parse_quality
from app.services.release_group_parser import parse_release_group


@dataclass
class MatchedCustomFormat:
    id: int
    name: str
    score: int
    include_custom_format_when_renaming: bool = False


# Стандартные преднастроенные кастомные форматы (Sonarr v4/v5 default formats & Qualities)
DEFAULT_CUSTOM_FORMATS = [
    {
        "name": "Remux-2160p",
        "score": 110,
        "include_custom_format_when_renaming": False,
        "specifications": [
            {
                "name": "Remux-2160p Pattern",
                "implementation": "ReleaseTitleSpecification",
                "negate": False,
                "required": True,
                "fields": {"value": r"\b(remux[._\-\s]?(?:2160p|4k|uhd)|(?:2160p|4k|uhd)[._\-\s]?remux|uhd[-_. ]?remux|bdremux[._\-\s]?(?:2160p|4k|uhd))\b"},
            }
        ],
    },
    {
        "name": "Bluray-2160p",
        "score": 100,
        "include_custom_format_when_renaming": False,
        "specifications": [
            {
                "name": "Bluray-2160p Pattern",
                "implementation": "ReleaseTitleSpecification",
                "negate": False,
                "required": True,
                "fields": {"value": r"\b(bluray[._\-\s]?(?:2160p|4k|uhd)|(?:2160p|4k|uhd)[._\-\s]?bluray|blu-ray[._\-\s]?(?:2160p|4k|uhd)|uhd[-_. ]?bluray|bdrip[._\-\s]?(?:2160p|4k|uhd)|brrip[._\-\s]?(?:2160p|4k|uhd))\b"},
            }
        ],
    },
    {
        "name": "WEBDL-2160p",
        "score": 95,
        "include_custom_format_when_renaming": False,
        "specifications": [
            {
                "name": "WEBDL-2160p Pattern",
                "implementation": "ReleaseTitleSpecification",
                "negate": False,
                "required": True,
                "fields": {"value": r"\b(web[-_. ]?dl[._\-\s]?(?:2160p|4k|uhd)|(?:2160p|4k|uhd)[._\-\s]?web[-_. ]?dl|webhd[._\-\s]?(?:2160p|4k|uhd))\b"},
            }
        ],
    },
    {
        "name": "WEBRip-2160p",
        "score": 90,
        "include_custom_format_when_renaming": False,
        "specifications": [
            {
                "name": "WEBRip-2160p Pattern",
                "implementation": "ReleaseTitleSpecification",
                "negate": False,
                "required": True,
                "fields": {"value": r"\b(webrip[._\-\s]?(?:2160p|4k|uhd)|(?:2160p|4k|uhd)[._\-\s]?webrip|web-rip[._\-\s]?(?:2160p|4k|uhd))\b"},
            }
        ],
    },
    {
        "name": "HDTV-2160p",
        "score": 85,
        "include_custom_format_when_renaming": False,
        "specifications": [
            {
                "name": "HDTV-2160p Pattern",
                "implementation": "ReleaseTitleSpecification",
                "negate": False,
                "required": True,
                "fields": {"value": r"\b(hdtv[._\-\s]?(?:2160p|4k|uhd)|(?:2160p|4k|uhd)[._\-\s]?hdtv)\b"},
            }
        ],
    },
    {
        "name": "Remux-1080p",
        "score": 80,
        "include_custom_format_when_renaming": False,
        "specifications": [
            {
                "name": "Remux-1080p Pattern",
                "implementation": "ReleaseTitleSpecification",
                "negate": False,
                "required": True,
                "fields": {"value": r"\b(remux[._\-\s]?(?:1080p)|1080p[._\-\s]?remux|bdremux[._\-\s]?1080p)\b"},
            }
        ],
    },
    {
        "name": "Bluray-1080p",
        "score": 70,
        "include_custom_format_when_renaming": False,
        "specifications": [
            {
                "name": "Bluray-1080p Pattern",
                "implementation": "ReleaseTitleSpecification",
                "negate": False,
                "required": True,
                "fields": {"value": r"\b(bluray[._\-\s]?(?:1080p)|1080p[._\-\s]?bluray|blu-ray[._\-\s]?1080p|bdrip[._\-\s]?1080p|brrip[._\-\s]?1080p)\b"},
            }
        ],
    },
    {
        "name": "WEBDL-1080p",
        "score": 60,
        "include_custom_format_when_renaming": False,
        "specifications": [
            {
                "name": "WEBDL-1080p Pattern",
                "implementation": "ReleaseTitleSpecification",
                "negate": False,
                "required": True,
                "fields": {"value": r"\b(web[-_. ]?dl[._\-\s]?(?:1080p)|1080p[._\-\s]?web[-_. ]?dl|webhd[._\-\s]?1080p)\b"},
            }
        ],
    },
    {
        "name": "WEBRip-1080p",
        "score": 55,
        "include_custom_format_when_renaming": False,
        "specifications": [
            {
                "name": "WEBRip-1080p Pattern",
                "implementation": "ReleaseTitleSpecification",
                "negate": False,
                "required": True,
                "fields": {"value": r"\b(webrip[._\-\s]?(?:1080p)|1080p[._\-\s]?webrip|web-rip[._\-\s]?1080p)\b"},
            }
        ],
    },
    {
        "name": "HDTV-1080p",
        "score": 50,
        "include_custom_format_when_renaming": False,
        "specifications": [
            {
                "name": "HDTV-1080p Pattern",
                "implementation": "ReleaseTitleSpecification",
                "negate": False,
                "required": True,
                "fields": {"value": r"\b(hdtv[._\-\s]?(?:1080p|1080i)|1080[pi][._\-\s]?hdtv)\b"},
            }
        ],
    },
    {
        "name": "Bluray-720p",
        "score": 45,
        "include_custom_format_when_renaming": False,
        "specifications": [
            {
                "name": "Bluray-720p Pattern",
                "implementation": "ReleaseTitleSpecification",
                "negate": False,
                "required": True,
                "fields": {"value": r"\b(bluray[._\-\s]?(?:720p)|720p[._\-\s]?bluray|blu-ray[._\-\s]?720p|bdrip[._\-\s]?720p|brrip[._\-\s]?720p)\b"},
            }
        ],
    },
    {
        "name": "WEBDL-720p",
        "score": 40,
        "include_custom_format_when_renaming": False,
        "specifications": [
            {
                "name": "WEBDL-720p Pattern",
                "implementation": "ReleaseTitleSpecification",
                "negate": False,
                "required": True,
                "fields": {"value": r"\b(web[-_. ]?dl[._\-\s]?(?:720p)|720p[._\-\s]?web[-_. ]?dl|webhd[._\-\s]?720p)\b"},
            }
        ],
    },
    {
        "name": "WEBRip-720p",
        "score": 35,
        "include_custom_format_when_renaming": False,
        "specifications": [
            {
                "name": "WEBRip-720p Pattern",
                "implementation": "ReleaseTitleSpecification",
                "negate": False,
                "required": True,
                "fields": {"value": r"\b(webrip[._\-\s]?(?:720p)|720p[._\-\s]?webrip|web-rip[._\-\s]?720p)\b"},
            }
        ],
    },
    {
        "name": "HDTV-720p",
        "score": 30,
        "include_custom_format_when_renaming": False,
        "specifications": [
            {
                "name": "HDTV-720p Pattern",
                "implementation": "ReleaseTitleSpecification",
                "negate": False,
                "required": True,
                "fields": {"value": r"\b(hdtv[._\-\s]?(?:720p)|720p[._\-\s]?hdtv)\b"},
            }
        ],
    },
    {
        "name": "Bluray-480p",
        "score": 28,
        "include_custom_format_when_renaming": False,
        "specifications": [
            {
                "name": "Bluray-480p Pattern",
                "implementation": "ReleaseTitleSpecification",
                "negate": False,
                "required": True,
                "fields": {"value": r"\b(bluray[._\-\s]?(?:480p|576p)|(?:480p|576p)[._\-\s]?bluray|blu-ray[._\-\s]?(?:480p|576p)|bdrip|brrip|bd[-_. ]?rip|br[-_. ]?rip)\b"},
            }
        ],
    },
    {
        "name": "WEBDL-480p",
        "score": 26,
        "include_custom_format_when_renaming": False,
        "specifications": [
            {
                "name": "WEBDL-480p Pattern",
                "implementation": "ReleaseTitleSpecification",
                "negate": False,
                "required": True,
                "fields": {"value": r"\b(web[-_. ]?dl[._\-\s]?(?:480p|576p)|(?:480p|576p)[._\-\s]?web[-_. ]?dl)\b"},
            }
        ],
    },
    {
        "name": "WEBRip-480p",
        "score": 24,
        "include_custom_format_when_renaming": False,
        "specifications": [
            {
                "name": "WEBRip-480p Pattern",
                "implementation": "ReleaseTitleSpecification",
                "negate": False,
                "required": True,
                "fields": {"value": r"\b(webrip[._\-\s]?(?:480p|576p)|(?:480p|576p)[._\-\s]?webrip)\b"},
            }
        ],
    },
    {
        "name": "HDTV-480p",
        "score": 22,
        "include_custom_format_when_renaming": False,
        "specifications": [
            {
                "name": "HDTV-480p Pattern",
                "implementation": "ReleaseTitleSpecification",
                "negate": False,
                "required": True,
                "fields": {"value": r"\b(hdtv[._\-\s]?(?:480p|576p)|(?:480p|576p)[._\-\s]?hdtv)\b"},
            }
        ],
    },
    {
        "name": "DVDRip-480p",
        "score": 20,
        "include_custom_format_when_renaming": False,
        "specifications": [
            {
                "name": "DVDRip Pattern",
                "implementation": "ReleaseTitleSpecification",
                "negate": False,
                "required": True,
                "fields": {"value": r"\b(dvdrip|dvd-rip)\b"},
            }
        ],
    },
    {
        "name": "DVD-480p",
        "score": 15,
        "include_custom_format_when_renaming": False,
        "specifications": [
            {
                "name": "DVD Pattern",
                "implementation": "ReleaseTitleSpecification",
                "negate": False,
                "required": True,
                "fields": {"value": r"\b(dvd|dvd9|dvd5|dvd-r|ntsc|pal|xvidvd)\b"},
            }
        ],
    },
    {
        "name": "TVRip-480p",
        "score": 12,
        "include_custom_format_when_renaming": False,
        "specifications": [
            {
                "name": "TVRip Pattern",
                "implementation": "ReleaseTitleSpecification",
                "negate": False,
                "required": True,
                "fields": {"value": r"\b(tvrip|satrip|dtvrip)\b"},
            }
        ],
    },
    {
        "name": "SDTV-480p",
        "score": 10,
        "include_custom_format_when_renaming": False,
        "specifications": [
            {
                "name": "SDTV Pattern",
                "implementation": "ReleaseTitleSpecification",
                "negate": False,
                "required": True,
                "fields": {"value": r"\b(sdtv|pdtv|dsr|360p)\b"},
            }
        ],
    },
    {
        "name": "Workprint-480p",
        "score": 4,
        "include_custom_format_when_renaming": False,
        "specifications": [
            {
                "name": "Workprint Pattern",
                "implementation": "ReleaseTitleSpecification",
                "negate": False,
                "required": True,
                "fields": {"value": r"\b(workprint|wp)\b"},
            }
        ],
    },
    {
        "name": "Telecine-480p",
        "score": 3,
        "include_custom_format_when_renaming": False,
        "specifications": [
            {
                "name": "Telecine Pattern",
                "implementation": "ReleaseTitleSpecification",
                "negate": False,
                "required": True,
                "fields": {"value": r"\b(telecine|tc|hdtc)\b"},
            }
        ],
    },
    {
        "name": "Telesync-480p",
        "score": 2,
        "include_custom_format_when_renaming": False,
        "specifications": [
            {
                "name": "Telesync Pattern",
                "implementation": "ReleaseTitleSpecification",
                "negate": False,
                "required": True,
                "fields": {"value": r"\b(telesync|hdts|hd-ts|tsrip|telesync-rip)\b"},
            }
        ],
    },
    {
        "name": "CAM-480p",
        "score": 1,
        "include_custom_format_when_renaming": False,
        "specifications": [
            {
                "name": "CAM Pattern",
                "implementation": "ReleaseTitleSpecification",
                "negate": False,
                "required": True,
                "fields": {"value": r"\b(camrip|cam|hdcam)\b"},
            }
        ],
    },
]


DEFAULT_FORMAT_BY_NAME = {item["name"]: item for item in DEFAULT_CUSTOM_FORMATS}
DEFAULT_FORMAT_NAMES = set(DEFAULT_FORMAT_BY_NAME.keys())


def seed_default_custom_formats(db: Session) -> None:
    """Создаёт базовые кастомные форматы в БД, если они ещё не созданы, и удаляет устаревшие."""
    REMOVED_FORMAT_NAMES = {
        "Dolby Vision",
        "HDR10+",
        "HDR10",
        "Lossless Audio (FLAC / TrueHD / Atmos / DTS-HD)",
        "Proper / Repack",
    }
    for r_name in REMOVED_FORMAT_NAMES:
        db.query(CustomFormat).filter(CustomFormat.name == r_name).delete()

    existing_cfs = {cf.name: cf for cf in db.query(CustomFormat).all()}
    added = False
    for item in DEFAULT_CUSTOM_FORMATS:
        if item["name"] not in existing_cfs:
            cf = CustomFormat(
                name=item["name"],
                score=item["score"],
                include_custom_format_when_renaming=item["include_custom_format_when_renaming"],
                specifications=item["specifications"],
                is_builtin=True,
            )
            db.add(cf)
            added = True
        else:
            cf = existing_cfs[item["name"]]
            if not getattr(cf, "is_builtin", False):
                cf.is_builtin = True
                db.add(cf)
                added = True
    try:
        db.commit()
    except Exception:
        db.rollback()


def reset_custom_format_to_default(cf: CustomFormat) -> bool:
    """Сбрасывает штатный кастомный формат до заводских настроек по умолчанию."""
    item = DEFAULT_FORMAT_BY_NAME.get(cf.name)
    if not item:
        return False
    cf.score = item["score"]
    cf.include_custom_format_when_renaming = item["include_custom_format_when_renaming"]
    cf.specifications = item["specifications"]
    cf.is_builtin = True
    return True


class SpecificationEvaluator:
    @staticmethod
    def evaluate(spec: dict, title: str, quality: QualityInfo, languages: List[Language], release_group: Optional[str], size_bytes: int) -> bool:
        impl = spec.get("implementation", "ReleaseTitleSpecification")
        negate = bool(spec.get("negate", False))
        fields = spec.get("fields", {})

        result = False
        if impl == "ReleaseTitleSpecification":
            val = fields.get("value", "")
            if val:
                try:
                    result = bool(re.search(val, title, re.IGNORECASE))
                except Exception:
                    result = False
        elif impl == "QualitySpecification":
            req_q = fields.get("value", "").strip()
            if req_q:
                if quality.name.lower() == req_q.lower():
                    result = True
                else:
                    try:
                        result = bool(re.search(req_q, quality.name, re.IGNORECASE)) or bool(re.search(req_q, title, re.IGNORECASE))
                    except Exception:
                        result = False
        elif impl == "ReleaseGroupSpecification":
            val = fields.get("value", "")
            if val and release_group:
                try:
                    result = bool(re.search(val, release_group, re.IGNORECASE))
                except Exception:
                    result = False
        elif impl == "LanguageSpecification":
            req_lang = fields.get("value", "").lower()
            if req_lang:
                result = any(l.value.lower() == req_lang or l.name.lower() == req_lang for l in languages)
        elif impl == "ResolutionSpecification":
            req_res = fields.get("value", "").lower()
            if req_res:
                result = (quality.resolution.lower() == req_res)
        elif impl == "SourceSpecification":
            req_src = fields.get("value", "").lower()
            if req_src:
                result = (quality.source.lower() == req_src)
        elif impl == "SizeSpecification":
            min_mb = fields.get("min_mb")
            max_mb = fields.get("max_mb")
            size_mb = size_bytes / (1024 * 1024)
            result = True
            if min_mb is not None and size_mb < min_mb:
                result = False
            if max_mb is not None and size_mb > max_mb:
                result = False
        else:
            result = True

        return not result if negate else result


def evaluate_custom_format(cf: CustomFormat, title: str, quality: QualityInfo, languages: List[Language], release_group: Optional[str], size_bytes: int = 0) -> bool:
    if cf.name and quality and quality.name and cf.name.lower() == quality.name.lower():
        return True

    specs = cf.specifications or []
    if not specs:
        return False

    for spec in specs:
        is_required = spec.get("required", True)
        matches = SpecificationEvaluator.evaluate(spec, title, quality, languages, release_group, size_bytes)
        if is_required and not matches:
            return False
        if not is_required and not matches:
            pass

    return True


def calculate_custom_formats_for_release(
    db: Session,
    title: str,
    quality: Optional[QualityInfo] = None,
    languages: Optional[List[Language]] = None,
    release_group: Optional[str] = None,
    size_bytes: int = 0,
    quality_profile: Optional[QualityProfile] = None,
) -> tuple[int, List[MatchedCustomFormat]]:
    """
    Вычисляет подходящие кастомные форматы для релиза и суммарный балл (Custom Format Score).
    Если задан quality_profile, учитываются переопределения очков из профиля.
    """
    if quality is None:
        quality = parse_quality(title)
    if languages is None:
        languages = parse_languages(title)
    if release_group is None:
        release_group = parse_release_group(title)

    all_cfs = db.query(CustomFormat).all() if db is not None else []
    matched_formats: List[MatchedCustomFormat] = []
    total_score = 0

    # Проверяем переопределения очков в профиле
    profile_format_scores = {}
    if quality_profile and quality_profile.format_items:
        for fi in quality_profile.format_items:
            fid = fi.get("format_id")
            fscore = fi.get("score")
            if fid is not None and fscore is not None:
                profile_format_scores[fid] = int(fscore)

    for cf in all_cfs:
        if evaluate_custom_format(cf, title, quality, languages, release_group, size_bytes):
            score = profile_format_scores.get(cf.id, cf.score)
            matched_formats.append(
                MatchedCustomFormat(
                    id=cf.id,
                    name=cf.name,
                    score=score,
                    include_custom_format_when_renaming=cf.include_custom_format_when_renaming,
                )
            )
            total_score += score

    return total_score, matched_formats
