import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import os


class TestUpgradeAndTracking(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        try:
            import sqlalchemy  # noqa: F401
        except ImportError:
            self.skipTest("SQLAlchemy not installed in host runner")

    async def test_tracker_sync_deactivates_unmonitored_shows(self):
        from app.models.db import Show, TrackedRelease, Episode, EpisodeStatus
        from app.services.tracker import recheck_all_active

        show_unmonitored = Show(id=1, title="Robot Chicken", monitored=False)
        tracked1 = TrackedRelease(id=1, show_id=1, show=show_unmonitored, active=True, topic_guid="guid1", indexer_id=1)

        show_monitored = Show(id=2, title="Ongoing Anime", monitored=True, content_type="anime")
        ep_wanted = Episode(id=20, show_id=2, season_number=1, episode_number=1, status=EpisodeStatus.WANTED)
        tracked2 = TrackedRelease(id=2, show_id=2, show=show_monitored, active=True, topic_guid="guid2", indexer_id=1)

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.all.return_value = [tracked1, tracked2]

        def _mock_query(model):
            m_q = MagicMock()
            if model == TrackedRelease:
                m_q.filter.return_value.all.return_value = [tracked1, tracked2]
            elif model == Episode:
                m_q.filter.return_value.first.return_value = ep_wanted
                m_q.filter_by.return_value.first.return_value = ep_wanted
            return m_q

        mock_db.query.side_effect = _mock_query

        with patch("app.services.tracker.recheck_tracked_release", new_callable=AsyncMock) as mock_recheck:
            mock_recheck.return_value = {"updated": False}
            results = await recheck_all_active(mock_db)

            # Assert unmonitored show tracking is deactivated
            self.assertFalse(tracked1.active)
            # Assert monitored show with wanted episodes remains active
            self.assertTrue(tracked2.active)
            # Only tracked2 should be rechecked over network
            mock_recheck.assert_called_once_with(mock_db, tracked2)

    async def test_downloads_monitor_rejected_downgrade_cleans_up_and_reverts(self):
        from app.models.db import Show, Episode, EpisodeStatus, DownloadClient
        from app.services.downloads_monitor import check_downloads

        blocked_hash = "1122334455667788990011223344556677889900"
        show = Show(id=1, title="Lord of the Flies", content_type="series", upgrade_requested=True)
        # Episode was downloading an upgrade, but already has an existing file
        ep = Episode(
            id=10,
            show_id=1,
            season_number=1,
            episode_number=1,
            status=EpisodeStatus.DOWNLOADING,
            torrent_hash=blocked_hash,
            file_path="/tmp/existing_lord_of_flies_s01e01.mkv",
            upgrade_requested=True,
            download_client_id=1,
            download_progress=1.0,
        )

        mock_db = MagicMock()
        dc = DownloadClient(id=1, name="Transmission", enabled=True, is_default=True)

        def _mock_query(model):
            m_q = MagicMock()
            if model == Episode:
                m_q.filter.return_value.all.return_value = [ep]
                m_q.filter.return_value.count.return_value = 0
            elif model == DownloadClient:
                m_q.filter.return_value.all.return_value = [dc]
            return m_q

        mock_db.query.side_effect = _mock_query
        mock_db.get.side_effect = lambda model, ident: show if model == Show and ident == 1 else None

        mock_client = AsyncMock()
        mock_t = MagicMock()
        mock_t.hash = blocked_hash
        mock_t.name = "lord.of.the.flies.s01.hdr.web-dlrip.xvid.ac3.-hqh"
        mock_t.progress = 1.0
        mock_t.state = "pausedup"
        mock_t.files = []
        mock_client.list_torrents.return_value = [mock_t]
        mock_client.get_torrent.return_value = mock_t
        mock_client.remove_torrent = AsyncMock()

        # Simulate postprocess returning skipped result due to downgrade protection
        skipped_results = [{
            "file": "/data/downloads/lord.of.the.flies.s01e01.avi",
            "status": "skipped",
            "reason": "существующий файл имеет лучшее качество (HDTV-1080p > WEBDL-480p)",
        }]

        with patch("app.services.downloads_monitor.get_client", return_value=mock_client),              patch("app.services.downloads_monitor._resolve_torrent_files_and_path", return_value=("/tmp/some_path", ["/tmp/some_path/f.avi"])),              patch("os.path.exists", return_value=True),              patch("os.path.isfile", return_value=True),              patch("os.path.getsize", return_value=100000),              patch("app.services.downloads_monitor._run_postprocess_in_thread", return_value=skipped_results),              patch("app.services.blocklist_service.add_to_blocklist") as mock_blocklist:

            await check_downloads(mock_db)

            # Torrent must be removed from client with files deleted
            mock_client.remove_torrent.assert_called_once_with(blocked_hash, delete_files=True)
            # Episode status must be reverted to DOWNLOADED
            self.assertEqual(ep.status, EpisodeStatus.DOWNLOADED)
            self.assertIsNone(ep.torrent_hash)
            self.assertEqual(ep.download_progress, 0.0)
            self.assertFalse(ep.upgrade_requested)
            # Added to blocklist
            mock_blocklist.assert_called_once()
            call_kwargs = mock_blocklist.call_args[1]
            self.assertEqual(call_kwargs["torrent_hash"], blocked_hash)
            self.assertIn("существующий файл имеет лучшее качество", call_kwargs["reason"])

    def test_postprocess_cutoff_clears_upgrade_requested(self):
        from app.models.db import Show, Episode, EpisodeStatus, QualityProfile
        from app.services.postprocess import process_download

        show = Show(id=1, title="Test Show", content_type="series", quality_profile_id=1, upgrade_requested=True)
        qp = QualityProfile(id=1, name="HD", upgrade_allowed=True, cutoff_quality="Bluray-1080p")
        ep = Episode(
            id=10,
            show_id=1,
            season_number=1,
            episode_number=1,
            status=EpisodeStatus.DOWNLOADING,
            upgrade_requested=True,
        )

        mock_db = MagicMock()
        mock_db.get.side_effect = lambda model, ident: qp if model == QualityProfile and ident == 1 else (show if model == Show and ident == 1 else None)
        mock_db.query.return_value.filter.return_value.all.return_value = [ep]
        mock_db.query.return_value.filter.return_value.count.return_value = 0

        with patch("app.services.postprocess.find_release_files", return_value={"video": ["/tmp/Test.Show.S01E01.1080p.BluRay.mkv"], "subtitle": [], "audio": [], "font": []}),              patch("os.path.exists", return_value=True),              patch("os.path.getsize", return_value=2000000000),              patch("shutil.move"),              patch("os.makedirs"),              patch("app.services.postprocess.apply_media_permissions"),              patch("app.services.postprocess.log_release_event"):

            results = process_download(
                mock_db,
                show,
                download_path="/tmp",
                rename_template="{title} - S{season:02d}E{episode:02d}",
                root_folder="/media/tv",
                season_folder_template="Season {season:02d}",
                specific_files=["/tmp/Test.Show.S01E01.1080p.BluRay.mkv"],
                torrent_hash="AABBCC112233",
            )

            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]["status"], "imported")
            # Upgrade requested must be cleared because Bluray-1080p reached cutoff
            self.assertFalse(ep.upgrade_requested)
            self.assertFalse(show.upgrade_requested)


if __name__ == "__main__":
    unittest.main()
