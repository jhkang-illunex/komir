# report_gen — 정의문 "일별" 하드코딩을 실제 조회단위로 동적화 (2026-08-31)

## 배경
사용자 지적: "입력으로 평균 옵션이 들어오는데 타이틀에는 일별
실거래라고 하드코딩 된것 같은데요, 이부분은 입력된 평균 옵션대로
실거래가라고 써야 하지 않을까요?" — 직전 커밋(`8847b9ae9`)에서
`srch_avg_opt`(평균옵션) 명시 입력을 추가했지만, 정의문(보고서 제목
줄, `page_definition`)은 `KOMIR_PAGE_CONTEXTS`의 정적 문자열("...일별
실거래가...")을 그대로 썼다 — 실제 조회 단위가 주/월/분기/년이어도
제목엔 항상 "일별"로 나오고 있었다.

## 수정
`app/analysis/summary.py::_analyze_price`에서 `response = AnalysisSummary
Response(...)`를 만들기 직전, `komir_summary.py::_detect_granularity`
(요청에 `srch_avg_opt`가 있으면 그 값, 없으면 관측치 날짜 간격 추론)로
실제 단위를 판별해 `context.definition`의 "일별"을 "{단위}별"로
치환한다. price_base_metals/minor_metals/iron_energy/other 4개 정의문
전부 "일별"이 "실거래가" 바로 앞에 정확히 1번만 있어 안전하게 치환된다.

## 검증
- 실측 3종 — DAY 응답(추론)="일별", MONTH 응답(추론)="개월별", DAY
  응답에 `srch_avg_opt=QUARTER` 강제="분기별" — 전부 의도대로 동작.
- price_minor_metals(가돌리늄, DAY 응답 + `srch_avg_opt=WEEK`)도 동일
  치환 확인, `report_render.py`의 존댓말 변환(2026-08-31 앞선 커밋)과도
  정상 합성됨("...주별 실거래가·최저가·최고가 추이를 보여주는
  자료입니다.").
- 회귀 395콤보 mismatch 0.

## 커밋
`app/analysis/summary.py` — main-agent 승인 후 재빌드·재기동(seed_prompts
불필요, output_contract 미변경).
