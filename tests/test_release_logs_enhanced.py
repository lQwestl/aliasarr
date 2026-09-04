"""Tests for enhanced release logs, download client diagnostics, and journal management."""
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from dataclasses import dataclass
from typing import Optional

from app.services import download_client
from app.services.download_client import (
    TransmissionClient,
    QBittorrentClient,
)
from app.services.auto_search import evaluate_torrent_file_priority


@dataclass
class MockEpisode:
    id: int
    show_id: int
    season_number: int
    episode_number: int
    title: str = ""
    status: str = "wanted"
    absolute_number: Optional[int] = None


class TestReleaseLogsEnhanced(unittest.IsolatedAsyncioTestCase):

    async def test_transmission_get_client_logs(self):
        client = TransmissionClient(host="localhost", port=9091, username="", password="")
        mock_messages = [
            {"id": 1, "message": "DHT port opened", "level": 1, "time": 1725450000},
            {"id": 2, "message": "Peer connected", "level": 2, "time": 1725450010},
        ]
        client._rpc_call = AsyncMock(return_value={"messages": mock_messages})

        logs = await client.get_client_logs(limit=10)
        self.assertEqual(len(logs), 2)
        self.assertEqual(logs[0]["message"], "DHT port opened")

    async def test_transmission_get_client_diagnostics(self):
        client = TransmissionClient(host="localhost", port=9091, username="", password="")
        client._rpc_call = AsyncMock(side_effect=[
            {"version": "4.0.5", "download-dir": "/downloads"},  # session-get
            {"activeTorrentCount": 5, "downloadSpeed": 1024},    # session-stats
        ])
        client.list_torrents = AsyncMock(return_value=[
            {"id": 1, "name": "Show.S01", "status": "downloading", "progress": 0.5, "left_until_done": 500000000, "rate_download": 1024}
        ])

        diag = await client.get_client_diagnostics()
        self.assertEqual(diag["type"], "transmission")
        self.assertEqual(diag["version"], "4.0.5")
        self.assertEqual(len(diag["torrents"]), 1)
        self.assertEqual(diag["torrents"][0]["name"], "Show.S01")

    async def test_qbittorrent_get_client_logs(self):
        client = QBittorrentClient(host="localhost", port=8080, username="", password="")
        client._ensure_auth = AsyncMock()

        mock_logs_data = [
            {"id": 1, "message": "UPnP initialized", "type": 1, "timestamp": 1725450000000},
            {"id": 2, "message": "Connection warning", "type": 4, "timestamp": 1725450010000},
        ]
        
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = mock_logs_data

        mock_http_client = MagicMock()
        mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
        mock_http_client.__aexit__ = AsyncMock(return_value=None)
        mock_http_client.get = AsyncMock(return_value=mock_resp)

        mock_httpx = MagicMock()
        mock_httpx.AsyncClient.return_value = mock_http_client

        with patch.object(download_client, "httpx", mock_httpx):
            logs = await client.get_client_logs(limit=10)
            self.assertEqual(len(logs), 2)
            self.assertEqual(logs[0]["message"], "UPnP initialized")

    def test_evaluate_torrent_file_priority_with_reasons(self):
        ep1 = MockEpisode(id=1, show_id=10, season_number=4, episode_number=1, title="Episode 1")
        ep2 = MockEpisode(id=2, show_id=10, season_number=4, episode_number=2, title="Episode 2")
        target_eps = [ep1, ep2]
        
        file_reasons = {}

        p1 = evaluate_torrent_file_priority(
            file_name="Attack.on.Titan.S04E01.1080p.mkv",
            file_index=0,
            target_episodes=target_eps,
            content_type="series",
            out_file_reasons=file_reasons,
        )
        self.assertEqual(p1, 1)
        self.assertIn("S04E01", file_reasons[0])
        self.assertIn("ВКЛЮЧЕН", file_reasons[0])

        p2 = evaluate_torrent_file_priority(
            file_name="Attack.on.Titan.S04E03.1080p.mkv",
            file_index=1,
            target_episodes=target_eps,
            content_type="series",
            out_file_reasons=file_reasons,
        )
        self.assertEqual(p2, 0)
        self.assertIn("ОТКЛЮЧЕН", file_reasons[1])

        p3 = evaluate_torrent_file_priority(
            file_name="Sample/sample.mkv",
            file_index=2,
            target_episodes=target_eps,
            content_type="series",
            out_file_reasons=file_reasons,
        )
        self.assertEqual(p3, 0)
        self.assertIn("сэмпл", file_reasons[2].lower())


if __name__ == "__main__":
    unittest.main()
