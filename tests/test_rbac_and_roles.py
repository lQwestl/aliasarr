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

    def test_owner_cannot_demote_self_or_strip_perms(self):
        """Главный администратор не может понизить свою роль, снять админку, отключить себя или изменить свои права."""
        try:
            from app.api.users_routes import UserUpdate, update_user
            from fastapi import HTTPException
        except ImportError:
            self.skipTest("FastAPI/Dependencies not installed on local host")

        owner = SimpleNamespace(
            id=1, username="admin", display_name="Admin", is_owner=True, is_admin=True,
            enabled=True, permissions={perm: True for perm in self.ALL_PERMISSIONS},
            session_timeout_minutes=43200, avatar=None, api_key=None, totp_enabled=False,
            totp_confirmed_at=None, created_at=None, last_login_at=None,
        )
        mock_db = MagicMock()
        mock_db.get.return_value = owner
        mock_req = MagicMock()

        # 1. Попытка снять права администратора
        with self.assertRaises(HTTPException) as ctx:
            update_user(user_id=1, payload=UserUpdate(is_admin=False), request=mock_req, current_user=owner, db=mock_db)
        self.assertEqual(ctx.exception.status_code, 400)

        # 2. Попытка сменить роль
        with self.assertRaises(HTTPException) as ctx:
            update_user(user_id=1, payload=UserUpdate(role="viewer"), request=mock_req, current_user=owner, db=mock_db)
        self.assertEqual(ctx.exception.status_code, 400)

        # 3. Попытка передать permissions
        with self.assertRaises(HTTPException) as ctx:
            update_user(user_id=1, payload=UserUpdate(permissions={"manage_users": False}), request=mock_req, current_user=owner, db=mock_db)
        self.assertEqual(ctx.exception.status_code, 400)

        # 4. Попытка отключить учётную запись
        with self.assertRaises(HTTPException) as ctx:
            update_user(user_id=1, payload=UserUpdate(enabled=False), request=mock_req, current_user=owner, db=mock_db)
        self.assertEqual(ctx.exception.status_code, 400)

        # 5. Смена отображаемого имени разрешена
        resp = update_user(user_id=1, payload=UserUpdate(display_name="SuperAdmin"), request=mock_req, current_user=owner, db=mock_db)
        self.assertEqual(resp["display_name"], "SuperAdmin")
        self.assertTrue(resp["is_admin"])
        self.assertTrue(resp["is_owner"])

    def test_subadmin_cannot_grant_admin_role(self):
        """Суб-администратор не может создать или назначить другого администратора."""
        try:
            from app.api.users_routes import UserCreate, UserUpdate, create_user, update_user
            from fastapi import HTTPException
        except ImportError:
            self.skipTest("FastAPI/Dependencies not installed on local host")

        subadmin = SimpleNamespace(
            id=2, username="subadmin", display_name="SubAdmin", is_owner=False, is_admin=True,
            enabled=True, permissions={perm: True for perm in self.ALL_PERMISSIONS},
        )
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None
        mock_req = MagicMock()

        # Попытка создать админа через is_admin=True
        with self.assertRaises(HTTPException) as ctx:
            create_user(payload=UserCreate(username="newadmin", password="password123", is_admin=True), request=mock_req, current_user=subadmin, db=mock_db)
        self.assertEqual(ctx.exception.status_code, 403)

        # Попытка создать админа через role="admin"
        with self.assertRaises(HTTPException) as ctx:
            create_user(payload=UserCreate(username="newadmin2", password="password123", role="admin"), request=mock_req, current_user=subadmin, db=mock_db)
        self.assertEqual(ctx.exception.status_code, 403)

        # Попытка повысить обычного пользователя до админа
        regular_user = SimpleNamespace(
            id=3, username="user3", display_name="User3", is_owner=False, is_admin=False,
            enabled=True, permissions={}, session_timeout_minutes=43200, avatar=None,
            api_key=None, totp_enabled=False, totp_confirmed_at=None, created_at=None, last_login_at=None,
        )
        mock_db.get.return_value = regular_user
        with self.assertRaises(HTTPException) as ctx:
            update_user(user_id=3, payload=UserUpdate(is_admin=True), request=mock_req, current_user=subadmin, db=mock_db)
        self.assertEqual(ctx.exception.status_code, 403)

    def test_subadmin_cannot_modify_delete_or_reset_other_admin(self):
        """Суб-администратор не может изменять, сбрасывать пароль или удалять другого администратора."""
        try:
            from app.api.users_routes import UserUpdate, UserPasswordReset, update_user, delete_user, reset_user_password
            from fastapi import HTTPException
        except ImportError:
            self.skipTest("FastAPI/Dependencies not installed on local host")

        subadmin1 = SimpleNamespace(id=2, username="subadmin1", is_owner=False, is_admin=True)
        other_admin = SimpleNamespace(
            id=3, username="subadmin2", display_name="SubAdmin2", is_owner=False, is_admin=True,
            enabled=True, permissions={}, session_timeout_minutes=43200, avatar=None,
            api_key=None, totp_enabled=False, totp_confirmed_at=None, created_at=None, last_login_at=None,
        )
        mock_db = MagicMock()
        mock_db.get.return_value = other_admin
        mock_req = MagicMock()

        # 1. Попытка редактировать другого администратора
        with self.assertRaises(HTTPException) as ctx:
            update_user(user_id=3, payload=UserUpdate(display_name="Hacked"), request=mock_req, current_user=subadmin1, db=mock_db)
        self.assertEqual(ctx.exception.status_code, 403)

        # 2. Попытка удалить другого администратора
        with self.assertRaises(HTTPException) as ctx:
            delete_user(user_id=3, request=mock_req, current_user=subadmin1, db=mock_db)
        self.assertEqual(ctx.exception.status_code, 403)

        # 3. Попытка сбросить пароль другому администратору
        with self.assertRaises(HTTPException) as ctx:
            reset_user_password(user_id=3, payload=UserPasswordReset(new_password="new-secret-pwd"), request=mock_req, current_user=subadmin1, db=mock_db)
        self.assertEqual(ctx.exception.status_code, 403)

    def test_subadmin_cannot_change_own_role_or_perms(self):
        """Суб-администратор не может изменять собственные права, роль или отключать себя."""
        try:
            from app.api.users_routes import UserUpdate, update_user
            from fastapi import HTTPException
        except ImportError:
            self.skipTest("FastAPI/Dependencies not installed on local host")

        subadmin = SimpleNamespace(
            id=2, username="subadmin", display_name="SubAdmin", is_owner=False, is_admin=True,
            enabled=True, permissions={perm: True for perm in self.ALL_PERMISSIONS},
            session_timeout_minutes=43200, avatar=None, api_key=None, totp_enabled=False,
            totp_confirmed_at=None, created_at=None, last_login_at=None,
        )
        mock_db = MagicMock()
        mock_db.get.return_value = subadmin
        mock_req = MagicMock()

        # Попытка изменить роль
        with self.assertRaises(HTTPException) as ctx:
            update_user(user_id=2, payload=UserUpdate(role="viewer"), request=mock_req, current_user=subadmin, db=mock_db)
        self.assertEqual(ctx.exception.status_code, 400)

        # Попытка изменить права
        with self.assertRaises(HTTPException) as ctx:
            update_user(user_id=2, payload=UserUpdate(permissions={"view_library": False}), request=mock_req, current_user=subadmin, db=mock_db)
        self.assertEqual(ctx.exception.status_code, 400)

        # Попытка отключить себя
        with self.assertRaises(HTTPException) as ctx:
            update_user(user_id=2, payload=UserUpdate(enabled=False), request=mock_req, current_user=subadmin, db=mock_db)
        self.assertEqual(ctx.exception.status_code, 400)

        # Смена своего отображаемого имени разрешена
        resp = update_user(user_id=2, payload=UserUpdate(display_name="UpdatedSubAdmin"), request=mock_req, current_user=subadmin, db=mock_db)
        self.assertEqual(resp["display_name"], "UpdatedSubAdmin")

    def test_owner_can_manage_subadmins(self):
        """Главный администратор может редактировать и удалять суб-администраторов."""
        try:
            from app.api.users_routes import UserUpdate, update_user, delete_user
        except ImportError:
            self.skipTest("FastAPI/Dependencies not installed on local host")

        owner = SimpleNamespace(id=1, username="admin", is_owner=True, is_admin=True)
        subadmin = SimpleNamespace(
            id=2, username="subadmin", display_name="SubAdmin", is_owner=False, is_admin=True,
            enabled=True, permissions={perm: True for perm in self.ALL_PERMISSIONS},
            session_timeout_minutes=43200, avatar=None, api_key=None, totp_enabled=False,
            totp_confirmed_at=None, created_at=None, last_login_at=None,
        )
        mock_db = MagicMock()
        mock_db.get.return_value = subadmin
        mock_req = MagicMock()

        # Главный администратор может понизить суб-администратора до роли viewer
        resp = update_user(user_id=2, payload=UserUpdate(role="viewer"), request=mock_req, current_user=owner, db=mock_db)
        self.assertEqual(resp["role"], "viewer")
        self.assertFalse(resp["is_admin"])

        # Главный администратор может удалить суб-администратора
        delete_user(user_id=2, request=mock_req, current_user=owner, db=mock_db)
        mock_db.delete.assert_called_with(subadmin)


if __name__ == "__main__":
    unittest.main()
