import unittest
from unittest.mock import MagicMock

try:
    from app.models.db import Indexer, TrackedRelease, DownloadHistory, User
    from app.api.indexers import delete_indexer
    HAS_DEPS = True
except (ImportError, ModuleNotFoundError):
    HAS_DEPS = False


class TestIndexerDelete(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
