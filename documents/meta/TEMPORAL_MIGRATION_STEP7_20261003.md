# Architecture Migration Step 7 — Temporal continuation mechanical extraction

## Acceptance

**PASS_SCOPED_TEMPORAL_EXTRACTION_PARITY**

`execute_relation`의 historical observed + forecast 연결 실행 본문만 독립 함수로 이관했다. 입력 순서, 선행 검사, metadata 구성, 바깥 예외 처리, 나머지 Join/Compare/alignment 알고리즘은 그대로다.

- old/new boundary differential **8012/8012 동일**.
- runtime graph differential **108/108 동일**.
- 저장/live upstream을 고정한 graph **22/22 동일**.
- targeted **299 passed**, rag_core **1755 passed / 0 failed**(1691 + 신규 characterization 64).
- rag_chat **155 passed / 동일 known legacy failure 1건**.
- 18012만 후보로 교체. **18002·source data·QA oracle·Strict 점수 변경 없음**.
- PF02 recovery, Full QA57, 다음 Source-result Adapter 단계, commit/push는 수행하지 않았다.

## 1. Identity / baseline / scope

| 항목 | 기록 |
|---|---|
| git parent | `979fd3f980bb10af74a218cc6e07bada110e76de` |
| source 상태 | 승인 Steps 1–6 dirty working tree + Step 7. clean Golden SHA라고 표시하지 않음 |
| old validation | `komir-relation-step6`, `komir-rag-chat:relation-step6-20261003` |
| old image ID | `sha256:e6d23fe258c1f17ae45fbe1b583c7c0e9fb61a6de29b558487eb91945c25e0a0` |
| new validation | `komir-temporal-step7`, loopback `127.0.0.1:18012` |
| new tag | `komir-rag-chat:temporal-step7-20261003` |
| new image ID | `sha256:2213f8fcc6dcf3b1cfcb98145d474a82c326f7c0c67f65d1628f95a52f35eb6c` |
| image metadata | parent revision / build timestamp / `temporal-step7-working-tree` label 기록. 없는 registry RepoDigest를 생성하지 않음 |
| source identity | host/container **230 files checksum 일치**. Step 6 대비 application 변경은 relational_ops.py와 새 temporal_composition.py만 |
| runtime configuration | env, extra_hosts, network, read-only mount 속성 동일. Gemma/MCP/18012 health 정상 |
| cache | 새 candidate 프로세스, 동일 cache 설정. live 요청별 fresh session. LLM/계획 변동과 실행 parity를 분리 |
| frozen prior evidence | Step 6 manifest의 **63파일** 모두 hash 불변 |
| source DB fingerprint | `public/mineral_risk` 전후 `341be4d0d4316a9cd4da90aaaa952f38d931a1e344910ff21bf24d8d18e71954` 동일. QA session 저장 schema는 별도 |
| protected 18002 | container ID/image/State/전체 mount 속성 불변. mount 배열 순서만 정렬하여 비교 |
| durable evidence | `/home/nuri/.codex/validation-evidence/temporal-step7-20261003` |

기존 [Behavioral Reference V1](BEHAVIORAL_REFERENCE_V1_PROVENANCE_AUDIT_20261003.md)을 보존한다. Certified Product Golden의 contamination/미인증 상태를 해결하거나 재인증하지 않는다.

## 2. Pre-change responsibility / contract check

iterative-audit의 Architecture/Complexity/Regression 및 Decomposition Guard를 적용했다. 구조 변경은 CRITICAL 범위로 취급하고, 구현 1회 + deterministic 검증 + 독립 read-only 감사로 제한했다.

| 점검 | 결론 |
|---|---|
| 현재 owner | `execute_relation`이 입력 guard, alignment, arithmetic, temporal 실행을 함께 소유 |
| 적절한 이동 경계 | 이미 준비된 left/right TypedResult, copied rows, args, metadata, 기존 resolver를 받는 순수 temporal 함수 |
| semantic rule owner | 기존 temporal branch 자체. 추출 후 새 함수가 동일 알고리즘의 유일한 실행 정본 |
| 기존 확장 구조 | registered Relation handler → execute_relation → pure component. StepFactory/FunctionStep/PipeRuntime 재사용 |
| 새 개념 유입 / 두 번째 정본 | 없음. 기존 body 제거, 새 알고리즘/alias table/validator 없음 |
| 재사용성과 특례 | 모든 기존 temporal_continuation 실행에 적용; QA/질문/entity 분기 없음 |
| 중앙 분기 | 기존 operation selector 1개 유지, 실행 본문만 위임. 신규 dispatcher 분기 0 |
| 구조 변경 필요성 | 승인된 독립 변경 이유 1개 추출. 308줄 전체를 다른 파일로 복제하지 않음 |
| 소유권 | 주 agent: source/harness/deployment/artifact. test worker: 새 test_temporal_composition.py만. 별도 auditor는 read-only |
| 제외/종료 | behavior 개선·PF02 recovery·source/planner/Projection/History/Renderer 변경 금지. Step 7 acceptance 후 종료 |

