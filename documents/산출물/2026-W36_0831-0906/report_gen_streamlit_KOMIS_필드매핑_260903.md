# report_gen × streamlit_demo — KOMIS 응답 필드 매핑 가이드

> 목적: streamlit_demo에서 report_gen API를 호출하려면 (1) KOMIS 사이트에서 어떤
> AJAX 엔드포인트의 응답을 받아와야 하는지, (2) 그 응답을 어떤 요청 필드에 담아야
> 하는지, (3) report_gen이 그 응답의 어떤 원본 필드를 읽어 어떤 내부 필드로
> 쓰는지를 페이지(page_id)별로 정리한다. 파이프라인 전체 흐름·계산 로직·프롬프트
> 계약은 다루지 않는다 — 그건 이미
> [`report_gen_아키텍처_처리흐름_260901.md`](./report_gen_아키텍처_처리흐름_260901.md)와
> [`report_gen_API별_내부동작_260903.md`](./report_gen_API별_내부동작_260903.md)가
> 다룬다(이 문서는 그 두 문서를 보완하는 "필드 룩업 표"다).
>
> 작성일: 2026-09-03. 코드 기준 확인(`app/routers/analysis.py`·`analysis/models.py`·
> `analysis/summary.py`·`streamlit_demo/komis_raw.py`·`streamlit_demo/
> report_gen_client.py` 직접 재확인, main `d064b4d3d` 반영 후).

## 0. 공통 계약

- **응답**: 모든 엔드포인트가 HTTP 200 고정 + `{"status": "ok"|"NO_DATA"|"TIMEOUT"|
  "INTERNAL_ERROR", "report": "<Markdown|null>"}`. 실패도 200이라 `status` 필드로만
  분기해야 한다.
- **streamlit_demo 연동 방식**: `streamlit_demo/komis_raw.py`가 표준 경로다 — 사람이
  브라우저 개발자도구·curl 등으로 KOMIS를 직접 조회해 얻은 원본 JSON을 화면에
  그대로 붙여넣으면, `KOMIS_RAW_PAGES[page_id].convert(raw, ctx)`
  (`passthrough_*` 함수)가 "구조가 맞는지" 얕은 검증만 하고 report_gen 요청 필드로
  그대로 실어 보낸다 — **필드명 손 매핑은 하지 않는다**(파싱은 전부 report_gen
  서버 쪽 `_parse_komis_*` 함수가 한다). 11개 page_id 전부 이 패턴을 쓴다.
- **`report_gen_client.py`의 `PAGE_SPECS`**(`observations` 손입력 예시)는 komis_response
  도입 이전 시절 유물이라 지금은 스키마 참고용일 뿐, 실제 화면은 `komis_raw.py`의
  붙여넣기 UI가 정본이다.
- **KOMIS 원본은 로그인·세션 쿠키가 필요한 AJAX**라 이 sandbox/컨테이너에서 직접
  호출할 수 없다 — 그래서 "사람이 브라우저에서 떠서 붙여넣기" 방식이다.
- `forecast_price`(가격예측)는 백엔드 라우터·파서·streamlit_demo의
  `passthrough_forecast_price`/`KOMIS_RAW_PAGES` 항목이 전부 살아있지만,
  **2026-09-01 사용자 지시로 streamlit 메뉴(드롭다운)에서는 제거**됐다 — API 자체는
  유효하나 데모 화면에는 안 뜬다. 참고용으로 §12에 남긴다.
- `price_group`은 2026-08-31 report_gen 외부 인터페이스 자체가 삭제돼(내부 로직은
  보존) 이 문서·streamlit_demo 양쪽 다 대상이 아니다.

## 1. 페이지 목록(11 + 부록 1)

