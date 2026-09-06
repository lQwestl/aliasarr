import unittest
from unittest.mock import MagicMock

try:
    from app.models.db import Show
    from app.schemas import ShowCreate, ShowOut, ShowUpdate
    from app.services.metadata import MetadataShowDetails
    HAS_DEPS = True
except (ImportError, ModuleNotFoundError):
    HAS_DEPS = False


class TestShowLinksAndExternalIds(unittest.TestCase):
    def test_show_model_external_ids(self):
        if not HAS_DEPS:
            self.skipTest("Dependencies not installed in host runner")
        show = Show(
            title="How to Get to Heaven From Belfast",
            year=2026,
            content_type="series",
            metadata_source="skyhook",
            metadata_id="tvdb:123456",
            imdb_id="tt31709373",
            tvdb_id=123456,
            tvmaze_id=78901,
            tmdb_id=234567,
            trailer_url="https://www.youtube.com/watch?v=sampleTrailer123",
        )
        self.assertEqual(show.imdb_id, "tt31709373")
        self.assertEqual(show.tvdb_id, 123456)
        self.assertEqual(show.tvmaze_id, 78901)
        self.assertEqual(show.tmdb_id, 234567)
        self.assertEqual(show.trailer_url, "https://www.youtube.com/watch?v=sampleTrailer123")

        # Test ShowOut serialization
        show_out = ShowOut.model_validate(show)
        self.assertEqual(show_out.imdb_id, "tt31709373")
        self.assertEqual(show_out.tvdb_id, 123456)
        self.assertEqual(show_out.tvmaze_id, 78901)
        self.assertEqual(show_out.tmdb_id, 234567)
        self.assertEqual(show_out.metadata_source, "skyhook")
        self.assertEqual(show_out.metadata_id, "tvdb:123456")

    def test_anime_external_ids(self):
        if not HAS_DEPS:
            self.skipTest("Dependencies not installed in host runner")
        anime = Show(
            title="Sousou no Frieren",
            year=2023,
            content_type="anime",
            metadata_source="tmdb",
            metadata_id="tv:209867",
            shikimori_id="52991",
            anidb_id=17617,
            mal_id=52991,
            anilist_id=154587,
            tmdb_id=209867,
        )
        self.assertEqual(anime.shikimori_id, "52991")
        self.assertEqual(anime.anidb_id, 17617)
        self.assertEqual(anime.mal_id, 52991)
        self.assertEqual(anime.anilist_id, 154587)

        anime_out = ShowOut.model_validate(anime)
        self.assertEqual(anime_out.shikimori_id, "52991")
        self.assertEqual(anime_out.mal_id, 52991)

    def test_metadata_show_details_fields(self):
        if not HAS_DEPS:
            self.skipTest("Dependencies not installed in host runner")
        details = MetadataShowDetails(
            external_id="tvdb:12345",
            title="Test Show",
            imdb_id="tt1234567",
            tmdb_id=9999,
            tvdb_id=12345,
            tvmaze_id=4444,
            trailer_url="https://youtube.com/watch?v=abc",
        )
        self.assertEqual(details.imdb_id, "tt1234567")
        self.assertEqual(details.tmdb_id, 9999)
        self.assertEqual(details.tvdb_id, 12345)
        self.assertEqual(details.tvmaze_id, 4444)
        self.assertEqual(details.trailer_url, "https://youtube.com/watch?v=abc")


if __name__ == "__main__":
    unittest.main()
