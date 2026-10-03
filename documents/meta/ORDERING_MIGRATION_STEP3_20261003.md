# Architecture Cleanup Step 3 — Sort / Rank / TopK mechanical extraction

## 판정 / 범위

**Step 3 acceptance: PASS_SCOPED_ORDERING_BEHAVIOR_PARITY.**
동일 graph/source input에 대한 기존·신규 execution parity가 확인되었다.
다만 비결정적 live planning/retrieval까지 포함한 raw 응답 전체 일치를 의미하지 않는다.
그 차이는 아래에 별도 기록하며 새 PASS나 QA recovery로 계산하지 않는다.

- SORT / dependency RANK / TOP_K의 기존 실행 책임만 등록형 handler로 이관.
- no-input RANK는 동일 handler에서 기존 `_retrieve`로 위임하며 source rank 의미를 유지.
- 기존 StepFactory / StepHandler-compatible callable / FunctionStep / PipeRuntime 재사용.
- 새 execution layer, hierarchy, scheduler, capability, semantic policy 없음.
- **18002 미변경. Full QA57 및 Strict 점수 갱신 없음. Step 4 Filter 미진행.**

| 검증 | 결과 |
|---|---|
| frozen Step2 → Step3 boundary differential | **3092/3092 일치** |
| Runtime/composition/SSE differential | **18/18 일치** |
| 실제 candidate container differential | 위 결과 및 host 산출물과 전체 일치 |
| Behavioral Reference V1 영향 saved graphs | **5/5 일치**, ordering node 14개 |
| old/new live raw answer | **5/8 일치**; 아래 비결정적 입력 차이 분리 |
| old/new live terminal / graph / TypedResult exact | **6/8 / 5/8 / 4/8** |
| 실제 live 16개 graph/source 고정 cross-executor replay | **16/16 전체 일치** |
| targeted / contract tests | **156 passed**, 1.14s |
| rag_core 전체 | **1614 passed / 0 failed**, 695 subtests, 40.41s |
| rag_chat 동일 scope | **155 passed / 동일 known legacy failure 1**, 15 subtests, 6.48s |

core는 기존 1589개 유지 + 신규 registered ordering test 25개다.
Certified Product Golden은 `NOT_CERTIFIED_WITH_KNOWN_REASONS` 그대로다.
dummy provenance, REG04 60행 평균, 기존 alias/NULL/tie/field selection 동작도 개선하지 않았다.

## 기준점 / 실행 환경

- 기준은 승인된 **Step2 working tree**이며 git HEAD만으로 이전 동작을 재구성하지 않았다.
- parent SHA: `979fd3f980bb10af74a218cc6e07bada110e76de`, branch `multihop_work`.
- 수정 전 `live_multihop.py`를 보존했고 Step2 봉인 checksum과 일치한다.
- Step1/2 기존 dirty 변경과 문서는 유지했다. commit/push는 수행하지 않았다.
- old image ID: `sha256:1f09dc8fe7ef32d7760c381d04c52272ff998628c4b28a5d2da7be6ed73f513b`.
- new tag: `komir-rag-chat:ordering-step3-20261003`.
- new image ID: `sha256:a04139648ace637ea8b7e4610fdadf9cca3b96389acad2e93e3cbf9a3baa8899`.
- local RepoDigests는 `[]`; image ID를 registry manifest digest라고 부르지 않는다.
- new container: `komir-ordering-step3` /
  `0059c8896e819cd690b987d6d574f05edfa1106297b0ea1cbf3ac6ce2fa576b3`.
- endpoint는 **127.0.0.1:18012**만 사용. env/extra_hosts/network/readonly mount 동일.
- image revision label은 parent SHA, validation label은 `ordering-step3-working-tree`이며
  build timestamp를 함께 기록했다. clean Golden checkout이라는 뜻이 아니다.
- 재사용한 validation helper의 container label은 `aggregate-step1`로 남아 있다.
  이를 identity 근거로 사용하지 않고 실제 image ID/container ID/source checksums로 판별했다.
- host/container **225 files checksum 일치**, Gemma models/MCP/source healthy 후 live 요청.
  최초 health 호출은 startup 중 connection reset이었으며 준비 완료 후 preflight를 통과했다.
  실패한 preflight 상태에서 QA를 실행하지 않았다.
- Step2 container/image는 삭제하지 않고 rollback용 stopped 상태로 보존.

## Pre-change responsibility / architecture audit

승인된 architecture migration으로 CRITICAL 절차와 읽기 전용 독립 감사를 적용했다.
production 구현 1회, 동작 수정 0회다.

