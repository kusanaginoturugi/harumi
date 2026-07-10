# Agent Handoff

## 2026-07-10

作業計画:

- `harumi quickscan` を full scan より軽い通常更新コマンドとして追加する。
- quickscan と scan の activity import 挙動を揃える。
- ChatGPT export の `conversations-*.json` shard 形式を import できるようにする。
- 実 export やローカルDBを誤ってコミットしないように ignore する。

作業記録:

- `scan_state` を追加し、root ごとの full scan / quickscan 時刻を保存するようにした。
- `harumi quickscan` と `worklog --refresh` の quickscan 化を追加した。
- CSV は既定では正規化・検索対象に残しつつ、要約だけ省く設定にした。
- ChatGPT export zip で `conversations.json` が直接ない場合、`export_manifest.json` の `logical_files` / `resources` から shard 一覧を読み、会話配列を結合するようにした。
- `data/` と `llm_logs/` を `.gitignore` に追加した。

引き継ぎ:

- 実 ZIP の dry-run で `Conversations read: 1735` を確認済み。
- `pytest` は venv に入っていないため、検証は `.venv/bin/python -m unittest ...` を使った。
- `gh auth status` は token invalid だが、remote は SSH なので `git push` は SSH で行う。
