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

    def test_settings_interface_panel_reorganized_to_regional(self):
        # Проверяем переименование панели в «Региональные параметры»
        self.assertIn('data-i18n="settings.regional_title"', self.index_html)
        self.assertIn('data-i18n="settings.regional_subtitle"', self.index_html)
        self.assertIn('id="setting-language"', self.index_html)
        self.assertIn('id="setting-timezone"', self.index_html)
        # Проверяем удаление дублирующих селекторов из карточки региональных настроек
        card_interface_chunk = self.index_html[self.index_html.find('id="card-interface"'):self.index_html.find('id="card-design"')]
        self.assertNotIn('id="setting-theme"', card_interface_chunk)
        self.assertNotIn('id="setting-glass"', card_interface_chunk)
        self.assertNotIn('id="setting-scrollbar"', card_interface_chunk)
        self.assertNotIn('switchTab(\'design-studio\')', card_interface_chunk)

    def test_design_cards_buttons_and_studio_footer(self):
        # В шапке блока «Дизайн интерфейса» больше нет отдельной кнопки перехода в студию
        card_design_chunk = self.index_html[self.index_html.find('id="card-design"'):self.index_html.find('id="card-media-folders"')]
        header_chunk = card_design_chunk[:card_design_chunk.find('class="design-cards-grid"')]
        self.assertNotIn('switchTab(\'design-studio\')', header_chunk)
        # В карточке STUDIO есть кнопка Студия дизайна рядом с «Выбрать стиль»
        self.assertIn('data-i18n="design_studio.open_studio">Студия дизайна</span>', card_design_chunk)
        # Кнопка в карточке Modern однотонная btn-secondary (без белого фона)
        modern_card_chunk = card_design_chunk[card_design_chunk.find('data-design-choice="modern"'):card_design_chunk.find('data-design-choice="servarr"')]
        self.assertIn('btn-secondary btn-small w-full', modern_card_chunk)
        self.assertNotIn('btn-primary', modern_card_chunk)

    def test_design_studio_gpu_blur_tip_present(self):
        # Предупреждение о нагрузке backdrop-filter на GPU под слайдером размытия
        self.assertIn('studio-gpu-tip', self.index_html)
        self.assertIn('design_studio.gpu_blur_tip', self.app_js)
        self.assertIn('backdrop-filter', self.index_html)

    def test_design_studio_base_tone_custom_palette(self):
        # Наличие hex-индикатора и нативного пикера для базового тона подложки
        self.assertIn('id="studio-base-tone-hex-label"', self.index_html)
        self.assertIn('id="studio-base-tone-color-input"', self.index_html)
        self.assertIn('onStudioCustomBaseToneInput', self.app_js)
        self.assertIn('computeCustomBaseTone', self.app_js)

    def test_design_studio_scrollbar_controls_and_colors(self):
        # Контролы полосы прокрутки: режим, палитра пресетов, свой цвет
        self.assertIn('id="studio-scrollbar-mode-toggle"', self.index_html)
        self.assertIn('id="studio-scrollbar-swatches"', self.index_html)
        self.assertIn('id="studio-scrollbar-color-input"', self.index_html)
        self.assertIn('id="studio-scrollbar-hex-label"', self.index_html)
        self.assertIn('STUDIO_SCROLLBAR_COLORS', self.app_js)
        self.assertIn('setStudioScrollbarMode', self.app_js)
        self.assertIn('setStudioScrollbarColor', self.app_js)
        self.assertIn('onStudioCustomScrollbarColorInput', self.app_js)
        self.assertIn('computeScrollbarThumbColors', self.app_js)


if __name__ == "__main__":
    unittest.main()

