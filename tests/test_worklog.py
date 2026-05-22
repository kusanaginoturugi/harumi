from __future__ import annotations

import os
import tempfile
import unittest
from contextlib import contextmanager
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from harumi.db import init_db, upsert_activity_events
from harumi.worklog import worklog_command


@contextmanager
def temp_env(**values: str):
    old_values = {key: os.environ.get(key) for key in values}
    os.environ.update(values)
    try:
        yield
    finally:
        for key, old_value in old_values.items():
            if old_value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old_value


class WorklogTests(unittest.TestCase):
    def test_worklog_filters_browser_events_to_work_hours_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir)
            db_path = app_dir / "harumi.db"
            init_db(db_path)
            self._insert_browser_event(db_path, "2026-05-08 10:00:00", "Work Docs")
            self._insert_browser_event(db_path, "2026-05-08 20:00:00", "Sushi Order")

            output = StringIO()
            with (
                temp_env(
                    HARUMI_HOME=str(app_dir),
                    HARUMI_WORK_HOURS_START="09:00",
                    HARUMI_WORK_HOURS_END="18:00",
                    HARUMI_WORK_DAYS="mon,tue,wed,thu,fri",
                ),
                patch("sys.stdout", output),
            ):
                exit_code = worklog_command(
                    "2026-05-08",
                    "text",
                    10,
                    True,
                    False,
                )

            text = output.getvalue()
            self.assertEqual(exit_code, 0)
            self.assertIn("Work Docs", text)
            self.assertNotIn("Sushi Order", text)

    def test_worklog_can_include_private_time(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir)
            db_path = app_dir / "harumi.db"
            init_db(db_path)
            self._insert_browser_event(db_path, "2026-05-08 20:00:00", "Sushi Order")

            output = StringIO()
            with (
                temp_env(HARUMI_HOME=str(app_dir)),
                patch("sys.stdout", output),
            ):
                exit_code = worklog_command(
                    "2026-05-08",
                    "text",
                    10,
                    True,
                    True,
                )

            self.assertEqual(exit_code, 0)
            self.assertIn("Sushi Order", output.getvalue())

    def test_worklog_displays_activity_events_chronologically(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir)
            db_path = app_dir / "harumi.db"
            init_db(db_path)
            self._insert_browser_event(db_path, "2026-05-08 10:00:00", "Second")
            self._insert_browser_event(db_path, "2026-05-08 09:00:00", "First")

            output = StringIO()
            with (
                temp_env(
                    HARUMI_HOME=str(app_dir),
                    HARUMI_WORK_HOURS_START="09:00",
                    HARUMI_WORK_HOURS_END="18:00",
                    HARUMI_WORK_DAYS="mon,tue,wed,thu,fri",
                ),
                patch("sys.stdout", output),
            ):
                exit_code = worklog_command(
                    "2026-05-08",
                    "text",
                    10,
                    True,
                    False,
                )

            text = output.getvalue()
            self.assertEqual(exit_code, 0)
            self.assertLess(text.index("First"), text.index("Second"))

    def test_worklog_hides_ai_export_path_from_activity_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = Path(tmpdir)
            db_path = app_dir / "harumi.db"
            init_db(db_path)
            self._insert_ai_event(db_path, "2026-05-08 10:00:00", "AI Search")

            output = StringIO()
            with (
                temp_env(
                    HARUMI_HOME=str(app_dir),
                    HARUMI_WORK_HOURS_START="09:00",
                    HARUMI_WORK_HOURS_END="18:00",
                    HARUMI_WORK_DAYS="mon,tue,wed,thu,fri",
                ),
                patch("sys.stdout", output),
            ):
                exit_code = worklog_command(
                    "2026-05-08",
                    "text",
                    10,
                    True,
                    False,
                )

            text = output.getvalue()
            self.assertEqual(exit_code, 0)
            self.assertIn("AI Search", text)
            self.assertNotIn("llm_logs/gemini_data/export.zip", text)

    def _insert_browser_event(self, db_path: Path, timestamp: str, title: str) -> None:
        local_tz = datetime.now(timezone.utc).astimezone().tzinfo
        event_time = datetime.fromisoformat(timestamp).replace(tzinfo=local_tz).timestamp()
        upsert_activity_events(
            db_path,
            [
                {
                    "source": "browser:firefox:test",
                    "event_type": "browser_visit",
                    "event_time": float(event_time),
                    "title": title,
                    "url": "https://example.com/",
                    "metadata_json": "{}",
                    "dedupe_key": f"{timestamp}:{title}",
                }
            ],
        )

    def _insert_ai_event(self, db_path: Path, timestamp: str, title: str) -> None:
        local_tz = datetime.now(timezone.utc).astimezone().tzinfo
        event_time = datetime.fromisoformat(timestamp).replace(tzinfo=local_tz).timestamp()
        upsert_activity_events(
            db_path,
            [
                {
                    "source": "ai:gemini",
                    "event_type": "ai_conversation",
                    "event_time": float(event_time),
                    "title": title,
                    "path": "/home/onoue/src/harumi/llm_logs/gemini_data/export.zip",
                    "metadata_json": "{}",
                    "dedupe_key": f"{timestamp}:{title}",
                }
            ],
        )


if __name__ == "__main__":
    unittest.main()
