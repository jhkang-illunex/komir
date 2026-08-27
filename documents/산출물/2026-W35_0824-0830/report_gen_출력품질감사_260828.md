# report_gen 출력 품질 감사 (2026-08-28)

## 무엇인가
main-agent(다른 Claude 세션)의 요청으로 report_gen의 두 데모 화면(프롬프트 관리
`prompt_admin.py`, 요약보고서 데모 `report_demo.py`)이 실제로 만들어내는 **최종
보고서 본문**을 발주처 PDF 템플릿 2종(`AI 통계분석 요약 답변_광물가격전망지표.pdf`,
`AI 통계분석 요약답변_수급지도광물지도.pdf`) 기준으로 감사한다. 코드 수정 없이
점검·기록만 한다(발견된 버그는 "다음 주 작업 목록"으로 남긴다).

## 환경
- `komir-report-gen-test` 컨테이너, 포트 18003(`curl http://localhost:18003/...`로
  호스트에서 직접 호출 가능 — docker exec 불필요, 08-28 최신 빌드 확인됨 §Phase 0).
- DB 조사/편집은 `docker exec -w /app -e PYTHONPATH=/app komir-report-gen-test python -c "..."`
  로 `shared.db.read_sql_pg`/`execute_pg` 직접 호출([[report_gen_llm_required_evidence_priority_260828]]
  기법 재사용).
- 12개 page_id: indicator_market/supply/composite, map_mineral, forecast_price,
  price_base_metals/minor_metals/iron_energy/other, map_korea, map_global, price_group.

## Phase 0 — 판별 체크(완료)
- `POST /prices/iron-energy`, `POST /price-group` 둘 다 200/ok 확인 — 컨테이너가
  2026-08-28 12종 코드로 최신 상태(구버전 아님, 감사 결과 귀속 문제 없음).
- round5(`report_gen_LLM보고서_반복검수_260827/round5_full`)는 **08-27 실행 + 구
  page_id 스키마**(`price` 미분리, `price_iron_energy`/`price_other`/`price_group`
  없음)라 이번 12종 감사엔 직접 못 씀 — 구조 규칙(G0x/P-xxx) 클린 이력의 보조
  참고자료로만 취급, 1차 증거는 이번에 새로 뽑은 라이브 표본.
- PDF 2종 원문 확보 완료(아래 각 절 판정에서 인용).

## Phase 1 — 12개 page_id 출력 품질 감사 (완료)
표본 26건 저장: `report_gen_출력품질감사_260828_samples/<page_id>_<variant>.json`
(+ `_index.json`), 전부 `http://localhost:18003`에 순차 curl로 라이브 생성.

### 정상(PDF 문형과 자연스럽게 일치)
| page_id | 근거 발췌 | 비고 |
|---|---|---|
| price_base_metals/minor_metals/iron_energy/other | "전주평균 대비 +0.83%, 전월평균 대비 +0.83%, 전년평균 대비 +3.08% 상승했습니다. 3개월 연속 상승세" | §1-1 문형과 근접. "주요 요인" 절 공백은 기존 확인 갭([[report_gen_prompt_content_260826]])이 여전함 — P2 |
| price_group | "니켈이 전주 대비 1.80%로 가장 높은 상승 폭..., 구리가 0.40% 내리며 가장 큰 낙폭" | §1-2 문형과 거의 동일. 요인 절 공백 동일 갭 — P2 |
| indicator_market / indicator_supply | 단계 전환·유지기간 서술 자연스러움, 5단계 등급명이 시장(신중/주의/중립/관심/기회)·수급(긴장/주의/관심/안정/원활)로 정확히 분리 | §2-2/2-3 충족 |
| map_korea / map_global | 관측 1건→"기간별 변화는 계산하지 않았다"(투명한 폴백) / 다건→CR3·상위5개국 비중까지 §1/§2 문형과 정확히 일치 | 정상 |
| price_minor_metals(비교광종) | "코발트는 -6.87% 변동한 반면, 리튬은 +3.33% 변동" — 방향이 실제 반대라 "반면" 사용이 올바름 | 정상(아래 indicator_composite 오용과 대조됨) |
| map_mineral(연도 다건, reserves/production) | "칠레는 매장량이 2021년 2억 톤에서 2025년 1억 8,000만 톤" 류 | §3/§4 문형과 잘 맞음 |

