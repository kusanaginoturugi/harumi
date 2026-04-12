from __future__ import annotations

import importlib.util
import json
import shutil
import urllib.error
import urllib.request

from harumi.config import (
    embedding_enabled,
    ensure_app_dirs,
    get_embed_model,
    get_summary_model,
    summary_enabled,
)


def _command_available(name: str) -> bool:
    return shutil.which(name) is not None


def _module_available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def _fetch_ollama_models() -> tuple[bool, list[str], str]:
    request = urllib.request.Request("http://127.0.0.1:11434/api/tags", method="GET")
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        return False, [], str(exc)

    models = [item.get("name", "") for item in data.get("models", []) if item.get("name")]
    return True, models, ""


def _model_installed(model_name: str, installed_models: list[str]) -> bool:
    if model_name in installed_models:
        return True
    if ":" not in model_name and f"{model_name}:latest" in installed_models:
        return True
    return False


def get_status_report() -> list[tuple[str, str, str]]:
    app_dir = ensure_app_dirs()
    summary_model = get_summary_model()
    embed_model = get_embed_model()

    rows: list[tuple[str, str, str]] = []
    rows.append(("app_dir", "ok", str(app_dir)))
    rows.append(("ollama_command", "ok" if _command_available("ollama") else "missing", "ollama CLI"))
    rows.append(("markitdown_module", "ok" if _module_available("markitdown") else "missing", "Python module"))
    rows.append(("summary_enabled", "ok" if summary_enabled() else "disabled", summary_model))
    rows.append(("embedding_enabled", "ok" if embedding_enabled() else "disabled", embed_model))

    connected, models, error = _fetch_ollama_models()
    if not connected:
        rows.append(("ollama_server", "error", error))
        return rows

    rows.append(("ollama_server", "ok", "127.0.0.1:11434"))
    rows.append(("ollama_models", "ok", ", ".join(models) if models else "(none)"))

    if summary_enabled():
        rows.append(
            (
                "summary_model",
                "ok" if _model_installed(summary_model, models) else "missing",
                summary_model,
            )
        )
    if embedding_enabled():
        rows.append(
            (
                "embedding_model",
                "ok" if _model_installed(embed_model, models) else "missing",
                embed_model,
            )
        )

    return rows
