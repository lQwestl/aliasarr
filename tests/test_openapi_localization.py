# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import re
import unittest
from unittest.mock import MagicMock

from app.services.openapi_catalog import (
    COMMON_PARAM_DESCRIPTIONS,
    ENDPOINT_CATALOG,
    RESPONSES_EN,
    RESPONSES_RU,
)
from app.services.openapi_service import (
    DESCRIPTION_EN,
    DESCRIPTION_RU,
    ENDPOINT_SUMMARIES,
    TAGS_METADATA_EN,
    TAGS_METADATA_RU,
    clear_openapi_cache,
    get_localized_openapi,
)


class TestOpenApiLocalization(unittest.TestCase):
    def setUp(self):
        clear_openapi_cache()
        self.base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.api_docs_html_path = os.path.join(self.base_dir, "web", "api-docs.html")
        self.cyrillic_pattern = re.compile(r"[\u0400-\u04FF]")

    def test_descriptions_no_duplicate_h1_header(self):
        """Verify that duplicate H1 headers are removed from API descriptions."""
        self.assertNotIn("# Aliasarr REST API — Интерактивный справочник", DESCRIPTION_RU)
        self.assertNotIn("# Aliasarr REST API — Interactive Reference", DESCRIPTION_EN)
        self.assertFalse(DESCRIPTION_RU.startswith("# "))
        self.assertFalse(DESCRIPTION_EN.startswith("# "))
        self.assertTrue(DESCRIPTION_RU.startswith("Добро пожаловать в официальную документацию"))
        self.assertTrue(DESCRIPTION_EN.startswith("Welcome to the official REST API"))

    def test_catalog_size_and_exact_count(self):
        """Verify that all 199 endpoints are defined in the catalog."""
        self.assertEqual(len(ENDPOINT_CATALOG), 199)
        self.assertEqual(len(ENDPOINT_SUMMARIES), 199)

    def test_catalog_bilingual_integrity_and_zero_cyrillic_leak(self):
        """Verify that English translations have strictly ZERO Cyrillic characters and valid content."""
        for (path, method), (ru_sum, en_sum, ru_desc, en_desc) in ENDPOINT_CATALOG.items():
            self.assertTrue(len(ru_sum.strip()) > 0, f"Empty ru_sum for {method} {path}")
            self.assertTrue(len(en_sum.strip()) > 0, f"Empty en_sum for {method} {path}")
            self.assertTrue(len(ru_desc.strip()) > 0, f"Empty ru_desc for {method} {path}")
            self.assertTrue(len(en_desc.strip()) > 0, f"Empty en_desc for {method} {path}")

            # Strict verification: zero Cyrillic characters in English texts
            self.assertFalse(
                self.cyrillic_pattern.search(en_sum),
                f"Cyrillic character found in English summary for {method} {path}: {en_sum}",
            )
            self.assertFalse(
                self.cyrillic_pattern.search(en_desc),
                f"Cyrillic character found in English description for {method} {path}: {en_desc}",
            )

    def test_english_tags_and_description_zero_cyrillic(self):
        """Ensure all tag metadata and overview description in English mode have ZERO Cyrillic letters."""
        self.assertFalse(
            self.cyrillic_pattern.search(DESCRIPTION_EN),
            "Cyrillic character found in DESCRIPTION_EN",
        )
        for tag in TAGS_METADATA_EN:
            tag_name = tag.get("name", "")
            tag_desc = tag.get("description", "")
            self.assertFalse(
                self.cyrillic_pattern.search(tag_name),
                f"Cyrillic character found in English tag name: {tag_name}",
            )
            self.assertFalse(
                self.cyrillic_pattern.search(tag_desc),
                f"Cyrillic character found in English tag description: {tag_desc}",
            )

    def test_parameter_and_response_translations(self):
        """Verify parameter descriptions and status responses are bilingual and English is Cyrillic-free."""
        for param_name, (ru_desc, en_desc) in COMMON_PARAM_DESCRIPTIONS.items():
            self.assertTrue(len(ru_desc) > 0)
            self.assertTrue(len(en_desc) > 0)
            self.assertFalse(
                self.cyrillic_pattern.search(en_desc),
                f"Cyrillic character found in English param desc for '{param_name}': {en_desc}",
            )

        for code, desc in RESPONSES_EN.items():
            self.assertTrue(len(desc) > 0)
            self.assertFalse(
                self.cyrillic_pattern.search(desc),
                f"Cyrillic character found in English response description for '{code}': {desc}",
            )

        for code, desc in RESPONSES_RU.items():
            self.assertTrue(len(desc) > 0)

    def test_api_docs_html_floating_button_present(self):
        """Verify that web/api-docs.html contains the floating back-to-top button, CSS, and JS."""
        with open(self.api_docs_html_path, "r", encoding="utf-8") as f:
            html = f.read()

        # HTML Button and classes
        self.assertIn('id="btn-back-to-top"', html)
        self.assertIn('class="api-floating-bar"', html)
        self.assertIn('class="api-floating-btn"', html)
        self.assertIn('onclick="scrollToTop()"', html)
        self.assertIn('data-lucide="arrow-up"', html)

        # CSS Styles
        self.assertIn('.api-floating-bar {', html)
        self.assertIn('.api-floating-btn {', html)
        self.assertIn('#btn-back-to-top {', html)
        self.assertIn('#btn-back-to-top.visible {', html)
        self.assertIn('env(safe-area-inset-bottom', html)

        # JavaScript Scroll listener and action
        self.assertIn('function scrollToTop()', html)
        self.assertIn("window.addEventListener('scroll'", html)

    def test_get_localized_openapi_sanitization(self):
        """Test localization logic and English sanitization on dummy OpenAPI schema."""
        dummy_schema = {
            "openapi": "3.1.0",
            "info": {"title": "Test", "version": "1.0"},
            "paths": {
                "/api/v1/shows": {
                    "get": {
                        "summary": "Список всех тайтлов",
                        "description": "Описание на русском языке с кириллицей.",
                        "parameters": [
                            {"name": "show_id", "in": "path", "description": "ID тайтла"},
                            {"name": "custom_arg", "in": "query", "description": "Пользовательский параметр"},
                        ],
                        "responses": {
                            "200": {"description": "Успешный ответ"},
                            "404": {"description": "Не найдено"},
                        },
                    }
                }
            },
        }

        mock_app = MagicMock()
        mock_app.routes = []

        with unittest.mock.patch("app.services.openapi_service.get_openapi", return_value=dummy_schema):
            # Test English output
            clear_openapi_cache()
            en_schema = get_localized_openapi(mock_app, lang="en")
            op_en = en_schema["paths"]["/api/v1/shows"]["get"]

            self.assertEqual(op_en["summary"], "List all library shows")
            self.assertEqual(
                op_en["description"],
                "Returns all movies, series, and anime in the library with episode progress, file counts, and cover art.",
            )
            self.assertFalse(self.cyrillic_pattern.search(op_en["summary"]))
            self.assertFalse(self.cyrillic_pattern.search(op_en["description"]))

            # Parameters
            params = {p["name"]: p["description"] for p in op_en["parameters"]}
            self.assertEqual(params["show_id"], "Unique title/show identifier")
            self.assertFalse(self.cyrillic_pattern.search(params["show_id"]))
            self.assertFalse(self.cyrillic_pattern.search(params["custom_arg"]))

            # Responses
            responses = {code: r["description"] for code, r in op_en["responses"].items()}
            self.assertEqual(responses["200"], "Successful response")
            self.assertEqual(responses["404"], "Requested resource not found")

            # Test Russian output
            clear_openapi_cache()
            ru_schema = get_localized_openapi(mock_app, lang="ru")
            op_ru = ru_schema["paths"]["/api/v1/shows"]["get"]
            self.assertEqual(op_ru["summary"], "Получить список всех тайтлов медиатеки")
            self.assertIn("Возвращает карточки всех фильмов", op_ru["description"])


if __name__ == "__main__":
    unittest.main()
