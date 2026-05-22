from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from harumi.ai_history import (
    import_ai_history,
    import_chatgpt_history,
    read_claude_conversations,
    read_gemini_conversations,
    read_chatgpt_conversations,
)
from harumi.db import (
    get_activity_import_state,
    init_db,
    query_activity_events_in_range,
    query_activity_sessions_in_range,
)


class AiHistoryTests(unittest.TestCase):
    def test_read_chatgpt_conversations_from_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "conversations.json"
            source.write_text(json.dumps([_chatgpt_conversation()]), encoding="utf-8")

            conversations = read_chatgpt_conversations(source)

            self.assertEqual(len(conversations), 1)
            self.assertEqual(conversations[0].conversation_id, "conv-1")
            self.assertEqual(conversations[0].title, "AWS SSO")
            self.assertEqual(conversations[0].user_messages, ("aws sso の設定を調べたい",))

    def test_read_chatgpt_conversations_from_export_zip(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "chatgpt-export.zip"
            with zipfile.ZipFile(source, "w") as archive:
                archive.writestr("conversations.json", json.dumps([_chatgpt_conversation()]))

            conversations = read_chatgpt_conversations(source)

            self.assertEqual(len(conversations), 1)
            self.assertEqual(conversations[0].assistant_messages, ("AWS SSO は Identity Center で設定します。",))

    def test_import_chatgpt_history_stores_activity_event_and_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            source = tmp / "conversations.json"
            source.write_text(json.dumps([_chatgpt_conversation()]), encoding="utf-8")
            db_path = tmp / "harumi.db"
            init_db(db_path)

            dry_stats = import_chatgpt_history(db_path, source_path=source, execute=False)
            self.assertEqual(dry_stats.conversations_after_filters, 1)
            self.assertEqual(query_activity_events_in_range(db_path, start_ts=0, end_ts=2_000_000_000), [])

            stats = import_chatgpt_history(db_path, source_path=source, execute=True)
            events = query_activity_events_in_range(db_path, start_ts=0, end_ts=2_000_000_000)
            sessions = query_activity_sessions_in_range(db_path, start_ts=0, end_ts=2_000_000_000)
            state = get_activity_import_state(db_path, "ai:chatgpt")

            self.assertEqual(stats.imported_events, 1)
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["source"], "ai:chatgpt")
            self.assertEqual(events[0]["event_type"], "ai_conversation")
            self.assertEqual(len(sessions), 1)
            self.assertEqual(sessions[0]["session_type"], "ai")
            self.assertIsNotNone(state)

            second_stats = import_chatgpt_history(db_path, source_path=source, execute=True, since_last=True)
            self.assertEqual(second_stats.conversations_after_filters, 0)
            self.assertEqual(second_stats.imported_events, 0)

    def test_read_claude_conversations_from_export_zip(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "claude-export.zip"
            with zipfile.ZipFile(source, "w") as archive:
                archive.writestr("conversations.json", json.dumps([_claude_conversation()]))

            conversations = read_claude_conversations(source)

            self.assertEqual(len(conversations), 1)
            self.assertEqual(conversations[0].conversation_id, "claude-conv-1")
            self.assertEqual(conversations[0].title, "Claude AWS SSO")
            self.assertEqual(conversations[0].user_messages, ("aws sso を整理して",))

    def test_read_gemini_conversations_from_takeout_html_zip(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "gemini-takeout.zip"
            html = """
            <html><body>
              <div class="outer-cell mdl-cell">
                <div>Gemini アプリ</div>
                <div>送信したメッセージ: aws sso を調べて</div>
                <div>2026/05/21 17:47:55 JST</div>
                <div>Identity Center を確認します。</div>
                <div>サービス: Gemini アプリ</div>
              </div>
            </body></html>
            """
            with zipfile.ZipFile(source, "w") as archive:
                archive.writestr("Takeout/マイ アクティビティ/Gemini アプリ/マイアクティビティ.html", html)

            conversations = read_gemini_conversations(source)

            self.assertEqual(len(conversations), 1)
            self.assertEqual(conversations[0].title, "aws sso を調べて")
            self.assertEqual(conversations[0].assistant_messages, ("Identity Center を確認します。",))

    def test_import_ai_history_supports_claude_provider(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            source = tmp / "claude-export.zip"
            with zipfile.ZipFile(source, "w") as archive:
                archive.writestr("conversations.json", json.dumps([_claude_conversation()]))
            db_path = tmp / "harumi.db"
            init_db(db_path)

            stats = import_ai_history(db_path, provider="claude", source_path=source, execute=True)
            events = query_activity_events_in_range(db_path, start_ts=0, end_ts=2_000_000_000)
            sessions = query_activity_sessions_in_range(db_path, start_ts=0, end_ts=2_000_000_000)

            self.assertEqual(stats.imported_events, 1)
            self.assertEqual(events[0]["source"], "ai:claude")
            self.assertEqual(sessions[0]["primary_domain"], "claude")


def _chatgpt_conversation() -> dict:
    return {
        "id": "conv-1",
        "title": "AWS SSO",
        "create_time": 1775001600.0,
        "update_time": 1775001900.0,
        "mapping": {
            "user-node": {
                "message": {
                    "author": {"role": "user"},
                    "create_time": 1775001600.0,
                    "content": {"content_type": "text", "parts": ["aws sso の設定を調べたい"]},
                }
            },
            "assistant-node": {
                "message": {
                    "author": {"role": "assistant"},
                    "create_time": 1775001700.0,
                    "content": {"content_type": "text", "parts": ["AWS SSO は Identity Center で設定します。"]},
                }
            },
        },
    }


def _claude_conversation() -> dict:
    return {
        "uuid": "claude-conv-1",
        "name": "Claude AWS SSO",
        "created_at": "2026-04-01T00:00:00.000000Z",
        "updated_at": "2026-04-01T00:05:00.000000Z",
        "chat_messages": [
            {
                "uuid": "msg-1",
                "text": "aws sso を整理して",
                "sender": "human",
                "created_at": "2026-04-01T00:00:00.000000Z",
                "content": [{"type": "text", "text": "aws sso を整理して"}],
            },
            {
                "uuid": "msg-2",
                "text": "Identity Center の設定を確認します。",
                "sender": "assistant",
                "created_at": "2026-04-01T00:01:00.000000Z",
                "content": [{"type": "text", "text": "Identity Center の設定を確認します。"}],
            },
        ],
    }


if __name__ == "__main__":
    unittest.main()
