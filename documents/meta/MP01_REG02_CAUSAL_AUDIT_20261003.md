# MP01 ↔ REG02 인과관계 감사 — 2026-10-03

## 결론

현재 18012의 MP01 보호 sentinel 실패는 REG02의 `last/order_by=date` 수정이
직접 만든 회귀로 확인되지 않았다.

- 판정: `NOT_A_REGRESSION`이면서 `KNOWN_BLOCKER_ISOLATED`
- 현재 반복성: `MODEL_NONDETERMINISM`이 섞인 기존 AAST/coverage blocker
- 공통 최초 causal boundary: 문서-derived 광종 branch와 정적 `mineral` requirement를
  AAST Coverage Validator가 동일한 entity 보존 대상으로 비교하는 경계
- 이번 iteration 코드 수정: 없음
- REG02 rollback: 없음

## 검증 identity

| 항목 | 값 |
|---|---|
| source HEAD | `fa423722caeb86bfb83e6561e3b355b20da2ef38` |
| 18012 container image | `sha256:a9116155ea385914dbfb506cd03574a4c54c6b8a5b0a1052f4b9eadf375870f9` |
| 18002 image | `sha256:0d3e757a3d04e75e7b60d7e6917df544b31d4a782d5f7722fb8ddcd3652b466a` |
| 운영 18002 | 변경 없음 |

## MP01 식별 주의

최근 보호 sentinel에서 `MP01`이라는 라벨로 실행한 질문은
`희소금속 보고서에 언급된 광종 가격 보여줘`이다. 이는 QA57 정본의 MP01 질문인
`니켈 가격 추이랑 우리나라 수입국 구성 같이 보여줘`와 다른 질문이다.

따라서 아래 결과는 정확히 최근 보호 sentinel 질문에 대한 결과이며, QA57 MP01의
strict 점수 회귀로 직접 합산하지 않는다. QA57 정본 MP01은 과거 artifact에서
`price.series + trade.country_rank` 경로로 기록되어 있다.

## REG02 변경 경계

REG02 변경은 `LiveOperatorFactory._derive()`의 기존 `aggregate` 실행 경계에만
있다.

```text
aggregation ∈ {first, last}
∧ order_by 없음
∧ 입력 row가 mapping
∧ canonical date가 유일하게 해석됨
→ 기존 aggregate args에 order_by=date 바인딩
```

MP01은 `_parse_ast()` 단계에서 AAST 생성/coverage 검증 또는 그 직후 root 실행에서
실패한다. `aggregate(last/first)`가 포함된 MP01 실행 trace가 없으므로 REG02의
`order_by` binding 경로를 통과하지 않는다. 또한 REG02 변경은 parser, semantic
requirement, capability registry, projection contract를 수정하지 않았다.

따라서 시간적 선후관계만으로 REG02 회귀라고 볼 근거가 없다.

## 이전 성공 근거 재평가

이전 `qa500_live_stability_20261002` 문서 probe에는 같은 sentinel 질문이 다음처럼
기록되어 있다.

- `document-fresh-repeat`: HTTP 200, `abstained=false`, `PARTIAL`, table 2
- `document-fresh`: HTTP 200, `abstained=false`, `PARTIAL`, table 2
- 과거 `document-r1/r3/r4`: HTTP 200, `abstained=false`; 실행 결과는 일부 광종 가격과
  실패 항목을 포함한 PARTIAL 응답

이 기록들은 parser/AAST 전체 trace 또는 strict oracle 3회 성공을 보존한 것이 아니다.
따라서 과거 결과는 `execution/partial success`이지 `STABLE_CONTENT_PASS`가 아니다.

별도 QA57 strict artifact의 MP01 one-run PASS도 현재 보호 sentinel과 질문이 다르고,
반복 안정성을 확정하지 않았다. 이번 결과를 기존 stable PASS regression으로 부르지
않고 `PREVIOUSLY_OVERCLASSIFIED / STABILITY_NOT_ESTABLISHED`로 분리한다.

## 현재 MP01 fresh ×5

질문: `희소금속 보고서에 언급된 광종 가격 보여줘`

