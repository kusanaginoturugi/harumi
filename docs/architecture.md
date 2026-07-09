# Harumi Architecture

> Historical design note: this document records the original architecture direction.
> For current user-facing commands and supported imports, use `README.md` and `harumi --help` as the source of truth.

## Goal

Harumi is a local-first assistant that helps find files and folders from vague natural-language instructions.
It scans user-selected directories on the local machine, extracts text from documents and source files, stores normalized markdown and summaries, and returns likely matches with reasons.

Core requirements:

- Index local documents and source files
- Convert supported document formats to markdown with Microsoft MarkItDown
- Summarize file contents with a local LLM via Ollama
- Persist metadata, markdown, summaries, and search indexes locally
- Support vague search queries such as "the note about tax setup from last winter" or "the script that syncs photos to S3"
- Re-index incrementally when files change

Non-goals for the first version:

- Full desktop-wide indexing with zero configuration
- Perfect OCR or perfect handling of every binary format
- Multi-user support
- Remote sync

## Product Shape

The app is closer to a personal search engine than to a document chat tool.

AnythingLLM is adjacent, but its center of gravity is workspace chat over selected documents. Harumi instead needs:

- durable file-level indexing
- stable local metadata storage
- incremental updates
- file and folder discovery as the main result
- summaries as search aids rather than only chat context

## Recommended Stack

### Language

- Python 3.11+

Reason:

- Strong ecosystem for file processing
- Easy integration with MarkItDown and Ollama
- Fast enough for an MVP

### Core libraries

- `markitdown`
  - Convert Office/PDF/HTML and other supported formats into markdown
- `ollama`
  - Generate summaries and embeddings using local models
- `sqlite3`
  - Persist metadata and normalized content
- `SQLite FTS5`
  - Full-text search over filenames, paths, markdown, and summaries
- SQLite tables
  - Store embedding vectors as JSON for the current implementation
- `watchdog`
  - File change monitoring
- `python-magic`
  - MIME detection
- `argparse`
  - CLI
- `fastapi`
  - Local API for a future GUI
- `pydantic` and `pydantic-settings`
  - Config and typed data models

### Why hybrid search is required

Vector search alone is not enough.

- Full-text search is better for exact names, filenames, extensions, symbols, and path fragments
- Vector search is better for vague requests and conceptual matching
- The best ranking will combine both

## System Overview

### Main components

1. Scanner
   - Walk selected root directories
   - Collect file metadata
   - Skip ignored directories and unsupported files

2. Normalizer
   - Route each file to a handler
   - Use MarkItDown for document formats
   - Read source code and plain text directly
   - Normalize everything into markdown-like text

3. Chunker
   - Split long normalized text into chunks for embeddings and optional detailed retrieval

4. Summarizer
   - Use a local Ollama model to generate document summaries
   - Prefer folder-level or project-level summaries for source code collections
   - Save summary text and summary metadata

5. Indexer
   - Save file metadata, normalized markdown, chunks, summaries, and embeddings
   - Build full-text and vector indexes

6. Search engine
   - Turn vague queries into embeddings
   - Run FTS and vector retrieval
   - Re-rank results with heuristics

7. Assistant layer
   - Return file and folder candidates with reasons
   - Offer explainable results instead of opaque embeddings-only matches

8. Activity importers
   - Import browser history as activity events and sessions
   - Import ChatGPT, Claude, and Gemini exports as AI activity
   - Feed imported activity into worklog and retrospect reports
   - `harumi scan` refreshes configured activity imports unless opted out

## Data Flow

1. User configures one or more root directories
2. Scanner discovers files and computes metadata
3. Router chooses document conversion strategy
4. Content is normalized to markdown or plain text
5. Content hash is checked to avoid duplicate work
6. Summary is generated if the file is new or changed
7. Chunks and summary embeddings are generated
8. Metadata, text, and vectors are stored
9. Configured browser and AI exports are imported as activity during scan
10. Query pipeline combines keyword and semantic retrieval
11. Ranked file and folder results are returned

