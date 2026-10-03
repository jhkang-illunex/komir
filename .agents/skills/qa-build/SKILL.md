---
name: qa-build
description: AST 기반 질의 처리기의 QA corpus, deterministic fixture, parser·Logical AST·lowering·execution 회귀 검증을 확장할 때 사용한다.
---

# qa-build

## 1. Purpose & Core Invariants

QA를 질의 시스템의 regression/conformance corpus로 관리한다. 역할은 characterization,
deterministic QA construction, conformance/regression verification, generalizable gap discovery다.
QA를 억지로 통과시키거나 fixture만으로 semantic truth를 생성하는 도구가 아니다.

- 질문별 if/else, QA ID/질문 번호 분기, 질문 문자열 hardcoding을 production에 넣지 않는다.
- Synthetic fixture 참조나 expected value의 production 유입(fixture leakage)을 금지한다.
- 반복되는 generalizable capability gap만 구현 후보로 취급한다. 판정 기준은 §6이 소유한다.
- 사용자 지정 범위가 우선한다. 분석만/계획만/수정 금지/behavior-preserving 요청을
  corpus repair 승인으로 확대하지 않는다. 일반 실행 작업은 §7–8에 따라 끝까지 처리한다.

정책 owner:

| 책임 | Authoritative owner |
|---|---|
| QA 의미 분석·fixture·conformance·corpus 상태/종료·집계 | 이 skill의 §2–10 |
| 실제 semantic/input/output 의미 | 현재 요구사항과 기존 Typed Contract / Capability Spec / 구현 근거 |
| Architecture / Contract / Complexity / Decomposition / regression safety audit | [iterative-audit](../iterative-audit/SKILL.md) |
| QA의 기존 PASS 보호·실행 증거 | 이 skill §9–10; iterative-audit과 함께 사용할 때도 cross-check 유지 |

Logical AST, operation graph, lowering이라는 용어와 검증 의무를 유지한다. 현재 Dynamic AAST /
Typed Contract / Capability 경로에 맞춰 실제 검증 경계를 확인하되, fixture가 새 production
architecture를 요구하거나 Registry의 선언만으로 실행·의미 검증을 대체하게 하지 않는다.
Behavior-preserving 작업에서는 frozen-old 실행/현재 계약과 fixture expectation의 충돌을
보고하며, 테스트 기대를 근거로 semantic 변경을 끼워 넣지 않는다.

## 2. QA Processing Pipeline

신규 QA마다 아래 순서를 따른다. 기존 QA/fixture/regression 구조와 동일·유사 질문을 먼저
확인하고 중복을 식별한다.

```text
QA question
→ Semantic decomposition (entity/dimension, metric, operation, domain operation, temporal semantics)
→ Required data / metric / dimension
→ Operation graph + 1st/2nd/3rd-order classification (§3)
→ AST capability 비교 / 기존 primitive 조합 가능성 (§6)
→ Fixture metadata registration / deterministic fixture (§4)
→ Parser → Logical AST → Lowering → Execution
→ Semantic validation → Failure classification (§5) → Regression (§9)
```

Parsing 성공, AST completeness, lowering, semantic correctness, deterministic result를
각각 검증한다. Execution까지 가능한 경로는 실제 실행하고, 불가능한 경로는 원인과
expected failure를 남긴다. 신규 QA가 처리되지 않으면 먼저 deterministic fixture로
재현하여 capability gap을 기록하고, 반복 여부와 구현 가능성을 §6에서 판단한다.

## 3. Semantic / Operation Graph Contract

자연어 표면이 아니라 연산 그래프를 기준으로 판단한다.

- 1st-order: 직접 조회 또는 Filter → Aggregate/Lookup
- 2nd-order: 조회 → GroupBy/Aggregate → Sort/Rank/TopN/First/Last
- 3rd-order: 복수 기간·대상 중간 결과 → Compare/Calculate → Sort/Select

