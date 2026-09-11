from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.download_client import TorrentInfo, QBittorrentClient, TransmissionClient
from app.services.postprocess import transfer_media_file
from app.services.downloads_monitor import _check_seeding_torrents

try:
    import fastapi
    from app.api.operations import get_queue, QueueItemOut
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False


class TestHardlinksAndSeeding(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="aliasarr_hl_test_")
        self.src_dir = os.path.join(self.temp_dir, "downloads")
        self.dst_dir = os.path.join(self.temp_dir, "library")
        os.makedirs(self.src_dir, exist_ok=True)
        os.makedirs(self.dst_dir, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_transfer_media_file_move_when_not_seeding_and_no_hardlinks(self):
        """Без сидирования (keep_source=False) и без хардлинков (use_hardlinks=False) файл перемещается, источник удаляется."""
        src_file = os.path.join(self.src_dir, "episode1.mkv")
        dst_file = os.path.join(self.dst_dir, "Show - S01E01.mkv")
        with open(src_file, "wb") as f:
            f.write(b"video data 12345")

        res = transfer_media_file(src_file, dst_file, keep_source=False, use_hardlinks=False)

        self.assertEqual(res, "move")
        self.assertTrue(os.path.exists(dst_file))
        self.assertFalse(os.path.exists(src_file))
        with open(dst_file, "rb") as f:
            self.assertEqual(f.read(), b"video data 12345")

    def test_transfer_media_file_hardlink_when_hardlinks_enabled(self):
        """При включенных хардлинках создается жесткая ссылка даже если keep_source=False."""
        src_file = os.path.join(self.src_dir, "episode1_hl.mkv")
        dst_file = os.path.join(self.dst_dir, "Show - S01E01_hl.mkv")
        with open(src_file, "wb") as f:
            f.write(b"video data hl")

        res = transfer_media_file(src_file, dst_file, keep_source=False, use_hardlinks=True)

        self.assertEqual(res, "hardlink")
        self.assertTrue(os.path.exists(src_file))
        self.assertTrue(os.path.exists(dst_file))
        self.assertEqual(os.stat(src_file).st_ino, os.stat(dst_file).st_ino)

    def test_transfer_media_file_hardlink_when_seeding(self):
        """При сидировании с включенными хардлинками создается жесткая ссылка (одинаковый inode, 0 доп. байт)."""
        src_file = os.path.join(self.src_dir, "episode2.mkv")
        dst_file = os.path.join(self.dst_dir, "Show - S01E02.mkv")
        with open(src_file, "wb") as f:
            f.write(b"video data episode 2")

        transfer_media_file(src_file, dst_file, keep_source=True, use_hardlinks=True)

        self.assertTrue(os.path.exists(src_file))
        self.assertTrue(os.path.exists(dst_file))
        # На одной ФС inode должны совпадать
        src_stat = os.stat(src_file)
        dst_stat = os.stat(dst_file)
        self.assertEqual(src_stat.st_ino, dst_stat.st_ino)
        self.assertEqual(src_stat.st_nlink, 2)

    def test_transfer_media_file_hardlink_fallback_to_copy_on_error(self):
        """Если os.link падает с ошибкой (например EXDEV), срабатывает fallback на shutil.copy2."""
        src_file = os.path.join(self.src_dir, "episode3.mkv")
        dst_file = os.path.join(self.dst_dir, "Show - S01E03.mkv")
        with open(src_file, "wb") as f:
            f.write(b"video data episode 3")

        with patch("os.link", side_effect=OSError(18, "Invalid cross-device link")):
            transfer_media_file(src_file, dst_file, keep_source=True, use_hardlinks=True)

        self.assertTrue(os.path.exists(src_file))
        self.assertTrue(os.path.exists(dst_file))
        with open(dst_file, "rb") as f:
            self.assertEqual(f.read(), b"video data episode 3")

    def test_transfer_media_file_copy_when_hardlinks_disabled(self):
        """Если use_hardlinks=False и keep_source=True, выполняется обычное копирование."""
        src_file = os.path.join(self.src_dir, "episode4.mkv")
        dst_file = os.path.join(self.dst_dir, "Show - S01E04.mkv")
        with open(src_file, "wb") as f:
            f.write(b"video data episode 4")

        with patch("os.link") as mock_link:
            transfer_media_file(src_file, dst_file, keep_source=True, use_hardlinks=False)
            self.assertFalse(mock_link.called)

        self.assertTrue(os.path.exists(src_file))
        self.assertTrue(os.path.exists(dst_file))

    def test_qbittorrent_set_seeding_limits(self):
        """Проверяет отправку запроса лимитов сидирования в qBittorrent."""
        client = QBittorrentClient("127.0.0.1", 8080, "admin", "adminadmin")

        mock_http_client = AsyncMock()
        mock_httpx_mod = MagicMock()
        mock_httpx_mod.AsyncClient.return_value.__aenter__.return_value = mock_http_client

        with patch("app.services.download_client.httpx", mock_httpx_mod), \
             patch.object(client, "_ensure_auth", new_callable=AsyncMock):
            asyncio.run(client.set_seeding_limits("hash123", seed_ratio_limit=1.5, seed_time_limit_minutes=4320))

            mock_http_client.post.assert_called_once()
            args, kwargs = mock_http_client.post.call_args
            self.assertIn("/api/v2/torrents/setShareLimits", args[0])
            self.assertEqual(kwargs["data"]["hashes"], "hash123")
            self.assertEqual(kwargs["data"]["ratioLimit"], "1.5")
            self.assertEqual(kwargs["data"]["seedingTimeLimit"], "4320")

    def test_transmission_set_seeding_limits(self):
        """Проверяет отправку RPC-запроса лимитов сидирования в Transmission без ошибочного seedIdleLimit."""
        client = TransmissionClient("127.0.0.1", 9091, "admin", "admin")

        with patch.object(client, "_rpc_call", new_callable=AsyncMock) as mock_rpc:
            asyncio.run(client.set_seeding_limits("hash456", seed_ratio_limit=2.0, seed_time_limit_minutes=2880))

            mock_rpc.assert_called_once()
            method, args = mock_rpc.call_args[0]
            self.assertEqual(method, "torrent-set")
            self.assertEqual(args["ids"], ["hash456"])
            self.assertEqual(args["seedRatioLimit"], 2.0)
            self.assertEqual(args["seedRatioMode"], 1)
            self.assertNotIn("seedIdleLimit", args)
            self.assertNotIn("seedIdleMode", args)

    def test_check_seeding_torrents_cleans_up_when_limit_reached(self):
        """Проверяет, что _check_seeding_torrents удаляет раздачу и временные файлы при достижении ratio."""
        db_mock = MagicMock()
        dc = SimpleNamespace(id=1, name="qBit", type="qbittorrent", enabled=True)
        indexer = SimpleNamespace(id=5, name="PrivateTracker", enable_seeding=True, seed_ratio_limit=1.5, seed_time_limit_hours=72)
        dh = SimpleNamespace(id=10, show_id=1, indexer_id=5, torrent_hash="seedhash1")

        db_mock.query.return_value.filter.return_value.order_by.return_value.first.return_value = dh
        db_mock.query.return_value.filter.return_value.count.return_value = 0
        db_mock.get.side_effect = lambda model, obj_id: indexer if obj_id == 5 else None

        torrent_finished = TorrentInfo(
            hash="seedhash1", name="Show.S01.1080p", progress=1.0,
            state="seeding", save_path=self.src_dir, size=5000000,
            ratio=1.6, seeding_time=3600,
        )

        mock_client = AsyncMock()
        mock_client.list_torrents.return_value = [torrent_finished]

        with patch("app.services.downloads_monitor.get_client", return_value=mock_client), \
             patch("app.services.downloads_monitor.log_release_event"):
            asyncio.run(_check_seeding_torrents(db_mock, [dc]))

        mock_client.remove_torrent.assert_called_once_with("seedhash1", delete_files=True)

    def test_check_seeding_torrents_cleans_up_when_time_limit_reached_with_unrelated_specials(self):
        """Проверяет, что раздача удаляется по истечению 12ч сидирования, даже если в базе у шоу есть спешлы."""
        db_mock = MagicMock()
        dc = SimpleNamespace(id=1, name="Transmission", type="transmission", enabled=True, seed_time_limit=None, seed_ratio_limit=None)
        indexer = SimpleNamespace(id=7, name="Tapochek", enable_seeding=True, seed_ratio_limit=None, seed_time_limit_hours=12)
        dh = SimpleNamespace(id=20, show_id=2, indexer_id=7, torrent_hash="tapochek_hash")

        db_mock.query.return_value.filter.return_value.order_by.return_value.first.return_value = dh
        db_mock.query.return_value.filter.return_value.count.return_value = 0
        db_mock.get.side_effect = lambda model, obj_id: indexer if obj_id == 7 else None

        # Торрент сидировался 12 часов 1 минуту (43260 секунд)
        torrent_seeded = TorrentInfo(
            hash="tapochek_hash", name="Anime.Show.S01.1080p", progress=1.0,
            state="seeding", save_path=self.src_dir, size=15000000000,
            ratio=0.45, seeding_time=43260,
        )

        mock_client = AsyncMock()
        mock_client.list_torrents.return_value = [torrent_seeded]

        with patch("app.services.downloads_monitor.get_client", return_value=mock_client), \
             patch("app.services.downloads_monitor.log_release_event"):
            asyncio.run(_check_seeding_torrents(db_mock, [dc]))

        mock_client.remove_torrent.assert_called_once_with("tapochek_hash", delete_files=True)

    def test_check_seeding_torrents_fallback_to_client_seeding_limits(self):
        """Проверяет применение лимитов сидирования из DownloadClient, если у трекера они не заданы."""
        db_mock = MagicMock()
        # Лимит 720 минут (12 часов) и ratio 1.0 в клиенте
        dc = SimpleNamespace(id=2, name="Transmission", type="transmission", enabled=True, seed_time_limit=720, seed_ratio_limit=1.0)
        dh = SimpleNamespace(id=30, show_id=3, indexer_id=None, torrent_hash="client_limit_hash")

        db_mock.query.return_value.filter.return_value.order_by.return_value.first.return_value = dh
        db_mock.query.return_value.filter.return_value.count.return_value = 0
        db_mock.get.return_value = None

        torrent_seeded = TorrentInfo(
            hash="client_limit_hash", name="Movie.2025.1080p", progress=1.0,
            state="seeding", save_path=self.src_dir, size=8000000000,
            ratio=0.1, seeding_time=43200,
        )

        mock_client = AsyncMock()
        mock_client.list_torrents.return_value = [torrent_seeded]

        with patch("app.services.downloads_monitor.get_client", return_value=mock_client), \
             patch("app.services.downloads_monitor.log_release_event"):
            asyncio.run(_check_seeding_torrents(db_mock, [dc]))

        mock_client.remove_torrent.assert_called_once_with("client_limit_hash", delete_files=True)

    def test_check_seeding_torrents_ignores_sample_video_files(self):
        """Проверяет, что семплы/трейлеры в раздаче не блокируют удаление после достижения лимита сидирования."""
        db_mock = MagicMock()
        dc = SimpleNamespace(id=1, name="qBit", type="qbittorrent", enabled=True, seed_time_limit=None, seed_ratio_limit=None)
        indexer = SimpleNamespace(id=5, name="Tracker", enable_seeding=True, seed_ratio_limit=1.0, seed_time_limit_hours=12)
        dh = SimpleNamespace(id=40, show_id=4, indexer_id=5, torrent_hash="sample_pack_hash")
        show = SimpleNamespace(id=4, title="Show With Sample", content_type="series")

        # Создаем файл семпла
        sample_file = os.path.join(self.src_dir, "sample.mkv")
        with open(sample_file, "wb") as f:
            f.write(b"sample video")

        db_mock.query.return_value.filter.return_value.order_by.return_value.first.return_value = dh
        db_mock.query.return_value.filter.return_value.count.return_value = 0
        db_mock.get.side_effect = lambda model, obj_id: indexer if obj_id == 5 else (show if obj_id == 4 else None)

        torrent_seeded = TorrentInfo(
            hash="sample_pack_hash", name="Show.With.Sample.S01", progress=1.0,
            state="seeding", save_path=self.src_dir, size=5000000,
            ratio=1.2, seeding_time=1000,
            files=[SimpleNamespace(name="sample.mkv", priority=1, index=0)],
        )

        mock_client = AsyncMock()
        mock_client.list_torrents.return_value = [torrent_seeded]

        settings = SimpleNamespace(download_folder_series=self.src_dir, root_folder_series=self.dst_dir)
        with patch("app.services.downloads_monitor.get_client", return_value=mock_client), \
             patch("app.services.downloads_monitor.get_or_create_settings", return_value=settings), \
             patch("app.services.downloads_monitor.log_release_event"):
            asyncio.run(_check_seeding_torrents(db_mock, [dc]))

        mock_client.remove_torrent.assert_called_once_with("sample_pack_hash", delete_files=True)

    @unittest.skipUnless(HAS_FASTAPI, "Requires fastapi")
    def test_get_queue_seeding_metrics(self):
        """Проверяет корректность расчета метрик сидирования (время, остаток, ratio, трекер) в get_queue."""
        db_mock = MagicMock()
        dc = SimpleNamespace(id=1, name="Transmission", type="transmission", enabled=True, seed_time_limit=None, seed_ratio_limit=None)
        indexer = SimpleNamespace(id=7, name="tapochek.net", enable_seeding=True, seed_ratio_limit=1.5, seed_time_limit_hours=12)
        dh = SimpleNamespace(id=1, show_id=10, indexer_id=7, torrent_hash="thash123")
        ep = SimpleNamespace(id=101, show_id=10, season_number=1, episode_number=1, torrent_hash="thash123", status="downloading", download_progress=1.0)
        show = SimpleNamespace(id=10, title="Invincible (2021)")

        def mock_query(model):
            q = MagicMock()
            if model.__name__ == "Episode":
                q.filter.return_value.all.return_value = [ep]
            elif model.__name__ == "DownloadHistory":
                q.filter.return_value.order_by.return_value.all.return_value = [dh]
            elif model.__name__ == "TrackedRelease":
                q.filter.return_value.all.return_value = []
            elif model.__name__ == "DownloadClient":
                q.filter.return_value.all.return_value = [dc]
            return q

        db_mock.query.side_effect = mock_query
        db_mock.get.side_effect = lambda model, obj_id: show if model.__name__ == "Show" and obj_id == 10 else (indexer if model.__name__ == "Indexer" and obj_id == 7 else None)

        t_seeding = TorrentInfo(
            hash="thash123", name="Invincible.S01E01.1080p", progress=1.0,
            state="seeding", save_path=self.src_dir, size=3221225472,
            ratio=0.85, seeding_time=7200, upload_speed=2097152, download_speed=0,
        )

        mock_client = AsyncMock()
        mock_client.list_torrents.return_value = [t_seeding]

        with patch("app.api.operations.get_client", return_value=mock_client):
            items = asyncio.run(get_queue(db_mock, current_user=MagicMock()))

        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual(item.hash, "thash123")
        self.assertEqual(item.indexer_name, "tapochek.net")
        self.assertTrue(item.is_seeding)
        self.assertEqual(item.seeding_time_seconds, 7200)
        self.assertEqual(item.seed_time_limit_seconds, 12 * 3600)
        self.assertEqual(item.seed_time_remaining_seconds, 10 * 3600)
        self.assertEqual(item.ratio, 0.85)
        self.assertEqual(item.seed_ratio_limit, 1.5)
        self.assertEqual(item.episode_label, "S01E01")
        self.assertEqual(item.show_title, "Invincible (2021)")


if __name__ == "__main__":
    unittest.main()
