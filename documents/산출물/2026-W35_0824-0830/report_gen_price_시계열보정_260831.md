# report_gen price — 입력 JSON 시계열 추가 분석으로 보정 (2026-08-31)

## 배경
사용자 지시: "입력된 komis json에 있는 데이터만을 이용하고, 연속적인
숫자열을 분석해서 llm에 던지는식으로 조금만 더 보정하세요. 입력된 json
외 다른 데이터는 안 씁니다." — geo_events·compare_mineral 같은 외부/추가
데이터원은 명시적으로 배제하고, 이미 받은 `observations`(komis_response
경유든 손 매핑이든 동일)만으로 파생 가능한 근거를 더 뽑아내라는 지시.

## 변경 (전부 `komir_summary.py::calculate_price_summary`, 새 데이터소스 0건)
1. **조회기간 전체 변동(`period_overall_change`, major_changes 신규)** —
   지금까지 major_changes는 KOMIS 롤링윈도우(전주/전월/전년)만 다뤘고,
   "이번에 받은 관측치 전체가 시작부터 끝까지 어떻게 움직였는지"는 어느
   근거에도 없었다. 첫 관측치(조회기간 시작)와 최신 관측치를 직접 비교해
   문장 1개 추가: "조회기간 시작(2026년 6월 1일, 19,050.00) 대비
   -12.55% 변동했다." — `SummaryNarrative.major_changes` 하드 제약
   (max_length=5)을 넘지 않도록, day_over_day+week+month+year+
   price_streak로 이미 5개가 찼으면(둘 다 동시 발생하는 드문 경우) 자리가
   없어 자동으로 생략한다(정상 재현 검증함, 크래시 없음).
2. **최고/최저가에 발생 날짜 추가(`period_range`, current_position 문구
   보강)** — 기존엔 "조회기간 중 최고 19,170.00, 최저 16,065.00였다"처럼
   값만 있었다. 그 값을 만든 관측치의 날짜를 찾아 "최고 19,170.00(2026년
   6월 2일), 최저 16,065.00(2026년 7월 6일)였다"로 보강. 근거 개수는
   그대로(1개), 문장 내용만 진해졌다 — section 상한과 무관.

## 검증
- 니켈 60일 데이터(komis_response 그대로)로 재현: major_changes 5문장
  (전일·전주·전월·전년·조회기간전체), current_position 2문장(날짜 포함
  최고/최저·재고량) — 둘 다 하드 제약(5/3) 안에서 정상.
- 합성 데이터로 price_streak까지 동시 발생하는 경계 케이스(day_over_day+
  week+month+year+streak=5) 재현 — `period_overall_change`가 자리 없어
  자동 생략, `ValidationError` 없음 확인.
- `komis_dump_smoke_test.py` 회귀 395콤보 전부 mismatch 0 유지.

## 의도적으로 안 건드린 것
`prompts.py::SECTION_SENTENCE_RANGES`의 price_* `major_changes`가 (1,3)
으로, 규칙기반 근거 최대치(5)보다 적다 — 이미 있는 주석("실측(LLM 온)
재현 전까지는 범위를 임의로 안 바꾼다")을 따라 이번에도 안 건드렸다.
규칙기반(`llm=None`, 이번 검증 전부 이 경로) 경로는 이 범위를 아예 안
타서 무관하고, LLM을 실제로 켰을 때 최대 5개 근거를 최대 3문장으로
압축해서 쓰라는 기존 설계(더 조밀한 문장으로 합치기를 기대하는 의도로
보임)가 그대로 유지된다 — LLM 실측 후 필요하면 별도로 판단할 사안.

## 커밋
`inhouse/services/report_gen/app/analysis/komir_summary.py` — main-agent
승인 후 재빌드·재기동 필요.
