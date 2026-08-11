# -*- coding: utf-8 -*-
"""템플릿 × 정형 조회 결과 → 리포트 본문 조립 → `out_report` 적재.

2026-08-11 구현. 설계는 `documents/meta/CONTAINER_ARCHITECTURE.md` §6 그대로다 —
**섹션→도구 매핑이 정적**(RAG처럼 매 턴 LLM이 도구를 고르지 않는다). 지금 배선된
섹션은 전부 정형(RDB) 도구다:

| 템플릿 섹션 | 출처 |
|---|---|
| 수급위기 진단 경보 | `MSR_DB.out_diagnosis_alert` (komir 산출물) |
| 12개월 수입 물량·금액 예측 | `MSR_DB.out_import_forecast` (komir 산출물) |
| 지정학 위기지수 추이 | `MSR_DB.geo_index` (komir 산출물) |
| KOMIS 공개지표(수급안정지수) | `public.KO_SPDM_STBT_INDX` (타 팀 소유, **읽기 전용**) |

비정형(VectorDB/PageIndex) 섹션은 아직 배선하지 않았다 — rag_chat의
`retrieval/unstructured.py`를 공유 라이브러리로 올리는 작업(§6 "중복 구현 금지")이
선행돼야 하고, 그건 별도 작업 소관이라 이 파일에서 rag_chat 코드를 import하거나
복제하지 않았다.

2026-08-11(2차): 정형(RDB) 질의 3종은 같은 날 rag_chat이 따로 만든 사본과 중복이었다
— §6대로 `services/shared/retrieval/structured.py`(정본)로 합치고, 여기 있던
`_latest_diagnosis`/`_import_forecast`/`_geo_index_trend`는 삭제했다. 화이트리스트와
SQL도 전부 그쪽 한 곳에만 있다. `_komis_supply_indicator`는 KOMIS 공개원천 전용이라
공유 대상이 아니어서 이 파일에 남는다.
"""
from __future__ import annotations

import hashlib
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from ._bootstrap import ensure_shared_on_path

ensure_shared_on_path()

from shared.config import get_settings  # noqa: E402
from shared.db import execute_msr, write_df_msr  # noqa: E402
from shared.retrieval.structured import (  # noqa: E402
    VALID_COMMODITIES,
    StructuredQueryError,
    check_commodity,
    geo_index_trend,
    import_forecast,
    latest_diagnosis,
)

from .analysis import DataSourceError, DatabaseIndicatorDataSource, KomisRawDataRepository  # noqa: E402

#: 발주 5광종의 한글 표기(CLAUDE.md §0 — REE 대표원소는 네오디뮴 Nd 확정).
COMMODITY_NAMES = {
    "CU": "동(구리)",
    "NI": "니켈",
    "CO": "코발트",
    "LI": "리튬",
    "REE": "희토류(네오디뮴)",
}

#: komir 광종코드 → KOMIS 광종 고유코드(`MNRKND_UNQ_CD`).
#: 2026-08-11 `search/resources/metadata`의 KOMIS 메타 스냅샷에서 확인한 값이다.
#: ⚠ 실측상 `public.KO_*`에는 텅스텐(MNRL0018) 데이터만 적재돼 있어, 아래 5개
#: 코드로 조회하면 현재는 전부 "데이터 없음"이 된다(리포트에 그대로 표기된다).
KOMIS_MINERAL_CODES = {
    "CU": "MNRL0008",
    "NI": "MNRL0002",
    "CO": "MNRL0003",
    "LI": "MNRL0001",
    "REE": "MNRL1001",
}

DEFAULT_TEMPLATE = "weekly_brief.md.j2"


class ReportGenerationError(RuntimeError):
    """리포트 생성 요청이 잘못됐거나 조립에 실패했을 때."""


def _check_commodity(commodity_code: str) -> str:
    """공용 화이트리스트(`shared.retrieval.structured`)를 태우되 예외형만 이 서비스
    계약(`ReportGenerationError` → main.py에서 HTTP 400)으로 바꿔 던진다."""

    try:
        return check_commodity(commodity_code)
    except StructuredQueryError as exc:
        raise ReportGenerationError(str(exc)) from exc


# ─────────────────── 정형(RDB) 섹션 — 조회는 shared/retrieval ───────────────────
# `latest_diagnosis`/`import_forecast`/`geo_index_trend`는 위에서 import한 공용
# 구현을 그대로 쓴다(2026-08-11 2차 통합). 여기서 감쌀 게 없어 래퍼도 두지 않는다.


def _komis_supply_indicator(code: str, months: int = 12) -> dict[str, Any]:
    """KOMIS 공개 수급안정지수(`public.KO_SPDM_STBT_INDX`) 최근 계열.

    이식한 정규화기(`analysis/data_sources/database.py`)를 그대로 태운다. 데이터가
    없으면 예외를 삼키고 사유 문구만 돌려준다 — 현재 이 테이블엔 텅스텐만 적재돼
    있어 5광종 전부 "데이터 없음"으로 나오는 게 정상이다.
    """

    mineral_code = KOMIS_MINERAL_CODES.get(code)
    if mineral_code is None:
        return {"available": False, "note": f"{code}에 대응하는 KOMIS 광종코드가 없다.", "observations": []}
    try:
        source = DatabaseIndicatorDataSource(KomisRawDataRepository())
        series = source.get_series(
            page_id="indicator_supply",
            mineral=mineral_code,
            start_month=None,
            end_month=None,
        )
    except DataSourceError as exc:
        return {
            "available": False,
            "note": f"KOMIS 공개 수급안정지수에 {code}({mineral_code}) 데이터가 없다 — {exc}",
            "observations": [],
        }
    observations = [item.model_dump() for item in series.observations][-months:]
    return {
        "available": True,
        "note": None,
        "mineral": series.mineral.model_dump(),
        "available_start_month": series.available_start_month,
        "available_end_month": series.available_end_month,
        "data_version": series.data_version[:12],
        "warnings": series.warnings,
        "observations": observations,
    }


