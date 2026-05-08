from __future__ import annotations

import os
import unittest

from harumi.summarize import (
    build_folder_summary_prompt,
    build_summary_prompt,
    _clean_ollama_output,
    should_summarize_folder,
    should_summarize_text,
)


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

    def test_summary_prompt_defaults_to_japanese(self) -> None:
        old_value = os.environ.get("HARUMI_SUMMARY_LANGUAGE")
        os.environ.pop("HARUMI_SUMMARY_LANGUAGE", None)
        try:
            prompt = build_summary_prompt("/tmp/report.txt", "A" * 50)
            self.assertIn("必ず日本語で回答してください", prompt)
        finally:
            if old_value is not None:
                os.environ["HARUMI_SUMMARY_LANGUAGE"] = old_value

    def test_folder_prompt_can_switch_to_english(self) -> None:
        old_value = os.environ.get("HARUMI_SUMMARY_LANGUAGE")
        os.environ["HARUMI_SUMMARY_LANGUAGE"] = "en"
        try:
            prompt = build_folder_summary_prompt("/tmp/docs", "file: note.txt (.txt)")
            self.assertIn("Respond in English.", prompt)
        finally:
            if old_value is None:
                os.environ.pop("HARUMI_SUMMARY_LANGUAGE", None)
            else:
                os.environ["HARUMI_SUMMARY_LANGUAGE"] = old_value

    def test_clean_output_removes_leading_thinking_trace(self) -> None:
        raw = (
            "Thinking... internal reasoning that should not be shown. "
            "...done thinking. 今日は Harumi の作業履歴機能を改善しました。"
        )
        self.assertEqual(
            _clean_ollama_output(raw),
            "今日は Harumi の作業履歴機能を改善しました。",
        )

    def test_clean_output_removes_think_tags(self) -> None:
        raw = "<think>hidden reasoning</think> 表示する本文です。"
        self.assertEqual(_clean_ollama_output(raw), "表示する本文です。")


if __name__ == "__main__":
    unittest.main()
