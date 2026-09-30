"""Application-owned semantic conversation context contracts."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any, Mapping, Protocol

from .pipe_runtime import ExecutionResult, Pipe, TypedResult
from .semantic_ir import SemanticProgram


@dataclass(frozen=True, slots=True)
class UserUtterance:
    text: str
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(frozen=True, slots=True)
class Turn:
    turn_id: str
    session_id: str
    utterance: UserUtterance
    semantic_program: SemanticProgram | None = None
    pipe_id: str | None = None
    pipe: Pipe | None = None
    result: ExecutionResult | None = None
    bindings: Mapping[str, TypedResult] = field(default_factory=dict)
    evidence: tuple[Any, ...] = ()
    rendered_response: Mapping[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class ConversationContext:
    session_id: str
    turns: tuple[Turn, ...] = ()

    @property
    def latest(self) -> Turn | None:
        return self.turns[-1] if self.turns else None

    def result(self, turn_id: str | None = None) -> ExecutionResult | None:
        turn = self.latest if turn_id is None else next((item for item in self.turns if item.turn_id == turn_id), None)
        return turn.result if turn else None


class HistoryStore(Protocol):
    async def create_session(self, session_id: str) -> None: ...

    async def append_turn(self, turn: Turn) -> None: ...

    async def get_context(self, session_id: str, limit: int = 8) -> ConversationContext: ...

    async def save_program(self, session_id: str, turn_id: str, program: SemanticProgram) -> None: ...

    async def save_result(self, session_id: str, turn_id: str, result: ExecutionResult) -> None: ...

    async def get_binding(self, session_id: str, turn_id: str, step_id: str) -> TypedResult | None: ...

    async def save_pipe(self, session_id: str, turn_id: str, pipe: Pipe) -> None: ...

    async def save_evidence(self, session_id: str, turn_id: str, evidence: tuple[Any, ...]) -> None: ...


class InMemoryHistoryStore:
    """Deterministic test/local implementation; no production DB assumption."""

    def __init__(self) -> None:
        self._sessions: dict[str, list[Turn]] = {}

    async def create_session(self, session_id: str) -> None:
        self._sessions.setdefault(session_id, [])

    async def append_turn(self, turn: Turn) -> None:
        self._sessions.setdefault(turn.session_id, []).append(turn)

    async def get_context(self, session_id: str, limit: int = 8) -> ConversationContext:
        return ConversationContext(session_id, tuple(self._sessions.get(session_id, [])[-limit:]))

    async def save_program(self, session_id: str, turn_id: str, program: SemanticProgram) -> None:
        turns = self._sessions.setdefault(session_id, [])
        for index, turn in enumerate(turns):
            if turn.turn_id == turn_id:
                turns[index] = replace(turn, semantic_program=program)
                return
        raise KeyError(turn_id)

    async def save_result(self, session_id: str, turn_id: str, result: ExecutionResult) -> None:
        turns = self._sessions.setdefault(session_id, [])
        for index, turn in enumerate(turns):
            if turn.turn_id == turn_id:
                turns[index] = replace(turn, result=result, bindings=result.results)
                return
        raise KeyError(turn_id)

    async def get_binding(self, session_id: str, turn_id: str, step_id: str) -> TypedResult | None:
        turns = self._sessions.get(session_id, [])
        turn = next((item for item in turns if item.turn_id == turn_id), None)
        return turn.bindings.get(step_id) if turn else None

    async def save_pipe(self, session_id: str, turn_id: str, pipe: Pipe) -> None:
        turns = self._sessions.setdefault(session_id, [])
        for index, turn in enumerate(turns):
            if turn.turn_id == turn_id:
                turns[index] = replace(turn, pipe_id=pipe.pipe_id, pipe=pipe)
                return
        raise KeyError(turn_id)

    async def save_evidence(self, session_id: str, turn_id: str, evidence: tuple[Any, ...]) -> None:
        turns = self._sessions.setdefault(session_id, [])
        for index, turn in enumerate(turns):
            if turn.turn_id == turn_id:
                turns[index] = replace(turn, evidence=evidence)
                return
        raise KeyError(turn_id)
