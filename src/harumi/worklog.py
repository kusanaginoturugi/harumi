from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from harumi.config import get_summary_language
from harumi.db import get_db_path, init_db, query_activity_events_in_range, query_files_in_range
from harumi.config import ensure_app_dirs
from harumi.summarize import _run_summary_prompt, get_summary_model


def _local_day_range(d: date) -> tuple[float, float]:
    local_tz = datetime.now(timezone.utc).astimezone().tzinfo
    start = datetime(d.year, d.month, d.day, tzinfo=local_tz)
    end = start + timedelta(days=1)
    return start.timestamp(), end.timestamp()


def _parse_date(value: str) -> date:
    today = date.today()
    if value in ("today", ""):
        return today
    if value == "yesterday":
        return today - timedelta(days=1)
    return date.fromisoformat(value)


def _format_mtime(ts: float) -> str:
    local_tz = datetime.now(timezone.utc).astimezone().tzinfo
    return datetime.fromtimestamp(ts, tz=local_tz).strftime("%H:%M")


def _format_event_time(ts: float) -> str:
    return _format_mtime(ts)


def _build_file_lines(rows: list[sqlite3.Row]) -> list[str]:
    lines = []
    for row in rows:
        time_str = _format_mtime(row["mtime"])
        summary = row["summary_short"]
        line = f"  {time_str}  {row['path']}"
        if summary:
            line += f"\n        {summary}"
        lines.append(line)
    return lines


def _build_event_lines(rows: list[sqlite3.Row]) -> list[str]:
    lines = []
    for row in rows:
        time_str = _format_event_time(row["event_time"])
        title = row["title"] or "(no title)"
        url = row["url"]
        lines.append(f"  {time_str}  {title}\n        {url}")
    return lines


def _language_instruction() -> str:
    lang = get_summary_language()
    if lang == "ja":
        return "必ず日本語で回答してください。3〜5文で簡潔にまとめてください。"
    if lang == "en":
        return "Respond in English. Summarize in 3-5 concise sentences."
    return f"Respond in {lang} if possible. Summarize in 3-5 concise sentences."


def _build_worklog_prompt(date_label: str, rows: list[sqlite3.Row], events: list[sqlite3.Row]) -> str:
    file_block = "\n".join(
        f"- {row['path']}" + (f"\n  {row['summary_short']}" if row["summary_short"] else "")
        for row in rows
    )
    event_block = "\n".join(
        f"- {row['title'] or '(no title)'}\n  {row['url']}"
        for row in events
    )
    return (
        f"{_language_instruction()}\n\n"
        f"以下は {date_label} の変更ファイルとブラウザ閲覧履歴です。\n"
        "これらの情報からその日の作業内容を 3〜5 文でまとめてください。\n"
        "技術的な詳細よりも「何に取り組んでいたか」を重視してください。\n\n"
        f"ファイル一覧:\n{file_block}\n\n"
        f"ブラウザ履歴:\n{event_block}"
    )


def _build_retrospect_prompt(
    from_label: str,
    to_label: str,
    day_blocks: list[tuple[str, list[sqlite3.Row], list[sqlite3.Row]]],
) -> str:
    block_text = ""
    for day_label, rows, events in day_blocks:
        block_text += f"\n【{day_label}】\n"
        for row in rows:
            block_text += f"- {row['path']}"
            if row["summary_short"]:
                block_text += f"\n  {row['summary_short']}"
            block_text += "\n"
        for row in events:
            block_text += f"- browser: {row['title'] or '(no title)'}\n  {row['url']}\n"
    return (
        f"{_language_instruction()}\n\n"
        f"以下は {from_label} から {to_label} の期間に変更されたファイルとブラウザ閲覧履歴です。\n"
        "この期間に何に取り組んでいたかを 3〜5 文でまとめてください。\n\n"
        f"{block_text}"
    )


def _print_worklog(
    date_label: str,
    rows: list[sqlite3.Row],
    events: list[sqlite3.Row],
    summary: str | None,
    output: str,
) -> None:
    if output == "markdown":
        print(f"## {date_label} の作業記録\n")
        if summary:
            print(f"{summary}\n")
        print(f"### 変更ファイル ({len(rows)}件)\n")
        for row in rows:
            time_str = _format_mtime(row["mtime"])
            print(f"- `{row['path']}` ({time_str})")
            if row["summary_short"]:
                print(f"  - {row['summary_short']}")
        if events:
            print(f"\n### ブラウザ履歴 ({len(events)}件)\n")
            for row in events:
                time_str = _format_event_time(row["event_time"])
                print(f"- {row['title'] or '(no title)'} ({time_str})")
                print(f"  - {row['url']}")
    else:
        print(f"=== {date_label} の作業記録 ===\n")
        if summary:
            print(summary)
            print()
        print(f"変更ファイル: {len(rows)}件")
        print(f"ブラウザ履歴: {len(events)}件")
        print()
        for line in _build_file_lines(rows):
            print(line)
        if events:
            print()
            print("--- ブラウザ履歴 ---")
            for line in _build_event_lines(events):
                print(line)


