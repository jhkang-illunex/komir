# report_gen API — 아규먼트별 KOMIS 조회 URL 매핑

> report_gen의 각 분석요약 API를 호출하는 데 필요한 아규먼트(요청 바디 필드) 중,
> KOMIS 원본 응답을 그대로 담는 필드는 komis.or.kr의 어느 URL을 호출해야 그 JSON을
> 얻을 수 있는지만 정리한다. 계산 로직·응답 형식 등은 다루지 않는다.
>
> **공통**: KOMIS AJAX는 동일출처 세션 쿠키가 필요하다 — 먼저 해당 화면의 페이지
> URL을 GET해 세션 쿠키를 받은 뒤, 같은 세션으로 AJAX 경로를 POST해야 응답이
> 온다(쿠키 없이 AJAX만 바로 호출하면 실패). base URL은 `https://www.komis.or.kr`.
> 작성일: 2026-09-03.

## 1. `indicator_market` — `POST /api/v1/analysis/indicators/market`

| 아규먼트 | 필수 | 값 |
|---|---|---|
| `mineral` | 필수 | 직접 지정(코드) — KOMIS 응답에 광종 식별자가 없음 |
| `komis_response` | 사실상 필수 | KOMIS `getListIndxMnrk` 응답 |

- 페이지 URL: `/Komis/MnrlIndc/IndcMrkt`(로그인 필요)
- AJAX 경로: **미확인** — 로그인 필요 화면이라 이 프로젝트에서 실제 호출해본 적
  없고, 발주처가 제공한 `getListIndxMnrk` 원본 JSON 덤프로만 확인됐다(액션명만
  앎, 정확한 경로는 모름).

## 2. `indicator_supply` — `POST /api/v1/analysis/indicators/supply`

| 아규먼트 | 필수 | 값 |
|---|---|---|
| `mineral` | 선택 | `komis_snapshot_response`가 있으면 그 안에서 자동채움, 없으면 직접 지정 |
| `komis_response` | 필수 | KOMIS `getListIndxSplyBalncMnrk` 응답 |
| `komis_snapshot_response` | 선택 | KOMIS `getChartDataSpdmStbt` 응답 |

- 페이지 URL: `/Komis/MnrlIndc/IndxSply`(로그인 필요)
- AJAX 경로: **미확인** — indicator_market과 동일한 사유(로그인 필요, 액션명만 앎).

## 3. `indicator_composite` — `POST /api/v1/analysis/indicators/composite-index`

| 아규먼트 | 필수 | 값 |
|---|---|---|
| `komis_response` | 필수(유일 입력) | KOMIS `getLineChartIndx` 응답 |

- 페이지 URL: `/Komis/MnrlIndc/IndxMin`
- AJAX 경로: `/Komis/MnrlIndc/IndxMinDex/ajax/getLineChartIndx`(POST)
- 파라미터: `srchDateS`/`srchDateE`(yyyymmdd)

## 4. `map_mineral` — `POST /api/v1/analysis/maps/mineral`

| 아규먼트 | 필수 | 값 |
|---|---|---|
| `mineral` | 필수 | 직접 지정(코드) |
| `measure` | 필수 | 직접 지정("reserves"\|"production") — 응답만으론 매장량/생산량 구분 불가 |
| `komis_response` | 필수 | KOMIS `getListMapMnrlChartData` 응답 |
| `komis_snapshot_response` | 선택 | KOMIS `getListMapMnrlData` 응답 |
| `komis_share_response` | 선택 | KOMIS `getListMnrlTablePrdctnBurgudg` 응답 |

- 페이지 URL: `/Komis/MnrlMap/MnrlMap`
- AJAX 경로(3개, 같은 파라미터를 같이 씀):
  - `/Komis/MnrlMap/MapMnrl/ajax/getListMapMnrlChartData`
  - `/Komis/MnrlMap/MapMnrl/ajax/getListMapMnrlData`
  - `/Komis/MnrlMap/MapMnrl/ajax/getListMnrlTablePrdctnBurgudg`
- 파라미터: `srchMnrkndUnqCd`(광종코드)·`srchDateS`/`srchDateE`(연도)·
  `selectedTab`("burudg"=매장량, "prdctn"=생산량)

## 5~8. `price_base_metals`·`price_minor_metals`·`price_iron_energy`·`price_other`

