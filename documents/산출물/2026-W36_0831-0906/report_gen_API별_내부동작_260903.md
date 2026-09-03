# report_gen — API 단위별 내부 동작

> `forecast_price`(가격예측)는 작업 대상이 아니라 아래 9개 어디에도 포함하지 않는다.
>
> 대상: `inhouse/services/report_gen/`. 전체 파이프라인 개요(요청→계산→LLM 정제→
> 렌더링 공통 흐름, 안전장치, 프롬프트/DB 계약)는 이미
> [`report_gen_아키텍처_처리흐름_260901.md`](./report_gen_아키텍처_처리흐름_260901.md)
> 에 정리돼 있다 — 이 문서는 그걸 대체하지 않고, **API(page_id) 단위로 내부 동작을
> 더 상세히** 파고든다. §2는 그 문서의 요약이니 전체 흐름이 궁금하면 그쪽을 먼저 볼 것.
>
> 작성일: 2026-09-03. 코드 기준 확인 완료(`app/routers/analysis.py`·`analysis/
> komir_summary.py`·`analysis/additional_summary.py`·`analysis/prompts.py`·
> `analysis/policy.py`·`analysis/store.py` 직접 재확인).

## 1. 이 문서가 다루는 9개 page_id

`app/routers/analysis.py`에 실제 등록된 경로 순서 그대로 다룬다(KOMIS 메뉴상
"광물전망지표"·"광물자원가격"·"핵심광물지도" 세 그룹에 속하며, 그룹 내 순서는
코드의 물리적 배치를 따름):

| # | page_id | 엔드포인트 | 그룹 |
|---|---|---|---|
| 1 | `indicator_market` | `POST /api/v1/analysis/indicators/market` | 광물전망지표 |
| 2 | `indicator_supply` | `POST /api/v1/analysis/indicators/supply` | 광물전망지표 |
| 3 | `indicator_composite` | `POST /api/v1/analysis/indicators/composite-index` | 광물전망지표 |
| 4 | `map_mineral` | `POST /api/v1/analysis/maps/mineral` | 핵심광물지도 |
| 5 | `price_base_metals` | `POST /api/v1/analysis/prices/base-metals` | 광물자원가격 |
| 6 | `price_minor_metals` | `POST /api/v1/analysis/prices/minor-metals` | 광물자원가격 |
| 7 | `price_iron_energy` | `POST /api/v1/analysis/prices/iron-energy` | 광물자원가격 |
| 8 | `price_other` | `POST /api/v1/analysis/prices/other` | 광물자원가격 |
| 9 | `map_korea` | `POST /api/v1/analysis/maps/domestic-trade` | 핵심광물지도(수급지도-국내) |
| 10 | `map_global` | `POST /api/v1/analysis/maps/global-trade` | 핵심광물지도(수급지도-해외) |

(표가 10행인 건 실수가 아니라 `map_korea`/`map_global`을 별도 행으로 세어서다 —
정확히 9개 page_id 맞다.)

모든 엔드포인트는 응답 모델이 `AnalysisReportResponse({status, report})` 하나로
통일돼 있고, HTTP 상태 코드는 항상 200이다(성공/실패는 `status` 필드로만 구분 —
`"ok"`/`"NO_DATA"`/`"TIMEOUT"`/`"INTERNAL_ERROR"`). 이 계약과 공통 실행기
(`run_summary`, Semaphore(8), 20초 예산)는 9개 전부 동일해서 여기서는 반복하지
않는다 — §2 참고.

## 2. 공통 처리 구조(요약)

```
Client → routers/analysis.py(엔드포인트) → run_summary(routers/_common.py)
  → AnalysisSummaryService._dispatch(analysis/summary.py) → page_id별 _analyze_*()
  → calculate_*_summary(komir_summary.py 또는 additional_summary.py) — 결정론적 계산
  → _refine_with_llm(summary.py) — ai_cfg.cfg_prompt 지시문으로 LLM 정제 + 검증(최대 2회)
  → render_markdown_report(report_render.py) → {status, report}
```

이 서비스는 **자체 DB를 조회하지 않는다** — 계산에 쓰는 원자료는 전부 요청
바디로 받는다. 두 입력 경로가 있고 page_id마다 어느 쪽을 지원하는지 다르다(§3
각 절에 명시):

1. **가공된 observations** — komir 자체 스키마(`IndicatorObservation` 등)로
   손 매핑한 배열.
