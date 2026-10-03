# Step 10 — Registered Projection extraction

## Acceptance

**PASS_SCOPED_REGISTERED_PROJECTION_PARITY**

PROJECT 실행 본문을 기존 등록형 handler 경계로 이관했다. canonical projection과 기존 domain compatibility를 구분하고, `_derive`의 PROJECT 실행 본문과 `_build_legacy`의 PROJECT routing을 제거했다. 알고리즘 개선·QA recovery·field 허용 확대는 하지 않았다.

| 검증 | 결과 |
|---|---:|
| Old/new deterministic Projection | **23,840 / 23,840 동일** |
| Runtime dependency/status/order graph | **12 / 12 동일** |
| Saved affected graph | **9 / 9 동일** |
| Targeted / projection contract | **321 passed / 3 subtests** |
| rag_core | **2176 passed / 0 failed / 695 subtests** |
| rag_chat | **155 passed / 동일 known legacy failure 1건 / 15 subtests** |
| 기존 assertion 변경 / 신규 regression | **0 / 0** |

이 판정은 host source의 behavior-preserving extraction에 한정한다. **18002/18012 변경 없음**, Full QA57·Strict 갱신·Product Golden 변경·image build/deploy·Step 11·commit/push 없음.

## 1. 기준점과 재현 evidence

- HEAD: `979fd3f980bb10af74a218cc6e07bada110e76de` + Step 1–9 누적 working tree. clean HEAD를 실행 기준으로 주장하지 않는다.
- 직전 artifact: `documents/meta/CATALOG_OWNERSHIP_STEP9_20261004.md`, `READY_WITH_KNOWN_DEBT`.
- Baseline: core 2081/2081, chat 155/156(동일 known failure), live 2821 LOC / Factory 493 LOC / `_derive` 164 LOC / central operator conditions 6.
- Step9 sealed evidence 45개 파일 checksum 불변을 다시 확인했다.
- 새 durable evidence: `/home/nuri/.codex/validation-evidence/projection-step10-20261004`.
- Frozen before live, 변경한 기존 test 9개, after source/test, iteration diff, characterization, differential, graph, logs, structural proof, 독립 감사, container identity, manifest를 보존한다.
- Container ID / image ID / Created / StartedAt / config hash / mounts 전후 동일. 18012는 `komir-temporal-step7` 유지하며 이번 host 변경을 배포하지 않았다.
- Behavioral Reference와 `NOT_CERTIFIED_WITH_KNOWN_REASONS` Product Golden을 구분한다. dummy/known-invalid behavior를 고치거나 재인증하지 않는다.

## 2. Projection Responsibility Pre-audit

`iterative-audit` HIGH 기준의 Architecture/Complexity/Decomposition/Regression Guard를 적용했다. `qa-build`는 QA fixture나 oracle 변경이 아니라 boundary characterization과 등록형 execution regression에만 사용했다. 구현 1회, targeted 검증, 독립 read-only audit 순으로 진행했다.

아래 10개 책임 그룹을 이번 before/after 집계 단위로 사용한다. 개별 조건문 수와 책임 수를 혼동하지 않는다.

| 구분 | 기존 책임 | 이번 owner / 판단 |
|---|---|---|
| A1 Canonical | alias 형식·reserved unit·output collision 검증 | `projection._alias_failure` |
| A2 Canonical | canonical field resolution, missing/incomplete 판정 | `projection._resolve_fields` + 기존 resolver 주입 |
| A3 Canonical | field selection/rename/distinct | `projection._select_rows` |
| A4 Canonical | TypedResult/envelope finalization | 기존 `_finalize_derived_rows`를 좁은 callable로 주입, 의미 미변경 |
| B1 Compatibility | empty list 조기 반환, PARTIAL row metadata 보존 | registered handler의 동일 실행 순서 유지 |
| B2 Compatibility | result-level unit/source/entity fallback | `_resolve_fields`에서 기존 cardinality 조건 그대로 |
| B3 Compatibility | heterogeneous row unit 경고 | handler에서 기존 집합 계산/경고 dedup 그대로 |
| C1 Domain | DocumentEvidence → MineralSet | `projection_compatibility.document_minerals`; 의미 재설계 보류 |
| C2 Domain | legacy optional price identity / 자동 보존 | `projection_compatibility.price_identity_fields`; 세 pass 순서 그대로 |
| C3 Domain | inventory/value 및 metric-specific fallback | `projection_compatibility.metric_value_key`; 기존 map만 이동 |

사전 책임 점검의 결론:

