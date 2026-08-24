from __future__ import annotations

import os
import tempfile
import unittest

from app.services.organizer import FileNameBuilder
from app.services.quality import QualityInfo


class TestPreviewRenameLogic(unittest.TestCase):
    def test_filename_builder_series(self):
        q = QualityInfo(name="Bluray-1080p", rank=10, source="Bluray", resolution="1080p")
        res = FileNameBuilder.build_file_name(
            template="{Series Title} - S{season:00}E{episode:00} - {Episode Title} {Quality Full}",
            title="Chained Soldier",
            year=2024,
            season_number=2,
            episode_number=12,
            episode_title="Gods Assemble",
            quality=q,
            content_type="series",
            extension=".mkv",
        )
        self.assertEqual(res, "Chained Soldier - S02E12 - Gods Assemble Bluray-1080p.mkv")

    def test_filename_builder_movie(self):
        q = QualityInfo(name="Bluray-2160p", rank=15, source="Bluray", resolution="2160p")
        res = FileNameBuilder.build_file_name(
            template="{Movie Title} ({Release Year}) {Quality Full}",
            title="Spider-Man Homecoming",
            year=2017,
            quality=q,
            content_type="movie",
            extension=".m2ts",
        )
        self.assertEqual(res, "Spider-Man Homecoming (2017) Bluray-2160p.m2ts")

    def test_season_folder_builder(self):
        res1 = FileNameBuilder.build_season_folder_name("Season {season:00}", 2)
        self.assertEqual(res1, "Season 02")

        res2 = FileNameBuilder.build_season_folder_name("Сезон {season}", 1)
        self.assertEqual(res2, "Сезон 1")
