# Architecture Cleanup Step 4 — Filter mechanical extraction

## 판정

**Step 4 acceptance: PASS_SCOPED_FILTER_BEHAVIOR_PARITY.**
동일 graph/source 입력에서 기존·신규 FILTER의 behavior가 동일하다.
uncontrolled live 전체 응답의 결정성이나 새로운 Strict PASS를 뜻하지 않는다.
**18002 미변경. Step 5 Calculation, Full QA57, Strict 갱신은 수행하지 않는다.**

| 검증 | 결과 |
|---|---|
| 실제 frozen Step3 vs Step4 boundary differential | **5057/5057 동일** |
| Runtime / composition / SSE differential | **36/36 동일** |
| 실제 후보 container differential | **5057+36**, host 산출물과도 전체 동일 |
| 저장된 Behavioral Reference V1 영향 graph | **ADD16 1/1 동일**, FILTER node 1개 |
| live old/new | **7/8 exact parity**: 응답/terminal/graph/TypedResult 모두 |
| live graph/source 고정 old/new executor 교차 비교 | **16/16 동일**, FILTER 포함 graph 6개 |
| targeted / contract tests | **172 passed**, 8 subtests, 1.18s |
| rag_core 전체 | **1641 passed / 0 failed**, 695 subtests, 40.55s |
| rag_chat 동일 scope | **155 passed / 동일 known failure 1**, 15 subtests, 6.32s |

core는 기존 1614개 유지 + 신규 registered Filter tests 27개다.
Certified Product Golden은 `NOT_CERTIFIED_WITH_KNOWN_REASONS` 그대로이며,
known-invalid provenance/alias/정책을 고치거나 신규 QA 회복으로 집계하지 않았다.

## 기준점 / 환경

- 비교 기준은 승인된 **Step3 working tree**. parent git SHA만으로 old를 재구성하지 않았다.
- parent SHA `979fd3f980bb10af74a218cc6e07bada110e76de`, branch `multihop_work`.
- 변경 전 source snapshot을 보존하고 봉인된 Step3 checksum과 일치 확인.
- 이전 dirty 변경, 스킬 변경, Step1~3 artifact는 유지. commit/push 없음.
- old image ID: `sha256:a04139648ace637ea8b7e4610fdadf9cca3b96389acad2e93e3cbf9a3baa8899`.
- new tag: `komir-rag-chat:filter-step4-20261003`.
- new image ID: `sha256:e8dca207d2f1b2173bb199e534c69cb5eaa21db31a2a55ba3f78a93243ffe0da`.
- local RepoDigests `[]`; 위 값은 image ID이며 registry manifest digest가 아니다.
- new container: `komir-filter-step4` /
  `23d83639df24f4b3fdf9e54e2fe196ddb59b9ce3344501ccaf4b89b538aa4ad1`.
- image revision label은 parent SHA, validation label은 `filter-step4-working-tree`,
  build timestamp는 `2026-10-03T13:04:30.444808+00:00`.
  container label은 `filter-step4`이며 clean Golden checkout이라는 뜻은 아니다.
- **127.0.0.1:18012**만 교체. env/extra_hosts/network/readonly resource mount 이전과 동일.
- host/container source **226 files checksum 일치**, Gemma models / MCP 정상 확인.
- Step3 container/image는 stopped 상태로 rollback용 보존했다. 삭제하지 않았다.

### Validation sequencing 한계

초기 startup health curl은 connection reset으로 retry limit에 도달했다.
후속 live runner는 자체 health 200을 확인하고 실행했으나, 별도로 재실행한 전체
source checksum/Gemma/MCP preflight 완료와 초기 요청이 중첩됐다.
따라서 **모든 QA가 전체 preflight 완료 이후 실행됐다고 주장하지 않는다.**
동일 immutable candidate image/source/env는 확인했고, 추가 deterministic container
differential 및 고정 graph/source 교차 검증으로 execution parity를 확인했다.
이번 scoped acceptance를 clean Full QA57 인증이나 product certification으로 확대하지 않는다.

## Pre-change 책임 / Decomposition Review

위험도는 승인된 architecture migration으로 CRITICAL 절차를 적용했다.
production 구현 1회, semantic repair 0회. 읽기 전용 독립 감사에서 차단 finding 없음.

