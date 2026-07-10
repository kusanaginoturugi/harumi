# Harumi

Harumi は、ローカル PC 上のファイルを索引化し、要約と埋め込みを保存して、あいまいな自然言語クエリから関連ファイルやフォルダを見つけるためのローカルファーストなアシスタントです。

現在の主な機能:

- ルートディレクトリ管理
- 再帰スキャンと高速 quickscan
- テキスト/コードの直接読込
- MarkItDown による文書正規化
- Ollama によるローカル要約
- 埋め込みベースの意味検索
- フォルダも含めた検索とランキング
- ブラウザ履歴の作業記録への取り込み
- 生成 AI 履歴エクスポートの作業記録への取り込み
- ファイル更新と activity に基づく worklog / retrospect

## クイックスタート

```bash
scripts/install.sh
harumi init
harumi roots add ~/Documents
harumi scan
harumi quickscan
harumi find "最近の旅行書類"
```

インストールスクリプトは、リポジトリ内に `.venv` を作り、Harumi を editable install し、推奨の MarkItDown PDF/Office extras を入れたうえで、`~/.local/bin/harumi` へリンクを作ります。

`~/.local/bin` が `PATH` に入っていない場合は、シェル設定に次を追加します。

```bash
export PATH="$HOME/.local/bin:$PATH"
```

## 前提

- Python 3.11+
- ローカルで動く Ollama
- summary 用モデル
  - 例: `gemma3:latest`
- embedding 用モデル
  - 例: `embeddinggemma`

推奨セットアップ:

```bash
ollama pull gemma3:latest
ollama pull embeddinggemma
```

Harumi 用の推奨 MarkItDown セットアップ:

```bash
pip install -U "markitdown[pdf,docx,pptx,xlsx,xls]"
```

`scripts/install.sh` を使わずに手動で入れる場合:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e .
pip install -U "markitdown[pdf,docx,pptx,xlsx,xls]"
```

## Harumi が保存するもの

- ファイルメタデータ
- 正規化済み本文
- 短い要約
- semantic search 用の embedding
- フォルダ summary
- フォルダ embedding

## 正規化の方針

- テキスト/コード系はそのまま読む
- PDF、DOCX、HTML、CSV などは MarkItDown で Markdown に変換する

ただし、`markitdown` 本体だけだと一部の文書変換機能が入らないことがあります。Harumi では通常 `markitdown[all]` までは不要で、`markitdown[pdf,docx,pptx,xlsx,xls]` のように必要な extras だけ入れるほうが安全です。`all` には YouTube transcription など Harumi では不要な extras も含まれ、Python のバージョンによっては依存解決に失敗することがあります。

## 基本コマンド

初期化:

```bash
harumi init
```

ルート追加:

```bash
harumi roots add ~/Documents
```

ルート一覧:

```bash
harumi roots list
```

通常の高速更新:

```bash
harumi quickscan
harumi quickscan --quiet
harumi quickscan --files-only
harumi quickscan --no-browser-history
harumi quickscan --no-ai-history
```

初回や `.harumiignore` 変更後など、全体を見直したいときの full scan:

```bash
harumi scan
harumi scan --progress-percent 5
harumi scan --quiet
harumi scan --files-only
harumi scan --no-browser-history
harumi scan --no-ai-history
```

検索:

```bash
harumi find "冬の税金支払いのファイル"
harumi find "スクショをクラウドに送るスクリプト"
harumi find "旅行フォルダはどこ"
```

Downloads は通常の索引対象として追加します。

```bash
harumi roots add ~/Downloads
harumi scan
```

プロジェクト単位の除外は、索引ルート直下の `.harumiignore` で定義できます。

```gitignore
# .harumiignore
vendor/
gems/
*.log
tmp/
```

環境チェック:

```bash
harumi status
```

インデックス、保存先、モデル、設定の状態確認:

```bash
harumi info
```

永続設定は `~/.config/harumi/config.toml` に保存します。

```bash
harumi config get
harumi config get summary_model
harumi config set summary_model qwen3:14b
harumi config set work_hours_start 09:00
```

言語や要約方針を変えたあとに summary を作り直したいときは、危険コマンドを明示実行します。

```bash
harumi regenerate-summaries --scope all --execute --confirm RESET-SUMMARIES
```

## Activity 取り込みと作業記録

Harumi はブラウザ履歴と生成 AI のエクスポートをローカル activity として取り込めます。`harumi quickscan` / `harumi scan` は既定でブラウザ履歴と設定済み AI export を更新します。1 回だけ外したい場合は `--files-only`、`--no-browser-history`、`--no-ai-history` を使います。

手動取り込みコマンドは既定で dry-run で、DB に書き込むには明示的な確認トークンが必要です。

ブラウザ履歴の取り込み:

```bash
harumi browser-history sources
harumi browser-history import --last 7d
harumi browser-history import --last 7d --execute --confirm IMPORT-BROWSER-HISTORY
harumi browser-history import --since-last --execute --confirm IMPORT-BROWSER-HISTORY
```

ブラウザ取り込みでは、既定で URL の query string と fragment を保存しません。完全な URL を保存したいときだけ `--keep-query` を使ってください。ページタイトルも保存したくない場合は `--redact-title` を使います。Harumi は Snap / Flatpak 版ブラウザのサンドボックス化されたプロファイルディレクトリは意図的に参照しません。それらは独立したアプリデータとして扱います。

生成 AI 履歴の取り込み:

```bash
harumi ai-history import ~/Downloads/chatgpt-export.zip
harumi ai-history import ~/Downloads/chatgpt-export.zip --execute --confirm IMPORT-AI-HISTORY

