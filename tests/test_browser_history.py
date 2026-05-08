from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from harumi.browser_history import (
    CHROME_EPOCH_OFFSET_SECONDS,
    BrowserHistorySource,
    discover_browser_history_sources,
    import_browser_history,
    parse_date_range,
)
from harumi.db import init_db, query_activity_events_in_range
from harumi.db import get_activity_import_state, query_activity_sessions_in_range


class BrowserHistoryTests(unittest.TestCase):
    def test_discovers_firefox_under_config_mozilla(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir)
            profile = home / ".config" / "mozilla" / "firefox" / "abc.default-release"
            profile.mkdir(parents=True)
            (profile / "places.sqlite").write_text("", encoding="utf-8")

            with patch("pathlib.Path.home", return_value=home):
                sources = discover_browser_history_sources()

            self.assertEqual(len(sources), 1)
            self.assertEqual(sources[0].browser, "firefox")
            self.assertEqual(sources[0].kind, "firefox")
            self.assertEqual(sources[0].profile, "abc.default-release")

    def test_parse_date_range_prefers_explicit_dates_over_last(self) -> None:
        start_ts, end_ts, label = parse_date_range("2026-04-01", "2026-04-02", "7d")
        self.assertIn("2026-04-01", label)
        self.assertGreater(end_ts, start_ts)

    def test_import_chromium_history_strips_query_and_respects_dry_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            history_db = tmp / "History"
            app_db = tmp / "harumi.db"
            init_db(app_db)
            self._create_chromium_history(history_db)
            source = BrowserHistorySource(
                browser="chromium",
                profile="Default",
                kind="chromium",
                path=history_db,
            )

            start_ts, end_ts, _ = parse_date_range("2026-04-01", "2026-04-01", None)
            dry_stats = import_browser_history(
                app_db,
                sources=[source],
                start_ts=start_ts,
                end_ts=end_ts,
                execute=False,
                strip_url_query=True,
                redact_title=False,
                limit_per_source=100,
            )

            self.assertEqual(dry_stats.visits_after_filters, 1)
            self.assertEqual(
                query_activity_events_in_range(app_db, start_ts=start_ts, end_ts=end_ts),
                [],
            )

            stats = import_browser_history(
                app_db,
                sources=[source],
                start_ts=start_ts,
                end_ts=end_ts,
                execute=True,
                strip_url_query=True,
                redact_title=False,
                limit_per_source=100,
            )
            rows = query_activity_events_in_range(app_db, start_ts=start_ts, end_ts=end_ts)

            self.assertEqual(stats.imported, 1)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["title"], "Example Work")
            self.assertEqual(rows[0]["url"], "https://example.com/work")

    def test_import_can_exclude_domains(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            history_db = tmp / "History"
            app_db = tmp / "harumi.db"
            init_db(app_db)
            self._create_chromium_history(history_db)
            source = BrowserHistorySource(
                browser="chromium",
                profile="Default",
                kind="chromium",
                path=history_db,
            )

            start_ts, end_ts, _ = parse_date_range("2026-04-01", "2026-04-01", None)
            stats = import_browser_history(
                app_db,
                sources=[source],
                start_ts=start_ts,
                end_ts=end_ts,
                execute=True,
                exclude_domains=["example.com"],
                limit_per_source=100,
            )

            self.assertEqual(stats.visits_after_filters, 0)
            self.assertEqual(stats.imported, 0)

    def test_import_updates_state_and_builds_sessions(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            history_db = tmp / "History"
            app_db = tmp / "harumi.db"
            init_db(app_db)
            self._create_chromium_history(history_db)
            source = BrowserHistorySource(
                browser="chromium",
                profile="Default",
                kind="chromium",
                path=history_db,
            )

            start_ts, end_ts, _ = parse_date_range("2026-04-01", "2026-04-01", None)
            stats = import_browser_history(
                app_db,
                sources=[source],
                start_ts=start_ts,
                end_ts=end_ts,
                execute=True,
                limit_per_source=100,
                rebuild_sessions=True,
            )

            state = get_activity_import_state(app_db, "browser:chromium:Default")
            sessions = query_activity_sessions_in_range(app_db, start_ts=start_ts, end_ts=end_ts)

            self.assertEqual(stats.imported, 1)
            self.assertIsNotNone(state)
            self.assertGreater(state["last_event_time"], 0)
            self.assertEqual(len(sessions), 1)
            self.assertEqual(sessions[0]["session_type"], "browser")
            self.assertEqual(sessions[0]["primary_domain"], "example.com")

            second_stats = import_browser_history(
                app_db,
                sources=[source],
                start_ts=start_ts,
                end_ts=end_ts,
                execute=True,
                limit_per_source=100,
                since_last=True,
            )
            self.assertEqual(second_stats.visits_seen, 0)
            self.assertEqual(second_stats.imported, 0)

    def _create_chromium_history(self, path: Path) -> None:
        event_ts = 1775001600.0  # 2026-04-01T00:00:00Z
        chrome_ts = int((event_ts + CHROME_EPOCH_OFFSET_SECONDS) * 1_000_000)
        with sqlite3.connect(path) as connection:
            connection.execute("CREATE TABLE urls (id INTEGER PRIMARY KEY, url TEXT, title TEXT)")
            connection.execute("CREATE TABLE visits (id INTEGER PRIMARY KEY, url INTEGER, visit_time INTEGER)")
            connection.execute(
                "INSERT INTO urls (id, url, title) VALUES (?, ?, ?)",
                (1, "https://example.com/work?token=secret#section", "Example Work"),
            )
            connection.execute(
                "INSERT INTO visits (id, url, visit_time) VALUES (?, ?, ?)",
                (1, 1, chrome_ts),
            )
            connection.commit()


if __name__ == "__main__":
    unittest.main()
