# Architecture Cleanup Step 1 — Aggregate Migration

## 결론

**Step 1 acceptance: PASS — Aggregate 범위의 behavior-preserving migration.**

- Behavioral Reference V1의 봉인된 Aggregate 입력 2건 및 전체 graph 2건에서 old/new 일치.
- 추가 결정론적 경계조건 146건 일치. status/failure 변화 0.
- `rag_core`: **1573 passed / 0 failed** — 기존 1560 + 신규 등록 경로 테스트 13.
- `rag_chat`: **155 passed / 기존 known legacy failure 1건**, 신규 failure 0.
- 18012에서만 candidate 검증. **18002 미변경**, Full QA57 미실행, Step 2 미시작.
- 신규 PASS/Strict 상승으로 계산하지 않는다. Certified Product Golden은
  **NOT_CERTIFIED_WITH_KNOWN_REASONS** 그대로다.

## 1. 기준점과 검증 identity

| 항목 | 값 |
|---|---|
| Golden parent SHA | `979fd3f980bb10af74a218cc6e07bada110e76de` |
| branch | `multihop_work` |
| 변경 상태 | Golden parent + 본 Aggregate extraction working-tree diff; 새 commit 아님 |
| Golden image | `sha256:a4fbcf8ee2f65b9869ef9fbb79d2ab60ea9dbc5fb98978ec0660949a8a3a2f0c` |
| candidate tag | `komir-rag-chat:aggregate-step1-20261003` |
| candidate image ID | `sha256:2403b1a7ba8e607261aaeb286e13445e13fc7e4eccaf2b527b2e5ebf250af571` |
| RepoDigests | `[]` — 위 SHA는 local image ID이며 registry manifest digest라고 부르지 않음 |
| candidate container | `komir-aggregate-step1` / `94a2d1a577d180c3d2bc2bf2245c50e56cbdec626bb051e81336344bba41a16c` |
| endpoint | `127.0.0.1:18012` |
| source identity | host/container **223 files checksum 일치**, mismatch 0 |
| 환경 | Golden과 Env / extra_hosts / Docker network / readonly resource mounts 동일 |
| model | 기존 Gemma endpoint/model 유지, 사전 health 정상 |
| source | 기존 `komir-golden-v1-step0-db` clone와 readonly data_lake 유지, MCP 정상 |

Image revision label은 parent SHA이며, clean Golden source라는 의미가 아니다.
`komir.validation=aggregate-step1-working-tree` label, build timestamp,
전체 source checksum과 patch/new-file archive로 candidate를 구별한다.
기동 직후 첫 health 연결은 startup 중 reset됐으며, 정상 preflight 완료 **후에만** QA를 실행했다.

Golden container/image는 삭제하지 않고 rollback 가능하게 보존했다. REG02 인과 검증을 위해
18012를 잠시 Golden image로 되돌린 뒤 candidate로 복귀했다. 최종 18012는 candidate다.

## 2. Pre-change responsibility / scope check

- 위험도: architecture migration — CRITICAL 절차, 승인된 한 책임 추출에 한정.
- 한 iteration, 구현 라운드 1회. 검증 harness/test 호출 경로 보정은 production semantics 변경이 아님.
- 기존 owner: `_derive`가 Aggregate wrapper precondition과 다른 연산의 실행까지 소유.
- 목표 owner: `operator_handlers/aggregate.py`는 Aggregate `FunctionStep` 생성 및 기존 wrapper만 소유.
- reduction/null/group/order/unit 알고리즘 owner: **기존 `analytical_aggregate.aggregate` 그대로**.
- canonical field owner: **기존 `_resolve_row_field(..., strict=True)` 그대로**, callback 주입.
- 기존 확장점: `StepFactory` protocol / `LiveOperatorFactory.build` / `LegacyOperatorFactory` / `FunctionStep`.
- 새 개념·business rule·source schema·semantic mapping·public interface를 도입하지 않음.
- 신규 hierarchy/scheduler/execution layer 없음. 기존 책임의 위치만 변경.
- 금지 범위: ADD16 denominator, dummy/provenance 개선, REG04 60행 평균 개선, alias 통합,
  calculation unit, planner/selection, Projection, History, Renderer, oracle 모두 미수정.

