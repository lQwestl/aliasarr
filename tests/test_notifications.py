from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, patch

try:
    from app.models.db import NotificationConfig
except ImportError:
    class NotificationConfig:
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)
from app.services.notifications import (
    _NOTIFICATION_DISPATCHERS,
    REQUIRED_NOTIFICATION_FIELDS,
    format_notification_message,
    notify_all,
    send_notification,
)


class TestNotificationSystem(unittest.TestCase):
    def test_providers_registered(self):
        expected_providers = {
            "telegram",
            "discord",
            "gotify",
            "ntfy",
            "pushover",
            "slack",
            "webhook",
            "email",
            "pushbullet",
            "apprise",
            "script",
        }
        for p in expected_providers:
            self.assertIn(p, _NOTIFICATION_DISPATCHERS, f"Provider {p} should be in _NOTIFICATION_DISPATCHERS")
            self.assertIn(p, REQUIRED_NOTIFICATION_FIELDS, f"Provider {p} should have REQUIRED_NOTIFICATION_FIELDS")

    def test_format_notification_message_translations(self):
        ru_msg = "🔔 Тестовое уведомление от Aliasarr — всё работает!"
        en_msg = format_notification_message(ru_msg, lang="en")
        self.assertEqual(en_msg, "🔔 Test notification from Aliasarr — everything works!")

        ru_grab = "Захвачен релиз для Lucifer S01E01, сиды: 50"
        en_grab = format_notification_message(ru_grab, lang="en")
        self.assertEqual(en_grab, "Grabbed release for Lucifer S01E01, seeds: 50")

    def test_notification_config_all_triggers(self):
        cfg = NotificationConfig(
            id=1,
            name="Test Discord",
            type="discord",
            settings={"webhook_url": "https://discord.com/api/webhooks/test"},
            enabled=True,
            on_grab=True,
            on_import=True,
            on_upgrade=True,
            on_rename=False,
            on_series_add=False,
            on_series_delete=False,
            on_episode_file_delete=False,
            on_episode_file_delete_for_upgrade=False,
            on_health_issue=True,
            on_health_restored=False,
            on_application_update=False,
            on_manual_interaction_required=True,
            on_backup=False,
        )
        self.assertTrue(cfg.on_grab)
        self.assertTrue(cfg.on_upgrade)
        self.assertFalse(cfg.on_rename)
        self.assertFalse(cfg.on_backup)

    def test_series_delete_and_backup_translations(self):
        msg_del_files = "🗑 Удалён тайтл «Breaking Bad» (вместе с файлами на диске)"
        en_del_files = format_notification_message(msg_del_files, lang="en")
        self.assertIn("Deleted title 'Breaking Bad' (along with files on disk)", en_del_files)

        msg_del_nofiles = "🗑 Удалена карточка тайтла «Breaking Bad» (файлы сохранены)"
        en_del_nofiles = format_notification_message(msg_del_nofiles, lang="en")
        self.assertIn("Deleted title card 'Breaking Bad' (files kept)", en_del_nofiles)

        msg_backup = "💾 Создан бэкап: backup_2026.zip (1.2 MB)"
        en_backup = format_notification_message(msg_backup, lang="en")
        self.assertIn("Backup created: backup_2026.zip (1.2 MB)", en_backup)

    def test_send_notification_dispatch(self):
        cfg = NotificationConfig(
            id=1,
            name="Test Pushbullet",
            type="pushbullet",
            settings={"api_key": "dummy_key"},
            enabled=True,
        )

        mock_send = AsyncMock()
        with patch.dict(_NOTIFICATION_DISPATCHERS, {"pushbullet": mock_send}):
            asyncio.run(send_notification(cfg, "Hello test", "test"))
            mock_send.assert_called_once()


if __name__ == "__main__":
    unittest.main()
