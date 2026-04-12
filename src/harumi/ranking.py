from __future__ import annotations

import math
import time
from dataclasses import dataclass


CODE_EXTENSIONS = {
    ".py",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".java",
    ".go",
    ".rs",
    ".rb",
    ".c",
    ".cc",
    ".cpp",
    ".h",
    ".hpp",
    ".sh",
    ".zsh",
}

DOCUMENT_EXTENSIONS = {
    ".md",
    ".txt",
    ".pdf",
    ".docx",
    ".pptx",
    ".xlsx",
    ".html",
    ".htm",
    ".csv",
}

CODE_HINTS = {
    "script",
    "code",
    "function",
    "module",
    "class",
    "repo",
    "repository",
    "upload",
    "sync",
    "api",
    "bug",
    "fix",
}

DOCUMENT_HINTS = {
    "doc",
    "document",
    "note",
    "notes",
    "memo",
    "policy",
    "guide",
    "invoice",
    "receipt",
    "summary",
}

FOLDER_HINTS = {
    "folder",
    "directory",
    "place",
    "where",
    "location",
    "置き場",
    "場所",
    "フォルダ",
    "ディレクトリ",
}

FILE_HINTS = {
    "file",
    "document",
    "note",
    "script",
    "memo",
    "ファイル",
}

RECENT_HINTS = {
    "latest",
    "recent",
    "new",
    "newest",
    "current",
    "today",
    "yesterday",
    "last",
    "recently",
    "最近",
    "最新",
    "新しい",
    "この前",
    "今",
}

STABLE_HINTS = {
    "policy",
    "guide",
    "spec",
    "manual",
    "reference",
    "procedure",
    "rule",
    "rules",
    "設計",
    "仕様",
    "手順",
    "ルール",
}


@dataclass
class QueryIntent:
    terms: list[str]
    code_intent: bool
    document_intent: bool
    folder_intent: bool
    file_intent: bool
    recent_intent: bool
    stable_intent: bool


def infer_intent(raw_query: str) -> QueryIntent:
    terms = [term.strip(".,/\\()[]{}:;!?\"'").lower() for term in raw_query.split()]
    terms = [term for term in terms if term]
    code_intent = any(term in CODE_HINTS for term in terms)
    document_intent = any(term in DOCUMENT_HINTS for term in terms)
    folder_intent = any(term in FOLDER_HINTS for term in terms)
    file_intent = any(term in FILE_HINTS for term in terms)
    recent_intent = any(term in RECENT_HINTS for term in terms)
    stable_intent = any(term in STABLE_HINTS for term in terms)
    return QueryIntent(
        terms=terms,
        code_intent=code_intent,
        document_intent=document_intent,
        folder_intent=folder_intent,
        file_intent=file_intent,
        recent_intent=recent_intent,
        stable_intent=stable_intent,
    )


def _normalize_fts_score(raw_fts_score: float) -> float:
    if raw_fts_score >= 9999:
        return 0.0
    return 1.0 / (1.0 + max(raw_fts_score, 0.0))


def _filename_path_boost(filename: str, path: str, terms: list[str]) -> tuple[float, list[str]]:
    reasons: list[str] = []
    score = 0.0
    filename_lower = filename.lower()
    path_lower = path.lower()

    filename_hits = sum(1 for term in terms if term in filename_lower)
    path_hits = sum(1 for term in terms if term in path_lower)

    if filename_hits:
        score += min(0.35, 0.12 * filename_hits)
        reasons.append("filename matched query terms")
    if path_hits:
        score += min(0.20, 0.05 * path_hits)
        reasons.append("path matched query terms")

    return score, reasons


def _summary_term_boost(summary_short: str, terms: list[str]) -> tuple[float, list[str]]:
    if not summary_short:
        return 0.0, []
    summary_lower = summary_short.lower()
    hits = sum(1 for term in terms if term in summary_lower)
    if not hits:
        return 0.0, []
    return min(0.20, 0.05 * hits), ["summary aligned with query"]


