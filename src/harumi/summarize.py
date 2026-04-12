from __future__ import annotations

import re
import subprocess
from pathlib import Path

from harumi.config import (
    get_folder_summary_min_items,
    get_summary_language,
    get_summary_min_chars,
    get_summary_model,
    summary_code_enabled,
)


PROMPT_VERSION = "v1"
ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
CODE_EXTENSIONS = {
    ".py",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
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


def _summary_language_instructions() -> str:
    language = get_summary_language()
    if language == "ja":
        return (
            "必ず日本語で回答してください。"
            "出力は1〜3文の簡潔な要約だけにしてください。"
            "箇条書きや前置きは不要です。"
        )
    if language == "en":
        return (
            "Respond in English."
            " Return only a concise 1-3 sentence summary."
            " Do not add bullet points or preamble."
        )
    return (
        f"Respond in {language} if possible."
        " Return only a concise 1-3 sentence summary."
        " Do not add bullet points or preamble."
    )


def build_summary_prompt(path: str, normalized_text: str) -> str:
    preview = normalized_text[:6000]
    return (
        f"{_summary_language_instructions()}\n\n"
        "Summarize this file in 1-3 concise sentences. "
        "Focus on what the file is for, the main topics, and what someone would use it for.\n\n"
        f"Path: {path}\n\n"
        "Content:\n"
        f"{preview}"
    )


def build_folder_summary_prompt(path: str, child_descriptions: str) -> str:
    return (
        f"{_summary_language_instructions()}\n\n"
        "Summarize this folder in 1-3 concise sentences. "
        "Focus on what kinds of files it contains and what someone would use this folder for.\n\n"
        f"Folder path: {path}\n\n"
        "Child file descriptions:\n"
        f"{child_descriptions[:6000]}"
    )


def _clean_ollama_output(text: str) -> str:
    cleaned = ANSI_ESCAPE_RE.sub("", text)
    while "\b" in cleaned:
        backspace_index = cleaned.find("\b")
        if backspace_index <= 0:
            cleaned = cleaned.replace("\b", "")
            continue
        cleaned = cleaned[: backspace_index - 1] + cleaned[backspace_index + 1 :]
    return " ".join(cleaned.split())


def summarize_text(path: str, normalized_text: str) -> tuple[str, str]:
    model = get_summary_model()
    prompt = build_summary_prompt(path, normalized_text)
    return _run_summary_prompt(model, prompt), model


def summarize_folder(path: str, child_descriptions: str) -> tuple[str, str]:
    model = get_summary_model()
    prompt = build_folder_summary_prompt(path, child_descriptions)
    return _run_summary_prompt(model, prompt), model


def should_summarize_text(path: str, normalized_text: str, normalized_format: str) -> bool:
    if len(normalized_text.strip()) < get_summary_min_chars():
        return False
    if normalized_format == "markdown":
        return True
    if summary_code_enabled():
        return True
    return Path(path).suffix.lower() not in CODE_EXTENSIONS


def should_summarize_folder(child_descriptions: str) -> bool:
    child_count = len([line for line in child_descriptions.splitlines() if line.strip()])
    return child_count >= get_folder_summary_min_items()


def _run_summary_prompt(model: str, prompt: str) -> str:
    completed = subprocess.run(
        ["ollama", "--nowordwrap", "run", model, prompt],
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )
    return _clean_ollama_output(completed.stdout)
