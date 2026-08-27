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
        # 2026-08-28 UI/UX 감사(report-summary-agent 검증분 이관)에서 발견: 두 관측치가
        # 모두 year=2023이라 서버 최소요건(연도 2개 이상)을 못 채워 항상 NO_DATA로
        # 응답했다 — 연도를 2022/2023으로 분리.
        "광물지도(매장량/생산량)", "핵심광물지도", "mineral-map", True, ("start_year", "end_year"), "year",
        ("measure", "unit"),
        '[{"year": 2022, "country_code": "CL", "country_name": "칠레", "value": 5400.0}, '
        '{"year": 2023, "country_code": "CL", "country_name": "칠레", "value": 5600.0}, '
        '{"year": 2023, "country_code": "PE", "country_name": "페루", "value": 2200.0}]',
    ),
    "forecast_price": PageSpec(
        "가격예측(중기/장기)", "광물전망지표", "price-forecast", True, ("start_period", "end_period"), "period",
        ("forecast_horizon", "price_unit"),
        '[{"period": "2026-Q1", "price": 9700.0}, {"period": "2026-Q2", "price": 9850.0}]',
    ),
    "price_base_metals": PageSpec(
        "비철금속", "광물자원가격", "prices/base-metals", True, ("start_date", "end_date"), "date",
        ("price_unit", "price_criterion", "price_criterion_serial"),
        '[{"date": "2025-08-25", "commerce_price": 9720.0, "lowest_price": 9680.0, '
        '"highest_price": 9760.0}]',
    ),
    "price_minor_metals": PageSpec(
        # compare_mineral/compare_price_criterion: KOMIS "비교광종" 기능 대응,
        # 이 page_id 전용(다른 page_id로 보내면 서버가 거부). compare_observations
        # (비교 계열 원자료 JSON)는 이 데모의 observations 텍스트영역과 별개라
        # 1차 범위에서 뺐다 — 필요해지면 별도 textarea로 추가.
        "희소금속", "광물자원가격", "prices/minor-metals", True, ("start_date", "end_date"), "date",
        ("price_unit", "price_criterion", "price_criterion_serial", "compare_mineral", "compare_price_criterion"),
        '[{"date": "2025-08-25", "commerce_price": 9720.0, "lowest_price": 9680.0, '
        '"highest_price": 9760.0}]',
    ),
    "price_iron_energy": PageSpec(
        "철광석 및 에너지", "광물자원가격", "prices/iron-energy", True, ("start_date", "end_date"), "date",
        ("price_unit", "price_criterion", "price_criterion_serial"),
        '[{"date": "2025-08-25", "commerce_price": 9720.0, "lowest_price": 9680.0, '
        '"highest_price": 9760.0}]',
    ),
    "price_other": PageSpec(
        "기타", "광물자원가격", "prices/other", True, ("start_date", "end_date"), "date",
        ("price_unit", "price_criterion", "price_criterion_serial"),
        '[{"date": "2025-08-25", "commerce_price": 9720.0, "lowest_price": 9680.0, '
        '"highest_price": 9760.0}]',
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

EXTRA_FIELD_VALUE_LABELS: dict[str, dict[str, str]] = {
    "measure": {"reserves": "매장량(reserves)", "production": "생산량(production)"},
    "forecast_horizon": {"medium": "중기(medium)", "long": "장기(long)"},
    "trade_direction": {"import": "수입(import)", "export": "수출(export)"},
    "price_group": {"base_metals": "비철금속(base_metals)", "minor_metals": "희소금속(minor_metals)"},
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
