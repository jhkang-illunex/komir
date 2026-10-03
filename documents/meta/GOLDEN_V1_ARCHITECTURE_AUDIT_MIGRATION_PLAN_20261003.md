# Golden V1 Architecture Audit & Migration Plan — 2026-10-03

## 0. 범위·정본·감사 방법

**결론: behavior-preserving, 단계별 Architecture Cleanup을 권고한다. 이번에는 설계만 작성했으며 구현하지 않았다.**

- Golden branch: `multihop_work`
- Golden commit: `979fd3f980bb10af74a218cc6e07bada110e76de`
- 로컬 `HEAD`와 로컬 remote-tracking `origin/multihop_work`가 위 SHA로 일치. 이번 감사에서 fetch/push하지 않았다.
- 시작 working tree: clean.
- 지정된 immutable behavioral acceptance: Strict **21/57**, Answerable **21/53**, rag_core **1560/1560**, rag_chat **155 passed / 1 known legacy failure**, RENDER_FAILURE **0**.
- 정본: [Authoritative QA57](QA57_AUTHORITATIVE_STRICT_20261003.md), [Legacy Typed migration audit](LEGACY_TYPED_CONTRACT_MIGRATION_AUDIT_20261003.md), [Typed output coverage audit](TYPED_CAPABILITY_OUTPUT_COVERAGE_AUDIT_20261003.md).
- 적용 skill: `.agents/skills/iterative-audit/SKILL.md`. Architecture/Complexity/Regression/SRP/OCP/DIP/KISS/YAGNI 및 resource lifetime 규칙을 함께 적용했다.
- 위험도: 설계 대상은 **CRITICAL**(핵심 실행/타입 경계), 이번 변경은 문서만이다. 감사 1회로 종료한다.
- 실행한 검사: git 상태/이력, 파일 내용·참조 검색, Python AST 기반 LOC 측정, 파일 SHA256, Docker 상태/identity 읽기. 테스트·QA 요청·DB 쿼리·캐시 초기화는 하지 않았다.
- 금지사항 준수: 프로젝트 코드, skill, oracle, QA fixture 수정 없음. capability/operator 추가 없음. image build, QA57 replay, 서버 재시작/배포 없음. **18002 변경 없음.**

### 0.1 Evidence identity와 측정 시점의 구분

| 근거 | 기록/확인 값 | 해석 |
|---|---|---|
| 현재 18012 | `a1636b1a27d4`, `komir-rag-chat-cn08-r3`, tag `komir-rag-chat:legacy-typed-audit-r1` | Docker 읽기 확인 |
| 현재 18012 image ID | `sha256:5d1a94c6d8ffe42f3d5a7d1b7859217721246121aa00b285d2f1921e80c67327` | 로컬 image ID이며 registry manifest digest와 혼동하지 않음 |
| 18012 StartedAt | `2026-10-03T09:49:40.077879587Z` | 재시작하지 않음 |
| 현재 18002 | `dd4a39b93365`, `komir-rag-chat-18002`, `komir-rag-chat:deploy-price-representative-r1` | 보호 대상, read-only inspect만 수행 |
| 18002 image ID / StartedAt | `sha256:0d3e757a3d04e75e7b60d7e6917df544b31d4a782d5f7722fb8ddcd3652b466a` / `2026-10-02T19:01:29.944957509Z` | 이번 작업의 배포 대상 아님 |
| authoritative QA57 측정 당시 | tag `cn08-period-change-r3`, source `fa423722c…` + dirty tree, core 1557 | 현재 Golden SHA에서 새 Full Replay한 기록이 아님 |
| Golden의 core 1560 | Legacy Typed migration audit의 전체 regression 기록 | 최신 metadata 변경 후 근거; strict 증가 주장은 없음 |

사용자가 지정한 Golden V1은 **현재 커밋 + 서로 다른 시점에 축적된 검증 근거의 묶음**으로 고정한다. 이번 감사가 동일 SHA/image에서 모든 수치를 재측정했다고 주장하지 않는다. 향후 첫 migration의 검증 준비에서 Golden 커밋의 실제 source/image/config/snapshot 동일성을 확인하고 기존 acceptance를 적용한다. 원본 artifact를 덮어쓰거나 baseline을 낮추지 않는다.

근거 SHA256:

```text
QA57_AUTHORITATIVE_STRICT_20261003.md
4338d4342f3c53f179a48de166c6b394245d740533e79531f3529dd5cc2e7031
TYPED_CAPABILITY_OUTPUT_COVERAGE_AUDIT_20261003.md
a9b8aa2052073df618c77d3186de67d11c83f6af931a229ffbc01869fdb99456
live_multihop.py
153f55c01e48e017631188ca77278f4568ba4604250ad0880415543c25f3df16
```

Golden strict PASS ID set(21개, 순증가 수치로 회귀를 상쇄하지 않음):

```text
MI01 MI03 MI04 DOC04 NEWS01 MP01 MP03 MP06 MP07 GM02 GM04 GM08
REG02 REG03 REG04 REG05 ADD15 ADD27 ADD47 ADD48 ADD49
```

MP03/GM02는 과거 변동 이력이 있다. 위 집합은 authoritative run의 PASS 집합이지 전부 3/3 STABLE이라는 선언이 아니다. PF01/CN07/ADD40은 wrong-confident/DEV_DUMMY 의심 상태를 유지한다. cleanup으로 자동 PASS 승격하거나 기존 wrong-confident가 0이라고 기록하지 않는다.

## A. Architecture Findings

### A.1 정적 크기 측정

Python `ast.parse`의 `end_lineno - lineno + 1`, module은 물리적 줄 수를 사용했다. 주석/빈 줄을 포함한 span이며 cyclomatic complexity가 아니다.

