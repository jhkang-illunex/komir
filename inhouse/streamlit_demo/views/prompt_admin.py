"""프롬프트 관리 — `ai_cfg.cfg_prompt` 조회·편집·저장 + report_gen 기능 테스트
(2026-08-27, report-summary-agent와 세션 간 조율해 확정한 계약).

- 저장 경로는 DB 직접 `UPDATE`뿐이다(별도 저장 API 없음, 만들 계획도 없음) —
  `prompt_key`는 report_gen `prompts.py::PROMPTS`가 코드로 고정한 집합이라
  이 화면에서 새 키를 만들지 않는다(행 추가 UI 없음, "DB에 있는 행을 그대로
  나열"만 한다).
- `content` 외 `page_name`·`page_definition`·`analysis_constraints`(JSONB
  문자열배열)·`policy_version`·`output_contract`(JSONB)도 편집 대상 —
  빈 입력은 반드시 NULL로 저장한다(NULL = "코드 기본값 사용", 값 단위 폴백
  설계라 빈 문자열과 다르다).
- 저장 = DB UPDATE 성공 직후 `POST /admin/prompts/reload`를 같은 액션으로
  묶는다(사람이 reload를 깜빡하지 않게). reload 실패는 "DB는 반영됐지만 캐시
  반영 실패"로 저장 자체 실패와 구분해서 보여준다.
- 기능 테스트는 `report_gen_client.PAGE_SPECS`를 그대로 재사용(복제 금지 —
  다른 세션이 계약을 계속 바꾸는 중이라 드리프트 방지). `summary_common`은
  전용 page_id가 없어 테스트할 페이지를 별도로 고르게 한다.

2026-08-27 UX 보완(main-agent 사용자 피드백 경유): `description` 컬럼은
`prompt_store.py::PromptRow`·`REQUIRED_COLUMNS`에 없고 `prompts.py`도 읽지
않는 참고용 메모일 뿐이라 편집창에 그 사실을 명시했다(입력창은 유지 — 메모
용도 자체는 유효). 기능 테스트가 지금 어느 리포트 화면(페이지별 프롬프트 중
어느 것)을 호출하는지 안 보이던 문제도 연결 화면 캡션·상단 전체목록으로
보완했다.

2026-08-27 추가 보완: `PageSpec.section`(주메뉴, page_recommend registry
`identity.section`의 2026-07-16 실측값 — 상세는 report_gen_client.py의
PageSpec docstring 참고)이 생겨서 prompt_key 선택창·전체목록·기능테스트
페이지선택 3곳 모두 "주메뉴 > 서브메뉴 (page_id)" 형식으로 통일했다.

2026-08-27 재변경(사용자가 report_demo.py 스타일로 재통일 요청): 상단
`prompt_key` 선택창을 report_demo.py와 같은 주메뉴/서브메뉴 콤보박스 2단
으로 바꿨다. `summary_common`(특정 메뉴 없는 공통 프롬프트)은 주메뉴 목록에
"[공통]" 항목을 추가해 수용 — 그걸 고르면 서브메뉴엔 `summary_common` 하나만
뜬다. 전체목록 expander·기능테스트 페이지선택은 이번 요청 범위 밖이라 기존
문자열 조합 형식 그대로 뒀다.

2026-08-27: 주메뉴 순서를 `report_gen_client.SECTION_ORDER`(komis_menu_map.yaml
`komis_site_map`의 실제 사이트맵 순서)로 고정했다. `summary_common`용
"[공통]" 항목은 YAML에 없는 항목이라 맨 앞에 둔다.
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import streamlit as st

from streamlit_demo.mineral_master import mineral_label, mineral_options
from streamlit_demo.komis_raw import KOMIS_RAW_PAGES, KomisRawConversionError
from streamlit_demo.report_gen_client import (
    EXTRA_FIELD_DEFAULTS,
    EXTRA_FIELD_LABELS,
    EXTRA_FIELD_VALUE_LABELS,
    PAGE_SPECS,
    PRICE_GROUP_OBSERVATIONS_BY_GROUP,
    SECTION_ORDER,
    ReportGenError,
    client_from_env,
    prioritize_core_minerals,
    render_json_error,
    render_report_markdown,
)

_INHOUSE_ROOT = Path(__file__).resolve().parents[2]
if str(_INHOUSE_ROOT / "services") not in sys.path:
    sys.path.insert(0, str(_INHOUSE_ROOT / "services"))

# Streamlit이 view 파일을 __main__으로 실행해(exec) __name__ 기반 로거명이
# 전부 "__main__"으로 뭉개진다(실측 확인, data_admin.py와 동일) — 경로를 그대로 쓴다.
_log = logging.getLogger("streamlit_demo.views.prompt_admin")

st.title("프롬프트 관리")
st.caption("분석요약 LLM 프롬프트(ai_cfg.cfg_prompt)를 조회·편집·저장하고, 저장한 내용이 report_gen에서 실제로 반영됐는지 즉석 호출로 확인합니다.")

_UPDATE_SQL = """
UPDATE ai_cfg.cfg_prompt SET
  content = %s,
  description = %s,
  updated_at = %s,
  page_name = %s,
  page_definition = %s,
  analysis_constraints = %s::jsonb,
  policy_version = %s,
  output_contract = %s::jsonb
