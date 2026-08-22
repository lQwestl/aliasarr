from __future__ import annotations

import sys
import os
import unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.quality import parse_quality, is_allowed, is_upgrade
from app.services.matcher import AliasCandidate, match_release, best_alias_match


class TestQualityAndMatcher(unittest.TestCase):
    def test_quality_webdl_1080p(self):
        q = parse_quality("Show.S01E05.1080p.WEB-DL.x264")
        self.assertEqual(q.name, "WEBDL-1080p")

    def test_quality_bluray_2160p_highest(self):
        q1 = parse_quality("Show.S01E05.2160p.BluRay")
        q2 = parse_quality("Show.S01E05.480p")
        self.assertTrue(is_upgrade(q2, q1))

    def test_quality_allowed_filter(self):
        q = parse_quality("Show.S01E05.720p.HDTV")
        self.assertFalse(is_allowed(q, ["WEBDL-1080p", "Bluray-1080p"]))

    def test_alias_match_russian(self):
        aliases = [
            AliasCandidate(1, "Крестьянин 999 уровня", "ru"),
            AliasCandidate(2, "The Villager of Level 999", "en"),
        ]
        best, score = best_alias_match("Крестьянин.999.уровня.S01E05.1080p", aliases)
        self.assertIsNotNone(best)
        self.assertEqual(best.alias_id, 1)
        self.assertGreater(score, 80)

    def test_match_release_full(self):
        aliases = [AliasCandidate(1, "Крестьянин 999 уровня", "ru")]
        m = match_release("Крестьянин.999.уровня.E01-E06.[1-6]", show_id=1, aliases=aliases)
        self.assertTrue(m.matched)
        self.assertEqual(m.parsed.episodes, [1, 2, 3, 4, 5, 6])

    def test_no_match_unrelated_title(self):
        aliases = [AliasCandidate(1, "Крестьянин 999 уровня", "ru")]
        m = match_release("Совершенно другое шоу S01E05", show_id=1, aliases=aliases)
        self.assertFalse(m.matched)

    def test_no_match_movie_for_anime_series(self):
        aliases = [AliasCandidate(0, "Naruto", "en", 0), AliasCandidate(1, "Наруто", "ru", 1)]
        m = match_release("Naruto Shippuuden. Movie 1 (BDrip 1080p)", show_id=1, aliases=aliases, content_type="anime")
        self.assertFalse(m.matched)

    def test_match_anime_batches(self):
        aliases = [AliasCandidate(0, "Naruto", "en", 0), AliasCandidate(1, "Наруто", "ru", 1)]
        m1 = match_release("Naruto [01-220] [WEBRip 1080p]", show_id=1, aliases=aliases, content_type="anime")
        self.assertTrue(m1.matched)
        self.assertEqual(m1.parsed.episodes, list(range(1, 221)))

        m2 = match_release("Naruto.S01.1080p", show_id=1, aliases=aliases, content_type="anime")
        self.assertTrue(m2.matched)

    def test_no_match_openings_and_endings(self):
        aliases = [AliasCandidate(0, "Naruto", "en", 0), AliasCandidate(1, "Наруто", "ru", 1)]
        for rel_name in [
            "Naruto - OP 03 [1080p]",
            "Naruto - ED 03 [1080p]",
            "Naruto - NCED 03 [1080p]",
            "Naruto - NCOP 03 [1080p]",
            "Naruto (Опенинги и Эндинги) [BDRip 1080p]",
            "Naruto - Опенинг 3",
            "Naruto - Эндинг 3",
            "[AniLibria] Naruto [OP/ED]",
            "Naruto Openings & Endings [1080p]",
            "Naruto (Трейлеры и Промо)",
        ]:
            m = match_release(rel_name, show_id=1, aliases=aliases, content_type="anime")
            self.assertFalse(m.matched, f"Expected {rel_name} not to match regular anime episodes")

    def test_lucifer_series_matching_and_rejections(self):
        aliases = [
            AliasCandidate(0, "Lucifer", "en", 0),
            AliasCandidate(1, "Люцифер", "ru", 1),
        ]

        # 1. Valid Lucifer series releases
        valid_releases = [
            ("Люцифер (S1E1-13 of 13) / Lucifer (2016) WEB-DL-1080p-AVC [мультираздача]", 1, list(range(1, 14))),
            ("Люцифер (S2E1-18 of 18) / Lucifer (2016) WEB-DL-1080p-AVC [мультираздача]", 2, list(range(1, 19))),
            ("Lucifer - S1 - rus 1080p WEBDL (LostFilm)", 1, []),
            ("Люцифер / Lucifer / S1-6E1-93 of 93", 1, list(range(1, 94))),
            ("Люцифер / Lucifer [S01-06] (2016-2021) HDRip, WEB-DL", 1, []),
        ]
        for rel_name, exp_season, exp_eps in valid_releases:
            m = match_release(rel_name, show_id=1, aliases=aliases, content_type="series")
            self.assertTrue(m.matched, f"Expected '{rel_name}' to match series Lucifer")
            self.assertEqual(m.parsed.season, exp_season)
            if exp_eps:
                self.assertEqual(m.parsed.episodes, exp_eps)

        # 2. Invalid releases (different movie, different anime, music, games)
        invalid_releases = [
            "Luzifer.2021.Al!ve.AG.BDRemux.1080p.mkv",
            "Люцифер и Бисквитный Молот / Hoshi no Samidare / Lucifer and the Biscuit Hammer [TV] [E24 of 24]",
            "Комета Люцифер / E01-E12 Comet Lucifer - AniLiberty.TOP [HDTVRip 720p]",
            "Shin Megami Tensei: Lucifer's Call [PAL/ENG]",
            "[32/384] Monte Kristo - The Girl Of Lucifer (12'' Maxi-Single) - 1985, WavPack (image+.cue)",
            "Konkhra - Sad Plight of Lucifer - 2024 (Death Metal) [TR24] [OF]",
            "Lucifer - Lucifer V - 2024, FLAC (tracks), lossless (Psychedelic, Heavy Rock, Occult Rock) [WEB]",
            "Lucifer's Friend - Lucifer's Friend - 1970 (2010), FLAC (tracks+.cue), lossless",
            "[32/384] The Alan Parsons Project - Lucifer (12'' Maxi-Single) - 1979, WavPack",
        ]
        for rel_name in invalid_releases:
            m = match_release(rel_name, show_id=1, aliases=aliases, content_type="series")
            self.assertFalse(m.matched, f"Expected '{rel_name}' NOT to match series Lucifer")


    def test_movie_star_wars_episode_iv(self):
        aliases = [
            AliasCandidate(0, "Star Wars: Episode IV - A New Hope", "en", 0),
            AliasCandidate(1, "Звёздные войны: Эпизод 4 - Новая надежда", "ru", 1),
            AliasCandidate(2, "Star Wars: A New Hope", "en", 2),
            AliasCandidate(3, "Звёздные войны: Новая надежда", "ru", 3),
        ]
        release = "Звёздные войны: Эпизод 4 - Новая надежда / Star Wars: Episode IV - A New Hope [1977, США, WEB-DL 2160p, HDR10, Dolby Vision]"
        m = match_release(release, show_id=1, aliases=aliases, content_type="movie")
        self.assertTrue(m.matched)
        self.assertIn(m.alias_text, ["Star Wars: Episode IV - A New Hope", "Звёздные войны: Эпизод 4 - Новая надежда"])

        # Test DecisionEngine does not reject it as S04/E04
        from app.services.decision_engine import DecisionEngine
        from unittest.mock import MagicMock
        mock_show = MagicMock()
        mock_show.id = 1
        mock_show.title = "Star Wars: Episode IV - A New Hope"
        mock_show.content_type = "movie"
        mock_show.quality_profile_id = None
        mock_show.aliases = [
            MagicMock(id=1, text="Звёздные войны: Эпизод 4 - Новая надежда", language=MagicMock(value="ru"), priority=1),
            MagicMock(id=2, text="Star Wars: Episode IV - A New Hope", language=MagicMock(value="en"), priority=2),
        ]
        mock_ep = MagicMock()
        mock_ep.season_number = 1
        mock_ep.episode_number = 1
        mock_ep.absolute_number = None
        mock_ep.status = "wanted"
        mock_ep.downloaded_quality = None
        mock_ep.file_path = None

        mock_db = MagicMock()
        mock_db.get.return_value = None

        dec = DecisionEngine.evaluate_release(
            db=mock_db,
            title=release,
            show=mock_show,
            episodes=[mock_ep],
            size_bytes=39 * 1024 * 1024 * 1024,
            seeders=58,
        )
        self.assertTrue(dec.approved, f"Decision rejected with: {dec.rejections}")
        self.assertEqual(dec.rejections, [])

    def test_builtin_custom_formats_and_reset(self):
        from types import SimpleNamespace
        from app.services.custom_formats import (
            DEFAULT_CUSTOM_FORMATS,
            DEFAULT_FORMAT_BY_NAME,
            DEFAULT_FORMAT_NAMES,
            reset_custom_format_to_default,
        )

        self.assertEqual(len(DEFAULT_CUSTOM_FORMATS), 17)
        self.assertIn("Bluray-1080p", DEFAULT_FORMAT_NAMES)
        self.assertIn("Remux-2160p", DEFAULT_FORMAT_NAMES)

        cf = SimpleNamespace(
            name="Bluray-1080p",
            score=999,  # modified
            include_custom_format_when_renaming=True,  # modified
            specifications=[{"name": "test", "implementation": "ReleaseTitleSpecification", "fields": {"value": "custom"}}],
            is_builtin=True,
        )
        self.assertEqual(cf.score, 999)

        # Reset to default
        res = reset_custom_format_to_default(cf)
        self.assertTrue(res)
        self.assertEqual(cf.score, DEFAULT_FORMAT_BY_NAME["Bluray-1080p"]["score"])
        self.assertEqual(cf.include_custom_format_when_renaming, False)
        self.assertEqual(cf.specifications, DEFAULT_FORMAT_BY_NAME["Bluray-1080p"]["specifications"])

        # Reset on non-builtin returns False
        user_cf = SimpleNamespace(name="MyUserFormat", score=100, is_builtin=False)
        self.assertFalse(reset_custom_format_to_default(user_cf))

    def test_lv999_villager_anime_season_and_episodes(self):
        from app.services.parser import parse_episode, detect_season_label
        from app.services.decision_engine import DecisionEngine
        from unittest.mock import MagicMock

        title1 = "Крестьянин 999 уровня / Lv999 no Murabito / The Villager of Level 999 / Крестьянин девятьсот девяносто девятого уровня [TV] [01-08 из 12] [RUS(int), JAP+Sub] [2026, Фэнтези, WEB-DL] [1080p]"
        title2 = "Крестьянин 999 уровня | Lv999 no Murabito | The Villager of Level 999 | Крестьянин девятьсот девяносто девятого уровня [TV] [1-7 из 12] [2026] [фэнтези] [WEB-DL] [1080p] [Дублированный, (JAP+SUB)]"

        p1 = parse_episode(title1)
        self.assertEqual(p1.episodes, [1, 2, 3, 4, 5, 6, 7, 8])
        self.assertEqual(p1.season, None)
        self.assertEqual(detect_season_label(title1), {"type": "none"})

        p2 = parse_episode(title2)
        self.assertEqual(p2.episodes, [1, 2, 3, 4, 5, 6, 7])
        self.assertEqual(p2.season, None)
        self.assertEqual(detect_season_label(title2), {"type": "none"})

        aliases = [
            AliasCandidate(1, "Крестьянин 999 уровня", "ru", 1),
            AliasCandidate(2, "Lv999 no Murabito", "ja", 2),
            AliasCandidate(3, "The Villager of Level 999", "en", 3),
        ]
        m1 = match_release(title1, show_id=10, aliases=aliases, content_type="anime")
        self.assertTrue(m1.matched)

        # DecisionEngine validation for Season 1
        mock_show = MagicMock()
        mock_show.id = 10
        mock_show.title = "Крестьянин 999 уровня"
        mock_show.content_type = "anime"
        mock_show.quality_profile_id = 1
        mock_show.aliases = [
            MagicMock(id=1, text="Крестьянин 999 уровня", language=MagicMock(value="ru"), priority=1),
            MagicMock(id=2, text="Lv999 no Murabito", language=MagicMock(value="ja"), priority=2),
            MagicMock(id=3, text="The Villager of Level 999", language=MagicMock(value="en"), priority=3),
        ]
        mock_profile = MagicMock()
        mock_profile.id = 1
        mock_profile.name = "HD-1080p"
        mock_profile.allowed_qualities = ["WEBDL-1080p", "Bluray-1080p", "WEBRip-1080p"]
        mock_profile.min_size_mb = 0
        mock_profile.max_size_mb = 50000

        mock_db = MagicMock()
        mock_db.get.return_value = mock_profile

        episodes = [
            MagicMock(id=i, season_number=1, episode_number=i, absolute_number=i, status="wanted", downloaded_quality=None, file_path=None)
            for i in range(1, 13)
        ]

        dec1 = DecisionEngine.evaluate_release(
            db=mock_db,
            title=title1,
            show=mock_show,
            episodes=episodes,
            size_bytes=11 * 1024 * 1024 * 1024,
            seeders=52,
            quality_profile=mock_profile,
        )
        self.assertTrue(dec1.approved, f"Expected title1 to be approved, got rejections: {dec1.rejections}")
        self.assertEqual(dec1.rejections, [])

        dec2 = DecisionEngine.evaluate_release(
            db=mock_db,
            title=title2,
            show=mock_show,
            episodes=episodes,
            size_bytes=10 * 1024 * 1024 * 1024,
            seeders=5,
            quality_profile=mock_profile,
        )
        self.assertTrue(dec2.approved, f"Expected title2 to be approved, got rejections: {dec2.rejections}")
        self.assertEqual(dec2.rejections, [])

    def test_spider_man_movie_vs_nintendo_wii_game(self):
        from app.services.matcher import is_non_video_release
        from app.services.decision_engine import DecisionEngine
        from unittest.mock import MagicMock

        aliases = [
            AliasCandidate(1, "Spider-Man: Brand New Day", "en", 1),
            AliasCandidate(2, "Человек-паук: Новый день", "ru", 2),
            AliasCandidate(3, "Spider-Man 4", "en", 3),
            AliasCandidate(5, "Marvel Studios' Spider-Man: Brand New Day", "en", 5),
            AliasCandidate(6, "Человек-паук КВМ 4", "ru", 6),
        ]

        # 1. Invalid Nintendo Wii game release with alias Spider-Man 4
        game_release = "[Nintendo Wii] Spider-Man 4 [NTSC, ENG] [Prototype]"
        self.assertTrue(is_non_video_release(game_release))

        m_game = match_release(game_release, show_id=1, aliases=aliases, content_type="movie")
        self.assertFalse(m_game.matched, "Expected Nintendo Wii game release NOT to match movie")

        # 2. DecisionEngine evaluation
        mock_show = MagicMock()
        mock_show.id = 1
        mock_show.title = "Spider-Man: Brand New Day"
        mock_show.content_type = "movie"
        mock_show.quality_profile_id = None
        mock_show.aliases = [
            MagicMock(id=1, text="Spider-Man: Brand New Day", language=MagicMock(value="en"), priority=1),
            MagicMock(id=2, text="Человек-паук: Новый день", language=MagicMock(value="ru"), priority=2),
            MagicMock(id=3, text="Spider-Man 4", language=MagicMock(value="en"), priority=3),
        ]
        mock_ep = MagicMock()
        mock_ep.season_number = 1
        mock_ep.episode_number = 1
        mock_ep.status = "wanted"
        mock_ep.downloaded_quality = None
        mock_ep.file_path = None

        mock_db = MagicMock()
        mock_db.get.return_value = None

        dec_game = DecisionEngine.evaluate_release(
            db=mock_db,
            title=game_release,
            show=mock_show,
            episodes=[mock_ep],
            size_bytes=4 * 1024 * 1024 * 1024,
            seeders=15,
        )
        self.assertFalse(dec_game.approved)
        self.assertTrue(any("не является видео-контентом" in r for r in dec_game.rejections))

        # 3. Valid movie release
        valid_movie = "Spider-Man: Brand New Day (2026) 1080p WEB-DL DDP5.1 Atmos H.264"
        self.assertFalse(is_non_video_release(valid_movie))
        m_movie = match_release(valid_movie, show_id=1, aliases=aliases, content_type="movie")
        self.assertTrue(m_movie.matched)

        dec_movie = DecisionEngine.evaluate_release(
            db=mock_db,
            title=valid_movie,
            show=mock_show,
            episodes=[mock_ep],
            size_bytes=6 * 1024 * 1024 * 1024,
            seeders=50,
        )
        self.assertTrue(dec_movie.approved, f"Expected movie release to be approved, got: {dec_movie.rejections}")


if __name__ == "__main__":
    unittest.main()


