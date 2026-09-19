"""Массовый импорт тайтлов из существующих папок (Library Import).

Проверяется то, от чего зависит корректность подбора: разбор имени папки,
ранжирование кандидатов и отбор подпапок при сканировании корня.
"""

from __future__ import annotations

import asyncio
import os
import re
import tempfile
import unittest
from pathlib import Path

try:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.api import library_import_routes as lir
    from app.models.db import AppSettings, Base, Show, User
    from app.services.library_import import (
        ParsedFolder,
        folder_has_media,
        is_ignored_folder,
        parse_folder_name,
        rank_candidates,
        score_candidate,
    )
    HAS_DEPS = True
except ImportError:  # pragma: no cover - окружение без зависимостей
    HAS_DEPS = False


ROOT = Path(__file__).resolve().parents[1]


class _Candidate:
    """Минимальный двойник MetadataSearchResultOut."""

    def __init__(self, external_id, title, year=None, content_type="series",
                 original_title=None, titles_by_lang=None, already_added=False):
        self.external_id = external_id
        self.title = title
        self.year = year
        self.content_type = content_type
        self.original_title = original_title
        self.titles_by_lang = titles_by_lang or {}
        self.overview = None
        self.poster_url = None
        self.rating = None
        self.country = None
        self.genre = None
        self.already_added = already_added
        self.existing_show_id = None


@unittest.skipUnless(HAS_DEPS, "FastAPI / SQLAlchemy dependencies not installed in host runner")
class TestParseFolderName(unittest.TestCase):
    def test_strips_release_junk_and_keeps_title(self):
        parsed = parse_folder_name("The.Office.US.2005.S01-S09.1080p.WEB-DL")
        self.assertEqual(parsed.title, "The Office US")
        self.assertEqual(parsed.year, 2005)

    def test_bracketed_year_wins_over_trailing_group(self):
        parsed = parse_folder_name("Игра престолов [2011] S01-S08 1080p")
        self.assertEqual(parsed.title, "Игра престолов")
        self.assertEqual(parsed.year, 2011)

    def test_leading_year_is_part_of_the_title(self):
        parsed = parse_folder_name("2012 (2009)")
        self.assertEqual(parsed.title, "2012")
        self.assertEqual(parsed.year, 2009)

        parsed = parse_folder_name("1917 (2019)")
        self.assertEqual(parsed.title, "1917")
        self.assertEqual(parsed.year, 2019)

    def test_second_language_in_brackets_becomes_alternative_title(self):
        parsed = parse_folder_name("Дюна (Dune) (2021)")
        self.assertEqual(parsed.title, "Дюна")
        self.assertEqual(parsed.alternative_titles, ["Dune"])
        self.assertEqual(parsed.search_terms, ["Дюна", "Dune"])

    def test_release_group_in_brackets_is_dropped(self):
        parsed = parse_folder_name("Some Show (LostFilm) 2019")
        self.assertEqual(parsed.title, "Some Show")
        self.assertEqual(parsed.alternative_titles, [])

    def test_pipe_separated_dual_title(self):
        parsed = parse_folder_name("Мандалорец | The Mandalorian")
        self.assertEqual(parsed.title, "Мандалорец")
        self.assertEqual(parsed.alternative_titles, ["The Mandalorian"])

    def test_full_path_is_reduced_to_its_last_segment(self):
        parsed = parse_folder_name("/media/series/Breaking Bad (2008)")
        self.assertEqual(parsed.title, "Breaking Bad")
        self.assertEqual(parsed.year, 2008)

    def test_plain_name_survives_untouched(self):
        parsed = parse_folder_name("Breaking Bad")
        self.assertEqual(parsed.title, "Breaking Bad")
        self.assertIsNone(parsed.year)

    def test_empty_name_is_safe(self):
        parsed = parse_folder_name("")
        self.assertEqual(parsed.title, "")
        self.assertEqual(parsed.search_terms, [])


