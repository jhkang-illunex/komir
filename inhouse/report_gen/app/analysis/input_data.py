"""KOMIS 응답 본문을 분석용 관측치로 변환한다.

원본 응답과 기존 observations 입력의 우선순위·결측값 규칙은 이 모듈에서
유지한다. DB, LLM, 보고서 렌더링에는 의존하지 않는다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .errors import DataSourceError
from .models import AnalysisSummaryRequest, PriceKomisPeriodComparisons, TradeKomisTotals, SupplyAuxiliaryData

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


def _komis_period_comparisons_from_request(
    request: AnalysisSummaryRequest,
    *,
    raw: dict | None = None,
) -> PriceKomisPeriodComparisons | None:
    """`request.komis_period_comparisons`(선택 필드, 2026-08-28 추가조사 확정 —
    `report_gen_price_base_metals_부실요약_원인조사_260828.md`)를 검증한다.
    없으면 에러가 아니라 None(하위호환).

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
    없으면 에러가 아니라 None(하위호환).

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


def _komis_num_comma(value) -> float | None:
    """콤마 천단위 구분자가 섞인 KOMIS 문자열 숫자(예: "110,000,000")를
    float로. `getListMnrlTablePrdctnBurgudg`(2026-08-31 신설) 전용 —
    다른 KOMIS 엔드포인트는 콤마 없는 숫자 문자열만 써서 `_komis_num`을
    그대로 쓴다(실측 확인)."""

    if value is None:
        return None
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _komis_zero_to_none(value) -> float | None:
    """KOMIS는 결측을 `null`이 아니라 문자열 "0.00"으로 채우는 관행이 있다
    (이 세션에서 `inventory`·`lowest_price`/`highest_price` 둘 다 실측
    확인) — 0(.0)은 항상 결측으로 정규화한다."""

    n = _komis_num(value)
    return None if n in (None, 0, 0.0) else n


def _komis_crtr_ymd_to_date(crtr_ymd) -> str:
    """KOMIS `crtrYmd`를 report_gen `Day`(YYYY-MM-DD)로 정규화한다.

    2026-08-31 사용자 질문("주·월·분기·년 단위를 인식할 수 있나요?")으로
    실측 확인(`income_data/komis/komis_01_base_metals.json`) — KOMIS는
    조회단위(DAY/WEEK/MONTH/QUARTER/YEAR)에 따라 `crtrYmd` 형식이 전부
    다른데, 이 함수는 여태 DAY/WEEK의 "YYYYMMDD"(8자리)만 가정하고 있었다.
    MONTH("202608")·QUARTER("2026.3Q")·YEAR("2026") 형식을 넣으면
    `s[6:8]`가 빈 문자열이 되어 "2026-08-"처럼 깨진 날짜가 나갔고, 이는
    `PriceObservation.date`의 `Day` 패턴 검증에 걸려 그 요청 전체가
    실패했다(월/분기/년 단위 가격 조회가 사실상 동작하지 않던 상태) —
    이번에 4가지 형식을 전부 정규화한다. MONTH/QUARTER/YEAR는 원래
    특정 "일자"가 없는 기간 집계값이라, 그 기간의 대표일(월초/분기
    첫 달 1일/1월 1일)로 정한다 — 실제 관측일이 아니라 정렬·간격판별용
    근사치임을 유의할 것(`komir_summary.py::_detect_granularity`가 이
    간격으로 단위를 재판별해 변동성 연율화 계수·이동평균 라벨 등에 쓴다)."""

    s = str(crtr_ymd).strip()
    if s.isdigit():
        if len(s) == 8:
            return f"{s[0:4]}-{s[4:6]}-{s[6:8]}"
        if len(s) == 6:
            return f"{s[0:4]}-{s[4:6]}-01"
        if len(s) == 4:
            return f"{s}-01-01"
    if "Q" in s.upper():
        year, _, quarter_part = s.partition(".")
        quarter_num = quarter_part.upper().replace("Q", "").strip()
        month = {"1": "01", "2": "04", "3": "07", "4": "10"}.get(quarter_num, "01")
        return f"{year}-{month}-01"
    # 알 수 없는 형식 — 추정으로 임의 정규화하지 않고 원본을 그대로
    # 돌려줘 Pydantic 검증에서 명시적으로 실패하게 둔다.
    return s


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


@dataclass(frozen=True, slots=True)
class _KomisPriceParsed:
    """`_parse_komis_price_response`의 반환 shape(2026-09-08 SC-003: 자리만
    구분되는 7-튜플 대신 이름으로 접근하게 함)."""

    observations: list[dict] | None
    compare_observations: list[dict] | None
    komis_period_comparisons: dict | None
    mineral_name: str | None
    price_criterion: str | None
    compare_mineral_name: str | None
    compare_price_criterion: str | None
    #: `dataAvg.INFO.prcUnitCdNm`(2026-09-09 발주처 업무지시서 — 핵심 진단
    #: 문장에 단위가 없다는 지적 대응). mineral_name/price_criterion과 같은
    #: 자리(`komis_info`)에서 뽑는다.
    price_unit: str | None = None