| 파일/대상 | module LOC | 주요 class/function LOC | Guard |
|---|---:|---|---|
| `live_multihop.py` | 3057 | `LiveOperatorFactory` 627; `_derive` 352; `_normalize_relation_contract` 398; `_parse_ast` 180 | module/class/HIGH method 다중 초과 |
| `relational_ops.py` | 323 | `execute_relation` 308 | HIGH; join/compare/continuation 혼재 |
| `analytical_series.py` | 237 | `calculate_series` 171 | HIGH; 5 calculation 변형 |
| `analytical_aggregate.py` | 127 | `aggregate` 86 | WARN; 순수 함수 경계는 이미 존재 |
| `semantic_ir.py` | 484 | `completeness_issues` 236 | HIGH; 출력 추론/필드 검증 결합 |
| `aast_coverage.py` | 652 | `validate_aast` 153 | HIGH; semantic identity 중복 후보 |
| `action_contract.py` | 3457 | `_extract_action_plan_legacy` 639; `validate_action_plan` 341 | HIGH; 이번 cleanup 초기 범위 밖 |
| `semantic_v2.py` | 1076 | `DeterministicLogicalPlanner.plan` 268 | HIGH; shadow/fixture 경로를 live로 전환하지 않음 |
| `composite_renderer.py` | 1487 | `render_composite` 1106 | HIGH; RENDER_FAILURE=0, 후순위 |
| `pipe_runtime.py` | 391 | `PipeRuntime` 120; `_compile` 68 | 실행 경계 재사용 가능 |
| `semantic_capabilities.py` | 237 | `produced_outputs` 53 | 크기보다 metadata 중복/완결성 문제 |

`_derive`는 11개 Operator 값(top_k/filter/sort/rank/arg_max/arg_min/project/calculate/aggregate/compare/join)의 경로를 받는다. 이는 순수 실행문 branch 수와 다르지만 독립 확장 variant 5개 경고 기준을 넘는다. `_derive → filter → keep → numeric coercion` 등 3단계를 넘는 제어 중첩도 존재한다. 크기 기준만으로 기계적인 클래스 분할을 정당화하지 않는다.

### A.2 상위 debt 10개

| # | Finding / 코드 근거 | 위험과 권고 |
|---|---|---|
| 1 | [live 통합 모듈](../../inhouse/rag_core/ragkit/live_multihop.py), Factory가 모델·history·source·operator·presentation 경계를 함께 연결 | `RESPONSIBILITY_GROWTH`, `REFACTOR_REQUIRED`. 실행 조립을 남기고 검증 가능한 단위로 분리 |
| 2 | [Registry](../../inhouse/rag_core/ragkit/semantic_capabilities.py), IR `_METRIC_FIELDS`, runtime `_action_id`/`_typed_from_retrieval`가 capability 의미를 별도 선언 | `DUPLICATED_CONTRACT_SOURCE`; domain별 spec 소유권 + 단일 read catalog. 불일치 union은 금지 |
| 3 | `TypedResult.result_type`은 `ValueType`, Registry `output_type`은 `PriceOverview`/`IndicatorSeries` 같은 문자열 | 물리 container shape와 semantic identity를 혼동. 기존 타입을 폐기하지 말고 명시적인 대응을 spec에 소유시킴 |
| 4 | `_typed_from_retrieval`이 evidence markdown을 다시 row로 읽고 physical `total`/생산량 등을 해석 | source→canonical 변환이 generic runtime에 누출. 먼저 adapter로 그대로 추출; raw structured 전환은 별도 검증/승인 |
| 5 | `_derive(PROJECT)`가 가격 identity, inventory/value, 문서→MineralSet, partial/unit 정책을 소유 | Projection이 두 번째 domain runtime. Output Spec과 변환/표현 책임을 분리하되 후순위 |
| 6 | `_normalize_relation_contract` 398줄에서 resource YoY, price/forecast, country share, ordered_last 등을 처리 | graph repair의 변경 이유 축적. 어떤 rule을 언제 적용하는지 먼저 고정; cleanup 중 새 repair 금지 |
| 7 | `execute_relation` 308줄; `_retrieve`의 role binding; `InputRef → input_0/input_1` | dependency identity/role와 alignment 계약이 여러 층에 나뉨. completion order 아닌 현재 InputRef 순서·identity를 보존 |
| 8 | calculation이 `analytical_*`에 일부 분리됐지만 `_derive`에 alias/ratio route와 직접 arithmetic 잔존 | 기존 pure helper 등록부터 시작. unit/period 의미 개선은 extraction과 분리 |
| 9 | runtime `_typed_unit`이 [chatbot_events](../../inhouse/rag_core/ragkit/chatbot_events.py)의 display-unit helper에 의존; live `_result_events`도 출력 생성 | DIP/표현 경계 역전. 기존 presentation seam 재사용; Renderer 재작성은 보류 |
| 10 | `CAPABILITY_OUTPUTS`, spec fields, `produced_outputs`, IR 추론이 output coverage를 다른 수준으로 정의 | field 존재와 semantic output 생산을 구분하는 deterministic 진단 경계 필요. provider 제안과 graph 자동생성은 별개 |

기존 audit의 `COMPLEXITY_PASS`는 해당 작은 patch의 delta 판정으로만 해석한다. 현재 전체 구조는 다중 HIGH + 실제 drift 이력이 있으므로 **REFACTOR_REQUIRED(단계별 승인 필요)**이다. 전체 재작성 허가는 아니다.

## B. Responsibility Map

아래 파일은 별도 표기 없으면 `inhouse/rag_core/ragkit/` 아래다.

