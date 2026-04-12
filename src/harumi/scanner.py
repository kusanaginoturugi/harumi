from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from pathlib import Path

from harumi.config import embedding_enabled, get_log_dir, summary_enabled
from harumi.db import (
    connect,
    get_enabled_roots_with_connection,
    upsert_folder_embedding,
    upsert_folder_record,
    upsert_folder_summary,
    upsert_fts_folder,
    upsert_embedding,
    upsert_document,
    upsert_file_record,
    upsert_fts_document,
    upsert_summary,
)
from harumi.embed import embed_text
from harumi.ignore_rules import is_ignored_directory, is_ignored_file
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


logger = logging.getLogger(__name__)


def _configure_scan_logger() -> None:
    if logger.handlers:
        return
    log_path = get_log_dir() / "scan-errors.log"
    handler = logging.FileHandler(log_path, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)


def _build_folder_child_descriptions(folder_path: Path) -> str:
    child_lines: list[str] = []
    try:
        entries = sorted(folder_path.iterdir(), key=lambda path: path.name.lower())
    except OSError:
        return ""

    for entry in entries[:20]:
        if entry.is_dir():
            child_lines.append(f"folder: {entry.name}")
            continue
        if is_ignored_file(entry):
            continue
        suffix = entry.suffix.lower() or "(no extension)"
        child_lines.append(f"file: {entry.name} ({suffix})")

    return "\n".join(child_lines)


def _folder_fingerprint(folder_path: Path, dirnames: list[str], filenames: list[str]) -> str:
    parts: list[str] = [str(folder_path)]
    parts.extend(f"dir:{name}" for name in sorted(dirnames))
    parts.extend(f"file:{name}" for name in sorted(name for name in filenames if not is_ignored_file(folder_path / name)))
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


def _index_folder(
    db_path: Path,
    *,
    root_id: int,
    folder_path: Path,
    dirnames: list[str],
    filenames: list[str],
    stats: ScanStats,
    connection,
) -> None:
    latest_mtime = 0.0
    for name in filenames:
        candidate = folder_path / name
        if is_ignored_file(candidate):
            continue
        try:
            latest_mtime = max(latest_mtime, candidate.stat().st_mtime)
        except OSError:
            continue

    fingerprint = _folder_fingerprint(folder_path, dirnames, filenames)
    folder_id, folder_changed = upsert_folder_record(
        db_path,
        root_id=root_id,
        path=str(folder_path),
        parent_path=str(folder_path.parent),
        folder_name=folder_path.name,
        file_count=len([name for name in filenames if not is_ignored_file(folder_path / name)]),
        child_folder_count=len(dirnames),
        latest_mtime=latest_mtime,
        content_fingerprint=fingerprint,
        connection=connection,
    )
    stats.folders_indexed += 1

    child_descriptions = _build_folder_child_descriptions(folder_path)
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


def run_scan(db_path: Path) -> ScanStats:
    _configure_scan_logger()
    stats = ScanStats()
    with connect(db_path) as connection:
        roots = get_enabled_roots_with_connection(connection)
        for root in roots:
            root_path = Path(root["path"])
            if not root_path.exists() or not root_path.is_dir():
                stats.failed += 1
                logger.error("Missing or invalid root: %s", root_path)
                continue

            for current_root, dirnames, filenames in root_path.walk():
                dirnames[:] = [name for name in dirnames if not is_ignored_directory(current_root / name)]
                stats.ignored += len([name for name in filenames if is_ignored_file(current_root / name)])

                try:
                    _index_folder(
                        db_path,
                        root_id=int(root["id"]),
                        folder_path=current_root,
                        dirnames=dirnames,
                        filenames=filenames,
                        stats=stats,
                        connection=connection,
                    )
                except Exception:
                    stats.failed += 1
                    logger.exception("Folder indexing failed: %s", current_root)
                    continue

                for filename in filenames:
                    file_path = current_root / filename
                    if is_ignored_file(file_path):
                        continue

                    stats.discovered += 1
                    try:
                        file_stat = file_path.stat()
                        status, file_id = upsert_file_record(
                            db_path,
                            root_id=int(root["id"]),
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
                        continue

                    if status == "indexed":
                        stats.indexed += 1
                    elif status == "updated":
                        stats.updated += 1
                    elif status == "unchanged":
                        stats.unchanged += 1

                    if status in {"indexed", "updated"}:
                        try:
                            document = normalize_file(file_path)
                            if document is None:
                                stats.normalization_skipped += 1
                            else:
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
                            continue

    return stats