| 점검 | 판단 |
|---|---|
| 기존 책임 | `_derive`가 Filter/Projection/Calculation/Relation을 직접 처리 |
| 적합한 이관 경계 | 기존 `operator_handlers`의 등록형 step builder |
| Filter owner | 신규 `filtering.py`, 기존 predicate 평가 알고리즘만 소유 |
| 재사용 contract | RequirementNode / TypedResult / FunctionStep 및 주입 helpers |
| domain/source 개념 증가 | 없음 |
| 별도 source of truth | 추가 없음. 기존 metric fallback table은 복제가 아닌 이동 |
| QA/질문/광종 특례 | 0 |
| 중앙 확장 방식 | registry entry +1, legacy FILTER condition 제거 |
| 독립 검증 가능성 | registered unit / frozen differential / runtime graph 비교 가능 |
| 구조 변경 필요성 | 승인된 단일 책임 extraction만 수행. parallel framework 불필요 |

Before: `_derive` 271 > 200, class 584 > 500, module 3018 > 1500,
operator-family 책임 4개로 `DECOMPOSITION_REVIEW_REQUIRED`.
After에도 class 517 > 500, module 2952 > 1500, `_derive`의 독립 family 3개이므로
검토 trigger가 남는다. `_derive` 199행도 기존 HIGH 150행 기준은 초과한다.
추가 분해를 자동 승인하지 않으며 Step5를 진행하지 않는다.

## 이동한 책임과 보존한 동작

```text
AAST → 기존 StepFactory.build
     → registered build_filter_step
     → 기존 FunctionStep
     → 기존 predicate/row selection
       + 주입 canonical resolver / numeric / country / period helpers
       + 기존 _finalize_derived_rows
     → 기존 TypedResult / PipeRuntime

미이관 연산 → 기존 legacy path (증가 없음)
```

- legacy Filter execution 본문 **72행을 제거**하고 routing set에서 FILTER를 제거했다.
- Mapping predicate의 field/operator/value fallback, compact string predicate 및
  `increase/decrease` alias를 동일하게 이동했다.
- 기존 metric fallback table의 후보 순서와 `_resolve_row_field` 호출 조건 그대로다.
  **explicit field는 metric alias로 새로 해석하지 않는다.**
- **fieldless일 때만** `_filter_period`를 적용한다. explicit field가 있으면 period를
  추가로 적용하지 않는 기존 정책도 유지한다.
- 기간의 latest-relative cutoff, inclusive bounds, invalid date/period 및 non-Mapping
  row 처리 등은 기존 helper에 위임한다. period 의미 개선 없음.
- country equality/not-equality는 source namespace resolver가 선택한 원본 row의 `id`로
  매칭하며 `country_alias_ambiguous` 기권을 유지한다. fuzzy matching 추가 없음.
- MINERAL_SET의 문자열 row 비교, numeric coercion, NULL equality, 비교 불가능한 타입의
  예외, unsupported operator의 예외 조건/문구를 보존한다.
- PARTIAL을 새로 차단하지 않는다. 입력 순서는 기존 첫 source 선택을 그대로 사용한다.
- **explicit empty rows**, unavailable metric의 **TypedResult.EMPTY**, fieldless **replace**,
  일반 field filter의 **공통 finalization**은 서로 다른 기존 경로 그대로다.
  EMPTY에서 원래 전달하지 않던 metadata를 보완하지 않았다.
- 원본 row/date/lineage, entity/metric/unit, source/evidence/provenance/status/warnings/failure
  의미 보존. MINERAL_SET empty의 entity도 기존처럼 empty다.
- node ID/operation/InputRef binding/dependency identity 보존. timeout=None/max_retries=0,
  cancel/exception propagation은 기존 FunctionStep/PipeRuntime 소유다.
- module의 모든 기존 top-level helper와 factory의 build/_build_legacy/_derive 외 method는
  **AST 동일** 확인. Projection/Calculation/History/Renderer/Capability는 수정하지 않았다.

## Differential / 테스트 범위

old는 실제 Step3 source snapshot을 별도 모듈로 로드했다. `__file__`은 변경 없는 설치
package의 common/resource bootstrap에만 연결하며 실행 code는 frozen snapshot에서 읽었다.
새 구현을 expected oracle로 복제하지 않았다.

- 5057 boundary: equals/not_equals/greater_than/less_than/gte/lte/unsupported,
  Mapping/compact predicate, None/zero/numeric string/mixed types, 모든 6 ResultStatus,
  list/Mapping/scalar/tuple/empty, unavailable/implicit/explicit field, period bounds,
  trailing-months/invalid period, country aliases/ambiguity, MINERAL_SET/first source/secondary
  PARTIAL/missing input 포함. 예외 type/message도 old/new 비교했다.
