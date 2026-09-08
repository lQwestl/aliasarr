import unittest
from unittest.mock import MagicMock

try:
    from app.models.db import Indexer, TrackedRelease, DownloadHistory, User
    from app.api.indexers import delete_indexer
    HAS_DEPS = True
except (ImportError, ModuleNotFoundError):
    HAS_DEPS = False


class TestIndexerEndpoints(unittest.IsolatedAsyncioTestCase):
    def test_delete_indexer_cleans_up_tracked_releases_and_download_history(self):
        if not HAS_DEPS:
            self.skipTest("Dependencies not installed in host runner")
        db = MagicMock()
        indexer = Indexer(id=5, name="Test Indexer", type="torznab", base_url="http://test")
        db.get.return_value = indexer
        
        user = User(id=1, username="admin", password_hash="test", is_admin=True, is_owner=True)
        delete_indexer(indexer_id=5, db=db, current_user=user)
        
        # Verify db.delete was called on indexer
        db.delete.assert_called_once_with(indexer)
        # Verify db.commit was called
        db.commit.assert_called_once()
        # Verify query on TrackedRelease and DownloadHistory
        self.assertGreaterEqual(db.query.call_count, 2)

    async def test_test_indexer_updates_db_status_on_success(self):
        if not HAS_DEPS:
            self.skipTest("Dependencies not installed in host runner")
        from app.api.indexers import test_indexer
        from unittest.mock import AsyncMock, patch

        db = MagicMock()
        indexer = Indexer(id=7, name="Tapochek", type="torznab", base_url="http://test", last_check_ok=False, consecutive_failures=3)
        db.get.return_value = indexer
        user = User(id=1, username="admin", password_hash="test", is_admin=True, is_owner=True)

        mock_client = AsyncMock()
        mock_client.search.return_value = [{"title": "Release 1"}, {"title": "Release 2"}]

        with patch("app.api.indexers.get_indexer_client", return_value=mock_client):
            res = await test_indexer(indexer_id=7, db=db, current_user=user)

        self.assertTrue(res["success"])
        self.assertIn("найдено релизов: 2", res["message"])
        self.assertTrue(indexer.last_check_ok)
        self.assertEqual(indexer.consecutive_failures, 0)
        self.assertIsNotNone(indexer.last_check_at)
        db.commit.assert_called()

    async def test_test_indexer_updates_db_status_on_failure(self):
        if not HAS_DEPS:
            self.skipTest("Dependencies not installed in host runner")
        from app.api.indexers import test_indexer
        from unittest.mock import AsyncMock, patch

        db = MagicMock()
        indexer = Indexer(id=7, name="Tapochek", type="torznab", base_url="http://test", last_check_ok=True, consecutive_failures=0)
        db.get.return_value = indexer
        user = User(id=1, username="admin", password_hash="test", is_admin=True, is_owner=True)

        mock_client = AsyncMock()
        mock_client.search.side_effect = Exception("Connection timed out")

        with patch("app.api.indexers.get_indexer_client", return_value=mock_client):
            res = await test_indexer(indexer_id=7, db=db, current_user=user)

        self.assertFalse(res["success"])
        self.assertIn("Connection timed out", res["message"])
        self.assertFalse(indexer.last_check_ok)
        self.assertEqual(indexer.consecutive_failures, 1)
        self.assertIsNotNone(indexer.last_check_at)
        db.commit.assert_called()


if __name__ == "__main__":
    unittest.main()
