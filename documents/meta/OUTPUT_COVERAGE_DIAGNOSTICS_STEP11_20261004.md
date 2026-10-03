# Step 11 — Output Coverage Diagnostics extraction

## Acceptance

**PASS_SCOPED_OUTPUT_COVERAGE_DIAGNOSTICS_PARITY**

기존 두 output-set 검사의 정확한 차집합 진단을 독립 deterministic component로 옮겼다. 기존 vocabulary/alias/조건부 output 생산 규칙과 각 validator의 acceptance 권한은 원래 owner에 남긴다. Known Provider는 선택적으로 조회하는 **관찰 정보**이며 plan을 수정하거나 실행 자격을 부여하지 않는다.

| 검증 | 결과 |
|---|---:|
| Legacy produced/requested output differential | **10,231 / 10,231 동일** |
| V2 output coverage differential | **120 / 120 동일** |
| Parser/resolver acceptance/error differential | **144 / 144 동일** |
| AAST/IR decision differential | **69 / 69 동일** — saved 변형 9 포함 |
| Saved runtime graph control | **17 / 17 동일** |
| Targeted / boundary tests | **301 passed** |
| rag_core | **2248 passed / 0 failed / 695 subtests** |
| rag_chat | **155 passed / 동일 known legacy failure 1건 / 15 subtests** |
| PASS→FAIL / FAIL→PASS / error-result drift | **0 / 0 / 0** |

**18002/18012 변경 없음.** Full QA57, Strict/Product Golden 갱신, image build/deploy, Step 12, commit/push는 수행하지 않았다. GM14/PF02/CN09 등의 recovery를 시도하거나 집계하지 않았다.

## 1. 기준점 / evidence

- HEAD `979fd3f980bb10af74a218cc6e07bada110e76de` + Step 1–10 누적 working tree. clean HEAD만을 이번 baseline이라고 주장하지 않는다.
- Step10 `PROJECTION_MIGRATION_STEP10_20261004.md` acceptance PASS 및 Architecture V1 `READY_WITH_KNOWN_DEBT`를 기준으로 했다.
- core baseline 2176/2176, chat 155/156(known 1), live 2666 LOC / Factory 337 LOC / `_derive` 5 LOC / central operator conditions 4.
- Step10 sealed evidence 61개 파일의 checksum 불변을 확인했다.
- 새 durable evidence: `/home/nuri/.codex/validation-evidence/output-coverage-step11-20261004`.
- Frozen catalog/V2/intent/IR/AAST/live, after sources/tests, iteration diff, before characterization, differential, graph, tests, identity, structure, audit, manifest를 저장한다.
- 18002/18012 container ID / image ID / Created / StartedAt / config hash / mount 속성 전후 동일. 18012의 `komir-temporal-step7` 이미지는 그대로며 host 변경을 배포하지 않았다.
- Product Golden은 `NOT_CERTIFIED_WITH_KNOWN_REASONS` 그대로다. 기존 contamination/failure/status를 이번 구조 이관에서 수정하지 않았다.

## 2. Responsibility pre-audit

`iterative-audit` HIGH 기준의 Architecture/Complexity/Decomposition/Regression Guard를 적용했다. `qa-build`는 characterization/conformance test 절차에만 사용했다. 신규 QA/corpus/oracle 변경 0. 구현 1회, targeted 검증, 독립 read-only 감사 후 종료한다.

### 서로 다른 output namespace와 owner

| 위치 | Required | Declared/Produced | 현재 책임 / 이번 처리 |
|---|---|---|---|
| Legacy SemanticPlan | `requested_outputs` token set | `CAPABILITY_OUTPUTS` + `produced_outputs(requirements)` | inventory 기간, resource operation, average+sum, price extremum 생산 규칙 그대로 |
| Legacy validator | 기존 `current_price→latest_price` alias 및 str 변환 후 token | 위 조건부 produced set | 차집합 계산만 새 component에 위임. 오류 문자열 생성은 기존 wrapper |
| V2 output helper | `RequestedOutput.name` set | 호출자가 제공한 mapping의 values 합집합 | source_node/fields가 아닌 기존 name coverage. legacy alias를 도입하지 않음 |
| Capability Registry / Step9 specs | capability resolution 이후 output declaration | `output_type`, `output_fields`, identity/mode 등 | semantic type과 allowed fields를 구분. metadata 추가/합치기 없음 |
| SemanticProgram IR | node가 요청한 field/dependency | Registry allowance 또는 기존 metric fallback, args-dependent inference | `None` unknown schema, unit 예외, alias/필드 검사와 최초 error 순서 그대로 |
| AAST validator | typed requirement의 capability/entity/metric/period/scope/branch | generated graph / canonical plan binding | graph→capability/type→identity/period→branch 순서 그대로; 새 set 진단으로 대체하지 않음 |
| Planner acceptance / repair | 기존 parser/IR/AAST 판정 | 기존 issues / CoverageReport | execution eligibility, retry/repair 횟수, payload 그대로 |
| Runtime | dependency와 실제 TypedResult | status/value/evidence/failure | 실제 공급 여부와 실패 전파를 계속 runtime이 판단. static coverage로 우회하지 않음 |