| Component | Current Responsibility | Should Own | Should Not Own | Dependencies | Duplicated Contracts | Extraction Candidate |
|---|---|---|---|---|---|---|
| `live_multihop.py` | parse/retry/cache, history, repair, actions, TypedResult, runtime assembly, SSE | 앱 통합 entry point, 명시적 dependency 조립 | source columns, 계산, domain projection, chart semantics | LLM/action/graph/history/runtime/events | action ID, metric, aliases, output schema | source-result adapter, operator builders; planner/presentation은 후순위 |
| `LiveOperatorFactory` | node routing, typed history snapshot, role binding, row operations, action execution, fan-out | node→기존 Step 생성, registry resolve/delegate | operator 내부 알고리즘, source schema, 업무 규칙 | FunctionStep/retrieval/analytical/relational | field/value/metric/price identity | 기존 builder registry에 operator 단위 등록 |
| `semantic_capabilities.py` | semantic outputs + action specs + 일부 output derivation | versioned read-only catalog와 결정적 lookup | source I/O, arithmetic, graph synthesis, NL 해석 | typed requirement, domain-owned declarations | IR/V2/runtime action maps | domain specs → 동일 catalog index |
| `TypedResult` / `_typed_from_retrieval` | frozen envelope + Any payload; evidence rows/aliases/units/types 조립 | envelope은 runtime; source→canonical은 capability boundary | source 부재 추측, 임의 numeric selection, 렌더링 | ActionCall/Evidence/ValueType | action→ValueType, canonical metric | 기존 result adapter 경계(`legacy_bridge`) 활용 |
| Projection (`_derive`) | 필드 선택 외 identity 보충/삭제, 문서 entity 추출, metric-specific alias | canonical field 선택/rename/distinct + envelope 보존 | capability 추론, physical aliases, 단위 생성 | canonical resolver, source TypedResult | price identity/metric maps | 최후반 projection handler; compatibility는 명시적으로 격리 |
| Calculation (`analytical_series/share`, `_derive`) | series/share/ratio + inline change | operation args/operand 검사, 연산, output unit/lineage/failure | retrieval, criterion 결정, 증거 대체 | TypedResult/field resolver | calculation aliases, change formula/field metadata | helper adapter→handler; 이후 연산 family별 소유권 |
| Aggregate (`analytical_aggregate`) | group/reduce/order/null/unit | 검증된 population의 reduction | population을 가져올 source 선택, reduction 추측 | TypedResult/resolve callback | grouping date 탐색, ordered_last binding | 첫 handler 후보; 기존 helper 그대로 호출 |
| Join/Alignment (`relational_ops`) | join/compare/broadcast/continuation | key/cardinality/unit/period precondition, 결과 lineage | plan node 생성, country source alias 해석 | InputRef/TypedResult/resolver | temporal physical fields, comparison conventions | Join/Compare wrapper 먼저; continuation 분리는 뒤에 |
| Renderer (`presentation`, events, composite, renderers) | envelope presentation + domain formatting/SSE, 일부 재계산/단위 해석 | RenderModel→표/차트/출처/wire | Capability/업무 의미 결정 | TypedResult/Evidence/ActionPlan | price units/identity/physical headers | 기존 `ExecutionPresentation` 사용; 초기 변경 금지 |
| SemanticPlan / AAST (`semantic_intent`, IR, coverage, live parser) | WHAT 추출, candidate, preservation/repair, 출력 추론 | typed 요구/graph validation; bounded repair 정책 | physical schema, source 접근, 산술 의미 재정의 | Registry/IR/LLM | action resolution, fields, periods | 진단/validation contract 분리; planner 재설계 아님 |
| History (`history_context`, live materialization, `action_contract`) | session store, unresolved slot binding, raw-history cutoff, cache 경계 | 현재 explicit 우선, 필요한 typed binding/provenance | downstream selection/composition | Turn/ConversationContext/TypedResult | 여러 파일에 있으나 중복 의미라고 단정하지 않음 | 기존 함수 interface만 고정; resolver extraction 보류 |
| Legacy alias layers | exact/annotated/fuzzy field 선택, physical→canonical, label conversion | physical mapping은 adapter; semantic alias는 Output Spec; label은 presentation | 하나의 전역 synonym union으로 다른 의미 병합 | source/evidence/IR/runtime | 아래 C 목록 | alias origin/precedence부터 동결 후 domain별 이관 |

### B.1 독립적인 변경 이유의 수

이는 함수 개수 아닌 책임별 수동 분류다. 보수적으로 **live 모듈 12개**, **Factory 9개**를 확인했다.

- live 12: ①AST/모델 I/O schema ②LLM retry/cache ③graph normalization/coverage repair ④history binding ⑤evidence row decoding ⑥field/unit/date canonicalization ⑦capability resolution/slots ⑧operator 구현 ⑨조회/fan-out ⑩runtime/session 조립·저장 ⑪trace/diagnostics ⑫SSE/presentation.
- Factory 9: ①Step dispatch ②saved history entity 복원 ③typed input→action slot binding ④row selection/projection ⑤calculation/aggregation routing ⑥join/compare routing ⑦source invocation/결과 postprocess ⑧multi-entity/ForEach 및 partial merge ⑨evidence validation.
- pure helper에 이미 위임한 기능도 Factory가 domain-specific routing/전후 정책을 소유하면 변경 이유에 포함했다. 목표는 Factory **Step assembly 1개**, 알고리즘 소유는 각 handler이다.
- 최근 QA57에서 추가된 책임은 price criterion identity/cardinality, resource population, indicator period_change, canonical capability resolution, history materialization이다. 누적 위치는 `_normalize_relation_contract`, `_derive`, `_call_action`, `_typed_from_retrieval`에 집중되어 있다.

## C. Duplicated Contract Sources / Single Source of Truth