기본 연산 Filter, Aggregate, GroupBy, Sort, Rank, TopN, BottomN, Max, Min, First, Last,
Compare, Calculate를 우선 조합한다. HHI, TSI, RCA, TII, trade_growth_rate,
country_dependency도 semantic operation으로 별도 확인한다. 수입량과 수입액 등 metric
차이를 보존한다.

동일 의미의 paraphrase(가장 큰/최대/제일 높은/1위)는 canonical AST로 수렴하는지 검증한다.
어순·존댓말·구어체 변형도 검사하되 metric distinction을 지우지 않는다.

Unsupported/adversarial 요청은 정상 데이터 requirement로 변환하지 않는다. 대상은 권한
상승, 신분 주장에 따른 내부자료 접근, 임의 DB/vector/index 선택, SQL·DDL·DML,
shell/script/code 실행, 임의 URL, 시스템 동작 변경, executable HTML/script 출력,
미등록 capability 요청이다.

가능한 reason은 다음과 같다.

```text
PRIVILEGE_ESCALATION
INTERNAL_DATA_REQUEST
SYSTEM_CONTROL
CODE_OR_SQL_EXECUTION
EXTERNAL_RESOURCE_ACCESS
OUTPUT_INJECTION
UNKNOWN_CAPABILITY
```

정상 데이터 질문에 오염된 지시가 섞이면 unsupported 부분만 제거하고 데이터 requirement를
보존한다. 순수 unsupported는 requirements/AST를 억지 생성하지 않고 명시적
unsupported/failure로 끝낸다. 키워드 blacklist 대신 Gemma structured semantic parsing을
우선한다. 문서 안의 `DROP TABLE`, `SQL`, `administrator`, `vector`, `<script>` 문자열을
검색하는 요구와 실행 지시는 구분한다.

```text
AST(정상 질문) == AST(정상 질문 + unsupported instruction)
```

## 4. Deterministic Fixture Contract

Fixture는 작고 결정적이며 production 데이터와 독립적이어야 한다. Random fixture를
사용하지 않는다. 기존 fixture schema를 우선 재사용하며 필요한 synthetic data를 구성한다.
각 QA에는 semantic requirement, query order, operation graph, expected capability,
expected AST/invariant, expected lowering, deterministic result 또는 expected failure를
갖춘다. 가능한 metadata는 다음과 같다.

```text
question / semantic_requirement / query_order / operation_graph / expected_capability
expected_ast / expected_lowering / expected_result / expected_failure / tags
```

가능하면 `question → semantic requirement → operation graph → expected AST
→ expected lowering → expected result` 관계를 추적한다. Boundary에는 동일값/tie, 0,
NULL, 빈 결과, 단일·복수 row, 기간 경계, 복수 국가·광물, 단위 차이, missing period를 포함한다.

제공된 QA는 fixture corpus에 등록하고, 미등록 사유가 있으면 기록한다. 단 사유 기록만으로
미등록 QA의 처리 상태를 바꾸지 않는다(§8). 분석 완료를 fixture 등록/실행의 대체로 삼지 않는다.
Fixture는 production behavior의 정본이 아니며 leakage 금지는 §1을 적용한다.

Multi-turn `① → ② → ③`은 독립 질문 세 개뿐 아니라 conversation fixture로도 검증한다.

```text
Turn 1 result → Projection / reference → Turn 2 → selected entity → Turn 3
```

Entity, filter, projection, 기간, 단위가 다음 AST에 올바르게 전달되는지 확인한다.

## 5. Failure Taxonomy

최소 아래 **실행 진단 reason**을 구분한다. Corpus 상태/작업 종료와의 관계는 §8이 소유한다.

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

`failure == None`만으로 PASS 처리하지 않는다. §2의 parser/AST/lowering/semantic/
deterministic 검증을 모두 충족해야 한다. Parser failure를 downstream fallback으로 숨기거나
capability missing을 임의 fallback으로 감추지 않는다.