| 점검 | 판단 |
|---|---|
| 기존 책임 | LiveOperatorFactory가 등록/라우팅 외 ordering 실행 알고리즘까지 소유 |
| 올바른 owner | 기존 ordering family 실행은 `operator_handlers/ordering.py` |
| 기존 확장점 | StepFactory.build의 등록형 builder table |
| semantic owner | field resolver / numeric / metadata finalization을 기존 단일 구현에서 주입 |
| 새 개념 도입 | 없음; 기존 source rank vs dependency rank 구분만 이동 |
| 계약 중복 | alias/normalization/metadata mapping을 복제하지 않음 |
| QA 특례 | 없음 |
| 중앙 branching | registry entry +3, legacy operator conditions −2 |
| 구조 변경 필요성 | 승인된 책임 추출만 수행, 별도 추상화 프레임워크 불필요 |
| 남은 부채 | 큰 runtime module/class 및 legacy alias duplication은 후속 승인 범위 |

## 이동한 책임 / 보존한 의미

```text
AAST → 기존 StepFactory.build
     → registered ordering builder
       ├─ RANK + no lowered dependencies → 기존 async _retrieve
       └─ SORT / dependency RANK / TOP_K → 이동한 ordering body
            → 기존 canonical resolver / _numeric
            → 기존 _finalize_derived_rows
     → 기존 FunctionStep → 기존 PipeRuntime → TypedResult

미이관 연산 → legacy fallback (증가 없음)
```

- no-input 여부는 **lowered dependencies**로 결정한다. runtime inputs, node.args 또는
  node.inputs 유무로 바꾸지 않았다. no-input rank의 async capability 조회·예외는 그대로다.
- SORT는 PARTIAL source를 그대로 정렬한다. RANK/TOP_K는 any-input PARTIAL이면
  `incomplete_population`으로 abstain하는 기존 차이를 유지했다.
- dependency RANK는 정렬만 하며 `top_n`으로 자르거나 새 rank field를 생성하지 않는다.
- TOP_K는 기존 slicing만 수행한다. `k or top_n or 5`의 zero fallback, negative slice,
  invalid int 예외도 그대로다. 새로운 범위 validation을 추가하지 않았다.
- numeric 우선 / string lexical ordering / ISO date 문자열 ordering, ascending/descending,
  explicit tie_breaker 문자열 선행 정렬 및 stable primary sort를 보존한다.
- NULL/missing rows 후순위, mixed incomparable values abstention, 기본 첫 numeric field 선택,
  `row not in valid`의 기존 equality 의미를 그대로 이관했다.
- 첫 upstream 선택은 inputs의 기존 순서 그대로다. field alias normalization은 기존 resolver.
- 원본 row 객체를 유지하며 date/entity/metric/unit/evidence/provenance/lineage/status/warnings/
  failure metadata는 기존 공통 finalization을 통해 유지한다.
- node ID / operation / InputRef bindings / dependency 순서 및 중복 ref 처리 그대로.
  timeout=None, max_retries=0, cancel/exception/status propagation은 기존 FunctionStep/Runtime 소유.
- legacy TOP_K와 SORT/RANK 본문 **29행 제거**. routing 집합과 PARTIAL guard에서도 이관 대상 제거.
- Filter/Projection/Calculation/Relation/History/Renderer/Planner/Capability 알고리즘은 미변경.

## 결정론적 검증

old factory는 frozen 실제 Step2 source를 별도 모듈로 로드했다. `__file__`만 변경 없는
설치 package의 common/resource bootstrap에 연결하며 실행 code는 snapshot에서 읽는다.
새 구현을 expected oracle로 복제하지 않았다. 네트워크 호출은 tripwire로 차단했다.

1. **3092 경계 사례:** SORT/RANK/TOP_K, asc/desc/기존 order alias, field/metric_field,
   missing/implicit field, tie_breaker, k/top_n, zero/negative/invalid k, 모든 6 ResultStatus,
   null/numeric string/date/string/mixed values, Mapping/list/scalar/tuple/empty,
   secondary PARTIAL, MINERAL_SET, missing dependency input, no-input RANK retrieval 포함.
   인접 Aggregate/Extremum/Filter/Project도 같은 builder로 비교했다.
2. **18 graph:** 각 operator × 6 status, source → ordering → projection.
   전체 TypedResult/runtime status/failure/root/presentation/SSE와 호출 identity/count/order 비교.
3. **saved graph 5건:** MP03/GM01/GM02/GM08/ADD15의 Behavioral Reference V1 graph와
   저장된 실제 source TypedResult로 replay. 14 ordering nodes 포함, 전체 old/new 동일.
4. **실제 container:** 3092+18 동일 harness를 Python 3.12 후보 이미지에서 실행.
   host Python 3.10 결과와 전체 JSON 일치. source/handler SHA를 함께 저장했다.
5. **live 교차 검증:** 이번 old/new fresh 8건씩의 각 graph와 source TypedResult를 고정하고
   양쪽 executor로 replay하여 16/16 동일함을 확인했다.

