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
- browser history import for work logs
- AI assistant export import for work logs
- worklog and retrospect reports from files and activity

## Quick start

```bash
scripts/install.sh
harumi init
harumi roots add ~/Documents
harumi scan
harumi find "recent travel document"
```

The install script creates a local virtualenv, installs Harumi from the source checkout, installs the recommended MarkItDown PDF/Office extras, and links `harumi` into `~/.local/bin`.

If `~/.local/bin` is not in your `PATH`, add this to your shell config:

```bash
export PATH="$HOME/.local/bin:$PATH"
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

Manual editable install, if you do not use `scripts/install.sh`:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e .
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

Scan roots and refresh configured activity imports:

```bash
harumi scan
harumi scan --progress-percent 5
harumi scan --quiet
harumi scan --files-only
harumi scan --no-browser-history
harumi scan --no-ai-history
```

Search for files or folders:

```bash
harumi find "the file about winter tax payments"
harumi find "script that uploads screenshots to cloud"
harumi find "where is the travel folder"
```

Use Downloads as normal indexed files:

```bash
harumi roots add ~/Downloads
harumi scan
```

Project-specific scan exclusions can be defined with `.harumiignore` at the root of each indexed directory.

```gitignore
# .harumiignore
vendor/
gems/
*.log
tmp/
```

Check local readiness:

```bash
harumi status
```

Show index, storage, model, and config status:

```bash
harumi info
```

Manage persistent configuration in `~/.config/harumi/config.toml`:

```bash
harumi config get
harumi config get summary_model
harumi config set summary_model qwen3:14b
harumi config set work_hours_start 09:00
```

Dangerous maintenance command for rebuilding summaries after changing language or summary policy:

```bash
harumi regenerate-summaries --scope all --execute --confirm RESET-SUMMARIES
```

## Activity imports and work logs

Harumi can import browser history and AI assistant exports as local activity. `harumi scan` refreshes browser history and configured AI exports by default. Use `--files-only`, `--no-browser-history`, or `--no-ai-history` to opt out for a single scan.

Manual import commands are dry-run by default and require an explicit confirmation token before writing to the database.

Import browser history:

```bash
harumi browser-history sources
harumi browser-history import --last 7d
harumi browser-history import --last 7d --execute --confirm IMPORT-BROWSER-HISTORY
harumi browser-history import --since-last --execute --confirm IMPORT-BROWSER-HISTORY
```

Browser imports strip URL query strings and fragments by default. Use `--keep-query` only when you intentionally want full URLs stored. Use `--redact-title` if page titles are too sensitive. Harumi intentionally does not inspect sandboxed Snap or Flatpak browser profile directories; those installations are treated as isolated app data.

Import AI assistant history:

```bash
harumi ai-history import ~/Downloads/chatgpt-export.zip
harumi ai-history import ~/Downloads/chatgpt-export.zip --execute --confirm IMPORT-AI-HISTORY

harumi ai-history import ~/Downloads/claude-export.zip --provider claude --execute --confirm IMPORT-AI-HISTORY
harumi ai-history import ~/Downloads/gemini-takeout.zip --provider gemini --execute --confirm IMPORT-AI-HISTORY
harumi ai-history import ~/Downloads/gemini-takeout.zip --provider gemini --since-last --execute --confirm IMPORT-AI-HISTORY
```

Supported AI providers:

- `chatgpt`: OpenAI data export zip or `conversations.json`
- `claude`: Claude export zip containing `conversations.json`
- `gemini`: Google Takeout Gemini activity HTML zip

To make `harumi scan` refresh AI history, configure export paths:

```bash
harumi config set ai_history_chatgpt_path ~/Downloads/chatgpt-export.zip
harumi config set ai_history_claude_path ~/Downloads/claude-export.zip
harumi config set ai_history_gemini_path ~/Downloads/gemini-takeout.zip
```

Imported activity is stored as raw activity events and compressed into sessions for `harumi worklog` / `harumi retrospect`. Worklog output hides AI export file paths because they are implementation metadata, not useful work context.

Summarize work for a day:

```bash
harumi worklog
harumi worklog --date yesterday
harumi worklog --refresh
harumi worklog --date 2026-05-21 --no-llm
harumi worklog --date 2026-05-21 --output markdown
```

Look back by year, month, or day:

```bash
harumi retrospect 2026
harumi retrospect 202605
harumi retrospect 20260521 --no-llm
```

`worklog` and `retrospect` use configured work hours by default, so private-time activity stays out of normal reports. Configure the window with `work_hours_start`, `work_hours_end`, and `work_days`, and use `--include-private-time` when you explicitly want the full day:

```bash
harumi config set work_hours_start 09:00
harumi config set work_hours_end 18:00
harumi config set work_days mon,tue,wed,thu,fri
harumi worklog --include-private-time
```

## Environment variables

Harumi uses these environment variables when needed:

- `HARUMI_HOME`
  - override the default local storage directory
- `HARUMI_CONFIG`
  - override the config file path
- `HARUMI_SUMMARY_MODEL`
  - summary model name for Ollama
- `HARUMI_SUMMARY_LANGUAGE`
  - summary output language, default `ja`
- `HARUMI_EMBED_MODEL`
  - embedding model name for Ollama
- `HARUMI_ENABLE_SUMMARY`
  - set to `0` to disable summary generation
- `HARUMI_SUMMARY_MIN_CHARS`
  - minimum normalized text length to summarize, default `400`
- `HARUMI_SUMMARY_CODE`
  - set to `1` to summarize code and config files too
- `HARUMI_ENABLE_EMBEDDING`
  - set to `0` to disable embedding generation
- `HARUMI_FOLDER_SUMMARY_MIN_ITEMS`
  - minimum number of visible child items before summarizing a folder, default `2`
- `HARUMI_WORK_HOURS_START`
  - worklog start time, default `09:00`
- `HARUMI_WORK_HOURS_END`
  - worklog end time, default `18:00`
- `HARUMI_WORK_DAYS`
  - comma-separated work days, default `mon,tue,wed,thu,fri`
- `HARUMI_SCAN_BROWSER_HISTORY`
  - set to `0` to stop `harumi scan` from importing browser history
- `HARUMI_SCAN_BROWSER_HISTORY_LAST`
  - browser history range used by `harumi scan`, default `7d`
- `HARUMI_SCAN_AI_HISTORY`
  - set to `0` to stop `harumi scan` from importing configured AI exports
- `HARUMI_AI_HISTORY_CHATGPT_PATH`
  - ChatGPT export path used by `harumi scan`
- `HARUMI_AI_HISTORY_CLAUDE_PATH`
  - Claude export path used by `harumi scan`
- `HARUMI_AI_HISTORY_GEMINI_PATH`
  - Gemini export path used by `harumi scan`

Example:

```bash
HARUMI_SUMMARY_MODEL=gemma3:latest \
HARUMI_SUMMARY_LANGUAGE=ja \
HARUMI_EMBED_MODEL=embeddinggemma \
harumi scan
```

To keep large scans faster, Harumi skips summaries for very short files by default, and it does not summarize code files unless `HARUMI_SUMMARY_CODE=1` is set.

## Notes

- Harumi stores data locally under `~/.local/share/harumi` by default
- folder search is supported alongside file search
- recent files get a small ranking boost, but strong semantic and keyword matches still matter more
- broad root folders are lightly penalized during folder-oriented search queries
- deleted or moved paths are not pruned yet; see the stale/prune and inode move-tracking GitHub issues
