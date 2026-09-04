import unittest
from unittest.mock import MagicMock

try:
    from fastapi import HTTPException
    from app.models.db import AppSettings
    from app.api.settings_routes import update_settings, SettingsUpdate
    HAS_DEPS = True
except ImportError:
    HAS_DEPS = False


class TestSettingsScrollbar(unittest.TestCase):
    def setUp(self):
        if not HAS_DEPS:
            self.skipTest("Dependencies not installed in host runner")
    def test_app_settings_default_scrollbar_mode(self):
        settings = AppSettings(id=1, api_key="test_key")
        self.assertEqual(settings.scrollbar_mode, "autohide")

    def test_update_settings_scrollbar_mode_valid(self):
        settings = AppSettings(id=1, api_key="test_key", scrollbar_mode="autohide")
        mock_db = MagicMock()
        mock_request = MagicMock()
        mock_user = MagicMock()

        for mode in ("autohide", "styled", "hidden", "native"):
            with unittest.mock.patch("app.api.settings_routes.get_or_create_settings", return_value=settings):
                payload = SettingsUpdate(scrollbar_mode=mode)
                update_settings(payload=payload, request=mock_request, db=mock_db, current_user=mock_user)
                self.assertEqual(settings.scrollbar_mode, mode)

    def test_update_settings_scrollbar_mode_invalid(self):
        settings = AppSettings(id=1, api_key="test_key", scrollbar_mode="autohide")
        mock_db = MagicMock()
        mock_request = MagicMock()
        mock_user = MagicMock()

        with unittest.mock.patch("app.api.settings_routes.get_or_create_settings", return_value=settings):
            payload = SettingsUpdate(scrollbar_mode="unknown_mode")
            with self.assertRaises(HTTPException) as ctx:
                update_settings(payload=payload, request=mock_request, db=mock_db, current_user=mock_user)
            self.assertEqual(ctx.exception.status_code, 400)
