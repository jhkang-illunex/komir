# Behavioral Reference V1 / Product Golden 분리 감사 — 2026-10-03

## 1. 최종 결정

| 항목 | 판정 | 범위 |
|---|---|---|
| Behavioral Reference V1 | **READY** | Golden979fd3… + Step0 고정 snapshot/runtime + 저장된 boundary evidence를 사용하는 **bounded Aggregate old/new differential** 기준 |
| Certified Product Golden | **NOT_CERTIFIED_WITH_KNOWN_REASONS** | 기존21/57, 후보8/57 중 어느 것도 재인증/새 score로 승격하지 않음 |
| Step1 기술적 readiness | **GO** | 다음 승인 작업에서 동일 입력 Golden/candidate 사전대조 gate를 만족하는 행동 보존형 Aggregate 추출에 한정 |
| 이번 실행/승인 상태 | **계속 보류, 미착수** | GO는 준비성 권고이지 사용자의 착수 보류를 해제하거나 migration을 실행했다는 뜻이 아님 |
| 환경 인과 | **ENVIRONMENT_DRIFT_PRESENT_BUT_CAUSALITY_UNPROVEN** | PostgreSQL/vector 차이 존재, 4개 응답 차이 원인으로 미입증 |

**READY는 과거21개의 product 정답성을 승인하거나, 모든 내부 호출을 완전히 관측했다는 선언이 아니다.** 관측되지 않은 사항은 아래처럼 UNKNOWN으로 동결한다. 향후 candidate 승격에서는 같은 Golden 코드를 같은 저장 입력으로 실행하여 부족한 비교 지표도 양쪽에서 측정해야 한다.

iterative-audit 적용 범위: HIGH(출처·인증 의미), 1회 read-only 감사. 증거 조사→정적 비교→읽기 전용 독립 검토→새 artifact 저장. 기능 코드/QA oracle/원천/DB version/prompt/renderer 수정0, QA 및 regression 재실행0, rebuild0, 18002 변경0.

## 2. 두 축의 정의와 authoritative owner

### Behavioral Reference V1

목적은 **이전 구현과 refactor 구현의 행동 동등성**이다. 입력과 출력이 업무적으로 틀렸거나 오염되어도 그것을 숨기지 않고 known-invalid/known-contamination 표식과 함께 보존한다.

| 경계 | 반드시 보존할 내용 | 증거/비교 방법 |
|---|---|---|
| 요청/응답 | 원문·payload·raw answer·final tables/charts/citations | Step0 raw57, SSE57; 출력 순서 포함 |
| TypedResult | value/type/metric/entity/period/unit/criterion/cardinality | 노드별 canonical JSON fingerprint, scalar type/null/배열순서 유지 |
| 실행 상태 | status/warnings/failure/sufficient/abstain | typed run/node/SSE 상태를 각각 비교, 서로 덮어쓰지 않음 |
| provenance | source/action/evidence/caveat/metadata/lineage | source branch별123기록 및 원본 evidence hash |
| 그래프 | node/root/input/dependency identity, selectors | 고정 AST 기준 동일성; 비교 편의를 위해 node ID를 일괄 제거하지 않음 |
| selection | action/capability/args/repair | parser trace53개 QA, 관측 ActionCall56건, coverage trace |
| 호출 | action/function/provider/retry 횟수 | 저장된 action trace count와 실제 backend count를 분리; 미관측은 UNKNOWN |
| SSE | ordered event payload, done/abstain/citations | 이번57 stream 보존. 세션 ID를 제외한 비교 hash도 별도 저장 |

소유권: **sealed Step0 artifacts + Golden commit의 실행 코드 + 이 문서의 비교 계약**. 과거 PASS 라벨이나 수동 점수표가 runtime behavior의 source of truth가 아니다.

### Certified Product Golden

목적은 **제품 관점의 정답성**이다. 위 행동 비교 외에 허용 provenance, source validity, semantic correctness, evidence relevance, completeness, no wrong-confident를 독립 검증해야 한다.

현재 상태는 NOT_CERTIFIED_WITH_KNOWN_REASONS. 알려진 이유:

- 최종 결과에 실제 기여한 dummy source와 그 경고 미표시.
- 출처가 확인되지 않는 행/문서.
- REG04의 연간 요구→최근60행 평균, GM04의 국가별 수입 요구→제품/세계무역 문서 등 completeness 문제.
- 이전 authoritative와 Step0 사이 환경/snapshot/dirty-source 동일성 미인증.

provenance-clean 자체도 semantic correctness와 동의어가 아니다. 이번 감사는 기존 oracle을 설치·수정·재채점하지 않았다. Strict21/57 및 Answerable21/53은 **과거 공식 측정값**으로 남지만 Certified Golden이라고 부르지 않는다.

## 3. Evidence identity / 관측 범위

- Golden branch/commit: multihop_work / `979fd3f980bb10af74a218cc6e07bada110e76de`.
- Step0 app image ID: `sha256:a4fbcf8ee2f65b9869ef9fbb79d2ab60ea9dbc5fb98978ec0660949a8a3a2f0c`.
- Parent evidence root: `/home/nuri/.codex/validation-evidence/golden-v1-step0-20261003`.
- Parent manifest SHA256: `de52ec92d7533698b38a0650df76cacc8cf5933e3d3379269640f3008c82e80b`.
- 이번에 parent108파일의 **실제 bytes/hash 전체 재검증, mismatch0**. image/source/DB archive도 포함.
- New evidence root: `/home/nuri/.codex/validation-evidence/behavioral-reference-v1-20261003`.
- New manifest SHA256: `852bafa78a12ed583c5ae7d8fbfb4ba9b2c2534efff5cfe674a3cb1f33231c67`.
- New bundle79파일: per-QA fingerprints/parser extracts, branch provenance, 21 contamination matrix, Aggregate actual input/output, read-only query evidence, reference contract, 수집 script.
- 파일0400/root0700의 content-addressed seal. WORM 저장장치나 root 사용자의 물리적 변경 불가능성을 주장하지 않는다.
- 새 문서는 기존 Golden/QA/Step0 artifact를 덮어쓰지 않는다.

