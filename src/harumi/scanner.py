from __future__ import annotations

import hashlib
import logging
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from harumi.config import embedding_enabled, get_log_dir, summary_enabled
from harumi.db import (
    connect,
    get_enabled_roots_with_connection,
    get_scan_state_with_connection,
    upsert_folder_embedding,
    upsert_folder_record,
    upsert_folder_summary,
    upsert_fts_folder,
    upsert_embedding,
    upsert_document,
    upsert_file_record,
    upsert_fts_document,
    upsert_scan_state,
    upsert_summary,
)
from harumi.embed import embed_text
from harumi.ignore_rules import (
    IGNORED_DIR_NAMES,
    IgnoreMatcher,
    is_ignored_directory,
    is_ignored_file,
    load_ignore_matcher,
)
from harumi.normalize import normalize_file
from harumi.summarize import (
    PROMPT_VERSION,
    should_summarize_folder,
    should_summarize_text,
    summarize_folder,
    summarize_text,
)


@dataclass
class ScanStats:
    discovered: int = 0
    ignored: int = 0
    indexed: int = 0
    updated: int = 0
    unchanged: int = 0
    normalized: int = 0
    normalization_skipped: int = 0
    summarized: int = 0
    summary_skipped: int = 0
    summary_failed: int = 0
    embedded: int = 0
    embedding_failed: int = 0
    folders_indexed: int = 0
    folder_summarized: int = 0
    folder_summary_skipped: int = 0
    folder_summary_failed: int = 0
    folder_embedded: int = 0
    folder_embedding_failed: int = 0
    folder_skipped: int = 0
    failed: int = 0
    full_scan_fallbacks: int = 0
    scan_kind: str = ""


ScanProgressCallback = Callable[[ScanStats, int, int, str], None]


logger = logging.getLogger(__name__)


def _configure_scan_logger() -> None:
    if logger.handlers:
        return
    log_path = get_log_dir() / "scan-errors.log"
    handler = logging.FileHandler(log_path, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)


def _build_folder_child_descriptions(folder_path: Path, matcher: IgnoreMatcher) -> str:
    child_lines: list[str] = []
    try:
        entries = sorted(folder_path.iterdir(), key=lambda path: path.name.lower())
    except OSError:
        return ""

    for entry in entries[:20]:
        if entry.is_dir():
            child_lines.append(f"folder: {entry.name}")
            continue
        if is_ignored_file(entry, matcher):
            continue
        suffix = entry.suffix.lower() or "(no extension)"
        child_lines.append(f"file: {entry.name} ({suffix})")

    return "\n".join(child_lines)


def _folder_fingerprint(
    folder_path: Path, dirnames: list[str], filenames: list[str], matcher: IgnoreMatcher
) -> str:
    parts: list[str] = [str(folder_path)]
    parts.extend(f"dir:{name}" for name in sorted(dirnames))
    parts.extend(
        f"file:{name}"
        for name in sorted(name for name in filenames if not is_ignored_file(folder_path / name, matcher))
    )
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


def _count_scan_items(root_path: Path, matcher: IgnoreMatcher) -> int:
    count = 0
    for current_root, dirnames, filenames in root_path.walk():
        dirnames[:] = [
            name for name in dirnames if not is_ignored_directory(current_root / name, matcher)
        ]
        count += 1
        count += sum(1 for name in filenames if not is_ignored_file(current_root / name, matcher))
    return count


