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


    def test_log_release_event_with_session_and_trigger(self):
        if not HAS_DEPS:
            self.skipTest("Dependencies not installed in host runner")
        mock_db = MagicMock()
        log_release_event(
            stage="search",
            level="info",
            show_title="Test Show 2",
            show_id=2,
            release_title="Test.Show.2.S01E01",
            indexer="RuTor",
            session_id="sess_12345",
            trigger="auto_search",
            message="Поиск запущен",
            details={"candidates_count": 5},
            db=mock_db,
        )
        self.assertTrue(mock_db.add.called)
        entry = mock_db.add.call_args[0][0]
        self.assertEqual(entry.session_id, "sess_12345")
        self.assertEqual(entry.trigger, "auto_search")
        self.assertEqual(entry.show_id, 2)

    def test_clear_release_logs_with_show_id(self):
        if not HAS_DEPS:
            self.skipTest("Dependencies not installed in host runner")
        from app.api.release_logs_routes import clear_release_logs

        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_filtered = MagicMock()
        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_filtered
        mock_filtered.delete.return_value = 3

        admin_user = User(id=1, username="admin", is_admin=True, is_owner=True, permissions={})
        res = clear_release_logs(show_id=42, db=mock_db, current_user=admin_user)

        self.assertTrue(res["success"])
        self.assertEqual(res["deleted"], 3)
        self.assertEqual(res["show_id"], 42)
        mock_query.filter.assert_called_once()
        self.assertTrue(mock_db.commit.called)

    def test_export_release_logs_with_show_id(self):
        if not HAS_DEPS:
            self.skipTest("Dependencies not installed in host runner")
        import asyncio
        from app.api.release_logs_routes import export_release_logs
        import datetime as dt

        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_filtered = MagicMock()
        mock_ordered = MagicMock()
        mock_limited = MagicMock()

        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_filtered
        mock_filtered.order_by.return_value = mock_ordered
        mock_ordered.limit.return_value = mock_limited

        dummy_log = ReleaseLog(
            id=1,
            created_at=dt.datetime(2026, 9, 10, 20, 0, 0),
            stage="grab",
            level="success",
            show_id=42,
            show_title="Avatar",
            release_title="Avatar.2025.1080p",
            indexer="RuTracker",
            session_id="sess_abc",
            trigger="auto_search",
            message="Релиз захвачен",
            details={"hash": "abcdef1234567890"}
        )
        mock_limited.all.return_value = [dummy_log]

        admin_user = User(id=1, username="admin", is_admin=True, is_owner=True, permissions={})
        resp = asyncio.run(export_release_logs(show_id=42, db=mock_db, current_user=admin_user))

        self.assertEqual(resp.status_code, 200)
        self.assertIn("Avatar", resp.body.decode("utf-8"))
        self.assertIn("RuTracker", resp.body.decode("utf-8"))
        self.assertIn("attachment; filename=", resp.headers["Content-Disposition"])


if __name__ == "__main__":
    unittest.main()
