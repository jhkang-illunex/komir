"""KOMIS AJAX 원본 응답 JSON → report_gen 요청 스키마 변환 (2026-08-30, 사용자 지시).

report_gen 원칙("prompt 제외 DB/외부호출 없음, 외부에서 입력된 값을 정리·요약")과
맞추기 위해, 이 데모는 komis.or.kr을 직접 호출하지 않는다(2026-08-30 오전
"실시간 가져오기" 시도는 이 세션에서 komis.or.kr 자체가 네트워크 레벨로 막혀
있어 취소됨). 대신 **사람이 외부에서(브라우저 개발자도구·curl 등) KOMIS를
직접 조회해 얻은 원본 JSON을 화면에 그대로 붙여넣으면**, 이 모듈이 그걸
report_gen이 원하는 형태로 넘긴다 — price_* 4종은 report_gen이 직접 파싱하는
`komis_response` 필드로 원본을 그대로 전달하고(passthrough), 나머지(map_*·
indicator_composite·forecast_price)는 아직 report_gen이 원본을 못 받아
`observations`(+`komis_trade_totals`)로 이 모듈이 손 변환한다.

원본 캡처 구조는 전부 `documents/산출물/2026-W35_0824-0830/
report_gen_KOMIS라이브재검증_Phase{1,2,3,4}_260829_evidence/`의 실측 JSON을
근거로 했다(값을 지어내지 않는다는 원칙) — 각 함수 docstring에 출처 명시.

2026-08-30 추가: price_minor_metals/iron_energy/other도 base_metals와 같은
엔드포인트(getMnrlPrcByMnrkndUnqCd, 광종코드만 다름)라는 가설을 Phase2 evidence
(코발트·철·금 raw 캡처)로 확인해 `convert_price_snapshot`을 그대로 재사용한다.

2026-08-30 재변경(report_gen 구조변경 반영): report_gen이 price_* 4종 전용
`komis_response: dict` 필드를 신설해 KOMIS 원본 응답을 그대로 받아 내부에서
직접 파싱하도록 바뀌었다(`observations`/`komis_period_comparisons` 손 매핑
과정에서 실제 버그가 두 번 났던 바로 그 계층 — 문서
`documents/산출물/2026-W35_0824-0830/report_gen_komis_response_직접수용_260830.md`
참고). 이에 맞춰 `convert_price_snapshot`(손 매핑)을 제거하고 원본을 그대로
전달하는 `passthrough_price_response`로 교체했다 — 4종 모두 이제 report_gen이
직접 파싱한다.

⚠ price_group·indicator_market/supply는 원본 캡처가 없거나(후자 2개는 로그인
필요 페이지) 엔드포인트가 확정되지 않아 이 변환기 목록에 없다 — 그 페이지들은
기존 방식(observations 수동 JSON 입력)을 그대로 쓴다."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable


class KomisRawConversionError(ValueError):
    """붙여넣은 KOMIS 원본 JSON의 구조가 예상과 달라 변환할 수 없을 때."""


def _ymd_to_iso(raw: str | None, *, fallback: str = "2025-01-01") -> str:
    if raw and len(raw) == 8 and raw.isdigit():
        return f"{raw[:4]}-{raw[4:6]}-{raw[6:]}"
    return fallback


def passthrough_price_response(raw: dict, ctx: dict) -> dict:
    """price_base_metals/price_minor_metals/price_iron_energy/price_other —
    2026-08-30 report_gen이 이 4종 전용 `komis_response: dict` 필드를 신설해
    KOMIS 원본 응답(`{"dataAvg":..., "data":...}`)을 그대로 받아 내부에서
    직접 파싱하도록 바뀌었다(`observations`/`komis_period_comparisons` 손
    매핑 과정에서 실제 버그가 두 번 났던 바로 그 계층을 없앤 것 —
    `report_gen_komis_response_직접수용_260830.md` 참고). 클라이언트는 더 이상
    날짜 변환·0.00 결측 정규화·기간평균 역산을 하지 않고 원본을 그대로
    전달한다."""

    if not isinstance(raw, dict) or "dataAvg" not in raw:
        raise KomisRawConversionError(
            "dataAvg를 찾을 수 없습니다 — 가격 조회 결과(getMnrlPrcByMnrkndUnqCd) JSON이 맞는지 확인하세요."
        )
    return {"komis_response": raw}


def convert_map_korea(raw: dict, ctx: dict) -> dict:
    """map_korea — 실측: Phase3 `map_korea_live_capture_260829.json`
    (getListKoreaData, MNRL0008=동). `list`가 국가별 관측치, 각 행의
    `sumIncmAmt`/`sumIncmWeig`(또는 수출이면 `sumExpAmt`/`sumExpWeig`)가
    `komis_trade_totals`(30행 절단 대비 진짜 총액). 응답 자체엔 날짜가 없어
    쿼리 파라미터 `srchDateS`(조회 시작일)를 관측일로 쓴다."""

    rows = raw.get("list")
    if not isinstance(rows, list) or not rows:
        raise KomisRawConversionError("list(국가별 목록)를 찾을 수 없습니다 — 국내 수급지도 조회 결과(getListKoreaData) JSON이 맞는지 확인하세요.")

    direction = ctx.get("trade_direction") or "import"
    date_fmt = _ymd_to_iso(raw.get("srchDateS") or raw.get("srchDatePS"))

    observations = []
    for r in rows:
        obs: dict[str, Any] = {"date": date_fmt, "country_code": r.get("ntnCd"), "country_name": r.get("ntnKornNm")}
        if direction == "export":
            obs["export_weight"] = r.get("expWeig")
            obs["export_amount"] = r.get("expAmt")
        else:
            obs["import_weight"] = r.get("incmWeig")
            obs["import_amount"] = r.get("incmAmt")
        observations.append(obs)

    result: dict[str, Any] = {"observations": observations}
    first = rows[0]
    if direction == "export" and first.get("sumExpAmt") is not None:
        result["komis_trade_totals"] = {"export_amount": first.get("sumExpAmt"), "export_weight": first.get("sumExpWeig")}
    elif direction != "export" and first.get("sumIncmAmt") is not None:
        result["komis_trade_totals"] = {"import_amount": first.get("sumIncmAmt"), "import_weight": first.get("sumIncmWeig")}
    return result


def convert_map_global(raw: dict, ctx: dict) -> dict:
    """map_global — 실측: Phase3 `map_global_live_capture_260829.json`
    (getListDataNation, MNRL0008=동). `list`가 루트별(원산지→도착지) 관측치,
    `sumAmt`/`sumWeig`가 komis_trade_totals(30행 절단 문제의 실측 사례 —
    round5 검증근거에서 naive합산 72억 vs 진짜총액 264억으로 확인됨)."""

    rows = raw.get("list")
    if not isinstance(rows, list) or not rows:
        raise KomisRawConversionError("list(루트별 목록)를 찾을 수 없습니다 — 글로벌 수급지도 조회 결과(getListDataNation) JSON이 맞는지 확인하세요.")

    date_fmt = _ymd_to_iso(raw.get("srchDateS") or raw.get("srchDatePS"))
    observations = [
        {
            "date": date_fmt,
            "country_code": r.get("incmNtnCd"), "country_name": r.get("incmNtnNm"),
            "import_weight": r.get("weig"), "import_amount": r.get("amt"),
            "origin_country_code": r.get("expNtnCd"), "origin_country_name": r.get("expNtnNm"),
        }
        for r in rows
    ]
    result: dict[str, Any] = {"observations": observations}
    first = rows[0]
    if first.get("sumAmt") is not None:
        result["komis_trade_totals"] = {"import_amount": first.get("sumAmt"), "import_weight": first.get("sumWeig")}
    return result


def convert_map_mineral(raw: dict, ctx: dict) -> dict:
    """map_mineral — 실측: Phase3 `map_mineral_live_capture_260829.json`
    (getListMapMnrlData, MNRL0008=동, 2025년). `measure` 선택(매장량/생산량)에
    따라 `burudgQuty`/`prdctnQuty`를 쓰고 "천톤" 단위로 환산(÷1000, cdVal="k
    ton" 확인). 응답 1건 = 연도 1개 스냅샷이라 서버 "연도≥2" 요건을 채우려면
    ⚠ end_year와 start_year가 다르면 **같은 스냅샷을 두 연도에 복제**한다
    (round5와 동일한 한계 — 실측은 최신연도뿐)."""

    rows = raw.get("data")
    if not isinstance(rows, list) or not rows:
        raise KomisRawConversionError("data(국가별 매장량/생산량 목록)를 찾을 수 없습니다 — 광물지도 조회 결과(getListMapMnrlData) JSON이 맞는지 확인하세요.")

    measure = ctx.get("measure") or "reserves"
    value_key = "burudgQuty" if measure == "reserves" else "prdctnQuty"

    def _year(raw_value: Any, default: int) -> int:
        try:
            return int(raw_value)
        except (TypeError, ValueError):
            return default

    end_year = _year(ctx.get("end_year"), _year(ctx.get("start_year"), 2025))
    start_year = _year(ctx.get("start_year"), end_year - 1)

    def _rows_for_year(year: int) -> list[dict]:
        out = []
        for r in rows:
            value = r.get(value_key)
            if value is None:
                continue
            out.append({
                "year": year, "country_code": r.get("ntnEngCd"), "country_name": r.get("ntnKornNm"),
                "value": round(float(value) / 1000, 1),
            })
        return out

    observations = []
    if start_year != end_year:
        observations.extend(_rows_for_year(start_year))
    observations.extend(_rows_for_year(end_year))
    if not observations:
        raise KomisRawConversionError(f"'{value_key}' 필드가 있는 행이 없습니다 — measure 선택과 실제 데이터가 일치하는지 확인하세요.")
    return {"observations": observations}


def convert_indicator_composite(raw: dict, ctx: dict) -> dict:
    """indicator_composite — 실측: Phase4 `composite_forecast_live_capture
    _260829.json`(getLineChartIndx). `data.xaxis`(날짜)+`data.series`(MNRL/
    MAJOR/RARE 3종 시계열)를 나란히 묶어 일자별 관측치로 변환한다.

    ⚠ 최신 스냅샷 1건(`data.dataIndx`)만으로는 report_gen이 "최근 한 주 변화"를
    계산할 비교 시점이 없어 NO_DATA를 반환함을 실측으로 확인했다(4건 이상,
    1주 이상 시차가 있으면 status:ok) — 그래서 스냅샷이 아니라 반드시
    `series`(시계열) 전체를 변환 대상으로 삼는다."""

    body = raw.get("data", raw)
    xaxis = body.get("xaxis") if isinstance(body, dict) else None
    series_list = body.get("series") if isinstance(body, dict) else None
    if not isinstance(xaxis, list) or not isinstance(series_list, list) or not series_list:
        raise KomisRawConversionError(
            "data.xaxis/data.series를 찾을 수 없습니다 — 광물종합지수 조회 결과(getLineChartIndx)의 시계열 응답 JSON이 맞는지 확인하세요"
            "(dataIndx 스냅샷만으로는 report_gen이 추세를 계산할 수 없습니다)."
        )
    series = {s.get("indxTp"): s.get("data") for s in series_list if isinstance(s, dict)}
    if not all(k in series and isinstance(series[k], list) for k in ("MNRL", "MAJOR", "RARE")):
        raise KomisRawConversionError("series에 MNRL/MAJOR/RARE(광물종합·메이저·희소금속지수) 3종이 모두 있어야 합니다.")

    n = min(len(xaxis), len(series["MNRL"]), len(series["MAJOR"]), len(series["RARE"]))
    observations = []
    for i in range(n):
        date_raw = xaxis[i]
        if not isinstance(date_raw, str) or date_raw.count(".") != 2:
            continue  # 관측된 이상치(비정상 날짜 포맷 1건) 방어
        observations.append({
            "date": date_raw.replace(".", "-"),
            "composite_index": series["MNRL"][i], "major_metals_index": series["MAJOR"][i],
            "minor_metals_index": series["RARE"][i],
        })
    if not observations:
        raise KomisRawConversionError("xaxis 날짜 형식을 해석할 수 있는 행이 없습니다.")
    return {"observations": observations}


_QUARTER_RE = re.compile(r"(\d+)년\s*(\d+)Q")
_YEAR_ONLY_RE = re.compile(r"(\d+)년$")


def convert_forecast_price(raw: dict, ctx: dict) -> dict:
    """forecast_price — 실측: Phase4 `composite_forecast_live_capture_260829
    .json`(getListPricePredc, 니켈·중기). `crtrPrd`("26년 2Q" 또는 장기면
    "2030년" 형태)를 period로, `realYn`(Y=확정실적/N=예측치)을 is_actual로
    매핑. 원본이 미래→과거 역순이라 시간순으로 뒤집는다."""

    rows = raw.get("data")
    if not isinstance(rows, list) or not rows:
        raise KomisRawConversionError("data(분기·연도별 예측 목록)를 찾을 수 없습니다 — 가격예측 조회 결과(getListPricePredc) JSON이 맞는지 확인하세요.")

    observations = []
    for r in rows:
        crtr_prd = str(r.get("crtrPrd", ""))
        m = _QUARTER_RE.match(crtr_prd)
        if m:
            yy, q = m.groups()
            period = f"{2000 + int(yy)}-Q{q}"
        else:
            m2 = _YEAR_ONLY_RE.match(crtr_prd)
            if not m2:
                continue
            period = str(2000 + int(m2.group(1)))
        try:
            price = float(str(r.get("prc", "")).replace(",", ""))
        except ValueError:
            continue
        observations.append({"period": period, "price": price, "is_actual": r.get("realYn") == "Y"})

    if not observations:
        raise KomisRawConversionError("crtrPrd/prc 형식을 해석할 수 있는 행이 없습니다.")
    observations.reverse()
    return {"observations": observations}


@dataclass(frozen=True)
class KomisRawPage:
    label: str
    convert: Callable[[dict, dict], dict]
    example_raw_json: str


KOMIS_RAW_PAGES: dict[str, KomisRawPage] = {
    "price_base_metals": KomisRawPage(
        "가격 조회 결과(getMnrlPrcByMnrkndUnqCd)",
        passthrough_price_response,
        '{"dataAvg": {"stdMap": {"MONTH": {"flctnPrc": "964.83", "crtrYmd": "202608", "flctnPrcnt": "7.13"}, '
        '"YEAR": {"flctnPrc": "4545.06", "crtrYmd": "2026", "flctnPrcnt": "45.70"}, '
        '"CRTRYMD": {"crtrYmd": "20260827", "cmercPrc": "14490.00"}, '
        '"INFO": {"mnrkndKornNm": "동", "prcCrtr": "LME CASH", "isISE": "N", "weigUnitCd": "ton", "prcUnitCdNm": "USD"}, '
        '"WEEK": {"flctnPrc": "124.80", "crtrYmd": "20260824", "flctnPrcnt": "0.87"}, '
        '"DAY": {"flctnPrc": "-35.00", "crtrYmd": "20260827", "flctnPrcnt": "-0.24", "cmercPrc": 14490}}, '
        '"INFO": {"mnrkndKornNm": "동", "prcCrtr": "LME CASH", "isISE": "N", "weigUnitCd": "ton", "prcUnitCdNm": "USD"}}, '
        '"data": {"compareMnrl": [], "defaultMnrl": [{"lowstPrc": "0.00", "invt": "235575.00", "flctnPrc": "-35.00", '
        '"invtPrcnt": "-0.80", "invtPrc": "-1900.00", "hghstPrc": "0.00", "crtrYmd": "20260827", '
        '"flctnPrcnt": "-0.24", "cmercPrc": "14490.00"}]}}',
    ),
    "price_minor_metals": KomisRawPage(
        # 실측: Phase2 collected_minor_spotcheck_raw_260829.json(코발트|LME
        # CASH) — base_metals와 동일 엔드포인트·구조(광종코드만 다름) 가설을
        # 이 실측 캡처로 확인했다.
        "가격 조회 결과(getMnrlPrcByMnrkndUnqCd)",
        passthrough_price_response,
        '{"dataAvg": {"stdMap": {"MONTH": {"flctnPrc": "-13.04", "crtrYmd": "202608", "flctnPrcnt": "-0.02"}, '
        '"YEAR": {"flctnPrc": "21039.47", "crtrYmd": "2026", "flctnPrcnt": "60.42"}, '
        '"CRTRYMD": {"crtrYmd": "20260827", "cmercPrc": "55860.00"}, '
        '"INFO": {"mnrkndKornNm": "코발트", "prcCrtr": "LME CASH", "isISE": "N", "weigUnitCd": "ton", "prcUnitCdNm": "USD"}, '
        '"WEEK": {"flctnPrc": "10.00", "crtrYmd": "20260824", "flctnPrcnt": "0.02"}, '
        '"DAY": {"flctnPrc": "20.00", "crtrYmd": "20260827", "flctnPrcnt": "0.04", "cmercPrc": 55860}}, '
        '"INFO": {"mnrkndKornNm": "코발트", "prcCrtr": "LME CASH", "isISE": "N", "weigUnitCd": "ton", "prcUnitCdNm": "USD"}}, '
        '"data": {"compareMnrl": [], "defaultMnrl": [{"lowstPrc": "0.00", "invt": "0.00", "flctnPrc": "20.00", '
        '"invtPrcnt": "0.00", "invtPrc": "0.00", "hghstPrc": "0.00", "crtrYmd": "20260827", '
        '"flctnPrcnt": "0.04", "cmercPrc": "55860.00"}]}}',
    ),
    "price_iron_energy": KomisRawPage(
        # 실측: Phase2 collected_iron_other_day_raw_260829.json(철|Australian
        # 62%min CNF China).
        "가격 조회 결과(getMnrlPrcByMnrkndUnqCd)",
        passthrough_price_response,
        '{"dataAvg": {"stdMap": {"MONTH": {"flctnPrc": "1.91", "crtrYmd": "202608", "flctnPrcnt": "1.94"}, '
        '"YEAR": {"flctnPrc": "-1.71", "crtrYmd": "2026", "flctnPrcnt": "-1.67"}, '
        '"CRTRYMD": {"crtrYmd": "20260827", "cmercPrc": "100.50"}, '
        '"INFO": {"mnrkndKornNm": "철", "prcCrtr": "Australian 62%min CNF China", "isISE": "Y", "weigUnitCd": "mt", "prcUnitCdNm": "USD"}, '
        '"WEEK": {"flctnPrc": "1.40", "crtrYmd": "20260824", "flctnPrcnt": "1.41"}, '
        '"DAY": {"flctnPrc": "0.00", "crtrYmd": "20260827", "flctnPrcnt": "0.00", "cmercPrc": 100.5}}, '
        '"INFO": {"mnrkndKornNm": "철", "prcCrtr": "Australian 62%min CNF China", "isISE": "Y", "weigUnitCd": "mt", "prcUnitCdNm": "USD"}}, '
        '"data": {"compareMnrl": [], "defaultMnrl": [{"lowstPrc": "100.00", "invt": "0.00", "flctnPrc": "0.00", '
        '"invtPrcnt": "0.00", "invtPrc": "0.00", "hghstPrc": "101.00", "crtrYmd": "20260827", '
        '"flctnPrcnt": "0.00", "cmercPrc": "100.50"}]}}',
    ),
    "price_other": KomisRawPage(
        # 실측: Phase2 collected_iron_other_day_raw_260829.json(금|London Gold
        # Market Fixing Ltd- LBMA PM Fixing Price/USD).
        "가격 조회 결과(getMnrlPrcByMnrkndUnqCd)",
        passthrough_price_response,
        '{"dataAvg": {"stdMap": {"MONTH": {"flctnPrc": "495.03", "crtrYmd": "202608", "flctnPrcnt": "12.15"}, '
        '"YEAR": {"flctnPrc": "1137.41", "crtrYmd": "2026", "flctnPrcnt": "33.15"}, '
        '"CRTRYMD": {"crtrYmd": "20260827", "cmercPrc": "4568.95"}, '
        '"INFO": {"mnrkndKornNm": "금", "prcCrtr": "London Gold Market Fixing Ltd- LBMA PM Fixing Price/USD", "isISE": "N", "weigUnitCd": "troz", "prcUnitCdNm": "USD"}, '
        '"WEEK": {"flctnPrc": "101.94", "crtrYmd": "20260824", "flctnPrcnt": "2.28"}, '
        '"DAY": {"flctnPrc": "-62.55", "crtrYmd": "20260827", "flctnPrcnt": "-1.35", "cmercPrc": 4568.95}}, '
        '"INFO": {"mnrkndKornNm": "금", "prcCrtr": "London Gold Market Fixing Ltd- LBMA PM Fixing Price/USD", "isISE": "N", "weigUnitCd": "troz", "prcUnitCdNm": "USD"}}, '
        '"data": {"compareMnrl": [], "defaultMnrl": [{"lowstPrc": "0.00", "invt": "0.00", "flctnPrc": "-62.55", '
        '"invtPrcnt": "0.00", "invtPrc": "0.00", "hghstPrc": "0.00", "crtrYmd": "20260827", '
        '"flctnPrcnt": "-1.35", "cmercPrc": "4568.95"}]}}',
    ),
    "map_korea": KomisRawPage(
        "국가별 목록 조회 결과(getListKoreaData)",
        convert_map_korea,
        '{"srchMnrkndUnqCd": "MNRL0008", "srchDateS": "20260101", "srchDatePS": "20250101", '
        '"list": [{"incmAmt": 2546230722, "RNUM": 1, "expAmt": 3802109, "sumExpWeig": 434611356, "expWeig": 421606, '
        '"sumIncmAmt": 10941953600, "incmWeig": 458239149, "sumIncmWeig": 1410885344, "ntnCd": "CL", '
        '"ntnKornNm": "칠레", "sumExpAmt": 5130303324}, '
        '{"incmAmt": 1200849392, "RNUM": 2, "expAmt": 885490710, "sumExpWeig": 434611356, "expWeig": 59618405, '
        '"sumIncmAmt": 10941953600, "incmWeig": 138542249, "sumIncmWeig": 1410885344, "ntnCd": "US", '
        '"ntnKornNm": "미국", "sumExpAmt": 5130303324}, '
        '{"incmAmt": 1102245059, "RNUM": 3, "expAmt": 34085589, "sumExpWeig": 434611356, "expWeig": 2771043, '
        '"sumIncmAmt": 10941953600, "incmWeig": 103333842, "sumIncmWeig": 1410885344, "ntnCd": "AU", '
        '"ntnKornNm": "호주", "sumExpAmt": 5130303324}, '
        '{"incmAmt": 983212537, "RNUM": 4, "expAmt": 261, "sumExpWeig": 434611356, "expWeig": 18, '
        '"sumIncmAmt": 10941953600, "incmWeig": 76287183, "sumIncmWeig": 1410885344, "ntnCd": "CD", '
        '"ntnKornNm": "콩고민주공화국", "sumExpAmt": 5130303324}, '
        '{"incmAmt": 687233413, "RNUM": 5, "expAmt": 2004103624, "sumExpWeig": 434611356, "expWeig": 206001218, '
        '"sumIncmAmt": 10941953600, "incmWeig": 53455286, "sumIncmWeig": 1410885344, "ntnCd": "CN", '
        '"ntnKornNm": "중국", "sumExpAmt": 5130303324}], "listCount": "10"}',
    ),
    "map_global": KomisRawPage(
        "루트별 목록 조회 결과(getListDataNation)",
        convert_map_global,
        '{"srchMnrkndUnqCd": "MNRL0008", "srchDateS": "20260101", "srchDatePS": "20250101", '
        '"list": [{"RNUM": 1, "incmNtnNm": "일본", "incmNtnCd": "JP", "expNtnNm": "칠레", "amt": 912677544.84, '
        '"weig": 339553072, "sumWeig": 3887689462.98, "weigRate": "8.73", "sumAmt": 26396166408.81, '
        '"expNtnCd": "CL", "amtRate": "3.46"}, '
        '{"RNUM": 2, "incmNtnNm": "미국", "incmNtnCd": "US", "expNtnNm": "칠레", "amt": 855452708, '
        '"weig": 70155941, "sumWeig": 3887689462.98, "weigRate": "1.80", "sumAmt": 26396166408.81, '
        '"expNtnCd": "CL", "amtRate": "3.24"}, '
        '{"RNUM": 3, "incmNtnNm": "인도", "incmNtnCd": "IN", "expNtnNm": "칠레", "amt": 690138479.7, '
        '"weig": 224395654, "sumWeig": 3887689462.98, "weigRate": "5.77", "sumAmt": 26396166408.81, '
        '"expNtnCd": "CL", "amtRate": "2.61"}, '
        '{"RNUM": 4, "incmNtnNm": "일본", "incmNtnCd": "JP", "expNtnNm": "페루", "amt": 655218643.21, '
        '"weig": 242969854, "sumWeig": 3887689462.98, "weigRate": "6.25", "sumAmt": 26396166408.81, '
        '"expNtnCd": "PE", "amtRate": "2.48"}, '
        '{"RNUM": 5, "incmNtnNm": "일본", "incmNtnCd": "JP", "expNtnNm": "미국", "amt": 618509454.06, '
        '"weig": 156458746, "sumWeig": 3887689462.98, "weigRate": "4.02", "sumAmt": 26396166408.81, '
        '"expNtnCd": "US", "amtRate": "2.34"}], "listCount": "15"}',
    ),
    "map_mineral": KomisRawPage(
        "국가별 매장량/생산량 조회 결과(getListMapMnrlData)",
        convert_map_mineral,
        '{"data": [{"cdVal": "k ton", "prdctnQuty": 730000, "burudgQuty": 100000000, "ntnEngNm": "Australia", '
        '"ntnKornNm": "호주", "ntnEngCd": "AU"}, '
        '{"cdVal": "k ton", "prdctnQuty": 500000, "burudgQuty": 7000000, "ntnEngNm": "Canada", '
        '"ntnKornNm": "캐나다", "ntnEngCd": "CA"}, '
        '{"cdVal": "k ton", "prdctnQuty": 3200000, "burudgQuty": 80000000, "ntnEngNm": "Democratic Republic of Congo", '
        '"ntnKornNm": "콩고민주공화국", "ntnEngCd": "CD"}, '
        '{"cdVal": "k ton", "prdctnQuty": 5300000, "burudgQuty": 180000000, "ntnEngNm": "Chile", '
        '"ntnKornNm": "칠레", "ntnEngCd": "CL"}, '
        '{"cdVal": "k ton", "prdctnQuty": 1800000, "burudgQuty": 41000000, "ntnEngNm": "China", '
        '"ntnKornNm": "중국", "ntnEngCd": "CN"}]}',
    ),
    "indicator_composite": KomisRawPage(
        "광물종합지수 조회 결과(getLineChartIndx)",
        convert_indicator_composite,
        # 최근 10영업일 시계열(xaxis+series) — dataIndx 스냅샷 1건만으로는
        # NO_DATA임을 실측으로 확인해 시계열 전체를 예시로 남긴다(§변환함수 참고).
        '{"data": {"xaxis": ["2026.08.14", "2026.08.17", "2026.08.18", "2026.08.19", "2026.08.20", '
        '"2026.08.21", "2026.08.24", "2026.08.25", "2026.08.26", "2026.08.27"], '
        '"series": [{"indxTp": "MNRL", "name": "광물종합지수", '
        '"data": [3454.93, 3469.62, 3489.6, 3458.39, 3496.56, 3503.6, 3539.45, 3557.13, 3546.37, 3558.81]}, '
        '{"indxTp": "MAJOR", "name": "메이저금속지수", '
        '"data": [2969.95, 2981.77, 3003.3, 2955.1, 2942.08, 2938.34, 2968.06, 2977.82, 2974.51, 2999.54]}, '
        '{"indxTp": "RARE", "name": "희소금속지수", '
        '"data": [2905.63, 2906.34, 2906.34, 2906.34, 2906.34, 2906.34, 2911.8, 2911.8, 2911.8, 2911.8]}]}}',
    ),
    "forecast_price": KomisRawPage(
        "가격예측 조회 결과(getListPricePredc)",
        convert_forecast_price,
        '{"data": [{"prc": "20563.75", "flutRt": "4.32", "flutPrc": "850.67", "realYn": "N", "realPrc": "20563.75", '
        '"mnrkndKornNm": "니켈", "crtrPrd": "26년 4Q"}, '
        '{"prc": "19713.08", "flutRt": "6.80", "flutPrc": "1,254.56", "realYn": "N", "realPrc": "19713.08", '
        '"mnrkndKornNm": "니켈", "crtrPrd": "26년 3Q"}, '
        '{"prc": "18458.52", "flutRt": "6.35", "flutPrc": "1,102.49", "realYn": "Y", "realPrc": "18458.52", '
        '"mnrkndKornNm": "니켈", "crtrPrd": "26년 2Q"}, '
        '{"prc": "17356.03", "flutRt": "16.55", "flutPrc": "2,464.23", "realYn": "Y", "realPrc": "17356.03", '
        '"mnrkndKornNm": "니켈", "crtrPrd": "26년 1Q"}, '
        '{"prc": "14891.80", "flutRt": "-0.82", "flutPrc": "-122.97", "realYn": "Y", "realPrc": "14891.80", '
        '"mnrkndKornNm": "니켈", "crtrPrd": "25년 4Q"}, '
        '{"prc": "15014.77", "flutRt": "-1.03", "flutPrc": "-156.71", "realYn": "Y", "realPrc": "15014.77", '
        '"mnrkndKornNm": "니켈", "crtrPrd": "25년 3Q"}]}',
    ),
}