def _index_folder(
    db_path: Path,
    *,
    root_id: int,
    folder_path: Path,
    dirnames: list[str],
    filenames: list[str],
    stats: ScanStats,
    connection,
    matcher: IgnoreMatcher,
) -> None:
    latest_mtime = 0.0
    for name in filenames:
        candidate = folder_path / name
        if is_ignored_file(candidate, matcher):
            continue
        try:
            latest_mtime = max(latest_mtime, candidate.stat().st_mtime)
        except OSError:
            continue

    fingerprint = _folder_fingerprint(folder_path, dirnames, filenames, matcher)
    folder_id, folder_changed = upsert_folder_record(
        db_path,
        root_id=root_id,
        path=str(folder_path),
        parent_path=str(folder_path.parent),
        folder_name=folder_path.name,
        file_count=len([name for name in filenames if not is_ignored_file(folder_path / name, matcher)]),
        child_folder_count=len(dirnames),
        latest_mtime=latest_mtime,
        content_fingerprint=fingerprint,
        connection=connection,
    )
    stats.folders_indexed += 1

    child_descriptions = _build_folder_child_descriptions(folder_path, matcher)
    if not child_descriptions:
        return
    if not folder_changed:
        stats.folder_skipped += 1
        return

    summary_short = ""
    if summary_enabled() and should_summarize_folder(child_descriptions):
        try:
            summary_short, model_name = summarize_folder(str(folder_path), child_descriptions)
            if summary_short:
                upsert_folder_summary(
                    db_path,
                    folder_id=folder_id,
                    summary_short=summary_short,
                    model_name=model_name,
                    prompt_version=PROMPT_VERSION,
                    connection=connection,
                )
                stats.folder_summarized += 1
        except Exception:
            stats.folder_summary_failed += 1
    elif summary_enabled():
        stats.folder_summary_skipped += 1

    if embedding_enabled():
        embedding_source = summary_short or child_descriptions[:4000]
        try:
            vector, model_name = embed_text(embedding_source)
            upsert_folder_embedding(
                db_path,
                folder_id=folder_id,
                model_name=model_name,
                vector=vector,
                source_text=embedding_source,
                connection=connection,
            )
            stats.folder_embedded += 1
        except Exception:
            stats.folder_embedding_failed += 1

    upsert_fts_folder(
        db_path,
        folder_id=folder_id,
        path=str(folder_path),
        folder_name=folder_path.name,
        summary_short=summary_short,
        connection=connection,
    )


def _index_file(
    db_path: Path,
    *,
    root_id: int,
    file_path: Path,
    stats: ScanStats,
    connection,
) -> None:
    stats.discovered += 1
    try:
        file_stat = file_path.stat()
        status, file_id = upsert_file_record(
            db_path,
            root_id=root_id,
            path=str(file_path),
            parent_path=str(file_path.parent),
            filename=file_path.name,
            extension=file_path.suffix.lower(),
            size_bytes=file_stat.st_size,
            mtime=file_stat.st_mtime,
            connection=connection,
        )
    except Exception:
        stats.failed += 1
        logger.exception("File stat/upsert failed: %s", file_path)
        return

    if status == "indexed":
        stats.indexed += 1
    elif status == "updated":
        stats.updated += 1
    elif status == "unchanged":
        stats.unchanged += 1

    if status not in {"indexed", "updated"}:
        return

    try:
        document = normalize_file(file_path)
        if document is None:
            stats.normalization_skipped += 1
            return

        upsert_document(
            db_path,
            file_id=file_id,
            normalized_text=document.text,
            normalized_format=document.format,
            connection=connection,
        )
        summary_short = ""
        if summary_enabled() and should_summarize_text(
            str(file_path),
            document.text,
            document.format,
        ):
            try:
                summary_short, model_name = summarize_text(str(file_path), document.text)
                if summary_short:
                    upsert_summary(
                        db_path,
                        file_id=file_id,
                        summary_short=summary_short,
                        model_name=model_name,
                        prompt_version=PROMPT_VERSION,
                        connection=connection,
                    )
                    stats.summarized += 1
            except Exception:
                stats.summary_failed += 1
        elif summary_enabled():
            stats.summary_skipped += 1

        if embedding_enabled():
            embedding_source = summary_short or document.text[:4000]
            try:
                vector, model_name = embed_text(embedding_source)
                upsert_embedding(
                    db_path,
                    file_id=file_id,
                    model_name=model_name,
                    vector=vector,
                    source_text=embedding_source,
                    connection=connection,
                )
                stats.embedded += 1
            except Exception:
                stats.embedding_failed += 1

        upsert_fts_document(
            db_path,
            file_id=file_id,
            path=str(file_path),
            filename=file_path.name,
            extension=file_path.suffix.lower(),
            parent_path=str(file_path.parent),
            normalized_text=document.text,
            summary_short=summary_short,
            connection=connection,
        )
        stats.normalized += 1
    except Exception:
        stats.failed += 1
        logger.exception("File normalization/indexing failed: %s", file_path)


