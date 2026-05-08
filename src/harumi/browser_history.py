from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import tempfile
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from harumi.db import (
    delete_activity_sessions_in_range,
    get_activity_import_state,
    query_activity_events_in_range,
    upsert_activity_events,
    upsert_activity_import_state,
    upsert_activity_sessions,
)


CHROME_EPOCH_OFFSET_SECONDS = 11644473600


@dataclass(frozen=True)
class BrowserHistorySource:
    browser: str
    profile: str
    kind: str
    path: Path


@dataclass
class BrowserHistoryImportStats:
    sources_seen: int = 0
    visits_seen: int = 0
    visits_after_filters: int = 0
    imported: int = 0
    sessions_rebuilt: int = 0
    session_rows_changed: int = 0
    since_last: bool = False


def discover_browser_history_sources() -> list[BrowserHistorySource]:
    home = Path.home()
    candidates: list[BrowserHistorySource] = []

    for browser, base in (
        ("chrome", home / ".config" / "google-chrome"),
        ("chromium", home / ".config" / "chromium"),
        ("brave", home / ".config" / "BraveSoftware" / "Brave-Browser"),
    ):
        if base.exists():
            for history_path in sorted(base.glob("*/History")):
                if history_path.is_file():
                    candidates.append(
                        BrowserHistorySource(
                            browser=browser,
                            profile=history_path.parent.name,
                            kind="chromium",
                            path=history_path,
                        )
                    )

    for firefox_base in (
        home / ".mozilla" / "firefox",
        home / ".config" / "mozilla" / "firefox",
    ):
        if not firefox_base.exists():
            continue
        for places_path in sorted(firefox_base.glob("*/places.sqlite")):
            if places_path.is_file():
                candidates.append(
                    BrowserHistorySource(
                        browser="firefox",
                        profile=places_path.parent.name,
                        kind="firefox",
                        path=places_path,
                    )
                )

    return candidates


def parse_date_range(from_date: str | None, to_date: str | None, last: str | None) -> tuple[float, float, str]:
    local_tz = datetime.now(timezone.utc).astimezone().tzinfo
    if from_date:
        start_day = date.fromisoformat(from_date)
        end_day = date.fromisoformat(to_date) if to_date else start_day
        start = datetime(start_day.year, start_day.month, start_day.day, tzinfo=local_tz)
        end = datetime(end_day.year, end_day.month, end_day.day, tzinfo=local_tz) + timedelta(days=1)
        if end <= start:
            raise ValueError("--to must be on or after --from.")
        return start.timestamp(), end.timestamp(), f"{start_day.isoformat()} to {end_day.isoformat()}"

    duration_label = last or "7d"
    delta = _parse_last_duration(duration_label)
    end = datetime.now(local_tz)
    start = end - delta
    return start.timestamp(), end.timestamp(), f"last {duration_label}"


def _parse_last_duration(value: str) -> timedelta:
    raw = value.strip().lower()
    if not raw:
        raise ValueError("--last must not be empty.")
    unit = raw[-1]
    amount_text = raw[:-1] if unit in {"d", "h"} else raw
    amount = int(amount_text)
    if amount <= 0:
        raise ValueError("--last must be positive.")
    if unit == "h":
        return timedelta(hours=amount)
    if unit == "d" or unit.isdigit():
        return timedelta(days=amount)
    raise ValueError("--last supports values like 24h, 7d, or 30.")


