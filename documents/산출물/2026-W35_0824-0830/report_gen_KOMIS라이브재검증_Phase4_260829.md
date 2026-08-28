# KOMIS 라이브 재검증 Phase 4 — indicator_composite·forecast_price (2026-08-29)

## 배경
main-agent 지시로 map_korea/global/mineral(Phase 3)과 병행 진행. 조사만 —
코드는 안 건드렸다.

## 1) indicator_composite — 구조적 갭 없음, 확인 완료
KOMIS `/Komis/MnrlIndc/IndxMin` 화면 텍스트를 전수 검색(page.inner_text)한
결과 "전주"/"전월"/"전년"/"주간"/"월간"/"년간" 어느 키워드도 없다 — **이
화면 자체에 전주/전월/전년 비교 UI가 없다.** 화면에 있는 유일한 비교값은
당일 등락(`getLineChartIndx` 응답의 `dataIndx`: `indxVal`/`prvdyFlutPrc`/
`prvdyFlutRt`, "전일"의 prvdy).

이 확인은 라이브 접속 시 기본 프리셋(1년) 로드 상태 기준이라, 추가로
로컬 정적 덤프(`komis_03_mineral_index.json`)에 있는 기간 프리셋 5개
전부(1개월/3개월/6개월/1년/전체(2016~))의 응답 키를 훑어 다른 요약
필드가 있는지 재확인했다 — **5개 프리셋 전부 응답 구조가
`{xaxis, min, max, series, tableData, dataIndx}`로 동일하고, `dataIndx`
값(indxVal=3539.45, prvdyFlutPrc=35.86, prvdyFlutRt=1.02)도 프리셋과
무관하게 동일하다**(기간 프리셋은 차트의 x축 범위만 바꿀 뿐 요약값
자체는 항상 "최신값 vs 전일"만 제공). 즉 위 결론("주/월/년 비교 UI
없음")은 기본 화면 1건이 아니라 화면이 제공하는 전체 기간 프리셋
범위에서 확인된 것이다.

즉 price 페이지의 stdMap 같은 "KOMIS가 이미 계산해준 값을 놓치고 있다"는
구조가 여기엔 성립하지 않는다 — `calculate_composite_summary`
(`additional_summary.py`)의 week/month/year 비교는 `_at_or_before`(N일 전
날짜에 가장 가까운 이전 관측치를 찾는 방식)로 자체 계산하는데, 대조할
KOMIS 화면 표시값 자체가 없으므로 "맞는지 틀린지 확인할 정답"이 없다.
기존 방식을 바꿀 근거가 없다.

**참고(버그 아님, 기능 갭 후보)**: report_gen은 KOMIS가 보여주는 당일
등락(`prvdyFlutRt`)에 대응하는 day-over-day 근거를 만들지 않는다(price
페이지의 `day_over_day`에 해당하는 게 composite엔 없음). 화면에 있는
정보 하나를 report_gen이 안 쓰고 있다는 뜻이라 잠재적 개선 후보로만
기록 — PDF 템플릿이 이걸 요구하는지 별도 확인 안 함(이번 조사 범위 밖).

## 2) forecast_price — 산식 검증 통과, 구조적 리스크 1건 발견(결정 필요)
### 산식 검증
`/Komis/MnrlIndc/PricePred`(니켈·중기)에서 `getListPricePredc`를 라이브
캡처, 분기별 `prc`(가격)·`flutRt`(KOMIS 계산 전분기대비 등락률)를 받았다.
`calculate_price_forecast_summary`(`additional_summary.py`)는 인접
관측치 가격 차이로 방향·전환점을 자체 계산하는데, 111개 연속 분기 전수
대조 결과 **111/111 정확히 일치** — day_over_day와 같은 이유로("인접
관측치 직접 비교") 재구현 필요 없이 이미 KOMIS와 일치한다.

이 검증은 **니켈 1광종**(중기 예측 기본값)에 한정됐다 — 이 문서의 다른
수치(구리 stdMap, 재고량, map 총액 등)는 다광종/전수 검증인 것과 달리
이건 표본 1건이다. flutRt 산식이 광종별로 다를 구조적 이유는 없지만
(전분기 대비 가격차/전분기가격 — 광종 무관 동일 공식), 미검증임을
명시해둔다.

### 신규 발견 — 실측 데이터에 과거 실적과 미래 예측이 섞여 있음
`getListPricePredc`가 준 112개 분기(2001년 1Q~2028년 4Q)를 보니, **최근
8분기(2026년 3Q~2028년 4Q)만 `realYn:"N"`(예측)이고 나머지 104분기는
`realYn:"Y"`(실측)**다 — 즉 "중기(3년) 예측" 조회 1건에 27년치 과거
실적과 3년치 미래 예측이 함께 온다(차트 배경으로 과거 추세를 보여주려는
KOMIS UI 설계로 보인다).

`PriceForecastObservation`(`models.py`) 모델엔 `period`·`price`만 있고
`realYn` 개념이 없다 — 만약 호출자가 이 응답을 거르지 않고 112개 분기를
그대로 report_gen에 넘기면, `calculate_price_forecast_summary`는 27년치
**실측 가격 등락**을 "예측가격의 방향은... N차례 바뀌어 등락이 반복되는
경로다"처럼 **전부 예측인 것처럼** 서술한다 — "예측"과 "실적"이 뒤섞여
발주처가 보면 혼란스러울 수 있는 지점이다.

**현재 실제로 위험한지는 확인 못 했다** — `report_demo.py`의 forecast_price
placeholder는 2개 분기짜리 얇은 예시라(price_base_metals와 같은 패턴)
실제 KOMIS 데이터를 caller가 어떻게 거르는지는 이번 조사로 확인 불가.
그래서 이건 "지금 배포에 있는 버그"가 아니라 **"실 API/데모 연동 시
호출자가 반드시 `realYn:"Y"`(실측)는 거르고 `"N"`(예측)만 넘겨야 한다"는
연동 요구사항**으로 문서화해둔다 — map_korea 시계열 발견(Phase 3 §2)과
같은 성격("코드 문제가 아니라 호출자가 갖춰야 할 데이터 형태").

**권고(참고, 결정은 main-agent 몫)**: (b) `is_actual`류 optional 필드
추가를 권한다. (a)(문서 규약만으로 필터를 caller에 위임)는 강제력이
없어서, 이 세션에서 이미 한 번 겪은 실패 모드(재고량 0.00 — "값이
있으면 신뢰한다"는 암묵 가정이 깨졌던 사례)와 같은 성격의 위험을 남긴다
— 호출자 구현이 realYn 필터링을 빠뜨리면 report_gen은 아무 신호 없이
27년치 실적 등락을 "예측"으로 서술한다. (b)는 `PriceForecastObservation`에
`is_actual: bool | None = None`처럼 optional 필드를 추가해(기존 요청과
하위호환 유지) 계산기가 있으면 예측구간만 골라 쓰고 없으면 지금처럼
전체를 예측으로 취급하는 폴백을 두는 방식 — geo_events·
komis_period_comparisons·komis_trade_totals와 같은 "요청 레벨 선택
필드" 패턴 그대로라 이 세션의 기존 설계와 일관적이다.

### 종합 판정
| 항목 | 확정도 | 처방 후보 |
|---|---|---|
| indicator_composite week/month/year | 문제 없음 | 조치 불필요 |
| indicator_composite 당일등락 미노출 | 기능 갭(버그 아님) | PDF 요구사항 확인 후 필요시 day_over_day 근거 추가 검토 |
| forecast_price QoQ 산식 | 문제 없음(111/111 검증) | 조치 불필요 |
| forecast_price 실측/예측 혼입 | **구조적 리스크**(현재 미발현, 연동 시 발현 가능) | (a) 호출자가 realYn="N"만 필터해서 보내도록 연동 가이드 문서화(코드 무수정) / **(b, 권고) `PriceForecastObservation`에 `is_actual`류 optional 필드 추가 — 결정 필요** |
