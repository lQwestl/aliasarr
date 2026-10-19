from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_JS_PATH = ROOT / "web" / "js" / "app.js"
INDEX_PATH = ROOT / "web" / "index.html"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class TestFrontendModalEscape(unittest.TestCase):
    def setUp(self):
        self.app_js = read(APP_JS_PATH)
        self.index_html = read(INDEX_PATH)

    def test_modal_stack_and_helpers_defined(self):
        """Проверяем наличие стека модальных окон MODAL_STACK и вспомогательных функций getTopActiveModal и closeActiveModalById."""
        self.assertIn("let MODAL_STACK = [];", self.app_js)
        self.assertIn("function getTopActiveModal()", self.app_js)
        self.assertIn("function closeActiveModalById(id)", self.app_js)

    def test_open_modal_tracks_in_stack(self):
        """Функция openModal регистрирует модальное окно в MODAL_STACK."""
        self.assertIn("MODAL_STACK = MODAL_STACK.filter(m => m !== id);", self.app_js)
        self.assertIn("MODAL_STACK.push(id);", self.app_js)

    def test_close_modal_removes_from_stack(self):
        """Функция closeModal удаляет модальное окно из MODAL_STACK."""
        self.assertIn("MODAL_STACK = MODAL_STACK.filter(m => m !== id);", self.app_js)

    def test_escape_handler_modal_handling(self):
        """Глобальный обработчик Escape закрывает активные модалки через getTopActiveModal и closeActiveModalById."""
        self.assertIn("if (e.key === \"Escape\")", self.app_js)
        self.assertIn("const topModalId = getTopActiveModal();", self.app_js)
        self.assertIn("if (topModalId)", self.app_js)
        self.assertIn("closeActiveModalById(topModalId);", self.app_js)

    def test_confirm_modal_overlay_click_cancel_trigger(self):
        """При клике по оверлею confirm-modal триггерится кнопка Отмена для корректного разрешения промиса."""
        self.assertIn("if (overlay.id === \"confirm-modal\")", self.app_js)
        self.assertIn("cancelBtn.click();", self.app_js)

    def test_modal_close_buttons_tooltips_include_esc(self):
        """Кнопки закрытия ключевых модальных окон имеют подсказку (Esc)."""
        self.assertIn("title=\"Закрыть (Esc)\"", self.index_html)


if __name__ == "__main__":
    unittest.main()
