from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

try:
    from app.api.operations import get_health_check
    HAS_DEPS = True
except ImportError:
    HAS_DEPS = False


class TestHealthAndDC(unittest.TestCase):
    def test_health_check_returns_comprehensive_metrics(self):
        if not HAS_DEPS:
            self.skipTest('FastAPI / dependencies not installed in host runner')
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.count.return_value = 2
        mock_db.query.return_value.count.return_value = 2

        with patch('os.path.exists', return_value=True),              patch('os.path.getsize', return_value=1024 * 1024 * 5),              patch('shutil.disk_usage', return_value=(1000, 500, 500)):
            res = get_health_check(db=mock_db)

        self.assertIn('status', res)
        self.assertIn('checks', res)
        checks = res['checks']
        titles = [c.get('title') for c in checks]
        self.assertIn('База данных', titles)
        self.assertIn('Индексаторы', titles)
        self.assertIn('Загрузчики', titles)
        self.assertIn('Фоновый мониторинг', titles)
        self.assertIn('Безопасность', titles)


if __name__ == '__main__':
    unittest.main()
