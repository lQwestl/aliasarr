"""Статические проверки инлайновых обработчиков фронтенда.

Эти проверки ловят класс ошибок, который не виден ни линтеру Python, ни глазу при
беглом просмотре: обработчик в HTML-атрибуте ссылается на несуществующую функцию
или на строковый литерал, собранный небезопасным экранированием. В обоих случаях
кнопка молча перестаёт работать — исключение уходит в консоль браузера.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "web" / "js" / "app.js"
INDEX_HTML = ROOT / "web" / "index.html"

HANDLER_ATTR_RE = re.compile(
    r"""\son(?:click|change|input|submit|keydown|keyup|blur|focus|error|load)\s*=\s*"([^"]*)\"""",
    re.IGNORECASE,
)
CALL_RE = re.compile(r"([A-Za-z_$][A-Za-z0-9_$]*)\s*\(")

# Методы объектов и языковые конструкции, которые не являются глобальными функциями.
NOT_GLOBAL_FUNCTIONS = {
    "if", "for", "while", "switch", "return", "typeof", "catch", "function", "try",
    "String", "Number", "Boolean", "Array", "Object", "JSON", "Math", "Date",
    "parseInt", "parseFloat", "encodeURIComponent", "decodeURIComponent", "RegExp",
    "Set", "Map", "fetch", "console", "alert", "confirm",
    "setTimeout", "setInterval", "clearTimeout", "clearInterval", "requestAnimationFrame",
    "preventDefault", "stopPropagation", "getElementById", "querySelector",
    "writeText", "click", "open", "setItem", "getItem", "replace", "stringify",
    "slice", "focus", "blur", "toggle", "add", "remove",
}


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def declared_globals(app_js: str) -> set[str]:
    names: set[str] = set()
    names.update(re.findall(r"^\s*(?:async\s+)?function\s+([A-Za-z0-9_$]+)", app_js, re.MULTILINE))
    names.update(re.findall(r"^(?:const|let|var)\s+([A-Za-z0-9_$]+)", app_js, re.MULTILINE))
    names.update(re.findall(r"window\.([A-Za-z0-9_$]+)\s*=", app_js))
    return names


class TestInlineHandlers(unittest.TestCase):
    def test_every_handler_in_markup_resolves_to_a_declared_function(self):
        app_js = read(APP_JS)
        known = declared_globals(app_js) | NOT_GLOBAL_FUNCTIONS

        missing: set[str] = set()
        for body in HANDLER_ATTR_RE.findall(read(INDEX_HTML)):
            for name in CALL_RE.findall(body):
                if name not in known:
                    missing.add(name)

        self.assertEqual(
            missing,
            set(),
            f"Обработчики в index.html вызывают необъявленные функции: {sorted(missing)}",
        )

    def test_no_manual_quote_escaping_after_escape_html(self):
        """escapeHtml уже превращает апостроф в &#39;, поэтому последующий
        .replace(/'/g, ...) ничего не находит, а парсер HTML возвращает апостроф
        обратно и рвёт строковый литерал внутри обработчика. Для аргументов
        обработчиков есть jsArg()."""
        app_js = read(APP_JS)
        offenders = re.findall(r"escapeHtml\([^\n]*?\)\.replace\(/'/g", app_js)
        self.assertEqual(
            offenders,
            [],
            "Используйте jsArg(value) вместо escapeHtml(value).replace(/'/g, ...)",
        )

    def test_js_arg_helper_exists_and_double_encodes(self):
        app_js = read(APP_JS)
        self.assertIn("function jsArg(value)", app_js)
        self.assertRegex(app_js, r"return escapeHtml\(JSON\.stringify\(raw\)\);")


class TestFolderPickerNavigation(unittest.TestCase):
    def test_up_button_uses_parent_reported_by_backend(self):
        app_js = read(APP_JS)
        self.assertIn("FOLDER_PICKER_PARENT_PATH", app_js)
        self.assertIn("function folderPickerNavigateUp()", app_js)
        # Навигация вверх не должна опираться только на разбор текущей строки:
        # после неудачной загрузки она оставалась равной "/" и кнопка «не работала».
        nav = app_js.split("function folderPickerNavigateUp()", 1)[1].split("}", 1)[0]
        self.assertIn("FOLDER_PICKER_PARENT_PATH", nav)

    def test_missing_folder_falls_back_to_nearest_existing_parent(self):
        app_js = read(APP_JS)
        loader = app_js.split("async function folderPickerLoad(", 1)[1]
        loader = loader.split("function folderPickerRender", 1)[0]
        self.assertIn("e.status === 404", loader)
        self.assertIn("folderPickerParentOf(candidate)", loader)

    def test_modal_exposes_editable_path_and_up_button(self):
        html = read(INDEX_HTML)
        self.assertIn('id="folder-picker-up-btn"', html)
        self.assertRegex(html, r'<input[^>]*id="folder-picker-current-path"')
        self.assertIn("folderPickerGoToTypedPath()", html)


class TestSettingsSubTabNavigation(unittest.TestCase):
    def test_switch_settings_sub_tab_is_defined(self):
        app_js = read(APP_JS)
        self.assertIn("function switchSettingsSubTab(", app_js)

    def test_markup_aliases_resolve_to_real_tabs(self):
        app_js = read(APP_JS)
        html = read(INDEX_HTML)
        aliases = set(re.findall(r"switchSettingsSubTab\('([^']+)'\)", html))
        self.assertTrue(aliases, "в разметке не нашлось вызовов switchSettingsSubTab")

        alias_block = app_js.split("const SETTINGS_SUBTAB_ALIASES = {", 1)[1].split("};", 1)[0]
        known_aliases = set(re.findall(r'"?([A-Za-z0-9_\-]+)"?\s*:', alias_block))
        real_tabs = set(re.findall(r'data-settings-tab="([^"]+)"', html))

        for alias in aliases:
            self.assertTrue(
                alias in real_tabs or alias in known_aliases,
                f"switchSettingsSubTab('{alias}') не соответствует ни одной подвкладке настроек",
            )


if __name__ == "__main__":
    unittest.main()