## 3. 실제 기존 Temporal 동작의 characterization

| 경계 | 보존한 실제 동작 |
|---|---|
| common input guard | 입력 2개, 입력 삽입 순서의 left/right. FAILED 등 dependency 실패, EMPTY, evidence/sufficient 검사를 temporal보다 먼저 수행 |
| row adaptation | Mapping은 1행, Mapping list는 행별 dict copy. 잘못된 shape는 기존 relation failure |
| PARTIAL | 허용된 명시 row status가 필요. 통과한 continuation은 **SUCCESS + incomplete_population warning**을 반환하며 해당 row status/payload도 그대로 유지 |
| date resolution | observed: date→crtr_ymd; forecast: forecast_date→date. 기존 strict resolver callback과 그 alias/year fallback을 그대로 소비 |
| date ordering | `str(value).replace('-', '')[:8]` 기준 stable sort. invalid/None/연·월 단위 날짜를 새로 검증하지 않음 |
| boundary / as-of | 실제 경계는 정렬된 observed 마지막 날짜. 별도 args.as_of를 새로 사용하지 않음. forecast 날짜가 경계 이하이면 제외 |
| duplicate policy | observed 중복 및 경계 이후 forecast 동일 날짜 중복은 유지. 같은 날짜 내 기존 입력 순서 유지 |
| values | left_field 또는 value, right_field 또는 predicted_price. numeric validation이나 formula 없음; 원본 row를 복제해 date/value/observation_type 추가 |
| entity | 양쪽 entity가 truthy일 때 set 동일성 검사. 비어 있는 쪽을 새로 거절하지 않음. 기존 metadata ordered union 보존 |
| metric / criterion | 출력 metric은 기존처럼 **price**. 입력 metric/criterion compatibility 검사를 추가하지 않고 원본 criterion field를 유지 |
| unit | 양쪽 truthy unit이 다르면 기존 mismatch. 한쪽/양쪽 누락이면 그대로 허용하며 left.unit or right.unit |
| provenance/evidence/lineage | 기존 공통 metadata 소비. DEV_DUMMY/DUMMY_LOAD filtering이나 production certification 추가 없음 |
| empty/failure | 기존 no_rows, field_required, unit_mismatch, entity_mismatch, no_future_rows reason 및 ValueType 유지 |
| exception | helper는 새 catch 없음. 호출은 기존 try 안에 유지: ValueError는 바깥 FACT_SET abstain, TypeError 등은 기존대로 전파 |

특히 PARTIAL의 SUCCESS 승격, dummy provenance 보존, invalid-date 문자열 정렬, criterion 검사 부재는 현행 reference behavior다. 올바른 제품 의미라고 승인하지 않았고 이번 단계에서 수정하지 않았다.

## 4. 변경 구조와 정적 parity

```text
기존 registered Relation handler
    → execute_relation
        → 기존 arity / status / evidence / structured rows / PARTIAL 검사
        → 기존 metadata 구성
        → temporal_continuation selector
            → compose_temporal_continuation
                → 기존 TypedResult
        → 나머지 Join / Compare / alignment [변경 없음]
        → 기존 ValueError boundary
```

- [temporal_composition.py](../../inhouse/rag_core/ragkit/temporal_composition.py): 새 함수 하나. 날짜 정렬/경계 이후 forecast concatenation과 기존 temporal 결과/failure만 소유.
- [relational_ops.py](../../inhouse/rag_core/ragkit/relational_ops.py): import 1줄 + 위임 1줄. 기존 temporal body 46줄 제거.
- [test_temporal_composition.py](../../inhouse/rag_core/tests/test_temporal_composition.py): 14개 함수, parameterized 64건. 새로운 product QA/expected answer/oracle 없음.

`metrics.py`의 AST 검증:

1. frozen Step 6 temporal body와 새 helper body가 위치 정보 제외 **완전히 동일**.
2. 새 호출을 원래 body로 치환하고 추가 import를 제거하면 **파일 전체 AST가 frozen old와 동일**.

따라서 non-temporal Join/Compare, 선행 guard, InputRef/operand order, exception scope를 함께 보존했음을 정적으로 확인했다.

## 5. 실행 검증

