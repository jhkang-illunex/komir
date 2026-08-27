# report_gen 분석요약 — DB 프롬프트 기반 LLM 보고서 전체 재작성·반복 검수 (2026-08-27)

## 무엇인가
사용자 지시(2026-08-27): "DB기반 프롬프트 생성 로직을 통해 기존에 작성한 보고서를
전체적으로 싹 다 작성 → 오류 점검 → 지침 준수 체크 → 미준수분 프롬프트·코드 수정,
오류 0·미준수 0이 될 때까지 반복(/loop)". 각 회차의 산출물(콤보별 최종 Markdown
보고서 + LLM 원출력 + 위반 목록)을 여기 보존한다. 서비스 자체는 08-26 계약대로
보고서를 DB에 저장하지 않으므로(응답에만 실음) 이 폴더가 유일한 보존본이다.

## 생성 방법 (재현)
- 코드: `inhouse/services/report_gen` (커밋 `de3637b1f` 이후 루프 회차별 수정분 — WORKLOG
  2026-08-27 "반복 루프" 항목 참고)
- 입력: `income_data/komis/komis_0{1..8}_*.json`(발주처 KOMIS 8페이지 실데이터 덤프, git
  미추적) → `scripts/komis_dump_smoke_test.py`의 어댑터로 384콤보 요청 생성(price 209·
  indicator_market/supply·composite 1·map_korea·map_global·map_mineral 104, forecast_price는
  덤프 원천 없음)
- LLM: 로컬 vLLM `http://127.0.0.1:52302/v1`, 모델 `gemma-4-26b-a4b`(세션 환경변수로만
  주입 — `.env`의 LLM_BASE_URL은 compose 서비스명이라 호스트에서 해석 불가)
- 프롬프트·페이지 정책·출력 계약: PostgreSQL `ai_cfg.cfg_prompt`(`prompt_store.reload()`로
  기동 시 로드) — 회차 시작 전 `python -m app.analysis.seed_prompts`로 코드 기본값과 동기화
- 하네스: `loop_harness_snapshot_round1.py` (스크래치패드 원본의 회차 시점 스냅샷).
  실행 `python3 loop_harness.py [--limit N] [--pages ...] --workers 8 --out <json>`
- 판독: `inspect_loop.py <json>` — 폴백 콤보의 LLM 시도별 출력(절 오배치·누락 id)을 표로

## 파일 구조
- `round0_pilot/` — 하네스 보정용 파일럿(페이지당 2건/6건). `pilot_limit6_b_with_llm_attempts.json`
  이 폴백 원인 진단에 쓴 파일(LLM 원출력 포함).
- `roundN_full/loop_fullN.json` — 회차 N 전체(384콤보) 결과. 스키마:
  `elapsed_s`, `by_page{count,ok,NO_DATA,INTERNAL_ERROR,llm_refined,violating}`,
  `rule_counter{규칙id: 건수}`, `fallback_reasons{검증 실패 사유: 건수}`,
  `entries[{combo_key,page_id,status,llm_refined,warnings,markdown,violations,summary,llm_attempts,elapsed}]`
- 규칙 id: `G0x` 공통(3절 존재·내부용어·원인 서술 금지·격식체·YYYY-MM 원형·중복 구절·
  금지어 '추세'), `P-<page>-0x` 페이지별(PDF 템플릿 구조 — 핵심진단/주요변화/현재위치의
  필수 요소). 근거는 발주처 PDF 2종(`AI 통계분석 요약 답변_광물가격전망지표.pdf`,
  `AI 통계분석 요약답변_수급지도광물지도.pdf`).

## 회차 기록
- **round0(파일럿, limit 2→6)**: 13건 → 폴백 2, 위반 2(하네스 정규식 오탐, 수정); 37건 → 폴백
  6~10(LLM 비결정성으로 표본마다 다름), 위반 0~1. 원인: map_global `top5_concentration` 누락
  (근거 4개 vs 2문장 계약), price 근거 5개 vs 2문장, indicator 절당 1문장에 근거 3개,
  composite 1년 비교값 없을 때 다른 절 근거 차용. → **1회차 수정**: 공통 프롬프트에
  "모든 evidence_id 정확히 1회·지정 section에서만" 명시, composite 프롬프트 보강,
  price/map_global 프롬프트의 "(있는 경우)" 제거, 출력 계약 완화(price·map_global major
  (1,3), indicator_market/supply major (1,2)) — 코드 기본값+DB 재시드.
