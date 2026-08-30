# report_gen — 자동채움 가능 필드 3차 재감사 (2026-08-30)

## 배경
`compare_mineral_name` 자동채움 누락(커밋 9598776b8)이 grep 기반
2차 감사(260830 문서)의 사각지대에서 나왔다 — "필드가 쓰이는가"만
확인하고 "komis_response 실제 구조에 이 필드에 대응하는 값이
있는가"는 안 물었다. 사용자가 "나머지 페이지도 자동채움 가능한
필드 있는지 다시 확인해줘"라고 요청 — 이번엔 grep이 아니라 **각
페이지의 실제 캡처된 KOMIS 응답 원문을 직접 열어** 모든 optional
필드를 하나씩 대조했다.

## 방법
`documents/산출물/2026-W35_0824-0830/report_gen_KOMIS라이브재검증_
Phase{1,2,3,4}_260829_evidence/`의 실측 라이브 캡처(map_korea·
map_global·map_mineral·composite·forecast 전부 포함)를 열어 각
페이지의 `komis_response` 최상위/중첩 키를 전부 나열하고, 남은
optional 필드마다 "이 값에 대응하는 키가 응답 어딘가에 있는가"를
직접 확인했다.

## 결과 — 페이지별

| 페이지 | 남은 optional 필드 | 대응 키 유무(실측) | 결론 |
|---|---|---|---|
| map_korea(`getListKoreaData`) | mineral_name | 응답에 `mnrkndKornNm`/INFO 블록 자체가 없음(국가 행에만 `ntnKornNm`) — 실측 확인 | 자동채움 불가, 현행 유지 |
| map_global(`getListDataNation`) | mineral_name | 위와 동일(국가명만 있고 광종명 없음) — 실측 확인 | 자동채움 불가, 현행 유지 |
| map_mineral(`getListMapMnrlChartData`) | mineral_name | 행에 `ntnKornNm`(국가명)·`cdVal`(단위)만 있고 광종명 없음 — 실측 확인 | 자동채움 불가, 현행 유지 |
| forecast_price(`getListPricePredc`) | price_unit | 행(`mnrkndKornNm`·`crtrPrd`·`prc`·`realYn`)에도, `chartData`(Bloomberg/JP Morgan 등 예측기관 시리즈)에도 단위 필드 없음 — 실측 확인 | 자동채움 불가, 현행 유지 |
| price_*(`getMnrlPrcByMnrkndUnqCd`) | (전부 이미 자동채움됨) | `mineral_name`(stdMap.INFO)·`price_criterion`(stdMap.INFO)·`compare_mineral_name`(cmpMap.INFO, 방금 수정) | 추가 없음 |
| composite-index | (필드 없음, komis_response뿐) | 해당 없음 | 추가 없음 |

## 결론
`compare_mineral_name`을 제외하면 나머지 페이지엔 실제로 자동채움
가능한 필드가 더 없다 — 이번엔 grep이 아니라 실제 응답 JSON 키를
직접 대조한 결과라 근거 수준이 다르다(2차 감사가 놓쳤던 종류의
사각지대를 이번엔 막았다).

## 참고(범위 밖) — compare_price_criterion 관련 발견
감사 중 부수적으로 확인: `dataAvg.cmpMap.INFO.prcCrtr`(비교광종
자체의 가격기준, 예: "99.99%min FOB China")도 응답에 있지만,
`compare_series`(요약 계산기에 넘기는 비교 계열) 조립부
(`summary.py::_analyze_price`)는 애초에 비교광종의 가격기준을
표시하는 필드 자체를 만들지 않는다(price_criterion_serial=0만
고정). 이건 "기존 필드의 자동채움 누락"이 아니라 "필드/기능이
아예 없음"이라 이번 감사 범위(자동채움) 밖이다 — 필요하면 별도
기능 추가 논의.

## 검증
코드 변경 없음(순수 감사) — 커밋·재빌드 불필요.
