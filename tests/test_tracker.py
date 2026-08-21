import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

try:
    from app.services.tracker import recheck_all_active, recheck_tracked_release
    HAVE_DEPS = True
except Exception:
    HAVE_DEPS = False


class TestTrackerService(unittest.TestCase):
    def setUp(self):
        if not HAVE_DEPS:
            self.skipTest("sqlalchemy or app dependencies not installed in current environment")

    def test_recheck_all_active_without_tracked_releases(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = []
        res = asyncio.run(recheck_all_active(db))
        self.assertEqual(res, [])

    def test_recheck_all_active_with_tracked_releases(self):
        show = SimpleNamespace(id=1, title="Test Anime Series")
        tracked = SimpleNamespace(
            id=101,
            show_id=1,
            show=show,
            indexer_id=5,
            topic_guid="guid-12345",
            topic_url="https://rutracker.org/forum/viewtopic.php?t=12345",
            infohash="abc123hash",
            downloaded_episodes=[{"season": 1, "episode": 1}],
            active=True,
            last_checked_at=None,
            last_updated_at=None,
        )

        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = [tracked]

        with patch("app.services.tracker.recheck_tracked_release", new_callable=AsyncMock) as mock_recheck:
            mock_recheck.return_value = {"updated": False, "new_episodes": []}
            results = asyncio.run(recheck_all_active(db))
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]["tracked_release_id"], 101)
            mock_recheck.assert_awaited_once_with(db, tracked)


if __name__ == "__main__":
    unittest.main()
