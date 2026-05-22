from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from harumi.config import get_summary_language, get_work_days, get_work_hours_end, get_work_hours_start
from harumi.db import (
    get_db_path,
    init_db,
    query_activity_events_in_range,
    query_activity_sessions_in_range,
    query_files_in_range,
)
from harumi.config import ensure_app_dirs
from harumi.summarize import _run_summary_prompt, get_summary_model


def _local_day_range(d: date) -> tuple[float, float]:
    local_tz = datetime.now(timezone.utc).astimezone().tzinfo
    start = datetime(d.year, d.month, d.day, tzinfo=local_tz)
    end = start + timedelta(days=1)
    return start.timestamp(), end.timestamp()


def _parse_hhmm(value: str) -> tuple[int, int]:
    hour_text, minute_text = value.split(":", 1)
    hour = int(hour_text)
    minute = int(minute_text)
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        raise ValueError
    return hour, minute


def _work_day_numbers() -> set[int]:
    mapping = {
        "mon": 0,
        "tue": 1,
        "wed": 2,
        "thu": 3,
        "fri": 4,
        "sat": 5,
        "sun": 6,
    }
    return {
        mapping[token.strip()]
        for token in get_work_days().split(",")
        if token.strip() in mapping
    }


def _work_window_for_day(d: date) -> tuple[float, float] | None:
    if d.weekday() not in _work_day_numbers():
        return None
    local_tz = datetime.now(timezone.utc).astimezone().tzinfo
    try:
        start_hour, start_minute = _parse_hhmm(get_work_hours_start())
        end_hour, end_minute = _parse_hhmm(get_work_hours_end())
    except (ValueError, TypeError):
        start_hour, start_minute = 9, 0
        end_hour, end_minute = 18, 0
    start = datetime(d.year, d.month, d.day, start_hour, start_minute, tzinfo=local_tz)
    end = datetime(d.year, d.month, d.day, end_hour, end_minute, tzinfo=local_tz)
    if end <= start:
        end += timedelta(days=1)
    return start.timestamp(), end.timestamp()


def _effective_day_range(d: date, include_private_time: bool) -> tuple[float, float, str]:
    if include_private_time:
        start_ts, end_ts = _local_day_range(d)
        return start_ts, end_ts, "all day"
    work_window = _work_window_for_day(d)
    if work_window is None:
        start_ts, end_ts = _local_day_range(d)
        return start_ts, start_ts, "outside configured work days"
    return work_window[0], work_window[1], f"work hours {get_work_hours_start()}-{get_work_hours_end()}"


def _timestamp_in_work_time(ts: float, local_tz) -> bool:
    local_dt = datetime.fromtimestamp(ts, tz=local_tz)
    window = _work_window_for_day(local_dt.date())
    if window is None:
        return False
    return window[0] <= ts < window[1]


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
        detail = _event_detail(row)
        line = f"  {time_str}  {title}"
        if detail:
            line += f"\n        {detail}"
        lines.append(line)
    return lines


def _event_detail(row: sqlite3.Row) -> str:
    source = row["source"] or ""
    if str(source).startswith("ai:"):
        return ""
    return row["url"] or row["path"] or source


def _build_session_lines(rows: list[sqlite3.Row]) -> list[str]:
    lines = []
    for row in rows:
        start = _format_event_time(row["start_time"])
        end = _format_event_time(row["end_time"])
        title = row["title"] or row["primary_domain"] or "activity"
        summary = row["summary"] or ""
        unit = "messages" if row["session_type"] == "ai" else "visits"
        line = f"  {start}-{end}  {title}  ({row['event_count']} {unit})"
        if summary:
            line += f"\n        {summary}"
        lines.append(line)
    return lines


def _language_instruction() -> str:
    lang = get_summary_language()
    if lang == "ja":
        return "必ず日本語で回答してください。3〜5文で簡潔にまとめてください。"
    if lang == "en":
        return "Respond in English. Summarize in 3-5 concise sentences."
    return f"Respond in {lang} if possible. Summarize in 3-5 concise sentences."


