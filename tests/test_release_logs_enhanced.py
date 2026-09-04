from __future__ import annotations

import unittest
from dataclasses import dataclass
from typing import Optional
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch, MagicMock

from app.services.auto_search import evaluate_torrent_file_priority
from app.services.download_client import TransmissionClient, QBittorrentClient


@dataclass
class MockEpisode:
    id: int
    season_number: int
    episode_number: int
    title: Optional[str] = None
    absolute_number: Optional[int] = None


class TestReleaseLogsEnhanced(unittest.TestCase):
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

    async def async_test_transmission_logs_and_diagnostics(self):
        client = TransmissionClient(host="127.0.0.1", port=9091, username="", password="")

        # Mock _rpc_call
        client._rpc_call = AsyncMock(side_effect=[
            # 1. get_client_logs: message-get
            {"messages": [{"timestamp": 1700000000, "level": 2, "name": "RPC", "message": "Listening on port 9091"}]},
            # 2. get_client_diagnostics: session-get
            {"version": "4.0.5", "download-dir-free-space": 50000000000, "download-dir": "/downloads"},
            # 3. get_client_diagnostics: session-stats
            {"downloadSpeed": 102400, "uploadSpeed": 51200, "torrentCount": 2, "activeTorrentCount": 1},
        ])

        # Mock list_torrents for diagnostics
        client.list_torrents = AsyncMock(return_value=[
            {"id": "hash1", "name": "Show.S01", "progress": 0.85, "state": "downloading", "size": 1000000000}
        ])

        logs = await client.get_client_logs(limit=10)
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0]["message"], "Listening on port 9091")

        diag = await client.get_client_diagnostics()
        self.assertEqual(diag["version"], "4.0.5")
        self.assertEqual(diag["free_space_bytes"], 50000000000)
        self.assertEqual(diag["download_speed_b_s"], 102400)
        self.assertEqual(len(diag["torrents"]), 1)

    def test_transmission_logs_and_diagnostics(self):
        import asyncio
        asyncio.run(self.async_test_transmission_logs_and_diagnostics())

    async def async_test_qbittorrent_logs_and_diagnostics(self):
        client = QBittorrentClient(host="127.0.0.1", port=8080, username="admin", password="adminadmin")
        client._cookies = {"SID": "fake_sid"}

        mock_resp_logs = MagicMock()
        mock_resp_logs.status_code = 200
        mock_resp_logs.json.return_value = [
            {"id": 1, "message": "qBittorrent v4.6.0 started", "timestamp": 1700000000, "type": 1}
        ]
        mock_resp_logs.raise_for_status = MagicMock()

        mock_resp_ver = MagicMock()
        mock_resp_ver.status_code = 200
        mock_resp_ver.text = "v4.6.0"
        mock_resp_ver.raise_for_status = MagicMock()

        mock_resp_api = MagicMock()
        mock_resp_api.status_code = 200
        mock_resp_api.text = "2.9.2"
        mock_resp_api.raise_for_status = MagicMock()

        mock_resp_info = MagicMock()
        mock_resp_info.status_code = 200
        mock_resp_info.json.return_value = {
            "connection_status": "connected",
            "dl_info_speed": 204800,
            "up_info_speed": 102400,
            "free_space_on_disk": 100000000000,
        }
        mock_resp_info.raise_for_status = MagicMock()

        mock_httpx = MagicMock()
        mock_client_instance = AsyncMock()
        mock_httpx.AsyncClient.return_value.__aenter__.return_value = mock_client_instance
        mock_client_instance.get.side_effect = [
            mock_resp_logs,
            mock_resp_ver,
            mock_resp_api,
            mock_resp_info,
        ]

        with patch("app.services.download_client.httpx", mock_httpx):
            client.list_torrents = AsyncMock(return_value=[
                {"id": "qhash1", "name": "Anime.Movie", "progress": 1.0, "state": "pausedUP", "size": 2000000000}
            ])

            logs = await client.get_client_logs(limit=10)
            self.assertEqual(len(logs), 1)
            self.assertEqual(logs[0]["message"], "qBittorrent v4.6.0 started")

            diag = await client.get_client_diagnostics()
            self.assertEqual(diag["version"], "v4.6.0")
            self.assertEqual(diag["webapi_version"], "2.9.2")
            self.assertEqual(diag["download_speed_b_s"], 204800)
            self.assertEqual(len(diag["torrents"]), 1)

    def test_qbittorrent_logs_and_diagnostics(self):
        import asyncio
        asyncio.run(self.async_test_qbittorrent_logs_and_diagnostics())


if __name__ == "__main__":
    unittest.main()
