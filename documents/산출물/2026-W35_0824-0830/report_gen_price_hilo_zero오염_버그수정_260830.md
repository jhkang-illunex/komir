# report_gen price_range 최고/최저가 0.00 오염 버그 수정 (2026-08-30)

## 배경
사용자가 KOMIS `getMnrlPrcByMnrkndUnqCd`(니켈) 응답 원문을 report_gen API에
"통째로" 보내려다 결과가 부실하다고 제보 — 조사 과정에서 두 가지를 확인했다.

## 1) 원본 KOMIS 응답을 그대로 보내면 안 된다 (설계 확인, 코드 수정 아님)
`app/main.py:267`의 `_analysis_request_validation_to_no_data` 핸들러가
분석요약 라우트(`/api/v1/analysis/`·`/prices/`·`/indicators/`·`/maps/`)의
요청 스키마 위반을 422가 아니라 항상 `200 + {"status":"NO_DATA"}`로
돌려준다(2026-08-27 skeptic 감사 반영 — "항상 200" 계약). 라이브 재현으로
확인: `dataAvg`/`data.defaultMnrl` 같은 KOMIS 원본 필드명을 그대로 담아
`/api/v1/analysis/prices/base-metals`에 POST하면 조용히 NO_DATA가 나온다
(에러 메시지 없음). report_gen은 자체 스키마(`observations[].date`/
`commerce_price`/`lowest_price`/`highest_price`/`inventory`,
`komis_period_comparisons.{week,month,year}.{average_price,change_pct}`)를
요구하므로 호출자가 KOMIS 필드명→report_gen 필드명으로 변환해서 보내야
한다. 이 부분은 기존 설계(호출자가 요청 바디로 값 공급, report_gen은
KOMIS를 직접 안 읽음) 그대로라 코드 수정 없음.

## 2) 신규 버그 — `lowest_price`/`highest_price`의 0.00 오염 (수정함)
변환된 페이로드를 실제로 쳐보니 "현재 위치" 근거가 **"조회기간 중 최고
0.00, 최저 0.00였다"**로 나왔다. KOMIS는 최고/최저가가 없는 날을 `null`이
아니라 문자열 `"0.00"`으로 채워 보내는데(`inventory` 필드는 이미 같은
문제로 값 기반 게이트가 적용돼 있음), `komir_summary.py::
calculate_price_summary`의 `has_full_hilo_coverage` 체크는
`highest_price is not None`만 확인해 0.0을 정상 데이터로 오인했다.

더 나쁜 패턴(부분 오염)도 재현 확인: 조회기간에 실제 최저가가 있는
과거 관측치와 0.00으로 채워진 최근 관측치가 섞이면, `max()`는 0.00이
못 이겨서 정상 값이 나오지만 **`min()`은 0.00에 오염돼 최저가만 조용히
0.00으로 깨진다** — 최고가가 그럴듯해 보여 눈치채기 더 어렵다.

### 수정
`inhouse/services/report_gen/app/analysis/komir_summary.py`의
`has_full_hilo_coverage` 체크와 그에 따른 `period_high`/`period_low`
후보 관측치를 `inventory`와 동일한 값 기반 게이트(`not in (None, 0, 0.0)`)로
바꿨다. 커버리지가 불완전하면(0.00 포함) 기존에 이미 있던 폴백 경로
(`commerce_price` 전체 범위, "조회기간 관측치(실거래가) 기준" 문구)로
정직하게 넘어간다 — 새 폴백 경로를 만든 게 아니라 게이트 조건만 고쳤다.

코드 주석 하나(2026-08-29 inventory 처방 부분)도 "lowest_price/
highest_price가 이미 같은 방식으로 게이트하는 중"이라고 잘못 적혀 있던
것을 사실대로("이번에 뒤늦게 같은 처리를 적용") 정정했다.

### 검증
- 케이스 1(전부 0.00, 사용자 실제 페이로드 재현): 수정 전
  "최고 0.00, 최저 0.00" → 수정 후 "조회기간 관측치(실거래가) 기준
  최고 16,940.00, 최저 16,660.00였다"(commerce_price 폴백 정상 동작).
- 케이스 2(2024-12 실값 + 2026-08 0.00 혼합): 수정 전 최저가만
  0.00으로 오염 → 수정 후 "최고 16,940.00, 최저 15,535.00"(진짜 과거
  최저값 정상 반영).
- `scripts/komis_dump_smoke_test.py` 회귀: 395콤보 전부 OK
  (mismatch 0, internal_error 0) — 정적 덤프 표본에는 이 조합(0.00
  오염 관측치)이 없어 회귀 스위트가 원래 못 잡던 케이스였다.

### 커밋
`inhouse/services/report_gen/app/analysis/komir_summary.py` 수정 —
main-agent 승인 후 재빌드·재기동 필요(이 세션은 docker 조작을 하지
않는다는 기존 원칙 유지).
