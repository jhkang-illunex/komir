# report_gen — compare_price_criterion 필드 복원 + 자동채움 (2026-08-30)

## 배경
사용자: "compare_price_criterion 필드 추가할지 검토해줘"(직전 3차
자동채움 재감사에서 "필드/기능 자체가 없다"고 보고한 항목).

## 검토 결과 — "추가"가 아니라 "회귀 복원"이었다
코드를 다시 열어보니 `compare_price_criterion`은 애초에 없던 필드가
아니었다:
- `models.py`(내부 `AnalysisSummaryRequest`)에 여전히
  `compare_price_criterion: str | None = None`로 살아 있었다.
- `summary.py::_analyze_price`도 여전히 `request.compare_price_
  criterion`을 읽어 `applied_filters["compare_price_criterion"]`에
  넣는 코드가 그대로 있었다.
- 그런데 `routers/analysis.py::PriceSummaryRequest`(캐스터가 실제로
  보낼 수 있는 Swagger 필드)에는 이 필드가 **없었다** — `c76466a47`
  (2026-08-30 "Swagger 스키마 트리밍", 이 세션 본인 작업)에서
  "komis_response로 대체돼 불필요"라고 판단해 `compare_observations`
  등과 함께 지운 것.

`compare_observations`는 실제로 komis_response(`data.compareMnrl`)로
완전히 대체됐지만, `compare_price_criterion`은 그때도 지금도
auto-fill 경로가 없었다(3차 재감사에서 "필드가 아예 없다"고 잘못
보고한 것도 이 사실 — 라우터에서 지워졌으니 없는 게 맞아 보였지만,
내부 로직은 여전히 그 값을 소비하고 있었다). 즉 그 트리밍 이후로는
**호출자가 이 값을 보낼 방법 자체가 없어서, 보고서의 "비교광종
가격기준" 표시가 조용히 죽어 있었다** — 스스로 만든 회귀.

## 조사 — auto-fill 가능 여부
`compare_mineral_name`을 찾을 때 확인했던 라이브 캡처(네오디뮴 대비
갈륨)를 다시 열어보니 같은 `dataAvg.cmpMap.INFO` 블록에
`prcCrtr: "99.99%min FOB China"`도 이미 있었다 — `compare_mineral_
name`을 뽑을 때 같은 블록을 열어놓고 `prcCrtr`는 놓쳤던 것(직전
커밋에서 이미 확보한 증거를 끝까지 다 안 썼다).

## 변경
- `app/analysis/summary.py::_parse_komis_price_response()` 반환값
  6개→7개로 확장, `compare_price_criterion`(`dataAvg.cmpMap.INFO.
  prcCrtr`) 추가.
- `_analyze_price()`에서 `request.compare_price_criterion or
  komis_compare_price_criterion` 폴백 체인으로 연결(`compare_mineral_
  name`과 동일 패턴).
- `routers/analysis.py::PriceSummaryRequest`에 `compare_price_
  criterion: str | None = None` 필드 복원.

## 검증
- 실제 캡처한 라이브 응답(네오디뮴 vs 갈륨)으로 `compare_price_
  criterion`을 아예 안 보내고 `prices/minor-metals` 호출 → 보고서에
  "**비교광종 가격기준**: 99.99%min FOB China" 정상 출력.
- `PriceSummaryRequest` Swagger 재조회 — `compare_price_criterion`
  필드 노출 확인(6개→7개).
- `komis_dump_smoke_test.py` 회귀 395콤보(8페이지) 전부 mismatch 0
  유지.

## 교훈
"필드/기능 자체가 없다"는 결론을 내리기 전에 **왜 없어졌는지**(원래
없었나, 지워졌나)를 먼저 확인해야 한다 — 지워진 필드는 grep으로
"필드 없음"까지는 보이지만 "내부 로직이 여전히 그 값을 기다리고
있는가"는 별도로 확인해야 드러난다. 이번 건은 이 세션 스스로가
만든 회귀를 사용자 질문으로 되짚어 찾은 사례.

## 커밋
`app/analysis/summary.py`·`app/routers/analysis.py` — main-agent
승인 후 재빌드·재기동 필요.
