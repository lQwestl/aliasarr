from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

try:
    from app.models.db import MetadataSourceType
except ImportError:
    class MetadataSourceType:
        RADARR = "radarr"
        SKYHOOK = "skyhook"
        TMDB = "tmdb"
        TVMAZE = "tvmaze"
        THETVDB = "thetvdb"
try:
    import fastapi
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False

from app.services.metadata import (
    MetadataResult,
    MetadataShowDetails,
    RadarrClient,
    SkyHookClient,
    TMDBClient,
    get_metadata_client,
)


class TestRadarrMetadata(unittest.TestCase):
    def test_get_metadata_client_radarr(self):
        source_mock = MagicMock()
        source_mock.type = "radarr"
        source_mock.base_url = "https://api.radarr.video/v1"
        source_mock.api_key = ""
        source_mock.field_mapping = {}

        client = get_metadata_client(source_mock)
        self.assertIsInstance(client, RadarrClient)
        self.assertEqual(client.base_url, "https://api.radarr.video/v1")

    def test_radarr_client_map_movie(self):
        radarr = RadarrClient()
        raw_movie = {
            "tmdbId": 550,
            "imdbId": "tt0137523",
            "title": "Fight Club",
            "originalTitle": "Fight Club",
            "year": 1999,
            "overview": "An insomniac office worker...",
            "images": [
                {"coverType": "poster", "url": "https://image.tmdb.org/t/p/original/pB8BM7pdSp6B6Ih7QZ4DrQ3PmJK.jpg"}
            ],
            "movieRatings": {"value": 8.4, "votes": 25000},
            "genres": ["Drama", "Thriller"],
            "originalLanguage": "en",
        }

        res = radarr._map_movie_to_result(raw_movie)
        self.assertIsNotNone(res)
        self.assertEqual(res.external_id, "movie:550")
        self.assertEqual(res.title, "Fight Club")
        self.assertEqual(res.year, 1999)
        self.assertEqual(res.rating, 8.4)
        self.assertEqual(res.content_type, "movie")
        self.assertEqual(res.poster_url, "https://image.tmdb.org/t/p/original/pB8BM7pdSp6B6Ih7QZ4DrQ3PmJK.jpg")

    def test_radarr_client_get_details_mocked(self):
        radarr = RadarrClient()
        fake_details_payload = {
            "tmdbId": 550,
            "imdbId": "tt0137523",
            "title": "Fight Club",
            "originalTitle": "Fight Club",
            "overview": "English overview",
            "year": 1999,
            "digitalRelease": "2000-06-06T00:00:00Z",
            "studio": "Fox 2000 Pictures",
            "genres": ["Drama", "Thriller"],
            "images": [{"coverType": "poster", "url": "https://image.tmdb.org/t/p/poster.jpg"}],
            "movieRatings": {"value": 8.4},
            "alternativeTitles": [
                {"title": "Бойцовский клуб", "language": "ru"},
                {"title": "Fight Club (1999)", "language": "en"},
            ],
            "translations": [
                {"title": "Бойцовский клуб", "overview": "Русское описание фильма...", "language": "ru"},
                {"title": "El club de la lucha", "overview": "Descripcion en espanol", "language": "es"},
            ],
        }

        async def run_test():
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = fake_details_payload

            mock_client_instance = AsyncMock()
            mock_client_instance.get.return_value = mock_resp
            mock_client_instance.__aenter__.return_value = mock_client_instance
            mock_client_instance.__aexit__.return_value = None

            mock_httpx = MagicMock()
            mock_httpx.AsyncClient.return_value = mock_client_instance

            with patch("app.services.metadata.httpx", mock_httpx):
                details = await radarr.get_details("movie:550")

                self.assertEqual(details.external_id, "movie:550")
                self.assertEqual(details.title, "Fight Club")
                # Russian translation overview was used
                self.assertEqual(details.overview, "Русское описание фильма...")
                # Aliases contain Russian title and AlternativeTitles
                self.assertIn("Бойцовский клуб", details.aliases)
                self.assertIn("Fight Club (1999)", details.aliases)
                self.assertEqual(details.content_type, "movie")
                self.assertEqual(details.premiere_date, "2000-06-06")

        asyncio.run(run_test())

    def test_search_prioritization_logic(self):
        # Verify that Radarr and SkyHook results are prioritized first
        primary_results = [
            MetadataResult(external_id="movie:1", title="Radarr Movie", year=2023, content_type="movie"),
            MetadataResult(external_id="tvdb:2", title="Sonarr Series", year=2022, content_type="series"),
        ]
        secondary_results = [
            MetadataResult(external_id="tvmaze:3", title="TVMaze Show", year=2021, content_type="series"),
            MetadataResult(external_id="movie:1", title="Duplicate Radarr Movie", year=2023, content_type="movie"),
        ]

        seen_ids = set()
        seen_keys = set()
        combined = []

        for r in primary_results + secondary_results:
            uid = f"{r.external_id}"
            c_type = r.content_type or "series"
            title_norm = (r.title or "").strip().lower()
            key = (c_type, title_norm, r.year)

            if uid in seen_ids or (title_norm and key in seen_keys):
                continue
            seen_ids.add(uid)
            if title_norm:
                seen_keys.add(key)
            combined.append(r)

        self.assertEqual(len(combined), 3)
        self.assertEqual(combined[0].title, "Radarr Movie")
        self.assertEqual(combined[1].title, "Sonarr Series")
        self.assertEqual(combined[2].title, "TVMaze Show")

    def test_refresh_show_cover_movie_uses_radarr(self):
        from app.services.metadata import resolve_show_cover

        movie_show = MagicMock()
        movie_show.id = 101
        movie_show.title = "Inception"
        movie_show.category = "movies"
        movie_show.content_type = "movie"
        movie_show.metadata_id = "movie:27205"
        movie_show.poster_url = None

        async def run_test():
            with patch("app.services.metadata.RadarrClient.get_details") as mock_get_details:
                mock_get_details.return_value = MetadataShowDetails(
                    external_id="movie:27205",
                    title="Inception",
                    poster_url="https://image.tmdb.org/t/p/original/inception_radarr.jpg",
                    content_type="movie",
                )
                poster_url, source_name = await resolve_show_cover(movie_show)
                self.assertEqual(poster_url, "https://image.tmdb.org/t/p/original/inception_radarr.jpg")
                self.assertIn("Radarr", source_name)

        asyncio.run(run_test())

    def test_refresh_show_cover_series_uses_skyhook(self):
        from app.services.metadata import resolve_show_cover

        series_show = MagicMock()
        series_show.id = 202
        series_show.title = "Breaking Bad"
        series_show.category = "series"
        series_show.content_type = "series"
        series_show.metadata_id = "tvdb:81189"
        series_show.poster_url = None

        async def run_test():
            with patch("app.services.metadata.SkyHookClient.get_details") as mock_get_details:
                mock_get_details.return_value = MetadataShowDetails(
                    external_id="tvdb:81189",
                    title="Breaking Bad",
                    poster_url="https://artworks.thetvdb.com/banners/posters/81189-1.jpg",
                    content_type="series",
                )
                poster_url, source_name = await resolve_show_cover(series_show)
                self.assertEqual(poster_url, "https://artworks.thetvdb.com/banners/posters/81189-1.jpg")
                self.assertIn("SkyHook", source_name)

        asyncio.run(run_test())

    def test_refresh_show_metadata_updates_episode_titles_and_adds_new(self):
        from app.services.metadata import MetadataEpisode, MetadataShowDetails, refresh_show_metadata

        mock_db = MagicMock()
        mock_show = MagicMock()
        mock_show.id = 42
        mock_show.title = "Frieren"
        mock_show.content_type = "anime"
        mock_show.metadata_id = "tvdb:408544"
        mock_show.aliases = []
        mock_show.overview = "Old overview"
        mock_show.poster_url = None
        mock_show.rating = None
        mock_show.genre = None
        mock_show.network = None
        mock_show.year = 2023
        mock_show.premiere_date = None

        existing_ep8 = MagicMock()
        existing_ep8.show_id = 42
        existing_ep8.season_number = 1
        existing_ep8.episode_number = 8
        existing_ep8.title = "Episode 8"
        existing_ep8.air_date = None
        existing_ep8.absolute_number = 8

        # Настраиваем mock запроса серий
        mock_db.query.return_value.filter.return_value.first.side_effect = lambda: existing_ep8

        fake_details = MetadataShowDetails(
            external_id="tvdb:408544",
            title="Frieren",
            content_type="anime",
            overview="Updated Frieren synopsis",
            poster_url="https://artworks.thetvdb.com/frieren.jpg",
            episodes=[
                MetadataEpisode(season_number=1, episode_number=8, title="Frieren the Slayer", absolute_number=8, air_date="2023-10-27"),
            ],
            aliases=["Провожающая в последний путь Фрирен", "Sousou no Frieren"],
        )

        async def run_test():
            with patch("app.services.metadata.SkyHookClient.get_details", return_value=fake_details):
                res = await refresh_show_metadata(mock_db, mock_show)
                self.assertTrue(res["updated"])
                self.assertEqual(mock_show.overview, "Updated Frieren synopsis")
                self.assertEqual(mock_show.poster_url, "https://artworks.thetvdb.com/frieren.jpg")
                self.assertEqual(existing_ep8.title, "Frieren the Slayer")
                mock_db.commit.assert_called()

        asyncio.run(run_test())

    def test_refresh_show_metadata_fallback_alias_and_none_titles(self):
        from app.services.metadata import MetadataEpisode, MetadataShowDetails, refresh_show_metadata

        mock_db = MagicMock()
        mock_show = MagicMock()
        mock_show.id = 99
        mock_show.title = "Реинкарнация безработного"
        mock_show.content_type = "anime"
        mock_show.metadata_id = None
        mock_alias = MagicMock()
        mock_alias.text = "Mushoku Tensei: Jobless Reincarnation"
        mock_alias.language = "en"
        mock_show.aliases = [mock_alias]
        mock_show.overview = None
        mock_show.poster_url = None
        mock_show.rating = None
        mock_show.genre = None
        mock_show.network = None
        mock_show.year = 2021
        mock_show.premiere_date = None

        existing_ep10 = MagicMock()
        existing_ep10.show_id = 99
        existing_ep10.season_number = 3
        existing_ep10.episode_number = 10
        existing_ep10.title = "Episode 10"
        existing_ep10.air_date = None
        existing_ep10.absolute_number = 59

        mock_db.query.return_value.filter.return_value.first.side_effect = lambda: existing_ep10

        fake_search_res = [
            MagicMock(external_id="tvdb:371310", title="Mushoku Tensei: Jobless Reincarnation")
        ]
        fake_details = MetadataShowDetails(
            external_id="tvdb:371310",
            title="Mushoku Tensei: Jobless Reincarnation",
            content_type="anime",
            episodes=[
                MetadataEpisode(season_number=3, episode_number=10, title="An Audience with an Immortal Demon King", absolute_number=59, air_date="2026-08-31"),
                MetadataEpisode(season_number=3, episode_number=12, title="None", absolute_number=61, air_date="2026-09-14"),
            ],
            aliases=["Jobless Reincarnation"],
        )

        async def run_test():
            with patch("app.services.metadata.SkyHookClient.search", return_value=fake_search_res), \
                 patch("app.services.metadata.SkyHookClient.get_details", return_value=fake_details):
                res = await refresh_show_metadata(mock_db, mock_show)
                self.assertTrue(res["updated"])
                self.assertEqual(mock_show.metadata_id, "tvdb:371310")
                self.assertEqual(existing_ep10.title, "An Audience with an Immortal Demon King")
                mock_db.commit.assert_called()

        asyncio.run(run_test())

    def test_should_refresh_show_sonarr_radarr_rules(self):
        import datetime as dt
        from app.services.metadata import should_refresh_show

        mock_db = MagicMock()

        # 1. Force always refreshes
        show = MagicMock(content_type="anime", last_metadata_refresh_at=dt.datetime.utcnow())
        self.assertTrue(should_refresh_show(show, mock_db, force=True))

        # 2. Never synced before
        show = MagicMock(content_type="anime", last_metadata_refresh_at=None)
        self.assertTrue(should_refresh_show(show, mock_db))

        # 3. Series with TBA / Episode X placeholders
        show = MagicMock(content_type="anime", status="ended", last_metadata_refresh_at=dt.datetime.utcnow() - dt.timedelta(hours=1))
        ep = MagicMock(title="Episode 10")
        mock_db.query.return_value.filter.return_value.all.return_value = [ep]
        self.assertTrue(should_refresh_show(show, mock_db))

        # 4. Ended series with all names filled, synced 2 hours ago -> skip
        ep_good = MagicMock(title="Final Battle", air_date=dt.datetime.utcnow() - dt.timedelta(days=100))
        mock_db.query.return_value.filter.return_value.all.return_value = [ep_good]
        self.assertFalse(should_refresh_show(show, mock_db))

        # 5. Movie in cinemas synced 2 hours ago -> skip (within 12h)
        movie = MagicMock(content_type="movie", status="in_cinemas", premiere_date=None, last_metadata_refresh_at=dt.datetime.utcnow() - dt.timedelta(hours=2))
        self.assertFalse(should_refresh_show(movie, mock_db))

        # 6. Movie in cinemas synced 14 hours ago -> should refresh
        movie.last_metadata_refresh_at = dt.datetime.utcnow() - dt.timedelta(hours=14)
        self.assertTrue(should_refresh_show(movie, mock_db))


