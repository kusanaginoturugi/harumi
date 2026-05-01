from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from harumi.db import get_db_path, init_db, insert_root
from harumi.scanner import run_scan


class ScannerTests(unittest.TestCase):
    def test_run_scan_emits_progress_callbacks(self) -> None:
        old_summary = os.environ.get("HARUMI_ENABLE_SUMMARY")
        old_embedding = os.environ.get("HARUMI_ENABLE_EMBEDDING")
        os.environ["HARUMI_ENABLE_SUMMARY"] = "0"
        os.environ["HARUMI_ENABLE_EMBEDDING"] = "0"
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                base = Path(tmpdir)
                root = base / "docs"
                root.mkdir()
                (root / "note.txt").write_text("hello worklog\n", encoding="utf-8")

                db_path = get_db_path(base / "app")
                init_db(db_path)
                insert_root(db_path, root)
                log_dir = base / "logs"
                log_dir.mkdir()

                events: list[tuple[int, int, str]] = []

                def record_progress(_stats, processed: int, total: int, current_path: str) -> None:
                    events.append((processed, total, current_path))

                with patch("harumi.scanner.get_log_dir", return_value=log_dir):
                    stats = run_scan(
                        db_path,
                        progress_callback=record_progress,
                        progress_interval_seconds=3600,
                        progress_percent_step=50,
                    )

                self.assertEqual(stats.discovered, 1)
                self.assertGreaterEqual(len(events), 2)
                self.assertEqual(events[0][0], 0)
                self.assertEqual(events[-1][0], events[-1][1])
                self.assertGreater(events[-1][1], 0)
        finally:
            if old_summary is None:
                os.environ.pop("HARUMI_ENABLE_SUMMARY", None)
            else:
                os.environ["HARUMI_ENABLE_SUMMARY"] = old_summary
            if old_embedding is None:
                os.environ.pop("HARUMI_ENABLE_EMBEDDING", None)
            else:
                os.environ["HARUMI_ENABLE_EMBEDDING"] = old_embedding


if __name__ == "__main__":
    unittest.main()
