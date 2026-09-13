# 광물가격·핵심광물지도 신규조건 확인 (2026-09-13)

> 배경: "요약 보고서에서 광물가격 및 핵심 광물 지도에 대해서 지금까지 입력된
> 조건 말고 다른 조건으로 메뉴당 4~5개 정도 넣어도 나온 결과물에 대해서
> 검증 해주세요." — 이 세션에서 이미 예시로 보여준 조건(동·니켈WEEK·코발트·
> 스트론튬WEEK·우라늄·흑연·망간/칼륨/크롬·리튬)은 피하고, 광물가격 4메뉴·
> 핵심광물지도 3메뉴에 각각 4~5개씩 새 조건을 넣어 **배포된 실 컨테이너**
> (`komir-report-gen-test`, 실시간가 수정 반영판, 2026-09-13 배포)에
> `POST /api/v1/analysis/...`로 직접 호출했다. 재현: `fresh_conditions_check.py`.

## 결과 요약

32개 조건 중 28개 `status: ok`, 4개 `status: NO_DATA`(전부 정상 — 아래 참고).
**status: INTERNAL_ERROR는 0건**.

| 메뉴 | 넣은 조건 | 결과 |
|---|---|---|
| price_base_metals | 아연 LME CASH MONTH, 알루미늄 LME 3개월 QUARTER, 연 LME CASH YEAR, 주석 LME 15개월 DAY, 주석 LME CASH WEEK | 1개 ok, 4개 NO_DATA |
| price_minor_metals | 네오디뮴 DAY, 리튬(수산화물) WEEK, 텅스텐(APT) MONTH, 몰리브덴 QUARTER, 갈륨 YEAR | 5/5 ok |
| price_iron_energy | 유연탄(Qinhuangdao 기준), 유연탄(Henan 기준) | 2/2 ok |
| price_other | 철, 금, 루테늄, 백금, 팔라듐 | 5/5 ok |
| map_korea | 니켈 수입, 코발트 수입, 리튬 수출, 희토류 수입, 흑연 수입 | 5/5 ok |
| map_global | 동, 니켈, 코발트, 희토류, 흑연 (전부 수입 라우트 기준) | 5/5 ok |
| map_mineral | 니켈 생산량, 코발트 매장량, 리튬 생산량, 희토류 매장량, 흑연 생산량 | 5/5 ok |

## NO_DATA 4건은 report_gen 문제가 아니다

`아연|LME CASH|MONTH`·`알루미늄|LME 3개월|QUARTER`·`연|LME CASH|YEAR`·
`주석|LME CASH|WEEK` — raw KOMIS 덤프(`komis_01_base_metals.json`)에서
해당 조합의 `data.defaultMnrl` 자체가 **0행**이다(수집 당시 그 조합만
빈 응답이 캡처된 것으로 보임 — 수집 스냅샷의 한계이지 report_gen 계산
로직의 문제가 아니다). report_gen은 이 경우 정확히 설계대로
"observations가 비었다" → `NO_DATA`로 응답한다(크래시·`INTERNAL_ERROR`
아님) — 원래 있어야 할 정상 동작.

## ok 28건 교차검산

- **가격 12건**(price_minor_metals 5·price_iron_energy 2·price_other 5·
  price_base_metals 1) — "현재가격" 표 값을 KOMIS `dataAvg.stdMap.CRTRYMD`
  (없으면 `DAY`)의 실시간 현물가와 대조, 12/12 정확히 일치. 등락률(전주/
  전월/전년 대비)도 몇 건은 직접 나눗셈으로 재확인(예: 텅스텐 87.69/88.69
  =-1.13%, 유연탄 127.51/125.86=+1.31%, 팔라듐 1337/1344.40=-0.55%) — 전부
  산수 일치(09-13 오전 수정한 "현재가=실시간가" 기준이 이 새 조건들에서도
  깨지지 않음을 재확인).
- **map_korea 5건** — "수입총액"/"수출총액" 표 값을 KOMIS `sumIncmAmt`/
  `sumExpAmt`와 대조, 5/5 일치(예: 니켈 수입 230.52억=23,052,177,200 정확히
  일치).
- **map_global 5건** — "세계 교역 총액"을 KOMIS `sumAmt`와 대조, 5/5
  일치(예: 동 28,081.01억=2,808,101,137,990.07 정확히 일치).
- **map_mineral 5건** — 이 5개 조합(니켈 생산량·코발트 매장량·리튬
  생산량·희토류 매장량·흑연 생산량)은 오늘 오전 `full_verify.py` 전수검증
  (66개 map_mineral 조합 전부, 이 5개 포함)에서 이미 세계총계·1위국·CR3/CR5
  독립 재계산 대조를 마쳤다 — 이번엔 그 검증된 계산이 **배포된 컨테이너**
  에서도 그대로 나오는지 실 HTTP로 재확인(전부 `status: ok`, LLM 정제
  경로까지 정상).

## 참고로 남긴 것(버그 아님, 통계 심화층이라 정밀검증 범위 밖)

텅스텐(APT, MONTH) 조건에서 "연속 6개월 하락세"와 "단기·중기 가격 흐름은
모두 상승 방향"이 한 문단에 같이 나온다 — 전자는 최근 관측치 연속 방향
(단순 direction streak), 후자는 이동평균(MA) 기반 추세 판정이라 서로 다른
정의라서 방향이 엇갈릴 수 있다(기존 로직, 이번에 새로 생긴 문제 아님).
`report_gen_풀검증_보고서_260913.md`의 "검증 범위 밖" 절에 이미 명시한
통계 심화층(MA/RSI 등)이라 이번 확인에서 깊게 파지 않았다 — 필요하면
별도로 짚어볼 수 있다.