def _folder_child_names(folder_path: Path, matcher: IgnoreMatcher) -> tuple[list[str], list[str]]:
    dirnames: list[str] = []
    filenames: list[str] = []
    try:
        entries = sorted(folder_path.iterdir(), key=lambda path: path.name.lower())
    except OSError:
        return dirnames, filenames

    for entry in entries:
        if entry.is_dir():
            if not is_ignored_directory(entry, matcher):
                dirnames.append(entry.name)
        elif entry.is_file():
            filenames.append(entry.name)
    return dirnames, filenames


def _folder_lineage(folder_path: Path, root_path: Path) -> list[Path]:
    folders: list[Path] = []
    current = folder_path
    root_resolved = root_path.resolve()
    while True:
        try:
            current.resolve().relative_to(root_resolved)
        except ValueError:
            break
        folders.append(current)
        if current.resolve() == root_resolved:
            break
        current = current.parent
    return folders


def _find_recent_files(root_path: Path, cutoff: float, matcher: IgnoreMatcher) -> list[Path]:
    args = ["find", str(root_path)]
    if IGNORED_DIR_NAMES:
        args.append("(")
        for index, name in enumerate(sorted(IGNORED_DIR_NAMES)):
            if index:
                args.append("-o")
            args.extend(["-name", name])
        args.extend([")", "-type", "d", "-prune", "-o"])
    args.extend(["-type", "f", "-newermt", f"@{cutoff}", "-print0"])

    try:
        completed = subprocess.run(
            args,
            check=True,
            capture_output=True,
        )
        raw_paths = [value for value in completed.stdout.split(b"\0") if value]
        paths = [Path(value.decode("utf-8", errors="surrogateescape")) for value in raw_paths]
    except (OSError, subprocess.CalledProcessError):
        paths = []
        for current_root, dirnames, filenames in root_path.walk():
            dirnames[:] = [
                name for name in dirnames if not is_ignored_directory(current_root / name, matcher)
            ]
            for filename in filenames:
                path = current_root / filename
                try:
                    if path.stat().st_mtime > cutoff:
                        paths.append(path)
                except OSError:
                    continue

    return [
        path
        for path in paths
        if path.exists() and path.is_file() and not is_ignored_file(path, matcher)
    ]


def run_scan(
    db_path: Path,
    *,
    progress_callback: ScanProgressCallback | None = None,
    progress_interval_seconds: float = 600.0,
    progress_percent_step: float = 1.0,
) -> ScanStats:
    _configure_scan_logger()
    stats = ScanStats()
    stats.scan_kind = "full"
    percent_progress_enabled = progress_percent_step > 0
    estimate_progress_total = progress_callback is not None and percent_progress_enabled
    with connect(db_path) as connection:
        roots = get_enabled_roots_with_connection(connection)
        valid_roots = []
        total_items = 0
        for root in roots:
            root_path = Path(root["path"])
            if not root_path.exists() or not root_path.is_dir():
                stats.failed += 1
                logger.error("Missing or invalid root: %s", root_path)
                continue
            valid_roots.append(root)
            if estimate_progress_total:
                try:
                    total_items += _count_scan_items(root_path, load_ignore_matcher(root_path))
                except Exception:
                    logger.exception("Progress estimation failed: %s", root_path)

        processed_items = 0
        last_progress_time = time.monotonic()
        next_progress_percent = progress_percent_step

        def maybe_emit_progress(current_path: str, *, force: bool = False) -> None:
            nonlocal last_progress_time, next_progress_percent
            if progress_callback is None:
                return

            now = time.monotonic()
            percent = (processed_items / total_items * 100.0) if total_items else 0.0
            should_emit = force or (now - last_progress_time >= progress_interval_seconds)
            if percent_progress_enabled and total_items and percent >= next_progress_percent:
                should_emit = True
                while percent >= next_progress_percent:
                    next_progress_percent += progress_percent_step

            if should_emit:
                progress_callback(stats, processed_items, total_items, current_path)
                last_progress_time = now

        maybe_emit_progress("scan started", force=True)
        for root in valid_roots:
            root_scan_started_at = time.time()
            root_path = Path(root["path"])
            ignore_matcher = load_ignore_matcher(root_path)

            for current_root, dirnames, filenames in root_path.walk():
                dirnames[:] = [
                    name
                    for name in dirnames
                    if not is_ignored_directory(current_root / name, ignore_matcher)
                ]
                stats.ignored += len(
                    [name for name in filenames if is_ignored_file(current_root / name, ignore_matcher)]
                )

                try:
                    _index_folder(
                        db_path,
                        root_id=int(root["id"]),
                        folder_path=current_root,
                        dirnames=dirnames,
                        filenames=filenames,
                        stats=stats,
                        connection=connection,
                        matcher=ignore_matcher,
                    )
                except Exception:
                    stats.failed += 1
                    logger.exception("Folder indexing failed: %s", current_root)
                    processed_items += sum(
                        1
                        for name in filenames
                        if not is_ignored_file(current_root / name, ignore_matcher)
                    )
                    maybe_emit_progress(str(current_root))
                    continue
                finally:
                    processed_items += 1
                    maybe_emit_progress(str(current_root))

                for filename in filenames:
                    file_path = current_root / filename
                    if is_ignored_file(file_path, ignore_matcher):
                        continue

                    _index_file(
                        db_path,
                        root_id=int(root["id"]),
                        file_path=file_path,
                        stats=stats,
                        connection=connection,
                    )
                    processed_items += 1
                    maybe_emit_progress(str(file_path))

            upsert_scan_state(
                db_path,
                root_id=int(root["id"]),
                started_at=root_scan_started_at,
                completed_at=time.time(),
                scan_kind="full",
                connection=connection,
            )

        maybe_emit_progress("scan complete", force=True)
    return stats