| # | page_id | 엔드포인트 | KOMIS API(필수) | KOMIS API(선택) |
|---|---|---|---|---|
| 1 | `indicator_market` | `POST /api/v1/analysis/indicators/market` | `getListIndxMnrk` | — |
| 2 | `indicator_supply` | `POST /api/v1/analysis/indicators/supply` | `getListIndxSplyBalncMnrk` | `getChartDataSpdmStbt` |
| 3 | `indicator_composite` | `POST /api/v1/analysis/indicators/composite-index` | `getLineChartIndx` | — |
| 4 | `map_mineral` | `POST /api/v1/analysis/maps/mineral` | `getListMapMnrlChartData` | `getListMapMnrlData`·`getListMnrlTablePrdctnBurgudg` |
| 5 | `price_base_metals` | `POST /api/v1/analysis/prices/base-metals` | `getMnrlPrcByMnrkndUnqCd` | — |
| 6 | `price_minor_metals` | `POST /api/v1/analysis/prices/minor-metals` | `getMnrlPrcByMnrkndUnqCd` | — |
| 7 | `price_iron_energy` | `POST /api/v1/analysis/prices/iron-energy` | `getMnrlPrcByMnrkndUnqCd` | — |
| 8 | `price_other` | `POST /api/v1/analysis/prices/other` | `getMnrlPrcByMnrkndUnqCd` | — |
| 9 | `map_korea` | `POST /api/v1/analysis/maps/domestic-trade` | `getListKoreaData` | — |
| 10 | `map_global` | `POST /api/v1/analysis/maps/global-trade` | `getListDataNation` | `getBarChartDataNation`·`getListMapNationData` |
| (부록) | `forecast_price` | `POST /api/v1/analysis/indicators/price-forecast` | `getListPricePredc` | — (streamlit 메뉴 제외) |

`map_mineral`·`price_*` 4종은 KOMIS 응답 본문에 광종 식별자가 없어(있어도 `mnrkndKornNm`
한글명뿐) `mineral`(코드)을 항상 별도로 명시해야 한다 — 자동채움 불가(§report_gen_
komis_response_필드_최종감사_260831.md에서 실측 확인된 결론).

---

## 2. `indicator_market` — 시장동향지표

- **streamlit_demo**: `komis_raw.py::passthrough_indicator_market`
- **붙여넣는 JSON**: `getListIndxMnrk` 원본 그대로(envelope 없음).
- **필수 광종코드**: `mineral`(드롭다운, 응답 본문에 식별자 없음).
- **Request 모델**: `IndicatorSummaryRequest` — `mineral`(필수)·`mineral_name`(선택)·
  `start_month`/`end_month`(선택 기간필터)·`komis_response`(dict)·`observations`
  (손입력 하위호환).

| KOMIS 원본 필드 | 경로 | 내부 필드 | 비고 |
|---|---|---|---|
| `data[]` | 최상위 | (관측치 배열) | `chartData`는 `data`의 그래프용 재구성이라 안 읽음 |
| `crtrYmd` | `data[i]` | `month`("YYYY-MM") | 8자리 YYYYMMDD 앞 6자리만 사용 |
| `mrktPrspectIdct` | `data[i]` | `score` | |
| `realPrc` | `data[i]` | `price` | |
| `crisisYn`("Y"/"N") | `data[i]` | `crisis_flag` | 이 API 응답엔 실제로 없는 필드 |

비고: KOMIS는 내림차순(최신월 먼저) 제공 — 서버가 오름차순 재정렬 + **월별 dedup**
(같은 달에 `crtrYmd`가 2회 오면 그 달의 최신 `crtrYmd`만 남김, 2026-09-02 skeptic
감사 SC-R2-006 대응, 방어적 조치).

---

## 3. `indicator_supply` — 수급동향지표

- **streamlit_demo**: `komis_raw.py::passthrough_indicator_supply`
- **붙여넣는 JSON(envelope)**:
  ```json
  {"komis_response": <getListIndxSplyBalncMnrk 원본, 필수>,
   "komis_snapshot_response": <getChartDataSpdmStbt 원본, 선택>}
  ```
  envelope 없이 `getListIndxSplyBalncMnrk` 원본만 붙여넣어도(구버전 호환) `komis_snapshot_response`
  없이 그대로 동작한다.
- **광종코드**: `mineral` 선택 — `komis_snapshot_response`가 있으면 그 안에서 자동채움,
  없으면 드롭다운 값을 그대로 보내야 한다(**드롭다운 값이 항상 우선** — `request.mineral
  or snapshot 파생값` 순서, 드롭다운·붙여넣은 JSON의 광종이 다르면 광종명과 수치가
  섞여 나올 수 있으니 주의).
- **Request 모델**: `SupplyIndicatorSummaryRequest(IndicatorSummaryRequest)` —
  `mineral`(선택)·`komis_response`·`komis_snapshot_response`·`supply_auxiliary`
  (손입력 폴백, snapshot 없을 때만 씀).

