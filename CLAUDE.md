# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Setup and common commands

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
pip install -U "markitdown[pdf,docx,pptx,xlsx,xls]"
```

A wrapper script at `~/.local/bin/harumi` makes the command available system-wide without activating the venv:

```sh
#!/bin/sh
exec /home/onoue/src/harumi/.venv/bin/harumi "$@"
```

Running the CLI during development:

```bash
harumi init
harumi roots add ~/Documents
harumi scan
harumi scan --progress-percent 5
harumi scan --quiet
harumi scan --files-only
harumi scan --no-browser-history
harumi scan --no-ai-history
harumi find "recent travel document"
harumi status
harumi info                      # index stats, storage, config

# Configuration — persistent settings in ~/.config/harumi/config.toml
harumi config get                # show all settings and their source
harumi config get summary_model  # show one setting
harumi config set summary_model qwen3:14b

# Activity imports — dry-run by default, explicit confirmation writes to DB
harumi browser-history sources
harumi browser-history import --last 7d
harumi browser-history import --last 7d --execute --confirm IMPORT-BROWSER-HISTORY
harumi ai-history import ~/Downloads/chatgpt-export.zip
harumi ai-history import ~/Downloads/claude-export.zip --provider claude --execute --confirm IMPORT-AI-HISTORY
harumi ai-history import ~/Downloads/gemini-takeout.zip --provider gemini --execute --confirm IMPORT-AI-HISTORY

# Work log — summarize modified files and imported activity via Ollama
harumi worklog
harumi worklog --refresh       # run scan first, then show worklog
harumi worklog --date yesterday
harumi worklog --no-llm          # raw files/activity only, no LLM call
harumi worklog --include-private-time

# Retrospect — look back by year / month / day
harumi retrospect 202604         # April 2026
harumi retrospect 20260424       # specific day
harumi retrospect 2026           # full year
harumi retrospect 20260424 --no-llm
```

Dangerous maintenance (requires explicit confirmation flags):

```bash
harumi regenerate-summaries --scope all --execute --confirm RESET-SUMMARIES
```

Run tests with:

```bash
python -m unittest discover -s tests
```

There is no dedicated linter configured yet.

## Architecture overview

Harumi is a local-first CLI tool that indexes directories, stores summaries and embeddings, and answers natural-language file queries. All state lives in a single SQLite database at `~/.local/share/harumi/harumi.db` (overridable via `HARUMI_HOME`).

### Data model (`db.py`)

The database has three layers per item:

| Layer | File tables | Folder tables |
|---|---|---|
| Metadata | `files` | `folders` |
| Summaries | `summaries` | `folder_summaries` |
| Embeddings | `embeddings` | `folder_embeddings` |

Plus two FTS5 virtual tables (`fts_documents`, `fts_folders`) that duplicate key fields for full-text search. Activity imports use `activity_events`, `activity_sessions`, and `activity_import_state`. Embeddings are stored as JSON arrays in `vector_json`. Schema migrations run inline in `_run_migrations()` by checking `PRAGMA table_info`.

### Scan pipeline (`scanner.py`)

`run_scan()` walks each enabled root with `Path.walk()`. Per file:

1. **Stat + upsert** → `files` table; returns `indexed` / `updated` / `unchanged`
2. **Normalize** → `normalize.py` dispatches by extension: text/code files read raw; `.pdf/.docx/.html/…` go through MarkItDown → `documents` table
3. **Summarize** → `summarize.py` calls `ollama run <model>` via `subprocess` → `summaries` table
4. **Embed** → `embed.py` calls Ollama's REST API `POST /api/embed` → `embeddings` table
5. **FTS update** → `fts_documents` rebuilt for the file

Folders follow the same steps (summary + embedding) but use a SHA-256 `content_fingerprint` to skip unchanged folders.

### Search and ranking (`search.py`, `ranking.py`)

`find_command()` in `cli.py` runs two parallel searches then merges:

- **FTS** (`find_documents`): SQLite `fts5 MATCH` with BM25 weights `(2.5, 3.0, 1.0, 1.0, 0.5)` across `path`, `filename`, `extension`, `parent_path`, `normalized_text`
- **Vector** (`find_similar_documents`): loads all embeddings from DB, computes cosine similarity in Python, returns top-k

Merged results go through `rank_results()` which builds a `final_score`:

```
final_score = 0.55×vector + 0.30×fts + filename_boost + summary_boost
            + filetype_boost + kind_boost + recency_boost
            - root_penalty - quality_penalty
