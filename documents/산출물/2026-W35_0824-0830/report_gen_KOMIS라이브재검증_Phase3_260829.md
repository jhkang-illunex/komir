# KOMIS 라이브 재검증 Phase 3 — map_korea·map_global·map_mineral (2026-08-29)

## 배경
main-agent 지시: 세 페이지를 Playwright로 실제 접속해 API 응답을 캡처하고,
지금 report_gen이 만드는 요약(1위국 비중·CR3/5·기간변화율 등)이 KOMIS가
이미 계산해준 값을 놓치고 있지 않은지 확인. **조사만 — 코드는 안
건드렸다.**

## 방법
- 동(MNRL0008)으로 세 페이지(`/Komis/MnrlMap/Korea`·`/Komis/MnrlMap/Nation`·
  `/Komis/MnrlMap/MnrlMap`)를 라이브 접속해 검색 시 발생하는 모든 JSON
  XHR을 `page.on("response")`로 캡처(evidence 폴더).
- 라이브 1건으로 끝내지 않고, 이미 로컬에 있는 정적 덤프(`income_data/
  komis/komis_06_supply_map_korea.json`·`komis_07_supply_map_global.json`,
  2026-08-26 캡처, gitignore 영역)의 **전체 콤보(map_korea 146개, map_global
  73개)**로 아래 §1 발견의 규모를 정량화했다(네트워크 불필요, 로컬 분석).

## 1) 총액 절단(list truncation) — map_korea·map_global 둘 다, map_global이 특히 심각
### 발견
`getListKoreaData`(map_korea)·`getListDataNation`(map_global) 응답의 `list`는
**관측상 최대 30행**(절단이 걸린 콤보는 전부 정확히 30행 — 하드 페이지
크기로 추정되나 서버 스펙으로 확인된 건 아님)까지만 국가/루트를 나열하는데, 같은 응답에 KOMIS가 이미
계산한 **진짜 전체 합계**가 매 행마다 반복 필드로 함께 온다:
- map_korea: `sumIncmAmt`/`sumExpAmt`/`sumIncmWeig`/`sumExpWeig`
- map_global: `sumAmt`/`sumWeig` + 심지어 **행별 점유율까지 이미 계산된
  `amtRate`/`weigRate`**(검증: `amt/sumAmt*100`과 소수점까지 정확히 일치 —
  912,677,544.84/26,396,166,408.81×100=3.46=`amtRate` 그대로)

그런데 `komir_summary.py::calculate_domestic_trade_summary`/
`calculate_global_trade_summary`는 이 sum 필드를 전혀 안 읽고
**요청받은 `observations`(=list의 가시행)를 그대로 합산**해 `total_amount`를
만든다 — list가 절단돼 있으면 총액이 과소, 그래서 `top1_share_pct`/
`top3_share_pct`/`top5_share_pct`가 전부 **과대**해진다(분모가 작아지므로).
이건 `calculate_mineral_map_summary`(`additional_summary.py::_world_total`)가
이미 `is_total` 플래그로 KOMIS 공식 합계를 우선 쓰고 없을 때만 합산하는
것과 대비된다 — map_mineral은 올바른 참조 패턴이고, map_korea/global은
그 패턴을 안 따르고 있다.

### 규모(정적 덤프 전체 콤보 정량화)
**1차 분석에서 방향(수입/수출) 매칭 버그를 발견·재실행했다** — map_korea는
수입·수출 콤보가 섞여 있는데, 처음엔 콤보 방향과 무관하게 `incmAmt`/
`sumIncmAmt`(수입 필드)만 썼다. 수출 콤보의 list는 애초에 수출액 기준
상위 랭킹이라 그 행들의 "수입액" 합과 "수입총액"을 비교하면 의미 없는
큰 갭이 나온다 — 실제로 1차 결과의 최악 사례가 전부 수출 콤보였다(버그
아티팩트였다는 신호). 콤보 키의 방향(`|수입|`/`|수출|`)에 맞춰
`incmAmt`↔`sumIncmAmt`, `expAmt`↔`sumExpAmt`로 재매칭해 재실행했다
(map_global은 덤프에 수출 콤보가 있어도 전부 0행이라 원래 분석 그대로
유효함을 확인).

| 페이지 | 콤보 수(검증 대상) | 갭 1% 초과 | 갭 20% 초과 | 중앙값 갭 | 최악 사례 |
|---|---|---|---|---|---|
| map_korea(방향매칭 재실행) | 145 | 9건(6%) | 0건 | 0.0% | 동\|수입: 5.8% 과소(1,352억 vs 실제 1,435억) |
| map_global | 73 | **72건(99%)** | **54건(74%)** | **30.6%** | 알루미늄\|수입: 69.4% 과소(6,497억 vs 실제 21,198억) |

**map_global이 이 문제의 본체다**: 거의 전 콤보(73개 중 72개)가 영향을
받고, 중앙값 갭이 30.6%다 — "가끔 발생하는 예외"가 아니라 map_global
페이지 전체의 구조적 문제다. map_korea는 재검증 결과 영향이 훨씬
작다(최악 5.8%, 20% 초과 콤보 0건) — 여전히 실재하는 문제지만 severity는
map_global보다 낮다. 전체 갭% 배열(방향매칭 전/후 둘 다)은
`report_gen_KOMIS라이브재검증_Phase3_260829_evidence/total_truncation_gap_stats_260829.json`에
보존.

