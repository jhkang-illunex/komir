"""요약보고서 작성 데모 — report_gen(`/api/v1/analysis/*`) 12종 연동(2026-08-27~28).

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
"희소금속" 2개가 자연스럽게 묶여 보인다.

2026-08-27: 주메뉴 순서를 `report_gen_client.SECTION_ORDER`(komis_menu_map.yaml
`komis_site_map`의 실제 사이트맵 순서)로 고정했다 — 이전엔 PAGE_SPECS dict
등록 순서를 그대로 따라가 실제 KOMIS 내비게이션 순서와 어긋날 수 있었다.

2026-08-28: 광물자원가격 나머지 서브메뉴 `price_iron_energy`(철광석 및
에너지)·`price_other`(기타) 2종 추가 — 10→12종. 필드 구성은 price_base_metals
와 동일(compare_* 없음)."""
from __future__ import annotations

import json
from datetime import date

import streamlit as st

from streamlit_demo.mineral_master import (
    PRICE_CATEGORY_BY_PAGE,
    market_supply_mineral_options,
    mineral_label,
    mineral_options_for_page,
)
from streamlit_demo.komis_fetch import (
    KOMIS_FETCH_DISPATCH,
    KomisFetchError,
    fetch_hs_code_options,
    fetch_product_type_options,
)
from streamlit_demo.komis_raw import KOMIS_RAW_PAGES, KomisRawConversionError
from streamlit_demo.report_gen_client import (
    EXTRA_FIELD_DEFAULTS,
    EXTRA_FIELD_LABELS,
    EXTRA_FIELD_VALUE_LABELS,
    PAGE_SPECS,
    SECTION_ORDER,
    ReportGenError,
    client_from_env,
    prioritize_core_minerals,
    render_json_error,
    render_report_markdown,
)

# 2026-08-31 사용자 지시: 광물자원가격 4종(price_*) 공통으로 평균 옵션·기간
# 구분자·기간(2000-01~현재) 실시간 조회 옵션 추가 — 값은 komis_fetch.py에서
# 라이브 실측한 것과 정확히 맞춘다(사용자가 부른 "QUATER"는 실제 KOMIS 값이
# 아니라 QUARTER가 맞음, §komis_fetch.py 주석 참고).
AVG_OPT_LABELS = {"일간": "DAY", "주간": "WEEK", "월간": "MONTH", "분기간": "QUARTER", "년간": "YEAR"}
PERIOD_FIELD_LABELS = {"년간": "year", "월간": "month"}


# 2026-08-31 사용자 지시: 대한민국 수급지도(map_korea) 생산품 유형(Lv3)·
# HS코드(Lv5) 드롭다운은 광종이 바뀔 때만 새로 조회하면 되므로(다른 위젯
# 조작마다 매번 komis.or.kr을 다시 부르면 느려진다) 캐시로 감싼다 — 광종
# 드롭다운(mineral_master.load_minerals)과 같은 패턴(ttl=300).
@st.cache_data(ttl=300, show_spinner="생산품 유형 목록을 불러오는 중…")
def _cached_product_type_options(mineral_code: str) -> list[dict]:
    return fetch_product_type_options(mineral_code)


@st.cache_data(ttl=300, show_spinner="HS코드 목록을 불러오는 중…")
def _cached_hs_code_options(mineral_code: str, product_type_code: str) -> list[dict]:
    return fetch_hs_code_options(mineral_code, product_type_code)

st.title("요약보고서 작성 데모")
st.caption("report_gen 분석요약 API(12종)를 관측치(observations) 바디로 직접 호출해보는 개발 데모입니다 — 운영 화면이 아닙니다.")

client = client_from_env()
with st.sidebar:
    st.divider()
    if client.health():
        st.success(f"report_gen 연결됨 · {client.base_url}", icon=":material/check_circle:")
    else:
        st.error(f"report_gen 연결 안 됨 · {client.base_url}", icon=":material/error:")

_present_sections = set(s.section for s in PAGE_SPECS.values())
_sections = [s for s in SECTION_ORDER if s in _present_sections] or list(dict.fromkeys(
    s.section for s in PAGE_SPECS.values()
))
col1, col2 = st.columns(2)
section = col1.selectbox("주메뉴", _sections)
section_page_ids = [p for p in PAGE_SPECS if PAGE_SPECS[p].section == section]
page_id = col2.selectbox(
    "서브메뉴", section_page_ids, format_func=lambda p: f"{PAGE_SPECS[p].label} ({p})",
)
spec = PAGE_SPECS[page_id]

