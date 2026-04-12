from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from harumi.config import embedding_enabled, summary_enabled
from harumi.db import (
    iter_documents_for_regeneration,
    iter_folders_for_regeneration,
    purge_summary_artifacts,
    upsert_embedding,
    upsert_folder_embedding,
    upsert_folder_summary,
    upsert_fts_document,
    upsert_fts_folder,
    upsert_summary,
)
from harumi.embed import embed_text
from harumi.ignore_rules import is_ignored_file
from harumi.summarize import (
    PROMPT_VERSION,
    should_summarize_folder,
    should_summarize_text,
    summarize_folder,
    summarize_text,
)


@dataclass
class RegenerationStats:
    file_documents_seen: int = 0
    file_summaries_regenerated: int = 0
    file_summary_skipped: int = 0
    file_summary_failed: int = 0
    file_embeddings_regenerated: int = 0
    file_embedding_failed: int = 0
    folders_seen: int = 0
    folder_summaries_regenerated: int = 0
    folder_summary_skipped: int = 0
    folder_summary_failed: int = 0
    folder_embeddings_regenerated: int = 0
    folder_embedding_failed: int = 0


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


def regenerate_summaries(
    db_path: Path,
    *,
    scope: str,
    limit: int | None = None,
    purge_only: bool = False,
) -> RegenerationStats:
    purge_summary_artifacts(db_path, scope)
    stats = RegenerationStats()
    if purge_only:
        return stats

    if scope in {"all", "files"}:
        for row in iter_documents_for_regeneration(db_path, limit=limit):
            stats.file_documents_seen += 1
            summary_short = ""
            if summary_enabled() and should_summarize_text(
                row["path"],
                row["normalized_text"],
                row["normalized_format"],
            ):
                try:
                    summary_short, model_name = summarize_text(row["path"], row["normalized_text"])
                    if summary_short:
                        upsert_summary(
                            db_path,
                            file_id=row["file_id"],
                            summary_short=summary_short,
                            model_name=model_name,
                            prompt_version=PROMPT_VERSION,
                        )
                        stats.file_summaries_regenerated += 1
                except Exception:
                    stats.file_summary_failed += 1
            elif summary_enabled():
                stats.file_summary_skipped += 1

            if embedding_enabled():
                embedding_source = summary_short or row["normalized_text"][:4000]
                try:
                    vector, model_name = embed_text(embedding_source)
                    upsert_embedding(
                        db_path,
                        file_id=row["file_id"],
                        model_name=model_name,
                        vector=vector,
                        source_text=embedding_source,
                    )
                    stats.file_embeddings_regenerated += 1
                except Exception:
                    stats.file_embedding_failed += 1

            upsert_fts_document(
                db_path,
                file_id=row["file_id"],
                path=row["path"],
                filename=row["filename"],
                extension=row["extension"],
                parent_path=row["parent_path"],
                normalized_text=row["normalized_text"],
                summary_short=summary_short,
            )

    if scope in {"all", "folders"}:
        for row in iter_folders_for_regeneration(db_path, limit=limit):
            stats.folders_seen += 1
            folder_path = Path(row["path"])
            child_descriptions = _build_folder_child_descriptions(folder_path)
            if not child_descriptions:
                stats.folder_summary_skipped += 1
                continue

            summary_short = ""
            if summary_enabled() and should_summarize_folder(child_descriptions):
                try:
                    summary_short, model_name = summarize_folder(row["path"], child_descriptions)
                    if summary_short:
                        upsert_folder_summary(
                            db_path,
                            folder_id=row["id"],
                            summary_short=summary_short,
                            model_name=model_name,
                            prompt_version=PROMPT_VERSION,
                        )
                        stats.folder_summaries_regenerated += 1
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
                        folder_id=row["id"],
                        model_name=model_name,
                        vector=vector,
                        source_text=embedding_source,
                    )
                    stats.folder_embeddings_regenerated += 1
                except Exception:
                    stats.folder_embedding_failed += 1

            upsert_fts_folder(
                db_path,
                folder_id=row["id"],
                path=row["path"],
                folder_name=row["folder_name"],
                summary_short=summary_short,
            )

    return stats
