from __future__ import annotations

import asyncio
import datetime as dt
import os
import shutil
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.download_client import TorrentInfo, TransmissionClient, QBittorrentClient
from app.services.downloads_monitor import (
    _check_seeding_torrents,
    check_downloads,
    is_unregistered_torrent_error,
    clear_unregistered_and_healed_torrents,
)
try:
    import fastapi
    from app.api.operations import resume_queue_item
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False


class TestUnregisteredTorrentsAndHealing(unittest.TestCase):
    def setUp(self):
        # Мок базы данных не может ответить на запрос к черному списку, поэтому
        # тест явно объявляет его пустым (раньше это угадывал продакшн-код).
        _blocklist = patch("app.services.blocklist_service.is_release_blocked", return_value=(False, None))
        _blocklist.start()
        self.addCleanup(_blocklist.stop)
        clear_unregistered_and_healed_torrents()

    def tearDown(self):
        clear_unregistered_and_healed_torrents()

    def test_is_unregistered_torrent_error(self):
        """Проверяет распознавание различных вариантов сообщений об unregistered torrent."""
        self.assertTrue(is_unregistered_torrent_error("Announce error: unregistered torrent"))
        self.assertTrue(is_unregistered_torrent_error("Torrent not registered, info_hash = 123"))
        self.assertTrue(is_unregistered_torrent_error("торрент не зарегистрирован на трекере"))
        self.assertTrue(is_unregistered_torrent_error("Tracker: Torrent not found"))
        self.assertTrue(is_unregistered_torrent_error("UNREGISTERED"))

        self.assertFalse(is_unregistered_torrent_error(None))
        self.assertFalse(is_unregistered_torrent_error(""))
        self.assertFalse(is_unregistered_torrent_error("Connection timed out"))
        self.assertFalse(is_unregistered_torrent_error("HTTP 502 Bad Gateway"))

    def test_seeding_torrent_removed_on_second_unregistered_error(self):
        """Проверяет, что сидирующаяся раздача с ошибкой unregistered torrent не удаляется с первого раза (grace period),
        но удаляется из клиента на втором цикле подтверждения."""
        db_mock = MagicMock()
        dc = SimpleNamespace(id=1, name="Transmission", type="transmission", enabled=True, seed_time_limit=None, seed_ratio_limit=None)
        indexer = SimpleNamespace(id=5, name="Tapochek", enable_seeding=True, seed_ratio_limit=None, seed_time_limit_hours=None)
        dh = SimpleNamespace(id=10, show_id=1, indexer_id=5, torrent_hash="tapochek_dead_hash")

        db_mock.query.return_value.filter.return_value.order_by.return_value.first.return_value = dh
        db_mock.query.return_value.filter.return_value.count.return_value = 0
        db_mock.get.side_effect = lambda model, obj_id: indexer if obj_id == 5 else None

        t_dead = TorrentInfo(
            hash="tapochek_dead_hash",
            name="Dead.Anime.S01.1080p",
            progress=1.0,
            state="seeding",
            save_path="/downloads",
            size=5000000,
            ratio=0.1,
            seeding_time=1200,
            error=2,
            error_string="Announce error: unregistered torrent",
        )

        mock_client = AsyncMock()
        mock_client.list_torrents.return_value = [t_dead]

        with patch("app.services.downloads_monitor.get_client", return_value=mock_client), \
             patch("app.services.downloads_monitor.log_release_event"):
            # Цикл 1: первая фиксация ошибки — раздача НЕ должна быть удалена сразу (grace period)
            asyncio.run(_check_seeding_torrents(db_mock, [dc]))
            mock_client.remove_torrent.assert_not_called()

            # Цикл 2: подтверждение ошибки — раздача должна быть удалена
            asyncio.run(_check_seeding_torrents(db_mock, [dc]))
            mock_client.remove_torrent.assert_called_once_with("tapochek_dead_hash", delete_files=True)

    def test_seeding_torrent_auto_healed_when_paused_without_limits_reached(self):
        """Проверяет автолечение: завершенная раздача на паузе (pausedup) без превышения лимитов
        автоматически запускается заново с обновлением лимитов сидирования."""
        db_mock = MagicMock()
        dc = SimpleNamespace(id=1, name="Transmission", type="transmission", enabled=True, seed_time_limit=None, seed_ratio_limit=None)
        indexer = SimpleNamespace(id=7, name="Tracker", enable_seeding=True, seed_ratio_limit=2.0, seed_time_limit_hours=24)
        dh = SimpleNamespace(id=20, show_id=2, indexer_id=7, torrent_hash="paused_seed_hash")

        db_mock.query.return_value.filter.return_value.order_by.return_value.first.return_value = dh
        db_mock.query.return_value.filter.return_value.count.return_value = 0
        db_mock.get.side_effect = lambda model, obj_id: indexer if obj_id == 7 else None

        t_paused = TorrentInfo(
            hash="paused_seed_hash",
            name="Valid.Show.S01.1080p",
            progress=1.0,
            state="pausedup",
            save_path="/downloads",
            size=5000000,
            ratio=0.5,           # 0.5 < 2.0 (лимит не исчерпан)
            seeding_time=3600,   # 1ч < 24ч (лимит не исчерпан)
            error=0,
            error_string=None,
        )

        mock_client = AsyncMock()
        mock_client.list_torrents.return_value = [t_paused]

        with patch("app.services.downloads_monitor.get_client", return_value=mock_client):
            asyncio.run(_check_seeding_torrents(db_mock, [dc]))

            # Должно быть вызвано обновление лимитов и resume_torrent
            mock_client.set_seeding_limits.assert_called_once_with("paused_seed_hash", seed_ratio_limit=2.0, seed_time_limit_minutes=1440)
            mock_client.resume_torrent.assert_called_once_with("paused_seed_hash")
            mock_client.remove_torrent.assert_not_called()

    def test_downloading_torrent_cancelled_and_episodes_reset_on_unregistered_error(self):
        """Проверяет, что недокачанная раздача с ошибкой unregistered torrent на 2 цикле
        удаляется, серии сбрасываются в wanted, хэш блокируется и запускается автопоиск."""
        show = SimpleNamespace(id=1, title="Test Anime Show", content_type="anime", monitored=True)
        dc = SimpleNamespace(id=10, name="Transmission", type="transmission", enabled=True)
        ep = SimpleNamespace(
            id=101, show_id=1, season_number=1, episode_number=3,
            status="downloading", torrent_hash="downloading_dead_hash",
            download_client_id=10, download_progress=0.45,
            air_date=dt.date.today() - dt.timedelta(days=5),
        )

        db_mock = MagicMock()
        db_mock.query.return_value.filter.return_value.all.return_value = [ep]
        db_mock.get.return_value = show

        t_incomplete_dead = TorrentInfo(
            hash="downloading_dead_hash",
            name="Anime.Show.E03.1080p",
            progress=0.45,
            state="downloading",
            save_path="/downloads",
            size=1000000,
            error=2,
            error_string="Announce error: unregistered torrent",
        )

        mock_client = AsyncMock()
        mock_client.list_torrents.return_value = [t_incomplete_dead]

        settings = SimpleNamespace(root_folder="", download_folder_anime="")

        with patch("app.services.downloads_monitor.get_or_create_settings", return_value=settings), \
             patch("app.services.downloads_monitor.get_client", return_value=mock_client), \
             patch("app.services.downloads_monitor._check_seeding_torrents"), \
             patch("app.services.downloads_monitor.log_release_event"), \
             patch("app.services.blocklist_service.add_to_blocklist") as mock_blocklist, \
             patch("app.services.downloads_monitor._trigger_auto_search_for_show") as mock_auto_search:

            # Цикл 1: первая фиксация — не удаляем (grace period)
            db_mock.query.return_value.filter.return_value.all.side_effect = [[ep], [dc]]
            asyncio.run(check_downloads(db_mock))
            mock_client.remove_torrent.assert_not_called()
            self.assertEqual(ep.status, "downloading")

            # Цикл 2: подтверждение ошибки
            db_mock.query.return_value.filter.return_value.all.side_effect = [[ep], [dc]]
            asyncio.run(check_downloads(db_mock))

            mock_client.remove_torrent.assert_called_once_with("downloading_dead_hash", delete_files=True)
            mock_blocklist.assert_called_once()
            self.assertEqual(ep.status, "wanted")
            self.assertEqual(ep.download_progress, 0.0)
            self.assertIsNone(ep.torrent_hash)
            self.assertIsNone(ep.download_client_id)

    @unittest.skipUnless(HAS_FASTAPI, "Requires fastapi")
    def test_resume_queue_item_resets_limits_and_uses_torrent_start_now(self):
        """Проверяет, что resume_queue_item сбрасывает устаревшие лимиты сидирования
        и для Transmission вызывает torrent-start-now."""
        client = TransmissionClient("127.0.0.1", 9091, "admin", "admin")
        dc = SimpleNamespace(id=1, name="Transmission", type="transmission", enabled=True, seed_time_limit=None, seed_ratio_limit=None)
        indexer = SimpleNamespace(id=3, name="Tracker", enable_seeding=True, seed_ratio_limit=1.5, seed_time_limit_hours=12)
        dh = SimpleNamespace(id=1, torrent_hash="hash_resume_test", indexer_id=3)

        db_mock = MagicMock()
        db_mock.query.return_value.filter.return_value.order_by.return_value.first.return_value = dh
        db_mock.query.return_value.filter.return_value.all.return_value = [dc]
        db_mock.get.side_effect = lambda model, obj_id: indexer if obj_id == 3 else None

        with patch("app.api.operations.get_client", return_value=client), \
             patch.object(client, "_rpc_call", new_callable=AsyncMock) as mock_rpc:

            user_mock = MagicMock()
            res = asyncio.run(resume_queue_item("hash_resume_test", db=db_mock, current_user=user_mock))
            self.assertEqual(res["status"], "resumed")

            # Проверяем вызовы RPC
            # 1. torrent-set для сброса лимитов
            # 2. torrent-start-now для принудительного старта
            calls = mock_rpc.call_args_list
            methods = [c[0][0] for c in calls]
            self.assertIn("torrent-set", methods)
            self.assertIn("torrent-start-now", methods)

            # Проверяем аргументы torrent-set
            set_call = [c for c in calls if c[0][0] == "torrent-set"][0]
            self.assertEqual(set_call[0][1]["seedRatioLimit"], 1.5)
            self.assertEqual(set_call[0][1]["seedRatioMode"], 1)
            self.assertNotIn("seedIdleLimit", set_call[0][1])
            self.assertEqual(set_call[0][1]["seedIdleMode"], 2)

    def test_transmission_set_seeding_limits_unlimited_overrides_global(self):
        """Проверяет, что при отсутствии ограничений выставляются seedRatioMode=2 и seedIdleMode=2 (unlimited)."""
        client = TransmissionClient("127.0.0.1", 9091, "admin", "admin")
        with patch.object(client, "_rpc_call", new_callable=AsyncMock) as mock_rpc:
            asyncio.run(client.set_seeding_limits("hash_unlimited", seed_ratio_limit=None, seed_time_limit_minutes=None))
            mock_rpc.assert_called_once_with("torrent-set", {
                "ids": ["hash_unlimited"],
                "seedRatioMode": 2,
                "seedIdleMode": 2,
            })

    def test_transmission_resume_torrent_uses_start_now(self):
        """Проверяет прямой вызов TransmissionClient.resume_torrent с torrent-start-now."""
        client = TransmissionClient("127.0.0.1", 9091, "admin", "admin")
        with patch.object(client, "_rpc_call", new_callable=AsyncMock) as mock_rpc:
            asyncio.run(client.resume_torrent("hash_start_now"))
            mock_rpc.assert_called_once_with("torrent-start-now", {"ids": ["hash_start_now"]})


if __name__ == "__main__":
    unittest.main()