### 개선필요(신규 발견)
1. **indicator_composite — 대조 접속사 오용, P1.** 메이저·희소금속지수가 둘 다 하락인데 "메이저금속지수는 0.81% 내린 반면 희소금속지수는 0.80% 내렸다"처럼 "반면"을 씀. variant에서는 완전히 같은 수치(1.96%)에 "전주보다 1.96% 내렸지만 한 달 전보다 1.96% 내렸다"로 역접을 씀 — 관측치가 희소(2~3개)해 주간/월간 구간이 겹칠 때 나타나는 패턴(§Phase 2 품질저하 항목과 연결). 발주처가 보면 바로 "왜 반면이지?"로 느낄 수준.
2. **map_mineral — 데모 기본 placeholder가 서버 최소요건 미달, P1(데모 UX).** `report_gen_client.py::PAGE_SPECS["map_mineral"].observations_example`이 연도 1개뿐인데, `additional_summary.py::calculate_mineral_map_summary`는 `ValueError("mineral map summary requires at least two distinct years")`를 요구 → `report_demo.py`에서 "광물지도" 고르고 기본 placeholder 그대로 누르면 **항상 `NO_DATA`**(빈 응답). 프롬프트/계산 로직 문제가 아니라 데모 placeholder가 서버 계약을 못 채우는 문제.
3. **forecast_price — long 지평선의 기간 형식 제약이 폼에 안내되지 않음, P1.** `forecast_horizon="long"`을 고르고 기본 placeholder 형식(분기, "2026-Q1")을 그대로 쓰면 pydantic이 "long forecasts require YYYY periods"로 명시 거부하는데, `run_summary`가 이 ValidationError를 전부 `NO_DATA`로 뭉개 원인이 클라이언트에 전혀 안 보임. `report_demo.py`/`prompt_admin.py` 둘 다 `forecast_horizon`과 기간 필드를 독립 위젯으로 노출해 이 제약을 안내하지 않음.

### SC-016 재확인 — 지금도 재현됨
`indicator_composite_base`·`map_mineral_variant_production` 응답의 `## 참고` 절에 "조회기간에 한 달 또는 1년 비교값이 없어 중장기 비교를 제외했다" / "페루의 2021년 비교값이 없어..." 같은 **검증기/계산기 내부 사유 문장이 최종 응답에 그대로 노출**됨. PDF 어느 템플릿에도 이런 메타 각주가 없어 최종 문서 톤과 어긋남 — [[report_gen_skeptic_audit_260827]] SC-016 그대로 유효.

## Phase 2 — 잔여 이슈 재확인 + 품질저하 패턴 (완료)

