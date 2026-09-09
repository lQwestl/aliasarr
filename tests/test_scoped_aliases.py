"""
Unit tests for Season/Range-Scoped Aliases and Episode Offset.
"""
from __future__ import annotations

import unittest
from types import SimpleNamespace

from app.services.matcher import match_release, AliasCandidate
from app.services.auto_search import evaluate_torrent_file_priority

try:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.models.db import (
        Base,
        Show,
        Episode,
        Alias,
        EpisodeStatus,
        User,
        UserRole,
    )
    from app.schemas import AliasCreate, AliasUpdate
    from app.api.shows import add_alias, update_alias
    from app.services.decision_engine import DecisionEngine
    from app.services.torznab import TorznabRelease
    from app.services.auto_search import _collect_candidates
    HAS_DB = True
except ImportError:
    HAS_DB = False


class TestScopedAliasesPure(unittest.TestCase):
    """Pure unit tests without external database dependency."""

    def test_matcher_effective_season_and_offset(self):
        """Test that match_release correctly calculates effective_season and effective_episodes with offset."""
        alias_cand = AliasCandidate(
            alias_id=1,
            text="Space Dandy TV-2",
            language="ru",
            priority=1,
            season_number=1,
            episode_start=14,
            episode_end=26,
            episode_offset=13,
        )

        res = match_release(
            release_name="[SubsPlease] Space Dandy TV-2 - 01 (1080p)",
            show_id=42,
            aliases=[alias_cand],
        )
        self.assertTrue(res.matched)
        self.assertEqual(res.show_id, 42)
        self.assertEqual(res.effective_season, 1)
        # Parsed ep 1 + offset 13 = ep 14
        self.assertEqual(res.effective_episodes, [14])
        self.assertIsNotNone(res.alias_candidate)
        self.assertEqual(res.alias_candidate.episode_offset, 13)

    def test_matcher_multi_episode_with_offset(self):
        """Test that multi-episode releases (e.g. 01-03) apply offset to all episodes."""
        alias_cand = AliasCandidate(
            alias_id=2,
            text="Space Dandy 2nd Season",
            language="ru",
            priority=1,
            season_number=1,
            episode_start=14,
            episode_end=26,
            episode_offset=13,
        )

        res = match_release(
            release_name="[Group] Space Dandy 2nd Season - 01-03 [1080p]",
            show_id=42,
            aliases=[alias_cand],
        )
        self.assertTrue(res.matched)
        self.assertEqual(res.effective_season, 1)
        # Parsed eps [1, 2, 3] + offset 13 = [14, 15, 16]
        self.assertEqual(res.effective_episodes, [14, 15, 16])

    def test_evaluate_torrent_file_priority_with_offset(self):
        """Test selective download file prioritizing with offset."""
        wanted_eps = [
            SimpleNamespace(id=1, season_number=1, episode_number=15, absolute_number=None, title="Ep 15")
        ]

        # File 1 (ep 01 -> 14): skip (0)
        prio_01 = evaluate_torrent_file_priority(
            file_name="Space Dandy TV-2 - 01.mkv",
            file_index=0,
            target_episodes=wanted_eps,
            content_type="anime",
            alias_offset=13,
            scoped_season=1,
        )
        self.assertEqual(prio_01, 0)

        # File 2 (ep 02 -> 15): download (1)
        prio_02 = evaluate_torrent_file_priority(
            file_name="Space Dandy TV-2 - 02.mkv",
            file_index=1,
            target_episodes=wanted_eps,
            content_type="anime",
            alias_offset=13,
            scoped_season=1,
        )
        self.assertEqual(prio_02, 1)

        # File 3 (ep 03 -> 16): skip (0)
        prio_03 = evaluate_torrent_file_priority(
            file_name="Space Dandy TV-2 - 03.mkv",
            file_index=2,
            target_episodes=wanted_eps,
            content_type="anime",
            alias_offset=13,
            scoped_season=1,
        )
        self.assertEqual(prio_03, 0)


@unittest.skipUnless(HAS_DB, "Requires sqlalchemy, fastapi, and pydantic")
class TestScopedAliasesDB(unittest.TestCase):
    """Integration tests with database."""

    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()

        self.user = User(
            id=1,
            username="admin",
            role=UserRole.ADMIN,
            is_active=True,
            password_hash="hash",
        )
        self.db.add(self.user)
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def test_alias_scoped_crud(self):
        show = Show(title="Space Dandy", content_type="anime")
        self.db.add(show)
        self.db.commit()

        payload = AliasCreate(
            text="Space Dandy TV-2",
            language="ru",
            priority=2,
            season_number=1,
            episode_start=14,
            episode_end=26,
            episode_offset=13,
        )
        alias_out = add_alias(show.id, payload, db=self.db, current_user=self.user)
        self.assertEqual(alias_out.season_number, 1)
        self.assertEqual(alias_out.episode_start, 14)
        self.assertEqual(alias_out.episode_end, 26)
        self.assertEqual(alias_out.episode_offset, 13)

        update_payload = AliasUpdate(
            text="Space Dandy 2nd Season",
            episode_offset=13,
            episode_start=14,
            episode_end=26,
        )
        updated = update_alias(show.id, alias_out.id, update_payload, db=self.db, current_user=self.user)
        self.assertEqual(updated.text, "Space Dandy 2nd Season")
        self.assertEqual(updated.episode_offset, 13)

    def test_decision_engine_with_offset(self):
        show = Show(title="Space Dandy", content_type="anime")
        self.db.add(show)
        self.db.flush()

        for ep_i in range(1, 27):
            ep = Episode(
                show_id=show.id,
                season_number=1,
                episode_number=ep_i,
                status=EpisodeStatus.WANTED,
            )
            self.db.add(ep)
        self.db.commit()

        alias_cand = AliasCandidate(
            alias_id=10,
            text="Space Dandy 2nd Season",
            season_number=1,
            episode_start=14,
            episode_end=26,
            episode_offset=13,
        )

        engine = DecisionEngine(self.db)
        release = TorznabRelease(
            title="[Erai-raws] Space Dandy 2nd Season - 01 [1080p]",
            guid="test-guid-1",
            download_url="http://fake/1.torrent",
            seeders=10,
        )

        decision = engine.evaluate_release(release, show, alias_candidate=alias_cand)
        self.assertTrue(decision.approved, f"Decision rejected: {decision.rejection_reason}")
        self.assertIn(14, decision.matched_episode_ids_or_numbers)


if __name__ == "__main__":
    unittest.main()