## File Type Strategy

### Use MarkItDown for

- PDF
- Word, PowerPoint, Excel when supported
- HTML
- CSV and structured document-like formats where markdown output is useful
- Email and archive-like formats if supported by the installed version

### Do not force MarkItDown for

- Source code
- Small plain text files
- Config files
- JSON, YAML, TOML when raw text is more useful than transformed markdown

For code and config, direct text ingestion is usually better because:

- structure matters
- line-level search matters
- markdown conversion adds little value

For semantic search, code should usually not be summarized file by file. A better long-term strategy is:

- keep code searchable as raw text for exact and structural lookup
- generate summaries at folder or project boundaries
- detect project boundaries from files such as `pyproject.toml`, `package.json`, `go.mod`, or `Cargo.toml`
- use those higher-level summaries for vague code-oriented queries

## Storage Design

Use local storage under a dedicated application directory, for example:

```text
~/.local/share/harumi/
  config.toml
  harumi.db
  cache/
    normalized/
    summaries/
  logs/
```

### SQLite schema sketch

`roots`

- `id`
- `path`
- `enabled`
- `created_at`

`files`

- `id`
- `root_id`
- `path`
- `parent_path`
- `filename`
- `extension`
- `mime_type`
- `size_bytes`
- `mtime`
- `content_hash`
- `ingest_status`
- `last_indexed_at`
- `error_message`

`documents`

- `file_id`
- `normalized_text`
- `normalized_format`
- `char_count`
- `token_estimate`

`summaries`

- `file_id`
- `summary_short`
- `summary_long`
- `model_name`
- `prompt_version`
- `generated_at`

`chunks`

- `id`
- `file_id`
- `chunk_index`
- `chunk_text`
- `char_count`

`query_history`

- `id`
- `query_text`
- `created_at`

### FTS table sketch

`fts_documents`

- `path`
- `filename`
- `parent_path`
- `normalized_text`
- `summary_short`
- `summary_long`

Recommended approach:

- Keep canonical data in ordinary SQLite tables
- Maintain FTS5 virtual tables for retrieval

### Vector storage

Current implementation:

- store one embedding per indexed file or folder
- store vectors as JSON arrays in SQLite
- compute cosine similarity in Python at query time

Possible future direction:

- move vectors to a dedicated local vector store when SQLite JSON vectors become too slow

Alternative:

- `Qdrant` if you want a dedicated vector DB process later

## Search Strategy

### Query types Harumi should handle

- Topic search
  - "the invoice parser notes"
- Task memory search
  - "the file about setting up tax payments"
- Code discovery
  - "the script that uploads screenshots"
- Folder discovery
  - "where do I keep old travel docs"
- Time-biased search
  - "the doc I edited around January"

### Retrieval stages

1. Parse query
   - detect possible filename terms, dates, code intent, and folder intent

2. Full-text retrieval
   - search path, filename, summary, and normalized text

3. Vector retrieval
   - embed the query and compare with file summary vectors and chunk vectors

4. Re-ranking
   - boost exact filename hits
   - boost path matches
   - boost recent files when the query implies recency
   - boost source files when the query looks code-related
   - boost folders when the user asks for a folder

5. Result explanation
   - return the match reason
   - show a short summary
   - show the file path

### Ranking sketch

Final score can be a weighted blend:

```text
score =
  0.35 * fts_score +
  0.35 * vector_score +
  0.15 * filename_path_boost +
  0.10 * recency_boost +
  0.05 * filetype_intent_boost
```

These weights will need empirical tuning.

## Summary Strategy

Use two summaries per file:

- `summary_short`
  - 1 to 3 sentences for result display
- `summary_long`
  - structured summary for retrieval and inspection

Suggested long-summary structure:

- what this file is
- key topics
- notable entities
- likely use case
- code-specific notes if the file is source code

For very large files:

- summarize selected chunks first
- then summarize the chunk summaries into a file-level summary

## Model Strategy