## 3. 이동한 책임과 삭제한 legacy body

```text
PipeLowerer → 기존 StepFactory.build
           → 등록된 Aggregate builder
           → FunctionStep(existing handler contract)
           → analytical_aggregate.aggregate
           → 기존 PipeRuntime / TypedResult

미이관 operator → _build_legacy → 기존 _derive / retrieve / other path
```

`build`의 registry lookup으로 Aggregate builder를 선택하고 나머지만 `_build_legacy`로 보낸다.
`_derive`의 Aggregate 실행 body를 제거했고, legacy derive operator 집합 및 공유 PARTIAL
검사 대상에서도 Aggregate를 제거했다. 별도 compatibility Aggregate 실행 분기는 남기지 않았다.

옮긴 wrapper 순서는 그대로다.

1. **어느 input이든 PARTIAL이면** `abstain("incomplete_population")`.
2. 기존 mapping iteration 순서의 첫 source 선택. 없으면 `failed("missing_input")`.
3. args 복사. first/last이고 명시적 order_by가 없을 때, 기존 strict resolver가 canonical
   date를 resolve하는 경우에만 `order_by="date"` binding.
4. 기존 Aggregate primitive 호출.

기존 first-source 선택 정책을 새 dependency 추론으로 교정하지 않았다. 명시적 order_by,
null/group/unit 정책, source metadata와 known-invalid 결과는 변경하지 않는다.
node ID, operation, dependencies, bindings를 그대로 FunctionStep에 전달하며,
timeout=None / max_retries=0 및 기존 cancel/runtime propagation 경로를 유지한다.

## 4. Old/new deterministic differential

old는 별도 clean Golden checkout의 **실제 factory/build/runtime**을 실행했다.
new는 현재 checkout을 실행했다. 기대값을 새 구현으로 재작성하거나 oracle를 완화하지 않았다.

| 비교 | 결과 | 범위 |
|---|---:|---|
| 봉인된 Aggregate boundary REG02/REG04 | **2/2 identical** | 전체 TypedResult, step identity/config, bindings, Pipe events/status/results |
| 봉인된 전체 AAST REG02/REG04 | **2/2 identical** | 모든 노드 TypedResult, root, presentation, SSE, action/args, boundary call order/count |
| 봉인 output 대비 | **2/2 일치** | PipeRuntime이 붙이는 upstream_step_ids 포함 |
| 추가 경계조건 | **146/146 identical** | 10 aggregation × 2 null policy × 7 row 조건 + 6 result status |

boundary 함수만 호출하면 REG04의 `upstream_step_ids`는 비어 있고 PipeRuntime 후에
`retrieve_nickel_price`가 붙는다. **old/new 모두 동일하며 runtime 후 봉인 결과와 일치**한다.

경계조건은 reversed date, null, tie, empty, invalid numeric/bool, mixed unit,
SUCCESS/PARTIAL/EMPTY/FAILED/ABSTAINED/DEPENDENCY_FAILED를 포함한다.
전체 graph replay는 저장된 retrieval TypedResult를 주입하고 network tripwire를 걸었다.
양쪽 graph 모두 저장 retrieval boundary 호출 1회, Aggregate의 추가 backend/network 호출 0회다.
이는 **고정 입력 실험의 계측값**이며 live 전체 backend 호출 수로 일반화하지 않는다.

REG02의 canonical date ordered_last와 REG04의 **60행 평균**을 그대로 보존했다.
dummy evidence/provenance/warnings도 제거·정상화하지 않았다.

## 5. REG02 및 Aggregate 영향 QA live probe

Behavioral Reference V1의 57개 saved graph 중 Aggregate 노드가 있는 항목은 REG02/REG04 두 건이다.
candidate fresh session 각 3회, 추가 인과검증 Golden fresh REG02 3회만 실행했다.