class TestMetadataSourcesSeeding(unittest.TestCase):
    def test_seed_default_metadata_sources_once(self):
        from app.services.metadata import seed_default_metadata_sources

        db = MagicMock()
        settings = MagicMock()
        settings.metadata_sources_seeded = False

        # First run: seeds
        with patch("app.services.settings_service.get_or_create_settings", return_value=settings):
            db.query.return_value.all.return_value = []
            db.query.return_value.count.return_value = 0
            seed_default_metadata_sources(db)
            self.assertTrue(settings.metadata_sources_seeded)
            self.assertGreater(db.add.call_count, 0)
            db.commit.assert_called()

        # Second run after user deletion: does not re-add
        db2 = MagicMock()
        settings.metadata_sources_seeded = True
        with patch("app.services.settings_service.get_or_create_settings", return_value=settings):
            seed_default_metadata_sources(db2)
            db2.add.assert_not_called()


class TestMetadataEpisodeDeduplication(unittest.TestCase):
    def test_metadata_show_details_deduplicates_episodes(self):
        from app.services.metadata import MetadataEpisode, MetadataShowDetails

        eps = [
            MetadataEpisode(season_number=0, episode_number=19, title="Q&A Part 1", air_date="2022-02-23"),
            MetadataEpisode(season_number=0, episode_number=19, title="Q&A Part 1 Duplicate", air_date="2022-02-23"),
            MetadataEpisode(season_number=1, episode_number=1, title="The Terror of Tal'Dorei - Part 1"),
            MetadataEpisode(season_number=1, episode_number=1, title="The Terror of Tal'Dorei - Part 1 Dup"),
            MetadataEpisode(season_number=1, episode_number=2, title="The Terror of Tal'Dorei - Part 2"),
        ]

        details = MetadataShowDetails(
            external_id="tvdb:385376",
            title="The Legend of Vox Machina",
            episodes=eps,
        )

        self.assertEqual(len(details.episodes), 3)
        self.assertEqual(details.episodes[0].season_number, 0)
        self.assertEqual(details.episodes[0].episode_number, 19)
        self.assertEqual(details.episodes[1].season_number, 1)
        self.assertEqual(details.episodes[1].episode_number, 1)
        self.assertEqual(details.episodes[2].season_number, 1)
        self.assertEqual(details.episodes[2].episode_number, 2)