# 2026-09-01 사용자 지시: 주메뉴/서브메뉴를 바꿔도 이전 페이지에서 생성된
# 결과 보고서가 하단에 그대로 남아 있어 "지금 선택과 무관한 결과"처럼
# 보이는 문제 — page_id 변경을 감지해 결과를 비운다.
if st.session_state.get("_report_demo_last_page_id") != page_id:
    st.session_state["_report_demo_last_page_id"] = page_id
    st.session_state["report_demo_result"] = None

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


def _compare_mineral_picker(col, page_id: str) -> None:
    """광물자원가격 서브메뉴(price_*) 전용 compare_mineral 필드 — 2026-08-28 UI/UX
    감사에서 지적된 "안내 없는 순수 텍스트 입력" 문제 대응. 이미 로드된 광종
    마스터를 그대로 재사용해 드롭다운으로 바꾼다. 2026-08-31: 서브메뉴가 바뀌면
    비교 대상도 그 서브메뉴 소속 광종만 보이게 mineral_options_for_page로 필터.
    2026-08-31 재수정(사용자 지적): compare_mineral은 KOMIS에서도 선택 필드라
    "비교 안 함"이 기본이어야 하는데 selectbox가 항상 첫 옵션을 자동 선택해
    원치 않아도 비교가 걸렸다 — index=None으로 기본 미선택, 값을 고를 때만
    payload에 채운다."""
    options = prioritize_core_minerals(mineral_options_for_page(page_id))
    label = EXTRA_FIELD_LABELS.get("compare_mineral", "compare_mineral")
    if not options:
        code = col.text_input(
            f"{label} 코드", value="", key=f"compare_mineral_code_{page_id}",
            help="DB 접속 실패 — 광종 목록을 못 불러와 직접 입력으로 대체합니다. 비워두면 비교하지 않습니다.",
        )
        if code:
            payload["compare_mineral"] = code
        return
    picked = col.selectbox(
        label, options, format_func=mineral_label, key=f"compare_mineral_{page_id}",
        index=None, placeholder="비교하지 않음",
    )
    if picked is not None:
        payload["compare_mineral"] = picked["code"]


# 2026-08-31 삭제(사용자 직접 확인): 시장동향지표(indicator_market)의
# "광종군(비철금속/희소금속)" 분리는 2026-08-27 당시 실제 KOMIS 화면을
# 캡처/확인하지 않고 그 자리의 인상만으로 추가했던 것 — 사용자가 지금 실제
# KOMIS 시장동향지표 화면엔 이런 구분이 없다고 확인해줘서(같은 날
# indicator_supply를 로그인해 확인하고 분리를 안 했던 것과 같은 결론) 걷어냈다.
# 이제 나머지 has_mineral 페이지와 동일하게 전체 광종 드롭다운 하나만 쓴다.
# 2026-09-01(사용자 지시): indicator_market/supply는 `ai_mnrl_mst`(이 프로젝트
# 19종 한정 DB)가 아니라 report_gen 자신의 registry(§mineral_master.py
# market_supply_mineral_options)로 광종을 채운다 — 실제 KOMIS 화면 39종/36종과
# 일치, 라이브검증에 쓴 갈륨(MNRL0024) 포함.
if spec.has_mineral:
    if page_id in ("indicator_market", "indicator_supply"):
        mineral_opts = prioritize_core_minerals(market_supply_mineral_options(page_id))
    else:
        mineral_opts = prioritize_core_minerals(mineral_options_for_page(page_id))
    _mineral_picker(mineral_opts, key=f"mineral_{page_id}")

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
    if "forecast_horizon" in spec.extra_fields:
        # 2026-08-28 UI/UX 감사: forecast_horizon=long이면 기간 형식이 연도(YYYY)로
        # 바뀌는데 위 period 플레이스홀더는 항상 분기(YYYY-Qn) 예시라 혼동을 준다 —
        # 필드 순서상 여기서 뒤늦게 알 수 있어 레이아웃 재배치 대신 캡션으로 안내.
        st.caption("forecast_horizon이 long(장기)이면 기간은 분기(YYYY-Qn)가 아닌 연도(YYYY) 형식입니다.")
    cols = st.columns(len(spec.extra_fields))
    for col, field in zip(cols, spec.extra_fields, strict=True):
        label = EXTRA_FIELD_LABELS.get(field, field)
        if field == "measure":
            payload["measure"] = col.selectbox(
                label, ("reserves", "production"), format_func=lambda v: EXTRA_FIELD_VALUE_LABELS["measure"][v]
            )
        elif field == "forecast_horizon":
            payload["forecast_horizon"] = col.selectbox(
                label, ("medium", "long"), format_func=lambda v: EXTRA_FIELD_VALUE_LABELS["forecast_horizon"][v]
            )
        elif field == "trade_direction":
            payload["trade_direction"] = col.selectbox(
                label, ("import", "export"), format_func=lambda v: EXTRA_FIELD_VALUE_LABELS["trade_direction"][v]
            )
        elif field == "price_criterion_serial":
            value = col.text_input(label, value="")
            if value:
                payload[field] = int(value)
        elif field == "compare_mineral":
            _compare_mineral_picker(col, page_id)
        else:
            value = col.text_input(label, value=EXTRA_FIELD_DEFAULTS.get(field, ""))
            if value:
                payload[field] = value

