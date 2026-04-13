from __future__ import annotations

import time
import unittest

from harumi.ranking import infer_intent, rank_results


class RankingTests(unittest.TestCase):
    def test_infer_intent_detects_folder_and_recent_terms(self) -> None:
        intent = infer_intent("where is the recent travel folder")
        self.assertTrue(intent.folder_intent)
        self.assertTrue(intent.recent_intent)
        self.assertFalse(intent.code_intent)

    def test_recent_query_prefers_newer_result(self) -> None:
        now = time.time()
        results = [
            {
                "kind": "file",
                "path": "/docs/older-policy.txt",
                "root_path": "/docs",
                "filename": "older-policy.txt",
                "extension": ".txt",
                "normalized_format": "text",
                "char_count": 100,
                "summary_short": "Travel policy reimbursement guide",
                "snippet": "",
                "fts_score": 9999.0,
                "vector_score": 0.45,
                "mtime": now - 120 * 86400,
            },
            {
                "kind": "file",
                "path": "/docs/newer-policy.txt",
                "root_path": "/docs",
                "filename": "newer-policy.txt",
                "extension": ".txt",
                "normalized_format": "text",
                "char_count": 100,
                "summary_short": "Travel policy reimbursement guide",
                "snippet": "",
                "fts_score": 9999.0,
                "vector_score": 0.45,
                "mtime": now - 2 * 86400,
            },
        ]

        ranked = rank_results("recent travel document", results)
        self.assertEqual(ranked[0]["path"], "/docs/newer-policy.txt")
        self.assertGreater(ranked[0]["recency_component"], ranked[1]["recency_component"])

    def test_stable_query_keeps_recency_weight_small(self) -> None:
        now = time.time()
        results = [
            {
                "kind": "file",
                "path": "/docs/policy.txt",
                "root_path": "/docs",
                "filename": "policy.txt",
                "extension": ".txt",
                "normalized_format": "text",
                "char_count": 100,
                "summary_short": "Travel policy guide",
                "snippet": "",
                "fts_score": 9999.0,
                "vector_score": 0.50,
                "mtime": now - 1 * 86400,
            }
        ]

        ranked = rank_results("travel policy guide", results)
        self.assertLess(ranked[0]["recency_component"], 0.05)

    def test_root_folder_penalty_applies_to_broad_root(self) -> None:
        now = time.time()
        results = [
            {
                "kind": "folder",
                "path": "/tmp/fixture",
                "root_path": "/tmp/fixture",
                "filename": "fixture",
                "extension": "",
                "normalized_format": "folder",
                "char_count": 0,
                "file_count": 0,
                "child_folder_count": 3,
                "summary_short": "Contains travel, tax, and code subfolders",
                "snippet": "",
                "fts_score": 9999.0,
                "vector_score": 0.40,
                "mtime": now,
            },
            {
                "kind": "folder",
                "path": "/tmp/fixture/travel",
                "root_path": "/tmp/fixture",
                "filename": "travel",
                "extension": "",
                "normalized_format": "folder",
                "char_count": 2,
                "file_count": 2,
                "child_folder_count": 1,
                "summary_short": "Travel folder with notes and receipts",
                "snippet": "",
                "fts_score": 9999.0,
                "vector_score": 0.40,
                "mtime": now,
            },
        ]

        ranked = rank_results("where is the travel folder", results)
        self.assertEqual(ranked[0]["path"], "/tmp/fixture/travel")
        root_result = next(row for row in ranked if row["path"] == "/tmp/fixture")
        self.assertGreater(root_result["root_penalty"], 0.0)

    def test_tiny_auxiliary_file_is_penalized_against_real_document(self) -> None:
        results = [
            {
                "kind": "file",
                "path": "/docs/sounds/acall/17/0001.wav.txt",
                "root_path": "/docs",
                "filename": "0001.wav.txt",
                "extension": ".txt",
                "normalized_format": "text",
                "char_count": 25,
                "summary_short": "",
                "snippet": "",
                "fts_score": 9999.0,
                "vector_score": 0.66,
                "mtime": 0.0,
            },
            {
                "kind": "file",
                "path": "/docs/manual/オートコール設計書.xlsx",
                "root_path": "/docs",
                "filename": "オートコール設計書.xlsx",
                "extension": ".xlsx",
                "normalized_format": "markdown",
                "char_count": 5000,
                "summary_short": "このファイルはオートコールシステムの設計書です。",
                "snippet": "",
                "fts_score": 9999.0,
                "vector_score": 0.54,
                "mtime": 0.0,
            },
        ]

        ranked = rank_results("オートコールシステム", results)
        self.assertEqual(ranked[0]["path"], "/docs/manual/オートコール設計書.xlsx")
        tiny = next(row for row in ranked if row["filename"] == "0001.wav.txt")
        self.assertGreater(tiny["quality_penalty"], 0.0)

    def test_sparse_folder_is_penalized_against_richer_folder(self) -> None:
        results = [
            {
                "kind": "folder",
                "path": "/docs/precal",
                "root_path": "/docs",
                "filename": "precal",
                "extension": "",
                "normalized_format": "folder",
                "char_count": 0,
                "file_count": 0,
                "child_folder_count": 1,
                "summary_short": "",
                "snippet": "",
                "fts_score": 9999.0,
                "vector_score": 0.58,
                "mtime": 0.0,
            },
            {
                "kind": "folder",
                "path": "/docs/designオートコール",
                "root_path": "/docs",
                "filename": "designオートコール",
                "extension": "",
                "normalized_format": "folder",
                "char_count": 0,
                "file_count": 3,
                "child_folder_count": 1,
                "summary_short": "このフォルダにはオートコールの設計資料が入っています。",
                "snippet": "",
                "fts_score": 9999.0,
                "vector_score": 0.54,
                "mtime": 0.0,
            },
        ]

        ranked = rank_results("オートコール フォルダ", results)
        self.assertEqual(ranked[0]["path"], "/docs/designオートコール")
        sparse = next(row for row in ranked if row["path"] == "/docs/precal")
        self.assertGreater(sparse["quality_penalty"], 0.0)


if __name__ == "__main__":
    unittest.main()
