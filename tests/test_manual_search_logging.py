import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

try:
    from app.models.db import Episode, Indexer, LogEntry, Show, User
    from app.api.indexers import search_custom_releases, search_releases_for_show
    from app.api.system_routes import list_journal
    HAS_DEPS = True
except ImportError:
    HAS_DEPS = False


class TestManualSearchLogging(unittest.TestCase):
    def test_search_custom_releases_logs_events(self):
        if not HAS_DEPS:
            self.skipTest('FastAPI / dependencies not installed in host runner')
        mock_db = MagicMock()
        mock_indexer = Indexer(id=1, name="RuTracker", enabled=True, priority=1)
        mock_db.query.return_value.filter.return_value.all.return_value = [mock_indexer]
        mock_db.get.return_value = None

        mock_user = MagicMock(spec=User)

        mock_rel = MagicMock()
        mock_rel.title = "Test Anime - 01 [1080p]"
        mock_rel.guid = "guid123"
        mock_rel.download_url = "http://example.com/1.torrent"
        mock_rel.page_url = "http://example.com/1"
        mock_rel.seeders = 10
        mock_rel.size_bytes = 1024 * 1024 * 500
        mock_rel.pub_date = "2026-09-10"

        mock_client = AsyncMock()
        mock_client.search.return_value = [mock_rel]

        with patch("app.api.indexers.get_indexer_client", return_value=mock_client), \
             patch("app.api.indexers.get_or_create_settings") as mock_settings, \
             patch("app.api.indexers.manual_logger") as mock_logger:

            mock_settings.return_value = MagicMock()

            results = asyncio.run(search_custom_releases(
                query="Test Anime",
                db=mock_db,
                current_user=mock_user,
            ))

            self.assertEqual(len(results), 1)
            # Check manual_logger calls
            info_messages = [call[0][0] for call in mock_logger.info.call_args_list]
            self.assertTrue(any("Запуск ручного поиска" in msg for msg in info_messages))
            self.assertTrue(any("Индексатор «%s»: найдено релизов" in msg for msg in info_messages))
            self.assertTrue(any("Ручной поиск завершён" in msg for msg in info_messages))

    def test_search_releases_for_show_logs_events(self):
        if not HAS_DEPS:
            self.skipTest('FastAPI / dependencies not installed in host runner')
        mock_db = MagicMock()
        mock_show = Show(id=1, title="Attack on Titan", content_type="anime", year=2013)
        mock_indexer = Indexer(id=1, name="Nyaa", enabled=True, priority=1)

        def mock_get(model, pk):
            if model == Show and pk == 1:
                return mock_show
            return None

        mock_db.get.side_effect = mock_get
        mock_db.query.return_value.filter.return_value.all.return_value = [mock_indexer]

        mock_user = MagicMock(spec=User)

        mock_rel = MagicMock()
        mock_rel.title = "Attack on Titan S01E01 [1080p]"
        mock_rel.guid = "guid456"
        mock_rel.download_url = "http://example.com/2.torrent"
        mock_rel.page_url = "http://example.com/2"
        mock_rel.seeders = 25
        mock_rel.size_bytes = 1024 * 1024 * 800
        mock_rel.pub_date = "2026-09-10"

        mock_client = AsyncMock()
        mock_client.search.return_value = [mock_rel]

        with patch("app.api.indexers.get_indexer_client", return_value=mock_client), \
             patch("app.api.indexers.get_or_create_settings") as mock_settings, \
             patch("app.api.indexers.build_alias_candidates", return_value=[]), \
             patch("app.api.indexers.manual_logger") as mock_logger:

            mock_settings.return_value = MagicMock()

            results = asyncio.run(search_releases_for_show(
                show_id=1,
                db=mock_db,
                current_user=mock_user,
            ))

            info_messages = [call[0][0] for call in mock_logger.info.call_args_list]
            self.assertTrue(any("Запуск ручного поиска" in msg for msg in info_messages))
            self.assertTrue(any("Ручной поиск завершён" in msg for msg in info_messages))

    def test_list_journal_component_filter(self):
        if not HAS_DEPS:
            self.skipTest('FastAPI / dependencies not installed in host runner')
        mock_db = MagicMock()
        mock_query = mock_db.query.return_value
        mock_query.filter.return_value = mock_query
        mock_query.count.return_value = 2
        mock_query.order_by.return_value.offset.return_value.limit.return_value.all.return_value = [
            LogEntry(id=1, level="info", component="aliasarr.manual_search", message="Test search"),
            LogEntry(id=2, level="info", component="aliasarr.manual_search", message="Test grab"),
        ]

        mock_user = MagicMock(spec=User)

        res = list_journal(
            level="all",
            component="manual_search",
            page=1,
            page_size=50,
            db=mock_db,
            current_user=mock_user,
        )

        self.assertEqual(res.total, 2)
        self.assertEqual(len(res.items), 2)
        # Ensure filter was called on component
        filter_calls = mock_db.query.return_value.filter.call_args_list
        self.assertTrue(len(filter_calls) > 0)


if __name__ == "__main__":
    unittest.main()