# 2026-08-30 재지시(사용자): streamlit이 komis.or.kr을 직접 호출하지 않는다
# (오전 "실시간 가져오기" 시도는 이 세션에서 komis.or.kr 자체가 네트워크
# 레벨로 막혀 있어 취소됨). 대신 사람이 외부에서 KOMIS를 조회해 얻은 원본
# JSON을 붙여넣으면 이 화면이 report_gen 스키마로 변환한다(report_gen
# 원칙 "prompt 제외 DB/외부호출 없음"과 일치). 원본 구조를 아는 9개 페이지
# (KOMIS_RAW_PAGES)만 이 방식이고, 나머지(indicator_market/supply — 로그인
# 필요 페이지라 원본 캡처 없음)는 기존 observations 수동 입력을 그대로 쓴다.
# 2026-08-30 추가 지시(사용자): 화면은 (1) komis.or.kr 해당 페이지가 실제로
# 제공하는 선택 UI, (2) KOMIS 원본 JSON 입력란, (3) 분석요약 결과 — 이 세
# 요소만 남긴다. geo_events 별도 expander·"고급: KOMIS 원본값 직접 입력"
# expander·"요청 바디 미리보기" 등 부가 UI는 전부 제거.
# 2026-08-31 재지시(사용자): "광물자원가격·핵심광물지도는 fetch 버튼을
# 추가해서 komis.or.kr에서 데이터를 가져와 표시"를 요청 — 이 데모가
# inhouse/airgap 원칙과 달리 komis.or.kr을 직접 호출하는 것에 대해 사용자가
# "이 데모는 납품처 설명용, DMZ존과 같음, 납품 후 미사용"이라고 DMZ/inhouse
# 원칙 예외를 직접 승인해 구현한다(§komis_fetch.py docstring — 실제로
# komis.or.kr 실호출·실데이터까지 검증 완료). 2026-08-31 재확인(사용자 지시):
# price_iron_energy/price_other도 같은 2단계 흐름으로 실데이터가 확인돼
# KOMIS_FETCH_DISPATCH에 추가 — 이제 광물자원가격 4종+핵심광물지도 3종,
# 총 7개 페이지 전부 버튼이 뜬다.
observations_text = ""
komis_raw_text = ""
if page_id in KOMIS_RAW_PAGES:
    raw_spec = KOMIS_RAW_PAGES[page_id]
    st.caption(
        f"KOMIS 데이터 조회 결과(외부에서 조회한 원본 JSON을 붙여넣으세요) — "
        f"komis.or.kr {raw_spec.label}을 그대로 붙여넣으면 이 화면이 report_gen이 원하는 형태로 변환합니다."
    )
    # 2026-09-01 report-summary-agent 지적: 위 광종 드롭다운 값(payload["mineral"])이
    # 항상 우선이고(request.mineral or snapshot_mineral_code), 서버는 "드롭다운에서
    # 고른 광종"과 "붙여넣은 JSON이 실제로 어떤 광종 데이터인지"를 교차검증하지
    # 않는다 — 니켈을 고르고 리튬 JSON을 붙여넣으면 광종명은 니켈, 수치는 리튬인
    # 조합이 조용히 만들어질 수 있다. indicator_market/supply는 komis_snapshot_
    # response에 광종명이 들어있어 이 불일치가 특히 눈에 안 띄기 쉬워 안내를 둔다.
    if page_id in ("indicator_market", "indicator_supply"):
        st.caption("⚠ 위 광종 드롭다운 값이 붙여넣은 JSON의 실제 광종과 다르면, 광종명과 수치가 서로 다른 광종 것으로 섞여 나올 수 있습니다 — 드롭다운과 JSON을 같은 광종으로 맞춰주세요.")
    # 2026-08-31 사용자 지시: 주메뉴/서브메뉴/광종/비교광종 중 하나라도 바뀌면
    # "KOMIS 데이터 조회 결과"도 그 선택에 맞게 바뀌어야 한다 — 이전엔 위젯
    # key가 page_id에만 묶여 있어(서브메뉴는 반영됐지만) 광종·비교광종만 바꾸면
    # 예전 광종으로 실시간 조회한 결과가 그대로 남아 있었다(오해 소지). 키에
    # 광종·비교광종까지 넣어 셋 중 하나라도 바뀌면 새 위젯으로 취급되게 한다
    # (주메뉴 변경은 서브메뉴=page_id가 같이 바뀌므로 이미 커버됨).
    raw_state_key = f"komis_raw_{page_id}_{payload.get('mineral', '')}_{payload.get('compare_mineral', '')}"
    # 2026-08-31 사용자 지시: 광물자원가격 4종 공통 평균 옵션/기간 구분자/기간
    # UI — komis_fetch.py의 fetch_price_* 4종이 실제로 받는 avg_opt/period_field/
    # start_period/end_period로 그대로 넘어간다(§komis_fetch.py 라이브 실측).
    period_fetch_opts: dict = {}
    if page_id in PRICE_CATEGORY_BY_PAGE:
        opt_cols = st.columns(4)
        avg_opt_label = opt_cols[0].selectbox(
            "평균 옵션", list(AVG_OPT_LABELS), key=f"komis_avg_opt_{page_id}",
        )
        period_field_label = opt_cols[1].selectbox(
            "기간 구분자", list(PERIOD_FIELD_LABELS), key=f"komis_period_field_{page_id}",
        )
        period_field = PERIOD_FIELD_LABELS[period_field_label]
        # 2026-08-31 사용자 지시: 자유입력 대신 콤보박스로, 2000년 이후만 —
        # 기간 구분자(년간/월간)에 따라 옵션 자체가 달라지므로 key에도
        # period_field를 넣어 년간↔월간 전환 시 이전 선택값이 안 맞는 목록에
        # 그대로 남는 걸 방지한다(선택 안 한 목록으로 넘어가면 리셋).
        _today = date.today()
        if period_field == "year":
            year_options = [str(y) for y in range(2000, _today.year + 1)]
            start_period = opt_cols[2].selectbox(
                "기간 시작(YYYY)", year_options, index=0, key=f"komis_start_{page_id}_year",
            )
            end_period = opt_cols[3].selectbox(
                "기간 종료(YYYY)", year_options, index=len(year_options) - 1, key=f"komis_end_{page_id}_year",
            )
        else:
            month_options = []
            y, m = 2000, 1
            while (y, m) <= (_today.year, _today.month):
                month_options.append(f"{y:04d}-{m:02d}")
                m += 1
                if m > 12:
                    m = 1
                    y += 1
            start_period = opt_cols[2].selectbox(
                "기간 시작(YYYY-MM)", month_options, index=0, key=f"komis_start_{page_id}_month",
            )
            end_period = opt_cols[3].selectbox(
                "기간 종료(YYYY-MM)", month_options, index=len(month_options) - 1, key=f"komis_end_{page_id}_month",
            )
        period_fetch_opts = {
            "avg_opt": AVG_OPT_LABELS[avg_opt_label], "period_field": period_field,
            "start_period": start_period, "end_period": end_period,
        }
    elif page_id == "map_mineral":
        # 2026-08-31 사용자 지시: 광물지도(매장량/생산량) 기간조회 추가 — 연간,
        # 2021~2025만(komis_fetch.py fetch_map_mineral의 start_year/end_year로
        # 그대로 전달, getListMapMnrlChartData의 srchDateS/srchDateE).
        map_year_options = [str(y) for y in range(2021, 2026)]
        opt_cols = st.columns(2)
        start_year_opt = opt_cols[0].selectbox(
            "기간 시작(YYYY)", map_year_options, index=0, key=f"komis_start_{page_id}",
        )
        end_year_opt = opt_cols[1].selectbox(
            "기간 종료(YYYY)", map_year_options, index=len(map_year_options) - 1, key=f"komis_end_{page_id}",
        )
        period_fetch_opts = {"start_year": start_year_opt, "end_year": end_year_opt}
    elif page_id == "map_korea":
        # 2026-08-31 사용자 지시: 대한민국 수급지도(map_korea)에 기간 구분자
        # (년/월)·국가명 직접입력(기본 전체)·생산품 유형·HS코드 구분자 추가 —
        # komis_fetch.py의 fetch_map_korea가 실제로 받는 인자로 그대로
        # 넘어간다(§komis_fetch.py 라이브 실측: getListMttrFlow·
        # getListOnlyHsCode·getNatInfoCodeList 3개 엔드포인트 기반).
        row1 = st.columns(2)
        period_field_label = row1[0].selectbox(
            "기간 구분자", list(PERIOD_FIELD_LABELS), key=f"komis_period_field_{page_id}",
        )
        period_field = PERIOD_FIELD_LABELS[period_field_label]
        country_name = row1[1].text_input(
            "국가명(선택, 기본 전체)", value="", key=f"komis_country_{page_id}",
            placeholder="예: 중국 (비워두면 전체)",
        )
        mk_year_options = [str(y) for y in range(2021, 2027)]
        if period_field == "year":
            row2 = st.columns(2)
            start_period = row2[0].selectbox(
                "기간 시작(YYYY)", mk_year_options, index=0, key=f"komis_start_{page_id}_year",
            )
            end_period = row2[1].selectbox(
                "기간 종료(YYYY)", mk_year_options, index=len(mk_year_options) - 1, key=f"komis_end_{page_id}_year",
            )
        else:
            # 사용자 지시: "월은 년도 선택후 월 선택 가능하게" — 연도·월을
            # 각각 별도 콤보박스로 뒀다(광물자원가격의 "YYYY-MM" 단일 목록과
            # 다른 UX, 사용자가 명시적으로 요청한 2단계 흐름).
            month_options = [f"{m:02d}" for m in range(1, 13)]
            row2 = st.columns(4)
            start_year_opt = row2[0].selectbox(
                "시작 연도(YYYY)", mk_year_options, index=0, key=f"komis_start_year_{page_id}",
            )
            start_month_opt = row2[1].selectbox(
                "시작 월(MM)", month_options, index=0, key=f"komis_start_month_{page_id}",
            )
            end_year_opt = row2[2].selectbox(
                "종료 연도(YYYY)", mk_year_options, index=len(mk_year_options) - 1, key=f"komis_end_year_{page_id}",
            )
            end_month_opt = row2[3].selectbox(
                "종료 월(MM)", month_options, index=len(month_options) - 1, key=f"komis_end_month_{page_id}",
            )
            start_period = f"{start_year_opt}-{start_month_opt}"
            end_period = f"{end_year_opt}-{end_month_opt}"

        row3 = st.columns(2)
        mineral_code = payload.get("mineral", "")
        product_type_options = _cached_product_type_options(mineral_code) if mineral_code else []
        product_type_choice = row3[0].selectbox(
            "생산품 유형(선택, 기본 전체)", product_type_options, index=None, placeholder="전체",
            format_func=lambda o: o["mttrFlowNm"], key=f"komis_product_type_{page_id}_{mineral_code}",
        )
        product_type_code = product_type_choice["mttrFlowCd"] if product_type_choice else ""
        # 2026-08-31 report-summary-agent 계약 확정(커밋 6cdd18250): 생산품
        # 유형은 komis_response에 한글 라벨이 없어(코드만 echo) report_gen이
        # 선택 필드 mttr_flow_name을 신설 — 보내면 보고서 문장에 라벨을 쓰고
        # (예: "기초원료"), 안 보내면 코드로 폴백한다. period_fetch_opts와
        # 달리 이건 komis.or.kr 조회용이 아니라 report_gen 요청 바디에
        # 직접 실리는 필드라 payload에 넣는다.
        if product_type_choice:
            payload["mttr_flow_name"] = product_type_choice["mttrFlowNm"]

        hs_code_options = _cached_hs_code_options(mineral_code, product_type_code) if mineral_code else []
        hs_code_choice = row3[1].selectbox(
            "HS코드(선택, 기본 전체)", hs_code_options, index=None, placeholder="전체",
            format_func=lambda o: f"{o['itemNm']} ({o['hsCd']})",
            key=f"komis_hs_code_{page_id}_{mineral_code}_{product_type_code}",
        )
        hs_code = hs_code_choice["hsCd"] if hs_code_choice else ""

        period_fetch_opts = {
            "period_field": period_field, "start_period": start_period, "end_period": end_period,
            "country_name": country_name, "product_type_code": product_type_code, "hs_code": hs_code,
        }
    elif page_id == "map_global":
        # 2026-08-31 사용자 지시: 글로벌 수급지도(map_global)에 map_korea와
        # 같은 기간 구분자·생산품 유형·HS코드 구분자 + 수출국가/수입국가
        # 직접입력(각각) 추가 — komis_fetch.py fetch_map_global이 실제로
        # 받는 인자로 그대로 넘어간다. UI 구조는 map_korea 블록과 동일한
        # 패턴(중복이지만 페이지별 위젯 key가 달라야 해서 그대로 반복).
        row1 = st.columns(2)
        period_field_label = row1[0].selectbox(
            "기간 구분자", list(PERIOD_FIELD_LABELS), key=f"komis_period_field_{page_id}",
        )
        period_field = PERIOD_FIELD_LABELS[period_field_label]
        mg_year_options = [str(y) for y in range(2021, 2027)]
        if period_field == "year":
            row2 = st.columns(2)
            start_period = row2[0].selectbox(
                "기간 시작(YYYY)", mg_year_options, index=0, key=f"komis_start_{page_id}_year",
            )
            end_period = row2[1].selectbox(
                "기간 종료(YYYY)", mg_year_options, index=len(mg_year_options) - 1, key=f"komis_end_{page_id}_year",
            )
        else:
            month_options = [f"{m:02d}" for m in range(1, 13)]
            row2 = st.columns(4)
            start_year_opt = row2[0].selectbox(
                "시작 연도(YYYY)", mg_year_options, index=0, key=f"komis_start_year_{page_id}",
            )
            start_month_opt = row2[1].selectbox(
                "시작 월(MM)", month_options, index=0, key=f"komis_start_month_{page_id}",
            )
            end_year_opt = row2[2].selectbox(
                "종료 연도(YYYY)", mg_year_options, index=len(mg_year_options) - 1, key=f"komis_end_year_{page_id}",
            )
            end_month_opt = row2[3].selectbox(
                "종료 월(MM)", month_options, index=len(month_options) - 1, key=f"komis_end_month_{page_id}",
            )
            start_period = f"{start_year_opt}-{start_month_opt}"
            end_period = f"{end_year_opt}-{end_month_opt}"

        row3 = st.columns(2)
        export_country_name = row3[0].text_input(
            "수출국가(선택, 기본 전체)", value="", key=f"komis_export_country_{page_id}",
            placeholder="예: 칠레 (비워두면 전체)",
        )
        import_country_name = row3[1].text_input(
            "수입국가(선택, 기본 전체)", value="", key=f"komis_import_country_{page_id}",
            placeholder="예: 중국 (비워두면 전체)",
        )

        row4 = st.columns(2)
        mineral_code = payload.get("mineral", "")
        product_type_options = _cached_product_type_options(mineral_code) if mineral_code else []
        product_type_choice = row4[0].selectbox(
            "생산품 유형(선택, 기본 전체)", product_type_options, index=None, placeholder="전체",
            format_func=lambda o: o["mttrFlowNm"], key=f"komis_product_type_{page_id}_{mineral_code}",
        )
        product_type_code = product_type_choice["mttrFlowCd"] if product_type_choice else ""
        # ⚠ mttr_flow_name(라벨 필드)은 report-summary-agent 계약상 아직
        # page_id=map_korea 전용이다(2026-08-31, 커밋 6cdd18250) — map_global에
        # 그대로 보내면 report_gen이 거부한다. map_global도 필요하면 아래
        # report-summary-agent 통지 후 별도로 추가할 것, 지금은 payload에
        # 안 싣는다(생산품유형 자체 필터링은 komis.or.kr 조회에는 이미 반영됨).

        hs_code_options = _cached_hs_code_options(mineral_code, product_type_code) if mineral_code else []
        hs_code_choice = row4[1].selectbox(
            "HS코드(선택, 기본 전체)", hs_code_options, index=None, placeholder="전체",
            format_func=lambda o: f"{o['itemNm']} ({o['hsCd']})",
            key=f"komis_hs_code_{page_id}_{mineral_code}_{product_type_code}",
        )
        hs_code = hs_code_choice["hsCd"] if hs_code_choice else ""

        period_fetch_opts = {
            "period_field": period_field, "start_period": start_period, "end_period": end_period,
            "export_country_name": export_country_name, "import_country_name": import_country_name,
            "product_type_code": product_type_code, "hs_code": hs_code,
        }
    if page_id in KOMIS_FETCH_DISPATCH:
        if st.button("komis.or.kr에서 실시간 조회", key=f"komis_fetch_btn_{page_id}"):
            try:
                with st.spinner("komis.or.kr 조회 중…"):
                    fetched = KOMIS_FETCH_DISPATCH[page_id](payload, **period_fetch_opts)
            except KomisFetchError as exc:
                st.error(str(exc))
            else:
                st.session_state[raw_state_key] = json.dumps(fetched, ensure_ascii=False, indent=2)
                st.success("조회 완료 — 아래 KOMIS 데이터 조회 결과에 반영했습니다.")
    # 2026-08-31 사용자 지시: "JSON으로 표시" — 정적 예시 JSON이 들여쓰기 없는
    # 한 줄짜리 문자열이라 읽기 어려웠다(실시간 조회 결과는 이미 §위 indent=2로
    # 저장돼 문제 없었음). 기본값도 같은 형식으로 맞춘다.
    # 2026-08-31 경고 수정("created with a default value but also had its value
    # set via the Session State API"): 위 fetch 성공 분기가 이 key에 session_state
    # 를 직접 써놓고 나서 아래서 또 value= 를 넘기면 Streamlit이 충돌로 본다 —
    # value= 를 없애고, session_state에 아직 값이 없을 때만(최초 렌더) 기본값을
    # 미리 채워 넣는 표준 패턴으로 바꾼다.
    if raw_state_key not in st.session_state:
        try:
            st.session_state[raw_state_key] = json.dumps(
                json.loads(raw_spec.example_raw_json), ensure_ascii=False, indent=2
            )
        except json.JSONDecodeError:
            st.session_state[raw_state_key] = raw_spec.example_raw_json
    komis_raw_text = st.text_area(
        "KOMIS 데이터 조회 결과", height=160,
        key=raw_state_key,
    )
