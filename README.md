# Harumi

Harumi is a local-first assistant for indexing files, storing summaries, and finding relevant files from vague natural-language queries.

HARUMI stands for `Hierarchical Assistant for Retrieval, Understanding, Metadata, and Indexing`.

Current status:

- root directory management
- recursive file scanning
- text/code normalization
- document normalization through MarkItDown
- local summaries through Ollama
- embedding-based semantic search
- folder-aware search and ranking

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e .
pip install -U "markitdown[all]"
harumi init
harumi roots add ~/Documents
harumi scan
harumi find "recent travel document"
```

## Requirements

- Python 3.11+
- Ollama running locally
- an installed summary model, for example `gemma3:latest`
- an installed embedding model, for example `embeddinggemma`

Recommended Ollama setup:

```bash
ollama pull gemma3:latest
ollama pull embeddinggemma
```

Recommended MarkItDown setup for Harumi document ingestion:

```bash
pip install -U "markitdown[pdf,docx,pptx,xlsx,xls]"
```

## What Harumi does

Harumi indexes selected root directories and stores:

- file metadata
- normalized text
- short summaries
- embeddings for semantic search
- folder summaries and folder embeddings

Current normalization behavior:

- text and source files are read directly
- PDF, DOCX, HTML, CSV, and similar document formats are converted through MarkItDown

If you only install base `markitdown`, some document converters may be unavailable. For Harumi, you usually do not need `markitdown[all]`. A narrower install such as `markitdown[pdf,docx,pptx,xlsx,xls]` is usually better because it avoids unrelated extras like YouTube transcription support, which may fail to resolve on some Python versions.

## Basic commands

Initialize local storage:

```bash
harumi init
```

Register a root directory:

```bash
harumi roots add ~/Documents
```

List registered roots:

```bash
harumi roots list
```

Scan roots and build indexes:

```bash
harumi scan
```

Search for files or folders:

```bash
harumi find "the file about winter tax payments"
harumi find "script that uploads screenshots to cloud"
harumi find "where is the travel folder"
```

Check local readiness:

```bash
harumi status
```

## Environment variables

Harumi uses these environment variables when needed:

- `HARUMI_HOME`
  - override the default local storage directory
- `HARUMI_SUMMARY_MODEL`
  - summary model name for Ollama
- `HARUMI_EMBED_MODEL`
  - embedding model name for Ollama
- `HARUMI_ENABLE_SUMMARY`
  - set to `0` to disable summary generation
- `HARUMI_ENABLE_EMBEDDING`
  - set to `0` to disable embedding generation

Example:

```bash
HARUMI_SUMMARY_MODEL=gemma3:latest \
HARUMI_EMBED_MODEL=embeddinggemma \
harumi scan
```

## Notes

- Harumi stores data locally under `~/.local/share/harumi` by default
- folder search is supported alongside file search
- recent files get a small ranking boost, but strong semantic and keyword matches still matter more
- broad root folders are lightly penalized during folder-oriented search queries