### (A) [[report_gen_skeptic_audit_260827]] 잔여 6항목 재확인
| 항목 | 판정 | 근거 |
|---|---|---|
| NEW-1(map_mineral 연도1개→IndexError) | **해소됨** | `additional_summary.py:860-864` "2026-08-27 skeptic 감사 Pass 3 NEW-1" 주석 가드 존재 — `ValueError`→NO_DATA. curl 재현: `{"status":"NO_DATA"}`(INTERNAL_ERROR 아님) |
| NEW-2(indicator_composite 날짜1개→ValidationError) | **해소됨** | 서버 로그: "composite index summary requires observations spanning at least one week..." → ValueError→NO_DATA. curl 재현 `{"status":"NO_DATA"}` |
| 422 계약 밖 | **해소됨** | `main.py:247-259` `RequestValidationError` 핸들러가 분석요약 라우트 전부를 200+NO_DATA로 매핑(08-27 skeptic Pass 3). extra field·start>end 둘 다 확인 |
| zombie(analysis_lock) | **부분 해소, P2** | `routers/_common.py:96-130` deadline 공유+`future.cancel()`+예산 부족 시 lock 시도 자체를 안 하는 가드로 **연쇄(pile-up)는 막힘**. 단 코드 주석(28-30)이 인정하듯 **이미 시작된 in-flight LLM 호출 1건은 강제 취소 불가**(클라이언트가 중간취소 미지원) — 근본 zombie 소지 잔존 |
| SC-017(secondary_measure_observations:[] vs compare_observations:[] 비일관) | **재현 안 됨** | 둘 다 지금은 "빈 리스트=무시"로 일관 동작 확인 |
| SC-018(claims≥4 결합문장 요구 vs price_group "그대로 옮겨쓴다" 충돌) | **확인됨(재현), P1** | price_group 5광종 payload docker exec 직접호출: `llm_refined=False`, `warnings=['...검증 사유: 관련 근거를 결합한 분석 문장이 없다.']`. 공개 `{status,report}` 응답은 `status:"ok"`만 보여 **클라이언트가 규칙기반 폴백인지 LLM 정제인지 구분 불가**([[report_gen_llm_required_evidence_priority_260828]]의 "LLM 경고 필터링" 부수발견과 동일 구조) — 발주처 프롬프트 튜닝이 무력화되는 지점 |

### (B) 품질저하 패턴 추가 3건
1. **극단값(등락률 +98,900%) — 전월/전년평균 중복 라벨링, P2.** `komir_summary.py:329-341` `_avg_before(7/30/365)`가 관측치 희소(2건)일 때 30일창·365일창이 같은 단일 이전 관측치로 수렴하는데, 보고서는 이를 "전월평균(10.00) 대비..." "전년평균(10.00) 대비..."로 마치 독립 통계인 것처럼 두 문장 반복 제시. round1 "G06 구절 반복"과 결이 같은 구조적 패턴(입력이 극단값인 게 아니라 관측치가 희소하기만 해도 발생).
2. map_korea 국가 1개(CR3=100%) — **정상**. 과장된 "집중" 표현 없이 정직하게 서술.
3. indicator_supply 극단 저점(3.00점) — **정상**(문장 품질). 단 등급 임계값 자체의 정확성은 이번 조사 범위 밖(별도 확인 필요 항목으로만 남김).

## Phase 3 — 프롬프트 관리 실효성 실험 (완료)
`forecast_price` 1개 prompt_key로 4개 조합 실측(다른 page_id는 건드리지 않음 — blast
radius 최소화). 절차: 8컬럼 전체 백업 → content만 편집 → reload → 동일 payload로
호출 비교 → 원본 8컬럼 그대로 복구 → 바이트 단위 일치 확인 → reload 재호출.

| 실험 | 지시 유형 | 변화 유무 | 발췌 |
|---|---|---|---|
| 1 | 어투(완곡 어미 강제) | **예 — 어투 표면 변함** | "…경로가 제시되었습니다"→"…제시될 것으로 보입니다", "…나타났습니다"→"…판단됩니다" |
| 2 | 강조 순서(첫 어절에 방향+수치) | **거의 무변화** | core_diagnosis가 이미 "니켈 중기 예측가격은 …1.55% 상승하며…"로 방향+수치를 초반에 담고 있어 지시 추가 효과가 표면화 안 됨 — evidence 템플릿이 순서를 사실상 고정 |
| 3 | 어휘 치환("상승"→"오름세") | **예 — 어휘 표면 변함** | major_changes에 "…오름세의 시작점입니다" 등장(원본은 "상승") |
| 4 | 해석 확장(절당 문장 1개 추가 요청) | **아니오 — 거부됨(통제 밖)** | `output_contract.section_sentence_ranges`가 3절 모두 `[1,1]` 고정 — content 지시로는 못 뚫음 |

