from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from io import StringIO
from unittest.mock import patch

from harumi import cli


class CliTests(unittest.TestCase):
    def test_find_command_passes_path_to_search_functions(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            fake_db = Path(tmpdir) / "harumi.db"

            with (
                patch("harumi.cli._ensure_ready", return_value=fake_db),
                patch("harumi.cli.embedding_enabled", return_value=False),
                patch("harumi.cli.find_documents", return_value=[]) as mock_find_documents,
            ):
                exit_code = cli.find_command("test query", limit=5)

            self.assertEqual(exit_code, 0)
            mock_find_documents.assert_called_once()
            self.assertIsInstance(mock_find_documents.call_args.args[0], Path)

    def test_regenerate_summaries_requires_execute_and_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            fake_db = Path(tmpdir) / "harumi.db"
            output = StringIO()

            with (
                patch("harumi.cli._ensure_ready", return_value=fake_db),
                patch(
                    "harumi.cli.count_regeneration_targets",
                    return_value={
                        "file_documents": 10,
                        "folder_records": 2,
                        "file_summaries": 10,
                        "folder_summaries": 2,
                        "file_embeddings": 10,
                        "folder_embeddings": 2,
                    },
                ),
                patch("harumi.cli.regenerate_summaries") as mock_regenerate,
                patch("sys.stdout", output),
            ):
                exit_code = cli.regenerate_summaries_command(
                    "all",
                    execute=False,
                    confirm=None,
                    purge_only=False,
                    limit=None,
                )

            self.assertEqual(exit_code, 0)
            mock_regenerate.assert_not_called()
            self.assertIn("Dry run only. No changes were made.", output.getvalue())

    def test_scan_command_refreshes_configured_activity_imports(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            fake_db = Path(tmpdir) / "harumi.db"
            output = StringIO()

            with (
                patch("harumi.cli._ensure_ready", return_value=fake_db),
                patch("harumi.cli._run_file_scan", return_value=object()),
                patch("harumi.cli._print_file_scan_summary"),
                patch("harumi.cli.scan_browser_history_enabled", return_value=True),
                patch("harumi.cli.scan_ai_history_enabled", return_value=True),
                patch("harumi.cli._import_browser_history_during_scan") as mock_browser,
                patch("harumi.cli._import_ai_history_during_scan") as mock_ai,
                patch("sys.stdout", output),
            ):
                exit_code = cli.scan_command(600.0, 1.0)

            self.assertEqual(exit_code, 0)
            mock_browser.assert_called_once_with(fake_db)
            mock_ai.assert_called_once_with(fake_db)

    def test_run_file_scan_uses_count_progress_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            fake_db = Path(tmpdir) / "harumi.db"

            with patch("harumi.cli.run_scan", return_value=object()) as mock_run_scan:
                cli._run_file_scan(fake_db, 600.0, None)

            _, kwargs = mock_run_scan.call_args
            self.assertIn("progress_callback", kwargs)
            self.assertEqual(kwargs["progress_interval_seconds"], 600.0)
            self.assertEqual(kwargs["progress_percent_step"], 0.0)

    def test_run_file_scan_skips_progress_when_quiet(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            fake_db = Path(tmpdir) / "harumi.db"

            with patch("harumi.cli.run_scan", return_value=object()) as mock_run_scan:
                cli._run_file_scan(fake_db, 600.0, None, quiet=True)

            mock_run_scan.assert_called_once_with(fake_db)

    def test_run_file_scan_enables_progress_when_percent_is_set(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            fake_db = Path(tmpdir) / "harumi.db"

            with patch("harumi.cli.run_scan", return_value=object()) as mock_run_scan:
                cli._run_file_scan(fake_db, 600.0, 5.0)

            _, kwargs = mock_run_scan.call_args
            self.assertIn("progress_callback", kwargs)
            self.assertEqual(kwargs["progress_interval_seconds"], 600.0)
            self.assertEqual(kwargs["progress_percent_step"], 5.0)

    def test_scan_command_files_only_skips_activity_imports(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            fake_db = Path(tmpdir) / "harumi.db"
            output = StringIO()

            with (
                patch("harumi.cli._ensure_ready", return_value=fake_db),
                patch("harumi.cli._run_file_scan", return_value=object()),
                patch("harumi.cli._print_file_scan_summary"),
                patch("harumi.cli._import_browser_history_during_scan") as mock_browser,
                patch("harumi.cli._import_ai_history_during_scan") as mock_ai,
                patch("sys.stdout", output),
            ):
                exit_code = cli.scan_command(600.0, 1.0, files_only=True)

            self.assertEqual(exit_code, 0)
            mock_browser.assert_not_called()
            mock_ai.assert_not_called()
            self.assertIn("files-only mode", output.getvalue())

    def test_worklog_refresh_runs_scan_before_worklog(self) -> None:
        with (
            patch("harumi.cli.scan_command", return_value=0) as mock_scan,
            patch("harumi.cli.worklog_command", return_value=0) as mock_worklog,
        ):
            exit_code = cli.main(["worklog", "--refresh", "--date", "2026-05-21", "--no-llm"])

        self.assertEqual(exit_code, 0)
        mock_scan.assert_called_once()
        mock_worklog.assert_called_once()


if __name__ == "__main__":
    unittest.main()
