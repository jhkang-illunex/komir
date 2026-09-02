# -*- coding: utf-8 -*-
"""`ai_cfg.cfg_prompt`(PostgreSQL, PG_DSN)를 만들고 프롬프트·페이지 정책·출력
계약을 채운다 — `prompt_store.py`가 런타임에 읽는 그 테이블(`data_lake/db/
schema_ai_cfg.sql` 참고 — `public`은 타 팀 소유라 안 쓰고, `mineral_risk`도
다른 용도로 이미 쓰이고 있어 전용 스키마 `ai_cfg`를 새로 뒀다).

**2026-08-26 실제 프롬프트로 교체**: 발주처가 제공한 `income_data/komis/`
자료(KOMIS 8개 페이지 덤프 JSON + 템플릿 PDF 2종)를 근거로 문구를 다시 썼다.

**2026-08-27 단일 소스화 + 컬럼 확장**: 프롬프트 본문은 `prompts.py::PROMPTS`가
단일 소유하고(skeptic 감사 SC-004), 페이지 정책(이름·정의·작성 제약·정책버전)과
출력 계약(섹션별 문장수 범위·문장당 근거 수)도 `prompts.py::code_page_config()`
에서 그대로 가져와 `page_name`/`page_definition`/`analysis_constraints`/
`policy_version`/`output_contract` 컬럼에 심는다(프롬프트 DB화 2단계). 이
파일은 "코드 기본값을 DB에 옮겨 적는" 일만 하며, 운영 중 문구·범위를 바꾸고
싶으면 DB 행을 UPDATE하고 `POST /admin/prompts/reload`를 호출한다.

멱등 실행: `ON CONFLICT (prompt_key) DO UPDATE`라 몇 번을 다시 돌려도 중복
행이 안 생기고, 최신 실행분으로 덮어쓴다(운영 중 손으로 고친 DB 값도 코드
기본값으로 되돌아간다 — 재시드는 그 뜻임을 알고 실행할 것). 스키마(컬럼
추가 포함)는 `apply_schema_pg`로 먼저 적용된다.

실행:
    cd komir/inhouse/services/report_gen
    python -m app.analysis.seed_prompts
(PG_DSN은 `inhouse/.env`에서 읽는다 — services/shared/config.py 참고)
검증: `python scripts/verify_prompt_db.py`(컬럼 존재·라운드트립·DB 반영 확인).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from .._bootstrap import ensure_shared_on_path

ensure_shared_on_path()

from shared.db import apply_schema_pg, execute_pg  # noqa: E402

from .prompt_store import SCHEMA_SQL  # noqa: E402
from .prompts import PROMPTS, code_page_config  # noqa: E402

_UPSERT_SQL = """
INSERT INTO ai_cfg.cfg_prompt
  (prompt_key, content, description, updated_at,
   page_name, page_definition, analysis_constraints, policy_version, output_contract)
VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s::jsonb)
ON CONFLICT (prompt_key) DO UPDATE SET
  content = EXCLUDED.content,
  description = EXCLUDED.description,
  updated_at = EXCLUDED.updated_at,
  page_name = EXCLUDED.page_name,
  page_definition = EXCLUDED.page_definition,
  analysis_constraints = EXCLUDED.analysis_constraints,
  policy_version = EXCLUDED.policy_version,
  output_contract = EXCLUDED.output_contract
"""

DESCRIPTION = "발주처 260826 KOMIS 템플릿 기반 v1 + 페이지 정책·출력 계약 컬럼(260827 DB화 2단계)"


def seed_rows() -> list[tuple]:
    """DB에 넣을 행 튜플 목록(코드 기본값 그대로) — 검증 스크립트도 이걸 대조한다."""

    now = datetime.now(timezone.utc).replace(microsecond=0, tzinfo=None)
    rows: list[tuple] = []
    for key, content in PROMPTS.items():
        if key == "summary_common":
            rows.append((key, content, DESCRIPTION, now, None, None, None, None, None))
            continue
        cfg = code_page_config(key)
        rows.append(
            (
                key,
                content,
                DESCRIPTION,
                now,
                cfg.name,
                cfg.definition,
                json.dumps(list(cfg.analysis_constraints), ensure_ascii=False),
                cfg.policy_version,
                json.dumps(cfg.output_contract_json(), ensure_ascii=False),
            )
        )
    return rows


#: 2026-08-27 price page_id 분리로 더 이상 `PROMPTS`에 없는 옛 prompt_key —
#: upsert는 `PROMPTS`에 있는 키만 건드리므로 재시드해도 저절로 없어지지 않는다.
#: 여기서 명시적으로 지운다(DELETE는 없는 행에 실행해도 안전, 몇 번을 다시
#: 돌려도 no-op).
RETIRED_KEYS = ("price",)


_BACKUP_SQL = """
INSERT INTO ai_cfg.cfg_prompt_backup
  (backup_at, prompt_key, content, description, updated_at,
   page_name, page_definition, analysis_constraints, policy_version, output_contract)
SELECT now(), prompt_key, content, description, updated_at,
       page_name, page_definition, analysis_constraints, policy_version, output_contract
FROM ai_cfg.cfg_prompt
"""


def main() -> None:
    n_stmt = apply_schema_pg(str(SCHEMA_SQL))
    print(f"{SCHEMA_SQL.name} 적용: {n_stmt}개 statement (ai_cfg 스키마·cfg_prompt 테이블·컬럼 포함, 이미 있으면 no-op)")
    # 2026-09-02 skeptic 2차 감사 PA-002: upsert가 운영자 편집을 무경고로
    # 덮어쓰므로, 덮기 전에 현재 행 전체를 백업 테이블에 스냅샷으로 남긴다
    # (테이블이 아직 비어 있는 최초 실행이어도 SELECT 0행 INSERT라 안전).
    execute_pg(_BACKUP_SQL)
    print("cfg_prompt → cfg_prompt_backup 스냅샷 저장 완료(재시드 전 백업)")
    rows = seed_rows()
    for row in rows:
        execute_pg(_UPSERT_SQL, row)
    print(f"ai_cfg.cfg_prompt에 {len(rows)}행 upsert 완료: {sorted(PROMPTS)}")
    for key in RETIRED_KEYS:
        execute_pg("DELETE FROM ai_cfg.cfg_prompt WHERE prompt_key = %s", (key,))
    print(f"퇴역 prompt_key 정리: {list(RETIRED_KEYS)}")


if __name__ == "__main__":
    main()
