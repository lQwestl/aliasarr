"""
Unit tests for upgrade_requested functionality:
- Setting upgrade_requested on episode, season, show
- Resetting upgrade_requested when reaching cutoff quality
- Auto search picking up downloaded episodes with upgrade_requested = True
"""
from __future__ import annotations

import asyncio
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
                size=1500000000,
            )
        ]

        with patch("app.services.auto_search.get_download_client", return_value=MockDC()), \
             patch("app.services.auto_search.search_all_indexers", return_value=releases):
            res = asyncio.run(auto_search.search_and_grab_show(self.db, show, wanted_only=False))

        self.assertTrue(res.get("success"))
        self.assertGreater(res.get("grabbed_count", 0), 0)
        self.db.refresh(ep1)
        self.assertEqual(ep1.status, EpisodeStatus.DOWNLOADING)
        self.assertEqual(ep1.torrent_hash, "test-hash-upgrade-123")

    def test_postprocess_resets_upgrade_requested_on_reaching_cutoff(self):
        from app.services.postprocess import _process_single_episode
        from types import SimpleNamespace

        show = Show(title="Breaking Bad", quality_profile_id=self.profile.id, monitored=True, content_type="series")
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

        # Simulate importing a 1080p file which meets cutoff "WEBDL-1080p"
        media_file = SimpleNamespace(
            quality="WEBDL-1080p",
            season=1,
            episode=1,
            dynamic_range=None,
            video_codec="H.264",
            audio_codec="AC3",
            release_group="TestGroup",
            languages=[],
        )

        with patch("app.services.postprocess.organize_and_import_file", return_value="/media/shows/Breaking Bad/S01E01.mkv"):
            _process_single_episode(self.db, show, ep1, media_file, "/tmp/src/file.mkv", True)

        self.db.refresh(ep1)
        self.assertEqual(ep1.status, EpisodeStatus.DOWNLOADED)
        self.assertEqual(ep1.downloaded_quality, "WEBDL-1080p")
        self.assertFalse(ep1.upgrade_requested, "upgrade_requested should be reset to False after reaching cutoff quality")


if __name__ == "__main__":
    unittest.main()
