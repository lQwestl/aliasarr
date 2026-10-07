from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STYLE_PATH = ROOT / "web" / "css" / "style.css"
SERVARR_PATH = ROOT / "web" / "css" / "servarr.css"
APP_JS_PATH = ROOT / "web" / "js" / "app.js"
AUTO_SEARCH_PATH = ROOT / "app" / "services" / "auto_search.py"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class TestFrontendCardAliasesAndSearchStatus(unittest.TestCase):
    def setUp(self):
        self.style = read(STYLE_PATH)
        self.servarr = read(SERVARR_PATH)
        self.app_js = read(APP_JS_PATH)
        self.auto_search = read(AUTO_SEARCH_PATH)

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
        modal_match = re.search(r"#show-modal\s+\.modal,\s*\n#collection-modal\s+\.modal\s*\{([^}]+)\}", self.style)
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


if __name__ == "__main__":
    unittest.main()

