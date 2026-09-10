import unittest
from types import SimpleNamespace
from app.services.auto_search import evaluate_torrent_file_priority
from app.services.parser import parse_episode


class TestMultiSeasonSelectiveDownload(unittest.TestCase):
    def setUp(self):
        # Create full show episode list for Silicon Valley (53 episodes across 6 seasons)
        # S1: 8 eps, S2: 10 eps, S3: 10 eps, S4: 10 eps, S5: 8 eps, S6: 7 eps
        self.all_show_episodes = []
        season_counts = {1: 8, 2: 10, 3: 10, 4: 10, 5: 8, 6: 7}
        ep_id = 1
        for s_num, count in season_counts.items():
            for ep_num in range(1, count + 1):
                self.all_show_episodes.append(
                    SimpleNamespace(
                        id=ep_id,
                        show_id=1,
                        season_number=s_num,
                        episode_number=ep_num,
                        absolute_number=None,
                        title=f"Episode S{s_num:02d}E{ep_num:02d}",
                    )
                )
                ep_id += 1

        # Target episodes: S3 to S6 (S1 and S2 are already grabbed/downloaded in better quality)
        self.target_episodes = [
            ep for ep in self.all_show_episodes if ep.season_number in (3, 4, 5, 6)
        ]

    def test_multi_season_folder_structure_russian(self):
        """Проверка структуры папок '1 сезон', '2 сезон' ... '6 сезон' в мультипаке.
        Сезоны 1 и 2 должны быть UNWANTED (0), а 3-6 — WANTED (1)."""
        # Season 1 files (should be unselected: 0)
        for ep in range(1, 9):
            file_path = f"Silicon.Valley.2014-2019.web-dlrip_[teko]/1 сезон/{ep:02d}.avi"
            reasons = {}
            prio = evaluate_torrent_file_priority(
                file_name=file_path,
                file_index=ep,
                target_episodes=self.target_episodes,
                all_show_episodes=self.all_show_episodes,
                torrent_name="Silicon.Valley.2014-2019.web-dlrip_[teko]",
                out_file_reasons=reasons,
            )
            self.assertEqual(prio, 0, f"File {file_path} should be UNWANTED (0), got {prio} (reason: {reasons.get(ep)})")

        # Season 2 files (should be unselected: 0)
        for ep in range(1, 11):
            file_path = f"Silicon.Valley.2014-2019.web-dlrip_[teko]/2 сезон/{ep:02d}.avi"
            reasons = {}
            prio = evaluate_torrent_file_priority(
                file_name=file_path,
                file_index=100 + ep,
                target_episodes=self.target_episodes,
                all_show_episodes=self.all_show_episodes,
                torrent_name="Silicon.Valley.2014-2019.web-dlrip_[teko]",
                out_file_reasons=reasons,
            )
            self.assertEqual(prio, 0, f"File {file_path} should be UNWANTED (0), got {prio} (reason: {reasons.get(100+ep)})")

        # Season 3 files (should be selected: 1)
        for ep in range(1, 11):
            file_path = f"Silicon.Valley.2014-2019.web-dlrip_[teko]/3 сезон/{ep:02d}.avi"
            reasons = {}
            prio = evaluate_torrent_file_priority(
                file_name=file_path,
                file_index=200 + ep,
                target_episodes=self.target_episodes,
                all_show_episodes=self.all_show_episodes,
                torrent_name="Silicon.Valley.2014-2019.web-dlrip_[teko]",
                out_file_reasons=reasons,
            )
            self.assertEqual(prio, 1, f"File {file_path} should be WANTED (1), got {prio} (reason: {reasons.get(200+ep)})")

        # Season 6 files (should be selected: 1)
        for ep in range(1, 8):
            file_path = f"Silicon.Valley.2014-2019.web-dlrip_[teko]/6 сезон/{ep:02d}.avi"
            reasons = {}
            prio = evaluate_torrent_file_priority(
                file_name=file_path,
                file_index=500 + ep,
                target_episodes=self.target_episodes,
                all_show_episodes=self.all_show_episodes,
                torrent_name="Silicon.Valley.2014-2019.web-dlrip_[teko]",
                out_file_reasons=reasons,
            )
            self.assertEqual(prio, 1, f"File {file_path} should be WANTED (1), got {prio} (reason: {reasons.get(500+ep)})")

    def test_multi_season_folder_structure_english(self):
        """Проверка структуры папок 'Season 1', 'Season 2' ... 'Season 6'."""
        for ep in range(1, 9):
            file_path = f"Silicon.Valley.Complete/Season 1/S01E{ep:02d}.mkv"
            prio = evaluate_torrent_file_priority(
                file_name=file_path,
                file_index=ep,
                target_episodes=self.target_episodes,
                all_show_episodes=self.all_show_episodes,
                torrent_name="Silicon.Valley.Complete.1080p",
            )
            self.assertEqual(prio, 0)

        for ep in range(1, 11):
            file_path = f"Silicon.Valley.Complete/Season 3/S03E{ep:02d}.mkv"
            prio = evaluate_torrent_file_priority(
                file_name=file_path,
                file_index=200 + ep,
                target_episodes=self.target_episodes,
                all_show_episodes=self.all_show_episodes,
                torrent_name="Silicon.Valley.Complete.1080p",
            )
            self.assertEqual(prio, 1)

    def test_multi_season_continuous_numbering(self):
        """Проверка сквозной кумулятивной нумерации в мультипаке (файлы 01.mkv..53.mkv).
        Файлы 1..18 относятся к S1 (1..8) и S2 (1..10) -> должны быть 0.
        Файлы 19..53 относятся к S3..S6 -> должны быть 1."""
        torrent_name = "Silicon Valley (1-6 сезон) HDTV-Rip"
        # Files 1 to 18 (cumulative for S1 and S2)
        for ep_idx in range(1, 19):
            file_path = f"Silicon Valley/{ep_idx:02d}.mkv"
            reasons = {}
            prio = evaluate_torrent_file_priority(
                file_name=file_path,
                file_index=ep_idx,
                target_episodes=self.target_episodes,
                all_show_episodes=self.all_show_episodes,
                torrent_name=torrent_name,
                out_file_reasons=reasons,
            )
            self.assertEqual(
                prio, 0,
                f"File {file_path} (idx {ep_idx}) should be UNWANTED (0), got {prio} (reason: {reasons.get(ep_idx)})"
            )

        # Files 19 to 53 (cumulative for S3 to S6)
        for ep_idx in range(19, 54):
            file_path = f"Silicon Valley/{ep_idx:02d}.mkv"
            reasons = {}
            prio = evaluate_torrent_file_priority(
                file_name=file_path,
                file_index=ep_idx,
                target_episodes=self.target_episodes,
                all_show_episodes=self.all_show_episodes,
                torrent_name=torrent_name,
                out_file_reasons=reasons,
            )
            self.assertEqual(
                prio, 1,
                f"File {file_path} (idx {ep_idx}) should be WANTED (1), got {prio} (reason: {reasons.get(ep_idx)})"
            )

    def test_multi_season_subtitles_and_extras(self):
        """Проверка включения/отключения сопутствующих файлов (субтитров/шрифтов)."""
        # S1 Subtitle in folder
        prio_s1_sub = evaluate_torrent_file_priority(
            file_name="Silicon.Valley/1 сезон/01.srt",
            file_index=1,
            target_episodes=self.target_episodes,
            all_show_episodes=self.all_show_episodes,
            torrent_name="Silicon.Valley.1-6",
        )
        self.assertEqual(prio_s1_sub, 0)

        # S3 Subtitle in folder
        prio_s3_sub = evaluate_torrent_file_priority(
            file_name="Silicon.Valley/3 сезон/01.srt",
            file_index=2,
            target_episodes=self.target_episodes,
            all_show_episodes=self.all_show_episodes,
            torrent_name="Silicon.Valley.1-6",
        )
        self.assertEqual(prio_s3_sub, 1)

        # Fonts
        prio_font = evaluate_torrent_file_priority(
            file_name="Silicon.Valley/Fonts/arial.ttf",
            file_index=3,
            target_episodes=self.target_episodes,
            all_show_episodes=self.all_show_episodes,
            torrent_name="Silicon.Valley.1-6",
        )
        self.assertEqual(prio_font, 1)

    def test_anime_official_absolute_numbering(self):
        """Проверка аниме с официальной абсолютной нумерацией."""
        anime_episodes = []
        # S1: 24 eps (abs 1..24), S2: 24 eps (abs 25..48)
        for ep in range(1, 25):
            anime_episodes.append(
                SimpleNamespace(id=ep, show_id=2, season_number=1, episode_number=ep, absolute_number=ep, title=f"Ep {ep}")
            )
        for ep in range(1, 25):
            anime_episodes.append(
                SimpleNamespace(id=24 + ep, show_id=2, season_number=2, episode_number=ep, absolute_number=24 + ep, title=f"Ep {24+ep}")
            )

        target_s2 = [ep for ep in anime_episodes if ep.season_number == 2]

        # File from S1 (abs 05)
        prio_s1 = evaluate_torrent_file_priority(
            file_name="[SubsPlease] Show - 05 [1080p].mkv",
            file_index=5,
            target_episodes=target_s2,
            all_show_episodes=anime_episodes,
            content_type="anime",
        )
        self.assertEqual(prio_s1, 0)

        # File from S2 (abs 26)
        prio_s2 = evaluate_torrent_file_priority(
            file_name="[SubsPlease] Show - 26 [1080p].mkv",
            file_index=26,
            target_episodes=target_s2,
            all_show_episodes=anime_episodes,
            content_type="anime",
        )
        self.assertEqual(prio_s2, 1)

    def test_single_season_release_matching(self):
        """Одиночный релиз сезона не должен ломаться наличием других сезонов в all_show_episodes."""
        target_s3 = [ep for ep in self.all_show_episodes if ep.season_number == 3]
        for ep in range(1, 11):
            file_name = f"Silicon.Valley.S03.1080p/{ep:02d}.mkv"
            prio = evaluate_torrent_file_priority(
                file_name=file_name,
                file_index=ep,
                target_episodes=target_s3,
                all_show_episodes=self.all_show_episodes,
                torrent_name="Silicon.Valley.S03.1080p.BluRay",
            )
            self.assertEqual(prio, 1, f"Episode S03E{ep:02d} should be WANTED (1)")

    def test_russian_various_folder_variations(self):
        """Проверка различных вариаций названий папок на русском: 'Сезон 1', '1-й Сезон', '01 Сезон'."""
        variations_s1 = [
            "Silicon Valley/Сезон 1/01.mkv",
            "Silicon Valley/1-й Сезон/01.mkv",
            "Silicon Valley/01 Сезон/01.mkv",
            "Silicon Valley/Сезон 01/01.mkv",
            "Silicon Valley/Season 01/01.mkv",
        ]
        for path in variations_s1:
            prio = evaluate_torrent_file_priority(
                file_name=path,
                file_index=1,
                target_episodes=self.target_episodes,
                all_show_episodes=self.all_show_episodes,
                torrent_name="Silicon Valley",
            )
            self.assertEqual(prio, 0, f"Path {path} should be detected as S1 and marked UNWANTED (0)")

        variations_s3 = [
            "Silicon Valley/Сезон 3/01.mkv",
            "Silicon Valley/3-й Сезон/01.mkv",
            "Silicon Valley/03 Сезон/01.mkv",
            "Silicon Valley/Season 03/01.mkv",
        ]
        for path in variations_s3:
            prio = evaluate_torrent_file_priority(
                file_name=path,
                file_index=1,
                target_episodes=self.target_episodes,
                all_show_episodes=self.all_show_episodes,
                torrent_name="Silicon Valley",
            )
            self.assertEqual(prio, 1, f"Path {path} should be detected as S3 and marked WANTED (1)")

    def test_format_3_4_digits_in_multipack(self):
        """Проверка 3-4 значной нумерации серий (101 -> S01E01, 301 -> S03E01)."""
        # S1 file: 101.mkv (S01E01) -> UNWANTED (0)
        prio_101 = evaluate_torrent_file_priority(
            file_name="Silicon.Valley.101.mkv",
            file_index=1,
            target_episodes=self.target_episodes,
            all_show_episodes=self.all_show_episodes,
            torrent_name="Silicon.Valley.Complete",
        )
        self.assertEqual(prio_101, 0)

        # S3 file: 301.mkv (S03E01) -> WANTED (1)
        prio_301 = evaluate_torrent_file_priority(
            file_name="Silicon.Valley.301.mkv",
            file_index=2,
            target_episodes=self.target_episodes,
            all_show_episodes=self.all_show_episodes,
            torrent_name="Silicon.Valley.Complete",
        )
        self.assertEqual(prio_301, 1)

    def test_multi_episode_files_in_multipack(self):
        """Проверка сдвоенных серий в мультипаке (например 01-02.avi)."""
        # S1 multi-episode file -> UNWANTED (0)
        prio_s1_double = evaluate_torrent_file_priority(
            file_name="Silicon.Valley/1 сезон/01-02.avi",
            file_index=1,
            target_episodes=self.target_episodes,
            all_show_episodes=self.all_show_episodes,
            torrent_name="Silicon.Valley.1-6",
        )
        self.assertEqual(prio_s1_double, 0)

        # S3 multi-episode file -> WANTED (1)
        prio_s3_double = evaluate_torrent_file_priority(
            file_name="Silicon.Valley/3 сезон/01-02.avi",
            file_index=2,
            target_episodes=self.target_episodes,
            all_show_episodes=self.all_show_episodes,
            torrent_name="Silicon.Valley.1-6",
        )
        self.assertEqual(prio_s3_double, 1)

    def test_transmission_add_torrent_paused(self):
        """Проверяет, что TransmissionClient.add_torrent отправляет paused=True при вызове RPC."""
        import asyncio
        from unittest.mock import AsyncMock, patch
        from app.services.download_client import TransmissionClient

        client = TransmissionClient("127.0.0.1", 9091, "admin", "admin")
        with patch.object(client, "_rpc_call", new_callable=AsyncMock) as mock_rpc:
            mock_rpc.return_value = {"torrent-added": {"hashString": "abc123hash", "name": "Silicon.Valley"}}
            res = asyncio.run(client.add_torrent("magnet:?xt=urn:btih:abc123hash", category="tv", save_path="/downloads", paused=True))
            self.assertEqual(res, "abc123hash")
            mock_rpc.assert_called_once()
            method, args = mock_rpc.call_args[0]
            self.assertEqual(method, "torrent-add")
            self.assertTrue(args.get("paused"))

    def test_transmission_session_id_caching(self):
        """Проверяет кэширование X-Transmission-Session-Id между запросами и обработку 409 Conflict."""
        import asyncio
        from unittest.mock import AsyncMock, patch, MagicMock
        from app.services.download_client import TransmissionClient, _TRANSMISSION_SESSION_CACHE

        _TRANSMISSION_SESSION_CACHE.clear()
        client = TransmissionClient("127.0.0.1", 9091, "admin", "admin")

        mock_resp_409 = MagicMock(status_code=409, headers={"X-Transmission-Session-Id": "sess_123"})
        mock_resp_200 = MagicMock(status_code=200, headers={}, json=lambda: {"result": "success", "arguments": {"torrents": []}})
        mock_resp_200.raise_for_status = MagicMock()

        mock_httpx = MagicMock()
        mock_http_instance = MagicMock()
        mock_http_instance.post = AsyncMock(side_effect=[mock_resp_409, mock_resp_200, mock_resp_200])
        mock_httpx.AsyncClient.return_value.__aenter__.return_value = mock_http_instance

        with patch("app.services.download_client.httpx", mock_httpx):
            # Первый вызов: получает 409, затем повторяет с sess_123
            res1 = asyncio.run(client._rpc_call("torrent-get"))
            self.assertEqual(res1, {"torrents": []})
            self.assertEqual(_TRANSMISSION_SESSION_CACHE.get(client._rpc_url), "sess_123")

            # Второй новый инстанс клиента должен сразу использовать сохраненный сессионный ключ
            client2 = TransmissionClient("127.0.0.1", 9091, "admin", "admin")
            self.assertEqual(client2._session_id, "sess_123")

    def test_qbittorrent_add_torrent_paused(self):
        """Проверяет, что QBittorrentClient.add_torrent отправляет paused=true при paused=True."""
        import asyncio
        from unittest.mock import AsyncMock, patch, MagicMock
        from app.services.download_client import QBittorrentClient

        client = QBittorrentClient("127.0.0.1", 8080, "admin", "admin")
        mock_resp_login = MagicMock(status_code=200, cookies={"SID": "test_sid"})
        mock_resp_info = MagicMock(status_code=200, json=lambda: [{"hash": "beforehash"}])
        mock_resp_add = MagicMock(status_code=200, text="Ok.")

        mock_httpx = MagicMock()
        mock_http_instance = MagicMock()
        mock_http_instance.post = AsyncMock(side_effect=[mock_resp_login, mock_resp_add])
        mock_http_instance.get = AsyncMock(return_value=mock_resp_info)
        mock_httpx.AsyncClient.return_value.__aenter__.return_value = mock_http_instance

        with patch("app.services.download_client.httpx", mock_httpx):
            res = asyncio.run(client.add_torrent("magnet:?xt=urn:btih:1234567890123456789012345678901234567890", category="tv", save_path="/downloads", paused=True))
            self.assertEqual(res, "1234567890123456789012345678901234567890")
            
            # Find the add call
            add_calls = [c for c in mock_http_instance.post.call_args_list if "torrents/add" in str(c)]
            self.assertTrue(len(add_calls) > 0)
            data_sent = add_calls[0][1]["data"]
            self.assertEqual(data_sent.get("paused"), "true")


if __name__ == "__main__":
    unittest.main()
