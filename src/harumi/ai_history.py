from __future__ import annotations

import json
import hashlib
import re
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from zoneinfo import ZoneInfo

from harumi.db import (
    get_activity_import_state,
    upsert_activity_events,
    upsert_activity_import_state,
    upsert_activity_sessions,
)


@dataclass
class AiHistoryImportStats:
    conversations_seen: int = 0
    conversations_after_filters: int = 0
    imported_events: int = 0
    sessions_changed: int = 0
    since_last: bool = False


@dataclass(frozen=True)
class AiConversation:
    conversation_id: str
    title: str
    create_time: float
    update_time: float
    user_messages: tuple[str, ...]
    assistant_messages: tuple[str, ...]


ChatGptConversation = AiConversation


def import_chatgpt_history(
    db_path: Path,
    *,
    source_path: Path,
    execute: bool,
    since_last: bool = False,
    limit: int | None = None,
) -> AiHistoryImportStats:
    return import_ai_history(
        db_path,
        provider="chatgpt",
        source_path=source_path,
        execute=execute,
        since_last=since_last,
        limit=limit,
    )


def import_ai_history(
    db_path: Path,
    *,
    provider: str,
    source_path: Path,
    execute: bool,
    since_last: bool = False,
    limit: int | None = None,
) -> AiHistoryImportStats:
    source_key = f"ai:{provider}"
    conversations = read_ai_conversations(provider, source_path)
    stats = AiHistoryImportStats(conversations_seen=len(conversations), since_last=since_last)

    start_after = 0.0
    if since_last:
        state = get_activity_import_state(db_path, source_key)
        if state is not None:
            start_after = float(state["last_event_time"])

    filtered = [conversation for conversation in conversations if conversation.update_time > start_after]
    filtered.sort(key=lambda conversation: conversation.update_time)
    if limit is not None:
        filtered = filtered[:limit]
    stats.conversations_after_filters = len(filtered)

    events = [_conversation_event(provider, source_key, source_path, conversation) for conversation in filtered]
    sessions = [_conversation_session(provider, source_key, conversation) for conversation in filtered]

    if execute:
        stats.imported_events = upsert_activity_events(db_path, events)
        stats.sessions_changed = upsert_activity_sessions(db_path, sessions)
        if filtered:
            upsert_activity_import_state(
                db_path,
                source=source_key,
                last_imported_at=datetime.now(timezone.utc).timestamp(),
                last_event_time=max(conversation.update_time for conversation in filtered),
            )

    return stats


def read_ai_conversations(provider: str, source_path: Path) -> list[AiConversation]:
    if provider == "chatgpt":
        return read_chatgpt_conversations(source_path)
    if provider == "claude":
        return read_claude_conversations(source_path)
    if provider == "gemini":
        return read_gemini_conversations(source_path)
    raise ValueError(f"Unsupported AI history provider: {provider}")


def read_chatgpt_conversations(source_path: Path) -> list[AiConversation]:
    data = _load_chatgpt_export(source_path)
    if not isinstance(data, list):
        raise ValueError("ChatGPT export conversations.json must contain a JSON array.")

    conversations: list[AiConversation] = []
    for index, raw in enumerate(data):
        if not isinstance(raw, dict):
            continue
        conversation = _parse_conversation(raw, fallback_id=f"conversation-{index}")
        if conversation is not None:
            conversations.append(conversation)
    return conversations


