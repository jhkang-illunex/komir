# Architecture Migration Step 6 — Relation builder extraction

## Acceptance

**`PASS_SCOPED_RELATION_ROUTING_PARITY`** — JOIN/COMPARE의 등록·routing만 이관했다. `execute_relation` 내부 알고리즘은 byte/checksum까지 동일하다. 기존 legacy delegation 및 도달 불가능한 COMPARE PARTIAL guard를 제거했다.

- rag_core: **1672 → 1691 passed / 0 failed** (새 characterization 19건).
- rag_chat: **155 passed / 동일 known legacy failure 1건**.
- 운영 18002, 원천 DB, QA oracle, Strict 기준 변경 없음.
- QA57 Full Replay, GM14/IX02/ADD25 recovery, Step 7 진행 없음.
- 이 판정은 immutable Behavioral Reference 기반 기계적 추출 범위다. Certified Product Golden의 기존 미인증/contamination 상태를 해결하거나 재인증하지 않는다.

## 1. Identity / source / 실행 경계

| 항목 | 확인값 |
|---|---|
| git parent | `979fd3f980bb10af74a218cc6e07bada110e76de` |
| 실제 source | 기존 승인 Step 1–5 working tree + Step 6; clean Golden SHA라고 표시하지 않음 |
| old image | `komir-rag-chat:calculation-step5-20261003` |
| old image ID | `sha256:84e763798fa8aa672cc265fe550881ccdf625cc08277681f35ebaaf1dffa4037` |
| new image | `komir-rag-chat:relation-step6-20261003` |
| new image ID | `sha256:e6d23fe258c1f17ae45fbe1b583c7c0e9fb61a6de29b558487eb91945c25e0a0` |
| validation container | `komir-relation-step6`, `127.0.0.1:18012` |
| source preflight | host/container **229 files checksum 일치**, image ID 일치 |
| runtime config | env/extra_hosts/network/readonly mount 동일; Gemma/MCP/health 정상 |
| 원천 DB fingerprint | 전후 `341be4d0d4316a9cd4da90aaaa952f38d931a1e344910ff21bf24d8d18e71954` 동일 |
| protected production | `komir-rag-chat-18002` Id/Image/StartedAt/mount 내용 불변 |
| evidence | `/home/nuri/.codex/validation-evidence/relation-step6-20261003` |

image에 parent revision/build timestamp label을 기록했다. local image ID와 실제 container Image를 비교하며 없는 registry RepoDigest를 생성하지 않았다. env-file secret은 artifact에 저장하지 않았다. 새 프로세스로 module cache를 교체하되 기존 config/resource를 변경하지 않았다. 후보 live 요청은 preflight PASS 이후 실행했다.

Frozen old `live_multihop.py`는 old container 실제 파일 및 Step 5 sealed source checksum과 일치한다. Step 5 evidence **66파일** 모두 무변경 확인했다. 원천 DB fingerprint 범위는 기존 `public/mineral_risk`; fresh session 저장 `ai_chatbot`은 source mutation과 구분한다. Docker mount 배열 순서는 destination 정렬 후 전체 속성을 비교했다.

## 2. 사전 책임/contract 감사

| Pre-change check | 결론 |
|---|---|
| 현재 책임 | Factory가 JOIN/COMPARE를 `_derive`로 dispatch하고, `_derive`가 즉시 helper에 위임 |
| 적절한 경계 | 기존 StepFactory dictionary → registered builder → FunctionStep |
| semantic owner | `relational_ops.execute_relation`; canonical field resolution은 기존 resolver |
| 새 개념 유입 | 없음; 기존 두 operator 등록 위치만 이동 |
| 중복 source of truth | 새 alias/key/unit/role mapping 생성 없음 |
| 재사용성 | JOIN/COMPARE 모든 node에 적용; QA/질문/entity 분기 없음 |
| 중앙 분기 증가 | 없음; 조건 2개 제거 |
| 구조 변경 필요성 | 승인된 Strangler migration이며 새 framework/scheduler 불필요 |
| 검증/소유권 | 주 agent만 파일 수정; 독립 감사자는 read-only. 승인 scope CRITICAL audit, 구현 1회 |
| 종료 조건 | deterministic parity + 동일 regression scope 확인 후 Step 6에서 종료 |

### 기존 실행 순서

