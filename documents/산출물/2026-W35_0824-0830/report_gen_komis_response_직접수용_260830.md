# report_gen price_* — KOMIS 원본 응답 직접 수용 (2026-08-30)

## 배경
KOMIS 납품 최적화 지시. "JSON으로 받아서 내부에서 정리해서 LLM으로
보고서 만드는 것"이 목적인데, 지금까지 price_* 4종은 호출자가 KOMIS
`getMnrlPrcByMnrkndUnqCd` 응답을 매번 손으로 report_gen 자체 스키마
(`observations[].date/commerce_price/lowest_price/highest_price/
inventory`, `komis_period_comparisons.{week,month,year}.
{average_price,change_pct}`)로 옮겨 담아야 했다 — 이 손 번역 과정에서
실제로 버그가 두 번 났다(0.00 결측값을 그대로 실어 최고/최저가가 깨진
사례, 비교광종 페이지 제한을 잘못 안 사례). "구조를 바꿔야 하지
않느냐"는 지적에 따라 손 번역 자체를 없앤다.

## 변경
`AnalysisSummaryRequest`(및 라우터 `MineralDateRangeSummaryRequest`)에
`komis_response: dict | None = None` 필드 신설(price_* 4종 전용, 다른
page_id로 보내면 거부). 값이 있으면 `summary.py::
_parse_komis_price_response()`가 KOMIS 원본 그대로 파싱해서 기존 3개
필드(`observations`/`compare_observations`/`komis_period_comparisons`)를
직접 만든다 — 값이 있으면 이걸 우선 쓰고, 없으면(하위호환) 기존처럼
호출자가 손으로 채운 필드를 그대로 쓴다.

매핑:
- `data.defaultMnrl[]` → `observations`(`crtrYmd` YYYYMMDD→YYYY-MM-DD,
  `cmercPrc`→`commerce_price`, `lowstPrc`/`hghstPrc`/`invt`는 0.00을
  항상 None으로 정규화 — 8/30에 고친 값 기반 게이트를 파싱 단계에서도
  적용해 같은 버그가 재발할 여지를 없앴다)
- `data.compareMnrl[]` → `compare_observations`(같은 매핑, 있을 때만)
- `dataAvg.stdMap.{WEEK,MONTH,YEAR}` → `komis_period_comparisons`
  (`average_price = latest_price - flctnPrc`, `change_pct = flctnPrcnt`
  — 기존 하네스와 동일 산식)
- `dataAvg.INFO.mnrkndKornNm` → `mineral_name` 자동 채움(호출자가
  명시하면 그쪽 우선)

`mineral`(코드)·`compare_mineral`(코드)은 KOMIS 응답 본문에 없는 조회
파라미터라 호출자가 여전히 명시해야 한다 — 그 외엔 KOMIS API 응답을
그대로 포워딩하면 끝이다.

## 검증
- 사용자가 실제로 붙여준 니켈 원본 JSON(축약 표본)을 `mineral='MNRL0006'`
  + `komis_response=<원본 그대로>`만으로 호출 — 전일/전주/전월/전년·
  현재위치·재고량까지 전부 정상 산출 확인(필드 수동 매핑 0건).
- `dataAvg.INFO.mnrkndKornNm`("니켈") 자동 채움 확인.
- 라우터 모델(`MineralDateRangeSummaryRequest`) 경로까지 전부 통과 확인.
- `komis_dump_smoke_test.py` 회귀 395콤보 전부 mismatch 0 유지(기존
  손 매핑 경로는 그대로 살아있어 하위호환).

## 커밋
`models.py`·`routers/analysis.py`·`summary.py` — main-agent 승인 후
재빌드·재기동 필요. 실제 캐스터(streamlit/외부 API 클라이언트)가
`observations` 손 매핑 코드를 걷어내고 `komis_response`로 바로 바꾸는
건 별도 연동 작업(streamlit-agent/main-agent 영역).