- **round1(384건, 450s)** `round1_full/loop_full1.json`: INTERNAL_ERROR 0 · NO_DATA 0 ·
  폴백 2(0.5%) · 위반 35 — G02 17·G04 18·G05 8·P-global-02 9·P-map-01 14(콤보 중복
  포함). 판독: 본문 `(current_state)` id 표기(→G02, 문장 분리 연쇄 오탐 G04/P-map-01),
  근거문 원형 날짜(G05), 어댑터 "출처미상"+`→` 풀어쓰기+조사 오류(P-global-02),
  검증기 등급명 오인 폴백 1. → **2회차 수정**(WORKLOG 참고): 프롬프트 2건·검증기 2건·
  계산기 날짜 한글화·어댑터 루트화·체커 보정(G08 로/으로 규칙 신설).
- **round2(384건, 472s)** `round2_full/loop_full2.json`: INTERNAL_ERROR 0 · NO_DATA 0 ·
  폴백 4(map_mineral, 전부 "근거에 없는 숫자" = LLM이 PDF대로 "2025년 기준 …1위"라고
  썼는데 `current_leaders` 근거문에 연도가 없어 검증 탈락) · 위반 1(G08 "페루→미국로").
  → **3회차 수정**: `calculate_mineral_map_summary` current_leaders 근거문에 연도 포함,
  map_global 프롬프트에 "화살표 뒤엔 '루트'+조사".
- **round3(384건, 473s)** `round3_full/loop_full3.json`: INTERNAL_ERROR 0 · NO_DATA 0 ·
  **폴백 0** · 위반 1(G06 구절 반복 — 대한민국 루트가 상위 3위 안에 들면 `korea_route_rank`
  근거문이 같은 루트의 금액·비중을 반복). → **4회차 수정**: `calculate_global_trade_summary`
  상위 3위 안 한국 루트는 "N위(상대국, 위 랭킹 참조)"로 금액 생략, 1~3위 랭킹 근거문도
  "루트로"로 조사 오류 제거.
- **round4(384건, 551s)** `round4_full/loop_full4.json`: INTERNAL_ERROR 0 · NO_DATA 0 ·
  **위반 0** · 폴백 1(price 니오븀 — 전일·전주·전월·전년 4개 비교를 PDF처럼 한 문장에
  썼는데 문장당 근거 id 상한 3에 걸려 전년평균 id 누락→"근거에 없는 숫자"). 콤보당
  소요 p50 11.3s/p95 16.6s(8동시). → **5회차 수정**: `SummarySentence.evidence_ids` 상한
  3→5, price 페이지 `max_evidence_ids_per_sentence`=5(코드 기본값+DB), 프롬프트에
  "문장에 쓴 근거 id 전부 evidence_ids에".
- **round5(384건, 488s)** `round5_full/loop_full5.json`: **LOOP_CLEAN** — 384/384 ok ·
  LLM 정제 채택 384 · INTERNAL_ERROR 0 · 폴백 0 · 위반 0. 루프 종료.
  누적: 폴백 16%(파일럿)→0.5%→1.0%→0→0.3%→0, 위반 35→1→1→0→0.
- 최종 하네스 스냅샷은 `loop_harness_snapshot_round4.py`(round4~5 동일).

## 주의
- LLM 출력은 비결정적(temperature 0이어도 vLLM 배치 영향)이라 같은 회차를 다시 돌려도
  폴백 콤보가 달라질 수 있다 — 회차 판정은 "건수·사유 분포"로 본다.
- 결과 JSON은 요청 바디(observations)를 담지 않는다(덤프에서 재생성 가능). 삭제 금지
  정책(artifact-provenance-policy) 적용.