**`komis_response`(`getListIndxSplyBalncMnrk`) 필드 매핑**:

| KOMIS 원본 필드 | 경로 | 내부 필드 | 비고 |
|---|---|---|---|
| `data[]` | 최상위 | (관측치 배열) | market과 같은 공용 파서 사용(6자리 YYYYMM도 지원) |
| `crtrYmd` | `data[i]` | `month` | 6자리(YYYYMM) 또는 8자리 둘 다 허용 |
| `spdmStbtIndx` | `data[i]` | `score` | |
| `realPrc` | `data[i]` | `price` | |

**`komis_snapshot_response`(`getChartDataSpdmStbt`) 필드 매핑** — "주요 요인" 문단용,
이게 있어야 §3-2 문단이 채워짐:

| KOMIS 원본 필드 | 경로 | 내부 필드 | 비고 |
|---|---|---|---|
| `data`(envelope, dict면) | 최상위 | (언랩) | 봉투 없이 바로 와도 허용 |
| `chartSpdmStbt.mnrkndUnqCd` | `data.chartSpdmStbt` | `mineral`(자동채움) | `request.mineral`이 없을 때만 |
| `chartSpdmStbt.mnrkndKornNm` | `data.chartSpdmStbt` | `mineral_name`(자동채움) | |
| `subChart02.labels[]`(연도) | `data.subChart02` | `domestic_imports[].year` | |
| `subChart02.series[name="수입량"].data[]` | 〃 | `domestic_imports[].import_weight_ton` | |
| `subChart02.series[name="수입액"].data[]` | 〃 | `domestic_imports[].import_amount_million_usd` | |
| `subChart03.crtrYr` | `data.subChart03` | `import_dependencies[].year` | |
| `subChart03.labels[]`(국가명) | 〃 | `import_dependencies[].country_name` | |
| `subChart03.series[]`(금액USD) | 〃 | `import_dependencies[].amount_usd` | 필드 하나뿐, 중량(kg)은 이 응답에 없음 |
| — (계산값) | — | `import_dependencies[].share_percent` | 나열국 합계 대비 비중(세계총액 아님) |
| — (계산값) | — | `top_three_dependency_percent` | 상위 3개국 share_percent 합, `min(100.0,...)` clamp 적용 |

미파싱: `subChart01`(실질가격, `realPrc`와 중복) · `subChart04`(국가별 생산량,
"세계 공급 편중도") · `subChart07`(국가별 매장량) — 대응 내부 필드 자체가 없음.

---

## 4. `indicator_composite` — 광물종합지수

- **streamlit_demo**: `komis_raw.py::passthrough_indicator_composite`
- **붙여넣는 JSON**: `getLineChartIndx` 원본 그대로(envelope 없음, `data`가 dict면
  언랩·아니면 그대로 — 봉투 있는 형태·없는 형태 둘 다 허용).
- **광종코드**: 없음 — `indicator_composite`는 mineral 개념 자체가 없는 유일한 페이지.
- **Request 모델**: `CompositeIndexSummaryRequest` — `komis_response`(사실상 유일한
  입력 필드).

| KOMIS 원본 필드 | 경로 | 내부 필드 | 비고 |
|---|---|---|---|
| `tableData[]` | (언랩된) `data` | (날짜별 관측치) | `xaxis`/`series`(그래프용)는 안 읽음, `tableData`만 |
| `crtrYmd`("YYYY.MM.DD") | `tableData[i]` | `date`(점→하이픈) | |
| `indxTp="MNRL"`+`indx` | `tableData[i]` | `composite_index` | 같은 `crtrYmd`끼리 묶어 하나의 관측치로 합성 |
| `indxTp="MAJOR"`+`indx` | 〃 | `major_metals_index` | |
| `indxTp="RARE"`+`indx` | 〃 | `minor_metals_index` | 3종 중 하나라도 없는 날짜는 스킵 |

---

## 5. `map_mineral` — 광물지도(매장량/생산량)

- **streamlit_demo**: `komis_raw.py::passthrough_map_mineral`
- **붙여넣는 JSON(envelope)**:
  ```json
  {"chart": <getListMapMnrlChartData 원본, 필수>,
   "snapshot": <getListMapMnrlData 원본, 선택>,
   "share": <getListMnrlTablePrdctnBurgudg 원본, 선택>}
  ```