**운영자용 결론**: content 편집으로 실제 바뀌는 표면은 **어투(어미)·어휘 선택**. 문장
순서는 evidence 서술 구조가 이미 방향+수치를 앞에 배치해 지시 효과가 잘 안 보인다.
**문장 수·절 구조는 `output_contract`(JSONB, content와 별개 컬럼)가 하드 캡**이라
content로는 절대 못 바꾼다 — "스타일 튜닝은 content로, 구조 튜닝은 output_contract로"
라고 안내해야 함(현재 prompt_admin.py 화면엔 이 구분이 문서화돼 있지 않음, §다음 주
작업 목록 참고).

**복구 검증**: content·description·page_name·page_definition 전부 백업본과 바이트
단위 일치 확인 완료, 임시 파일 호스트/컨테이너 양쪽 정리 완료. DB에 남은 변경 없음.

## 종합 — 다음 주 작업 목록(우선순위순)

**P1**
1. **map_mineral 데모 placeholder가 서버 최소요건(연도 2개 이상) 미달** — `report_gen_client.py::PAGE_SPECS["map_mineral"].observations_example`을 연도 1개→2개 이상으로 교체. 지금 상태로는 요약보고서 데모에서 "광물지도" 첫 클릭이 항상 `NO_DATA`.
2. **forecast_price의 long horizon 기간 형식 제약이 폼에 미반영** — `forecast_horizon="long"` 선택 시 `start_period`/`end_period`가 연도(YYYY) 형식이어야 하는데 데모 placeholder는 분기 형식 고정. `report_demo.py`/`prompt_admin.py`가 horizon에 따라 placeholder를 분기하거나, 최소한 캡션으로 안내 필요. 근본 원인은 `run_summary`가 ValidationError를 전부 NO_DATA로 뭉개 클라이언트에 사유가 안 보이는 것(SC-018과 같은 구조).
3. **indicator_composite 대조 접속사("반면"/"-지만") 오용 — 프롬프트가 아니라 코드 버그로 확정.** docker exec로 두 샘플 모두 재검증한 결과 `llm_refined=False`(규칙기반 경로, LLM 미개입) — 즉 접속사는 LLM 출력이 아니라 `additional_summary.py`의 결정론적 문자열 조립이 만든다. 근본 원인: `_change_with_contrast()`(511번째 줄 부근)와 `_change_before_contrast()`+`반면`(560·602번째 줄, `weekly_subindex_comparison`/`monthly_subindex_comparison` claim)가 **두 값의 부호(같은 방향인지)를 비교하지 않고 항상 "-지만"/"반면"을 붙인다** — 관측치 희소(2~3개)로 주간/월간 구간이 겹치거나 두 지수가 같은 방향으로 움직일 때마다 100% 재현되는 결정론적 버그(비결정성 아님). **처방 정정**: prompt_admin.py로는 못 고친다(규칙기반 경로라 content가 관여 안 함) — `additional_summary.py`에서 두 change 값의 부호를 비교해 같으면 순접("~며"/"~고"), 다르면 역접("~지만"/"반면")을 고르는 조건 분기 추가가 맞는 처방.
4. **SC-018(재확인) — 규칙기반 폴백이 공개 응답에서 LLM 정제와 구분 불가** — price_group 5광종처럼 claims≥4일 때 검증 실패로 규칙기반 폴백이 나도 `{status:"ok"}`만 보여 운영자가 "프롬프트를 아무리 튜닝해도 안 바뀌는" 상황을 겪을 수 있음. [[report_gen_llm_required_evidence_priority_260828]] 부수발견(`report_render.py:102`가 `warning.startswith("LLM ")` 필터링)과 같은 근본 원인 — 관측성(예: 내부 디버그 헤더나 관리자 전용 필드) 추가 논의 필요.

