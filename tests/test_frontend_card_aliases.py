from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STYLE_PATH = ROOT / "web" / "css" / "style.css"
SERVARR_PATH = ROOT / "web" / "css" / "servarr.css"
APP_JS_PATH = ROOT / "web" / "js" / "app.js"
AUTO_SEARCH_PATH = ROOT / "app" / "services" / "auto_search.py"
HTML_PATH = ROOT / "web" / "index.html"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class TestFrontendCardAliasesAndSearchStatus(unittest.TestCase):
    def setUp(self):
        self.style = read(STYLE_PATH)
        self.servarr = read(SERVARR_PATH)
        self.app_js = read(APP_JS_PATH)
        self.auto_search = read(AUTO_SEARCH_PATH)
        self.index_html = read(HTML_PATH)

    def test_outer_card_aliases_do_not_switch_title(self):
        """Ensure renderShowCard does not attach onAliasCardChipClick or interactive class to alias chips."""
        match = re.search(r"function renderShowCard\b.*?(?=function\s+[a-zA-Z0-9_]+\s*\()", self.app_js, re.DOTALL)
        self.assertIsNotNone(match, "renderShowCard not found in app.js")
        card_code = match.group(0)

        self.assertNotIn("onAliasCardChipClick", card_code, "Outer card must NOT have onAliasCardChipClick")
        self.assertNotIn("canManageLib ? 'interactive' : ''", card_code)
        self.assertNotIn("Click to set as main title", card_code)
        self.assertNotIn("Нажмите, чтобы сделать основным названием", card_code)

    def test_modal_alias_make_primary_button_retained(self):
        """Ensure modal still has onAliasCardChipClick for the dedicated checkmark button."""
        self.assertIn("alias-chip-make-primary", self.app_js)
        self.assertIn("onAliasCardChipClick(event, ${show.id}, this)", self.app_js)

    def test_alias_chip_priority_nowrap_and_no_shrink(self):
        """Ensure .alias-chip-priority has nowrap and flex-shrink: 0 to prevent vertical breaks like # 5."""
        priority_css_match = re.search(r"\.alias-chip-priority\s*\{([^}]+)\}", self.style)
        self.assertIsNotNone(priority_css_match, ".alias-chip-priority not found in style.css")
        priority_css = priority_css_match.group(1)
        self.assertIn("white-space: nowrap", priority_css)
        self.assertIn("flex-shrink: 0", priority_css)

        servarr_match = re.search(r"\.alias-chip-priority\s*\{([^}]+)\}", self.servarr)
        self.assertIsNotNone(servarr_match, ".alias-chip-priority not found in servarr.css")
        servarr_css = servarr_match.group(1)
        self.assertIn("white-space: nowrap", servarr_css)
        self.assertIn("flex-shrink: 0", servarr_css)

    def test_search_status_micropill_and_vanguard_no_fixed_height(self):
        """Ensure search-style-micropill and search-style-vanguard do not have hardcoded height: 24px."""
        micropill_match = re.search(r"\.search-style-micropill\s*\{([^}]+)\}", self.style)
        self.assertIsNotNone(micropill_match, ".search-style-micropill not found in style.css")
        micropill_css = micropill_match.group(1)
        self.assertNotIn("height: 24px", micropill_css)
        self.assertIn("min-height: 26px", micropill_css)

        vanguard_match = re.search(r"\.search-style-vanguard\s*\{([^}]+)\}", self.style)
        self.assertIsNotNone(vanguard_match, ".search-style-vanguard not found in style.css")
        vanguard_css = vanguard_match.group(1)
        self.assertNotIn("height: 24px", vanguard_css)
        self.assertIn("min-height: 26px", vanguard_css)

    def test_format_search_status_display_helper_exists(self):
        """Ensure formatSearchStatusDisplay parses long criteria strings cleanly."""
        self.assertIn("function formatSearchStatusDisplay(rawText)", self.app_js)
        self.assertIn("search-status-criteria-tag", self.app_js)
        self.assertIn(".search-status-criteria-tag", self.style)

    def test_backend_criteria_length_guard(self):
        """Ensure backend auto_search guards criteria length to stay safely within String(500)."""
        self.assertIn("criteria_clean = str(criteria).strip()", self.auto_search)
        self.assertIn("rest_count = len(parts) - 2", self.auto_search)

    def test_modal_hero_backdrop_full_bleed_and_transparent(self):
        """Ensure modal has zero top padding, hero container is full width and backdrop filter is removed."""
        modal_match = re.search(r"(?::root:not\(\[data-design=\"servarr\"\]\)\s+)?#show-modal\s+\.modal,\s*\n(?::root:not\(\[data-design=\"servarr\"\]\)\s+)?#collection-modal\s+\.modal\s*\{([^}]+)\}", self.style)
        self.assertIsNotNone(modal_match, "Modal rule not found")
        modal_css = modal_match.group(1)
        self.assertIn("padding: 0 0 24px 0", modal_css)

        hero_match = re.search(r"\.show-hero-container\s*\{([^}]+)\}", self.style)
        self.assertIsNotNone(hero_match, ".show-hero-container rule not found")
        hero_css = hero_match.group(1)
        self.assertIn("background: transparent !important", hero_css)
        self.assertIn("border-bottom: 1px solid var(--border)", hero_css)

        backdrop_match = re.search(r"\.show-hero-backdrop\s*\{([^}]+)\}", self.style)
        self.assertIsNotNone(backdrop_match, ".show-hero-backdrop rule not found")
        backdrop_css = backdrop_match.group(1)
        self.assertIn("filter: none !important", backdrop_css)

    def test_modal_hero_poster_and_buttons_enlarged(self):
        """Ensure show hero poster is enlarged to 230x345px and action buttons have 32px height."""
        poster_match = re.search(r"\.show-hero-poster\s*\{([^}]+)\}", self.style)
        self.assertIsNotNone(poster_match, ".show-hero-poster rule not found")
        poster_css = poster_match.group(1)
        self.assertIn("width: 230px", poster_css)
        self.assertIn("height: 345px", poster_css)

        btn_match = re.search(r"\.show-hero-poster-actions\s+\.btn[^{]*\{([^}]+)\}", self.style)
        self.assertIsNotNone(btn_match, ".show-hero-poster-actions .btn rule not found")
        btn_css = btn_match.group(1)
        self.assertIn("height: 32px !important", btn_css)
        self.assertIn("font-size: 12px !important", btn_css)

    def test_modal_hero_aliases_block_unified_theme_outline(self):
        """Ensure .show-hero-aliases-block has unified border and uses var(--teal) instead of hardcoded green."""
        aliases_block_match = re.search(r"\.show-hero-aliases-block\s*\{([^}]+)\}", self.style)
        self.assertIsNotNone(aliases_block_match, ".show-hero-aliases-block rule not found")
        block_css = aliases_block_match.group(1)
        self.assertIn("border: 1px solid var(--border)", block_css)
        self.assertIn("border-radius:", block_css)

        expanded_match = re.search(r"\.show-hero-aliases-block\.is-expanded\s*\{([^}]+)\}", self.style)
        self.assertIsNotNone(expanded_match, ".show-hero-aliases-block.is-expanded rule not found")
        expanded_css = expanded_match.group(1)
        self.assertIn("border-color: var(--teal)", expanded_css)

        # Header and body must not have disjointed borders or hardcoded green
        header_hover_match = re.search(r"\.show-aliases-accordion-header:hover\s*\{([^}]+)\}", self.style)
        self.assertIsNotNone(header_hover_match, ".show-aliases-accordion-header:hover rule not found")
        header_hover_css = header_hover_match.group(1)
        self.assertNotIn("rgba(45, 212, 191", header_hover_css)
        self.assertIn("var(--teal)", header_hover_css)

        # Base alias-chip uses theme var(--teal) via color-mix
        alias_chip_match = re.search(r"(?:^|\n)\.alias-chip\s*\{([^}]+)\}", self.style)
        self.assertIsNotNone(alias_chip_match, ".alias-chip rule not found")
        chip_css = alias_chip_match.group(1)
        self.assertIn("color: var(--teal)", chip_css)
        self.assertIn("color-mix(in srgb, var(--teal)", chip_css)
        self.assertNotIn("rgba(0, 240, 255,", chip_css)


    def test_modal_close_hover_red(self):
        """Ensure modal close button hover has red styling and rotation in custom themes."""
        hover_match = re.search(r":root:not\(\[data-design=\"servarr\"\]\)\s+#show-modal\s+\.modal-close:hover[^{]*\{([^}]+)\}", self.style)
        self.assertIsNotNone(hover_match, ":root:not([data-design=\"servarr\"]) #show-modal .modal-close:hover rule not found")
        hover_css = hover_match.group(1)
        self.assertIn("rgba(239, 68, 68", hover_css)
        self.assertIn("color: #ff6b6b !important", hover_css)
        self.assertIn("transform: rotate(90deg)", hover_css)

    def test_modal_close_isolated_from_servarr(self):
        """Ensure #show-modal .modal-close rules in style.css are strictly isolated from Servarr via :root."""
        # Unscoped #show-modal .modal-close must NOT exist in style.css
        unscoped_rule = re.search(r"(?:^|\n)\s*#show-modal\s+\.modal-close\s*\{", self.style)
        self.assertIsNone(unscoped_rule, "Found unscoped #show-modal .modal-close rule in style.css that bleeds into Servarr")

        # Must have :root prefix, not bare :not([data-design="servarr"])
        bare_not_rule = re.search(r"(?:^|\n)\s*:not\(\[data-design=\"servarr\"\]\)\s+#show-modal\s+\.modal-close\b", self.style)
        self.assertIsNone(bare_not_rule, "Found bare :not([data-design=\"servarr\"]) without :root which matches body ancestor")

        scoped_rule = re.search(r":root:not\(\[data-design=\"servarr\"\]\)\s+#show-modal\s+\.modal-close\b", self.style)
        self.assertIsNotNone(scoped_rule, "Expected scoped :root:not([data-design=\"servarr\"]) #show-modal .modal-close in style.css")

    def test_servarr_modal_close_static_and_transparent(self):
        """Ensure Servarr design mode has 100% transparent, borderless, non-rotating close button."""
        close_match = re.search(r"\[data-design=\"servarr\"\]\s+\.modal-close,\s*\n\[data-design=\"servarr\"\]\s+\.modal\s+\.modal-close\s*\{([^}]+)\}", self.servarr)
        self.assertIsNotNone(close_match, "Servarr modal-close base rule not found")
        close_css = close_match.group(1)
        self.assertIn("border: 0", close_css)
        self.assertIn("background: transparent", close_css)
        self.assertIn("transform: none", close_css)

        hover_match = re.search(r"\[data-design=\"servarr\"\]\s+\.modal-close:hover,\s*\n\[data-design=\"servarr\"\]\s+\.modal\s+\.modal-close:hover\s*\{([^}]+)\}", self.servarr)
        self.assertIsNotNone(hover_match, "Servarr modal-close:hover rule not found")
        hover_css = hover_match.group(1)
        self.assertIn("border: 0", hover_css)
        self.assertIn("background: transparent", hover_css)
        self.assertIn("transform: none", hover_css)

    def test_css_braces_balanced(self):
        """Ensure style.css and servarr.css have completely balanced braces."""
        for css_file in [STYLE_PATH, SERVARR_PATH]:
            with open(css_file, "r", encoding="utf-8") as f:
                content = f.read()
            # Basic brace balance check
            open_cnt = content.count("{")
            close_cnt = content.count("}")
            self.assertEqual(open_cnt, close_cnt, f"Mismatched braces in {css_file}: {open_cnt} open vs {close_cnt} close")

    def test_show_hero_title_row_clearance(self):
        """Ensure .show-hero-title-row has padding-right to not overlap with navigation and close buttons."""
        title_row_match = re.search(r"\.show-hero-title-row\s*\{([^}]+)\}", self.style)
        self.assertIsNotNone(title_row_match, ".show-hero-title-row rule not found")
        title_row_css = title_row_match.group(1)
        self.assertIn("padding-right: 120px", title_row_css)

    def test_show_detail_path_actions_bar_compact(self):
        """Ensure .show-detail-path-actions-bar buttons are compact to fit on one row."""
        actions_btn_match = re.search(r"\.show-detail-path-actions-bar\s+\.btn\s*\{([^}]+)\}", self.style)
        self.assertIsNotNone(actions_btn_match, ".show-detail-path-actions-bar .btn rule not found")
        btn_css = actions_btn_match.group(1)
        self.assertIn("height: 28px !important", btn_css)
        self.assertIn("padding: 0 8px !important", btn_css)

    def test_modal_hero_overview_readability_and_contrast(self):
        """Ensure overview text has crisp contrast, text-shadow, and reinforced backdrop gradient."""
        overview_match = re.search(r"(?:^|\n)\.show-hero-overview\s*\{([^}]+)\}", self.style)
        self.assertIsNotNone(overview_match, ".show-hero-overview rule not found")
        overview_css = overview_match.group(1)
        self.assertIn("color: #f8fafc", overview_css)
        self.assertIn("text-shadow:", overview_css)
        self.assertIn("font-size: 13.5px", overview_css)

        gradient_match = re.search(r"(?:^|\n)\.show-hero-gradient\s*\{([^}]+)\}", self.style)
        self.assertIsNotNone(gradient_match, ".show-hero-gradient rule not found")
        grad_css = gradient_match.group(1)
        self.assertIn("0.88", grad_css)
        self.assertIn("0.60", grad_css)

    def test_wizard_stepper_theme_colors_and_no_duplicate_numbers(self):
        """Ensure wizard stepper adapts to theme accent colors and does not duplicate step numbers."""
        # 1. Check CSS stepper rules
        step_active_match = re.search(r"\.wizard-step-item\.active\s*\{([^}]+)\}", self.style)
        self.assertIsNotNone(step_active_match, ".wizard-step-item.active rule not found")
        active_css = step_active_match.group(1)
        self.assertNotIn("rgba(45, 212, 191", active_css, "Hardcoded teal must not be in .wizard-step-item.active")
        self.assertIn("var(--teal)", active_css)
        self.assertIn("color-mix", active_css)

        connector_active_match = re.search(r"\.wizard-stepper-connector\.active\s*\{([^}]+)\}", self.style)
        self.assertIsNotNone(connector_active_match, ".wizard-stepper-connector.active rule not found")
        connector_css = connector_active_match.group(1)
        self.assertNotIn("rgba(45, 212, 191", connector_css, "Hardcoded teal must not be in connector")
        self.assertIn("var(--teal)", connector_css)

        # 2. Check localization strings (no duplicate 1. or 2.)
        self.assertIn('"wizard.step_search": "Поиск"', self.app_js)
        self.assertIn('"wizard.step_setup": "Настройка"', self.app_js)
        self.assertNotIn('"wizard.step_search": "1. Поиск"', self.app_js)
        self.assertNotIn('"wizard.step_setup": "2. Настройка"', self.app_js)

        self.assertIn('"wizard.step_search": "Search"', self.app_js)
        self.assertIn('"wizard.step_setup": "Setup"', self.app_js)
        self.assertNotIn('"wizard.step_search": "1. Search"', self.app_js)
        self.assertNotIn('"wizard.step_setup": "2. Setup"', self.app_js)

        # 3. Check HTML template
        self.assertIn('data-i18n="wizard.step_search">Поиск</span>', self.index_html)
        self.assertIn('data-i18n="wizard.step_setup">Настройка</span>', self.index_html)
        self.assertNotIn('data-i18n="wizard.step_search">1. Поиск</span>', self.index_html)
        self.assertNotIn('data-i18n="wizard.step_setup">2. Настройка</span>', self.index_html)

    def test_modal_and_window_close_buttons_circular_animated_red_hover(self):
        """Ensure all modals and windows have circular close buttons with 90deg rotation and red hover."""
        # 1. Universal animated hover rule in style.css scoped with :root:not([data-design="servarr"])
        hover_pattern = r":root:not\(\[data-design=\"servarr\"\]\)\s+\.modal-close:hover[^{]*\{([^}]+)\}"
        hover_match = re.search(hover_pattern, self.style)
        self.assertIsNotNone(hover_match, "Universal modal-close hover rule not found")
        hover_css = hover_match.group(1)
        self.assertIn("transform: rotate(90deg)", hover_css)
        self.assertIn("#ff6b6b", hover_css)

        # 2. Base circular border-radius
        base_pattern = r":root:not\(\[data-design=\"servarr\"\]\)\s+\.modal-close[^{]*\{([^}]+)\}"
        base_match = re.search(base_pattern, self.style)
        self.assertIsNotNone(base_match, "Universal modal-close base rule not found")
        base_css = base_match.group(1)
        self.assertIn("border-radius: 50%", base_css)

        # 3. Specific modals use modal-close
        self.assertIn('<button class="modal-close" onclick="closeModal(\'delete-show-modal\')"', self.index_html)
        self.assertIn('<button class="modal-close" onclick="closeModal(\'ssl-redirect-modal\')"', self.index_html)
        self.assertIn('<button class="modal-close" onclick="closeModal(\'wizard-modal\')"', self.index_html)

        # 4. Drawers & popups have window-close-btn
        self.assertIn("tasks-popup-close window-close-btn", self.index_html)
        self.assertIn("release-drawer-close window-close-btn", self.index_html)
        self.assertIn("mobile-drawer-close window-close-btn", self.index_html)

    def test_servarr_theme_close_button_strict_isolation(self):
        """Ensure servarr theme retains static, non-rotating, borderless close button."""
        servarr_close_match = re.search(r"\[data-design=\"servarr\"\]\s+\.modal-close[^{]*\{([^}]+)\}", self.servarr)
        self.assertIsNotNone(servarr_close_match, "Servarr modal-close rule not found")
        servarr_css = servarr_close_match.group(1)
        self.assertIn("transform: none", servarr_css)
        self.assertIn("border: 0", servarr_css)
        self.assertIn("border-radius: 0", servarr_css)

        servarr_hover_match = re.search(r"\[data-design=\"servarr\"\]\s+\.modal-close:hover[^{]*\{([^}]+)\}", self.servarr)
        self.assertIsNotNone(servarr_hover_match, "Servarr modal-close hover rule not found")
        servarr_hover_css = servarr_hover_match.group(1)
        self.assertIn("transform: none", servarr_hover_css)


    def test_collection_card_hover_theme_color_and_no_cyan(self):
        """Ensure .collection-card:hover and .show-card:hover use var(--teal) and color-mix instead of hardcoded cyan."""
        card_hover_match = re.search(r"\.collection-card:hover\s*\{([^}]+)\}", self.style)
        self.assertIsNotNone(card_hover_match, ".collection-card:hover rule not found")
        card_hover_css = card_hover_match.group(1)
        self.assertNotIn("rgba(0, 240, 255", card_hover_css, "Hardcoded cyan must not be in .collection-card:hover")
        self.assertIn("var(--teal)", card_hover_css)
        self.assertIn("color-mix", card_hover_css)

        show_hover_match = re.search(r"\.show-card:hover\s*\{([^}]+)\}", self.style)
        self.assertIsNotNone(show_hover_match, ".show-card:hover rule not found")
        show_hover_css = show_hover_match.group(1)
        self.assertNotIn("rgba(0, 240, 255", show_hover_css, "Hardcoded cyan must not be in .show-card:hover")
        self.assertIn("var(--teal)", show_hover_css)
        self.assertIn("color-mix", show_hover_css)

    def test_collection_modal_hero_poster_and_parts_dimensions(self):
        """Ensure collection modal has 230px poster, 76px franchise parts, contrast gradient, and poster actions."""
        # 1. Poster column and poster dimensions (unindented desktop rule)
        poster_col_match = re.search(r"(?:^|\n)\.collection-hero-poster-col\s*\{([^}]+)\}", self.style)
        self.assertIsNotNone(poster_col_match, ".collection-hero-poster-col rule not found")
        self.assertIn("width: 230px", poster_col_match.group(1))

        poster_match = re.search(r"(?:^|\n)\.collection-hero-poster\s*\{([^}]+)\}", self.style)
        self.assertIsNotNone(poster_match, ".collection-hero-poster rule not found")
        poster_css = poster_match.group(1)
        self.assertIn("width: 230px", poster_css)
        self.assertIn("height: 345px", poster_css)

        # 2. Poster actions under poster
        poster_actions_match = re.search(r"(?:^|\n)\.collection-hero-poster-actions\s*\{([^}]+)\}", self.style)
        self.assertIsNotNone(poster_actions_match, ".collection-hero-poster-actions rule not found")
        self.assertIn("max-width: 230px", poster_actions_match.group(1))

        # 3. Backdrop gradient and text readability
        grad_match = re.search(r"\.collection-hero-gradient\s*\{([^}]+)\}", self.style)
        self.assertIsNotNone(grad_match, ".collection-hero-gradient rule not found")
        grad_css = grad_match.group(1)
        self.assertIn("linear-gradient", grad_css)
        self.assertIn("z-index: 2", grad_css)

        overview_match = re.search(r"(?:^|\n)\.collection-hero-overview\s*\{([^}]+)\}", self.style)
        self.assertIsNotNone(overview_match, ".collection-hero-overview rule not found")
        overview_css = overview_match.group(1)
        self.assertIn("color: #f8fafc", overview_css)
        self.assertIn("text-shadow:", overview_css)

        # 4. Title row padding-right for close & nav buttons isolation
        title_row_match = re.search(r"(?:^|\n)\.collection-hero-title-row\s*\{([^}]+)\}", self.style)
        self.assertIsNotNone(title_row_match, ".collection-hero-title-row rule not found")
        self.assertIn("padding-right: 120px", title_row_match.group(1))

        # 5. Franchise parts enlarged poster & 2-line overview
        part_poster_match = re.search(r"(?:^|\n)\.franchise-part-poster\s*\{([^}]+)\}", self.style)
        self.assertIsNotNone(part_poster_match, ".franchise-part-poster rule not found")
        part_poster_css = part_poster_match.group(1)
        self.assertIn("width: 90px", part_poster_css)
        self.assertIn("height: 135px", part_poster_css)

        part_overview_match = re.search(r"\.franchise-part-overview\s*\{([^}]+)\}", self.style)
        self.assertIsNotNone(part_overview_match, ".franchise-part-overview rule not found")
        self.assertIn("-webkit-line-clamp: 2", part_overview_match.group(1))

    def test_collection_modal_app_js_structure(self):
        """Ensure openCollectionModal in app.js renders actions in hero actions bar (not cramped under poster) and uses quality capsule."""
        self.assertIn("collection-hero-backdrop-wrap", self.app_js)
        self.assertIn("collection-hero-gradient", self.app_js)
        self.assertIn("collection-hero-poster-col", self.app_js)
        self.assertIn("collection-hero-actions-bar", self.app_js)
        self.assertIn("meta-pill-quality-profile", self.app_js)
        self.assertIn("franchise-progress-pill", self.app_js)
        self.assertIn("franchise-part-index", self.app_js)
        self.assertIn("franchise-part-row ${isInLib ? 'is-in-library' : ''}", self.app_js)

    def test_collection_modal_navigation_and_toolbar_features(self):
        """Ensure saga gallery navigation, monitored toggle, search-missing, chip filters, and stats exist."""
        # 1. Navigation controls in HTML and JS
        self.assertIn("collection-modal-nav-wrap", self.index_html)
        self.assertIn("collection-modal-prev-btn", self.index_html)
        self.assertIn("collection-modal-next-btn", self.index_html)
        self.assertIn("function navigateCollectionModal", self.app_js)
        self.assertIn("function updateCollectionModalNavButtons", self.app_js)

        # 2. Monitored toggle and search-missing
        self.assertIn("function toggleCollectionMonitored", self.app_js)
        self.assertIn("function searchMissingCollectionMovies", self.app_js)
        self.assertIn("meta-pill-monitored", self.style)
        self.assertIn("meta-pill-monitored", self.app_js)

        # 3. Badges for franchise parts (disk / queue / quality / size)
        self.assertIn("franchise-part-badge-disk", self.style)
        self.assertIn("franchise-part-badge-queue", self.style)
        self.assertIn("franchise-part-quality", self.style)
        self.assertIn("franchise-part-badge-disk", self.app_js)
        self.assertIn("franchise-part-badge-queue", self.app_js)
        self.assertIn("franchise-part-quality", self.app_js)

        # 4. Collections segmented filter & sorting in HTML and JS
        self.assertIn("collections-filter-control", self.index_html)
        self.assertIn("collections-sort-select", self.index_html)
        self.assertIn("collections-stats-counter", self.index_html)
        self.assertIn("function selectCollectionsFilter", self.app_js)
        self.assertIn("function onCollectionsSortChange", self.app_js)

        # 5. Library card collection chip displays part number
        self.assertIn("show-collection-chip", self.app_js)
        self.assertIn("Part ${show.collection_order}", self.app_js)

    def test_collections_search_in_header_row_and_safe_episode_quality(self):
        """Ensure collections search is located in header-row next to actions, and collections routes use downloaded_quality."""
        # 1. Search wrap is located in collections-panel-header, NOT inside collections-toolbar
        header_match = re.search(r'<header class="panel-header collections-panel-header">.*?</header>', self.index_html, re.DOTALL)
        self.assertIsNotNone(header_match, "collections-panel-header not found in index.html")
        header_html = header_match.group(0)
        self.assertIn('id="collections-search-wrap"', header_html)
        self.assertIn('id="btn-collections-spotlight-action"', header_html)
        self.assertIn('refreshAllCollections()', header_html)

        # 2. collections-toolbar only contains filter control and sort switcher (no search wrap)
        toolbar_match = re.search(r'<div class="toolbar collections-toolbar">.*?</div>\s*</div>\s*<div class="shows-grid collections-grid', self.index_html, re.DOTALL)
        if toolbar_match:
            toolbar_html = toolbar_match.group(0)
            self.assertNotIn('id="collections-search-wrap"', toolbar_html)

        # 3. Backend routes use downloaded_quality and file_size_bytes
        routes_py = read(ROOT / "app" / "api" / "collections_routes.py")
        self.assertIn('getattr(ep, "downloaded_quality", None)', routes_py)
        self.assertIn('getattr(ep, "file_size_bytes", None)', routes_py)
        self.assertNotIn('ep.quality', routes_py, "Direct ep.quality must not be used (causes AttributeError)")

    def test_show_modal_gallery_navigation_and_quality_profile_badge(self):
        """Ensure show modal has gallery navigation buttons and quality profile is styled as a capsule badge."""
        # 1. Show modal header actions with prev and next buttons in index.html
        self.assertIn("show-modal-header-actions", self.index_html)
        self.assertIn("show-modal-nav-wrap", self.index_html)
        self.assertIn("show-modal-prev-btn", self.index_html)
        self.assertIn("show-modal-next-btn", self.index_html)

        # 2. Navigation logic in app.js
        self.assertIn("function navigateShowModal", self.app_js)
        self.assertIn("function updateShowModalNavButtons", self.app_js)
        self.assertIn("function getActiveShowsList", self.app_js)

        # 3. Quality profile capsule badge in CSS
        self.assertIn(".meta-pill-quality-profile", self.style)
        self.assertIn(".meta-pill-qp-label", self.style)
        self.assertIn(".meta-pill-qp-select", self.style)
        self.assertIn(".meta-pill-qp-select option", self.style)
        self.assertIn("color-scheme: dark", self.style)

        # 4. Collection hero actions bar in CSS
        self.assertIn(".collection-hero-actions-bar", self.style)


if __name__ == "__main__":
    unittest.main()