def _parse_komis_price_response(raw: dict) -> _KomisPriceParsed:
    """`request.komis_response`(2026-08-30 신설)를 report_gen 내부 shape 8종
    (observations, compare_observations, komis_period_comparisons, mineral_name,
    price_criterion, compare_mineral_name, compare_price_criterion, price_unit)으로
    변환한다 — KOMIS `getMnrlPrcByMnrkndUnqCd` 원본 응답을 그대로 받아
    호출자가 필드명을 손으로 옮겨 담을 필요를 없앤다(발주처 납품 최적화
    요청, 2026-08-30).

    - `data.defaultMnrl[]` → observations(기본 계열)
    - `data.compareMnrl[]` → compare_observations(비교광종 계열, 있을 때만)
    - `dataAvg.stdMap.{WEEK,MONTH,YEAR}` → komis_period_comparisons.
      `average_price`는 응답에 직접 없고 `flctnPrc`(등락액)만 있어
      `latest_price - flctnPrc`로 역산한다(`komis_dump_smoke_test.py`의
      하네스 산식과 동일 — 라이브 재현으로 확정된 공식).
    - `dataAvg.INFO.mnrkndKornNm` → mineral_name(있으면, 호출자가 명시한
      `mineral_name`이 있으면 그쪽이 항상 우선 — 호출부에서 처리).
    - `dataAvg.INFO.prcCrtr`(예: "LME CASH") → price_criterion(2026-08-30
      사용자 지적 — "LME쪽이 안 보인다": `applied_filters["price_criterion"]`
      은 이미 있는데 komis_response 경로가 안 채워서 보고서 상단
      "**가격기준**: ..." 줄이 항상 비어 있었다. mineral_name과 같은 규칙 —
      호출자가 명시한 `price_criterion`이 있으면 그쪽이 우선).
    - `dataAvg.INFO.prcUnitCdNm`(예: "USD"·"CNY") → price_unit(2026-09-09
      발주처 업무지시서 대응 — 핵심 진단 문장에 단위가 없다는 지적. 실 KOMIS
      덤프 전수 확인 결과 값은 "USD"/"CNY" 2종뿐이라 `komir_summary.py`가
      한국어 표기("달러"/"위안")로 바꾼다 — mineral_name과 같은 자리에서
      뽑되, 이 필드는 사람이 손으로 대체할 이유가 없어 호출자 우선순위
      규칙은 두지 않는다).
    - `dataAvg.cmpMap.INFO.mnrkndKornNm` → compare_mineral_name(2026-08-30
      2차 발견 — 사용자가 "compare_mineral_name도 komis_response 안에
      있지 않냐"고 지적해 Playwright 라이브 재현(네오디뮴 대비 갈륨
      조회)으로 확인. `cmpMap`은 `stdMap`(기본 광종)과 완전히 같은
      모양으로 비교 광종 몫이 따로 온다 — `mineral_name`과 같은 자리에
      있는데도 그동안 안 읽고 있었다).
    - `dataAvg.cmpMap.INFO.prcCrtr` → compare_price_criterion(2026-08-30
      3차 발견 — `compare_mineral_name`과 같은 `cmpMap.INFO` 블록 안에
      비교광종 자신의 가격기준도 같이 온다는 걸 그때 같이 확인해놓고
      실제 배선은 놓쳤다. `routers/analysis.py::PriceSummaryRequest`가
      `c76466a47`(2026-08-30 Swagger 트리밍)에서 이 필드를 "komis_
      response로 대체돼 불필요"로 잘못 판단해 라우터에서 지운 적이 있다
      — 그런데 `_analyze_price`(아래)는 계속 `request.compare_price_
      criterion`을 읽고 있었으니, 그 트리밍 이후로는 호출자가 값을
      보낼 방법 자체가 없어 이 표시가 조용히 죽어 있었다(회귀). 이번에
      필드를 라우터에 복원하면서 auto-fill까지 같이 넣는다).

    `mineral`/`compare_mineral`(코드)은 KOMIS 응답 본문 어디에도 없는
    조회 파라미터라(`cmpMap.INFO`도 이름만 있고 코드가 없음, 실측
    확인) 이 함수가 채우지 않는다 — 호출자가 그대로 명시해야 한다.

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
    dataAvg = raw.get("dataAvg") or {}
    komis_info = dataAvg.get("INFO") or {}
    mineral_name = komis_info.get("mnrkndKornNm") or None
    price_criterion = komis_info.get("prcCrtr") or None
    price_unit = komis_info.get("prcUnitCdNm") or None
    compare_info = (dataAvg.get("cmpMap") or {}).get("INFO") or {}
    compare_mineral_name = compare_info.get("mnrkndKornNm") or None
    compare_price_criterion = compare_info.get("prcCrtr") or None

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

    return _KomisPriceParsed(
        observations=observations,
        compare_observations=compare_observations,
        komis_period_comparisons=(komis_period_comparisons or None),
        mineral_name=mineral_name,
        price_criterion=price_criterion,
        compare_mineral_name=compare_mineral_name,
        compare_price_criterion=compare_price_criterion,
        price_unit=price_unit,
    )


def _parse_komis_map_korea_response(raw: dict) -> tuple[list[dict], dict | None, str | None]:
    """`getListKoreaData` 원본 응답(2026-08-30, 사용자 지시로 price와 같은 패턴을
    나머지 페이지로 확장) → observations + komis_trade_totals + mineral(코드).
    응답 자체가 조회 파라미터(`srchDateE`·`srchMnrkndUnqCd`)를 그대로
    되돌려주므로 그걸 관측일·광종코드로 쓴다(행 자체엔 날짜가 없는 스냅샷
    응답 — `komis_dump_smoke_test.py::adapt_map_korea`와 같은 근거).
    2026-08-31 확인: `srchMnrkndUnqCd`가 있어 `mineral`도 자동 채움
    가능(price_*는 응답 본문에 코드가 없어 이 자동채움이 불가능한 것과
    대비된다)."""

    rows = raw.get("list") or []
    as_of = raw.get("srchDateE")
    as_of_date = f"{as_of[0:4]}-{as_of[4:6]}-{as_of[6:8]}" if as_of else None
    mineral_code = raw.get("srchMnrkndUnqCd") or None
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
    return observations, (komis_trade_totals or None), mineral_code


def _map_korea_query_filters(
    komis_response: dict | None, observations: list, mttr_flow_name: str | None
) -> tuple[str | None, str | None, str | None]:
    """`request.komis_response`(`getListKoreaData`)의 echo에서 조회필터
    3종(기간구분·국가·생산품유형/HS)을 뽑는다 — `komis_snapshot_response`
    류와 달리 새 요청 필드가 필요 없다(2026-08-31, streamlit-agent 실측
    확인: 이 응답은 `srchCrtrYmd`/`srchNtnCd`/`srchMttrFlowCd`/`srchHsCd`
    요청 파라미터 전부를 최상위에 그대로 echo한다).

    반환: (period_unit_label, country_filter_name, scope_label).
    `country_filter_name`과 `scope_label`은 상호배타(국가필터가 있으면
    scope_label은 만들지 않는다 — `calculate_domestic_trade_summary`
    docstring 참고, 국가필터가 랭킹 claim 자체를 억제하므로 범위라벨은
    의미가 없다)."""

    if not komis_response:
        return None, None, None
    period_unit_label = "월별" if komis_response.get("srchCrtrYmd") == "M" else "년별"

    ntn_cd = (komis_response.get("srchNtnCd") or "").strip()
    country_filter_name = None
    if ntn_cd:
        hit = next((o for o in observations if o.country_code == ntn_cd), None)
        country_filter_name = hit.country_name if hit is not None else ntn_cd

    scope_label = None
    if not country_filter_name:
        hs_cd = (komis_response.get("srchHsCd") or "").strip()
        mttr_flow_cd = (komis_response.get("srchMttrFlowCd") or "").strip()
        if hs_cd:
            item_name = None
            for row in komis_response.get("list") or []:
                if row.get("hsCd") == hs_cd and row.get("itemNm"):
                    item_name = row["itemNm"]
                    break
            scope_label = f"HS {hs_cd}({item_name})" if item_name else f"HS {hs_cd}"
        elif mttr_flow_cd:
            scope_label = mttr_flow_name or f"생산품유형코드 {mttr_flow_cd}"

    return period_unit_label, country_filter_name, scope_label


def _parse_komis_map_global_response(raw: dict) -> tuple[list[dict], dict | None, str | None]:
    """`getListDataNation` 원본 응답 → observations + komis_trade_totals +
    mineral(코드). map_korea와 달리 행마다 도착국(`incmNtn*`)·원산국
    (`expNtn*`) 쌍이 이미 있어 행 1개 = 루트 관측 1건(`komis_dump_smoke_
    test.py::adapt_map_global`과 동일 근거). map_korea와 마찬가지로
    `srchMnrkndUnqCd`가 응답에 echo되어 `mineral` 자동 채움 가능
    (2026-08-31 확인)."""

    rows = raw.get("list") or []
    as_of = raw.get("srchDateE")
    as_of_date = f"{as_of[0:4]}-{as_of[4:6]}-{as_of[6:8]}" if as_of else None
    mineral_code = raw.get("srchMnrkndUnqCd") or None
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
    return observations, komis_trade_totals, mineral_code


def _parse_komis_map_global_bar_chart_top_movers(raw: dict) -> list[dict] | None:
    """`getBarChartDataNation` 원본 응답 → 최근 2개년 교역액 변화량(절대값)
    기준 상위 3개국 `[{country_name, previous_year, previous_value,
    latest_year, latest_value, change}, ...]`(신호 부호 내림차순 정렬 —
    호출부가 그대로 "+--" 패턴으로 서술할 수 있게).

    2026-09-11 사용자 지시로 확장 — 예전엔 최신연도 값 기준 1위국만
    골라 그 국가의 연도별 추이 하나만 보여줬는데("교역액이 많이 변화된
    국가"가 아니라 "교역액 자체가 큰 국가"를 고르던 것과 다르다), 이제
    변화량(latest-previous)의 절대값 기준으로 상위 3개국을 고른다.

    2026-08-31 신설 배경 — `getListDataNation`이 스냅샷 1건뿐이라 실전에서
    기간변화(`period_total_change`)가 거의 항상 비어 있던 문제(map_global
    `dates`가 사실상 항상 1개)를 완화한다. 실측 대조 결과 바차트 국가별
    합계가 `getListDataNation`의 `sumAmt`와 다르다(예: 2017년 갈륨 수입,
    list sumAmt 886M 대 bar 국가합계 1,391M — 30%대 차이) — 두 엔드포인트의
    "총액" 집계 범위가 다른 것으로 보여 합산값을 "세계 교역 총액"이라
    부르지 않는다. 대신 **국가 자신의 연도별 원값**만 쓴다(집계가 아니라
    KOMIS가 이미 국가 단위로 준 값 그대로라 범위 논쟁이 없다).

    ⚠바차트의 마지막 연도(`xaxis[-1]`)는 항상 연중 진행분으로 취급해
    제외한다 — 실측 확인(최신 연도 값이 직전 연도의 1/9~1/15로 급감,
    가격페이지 "{year}년(연중)" 문제와 같은 패턴). `srchDateChartS`/
    `srchDateChartE`가 조회 대상 연도와 무관하게 항상 "최근 ~13개년~현재"
    고정 폭이라(실측 확인 — list_data가 2017년을 조회해도 바차트는
    2014~2026을 그대로 준다), 이 규칙은 조회 연도와 무관하게 항상
    적용해도 안전하다."""

    bar = ((raw.get("data") or {}).get("barChart")) or {}
    xaxis = bar.get("xaxis") or []
    series = bar.get("series") or []
    if len(xaxis) < 3 or not series:
        return None
    complete_years = xaxis[:-1]
    latest_idx = len(complete_years) - 1
    previous_idx = latest_idx - 1
    if previous_idx < 0:
        return None

    def _value_at(entry: dict, idx: int) -> float | None:
        values = entry.get("data") or []
        if idx >= len(values) or values[idx] is None:
            return None
        return float(values[idx])

    candidates = []
    for entry in series:
        latest_val = _value_at(entry, latest_idx)
        previous_val = _value_at(entry, previous_idx)
        name = entry.get("name") or entry.get("seriesCd")
        if latest_val is None or previous_val is None or not name:
            continue
        candidates.append(
            {
                "country_name": name,
                "previous_year": str(complete_years[previous_idx]),
                "previous_value": previous_val,
                "latest_year": str(complete_years[latest_idx]),
                "latest_value": latest_val,
                "change": latest_val - previous_val,
            }
        )
    if not candidates:
        return None
    candidates.sort(key=lambda c: abs(c["change"]), reverse=True)
    top3 = candidates[: min(3, len(candidates))]
    top3.sort(key=lambda c: c["change"], reverse=True)
    return top3


def _parse_komis_map_global_route_shares(raw: dict) -> list[dict]:
    """`getListMapNationData` 원본 응답 → 루트별
    `[{origin_name, dest_name, origin_share_percent, dest_share_percent}]`.

    2026-08-31 신설. `crtrNtnAmtRt`/`trgtNtnAmtRt`의 의미를 실측 교차곱
    검증으로 확정했다 — 같은 루트에서 `crtrTotalAmt × crtrNtnAmtRt`와
    `trgtTotalAmt × trgtNtnAmtRt`가 (반올림 오차 내로) 같은 값에 수렴한다,
    즉 **"이 루트가 각국 자신의 집계총액에서 차지하는 비중"**이다. 다만
    그 집계총액이 수출·수입 중 어느 방향인지까지는 검증하지 못해 호출부가
    라벨을 방향중립("{국가}측 집계총액 대비")으로 둔다."""

    rows = (raw.get("data") or {}).get("mapData") or []
    result: list[dict] = []
    for row in rows:
        origin_name = row.get("crtrNtnKornNm")
        dest_name = row.get("trgtNtnKornNm")
        if not origin_name or not dest_name:
            continue
        result.append(
            {
                "origin_name": origin_name,
                "dest_name": dest_name,
                "origin_share_percent": _komis_num(row.get("crtrNtnAmtRt")),
                "dest_share_percent": _komis_num(row.get("trgtNtnAmtRt")),
            }
        )
    return result


#: 2026-09-09 발주처 업무지시서 §3.3 대응 — `getListMapMnrlChartData`/
#: `getListMapMnrlData`의 `cdVal`(단위 코드)이 영문 그대로("ton"/"k ton"/
#: "kg"/"mt")라 한글 문장에 영문이 섞여 나온다(65개 광종 실측 전수 확인,
#: `mt`는 철 등 WT007 계열에서 실측값 규모상 "metric ton"=톤과 동일).
#: 매핑에 없는 코드가 오면 원문 코드를 그대로 쓴다(단위를 지어내지 않는다).
#:
#: ⚠"k ton"→"톤"(잠정, "천톤" 아님) — main-agent가 USGS 실측치와 교차
#: 대조해 확정: 동(구리) 칠레 2025 매장량 원값 180,000,000을 "천톤"으로
#: 읽으면 1,800억 톤(물리적으로 불가능한 규모)이지만 "톤"으로 읽으면
#: 1.8억 톤 = USGS 실측(~1.9억 톤)과 일치한다. 생산량도 동일 검증
#: (칠레 2025 원값 5,300,000을 톤으로 읽으면 530만 톤, 실제 연간
#: 생산량과 정확히 일치). 즉 KOMIS `cdVal` 라벨("k ton")과 실제 값의
#: 스케일이 서로 안 맞고, 값 자체는 이미 톤 단위다 — KOMIS 웹 화면에서
#: 이 단위가 실제로 어떻게 표기되는지는 아직 직접 확인하지 못했다(이
#: 세션은 오프라인이라 komis.or.kr 라이브 접속 불가) — 온라인 접속
#: 가능한 세션에서 화면 표기와 최종 대조 필요.
_MINERAL_MAP_UNIT_LABELS = {"ton": "톤", "k ton": "톤", "kg": "킬로그램", "mt": "톤"}


def _mineral_map_unit_label(raw_unit: str | None) -> str | None:
    if not raw_unit:
        return None
    return _MINERAL_MAP_UNIT_LABELS.get(raw_unit, raw_unit)


def _mineral_map_value_key(measure: str) -> str:
    return "burudgQuty" if measure == "reserves" else "prdctnQuty"


def _mineral_map_country_observation(year: int, row: dict, value_key: str) -> dict | None:
    """`getListMapMnrlChartData`/`getListMapMnrlData` 공통 행 구조(2026-09-09
    복잡성 해소 — 두 파서가 이 추출 로직을 그대로 복제하고 있었다) →
    국가별 관측치 dict 1건, 값이 없거나 0 이하면 None(호출부가 건너뛴다)."""

    value = _komis_num(row.get(value_key))
    if value is None or value <= 0:
        return None
    return {
        "year": year,
        "country_code": row.get("ntnEngCd") or row.get("ntnKornNm"),
        "country_name": row.get("ntnKornNm") or row.get("ntnEngNm"),
        "value": value,
        "is_total": False,
        "is_other": False,
    }


def _parse_komis_mineral_map_response(raw: dict, measure: str) -> tuple[list[dict], str | None]:
    """`getListMapMnrlChartData` 원본 응답 → observations + unit.
    `measure`("reserves"/"production")는 응답 본문에 없는 조회 파라미터라
    호출자가 그대로 명시해야 한다(`komis_dump_smoke_test.py::
    adapt_mineral_map`과 동일 근거).

    2026-09-09 발주처 업무지시서 §3.3·§4-8("비중·합계 산출 검증 필요")
    대응 — 이전엔 응답의 `totalBurudgQuty`/`TOTALPRDCTNQUTY`를 "공식
    세계 총계"로 그대로 신뢰해 `is_total=True` 관측치를 만들었다. 동(구리)
    실 덤프로 대조한 결과 이 필드가 **2019~2025년 내내 완전히 같은 값**
    (예: 매장량 5,060,700,000)으로 고정돼 있어 그 해 국가별 합계(예: 2019년
    651,000,000·2025년 770,200,000)와 다르다 — 실제 국가별 연도별 합계
    보다 6~8배 크다. main-agent가 재검증해 정체를 확정했다: 이 값은
    무의미한 상수가 아니라 **조회기간(2019~2025) 전체 연도·국가를 다
    합산한 값**이다(직접 검산: 모든 연도·국가의 `burudgQuty` 총합 =
    5,060,700,000, 생산량도 동일하게 `TOTALPRDCTNQUTY`=132,244,000과
    일치). 즉 "그 해의 세계 총계"가 아니라 "조회기간 총합"을 담은
    필드라 애초에 연도별 분모로 쓰기에 부적합하다(이 결론 자체는 그대로
    유효). 이 필드를 아예 읽지 않는다 — `additional_summary.py::
    _world_total()`이 이미 "공식 총계가 없으면 국가별 합계를 쓴다"는
    폴백을 갖고 있어(그 파일은 무수정 이식이라 편집하지 않음), 여기서
    가짜 `is_total` 관측치 생성을 멈추기만 하면 계산기가 자동으로
    올바르게 그 해 국가별 합계를 쓴다."""

    rows = raw.get("data") or []
    value_key = _mineral_map_value_key(measure)
    unit = _mineral_map_unit_label(str(rows[0].get("cdVal") or "").strip() or None) if rows else None
    observations: list[dict] = []
    for row in rows:
        year_raw = row.get("crtrYr")
        if year_raw is None:
            continue
        observation = _mineral_map_country_observation(int(year_raw), row, value_key)
        if observation is not None:
            observations.append(observation)
    return observations, unit


def _parse_komis_map_mineral_snapshot_response(
    raw: dict, measure: str, year: int
) -> tuple[list[dict], str | None]:
    """`getListMapMnrlData` 원본 응답 → observations(단일 연도) + unit.

    2026-08-31 신설 — 옛 `secondary_measure_observations`(손입력)를
    대체한다. `measure`는 뽑아낼 항목("reserves"/"production", 보통
    primary measure의 반대)이고, `year`는 응답 본문에 없는 연도라
    호출자가 명시해야 한다(`_analyze_mineral_map`이 primary 계열의
    `available_end_year`를 넘긴다 — `models.py`의 `komis_snapshot_response`
    필드 docstring 참고). ⚠단일 연도 조회(srchDateS==srchDateE) 전제 —
    다년 범위로 조회하면 KOMIS가 그 범위를 합산한 값을 준다(실측 확인,
    같은 문서 참고), 이 함수는 그 구분을 응답만으로 할 수 없다.

    2026-09-09 — `_parse_komis_mineral_map_response`와 같은 이유로 응답의
    "공식 총계" 필드(`totalBurudgQuty`/`TOTALPRDCTNQUTY`)를 더 이상 신뢰
    하지 않는다(위 함수 docstring의 실측 근거 참고) — 국가별 관측치만
    반환하고, 세계 총계는 이 값들의 합으로 자동 계산되게 둔다."""

    rows = raw.get("data") or []
    value_key = _mineral_map_value_key(measure)
    unit = _mineral_map_unit_label(str(rows[0].get("cdVal") or "").strip() or None) if rows else None
    observations = [
        observation
        for row in rows
        if (observation := _mineral_map_country_observation(year, row, value_key)) is not None
    ]
    return observations, unit


def _parse_komis_map_mineral_share_response(raw: dict) -> list[dict]:
    """`getListMnrlTablePrdctnBurgudg` 원본 응답 → 국가별
    `[{country_code, country_name, value, share_percent}]`.

    2026-08-31 신설. 응답은 국가별 최근 5개년(`before1`=최신연도~
    `before5`) 값을 주지만, 사용자 지시로 가장 최근 연도(`before1`)만
    쓴다("매장량 현황은 가장 마지막 년도 값만 사용해요"). `rate`는 실측
    대조(2개 표본 정확히 일치)로 확정 — "전년대비 증감률"이 아니라
    **해당 국가가 이 표의 `_TOTAL_`(before1 연도, 표에 나열된 국가들의
    소계)에서 차지하는 비중(%)**이다. ⚠이 `_TOTAL_`은 `getListMapMnrlChartData`
    기반 세계합계보다 체계적으로 작다(실측 4개 광종에서 4~11배 — 표에
    나열된 국가 수만큼만 합산된 소계라 그렇다, `additional_summary.py::
    calculate_mineral_map_summary`의 `market_share` 파라미터 docstring
    참고) — "세계비중"이라고 부르지 않는다. `_TOTAL_`(코드 SU)·`_ETC_`
    (코드 OT)는 국가 목록이 아니라 국가 랭킹에서 제외한다. 값이 콤마
    천단위 구분자 문자열이라 `_komis_num_comma`로 파싱한다."""

    rows = raw.get("data") or []
    result: list[dict] = []
    for row in rows:
        code = row.get("ntnEngCd")
        if not code or code in ("SU", "OT"):
            continue
        value = _komis_num_comma(row.get("before1"))
        if value is None or value <= 0:
            continue
        result.append(
            {
                "country_code": code,
                "country_name": row.get("ntnKornNm") or code,
                "value": value,
                "share_percent": _komis_num_comma(row.get("rate")),
            }
        )
    return result


def _parse_komis_composite_response(raw: dict) -> list[dict]:
    """`getLineChartIndx` 원본 응답(2026-08-29 Phase4 라이브재검증) →
    observations. `data.tableData`가 날짜별로 지수유형(indxTp: MNRL=광물
    종합지수/MAJOR=메이저금속지수/RARE=희소금속지수) 3종을 행 3개로 나눠서
    준다 — 같은 crtrYmd(YYYY.MM.DD 점 구분)끼리 묶어 CompositeIndexObservation
    1건(세 지수값 전부)으로 합친다. 세 지수 중 하나라도 없는 날짜는 모델
    요구사항(gt=0 필수 3종)을 못 채워 건너뛴다.

    2026-09-01 수정 — 전체 응답 봉투(`{"status":..., "data": {"tableData":
    ...}}`)뿐 아니라 그 안의 `data` 페이로드만 떼어 낸 형태(`{"tableData":
    ...}`, 발주처 기획문서 `report_summary/메뉴/광물전망지표/광물종합지수/
    getLineChartIndx.json`이 이 모양)도 그대로 받는다 — 그 파일로 실측
    검증한 결과 봉투 없이 `tableData`가 최상위에 바로 있어 기존 코드로는
    0건으로 파싱됐다."""

    payload = raw.get("data") if isinstance(raw.get("data"), dict) else raw
    table = payload.get("tableData") or []
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


def _komis_ymd_to_month(crtr_ymd) -> str | None:
    """KOMIS `crtrYmd`(시장동향지표는 "YYYYMMDD" 8자리 — 매월 1일자 스냅샷,
    수급동향지표는 "YYYYMM" 6자리)를 둘 다 report_gen `Month`("YYYY-MM")로
    정규화한다. 두 형식 모두 앞 6자리가 그대로 연월이라 슬라이스 하나로
    충분하다(2026-09-01, `getListIndxMnrk`/`getListIndxSplyBalncMnrk`
    실측 확인)."""

    text = str(crtr_ymd or "").strip()
    if len(text) < 6 or not text[:6].isdigit():
        return None
    return f"{text[0:4]}-{text[4:6]}"


def _parse_komis_indicator_list_response(raw: dict | list, score_field: str) -> list[dict]:
    """시장동향·수급동향 지표 리스트 응답 공통 파서(2026-09-01 신설).

    `getListIndxMnrk`(시장동향, `score_field="mrktPrspectIdct"`)·
    `getListIndxSplyBalncMnrk`(수급동향, `score_field="spdmStbtIndx"`) 둘 다
    `{"data": [...행들], "chartData": {...}}` 모양이다(실측). `chartData`는
    `data`를 그래프용으로 재구성한 값이라 안 쓴다(같은 정보의 중복). 행마다
    있는 `realPrc`(실질가격)를 `price`로, `crisisYn`("Y"/"N")을 `crisis_flag`로
    옮긴다. `flutRt`/`flutPrc`/`realFlutRt`/`realFlutPrc`(전월 대비 등락)는
    이미 `IndicatorObservation` 목록에서 인접 월 비교로 재계산하는 값과
    같아서(계산기가 이미 그 일을 함) 옮기지 않는다.

    KOMIS는 두 응답 모두 최신월이 먼저 오는 내림차순으로 행을 준다(실측) —
    `summary.py::_calculate_summary`는 (composite와 달리) 내부에서 재정렬하지
    않고 `observations[-1]`을 그대로 "현재"로 쓰므로, 여기서 오름차순으로
    정렬해 반환하지 않으면 가장 오래된 달이 "현재"로 잘못 계산된다(실측
    재현됨).

    2026-09-02 skeptic 2차 감사 SC-R2-006: `Month`(YYYY-MM)는 KOMIS `crtrYmd`
    앞 6자리라 월중 재게시로 같은 달에 `crtrYmd`가 두 번(예: 20260801·20260815)
    오면 같은 달이 관측치 2건으로 중복돼, 그 달이 "전월"과 나란히 비교되는
    사고가 날 수 있다 — 발주처 제공 실측 덤프(23개월치, 시장동향)에선 중복이
    없었지만(월당 1행 확인됨) 다른 기간·광종에서 재게시가 없다는 보장은 없어
    방어적으로 dedup한다. KOMIS가 최신 `crtrYmd`를 먼저 주므로(내림차순), 같은
    달이 반복되면 먼저 나온 쪽(=그 달 안에서 가장 최근 crtrYmd)만 남긴다."""

    rows = raw.get("data") if isinstance(raw, dict) else raw
    if not isinstance(rows, list):
        return []
    observations: list[dict] = []
    seen_months: set[str] = set()
    for row in rows:
        month = _komis_ymd_to_month(row.get("crtrYmd"))
        score = _komis_num(row.get(score_field))
        if month is None or score is None or month in seen_months:
            continue
        seen_months.add(month)
        entry: dict = {"month": month, "score": score}
        price = _komis_num(row.get("realPrc"))
        if price is not None:
            entry["price"] = price
        crisis_raw = row.get("crisisYn")
        if crisis_raw is not None:
            entry["crisis_flag"] = str(crisis_raw).strip().upper() == "Y"
        observations.append(entry)
    observations.sort(key=lambda item: item["month"])
    return observations


def _parse_komis_market_response(raw: dict | list) -> list[dict]:
    """`getListIndxMnrk`(시장동향지표) 원본 응답 → observations."""

    return _parse_komis_indicator_list_response(raw, "mrktPrspectIdct")


def _parse_komis_supply_response(raw: dict | list) -> list[dict]:
    """`getListIndxSplyBalncMnrk`(수급동향지표) 원본 응답 → observations."""

    return _parse_komis_indicator_list_response(raw, "spdmStbtIndx")


def _parse_komis_supply_snapshot_response(raw: dict) -> tuple[dict, str | None, str | None]:
    """`getChartDataSpdmStbt`(수급동향지표 상세) 원본 응답 →
    (supply_auxiliary dict, mineral_code, mineral_name), 2026-09-01 신설.

    `subChart02`(수입량·수입액 5개년, yaxisTitle "수입량(톤)"/oppoTitle
    "수입액(백만$)" 라벨 그대로 신뢰 — 사용자가 2024년 값 12,416,224가
    이상해 보인다고 재확인 요청했으나 "라벨 그대로 백만$가 맞음"으로 확정)
    → `domestic_imports`.

    `subChart03`(국가별 파이, 라벨 없이 `series`/`labels` 두 배열만 줌)은
    사용자 실측 확인(2026-09-01, "일본 데이터에서 454240인 필드는 금액(USD)")
    으로 단일 값이 **금액(USD, 백만달러 아님)**임을 확정했다 — 중량(kg)은
    이 응답에 없어(`SupplyImportDependencyObservation.weight_kg`를 선택
    필드로 완화) `amount_usd`만 채우고, `share_percent`는 이 표에 나열된
    국가들의 합계 대비 비중으로 계산한다(세계 총액이 아님 — `komis_share_
    response`/`market_share`의 "소계 대비 비중" 선례와 같은 결). 상위 3개국
    합을 `top_three_dependency_percent`로 둔다.

    `subChart01`(실질가격)은 핵심 관측치(`IndicatorObservation.price`,
    `getListIndxSplyBalncMnrk`의 `realPrc`)와 같은 값의 중복이라 안 쓴다.

    `subChart04`(국가별 생산량, "세계 공급 편중도", 2026-09-10 추가) —
    subChart02/03과 달리 `labels`/`series` 쌍이 아니라 국가당 1행인 리스트
    (`[{"prdctnQuty":..., "ntnKornNm":..., "crtrYr":..., ...}, ...]`)다.
    KOMIS가 주는 `prdtnRt`/`totalPrdctnQuty`는 신뢰하지 않는다 — 실측
    확인 결과 `totalPrdctnQuty`가 모든 행에 1위국 자신의 생산량과 똑같이
    찍혀 있어(예: 중국 900·러시아 6·일본 3인데 `totalPrdctnQuty`가 세
    행 다 900) `prdtnRt` 합이 100%를 넘는다 — map_mineral 세계총계 버그
    (2026-09-09)와 같은 신뢰 불가 패턴. `subChart03`처럼 나열된 국가의
    생산량 합계를 직접 구해 그 소계 대비로 `share_percent`를 다시
    계산한다 → `production_shares`(전체)+`top_country_production_share_
    percent`(1위국 비중).

    `subChart07`(국가별 매장량)은 대응 모델 필드가 없어 파싱하지 않는다
    (§`models.py`의 `SupplyAuxiliaryData` docstring 참고, 5개 요인에 없는
    항목이라 범위 밖).

    `subChart05`(세계 수요-공급, "세계수급비율", 2026-09-10 사용자 후속
    지시로 파싱 구현) — subChart02처럼 `xaxis`(연도 라벨)+`series`(이름별
    배열) 쌍이다. 이름 "수요"/"공급"/"과부족" 그대로 신뢰하고, "과부족"이
    없거나 결측이면 공급-수요로 직접 계산한다(KOMIS가 이미 계산해 주는
    값이 있으면 그쪽을 우선 — `subChart02`의 수입액과 같은 "라벨 그대로
    신뢰" 원칙). 갈륨 실측 덤프는 여전히 xaxis·수요·공급·과부족 전부
    빈 배열이라(2026-09-10 재확인) 갈륨에서는 이 factor가 생략되지만,
    다른 광종은 값이 있을 수 있어 파싱 자체는 항상 시도한다.

    단위·부호는 2026-09-10 동(CU) 실측(사용자가 KOMIS 화면에서 직접
    캡처해 제공)으로 확정했다 — "천톤" 단위는 2024년 세계 수요 26,751이
    실제 세계 정제동 생산량(연 약 2,600만~2,700만 톤)과 맞아떨어져
    확인됐고, "과부족" 부호(공급-수요, 양수=과잉)는 제공된 10개 연도
    값 중 8개가 공급-수요와 정확히 일치(나머지 2개는 소수점 반올림 오차
    1)로 확인됐다.

    ⚠ subChart05는 과거~미래 예측을 함께 담은 다년 시계열이다(동 실측:
    2024~2033년 10개년, 2027년 이후는 예측치로 추정됨) — 호출부
    (`indicator_summary.py`)가 최대 연도가 아니라 관측 시점(current.month)에
    가장 가까운 연도를 고르도록 돼 있다(최대 연도를 그대로 쓰면 몇 년
    뒤 예측치가 "현재 수급비율"로 잘못 표시되는 버그가 실측 재현으로
    발견·수정됨) — 이 함수(파서)는 연도 선택에 관여하지 않고 전체
    시계열을 그대로 넘긴다."""

    payload = raw.get("data") if isinstance(raw.get("data"), dict) else raw
    if not isinstance(payload, dict):
        return {}, None, None

    chart_info = payload.get("chartSpdmStbt") or {}
    mineral_code = chart_info.get("mnrkndUnqCd") or None
    mineral_name = chart_info.get("mnrkndKornNm") or None

    aux: dict = {}

    sub02 = payload.get("subChart02") or {}
    labels = sub02.get("labels") or []
    series_by_name = {
        item.get("name"): item.get("data") or [] for item in (sub02.get("series") or [])
    }
    weights = series_by_name.get("수입량") or []
    amounts = series_by_name.get("수입액") or []
    domestic_imports = []
    for index, year_label in enumerate(labels):
        year = _komis_num(year_label)
        if year is None or index >= len(weights) or index >= len(amounts):
            continue
        weight = _komis_num(weights[index])
        amount = _komis_num(amounts[index])
        if weight is None or amount is None:
            continue
        domestic_imports.append(
            {
                "year": int(year),
                "import_weight_ton": weight,
                "import_amount_million_usd": amount,
            }
        )
    if domestic_imports:
        aux["domestic_imports"] = domestic_imports

    sub03 = payload.get("subChart03") or {}
    sub03_labels = sub03.get("labels") or []
    sub03_series = sub03.get("series") or []
    sub03_year = _komis_num(sub03.get("crtrYr"))
    rows = [
        (name, _komis_num(value))
        for name, value in zip(sub03_labels, sub03_series)
    ]
    rows = [(name, value) for name, value in rows if value is not None]
    total = sum(value for _, value in rows)
    if sub03_year is not None and total > 0:
        rows.sort(key=lambda item: item[1], reverse=True)
        import_dependencies = [
            {
                "year": int(sub03_year),
                "country_name": name,
                "amount_usd": value,
                "share_percent": value / total * 100,
            }
            for name, value in rows
        ]
        aux["import_dependencies"] = import_dependencies
        aux["top_three_dependency_percent"] = min(
            100.0, sum(row["share_percent"] for row in import_dependencies[:3])
        )

    sub04 = payload.get("subChart04") or []
    production_rows = []
    for row in sub04 if isinstance(sub04, list) else []:
        year = _komis_num(row.get("crtrYr"))
        quantity = _komis_num(row.get("prdctnQuty"))
        name = row.get("ntnKornNm") or row.get("ntnEngNm")
        if year is None or quantity is None or quantity <= 0 or not name:
            continue
        production_rows.append((int(year), name, quantity))
    production_total = sum(quantity for _, _, quantity in production_rows)
    if production_rows and production_total > 0:
        production_rows.sort(key=lambda item: item[2], reverse=True)
        production_shares = [
            {
                "year": year,
                "country_name": name,
                "production_qty": quantity,
                "share_percent": quantity / production_total * 100,
            }
            for year, name, quantity in production_rows
        ]
        aux["production_shares"] = production_shares
        aux["top_country_production_share_percent"] = min(
            100.0, production_shares[0]["share_percent"]
        )

    sub05 = payload.get("subChart05") or {}
    sub05_labels = sub05.get("xaxis") or []
    sub05_series_by_name = {
        item.get("name"): item.get("data") or [] for item in (sub05.get("series") or [])
    }
    demands = sub05_series_by_name.get("수요") or []
    supplies = sub05_series_by_name.get("공급") or []
    balances = sub05_series_by_name.get("과부족") or []
    world_balances = []
    for index, year_label in enumerate(sub05_labels):
        year = _komis_num(year_label)
        if year is None or index >= len(demands) or index >= len(supplies):
            continue
        demand = _komis_num(demands[index])
        supply = _komis_num(supplies[index])
        if demand is None or supply is None:
            continue
        balance = _komis_num(balances[index]) if index < len(balances) else None
        if balance is None:
            balance = supply - demand
        world_balances.append(
            {
                "year": int(year),
                "demand_thousand_ton": demand,
                "supply_thousand_ton": supply,
                "balance_thousand_ton": balance,
            }
        )
    if world_balances:
        aux["world_balances"] = world_balances

    return aux, mineral_code, mineral_name


_KOMIS_FORECAST_PERIOD_RE = re.compile(r"^(\d{2})년\s*(?:(\d)Q)?")


def _parse_komis_price_forecast_response(raw: dict) -> tuple[list[dict], str | None]:
    """`getListPricePredc` 원본 응답(2026-08-29 Phase4 라이브재검증) →
    observations + mineral_name. `data[]`의 `crtrPrd`("28년 4Q"/"01년 1Q"
    형식, 2000년대만 관측됨)를 `YYYY-QN`/`YYYY`로, `realYn`(Y=확정 실적/
    N=예측)을 `is_actual`로 변환한다(§models.py
    `PriceForecastObservation.is_actual` 참고). 각 행의 `mnrkndKornNm`
    (예: "니켈")도 mineral_name으로 뽑는다(2026-08-31 추가 — price
    파서와 같은 패턴, 호출자가 명시한 mineral_name이 있으면 그쪽 우선)."""

    rows = raw.get("data") or []
    observations: list[dict] = []
    mineral_name = None
    for row in rows:
        if mineral_name is None:
            mineral_name = row.get("mnrkndKornNm") or None
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
    return observations, mineral_name


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




def normalize_price_request(request: AnalysisSummaryRequest) -> _KomisPriceParsed:
    """원본 JSON과 기존 수동 입력의 우선순위를 한 번만 결정한다.

    본문 관측치는 KOMIS 우선, 이름·단위는 명시 입력 우선이다.
    비교 관측치/기간 비교의 None은 기존 입력으로 폴백하지만 빈 배열/dict는 유지한다.
    """
    parsed = (
        _parse_komis_price_response(request.komis_response)
        if request.komis_response is not None
        else _KomisPriceParsed(request.observations, None, None, None, None, None, None)
    )
    return _KomisPriceParsed(
        observations=parsed.observations,
        compare_observations=(parsed.compare_observations if parsed.compare_observations is not None
                              else request.compare_observations),
        komis_period_comparisons=(parsed.komis_period_comparisons if parsed.komis_period_comparisons is not None
                                  else request.komis_period_comparisons),
        mineral_name=request.mineral_name or parsed.mineral_name or request.mineral,
        price_criterion=request.price_criterion or parsed.price_criterion,
        compare_mineral_name=request.compare_mineral_name or parsed.compare_mineral_name or request.compare_mineral,
        compare_price_criterion=request.compare_price_criterion or parsed.compare_price_criterion,
        price_unit=request.price_unit or parsed.price_unit,
    )
