# -*- coding: utf-8 -*-
"""분석요약 LLM 프롬프트·페이지 정책·출력 계약 DB 저장소 — 2026-08-26 신설,
2026-08-27 컬럼 확장(프롬프트 DB화 2단계).

`ai_cfg.cfg_prompt`(PostgreSQL, PG_DSN 대상 — `data_lake/db/schema_ai_cfg.sql`)
에서 행 전체를 읽어 프로세스 캐시(`_cache`)에 보관한다. `public`
(ko_*·ai_mnrl_mst 등)은 타 팀 소유라 건드리지 않고, `mineral_risk`도 이미
다른 용도(MSR_DB의 fact_*/out_*/mart_*, PG_DSN의 doc_chunk/pgvector)로 쓰여서
섞지 않는다 — 전용 스키마 `ai_cfg`를 새로 둔다(2026-08-26 사용자 결정,
`schema_ai_cfg.sql` 상단 참고). DuckDB는 더 안 쓴다 — 이 테이블은 PostgreSQL
전용이고 MSR_DB(duckdb/postgres 양쪽 다 대응하는 범용 대상)를 거치지 않는다.

**행 구조(2026-08-27)**: `content`(지시문 본문) 외에 `page_name`·
`page_definition`·`analysis_constraints`(JSONB 문자열 배열)·`policy_version`·
`output_contract`(JSONB — `section_sentence_ranges`·`total_sentence_range`·
`max_evidence_ids_per_sentence`)를 함께 읽는다. 이전엔 지시문만 DB였고 나머지는
YAML/dataclass/prompts.py 상수에 흩어져 있었다(전체 지침의 ~15%). 컬럼이 NULL이면
그 값만 코드 기본값(`prompts.py::code_page_config`)으로 폴백한다 — 값 단위 폴백.

**컬럼 자동 추가**: `reload()`가 조회 전에 `information_schema.columns`로 필요한
컬럼이 다 있는지 보고, 하나라도 없으면 `schema_ai_cfg.sql`(ADD COLUMN IF NOT
EXISTS, 멱등)을 적용한다 — 운영 DB에 새 컬럼을 손으로 넣지 않아도 기동/리로드
시점에 맞춰진다. 스키마 적용 실패는 조회 실패와 같이 처리한다(서비스는 뜬다).

`reload()`는 `main.py`의 lifespan이 기동 시 1회 호출하고, 이후엔 `POST
/admin/prompts/reload`가 호출될 때만 다시 부른다 — `get_prompt()`/
`get_page_row()` 자체는 DB를 조회하지 않고 캐시만 읽는다. 캐시 교체는 새 dict를
만들어 모듈 전역을 한 번에 가리키게 하는 방식이라(CPython에서 이름 재바인딩은
원자적) 교체 도중에도 동시 요청이 절반만 바뀐 캐시를 보는 일이 없다.

DB에 해당 `prompt_key` 행이 없거나 조회 자체가 실패하면(테이블·스키마 미생성·
PG_DSN 미설정·DB 접속 불가 등) 코드 기본값으로 폴백한다 — 그래서 `get_prompt()`는
항상 `default`를 요구하고, `get_page_row()`는 `None`을 돌려줄 수 있다."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .._bootstrap import ensure_shared_on_path

ensure_shared_on_path()

from shared.db import apply_schema_pg, read_sql_pg  # noqa: E402

_log = logging.getLogger(__name__)

#: `seed_prompts.py`와 같은 파일 — 컬럼 자동 추가에 쓴다.
SCHEMA_SQL = Path(__file__).resolve().parents[4] / "data_lake" / "db" / "schema_ai_cfg.sql"

#: 이 모듈이 읽는 컬럼 전부 — 하나라도 없으면 스키마를 다시 적용한다.
REQUIRED_COLUMNS = (
    "prompt_key",
    "content",
    "page_name",
    "page_definition",
    "analysis_constraints",
    "policy_version",
    "output_contract",
)


@dataclass(frozen=True, slots=True)
class PromptRow:
    """`cfg_prompt` 한 행. 페이지 정책 컬럼은 NULL이면 None(=코드 기본값 사용)."""

    prompt_key: str
    content: str
    page_name: str | None = None
    page_definition: str | None = None
    analysis_constraints: list[str] | None = None
    policy_version: str | None = None
    output_contract: dict[str, Any] | None = None


_cache: dict[str, PromptRow] = {}


def _as_json(value: Any) -> Any:
    """JSONB 컬럼은 드라이버에 따라 dict/list 또는 문자열로 온다 — 둘 다 받는다."""

    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, float) and value != value:  # pandas NaN
        return None
    if isinstance(value, str):
        return json.loads(value)
    return value


def _as_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, float) and value != value:  # pandas NaN
        return None
    return str(value)


def _existing_columns() -> set[str]:
    frame = read_sql_pg(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = 'ai_cfg' AND table_name = 'cfg_prompt'"
    )
    return {str(row["column_name"]) for row in frame.to_dict("records")}


def ensure_schema() -> list[str]:
    """필요한 컬럼이 빠져 있으면 `schema_ai_cfg.sql`을 적용한다. 반환값은 적용
    전 누락돼 있던 컬럼 목록(없으면 빈 리스트 = no-op)."""

    existing = _existing_columns()
    missing = [name for name in REQUIRED_COLUMNS if name not in existing]
    if missing:
        _log.info("cfg_prompt 컬럼 누락 %s — %s 적용", missing, SCHEMA_SQL.name)
        apply_schema_pg(str(SCHEMA_SQL))
        still_missing = [name for name in REQUIRED_COLUMNS if name not in _existing_columns()]
        if still_missing:
            raise RuntimeError(f"cfg_prompt 스키마 적용 후에도 컬럼이 없다: {still_missing}")
    return missing


def _fetch_all() -> dict[str, PromptRow]:
    frame = read_sql_pg(
        "SELECT prompt_key, content, page_name, page_definition, analysis_constraints, "
        "policy_version, output_contract FROM ai_cfg.cfg_prompt"
    )
    rows: dict[str, PromptRow] = {}
    for row in frame.to_dict("records"):
        key = str(row["prompt_key"])
        rows[key] = PromptRow(
            prompt_key=key,
            content=str(row["content"]),
            page_name=_as_text(row.get("page_name")),
            page_definition=_as_text(row.get("page_definition")),
            analysis_constraints=_json_column(key, "analysis_constraints", row.get("analysis_constraints")),
            policy_version=_as_text(row.get("policy_version")),
            output_contract=_json_column(key, "output_contract", row.get("output_contract")),
        )
    return rows


def _json_column(key: str, column: str, value: Any) -> Any:
    """JSON 컬럼 1개를 해석한다 — 깨진 값은 그 컬럼만 None(코드 기본값)으로 두고
    경고한다(Pass 3 R3-L2: 이전엔 행 하나의 컬럼 하나가 깨지면 reload 전체가
    실패해 모든 프롬프트 갱신이 막혔다)."""

    try:
        return _as_json(value)
    except (ValueError, TypeError):
        _log.warning("cfg_prompt[%s].%s JSON 해석 실패 — 이 컬럼만 코드 기본값 사용: %r", key, column, value)
        return None


def reload() -> int:
    """(컬럼 자동 추가 →) `cfg_prompt`를 다시 읽어 캐시를 통째로 교체한다.
    반환값은 로드된 행 수.

    조회가 실패해도 예외를 올리지 않는다 — 기동 시점에 DB가 잠깐 안 뜬 경우
    등으로 report_gen 자체가 죽으면 안 된다(기존 캐시 또는 빈 캐시→코드
    기본값 폴백을 유지한 채 계속 뜬다)."""

    global _cache
    try:
        ensure_schema()
        fresh = _fetch_all()
    except Exception:  # noqa: BLE001 — DB 미기동·테이블 미생성 등 원인 다양
        _log.exception("cfg_prompt 재조회 실패 — 기존 캐시(또는 코드 기본값)를 유지한다")
        return len(_cache)
    _cache = fresh
    return len(_cache)


def get_prompt(prompt_key: str, *, default: str) -> str:
    """`prompt_key`의 캐시된 DB 지시문을 돌려준다. 캐시에 없으면 `default`
    (prompts.py 하드코드 값)로 폴백한다. DB를 직접 조회하지 않는다."""

    row = _cache.get(prompt_key)
    return row.content if row is not None else default


def get_page_row(page_id: str) -> PromptRow | None:
    """`page_id` 행 전체(페이지 정책·출력 계약 컬럼 포함). 캐시에 없으면 None."""

    return _cache.get(page_id)


def cached_keys() -> list[str]:
    return sorted(_cache)


__all__ = ["PromptRow", "REQUIRED_COLUMNS", "SCHEMA_SQL", "cached_keys", "ensure_schema", "get_page_row", "get_prompt", "reload"]