```

`infer_intent()` inspects query terms against keyword hint sets (`FOLDER_HINTS`, `RECENT_HINTS`, `CODE_HINTS`, etc.) to adjust weights and penalties at query time.

### Ollama integration

- **Summaries**: `subprocess.run(["ollama", "--nowordwrap", "run", model, prompt])` — synchronous, 120 s timeout. Output cleaning strips ANSI codes and backspace characters.
- **Embeddings**: `urllib.request` POST to `http://127.0.0.1:11434/api/embed` — no external HTTP library dependency.

### Configuration (`config.py`, `harumi_config.py`)

Settings are resolved in this priority order: **env var > config file > built-in default**

**Config file**: `~/.config/harumi/config.toml` — created automatically with defaults on first `harumi config get`. Edit directly or via `harumi config set KEY VALUE`.

**Env vars** override the config file on a per-run basis and are useful for one-off overrides in scripts:

```sh
HARUMI_SUMMARY_MODEL=qwen3:14b harumi scan
```

| Config key | Env var | Default | Purpose |
|---|---|---|---|
| `summary_model` | `HARUMI_SUMMARY_MODEL` | `gemma3:latest` | Ollama summary model |
| `embed_model` | `HARUMI_EMBED_MODEL` | `embeddinggemma` | Ollama embedding model |
| `summary_language` | `HARUMI_SUMMARY_LANGUAGE` | `ja` | Summary output language |
| `summary_enabled` | `HARUMI_ENABLE_SUMMARY` | `true` | Enable summary generation |
| `embedding_enabled` | `HARUMI_ENABLE_EMBEDDING` | `true` | Enable embedding generation |
| `summary_min_chars` | `HARUMI_SUMMARY_MIN_CHARS` | `400` | Min chars before summarizing |
| `summary_code` | `HARUMI_SUMMARY_CODE` | `false` | Summarize code files |
| `folder_summary_min_items` | `HARUMI_FOLDER_SUMMARY_MIN_ITEMS` | `2` | Min items to summarize a folder |
| `work_hours_start` | `HARUMI_WORK_HOURS_START` | `09:00` | Start of normal worklog window |
| `work_hours_end` | `HARUMI_WORK_HOURS_END` | `18:00` | End of normal worklog window |
| `work_days` | `HARUMI_WORK_DAYS` | `mon,tue,wed,thu,fri` | Days included in the normal worklog window |
| `scan_browser_history` | `HARUMI_SCAN_BROWSER_HISTORY` | `true` | Import browser history during `harumi scan` |
| `scan_browser_history_last` | `HARUMI_SCAN_BROWSER_HISTORY_LAST` | `7d` | Browser history range used by `harumi scan` |
| `scan_ai_history` | `HARUMI_SCAN_AI_HISTORY` | `true` | Import configured AI history exports during `harumi scan` |
| `ai_history_chatgpt_path` | `HARUMI_AI_HISTORY_CHATGPT_PATH` | empty | ChatGPT export path used by `harumi scan` |
| `ai_history_claude_path` | `HARUMI_AI_HISTORY_CLAUDE_PATH` | empty | Claude export path used by `harumi scan` |
| `ai_history_gemini_path` | `HARUMI_AI_HISTORY_GEMINI_PATH` | empty | Gemini export path used by `harumi scan` |

`HARUMI_HOME` (storage directory, default `~/.local/share/harumi`) and `HARUMI_CONFIG` (config file path) are env-only; they cannot be set via the config file.

### Module responsibilities

| Module | Role |
|---|---|
| `cli.py` | Argparse entry point; all commands delegate to other modules |
| `db.py` | All SQLite reads/writes; schema definition and migrations |
| `scanner.py` | Directory walk, orchestrates normalize → summarize → embed per file/folder |
| `normalize.py` | Converts a file to plain text (`NormalizedDocument`) |
| `summarize.py` | Builds prompts, calls Ollama CLI, cleans output |
| `embed.py` | Calls Ollama REST API, computes cosine similarity |
| `search.py` | FTS and vector search; returns unified result dicts |
| `ranking.py` | Scores and sorts merged results; intent inference from query |
| `maintenance.py` | Bulk summary/embedding purge and rebuild |
| `browser_history.py` | Browser history discovery, import, and browser session building |
| `ai_history.py` | ChatGPT, Claude, and Gemini export import as activity |
| `ignore_rules.py` | Decides which paths to skip during scanning |
| `config.py` | Reads env vars and config file; provides typed accessors (priority: env > config > default) |
| `harumi_config.py` | `config get/set` commands; reads/writes `~/.config/harumi/config.toml` |
| `info.py` | `info` command; shows index stats, storage, LLM settings, and active config |
| `worklog.py` | `worklog` and `retrospect` commands over files and imported activity |
| `status.py` | Reports readiness of Ollama, models, and DB |