@unittest.skipUnless(HAS_DEPS, "FastAPI / SQLAlchemy dependencies not installed in host runner")
class TestCandidateRanking(unittest.TestCase):
    def test_exact_title_and_year_outranks_a_namesake(self):
        parsed = parse_folder_name("The Office (2005)")
        ranked = rank_candidates(
            parsed,
            [
                _Candidate("tvdb:2", "The Office", 2001),
                _Candidate("tvdb:1", "The Office", 2005),
            ],
            "series",
        )
        self.assertEqual(ranked[0][0].external_id, "tvdb:1")

    def test_matching_year_scores_above_a_mismatch(self):
        parsed = parse_folder_name("Dune (2021)")
        right = score_candidate(parsed, _Candidate("movie:1", "Dune", 2021, "movie"), "movie")
        wrong = score_candidate(parsed, _Candidate("movie:2", "Dune", 1984, "movie"), "movie")
        self.assertGreater(right, wrong)

    def test_wrong_content_type_is_penalised(self):
        parsed = parse_folder_name("Fargo (2014)")
        series = score_candidate(parsed, _Candidate("tvdb:1", "Fargo", 2014, "series"), "series")
        movie = score_candidate(parsed, _Candidate("movie:1", "Fargo", 1996, "movie"), "series")
        self.assertGreater(series, movie)

    def test_alternative_language_title_is_matched(self):
        parsed = parse_folder_name("Дюна (Dune) (2021)")
        score = score_candidate(parsed, _Candidate("movie:1", "Dune", 2021, "movie"), "movie")
        self.assertGreaterEqual(score, lir.AUTO_SELECT_THRESHOLD)

    def test_localized_title_from_titles_by_lang_is_matched(self):
        parsed = parse_folder_name("Во все тяжкие (2008)")
        candidate = _Candidate("tvdb:1", "Breaking Bad", 2008, "series",
                               titles_by_lang={"ru": "Во все тяжкие", "en": "Breaking Bad"})
        self.assertGreaterEqual(score_candidate(parsed, candidate, "series"), lir.AUTO_SELECT_THRESHOLD)

    def test_unrelated_title_stays_below_the_auto_select_threshold(self):
        parsed = parse_folder_name("Breaking Bad (2008)")
        score = score_candidate(parsed, _Candidate("tvdb:9", "Better Call Saul", 2015, "series"), "series")
        self.assertLess(score, lir.AUTO_SELECT_THRESHOLD)

    def test_empty_folder_title_scores_zero(self):
        self.assertEqual(score_candidate(ParsedFolder(name="", title=""), _Candidate("x", "Anything")), 0.0)