### 완전성 및 한계

- raw answers57, SSE streams57.
- persisted history39행 중 **실제 result map37개**. 나머지2개는 null result이고, 전체57의 모든 TypedResult가 저장됐다고 부르지 않는다.
- parser trace53개 QA, 로깅된 ActionCall56건. Direct/static/실행 이전 실패의 기록 유무를 각각 유지.
- 과거 authoritative raw에는 complete SSE events/TypedResult/AAST가 없고 debug=[]이다. 따라서 과거→현재 내부 graph parity는 미입증.
- MI02는 ActionCall log0이어도 document output이 있다. **log0 ≠ 실제 backend call0**.
- 실제 SQL/MCP/LLM 총 호출·retry 수는 UNKNOWN. 저장된 step 결과 map으로 실행 횟수를 추정하지 않는다.
- 새 fingerprint는 JSON object key만 정렬한다. 리스트순서/숫자와 문자열 차이/null/unit/date/provenance는 유지한다. SSE 비교본의 top-level session_id만 제외하고 raw본은 그대로 보존.
- latency/UUID의 비결정성은 업무 시계열 date/as-of를 무시할 근거가 아니다.

## 4. 53 identical + 4 changed

| 관측 | 수 |
|---|---:|
| answer 문자열 IDENTICAL |53|
| SEMANTICALLY_EQUIVALENT(MP04, 아래 한정) |1|
| RESPONSE_DRIFT |3|
| 이번 자료로 새롭게 MODEL_FLAKY 확정 |0|
| 이번 자료로 DATA_DRIFT 인과 확정 |0|
| old/new terminal JSON 동일 |50|
| old/new complete SSE parity |UNKNOWN|

답변이 같은 **MP01/MP03/MP09/GM02도 terminal.citations는 다르다**. 그러므로53/57을 전체 pipeline 행동 동등성으로 확대하지 않는다. 이번 새 참조의 기준점은 historical raw가 아니라 **Golden SHA의 Step0 실행 evidence**이다.

### 변경4건의 최초 관측 divergence

| QA | 과거→현재 | 현재 실행에서 확인한 경계 | 원인 입증 한계 |
|---|---|---|---|
| MI02 | 초합금 FCC/고온 강도 근거→EV/ESS 수요 근거 | document.retrieve의 최종 근거 선택/본문이 다름; 현재 concept/topic=니켈의 특성 | old 후보문서/typed 없으므로 retrieval·model·source·code 원인 UNKNOWN |
| IX02 | 가격/지수 side_by_side 표→semantic_plan_incomplete 기권 | parser input metric_fields.indicator에 series 허용, validator는 requested_output_not_produced:series; 3attempt 반복 | **현재 field 계약 충돌**은 입증. old AAST 없으므로 신규 code regression/모델 비결정성 원인 미입증 |
| MP04 | node 표 제목2개 변경 | 60행 가격표·projection_field_unavailable:year·부분응답은 모두 동일 | 내용은 SEMANTICALLY_EQUIVALENT. ID 변경 원인은 UNKNOWN; 같은 고정 AST refactor 검사에서는 ID를 무시하면 안 됨 |
| GM04 | Li/Ni/Co 표 동일; Mn 표 배치/흑연 물성 열·인용16→17 | typed country_share에 제품설명/세계무역 문서 표가 들어감 | old부터 한국 수입 branch 일부 미충족. old 내부자료 없어 retrieval/extraction/render 최초 변화 원인 UNKNOWN |

MP04 정확한 제목 변경:

- project_nickel_price → node_nickel_price_proj
- project_production_yoy → node_nickel_prod_yoy_proj

4건 모두 **old→new 직접 비교로 처음 관측 가능한 경계는 final response**이다. 현재 내부 원인을 찾았다는 사실과 과거 대비 최초 원인을 입증했다는 사실은 다르다.

### 원인 축별 결론

| 축 | 확인 | 미확인 |
|---|---|---|
| code | 과거fa423…+dirty, 현재Golden979fd3…; 현재 IX02 계약충돌 | 특정 코드차이가 응답 차이를 유발했는지 |
| model | 현재Gemma/parser output/repair 흔적 | 동일 입력·동일 model에서 반복 변동인지 |
| source data | MI02/GM04 인용 선택 차이 | 과거 snapshot/query 후보·순위가 같았는지 |
| environment | PostgreSQL16.14→16.15, vector0.8.2→0.8.7 | 해당 버전차이의 causal effect |
| temporal | 실행 시각/relative period 존재 | 상대시각이 4개 차이 원인인지; MP04 값은 동일 |
| oracle | GM04 과거PASS와 실제 내용의 충돌 | oracle이 raw response 차이를 일으켰다는 주장(근거 없음) |

독립 read-only reviewer도 동일 범위와 한계를 확인했다. QA/테스트 재실행으로 원인을 추가 추정하지 않았다.

## 5. QA57 provenance inventory

약어/분류의 정확한 의미:

- VERIFIED_RESOURCE: Golden 편집형 resource의 source_verified=true 및 실제 소비 확인. 이번 인터넷 원문 재감사를 뜻하지 않음.
- VERIFIED_SAMPLE: KOMIS_SAMPLE source와 선택 행 연결 확인. 전 제품 production 인증과 다름.
- STATIC_RESOURCE: 관측자료가 아닌 versioned help/navigation/definition. source provenance는 non-observational N/A.
- DEV_DUMMY: 원장/forecast model_ver 등 실제 개발용 source 확인.
- DEV_DUMMY_WAS: 원천 등록자 marker, **정확한 natural key의 dummy 원장과 대조**한 가격 source.
- DUMMY_LOAD: 원천 creator/modifier marker. 이름만으로 합성 값이라고 결론내리지 않으며 lifecycle UNKNOWN.
- UNKNOWN: 게시/문서 경로/마스터 caveat는 있으나 row-level 허용 provenance를 확정하지 못함.
- MIXED: 원장-confirmed dummy와 그 외 상태가 같은 population/branch에 존재. 그 외를 자동 production으로 취급하지 않음.
- SOURCE_UNAVAILABLE_IN_TRACE: 이 실행에서 성공 source/evidence가 미관측. **실제 원천 데이터 부재 판정이 아님**.

