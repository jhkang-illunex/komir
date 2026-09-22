# -*- coding: utf-8 -*-
"""Langfuse 관측은 선택 기능이며 챗봇 경로를 막으면 안 된다."""
from __future__ import annotations

import sys
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from common import langfuse_tracing as tracing  # noqa: E402


class _Observation:
    def __init__(self, kwargs):
        self.kwargs = kwargs
        self.updates = []

    def update(self, **kwargs):
        self.updates.append(kwargs)


class _ObservationManager:
    def __init__(self, observation):
        self.observation = observation

    def __enter__(self):
        return self.observation

    def __exit__(self, *_args):
        return False


class _Client:
    def __init__(self, events):
        self.events = events
        self.observations = []

    def start_as_current_observation(self, **kwargs):
        self.events.append(("observation", kwargs))
        observation = _Observation(kwargs)
        self.observations.append(observation)
        return _ObservationManager(observation)


class LangfuseTracingTest(unittest.TestCase):
    def setUp(self):
        self.original_client = tracing._client
        self.original_initialized = tracing._client_initialized
        self.original_propagate = tracing.propagate_attributes
        self.events = []
        self.client = _Client(self.events)
        tracing._client = self.client
        tracing._client_initialized = True

    def tearDown(self):
        tracing._client = self.original_client
        tracing._client_initialized = self.original_initialized
        tracing.propagate_attributes = self.original_propagate

    def test_trace_attributes_are_active_before_root_observation(self):
        @contextmanager
        def propagate_attributes(**kwargs):
            self.events.append(("attributes_enter", kwargs))
            try:
                yield
            finally:
                self.events.append(("attributes_exit", kwargs))

        tracing.propagate_attributes = propagate_attributes
        with tracing.chat_trace(user_id="u-1", session_id="s-1", message="질문", profile="public") as root:
            self.assertIsNotNone(root)
            with tracing.llm_generation(
                name="route", model="local", system="system", user="user",
                max_tokens=512, temperature=0, stream=False,
            ) as generation:
                tracing.update_observation(generation, output="{}")

        self.assertEqual(self.events[0][0], "attributes_enter")
        self.assertEqual(self.events[1][0], "observation")
        self.assertEqual(self.events[0][1]["user_id"], "u-1")
        self.assertEqual([item[0] for item in self.events], [
            "attributes_enter", "observation", "observation", "attributes_exit",
        ])
        self.assertEqual(self.client.observations[1].updates, [{"output": "{}"}])

    def test_attribute_context_failure_does_not_block_chat_trace(self):
        class _BrokenAttributes:
            def __enter__(self):
                raise RuntimeError("Langfuse unavailable")

            def __exit__(self, *_args):
                return False

        tracing.propagate_attributes = lambda **_kwargs: _BrokenAttributes()
        with patch.object(tracing, "_logger"):
            with tracing.chat_trace(user_id="u-1", session_id="s-1", message="질문", profile="public") as root:
                self.assertIsNotNone(root)
                self.assertTrue(tracing._chat_trace_active.get())
        self.assertFalse(tracing._chat_trace_active.get())


if __name__ == "__main__":
    unittest.main()
