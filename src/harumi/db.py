from __future__ import annotations

import json
import sqlite3
import time
from contextlib import nullcontext
from pathlib import Path


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS roots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    path TEXT NOT NULL UNIQUE,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS scan_state (
    root_id INTEGER PRIMARY KEY,
    last_started_at REAL NOT NULL DEFAULT 0,
    last_completed_at REAL NOT NULL DEFAULT 0,
    last_full_started_at REAL NOT NULL DEFAULT 0,
    last_full_completed_at REAL NOT NULL DEFAULT 0,
    last_quick_started_at REAL NOT NULL DEFAULT 0,
    last_quick_completed_at REAL NOT NULL DEFAULT 0,
    scan_kind TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(root_id) REFERENCES roots(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    root_id INTEGER NOT NULL,
    path TEXT NOT NULL UNIQUE,
    parent_path TEXT NOT NULL,
    filename TEXT NOT NULL,
    extension TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    mtime REAL NOT NULL,
    scan_status TEXT NOT NULL DEFAULT 'discovered',
    last_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_scanned_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(root_id) REFERENCES roots(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS documents (
    file_id INTEGER PRIMARY KEY,
    normalized_text TEXT NOT NULL,
    normalized_format TEXT NOT NULL,
    char_count INTEGER NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(file_id) REFERENCES files(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS summaries (
    file_id INTEGER PRIMARY KEY,
    summary_short TEXT NOT NULL,
    model_name TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(file_id) REFERENCES files(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS embeddings (
    file_id INTEGER PRIMARY KEY,
    model_name TEXT NOT NULL,
    dimensions INTEGER NOT NULL,
    vector_json TEXT NOT NULL,
    source_text TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(file_id) REFERENCES files(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS folders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    root_id INTEGER NOT NULL,
    path TEXT NOT NULL UNIQUE,
    parent_path TEXT NOT NULL,
    folder_name TEXT NOT NULL,
    file_count INTEGER NOT NULL DEFAULT 0,
    child_folder_count INTEGER NOT NULL DEFAULT 0,
    latest_mtime REAL NOT NULL DEFAULT 0,
    content_fingerprint TEXT NOT NULL DEFAULT '',
    last_scanned_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(root_id) REFERENCES roots(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS folder_summaries (
    folder_id INTEGER PRIMARY KEY,
    summary_short TEXT NOT NULL,
    model_name TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(folder_id) REFERENCES folders(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS folder_embeddings (
    folder_id INTEGER PRIMARY KEY,
    model_name TEXT NOT NULL,
    dimensions INTEGER NOT NULL,
    vector_json TEXT NOT NULL,
    source_text TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(folder_id) REFERENCES folders(id) ON DELETE CASCADE
);

CREATE VIRTUAL TABLE IF NOT EXISTS fts_documents USING fts5(
    path,
    filename,
    extension,
    parent_path,
    normalized_text
);

CREATE VIRTUAL TABLE IF NOT EXISTS fts_folders USING fts5(
    path,
    folder_name,
    summary_short
);

CREATE TABLE IF NOT EXISTS activity_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    event_type TEXT NOT NULL,
    event_time REAL NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    url TEXT NOT NULL DEFAULT '',
    path TEXT NOT NULL DEFAULT '',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    dedupe_key TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_activity_events_time
ON activity_events(event_time);

CREATE INDEX IF NOT EXISTS idx_activity_events_source_time
ON activity_events(source, event_time);

CREATE TABLE IF NOT EXISTS activity_import_state (
    source TEXT PRIMARY KEY,
    last_imported_at REAL NOT NULL DEFAULT 0,
    last_event_time REAL NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS activity_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    session_type TEXT NOT NULL,
    start_time REAL NOT NULL,
    end_time REAL NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    summary TEXT NOT NULL DEFAULT '',
    primary_domain TEXT NOT NULL DEFAULT '',
    event_count INTEGER NOT NULL DEFAULT 0,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    dedupe_key TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_activity_sessions_time
ON activity_sessions(start_time, end_time);

CREATE INDEX IF NOT EXISTS idx_activity_sessions_source_time
ON activity_sessions(source, start_time);
"""


def get_db_path(app_dir: Path) -> Path:
    return app_dir / "harumi.db"


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    last_error: sqlite3.OperationalError | None = None

    for delay in (0.0, 0.2, 0.5, 1.0, 2.0, 4.0):
        if delay:
            time.sleep(delay)
        try:
            connection = sqlite3.connect(db_path, timeout=30)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA busy_timeout = 30000")
            return connection
        except sqlite3.OperationalError as exc:
            last_error = exc
            message = str(exc).lower()
            if (
                "unable to open database file" not in message
                and "database is locked" not in message
            ):
                raise

    assert last_error is not None
    raise last_error


def init_db(db_path: Path) -> None:
    with connect(db_path) as connection:
        connection.executescript(SCHEMA)
        _run_migrations(connection)


def _run_migrations(connection: sqlite3.Connection) -> None:
    folder_columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(folders)").fetchall()
    }
    if "latest_mtime" not in folder_columns:
        connection.execute(
            "ALTER TABLE folders ADD COLUMN latest_mtime REAL NOT NULL DEFAULT 0"
        )
    if "content_fingerprint" not in folder_columns:
        connection.execute(
            "ALTER TABLE folders ADD COLUMN content_fingerprint TEXT NOT NULL DEFAULT ''"
        )
    connection.commit()

    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS scan_state (
            root_id INTEGER PRIMARY KEY,
            last_started_at REAL NOT NULL DEFAULT 0,
            last_completed_at REAL NOT NULL DEFAULT 0,
            last_full_started_at REAL NOT NULL DEFAULT 0,
            last_full_completed_at REAL NOT NULL DEFAULT 0,
            last_quick_started_at REAL NOT NULL DEFAULT 0,
            last_quick_completed_at REAL NOT NULL DEFAULT 0,
            scan_kind TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(root_id) REFERENCES roots(id) ON DELETE CASCADE
        );
        """
    )
    connection.commit()
    scan_state_columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(scan_state)").fetchall()
    }
    for column in (
        "last_full_started_at",
        "last_full_completed_at",
        "last_quick_started_at",
        "last_quick_completed_at",
    ):
        if column not in scan_state_columns:
            connection.execute(
                f"ALTER TABLE scan_state ADD COLUMN {column} REAL NOT NULL DEFAULT 0"
            )
    connection.execute(
        """
        UPDATE scan_state
        SET last_full_started_at = last_started_at,
            last_full_completed_at = last_completed_at
        WHERE scan_kind = 'full'
          AND last_full_started_at = 0
          AND last_started_at > 0
        """
    )
    connection.execute(
        """
        UPDATE scan_state
        SET last_quick_started_at = last_started_at,
            last_quick_completed_at = last_completed_at
        WHERE scan_kind = 'quick'
          AND last_quick_started_at = 0
          AND last_started_at > 0
        """
    )
    connection.commit()

    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS activity_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,
            event_type TEXT NOT NULL,
            event_time REAL NOT NULL,
            title TEXT NOT NULL DEFAULT '',
            url TEXT NOT NULL DEFAULT '',
            path TEXT NOT NULL DEFAULT '',
            metadata_json TEXT NOT NULL DEFAULT '{}',
            dedupe_key TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_activity_events_time
        ON activity_events(event_time);

        CREATE INDEX IF NOT EXISTS idx_activity_events_source_time
        ON activity_events(source, event_time);

        CREATE TABLE IF NOT EXISTS activity_import_state (
            source TEXT PRIMARY KEY,
            last_imported_at REAL NOT NULL DEFAULT 0,
            last_event_time REAL NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS activity_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,
            session_type TEXT NOT NULL,
            start_time REAL NOT NULL,
            end_time REAL NOT NULL,
            title TEXT NOT NULL DEFAULT '',
            summary TEXT NOT NULL DEFAULT '',
            primary_domain TEXT NOT NULL DEFAULT '',
            event_count INTEGER NOT NULL DEFAULT 0,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            dedupe_key TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_activity_sessions_time
        ON activity_sessions(start_time, end_time);

        CREATE INDEX IF NOT EXISTS idx_activity_sessions_source_time
        ON activity_sessions(source, start_time);
        """
    )
    connection.commit()


def insert_root(db_path: Path, path: Path) -> bool:
    with connect(db_path) as connection:
        cursor = connection.execute(
            "INSERT OR IGNORE INTO roots(path) VALUES (?)",
            (str(path),),
        )
        connection.commit()
        return cursor.rowcount > 0


def list_roots(db_path: Path) -> list[sqlite3.Row]:
    with connect(db_path) as connection:
        cursor = connection.execute(
            "SELECT id, path, enabled, created_at FROM roots ORDER BY path"
        )
        return list(cursor.fetchall())


def get_enabled_roots(db_path: Path) -> list[sqlite3.Row]:
    with connect(db_path) as connection:
        cursor = connection.execute(
            "SELECT id, path FROM roots WHERE enabled = 1 ORDER BY path"
        )
        return list(cursor.fetchall())


def get_enabled_roots_with_connection(connection: sqlite3.Connection) -> list[sqlite3.Row]:
    cursor = connection.execute(
        "SELECT id, path FROM roots WHERE enabled = 1 ORDER BY path"
    )
    return list(cursor.fetchall())


def get_scan_state_with_connection(
    connection: sqlite3.Connection,
    root_id: int,
) -> sqlite3.Row | None:
    return connection.execute(
        """
        SELECT
            root_id,
            last_started_at,
            last_completed_at,
            last_full_started_at,
            last_full_completed_at,
            last_quick_started_at,
            last_quick_completed_at,
            scan_kind,
            updated_at
        FROM scan_state
        WHERE root_id = ?
        """,
        (root_id,),
    ).fetchone()


def list_scan_state(db_path: Path) -> list[sqlite3.Row]:
    with connect(db_path) as connection:
        cursor = connection.execute(
            """
            SELECT
                roots.id AS root_id,
                roots.path AS root_path,
                roots.enabled,
                scan_state.last_started_at,
                scan_state.last_completed_at,
                scan_state.last_full_started_at,
                scan_state.last_full_completed_at,
                scan_state.last_quick_started_at,
                scan_state.last_quick_completed_at,
                scan_state.scan_kind,
                scan_state.updated_at
            FROM roots
            LEFT JOIN scan_state ON scan_state.root_id = roots.id
            ORDER BY roots.path
            """
        )
        return list(cursor.fetchall())


def upsert_scan_state(
    db_path: Path,
    *,
    root_id: int,
    started_at: float,
    completed_at: float,
    scan_kind: str,
    connection: sqlite3.Connection | None = None,
) -> None:
    manager = nullcontext(connection) if connection is not None else connect(db_path)
    full_started_at = started_at if scan_kind == "full" else 0
    full_completed_at = completed_at if scan_kind == "full" else 0
    quick_started_at = started_at if scan_kind == "quick" else 0
    quick_completed_at = completed_at if scan_kind == "quick" else 0
    with manager as connection:
        connection.execute(
            """
            INSERT INTO scan_state (
                root_id,
                last_started_at,
                last_completed_at,
                last_full_started_at,
                last_full_completed_at,
                last_quick_started_at,
                last_quick_completed_at,
                scan_kind,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(root_id) DO UPDATE SET
                last_started_at = excluded.last_started_at,
                last_completed_at = excluded.last_completed_at,
                last_full_started_at = CASE
                    WHEN excluded.last_full_started_at > 0 THEN excluded.last_full_started_at
                    ELSE scan_state.last_full_started_at
                END,
                last_full_completed_at = CASE
                    WHEN excluded.last_full_completed_at > 0 THEN excluded.last_full_completed_at
                    ELSE scan_state.last_full_completed_at
                END,
                last_quick_started_at = CASE
                    WHEN excluded.last_quick_started_at > 0 THEN excluded.last_quick_started_at
                    ELSE scan_state.last_quick_started_at
                END,
                last_quick_completed_at = CASE
                    WHEN excluded.last_quick_completed_at > 0 THEN excluded.last_quick_completed_at
                    ELSE scan_state.last_quick_completed_at
                END,
                scan_kind = excluded.scan_kind,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                root_id,
                started_at,
                completed_at,
                full_started_at,
                full_completed_at,
                quick_started_at,
                quick_completed_at,
                scan_kind,
            ),
        )
        connection.commit()


def upsert_file_record(
    db_path: Path,
    *,
    root_id: int,
    path: str,
    parent_path: str,
    filename: str,
    extension: str,
    size_bytes: int,
    mtime: float,
    connection: sqlite3.Connection | None = None,
) -> tuple[str, int]:
    manager = nullcontext(connection) if connection is not None else connect(db_path)
    with manager as connection:
        existing = connection.execute(
            "SELECT id, size_bytes, mtime FROM files WHERE path = ?",
            (path,),
        ).fetchone()

        if existing is None:
            cursor = connection.execute(
                """
                INSERT INTO files (
                    root_id, path, parent_path, filename, extension, size_bytes, mtime, scan_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'indexed')
                """,
                (root_id, path, parent_path, filename, extension, size_bytes, mtime),
            )
            connection.commit()
            return "indexed", int(cursor.lastrowid)

        if existing["size_bytes"] == size_bytes and existing["mtime"] == mtime:
            connection.execute(
                """
                UPDATE files
                SET last_seen_at = CURRENT_TIMESTAMP,
                    last_scanned_at = CURRENT_TIMESTAMP,
                    scan_status = 'unchanged'
                WHERE path = ?
                """,
                (path,),
            )
            connection.commit()
            return "unchanged", int(existing["id"])

        connection.execute(
            """
            UPDATE files
            SET root_id = ?,
                parent_path = ?,
                filename = ?,
                extension = ?,
                size_bytes = ?,
                mtime = ?,
                last_seen_at = CURRENT_TIMESTAMP,
                last_scanned_at = CURRENT_TIMESTAMP,
                scan_status = 'updated'
            WHERE path = ?
            """,
            (root_id, parent_path, filename, extension, size_bytes, mtime, path),
        )
        connection.commit()
        return "updated", int(existing["id"])


def count_files(db_path: Path) -> int:
    with connect(db_path) as connection:
        row = connection.execute("SELECT COUNT(*) AS count FROM files").fetchone()
        return int(row["count"])


def upsert_folder_record(
    db_path: Path,
    *,
    root_id: int,
    path: str,
    parent_path: str,
    folder_name: str,
    file_count: int,
    child_folder_count: int,
    latest_mtime: float,
    content_fingerprint: str,
    connection: sqlite3.Connection | None = None,
) -> tuple[int, bool]:
    manager = nullcontext(connection) if connection is not None else connect(db_path)
    with manager as connection:
        existing = connection.execute(
            "SELECT id, content_fingerprint FROM folders WHERE path = ?",
            (path,),
        ).fetchone()

        if existing is None:
            cursor = connection.execute(
                """
                INSERT INTO folders (
                    root_id, path, parent_path, folder_name, file_count, child_folder_count, latest_mtime, content_fingerprint, last_scanned_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (
                    root_id,
                    path,
                    parent_path,
                    folder_name,
                    file_count,
                    child_folder_count,
                    latest_mtime,
                    content_fingerprint,
                ),
            )
            connection.commit()
            return int(cursor.lastrowid), True

        connection.execute(
            """
            UPDATE folders
            SET root_id = ?,
                parent_path = ?,
                folder_name = ?,
                file_count = ?,
                child_folder_count = ?,
                latest_mtime = ?,
                content_fingerprint = ?,
                last_scanned_at = CURRENT_TIMESTAMP
            WHERE path = ?
            """,
            (
                root_id,
                parent_path,
                folder_name,
                file_count,
                child_folder_count,
                latest_mtime,
                content_fingerprint,
                path,
            ),
        )
        connection.commit()
        changed = existing["content_fingerprint"] != content_fingerprint
        return int(existing["id"]), changed


def upsert_document(
    db_path: Path,
    *,
    file_id: int,
    normalized_text: str,
    normalized_format: str,
    connection: sqlite3.Connection | None = None,
) -> None:
    manager = nullcontext(connection) if connection is not None else connect(db_path)
    with manager as connection:
        connection.execute(
            """
            INSERT INTO documents (file_id, normalized_text, normalized_format, char_count, updated_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(file_id) DO UPDATE SET
                normalized_text = excluded.normalized_text,
                normalized_format = excluded.normalized_format,
                char_count = excluded.char_count,
                updated_at = CURRENT_TIMESTAMP
            """,
            (file_id, normalized_text, normalized_format, len(normalized_text)),
        )
        connection.commit()


def count_documents(db_path: Path) -> int:
    with connect(db_path) as connection:
        row = connection.execute("SELECT COUNT(*) AS count FROM documents").fetchone()
        return int(row["count"])


def count_folders(db_path: Path) -> int:
    with connect(db_path) as connection:
        row = connection.execute("SELECT COUNT(*) AS count FROM folders").fetchone()
        return int(row["count"])


def upsert_summary(
    db_path: Path,
    *,
    file_id: int,
    summary_short: str,
    model_name: str,
    prompt_version: str,
    connection: sqlite3.Connection | None = None,
) -> None:
    manager = nullcontext(connection) if connection is not None else connect(db_path)
    with manager as connection:
        connection.execute(
            """
            INSERT INTO summaries (file_id, summary_short, model_name, prompt_version, updated_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(file_id) DO UPDATE SET
                summary_short = excluded.summary_short,
                model_name = excluded.model_name,
                prompt_version = excluded.prompt_version,
                updated_at = CURRENT_TIMESTAMP
            """,
            (file_id, summary_short, model_name, prompt_version),
        )
        connection.commit()


def upsert_fts_document(
    db_path: Path,
    *,
    file_id: int,
    path: str,
    filename: str,
    extension: str,
    parent_path: str,
    normalized_text: str,
    summary_short: str,
    connection: sqlite3.Connection | None = None,
) -> None:
    manager = nullcontext(connection) if connection is not None else connect(db_path)
    with manager as connection:
        connection.execute("DELETE FROM fts_documents WHERE rowid = ?", (file_id,))
        connection.execute(
            """
            INSERT INTO fts_documents(rowid, path, filename, extension, parent_path, normalized_text)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (file_id, path, filename, extension, parent_path, normalized_text),
        )
        connection.commit()


def search_documents(db_path: Path, query: str, limit: int = 10) -> list[sqlite3.Row]:
    with connect(db_path) as connection:
        cursor = connection.execute(
            """
            SELECT
                files.path,
                files.filename,
                files.extension,
                files.parent_path,
                files.mtime,
                roots.path AS root_path,
                documents.normalized_format,
                documents.char_count,
                COALESCE(summaries.summary_short, '') AS summary_short,
                snippet(fts_documents, 4, '[', ']', ' ... ', 16) AS snippet,
                bm25(fts_documents, 2.5, 3.0, 1.0, 1.0, 0.5) AS rank
            FROM fts_documents
            JOIN files ON files.id = fts_documents.rowid
            JOIN roots ON roots.id = files.root_id
            JOIN documents ON documents.file_id = files.id
            LEFT JOIN summaries ON summaries.file_id = files.id
            WHERE fts_documents MATCH ?
            ORDER BY rank
            LIMIT ?
            """,
            (query, limit),
        )
        return list(cursor.fetchall())


def count_summaries(db_path: Path) -> int:
    with connect(db_path) as connection:
        row = connection.execute("SELECT COUNT(*) AS count FROM summaries").fetchone()
        return int(row["count"])


def upsert_folder_summary(
    db_path: Path,
    *,
    folder_id: int,
    summary_short: str,
    model_name: str,
    prompt_version: str,
    connection: sqlite3.Connection | None = None,
) -> None:
    manager = nullcontext(connection) if connection is not None else connect(db_path)
    with manager as connection:
        connection.execute(
            """
            INSERT INTO folder_summaries (folder_id, summary_short, model_name, prompt_version, updated_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(folder_id) DO UPDATE SET
                summary_short = excluded.summary_short,
                model_name = excluded.model_name,
                prompt_version = excluded.prompt_version,
                updated_at = CURRENT_TIMESTAMP
            """,
            (folder_id, summary_short, model_name, prompt_version),
        )
        connection.commit()


def count_folder_summaries(db_path: Path) -> int:
    with connect(db_path) as connection:
        row = connection.execute("SELECT COUNT(*) AS count FROM folder_summaries").fetchone()
        return int(row["count"])


def upsert_embedding(
    db_path: Path,
    *,
    file_id: int,
    model_name: str,
    vector: list[float],
    source_text: str,
    connection: sqlite3.Connection | None = None,
) -> None:
    manager = nullcontext(connection) if connection is not None else connect(db_path)
    with manager as connection:
        connection.execute(
            """
            INSERT INTO embeddings (file_id, model_name, dimensions, vector_json, source_text, updated_at)
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(file_id) DO UPDATE SET
                model_name = excluded.model_name,
                dimensions = excluded.dimensions,
                vector_json = excluded.vector_json,
                source_text = excluded.source_text,
                updated_at = CURRENT_TIMESTAMP
            """,
            (file_id, model_name, len(vector), json.dumps(vector), source_text),
        )
        connection.commit()


def count_embeddings(db_path: Path) -> int:
    with connect(db_path) as connection:
        row = connection.execute("SELECT COUNT(*) AS count FROM embeddings").fetchone()
        return int(row["count"])


def upsert_folder_embedding(
    db_path: Path,
    *,
    folder_id: int,
    model_name: str,
    vector: list[float],
    source_text: str,
    connection: sqlite3.Connection | None = None,
) -> None:
    manager = nullcontext(connection) if connection is not None else connect(db_path)
    with manager as connection:
        connection.execute(
            """
            INSERT INTO folder_embeddings (folder_id, model_name, dimensions, vector_json, source_text, updated_at)
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(folder_id) DO UPDATE SET
                model_name = excluded.model_name,
                dimensions = excluded.dimensions,
                vector_json = excluded.vector_json,
                source_text = excluded.source_text,
                updated_at = CURRENT_TIMESTAMP
            """,
            (folder_id, model_name, len(vector), json.dumps(vector), source_text),
        )
        connection.commit()


def count_folder_embeddings(db_path: Path) -> int:
    with connect(db_path) as connection:
        row = connection.execute("SELECT COUNT(*) AS count FROM folder_embeddings").fetchone()
        return int(row["count"])


def count_index_stats(db_path: Path) -> dict[str, int]:
    with connect(db_path) as connection:
        queries = {
            "files": "SELECT COUNT(*) AS count FROM files",
            "folders": "SELECT COUNT(*) AS count FROM folders",
            "documents": "SELECT COUNT(*) AS count FROM documents",
            "summaries": "SELECT COUNT(*) AS count FROM summaries",
            "folder_summaries": "SELECT COUNT(*) AS count FROM folder_summaries",
            "embeddings": "SELECT COUNT(*) AS count FROM embeddings",
            "folder_embeddings": "SELECT COUNT(*) AS count FROM folder_embeddings",
            "activity_events": "SELECT COUNT(*) AS count FROM activity_events",
            "activity_sessions": "SELECT COUNT(*) AS count FROM activity_sessions",
        }
        return {
            name: int(connection.execute(sql).fetchone()["count"])
            for name, sql in queries.items()
        }


def get_activity_import_state(db_path: Path, source: str) -> sqlite3.Row | None:
    with connect(db_path) as connection:
        return connection.execute(
            """
            SELECT source, last_imported_at, last_event_time, updated_at
            FROM activity_import_state
            WHERE source = ?
            """,
            (source,),
        ).fetchone()


def upsert_activity_import_state(
    db_path: Path,
    *,
    source: str,
    last_imported_at: float,
    last_event_time: float,
    connection: sqlite3.Connection | None = None,
) -> None:
    manager = nullcontext(connection) if connection is not None else connect(db_path)
    with manager as connection:
        connection.execute(
            """
            INSERT INTO activity_import_state (source, last_imported_at, last_event_time)
            VALUES (?, ?, ?)
            ON CONFLICT(source) DO UPDATE SET
                last_imported_at = excluded.last_imported_at,
                last_event_time = MAX(activity_import_state.last_event_time, excluded.last_event_time),
                updated_at = CURRENT_TIMESTAMP
            """,
            (source, last_imported_at, last_event_time),
        )
        if connection.in_transaction:
            connection.commit()


def upsert_activity_events(
    db_path: Path,
    events: list[dict],
    connection: sqlite3.Connection | None = None,
) -> int:
    if not events:
        return 0
    manager = nullcontext(connection) if connection is not None else connect(db_path)
    inserted = 0
    with manager as connection:
        for event in events:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO activity_events (
                    source, event_type, event_time, title, url, path, metadata_json, dedupe_key
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event["source"],
                    event["event_type"],
                    event["event_time"],
                    event.get("title", ""),
                    event.get("url", ""),
                    event.get("path", ""),
                    event.get("metadata_json", "{}"),
                    event["dedupe_key"],
                ),
            )
            inserted += cursor.rowcount
        connection.commit()
    return inserted


def query_activity_events_in_range(
    db_path: Path,
    *,
    start_ts: float,
    end_ts: float,
    limit: int = 100,
    source_prefix: str | None = None,
) -> list[sqlite3.Row]:
    with connect(db_path) as connection:
        params: list[object] = [start_ts, end_ts]
        source_clause = ""
        if source_prefix:
            source_clause = "AND source LIKE ?"
            params.append(f"{source_prefix}%")
        params.append(limit)
        cursor = connection.execute(
            f"""
            SELECT
                source,
                event_type,
                event_time,
                title,
                url,
                path,
                metadata_json
            FROM activity_events
            WHERE event_time >= ? AND event_time < ?
              {source_clause}
            ORDER BY event_time DESC
            LIMIT ?
            """,
            tuple(params),
        )
        return list(cursor.fetchall())


def upsert_activity_sessions(
    db_path: Path,
    sessions: list[dict],
    connection: sqlite3.Connection | None = None,
) -> int:
    if not sessions:
        return 0
    manager = nullcontext(connection) if connection is not None else connect(db_path)
    changed = 0
    with manager as connection:
        for session in sessions:
            cursor = connection.execute(
                """
                INSERT INTO activity_sessions (
                    source, session_type, start_time, end_time, title, summary,
                    primary_domain, event_count, metadata_json, dedupe_key
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(dedupe_key) DO UPDATE SET
                    end_time = excluded.end_time,
                    title = excluded.title,
                    summary = excluded.summary,
                    primary_domain = excluded.primary_domain,
                    event_count = excluded.event_count,
                    metadata_json = excluded.metadata_json,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    session["source"],
                    session["session_type"],
                    session["start_time"],
                    session["end_time"],
                    session.get("title", ""),
                    session.get("summary", ""),
                    session.get("primary_domain", ""),
                    session.get("event_count", 0),
                    session.get("metadata_json", "{}"),
                    session["dedupe_key"],
                ),
            )
            changed += cursor.rowcount
        connection.commit()
    return changed


def delete_activity_sessions_in_range(
    db_path: Path,
    *,
    start_ts: float,
    end_ts: float,
    source_prefix: str | None = None,
    connection: sqlite3.Connection | None = None,
) -> int:
    manager = nullcontext(connection) if connection is not None else connect(db_path)
    with manager as connection:
        params: list[object] = [start_ts, end_ts]
        source_clause = ""
        if source_prefix:
            source_clause = "AND source LIKE ?"
            params.append(f"{source_prefix}%")
        cursor = connection.execute(
            f"""
            DELETE FROM activity_sessions
            WHERE start_time >= ? AND start_time < ?
              {source_clause}
            """,
            tuple(params),
        )
        connection.commit()
        return int(cursor.rowcount)


def query_activity_sessions_in_range(
    db_path: Path,
    *,
    start_ts: float,
    end_ts: float,
    limit: int = 100,
    source_prefix: str | None = None,
) -> list[sqlite3.Row]:
    with connect(db_path) as connection:
        params: list[object] = [start_ts, end_ts]
        source_clause = ""
        if source_prefix:
            source_clause = "AND source LIKE ?"
            params.append(f"{source_prefix}%")
        params.append(limit)
        cursor = connection.execute(
            f"""
            SELECT
                source,
                session_type,
                start_time,
                end_time,
                title,
                summary,
                primary_domain,
                event_count,
                metadata_json
            FROM activity_sessions
            WHERE start_time >= ? AND start_time < ?
              {source_clause}
            ORDER BY start_time DESC
            LIMIT ?
            """,
            tuple(params),
        )
        return list(cursor.fetchall())


def count_regeneration_targets(db_path: Path, scope: str) -> dict[str, int]:
    with connect(db_path) as connection:
        counts = {
            "file_documents": 0,
            "folder_records": 0,
            "file_summaries": 0,
            "folder_summaries": 0,
            "file_embeddings": 0,
            "folder_embeddings": 0,
        }
        if scope in {"all", "files"}:
            counts["file_documents"] = int(
                connection.execute("SELECT COUNT(*) AS count FROM documents").fetchone()["count"]
            )
            counts["file_summaries"] = int(
                connection.execute("SELECT COUNT(*) AS count FROM summaries").fetchone()["count"]
            )
            counts["file_embeddings"] = int(
                connection.execute("SELECT COUNT(*) AS count FROM embeddings").fetchone()["count"]
            )
        if scope in {"all", "folders"}:
            counts["folder_records"] = int(
                connection.execute("SELECT COUNT(*) AS count FROM folders").fetchone()["count"]
            )
            counts["folder_summaries"] = int(
                connection.execute("SELECT COUNT(*) AS count FROM folder_summaries").fetchone()["count"]
            )
            counts["folder_embeddings"] = int(
                connection.execute("SELECT COUNT(*) AS count FROM folder_embeddings").fetchone()["count"]
            )
        return counts


def purge_summary_artifacts(
    db_path: Path,
    scope: str,
    connection: sqlite3.Connection | None = None,
) -> None:
    manager = nullcontext(connection) if connection is not None else connect(db_path)
    with manager as connection:
        if scope in {"all", "files"}:
            connection.execute("DELETE FROM summaries")
            connection.execute("DELETE FROM embeddings")
        if scope in {"all", "folders"}:
            connection.execute("DELETE FROM folder_summaries")
            connection.execute("DELETE FROM folder_embeddings")
        connection.commit()


def iter_documents_for_regeneration(
    db_path: Path,
    *,
    limit: int | None = None,
) -> list[sqlite3.Row]:
    with connect(db_path) as connection:
        sql = """
            SELECT
                files.id AS file_id,
                files.path,
                files.parent_path,
                files.filename,
                files.extension,
                documents.normalized_text,
                documents.normalized_format
            FROM documents
            JOIN files ON files.id = documents.file_id
            ORDER BY files.path
        """
        params: tuple[int, ...] = ()
        if limit is not None:
            sql += "\nLIMIT ?"
            params = (limit,)
        return list(connection.execute(sql, params).fetchall())


def iter_folders_for_regeneration(
    db_path: Path,
    *,
    limit: int | None = None,
) -> list[sqlite3.Row]:
    with connect(db_path) as connection:
        sql = """
            SELECT
                id,
                path,
                folder_name
            FROM folders
            ORDER BY path
        """
        params: tuple[int, ...] = ()
        if limit is not None:
            sql += "\nLIMIT ?"
            params = (limit,)
        return list(connection.execute(sql, params).fetchall())


def list_embeddings(db_path: Path) -> list[sqlite3.Row]:
    with connect(db_path) as connection:
        cursor = connection.execute(
            """
            SELECT
                embeddings.file_id,
                embeddings.model_name,
                embeddings.dimensions,
                embeddings.vector_json,
                embeddings.source_text,
                files.path,
                files.filename,
                files.extension,
                files.parent_path,
                files.mtime,
                roots.path AS root_path,
                documents.normalized_format,
                documents.char_count,
                COALESCE(summaries.summary_short, '') AS summary_short
            FROM embeddings
            JOIN files ON files.id = embeddings.file_id
            JOIN roots ON roots.id = files.root_id
            JOIN documents ON documents.file_id = files.id
            LEFT JOIN summaries ON summaries.file_id = files.id
            ORDER BY files.path
            """
        )
        return list(cursor.fetchall())


def upsert_fts_folder(
    db_path: Path,
    *,
    folder_id: int,
    path: str,
    folder_name: str,
    summary_short: str,
    connection: sqlite3.Connection | None = None,
) -> None:
    manager = nullcontext(connection) if connection is not None else connect(db_path)
    with manager as connection:
        connection.execute("DELETE FROM fts_folders WHERE rowid = ?", (folder_id,))
        connection.execute(
            """
            INSERT INTO fts_folders(rowid, path, folder_name, summary_short)
            VALUES (?, ?, ?, ?)
            """,
            (folder_id, path, folder_name, summary_short),
        )
        connection.commit()


def search_folders(db_path: Path, query: str, limit: int = 10) -> list[sqlite3.Row]:
    with connect(db_path) as connection:
        cursor = connection.execute(
            """
            SELECT
                folders.path,
                folders.folder_name,
                folders.parent_path,
                folders.file_count,
                folders.child_folder_count,
                folders.latest_mtime AS mtime,
                roots.path AS root_path,
                COALESCE(folder_summaries.summary_short, '') AS summary_short,
                snippet(fts_folders, 2, '[', ']', ' ... ', 16) AS snippet,
                bm25(fts_folders, 2.5, 3.0, 1.2) AS rank
            FROM fts_folders
            JOIN folders ON folders.id = fts_folders.rowid
            JOIN roots ON roots.id = folders.root_id
            LEFT JOIN folder_summaries ON folder_summaries.folder_id = folders.id
            WHERE fts_folders MATCH ?
            ORDER BY rank
            LIMIT ?
            """,
            (query, limit),
        )
        return list(cursor.fetchall())


def query_files_in_range(
    db_path: Path,
    *,
    start_ts: float,
    end_ts: float,
    limit: int = 100,
) -> list[sqlite3.Row]:
    with connect(db_path) as connection:
        cursor = connection.execute(
            """
            SELECT
                files.path,
                files.filename,
                files.extension,
                files.parent_path,
                files.mtime,
                files.size_bytes,
                COALESCE(summaries.summary_short, '') AS summary_short
            FROM files
            LEFT JOIN summaries ON summaries.file_id = files.id
            WHERE files.mtime >= ? AND files.mtime < ?
            ORDER BY files.mtime DESC
            LIMIT ?
            """,
            (start_ts, end_ts, limit),
        )
        return list(cursor.fetchall())


def list_folder_embeddings(db_path: Path) -> list[sqlite3.Row]:
    with connect(db_path) as connection:
        cursor = connection.execute(
            """
            SELECT
                folder_embeddings.folder_id,
                folder_embeddings.model_name,
                folder_embeddings.dimensions,
                folder_embeddings.vector_json,
                folder_embeddings.source_text,
                folders.path,
                folders.folder_name,
                folders.parent_path,
                folders.file_count,
                folders.child_folder_count,
                folders.latest_mtime AS mtime,
                roots.path AS root_path,
                COALESCE(folder_summaries.summary_short, '') AS summary_short
            FROM folder_embeddings
            JOIN folders ON folders.id = folder_embeddings.folder_id
            JOIN roots ON roots.id = folders.root_id
            LEFT JOIN folder_summaries ON folder_summaries.folder_id = folders.id
            ORDER BY folders.path
            """
        )
        return list(cursor.fetchall())
