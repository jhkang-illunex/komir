# report_gen — 핵심광물지도(map_mineral) KOMIS 엔드포인트 2개 추가 (2026-08-31)

## 배경
사용자 지시: "핵심 광물지도 ... 광물지도 테스트 페이지에는 기존 데이터
url 말고 두개 url이 더 필요하네요" — `getListMnrlTablePrdctnBurgudg`
(매장량 현황)·`getListMapMnrlData`(연도별 국가별 매장량 현황)를 report_gen
데이터소스·API·요약문에 추가 요청. 기존엔 `getListMapMnrlChartData` 1개
엔드포인트만 파싱했다(`income_data/komis/komis_08_mineral_map.json` 실측
덤프로 이 페이지의 실제 엔드포인트가 정확히 3개임을 확인).

## 실측으로 정정된 사용자 원 설명 2건
1. **"연도별 국가별 매장량 현황(getListMapMnrlData)은 마지막 연도만 온다"**
   — 실측 결과 정확한 메커니즘은 **요청 기간(srchDateS~srchDateE) 전체를
   합산**하는 것이었다(2019~2025로 조회 시 890,000,000 = 개별연도
   합계와 정확히 일치, 생산량 필드도 동일 패턴). 사용자 예시 URL이
   이미 srchDateS=srchDateE(단일연도)라 결과적으로 "마지막 연도만
   온다"고 보인 것 — 실사용과 어긋나지 않음, 단일연도 조회 전제로
   문서화.
2. **매장량 현황(getListMnrlTablePrdctnBurgudg)의 `rate` 필드**는 처음
   "전년대비 증감률"로 추정했으나 실측 대조(여러 광종·국가 표본에서
   정확히 일치) 결과 **"해당 국가가 이 표의 `_TOTAL_`(표에 나열된
   국가들의 소계)에서 차지하는 비중(%)"**이었다. 이 `_TOTAL_`은
   `getListMapMnrlChartData` 기반 세계합계보다 체계적으로 작다(실측
   4개 광종에서 4~11배 차이 — 표에 나열된 국가 수만큼만 합산된 소계라
   그렇다) — 그래서 이 값을 "세계비중"으로 라벨링하면 기존 자체계산
   비중(`top_country_share`)과 같은 국가에 완전히 다른 숫자가 나란히
   보여 오해를 준다. 라벨을 "국가목록 내 비중(KOMIS 매장량표 기준)"
   으로 명시해 구분했다.
3. 사용자 후속 지시로 매장량 현황(before1~before5 5개년 표)은
   가장 최근 연도(before1)만 쓰기로 단순화("매장량 현황은 가장
   마지막 년도 값만 사용해요").

## 구현
### 필드 (models.py / routers/analysis.py)
- `komis_snapshot_response`(`getListMapMnrlData`) 신설 — 국가별 매장량·
  생산량을 한 응답에 동시에 준다는 걸 확인해, 옛
  `secondary_measure_observations`/`secondary_unit`(2026-08-27 신설,
  손입력 전용, "komis_response가 아직 커버 못 하는 유일한 기능"이라
  코드 주석에 남아있던 필드)를 **완전히 대체·제거**(사용자 확인:
  "대체(권장)"). 연도는 별도 필드 없이 primary 계열의 최신연도
  (`available_end_year`)로 라벨링 — 교차비교 게이트가 그 연도 데이터를
  찾으므로 구조적으로 맞다.
- `komis_share_response`(`getListMnrlTablePrdctnBurgudg`) 신설 — page_id=
  map_mineral 전용, `validate_period`에 page_id 가드 추가.

### 파서 (summary.py)
- `_parse_komis_map_mineral_snapshot_response(raw, measure, year)` —
  기존 `_parse_komis_mineral_map_response`와 대칭 구조(반대 measure의
  value_key 추출 + totalBurudgQuty/totalPrdctnQuty로 WORLD 행 합성).
- `_parse_komis_map_mineral_share_response(raw)` — `_TOTAL_`(SU)·
  `_ETC_`(OT) 행은 국가 랭킹에서 제외, before1+rate만 추출. 콤마
  천단위 구분자 숫자 문자열 파싱용 `_komis_num_comma` 신설(다른 KOMIS
  엔드포인트는 콤마 없는 문자열이라 기존 `_komis_num`은 그대로 둠).
- `_analyze_mineral_map`에서 `komis_snapshot_response`→secondary_series,
  `komis_share_response`→market_share로 배선. 둘은 서로 독립(하나만
  보내도 동작).

### 요약 반영 (additional_summary.py)
- `calculate_mineral_map_summary(series, *, secondary_series=None,
  market_share=None)` — `market_share` 신규 파라미터.
- 1위국 비중은 기존 `current_leaders` claim이 이미 자체계산값으로
  말하고 있어 같은 숫자를 claim으로 중복 서술하지 않고(advisor 권고),
  상위 5개국의 KOMIS 공식 비중을 detailed_metrics 표로만 추가
  (`komis_market_share_{country_code}`, 라벨 "{국가} 국가목록 내
  비중(KOMIS 매장량표 기준)"). 기존 claim/랭킹 로직은 무수정.

## 검증
- pydantic 검증 3종 — 옛 필드 전송 시 거부(extra=forbid 확인), 신규
  2개 필드의 page_id 가드(price_* 페이지로 보내면 거부) 확인.
- 실측 3종(income_data/komis/komis_08_mineral_map.json, MNRL0046 희토류
  시료용/매장량) — komis_response+komis_snapshot_response+
  komis_share_response 전부 실어 `AnalysisSummaryService(llm=None).analyze()`
  직접 호출:
  - `cross_measure_comparison` claim 정상 생성("매장량 3위 남아공은
    생산량 15위" 패턴).
  - `komis_market_share_*` detailed_metrics 5개국 정상 생성, 라벨에
    "KOMIS 매장량표 기준" 명시.
  - `komis_share_response`만 단독으로 보내도(snapshot 없이) market_share
    는 독립적으로 반영, cross_measure_comparison은 생성 안 됨(정상).
- 회귀 395콤보(`scripts/komis_dump_smoke_test.py`) mismatch 0 유지.
- MNRL0060(규조토) 표본에서 KOMIS 자체 `_TOTAL_`이 0으로 나오는 케이스
  발견 — 개별 국가값은 정상인데 KOMIS 쪽 세계합계 필드가 미기재된
  데이터 품질 이슈로 판단(우리 파싱 버그 아님, rate=0.00으로 자연
  스킵됨).

## 미반영/후속
- streamlit_demo 쪽 UI(두 번째·세 번째 KOMIS fetch + 붙여넣기 UI 배선)는
  streamlit-agent 담당 — 최종 필드 계약(이름·shape·단일연도 전제,
  구 필드 삭제) 통지 완료.
- seed_prompts 재실행 불필요 — 이번 변경은 새 claim/instruction 문구를
  추가하지 않고 detailed_metrics만 확장했다(LLM 검증 계약·
  MINERAL_MAP_SUMMARY_INSTRUCTIONS 무변경).

## 커밋
`app/analysis/models.py`·`app/analysis/summary.py`·
`app/analysis/additional_summary.py`·`app/routers/analysis.py` —
main-agent 승인 후 재빌드·재기동(seed_prompts 불필요).