2. **KOMIS AJAX 원본 JSON passthrough**(`komis_response` 등) — KOMIS 사이트가
   실제로 돌려주는 응답을 그대로 담으면 서버가 직접 파싱한다. 9개 전부
   이 경로를 지원하며, 최신 요청 스키마는 대체로 이쪽을 기본으로 하고
   손 매핑 필드는 하위호환으로만 남아 있거나(또는 완전히 제거됐다 —
   각 절 참고).

등급 판정 정책: **`indicator_market`·`indicator_supply` 2개만** YAML
등급 밴드(`resources/policies/*.yaml`)를 쓴다. 나머지 7개(`indicator_composite`
포함)는 등급 개념 자체가 없다 — `policy.py` 모듈 docstring이 명시하는 원칙이다.

## 3. page_id별 내부 동작

### 3-1. `indicator_market` — 시장동향지표

**요청 스키마**(`IndicatorSummaryRequest`): `mineral`(필수, 코드) · `mineral_name`
(선택) · `start_month`/`end_month`(선택 기간필터) · `observations`(손 매핑,
`IndicatorObservation` 리스트) · `komis_response`(2026-09-01 신설, KOMIS
`getListIndxMnrk` 원본 — `{"data": [...], "chartData": {...}}`, `chartData`는
`data`와 동일값의 그래프용 재구성이라 안 씀) · `price_unit`/`price_criterion`/
`unavailable_page_data`(선택). 이 페이지는 KOMIS 로그인 필요 화면이라 정적
데이터 예시가 오래 없었고, `observations` 손 매핑만 지원하다가 09-01에
`komis_response` 경로가 추가됐다. `mineral`은 응답 본문에 코드가 없어 여전히
필수.

**등급 정책**(`resources/policies/indicator_market.yaml`, `policy_version:
"2026-07-16"`): 0~100점, 5단계 균등구간 — **신중(0~20)·주의(20~40)·중립(40~60)·
관심(60~80)·기회(80~100)**. "점수가 높을수록 중장기 가격위험이 낮다."

**결정론적 계산**(`summary.py::_calculate_summary`, market/supply 공용):
- `core_diagnosis`: `"{월} {광종} {지표명}는 {점수}점으로 {단계} 단계다."`
  (전월 대비 점수변화 있으면 이어붙임)
- `major_changes`: 등급 유지/전환 연속개월수, 조회기간 중 최대 월간변동폭
- `current_position`: 조회기간 평균 대비 현재 위치
- **"주요 요인" 절 자체가 없다** — PDF는 "가격변동지수 확대 견인"/"투자환경지수
  변동성 확대" 원인 분해를 요구하지만 계산 로직에 그 근거가 없어
  `MARKET_SUMMARY_INSTRUCTIONS`가 "만들지 않는다"고 명시 지시.

**실측 예시**: 로그인 필요 페이지라 실측 캡처 없음(코드상 템플릿만 확인).

### 3-2. `indicator_supply` — 수급동향지표

**요청 스키마**(`SupplyIndicatorSummaryRequest`, `IndicatorSummaryRequest` 상속):
`mineral`은 선택으로 재선언(`komis_snapshot_response`가 있으면 자동 채움).
`komis_snapshot_response`(`getChartDataSpdmStbt`)가 있으면 `subChart02`(수입량·
수입액 5개년)→`domestic_imports`, `subChart03`(국가별 수입금액 비중)→
`import_dependencies`를 자동 파싱한다. `subChart04`(국가별 생산량)·`subChart07`
(국가별 매장량)은 대응 필드가 없어 미반영. 손 매핑 `supply_auxiliary`는
`komis_snapshot_response`가 없을 때의 폴백.

**등급 정책**(`resources/policies/indicator_supply.yaml`, `policy_version:
"2026-09-01"`): 0~100점, 5단계 균등구간 — **긴장(0~20)·주의(20~40)·관심(40~60)·
안정(60~80)·원활(80~100)**. "점수가 높을수록 수급 안정성이 강함." **2026-09-01
발주처 확인으로 확정된 값**(이전 4단계 비균등구간 — 주의 1~5·관심 5~20·안정
20~80·원활 80~100 — 을 대체, [[report_gen_supply_5grade_260901]] 참고). market과
계산 함수(`_calculate_summary`)를 공유하되 등급 라벨·구간만 다르다.

**결정론적 계산**: market과 동일한 `_calculate_summary` 흐름 + 수급 보조패널
(`_supply_auxiliary_metrics`)로 수입의존도·상위3국 비중 등을 추가 지표로 얹는다.

**실측 예시**: 로그인 필요 페이지라 실측 캡처 없음.

### 3-3. `indicator_composite` — 광물종합지수

