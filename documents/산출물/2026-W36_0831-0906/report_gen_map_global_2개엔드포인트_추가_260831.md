# report_gen — 글로벌 수급지도(map_global) KOMIS 엔드포인트 2개 추가 (2026-08-31)

## 배경
사용자 지시(streamlit-agent 경유): "핵심광물지도 > 수급지도 > 글로벌"
페이지에 신규 엔드포인트 2개(`getBarChartDataNation`·`getListMapNationData`)를
추가하고 보고서 작성에도 반영. streamlit_demo 쪽 KOMIS 실호출은 이미
구현·배포됐고, report_gen이 이걸 어떻게 받아 반영할지는 이 세션에
위임됐다. 사용자 지시("답 오면 바로 구현해주세요")에 따라 이번엔
AskUserQuestion 없이 실측 검증만 거쳐 바로 구현했다.

## 실측 검증 3건 (구현 전 필수로 확인)
로컬에 이미 있던 실제 캡처 덤프(`income_data/komis/
komis_07_supply_map_global.json` — 3개 엔드포인트 3,285콤보 전부 포함)로
streamlit-agent 재왕복 없이 전부 로컬에서 끝냈다.

1. **`getBarChartDataNation`의 국가합계가 `getListDataNation`의 `sumAmt`와
   다르다.** 같은 조회(갈륨/MNRL0024, 2017년, 수입)에서 list `sumAmt`=
   886,243,588 대 bar 국가합계(2017)=1,391,759,159 — 30%대 차이. 두
   엔드포인트의 "총액" 집계 범위가 다른 것으로 보여, 바차트 합산값을
   "세계 교역 총액"이라 부르지 않기로 했다(map_mineral "세계비중"·
   map_korea "전체의" 오라벨과 같은 부류가 될 뻔한 걸 사전에 막음).
   대신 **1위국 자신의 연도별 원값만** 쓴다 — 합산이 아니라 KOMIS가
   이미 국가 단위로 준 값 그대로라 집계범위 논쟁이 없다.
2. **바차트의 마지막 연도는 항상 연중 진행분이다.** 실측 확인: 2026년
   값이 2025년의 약 1/9(118M 대 1,081M)로 급감 — 명백한 연중 미완결
   패턴. `srchDateChartS`/`srchDateChartE`가 조회 대상 연도와 무관하게
   항상 "최근 ~13개년~현재" 고정 폭으로 온다는 것도 확인해(list_data가
   2017년을 조회해도 바차트는 2014~2026을 그대로 줌), "마지막 xaxis
   연도는 항상 제외"라는 규칙을 조회 연도와 무관하게 안전하게 적용할 수
   있다고 판단했다.
3. **`getListMapNationData`의 `crtrNtnAmtRt`/`trgtNtnAmtRt` 의미를 교차곱
   검증으로 확정했다.** 같은 루트에서 crtrTotalAmt×crtrNtnAmtRt ≈
   trgtTotalAmt×trgtNtnAmtRt(반올림 오차 내로 동일 값에 수렴 — 예:
   중국→일본 루트에서 35,621,452 대 35,621,336). 즉 "이 루트가 각국
   자신의 집계총액에서 차지하는 비중"임을 확정. 단 그 집계총액이
   수출·수입 중 어느 방향인지까지는 검증하지 못해 라벨은 방향중립
   ("{국가}측 집계총액 대비")으로 뒀다.

## 구현
### 신규 필드 (models.py / routers/analysis.py, page_id=map_global 전용)
- `komis_bar_chart_response: dict | None` — `getBarChartDataNation` 원본.
- `komis_route_share_response: dict | None` — `getListMapNationData` 원본.

### 파서 (summary.py)
- `_parse_komis_map_global_bar_chart_top_country(raw)` → `(1위국명,
  {연도: 값})` — 마지막 xaxis 연도를 항상 제외하고, 남은 연도 중 최신
  연도 기준 1위국을 골라 그 국가만의 시계열을 반환.
- `_parse_komis_map_global_route_shares(raw)` → 루트별
  `[{origin_name, dest_name, origin_share_percent, dest_share_percent}]`.
- `_analyze_global_trade`가 둘 다 선택적으로 파싱해
  `calculate_global_trade_summary`에 전달(독립적 — 하나만 보내도 동작).

### 서사 반영 (komir_summary.py::calculate_global_trade_summary)
- `top_country_yearly_trend`/`route_shares` 2개 신규 파라미터.
- `current_position`: 기존 `len(dates)>=2`(list_data가 스냅샷 1건뿐이라
  실전에서 거의 항상 미발동) 분기는 그대로 두고, 새 `elif
  top_country_yearly_trend` 분기를 추가 — "KOMIS 차트 기준 {국가}의
  {연도}년 교역액은 {전년}년 대비 X% 변동했다"(claim id
  `country_yearly_trend`). "세계 교역 총액"이 아니라 특정 1개국 수치임을
  문장에 명시해 오해를 막는다.
- `route_shares`는 서사 claim이 아니라 detailed_metrics로만 반영(상위
  5개 루트, 각 루트당 origin/dest 2개씩 최대 10개 — map_mineral의
  `market_share` 선례와 동일 원칙, 방향까지 검증 못 한 숫자를 확정적
  서사 문장에 넣지 않는다).
- `MAP_GLOBAL_SUMMARY_INSTRUCTIONS`에 `country_yearly_trend` claim
  설명을 추가(3개 claim이 상호배타임을 명시) — **output_contract
  변경이라 이번 배포는 seed_prompts 재실행 필요.**

## 검증
- 실측 기반 테스트(`komis_07_supply_map_global.json`의 실제 매칭 3종
  조합, 갈륨/MNRL0024/2017년/수입) — `AnalysisSummaryService(llm=None)
  .analyze()` 직접 호출 4가지 조합:
  - 기존(komis_response만): 기존과 동일한 랭킹·한국순위 문장, current_
    position은 여전히 "관측일 1건뿐" — 회귀 없음.
  - +bar_chart: "KOMIS 차트 기준 미국의 2025년 교역액은 2024년 대비
    -48.55% 변동했다" — 2026(진행중) 연도가 올바르게 제외되고 2025 대
    2024로 비교됨 확인.
  - +route_share: 상위 5개 루트 × 2방향 = 10개 detailed_metrics 정상
    생성, 라벨에 방향중립 문구 확인.
  - 둘 다: 독립적으로 동시에 반영됨 확인.
- 회귀 395콤보(`scripts/komis_dump_smoke_test.py`) mismatch 0 유지(기존
  덤프엔 새 필드가 없어 no-op).

## 미반영/후속
- `route_shares`의 한국 루트 하이라이트(`korea_route_rank`) 연동은
  실재하는 확장이지만 이번 사이클 범위 밖(advisor 권고, 별도 사이클).
- `crtrNtnAmtRt`/`trgtNtnAmtRt`의 수출/수입 방향성은 미검증 — 필요시
  후속 검증 대상.

## 커밋
`app/analysis/models.py`·`app/analysis/summary.py`·
`app/analysis/komir_summary.py`·`app/analysis/prompts.py`·
`app/routers/analysis.py` — main-agent 승인 후 재빌드·재기동
(**seed_prompts 재실행 필요**).
