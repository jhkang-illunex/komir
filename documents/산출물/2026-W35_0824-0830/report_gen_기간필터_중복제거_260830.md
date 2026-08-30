# report_gen — 기간 필터 필드(start_date/end_date 등) 6쌍 제거 (2026-08-30)

## 배경
사용자가 `/api/v1/analysis/prices/base-metals` Swagger를 다시 보여주며
지적: "{mineral, mineral_name, start_date, end_date, komis_response,
compare_mineral, compare_mineral_name} 이렇게나 많네 정말 필요한것만
남기라니까 start_date, end_date가 필요하냐고?"

## 조사

### 1차 — 캐스터가 실제로 이 필드를 쓰는지
`grep -n "start_date\|end_date" inhouse/streamlit_demo/views/report_demo.py
inhouse/streamlit_demo/report_gen_client.py` → `PAGE_SPECS`에
`period_fields = ("start_date", "end_date")`(price_* 4종·composite-index·
domestic-trade·global-trade)로 실제 선택 입력란(placeholder만 있고 빈
값이면 payload에 안 실림)으로 렌더링되고 있었다. 나머지 두 쌍도 확인:
`start_year`/`end_year`(mineral-map)·`start_period`/`end_period`
(price-forecast)도 같은 패턴으로 쓰이고 있었다 — 6쌍 전부 "죽은
필드"는 아니라는 뜻.

### 2차 — 그런데도 제거가 맞는 이유
`request_id`/`analysis_scope`(2026-08-31 제거)처럼 "완전히 무효과"는
아니지만, 기능적으로 **순수 중복 레이어**였다:
- 이 6쌍은 전부 `komis_response`로 이미 받은 시계열을 report_gen이
  사후에 다시 좁히는 필터다.
- 그런데 "어느 기간을 보고 싶은지"는 애초에 KOMIS 조회 자체(호출자가
  KOMIS에 던지는 파라미터)로 이미 결정된다 — `komis_response`는 그
  결과를 그대로 담고 있으므로, 범위를 좁히고 싶으면 KOMIS 조회를
  그 범위로 다시 하면 된다.
- report_gen이 받은 뒤 또 한 번 잘라내는 두 번째 필터 지점을 별도로
  둘 필요가 없다 — 실사용은 있었지만 "필요한 실사용"은 아니었다.

## 변경
`app/routers/analysis.py`에서 6쌍 제거:
- `_DateRangeMineralRequest`(price_*·domestic-trade·global-trade
  공유 베이스) — `start_date`/`end_date` + `validate_period` 검증기
- `CompositeIndexSummaryRequest` — `start_date`/`end_date` + 검증기
- `MineralMapSummaryRequest` — `start_year`/`end_year` + 검증기
- `PriceForecastSummaryRequest` — `start_period`/`end_period` +
  medium/long 기간형식 교차검증(둘 다 필드 없이는 대상이 없어
  통째로 제거)

미사용이 된 `Day`/`ForecastPeriod` import도 함께 정리.

`PriceSummaryRequest` 최종 필드: `mineral`(필수) + `mineral_name`·
`compare_mineral`·`compare_mineral_name`·`komis_response`(전부 선택)
= 5개 — 사용자가 원래 보여준 7개 Swagger에서 정확히 2개 감소.

## ⚠️ streamlit_demo 쪽 조치 필요(중요 — 처음으로 "동작하는 UI"를 깬다)
지금까지의 트리밍(observations·request_id·analysis_scope 등)은 전부
"이미 아무도 안 쓰던" 필드 제거였다. 이번엔 다르다 — streamlit_demo가
이 6쌍을 실제 선택 입력란으로 렌더링해서 값이 채워지면 payload에
실어 보낸다. `extra="forbid"`라 캐스터가 값을 채우는 순간 조용히
`NO_DATA`로 떨어진다(실측 확인: `start_date` 하나만 얹어도 status가
`ok`→`NO_DATA`). **streamlit_demo가 이 6쌍의 UI 입력란(또는 최소한
페이로드 전송)을 report_gen과 같은 배포 주기에 맞춰 제거해야 한다** —
streamlit-agent에 통지 예정.

## 검증
- `TestClient`로 6개 요청 스키마 재조회 — 6쌍(12개 필드) 전부 사라짐
  확인.
- 니켈 실데이터로 `prices/base-metals` end-to-end 재현 — `status=ok`,
  보고서 정상 생성(596자).
- stray `start_date`를 실어 보내는 회귀 케이스 — `status=NO_DATA`
  확인(예상된 실패 모드, 문서화 목적).
- `komis_dump_smoke_test.py` 회귀 395콤보 전부 mismatch 0 유지(이
  하네스는 `AnalysisSummaryService`를 직접 호출해 라우터 스키마
  변경과 무관).

## 커밋
`app/routers/analysis.py` — main-agent 승인 후 재빌드·재기동 필요.
streamlit_demo 쪽 UI 갱신은 streamlit-agent 담당.