1. 기존 `_derive`는 canonical projection, domain transformation, compatibility 정책을 동시에 소유했다. PROJECT 실행 이관은 이번 승인 범위다.
2. 기존 StepFactory/FunctionStep/TypedResult 경계와 resolver/finalizer가 이미 있으므로 새 framework, class hierarchy, parallel type system은 필요 없다.
3. semantic owner는 기존 resolver, Step9 domain spec, 기존 helper다. handler가 output guarantee나 physical alias를 새로 정의하면 안 된다.
4. 새 domain 개념이나 QA 의미를 추가하지 않는다. 중앙 dispatcher의 legacy 조건 두 개를 제거하고 기존 registry에 PROJECT 구현을 연결한다.
5. domain compatibility를 canonical code와 분리하되, 동등하지 않은 legacy literal 순서와 catalog 순서를 억지 통합하지 않는다.
6. 전체 branch를 God Handler로 복사하지 않고 validation / resolution / row selection / 세 compatibility 함수의 명시적 composition으로 재구성한다.

## 3. 실행 경계와 좁은 dependency

```text
PROJECT RequirementNode
  → existing StepFactory registration
  → build_projection_step
      ├─ alias validation
      ├─ existing document/price/metric compatibility
      ├─ canonical resolver + metadata fallback
      └─ row projection / PARTIAL preservation / distinct
  → existing finalizer
  → existing FunctionStep / PipeRuntime / TypedResult
```

- 새 `operator_handlers/projection.py`: 98 LOC, canonical orchestration과 작은 pure helper.
- 새 `operator_handlers/projection_compatibility.py`: 93 LOC, 기존 세 domain compatibility 책임의 relocation. 새 semantic owner를 병렬로 생성하지 않는다.
- 주입 dependency는 `resolve`, `entity_values`, `evidence_rows`, `finalize` 네 callable뿐이다. handler가 live module이나 Factory 전체를 역참조하지 않는다.
- price identity는 기존 `capability_identity_fields` → Step9 `capability_specs.price` lookup을 read-only로 소비한다. allowed/guaranteed/optional/args-dependent/type/alias 선언은 변경하지 않았다.
- node ID / operator name / dependencies / bindings를 기존 FunctionStep에 그대로 전달한다. `next(iter(inputs.values()))`의 기존 first InputRef 선택도 그대로다.
- `_derive`는 5 LOC generic row passthrough만 남는다. PROJECT private 실행 API로 유지하지 않으며, 저장소 내 직접 호출은 0이다. 다른 테스트가 registered routing을 검증하는 monkeypatch 지점으로는 남아 있다.
- `_finalize_derived_rows`의 PROJECT + COMPOSITE → FACT_SET 호환 분기는 그대로다. 이를 새 handler에 복제하지 않고 기존 callable로 사용한다. 이 잔여 책임은 아래 deferred inventory에 명시한다.

## 4. Behavior characterization / 보존 결과

검증은 기존 성공뿐 아니라 실패·abstain·예외·조기 반환도 포함한다.

| Boundary | 보존한 실제 behavior |
|---|---|
| alias 형식 | `args.get('aliases') or {}` 기존 falsy 취급과 `invalid_projection_alias` 유지 |
| reserved unit | 기존 strict resolver 기준으로 비unit→unit alias를 `projection_reserved_unit_alias`로 거절 |
| collision | identity 자동추가 **이전** requested field collision 검사 순서 유지; 새 사후 collision 검사 없음 |
| document→entity | DOCUMENT_EVIDENCE + `minerals`/`mineral_list`만 기존 transformation. rows 우선, evidence fallback. empty면 기존 `document_mineral_list_unavailable` |
| empty | source.value가 빈 list면 field 검증보다 먼저 value=[] / entity=() 조기 반환. status/type 보존 |
| heterogeneous unit | row unit 또는 source.unit 집합으로 기존 경고를 생성하고 dedup. unit 보정 없음 |
| price identity | literal `price_measure` 존재 여부 pass, literal identity append pass, registry identity pass의 순서와 optional 처리 보존 |
| criterion modes | REPRESENTATIVE / EXPLICIT / ALL의 입력 identity와 row 수 보존. Projection이 criterion을 선택하거나 mode를 새로 해석하지 않음 |
| inventory/value | strict canonical resolver 실패 후에만 기존 metric-specific fallback. 임의 numeric field 선택 없음 |
| metadata fallback | unit이 non-None일 때, source/entity가 정확히 하나일 때만 기존 fallback |
| missing | `projection_field_unavailable:<field>` 유지. alias/metadata로 허용 범위 확대 없음 |
| incomplete | SUCCESS에서 resolved key가 일부 row에 없으면 `projection_input_incomplete`. 다른 status에 새 검증 추가 없음 |
| PARTIAL | projected row에 원본 status/reason/output/unit을 기존 순서로 덮어씀. 의미 개선 없음 |
| distinct | `distinct is True`와 JSON 기반 기존 dedup. `1`과 True의 identity 차이도 보존 |
| final envelope | 기존 result type/entity/unit/period/metric/evidence/source/provenance/warnings/confidence/lineage/failure 보존 |
| runtime barrier | FAILED / DEPENDENCY_FAILED / ABSTAINED / EMPTY / PARTIAL 등 기존 Runtime 처리와 InputRef order 보존 |

