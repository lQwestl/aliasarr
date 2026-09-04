from __future__ import annotations

import unittest
from dataclasses import dataclass
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

from app.services import download_client
from app.services.download_client import TransmissionClient, QBittorrentClient
from app.services.auto_search import evaluate_torrent_file_priority

try:
    from app.api.release_logs_routes import get_download_client_logs
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False


@dataclass
class MockEpisode:
    id: int
    season_number: int
    episode_number: int
    title: Optional[str] = None
    absolute_number: Optional[int] = None


class TestReleaseLogsEnhanced(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        super().setUp()
        self._patch_tr = patch.dict("sys.modules", {"transmission_rpc": None})
        self._patch_tr.start()

    def tearDown(self):
        self._patch_tr.stop()
        super().tearDown()

    async def test_transmission_get_client_logs(self):
        client = TransmissionClient(
            host="localhost",
            port=9091,
            username="admin",
            password="pwd",
        )

        sample_messages = [
            {"date": 1700000000, "level": 2, "name": "transmission", "message": "Server started"},
            {"date": 1700000010, "level": 3, "name": "transmission", "message": "Peer connected"},
            {"date": 1700000020, "level": 1, "name": "transmission", "message": "Disk space critical"},
        ]

        with patch.object(client, "_rpc_call", new_callable=AsyncMock) as mock_rpc:
            mock_rpc.return_value = {"messages": sample_messages}
            logs = await client.get_client_logs(limit=10)

            self.assertEqual(len(logs), 3)
            self.assertEqual(logs[0]["level"], "info")
            self.assertEqual(logs[0]["message"], "Server started")
            self.assertEqual(logs[1]["level"], "debug")
            self.assertEqual(logs[2]["level"], "error")
            mock_rpc.assert_awaited_once_with("message-get", {})

    async def test_transmission_get_client_diagnostics(self):
        client = TransmissionClient(
            host="localhost",
            port=9091,
            username="",
            password="",
        )

        with patch.object(client, "_rpc_call", new_callable=AsyncMock) as mock_rpc, \
             patch.object(client, "list_torrents", new_callable=AsyncMock) as mock_list:
            mock_rpc.side_effect = [
                {"version": "4.0.3", "rpc-version": 17, "download-dir": "/downloads"},
                {"activeTorrentCount": 2, "torrentCount": 5, "downloadSpeed": 1048576, "uploadSpeed": 524288},
            ]
            mock_list.return_value = [
                MagicMock(
                    id=1,
                    name="Show.S01E01",
                    percent_done=0.75,
                    is_finished=False,
                    left_until_done=250000000,
                    rate_download=1048576,
                    rate_upload=0,
                    status=4,
                )
            ]

            diag = await client.get_client_diagnostics()
            self.assertTrue(diag["connected"])
            self.assertEqual(diag["version"], "4.0.3")
            self.assertEqual(diag["download_dir"], "/downloads")
            self.assertEqual(len(diag["torrents"]), 1)

    async def test_qbittorrent_get_client_logs(self):
        client = QBittorrentClient(
            host="localhost",
            port=8080,
            username="admin",
            password="pwd",
        )

        mock_entries = [
            {"timestamp": 1700000000000, "type": 1, "message": "Normal log"},
            {"timestamp": 1700000010000, "type": 4, "message": "Warning log"},
            {"timestamp": 1700000020000, "type": 8, "message": "Critical error"},
        ]

        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = mock_entries

        mock_instance = AsyncMock()
        mock_instance.get.return_value = mock_resp
        mock_cm = MagicMock()
        mock_cm.__aenter__.return_value = mock_instance
        mock_cm.__aexit__.return_value = None

        mock_httpx = MagicMock()
        mock_httpx.AsyncClient.return_value = mock_cm

        with patch.object(download_client, "httpx", mock_httpx), \
             patch.object(client, "_ensure_auth", new_callable=AsyncMock):
            logs = await client.get_client_logs(limit=10)

            self.assertEqual(len(logs), 3)
            self.assertEqual(logs[0]["level"], "info")
            self.assertEqual(logs[1]["level"], "warning")
            self.assertEqual(logs[2]["level"], "error")

    async def test_qbittorrent_get_client_diagnostics(self):
        client = QBittorrentClient(
            host="localhost",
            port=8080,
            username="",
            password="",
        )

        mock_v_resp = MagicMock(status_code=200, text="v4.5.2")
        mock_api_resp = MagicMock(status_code=200, text="2.8.19")

        mock_instance = AsyncMock()
        mock_instance.get.side_effect = [mock_v_resp, mock_api_resp]
        mock_cm = MagicMock()
        mock_cm.__aenter__.return_value = mock_instance
        mock_cm.__aexit__.return_value = None

        mock_httpx = MagicMock()
        mock_httpx.AsyncClient.return_value = mock_cm

        with patch.object(download_client, "httpx", mock_httpx), \
             patch.object(client, "_ensure_auth", new_callable=AsyncMock), \
             patch.object(client, "list_torrents", new_callable=AsyncMock) as mock_list:
            mock_torrent = MagicMock(
                hash="hash123",
                name="Movie.2024",
                progress=1.0,
                state="uploading",
                left_until_done=0,
                size=5000000000,
                download_speed=0,
                upload_speed=10240,
            )
            mock_list.return_value = [mock_torrent]

            diag = await client.get_client_diagnostics()
            self.assertTrue(diag["connected"])
            self.assertEqual(diag["version"], "v4.5.2")
            self.assertEqual(diag["webapi_version"], "2.8.19")
            self.assertEqual(len(diag["torrents"]), 1)

    def test_evaluate_torrent_file_priority_with_reasons(self):
        # Mock episode targets: Ep 1 wanted, Ep 2 existing
        ep1 = MockEpisode(id=1, season_number=1, episode_number=1)
        ep2 = MockEpisode(id=2, season_number=1, episode_number=2)
        all_eps = [ep1, ep2]
        wanted_eps = [ep1]

        out_reasons = {}

        # 1. Wanted episode file
        prio_wanted = evaluate_torrent_file_priority(
            file_name="Show.S01E01.1080p.mkv",
            file_index=0,
            target_episodes=wanted_eps,
            all_show_episodes=all_eps,
            out_file_reasons=out_reasons,
        )
        self.assertEqual(prio_wanted, 1)
        self.assertIn("разыскивается", out_reasons[0])

        # 2. Episode file not wanted
        prio_unwanted = evaluate_torrent_file_priority(
            file_name="Show.S01E02.1080p.mkv",
            file_index=1,
            target_episodes=wanted_eps,
            all_show_episodes=all_eps,
            out_file_reasons=out_reasons,
        )
        self.assertEqual(prio_unwanted, 0)
        self.assertIn("не входит в список разыскиваемых", out_reasons[1])

        # 3. Wrong season file
        prio_wrong_s = evaluate_torrent_file_priority(
            file_name="Show.S02E01.1080p.mkv",
            file_index=2,
            target_episodes=wanted_eps,
            all_show_episodes=all_eps,
            out_file_reasons=out_reasons,
        )
        self.assertEqual(prio_wrong_s, 0)
        self.assertTrue("S02" in out_reasons[2] and "не входит в список разыскиваемых" in out_reasons[2])

        # 4. Sample video file (without target episode match)
        prio_sample = evaluate_torrent_file_priority(
            file_name="Sample/sample.mkv",
            file_index=3,
            target_episodes=wanted_eps,
            all_show_episodes=all_eps,
            out_file_reasons=out_reasons,
        )
        self.assertEqual(prio_sample, 0)
        self.assertTrue("Sample" in out_reasons[3] or "сэмпл" in out_reasons[3] or "ОТКЛЮЧЕН" in out_reasons[3])

    def test_evaluate_torrent_file_priority_subtitles_and_extras(self):
        ep1 = MockEpisode(id=1, season_number=1, episode_number=1)
        wanted_eps = [ep1]
        out_reasons = {}

        # 1. Subtitles for wanted episode
        prio_sub_wanted = evaluate_torrent_file_priority(
            file_name="Subs/Show.S01E01.rus.ass",
            file_index=0,
            target_episodes=wanted_eps,
            import_extra_files=True,
            out_file_reasons=out_reasons,
        )
        self.assertEqual(prio_sub_wanted, 1)
        self.assertIn("Сопутствующий файл", out_reasons[0])
        self.assertIn("ВКЛЮЧЕН", out_reasons[0])

        # 2. Subtitles for unwanted episode
        prio_sub_unwanted = evaluate_torrent_file_priority(
            file_name="Subs/Show.S01E02.rus.ass",
            file_index=1,
            target_episodes=wanted_eps,
            import_extra_files=True,
            out_file_reasons=out_reasons,
        )
        self.assertEqual(prio_sub_unwanted, 0)
        self.assertIn("ОТКЛЮЧЕН", out_reasons[1])


    def test_get_download_client_logs_endpoint_format(self):
        if not HAS_FASTAPI:
            self.skipTest("FastAPI not installed in host runner")
        import asyncio
        from unittest.mock import MagicMock

        db = MagicMock()
        mock_dc = MagicMock(id=1, name="Transmission", type="transmission", host="127.0.0.1", port=9091, enabled=True)
        db.query.return_value.filter.return_value.all.return_value = [mock_dc]

        with patch("app.services.download_client.get_client") as mock_get_c:
            mock_c = AsyncMock()
            mock_c.get_client_diagnostics.return_value = {"connected": True, "version": "4.0.3"}
            mock_c.get_client_logs.return_value = [{"level": "info", "message": "hello"}]
            mock_get_c.return_value = mock_c

            resp = asyncio.run(get_download_client_logs(db=db, current_user=MagicMock()))
            self.assertIn("clients", resp)
            self.assertEqual(len(resp["clients"]), 1)
            self.assertEqual(resp["clients"][0]["name"], "Transmission")
            self.assertEqual(resp["clients"][0]["client_name"], "Transmission")
            self.assertTrue(resp["clients"][0]["diagnostics"]["connected"])


if __name__ == "__main__":
    unittest.main()
