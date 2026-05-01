from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from rich.rule import Rule

from harumi.config import embedding_enabled, ensure_app_dirs
from harumi.db import (
    count_regeneration_targets,
    count_index_stats,
    get_db_path,
    init_db,
    insert_root,
    list_roots,
)
from harumi.maintenance import regenerate_summaries
from harumi.ranking import rank_results
from harumi.scanner import run_scan
from harumi.search import find_documents, find_similar_documents
from harumi.status import get_status_report


def _ensure_ready() -> Path:
    app_dir = ensure_app_dirs()
    db_path = get_db_path(app_dir)
    init_db(db_path)
    return db_path


def init_command() -> int:
    app_dir = ensure_app_dirs()
    db_path = get_db_path(app_dir)
    init_db(db_path)
    print(f"Initialized Harumi at {app_dir}")
    print(f"Database: {db_path}")
    return 0


def add_root_command(path: Path) -> int:
    resolved = path.expanduser().resolve()
    if not resolved.exists():
        print(f"Path does not exist: {resolved}", file=sys.stderr)
        return 2
    if not resolved.is_dir():
        print(f"Path is not a directory: {resolved}", file=sys.stderr)
        return 2

    db_path = _ensure_ready()
    created = insert_root(db_path, resolved)
    if created:
        print(f"Added root: {resolved}")
    else:
        print(f"Root already exists: {resolved}")
    return 0


def list_roots_command() -> int:
    db_path = _ensure_ready()
    rows = list_roots(db_path)
    if not rows:
        print("No roots configured.")
        return 0

    for row in rows:
        status = "enabled" if row["enabled"] else "disabled"
        print(f"{row['id']}\t{status}\t{row['path']}")
    return 0


def _shorten_path(value: str, max_len: int = 90) -> str:
    if len(value) <= max_len:
        return value
    return "..." + value[-(max_len - 3):]


def scan_command(progress_interval: float, progress_percent: float) -> int:
    db_path = _ensure_ready()
    started_at = time.monotonic()
    print("Scan progress: estimating scan size...", file=sys.stderr, flush=True)

    def print_progress(stats, processed: int, total: int, current_path: str) -> None:
        elapsed = int(time.monotonic() - started_at)
        percent = (processed / total * 100.0) if total else 0.0
        print(
            "Scan progress: "
            f"{processed}/{total or '?'} "
            f"({percent:.1f}%) "
            f"elapsed={elapsed}s "
            f"files={stats.discovered} "
            f"indexed={stats.indexed} "
            f"updated={stats.updated} "
            f"unchanged={stats.unchanged} "
            f"folders={stats.folders_indexed} "
            f"failed={stats.failed} "
            f"current={_shorten_path(current_path)}",
            file=sys.stderr,
            flush=True,
        )

    stats = run_scan(
        db_path,
        progress_callback=print_progress,
        progress_interval_seconds=progress_interval,
        progress_percent_step=progress_percent,
    )
    index_counts: dict[str, int] | None = None
    count_error: Exception | None = None
    try:
        index_counts = count_index_stats(db_path)
    except Exception as exc:
        count_error = exc

    print("Scan complete")
    print(f"Discovered: {stats.discovered}")
    print(f"Ignored: {stats.ignored}")
    print(f"Indexed: {stats.indexed}")
    print(f"Updated: {stats.updated}")
    print(f"Unchanged: {stats.unchanged}")
    print(f"Normalized: {stats.normalized}")
    print(f"Normalization skipped: {stats.normalization_skipped}")
    print(f"Summarized: {stats.summarized}")
    print(f"Summary skipped: {stats.summary_skipped}")
    print(f"Summary failed: {stats.summary_failed}")
    print(f"Embedded: {stats.embedded}")
    print(f"Embedding failed: {stats.embedding_failed}")
    print(f"Folders indexed: {stats.folders_indexed}")
    print(f"Folders skipped: {stats.folder_skipped}")
    print(f"Folders summarized: {stats.folder_summarized}")
    print(f"Folder summary skipped: {stats.folder_summary_skipped}")
    print(f"Folder summary failed: {stats.folder_summary_failed}")
    print(f"Folders embedded: {stats.folder_embedded}")
    print(f"Folder embedding failed: {stats.folder_embedding_failed}")
    print(f"Failed: {stats.failed}")
    if index_counts is not None:
        print(f"Tracked files: {index_counts['files']}")
        print(f"Tracked folders: {index_counts['folders']}")
        print(f"Normalized documents: {index_counts['documents']}")
        print(f"Summaries: {index_counts['summaries']}")
        print(f"Folder summaries: {index_counts['folder_summaries']}")
        print(f"Embeddings: {index_counts['embeddings']}")
        print(f"Folder embeddings: {index_counts['folder_embeddings']}")
    else:
        print("Index counts: unavailable")
        print(f"Count error: {count_error}")
    return 0