**요청 스키마**(`CompositeIndexSummaryRequest`): `komis_response`(선택, 사실상
유일한 입력 — `getLineChartIndx` 원본을 담으면 광물종합·메이저·희소 3개 지수
시계열을 직접 파싱). mineral 개념 자체가 없는 유일한 페이지.

**등급 정책**: 없음(`policy.py` 명시).

**결정론적 계산**(`additional_summary.py::calculate_composite_summary`):
- `core_diagnosis`: `"{일자} 광물종합지수는 {포인트}포인트다."` (1년 전 비교값
  있으면 "최근 한 달에는 {상승/하락/보합}했지만 1년 전보다 {비율}% {높은/낮은}
  수준" 추가)
- `major_changes`: 전주·전월 대비 변화 + 메이저/희소 하위지수 비교(같은 방향이면
  "반면" 대신 순접)
- `current_position`: 조회기간 최고·최저 대비 현재 위치, 하위지수 1년 변화 방향
  불일치 시 명시
- **"변동 이슈"·"주요 원인 광종" 없음** — PDF는 견인 광종을 요구하지만 evidence에
  없어 추정 금지 원칙상 서술하지 않는다.

**실측 예시**(`getLineChartIndx` 라이브 캡처, `report_gen_KOMIS라이브재검증_
Phase4_260829_evidence/composite_forecast_live_capture_260829.json`):

```
## 주요 변화
광물종합지수는 전주 대비 1.78% 상승하며 한 달 전보다 3.89% 올랐으며,
메이저금속지수와 희소금속지수 모두 전주와 전월 대비 상승세를 나타냈습니다.

## 현재 위치
현재 광물종합지수는 조회기간 내 최저치인 2,616.06포인트보다 36.04% 높은
수준이지만, 최고치인 3,682.58포인트보다는 3.36% 낮은 위치에 있습니다.
```

### 3-4. `map_mineral` — 광물지도(매장량/생산량)

**요청 스키마**(`MineralMapSummaryRequest`): `mineral`(필수, 코드)·`measure`
(필수, `reserves`|`production` — 응답 본문엔 둘 다 오지만 어느 걸 물었는지는
파라미터로만 구분 가능)·`unit`(선택, 자동채움 폴백)·`komis_response`
(`getListMapMnrlChartData`, observations+unit 직접 파싱)·
`komis_snapshot_response`(`getListMapMnrlData`, 매장량/생산량 교차비교 — 단일
연도 조회 전제)·`komis_share_response`(`getListMnrlTablePrdctnBurgudg`, 국가별
KOMIS 공식 비중).

**등급 정책**: 없음.

**결정론적 계산**(`additional_summary.py::calculate_mineral_map_summary`):
- 연도 그룹화(`_by_year`) 후 시작연도·최종연도 세계총량(`_world_total`, 공식
  총계 행이 있으면 그 값, 없으면 국가별 합산) 비교
- `core_diagnosis`: `"{연도}년 세계 {광종} {매장량/생산량}은 {값}{단위}다."` +
  기간 전체 증감 + 직전연도 대비 증감(있으면)
- `major_changes`(`current_leaders`/`third_country`): 1~3위 국가 값·비중·순위차
- `current_position`: 국가별 기간 변화(순위 이동 포함, 최대 2개국) + CR3/CR5
  집중도 변화
- `secondary_series`(반대 measure, 있으면): 매장량↔생산량 교차비교 근거 1건
  추가(예: "매장량 2위 호주는 생산량 8위")
- `market_share`(KOMIS 공식 비중표, 있으면): 서사 문장이 아니라
  `detailed_metrics`(표)로만 추가 — 이 값의 분모(표에 나열된 국가들의 소계)가
  `series` 세계합계와 체계적으로 다르다는 걸 실측 확인해 같은 이름("세계비중")
  으로 중복 노출하지 않는다.

**실측 예시**: 없음(코드 확인만, 라이브 캡처 미실시).

### 3-5~3-8. `price_base_metals`·`price_minor_metals`·`price_iron_energy`·`price_other` — 광물자원가격 4종

4개 page_id가 요청 스키마·계산 함수를 완전히 공유한다(`PriceSummaryRequest` +
`komir_summary.py::calculate_price_summary`) — 페이지 이름·정의·정책버전만
`KOMIR_PAGE_CONTEXTS`에서 갈린다.

**요청 스키마**(`PriceSummaryRequest`): `mineral`(필수, 코드 — 응답에
`mnrkndKornNm` 한글명만 있어 자동채움 불가)·`mineral_name`(자동채움+오버라이드)·
`compare_mineral`/`compare_mineral_name`/`compare_price_criterion`(비교광종,
4종 전부 지원 — 희소금속 전용 아님)·`price_criterion`(가격기준, 예: "LME
CASH")·`srch_avg_opt`/`srch_field`/`srch_start_date`/`srch_end_date`(호출자가
KOMIS에 던진 조회 파라미터 그대로 — 응답 본문엔 없는 정보라 관측치 간격
추론보다 우선)·`komis_response`(`getMnrlPrcByMnrkndUnqCd` 원본, 일별 시세·재고·
전주/전월/전년 비교·가격기준까지 전부 여기서 직접 파싱).

**등급 정책**: 없음(4종 모두 `analysis_constraints`만: 제공된 계열·기간만 사용,
외부사건 원인 추정 금지, 단위 없으면 절대수준 해석 금지).

**결정론적 계산**(`calculate_price_summary`, 4종 공유):
- `core_diagnosis`: 최신 실거래가
- `major_changes`: 전일(정확히 1일 간격일 때만) 또는 직전 관측치 대비 등락 +
  전주/전월/전년평균 대비(조회기간이 각 창의 60% 미만이면 계산 안 함, 이미
  같은 관측일 집합으로 중복되는 기간은 dedup) + 연속 추세(N일/주/개월 연속
  상승/하락/보합) + 조회기간 시작 대비 전체 변화 + `geo_events` 있으면 severity
  상위 2건까지 가격변동 요인(방향 통제어휘 + 품질검증 통과한 원문 인용, 최대
  major_changes 5문장 상한 안에서)
- `current_position`: 조회기간 최고·최저(hilo 커버리지 완전하면 그 값, 아니면
  실거래가 기준 폴백 — 둘 다 0.00을 결측으로 취급) + 비교광종 있으면 전체
  변화율 비교 + **2026-08-31 통계확장 6개 층**(각각 관측치 요건 미달 시
  계산 안 하고 `insufficient_history` 문장 1개로 합쳐 안내): 변동성, 이동평균
  +RSI(최소 20/15건), 백분위 위치(최소 20건), 낙폭 국면(최소 2건), 재고 해석
  (재고 있는 관측 최소 10건), 상대가치(비교광종 있을 때, 같은 날짜 20건)
- 표 전용 2개 층(문장 아닌 `detailed_metrics`): 연도별 수익률, 계절성(월별
  평균수익률 — 표본 2개 연도 미만이면 경고)
- 재고량 필드는 0.00을 KOMIS의 "미제공" 관행으로 보고 결측 취급(LME 6대
  비철금속 외 광종은 `invt`가 항상 0.00으로 채워져 옴, 실측 16개 콤보 확인)

**page_id별 정의문**(`KOMIR_PAGE_CONTEXTS`):
- `price_base_metals`: "선택한 비철금속(LME 기준)의 일별 실거래가 추이를
  보여주는 자료다." — 최고가·최저가는 정의문에서 뺐다(LME 6대 비철금속 DAY
  계열은 최고=최저=실거래가로 채워져 정보량 0이라는 실측 근거).