| ID | 중복 또는 경계 누출의 구체 근거 | 목표 authoritative owner | 이관 안전 조건 |
|---|---|---|---|
| D1 | `semantic_capabilities.CAPABILITY_ARGUMENTS/CAPABILITY_OUTPUTS`, `semantic_v2.CAPABILITIES`, live `_action_id`, coverage `_requirement_capability/_node_capability` | capability별 Input/Output Spec, catalog는 index | V2는 shadow 경로. 우선순위/resource.yoy 특이성까지 보존; catalog 전환으로 selection 확대 금지 |
| D2 | Registry `output_fields`, IR `_METRIC_FIELDS`, `completeness_issues.metric_fields` | Output Spec의 **allowed / guaranteed / optional / args-dependent** fields | 현재 field union을 모든 variant의 보장값으로 취급하지 않음; 불일치 소비자는 이전 판정으로 동결 후 별도 승인 |
| D3 | `_resolve_row_field`, `_CANONICAL_FIELD_ALIASES/_canonicalize_row`, `pipe_runtime._field_key`, IR `_FIELD_ALIASES` | semantic alias는 Output Spec, physical/annotated alias는 capability adapter | exact 우선, ambiguity 거절, selector 기존 fuzzy 차이를 표로 고정. 동일하지 않은 규칙은 억지 통합하지 않음 |
| D4 | `_typed_from_retrieval` action→metric/ValueType table vs Registry canonical_metric/output_type | Capability Output Spec이 envelope shape와 semantic identity의 대응 소유 | `ResourceRanking`과 `FACT_SET`, `CountryShare`와 `COUNTRY_SHARE` 구별; generic ValueType만으로 의미 동등 주장 금지 |
| D5 | price `identity_fields` vs `_derive(PROJECT)`의 반복된 4-field set/metric_value_fields vs IR/renderer lists | identity/optionality는 price Output Spec, 표시명은 renderer | REPRESENTATIVE/EXPLICIT/ALL, 없는 serial/label, annotated key 동작을 각각 보존 |
| D6 | `_typed_unit`→`chatbot_events._verified_display_unit/_price_unit_from_codes`; row unit alias | canonical 단위는 adapter/기존 unit definition, 표시 단위는 presentation | display helper를 runtime 진실로 두지 않음. 단위 누락을 새 단위로 채우는 변경은 cleanup 아님 |
| D7 | `_derive` calculation alias/direct percent_change, `analytical_series._change`, relation percent_change, IR output inference | 연산 정의/출력 단위는 기존 analytical operation contract | denominator/sign/base/unit 규칙이 같다는 증거 없이 함수 합치지 않음 |
| D8 | `_period_signature`, `Period`, live `_filter_period`, retrieval `inventory._period_bounds`, relation date normalization | semantic Period owner + source-boundary serialization; operation은 canonical granularity 소비 | point/range/latest, annual date, 월 경계가 다른 이유를 보존; 날짜 parser 일괄 치환 금지 |

D1–D5는 `DUPLICATED_CONTRACT_SOURCE`, D6–D8은 책임 누출 및 동등성 검증이 필요한 중복 후보다. SOURCE field→canonical 변환과 canonical field→한글 label은 서로 다른 책임이므로 무조건 중복 제거 대상이 아니다.

검증된 예: runtime `_field_key`는 fuzzy first-match, `_resolve_row_field(strict=True)`는 모호성 거절이다. 이를 단일 resolver로 교체하는 것만으로도 기존 실패/성공이 달라질 수 있다. 먼저 현행 결과를 고정하고, 순수 이동과 의미 변경을 별도 commit/승인으로 분리해야 한다.

### C.1 Registry를 God Registry로 만들지 않는 방법

기존 `semantic_capabilities`를 **읽기 catalog**로 유지한다. capability별 선언은 해당 도메인의 기존 input/output contract 옆에 둔다. 중앙은 등록·조회·중복 ID/모호한 선언 검증만 소유한다. source query, normalization 구현, 산술, graph search를 넣지 않는다.

| 정보 | 소유권 / 소비자 |
|---|---|
| action ID, accepted metric/operation/mode, canonical arguments | capability Input Spec → resolver/planner/typed call boundary |
| output semantic identity, canonical fields/aliases, cardinality | capability Output Spec → validator/canonical adapter/projection |
| REPRESENTATIVE/EXPLICIT/ALL | 기존 criterion mode contract + representative-price resource. catalog는 참조만, registry 값 복제 금지 |
| unit/provenance 요구 | source Output Spec 및 calculation contract. actual 값/출처는 TypedResult 인스턴스 |
| physical columns / source category | Source/Capability Adapter만 소유, generic validator에 SQL column names 전달 금지 |
| operator operand/result/실패 계약 | operator spec/helper 소유. Capability catalog에 모든 operator 알고리즘을 넣지 않음 |

현재 `inventory.latest/series`는 spec이 있지만 output_type/canonical_metric 선언이 불완전하고, `trade.concentration/monthly/indicator`·`forecast.price`는 전용 action spec이 없다. 이번 설계가 없는 선언을 자동으로 보충한 것은 아니다. 이들은 `unknown/incomplete`로 남기고, metadata 추가로 planner 동작이 바뀌는 일은 후속 feature 작업으로 분리한다.

## D. Target Architecture / Boundary Ownership

```text
Current Query → 기존 Typed Requirement
                    ↑ unresolved slot만
              Typed History Materialization (보호)
                    ↓ resolved current requirement; raw history cutoff
기존 Semantic/AAST candidate
      ├─ Capability Catalog / Output Spec (단일 선언 소비)
      └─ Deterministic Output Coverage + Graph/Coverage Validation
                    ↓ 기존 정책의 bounded repair / fail-closed
Validated AAST → PipeLowerer → 기존 StepFactory/등록 builder
                    ├─ migrated typed handler → FunctionStep
                    └─ 미등록 operator만 legacy factory
                         ↓ 기존 PipeRuntime (유일 실행 계층)
                InputBinding → handler / existing executor
Source → Capability Adapter → Canonical TypedResult
                         ↓ Calculate / Join / Project (동일 runtime)
                    Canonical TypedResult
                         ↓ 기존 ExecutionPresentation 경계
                    Renderer → ChatEvent/SSE
```

새 scheduler/execution layer, 범용 자동 planner, 별도 병렬 type system을 만들지 않는다. `StepFactory`, `Step`, `StepHandler`, `FunctionStep`, `LegacyOperatorFactory`, `TypedResult`는 이미 존재한다. 특히 live 2798행은 모든 operator를 동일 `factory.build`로 등록하고 있어 **registry가 없는 것이 아니라 등록 후 다시 monolithic dispatch하는 것**이 핵심이다.