| QA / 실행 | 결과 |
|---|---|
| REG02 candidate ×3 | 3/3 실행 성공, latest 값·날짜 및 terminal 유지. Step0 답변과 컬럼 구성은 다름 |
| REG02 Golden ×3 | candidate와 **3/3 graph / 모든 TypedResults / 답변 / terminal 동일** |
| REG04 candidate ×3 | **3/3 Step0 answer / terminal 동일**, Aggregate 실행 정상 |

### REG02 출력 차이의 최초 경계

Step0 saved plan: `entity → retrieve → project → aggregate(last)`.
현재 old/new live plan: `entity → retrieve(output=latest_value)`.

현재 live에는 Aggregate 노드 자체가 없다. 달라진 최초 경계는 **planner-generated graph**이며,
Golden image에서도 똑같이 재현됐다. source fingerprint는 동일하고 migration은 parser/selection을
수정하지 않았다. 따라서 **Aggregate refactor caused regression이 아님**을 paired run으로 확인했다.
정확한 model 내부 변동 원인까지 입증한 것은 아니다.

live REG02 ×3을 Aggregate 실행 ×3으로 표현하지 않는다. 실제 ordered_last 보존 근거는
봉인된 Aggregate 포함 graph와 boundary old/new differential 및 등록 경로 unit test다.
현재 graph의 새 필드/identity 노출도 Product PASS 개선으로 집계하지 않는다.

## 6. Regression 결과 — 사용자 지정 순서

1. saved Aggregate old/new differential.
2. Aggregate/contract targeted: **198 passed, 3 subtests**, 1.35s.
3. 추가 fixture/operator integration: **163 passed, 541 subtests**, 2.77s;
   REG02/REG04 fresh probe 및 REG02 paired-old 인과 검증.
4. rag_core 전체: **1573 passed, 695 subtests**, 40.66s.
5. rag_chat 동일 scope: **155 passed, 1 failed, 15 subtests**, 6.53s.
6. Behavioral Reference fingerprints / protected runtime / source 데이터 무결성 최종 확인.

