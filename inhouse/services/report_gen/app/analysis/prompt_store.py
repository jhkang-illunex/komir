# -*- coding: utf-8 -*-
"""분석요약 LLM 프롬프트 DB 저장소 — 2026-08-26 신설.

`ai_cfg.cfg_prompt`(PostgreSQL, PG_DSN 대상 — `data_lake/db/schema_ai_cfg.sql`)
에서 프롬프트 텍스트를 읽어 프로세스 캐시(`_cache`)에 보관한다. `public`
(ko_*·ai_mnrl_mst 등)은 타 팀 소유라 건드리지 않고, `mineral_risk`도 이미
다른 용도(MSR_DB의 fact_*/out_*/mart_*, PG_DSN의 doc_chunk/pgvector)로 쓰여서
섞지 않는다 — 전용 스키마 `ai_cfg`를 새로 둔다(2026-08-26 사용자 결정,
`schema_ai_cfg.sql` 상단 참고). DuckDB는 더 안 쓴다 — 이 테이블은 PostgreSQL
전용이고 MSR_DB(duckdb/postgres 양쪽 다 대응하는 범용 대상)를 거치지 않는다.

`reload()`는 `main.py`의 lifespan이 기동 시 1회 호출하고, 이후엔 `POST
/admin/prompts/reload`가 호출될 때만 다시 부른다 — `get_prompt()` 자체는 DB를
조회하지 않고 캐시만 읽는다(요구사항: "서버 재시동 혹은 프롬프트 리로딩이
콜 되면" DB를 다시 읽는다, 매 호출마다 읽는 게 아니다). 캐시 교체는 새 dict를
만들어 모듈 전역을 한 번에 가리키게 하는 방식이라(CPython에서 이름 재바인딩은
원자적) — 교체 도중에도 동시 요청이 절반만 바뀐 캐시를 보는 일이 없고, 교체
이후 시작되는 보고서 생성부터 새 프롬프트를 쓴다.

DB에 해당 `prompt_key` 행이 없거나(테이블은 있는데 아직 안 채움) 조회 자체가
실패하면(테이블·스키마 미생성·PG_DSN 미설정·DB 접속 불가 등) `prompts.py`의
하드코드 값으로 폴백한다 — 그래서 `get_prompt()`는 항상 `default`를 요구한다."""
from __future__ import annotations

import logging

from .._bootstrap import ensure_shared_on_path

ensure_shared_on_path()

from shared.db import read_sql_pg  # noqa: E402

_log = logging.getLogger(__name__)

_cache: dict[str, str] = {}


def _fetch_all() -> dict[str, str]:
    frame = read_sql_pg("SELECT prompt_key, content FROM ai_cfg.cfg_prompt")
    return {str(row["prompt_key"]): str(row["content"]) for row in frame.to_dict("records")}


def reload() -> int:
    """`cfg_prompt`를 다시 읽어 캐시를 통째로 교체한다. 반환값은 로드된 행 수.

    조회가 실패해도 예외를 올리지 않는다 — 기동 시점에 DB가 잠깐 안 뜬 경우
    등으로 report_gen 자체가 죽으면 안 된다(기존 캐시 또는 빈 캐시→하드코드
    기본값 폴백을 유지한 채 계속 뜬다)."""

    global _cache
    try:
        fresh = _fetch_all()
    except Exception:  # noqa: BLE001 — DB 미기동·테이블 미생성 등 원인 다양
        _log.exception("cfg_prompt 재조회 실패 — 기존 캐시(또는 하드코드 기본값)를 유지한다")
        return len(_cache)
    _cache = fresh
    return len(_cache)


def get_prompt(prompt_key: str, *, default: str) -> str:
    """`prompt_key`의 캐시된 DB 프롬프트를 돌려준다. 캐시에 없으면 `default`
    (prompts.py 하드코드 값)로 폴백한다. DB를 직접 조회하지 않는다 — 모듈
    docstring의 "reload는 기동·수동 리로드 때만" 계약 참고."""

    return _cache.get(prompt_key, default)


__all__ = ["get_prompt", "reload"]