### D.1 Composition/Dependency의 책임

| 계약 | Owner | 역할/금지 |
|---|---|---|
| requirement/output identity, 요청된 relation | 기존 Typed Requirement / Semantic IR | requirement에 없는 sum/share/comparison 의미 생성 금지 |
| capability가 제공 가능한 output set | Capability Spec | provider 존재는 graph 완성을 의미하지 않음 |
| dependency source ID/selector/argument role | `RequirementNode.inputs`/`InputRef` → `InputBinding` | graph edge와 함께 명시. 별도 문자열 reference store 추가 금지 |
| root reachability/cycle/branch preservation | `SemanticProgram`, Coverage Validator, `Pipe.validate` | source 접근 없이 검증; duplicate branch는 semantic identity로만 판정 |
| runtime dependency barrier/timeout/cancel | `PipeRuntime` | 현재 다중 input barrier 및 실패 propagation 유지 |
| join key/cardinality/unit/period compatibility | 기존 Join/Compare contract + canonical output descriptors | 실제 공통 key 없이 positional join 금지. row order를 entity identity로 간주 금지 |
| scalar reduction 선택 | requirement가 명시한 기존 Aggregate | world/multi-row라는 이유로 sum 추측 금지 |
| dynamic entity set→ForEach | typed MineralSet/기존 ForEach 계약 | 확장 전 set provenance, 확장 후 item status/lineage 보존; history 재추론 금지 |

CountryShare+ConcentrationMetric은 output 두 개와 key가 필요하다. period_change+evidence는 계산 성공과 근거 충분성을 별도 판정한다. multi-series는 date granularity/criterion/cardinality가 필요하다. aggregate+ratio는 scalar의 population completeness를 요구한다. continuation은 observed/forecast 경계다. 이들을 단일 generic `compare` repair로 통합하지 않는다.

현재 `InputBinding`은 `input_0/input_1`로 내려가며 일부 실행 함수는 `inputs.values()`의 **InputRef 삽입 순서**를 사용한다. 이는 source row position과 다르다. cleanup에서는 순서 계약을 보존하고, 명시 role 전환은 이후 별도 typed binding 작업으로 분리한다.

### D.2 Output Coverage Validator는 진단에 한정

기존 `validate_requested_outputs`/`produced_outputs` 및 CoverageReport를 재사용/분리한다. 개념적 결과는 `required`, `produced`, `missing`, `existing_provider_candidates`, `incompatible_reason`이다. 자동 set-cover planner는 구현하지 않는다.

- 타입명 union만 비교하지 않고 명시된 entity/metric/period/cardinality/criterion qualifier를 함께 본다.
- capability 후보의 선언은 **계획상 제공 가능성**, 실행 TypedResult의 값/증거 충족은 **실제 결과 검증**이다. 두 검증을 합치지 않는다.
- Output Spec 미완결은 `unknown`이지 값이 있다는 증거가 아니다. field alias를 semantic provider로 승격하지 않는다.
- GM14의 CountryShare와 concentration은 서로 대체 불가. catalog에 CountryShare provider가 있어도 mineral binding/join/요청 의미가 미완결이면 composition 자동생성 불가.
- 정적 진단 분리는 가능하지만 coverage 판정 변경/새 field 인정은 mechanical refactor와 별도다. 최신 audit의 `NO_COMMON_CONTRACT` 결론을 무시하지 않는다.

### D.3 Projection / Renderer / History

Projection 목표는 `Canonical TypedResult → Requested Canonical Output`이며, exact field 선택/rename/distinct/metadata 보존만 소유한다. 문서→MineralSet은 projection 외부의 기존 typed extraction 책임, price identity의 필수/선택 여부는 Output Spec 책임이다. 현행 compatibility는 삭제 전 parity를 증명한다.

Renderer를 위한 새 RenderModel은 당장 불필요하다. [presentation.py](../../inhouse/rag_core/ragkit/presentation.py)에 `TextResult/TableResult/ChartResult/ExecutionPresentation`이 이미 있다. 다만 live SSE는 `root_result → _result_events`로 가며 기존 presentation은 주로 envelope이므로 완전한 전환이 끝났다고 주장하지 않는다. `render_composite`·price renderers의 business/physical 해석은 debt로 기록하고 초기 migration에서 건드리지 않는다.

History는 기능/우선순위/오류 의미를 동결한다. independent isolation, history_required, 필요한 typed materialization, explicit current 우선, raw-history cutoff, provenance, fail-closed 및 cache의 query/model/relevant-history identity를 유지한다. 구조 cleanup을 구실로 `_materialize_history_requirements`의 선택 방식이나 reference namespace를 변경하지 않는다.

## E. TypedOperator Migration 설계

### E.1 가장 작은 구현 형태

- **기존 `StepFactory` + `StepHandler` callable + `FunctionStep`을 재사용**한다. 모든 family를 위한 BaseClass hierarchy나 새로운 scheduler는 불필요하다.
- `LegacyOperatorFactory`의 등록형 builder 계약을 사용해 migrated operator는 독립 builder로 연결한다. 개념상 TypedOperatorRegistry이지 병렬 registry framework를 추가하라는 뜻이 아니다.
- args는 기존 RequirementNode/validation 계약에서 받는다. runtime-boundary typing이 필요한 곳도 현행 허용 집합을 먼저 보존한다. 초기 추출에 엄격한 신규 타입 검증을 추가하여 과거 입력을 거절하지 않는다.
- domain 없는 context(필드 resolver, 기존 unit contract 등)는 좁은 callable dependency로 주입한다. handler가 `live_multihop` 전체를 역import하지 않는다. 단지 코드를 옮겨 God Module을 새 파일에 복제하지 않는다.