- 36 runtime graph: 6 Filter 요구 × 6 status, source → Filter → Projection.
  전체 실행 결과/status/failure/root/presentation/SSE와 고정 retrieval 호출 순서/횟수 비교.
- graph harness 초안의 fieldless/undeclared-field 사례는 기존 AAST validator가 거절했다.
  제품 validator를 바꾸지 않고, invalid 사례는 boundary matrix에 유지하고 runtime graph는
  선언된 price field/metric 입력으로 구성했다. target tests도 다시 실행했다.
- Behavioral Reference V1의 FILTER 포함 graph는 **ADD16 1건**이었다. 저장된 source
  TypedResult를 주입해 동일 graph를 old/new로 재실행했고 전체 결과가 같았다.
- container Python 3.12에서 5057+36 실행 결과가 host Python 3.10 JSON과 전체 동일.
- network tripwire 및 저장 source substitution을 이용한 비교는 execution 경계 검증이다.
  실제 source 전체의 정확성이나 외부 retrieval 결정성을 보증하지 않는다.

## Live parity / 기존 blocker

각 실행은 fresh UUID session, empty history로 시작했다.
old/new 각각 ADD16 ×3 + REG02/REG04/ADD15/ADD49/ADD27 ×1, 총 16 requests.
각 응답은 terminal 정확히 1개 및 마지막 SSE event임을 확인했다.

| QA | old/new 결과 |
|---|---|
| ADD16 run1 | old 4-node Compare graph: `comparison_alignment_required`; new 6-node Calculate graph: `calculation_field_unavailable` |
| ADD16 run2/3 | old부터 이미 new와 graph/TypedResult/응답/terminal 동일; 계산 blocker 유지 |
| REG02 | graph/TypedResult/응답/terminal 동일, 이번 live는 latest retrieval 경로 |
| REG04 | graph/TypedResult/응답/terminal 동일, 기존 60행 평균 유지 |
| ADD15 | graph/TypedResult/응답/terminal 동일, 이전 Ordering sentinel 유지 |
| ADD49 | graph/TypedResult/응답/terminal 동일, Price Identity 유지 |
| ADD27 | graph/TypedResult/응답/terminal 동일, price series 유지 |

ADD16은 양쪽 3/3 abstention이다. 같은 old 이미지에서 이미 graph가 변했으므로 첫 pair의
차이를 migration에 의한 semantic 변화로 분류하지 않는다. 다만 최초 raw 차이를 숨기지
않고 **7/8 exact parity**로 기록한다. 모델 변동의 seed/hardware 등 근본 원인까지 확정하지 않는다.

각 old/new live의 **16개 실제 graph와 source input을 고정**하여 양 executor로 교차 실행했다.
결과 16/16 동일이며, 이 중 FILTER 포함 graph 6개는 Filter 결과가 동일하다.
나머지 10개는 주변 경로 회귀 확인이다. Compare/Calculate의 downstream 실패도 양쪽 동일.
ADD16 denominator/계산/정렬 semantics는 수정하지 않았고 Strict 회복으로 계산하지 않았다.