각 실행은 새 `session_id`, 빈 history로 시작했다.

| Run | session | HTTP | elapsed(s) | final reason | AAST/validator 관찰 |
|---:|---|---:|---:|---|---|
| 1 | `a199d088-f906-4c85-a7f8-3954f4d3fd65` | 200 | 11.560 | `all_roots_failed` | 문서 branch와 `희소금속` 가격 branch가 생성됐으나 실행 중 retrieval/projection validation 실패 |
| 2 | `b8ede0f5-fbe7-4658-83d7-dc05be529c0b` | 200 | 11.482 | `all_roots_failed` | 동일 계열의 문서-derived branch/정적 entity 충돌 후 root 실패 |
| 3 | `e2e8a5f6-a1e1-4bcd-b839-6d74e4110661` | 200 | 23.992 | `semantic_plan_incomplete` | `ENTITY_PRESERVATION_FAILED`, bounded repair 후 계획 종료 |
| 4 | `396efb8f-b434-4acb-bd70-b7a7a361bf8f` | 200 | 18.772 | `semantic_plan_incomplete` | `ENTITY_PRESERVATION_FAILED`, repair/재계획 경로에서 종료 |
| 5 | `af1d85f1-d5a8-44d3-a572-e1e140a433cc` | 200 | 18.856 | `semantic_plan_incomplete` | `ENTITY_PRESERVATION_FAILED`, repair/재계획 경로에서 종료 |

집계:

- 최종 strict/content 성공: `0/5`
- `semantic_plan_incomplete`: `3/5`
- `all_roots_failed`: `2/5`
- 동일 최종 marker만 반복된 deterministic failure는 아님
- 그러나 5회 모두 성공하지 못했고, 동일한 coverage/entity 경계가 반복됨

## Trace 비교

### Semantic Requirement

현재 trace에서 공통으로 다음 두 requirement가 생성됐다.

```text
document / retrieve / topic=희소금속 보고서
price / current / mineral=희소금속 / criterion_mode=REPRESENTATIVE
```

### AAST 후보

반복적으로 관찰된 정상 의도에 가까운 후보는 다음 구조다.

```text
retrieve_document(topic=희소금속 보고서)
→ project(mineral)
→ for_each(item_type=mineral, operation=retrieve, domain=price, metric=price)
→ optional projection/refresh
```

이 구조에서 가격 광종은 문서 결과의 `mineral` 행에서 동적으로 만들어진다. 따라서
AST에 정적 `mineral=희소금속` retrieve node가 반드시 있어야 하는 것은 아니다.

그러나 Coverage trace는 다음 violation을 반복 기록했다.

```text
ENTITY_PRESERVATION_FAILED:
required=['희소금속'], planned=[]
```

일부 model attempt는 정적 `rare_metal_price` node를 추가해 validator를 통과했지만,
그 node는 문서에서 추출된 실제 광종 집합과 같은 의미의 entity가 아니다. 그 후
retrieval/projection validation 실패 또는 `all_roots_failed`가 발생했다. 이는
validator를 느슨하게 하거나 정적 entity를 강제하여 해결할 수 있는 문제가 아니다.

### 최초 causal failure

```text
Semantic extraction
  → document-derived entity와 literal mineral requirement가 동시에 존재
AAST candidate
  → for_each branch는 동적 광종을 사용하지만 literal entity는 root에 직접 보존되지 않음
Coverage validation
  → ENTITY_PRESERVATION_FAILED(required literal entity, planned dynamic entity 없음)
Bounded repair
  → 일부 시도는 정적 가격 node를 추가하지만 의미적으로 유일한 복구가 아니며 후속 root 실패
Final
  → semantic_plan_incomplete 또는 all_roots_failed
```

분류상 wrapper인 `semantic_plan_incomplete`보다 실제 최초 원인은
`VALIDATOR_REJECTION / ENTITY_PRESERVATION_FAILED`이며, 실행된 후보에서는
`SOURCE/PROJECTION validation`이 추가로 드러난다.

## REG02 인과 판정

