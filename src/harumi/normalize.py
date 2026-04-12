from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from pathlib import Path


TEXT_EXTENSIONS = {
    ".md",
    ".txt",
    ".rst",
    ".py",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".cfg",
    ".conf",
    ".sh",
    ".zsh",
    ".bash",
    ".c",
    ".cc",
    ".cpp",
    ".h",
    ".hpp",
    ".java",
    ".rb",
    ".go",
    ".rs",
    ".css",
    ".scss",
    ".sql",
}

MARKITDOWN_EXTENSIONS = {
    ".pdf",
    ".docx",
    ".pptx",
    ".xlsx",
    ".doc",
    ".ppt",
    ".xls",
    ".csv",
    ".html",
    ".htm",
    ".xml",
}


@dataclass
class NormalizedDocument:
    text: str
    format: str


def _has_markitdown() -> bool:
    return importlib.util.find_spec("markitdown") is not None


def _normalize_text_file(path: Path) -> NormalizedDocument | None:
    try:
        text = path.read_text(encoding="utf-8")
        return NormalizedDocument(text=text, format="text")
    except UnicodeDecodeError:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
            return NormalizedDocument(text=text, format="text")
        except OSError:
            return None
    except OSError:
        return None


def _normalize_with_markitdown(path: Path) -> NormalizedDocument | None:
    if not _has_markitdown():
        return None

    try:
        from markitdown import MarkItDown

        result = MarkItDown().convert(str(path))
    except Exception:
        return None

    text = getattr(result, "text_content", None) or getattr(result, "markdown", None)
    if not text:
        return None
    return NormalizedDocument(text=text, format="markdown")


def normalize_file(path: Path) -> NormalizedDocument | None:
    suffix = path.suffix.lower()
    if suffix in MARKITDOWN_EXTENSIONS:
        return _normalize_with_markitdown(path)
    if suffix in TEXT_EXTENSIONS:
        return _normalize_text_file(path)
    return None