세 가지를 구별해야 한다.

1. `CountryShare` 같은 Registry semantic type.
2. `country_share`, `import_share` 같은 legacy semantic output token.
3. `value`, `share_percentage` 등 allowed/actual row field와 runtime ValueType.

이름이 유사해도 서로 같은 집합의 멤버라고 가정하지 않는다. `RankedCountrySet/TradeTimeSeries`를 비교하는 기존 AAST output mismatch 정책도 별개다. 이번에는 alias union, allowed→guaranteed 승격, runtime type 통합을 하지 않았다.

### Pre-change / decomposition 결론

- 기존 두 검사는 서로 다른 vocabulary를 다루지만, **이미 확정된 두 집합의 차집합을 정렬하는 계산**만 동등하다.
- domain 생산 규칙과 AAST graph 검증까지 한 엔진에 넣으면 새 책임과 의미 혼합이 발생한다. 이들은 추출 대상에서 제외한다.
- 기존 catalog/IR/spec은 read-only 정보 공급자다. 새 component에 domain mapping이나 planner 객체를 주입할 필요가 없다.
- 기존 handler/runtime framework와 무관한 순수 진단이므로 작은 함수 + frozen snapshot만 필요하다. 새 planner/strategy/실행 framework는 만들지 않는다.
- 기존 두 call site의 정규화·호출 순서를 보존하고 집합 비교 구현의 owner만 하나로 만들 수 있다.

## 3. 새 deterministic contract

파일: `inhouse/rag_core/ragkit/output_coverage.py` — **60 LOC**.

```text
Existing caller-owned required/produced vocabulary
               ↓
diagnose_output_coverage(required, produced, provider_specs=None)
               ↓
immutable OutputCoverageDiagnostic
  required / produced / covered / missing / status
  optional known_providers
```

### 판단하는 것

- 입력 iterable의 정확한 set membership.
- `covered = required ∩ produced`, `missing = sorted(required − produced)`.
- set 수준 `COMPLETE / PARTIAL / MISSING`.
- 선택적으로 주어진 Registry spec의 `output_type`과 missing item이 정확히 같은 경우 candidate action ID 목록. missing과 후보 목록 모두 정렬한다.
- 불변 frozenset / nested tuple snapshot 및 분리된 JSON-shaped `to_dict()`.

### 절대 판단하지 않는 것

- semantic alias/case/whitespace normalization.
- 어떤 Capability를 선택하거나 추가해야 하는지.
- required/produced output의 의미 자체나 실제 데이터 공급 보장.
- argument/unit/period/cardinality/provenance/dependency/composition 호환성.
- AAST root/branch 생성, InputRef 연결, capability 실행, fallback, retry/repair.
- 계획의 최종 PASS/FAIL, Strict correctness, source validity.

`COMPLETE`는 **입력 집합 비교 결과**일 뿐 plan complete/execute 승인이라는 뜻이 아니다. 이 snapshot은 진단 함수를 통해 생성한다. dataclass 직접 생성에서 멤버 일관성을 강제하는 새 validator는 추가하지 않았으므로 임의 구성된 객체를 acceptance 권한으로 사용하면 안 된다.

### Provider discovery의 실제 범위

