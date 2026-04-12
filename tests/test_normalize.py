from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from harumi.normalize import normalize_file


class NormalizeTests(unittest.TestCase):
    def test_text_file_is_read_directly(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "note.txt"
            path.write_text("hello world\nthis is a note\n", encoding="utf-8")

            result = normalize_file(path)

            self.assertIsNotNone(result)
            assert result is not None
            self.assertEqual(result.format, "text")
            self.assertIn("hello world", result.text)

    def test_html_uses_markitdown_and_returns_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "sample.html"
            path.write_text(
                """
                <html>
                  <body>
                    <h1>Travel Policy</h1>
                    <p>This page explains reimbursement rules.</p>
                    <ul>
                      <li>Keep receipts</li>
                    </ul>
                  </body>
                </html>
                """,
                encoding="utf-8",
            )

            result = normalize_file(path)

            self.assertIsNotNone(result)
            assert result is not None
            self.assertEqual(result.format, "markdown")
            self.assertIn("# Travel Policy", result.text)
            self.assertIn("Keep receipts", result.text)

    def test_unknown_extension_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "archive.bin"
            path.write_bytes(b"\x00\x01\x02")

            result = normalize_file(path)

            self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