각 branch별 source/evidence hash·metric/entity/period/unit/result type·consumer node는 새 bundle의 `qa57_branch_provenance.json` **123기록**에 보존했다. 아래 문서 표는 같은 branch의 여러 문서경로를 묶었고, 전체 물리 경로는 JSON/원본에 있다. Content Status는 Step0 진단 인용이며 이번 새 score가 아니다.

| QA | Source / Action / branch | Provenance | Content Status | Previous Strict | Answer parity |
|---|---|---|---|---|---|
| MI01 | semantic_concept_retrieve_0: document.retrieve ← Royal Society of Chemistry | VERIFIED_RESOURCE | Step0 내용 후보(미인증) | PASS | IDENTICAL |
| MI02 | semantic_concept_retrieve_0: document.retrieve ← 문서(원 경로 보존) | UNKNOWN | Step0 미충족/미인증 | NON-PASS | RESPONSE_DRIFT |
| MI03 | semantic_concept_retrieve_0: document.retrieve ← Royal Society of Chemistry | VERIFIED_RESOURCE | Step0 내용 후보(미인증) | PASS | IDENTICAL |
| MI04 | semantic_concept_retrieve_0: document.retrieve ← Royal Society of Chemistry | VERIFIED_RESOURCE | Step0 내용 후보(미인증) | PASS | IDENTICAL |
| DOC02 | doc_retrieve_monthly_trend: document.retrieve ← source 미기록 | SOURCE_UNAVAILABLE_IN_TRACE | Step0 미충족/미인증 | NON-PASS | IDENTICAL |
| DOC04 | N/A: 정적/미관측 ← source 미기록 | STATIC_RESOURCE | Step0 내용 후보(미인증) | PASS | IDENTICAL |
| NEWS01 | semantic_document_retrieve_0: document.retrieve ← public.ai_daynews_raw | UNKNOWN | Step0 내용 후보(미인증) | PASS | IDENTICAL |
| NEWS03 | semantic_document_retrieve_0: document.retrieve ← public.ai_daynews_raw | UNKNOWN | Step0 미충족/미인증 | NON-PASS | IDENTICAL |
| PF01 | retrieve_nickel_price_current: price.series ← public.KO_MNRL_PRC<br>retrieve_nickel_price_forecast: forecast.price ← public.AI_MNRL_PRC_FRCST | DEV_DUMMY_WAS, DEV_DUMMY | Step0 미충족/미인증 | NON-PASS | IDENTICAL |
| PF02 | N/A: 정적/미관측 ← source 미기록 | SOURCE_UNAVAILABLE_IN_TRACE | Step0 미충족/미인증 | NON-PASS | IDENTICAL |
| PF03 | retrieve_current_price: price.series ← public.KO_MNRL_PRC<br>retrieve_forecast_price: forecast.price ← public.AI_MNRL_PRC_FRCST | DEV_DUMMY_WAS, DEV_DUMMY | Step0 미충족/미인증 | NON-PASS | IDENTICAL |
| IX01 | N/A: 정적/미관측 ← source 미기록 | SOURCE_UNAVAILABLE_IN_TRACE | Step0 미충족/미인증 | NON-PASS | IDENTICAL |
| IX02 | N/A: 정적/미관측 ← source 미기록 | SOURCE_UNAVAILABLE_IN_TRACE | Step0 미충족/미인증 | NON-PASS | RESPONSE_DRIFT |
| MP01 | node_trade_rank: trade.country_rank ← public.KO_CSTM_CMMRC<br>node_trade_rank: trade.country_rank ← 문서(원 경로 보존)<br>node_price_series: price.series ← public.KO_MNRL_PRC | UNKNOWN, DEV_DUMMY_WAS, DUMMY_LOAD | Step0 미충족/미인증 | PASS | IDENTICAL |
| MP03 | node_import_val: trade.country_rank ← public.KO_CSTM_CMMRC<br>node_import_val: trade.country_rank ← 문서(원 경로 보존)<br>node_price_current: price.series ← public.KO_MNRL_PRC | UNKNOWN, DEV_DUMMY_WAS, DUMMY_LOAD | Step0 미충족/미인증 | PASS | IDENTICAL |
| MP04 | node_nickel_price: price.series ← public.KO_MNRL_PRC<br>node_nickel_prod: resource.yoy ← source 미기록 | DEV_DUMMY_WAS, DUMMY_LOAD, SOURCE_UNAVAILABLE_IN_TRACE | Step0 미충족/미인증 | NON-PASS | SEMANTICALLY_EQUIVALENT |
| MP05 | N/A: 정적/미관측 ← source 미기록 | SOURCE_UNAVAILABLE_IN_TRACE | Step0 미충족/미인증 | NON-PASS | IDENTICAL |
| MP06 | node_price_nickel: price.series ← public.KO_MNRL_PRC<br>node_concept_nickel: document.retrieve ← Royal Society of Chemistry | DEV_DUMMY_WAS, VERIFIED_RESOURCE | Step0 미충족/미인증 | PASS | IDENTICAL |
| MP07 | retrieve_strategic_prices: price.overview ← public.KO_MNRL_PRC | DEV_DUMMY_WAS | Step0 미충족/미인증 | PASS | IDENTICAL |
| MP09 | node_doc_trend: document.retrieve ← 문서(원 경로 보존)<br>node_price_series: price.series ← public.KO_MNRL_PRC | UNKNOWN, DEV_DUMMY_WAS, DUMMY_LOAD | Step0 미충족/미인증 | NON-PASS | IDENTICAL |
| CN01 | N/A: 정적/미관측 ← source 미기록 | SOURCE_UNAVAILABLE_IN_TRACE | Step0 미충족/미인증 | NON-PASS | IDENTICAL |
| CN04 | N/A: 정적/미관측 ← source 미기록 | SOURCE_UNAVAILABLE_IN_TRACE | Step0 미충족/미인증 | NON-PASS | IDENTICAL |
| CN05 | N/A: 정적/미관측 ← source 미기록 | SOURCE_UNAVAILABLE_IN_TRACE | Step0 미충족/미인증 | NON-PASS | IDENTICAL |
| CN07 | node_news_retrieval: document.retrieve ← public.ai_daynews_raw<br>node_price_forecast: forecast.price ← public.AI_MNRL_PRC_FRCST | UNKNOWN, DEV_DUMMY | Step0 미충족/미인증 | NON-PASS | IDENTICAL |
| CN08 | node_index_retrieve: indicator.series ← public.KO_MNRL_SNTHS_INDX<br>node_doc_retrieve: document.retrieve ← source 미기록 | UNKNOWN, SOURCE_UNAVAILABLE_IN_TRACE | Step0 미충족/미인증 | NON-PASS | IDENTICAL |
| CN09 | N/A: 정적/미관측 ← source 미기록 | SOURCE_UNAVAILABLE_IN_TRACE | Step0 미충족/미인증 | NON-PASS | IDENTICAL |
| GM01 | node_kr_import_retrieve: trade.country_rank ← public.KO_CSTM_CMMRC<br>node_kr_import_retrieve: trade.country_rank ← 문서(원 경로 보존)<br>node_world_prod_retrieve: resource.rank ← public.KO_RSRC_PRDCTN_QUTY | UNKNOWN, DEV_DUMMY, MIXED | Step0 미충족/미인증 | NON-PASS | IDENTICAL |
| GM02 | retrieve_prod_lithium: resource.rank ← public.KO_RSRC_PRDCTN_QUTY<br>retrieve_import_lithium_kr: trade.country_rank ← public.KO_CSTM_CMMRC<br>retrieve_import_lithium_kr: trade.country_rank ← 문서(원 경로 보존) | DEV_DUMMY, MIXED, UNKNOWN | Step0 미충족/미인증 | PASS | IDENTICAL |
| GM04 | tr_cobalt: trade.country_rank ← public.KO_CSTM_CMMRC<br>tr_cobalt: trade.country_rank ← 문서(원 경로 보존)<br>tr_nickel: trade.country_rank ← public.KO_CSTM_CMMRC<br>tr_nickel: trade.country_rank ← 문서(원 경로 보존)<br>tr_lithium: trade.country_rank ← public.KO_CSTM_CMMRC<br>tr_lithium: trade.country_rank ← 문서(원 경로 보존)<br>tr_graphite: trade.country_rank ← 문서(원 경로 보존)<br>tr_manganese: trade.country_rank ← 문서(원 경로 보존) | UNKNOWN | Step0 미충족/미인증 | PASS | RESPONSE_DRIFT |
| GM05 | node_1: document.retrieve ← Royal Society of Chemistry<br>node_3: trade.country_rank ← 문서(원 경로 보존) | VERIFIED_RESOURCE, UNKNOWN | Step0 미충족/미인증 | NON-PASS | IDENTICAL |
| GM08 | node_usage: document.retrieve ← Royal Society of Chemistry<br>node_production: resource.rank ← public.KO_RSRC_PRDCTN_QUTY | VERIFIED_RESOURCE, VERIFIED_SAMPLE | Step0 내용 후보(미인증) | PASS | IDENTICAL |
| GM11 | node_trade_retrieve: trade.country_rank ← 문서(원 경로 보존)<br>node_res_retrieve: resource.rank ← source 미기록 | UNKNOWN, SOURCE_UNAVAILABLE_IN_TRACE | Step0 미충족/미인증 | NON-PASS | IDENTICAL |
| GM12 | N/A: 정적/미관측 ← source 미기록 | SOURCE_UNAVAILABLE_IN_TRACE | Step0 미충족/미인증 | NON-PASS | IDENTICAL |
| GM13 | node_price_cobalt: price.series ← public.KO_MNRL_PRC<br>node_trade_rank_cobalt_kr: trade.country_rank ← public.KO_CSTM_CMMRC<br>node_trade_rank_cobalt_kr: trade.country_rank ← 문서(원 경로 보존)<br>node_resource_rank_cobalt_world: resource.rank ← public.KO_RSRC_PRDCTN_QUTY | DEV_DUMMY_WAS, UNKNOWN, DEV_DUMMY, MIXED | Step0 미충족/미인증 | NON-PASS | IDENTICAL |
| GM14 | N/A: 정적/미관측 ← source 미기록 | SOURCE_UNAVAILABLE_IN_TRACE | Step0 미충족/미인증 | NON-PASS | IDENTICAL |
| REG02 | node_2: price.series ← public.KO_MNRL_PRC | DEV_DUMMY_WAS, DUMMY_LOAD | Step0 미충족/미인증 | PASS | IDENTICAL |
| REG03 | current_price: price.series ← public.KO_MNRL_PRC | DEV_DUMMY_WAS | Step0 미충족/미인증 | PASS | IDENTICAL |
| REG04 | retrieve_nickel_price: price.series ← public.KO_MNRL_PRC | DEV_DUMMY_WAS, DUMMY_LOAD | Step0 미충족/미인증 | PASS | IDENTICAL |
| REG05 | node_2: inventory.latest ← public.ko_mnrl_prc + public.ko_mnrl_prc_crtr | DUMMY_LOAD, UNKNOWN | Step0 미충족/미인증 | PASS | IDENTICAL |
| REG06 | retrieve_nickel: price.series ← public.KO_MNRL_PRC<br>retrieve_tungsten: price.series ← source 미기록 | DEV_DUMMY_WAS, DUMMY_LOAD, SOURCE_UNAVAILABLE_IN_TRACE | Step0 미충족/미인증 | NON-PASS | IDENTICAL |
| ADD01 | retrieve_lithium_price: price.series ← public.KO_MNRL_PRC | DEV_DUMMY_WAS | Step0 미충족/미인증 | NON-PASS | IDENTICAL |
| ADD03 | N/A: 정적/미관측 ← source 미기록 | SOURCE_UNAVAILABLE_IN_TRACE | Step0 미충족/미인증 | NON-PASS | IDENTICAL |
| ADD06 | N/A: 정적/미관측 ← source 미기록 | SOURCE_UNAVAILABLE_IN_TRACE | Step0 미충족/미인증 | NON-PASS | IDENTICAL |
| ADD12 | N/A: 정적/미관측 ← source 미기록 | SOURCE_UNAVAILABLE_IN_TRACE | Step0 미충족/미인증 | NON-PASS | IDENTICAL |
| ADD15 | retrieve_reserves: resource.rank ← public.KO_RSRC_BURUDG_QUTY<br>retrieve_production: resource.rank ← public.KO_RSRC_PRDCTN_QUTY | UNKNOWN, DEV_DUMMY, MIXED | Step0 미충족/미인증 | PASS | IDENTICAL |
| ADD16 | node_chile_reserves: resource.rank ← public.KO_RSRC_BURUDG_QUTY<br>node_world_reserves: resource.rank ← public.KO_RSRC_BURUDG_QUTY | UNKNOWN | Step0 미충족/미인증 | NON-PASS | IDENTICAL |
| ADD18 | N/A: 정적/미관측 ← source 미기록 | SOURCE_UNAVAILABLE_IN_TRACE | Step0 미충족/미인증 | NON-PASS | IDENTICAL |
| ADD25 | retrieve_cobalt: price.series ← public.KO_MNRL_PRC<br>retrieve_copper: price.series ← public.KO_MNRL_PRC<br>retrieve_nickel: price.series ← public.KO_MNRL_PRC | DEV_DUMMY_WAS, DUMMY_LOAD | Step0 미충족/미인증 | NON-PASS | IDENTICAL |
| ADD27 | retrieve_nickel_price: price.series ← public.KO_MNRL_PRC | DEV_DUMMY_WAS, DUMMY_LOAD | Step0 미충족/미인증 | PASS | IDENTICAL |
| ADD32 | N/A: 정적/미관측 ← source 미기록 | SOURCE_UNAVAILABLE_IN_TRACE | Step0 미충족/미인증 | NON-PASS | IDENTICAL |
| ADD38 | retrieve_price_data: price.series ← source 미기록 | SOURCE_UNAVAILABLE_IN_TRACE | Step0 미충족/미인증 | NON-PASS | IDENTICAL |
| ADD40 | doc_retrieval: document.retrieve ← 문서(원 경로 보존)<br>price_forecast_retrieval: forecast.price ← public.AI_MNRL_PRC_FRCST | UNKNOWN, DEV_DUMMY | Step0 미충족/미인증 | NON-PASS | IDENTICAL |
| ADD45 | N/A: 정적/미관측 ← source 미기록 | SOURCE_UNAVAILABLE_IN_TRACE | Step0 미충족/미인증 | NON-PASS | IDENTICAL |
| ADD46 | N/A: 정적/미관측 ← source 미기록 | SOURCE_UNAVAILABLE_IN_TRACE | Step0 미충족/미인증 | NON-PASS | IDENTICAL |
| ADD47 | N/A: 정적/미관측 ← source 미기록 | STATIC_RESOURCE | Step0 내용 후보(미인증) | PASS | IDENTICAL |
| ADD48 | N/A: 정적/미관측 ← source 미기록 | STATIC_RESOURCE | Step0 내용 후보(미인증) | PASS | IDENTICAL |
| ADD49 | retrieve_copper_price: price.series ← public.KO_MNRL_PRC | DEV_DUMMY_WAS | Step0 미충족/미인증 | PASS | IDENTICAL |

