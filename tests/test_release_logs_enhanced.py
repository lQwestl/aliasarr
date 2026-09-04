from __future__ import annotations

import unittest
from dataclasses import dataclass
from typing import Optional
from app.services.auto_search import evaluate_torrent_file_priority


@dataclass
class MockEpisode:
    id: int
    season_number: int
    episode_number: int
    title: Optional[str] = None
    absolute_number: Optional[int] = None


class TestReleaseLogsEnhanced(unittest.TestCase):
    def test_evaluate_torrent_file_priority_with_reasons(self):
        # Mock episode targets: Ep 1 wanted, Ep 2 existing
        ep1 = MockEpisode(id=1, season_number=1, episode_number=1)
        ep2 = MockEpisode(id=2, season_number=1, episode_number=2)
        all_eps = [ep1, ep2]
        wanted_eps = [ep1]

        out_reasons = {}

        # 1. Wanted episode file
        prio_wanted = evaluate_torrent_file_priority(
            file_name="Show.S01E01.1080p.mkv",
            file_index=0,
            target_episodes=wanted_eps,
            all_show_episodes=all_eps,
            out_file_reasons=out_reasons,
        )
        self.assertEqual(prio_wanted, 1)
        self.assertIn("разыскивается", out_reasons[0])

        # 2. Episode file not wanted
        prio_unwanted = evaluate_torrent_file_priority(
            file_name="Show.S01E02.1080p.mkv",
            file_index=1,
            target_episodes=wanted_eps,
            all_show_episodes=all_eps,
            out_file_reasons=out_reasons,
        )
        self.assertEqual(prio_unwanted, 0)
        self.assertIn("не входит в список разыскиваемых", out_reasons[1])

        # 3. Wrong season file
        prio_wrong_s = evaluate_torrent_file_priority(
            file_name="Show.S02E01.1080p.mkv",
            file_index=2,
            target_episodes=wanted_eps,
            all_show_episodes=all_eps,
            out_file_reasons=out_reasons,
        )
        self.assertEqual(prio_wrong_s, 0)
        self.assertTrue("S02" in out_reasons[2] and "не входит в список разыскиваемых" in out_reasons[2])

        # 4. Sample video file (without target episode match)
        prio_sample = evaluate_torrent_file_priority(
            file_name="Sample/sample.mkv",
            file_index=3,
            target_episodes=wanted_eps,
            all_show_episodes=all_eps,
            out_file_reasons=out_reasons,
        )
        self.assertEqual(prio_sample, 0)
        self.assertTrue("Sample" in out_reasons[3] or "сэмпл" in out_reasons[3] or "ОТКЛЮЧЕН" in out_reasons[3])

    def test_evaluate_torrent_file_priority_subtitles_and_extras(self):
        ep1 = MockEpisode(id=1, season_number=1, episode_number=1)
        wanted_eps = [ep1]
        out_reasons = {}

        # 1. Subtitles for wanted episode
        prio_sub_wanted = evaluate_torrent_file_priority(
            file_name="Subs/Show.S01E01.rus.ass",
            file_index=0,
            target_episodes=wanted_eps,
            import_extra_files=True,
            out_file_reasons=out_reasons,
        )
        self.assertEqual(prio_sub_wanted, 1)
        self.assertIn("Сопутствующий файл", out_reasons[0])
        self.assertIn("ВКЛЮЧЕН", out_reasons[0])

        # 2. Subtitles for unwanted episode
        prio_sub_unwanted = evaluate_torrent_file_priority(
            file_name="Subs/Show.S01E02.rus.ass",
            file_index=1,
            target_episodes=wanted_eps,
            import_extra_files=True,
            out_file_reasons=out_reasons,
        )
        self.assertEqual(prio_sub_unwanted, 0)
        self.assertIn("ОТКЛЮЧЕН", out_reasons[1])


if __name__ == "__main__":
    unittest.main()