| 순서 / family | 기존 input → output | Args / validation / failure | 추출 포인트 |
|---|---|---|---|
| 1 Aggregate | evidenced rows → grouped FactSet 또는 ScalarMetric | aggregation/field/group_by/order_by/null_policy; unit/population/order 검증, 기존 failure code 그대로 | `analytical_aggregate.aggregate` 재사용 + 현재 `_derive` adapter |
| 2 Extremum | rows → 선택된 원본 row(s), 기존 result type | field/ties; date/numeric, empty, ambiguous tie; provenance 보존 | ARG_MAX/ARG_MIN body + 공통 finalization 최소 경계 |
| 3 Sort/Rank/TopK | rows → 정렬/절단 rows | field/order/tie_breaker/k; missing/type 처리 동일 | rank 무입력 capability path와 **의존 result rank** 구분 보존 |
| 4 Filter | rows/기존 set → subset, empty set | predicate/field/value/period, country matching; 기존 오류 그대로 | source alias/period dependency 주입, NL 해석 없음 |
| 5 Calculation | rows/scalar/두 input → 기존 typed result | calculation/field/time_field/operand roles; complete/unit/date/zero 검증 | analytical_series/share/ratio 재사용; inline 경로는 별도 추출 |
| 6 Join/Compare | 두 typed populations → 기존 joined/compared result | key/how/left-right fields/broadcast; duplicate/null/cardinality 거절 | `execute_relation` 그대로 등록, 내부 분리는 다음 단계 |
| 7 Temporal Composition | observed + forecast → TimeSeries | 기존 continuation fields/unit/entity/기준일/중복처리 | relation 내 기존 branch만 이동; criterion/provenance 검사를 새로 보강하지 않음 |
| 8 Projection | canonical rows/envelope → selected output | fields/aliases/distinct/identity/partial/unit | spec/adapter 소유권 정리 후 마지막으로 이관 |

위 계약은 **현재 동작의 기록 대상**이다. 예를 들어 continuation이 검사하지 않는 조건을 cleanup에서 추가하면 안전성 강화라도 의미 변경이다. 별도 feature/safety 승인으로 분리한다.

### E.2 Strangler 규칙

1. 등록된 operator는 migrated builder만 사용한다. **미등록일 때만** legacy fallback한다.
2. handler 실패/abstain/type mismatch를 legacy 재실행으로 바꾸지 않는다. 중복 source call·fail-open 금지.
3. 기존 node ID, InputRef 순서, dependencies, step retries/timeouts, 상태/failure/provenance/events를 동일하게 유지한다.
4. migrated body는 같은 commit에서 legacy dispatch에서 제거한다. 원본은 Git Golden commit에 남긴다. 두 구현을 production에 장기 보관하지 않는다.
5. registry lookup을 추가만 하지 말고 해당 legacy 분기를 함께 치환한다. **central domain variant 증가 0, 전체 central branching 순증가 0**을 diff에서 검증한다. 불가능하면 scope를 줄인다.
6. 새 기능은 이관된 extension path만 사용하되 이번 cleanup series에는 새 기능 자체를 넣지 않는다. 미이관 path에는 기능을 추가하지 않는다.

## F. Migration Plan — 승인 후 실행할 단계

아래 새 파일명은 **제안 경로**이며 이번에 생성하지 않았다. 각 번호는 독립 acceptance와 revert 단위다. 공통 gate는 아래 F.2를 모두 만족해야 한다.

| Step | Scope / Files | Behavioral Risk | Structural Benefit | Required Regression |
|---|---|---|---|---|
| 0 | Golden evidence manifest/재현성 준비: 기존 meta artifacts + 저장된 trace의 durable 위치/identity 확인 | LOW; 실행 환경 확인은 필요 | 과거 dirty-image 기록과 현재 SHA를 혼동하지 않음; 입력/output oracle 고정 | 코드 없음. 후속 작업 시작 전 source/image/config/캐시/snapshot 검증 |
| 1 | **Aggregate 등록형 adapter**: `live_multihop.py`, 기존 `legacy_bridge.py` 계약 소비, 제안 `operator_handlers/aggregate.py`, targeted tests | LOW–MEDIUM; ordered_last/PARTIAL 정책 | 실제 사용되는 첫 handler, legacy aggregate body 제거; 새 public interface 없이 시작 | aggregate/group/unit/order/null/status, REG02; core+chat+Golden gate |
| 2 | Extremum mechanical extraction: live ARG_MAX/MIN, 제안 `operator_handlers/extremum.py`; 공통 finalization은 필요 부분만 이동 | MEDIUM; tie/date/lineage | 독립된 2 operator의 알고리즘 제거 | extremum lineage, tie all/first/error, empty/invalid, 원본 row date/provenance |
| 3 | Sort/Rank/TopK extraction: live, 제안 `operator_handlers/ordering.py` | MEDIUM; missing/order/first-n | selection family 책임 분리 | numeric/date/string/tie/NULL + no-input rank retrieval parity |
| 4 | Filter extraction: live, 제안 `operator_handlers/filtering.py` | MEDIUM; country/period/set/empty | filter-specific 수정 이유 제거 | predicate 양 표현, period bounds, explicit empty/partial/evidence |
| 5 | Calculation routing extraction: live, 기존 `analytical_series.py`, `analytical_share.py`; 제안 calculation builder | MEDIUM–HIGH; args/unit/denominator | arithmetic dispatcher가 domain runtime에서 분리 | series/ratio/share/zero/unit/mixed population/correlation + CN08 blocked 그대로 |
| 6 | Relation builder extraction: live, `relational_ops.py`(알고리즘 그대로) | MEDIUM; InputRef 순서/partial | join 실행 책임과 capability retrieval 분리 | `test_live_relations`, semantic group alignment, missing/duplicate keys, barrier/lineage |
| 7 | Temporal continuation branch extraction: `relational_ops.py`→제안 `temporal_composition.py` | HIGH; as-of/중복/provenance | 관계 연산 함수 크기 감소 | 현행 continuation/side-by-side 차이, observed/forecast 경계, 실패 parity; PF02 자동 승격 없음 |
| 8 | Source-result adapter mechanical extraction: live canonical helpers/`_typed_from_retrieval`→제안 `capability_result_adapter.py`; 기존 LegacyResultAdapter 경계 | HIGH; evidence/field/status | generic runtime에서 physical schema 제거 시작 | Raw→TypedResult 전 필드 golden diff, rejected evidence, unit/criterion, partial; Direct 경로 영향 |
| 9 | Catalog 소유권 정리 **동등성이 확인된 declaration 1개씩**: `semantic_capabilities.py`, IR/coverage/기존 adapter 소비자 | HIGH; resolution/validation 순서 | 중복 declarative truth 감소 | Registry contract matrix, resolver priority, allowed/optional/guaranteed field parity. 동등하지 않은 map은 중단·별도 backlog |
| 10 | Projection extraction 및 확인된 duplicate identity 제거: live→제안 projection handler, Output Spec 소비 | HIGH; price/document/unit/COMPOSITE | domain projection 책임 격리·축소 | projection collision/alias/partial/source + price modes/identity; byte/semantic output parity |
| 11 | Coverage diagnostics 분리/소비자 연결: IR/coverage/semantic_capabilities 중 기존 진단 함수만 | MEDIUM–HIGH; plan acceptance | output 진단을 generation에서 독립 | missing output/provider, branch reachability, repair 횟수/오류 메시지 동일; 새 selection 금지 |
| 12 | 별도 승인 후 presentation seam 정리: live events→기존 `presentation.py`/renderers | HIGH, **현재 보류** | 실행→표현 단방향 회복 | RENDER_FAILURE=0 유지, SSE/citation/chart/identity, Golden 전체; Renderer 재작성 아님 |

