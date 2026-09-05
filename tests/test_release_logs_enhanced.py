from __future__ import annotations

import unittest
from dataclasses import dataclass
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.download_client import QBittorrentClient, TransmissionClient
from app.services.auto_search import evaluate_torrent_file_priority


@dataclass
class DummyEpisode:
    id: int
    season_number: int
    episode_number: int
    title: str = ""
    absolute_number: Optional[int] = None


class TestReleaseLogsEnhanced(unittest.IsolatedAsyncioTestCase):
    async def test_transmission_get_client_logs(self):
        client = TransmissionClient(host="localhost", port=9091, username="admin", password="pass")
        mock_args = {
            "messages": [
                {"name": "daemon", "message": "Listening on 51413", "level": 2, "timestamp": 1720000000},
                {"name": "rpc", "message": "Session updated", "level": 2, "timestamp": 1720000010},
            ]
        }
        with patch.object(client, "_rpc_call", new_callable=AsyncMock) as mock_rpc:
            mock_rpc.return_value = mock_args
            logs = await client.get_client_logs(limit=50)
            self.assertEqual(len(logs), 2)
            self.assertEqual(logs[0]["message"], "Listening on 51413")
            mock_rpc.assert_called_once()
            self.assertEqual(mock_rpc.call_args[0][0], "message-get")

    async def test_transmission_get_client_diagnostics(self):
        client = TransmissionClient(host="localhost", port=9091, username="admin", password="pass")
        mock_session = {"version": "4.0.5", "download-dir": "/downloads"}
        mock_stats = {
            "downloadSpeed": 1048576,
            "uploadSpeed": 524288,
            "activeTorrentCount": 3,
            "torrentCount": 5,
        }
        with patch.object(client, "_rpc_call", new_callable=AsyncMock) as mock_rpc,              patch.object(client, "list_torrents", new_callable=AsyncMock) as mock_list:
            mock_rpc.side_effect = [mock_session, mock_stats]
            mock_list.return_value = [{"id": 1, "name": "Torrent 1", "progress": 1.0}]

            diag = await client.get_client_diagnostics()
            self.assertEqual(diag["type"], "transmission")
            self.assertEqual(diag["version"], "4.0.5")
            self.assertEqual(diag["download_speed_b_s"], 1048576)
            self.assertEqual(diag["upload_speed_b_s"], 524288)
            self.assertEqual(len(diag["torrents"]), 1)

    async def test_qbittorrent_get_client_logs(self):
        client = QBittorrentClient(host="localhost", port=8080, username="admin", password="pass")
        mock_logs = [
            {"id": 1, "message": "qBittorrent started", "timestamp": 1720000000, "type": 1},
            {"id": 2, "message": "DHT initialized", "timestamp": 1720000005, "type": 2},
        ]
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = mock_logs

        mock_http_client = AsyncMock()
        mock_http_client.get = AsyncMock(return_value=mock_resp)
        mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
        mock_http_client.__aexit__ = AsyncMock(return_value=None)

        mock_httpx_mod = MagicMock()
        mock_httpx_mod.AsyncClient.return_value = mock_http_client

        with patch.object(client, "_ensure_auth", new_callable=AsyncMock),              patch("app.services.download_client.httpx", mock_httpx_mod):

            logs = await client.get_client_logs(limit=50)
            self.assertEqual(len(logs), 2)
            self.assertEqual(logs[0]["message"], "qBittorrent started")

    async def test_qbittorrent_get_client_diagnostics(self):
        client = QBittorrentClient(host="localhost", port=8080, username="admin", password="pass")
        mock_resp_ver = MagicMock()
        mock_resp_ver.status_code = 200
        mock_resp_ver.text = "v4.6.3"

        mock_resp_web = MagicMock()
        mock_resp_web.status_code = 200
        mock_resp_web.text = "2.9.3"

        mock_http_client = AsyncMock()
        mock_http_client.get = AsyncMock(side_effect=[mock_resp_ver, mock_resp_web])
        mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
        mock_http_client.__aexit__ = AsyncMock(return_value=None)

        mock_httpx_mod = MagicMock()
        mock_httpx_mod.AsyncClient.return_value = mock_http_client

        with patch.object(client, "_ensure_auth", new_callable=AsyncMock), \
             patch.object(client, "list_torrents", new_callable=AsyncMock) as mock_list, \
             patch("app.services.download_client.httpx", mock_httpx_mod):

            mock_list.return_value = [{"id": "abc", "name": "Torr Q", "progress": 0.5}]
            diag = await client.get_client_diagnostics()
            self.assertEqual(diag["type"], "qbittorrent")
            self.assertEqual(diag["version"], "v4.6.3")
            self.assertEqual(diag["webapi_version"], "2.9.3")
            self.assertEqual(len(diag["torrents"]), 1)

    async def test_get_download_client_logs_route(self):
        try:
            from app.api.release_logs_routes import get_download_client_logs
            from app.models.db import DownloadClient, User
        except ImportError:
            self.skipTest("FastAPI or DB dependencies not installed in host runner")

        mock_db = MagicMock()
        client_row = DownloadClient(
            id=1, name="Main Transmission", type="transmission", host="127.0.0.1", port=9091, enabled=True
        )
        mock_db.query.return_value.filter.return_value.all.return_value = [client_row]

        user = User(id=1, username="admin", is_admin=True)

        mock_inst = AsyncMock()
        mock_inst.get_client_diagnostics = AsyncMock(return_value={"version": "4.0.0"})
        mock_inst.get_client_logs = AsyncMock(return_value=[{"message": "Hello from Transmission"}])

        with patch("app.api.release_logs_routes.get_client", return_value=mock_inst):
            res = await get_download_client_logs(db=mock_db, current_user=user)
            self.assertIn("clients", res)
            self.assertEqual(len(res["clients"]), 1)
            self.assertEqual(res["clients"][0]["name"], "Main Transmission")
            self.assertEqual(res["clients"][0]["diagnostics"]["version"], "4.0.0")
            self.assertEqual(len(res["clients"][0]["logs"]), 1)

    async def test_export_release_logs_route(self):
        try:
            from app.api.release_logs_routes import export_release_logs
            from app.models.db import ReleaseLog, DownloadClient, User
        except ImportError:
            self.skipTest("FastAPI or DB dependencies not installed in host runner")
        import datetime as dt

        mock_db = MagicMock()
        log_entry = ReleaseLog(
            id=1,
            stage="decision",
            level="success",
            show_title="Test Anime",
            release_title="Test.Anime.S01.1080p",
            indexer="RuTracker",
            message="Выбран наилучший релиз",
            details={"winner": "Test.Anime.S01.1080p", "score": 95},
            created_at=dt.datetime(2026, 9, 5, 12, 0, 0),
        )
        mock_db.query.return_value.order_by.return_value.limit.return_value.all.return_value = [log_entry]

        client_row = DownloadClient(
            id=1, name="Test QB", type="qbittorrent", host="127.0.0.1", port=8080, enabled=True
        )
        mock_db.query.return_value.filter.return_value.all.return_value = [client_row]

        user = User(id=1, username="admin", is_admin=True)

        mock_inst = AsyncMock()
        mock_inst.get_client_diagnostics = AsyncMock(return_value={"version": "4.6.3", "torrents": []})
        mock_inst.get_client_logs = AsyncMock(return_value=[{"message": "qb started"}])

        with patch("app.api.release_logs_routes.get_client", return_value=mock_inst):
            resp = await export_release_logs(db=mock_db, current_user=user)
            self.assertEqual(resp.media_type, "text/plain; charset=utf-8")
            content = resp.body.decode("utf-8")
            self.assertIn("=== ALIASARR RELEASE LOGS DUMP ===", content)
            self.assertIn("=== DOWNLOAD CLIENTS DIAGNOSTICS & STATUS ===", content)
            self.assertIn("=== Recent Daemon Logs ===", content)
            self.assertIn("qb started", content)
            self.assertIn("Test.Anime.S01.1080p", content)

    def test_evaluate_torrent_file_priority_with_reasons(self):
        ep1 = DummyEpisode(id=1, season_number=1, episode_number=1, title="Ep 1")
        ep2 = DummyEpisode(id=2, season_number=1, episode_number=2, title="Ep 2")
        ep3 = DummyEpisode(id=3, season_number=1, episode_number=3, title="Ep 3")
        
        target_episodes = [ep1, ep2]
        all_show_episodes = [ep1, ep2, ep3]
        file_reasons = {}

        # Episode 1 -> Target / Wanted
        p0 = evaluate_torrent_file_priority(
            file_name="Show.S01E01.1080p.mkv",
            file_index=0,
            target_episodes=target_episodes,
            all_show_episodes=all_show_episodes,
            out_file_reasons=file_reasons,
        )
        self.assertEqual(p0, 1)
        self.assertIn("разыскивается", file_reasons[0])

        # Episode 3 -> Not in target list
        p1 = evaluate_torrent_file_priority(
            file_name="Show.S01E03.1080p.mkv",
            file_index=1,
            target_episodes=target_episodes,
            all_show_episodes=all_show_episodes,
            out_file_reasons=file_reasons,
        )
        self.assertEqual(p1, 0)
        self.assertIn("не входит в список", file_reasons[1])

        # Sample file
        p2 = evaluate_torrent_file_priority(
            file_name="sample.mkv",
            file_index=2,
            target_episodes=target_episodes,
            all_show_episodes=all_show_episodes,
            out_file_reasons=file_reasons,
        )
        self.assertEqual(p2, 0)
        self.assertIn("Видеосэмпл", file_reasons[2])


if __name__ == "__main__":
    unittest.main()

