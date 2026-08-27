"""report_gen(`/api/v1/analysis/*`) 클라이언트 — Streamlit 개발 데모 전용.

2026-08-27 기준 계약(`.claude/worktrees/report_summary`에서 진행 중인 별도 세션의
최신 작업 — `services/report_gen/app/routers/analysis.py`·`analysis/models.py`):
- DB 조회 없음(prompt만 DB). 원자료는 요청 바디의 `observations`(+`mineral_name`·
  `unit`·`price_unit` 등 부속 필드)로 받는다.
- 응답은 항상 HTTP 200 + `{"status": "ok"|"NO_DATA"|"TIMEOUT"|"INTERNAL_ERROR",
  "report": "<Markdown 또는 null>"}` — 성공/실패를 status 한 필드로 겸한다.
- 9개 페이지 전부 `POST /api/v1/analysis/<path>`, 요청 바디 필드는 page_id별로
  달라(PAGE_SPECS가 그 차이를 담는다).

⚠ 다른 세션이 이 계약을 계속 바꾸는 중이다(committed 6038fead0 이후로도 uncommitted
변경 있음) — 필드가 하나라도 안 맞으면 pydantic이 `extra="forbid"`라 422로
거부한다. 실패하면 먼저 이 파일의 PAGE_SPECS가 그 세션의 최신
`routers/analysis.py`와 여전히 일치하는지부터 확인할 것."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx


class ReportGenError(RuntimeError):
    """report_gen 서버가 유효한 응답을 주지 못했을 때."""


@dataclass(frozen=True)
class PageSpec:
    """페이지 1개의 데모 폼 스펙 — 실제 검증은 서버 pydantic 모델이 하고,
    여기서는 입력 UI만 안내한다(필드 목록이 어긋나도 서버가 422로 거부할 뿐,
    이 파일이 진실 원천은 아니다)."""

    label: str
    path: str  # /api/v1/analysis/<path>
    has_mineral: bool  # False면 mineral 필드 자체가 없는 페이지(indicator_composite·price_group)
    period_fields: tuple[str, str]  # (시작 필드명, 종료 필드명) — 없으면 ("", "")
    period_kind: str  # "month" | "date" | "year" | "period" | ""
    extra_fields: tuple[str, ...]  # 페이지 고유 부속 필드(문자열 입력으로 노출)
    observations_example: str  # observations 예시 JSON(placeholder)


PAGE_SPECS: dict[str, PageSpec] = {
    "indicator_market": PageSpec(
        "시장동향지표", "market-indicator", True, ("start_month", "end_month"), "month",
        ("price_unit", "price_criterion"),
        '[{"month": "2025-08", "score": 62.5, "price": 9800.0, "crisis_flag": false}, '
        '{"month": "2025-09", "score": 58.1, "price": 9650.0, "crisis_flag": false}]',
    ),
    "indicator_supply": PageSpec(
        "수급동향지표", "supply-indicator", True, ("start_month", "end_month"), "month",
        ("price_unit", "price_criterion"),
        '[{"month": "2025-08", "score": 71.0}, {"month": "2025-09", "score": 68.4}]',
    ),
    "indicator_composite": PageSpec(
        "광물종합지수", "composite-index", False, ("start_date", "end_date"), "date",
        (),
        '[{"date": "2025-08-01", "composite_index": 105.2, "major_metals_index": 110.1, '
        '"minor_metals_index": 98.7}]',
    ),
    "map_mineral": PageSpec(
        "광물지도(매장량/생산량)", "mineral-map", True, ("start_year", "end_year"), "year",
        ("measure", "unit"),
        '[{"year": 2023, "country_code": "CL", "country_name": "칠레", "value": 5600.0}, '
        '{"year": 2023, "country_code": "PE", "country_name": "페루", "value": 2200.0}]',
    ),
    "forecast_price": PageSpec(
        "가격예측(중기/장기)", "price-forecast", True, ("start_period", "end_period"), "period",
        ("forecast_horizon", "price_unit"),
        '[{"period": "2026-Q1", "price": 9700.0}, {"period": "2026-Q2", "price": 9850.0}]',
    ),
    "price": PageSpec(
        "광물자원가격", "prices", True, ("start_date", "end_date"), "date",
        ("price_unit", "price_criterion", "price_criterion_serial"),
        '[{"date": "2025-08-25", "commerce_price": 9720.0, "lowest_price": 9680.0, '
        '"highest_price": 9760.0}]',
    ),
    "map_korea": PageSpec(
        "국내 수급지도(수출입)", "domestic-trade", True, ("start_date", "end_date"), "date",
        ("trade_direction",),
        '[{"date": "2025-08-01", "country_code": "AU", "country_name": "호주", '
        '"import_weight": 1200.0, "import_amount": 850000.0}]',
    ),
    "map_global": PageSpec(
        "글로벌 수급지도(원산지→도착지)", "global-trade", True, ("start_date", "end_date"), "date",
        (),
        '[{"date": "2025-08-01", "country_code": "DE", "country_name": "독일", '
        '"import_weight": 300.0, "import_amount": 210000.0, '
        '"origin_country_code": "US", "origin_country_name": "미국"}]',
    ),
    "price_group": PageSpec(
        "그룹 요약(비철금속/희소금속)", "price-group", False, ("", ""), "",
        ("price_group",),
        '[{"mineral_name": "니켈", "week_change_pct": 1.8, "month_change_pct": -2.3}, '
        '{"mineral_name": "구리", "week_change_pct": -0.4, "month_change_pct": 3.1}]',
    ),
}


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
            return False

    def summarize(self, page_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        """`{status, report}`를 그대로 돌려준다 — 계약상 HTTP는 항상 200이라
        raise_for_status로 못 잡는 실패는 status 필드로 구분해야 한다."""

        spec = PAGE_SPECS[page_id]
        try:
            with httpx.Client(base_url=self.base_url, timeout=self.timeout_seconds) as client:
                response = client.post(f"/api/v1/analysis/{spec.path}", json=payload)
        except httpx.RequestError as exc:
            raise ReportGenError(f"report_gen 서버({self.base_url})에 연결할 수 없습니다.") from exc
        if response.status_code == 422:
            raise ReportGenError(f"요청 검증 실패(422): {response.text[:500]}")
        if response.status_code != 200:
            raise ReportGenError(f"예상치 못한 응답({response.status_code}): {response.text[:500]}")
        return response.json()