def worklog_command(
    date_str: str,
    output: str,
    limit: int,
    no_llm: bool,
) -> int:
    try:
        target = _parse_date(date_str)
    except ValueError:
        print(f"日付の形式が正しくありません: {date_str}  (例: 2026-04-30 / today / yesterday)")
        return 2

    db_path = get_db_path(ensure_app_dirs())
    init_db(db_path)

    start_ts, end_ts = _local_day_range(target)
    rows = query_files_in_range(db_path, start_ts=start_ts, end_ts=end_ts, limit=limit)
    events = query_activity_events_in_range(
        db_path,
        start_ts=start_ts,
        end_ts=end_ts,
        limit=limit,
        source_prefix="browser:",
    )

    date_label = target.isoformat()

    if not rows and not events:
        print(f"{date_label} の活動はありません（インデックス済みの範囲内）。")
        return 0

    summary: str | None = None
    if not no_llm:
        try:
            prompt = _build_worklog_prompt(date_label, rows, events)
            model = get_summary_model()
            summary = _run_summary_prompt(model, prompt[:8000])
        except Exception as exc:
            print(f"[警告] LLM によるサマリー生成に失敗しました: {exc}")

    _print_worklog(date_label, rows, events, summary, output)
    return 0


def _parse_period(period: str) -> tuple[float, float, str]:
    """
    4桁 → 年, 6桁 → 年月, 8桁 → 日
    戻り値: (start_ts, end_ts, label)
    """
    local_tz = datetime.now(timezone.utc).astimezone().tzinfo
    s = period.strip()
    try:
        if len(s) == 4:
            year = int(s)
            start = datetime(year, 1, 1, tzinfo=local_tz)
            end = datetime(year + 1, 1, 1, tzinfo=local_tz)
            label = f"{year}年"
        elif len(s) == 6:
            year, month = int(s[:4]), int(s[4:])
            start = datetime(year, month, 1, tzinfo=local_tz)
            end = datetime(year + 1, 1, 1, tzinfo=local_tz) if month == 12 else datetime(year, month + 1, 1, tzinfo=local_tz)
            label = f"{year}-{month:02d}"
        elif len(s) == 8:
            year, month, day = int(s[:4]), int(s[4:6]), int(s[6:])
            start = datetime(year, month, day, tzinfo=local_tz)
            end = start + timedelta(days=1)
            label = f"{year}-{month:02d}-{day:02d}"
        else:
            raise ValueError
    except (ValueError, OverflowError):
        raise ValueError(f"期間の形式が正しくありません: {period!r}  (例: 2026 / 202604 / 20260430)")
    return start.timestamp(), end.timestamp(), label


def retrospect_command(
    period: str,
    output: str,
    limit: int,
    no_llm: bool,
) -> int:
    try:
        start_ts, end_ts, label = _parse_period(period)
    except ValueError as exc:
        print(exc)
        return 2

    db_path = get_db_path(ensure_app_dirs())
    init_db(db_path)

    rows = query_files_in_range(db_path, start_ts=start_ts, end_ts=end_ts, limit=limit)
    events = query_activity_events_in_range(
        db_path,
        start_ts=start_ts,
        end_ts=end_ts,
        limit=limit,
        source_prefix="browser:",
    )

    from_label = label
    to_label = label

    if not rows and not events:
        print(f"{label} の活動はありません（インデックス済みの範囲内）。")
        return 0

    # 日ごとにグループ化
    day_blocks: dict[date, list[sqlite3.Row]] = {}
    local_tz = datetime.now(timezone.utc).astimezone().tzinfo
    for row in rows:
        d = datetime.fromtimestamp(row["mtime"], tz=local_tz).date()
        day_blocks.setdefault(d, []).append(row)
    event_day_blocks: dict[date, list[sqlite3.Row]] = {}
    for row in events:
        d = datetime.fromtimestamp(row["event_time"], tz=local_tz).date()
        event_day_blocks.setdefault(d, []).append(row)

    sorted_days = sorted(set(day_blocks.keys()) | set(event_day_blocks.keys()))

    summary: str | None = None
    if not no_llm:
        try:
            blocks = [(d.isoformat(), day_blocks.get(d, []), event_day_blocks.get(d, [])) for d in sorted_days]
            prompt = _build_retrospect_prompt(label, label, blocks)
            model = get_summary_model()
            summary = _run_summary_prompt(model, prompt[:8000])
        except Exception as exc:
            print(f"[警告] LLM によるサマリー生成に失敗しました: {exc}")

    if output == "markdown":
        print(f"## {label} の作業履歴\n")
        if summary:
            print(f"{summary}\n")
        for d in sorted_days:
            d_rows = day_blocks.get(d, [])
            d_events = event_day_blocks.get(d, [])
            print(f"### {d.isoformat()} ({len(d_rows)} files / {len(d_events)} browser)\n")
            for row in d_rows:
                time_str = _format_mtime(row["mtime"])
                print(f"- `{row['path']}` ({time_str})")
                if row["summary_short"]:
                    print(f"  - {row['summary_short']}")
            for row in d_events:
                time_str = _format_event_time(row["event_time"])
                print(f"- browser: {row['title'] or '(no title)'} ({time_str})")
                print(f"  - {row['url']}")
            print()
    else:
        print(f"=== {label} の作業履歴 ===\n")
        if summary:
            print(summary)
            print()
        for d in sorted_days:
            d_rows = day_blocks.get(d, [])
            d_events = event_day_blocks.get(d, [])
            print(f"--- {d.isoformat()} ({len(d_rows)} files / {len(d_events)} browser) ---")
            for line in _build_file_lines(d_rows):
                print(line)
            if d_events:
                print("  [browser]")
                for line in _build_event_lines(d_events):
                    print(line)
            print()

    return 0
