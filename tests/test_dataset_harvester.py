from __future__ import annotations

import unittest
try:
    from app.api.dataset_routes import _analyze_record, _compute_stats
    HAS_DEPS = True
except ImportError:
    HAS_DEPS = False

class TestDatasetHarvester(unittest.TestCase):
    def test_analyze_record_video_part2(self):
        if not HAS_DEPS:
            self.skipTest("FastAPI not installed in host test environment")
        rec = {
            "title": "Re:Zero — жизнь с нуля в другом мире (ТВ-2, часть 2) / Re:Zero 2nd Season Part 2 [TV] [12 из 12] [1080p]",
            "indexer": "RuTracker",
            "size_bytes": 15000000000,
            "categories": [],
        }
        res = _analyze_record(rec)
        self.assertTrue(res["is_video"])
        self.assertEqual(res["season"], 2)
        self.assertEqual(res["part"], 2)
        self.assertEqual(res["total_in_part"], 12)
        self.assertEqual(res["status"], "parsed")

    def test_analyze_record_non_video_filter(self):
        if not HAS_DEPS:
            self.skipTest("FastAPI not installed in host test environment")
        rec = {
            "title": "Re:Zero kara Hajimeru Isekai Seikatsu (Soundtrack / OST) [FLAC]",
            "indexer": "RuTracker",
            "size_bytes": 500000000,
            "categories": [],
        }
        res = _analyze_record(rec)
        self.assertFalse(res["is_video"])
        self.assertEqual(res["status"], "non_video")

    def test_compute_stats(self):
        if not HAS_DEPS:
            self.skipTest("FastAPI not installed in host test environment")
        records = [
            {
                "title": "Re:Zero S01E01 1080p",
                "analysis": {"is_video": True, "status": "parsed", "kind": "episode", "episodes": [1], "part": None},
            },
            {
                "title": "Re:Zero S02 Part 2 [12 из 12]",
                "analysis": {"is_video": True, "status": "parsed", "kind": "episode", "episodes": list(range(1, 13)), "part": 2},
            },
            {
                "title": "Re:Zero OST Flac",
                "analysis": {"is_video": False, "status": "non_video", "kind": "non_video"},
            },
            {
                "title": "Some completely unknown random string release",
                "analysis": {"is_video": True, "status": "unknown", "kind": "unknown", "episodes": []},
            },
        ]
        stats = _compute_stats(records)
        self.assertEqual(stats["total_records"], 4)
        self.assertEqual(stats["video_titles"], 3)
        self.assertEqual(stats["non_video_filtered"], 1)
        self.assertEqual(stats["parsed_success"], 2)
        self.assertEqual(stats["unknown_total"], 1)
        self.assertEqual(stats["multi_part_detected"], 1)
        # Accuracy: 2 / 3 = 66.7%
        self.assertEqual(stats["accuracy_pct"], 66.7)

if __name__ == "__main__":
    unittest.main()