```text
StepFactory legacy JOIN/COMPARE
  → FunctionStep → _derive
      → execute_relation(node, inputs, strict resolver) [즉시 return]
      → COMPARE PARTIAL guard [도달 불가능]
```

이관 후:

```text
StepFactory JOIN/COMPARE registrations
  → build_relation_step
  → existing FunctionStep
  → execute_relation(동일 node, 동일 ordered inputs, 동일 strict resolver)
  → existing TypedResult / PipeRuntime
```

handler는 input을 복사·정렬하거나 검증하지 않는다. resolver callback adaptation과 FunctionStep 생성만 담당한다. `InputRef → input_0/input_1 → inputs.values()` 순서를 유지한다. named left/right role 추론이나 완료 순서 기반 operand 선택을 추가하지 않았다.

### 보존한 주요 계약

| 경계 | 기존 동작 — 변경 없음 |
|---|---|
| arity | exactly 2; 그 외 `relation_requires_two_inputs` |
| dependency barrier | PipeRuntime가 FAILED/ABSTAINED/DEPENDENCY_FAILED upstream을 차단. handler 직접 호출 시 helper의 status 정책 적용 |
| status/evidence | helper는 SUCCESS/EMPTY/PARTIAL 분기 유지; EMPTY→dependency_unavailable, insufficient/evidence→evidence_insufficient |
| PARTIAL | 명시된 row status 정책 유지. helper 전에 `incomplete_population`으로 일괄 변환하지 않음 |
| keys/cardinality | typed key identity, null/invalid key 거절, duplicate cardinality 거절, 기존 join mode 유지 |
| compare | side_by_side/difference/ratio/percent_change 및 scalar broadcast의 기존 field/unit/denominator 정책 유지 |
| temporal continuation | 기존 helper 내부 branch 그대로; 분리/alias/criterion/date policy 개선 없음 |
| provenance/lineage | entity/source/provenance/warnings의 기존 순서·dedup, evidence concatenation, node.inputs 기반 upstream IDs 유지 |
| period/unit | 같은 period 유지/다르면 None, 연산별 unit 및 mismatch/failure 그대로 |
| failure/exception | helper의 ValueError 처리 범위와 나머지 exception 전달 그대로; retry/timeout 정책 추가 없음 |

비교 알고리즘이나 positional join 동작을 개선하지 않았다. 형식/상태가 제품 요구에 충분한지와 별개로 기존 known-invalid behavior를 보존했다.

## 3. 실제 수정 범위

- `operator_handlers/relation.py`: **21 LOC**, builder **12 LOC**. 기존 `execute_relation` 단일 호출만 수행.
- `live_multihop.py`: JOIN/COMPARE를 같은 partial builder로 등록. legacy routing에서 두 operator 제외. `_derive`의 delegation 2 LOC와 unreachable PARTIAL guard 4 LOC 제거.
- 기존 tests 3파일: JOIN/COMPARE private `_derive` 호출을 기존 `execute_registered`로 이동. assertions/fixture 의미는 불변.
- `test_registered_relation.py`: 19개 characterization tests 추가.
- `relational_ops.py`, PipeRuntime, lowering, Capability/Planner/History/Renderer/Projection 계산 body: 변경 없음.

Factory의 다른 methods/module helpers와 `_derive`의 나머지 전체 AST가 frozen Step 5와 동일함을 확인했다. 형식상 import 경로와 routing만 바뀌며 새로운 relation semantic metadata를 선언하지 않았다.

## 4. Deterministic / runtime / regression

| 검증 | 결과 |
|---|---:|
| frozen 실제 Step 5 vs new boundary differential | **6092/6092 동일** |
| PipeLowerer/PipeRuntime/root/presentation/SSE graph parity | **72/72 동일** |
| 후보 container differential | host와 전체 JSON 동일 |
| 저장 Golden Relation graph | **6/6 동일** |
| 이번 live graph/source 고정 교차 실행 | **11/11 동일**, Relation 포함 graph 7개 |
| targeted | **235 passed**, 3 subtests; 2.27s |
| rag_core 전체 | **1691 passed**, 695 subtests; 41.19s |
| rag_chat 동일 scope | **155 passed / known failure 1**, 15 subtests; 6.46s |

6092 matrix는 JOIN modes, 모든 comparison family, temporal continuation, 0–3 inputs, null/invalid/duplicate/typed keys, scalar broadcast, field invalidity, unit/period/entity/evidence/warnings, 모든 ResultStatus 조합을 포함한다. TypedResult 모든 필드 및 exception type/message와 step identity/defaults를 비교했다.