## 6. 기존 PASS21 contamination matrix

**집계: provenance-clean7 / contaminated11 / unknown3.**

clean7은 **로컬에서 출처가 검증된 resource/sample 또는 관측 원천을 사용하지 않는 정적 응답**이다. 외부 원문/전체 제품 정답 인증 숫자가 아니다. 같은 기준으로 unknown3을 clean에 더하지 않는다.

| QA | 판정 | 최종 답변에 실제 기여 | trace-only/혼합 구분 |
|---|---|---|---|
| MI01 | CLEAN | source_verified RSC YAML 용도→최종 응답 | price/trade source 사용 없음 |
| MI03 | CLEAN | RSC YAML Cu/29/특성→최종 응답 | 관측 source 없음 |
| MI04 | CLEAN | RSC YAML 망간 광석→최종 응답 | 관측 source 없음 |
| DOC04 | CLEAN(N/A) | 검색 기간/검색어 정적 resource | 원천 관측값 없음 |
| NEWS01 | UNKNOWN | ai_daynews_raw 게시기사5개 제목→최종 목록 | ai_news dummy table과 다름; 원문 URL/ingestion 인증 미확정 |
| MP01 | CONTAMINATED | price502/20261002/24310.4가 최종 시계열에 기여 | trade master caveat는 row 증거 아님; price가 오염 확정 |
| MP03 | CONTAMINATED | 위 가격행 포함 다수행 current-price 표 | trade는 별도 UNKNOWN, 가격에 확정 dependency |
| MP06 | CONTAMINATED | 최신가격24310.4가 최종 출력 | RSC clean + dummy price MIXED |
| MP07 | CONTAMINATED | 16행 중9 available, dev_dummy 행의 니켈24310.4 등 표시 | unavailable7행과 혼재. 공란은 생성값으로 간주하지 않음 |
| GM02 | CONTAMINATED | 중국의 production27376이 top5 선택→intersection 중국에 기여 | 중국행 ledger확인; trade source는 row dummy 미확인 |
| GM04 | UNKNOWN | Li/Ni/Co 집계 및 Mn/graphite 문서 출력 | 선택 무역 HS·기간3164행의 dummy ledger일치0. 광종 caveat만으로 contamination 확정 금지 |
| GM08 | CLEAN | RSC 용도 + KOMIS_SAMPLE 텅스텐 생산행67000 등 | 선택 생산행과 sample source 확인, dummyledger0 |
| REG02 | CONTAMINATED | last 결과24310.4가 정확히 DEV_DUMMY_WAS row | 단순 upstream 경고만이 아니라 selected endpoint 의존 |
| REG03 | CONTAMINATED | 같은 최신행 출력; 공식 데이터라고 서술 | provenance와 최종 신뢰표시 충돌 |
| REG04 | CONTAMINATED | 60행 평균에 원장 확인 dummy 가격행 포함 | 집계 파생 오염; historical 일부행은 UNKNOWN |
| REG05 | UNKNOWN | source502/20260908/inventory272380과 최종 일치 | DUMMY_LOAD creator, ledger없음; loader 의미/생성법 미확정 |
| ADD15 | CONTAMINATED | production 중국24320/호주13680이 최종 순위에 기여 | reserves RI001 선택행에는 dummyledger 없음; 양쪽 모두 dummy라고 단정 금지 |
| ADD27 | CONTAMINATED | 261행 series/chart에 확인된 dummy row 포함 | history의 모든 행이 dummy라는 뜻 아님 |
| ADD47 | CLEAN(N/A) | versioned messages.yml 정의/기존 출처 표기 | 관측 source 없음 |
| ADD48 | CLEAN(N/A) | versioned 지원범위/help text | 관측 source 없음 |
| ADD49 | CONTAMINATED | copper501/20261002/12087.43과 final 일치 | 정확한 ledger와 등록자 교차 확인 |