source retrieval을 저장된 결과로 치환한 fixed replay는 외부 시스템 자체를 재검증하는
것이 아니라 migrated execution boundary의 동등성 검증이다. live backend 전체 호출 수가
항상 같다고 확대 해석하지 않는다.

## 영향 live QA / 변동 분석

동일 설정 old/new 이미지에서 각 QA를 각각 새 session으로 1회 실행했다.
총 **16 requests**, terminal 정확히 1개/마지막 event임을 모두 확인했다.

| QA | 최초 live 차이 | migration 인과 판정 |
|---|---|---|
| MP03 | generated nodes 6→8; 새 Project가 `import_value` 요구, PARTIAL | 같은 새 graph/source를 Step2에도 넣으면 동일 PARTIAL; ordering 회귀 아님 |
| GM01 | graph/응답/terminal 동일; retrieval document evidence의 section/text 차이 | 차이는 rank 이전 retrieval에서 존재; 고정하면 양쪽 전체 동일 |
| GM02 | generated top_n null→10, retrieval evidence도 일부 변동; 국가 2→4 | 기존 `k or top_n or 5`에 서로 다른 입력. 각 입력에서 양쪽 동일 |
| GM08 | 응답/terminal/graph/TypedResult 동일 | sentinel 유지 |
| ADD15 | generated Project nodes 추가; root/table field 감소 | 요구된 나라·값은 동일하나 raw 출력은 다름. 각 graph에서 양쪽 동일 |
| REG02 | 응답/terminal/graph/TypedResult 동일 | sentinel 유지; 이번 live는 latest retrieval 경로 |
| REG04 | 응답/terminal/graph/TypedResult 동일 | 60행 평균 등 known-invalid behavior 보존 |
| ADD49 | 응답/terminal/graph/TypedResult 동일 | Price Identity sentinel 유지 |

MP03는 old live SUCCESS → new live PARTIAL이었다. 이를 숨기거나 PASS로 계산하지 않는다.
**새로 생성된 graph를 실제 old executor도 동일하게 실패**하므로 최초 차이는 migrated
ordering 실행 전이다. GM02/ADD15도 generated graph 차이가 먼저 존재한다.
planner/retrieval 비결정성 후보로 기록하며 seed/hardware 등 변동 원인까지 확정하지 않는다.
GM01은 source row가 아니라 document evidence 선택 차이다. source DB fingerprint는 동일하다.

REG02 `ordered_last`는 이번 live에서 Aggregate가 생성되지 않았으므로 live만으로 검증했다고
주장하지 않는다. 기존 Aggregate tests/전체 regression/인접 differential을 함께 유지했다.
unknown/known-invalid 값과 provenance는 수정하거나 Certified Product PASS로 승격하지 않았다.

## Regression commands / 결과

