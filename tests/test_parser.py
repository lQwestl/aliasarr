"""
Тесты универсального парсера названий релизов.
Запуск: pytest tests/test_parser.py -v
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.parser import parse_episode, ReleaseKind, normalize


def test_sxxexx_basic():
    r = parse_episode("Show.Name.S01E05.1080p.WEB-DL")
    assert r.kind == ReleaseKind.EPISODE
    assert r.season == 1
    assert r.episodes == [5]


def test_sxxexx_multi_range():
    r = parse_episode("Show.Name.S01E05-E07.1080p")
    assert r.season == 1
    assert r.episodes == [5, 6, 7]
    assert r.is_range


def test_1x05_format():
    r = parse_episode("Show Name 1x05 HDTV")
    assert r.season == 1
    assert r.episodes == [5]


def test_e05_format():
    r = parse_episode("Show Name E05")
    assert r.episodes == [5]


def test_ep05_format():
    r = parse_episode("Show Name EP05")
    assert r.episodes == [5]


def test_lone_number_05():
    r = parse_episode("Шоу Имя - серия 05")
    assert 5 in r.episodes


def test_lone_number_5():
    r = parse_episode("Show Name 5")
    assert r.episodes == [5]


def test_bracket_range():
    r = parse_episode("Show Name [01-06] complete")
    assert r.episodes == list(range(1, 7))
    assert r.is_range


def test_range_iz_n():
    r = parse_episode("Show Name 01-06 из 12")
    assert r.episodes == list(range(1, 7))


def test_dash_absolute():
    r = parse_episode("Anime Name - 05 [1080p]")
    assert r.kind == ReleaseKind.ABSOLUTE
    assert r.episodes == [5]


def test_year_not_parsed_as_range():
    r = parse_episode("Show Name 2024-2025 Complete Series")
    # год не должен восприниматься как диапазон серий 2024-2025
    assert r.episodes != list(range(2024, 2026))


def test_season_pack():
    r = parse_episode("Show Name S02 Complete 1080p")
    assert r.kind == ReleaseKind.SEASON_PACK
    assert r.season == 2


def test_acceptance_case_villager_999():
    """
    Русскоязычный релиз с составным именем, диапазоном серий E01-E06 и меткой [1-6].
    """
    name = "Крестьянин.девятьсот.девяносто.девятого.уровня..E01-E06.Lv999.no.Murabito...[1-6]"
    r = parse_episode(name)
    assert r.kind == ReleaseKind.EPISODE
    assert r.episodes == [1, 2, 3, 4, 5, 6]
    assert r.is_range


def test_resolution_not_confused_with_number():
    r = parse_episode("Show Name S01E05 1080p x264")
    assert r.season == 1
    assert r.episodes == [5]


def test_all_formats_give_episode_5():
    """Все вариации форматов нумерации серии должны распознавать 5 серию."""
    variants = [
        "Show S01E05",
        "Show 1x05",
        "Show E05",
        "Show 05",
        "Show 5",
    ]
    for v in variants:
        r = parse_episode(v)
        assert 5 in r.episodes, f"failed for variant: {v} -> {r}"


def test_normalize_strips_noise():
    n = normalize("Show.Name.1080p.x264.WEB-DL.AAC")
    assert "1080p" not in n
    assert "x264" not in n
