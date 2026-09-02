# -*- coding: utf-8 -*-
"""프롬프트 DB화 자동 검증 — 2026-08-27 신설(DB화 2단계).

확인하는 것(전부 실제 PostgreSQL `ai_cfg.cfg_prompt` 대상, PG_DSN 필요):
  V1  컬럼 자동 추가: `prompt_store.ensure_schema()` 후 information_schema에
      REQUIRED_COLUMNS 전부 존재.
  V2  시드 라운드트립: `seed_prompts.main()` 실행 → `prompt_store.reload()` →
      13키 전부 DB 값 == 코드 기본값(content·name·definition·constraints·
      version·output_contract), `resolve_page_config().source`가 전부 "db"
      (2026-08-27 price page_id 분리로 10→11키, 2026-08-28 price_iron_energy/
      price_other 추가로 11→13키, §RETIRED_KEYS 정리도 같이 확인).
  V3  DB 변경 반영: `price_minor_metals`(2026-08-27 이전엔 `price`) 행의
      page_definition·analysis_constraints·output_contract(major_changes
      [1,3])를 UPDATE → reload → 규칙기반
      `analyze()` 응답의 page_definition/notices, `build_summary_payload()`의
      page_policy·output_contract, `_validate_llm_summary`의 문장수 한도가
      전부 바뀐 값을 따르는지. 끝나면 재시드로 원복하고 원복도 확인(finally).
  V4  값 단위 폴백: `map_korea` 행의 page_name을 NULL로 → reload → name은 코드
      기본값("db"→"code"), definition은 여전히 DB. 원복.
  V5  잘못된 output_contract(범위 역전)는 경고 후 코드 기본값 사용(서비스 무중단).

CHECK 계약: 전부 통과하면 종료코드 0 + "VERIFY_PROMPT_DB_OK", 하나라도 실패하면
종료코드 1 + 실패 항목. 실행: `python3 scripts/verify_prompt_db.py`
(report_gen 디렉토리 기준, PG_DSN은 inhouse/.env).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_APP_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_APP_ROOT))

from app._bootstrap import ensure_shared_on_path  # noqa: E402

ensure_shared_on_path()

from shared.db import execute_pg, read_sql_pg  # noqa: E402

from app.analysis import prompt_store, seed_prompts  # noqa: E402
from app.analysis.models import AnalysisSummaryRequest, SummaryNarrative, SummarySentence  # noqa: E402
from app.analysis.prompts import PROMPTS, build_summary_payload, code_page_config, resolve_page_config  # noqa: E402
from app.analysis.summary import AnalysisSummaryService, _validate_llm_summary  # noqa: E402

FAILURES: list[str] = []


def check(cond: bool, label: str) -> None:
    print(("  PASS " if cond else "  FAIL ") + label)
    if not cond:
        FAILURES.append(label)


PRICE_BODY = dict(
    mineral="LI",
    mineral_name="리튬",
    observations=[{"date": f"2026-08-{d:02d}", "commerce_price": 70000 + d * 150, "highest_price": 70500 + d * 150, "lowest_price": 69500 + d * 150} for d in range(1, 21)],
)


def _db_row(key: str) -> dict:
    frame = read_sql_pg(
        "SELECT prompt_key, content, page_name, page_definition, analysis_constraints, policy_version, output_contract "
        f"FROM ai_cfg.cfg_prompt WHERE prompt_key = '{key}'"
    )
    return frame.to_dict("records")[0]


def v1_columns() -> None:
    print("V1 컬럼 자동 추가")
    missing_before = prompt_store.ensure_schema()
    cols = prompt_store._existing_columns()
    check(all(c in cols for c in prompt_store.REQUIRED_COLUMNS), f"REQUIRED_COLUMNS 전부 존재 (적용 전 누락: {missing_before or '없음'})")


def v2_roundtrip() -> None:
    print("V2 시드 라운드트립")
    seed_prompts.main()
    result = prompt_store.reload()
    check(result.ok, f"reload 성공(ok={result.ok})")
    check(result.count == len(PROMPTS), f"reload 행 수 == PROMPTS 키 수 ({result.count})")
    for key in PROMPTS:
        row = _db_row(key)
        check(row["content"] == PROMPTS[key], f"{key}: content 동일")
        if key == "summary_common":
            check(row["page_name"] is None and row["output_contract"] is None, "summary_common: 페이지 컬럼 NULL")
            continue
        cfg = code_page_config(key)
        eff = resolve_page_config(key)
        oc = row["output_contract"] if isinstance(row["output_contract"], dict) else json.loads(row["output_contract"])
        ac = row["analysis_constraints"] if isinstance(row["analysis_constraints"], list) else json.loads(row["analysis_constraints"])
        check(row["page_name"] == cfg.name and row["page_definition"] == cfg.definition and row["policy_version"] == cfg.policy_version, f"{key}: name/definition/version 동일")
        check(list(ac) == list(cfg.analysis_constraints), f"{key}: analysis_constraints 동일")
        check(oc == cfg.output_contract_json(), f"{key}: output_contract 동일")
        expected_source = {k: "db" for k in eff.source}
        if key != "map_mineral":
            expected_source["total_sentence_range"] = "code"  # 시드가 total을 안 쓰는 페이지는 코드값
        check(eff.source == expected_source, f"{key}: resolve 출처 정확히 일치 ({eff.source})")
        check(eff.section_sentence_ranges == cfg.section_sentence_ranges, f"{key}: 유효 문장수 범위 == 코드 기본값")


def v3_db_change_propagates() -> None:
    print("V3 DB 변경 → reload → 응답/payload/검증기 반영")
    marker_def = "[VERIFY] 검증용 정의문 — 이 문구가 보이면 DB 값이 반영된 것이다."
    marker_constraint = "[VERIFY] 검증용 제약문."
    new_contract = {"section_sentence_ranges": {"core_diagnosis": [1, 1], "major_changes": [1, 3], "current_position": [1, 2]}, "max_evidence_ids_per_sentence": 3}
    try:
        execute_pg(
            "UPDATE ai_cfg.cfg_prompt SET page_definition = %s, analysis_constraints = %s::jsonb, output_contract = %s::jsonb WHERE prompt_key = 'price_minor_metals'",
            (marker_def, json.dumps([marker_constraint], ensure_ascii=False), json.dumps(new_contract)),
        )
        prompt_store.reload()
        eff = resolve_page_config("price_minor_metals")
        check(eff.definition == marker_def and eff.analysis_constraints == (marker_constraint,), "resolve_page_config('price_minor_metals')가 DB 값 반영")
        check(eff.section_sentence_ranges["major_changes"] == (1, 3), "output_contract major_changes (1,3) 반영")
        svc = AnalysisSummaryService(None, llm=None)
        resp = svc.analyze(AnalysisSummaryRequest(page_id="price_minor_metals", **PRICE_BODY))
        check(resp.page_definition == marker_def and resp.notices == [marker_constraint], "analyze() 응답 page_definition/notices 반영")
        payload = build_summary_payload(response=resp, policy=None, allowed_evidence=[])  # type: ignore[arg-type]
        check(payload["page_policy"]["definition"] == marker_def and payload["output_contract"]["section_sentence_ranges"]["major_changes"] == [1, 3], "build_summary_payload page_policy/output_contract 반영")
        # 검증기: major_changes 3문장 — 코드 기본값(1,2)이면 거부, DB(1,3)면 문장수 통과
        claims = [c for c in svc.analyze(AnalysisSummaryRequest(page_id="price_minor_metals", **PRICE_BODY)).summary.major_changes]
        _ = claims
        from app.analysis.komir_summary import calculate_price_summary
        from app.analysis.models import MineralRef, PriceObservation, PriceSeries
        series = PriceSeries(page_id="price_minor_metals", mineral=MineralRef(code="LI", name="리튬"), price_criterion_serial=0, available_start_date="2026-08-01", available_end_date="2026-08-20", source_type="api", source_id="x", data_version="v", data_as_of="2026-08-20", observations=[PriceObservation(**o) for o in PRICE_BODY["observations"]])
        calc = calculate_price_summary(series)
        by_sec = {"core_diagnosis": [], "major_changes": [], "current_position": []}
        for c in calc.claims:
            by_sec[c.section].append(c)
        major = by_sec["major_changes"]
        three = [SummarySentence(text=c.fact, evidence_ids=[c.id]) for c in major[:3]]
        rest_ids = [c.id for c in major[3:]]
        if rest_ids:
            three[-1] = SummarySentence(text=" ".join(c.fact for c in major[2:]), evidence_ids=[major[2].id, *rest_ids][:3])
        narrative = SummaryNarrative(
            core_diagnosis=[SummarySentence(text=c.fact, evidence_ids=[c.id]) for c in by_sec["core_diagnosis"]],
            major_changes=three,
            current_position=[SummarySentence(text=" ".join(c.fact for c in by_sec["current_position"]), evidence_ids=[c.id for c in by_sec["current_position"]][:3])],
        )
        err = _validate_llm_summary(narrative, calc.claims, page_id="price_minor_metals")
        check(err != "섹션별 분석문 수가 출력 계약과 일치하지 않는다.", f"검증기가 DB 범위(1,3)로 3문장 허용 (err={err!r})")
    finally:
        seed_prompts.main()
        prompt_store.reload()
        eff = resolve_page_config("price_minor_metals")
        base = code_page_config("price_minor_metals")
        check(eff.definition == base.definition and eff.section_sentence_ranges == base.section_sentence_ranges, "재시드 원복 확인")


def v4_null_fallback() -> None:
    print("V4 값 단위 폴백(page_name NULL)")
    try:
        execute_pg("UPDATE ai_cfg.cfg_prompt SET page_name = NULL WHERE prompt_key = 'map_korea'")
        prompt_store.reload()
        eff = resolve_page_config("map_korea")
        check(eff.source["name"] == "code" and eff.name == code_page_config("map_korea").name, "name은 코드 기본값으로 폴백")
        check(eff.source["definition"] == "db", "definition은 여전히 DB")
    finally:
        seed_prompts.main()
        prompt_store.reload()
        check(resolve_page_config("map_korea").source["name"] == "db", "원복 확인")


def v5_bad_contract_ignored() -> None:
    print("V5 잘못된 output_contract는 경고 후 코드 기본값")
    try:
        execute_pg("UPDATE ai_cfg.cfg_prompt SET output_contract = %s::jsonb WHERE prompt_key = 'map_global'", (json.dumps({"section_sentence_ranges": {"core_diagnosis": [2, 1], "major_changes": [1, 2], "current_position": [1, 1]}}),))
        prompt_store.reload()
        eff = resolve_page_config("map_global")
        check(eff.section_sentence_ranges == code_page_config("map_global").section_sentence_ranges and eff.source["section_sentence_ranges"] == "code", "역전 범위 무시, 코드 기본값 사용")
        resp = AnalysisSummaryService(None, llm=None).analyze(AnalysisSummaryRequest(page_id="map_global", mineral="NI", observations=[{"date": "2026-08-01", "country_code": "CN", "country_name": "중국", "origin_country_code": "ID", "origin_country_name": "인도네시아", "import_amount": 10.0}]))
        check(resp.page_id == "map_global", "서비스 무중단(analyze 정상)")
    finally:
        seed_prompts.main()
        prompt_store.reload()


def main() -> None:
    v1_columns()
    v2_roundtrip()
    v3_db_change_propagates()
    v4_null_fallback()
    v5_bad_contract_ignored()
    if FAILURES:
        print(f"\n실패 {len(FAILURES)}건:")
        for f in FAILURES:
            print(" -", f)
        sys.exit(1)
    print("\nVERIFY_PROMPT_DB_OK")


if __name__ == "__main__":
    main()
