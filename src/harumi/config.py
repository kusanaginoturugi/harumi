from __future__ import annotations

import os
import tomllib
from pathlib import Path


# ── env var names ──────────────────────────────────────────────────────────────
APP_DIR_ENV = "HARUMI_HOME"
CONFIG_FILE_ENV = "HARUMI_CONFIG"
SUMMARY_MODEL_ENV = "HARUMI_SUMMARY_MODEL"
SUMMARY_ENABLED_ENV = "HARUMI_ENABLE_SUMMARY"
SUMMARY_MIN_CHARS_ENV = "HARUMI_SUMMARY_MIN_CHARS"
SUMMARY_CODE_ENABLED_ENV = "HARUMI_SUMMARY_CODE"
FOLDER_SUMMARY_MIN_ITEMS_ENV = "HARUMI_FOLDER_SUMMARY_MIN_ITEMS"
SUMMARY_LANGUAGE_ENV = "HARUMI_SUMMARY_LANGUAGE"
EMBED_MODEL_ENV = "HARUMI_EMBED_MODEL"
EMBED_ENABLED_ENV = "HARUMI_ENABLE_EMBEDDING"

# ── config file key metadata ───────────────────────────────────────────────────
# key → (env_var, python_type, default_value, description)
CONFIG_SCHEMA: dict[str, tuple[str, type, object, str]] = {
    "summary_model":          (SUMMARY_MODEL_ENV,          str,  "gemma3:latest", "Ollama model for summaries"),
    "embed_model":            (EMBED_MODEL_ENV,             str,  "embeddinggemma", "Ollama model for embeddings"),
    "summary_language":       (SUMMARY_LANGUAGE_ENV,        str,  "ja",            "Summary output language (ja/en/...)"),
    "summary_enabled":        (SUMMARY_ENABLED_ENV,         bool, True,            "Enable summary generation"),
    "embedding_enabled":      (EMBED_ENABLED_ENV,           bool, True,            "Enable embedding generation"),
    "summary_min_chars":      (SUMMARY_MIN_CHARS_ENV,       int,  400,             "Minimum chars before summarizing"),
    "summary_code":           (SUMMARY_CODE_ENABLED_ENV,    bool, False,           "Summarize code files"),
    "folder_summary_min_items": (FOLDER_SUMMARY_MIN_ITEMS_ENV, int, 2,            "Min child items to summarize a folder"),
}

_config_cache: dict | None = None


# ── paths ──────────────────────────────────────────────────────────────────────

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


def get_config_file_path() -> Path:
    env = os.environ.get(CONFIG_FILE_ENV)
    if env:
        return Path(env).expanduser().resolve()
    return Path.home() / ".config" / "harumi" / "config.toml"


# ── config file loading ────────────────────────────────────────────────────────

def _load_config_file() -> dict:
    global _config_cache
    if _config_cache is not None:
        return _config_cache
    path = get_config_file_path()
    if not path.exists():
        _config_cache = {}
        return _config_cache
    try:
        with open(path, "rb") as f:
            _config_cache = tomllib.load(f)
    except Exception:
        _config_cache = {}
    return _config_cache


def _invalidate_config_cache() -> None:
    global _config_cache
    _config_cache = None


def _get_value(key: str) -> object:
    """Return the effective value for a config key. Priority: env > config file > default."""
    env_var, typ, default, _ = CONFIG_SCHEMA[key]

    if env_var in os.environ:
        raw = os.environ[env_var].strip().lower()
        if typ is bool:
            return raw not in {"0", "false", "no", "off"}
        if typ is int:
            try:
                return max(0, int(raw))
            except ValueError:
                return default
        return os.environ[env_var]

    cfg = _load_config_file()
    if key in cfg:
        val = cfg[key]
        if typ is bool and not isinstance(val, bool):
            return str(val).lower() not in {"0", "false", "no", "off"}
        if typ is int and not isinstance(val, int):
            try:
                return int(val)
            except (ValueError, TypeError):
                return default
        return val

    return default


def value_source(key: str) -> str:
    """Return 'env', 'config', or 'default' for the given key."""
    env_var, _, _, _ = CONFIG_SCHEMA[key]
    if env_var in os.environ:
        return "env"
    if key in _load_config_file():
        return "config"
    return "default"


# ── public accessors ───────────────────────────────────────────────────────────

def get_summary_model() -> str:
    return str(_get_value("summary_model"))


def summary_enabled() -> bool:
    return bool(_get_value("summary_enabled"))


def get_summary_min_chars() -> int:
    v = _get_value("summary_min_chars")
    return int(v) if isinstance(v, (int, str)) else 400


def summary_code_enabled() -> bool:
    return bool(_get_value("summary_code"))


def get_folder_summary_min_items() -> int:
    v = _get_value("folder_summary_min_items")
    return max(1, int(v)) if isinstance(v, (int, str)) else 2


def get_summary_language() -> str:
    v = str(_get_value("summary_language")).strip().lower()
    return v or "ja"


def get_embed_model() -> str:
    return str(_get_value("embed_model"))


def embedding_enabled() -> bool:
    return bool(_get_value("embedding_enabled"))
