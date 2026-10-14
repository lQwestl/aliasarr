import unittest
from app.services.parser import parse_episode
from app.services.matcher import AliasCandidate, match_release, best_alias_match


class TestSeasonSplitMatcher(unittest.TestCase):
    def test_donghua_ona_tv3_parsing(self):
        # 1. Tapochek format with [ONA] and (ТВ-3, часть 1)
        tap = (
            "Агент времени (ТВ-3, часть 1) | Shiguang Dailiren III | "
            "Link Click Season 3rd Season Part One [ONA] [1-9 из 12] [2026] "
            "[приключения, драма, детектив] [WEB-DL] [1080p] [Дублированный, (CHI+SUB)]"
        )
        p_tap = parse_episode(tap)
        self.assertEqual(p_tap.season, 3)
        self.assertEqual(p_tap.episodes, list(range(1, 10)))
        self.assertEqual(p_tap.part, 1)
        self.assertEqual(p_tap.total_in_part, 12)
        self.assertFalse(p_tap.has_specials)
        self.assertEqual(p_tap.special_episodes, [])

        # 2. Rutracker format with (S3, часть 1) and [ONA]
        rut = (
            "Агент времени (S3, часть 1) / Shiguang Dailiren III / "
            "Link Click 3rd Season Part One [ONA] [1-9 из 12] [RUS(int), CHI+Sub] "
            "[2026, драма, фэнтези, WEB-DL] [1080p]"
        )
        p_rut = parse_episode(rut)
        self.assertEqual(p_rut.season, 3)
        self.assertEqual(p_rut.episodes, list(range(1, 10)))
        self.assertEqual(p_rut.part, 1)
        self.assertEqual(p_rut.total_in_part, 12)
        self.assertFalse(p_rut.has_specials)

    def test_season_split_matching_part1_and_part2(self):
        candidates = [
            AliasCandidate(
                alias_id=1,
                text="Агент времени (ТВ-3, часть 1)",
                season_number=4,
                episode_start=1,
                episode_end=12,
                episode_offset=0,
                target_number=3,
                split_id=10,
            ),
            AliasCandidate(
                alias_id=2,
                text="Shiguang Dailiren III",
                season_number=4,
                episode_start=1,
                episode_end=12,
                episode_offset=0,
                target_number=3,
                split_id=10,
            ),
            AliasCandidate(
                alias_id=3,
                text="Link Click Season 3rd Season Part One",
                season_number=4,
                episode_start=1,
                episode_end=12,
                episode_offset=0,
                target_number=3,
                split_id=10,
            ),
            AliasCandidate(
                alias_id=4,
                text="Агент времени (ТВ-3, часть 2)",
                season_number=4,
                episode_start=13,
                episode_end=24,
                episode_offset=12,
                target_number=3,
                split_id=10,
            ),
            AliasCandidate(
                alias_id=5,
                text="Link Click Season 3rd Season Part Two",
                season_number=4,
                episode_start=13,
                episode_end=24,
                episode_offset=12,
                target_number=3,
                split_id=10,
            ),
            AliasCandidate(alias_id=6, text="Агенты времени", season_number=None),
            AliasCandidate(alias_id=7, text="Shiguang Dailiren", season_number=None),
            AliasCandidate(alias_id=8, text="Link Click", season_number=None),
        ]

        # A. Rutracker release (Part 1)
        rut_title = (
            "Агент времени (S3, часть 1) / Shiguang Dailiren III / "
            "Link Click 3rd Season Part One [ONA] [1-9 из 12] [RUS(int), CHI+Sub] "
            "[2026, драма, фэнтези, WEB-DL] [1080p]"
        )
        m_rut = match_release(rut_title, show_id=183, aliases=candidates, content_type="anime")
        self.assertTrue(m_rut.matched)
        self.assertIsNotNone(m_rut.alias_candidate)
        self.assertEqual(m_rut.alias_candidate.season_number, 4)
        self.assertEqual(m_rut.alias_candidate.target_number, 3)
        self.assertEqual(m_rut.alias_candidate.episode_offset, 0)

        # B. Transmission client torrent name (Part 1)
        trans_name = "Shiguang Dailiren III Part 1 [WEB-DL 1080p]"
        m_trans = match_release(trans_name, show_id=183, aliases=candidates, content_type="anime")
        self.assertTrue(m_trans.matched)
        self.assertIsNotNone(m_trans.alias_candidate)
        self.assertEqual(m_trans.alias_candidate.season_number, 4)
        self.assertEqual(m_trans.alias_candidate.target_number, 3)
        self.assertEqual(m_trans.alias_candidate.episode_offset, 0)

        # C. Tapochek release (Part 1)
        tap_title = (
            "Агент времени (ТВ-3, часть 1) | Shiguang Dailiren III | "
            "Link Click Season 3rd Season Part One [ONA] [1-9 из 12] [2026] "
            "[приключения, драма, детектив] [WEB-DL] [1080p] [Дублированный, (CHI+SUB)]"
        )
        m_tap = match_release(tap_title, show_id=183, aliases=candidates, content_type="anime")
        self.assertTrue(m_tap.matched)
        self.assertIsNotNone(m_tap.alias_candidate)
        self.assertEqual(m_tap.alias_candidate.season_number, 4)
        self.assertEqual(m_tap.alias_candidate.target_number, 3)
        self.assertEqual(m_tap.alias_candidate.episode_offset, 0)

        # D. Part 2 release
        p2_title = "Агент времени (ТВ-3, часть 2) / Shiguang Dailiren III Part 2 [WEB-DL 1080p]"
        m_p2 = match_release(p2_title, show_id=183, aliases=candidates, content_type="anime")
        self.assertTrue(m_p2.matched)
        self.assertIsNotNone(m_p2.alias_candidate)
        self.assertEqual(m_p2.alias_candidate.season_number, 4)
        self.assertEqual(m_p2.alias_candidate.target_number, 3)
        self.assertEqual(m_p2.alias_candidate.episode_offset, 12)

    def test_regular_tv_series_split_not_broken(self):
        # Ensure TV series with season > 1 (e.g. Breaking Bad Season 5 Part 1) works
        series_candidates = [
            AliasCandidate(
                alias_id=101,
                text="Breaking Bad Season 5 Part 1",
                season_number=5,
                episode_start=1,
                episode_end=8,
                episode_offset=0,
                target_number=5,
                split_id=20,
            ),
            AliasCandidate(
                alias_id=102,
                text="Breaking Bad Season 5 Part 2",
                season_number=5,
                episode_start=9,
                episode_end=16,
                episode_offset=8,
                target_number=5,
                split_id=20,
            ),
            AliasCandidate(alias_id=100, text="Breaking Bad", season_number=None),
        ]

        rel_p1 = "Breaking Bad S05 Part 1 1080p WEB-DL"
        m1 = match_release(rel_p1, show_id=50, aliases=series_candidates, content_type="series")
        self.assertTrue(m1.matched)
        self.assertEqual(m1.alias_candidate.season_number, 5)
        self.assertEqual(m1.alias_candidate.episode_offset, 0)

        rel_p2 = "Breaking Bad S05 Part 2 1080p WEB-DL"
        m2 = match_release(rel_p2, show_id=50, aliases=series_candidates, content_type="series")
        self.assertTrue(m2.matched)
        self.assertEqual(m2.alias_candidate.season_number, 5)
        self.assertEqual(m2.alias_candidate.episode_offset, 8)


if __name__ == "__main__":
    unittest.main()
