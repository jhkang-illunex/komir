"""요약보고서 작성 데모 — report_gen(`/api/v1/analysis/*`) 10종 연동(2026-08-27).

report_gen은 DB를 읽지 않고(prompt만 DB) 요청 바디의 `observations`로 원자료를
받는 계약이라, 이 화면도 실제 서비스 화면이 아니라 **API 자체를 그 계약대로
호출해보는 개발 데모**다 — page_id를 고르면 그 페이지가 요구하는 부속 필드
입력창과 observations JSON 예시(placeholder)가 뜬다. 응답은 `{status, report}`
그대로 표시(성공이면 report를 Markdown으로, 실패면 status 코드와 원문을 노출).

report_gen 코드는 다른 세션이 `.claude/worktrees/report_summary`에서 계속
바꾸는 중이다 — `report_gen_client.PAGE_SPECS`가 그 세션의 최신
`routers/analysis.py`와 어긋나면 422가 난다(하단에 원문 노출하므로 바로 보임).

2026-08-27: `price`(광물자원가격)가 KOMIS 실제 구조대로 `price_base_metals`
(비철금속)·`price_minor_metals`(희소금속) 2개 page_id로 분리됐다 — 9→10종.
`price_minor_metals`엔 KOMIS "비교광종" 기능 대응 `compare_mineral`/
`compare_price_criterion` 필드도 생겼다(다른 page_id로 보내면 서버가 거부).

2026-08-27: 페이지 선택을 주메뉴/서브메뉴 콤보박스 2단으로 분리했다(사용자
요청 — prompt_admin.py는 문자열 조합 1단 그대로 유지, 이 화면만 2단).
`PAGE_SPECS[p].section`(KOMIS 실제 주메뉴, page_recommend registry 실측값)
으로 1단(주메뉴)을 채우고, 그 주메뉴에 속한 page_id만 걸러 2단(서브메뉴,
label)에 보여준다 — price 분리 후 "광물자원가격" 주메뉴 아래 "비철금속"·
"희소금속" 2개가 자연스럽게 묶여 보인다."""
from __future__ import annotations

import json

import streamlit as st

from streamlit_demo.mineral_master import mineral_label, mineral_options
from streamlit_demo.report_gen_client import PAGE_SPECS, ReportGenError, client_from_env

st.title("요약보고서 작성 데모")
st.caption("report_gen 분석요약 API(10종)를 관측치(observations) 바디로 직접 호출해보는 개발 데모입니다 — 운영 화면이 아닙니다.")

client = client_from_env()
with st.sidebar:
    st.divider()
    if client.health():
        st.success(f"report_gen 연결됨 · {client.base_url}", icon=":material/check_circle:")
    else:
        st.error(f"report_gen 연결 안 됨 · {client.base_url}", icon=":material/error:")

_sections = list(dict.fromkeys(s.section for s in PAGE_SPECS.values()))
col1, col2 = st.columns(2)
section = col1.selectbox("주메뉴", _sections)
section_page_ids = [p for p in PAGE_SPECS if PAGE_SPECS[p].section == section]
page_id = col2.selectbox(
    "서브메뉴", section_page_ids, format_func=lambda p: f"{PAGE_SPECS[p].label} ({p})",
)
spec = PAGE_SPECS[page_id]

payload: dict = {}


def _mineral_picker(options: list, *, key: str) -> None:
    """드롭다운에서 고른 광종의 코드+한글명을 payload 에 채운다. DB 조회가
    실패해 options 가 비면(예: report_gen DB 미접속 환경) 코드 직접입력으로
    폴백한다 — 예전 동작과 동일, 화면이 죽지 않게."""

    if not options:
        col1, col2 = st.columns(2)
        payload["mineral"] = col1.text_input("광종 코드", value="MNRL0018", help="DB 접속 실패 — 광종 목록을 못 불러와 직접 입력으로 대체합니다.")
        mineral_name = col2.text_input("광종 표시명(선택)", value="")
        if mineral_name:
            payload["mineral_name"] = mineral_name
        return
    picked = st.selectbox("광종", options, format_func=mineral_label, key=key)
    payload["mineral"] = picked["code"]
    payload["mineral_name"] = picked["name_ko"]


