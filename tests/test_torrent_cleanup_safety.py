"""Aliasarr делит торрент-клиент с другими программами и личными раздачами.

Проверяется, что очистка и перезапуск раздач касаются только того, что добавил
сам Aliasarr, что захват нового релиза не удаляет раздачи, которые ещё нужны,
и что незавершённый апгрейд не подменяет качество существующего файла.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.services.downloads_monitor as dm
from app.models.db import (
    Base,
    DownloadClient,
    DownloadHistory,
    Episode,
    EpisodeStatus,
    Show,
    TrackedRelease,
)
from app.services.auto_search import _remove_superseded_torrent
from app.services.download_client import TorrentInfo


class _FakeClient:
    def __init__(self, torrents=None, info=None):
        self.torrents = torrents or []
        self.info = info or {}
        self.removed: list[tuple[str, bool]] = []
        self.resumed: list[str] = []
        self.limits: list[str] = []

    async def list_torrents(self):
        return self.torrents

    async def get_torrent(self, torrent_hash):
        return self.info.get(torrent_hash)

    async def remove_torrent(self, torrent_hash, delete_files=False):
        self.removed.append((torrent_hash, delete_files))

    async def resume_torrent(self, torrent_hash):
        self.resumed.append(torrent_hash)

    async def set_seeding_limits(self, torrent_hash, **kwargs):
        self.limits.append(torrent_hash)


def _torrent(torrent_hash, name, state, ratio, progress=1.0):
    return TorrentInfo(
        hash=torrent_hash, name=name, progress=progress, state=state,
        save_path="/downloads/other", size=10, ratio=ratio,
    )


class _DbCase(unittest.TestCase):
    def setUp(self):
        engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
        )
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()
        self.show = Show(title="Dexter", content_type="series", monitored=True)
        self.db.add(self.show)
        self.db.flush()
        self.dc = DownloadClient(
            name="qb", type="qbittorrent", host="qb", port=8080,
            category="tv", enabled=True, seed_ratio_limit=1.0,
        )
        self.db.add(self.dc)
        self.db.commit()
        dm.clear_unregistered_and_healed_torrents()
        dm.clear_pending_manual_import_torrents()

    def tearDown(self):
        self.db.close()


class TestSeedingCleanupOwnership(_DbCase):
    def _run(self, client):
        with patch.object(dm, "get_client", lambda row: client):
            asyncio.run(dm._check_seeding_torrents(self.db, [self.dc]))

    def test_foreign_torrents_are_never_removed_or_resumed(self):
        client = _FakeClient(torrents=[
            _torrent("aaaa", "My.Personal.Linux.ISO", "stalledup", ratio=2.5),
            _torrent("bbbb", "Family.Video", "pausedup", ratio=0.2),
        ])
        self._run(client)
        self.assertEqual(client.removed, [])
        self.assertEqual(client.resumed, [])
        self.assertEqual(client.limits, [])

    def test_own_torrent_is_removed_when_seed_limit_is_reached(self):
        self.db.add(DownloadHistory(
            show_id=self.show.id, release_title="Dexter.S01", torrent_hash="cccc", event_type="grabbed",
        ))
        self.db.commit()
        client = _FakeClient(torrents=[_torrent("cccc", "Dexter.S01", "stalledup", ratio=1.5)])
        self._run(client)
        self.assertEqual(client.removed, [("cccc", True)])

    def test_tracked_infohash_counts_as_own_torrent(self):
        self.db.add(TrackedRelease(
            show_id=self.show.id, indexer_id=1, topic_guid="g", topic_url="",
            infohash="DDDD", downloaded_episodes=[],
        ))
        self.db.commit()
        client = _FakeClient(torrents=[_torrent("dddd", "Dexter.S02", "stalledup", ratio=3.0)])
        self._run(client)
        self.assertEqual(client.removed, [("dddd", True)])


class TestSupersededTorrentRemoval(_DbCase):
    def _episode(self, number, status, torrent_hash, file_path=None):
        ep = Episode(
            show_id=self.show.id, season_number=1, episode_number=number,
            status=status, torrent_hash=torrent_hash, file_path=file_path,
        )
        self.db.add(ep)
        self.db.flush()
        return ep

    def test_finished_torrent_is_kept_as_seeding_source(self):
        ep = self._episode(1, EpisodeStatus.DOWNLOADED, "pack", file_path="/media/Dexter/S01E01.mkv")
        client = _FakeClient(info={"pack": _torrent("pack", "Dexter.S01", "stalledup", ratio=0.1)})
        removed = asyncio.run(_remove_superseded_torrent(self.db, client, "pack", {ep.id}, self.show.id))
        self.assertFalse(removed)
        self.assertEqual(client.removed, [])

    def test_torrent_still_downloading_other_episodes_is_kept(self):
        ep1 = self._episode(1, EpisodeStatus.DOWNLOADING, "pack")
        self._episode(2, EpisodeStatus.DOWNLOADING, "pack")
        client = _FakeClient(info={"pack": _torrent("pack", "Dexter.S01", "downloading", 0.0, progress=0.4)})
        removed = asyncio.run(_remove_superseded_torrent(self.db, client, "pack", {ep1.id}, self.show.id))
        self.assertFalse(removed)
        self.assertEqual(client.removed, [])

    def test_unfinished_duplicate_is_removed(self):
        ep1 = self._episode(1, EpisodeStatus.DOWNLOADING, "dupe")
        client = _FakeClient(info={"dupe": _torrent("dupe", "Dexter.S01E01", "stalleddl", 0.0, progress=0.1)})
        removed = asyncio.run(_remove_superseded_torrent(self.db, client, "dupe", {ep1.id}, self.show.id))
        self.assertTrue(removed)
        self.assertEqual(client.removed, [("dupe", True)])

    def test_torrent_missing_from_client_is_left_alone(self):
        ep1 = self._episode(1, EpisodeStatus.DOWNLOADING, "gone")
        client = _FakeClient()
        removed = asyncio.run(_remove_superseded_torrent(self.db, client, "gone", {ep1.id}, self.show.id))
        self.assertFalse(removed)


class TestStalledImportBackoff(unittest.TestCase):
    def setUp(self):
        dm.clear_pending_manual_import_torrents()

    def test_same_pending_set_is_not_retried_immediately(self):
        dm._remember_stalled_import("ABC", frozenset({1, 2}))
        self.assertTrue(dm._import_is_stalled("abc", frozenset({1, 2})))

    def test_changed_pending_set_retries(self):
        dm._remember_stalled_import("abc", frozenset({1, 2}))
        self.assertFalse(dm._import_is_stalled("abc", frozenset({2})))

    def test_retry_after_interval(self):
        dm._remember_stalled_import("abc", frozenset({1}))
        with patch.object(dm.time, "monotonic", return_value=dm.time.monotonic() + dm._STALLED_IMPORT_RETRY_SECONDS + 1):
            self.assertFalse(dm._import_is_stalled("abc", frozenset({1})))

    def test_manual_import_clears_backoff(self):
        dm._remember_stalled_import("abc", frozenset({1}))
        dm.unmark_torrent_pending_manual_import("ABC")
        self.assertFalse(dm._import_is_stalled("abc", frozenset({1})))


class TestDownloadPathFallback(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = os.path.realpath(self.tmp.name)
        self.settings = SimpleNamespace(download_folder="")

    def tearDown(self):
        self.tmp.cleanup()

    def _touch(self, name):
        path = os.path.join(self.root, name)
        with open(path, "wb") as fh:
            fh.write(b"x")
        return path

    def _resolve(self, torrent_name):
        t = SimpleNamespace(
            name=torrent_name, save_path=self.root, content_path="", files=[],
        )
        show = SimpleNamespace(id=1, title="Dexter", aliases=[], content_type="series")
        return dm._resolve_torrent_files_and_path(t, self.settings, show)

    def test_neighbouring_releases_of_the_same_show_are_not_claimed(self):
        self._touch("Dexter.S01E01.1080p.mkv")
        self._touch("Dexter.S02E05.720p.mkv")
        path, files = self._resolve("Dexter.S03E01.2160p.WEB-DL")
        self.assertEqual(files, [])
        self.assertNotIn("Dexter.S01E01", path)

    def test_renamed_single_file_of_the_torrent_is_found(self):
        renamed = self._touch("Dexter.S03E01.2160p.WEB-DL-.mkv")
        path, files = self._resolve("Dexter.S03E01.2160p.WEB-DL.mkv")
        self.assertEqual(files, [renamed])
        self.assertEqual(path, renamed)


if __name__ == "__main__":
    unittest.main()
