"""Планировщик переживает перезапуск сервера, а фоновые задачи уважают выбор пользователя."""

from __future__ import annotations

import asyncio
import datetime as dt
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.main as main_module
import app.services.metadata as metadata
from app.models.db import Base, Episode, EpisodeStatus, Show
from app.services.metadata import MetadataEpisode, MetadataShowDetails, refresh_show_release_dates


class TestSchedulerRestart(unittest.TestCase):
    def test_scheduler_survives_a_second_server_run_in_a_new_event_loop(self):
        """run.py перезапускает uvicorn в том же процессе (смена SSL/порта): каждый
        запуск получает новый event loop, а прежний закрывается."""

        async def job():
            return None

        async def one_server_run():
            scheduler = main_module._fresh_scheduler()
            scheduler.add_job(job, "interval", minutes=5, id="wanted_search")
            scheduler.start()
            await asyncio.sleep(0)
            self.assertIs(main_module.app.state.scheduler, scheduler)
            scheduler.shutdown()
            return scheduler

        first = asyncio.run(one_server_run())
        second = asyncio.run(one_server_run())
        self.assertIsNot(first, second)


class _MetadataCase(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        self.db = sessionmaker(bind=engine)()

    def tearDown(self):
        self.db.close()

    def _refresh(self, show, details, client_name):
        class _Client:
            async def get_details(self, metadata_id):
                return details

        with patch.object(metadata, client_name, _Client):
            return asyncio.run(refresh_show_release_dates(self.db, show))


class TestMetadataRefreshRespectsUser(_MetadataCase):
    def test_unmonitored_future_episode_stays_unmonitored(self):
        show = Show(title="Frieren", content_type="anime", monitored=True, metadata_id="1", metadata_source="skyhook")
        self.db.add(show)
        self.db.flush()
        future = (dt.datetime.utcnow() + dt.timedelta(days=30)).date().isoformat()
        ep = Episode(show_id=show.id, season_number=2, episode_number=1, status=EpisodeStatus.UNAIRED, monitored=False)
        self.db.add(ep)
        self.db.commit()

        details = MetadataShowDetails(
            external_id="1", title="Frieren",
            episodes=[MetadataEpisode(season_number=2, episode_number=1, air_date=future)],
        )
        self._refresh(show, details, "SkyHookClient")
        self.db.refresh(ep)
        self.assertFalse(ep.monitored)
        self.assertEqual(ep.status, EpisodeStatus.UNAIRED)

    def test_series_air_dates_are_refreshed(self):
        """Цикл по сериям был вложен в ветку фильмов, и календарь сериалов не обновлялся."""
        show = Show(title="Frieren", content_type="anime", monitored=True, metadata_id="1", metadata_source="skyhook")
        self.db.add(show)
        self.db.flush()
        ep = Episode(show_id=show.id, season_number=2, episode_number=3, status=EpisodeStatus.UNAIRED, monitored=True)
        self.db.add(ep)
        self.db.commit()
        announced = (dt.datetime.utcnow() + dt.timedelta(days=10)).date()
        details = MetadataShowDetails(
            external_id="1", title="Frieren",
            episodes=[MetadataEpisode(season_number=2, episode_number=3, air_date=announced.isoformat())],
        )
        self.assertTrue(self._refresh(show, details, "SkyHookClient"))
        self.db.refresh(ep)
        self.assertEqual(ep.air_date.date(), announced)

    def test_downloaded_movie_keeps_its_status_when_premiere_moves(self):
        movie = Show(title="Dune", content_type="movie", monitored=True, metadata_id="2", metadata_source="radarr")
        self.db.add(movie)
        self.db.flush()
        ep = Episode(
            show_id=movie.id, season_number=1, episode_number=1, status=EpisodeStatus.DOWNLOADED,
            file_path="/media/Dune/Dune.mkv", air_date=dt.datetime.utcnow() + dt.timedelta(days=3),
        )
        self.db.add(ep)
        self.db.commit()

        moved = (dt.datetime.utcnow() + dt.timedelta(days=60)).date().isoformat()
        details = MetadataShowDetails(external_id="2", title="Dune", premiere_date=moved, content_type="movie")
        self._refresh(movie, details, "RadarrClient")
        self.db.refresh(ep)
        self.assertEqual(ep.status, EpisodeStatus.DOWNLOADED)


if __name__ == "__main__":
    unittest.main()