def _load_chatgpt_export(source_path: Path):
    if source_path.suffix.lower() == ".zip":
        with zipfile.ZipFile(source_path) as archive:
            try:
                with archive.open("conversations.json") as handle:
                    return json.load(handle)
            except KeyError as exc:
                raise ValueError("ChatGPT export zip does not contain conversations.json.") from exc

    with source_path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def read_claude_conversations(source_path: Path) -> list[AiConversation]:
    data = _load_named_json(source_path, "conversations.json")
    if not isinstance(data, list):
        raise ValueError("Claude export conversations.json must contain a JSON array.")

    conversations: list[AiConversation] = []
    for index, raw in enumerate(data):
        if not isinstance(raw, dict):
            continue
        messages = raw.get("chat_messages")
        if not isinstance(messages, list):
            continue
        user_messages: list[str] = []
        assistant_messages: list[str] = []
        message_times: list[float] = []
        for message in messages:
            if not isinstance(message, dict):
                continue
            text = str(message.get("text") or "").strip()
            if not text:
                text = _claude_content_text(message.get("content"))
            if not text:
                continue
            timestamp = _parse_iso_timestamp(message.get("created_at"))
            if timestamp > 0:
                message_times.append(timestamp)
            sender = str(message.get("sender") or "").lower()
            if sender == "human":
                user_messages.append(text)
            elif sender == "assistant":
                assistant_messages.append(text)
        if not user_messages and not assistant_messages:
            continue
        create_time = _parse_iso_timestamp(raw.get("created_at")) or (min(message_times) if message_times else 0.0)
        update_time = _parse_iso_timestamp(raw.get("updated_at")) or (max(message_times) if message_times else create_time)
        conversations.append(
            AiConversation(
                conversation_id=str(raw.get("uuid") or f"conversation-{index}"),
                title=str(raw.get("name") or (user_messages[0][:80] if user_messages else "Claude conversation")),
                create_time=create_time or update_time,
                update_time=update_time or create_time,
                user_messages=tuple(user_messages),
                assistant_messages=tuple(assistant_messages),
            )
        )
    return conversations


def read_gemini_conversations(source_path: Path) -> list[AiConversation]:
    html = _load_gemini_activity_html(source_path)
    chunks = _extract_activity_chunks(html)
    conversations: list[AiConversation] = []
    for index, chunk in enumerate(chunks):
        plain = _html_to_text(chunk)
        conversation = _parse_gemini_activity(plain)
        if conversation is not None:
            conversations.append(conversation)
    return conversations


def _parse_conversation(raw: dict, *, fallback_id: str) -> AiConversation | None:
    mapping = raw.get("mapping")
    if not isinstance(mapping, dict):
        return None

    user_messages: list[str] = []
    assistant_messages: list[str] = []
    message_times: list[float] = []

    for node in mapping.values():
        if not isinstance(node, dict):
            continue
        message = node.get("message")
        if not isinstance(message, dict):
            continue
        role = ((message.get("author") or {}).get("role") or "").lower()
        text = _message_text(message)
        if not text:
            continue
        created_at = message.get("create_time")
        if isinstance(created_at, int | float):
            message_times.append(float(created_at))
        if role == "user":
            user_messages.append(text)
        elif role == "assistant":
            assistant_messages.append(text)

    if not user_messages and not assistant_messages:
        return None

    create_time = _coerce_timestamp(raw.get("create_time")) or (min(message_times) if message_times else 0.0)
    update_time = _coerce_timestamp(raw.get("update_time")) or (max(message_times) if message_times else create_time)
    if create_time <= 0:
        create_time = update_time
    if update_time <= 0:
        update_time = create_time

    conversation_id = str(raw.get("id") or raw.get("conversation_id") or fallback_id)
    title = str(raw.get("title") or user_messages[0][:80] or "ChatGPT conversation")

    return AiConversation(
        conversation_id=conversation_id,
        title=title,
        create_time=create_time,
        update_time=update_time,
        user_messages=tuple(user_messages),
        assistant_messages=tuple(assistant_messages),
    )


def _message_text(message: dict) -> str:
    content = message.get("content")
    if not isinstance(content, dict):
        return ""
    parts = content.get("parts")
    if not isinstance(parts, list):
        return ""
    text_parts: list[str] = []
    for part in parts:
        if isinstance(part, str):
            text_parts.append(part)
        elif isinstance(part, dict):
            text = part.get("text")
            if isinstance(text, str):
                text_parts.append(text)
    return "\n".join(part.strip() for part in text_parts if part.strip()).strip()


def _claude_content_text(content) -> str:
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for item in content:
        if isinstance(item, dict) and isinstance(item.get("text"), str):
            parts.append(item["text"].strip())
    return "\n".join(part for part in parts if part)


def _coerce_timestamp(value) -> float:
    if isinstance(value, int | float):
        return float(value)
    return 0.0


