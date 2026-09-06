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


class TestHardlinksAndSeeding(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="aliasarr_hl_test_")
        self.src_dir = os.path.join(self.temp_dir, "downloads")
        self.dst_dir = os.path.join(self.temp_dir, "library")
        os.makedirs(self.src_dir, exist_ok=True)
        os.makedirs(self.dst_dir, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_transfer_media_file_move_when_not_seeding(self):
        """Без сидирования (keep_source=False) файл перемещается, источник удаляется."""
        src_file = os.path.join(self.src_dir, "episode1.mkv")
        dst_file = os.path.join(self.dst_dir, "Show - S01E01.mkv")
        with open(src_file, "wb") as f:
            f.write(b"video data 12345")

        transfer_media_file(src_file, dst_file, keep_source=False, use_hardlinks=True)

        self.assertTrue(os.path.exists(dst_file))
        self.assertFalse(os.path.exists(src_file))
        with open(dst_file, "rb") as f:
            self.assertEqual(f.read(), b"video data 12345")

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
        """Проверяет отправку RPC-запроса лимитов сидирования в Transmission."""
        client = TransmissionClient("127.0.0.1", 9091, "admin", "admin")

        with patch.object(client, "_rpc_call", new_callable=AsyncMock) as mock_rpc:
            asyncio.run(client.set_seeding_limits("hash456", seed_ratio_limit=2.0, seed_time_limit_minutes=2880))

            mock_rpc.assert_called_once()
            method, args = mock_rpc.call_args[0]
            self.assertEqual(method, "torrent-set")
            self.assertEqual(args["ids"], ["hash456"])
            self.assertEqual(args["seedRatioLimit"], 2.0)
            self.assertEqual(args["seedRatioMode"], 1)
            self.assertEqual(args["seedIdleLimit"], 2880)
            self.assertEqual(args["seedIdleMode"], 1)

    def test_check_seeding_torrents_cleans_up_when_limit_reached(self):
        """Проверяет, что _check_seeding_torrents удаляет раздачу и временные файлы при достижении ratio."""
        db_mock = MagicMock()
        dc = SimpleNamespace(id=1, name="qBit", type="qbittorrent", enabled=True)
        indexer = SimpleNamespace(id=5, name="PrivateTracker", enable_seeding=True, seed_ratio_limit=1.5, seed_time_limit_hours=72)
        dh = SimpleNamespace(id=10, show_id=1, indexer_id=5, torrent_hash="seedhash1")

        db_mock.query.return_value.filter.return_value.order_by.return_value.first.return_value = dh
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


if __name__ == "__main__":
    unittest.main()
