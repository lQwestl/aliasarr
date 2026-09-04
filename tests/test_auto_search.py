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


async def _async_return(val):
    return val


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

        with patch("app.services.indexer_service.TorznabIndexerClient.search", lambda self_c, query, categories=None: _async_return([same_release])):
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
        with patch("app.services.indexer_service.TorznabIndexerClient.search", lambda self_c, query, categories=None: _async_return([season_pack, single_ep_popular])), \
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
        with patch("app.services.indexer_service.TorznabIndexerClient.search", lambda self_c, query, categories=None: _async_return([low_seed_release])), \
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
        with patch("app.services.indexer_service.TorznabIndexerClient.search", lambda self_c, query, categories=None: _async_return([ep1_release, ep2_release])), \
             patch("app.services.auto_search.get_client", lambda row: fake_dc):
            result = asyncio.run(auto_search._do_search_and_grab(self.session, show, episode_ids={ep1.id}))

            grabbed_episode_ids = {g["episode_id"] for g in result["grabbed"]}
            self.assertEqual(grabbed_episode_ids, {ep1.id}, "Должна быть захвачена только запрошенная серия")
            self.assertEqual(len(fake_dc.added), 1)

            self.session.refresh(ep2)
            self.assertEqual(ep2.status, EpisodeStatus.WANTED, "Серия, не входящая в episode_ids, не должна трогаться")

    def test_auto_search_falls_back_to_next_candidate_if_first_fails(self):
        """Если лучший по скору релиз падает при добавлении в загрузчик (например 404 у трекера),
        система должна автоматически попытаться захватить следующий подходящий релиз."""
        show = make_show(self.session, title="Fallback Show")
        self.session.add(Alias(show_id=show.id, text="Fallback Show"))
        self.session.commit()

        ep1 = make_episode(self.session, show, season=1, episode=1)
        make_indexer(self.session)
        make_download_client(self.session)

        rel_failing = _release("guid-fail", "Fallback.Show.S01E01.1080p.WEBDL", seeders=100)
        rel_working = _release("guid-work", "Fallback.Show.S01E01.720p.WEBDL", seeders=40)

        class FailingFirstDownloadClient:
            def __init__(self):
                self.attempts = []

            async def add_torrent(self, url_or_magnet, category=None, save_path=None):
                self.attempts.append(url_or_magnet)
                if "guid-fail" in url_or_magnet:
                    raise RuntimeError("HTTP 404: Not Found")
                return "hash-working-123"

            async def remove_torrent(self, *args, **kwargs):
                pass

        fake_dc = FailingFirstDownloadClient()
        with patch("app.services.indexer_service.TorznabIndexerClient.search", lambda self_c, query, categories=None: _async_return([rel_failing, rel_working])), \
             patch("app.services.auto_search.get_client", lambda row: fake_dc):
            result = asyncio.run(auto_search._do_search_and_grab(self.session, show))

            self.assertEqual(len(result["grabbed"]), 1, "Должен быть захвачен второй кандидат после падения первого")
            self.assertEqual(result["grabbed"][0]["release"], "Fallback.Show.S01E01.720p.WEBDL")
            self.assertEqual(len(fake_dc.attempts), 2, "Загрузчик должен был сначала попробовать первый релиз, затем второй")

            self.session.refresh(ep1)
            self.assertEqual(ep1.status, EpisodeStatus.DOWNLOADING)
            self.assertEqual(ep1.torrent_hash, "hash-working-123")

    def test_evaluate_priority_absolute_numbering_and_torrent_name(self):
        """Проверяет корректность фильтрации файлов в раздачах со сквозной нумерацией (например Робоцып S05E01 = серия 81)."""
        ep1 = Episode(id=1, show_id=1, season_number=5, episode_number=1, absolute_number=81)
        ep6 = Episode(id=2, show_id=1, season_number=5, episode_number=6, absolute_number=86)
        targets = [ep1, ep6]

        # 1. Файл со сквозным номером 81 должен быть включен
        self.assertEqual(auto_search.evaluate_torrent_file_priority("Season 5/81.avi", 0, targets, torrent_name="Season 5"), 1)
        self.assertEqual(auto_search.evaluate_torrent_file_priority("Season 5/86 - Ep.avi", 1, targets, torrent_name="Season 5"), 1)
        self.assertEqual(auto_search.evaluate_torrent_file_priority("Season 5/82.avi", 2, targets, torrent_name="Season 5"), 0)

        # 2. Файлы без явного сезона в имени, но с именем торрента Season 5
        self.assertEqual(auto_search.evaluate_torrent_file_priority("01.avi", 0, targets, torrent_name="Season 5"), 1)
        self.assertEqual(auto_search.evaluate_torrent_file_priority("06.avi", 1, targets, torrent_name="Season 5"), 1)
        self.assertEqual(auto_search.evaluate_torrent_file_priority("02.avi", 2, targets, torrent_name="Season 5"), 0)

        # 3. Пути с обратными слэшами Windows (например из торрентов с RuTracker: 'Season 5\01.avi')
        self.assertEqual(auto_search.evaluate_torrent_file_priority("Season 5\\01.avi", 0, targets, torrent_name="Season 5"), 1)
        self.assertEqual(auto_search.evaluate_torrent_file_priority("Season 5\\81.avi", 1, targets, torrent_name="Season 5"), 1)
        self.assertEqual(auto_search.evaluate_torrent_file_priority("Season 5\\02.avi", 2, targets, torrent_name="Season 5"), 0)

        # 4. Сопоставление по названиям серий (при смещении нумерации в релизе из-за спешла)
        ep1_titled = Episode(id=1, show_id=1, season_number=5, episode_number=1, title="Saving Private Gigli")
        ep2_titled = Episode(id=2, show_id=1, season_number=5, episode_number=2, title="Terms of Endaredevil")
        ep6_titled = Episode(id=6, show_id=1, season_number=5, episode_number=6, title="Major League of Extraordinary Gentlemen")
        all_show_eps = [ep1_titled, ep2_titled, ep6_titled]
        wanted_eps = [ep1_titled, ep6_titled]

        # S05E02 в релизе на самом деле серия 1 (Saving Private Gigli) — должна быть 1!
        self.assertEqual(auto_search.evaluate_torrent_file_priority("S05E02 Saving Private Gigli.avi", 1, wanted_eps, all_show_episodes=all_show_eps), 1)
        # S05E07 в релизе на самом деле серия 6 (Major League...) — должна быть 1!
        self.assertEqual(auto_search.evaluate_torrent_file_priority("S05E07 Major League Of Extraordinary Gentlemen.avi", 6, wanted_eps, all_show_episodes=all_show_eps), 1)
        # S05E03 в релизе это серия 2 (Terms of Endaredevil) — не нужна, должна быть 0!
        self.assertEqual(auto_search.evaluate_torrent_file_priority("S05E03 Terms Of Endaredevil.avi", 2, wanted_eps, all_show_episodes=all_show_eps), 0)
        # S05E01 DP Christmas Special — спешл, должна быть 0!
        self.assertEqual(auto_search.evaluate_torrent_file_priority("S05E01 DP Christmas Special.avi", 0, wanted_eps, all_show_episodes=all_show_eps), 0)

        # 5. Сериал с титульной серией (например, Daredevil -> S01E13 "Daredevil")
        # Файлы S01E01..S01E13 не должны ложно сопоставляться с S01E13 только из-за названия тайтла в файле
        dd_episodes = [
            Episode(id=i, show_id=10, season_number=1, episode_number=i, title="Daredevil" if i == 13 else f"Episode {i}")
            for i in range(1, 14)
        ]
        dd_show_words = {"marvels", "daredevil", "сорвиголова"}
        matched_eps = []
        for i in range(1, 14):
            fname = f"Marvel's.Daredevil.S01E{i:02d}.1080p.BDRip.Rus.Eng.CasStudio.TV.mkv"
            prio = auto_search.evaluate_torrent_file_priority(
                fname, i - 1, dd_episodes, all_show_episodes=dd_episodes,
                out_matched_episodes=matched_eps, show_words=dd_show_words,
            )
            self.assertEqual(prio, 1)

        self.assertEqual(len(matched_eps), 13)
        matched_pairs = {(e.season_number, e.episode_number) for e in matched_eps}
        expected_pairs = {(1, i) for i in range(1, 14)}
        self.assertEqual(matched_pairs, expected_pairs)

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
        with patch("app.services.indexer_service.TorznabIndexerClient.search", lambda self_c, query, categories=None: _async_return([absolute_release, wrong_season_release])), \
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
        with patch("app.services.indexer_service.TorznabIndexerClient.search", lambda self_c, query, categories=None: _async_return([release])), \
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

        with patch("app.services.indexer_service.TorznabIndexerClient.search", lambda self_c, query, categories=None: _async_return([release])), \
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

        with patch("app.services.indexer_service.TorznabIndexerClient.search", lambda self_c, query, categories=None: _async_return([release])), \
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

    def test_genocyber_ova_priority_and_selective_matching(self):
        """Проверяет корректность разметки приоритетов файлов и сопоставления серий для OVA-тайтлов вроде Genocyber."""
        episodes = [
            Episode(id=100 + i, season_number=1, episode_number=i, absolute_number=None)
            for i in range(1, 6)
        ]
        files = [
            f"Genocyber - {i:02d} [OVA].mkv" for i in range(1, 6)
        ]
        for idx, f in enumerate(files):
            prio_s1 = auto_search.evaluate_torrent_file_priority(
                f, idx, episodes, True, content_type="anime", ova_mode="season_1"
            )
            self.assertEqual(prio_s1, 1, f"File {f} must have prio 1 for season_1")

            prio_auto = auto_search.evaluate_torrent_file_priority(
                f, idx, episodes, True, content_type="anime", ova_mode="auto"
            )
            self.assertEqual(prio_auto, 1, f"File {f} must have prio 1 for auto")

            prio_sp = auto_search.evaluate_torrent_file_priority(
                f, idx, episodes, True, content_type="anime", ova_mode="specials"
            )
            self.assertEqual(prio_sp, 0, f"File {f} must have prio 0 for specials")

    def test_limit_torrent_files_removes_mismatched_torrent(self):
        """Если раздача не содержит ни одной запрошенной серии (например, Part 1 1-12 при поиске 23-24),
        раздача удаляется из загрузчика, а статус серий возвращается в WANTED."""
        show = make_show(self.session, "Slime S2")
        ep23 = make_episode(self.session, show, season=2, episode=23, status=EpisodeStatus.DOWNLOADING)
        ep23.torrent_hash = "hash-part1"
        ep24 = make_episode(self.session, show, season=2, episode=24, status=EpisodeStatus.DOWNLOADING)
        ep24.torrent_hash = "hash-part1"
        self.session.commit()

        class MockTorrentClient:
            def __init__(self):
                self.removed = []
            async def get_torrent(self, torrent_hash):
                from app.services.download_client import TorrentInfo, TorrentFile
                files = [
                    TorrentFile(index=0, name="01. Rimurus Busy Life.mkv", size=1000, progress=0.0, priority=1),
                    TorrentFile(index=1, name="02. Trade with the Animal Kingdom.mkv", size=1000, progress=0.0, priority=1),
                ]
                return TorrentInfo(hash=torrent_hash, name="Slime Part 1", progress=0.0, state="downloading", save_path="", size=2000, files=files)
            async def remove_torrent(self, torrent_hash, delete_files=False):
                self.removed.append(torrent_hash)

        mock_client = MockTorrentClient()
        asyncio.run(auto_search._limit_torrent_files_to_episodes(
            mock_client,
            "hash-part1",
            [ep23, ep24],
            db=self.session,
            content_type="anime",
        ))

        self.assertIn("hash-part1", mock_client.removed, "Неподходящая раздача должна быть удалена из торрент-клиента")
        self.session.refresh(ep23)
        self.session.refresh(ep24)
        self.assertEqual(ep23.status, EpisodeStatus.WANTED, "Серия 23 должна вернуться в статус WANTED")
        self.assertEqual(ep24.status, EpisodeStatus.WANTED, "Серия 24 должна вернуться в статус WANTED")
        self.assertIsNone(ep23.torrent_hash)
        self.assertIsNone(ep24.torrent_hash)

    def test_selective_priority_part2_cours_and_subdirectories(self):
        """Проверяет корректность разметки файлов при сплит-курах (Part 2) и подпапках."""
        ep23 = Episode(id=201, season_number=2, episode_number=23, absolute_number=47)
        ep24 = Episode(id=202, season_number=2, episode_number=24, absolute_number=48)
        target_eps = [ep23, ep24]

        # Part 2 с 01..12 (11 -> 23, 12 -> 24)
        f_p1_01 = "Tensei Shitara Slime Datta Ken (2021)/Part 1/01. Rimurus Busy Life.mkv"
        f_p2_11 = "Tensei Shitara Slime Datta Ken (2021)/Part 2/11. The One Unleashed.mkv"
        f_p2_12 = "Tensei Shitara Slime Datta Ken (2021)/Part 2/12. Octagram.mkv"
        # Подпапки с 23, 24
        f_s2_p2_23 = "Season 2 Part 2/23. The One Unleashed.mkv"
        f_s2_p2_24 = "Season 2 Part 2/24. Octagram.mkv"

        self.assertEqual(auto_search.evaluate_torrent_file_priority(f_p1_01, 0, target_eps, True, content_type="anime"), 0)
        self.assertEqual(auto_search.evaluate_torrent_file_priority(f_p2_11, 1, target_eps, True, content_type="anime"), 1)
        self.assertEqual(auto_search.evaluate_torrent_file_priority(f_p2_12, 2, target_eps, True, content_type="anime"), 1)
        self.assertEqual(auto_search.evaluate_torrent_file_priority(f_s2_p2_23, 3, target_eps, True, content_type="anime"), 1)
        self.assertEqual(auto_search.evaluate_torrent_file_priority(f_s2_p2_24, 4, target_eps, True, content_type="anime"), 1)

    def test_quality_preference_over_multiseason_pack(self):
        """Проверяет, что релизы высокого качества из профиля побеждают низкокачественные мультисезонные паки."""
        if not HAS_DEPS:
            self.skipTest("sqlalchemy is missing")
        from app.models.db import QualityProfile

        qp = QualityProfile(
            name="Ultra-Remux",
            allowed_qualities=[
                "Remux-2160p", "Bluray-2160p", "WEBDL-2160p", "WEBRip-2160p",
                "Remux-1080p", "Bluray-1080p", "WEBDL-1080p", "WEBRip-1080p"
            ],
            upgrade_allowed=True,
        )
        self.session.add(qp)
        self.session.commit()
        self.session.refresh(qp)

        show = make_show(self.session, "Arcane")
        self.session.add(Alias(show_id=show.id, text="Arcane"))
        show.quality_profile_id = qp.id
        self.session.add(show)
        self.session.commit()

        # Создаём серии S01 (9 серий) и S02 (9 серий)
        s1_eps = [make_episode(self.session, show, season=1, episode=i) for i in range(1, 10)]
        s2_eps = [make_episode(self.session, show, season=2, episode=i) for i in range(1, 10)]

        make_download_client(self.session)
        idx = make_indexer(self.session, "Rutracker")

        releases = [
            _release("g1", "Arcane (Сезоны 1-2) WEB-DLRip 1080p", seeders=50),
            _release("g2", "Arcane.S01.2021.2160p.BDRemux-Rutracker", seeders=60),
            _release("g3", "Arcane.S02.2024.2160p.WEB-DL.DDP5.1.Atmos", seeders=70),
            _release("g4", "Arcane BDRemux", seeders=40),
        ]

        fake_dc = FakeDownloadClient()
        with patch("app.services.indexer_service.TorznabIndexerClient.search", lambda self_c, query, categories=None: _async_return(releases)), \
             patch("app.services.auto_search.get_client", lambda row: fake_dc):
            res = asyncio.run(auto_search._do_search_and_grab(self.session, show))

        grabbed = res.get("grabbed", [])
        self.assertEqual(len(grabbed), 18, "Должно быть закрыто 18 серий (9 серий S01 и 9 серий S02)")
        grabbed_releases = {g["release"] for g in grabbed}
        self.assertEqual(len(grabbed_releases), 2, "Должно быть использовано ровно 2 релиза: по одному на S01 и S02")
        self.assertIn("Arcane.S01.2021.2160p.BDRemux-Rutracker", grabbed_releases)
        self.assertIn("Arcane.S02.2024.2160p.WEB-DL.DDP5.1.Atmos", grabbed_releases)
        self.assertNotIn("Arcane (Сезоны 1-2) WEB-DLRip 1080p", grabbed_releases)

    def test_unmonitored_downloaded_episode_preserves_status_and_skips_upgrades(self):
        """Проверяет, что снятие мониторинга со скачанной серии сохраняет статус DOWNLOADED и исключает её из апгрейдов."""
        if not HAS_DEPS:
            self.skipTest("sqlalchemy is missing")
        from app.models.db import QualityProfile
        from app.api.operations import set_episode_status
        from app.api.shows import set_all_seasons_monitored

        qp = QualityProfile(
            name="UpgradeProfile",
            allowed_qualities=["Remux-1080p", "WEBDL-1080p", "SDTV"],
            upgrade_allowed=True,
        )
        self.session.add(qp)
        self.session.commit()

        show = make_show(self.session, "Test Upgrade Show")
        self.session.add(Alias(show_id=show.id, text="Test Upgrade Show"))
        show.quality_profile_id = qp.id
        self.session.add(show)
        self.session.commit()

        ep1 = make_episode(self.session, show, season=1, episode=1, status=EpisodeStatus.DOWNLOADED)
        ep1.downloaded_quality = "SDTV"
        ep1.monitored = True
        self.session.add(ep1)
        self.session.commit()

        # 1. Снимаем мониторинг вручную через API endpoint: статус должен остаться DOWNLOADED
        res = set_episode_status(ep1.id, monitored=False, db=self.session)
        self.session.refresh(ep1)
        self.assertEqual(ep1.status, EpisodeStatus.DOWNLOADED, "Статус скачанной серии должен оставаться DOWNLOADED")
        self.assertFalse(ep1.monitored, "Флаг monitored должен стать False")

        # 2. Проверяем, что автопоиск апгрейдов игнорирует немониторящуюся скачанную серию
        make_indexer(self.session)
        make_download_client(self.session)
        upgrade_rel = _release("g-up", "Test.Upgrade.Show.S01E01.1080p.Remux", seeders=50)
        fake_dc = FakeDownloadClient()
        with patch("app.services.indexer_service.TorznabIndexerClient.search", lambda self_c, query, categories=None: _async_return([upgrade_rel])), \
             patch("app.services.auto_search.get_client", lambda row: fake_dc):
            search_res = asyncio.run(auto_search._do_search_and_grab(self.session, show))
            self.assertEqual(search_res.get("grabbed", []), [], "Немониторящаяся скачанная серия не должна апгрейдиться")

        # 3. Включаем мониторинг обратно
        res = set_episode_status(ep1.id, monitored=True, db=self.session)
        self.session.refresh(ep1)
        self.assertEqual(ep1.status, EpisodeStatus.DOWNLOADED)
        self.assertTrue(ep1.monitored)

        # 4. Проверяем, что теперь апгрейд находится и захватывается
        with patch("app.services.indexer_service.TorznabIndexerClient.search", lambda self_c, query, categories=None: _async_return([upgrade_rel])), \
             patch("app.services.auto_search.get_client", lambda row: fake_dc):
            search_res = asyncio.run(auto_search._do_search_and_grab(self.session, show))
            self.assertEqual(len(search_res.get("grabbed", [])), 1, "Мониторящаяся скачанная серия должна апгрейдиться")

        # 5. Проверяем, что "Игнорировать все сезоны" снимает мониторинг, но оставляет статус DOWNLOADED
        ep1.status = EpisodeStatus.DOWNLOADED
        self.session.add(ep1)
        self.session.commit()

        set_all_seasons_monitored(show.id, monitored=False, db=self.session)
        self.session.refresh(ep1)
        self.assertEqual(ep1.status, EpisodeStatus.DOWNLOADED)
        self.assertFalse(ep1.monitored)

    def test_evaluate_torrent_file_priority_specials_and_sound_folder(self):
        """Проверяет корректное разделение серий и спешлов, а также выбор папок Sound."""
        from app.services.auto_search import evaluate_torrent_file_priority

        class DummyEp:
            def __init__(self, s, e, abs_n=None):
                self.id = 100 + s * 20 + e
                self.season_number = s
                self.episode_number = e
                self.absolute_number = abs_n
                self.title = f"Episode {e}"

        # 1. Разыскиваются только спешлы (S00E01, S00E02)
        target_s0 = [DummyEp(0, 1), DummyEp(0, 2)]
        
        # Обычные серии 01.avi..12.avi НЕ должны помечаться как спешлы
        for ep_i in range(1, 13):
            prio = evaluate_torrent_file_priority(f"Anime - {ep_i:02d}.avi", ep_i, target_s0, content_type="anime")
            self.assertEqual(prio, 0, f"Серия {ep_i:02d}.avi не должна скачиваться, когда разыскиваются только спешлы")

        # Файл OVA.avi ДОЛЖЕН скачиваться
        prio_ova = evaluate_torrent_file_priority("Anime - OVA.avi", 13, target_s0, content_type="anime")
        self.assertEqual(prio_ova, 1, "Файл OVA.avi должен скачиваться для разыскиваемых спешлов")

        # 2. Разыскивается 1-й сезон (S01E01..S01E12)
        target_s1 = [DummyEp(1, i) for i in range(1, 13)]
        for ep_i in range(1, 13):
            prio = evaluate_torrent_file_priority(f"Anime - {ep_i:02d}.avi", ep_i, target_s1, content_type="anime")
            self.assertEqual(prio, 1, f"Серия {ep_i:02d}.avi должна скачиваться для 1-го сезона")

        # 3. Аудиофайлы в папке Sound [Scout86, YukiKata, Sayuri-chan]
        sound_file_1 = "Sound [Scout86, YukiKata, Sayuri-chan]/Anime - 01 [Scout86].mka"
        sound_file_2 = "Sound [Scout86, YukiKata, Sayuri-chan]/Anime - 02 [Scout86].mka"
        sound_ost = "Sound [Scout86, YukiKata, Sayuri-chan]/OST.flac"

        prio_sound1 = evaluate_torrent_file_priority(sound_file_1, 14, target_s1, content_type="anime")
        prio_sound2 = evaluate_torrent_file_priority(sound_file_2, 15, target_s1, content_type="anime")
        prio_ost = evaluate_torrent_file_priority(sound_ost, 16, target_s1, content_type="anime")

        self.assertEqual(prio_sound1, 1, "Аудиодорожка к 1-й серии должна скачиваться")
        self.assertEqual(prio_sound2, 1, "Аудиодорожка ко 2-й серии должна скачиваться")
        self.assertEqual(prio_ost, 1, "Общий аудиофайл/OST из папки Sound должен скачиваться")

