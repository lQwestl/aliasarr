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


class TestDesignStudioLayout(unittest.TestCase):
    def test_container_uses_flexible_grid_tracks(self):
        style = read(STYLE_PATH)
        container = css_rule(style, ".design-studio-container")
        self.assertIn("minmax(0, 1fr)", container)
        self.assertIn("box-sizing: border-box", container)

    def test_controls_and_preview_wrappers_have_min_width_zero(self):
        style = read(STYLE_PATH)
        controls = css_rule(style, ".design-studio-controls")
        self.assertIn("min-width: 0", controls)
        preview_wrap = css_rule(style, ".design-studio-preview-wrap")
        self.assertIn("min-width: 0", preview_wrap)

    def test_preview_header_stacks_and_tabs_scroll_horizontally(self):
        style = read(STYLE_PATH)
        header = css_rule(style, ".studio-preview-header")
        self.assertIn("flex-direction: column", header)
        self.assertIn("min-width: 0", header)

        tabs = css_rule(style, ".studio-preview-mode-tabs")
        self.assertIn("overflow-x: auto", tabs)
        self.assertIn("scrollbar-width: none", tabs)

    def test_preview_card_uses_safe_glass_blur_fallback(self):
        style = read(STYLE_PATH)
        card = css_rule(style, ".studio-preview-card")
        self.assertIn("backdrop-filter: var(--glass-blur, none)", card)

    def test_preview_card_has_viewport_max_height_and_scrollable_canvas(self):
        style = read(STYLE_PATH)
        wrap = css_rule(style, ".design-studio-preview-wrap")
        self.assertIn("max-height: calc(100vh - 96px)", wrap)

        card = css_rule(style, ".studio-preview-card")
        self.assertIn("max-height: calc(100vh - 96px)", card)

        canvas = css_rule(style, ".studio-preview-canvas")
        self.assertIn("overflow-y: auto", canvas)

    def test_badge_and_shell_controls_have_wrapping_rules(self):
        style = read(STYLE_PATH)
        toggle_group = css_rule(style, ".studio-toggle-group")
        self.assertIn("display: grid", toggle_group)
        self.assertIn("grid-template-columns: repeat(auto-fit, minmax(65px, 1fr))", toggle_group)

        btn = css_rule(style, ".studio-toggle-btn")
        self.assertIn("overflow: hidden", btn)
        self.assertIn("text-overflow: ellipsis", btn)

        chip_desc = css_rule(style, ".studio-chip-desc")
        self.assertIn("word-break: break-word", chip_desc)

    def test_daylight_paper_does_not_have_hardcoded_dark_color(self):
        index = read(INDEX_PATH)
        # Verify daylight paper theme card does not have inline dark text colors
        daylight_match = re.search(r'data-theme-choice="paper".*?<\/div>\s*<\/div>', index, re.S)
        self.assertIsNotNone(daylight_match)
        daylight_html = daylight_match.group(0)
        self.assertNotIn("color:#111", daylight_html)
        self.assertNotIn("color:#555", daylight_html)

    def test_preview_reactivity_functions_call_render_studio_preview(self):
        app = read(APP_JS_PATH)
        for fn_name in ("setCardStyle", "setSearchLayoutStyle", "setSearchProgressStyle", "setCollectionsCardStyle"):
            with self.subTest(fn=fn_name):
                fn_code = js_function(app, fn_name)
                self.assertIn("renderStudioPreviewCanvas()", fn_code)

    def test_show_info_is_not_absolutely_positioned_over_poster(self):
        style = read(STYLE_PATH)
        # Ensure .show-info is not positioned absolutely over the poster artwork
        self.assertNotIn('html[data-design="studio"][data-card-style="cinematic"] .show-card .show-info', style)


if __name__ == "__main__":
    unittest.main()