현재 literal price identity 순서는 `measure, label, criterion, serial`, Registry 순서는 `measure, criterion, label, serial`이다. 동등하지 않으므로 기존 두 순서를 유지했다. `price_measure` literal이 있는 non-price result에도 적용되는 기존 compatibility 역시 보존했다.

known-invalid behavior도 differential에 포함한다. 예를 들어 invalid hashable field/unit 입력의 기존 TypeError, document empty에서 새 empty envelope를 만드는 동작, PARTIAL metadata가 rename 결과를 덮어쓰는 동작을 이번 refactor에서 고치지 않았다.

## 5. Differential / runtime / regression

### 결정적 비교

- frozen Step9 live `_derive`와 현재 **실제 Factory 등록 handler**에 동일 입력을 전달했다.
- 745 source 변형 × 32 projection args = **23,840 cases**. source shape / result type / metric / ResultStatus / metadata cardinality / alias / identity / malformed field 등을 포함한다.
- dataclass 전체 값, list/tuple 및 scalar/key type tree, field/key 순서, exception type/message, 입력 불변을 비교했다. mismatch **0**.
- 이전 실행 결과가 예상값이며 oracle을 바꾸어 새 성공을 만든 것이 아니다.
- harness의 network connection을 금지했다. model/cache/source 변동을 deterministic Projection regression과 분리했다.
- runtime graph **12개**: 6개 ResultStatus × 두 InputRef 순서. 실제 PipeLowerer/PipeRuntime과 dependency barrier를 비교했다.
- saved graph **9개 / 6 QA ID**: GM02, ADD27, IX02, ADD25, REG06, ADD16. Step6 old/new와 Golden 저장 graph 변형이며 fresh QA 9건이 아니다.
- saved upstream은 저장 TypedResult를 `_retrieve` 경계에 주입했다. 실제 downstream PROJECT, graph, root, execution, presentation, SSE event 생성 old/new 동일. 실제 DB·LLM·live SSE 통합 인증은 아니다.
- REG06 DEPENDENCY_FAILED / ADD16 `comparison_alignment_required` abstain, 기타 저장 SUCCESS가 그대로다. QA recovery로 집계하지 않는다.

### Test boundary 유지

새 `test_registered_projection.py`: **95 cases / 351 LOC**. alias/collision/reserved unit, price modes, inventory, document, metadata, PARTIAL/EMPTY/FAIL, distinct, provenance, InputRef, runtime barrier 및 cancellation을 검증한다.

기존 9개 test 파일의 PROJECT 직접 `_derive` 호출 25곳을 기존 `execute_registered` helper를 통한 Factory 등록 경계로 옮겼다. bare assert와 unittest assert의 AST를 비교하여 **기존 assertion 내용 0 변경**을 확인했다. QA106의 최소 fake node는 실제 RequirementNode로 바꾸어 node/operator identity를 제공했다. QA fixture/corpus/oracle는 변경하지 않았다.

`execute_registered`의 직접 handler 호출만으로 Runtime barrier를 검증했다고 주장하지 않는다. 별도의 runtime graph 및 cancellation tests를 사용했다.

### 실제 실행 commands