def import_browser_history(
    db_path: Path,
    *,
    sources: list[BrowserHistorySource],
    start_ts: float,
    end_ts: float,
    execute: bool,
    strip_url_query: bool = True,
    redact_title: bool = False,
    include_domains: list[str] | None = None,
    exclude_domains: list[str] | None = None,
    limit_per_source: int = 1000,
    since_last: bool = False,
    rebuild_sessions: bool = True,
    session_gap_minutes: int = 30,
) -> BrowserHistoryImportStats:
    stats = BrowserHistoryImportStats(sources_seen=len(sources), since_last=since_last)
    all_events: list[dict] = []
    include_domains = [domain.lower() for domain in include_domains or []]
    exclude_domains = [domain.lower() for domain in exclude_domains or []]
    actual_start_ts = end_ts
    actual_end_ts = start_ts
    latest_event_by_source: dict[str, float] = {}

    for source in sources:
        source_key = _source_key(source)
        source_start_ts = start_ts
        if since_last:
            state = get_activity_import_state(db_path, source_key)
            if state is not None and float(state["last_event_time"]) > 0:
                source_start_ts = max(source_start_ts, float(state["last_event_time"]) + 0.001)

        visits = _read_source_visits(source, source_start_ts, end_ts, limit_per_source)
        stats.visits_seen += len(visits)
        if visits:
            actual_start_ts = min(actual_start_ts, min(float(visit["event_time"]) for visit in visits))
            actual_end_ts = max(actual_end_ts, max(float(visit["event_time"]) for visit in visits))
            latest_event_by_source[source_key] = max(float(visit["event_time"]) for visit in visits)
        for visit in visits:
            url = visit["url"]
            parsed = urlsplit(url)
            if parsed.scheme not in {"http", "https"}:
                continue
            domain = (parsed.hostname or "").lower()
            if include_domains and not _domain_matches_any(domain, include_domains):
                continue
            if exclude_domains and _domain_matches_any(domain, exclude_domains):
                continue

            stored_url = _strip_query_and_fragment(url) if strip_url_query else url
            title = "" if redact_title else visit["title"]
            stats.visits_after_filters += 1
            all_events.append(
                {
                    "source": source_key,
                    "event_type": "browser_visit",
                    "event_time": visit["event_time"],
                    "title": title,
                    "url": stored_url,
                    "path": "",
                    "metadata_json": json.dumps(
                        {
                            "browser": source.browser,
                            "profile": source.profile,
                            "history_path": str(source.path),
                            "domain": domain,
                            "query_redacted": strip_url_query,
                            "title_redacted": redact_title,
                        },
                        ensure_ascii=False,
                    ),
                    "dedupe_key": _dedupe_key(source, visit["event_time"], stored_url),
                }
            )

    if execute:
        stats.imported = upsert_activity_events(db_path, all_events)
        imported_at = datetime.now(timezone.utc).timestamp()
        for source_key, latest_event_time in latest_event_by_source.items():
            upsert_activity_import_state(
                db_path,
                source=source_key,
                last_imported_at=imported_at,
                last_event_time=latest_event_time,
            )
        if rebuild_sessions and actual_start_ts <= actual_end_ts:
            window_start = max(start_ts, actual_start_ts - (session_gap_minutes * 60))
            window_end = min(end_ts, actual_end_ts + (session_gap_minutes * 60))
            stats.sessions_rebuilt, stats.session_rows_changed = rebuild_browser_activity_sessions(
                db_path,
                start_ts=window_start,
                end_ts=window_end,
                gap_minutes=session_gap_minutes,
            )
    return stats


def rebuild_browser_activity_sessions(
    db_path: Path,
    *,
    start_ts: float,
    end_ts: float,
    gap_minutes: int = 30,
) -> tuple[int, int]:
    events = list(
        reversed(
            query_activity_events_in_range(
                db_path,
                start_ts=start_ts,
                end_ts=end_ts,
                limit=10000,
                source_prefix="browser:",
            )
        )
    )
    sessions = _build_browser_sessions(events, gap_seconds=gap_minutes * 60)
    delete_activity_sessions_in_range(
        db_path,
        start_ts=start_ts,
        end_ts=end_ts,
        source_prefix="browser:",
    )
    changed = upsert_activity_sessions(db_path, sessions)
    return len(sessions), changed


def _domain_matches_any(domain: str, patterns: list[str]) -> bool:
    return any(domain == pattern or domain.endswith(f".{pattern}") for pattern in patterns)


def _source_key(source: BrowserHistorySource) -> str:
    return f"browser:{source.browser}:{source.profile}"


def _strip_query_and_fragment(url: str) -> str:
    parsed = urlsplit(url)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def _dedupe_key(source: BrowserHistorySource, event_time: float, url: str) -> str:
    raw = f"{source.browser}\0{source.profile}\0{event_time:.6f}\0{url}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _session_dedupe_key(source: str, start_time: float, end_time: float, primary_domain: str) -> str:
    raw = f"{source}\0{start_time:.6f}\0{end_time:.6f}\0{primary_domain}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _metadata_domain(row: sqlite3.Row) -> str:
    try:
        metadata = json.loads(row["metadata_json"] or "{}")
    except json.JSONDecodeError:
        return ""
    return str(metadata.get("domain", ""))