def status_command() -> int:
    for name, state, detail in get_status_report():
        print(f"{name}\t{state}\t{detail}")
    return 0


def regenerate_summaries_command(
    scope: str,
    execute: bool,
    confirm: str | None,
    purge_only: bool,
    limit: int | None,
) -> int:
    db_path = _ensure_ready()
    counts = count_regeneration_targets(db_path, scope)

    print("Dangerous operation: regenerate-summaries")
    print(f"Scope: {scope}")
    print(f"File documents in scope: {counts['file_documents']}")
    print(f"Folder records in scope: {counts['folder_records']}")
    print(f"Existing file summaries: {counts['file_summaries']}")
    print(f"Existing folder summaries: {counts['folder_summaries']}")
    print(f"Existing file embeddings: {counts['file_embeddings']}")
    print(f"Existing folder embeddings: {counts['folder_embeddings']}")
    if limit is not None:
        print(f"Limit: {limit}")
    print()
    print("This command deletes stored summaries and related embeddings before rebuilding them.")
    print("Use this when you intentionally want to change summary language or summary policy.")
    if purge_only:
        print("Mode: purge-only")
    else:
        print("Mode: purge and regenerate")

    if not execute or confirm != "RESET-SUMMARIES":
        print()
        print("Dry run only. No changes were made.")
        print("To execute, rerun with:")
        print("  --execute --confirm RESET-SUMMARIES")
        if purge_only:
            print("This will leave summaries empty until you regenerate them later.")
        return 0

    stats = regenerate_summaries(
        db_path,
        scope=scope,
        limit=limit,
        purge_only=purge_only,
    )
    print()
    print("Summary regeneration complete")
    print(f"File documents seen: {stats.file_documents_seen}")
    print(f"File summaries regenerated: {stats.file_summaries_regenerated}")
    print(f"File summary skipped: {stats.file_summary_skipped}")
    print(f"File summary failed: {stats.file_summary_failed}")
    print(f"File embeddings regenerated: {stats.file_embeddings_regenerated}")
    print(f"File embedding failed: {stats.file_embedding_failed}")
    print(f"Folders seen: {stats.folders_seen}")
    print(f"Folder summaries regenerated: {stats.folder_summaries_regenerated}")
    print(f"Folder summary skipped: {stats.folder_summary_skipped}")
    print(f"Folder summary failed: {stats.folder_summary_failed}")
    print(f"Folder embeddings regenerated: {stats.folder_embeddings_regenerated}")
    print(f"Folder embedding failed: {stats.folder_embedding_failed}")
    return 0


def _render_find_results(ranked_results: list[dict], limit: int, query: str) -> None:
    console = Console()

    console.print(
        Rule(f"[bold]harumi find[/bold] [dim]{query!r}[/dim]", style="bright_black")
    )

    for index, row in enumerate(ranked_results[:limit], start=1):
        is_folder = row["kind"] == "folder"

        # ── Title line ──────────────────────────────────────────────
        kind_badge = "[bold blue] folder [/bold blue]" if is_folder else "[bold cyan] file [/bold cyan]"
        title = Text()
        title.append(f" {index}. ", style="bold bright_white")
        title.append(row["path"], style="bold yellow")
        title.append("  ")
        title_str = title.markup + kind_badge

        # ── Body ────────────────────────────────────────────────────
        body = Text()

        # Metadata row
        if is_folder:
            meta = f"folder  ·  {row.get('file_count', 0)} files  ·  {row.get('child_folder_count', 0)} subfolders"
        else:
            ext = row["extension"] or "(no ext)"
            fmt = row["normalized_format"] or ""
            chars = row["char_count"]
            meta = f"{ext}  ·  {fmt}  ·  {chars:,} chars"
        body.append(meta + "\n", style="dim")

        # Score row
        score_line = Text()
        score_line.append("score ", style="dim")
        score_line.append(f"{row['final_score']:.4f}", style="bold green")
        score_line.append("  vector ", style="dim")
        score_line.append(f"{row['vector_score']:.4f}", style="cyan")
        if row["fts_score"] < 9999:
            score_line.append("  fts ", style="dim")
            score_line.append(f"{row['fts_score']:.4f}", style="cyan")
        body.append_text(score_line)
        body.append("\n")

        # Component row
        comp_line = Text()
        comp_line.append(
            f"v={row['vector_component']:.4f}  "
            f"f={row['fts_component']:.4f}  "
            f"recency={row['recency_component']:.4f}",
            style="dim",
        )
        if row["root_penalty"] > 0:
            comp_line.append(f"  root_penalty={row['root_penalty']:.4f}", style="dim red")
        if row["quality_penalty"] > 0:
            comp_line.append(f"  quality_penalty={row['quality_penalty']:.4f}", style="dim red")
        body.append_text(comp_line)
        body.append("\n")

        if row["reasons"]:
            body.append("reasons: " + ", ".join(row["reasons"]) + "\n", style="dim italic")

        # Summary
        if row["summary_short"]:
            body.append("\n")
            body.append(row["summary_short"] + "\n", style="italic")

        # Snippet
        if row["snippet"]:
            body.append("\n")
            body.append(f'"{row["snippet"]}"\n', style="dim italic")

        console.print(
            Panel(
                body,
                title=title_str,
                title_align="left",
                border_style="bright_black",
                padding=(0, 1),
            )
        )

    console.print(
        Rule(style="bright_black")
    )


