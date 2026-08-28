"""report_gen(`/api/v1/analysis/*`) 클라이언트 — Streamlit 개발 데모 전용.

2026-08-27 기준 계약(`.claude/worktrees/report_summary`에서 진행 중인 별도 세션의
최신 작업 — `services/report_gen/app/routers/analysis.py`·`analysis/models.py`):
- DB 조회 없음(prompt만 DB). 원자료는 요청 바디의 `observations`(+`mineral_name`·
  `unit`·`price_unit` 등 부속 필드)로 받는다.
- 응답은 항상 HTTP 200 + `{"status": "ok"|"NO_DATA"|"TIMEOUT"|"INTERNAL_ERROR",
  "report": "<Markdown 또는 null>"}` — 성공/실패를 status 한 필드로 겸한다.
- 12개 페이지 전부 `POST /api/v1/analysis/<path>`, 요청 바디 필드는 page_id별로
  달라(PAGE_SPECS가 그 차이를 담는다). 2026-08-27 `price`(광물자원가격)가 KOMIS
  실제 구조대로 `price_base_metals`(비철금속)·`price_minor_metals`(희소금속)
  2개 page_id로 분리됐다(옛 `POST /prices` 단일 경로는 제거, 404) — 9→10종.
  2026-08-28 광물자원가격 나머지 서브메뉴 `price_iron_energy`(철광석 및
  에너지)·`price_other`(기타) 2종이 추가돼 10→12종.

⚠ 다른 세션이 이 계약을 계속 바꾸는 중이다(committed 6038fead0 이후로도 uncommitted
변경 있음) — 필드가 하나라도 안 맞으면 pydantic이 `extra="forbid"`라 422로
거부한다. 실패하면 먼저 이 파일의 PAGE_SPECS가 그 세션의 최신
`routers/analysis.py`와 여전히 일치하는지부터 확인할 것."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

_log = logging.getLogger(__name__)


class ReportGenError(RuntimeError):
    """report_gen 서버가 유효한 응답을 주지 못했을 때."""


@dataclass(frozen=True)
class PageSpec:
    """페이지 1개의 데모 폼 스펙 — 실제 검증은 서버 pydantic 모델이 하고,
    여기서는 입력 UI만 안내한다(필드 목록이 어긋나도 서버가 422로 거부할 뿐,
    이 파일이 진실 원천은 아니다).

    `section`(주메뉴)은 2026-08-27 추가 — 임의 추정이 아니라
    `services/rag_chat/app/page_recommend/resources/registry/pages/*.yaml`의
    `identity.section`(주메뉴)/`identity.name`(서브메뉴)을 그대로 옮겼다. 이
    registry는 2026-07-16 KOMIS 사이트를 브라우저로 실제 프로브해 관측한 값
    (각 yaml의 `provenance.sources`에 `artifacts/browser/page-probe/pages.json`
    명시)이라 추정이 아니라 확인된 데이터다. `price`(report_gen 쪽 1개 page_id)는
    registry에서 `price_base_metals`/`price_minor_metals` 2개로 더 세분화돼
    있지만 둘 다 section="광물자원가격"로 같아 그대로 옮겼다."""

    label: str
    section: str  # 주메뉴(KOMIS 실제 내비게이션 — registry identity.section 그대로)
    path: str  # /api/v1/analysis/<path>
    has_mineral: bool  # False면 mineral 필드 자체가 없는 페이지(indicator_composite·price_group)
    period_fields: tuple[str, str]  # (시작 필드명, 종료 필드명) — 없으면 ("", "")
    period_kind: str  # "month" | "date" | "year" | "period" | ""
    extra_fields: tuple[str, ...]  # 페이지 고유 부속 필드(문자열 입력으로 노출)
    observations_example: str  # observations 예시 JSON(placeholder)


PAGE_SPECS: dict[str, PageSpec] = {
    "indicator_market": PageSpec(
        "시장동향지표", "광물전망지표", "market-indicator", True, ("start_month", "end_month"), "month",
        ("price_unit", "price_criterion"),
        '[{"month": "2025-08", "score": 62.5, "price": 9800.0, "crisis_flag": false}, '
        '{"month": "2025-09", "score": 58.1, "price": 9650.0, "crisis_flag": false}]',
    ),
    "indicator_supply": PageSpec(
        "수급동향지표", "광물전망지표", "supply-indicator", True, ("start_month", "end_month"), "month",
        ("price_unit", "price_criterion"),
        '[{"month": "2025-08", "score": 71.0}, {"month": "2025-09", "score": 68.4}]',
    ),
    "indicator_composite": PageSpec(
        "광물종합지수", "광물전망지표", "composite-index", False, ("start_date", "end_date"), "date",
        (),
        '[{"date": "2025-08-01", "composite_index": 105.2, "major_metals_index": 110.1, '
        '"minor_metals_index": 98.7}]',
    ),
    "map_mineral": PageSpec(
        # 2026-08-28 UI/UX 감사에서 1차로 연도를 2022/2023 두 개로 분리했지만(연도
        # 개수≥2 요건), 2026-08-29 report-summary-agent가 재확인한 서버 요건
        # "최신연도(2023) 기준 국가 수≥3"까지는 못 채워 여전히 NO_DATA였다 —
        # 2023년을 칠레·페루·콩고민주공화국 3개국으로 확장.
        "광물지도(매장량/생산량)", "핵심광물지도", "mineral-map", True, ("start_year", "end_year"), "year",
        ("measure", "unit"),
        '[{"year": 2022, "country_code": "CL", "country_name": "칠레", "value": 5400.0}, '
        '{"year": 2023, "country_code": "CL", "country_name": "칠레", "value": 5600.0}, '
        '{"year": 2023, "country_code": "PE", "country_name": "페루", "value": 2200.0}, '
        '{"year": 2023, "country_code": "CD", "country_name": "콩고민주공화국", "value": 1800.0}]',
    ),
    "forecast_price": PageSpec(
        # 2026-08-29: is_actual(KOMIS realYn 대응, True=확정 실적/False=예측치)이
        # 신설됐는데 예시가 안 보여줘서 하나씩 섞어 필터링 동작을 데모에서도
        # 보여준다(main-agent 요청). 계산기가 is_actual=true 관측치를 예측
        # 요약에서 제외하므로(models.py PriceForecastObservation 주석) 2개만
        # 섞으면 예측치가 1개만 남아 NO_DATA — 실측 1 + 예측 2로 확장(실측 확인).
        "가격예측(중기/장기)", "광물전망지표", "price-forecast", True, ("start_period", "end_period"), "period",
        ("forecast_horizon", "price_unit"),
        '[{"period": "2026-Q1", "price": 9700.0, "is_actual": true}, '
        '{"period": "2026-Q2", "price": 9850.0, "is_actual": false}, '
        '{"period": "2026-Q3", "price": 9920.0, "is_actual": false}]',
    ),
    "price_base_metals": PageSpec(
        # 2026-08-29: inventory(재고량, 선택) 신설 — 예시에 반영.
        "비철금속", "광물자원가격", "prices/base-metals", True, ("start_date", "end_date"), "date",
        ("price_unit", "price_criterion", "price_criterion_serial"),
        '[{"date": "2025-08-25", "commerce_price": 9720.0, "lowest_price": 9680.0, '
        '"highest_price": 9760.0, "inventory": 15000.0}]',
    ),
    "price_minor_metals": PageSpec(
        # compare_mineral/compare_price_criterion: KOMIS "비교광종" 기능 대응,
        # 이 page_id 전용(다른 page_id로 보내면 서버가 거부). compare_observations
        # (비교 계열 원자료 JSON)는 이 데모의 observations 텍스트영역과 별개라
        # 1차 범위에서 뺐다 — 필요해지면 별도 textarea로 추가.
        # 2026-08-29: inventory(재고량, 선택) 신설 — 예시에 반영.
        "희소금속", "광물자원가격", "prices/minor-metals", True, ("start_date", "end_date"), "date",
        ("price_unit", "price_criterion", "price_criterion_serial", "compare_mineral", "compare_price_criterion"),
        '[{"date": "2025-08-25", "commerce_price": 9720.0, "lowest_price": 9680.0, '
        '"highest_price": 9760.0, "inventory": 15000.0}]',
    ),
    "price_iron_energy": PageSpec(
        # 2026-08-29: inventory(재고량, 선택) 신설 — 예시에 반영.
        "철광석 및 에너지", "광물자원가격", "prices/iron-energy", True, ("start_date", "end_date"), "date",
        ("price_unit", "price_criterion", "price_criterion_serial"),
        '[{"date": "2025-08-25", "commerce_price": 9720.0, "lowest_price": 9680.0, '
        '"highest_price": 9760.0, "inventory": 15000.0}]',
    ),
    "price_other": PageSpec(
        # 2026-08-29: inventory(재고량, 선택) 신설 — 예시에 반영.
        "기타", "광물자원가격", "prices/other", True, ("start_date", "end_date"), "date",
        ("price_unit", "price_criterion", "price_criterion_serial"),
        '[{"date": "2025-08-25", "commerce_price": 9720.0, "lowest_price": 9680.0, '
        '"highest_price": 9760.0, "inventory": 15000.0}]',
    ),
    "map_korea": PageSpec(
        "국내 수급지도(수출입)", "핵심광물지도", "domestic-trade", True, ("start_date", "end_date"), "date",
        ("trade_direction",),
        '[{"date": "2025-08-01", "country_code": "AU", "country_name": "호주", '
        '"import_weight": 1200.0, "import_amount": 850000.0}]',
    ),
    "map_global": PageSpec(
        "글로벌 수급지도(원산지→도착지)", "핵심광물지도", "global-trade", True, ("start_date", "end_date"), "date",
        (),
        '[{"date": "2025-08-01", "country_code": "DE", "country_name": "독일", '
        '"import_weight": 300.0, "import_amount": 210000.0, '
        '"origin_country_code": "US", "origin_country_name": "미국"}]',
    ),
    "price_group": PageSpec(
        "그룹 요약(비철금속/희소금속)", "광물자원가격", "price-group", False, ("", ""), "",
        ("price_group",),
        '[{"mineral_name": "니켈", "week_change_pct": 1.8, "month_change_pct": -2.3}, '
        '{"mineral_name": "구리", "week_change_pct": -0.4, "month_change_pct": 3.1}]',
    ),
}


EXTRA_FIELD_LABELS: dict[str, str] = {
    # 2026-08-28 UI/UX 감사에서 발견: "페이지 고유 필드"가 API 필드명 그대로 라벨로
    # 노출돼(measure, trade_direction 등) 나머지 한국어 UI와 어긋났다 — 한글 라벨 매핑.
    "price_unit": "가격 단위(price_unit)",
    "price_criterion": "가격 기준(price_criterion)",
    "price_criterion_serial": "가격 기준 일련번호(price_criterion_serial)",
    "measure": "측정지표(measure)",
    "unit": "단위(unit)",
    "forecast_horizon": "예측기간(forecast_horizon)",
    "trade_direction": "수출입방향(trade_direction)",
    "price_group": "가격 그룹(price_group)",
    "compare_mineral": "비교광종(compare_mineral)",
    "compare_price_criterion": "비교 가격기준(compare_price_criterion)",
}

EXTRA_FIELD_DEFAULTS: dict[str, str] = {
    # 2026-08-29 report-summary-agent 확정: map_mineral의 unit이 빈 text_input이라
    # 버튼만 누르면 payload에 키 자체가 안 들어가 서버가 "unit in the request body"
    # NO_DATA를 던졌다 — 기본값을 채워 즉시 status:ok 재현되게 한다.
    "unit": "천톤",
}

EXTRA_FIELD_VALUE_LABELS: dict[str, dict[str, str]] = {
    "measure": {"reserves": "매장량(reserves)", "production": "생산량(production)"},
    "forecast_horizon": {"medium": "중기(medium)", "long": "장기(long)"},
    "trade_direction": {"import": "수입(import)", "export": "수출(export)"},
    "price_group": {"base_metals": "비철금속(base_metals)", "minor_metals": "희소금속(minor_metals)"},
}

MAP_KOREA_OBSERVATIONS_BY_DIRECTION: dict[str, str] = {
    # 2026-08-29 main-agent 요청: trade_direction=수출 선택 시 observations 예시가
    # 수입 필드(import_*) 그대로 고정돼 사용자가 직접 고쳐야 했다 — 방향에 맞는
    # 예시로 동적 전환.
    "import": '[{"date": "2025-08-01", "country_code": "AU", "country_name": "호주", '
    '"import_weight": 1200.0, "import_amount": 850000.0}]',
    "export": '[{"date": "2025-08-01", "country_code": "AU", "country_name": "호주", '
    '"export_weight": 800.0, "export_amount": 620000.0}]',
}


@dataclass(frozen=True)
class AdvancedJsonField:
    """"고급: KOMIS 원본값 직접 입력(선택)" expander 안 JSON 입력란 1개 스펙 —
    2026-08-29 main-agent 요청(geo_events·komis_period_comparisons·
    komis_trade_totals). 값을 지어내지 않고 사용자가 입력한 값을 그대로
    report_gen에 전달하는 통로만 만든다 — 비어있으면 payload에 안 넣는다."""

    field: str
    label: str
    placeholder: str


_GEO_EVENTS_FIELD = AdvancedJsonField(
    "geo_events",
    "가격변동 주요요인(geo_events, 리스트)",
    # 2026-08-29 main-agent 확정: komir_summary.py::_PRICE_DRIVER_MIN_SEVERITY=2.0
    # 미만은 "주요" 요인으로 안 보고 걸러진다 — 처음 넣은 0.6은 문턱 미달이라
    # 리포트에 전혀 반영되지 않았다(서버 버그 아님). 실제 검증에 쓴 값과 동일하게
    # 2.8로 맞춤(재현성).
    '[{"obs_date": "2025-08-20", "country": "칠레", "direction": "supply_down", '
    '"severity": 2.8, "evidence_quote": "칠레 대형 광산 파업으로 공급 차질"}]',
)
_KOMIS_PERIOD_COMPARISONS_FIELD = AdvancedJsonField(
    "komis_period_comparisons",
    "KOMIS 기간평균(komis_period_comparisons, 객체)",
    '{"week": {"average_price": 9700.0, "change_pct": 0.98}, '
    '"month": {"average_price": 9550.0, "change_pct": 1.75}, '
    '"year": {"average_price": 9200.0, "change_pct": 4.5}}',
)
_KOMIS_TRADE_TOTALS_FIELD = AdvancedJsonField(
    "komis_trade_totals",
    "KOMIS 실제 총액(komis_trade_totals, 객체)",
    '{"import_amount": 1250000.0, "import_weight": 1800.0, '
    '"export_amount": 300000.0, "export_weight": 450.0}',
)

ADVANCED_JSON_FIELDS: dict[str, tuple[AdvancedJsonField, ...]] = {
    "price_base_metals": (_GEO_EVENTS_FIELD, _KOMIS_PERIOD_COMPARISONS_FIELD),
    "price_minor_metals": (_GEO_EVENTS_FIELD, _KOMIS_PERIOD_COMPARISONS_FIELD),
    "price_iron_energy": (_GEO_EVENTS_FIELD, _KOMIS_PERIOD_COMPARISONS_FIELD),
    "price_other": (_GEO_EVENTS_FIELD, _KOMIS_PERIOD_COMPARISONS_FIELD),
    "map_korea": (_KOMIS_TRADE_TOTALS_FIELD,),
    "map_global": (_KOMIS_TRADE_TOTALS_FIELD,),
}


def _load_section_order() -> list[str]:
    """`komis_menu_map.yaml`(같은 디렉토리, KOMIS 실제 사이트맵 캡처 기반 —
    파일 상단 주석 참고)의 `komis_site_map` top-level 키 순서를 그대로 돌려준다.
    prompt_admin.py·report_demo.py의 주메뉴 콤보박스 정렬 기준(2026-08-27,
    사용자 요청 — 두 화면이 PAGE_SPECS dict 등록 순서로 제각각 보이던 문제).
    파일이 없거나 파싱 실패하면 빈 리스트를 돌려주고, 호출부가 PAGE_SPECS 발견
    순서로 폴백한다(화면이 죽지 않게)."""

    import yaml

    path = Path(__file__).resolve().parent / "komis_menu_map.yaml"
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return list(data["komis_site_map"])
    except (OSError, yaml.YAMLError, KeyError, TypeError):
        return []


SECTION_ORDER: list[str] = _load_section_order()


def client_from_env() -> "ReportGenClient":
    import os

    base_url = os.getenv("KOMIR_REPORT_GEN_BASE_URL", "http://localhost:18003")
    timeout = float(os.getenv("KOMIR_REPORT_GEN_TIMEOUT_SECONDS", "30"))
    return ReportGenClient(base_url, timeout_seconds=timeout)


class ReportGenClient:
    def __init__(self, base_url: str, *, timeout_seconds: float = 30.0) -> None:
        normalized = base_url.strip().rstrip("/")
        if not normalized:
            raise ValueError("base_url must not be empty")
        self.base_url = normalized
        self.timeout_seconds = timeout_seconds

    def health(self) -> bool:
        try:
            with httpx.Client(base_url=self.base_url, timeout=2.0) as client:
                response = client.get("/healthz")
                response.raise_for_status()
            return response.status_code == 200
        except httpx.HTTPError:
            _log.debug("report_gen health check 실패(base_url=%s)", self.base_url, exc_info=True)
            return False

    def summarize(self, page_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        """`{status, report}`를 그대로 돌려준다 — 계약상 HTTP는 항상 200이라
        raise_for_status로 못 잡는 실패는 status 필드로 구분해야 한다."""

        spec = PAGE_SPECS[page_id]
        try:
            with httpx.Client(base_url=self.base_url, timeout=self.timeout_seconds) as client:
                response = client.post(f"/api/v1/analysis/{spec.path}", json=payload)
        except httpx.RequestError as exc:
            _log.warning("report_gen 연결 실패(page_id=%s, base_url=%s): %s", page_id, self.base_url, exc)
            raise ReportGenError(f"report_gen 서버({self.base_url})에 연결할 수 없습니다.") from exc
        if response.status_code == 422:
            _log.warning("report_gen 요청 검증 실패(page_id=%s, 422): %s", page_id, response.text[:500])
            raise ReportGenError(f"요청 검증 실패(422): {response.text[:500]}")
        if response.status_code != 200:
            _log.warning(
                "report_gen 예상치 못한 응답(page_id=%s, status=%s): %s",
                page_id, response.status_code, response.text[:500],
            )
            raise ReportGenError(f"예상치 못한 응답({response.status_code}): {response.text[:500]}")
        result = response.json()
        if result.get("status") != "ok":
            _log.info("report_gen 분석요약 status!=ok(page_id=%s): %s", page_id, result.get("status"))
        return result


CORE_MINERAL_CODES: tuple[str, ...] = ("MNRL0008", "MNRL0002", "MNRL0003", "MNRL0001", "MNRL1001")
"""프로젝트 5대 핵심광물(구리·니켈·코발트·리튬·네오디뮴=REE 대표원소) 코드
(public.ai_mnrl_mst 2026-08-28 실측 확인) — 광종 드롭다운 기본 정렬용."""


def prioritize_core_minerals(options: list[dict]) -> list[dict]:
    """드롭다운을 열자마자 5대 핵심광물이 먼저 보이도록 앞으로 끌어올린다(2026-08-28
    UI/UX 감사 — 기본 선택값이 "텅스텐"처럼 프로젝트와 무관한 광종으로 뜨는 문제).
    나머지 광종은 기존 sort_ordr 순서를 그대로 유지한다."""
    core = [m for code in CORE_MINERAL_CODES for m in options if m["code"] == code]
    rest = [m for m in options if m["code"] not in CORE_MINERAL_CODES]
    return core + rest


def parse_advanced_json_fields(page_id: str, texts: dict[str, str]) -> tuple[dict[str, Any], bool]:
    """`ADVANCED_JSON_FIELDS[page_id]`의 각 입력란 원문(texts)을 파싱한다 — 빈
    입력은 건너뛰고(안 보냄), 파싱 실패는 그 자리에 `render_json_error`로
    바로 그려서 호출부는 `ok`만 보고 제출 여부를 결정하면 된다."""
    result: dict[str, Any] = {}
    ok = True
    for spec in ADVANCED_JSON_FIELDS.get(page_id, ()):
        text = texts.get(spec.field, "")
        if not text.strip():
            continue
        try:
            result[spec.field] = json.loads(text)
        except json.JSONDecodeError as exc:
            render_json_error(exc, field_label=spec.label)
            ok = False
    return result, ok


def render_json_error(exc: Exception, *, field_label: str = "observations") -> None:
    """JSON 파싱 실패를 report_demo.py·prompt_admin.py 양쪽에서 같은 톤으로 보여준다
    (2026-08-28 UI/UX 감사 — Python 예외 원문이 그대로 노출돼 비개발자 데모 관객에게
    불친절하다는 지적 반영). 원문은 접어서 필요할 때만 보이게 한다."""
    import streamlit as st

    st.error(f"{field_label} JSON 형식이 올바르지 않습니다 — 쉼표·따옴표 등을 확인하세요.")
    with st.expander("원본 오류 메시지(디버깅용)"):
        st.code(str(exc), language=None)


def render_report_markdown(report: str | None) -> None:
    """report_gen이 돌려준 마크다운을 페이지 제목보다 크게 보이지 않도록 감싸서
    렌더링한다(2026-08-28 UI/UX 감사 — 응답 본문이 `# 제목`으로 시작해 h1이 페이지
    타이틀보다 커 보이는 문제). 헤딩 레벨을 한 단계씩 낮춘 뒤 테두리 컨테이너에 담는다."""
    import re

    import streamlit as st

    text = report or "_(빈 보고서)_"
    demoted = re.sub(r"(?m)^(#{1,5})(\s)", r"#\1\2", text)
    with st.container(border=True):
        st.markdown(demoted)