# ─────────────────────────────── 조립·저장 ───────────────────────────────


def _template_dir() -> Path:
    """템플릿 디렉토리 — .env의 REPORT_TEMPLATE_DIR, 없으면 이 파일 옆 templates/.

    설정 기본값은 소스트리 절대경로라 컨테이너(`/app/app/templates`)에서는 맞지
    않는다 — 존재하지 않으면 모듈 상대경로로 떨어진다."""

    configured = Path(get_settings().REPORT_TEMPLATE_DIR)
    return configured if configured.is_dir() else Path(__file__).resolve().parent / "templates"


def _ymd(value: Any) -> str:
    """날짜형 값을 YYYY-MM-DD로 — DuckDB DATE는 pandas Timestamp로 올라와
    기본 str()이 '2026-06-08 00:00:00'이 된다(템플릿에 시각까지 찍히는 문제)."""

    if value is None:
        return "—"
    if isinstance(value, (datetime, date)):
        return value.strftime("%Y-%m-%d")
    return str(value)[:10]


def _jinja_env() -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(_template_dir())),
        undefined=StrictUndefined,
        autoescape=select_autoescape(enabled_extensions=("html", "xml"), default=False),
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )
    env.filters["ymd"] = _ymd
    return env


def _period_label(as_of: date) -> str:
    """out_report.period(VARCHAR(8))에 넣을 ISO 주차 라벨 — 예 '2026-W33'."""

    iso = as_of.isocalendar()
    return f"{iso[0]:04d}-W{iso[1]:02d}"


def _report_id(kind: str, code: str, period: str) -> str:
    """같은 (종류·광종·주차)면 항상 같은 id — 재실행 시 덮어쓰기 가능(≤32자)."""

    digest = hashlib.sha1(f"{kind}|{code}|{period}".encode("utf-8")).hexdigest()
    return f"rpt_{digest[:24]}"  # 4 + 24 = 28자


def build_context(commodity_code: str, *, as_of: date | None = None) -> dict[str, Any]:
    """템플릿에 넣을 섹션별 데이터를 한 번에 모은다."""

    code = _check_commodity(commodity_code)
    as_of = as_of or datetime.now(timezone.utc).date()
    return {
        "commodity_code": code,
        "commodity_name": COMMODITY_NAMES[code],
        "period": _period_label(as_of),
        "as_of": as_of.isoformat(),
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "diagnosis": latest_diagnosis(code),
        "forecast_volume": import_forecast(code, "volume"),
        "forecast_value": import_forecast(code, "value"),
        "geo_index": geo_index_trend(code, "W", 8),
        "komis_supply": _komis_supply_indicator(code),
    }


def render_report(
    commodity_code: str,
    *,
    template: str = DEFAULT_TEMPLATE,
    as_of: date | None = None,
) -> dict[str, Any]:
    """템플릿×정형데이터로 리포트 1건을 조립한다(저장은 하지 않는다)."""

    context = build_context(commodity_code, as_of=as_of)
    body = _jinja_env().get_template(template).render(**context)
    kind = "report"
    period = context["period"]
    return {
        "report_id": _report_id(kind, context["commodity_code"], period),
        "commodity_code": context["commodity_code"],
        "period": period,
        "kind": kind,
        "title": f"[{context['commodity_name']}] 수급위기 주간 브리프 ({period})",
        "body": body,
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0, tzinfo=None),
    }


def store_report(report: dict[str, Any]) -> int:
    """`out_report`에 적재한다(같은 report_id면 지우고 다시 넣어 멱등하게).

    `dbio.write_df`의 `pk=`는 DataFrame 내부 중복만 제거할 뿐 기존 행과는 대조하지
    않는다 — out_report는 report_id가 PRIMARY KEY라 재실행 시 제약 위반이 난다.
    그래서 삽입 전에 같은 id를 지운다(`execute_msr`, DuckDB `?` 자리표시자)."""

    import pandas as pd

    execute_msr("DELETE FROM out_report WHERE report_id = ?", [report["report_id"]])
    return write_df_msr(pd.DataFrame([report]), "out_report", if_exists="append", pk=["report_id"])


def generate_and_store(
    commodity_code: str,
    *,
    template: str = DEFAULT_TEMPLATE,
    as_of: date | None = None,
) -> dict[str, Any]:
    """조립 + `out_report` 적재 — API 수동 트리거와 스케줄러의 공통 진입점."""

    report = render_report(commodity_code, template=template, as_of=as_of)
    stored = store_report(report)
    return {**report, "stored_rows": stored}