### Step0의 보수적 경고 집계와 구별

“기존PASS12개에 dummy caveat 존재”라는 관측은 그대로 유효하다. 하지만 그것이 **12개 모두의 최종 값이 dummy-generated임을 증명하지는 않는다**. 특히 GM04를 이번에는 UNKNOWN으로 분리한다. REG05도 marker와 최종값의 연결은 확인했지만 의미가 확인된 dummy code와 동치로 처리하지 않는다.

새 contamination11은 그중 실제 결과 의존을 확인한 수다. 이것이 GM04/REG05를 product PASS로 승격한다는 뜻은 아니다.

- price: serial501/502/503의 DEV_DUMMY_WAS 행은 각각20/18/20개가 정확한 원장 key에 일치. 원장 `src_cd=DEV_DUMMY`, load_id=DEV_DUMMY_WAS_WEEKLY.
- 가격 natural key는 **serial|date|status**. status를 누락한 초도 read-only 탐색은 match0을 반환했으므로 최종 증거에서는 schema를 확인하고 full key로 다시 대조했다. source 없음으로 오판하지 않았다.
- REG05의502|20260908|Y는 원장 연결 없음. DUMMY_LOAD의 creator뿐 아니라 기존 가격행 modifier에도 사용된 이력이 존재한다.
- GM02 China27376 및 ADD15 China24320은 production natural key의 DEV_DUMMY ledger와 값이 일치.
- trade3164는 세 광종 HS population membership 기준 합계로, 전체 table row count가 아니다. 그 조회 범위에 ledger-match0인 사실만 주장하며 전체 무역 source의 무오염을 보증하지 않는다.
- reserves의 RI001과 DEV category는 별개 row identity. 광종master 경고를 모든 reserve 행의 확정 source label로 복사하지 않는다.

