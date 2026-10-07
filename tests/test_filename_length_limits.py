import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock
from app.services.postprocess import (
    truncate_fs_name,
    sanitize_filename,
    pick_safe_title_candidate,
    get_show_default_path,
    ensure_safe_show_path,
)

Show = SimpleNamespace
Alias = SimpleNamespace


LONG_RU_TITLE = (
    "Изгнанный читер-чародей наслаждается беззаботной второй жизнью: "
    "Я могу накладывать «очки усиления» не только на оружие, но и на что угодно, "
    "в любой момент отменяя эффект по собственной воле, а с теми, кто остался, всё нормально?"
)


class TestFilenameLengthLimits(unittest.TestCase):
    def test_truncate_fs_name_ascii(self):
        short = "Simple Title"
        self.assertEqual(truncate_fs_name(short, 220), "Simple Title")

        long_en = "A " * 200
        res = truncate_fs_name(long_en, 200)
        self.assertLessEqual(len(res.encode("utf-8")), 200)

    def test_truncate_fs_name_cyrillic(self):
        # 412 bytes in UTF-8
        encoded_len = len(LONG_RU_TITLE.encode("utf-8"))
        self.assertGreater(encoded_len, 255)

        res = truncate_fs_name(LONG_RU_TITLE, max_bytes=220)
        res_bytes = len(res.encode("utf-8"))
        self.assertLessEqual(res_bytes, 220)
        # Check that decoding doesn't throw UnicodeDecodeError
        res.encode("utf-8").decode("utf-8")
        # Check that it ends cleanly, not cut in half
        self.assertFalse(res.endswith((".", "-", "«", " ")))

    def test_pick_safe_title_candidate_short_russian(self):
        tbl = {
            "ru": "Изгнанный читер-чародей",
            "en": "The Banished Court Magician",
            "original": "Chitsuki Madoushi",
        }
        res = pick_safe_title_candidate(LONG_RU_TITLE, titles_by_lang=tbl, max_bytes=220)
        self.assertEqual(res, "Изгнанный читер-чародей")
        self.assertLessEqual(len(res.encode("utf-8")), 220)

    def test_pick_safe_title_candidate_english_fallback(self):
        tbl = {
            "ru": LONG_RU_TITLE,  # Russian is too long
            "en": "The Banished Court Magician",
            "original": "Chitsuki Madoushi",
        }
        res = pick_safe_title_candidate(LONG_RU_TITLE, titles_by_lang=tbl, max_bytes=220)
        self.assertEqual(res, "The Banished Court Magician")
        self.assertLessEqual(len(res.encode("utf-8")), 220)

    def test_pick_safe_title_candidate_from_aliases(self):
        aliases = [
            "Super Long Alias That Exceeds The Limit " * 10,
            "The Banished Court Magician",
        ]
        res = pick_safe_title_candidate(LONG_RU_TITLE, aliases=aliases, max_bytes=220)
        self.assertEqual(res, "The Banished Court Magician")

    def test_get_show_default_path_safe_length(self):
        settings = MagicMock()
        settings.root_folder = "/data/serials"
        settings.root_folder_series = "/data/serials"
        settings.root_folder_anime = "/data/anime"
        settings.root_folder_movies = "/data/movies"

        show = Show(
            title=LONG_RU_TITLE,
            year=2024,
            content_type="anime",
        )
        show.aliases = [Alias(text="The Banished Court Magician", language="en")]

        path = get_show_default_path(show, settings)
        self.assertTrue(path.startswith("/data/anime/"))
        folder = path.split("/")[-1]
        self.assertLessEqual(len(folder.encode("utf-8")), 220)
        self.assertIn("The Banished Court Magician", folder)

    def test_ensure_safe_show_path_auto_healing(self):
        db = MagicMock()
        show = Show(
            id=180,
            title=LONG_RU_TITLE,
            year=2024,
            content_type="series",
            path=f"/data/serials/{LONG_RU_TITLE}",
        )
        show.aliases = [Alias(text="The Banished Court Magician", language="en")]

        safe_path = ensure_safe_show_path(db, show, "/data/serials")
        folder = safe_path.split("/")[-1]
        self.assertLessEqual(len(folder.encode("utf-8")), 220)
        self.assertEqual(show.path, safe_path)
        db.add.assert_called_with(show)
        db.commit.assert_called()

    def test_frontend_wizard_fs_warning_elements(self):
        with open("web/css/style.css", "r", encoding="utf-8") as f:
            style_css = f.read()
        self.assertIn(".wizard-fs-warning-banner", style_css)
        self.assertIn(".title-lang-fs-badge", style_css)

        with open("web/js/app.js", "r", encoding="utf-8") as f:
            app_js = f.read()
        self.assertIn("function getUtf8ByteLength", app_js)
        self.assertIn("function findSafeWizardFolderName", app_js)
        self.assertIn("function updateWizardFsWarningBanner", app_js)
        self.assertIn("wizard-fs-warning-banner", app_js)

    def test_backend_import_uses_safe_folder(self):
        with open("app/api/metadata_routes.py", "r", encoding="utf-8") as f:
            meta_py = f.read()
        self.assertIn("pick_safe_title_candidate", meta_py)
        self.assertIn("safe_folder_title = pick_safe_title_candidate", meta_py)


if __name__ == "__main__":
    unittest.main()