- `price_minor_metals`: "…일별 실거래가·최저가·최고가 추이…" (희소금속은
  hilo 결함 없음 확인됨).
- `price_iron_energy`: "…철광석·유연탄·우라늄(품목 기준)의 일별 실거래가·
  최저가·최고가…" — 원천 덤프 미확보라 hilo 결함 여부 미검증(price_base_metals
  수정을 재확인 없이 옮기지 않음).
- `price_other`: "…금·은·백금족·흑연(기준시장 기준)의…" — 마찬가지로 미검증.

**실측 예시**: 없음(코드 확인만).

### 3-9. `map_korea` — 국내 수급지도

**요청 스키마**(`DomesticTradeSummaryRequest`, `_DateRangeMineralRequest` 상속):
`mineral`/`mineral_name`(선택, `komis_response`가 조회 파라미터를 그대로
echo해 자동채움 가능)·`komis_response`(`getListKoreaData` 원본, 국가별 수입/
수출·총액 직접 파싱)·`trade_direction`("import"|"export", 응답 자체엔 방향이
안 드러나 호출자가 명시 필수)·`mttr_flow_name`(생산품유형 라벨, 코드만 echo되고
한글라벨이 없어 선택 passthrough). 조회필터(기간구분·국가·생산품유형·HS코드)는
`komis_response` 최상위 echo 필드에서 다 읽는다.

**등급 정책**: 없음.

