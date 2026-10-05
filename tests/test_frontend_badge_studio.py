from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STYLE_PATH = ROOT / 'web' / 'css' / 'style.css'
APP_JS_PATH = ROOT / 'web' / 'js' / 'app.js'
INDEX_PATH = ROOT / 'web' / 'index.html'

def read(path: Path) -> str:
    return path.read_text(encoding='utf-8')

class TestBadgeStudioCoverage(unittest.TestCase):
    def setUp(self):
        self.style = read(STYLE_PATH)
        self.app_js = read(APP_JS_PATH)
        self.index_html = read(INDEX_PATH)

    def test_badge_shape_selectors_include_all_system_badges(self):
        expected_classes = [
            '.badge',
            '.badge-quality',
            '.badge-hdr',
            '.badge-audio',
            '.badge-lang',
            '.badge-group',
            '.badge-edition',
            '.badge-collection',
            '.badge-cf-score',
            '.badge-cf-item',
            '.badge-file-present',
            '.badge-upgrade-pending',
            '.badge-season-progress',
            '.show-quality-badge',
            '.category-badge-chip',
            '.poster-status-pill',
            '.alias-chip',
            '.meta-badge',
        ]
        shapes = ['pill', 'rounded', 'sharp', 'chamfer']
        for shape in shapes:
            self.assertIn(f'[data-badge-shape="{shape}"]', self.style)
            for cls in expected_classes:
                self.assertIn(cls, self.style, f'Class {cls} missing from badge studio rules')

    def test_badge_shapes_definitions(self):
        self.assertIn('clip-path: polygon(5px 0, 100% 0, 100% calc(100% - 5px), calc(100% - 5px) 100%, 0 100%, 0 5px)', self.style)
        self.assertIn('border-radius: 9999px', self.style)

    def test_badge_styles_definitions(self):
        self.assertIn('[data-badge-style="frosted"]', self.style)
        self.assertIn('backdrop-filter: var(--glass-blur, blur(8px))', self.style)
        self.assertIn('[data-badge-style="outline"]', self.style)
        self.assertIn('border-color: currentColor', self.style)
        self.assertIn('[data-badge-style="subtle"]', self.style)

    def test_badge_palette_monochrome_and_contrast(self):
        self.assertIn('[data-badge-color="monochrome"]', self.style)
        self.assertIn('color: var(--teal)', self.style)
        self.assertIn('[data-badge-color="high-contrast"]', self.style)
        self.assertIn('color: #ffffff', self.style)

    def test_interactive_stage_uses_real_badge_classes(self):
        self.assertIn('badge-quality', self.app_js)
        self.assertIn('badge-hdr', self.app_js)
        self.assertIn('badge-audio', self.app_js)
        self.assertIn('show-quality-badge', self.app_js)
        self.assertIn('category-badge-chip', self.app_js)

if __name__ == '__main__':
    unittest.main()
