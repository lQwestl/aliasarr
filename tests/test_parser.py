import sys
import os
import unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.parser import parse_episode, ReleaseKind, normalize


class TestParser(unittest.TestCase):
    def test_sxxexx_basic(self):
        r = parse_episode("Show.Name.S01E05.1080p.WEB-DL")
        self.assertEqual(r.kind, ReleaseKind.EPISODE)
        self.assertEqual(r.season, 1)
        self.assertEqual(r.episodes, [5])

    def test_sxxexx_multi_range(self):
        r = parse_episode("Show.Name.S01E05-E07.1080p")
        self.assertEqual(r.season, 1)
        self.assertEqual(r.episodes, [5, 6, 7])
        self.assertTrue(r.is_range)


    def test_1x05_format(self):
        r = parse_episode("Show Name 1x05 HDTV")
        self.assertEqual(r.season, 1)
        self.assertEqual(r.episodes, [5])

    def test_e05_format(self):
        r = parse_episode("Show Name E05")
        self.assertEqual(r.episodes, [5])

    def test_ep05_format(self):
        r = parse_episode("Show Name EP05")
        self.assertEqual(r.episodes, [5])

    def test_lone_number_05(self):
        r = parse_episode("Шоу Имя - серия 05")
        self.assertIn(5, r.episodes)

    def test_lone_number_5(self):
        r = parse_episode("Show Name 5")
        self.assertIn(5, r.episodes)

    def test_bracket_range(self):
        r = parse_episode("Show Name [01-06] complete")
        self.assertEqual(r.episodes, list(range(1, 7)))
        self.assertTrue(r.is_range)

    def test_range_iz_n(self):
        r = parse_episode("Show Name 01-06 из 12")
        self.assertEqual(r.episodes, list(range(1, 7)))

    def test_dash_absolute(self):
        r = parse_episode("Anime Name - 05 [1080p]")
        self.assertEqual(r.kind, ReleaseKind.ABSOLUTE)
        self.assertEqual(r.episodes, [5])

    def test_year_not_parsed_as_range(self):
        r = parse_episode("Show Name 2024-2025 Complete Series")
        self.assertNotEqual(r.episodes, list(range(2024, 2026)))

    def test_season_pack(self):
        r = parse_episode("Show Name S02 Complete 1080p")
        self.assertEqual(r.kind, ReleaseKind.SEASON_PACK)
        self.assertEqual(r.season, 2)

    def test_acceptance_case_villager_999(self):
        name = "Крестьянин.девятьсот.девяносто.девятого.уровня..E01-E06.Lv999.no.Murabito...[1-6]"
        r = parse_episode(name)
        self.assertEqual(r.kind, ReleaseKind.EPISODE)
        self.assertEqual(r.episodes, [1, 2, 3, 4, 5, 6])
        self.assertTrue(r.is_range)

    def test_resolution_not_confused_with_number(self):
        r = parse_episode("Show Name S01E05 1080p x264")
        self.assertEqual(r.season, 1)
        self.assertEqual(r.episodes, [5])

    def test_all_formats_give_episode_5(self):
        variants = [
            "Show S01E05",
            "Show 1x05",
            "Show E05",
            "Show 05",
            "Show 5",
        ]
        for v in variants:
            r = parse_episode(v)
            self.assertIn(5, r.episodes, f"failed for variant: {v} -> {r}")

    def test_normalize_strips_noise(self):
        n = normalize("Show.Name.1080p.x264.WEB-DL.AAC")
        self.assertNotIn("1080p", n)
        self.assertNotIn("x264", n)

    def test_anime_season_2_with_episodes(self):
        # 2nd Season - 01 / 02
        r1 = parse_episode("[Erai-raws] Jujutsu Kaisen 2nd Season - 01 [1080p].mkv")
        self.assertEqual(r1.season, 2)
        self.assertEqual(r1.episodes, [1])

        r2 = parse_episode("[Erai-raws] Jujutsu Kaisen 2nd Season - 02 [1080p].mkv")
        self.assertEqual(r2.season, 2)
        self.assertEqual(r2.episodes, [2])

        # S2 - 02
        r3 = parse_episode("[Judas] Boku no Hero Academia S2 - 02 [1080p].mkv")
        self.assertEqual(r3.season, 2)
        self.assertEqual(r3.episodes, [2])

        # Season 2 - 02
        r4 = parse_episode("[AnimeRG] Attack on Titan Season 2 - 02 (1080p).mkv")
        self.assertEqual(r4.season, 2)
        self.assertEqual(r4.episodes, [2])

        # S2 - 01
        r5 = parse_episode("[SubsPlease] Mushoku Tensei S2 - 01 (1080p) [12345678].mkv")
        self.assertEqual(r5.season, 2)
        self.assertEqual(r5.episodes, [1])

        # 2nd Season [01-12]
        r6 = parse_episode("Anime Title 2nd Season [01-12] [1080p]")
        self.assertEqual(r6.season, 2)
        self.assertEqual(r6.episodes, list(range(1, 13)))

        # Russian: 2 сезон - 05
        r7 = parse_episode("Anime Title 2 сезон - 05.mkv")
        self.assertEqual(r7.season, 2)
        self.assertEqual(r7.episodes, [5])

        # Roman: II сезон - 03
        r8 = parse_episode("Anime Title II сезон - 03.mkv")
        self.assertEqual(r8.season, 2)
        self.assertEqual(r8.episodes, [3])

        # Season pack without episode numbers:
        r9 = parse_episode("Anime Title 2nd Season")
        self.assertEqual(r9.kind, ReleaseKind.SEASON_PACK)
        self.assertEqual(r9.season, 2)
        self.assertEqual(r9.episodes, [])


if __name__ == "__main__":
    unittest.main()