## 2) 시계열 총액 — map_korea가 "single_snapshot"만 내는 이유의 실제 원천 확보
`calculate_domestic_trade_summary`의 `period_total_change` 근거는 관측이
2개 시점 이상이어야 계산되는데, 지금까지는 호출자가 보통 스냅샷 1건만
보내 항상 "관측이 1건뿐이라 기간별 변화는 계산하지 않았다"는
`single_snapshot` 분기로 빠졌다(이전 회귀 표본에서도 관찰됨).

라이브 캡처로 확인한 결과, **`getLineChartDataKorea`가 이미 5개년(2022~
2026) 연도별 총액 시계열을 준다**:
```json
{"crtrYmd": "2022", "totalIncmAmt": 15106085675, "totalExpAmt": 8269295888, ...}
...
{"crtrYmd": "2026", "totalIncmAmt": 10941953600, "totalExpAmt": 5130303324, ...}
```
`totalIncmAmt`(2026)=10,941,953,600은 §1에서 확인한 `sumIncmAmt`와 정확히
같은 값 — 같은 진짜 총액이 여러 엔드포인트에서 일관되게 나온다는 교차
검증이기도 하다. 이건 사용자가 처음 제기한 "정보가 많은데 요약이
빈약하다"는 불만의 **map 버전**일 수 있다 — 호출자가 이 시계열을 같이
넘겨주기만 하면 `period_total_change`가 매번 계산 가능해진다(지금처럼
단일 스냅샷에 의존하지 않아도 된다).

map_global의 `getBarChartDataNation`도 연도별 시계열을 주지만 국가별
분해(이번 캡처 표본 기준 14개국)라 map_korea의 "총액 시계열" 같은 단일
계열은 아니다 —
필요하면 국가별로 합산해 근사할 수 있지만, 이것도 결국 상위 N개국
한정이라 §1과 같은 절단 문제가 있다(총액 자체의 시계열은 아직 못 찾음).

### [2026-08-29 추가확인] "여러 연도 observations를 보내면 자동으로 계산되나" — 예, 막힌 코드 없음
main-agent 질문에 답하기 위해 라이브 데이터로 재현: `calculate_domestic_
trade_summary`(§1의 komis_trade_totals 배선 전 코드)를 읽어보면
`if len(dates) >= 2:` 분기가 이미 있고, 별도 게이트가 없다. 실제로
2026년 국가별 관측치(오늘 캡처)에 합성 2025년 관측치(가격을 0.9배로
스케일한 것 — 산식 검증용, 진짜 KOMIS 데이터 아님)를 섞어 호출했더니
`period_total_change` 근거가 정확히 계산됐다("직전 관측일(2025년 12월
31일) 대비 수입총액이 +11.11% 변동했다" — 1/0.9-1=11.11%, 산식 그대로
정확).

**결론: 코드 수정 불필요.** price_base_metals 데모 placeholder 사례와
같은 패턴 — 호출자가 지금 스냅샷 1건만 보내서 생긴 문제이지, report_gen이
못 만드는 게 아니다. 나중에 데모/실API가 여러 연도(또는 여러 월) 관측치를
함께 보내도록 연동하면 이 근거가 자동으로 채워진다 — 참고용으로만 문서에
남기고, 이번 라운드에서 별도 코드 조치는 하지 않았다.

## 3) map_mineral — 이미 올바른 참조 패턴(positive control)
라이브로 재확인: `getListMapMnrlChartData` 응답의 각 행에 여전히
`totalBurudgQuty`가 존재하고(예: 칠레 2021년 행에 `burudgQuty=200,000,000`
+ `totalBurudgQuty=3,738,700,000`), `_world_total()`이 `is_total` 플래그로
이 값을 최우선으로 쓴다 — §1·§2의 문제가 여기엔 없다.

## 종합 판정 — 처방 후보(결정 대기, 코드 미수정)
| 항목 | 확정도 | 처방 후보 |
|---|---|---|
| map_korea/global 총액 절단 | **확정**(라이브+정적덤프 전수 정량화) | KOMIS `sum*` 필드를 요청 바디 선택 필드로 패스스루(geo_events·komis_period_comparisons와 같은 패턴) — 호출자가 리스트와 함께 sum값을 그대로 넘기면 계산기가 자체 합산 대신 그 값을 우선 사용 |
| map_korea 기간변화율 상시 불가 | **확정**(단일스냅샷 의존이 원인, 원천 있음을 확인) | `getLineChartDataKorea`류 시계열을 호출자가 넘기게 하거나, `observations`를 여러 시점으로 보내도록 호출자 쪽을 바꾸는 방안 — 코드보다 호출자 설계 문제일 수 있어 결정 필요 |
| map_mineral | 문제 없음 | 조치 불필요(참조 패턴 유지) |

**설계 권고(참고, 결정은 main-agent 몫)**: mineral_map처럼 관측치에
`is_total` 합성 행을 섞는 방식은 map_korea/global엔 안 맞는다 —
`calculate_domestic/global_trade_summary`의 랭킹·한국 하이라이트 루프
전부가 그 합성 행을 걸러내야 해서 수정 표면이 커진다(안 거르면 "세계"가
수입 1위국으로 잡히는 식). 대신 이 세션에서 이미 두 번 쓴 패턴
(`geo_events`·`komis_period_comparisons` — 요청 레벨 선택 필드)을
따르는 쪽을 추천한다. `amtRate`/`weigRate`는 패스스루가 굳이 필요 없다 —
총액만 넘기면 계산기가 그걸로 정확히 유도할 수 있음을 위에서 산식으로
검증했다.