| 검증 | 결과 |
|---|---:|
| 기존 Relation 전 family boundary matrix | 6092/6092 동일 |
| 추가 Temporal boundary/order/overlap/metadata matrix | 1920/1920 동일 |
| 기존 runtime graph: JOIN/COMPARE/barrier/selectors | 72/72 동일 |
| Temporal runtime graph: status × reverse InputRef × selector | 36/36 동일 |
| 기존 Golden saved graph | 6/6 동일 |
| 기존 Step 6 live saved graph | 11/11 동일 |
| 이번 실제 live graph의 fixed-input 교차 실행 | 5/5 동일; PF02 temporal graph 1개 포함 |
| targeted/contract | **299 passed**, 3 subtests; 2.37s |
| rag_core 전체 | **1755 passed**, 695 subtests, 기존 warning 1; 41.27s |
| rag_chat 동일 scope | **155 passed / known failure 1**, 15 subtests; 6.56s |
| 실제 SSE 요청 | old/new 각 3회, 총6회 모두 terminal 정확히 한 번 |

Differential은 전체 TypedResult 필드, failure/status, exception type/message, step ID/dependencies/bindings/retry/timeout을 비교한다. runtime graph는 완료 순서를 뒤집어도 InputRef/operand 순서를 보존하는지, root/presentation/SSE 및 호출 순서까지 비교한다. Temporal 추가 matrix는 입력 불변성도 검사한다.

Known rag_chat failure는 이전과 동일:

`test_sse_cancellation.py::test_disconnect_stops_real_ast_retry_before_blocking_invocation_returns[legacy_control-False]`

기존 expected calls 3 / actual 4. skip/xfail/assertion/oracle 완화 없음.

### Live 결과와 execution parity 분리

| QA | old → new | 판단 |
|---|---|---|
| PF02 | semantic_plan_incomplete → 3-node temporal graph SUCCESS | 최초 차이는 **계획 생성**. old는 executable graph가 없어 직접 plan parity 미측정. 새 graph/upstream을 old/new executor에 동일 투입하면 모든 결과 동일 |
| GM02 | answer / terminal / graph / TypedResult 동일 | non-temporal sentinel 유지 |
| REG02 | answer / terminal / graph / TypedResult 동일 | ordered_last 보호 sentinel 유지 |

PF02는 strict oracle로 회복 평가하지 않았다. 성공처럼 보이는 live 변화를 이 refactor의 recovery로 집계하지 않는다. old PF02는 `NO_EXECUTABLE_GRAPH`, `parity_measured=false`로 별도 기록했다. Planner/model 입력 변동을 Temporal 알고리즘 regression과 섞지 않는다.

### 재현 명령