def find_command(query: str, limit: int) -> int:
    db_path = _ensure_ready()
    fts_rows = find_documents(db_path, query, limit=limit)
    vector_rows = []
    if embedding_enabled():
        try:
            vector_rows = find_similar_documents(db_path, query, limit=limit)
        except Exception:
            vector_rows = []

    merged: dict[tuple[str, str], dict] = {}
    for row in fts_rows:
        merged[(row["kind"], row["path"])] = row

    for row in vector_rows:
        entry = merged.setdefault(
            (row["kind"], row["path"]),
            row,
        )
        entry["vector_score"] = max(entry["vector_score"], row["vector_score"])
        if not entry["summary_short"]:
            entry["summary_short"] = row["summary_short"]

    results = list(merged.values())
    if not results:
        Console().print("[dim]No matches found.[/dim]")
        return 0

    ranked_results = rank_results(query, results)
    _render_find_results(ranked_results, limit, query)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="harumi",
        description="Local-first file indexing assistant.",
    )
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("init", help="Initialize Harumi local storage.")
    scan_parser = subparsers.add_parser("scan", help="Scan enabled roots and collect file metadata.")
    scan_parser.add_argument(
        "--progress-interval",
        type=float,
        default=600.0,
        help="Emit scan progress at least every N seconds.",
    )
    scan_parser.add_argument(
        "--progress-percent",
        type=float,
        default=1.0,
        help="Emit scan progress whenever another N percent is completed.",
    )
    subparsers.add_parser("status", help="Show local dependency and model readiness.")
    regen_parser = subparsers.add_parser(
        "regenerate-summaries",
        help="Dangerously purge and rebuild stored summaries and related embeddings.",
    )
    regen_parser.add_argument(
        "--scope",
        choices=("all", "files", "folders"),
        default="all",
    )
    regen_parser.add_argument("--execute", action="store_true")
    regen_parser.add_argument("--confirm")
    regen_parser.add_argument("--purge-only", action="store_true")
    regen_parser.add_argument("--limit", type=int)
    find_parser = subparsers.add_parser("find", help="Search normalized documents.")
    find_parser.add_argument("query")
    find_parser.add_argument("--limit", type=int, default=10)

    roots_parser = subparsers.add_parser("roots", help="Manage indexed root directories.")
    roots_subparsers = roots_parser.add_subparsers(dest="roots_command")

    roots_add_parser = roots_subparsers.add_parser("add", help="Register a root directory.")
    roots_add_parser.add_argument("path", type=Path)

    roots_subparsers.add_parser("list", help="List registered root directories.")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "init":
        return init_command()
    if args.command == "scan":
        return scan_command(args.progress_interval, args.progress_percent)
    if args.command == "status":
        return status_command()
    if args.command == "regenerate-summaries":
        return regenerate_summaries_command(
            args.scope,
            args.execute,
            args.confirm,
            args.purge_only,
            args.limit,
        )
    if args.command == "find":
        return find_command(args.query, args.limit)
    if args.command == "roots" and args.roots_command == "add":
        return add_root_command(args.path)
    if args.command == "roots" and args.roots_command == "list":
        return list_roots_command()

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
