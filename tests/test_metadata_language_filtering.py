from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.metadata import (
    TMDBClient,
    RadarrClient,
    TheTVDBClient,
    is_alias_allowed,
    normalize_metadata_lang_code,
)


class TestMetadataLanguageFiltering(unittest.TestCase):
    def test_normalize_metadata_lang_code(self):
        # Country codes to ISO-639-1
        self.assertEqual(normalize_metadata_lang_code("US"), "en")
        self.assertEqual(normalize_metadata_lang_code("GB"), "en")
        self.assertEqual(normalize_metadata_lang_code("RU"), "ru")
        self.assertEqual(normalize_metadata_lang_code("JP"), "ja")
        self.assertEqual(normalize_metadata_lang_code("HU"), "hu")
        self.assertEqual(normalize_metadata_lang_code("FR"), "fr")
        self.assertEqual(normalize_metadata_lang_code("ID"), "id")
        self.assertEqual(normalize_metadata_lang_code("AZ"), "az")
        self.assertEqual(normalize_metadata_lang_code("DE"), "de")
        self.assertEqual(normalize_metadata_lang_code("KR"), "ko")
        self.assertEqual(normalize_metadata_lang_code("CN"), "zh")

        # Full language names
        self.assertEqual(normalize_metadata_lang_code("japanese"), "ja")
        self.assertEqual(normalize_metadata_lang_code("Hungarian"), "hu")
        self.assertEqual(normalize_metadata_lang_code("French"), "fr")
        self.assertEqual(normalize_metadata_lang_code("Russian"), "ru")
        self.assertEqual(normalize_metadata_lang_code("English"), "en")

        # Dict structures
        self.assertEqual(normalize_metadata_lang_code({"name": "Japanese"}), "ja")
        self.assertEqual(normalize_metadata_lang_code({"iso_639_1": "ru"}), "ru")
        self.assertEqual(normalize_metadata_lang_code({"iso_3166_1": "HU"}), "hu")

        # Empty / None
        self.assertEqual(normalize_metadata_lang_code(None), "")
        self.assertEqual(normalize_metadata_lang_code(""), "")

    def test_is_alias_allowed_en_ru(self):
        allowed = {"en", "eng", "ru", "rus"}

        # Russian titles
        self.assertTrue(is_alias_allowed("Дюна 3", "RU", allowed))
        self.assertTrue(is_alias_allowed("Дюна: Часть третья", "ru", allowed))
        self.assertTrue(is_alias_allowed("Дюна 3", "", allowed))  # Detected by Cyrillic script

        # English titles
        self.assertTrue(is_alias_allowed("Dune 3", "US", allowed))
        self.assertTrue(is_alias_allowed("Dune: Part Three", "GB", allowed))
        self.assertTrue(is_alias_allowed("Dune Part 3", "", allowed))  # Latin untagged

        # Foreign Latin titles (must NOT pass when only en+ru allowed)
        self.assertFalse(is_alias_allowed("Duna 3", "HU", allowed))
        self.assertFalse(is_alias_allowed("Dune: Bagian Tiga", "ID", allowed))
        self.assertFalse(is_alias_allowed("Dyun 3", "AZ", allowed))
        self.assertFalse(is_alias_allowed("Dune : Troisième partie", "FR", allowed))
        self.assertFalse(is_alias_allowed("Duna 3", "Hungarian", allowed))

        # Foreign Non-Latin titles (must NOT pass when only en+ru allowed)
        self.assertFalse(is_alias_allowed("デューン 砂の惑星PART3", "JP", allowed))
        self.assertFalse(is_alias_allowed("デューン 砂の惑星PART3", "", allowed))  # Detected CJK
        self.assertFalse(is_alias_allowed("듄: 파트 3", "KR", allowed))
        self.assertFalse(is_alias_allowed("듄: 파트 3", "", allowed))

    def test_is_alias_allowed_with_japanese(self):
        allowed = {"en", "eng", "ru", "rus", "ja", "jpn"}

        # Japanese title should now be allowed
        self.assertTrue(is_alias_allowed("デューン 砂の惑星PART3", "JP", allowed))
        self.assertTrue(is_alias_allowed("デューン 砂の惑星PART3", "", allowed))
        self.assertTrue(is_alias_allowed("Dune JP", "ja", allowed))

        # Hungarian should still be blocked
        self.assertFalse(is_alias_allowed("Duna 3", "HU", allowed))

    def test_tmdb_movie_details_language_filtering(self):
        # Movie payload mimicking Dune: Part Three with multiple international alternative titles
        fake_payload = {
            "id": 123456,
            "title": "Dune: Part Three",
            "original_title": "Dune: Part Three",
            "original_language": "en",
            "overview": "Paul Atreides continues his journey...",
            "release_date": "2026-12-18",
            "poster_path": "/dune3.jpg",
            "genres": [{"id": 878, "name": "Science Fiction"}],
            "production_countries": [{"iso_3166_1": "US"}],
            "translations": {
                "translations": [
                    {"iso_639_1": "en", "data": {"title": "Dune: Part Three", "overview": "English overview"}},
                    {"iso_639_1": "ru", "data": {"title": "Дюна: Часть третья", "overview": "Русское описание"}},
                    {"iso_639_1": "fr", "data": {"title": "Dune : Troisième partie", "overview": "Description francaise"}},
                    {"iso_639_1": "id", "data": {"title": "Dune: Bagian Tiga", "overview": "Deskripsi"}},
                ]
            },
            "alternative_titles": {
                "titles": [
                    {"title": "デューン 砂の惑星PART3", "iso_3166_1": "JP"},
                    {"title": "Duna 3", "iso_3166_1": "HU"},
                    {"title": "Dune: Bagian Tiga", "iso_3166_1": "ID"},
                    {"title": "Dyun 3", "iso_3166_1": "AZ"},
                    {"title": "Dune 3", "iso_3166_1": "US"},
                    {"title": "Дюна 3", "iso_3166_1": "RU"},
                    {"title": "Dune: Part 3", "iso_3166_1": "GB"},
                ]
            },
            "release_dates": {"results": []},
            "external_ids": {"imdb_id": "tt9999999"},
            "videos": {"results": []},
        }

        async def run_en_ru_test():
            client = TMDBClient(api_key="fake_key", alias_languages=["ru"])
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = fake_payload
            mock_resp.raise_for_status = MagicMock()

            mock_client_instance = AsyncMock()
            mock_client_instance.get.return_value = mock_resp
            mock_client_instance.__aenter__.return_value = mock_client_instance
            mock_client_instance.__aexit__.return_value = None

            mock_httpx = MagicMock()
            mock_httpx.AsyncClient.return_value = mock_client_instance

            with patch("app.services.metadata.httpx", mock_httpx):
                details = await client._get_movie_details("123456")

            self.assertEqual(details.title, "Dune: Part Three")
            # Only English and Russian aliases must be present
            self.assertIn("Дюна: Часть третья", details.aliases)
            self.assertIn("Dune 3", details.aliases)
            self.assertIn("Дюна 3", details.aliases)
            self.assertIn("Dune: Part 3", details.aliases)

            # Unauthorized languages MUST NOT be present
            self.assertNotIn("デューン 砂の惑星PART3", details.aliases)
            self.assertNotIn("Duna 3", details.aliases)
            self.assertNotIn("Dune: Bagian Tiga", details.aliases)
            self.assertNotIn("Dyun 3", details.aliases)
            self.assertNotIn("Dune : Troisième partie", details.aliases)

        async def run_en_ru_ja_test():
            client = TMDBClient(api_key="fake_key", alias_languages=["ru", "ja"])
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = fake_payload
            mock_resp.raise_for_status = MagicMock()

            mock_client_instance = AsyncMock()
            mock_client_instance.get.return_value = mock_resp
            mock_client_instance.__aenter__.return_value = mock_client_instance
            mock_client_instance.__aexit__.return_value = None

            mock_httpx = MagicMock()
            mock_httpx.AsyncClient.return_value = mock_client_instance

            with patch("app.services.metadata.httpx", mock_httpx):
                details = await client._get_movie_details("123456")

            # Japanese title should now be included
            self.assertIn("デューン 砂の惑星PART3", details.aliases)
            self.assertIn("Дюна: Часть третья", details.aliases)
            # Hungarian and French should still be excluded
            self.assertNotIn("Duna 3", details.aliases)
            self.assertNotIn("Dune : Troisième partie", details.aliases)

        asyncio.run(run_en_ru_test())
        asyncio.run(run_en_ru_ja_test())

    def test_radarr_movie_details_language_filtering(self):
        fake_radarr_payload = {
            "tmdbId": 123456,
            "title": "Dune: Part Three",
            "originalTitle": "Dune: Part Three",
            "originalLanguage": "en",
            "overview": "English overview",
            "alternativeTitles": [
                {"title": "Дюна 3", "language": "ru"},
                {"title": "Dune 3", "language": "en"},
                {"title": "Duna 3", "language": "hu"},
                {"title": "デューン 砂の惑星PART3", "language": "ja"},
                {"title": "Dune: Bagian Tiga", "language": "id"},
            ],
            "translations": [
                {"title": "Дюна: Часть третья", "language": "ru", "overview": "Русское описание"},
                {"title": "Dune : Troisième partie", "language": "fr", "overview": "Description"},
            ],
            "images": [],
        }

        async def run_radarr_test():
            client = RadarrClient(api_key="", alias_languages=["ru"])
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = fake_radarr_payload

            mock_client_instance = AsyncMock()
            mock_client_instance.get.return_value = mock_resp
            mock_client_instance.__aenter__.return_value = mock_client_instance
            mock_client_instance.__aexit__.return_value = None

            mock_httpx = MagicMock()
            mock_httpx.AsyncClient.return_value = mock_client_instance

            # Mock TMDB fallback to raise so Radarr API is executed
            with patch("app.services.metadata.TMDBClient._get_movie_details", side_effect=Exception("TMDB off")), \
                 patch("app.services.metadata.httpx", mock_httpx):
                details = await client.get_details("movie:123456")

            self.assertEqual(details.title, "Dune: Part Three")
            self.assertIn("Дюна 3", details.aliases)
            self.assertIn("Dune 3", details.aliases)
            self.assertIn("Дюна: Часть третья", details.aliases)

            # Foreign titles excluded
            self.assertNotIn("Duna 3", details.aliases)
            self.assertNotIn("デューン 砂の惑星PART3", details.aliases)
            self.assertNotIn("Dune: Bagian Tiga", details.aliases)
            self.assertNotIn("Dune : Troisième partie", details.aliases)

        asyncio.run(run_radarr_test())


if __name__ == "__main__":
    unittest.main()
