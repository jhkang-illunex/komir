# -*- coding: utf-8 -*-
"""ingest 체인의 실패 전파 계약 검사.

    cd inhouse && python -m unittest ingest.tests.test_run_chain
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ingest import run_chain  # noqa: E402


class _Log:
    def __init__(self):
        self.messages: list[str] = []

    def write(self, text: str) -> None:
        self.messages.append(text)

    def close(self) -> None:
        pass


class ChainFailurePropagationTest(unittest.TestCase):
    def test_noncritical_pageindex_failure_marks_chain_failed_and_exits_nonzero(self):
        """후속 단계는 실행해도 PageIndex 실패를 체인 성공으로 숨기면 안 된다."""

        metrics: dict = {}
        captured: list[type[BaseException]] = []

        @contextmanager
        def fake_pipeline_run(*_args, **_kwargs):
            handle = SimpleNamespace(metrics=metrics)
            try:
                yield handle
            except BaseException as exc:
                captured.append(type(exc))
                raise

        def fake_run(*_args, **_kwargs):
            return {
                "pageindex": {"rc": 1, "sec": 0.1},
                "pgvector_index": {"rc": 0, "sec": 0.1},
            }

        with tempfile.TemporaryDirectory() as d:
            paths = SimpleNamespace(logs=Path(d), as_dict=lambda: {"test": True})
            log = _Log()
            steps = [run_chain.Step("pageindex", ("ingest.pageindex.build_pageindex_trees",), critical=False)]
            with patch.object(run_chain, "get_paths", return_value=paths), \
                    patch.object(run_chain, "build_steps", return_value=steps), \
                    patch.object(run_chain, "_Tee", return_value=log), \
                    patch.object(run_chain.ingest_status, "pipeline_run", fake_pipeline_run), \
                    patch.object(run_chain, "run", side_effect=fake_run):
                rc = run_chain.main(["--no-lock"])

        self.assertEqual(rc, 1)
        self.assertEqual(metrics["failed_steps"], ["pageindex"])
        self.assertEqual(captured, [run_chain.ChainStepFailure])
        self.assertIn("ingest 체인 실패", "".join(log.messages))

    def test_failed_steps_ignores_abort_marker(self):
        self.assertEqual(
            run_chain.failed_steps({"pageindex": {"rc": 1}, "aborted_at": "pageindex"}),
            ("pageindex",),
        )


if __name__ == "__main__":
    unittest.main()