if spec.has_mineral and page_id == "indicator_market":
    # 사용자 요청(2026-08-27): 시장동향지표는 KOMIS 화면처럼 비철금속/희소금속을
    # 나눠서 보여준다. st.tabs 는 활성 탭을 코드에서 읽을 방법이 없어(둘 다 매
    # 재실행마다 렌더돼 어느 쪽이 화면에 보이는지 구분 불가) 대신 탭처럼 보이는
    # st.segmented_control(선택값을 실제로 돌려주는 위젯)을 쓴다.
    group = st.segmented_control("광종군", ["비철금속", "희소금속"], default="비철금속")
    group_key = "base_metals" if group == "비철금속" else "minor_metals"
    _mineral_picker(mineral_options(group_key), key=f"mineral_{page_id}_{group_key}")
elif spec.has_mineral:
    _mineral_picker(mineral_options(), key=f"mineral_{page_id}")

start_key, end_key = spec.period_fields
if start_key:
    col1, col2 = st.columns(2)
    placeholders = {
        "month": ("2025-08", "2025-09"), "date": ("2025-08-01", "2025-09-01"),
        "year": ("2021", "2023"), "period": ("2026-Q1", "2026-Q2"),
    }
    ph_start, ph_end = placeholders.get(spec.period_kind, ("", ""))
    start_val = col1.text_input(f"{start_key}(선택)", value="", placeholder=ph_start)
    end_val = col2.text_input(f"{end_key}(선택)", value="", placeholder=ph_end)
    if start_val:
        payload[start_key] = int(start_val) if spec.period_kind == "year" else start_val
    if end_val:
        payload[end_key] = int(end_val) if spec.period_kind == "year" else end_val

if spec.extra_fields:
    st.caption("페이지 고유 필드")
    cols = st.columns(len(spec.extra_fields))
    for col, field in zip(cols, spec.extra_fields, strict=True):
        if field == "measure":
            payload["measure"] = col.selectbox("measure", ("reserves", "production"))
        elif field == "forecast_horizon":
            payload["forecast_horizon"] = col.selectbox("forecast_horizon", ("medium", "long"))
        elif field == "trade_direction":
            payload["trade_direction"] = col.selectbox("trade_direction", ("import", "export"))
        elif field == "price_group":
            payload["price_group"] = col.selectbox("price_group", ("base_metals", "minor_metals"))
        elif field == "price_criterion_serial":
            value = col.text_input(field, value="")
            if value:
                payload[field] = int(value)
        else:
            value = col.text_input(field, value="")
            if value:
                payload[field] = value

st.caption("observations(JSON 배열) — 계산에 쓰는 원자료. DB를 안 읽으므로 비우면 대부분 NO_DATA로 응답합니다.")
observations_text = st.text_area("observations", value=spec.observations_example, height=140)

if st.button("분석요약 생성", type="primary"):
    try:
        payload["observations"] = json.loads(observations_text) if observations_text.strip() else None
    except json.JSONDecodeError as exc:
        st.error(f"observations JSON 파싱 실패: {exc}")
    else:
        try:
            with st.spinner("report_gen 호출 중…"):
                st.session_state["report_demo_result"] = client.summarize(page_id, payload)
        except ReportGenError as exc:
            st.session_state["report_demo_result"] = None
            st.error(str(exc))

result = st.session_state.get("report_demo_result")
if result:
    status = result.get("status")
    if status == "ok":
        st.success("status: ok")
        st.markdown(result.get("report") or "_(빈 보고서)_")
    else:
        st.warning(f"status: {status}")
        if result.get("report"):
            st.markdown(result["report"])

with st.expander("요청 바디 미리보기"):
    st.json({**payload, "observations": "(위 텍스트 영역 값)"})
