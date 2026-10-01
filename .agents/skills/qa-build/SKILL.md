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

신규 QA 실패만으로 즉시 production code를 수정하지 않는다.

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