## 7. Dummy taxonomy와 lifecycle / 제안 policy

| 실제 marker | 사용 위치·관측 lifecycle | 확인 범위 | 제안 certification policy |
|---|---|---|---|
| DEV_DUMMY | ai_mnrl_mst.ko_data_src_cd, ai_dev_dummy_load.src_cd, forecast.model_ver | master rm은 개발용·공단 실샘플 아님을 명시. row ledger는 source key/load_id/time 보유. forecast snapshot360행은 해당model_ver | row/model에 직접 연결되면 FORBIDDEN. master-only는 selected row를 확인하기 전 UNKNOWN |
| DEV_DUMMY_WAS | KO_MNRL_PRC.frst_rgtr_id | exact key가 DEV_DUMMY_WAS_WEEKLY load의 DEV_DUMMY src와 연결. 여러 적재 시각의 추가행 관측 | 확인된 해당행 FORBIDDEN. WAS 약어 의미/생성 알고리즘은 추정하지 않음 |
| DUMMY_LOAD | KO_MNRL_PRC.frst_rgtr_id 또는 last_mdfr_id | 최초 삽입 및 기존행 수정 actor로 사용. 선택502/20260908은 ledger없음. live code/관련 git history에서 생성 implementation 찾지 못함 | UNKNOWN_SUSPECT. 이름만 보고 모든 field 합성/모든 row FORBIDDEN으로 자동 판정하지 않음 |
| KOMIS_SAMPLE | mineral master | 텅스텐 명시 공단샘플, 선택행 및 source 맞음 | 해당 row/schema/version 한정 ALLOWED 후보 |
| source_verified YAML / versioned resource | mineral_info_data.yml / messages·navigation | code가 verified resource만 사용, 실제 응답 연결 | 해당 static 내용 ALLOWED 후보 |
| 일반 수집문서/news/실HS raw | source path/게시상태만 존재할 수 있음 | dummy 원장미일치는 인증 증거와 다름 | 출처 책임/버전/ingestion 증거 없으면 UNKNOWN |

제안 상태:

- **ALLOWED**: 책임 있는 source 승인 + snapshot/version + row/field/key lineage 및 사용 의미 일치.
- **FORBIDDEN**: 실제 사용 input/selected value에 연결된 개발 fixture/dummy.
- **UNKNOWN**: 미확인 loader, provenance 부재, broad caveat와 세부행의 불일치, source unavailable.
- **MIXED**: branch/row별 상태 유지. 필수 최종 결과가 FORBIDDEN에 의존하면 인증 실패. 단순 검색 후보에 dummy가 있었으나 최종 lineage에 전혀 사용되지 않았다면 그 결과까지 오염으로 승격하지 않음.

**제안만 기록**했다. source policy/oracle/dummy filtering은 설치·변경하지 않았다.

기존 코드 근거:

- `inhouse/rag_core/ragkit/data_source_policy.py`: DEV_DUMMY는 별도 ALLOW_DUMMY, unknown은 SOURCE_UNAVAILABLE. production 인증과 개발 노출 허용은 다름.
- `inhouse/common/komis_raw.py:817`: price criterion에 dummy tracking이 하나라도 있는지를 판정하는 criterion-level 함수.
- `inhouse/rag_core/ragkit/_mcp_tools_common.py:722`: 비가격 경로는 mineral master policy를 evidence에 전달.
- `inhouse/rag_core/retrieval/evidence.py:270`: is_dummy/unverified caveat 생성; source field를 임의 승격하지 않음.
- `inhouse/rag_core/retrieval/mineral_info.py:17`: source_verified=true 편집형 record만 사용.
- `inhouse/rag_core/retrieval/news.py:88`: ai_daynews_raw 조회; ai_news dummy 원장을 같은 source로 취급하면 안 됨.

## 8. Temporal invariant policy — 값 하드코딩 금지

아래는 **미래 product certification invariant 제안**, 즉시 runtime/QA oracle에 적용하지 않는다.

| invariant | 검사 의미 | 지금 보존할 known-invalid |
|---|---|---|
| requested coverage | resolved period와 실제 관측범위·빈 구간·operation 최소관측 수 | REG04 최근60행을 전체 연평균처럼 표기하는 기존 결과 |
| date ordering | canonical date의 선언된 asc/desc, tie 규칙 | 입력 row순서 및 기존 sort 결과를 이동 중 바꾸지 않음 |
| latest cardinality | 선택 criterion별 최신1개; ALL이면 criterion별1개 | ADD01/MP03 current가 다수 rows를 내는 기존 동작 |
| as-of | observed≤reference date, future분리; 월/연 확정기간 semantics | source future-date row 존재 사실을 snapshot에 남김 |
| identity | entity/metric/criterion/period 보존 | alias/누락이 existing failure를 만드는 경우 그 failure도 동등 |
| unit | 차원·통화·중량·변화율 semantic과 일치 | REG05 WT002, CN08 unit_unavailable 수정 금지 |
| provenance | row/branch status와 final lineage의 적합성 | 기존 caveat 미표시도 known-invalid output; 새 경로로 확산 금지 |
| duplicate | entity/criterion/date/observation_type의 선언 key와 deterministic tie | 모든 중복 자동제거 등 동작 개선을 refactor와 섞지 않음 |
| observed/forecast | 동일 identity 호환성, reference boundary, provenance 유지 | PF02 실패, dummy forecast 사용 상태는 별도 개선과제 |

영구 Golden assertion을 “price==24310.4”로 만들지 않는다. 같은 **고정 입력 snapshot**의 old/new differential에서 exact output/hash를 비교하는 것과, 시간이 흐르는 제품의 가격 정답을 특정 값으로 고정하는 것은 다르다. source snapshot이 바뀌면 exact-value reference가 아니라 위 invariant로 별도 검증한다. 의미 비교를 이유로 unit/date/caveat 누락을 무시하지 않는다.

## 9. Environment drift 판정

**ENVIRONMENT_DRIFT_PRESENT_BUT_CAUSALITY_UNPROVEN.**

- 원본 PostgreSQL16.14/vector0.8.2, Step0 clone16.15/vector0.8.7.
- 동일 DB binary에서 old/new SQL ordering/type/vector ranking을 직접 대조한 A/B 기록 없음.
- MI02/GM04의 인용 차이만으로 vector version 때문이라고 단정할 수 없음.
- MP04의 가격60행, GM04의 Li/Ni/Co 표는 실제 동일. 모든 QA에 typing/ordering 변화가 발생했다는 주장에도 근거 없음.
- Step0 during/after source hash 동일은 **그 run 동안 해당 schema 데이터 동일성**만 뜻하며 과거 authoritative snapshot과의 parity를 보증하지 않음.
- 이번에는 설치/다운그레이드/업그레이드/재실행 없음.

향후 refactor paired test의 baseline 환경은 **실제로 보존한 Step0의16.15/0.8.7**로 명시한다. 두 구현을 같은 환경에서 비교하면 역사적16.14/0.8.2의 product 인증과 분리하여 behavior preservation을 검증할 수 있다. 이 선택으로 과거 환경동일성 실패를 소급 해소했다고 선언하지 않는다.

## 10. Aggregate Step1 readiness와 acceptance

### 준비된 실제 boundary evidence

| QA | 저장된 입력/args/출력 | 추출 시 보존할 adapter 책임 |
|---|---|---|
| REG02 | node_4 aggregate(last,field=value,output_field=current_price), upstream node_3 TypedResult, final TypedResult 모두 저장 | AST에는 order_by가 없지만 Golden _derive가 canonical date를 찾아 order_by=date 보정. 이 경로를 포함해 비교 |
| REG04 | aggregate_yearly_avg average(price), group_by=year, upstream60행, 출력TypedResult 모두 저장 | 60행 입력/metadata/evidence/status를 그대로 평균. annual population 확대는 이번 구조이동에 포함 금지 |

`aggregate_boundary_evidence.json`은 synthetic fixture가 아니라 **실제 Step0 저장 입력/출력의 발췌**이다. 새 operator/test/handler는 만들지 않았다.