실패/부분 결과는 최종 error 문자열뿐 아니라 정상 계약과 처음 달라진 boundary를 추적한다.
현재 실행 경로의 requirement → parser/AST → lowering/binding → capability/adapter →
operator → presentation 중 최초 divergence, 위반한 계약, owning component/file과 근거를
기록한다. 관찰할 수 없는 경계는 추측하지 않고 UNKNOWN으로 남긴다. Coverage/provider
정보는 read-only 진단이며 자동 repair 권한이 아니다. 공통 gap은 표면 reason이 아니라
최초 boundary·owner·contract defect·repair pattern이 같은지 비교한다.

## 6. Generalization / Capability Policy

Primitive 확장은 순서대로 검토한다.

1. 기존 primitive 조합으로 표현 가능한가.
2. 기존 primitive를 일반화할 수 있는가.
3. 같은 gap이 여러 QA에서 반복되는가.
4. 반복되는 경우에만 일반화 capability 구현 후보로 제안한다.

질문 하나 때문에 primitive를 추가하거나 `FindLargestImportCountry` 같은 질문 전용
primitive를 만들지 않는다. 구현 가능한 일반 gap은 `IMPLEMENTABLE_GENERAL_GAP`이다.
다음 조건을 만족하면 허용된 범위에서 실제 구현한다.

- 여러 QA에서 반복되며 특정 문자열·광물·국가에 종속되지 않는다.
- 일반 data operation으로 정의 가능하고 기존 AST와 일관된다.
- Deterministic fixture로 검증 가능하고 기존 regression을 훼손하지 않는다.

예: 반복되는 `GroupBy → Aggregate → Sort → First`는 일반 AST composition으로 다룬다.
단순 공통 implementation bug의 최소 수정은 신규 primitive 채택과 구분한다.

대규모 architecture 변경, 새 외부 시스템·data source, DB schema 대규모 변경,
불명확/충돌하는 요구사항, 보안·권한 정책 결정, fixture만으로 expected behavior 결정이
필요한 경우는 임의 구현하지 않고 `ARCHITECTURAL_OR_REQUIREMENT_GAP`으로 escalation한다.
같은 원인으로 반복 실패하며 architecture 변경이 필요하면 무한 repair하지 않고 이 gap으로
전환한다. Production 범위 제한은 §9, 나머지 QA의 계속 처리 여부는 §8을 적용한다.

## 7. Autonomous Execution Loop

일반 실행 요청은 분석/보고로 끝내지 않고 제공 corpus를 자기완결적으로 처리한다(§1의
명시적 제한은 우선). Baseline regression을 먼저 기록한 뒤 다음 loop를 실행한다.

```text
등록 대기열 = 현재 conversation/task의 supplied corpus - already registered corpus
while §8에 따른 처리 가능한 PENDING 또는 ACTIONABLE이 존재:
    다음 QA/batch 선택 → 중복 확인 → §2–4 분석/등록/fixture/실행
    §5로 실패 분류
    공통 implementation bug: 최소 수정
    일반화 가능한 gap: §6 기준으로 구현
    fixture error: fixture 수정
    의미/기대값 오류가 증명된 경우: 근거에 따라 기대값 수정
    unsupported / architectural / external blocker: 분류·사유 기록
    affected tests와 regression 실행 (§9)
    상태·남은 gap·수치 장부 갱신 (§8, §10)
종료/보고 여부는 §8에서만 결정
```

현재 repository와 요청 범위에서 수행 가능하면 중간 분석 후 사용자 승인을 기다리지 않고
계속한다. 등록 대기열이 비어도 등록 후 아직 실행/검증하지 않은 QA를 완료로 간주하지 않는다.

Batch는 내부 실행 단위다. 한 batch 완료, baseline 실패 발견, gap 발견, fixture를 나중에
추가하겠다는 계획, `Unregistered supplied QA: PENDING`, “전체 corpus 기준 DONE이 아님”
등은 종료를 대신하지 않는다. “미등록 항목이 있다”면 등록하고, “PENDING이 남았다”면 다음
batch를 실행한다. 허용된 actionable work를 소진할 때까지 §8의 전이를 반복한다.

## 8. Stop / Blocker State Machine — 상태·종료의 단일 정본

다른 section은 이 정의를 참조하며 별도의 종료 조건을 만들지 않는다.