def _filetype_boost(extension: str, intent: QueryIntent) -> tuple[float, list[str]]:
    if intent.code_intent and extension in CODE_EXTENSIONS:
        return 0.12, ["query looks code-oriented"]
    if intent.document_intent and extension in DOCUMENT_EXTENSIONS:
        return 0.12, ["query looks document-oriented"]
    return 0.0, []


def _kind_boost(kind: str, intent: QueryIntent) -> tuple[float, list[str]]:
    if kind == "folder" and intent.folder_intent:
        return 0.18, ["query looks folder-oriented"]
    if kind == "file" and intent.file_intent:
        return 0.10, ["query looks file-oriented"]
    return 0.0, []


def _root_penalty(path: str, root_path: str, kind: str, terms: list[str]) -> tuple[float, list[str]]:
    if kind != "folder":
        return 0.0, []
    if path != root_path:
        return 0.0, []
    root_name = root_path.rstrip("/").split("/")[-1].lower()
    meaningful_terms = [term for term in terms if term not in FOLDER_HINTS and term not in FILE_HINTS]
    if any(term and term in root_name for term in meaningful_terms):
        return 0.0, []
    penalty = 0.10
    if any(term in FOLDER_HINTS for term in terms):
        penalty = 0.18
    return penalty, ["broad root folder penalty"]


def _recency_component(mtime: float, intent: QueryIntent) -> tuple[float, list[str]]:
    if not mtime or mtime <= 0:
        return 0.0, []

    age_days = max(0.0, (time.time() - mtime) / 86400.0)
    base_score = math.exp(-age_days / 90.0)
    weight = 0.06
    reasons: list[str] = []

    if intent.recent_intent:
        weight = 0.14
        reasons.append("query prefers newer information")
    elif intent.stable_intent:
        weight = 0.03
    elif age_days <= 30:
        reasons.append("recently updated")

    return base_score * weight, reasons


def rank_results(raw_query: str, results: list[dict]) -> list[dict]:
    intent = infer_intent(raw_query)
    ranked: list[dict] = []

    for row in results:
        reasons: list[str] = []
        vector_component = 0.55 * row.get("vector_score", 0.0)
        fts_component = 0.30 * _normalize_fts_score(row.get("fts_score", 9999.0))

        filename_path_component, fp_reasons = _filename_path_boost(
            row["filename"],
            row["path"],
            intent.terms,
        )
        summary_component, summary_reasons = _summary_term_boost(
            row.get("summary_short", ""),
            intent.terms,
        )
        filetype_component, filetype_reasons = _filetype_boost(
            row.get("extension", ""),
            intent,
        )
        kind_component, kind_reasons = _kind_boost(
            row.get("kind", "file"),
            intent,
        )
        recency_component, recency_reasons = _recency_component(
            row.get("mtime", 0.0),
            intent,
        )
        root_penalty, root_penalty_reasons = _root_penalty(
            row["path"],
            row.get("root_path", ""),
            row.get("kind", "file"),
            intent.terms,
        )

        reasons.extend(fp_reasons)
        reasons.extend(summary_reasons)
        reasons.extend(filetype_reasons)
        reasons.extend(kind_reasons)
        reasons.extend(recency_reasons)
        reasons.extend(root_penalty_reasons)
        if row.get("vector_score", 0.0) > 0.45:
            reasons.append("strong semantic match")
        if row.get("fts_score", 9999.0) < 2.0:
            reasons.append("strong keyword match")

        final_score = (
            vector_component
            + fts_component
            + filename_path_component
            + summary_component
            + filetype_component
            + kind_component
            + recency_component
            - root_penalty
        )

        ranked.append(
            {
                **row,
                "final_score": final_score,
                "reasons": list(dict.fromkeys(reasons)),
                "fts_component": fts_component,
                "vector_component": vector_component,
                "recency_component": recency_component,
                "root_penalty": root_penalty,
            }
        )

    ranked.sort(key=lambda row: row["final_score"], reverse=True)
    return ranked
