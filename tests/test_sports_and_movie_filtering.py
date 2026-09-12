import unittest
from app.services.matcher import (
    AliasCandidate,
    match_release,
    best_alias_match,
    is_sports_release,
)


class TestSportsAndMovieFiltering(unittest.TestCase):
    def test_is_sports_release_keywords(self):
        """Test that sports broadcast titles are detected and filtered."""
        sports_titles = [
            "Лига Чемпионов 2024-2025 / 3-й квалификационный раунд / Первые матчи / Карабах - Лудогорец / Duna HD [06.08.2024, Футбол]",
            "Футбол. Чемпионат Европы 2024. Финал. Испания - Англия (14.07.2024) [1080p, 50fps, HDTV]",
            "UFC 305: Du Plessis vs. Adesanya [17.08.2024, ММА, WEB-DL 1080p]",
            "Formula 1 2024. Этап 14. Гран-при Бельгии. Гонка [28.07.2024, Автоспорт, 1080p 50fps]",
            "Хоккей. КХЛ 2024/2025. Регулярный чемпионат. СКА - ЦСКА [HDTV 1080i]",
            "НБА. Финал 2024. Матч 5. Бостон Селтикс - Даллас Маверикс [1080p, 60fps]",
            "Биатлон. Кубок мира 2023-2024. 9-й этап. Масс-старт [Спорт, HDTV]",
        ]
        for title in sports_titles:
            self.assertTrue(
                is_sports_release(title),
                f"Expected '{title}' to be identified as sports release",
            )

    def test_is_sports_release_torznab_category(self):
        """Test that Torznab category 5060 (TV/Sport) is identified as sports."""
        self.assertTrue(is_sports_release("Normal Looking Title", categories=[5060]))
        self.assertTrue(is_sports_release("Another Title", categories=[2000, 5060]))
        self.assertFalse(is_sports_release("Dune: Part Two (2024) 1080p WEB-DL", categories=[2000]))

    def test_dune_3_soccer_rejection(self):
        """
        Verify that Dune 3 (2026) rejects the Rutracker soccer match that was falsely matched.
        """
        soccer_title = "Лига Чемпионов 2024-2025 / 3-й квалификационный раунд / Первые матчи / Карабах - Лудогорец / Duna HD [06.08.2024, Футбол]"
        dune_aliases = [
            AliasCandidate(alias_id=1, text="Dune: Part Three", language="en", priority=0),
            AliasCandidate(alias_id=2, text="Дюна: Часть третья", language="ru", priority=0),
            AliasCandidate(alias_id=3, text="Duna 3", language="hu", priority=5),
        ]

        # 1. match_release must reject the sports release
        res = match_release(
            soccer_title,
            show_id=100,
            aliases=dune_aliases,
            content_type="movie",
            show_year=2026,
            categories=[5000],
        )
        self.assertFalse(res.matched, "Soccer broadcast should not match Dune 3")

    def test_future_movie_year_strict_check(self):
        """
        Verify that future/unreleased movies reject releases from earlier years.
        """
        dune_aliases = [
            AliasCandidate(alias_id=1, text="Dune: Part Three", language="en", priority=0),
            AliasCandidate(alias_id=2, text="Duna 3", language="hu", priority=5),
        ]

        # Year range (2024-2025) should be rejected for a movie
        res_range = match_release(
            "Duna 3 2024-2025 1080p HDTV",
            show_id=100,
            aliases=dune_aliases,
            content_type="movie",
            show_year=2026,
        )
        self.assertFalse(res_range.matched, "Year range should be rejected for movies")

        # Past year release (2024 or 2025) for a 2027 film should be rejected
        res_past = match_release(
            "Dune: Part Three (2024) 1080p WEB-DL",
            show_id=100,
            aliases=dune_aliases,
            content_type="movie",
            show_year=2027,
        )
        self.assertFalse(res_past.matched, "Past year release should not match unreleased 2027 movie")

        # Exact year release (2027) should match
        res_correct = match_release(
            "Dune: Part Three (2027) 1080p WEB-DL",
            show_id=100,
            aliases=dune_aliases,
            content_type="movie",
            show_year=2027,
        )
        self.assertTrue(res_correct.matched, "Exact year release should match")

    def test_movie_alias_part_number_preservation(self):
        """
        Ensure that 'Duna 3' alias does not match a release titled 'Duna HD' or 'Duna'.
        """
        duna3_aliases = [
            AliasCandidate(alias_id=1, text="Duna 3", language="hu", priority=1),
        ]
        alias, score = best_alias_match("Duna HD 1080p", duna3_aliases, threshold=80, content_type="movie")
        self.assertIsNone(alias, f"Expected Duna HD to NOT match Duna 3, got score {score}")

        alias_match, score_match = best_alias_match("Duna 3 (2026) 1080p", duna3_aliases, threshold=80, content_type="movie")
        self.assertIsNotNone(alias_match)
        self.assertGreaterEqual(score_match, 80)

    def test_valid_movie_matching(self):
        """Ensure legitimate movie releases continue to match correctly."""
        avatar_aliases = [
            AliasCandidate(alias_id=1, text="Avatar: The Way of Water", language="en", priority=0),
            AliasCandidate(alias_id=2, text="Аватар: Путь воды", language="ru", priority=0),
            AliasCandidate(alias_id=3, text="Avatar 2", language="en", priority=5),
        ]
        res = match_release(
            "Avatar.The.Way.of.Water.2022.2160p.UHD.HDR.BluRay.x265",
            show_id=2,
            aliases=avatar_aliases,
            content_type="movie",
            show_year=2022,
        )
        self.assertTrue(res.matched)
        self.assertEqual(res.parsed.kind.value, "episode")
        self.assertEqual(res.parsed.episodes, [])


if __name__ == "__main__":
    unittest.main()
