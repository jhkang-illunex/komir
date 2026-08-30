# report_gen map_korea/global — mineral도 komis_response에서 자동 채움 (2026-08-31)

## 배경
사용자: "komis_response 외는 다 필요없어 보이는데 솔직히." 어제 트리밍
후 남은 필드(mineral·mineral_name·start_date·end_date·compare_mineral·
compare_mineral_name·trade_direction)를 페이지별로 다시 감사했다.

## 결론(정직한 답)
전부 komis_response로 대체 가능한 건 아니다 — KOMIS 응답 본문에 그
값이 아예 없는 페이지가 있다. 하지만 감사 과정에서 실제로 하나 더
줄일 수 있는 걸 찾았다:

| 필드 | price_* 4종 | map_korea/global |
|---|---|---|
| `mineral`(코드) | **응답 본문에 없음**(`mnrkndKornNm` 한글명만 있고 내부 코드 없음) — 필수 유지 | **응답이 조회 파라미터 `srchMnrkndUnqCd`를 그대로 echo** — 2026-08-31부터 자동 채움, 필수 아님 |
| `mineral_name` | 이미 자동 채움(`dataAvg.INFO.mnrkndKornNm`, 2026-08-30) | 응답에 광종 한글명 자체가 없어 자동 채움 불가 — 선택 필드로 유지(안 주면 코드를 이름으로 표시) |
| `start_date`/`end_date` | KOMIS 응답이 이미 특정 기간으로 조회된 결과라, 그 결과를 더 좁히고 싶을 때만 쓰는 선택적 필터 — 있어도 없어도 동작에 지장 없음(0-cost) | 좌동 |
| `compare_mineral`(코드) | 응답의 `data.compareMnrl`엔 비교광종 가격만 있고 코드가 없음 — 비교 조회 시에만 필수, 필드 자체는 선택 | 해당 없음(비교광종 기능 없음) |
| `trade_direction` | 해당 없음 | map_korea 전용, 응답 한 행에 수입/수출 금액이 같이 오므로 "어느 방향을 서술할지"는 코드로 못 정함 — 호출자 의도 표현, 선택 필드(기본값 수입) |

## 변경
`_parse_komis_map_korea_response`/`_parse_komis_map_global_response`가
`raw.get("srchMnrkndUnqCd")`(조회 파라미터 echo)도 같이 반환하도록
확장. `_trade_series_from_request`가 `request.mineral or komis_mineral`
로 우선순위를 매기고, 내부 `AnalysisSummaryRequest.validate_period`의
"mineral 필수" 검사도 `map_korea`/`map_global` + `komis_response` 있음
조합에서만 예외를 허용하도록 좁혀서 고쳤다(price_* 4종은 그대로 필수).
라우터 모델(`DomesticTradeSummaryRequest`/`GlobalTradeSummaryRequest`)
의 `mineral`도 선택 필드로 내렸다.

## 검증
- map_korea/map_global 둘 다 `{"komis_response": <원본>}`만 보내도(구리
  실제 데이터) `status="ok"`로 정상 산출 확인 — 진짜 `komis_response`
  하나만 필요.
- price_base_metals는 여전히 `mineral` 없이 보내면 `NO_DATA`로 거부됨을
  재확인(퇴행 없음 — 응답 본문에 코드가 없는 페이지는 자동 채움이
  거짓말이 되므로 의도적으로 그대로 뒀다).
- 최종 스키마 필드 전수 감사(OpenAPI): `PriceSummaryRequest`는
  `mineral`만 필수, 나머지 8개 필드 전부 선택. `DomesticTradeSummaryRequest`
  ·`GlobalTradeSummaryRequest`는 전부 선택 필드(둘 다 komis_response
  단독으로 충분).
- `komis_dump_smoke_test.py` 회귀 395콤보 전부 mismatch 0 유지.

## 커밋
`app/analysis/models.py`(validate_period 예외)·`app/analysis/summary.py`
(파서 3종 mineral 반환 추가, `_trade_series_from_request` 우선순위)·
`app/routers/analysis.py`(mineral 필드 선택화+docstring) — main-agent
승인 후 재빌드·재기동 필요.
