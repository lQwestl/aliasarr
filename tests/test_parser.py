from __future__ import annotations

import sys
import os
import unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.parser import parse_episode, ReleaseKind, normalize


class TestParser(unittest.TestCase):
    def test_sxxexx_basic(self):
        r = parse_episode("Show.Name.S01E05.1080p.WEB-DL")
        self.assertEqual(r.kind, ReleaseKind.EPISODE)
        self.assertEqual(r.season, 1)
        self.assertEqual(r.episodes, [5])

    def test_sxxexx_multi_range(self):
        r = parse_episode("Show.Name.S01E05-E07.1080p")
        self.assertEqual(r.season, 1)
        self.assertEqual(r.episodes, [5, 6, 7])
        self.assertTrue(r.is_range)


    def test_1x05_format(self):
        r = parse_episode("Show Name 1x05 HDTV")
        self.assertEqual(r.season, 1)
        self.assertEqual(r.episodes, [5])

    def test_e05_format(self):
        r = parse_episode("Show Name E05")
        self.assertEqual(r.episodes, [5])

    def test_ep05_format(self):
        r = parse_episode("Show Name EP05")
        self.assertEqual(r.episodes, [5])

    def test_lone_number_05(self):
        r = parse_episode("Шоу Имя - серия 05")
        self.assertIn(5, r.episodes)

    def test_lone_number_5(self):
        r = parse_episode("Show Name 5")
        self.assertIn(5, r.episodes)

    def test_bracket_range(self):
        r = parse_episode("Show Name [01-06] complete")
        self.assertEqual(r.episodes, list(range(1, 7)))
        self.assertTrue(r.is_range)

    def test_range_iz_n(self):
        r = parse_episode("Show Name 01-06 из 12")
        self.assertEqual(r.episodes, list(range(1, 7)))

    def test_dash_absolute(self):
        r = parse_episode("Anime Name - 05 [1080p]")
        self.assertEqual(r.kind, ReleaseKind.ABSOLUTE)
        self.assertEqual(r.episodes, [5])

    def test_year_not_parsed_as_range(self):
        r = parse_episode("Show Name 2024-2025 Complete Series")
        self.assertNotEqual(r.episodes, list(range(2024, 2026)))

    def test_season_pack(self):
        r = parse_episode("Show Name S02 Complete 1080p")
        self.assertEqual(r.kind, ReleaseKind.SEASON_PACK)
        self.assertEqual(r.season, 2)

    def test_acceptance_case_villager_999(self):
        name = "Крестьянин.девятьсот.девяносто.девятого.уровня..E01-E06.Lv999.no.Murabito...[1-6]"
        r = parse_episode(name)
        self.assertEqual(r.kind, ReleaseKind.EPISODE)
        self.assertEqual(r.episodes, [1, 2, 3, 4, 5, 6])
        self.assertTrue(r.is_range)

    def test_resolution_not_confused_with_number(self):
        r = parse_episode("Show Name S01E05 1080p x264")
        self.assertEqual(r.season, 1)
        self.assertEqual(r.episodes, [5])

    def test_all_formats_give_episode_5(self):
        variants = [
            "Show S01E05",
            "Show 1x05",
            "Show E05",
            "Show 05",
            "Show 5",
        ]
        for v in variants:
            r = parse_episode(v)
            self.assertIn(5, r.episodes, f"failed for variant: {v} -> {r}")

    def test_normalize_strips_noise(self):
        n = normalize("Show.Name.1080p.x264.WEB-DL.AAC")
        self.assertNotIn("1080p", n)
        self.assertNotIn("x264", n)

    def test_anime_season_2_with_episodes(self):
        # 2nd Season - 01 / 02
        r1 = parse_episode("[Erai-raws] Jujutsu Kaisen 2nd Season - 01 [1080p].mkv")
        self.assertEqual(r1.season, 2)
        self.assertEqual(r1.episodes, [1])

        r2 = parse_episode("[Erai-raws] Jujutsu Kaisen 2nd Season - 02 [1080p].mkv")
        self.assertEqual(r2.season, 2)
        self.assertEqual(r2.episodes, [2])

        # S2 - 02
        r3 = parse_episode("[Judas] Boku no Hero Academia S2 - 02 [1080p].mkv")
        self.assertEqual(r3.season, 2)
        self.assertEqual(r3.episodes, [2])

        # Season 2 - 02
        r4 = parse_episode("[AnimeRG] Attack on Titan Season 2 - 02 (1080p).mkv")
        self.assertEqual(r4.season, 2)
        self.assertEqual(r4.episodes, [2])

        # S2 - 01
        r5 = parse_episode("[SubsPlease] Mushoku Tensei S2 - 01 (1080p) [12345678].mkv")
        self.assertEqual(r5.season, 2)
        self.assertEqual(r5.episodes, [1])

        # 2nd Season [01-12]
        r6 = parse_episode("Anime Title 2nd Season [01-12] [1080p]")
        self.assertEqual(r6.season, 2)
        self.assertEqual(r6.episodes, list(range(1, 13)))

        # Russian: 2 сезон - 05
        r7 = parse_episode("Anime Title 2 сезон - 05.mkv")
        self.assertEqual(r7.season, 2)
        self.assertEqual(r7.episodes, [5])

        # Roman: II сезон - 03
        r8 = parse_episode("Anime Title II сезон - 03.mkv")
        self.assertEqual(r8.season, 2)
        self.assertEqual(r8.episodes, [3])

        # Season pack without episode numbers:
        r9 = parse_episode("Anime Title 2nd Season")
        self.assertEqual(r9.kind, ReleaseKind.SEASON_PACK)
        self.assertEqual(r9.season, 2)
        self.assertEqual(r9.episodes, [])

        # Discrete episode list after season:
        r10 = parse_episode("Робоцып / Robot Chicken / 5 сезон / 0 , 10, 19 серия (19) (Крис МакКэй / Chris McKay) [2011, США, Мультсериал, комедия, пародия, кукольный, DVDRip] MVO")
        self.assertEqual(r10.kind, ReleaseKind.EPISODE)
        self.assertEqual(r10.season, 5)
        self.assertEqual(r10.episodes, [0, 10, 19])

        r11 = parse_episode("Show Title Season 2 / 01, 02, 05, 08")
        self.assertEqual(r11.kind, ReleaseKind.EPISODE)
        self.assertEqual(r11.season, 2)
        self.assertEqual(r11.episodes, [1, 2, 5, 8])

    def test_hell_mode_season_2_episodes(self):
        for i in range(1, 8):
            fn = f"Hell_Mode_Yarikomizuki_no_Gamer_wa_Hai_Sette_2_[0{i}]_[HEVC].mkv"
            p = parse_episode(fn)
            self.assertEqual(p.season, 2, f"Failed season for {fn}")
            self.assertEqual(p.episodes, [i], f"Failed episode for {fn}")
            self.assertEqual(p.kind, ReleaseKind.EPISODE)

        torrent_title = "Hell Mode Yarikomizuki no Gamer wa Hai Sette 2 - AniLiberty [WEBRip 1080p HEVC]"
        p_pack = parse_episode(torrent_title)
        self.assertEqual(p_pack.season, 2)
        self.assertEqual(p_pack.episodes, [])
        self.assertEqual(p_pack.kind, ReleaseKind.SEASON_PACK)


    def test_slime_season_4_parts(self):
        # Anime with "4th Season Part 1 - 04"
        for i in range(1, 13):
            fn = f"Tensei shitara Slime Datta Ken 4th Season Part 1 - {i:02d} [WEB-DL 1080p].mkv"
            p = parse_episode(fn)
            self.assertEqual(p.season, 4, f"Failed season for {fn}")
            self.assertEqual(p.episodes, [i], f"Failed episode for {fn}")
            self.assertEqual(p.kind, ReleaseKind.EPISODE)

        torrent_pack = "Tensei shitara Slime Datta Ken 4th Season Part 1 [WEB-DL 1080p]"
        p_pack = parse_episode(torrent_pack)
        self.assertEqual(p_pack.season, 4)
        self.assertEqual(p_pack.episodes, [])
        self.assertEqual(p_pack.kind, ReleaseKind.SEASON_PACK)

    def test_anime_parts_and_cours(self):
        p1 = parse_episode("Season 4 Part 1 - 02 [1080p].mkv")
        self.assertEqual(p1.season, 4)
        self.assertEqual(p1.episodes, [2])

        p2 = parse_episode("Сезон 4 Часть 2 - 05 [1080p].mkv")
        self.assertEqual(p2.season, 4)
        self.assertEqual(p2.episodes, [5])

        p3 = parse_episode("Overlord IV Part 1 - 05 [1080p].mkv")
        self.assertEqual(p3.season, 4)
        self.assertEqual(p3.episodes, [5])

    def test_season_with_iz_range_partial_pack(self):
        # 1. Clevatess Season 2 with [1-7 из 13]
        t1 = "Клеватесс (ТВ-2): Король демонических зверей | Clevatess Season 2 [TV] [1-7 из 13] [2026] [WEBRip 1080p]"
        p1 = parse_episode(t1)
        self.assertEqual(p1.season, 2)
        self.assertEqual(p1.episodes, [1, 2, 3, 4, 5, 6, 7])
        self.assertEqual(p1.kind, ReleaseKind.EPISODE)

        # 2. Re:Zero Season 4 with [1-12 из 19]
        t2 = "Re:Zero (S4) / Re:Zero kara Hajimeru Isekai Seikatsu 4 [TV] [1-12 из 19] [WEB-DL 1080p]"
        p2 = parse_episode(t2)
        self.assertEqual(p2.season, 4)
        self.assertEqual(p2.episodes, list(range(1, 13)))
        self.assertEqual(p2.kind, ReleaseKind.EPISODE)

        # 3. Mushoku Tensei Season 3 with [01-08 из 14]
        t3 = "Mushoku Tensei Season 3 [TV] [01-08 из 14] [WEB-DL 1080p]"
        p3 = parse_episode(t3)
        self.assertEqual(p3.season, 3)
        self.assertEqual(p3.episodes, list(range(1, 9)))
        self.assertEqual(p3.kind, ReleaseKind.EPISODE)

    def test_specials_and_ova_parsing(self):
        # OVA with hyphen
        p1 = parse_episode("Tensei shitara Slime Datta Ken OVA-1.avi")
        self.assertEqual(p1.season, 0)
        self.assertEqual(p1.episodes, [1])

        p2 = parse_episode("Tensei shitara Slime Datta Ken OVA-5.avi")
        self.assertEqual(p2.season, 0)
        self.assertEqual(p2.episodes, [5])

        # OVA range
        p3 = parse_episode("Attack on Titan OVA 01-08 [BDRip].mkv")
        self.assertEqual(p3.season, 0)
        self.assertEqual(p3.episodes, list(range(1, 9)))
        self.assertTrue(p3.is_range)

        # SP code
        p4 = parse_episode("Chained Soldier SP02 [BDRip 1080p].mkv")
        self.assertEqual(p4.season, 0)
        self.assertEqual(p4.episodes, [2])

        # Season Special
        p5 = parse_episode("Tensei Shitara Slime Datta Ken 2 sp.avi")
        self.assertEqual(p5.season, 0)
        self.assertEqual(p5.episodes, [1])

    def test_e_of_n_formats_and_vermeil(self):
        # 1. Exact user example: Vermeil in Gold [E12 of 12]
        title = "Вермейл в золотом / Kinsou no Vermeil: Gakeppuchi Majutsushi wa Saikyou no Yakusai to Mahou Sekai o (wo) Tsukisusumu / Vermeil in Gold (Наоя Такаси) [TV] [E12 of 12] [RUS(ext), ENG, JAP+Sub] [2022, комедия, романтика, этти, фэнтези, BDRip] [1080p]"
        p = parse_episode(title)
        self.assertEqual(p.kind, ReleaseKind.EPISODE)
        self.assertEqual(p.episodes, list(range(1, 13)))
        self.assertTrue(p.is_range)

        # 2. [E12 of E12], [12 of 12], [E12 из 12], [12 из 12], [E12 из E12]
        for t in [
            "Anime Title [E12 of E12]",
            "Anime Title [12 of 12]",
            "Anime Title [E12 из 12]",
            "Anime Title [12 из 12]",
            "Anime Title [E12 из E12]",
            "Anime Title [EP12 of 12]",
            "Anime Title [Ep.12 of 12]",
            "Anime Title [Эп.12 из 12]",
            "Anime Title [E12/12]",
            "Anime Title [12/12]",
            "Anime Title [E12/E12]",
            "Anime Title (E12 of 12)",
            "Anime Title (12 of 12)",
            "Anime Title (12 из 12)",
            "Anime Title E12 of 12",
            "Anime Title 12 of 12",
            "Anime Title E12 из 12",
            "Anime Title 12 из 12",
        ]:
            res = parse_episode(t)
            self.assertEqual(res.episodes, list(range(1, 13)), f"Failed for title: {t}")
            self.assertTrue(res.is_range, f"Expected range for title: {t}")

        # 3. Partial batches: [E06 of 12], [06 of 12], [6 из 12]
        for t in ["Anime Title [E06 of 12]", "Anime Title [06 of 12]", "Anime Title [6 из 12]"]:
            res = parse_episode(t)
            self.assertEqual(res.episodes, list(range(1, 7)), f"Failed for partial batch: {t}")
            self.assertTrue(res.is_range)

        # 4. Explicit ranges with of/из: [E01-E12 of 12], [01-12 of 12], [E07-E12 of 12]
        r_full = parse_episode("Anime Title [E01-E12 of 12]")
        self.assertEqual(r_full.episodes, list(range(1, 13)))
        self.assertTrue(r_full.is_range)

        r_part = parse_episode("Anime Title [E07-E12 of 12]")
        self.assertEqual(r_part.episodes, list(range(7, 13)))
        self.assertTrue(r_part.is_range)

        # 5. Long series up to 9999 episodes (e.g. E0012 of E0012, E100 of 100, E1234 of 1234)
        r_lead_zero = parse_episode("Anime Title [E0012 of E0012]")
        self.assertEqual(r_lead_zero.episodes, list(range(1, 13)))

        r_100 = parse_episode("Anime Title [E100 of 100]")
        self.assertEqual(r_100.episodes, list(range(1, 101)))
        self.assertEqual(len(r_100.episodes), 100)

        r_9999 = parse_episode("Anime Title [E9999 of 9999]")
        self.assertEqual(r_9999.episodes, list(range(1, 10000)))
        self.assertEqual(len(r_9999.episodes), 9999)

        # 6. With season prefix: S02 [E12 of 12], Season 2 [E12 of 12], 2nd Season [E12 of 12]
        r_s2_1 = parse_episode("Anime Title S02 [E12 of 12]")
        self.assertEqual(r_s2_1.season, 2)
        self.assertEqual(r_s2_1.episodes, list(range(1, 13)))

        r_s2_2 = parse_episode("Anime Title Season 2 [E12 of 12]")
        self.assertEqual(r_s2_2.season, 2)
        self.assertEqual(r_s2_2.episodes, list(range(1, 13)))

        r_s2_3 = parse_episode("Anime Title 2nd Season [E12 of 12]")
        self.assertEqual(r_s2_3.season, 2)
        self.assertEqual(r_s2_3.episodes, list(range(1, 13)))

        r_s2_4 = parse_episode("Anime Title II сезон [12 из 12]")
        self.assertEqual(r_s2_4.season, 2)
        self.assertEqual(r_s2_4.episodes, list(range(1, 13)))

        # 7. Complex anime release with slash title separator and 2nd Season / E01-E09
        r_s2_5 = parse_episode("Адский режим: Хардкорный геймер отправляется в другой мир на высоком уровне сложности 2 / E01-E09 Hell Mode- Yarikomizuki no Gamer wa Hai Settei no Isekai de Musou suru 2nd Season - AniLiberty.TOP [WEBRip 1080p][AVC][1-9]  RUS")
        self.assertEqual(r_s2_5.season, 2)
        self.assertEqual(r_s2_5.episodes, list(range(1, 10)))
        self.assertTrue(r_s2_5.is_range)

    def test_russian_and_translit_season_episode_formats(self):
        # 1. Translit Robot Chicken format
        r1 = parse_episode("Robocip.(1.sezon.06.seriya.iz.20).2005.XviD.DVDRip.avi")
        self.assertEqual(r1.season, 1)
        self.assertEqual(r1.episodes, [6])
        self.assertEqual(r1.kind, ReleaseKind.EPISODE)

        r2 = parse_episode("Robocip.(1.sezon.14.seriya.iz.20).2005.XviD.DVDRip.avi")
        self.assertEqual(r2.season, 1)
        self.assertEqual(r2.episodes, [14])

        r3 = parse_episode("Robocip.(2.sezon.19.seriya.iz.20).2005-2006.XviD.DVDRip.avi")
        self.assertEqual(r3.season, 2)
        self.assertEqual(r3.episodes, [19])

        r4 = parse_episode("Robocip.(3.sezon.06.seriya.iz.20).2007-2008.XviD.DVDRip.avi")
        self.assertEqual(r4.season, 3)
        self.assertEqual(r4.episodes, [6])

        r5 = parse_episode("Robocip.(4.sezon.04.seriya.iz.20).2008-2009.XviD.DVDRip.avi")
        self.assertEqual(r5.season, 4)
        self.assertEqual(r5.episodes, [4])

        r6 = parse_episode("Robocip.(1.sezon.01-20.serii.iz.20).2005.XviD.DVDRip.avi")
        self.assertEqual(r6.season, 1)
        self.assertEqual(r6.episodes, list(range(1, 21)))
        self.assertTrue(r6.is_range)

        # 2. Cyrillic format
        r7 = parse_episode("Робоцып (1 сезон 06 серия из 20) 2005.avi")
        self.assertEqual(r7.season, 1)
        self.assertEqual(r7.episodes, [6])

        # 3. Multi-season translit pack
        r8 = parse_episode("Robocip.(1-4.sezoni.plus.Robocip.Zvezdnie.voiny.1-2.epizodi).2005-2009.XviD.DVDRip")
        self.assertEqual(r8.kind, ReleaseKind.SEASON_PACK)
        self.assertEqual(r8.seasons, [1, 2, 3, 4])


    def test_numbered_specials_and_ovas(self):
        # 1. Leading number with special in name
        r1 = parse_episode("13 Robot Chicken's ATM Christmas Special.mkv")
        self.assertEqual(r1.kind, ReleaseKind.EPISODE)
        self.assertEqual(r1.episodes, [13])

        r2 = parse_episode("00 Born Again Virgin Christmas Special.mkv")
        self.assertEqual(r2.kind, ReleaseKind.EPISODE)
        self.assertEqual(r2.episodes, [0])

        r3 = parse_episode("20 The Robot Chicken Lots of Holidays Special.mkv")
        self.assertEqual(r3.kind, ReleaseKind.EPISODE)
        self.assertEqual(r3.episodes, [20])

        r4 = parse_episode("16 Bitch Pudding Special.mkv")
        self.assertEqual(r4.kind, ReleaseKind.EPISODE)
        self.assertEqual(r4.episodes, [16])

        r5 = parse_episode("07 The Robot Chicken Christmas Special X-Mas United.mkv")
        self.assertEqual(r5.kind, ReleaseKind.EPISODE)
        self.assertEqual(r5.episodes, [7])

        # 2. Season episode with special in title
        r6 = parse_episode("Robot.Chicken.S11E00.The.Bleepin.Robot.Chicken.Archie.Comics.Special.mkv")
        self.assertEqual(r6.kind, ReleaseKind.EPISODE)
        self.assertEqual(r6.season, 11)
        self.assertEqual(r6.episodes, [0])

        r7 = parse_episode("Robot.Chicken.S11E21.Self-Discovery.Special.mkv")
        self.assertEqual(r7.kind, ReleaseKind.EPISODE)
        self.assertEqual(r7.season, 11)
        self.assertEqual(r7.episodes, [21])

        # 3. Whole OVA packs without episode numbers
        r8 = parse_episode("Attack on Titan OVA")
        self.assertEqual(r8.kind, ReleaseKind.SEASON_PACK)
        self.assertEqual(r8.season, 0)
        self.assertEqual(r8.episodes, [])

        r9 = parse_episode("Tensei Shitara Slime Datta Ken OAD [BDRip 1920x1080 HEVC FLAC]_rev")
        self.assertEqual(r9.kind, ReleaseKind.SEASON_PACK)
        self.assertEqual(r9.season, 0)
        self.assertEqual(r9.episodes, [])

        # 4. Numbered OVA/SP files
        r10 = parse_episode("Frieren Special 02.mkv")
        self.assertEqual(r10.kind, ReleaseKind.EPISODE)
        self.assertEqual(r10.episodes, [2])

        r11 = parse_episode("KonoSuba OVA 1.mkv")
        self.assertEqual(r11.kind, ReleaseKind.EPISODE)
        self.assertEqual(r11.episodes, [1])

    def test_anime_tv_seasons_and_multi_seasons(self):
        cases = [
            ("Re:Zero (ТВ-4) [1080p]", 4, ReleaseKind.SEASON_PACK, [4]),
            ("Re:Zero [ТВ-4] [1080p]", 4, ReleaseKind.SEASON_PACK, [4]),
            ("Re:Zero ТВ-4 [1080p]", 4, ReleaseKind.SEASON_PACK, [4]),
            ("Re:Zero (TV-4) [1080p]", 4, ReleaseKind.SEASON_PACK, [4]),
            ("Re:Zero TV-4 [1080p]", 4, ReleaseKind.SEASON_PACK, [4]),
            ("Re:Zero 4 сезон [1080p]", 4, ReleaseKind.SEASON_PACK, [4]),
            ("Re:Zero 4-й сезон [1080p]", 4, ReleaseKind.SEASON_PACK, [4]),
            ("Re:Zero IV сезон [1080p]", 4, ReleaseKind.SEASON_PACK, [4]),
            ("Re:Zero 1-4 сезон [1080p]", 1, ReleaseKind.SEASON_PACK, [1, 2, 3, 4]),
            ("Re:Zero 1 - 4 сезон [1080p]", 1, ReleaseKind.SEASON_PACK, [1, 2, 3, 4]),
            ("Re:Zero Сезоны 1-4 [1080p]", 1, ReleaseKind.SEASON_PACK, [1, 2, 3, 4]),
            ("Re:Zero S01-S04 [1080p]", 1, ReleaseKind.SEASON_PACK, [1, 2, 3, 4]),
            ("Re:Zero [S1-4] [1080p]", 1, ReleaseKind.SEASON_PACK, [1, 2, 3, 4]),
            ("Re:Zero (S1-4) [1080p]", 1, ReleaseKind.SEASON_PACK, [1, 2, 3, 4]),
            ("Re:Zero (ТВ-1-4) [BDRip]", 1, ReleaseKind.SEASON_PACK, [1, 2, 3, 4]),
            ("Re:Zero (ТВ-1, 2) [BDRip]", 1, ReleaseKind.SEASON_PACK, [1, 2]),
        ]
        for name, exp_s, exp_kind, exp_seasons in cases:
            p = parse_episode(name)
            self.assertEqual(p.kind, exp_kind, f"Failed kind for {name}")
            self.assertEqual(p.seasons, exp_seasons, f"Failed seasons for {name}")

        p_ep = parse_episode("Re:Zero (ТВ-4) [E01-E08 of 16] [1080p]")
        self.assertEqual(p_ep.kind, ReleaseKind.EPISODE)
        self.assertEqual(p_ep.season, 4)
        self.assertEqual(p_ep.episodes, list(range(1, 9)))

    def test_ongoing_bracket_ranges_with_greater_than_and_symbols(self):
        # 1. [01-12 из >24]
        t1 = "О моём перерождении в слизь (S4, часть 1) / Tensei Shitara Slime Datta Ken 4th Season / That Time I Got Reincarnated as a Slime [TV] [01-12 из >24] [RUS(int), JAP+Sub] [2026, приключения, комедия, фэнтези, WEBRip] [HWP]"
        p1 = parse_episode(t1)
        self.assertEqual(p1.season, 4)
        self.assertEqual(p1.part, 1)
        self.assertEqual(p1.episodes, list(range(1, 13)))

        # 2. [1-10 из 26]
        t2 = "Изгнанный реинкарнированный тяжёлый рыцарь не имеет себе равных в знаниях игры | Tsuihou sareta Tensei Juukishi (Juu Kishi) wa Game Chishiki de Musou suru | The Exiled Heavy Knight Knows How to Game the System | Как обмануть систему [TV] [1-10 из 26] [2026] [фэнтези] [WEB-DL] [1080p] [Дублированный, (JAP+SUB)]"
        p2 = parse_episode(t2)
        self.assertEqual(p2.episodes, list(range(1, 11)))

        # 3. [01-08 из XX]
        t3 = "Табакошка / Yani Neko / Chainsmoker Cat [TV] [01-08 из XX] [RUS(int), JAP+Sub] [2026, Сэйнэн, Комедия, WEB-DL] [1080p]"
        p3 = parse_episode(t3)
        self.assertEqual(p3.episodes, list(range(1, 9)))


if __name__ == "__main__":
    unittest.main()