class TestMetadataProtectionEngine(unittest.TestCase):
    def test_calc_metadata_match_score_exact_match(self):
        from app.services.metadata import MetadataResult, calc_metadata_match_score

        cand = MetadataResult(
            external_id="tvdb:12345",
            title="I Became a Legend After My 10 Year-Long Last Stand",
            year=2026,
        )
        score = calc_metadata_match_score(
            candidate=cand,
            target_title="I Became a Legend After My 10 Year-Long Last Stand",
            target_year=2026,
        )
        self.assertGreaterEqual(score, 0.95)

    def test_calc_metadata_match_score_unrelated_show_rejected(self):
        from app.services.metadata import MetadataResult, calc_metadata_match_score

        cand = MetadataResult(
            external_id="tvdb:364402",
            title="My Next Life as a Villainess: All Routes Lead to Doom!",
            year=2020,
        )
        score = calc_metadata_match_score(
            candidate=cand,
            target_title="I Became a Legend After My 10 Year-Long Last Stand",
            target_year=2026,
            target_aliases=["10-nen Goshi no Hikikomori"],
        )
        self.assertLess(score, 0.40)

    def test_calc_metadata_match_score_year_penalty(self):
        from app.services.metadata import MetadataResult, calc_metadata_match_score

        cand_old = MetadataResult(
            external_id="tvdb:1111",
            title="Shaman King",
            year=2001,
        )
        score_diff_year = calc_metadata_match_score(
            candidate=cand_old,
            target_title="Shaman King",
            target_year=2021,
        )
        self.assertLess(score_diff_year, 0.70)

    def test_refresh_metadata_preserves_empty_episodes_for_valid_show(self):
        from app.services.metadata import MetadataShowDetails, refresh_show_metadata

        mock_db = MagicMock()
        mock_show = MagicMock()
        mock_show.id = 55
        mock_show.title = "I Became a Legend After My 10 Year-Long Last Stand"
        mock_show.year = 2026
        mock_show.content_type = "anime"
        mock_show.metadata_id = "tvdb:999999"
        mock_show.metadata_source = "skyhook"
        mock_show.aliases = []
        mock_show.overview = "Original overview"
        mock_show.poster_url = "https://example.com/poster.jpg"
        mock_show.rating = None
        mock_show.genre = "Fantasy"
        mock_show.network = None
        mock_show.premiere_date = None

        valid_empty_details = MetadataShowDetails(
            external_id="tvdb:999999",
            title="I Became a Legend After My 10 Year-Long Last Stand",
            year=2026,
            content_type="anime",
            episodes=[],
            overview="Updated official synopsis",
            poster_url="https://example.com/poster_new.jpg",
        )

        async def run_test():
            with patch("app.services.metadata.SkyHookClient.get_details", return_value=valid_empty_details), \
                 patch("app.services.metadata.SkyHookClient.search", return_value=[]):
                res = await refresh_show_metadata(mock_db, mock_show)
                self.assertTrue(res["updated"])
                self.assertEqual(mock_show.metadata_id, "tvdb:999999")
                self.assertEqual(mock_show.overview, "Updated official synopsis")

        asyncio.run(run_test())