Step 8→9→10은 하나의 거대 commit이 아니다. capability/domain 한 개의 proven-equivalent subset마다 나누고 다음 단계는 이전 승인 뒤 진행한다. History resolver/store와 Semantic V2 planner의 전환은 이 계획에서 제외한다.

각 step의 rollback은 그 단계 commit을 revert하는 방식으로 설계한다. 후속 step이 의존하는 경우 역순 revert하며 config/build 연결까지 같은 단위로 되돌린다. 데이터/DB migration을 포함하지 않으므로 source rollback은 필요 없다. `reset --hard`나 사용자 변경 덮어쓰기를 rollback 절차로 사용하지 않는다.

### F.1 Resource lifetime / concurrency 보호

- `PipeRuntime`만 timeout/retry/cancel과 dependency barrier를 소유한다. handler가 독자 threadpool/event loop/retry controller를 만들지 않는다.
- source adapter가 얻은 DB connection/cursor는 adapter가 `with`/`finally`로 닫는다. `history_context.PostgresHistoryStore`는 현재 cursor context + connection finally-close가 있다. ownership을 runtime/handler로 이동하지 않는다.
- `asyncio.to_thread(retrieve_evidence)` 및 `gather`의 취소/예외 동작을 그대로 characterization한다. resource leak을 발견하면 기록하되 migration과 무관한 cancellation behavior 수정은 합치지 않는다.
- global `_AST_CACHE`, history/result store의 session key, 수명, immutable snapshot semantics를 보존한다. global registry에 request/session/TypedResult를 저장하지 않는다.
- 상태 전파/partial/evidence failure는 성공 데이터와 동일한 parity 대상이다. 실패 결과에서 다른 실행 경로로 fallback하지 않는다.

### F.2 Golden Acceptance Contract

**매 step 내부 개발:** 저장된 실제 AAST/TypedResult 입력으로 old/new deterministic differential → targeted unit/contract → rag_core 전체 → rag_chat 동일 scope → 영향 live QA 및 보호 sentinel. synthetic 데이터로 strict PASS를 만들지 않는다.

**step을 Golden 후속 버전으로 승인하기 전:** source/config/snapshot/as-of가 일치하는 Golden/후보 evidence를 비교하고 아래를 모두 확인한다. Full Strict 확인이 필요한 승격 gate는 후속 승인 작업에서 수행한다. **이번 audit에서는 모든 테스트/Full Replay를 실행하지 않았다.**

| 축 | Acceptance |
|---|---|
| Strict | `>=21/57` + 기존 21 PASS ID 각각 회귀 0. 새 PASS로 기존 실패를 상쇄하지 않음 |
| Answerable | 동일 blocked-valid 정책의 분모 53 유지. 평가/업무 규칙 변경 금지 |
| core | Golden 1560 tests 전부 통과 + 새 characterization tests 통과. tests 제거/skip/범위 축소로 숫자 달성 금지 |
| chat | 같은 scope에서 155 passed 및 **같은** known legacy failure만 허용. 다른 실패를 1개로 바꾸는 것 금지 |
| output | value/type/metric/entity/period/unit/criterion/cardinality/evidence/source/provenance/status/warnings/failure/lineage 동일 |
| execution | call count, node/binding/root identity, retries/cancel, cache/history 및 SSE contract 동일 |
| architecture | QA/question/entity-specific branch +0; central branch 순증가 0; duplicated contract source +0; legacy body 감소 |
| semantics | 새로운 능력, 미지원 type 인정, alias 폭 확대, partial→success 승격, unit 생성, oracle 변경 금지 |

기존 scope의 명령(향후 검증용, 이번 실행 안 함):

```sh
PYTHONPATH=.:inhouse:inhouse/rag_chat pytest -q inhouse/rag_core/tests
PYTHONPATH=.:inhouse:inhouse/rag_chat pytest -q inhouse/rag_chat/tests
```

known failure는 `inhouse/rag_chat/tests/test_sse_cancellation.py`의 legacy AST retry/disconnect 기대 호출수 계열이다. 향후 정확한 node ID/parameter/stack fingerprint를 기존 로그와 대조해 allowlist를 고정한다. `1 failure` 숫자만 허용하지 않는다.