순서: old/new differential → targeted/contract → old/new live/sentinel → core → chat.
live 변동을 확인한 후에는 추가 QA 수정 없이 fixed graph cross-replay만 보강했다.

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:inhouse:inhouse/rag_chat python3 -m pytest -q -p no:cacheprovider inhouse/rag_core/tests/test_registered_ordering.py inhouse/rag_core/tests/test_live_multihop.py inhouse/rag_core/tests/test_live_relations.py inhouse/rag_core/tests/test_qa500_common_contracts.py inhouse/rag_core/tests/test_multihop_runtime.py inhouse/rag_core/tests/test_multihop_lowering.py
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:inhouse:inhouse/rag_chat python3 -m pytest -q -p no:cacheprovider inhouse/rag_core/tests
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:inhouse:inhouse/rag_chat python3 -m pytest -q -p no:cacheprovider inhouse/rag_chat/tests
```

- targeted: **156 passed**.
- core: **1614 passed**, 기존 1589 유지 + 새 25. 기존 Pydantic annotation warning 1개 유지.
- chat: **155 passed / 1 failed**. 동일 known legacy:
  `test_sse_cancellation.py::test_disconnect_stops_real_ast_retry_before_blocking_invocation_returns[legacy_control-False]`.
  실제 호출 4 / 기대 3 그대로, 신규 failure 0.
- 기존 테스트 2개의 private `_derive` 직접 호출을 기존 registered helper로 이동했다.
  assertion/expected value/oracle/fixture 의미는 변경하지 않았다.
- 읽기 전용 독립 감사에서 algorithm / routing / identity / metadata / complexity 관련
  actionable finding 없음.

## Complexity Delta / before-after

| 지표 | Step2 before | Step3 after |
|---|---:|---:|
| live_multihop.py LOC | 3035 | **3018** |
| LiveOperatorFactory LOC | 602 | **584** |
| `_derive` LOC | 296 | **271** |
| central operator condition 수 | 13 | **11** |
| legacy ordering execution body LOC | 29 | **0** |
| 신규 ordering handler module LOC | 0 | **64** |
| 신규 handler function LOC | 0 | **56** |

LOC는 빈 줄·주석을 포함한다. 중앙 조건은 기존과 동일하게 class AST If test의
`*.operator` 참조 조건 수다. legacy routing operator membership은 8→5,
PARTIAL guard membership은 4→2다. source RANK 분기는 새 의미가 아니라 기존 routing의 이동이다.

- Files changed: **production 2 + tests 3 + 이 artifact 1**. 이전 Step1/2 변경은 별도.
- New classes: **0**.
- New public semantic contracts: **0**; 기존 step-builder signature에 맞춘 내부 handler function 1개.
- New registry entries: **3** (SORT, RANK, TOP_K, 단일 ordering builder).
- New QA/question/entity special-case branches: **0/0/0**.
- New central-dispatch branches: **0**.
- Removed central operator conditions: **2**; legacy 실행 body 29행 제거.
- Duplicated contract sources added/removed: **0/0**. 단일 의미의 위치 이동이며 중복 통합 작업 아님.
- Largest modified method/class/module: **271 / 584 / 3018 LOC**.
- Responsibility growth: **없음**. ordering 실행 책임을 기존 factory에서 분리했다.
- **변경량 COMPLEXITY_PASS**. 전체 legacy module/class에는 HIGH 크기 경고와
  `REFACTOR_CANDIDATE/REFACTOR_REQUIRED` 부채가 남는다. 이번 단계에서 확장 정리하지 않는다.

### Decomposition & Composition Guard

작업 중 추가 승인된 상시 guard도 적용했다. `_derive` 271 > 200, class 584 > 500,
module 3018 > 1500이므로 **DECOMPOSITION_REVIEW_REQUIRED는 계속 해당**한다.
자동 추가 refactor로 해석하지 않으며 Step4는 보류한다.

- `_derive`의 독립적인 operator family 책임은 Ordering/Filter/Projection/Calculation/
  Relation **5→4**다. source retrieval·history·evidence 등 class의 다른 책임은 그대로다.
- 이관한 ordering failure는 64행 handler와 주입 contract에서 식별 가능하다.
  resolver/finalization 내부의 기존 alias 부채까지 해결했다고 주장하지 않는다.
- 동일 family는 등록형 builder에서 처리하며 중앙 legacy if/elif를 추가하지 않는다.
- handler는 단독 contract test와 실제 old/new differential로 독립 검증된다.
- LOC만 나누거나 God Function을 복제하지 않았다. 기존 ordering 의미를 제거 후 이동했고,
  신규 parallel framework 또는 semantic feature 변경은 없다.
- 이번 완료 판정은 ordering 책임 감소에 한정하며 전체 monolith 정리 완료가 아니다.

## Contract Delta

- New/modified/removed semantic contract: **0/0/0**.
- ordering execution owner: `_derive` → `operator_handlers.ordering`.
- source RANK canonical capability/source 의미: 기존 `_retrieve` 유지.
- canonical field / numeric owner: 기존 `_resolve_row_field` / `_numeric` 그대로 주입.
- row metadata/entity finalization owner: 단일 `_finalize_derived_rows`, 본문 미변경.
- consumers: 기존 StepFactory / FunctionStep / PipeRuntime.
- legacy alias/renderer mappings는 기존대로 남으며 추가 local semantic mapping 없음.
- 정렬 의미, tie/null/order policy, rank cardinality, provenance/status/failure 의미 변경 없음.

## 무결성 / Evidence / 종료

- Step2 봉인 evidence 49개 파일 checksum 유지 확인.
- Step2 대비 application source checksum 변경은 live_multihop.py와 ordering.py 2개뿐.
- source DB public/mineral_risk fingerprint before/after:
  `341be4d0d4316a9cd4da90aaaa952f38d931a1e344910ff21bf24d8d18e71954` 동일.
  fresh session 기록은 검증 clone ai_chatbot에 한정한다.
- 18002 container ID/image/StartedAt/mount 불변. 요청·재시작·배포 없음.
- private evidence: `/home/nuri/.codex/validation-evidence/ordering-step3-20261003`.
  manifest에는 source snapshots/patch, host/container differential, saved/cross graph replay,
  raw/session/TypedResults, tests/logs, image/source identities, 보호 identity, 독립 감사가 포함된다.
  credentials/env secrets는 포함하지 않는다.
- 별도 사용자 요청으로 iterative-audit skill에 상시 Decomposition & Composition Guard를
  추가했다. 이는 application source 변경량에 포함하지 않는다. skill 형식 검증 통과,
  기존 80/150 LOC 경고와 새 200 LOC review trigger가 공존하며 기존 규칙 삭제 없음.

**Step 3만 완료하고 종료한다. Step4 Filter, FullQA57, Strict 갱신, QA repair, 18002 배포 없음.**