@unittest.skipUnless(HAS_FASTAPI, "Requires fastapi")
class TestShowRemapLogic(unittest.TestCase):
    def test_remap_show_cleans_corrupted_unlinked_episodes(self):
        import datetime as dt
        from app.api.shows import ShowRemapIn, remap_show_metadata
        from app.models.db import Alias, DownloadHistory, Episode, EpisodeStatus, MetadataSource, Show
        from app.services.metadata import MetadataEpisode, MetadataShowDetails

        mock_db = MagicMock()
        mock_user = MagicMock()
        mock_user.username = "admin"

        show = Show(
            title="I Became a Legend (Corrupted)",
            year=2026,
            content_type="anime",
            monitored=True,
            upgrade_requested=False,
            is_searching=False,
            ova_mode="auto",
            in_calendar=True,
            metadata_id="tvdb:364402",
            metadata_source="skyhook",
        )
        show.id = 12
        show.aliases = []

        fake_orphan_eps = []
        for i in range(1, 26):
            ep_inst = Episode(
                show_id=12,
                season_number=1,
                episode_number=i,
                title=f"Villainess Episode {i}",
                status=EpisodeStatus.WANTED,
                file_path=None,
            )
            ep_inst.id = 1000 + i
            fake_orphan_eps.append(ep_inst)

        downloaded_ep = Episode(
            show_id=12,
            season_number=1,
            episode_number=1,
            title="Ep 1 Real",
            status=EpisodeStatus.DOWNLOADED,
            file_path="/downloads/ep1.mkv",
        )

        def query_mock(model):
            mock_q = MagicMock()
            if model == Episode:
                mock_q.filter.return_value.all.return_value = fake_orphan_eps
            elif model == Alias:
                mock_q.filter.return_value.all.return_value = []
            elif model == DownloadHistory:
                mock_q.filter.return_value.update.return_value = 0
            elif model == MetadataSource:
                mock_q.filter.return_value.first.return_value = None
            else:
                mock_q.filter.return_value.all.return_value = []
                mock_q.filter.return_value.first.return_value = None
                mock_q.filter.return_value.update.return_value = 0
            return mock_q

        mock_db.get.return_value = show
        mock_db.query.side_effect = query_mock

        new_show_details = MetadataShowDetails(
            external_id="tvdb:445566",
            title="I Became a Legend After My 10 Year-Long Last Stand",
            year=2026,
            content_type="anime",
            episodes=[
                MetadataEpisode(season_number=1, episode_number=1, title="Episode 1", air_date="2026-09-01"),
                MetadataEpisode(season_number=1, episode_number=2, title="Episode 2", air_date="2026-09-08"),
            ],
            aliases=["10-nen Goshi no Hikikomori"],
        )

        async def run_remap_test():
            with patch("app.services.metadata.get_metadata_client") as mock_get_client, \
                 patch("app.api.shows.get_metadata_client", mock_get_client), \
                 patch("app.api.shows.log_audit"):
                mock_client = MagicMock()
                mock_client.get_details = AsyncMock(return_value=new_show_details)
                mock_get_client.return_value = mock_client

                payload = ShowRemapIn(
                    external_id="tvdb:445566",
                    new_metadata_id="tvdb:445566",
                    cleanup_unlinked_episodes=True,
                    update_title=True,
                )

                res = await remap_show_metadata(show_id=12, payload=payload, db=mock_db, current_user=mock_user)
                self.assertTrue(res["success"])
                self.assertEqual(show.metadata_id, "tvdb:445566")
                self.assertEqual(show.title, "I Became a Legend After My 10 Year-Long Last Stand")
                # 25 fake episodes existed, 2 were updated in-place with new metadata, 23 unlinked orphan episodes were deleted
                self.assertEqual(res["deleted_episodes"], 23)
                self.assertEqual(res["added_episodes"], 0)
                self.assertEqual(fake_orphan_eps[0].title, "Episode 1")
                self.assertEqual(fake_orphan_eps[1].title, "Episode 2")

        asyncio.run(run_remap_test())


if __name__ == "__main__":
    unittest.main()


