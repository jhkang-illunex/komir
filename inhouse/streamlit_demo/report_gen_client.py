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
    has_mineral: bool  # False면 mineral 필드 자체가 없는 페이지(indicator_composite)
    period_fields: tuple[str, str]  # (시작 필드명, 종료 필드명) — 없으면 ("", "")
    period_kind: str  # "month" | "date" | "year" | "period" | ""
    extra_fields: tuple[str, ...]  # 페이지 고유 부속 필드(문자열 입력으로 노출)
    observations_example: str  # observations 예시 JSON(placeholder)



# 2026-08-30 main-agent 방향전환: "선택 입력값은 사용자가 채운다"에서 "기본값
# 자체를 처음부터 풍부하게"로 바뀌었다 — 아무것도 안 건드리고 버튼만 눌러도
# 화면 가득한 KOMIS 정보량에 걸맞은 리포트가 나와야 한다는 사용자 지적 반영.
# 아래 관측치 대부분은 `documents/산출물/2026-W35_0824-0830/
# report_gen_KOMIS라이브재검증_Phase{1,2,3,4}_260829_evidence/`의 실측 라이브
# 캡처를 그대로 옮긴 것이다(값을 지어내지 않는다는 원칙) — 페이지별 출처는
# 각 PageSpec 주석에 명시.
PAGE_SPECS: dict[str, PageSpec] = {
    # 2026-09-01(사용자 지시): 광물전망지표 서브메뉴 순서를 komis_menu_map.yaml
    # 실측 사이트맵 순서(광물종합지수→시장동향지표→수급동향지표)에 맞춰 이
    # dict의 등록 순서 자체를 재배열했다 — section_page_ids(report_demo.py)가
    # PAGE_SPECS dict 순회 순서를 그대로 쓰기 때문(§SECTION_ORDER 방식과 달리
    # 서브메뉴 전용 정렬 리스트는 따로 없음, 등록 순서로 충분해 새로 안 만듦).
    "indicator_composite": PageSpec(
        # 실측: Phase4 `composite_forecast_live_capture_260829.json`
        # (getLineChartIndx, 2026-08-14~27 10영업일) 그대로.
        # 2026-08-30 report-summary-agent 제보(커밋 0d0568a50) — start_date/
        # end_date가 요청 모델에서 삭제됐다(komis_response가 이미 KOMIS 조회
        # 범위 그대로의 시계열이라 서버 재필터가 중복) — period_fields 제거.
        "광물종합지수", "광물전망지표", "composite-index", False, ("", ""), "",
        (),
        '[{"date": "2026-08-14", "composite_index": 3454.93, "major_metals_index": 2969.95, "minor_metals_index": 2905.63}, '
        '{"date": "2026-08-17", "composite_index": 3469.62, "major_metals_index": 2981.77, "minor_metals_index": 2906.34}, '
        '{"date": "2026-08-18", "composite_index": 3489.6, "major_metals_index": 3003.3, "minor_metals_index": 2906.34}, '
        '{"date": "2026-08-19", "composite_index": 3458.39, "major_metals_index": 2955.1, "minor_metals_index": 2906.34}, '
        '{"date": "2026-08-20", "composite_index": 3496.56, "major_metals_index": 2942.08, "minor_metals_index": 2906.34}, '
        '{"date": "2026-08-21", "composite_index": 3503.6, "major_metals_index": 2938.34, "minor_metals_index": 2906.34}, '
        '{"date": "2026-08-24", "composite_index": 3539.45, "major_metals_index": 2968.06, "minor_metals_index": 2911.8}, '
        '{"date": "2026-08-25", "composite_index": 3557.13, "major_metals_index": 2977.82, "minor_metals_index": 2911.8}, '
        '{"date": "2026-08-26", "composite_index": 3546.37, "major_metals_index": 2974.51, "minor_metals_index": 2911.8}, '
        '{"date": "2026-08-27", "composite_index": 3558.81, "major_metals_index": 2999.54, "minor_metals_index": 2911.8}]',
    ),
    "indicator_market": PageSpec(
        # 2026-09-01: 발주처가 이 페이지(로그인 필요라 그동안 라이브 캡처가
        # 없었음)의 KOMIS 원본 JSON 덤프를 처음 제공, report_gen이
        # komis_response 파싱을 추가하면서(worktree-report_gen 커밋 53425f1e4)
        # KOMIS_RAW_PAGES로 옮겨져 아래 observations_example은 더 이상 화면에
        # 안 쓰인다(§komis_raw.py의 indicator_market 실측 예시가 정본) —
        # 스키마 호환용으로만 남긴다. 값은 실측 getListIndxMnrk.json(2024-09~
        # 2026-07, mrktPrspectIdct→score, realPrc→price)을 그대로 옮겼다(기존
        # 가짜 placeholder였던 걸 사용자 지적으로 실측 교체) — crisis_flag는
        # 이 응답에 대응 필드(crisisYn)가 없어 넣지 않는다(§summary.py
        # _parse_komis_market_response 참고).
        # 2026-09-01 재수정(사용자 지적): price_unit/price_criterion은 실제
        # KOMIS 시장동향지표 화면에 없는 필드고 komis_response로도 채울 방법이
        # 없어(가격 페이지의 dataAvg.INFO.prcCrtr 같은 자동채움 소스가 없음)
        # 항상 빈 값 → report_gen이 매번 "가격 기준/단위 누락"으로만 표시하는
        # 무용한 필드였다 — extra_fields에서 제거.
        "시장동향지표", "광물전망지표", "market-indicator", True, ("start_month", "end_month"), "month",
        (),
        '[{"month": "2024-09", "score": 5.27, "price": 447.46}, '
        '{"month": "2024-10", "score": 5.55, "price": 455.23}, '
        '{"month": "2024-11", "score": 7.99, "price": 438.84}, '
        '{"month": "2024-12", "score": 11.41, "price": 420.54}, '
        '{"month": "2025-01", "score": 20.24, "price": 387.64}, '
        '{"month": "2025-02", "score": 21.51, "price": 385.0}, '
        '{"month": "2025-03", "score": 21.01, "price": 387.31}, '
        '{"month": "2025-04", "score": 21.24, "price": 389.15}, '
        '{"month": "2025-05", "score": 20.79, "price": 394.63}, '
        '{"month": "2025-06", "score": 20.63, "price": 398.48}, '
        '{"month": "2025-07", "score": 22.16, "price": 395.84}, '
        '{"month": "2025-08", "score": 23.33, "price": 394.77}, '
        '{"month": "2025-09", "score": 23.6, "price": 398.26}, '
        '{"month": "2025-10", "score": 24.3, "price": 400.16}, '
        '{"month": "2025-11", "score": 25.56, "price": 399.42}, '
        '{"month": "2025-12", "score": 28.19, "price": 393.05}, '
        '{"month": "2026-01", "score": 30.07, "price": 390.01}, '
        '{"month": "2026-02", "score": 29.2, "price": 399.84}, '
        '{"month": "2026-03", "score": 30.12, "price": 399.91}, '
        '{"month": "2026-04", "score": 31.5, "price": 398.47}, '
        '{"month": "2026-05", "score": 32.74, "price": 398.9}, '
        '{"month": "2026-06", "score": 34.04, "price": 400.4}, '
        '{"month": "2026-07", "score": 30.38, "price": 418.09}]',
    ),
    "indicator_supply": PageSpec(
        # 2026-09-01: §위 indicator_market과 동일 이유로 KOMIS_RAW_PAGES로
        # 옮겨졌다(worktree-report_gen 커밋 cd51bc205) — observations_example은
        # 스키마 호환용으로만 남긴다. 값은 실측 getListIndxSplyBalncMnrk.json
        # (2024-09~2026-07, spdmStbtIndx→score, realPrc→price, crisisYn→
        # crisis_flag, 조회기간 전체 "N"=false)을 그대로 옮겼다(기존 가짜
        # placeholder 교체). price_unit/price_criterion 제거 사유는
        # §indicator_market 주석과 동일.
        "수급동향지표", "광물전망지표", "supply-indicator", True, ("start_month", "end_month"), "month",
        (),
        '[{"month": "2024-09", "score": 5.07, "price": 447.46, "crisis_flag": false}, '
        '{"month": "2024-10", "score": 5.34, "price": 455.23, "crisis_flag": false}, '
        '{"month": "2024-11", "score": 7.69, "price": 438.84, "crisis_flag": false}, '
        '{"month": "2024-12", "score": 10.97, "price": 420.54, "crisis_flag": false}, '
        '{"month": "2025-01", "score": 19.46, "price": 387.64, "crisis_flag": false}, '
        '{"month": "2025-02", "score": 20.68, "price": 385.0, "crisis_flag": false}, '
        '{"month": "2025-03", "score": 20.2, "price": 387.31, "crisis_flag": false}, '
        '{"month": "2025-04", "score": 20.43, "price": 389.15, "crisis_flag": false}, '
        '{"month": "2025-05", "score": 19.99, "price": 394.63, "crisis_flag": false}, '
        '{"month": "2025-06", "score": 19.84, "price": 398.48, "crisis_flag": false}, '
        '{"month": "2025-07", "score": 21.3, "price": 395.84, "crisis_flag": false}, '
        '{"month": "2025-08", "score": 22.44, "price": 394.77, "crisis_flag": false}, '
        '{"month": "2025-09", "score": 22.7, "price": 398.26, "crisis_flag": false}, '
        '{"month": "2025-10", "score": 23.36, "price": 400.16, "crisis_flag": false}, '
        '{"month": "2025-11", "score": 24.57, "price": 399.42, "crisis_flag": false}, '
        '{"month": "2025-12", "score": 27.11, "price": 393.05, "crisis_flag": false}, '
        '{"month": "2026-01", "score": 29.19, "price": 390.01, "crisis_flag": false}, '
        '{"month": "2026-02", "score": 28.08, "price": 399.84, "crisis_flag": false}, '
        '{"month": "2026-03", "score": 28.96, "price": 399.91, "crisis_flag": false}, '
        '{"month": "2026-04", "score": 30.58, "price": 398.47, "crisis_flag": false}, '
        '{"month": "2026-05", "score": 31.79, "price": 398.9, "crisis_flag": false}, '
        '{"month": "2026-06", "score": 33.05, "price": 400.4, "crisis_flag": false}, '
        '{"month": "2026-07", "score": 29.5, "price": 418.09, "crisis_flag": false}]',
    ),
    # 2026-09-01 삭제(사용자 지시): "광물전망지표>가격예측(중기/장기)" 메뉴를
    # 화면에서 지웠다 — page_id "forecast_price"(path price-forecast)를
    # PAGE_SPECS에서 제거(§price_group 2026-08-31 삭제와 같은 패턴, 이유는
    # 별도로 듣지 못해 기록만). report_gen 서버 쪽 엔드포인트·komis_raw.py의
    # KOMIS_RAW_PAGES["forecast_price"]/passthrough_forecast_price는 손대지
    # 않았다(이 화면의 메뉴 노출만 제거 대상이라 판단, 백엔드 범위 밖).
    "price_base_metals": PageSpec(
        # 실측: Phase1 `harness_sample_entries_260828.json`(동|LME 3개월, 최근
        # 14영업일 + inventory) — 이 샘플은 report-summary-agent가 실제 스크린샷
        # (-0.70%/+0.98%/+5.11%/+42.84%)과 일치까지 확인한 값이다.
        # 2026-08-30 사용자 지시: 데모 화면은 komis.or.kr 해당 페이지가 실제로
        # 제공하는 선택 UI만 노출한다 — price_unit·price_criterion_serial은
        # 실제 KOMIS 조회 파라미터(mnrkndUnqRadioCd/srchPrcCrtr/srchAvgOpt 등,
        # Phase1 evidence params 확인)에 없는 report_gen 전용 옵션 필드라 제거.
        # 2026-08-30 재수정(report-summary-agent 스키마 트리밍, 커밋 c76466a47):
        # price_criterion 자체가 요청 모델에서 삭제됐다(extra="forbid"라 보내면
        # 조용히 NO_DATA) — extra_fields에서도 제거.
        # 2026-08-30 3차 수정(report-summary-agent 제보, 커밋 0d0568a50):
        # start_date/end_date도 삭제됐다(§indicator_composite 주석 참고).
        # 2026-08-30 4차(report-summary-agent 알림, 급하지 않음·회귀 아님):
        # price_criterion·compare_price_criterion이 optional로 복원됐고
        # komis_response가 있으면 mineral_name과 마찬가지로 자동채움된다
        # (report_gen_price_criterion_복원_4차재감사_260830.md 등 참고) — 이
        # 화면은 komis_response 통짜 붙여넣기 방식이라 자동채움만으로 충분,
        # 덮어쓰기용 별도 입력란은 사용자의 "3요소만" 지시(§파일 상단)와
        # 상충해 추가하지 않았다.
        "비철금속", "광물자원가격", "prices/base-metals", True, ("", ""), "",
        ("compare_mineral",),
        '[{"date": "2026-08-10", "commerce_price": 14152.0, "lowest_price": null, "highest_price": null, "inventory": 218300.0}, '
        '{"date": "2026-08-11", "commerce_price": 14217.0, "lowest_price": null, "highest_price": null, "inventory": 214550.0}, '
        '{"date": "2026-08-12", "commerce_price": 14201.0, "lowest_price": null, "highest_price": null, "inventory": 212125.0}, '
        '{"date": "2026-08-13", "commerce_price": 14082.0, "lowest_price": null, "highest_price": null, "inventory": 207725.0}, '
        '{"date": "2026-08-14", "commerce_price": 14134.0, "lowest_price": null, "highest_price": null, "inventory": 204975.0}, '
        '{"date": "2026-08-17", "commerce_price": 14315.0, "lowest_price": null, "highest_price": null, "inventory": 207825.0}, '
        '{"date": "2026-08-18", "commerce_price": 14080.0, "lowest_price": null, "highest_price": null, "inventory": 223550.0}, '
        '{"date": "2026-08-19", "commerce_price": 13890.0, "lowest_price": null, "highest_price": null, "inventory": 235975.0}, '
        '{"date": "2026-08-20", "commerce_price": 13970.5, "lowest_price": null, "highest_price": null, "inventory": 239925.0}, '
        '{"date": "2026-08-21", "commerce_price": 14235.0, "lowest_price": null, "highest_price": null, "inventory": 238575.0}, '
        '{"date": "2026-08-24", "commerce_price": 14245.0, "lowest_price": null, "highest_price": null, "inventory": 240250.0}, '
        '{"date": "2026-08-25", "commerce_price": 14298.0, "lowest_price": null, "highest_price": null, "inventory": 238725.0}, '
        '{"date": "2026-08-26", "commerce_price": 14336.0, "lowest_price": null, "highest_price": null, "inventory": 237475.0}, '
        '{"date": "2026-08-27", "commerce_price": 14236.0, "lowest_price": null, "highest_price": null, "inventory": 235575.0}]',
    ),
    "price_minor_metals": PageSpec(
        # compare_mineral/compare_price_criterion: KOMIS "비교광종" 기능 대응,
        # 이 page_id 전용(다른 page_id로 보내면 서버가 거부). compare_observations
        # (비교 계열 원자료 JSON)는 이 데모의 observations 텍스트영역과 별개라
        # 1차 범위에서 뺐다 — 필요해지면 별도 textarea로 추가.
        # 실측: Phase2 `collected_minor_spotcheck_raw_260829.json`(코발트 LME
        # CASH, 최근 14영업일). Phase2 META 확인상 minor_metals는 inventory가
        # 항상 "0.00"이라(실측 없음) base_metals와 달리 예시에 넣지 않았다.
        # 2026-08-30: price_unit·price_criterion_serial 제거(§price_base_metals
        # 주석 참고) — compare_mineral/compare_price_criterion(비교광종)은 실제
        # KOMIS 파라미터(srchCompareMnrkndUnqCd/srchComparePrcCrtr)라 유지.
        # 2026-08-30 재수정(report-summary-agent 스키마 트리밍, 커밋 c76466a47):
        # price_criterion·compare_price_criterion 둘 다 요청 모델에서 삭제됐다
        # (extra="forbid") — compare_mineral만 남긴다(스키마에 그대로 있음).
        # 2026-08-30 3차 수정(report-summary-agent 제보, 커밋 0d0568a50):
        # start_date/end_date도 삭제됐다(§indicator_composite 주석 참고).
        # 2026-08-30 4차(§price_base_metals 주석 참고, 급하지 않음·회귀 아님):
        # price_criterion·compare_price_criterion이 optional로 복원돼
        # komis_response로 자동채움된다 — 덮어쓰기 입력란은 추가하지 않음.
        "희소금속", "광물자원가격", "prices/minor-metals", True, ("", ""), "",
        ("compare_mineral",),
        '[{"date": "2026-08-10", "commerce_price": 55850.0}, {"date": "2026-08-11", "commerce_price": 55845.0}, '
        '{"date": "2026-08-12", "commerce_price": 55850.0}, {"date": "2026-08-13", "commerce_price": 55855.0}, '
        '{"date": "2026-08-14", "commerce_price": 55860.0}, {"date": "2026-08-17", "commerce_price": 55845.0}, '
        '{"date": "2026-08-18", "commerce_price": 55845.0}, {"date": "2026-08-19", "commerce_price": 55845.0}, '
        '{"date": "2026-08-20", "commerce_price": 55855.0}, {"date": "2026-08-21", "commerce_price": 55860.0}, '
        '{"date": "2026-08-24", "commerce_price": 55845.0}, {"date": "2026-08-25", "commerce_price": 55845.0}, '
        '{"date": "2026-08-26", "commerce_price": 55840.0}, {"date": "2026-08-27", "commerce_price": 55860.0}]',
    ),
    "price_iron_energy": PageSpec(
        # 실측: Phase2 `collected_iron_other_day_raw_260829.json`(철,
        # Australian 62%min CNF China, 최근 14영업일) — inventory 없음(§위 참고).
        # 2026-08-30 재수정(report-summary-agent 스키마 트리밍, 커밋 c76466a47):
        # price_criterion이 요청 모델에서 삭제됐다(extra="forbid") — 제거.
        # 2026-08-30 3차 수정(report-summary-agent 제보, 커밋 0d0568a50):
        # start_date/end_date도 삭제됐다(§indicator_composite 주석 참고).
        # 2026-08-30 4차(§price_base_metals 주석 참고, 급하지 않음·회귀 아님):
        # price_criterion이 optional로 복원돼 komis_response로 자동채움된다.
        "철광석 및 에너지", "광물자원가격", "prices/iron-energy", True, ("", ""), "",
        ("compare_mineral",),
        '[{"date": "2026-08-10", "commerce_price": 97.5, "lowest_price": 97.0, "highest_price": 98.0}, '
        '{"date": "2026-08-11", "commerce_price": 97.5, "lowest_price": 97.0, "highest_price": 98.0}, '
        '{"date": "2026-08-12", "commerce_price": 98.5, "lowest_price": 98.0, "highest_price": 99.0}, '
        '{"date": "2026-08-13", "commerce_price": 98.5, "lowest_price": 98.0, "highest_price": 99.0}, '
        '{"date": "2026-08-14", "commerce_price": 98.5, "lowest_price": 98.0, "highest_price": 99.0}, '
        '{"date": "2026-08-17", "commerce_price": 98.5, "lowest_price": 98.0, "highest_price": 99.0}, '
        '{"date": "2026-08-18", "commerce_price": 98.5, "lowest_price": 98.0, "highest_price": 99.0}, '
        '{"date": "2026-08-19", "commerce_price": 99.5, "lowest_price": 99.0, "highest_price": 100.0}, '
        '{"date": "2026-08-20", "commerce_price": 99.5, "lowest_price": 99.0, "highest_price": 100.0}, '
        '{"date": "2026-08-21", "commerce_price": 99.5, "lowest_price": 99.0, "highest_price": 100.0}, '
        '{"date": "2026-08-24", "commerce_price": 99.5, "lowest_price": 99.0, "highest_price": 100.0}, '
        '{"date": "2026-08-25", "commerce_price": 100.5, "lowest_price": 100.0, "highest_price": 101.0}, '
        '{"date": "2026-08-26", "commerce_price": 100.5, "lowest_price": 100.0, "highest_price": 101.0}, '
        '{"date": "2026-08-27", "commerce_price": 100.5, "lowest_price": 100.0, "highest_price": 101.0}]',
    ),
    "price_other": PageSpec(
        # 실측: Phase2 `collected_iron_other_day_raw_260829.json`(금, London
        # Gold Market LBMA PM Fixing, 최근 14영업일) — inventory 없음(§위 참고).
        # 2026-08-30 재수정(report-summary-agent 스키마 트리밍, 커밋 c76466a47):
        # price_criterion이 요청 모델에서 삭제됐다(extra="forbid") — 제거.
        # 2026-08-30 3차 수정(report-summary-agent 제보, 커밋 0d0568a50):
        # start_date/end_date도 삭제됐다(§indicator_composite 주석 참고).
        # 2026-08-30 4차(§price_base_metals 주석 참고, 급하지 않음·회귀 아님):
        # price_criterion이 optional로 복원돼 komis_response로 자동채움된다.
        "기타", "광물자원가격", "prices/other", True, ("", ""), "",
        ("compare_mineral",),
        '[{"date": "2026-08-10", "commerce_price": 4324.45}, {"date": "2026-08-11", "commerce_price": 4383.35}, '
        '{"date": "2026-08-12", "commerce_price": 4426.65}, {"date": "2026-08-13", "commerce_price": 4373.0}, '
        '{"date": "2026-08-14", "commerce_price": 4390.7}, {"date": "2026-08-17", "commerce_price": 4405.8}, '
        '{"date": "2026-08-18", "commerce_price": 4403.5}, {"date": "2026-08-19", "commerce_price": 4460.7}, '
        '{"date": "2026-08-20", "commerce_price": 4482.95}, {"date": "2026-08-21", "commerce_price": 4582.1}, '
        '{"date": "2026-08-24", "commerce_price": 4663.7}, {"date": "2026-08-25", "commerce_price": 4615.45}, '
        '{"date": "2026-08-26", "commerce_price": 4631.5}, {"date": "2026-08-27", "commerce_price": 4568.95}]',
    ),
    "map_korea": PageSpec(
        # 실측: Phase3 `map_korea_live_capture_260829.json`(getListKoreaData,
        # MNRL0008=동·수입, 상위 14개국 — 원본은 30개국까지 있음). 총액(고급
        # expander 기본값)도 같은 캡처의 sumIncmAmt/sumIncmWeig 그대로.
        # 2026-08-30 report-summary-agent 제보(커밋 0d0568a50) — start_date/
        # end_date가 요청 모델에서 삭제됐다(§indicator_composite 주석 참고).
        "국내 수급지도(수출입)", "핵심광물지도", "domestic-trade", True, ("", ""), "",
        ("trade_direction",),
        '[{"date": "2025-08-01", "country_code": "CL", "country_name": "칠레", "import_weight": 458239149, "import_amount": 2546230722}, '
        '{"date": "2025-08-01", "country_code": "US", "country_name": "미국", "import_weight": 138542249, "import_amount": 1200849392}, '
        '{"date": "2025-08-01", "country_code": "AU", "country_name": "호주", "import_weight": 103333842, "import_amount": 1102245059}, '
        '{"date": "2025-08-01", "country_code": "CD", "country_name": "콩고민주공화국", "import_weight": 76287183, "import_amount": 983212537}, '
        '{"date": "2025-08-01", "country_code": "CN", "country_name": "중국", "import_weight": 53455286, "import_amount": 687233413}, '
        '{"date": "2025-08-01", "country_code": "CA", "country_name": "캐나다", "import_weight": 126045149, "import_amount": 685247124}, '
        '{"date": "2025-08-01", "country_code": "JP", "country_name": "일본", "import_weight": 21003769, "import_amount": 505419938}, '
        '{"date": "2025-08-01", "country_code": "MX", "country_name": "멕시코", "import_weight": 80823522, "import_amount": 458978653}, '
        '{"date": "2025-08-01", "country_code": "PE", "country_name": "페루", "import_weight": 85295111, "import_amount": 362518246}, '
        '{"date": "2025-08-01", "country_code": "TW", "country_name": "대만", "import_weight": 17014583, "import_amount": 266357398}, '
        '{"date": "2025-08-01", "country_code": "PG", "country_name": "파푸아뉴기니", "import_weight": 35749898, "import_amount": 217628442}, '
        '{"date": "2025-08-01", "country_code": "IN", "country_name": "인도", "import_weight": 21405318, "import_amount": 206058658}, '
        '{"date": "2025-08-01", "country_code": "PH", "country_name": "필리핀", "import_weight": 16862824, "import_amount": 173097284}, '
        '{"date": "2025-08-01", "country_code": "ES", "country_name": "스페인", "import_weight": 12708884, "import_amount": 128174269}]',
    ),
    "map_global": PageSpec(
        # 실측: Phase3 `map_global_live_capture_260829.json`(getListDataNation,
        # MNRL0008=동, 상위 14루트 — 원본 30개 루트 중 상위, 실제 전체 총액과
        # 합산 격차(72% 이상)까지 있는 값을 그대로 옮겼다). 고급 expander
        # 기본값(komis_trade_totals)도 같은 캡처의 sumAmt/sumWeig 그대로 —
        # 관측치 14건 합산(≈72억)보다 진짜 총액(≈264억)이 훨씬 커서 이 필드가
        # "30행 절단으로 인한 과소총액" 문제를 실측으로 보여준다.
        # 2026-08-30 report-summary-agent 제보(커밋 0d0568a50) — start_date/
        # end_date가 요청 모델에서 삭제됐다(§indicator_composite 주석 참고).
        "글로벌 수급지도(원산지→도착지)", "핵심광물지도", "global-trade", True, ("", ""), "",
        (),
        '[{"date": "2025-08-01", "country_code": "JP", "country_name": "일본", "import_weight": 339553072, "import_amount": 912677544.84, "origin_country_code": "CL", "origin_country_name": "칠레"}, '
        '{"date": "2025-08-01", "country_code": "US", "country_name": "미국", "import_weight": 70155941, "import_amount": 855452708, "origin_country_code": "CL", "origin_country_name": "칠레"}, '
        '{"date": "2025-08-01", "country_code": "IN", "country_name": "인도", "import_weight": 224395654, "import_amount": 690138479.7, "origin_country_code": "CL", "origin_country_name": "칠레"}, '
        '{"date": "2025-08-01", "country_code": "JP", "country_name": "일본", "import_weight": 242969854, "import_amount": 655218643.21, "origin_country_code": "PE", "origin_country_name": "페루"}, '
        '{"date": "2025-08-01", "country_code": "JP", "country_name": "일본", "import_weight": 156458746, "import_amount": 618509454.06, "origin_country_code": "US", "origin_country_name": "미국"}, '
        '{"date": "2025-08-01", "country_code": "TH", "country_name": "태국", "import_weight": 41713616.7, "import_amount": 575517998.2, "origin_country_code": "CN", "origin_country_name": "중국"}, '
        '{"date": "2025-08-01", "country_code": "CA", "country_name": "캐나다", "import_weight": 49058003.33, "import_amount": 485786916.43, "origin_country_code": "US", "origin_country_name": "미국"}, '
        '{"date": "2025-08-01", "country_code": "IN", "country_name": "인도", "import_weight": 35860366, "import_amount": 440004987.1, "origin_country_code": "ZM", "origin_country_name": "잠비아"}, '
        '{"date": "2025-08-01", "country_code": "ES", "country_name": "스페인", "import_weight": 128000282, "import_amount": 346453677.14, "origin_country_code": "PE", "origin_country_name": "페루"}, '
        '{"date": "2025-08-01", "country_code": "CA", "country_name": "캐나다", "import_weight": 19004561.01, "import_amount": 345737877.36, "origin_country_code": "SE", "origin_country_name": "스웨덴"}, '
        '{"date": "2025-08-01", "country_code": "DE", "country_name": "독일", "import_weight": 88687940.47, "import_amount": 343653275.86, "origin_country_code": "CL", "origin_country_name": "칠레"}, '
        '{"date": "2025-08-01", "country_code": "US", "country_name": "미국", "import_weight": 25095634, "import_amount": 325830531, "origin_country_code": "AU", "origin_country_name": "호주"}, '
        '{"date": "2025-08-01", "country_code": "BR", "country_name": "브라질", "import_weight": 25902594, "import_amount": 303322485, "origin_country_code": "CL", "origin_country_name": "칠레"}, '
        '{"date": "2025-08-01", "country_code": "US", "country_name": "미국", "import_weight": 27102934, "import_amount": 303312213, "origin_country_code": "CD", "origin_country_name": "콩고민주공화국"}]',
    ),
    # 2026-09-01(사용자 지시): 핵심광물지도 서브메뉴 순서를 [수급지도>대한민국,
    # 수급지도>글로벌, 광물지도]로 맞추기 위해 map_mineral을 map_korea/
    # map_global 뒤로 옮겼다(§indicator_composite 재배치와 같은 이유·같은 패턴,
    # PAGE_SPECS dict 등록 순서 = section_page_ids 순서).
    "map_mineral": PageSpec(
        # 실측: Phase3 `map_mineral_live_capture_260829.json`(getListMapMnrlData,
        # MNRL0008=동, 2025년 매장량 burudgQuty 14개국, 천톤 환산=÷1000). 2024년은
        # 라이브 재캡처를 못 받아(2차 연도 미보유) 서버 최소요건(연도≥2) 충족용으로
        # 2025년 값을 그대로 복제했다 — 국가별 실측값 자체는 100% 라이브, 연도 간
        # 변화율만 0%로 나온다(지어낸 델타 없음, 정직한 한계).
        # 2026-08-30 report-summary-agent 제보(커밋 0d0568a50) — start_year/
        # end_year가 요청 모델에서 삭제됐다(§indicator_composite 주석 참고).
        "광물지도(매장량/생산량)", "핵심광물지도", "mineral-map", True, ("", ""), "",
        ("measure", "unit"),
        '[{"year": 2024, "country_code": "AU", "country_name": "호주", "value": 100000.0}, '
        '{"year": 2024, "country_code": "CA", "country_name": "캐나다", "value": 7000.0}, '
        '{"year": 2024, "country_code": "CD", "country_name": "콩고민주공화국", "value": 80000.0}, '
        '{"year": 2024, "country_code": "CL", "country_name": "칠레", "value": 180000.0}, '
        '{"year": 2024, "country_code": "CN", "country_name": "중국", "value": 41000.0}, '
        '{"year": 2024, "country_code": "ID", "country_name": "인도네시아", "value": 21000.0}, '
        '{"year": 2024, "country_code": "IN", "country_name": "인도", "value": 2200.0}, '
        '{"year": 2024, "country_code": "KZ", "country_name": "카자흐스탄", "value": 20000.0}, '
        '{"year": 2024, "country_code": "MX", "country_name": "멕시코", "value": 53000.0}, '
        '{"year": 2024, "country_code": "PE", "country_name": "페루", "value": 85000.0}, '
        '{"year": 2024, "country_code": "PL", "country_name": "폴란드", "value": 33000.0}, '
        '{"year": 2024, "country_code": "RU", "country_name": "러시아", "value": 80000.0}, '
        '{"year": 2024, "country_code": "US", "country_name": "미국", "value": 47000.0}, '
        '{"year": 2024, "country_code": "ZM", "country_name": "잠비아", "value": 21000.0}, '
        '{"year": 2025, "country_code": "AU", "country_name": "호주", "value": 100000.0}, '
        '{"year": 2025, "country_code": "CA", "country_name": "캐나다", "value": 7000.0}, '
        '{"year": 2025, "country_code": "CD", "country_name": "콩고민주공화국", "value": 80000.0}, '
        '{"year": 2025, "country_code": "CL", "country_name": "칠레", "value": 180000.0}, '
        '{"year": 2025, "country_code": "CN", "country_name": "중국", "value": 41000.0}, '
        '{"year": 2025, "country_code": "ID", "country_name": "인도네시아", "value": 21000.0}, '
        '{"year": 2025, "country_code": "IN", "country_name": "인도", "value": 2200.0}, '
        '{"year": 2025, "country_code": "KZ", "country_name": "카자흐스탄", "value": 20000.0}, '
        '{"year": 2025, "country_code": "MX", "country_name": "멕시코", "value": 53000.0}, '
        '{"year": 2025, "country_code": "PE", "country_name": "페루", "value": 85000.0}, '
        '{"year": 2025, "country_code": "PL", "country_name": "폴란드", "value": 33000.0}, '
        '{"year": 2025, "country_code": "RU", "country_name": "러시아", "value": 80000.0}, '
        '{"year": 2025, "country_code": "US", "country_name": "미국", "value": 47000.0}, '
        '{"year": 2025, "country_code": "ZM", "country_name": "잠비아", "value": 21000.0}]',
    ),
    # 2026-08-31 삭제(report-summary-agent 알림, 커밋 de2bd6336): 사용자가
    # 메뉴별 템플릿 현황 문서를 보고 "전체 광종은 필요 없어 보임"이라 피드백,
    # 확인 결과 "코드는 남기고 외부 인터페이스만 제거"로 확정 — report_gen도
    # POST /api/v1/analysis/price-group를 404로 막았다(완전 삭제 아니라 필요
    # 시 API만 복원 가능한 상태). 이 데모도 같은 결정을 따라 page_id
    # "price_group"(구 "그룹 요약(비철금속/희소금속)")을 PAGE_SPECS에서
    # 제거했다 — 과거엔 있었다는 사실만 기록.
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
    "compare_mineral": "비교광종(compare_mineral)",
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
