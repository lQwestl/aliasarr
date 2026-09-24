"""Правила выбора и замены релизов одинаковы для ручного и автоматического поиска.

Проверяются единое правило апгрейда, лимиты размера на серию, разбор названий
(S01.E01, S2024E01, ежедневные выпуски, экранки) и сопоставление с алиасами.
"""

from __future__ import annotations

import datetime as dt
import unittest
from types import SimpleNamespace

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.operations import _validated_title_regex
from app.models.db import Base, CustomFormat, DownloadHistory, Episode, EpisodeStatus, QualityProfile, Show
from app.services.auto_search import _backlog_search_due, _indexer_priority, _release_episode_count
from app.services.decision_engine import DecisionEngine
from app.services.matcher import AliasCandidate, match_release
from app.services.parser import parse_episode
from app.services.postprocess import _grabbed_release_cf_score
from app.services.quality import parse_quality, size_limit_rejection, upgrade_rejection


class TestUpgradeRule(unittest.TestCase):
    def test_lower_quality_is_never_an_upgrade_even_with_better_formats(self):
        reason = upgrade_rejection(
            parse_quality("Bluray-1080p"), parse_quality("Show.S01E01.720p.WEB-DL.RUS"),
            current_score=0, candidate_score=500,
        )
        self.assertIsNotNone(reason)

    def test_higher_quality_is_an_upgrade(self):
        self.assertIsNone(upgrade_rejection(parse_quality("WEBDL-720p"), parse_quality("WEBDL-1080p")))

    def test_proper_of_the_same_quality_is_an_upgrade(self):
        self.assertIsNone(upgrade_rejection(
            parse_quality("Show.S01E01.1080p.WEB-DL"), parse_quality("Show.S01E01.1080p.WEB-DL.PROPER"),
        ))
        self.assertIsNotNone(upgrade_rejection(
            parse_quality("Show.S01E01.1080p.WEB-DL.PROPER"), parse_quality("Show.S01E01.1080p.WEB-DL.REPACK"),
        ))

    def test_better_formats_at_the_same_quality_need_a_known_current_score(self):
        same = parse_quality("WEBDL-1080p")
        self.assertIsNone(upgrade_rejection(same, same, current_score=10, candidate_score=50))
        # Файлы, импортированные до учёта форматов: счёт неизвестен — не перекачиваем.
        self.assertIsNotNone(upgrade_rejection(same, same, current_score=None, candidate_score=50))

    def test_cutoff_uses_quality_and_format_score(self):
        current = parse_quality("WEBDL-1080p")
        better = parse_quality("Bluray-1080p")
        self.assertIsNotNone(upgrade_rejection(current, better, cutoff_quality="WEBDL-1080p", current_score=100, cutoff_score=100))
        self.assertIsNone(upgrade_rejection(current, better, cutoff_quality="WEBDL-1080p", current_score=10, cutoff_score=100))

    def test_disallowed_candidate_is_rejected(self):
        self.assertIsNotNone(upgrade_rejection(
            parse_quality("WEBDL-720p"), parse_quality("Remux-2160p"), allowed_qualities=["WEBDL-1080p"],
        ))


class TestSizeLimits(unittest.TestCase):
    profile = SimpleNamespace(min_size_mb=200, max_size_mb=4000)

    def test_limits_are_per_episode(self):
        ten_episode_pack = 10 * 3000 * 1024 * 1024
        self.assertIsNone(size_limit_rejection(ten_episode_pack, self.profile, 10))
        self.assertIsNotNone(size_limit_rejection(ten_episode_pack, self.profile, 1))

    def test_too_small_and_unknown_size(self):
        self.assertIsNotNone(size_limit_rejection(50 * 1024 * 1024, self.profile, 1))
        self.assertIsNone(size_limit_rejection(0, self.profile, 1))

    def test_release_episode_count(self):
        show = SimpleNamespace(content_type="series")
        self.assertEqual(_release_episode_count(parse_episode("Show.S01E01E02.1080p"), {}, show), 2)
        self.assertEqual(_release_episode_count(parse_episode("Show.S02.1080p.WEB-DL"), {2: 8}, show), 8)
        self.assertEqual(_release_episode_count(parse_episode("Movie.2023.1080p"), {}, SimpleNamespace(content_type="movie")), 1)