정확한 전체 suite 명령:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:inhouse:inhouse/rag_chat python3 -m pytest -q -p no:cacheprovider inhouse/rag_core/tests
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:inhouse:inhouse/rag_chat python3 -m pytest -q -p no:cacheprovider inhouse/rag_chat/tests
```

동일 known legacy failure:
`test_sse_cancellation.py::test_disconnect_stops_real_ast_retry_before_blocking_invocation_returns[legacy_control-False]`
— 실제 model call 4, 기존 assertion 3. 수정/skip/완화하지 않았다.

기존 1560 test의 assertion/fixture/정답은 유지했다. Aggregate private `_derive` 호출만 등록된
builder/FunctionStep 경로로 바꿨다. 새 13개 테스트는 metadata, args 불변성, 명시적 정렬,
fail-closed, unused PARTIAL input, first-source/null 정책, ID/InputRef/dependency 순서,
runtime defaults/FAIL/ABSTAIN propagation/cancel을 확인한다.

## 7. Complexity Delta

| 항목 | 결과 |
|---|---:|
| Files changed — 프로젝트 구현/검증 | **13**: production 3, tests/helpers 10 |
| Artifact | 본 보고서 1; 기존 미추적 audit 문서 3개는 수정하지 않음 |
| New classes | 0 |
| New public contracts | 0 — 기존 builder / StepHandler 계약 구현만 추가 |
| New registry entries | 1 — Aggregate builder |
| QA / question / entity special-case branches | 0 / 0 / 0 |
| New central-dispatch branches | 0 |
| Removed central branches | 1 — legacy Aggregate 실행 분기 |
| Duplicated contract sources added/removed | 0 / 0 |
| Responsibility growth | 없음; Aggregate wrapper 책임을 class에서 이관 |
| `LiveOperatorFactory` LOC | **627 → 623** |
| `_derive` LOC | **352 → 337** |
| `_derive` 전체 AST If 수 | **72 → 67** |
| central operator 조건 수 | **15 → 14** |
| `live_multihop.py` LOC | **3057 → 3055** |
| 신규 Aggregate builder module | 40 LOC |

central operator 조건 수는 `LiveOperatorFactory` 내부의 AST If test가 `*.operator`를
참조하는 경우를 센 값이다. registry lookup은 if/elif 분기 증가가 아니다.
wrapper 내부 기존 conditional은 handler로 이동했으며 의미를 추가하지 않았다.

**이번 delta: COMPLEXITY_PASS.** `_derive`와 module/class의 기존 HIGH 크기 경고는 남는다.
전체 architecture debt는 승인된 단계적 cleanup 대상(`REFACTOR_CANDIDATE/REFACTOR_REQUIRED`)
이지 이번 작은 extraction으로 모두 해소됐다는 뜻이 아니다. 이번 수정 method 최대 LOC는 337이며,
module 내 최대 function 398 LOC는 변경하지 않은 기존 영역이다.

## 8. Contract Delta / Single Source of Truth

| 항목 | 결과 |
|---|---|
| New semantic contracts/types | 없음 |
| Modified semantic contracts | 없음 |
| Removed semantic contracts | 없음 |
| Implementation owner 이동 | `_derive` Aggregate wrapper → `operator_handlers.aggregate.build_aggregate_step` |
| Canonical reduction owner | `analytical_aggregate.aggregate` — 내용 변경 없음 |
| Canonical field owner | 기존 strict `_resolve_row_field` — 내용 변경 없음; builder에 주입 |
| Consumers | 기존 StepFactory/LegacyOperatorFactory/PipeLowerer → FunctionStep → PipeRuntime |
| Remaining duplicated mappings | 기존 alias/renderer mapping 부채 유지; 이번 extraction에 새 mapping 없음 |
| Removed legacy execution | Aggregate `_derive` body와 legacy routing membership |

별도 read-only 감사에서 actionable finding 없음. 동기 계산 도중 선점 취소/timeout을
새로 보장하지 않으며, 기존 Runtime 정책을 그대로 보존한다. 테스트용 synchronous helper만으로
수명주기를 주장하지 않고 FunctionStep/PipeRuntime 테스트·differential로 보완했다.

## 9. 보호·무결성

- Behavioral Reference V1 manifest의 **79 files** checksum 모두 재검증, 변경 0.
- DB `public/mineral_risk` data fingerprint before/after 동일:
  `341be4d0d4316a9cd4da90aaaa952f38d931a1e344910ff21bf24d8d18e71954`.
  app session 쓰기는 clone의 `ai_chatbot`에만 있으며 source fingerprint에서 분리했다.
- 18002 ID `dd4a39b93365022e2558a4a945a1c8d1e792dce4d588fd243c90728c94fced59`,
  image `sha256:0d3e757a3d04e75e7b60d7e6917df544b31d4a782d5f7722fb8ddcd3652b466a`,
  StartedAt `2026-10-02T19:01:29.944957509Z` 모두 unchanged.
- 기존 Golden source checkout/image 및 Step0/reference artifact 미변경.
- 기존 known-invalid 출력은 개선하지 않았고 certified score를 갱신하지 않았다.

## 10. Evidence / rollback / 종료

Private evidence:
`/home/nuri/.codex/validation-evidence/aggregate-step1-20261003`

- 45 files manifest SHA256:
  `7c261ff9cbcddef66511c4faf559026f76808043801fb9e68570a7d4384484ee`.
- `old/new.json`, `old/new_matrix.json`, `old/new_graph.json`.
- candidate/Golden live requests, fresh session IDs, raw SSE/terminal, typed snapshots.
- exact tests/logs, source checksums/patch/new-file archive, image/config identity,
  before/after protected service and source fingerprint, independent audit.
- DB credentials/env secrets는 새 artifact로 복사하지 않음. raw는 private evidence에 보관.

Rollback 단위는 Aggregate builder 등록 + wrapper 이동 + 해당 테스트 호출 경로다.
단계 rollback 시 golden container/image가 보존되어 있어 18012만 원상 복귀 가능하다.
이번 작업에서 자동 rollback이나 commit/push는 하지 않았다.

**Step 1 완료. Step 2 Extremum migration은 시작하지 않고 다음 승인을 기다린다.**
