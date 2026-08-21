"""
Тесты компонентов, портированных из Sonarr:
- LanguageParser (LanguageParser.cs)
- ReleaseGroupParser (ReleaseGroupParser.cs)
- Quality & Codec Parser (QualityModel.cs / QualityParser.cs)
- CustomFormats (CustomFormatCalculationService.cs)
- DecisionEngine (DecisionEngine specifications)
- FileNameBuilder (Organizer / FileNameBuilder.cs)
"""

import unittest
from app.services.language_parser import Language, get_language_badges, parse_languages
from app.services.quality import QualityInfo, is_allowed, parse_quality
from app.services.release_group_parser import parse_release_group
from app.services.organizer import FileNameBuilder, clean_title, title_the


class TestSonarrPorts(unittest.TestCase):

    def test_language_parser(self):
        # Русский
        langs = parse_languages("The.Boys.S04E01.1080p.RUS.LostFilm")
        self.assertIn(Language.RUSSIAN, langs)
        badges = get_language_badges(langs)
        self.assertIn("RU", badges)

        # Японский + Мульти
        langs2 = parse_languages("[SubsPlease] Frieren - 28 (1080p) [Multi-Audio] [Dual Audio] [JAP+ENG]")
        self.assertIn(Language.JAPANESE, langs2)
        self.assertIn(Language.ENGLISH, langs2)
        self.assertIn(Language.DUAL, langs2)

    def test_release_group_parser(self):
        # Anime anime brackets
        grp1 = parse_release_group("[SubsPlease] Jujutsu Kaisen - 24 [1080p].mkv")
        self.assertEqual(grp1, "SubsPlease")

        # Scene trailing
        grp2 = parse_release_group("House.of.the.Dragon.S02E01.1080p.WEB-DL-FLUX")
        self.assertEqual(grp2, "FLUX")

        # Russian release studio
        grp3 = parse_release_group("Stranger Things [04x01-09] (2022) WEB-DL 1080p | LostFilm")
        self.assertEqual(grp3, "LostFilm")

        grp4 = parse_release_group("The.Bear.S03E01.1080p.HDRezka.mkv")
        self.assertEqual(grp4, "HDRezka")

    def test_quality_and_codecs(self):
        q1 = parse_quality("Severance.S01E01.2160p.ATVP.WEB-DL.DDP5.1.Atmos.DV.HDR.HEVC-FLUX")
        self.assertEqual(q1.resolution, "2160p")
        self.assertEqual(q1.source, "WEBDL")
        self.assertEqual(q1.name, "WEBDL-2160p")
        self.assertEqual(q1.video_codec, "HEVC")
        self.assertEqual(q1.dynamic_range, "DV HDR")
        self.assertTrue(q1.rank >= 12)

        q2 = parse_quality("Breaking.Bad.S05E16.1080p.BluRay.Remux.AVC.TrueHD.7.1-Group")
        self.assertEqual(q2.name, "Remux-1080p")
        self.assertEqual(q2.source, "Remux")
        self.assertEqual(q2.audio_codec, "TrueHD")

        q3 = parse_quality("Show.Title.S01E01.PROPER.1080p.WEBDL")
        self.assertEqual(q3.modifier, "Proper")

    def test_quality_allowed(self):
        q = parse_quality("Show.S01E01.1080p.WEB-DL")
        self.assertTrue(is_allowed(q, ["WEBDL-1080p", "Bluray-1080p"]))
        self.assertFalse(is_allowed(q, ["SDTV", "DVD"]))
        self.assertTrue(is_allowed(q, []))  # Пустой список = любое

    def test_organizer_filename_builder(self):
        q = QualityInfo(name="Bluray-1080p", resolution="1080p", source="Bluray", rank=9, modifier="Proper", video_codec="x264", audio_codec="FLAC")
        
        name = FileNameBuilder.build_file_name(
            template="{Series Title} - S{season:00}E{episode:00} - {Episode Title} [{Quality Full}] [{Release Group}]",
            title="Attack on Titan",
            season_number=1,
            episode_number=5,
            episode_title="First Battle",
            quality=q,
            release_group="LostFilm",
            content_type="series",
            extension=".mkv",
        )
        self.assertEqual(name, "Attack on Titan - S01E05 - First Battle [Bluray-1080p Proper] [LostFilm].mkv")

        # Movie template
        movie_name = FileNameBuilder.build_file_name(
            template="{Movie Title} ({Release Year}) [{Quality Full}]",
            title="Inception",
            year=2010,
            quality=q,
            content_type="movie",
            extension=".mkv",
        )
        self.assertEqual(movie_name, "Inception (2010) [Bluray-1080p Proper].mkv")

    def test_clean_title_and_the(self):
        self.assertEqual(clean_title("The Flash: Rebirth (2023)!"), "The Flash Rebirth 2023")
        self.assertEqual(title_the("The Walking Dead"), "Walking Dead, The")
        self.assertEqual(title_the("A Quiet Place"), "Quiet Place, A")

    def test_skyhook_client_instantiation(self):
        from app.services.metadata import SkyHookClient, extract_skyhook_poster
        client = SkyHookClient()
        self.assertEqual(client.base_url, "https://skyhook.sonarr.tv/v1/tvdb")
        self.assertEqual(client.RADARR_URL, "https://radarr.servarr.com/v1/api")

        # Test poster extraction
        images = [
            {"coverType": "Banner", "url": "banners/123.jpg"},
            {"coverType": "Poster", "url": "posters/456.jpg"},
        ]
        poster = extract_skyhook_poster(images)
        self.assertEqual(poster, "https://artworks.thetvdb.com/posters/456.jpg")

    def test_parse_release_age_and_date(self):
        from app.services.indexer_service import _parse_release_age_and_date
        import datetime as dt

        # RFC 2822
        iso, age = _parse_release_age_and_date("Wed, 19 Aug 2026 12:00:00 +0000")
        self.assertIsNotNone(iso)

        # Datetime object
        now = dt.datetime.utcnow() - dt.timedelta(days=3, hours=12)
        iso2, age2 = _parse_release_age_and_date(now)
        self.assertIsNotNone(iso2)
        self.assertAlmostEqual(age2, 3.5, delta=0.2)

    def test_selective_download_priority_season_and_episodes(self):
        from dataclasses import dataclass
        from typing import Optional
        from app.services.auto_search import evaluate_torrent_file_priority

        @dataclass
        class MockEpisode:
            id: int
            show_id: int
            season_number: int
            episode_number: int
            absolute_number: Optional[int] = None

        ep1 = MockEpisode(id=1, show_id=10, season_number=1, episode_number=1, absolute_number=1)
        ep2 = MockEpisode(id=2, show_id=10, season_number=1, episode_number=2, absolute_number=2)
        ep3 = MockEpisode(id=3, show_id=10, season_number=1, episode_number=3, absolute_number=3)

        target_season_1 = [ep1, ep2, ep3]

        # 1. Видеофайлы сезона 1 должны быть приоритет 1
        prio_s1e1 = evaluate_torrent_file_priority("Naruto.S01E01.1080p.mkv", 0, target_season_1)
        prio_s1e2 = evaluate_torrent_file_priority("Naruto - 02 (1080p).mkv", 1, target_season_1)
        self.assertEqual(prio_s1e1, 1)
        self.assertEqual(prio_s1e2, 1)

        # 2. Видеофайлы сезона 2 из того же пака должны быть приоритет 0 (не качать)
        prio_s2e1 = evaluate_torrent_file_priority("Naruto.S02E01.1080p.mkv", 2, target_season_1)
        prio_s3e5 = evaluate_torrent_file_priority("Naruto.S03E05.1080p.mkv", 3, target_season_1)
        self.assertEqual(prio_s2e1, 0)
        self.assertEqual(prio_s3e5, 0)

        # 3. Субтитры к сезону 1 должны быть приоритет 1
        prio_sub_s1 = evaluate_torrent_file_priority("Subs/Naruto.S01E01.rus.ass", 4, target_season_1)
        self.assertEqual(prio_sub_s1, 1)

        # 4. Субтитры к сезону 2 должны быть приоритет 0
        prio_sub_s2 = evaluate_torrent_file_priority("Subs/Naruto.S02E01.rus.ass", 5, target_season_1)
        self.assertEqual(prio_sub_s2, 0)

        # 5. Шрифты (Fonts) должны быть приоритет 1 для стилизации субтитров
        prio_font = evaluate_torrent_file_priority("Fonts/AnimeFont.ttf", 6, target_season_1)
        self.assertEqual(prio_font, 1)

        # 6. Внешние аудиодорожки к сезону 1 (LostFilm .mka)
        prio_audio_s1 = evaluate_torrent_file_priority("Audio/Naruto.S01E02.rus.LostFilm.mka", 7, target_season_1)
        prio_audio_s2 = evaluate_torrent_file_priority("Audio/Naruto.S02E02.rus.LostFilm.mka", 8, target_season_1)
        self.assertEqual(prio_audio_s1, 1)
        self.assertEqual(prio_audio_s2, 0)

        # 7. Выбор только конкретной серии (например ep2)
        target_only_ep2 = [ep2]
        self.assertEqual(evaluate_torrent_file_priority("Naruto.S01E01.1080p.mkv", 0, target_only_ep2), 0)
        self.assertEqual(evaluate_torrent_file_priority("Naruto.S01E02.1080p.mkv", 1, target_only_ep2), 1)
        self.assertEqual(evaluate_torrent_file_priority("Naruto.S01E03.1080p.mkv", 2, target_only_ep2), 0)

        # 8. Для фильмов: файлы со словами "Episode IV" или "Эпизод 4" не должны отключаться
        movie_ep = [MockEpisode(id=100, show_id=99, season_number=1, episode_number=1)]
        self.assertEqual(
            evaluate_torrent_file_priority("Star.Wars.Episode.IV.A.New.Hope.1977.2160p.mkv", 0, movie_ep, content_type="movie"),
            1,
        )
        self.assertEqual(
            evaluate_torrent_file_priority("Zvezdnye.Voiny.Epizod.4.1080p.mkv", 1, movie_ep, content_type="movie"),
            1,
        )
        self.assertEqual(
            evaluate_torrent_file_priority("Star.Wars.Episode.IV.rus.srt", 2, movie_ep, content_type="movie"),
            1,
        )

        # 9. Проверка _ensure_movie_files_wanted для фильма
        from unittest.mock import AsyncMock, MagicMock
        from app.services.auto_search import _ensure_movie_files_wanted
        from app.services.download_client import TorrentInfo, TorrentFile
        import asyncio

        mock_dl_client = MagicMock()
        mock_dl_client.get_torrent = AsyncMock(return_value=TorrentInfo(
            hash="abc1234",
            name="Star.Wars.Episode.IV.A.New.Hope.1977.2160p.UHD.BDRemux.mkv",
            progress=0.0,
            state="downloading",
            save_path="/data/movies",
            size=100_000_000_000,
            download_speed=0,
            upload_speed=0,
            files=[
                TorrentFile(index=0, name="Star.Wars.Episode.IV.A.New.Hope.1977.2160p.UHD.BDRemux.mkv", size=100_000_000_000, progress=0.0, priority=0),
                TorrentFile(index=1, name="Star.Wars.Episode.IV.rus.srt", size=100_000, progress=0.0, priority=0),
            ]
        ))
        mock_dl_client.set_file_priorities = AsyncMock()
        mock_dl_client.resume_torrent = AsyncMock()

        asyncio.run(_ensure_movie_files_wanted(mock_dl_client, "abc1234"))
        mock_dl_client.set_file_priorities.assert_awaited_once_with("abc1234", [0, 1], 1)
        mock_dl_client.resume_torrent.assert_awaited_once_with("abc1234")

    def test_extra_files_postprocess(self):
        from app.services.postprocess import SUBTITLE_EXTENSIONS, AUDIO_EXTENSIONS, FONT_EXTENSIONS, find_release_files
        self.assertIn(".ass", SUBTITLE_EXTENSIONS)
        self.assertIn(".srt", SUBTITLE_EXTENSIONS)
        self.assertIn(".mka", AUDIO_EXTENSIONS)
        self.assertIn(".ttf", FONT_EXTENSIONS)
        self.assertIn(".otf", FONT_EXTENSIONS)

    def test_decision_engine_season_matching(self):
        from unittest.mock import MagicMock
        from app.services.decision_engine import DecisionEngine

        show = MagicMock()
        show.id = 1
        show.title = "Lucifer"
        show.content_type = "series"
        show.quality_profile_id = None
        show.aliases = [MagicMock(id=1, text="Люцифер", language=MagicMock(value="ru"), priority=1)]

        wanted_s1_episodes = [MagicMock(id=i, show_id=1, season_number=1, episode_number=i, absolute_number=None, status="wanted", file_path=None) for i in range(1, 14)]

        # Season 1 and packs covering S1 -> approved
        r1 = DecisionEngine.evaluate_release(db=None, title="Люцифер (S1E1-13 of 13) / Lucifer (2016) WEB-DL-1080p-AVC", show=show, episodes=wanted_s1_episodes)
        self.assertTrue(r1.approved, f"S1 release should be approved: {r1.rejections}")

        r2 = DecisionEngine.evaluate_release(db=None, title="Lucifer - S1 - rus 1080p WEBDL (LostFilm)", show=show, episodes=wanted_s1_episodes)
        self.assertTrue(r2.approved, f"S1 pack should be approved: {r2.rejections}")

        r3 = DecisionEngine.evaluate_release(db=None, title="Люцифер / Lucifer / S1-6E1-93 of 93", show=show, episodes=wanted_s1_episodes)
        self.assertTrue(r3.approved, f"S1-6 pack should be approved: {r3.rejections}")

        r4 = DecisionEngine.evaluate_release(db=None, title="Люцифер / Lucifer [S01-06] (2016-2021) HDRip, WEB-DL", show=show, episodes=wanted_s1_episodes)
        self.assertTrue(r4.approved, f"[S01-06] pack should be approved: {r4.rejections}")

        # Season 2 -> rejected for Season 1
        r_s2 = DecisionEngine.evaluate_release(db=None, title="Люцифер (S2E1-18 of 18) / Lucifer (2016) WEB-DL-1080p-AVC", show=show, episodes=wanted_s1_episodes)
        self.assertFalse(r_s2.approved)
        self.assertTrue(any("S02" in rej or "сезону" in rej for rej in r_s2.rejections))

        # Different movie Luzifer 2021 -> rejected
        r_luzifer = DecisionEngine.evaluate_release(db=None, title="Luzifer.2021.Al!ve.AG.BDRemux.1080p.mkv", show=show, episodes=wanted_s1_episodes)
        self.assertFalse(r_luzifer.approved)

        # Music album -> rejected
        r_music = DecisionEngine.evaluate_release(db=None, title="[32/384] Monte Kristo - The Girl Of Lucifer (12'' Maxi-Single) - 1985, WavPack", show=show, episodes=wanted_s1_episodes)
        self.assertFalse(r_music.approved)
        self.assertTrue(any("видео" in rej for rej in r_music.rejections))


if __name__ == "__main__":
    unittest.main()
