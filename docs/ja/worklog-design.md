# 作業記録機能 設計書

## 概要

Harumi に「今日（または指定期間）に何をしていたか」を自動でまとめる機能を追加する。

2 つのコマンドとして実装する:

| コマンド | 用途 |
|---|---|
| `harumi worklog` | 今日（またはデフォルト期間）の作業をまとめる |
| `harumi retrospect` | 日付・期間を指定して過去の作業を振り返る |

---

## 背景と動機

Harumi はすでにファイルの mtime を SQLite に保存している。
`files` テーブルの `mtime`（UNIX timestamp, REAL型）と `summaries` テーブルの `summary_short` を組み合わせると、
「その日に変更されたファイルとその内容」を低コストで取得できる。

この情報を Ollama に渡せば、1 日の作業サマリーを自動生成できる。

---

## 実現可能性の評価

### できること（高確実性）

- **mtime ベースのファイル絞り込み**: `files.mtime` を日付でフィルタすれば、その日に更新されたファイル一覧が取れる。SQL だけで完結する。
- **既存サマリーの再利用**: `summaries.summary_short` が存在すれば、再度 Ollama を呼ばずにまとめられる。
- **Ollama によるサマリー合成**: ファイル一覧とその要約を Ollama に渡してサマリーを生成する。`summarize.py` の `_run_summary_prompt()` をそのまま流用できる。
- **日付パース**: `YYYY-MM-DD` 形式と `today` / `yesterday` に対応するのは Python 標準ライブラリだけで十分。

### 制約・注意点

- **mtime = 変更時刻**: 読んだだけのファイルは記録されない。「閲覧」は対象外。
- **インデックス外のファイルは見えない**: `harumi roots add` したディレクトリ外のファイルは対象外。
- **スキャン前の変更は拾えない**: `harumi scan` を実行していない期間のファイルは mtime が DB に反映されていない場合がある。
- **シェル履歴・ブラウザ履歴は別途対応が必要**: オプション機能として後から追加できるが、初期実装では対象外。

### オプション拡張（後から追加可能）

- `~/.zsh_history` / `~/.bash_history` の読み込み（コマンド履歴）
- `git log` の取り込み（インデックス配下の git リポジトリを検出して実行）
- systemd journal の取り込み（`journalctl --since today`）

初期実装はシンプルに Harumi DB のみを使う。

---

## コマンド仕様

### `harumi worklog`

```
harumi worklog [--date DATE] [--output FORMAT] [--limit N]
```

**引数:**

| 引数 | 説明 | デフォルト |
|---|---|---|
| `--date DATE` | 対象日 (`YYYY-MM-DD`, `today`, `yesterday`) | `today` |
| `--output FORMAT` | 出力形式 (`text`, `markdown`) | `text` |
| `--limit N` | 対象ファイル数の上限 | 50 |
| `--no-llm` | Ollama での合成をスキップ、ファイル一覧のみ出力 | false |

**動作フロー:**

1. `--date` をパースして開始・終了 UNIX timestamp を算出
2. DB から該当期間に mtime が入るファイルを取得（サマリーも JOIN）
3. 件数が 0 なら「その日の変更なし」を表示して終了
4. `--no-llm` なら一覧だけ表示して終了
5. ファイル一覧 + サマリーを worklog 用プロンプトに組み立て
6. Ollama でサマリーを生成して出力

**出力例（text）:**

```
=== 2026-04-30 の作業記録 ===

変更ファイル: 12件

作業まとめ:
Harumi の作業記録機能の設計と実装を進めた。docs/ に設計書を追加し、
src/harumi/worklog.py に新しいコマンドを実装した。
また設定ファイルの env var 対応を整理した。

--- 変更ファイル一覧 ---
1. ~/src/harumi/docs/ja/worklog-design.md  (2026-04-30 14:23)
   設計書
2. ~/src/harumi/src/harumi/worklog.py      (2026-04-30 16:45)
   作業記録コマンドの実装
...
```

---

### `harumi retrospect`

```
harumi retrospect [--date DATE | --from DATE --to DATE] [--output FORMAT] [--limit N]
```

**引数:**

| 引数 | 説明 | デフォルト |
|---|---|---|
| `--date DATE` | 特定の 1 日 (`YYYY-MM-DD`) | なし |
| `--from DATE` | 期間の開始日 | なし |
| `--to DATE` | 期間の終了日 | なし（`--from` と同日） |
| `--days N` | 今日から N 日前まで | なし |
| `--output FORMAT` | 出力形式 (`text`, `markdown`) | `text` |
| `--limit N` | 対象ファイル数の上限 | 100 |
| `--no-llm` | ファイル一覧のみ（LLM 合成なし） | false |

`--date`, `--from/--to`, `--days` のいずれか 1 つが必須。

**動作フロー:**

1. 期間を解釈して開始・終了 timestamp を算出
2. DB からその期間に変更されたファイルを取得
3. 期間内の日ごとにファイルをグループ化
4. 日ごとのサマリーを生成（期間が 1 日なら worklog と同じ流れ）
5. 全体まとめを Ollama で生成

