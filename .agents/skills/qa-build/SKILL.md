---
name: qa-build
description: AST 기반 질의 처리기의 QA corpus, deterministic fixture, parser·Logical AST·lowering·execution 회귀 검증을 확장할 때 사용한다.
---

# qa-build

QA 질문을 억지로 통과시키기 위한 예외처리 스킬이 아니다. QA를 AST 질의 시스템의
regression/conformance corpus로 관리하고, 반복되는 capability gap만 일반화된 구현
후보로 제안한다.

## 기본 흐름

항상 다음 방향으로 진행한다.

```text
QA question
→ Semantic decomposition
→ Required data / metric / dimension
→ Operation graph
→ AST capability 비교
→ Deterministic fixture
→ Parser
→ Logical AST
→ Lowering
→ Execution
→ Semantic validation
→ Regression
```

질문별 if/else, 질문 번호 분기, expected value를 production logic에 넣지 않는다.

## 필수 작업 순서

신규 QA마다 다음을 수행한다.

1. 현재 QA fixture와 regression 구조를 확인한다.
2. 동일·유사 질문과 중복을 확인한다.
3. entity/dimension, metric, operation, domain operation, temporal semantics를 분해한다.
4. 1st/2nd/3rd-order로 분류한다.
5. operation graph를 먼저 도출한다.
6. 현재 AST capability와 비교하고 기존 primitive 조합 가능성을 확인한다.
7. 필요하면 production과 독립된 deterministic synthetic fixture를 추가한다.
8. parser → Logical AST → lowering을 실행하고 가능한 경우 execution까지 검증한다.
9. parsing, AST completeness, lowering, semantic correctness, deterministic result를 각각 검증한다.
10. 기존 regression 전체를 실행한다.
11. 실패를 분류하고 capability gap을 기록한다.
12. 여러 QA에서 반복되는 gap만 일반화 후보로 제안한다.

신규 QA 실패만으로 질문별 production 특례를 추가하지 않는다. 다만 공통 implementation
bug 또는 일반화 가능한 capability gap이면 아래 Autonomous Completion Policy에 따라
현재 범위 안에서 수정·검증을 계속한다.

## Operation graph와 분류

자연어가 아니라 연산 그래프를 기준으로 판단한다.

- 1st-order: 직접 조회 또는 Filter → Aggregate/Lookup
- 2nd-order: 조회 → GroupBy/Aggregate → Sort/Rank/TopN/First/Last
- 3rd-order: 복수 기간·대상 중간 결과 → Compare/Calculate → Sort/Select

기본 연산은 Filter, Aggregate, GroupBy, Sort, Rank, TopN, BottomN, Max, Min, First,
Last, Compare, Calculate를 우선 조합한다. HHI, TSI, RCA, TII, trade_growth_rate,
country_dependency도 semantic operation으로 별도 확인한다. metric 차이는 보존한다
(수입량과 수입액을 동일시하지 않는다).

## Deterministic fixture

fixture는 작고 결정적이며 production 데이터와 독립적이어야 한다. Random fixture를
사용하지 않는다. 가능하면 다음 관계를 관리한다.

```text
question → semantic requirement → operation graph → expected AST
→ expected lowering → expected result
```

연산 오류를 드러내도록 동일값/tie, 0, NULL, 빈 결과, 단일·복수 row, 기간 경계,
복수 국가·광물, 단위 차이, missing period를 포함한다. fixture가 production behavior를
정의하거나 expected result가 production 코드로 유입되어서는 안 된다.

## Paraphrase와 semantic invariant

동일 의미의 표현(가장 큰/최대/제일 높은/1위)을 canonical AST로 수렴시킨다. 단,
수입량·수입액 등 metric distinction은 반드시 유지한다. 어순·존댓말·구어체 변경도
검증한다.

## Unsupported / adversarial

