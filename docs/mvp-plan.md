# Harumi MVP Plan

## Objective

Build a local-first assistant that can index selected directories, normalize files into searchable text, generate local summaries with Ollama, and return likely file matches from vague natural-language queries.

The MVP must prove this loop works end to end:

1. scan files
2. normalize content
3. summarize with a local model
4. index metadata and text
5. search with hybrid retrieval
6. show useful file results

## MVP Boundaries

### In scope

- User-configured root directories
- Recursive file scanning
- Ignore rules
- Document normalization with MarkItDown for supported formats
- Direct text ingestion for source code and text-like files
- Local metadata storage in SQLite
- Full-text search with SQLite FTS5
- Local summaries with Ollama
- File-level embeddings with Ollama
- Vector search with LanceDB
- CLI commands for scan, reindex, and find
- Search result explanations

### Out of scope

- OCR
- Real-time file watching
- GUI
- Automatic desktop-wide indexing
- Cloud sync
- Multi-user support
- Cross-file question answering
- Editing or opening files from the app

## User Stories

### Primary

- As a user, I can register one or more root directories to index
- As a user, I can run a scan and see how many files were discovered, indexed, skipped, or failed
- As a user, I can search with vague language and get likely matching files
- As a user, I can inspect why a file was returned
- As a user, I can re-run indexing without reprocessing every unchanged file

### Secondary

- As a user, I can see whether a result was matched mostly by name, path, text, or summary meaning
- As a user, I can limit search to certain roots or file types

## Proposed Commands

```text
harumi init
harumi roots add /path/to/root
harumi roots list
harumi scan
harumi scan --root /path/to/root
harumi find "the note about tax setup"
harumi find "script that uploads screenshots" --type code
harumi status
```

## Functional Requirements

### FR-1 Root management

- Add root directories
- Enable or disable roots
- Persist root configuration locally

Acceptance:

- Root list survives process restart

### FR-2 Scanning

- Walk each enabled root recursively
- Collect metadata for each file
- Apply ignore rules before content extraction

Acceptance:

- Scan reports counts for discovered, ignored, indexed, unchanged, and failed files

### FR-3 Normalization

- Route files by MIME type and extension
- Use MarkItDown for supported document formats
- Read text/code/config files directly
- Store normalized text

Acceptance:

- At least PDF, DOCX, HTML, MD, TXT, PY, TS, JS, JSON, YAML, TOML are handled or explicitly skipped

### FR-4 Summaries

- Generate summaries for document-like files using Ollama
- Save model name and prompt version
- Keep source code searchable as text, with higher-level code summaries deferred to a later phase

Acceptance:

- Summary generation can be skipped for unchanged files
- Very short files and code files may be skipped by policy

### FR-5 Embeddings

- Generate one embedding per file summary
- Persist vectors in a local vector store

Acceptance:

- Query embedding and similarity search return candidates for re-ranking

### FR-6 Full-text search

- Index path, filename, normalized text, and summaries in FTS5

Acceptance:

- Exact filename and path queries return expected files near the top

### FR-7 Hybrid search

- Combine FTS retrieval and vector retrieval
- Re-rank using filename/path boosts and simple heuristics

Acceptance:

- Vague topic queries return at least one useful result in the top few items on a small test corpus

### Future code search extension

- Detect project boundaries using files such as `pyproject.toml`, `package.json`, `go.mod`, or `Cargo.toml`
- Generate semantic summaries for code at folder or project level instead of per file
- Use those summaries to improve vague code-oriented search

### FR-8 Explainable output

- For each result, show:
  - file path
  - file type
  - short summary
  - score
  - match reason

Acceptance:

- User can tell why a result appeared without inspecting the database

## Non-Functional Requirements

- Local-first only
- No mandatory network dependency during indexing or search
- Reasonable indexing throughput on a personal machine
- Recover cleanly from conversion and model failures
- Do not crash the entire scan because one file failed

## Recommended Tech Choices

- Python 3.11+
- `typer`
- `pydantic` and `pydantic-settings`
- `sqlite3`
- `markitdown`
- `ollama`
- `lancedb`
- `python-magic`

