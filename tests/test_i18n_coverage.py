from __future__ import annotations

import os
import re
import unittest

class TestTranslationsCoverage(unittest.TestCase):
    def setUp(self):
        self.base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.app_js_path = os.path.join(self.base_dir, "web", "js", "app.js")
        self.index_html_path = os.path.join(self.base_dir, "web", "index.html")
        self.guide_html_path = os.path.join(self.base_dir, "web", "quality-guide.html")

    def test_app_translations_symmetry(self):
        with open(self.app_js_path, "r", encoding="utf-8") as f:
            text = f.read()

        ru_start = text.find("ru: {")
        en_start = text.find("en: {")
        en_end = text.find("let CURRENT_LANG", en_start)

        self.assertTrue(ru_start > 0, "ru translations start not found")
        self.assertTrue(en_start > 0, "en translations start not found")

        ru_dict = dict(re.findall(r'"([^"]+)":\s*"((?:[^"\\]|\\.)*)"', text[ru_start:en_start], re.DOTALL))
        en_dict = dict(re.findall(r'"([^"]+)":\s*"((?:[^"\\]|\\.)*)"', text[en_start:en_end], re.DOTALL))

        self.assertGreater(len(ru_dict), 800)
        self.assertGreater(len(en_dict), 800)

        missing_in_en = set(ru_dict.keys()) - set(en_dict.keys())
        missing_in_ru = set(en_dict.keys()) - set(ru_dict.keys())

        self.assertEqual(missing_in_en, set(), f"Keys in RU missing in EN: {missing_in_en}")
        self.assertEqual(missing_in_ru, set(), f"Keys in EN missing in RU: {missing_in_ru}")

    def test_index_html_i18n_keys_present_in_translations(self):
        with open(self.app_js_path, "r", encoding="utf-8") as f:
            text = f.read()

        ru_start = text.find("ru: {")
        en_start = text.find("en: {")
        en_end = text.find("let CURRENT_LANG", en_start)
        ru_dict = dict(re.findall(r'"([^"]+)":\s*"((?:[^"\\]|\\.)*)"', text[ru_start:en_start], re.DOTALL))
        en_dict = dict(re.findall(r'"([^"]+)":\s*"((?:[^"\\]|\\.)*)"', text[en_start:en_end], re.DOTALL))

        with open(self.index_html_path, "r", encoding="utf-8") as f:
            html = f.read()

        html_keys = set(re.findall(r'data-i18n(?:-placeholder|-title|-label)?="([^"]+)"', html))
        self.assertGreater(len(html_keys), 200)

        for k in html_keys:
            self.assertIn(k, ru_dict, f"HTML key '{k}' missing from TRANSLATIONS.ru")
            self.assertIn(k, en_dict, f"HTML key '{k}' missing from TRANSLATIONS.en")

    def test_quality_guide_bilingual_translations(self):
        with open(self.guide_html_path, "r", encoding="utf-8") as f:
            guide_html = f.read()

        self.assertIn("GUIDE_TRANSLATIONS", guide_html)
        self.assertIn("applyGuideLanguage", guide_html)
        self.assertIn("toggleGuideLang", guide_html)
        self.assertIn("guide-lang-toggle", guide_html)

        # Check all data-i18n in guide
        guide_keys = set(re.findall(r'data-i18n(?:-placeholder|-title)?="([^"]+)"', guide_html))
        self.assertGreater(len(guide_keys), 40)

        # Extract ru and en dicts from GUIDE_TRANSLATIONS
        qg_ru_match = re.search(r'ru:\s*\{([^}]+(?:\n\s*[^}]+)*)\n\s*\},', guide_html)
        qg_en_match = re.search(r'en:\s*\{([^}]+(?:\n\s*[^}]+)*)\n\s*\}', guide_html)

        self.assertIsNotNone(qg_ru_match)
        self.assertIsNotNone(qg_en_match)

        qg_ru = dict(re.findall(r'"([^"]+)":\s*"((?:[^"\\]|\\.)*)"', qg_ru_match.group(1), re.DOTALL))
        qg_en = dict(re.findall(r'"([^"]+)":\s*"((?:[^"\\]|\\.)*)"', qg_en_match.group(1), re.DOTALL))

        for k in guide_keys:
            self.assertIn(k, qg_ru, f"Quality guide key '{k}' missing from GUIDE_TRANSLATIONS.ru")
            self.assertIn(k, qg_en, f"Quality guide key '{k}' missing from GUIDE_TRANSLATIONS.en")

if __name__ == "__main__":
    unittest.main()