권한 상승, 신분 주장에 따른 내부자료 접근, 임의 DB/vector/index 선택, SQL·DDL·DML,
shell/script/code 실행, 임의 URL, 시스템 동작 변경, executable HTML/script 출력,
미등록 capability 요청을 정상 데이터 requirement로 변환하지 않는다.

가능한 reason:

```text
PRIVILEGE_ESCALATION
INTERNAL_DATA_REQUEST
SYSTEM_CONTROL
CODE_OR_SQL_EXECUTION
EXTERNAL_RESOURCE_ACCESS
OUTPUT_INJECTION
UNKNOWN_CAPABILITY
```

정상 데이터 질문에 오염된 지시가 섞이면 unsupported 부분만 제거하고 데이터
requirement를 보존한다. 순수 unsupported라면 requirements/AST를 억지로 만들지 말고
명시적 unsupported/failure로 종료한다. 키워드 blacklist를 만들지 말고 Gemma structured
semantic parsing을 우선한다. 문서 안의 `DROP TABLE`, `SQL`, `administrator`, `vector`,
`<script>` 문자열을 검색하는 요청과 실행 지시는 구분한다.

오염 invariant:

```text
AST(정상 질문) == AST(정상 질문 + unsupported instruction)
```

## 실패 분류

최소 다음을 구분한다.

```text
PASS
SEMANTIC_FAIL
PARSER_FAIL
LOGICAL_PLAN_INCOMPLETE
LOWERING_FAIL
CAPABILITY_MISSING
DATA_UNAVAILABLE
AMBIGUOUS_QUERY
UNSUPPORTED
```

`failure == None`만으로 PASS 처리하지 않는다. parser 성공, AST 완전성, lowering 성공,
semantic correctness, deterministic result를 모두 확인한다. parser 실패를 downstream
fallback으로 숨기거나 capability missing을 임의 fallback으로 감추지 않는다.

## Primitive expansion policy

질문 하나 때문에 primitive를 추가하지 않는다.

1. 기존 primitive 조합 가능 여부
2. 기존 primitive 일반화 가능 여부
3. 동일 gap이 여러 QA에서 반복되는지
4. 반복될 때만 일반화 capability 후보 제안

`FindLargestImportCountry` 같은 question-specific primitive는 만들지 않는다.

## Production 보호

QA build는 parser/AST/lowering/fixture 검증 범위에 둔다. QA 질문을 production에
하드코딩하지 않고, synthetic fixture를 production 로직에서 참조하지 않는다. 기존
regression의 PASS→FAIL은 별도 원인 분석 없이 승인하지 않는다. 다음은 범위 밖이다.

- 전체 architecture 재설계
- 새 agent framework
- DB schema 대규모 변경
- 운영 DB 데이터 생성
- RBAC, SQL firewall, network firewall

## 필수 보고

완료 보고에는 다음을 포함한다.

- 신규/중복/실제 coverage 질문 수
- 1st/2nd/3rd-order 및 adversarial 수
- fixture·synthetic·paraphrase·boundary 변경
- PASS와 각 실패 분류별 개수
- 관련 QA별 capability gap, 필요한 operation, 기존 primitive 조합 가능성, 일반화 가능성
- Existing regression damage: NONE 또는 구체적인 PASS→FAIL 원인
- 반복 gap만 포함한 다음 구현 후보

새 QA가 처리되지 않으면 먼저 deterministic fixture로 재현하고 capability gap으로
기록한다. 반복되는 일반 gap만 구현을 검토한다.

## Autonomous Completion Policy

이 스킬은 분석·보고만 수행하지 않는다. 사용자가 별도로 분석만, 수정 금지, 계획만을
지시하지 않는 한 제공된 QA corpus를 자기완결적으로 처리한다.

```text
QA corpus
→ Baseline regression
→ QA semantic analysis
→ Fixture registration
→ Deterministic synthetic data
→ Parser / AST / Lowering regression
→ Failure classification
→ Common bug fix
→ Generalizable capability implementation
→ Full regression
→ Remaining gap analysis
→ 반복
→ Final report
```