- **필수 파라미터**: `mineral`(코드)·`measure`("reserves"|"production") — 둘 다 응답
  본문만으로는 구분 불가(매장량 조회든 생산량 조회든 `totalBurudgQuty`·
  `totalPrdctnQuty` 총계가 항상 같이 옴, 실측 390콤보 확인) → 호출자가 반드시 명시.
- **Request 모델**: `MineralMapSummaryRequest` — `mineral`·`measure`(필수)·`unit`
  (선택 오버라이드)·`komis_response`·`komis_snapshot_response`·`komis_share_response`.

**`komis_response`(`chart`, `getListMapMnrlChartData`) 매핑**:

| KOMIS 원본 필드 | 내부 필드 | 비고 |
|---|---|---|
| `data[].crtrYr` | `year` | |
| `data[].ntnEngCd`/`ntnKornNm` | `country_code`/`country_name` | |
| `data[].burudgQuty`(매장량) 또는 `prdctnQuty`(생산량) | `value` | `measure`로 어느 컬럼을 읽을지 결정 |
| `data[].cdVal` | `unit`(예: "천톤") | |
| `totalBurudgQuty` 또는 `totalPrdctnQuty`/`TOTALPRDCTNQUTY`(대소문자 혼재) | `country_code="WORLD"` 행 | 세계 합계 |

**`komis_snapshot_response`(`snapshot`, `getListMapMnrlData`)** — 단일연도 국가별
스냅샷, `chart`와 필드명 동일하되 연도 없음(가장 최근연도를 그대로 붙임). 매장량↔생산량
교차비교(`secondary_series`, "매장량 2위 호주는 생산량 8위" 류 문장)에 씀.

**`komis_share_response`(`share`, `getListMnrlTablePrdctnBurgudg`)** — `before1`
(최근연도)만 사용, `rate`→`share_percent`(**표 내 소계 대비 비중**, `chart`의
세계합계와 분모가 달라 별도 지표로만 노출, "세계비중" 라벨로 중복 안 함). `_TOTAL_`
(SU)·`_ETC_`(OT) 코드 행은 제외.

---

## 6~9. `price_base_metals`·`price_minor_metals`·`price_iron_energy`·`price_other` — 광물자원가격 4종

4종이 요청 스키마·파서를 완전히 공유한다(페이지 이름·정의문만 다름).

- **streamlit_demo**: `komis_raw.py::passthrough_price_response`(4종 공용)
- **붙여넣는 JSON**: `getMnrlPrcByMnrkndUnqCd` 원본 그대로(envelope 없음, `dataAvg`
  키 존재로 얕은 검증).
- **필수 파라미터**: `mineral`(코드, 응답엔 `mnrkndKornNm` 한글명뿐이라 자동채움 불가).
- **Request 모델**: `PriceSummaryRequest` — `mineral`(필수)·`mineral_name`(자동채움
  가능)·`compare_mineral`/`compare_mineral_name`/`compare_price_criterion`(비교광종,
  4종 전부 지원)·`price_criterion`·`srch_avg_opt`/`srch_field`/`srch_start_date`/
  `srch_end_date`(호출자가 KOMIS에 던진 조회 파라미터 그대로 echo)·`komis_response`.

| KOMIS 원본 필드 | 경로 | 내부 필드 | 비고 |
|---|---|---|---|
| `data.defaultMnrl[]` | | (관측치 배열) | |
| `crtrYmd` | `defaultMnrl[i]` | `date` | |
| `cmercPrc` | 〃 | `commerce_price` | |
| `lowstPrc` | 〃 | `lowest_price` | 0.00은 결측으로 취급 |
| `hghstPrc` | 〃 | `highest_price` | 0.00은 결측으로 취급 |
| `invt` | 〃 | `inventory` | 0.00은 결측(LME 6대 비철 외엔 항상 0.00으로 옴, 실측 확인) |
| `data.compareMnrl[]` | | (비교광종 관측치) | 위와 동일 필드 규칙 |
| `dataAvg.stdMap.WEEK/MONTH/YEAR.flctnPrc`+`flctnPrcnt` | | `komis_period_comparisons`(전주/전월/전년) | `average_price = latest_price - flctnPrc`로 역산 |
| `dataAvg.INFO.mnrkndKornNm` | | `mineral_name`(자동채움) | 명시값이 있으면 그쪽 우선 |
| `dataAvg.INFO.prcCrtr` | | `price_criterion`(자동채움) | 명시값이 있으면 그쪽 우선 |
| `dataAvg.cmpMap.INFO.mnrkndKornNm` | | `compare_mineral_name`(자동채움) | |
| `dataAvg.cmpMap.INFO.prcCrtr` | | `compare_price_criterion`(자동채움) | |
| `dataAvg.stdMap.CRTRYMD.cmercPrc` → 없으면 `stdMap.DAY.cmercPrc` → 없으면 observations 최신일 | | `latest_price` | 우선순위 순서대로 폴백 |

