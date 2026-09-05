import unittest
from unittest.mock import AsyncMock, MagicMock, patch


class TestBlocklistEnhanced(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        try:
            import sqlalchemy  # noqa: F401
        except ImportError:
            self.skipTest("SQLAlchemy not installed in host runner")
    def test_add_to_blocklist_and_query(self):
        from app.services.blocklist_service import add_to_blocklist
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None

        entry = add_to_blocklist(
            mock_db,
            release_title="Attack.on.Titan.S04.1080p",
            reason="Отсутствуют запрошенные серии",
            show_id=10,
            torrent_hash="AABBCCDDEEFF11223344",
            indexer="RuTracker",
            size=1024 * 1024 * 500,
        )
        self.assertIsNotNone(entry)
        mock_db.add.assert_called_once()
        mock_db.commit.assert_called_once()

    def test_is_release_blocked_title_and_hash(self):
        from app.models.db import Blocklist
        from app.services.blocklist_service import is_release_blocked
        mock_db = MagicMock()
        existing = Blocklist(
            id=1,
            show_id=10,
            release_title="Attack.on.Titan.S04.1080p",
            torrent_hash="AABBCCDDEEFF11223344",
            reason="Blocked test reason",
        )
        # By hash
        mock_db.query.return_value.filter.return_value.first.return_value = existing
        is_blocked, reason = is_release_blocked(
            mock_db,
            show_id=10,
            torrent_hash="aabbccddeeff11223344",
        )
        self.assertTrue(is_blocked)
        self.assertEqual(reason, "Blocked test reason")

        # By title
        mock_db.query.return_value.filter.return_value.first.return_value = existing
        is_blocked, reason = is_release_blocked(
            mock_db,
            show_id=10,
            release_title="Attack.on.Titan.S04.1080p",
        )
        self.assertTrue(is_blocked)
        self.assertEqual(reason, "Blocked test reason")

    def test_remove_from_blocklist(self):
        from app.models.db import Blocklist
        from app.services.blocklist_service import remove_from_blocklist
        mock_db = MagicMock()
        existing = Blocklist(id=5, release_title="Sample")
        mock_db.get.return_value = existing

        res = remove_from_blocklist(mock_db, 5)
        self.assertTrue(res)
        mock_db.delete.assert_called_once_with(existing)
        mock_db.commit.assert_called_once()

    def test_clear_blocklist_for_show_and_all(self):
        from app.services.blocklist_service import clear_blocklist_for_show, clear_all_blocklist
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.delete.return_value = 3
        count = clear_blocklist_for_show(mock_db, show_id=7)
        self.assertEqual(count, 3)

        mock_db.query.return_value.delete.return_value = 10
        count_all = clear_all_blocklist(mock_db)
        self.assertEqual(count_all, 10)

    def test_get_blocked_shows_summary(self):
        from app.models.db import Blocklist, Show
        from app.services.blocklist_service import get_blocked_shows_summary
        import datetime as dt
        mock_db = MagicMock()
        show = Show(id=10, title="Naruto", poster_url="/posters/naruto.jpg", year=2002)
        item1 = Blocklist(id=1, show_id=10, release_title="Naruto.E01", created_at=dt.datetime(2026, 9, 1))
        item2 = Blocklist(id=2, show_id=10, release_title="Naruto.E02", created_at=dt.datetime(2026, 9, 2))
        item3 = Blocklist(id=3, show_id=None, show_title="Без привязки к тайтлу", release_title="Unknown.Release", created_at=dt.datetime(2026, 9, 3))

        mock_db.query.return_value.all.return_value = [item1, item2, item3]
        mock_db.get.return_value = show

        summary = get_blocked_shows_summary(mock_db)
        self.assertEqual(len(summary), 2)
        show_summary = next(s for s in summary if s["show_id"] == 10)
        self.assertEqual(show_summary["count"], 2)
        self.assertEqual(show_summary["show_title"], "Naruto")
        self.assertEqual(show_summary["year"], 2002)

        unlinked_summary = next(s for s in summary if s["show_id"] is None)
        self.assertEqual(unlinked_summary["count"], 1)
        self.assertEqual(unlinked_summary["show_title"], "Без привязки к тайтлу")

    async def test_blocklist_routes_delete_and_list(self):
        from app.models.db import User
        from app.api.blocklist_routes import delete_blocklist_entry, clear_blocklist
        mock_db = MagicMock()
        user = User(id=1, username="admin", is_admin=True)

        with patch("app.services.blocklist_service.remove_from_blocklist", return_value=True):
            res = delete_blocklist_entry(entry_id=5, db=mock_db, current_user=user)
            self.assertTrue(res["success"])

        with patch("app.services.blocklist_service.clear_blocklist_for_show", return_value=4):
            res2 = clear_blocklist(show_id=10, db=mock_db, current_user=user)
            self.assertTrue(res2["success"])
            self.assertEqual(res2["deleted_count"], 4)

        with patch("app.services.blocklist_service.clear_all_blocklist", return_value=15):
            res3 = clear_blocklist(show_id=None, db=mock_db, current_user=user)
            self.assertTrue(res3["success"])
            self.assertEqual(res3["deleted_count"], 15)

    def test_update_blocklist_entry(self):
        from app.models.db import Blocklist, Show
        from app.services.blocklist_service import update_blocklist_entry
        mock_db = MagicMock()
        existing = Blocklist(id=5, release_title="Old.Title", reason="Old reason", show_id=1)
        mock_db.get.side_effect = lambda model, ident: existing if model == Blocklist and ident == 5 else (Show(id=2, title="New Show") if model == Show and ident == 2 else None)

        updated = update_blocklist_entry(
            mock_db,
            item_id=5,
            release_title="New.Title.1080p",
            reason="New updated reason",
            show_id=2,
            torrent_hash="1122334455667788990011223344556677889900",
        )
        self.assertIsNotNone(updated)
        self.assertEqual(updated.release_title, "New.Title.1080p")
        self.assertEqual(updated.reason, "New updated reason")
        self.assertEqual(updated.show_id, 2)
        self.assertEqual(updated.show_title, "New Show")
        mock_db.commit.assert_called()

    async def test_limit_torrent_files_cancellation_adds_to_blocklist(self):
        from app.models.db import Show, Episode, EpisodeStatus
        from app.services.auto_search import _limit_torrent_files_to_episodes
        mock_dl = AsyncMock()
        mock_file = MagicMock()
        mock_file.index = 0
        mock_file.name = "Sample.Anime.S01E01.1080p.mkv"
        mock_file.size = 1000000

        mock_torrent = MagicMock()
        mock_torrent.name = "Sample Anime S01 - Wrong Files"
        mock_torrent.size = 1000000
        mock_torrent.files = [mock_file]

        mock_dl.get_torrent = AsyncMock(return_value=mock_torrent)
        mock_dl.remove_torrent = AsyncMock()

        show = Show(id=20, title="Sample Anime", content_type="anime")
        ep = Episode(id=100, show_id=20, season_number=1, episode_number=10, status=EpisodeStatus.DOWNLOADING, torrent_hash="TESTHASH123")

        mock_db = MagicMock()
        mock_db.is_active = True

        def _mock_get(model, ident):
            if model == Episode:
                return ep
            if model == Show:
                return show
            return None

        mock_db.get.side_effect = _mock_get

        with patch("app.services.blocklist_service.add_to_blocklist") as mock_add_block, \
             patch("app.services.auto_search.log_release_event") as mock_log, \
             patch("asyncio.create_task", side_effect=lambda coro: (coro.close(), MagicMock())[1]):

            await _limit_torrent_files_to_episodes(
                mock_dl,
                "TESTHASH123",
                [ep],
                db=mock_db,
            )

            mock_dl.remove_torrent.assert_called_once_with("TESTHASH123", delete_files=True)
            self.assertEqual(ep.status, EpisodeStatus.WANTED)
            mock_add_block.assert_called_once()
            call_kwargs = mock_add_block.call_args[1]
            self.assertEqual(call_kwargs["torrent_hash"], "TESTHASH123")
            self.assertIn("отсутствуют запрошенные серии", call_kwargs["reason"])
    def test_add_and_resolve_page_url(self):
        from app.models.db import Blocklist, TrackedRelease
        from app.services.blocklist_service import add_to_blocklist, get_blocklist_entries
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None

        # Add with explicit page_url
        entry = add_to_blocklist(
            mock_db,
            release_title="Test.Release.1080p",
            reason="Bad quality",
            torrent_hash="aabbccddee112233445566778899001122334455",
            page_url="https://rutracker.org/forum/viewtopic.php?t=123456",
        )
        self.assertEqual(entry.page_url, "https://rutracker.org/forum/viewtopic.php?t=123456")

        # Test resolving page_url from TrackedRelease when not provided
        tr = TrackedRelease(
            id=1,
            infohash="aabbccddee112233445566778899001122334455",
            topic_url="https://kinozal.guru/details.php?id=99999",
        )
        mock_db.query.return_value.filter.return_value.first.return_value = tr
        from app.services.blocklist_service import _resolve_release_details
        resolved = _resolve_release_details(mock_db, torrent_hash="aabbccddee112233445566778899001122334455")
        self.assertEqual(resolved["page_url"], "https://kinozal.guru/details.php?id=99999")

        # Test update_blocklist_entry with page_url
        from app.services.blocklist_service import update_blocklist_entry
        existing = Blocklist(id=1, release_title="Test", page_url=None)
        mock_db.get.return_value = existing
        updated = update_blocklist_entry(mock_db, item_id=1, page_url="https://rutracker.org/forum/viewtopic.php?t=888")
        self.assertEqual(updated.page_url, "https://rutracker.org/forum/viewtopic.php?t=888")

    def test_extract_infohash_formats(self):
        from app.services.blocklist_service import extract_infohash
        # 40 hex chars
        h40 = "4a5b6c7d8e9f0123456789abcdef0123456789ab"
        self.assertEqual(extract_infohash(h40), h40)
        self.assertEqual(extract_infohash(h40.upper()), h40)

        # Magnet URI with hex
        mag_hex = f"magnet:?xt=urn:btih:{h40}&dn=My+Show+S01"
        self.assertEqual(extract_infohash(mag_hex), h40)

        # Base32 BTIH (32 chars)
        # 20 bytes of 0x01 -> hex 0101010101010101010101010101010101010101
        import base64
        raw20 = bytes([0x12] * 20)
        b32 = base64.b32encode(raw20).decode("ascii")
        mag_b32 = f"magnet:?xt=urn:btih:{b32}&tr=http://tracker"
        self.assertEqual(extract_infohash(mag_b32), raw20.hex())

        # Non-hash URL returns None
        self.assertIsNone(extract_infohash("https://rutracker.org/forum/viewtopic.php?t=12345"))
        self.assertIsNone(extract_infohash(""))
        self.assertIsNone(extract_infohash(None))

    def test_is_release_blocked_cross_format(self):
        from app.models.db import Blocklist, Show
        from app.services.blocklist_service import is_release_blocked
        mock_db = MagicMock()
        h40 = "aabbccddeeff00112233445566778899aabbccdd"
        show = Show(id=5, title="Test Anime")

        # 1. DB has torrent_hash (40 hex), search query has magnet URL in download_url
        existing1 = Blocklist(id=1, show_id=5, torrent_hash=h40, reason="Banned torrent hash")
        mock_db.query.return_value.filter.return_value.first.return_value = existing1

        is_blocked, reason = is_release_blocked(
            mock_db,
            show=show,
            title="Test.Anime.S01E01.1080p",
            download_url=f"magnet:?xt=urn:btih:{h40}&dn=Test",
        )
        self.assertTrue(is_blocked)
        self.assertEqual(reason, "Banned torrent hash")

        # 2. DB has download_url (magnet), search query passes torrent_hash
        existing2 = Blocklist(id=2, show_id=5, download_url=f"magnet:?xt=urn:btih:{h40}&dn=Test", reason="Magnet ban")
        mock_db.query.return_value.filter.return_value.first.return_value = existing2

        is_blocked2, reason2 = is_release_blocked(
            mock_db,
            show=show,
            torrent_hash=h40,
        )
        self.assertTrue(is_blocked2)
        self.assertEqual(reason2, "Magnet ban")

    async def test_downloads_monitor_cancels_blocked_downloading_torrent(self):
        from app.models.db import Show, Episode, EpisodeStatus, DownloadClient
        from app.services.downloads_monitor import check_downloads

        blocked_hash = "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"
        show = Show(id=1, title="Upgrade Show", content_type="series")
        # An episode with status DOWNLOADING, upgrade in progress, already having a downloaded file
        ep = Episode(
            id=10,
            show_id=1,
            season_number=1,
            episode_number=1,
            status=EpisodeStatus.DOWNLOADING,
            torrent_hash=blocked_hash,
            file_path="/media/tv/Upgrade.Show.S01E01.mkv",
            upgrade_requested=True,
            download_client_id=1,
        )

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.all.return_value = [ep]

        dc = DownloadClient(id=1, name="qBit", enabled=True, is_default=True)
        def _mock_query(model):
            m_q = MagicMock()
            if model == Episode:
                m_q.filter.return_value.all.return_value = [ep]
            elif model == DownloadClient:
                m_q.filter.return_value.all.return_value = [dc]
            return m_q

        mock_db.query.side_effect = _mock_query
        mock_db.get.side_effect = lambda model, ident: show if model == Show and ident == 1 else None

        mock_client = AsyncMock()
        mock_t = MagicMock()
        mock_t.hash = blocked_hash
        mock_t.name = "Upgrade.Show.S01E01.1080p.Blocked"
        mock_t.progress = 0.5
        mock_t.state = "downloading"
        mock_client.list_torrents.return_value = [mock_t]
        mock_client.remove_torrent = AsyncMock()

        # Blocklist check returns True (blocked)
        with patch("app.services.downloads_monitor.get_client", return_value=mock_client), \
             patch("app.services.blocklist_service.is_release_blocked", return_value=(True, "Blocked by hash in test")):

            await check_downloads(mock_db)

            # Assert torrent was removed from client
            mock_client.remove_torrent.assert_called_once_with(blocked_hash, delete_files=True)
            # Assert episode was reverted to DOWNLOADED because it has existing file_path
            self.assertEqual(ep.status, EpisodeStatus.DOWNLOADED)
            self.assertIsNone(ep.torrent_hash)
            self.assertEqual(ep.download_progress, 0.0)

    async def test_auto_search_post_grab_removes_blocked_infohash(self):
        from app.models.db import Show, Episode, EpisodeStatus, QualityProfile, Indexer, DownloadClient, AppSettings
        from app.services.auto_search import _do_search_and_grab
        from app.services.torznab import TorznabRelease

        show = Show(id=1, title="Test Show", content_type="series", monitored=True, quality_profile_id=1, upgrade_requested=True)
        ep = Episode(id=10, show_id=1, season_number=1, episode_number=1, status=EpisodeStatus.DOWNLOADED, upgrade_requested=True, monitored=True)
        qp = QualityProfile(id=1, name="HD", upgrade_allowed=True, allowed_qualities=["WEBDL-1080p"])
        indexer = Indexer(id=1, name="TestIndexer", enabled=True, priority=1)
        dc = DownloadClient(id=1, name="qBit", enabled=True, is_default=True, category="tv")
        settings = AppSettings(id=1, download_folder_series="/downloads/tv")

        mock_db = MagicMock()
        def _mock_get(model, ident):
            if model == Show and ident == 1:
                return show
            if model == QualityProfile and ident == 1:
                return qp
            return None
        mock_db.get.side_effect = _mock_get

        def _mock_query(model):
            m_q = MagicMock()
            if model == Episode:
                m_q.filter.return_value.all.return_value = [ep]
            elif model == Indexer:
                m_q.filter.return_value.all.return_value = [indexer]
            elif model == DownloadClient:
                m_q.filter.return_value.order_by.return_value.first.return_value = dc
            elif model == QualityProfile:
                m_q.filter.return_value.all.return_value = [qp]
            return m_q
        mock_db.query.side_effect = _mock_query

        rel1 = TorznabRelease(
            title="Test.Show.S01E01.1080p.WEB-DL",
            guid="http://tracker/topic1",
            download_url="http://tracker/download/1",
            size_bytes=1000000000,
            seeders=15,
        )

        mock_dl_client = AsyncMock()
        blocked_hash = "deadbeef11223344556677889900112233445566"
        mock_dl_client.add_torrent = AsyncMock(return_value=blocked_hash)
        mock_dl_client.remove_torrent = AsyncMock()

        with patch("app.services.auto_search.get_or_create_settings", return_value=settings), \
             patch("app.services.auto_search.get_client", return_value=mock_dl_client), \
             patch("app.services.auto_search._collect_candidates") as mock_collect, \
             patch("app.services.blocklist_service.is_release_blocked") as mock_is_blocked, \
             patch("app.services.auto_search.log_release_event"):

            from app.services.matcher import MatchResult
            from app.services.parser import ParsedTitle, ReleaseKind
            from app.services.quality import QualityInfo
            from app.services.auto_search import CandidateList

            mock_cand = {
                "rel": rel1,
                "match": MatchResult(matched=True, score=1.0, parsed=ParsedTitle(title="Test Show", season=1, episodes=[1], kind=ReleaseKind.SINGLE_EPISODE)),
                "quality": QualityInfo(name="WEBDL-1080p", rank=10),
                "indexer": indexer,
                "covered": [ep],
            }
            mock_collect.return_value = CandidateList([mock_cand])

            # Post-add blocklist check returns (True, "Blocked infohash")
            mock_is_blocked.return_value = (True, "Blocked infohash in test")

            res = await _do_search_and_grab(mock_db, show, wanted_only=False)

            # Assert add_torrent was called
            mock_dl_client.add_torrent.assert_called_once()
            # Assert remove_torrent was immediately called upon discovering blocked hash
            mock_dl_client.remove_torrent.assert_called_once_with(blocked_hash, delete_files=True)
            # Assert episode was NOT set to DOWNLOADING
            self.assertNotEqual(ep.status, EpisodeStatus.DOWNLOADING)


if __name__ == "__main__":
    unittest.main()