**出力例（--from 2026-04-28 --to 2026-04-30）:**

```
=== 2026-04-28 〜 2026-04-30 の作業履歴 ===

全体まとめ:
3日間で Harumi の作業記録機能を設計・実装した。設計フェーズで
仕様書を整備し、実装フェーズでコマンドと DB クエリを追加した。

--- 2026-04-28 (3件) ---
- ~/Documents/notes/design-draft.md
...

--- 2026-04-29 (5件) ---
...

--- 2026-04-30 (12件) ---
...
```

---

## 実装設計

### 新規ファイル

**`src/harumi/worklog.py`**

責務: 日付ベースのファイル取得、プロンプト構築、Ollama 呼び出し、出力整形。

```python
# 主要な関数
def query_files_by_date_range(db_path, start_ts, end_ts, limit) -> list[Row]
def build_worklog_prompt(date_label, file_rows) -> str
def format_file_list(file_rows) -> str
def worklog_command(date, output_format, limit, no_llm) -> int
def retrospect_command(date, from_date, to_date, days, output_format, limit, no_llm) -> int
```

### DB クエリ（追加なし・既存テーブルで完結）

```sql
SELECT
    files.path,
    files.filename,
    files.extension,
    files.mtime,
    files.size_bytes,
    COALESCE(summaries.summary_short, '') AS summary_short
FROM files
LEFT JOIN summaries ON summaries.file_id = files.id
WHERE files.mtime >= :start_ts
  AND files.mtime < :end_ts
ORDER BY files.mtime DESC
LIMIT :limit
```

スキーマ変更は不要。既存の `files` と `summaries` テーブルで全て完結する。

### 追加する DB 関数（`db.py`）

```python
def query_files_in_range(
    db_path: Path,
    *,
    start_ts: float,
    end_ts: float,
    limit: int = 100,
) -> list[sqlite3.Row]: ...
```

### プロンプト設計

worklog 用プロンプト（`summarize.py` の `_summary_language_instructions()` を流用）:

```
{言語指示}

以下は {日付} に変更されたファイルの一覧と要約です。
これらのファイルからその日の作業内容を 3〜5 文でまとめてください。
技術的な詳細より「何に取り組んでいたか」を重視してください。

ファイル一覧:
{ファイルパス + サマリーの箇条書き}
```

### `cli.py` への追加

```python
# サブコマンド追加
worklog_parser = subparsers.add_parser("worklog", ...)
worklog_parser.add_argument("--date", default="today")
worklog_parser.add_argument("--output", choices=("text", "markdown"), default="text")
worklog_parser.add_argument("--limit", type=int, default=50)
worklog_parser.add_argument("--no-llm", action="store_true")

retrospect_parser = subparsers.add_parser("retrospect", ...)
retrospect_parser.add_argument("--date")
retrospect_parser.add_argument("--from", dest="from_date")
retrospect_parser.add_argument("--to", dest="to_date")
retrospect_parser.add_argument("--days", type=int)
retrospect_parser.add_argument("--output", choices=("text", "markdown"), default="text")
retrospect_parser.add_argument("--limit", type=int, default=100)
retrospect_parser.add_argument("--no-llm", action="store_true")
```

---

## 実装の優先順位

| フェーズ | 内容 | 難易度 |
|---|---|---|
| 1 | `query_files_in_range()` を db.py に追加 | 低 |
| 2 | `worklog.py` 新規作成、ファイル一覧表示のみ（`--no-llm` 相当） | 低 |
| 3 | Ollama によるサマリー合成（`worklog` コマンド完成） | 低〜中 |
| 4 | `retrospect` コマンド（日付範囲 + 日ごとグループ化） | 中 |
| 5 | markdown 出力対応 | 低 |
| 6 | シェル履歴・git log の統合（オプション） | 中〜高 |

フェーズ 1〜4 が最小実用版。フェーズ 5〜6 は後から追加できる。

---

## 未解決の問題

1. **サマリーがないファイルの扱い**: `summary_short` が空のファイルはパス名だけで判断するしかない。ファイル名から内容を推測するか、スキップするかを決める必要がある。
   - 案: パス名と拡張子だけをプロンプトに含める（十分実用的）

2. **大量ファイル時のプロンプト肥大化**: `--limit` で制限するが、上位 N 件をどう選ぶか（mtime 降順でいい？）。
   - 案: mtime 降順で最大 50 件、プロンプトは最大 8000 文字でトリム

3. **タイムゾーン**: `files.mtime` は UNIX timestamp（UTC）。ローカル時刻に合わせて日付境界を計算する必要がある。
   - 案: Python の `datetime` に `local_timezone` を使う（`datetime.now().astimezone().utcoffset()` で offset 取得）

4. **`--days` の基点**: 「今日から N 日前まで」の「今日」はローカル時刻の今日。