harumi ai-history import ~/Downloads/claude-export.zip --provider claude --execute --confirm IMPORT-AI-HISTORY
harumi ai-history import ~/Downloads/gemini-takeout.zip --provider gemini --execute --confirm IMPORT-AI-HISTORY
harumi ai-history import ~/Downloads/gemini-takeout.zip --provider gemini --since-last --execute --confirm IMPORT-AI-HISTORY
```

対応 provider:

- `chatgpt`: OpenAI のデータエクスポート zip または `conversations.json`
- `claude`: `conversations.json` を含む Claude エクスポート zip
- `gemini`: Google Takeout の マイアクティビティをエクスポート HTML zip

`harumi quickscan` / `harumi scan` で AI 履歴も更新するには、export path を設定します。

```bash
harumi config set ai_history_chatgpt_path ~/Downloads/chatgpt-export.zip
harumi config set ai_history_claude_path ~/Downloads/claude-export.zip
harumi config set ai_history_gemini_path ~/Downloads/gemini-takeout.zip
```

取り込んだ activity は生の activity event として保存し、`harumi worklog` / `harumi retrospect` で使いやすいように session へ圧縮します。AI 履歴の export ファイルパスは作業内容としてはノイズなので、worklog 表示では隠します。

1 日の作業記録:

```bash
harumi worklog
harumi worklog --date yesterday
harumi worklog --refresh
harumi worklog --date 2026-05-21 --no-llm
harumi worklog --date 2026-05-21 --output markdown
```

年・月・日単位の振り返り:

```bash
harumi retrospect 2026
harumi retrospect 202605
harumi retrospect 20260521 --no-llm
```

`worklog` と `retrospect` は既定で設定された勤務時間内だけを表示します。私用時間の activity は通常のレポートには出しません。勤務時間は `work_hours_start`、`work_hours_end`、`work_days` で設定し、明示的に全時間帯を見たい場合だけ `--include-private-time` を使います。

```bash
harumi config set work_hours_start 09:00
harumi config set work_hours_end 18:00
harumi config set work_days mon,tue,wed,thu,fri
harumi worklog --include-private-time
```

## 環境変数

- `HARUMI_HOME`
  - ローカル保存先を上書きする
- `HARUMI_CONFIG`
  - 設定ファイルパスを上書きする
- `HARUMI_SUMMARY_MODEL`
  - Ollama の summary モデル名
- `HARUMI_SUMMARY_LANGUAGE`
  - 要約の出力言語。既定値は `ja`
- `HARUMI_EMBED_MODEL`
  - Ollama の embedding モデル名
- `HARUMI_ENABLE_SUMMARY`
  - `0` にすると要約生成を無効化
- `HARUMI_SUMMARY_MIN_CHARS`
  - 要約対象にする最小文字数。既定値は `400`
- `HARUMI_SUMMARY_CODE`
  - `1` にするとコードや設定ファイルも要約する
- `HARUMI_SUMMARY_CSV`
  - `1` にすると CSV も要約する。既定では CSV は正規化・検索対象に残し、要約だけ作らない
- `HARUMI_ENABLE_EMBEDDING`
  - `0` にすると embedding 生成を無効化
- `HARUMI_FOLDER_SUMMARY_MIN_ITEMS`
  - フォルダ要約を作る最小子要素数。既定値は `2`
- `HARUMI_WORK_HOURS_START`
  - worklog の開始時刻。既定値は `09:00`
- `HARUMI_WORK_HOURS_END`
  - worklog の終了時刻。既定値は `18:00`
- `HARUMI_WORK_DAYS`
  - worklog 対象曜日。既定値は `mon,tue,wed,thu,fri`
- `HARUMI_SCAN_BROWSER_HISTORY`
  - `0` にすると `harumi quickscan` / `harumi scan` でブラウザ履歴を取り込まない
- `HARUMI_SCAN_BROWSER_HISTORY_LAST`
  - `harumi quickscan` / `harumi scan` が使うブラウザ履歴の範囲。既定値は `7d`
- `HARUMI_SCAN_AI_HISTORY`
  - `0` にすると `harumi quickscan` / `harumi scan` で設定済み AI export を取り込まない
- `HARUMI_AI_HISTORY_CHATGPT_PATH`
  - `harumi quickscan` / `harumi scan` が使う ChatGPT export path
- `HARUMI_AI_HISTORY_CLAUDE_PATH`
  - `harumi quickscan` / `harumi scan` が使う Claude export path
- `HARUMI_AI_HISTORY_GEMINI_PATH`
  - `harumi quickscan` / `harumi scan` が使う Gemini export path

例:

```bash
HARUMI_SUMMARY_MODEL=gemma3:latest \
HARUMI_SUMMARY_LANGUAGE=ja \
HARUMI_EMBED_MODEL=embeddinggemma \
harumi scan
```

大規模スキャンを少し軽くするため、Harumi は既定で短すぎる文書の要約を省き、コードファイルは `HARUMI_SUMMARY_CODE=1`、CSV は `HARUMI_SUMMARY_CSV=1` を指定したときだけ要約します。

## メモ

- 既定の保存先は `~/.local/share/harumi`
- フォルダも独立した検索対象
- 新しい情報は少し加点するが、semantic / keyword の強い一致のほうを優先する
- フォルダ検索では broad な root フォルダに軽い減点を入れている
- 削除・移動済み path の prune は未実装。stale/prune と inode 移動追跡の GitHub issue を参照
