from __future__ import annotations

import json
from pathlib import Path

from harumi.db import (
    list_embeddings,
    list_folder_embeddings,
    search_documents,
    search_folders,
)
from harumi.embed import cosine_similarity, embed_text
from harumi.ignore_rules import IgnoreMatcher, is_ignored_directory, is_ignored_file, load_ignore_matcher


def to_fts_query(raw_query: str) -> str:
    terms = [term.strip() for term in raw_query.split() if term.strip()]
    if not terms:
        return ""
    return " AND ".join(f'"{term}"' for term in terms)


def _ignore_matcher_for_root(root_path: str, cache: dict[str, IgnoreMatcher]) -> IgnoreMatcher:
    matcher = cache.get(root_path)
    if matcher is None:
        matcher = load_ignore_matcher(Path(root_path))
        cache[root_path] = matcher
    return matcher


def _is_ignored_search_row(row, matcher_cache: dict[str, IgnoreMatcher]) -> bool:
    matcher = _ignore_matcher_for_root(row["root_path"], matcher_cache)
    path = Path(row["path"])
    if row["kind"] == "folder":
        return is_ignored_directory(path, matcher)
    return is_ignored_file(path, matcher)


def find_documents(db_path: Path, raw_query: str, limit: int = 10):
    fts_query = to_fts_query(raw_query)
    if not fts_query:
        return []
    rows = []
    fetch_limit = max(limit * 5, limit)
    for row in search_documents(db_path, fts_query, limit=fetch_limit):
        rows.append(
            {
                "kind": "file",
                "path": row["path"],
                "root_path": row["root_path"],
                "filename": row["filename"],
                "extension": row["extension"],
                "normalized_format": row["normalized_format"],
                "char_count": row["char_count"],
                "mtime": row["mtime"],
                "summary_short": row["summary_short"],
                "snippet": row["snippet"],
                "fts_score": abs(row["rank"]),
                "vector_score": 0.0,
            }
        )
    for row in search_folders(db_path, fts_query, limit=fetch_limit):
        rows.append(
            {
                "kind": "folder",
                "path": row["path"],
                "root_path": row["root_path"],
                "filename": row["folder_name"],
                "extension": "",
                "normalized_format": "folder",
                "char_count": row["file_count"],
                "mtime": row["mtime"],
                "summary_short": row["summary_short"],
                "snippet": row["snippet"],
                "fts_score": abs(row["rank"]),
                "vector_score": 0.0,
                "file_count": row["file_count"],
                "child_folder_count": row["child_folder_count"],
            }
        )
    matcher_cache: dict[str, IgnoreMatcher] = {}
    return [row for row in rows if not _is_ignored_search_row(row, matcher_cache)][:limit]


def find_similar_documents(db_path: Path, raw_query: str, limit: int = 10):
    query_vector, model_name = embed_text(raw_query)
    scored = []
    matcher_cache: dict[str, IgnoreMatcher] = {}
    for row in list_embeddings(db_path):
        if row["model_name"] != model_name:
            continue
        result = {
            "kind": "file",
            "path": row["path"],
            "root_path": row["root_path"],
            "filename": row["filename"],
            "extension": row["extension"],
            "normalized_format": row["normalized_format"],
            "char_count": row["char_count"],
            "mtime": row["mtime"],
            "summary_short": row["summary_short"],
            "vector_score": 0.0,
            "snippet": "",
            "fts_score": 9999.0,
        }
        if _is_ignored_search_row(result, matcher_cache):
            continue
        vector = json.loads(row["vector_json"])
        score = cosine_similarity(query_vector, vector)
        if score <= 0:
            continue
        result["vector_score"] = score
        scored.append(result)
    for row in list_folder_embeddings(db_path):
        if row["model_name"] != model_name:
            continue
        result = {
            "kind": "folder",
            "path": row["path"],
            "root_path": row["root_path"],
            "filename": row["folder_name"],
            "extension": "",
            "normalized_format": "folder",
            "char_count": row["file_count"],
            "mtime": row["mtime"],
            "summary_short": row["summary_short"],
            "vector_score": 0.0,
            "snippet": "",
            "fts_score": 9999.0,
            "file_count": row["file_count"],
            "child_folder_count": row["child_folder_count"],
        }
        if _is_ignored_search_row(result, matcher_cache):
            continue
        vector = json.loads(row["vector_json"])
        score = cosine_similarity(query_vector, vector)
        if score <= 0:
            continue
        result["vector_score"] = score
        scored.append(result)
    scored.sort(key=lambda item: item["vector_score"], reverse=True)
    return scored[:limit]
