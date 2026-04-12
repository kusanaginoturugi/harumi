from __future__ import annotations

import re
import subprocess

from harumi.config import get_summary_model


PROMPT_VERSION = "v1"
ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")


def build_summary_prompt(path: str, normalized_text: str) -> str:
    preview = normalized_text[:6000]
    return (
        "Summarize this file in 1-3 concise sentences. "
        "Focus on what the file is for, the main topics, and what someone would use it for.\n\n"
        f"Path: {path}\n\n"
        "Content:\n"
        f"{preview}"
    )


def build_folder_summary_prompt(path: str, child_descriptions: str) -> str:
    return (
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


def _run_summary_prompt(model: str, prompt: str) -> str:
    completed = subprocess.run(
        ["ollama", "--nowordwrap", "run", model, prompt],
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )
    return _clean_ollama_output(completed.stdout)
