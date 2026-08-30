# report_gen komis_response — 전 페이지 필드 최종 감사 (2026-08-31)

## 배경
사용자가 "나머지 페이지도 확인해줘"라고 지시 — price-forecast에서
`forecast_horizon`을 놓쳤던 것처럼 다른 페이지에도 비슷하게 놓친
자동채움 여지가 있는지 전수 재감사.

## 결과 — 이미 최소치, 추가로 뺄 건 없음(근거 포함)

| 페이지 | 남은 필수 필드 | 확인 방법 | 결론 |
|---|---|---|---|
| price_* 4종 | `mineral` | 니켈 원본 응답 전체(`dataAvg`+`data.defaultMnrl`) 재확인 — 광종 코드가 어디에도 없음, `mnrkndKornNm`(한글명)뿐 | 자동화 불가, 필수 유지 정당 |
| map_korea/global | (없음, 전부 선택) | 어제 확인·수정 완료 | — |
| indicator_composite | (없음, 전부 선택) | mineral 개념 자체가 없는 페이지 | — |
| map_mineral | `mineral`·`measure` | **정적 덤프 390콤보 전수 확인**(`income_data/komis/komis_08_mineral_map.json`) — `측정지표(매장량/생산량)`을 자동 구분할 수 있을지 확인하려 매장량 쿼리 결과와 생산량 쿼리 결과의 필드를 대조했더니, **두 경우 다 `totalBurudgQuty`(매장량 총계)·`totalPrdctnQuty`(생산량 총계)가 항상 같이 온다**(예: "규조토\|매장량\|map"과 "갈륨\|생산량\|map" 둘 다 두 total 필드를 동시에 가짐) — 응답만 보고는 어느 쪽을 조회한 건지 구분 불가 | 자동화 불가 확인(추측 아니라 실측), 필수 유지 정당 |
| forecast_price | `mineral` | 위와 동일 근거 | 자동화 불가, 필수 유지 정당(`forecast_horizon`은 어제 자동화 완료) |
| price_group | (komis_response 대상 아님) | 여러 광종의 이미 계산된 요약을 묶는 집계 페이지라 KOMIS 원본 응답 1건에 대응하는 구조가 아님 | 의도적 범위 밖 — 이번 komis_response 확장 대상이 아니었음(오늘 처음 명시) |
| indicator_market/supply | (komis_response 대상 아님) | 로그인 필요 페이지 — 세션 시작 시점부터 이번 재검증 범위 제외로 확정돼 있었음 | 의도적 범위 밖 |

## 결론
지금까지(어제 8/30~오늘 8/31) 진행한 감사로 komis_response가 적용된
7개 페이지(price_* 4종·map_korea·map_global·map_mineral·
indicator_composite·forecast_price) 전부, "KOMIS 응답 본문에 실제로
없는 값"(mineral 코드 — price_*/forecast_price/map_mineral, measure —
map_mineral)만 필수로 남기고 나머지는 전부 자동채움했거나 이미
선택(0-cost) 필드다. `measure`는 처음엔 자동화될 것처럼 보였지만
실제 정적 덤프로 검증한 결과 KOMIS가 두 total을 항상 같이 준다는
사실을 확인해 "안 되는 이유"까지 확정했다 — 추측이 아니라 실측
근거로 남긴다.

## 산출물(코드 변경 없음 — 순수 감사·검증)
`income_data/komis/komis_08_mineral_map.json`(정적 덤프, git 미추적)
390콤보 전수 스캔 스크립트는 1회성이라 레포에 커밋하지 않음, 이 문서에
근거 요약만 남긴다.