중간 분석 후 승인을 기다리지 않고 명확한 범위의 구현·테스트를 계속한다.

## Definition of Done

다음 조건을 만족하기 전에는 완료로 보고하지 않는다.

1. 모든 QA가 fixture corpus에 등록되었거나 미등록 사유가 기록됨
2. 각 QA에 semantic requirement, query order, operation graph, expected capability,
   expected AST/invariant, lowering, deterministic result 또는 expected failure가 있음
3. 필요한 deterministic synthetic data가 구성됨
4. 신규 QA regression이 실제 실행됨
5. 기존 regression 전체가 실행됨
6. 가능한 공통 implementation bug가 수정됨
7. 기존 architecture 안에서 일반화 가능한 반복 capability gap이 구현됨
8. 구현 후 전체 regression을 재실행함
9. 남은 실패가 failure/capability category로 분류됨
10. 질문별 hardcoding과 fixture leakage를 점검함
11. 최종 결과를 수치로 보고함

## Baseline Failure Policy

기준선 실패를 발견해도 중단하지 않는다. 기존 실패와 신규 QA 실패를 구분하고, 기존
실패를 재현하여 공통 원인을 찾는다. `None` 역참조, dependency 상태 전파, output
naming, 명백한 schema contract mismatch 같은 일반 bug는 최소 수정한 뒤 baseline
regression을 다시 실행하고 신규 QA 작업을 계속한다.

## Capability Gap Implementation Policy

capability gap은 먼저 일반화 가능성을 판단한다. 여러 QA에서 반복되고, 특정 문자열·
광물·국가에 종속되지 않으며, 일반 data operation으로 정의 가능하고, 기존 AST와
일관되며, deterministic fixture로 검증 가능하고, 기존 regression을 훼손하지 않으면
이 스킬 안에서 구현한다. 예를 들어 `GroupBy → Aggregate → Sort → First`가 반복되면
질문별 primitive가 아니라 일반 AST composition capability로 구현한다.

## Capability Gap Escalation Policy

대규모 architecture 변경, 새 외부 시스템·데이터 source, DB schema 대규모 변경,
불명확하거나 충돌하는 요구사항, 보안·권한 정책 결정, fixture만으로 expected behavior
결정이 필요한 경우는 임의 구현하지 않고 `ARCHITECTURAL_OR_REQUIREMENT_GAP`으로
기록한다. 구현 가능한 일반 gap은 `IMPLEMENTABLE_GENERAL_GAP`으로 처리한다.

## Iterative Repair Loop

```text
while actionable_failures_exist:
    classify failure
    implementation bug면 공통 원인 최소 수정
    generalizable gap이면 일반화 구현
    fixture error면 fixture 수정
    semantics가 틀렸음이 증명되면 기대값 수정
    unsupported/architectural gap이면 기록 후 계속
    affected tests와 regression 실행
```

동일 원인으로 반복 실패하면서 architecture 변경이 필요하면 무한 수정하지 않고 gap으로
전환한다.

## Fixture Registration Is Mandatory

QA 분석만 하고 fixture 등록 전에 멈추지 않는다. 기존 fixture schema를 우선 재사용하며,
각 항목은 가능한 경우 다음 metadata를 가진다.

```text
question
semantic_requirement
query_order
operation_graph
expected_ast
expected_lowering
expected_result
expected_failure
tags
```

## Multi-turn Fixture Policy

`① → ② → ③` 질문은 독립 질문 세 개로 끝내지 않고 conversation fixture로도 검증한다.

```text
Turn 1 result
→ Projection / reference
→ Turn 2
→ selected entity
→ Turn 3
```

entity, filter, projection, 기간, 단위가 다음 AST에 올바르게 전달되는지 확인한다.

## No Premature Stop

