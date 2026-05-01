# File Watcher Design

## Goal

Add a `harumi watch` command that monitors all enabled root directories and
re-indexes files incrementally when they are created, modified, deleted, or moved.
This removes the need to run `harumi scan` manually after every change.

## Library

Use `watchdog` (>= 4.0).

- Uses native OS APIs: inotify on Linux, FSEvents on macOS, ReadDirectoryChanges on Windows
- Pure Python, no extra services
- Add to `pyproject.toml` dependencies

## New command

```
harumi watch [--debounce SECONDS] [--no-summary] [--no-embed]
```

Runs in the foreground. Progress lines go to stdout and to the existing
`scan-errors.log`. Stop with Ctrl+C or SIGTERM.

## Architecture

```
watchdog Observer (one per root, recursive=True)
  └─ HarumiEventHandler
       on_created / on_modified → pending_events[path] = PendingEvent(type, now)
       on_deleted               → pending_events[path] = PendingEvent("delete", now)
       on_moved                 → pending_events[src]  = PendingEvent("move", now, dest)

Debounce thread  (runs every 0.5 s)
  for path, event in pending_events:
      if time.time() - event.seen_at >= DEBOUNCE_SECONDS:
          work_queue.put(event)
          del pending_events[path]

Worker thread  (single thread, processes work_queue)
  CREATE / MODIFY → _process_file_change(path)
  DELETE          → _process_file_delete(path)
  MOVE            → _process_file_delete(src) then _process_file_change(dest)
  DIR events      → _process_folder_change(folder_path)
```

### Why a single worker thread

Ollama summary and embedding calls are sequential and can take 5–30 seconds each.
A single worker thread avoids concurrent Ollama calls and eliminates SQLite write
contention without needing additional locking.
The debounce step absorbs bursts (e.g. a 50-file git checkout) and groups them
into a steady stream the worker can handle.

### Debounce

- Default: 2.0 seconds
- Pending events are keyed by path; a second event for the same path resets the timer
- This handles editors that write a temp file then rename, vim swap files, etc.
- `--debounce` flag lets the user tune this

## Processing per event type

### CREATE or MODIFY

Reuses the same per-file pipeline as `scanner.py`:

1. `is_ignored_file(path)` → skip if true
2. `path.stat()` → size, mtime
3. `upsert_file_record()` → if "unchanged", return early
4. `normalize_file(path)` → `NormalizedDocument` or `None`
5. If document:
   - `upsert_document()`
   - `summarize_text()` + `upsert_summary()` if eligible
   - `embed_text()` + `upsert_embedding()`
   - `upsert_fts_document()`
6. Trigger parent folder re-index (see below)

### DELETE

1. Look up `file_id` from `files` where `path = ?`
2. `DELETE FROM fts_documents WHERE rowid = file_id`
3. `DELETE FROM files WHERE path = ?`
   — `ON DELETE CASCADE` removes `documents`, `summaries`, `embeddings` automatically
4. Trigger parent folder re-index

### MOVE (src → dest)

1. `_process_file_delete(src)`
2. `_process_file_change(dest)`

### Folder change (DirModified, DirCreated)

Re-run the folder indexing logic from `scanner._index_folder()`:

1. Recompute `content_fingerprint`
2. `upsert_folder_record()` → if fingerprint unchanged, skip
3. Re-summarize and re-embed the folder if content changed
4. `upsert_fts_folder()`

Folder deletes are less critical because the cascade from deleted files will
eventually leave the folder empty; a periodic `harumi scan` can prune orphan
folder records.

## New DB functions required

Add to `db.py`:

```python
def get_file_id_by_path(db_path: Path, path: str) -> int | None:
    """Return the file id for a given absolute path, or None if not found."""

def delete_file_by_path(db_path: Path, path: str) -> bool:
    """Delete a file record and its fts_documents row. CASCADE handles the rest.
    Returns True if a row was deleted."""

def get_root_for_path(db_path: Path, path: str) -> sqlite3.Row | None:
    """Return the root row (id, path) whose path is the longest prefix of the given path."""
```

## New module: `watcher.py`

```python
DEBOUNCE_SECONDS = 2.0

@dataclass
class PendingEvent:
    path: str
    event_type: str          # "create" | "modify" | "delete" | "move"
    dest_path: str | None    # only for "move"
    seen_at: float           # time.time()

class FileWatcher:
    def __init__(self, db_path: Path, debounce: float = DEBOUNCE_SECONDS,
                 summarize: bool = True, embed: bool = True) -> None

    def start(self) -> None
        """Blocking. Loads roots, starts Observer, runs until KeyboardInterrupt."""

    def _load_and_schedule_roots(self, observer: Observer) -> None
    def _debounce_loop(self) -> None   # runs in thread
    def _worker_loop(self) -> None     # runs in thread
    def _process_file_change(self, path: Path, root_id: int) -> None
    def _process_file_delete(self, path: str) -> None
    def _process_folder_change(self, folder_path: Path, root_id: int) -> None
```

`HarumiEventHandler` is a `watchdog.events.FileSystemEventHandler` subclass
created per root and passed to `observer.schedule(handler, root_path, recursive=True)`.

## pyproject.toml change

```toml
dependencies = [
  "markitdown>=0.1.0",
  "watchdog>=4.0",
]
```

## Handling root changes at runtime

On first start, load all enabled roots from the DB and schedule each one.
A simple approach for v1: do not hot-reload roots while `watch` is running.
Print a message telling the user to restart after `harumi roots add`.

A future improvement is to poll the `roots` table every 60 seconds and
add/remove `observer.schedule` entries for newly added or disabled roots.

## Systemd user service (optional)

For users who want the watcher to start automatically on login:

```ini
# ~/.config/systemd/user/harumi-watch.service
[Unit]
Description=Harumi file watcher
After=default.target

[Service]
ExecStart=/home/USER/.venv/bin/harumi watch
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
```

Enable with:

```bash
systemctl --user enable --now harumi-watch.service
```

## Known limitations and follow-up work

- Folder deletes leave orphan `folders` rows; clean up in a future `harumi prune` command
- Very large bursts (e.g. `git clone` into a root) may queue thousands of events;
  consider a batch-size cap or a fallback to `run_scan()` when the queue depth exceeds a threshold
- Vector search loads all embeddings into memory at query time; this is unrelated to the watcher
  but becomes more noticeable as the index grows
- No support for watching network-mounted filesystems (inotify limitation on Linux)
