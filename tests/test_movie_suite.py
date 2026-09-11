from __future__ import annotations

import unittest
import os
import tempfile
import datetime as dt
from unittest.mock import patch, MagicMock, AsyncMock

try:
    from app.models.db import Show, Episode, EpisodeStatus, MovieCollection
except ImportError:
    class EpisodeStatus:
        UNAIRED = "unaired"
        MISSING = "missing"
        WANTED = "wanted"
        DOWNLOADING = "downloading"
        DOWNLOADED = "downloaded"

    class Show:
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)

    class Episode:
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)

    class MovieCollection:
        def __init__(self, **kwargs):
            self.shows = []
            for k, v in kwargs.items():
                setattr(self, k, v)

from app.services.parser import parse_movie_edition
from app.services.movie_merger import find_movie_parts, extract_part_number, merge_movie_parts
from app.services.postprocess import render_movie_template
from app.services.metadata import MetadataShowDetails, refresh_show_metadata


class TestMovieSuite(unittest.TestCase):

    # -------------------------------------------------------------------------
    # 1. MOVIE EDITIONS
    # -------------------------------------------------------------------------

    def test_parse_movie_editions(self):
        cases = [
            ("Avatar.Fire.and.Ash.2025.DIRECTORS.CUT.2160p.UHD.Remux.mkv", "Director's Cut"),
            ("Gladiator.II.2024.EXTENDED.EDITION.1080p.BluRay.x264.mkv", "Extended Edition"),
            ("Avengers.Endgame.2019.IMAX.Enhanced.2160p.DV.HDR.mkv", "IMAX Enhanced"),
            ("The.Lord.of.the.Rings.The.Fellowship.of.the.Ring.2001.SEE.1080p.mkv", "Special Extended Edition"),
            ("Basic.Instinct.1992.UNRATED.UNCUT.1080p.BluRay.mkv", "Unrated"),
            ("The.Godfather.1972.50th.Anniversary.REMASTERED.2160p.mkv", "Remastered"),
            ("Blade.Runner.1982.FINAL.CUT.2160p.BluRay.mkv", "Final Cut"),
            ("Seven.Samurai.1954.CRITERION.COLLECTION.1080p.mkv", "Criterion Collection"),
            ("The.Matrix.1999.THEATRICAL.CUT.1080p.mkv", "Theatrical Cut"),
            ("Inception.2010.1080p.BluRay.x264-SPARKS.mkv", None),
        ]
        for filename, expected_edition in cases:
            res = parse_movie_edition(filename)
            self.assertEqual(res, expected_edition, f"Failed for {filename}: expected {expected_edition}, got {res}")

    def test_render_movie_template_with_edition(self):
        template = "{Movie CleanTitle} ({Release Year}) {Edition} [{Quality Full}]"
        rendered = render_movie_template(
            template,
            movie_title="Avatar: Fire and Ash",
            movie_year=2025,
            quality_title="Bluray-2160p Remux",
            edition="Director's Cut",
            release_group="FraMeSToR",
        )
        self.assertIn("Director's Cut", rendered)
        self.assertIn("Avatar Fire and Ash", rendered)
        self.assertIn("2025", rendered)

        # When edition is None, {Edition} token is cleanly omitted without dangling spaces
        rendered_no_ed = render_movie_template(
            template,
            movie_title="Avatar: Fire and Ash",
            movie_year=2025,
            quality_title="Bluray-2160p Remux",
            edition=None,
        )
        self.assertNotIn("Director's Cut", rendered_no_ed)
        self.assertNotIn("{}", rendered_no_ed)
        self.assertIn("Avatar Fire and Ash (2025) [Bluray-2160p Remux]", rendered_no_ed)

    # -------------------------------------------------------------------------
    # 2. MULTI-PART MOVIE HANDLING & MERGER
    # -------------------------------------------------------------------------

    def test_find_movie_parts(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            # Create cd1 and cd2 files
            f1 = os.path.join(tmp_dir, "Titanic.1997.CD1.avi")
            f2 = os.path.join(tmp_dir, "Titanic.1997.CD2.avi")
            sample = os.path.join(tmp_dir, "Sample.avi")
            nfo = os.path.join(tmp_dir, "info.nfo")
            for path in (f1, f2, sample, nfo):
                with open(path, "w") as f:
                    f.write("content")

            parts = find_movie_parts(tmp_dir)
            self.assertEqual(len(parts), 2)
            self.assertEqual(parts[0], f1)
            self.assertEqual(parts[1], f2)

    def test_extract_part_number(self):
        self.assertEqual(extract_part_number("Movie.CD1.avi"), 1)
        self.assertEqual(extract_part_number("Movie.Part2.mkv"), 2)
        self.assertEqual(extract_part_number("Movie.Disk03.mp4"), 3)
        self.assertEqual(extract_part_number("SingleMovie.mkv"), None)

    @patch("app.services.movie_merger.shutil.which")
    @patch("app.services.movie_merger.subprocess.run")
    def test_merge_movie_parts_mkvmerge(self, mock_run, mock_which):
        mock_which.side_effect = lambda tool: "/usr/bin/" + tool if tool == "mkvmerge" else None
        mock_run.return_value = MagicMock(returncode=0, stdout="Success", stderr="")

        with tempfile.TemporaryDirectory() as tmp_dir:
            p1 = os.path.join(tmp_dir, "Movie.CD1.mkv")
            p2 = os.path.join(tmp_dir, "Movie.CD2.mkv")
            out_file = os.path.join(tmp_dir, "output", "Movie (2020).mkv")
            os.makedirs(os.path.dirname(out_file), exist_ok=True)
            for p in (p1, p2):
                with open(p, "w") as f:
                    f.write("data")

            def side_effect(*args, **kwargs):
                cmd = args[0]
                staging = cmd[2]  # -o <staging_path>
                with open(staging, "w") as sf:
                    sf.write("merged_data")
                return MagicMock(returncode=0, stdout="Merged", stderr="")

            mock_run.side_effect = side_effect

            res = merge_movie_parts([p1, p2], out_file)
            self.assertEqual(res, [out_file])
            self.assertTrue(os.path.exists(out_file))

    def test_merge_movie_parts_fallback(self):
        # When no merge tool is installed, falls back to Plex/Jellyfin naming standard: - part1.ext, - part2.ext
        with patch("app.services.movie_merger.is_merge_tool_available", return_value=False):
            with patch("app.services.movie_merger.os.link") as mock_link:
                res = merge_movie_parts(
                    ["/downloads/Movie.CD1.mkv", "/downloads/Movie.CD2.mkv"],
                    "/library/Movie (2020)/Movie (2020).mkv",
                )
                self.assertEqual(len(res), 2)
                self.assertIn("Movie (2020) - part1.mkv", res[0])
                self.assertIn("Movie (2020) - part2.mkv", res[1])

    # -------------------------------------------------------------------------
    # 3. GRANULAR RELEASE DATES & CALENDAR
    # -------------------------------------------------------------------------

    def test_granular_release_dates_in_metadata_and_refresh(self):
        show = Show(
            id=42,
            title="Dune: Part Two",
            year=2024,
            content_type="movie",
            metadata_id="movie:693134",
            metadata_source="radarr",
            overview="Dune sequel",
            poster_url=None,
            rating=8.5,
            genre="Sci-Fi",
            network="Warner Bros.",
            premiere_date=None,
            in_cinemas_date=None,
            digital_release_date=None,
            physical_release_date=None,
            collection_id=None,
            collection_order=None,
        )

        fake_details = MetadataShowDetails(
            external_id="movie:693134",
            title="Dune: Part Two",
            year=2024,
            content_type="movie",
            premiere_date="2024-03-01",
            in_cinemas_date="2024-03-01",
            digital_release_date="2024-04-16",
            physical_release_date="2024-05-14",
            edition="IMAX Enhanced",
            collection_tmdb_id=726871,
            collection_name="Dune Collection",
        )

        db_mock = MagicMock()
        db_mock.query.return_value.filter.return_value.first.return_value = None
        db_mock.query.return_value.filter.return_value.order_by.return_value.first.return_value = Episode(
            id=101, show_id=42, season_number=1, episode_number=1, title="Dune: Part Two", status=EpisodeStatus.WANTED, air_date=None,
        )

        with patch("app.services.metadata.RadarrClient.get_details", new=AsyncMock(return_value=fake_details)):
            import asyncio
            res = asyncio.run(refresh_show_metadata(db_mock, show))
            self.assertTrue(res.get("updated"))
            self.assertEqual(show.in_cinemas_date, dt.datetime(2024, 3, 1))
            self.assertEqual(show.digital_release_date, dt.datetime(2024, 4, 16))
            self.assertEqual(show.physical_release_date, dt.datetime(2024, 5, 14))

    # -------------------------------------------------------------------------
    # 4. MOVIE COLLECTIONS & FRANCHISES
    # -------------------------------------------------------------------------

    def test_movie_collection_model_and_parts(self):
        coll = MovieCollection(
            id=10,
            title="Avatar Collection",
            tmdb_collection_id=87096,
            overview="The Avatar movie series by James Cameron.",
        )
        m1 = Show(id=1, title="Avatar", year=2009, content_type="movie", collection_id=10, collection_order=1)
        m2 = Show(id=2, title="Avatar: The Way of Water", year=2022, content_type="movie", collection_id=10, collection_order=2)
        coll.shows = [m1, m2]

        self.assertEqual(coll.title, "Avatar Collection")
        self.assertEqual(len(coll.shows), 2)
    def test_sync_movie_disk_preserves_downloading_and_upgrading_status(self):
        try:
            from app.api.shows import sync_show_disk
        except ImportError:
            return

        with tempfile.TemporaryDirectory() as tmp_dir:
            f_path = os.path.join(tmp_dir, "Avatar.Fire.and.Ash.2025.HDTV.720p.mkv")
            with open(f_path, "w") as f:
                f.write("test_content")

            show = Show(id=1, title="Avatar: Fire and Ash", content_type="movie", path=tmp_dir)
            ep = Episode(
                id=1,
                show_id=1,
                season_number=1,
                episode_number=1,
                title="Avatar: Fire and Ash",
                status=EpisodeStatus.DOWNLOADING,
                download_progress=0.45,
                torrent_hash="abc123hash",
                file_path=f_path,
                upgrade_requested=True,
            )

            db_mock = MagicMock()
            db_mock.get.return_value = show
            db_mock.query.return_value.filter_by.return_value.all.return_value = [ep]
            db_mock.query.return_value.filter_by.return_value.order_by.return_value.first.return_value = None

            with patch("app.api.shows.get_or_create_settings") as mock_settings:
                mock_settings.return_value = MagicMock()
                res = sync_show_disk(show_id=1, db=db_mock, current_user=MagicMock())
                self.assertEqual(ep.status, EpisodeStatus.DOWNLOADING)
                self.assertEqual(ep.download_progress, 0.45)
                self.assertEqual(ep.file_path, f_path)

    def test_tmdb_collection_details_cache(self):
        import asyncio
        from app.services.metadata import TMDBClient, _COLLECTION_DETAILS_CACHE

        _COLLECTION_DETAILS_CACHE.clear()
        client = TMDBClient()

        fake_resp = MagicMock()
        fake_resp.json.return_value = {
            "id": 12345,
            "name": "Test Saga",
            "overview": "Overview of saga",
            "parts": [
                {"id": 101, "title": "Part 1", "release_date": "2020-01-01"},
                {"id": 102, "title": "Part 2", "release_date": "2022-01-01"},
            ],
        }
        fake_resp.raise_for_status = MagicMock()

        mock_client_instance = MagicMock()
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=None)
        mock_client_instance.get = AsyncMock(return_value=fake_resp)

        mock_httpx = MagicMock()
        mock_httpx.AsyncClient.return_value = mock_client_instance

        with patch("app.services.metadata.httpx", mock_httpx):
            res1 = asyncio.run(client.get_collection_details(12345))
            self.assertEqual(res1["name"], "Test Saga")
            self.assertEqual(len(res1["parts"]), 2)
            self.assertEqual(mock_client_instance.get.call_count, 1)

            # Second call should use cache and not call httpx get again
            res2 = asyncio.run(client.get_collection_details(12345))
            self.assertEqual(res2["name"], "Test Saga")
            self.assertEqual(mock_client_instance.get.call_count, 1)

    def test_get_collection_detail_fallback_on_shows(self):
        try:
            import fastapi
            from app.api.collections_routes import get_collection_detail
        except ImportError:
            return

        import asyncio

        coll = MovieCollection(
            id=77,
            title="Devilman Saga",
            tmdb_collection_id=99999,
            overview="Devilman saga",
        )
        s1 = Show(
            id=101,
            title="Devilman: The Birth",
            year=1987,
            content_type="movie",
            collection_id=77,
            metadata_id="movie:3001",
            overview="Part 1 overview",
            poster_url="/poster1.jpg",
            rating=7.2,
            premiere_date=dt.datetime(1987, 11, 1),
        )
        s2 = Show(
            id=102,
            title="Devilman: The Demon Bird",
            year=1990,
            content_type="movie",
            collection_id=77,
            metadata_id="movie:3002",
            overview="Part 2 overview",
            poster_url="/poster2.jpg",
            rating=7.5,
            premiere_date=dt.datetime(1990, 2, 25),
        )

        db_mock = MagicMock()
        db_mock.get.return_value = coll
        db_mock.query.return_value.filter.return_value.order_by.return_value.all.return_value = [s1, s2]
        db_mock.query.return_value.filter.return_value.first.return_value = None

        # Simulate TMDb failing / timing out
        with patch("app.services.metadata.RadarrClient.get_collection_details", side_effect=Exception("TMDB Timeout")):
            res = asyncio.run(get_collection_detail(collection_id=77, db=db_mock, current_user=MagicMock()))
            self.assertEqual(len(res.franchise_parts), 2)
            self.assertEqual(res.franchise_parts[0].title, "Devilman: The Birth")
            self.assertEqual(res.franchise_parts[0].tmdb_id, 3001)
            self.assertTrue(res.franchise_parts[0].in_library)
            self.assertEqual(res.franchise_parts[1].title, "Devilman: The Demon Bird")
            self.assertTrue(res.franchise_parts[1].in_library)


if __name__ == "__main__":
    unittest.main()