def _build_browser_sessions(rows: list[sqlite3.Row], *, gap_seconds: int) -> list[dict]:
    sessions: list[dict] = []
    current: list[sqlite3.Row] = []

    def flush() -> None:
        if not current:
            return
        start_time = float(current[0]["event_time"])
        end_time = float(current[-1]["event_time"])
        domains: dict[str, int] = {}
        titles: list[str] = []
        urls: list[str] = []
        for row in current:
            domain = _metadata_domain(row)
            if domain:
                domains[domain] = domains.get(domain, 0) + 1
            title = row["title"] or ""
            url = row["url"] or ""
            if title and title not in titles:
                titles.append(title)
            if url and url not in urls:
                urls.append(url)
        primary_domain = max(domains, key=domains.get) if domains else ""
        title = primary_domain or (titles[0] if titles else "browser activity")
        summary_parts = []
        if primary_domain:
            summary_parts.append(f"{primary_domain} を中心に閲覧")
        if titles:
            summary_parts.append(" / ".join(titles[:3]))
        summary = " - ".join(summary_parts) if summary_parts else title
        source = str(current[0]["source"])
        sessions.append(
            {
                "source": source,
                "session_type": "browser",
                "start_time": start_time,
                "end_time": end_time,
                "title": title,
                "summary": summary,
                "primary_domain": primary_domain,
                "event_count": len(current),
                "metadata_json": json.dumps(
                    {
                        "domains": domains,
                        "sample_titles": titles[:10],
                        "sample_urls": urls[:10],
                    },
                    ensure_ascii=False,
                ),
                "dedupe_key": _session_dedupe_key(source, start_time, end_time, primary_domain),
            }
        )
        current.clear()

    for row in rows:
        if not current:
            current.append(row)
            continue
        previous = current[-1]
        same_source = row["source"] == previous["source"]
        close_enough = float(row["event_time"]) - float(previous["event_time"]) <= gap_seconds
        if same_source and close_enough:
            current.append(row)
        else:
            flush()
            current.append(row)
    flush()
    return sessions


def _read_source_visits(
    source: BrowserHistorySource,
    start_ts: float,
    end_ts: float,
    limit: int,
) -> list[dict]:
    with tempfile.NamedTemporaryFile(prefix="harumi-browser-history-", suffix=".sqlite") as tmp:
        shutil.copy2(source.path, tmp.name)
        if source.kind == "firefox":
            return _read_firefox_visits(Path(tmp.name), start_ts, end_ts, limit)
        return _read_chromium_visits(Path(tmp.name), start_ts, end_ts, limit)


def _read_chromium_visits(path: Path, start_ts: float, end_ts: float, limit: int) -> list[dict]:
    start_chrome = int((start_ts + CHROME_EPOCH_OFFSET_SECONDS) * 1_000_000)
    end_chrome = int((end_ts + CHROME_EPOCH_OFFSET_SECONDS) * 1_000_000)
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            """
            SELECT urls.url, COALESCE(urls.title, '') AS title, visits.visit_time
            FROM visits
            JOIN urls ON urls.id = visits.url
            WHERE visits.visit_time >= ? AND visits.visit_time < ?
            ORDER BY visits.visit_time DESC
            LIMIT ?
            """,
            (start_chrome, end_chrome, limit),
        ).fetchall()
    return [
        {
            "url": row["url"],
            "title": row["title"],
            "event_time": (int(row["visit_time"]) / 1_000_000) - CHROME_EPOCH_OFFSET_SECONDS,
        }
        for row in rows
    ]


def _read_firefox_visits(path: Path, start_ts: float, end_ts: float, limit: int) -> list[dict]:
    start_firefox = int(start_ts * 1_000_000)
    end_firefox = int(end_ts * 1_000_000)
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            """
            SELECT moz_places.url, COALESCE(moz_places.title, '') AS title, moz_historyvisits.visit_date
            FROM moz_historyvisits
            JOIN moz_places ON moz_places.id = moz_historyvisits.place_id
            WHERE moz_historyvisits.visit_date >= ? AND moz_historyvisits.visit_date < ?
            ORDER BY moz_historyvisits.visit_date DESC
            LIMIT ?
            """,
            (start_firefox, end_firefox, limit),
        ).fetchall()
    return [
        {
            "url": row["url"],
            "title": row["title"],
            "event_time": int(row["visit_date"]) / 1_000_000,
        }
        for row in rows
        if row["visit_date"] is not None
    ]