class TestSeasonQueries(unittest.TestCase):
    def setUp(self):
        if not HAS_DEPS:
            self.skipTest("Requires sqlalchemy and models")
        self.engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        Base.metadata.create_all(bind=self.engine)
        Session = sessionmaker(bind=self.engine)
        self.session = Session()

    def tearDown(self):
        if hasattr(self, "session") and self.session:
            self.session.close()

    def test_season_queries_generation_and_core_title(self):
        import asyncio
        from unittest.mock import MagicMock
        from types import SimpleNamespace
        from app.services.auto_search import _generate_season_queries, _extract_core_title, _collect_candidates

        # 1. Проверка извлечения ядра
        core_en = _extract_core_title("Re: ZERO, Starting Life in Another World")
        self.assertEqual(core_en, "Re:ZERO")

        core_ru = _extract_core_title("Re:Zero — жизнь в альтернативном мире с нуля")
        self.assertEqual(core_ru, "Re:Zero")

        # 2. Проверка генерации сезонных запросов для 4-го сезона
        ru_terms = _generate_season_queries("Re:Zero", 4)
        self.assertIn("Re:Zero (ТВ-4)", ru_terms)
        self.assertIn("Re:Zero ТВ-4", ru_terms)
        self.assertIn("Re:Zero 4 сезон", ru_terms)
        self.assertIn("Re:Zero S04", ru_terms)
        self.assertIn("Re:Zero 1-4 сезон", ru_terms)
        self.assertIn("Re:Zero 4th Season", ru_terms)
        self.assertIn("Re:Zero S01-S04", ru_terms)

        en_terms = _generate_season_queries("Re: ZERO", 4)
        self.assertIn("Re: ZERO (ТВ-4)", en_terms)
        self.assertIn("Re: ZERO ТВ-4", en_terms)
        self.assertIn("Re: ZERO S04", en_terms)
        self.assertIn("Re: ZERO 4th Season", en_terms)
        self.assertIn("Re: ZERO S01-S04", en_terms)

        # 3. Проверка _collect_candidates со списком эпизодов 4-го сезона
        show = SimpleNamespace(
            id=77,
            title="Re: ZERO, Starting Life in Another World",
            year=2016,
            content_type="anime",
            path=None,
            quality_profile_id=1,
        )
        ep4 = SimpleNamespace(
            id=204,
            show_id=77,
            season_number=4,
            episode_number=1,
            absolute_number=None,
            title="Season 4 Premiere",
            status="wanted",
        )
        db_mock = MagicMock()
        db_mock.get.return_value = None
        db_mock.query.return_value.filter.return_value.all.return_value = []
        db_mock.query.return_value.filter_by.return_value.all.return_value = []

        cands = asyncio.run(_collect_candidates(db_mock, show, [], wanted_episodes=[ep4]))
        query_terms = getattr(cands, "query_terms", [])
        self.assertTrue(any("ТВ-4" in q or "(ТВ-4)" in q for q in query_terms), f"ТВ-4 missing from queries: {query_terms}")
        self.assertTrue(any("S04" in q for q in query_terms), f"S04 missing from queries: {query_terms}")

    def test_selective_download_tracks_matched_episodes_and_reconciles(self):
        """Проверка того, что evaluate_torrent_file_priority возвращает сматченные серии в out_matched_episodes."""
        from types import SimpleNamespace as Ep
        from app.services import auto_search
        ep1 = Ep(id=101, show_id=1, season_number=5, episode_number=1, absolute_number=81, title="Saving Private Gigli")
        ep2 = Ep(id=102, show_id=1, season_number=5, episode_number=2, absolute_number=82, title="Terms of Endaredevil")
        ep6 = Ep(id=106, show_id=1, season_number=5, episode_number=6, absolute_number=86, title="Major League of Extraordinary Gentlemen")
        ep10 = Ep(id=110, show_id=1, season_number=5, episode_number=10, absolute_number=90, title="Beastmaster & Commander")

        all_show_eps = [ep1, ep2, ep6, ep10]
        targets = [ep1, ep2, ep6, ep10]

        matched = []
        prio_f1 = auto_search.evaluate_torrent_file_priority(
            "Season 5/S05E02 Saving Private Gigli.avi", 1, targets, all_show_episodes=all_show_eps, out_matched_episodes=matched
        )
        self.assertEqual(prio_f1, 1)
        self.assertEqual(len(matched), 1)
        self.assertEqual(matched[0].id, 101)  # Сматчилась серия 1 (Saving Private Gigli)!

        prio_f6 = auto_search.evaluate_torrent_file_priority(
            "Season 5/S05E07 Major League Of Extraordinary Gentlemen.avi", 6, targets, all_show_episodes=all_show_eps, out_matched_episodes=matched
        )
        self.assertEqual(prio_f6, 1)
        self.assertEqual(len(matched), 2)
        self.assertEqual(matched[1].id, 106)  # Сматчилась серия 6!

        prio_special = auto_search.evaluate_torrent_file_priority(
            "Season 5/S05E01 DP Christmas Special.avi", 0, targets, all_show_episodes=all_show_eps, out_matched_episodes=matched
        )
        self.assertEqual(prio_special, 0)
        self.assertEqual(len(matched), 2)  # Спешл не добавлен!

        matched_ids = {e.id for e in matched}
        uncovered = [e for e in targets if e.id not in matched_ids]
        # Серии 2 и 10 не были покрыты этими файлами
        self.assertIn(ep10, uncovered)
        self.assertIn(ep2, uncovered)

    def test_season_queries_include_season_x(self):
        """Проверка генерации сезонных запросов (Season X, Сезон X) для сериалов."""
        from app.services.auto_search import _generate_season_queries
        queries = _generate_season_queries("Robot Chicken", 5, is_anime=False)
        self.assertIn("Robot Chicken Season 5", queries)
        self.assertIn("Robot Chicken Сезон 5", queries)
        self.assertIn("Robot Chicken S05", queries)
        self.assertIn("Robot Chicken S5", queries)

    def test_roman_numeral_title_matching(self):
        """Проверка сопоставления названий с римскими цифрами (Casablankman 2 -> Casablankman II)."""
        from types import SimpleNamespace
        from app.services.auto_search import evaluate_torrent_file_priority

        ep11 = SimpleNamespace(id=111, season_number=5, episode_number=11, title="Casablankman", absolute_number=None)
        ep18 = SimpleNamespace(id=118, season_number=5, episode_number=18, title="Casablankman II", absolute_number=None)
        all_eps = [ep11, ep18]
        targets = [ep11, ep18]

        matched_eps_12 = []
        prio_12 = evaluate_torrent_file_priority(
            "Season 5/12 Casablankman.mkv", 0, targets, all_show_episodes=all_eps, out_matched_episodes=matched_eps_12
        )
        self.assertEqual(prio_12, 1)
        self.assertEqual(len(matched_eps_12), 1)
        self.assertEqual(matched_eps_12[0].id, ep11.id)

        matched_eps_19 = []
        prio_19 = evaluate_torrent_file_priority(
            "Season 5/19 Casablankman 2.mkv", 1, targets, all_show_episodes=all_eps, out_matched_episodes=matched_eps_19
        )
        self.assertEqual(prio_19, 1)
        self.assertEqual(len(matched_eps_19), 1)
        self.assertEqual(matched_eps_19[0].id, ep18.id)  # Должна сопоставиться именно Casablankman II!

    def test_evaluate_torrent_file_priority_cross_season_isolation(self):
        """Проверяет, что серия с титульным названием из 1-го сезона (S01E13 'Daredevil') не перехватывает файлы 3-го сезона."""
        from types import SimpleNamespace
        from app.services.auto_search import evaluate_torrent_file_priority

        s1e13 = SimpleNamespace(id=13, show_id=1, season_number=1, episode_number=13, title="Daredevil", absolute_number=None)
        s3e01 = SimpleNamespace(id=31, show_id=1, season_number=3, episode_number=1, title="Resurrection", absolute_number=None)
        s3e02 = SimpleNamespace(id=32, show_id=1, season_number=3, episode_number=2, title="Please", absolute_number=None)
        all_eps = [s1e13, s3e01, s3e02]
        target_s3 = [s3e01, s3e02]

        matched = []
        prio = evaluate_torrent_file_priority(
            "Daredevil.S03E01.WEB-DL.1080p.mkv", 0, target_s3,
            torrent_name="Daredevil.S03.WEB-DL.1080p",
            all_show_episodes=all_eps,
            out_matched_episodes=matched,
            show_words={"daredevil", "сорвиголова"},
        )
        self.assertEqual(prio, 1)
        self.assertEqual(len(matched), 1)
        self.assertEqual(matched[0].id, s3e01.id)
        self.assertEqual(matched[0].season_number, 3)
        self.assertEqual(matched[0].episode_number, 1)

    @unittest.skipUnless(HAS_DEPS, "Requires sqlalchemy and models")
    def test_disjoint_episodes_cancels_even_without_part1_keyword(self):
        """Проверяет, что если раздача содержит только серии 1-5, а запрошены были серии 6-7,
        раздача отменяется и удаляется даже без ключевого слова 'part 1' в названии (кейс Star Trek)."""
        show = make_show(self.session, "Star Trek SNW")
        ep6 = make_episode(self.session, show, season=4, episode=6, status=EpisodeStatus.DOWNLOADING)
        ep6.torrent_hash = "hash-fake-pack"
        ep7 = make_episode(self.session, show, season=4, episode=7, status=EpisodeStatus.DOWNLOADING)
        ep7.torrent_hash = "hash-fake-pack"
        self.session.commit()

        class MockTorrentClient:
            def __init__(self):
                self.removed = []
            async def get_torrent(self, torrent_hash):
                from app.services.download_client import TorrentInfo, TorrentFile
                files = [
                    TorrentFile(index=0, name="Star.Trek.S04E01.720p.mkv", size=1000, progress=0.0, priority=1),
                    TorrentFile(index=1, name="Star.Trek.S04E02.720p.mkv", size=1000, progress=0.0, priority=1),
                ]
                return TorrentInfo(
                    hash=torrent_hash,
                    name="Star.Trek.Strange.New.Worlds.S04E01-10.720p.WEB-DL",
                    progress=0.0,
                    state="downloading",
                    save_path="",
                    size=2000,
                    files=files,
                )
            async def remove_torrent(self, torrent_hash, delete_files=False):
                self.removed.append(torrent_hash)

        mock_client = MockTorrentClient()
        asyncio.run(auto_search._limit_torrent_files_to_episodes(
            mock_client,
            "hash-fake-pack",
            [ep6, ep7],
            db=self.session,
            content_type="series",
        ))

        self.assertIn("hash-fake-pack", mock_client.removed)
        self.session.refresh(ep6)
        self.session.refresh(ep7)
        self.assertEqual(ep6.status, EpisodeStatus.WANTED)
        self.assertEqual(ep7.status, EpisodeStatus.WANTED)
        self.assertIsNone(ep6.torrent_hash)
        self.assertIsNone(ep7.torrent_hash)



