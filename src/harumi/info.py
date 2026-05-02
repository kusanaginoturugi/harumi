from __future__ import annotations

from pathlib import Path

from rich.console import Console
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from harumi.config import (
    APP_DIR_ENV,
    CONFIG_SCHEMA,
    _get_value,
    embedding_enabled,
    ensure_app_dirs,
    get_app_dir,
    get_embed_model,
    get_summary_language,
    get_summary_min_chars,
    get_summary_model,
    summary_code_enabled,
    summary_enabled,
    value_source,
)
from harumi.db import connect, count_index_stats, get_db_path, init_db


def _human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n //= 1024
    return f"{n:.1f} TB"


def _dir_size(path: Path) -> int:
    total = 0
    for p in path.rglob("*"):
        if p.is_file():
            try:
                total += p.stat().st_size
            except OSError:
                pass
    return total


def _pct(part: int, total: int) -> str:
    if total == 0:
        return ""
    return f"{part * 100 // total}%"


def _ok(v: bool) -> Text:
    return Text("enabled", style="green") if v else Text("disabled", style="dim yellow")


def info_command() -> int:
    app_dir = ensure_app_dirs()
    db_path = get_db_path(app_dir)
    init_db(db_path)

    console = Console()

    # --- Roots ---
    console.print(Rule("Roots", style="bold"))
    with connect(db_path) as conn:
        root_rows = conn.execute("""
            SELECT roots.id, roots.path, roots.enabled,
                   COUNT(files.id) AS file_count
            FROM roots
            LEFT JOIN files ON files.root_id = roots.id
            GROUP BY roots.id
            ORDER BY roots.path
        """).fetchall()

    if not root_rows:
        console.print("  (no roots configured)", style="dim")
    else:
        t = Table(show_header=True, box=None, padding=(0, 2, 0, 0), header_style="dim")
        t.add_column("#", justify="right")
        t.add_column("Path")
        t.add_column("Files", justify="right")
        t.add_column("Status")
        for row in root_rows:
            status = Text("enabled", style="green") if row["enabled"] else Text("disabled", style="dim yellow")
            t.add_row(str(row["id"]), row["path"], str(row["file_count"]), status)
        console.print(t)

    # --- Index ---
    console.print(Rule("Index", style="bold"))
    stats = count_index_stats(db_path)
    with connect(db_path) as conn:
        last_scan_row = conn.execute("SELECT MAX(last_scanned_at) AS ts FROM files").fetchone()
    last_scan = (last_scan_row["ts"] or "(never)") if last_scan_row else "(never)"

    files = stats["files"]
    t = Table(show_header=False, box=None, padding=(0, 2, 0, 0))
    t.add_column("key", style="dim", min_width=14)
    t.add_column("value", justify="right", min_width=6)
    t.add_column("note", style="dim")
    t.add_row("Files", str(files), "")
    t.add_row("Folders", str(stats["folders"]), "")
    t.add_row("Documents", str(stats["documents"]), _pct(stats["documents"], files))
    t.add_row("Summaries", str(stats["summaries"]), _pct(stats["summaries"], files))
    t.add_row("Embeddings", str(stats["embeddings"]), _pct(stats["embeddings"], files))
    t.add_row("Activity events", str(stats.get("activity_events", 0)), "")
    t.add_row("Last scan", last_scan[:16], "")
    console.print(t)

    # --- Storage ---
    console.print(Rule("Storage", style="bold"))
    db_size = db_path.stat().st_size if db_path.exists() else 0
    cache_dir = app_dir / "cache"
    cache_size = _dir_size(cache_dir) if cache_dir.exists() else 0

    t = Table(show_header=False, box=None, padding=(0, 2, 0, 0))
    t.add_column("key", style="dim", min_width=8)
    t.add_column("path", style="dim")
    t.add_column("size", justify="right")
    t.add_row("DB", str(db_path), _human_size(db_size))
    t.add_row("Cache", str(cache_dir), _human_size(cache_size))
    console.print(t)

    # --- LLM ---
    console.print(Rule("LLM", style="bold"))
    t = Table(show_header=False, box=None, padding=(0, 2, 0, 0))
    t.add_column("key", style="dim", min_width=12)
    t.add_column("model")
    t.add_column("status")
    t.add_column("note", style="dim")
    t.add_row("Summary", get_summary_model(), _ok(summary_enabled()), f"lang={get_summary_language()}  min_chars={get_summary_min_chars()}  code={'yes' if summary_code_enabled() else 'no'}")
    t.add_row("Embedding", get_embed_model(), _ok(embedding_enabled()), "")
    console.print(t)

    # --- Config ---
    console.print(Rule("Config", style="bold"))
    t = Table(show_header=False, box=None, padding=(0, 2, 0, 0))
    t.add_column("key", style="dim")
    t.add_column("value")
    t.add_column("source", style="dim")
    for key, (env_var, _, _, _) in CONFIG_SCHEMA.items():
        src = value_source(key)
        src_text = Text(src, style="green" if src == "config" else ("yellow" if src == "env" else "dim"))
        t.add_row(key, str(_get_value(key)), src_text)
    console.print(t)

    return 0
