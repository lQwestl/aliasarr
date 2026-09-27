"""Проверка обновлённой темы на трекере не должна портить статусы серий.

Тема сообщает только номера серий. Серия, которая уже качается, у которой есть
файл или которую пользователь исключил, остаётся как была; номер без сезона
ищется по абсолютной нумерации, а не в спецвыпусках.
"""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.services.tracker as tracker
from app.models.db import Base, Episode, EpisodeStatus, Indexer, Show, TrackedRelease


class _Release:
    def __init__(self, title, guid="topic-1"):
        self.title = title
        self.guid = guid
        self.page_url = None
        self.download_url = "http://tracker/dl/1"
        self.infohash = None


def _client_returning(title):
    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        async def search(self, query):
            return [_Release(title)]

    return _Client


class TestTrackerEpisodeStatus(unittest.TestCase):
    def setUp(self):
        engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
        )
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()
        self.indexer = Indexer(name="tracker", type="torznab", base_url="http://tracker", api_key="k")
        self.show = Show(title="Frieren", content_type="anime", monitored=True)
        self.db.add_all([self.indexer, self.show])
        self.db.flush()

        def ep(season, number, status, **kw):
            row = Episode(show_id=self.show.id, season_number=season, episode_number=number, status=status, **kw)
            self.db.add(row)
            return row

        self.e1 = ep(1, 1, EpisodeStatus.DOWNLOADED, file_path="/media/Frieren/e1.mkv", absolute_number=1)
        self.e2 = ep(1, 2, EpisodeStatus.DOWNLOADING, torrent_hash="abc", absolute_number=2)
        self.e3 = ep(1, 3, EpisodeStatus.IGNORED, absolute_number=3)
        self.e4 = ep(1, 4, EpisodeStatus.MISSING, absolute_number=4)
        self.e5 = ep(1, 5, EpisodeStatus.MISSING, monitored=False, absolute_number=5)
        self.special2 = ep(0, 2, EpisodeStatus.IGNORED)
        self.tracked = TrackedRelease(
            show_id=self.show.id, indexer_id=self.indexer.id, topic_guid="topic-1", topic_url="",
            downloaded_episodes=[{"season": 1, "episode": 1}], active=True,
        )
        self.db.add(self.tracked)
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def _recheck(self, title):
        with patch.object(tracker, "TorznabClient", _client_returning(title)):
            return asyncio.run(tracker.recheck_tracked_release(self.db, self.tracked))

    def _status(self, episode):
        self.db.refresh(episode)
        return episode.status

    def test_only_searchable_episodes_become_wanted(self):
        result = self._recheck("Frieren / Сезон: 1 / Серии: 1-5 из 28 [2023, WEB-DL 1080p]")
        self.assertEqual(result["new_episodes"], [4])
        self.assertEqual(self._status(self.e2), EpisodeStatus.DOWNLOADING)
        self.assertEqual(self.e2.torrent_hash, "abc")
        self.assertEqual(self._status(self.e3), EpisodeStatus.IGNORED)
        self.assertEqual(self._status(self.e4), EpisodeStatus.WANTED)
        self.assertEqual(self._status(self.e5), EpisodeStatus.MISSING)

    def test_absolute_number_does_not_hit_specials(self):
        self.e4.status = EpisodeStatus.MISSING
        self.db.commit()
        self._recheck("[SubsPlease] Frieren - 04 (1080p)")
        self.assertEqual(self._status(self.special2), EpisodeStatus.IGNORED)
        self.assertEqual(self._status(self.e4), EpisodeStatus.WANTED)

    def test_seen_episodes_are_remembered(self):
        self._recheck("Frieren / Сезон: 1 / Серии: 1-5 из 28")
        self.e4.status = EpisodeStatus.DOWNLOADING
        self.db.commit()
        second = self._recheck("Frieren / Сезон: 1 / Серии: 1-5 из 28")
        self.assertFalse(second["updated"])
        self.assertEqual(self._status(self.e4), EpisodeStatus.DOWNLOADING)

    def test_duplicate_topics_keep_only_newest_record(self):
        newer = TrackedRelease(
            show_id=self.show.id, indexer_id=self.indexer.id, topic_guid="topic-1", topic_url="",
            downloaded_episodes=[], active=True,
        )
        self.db.add(newer)
        self.db.commit()
        active = tracker._deactivate_duplicate_topics(self.db, [self.tracked, newer])
        self.assertEqual([t.id for t in active], [newer.id])
        self.assertFalse(self.tracked.active)


if __name__ == "__main__":
    unittest.main()
