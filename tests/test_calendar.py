from __future__ import annotations

import datetime as dt
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch


def _calendar_status(show, episode, air_date, entry_type: str) -> str:
    if entry_type == "premiere":
        return "premiere"
    if show and not show.monitored:
        return "unmonitored"
    if episode is not None:
        if episode.status == "downloaded":
            return "downloaded"
        if episode.status == "downloading":
            return "downloading"
        if air_date and air_date.date() == dt.datetime.utcnow().date():
            return "on_air"
        if episode.status == "missing":
            return "missing"
        if episode.status == "unaired":
            return "unaired"
    if air_date and air_date.date() == dt.datetime.utcnow().date():
        return "on_air"
    if air_date and air_date > dt.datetime.utcnow():
        return "unaired"
    return "missing"


def _build_ical_feed(entries, cal_name: str = "Aliasarr") -> str:
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Aliasarr//Calendar Feed//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{cal_name}",
        "X-WR-TIMEZONE:UTC",
    ]
    now_str = dt.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    for e in entries:
        if not e.air_date:
            continue
        dt_start = e.air_date.strftime("%Y%m%dT%H%M%SZ")
        dt_end = (e.air_date + dt.timedelta(hours=1)).strftime("%Y%m%dT%H%M%SZ")
        uid = f"aliasarr-{e.content_type}-{e.show_id}-{e.episode_id or 'prem'}@aliasarr"

        summary = e.show_title
        if e.content_type != "movie" and getattr(e, "season", None) is not None and getattr(e, "episode", None) is not None:
            summary += f" - S{e.season:02d}E{e.episode:02d}"
            if getattr(e, "title", None):
                summary += f" - {e.title}"
        elif getattr(e, "year", None):
            summary += f" ({e.year})"

        desc = f"Status: {e.status}\\nContent: {e.content_type}"
        if getattr(e, "overview", None):
            clean_ov = e.overview.replace("\n", " ").replace("\r", "")
            desc += f"\\n\\n{clean_ov}"

        lines.append("BEGIN:VEVENT")
        lines.append(f"UID:{uid}")
        lines.append(f"DTSTAMP:{now_str}")
        lines.append(f"DTSTART:{dt_start}")
        lines.append(f"DTEND:{dt_end}")
        lines.append(f"SUMMARY:{summary}")
        lines.append(f"DESCRIPTION:{desc}")
        lines.append(f"CATEGORIES:{e.content_type.capitalize()},Aliasarr")
        lines.append("END:VEVENT")

    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"


class TestCalendarSystem(unittest.TestCase):
    def test_calendar_status(self):
        show = SimpleNamespace(monitored=True)
        unmon = SimpleNamespace(monitored=False)
        ep_down = SimpleNamespace(status="downloaded")
        ep_miss = SimpleNamespace(status="missing")

        self.assertEqual(_calendar_status(unmon, None, dt.datetime.utcnow(), "episode"), "unmonitored")
        self.assertEqual(_calendar_status(show, None, dt.datetime.utcnow(), "premiere"), "premiere")
        self.assertEqual(_calendar_status(show, ep_down, dt.datetime.utcnow(), "episode"), "downloaded")
        self.assertEqual(_calendar_status(show, ep_miss, dt.datetime.utcnow() - dt.timedelta(days=2), "episode"), "missing")

    def test_ical_feed_generation(self):
        entries = [
            SimpleNamespace(
                show_id=1,
                episode_id=101,
                show_title="Breaking Test",
                season=1,
                episode=1,
                title="Pilot",
                air_date=dt.datetime(2026, 8, 20, 18, 0, 0),
                status="unaired",
                entry_type="episode",
                content_type="series",
                monitored=True,
                overview="A high school chemistry teacher...",
                year=2024,
            ),
            SimpleNamespace(
                show_id=2,
                episode_id=None,
                show_title="Star Test: Episode IV",
                season=None,
                episode=None,
                title=None,
                air_date=dt.datetime(2026, 8, 25, 20, 0, 0),
                status="premiere",
                entry_type="premiere",
                content_type="movie",
                monitored=True,
                overview="A farm boy on Tatooine...",
                year=1977,
                release_types=["cinemas"],
            ),
        ]

        feed = _build_ical_feed(entries, cal_name="Aliasarr Releases")
        self.assertIn("BEGIN:VCALENDAR", feed)
        self.assertIn("VERSION:2.0", feed)
        self.assertIn("X-WR-CALNAME:Aliasarr Releases", feed)
        self.assertIn("SUMMARY:Breaking Test - S01E01 - Pilot", feed)
        self.assertIn("SUMMARY:Star Test: Episode IV (1977)", feed)
        self.assertIn("CATEGORIES:Series,Aliasarr", feed)
        self.assertIn("CATEGORIES:Movie,Aliasarr", feed)
        self.assertIn("END:VCALENDAR", feed)


if __name__ == "__main__":
    unittest.main()
