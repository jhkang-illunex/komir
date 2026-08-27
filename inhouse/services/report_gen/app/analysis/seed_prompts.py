# -*- coding: utf-8 -*-
"""`ai_cfg.cfg_prompt`(PostgreSQL, PG_DSN)를 만들고 프롬프트 본문을 채운다 —
`prompt_store.py`가 런타임에 읽는 그 테이블(`data_lake/db/schema_ai_cfg.sql`
참고 — `public`은 타 팀 소유라 안 쓰고, `mineral_risk`도 다른 용도로 이미
쓰이고 있어 전용 스키마 `ai_cfg`를 새로 뒀다).

**2026-08-26 실제 프롬프트로 교체**: 발주처가 제공한 `income_data/komis/`
자료(KOMIS 8개 페이지 덤프 JSON + 템플릿 PDF 2종: `AI 통계분석 요약
답변_광물가격전망지표.pdf`, `AI 통계분석 요약답변_수급지도광물지도.pdf`)를
근거로 문구를 다시 썼다. 최초 커밋(같은 날 앞선 버전)은 `prompts.py`의
하드코드 문구를 그대로 옮겨 심은 "임시 프롬프트"였다 — 지금은 그게 아니다.

**실제 반영 범위(중요, 구조적 제약)**:
- `AnalysisSummaryService.analyze()`(`summary.py`)가 LLM 정제
  (`_refine_with_llm`)를 타는 페이지는 `indicator_market`·`indicator_supply`·
  `indicator_composite`·`map_mineral`·`forecast_price` 5종 + **2026-08-26에
  배선을 추가한 `price`·`map_korea`·`map_global` 3종, 총 8종**이다(9번째
  `prompt_key`인 `summary_common`은 페이지가 아니라 공통 서두). `forecast_price`
  만 참고자료가 없어 문구를 그대로 뒀다. 배선 추가 커밋에서
  `komir_summary.py::calculate_price_summary`의 core_diagnosis 근거 id를
  `"latest_price"`→`"current_state"`로 고쳤다(다른 7종과 규약을 맞춘 버그
  수정 — `summary.py::_validate_llm_summary`가 "core_diagnosis에 current_state가
  있어야 한다"를 페이지 무관 공통 규칙으로 검사하는데, 예전 이름으로는 이
  검사를 항상 통과 못 해 LLM 출력이 매번 규칙기반으로 폴백했을 것이다).
- 각 프롬프트는 `additional_summary.py`/`komir_summary.py`가 실제로 만드는
  `EvidenceClaim`(사실+evidence_id) 범위 안에서만 쓰도록 지시한다 — PDF가
  요구하는 "주요 요인"(가격변동 원인, 투자환경지수 요인 등) 절은 현재 계산
  레이어가 원인을 분해해 근거로 만들지 않으므로 **의도적으로 비웠다**(지어내면
  `_validate_llm_summary`의 숫자·근거 검증에 걸려 규칙기반으로 폴백한다).

멱등 실행: `ON CONFLICT (prompt_key) DO UPDATE`라 몇 번을 다시 돌려도 중복
행이 안 생기고, 최신 실행분으로 덮어쓴다.

실행:
    cd komir/inhouse/services/report_gen
    python -m app.analysis.seed_prompts
(PG_DSN은 `inhouse/.env`에서 읽는다 — services/shared/config.py 참고)

실행 후에는 `POST /admin/prompts/reload`(또는 서버 재시동)를 호출해야
`prompt_store` 캐시가 새 문구로 갱신된다.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from .._bootstrap import ensure_shared_on_path

ensure_shared_on_path()

from shared.db import apply_schema_pg, execute_pg  # noqa: E402

_SCHEMA_SQL = Path(__file__).resolve().parents[4] / "data_lake" / "db" / "schema_ai_cfg.sql"

# 프롬프트 본문은 `prompts.py::PROMPTS`가 단일 소유한다(2026-08-27, skeptic 감사
# SC-004 — 이 파일과 prompts.py 폴백이 따로 놀아 10키 중 9키가 드리프트돼 있었다).
# 여기서는 그걸 그대로 DB에 심기만 한다.
from .prompts import PROMPTS  # noqa: E402

_UPSERT_SQL = """
INSERT INTO ai_cfg.cfg_prompt (prompt_key, content, description, updated_at)
VALUES (%s, %s, %s, %s)
ON CONFLICT (prompt_key) DO UPDATE SET
  content = EXCLUDED.content,
  description = EXCLUDED.description,
  updated_at = EXCLUDED.updated_at
"""


def main() -> None:
    n_stmt = apply_schema_pg(str(_SCHEMA_SQL))
    print(f"{_SCHEMA_SQL.name} 적용: {n_stmt}개 statement (ai_cfg 스키마·cfg_prompt 테이블 포함, 이미 있으면 no-op)")

    now = datetime.now(timezone.utc).replace(microsecond=0, tzinfo=None)
    description = "발주처 260826 KOMIS 템플릿(income_data/komis/) 기반 v1 — price/map_korea/map_global LLM 배선 완료(260826)"
    for key, content in PROMPTS.items():
        execute_pg(_UPSERT_SQL, (key, content, description, now))
    print(f"ai_cfg.cfg_prompt에 {len(PROMPTS)}행 upsert 완료: {sorted(PROMPTS)}")


if __name__ == "__main__":
    main()
