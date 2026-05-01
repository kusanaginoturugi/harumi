# ファイル監視 設計書

英語版: [../watcher-design.md](../watcher-design.md)

## 目的

`harumi watch` コマンドを追加し、有効なすべてのルートディレクトリを監視して、
ファイルの作成・変更・削除・移動を検知したときに差分インデックスを更新する。
`harumi scan` を手動実行する必要がなくなる。

## 使用ライブラリ

`watchdog >= 4.0`

- Linux は inotify、macOS は FSEvents、Windows は ReadDirectoryChanges を使用
- 純粋 Python、追加サービス不要
- `pyproject.toml` の dependencies に追加する

## 新コマンド

```
harumi watch [--debounce 秒数] [--no-summary] [--no-embed]
```

フォアグラウンドで動作する。進捗ログは標準出力と既存の `scan-errors.log` に出力。
Ctrl+C または SIGTERM で停止。

## アーキテクチャ

```
watchdog Observer（ルートごとに1個、recursive=True）
  └─ HarumiEventHandler
       on_created / on_modified → pending_events[path] = PendingEvent(種別, 現在時刻)
       on_deleted               → pending_events[path] = PendingEvent("delete", 現在時刻)
       on_moved                 → pending_events[src]  = PendingEvent("move", 現在時刻, dest)

デバウンスthread（0.5秒ごとに起動）
  pending_events を走査し、
  time.time() - event.seen_at >= DEBOUNCE_SECONDS になったものを
  work_queue に移す

ワーカーthread（シングルスレッド、work_queue を処理）
  CREATE / MODIFY → _process_file_change(path)
  DELETE          → _process_file_delete(path)
  MOVE            → _process_file_delete(src) → _process_file_change(dest)
  DIRイベント     → _process_folder_change(folder_path)
```

### ワーカーをシングルスレッドにする理由

Ollama のサマリー生成・埋め込み呼び出しは逐次的で 5〜30 秒かかる。
シングルスレッドにすることで Ollama の並列呼び出しを避け、
追加のロックなしに SQLite 書き込みの競合も排除できる。
デバウンスステップがバースト（例：50ファイルの git checkout）を吸収し、
ワーカーが処理できる定常的なストリームにまとめる。

### デバウンス

- デフォルト: 2.0 秒
- pending は path をキーにする。同一 path で再度イベントが来たらタイマーをリセット
- エディタがテンポラリファイルを書いてリネームする動作や vim のスワップファイルに対応
- `--debounce` フラグでユーザーが調整可能

## イベント種別ごとの処理

### CREATE または MODIFY

`scanner.py` の1ファイル処理パイプラインをそのまま再利用する:

1. `is_ignored_file(path)` → true なら skip
2. `path.stat()` → size, mtime を取得
3. `upsert_file_record()` → "unchanged" なら早期リターン
4. `normalize_file(path)` → `NormalizedDocument` または `None`
5. ドキュメントがある場合:
   - `upsert_document()`
   - 条件を満たせば `summarize_text()` → `upsert_summary()`
   - `embed_text()` → `upsert_embedding()`
   - `upsert_fts_document()`
6. 親フォルダの再インデックスをトリガー（後述）

### DELETE

1. `files` テーブルから `path = ?` で `file_id` を取得
2. `DELETE FROM fts_documents WHERE rowid = file_id`
3. `DELETE FROM files WHERE path = ?`
   （`ON DELETE CASCADE` により `documents`、`summaries`、`embeddings` も自動削除）
4. 親フォルダの再インデックスをトリガー

### MOVE（src → dest）

1. `_process_file_delete(src)`
2. `_process_file_change(dest)`

### フォルダ変更（DirModified、DirCreated）

`scanner._index_folder()` のロジックを再実行する:

1. `content_fingerprint` を再計算
2. `upsert_folder_record()` → フィンガープリントが変わっていなければ skip
3. 内容が変わっていればフォルダのサマリー・埋め込みを再生成
4. `upsert_fts_folder()`

フォルダ削除はそれほど重要ではない。
ファイルが削除されるとフォルダが空になり、
次の `harumi scan` 時に孤立したフォルダレコードを整理できる。

## db.py に追加が必要な関数

```python
def get_file_id_by_path(db_path: Path, path: str) -> int | None:
    """絶対パスから file_id を返す。見つからなければ None。"""

def delete_file_by_path(db_path: Path, path: str) -> bool:
    """file レコードと fts_documents 行を削除する。CASCADE が残りを処理する。
    削除が行われたら True を返す。"""

def get_root_for_path(db_path: Path, path: str) -> sqlite3.Row | None:
    """指定パスに対して最長プレフィックスマッチとなるルート行（id, path）を返す。"""
```

## 新モジュール: `watcher.py`

```python
DEBOUNCE_SECONDS = 2.0

@dataclass
class PendingEvent:
    path: str
    event_type: str          # "create" | "modify" | "delete" | "move"
    dest_path: str | None    # "move" のみ
    seen_at: float           # time.time()

class FileWatcher:
    def __init__(self, db_path: Path, debounce: float = DEBOUNCE_SECONDS,
                 summarize: bool = True, embed: bool = True) -> None

    def start(self) -> None
        """ブロッキング。ルートを読み込み Observer を起動し KeyboardInterrupt まで実行。"""

    def _load_and_schedule_roots(self, observer: Observer) -> None
    def _debounce_loop(self) -> None   # thread で実行
    def _worker_loop(self) -> None     # thread で実行
    def _process_file_change(self, path: Path, root_id: int) -> None
    def _process_file_delete(self, path: str) -> None
    def _process_folder_change(self, folder_path: Path, root_id: int) -> None
```

`HarumiEventHandler` はルートごとに生成する
`watchdog.events.FileSystemEventHandler` のサブクラスで、
`observer.schedule(handler, root_path, recursive=True)` に渡す。

## pyproject.toml の変更

```toml
dependencies = [
  "markitdown>=0.1.0",
  "watchdog>=4.0",
]
```

## 実行中のルート変更への対応

初回起動時: DB から有効なルートを全件読み込み、各ルートをスケジュールする。
**v1 のシンプルな方針**: `watch` 実行中のホットリロードはサポートしない。
`harumi roots add` 後は `watch` を再起動するよう案内メッセージを出す。

将来の改善案: 60 秒ごとに `roots` テーブルをポーリングし、
新規追加・無効化されたルートに対して `observer.schedule` / `observer.unschedule` を動的に行う。

## systemd ユーザーサービス（任意）

ログイン時に自動起動したい場合:

```ini
# ~/.config/systemd/user/harumi-watch.service
[Unit]
Description=Harumi file watcher
After=default.target

[Service]
ExecStart=/home/USER/.venv/bin/harumi watch
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
```

有効化:

```bash
systemctl --user enable --now harumi-watch.service
```

## 既知の制限と今後の課題

- **フォルダ削除の孤立レコード**: フォルダが削除されても `folders` 行が残る。
  将来 `harumi prune` コマンドで整理する。
- **大規模バースト**: `git clone` などで大量イベントが発生したとき、
  キュー深さが閾値を超えたら `run_scan()` にフォールバックする仕組みを検討する。
- **ベクトル検索のメモリ**: クエリ時に全埋め込みをメモリに読み込む実装はウォッチャーとは無関係だが、
  インデックスが大きくなると影響が出てくる。
- **NFS/ネットワークマウント**: Linux の inotify はネットワークファイルシステムを監視できない。