WHERE prompt_key = %s
"""

_PERIOD_PLACEHOLDERS = {
    "month": ("2025-08", "2025-09"),
    "date": ("2025-08-01", "2025-09-01"),
    "year": ("2021", "2023"),
    "period": ("2026-Q1", "2026-Q2"),
}


@st.cache_data(ttl=30, show_spinner="ai_cfg.cfg_prompt를 조회하는 중…")
def _fetch_prompts():
    from shared.db import read_sql_pg

    return read_sql_pg(
        "SELECT prompt_key, content, description, updated_at, page_name, page_definition, "
        "analysis_constraints, policy_version, output_contract "
        "FROM ai_cfg.cfg_prompt ORDER BY prompt_key"
    )


def _jsonb_to_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return value
    return json.dumps(value, ensure_ascii=False, indent=2)


try:
    prompts = _fetch_prompts()
except Exception as exc:  # noqa: BLE001 — Postgres 미접속 환경에서도 화면은 떠야 한다
    _log.exception("ai_cfg.cfg_prompt 조회 실패")
    st.warning(f"ai_cfg.cfg_prompt 조회 실패 — Postgres(komis_demo) 접속을 확인하세요. ({str(exc)[:200]})")
    st.stop()

if prompts.empty:
    st.info("ai_cfg.cfg_prompt에 행이 없습니다.", icon=":material/info:")
    st.stop()

with st.expander(f"등록된 프롬프트 {len(prompts)}개 목록 — 공통 1 + 페이지별 {len(PAGE_SPECS)}개", expanded=False):
    overview = pd.DataFrame(
        {
            "prompt_key": pk,
            "연결된 화면": (
                f"{PAGE_SPECS[pk].section} > {PAGE_SPECS[pk].label} ({pk})" if pk in PAGE_SPECS
                else f"[공통] 아래 {len(PAGE_SPECS)}개 화면 전체에 적용"
            ),
        }
        for pk in prompts["prompt_key"]
    )
    st.dataframe(overview, use_container_width=True, hide_index=True)

_COMMON_SECTION = "[공통]"
_present_prompt_sections = {
    PAGE_SPECS[pk].section if pk in PAGE_SPECS else _COMMON_SECTION for pk in prompts["prompt_key"]
}
_prompt_key_sections = [_COMMON_SECTION] + [s for s in SECTION_ORDER if s in _present_prompt_sections]
if len(_prompt_key_sections) <= 1:  # SECTION_ORDER 로딩 실패 시 폴백(화면이 죽지 않게)
    _prompt_key_sections = list(dict.fromkeys(
        PAGE_SPECS[pk].section if pk in PAGE_SPECS else _COMMON_SECTION
        for pk in prompts["prompt_key"]
    ))

pk_col1, pk_col2 = st.columns(2)
prompt_section = pk_col1.selectbox("주메뉴", _prompt_key_sections, key="pa_prompt_section")
if prompt_section == _COMMON_SECTION:
    section_prompt_keys = [pk for pk in prompts["prompt_key"] if pk not in PAGE_SPECS]
else:
    section_prompt_keys = [
        pk for pk in prompts["prompt_key"] if pk in PAGE_SPECS and PAGE_SPECS[pk].section == prompt_section
    ]
prompt_key = pk_col2.selectbox(
    "서브메뉴", section_prompt_keys,
    format_func=lambda pk: f"{PAGE_SPECS[pk].label} ({pk})" if pk in PAGE_SPECS else pk,
    key="pa_prompt_key",
)
row = prompts[prompts["prompt_key"] == prompt_key].iloc[0]
st.caption(f"마지막 수정: {row['updated_at'] or '(기록 없음)'}")

content = st.text_area("content(지시문 본문)", value=row["content"] or "", height=220)
st.caption(
    "⚠ 근거·수치 구조(allowed_evidence 인용, 표 등)는 output_contract·공통 프롬프트가 "
    "함께 강제합니다 — content를 간단히 써도 상세 수치·표는 유지됩니다."
)
description = st.text_input(
    "description",
    value=row["description"] or "",
    help="⚠ 참고용 메모입니다 — report_gen(prompt_store.py::PromptRow)이 이 컬럼을 읽지 않아 실제 분석요약 결과엔 영향이 없습니다.",
)

with st.expander("페이지 정책 · 출력 계약(고급 — 비우면 NULL로 저장, 코드 기본값 사용)"):
    page_name = st.text_input("page_name", value=row["page_name"] or "")
    page_definition = st.text_area("page_definition", value=row["page_definition"] or "", height=100)
    _constraints = row["analysis_constraints"]
    if isinstance(_constraints, str):
        try:
            _constraints = json.loads(_constraints)
        except json.JSONDecodeError:
            _constraints = None
    constraints_text = st.text_area(
        "analysis_constraints(한 줄 = 항목 1개)",
        value="\n".join(_constraints) if _constraints else "",
        height=100,
    )
    policy_version = st.text_input("policy_version", value=row["policy_version"] or "")
    output_contract_text = st.text_area(
        "output_contract(JSON)", value=_jsonb_to_text(row["output_contract"]), height=140,
    )

client = client_from_env()

if st.button("저장 + report_gen 캐시 reload", type="primary"):
    errors: list[str] = []
    if not content.strip():
        errors.append("content는 비울 수 없습니다.")

    constraints_lines = [line.strip() for line in constraints_text.splitlines() if line.strip()]
    analysis_constraints_json = json.dumps(constraints_lines, ensure_ascii=False) if constraints_lines else None

    output_contract_json = None
    output_contract_error: json.JSONDecodeError | None = None
    if output_contract_text.strip():
        try:
            output_contract_json = json.dumps(json.loads(output_contract_text), ensure_ascii=False)
        except json.JSONDecodeError as exc:
            output_contract_error = exc

    if errors or output_contract_error:
        for message in errors:
            st.error(message)
        if output_contract_error:
            render_json_error(output_contract_error, field_label="output_contract")
    else:
        from shared.db import execute_pg

        params = (
            content,
            description.strip() or None,
            datetime.now(timezone.utc),
            page_name.strip() or None,
            page_definition.strip() or None,
            analysis_constraints_json,
            policy_version.strip() or None,
            output_contract_json,
            prompt_key,
        )
        try:
            execute_pg(_UPDATE_SQL, params)
        except Exception as exc:  # noqa: BLE001
            _log.exception("ai_cfg.cfg_prompt UPDATE 실패(prompt_key=%s)", prompt_key)
            st.error(f"DB 저장 실패: {exc}")
        else:
            _log.info("ai_cfg.cfg_prompt UPDATE 완료(prompt_key=%s)", prompt_key)
            st.success("DB 저장 완료")
            _fetch_prompts.clear()
            try:
                import httpx

                response = httpx.post(f"{client.base_url}/admin/prompts/reload", timeout=10.0)
                response.raise_for_status()
                reload_body = response.json()
                reloaded_count = reload_body.get("reloaded_prompt_count")
                if reloaded_count is not None:
                    st.success(f"report_gen 캐시 reload 완료 — 프롬프트 {reloaded_count}개 갱신")
                else:
                    st.success(f"report_gen 캐시 reload 완료 — {reload_body}")
            except Exception as exc:  # noqa: BLE001
                _log.exception("report_gen 캐시 reload 실패(prompt_key=%s)", prompt_key)
                st.warning(f"DB는 반영됐지만 report_gen 캐시 reload 실패 — 수동으로 재시도하세요. ({exc})")

st.divider()
st.subheader("기능 테스트")
st.caption("이 프롬프트가 실제로 반영됐는지 report_gen 분석요약 API를 즉석 호출해 확인합니다 — 저장 후 실행하세요.")

if not client.health():
    st.error(f"report_gen 연결 안 됨 · {client.base_url}", icon=":material/error:")

if prompt_key in PAGE_SPECS:
    test_page_id = prompt_key
else:
    st.info(
        f"이 프롬프트(summary_common)는 {len(PAGE_SPECS)}개 리포트 화면 전체의 공통 서두에 적용됩니다 — "
        "아래에서 대표로 확인할 화면을 1개 고르세요.",
        icon=":material/info:",
    )
    test_page_id = st.selectbox(
        "테스트할 페이지 선택(공통 프롬프트라 페이지를 골라야 합니다)",
        list(PAGE_SPECS),
        format_func=lambda p: f"{PAGE_SPECS[p].section} > {PAGE_SPECS[p].label} ({p})",
    )

spec = PAGE_SPECS[test_page_id]
st.caption(f"🔗 연결된 화면: {spec.section} > {spec.label} ({test_page_id}) · POST /api/v1/analysis/{spec.path}")
test_payload: dict = {}

if spec.has_mineral:
    options = prioritize_core_minerals(mineral_options())
    if options:
        picked = st.selectbox("광종", options, format_func=mineral_label, key=f"pa_mineral_{test_page_id}")
        test_payload["mineral"] = picked["code"]
        test_payload["mineral_name"] = picked["name_ko"]
    else:
        test_payload["mineral"] = st.text_input(
            "광종 코드", value="MNRL0018", key=f"pa_mineral_code_{test_page_id}",
            help="DB 접속 실패 — 광종 목록을 못 불러와 직접 입력으로 대체합니다.",
        )

start_key, end_key = spec.period_fields
if start_key:
    ph_start, ph_end = _PERIOD_PLACEHOLDERS.get(spec.period_kind, ("", ""))
    col1, col2 = st.columns(2)
    start_val = col1.text_input(f"{start_key}(선택)", value="", placeholder=ph_start, key=f"pa_start_{test_page_id}")
    end_val = col2.text_input(f"{end_key}(선택)", value="", placeholder=ph_end, key=f"pa_end_{test_page_id}")
    if start_val:
        test_payload[start_key] = int(start_val) if spec.period_kind == "year" else start_val
    if end_val:
        test_payload[end_key] = int(end_val) if spec.period_kind == "year" else end_val

if spec.extra_fields:
    st.caption("페이지 고유 필드")
    if "forecast_horizon" in spec.extra_fields:
        st.caption("forecast_horizon이 long(장기)이면 기간은 분기(YYYY-Qn)가 아닌 연도(YYYY) 형식입니다.")
    cols = st.columns(len(spec.extra_fields))
    for col, field in zip(cols, spec.extra_fields, strict=True):
        key = f"pa_extra_{test_page_id}_{field}"
        label = EXTRA_FIELD_LABELS.get(field, field)
        if field == "measure":
            test_payload["measure"] = col.selectbox(
                label, ("reserves", "production"), format_func=lambda v: EXTRA_FIELD_VALUE_LABELS["measure"][v], key=key
            )
        elif field == "forecast_horizon":
            test_payload["forecast_horizon"] = col.selectbox(
                label, ("medium", "long"), format_func=lambda v: EXTRA_FIELD_VALUE_LABELS["forecast_horizon"][v], key=key
            )
        elif field == "trade_direction":
            test_payload["trade_direction"] = col.selectbox(
                label, ("import", "export"), format_func=lambda v: EXTRA_FIELD_VALUE_LABELS["trade_direction"][v], key=key
            )
        elif field == "price_group":
            test_payload["price_group"] = col.selectbox(
                label, ("base_metals", "minor_metals"), format_func=lambda v: EXTRA_FIELD_VALUE_LABELS["price_group"][v], key=key
            )
        elif field == "price_criterion_serial":
            value = col.text_input(label, value="", key=key)
            if value:
                test_payload[field] = int(value)
        elif field == "compare_mineral":
            compare_options = prioritize_core_minerals(mineral_options())
            if compare_options:
                compare_picked = col.selectbox(label, compare_options, format_func=mineral_label, key=key)
                test_payload["compare_mineral"] = compare_picked["code"]
            else:
                test_payload["compare_mineral"] = col.text_input(f"{label} 코드", value="", key=key)
        else:
            value = col.text_input(label, value=EXTRA_FIELD_DEFAULTS.get(field, ""), key=key)
            if value:
                test_payload[field] = value

# 2026-08-30 재지시(사용자): streamlit이 komis.or.kr을 직접 호출하지 않는다 —
# 사람이 외부에서 KOMIS를 조회해 얻은 원본 JSON을 붙여넣으면 이 화면이
# report_gen 스키마로 변환한다(report_demo.py와 동일 방식).
observations_text = ""
komis_raw_text = ""
if test_page_id in KOMIS_RAW_PAGES:
    raw_spec = KOMIS_RAW_PAGES[test_page_id]
    st.caption(
        f"KOMIS 데이터 조회 결과(외부에서 조회한 원본 JSON을 붙여넣으세요) — "
        f"komis.or.kr {raw_spec.label}을 그대로 붙여넣으면 이 화면이 report_gen이 원하는 형태로 변환합니다."
    )
    komis_raw_text = st.text_area(
        "KOMIS 데이터 조회 결과", value=raw_spec.example_raw_json, height=160,
        key=f"pa_komis_raw_{test_page_id}",
    )
else:
    _observations_default = spec.observations_example
    _obs_key_suffix = ""
    if test_page_id == "price_group":
        _group = test_payload.get("price_group", "base_metals")
        _observations_default = PRICE_GROUP_OBSERVATIONS_BY_GROUP.get(_group, spec.observations_example)
        _obs_key_suffix = f"_{_group}"
    observations_text = st.text_area(
        "observations(JSON) — 방금 저장한 content/제약 조건이 이 데이터를 어떻게 요약하는지 확인합니다",
        value=_observations_default, height=140, key=f"pa_obs_{test_page_id}{_obs_key_suffix}",
    )

if st.button("이 프롬프트로 분석요약 호출", key=f"pa_test_btn_{test_page_id}"):
    if test_page_id in KOMIS_RAW_PAGES:
        try:
            raw = json.loads(komis_raw_text) if komis_raw_text.strip() else None
        except json.JSONDecodeError as exc:
            render_json_error(exc, field_label="KOMIS 데이터 조회 결과")
        else:
            if raw is None:
                st.error("KOMIS 데이터 조회 결과가 비어 있습니다 — 원본 JSON을 붙여넣으세요.")
            else:
                try:
                    converted = KOMIS_RAW_PAGES[test_page_id].convert(raw, test_payload)
                except KomisRawConversionError as exc:
                    st.error(f"KOMIS 원본 JSON 변환 실패: {exc}")
                else:
                    test_payload.update(converted)
                    try:
                        with st.spinner("report_gen 호출 중…"):
                            result = client.summarize(test_page_id, test_payload)
                    except ReportGenError as exc:
                        st.error(str(exc))
                    else:
                        status = result.get("status")
                        if status == "ok":
                            st.success("status: ok")
                            render_report_markdown(result.get("report"))
                        else:
                            st.warning(f"status: {status} — 원문 응답(디버깅용)")
                            st.json(result)
    else:
        try:
            test_payload["observations"] = json.loads(observations_text) if observations_text.strip() else None
        except json.JSONDecodeError as exc:
            render_json_error(exc, field_label="observations")
        else:
            try:
                with st.spinner("report_gen 호출 중…"):
                    result = client.summarize(test_page_id, test_payload)
            except ReportGenError as exc:
                st.error(str(exc))
            else:
                status = result.get("status")
                if status == "ok":
                    st.success("status: ok")
                    render_report_markdown(result.get("report"))
                else:
                    st.warning(f"status: {status} — 원문 응답(디버깅용)")
                    st.json(result)
