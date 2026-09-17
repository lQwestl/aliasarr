"""Сопоставление файлов-спутников (субтитры, дорожки, обложки) с видеофайлом.

Релизы без ведущих нулей — «Naruto - 1.mkv», «Naruto - 10.mkv» — ломали наивную
проверку «имя начинается с имени видеофайла»: под неё попадали и другие серии.
"""

from __future__ import annotations

import os
import tempfile
import unittest

from app.services.postprocess import (
    COMPANION_EXTENSIONS,
    DELETABLE_COMPANION_EXTENSIONS,
    episode_number_in_name,
    is_companion_file_name,
    iter_companion_files,
    match_companion_files_for_episode,
)


class TestIsCompanionFileName(unittest.TestCase):
    def test_suffix_after_separator_is_a_companion(self):
        for name in (
            "Naruto - 1.rus.srt",
            "Naruto - 1_rus.ass",
            "Naruto - 1 [RUS].srt",
            "Naruto - 1-AniDub.mka",
            "Naruto - 1(rus).srt",
        ):
            self.assertTrue(is_companion_file_name(name, "Naruto - 1.mkv"), name)

    def test_neighbouring_episodes_are_not_companions(self):
        for name in (
            "Naruto - 10.mkv",
            "Naruto - 10.rus.srt",
            "Naruto - 11.ass",
            "Naruto - 123.mka",
        ):
            self.assertFalse(is_companion_file_name(name, "Naruto - 1.mkv"), name)

    def test_padded_numbering_also_holds(self):
        self.assertTrue(is_companion_file_name("Show - S01E01.eng.srt", "Show - S01E01.mkv"))
        self.assertFalse(is_companion_file_name("Show - S01E010.mkv", "Show - S01E01.mkv"))

    def test_case_insensitive_and_self_excluded(self):
        self.assertTrue(is_companion_file_name("NARUTO - 1.RUS.SRT", "Naruto - 1.mkv"))
        self.assertFalse(is_companion_file_name("Naruto - 1.mkv", "Naruto - 1.mkv"))
        self.assertFalse(is_companion_file_name("Bleach - 1.srt", "Naruto - 1.mkv"))


class TestIterCompanionFiles(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name
        self.names = [
            "Naruto - 1.mkv",
            "Naruto - 1.rus.srt",
            "Naruto - 1.rus.mka",
            "Naruto - 1.jpg",
            "Naruto - 10.mkv",
            "Naruto - 10.rus.srt",
            "Naruto - 11.mkv",
        ]
        for name in self.names:
            with open(os.path.join(self.dir, name), "w", encoding="utf-8") as fh:
                fh.write("x")
        self.episode = os.path.join(self.dir, "Naruto - 1.mkv")

    def tearDown(self):
        self.tmp.cleanup()

    def test_only_own_companions_are_returned(self):
        found = {os.path.basename(p) for p in iter_companion_files(self.episode, COMPANION_EXTENSIONS)}
        self.assertEqual(found, {"Naruto - 1.rus.srt", "Naruto - 1.rus.mka"})

    def test_deletable_set_adds_artwork_but_never_other_episodes(self):
        found = {os.path.basename(p) for p in iter_companion_files(self.episode, DELETABLE_COMPANION_EXTENSIONS)}
        self.assertEqual(found, {"Naruto - 1.rus.srt", "Naruto - 1.rus.mka", "Naruto - 1.jpg"})
        self.assertNotIn("Naruto - 10.mkv", found)
        self.assertNotIn("Naruto - 10.rus.srt", found)

    def test_video_of_another_episode_is_never_collected(self):
        # Раньше удаление первой серии уносило с собой десятую и одиннадцатую.
        for path in iter_companion_files(self.episode, DELETABLE_COMPANION_EXTENSIONS):
            self.assertNotIn("Naruto - 1" + "0", os.path.basename(path))
            self.assertNotIn("Naruto - 1" + "1", os.path.basename(path))


class TestEpisodeNumberInName(unittest.TestCase):
    def test_resolution_and_codec_are_not_episode_numbers(self):
        self.assertFalse(episode_number_in_name("Naruto.1080p.rus.srt", {1}))
        self.assertFalse(episode_number_in_name("Naruto.x264-GROUP.srt", {2}))
        # Ограничение эвристики: в «DDP5.1» цифра окружена нецифрами, поэтому
        # отличить её от номера серии по одному имени файла нельзя. Эта ветка —
        # запасная, она работает только внутри папок Subs/Audio и после того,
        # как разбор имени парсером не дал результата.

    def test_real_episode_numbers_are_found(self):
        self.assertTrue(episode_number_in_name("Naruto - 01.rus.srt", {1}))
        self.assertTrue(episode_number_in_name("S01E01.eng.ass", {1}))
        self.assertTrue(episode_number_in_name("Ep 12.srt", {12}))
        self.assertTrue(episode_number_in_name("Naruto - 012.srt", {12}))

    def test_neighbouring_numbers_do_not_match(self):
        self.assertFalse(episode_number_in_name("Naruto - 10.rus.srt", {1}))
        self.assertFalse(episode_number_in_name("Naruto - 21.rus.srt", {2}))

    def test_empty_input_is_safe(self):
        self.assertFalse(episode_number_in_name("anything.srt", set()))
        self.assertFalse(episode_number_in_name("anything.srt", {None}))
        self.assertFalse(episode_number_in_name("", {1}))


class TestMatchCompanionFilesForEpisode(unittest.TestCase):
    def test_tenth_episode_subtitle_does_not_stick_to_the_first(self):
        video = "/media/Naruto/Сезон 1/Naruto - 1.mkv"
        companions = [
            "/media/Naruto/Сезон 1/Naruto - 1.rus.srt",
            "/media/Naruto/Сезон 1/Naruto - 10.rus.srt",
        ]
        matched = match_companion_files_for_episode(companions, 1, 1, video, total_video_count=12)
        self.assertEqual(matched, ["/media/Naruto/Сезон 1/Naruto - 1.rus.srt"])

    def test_exact_stem_match_still_works(self):
        video = "/media/Show/Season 01/Show - S01E01.mkv"
        companions = ["/media/Show/Season 01/Show - S01E01.srt"]
        matched = match_companion_files_for_episode(companions, 1, 1, video, total_video_count=10)
        self.assertEqual(matched, companions)


if __name__ == "__main__":
    unittest.main()
