"""KOMIS AJAX 원본 응답 JSON → report_gen 요청 스키마 변환 (2026-08-30, 사용자 지시).

report_gen 원칙("prompt 제외 DB/외부호출 없음, 외부에서 입력된 값을 정리·요약")과
맞추기 위해, 이 데모는 komis.or.kr을 직접 호출하지 않는다(2026-08-30 오전
"실시간 가져오기" 시도는 이 세션에서 komis.or.kr 자체가 네트워크 레벨로 막혀
있어 취소됨). 대신 **사람이 외부에서(브라우저 개발자도구·curl 등) KOMIS를
직접 조회해 얻은 원본 JSON을 화면에 그대로 붙여넣으면**, 이 모듈이 그걸
`komis_response` 필드에 그대로 실어 report_gen에 보낸다 — 9개 페이지 전부
(price_base_metals/minor_metals/iron_energy/other·map_korea/global/mineral·
indicator_composite·forecast_price) report_gen이 원본을 직접 파싱하므로,
이 모듈은 "구조가 맞는지" 얕은 검증만 하고 원본을 그대로 전달한다
(passthrough) — 필드명 손 매핑은 하지 않는다.

원본 캡처 구조는 전부 `documents/산출물/2026-W35_0824-0830/
report_gen_KOMIS라이브재검증_Phase{1,2,3,4}_260829_evidence/`의 실측 JSON을
근거로 했다(값을 지어내지 않는다는 원칙) — 각 함수 docstring에 출처 명시.

2026-08-30 이력:
1) price_minor_metals/iron_energy/other도 base_metals와 같은 엔드포인트
   (getMnrlPrcByMnrkndUnqCd, 광종코드만 다름)임을 Phase2 evidence(코발트·철·
   금 raw 캡처)로 확인해 같은 변환 로직을 재사용.
2) report_gen이 price_* 4종 전용 `komis_response: dict` 필드를 신설해 원본을
   직접 파싱하도록 바뀌면서(`observations`/`komis_period_comparisons` 손
   매핑 과정에서 실제 버그가 두 번 났던 바로 그 계층 — 문서
   `report_gen_komis_response_직접수용_260830.md`), 이 4종의 손 매핑
   (`convert_price_snapshot`)을 삭제하고 `passthrough_price_response`로
   교체.
3) 사용자가 "하위호환 무관 싹다 교체" 지시, report_gen이 나머지 5종
   (map_korea/global/mineral·indicator_composite·forecast_price)도
   `komis_response`로 확장(문서 `report_gen_komis_response_5종확장_260830.md`
   — map_mineral은 엔드포인트가 `getListMapMnrlChartData`로 바뀌었고
   indicator_composite는 `data.tableData`가 새 파서 입력임에 주의)해, 이
   5종의 손 매핑도 전부 passthrough로 교체.

⚠ indicator_market/supply는 로그인 필요 페이지라 원본 캡처가 없어 이 목록에
없다 — 그 페이지들은 기존 방식(observations 수동 JSON 입력)을 그대로 쓴다.
(price_group은 2026-08-31 report_gen 외부 인터페이스 자체가 삭제돼 이 데모의
PAGE_SPECS에서도 제거됐다 — §report_gen_client.py 주석 참고.)"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


class KomisRawConversionError(ValueError):
    """붙여넣은 KOMIS 원본 JSON의 구조가 예상과 달라 변환할 수 없을 때."""


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


def passthrough_map_korea(raw: dict, ctx: dict) -> dict:
    """map_korea — 2026-08-30 report_gen이 `getListKoreaData` 원본 응답을
    그대로 받아 내부에서 파싱한다(`_parse_komis_map_korea_response` —
    `list`+쿼리 파라미터 echo `srchDateE`를 직접 읽는다). 클라이언트는 손
    변환 없이 원본을 그대로 전달한다."""

    if not isinstance(raw, dict) or not isinstance(raw.get("list"), list):
        raise KomisRawConversionError("list(국가별 목록)를 찾을 수 없습니다 — 국내 수급지도 조회 결과(getListKoreaData) JSON이 맞는지 확인하세요.")
    return {"komis_response": raw}


def passthrough_map_global(raw: dict, ctx: dict) -> dict:
    """map_global — 2026-08-30 report_gen이 `getListDataNation` 원본 응답을
    그대로 받아 내부에서 파싱한다(`_parse_komis_map_global_response`)."""

    if not isinstance(raw, dict) or not isinstance(raw.get("list"), list):
        raise KomisRawConversionError("list(루트별 목록)를 찾을 수 없습니다 — 글로벌 수급지도 조회 결과(getListDataNation) JSON이 맞는지 확인하세요.")
    return {"komis_response": raw}


def passthrough_map_mineral(raw: dict, ctx: dict) -> dict:
    """map_mineral — 2026-08-31 report_gen이 이 페이지의 KOMIS 엔드포인트
    3개를 각각 다른 요청 필드로 받도록 확장됐다(계약: documents/산출물/
    2026-W36_0831-0906/report_gen_광물지도_2개엔드포인트_추가_260831.md) —
    `chart`(getListMapMnrlChartData, 연도별 시계열, 필수)·`snapshot`
    (getListMapMnrlData, 단일연도 국가별 스냅샷, 선택)·`share`
    (getListMnrlTablePrdctnBurgudg, 국가별 최근5개년+비중표, 선택)를 한
    JSON 객체로 묶어 붙여넣으면(§komis_fetch.py fetch_map_mineral과 같은
    envelope) 이 함수가 3개 요청 필드로 각각 갈라 보낸다. snapshot·share는
    없어도(하나만 있어도) 그대로 동작(report_gen 쪽 "독립적으로 동작"
    확인됨) — `measure`(매장량/생산량)는 응답 본문에 없는 조회 파라미터라
    여전히 호출자가 명시해야 한다."""

    if not isinstance(raw, dict) or not isinstance((raw.get("chart") or {}).get("data"), list):
        raise KomisRawConversionError(
            "chart.data(국가별 매장량/생산량 시계열)를 찾을 수 없습니다 — "
            '{"chart": <getListMapMnrlChartData 응답>, "snapshot": <getListMapMnrlData 응답, 선택>, '
            '"share": <getListMnrlTablePrdctnBurgudg 응답, 선택>} 형태로 붙여넣었는지 확인하세요.'
        )
    converted: dict = {"komis_response": raw["chart"]}
    if isinstance(raw.get("snapshot"), dict):
        converted["komis_snapshot_response"] = raw["snapshot"]
    if isinstance(raw.get("share"), dict):
        converted["komis_share_response"] = raw["share"]
    return converted


def passthrough_indicator_composite(raw: dict, ctx: dict) -> dict:
    """indicator_composite — 2026-08-30 report_gen이 `getLineChartIndx` 원본
    응답을 그대로 받아 내부에서 파싱한다(`_parse_komis_composite_response` —
    `data.tableData`의 날짜×지수유형(MNRL/MAJOR/RARE) 행을 crtrYmd로 묶는다).

    엔드포인트 전체 경로(2026-08-31 사용자 제공+라이브 재검증, 200 확인):
    `https://www.komis.or.kr/Komis/MnrlIndc/IndxMinDex/ajax/getLineChartIndx`
    (POST, srchDateS/srchDateE=yyyymmdd) — 페이지 URL(`/Komis/MnrlIndc/IndxMin`,
    §komis_menu_map.yaml)과 AJAX 세션 경로(`IndxMinDex`)가 다르므로 페이지를
    먼저 GET해 세션 쿠키를 받은 뒤 이 경로로 POST해야 한다(§모듈 docstring
    "KOMIS AJAX는 쿠키 동일출처 세션 필요" 원칙과 동일 — komis_fetch.py에 이
    페이지의 실시간 조회는 아직 없다, 있다면 이 패턴을 그대로 따를 것).

    ⚠ `data.xaxis`+`data.series`(예전 클라이언트 손 변환이 쓰던 필드)가 아니라
    `data.tableData`가 새 파서의 입력이다 — KOMIS 원본 응답엔 둘 다 있지만
    report_gen은 tableData만 읽는다."""

    body = raw.get("data", raw) if isinstance(raw, dict) else None
    if not isinstance(body, dict) or not isinstance(body.get("tableData"), list):
        raise KomisRawConversionError(
            "data.tableData를 찾을 수 없습니다 — 광물종합지수 조회 결과(getLineChartIndx) JSON이 맞는지 확인하세요."
        )
    return {"komis_response": raw}


def passthrough_forecast_price(raw: dict, ctx: dict) -> dict:
    """forecast_price — 2026-08-30 report_gen이 `getListPricePredc` 원본
    응답을 그대로 받아 내부에서 파싱한다(`_parse_komis_price_forecast_response`
    — `crtrPrd`→period, `realYn`→is_actual 변환까지 전부 서버가 한다)."""

    if not isinstance(raw, dict) or not isinstance(raw.get("data"), list):
        raise KomisRawConversionError("data(분기·연도별 예측 목록)를 찾을 수 없습니다 — 가격예측 조회 결과(getListPricePredc) JSON이 맞는지 확인하세요.")
    return {"komis_response": raw}


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
        passthrough_map_korea,
        # 실측: Phase3 map_korea_live_capture_260829.json(MNRL0024, 상위 5개국).
        # 2026-08-30 report_gen 확정 — 응답의 날짜는 행이 아니라 쿼리 파라미터
        # echo인 srchDateE(조회 종료일)에서 온다(예전 srchDateS 방식 아님).
        '{"srchMnrkndUnqCd": "MNRL0024", "srchDateS": "20260101", "srchDateE": "20261231", '
        '"list": [{"incmAmt": 2429691, "RNUM": 1, "expAmt": 668454, "sumExpWeig": 2504, "expWeig": 359, '
        '"sumIncmAmt": 6350539, "incmWeig": 1255, "sumIncmWeig": 3690, "ntnCd": "TW", "ntnKornNm": "대만", '
        '"sumExpAmt": 4246583}, '
        '{"incmAmt": 2106864, "RNUM": 2, "expAmt": 512149, "sumExpWeig": 2504, "expWeig": 270, '
        '"sumIncmAmt": 6350539, "incmWeig": 949, "sumIncmWeig": 3690, "ntnCd": "DE", "ntnKornNm": "독일", '
        '"sumExpAmt": 4246583}, '
        '{"incmAmt": 775645, "RNUM": 3, "expAmt": 1695825, "sumExpWeig": 2504, "expWeig": 965, '
        '"sumIncmAmt": 6350539, "incmWeig": 287, "sumIncmWeig": 3690, "ntnCd": "US", "ntnKornNm": "미국", '
        '"sumExpAmt": 4246583}, '
        '{"incmAmt": 690468, "RNUM": 4, "expAmt": 769144, "sumExpWeig": 2504, "expWeig": 423, '
        '"sumIncmAmt": 6350539, "incmWeig": 459, "sumIncmWeig": 3690, "ntnCd": "JP", "ntnKornNm": "일본", '
        '"sumExpAmt": 4246583}, '
        '{"incmAmt": 332372, "RNUM": 5, "expAmt": 13425, "sumExpWeig": 2504, "expWeig": 1, '
        '"sumIncmAmt": 6350539, "incmWeig": 736, "sumIncmWeig": 3690, "ntnCd": "CN", "ntnKornNm": "중국", '
        '"sumExpAmt": 4246583}], "listCount": "10"}',
    ),
    "map_global": KomisRawPage(
        "루트별 목록 조회 결과(getListDataNation)",
        passthrough_map_global,
        # 실측: Phase3 map_global_live_capture_260829.json(MNRL0024, 상위 5루트).
        '{"srchMnrkndUnqCd": "MNRL0024", "srchDateS": "20260101", "srchDateE": "20261231", '
        '"list": [{"RNUM": 1, "incmNtnNm": "독일", "incmNtnCd": "DE", "expNtnNm": "미국", "amt": 10855175.06, '
        '"weig": 29409.43, "sumWeig": 1704156.52, "weigRate": "1.73", "sumAmt": 76968241.63, '
        '"expNtnCd": "US", "amtRate": "14.10"}, '
        '{"RNUM": 2, "incmNtnNm": "영국", "incmNtnCd": "GB", "expNtnNm": "독일", "amt": 7839564.69, '
        '"weig": 138246, "sumWeig": 1704156.52, "weigRate": "8.11", "sumAmt": 76968241.63, '
        '"expNtnCd": "DE", "amtRate": "10.19"}, '
        '{"RNUM": 3, "incmNtnNm": "독일", "incmNtnCd": "DE", "expNtnNm": "중국", "amt": 4818696.95, '
        '"weig": 16205.2, "sumWeig": 1704156.52, "weigRate": "0.95", "sumAmt": 76968241.63, '
        '"expNtnCd": "CN", "amtRate": "6.26"}, '
        '{"RNUM": 4, "incmNtnNm": "독일", "incmNtnCd": "DE", "expNtnNm": "브라질", "amt": 3499065.45, '
        '"weig": 60000, "sumWeig": 1704156.52, "weigRate": "3.52", "sumAmt": 76968241.63, '
        '"expNtnCd": "BR", "amtRate": "4.55"}, '
        '{"RNUM": 5, "incmNtnNm": "미국", "incmNtnCd": "US", "expNtnNm": "브라질", "amt": 3183660, '
        '"weig": 72000, "sumWeig": 1704156.52, "weigRate": "4.22", "sumAmt": 76968241.63, '
        '"expNtnCd": "BR", "amtRate": "4.14"}], "listCount": "15"}',
    ),
    "map_mineral": KomisRawPage(
        "광물지도 조회 결과(getListMapMnrlChartData+getListMapMnrlData+getListMnrlTablePrdctnBurgudg)",
        passthrough_map_mineral,
        # chart 실측: Phase3 map_mineral_live_capture_260829.json(MNRL0008=동,
        # getListMapMnrlChartData, 2024·2025년 상위 5개국). snapshot·share는
        # 2026-08-31 이 세션이 komis.or.kr 직접 호출로 재검증(MNRL0008=동,
        # 2025년 단일연도 snapshot 상위 3개국, 2021~2025 share 상위 3개국) —
        # §komis_fetch.py fetch_map_mineral과 같은 {"chart","snapshot","share"}
        # envelope.
        # 2026-08-31 재수정(main-agent 통합검증 제보): chart를 5개국→2개국으로
        # 줄였다가 report_gen "3개국 이상 필요" 검증에 걸려 NO_DATA가 났다 —
        # 원래 5개국(칠레/호주/페루/DRC/러시아)으로 복원, snapshot도 3개국으로
        # 맞춤(둘 다 최소 표본 3개국 이상 유지).
        '{"chart": {"data": ['
        '{"cdVal": "k ton", "prdctnQuty": 5510000, "crtrYr": "2024", "totalBurudgQuty": 3738700000, '
        '"massUnitCd": "WT003", "burudgQuty": 190000000, "ntnEngNm": "Chile", "ntnKornNm": "칠레", "ntnEngCd": "CL"}, '
        '{"cdVal": "k ton", "prdctnQuty": 765000, "crtrYr": "2024", "totalBurudgQuty": 3738700000, '
        '"massUnitCd": "WT003", "burudgQuty": 100000000, "ntnEngNm": "Australia", "ntnKornNm": "호주", "ntnEngCd": "AU"}, '
        '{"cdVal": "k ton", "prdctnQuty": 2740000, "crtrYr": "2024", "totalBurudgQuty": 3738700000, '
        '"massUnitCd": "WT003", "burudgQuty": 100000000, "ntnEngNm": "Peru", "ntnKornNm": "페루", "ntnEngCd": "PE"}, '
        '{"cdVal": "k ton", "prdctnQuty": 2990000, "crtrYr": "2024", "totalBurudgQuty": 3738700000, '
        '"massUnitCd": "WT003", "burudgQuty": 80000000, "ntnEngNm": "Democratic Republic of Congo", '
        '"ntnKornNm": "콩고민주공화국", "ntnEngCd": "CD"}, '
        '{"cdVal": "k ton", "prdctnQuty": 1020000, "crtrYr": "2024", "totalBurudgQuty": 3738700000, '
        '"massUnitCd": "WT003", "burudgQuty": 80000000, "ntnEngNm": "Russia", "ntnKornNm": "러시아", "ntnEngCd": "RU"}, '
        '{"cdVal": "k ton", "prdctnQuty": 5300000, "crtrYr": "2025", "totalBurudgQuty": 3738700000, '
        '"massUnitCd": "WT003", "burudgQuty": 180000000, "ntnEngNm": "Chile", "ntnKornNm": "칠레", "ntnEngCd": "CL"}, '
        '{"cdVal": "k ton", "prdctnQuty": 730000, "crtrYr": "2025", "totalBurudgQuty": 3738700000, '
        '"massUnitCd": "WT003", "burudgQuty": 100000000, "ntnEngNm": "Australia", "ntnKornNm": "호주", "ntnEngCd": "AU"}, '
        '{"cdVal": "k ton", "prdctnQuty": 2700000, "crtrYr": "2025", "totalBurudgQuty": 3738700000, '
        '"massUnitCd": "WT003", "burudgQuty": 85000000, "ntnEngNm": "Peru", "ntnKornNm": "페루", "ntnEngCd": "PE"}, '
        '{"cdVal": "k ton", "prdctnQuty": 3200000, "crtrYr": "2025", "totalBurudgQuty": 3738700000, '
        '"massUnitCd": "WT003", "burudgQuty": 80000000, "ntnEngNm": "Democratic Republic of Congo", '
        '"ntnKornNm": "콩고민주공화국", "ntnEngCd": "CD"}, '
        '{"cdVal": "k ton", "prdctnQuty": 1300000, "crtrYr": "2025", "totalBurudgQuty": 3738700000, '
        '"massUnitCd": "WT003", "burudgQuty": 80000000, "ntnEngNm": "Russia", "ntnKornNm": "러시아", "ntnEngCd": "RU"}]}, '
        '"snapshot": {"data": ['
        '{"cdVal": "k ton", "prdctnQuty": 730000, "totalBurudgQuty": 770200000, "totalPrdctnQuty": 20013000, '
        '"massUnitCd": "WT003", "burudgQuty": 100000000, "ntnEngNm": "Australia", "ntnKornNm": "호주", "ntnEngCd": "AU"}, '
        '{"cdVal": "k ton", "prdctnQuty": 500000, "totalBurudgQuty": 770200000, "totalPrdctnQuty": 20013000, '
        '"massUnitCd": "WT003", "burudgQuty": 7000000, "ntnEngNm": "Canada", "ntnKornNm": "캐나다", "ntnEngCd": "CA"}, '
        '{"cdVal": "k ton", "prdctnQuty": 200000, "totalBurudgQuty": 770200000, "totalPrdctnQuty": 20013000, '
        '"massUnitCd": "WT003", "burudgQuty": 35000000, "ntnEngNm": "Chile", "ntnKornNm": "칠레", "ntnEngCd": "CL"}]}, '
        '"share": {"data": ['
        '{"ntnKornNm": "칠레", "ntnEngCd": "CL", "before5": "200,000,000", "before4": "190,000,000", '
        '"before3": "190,000,000", "before2": "190,000,000", "before1": "180,000,000", "rate": "18.37"}, '
        '{"ntnKornNm": "호주", "ntnEngCd": "AU", "before5": "93,000,000", "before4": "97,000,000", '
        '"before3": "100,000,000", "before2": "100,000,000", "before1": "100,000,000", "rate": "10.20"}, '
        '{"ntnKornNm": "_TOTAL_", "ntnEngCd": "SU", "before5": "980,000,000", "before4": "990,000,000", '
        '"before3": "1,000,000,000", "before2": "1,000,000,000", "before1": "980,000,000", "rate": "100.00"}]}}',
    ),
    "indicator_composite": KomisRawPage(
        "광물종합지수 조회 결과(getLineChartIndx)",
        passthrough_indicator_composite,
        # 실측: Phase4 composite_forecast_live_capture_260829.json의
        # data.tableData(날짜×지수유형 3종, 최근 10영업일분만 추림 — 원본은
        # 774행/약 1년치). dataIndx 스냅샷 1건만으로는 NO_DATA임을 실측으로
        # 확인해(§변환함수 참고) tableData 시계열 전체를 예시로 남긴다.
        '{"data": {"tableData": ['
        '{"prvdyFlutRt": "-1.03", "prvdyCprs": -31.03, "indx": 2969.95, "SORT": 2, "crtrYmd": "2026.08.14", "indxTp": "MAJOR"}, '
        '{"prvdyFlutRt": "-0.72", "prvdyCprs": -24.93, "indx": 3454.93, "SORT": 1, "crtrYmd": "2026.08.14", "indxTp": "MNRL"}, '
        '{"prvdyFlutRt": "0.00", "prvdyCprs": 0, "indx": 2905.63, "SORT": 3, "crtrYmd": "2026.08.14", "indxTp": "RARE"}, '
        '{"prvdyFlutRt": "0.40", "prvdyCprs": 11.82, "indx": 2981.77, "SORT": 2, "crtrYmd": "2026.08.17", "indxTp": "MAJOR"}, '
        '{"prvdyFlutRt": "0.43", "prvdyCprs": 14.69, "indx": 3469.62, "SORT": 1, "crtrYmd": "2026.08.17", "indxTp": "MNRL"}, '
        '{"prvdyFlutRt": "0.02", "prvdyCprs": 0.71, "indx": 2906.34, "SORT": 3, "crtrYmd": "2026.08.17", "indxTp": "RARE"}, '
        '{"prvdyFlutRt": "0.72", "prvdyCprs": 21.54, "indx": 3003.3, "SORT": 2, "crtrYmd": "2026.08.18", "indxTp": "MAJOR"}, '
        '{"prvdyFlutRt": "0.58", "prvdyCprs": 19.98, "indx": 3489.6, "SORT": 1, "crtrYmd": "2026.08.18", "indxTp": "MNRL"}, '
        '{"prvdyFlutRt": "0.00", "prvdyCprs": 0, "indx": 2906.34, "SORT": 3, "crtrYmd": "2026.08.18", "indxTp": "RARE"}, '
        '{"prvdyFlutRt": "-1.60", "prvdyCprs": -48.2, "indx": 2955.1, "SORT": 2, "crtrYmd": "2026.08.19", "indxTp": "MAJOR"}, '
        '{"prvdyFlutRt": "-0.89", "prvdyCprs": -31.21, "indx": 3458.39, "SORT": 1, "crtrYmd": "2026.08.19", "indxTp": "MNRL"}, '
        '{"prvdyFlutRt": "0.00", "prvdyCprs": 0, "indx": 2906.34, "SORT": 3, "crtrYmd": "2026.08.19", "indxTp": "RARE"}, '
        '{"prvdyFlutRt": "-0.44", "prvdyCprs": -13.02, "indx": 2942.08, "SORT": 2, "crtrYmd": "2026.08.20", "indxTp": "MAJOR"}, '
        '{"prvdyFlutRt": "1.10", "prvdyCprs": 38.17, "indx": 3496.56, "SORT": 1, "crtrYmd": "2026.08.20", "indxTp": "MNRL"}, '
        '{"prvdyFlutRt": "0.00", "prvdyCprs": 0, "indx": 2906.34, "SORT": 3, "crtrYmd": "2026.08.20", "indxTp": "RARE"}, '
        '{"prvdyFlutRt": "-0.13", "prvdyCprs": -3.74, "indx": 2938.34, "SORT": 2, "crtrYmd": "2026.08.21", "indxTp": "MAJOR"}, '
        '{"prvdyFlutRt": "0.20", "prvdyCprs": 7.04, "indx": 3503.6, "SORT": 1, "crtrYmd": "2026.08.21", "indxTp": "MNRL"}, '
        '{"prvdyFlutRt": "0.00", "prvdyCprs": 0, "indx": 2906.34, "SORT": 3, "crtrYmd": "2026.08.21", "indxTp": "RARE"}, '
        '{"prvdyFlutRt": "1.01", "prvdyCprs": 29.72, "indx": 2968.06, "SORT": 2, "crtrYmd": "2026.08.24", "indxTp": "MAJOR"}, '
        '{"prvdyFlutRt": "1.02", "prvdyCprs": 35.86, "indx": 3539.45, "SORT": 1, "crtrYmd": "2026.08.24", "indxTp": "MNRL"}, '
        '{"prvdyFlutRt": "0.19", "prvdyCprs": 5.46, "indx": 2911.8, "SORT": 3, "crtrYmd": "2026.08.24", "indxTp": "RARE"}, '
        '{"prvdyFlutRt": "0.33", "prvdyCprs": 9.76, "indx": 2977.82, "SORT": 2, "crtrYmd": "2026.08.25", "indxTp": "MAJOR"}, '
        '{"prvdyFlutRt": "0.50", "prvdyCprs": 17.67, "indx": 3557.13, "SORT": 1, "crtrYmd": "2026.08.25", "indxTp": "MNRL"}, '
        '{"prvdyFlutRt": "0.00", "prvdyCprs": 0, "indx": 2911.8, "SORT": 3, "crtrYmd": "2026.08.25", "indxTp": "RARE"}, '
        '{"prvdyFlutRt": "-0.11", "prvdyCprs": -3.31, "indx": 2974.51, "SORT": 2, "crtrYmd": "2026.08.26", "indxTp": "MAJOR"}, '
        '{"prvdyFlutRt": "-0.30", "prvdyCprs": -10.76, "indx": 3546.37, "SORT": 1, "crtrYmd": "2026.08.26", "indxTp": "MNRL"}, '
        '{"prvdyFlutRt": "0.00", "prvdyCprs": 0, "indx": 2911.8, "SORT": 3, "crtrYmd": "2026.08.26", "indxTp": "RARE"}, '
        '{"prvdyFlutRt": "0.84", "prvdyCprs": 25.03, "indx": 2999.54, "SORT": 2, "crtrYmd": "2026.08.27", "indxTp": "MAJOR"}, '
        '{"prvdyFlutRt": "0.35", "prvdyCprs": 12.44, "indx": 3558.81, "SORT": 1, "crtrYmd": "2026.08.27", "indxTp": "MNRL"}, '
        '{"prvdyFlutRt": "0.00", "prvdyCprs": 0, "indx": 2911.8, "SORT": 3, "crtrYmd": "2026.08.27", "indxTp": "RARE"}]}}',
    ),
    "forecast_price": KomisRawPage(
        "가격예측 조회 결과(getListPricePredc)",
        passthrough_forecast_price,
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