실행 당시 harness 위치: `/tmp/komir-temporal-step7.3E05FB` (durable bundle에도 보관).

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:inhouse:inhouse/rag_chat python3 /tmp/komir-temporal-step7.3E05FB/differential.py
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:inhouse:inhouse/rag_chat python3 /tmp/komir-temporal-step7.3E05FB/temporal_differential.py
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:inhouse:inhouse/rag_chat python3 /tmp/komir-temporal-step7.3E05FB/replay_graphs.py
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:inhouse:inhouse/rag_chat python3 -m pytest -q -p no:cacheprovider inhouse/rag_core/tests/test_temporal_composition.py inhouse/rag_core/tests/test_registered_relation.py inhouse/rag_core/tests/test_live_relations.py inhouse/rag_core/tests/test_qa500_series.py inhouse/rag_core/tests/test_qa500_common_contracts.py inhouse/rag_core/tests/test_live_audit_safety.py
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:inhouse:inhouse/rag_chat python3 -m pytest -q -p no:cacheprovider inhouse/rag_core/tests
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:inhouse:inhouse/rag_chat python3 -m pytest -q -p no:cacheprovider inhouse/rag_chat/tests
```

검증 harness 조정은 두 건 있었다: synthetic runtime graph에 기존 IR이 요구하는 comparison fields를 명시했고, Docker mount 배열의 비의미적 순서를 destination 정렬로 비교했다. 실제 field/속성·oracle·application validation을 완화하지 않았다. 이 두 건은 product regression으로 집계하지 않는다.

## 6. 구조 지표 / 남은 책임

| 지표 | Before | After |
|---|---:|---:|
| relational_ops.py LOC | 323 | **279** |
| execute_relation LOC | 308 | **263** |
| temporal legacy 실행 body LOC | 46 | **0** |
| temporal selector 포함 원래 block | 47 | **2** (selector + delegate) |
| 새 temporal module / function LOC | 0 / 0 | **63 / 55** |
| execute_relation AST If 수 | 66 | **60** |
| temporal component If 수 | 0 | **6** (이동; 전체 알고리즘 조건 순증가 0) |
| Relation 독립 변경 이유 | 6 | **5** |
| 중앙 temporal selector | 1 | **1**, 새 분기0 |
| LiveOperatorFactory operator conditions | 6 | **6**, 무변경 |
| live / Factory / derive LOC | 2928 / 493 / 164 | **동일** |

책임 집계는 Step 6 §6의 동일 목록을 사용했다:

1. arity/status/evidence preconditions와 metadata composition — 유지.
2. structured row adaptation, key validation/indexing/cardinality, join modes — 유지.
3. scalar broadcast와 side-by-side field 선택/alignment — 유지.
4. arithmetic comparison과 unit/zero/invalid operand — 유지.
5. temporal continuation date boundary/concatenation — **새 component로 이동**.
6. row outcome masking, aggregate status, provenance/lineage output — 유지.

새 component dependencies는 `typing.Any/Callable/Mapping`, 기존 `TypedResult`, 기존 `ValueType`, 인자로 주입하는 기존 `resolve_field`뿐이다. source/DB/LLM/clock/Planner/History/Renderer/LiveOperatorFactory import 및 상태 소유가 없다. temporal 실패 owner를 이제 이 함수에서 바로 찾을 수 있다. 공통 eligibility failure는 Relation에 남는다.

Relation 자체는 여전히 263 LOC와 복수 책임으로 `DECOMPOSITION_REVIEW_REQUIRED`다. 이번 추출은 이 경고를 없애기 위한 LOC 이동이 아니라 temporal 실행 의미의 owner를 하나로 만든 단계다. 신규 operation routing까지 자동 등록되는 범용 framework를 만들었다고 주장하지 않는다.

## 7. Complexity Delta

- Files changed: application 2(기존 relation + 새 temporal), tests 1(신규), artifact 1. 이전 dirty 변경 보존.
- New classes: **0**.
- New public semantic contracts: **0**; 내부 Python helper 호출 경계 **1**.
- New registry entries: **0**; 새 Capability/Operator/Handler family **0**.
- QA/question/entity special-case branches: **0**; answer hardcoding **0**.
- New central-dispatch branches: **0**. 기존 selector 유지; 그 안의 semantic If 6개와 실행 body 이동.
- Duplicated temporal logic added: **0**; 기존 실행 body 제거로 정본 1개 유지.
- Duplicated contract sources added/removed: **0 / 0**. frozen differential reference는 production 구현이 아님.
- Largest modified production method/class/module: **263 / N/A / 279 LOC**; 새 helper55/module63.
- Responsibility growth: **false**. Relation 6→5, Temporal component 1개 책임.
- Scoped structural/behavioral acceptance: **PASS**. 잔여 `COMPLEXITY_WARN / REFACTOR_CANDIDATE`, 전체 기존 HIGH debt는 별도 승인된 migration 계획으로 유지.

## 8. Contract Delta

| 항목 | 결과 |
|---|---|
| New/modified/removed semantic contracts | **0 / 0 / 0** |
| 변경된 구현 경계 | inline temporal body → pure compose_temporal_continuation 함수 |
| Canonical owner | temporal 알고리즘: 새 함수. eligibility/metadata/catch: 기존 execute_relation. field resolution: 기존 resolver |
| Consumers | registered Relation handler → execute_relation → temporal component; 기존 PipeRuntime/TypedResult |
| 단일 정본 | temporal body는 원래 위치에서 제거. 새 alias/date/unit/criterion mapping 없음 |
| Remaining duplicated mappings | 기존 side-by-side preferred fields, source/display aliases, graph-normalizer forecast vocabulary. 이번 scope에서 변경하지 않음 |
| Known-invalid behavior | PARTIAL/status, criterion/provenance 검사 부재, legacy date 정렬 등 그대로 보존 |

`qa-build`는 기존 동작의 deterministic characterization에만 적용했다. 신규 natural-language QA 0, 신규 product fixture/source 0, 테스트 fixture 64건, 신규 regression 0. 기능 개선/exhaustion 규칙으로 사용자 scope를 확대하지 않았다.

## 9. 독립 감사 / 종료

독립 read-only 감사에서 HIGH/CRITICAL semantic drift 미발견. 이동 body 및 나머지 파일 AST 동등성, guard/exception/operand/metadata와 새 조건 부재를 확인했다. executable differential/regression 결과가 이를 뒷받침한다.

`acceptance.json`에 parity 수, image/source identity, 기존 sealed evidence 불변, protected18002, source DB fingerprint, known failure와 PF02 미측정 old graph를 기록했다. private evidence/source snapshots와 scripts는 `manifest.json`으로 봉인한다.

**Step 7 완료 후 종료. Source-result Adapter extraction, Full QA57, Strict 갱신, 18002 배포는 하지 않는다.**
