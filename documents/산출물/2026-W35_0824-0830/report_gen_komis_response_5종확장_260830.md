# report_gen komis_response — 나머지 5종(map_korea/global/mineral, indicator_composite, forecast_price) 확장 (2026-08-30)

## 배경
price_* 4종에 `komis_response`(KOMIS 원본 응답 통째 수용) 신설 후,
main-agent가 같은 패턴을 로그인 불필요한 나머지 5종으로 확장 지시.
같은 날 사용자가 "하위호환 무관 싹다 교체"라고 명확히 해서, price 때처럼
조심스러운 이중경로 설계 대신 곧바로 `komis_response`를 각 페이지의
1차 입력 경로로 얹었다(기존 `observations` 손 매핑 필드는 스키마에는
남아있지만 — 다른 페이지들과 모델을 공유해서 완전 제거는 안 함 —
새 캐스터는 `komis_response`만 쓰면 된다).

## 매핑(페이지별 KOMIS 엔드포인트 → report_gen 필드)
| page_id | KOMIS 엔드포인트 | 응답 구조 → report_gen |
|---|---|---|
| map_korea | `getListKoreaData` | 응답 자체가 `list`(국가별 행) — 행엔 날짜가 없어 응답이 그대로 되돌려주는 `srchDateE`(조회 파라미터 echo)를 관측일로 씀. `sumIncmAmt`/`sumExpAmt`→komis_trade_totals |
| map_global | `getListDataNation` | `list`(도착국·원산국 루트 행). `srchDateE` 동일 echo. `sumAmt`→komis_trade_totals |
| map_mineral | `getListMapMnrlChartData` | `data`(연도×국가 행, `burudgQuty`/`prdctnQuty` 둘 다 항상 존재). `measure`는 응답에 없는 조회 파라미터라 여전히 호출자 명시. `cdVal`→unit 자동 채움 |
| indicator_composite | `getLineChartIndx` | `data.tableData`(날짜×지수유형 3종, MNRL/MAJOR/RARE)를 crtrYmd로 묶어 관측치 1건(세 지수값)으로 합침 — **스냅샷이 아니라 시계열 전체를 파싱해야 한다**(Phase4에서 확정한 바로 그 이슈) |
| forecast_price | `getListPricePredc` | `data`(분기별 행, `crtrPrd`="28년 4Q" 형식→`YYYY-QN`, `realYn`→`is_actual`). `forecast_horizon`은 응답에 없는 조회 파라미터라 여전히 호출자 명시 |

각 페이지의 `mineral`(코드)·`measure`·`forecast_horizon`처럼 KOMIS 응답
본문에 없는 "조회 파라미터"는 계속 호출자가 명시해야 한다 — 응답
본문에 있는 값은 최대한 자동으로 뽑는다(map_mineral의 unit=`cdVal`처럼).

## 검증
Phase3·Phase4에서 이미 캡처해둔 실제 evidence JSON(구리·니켈 라이브
응답)을 그대로 `komis_response`에 얹어 5종 전부 재현:
- map_korea: 수입총액 10,941,953,600(=KOMIS `sumIncmAmt`) 정확히 일치,
  1위(칠레 23.27%)·상위3(44.32%)·상위5(59.59%) 산출.
- map_global: 세계교역총액 26,396,166,408.81(=KOMIS `sumAmt`) 정확히
  일치, 1~3위 루트(칠레→일본/미국/인도)·대한민국 순위(25위)까지 산출.
- map_mineral: unit "k ton" 자동 채움, 매장량 4개년(2021~2025)·1~3위국
  정상 산출.
- indicator_composite: `tableData` 전체(365일치)를 시계열로 파싱해
  전주(+1.78%)/전월(+3.89%)/메이저·희소금속 지수·조회기간 최고최저까지
  전부 산출 — 스냅샷 축소 없이 시계열 전체 반영 확인.
- forecast_price: 112개 분기(2001Q1~2028Q4) 중 `realYn="N"`인 8개
  예측분기(2026Q3~2028Q4)만 정확히 골라 예측 요약을 만듦(첫 예측시점이
  정확히 2026년 3분기로 시작 — 104개 실측 분기 완전 배제 확인).

`komis_dump_smoke_test.py` 회귀 395콤보 전부 mismatch 0 유지(기존
손 매핑 경로는 그대로 살아있어 영향 없음).

## 커밋
`models.py`(komis_response page_id 확장)·`summary.py`(5개 파서 함수 +
5개 `_analyze_*` 메서드 배선)·`routers/analysis.py`(3개 라우터 모델에
komis_response 필드 추가) — main-agent 승인 후 재빌드·재기동 필요.