class TestIndexerPriority(unittest.TestCase):
    def test_zero_is_the_highest_priority(self):
        self.assertEqual(_indexer_priority(SimpleNamespace(priority=0)), 0)
        self.assertEqual(_indexer_priority(SimpleNamespace(priority=None)), 100)
        self.assertGreater(-_indexer_priority(SimpleNamespace(priority=0)), -_indexer_priority(SimpleNamespace(priority=25)))


class TestReleaseParsing(unittest.TestCase):
    def test_split_season_episode(self):
        parsed = parse_episode("Show.Name.S01.E05.1080p.WEB-DL")
        self.assertEqual((parsed.season, parsed.episodes), (1, [5]))

    def test_year_numbered_season(self):
        parsed = parse_episode("Show.Name.S2024E03.1080p")
        self.assertEqual((parsed.season, parsed.episodes), (2024, [3]))

    def test_daily_release_is_matched_by_date_not_as_episode_ten(self):
        parsed = parse_episode("Show.Name.2024.10.15.Guest.1080p.WEB")
        self.assertEqual(parsed.air_date, "2024-10-15")
        self.assertEqual(parsed.episodes, [])

    def test_bracketed_date_does_not_override_episode_number(self):
        parsed = parse_episode("[Group] Show - 12 [2024.10.15]")
        self.assertEqual(parsed.episodes, [12])
        self.assertIsNone(parsed.air_date)

    def test_pre_release_sources(self):
        self.assertEqual(parse_quality("Movie.2023.1080p.TS.x264").source, "Telesync")
        self.assertEqual(parse_quality("Movie.2023.DVDSCR.XviD").source, "Workprint")
        self.assertEqual(parse_quality("Movie.2023.UHDRip").name, "Bluray-2160p")
        self.assertEqual(parse_quality("Show.S01E01.1080p.ts").source, "HDTV")


class TestCountryTags(unittest.TestCase):
    def _match(self, release, *aliases):
        return match_release(release, 1, [AliasCandidate(i, a) for i, a in enumerate(aliases)])

    def test_scene_country_tag_is_ignored_for_plain_alias(self):
        self.assertTrue(self._match("The.Office.US.S01E01.720p", "The Office").matched)

    def test_country_specific_alias_still_distinguishes_versions(self):
        self.assertFalse(self._match("The.Office.UK.S01E01.720p", "The Office (US)").matched)

    def test_lowercase_word_is_part_of_the_title(self):
        self.assertFalse(self._match("It.Ends.With.Us.2024.1080p", "It Ends With").matched)


