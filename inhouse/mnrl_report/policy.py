"""컬럼별 생성 정책 — 테이블 COMMENT의 [RULE]/[LLM]/[MANUAL] 태그를 코드로 고정.

덮어쓰기 규칙(writer.py가 강제):
- RULE   : 매 실행 재계산해 덮어쓴다. 단 행의 gen_stts_cd가 DRAFT일 때만
           (REVIEWED/DONE은 --force 없이는 손대지 않는다 — 검수 결과 보호).
- LLM    : LLM 단계가 켜졌을 때만 쓴다. 같은 DRAFT 조건.
- MANUAL : 엔진은 절대 덮어쓰지 않는다. 비어 있을 때만 고정 문안을 시드한다
           (resources/fixed_texts.json). 담당자가 채운 값은 유지.
- META   : rule_ver·llm_model_ver·llm_refined_yn·last_mdfcn_dt는 엔진이 관리,
           gen_stts_cd·reviewer_id·reviewed_dt는 검수 화면이 관리.
"""
from __future__ import annotations

RULE, LLM, MANUAL, META = "RULE", "LLM", "MANUAL", "META"

OVERALL_POLICY: dict[str, str] = {
    "base_ymd": RULE, "period_from_ymd": RULE, "period_to_ymd": RULE,
    "rpt_year": RULE, "rpt_week_no": RULE, "title": RULE,
    "overall_score": RULE, "overall_wow": RULE, "overall_level_txt": RULE, "focus_mnrl_cds": RULE,
    "smry_quant_txt": RULE, "smry_cause_txt": LLM, "smry_demand_bg_txt": LLM, "smry_supply_bg_txt": LLM,
    "diag_grade_cd": RULE, "diag_grade_mnrl_txt": RULE, "diag_key_txt": LLM, "diag_tbl_title_txt": RULE,
    "idx_anal_txt": RULE, "judge_quant_txt": RULE, "judge_basis_txt": LLM,
    "geo_risk_idx": MANUAL, "geo_risk_wow_pct": MANUAL,  # 실값 원천 적재 전까지 MANUAL(→RULE 전환 예정)
    "risk1_title": LLM, "risk1_txt": LLM,
    "risk2_title": LLM, "risk2_quant_txt": RULE, "risk2_narr_txt": LLM,
    "risk3_title": LLM, "gscpi_val": MANUAL, "gscpi_mom": MANUAL, "gscpi_yoy": MANUAL, "risk3_txt": LLM,
    "risk4_title": LLM, "risk4_quant_txt": RULE, "risk4_narr_txt": LLM,
    "response_txt": LLM,
    "gen_stts_cd": META, "rule_ver": META, "llm_model_ver": META, "llm_refined_yn": META,
    "reviewer_id": META, "reviewed_dt": META, "frst_reg_dt": META, "last_mdfcn_dt": META,
}

MNRL_POLICY: dict[str, str] = {
    "mnrknd_unq_cd": RULE, "base_ymd": RULE, "rpt_year": RULE, "rpt_week_no": RULE, "title": RULE,
    "grade_cd": RULE, "grade_nm": RULE, "score": RULE, "score_wow": RULE, "score_mom": RULE,
    "grade_streak_wk": RULE, "price_wow_pct": RULE,
    "smry_quant_txt": RULE, "smry_cause_txt": LLM, "diag_result_txt": RULE, "diag_key_txt": LLM,
    "price_bg_long_txt": MANUAL, "price_bg_recent_txt": LLM, "price_foot_txt": RULE,
    "price_signal_cd": RULE, "price_signal_streak_wk": RULE, "price_signal_foot_txt": RULE,
    "import_month_ymd": RULE, "import_month_txt": RULE, "import_cagr_txt": RULE,
    "import_ntn_txt": RULE, "import_hhi": RULE,
    "reserve_txt": RULE, "production_txt": RULE,
    "risk_quant_txt": RULE, "risk_narr_txt": LLM, "domestic_prod_txt": MANUAL, "import_struct_txt": RULE,
    "response_txt": LLM,
    "gen_stts_cd": META, "rule_ver": META, "llm_model_ver": META, "llm_refined_yn": META,
    "reviewer_id": META, "reviewed_dt": META, "frst_reg_dt": META, "last_mdfcn_dt": META,
}

POLICIES = {"ai_rpt_overall": OVERALL_POLICY, "ai_rpt_mnrl": MNRL_POLICY}
KEYS = {"ai_rpt_overall": ["base_ymd"], "ai_rpt_mnrl": ["mnrknd_unq_cd", "base_ymd"]}


def columns_of(table: str, kind: str) -> list[str]:
    return [c for c, k in POLICIES[table].items() if k == kind]