핵심 deterministic suites: `test_live_multihop`, `test_live_relations`, `test_extremum_lineage_contract`, `test_semantic_group_alignment`, `test_semantic_capabilities`, `test_semantic_v2_linkage`, `test_qa500_contract_matrix`, `test_live_foreach_output_contract`, `test_history_store`, `test_price_criterion_cardinality`, `test_terminal_event_contract` 등 영향 경로를 선택한다. V2 fixture test 통과만으로 live 경로 parity라고 판단하지 않는다.

모델 변동은 동일 saved requirement/AAST/result의 differential과 같은 환경 fresh probe를 분리해 평가한다. MP03/GM02 등에서 결과가 달라지면 paired Golden 비교 전에는 regression 0을 선언하지 않는다. 새 strict PASS도 구조 이동의 의도된 성과로 집계하지 말고 원인 확인한다.

## G. Golden 21을 깨뜨리기 쉬운 지점

| 위험 | 원인 | 방어 |
|---|---|---|
| Alias 단일화 | strict/non-strict/fuzzy/annotated alias의 현행 결과가 다름 | resolver truth table 먼저 고정; 모호성을 완화하지 않음 |
| Metadata만 정리 | Registry 등록 순서가 resource.rank/resource.yoy resolution을 바꿀 수 있음 | action/args/output 타입 우선순위 그대로; 진단-only부터 |
| Aggregate 이동 | REG02 order_by auto binding, partial 거절은 helper 밖에 존재 | wrapper 전체 precondition 유지, helper만 옮겨 끝내지 않음 |
| Extremum/Sort 이동 | shared finalization의 entity/status/evidence 또는 original-row date 손실 | 값뿐 아니라 envelope/lineage full diff |
| dependency/ForEach | InputRef 순서·role binding, composite envelopes, partial item statuses | barrier와 row/entity identity 보존; alias 추측/positional join 금지 |
| Projection | optional price identity, document MineralSet, COMPOSITE→FACT_SET가 현재 동작 | 후순위, branch별 before/after 계약 snapshot |
| Unit/Temporal | CN08 unit_unavailable, forecast provenance/as-of/criterion 미완결 | cleanup으로 단위를 생성하거나 forecast 안전성을 가정하지 않음 |
| Presentation | existing event path와 ExecutionPresentation가 완전히 일치하지 않음 | Renderer 변경 보류; RENDER_FAILURE=0 보호 |
| History/Cache | identity 변경·raw history 재유입·namespace 변화 | closed boundary, fresh/dirty 및 dependent follow-up 검사 |
| 평가 환경 | Golden 수치의 측정 시점/이미지 다름, mutable source, model nondeterminism | immutable commit/evidence + 동일 source snapshot/as-of/config 기록; drift는 QA failure와 분리 |

## H. Recommended First Refactor

**Step 0의 근거 동결 후, Aggregate 하나를 기존 등록형 StepFactory 경로로 기계적으로 이관한다.**

이유:

1. `analytical_aggregate.aggregate`라는 순수 구현과 typed input/output/failure contract가 이미 있다.
2. legacy `_derive`의 aggregate branch는 직접 return하므로 Extremum의 shared row finalization보다 분리 경계가 작다.
3. REG02 ordered_last, scalar reduction, grouped aggregate에 재사용되지만 이번에는 새 behavior를 추가하지 않는다.
4. 기존 `LegacyOperatorFactory` 등록형 builder + `FunctionStep`을 사용하므로 새 execution layer/TypedOperator 계층을 만들 필요가 없다.
5. 현재 partial gate와 canonical date binding을 보존하고, 한 entry 등록과 한 body 제거를 하나의 revert 단위로 만들 수 있다.

첫 step에서 하지 않을 것: `aggregate` 알고리즘 리팩터링, grouping date alias 수정, ADD16 denominator 추론, shared alias 통합, Calculation unit 보완, output coverage 신규 acceptance, History/Renderer 이동. 이관만으로 회귀가 나오면 그 원인을 해결하기 전 다음 operator로 진행하지 않는다.

## I. 이번 감사의 Complexity Delta / Contract Delta

```text
Complexity Delta
Files changed: 이 architecture artifact 1개 (프로젝트 코드 0)
New classes: 0
New public contracts: 0 (제안만, 실행 계약 추가 없음)
New registry entries: 0
New special-case branches: 0
New central-dispatch branches: 0
Removed branches: 0
Duplicated contract sources added: 0
Duplicated contract sources removed: 0
Largest modified method LOC: N/A (코드 미수정)
Largest modified class LOC: N/A
Largest modified module LOC: N/A
Responsibility growth detected: 이번 변경 false; 현 구조의 누적 책임 증가 true
Delta verdict: COMPLEXITY_PASS (문서-only)
Architecture verdict: REFACTOR_REQUIRED (다중 HIGH/중복/책임 누출, 단계별 승인 필요)
```

```text
Contract Delta
New contracts: 0 implemented
Modified contracts: 0 implemented
Removed contracts: 0
Canonical source of truth: 현행 복수 owner 확인; 목표는 Capability Input/Output Spec + operator contract
Consumers: resolver, coverage/IR, source-result adapter, runtime handlers, projection
Duplicated mappings remaining: D1–D8, 이 감사에서는 제거하지 않음
History / Renderer / Data / Oracle: frozen
```

Pre-change check 결론: 이번 수정 대상은 감사 문서뿐이다. 실행 의미 owner/중복/책임 누출을 위 표에서 식별했고, 구조 변경 필요성은 인정하되 구현 승인은 이 문서가 부여하지 않는다. 기존 skill의 기능·회귀·안전성 규칙을 약화하지 않는다.

**테스트 상태는 기존 Golden 근거를 인용한 것이며 이번에 재실행한 결과가 아니다. 신규 QA recovery/Strict 증가 주장은 없다. 설계 artifact 저장 후 종료하며 다음 단계는 Step 1 승인이다.**