def _build_worklog_prompt(
    date_label: str,
    rows: list[sqlite3.Row],
    events: list[sqlite3.Row],
    sessions: list[sqlite3.Row],
) -> str:
    file_block = "\n".join(
        f"- {row['path']}" + (f"\n  {row['summary_short']}" if row["summary_short"] else "")
        for row in rows
    )
    event_block = "\n".join(
        f"- {row['title'] or '(no title)'}" + (f"\n  {_event_detail(row)}" if _event_detail(row) else "")
        for row in events
    )
    session_block = "\n".join(
        f"- {_format_event_time(row['start_time'])}-{_format_event_time(row['end_time'])} "
        f"{row['title'] or row['primary_domain']}\n  {row['summary']}"
        for row in sessions
    )
    return (
        f"{_language_instruction()}\n\n"
        f"以下は {date_label} の変更ファイル、活動セッション、補助的な活動履歴です。\n"
        "これらの情報からその日の作業内容を 3〜5 文でまとめてください。\n"
        "技術的な詳細よりも「何に取り組んでいたか」を重視してください。\n\n"
        f"ファイル一覧:\n{file_block}\n\n"
        f"活動セッション:\n{session_block}\n\n"
        f"補助的な活動履歴:\n{event_block}"
    )


def _build_retrospect_prompt(
    from_label: str,
    to_label: str,
    day_blocks: list[tuple[str, list[sqlite3.Row], list[sqlite3.Row]]],
    session_blocks: list[tuple[str, list[sqlite3.Row]]],
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
            detail = _event_detail(row)
            block_text += f"- activity: {row['title'] or '(no title)'}"
            if detail:
                block_text += f"\n  {detail}"
            block_text += "\n"
    for day_label, sessions in session_blocks:
        block_text += f"\n【{day_label} activity sessions】\n"
        for row in sessions:
            block_text += (
                f"- {_format_event_time(row['start_time'])}-{_format_event_time(row['end_time'])} "
                f"{row['title'] or row['primary_domain']}\n  {row['summary']}\n"
            )
    return (
        f"{_language_instruction()}\n\n"
        f"以下は {from_label} から {to_label} の期間に変更されたファイルと活動履歴です。\n"
        "この期間に何に取り組んでいたかを 3〜5 文でまとめてください。\n\n"
        f"{block_text}"
    )


def _print_worklog(
    date_label: str,
    rows: list[sqlite3.Row],
    events: list[sqlite3.Row],
    sessions: list[sqlite3.Row],
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
        if sessions:
            print(f"\n### 活動セッション ({len(sessions)}件)\n")
            for row in sessions:
                start = _format_event_time(row["start_time"])
                end = _format_event_time(row["end_time"])
                unit = "messages" if row["session_type"] == "ai" else "visits"
                print(f"- {row['title'] or row['primary_domain']} ({start}-{end}, {row['event_count']} {unit})")
                if row["summary"]:
                    print(f"  - {row['summary']}")
        if events:
            print(f"\n### 補助的な活動履歴 ({len(events)}件)\n")
            for row in events:
                time_str = _format_event_time(row["event_time"])
                print(f"- {row['title'] or '(no title)'} ({time_str})")
                detail = _event_detail(row)
                if detail:
                    print(f"  - {detail}")
    else:
        print(f"=== {date_label} の作業記録 ===\n")
        if summary:
            print(summary)
        print()
        print(f"変更ファイル: {len(rows)}件")
        print(f"活動セッション: {len(sessions)}件")
        print(f"活動履歴: {len(events)}件")
        print()
        for line in _build_file_lines(rows):
            print(line)
        if sessions:
            print()
            print("--- 活動セッション ---")
            for line in _build_session_lines(sessions):
                print(line)
        if events:
            print()
            print("--- 補助的な活動履歴 ---")
            for line in _build_event_lines(events):
                print(line)


def worklog_command(
    date_str: str,
    output: str,
    limit: int,
    no_llm: bool,
    include_private_time: bool,
) -> int:
    try:
        target = _parse_date(date_str)
    except ValueError:
        print(f"日付の形式が正しくありません: {date_str}  (例: 2026-04-30 / today / yesterday)")
        return 2

    db_path = get_db_path(ensure_app_dirs())
    init_db(db_path)

    start_ts, end_ts, range_label = _effective_day_range(target, include_private_time)
    rows = query_files_in_range(db_path, start_ts=start_ts, end_ts=end_ts, limit=limit)
    events = query_activity_events_in_range(
        db_path,
        start_ts=start_ts,
        end_ts=end_ts,
        limit=limit,
        source_prefix=None,
    )
    sessions = query_activity_sessions_in_range(
        db_path,
        start_ts=start_ts,
        end_ts=end_ts,
        limit=limit,
        source_prefix=None,
    )
    events = sorted(events, key=lambda row: float(row["event_time"]))
    sessions = sorted(sessions, key=lambda row: float(row["start_time"]))
    prompt_events = [] if sessions else events

    date_label = target.isoformat()

    if not rows and not events and not sessions:
        print(f"{date_label} の活動はありません（{range_label} / インデックス済みの範囲内）。")
        return 0

    summary: str | None = None
    if not no_llm:
        try:
            prompt = _build_worklog_prompt(date_label, rows, prompt_events, sessions)
            model = get_summary_model()
            summary = _run_summary_prompt(model, prompt[:8000])
        except Exception as exc:
            print(f"[警告] LLM によるサマリー生成に失敗しました: {exc}")

    _print_worklog(f"{date_label} ({range_label})", rows, events, sessions, summary, output)
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
    include_private_time: bool,
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
        source_prefix=None,
    )
    sessions = query_activity_sessions_in_range(
        db_path,
        start_ts=start_ts,
        end_ts=end_ts,
        limit=limit,
        source_prefix=None,
    )

    from_label = label
    to_label = label

    if not rows and not events and not sessions:
        print(f"{label} の活動はありません（インデックス済みの範囲内）。")
        return 0

    # 日ごとにグループ化
    day_blocks: dict[date, list[sqlite3.Row]] = {}
    local_tz = datetime.now(timezone.utc).astimezone().tzinfo
    for row in rows:
        d = datetime.fromtimestamp(row["mtime"], tz=local_tz).date()
        if not include_private_time and not _timestamp_in_work_time(float(row["mtime"]), local_tz):
            continue
        day_blocks.setdefault(d, []).append(row)
    event_day_blocks: dict[date, list[sqlite3.Row]] = {}
    for row in events:
        d = datetime.fromtimestamp(row["event_time"], tz=local_tz).date()
        if not include_private_time and not _timestamp_in_work_time(float(row["event_time"]), local_tz):
            continue
        event_day_blocks.setdefault(d, []).append(row)
    session_day_blocks: dict[date, list[sqlite3.Row]] = {}
    for row in sessions:
        d = datetime.fromtimestamp(row["start_time"], tz=local_tz).date()
        if not include_private_time and not _timestamp_in_work_time(float(row["start_time"]), local_tz):
            continue
        session_day_blocks.setdefault(d, []).append(row)

    sorted_days = sorted(set(day_blocks.keys()) | set(event_day_blocks.keys()) | set(session_day_blocks.keys()))

    if not sorted_days:
        print(f"{label} の勤務時間内の活動はありません（インデックス済みの範囲内）。")
        return 0

    summary: str | None = None
    if not no_llm:
        try:
            blocks = [(d.isoformat(), day_blocks.get(d, []), event_day_blocks.get(d, [])) for d in sorted_days]
            session_blocks = [(d.isoformat(), session_day_blocks.get(d, [])) for d in sorted_days]
            prompt = _build_retrospect_prompt(label, label, blocks, session_blocks)
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
            d_sessions = session_day_blocks.get(d, [])
            print(f"### {d.isoformat()} ({len(d_rows)} files / {len(d_sessions)} sessions / {len(d_events)} events)\n")
            for row in d_rows:
                time_str = _format_mtime(row["mtime"])
                print(f"- `{row['path']}` ({time_str})")
                if row["summary_short"]:
                    print(f"  - {row['summary_short']}")
            for row in d_events:
                time_str = _format_event_time(row["event_time"])
                print(f"- activity: {row['title'] or '(no title)'} ({time_str})")
                detail = _event_detail(row)
                if detail:
                    print(f"  - {detail}")
            for row in d_sessions:
                start = _format_event_time(row["start_time"])
                end = _format_event_time(row["end_time"])
                unit = "messages" if row["session_type"] == "ai" else "visits"
                print(f"- activity session: {row['title'] or row['primary_domain']} ({start}-{end}, {row['event_count']} {unit})")
                if row["summary"]:
                    print(f"  - {row['summary']}")
            print()
    else:
        print(f"=== {label} の作業履歴 ===\n")
        if summary:
            print(summary)
            print()
        for d in sorted_days:
            d_rows = day_blocks.get(d, [])
            d_events = event_day_blocks.get(d, [])
            d_sessions = session_day_blocks.get(d, [])
            print(f"--- {d.isoformat()} ({len(d_rows)} files / {len(d_sessions)} sessions / {len(d_events)} events) ---")
            for line in _build_file_lines(d_rows):
                print(line)
            if d_sessions:
                print("  [activity sessions]")
                for line in _build_session_lines(d_sessions):
                    print(line)
            if d_events:
                print("  [activity]")
                for line in _build_event_lines(d_events):
                    print(line)
            print()

    return 0