## Regression

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:inhouse:inhouse/rag_chat python3 -m pytest -q -p no:cacheprovider inhouse/rag_core/tests/test_registered_filter.py inhouse/rag_core/tests/test_live_country_alias.py inhouse/rag_core/tests/test_live_contract_repair.py inhouse/rag_core/tests/test_live_price_fanout.py inhouse/rag_core/tests/test_live_audit_safety.py inhouse/rag_core/tests/test_live_multihop.py inhouse/rag_core/tests/test_qa500_common_contracts.py inhouse/rag_core/tests/test_multihop_runtime.py
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:inhouse:inhouse/rag_chat python3 -m pytest -q -p no:cacheprovider inhouse/rag_core/tests
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:inhouse:inhouse/rag_chat python3 -m pytest -q -p no:cacheprovider inhouse/rag_chat/tests
```

- targeted **172 passed / 8 subtests**.
- core **1641 passed / 695 subtests**, 기존 Pydantic annotation warning 유지.
- chat **155 passed / 15 subtests / 동일 known failure 1**:
  `test_sse_cancellation.py::test_disconnect_stops_real_ast_retry_before_blocking_invocation_returns[legacy_control-False]`.
  actual calls 4 / expected 3 그대로이며 신규 regression 0.
- 기존 6개 test file의 FILTER private `_derive` 호출만 기존 registered helper로 이동했다.
  assertion/fixture/oracle 의미 변경 없음. 신규 registered Filter tests 27개 추가.
- 전체 suite는 targeted/live 후 core → chat 순으로 실행했다.

## Complexity Delta / before-after

| 지표 | Step3 before | Step4 after |
|---|---:|---:|
| live_multihop.py LOC | 3018 | **2952** |
| LiveOperatorFactory LOC | 584 | **517** |
| `_derive` LOC | 271 | **199** |
| central operator condition 수 | 11 | **10** |
| legacy Filter execution body LOC | 72 | **0** |
| 신규 handler module LOC | 0 | **101** |
| 신규 handler builder LOC | 0 | **92** |

LOC는 주석/빈 줄 포함. central condition은 기존처럼 class AST If test에서
`*.operator`를 참조하는 조건 수다. legacy routing operator membership은 5→4.

- Files changed: **production 2 + tests 7 + 이 artifact 1**. 이전 Step1~3 변경은 별도 보존.
- New classes / public semantic contracts: **0 / 0**. 기존 signature의 내부 builder 1개.
- New registry entries: **1**.
- New QA/question/entity special cases: **0/0/0**.
- New central-dispatch branches: **0**; removed legacy Filter condition **1**, 본문 **72행**.
- Duplicated contract sources added/removed: **0/0**. 기존 local alias table의 위치만 이동.
- Largest modified method/class/module: **199 / 517 / 2952 LOC**.
- Responsibility growth: **없음**. `_derive` family 책임 Filter/Projection/Calculation/Relation
  **4→3**, handler는 Filter 평가 한 책임을 소유한다.
- Structural delta: **PASS**. Complexity verdict: **COMPLEXITY_WARN**.
  92행 builder가 기존 80 LOC warning을 넘고 monolith/alias 부채가 남는다.
  LOC만 줄이기 위한 의미 없는 추가 분할은 하지 않았다.
- `DECOMPOSITION_REVIEW_REQUIRED` 및 기존 `REFACTOR_CANDIDATE/REFACTOR_REQUIRED` 잔여 부채 유지.
  실행 failure owner는 Filter handler에서 식별 가능하고 common resolver/finalizer는 명시적 의존이다.
  중앙 legacy dispatcher에 Filter 의미를 남기거나 새 parallel framework를 만들지 않았다.

## Contract Delta

- New / modified / removed **semantic contracts: 0 / 0 / 0**.
- 실행 owner: `_derive` → `operator_handlers.filtering`.
- Filter의 기존 metric 후보·compact predicate alias table도 동일 body와 함께 이동.
- canonical field / numeric / country / period owner: 기존 `_resolve_row_field`, `_numeric`,
  `_resolve_country_alias`, `_filter_period` 그대로 주입.
- metadata/entity finalization: 단일 기존 `_finalize_derived_rows`.
- consumers: 기존 StepFactory / FunctionStep / PipeRuntime.
- remaining duplicated mappings: 기존 planning metric normalization 및 legacy source/projection/
  renderer alias 부채는 유지. 추가 mapping/normalization 중복 0, 이번 범위에서 alias 통합 0.
- known-invalid behavior/provenance를 개선하거나 확산하는 새 정책 없음.

## 무결성 / Evidence / 종료

- Step3 봉인 evidence **62개 파일 checksum 불변**.
- application source 변경은 `live_multihop.py`, `operator_handlers/filtering.py` **2개**뿐.
- source DB public/mineral_risk fingerprint before/after:
  `341be4d0d4316a9cd4da90aaaa952f38d931a1e344910ff21bf24d8d18e71954` 동일.
  이는 ai_chatbot fresh session 기록을 제외한 범위이며 source correctness 인증이 아니다.
- 18002 container/image/StartedAt/mount 불변. 운영 요청·재시작·배포 없음.
- private evidence: `/home/nuri/.codex/validation-evidence/filter-step4-20261003`.
  source snapshot/patch, host/container differential, saved/live cross-replay,
  raw/session/TypedResult, image/checksum, regression logs, 독립 감사, manifest 포함.
  env credentials는 포함하지 않는다.

**Step4 완료 후 중단. Step5 Calculation, Full QA57, Strict 갱신, commit/push는 하지 않는다.**