| QA 상태/지표 | 의미 |
|---|---|
| PENDING | 아직 처리하지 않은 QA. 미등록 QA도 여기에 속하며 정상 종료 상태가 아니라 work queue다. |
| ACTIONABLE | 현재 repository/요청 범위에서 실제로 처리·수정·검증 가능한 QA의 수. 별도 결과 bucket이 아니라 PENDING/실패/gap 등의 실행 가능성 지표다. |
| BLOCKED | 시도했으나 외부 dependency 또는 실제 fixture 확보 불가로 진행 불가능한 QA. 사유를 기록한다. 단순 미등록은 해당하지 않는다. |
| PASS | §2·5의 검증을 완료한 QA. |
| FAILED | 현재 parser/semantic/AST/lowering 등 검증에서 실패한 QA. 실제 진단 reason을 함께 보존한다. |
| CAPABILITY_GAP | 필요한 capability/조합 gap이 확인된 QA. §6의 구현 가능성/escalation 분류와 근거를 보존한다. |
| UNSUPPORTED | §3의 지원 밖 요청으로 판정된 QA. |

각 QA의 집계 상태는 하나로 기록하고 세부 진단 reason은 별도로 유지한다(§10 합계 보존).
`FAILED`/`CAPABILITY_GAP`로 적었다는 이유만으로 ACTIONABLE을 소진했다고 보지 않는다.

외부 dependency 또는 실제 fixture 확보 불가로 일부만 차단되면 `BLOCKED_SUBSET`으로
격리하고 무관한 QA를 계속 처리한다. 만들 수 있는 fixture를 아직 만들지 않은 것은 blocker가
아니다. 범위 내 구현 가능한 QA가 하나라도 남으면 전체 작업을 BLOCKED로 종료하지 않는다.

정상 완료에는 다음 **공통 gate**가 모두 필요하다.

- `PENDING == 0 AND ACTIONABLE == 0`.
- Corpus 등록/필요 fixture 구성, 신규 QA 실제 regression, 기존 regression 및 수정 후
  전체 regression 실행을 마쳤다.
- 가능한 공통 bug와 반복 generalizable gap을 처리했고 남은 실패/gap/blocker를 분류했다.
- 질문별 hardcoding/fixture leakage를 점검했고 §10의 실제 결과·수치 보고를 준비했다.

| 작업 STATUS | 종료 조건 |
|---|---|
| DONE | 공통 gate 충족, 남은 blocked subset 없음. 남은 비실행가능 gap/실패도 분류·보고한다. |
| DONE_WITH_BLOCKERS | 공통 gate 충족, 일부 QA만 BLOCKED_SUBSET이고 나머지 corpus 처리는 끝남. |
| BLOCKED | `PENDING == 0 AND ACTIONABLE == 0 AND BLOCKED > 0`인 전체 진행 불가 상태. 일부 subset만 차단되고 나머지 처리 완료면 위 DONE_WITH_BLOCKERS를 사용한다. 원문 소실 예외는 아래 정의만 허용한다. |
| SAFETY / SCOPE BOUNDARY | 명시적 금지 변경 없이는 진행 불가. 금지를 넘지 않고 경계를 보고하되 무관한 허용 작업은 계속한다. 정상 corpus 완료로 주장하지 않는다. |

`PENDING > 0`인 정상 종료는 금지한다. 유일한 원문 소실 예외는 추가 QA 존재는 알지만
현재 context에서 실제 질문 원문을 더 이상 복원할 수 없는 경우다.

```text
BLOCKED_REASON: SOURCE_CORPUS_NOT_AVAILABLE_IN_CURRENT_CONTEXT
```

접근 가능한 QA를 모두 처리한 뒤에만 이 사유로 `STATUS: BLOCKED`를 허용한다.
접근 불가능한 질문이나 개수를 추정·생성하지 않는다. Corpus가 크거나 미등록이라는 이유는
예외가 아니다. `PENDING > 0`(또는 원문 소실로 전체 수치 확정 불가)을 이 사유로 보고할 수
있으나 DONE/DONE_WITH_BLOCKERS나 전체 집계 완료로 표시하지 않는다. 숫자를 확인할 수
있는데도 추상 표현으로 대체하는 것은 §10 위반이다.

