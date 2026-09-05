"""
Unit tests for upgrade_requested functionality:
- Setting upgrade_requested on episode, season, show
- Resetting upgrade_requested when reaching cutoff quality
- Auto search picking up downloaded episodes with upgrade_requested = True
"""
from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from unittest.mock import patch, MagicMock

try:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.models.db import (
        Base,
        Episode,
        EpisodeStatus,
        Show,
        QualityProfile,
        DownloadClient,
        Indexer,
        IndexerType,
    )
    from app.services import auto_search
    from app.services.torznab import TorznabRelease
    from app.services.postprocess import process_download
    HAS_DEPS = True
except ImportError:
    HAS_DEPS = False
    class EpisodeStatus:
        WANTED = "wanted"
        DOWNLOADED = "downloaded"
        DOWNLOADING = "downloading"


@unittest.skipUnless(HAS_DEPS, "Requires sqlalchemy and project dependencies")
class TestUpgradeFeature(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        Session = sessionmaker(bind=self.engine)
        self.db = Session()

        # Create default quality profile
        self.profile = QualityProfile(
            name="HD-1080p",
            cutoff_quality="WEBDL-1080p",
            allowed_qualities=["SDTV", "WEBDL-720p", "WEBDL-1080p", "Bluray-1080p"],
            upgrade_allowed=True,
        )
        self.db.add(self.profile)
        self.db.commit()
        self.db.refresh(self.profile)

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_upgrade_toggle_logic(self):
        show = Show(title="Breaking Bad", quality_profile_id=self.profile.id, monitored=True, content_type="series")
        self.db.add(show)
        self.db.commit()

        ep1 = Episode(show_id=show.id, season_number=1, episode_number=1, status=EpisodeStatus.DOWNLOADED, downloaded_quality="SDTV", monitored=True)
        ep2 = Episode(show_id=show.id, season_number=1, episode_number=2, status=EpisodeStatus.DOWNLOADED, downloaded_quality="SDTV", monitored=True)
        ep3 = Episode(show_id=show.id, season_number=2, episode_number=1, status=EpisodeStatus.DOWNLOADED, downloaded_quality="SDTV", monitored=False)
        self.db.add_all([ep1, ep2, ep3])
        self.db.commit()

        # Toggle episode
        ep1.upgrade_requested = True
        ep1.monitored = True
        self.db.commit()
        self.assertTrue(ep1.upgrade_requested)
        self.assertTrue(ep1.monitored)

        # Toggle season 1
        for ep in [ep1, ep2]:
            ep.upgrade_requested = True
            ep.monitored = True
        self.db.commit()
        self.assertTrue(ep1.upgrade_requested)
        self.assertTrue(ep2.upgrade_requested)

        # Toggle whole show
        show.upgrade_requested = True
        show.monitored = True
        for ep in [ep1, ep2, ep3]:
            ep.upgrade_requested = True
            ep.monitored = True
        self.db.commit()

        self.assertTrue(show.upgrade_requested)
        self.assertTrue(show.monitored)
        self.assertTrue(ep3.upgrade_requested)
        self.assertTrue(ep3.monitored)

    def test_search_and_grab_finds_higher_quality_for_upgrade_requested(self):
        show = Show(title="Breaking Bad", quality_profile_id=self.profile.id, monitored=True, content_type="series")
        self.db.add(show)
        self.db.commit()

        ep1 = Episode(
            show_id=show.id,
            season_number=1,
            episode_number=1,
            status=EpisodeStatus.DOWNLOADED,
            downloaded_quality="SDTV",
            monitored=True,
            upgrade_requested=True
        )
        self.db.add(ep1)

        idx = Indexer(name="Torznab1", type=IndexerType.TORZNAB, base_url="http://fake.local", enabled=True, priority=0)
        self.db.add(idx)

        dc = DownloadClient(name="DC1", type="qbittorrent", host="localhost", port=8080, is_default=True, enabled=True)
        self.db.add(dc)
        self.db.commit()

        from app.models.db import Alias
        self.db.add(Alias(show_id=show.id, text="Breaking Bad"))
        self.db.commit()

        # Mock download client and torznab releases
        class MockDC:
            async def add_torrent(self, url, category=None, save_path=None):
                return "test-hash-upgrade-123"
            async def get_torrent(self, torrent_hash):
                return None
            async def set_file_priorities(self, torrent_hash, file_indices, priority):
                pass

        releases = [
            TorznabRelease(
                title="Breaking.Bad.S01E01.1080p.WEB-DL.Rus.Eng",
                guid="guid-1080p",
                download_url="http://fake.local/bb_s01e01_1080p.torrent",
                page_url="http://fake.local/view/1",
                seeders=10,
                size_bytes=1500000000,
            )
        ]

        async def _async_return(val):
            return val

        fake_dc = MockDC()

        with patch("app.services.indexer_service.TorznabIndexerClient.search", lambda self_c, query, categories=None: _async_return(releases)), \
             patch("app.services.auto_search.get_client", lambda row: fake_dc):
            res = asyncio.run(auto_search.search_and_grab_show(self.db, show, wanted_only=False))

        self.assertIn("grabbed", res)
        self.assertGreater(len(res["grabbed"]), 0)
        self.db.refresh(ep1)
        self.assertEqual(ep1.status, EpisodeStatus.DOWNLOADING)
        self.assertEqual(ep1.torrent_hash, "test-hash-upgrade-123")

    def test_postprocess_resets_upgrade_requested_on_reaching_cutoff(self):
        with tempfile.TemporaryDirectory() as root_folder, tempfile.TemporaryDirectory() as dl_folder:
            show = Show(
                title="Breaking Bad",
                quality_profile_id=self.profile.id,
                monitored=True,
                content_type="series",
                path=os.path.join(root_folder, "Breaking Bad")
            )
            self.db.add(show)
            self.db.commit()

            ep1 = Episode(
                show_id=show.id,
                season_number=1,
                episode_number=1,
                status=EpisodeStatus.DOWNLOADING,
                downloaded_quality="SDTV",
                monitored=True,
                upgrade_requested=True
            )
            self.db.add(ep1)
            self.db.commit()

            # Create a mock 1080p video file in download directory
            dummy_file = os.path.join(dl_folder, "Breaking.Bad.S01E01.1080p.WEB-DL.mkv")
            with open(dummy_file, "wb") as f:
                f.write(b"dummy video data")

            process_download(
                db=self.db,
                show=show,
                download_path=dl_folder,
                rename_template="{show.title} - S{season:02d}E{episode:02d}",
                root_folder=root_folder,
            )

            self.db.refresh(ep1)
            self.assertEqual(ep1.status, EpisodeStatus.DOWNLOADED)
            self.assertEqual(ep1.downloaded_quality, "WEBDL-1080p")
            self.assertFalse(ep1.upgrade_requested, "upgrade_requested should be reset to False after reaching cutoff quality")

    def test_quality_profile_cutoff_persistence(self):
        from app.api.operations import create_quality_profile, update_quality_profile, list_quality_profiles
        from app.schemas import QualityProfileCreate, QualityProfileUpdate
        from types import SimpleNamespace

        admin_user = SimpleNamespace(id=1, username="admin", role="admin")

        # 1. Create with cutoff_quality and cutoff_score
        payload_create = QualityProfileCreate(
            name="Ultra-HD",
            allowed_qualities=["Bluray-1080p", "Bluray-2160p"],
            cutoff_quality="Bluray-2160p",
            cutoff_score=500,
            upgrade_allowed=True,
        )
        created = create_quality_profile(payload_create, self.db, admin_user)
        self.assertEqual(created.cutoff_quality, "Bluray-2160p")
        self.assertEqual(created.cutoff_score, 500)

        # 2. Update cutoff_quality and cutoff_score
        payload_update = QualityProfileUpdate(
            cutoff_quality="Bluray-1080p",
            cutoff_score=250,
        )
        updated = update_quality_profile(created.id, payload_update, self.db, admin_user)
        self.assertEqual(updated.cutoff_quality, "Bluray-1080p")
        self.assertEqual(updated.cutoff_score, 250)

        # 3. List profiles and verify cutoff values are returned
        profiles = list_quality_profiles(self.db, admin_user)
        found = next((p for p in profiles if p.id == created.id), None)
        self.assertIsNotNone(found)
        self.assertEqual(found.cutoff_quality, "Bluray-1080p")
        self.assertEqual(found.cutoff_score, 250)


if __name__ == "__main__":
    unittest.main()
