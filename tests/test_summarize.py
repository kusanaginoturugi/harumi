from __future__ import annotations

import os
import unittest

from harumi.summarize import should_summarize_folder, should_summarize_text


class SummarizePolicyTests(unittest.TestCase):
    def test_short_text_is_skipped(self) -> None:
        old_value = os.environ.get("HARUMI_SUMMARY_MIN_CHARS")
        os.environ["HARUMI_SUMMARY_MIN_CHARS"] = "50"
        try:
            self.assertFalse(should_summarize_text("/tmp/note.txt", "short note", "text"))
        finally:
            if old_value is None:
                os.environ.pop("HARUMI_SUMMARY_MIN_CHARS", None)
            else:
                os.environ["HARUMI_SUMMARY_MIN_CHARS"] = old_value

    def test_markdown_document_is_summarized_when_long_enough(self) -> None:
        old_value = os.environ.get("HARUMI_SUMMARY_MIN_CHARS")
        os.environ["HARUMI_SUMMARY_MIN_CHARS"] = "10"
        try:
            self.assertTrue(
                should_summarize_text(
                    "/tmp/report.pdf",
                    "A" * 200,
                    "markdown",
                )
            )
        finally:
            if old_value is None:
                os.environ.pop("HARUMI_SUMMARY_MIN_CHARS", None)
            else:
                os.environ["HARUMI_SUMMARY_MIN_CHARS"] = old_value

    def test_code_file_is_skipped_by_default(self) -> None:
        old_min = os.environ.get("HARUMI_SUMMARY_MIN_CHARS")
        old_code = os.environ.get("HARUMI_SUMMARY_CODE")
        os.environ["HARUMI_SUMMARY_MIN_CHARS"] = "10"
        os.environ["HARUMI_SUMMARY_CODE"] = "0"
        try:
            self.assertFalse(should_summarize_text("/tmp/app.py", "A" * 200, "text"))
        finally:
            if old_min is None:
                os.environ.pop("HARUMI_SUMMARY_MIN_CHARS", None)
            else:
                os.environ["HARUMI_SUMMARY_MIN_CHARS"] = old_min
            if old_code is None:
                os.environ.pop("HARUMI_SUMMARY_CODE", None)
            else:
                os.environ["HARUMI_SUMMARY_CODE"] = old_code

    def test_code_file_can_be_enabled(self) -> None:
        old_min = os.environ.get("HARUMI_SUMMARY_MIN_CHARS")
        old_code = os.environ.get("HARUMI_SUMMARY_CODE")
        os.environ["HARUMI_SUMMARY_MIN_CHARS"] = "10"
        os.environ["HARUMI_SUMMARY_CODE"] = "1"
        try:
            self.assertTrue(should_summarize_text("/tmp/app.py", "A" * 200, "text"))
        finally:
            if old_min is None:
                os.environ.pop("HARUMI_SUMMARY_MIN_CHARS", None)
            else:
                os.environ["HARUMI_SUMMARY_MIN_CHARS"] = old_min
            if old_code is None:
                os.environ.pop("HARUMI_SUMMARY_CODE", None)
            else:
                os.environ["HARUMI_SUMMARY_CODE"] = old_code

    def test_folder_summary_requires_multiple_children_by_default(self) -> None:
        self.assertFalse(should_summarize_folder("file: note.txt (.txt)"))
        self.assertTrue(
            should_summarize_folder(
                "file: note.txt (.txt)\nfile: policy.pdf (.pdf)"
            )
        )


if __name__ == "__main__":
    unittest.main()
