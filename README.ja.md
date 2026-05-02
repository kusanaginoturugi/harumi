# Harumi

Harumi は、ローカル PC 上のファイルを索引化し、要約と埋め込みを保存して、あいまいな自然言語クエリから関連ファイルやフォルダを見つけるためのローカルファーストなアシスタントです。

現在の主な機能:

- ルートディレクトリ管理
- 再帰スキャン
- テキスト/コードの直接読込
- MarkItDown による文書正規化
- Ollama によるローカル要約
- 埋め込みベースの意味検索
- フォルダも含めた検索とランキング

## クイックスタート

```bash
scripts/install.sh
harumi init
harumi roots add ~/Documents
harumi scan
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

スキャン:

```bash
harumi scan
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

ブラウザ履歴は worklog 用の activity event として取り込みます。既定は dry-run で、URL の query string は `--keep-query` を付けない限り保存しません。

```bash
harumi browser-history sources
harumi browser-history import --last 7d
harumi browser-history import --last 7d --execute --confirm IMPORT-BROWSER-HISTORY
```

環境チェック:

```bash
harumi status
```

言語や要約方針を変えたあとに summary を作り直したいときは、危険コマンドを明示実行します。

```bash
harumi regenerate-summaries --scope all --execute --confirm RESET-SUMMARIES
```

## 環境変数

- `HARUMI_HOME`
  - ローカル保存先を上書きする
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
- `HARUMI_ENABLE_EMBEDDING`
  - `0` にすると embedding 生成を無効化
- `HARUMI_FOLDER_SUMMARY_MIN_ITEMS`
  - フォルダ要約を作る最小子要素数。既定値は `2`

例:

```bash
HARUMI_SUMMARY_MODEL=gemma3:latest \
HARUMI_SUMMARY_LANGUAGE=ja \
HARUMI_EMBED_MODEL=embeddinggemma \
harumi scan
```

大規模スキャンを少し軽くするため、Harumi は既定で短すぎる文書の要約を省き、コードファイルは `HARUMI_SUMMARY_CODE=1` を指定したときだけ要約します。

## メモ

- 既定の保存先は `~/.local/share/harumi`
- フォルダも独立した検索対象
- 新しい情報は少し加点するが、semantic / keyword の強い一致のほうを優先する
- フォルダ検索では broad な root フォルダに軽い減点を入れている