- read-only `provider_specs[action_id]['output_type']`만 검사한다.
- `output_fields`, runtime ValueType, surface metric, physical alias로 후보를 추측하지 않는다.
- 후보가 있어도 produced/covered/missing/status는 바뀌지 않는다.
- `provider_specs=None`은 조회하지 않은 상태(`known_providers=()`), 빈 catalog는 조회했으나 missing별 후보가 없는 상태다.
- 현재 Registry에는 `CountryShare→trade.country_rank` 선언이 있다.
- 현재 `CAPABILITY_ARGUMENTS`에는 `trade.concentration→ConcentrationMetric` 선언이 없다. V2의 별도 lowering declaration은 `FactSet`이며 이를 ConcentrationMetric이라고 보완하지 않았다.
- 따라서 `{ConcentrationMetric, CountryShare}`와 빈 produced set의 진단은 둘 다 missing, CountryShare에만 `trade.country_rank` 후보다. actual plan이 ConcentrationMetric을 제공한다고 새로 선언하지 않는다.
- 기존 production acceptance caller 두 곳은 provider_specs를 전달하지 않는다. provider 정보는 standalone 관찰용이다. 기존 repair/model payload, 로그 schema, SSE에 새 후보를 주입하지 않는다.

## 4. Mechanical extraction / 보존한 acceptance

Production 변경은 **기존 2파일 각각 import + 한 문장 교체, 신규 순수 component 1개**다.

| Caller | 보존한 계약 | 이동한 책임 |
|---|---|---|
| `semantic_capabilities.validate_requested_outputs` | 기존 alias 한 개, str 변환, produced_outputs 호출, `requested_output_not_produced:` + sorted names, 성공 None | normalized required와 produced의 차집합 |
| `semantic_v2.validate_output_coverage` | requested name set, mapping values 합집합, sorted missing tuple | 같은 vocabulary 내 차집합 |

Legacy 함수 내부 missing은 list→tuple이지만 외부 반환은 동일 str/None이다. V2는 기존과 동일 tuple을 반환한다. 기존 table, args-dependent 생산 규칙, Resolver order는 AST 동일하다.

보존한 failure ordering:

- resolver: normalize → output coverage → unresolved → intent/action resolution.
- parser: output schema / unsupported request / empty requirements → output coverage → price context binding → resolver. resolver에서의 재검사를 제거하지 않는다.
- AAST: graph contract → required capability 및 output mismatch → entity/metric/scope/period → branch count. violation 순서와 details를 바꾸지 않는다.
- `semantic_plan_incomplete` 래핑, 기존 `aast_coverage_invalid`, bounded repair, abstain 경로는 live source byte-identical이다.
- V2 name coverage가 source_node를 검증하지 않는 기존 제한도 유지한다. 이를 더 엄격하게 만드는 것은 이번 scope가 아니다.

**diagnose != repair**: 기존 repair 구현은 바꾸지 않았으며 새 진단 결과를 repair로 전달하는 경로도 만들지 않았다.

## 5. Differential / regression evidence

### Old/new 구성

동일 interpreter에서 frozen/current module을 로드하고 동일 payload를 비교했다. Frozen IR은 frozen catalog lookup, frozen AAST는 frozen IR을 참조한다. Parser/resolver 비교는 동일 SemanticPlan을 사용하며 local catalog import만 frozen/current로 교체한다. network connection은 harness에서 금지했다.

| Matrix | 실제 범위 |
|---|---|
| Legacy 10,231 | produced 787 + requested 9,444. 기간 dict/object, resource operation, 복수 average+sum, price selection, alias, 대소문자/공백, unknown token, 기존 str coercion 포함 |
| V2 120 | multi-output/name duplicate/empty, 분리된 source values 합집합, current/latest 불일치, camel/snake mismatch, malformed None input의 동일 exception 포함 |
| Parser 144 | resolved/unresolved/invalid status × requirement pattern × requested set. 기존 schema rejection과 coverage-before-unresolved/unsupported 순서 포함 |
| AAST/IR 69 | synthetic graph 60 + saved graph 변형 9. IR field rejection, type mismatch, wrong entity/period/capability, branch/root coverage의 동일 순서 비교 |
| New tests 72 | complete/partial/missing, provider present/absent, 실 Registry 후보, mutation/호출 금지, exact type-only, frozen snapshot, 기존 wrapper/parser 경계 |

허용/거절 변화는 점수 상승으로 상쇄하지 않고 양방향으로 따로 집계했다.

| Boundary | Cases | Old accepted | New accepted | PASS→FAIL | FAIL→PASS | reason/result 차이 |
|---|---:|---:|---:|---:|---:|---:|
| Legacy requested | 9444 | 1270 | 1270 | 0 | 0 | 0 |
| V2 coverage | 120 | 18 | 18 | 0 | 0 | 0 |
| Parser/resolver | 144 | 9 | 9 | 0 | 0 | 0 |
| AAST/IR | 69 | 9 | 9 | 0 | 0 | 0 |

