# -*- coding: utf-8 -*-
"""SSE-Starlette의 이벤트별 context 전환에서도 root trace를 정상 종료한다."""
from __future__ import annotations

import sys
import unittest
from contextlib import contextmanager
from contextvars import ContextVar, copy_context
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rag_chat.app.routers import chat  # noqa: E402


class ChatTraceContextTest(unittest.TestCase):
    def test_trace_is_entered_and_exited_in_one_context_across_sse_events(self):
        active = ContextVar("trace_active", default=False)

        @contextmanager
        def fake_chat_trace(**_kwargs):
            token = active.set(True)
            try:
                yield object()
            finally:
                active.reset(token)

        request = chat.ChatRequest(user_id="u-1", message="질문", mode="document")
        events = iter((
            {"event": "status", "data": "{}"},
            {"event": "done", "data": '{"done": true}'},
        ))
        with patch.object(chat.session_store, "get_or_create_session", return_value="s-1"), \
             patch.object(chat, "_run_chat_session", return_value=events), \
             patch.object(chat, "chat_trace", fake_chat_trace), \
             patch.object(chat, "update_observation"):
            stream = chat._run_chat(request, "public")
            first_context = copy_context()
            second_context = copy_context()
            self.assertEqual(first_context.run(next, stream)["event"], "status")
            self.assertEqual(second_context.run(next, stream)["event"], "done")
            with self.assertRaises(StopIteration):
                copy_context().run(next, stream)
        self.assertFalse(active.get())


if __name__ == "__main__":
    unittest.main()