## Data Model Summary

### Core tables

- `roots`
- `files`
- `documents`
- `summaries`

### Derived indexes

- `fts_documents`
- `lancedb` summary vectors

## Query Pipeline

1. Accept raw user query
2. Infer intent signals:
   - code vs document
   - possible filename/path terms
   - recency hints
3. Run FTS retrieval
4. Run embedding retrieval
5. Merge candidates
6. Re-rank with heuristics
7. Return top results with explanation

## Directory Layout

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
      cli.py
      config.py
      db.py
      scanner.py
      normalize.py
      summarize.py
      embed.py
      search.py
      ranking.py
      filetypes.py
      ignore_rules.py
      models.py
  tests/
```

## Implementation Sequence

### Step 1: Bootstrap project

Tasks:

- create `pyproject.toml`
- add package layout
- add CLI entrypoint
- add app config path handling

Done when:

- `harumi --help` works

### Step 2: Storage layer

Tasks:

- create SQLite schema
- add migration/init function
- add repository helpers for roots and files

Done when:

- database file is created and schema initializes cleanly

### Step 3: Root management

Tasks:

- implement `roots add`
- implement `roots list`
- validate paths

Done when:

- roots can be added and retrieved across runs

### Step 4: Scanner

Tasks:

- walk configured roots
- apply ignore rules
- collect file metadata
- compute lightweight change detection

Done when:

- scanner can populate `files` records

### Step 5: Normalization

Tasks:

- add file routing
- integrate MarkItDown
- direct-read code and text files
- persist normalized content

Done when:

- readable text is stored for a representative corpus

### Step 6: Summary generation

Tasks:

- integrate Ollama client
- add prompts for short and long summary
- store summary records

Done when:

- indexed files have reusable summaries

### Step 7: FTS indexing

Tasks:

- create FTS5 table
- write sync/update logic
- add simple keyword search

Done when:

- exact and near-exact queries work well

### Step 8: Embeddings and vector search

Tasks:

- add embedding generation
- store summary vectors
- add similarity retrieval

Done when:

- semantic retrieval returns useful candidates

### Step 9: Hybrid search and ranking

Tasks:

- merge FTS and vector candidates
- add ranking weights
- generate explanation strings

Done when:

- vague search is noticeably better than FTS-only

### Step 10: Polish

Tasks:

- add scan status reporting
- improve error handling
- add logging
- add a small fixture corpus for tests

Done when:

- CLI is usable without manual inspection

## Suggested Milestones

### Milestone A: Scanner only

Goal:

- scan roots and store metadata

Commands ready:

- `harumi init`
- `harumi roots add`
- `harumi roots list`
- `harumi scan`

### Milestone B: Searchable text

Goal:

- normalize documents and enable FTS search

Commands ready:

- `harumi find "keyword query"`

### Milestone C: Semantic search

Goal:

- add summaries, embeddings, and hybrid ranking

Commands ready:

- `harumi find "vague natural language query"`

## Risks

### Risk 1: Indexing too much data too early

Mitigation:

- require explicit root registration
- default to aggressive ignore rules

### Risk 2: Slow local summary generation

Mitigation:

- use smaller local models
- summarize only changed files
- start with file-level summaries only

### Risk 3: Poor search quality

Mitigation:

- use hybrid retrieval
- keep explanations visible
- test on a small real corpus before scaling

### Risk 4: Document conversion failures

Mitigation:

- isolate per-file errors
- keep failure state in database
- skip unsupported files cleanly

## First Test Corpus

Before indexing your whole machine, prepare a small but realistic corpus.

Suggested contents:

- a few PDFs
- a few Word docs
- notes in markdown
- source repositories
- config files
- a couple of HTML exports

This will help tune:

- ignore rules
- summary prompts
- ranking weights
- supported file type routing

## Recommended Immediate Next Step

Implement the foundation only:

1. bootstrap the Python project
2. create the database schema
3. add root management and scanning

Do not start with embeddings first.

The fastest path to a useful MVP is:

- metadata
- normalized text
- FTS
- summaries
- vector search