72 runtime graph는 JOIN/COMPARE, reverse InputRef, all/index/field selector, status propagation과 barrier를 검사한다. left source 완료를 지연시켜 completion order가 right→left여도 InputRef role이 유지되는지 검증했다. 새 단위 tests는 helper 인자 객체 identity, strict resolver, PARTIAL precedence, cancel-before-execute, timeout=None/retry=0을 확인한다. scheduler 알고리즘은 손대지 않았다.

저장 Golden 6개: GM01, GM02, REG06, PF03, ADD16, ADD25. GM01/GM02의 기존 success 및 나머지의 dependency_failed/comparison_alignment_required/dependency_unavailable도 동일하다. 이를 신규 recovery로 해석하지 않는다.

### 동일 regression command

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:inhouse:inhouse/rag_chat python3 /tmp/komir-relation-step6.ZGCepP/differential.py
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:inhouse:inhouse/rag_chat python3 -m pytest -q -p no:cacheprovider inhouse/rag_core/tests/test_registered_relation.py inhouse/rag_core/tests/test_live_relations.py inhouse/rag_core/tests/test_qa500_series.py inhouse/rag_core/tests/test_qa500_common_contracts.py inhouse/rag_core/tests/test_live_audit_safety.py
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:inhouse:inhouse/rag_chat python3 -m pytest -q -p no:cacheprovider inhouse/rag_core/tests
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:inhouse:inhouse/rag_chat python3 -m pytest -q -p no:cacheprovider inhouse/rag_chat/tests
```

Known rag_chat failure: `test_sse_cancellation.py::test_disconnect_stops_real_ast_retry_before_blocking_invocation_returns[legacy_control-False]`, expected calls3/actual4로 동일. skip/xfail/oracle 완화 없음. 기존 pydantic warning1도 유지했다.

## 5. Live 변동 — execution parity와 분리

old/new 각6회, 모두 fresh session; Full QA57 아님. SSE terminal은 12회 모두 정확히 한 번 종료했다.

| QA | latest old→new 관찰 | 최초 차이 / 해석 |
|---|---|---|
| GM01 | answer/terminal/graph 동일, TypedResult evidence 일부 다름 | trade upstream retrieval evidence text/section부터 다름; 고정 input executor 결과 동일 |
| GM02 | answer/graph 동일, citation/TypedResult provenance 다름 | trade upstream document evidence source부터 다름; 동일 relation은 그대로 전파 |
| IX02 | old semantic_plan_incomplete, new executable compare graph | old는 execution graph 없음. Planning 이전 차이; recovery 집계 금지 |
| ADD25 | old 5-node compare graph 실패, new 8-node join graph 실행 | 생성 graph부터 다름. 양 graph는 각각 old/new executor에서 동일한 failure/success 재현 |
| REG02 | raw/terminal/graph/TypedResult 모두 동일 | 변화 없음 |
| ADD27 | raw/terminal/graph/TypedResult 모두 동일 | 변화 없음 |

정확한 수: raw answer **4/6**, terminal **3/6**, program **4/6**(1개 차이, 1개 old graph 없음), TypedResult **2/6**(3개 차이, 1개 비교 불가). 이를 live 전체 동일성이나 안정성 증명으로 표현하지 않는다.

graph가 존재하는 11개를 각각의 저장 upstream TypedResult로 고정하여 old/new 모두 실행한 결과 **11/11 동일**했다. old IX02는 `NO_EXECUTABLE_GRAPH:semantic_plan_incomplete`로 별도 저장하고 parity 측정했다고 주장하지 않는다. 최초 cross-replay harness의 missing snapshot 예외를 이 명시적 미측정 상태로 기록했다. QA oracle/제품 코드는 변경하지 않았다.

상태가 좋아 보이는 IX02/ADD25도 Strict PASS나 Layer Recovery로 계산하지 않았다. Planner/retrieval 변동의 세부 원인을 이번 routing refactor에서 고치거나 단정하지 않는다. input이 다른 live 결과와 deterministic execution regression을 구분한다.

## 6. 구조 지표와 남은 책임

측정 기준은 기존 Steps와 동일하다: physical module LOC, AST start/end class/method LOC, Factory 내부 If.test에 `.operator`가 있는 condition 수.

| 지표 | Before | After |
|---|---:|---:|
| live_multihop.py | 2928 | **2928** |
| LiveOperatorFactory | 493 | **493** |
| `_derive` | 170 | **164** |
| central operator conditions | 8 | **6** |
| legacy Relation delegation | 2 | **0** |
| unreachable COMPARE PARTIAL guard | 4 | **0** |
| Relation handler module / builder | 0 / 0 | **21 / 12** |
| relational_ops.py / execute_relation | 323 / 308 | **323 / 308** (checksum 불변) |

module/class LOC는 등록부가 추가돼 순감소하지 않았다. 구조 이익은 LOC 축소가 아니라 중앙 실행 경로의 Relation 책임/조건 감소와 기존 등록 경계 사용이다. `_derive`에는 이제 Projection과 공통 input-row adaptation/finalization만 남았다.

`execute_relation`에는 다음 책임이 그대로 남는다:

1. arity/status/evidence preconditions와 metadata composition.
2. structured row adaptation, key validation/indexing/cardinality, join modes.
3. scalar broadcast와 side-by-side field 선택/alignment.
4. arithmetic comparison과 unit/zero/invalid operand 처리.
5. temporal continuation date boundary/concatenation.
6. row outcome masking, aggregate status, provenance/lineage output.

이는 **308 LOC / 독립 변경 이유3+**로 `DECOMPOSITION_REVIEW_REQUIRED`다. 이번 승인은 builder extraction만이므로 알고리즘/temporal continuation 분해를 하지 않았다. handler 소유자는 명확해졌지만 Relation 내부 실패를 국소 component로 나누는 작업까지 완료한 것은 아니다.

## 7. Complexity Delta

- Files changed 이번 scope: **application2 + tests4 + artifact1**. 이전 Step/skill dirty changes는 보존했다.
- New classes **0**, public semantic contracts **0**, 내부 builder **1**.
- Registry entries **+2** (기존 JOIN/COMPARE; capability/operator 신규0).
- QA/question/entity special cases **0**, answer hardcoding **0**.
- New central-dispatch branches **0**, removed central conditions **2**.
- Duplicated contract sources added/removed **0/0**; algorithm duplication **0**.
- Largest modified method/class/module LOC **164 / 493 / 2928**.
- Responsibility growth **false**. Factory의 Relation delegation 책임 감소. handler는 domain algorithm/field mapping을 소유하지 않음.
- 이관 범위의 책임 분리와 contract 보존은 PASS. 전체에는 **COMPLEXITY_WARN / DECOMPOSITION_REVIEW_REQUIRED**가 남는다. `_derive`164와 `execute_relation`308의 복수 HIGH 크기 부채는 **REFACTOR_REQUIRED(기존 부채, 별도 승인 범위)**로 기록한다. 이번 작업에서 부채를 확대하지 않았으며 이 표시는 추가 리팩터링 권한이 아니다.

## 8. Contract Delta

| 항목 | 결과 |
|---|---|
| New/removed semantic contracts | 0 / 0 |
| Modified contract | 실행 entry만 legacy derive→registered Relation builder |
| Canonical owner | relational_ops.execute_relation; 기존 strict field resolver |
| Consumers | 기존 StepFactory/FunctionStep/PipeRuntime; TypedResult/Projection/Renderer 불변 |
| dependency identity owner | 기존 PipeLowerer InputRef bindings와 PipeRuntime barrier |
| Remaining duplicate candidates | 기존 side_by_side preferred field/legacy alias/Projection mapping 부채. 복제·통합하지 않음 |
| semantic changes | role/key/cardinality/unit/period/temporal/failure/provenance 정책 변경0 |

## 9. 최종 범위 확인

Independent read-only audit는 입력 identity/order, unreachable guard 제거, FunctionStep 기본 동작, unchanged helper checksum에서 HIGH/CRITICAL drift를 발견하지 않았다. 별도 executable evidence가 위 acceptance를 뒷받침한다.

`acceptance.json`은 frozen/actual source identity, host/container differential, source DB fingerprint, protected18002, 기존 Step5 sealed evidence, unchanged helper/다른 methods/Projection remainder, regression 수를 검증한다. raw evidence와 scripts/source snapshot은 새 private bundle의 `manifest.json`으로 봉인한다.

**Step 6에서 종료한다. Step 7, Full QA57, Strict 갱신, 18002 배포, commit/push는 실행하지 않았다.**