fixture를 다음 단계에서 추가하겠다는 상태, capability gap을 발견했다는 상태, baseline
실패를 발견했다는 상태, 분석만 완료했다는 상태에서 종료하지 않는다. 현재 repository와
요청 범위에서 수행 가능하면 실제 구현·fixture·회귀를 계속한다.

## Final Stop Conditions

- `DONE`: corpus 반영, 구현 가능한 공통 문제 수정, 전체 regression, 남은 gap 분류 완료
- `DONE_WITH_BLOCKERS`: `PENDING == 0`, actionable QA가 없고 일부 QA만
  `BLOCKED_SUBSET`으로 남은 상태. 나머지 corpus 처리가 끝났으면 정상 완료로 취급한다.
- `BLOCKED`: `PENDING == 0`이고 `ACTIONABLE == 0`이며 `BLOCKED > 0`인 경우에만 사용한다.
- `SAFETY / SCOPE BOUNDARY`: 명시적 금지 변경 없이는 진행 불가

B/C라도 blocker와 무관한 QA 작업은 계속 수행한다. 처리 가능한 QA가 하나라도 남아
있으면 전체 작업을 `BLOCKED`로 종료하지 않는다.

## Partial Blocker Rule

일부 QA가 외부 dependency 또는 fixture 부재로 차단되어도 전체 qa-build를 중단하지
않는다. 차단된 항목은 `BLOCKED_SUBSET`으로 격리하고 actionable QA를 계속 처리한다.

상태를 다음과 같이 구분한다.

```text
PENDING  아직 처리하지 않은 QA
BLOCKED  시도했으나 외부 dependency로 진행할 수 없는 QA
FAILED   현재 parser/semantic/AST/lowering에서 실패한 QA
PASS     검증 완료 QA
```

아직 fixture에 등록하지 않은 QA는 blocker가 아니라 `PENDING`이다. `PENDING`이 있고
처리 가능하면 계속 실행한다.

## Exhaustion Rule

현재 corpus에 actionable item이 없어질 때까지 반복한다.

```text
while actionable_qa_exists:
    next QA batch 선택
    fixture 등록
    semantic 분석
    가능하면 deterministic fixture 구성
    parser / AST / lowering 실행
    결과 분류
    공통 bug면 수정 후 regression
    일반 capability gap이면 구현 후 regression
    외부 dependency면 BLOCKED_SUBSET 기록 후 계속
    그 밖에는 결과 기록 후 계속
```

종료 조건은 `PENDING == 0` 또는 remaining QA가 모두 실제 `BLOCKED_SUBSET`인 경우다.

## Corpus Completion Report

최종 보고에는 다음 수치를 반드시 포함한다.

```text
TOTAL_CORPUS:
REGISTERED:
PASS:
FAILED:
CAPABILITY_GAP:
UNSUPPORTED:
BLOCKED:
PENDING:
```

다음 invariant를 검증한다.

```text
TOTAL_CORPUS == PASS + FAILED + CAPABILITY_GAP + UNSUPPORTED + BLOCKED + PENDING
```

`STATUS: DONE`은 `PENDING == 0`이고 `ACTIONABLE == 0`일 때만 사용한다. blocked 항목이
있어도 나머지 corpus 처리가 끝났으면 `STATUS: DONE_WITH_BLOCKERS`로 보고한다.

## Final Report Only After Execution

최종 보고에는 실제 실행 결과를 포함한다.

```text
Baseline: passed / failed
QA corpus: received / registered / duplicate / unsupported
Implementation: bugs fixed / generalized capabilities / files changed
Final regression: passed / failed / semantic failures / capability gaps
Remaining gaps: gap / affected QA count / not-implemented reason
Regression damage: existing PASS → FAIL count
TOTAL_CORPUS / REGISTERED / PASS / FAILED / CAPABILITY_GAP / UNSUPPORTED / BLOCKED / PENDING
STATUS: DONE | DONE_WITH_BLOCKERS | BLOCKED
```