def run_quickscan(
    db_path: Path,
    *,
    progress_callback: ScanProgressCallback | None = None,
) -> ScanStats:
    _configure_scan_logger()
    stats = ScanStats()
    stats.scan_kind = "quick"
    needs_full_scan = False
    with connect(db_path) as connection:
        roots = get_enabled_roots_with_connection(connection)
        valid_roots = []
        for root in roots:
            root_path = Path(root["path"])
            if not root_path.exists() or not root_path.is_dir():
                stats.failed += 1
                logger.error("Missing or invalid root: %s", root_path)
                continue
            state = get_scan_state_with_connection(connection, int(root["id"]))
            if state is None or float(state["last_started_at"]) <= 0:
                stats.full_scan_fallbacks += 1
                needs_full_scan = True
                break
            valid_roots.append((root, float(state["last_started_at"])))

    if needs_full_scan:
        fallback_stats = run_scan(
            db_path,
            progress_callback=progress_callback,
            progress_percent_step=0.0,
        )
        fallback_stats.full_scan_fallbacks = stats.full_scan_fallbacks
        fallback_stats.scan_kind = "full"
        return fallback_stats

    with connect(db_path) as connection:
        processed_items = 0
        total_items = 0

        def emit(current_path: str, *, force: bool = False) -> None:
            if progress_callback is not None and (force or total_items):
                progress_callback(stats, processed_items, total_items, current_path)

        emit("quickscan started", force=True)
        for root, cutoff in valid_roots:
            root_scan_started_at = time.time()
            root_failed_before = stats.failed
            root_path = Path(root["path"])
            matcher = load_ignore_matcher(root_path)
            changed_files = _find_recent_files(root_path, cutoff, matcher)
            folder_paths: set[Path] = set()
            total_items += len(changed_files)

            for file_path in changed_files:
                _index_file(
                    db_path,
                    root_id=int(root["id"]),
                    file_path=file_path,
                    stats=stats,
                    connection=connection,
                )
                folder_paths.update(_folder_lineage(file_path.parent, root_path))
                processed_items += 1
                emit(str(file_path))

            total_items += len(folder_paths)
            for folder_path in sorted(folder_paths, key=lambda path: len(path.parts), reverse=True):
                dirnames, filenames = _folder_child_names(folder_path, matcher)
                try:
                    _index_folder(
                        db_path,
                        root_id=int(root["id"]),
                        folder_path=folder_path,
                        dirnames=dirnames,
                        filenames=filenames,
                        stats=stats,
                        connection=connection,
                        matcher=matcher,
                    )
                except Exception:
                    stats.failed += 1
                    logger.exception("Folder indexing failed: %s", folder_path)
                processed_items += 1
                emit(str(folder_path))

            if stats.failed == root_failed_before:
                upsert_scan_state(
                    db_path,
                    root_id=int(root["id"]),
                    started_at=root_scan_started_at,
                    completed_at=time.time(),
                    scan_kind="quick",
                    connection=connection,
                )

        emit("quickscan complete", force=True)
    return stats
