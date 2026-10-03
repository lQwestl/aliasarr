"""Поиск тайтла при добавлении по IMDb ID или ссылке на страницу IMDb."""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, patch

import httpx
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.services.metadata as metadata
from app.api.metadata_routes import search_all_metadata_sources
from app.models.db import Base, Show, User
from app.services.metadata import (
    MetadataResult,
    MetadataShowDetails,
    extract_imdb_id,
    search_by_imdb_id,
)


class TestExtractImdbId(unittest.TestCase):
    def test_ids_and_links_are_recognised(self):
        for query in (
            "tt0903747",
            "TT0903747",
            " imdb:tt0903747 ",
            "https://www.imdb.com/title/tt0903747/",
            "https://www.imdb.com/title/tt0903747/?ref_=nv_sr_srsg_0",
            "https://m.imdb.com/title/tt0903747/episodes",
            "imdb.com/ru/title/tt0903747",
        ):
            with self.subTest(query=query):
                self.assertEqual(extract_imdb_id(query), "tt0903747")

    def test_ordinary_titles_are_not_ids(self):
        for query in ("Breaking Bad", "tt12", "The tt0903747 file", "", "https://www.themoviedb.org/tv/1396"):
            with self.subTest(query=query):
                self.assertIsNone(extract_imdb_id(query))


def _tmdb_transport(find_payload: dict, tvdb_by_tmdb: dict[int, int | None]):
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if "/find/" in path:
            assert request.url.params.get("external_source") == "imdb_id"
            return httpx.Response(200, json=find_payload)
        if path.endswith("/external_ids"):
            tmdb_id = int(path.split("/")[-2])
            return httpx.Response(200, json={"tvdb_id": tvdb_by_tmdb.get(tmdb_id)})
        raise AssertionError(f"unexpected request {request.url}")

    real_client = httpx.AsyncClient

    def factory(**kwargs):
        return real_client(transport=httpx.MockTransport(handler), **kwargs)

    return factory


class TestSearchByImdbId(unittest.TestCase):
    def _run(self, find_payload, tvdb_by_tmdb=None, radarr_movie=None, skyhook_details=None):
        skyhook = AsyncMock(return_value=skyhook_details)
        with patch.object(metadata.httpx, "AsyncClient", _tmdb_transport(find_payload, tvdb_by_tmdb or {})), \
             patch.object(metadata.RadarrClient, "_get_movie_by_imdb", AsyncMock(return_value=radarr_movie)), \
             patch.object(metadata.SkyHookClient, "get_details", skyhook):
            return asyncio.run(search_by_imdb_id("tt0903747")), skyhook

    def test_series_is_returned_through_skyhook_by_tvdb_id(self):
        details = MetadataShowDetails(external_id="tvdb:81189", title="Во все тяжкие", year=2008,
                                      content_type="series", premiere_date="2008-01-20")
        results, skyhook = self._run(
            {"movie_results": [], "tv_results": [{"id": 1396, "name": "Во все тяжкие", "first_air_date": "2008-01-20"}]},
            tvdb_by_tmdb={1396: 81189},
            skyhook_details=details,
        )
        skyhook.assert_awaited_once_with("tvdb:81189")
        self.assertEqual([r.external_id for r in results], ["tvdb:81189"])
        self.assertEqual(results[0].year, 2008)

    def test_series_without_tvdb_id_falls_back_to_tmdb(self):
        results, skyhook = self._run(
            {"movie_results": [], "tv_results": [{"id": 555, "name": "Show", "first_air_date": "2020-05-01"}]},
            tvdb_by_tmdb={555: None},
        )
        skyhook.assert_not_awaited()
        self.assertEqual(results[0].external_id, "tv:555")
        self.assertEqual(results[0].content_type, "series")

    def test_movie_is_returned_through_radarr(self):
        movie = MetadataResult(external_id="movie:603", title="Матрица", year=1999, content_type="movie")
        results, _ = self._run(
            {"movie_results": [{"id": 603, "title": "Матрица", "release_date": "1999-03-30"}], "tv_results": []},
            radarr_movie=movie,
        )
        self.assertEqual([r.external_id for r in results], ["movie:603"])

    def test_movie_falls_back_to_tmdb_when_radarr_is_unavailable(self):
        results, _ = self._run(
            {"movie_results": [{"id": 603, "title": "The Matrix", "release_date": "1999-03-30", "poster_path": "/p.jpg"}],
             "tv_results": []},
        )
        self.assertEqual(results[0].external_id, "movie:603")
        self.assertEqual(results[0].year, 1999)
        self.assertTrue(results[0].poster_url.endswith("/p.jpg"))


class TestSearchEndpointWithImdb(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()
        self.user = User(username="admin", password_hash="h", is_admin=True, is_owner=True)
        self.db.add(self.user)
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def test_imdb_link_skips_text_search_and_marks_existing_title(self):
        self.db.add(Show(title="Breaking Bad", content_type="series", imdb_id="tt0903747"))
        self.db.commit()
        found = [MetadataResult(external_id="tvdb:81189", title="Breaking Bad", year=2008, content_type="series")]
        with patch("app.api.metadata_routes.search_by_imdb_id", AsyncMock(return_value=found)) as by_imdb, \
             patch.object(metadata.RadarrClient, "search", AsyncMock(side_effect=AssertionError("text search"))), \
             patch.object(metadata.SkyHookClient, "search", AsyncMock(side_effect=AssertionError("text search"))):
            results = asyncio.run(search_all_metadata_sources(
                query="https://www.imdb.com/title/tt0903747/?ref_=fn_al_tt_1", db=self.db, current_user=self.user,
            ))
        by_imdb.assert_awaited_once()
        self.assertEqual(by_imdb.await_args.args[0], "tt0903747")
        self.assertEqual(len(results), 1)
        self.assertTrue(results[0].already_added)


if __name__ == "__main__":
    unittest.main()