**결정론적 계산**(`komir_summary.py::calculate_domestic_trade_summary`):
- `komis_totals`(응답에 동봉된 `sumIncmAmt`/`sumExpAmt`)가 있으면 그 값을 총액으로
  쓴다 — KOMIS `list` 응답이 최대 30개 국가까지만 줘서(실측 145콤보 중 9건
  영향, 최악 5.8% 과소) 관측치 합산보다 정확
- 단일 국가로 조회 한정(`country_filter_name`)되면 랭킹 근거를 만들지 않고
  "{국가} 대상 총액은 X다" 단문으로 대체(비중이 항상 100%로 공허해지는 문제
  회피)
- `scope_label`(생산품유형/HS코드로 범위만 좁힘, 국가는 여러 개)이 있으면
  "전체의"를 "이 범위 내"로 바꿔 명시
- `core_diagnosis`: 기준일·광종·{한정어}·{수입/수출}총액
- `major_changes`: 1위국(top1)·상위3국(CR3, 5.8%↑↓ 실측 반영)·상위5국(CR5)
- `current_position`: 직전 관측일 대비 총액 변동(관측 1건뿐이면 그 사실만 명시)

**실측 예시**: 없음(코드 확인만).

### 3-10. `map_global` — 글로벌 수급지도

**요청 스키마**(`GlobalTradeSummaryRequest`, `_DateRangeMineralRequest` 상속):
`mineral`/`mineral_name`(자동채움 가능)·`komis_response`(`getListDataNation`
원본, 원산국→도착국 루트별 교역량·총액)·`komis_bar_chart_response`
(`getBarChartDataNation`, 국가별 다년 시계열 — list_data가 스냅샷 1건뿐이라
period_total_change가 거의 발동 안 하는 걸 보완)·`komis_route_share_response`
(`getListMapNationData`, 루트별 각국 집계총액 대비 비중).

**등급 정책**: 없음.

**결정론적 계산**(`komir_summary.py::calculate_global_trade_summary`):
- `komis_totals`(응답의 `sumAmt`)가 있으면 우선 사용 — `list` 응답의 30개 루트
  상한 영향이 map_korea보다 훨씬 심각(실측 73콤보 중 72건/99% 영향, 중앙값
  30.6%·최악 69.4% 과소)
- `core_diagnosis`: 기준일·광종·세계 교역 총액
- `major_changes`: 1~3위 루트(원산국→도착국 화살표 표기) + CR3 + CR5 +
  대한민국이 등장하는 루트의 순위 하이라이트(원산지/도착지 어느 쪽이든,
  최대 2건 — 이미 랭킹에 있으면 "위 랭킹 참조"로 숫자 중복 안 함, 없으면 없음
  사실 명시)
- `current_position`: 직전 관측일 대비 총액 변동 → 없으면(스냅샷 1건뿐)
  바차트 1위국 자체의 연도별 변동(**"세계 교역 총액"이 아니라 그 국가 자신의
  수치** — list_data의 `sumAmt`와 bar 합계가 서로 다른 집계범위임을 실측
  확인, 30%대 격차) → 그것도 없으면 "관측 1건뿐" 명시
- `route_shares`(있으면): 서사 문장이 아니라 `detailed_metrics`로만(방향 —
  수출/수입 — 은 검증 못해 라벨 중립)

**실측 예시**: 없음(코드 확인만).

## 4. 코드 확인 중 발견한 참고 사항(수정 아님, 기록만)

- `analysis/store.py`(`out_report` 적재)는 **현재 미사용 죽은 코드**다 — 2026-08-19
  도입 후 2026-08-26 사용자 지시로 `routers/_common.py::run_summary`가
  `analyze_and_store()`가 아닌 `service.analyze()`만 부르도록 바뀌었다(파일
  자체는 복원 가능하도록 삭제하지 않음, `report_gen_아키텍처_처리흐름_260901.md`
  §5에도 같은 내용). `store.py::_PAGE_TITLES`의 `"price"` 키도 2026-08-27
  `/prices` 분리 이전 표기라 지금의 4개 `price_*` page_id와 안 맞는데, 죽은
  코드라 실제 응답에 영향은 없다.
- `price_iron_energy`/`price_other`는 `price_base_metals`에서 발견된 최고/최저가
  결함(LME 6대 비철금속 DAY 계열의 hilo=실거래가 동일값 문제)이 있는지 원천
  덤프가 없어 아직 미검증 상태로 남아있다(정의문에 "최저가·최고가" 표현 유지 —
  검증 전까지 임의로 빼지 않은 게 의도된 판단).