repository root, 동일 환경과 동일 regression scope:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:inhouse:inhouse/rag_chat python3 /tmp/komir-projection-step10.SiyE7E/validate_projection.py before
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:inhouse:inhouse/rag_chat python3 /tmp/komir-projection-step10.SiyE7E/validate_projection.py diff
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:inhouse:inhouse/rag_chat python3 /tmp/komir-projection-step10.SiyE7E/validate_projection.py runtime
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:inhouse:inhouse/rag_chat python3 /tmp/komir-projection-step10.SiyE7E/validate_projection.py saved
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:inhouse:inhouse/rag_chat python3 -m pytest -q -p no:cacheprovider inhouse/rag_core/tests/test_registered_projection.py inhouse/rag_core/tests/test_live_audit_safety.py inhouse/rag_core/tests/test_live_multihop.py inhouse/rag_core/tests/test_live_contract_repair.py inhouse/rag_core/tests/test_live_price_fanout.py inhouse/rag_core/tests/test_live_relations.py inhouse/rag_core/tests/test_qa500_contract_matrix.py inhouse/rag_core/tests/test_qa500_common_contracts.py inhouse/rag_core/tests/test_price_criterion_cardinality.py inhouse/rag_core/tests/test_qa106_contract_repairs.py
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:inhouse:inhouse/rag_chat python3 -m pytest -q -p no:cacheprovider inhouse/rag_core/tests
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:inhouse:inhouse/rag_chat python3 -m pytest -q -p no:cacheprovider inhouse/rag_chat/tests
PYTHONDONTWRITEBYTECODE=1 python3 /tmp/komir-projection-step10.SiyE7E/measure.py
git diff --check
```

- Targeted **321 passed**, 3 subtests, 3.20s. 기존 targeted 226 + 신규 95.
- Core **2176 passed** = baseline 2081 + 신규 95, 695 subtests, 42.47s. 기존 Pydantic lifespan warning 1개 유지.
- Chat **155 passed / 1 known legacy failure**, 15 subtests, 6.40s.
- 동일 known failure: `test_sse_cancellation.py::test_disconnect_stops_real_ast_retry_before_blocking_invocation_returns[legacy_control-False]`.
- live의 top-level 함수들과 Factory의 build/_build_legacy/_derive 이외 모든 method는 frozen AST와 동일. resolver/finalizer, planner, source adapter, History, Renderer, coverage를 변경하지 않았다.
- 독립 read-only 감사: High/Critical finding 0. 기존 private test 경로가 bypass될 수 있다는 지적은 실제 registered 경로로 옮기고 기존 assertion을 보존하여 해소했다.

## 6. 구조 측정 / Responsibility delta

LOC는 물리적 line 기준, class/function은 AST lineno~end_lineno 포함이다. central operator conditions는 Factory 내부에서 `node.operator`를 검사하는 If 개수로 기존 Step9와 동일하게 계산했다. builder registry key는 if branch로 세지 않는다.

| 지표 | Before | After | Delta |
|---|---:|---:|---:|
| live_multihop.py LOC | 2821 | 2666 | -155 |
| LiveOperatorFactory LOC | 493 | 337 | -156 |
| `_derive` LOC | 164 | 5 | -159 |
| Central operator conditions | 6 | 4 | -2 |
| legacy PROJECT 실행 body LOC | 157 | 0 | -157 |
| legacy PROJECT branch (if 포함) LOC | 158 | 0 | -158 |
| legacy PROJECT builder route LOC | 2 | 0 | -2 |
| Projection handler module LOC | 0 | 98 | +98 |
| Compatibility dependency module LOC | 0 | 93 | +93 |
| 가장 큰 신규 handler function | 0 | 42 | orchestration, nested execute 31 |
| 가장 큰 compatibility function | 0 | 48 | price identity 세 pass |
| Projection 의미 책임 그룹 전체 | 10 | 10 | 의미 삭제/추가 0 |
| `_derive`가 직접 소유한 Projection 책임 그룹 | 10 | 0 | handler/helpers로 분산 |

최종 `_derive` 책임은 입력의 첫 TypedResult 선택 → list/mapping row shape → 기존 finalizer 호출뿐이다. 실행 경로에서 호출되지 않는 잔여 private passthrough이며, 후속 cleanup 때 제거 여부를 판단할 수 있다. 새로운 domain responsibility를 추가할 자리가 아니다.

실패 owner를 `_alias_failure`, `_resolve_fields`, compatibility helper, 기존 finalizer/Runtime으로 좁힐 수 있다. 동일 계열 execution은 기존 등록 경계에서 교체/조합할 수 있고 중앙 legacy branch를 다시 늘릴 필요가 없다. 단 모든 domain semantic debt가 해소되었다고 주장하지 않는다.

## 7. DEFERRED_PROJECTION_RESPONSIBILITY

| 남은 책임 / 중복 | 이번 유지 이유 | 향후 owner 후보 |
|---|---|---|
| literal price identity optional 처리와 Registry identity 순서 | 순서와 조건이 실제로 다름. 단순 union/보장 승격은 semantic change | 승인된 별도 domain output contract 정리 |
| inventory/metric fallback physical 별칭 | 기존 strict resolver 뒤에 적용되는 compatibility. 새 canonical alias와 동등성 미확정 | Capability Output Spec / source adapter |
| document→MineralSet transformation | empty/failure/evidence 우선순위까지 기존 동작 보존 필요 | document output contract / 별도 typed transformation 경계 |
| unit/source/entity metadata fallback | row-level 보장과 result metadata는 다른 계약 | 기존 TypedResult contract를 명시화하는 별도 작업 |
| `_finalize_derived_rows` PROJECT+COMPOSITE→FACT_SET | shared finalizer를 이번에 재설계하거나 type 정책을 옮겨 복제하지 않음 | 후속 common envelope 책임 정리 |
| resolver / physical alias / catalog output 목록 | 허용 집합·실제 row resolution·guaranteed의 동등성 없음 | Step9 DEFERRED_CONTRACT_OWNERSHIP 그대로 |

Domain compatibility 모듈은 세 개 독립 이유를 가지므로 `DECOMPOSITION_REVIEW_REQUIRED`가 남는다. 각각 작은 함수로 분리되고 canonical handler와 dependency 방향은 분리됐지만, 앞으로 source adapter/spec으로 의미를 옮길지는 추가 동등성 증명이 필요하다. 단순 파일 수 증가를 위한 재분해는 하지 않는다.

## 8. Complexity Delta

- Files changed: production **3**(기존 live 1 + 신규 handler/compatibility 2), tests **10**(기존 9 + 신규 1), artifact **1**. 이전 Steps의 누적 dirty changes 제외.
- New classes: **0**.
- New public semantic contracts: **0**. 내부 builder/helper relocation이며 새 Protocol/framework 0.
- New registry entries: 기존 operator PROJECT의 implementation registration **+1**; Capability/semantic catalog entry **+0**.
- New QA/question/entity/answer special-case branches: **0**.
- New central-dispatch branches: **0**; removed central operator branches: **2**.
- Duplicated contract sources added / removed: **0 / 0**. 기존 중복/호환 literal을 이동했으며 정리 완료라고 주장하지 않는다.
- Largest actually modified Factory method: `build` **44 LOC**. 신규 pure helper 최대 **48 LOC**.
- Largest modified class: LiveOperatorFactory **337 LOC**.
- Largest modified module: live_multihop **2666 LOC**. 기존 `_normalize_relation_contract` **398 LOC**는 미변경.
- Responsibility growth: **false**. 새 의미 없이 중앙 PROJECT 실행 책임만 감소. 기존 compatibility debt는 명시적으로 유지.
- Verdict: **COMPLEXITY_WARN / REFACTOR_CANDIDATE**. scoped extraction acceptance는 PASS지만 live >1500 LOC, 기존 >200 LOC 함수, compatibility의 독립 변경 이유 3개로 `DECOMPOSITION_REVIEW_REQUIRED`가 남는다.

## 9. Contract Delta

- New / modified / removed **semantic contracts: 0 / 0 / 0**.
- Structural contract change: PROJECT registration과 좁은 callable dependency. 실제 실행은 동일 FunctionStep/PipeRuntime/TypedResult.
- Canonical source of truth: 기존 canonical field resolver, 기존 TypedResult, Step9 `capability_specs.price` identity tuple(기존 lookup 경유), 기존 finalizer.
- Consumers: registered Projection handler와 명시적 compatibility dependency. 기존 Registry/IR/coverage consumer acceptance는 그대로.
- Removed implementation: `_derive` legacy PROJECT body 및 `_build_legacy` PROJECT dispatch. 동일 logic를 양쪽에 남기지 않았다.
- Remaining duplicated mappings: §7. allowed/guaranteed/optional/args-dependent/type/physical alias는 통합하지 않았다.
- Public request/result schema, semantic type, alias members, criterion policy, output guarantee, calculation, source query, planner/coverage, oracle 변화 **0**.

## 10. Rollback / 종료

Rollback은 이번 live 세 method/import/registration 변경, 신규 두 module, 기존 test 호출 경계 변경 및 신규 test만 대상으로 한다. 이전 Steps까지 지우는 HEAD reset은 사용하지 않는다. Frozen source와 per-file iteration diff를 evidence에 저장한다.

이전 known failure/status/provenance/contamination을 보존했으며 새 PASS/Strict 증가를 집계하지 않는다. 새 evidence는 checksum manifest와 read-only 권한으로 봉인한다. 이는 Git clean commit이나 배포 certification을 대신하지 않는다.

**Step 10에서 종료한다. Step 11 Coverage Diagnostics 자동 진행 없음. Full QA57 / Strict / Product Golden / 18002·18012 변경 없음.**