| 검사 | 결과 |
|---|---|
| MP01이 `aggregate(last/first)`를 사용했는가 | 확인되지 않음 |
| MP01이 REG02의 `order_by=date` binding을 통과했는가 | 아니오 |
| REG02가 parser/AAST/registry를 변경했는가 | 아니오 |
| REG02 수정 전에도 MP01 plan failure가 관찰됐는가 | 예. 이전 artifact에 동일 MP01 plan 변동/실패 기록 |
| 현재 차이를 설명하는 공통 경계 | AAST coverage의 document-derived entity 보존 + 모델 계획 변동 |
| 최종 판정 | `NOT_A_REGRESSION` |

## Taxonomy 및 circuit breaker

- `MODEL_NONDETERMINISM`: **관찰됨**. 5회에서 AAST shape와 최종 reason이 변동함.
- `KNOWN_BLOCKER_ISOLATED`: **해당**. document-derived entity와 literal entity의
  보존 contract가 별도 blocker로 격리됨.
- `REG02_CAUSED_REGRESSION`: **근거 없음**.
- `DETERMINISTIC_PLAN_FAILURE`: 최종 marker 전체에는 적용하지 않음. 다만
  `ENTITY_PRESERVATION_FAILED` 경계는 반복되는 공통 failure이다.
- 과거 MP01 strict/stable regression: **확정하지 않음**. 과거 sentinel 기록은
  PARTIAL 실행 성공이고 QA57 정본 MP01과 질문도 다르다.

## 수정 여부

이번 감사에서는 수정하지 않았다.

이유:

1. REG02 rollback 근거가 없다.
2. validator를 느슨하게 하면 문서 branch와 실제 광종 집합을 검증하지 못한다.
3. `희소금속`을 정적 광종으로 강제하는 것은 질문/문서 의미를 잘못 만들 수 있다.
4. 올바른 동적 entity 보존 contract는 별도 plan/coverage audit 대상이며, 현재
   MP01 보호 sentinel 하나를 위한 특례로 처리할 수 없다.

## Regression / architecture

이번 iteration에는 코드 변경이 없었다.

- 이전 검증 golden: `rag_core 1554 passed / 0 failed`
- 이전 검증 golden: `rag_chat 155 passed / 1 known legacy failure`
- 18002: 변경 없음
- 새 unit/regression 실행: 코드 변경이 없어 생략
- sentinel regression: 이번 감사 대상은 MP01 원인 분리이며, REG02 fresh 3/3은 유지

### Complexity Delta

```text
Files changed: 0
New classes: 0
New public contracts: 0
New registry entries: 0
New special-case branches: 0
New central-dispatch branches: 0
Removed branches: 0
Duplicated contract sources added: 0
Duplicated contract sources removed: 0
Largest modified method LOC: N/A (이번 iteration 수정 없음)
Largest modified class LOC: N/A
Largest modified module LOC: N/A
Responsibility growth detected: 없음
Verdict: COMPLEXITY_PASS
```

### Contract Delta

```text
New contracts: 없음
Modified contracts: 없음
Removed contracts: 없음
Canonical source of truth: 기존 AAST Coverage Validator 및 document/for_each typed output contract
Consumers: audit only; runtime contract 변경 없음
Duplicated mappings remaining: 기존 alias/renderer mapping debt; REFACTOR_CANDIDATE 유지
```

## Roadmap

REG02와 MP01의 인과관계는 분리되었으므로 REG02 이후 roadmap을 재개할 수 있는
조건은 충족됐다(`NOT_A_REGRESSION`/`KNOWN_BLOCKER_ISOLATED`). 다만 MP01 자체는
보호 sentinel로서 여전히 회복되지 않았으므로, 다음 구현 iteration에서는 MP01을
QA 특례로 고치지 말고 `document-derived entity → for_each → coverage validator`
공통 contract를 별도 분석하는 것이 안전하다.

이번 iteration은 여기서 종료한다. `ADD16/ADD25 → CN08 → PF02`를 이 감사 중에
진행하지 않았고, QA57 full replay도 수행하지 않았다.