class _DbCase(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()
        self.profile = QualityProfile(
            name="HD", allowed_qualities=["WEBDL-720p", "WEBDL-1080p", "Bluray-1080p"],
            upgrade_allowed=True, cutoff_quality="Bluray-1080p",
        )
        self.db.add(self.profile)
        self.db.add(CustomFormat(name="Russian dub", score=100, specifications=[
            {"implementation": "ReleaseTitleSpecification", "fields": {"value": r"\bRUS\b"}},
        ]))
        self.db.flush()
        self.show = Show(title="Dexter", content_type="series", monitored=True, quality_profile_id=self.profile.id)
        self.db.add(self.show)
        self.db.flush()

    def tearDown(self):
        self.db.close()


class TestDecisionEngineUpgrades(_DbCase):
    def _episode(self, quality, score=None):
        ep = Episode(
            show_id=self.show.id, season_number=1, episode_number=1, status=EpisodeStatus.DOWNLOADED,
            file_path="/media/Dexter/S01E01.mkv", downloaded_quality=quality, imported_cf_score=score,
        )
        self.db.add(ep)
        self.db.commit()
        return ep

    def test_better_formats_do_not_justify_a_quality_downgrade(self):
        ep = self._episode("WEBDL-1080p", score=0)
        decision = DecisionEngine.evaluate_release(
            self.db, "Dexter.S01E01.720p.WEB-DL.RUS", show=self.show, episodes=[ep],
            quality_profile=self.profile,
        )
        self.assertFalse(decision.approved)

    def test_same_quality_with_better_formats_is_approved(self):
        ep = self._episode("WEBDL-1080p", score=0)
        decision = DecisionEngine.evaluate_release(
            self.db, "Dexter.S01E01.1080p.WEB-DL.RUS", show=self.show, episodes=[ep],
            quality_profile=self.profile,
        )
        self.assertTrue(decision.approved, decision.rejections)

    def test_daily_release_must_match_episode_air_date(self):
        ep = Episode(show_id=self.show.id, season_number=2024, episode_number=40,
                     status=EpisodeStatus.WANTED, air_date=dt.datetime(2024, 10, 15))
        self.db.add(ep)
        self.db.commit()
        ok = DecisionEngine.evaluate_release(self.db, "Dexter.2024.10.15.1080p.WEB-DL", show=self.show, episodes=[ep])
        wrong = DecisionEngine.evaluate_release(self.db, "Dexter.2024.10.16.1080p.WEB-DL", show=self.show, episodes=[ep])
        self.assertNotIn("не относится к разыскиваемым", " ".join(ok.rejections))
        self.assertIn("не относится к разыскиваемым", " ".join(wrong.rejections))


class TestImportedFormatScore(_DbCase):
    def test_score_comes_from_the_grabbed_release_title(self):
        self.db.add(DownloadHistory(show_id=self.show.id, release_title="Dexter.S01E01.1080p.WEB-DL.RUS",
                                    torrent_hash="abc", event_type="grabbed"))
        self.db.commit()
        self.assertEqual(_grabbed_release_cf_score(self.db, self.show, "ABC"), 100)
        self.assertIsNone(_grabbed_release_cf_score(self.db, self.show, "unknown"))


class TestBacklogSearchWindow(_DbCase):
    def test_old_missing_episodes_are_searched_less_often(self):
        now = dt.datetime(2026, 9, 24, 12, 0)
        self.db.add(Episode(show_id=self.show.id, season_number=1, episode_number=1, status=EpisodeStatus.WANTED,
                            monitored=True, air_date=dt.datetime(2020, 1, 1)))
        self.show.last_search_at = now - dt.timedelta(hours=1)
        self.db.commit()
        self.assertFalse(_backlog_search_due(self.db, self.show, now))
        self.show.last_search_at = now - dt.timedelta(hours=13)
        self.assertTrue(_backlog_search_due(self.db, self.show, now))

    def test_recent_episodes_are_searched_every_cycle(self):
        now = dt.datetime(2026, 9, 24, 12, 0)
        self.db.add(Episode(show_id=self.show.id, season_number=1, episode_number=2, status=EpisodeStatus.WANTED,
                            monitored=True, air_date=now - dt.timedelta(days=2)))
        self.show.last_search_at = now - dt.timedelta(minutes=15)
        self.db.commit()
        self.assertTrue(_backlog_search_due(self.db, self.show, now))


class TestProfileRegexValidation(unittest.TestCase):
    def test_invalid_pattern_is_rejected_on_save(self):
        with self.assertRaises(HTTPException):
            _validated_title_regex("(unclosed")
        self.assertEqual(_validated_title_regex("  RUS  "), "RUS")
        self.assertIsNone(_validated_title_regex("   "))


if __name__ == "__main__":
    unittest.main()