---

## 10. `map_korea` — 국내 수급지도

- **streamlit_demo**: `komis_raw.py::passthrough_map_korea`
- **붙여넣는 JSON**: `getListKoreaData` 원본 그대로(envelope 없음, `list` 배열 존재로
  얕은 검증).
- **필수 파라미터**: `trade_direction`("import"|"export") — 응답 자체엔 방향이
  안 드러나 호출자가 반드시 명시.
- **Request 모델**: `DomesticTradeSummaryRequest` — `mineral`/`mineral_name`(선택,
  `komis_response`의 조회 파라미터 echo에서 자동채움 가능)·`trade_direction`(필수)·
  `mttr_flow_name`(선택, 코드만 echo되고 한글라벨이 없어 수동 전달)·`komis_response`.

| KOMIS 원본 필드 | 경로 | 내부 필드 | 비고 |
|---|---|---|---|
| `srchDateE`(YYYYMMDD) | 최상위 | `as_of_date` | 행이 아니라 쿼리 파라미터 echo에서 옴 |
| `srchMnrkndUnqCd` | 최상위 | `mineral`(자동채움) | |
| `list[]` | 최상위 | (국가별 목록) | |
| `ntnCd`/`ntnKornNm` | `list[i]` | `country_code`/`country_name` | |
| `incmWeig`/`incmAmt` | `list[i]` | `import_weight`/`import_amount` | |
| `expWeig`/`expAmt` | `list[i]` | `export_weight`/`export_amount` | |
| `list[0].sumIncmAmt`/`sumExpAmt` | | `komis_trade_totals`(수입/수출 총액) | KOMIS `list`가 최대 30개국까지만 줘서, 관측치 합산보다 이 총액이 정확(실측 145콤보 중 9건, 최악 5.8% 과소 확인) |
| `srchCrtrYmd`/`srchNtnCd`/`srchMttrFlowCd`/`srchHsCd` | 최상위 | 조회필터 4종(기간구분/국가/생산품유형/HS) echo | 새 요청필드 불필요, `komis_response`에서 직접 읽음 |

---

## 11. `map_global` — 글로벌 수급지도

- **streamlit_demo**: `komis_raw.py::passthrough_map_global`
- **붙여넣는 JSON(envelope)**:
  ```json
  {"list_data": <getListDataNation 원본, 필수>,
   "bar_chart": <getBarChartDataNation 원본, 선택>,
   "nation_map": <getListMapNationData 원본, 선택>}
  ```
  구버전 예시(envelope 없이 `getListDataNation` 원본만)도 호환.
- **Request 모델**: `GlobalTradeSummaryRequest` — `mineral`/`mineral_name`(자동채움
  가능)·`komis_response`(`list_data`)·`komis_bar_chart_response`(`bar_chart`)·
  `komis_route_share_response`(`nation_map`).