else:
    st.caption("observations(JSON 배열) — 계산에 쓰는 원자료. DB를 안 읽으므로 비우면 대부분 NO_DATA로 응답합니다.")
    observations_text = st.text_area("observations", value=spec.observations_example, height=140)

if st.button("분석요약 생성", type="primary"):
    if page_id in KOMIS_RAW_PAGES:
        try:
            raw = json.loads(komis_raw_text) if komis_raw_text.strip() else None
        except json.JSONDecodeError as exc:
            st.session_state["report_demo_result"] = None
            render_json_error(exc, field_label="KOMIS 데이터 조회 결과")
        else:
            if raw is None:
                st.session_state["report_demo_result"] = None
                st.error("KOMIS 데이터 조회 결과가 비어 있습니다 — 원본 JSON을 붙여넣으세요.")
            else:
                try:
                    converted = KOMIS_RAW_PAGES[page_id].convert(raw, payload)
                except KomisRawConversionError as exc:
                    st.session_state["report_demo_result"] = None
                    st.error(f"KOMIS 원본 JSON 변환 실패: {exc}")
                else:
                    payload.update(converted)
                    try:
                        with st.spinner("report_gen 호출 중…"):
                            st.session_state["report_demo_result"] = client.summarize(page_id, payload)
                    except ReportGenError as exc:
                        st.session_state["report_demo_result"] = None
                        st.error(str(exc))
    else:
        try:
            payload["observations"] = json.loads(observations_text) if observations_text.strip() else None
        except json.JSONDecodeError as exc:
            # 2026-08-28 UI/UX 감사(P0): 파싱 실패 시 이전 성공 결과를 지우지 않으면
            # 에러 배너 아래에 직전 리포트가 그대로 남아 "에러인데 결과가 나온 것"처럼
            # 보인다 — ReportGenError 분기와 동일하게 초기화.
            st.session_state["report_demo_result"] = None
            render_json_error(exc, field_label="observations")
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
        render_report_markdown(result.get("report"))
    else:
        st.warning(f"status: {status}")
        if result.get("report"):
            render_report_markdown(result["report"])
