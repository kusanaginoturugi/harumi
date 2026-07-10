from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from harumi.db import count_index_stats, get_db_path, init_db, insert_root, list_scan_state
from harumi.scanner import run_quickscan, run_scan


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

    def test_run_scan_count_progress_does_not_estimate_total(self) -> None:
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

                with (
                    patch("harumi.scanner.get_log_dir", return_value=log_dir),
                    patch("harumi.scanner._count_scan_items", side_effect=AssertionError("unexpected estimate")),
                ):
                    stats = run_scan(
                        db_path,
                        progress_callback=record_progress,
                        progress_interval_seconds=3600,
                        progress_percent_step=0,
                    )

                self.assertEqual(stats.discovered, 1)
                self.assertGreaterEqual(len(events), 2)
                self.assertTrue(all(total == 0 for _, total, _ in events))
        finally:
            if old_summary is None:
                os.environ.pop("HARUMI_ENABLE_SUMMARY", None)
            else:
                os.environ["HARUMI_ENABLE_SUMMARY"] = old_summary
            if old_embedding is None:
                os.environ.pop("HARUMI_ENABLE_EMBEDDING", None)
            else:
                os.environ["HARUMI_ENABLE_EMBEDDING"] = old_embedding

    def test_scan_respects_harumiignore_patterns(self) -> None:
        old_summary = os.environ.get("HARUMI_ENABLE_SUMMARY")
        old_embedding = os.environ.get("HARUMI_ENABLE_EMBEDDING")
        os.environ["HARUMI_ENABLE_SUMMARY"] = "0"
        os.environ["HARUMI_ENABLE_EMBEDDING"] = "0"
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                base = Path(tmpdir)
                root = base / "workspace"
                root.mkdir()
                (root / ".harumiignore").write_text("vendor/\n*.log\n", encoding="utf-8")
                (root / "note.txt").write_text("keep me\n", encoding="utf-8")
                vendor_dir = root / "vendor" / "bundle"
                vendor_dir.mkdir(parents=True)
                (vendor_dir / "gem.txt").write_text("ignore me\n", encoding="utf-8")
                (root / "debug.log").write_text("ignore me too\n", encoding="utf-8")

                db_path = get_db_path(base / "app")
                init_db(db_path)
                insert_root(db_path, root)
                log_dir = base / "logs"
                log_dir.mkdir()

                with patch("harumi.scanner.get_log_dir", return_value=log_dir):
                    stats = run_scan(db_path)

                counts = count_index_stats(db_path)
                self.assertEqual(stats.discovered, 1)
                self.assertGreaterEqual(stats.ignored, 2)
                self.assertEqual(counts["files"], 1)
        finally:
            if old_summary is None:
                os.environ.pop("HARUMI_ENABLE_SUMMARY", None)
            else:
                os.environ["HARUMI_ENABLE_SUMMARY"] = old_summary
            if old_embedding is None:
                os.environ.pop("HARUMI_ENABLE_EMBEDDING", None)
            else:
                os.environ["HARUMI_ENABLE_EMBEDDING"] = old_embedding

    def test_quickscan_indexes_only_files_changed_after_previous_scan(self) -> None:
        old_summary = os.environ.get("HARUMI_ENABLE_SUMMARY")
        old_embedding = os.environ.get("HARUMI_ENABLE_EMBEDDING")
        os.environ["HARUMI_ENABLE_SUMMARY"] = "0"
        os.environ["HARUMI_ENABLE_EMBEDDING"] = "0"
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                base = Path(tmpdir)
                root = base / "docs"
                root.mkdir()
                old_file = root / "old.txt"
                old_file.write_text("old\n", encoding="utf-8")

                db_path = get_db_path(base / "app")
                init_db(db_path)
                insert_root(db_path, root)
                log_dir = base / "logs"
                log_dir.mkdir()

                with patch("harumi.scanner.get_log_dir", return_value=log_dir):
                    full_stats = run_scan(db_path)

                new_file = root / "new.txt"
                new_file.write_text("new\n", encoding="utf-8")
                future_mtime = full_stats.discovered + 2_000_000_000
                os.utime(new_file, (future_mtime, future_mtime))

                with patch("harumi.scanner.get_log_dir", return_value=log_dir):
                    quick_stats = run_quickscan(db_path)

                counts = count_index_stats(db_path)
                scan_state = list_scan_state(db_path)[0]
                self.assertEqual(quick_stats.discovered, 1)
                self.assertEqual(quick_stats.indexed, 1)
                self.assertEqual(quick_stats.unchanged, 0)
                self.assertEqual(counts["files"], 2)
                self.assertGreater(scan_state["last_full_started_at"], 0)
                self.assertGreater(scan_state["last_quick_started_at"], 0)
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
