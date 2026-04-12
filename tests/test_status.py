from __future__ import annotations

import unittest
from unittest.mock import patch

from harumi import status


class StatusTests(unittest.TestCase):
    def test_model_installed_accepts_latest_suffix(self) -> None:
        self.assertTrue(status._model_installed("embeddinggemma", ["embeddinggemma:latest"]))
        self.assertTrue(status._model_installed("gemma3:latest", ["gemma3:latest"]))
        self.assertFalse(status._model_installed("missing-model", ["embeddinggemma:latest"]))

    @patch("harumi.status._fetch_ollama_models")
    @patch("harumi.status._module_available")
    @patch("harumi.status._command_available")
    @patch("harumi.status.ensure_app_dirs")
    def test_status_report_shows_missing_server(
        self,
        mock_app_dir,
        mock_command,
        mock_module,
        mock_fetch_models,
    ) -> None:
        mock_app_dir.return_value = "/tmp/harumi"
        mock_command.return_value = True
        mock_module.return_value = True
        mock_fetch_models.return_value = (False, [], "connection refused")

        rows = status.get_status_report()
        names = {name: (state, detail) for name, state, detail in rows}

        self.assertEqual(names["ollama_command"][0], "ok")
        self.assertEqual(names["markitdown_module"][0], "ok")
        self.assertEqual(names["ollama_server"], ("error", "connection refused"))


if __name__ == "__main__":
    unittest.main()
