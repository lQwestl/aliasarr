"""
Тесты логики автоматического поиска (app/services/auto_search.py):
- дедупликация кандидатов по guid при опросе нескольких индексаторов
- выбор лучшего релиза на пересекающийся набор серий
- фильтрация по минимальному числу сидов
- точечный поиск по выбранным episode_ids без захвата лишних серий

Сетевые запросы к Torznab и вызовы торрент-клиента изолированы моками.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import unittest
from unittest.mock import patch

try:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.models.db import (
        Alias,
        Base,
        DownloadClient,
        Episode,
        EpisodeStatus,
        Indexer,
        IndexerType,
        Show,
    )
    from app.services import auto_search
    from app.services.torznab import TorznabRelease
    HAS_DEPS = True
except ImportError:
    HAS_DEPS = False
    class EpisodeStatus:
        WANTED = "wanted"
    class IndexerType:
        TORZNAB = "torznab"
    class TorznabRelease:
        pass


def make_show(db, title="Test Show", monitored=True):
    show = Show(title=title, monitored=monitored, content_type="series")
    db.add(show)
    db.commit()
    db.refresh(show)
    return show


def make_episode(db, show, season=1, episode=1, status=EpisodeStatus.WANTED):
    ep = Episode(show_id=show.id, season_number=season, episode_number=episode, status=status)
    db.add(ep)
    db.commit()
    db.refresh(ep)
    return ep


def make_indexer(db, name="Indexer1", priority=0):
    idx = Indexer(name=name, type=IndexerType.TORZNAB, base_url="http://fake.local", priority=priority)
    db.add(idx)
    db.commit()
    db.refresh(idx)
    return idx


def make_download_client(db):
    dc = DownloadClient(name="DC1", type="qbittorrent", host="localhost", port=8080, is_default=True)
    db.add(dc)
    db.commit()
    db.refresh(dc)
    return dc


class FakeDownloadClient:
    """Мок download client — просто возвращает предсказуемый хэш, ничего не шлёт по сети."""

    def __init__(self):
        self.added = []

    async def add_torrent(self, url_or_magnet, category=None, save_path=None):
        self.added.append(url_or_magnet)
        return f"hash-{len(self.added)}"

    async def get_torrent(self, torrent_hash):
        return None

    async def set_file_priorities(self, torrent_hash, file_indices, priority):
        pass


def _release(guid, title, seeders, download_url=None):
    return TorznabRelease(
        title=title, guid=guid, download_url=download_url or f"http://fake.local/{guid}.torrent",
        page_url=f"http://fake.local/view/{guid}", seeders=seeders,
    )


class TestAutoSearch(unittest.TestCase):
    def setUp(self):
        if not HAS_DEPS:
            self.skipTest("sqlalchemy or app dependencies not installed in current environment")
        self.engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        Base.metadata.create_all(bind=self.engine)
        Session = sessionmaker(bind=self.engine)
        self.session = Session()

    def tearDown(self):
        if hasattr(self, "session") and self.session:
            self.session.close()

    def test_dedup_candidates_by_guid_across_aliases(self):
        """Один и тот же релиз (одинаковый guid), найденный по нескольким алиасам,
        должен попасть в кандидаты только один раз без дублирования."""
        show = make_show(self.session, title="The Series Title's!")
        self.session.add(Alias(show_id=show.id, text="The Series Title's!"))
        self.session.add(Alias(show_id=show.id, text="Сериал Тест"))
        self.session.commit()

        indexer = make_indexer(self.session)
        same_release = _release("guid-1", "The.Series.Title.S01E01.1080p.WEBDL", seeders=50)

        with patch("app.services.auto_search.TorznabClient.search", lambda self_c, query, categories=None: _async_return([same_release])):
            candidates = asyncio.run(auto_search._collect_candidates(self.session, show, [indexer]))
            self.assertEqual(len(candidates), 1, "Релиз с одинаковым guid не должен дублироваться в кандидатах")

    def test_single_release_grabbed_for_overlapping_episode_set(self):
        """Два релиза покрывают одну и ту же серию — должен быть скачан только один релиз."""
        show = make_show(self.session, title="Avengers Show")
        self.session.add(Alias(show_id=show.id, text="Avengers Show"))
        self.session.commit()

        make_episode(self.session, show, season=1, episode=1)
        make_indexer(self.session)
        make_download_client(self.session)

        season_pack = _release("guid-pack", "Avengers.Show.S01.COMPLETE.1080p.WEBDL", seeders=20)
        single_ep_popular = _release("guid-single", "Avengers.Show.S01E01.1080p.WEBDL", seeders=200)

        fake_dc = FakeDownloadClient()
        with patch("app.services.auto_search.TorznabClient.search", lambda self_c, query, categories=None: _async_return([season_pack, single_ep_popular])), \
             patch("app.services.auto_search.get_client", lambda row: fake_dc):
            result = asyncio.run(auto_search._do_search_and_grab(self.session, show))

            self.assertEqual(len(result["grabbed"]), 1, "На пересекающийся набор серий должен качаться только один релиз")
            self.assertEqual(result["grabbed"][0]["seeders"], 200, "Должен быть выбран самый раздающийся релиз")
            self.assertEqual(len(fake_dc.added), 1, "add_torrent должен быть вызван ровно один раз")

    def test_min_seeds_filter_excludes_low_seed_releases(self):
        """Релиз с числом сидов ниже настроенного минимума не должен захватываться."""
        show = make_show(self.session, title="Low Seed Show")
        self.session.add(Alias(show_id=show.id, text="Low Seed Show"))
        self.session.commit()

        make_episode(self.session, show, season=1, episode=1)
        make_indexer(self.session)
        make_download_client(self.session)

        from app.services.settings_service import get_or_create_settings
        settings = get_or_create_settings(self.session)
        settings.min_seeds = 10
        self.session.add(settings)
        self.session.commit()

        low_seed_release = _release("guid-lowseed", "Low.Seed.Show.S01E01.1080p.WEBDL", seeders=2)
        fake_dc = FakeDownloadClient()
        with patch("app.services.auto_search.TorznabClient.search", lambda self_c, query, categories=None: _async_return([low_seed_release])), \
             patch("app.services.auto_search.get_client", lambda row: fake_dc):
            result = asyncio.run(auto_search._do_search_and_grab(self.session, show))

            self.assertEqual(result["grabbed"], [], "Релиз ниже min_seeds не должен захватываться")
            self.assertEqual(fake_dc.added, [], "add_torrent не должен вызываться, если ни один релиз не прошёл фильтр")

    def test_search_by_specific_episode_ids_does_not_grab_whole_season(self):
        """Поиск, запущенный для конкретной серии (episode_ids), не должен
        захватывать релизы, покрывающие другие wanted-серии того же шоу."""
        show = make_show(self.session, title="Multi Ep Show")
        self.session.add(Alias(show_id=show.id, text="Multi Ep Show"))
        self.session.commit()

        ep1 = make_episode(self.session, show, season=1, episode=1)
        ep2 = make_episode(self.session, show, season=1, episode=2)
        make_indexer(self.session)
        make_download_client(self.session)

        ep1_release = _release("guid-ep1", "Multi.Ep.Show.S01E01.1080p.WEBDL", seeders=50)
        ep2_release = _release("guid-ep2", "Multi.Ep.Show.S01E02.1080p.WEBDL", seeders=50)

        fake_dc = FakeDownloadClient()
        with patch("app.services.auto_search.TorznabClient.search", lambda self_c, query, categories=None: _async_return([ep1_release, ep2_release])), \
             patch("app.services.auto_search.get_client", lambda row: fake_dc):
            result = asyncio.run(auto_search._do_search_and_grab(self.session, show, episode_ids={ep1.id}))

            grabbed_episode_ids = {g["episode_id"] for g in result["grabbed"]}
            self.assertEqual(grabbed_episode_ids, {ep1.id}, "Должна быть захвачена только запрошенная серия")
            self.assertEqual(len(fake_dc.added), 1)

            self.session.refresh(ep2)
            self.assertEqual(ep2.status, EpisodeStatus.WANTED, "Серия, не входящая в episode_ids, не должна трогаться")

    def test_wrong_season_release_not_grabbed_for_absolute_numbering(self):
        """Релиз без явного сезона в названии не должен ошибочно захватываться для 2 сезона."""
        show = make_show(self.session, title="My Hero Academia")
        self.session.add(Alias(show_id=show.id, text="My Hero Academia"))
        self.session.commit()

        ep_s2e2 = make_episode(self.session, show, season=2, episode=2)
        make_indexer(self.session)
        make_download_client(self.session)

        absolute_release = _release("guid-abs", "My.Hero.Academia.-.02.1080p.WEBDL", seeders=50)
        wrong_season_release = _release("guid-s5", "My.Hero.Academia.S05E02.1080p.WEBDL", seeders=50)

        fake_dc = FakeDownloadClient()
        with patch("app.services.auto_search.TorznabClient.search", lambda self_c, query, categories=None: _async_return([absolute_release, wrong_season_release])), \
             patch("app.services.auto_search.get_client", lambda row: fake_dc):
            result = asyncio.run(auto_search._do_search_and_grab(self.session, show, episode_ids={ep_s2e2.id}))

            self.assertEqual(result["grabbed"], [], "Ни один из релизов не относится ко 2 сезону — захватываться не должно")
            self.assertEqual(len(fake_dc.added), 0)

    def test_correct_season_release_grabbed_with_ru_season_word(self):
        """Релиз с явным «Сезон 1 Серия 3» должен матчиться под нужный сезон/серию."""
        show = make_show(self.session, title="Тестовое Аниме")
        self.session.add(Alias(show_id=show.id, text="Тестовое Аниме"))
        self.session.commit()

        ep = make_episode(self.session, show, season=1, episode=3)
        make_indexer(self.session)
        make_download_client(self.session)

        release = _release("guid-ru", "Тестовое.Аниме.Сезон.1.Серия.3.1080p", seeders=50)
        fake_dc = FakeDownloadClient()
        with patch("app.services.auto_search.TorznabClient.search", lambda self_c, query, categories=None: _async_return([release])), \
             patch("app.services.auto_search.get_client", lambda row: fake_dc):
            result = asyncio.run(auto_search._do_search_and_grab(self.session, show, episode_ids={ep.id}))

            grabbed_episode_ids = {g["episode_id"] for g in result["grabbed"]}
            self.assertEqual(grabbed_episode_ids, {ep.id})
            self.assertEqual(len(fake_dc.added), 1)

    def test_wanted_search_ignores_already_downloaded_movie(self):
        """Автопоиск разыскиваемых релизов (Wanted) не должен трогать уже скачанный фильм."""
        movie = Show(title="The Robot Chicken: Star Wars", monitored=True, content_type="movie")
        self.session.add(movie)
        self.session.commit()
        self.session.refresh(movie)

        self.session.add(Alias(show_id=movie.id, text="The Robot Chicken: Star Wars"))
        self.session.add(Alias(show_id=movie.id, text="Robot Chicken Star Wars"))
        self.session.commit()

        ep = make_episode(self.session, movie, season=1, episode=1, status=EpisodeStatus.DOWNLOADED)
        ep.downloaded_quality = "WEBDL-1080p"
        self.session.add(ep)
        self.session.commit()

        make_indexer(self.session)
        make_download_client(self.session)

        release = _release("guid-movie", "The.Robot.Chicken.Star.Wars.2007.BDRip.1080p", seeders=100)
        fake_dc = FakeDownloadClient()

        with patch("app.services.auto_search.TorznabClient.search", lambda self_c, query, categories=None: _async_return([release])), \
             patch("app.services.auto_search.get_client", lambda row: fake_dc):
            results = asyncio.run(auto_search.run_wanted_search(self.session))

            self.assertEqual(results, [], "У фильма нет wanted серий — он не должен захватываться в wanted_search")
            self.assertEqual(len(fake_dc.added), 0)
            self.session.refresh(ep)
            self.assertEqual(ep.status, EpisodeStatus.DOWNLOADED, "Статус фильма должен остаться DOWNLOADED")

    def test_search_and_grab_wanted_only_flag(self):
        """С флагом wanted_only=True поиск не пытается апгрейдить DOWNLOADED серии."""
        movie = Show(title="Star Wars Movie", monitored=True, content_type="movie")
        self.session.add(movie)
        self.session.commit()
        self.session.refresh(movie)

        self.session.add(Alias(show_id=movie.id, text="Star Wars Movie"))
        self.session.commit()

        ep = make_episode(self.session, movie, season=1, episode=1, status=EpisodeStatus.DOWNLOADED)
        make_indexer(self.session)
        make_download_client(self.session)

        release = _release("guid-m", "Star.Wars.Movie.1080p.Remux", seeders=100)
        fake_dc = FakeDownloadClient()

        with patch("app.services.auto_search.TorznabClient.search", lambda self_c, query, categories=None: _async_return([release])), \
             patch("app.services.auto_search.get_client", lambda row: fake_dc):
            res = asyncio.run(auto_search._do_search_and_grab(self.session, movie, wanted_only=True))
            self.assertEqual(res["grabbed"], [])
            self.assertEqual(len(fake_dc.added), 0)

    def test_selective_episodes_priority_on_slime_season_3(self):
        """Проверяет корректность разметки приоритетов файлов для последних 2 серий 3 сезона аниме."""
        ep23 = Episode(id=101, season_number=3, episode_number=23, absolute_number=71)
        ep24 = Episode(id=102, season_number=3, episode_number=24, absolute_number=72)
        target_eps = [ep23, ep24]

        # Файлы 1..22 должны получить prio=0, файлы 23 и 24 — prio=1
        f01 = "[Beatrice-Raws] Tensei Shitara Slime Datta Ken 3rd Season 01 [BDRip 1920x1080 HEVC FLAC].mkv"
        f23 = "[Beatrice-Raws] Tensei Shitara Slime Datta Ken 3rd Season 23 [BDRip 1920x1080 HEVC FLAC].mkv"
        f24 = "[Beatrice-Raws] Tensei Shitara Slime Datta Ken 3rd Season 24 [BDRip 1920x1080 HEVC FLAC].mkv"
        sub01 = "ENG Subs/[Beatrice-Raws] Tensei Shitara Slime Datta Ken 3rd Season 01 [BDRip 1920x1080 HEVC FLAC].Asakura.ass"
        sub24 = "ENG Subs/[Beatrice-Raws] Tensei Shitara Slime Datta Ken 3rd Season 24 [BDRip 1920x1080 HEVC FLAC].Asakura.ass"

        self.assertEqual(auto_search.evaluate_torrent_file_priority(f01, 0, target_eps, True, content_type="anime"), 0)
        self.assertEqual(auto_search.evaluate_torrent_file_priority(f23, 1, target_eps, True, content_type="anime"), 1)
        self.assertEqual(auto_search.evaluate_torrent_file_priority(f24, 2, target_eps, True, content_type="anime"), 1)
        self.assertEqual(auto_search.evaluate_torrent_file_priority(sub01, 3, target_eps, True, content_type="anime"), 0)
        self.assertEqual(auto_search.evaluate_torrent_file_priority(sub24, 4, target_eps, True, content_type="anime"), 1)