위 accepted는 해당 validator 경계의 판정이며 Strict content PASS가 아니다. malformed input exception도 기존과 같아야 한다.

Saved runtime graph control은 Step6/Golden 저장 evidence의 **17변형 / 9 QA ID**(GM01, GM02, ADD25, REG02, ADD27, IX02, REG06, PF03, ADD16)다. 일부 source envelope는 저장 evidence로 재구성한 success fixture이고 나머지는 저장 TypedResult다. 실제 DB/LLM/live QA 재실행이 아니다. root/status/failure/presentation/SSE event 생성/call 기록을 전후 비교했다. ADD25 EMPTY, REG06 DEPENDENCY_FAILED, PF03/ADD16 abstain을 그대로 보존했다.

### 실제 commands

repository root, 기존과 동일 PYTHONPATH/scope:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:inhouse:inhouse/rag_chat python3 /tmp/komir-output-coverage-step11.Iuup09/validate_coverage.py before
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:inhouse:inhouse/rag_chat python3 /tmp/komir-output-coverage-step11.Iuup09/validate_coverage.py diff
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:inhouse:inhouse/rag_chat python3 /tmp/komir-output-coverage-step11.Iuup09/evidence_helpers.py graphs
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:inhouse:inhouse/rag_chat python3 -m pytest -q -p no:cacheprovider inhouse/rag_core/tests/test_output_coverage_diagnostics.py inhouse/rag_core/tests/test_semantic_capabilities.py inhouse/rag_core/tests/test_semantic_v2_contract.py inhouse/rag_core/tests/test_semantic_v2_linkage.py inhouse/rag_core/tests/test_semantic_intent.py inhouse/rag_core/tests/test_aast_coverage_validator.py inhouse/rag_core/tests/test_catalog_ownership.py inhouse/rag_core/tests/test_live_contract_repair.py inhouse/rag_core/tests/test_live_plan_failure.py
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:inhouse:inhouse/rag_chat python3 -m pytest -q -p no:cacheprovider inhouse/rag_core/tests
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:inhouse:inhouse/rag_chat python3 -m pytest -q -p no:cacheprovider inhouse/rag_chat/tests
PYTHONDONTWRITEBYTECODE=1 python3 /tmp/komir-output-coverage-step11.Iuup09/measure.py
PYTHONDONTWRITEBYTECODE=1 python3 /tmp/komir-output-coverage-step11.Iuup09/decisions.py
git diff --check
```

- Targeted **301 passed**, 6.18s.
- Core **2248 passed** = 2176 baseline + 신규 characterization 72, 695 subtests, 42.73s. 기존 Pydantic lifespan warning 1개.
- Chat **155 passed / 1 known legacy failure**, 15 subtests, 6.60s.
- known: `test_sse_cancellation.py::test_disconnect_stops_real_ast_retry_before_blocking_invocation_returns[legacy_control-False]`.
- 기존 tests/assertions 수정 **0**. 새 test 1개(299 LOC)만 추가.
- 독립 read-only 감사에서 High/Critical finding 없음. dataclass를 acceptance authority로 사용하지 않는 제한을 명시했다.

## 6. 구조 측정 / 책임 위치

| 지표 | Before | After |
|---|---:|---:|
| semantic_capabilities.py LOC | 236 | 237 |
| validate_requested_outputs LOC | 7 | 7 |
| produced_outputs LOC | 53 | 53 — 미변경 |
| semantic_v2.py LOC | 1076 | 1077 |
| validate_output_coverage LOC | 8 | 8 |
| aast_coverage.py / validate_aast LOC | 652 / 153 | 동일 |
| semantic_ir.py LOC | 488 | 동일 |
| live_multihop.py / Factory / `_derive` LOC | 2666 / 337 / 5 | 동일 |
| central operator conditions | 4 | 4 |
| catalog / V2 AST If 개수 | 15 / 159 | 15 / 159 |
| 신규 diagnostic component LOC | 0 | 60 |
| 신규 component 최대 function / class LOC | 0 | 22 / 23 |
| 동일 exact 차집합 구현 owner 수 | 2 | 1 |

이번 extraction은 LOC 감소 목적이 아니다. 기존 두 wrapper는 vocabulary adaptation과 error 형식을 유지하고, set 진단 책임만 단일 owner로 이동했다. AAST graph coverage나 domain 생산 규칙까지 줄였다고 주장하지 않는다.

새 component의 dependency는 **stdlib `dataclasses`, `typing`뿐**이다. Planner/Gemma/Runtime/IR/Capability executor를 import하지 않는다. Registry는 optional Mapping 입력이며 central catalog를 God Registry로 확장하지 않는다.

### 판단을 합치지 않고 남긴 책임

- 조건부 `produced_outputs`와 capability lookup의 서로 다른 의미.
- V2 requested name / source-node field compatibility / logical planner selection.
- IR field allowance vs actual TypedResult field vs Registry semantic output type.
- AAST reachability, alias, capability/output mismatch와 identity preservation.
- live diagnostic payload / bounded repair / runtime evidence/status 판단.
- Step9 `DEFERRED_CONTRACT_OWNERSHIP` 전체.

위 책임은 비슷한 이름만으로 합칠 수 없다. 진단 API가 있다고 자동 selection/composition 문제가 해결된 것으로 판단하지 않는다.

## 7. Complexity Delta / Contract Delta

### Complexity Delta

- Files changed: production **3**(기존 2 + 신규 1), 신규 test **1**, artifact **1**. 누적 dirty changes 제외.
- New classes: **1**, frozen diagnostic snapshot. 새 execution class/framework 0.
- New public contracts: **1 diagnostic API/result**, 새 capability/semantic-output/acceptance 계약 0.
- New registry entries: **0**.
- New QA/question/entity/answer special cases: **0**.
- New central-dispatch branches / removed central branches: **0 / 0**.
- 중복 exact coverage 집합 비교 구현: **2→1**. semantic declaration/mapping 정본 추가/삭제: **0 / 0**.
- Largest actually modified method/function: 기존 wrapper **8 LOC**; 신규 진단 함수 22 LOC.
- Largest class in modified module: 기존 `DeterministicLogicalPlanner` **317 LOC**, 미변경. 신규 snapshot 23 LOC.
- Largest modified module: semantic_v2 **1077 LOC**; 기존 planner.plan **268 LOC**, 미변경.
- Responsibility growth: **false** for existing components. output 집합 진단의 locality만 개선하고 domain 의미나 selection 책임을 추가하지 않았다.
- Verdict: **COMPLEXITY_WARN / REFACTOR_CANDIDATE** 유지. 기존 >200 LOC planner와 IR/live 다중 책임은 `DECOMPOSITION_REVIEW_REQUIRED`이며 이번 승인 범위에서 확장하지 않는다.

### Contract Delta

- New: 정확한 required/produced 집합과 optional provider 후보를 담는 read-only diagnostic contract 1.
- Modified/removed semantic acceptance contracts: **0 / 0**. 정보 반환 계약을 추가했을 뿐 기존 validator 반환값은 동일하다.
- Canonical source of truth: set 진단은 `output_coverage`; domain produced/alias는 기존 `semantic_capabilities`; declared output type은 기존 Registry/Step9 spec; V2 names와 graph validity는 기존 V2/IR/AAST owner.
- Consumers: 기존 legacy/V2 wrapper 두 곳은 `.missing`만 소비한다. optional provider lookup은 standalone diagnostic consumer용이며 production repair나 model context로 연결하지 않는다.
- Remaining duplicated mappings: canonical metric/alias/field/type와 coverage capability 해석의 기존 차이. Step9 보류 목록을 새 union으로 해결하지 않는다.
- 기존 `_coverage_diagnostic`, `_coverage_repair`, `_deterministic_coverage_repair`, parser/History/source/Projection/Renderer는 byte-identical.

## 8. 향후 Dynamic AAST와 종료 경계

향후 caller가 authoritative typed requirement와 명시적 output 선언을 각각 같은 vocabulary의 집합으로 제공하면 이 component를 **read-only signal**로 사용할 수 있다. 후보 capability는 별도의 argument/dependency/cardinality/period/provenance 검증이 필요한 탐색 정보일 뿐이다. 이를 plan 생성이나 repair 승인으로 변환하는 기능은 별도 설계·승인·behavior 검증이 필요하다. 이번 Step에서는 구현하지 않았다.

Rollback은 기존 두 wrapper의 import/한 문장과 신규 component/test만 대상으로 한다. 이전 Steps를 HEAD reset으로 제거하지 않는다. frozen snapshot/per-file diff/manifest를 보존한다.

**Step 11에서 종료. Step 12 Presentation 자동 진행 없음. Full QA57 / Strict / Product Golden / 18002·18012 변경 없음.**