def _parse_iso_timestamp(value) -> float:
    if not isinstance(value, str) or not value:
        return 0.0
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def _load_named_json(source_path: Path, name: str):
    if source_path.suffix.lower() == ".zip":
        with zipfile.ZipFile(source_path) as archive:
            try:
                with archive.open(name) as handle:
                    return json.load(handle)
            except KeyError as exc:
                raise ValueError(f"Export zip does not contain {name}.") from exc
    with source_path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _load_gemini_activity_html(source_path: Path) -> str:
    if source_path.suffix.lower() == ".zip":
        with zipfile.ZipFile(source_path) as archive:
            candidates = [
                name
                for name in archive.namelist()
                if name.endswith(".html") and ("Gemini" in name or "Gemini アプリ" in name)
            ]
            activity_candidates = [name for name in candidates if "アクティビティ" in name or "Activity" in name]
            if not activity_candidates:
                raise ValueError("Gemini export zip does not contain a Gemini activity HTML file.")
            with archive.open(activity_candidates[0]) as handle:
                return handle.read().decode("utf-8", errors="replace")
    return source_path.read_text(encoding="utf-8", errors="replace")


def _extract_activity_chunks(html: str) -> list[str]:
    matches = list(re.finditer(r'<div class="outer-cell[^"]*"', html))
    chunks: list[str] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(html)
        chunks.append(html[match.start():end])
    return chunks


def _html_to_text(html: str) -> str:
    text = re.sub(r"<br\s*/?>", "\n", html, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _parse_gemini_activity(text: str) -> AiConversation | None:
    marker = "送信したメッセージ:"
    if marker not in text:
        return None
    after_marker = text.split(marker, 1)[1].strip()
    date_match = re.search(r"\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2} JST", after_marker)
    if not date_match:
        return None
    user_text = after_marker[: date_match.start()].strip()
    user_text = re.sub(r"\s*添付ファイル \d+ 件 - .*$", "", user_text).strip()
    timestamp = _parse_gemini_timestamp(date_match.group(0))
    assistant_text = after_marker[date_match.end():].strip()
    service_index = assistant_text.find("サービス:")
    if service_index >= 0:
        assistant_text = assistant_text[:service_index].strip()
    if not user_text and not assistant_text:
        return None
    title = user_text[:80] or "Gemini activity"
    digest = hashlib.sha256(f"{timestamp}\0{user_text}".encode("utf-8")).hexdigest()[:16]
    return AiConversation(
        conversation_id=f"gemini-{digest}",
        title=title,
        create_time=timestamp,
        update_time=timestamp,
        user_messages=(user_text,) if user_text else (),
        assistant_messages=(assistant_text,) if assistant_text else (),
    )


def _parse_gemini_timestamp(value: str) -> float:
    dt = datetime.strptime(value, "%Y/%m/%d %H:%M:%S JST")
    return dt.replace(tzinfo=ZoneInfo("Asia/Tokyo")).timestamp()


def _conversation_event(provider: str, source: str, source_path: Path, conversation: AiConversation) -> dict:
    return {
        "source": source,
        "event_type": "ai_conversation",
        "event_time": conversation.update_time,
        "title": conversation.title,
        "url": "",
        "path": str(source_path),
        "metadata_json": json.dumps(
            {
                "provider": provider,
                "conversation_id": conversation.conversation_id,
                "created_at": conversation.create_time,
                "updated_at": conversation.update_time,
                "user_message_count": len(conversation.user_messages),
                "assistant_message_count": len(conversation.assistant_messages),
                "sample_user_messages": list(conversation.user_messages[:5]),
            },
            ensure_ascii=False,
        ),
        "dedupe_key": _dedupe_key(source, conversation.conversation_id),
    }


def _conversation_session(provider: str, source: str, conversation: AiConversation) -> dict:
    return {
        "source": source,
        "session_type": "ai",
        "start_time": conversation.create_time,
        "end_time": conversation.update_time,
        "title": conversation.title,
        "summary": _conversation_summary(conversation),
        "primary_domain": provider,
        "event_count": len(conversation.user_messages) + len(conversation.assistant_messages),
        "metadata_json": json.dumps(
            {
                "provider": provider,
                "conversation_id": conversation.conversation_id,
                "sample_user_messages": list(conversation.user_messages[:5]),
            },
            ensure_ascii=False,
        ),
        "dedupe_key": _dedupe_key(source, conversation.conversation_id),
    }


def _conversation_summary(conversation: AiConversation) -> str:
    prompts = [message.replace("\n", " ") for message in conversation.user_messages[:3]]
    if not prompts:
        return conversation.title
    return " / ".join(prompt[:120] for prompt in prompts)


def _dedupe_key(source: str, conversation_id: str) -> str:
    raw = f"{source}\0{conversation_id}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
