"""Season-scoped pinned torrent regression tests (no network/download client)."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.indexers import (
    FavoriteReleaseRequest,
    list_favorite_releases,
    pin_favorite_release,
    unpin_favorite_release,
)
from app.models.db import Alias, Base, DownloadClient, Episode, EpisodeStatus, Indexer, Show, TrackedRelease
from app.services.auto_search import _do_search_and_grab
from app.services.torznab import TorznabRelease
from app.services.tracker import recheck_tracked_release


class FavoriteReleaseTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.show = Show(title="Oldskul", content_type="series", monitored=True)
        self.db.add(self.show)
        self.db.flush()
        self.first = Episode(show_id=self.show.id, season_number=1, episode_number=1, status=EpisodeStatus.WANTED)
        self.second = Episode(show_id=self.show.id, season_number=2, episode_number=1, status=EpisodeStatus.WANTED)
        self.indexer = Indexer(name="Kinozal", type="torznab", base_url="https://indexer.invalid", enabled=True)
        self.db.add_all([self.first, self.second, self.indexer])
        self.db.commit()
        self.release = TorznabRelease(
            title="Oldskul S02 1-10 WEB-DL 1080p", guid="kinozal-123",
            page_url="https://tracker.invalid/topic/123",
            download_url="https://indexer.invalid/download/123", size_bytes=123456,
        )

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    async def _pin(self):
        client = SimpleNamespace(search=AsyncMock(return_value=[self.release]))
        payload = FavoriteReleaseRequest(
            season=2, indexer_id=self.indexer.id,
            guid=self.release.guid, title=self.release.title,
        )
        with patch("app.api.indexers.get_indexer_client", return_value=client):
            return await pin_favorite_release(self.show.id, payload, self.db, None)

    async def test_pin_replace_and_unpin_are_season_scoped(self):
        result = await self._pin()
        self.assertEqual(result["season"], 2)
        self.assertEqual(len(list_favorite_releases(self.show.id, self.db, None)), 1)

        # Re-pinning the same GUID is idempotent.
        await self._pin()
        self.assertEqual(len(list_favorite_releases(self.show.id, self.db, None)), 1)

        replacement = TorznabRelease(
            title="Oldskul S02 1-11 WEB-DL 1080p", guid="kinozal-456",
            page_url="https://tracker.invalid/topic/456",
            download_url="https://indexer.invalid/download/456",
        )
        client = SimpleNamespace(search=AsyncMock(return_value=[replacement]))
        with patch("app.api.indexers.get_indexer_client", return_value=client):
            await pin_favorite_release(
                self.show.id,
                FavoriteReleaseRequest(
                    season=2, indexer_id=self.indexer.id,
                    guid=replacement.guid, title=replacement.title,
                ),
                self.db, None,
            )
        active = list_favorite_releases(self.show.id, self.db, None)
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0]["guid"], replacement.guid)

        self.assertTrue(unpin_favorite_release(self.show.id, 2, self.db, None)["removed"])
        self.assertEqual(list_favorite_releases(self.show.id, self.db, None), [])

    async def test_pin_rejects_guid_not_returned_by_indexer(self):
        client = SimpleNamespace(search=AsyncMock(return_value=[]))
        payload = FavoriteReleaseRequest(
            season=2, indexer_id=self.indexer.id,
            guid=self.release.guid, title=self.release.title,
        )
        with patch("app.api.indexers.get_indexer_client", return_value=client):
            with self.assertRaises(HTTPException) as error:
                await pin_favorite_release(self.show.id, payload, self.db, None)
        self.assertEqual(error.exception.status_code, 404)
        self.assertEqual(list_favorite_releases(self.show.id, self.db, None), [])

    async def test_pin_preserves_verified_alias_for_future_checks(self):
        self.show.title = "Old School"
        self.db.add(Alias(show_id=self.show.id, text="Олдскул", language="ru"))
        self.db.commit()
        self.release.title = "Олдскул S02 1-10 WEB-DL 1080p"

        async def search(query):
            return [self.release] if query == "Олдскул" else []

        client = SimpleNamespace(search=AsyncMock(side_effect=search))
        payload = FavoriteReleaseRequest(
            season=2, indexer_id=self.indexer.id,
            guid=self.release.guid, title=self.release.title,
            matched_alias="Олдскул",
        )
        with patch("app.api.indexers.get_indexer_client", return_value=client):
            await pin_favorite_release(self.show.id, payload, self.db, None)
        tracked = self.db.query(TrackedRelease).filter(TrackedRelease.favorite_season == 2).one()
        self.assertEqual(tracked.favorite_query, "Олдскул")

        client.search.reset_mock()
        with patch("app.services.tracker.get_indexer_client", return_value=client), \
             patch("app.services.tracker._release_fingerprint", new_callable=AsyncMock, return_value="btih:old"), \
             patch("app.services.auto_search.search_and_grab_show", new_callable=AsyncMock, return_value={"grabbed": []}):
            await recheck_tracked_release(self.db, tracked)
        client.search.assert_awaited_once_with("Олдскул")

    async def test_auto_search_excludes_only_pinned_season(self):
        await self._pin()
        seen = []

        async def collect(db, show, indexers, wanted_episodes=None):
            seen.extend((ep.season_number, ep.episode_number) for ep in wanted_episodes)
            return []

        with patch("app.services.auto_search._collect_candidates", side_effect=collect):
            await _do_search_and_grab(self.db, self.show)
        self.assertEqual(seen, [(1, 1)])

    async def test_tracker_uses_only_exact_topic_and_does_not_retry_same_version(self):
        await self._pin()
        tracked = self.db.query(TrackedRelease).filter(TrackedRelease.favorite_season == 2).one()
        other = TorznabRelease(title="Oldskul S02 1-10 WEB-DL 1080p", guid="other")
        client = SimpleNamespace(search=AsyncMock(return_value=[other, self.release]))
        grab = AsyncMock(return_value={"grabbed": [{"hash": "hash-new"}]})
        with patch("app.services.tracker.get_indexer_client", return_value=client), \
             patch("app.services.tracker._release_fingerprint", new_callable=AsyncMock, return_value="btih:hash-new"), \
             patch("app.services.auto_search.search_and_grab_show", grab):
            first = await recheck_tracked_release(self.db, tracked)
            second = await recheck_tracked_release(self.db, tracked)

        self.assertTrue(first["updated"])
        self.assertEqual(first["new_episodes"], [1])
        self.assertEqual(second["reason"], "unchanged")
        self.assertEqual(tracked.last_check_status, "unchanged")
        grab.assert_awaited_once()
        _, kwargs = grab.await_args
        self.assertIs(kwargs["pinned_release"][1], self.release)
        self.assertEqual(kwargs["episode_ids"], {self.second.id})

    async def test_missing_topic_does_not_search_other_indexers_or_grab(self):
        await self._pin()
        tracked = self.db.query(TrackedRelease).filter(TrackedRelease.favorite_season == 2).one()
        client = SimpleNamespace(search=AsyncMock(return_value=[]))
        grab = AsyncMock()
        with patch("app.services.tracker.get_indexer_client", return_value=client), \
             patch("app.services.auto_search.search_and_grab_show", grab):
            result = await recheck_tracked_release(self.db, tracked)
        self.assertEqual(result["reason"], "topic_not_found")
        self.assertEqual(tracked.last_check_status, "topic_not_found")
        grab.assert_not_awaited()

    async def test_pinned_grab_reuses_favorite_tracker_row(self):
        await self._pin()
        self.db.add(DownloadClient(
            name="Test client", type="qbittorrent", host="localhost", port=8080,
            enabled=True, is_default=True,
        ))
        self.db.commit()
        download_client = SimpleNamespace(add_torrent=AsyncMock(return_value="new-infohash"))
        self.release.seeders = 10

        with patch("app.services.auto_search.get_client", return_value=download_client), \
             patch("app.services.auto_search._limit_torrent_files_to_episodes", new_callable=AsyncMock):
            result = await _do_search_and_grab(
                self.db, self.show, episode_ids={self.second.id},
                wanted_only=True, pinned_release=(self.indexer, self.release),
            )

        self.assertEqual(len(result["grabbed"]), 1)
        tracked = self.db.query(TrackedRelease).filter(TrackedRelease.show_id == self.show.id).all()
        self.assertEqual(len(tracked), 1)
        self.assertEqual(tracked[0].infohash, "new-infohash")
        self.assertEqual(tracked[0].downloaded_episodes, [{"season": 2, "episode": 1}])
        self.db.refresh(self.first)
        self.assertEqual(self.first.status, EpisodeStatus.WANTED)


if __name__ == "__main__":
    unittest.main()
