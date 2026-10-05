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


if __name__ == "__main__":
    unittest.main()
