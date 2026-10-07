from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_JS_PATH = ROOT / "web" / "js" / "app.js"
INDEX_PATH = ROOT / "web" / "index.html"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class TestFrontendUserProtection(unittest.TestCase):
    def setUp(self):
        self.app_js = read(APP_JS_PATH)
        self.index_html = read(INDEX_PATH)

    def test_html_contains_self_perm_hint(self):
        """Индикатор-подсказка заблокированных прав присутствует в разметке формы."""
        self.assertIn('id="user-form-self-perm-hint"', self.index_html)
        self.assertIn('id="user-form-role-presets"', self.index_html)
        self.assertIn('id="user-form-permissions-box"', self.index_html)

    def test_edit_user_guards_self_and_owner(self):
        """Функция editUser блокирует редактирование прав при редактировании себя или главного администратора."""
        self.assertIn("const isEditingSelf = CURRENT_USER && CURRENT_USER.id === u.id;", self.app_js)
        self.assertIn("const isTargetOwner = !!u.is_owner;", self.app_js)
        self.assertIn("const blockPermissions = isEditingSelf || isTargetOwner;", self.app_js)
        self.assertIn("Главный администратор обладает всеми правами системы", self.app_js)
        self.assertIn("Вы не можете изменять собственные права доступа и роль администратора", self.app_js)

    def test_submit_user_omits_privilege_fields_for_self_and_owner(self):
        """Функция submitUser не отправляет role, is_admin и permissions для себя или главного администратора."""
        self.assertIn("const isEditingSelf = CURRENT_USER && CURRENT_USER.id === EDITING_USER_ID;", self.app_js)
        self.assertIn("const isTargetOwner = !!EDITING_USER_IS_OWNER;", self.app_js)
        self.assertIn("if (!isEditingSelf && !isTargetOwner)", self.app_js)
        self.assertIn("payload.role = role;", self.app_js)
        self.assertIn("payload.is_admin = isAdmin;", self.app_js)
        self.assertIn("payload.permissions = perms;", self.app_js)

    def test_select_role_preset_blocks_subadmin_admin_grant(self):
        """Пресет роли 'admin' не может быть выбран суб-администратором."""
        self.assertIn('if (roleKey === "admin" && !isCurrentUserOwner)', self.app_js)
        self.assertIn("Назначать администраторов может только главный администратор", self.app_js)

    def test_load_users_table_action_guards(self):
        """Таблица пользователей скрывает управление (сброс пароля, 2FA, удаление, редактирование) других администраторов от суб-администраторов."""
        self.assertIn("const canManageTotp = isCurrentUserOwner || (!isTargetOwner && !isTargetAdmin);", self.app_js)
        self.assertIn("const canResetPwd = isCurrentUserOwner || (!isTargetOwner && !isTargetAdmin);", self.app_js)
        self.assertIn("const canEditUser = isCurrentUserOwner || !isTargetAdmin || isSelf;", self.app_js)
        self.assertIn("const canDeleteUser = !isTargetOwner && !isSelf && (isCurrentUserOwner || !isTargetAdmin);", self.app_js)

    def test_reset_form_disables_admin_for_subadmins(self):
        """При сбросе формы назначение роли админа блокируется, если текущий пользователь не владелец."""
        self.assertIn("adminCb.disabled = !isCurrentUserOwner;", self.app_js)
        self.assertIn("c.style.pointerEvents = \"none\";", self.app_js)


if __name__ == "__main__":
    unittest.main()
