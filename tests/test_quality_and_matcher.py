from __future__ import annotations

import sys
import os
import unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.quality import parse_quality, is_allowed, is_upgrade, detect_file_quality
from app.services.matcher import AliasCandidate, match_release, best_alias_match


class TestQualityAndMatcher(unittest.TestCase):
    def test_quality_webdl_1080p(self):
        q = parse_quality("Show.S01E05.1080p.WEB-DL.x264")
        self.assertEqual(q.name, "WEBDL-1080p")

    def test_quality_bluray_2160p_highest(self):
        q1 = parse_quality("Show.S01E05.2160p.BluRay")
        q2 = parse_quality("Show.S01E05.480p")
        self.assertTrue(is_upgrade(q2, q1))

    def test_quality_uhd_bluray_disc_bdmv(self):
        title = "Человек-паук: Возвращение домой / Spider-Man: Homecoming (2017) UHD Blu-ray disc 2160p BDMV"
        q = parse_quality(title)
        self.assertEqual(q.name, "Bluray-2160p")
        self.assertEqual(q.resolution, "2160p")
        self.assertEqual(q.source, "Bluray")

    def test_detect_file_quality_hierarchical(self):
        # 1. BDMV stream video file with parent directory context
        path1 = "/downloads/Spider-Man Homecoming (2017) UHD Blu-ray disc 2160p BDMV/BDMV/STREAM/00001.m2ts"
        q1 = detect_file_quality(path1)
        self.assertEqual(q1.name, "Bluray-2160p")
        self.assertEqual(q1.source, "Bluray")
        self.assertEqual(q1.resolution, "2160p")

        # 2. Anime episode inside release folder
        path2 = "/downloads/Attack on Titan S04 Part 2 [WEBRip 1080p HEVC]/01.mkv"
        q2 = detect_file_quality(path2)
        self.assertEqual(q2.name, "WEBRip-1080p")
        self.assertEqual(q2.video_codec, "HEVC")

        # 3. Simple file name with external context hints
        path3 = "/downloads/Spider-Man.mkv"
        hints = ["Spider-Man: Brand New Day 2026 DVO, Sub TS 1080p - RUSSIAN"]
        q3 = detect_file_quality(path3, hints)
        self.assertEqual(q3.name, "HDTV-1080p")

        # 4. BDRip folder detection (e.g. Vermeil in Gold [BDRip] [1080p])
        path4 = "/downloads/Vermeil in Gold [BDRip] [1080p]/01.mkv"
        q4 = detect_file_quality(path4)
        self.assertEqual(q4.name, "Bluray-1080p")
        self.assertEqual(q4.source, "Bluray")
        self.assertEqual(q4.resolution, "1080p")

        # 5. Standalone BDRip without resolution
        path5 = "/downloads/Kinsou no Vermeil BDRip AVC/01.mkv"
        q5 = detect_file_quality(path5)
        self.assertEqual(q5.name, "Bluray-480p")
        self.assertEqual(q5.source, "Bluray")

    def test_parse_quality_all_formats(self):
        cases = [
            ("Show.S01E01.BDRip.x264.mkv", "Bluray-480p", "Bluray", "480p"),
            ("Show.S01E01.BRRip.x264.mkv", "Bluray-480p", "Bluray", "480p"),
            ("Show.S01E01.BDRip.720p.mkv", "Bluray-720p", "Bluray", "720p"),
            ("Show.S01E01.BDRip.1080p.mkv", "Bluray-1080p", "Bluray", "1080p"),
            ("Show.S01E01.BDRip.2160p.mkv", "Bluray-2160p", "Bluray", "2160p"),
            ("Show.S01E01.Bluray.480p.mkv", "Bluray-480p", "Bluray", "480p"),
            ("Show.S01E01.Bluray.720p.mkv", "Bluray-720p", "Bluray", "720p"),
            ("Show.S01E01.Bluray.1080p.mkv", "Bluray-1080p", "Bluray", "1080p"),
            ("Show.S01E01.Bluray.2160p.mkv", "Bluray-2160p", "Bluray", "2160p"),
            ("Show.S01E01.Remux.1080p.mkv", "Remux-1080p", "Remux", "1080p"),
            ("Show.S01E01.Remux.2160p.mkv", "Remux-2160p", "Remux", "2160p"),
            ("Show.S01E01.WEBDL.480p.mkv", "WEBDL-480p", "WEBDL", "480p"),
            ("Show.S01E01.WEBDL.720p.mkv", "WEBDL-720p", "WEBDL", "720p"),
            ("Show.S01E01.WEBDL.1080p.mkv", "WEBDL-1080p", "WEBDL", "1080p"),
            ("Show.S01E01.WEBDL.2160p.mkv", "WEBDL-2160p", "WEBDL", "2160p"),
            ("Show.S01E01.WEBRip.480p.mkv", "WEBRip-480p", "WEBRip", "480p"),
            ("Show.S01E01.WEBRip.720p.mkv", "WEBRip-720p", "WEBRip", "720p"),
            ("Show.S01E01.WEBRip.1080p.mkv", "WEBRip-1080p", "WEBRip", "1080p"),
            ("Show.S01E01.WEBRip.2160p.mkv", "WEBRip-2160p", "WEBRip", "2160p"),
            ("Show.S01E01.HDTV.480p.mkv", "HDTV-480p", "HDTV", "480p"),
            ("Show.S01E01.HDTV.720p.mkv", "HDTV-720p", "HDTV", "720p"),
            ("Show.S01E01.HDTV.1080p.mkv", "HDTV-1080p", "HDTV", "1080p"),
            ("Show.S01E01.HDTV.2160p.mkv", "HDTV-2160p", "HDTV", "2160p"),
            ("Show.S01E01.TVRip.avi", "TVRip-480p", "TVRip", "480p"),
            ("Show.S01E01.DVDRip.avi", "DVDRip-480p", "DVDRip", "480p"),
            ("Show.S01E01.DVD.iso", "DVD-480p", "DVD", "480p"),
            ("Movie.CAM.avi", "CAM-480p", "CAM", "480p"),
            ("Movie.Telesync.avi", "Telesync-480p", "Telesync", "480p"),
        ]
        for name, exp_qname, exp_source, exp_res in cases:
            q = parse_quality(name)
            self.assertEqual(q.name, exp_qname, f"Failed canonical name for {name}")
            self.assertEqual(q.source, exp_source, f"Failed source for {name}")
            self.assertEqual(q.resolution, exp_res, f"Failed resolution for {name}")

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

    def test_vermeil_in_gold_matching(self):
        aliases = [
            AliasCandidate(0, "Vermeil in Gold", "en", 0),
            AliasCandidate(1, "Вермейл в золотом", "ru", 1),
            AliasCandidate(2, "Kinsou no Vermeil", "romaji", 2),
        ]
        title = "Вермейл в золотом / Kinsou no Vermeil: Gakeppuchi Majutsushi wa Saikyou no Yakusai to Mahou Sekai o (wo) Tsukisusumu / Vermeil in Gold (Наоя Такаси) [TV] [E12 of 12] [RUS(ext), ENG, JAP+Sub] [2022, комедия, романтика, этти, фэнтези, BDRip] [1080p]"
        m = match_release(title, show_id=10, aliases=aliases, content_type="anime")
        self.assertTrue(m.matched)
        self.assertEqual(m.parsed.episodes, list(range(1, 13)))
        self.assertTrue(m.parsed.is_range)

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

        self.assertEqual(len(DEFAULT_CUSTOM_FORMATS), len(DEFAULT_FORMAT_NAMES))
        self.assertIn("SDTV-480p", DEFAULT_FORMAT_NAMES)
        self.assertIn("Bluray-480p", DEFAULT_FORMAT_NAMES)
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

    def test_create_custom_format_auto_regex_and_update(self):
        try:
            from sqlalchemy import create_engine
            from sqlalchemy.orm import sessionmaker
            from app.models.db import Base, CustomFormat, User
            from app.schemas import CustomFormatCreate, CustomFormatUpdate
            from app.api.custom_formats_routes import create_custom_format, update_custom_format
        except ImportError:
            self.skipTest("sqlalchemy or app dependencies not installed in current test environment")

        test_engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(test_engine)
        TestSession = sessionmaker(bind=test_engine)
        db = TestSession()

        dummy_user = User(
            username="admin",
            password_hash="dummy_hash",
            is_admin=True,
            is_owner=True,
            enabled=True,
            permissions={"manage_settings": True},
        )

        # 1. Create format with only name and score (no regex specified)
        payload1 = CustomFormatCreate(name="LostFilm", score=200)
        cf1 = create_custom_format(payload1, db=db, current_user=dummy_user)
        self.assertEqual(cf1.name, "LostFilm")
        self.assertEqual(cf1.score, 200)
        self.assertTrue(len(cf1.specifications) > 0)
        self.assertIn(r"\bLostFilm\b", cf1.specifications[0]["fields"]["value"])

        # 2. Resubmitting with same name (case-insensitive) should update score instead of raising 400
        payload2 = CustomFormatCreate(name="lostfilm", score=350)
        cf2 = create_custom_format(payload2, db=db, current_user=dummy_user)
        self.assertEqual(cf2.id, cf1.id)
        self.assertEqual(cf2.score, 350)

        # 3. Update format via PUT
        update_payload = CustomFormatUpdate(score=500)
        cf3 = update_custom_format(cf1.id, update_payload, db=db, current_user=dummy_user)
        self.assertEqual(cf3.score, 500)

        db.close()

    def test_is_non_video_release_manga_and_light_novels(self):
        from app.services.matcher import is_non_video_release

        non_video_titles = [
            "TACHIBANA Pan, KATSURAI Yoshiaki - だから僕は、Hができない。/ Dakara Boku wa, H ga Dekinai. / Говорю же, я не извращенец! (комедия, мистика, романтика, этти) [тома 1-11] [2010, EPUB, JPN] [complete] [японский]",
            "Dakara Boku wa, H ga Dekinai [Light Novel] [Vol 1-11]",
            "Hell Mode [Manga] [Vols 01-08] [CBZ]",
            "Sword Art Online [Ранобэ] [Тома 01-26] [FB2]",
            "Berserk [Манга] [Тома 1-41] [PDF]",
            "Attack on Titan [Artbook] [2018] [Scans]",
        ]

        for t in non_video_titles:
            self.assertTrue(is_non_video_release(t), f"Релиз должен быть распознан как не-видео контент: {t}")

        video_titles = [
            "Говорю же, я не извращенец! | Dakara Boku wa, H ga Dekinai. | So, I Can't Play H! [TV + OVA] [1-12+1 из 12+1] [2012] [BDRip] [1080p]",
            "Адский режим: Хардкорный геймер отправляется в другой мир на высоком уровне сложности 2 / E01-E09 Hell Mode [WEBRip 1080p][AVC][1-9] RUS",
        ]

        for t in video_titles:
            self.assertFalse(is_non_video_release(t), f"Видео-релиз НЕ должен помечаться как не-видео: {t}")

    def test_gto_dorama_year_mismatch_and_alias_splitting(self):
        from app.services.matcher import match_release, build_alias_candidates, AliasCandidate

        class MockShow:
            def __init__(self, title, year=1999, content_type="anime"):
                self.id = 10
                self.title = title
                self.year = year
                self.content_type = content_type
                self.aliases = []

        class MockAlias:
            def __init__(self, text):
                self.id = 1
                self.text = text
                self.language = "ru"
                self.priority = 100

        # 1. Проверяем расщепление составного алиаса
        show = MockShow("Great Teacher Onizuka", year=1999, content_type="anime")
        show.aliases = [MockAlias("Крутой учитель Онидзука / Great Teacher Onizuka / GTO")]

        candidates = build_alias_candidates(show)
        cand_texts = [c.text for c in candidates]
        self.assertIn("Great Teacher Onizuka", cand_texts)
        self.assertIn("Крутой учитель Онидзука", cand_texts)
        self.assertIn("GTO", cand_texts)

        # 2. Проверяем отсеивание дорамы 2012 года для аниме 1999 года
        t_dorama = "Великий Учитель Онидзука 2012 / GTO / GTO: Great Teacher Onizuka 2012 [11/11] [Япония, 2012, комедия, школа, DTVRip] [RAW] [VO] (SkomoroX)"
        t_anime = "[AniLibria] Крутой учитель Онидзука / Great Teacher Onizuka [01-43 из 43] [1999, WEBRip 1080p]"

        m_dorama = match_release(t_dorama, show.id, candidates, content_type="anime", show_year=show.year)
        m_anime = match_release(t_anime, show.id, candidates, content_type="anime", show_year=show.year)

        self.assertFalse(m_dorama.matched, "Дорама 2012 года НЕ должна матчиться с аниме 1999 года")
        self.assertTrue(m_anime.matched, "Аниме 1999 года должно успешно матчиться")

    def test_rezero_season4_complex_naming(self):
        from types import SimpleNamespace
        from app.services.parser import parse_episode, ReleaseKind

        aliases = [
            AliasCandidate(alias_id=1, text="Re: ZERO, Starting Life in Another World", language="en", priority=10),
            AliasCandidate(alias_id=2, text="Re:Zero — жизнь в альтернативном мире с нуля", language="ru", priority=20),
            AliasCandidate(alias_id=3, text="Re:Zero kara Hajimeru Isekai Seikatsu", language="ja", priority=30),
        ]

        test_titles = [
            "Re:Zero — жизнь в альтернативном мире с нуля (ТВ-4)",
            "Re:Zero kara Hajimeru Isekai Seikatsu 4th Season",
            "Re:ZERO -Starting Life in Another World- Season 4",
            "Re:Zero — жизнь в альтернативном мире с нуля (ТВ-4) / Re:Zero kara Hajimeru Isekai Seikatsu 4th Season | Re:ZERO -Starting Life in Another World- Season 4",
        ]

        for t in test_titles:
            m = match_release(t, 77, aliases, content_type="anime")
            self.assertTrue(m.matched, f"Failed to match: {t}")
            p = parse_episode(t)
            self.assertEqual(p.kind, ReleaseKind.SEASON_PACK, f"Wrong kind for: {t}")
            self.assertEqual(p.seasons, [4], f"Wrong season for: {t}")

    def test_rezero_season3_rutracker_composite_and_later_year(self):
        from app.services.parser import parse_episode, ReleaseKind

        aliases = [
            AliasCandidate(alias_id=1, text="Re: ZERO, Starting Life in Another World", language="en", priority=10),
            AliasCandidate(alias_id=2, text="Re:Zero — жизнь в альтернативном мире с нуля", language="ru", priority=20),
            AliasCandidate(alias_id=3, text="Re:Zero kara Hajimeru Isekai Seikatsu", language="ja", priority=30),
        ]

        title = "Re:Zero — жизнь с нуля в другом мире (ТВ-3) / Re:Zero kara Hajimeru Isekai Seikatsu 3 / Re: Zero - Starting Life in Another World 3rd Season / С нуля: пособие по выживанию в альтернативном мире 3 [TV] [16 из 16] [RUS(int), JAP+Sub] [2024, приключения, фэнтези, BDRip] [1080p]"

        # Проверяем, что релиз 2024 года не блокируется для аниме 2016 года (так как это 3-й сезон)
        m = match_release(title, 77, aliases, content_type="anime", show_year=2016)
        self.assertTrue(m.matched, f"Failed to match RuTracker Season 3 title: {title}")
        self.assertEqual(m.score, 100.0)

        p = parse_episode(title)
        self.assertEqual(p.season, 3)
        self.assertEqual(p.episodes, list(range(1, 17)))

    def test_user_provided_complex_tracker_titles_suite(self):
        from app.services.parser import parse_episode, detect_season_label
        from app.services.matcher import is_non_video_release, match_release, AliasCandidate

        rezero_aliases = [
            AliasCandidate(1, "Re: ZERO, Starting Life in Another World"),
            AliasCandidate(2, "Re:Zero — жизнь в альтернативном мире с нуля"),
            AliasCandidate(3, "Re:Zero kara Hajimeru Isekai Seikatsu"),
            AliasCandidate(4, "Re: Жизнь в альтернативном мире с нуля"),
            AliasCandidate(5, "С нуля: пособие по выживанию в альтернативном мире"),
            AliasCandidate(6, "Re:Zero — жизнь с нуля в другом мире"),
        ]
        clevatess_aliases = [
            AliasCandidate(1, "Clevatess"),
            AliasCandidate(2, "Клеватесс: Король демонических зверей, младенец и герой-нежить"),
            AliasCandidate(3, "Клеватесс"),
        ]
        tabakoshka_aliases = [
            AliasCandidate(1, "Yani Neko"),
            AliasCandidate(2, "Табакошка"),
            AliasCandidate(3, "Chainsmoker Cat"),
        ]
        tsugai_aliases = [
            AliasCandidate(1, "Yomi no Tsugai"),
            AliasCandidate(2, "Цугаи загробного мира"),
            AliasCandidate(3, "Daemons of the Shadow Realm"),
        ]

        # 1. Проверка видео-релизов (корректный сезон, серии и 100% совпадение)
        video_cases = [
            ("Re:Zero — жизнь с нуля в другом мире (ТВ-4) / Re:Zero kara Hajimeru Isekai Seikatsu 4 / Re:Zero - Starting Life in Another World 4th Season [TV] [01-15 из 19] [RUS(ext), JAP+Sub] [2026, фэнтези, драма, WEB-DL] [1080p]", rezero_aliases, 4, [1, 15], 2016),
            ("Re:Zero — жизнь с нуля в другом мире (ТВ-4) / Re:Zero kara Hajimeru Isekai Seikatsu 4 / Re:Zero - Starting Life in Another World / С нуля: пособие по выживанию в альтернативном мире 4 [TV] [1-14 из 19] [RUS(int), JAP+Sub] [2026, фэнтези, драма, WEB-DL] [1080p] [Локализованный видеоряд]", rezero_aliases, 4, [1, 14], 2016),
            ("Re:Zero — жизнь с нуля в другом мире (ТВ-4) / Re:Zero kara Hajimeru Isekai Seikatsu 4 / Re:Zero - Starting Life in Another World 4th Season / Re: Жизнь в альтернативном мире с нуля 4 [TV] [01-11 из 19] [RUS(int), JAP+Sub] [2026, приключения, фэнтези, драма, WEBRip] [HWP]", rezero_aliases, 4, [1, 11], 2016),
            ("Re:Zero — жизнь с нуля в другом мире (ТВ-2, часть 2) / Re:Zero kara Hajimeru Isekai Seikatsu 2 / Re:Zero - Starting Life in Another World 2nd Season Part 2 / С нуля: пособие по выживанию в альтернативном мире 2 [TV] [12 из 12] [RUS(ext), JAP+Sub] [2021, фэнтези, приключения, драма, BDRip] [1080p]", rezero_aliases, 2, [1, 12], 2016),
            ("Клеватесс (ТВ-2): Король демонических зверей и легенда о ложном герое / Clevatess II: Majuu no Ou to Itsuwari no Yuusha Denshou [TV] [01-08 из 13] [RUS(int), ENG, JAP+Sub] [2026, Фэнтези, WEB-DL] [1080p]", clevatess_aliases, 2, [1, 8], 2025),
            ("Табакошка / Yani Neko / Chainsmoker Cat [TV] [01-08 из XX] [RUS(int), JAP+Sub] [2026, Сэйнэн, Комедия, WEB-DL] [1080p]", tabakoshka_aliases, 1, [1, 8], 2026),
            ("Цугаи загробного мира / Yomi no Tsugai / Daemons of the Shadow Realm [TV] [1-21 из 24] [JAP+Sub] & [1-12 из 24] [RUS(int)] & [1-21 из 24] [RUS(ext)] [2026, приключения, фэнтези, сёнэн, WEB-DL] [1080p]", tsugai_aliases, 1, [1, 21], 2026),
        ]

        for title, aliases, exp_s, exp_eps, s_year in video_cases:
            self.assertFalse(is_non_video_release(title), f"False positive non-video: {title}")
            m = match_release(title, 1, aliases, content_type="anime", show_year=s_year)
            self.assertTrue(m.matched, f"Failed to match title: {title}")
            p = parse_episode(title)
            lbl = detect_season_label(title)
            actual_season = p.season or (lbl.get("season") if lbl["type"] == "numbered" else 1)
            self.assertEqual(actual_season, exp_s, f"Wrong season for {title}")
            self.assertEqual([min(p.episodes), max(p.episodes)], exp_eps, f"Wrong episodes for {title}")

        # 2. Проверка не-видео контента (ранобэ, манга, аудиокниги, звуковые дорожки, игры, обои)
        non_video_cases = [
            "NAGATSUKI Tappei, OOTSUKA Shinichirou - Re:Zero − Starting Life in Another World / Re:Zero kara Hajimeru Isekai Seikatsu (триллер, фэнтези, драма) [тома 1-29, 1-6 EX, 1-5 Short Stories] [2014, EPUB, ENG] [incomplete]",
            "Re:Zero — жизнь с нуля в другом мире (ТВ-3) / Re:Zero kara Hajimeru Isekai Seikatsu 3 / Re: Zero - Starting Life in Another World 3rd Season / С нуля: пособие по выживанию в альтернативном мире 3 [TV] [16 из 16] [RUS(Dub)] [2024, ААС]",
            "Re: Жизнь в альтернативном мире с нуля / Re:Zero kara Hajimeru Isekai Seikatsu / Re:Zero -Starting Life in Another World- / ゼロから始める異世界生活 (21 релиз) (Kenichiro Suehiro), 2016-2025, MP3 (tracks), 320 kbps",
            "Re:ZERO Starting Life in Another World - The Prophecy of the Throne (The False Royal Election Candidate) [NSP][RUS (Mod.)/ENG]",
            "Нагацуки Таппэй - Re: Zero kara Hajimeru Isekai Seikatsu / Жизнь в альтернативном мире с нуля 3 [NoName, (ЛИ), 2021, 160 kbps, MP3]",
            "Re:ZERO -Starting Life in Another World- The Prophecy of the Throne [P] [ENG + 3 / ENG + JPN] (2021, TBS) (1.0) [Scene]",
            "Re:Zero kara Hajimeru Isekai Seikatsu / Starting Life in Another World / Жизнь в альтернативном мире с нуля [Art] [2020] [JPG]",
            "Tappei Nagatsuki/Таппэй Нагацуки - RE Zero. Жизнь с нуля в альтернативном мире/Re:Zero kara Hajimeru Isekai Seikatsu (фэнтези, приключения) [тома 1-6] [2014, FB2/EPUB/DOCX, RUS] [incomplete]",
            "Nyan Nyan Factory - Табакошка / Yani Neko / Chainsmoker Cat / Tar Cat [manga] [Vol. 5-9] [2023, Comedy, Psychological, Slice of Life] [incomplete]",
            "Цугаи загробного мира / Yomi no Tsugai / Daemons of the Shadow Realm [TV] [1-21 из 24] [RUS(2*Dub, 2*MVO)] [2026, ААС]",
        ]

        for nv_title in non_video_cases:
            self.assertTrue(is_non_video_release(nv_title), f"Failed to detect non-video: {nv_title}")


if __name__ == "__main__":
    unittest.main()


