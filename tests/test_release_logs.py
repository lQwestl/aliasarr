from __future__ import annotations

import unittest
from unittest.mock import MagicMock

try:
    from app.models.db import ReleaseLog
    from app.services.release_log_service import log_release_event, purge_old_release_logs
    HAS_DEPS = True
except ImportError:
    HAS_DEPS = False


class TestReleaseLogs(unittest.TestCase):
    def test_log_release_event_records_entry(self):
        if not HAS_DEPS:
            self.skipTest("Dependencies not installed in host runner")
        mock_db = MagicMock()
        log_release_event(
            stage="match",
            level="success",
            show_title="Test Show",
            show_id=1,
            release_title="Test.Show.S01E01.1080p",
            indexer="RuTracker",
            message="Кандидат успешно сопоставлен",
            details={"score": 100, "seeds": 15},
            db=mock_db,
        )
        self.assertTrue(mock_db.add.called)
        self.assertTrue(mock_db.commit.called)


if __name__ == "__main__":
    unittest.main()
