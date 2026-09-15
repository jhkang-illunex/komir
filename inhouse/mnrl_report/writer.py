"""정책을 지키는 upsert.

- INSERT … ON CONFLICT DO UPDATE. UPDATE 대상 컬럼은 이번 실행이 만든 RULE 컬럼
  (+ 생성형 엔진이 돌았으면 LLM 컬럼) + 엔진 메타뿐. MANUAL 컬럼은 UPDATE 절에
  넣지 않고 INSERT 시 초기 시드만 넣는다(이미 있는 행의 MANUAL 값은 보존).
- 기존 행이 DRAFT가 아니면(REVIEWED/DONE) force=False일 때 UPDATE를 건너뛴다
  (ON CONFLICT … WHERE gen_stts_cd='DRAFT').
- 값이 None인 RULE 컬럼도 NULL로 덮어쓴다(원천이 사라지면 문장도 사라져야
  "지어내지 않는다" 원칙이 유지된다).
- 엔진 메타: rule_ver = 규칙 엔진 버전(YYMMDD-sha8), llm_model_ver = 생성형 엔진
  버전(모델명은 ai_rpt_engine_ver.model_nm에서 역참조), llm_refined_yn.
"""
from __future__ import annotations

import sqlalchemy as sa

from . import db
from .engines.base import EngineResult
from .policy import KEYS, LLM, MANUAL, POLICIES, RULE


def upsert(table: str, rule: EngineResult, rule_ver: str, *, gen: EngineResult | None = None,
           gen_ver: str | None = None, manual_seed: dict | None = None, force: bool = False,
           dry_run: bool = False) -> str:
    """rule: 규칙 엔진 결과(RULE 컬럼), gen: 생성형 엔진 결과(LLM 컬럼, None이면 LLM 컬럼 불변)."""
    assert table in db.WRITABLE_TABLES, table
    policy = POLICIES[table]
    keys = KEYS[table]
    rule_cols = [c for c, k in policy.items() if k == RULE]
    values: dict = {c: rule.columns.get(c) for c in rule_cols}
    update_cols = list(rule_cols)
    values["rule_ver"] = rule_ver
    update_cols.append("rule_ver")
    if gen is not None:
        for c, k in policy.items():
            if k == LLM:
                values[c] = gen.columns.get(c)
                update_cols.append(c)
        values["llm_model_ver"] = gen_ver
        values["llm_refined_yn"] = "Y" if gen.filled else "N"
        update_cols += ["llm_model_ver", "llm_refined_yn"]
    for c, k in policy.items():
        if k == MANUAL and manual_seed and manual_seed.get(c) is not None:
            values[c] = manual_seed[c]  # INSERT 시에만 유효(UPDATE 절엔 넣지 않음)
    cols = list(values)
    set_clause = ", ".join(f"{c}=EXCLUDED.{c}" for c in update_cols if c not in keys)
    set_clause += ", last_mdfcn_dt=now()"
    where = "" if force else f" WHERE {table}.gen_stts_cd='DRAFT'"
    sql = (f"INSERT INTO public.{table} ({', '.join(cols)}) VALUES ({', '.join(':' + c for c in cols)}) "
           f"ON CONFLICT ({', '.join(keys)}) DO UPDATE SET {set_clause}{where} "
           f"RETURNING (xmax = 0) AS inserted")
    if dry_run:
        return "dry-run"
    with db.engine().begin() as c:
        res = c.execute(sa.text(sql), values).fetchall()
    if not res:
        return "skipped(not DRAFT)"
    return "inserted" if res[0][0] else "updated"
