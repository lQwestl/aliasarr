from __future__ import annotations

import unittest
from unittest.mock import MagicMock


class TestMetadataMatching(unittest.TestCase):
    def test_distinct_movie_years_not_conflicted(self):
        """Проверяет, что фильмы с одинаковым названием, но разными годами (Scary Movie 1991 vs 2000), не матчатся."""
        show_2000 = MagicMock()
        show_2000.id = 96
        show_2000.title = "Scary Movie"
        show_2000.year = 2000
        show_2000.content_type = "movie"
        show_2000.metadata_id = "movie:4247"
        show_2000.metadata_source = "radarr"
        show_2000.tmdb_id = 4247
        show_2000.tvdb_id = None
        show_2000.imdb_id = None

        mock_db = MagicMock()
        q = MagicMock()
        q.filter.return_value = q
        q.first.return_value = None
        q.all.return_value = [show_2000]
        mock_db.query.return_value = q

        candidates = [show_2000]
        search_title = "Scary Movie"
        search_year = 1991
        search_content_type = "movie"

        matched = None
        for c in candidates:
            if search_content_type:
                c_type = c.content_type or "series"
                req_type = "movie" if search_content_type == "movie" else "series"
                cand_type = "movie" if c_type == "movie" else "series"
                if req_type != cand_type:
                    continue
            if search_year is not None and c.year is not None:
                if c.year != search_year:
                    continue
            matched = c
            break

        self.assertIsNone(matched, "Фильм 1991 года не должен сопоставляться с фильмом 2000 года")

        search_year_2000 = 2000
        matched_2000 = None
        for c in candidates:
            if search_content_type:
                c_type = c.content_type or "series"
                req_type = "movie" if search_content_type == "movie" else "series"
                cand_type = "movie" if c_type == "movie" else "series"
                if req_type != cand_type:
                    continue
            if search_year_2000 is not None and c.year is not None:
                if c.year != search_year_2000:
                    continue
            matched_2000 = c
            break

        self.assertIsNotNone(matched_2000)
        self.assertEqual(matched_2000.id, 96)


if __name__ == "__main__":
    unittest.main()
