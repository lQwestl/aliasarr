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

    def test_best_alias_match_disambiguates_split_cour_parts(self):
        """Test that best_alias_match picks Part 2 alias for S2/TV-2 releases and Part 1 for S1."""
        from app.services.matcher import best_alias_match

        alias_part1_ru = AliasCandidate(
            alias_id=1,
            text="Космический Денди",
            season_number=1,
            episode_start=1,
            episode_end=13,
            episode_offset=0,
        )
        alias_part1_en = AliasCandidate(
            alias_id=2,
            text="Space Dandy",
            season_number=1,
            episode_start=1,
            episode_end=13,
            episode_offset=0,
        )
        alias_part2_ru = AliasCandidate(
            alias_id=3,
            text="Космический Денди (ТВ-2)",
            season_number=1,
            episode_start=14,
            episode_end=26,
            episode_offset=13,
        )
        alias_part2_en = AliasCandidate(
            alias_id=4,
            text="Space Dandy 2",
            season_number=1,
            episode_start=14,
            episode_end=26,
            episode_offset=13,
        )

        all_aliases = [alias_part1_ru, alias_part1_en, alias_part2_ru, alias_part2_en]

        # Release S2 / 2nd season
        rel_s2 = "[AniLibria] Космический Денди (S2) / Space Dandy 2 [13 из 13] [WEBRip 1080p]"
        best_s2, score_s2 = best_alias_match(rel_s2, all_aliases)
        self.assertIsNotNone(best_s2)
        self.assertIn(best_s2.alias_id, (3, 4))
        self.assertEqual(best_s2.episode_offset, 13)

        # Release S1
        rel_s1 = "[AniLibria] Космический Денди (S1) / Space Dandy [13 из 13] [WEBRip 1080p]"
        best_s1, score_s1 = best_alias_match(rel_s1, all_aliases)
        self.assertIsNotNone(best_s1)
        self.assertIn(best_s1.alias_id, (1, 2))
        self.assertEqual(best_s1.episode_offset, 0)

    def test_reconciliation_evaluates_part_2_files_with_offset(self):
        """Test evaluate_torrent_file_priority matches files in S2 pack to episodes 14..26."""
        all_eps = [
            SimpleNamespace(id=i, season_number=1, episode_number=i, absolute_number=None, title=f"Ep {i}")
            for i in range(1, 27)
        ]
        target_wanted = [ep for ep in all_eps if ep.episode_number >= 14]

        matched_eps = []
        for i in range(1, 14):
            f_name = f"[AniLibria] Space Dandy 2 - {i:02d} [1080p].mkv"
            prio = evaluate_torrent_file_priority(
                file_name=f_name,
                file_index=i - 1,
                target_episodes=target_wanted,
                content_type="anime",
                torrent_name="[AniLibria] Космический Денди (S2) / Space Dandy 2 [13 из 13]",
                all_show_episodes=all_eps,
                out_matched_episodes=matched_eps,
                alias_offset=13,
                scoped_season=1,
            )
            self.assertGreater(prio, 0, f"File {f_name} should have priority > 0")

        self.assertEqual(len(matched_eps), 13)
        matched_numbers = [m.episode_number for m in matched_eps]
        self.assertEqual(matched_numbers, list(range(14, 27)))


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

    def test_clear_auto_rejected_blocklist(self):
        """Test that clear_auto_rejected_for_show only clears automated empty-match blocks."""
        from app.models.db import Blocklist
        from app.services.blocklist_service import clear_auto_rejected_for_show

        show = Show(title="Space Dandy", content_type="anime")
        self.db.add(show)
        self.db.commit()

        # 1. Automated rejection
        auto_block = Blocklist(
            show_id=show.id,
            release_title="[AniLibria] Space Dandy 2",
            torrent_hash="6ba484cb11111111111111111111111111111111",
            reason="Раздача не содержит ни одной нужной серии для тайтла",
        )
        # 2. Manual user rejection
        manual_block = Blocklist(
            show_id=show.id,
            release_title="[BadGroup] Space Dandy 2",
            torrent_hash="823ce92b22222222222222222222222222222222",
            reason="Плохое качество перевода",
        )
        self.db.add_all([auto_block, manual_block])
        self.db.commit()

        # Clear auto rejected
        cleared = clear_auto_rejected_for_show(self.db, show.id)
        self.assertEqual(cleared, 1)

        remaining = self.db.query(Blocklist).filter(Blocklist.show_id == show.id).all()
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0].reason, "Плохое качество перевода")


if __name__ == "__main__":
    unittest.main()