4종 전부 같은 2단계 AJAX 흐름을 쓴다(페이지 URL과 `HP000` 값만 다름).

| 아규먼트 | 필수 | 값 |
|---|---|---|
| `mineral` | 필수 | 직접 지정(코드) — 응답엔 한글명만 있어 자동채움 불가 |
| `komis_response` | 필수 | KOMIS `getMnrlPrcByMnrkndUnqCd` 응답(2단계 조회로 얻음, 아래 참고) |

| page_id | 페이지 URL | `HP000` |
|---|---|---|
| `price_base_metals` | `/Komis/RsrcPrice/BaseMetals` | `HP001` |
| `price_minor_metals` | `/Komis/RsrcPrice/MinorMetals` | `HP002` |
| `price_iron_energy` | `/Komis/RsrcPrice/IronOre` | `HP003` |
| `price_other` | `/Komis/RsrcPrice/EtcMnrl` | `HP004` |

- **1단계**(가격기준 코드 조회) AJAX: `/Komis/RsrcPrice/ajax/getMnrlPriceCrtr`(POST,
  파라미터 `HP000`+`mnrkndUnqCd`=광종코드) → 응답 목록에서 가격기준 1건의
  `cdKey`를 얻는다. ⚠ 이 `cdKey`는 고정값이 아니라 주기적으로 재발급되는
  값이라(실측 확인) 매번 이 1단계부터 다시 호출해야 한다 — 하드코딩 불가.
- **2단계**(실제 가격 데이터) AJAX: `/Komis/RsrcPrice/ajax/getMnrlPrcByMnrkndUnqCd`
  (POST, 파라미터 `srchMnrkndUnqCd`=광종코드·`srchPrcCrtr`=1단계에서 얻은
  `cdKey`·`srchAvgOpt`(DAY/WEEK/MONTH/QUARTER/YEAR)·`srchField`(year/month)·
  `srchStartDate`/`srchEndDate`) — 이 응답이 `komis_response`에 담을 JSON.

## 9. `map_korea` — `POST /api/v1/analysis/maps/domestic-trade`

| 아규먼트 | 필수 | 값 |
|---|---|---|
| `mineral` | 선택 | `komis_response`가 조회 파라미터를 echo해 자동채움됨 |
| `trade_direction` | 필수 | 직접 지정("import"\|"export") — 응답만으론 방향 구분 불가 |
| `komis_response` | 필수 | KOMIS `getListKoreaData` 응답 |

- 페이지 URL: `/Komis/MnrlMap/Korea`
- AJAX 경로: `/Komis/MnrlMap/MapKorea/ajax/getListKoreaData`(POST)
- 파라미터: `srchMnrkndUnqCd`(광종코드)·`srchDateS`/`srchDateE`·
  `srchIncmExp`("I"=수입, "E"=수출)·`srchCrtrYmd`("Y"=년별, "M"=월별)·
  `srchNtnCd`(국가 필터, 선택)·`srchMttrFlowCd`/`srchHsCd`(생산품유형/HS코드
  필터, 선택)

## 10. `map_global` — `POST /api/v1/analysis/maps/global-trade`

| 아규먼트 | 필수 | 값 |
|---|---|---|
| `mineral` | 선택 | `komis_response`가 조회 파라미터를 echo해 자동채움됨 |
| `komis_response` | 필수 | KOMIS `getListDataNation` 응답 |
| `komis_bar_chart_response` | 선택 | KOMIS `getBarChartDataNation` 응답 |
| `komis_route_share_response` | 선택 | KOMIS `getListMapNationData` 응답 |

- 페이지 URL: `/Komis/MnrlMap/Nation`
- AJAX 경로(3개, 같은 파라미터를 같이 씀):
  - `/Komis/MnrlMap/MapNation/ajax/getListDataNation`
  - `/Komis/MnrlMap/MapNation/ajax/getBarChartDataNation`
  - `/Komis/MnrlMap/MapNation/ajax/getListMapNationData`
- 파라미터: `srchMnrkndUnqCd`(광종코드)·`srchDateS`/`srchDateE`·
  `srchImxprtSeCd`(기본 "I")·`srchExpNtnCd`/`srchIncmNtnCd`(수출/수입국 필터,
  선택)

---

`price_group`·`forecast_price`는 요약보고서 작업 대상이 아니라 이 문서에도
포함하지 않는다.
