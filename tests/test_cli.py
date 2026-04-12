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


if __name__ == "__main__":
    unittest.main()
