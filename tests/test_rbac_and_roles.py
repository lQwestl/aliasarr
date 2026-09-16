from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock


class TestRBACAndRolePresets(unittest.TestCase):
    def setUp(self):
        try:
            import fastapi  # noqa: F401
            import sqlalchemy  # noqa: F401
            from app.services.user_service import ALL_PERMISSIONS, ROLE_PRESETS, detect_user_role
            self.ALL_PERMISSIONS = ALL_PERMISSIONS
            self.ROLE_PRESETS = ROLE_PRESETS
            self.detect_user_role = detect_user_role
        except ImportError:
            self.skipTest("Dependencies not installed in host runner")

    def test_permissions_and_presets_structure(self):
        """Проверка целостности словаря прав и профилей ролей."""
        self.assertIn("manage_blocklist", self.ALL_PERMISSIONS)
        self.assertIn("manage_quality_profiles", self.ALL_PERMISSIONS)
        self.assertEqual(len(self.ALL_PERMISSIONS), 23)

        for role_key in ("admin", "moderator", "user", "viewer", "custom"):
            self.assertIn(role_key, self.ROLE_PRESETS)
            preset = self.ROLE_PRESETS[role_key]
            self.assertEqual(preset["key"], role_key)
            self.assertTrue(bool(preset["name"]))
            self.assertTrue(bool(preset["description"]))
            self.assertTrue(bool(preset["icon"]))

    def test_detect_user_role_admin_and_owner(self):
        """Администратор и владелец всегда определяются как admin."""
        owner = SimpleNamespace(id=1, username="admin", is_owner=True, is_admin=True, permissions={})
        self.assertEqual(self.detect_user_role(owner), "admin")

        admin = SimpleNamespace(id=2, username="subadmin", is_owner=False, is_admin=True, permissions={})
        self.assertEqual(self.detect_user_role(admin), "admin")

    def test_detect_user_role_moderator(self):
        """Пользователь с правами модератора определяется как moderator."""
        mod_user = SimpleNamespace(
            id=3,
            username="mod",
            is_owner=False,
            is_admin=False,
            permissions=dict(self.ROLE_PRESETS["moderator"]["permissions"]),
        )
        self.assertEqual(self.detect_user_role(mod_user), "moderator")

    def test_detect_user_role_user(self):
        """Пользователь с типовыми правами определяется как user."""
        std_user = SimpleNamespace(
            id=4,
            username="viewer_user",
            is_owner=False,
            is_admin=False,
            permissions=dict(self.ROLE_PRESETS["user"]["permissions"]),
        )
        self.assertEqual(self.detect_user_role(std_user), "user")

    def test_detect_user_role_viewer(self):
        """Пользователь с правами только для чтения определяется как viewer."""
        view_user = SimpleNamespace(
            id=5,
            username="guest",
            is_owner=False,
            is_admin=False,
            permissions=dict(self.ROLE_PRESETS["viewer"]["permissions"]),
        )
        self.assertEqual(self.detect_user_role(view_user), "viewer")

    def test_detect_user_role_custom(self):
        """Пользователь с нестандартным набором прав определяется как custom."""
        custom_user = SimpleNamespace(
            id=6,
            username="custom_dev",
            is_owner=False,
            is_admin=False,
            permissions={"view_library": True, "manage_backups": True},
        )
        self.assertEqual(self.detect_user_role(custom_user), "custom")

    def test_presets_api_endpoint(self):
        """Эндпоинт GET /api/v1/users/roles/presets возвращает список пресетов."""
        try:
            from app.api.users_routes import get_role_presets
        except ImportError:
            self.skipTest("FastAPI/Dependencies not installed on local host")
        admin_user = SimpleNamespace(id=1, username="admin", is_owner=True, is_admin=True)
        presets = get_role_presets(current_user=admin_user)
        self.assertIsInstance(presets, list)
        keys = [p["key"] for p in presets]
        self.assertEqual(keys, ["admin", "moderator", "user", "viewer", "custom"])

    def test_create_user_with_role_preset(self):
        """Создание пользователя с указанием роли корректно применяет набор прав."""
        try:
            from app.api.users_routes import UserCreate, create_user
        except ImportError:
            self.skipTest("FastAPI/Dependencies not installed on local host")

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None
        mock_req = MagicMock()

        admin_user = SimpleNamespace(id=1, username="admin", is_owner=True, is_admin=True)

        payload = UserCreate(
            username="moderator_test",
            password="password123",
            role="moderator",
        )

        resp = create_user(payload=payload, request=mock_req, current_user=admin_user, db=mock_db)
        self.assertEqual(resp["username"], "moderator_test")
        self.assertEqual(resp["role"], "moderator")
        self.assertFalse(resp["is_admin"])
        self.assertTrue(resp["permissions"]["manage_blocklist"])
        self.assertTrue(resp["permissions"]["manage_quality_profiles"])
        self.assertFalse(resp["permissions"]["manage_settings"])

    def test_format_user_out_auth_me(self):
        """_format_user_out возвращает корректное поле role."""
        try:
            from app.api.auth_routes import _format_user_out
        except ImportError:
            self.skipTest("FastAPI/Dependencies not installed on local host")

        mod = SimpleNamespace(
            id=10,
            username="mod_test",
            display_name="Mod",
            is_owner=False,
            is_admin=False,
            avatar=None,
            enabled=True,
            session_timeout_minutes=43200,
            api_key=None,
            totp_enabled=False,
            totp_confirmed_at=None,
            created_at=None,
            last_login_at=None,
            permissions=dict(self.ROLE_PRESETS["moderator"]["permissions"]),
        )
        out = _format_user_out(mod)
        self.assertEqual(out["role"], "moderator")


if __name__ == "__main__":
    unittest.main()
