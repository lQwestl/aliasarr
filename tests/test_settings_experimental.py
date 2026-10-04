import unittest
from unittest.mock import MagicMock

try:
    from fastapi import HTTPException
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.models.db import Base, AppSettings, User
    from app.services.settings_service import get_or_create_settings
    from app.api.settings_routes import update_settings, SettingsUpdate, get_settings
    HAS_DEPS = True
except ImportError:
    HAS_DEPS = False


class TestSettingsExperimental(unittest.TestCase):
    def setUp(self):
        if not HAS_DEPS:
            self.skipTest("Dependencies not installed in host runner")
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()
        self.user = User(
            id=1,
            username="admin",
            is_admin=True,
            enabled=True,
            password_hash="hash",
            is_owner=True,
        )
        self.db.add(self.user)
        self.db.commit()

    def tearDown(self):
        if hasattr(self, "db"):
            self.db.close()

    def test_default_enable_remap_button_is_false(self):
        settings = get_or_create_settings(self.db)
        self.assertFalse(settings.enable_remap_button)

        out = get_settings(db=self.db, current_user=self.user)
        self.assertFalse(out.enable_remap_button)

    def test_update_enable_remap_button(self):
        get_or_create_settings(self.db)
        mock_request = MagicMock()

        # Enable remap button
        payload = SettingsUpdate(enable_remap_button=True)
        res = update_settings(payload=payload, request=mock_request, db=self.db, current_user=self.user)
        self.assertTrue(res.enable_remap_button)

        settings = get_or_create_settings(self.db)
        self.assertTrue(settings.enable_remap_button)

        # Disable remap button
        payload = SettingsUpdate(enable_remap_button=False)
        res = update_settings(payload=payload, request=mock_request, db=self.db, current_user=self.user)
        self.assertFalse(res.enable_remap_button)

        settings = get_or_create_settings(self.db)
        self.assertFalse(settings.enable_remap_button)


class TestExperimentalLogicStandalone(unittest.TestCase):
    """Standalone unit test that doesn't depend on external libraries."""
    def test_remap_button_visibility_decision(self):
        def should_show_remap_button(settings_obj, local_storage_dict):
            if settings_obj and hasattr(settings_obj, "enable_remap_button"):
                return bool(settings_obj.enable_remap_button)
            return local_storage_dict.get("aliasarr_enable_remap_button") == "true"

        class MockSettings:
            def __init__(self, remap_enabled):
                self.enable_remap_button = remap_enabled

        # By default, button is hidden
        self.assertFalse(should_show_remap_button(MockSettings(False), {}))
        self.assertFalse(should_show_remap_button(None, {}))
        self.assertFalse(should_show_remap_button(None, {"aliasarr_enable_remap_button": "false"}))

        # When enabled, button is shown
        self.assertTrue(should_show_remap_button(MockSettings(True), {}))
        self.assertTrue(should_show_remap_button(None, {"aliasarr_enable_remap_button": "true"}))


class TestThemeAndDesignSettingsValidation(unittest.TestCase):
    """Unit tests for theme and design system validation in settings."""

    def test_settings_routes_theme_and_design_validation(self):
        with open("app/api/settings_routes.py", "r", encoding="utf-8") as f:
            content = f.read()

        # Verify all 5 themes plus legacy aliases are accepted in validation
        expected_themes = ("slate", "oled", "indigo", "pine", "paper", "dark", "light", "dracula", "obsidian")
        for t in expected_themes:
            self.assertIn(f'"{t}"', content)

        # Verify design systems
        expected_designs = ("modern", "servarr", "studio", "classic", "vanguard")
        for d in expected_designs:
            self.assertIn(f'"{d}"', content)

    def test_daylight_paper_css_adaptation(self):
        with open("web/css/style.css", "r", encoding="utf-8") as f:
            css = f.read()

        # Verify settings-section-card uses CSS variables
        self.assertIn(".settings-section-card {", css)
        self.assertIn("background: var(--panel);", css)

        # Verify :is([data-theme="paper"], [data-theme="light"]) is widespread
        self.assertIn(':is([data-theme="paper"], [data-theme="light"])', css)

        # Verify button contrast and hover in paper mode
        self.assertIn(':is([data-theme="paper"], [data-theme="light"]) .btn-primary', css)
        self.assertIn(':is([data-theme="paper"], [data-theme="light"]) .btn:disabled', css)


if __name__ == "__main__":
    unittest.main()

