# Recoverability Repair R5 — 2026-10-03

## Scope

- 대상 순서: `REG02 → ADD16/ADD25 → CN08 → PF02`
- 이번 iteration에서 실제 처리: `REG02`만
- `ADD16/ADD25`, `CN08`, `PF02`: 보호 sentinel 실패로 보류
- 공식 Strict baseline: `17/57`
- provisional candidate: `REG02` 회복 포함 시 `22/57`
- 18002: 변경 없음

## REG02

### Root cause

`price.series` TypedResult가 `date/value`를 보유하고 있었지만 Gemma AAST의
`aggregate(last, field=value)`에 `order_by`가 없었다. 기존 aggregate는 시간 순서를
추측하지 않고 `aggregate_order_required`로 fail-closed했다.

### Common contract repair

기존 aggregate executor를 새로 만들지 않고, capability boundary에서 다음 조건을
만족할 때만 기존 aggregate args에 `order_by=date`를 바인딩했다.

- aggregation이 `first` 또는 `last`
- 명시적 `order_by`가 없음
- 입력 rows가 mapping임
- canonical date field가 정확히 하나로 해석됨

날짜가 없거나 모호하면 기존 `aggregate_order_required`를 유지한다. row insertion order,
positional selection, QA/question/entity 특례는 사용하지 않았다.

### Validation

- targeted unit: `3 passed`
- REG02 fresh strict probe: `3/3` 최신 날짜와 가격 반환
- 결과: `STABLE_RECOVERED` 후보
- `rag_core`: `1554 passed / 0 failed`, 1 warning, 695 subtests
- `rag_chat`: `155 passed / 1 known legacy failure`

rag_chat known failure는
`test_disconnect_stops_real_ast_retry_before_blocking_invocation_returns[legacy_control-False]`
이며 이번 aggregate 수정과 무관하다.

## 보호 sentinel 결과

REG05, GM02, ADD27은 정상 실행했다. 그러나 MP01은 다음과 같이 실패했다.

- 질문: `희소금속 보고서에 언급된 광종 가격 보여줘`
- fresh probe: `3/3 semantic_plan_incomplete`
- 결과: 기존 sentinel 안정성을 확인하지 못함

따라서 MP01 failure는 REG02 수정의 인과적 regression이라고 단정하지 않지만, 보호
sentinel gate를 통과하지 못했으므로 ADD16/ADD25로 진행하지 않고 iteration을 중단했다.
MP01은 planner/model nondeterminism 또는 기존 plan-generation regression으로 별도 감사가
필요하다.

## Recovery ledger

| QA | Result | 근거 |
|---|---|---|
| REG02 | `STABLE_RECOVERED` 후보 | canonical date 기반 `last`, fresh 3/3 |
| ADD16 | 보류 | scalar denominator reduction/composition 필요 |
| ADD25 | 보류 | typed dependency/result binding 필요 |
| CN08 | 보류 | period_change와 evidence 분리 필요 |
| PF02 | 보류 | temporal continuation planner branch 필요 |
| MP01 sentinel | `FLAKY/UNRECOVERED` | fresh 3/3 동일 plan failure |

공식 Strict는 full replay 전까지 `17/57`이다. REG02는 strict oracle 재확정 전
`PROVISIONAL_CONTENT_PASS`로만 관리하며 provisional 후보는 `22/57`로 기록한다.

## Complexity Delta

- Files changed: `live_multihop.py`, `test_live_multihop.py`, 본 artifact
- New classes: 0
- New public contracts: 0
- New registry entries: 0
- New special-case branches: 0
- New central-dispatch branches: 0
- Removed branches: 0
- Duplicated contract sources added/removed: 0/0
- Responsibility growth: 없음
- Verdict: `COMPLEXITY_PASS`

수정은 기존 aggregate/operator와 canonical date resolver를 재사용했다. 기존 alias
mapping duplication은 `REFACTOR_CANDIDATE`로 유지한다.

## Contract Delta

- New contracts: 없음
- Modified contract: ordered aggregate binding at capability boundary
- Canonical source of truth: existing `date` canonical field resolver + existing aggregate `last`
- Consumers: live AAST aggregate execution, price latest-value path
- Duplicated mappings remaining: existing `_METRIC_FIELDS`/live alias/renderer mappings

## 다음 단계

1. MP01 plan-generation failure를 먼저 별도 원인 감사
2. 보호 sentinel 안정성 회복 후 `ADD16/ADD25` scalar reduction/dependency 검토
3. 이후 `CN08 period_change`, `PF02 temporal_continuation` 순서

이번 iteration에서는 ADD16/ADD25/CN08/PF02를 수정하지 않았고, QA57 full replay 및
18002 배포도 수행하지 않았다.
