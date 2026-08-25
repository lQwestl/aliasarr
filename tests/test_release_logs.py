from __future__ import annotations

import unittest
from unittest.mock import MagicMock

try:
    from fastapi import HTTPException
    from app.models.db import ReleaseLog, User
    from app.services.release_log_service import log_release_event, purge_old_release_logs
    from app.services.user_service import ALL_PERMISSIONS, require_permission, require_any_permission
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

    def test_release_logs_permissions_rbac(self):
        if not HAS_DEPS:
            self.skipTest("Dependencies not installed in host runner")

        self.assertIn("view_release_logs", ALL_PERMISSIONS)
        self.assertIn("manage_release_logs", ALL_PERMISSIONS)

        # 1. Admin user has access to everything
        admin_user = User(id=1, username="admin", is_admin=True, is_owner=True, permissions={})
        dep_view = require_any_permission("view_release_logs", "manage_release_logs")
        dep_manage = require_permission("manage_release_logs")

        self.assertEqual(dep_view(admin_user), admin_user)
        self.assertEqual(dep_manage(admin_user), admin_user)

        # 2. Viewer user with view_release_logs only
        viewer_user = User(id=2, username="viewer", is_admin=False, is_owner=False, permissions={"view_release_logs": True})
        self.assertEqual(dep_view(viewer_user), viewer_user)
        with self.assertRaises(HTTPException) as ctx:
            dep_manage(viewer_user)
        self.assertEqual(ctx.exception.status_code, 403)

        # 3. Manager user with manage_release_logs
        manager_user = User(id=3, username="manager", is_admin=False, is_owner=False, permissions={"manage_release_logs": True})
        self.assertEqual(dep_view(manager_user), manager_user)
        self.assertEqual(dep_manage(manager_user), manager_user)

        # 4. Standard user without release logs permissions
        standard_user = User(id=4, username="user", is_admin=False, is_owner=False, permissions={"view_library": True})
        with self.assertRaises(HTTPException) as ctx1:
            dep_view(standard_user)
        self.assertEqual(ctx1.exception.status_code, 403)

        with self.assertRaises(HTTPException) as ctx2:
            dep_manage(standard_user)
        self.assertEqual(ctx2.exception.status_code, 403)


if __name__ == "__main__":
    unittest.main()
