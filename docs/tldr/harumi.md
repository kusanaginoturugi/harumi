# harumi

> Local-first file indexing, semantic search, and worklog assistant.
> More information: <https://github.com/kusanaginoturugi/harumi>.

- Initialize local storage:

`harumi init`

- Register a directory and scan it:

`harumi roots add {{~/Documents}} && harumi scan`

- Search indexed files and folders with natural language:

`harumi find "{{recent travel document}}"`

- Show index, storage, model, and config status:

`harumi info`

- Import browser history as activity events (dry-run first, then execute):

`harumi browser-history import --last {{7d}}`

`harumi browser-history import --last {{7d}} --execute --confirm IMPORT-BROWSER-HISTORY`

- Import AI assistant history from ChatGPT, Claude, or Gemini exports:

`harumi ai-history import {{path/to/export.zip}} --provider {{chatgpt|claude|gemini}}`

`harumi ai-history import {{path/to/export.zip}} --provider {{chatgpt|claude|gemini}} --execute --confirm IMPORT-AI-HISTORY`

- Summarize work for a day without calling the LLM:

`harumi worklog --date {{2026-05-21|today|yesterday}} --no-llm`

- Retrospect a year, month, or day:

`harumi retrospect {{2026|202605|20260521}}`

- Set persistent config:

`harumi config set {{summary_model}} {{qwen3:14b}}`

- Rebuild summaries and embeddings after changing summary policy:

`harumi regenerate-summaries --scope {{all|files|folders}} --execute --confirm RESET-SUMMARIES`
