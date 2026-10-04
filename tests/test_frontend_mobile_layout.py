from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STYLE_PATH = ROOT / "web" / "css" / "style.css"
SERVARR_STYLE_PATH = ROOT / "web" / "css" / "servarr.css"
APP_JS_PATH = ROOT / "web" / "js" / "app.js"
INDEX_PATH = ROOT / "web" / "index.html"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def css_rule(source: str, selector: str) -> str:
    match = re.search(rf"(?:^|\}}|\n)\s*{re.escape(selector)}\s*\{{(?P<body>[^}}]*)\}}", source)
    if match is None:
        raise AssertionError(f"CSS rule not found: {selector}")
    return match.group("body")


def js_function(source: str, name: str) -> str:
    match = re.search(rf"(?:async\s+)?function {re.escape(name)}\(.*?\n\}}\n", source, re.S)
    if match is None:
        raise AssertionError(f"JS function not found: {name}")
    return match.group(0)


class TestWizardPosterCards(unittest.TestCase):
    def test_card_ratio_does_not_rely_on_aspect_ratio(self):
        style = read(STYLE_PATH)
        card = css_rule(style, ".metadata-poster-card")
        self.assertNotIn("aspect-ratio", card)
        spacer = css_rule(style, ".metadata-poster-card::before")
        self.assertIn('content: ""', spacer)
        self.assertIn("padding-top: 150%", spacer)

    def test_card_caption_is_overlaid_instead_of_adding_height(self):
        bottom = css_rule(read(STYLE_PATH), ".metadata-poster-bottom")
        self.assertIn("position: absolute", bottom)
        self.assertIn("bottom: 0", bottom)

    def test_grid_rows_follow_card_height(self):
        grid = css_rule(read(STYLE_PATH), ".metadata-poster-grid")
        self.assertIn("grid-auto-rows: max-content", grid)
        self.assertIn("align-content: start", grid)


class TestMobileSidebar(unittest.TestCase):
    def test_closed_drawer_has_no_visible_shadow(self):
        style = read(STYLE_PATH)
        mobile = style[style.index("/* Mobile Slide-in Drawer */"):]
        closed = css_rule(mobile, ".sidebar")
        self.assertIn("box-shadow: none", closed)
        self.assertIn("visibility: hidden", closed)
        opened = css_rule(mobile, ".sidebar.mobile-open")
        self.assertIn("visibility: visible", opened)
        self.assertRegex(opened, r"box-shadow:\s*12px 0 32px")

    def test_servarr_closed_drawer_is_hidden(self):
        servarr = read(SERVARR_STYLE_PATH)
        servarr = servarr[servarr.index("overflow-x: clip !important;"):]
        closed = css_rule(servarr, '[data-design="servarr"] .sidebar')
        self.assertIn("visibility: hidden", closed)
        opened = css_rule(servarr, '[data-design="servarr"] .sidebar.mobile-open')
        self.assertIn("visibility: visible", opened)


class TestMobileLibrarySearch(unittest.TestCase):
    def test_desktop_flex_basis_is_reset_in_column_header(self):
        style = read(STYLE_PATH)
        mobile = style[style.index("@media (max-width: 768px)"):]
        rule = css_rule(mobile, ':root:not([data-design="servarr"]) .library-search-wrap[data-search-mode]')
        self.assertIn("flex: 0 0 auto !important", rule)
        self.assertIn("height: 42px !important", rule)


class TestAppearancePersistence(unittest.TestCase):
    def test_controls_save_choice_immediately(self):
        index = read(INDEX_PATH)
        self.assertIn('id="setting-theme" class="input" onchange="selectTheme(this.value)"', index)
        self.assertIn('id="setting-glass" class="input" onchange="selectGlassMode(this.value)"', index)

        app = read(APP_JS_PATH)
        expected = {
            "selectTheme": "theme",
            "selectDesignSystem": "design_system",
            "selectScrollbarMode": "scrollbar_mode",
            "selectGlassMode": "glass_mode",
        }
        for name, key in expected.items():
            with self.subTest(name=name):
                self.assertRegex(js_function(app, name), rf"persistAppearance\(\{{ {key}:")

    def test_unsaved_local_choice_wins_over_server_settings(self):
        app = read(APP_JS_PATH)
        persist = js_function(app, "persistAppearance")
        self.assertIn('api("/api/v1/settings", { method: "PUT"', persist)
        self.assertIn("writeLocalAppearance", persist)
        for name in ("startApp", "loadGeneralSettings"):
            with self.subTest(name=name):
                self.assertIn(
                    'mergeLocalAppearance(await api("/api/v1/settings"))',
                    js_function(app, name),
                )


if __name__ == "__main__":
    unittest.main()
