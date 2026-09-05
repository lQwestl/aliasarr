import unittest
from unittest.mock import AsyncMock, MagicMock, patch


class TestBlocklistEnhanced(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        try:
            import sqlalchemy  # noqa: F401
        except ImportError:
            self.skipTest("SQLAlchemy not installed in host runner")
    def test_add_to_blocklist_and_query(self):
        from app.services.blocklist_service import add_to_blocklist
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None

        entry = add_to_blocklist(
            mock_db,
            release_title="Attack.on.Titan.S04.1080p",
            reason="Отсутствуют запрошенные серии",
            show_id=10,
            torrent_hash="AABBCCDDEEFF11223344",
            indexer="RuTracker",
            size=1024 * 1024 * 500,
        )
        self.assertIsNotNone(entry)
        mock_db.add.assert_called_once()
        mock_db.commit.assert_called_once()

    def test_is_release_blocked_title_and_hash(self):
        from app.models.db import Blocklist
        from app.services.blocklist_service import is_release_blocked
        mock_db = MagicMock()
        existing = Blocklist(
            id=1,
            show_id=10,
            release_title="Attack.on.Titan.S04.1080p",
            torrent_hash="AABBCCDDEEFF11223344",
            reason="Blocked test reason",
        )
        # By hash
        mock_db.query.return_value.filter.return_value.first.return_value = existing
        is_blocked, reason = is_release_blocked(
            mock_db,
            show_id=10,
            torrent_hash="aabbccddeeff11223344",
        )
        self.assertTrue(is_blocked)
        self.assertEqual(reason, "Blocked test reason")

        # By title
        mock_db.query.return_value.filter.return_value.first.return_value = existing
        is_blocked, reason = is_release_blocked(
            mock_db,
            show_id=10,
            release_title="Attack.on.Titan.S04.1080p",
        )
        self.assertTrue(is_blocked)
        self.assertEqual(reason, "Blocked test reason")

    def test_remove_from_blocklist(self):
        from app.models.db import Blocklist
        from app.services.blocklist_service import remove_from_blocklist
        mock_db = MagicMock()
        existing = Blocklist(id=5, release_title="Sample")
        mock_db.query.return_value.filter.return_value.first.return_value = existing

        res = remove_from_blocklist(mock_db, 5)
        self.assertTrue(res)
        mock_db.delete.assert_called_once_with(existing)
        mock_db.commit.assert_called_once()

    def test_clear_blocklist_for_show_and_all(self):
        from app.services.blocklist_service import clear_blocklist_for_show, clear_all_blocklist
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.delete.return_value = 3
        count = clear_blocklist_for_show(mock_db, show_id=7)
        self.assertEqual(count, 3)

        mock_db.query.return_value.delete.return_value = 10
        count_all = clear_all_blocklist(mock_db)
        self.assertEqual(count_all, 10)

    def test_get_blocked_shows_summary(self):
        from app.models.db import Show
        from app.services.blocklist_service import get_blocked_shows_summary
        mock_db = MagicMock()
        # Mock group_by result
        mock_db.query.return_value.group_by.return_value.all.return_value = [
            (10, 5),
            (None, 2),
        ]
        show = Show(id=10, title="Naruto", poster_url="/posters/naruto.jpg", release_year=2002)
        mock_db.get.return_value = show

        summary = get_blocked_shows_summary(mock_db)
        self.assertEqual(len(summary), 2)
        self.assertEqual(summary[0]["show_id"], 10)
        self.assertEqual(summary[0]["show_title"], "Naruto")
        self.assertEqual(summary[0]["blocked_count"], 5)
        self.assertEqual(summary[1]["show_id"], None)
        self.assertEqual(summary[1]["show_title"], "Без привязки к тайтлу")
        self.assertEqual(summary[1]["blocked_count"], 2)

    async def test_blocklist_routes_delete_and_list(self):
        from app.models.db import User
        from app.api.blocklist_routes import delete_blocklist_entry, clear_blocklist
        mock_db = MagicMock()
        user = User(id=1, username="admin", is_admin=True)

        with patch("app.services.blocklist_service.remove_from_blocklist", return_value=True):
            res = delete_blocklist_entry(entry_id=5, db=mock_db, current_user=user)
            self.assertTrue(res["success"])

        with patch("app.services.blocklist_service.clear_blocklist_for_show", return_value=4):
            res2 = clear_blocklist(show_id=10, db=mock_db, current_user=user)
            self.assertTrue(res2["success"])
            self.assertEqual(res2["deleted_count"], 4)

        with patch("app.services.blocklist_service.clear_all_blocklist", return_value=15):
            res3 = clear_blocklist(show_id=None, db=mock_db, current_user=user)
            self.assertTrue(res3["success"])
            self.assertEqual(res3["deleted_count"], 15)

    async def test_limit_torrent_files_cancellation_adds_to_blocklist(self):
        from app.models.db import Show, Episode, EpisodeStatus
        from app.services.auto_search import _limit_torrent_files_to_episodes
        mock_dl = AsyncMock()
        mock_dl.get_torrent_files = AsyncMock(return_value=[
            {"index": 0, "name": "Completely.Unrelated.Movie.mkv", "size": 1000000}
        ])
        mock_dl.remove_torrent = AsyncMock()

        show = Show(id=20, title="Sample Anime", content_type="anime")
        ep = Episode(id=100, show_id=20, season_number=1, episode_number=1, status=EpisodeStatus.DOWNLOADING, torrent_hash="TESTHASH123")

        mock_db = MagicMock()
        mock_db.is_active = True
        mock_db.get.return_value = ep

        with patch("app.services.blocklist_service.add_to_blocklist") as mock_add_block, \
             patch("app.services.auto_search.log_release_event") as mock_log:

            await _limit_torrent_files_to_episodes(
                mock_dl,
                "TESTHASH123",
                [ep],
                [ep],
                db=mock_db,
                torrent=MagicMock(name="Sample Anime S01 - Wrong Files", size=1000000),
            )

            mock_dl.remove_torrent.assert_called_once_with("TESTHASH123", delete_files=True)
            self.assertEqual(ep.status, EpisodeStatus.WANTED)
            mock_add_block.assert_called_once()
            call_kwargs = mock_add_block.call_args[1]
            self.assertEqual(call_kwargs["torrent_hash"], "TESTHASH123")
            self.assertIn("отсутствуют запрошенные серии", call_kwargs["reason"])
            mock_log.assert_called_once()


if __name__ == "__main__":
    unittest.main()