**P2**
5. SC-016(재확인) — `## 참고` 절에 검증기/계산기 내부 사유 문장이 최종 문서에 노출(예: "조회기간에 한 달 또는 1년 비교값이 없어 중장기 비교를 제외했다"). PDF 템플릿엔 이런 메타 각주가 없어 발주처 문서 톤과 어긋남.
6. 관측치 희소 시 전월평균·전년평균이 같은 단일 이전 관측치로 수렴하는데도 두 문장으로 독립 인용(중복 라벨링). 극단값 자체보다 "관측치가 희소하기만 해도" 발생하는 구조적 패턴.
7. zombie(analysis_lock) 부분 해소 — 연쇄(pile-up)는 막혔으나 이미 시작된 in-flight LLM 호출 1건의 강제 취소는 여전히 불가(코드 주석이 인정). 심각도는 낮아졌으나 근본 해결은 아님.
8. price 계열(base/minor/iron/other) "가격 변동의 주요 요인" 절이 여전히 영구 공백([[report_gen_prompt_content_260826]] 기존 확인 갭) — 계산 레이어가 원인 분해 근거를 안 만드는 한 못 채움, 재확인만.

**해소 확인(재제안 불필요)**
- NEW-1(map_mineral IndexError), NEW-2(indicator_composite ValidationError), 422 계약 밖 — 전부 08-27 skeptic 감사 적용분이 실제로 살아있음, 코드 주석까지 확인.
- SC-017(secondary_measure_observations vs compare_observations 비일관) — 지금은 둘 다 "빈 리스트=무시"로 일관.

## 감사 방법 메모
- Phase 1~3 전부 3개의 fork 서브에이전트로 순차 실행(같은 컨테이너에 몰리면
  `analysis_lock` 경합으로 가짜 TIMEOUT이 날 수 있어 병렬 대신 순차 진행 — advisor
  자문 반영). Phase 1의 첫 시도(포크)가 13초·tool_uses 2로 아무 작업 없이 비정상
  종료돼 SendFeedback으로 제품 버그 신고 후 재시도해 정상 완료.
- 표본 26건은 `report_gen_출력품질감사_260828_samples/`에 실제 응답 JSON 그대로
  보존(재현 가능, artifact-provenance-policy 적용).
- Phase 3은 유일하게 프로덕션 DB(`ai_cfg.cfg_prompt`)를 수정하는 단계라 다른 Phase와
  분리해 마지막에 실행, 8컬럼 전체 백업→실험→원상복구→바이트 단위 일치 확인까지 완료.
- 종합 직전 advisor 재자문에서 "P1-3 처방이 LLM/규칙기반 귀속을 확인 안 함" 지적을
  받아, 세션 본인이 직접 `docker exec`로 `AnalysisSummaryService.analyze()`를 두
  샘플(base/variant) 그대로 재호출해 `llm_refined=False`를 확인하고 코드 라인
  (`additional_summary.py:511,560,602`)까지 특정 — 위 P1-3 처방을 프롬프트에서
  코드로 정정했다.

## 미커밋 상태 안내
이 감사 산출물(본 MD + `_samples/` 26건)은 워크트리 `worktree-report_gen`
(`.claude/worktrees/report_gen/`)에만 존재하며 **아직 커밋되지 않았다** — main-agent가
공유 체크아웃(`komir/documents/...`)에서 찾으면 안 보인다. 커밋/병합은 이 세션이
독단으로 하지 않았다(요청받지 않음) — 필요하면 지시할 것.

## 라운드1 수정 (2026-08-28, main-agent 지시)
main-agent가 감사 후 지시한 `inhouse/services/report_gen/**` 백엔드 4건 수정. 컨테이너
재기동 없이(main-agent 전담) git HEAD(수정 전) vs 워킹트리(수정 후) 코드를 **동일
payload로 직접 비교**해 각 수정의 실제 전후 응답 차이를 확인했다(요청 반영).

1. **[P1] `additional_summary.py:511,560,602` 대조 접속사 오용 — 수정 완료.**
   `_same_direction()`으로 두 change 값의 부호를 비교해 같으면 순접(`_change_verb_
   conjunctive`/`_change_before_conjunctive`, "-며"/"-고"), 다르면 기존 역접("-지만"/
   "반면")을 쓰도록 분기. Phase1 샘플 payload 그대로 재현:
   - base(메이저·희소 둘 다 하락): BEFORE `"...0.81% 내린 반면 희소금속지수는 0.80%
     내렸다"` → AFTER `"...0.81% 내리고 희소금속지수는 0.80% 내렸다"`.
   - variant(전주=전월 동일값 1.96%): BEFORE `"...전주보다 1.96% 내렸지만 한 달
     전보다 1.96% 내렸다"` → AFTER `"...전주보다 1.96% 내리며 한 달 전보다 1.96%
     내렸다"`.
   - 회귀 확인(방향이 실제로 다른 경우, 메이저 상승/희소 하락): BEFORE·AFTER 동일하게
     `"...5.00% 오른 반면 희소금속지수는 5.00% 내렸다"` — 정상 대조는 그대로 유지됨.
