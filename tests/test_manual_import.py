import os
import tempfile
import unittest
from unittest.mock import MagicMock

from app.services.parser import parse_episode, ReleaseKind
from app.services.quality import parse_quality
from app.services.matcher import match_release, best_alias_match, AliasCandidate
from app.services.postprocess import (
    find_release_files,
    render_episode_template,
    render_season_folder_template,
    match_companion_files_for_episode,
)


class TestManualImportLogic(unittest.TestCase):
    def test_filename_episode_and_quality_parsing(self):
        # 1. Anime absolute numbering
        name1 = "[SubsPlease] Naruto - 04 (1080p) [x265].mkv"
        p1 = parse_episode(name1)
        q1 = parse_quality(name1)
        self.assertEqual(p1.kind, ReleaseKind.ABSOLUTE)
        self.assertEqual(p1.episodes, [4])
        self.assertEqual(q1.resolution, "1080p")
        self.assertEqual(q1.video_codec, "HEVC")

        # 2. Series SxxExx
        name2 = "Stranger.Things.S04E01.Chapter.One.1080p.NF.WEB-DL.DDP5.1.Atmos.x264-FLUX.mkv"
        p2 = parse_episode(name2)
        q2 = parse_quality(name2)
        self.assertEqual(p2.kind, ReleaseKind.EPISODE)
        self.assertEqual(p2.season, 4)
        self.assertEqual(p2.episodes, [1])
        self.assertEqual(q2.name, "WEBDL-1080p")
        self.assertEqual(q2.audio_codec, "Atmos")

    def test_matcher_with_show_aliases(self):
        aliases = [
            AliasCandidate(alias_id=1, text="Naruto", language="en", priority=0),
            AliasCandidate(alias_id=2, text="Наруто", language="ru", priority=1),
            AliasCandidate(alias_id=3, text="NARUTO -ナルト-", language="ja", priority=2),
        ]
        res = match_release("[SubsPlease] Naruto - 04 (1080p) [x265].mkv", 1, aliases, content_type="anime")
        self.assertTrue(res.matched)
        self.assertGreater(res.score, 80)

        best, score = best_alias_match("Наруто.S01E04.1080p.mkv", aliases)
        self.assertIsNotNone(best)
        self.assertEqual(best.alias_id, 2)
        self.assertGreater(score, 70)

        res_ru = match_release("Наруто.S01E04.1080p.mkv", 1, aliases, content_type="anime")
        self.assertTrue(res_ru.matched)

    def test_render_templates_for_import(self):
        season_folder = render_season_folder_template("Season {season:02d}", season=1, show_title="Naruto")
        self.assertEqual(season_folder, "Season 01")

        dest_stem = render_episode_template(
            "{Series Title} - S{season:02d}E{episode:02d} - {Episode Title}",
            show_title="Naruto",
            season=1,
            episode=4,
            episode_title="Pass or Fail",
            quality="WEBDL-1080p",
        )
        self.assertEqual(dest_stem, "Naruto - S01E04 - Pass or Fail")

    def test_companion_subtitles_match(self):
        subs = [
            "/downloads/Naruto/Naruto.S01E04.rus.srt",
            "/downloads/Naruto/Naruto.S01E04.eng.ass",
            "/downloads/Naruto/Naruto.S01E05.rus.srt",
        ]
        matched = match_companion_files_for_episode(
            companion_files=subs,
            ep_num=4,
            season_num=1,
            video_fpath="/downloads/Naruto/Naruto.S01E04.mkv",
            total_video_count=1,
        )
        self.assertEqual(len(matched), 2)
    def test_custom_formats_quality_list(self):
        from app.services.custom_formats import DEFAULT_CUSTOM_FORMATS, evaluate_custom_format
        from app.services.language_parser import parse_languages
        from app.services.release_group_parser import parse_release_group

        cf_dict = {item["name"]: MagicMock(name=item["name"], specifications=item["specifications"]) for item in DEFAULT_CUSTOM_FORMATS}
        
        # Test each format evaluates
        test_cases = [
            ("SDTV", "My.Show.S01E01.SDTV.x264.mkv"),
            ("DVD", "My.Show.S01E01.DVD.PAL.mkv"),
            ("DVDRip", "My.Show.S01E01.DVDRip.xvid.mkv"),
            ("HDTV-720p", "My.Show.S01E01.720p.HDTV.x264.mkv"),
            ("WEBRip-720p", "My.Show.S01E01.720p.WEBRip.x264.mkv"),
            ("WEBDL-720p", "My.Show.S01E01.720p.WEB-DL.x264.mkv"),
            ("Bluray-720p", "My.Show.S01E01.720p.BluRay.x264.mkv"),
            ("HDTV-1080p", "My.Show.S01E01.1080p.HDTV.x264.mkv"),
            ("WEBRip-1080p", "My.Show.S01E01.1080p.WEBRip.x264.mkv"),
            ("WEBDL-1080p", "My.Show.S01E01.1080p.WEB-DL.x264.mkv"),
            ("Bluray-1080p", "My.Show.S01E01.1080p.BluRay.x264.mkv"),
            ("Remux-1080p", "My.Show.S01E01.1080p.Remux.AVC.mkv"),
            ("HDTV-2160p", "My.Show.S01E01.2160p.HDTV.HEVC.mkv"),
            ("WEBRip-2160p", "My.Show.S01E01.2160p.WEBRip.HEVC.mkv"),
            ("WEBDL-2160p", "My.Show.S01E01.2160p.WEB-DL.HEVC.mkv"),
            ("Bluray-2160p", "My.Show.S01E01.2160p.BluRay.HEVC.mkv"),
            ("Remux-2160p", "My.Show.S01E01.2160p.UHD.Remux.HEVC.mkv"),
        ]

        for cf_name, release_title in test_cases:
            self.assertIn(cf_name, cf_dict, f"Custom format {cf_name} should exist in DEFAULT_CUSTOM_FORMATS")
            cf_mock = cf_dict[cf_name]
            cf_mock.name = cf_name
            quality = parse_quality(release_title)
            langs = parse_languages(release_title)
            rg = parse_release_group(release_title)
            matched = evaluate_custom_format(cf_mock, release_title, quality, langs, rg)
            self.assertTrue(matched, f"Custom format {cf_name} should match release '{release_title}' (parsed quality: {quality.name})")

        removed_cf = ["Dolby Vision", "HDR10+", "HDR10", "Lossless Audio (FLAC / TrueHD / Atmos / DTS-HD)", "Proper / Repack"]
        for r_name in removed_cf:
            self.assertNotIn(r_name, cf_dict, f"Custom format {r_name} should NOT exist in DEFAULT_CUSTOM_FORMATS")

    def test_manual_import_task_tracking(self):
        from app.services.task_manager import task_manager

        with task_manager.track_sync(
            name="manual_import",
            title="Ручной импорт: Lucifer",
            message="Импорт 5 файлов...",
            progress=0.0,
        ) as m_task:
            status = task_manager.get_status()
            self.assertEqual(len(status["running"]), 1)
            self.assertEqual(status["running"][0]["name"], "manual_import")
            self.assertEqual(status["running"][0]["title"], "Ручной импорт: Lucifer")

            m_task.update(message="Обработка (3/5): Lucifer.S01E03.1080p.mkv", progress=0.6)
            status_mid = task_manager.get_status()
            self.assertEqual(status_mid["running"][0]["progress"], 0.6)

    def test_find_release_files_discovers_all_video_formats_and_extras(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create various video formats in folder
            files_to_create = [
                "Show.S01E01.mkv",
                "Show.S01E02.mp4",
                "Show.S01E03.m4v",
                "Show.S01E04.wmv",
                "Show.S01E05.avi",
                "Show.S01E06.ts",
                "Show.S01E07.m2ts",
                "Show.S01E08.flv",
                "Show.S01E09.Sample.Life.mkv",  # Contains 'Sample'
                "Show.S01E10.Limited.Edition.mkv",  # Contains 'Edition' / 'ed'
                "Show.S01E11.Special.Ops.mkv",  # Contains 'Special' / 'op'
            ]
            for fn in files_to_create:
                fpath = os.path.join(tmpdir, fn)
                with open(fpath, "wb") as f:
                    f.write(b"fake video data")

            # Nested folder with Season 2
            s2_dir = os.path.join(tmpdir, "Season 02")
            os.makedirs(s2_dir, exist_ok=True)
            with open(os.path.join(s2_dir, "01.mkv"), "wb") as f:
                f.write(b"s2 ep 1")
            with open(os.path.join(s2_dir, "02.mkv"), "wb") as f:
                f.write(b"s2 ep 2")

            release_files = find_release_files(tmpdir)
            all_found = release_files["video"] + release_files["extras"]
            self.assertEqual(len(all_found), 13)

    def test_natural_sort_key(self):
        from app.services.postprocess import natural_sort_key
        items = ["Ep 1.mkv", "Ep 10.mkv", "Ep 2.mkv", "Ep 20.mkv", "Ep 3.mkv"]
        items.sort(key=natural_sort_key)
        self.assertEqual(items, ["Ep 1.mkv", "Ep 2.mkv", "Ep 3.mkv", "Ep 10.mkv", "Ep 20.mkv"])

    def test_log_audit_flexibility(self):
        from app.services.audit_service import log_audit
        db_mock = MagicMock()
        # 1. Calling with positional description
        entry1 = log_audit(db_mock, "manual_import", "Импортировано 5 файлов", username="admin")
        self.assertIsNotNone(entry1)
        self.assertEqual(entry1.description, "Импортировано 5 файлов")

        # 2. Calling with details as string
        entry2 = log_audit(db_mock, "manual_import", username="admin", details="Импортировано 3 файла")
        self.assertIsNotNone(entry2)
        self.assertEqual(entry2.description, "Импортировано 3 файла")


    def test_movie_manual_import_rendering(self):
        from app.services.postprocess import render_movie_template
        res = render_movie_template(
            "{Movie Title} ({Release Year}) {Quality Full}",
            show_title="Star Wars: Episode IV - A New Hope",
            year=1977,
            quality="Bluray-1080p",
        )
    def test_copy_and_move_file_with_progress(self):
        from app.services.postprocess import copy_file_with_progress, move_file_with_progress

        with tempfile.TemporaryDirectory() as tmpdir:
            src_file = os.path.join(tmpdir, "source.mkv")
            dst_copy = os.path.join(tmpdir, "dest_copy.mkv")
            dst_move = os.path.join(tmpdir, "dest_move.mkv")

            # 10 MB file
            data = b"X" * (10 * 1024 * 1024)
            with open(src_file, "wb") as f:
                f.write(data)

            # Test copy with progress
            progress_calls = []
            def _cb(copied, total):
                progress_calls.append((copied, total))

            copy_file_with_progress(src_file, dst_copy, callback=_cb, chunk_size=2 * 1024 * 1024)
            self.assertTrue(os.path.exists(dst_copy))
            self.assertEqual(os.path.getsize(dst_copy), 10 * 1024 * 1024)
            self.assertGreater(len(progress_calls), 1)
            self.assertEqual(progress_calls[-1], (10 * 1024 * 1024, 10 * 1024 * 1024))

            # Test move with progress
            move_progress_calls = []
            def _move_cb(copied, total):
                move_progress_calls.append((copied, total))

            move_file_with_progress(dst_copy, dst_move, callback=_move_cb)
            self.assertTrue(os.path.exists(dst_move))
            self.assertFalse(os.path.exists(dst_copy))
            self.assertEqual(len(move_progress_calls), 2)
            self.assertEqual(move_progress_calls[-1], (10 * 1024 * 1024, 10 * 1024 * 1024))

    def test_deleted_file_resets_quality_and_status(self):
        """Проверяет, что при отсутствии файла на диске сбрасывается ярлык качества (downloaded_quality) и статус."""
        try:
            from app.api.shows import get_show, list_episodes
        except ImportError:
            self.skipTest("FastAPI not installed in test runner")
            return

        from types import SimpleNamespace
        from unittest.mock import MagicMock

        show = SimpleNamespace(id=1, title="Test Anime", content_type="anime", monitored=True, premiere_date=None, path="/media/anime/Test Anime")
        ep1 = SimpleNamespace(
            id=101, show_id=1, season_number=1, episode_number=2, absolute_number=2,
            title="The Appraisal Ceremony", air_date=None, status="downloaded",
            downloaded_quality="SDTV", file_path="/non/existent/path/S01E02.mkv",
            download_progress=1.0, video_codec="x264", audio_codec="AAC",
            audio_channels="2.0", dynamic_range=None, release_group=None,
            file_size_bytes=1000000, monitor_status="monitored",
        )
        show.episodes = [ep1]

        db_mock = MagicMock()
        db_mock.get.return_value = show
        db_mock.query.return_value.filter.return_value.all.return_value = [ep1]
        db_mock.query.return_value.filter.return_value.order_by.return_value.all.return_value = [ep1]
        db_mock.query.return_value.filter.return_value.group_by.return_value.all.return_value = []

        current_user = SimpleNamespace(id=1, username="admin")

        # 1. Test get_show
        res_show = get_show(1, db=db_mock, current_user=current_user)
        self.assertIsNone(ep1.downloaded_quality)
        self.assertIsNone(ep1.file_path)
        self.assertEqual(ep1.status, "wanted")
        self.assertEqual(ep1.download_progress, 0.0)

        # 2. Test list_episodes
        ep1.downloaded_quality = "SDTV"
        ep1.file_path = "/non/existent/path/S01E02.mkv"
        res_eps = list_episodes(1, db=db_mock, current_user=current_user)
        self.assertEqual(len(res_eps), 1)
        self.assertFalse(res_eps[0].has_file)
        self.assertIsNone(res_eps[0].downloaded_quality)
        self.assertIsNone(res_eps[0].file_path)


if __name__ == "__main__":
    unittest.main()

