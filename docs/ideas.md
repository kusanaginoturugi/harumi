# Extension Ideas

Ideas for extending Harumi beyond the current CLI-based MVP.
Captured after the basic indexing pipeline (scan, summarize, embed, find) was working.

## High value, low effort

### File watcher (`harumi watch`)

Watch enabled roots with `watchdog` and re-index incrementally on file changes.
Eliminates the need to run `harumi scan` manually after every edit.
Design document: [watcher-design.md](watcher-design.md)

### Web UI

A local web interface for search and browsing.
Backend: FastAPI, wrapping the existing `search.py` / `db.py` layer.
Frontend: Vanilla JS + HTML, or Svelte for a richer experience.
Key screens: search box → result list with summaries, click to open file in OS.

## Medium value, moderate effort

### MCP server

Expose Harumi as a Model Context Protocol tool so AI agents (Claude Code, etc.)
can call `harumi find` directly from within a session.
Thin wrapper over `find_command()` returning structured JSON.

### RAG-style Q&A (`harumi ask`)

Use `find` to retrieve relevant files, then pass their content to Ollama
and answer a natural-language question.
Useful when the user wants to read rather than navigate.

### Duplicate and near-duplicate detection (`harumi duplicates`)

Cosine similarity is already computed at query time.
A batch command could compare all embeddings pairwise (or via approximate nearest
neighbour) and surface likely duplicates or near-identical files.

### Manual tagging

Store user-assigned tags in a new `file_tags` table.
Enable `harumi find --tag travel` and show tags in search results.

## Interesting, more speculative

### TUI (Textual)

Interactive terminal UI using the `textual` library.
`harumi tui` opens a full-screen search interface with keyboard navigation,
no browser required.

### Systemd user service

Document and ship a `.service` unit file that starts `harumi watch`
automatically on login.

### Project-boundary detection

Detect `pyproject.toml`, `package.json`, `go.mod`, `Cargo.toml`, etc.
and generate a single project-level summary instead of per-file summaries
for source trees.

## Suggested order of implementation

1. File watcher — keeps index fresh, multiplies the value of all other features
2. Web UI — makes search accessible without memorizing CLI syntax
3. MCP server — connects Harumi to AI workflows
