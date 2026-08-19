# -*- coding: utf-8 -*-
"""분석요약 5종의 최종 결과를 `out_report`에 적재한다.

2026-08-13 이식 시점엔 `AnalysisSummaryService.analyze()`가 응답을 돌려주기만
하고 아무것도 저장하지 않았다(호출→HTTP 응답, 끝) — `CONTAINER_ARCHITECTURE.md`
§4가 "Report 생성기 ... `out_report` 스키마만 존재 — 이걸 확장해서 쓴다"라고
이미 정해둔 대로, 주간 리포트(`generator.py`)와 같은 테이블·같은 멱등 적재 방식을
그대로 따른다(`kind`만 'report' 대신 'summary'). 새 테이블을 만들지 않는다.

레코드 식별자는 자체 해시를 새로 만들지 않고 엔진이 이미 계산해 응답에 담아
돌려주는 `filter_hash`(page_id+applied_filters의 sha256)를 그대로 쓴다 — 같은
(페이지·광종·필터)로 다시 호출하면 같은 report_id로 덮어써 멱등하다.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .._bootstrap import ensure_shared_on_path

ensure_shared_on_path()

from shared.db import execute_msr, write_df_msr  # noqa: E402

from .models import AnalysisSummaryRequest, AnalysisSummaryResponse  # noqa: E402

#: page_id → 리포트 제목에 쓸 한글 라벨.
_PAGE_TITLES = {
    "indicator_market": "시장동향지표 분석요약",
    "indicator_supply": "수급동향지표 분석요약",
    "indicator_composite": "광물종합지수 분석요약",
    "map_mineral": "광물지도 분석요약",
    "forecast_price": "가격예측 분석요약",
}


def summary_report_id(response: AnalysisSummaryResponse) -> str:
    """같은 (page_id·광종·필터)면 항상 같은 id(≤32자, `out_report.report_id` PK)."""

    return f"ans_{response.filter_hash[:24]}"  # 4 + 24 = 28자


def to_report_row(response: AnalysisSummaryResponse) -> dict[str, Any]:
    """`AnalysisSummaryResponse`를 `out_report` 행 모양으로 변환한다(저장은 안 함).

    본문은 전체 구조(등급·지표·데이터품질·근거문장 등)를 잃지 않도록 응답 전체를
    JSON으로 직렬화해 담는다 — `out_diagnosis_alert.evidence_json`과 같은 관례."""

    title_base = _PAGE_TITLES[response.page_id]
    return {
        "report_id": summary_report_id(response),
        "commodity_code": response.mineral.code,
        "period": response.source.as_of,
        "kind": "summary",
        "title": f"[{response.mineral.name}] {title_base}",
        "body": response.model_dump_json(),
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0, tzinfo=None),
    }


def store_summary(response: AnalysisSummaryResponse) -> int:
    """`out_report`에 적재한다(같은 report_id면 지우고 다시 넣어 멱등하게).

    `generator.store_report()`와 같은 이유로 삽입 전 삭제한다 — `write_df_msr`의
    `pk=`는 DataFrame 내부 중복만 제거할 뿐 기존 행과는 대조하지 않는다."""

    import pandas as pd

    row = to_report_row(response)
    execute_msr("DELETE FROM out_report WHERE report_id = ?", [row["report_id"]])
    return write_df_msr(pd.DataFrame([row]), "out_report", if_exists="append", pk=["report_id"])


def analyze_and_store(service: Any, request: AnalysisSummaryRequest) -> AnalysisSummaryResponse:
    """분석 실행 + `out_report` 적재 — 라우터의 공통 진입점.

    응답 모델(`AnalysisSummaryResponse`)은 외부repo 계약 그대로 유지해야 해서
    `stored_rows` 같은 필드를 덧붙이지 않는다(저장은 부수효과)."""

    response = service.analyze(request)
    store_summary(response)
    return response
