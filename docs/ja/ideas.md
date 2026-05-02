# 拡張アイデア

CLIベースのMVP（scan/summarize/embed/find）が動作した後に検討する拡張案。

英語版: [../ideas.md](../ideas.md)

## 価値が高く、実装しやすいもの

### ファイル監視 (`harumi watch`)

`watchdog` を使って有効なルートを監視し、ファイル変更時に差分インデックスを更新する。
`harumi scan` を手動実行しなくて済むようになる。
設計書: [watcher-design.md](watcher-design.md)

### Web UI

ローカル向けの検索・ブラウズ画面。
バックエンドは FastAPI（既存の `search.py` / `db.py` をそのまま使う）。
フロントエンドは Vanilla JS+HTML か Svelte。
主要画面: 検索ボックス → サマリー付き結果一覧 → クリックでOSがファイルを開く。

## 価値が中程度で、少し工数が必要なもの

### MCP サーバー化

Harumi を MCP ツールとして公開し、Claude Code などの AI エージェントから
セッション内で直接 `harumi find` を呼べるようにする。
`find_command()` の薄いラッパーで実現可能。

### RAG スタイルの Q&A (`harumi ask`)

`find` で関連ファイルを取得し、そのコンテキストを Ollama に渡して
自然言語の質問に回答する。ファイルを「開かずに内容を把握したい」場面に有効。

### 重複・類似ファイル検出 (`harumi duplicates`)

クエリ時のコサイン類似度計算は既に実装済み。
全埋め込みをバッチ比較（または近似近傍探索）して、ほぼ同一のファイルを列挙する。

### 手動タグ付け

`file_tags` テーブルにユーザー指定タグを保存。
`harumi find --tag 旅行` のようなフィルタや、検索結果へのタグ表示を可能にする。

## 面白いが、やや先の話

### TUI（Textual）

`textual` ライブラリによるターミナル内インタラクティブUI。
`harumi tui` でフルスクリーンの検索画面を起動。ブラウザ不要。

### systemd ユーザーサービス

`harumi watch` をログイン時に自動起動する `.service` ユニットを用意する。

### プロジェクト境界の検出

`pyproject.toml`、`package.json`、`go.mod`、`Cargo.toml` などを検出し、
ソースツリーをファイル単位ではなくプロジェクト単位でサマリーを生成する。

## 実装順の提案

1. ファイル監視 — インデックスを常に新鮮に保ち、他の機能の価値を高める
2. Web UI — CLIコマンドを覚えなくても検索できるようにする
3. MCP サーバー — AI ワークフローに Harumi を組み込む
