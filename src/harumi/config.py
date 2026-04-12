from __future__ import annotations

import os
from pathlib import Path


APP_DIR_ENV = "HARUMI_HOME"
SUMMARY_MODEL_ENV = "HARUMI_SUMMARY_MODEL"
SUMMARY_ENABLED_ENV = "HARUMI_ENABLE_SUMMARY"
SUMMARY_MIN_CHARS_ENV = "HARUMI_SUMMARY_MIN_CHARS"
SUMMARY_CODE_ENABLED_ENV = "HARUMI_SUMMARY_CODE"
FOLDER_SUMMARY_MIN_ITEMS_ENV = "HARUMI_FOLDER_SUMMARY_MIN_ITEMS"
SUMMARY_LANGUAGE_ENV = "HARUMI_SUMMARY_LANGUAGE"
EMBED_MODEL_ENV = "HARUMI_EMBED_MODEL"
EMBED_ENABLED_ENV = "HARUMI_ENABLE_EMBEDDING"


def get_app_dir() -> Path:
    env_value = os.environ.get(APP_DIR_ENV)
    if env_value:
        return Path(env_value).expanduser().resolve()
    return (Path.home() / ".local" / "share" / "harumi").resolve()


def ensure_app_dirs() -> Path:
    app_dir = get_app_dir()
    for path in (
        app_dir,
        app_dir / "cache",
        app_dir / "cache" / "normalized",
        app_dir / "cache" / "summaries",
        app_dir / "logs",
    ):
        path.mkdir(parents=True, exist_ok=True)
    return app_dir


def get_log_dir() -> Path:
    return ensure_app_dirs() / "logs"


def get_summary_model() -> str:
    return os.environ.get(SUMMARY_MODEL_ENV, "gemma3:latest")


def summary_enabled() -> bool:
    value = os.environ.get(SUMMARY_ENABLED_ENV, "1").strip().lower()
    return value not in {"0", "false", "no", "off"}


def get_summary_min_chars() -> int:
    raw = os.environ.get(SUMMARY_MIN_CHARS_ENV, "400").strip()
    try:
        return max(0, int(raw))
    except ValueError:
        return 400


def summary_code_enabled() -> bool:
    value = os.environ.get(SUMMARY_CODE_ENABLED_ENV, "0").strip().lower()
    return value not in {"0", "false", "no", "off"}


def get_folder_summary_min_items() -> int:
    raw = os.environ.get(FOLDER_SUMMARY_MIN_ITEMS_ENV, "2").strip()
    try:
        return max(1, int(raw))
    except ValueError:
        return 2


def get_summary_language() -> str:
    value = os.environ.get(SUMMARY_LANGUAGE_ENV, "ja").strip().lower()
    if not value:
        return "ja"
    return value


def get_embed_model() -> str:
    return os.environ.get(EMBED_MODEL_ENV, "embeddinggemma")


def embedding_enabled() -> bool:
    value = os.environ.get(EMBED_ENABLED_ENV, "1").strip().lower()
    return value not in {"0", "false", "no", "off"}