2. **[P1, 범위 한정] SC-018 — 내부 전용 개선만(공개 계약 불변).** `report_render.py`에
   매 요청마다 `llm_refined` 값을 구조화 INFO 로그로 남기도록 추가(기존엔 폴백
   경고가 있을 때만 로그가 남아 "로그 없음=성공"을 신뢰할 수 없었음). price_group
   재현 payload(5광종, 검증 실패 폴백)로 확인: AFTER는
   `"분석요약 완료 ... llm_refined=False"` INFO 라인이 항상 남고, 공개 `report`
   텍스트에는 BEFORE·AFTER 모두 `llm_refined` 단서 없음(계약 불변 확인). **근본
   해결(공개 계약에 `llm_refined` 필드 추가)은 이 세션이 임의 결정하지 않음 — 다음
   주 논의 필요 항목으로 남김.**
3. **[P2] SC-016 — `## 참고` 절 완화, 완료(제거 선택).** PDF 템플릿 어디에도 이런
   메타 각주가 없어 톤이 어긋난다는 지적에 따라 데이터 결측 경고를 독자용
   렌더링에서 전부 제거(서버 WARNING 로그로는 유지, 운영 관측성 보존).
   indicator_composite 재현: BEFORE는 본문 끝에 `"## 참고\n\n- 조회기간에 한 달
   또는 1년 비교값이 없어 중장기 비교를 제외했다."`가 남았고, AFTER는 이 절 자체가
   사라짐(다른 절 내용은 완전히 동일).
4. **[P2] `komir_summary.py` `_avg_before` 중복 라벨링 — 수정 완료.** `_avg_before`가
   평균값과 함께 그 계산에 쓰인 관측일 집합을 돌려주도록 바꾸고, 이미 같은
   관측일 집합으로 인용한 기간이 있으면 건너뛰도록(가장 짧은 기간만 남김) 수정.
   재현(관측치 2건, 이전 관측치가 전주·전월·전년 창 전부에 포함): BEFORE는
   `week_avg`·`month_avg`·`year_avg` 3개 클레임이 전부 `"...(10.00) 대비
   +98,900.00% 수준이다"`로 동일 문구 반복 → AFTER는 `week_avg` 1개만 남음
   (key_metrics도 3행→1행).

**검증**: 4개 파일 전부 `py_compile` 통과. `scripts/komis_dump_smoke_test.py`(실
KOMIS 덤프 384콤보, `AnalysisSummaryService(llm=None)` 결정론적 경로) 로컬 재실행 —
수정과 무관한 6개 page_id(indicator_composite/market/supply, map_korea/global/mineral,
합 326콤보) 전부 `ok`·`internal_error 0`·`mismatches 0`(회귀 없음 확인). `price`
그룹(58콤보)은 스크립트가 2026-08-27 이전 폐기된 단일 `page_id="price"`를 아직
써서 전부 `INTERNAL_ERROR`(pydantic 리터럴 검증 실패)였는데, **이 세션의 수정과
무관한 기존 스크립트 노후화**임을 직접 확인(`AnalysisSummaryRequest(page_id="price",
...)`가 워킹트리 코드에서도 즉시 같은 `ValidationError`를 던짐, 즉 내 수정 이전
부터 있던 문제) — 코드 수정은 지시받은 4건 범위 밖이라 손대지 않고 기록만 남김.

**커밋**: 이 라운드1 수정은 워크트리에 별도 커밋으로 남긴다(감사 문서 커밋과 분리).