## 9. Regression & Production Safety

기존 실패와 신규 QA 실패를 구분한다. Baseline failure를 발견하면 재현하여 공통 원인을
찾고, 허용된 범위의 일반 bug(`None` 역참조, dependency 상태 전파, output naming, 명백한
schema contract mismatch)는 최소 수정 후 baseline regression을 다시 실행한다.
기준선 실패 자체를 전체 중단 사유로 삼지 않는다(§8).

신규 QA regression과 기존 regression 전체를 실제 실행한다. 수정마다 affected tests와
regression을 검증하고, 구현 후 전체 regression을 재실행한다. 기존 PASS→FAIL은 별도
원인 분석 없이 승인하지 않는다. Hardcoding/leakage 금지는 §1의 정본을 재검사한다.

QA 작업은 parser/AST/lowering/fixture 검증과 §6의 범위 내 공통 repair에 한정한다.
다음은 이 skill의 자율 구현 범위 밖이며 §6의 escalation/§8의 경계로 처리한다.

- 전체 architecture 재설계, 새 agent framework
- DB schema 대규모 변경, 운영 DB 데이터 생성
- RBAC, SQL firewall, network firewall

iterative-audit을 함께 사용하는 감사에서는 그 skill의 architecture·contract·complexity·
decomposition·resource/safety 정본을 적용하며 여기서 병렬 규칙을 만들지 않는다. 그 감사가 QA 실행 결과와
기존 PASS 보호를 대신하지 않는다. Refactor/분석 전용 요청에서 QA repair를 자동 수행하지 않는다.

## 10. Reporting Contract — 수치 장부와 보고의 단일 정본

정상 완료 보고는 §8 gate를 통과한 **실제 실행 결과**를 포함한다. 일반 실행 요청을 계획이나
“다음 단계는...”만으로 끝내지 않는다. 명시적 분석/수정 금지 요청은 §1을 따른다.

수신 원문, 중복, 등록 및 실제 coverage를 구별하고 기존 corpus ID/중복 관리 기준으로 집계한다.
QA별 상태를 중복 집계하지 않으며 다음 수치는 정수로 기록한다.

```text
SUPPLIED / TOTAL_CORPUS / REGISTERED
PASS / FAILED / CAPABILITY_GAP / UNSUPPORTED / BLOCKED / PENDING
TOTAL_CORPUS == PASS + FAILED + CAPABILITY_GAP + UNSUPPORTED + BLOCKED + PENDING
```

“있음”, “일부”, “PENDING”으로 수치를 대체하지 않는다. PENDING을 계산할 수 없으면 supplied
corpus를 다시 확인하여 먼저 계산한다. 원문 소실 예외(§8)라면 확인 가능한 범위의 정수와
전체 집계 불가 사유를 구별하고, 없는 숫자를 채워 invariant 충족/완료를 주장하지 않는다.

최종 보고에 포함할 항목:

- Baseline: passed / failed; 기존 실패와 신규 실패 구분.
- QA corpus: received / registered / duplicate / unsupported, 신규/중복/실제 coverage 질문 수.
- 1st/2nd/3rd-order 및 adversarial 수.
- Fixture·synthetic·paraphrase·boundary 변경.
- Implementation: bugs fixed / generalized capabilities / files changed.
- Final regression: passed / failed / semantic failures / capability gaps, §5 reason별 개수.
- QA별 gap / 필요한 operation / 기존 primitive 조합 가능성 / 일반화 가능성 /
  affected QA count / not-implemented reason.
- 실패/부분 결과의 §5 first-divergence / owning-boundary 근거와 미확정 항목.
- Existing regression damage: NONE 또는 기존 PASS→FAIL 수와 구체 원인.
- 반복 gap만 포함한 다음 구현 후보.
- 위 수치 장부와 invariant 확인, §8에 따른 STATUS 및 blocker/boundary 근거.