| KOMIS 원본 필드 | 경로 | 내부 필드 | 비고 |
|---|---|---|---|
| `list[]` | `komis_response`(list_data) | (루트별 목록) | |
| `incmNtnCd`/`incmNtnNm` | `list[i]` | `country_code`/`country_name`(도착국) | |
| `expNtnCd`/`expNtnNm` | `list[i]` | `origin_country_code`/`origin_country_name`(원산국) | |
| `weig`/`amt` | `list[i]` | `import_weight`/`import_amount` | |
| `srchMnrkndUnqCd` | 최상위 | `mineral`(자동채움) | |
| `list[0].sumAmt` | | `komis_trade_totals` | `list` 응답 최대 30개 루트 상한 영향이 map_korea보다 훨씬 큼(실측 73콤보 중 72건/99% 영향, 중앙값 30.6%·최악 69.4% 과소) — 이 총액을 우선 사용 |
| `data.barChart.xaxis`/`series` | `komis_bar_chart_response`(bar_chart) | 1위국 연도별 수치 | 마지막 연도(연중 진행분)는 제외, "세계 총액"으로는 안 씀(list_data의 sumAmt와 집계범위 자체가 달라 30%대 격차 실측) |
| `data.mapData[].crtrNtnKornNm`/`trgtNtnKornNm` | `komis_route_share_response`(nation_map) | `route_shares[].origin_name`/`dest_name` | |
| `data.mapData[].crtrNtnAmtRt`/`trgtNtnAmtRt` | 〃 | `route_shares[].origin_share_percent`/`dest_share_percent` | 각자 집계총액 대비 비중 |

---

## 12. 부록 — `forecast_price`(streamlit 메뉴 제외, API는 유효)

- **streamlit_demo**: `komis_raw.py::passthrough_forecast_price`는 존재하나
  `report_gen_client.py::PAGE_SPECS`에서 2026-09-01 제거돼 드롭다운엔 안 뜬다.
- **붙여넣는 JSON**: `getListPricePredc` 원본 그대로(envelope 없음).
- **Request 모델**: `PriceForecastSummaryRequest` — `mineral`(필수)·`forecast_horizon`
  ("medium"|"long", `komis_response` 있으면 자동판별)·`komis_response`.

| KOMIS 원본 필드 | 내부 필드 | 비고 |
|---|---|---|
| `data[].crtrPrd`("28년 4Q"/"01년 1Q") | `period`("YYYY-QN" 또는 "YYYY") | 정규식 `^(\d{2})년\s*(?:(\d)Q)?` |
| `data[].prc` | `price` | |
| `data[].realYn`("Y"/"N") | `is_actual`(True/False) | |
| `data[].mnrkndKornNm` | `mineral_name`(자동채움) | |

---

## 13. 자주 걸리는 함정

- **`komis_snapshot_response`/`komis_share_response`/`komis_bar_chart_response`/
  `komis_route_share_response`는 page_id별 화이트리스트**가 있다 — 허용 안 된
  page_id에 보내면 검증 실패(NO_DATA)로 거부된다: `komis_snapshot_response`는
  `map_mineral`·`indicator_supply`만, `komis_share_response`는 `map_mineral`만,
  `komis_bar_chart_response`/`komis_route_share_response`는 `map_global`만.
- **광종 자동채움 우선순위**: 항상 "호출자가 명시한 값 > 응답 본문에서 자동채움"
  순서다 — `indicator_supply`(snapshot의 `mnrkndUnqCd`)·`map_korea`/`map_global`
  (`srchMnrkndUnqCd` echo)·`price_*`/`forecast_price`(`mnrkndKornNm`, 이름만 채움,
  코드는 여전히 필수) 전부 같은 규칙. 드롭다운 값과 붙여넣은 JSON의 실제 광종이
  다르면 광종명·수치가 서로 다른 광종 것으로 섞여 나올 수 있다(교차검증 없음).
- **총액/비중 필드는 관측치 합산이 아니라 응답에 동봉된 총계 필드를 우선**한다
  (`map_korea`의 `sumIncmAmt`/`sumExpAmt`, `map_global`의 `sumAmt`) — KOMIS `list`
  응답이 상위 N개(최대 30)까지만 주기 때문. 직접 관측치를 합산해 총액을 재계산하면
  안 된다.
- **0.00은 결측**(price_* 4종의 `lowstPrc`/`hghstPrc`/`invt`) — 실제 값 0이 아니라
  KOMIS가 미제공일 때 채우는 관행값이다.
- **envelope 유무를 페이지마다 다르게 다룬다** — `indicator_composite`는 봉투
  있어도/없어도 허용, `indicator_supply`도 마찬가지(구버전 호환), 반면 `map_mineral`·
  `map_global`은 처음부터 envelope 필수 설계(여러 KOMIS API를 한 붙여넣기로
  받아야 해서). 각 페이지 절의 "붙여넣는 JSON" 예시를 그대로 따를 것.