You already have Ollama installed, so use separate models by role.

Recommended model roles:

- Summary model
  - general instruct model with good compression and local speed
- Embedding model
  - dedicated embedding model if available in Ollama

Selection criteria:

- small enough to batch locally
- stable JSON or structured output if requested
- acceptable throughput on your machine

Practical note:

- do not use the largest model for all indexing work
- indexing throughput matters more than peak reasoning quality

## Ignore Rules

The app should support explicit include and ignore patterns.

Default ignores should include:

- `.git/`
- `node_modules/`
- `.venv/`
- `venv/`
- `dist/`
- `build/`
- `.cache/`
- OS metadata folders
- files above a configured size threshold

This is necessary to avoid wasting time and disk on low-value data.

## Incremental Indexing

Do not reprocess every file on each run.

Re-index only if one of these changes:

- path first seen
- `mtime` changed
- file size changed
- content hash changed
- summary prompt version changed
- model version changed and re-index is requested

Recommended approach:

- cheap pre-check with `mtime` and size
- content hash only when needed

## Security and Privacy

The app is local-first, but there are still security concerns.

- Index only user-approved roots
- Allow exclude lists for sensitive directories
- Record whether files were summarized or only indexed
- Avoid sending content outside the machine
- Keep model endpoints local
- Log failures without dumping entire sensitive documents

## MVP Scope

The MVP should be intentionally small.

### MVP features

- Configure scan roots
- Scan files recursively
- Normalize supported documents
- Read source code and text files directly
- Generate one short summary and one long summary per file
- Store metadata and normalized text in SQLite
- Build FTS index
- Generate file-level embeddings
- Support CLI query such as `harumi find "the doc about taxes"`
- Return top matches with path, summary, and reason

### MVP explicitly excludes

- OCR pipeline
- GUI
- Live folder watching
- Cross-device sync
- Per-chunk citation answers
- Agentic task execution

## Suggested Project Layout

```text
harumi/
  pyproject.toml
  README.md
  docs/
    architecture.md
    mvp-plan.md
  src/
    harumi/
      __init__.py
      config.py
      cli.py
      scanner.py
      normalize.py
      summarize.py
      embed.py
      storage.py
      search.py
      ranking.py
      models.py
      ignore_rules.py
      filetypes.py
  tests/
    test_scanner.py
    test_normalize.py
    test_search.py
```

## Implementation Plan

### Phase 1: Foundation

- Initialize Python project
- Add config loading
- Create SQLite schema
- Implement root registration and file scanner
- Add ignore rules and MIME detection

Exit criteria:

- app can discover files and store metadata

### Phase 2: Content normalization

- Integrate MarkItDown for supported document types
- Add direct text ingestion for code and config files
- Save normalized text

Exit criteria:

- app can persist readable text for major target file types

### Phase 3: Summaries

- Integrate Ollama summary generation
- Add prompt templates
- Save short and long summaries

Exit criteria:

- each indexed file can have a stable reusable summary

### Phase 4: Retrieval

- Add FTS5 indexing
- Add embedding generation
- Add vector store
- Implement hybrid ranking

Exit criteria:

- app can find likely files from vague natural-language queries

### Phase 5: Usability

- Add CLI commands for scan, reindex, and find
- Add reason strings to result ranking
- Add optional local API for GUI integration

Exit criteria:

- usable end to end without manual DB inspection

## Open Decisions

These should be resolved before coding the indexing pipeline deeply.

- Which exact document formats matter most in your corpus
- Whether chunk embeddings are needed in MVP or only file-level embeddings
- Which Ollama models you want to standardize on
- Whether folders should get synthetic summaries based on child files
- Whether to support OCR in a later phase
- Whether the first UI should be CLI-only or local web

## Recommendation

Build this as a custom local-first indexing app.

Start with:

- Python
- MarkItDown
- Ollama
- SQLite FTS5
- LanceDB

This is enough to validate the core promise quickly without prematurely introducing distributed systems or a heavyweight desktop app shell.
