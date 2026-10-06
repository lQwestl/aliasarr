from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STYLE_PATH = ROOT / "web" / "css" / "style.css"
APP_JS_PATH = ROOT / "web" / "js" / "app.js"
INDEX_PATH = ROOT / "web" / "index.html"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class TestFrontendTopNavStudio(unittest.TestCase):
    def setUp(self):
        self.style = read(STYLE_PATH)
        self.app_js = read(APP_JS_PATH)
        self.index_html = read(INDEX_PATH)

    def test_top_nav_design_studio_controls_present_in_html(self):
        self.assertIn('id="studio-top-nav-options"', self.index_html)
        self.assertIn('id="studio-top-nav-layout-toggle"', self.index_html)
        self.assertIn('data-value="compact-more"', self.index_html)
        self.assertIn('data-value="grouped"', self.index_html)
        self.assertIn('data-value="icons-pill"', self.index_html)
        self.assertIn('id="studio-top-nav-tasks-toggle"', self.index_html)
        self.assertIn('data-value="hud"', self.index_html)
        self.assertIn('data-value="fixed-bar"', self.index_html)
        self.assertIn('id="studio-tasks-view-toggle"', self.index_html)
        self.assertIn('id="tasks-drawer-overlay"', self.index_html)

    def test_top_nav_dropdown_elements_present_in_html(self):
        self.assertIn('id="nav-more-dropdown"', self.index_html)
        self.assertIn('id="nav-more-menu"', self.index_html)
        self.assertIn('id="nav-group-media"', self.index_html)
        self.assertIn('id="nav-group-monitoring"', self.index_html)
        self.assertIn('id="nav-group-tools"', self.index_html)
        self.assertIn('id="tasks-hud-pct"', self.index_html)

    def test_css_top_nav_modes_and_zero_scroll(self):
        self.assertIn('data-top-nav-layout="compact-more"', self.style)
        self.assertIn('data-top-nav-layout="grouped"', self.style)
        self.assertIn('data-top-nav-layout="icons-pill"', self.style)
        self.assertIn('.nav-more-dropdown', self.style)
        self.assertIn('.nav-more-menu', self.style)
        self.assertIn('.nav-more-menu.open', self.style)
        self.assertIn('.nav-group-menu.open', self.style)

    def test_css_tasks_zero_layout_shift(self):
        self.assertIn('data-top-nav-tasks="hud"', self.style)
        self.assertIn('88px !important', self.style)
        self.assertIn('data-top-nav-tasks="fixed-bar"', self.style)
        self.assertIn('220px !important', self.style)
        self.assertIn('.tasks-drawer-overlay', self.style)
        self.assertIn('data-tasks-view="drawer"', self.style)

    def test_js_top_nav_functions_and_state(self):
        self.assertIn('setStudioTopNavLayout', self.app_js)
        self.assertIn('setStudioTopNavTasksMode', self.app_js)
        self.assertIn('setStudioTasksViewMode', self.app_js)
        self.assertIn('toggleNavMoreMenu', self.app_js)
        self.assertIn('closeNavMoreMenu', self.app_js)
        self.assertIn('toggleNavGroupMenu', self.app_js)
        self.assertIn('closeAllTopNavMenus', self.app_js)
        self.assertIn('syncTopNavActiveState', self.app_js)
        self.assertTrue('tasks_hud_pct' in self.app_js or 'tasks-hud-pct' in self.app_js)


    def test_sidebar_footer_no_line_and_aligned(self):
        # Проверяем удаление полосы (border-top: none) и нулевые отступы футера
        self.assertIn('border-top: none !important', self.style)
        self.assertIn('padding-top: 0 !important', self.style)

    def test_wiki_icon_centered_in_icons_pill(self):
        # Проверяем центрирование и обнуление отступов иконки в режиме icons-pill
        self.assertIn('margin-right: 0 !important', self.style)
        # Проверяем компактную верстку nav-wiki без пробелов между тегами
        self.assertIn('<a href="/wiki" target="_blank" rel="noopener noreferrer" class="nav-item-wiki" id="nav-wiki" title="База знаний и документация" data-i18n-title="nav.wiki_tooltip" onclick="openWiki(event)"><i data-lucide="book-open"', self.index_html)


if __name__ == "__main__":
    unittest.main()