@unittest.skipUnless(HAS_DEPS, "FastAPI / SQLAlchemy dependencies not installed in host runner")
class TestFolderHelpers(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = os.path.realpath(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_service_folders_are_ignored(self):
        for name in ("extras", "Subs", ".actors", "@eaDir", "sample", ""):
            self.assertTrue(is_ignored_folder(name), name)
        self.assertFalse(is_ignored_folder("Breaking Bad"))

    def test_media_detection_walks_into_season_folders(self):
        show = os.path.join(self.root, "Show", "Season 01")
        os.makedirs(show)
        self.assertFalse(folder_has_media(os.path.join(self.root, "Show")))
        with open(os.path.join(show, "s01e01.mkv"), "w", encoding="utf-8") as fh:
            fh.write("video")
        self.assertTrue(folder_has_media(os.path.join(self.root, "Show")))


@unittest.skipUnless(HAS_DEPS, "FastAPI / SQLAlchemy dependencies not installed in host runner")
class TestScanEndpoint(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()

        self.tmp = tempfile.TemporaryDirectory()
        self.root = os.path.realpath(self.tmp.name)
        for name in ("Breaking Bad (2008)", "The Office 2005", "extras", ".hidden", "Already Added"):
            os.makedirs(os.path.join(self.root, name))
        with open(os.path.join(self.root, "loose-file.mkv"), "w", encoding="utf-8") as fh:
            fh.write("video")

        self.db.add(AppSettings(id=1, api_key="test-key", root_folder=self.root, root_folder_series=self.root))
        self.user = User(username="admin", password_hash="hash", is_admin=True, is_owner=True)
        self.db.add(self.user)
        self.db.add(Show(title="Already Added", content_type="series",
                         path=os.path.join(self.root, "Already Added")))
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        self.tmp.cleanup()

    def _scan(self, **kwargs):
        return lir.scan_root_folder(path=self.root, db=self.db, current_user=self.user, **kwargs)

    def test_scan_lists_candidates_and_skips_noise(self):
        out = self._scan()
        names = [f.name for f in out.folders]
        self.assertIn("Breaking Bad (2008)", names)
        self.assertIn("The Office 2005", names)
        # Служебные, скрытые папки и обычные файлы кандидатами не являются.
        self.assertNotIn("extras", names)
        self.assertNotIn(".hidden", names)
        self.assertNotIn("loose-file.mkv", names)
        # Папка, уже привязанная к тайтлу, по умолчанию не предлагается повторно.
        self.assertNotIn("Already Added", names)
        self.assertEqual(out.skipped_existing, 1)

    def test_scan_parses_title_and_year_for_every_row(self):
        row = next(f for f in self._scan().folders if f.name == "Breaking Bad (2008)")
        self.assertEqual(row.parsed_title, "Breaking Bad")
        self.assertEqual(row.parsed_year, 2008)
        self.assertFalse(row.has_media)

    def test_include_added_flags_existing_rows_instead_of_hiding_them(self):
        out = self._scan(include_added=True)
        row = next(f for f in out.folders if f.name == "Already Added")
        self.assertTrue(row.already_added)
        self.assertEqual(row.existing_show_title, "Already Added")

    def test_require_media_drops_folders_without_video(self):
        self.assertEqual(self._scan(require_media=True).folders, [])

    def test_missing_root_is_reported(self):
        from fastapi import HTTPException

        with self.assertRaises(HTTPException) as ctx:
            lir.scan_root_folder(path=os.path.join(self.root, "nope"), db=self.db, current_user=self.user)
        self.assertEqual(ctx.exception.status_code, 404)


@unittest.skipUnless(HAS_DEPS, "FastAPI / SQLAlchemy dependencies not installed in host runner")
class TestLookupEndpoint(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.db.add(AppSettings(id=1, api_key="test-key"))
        self.user = User(username="admin", password_hash="hash", is_admin=True, is_owner=True)
        self.db.add(self.user)
        self.db.commit()

        self.queries: list[str] = []
        self._original_search = lir._search_metadata

    def tearDown(self):
        lir._search_metadata = self._original_search
        self.db.close()
        self.engine.dispose()

    def _patch_search(self, by_query):
        async def fake_search(query, db, current_user):
            self.queries.append(query)
            return by_query.get(query, [])

        lir._search_metadata = fake_search

    def _lookup(self, folder, **kwargs):
        return asyncio.run(lir.lookup_folder(folder=folder, db=self.db, current_user=self.user, **kwargs))

    def test_best_match_is_auto_selected_and_listed_first(self):
        self._patch_search({
            "Breaking Bad": [
                _Candidate("tvdb:9", "Better Call Saul", 2015),
                _Candidate("tvdb:1", "Breaking Bad", 2008),
            ]
        })
        out = self._lookup("Breaking Bad (2008)")
        self.assertEqual(out.query, "Breaking Bad")
        self.assertEqual(out.candidates[0].external_id, "tvdb:1")
        self.assertEqual(out.auto_selected_id, "tvdb:1")
        self.assertGreater(out.candidates[0].match_score, out.candidates[1].match_score)

    def test_weak_match_is_offered_but_not_auto_selected(self):
        self._patch_search({"Unknown Thing": [_Candidate("tvdb:5", "Something Else Entirely", 1999)]})
        out = self._lookup("Unknown Thing")
        self.assertIsNone(out.auto_selected_id)
        self.assertEqual(len(out.candidates), 1)

    def test_alternative_title_is_searched_when_the_first_one_fails(self):
        self._patch_search({
            "Дюна": [],
            "Dune": [_Candidate("movie:1", "Dune", 2021, "movie")],
        })
        out = self._lookup("Дюна (Dune) (2021)", content_type="movie")
        self.assertEqual(self.queries, ["Дюна", "Dune"])
        self.assertEqual(out.auto_selected_id, "movie:1")

    def test_manual_query_overrides_the_folder_name(self):
        self._patch_search({"Fargo": [_Candidate("tvdb:3", "Fargo", 2014)]})
        out = self._lookup("badly named folder", query="Fargo")
        self.assertEqual(self.queries, ["Fargo"])
        self.assertEqual(out.auto_selected_id, "tvdb:3")

    def test_already_added_candidate_is_never_auto_selected(self):
        self._patch_search({"Breaking Bad": [_Candidate("tvdb:1", "Breaking Bad", 2008, already_added=True)]})
        out = self._lookup("Breaking Bad (2008)")
        self.assertIsNone(out.auto_selected_id)
        self.assertTrue(out.candidates[0].already_added)

    def test_second_folder_of_an_added_title_is_reported_separately(self):
        """Вторая папка того же тайтла — не «совпадение не найдено»:
        совпадение как раз уверенное, просто тайтл уже заведён под другим путём."""
        added = _Candidate("tvdb:1", "Breaking Bad", 2008, already_added=True)
        added.existing_show_id = 42
        self._patch_search({"Breaking Bad": [added]})
        out = self._lookup("Breaking Bad (2008)")
        self.assertIsNone(out.auto_selected_id)
        self.assertEqual(out.existing_match_id, "tvdb:1")
        self.assertEqual(out.existing_show_id, 42)
        self.assertEqual(out.existing_title, "Breaking Bad")

    def test_a_free_candidate_wins_over_an_added_namesake(self):
        """Если рядом с уже добавленным тайтлом есть столь же уверенный свободный,
        импортировать надо его, а не блокировать строку."""
        added = _Candidate("tvdb:1", "Fargo", 2014, already_added=True)
        free = _Candidate("tvdb:2", "Fargo", 2014)
        self._patch_search({"Fargo": [added, free]})
        out = self._lookup("Fargo (2014)")
        self.assertEqual(out.auto_selected_id, "tvdb:2")

    def test_weak_added_candidate_does_not_block_the_row(self):
        self._patch_search({"Unknown Thing": [_Candidate("tvdb:5", "Something Else", 1999, already_added=True)]})
        out = self._lookup("Unknown Thing")
        self.assertIsNone(out.auto_selected_id)
        self.assertIsNone(out.existing_match_id)


class TestLibraryImportFrontend(unittest.TestCase):
    """Статические проверки разметки и скрипта окна импорта."""

    @classmethod
    def setUpClass(cls):
        cls.html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        cls.app_js = (ROOT / "web" / "js" / "app.js").read_text(encoding="utf-8")
        cls.style_css = (ROOT / "web" / "css" / "style.css").read_text(encoding="utf-8")

    def test_library_page_opens_the_import_window(self):
        self.assertIn('id="btn-library-import"', self.html)
        self.assertIn("openLibraryImportModal()", self.html)
        self.assertIn('id="library-import-modal"', self.html)

    def test_import_window_precedes_the_folder_picker_so_it_stacks_on_top(self):
        # Оба окна лежат на одном z-index, поэтому поверх оказывается то,
        # что объявлено в разметке ниже: обзор папок обязан идти последним.
        self.assertLess(
            self.html.index('id="library-import-modal"'),
            self.html.index('id="folder-picker-modal"'),
        )

    def test_scan_bar_offers_category_root_folder_and_browse(self):
        self.assertIn('id="lib-import-category-chips"', self.html)
        self.assertIn('id="lib-import-root-input"', self.html)
        self.assertIn("openFolderPicker('lib-import-root-input')", self.html)
        self.assertIn('id="lib-import-scan-btn"', self.html)

    def test_every_function_called_from_the_import_markup_exists(self):
        block = self.html.split('id="library-import-modal"', 1)[1]
        block = block.split("<!-- Смена папки тайтла -->", 1)[0]
        self.assertLess(len(block), 6000, "разметка окна импорта выделена неверно")
        called = set(re.findall(r'on(?:click|change|keydown)="([^"]+)"', block))
        names = {n for body in called for n in re.findall(r"([A-Za-z_$][A-Za-z0-9_$]*)\s*\(", body)}
        names -= {"getElementById", "preventDefault", "if", "for", "while", "return", "typeof"}
        self.assertIn("openLibraryImportModal", names | {"openLibraryImportModal"})
        for name in names:
            self.assertRegex(
                self.app_js,
                rf"(?m)^\s*(?:async\s+)?function\s+{re.escape(name)}\s*\(",
                f"обработчик окна импорта вызывает необъявленную функцию {name}()",
            )

    def test_matching_runs_with_a_bounded_pool_and_debounced_input(self):
        self.assertIn("LIB_IMPORT_LOOKUP_CONCURRENCY", self.app_js)
        self.assertIn("LIB_IMPORT_QUERY_DEBOUNCE_MS", self.app_js)
        self.assertIn("function runLibraryImportLookups()", self.app_js)

    def test_stale_lookup_responses_cannot_overwrite_a_newer_one(self):
        body = self.app_js.split("async function lookupLibraryImportRow(", 1)[1]
        body = body.split("\nfunction toggleLibraryImportRowPanel", 1)[0]
        self.assertIn("LIB_IMPORT_LOOKUP_SEQ", body)
        self.assertIn("row.lookupSeq !== seq", body)

    def test_duplicate_selection_blocks_the_row_from_import(self):
        self.assertIn("function recalcLibraryImportDuplicates()", self.app_js)
        selectable = self.app_js.split("function libImportSelectableRows()", 1)[1].split("}", 1)[0]
        self.assertIn("!r.duplicate", selectable)

    def test_duplicate_notice_names_the_conflicting_folder(self):
        """Подсказка «тайтл уже выбран» бесполезна без имени второй папки."""
        notice = self.app_js.split("function renderLibraryImportPanelNoticeHtml(", 1)[1]
        notice = notice.split("\nfunction renderLibraryImportSearchPanelHtml", 1)[0]
        self.assertIn("row.duplicate", notice)
        self.assertIn("other.name", notice)
        self.assertIn("row.existingMatch", notice)

    def test_second_folder_of_an_added_title_gets_its_own_row_state(self):
        lookup = self.app_js.split("async function lookupLibraryImportRow(", 1)[1]
        lookup = lookup.split("\nfunction toggleLibraryImportRowPanel", 1)[0]
        self.assertIn("data.existing_match_id", lookup)
        self.assertIn('row.status = "exists"', lookup)
        # Такая строка не должна попадать в импорт: путь у тайтла один.
        self.assertIn("row.selectedCandidate = null", lookup)
        self.assertIn("lib-import-match-btn is-exists", self.app_js)
        self.assertIn(".lib-import-row.is-exists", self.style_css)

    def test_import_posts_to_the_backend_and_requests_a_disk_sync(self):
        run = self.app_js.split("async function startLibraryImport(", 1)[1]
        self.assertIn('"/api/v1/library-import/item"', run)
        self.assertIn("sync_disk: true", run)

    def test_translations_exist_for_both_languages(self):
        for key in ("lib_import.btn", "lib_import.title", "lib_import.no_match", "lib_import.duplicate",
                    "lib_import.already_in_library", "lib_import.second_folder_hint"):
            self.assertEqual(
                len(re.findall(rf'"{re.escape(key)}":', self.app_js)), 2,
                f"ключ {key} должен быть объявлен и в ru, и в en",
            )

    def test_styles_cover_the_import_table(self):
        for selector in (".lib-import-row", ".lib-import-match-btn", ".lib-import-option", ".modal-xl"):
            self.assertIn(selector, self.style_css)


if __name__ == "__main__":
    unittest.main()
