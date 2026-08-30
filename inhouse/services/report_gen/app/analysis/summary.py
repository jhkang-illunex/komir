# -*- coding: utf-8 -*-
"""검증된 계산 + LLM 분석문 생성 서비스 — 외부 저장소
`komis_report_generator/analysis/summary.py` 이식본(2026-08-13).

5개 분석요약 엔드포인트(시장동향지표·수급동향지표·광물종합지수·광물지도·가격예측)가
전부 이 파일의 `AnalysisSummaryService.analyze()` 하나로 들어온다.

**원본에서 바뀐 것 3가지**

1. **LLM 클라이언트**: `search.llm.JsonLLM`(httpx 기반 별도 구현) →
   `services/shared/llm_client.KomirJsonLLM`. 두 타입은 `invoke(task=, instructions=,
   payload=, output_model=, max_tokens=) -> LLMInvocation` 시그니처가 같게 설계돼
   있어 호출부는 손대지 않았다(`rag_chat`의 `page_recommend/graph.py`가 8/11에 쓴
   같은 방식 — LLM 호출 클라이언트를 2벌 만들지 않는다).
2. **import 경로**: 절대(`komis_report_generator.analysis.*`) → 상대(`.`).
3. **`_refine_with_llm`의 예외 처리 범위**(⚠ 실질적 차이): 원본은 `LLMError`만
   잡는다. 그런데 komir의 `KomirJsonLLM`은 JSON 파싱·스키마 검증 실패만
   `LLMOutputError(LLMError)`로 바꾸고, 그 아래 `OpenAICompatChat.complete()`가
   내는 **전송 계층 오류는 그대로 통과시킨다**(실측: 재시도 소진 시 맨
   `RuntimeError`, 타임아웃·커넥션 오류는 `requests.RequestException`). 그대로
   두면 vLLM이 죽었을 때 규칙기반 요약으로 우아하게 물러나지 않고 API가 500을
   낸다 — 그래서 `RuntimeError`/`OSError`까지 잡아 원본이 의도한 폴백 동작을
   유지한다(`LLMError`·`requests.RequestException`이 각각 그 하위형이다).
4. **komir 자체 3종 추가(2026-08-19, 이식 아님 — 2026-08-26 LLM 배선 추가)**:
   `price`·`map_korea`·`map_global`(광물자원가격·국내/글로벌 수급지도) 디스패치를
   추가했다. 원본은 이 3종을 501 스텁으로만 뒀지 `analyze()`에 분기가 없다 —
   `_analyze_price`/`_analyze_domestic_trade`/`_analyze_global_trade`는 komir가
   새로 짠 것이고, 계산은 `komir_summary.py`(별도 파일, `additional_summary.py`와
   안 섞음)를 쓴다. 2026-08-19 최초 추가 때는 `prompts.py`(이식본)에 이 3종용
   프롬프트·검증계약이 없어 `_refine_with_llm`을 안 태우고 규칙기반 응답만
   돌려줬다. **2026-08-26 발주처 KOMIS 템플릿 PDF(`income_data/komis/`)를
   근거로 이 3종 전용 지시문·output_contract를 `prompts.py`에 마련하고
   `_refine_with_llm`을 태우도록 배선했다** — 이 과정에서 `komir_summary.py::
   calculate_price_summary`의 core_diagnosis 근거 id가 다른 7종과 다르게
   `"latest_price"`였던 걸 `"current_state"`로 맞췄다(`_validate_llm_summary`가
   "core_diagnosis에 current_state가 있어야 한다"를 페이지 무관 공통 규칙으로
   검사하는데, 예전엔 이 3종이 LLM을 안 태워 이 불일치가 드러나지 않았다).

계산 로직·검증 규칙(`_validate_llm_summary`)·문구는 원본 그대로다(포터 5종 한정 —
komir 자체 3종은 위 4번대로 komir가 새로 마련했다).
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Literal

from pydantic import ValidationError

from .._bootstrap import ensure_shared_on_path

ensure_shared_on_path()

from shared.llm_client import KomirJsonLLM, LLMError  # noqa: E402

from .budget import ANALYSIS_LLM_TIMEOUT_SECONDS  # noqa: E402
from .additional_summary import (  # noqa: E402
    AdditionalCalculatedSummary,
    EvidenceClaim,
    SummaryPageContext,
    calculate_composite_summary,
    calculate_mineral_map_summary,
    calculate_price_forecast_summary,
)
from .data_sources import (  # noqa: E402
    CompositeIndexDataSource,
    DataSourceError,
    DomesticTradeDataSource,
    GlobalTradeDataSource,
    IndicatorDataSource,
    MineralMapDataSource,
    PriceDataSource,
    PriceForecastDataSource,
)
from .indicators import months_are_contiguous, percent_change  # noqa: E402
from .komir_summary import (  # noqa: E402
    calculate_domestic_trade_summary,
    calculate_global_trade_summary,
    calculate_price_group_summary,
    calculate_price_summary,
)
from .models import (  # noqa: E402
    AnalysisSummaryRequest,
    AnalysisSummaryResponse,
    CompositeIndexObservation,
    CompositeIndexSeries,
    DataQuality,
    DetectedPattern,
    GeoEventObservation,
    GradeResult,
    IndicatorObservation,
    IndicatorSeries,
    Metric,
    MineralMapObservation,
    MineralMapSeries,
    MineralRef,
    OmittedIndicator,
    PriceForecastObservation,
    PriceForecastSeries,
    PriceGroupMineralObservation,
    PriceKomisPeriodComparisons,
    PriceObservation,
    PriceSeries,
    SourceInfo,
    SummaryNarrative,
    SummaryPageId,
    SummarySentence,
    SupplyAuxiliaryData,
    TradeCountryObservation,
    TradeKomisTotals,
    TradeMapSeries,
)
from .policy import PagePolicy, load_page_policy  # noqa: E402
from .prompts import (  # noqa: E402
    apply_page_config,
    build_summary_payload,
    effective_page_context,
    resolve_page_config,
    summary_instructions,
)

SectionId = Literal["core_diagnosis", "major_changes", "current_position"]


def _calculate_or_no_data(page_id: str, calculate, /, *args, **kwargs):
    """`calculate_*`가 데이터 조건 미충족(관측 1건뿐·국가 3개 미만·총액 0 등)으로
    던지는 `ValueError`를 `DataSourceError`(→ 응답 `NO_DATA`)로 바꾼다.

    2026-08-27 skeptic 감사(SC-003)에서 실측: 이 ValueError들이 그대로 새어
    `routers/_common.py`에서 스택트레이스+`INTERNAL_ERROR`로 보고돼, "코드가
    죽었다"는 신호(G2 게이트)와 정당한 데이터 부족이 구분되지 않았다. pydantic
    `ValidationError`도 ValueError 하위형이지만 그건 응답 모델 조립 실패 = 진짜
    코드 버그이므로 그대로 통과시킨다(INTERNAL_ERROR로 남아야 게이트가 잡는다)."""

    try:
        return calculate(*args, **kwargs)
    except ValidationError:
        raise
    except ValueError as exc:
        raise DataSourceError(f"{page_id}: 요청 데이터로는 요약을 계산할 수 없다 — {exc}") from exc


def _data_version(payload: object) -> str:
    """요청 바디 observations의 내용 해시 — DB판 `data_sources/_shared._version`과
    같은 목적(캐시/변경감지용 지문)이지만, 이제 DB를 안 거치니 여기서 자체 계산한다."""

    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def _observations_from_request(
    observation_cls,
    request: AnalysisSummaryRequest,
    *,
    raw: list[dict] | None = None,
    field_name: str = "observations",
):
    """요청 바디의 observations(dict 리스트)를 페이지별 Observation 모델로 검증한다.

    2026-08-26: "DB에서 값을 로딩하지 않는다"는 원칙 전환 이후, 계산에 쓰는
    원자료는 전부 이 경로로 들어온다 — DB DataSource가 하던 일(원천 조회)을
    호출자가 요청 바디에 실어 보내는 것으로 대체했다(옛 DB 조회 경로는
    `data_sources/`에 그대로 남겨 뒀고, 이 서비스에서 호출부만 주석 처리했다 —
    WORKLOG 2026-08-26 참고). `raw`/`field_name`은 `price` 페이지의
    `compare_observations`(비교광종, KOMIS 원본의 `compareMnrl`에 대응)처럼
    `observations` 외 다른 필드도 같은 방식으로 검증할 때 쓴다."""

    payload = raw if raw is not None else request.observations
    if not payload:
        raise DataSourceError(
            f"{request.page_id}: 요청 바디에 {field_name}가 없다 — "
            "DB 조회 대신 요청에 원자료를 실어 보내야 한다(2026-08-26 이후 계약)."
        )
    try:
        return [observation_cls.model_validate(item) for item in payload]
    except Exception as exc:  # noqa: BLE001 — pydantic ValidationError 등을 422로 통일
        raise DataSourceError(
            f"{request.page_id}: {field_name} 형식이 {observation_cls.__name__}과 맞지 않는다: {exc}"
        ) from exc


def _geo_events_from_request(request: AnalysisSummaryRequest) -> list[GeoEventObservation] | None:
    """`request.geo_events`(선택 필드, PDF §1-1 "가격 변동의 주요 요인" 대응)를
    검증한다. `_observations_from_request`와 달리 **없으면 에러가 아니라 그냥
    None**이다 — 하위호환 필드라 안 보내는 요청이 정상이다(2026-08-28 신설)."""

    if not request.geo_events:
        return None
    try:
        return [GeoEventObservation.model_validate(item) for item in request.geo_events]
    except Exception as exc:  # noqa: BLE001 — pydantic ValidationError 등을 NO_DATA로 통일
        raise DataSourceError(
            f"{request.page_id}: geo_events 형식이 GeoEventObservation과 맞지 않는다: {exc}"
        ) from exc


def _komis_period_comparisons_from_request(
    request: AnalysisSummaryRequest,
    *,
    raw: dict | None = None,
) -> PriceKomisPeriodComparisons | None:
    """`request.komis_period_comparisons`(선택 필드, 2026-08-28 추가조사 확정 —
    `report_gen_price_base_metals_부실요약_원인조사_260828.md`)를 검증한다.
    `_geo_events_from_request`와 같은 패턴: 없으면 에러가 아니라 None(하위호환).

    `raw`(2026-08-30 신설) — `_parse_komis_price_response`가 `komis_response`
    에서 뽑아낸 값을 여기 override로 넘긴다(`_observations_from_request`의
    `raw` 파라미터와 같은 패턴)."""

    payload = raw if raw is not None else request.komis_period_comparisons
    if not payload:
        return None
    try:
        return PriceKomisPeriodComparisons.model_validate(payload)
    except Exception as exc:  # noqa: BLE001 — pydantic ValidationError 등을 NO_DATA로 통일
        raise DataSourceError(
            f"{request.page_id}: komis_period_comparisons 형식이 PriceKomisPeriodComparisons와 맞지 않는다: {exc}"
        ) from exc


def _komis_trade_totals_from_request(
    request: AnalysisSummaryRequest,
    *,
    raw: dict | None = None,
) -> TradeKomisTotals | None:
    """`request.komis_trade_totals`(선택 필드, 2026-08-29 Phase3 라이브 재검증
    확정 — `report_gen_KOMIS라이브재검증_Phase3_260829.md`)를 검증한다.
    `_geo_events_from_request`와 같은 패턴: 없으면 에러가 아니라 None(하위호환).

    `raw`(2026-08-30 신설) — `_trade_series_from_request`가 `komis_response`
    에서 뽑아낸 값을 여기 override로 넘긴다(`_komis_period_comparisons_
    from_request`의 `raw` 파라미터와 같은 패턴)."""

    payload = raw if raw is not None else request.komis_trade_totals
    if not payload:
        return None
    try:
        return TradeKomisTotals.model_validate(payload)
    except Exception as exc:  # noqa: BLE001 — pydantic ValidationError 등을 NO_DATA로 통일
        raise DataSourceError(
            f"{request.page_id}: komis_trade_totals 형식이 TradeKomisTotals와 맞지 않는다: {exc}"
        ) from exc


def _komis_num(value) -> float | None:
    """KOMIS 응답 값(문자열 또는 숫자, 종종 `null`)을 float으로. 파싱 실패 시 None."""

    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _komis_zero_to_none(value) -> float | None:
    """KOMIS는 결측을 `null`이 아니라 문자열 "0.00"으로 채우는 관행이 있다
    (이 세션에서 `inventory`·`lowest_price`/`highest_price` 둘 다 실측
    확인) — 0(.0)은 항상 결측으로 정규화한다."""

    n = _komis_num(value)
    return None if n in (None, 0, 0.0) else n


def _komis_crtr_ymd_to_date(crtr_ymd) -> str:
    """KOMIS `crtrYmd`(YYYYMMDD 문자열)를 report_gen `Day`(YYYY-MM-DD)로."""

    s = str(crtr_ymd)
    return f"{s[0:4]}-{s[4:6]}-{s[6:8]}"


def _komis_rows_to_observations(rows: list[dict]) -> list[dict]:
    out = []
    for row in rows:
        price = _komis_num(row.get("cmercPrc"))
        if price is None or not row.get("crtrYmd"):
            continue
        out.append(
            {
                "date": _komis_crtr_ymd_to_date(row["crtrYmd"]),
                "commerce_price": price,
                "lowest_price": _komis_zero_to_none(row.get("lowstPrc")),
                "highest_price": _komis_zero_to_none(row.get("hghstPrc")),
                "inventory": _komis_zero_to_none(row.get("invt")),
            }
        )
    return out


def _parse_komis_price_response(
    raw: dict,
) -> tuple[list[dict], list[dict] | None, dict | None, str | None]:
    """`request.komis_response`(2026-08-30 신설)를 report_gen 내부 shape 4종
    (observations, compare_observations, komis_period_comparisons, mineral_name)
    으로 변환한다 — KOMIS `getMnrlPrcByMnrkndUnqCd` 원본 응답을 그대로 받아
    호출자가 필드명을 손으로 옮겨 담을 필요를 없앤다(발주처 납품 최적화 요청,
    2026-08-30).

    - `data.defaultMnrl[]` → observations(기본 계열)
    - `data.compareMnrl[]` → compare_observations(비교광종 계열, 있을 때만)
    - `dataAvg.stdMap.{WEEK,MONTH,YEAR}` → komis_period_comparisons.
      `average_price`는 응답에 직접 없고 `flctnPrc`(등락액)만 있어
      `latest_price - flctnPrc`로 역산한다(`komis_dump_smoke_test.py`의
      하네스 산식과 동일 — 라이브 재현으로 확정된 공식).
    - `dataAvg.INFO.mnrkndKornNm` → mineral_name(있으면, 호출자가 명시한
      `mineral_name`이 있으면 그쪽이 항상 우선 — 호출부에서 처리).

    `mineral`(코드)은 KOMIS 응답 본문에 없는 조회 파라미터라 이 함수가
    채우지 않는다 — 호출자가 그대로 명시해야 한다.

    2026-08-30 실사용 재현으로 발견·수정한 버그: `latest_price`를
    `observations[-1]`(defaultMnrl의 배열상 마지막 행)로 뽑았었는데, 실제
    KOMIS 응답은 `defaultMnrl`을 최신일이 먼저 오는 내림차순으로 준다 —
    `[-1]`은 오히려 조회기간 중 가장 오래된 행이라 전주/전월/전년 평균이
    엉뚱한 값으로 역산됐다(예: 니켈 8/27 기준 16,660에서 -64 등락액으로
    16,724가 나와야 하는데, 60일 조회에서 [-1]이 6/1 데이터라 19,050
    기준으로 19,114가 나온 사례 실측). 배열 순서에 의존하지 않는
    `dataAvg.stdMap.CRTRYMD.cmercPrc`(당일 실거래가, 순서 무관 고정
    필드)를 우선 쓰고, 없으면 관측치를 날짜로 정렬해 최신값을 쓴다."""

    data = raw.get("data") or {}
    observations = _komis_rows_to_observations(data.get("defaultMnrl") or [])
    compare_observations = _komis_rows_to_observations(data.get("compareMnrl") or []) or None
    mineral_name = ((raw.get("dataAvg") or {}).get("INFO") or {}).get("mnrkndKornNm") or None

    std_map = ((raw.get("dataAvg") or {}).get("stdMap")) or {}
    latest_price = _komis_num((std_map.get("CRTRYMD") or {}).get("cmercPrc"))
    if latest_price is None:
        latest_price = _komis_num((std_map.get("DAY") or {}).get("cmercPrc"))
    if latest_price is None and observations:
        latest_price = max(observations, key=lambda item: item["date"])["commerce_price"]
    komis_period_comparisons: dict = {}
    for key, field in (("week", "WEEK"), ("month", "MONTH"), ("year", "YEAR")):
        entry = std_map.get(field)
        if not entry or latest_price is None:
            continue
        delta = _komis_num(entry.get("flctnPrc"))
        pct = _komis_num(entry.get("flctnPrcnt"))
        if delta is None or pct is None:
            continue
        komis_period_comparisons[key] = {"average_price": latest_price - delta, "change_pct": pct}

    return observations, compare_observations, (komis_period_comparisons or None), mineral_name


def _komis_ci_get(row: dict, *names: str):
    """`_komis_num`류 헬퍼와 짝 — 대소문자가 다른 동의 키(예: totalBurudgQuty
    vs TOTALPRDCTNQUTY)를 순서대로 찾는다(map_mineral 응답에서 관측된 표기
    불일치)."""

    for name in names:
        if name in row:
            return row[name]
    lowered = {key.lower(): value for key, value in row.items()}
    for name in names:
        if name.lower() in lowered:
            return lowered[name.lower()]
    return None


def _parse_komis_map_korea_response(raw: dict) -> tuple[list[dict], dict | None]:
    """`getListKoreaData` 원본 응답(2026-08-30, 사용자 지시로 price와 같은 패턴을
    나머지 페이지로 확장) → observations + komis_trade_totals. 응답 자체가
    조회 파라미터(`srchDateE`)를 그대로 되돌려주므로 그걸 관측일로 쓴다(행
    자체엔 날짜가 없는 스냅샷 응답 — `komis_dump_smoke_test.py::
    adapt_map_korea`와 같은 근거)."""

    rows = raw.get("list") or []
    as_of = raw.get("srchDateE")
    as_of_date = f"{as_of[0:4]}-{as_of[4:6]}-{as_of[6:8]}" if as_of else None
    observations: list[dict] = []
    if as_of_date:
        for row in rows:
            code = row.get("ntnCd")
            if not code:
                continue
            observations.append(
                {
                    "date": as_of_date,
                    "country_code": code,
                    "country_name": row.get("ntnKornNm") or code,
                    "import_weight": _komis_num(row.get("incmWeig")),
                    "import_amount": _komis_num(row.get("incmAmt")),
                    "export_weight": _komis_num(row.get("expWeig")),
                    "export_amount": _komis_num(row.get("expAmt")),
                }
            )
    komis_trade_totals: dict = {}
    if rows:
        sum_incm = _komis_num(rows[0].get("sumIncmAmt"))
        sum_exp = _komis_num(rows[0].get("sumExpAmt"))
        if sum_incm:
            komis_trade_totals["import_amount"] = sum_incm
        if sum_exp:
            komis_trade_totals["export_amount"] = sum_exp
    return observations, (komis_trade_totals or None)


def _parse_komis_map_global_response(raw: dict) -> tuple[list[dict], dict | None]:
    """`getListDataNation` 원본 응답 → observations + komis_trade_totals.
    map_korea와 달리 행마다 도착국(`incmNtn*`)·원산국(`expNtn*`) 쌍이 이미
    있어 행 1개 = 루트 관측 1건(`komis_dump_smoke_test.py::adapt_map_global`
    과 동일 근거)."""

    rows = raw.get("list") or []
    as_of = raw.get("srchDateE")
    as_of_date = f"{as_of[0:4]}-{as_of[4:6]}-{as_of[6:8]}" if as_of else None
    observations: list[dict] = []
    if as_of_date:
        for row in rows:
            dest_code, origin_code = row.get("incmNtnCd"), row.get("expNtnCd")
            if not dest_code or not origin_code:
                continue
            observations.append(
                {
                    "date": as_of_date,
                    "country_code": dest_code,
                    "country_name": row.get("incmNtnNm") or dest_code,
                    "origin_country_code": origin_code,
                    "origin_country_name": row.get("expNtnNm") or origin_code,
                    "import_weight": _komis_num(row.get("weig")) or 0.0,
                    "import_amount": _komis_num(row.get("amt")) or 0.0,
                }
            )
    komis_trade_totals = None
    if rows:
        sum_amt = _komis_num(rows[0].get("sumAmt"))
        if sum_amt:
            komis_trade_totals = {"import_amount": sum_amt}
    return observations, komis_trade_totals


def _parse_komis_mineral_map_response(raw: dict, measure: str) -> tuple[list[dict], str | None]:
    """`getListMapMnrlChartData` 원본 응답 → observations + unit.
    `measure`("reserves"/"production")는 응답 본문에 없는 조회 파라미터라
    호출자가 그대로 명시해야 한다(`komis_dump_smoke_test.py::
    adapt_mineral_map`과 동일 근거 — 매장량/생산량 총계 키가 대소문자
    표기까지 다를 수 있어 `_komis_ci_get`으로 찾는다)."""

    rows = raw.get("data") or []
    value_key = "burudgQuty" if measure == "reserves" else "prdctnQuty"
    total_key_candidates = (
        ("totalBurudgQuty",) if measure == "reserves" else ("TOTALPRDCTNQUTY", "totalPrdctnQuty")
    )
    unit = (str(rows[0].get("cdVal") or "").strip() or None) if rows else None
    by_year: dict[int, list[dict]] = {}
    totals: dict[int, float] = {}
    for row in rows:
        year_raw = row.get("crtrYr")
        if year_raw is None:
            continue
        year = int(year_raw)
        value = _komis_num(row.get(value_key))
        if value is None or value <= 0:
            continue
        by_year.setdefault(year, []).append(
            {
                "year": year,
                "country_code": row.get("ntnEngCd") or row.get("ntnKornNm"),
                "country_name": row.get("ntnKornNm") or row.get("ntnEngNm"),
                "value": value,
                "is_total": False,
                "is_other": False,
            }
        )
        total_val = _komis_num(_komis_ci_get(row, *total_key_candidates))
        if total_val is not None:
            totals[year] = total_val
    observations: list[dict] = []
    for year in sorted(by_year):
        observations.extend(by_year[year])
        if year in totals:
            observations.append(
                {
                    "year": year,
                    "country_code": "WORLD",
                    "country_name": "세계",
                    "value": totals[year],
                    "is_total": True,
                    "is_other": False,
                }
            )
    return observations, unit


def _parse_komis_composite_response(raw: dict) -> list[dict]:
    """`getLineChartIndx` 원본 응답(2026-08-29 Phase4 라이브재검증) →
    observations. `data.tableData`가 날짜별로 지수유형(indxTp: MNRL=광물
    종합지수/MAJOR=메이저금속지수/RARE=희소금속지수) 3종을 행 3개로 나눠서
    준다 — 같은 crtrYmd(YYYY.MM.DD 점 구분)끼리 묶어 CompositeIndexObservation
    1건(세 지수값 전부)으로 합친다. 세 지수 중 하나라도 없는 날짜는 모델
    요구사항(gt=0 필수 3종)을 못 채워 건너뛴다."""

    table = (raw.get("data") or {}).get("tableData") or []
    by_date: dict[str, dict[str, float]] = {}
    for row in table:
        crtr = row.get("crtrYmd")
        indx_tp = row.get("indxTp")
        value = _komis_num(row.get("indx"))
        if not crtr or not indx_tp or value is None:
            continue
        by_date.setdefault(crtr, {})[indx_tp] = value
    observations: list[dict] = []
    for crtr, values in by_date.items():
        if not all(key in values for key in ("MNRL", "MAJOR", "RARE")):
            continue
        observations.append(
            {
                "date": crtr.replace(".", "-"),
                "composite_index": values["MNRL"],
                "major_metals_index": values["MAJOR"],
                "minor_metals_index": values["RARE"],
            }
        )
    return observations


_KOMIS_FORECAST_PERIOD_RE = re.compile(r"^(\d{2})년\s*(?:(\d)Q)?")


def _parse_komis_price_forecast_response(raw: dict) -> list[dict]:
    """`getListPricePredc` 원본 응답(2026-08-29 Phase4 라이브재검증) →
    observations. `data[]`의 `crtrPrd`("28년 4Q"/"01년 1Q" 형식, 2000년대만
    관측됨)를 `YYYY-QN`/`YYYY`로, `realYn`(Y=확정 실적/N=예측)을 `is_actual`로
    변환한다(§models.py `PriceForecastObservation.is_actual` 참고)."""

    rows = raw.get("data") or []
    observations: list[dict] = []
    for row in rows:
        prd = row.get("crtrPrd")
        price = _komis_num(row.get("prc"))
        if not prd or price is None:
            continue
        match = _KOMIS_FORECAST_PERIOD_RE.match(str(prd))
        if not match:
            continue
        year = 2000 + int(match.group(1))
        period = f"{year}-Q{match.group(2)}" if match.group(2) else str(year)
        real_yn = row.get("realYn")
        is_actual = True if real_yn == "Y" else False if real_yn == "N" else None
        observations.append({"period": period, "price": price, "is_actual": is_actual})
    return observations


def _supply_auxiliary_from_request(request: AnalysisSummaryRequest) -> SupplyAuxiliaryData | None:
    """`supply_auxiliary`(수급 보조패널, 선택)를 검증한다 — 형식이 틀리면
    `DataSourceError`(→ NO_DATA). Pass 3 라운드 2 R2-F1: 이전엔 검증 예외가 그대로
    새어 4개 지표 라우트에서 `{"bogus": 1}` 같은 바디가 INTERNAL_ERROR가 됐다
    (`_observations_from_request`와 같은 규칙으로 맞춤)."""

    if request.supply_auxiliary is None:
        return None
    try:
        return SupplyAuxiliaryData.model_validate(request.supply_auxiliary)
    except Exception as exc:  # noqa: BLE001 — pydantic ValidationError 등
        raise DataSourceError(
            f"{request.page_id}: supply_auxiliary 형식이 SupplyAuxiliaryData와 맞지 않는다: {exc}"
        ) from exc


@dataclass(frozen=True, slots=True)
class _EvidenceClaim:
    id: str
    section: SectionId
    fact: str


@dataclass(slots=True)
class _CalculatedSummary:
    grade: GradeResult | None
    claims: list[_EvidenceClaim]
    key_metrics: list[Metric]
    detailed_metrics: list[Metric]
    patterns: list[DetectedPattern]
    omitted: list[OmittedIndicator]


def _number(value: float, digits: int = 2) -> str:
    return f"{value:,.{digits}f}"


def _metric(
    metric_id: str,
    label: str,
    value: float | int | str | None,
    *,
    unit: str | None = None,
    basis: str | None = None,
    status: Literal["available", "insufficient_data"] = "available",
) -> Metric:
    return Metric(
        id=metric_id,
        label=label,
        status=status,
        value=round(value, 6) if isinstance(value, float) else value,
        unit=unit,
        basis=basis,
    )


def _filter_hash(page_id: str, filters: dict[str, str | None]) -> str:
    canonical = json.dumps(
        {"page_id": page_id, "filters": filters},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _grade_for_summary(
    series: IndicatorSeries,
    observation: IndicatorObservation,
    policy: PagePolicy,
) -> GradeResult | None:
    if (
        series.page_id == "indicator_supply"
        and observation.score <= 1
    ):
        return None
    return policy.classify(observation.score)


def _score_meaning(page_id: str, change: float) -> str:
    if change == 0:
        return "점수와 지표가 나타내는 상태에 변화가 없었다"
    if page_id == "indicator_market":
        return (
            "중장기 가격위험이 낮아지는 방향으로 움직였다"
            if change > 0
            else "중장기 가격위험이 높아지는 방향으로 움직였다"
        )
    return (
        "수급 안정성이 강화되는 방향으로 움직였다"
        if change > 0
        else "수급 안정성이 약해지는 방향으로 움직였다"
    )


def _score_position_meaning(page_id: str, difference: float) -> str:
    if difference == 0:
        return (
            "중장기 가격위험이 조회기간 평균 수준이다"
            if page_id == "indicator_market"
            else "수급 안정성이 조회기간 평균 수준이다"
        )
    if page_id == "indicator_market":
        return (
            "중장기 가격위험이 조회기간 평균보다 낮은 수준이다"
            if difference > 0
            else "중장기 가격위험이 조회기간 평균보다 높은 수준이다"
        )
    return (
        "수급 안정성이 조회기간 평균보다 높은 수준이다"
        if difference > 0
        else "수급 안정성이 조회기간 평균보다 낮은 수준이다"
    )


def _change_phrase(value: float) -> str:
    if value > 0:
        return f"{_number(value)}점 올라"
    if value < 0:
        return f"{_number(abs(value))}점 내려"
    return "변동 없이"


def _supply_auxiliary_metrics(series: IndicatorSeries) -> list[Metric]:
    auxiliary = series.supply_auxiliary
    if series.page_id != "indicator_supply" or auxiliary is None:
        return []
    metrics: list[Metric] = []
    if auxiliary.international_prices:
        latest = auxiliary.international_prices[-1]
        metrics.append(
            _metric(
                "supply_international_price_latest",
                "국제가격 최신값",
                latest.price,
                basis=latest.month,
            )
        )
    if auxiliary.domestic_imports:
        latest_import = auxiliary.domestic_imports[-1]
        metrics.extend(
            [
                _metric(
                    "supply_domestic_import_weight_latest",
                    "국내 수입중량 최신값",
                    latest_import.import_weight_ton,
                    unit="톤",
                    basis=str(latest_import.year),
                ),
                _metric(
                    "supply_domestic_import_amount_latest",
                    "국내 수입금액 최신값",
                    latest_import.import_amount_million_usd,
                    unit="백만USD",
                    basis=str(latest_import.year),
                ),
            ]
        )
    if auxiliary.world_balances:
        latest_balance = auxiliary.world_balances[-1]
        metrics.extend(
            [
                _metric(
                    "supply_world_demand_latest",
                    "세계 수요 최신값",
                    latest_balance.demand_thousand_ton,
                    unit="천톤",
                    basis=str(latest_balance.year),
                ),
                _metric(
                    "supply_world_supply_latest",
                    "세계 공급 최신값",
                    latest_balance.supply_thousand_ton,
                    unit="천톤",
                    basis=str(latest_balance.year),
                ),
                _metric(
                    "supply_world_balance_latest",
                    "세계 수급 과부족 최신값",
                    latest_balance.balance_thousand_ton,
                    unit="천톤",
                    basis=str(latest_balance.year),
                ),
            ]
        )
    if auxiliary.top_three_dependency_percent is not None:
        dependency_year = (
            str(auxiliary.import_dependencies[0].year)
            if auxiliary.import_dependencies
            else None
        )
        metrics.append(
            _metric(
                "supply_top_three_import_dependency",
                "상위 3개국 수입의존도",
                auxiliary.top_three_dependency_percent,
                unit="%",
                basis=dependency_year,
            )
        )
    return metrics


def _classify_series(
    series: IndicatorSeries,
    policy: PagePolicy,
) -> list[GradeResult | None]:
    return [_grade_for_summary(series, item, policy) for item in series.observations]


def _calculate_summary(series: IndicatorSeries, policy: PagePolicy) -> _CalculatedSummary:
    observations = series.observations
    current = observations[-1]
    previous = observations[-2] if len(observations) >= 2 else None
    grades = _classify_series(series, policy)
    grade = grades[-1]
    omitted: list[OmittedIndicator] = []
    patterns: list[DetectedPattern] = []

    current_grade_metric = _metric(
        "current_grade",
        "현재 단계",
        grade.label if grade else None,
        status="available" if grade else "insufficient_data",
    )
    key_metrics = [
        _metric("current_score", "현재 점수", current.score, unit="점"),
        current_grade_metric,
    ]
    detailed_metrics = [*key_metrics]

    current_fact = (
        f"{current.month} {series.mineral.name} {policy.name}는 "
        f"{_number(current.score)}점"
    )
    if grade is None:
        current_fact += "이며 0~1점 구간은 현재 데이터만으로 단계를 확정하지 않는다."
        omitted.append(
            OmittedIndicator(
                id="current_grade",
                reason="0~1점 구간은 현재 다운로드·기준정보만으로 단계를 확정하지 않는다.",
            )
        )
    else:
        current_fact += f"으로 {grade.label} 단계다."
    claims = [_EvidenceClaim("current_state", "core_diagnosis", current_fact)]

    contiguous_pairs = [
        (before, after, before_grade, after_grade)
        for before, after, before_grade, after_grade in zip(
            observations[:-1],
            observations[1:],
            grades[:-1],
            grades[1:],
            strict=True,
        )
        if months_are_contiguous(before.month, after.month)
    ]
    score_change: float | None = None
    if previous is not None:
        score_change = current.score - previous.score
        comparison = (
            "최근 한 달"
            if months_are_contiguous(previous.month, current.month)
            else "직전 관측치 대비"
        )
        score_fact = (
            f"{comparison}에는 점수가 {_change_phrase(score_change)} "
            f"{_score_meaning(series.page_id, score_change)}."
        )
        key_metrics.append(
            _metric(
                "latest_score_change",
                "최근 점수 변화",
                score_change,
                unit="점",
                basis=f"{previous.month} 대비",
            )
        )
        claims.append(_EvidenceClaim("latest_score_change", "core_diagnosis", score_fact))
    else:
        claims.append(
            _EvidenceClaim(
                "latest_score_change",
                "core_diagnosis",
                "이전 관측치가 없어 최근 점수 변화는 계산하지 않았다.",
            )
        )
        omitted.append(
            OmittedIndicator(id="latest_score_change", reason="이전 관측치가 없다.")
        )

    streak = 0
    if grade is not None:
        streak = 1
        for index in range(len(observations) - 1, 0, -1):
            before_grade = grades[index - 1]
            if (
                before_grade is None
                or before_grade.label != grade.label
                or not months_are_contiguous(
                    observations[index - 1].month,
                    observations[index].month,
                )
            ):
                break
            streak += 1
        streak_basis = "조회범위 내 최소 " if streak == len(observations) else ""
        streak_fact = f"{grade.label} 단계는 {streak_basis}{streak}개월 연속 유지됐다."
        streak_metric = _metric(
            "current_grade_streak",
            "현재 단계 연속기간",
            streak,
            unit="개월",
        )
    else:
        streak_fact = "현재 단계가 확인되지 않아 단계 유지기간은 계산하지 않았다."
        streak_metric = _metric(
            "current_grade_streak",
            "현재 단계 연속기간",
            None,
            unit="개월",
            status="insufficient_data",
        )
        omitted.append(
            OmittedIndicator(
                id="current_grade_streak",
                reason="현재 단계가 확인되지 않았다.",
            )
        )
    key_metrics.append(streak_metric)
    if grade is not None:
        claims.append(_EvidenceClaim("grade_streak", "major_changes", streak_fact))

    transitions = [
        pair
        for pair in contiguous_pairs
        if pair[2] is not None and pair[3] is not None and pair[2].label != pair[3].label
    ]
    key_metrics.append(
        _metric("grade_transition_count", "단계 전환 횟수", len(transitions), unit="회")
    )
    if transitions:
        before, after, before_grade, after_grade = transitions[-1]
        assert before_grade is not None and after_grade is not None
        transition_fact = (
            f"가장 최근에는 {after.month}에 {before_grade.label}에서 "
            f"{after_grade.label} 단계로 전환됐다."
        )
        patterns.append(
            DetectedPattern(
                code="latest_grade_transition",
                label="가장 최근 단계 전환",
                evidence=[
                    f"{before.month} {before_grade.label}",
                    f"{after.month} {after_grade.label}",
                ],
            )
        )
    else:
        transition_fact = "조회기간의 연속 월 구간에서는 단계 전환이 확인되지 않았다."
    claims.append(_EvidenceClaim("grade_transition", "major_changes", transition_fact))

    if contiguous_pairs:
        largest = max(contiguous_pairs, key=lambda pair: abs(pair[1].score - pair[0].score))
        largest_change = largest[1].score - largest[0].score
        largest_fact = (
            f"조회기간 중 월간 점수 변화 폭이 가장 컸던 때는 {largest[1].month}로, "
            f"직전월보다 {_change_phrase(largest_change)} 움직였다."
        )
        key_metrics.append(
            _metric(
                "largest_monthly_score_change",
                "최대 월간 점수 변화",
                largest_change,
                unit="점",
                basis=f"{largest[0].month} 대비 {largest[1].month}",
            )
        )
        patterns.append(
            DetectedPattern(
                code="largest_monthly_score_change",
                label="조회기간 최대 월간 점수 변화",
                evidence=[largest_fact],
            )
        )
    else:
        largest_fact = "연속된 월 데이터가 없어 최대 월간 점수 변화는 계산하지 않았다."
        omitted.append(
            OmittedIndicator(
                id="largest_monthly_score_change",
                reason="연속된 월 데이터가 없다.",
            )
        )
    claims.append(
        _EvidenceClaim("largest_monthly_score_change", "major_changes", largest_fact)
    )

    price_change = (
        percent_change(current.price, previous.price)
        if previous is not None and months_are_contiguous(previous.month, current.month)
        else None
    )
    if price_change is not None:
        price_direction = (
            "올랐다"
            if price_change > 0
            else "내렸다"
            if price_change < 0
            else "같았다"
        )
        price_fact = (
            f"같은 최근 한 달 동안 가격은 {_number(abs(price_change) * 100)}% "
            f"{price_direction}."
        )
        key_metrics.append(
            _metric(
                "latest_price_change_rate",
                "최근 가격 변화율",
                price_change,
                unit="ratio",
                basis=f"{previous.month} 대비",
            )
        )
        claims.append(
            _EvidenceClaim("latest_price_change", "current_position", price_fact)
        )
    else:
        omitted.append(
            OmittedIndicator(
                id="latest_price_change_rate",
                reason="비교 가능한 연속 월 가격이 없다.",
            )
        )

    period_average = sum(item.score for item in observations) / len(observations)
    difference_from_average = current.score - period_average
    key_metrics.append(
        _metric(
            "period_average_score",
            "조회기간 평균 점수",
            period_average,
            unit="점",
            basis=f"{observations[0].month}~{observations[-1].month}",
        )
    )
    if difference_from_average > 0:
        average_comparison = (
            f"평균 {_number(period_average)}점보다 "
            f"{_number(difference_from_average)}점 높아"
        )
    elif difference_from_average < 0:
        average_comparison = (
            f"평균 {_number(period_average)}점보다 "
            f"{_number(abs(difference_from_average))}점 낮아"
        )
    else:
        average_comparison = f"평균 {_number(period_average)}점과 같아"
    position_detail = (
        f"현재 점수 {_number(current.score)}점은 조회기간 {average_comparison}, "
        f"{_score_position_meaning(series.page_id, difference_from_average)}."
    )
    if score_change is None or score_change == 0:
        position_fact = position_detail
    else:
        if series.page_id == "indicator_market":
            recent_position = (
                "최근 한 달 중장기 가격위험은 낮아졌"
                if score_change > 0
                else "최근 한 달 중장기 가격위험은 높아졌"
            )
        else:
            recent_position = (
                "최근 한 달 수급 안정성은 강화됐"
                if score_change > 0
                else "최근 한 달 수급 안정성은 약해졌"
            )
        if difference_from_average == 0:
            connector = "으며"
        elif score_change * difference_from_average > 0:
            connector = "고"
        else:
            connector = "지만"
        position_fact = f"{recent_position}{connector}, {position_detail}"

    score_changes = [after.score - before.score for before, after, _, _ in contiguous_pairs]
    rising = sum(change > 0 for change in score_changes)
    falling = sum(change < 0 for change in score_changes)
    flat = sum(change == 0 for change in score_changes)
    detailed_metrics.extend(
        [
            *key_metrics[2:],
            _metric("score_rising_months", "점수 상승 월", rising, unit="개월"),
            _metric("score_falling_months", "점수 하락 월", falling, unit="개월"),
            _metric("score_flat_months", "점수 보합 월", flat, unit="개월"),
            _metric("observation_count", "유효 관측월", len(observations), unit="개월"),
            _metric(
                "current_vs_period_average",
                "평균 대비 현재 점수",
                difference_from_average,
                unit="점",
                basis=f"조회기간 평균 {_number(period_average)}점 대비",
            ),
        ]
    )
    detailed_metrics.extend(_supply_auxiliary_metrics(series))
    claims.append(
        _EvidenceClaim("period_average_position", "current_position", position_fact)
    )

    return _CalculatedSummary(
        grade=grade,
        claims=claims,
        key_metrics=key_metrics[:8],
        detailed_metrics=detailed_metrics,
        patterns=patterns,
        omitted=omitted,
    )


def _deterministic_narrative(
    claims: list[_EvidenceClaim] | list[EvidenceClaim],
) -> SummaryNarrative:
    grouped: dict[SectionId, list[SummarySentence]] = {
        "core_diagnosis": [],
        "major_changes": [],
        "current_position": [],
    }
    for claim in claims:
        grouped[claim.section].append(
            SummarySentence(text=claim.fact, evidence_ids=[claim.id])
        )
    return SummaryNarrative(**grouped)


_NUMBER_PATTERN = re.compile(r"(?<![\w.])\d[\d,]*(?:\.\d+)?%?")
_FORBIDDEN_SUMMARY_TERMS = (
    "경계까지",
    "경계거리",
    "방향 일치율",
    "상관계수",
    "추세",
)
_GRADE_LABELS = {"신중", "주의", "중립", "관심", "기회", "긴장", "안정", "원활"}
# 2026-08-28 작업C(main-agent 조사) — "근거 4개 이상이면 최소 1문장은 근거
# 2개를 결합해야 한다"(SC-018) 규칙이 모든 page_id에 무차별 적용됐는데,
# price_group은 `PRICE_GROUP_SUMMARY_INSTRUCTIONS`(prompts.py)가 "group_movers·
# extreme_movers를 근거에 있는 그대로 옮겨 쓴다"(근거 1개=문장 1개, 결합 금지
# 취지)를 지시하고 `major_changes` 절 자체가 최대 2문장이라, 근거 4개 이상일
# 때 "각자 따로 쓰기"와 "누군가는 합쳐 쓰기"를 동시에 만족하는 게 구조적으로
# 불가능하다 — 실측(26건 표본 재전송) 결과 price_group은 매번 100% 폴백,
# 우연이 아니라 예정된 실패였다. 이 규칙에서만 예외 처리한다("모든 evidence_id
# 정확히 1회 사용" 체크는 여전히 걸린다 — 안전장치로 유효해 유지).
_COMBINED_SENTENCE_EXEMPT_PAGES = {"price_group"}


def _number_tokens(text: str) -> set[str]:
    result: set[str] = set()
    for token in _NUMBER_PATTERN.findall(text):
        is_percent = token.endswith("%")
        raw = token.rstrip("%").replace(",", "")
        try:
            normalized = str(Decimal(raw).normalize())
        except InvalidOperation:
            normalized = raw
        result.add(f"{normalized}%" if is_percent else normalized)
    return result


def _validate_llm_summary(
    candidate: SummaryNarrative,
    claims: list[_EvidenceClaim] | list[EvidenceClaim],
    *,
    page_id: SummaryPageId,
) -> str | None:
    claim_map = {claim.id: claim for claim in claims}
    sections: list[tuple[SectionId, list[SummarySentence]]] = [
        ("core_diagnosis", candidate.core_diagnosis),
        ("major_changes", candidate.major_changes),
        ("current_position", candidate.current_position),
    ]
    sentences = [sentence for _, values in sections for sentence in values]
    # 섹션별 문장수 계약은 `prompts.py::resolve_page_config`(코드 기본값 + DB
    # 오버레이) 한 곳에서 온다 — LLM에 보내는 output_contract와 이 검증기가 같은
    # 값을 보게 하기 위해서다(2026-08-27 skeptic 감사 SC-005 → 같은 날 DB화 2단계).
    cfg = resolve_page_config(page_id)
    if page_id == "map_mineral":
        total_min, total_max = cfg.total_sentence_range or (5, 8)
        if not total_min <= len(sentences) <= total_max:
            return f"광물지도 출력은 전체 {total_min}~{total_max}문장이어야 한다."
        major_min, major_max = cfg.section_sentence_ranges["major_changes"]
        if not major_min <= len(candidate.major_changes) <= major_max:
            return f"광물지도 주요 변화는 {major_min}~{major_max}문장이어야 한다."
        position_min, position_max = cfg.section_sentence_ranges["current_position"]
        if not position_min <= len(candidate.current_position) <= position_max:
            return f"광물지도 현재 위치·의미는 {position_min}~{position_max}문장이어야 한다."
    else:
        for section, values in sections:
            minimum, maximum = cfg.section_sentence_ranges[section]
            if not minimum <= len(values) <= maximum:
                return "섹션별 분석문 수가 출력 계약과 일치하지 않는다."
    used_ids: list[str] = []
    # 등급명 검사는 등급이 있는 지표 페이지에만 — map_mineral 등에서 "안정된 수준"의
    # "안정"이 등급명으로 오인돼 폴백되는 사례가 실 LLM 384건 회귀에서 나왔다(2026-08-27
    # 반복 루프 1회차; PDF 템플릿 자체가 매장량 서술에 "안정된 수준"을 쓴다).
    check_grade_labels = page_id in ("indicator_market", "indicator_supply")
    for section, values in sections:
        for sentence in values:
            if any(term in sentence.text for term in _FORBIDDEN_SUMMARY_TERMS):
                return "본문에서 제외한 지표를 언급했다."
            if any(re.search(rf"\b{re.escape(claim_id)}\b", sentence.text) for claim_id in claim_map):
                # 2026-08-27 반복 루프 1회차: "(current_state)"처럼 id를 본문에 적는 사례 17건.
                return "본문(text)에 evidence_id를 적었다 — evidence_ids 필드에만 적어야 한다."
            referenced = [claim_map.get(evidence_id) for evidence_id in sentence.evidence_ids]
            if any(claim is None for claim in referenced):
                return "존재하지 않는 evidence_id를 사용했다."
            typed_references = [claim for claim in referenced if claim is not None]
            if any(claim.section != section for claim in typed_references):
                return "evidence_id를 다른 출력 섹션에 사용했다."
            evidence_text = " ".join(claim.fact for claim in typed_references)
            if not _number_tokens(sentence.text) <= _number_tokens(evidence_text):
                return "근거에 없는 숫자나 날짜를 사용했다."
            if check_grade_labels:
                mentioned_grades = {label for label in _GRADE_LABELS if label in sentence.text}
                allowed_grades = {label for label in _GRADE_LABELS if label in evidence_text}
                if not mentioned_grades <= allowed_grades:
                    return "근거에 없는 단계명을 사용했다."
            used_ids.extend(sentence.evidence_ids)
    if page_id == "map_mineral":
        required_ids = {
            claim.id for claim in claims if getattr(claim, "required", False)
        }
        if not required_ids <= set(used_ids):
            return "필수 evidence_id를 모두 사용하지 않았다."
    elif Counter(used_ids) != Counter(claim_map.keys()):
        return "모든 evidence_id를 정확히 한 번씩 사용하지 않았다."
    elif (
        page_id not in _COMBINED_SENTENCE_EXEMPT_PAGES
        and len(claims) >= 4
        and not any(len(sentence.evidence_ids) >= 2 for sentence in sentences)
    ):
        return "관련 근거를 결합한 분석 문장이 없다."
    if "current_state" not in {
        evidence_id
        for sentence in candidate.core_diagnosis
        for evidence_id in sentence.evidence_ids
    }:
        return "핵심 진단에 현재 상태 근거가 없다."
    return None


class AnalysisSummaryService:
    """Calculate a page-scoped summary and optionally refine it with verified LLM output."""

    def __init__(
        self,
        data_source: IndicatorDataSource | None,
        *,
        composite_source: CompositeIndexDataSource | None = None,
        mineral_map_source: MineralMapDataSource | None = None,
        price_forecast_source: PriceForecastDataSource | None = None,
        price_source: PriceDataSource | None = None,
        domestic_trade_source: DomesticTradeDataSource | None = None,
        global_trade_source: GlobalTradeDataSource | None = None,
        llm: KomirJsonLLM | None = None,
    ) -> None:
        self._data_source = data_source
        self._composite_source = composite_source
        self._mineral_map_source = mineral_map_source
        self._price_forecast_source = price_forecast_source
        # 아래 3개는 komir 자체 추가(2026-08-19) — §모듈 docstring 4번 참고.
        self._price_source = price_source
        self._domestic_trade_source = domestic_trade_source
        self._global_trade_source = global_trade_source
        self._llm = llm
        self._deadlines = threading.local()

    @property
    def uses_llm(self) -> bool:
        """LLM 정제가 배선돼 있는지 — `routers/_common.py`가 lock 인수 뒤 남은
        예산이 LLM 1회분보다 짧을 때 포기할지 결정하는 데 쓴다(R2-F2)."""

        return self._llm is not None

    def analyze(
        self,
        request: AnalysisSummaryRequest,
        *,
        deadline: float | None = None,
    ) -> AnalysisSummaryResponse:
        """Calculate the summary appropriate for the requested page.

        `deadline`(`time.monotonic()` 기준, 선택) — `routers/_common.py`가 요청당
        예산을 넘긴다. `_refine_with_llm`이 LLM 호출 전마다 남은 예산이 호출 1회
        상한보다 짧으면 호출을 건너뛰고 규칙기반으로 돌아간다(Pass 3 R3-F1: 이전엔
        정제 2루프 × repair 2회가 예산 밖까지 lock을 쥘 수 있었다). 스레드별로
        보관한다 — 서비스 객체는 공유되고 하네스는 동시 호출한다."""

        self._deadlines.value = deadline
        try:
            return self._dispatch(request)
        finally:
            self._deadlines.value = None

    def _dispatch(self, request: AnalysisSummaryRequest) -> AnalysisSummaryResponse:
        if request.page_id == "indicator_composite":
            return self._analyze_composite(request)
        if request.page_id == "map_mineral":
            return self._analyze_mineral_map(request)
        if request.page_id == "forecast_price":
            return self._analyze_price_forecast(request)
        if request.page_id in ("price_base_metals", "price_minor_metals", "price_iron_energy", "price_other"):
            return self._analyze_price(request)
        if request.page_id == "map_korea":
            return self._analyze_domestic_trade(request)
        if request.page_id == "map_global":
            return self._analyze_global_trade(request)
        if request.page_id == "price_group":
            return self._analyze_price_group(request)
        return self._analyze_indicator(request)

    def _analyze_indicator(
        self,
        request: AnalysisSummaryRequest,
    ) -> AnalysisSummaryResponse:
        """Load an indicator series and build its validated summary response."""

        if request.mineral is None:
            raise DataSourceError("indicator analysis requires mineral in the request body")
        # 2026-08-26 DB 조회 경로 비활성화(요청 바디 입력으로 전환, WORKLOG 참고) —
        # 복원 시 아래 두 줄 주석을 해제하고 그 아래 request 기반 조립 블록을 지운다.
        # if self._data_source is None:
        #     raise ValueError("indicator analysis data source is not configured")
        # series = self._data_source.get_series(
        #     page_id=request.page_id,
        #     mineral=request.mineral,
        #     start_month=request.start_month,
        #     end_month=request.end_month,
        # )
        observations = _observations_from_request(IndicatorObservation, request)
        if request.start_month:
            observations = [o for o in observations if o.month >= request.start_month]
        if request.end_month:
            observations = [o for o in observations if o.month <= request.end_month]
        if not observations:
            raise DataSourceError("indicator analysis: 필터 적용 후 observations가 비었다")
        months = sorted(o.month for o in observations)
        series = IndicatorSeries(
            page_id=request.page_id,
            mineral=MineralRef(code=request.mineral, name=request.mineral_name or request.mineral),
            requested_start_month=request.start_month,
            requested_end_month=request.end_month,
            available_start_month=months[0],
            available_end_month=months[-1],
            source_type="api",
            source_id="api:request",
            data_version=_data_version([o.model_dump(mode="json") for o in observations]),
            data_as_of=months[-1],
            observations=observations,
            supply_auxiliary=_supply_auxiliary_from_request(request),
            price_unit=request.price_unit,
            price_criterion=request.price_criterion,
            unavailable_page_data=request.unavailable_page_data or [],
            warnings=[],
        )
        # YAML 등급 정책에 DB 오버레이(이름·정의·제약·버전)를 입힌다 — 등급 밴드는
        # 판정 로직이라 YAML 그대로(2026-08-27 프롬프트 DB화 2단계).
        policy = apply_page_config(load_page_policy(request.page_id))
        calculated = _calculate_summary(series, policy)
        applied_filters = {
            "mineral": series.mineral.name,
            "mineral_code": series.mineral.code,
            "start_month": request.start_month or series.observations[0].month,
            "end_month": request.end_month or series.observations[-1].month,
        }
        defaulted_filters = [
            name
            for name, value in (
                ("start_month", request.start_month),
                ("end_month", request.end_month),
            )
            if value is None
        ]
        missing_data = [*series.unavailable_page_data]
        if series.price_criterion is None:
            missing_data.append("가격 기준")
        if series.price_unit is None:
            missing_data.append("가격 단위")
        quality_status: Literal["available", "partial", "insufficient"] = "partial"
        if len(series.observations) < 2:
            quality_status = "insufficient"
        elif not missing_data and not series.warnings:
            quality_status = "available"
        response = AnalysisSummaryResponse(
            request_id=request.request_id,
            page_id=request.page_id,
            analysis_scope=request.analysis_scope,
            mineral=series.mineral,
            applied_filters=applied_filters,
            defaulted_filters=defaulted_filters,
            filter_hash=_filter_hash(request.page_id, applied_filters),
            source=SourceInfo(
                type=series.source_type,
                id=series.source_id,
                data_version=series.data_version,
                as_of=series.data_as_of,
                file=series.source_file,
                sheets=series.source_sheets,
            ),
            policy_version=policy.policy_version,
            page_definition=policy.definition,
            grade=calculated.grade,
            data_quality=DataQuality(
                status=quality_status,
                observation_count=len(series.observations),
                available_start_month=series.available_start_month,
                available_end_month=series.available_end_month,
                effective_start_month=series.observations[0].month,
                effective_end_month=series.observations[-1].month,
                missing_data=missing_data,
                warnings=series.warnings,
            ),
            summary=_deterministic_narrative(calculated.claims),
            key_metrics=calculated.key_metrics,
            detailed_metrics=calculated.detailed_metrics,
            detected_patterns=calculated.patterns,
            omitted_indicators=calculated.omitted,
            notices=policy.analysis_constraints,
        )
        if self._llm is None or len(calculated.claims) < 5 or quality_status == "insufficient":
            return response
        return self._refine_with_llm(response, policy, calculated.claims)

    def _analyze_composite(
        self,
        request: AnalysisSummaryRequest,
    ) -> AnalysisSummaryResponse:
        """Load a composite-index series and build its validated summary response."""

        # 2026-08-26 DB 조회 경로 비활성화(요청 바디 입력으로 전환, WORKLOG 참고) —
        # 복원 시 아래 두 줄 주석을 해제하고 그 아래 request 기반 조립 블록을 지운다.
        # if self._composite_source is None:
        #     raise ValueError("composite index analysis data source is not configured")
        # series = self._composite_source.get_composite_series(
        #     start_date=request.start_date,
        #     end_date=request.end_date,
        # )
        # 2026-08-30 신설(사용자 지시로 price의 komis_response 패턴 확장) —
        # `getLineChartIndx` 원본 응답이 있으면 시계열 전체를 직접 파싱한다
        # (Phase4 라이브재검증에서 확인한 대로 스냅샷이 아니라 tableData
        # 전체를 읽어야 한다).
        raw_observations = request.observations
        if request.komis_response is not None:
            raw_observations = _parse_komis_composite_response(request.komis_response)
        observations = _observations_from_request(CompositeIndexObservation, request, raw=raw_observations)
        if request.start_date:
            observations = [o for o in observations if o.date >= request.start_date]
        if request.end_date:
            observations = [o for o in observations if o.date <= request.end_date]
        if not observations:
            raise DataSourceError("composite index analysis: 필터 적용 후 observations가 비었다")
        dates = sorted(o.date for o in observations)
        series = CompositeIndexSeries(
            available_start_date=dates[0],
            available_end_date=dates[-1],
            source_type="api",
            source_id="api:request",
            data_version=_data_version([o.model_dump(mode="json") for o in observations]),
            data_as_of=dates[-1],
            observations=observations,
            warnings=[],
        )
        calculated = _calculate_or_no_data(request.page_id, calculate_composite_summary, series)
        context = effective_page_context("indicator_composite")
        applied_filters = {
            "start_date": request.start_date or series.observations[0].date,
            "end_date": request.end_date or series.observations[-1].date,
        }
        defaulted_filters = [
            name
            for name, value in (
                ("start_date", request.start_date),
                ("end_date", request.end_date),
            )
            if value is None
        ]
        effective_warnings = [*series.warnings, *calculated.warnings]
        quality_status: Literal["available", "partial", "insufficient"] = (
            "available" if len(series.observations) >= 4 else "insufficient"
        )
        if effective_warnings and quality_status == "available":
            quality_status = "partial"
        response = AnalysisSummaryResponse(
            request_id=request.request_id,
            page_id=request.page_id,
            analysis_scope=request.analysis_scope,
            mineral=MineralRef(code="COMPOSITE", name="광물종합지수"),
            applied_filters=applied_filters,
            defaulted_filters=defaulted_filters,
            filter_hash=_filter_hash(request.page_id, applied_filters),
            source=SourceInfo(
                type=series.source_type,
                id=series.source_id,
                data_version=series.data_version,
                as_of=series.data_as_of,
                file=series.source_file,
                sheets=series.source_sheets,
            ),
            policy_version=context.policy_version,
            page_definition=context.definition,
            grade=None,
            data_quality=DataQuality(
                status=quality_status,
                observation_count=len(series.observations),
                available_start_date=series.available_start_date,
                available_end_date=series.available_end_date,
                effective_start_date=series.observations[0].date,
                effective_end_date=series.observations[-1].date,
                warnings=effective_warnings,
            ),
            summary=_deterministic_narrative(calculated.claims),
            key_metrics=calculated.key_metrics,
            detailed_metrics=calculated.detailed_metrics,
            detected_patterns=calculated.patterns,
            omitted_indicators=calculated.omitted,
            notices=context.analysis_constraints,
        )
        if self._llm is None or len(calculated.claims) < 5 or quality_status == "insufficient":
            return response
        return self._refine_with_llm(response, context, calculated.claims)

    def _analyze_mineral_map(
        self,
        request: AnalysisSummaryRequest,
    ) -> AnalysisSummaryResponse:
        """Load a mineral-map series and build its validated summary response."""

        if request.mineral is None or request.measure is None:
            raise DataSourceError("mineral map analysis requires mineral and measure in the request body")
        # 2026-08-30 신설(사용자 지시로 price의 komis_response 패턴을 나머지
        # 페이지로 확장) — `getListMapMnrlChartData` 원본 응답을 그대로 받으면
        # observations·unit을 직접 만든다. 없으면(하위호환) 기존처럼 손으로
        # 채운 필드를 그대로 쓴다.
        raw_observations = request.observations
        komis_unit = None
        if request.komis_response is not None:
            raw_observations, komis_unit = _parse_komis_mineral_map_response(
                request.komis_response, request.measure
            )
        unit = request.unit or komis_unit
        if not unit:
            raise DataSourceError("mineral map analysis requires unit in the request body")
        # 2026-08-26 DB 조회 경로 비활성화(요청 바디 입력으로 전환, WORKLOG 참고) —
        # 복원 시 아래 두 줄 주석을 해제하고 그 아래 request 기반 조립 블록을 지운다.
        # if self._mineral_map_source is None:
        #     raise ValueError("mineral map analysis data source is not configured")
        # series = self._mineral_map_source.get_mineral_map_series(
        #     mineral=request.mineral,
        #     measure=request.measure,
        #     start_year=request.start_year,
        #     end_year=request.end_year,
        # )
        observations = _observations_from_request(MineralMapObservation, request, raw=raw_observations)
        if request.start_year:
            observations = [o for o in observations if o.year >= request.start_year]
        if request.end_year:
            observations = [o for o in observations if o.year <= request.end_year]
        if not observations:
            raise DataSourceError("mineral map analysis: 필터 적용 후 observations가 비었다")
        years = sorted({o.year for o in observations})
        series = MineralMapSeries(
            mineral=MineralRef(code=request.mineral, name=request.mineral_name or request.mineral),
            measure=request.measure,
            unit=unit,
            available_start_year=years[0],
            available_end_year=years[-1],
            source_type="api",
            source_id="api:request",
            data_version=_data_version([o.model_dump(mode="json") for o in observations]),
            data_as_of=str(years[-1]),
            observations=observations,
            warnings=[],
        )
        secondary_series = None
        # 빈 리스트는 "없음"으로 본다 — `compare_observations`와 같은 규칙(2026-08-27
        # skeptic 감사 SC-017: 이전엔 `is not None`이라 `[]`를 보내면 요청 전체가
        # NO_DATA로 떨어져 두 필드의 동작이 달랐다).
        if request.secondary_measure_observations:
            # 2026-08-27 신설 — map_mineral 매장량/생산량 교차 비교(PDF §4).
            secondary_measure = "production" if request.measure == "reserves" else "reserves"
            secondary_observations = _observations_from_request(
                MineralMapObservation,
                request,
                raw=request.secondary_measure_observations,
                field_name="secondary_measure_observations",
            )
            secondary_years = sorted({o.year for o in secondary_observations})
            secondary_series = MineralMapSeries(
                mineral=series.mineral,
                measure=secondary_measure,
                unit=request.secondary_unit or request.unit,
                available_start_year=secondary_years[0],
                available_end_year=secondary_years[-1],
                source_type="api",
                source_id="api:request",
                data_version=_data_version([o.model_dump(mode="json") for o in secondary_observations]),
                data_as_of=str(secondary_years[-1]),
                observations=secondary_observations,
                warnings=[],
            )
        calculated = _calculate_or_no_data(
            request.page_id, calculate_mineral_map_summary, series, secondary_series=secondary_series
        )
        context = effective_page_context("map_mineral")
        years = sorted({item.year for item in series.observations})
        applied_filters = {
            "mineral": series.mineral.name,
            "mineral_code": series.mineral.code,
            "measure": series.measure,
            "start_year": str(request.start_year or years[0]),
            "end_year": str(request.end_year or years[-1]),
        }
        defaulted_filters = [
            name
            for name, value in (
                ("start_year", request.start_year),
                ("end_year", request.end_year),
            )
            if value is None
        ]
        effective_warnings = [*series.warnings, *calculated.warnings]
        quality_status: Literal["available", "partial", "insufficient"] = (
            "available" if len(years) >= 2 else "insufficient"
        )
        if effective_warnings and quality_status == "available":
            quality_status = "partial"
        response = AnalysisSummaryResponse(
            request_id=request.request_id,
            page_id=request.page_id,
            analysis_scope=request.analysis_scope,
            mineral=series.mineral,
            applied_filters=applied_filters,
            defaulted_filters=defaulted_filters,
            filter_hash=_filter_hash(request.page_id, applied_filters),
            source=SourceInfo(
                type=series.source_type,
                id=series.source_id,
                data_version=series.data_version,
                as_of=series.data_as_of,
                file=series.source_file,
                sheets=series.source_sheets,
            ),
            policy_version=context.policy_version,
            page_definition=context.definition,
            grade=None,
            data_quality=DataQuality(
                status=quality_status,
                observation_count=len(series.observations),
                available_start_year=series.available_start_year,
                available_end_year=series.available_end_year,
                effective_start_year=years[0],
                effective_end_year=years[-1],
                warnings=effective_warnings,
            ),
            summary=_deterministic_narrative(calculated.claims),
            key_metrics=calculated.key_metrics,
            detailed_metrics=calculated.detailed_metrics,
            detected_patterns=calculated.patterns,
            omitted_indicators=calculated.omitted,
            notices=context.analysis_constraints,
        )
        if self._llm is None or len(calculated.claims) < 5 or quality_status == "insufficient":
            return response
        return self._refine_with_llm(response, context, calculated.claims)

    def _analyze_price_forecast(
        self,
        request: AnalysisSummaryRequest,
    ) -> AnalysisSummaryResponse:
        """Load forecast prices and build a validated forecast summary."""
        if request.mineral is None or request.forecast_horizon is None:
            raise DataSourceError("price forecast analysis requires mineral and forecast_horizon in the request body")
        # 2026-08-26 DB 조회 경로 비활성화(요청 바디 입력으로 전환, WORKLOG 참고) —
        # 복원 시 아래 두 줄 주석을 해제하고 그 아래 request 기반 조립 블록을 지운다.
        # if self._price_forecast_source is None:
        #     raise ValueError("price forecast analysis data source is not configured")
        # series = self._price_forecast_source.get_price_forecast_series(
        #     mineral=request.mineral,
        #     horizon=request.forecast_horizon,
        #     start_period=request.start_period,
        #     end_period=request.end_period,
        # )
        # 2026-08-30 신설(사용자 지시로 price의 komis_response 패턴 확장) —
        # `getListPricePredc` 원본 응답이 있으면 realYn→is_actual 변환까지
        # 포함해 직접 파싱한다.
        raw_observations = request.observations
        if request.komis_response is not None:
            raw_observations = _parse_komis_price_forecast_response(request.komis_response)
        observations = _observations_from_request(PriceForecastObservation, request, raw=raw_observations)
        if request.start_period:
            observations = [o for o in observations if o.period >= request.start_period]
        if request.end_period:
            observations = [o for o in observations if o.period <= request.end_period]
        if not observations:
            raise DataSourceError("price forecast analysis: 필터 적용 후 observations가 비었다")
        periods = sorted(o.period for o in observations)
        series = PriceForecastSeries(
            mineral=MineralRef(code=request.mineral, name=request.mineral_name or request.mineral),
            horizon=request.forecast_horizon,
            available_start_period=periods[0],
            available_end_period=periods[-1],
            price_unit=request.price_unit,
            source_type="api",
            source_id="api:request",
            data_version=_data_version([o.model_dump(mode="json") for o in observations]),
            data_as_of=periods[-1],
            observations=observations,
            warnings=[],
        )
        calculated = _calculate_or_no_data(request.page_id, calculate_price_forecast_summary, series)
        context = effective_page_context("forecast_price")
        applied_filters = {
            "mineral": series.mineral.name,
            "mineral_code": series.mineral.code,
            "forecast_horizon": series.horizon,
            "start_period": request.start_period or series.observations[0].period,
            "end_period": request.end_period or series.observations[-1].period,
        }
        defaulted_filters = [
            name
            for name, value in (
                ("start_period", request.start_period),
                ("end_period", request.end_period),
            )
            if value is None
        ]
        warnings = [*series.warnings, *calculated.warnings]
        quality_status: Literal["available", "partial", "insufficient"] = (
            "partial" if warnings else "available"
        )
        response = AnalysisSummaryResponse(
            request_id=request.request_id,
            page_id=request.page_id,
            analysis_scope=request.analysis_scope,
            mineral=series.mineral,
            applied_filters=applied_filters,
            defaulted_filters=defaulted_filters,
            filter_hash=_filter_hash(request.page_id, applied_filters),
            source=SourceInfo(
                type=series.source_type,
                id=series.source_id,
                data_version=series.data_version,
                as_of=series.data_as_of,
                file=series.source_file,
                sheets=series.source_sheets,
            ),
            policy_version=context.policy_version,
            page_definition=context.definition,
            grade=None,
            data_quality=DataQuality(
                status=quality_status,
                observation_count=len(series.observations),
                available_start_period=series.available_start_period,
                available_end_period=series.available_end_period,
                effective_start_period=series.observations[0].period,
                effective_end_period=series.observations[-1].period,
                missing_data=["가격 단위"] if series.price_unit is None else [],
                warnings=warnings,
            ),
            summary=_deterministic_narrative(calculated.claims),
            key_metrics=calculated.key_metrics,
            detailed_metrics=calculated.detailed_metrics,
            detected_patterns=calculated.patterns,
            omitted_indicators=calculated.omitted,
            notices=context.analysis_constraints,
        )
        if self._llm is None:
            return response
        return self._refine_with_llm(response, context, calculated.claims)

    # ────────────────────────────────────────────────────────────────
    # 아래 3개 메서드는 komir 자체 추가(2026-08-19, 이식 아님) — §모듈 docstring
    # 4번 참고. `_analyze_composite`와 같은 모양(grade 없는 페이지)을 따른다.
    # ────────────────────────────────────────────────────────────────

    def _analyze_price(self, request: AnalysisSummaryRequest) -> AnalysisSummaryResponse:
        """Load a price series and build its validated summary response."""

        if request.mineral is None:
            raise DataSourceError("price analysis requires mineral in the request body")
        # 2026-08-26 DB 조회 경로 비활성화(요청 바디 입력으로 전환, WORKLOG 참고) —
        # 복원 시 아래 두 줄 주석을 해제하고 그 아래 request 기반 조립 블록을 지운다.
        # if self._price_source is None:
        #     raise ValueError("price analysis data source is not configured")
        # series = self._price_source.get_price_series(
        #     mineral=request.mineral,
        #     start_date=request.start_date,
        #     end_date=request.end_date,
        # )
        # 2026-08-30 신설 — `komis_response`(KOMIS 원본 응답 통째)가 있으면
        # 그걸 파싱해서 observations/compare_observations/
        # komis_period_comparisons를 직접 만든다. 있으면 이걸 우선 쓰고,
        # 없으면(하위호환) 기존처럼 손으로 매핑된 필드들을 그대로 쓴다.
        raw_observations = request.observations
        raw_compare_observations = request.compare_observations
        raw_komis_period_comparisons = None
        komis_mineral_name = None
        if request.komis_response is not None:
            parsed_observations, parsed_compare, parsed_period_comparisons, komis_mineral_name = (
                _parse_komis_price_response(request.komis_response)
            )
            raw_observations = parsed_observations
            if parsed_compare is not None:
                raw_compare_observations = parsed_compare
            raw_komis_period_comparisons = parsed_period_comparisons

        observations = _observations_from_request(PriceObservation, request, raw=raw_observations)
        if request.start_date:
            observations = [o for o in observations if o.date >= request.start_date]
        if request.end_date:
            observations = [o for o in observations if o.date <= request.end_date]
        if not observations:
            raise DataSourceError("price analysis: 필터 적용 후 observations가 비었다")
        dates = sorted(o.date for o in observations)
        series = PriceSeries(
            page_id=request.page_id,
            mineral=MineralRef(
                code=request.mineral,
                name=request.mineral_name or komis_mineral_name or request.mineral,
            ),
            price_criterion_serial=request.price_criterion_serial or 0,
            available_start_date=dates[0],
            available_end_date=dates[-1],
            source_type="api",
            source_id="api:request",
            data_version=_data_version([o.model_dump(mode="json") for o in observations]),
            data_as_of=dates[-1],
            observations=observations,
            warnings=[],
        )
        # 2026-08-26: KOMIS 광물자원가격 "비교광종" 대응(price_* 4종 공통,
        # 2026-08-30 확인) — 원본 응답의 `compareMnrl`에
        # 해당하는 `compare_observations`가 있을 때만 두 번째 PriceSeries를
        # 조립해 비교 근거를 계산한다(§`komir_summary.py::calculate_price_summary`).
        compare_series = None
        if raw_compare_observations:
            if request.compare_mineral is None:
                raise DataSourceError("price analysis: compare_observations가 있으면 compare_mineral도 필요하다")
            compare_obs = _observations_from_request(
                PriceObservation,
                request,
                raw=raw_compare_observations,
                field_name="compare_observations",
            )
            compare_dates = sorted(o.date for o in compare_obs)
            compare_series = PriceSeries(
                page_id=request.page_id,
                mineral=MineralRef(
                    code=request.compare_mineral,
                    name=request.compare_mineral_name or request.compare_mineral,
                ),
                price_criterion_serial=0,
                available_start_date=compare_dates[0],
                available_end_date=compare_dates[-1],
                source_type="api",
                source_id="api:request",
                data_version=_data_version([o.model_dump(mode="json") for o in compare_obs]),
                data_as_of=compare_dates[-1],
                observations=compare_obs,
                warnings=[],
            )
        geo_events = _geo_events_from_request(request)
        komis_period_comparisons = _komis_period_comparisons_from_request(
            request, raw=raw_komis_period_comparisons
        )
        calculated = _calculate_or_no_data(
            request.page_id,
            calculate_price_summary,
            series,
            compare_series=compare_series,
            geo_events=geo_events,
            komis_period_comparisons=komis_period_comparisons,
        )
        context = effective_page_context(request.page_id)
        applied_filters = {
            "mineral": series.mineral.name,
            "mineral_code": series.mineral.code,
            "start_date": request.start_date or series.observations[0].date,
            "end_date": request.end_date or series.observations[-1].date,
        }
        # 비철금속(예: "LME CASH")·희소금속(예: "Lithium Carbonate")은 같은
        # 광종이라도 조회조건(가격기준·품목/스펙)이 서로 다를 수 있다 —
        # 요청 바디의 자유 텍스트를 그대로 표시 필터에 실어 보고서에 남긴다
        # (report_render.py가 applied_filters를 보고서 상단에 렌더링한다).
        if request.price_criterion:
            applied_filters["price_criterion"] = request.price_criterion
        if compare_series is not None:
            applied_filters["compare_mineral"] = compare_series.mineral.name
            if request.compare_price_criterion:
                applied_filters["compare_price_criterion"] = request.compare_price_criterion
        defaulted_filters = [
            name
            for name, value in (
                ("start_date", request.start_date),
                ("end_date", request.end_date),
            )
            if value is None
        ]
        effective_warnings = [*series.warnings, *calculated.warnings]
        quality_status: Literal["available", "partial", "insufficient"] = (
            "available" if len(series.observations) >= 2 else "insufficient"
        )
        if effective_warnings and quality_status == "available":
            quality_status = "partial"
        response = AnalysisSummaryResponse(
            request_id=request.request_id,
            page_id=request.page_id,
            analysis_scope=request.analysis_scope,
            mineral=series.mineral,
            applied_filters=applied_filters,
            defaulted_filters=defaulted_filters,
            filter_hash=_filter_hash(request.page_id, applied_filters),
            source=SourceInfo(
                type=series.source_type,
                id=series.source_id,
                data_version=series.data_version,
                as_of=series.data_as_of,
                file=series.source_file,
                sheets=series.source_sheets,
            ),
            policy_version=context.policy_version,
            page_definition=context.definition,
            grade=None,
            data_quality=DataQuality(
                status=quality_status,
                observation_count=len(series.observations),
                available_start_date=series.available_start_date,
                available_end_date=series.available_end_date,
                effective_start_date=series.observations[0].date,
                effective_end_date=series.observations[-1].date,
                warnings=effective_warnings,
            ),
            summary=_deterministic_narrative(calculated.claims),
            key_metrics=calculated.key_metrics,
            detailed_metrics=calculated.detailed_metrics,
            detected_patterns=calculated.patterns,
            omitted_indicators=calculated.omitted,
            notices=context.analysis_constraints,
        )
        # 2026-08-26부터 LLM 정제를 태운다(§모듈 docstring 4번) — 발주처 KOMIS
        # 템플릿 PDF를 근거로 `prompts.py`에 이 3종 전용 지시문·출력계약을
        # 마련했다. forecast_price와 같은 패턴으로 `len(claims) < 5` 같은 최소
        # 근거수 게이트는 두지 않는다 — 이 페이지들의 claim 수는 원래 3~6개뿐이라
        # 그 게이트를 그대로 쓰면 사실상 영구히 규칙기반에 머문다. quality_status
        # 가 "insufficient"(관측치 부족)일 때만 건너뛴다.
        if self._llm is None or quality_status == "insufficient":
            return response
        return self._refine_with_llm(response, context, calculated.claims)

    @staticmethod
    def _trade_series_from_request(
        request: AnalysisSummaryRequest,
        page_id: Literal["map_korea", "map_global"],
    ) -> tuple[TradeMapSeries, dict | None]:
        """`_analyze_domestic_trade`/`_analyze_global_trade` 공통 request→Series 조립.

        2026-08-26: DB(`KO_CSTM_CMMRC`/`KO_UN_CMMRC`) 조회 대신 요청 바디의
        `observations`(TradeCountryObservation 리스트)로 직접 조립한다.

        2026-08-30 신설(사용자 지시로 price의 komis_response 패턴 확장) —
        `getListKoreaData`/`getListDataNation` 원본 응답이 있으면
        observations와 komis_trade_totals(총액 절단 처방, Phase3)를 둘 다
        직접 파싱한다. 반환값에 raw komis_trade_totals dict를 같이 얹어
        호출부가 `_komis_trade_totals_from_request(request, raw=...)`로
        넘길 수 있게 한다."""

        if request.mineral is None:
            raise DataSourceError(f"{page_id} analysis requires mineral in the request body")
        raw_observations = request.observations
        raw_komis_trade_totals = None
        if request.komis_response is not None:
            parser = _parse_komis_map_korea_response if page_id == "map_korea" else _parse_komis_map_global_response
            raw_observations, raw_komis_trade_totals = parser(request.komis_response)
        observations = _observations_from_request(TradeCountryObservation, request, raw=raw_observations)
        if request.start_date:
            observations = [o for o in observations if o.date >= request.start_date]
        if request.end_date:
            observations = [o for o in observations if o.date <= request.end_date]
        if not observations:
            raise DataSourceError(f"{page_id} analysis: 필터 적용 후 observations가 비었다")
        dates = sorted(o.date for o in observations)
        series = TradeMapSeries(
            page_id=page_id,
            mineral=MineralRef(code=request.mineral, name=request.mineral_name or request.mineral),
            available_start_date=dates[0],
            available_end_date=dates[-1],
            source_type="api",
            source_id="api:request",
            data_version=_data_version([o.model_dump(mode="json") for o in observations]),
            data_as_of=dates[-1],
            observations=observations,
            warnings=[],
        )
        return series, raw_komis_trade_totals

    def _analyze_domestic_trade(self, request: AnalysisSummaryRequest) -> AnalysisSummaryResponse:
        """Load a domestic (KO_CSTM_CMMRC) trade-map series and build its response."""

        # 2026-08-26 DB 조회 경로 비활성화(요청 바디 입력으로 전환, WORKLOG 참고) —
        # 복원 시 아래 두 줄 주석을 해제하고 그 아래 request 기반 조립 호출을 지운다.
        # if self._domestic_trade_source is None:
        #     raise ValueError("domestic trade analysis data source is not configured")
        # series = self._domestic_trade_source.get_domestic_trade_series(
        #     mineral=request.mineral,
        #     start_date=request.start_date,
        #     end_date=request.end_date,
        # )
        series, raw_komis_trade_totals = self._trade_series_from_request(request, "map_korea")
        komis_trade_totals = _komis_trade_totals_from_request(request, raw=raw_komis_trade_totals)
        calculated = _calculate_or_no_data(
            request.page_id,
            calculate_domestic_trade_summary,
            series,
            direction=request.trade_direction or "import",
            komis_totals=komis_trade_totals,
        )
        return self._respond_trade_map(request, series, calculated, effective_page_context("map_korea"))

    def _analyze_global_trade(self, request: AnalysisSummaryRequest) -> AnalysisSummaryResponse:
        """Load a global (KO_UN_CMMRC) trade-map series and build its response."""

        # 2026-08-26 DB 조회 경로 비활성화(요청 바디 입력으로 전환, WORKLOG 참고) —
        # 복원 시 아래 두 줄 주석을 해제하고 그 아래 request 기반 조립 호출을 지운다.
        # if self._global_trade_source is None:
        #     raise ValueError("global trade analysis data source is not configured")
        # series = self._global_trade_source.get_global_trade_series(
        #     mineral=request.mineral,
        #     start_date=request.start_date,
        #     end_date=request.end_date,
        # )
        series, raw_komis_trade_totals = self._trade_series_from_request(request, "map_global")
        komis_trade_totals = _komis_trade_totals_from_request(request, raw=raw_komis_trade_totals)
        calculated = _calculate_or_no_data(
            request.page_id, calculate_global_trade_summary, series, komis_totals=komis_trade_totals
        )
        return self._respond_trade_map(request, series, calculated, effective_page_context("map_global"))

    def _analyze_price_group(self, request: AnalysisSummaryRequest) -> AnalysisSummaryResponse:
        """`page_id="price_group"` — PDF §1-2 그룹(비철금속/희소금속) 요약(2026-08-27 신설)."""

        if request.price_group is None:
            raise DataSourceError("price_group analysis requires price_group in the request body")
        observations = _observations_from_request(PriceGroupMineralObservation, request)
        calculated = _calculate_or_no_data(
            request.page_id, calculate_price_group_summary, request.price_group, observations
        )
        context = effective_page_context("price_group")
        group_label = {"base_metals": "비철금속", "minor_metals": "희소금속"}[request.price_group]
        applied_filters = {"price_group": request.price_group}
        data_version = _data_version([o.model_dump(mode="json") for o in observations])
        response = AnalysisSummaryResponse(
            request_id=request.request_id,
            page_id=request.page_id,
            analysis_scope=request.analysis_scope,
            mineral=MineralRef(code=request.price_group, name=group_label),
            applied_filters=applied_filters,
            defaulted_filters=[],
            filter_hash=_filter_hash(request.page_id, applied_filters),
            source=SourceInfo(
                type="api",
                id="api:request",
                data_version=data_version,
                as_of="latest",
                file=None,
                sheets=[],
            ),
            policy_version=context.policy_version,
            page_definition=context.definition,
            grade=None,
            data_quality=DataQuality(
                status="available",
                observation_count=len(observations),
            ),
            summary=_deterministic_narrative(calculated.claims),
            key_metrics=calculated.key_metrics,
            detailed_metrics=calculated.detailed_metrics,
            detected_patterns=calculated.patterns,
            omitted_indicators=calculated.omitted,
            notices=context.analysis_constraints,
        )
        if self._llm is None:
            return response
        return self._refine_with_llm(response, context, calculated.claims)

    def _respond_trade_map(
        self,
        request: AnalysisSummaryRequest,
        series: TradeMapSeries,
        calculated: AdditionalCalculatedSummary,
        context: SummaryPageContext,
    ) -> AnalysisSummaryResponse:
        """`_analyze_domestic_trade`/`_analyze_global_trade` 공통 응답 조립부."""

        dates = sorted({item.date for item in series.observations})
        applied_filters = {
            "mineral": series.mineral.name,
            "mineral_code": series.mineral.code,
            "start_date": request.start_date or dates[0],
            "end_date": request.end_date or dates[-1],
        }
        if request.page_id == "map_korea":
            # 2026-08-27 신설 — 보고서 상단에 조회 방향(수입/수출)을 표시해
            # PDF 지침 점검(/unlazy)에서 고친 방향 라벨 버그를 화면에서도
            # 바로 확인할 수 있게 한다.
            applied_filters["trade_direction"] = "수출" if request.trade_direction == "export" else "수입"
        defaulted_filters = [
            name
            for name, value in (
                ("start_date", request.start_date),
                ("end_date", request.end_date),
            )
            if value is None
        ]
        effective_warnings = [*series.warnings, *calculated.warnings]
        quality_status: Literal["available", "partial", "insufficient"] = (
            "available" if len(dates) >= 1 else "insufficient"
        )
        if effective_warnings and quality_status == "available":
            quality_status = "partial"
        response = AnalysisSummaryResponse(
            request_id=request.request_id,
            page_id=request.page_id,
            analysis_scope=request.analysis_scope,
            mineral=series.mineral,
            applied_filters=applied_filters,
            defaulted_filters=defaulted_filters,
            filter_hash=_filter_hash(request.page_id, applied_filters),
            source=SourceInfo(
                type=series.source_type,
                id=series.source_id,
                data_version=series.data_version,
                as_of=series.data_as_of,
                file=series.source_file,
                sheets=series.source_sheets,
            ),
            policy_version=context.policy_version,
            page_definition=context.definition,
            grade=None,
            data_quality=DataQuality(
                status=quality_status,
                observation_count=len(series.observations),
                available_start_date=series.available_start_date,
                available_end_date=series.available_end_date,
                effective_start_date=dates[0],
                effective_end_date=dates[-1],
                warnings=effective_warnings,
            ),
            summary=_deterministic_narrative(calculated.claims),
            key_metrics=calculated.key_metrics,
            detailed_metrics=calculated.detailed_metrics,
            detected_patterns=calculated.patterns,
            omitted_indicators=calculated.omitted,
            notices=context.analysis_constraints,
        )
        # `_analyze_price`와 같은 패턴으로 LLM 정제를 태운다(§주석 참고,
        # 2026-08-26). single_snapshot(관측 1건뿐) claim만 있어도 claim 수 자체는
        # 항상 3개 이상 확보되므로 별도 최소 근거수 게이트는 두지 않는다.
        if self._llm is None or quality_status == "insufficient":
            return response
        return self._refine_with_llm(response, context, calculated.claims)

    def _refine_with_llm(
        self,
        response: AnalysisSummaryResponse,
        policy: PagePolicy | SummaryPageContext,
        claims: list[_EvidenceClaim] | list[EvidenceClaim],
    ) -> AnalysisSummaryResponse:
        """Request LLM refinement and accept only evidence-valid output."""

        validation_error = None
        evidence_payload = [
            {
                "evidence_id": claim.id,
                "section": claim.section,
                "fact": claim.fact,
                "required": getattr(claim, "required", True),
            }
            for claim in claims
        ]
        # Pass 3 R3-F2: 출력 계약(DB에서 바꿀 수 있음)으로 모든 근거를 정확히 1회씩
        # 담는 게 산술적으로 불가능하면(근거 수 > Σ절 문장 상한 × 문장당 근거 상한)
        # LLM은 어떤 답을 써도 검증에 떨어진다 — 호출 없이 바로 규칙기반으로.
        cfg = resolve_page_config(response.page_id)
        if response.page_id == "map_mineral":
            capacity = (cfg.total_sentence_range or (5, 8))[1] * cfg.max_evidence_ids_per_sentence
            demand = sum(1 for claim in claims if getattr(claim, "required", False))
        else:
            capacity = sum(hi for _, hi in cfg.section_sentence_ranges.values()) * cfg.max_evidence_ids_per_sentence
            demand = len(claims)
        if demand > capacity:
            return self._with_warning(
                response,
                f"LLM 분석요약을 건너뛰었다 — 근거 {demand}개를 출력 계약(문장 상한 합 × 문장당 근거 "
                f"{cfg.max_evidence_ids_per_sentence}개 = {capacity})에 담을 수 없다. DB output_contract를 확인할 것.",
            )
        deadline = getattr(self._deadlines, "value", None)
        for _ in range(2):
            if deadline is not None and (deadline - time.monotonic()) < ANALYSIS_LLM_TIMEOUT_SECONDS:
                # R3-F1: 남은 예산이 LLM 호출 1회 상한보다 짧으면 호출하지 않는다 —
                # 클라이언트는 어차피 TIMEOUT을 받고 lock만 예산 너머까지 쥐게 된다.
                return self._with_warning(
                    response,
                    "LLM 분석요약을 건너뛰었다 — 요청 예산 안에 LLM 호출을 마칠 수 없어 규칙 기반 요약을 반환했다.",
                )
            try:
                invocation = self._llm.invoke(
                    task="analysis_summary",
                    instructions=summary_instructions(response.page_id),
                    payload=build_summary_payload(
                        response=response,
                        policy=policy,
                        allowed_evidence=evidence_payload,
                        previous_validation_error=validation_error,
                    ),
                    output_model=SummaryNarrative,
                    max_tokens=1200,
                )
            # ⚠ 원본은 LLMError만 잡는다. komir의 KomirJsonLLM은 그 아래
            #   OpenAICompatChat.complete()의 전송 오류(재시도 소진 시 맨
            #   RuntimeError, 타임아웃·커넥션은 requests.RequestException →
            #   OSError 하위형)를 감싸지 않고 그대로 올린다 — 여기서 같이 잡지
            #   않으면 vLLM 장애 때 폴백 대신 API가 500을 낸다.
            #   (LLMError 자체도 RuntimeError 하위형이라 함께 처리된다.)
            except (LLMError, RuntimeError, OSError):
                return self._with_warning(
                    response,
                    "LLM 분석요약 생성에 실패해 검증된 규칙 기반 요약을 반환했다.",
                )
            validation_error = _validate_llm_summary(
                invocation.output,
                claims,
                page_id=response.page_id,
            )
            if validation_error is None:
                return response.model_copy(
                    update={"summary": invocation.output, "llm_refined": True}
                )
        return self._with_warning(
            response,
            "LLM 분석요약이 근거 검증을 통과하지 못해 규칙 기반 요약을 반환했다. "
            f"검증 사유: {validation_error or '확인되지 않음'}",
        )

    @staticmethod
    def _with_warning(
        response: AnalysisSummaryResponse,
        warning: str,
    ) -> AnalysisSummaryResponse:
        quality = response.data_quality.model_copy(
            update={"warnings": [*response.data_quality.warnings, warning]}
        )
        return response.model_copy(update={"data_quality": quality})

    def close(self) -> None:
        """Close the LLM and each configured data source when supported."""

        for target in (
            self._llm,
            self._data_source,
            self._composite_source,
            self._mineral_map_source,
            self._price_forecast_source,
        ):
            close = getattr(target, "close", None)
            if callable(close):
                close()
