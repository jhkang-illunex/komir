"""Application-owned semantic conversation context contracts."""

from __future__ import annotations

import asyncio
import dataclasses
import json
import os
import re
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any, Mapping, Protocol

from .pipe_runtime import ExecutionResult, Pipe, TypedResult
from .semantic_ir import SemanticProgram


HISTORY_MIGRATION_COMPONENT = "multihop_history"
HISTORY_MIGRATION_VERSION = 1


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

    async def cleanup_expired(self) -> int: ...


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

    async def cleanup_expired(self) -> int:
        return 0


def _json_default(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if dataclasses.is_dataclass(value):
        return dataclasses.asdict(value)
    return str(value)


def _json_dump(value: Any) -> str | None:
    return None if value is None else json.dumps(value, ensure_ascii=False, default=_json_default, separators=(",", ":"))


def _json_load(value: Any) -> Any:
    if value is None or isinstance(value, (dict, list, tuple)):
        return value
    return json.loads(value)


def _typed_to_dict(result: TypedResult) -> dict[str, Any]:
    return {
        "result_type": result.result_type.value,
        "value": result.value,
        "status": result.status.value,
        "entity": list(result.entity),
        "metric": result.metric,
        "period": result.period,
        "unit": result.unit,
        "source": list(result.source),
        "evidence": list(result.evidence),
        "provenance": list(result.provenance),
        "confidence": result.confidence,
        "sufficient": result.sufficient,
        "upstream_step_ids": list(result.upstream_step_ids),
        "warnings": list(result.warnings),
        "failure_reason": result.failure_reason,
    }


def _typed_from_dict(payload: Mapping[str, Any]) -> TypedResult:
    from .pipe_runtime import ResultStatus
    from .semantic_ir import ValueType

    try:
        result_type = ValueType(str(payload.get("result_type", ValueType.UNKNOWN.value)))
    except ValueError:
        result_type = ValueType.UNKNOWN
    try:
        status = ResultStatus(str(payload.get("status", ResultStatus.SUCCESS.value)))
    except ValueError:
        status = ResultStatus.FAILED
    return TypedResult(
        result_type=result_type,
        value=payload.get("value"),
        status=status,
        entity=tuple(str(item) for item in payload.get("entity", ())),
        metric=payload.get("metric"),
        period=payload.get("period"),
        unit=payload.get("unit"),
        source=tuple(str(item) for item in payload.get("source", ())),
        evidence=tuple(payload.get("evidence", ())),
        provenance=tuple(str(item) for item in payload.get("provenance", ())),
        confidence=payload.get("confidence"),
        sufficient=bool(payload.get("sufficient", True)),
        upstream_step_ids=tuple(str(item) for item in payload.get("upstream_step_ids", ())),
        warnings=tuple(str(item) for item in payload.get("warnings", ())),
        failure_reason=payload.get("failure_reason"),
    )


def _execution_to_dict(result: ExecutionResult) -> dict[str, Any]:
    return {
        "pipe_id": result.pipe_id,
        "status": result.status.value,
        "results": {key: _typed_to_dict(value) for key, value in result.results.items()},
        "failure_reason": result.failure_reason,
    }


def _execution_from_dict(payload: Mapping[str, Any]) -> ExecutionResult:
    from .pipe_runtime import ExecutionResult, PipeEvent, ResultStatus

    try:
        status = ResultStatus(str(payload.get("status", ResultStatus.FAILED.value)))
    except ValueError:
        status = ResultStatus.FAILED
    results = {str(key): _typed_from_dict(value) for key, value in (payload.get("results") or {}).items()}
    return ExecutionResult(
        pipe_id=str(payload.get("pipe_id", "persisted")),
        status=status,
        results=results,
        events=tuple(),
        failure_reason=payload.get("failure_reason"),
    )


class PostgresHistoryStore:
    """Persistent semantic history adapter backed by an application-owned table.

    Schema creation is explicit via :meth:`ensure_schema`; constructing the
    store never mutates a database. Pipe steps are stored as an inspectable
    summary because executable Step instances are process-local objects.
    """

    _IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

    def __init__(
        self,
        dsn: str,
        *,
        schema: str = "ai_chatbot",
        ttl_days: int = 30,
        connection_factory: Any | None = None,
    ) -> None:
        if not dsn:
            raise ValueError("PostgresHistoryStore requires a DSN")
        if not self._IDENTIFIER.fullmatch(schema):
            raise ValueError("invalid history schema identifier")
        if ttl_days <= 0:
            raise ValueError("ttl_days must be positive")
        self.dsn = dsn.replace("postgresql+psycopg2://", "postgresql://", 1)
        self.schema = schema
        self.ttl_days = ttl_days
        self._connection_factory = connection_factory or self._default_connection

    def _default_connection(self):
        import psycopg2

        return psycopg2.connect(self.dsn)

    @property
    def _table(self) -> str:
        return f'"{self.schema}"."multihop_semantic_turn"'

    async def _call(self, function, *args):
        return await asyncio.to_thread(function, *args)

    def _ensure_schema_sync(self) -> None:
        con = self._connection_factory()
        try:
            with con.cursor() as cur:
                cur.execute(f'CREATE SCHEMA IF NOT EXISTS "{self.schema}"')
                cur.execute(f"""
                    CREATE TABLE IF NOT EXISTS "{self.schema}"."schema_migration" (
                        component VARCHAR(128) PRIMARY KEY,
                        version INTEGER NOT NULL,
                        applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                cur.execute(f"""
                    CREATE TABLE IF NOT EXISTS {self._table} (
                        session_id VARCHAR(128) NOT NULL,
                        turn_id VARCHAR(128) NOT NULL,
                        utterance TEXT NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL,
                        program_json JSONB,
                        pipe_id VARCHAR(128),
                        pipe_summary_json JSONB,
                        result_json JSONB,
                        evidence_json JSONB,
                        expires_at TIMESTAMPTZ NOT NULL,
                        PRIMARY KEY (session_id, turn_id)
                    )
                """)
                cur.execute(f"CREATE INDEX IF NOT EXISTS idx_multihop_history_expiry ON {self._table} (expires_at)")
                cur.execute(f"CREATE INDEX IF NOT EXISTS idx_multihop_history_session ON {self._table} (session_id, created_at DESC)")
                cur.execute(
                    f"""INSERT INTO "{self.schema}"."schema_migration" (component, version)
                    VALUES (%s, %s)
                    ON CONFLICT (component) DO UPDATE SET version=EXCLUDED.version,
                    applied_at=CURRENT_TIMESTAMP""",
                    (HISTORY_MIGRATION_COMPONENT, HISTORY_MIGRATION_VERSION),
                )
            con.commit()
        finally:
            con.close()

    async def ensure_schema(self) -> None:
        await self._call(self._ensure_schema_sync)

    @staticmethod
    def _pipe_summary(pipe: Pipe) -> dict[str, Any]:
        return {
            "pipe_id": pipe.pipe_id,
            "steps": [
                {
                    "step_id": step.step_id,
                    "operation": step.operation,
                    "dependencies": list(step.dependencies),
                    "bindings": {
                        key: {
                            "source_step_id": binding.source_step_id,
                            "selector": binding.selector,
                            "selector_value": binding.selector_value,
                        }
                        for key, binding in step.bindings.items()
                    },
                    "timeout_seconds": step.timeout_seconds,
                    "max_retries": step.max_retries,
                }
                for step in pipe.steps
            ],
        }

    def _append_turn_sync(self, turn: Turn) -> None:
        created_at = turn.utterance.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        expires_at = created_at + timedelta(days=self.ttl_days)
        result = _execution_dump(turn.result)
        con = self._connection_factory()
        try:
            with con.cursor() as cur:
                cur.execute(f"""
                    INSERT INTO {self._table}
                    (session_id, turn_id, utterance, created_at, program_json, pipe_id,
                     pipe_summary_json, result_json, evidence_json, expires_at)
                    VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s)
                    ON CONFLICT (session_id, turn_id) DO UPDATE SET
                      utterance=EXCLUDED.utterance, created_at=EXCLUDED.created_at,
                      program_json=EXCLUDED.program_json, pipe_id=EXCLUDED.pipe_id,
                      pipe_summary_json=EXCLUDED.pipe_summary_json, result_json=EXCLUDED.result_json,
                      evidence_json=EXCLUDED.evidence_json, expires_at=EXCLUDED.expires_at
                """, (
                    turn.session_id, turn.turn_id, turn.utterance.text, created_at,
                    _json_dump(turn.semantic_program.to_dict() if turn.semantic_program else None),
                    turn.pipe_id,
                    _json_dump(self._pipe_summary(turn.pipe) if turn.pipe else None),
                    _json_dump(result), _json_dump(turn.evidence), expires_at,
                ))
            con.commit()
        finally:
            con.close()

    async def append_turn(self, turn: Turn) -> None:
        await self._call(self._append_turn_sync, turn)

    def _rows_sync(self, session_id: str, limit: int) -> list[tuple[Any, ...]]:
        con = self._connection_factory()
        try:
            with con.cursor() as cur:
                cur.execute(f"""
                    SELECT turn_id, utterance, created_at, program_json, pipe_id,
                           result_json, evidence_json
                    FROM {self._table}
                    WHERE session_id = %s AND expires_at > CURRENT_TIMESTAMP
                    ORDER BY created_at DESC, turn_id DESC
                    LIMIT %s
                """, (session_id, limit))
                return list(cur.fetchall())
        finally:
            con.close()

    @staticmethod
    def _turn_from_row(session_id: str, row: tuple[Any, ...]) -> Turn:
        from .semantic_ir import SemanticProgram

        turn_id, utterance, created_at, program_json, pipe_id, result_json, evidence_json = row
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        program = None
        if program_json:
            try:
                program = SemanticProgram.from_dict(_json_load(program_json))
            except ValueError:
                program = None
        result = _execution_from_dict(_json_load(result_json)) if result_json else None
        evidence = tuple(_json_load(evidence_json) or ())
        return Turn(
            turn_id=str(turn_id),
            session_id=session_id,
            utterance=UserUtterance(str(utterance), created_at),
            semantic_program=program,
            pipe_id=pipe_id,
            result=result,
            bindings=result.results if result else {},
            evidence=evidence,
        )

    async def create_session(self, session_id: str) -> None:
        # Session identity is represented by its durable turn rows. This avoids
        # changing the existing chat_session schema or owning user metadata.
        return None

    async def get_context(self, session_id: str, limit: int = 8) -> ConversationContext:
        rows = await self._call(self._rows_sync, session_id, max(1, min(limit, 8)))
        return ConversationContext(session_id, tuple(self._turn_from_row(session_id, row) for row in reversed(rows)))

    def _update_json_sync(self, session_id: str, turn_id: str, column: str, value: Any) -> None:
        if column not in {"program_json", "result_json", "evidence_json", "pipe_summary_json"}:
            raise ValueError("unsupported history column")
        con = self._connection_factory()
        try:
            with con.cursor() as cur:
                cast = "::jsonb" if column.endswith("json") else ""
                cur.execute(f"UPDATE {self._table} SET {column}=%s{cast} WHERE session_id=%s AND turn_id=%s", (_json_dump(value), session_id, turn_id))
                if cur.rowcount == 0:
                    raise KeyError(turn_id)
            con.commit()
        finally:
            con.close()

    async def save_program(self, session_id: str, turn_id: str, program: SemanticProgram) -> None:
        await self._call(self._update_json_sync, session_id, turn_id, "program_json", program.to_dict())

    async def save_result(self, session_id: str, turn_id: str, result: ExecutionResult) -> None:
        await self._call(self._update_json_sync, session_id, turn_id, "result_json", _execution_dump(result))

    async def get_binding(self, session_id: str, turn_id: str, step_id: str) -> TypedResult | None:
        context = await self.get_context(session_id, limit=8)
        turn = next((item for item in context.turns if item.turn_id == turn_id), None)
        return turn.bindings.get(step_id) if turn else None

    async def save_pipe(self, session_id: str, turn_id: str, pipe: Pipe) -> None:
        await self._call(self._update_json_sync, session_id, turn_id, "pipe_summary_json", self._pipe_summary(pipe))

    async def save_evidence(self, session_id: str, turn_id: str, evidence: tuple[Any, ...]) -> None:
        await self._call(self._update_json_sync, session_id, turn_id, "evidence_json", evidence)

    def _cleanup_sync(self) -> int:
        con = self._connection_factory()
        try:
            with con.cursor() as cur:
                cur.execute(f"DELETE FROM {self._table} WHERE expires_at <= CURRENT_TIMESTAMP")
                count = cur.rowcount
            con.commit()
            return count
        finally:
            con.close()

    async def cleanup_expired(self) -> int:
        return await self._call(self._cleanup_sync)


def _execution_dump(result: ExecutionResult | None) -> dict[str, Any] | None:
    return _execution_to_dict(result) if result else None