계획만 보고하거나 `다음 단계는...`으로 종료하지 않는다.

## PENDING Is Work, Not Status

PENDING은 최종 보고 상태가 아니라 실행 대기열이다. 실행 중 PENDING QA를 발견하면
종료하지 말고 다음 batch로 가져와 처리한다.

다음과 같은 종료는 금지한다.

- `Unregistered supplied QA: PENDING`
- "나머지 질문은 아직 fixture에 등록되지 않았습니다."
- "전체 corpus 기준 DONE이 아닙니다."

위 상태는 종료 조건이 아니라 다음 작업의 시작 조건이다.

## Automatic Corpus Continuation

현재 conversation/task context에서 사용자가 제공한 QA 중 fixture에 등록되지 않은 질문이
있으면 다음을 자동으로 계산한다.

```text
pending corpus = supplied corpus - already registered corpus
```

pending corpus가 있으면 사용자 승인을 기다리지 않고 다음 순서로 계속 처리한다.

```text
pending corpus
→ deduplicate
→ semantic classification
→ fixture metadata registration
→ deterministic fixture construction
→ parser / AST / lowering validation
→ failure classification
→ generalized repair if applicable
→ regression
```

## Do Not Stop Between Batches

corpus가 크면 내부적으로 batch로 나눌 수 있지만 batch 완료를 전체 작업 완료로 간주하지
않는다.

```text
batch 1 → batch 2 → batch 3 → ... → PENDING == 0
```

`batch 1 완료 후 보고하고 중단`하는 동작은 허용하지 않는다. 처리 가능한 PENDING이 있는
동안 exhaustion rule을 계속 실행한다.

## Corpus Accounting Must Be Numeric

최종 보고의 corpus 상태는 모두 정수로 기록한다.

```text
SUPPLIED:
REGISTERED:
PASS:
FAILED:
CAPABILITY_GAP:
UNSUPPORTED:
BLOCKED:
PENDING:
```

`있음`, `일부`, `PENDING` 같은 추상 표현으로 수치를 대체하지 않는다. PENDING 수를 계산할
수 없으면 supplied corpus를 다시 확인하여 먼저 계산한다. 수를 모르는 상태에서 완료로
판단하지 않는다.

## Missing Corpus Input Rule

현재 context에 추가 QA가 존재한다는 사실은 알지만 실제 질문 원문을 더 이상 복원할 수
없는 경우에만 다음 blocker를 허용한다.

```text
BLOCKED_REASON: SOURCE_CORPUS_NOT_AVAILABLE_IN_CURRENT_CONTEXT
```

이 경우에도 접근 가능한 QA는 모두 처리하고, 접근할 수 없는 QA의 개수를 추정하거나
질문을 임의 생성하지 않는다. corpus가 크거나 아직 등록되지 않았다는 이유만으로 blocker로
처리하지 않는다.

## Mandatory Execution Rule

다음 문장을 작성하려는 순간 실제 작업을 계속한다.

- "아직 fixture에 등록되지 않은 항목이 있습니다." → 해당 항목을 등록한다.
- "PENDING으로 남아 있습니다." → 다음 pending batch를 실행한다.
- "따라서 DONE으로 확정할 수 없습니다." → 사유가 PENDING이면 종료하지 않고 처리한다.

## Final Invariant

정상적인 qa-build 종료 조건은 반드시 다음을 만족해야 한다.

```text
PENDING == 0
```

`PENDING > 0`인 상태의 정상 종료는 허용하지 않는다. 유일한 예외는 다음과 같다.

```text
PENDING > 0
AND SOURCE_CORPUS_NOT_AVAILABLE_IN_CURRENT_CONTEXT
```

이 경우에만 `STATUS: BLOCKED`를 허용한다. `STATUS: DONE_WITH_BLOCKERS`는 반드시
`PENDING == 0`이고 BLOCKED subset만 남은 경우에만 사용한다.