### GO의 정확한 의미

- Product Golden이 NOT_CERTIFIED라고 해서 동작을 보존하는 구조 정리가 논리적으로 금지되는 것은 아니다.
- Golden source/image·snapshot·실제 두 Aggregate boundary input/output·기존 regression evidence가 고정되었으므로 **그 범위의 behavioral reference는 READY**.
- 그러나 candidate의 behavior가 아직 검증된 것은 아니다. **이번 migration은 수행하지 않았고 계속 보류**.
- 다음 작업의 첫 gate는 고정 입력을 Golden의 기존 `LiveOperatorFactory._derive`와 후보 adapter에 각각 넣는 paired test다. `aggregate_rows(raw_args)`만 호출하여 wrapper를 생략하면 잘못된 비교다.
- 실제 effective args, function/provider call count, retry/fallback count는 그 paired gate에서 양쪽 측정한다. 과거 미관측을0으로 채우지 않는다.
- 이 gate를 통과하기 전 legacy body 제거를 완료로 인정하지 않는다. 설명되지 않는 차이/신규회귀 발생 시 NO-GO로 되돌린다.

### 반드시 보호할 known-invalid behavior

1. REG04: 제한된60행 평균 및 현재 period/결과 표시. 전체 연간 값을 다시 조회하는 “개선” 금지.
2. REG02: unique canonical date 보정, missing/ambiguous order fail-closed, current metadata/type.
3. dummy/unknown source의 현재 TypedResult와 warning/caveat 및 최종 노출 유무. 리팩터링 중 filtering/경고추가/삭제/production 재분류를 섞지 않음.
4. PARTIAL input→incomplete_population 등 기존 status/failure, empty/null/unit 동작.
5. root/dependency/input selector/step ID와 불일치 상태를 포함한 raw output. MP04의 과거 ID변동을 고정-AST 비교에서 허용차로 전용하지 않음.
6. ADD01/MP03 cardinality, GM04 문서 fallback 오출력, CN08 unit blocker 등 바깥 경계는 현재 값/실패를 유지.
7. PF01/CN07/ADD40 dummy forecast를 새 product PASS로 승격하지 않음.
8. 알고 있는 오염을 새 QA/source/branch로 확산하지 않고, provenance 정보를 더 소실시키지 않음.

### 향후 승인 gate

- **Behavioral**: 동일 input+same pinned source/runtime에서 old/new boundary parity; 기존21 PASS-label QA의 **행동** 회귀0; 그 라벨의 제품 정답성을 재사용하지 않음.
- **Regression**: core1560 전체 및 새 characterization 통과, chat known1 외 신규실패0. 테스트 삭제/skip/완화 금지.
- **Architecture**: QA/질문/entity 특례0, central-dispatch growth0, duplicated contract source 증가0, legacy execution 증가0.
- **Product**: 인증 개선은 별도 iteration. 이번 cleanup 성공을 Strict 점수 증가/출처 인증 성공으로 보고하지 않음.
- 기존 Architecture Plan의 “Strict≥21” 문서는 덮어쓰지 않는다. 이 사용자의 최신 분리 지시에 따라 refactor gate는 위 행동/회귀 기준을 사용하고, Product21 인증 조건은 별도 미충족 ledger로 유지한다.

## 11. Regression / Complexity / Contract Delta

### Regression

이번 실행0. Step0 sealed log를 인용:

- rag_core1560 passed/0failed.
- rag_chat155passed/1knownlegacyfailure.
- 신규코드 변경0이므로 신규회귀0을 **실행으로 재확인했다**고 주장하지 않는다.
- 원본 evidence108파일 hash mismatch0, branch records/QA ID57/기존PASS21 집계 일치 확인.

### Complexity Delta

| 항목 | 변화 |
|---|---|
| Project files changed | 새 감사 Markdown1개; 기존 미추적문서2개 보존 |
| Feature code files / new classes |0 /0|
| New public runtime contracts / registry entries |0 /0|
| New special-case execution branches |0|
| New central-dispatch branches / removed branches |0 /0|
| Duplicated production contract sources added/removed |0 /0|
| Largest modified method/class/module LOC |N/A(프로젝트 실행코드 수정 없음)|
| Responsibility growth |false|
| Verdict |**COMPLEXITY_PASS**(이번 문서/증거변화); 기존 REFACTOR_CANDIDATE 부채 유지 |

Private bundle의 read-only 수집/보고 script와 QA별 장부는 제품 실행 매핑/정답 하드코딩/QA handler가 아니다. 향후 runtime import 경로로 편입하지 않는다.

### Contract Delta

- **문서 계약 신규 정의**: Behavioral Reference V1, Certified Product Golden 분리.
- **runtime/oracle 계약 신규·수정·삭제**:0/0/0.
- **제안만**: ALLOWED/FORBIDDEN/UNKNOWN/MIXED provenance policy, temporal invariant, refactor acceptance.
- Canonical owner: behavioral=sealed Golden implementation+boundary evidence; product policy=별도 승인될 source/provenance owner와 strict oracle(이번 미변경).
- Consumers: 향후 Aggregate old/new differential/regression 및 별도 product certification.
- Duplicated mappings remaining: 기존 Registry/runtime/legacy alias 부채 유지. 이 감사로 새 runtime source of truth를 추가하지 않음.
- broad mineral caveat와 row-level ledger의 granularity 차이는 증거 불일치 위험으로 기록. 수정/새정규화/central if문 추가 없음.

## 12. 종료

**Behavioral Reference READY, Certified Product Golden NOT_CERTIFIED, Step1 bounded migration readiness GO. 실제 Aggregate migration은 계속 보류하며 이번에는 수행하지 않았다.**

18002 container/image/StartedAt는 Step0와 동일함을 read-only inspect로 확인했다. 소스/원천/DBversion/QA oracle/기존 artifact는 그대로다. 이 보고 이후 추가 repair나 Full Replay로 이어가지 않는다.

