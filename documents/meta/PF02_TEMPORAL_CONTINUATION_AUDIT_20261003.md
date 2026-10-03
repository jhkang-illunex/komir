# PF02 Temporal Continuation Audit — 2026-10-03

## 결론

PF02의 기존 `temporal_continuation` contract는 현재 코드에서 정상적으로
재사용된다. 명시적 비교가 없는 historical price + future forecast 요구에서 Gemma가
생성한 generic `JOIN` 또는 `COMPARE(side_by_side)`를 typed semantic requirement와
branch contract에 따라 `COMPARE(operation=temporal_continuation)`으로 정규화한다.

성공 실행에서는 다음 결과를 확인했다.

```text
historical observed: 131 rows
future forecast: 24 source rows → 23 appended rows
boundary duplicate: 1 forecast base/boundary row excluded
final output: 154 rows, observed first, forecast after
```

다만 fresh 3회 중 1회는 temporal executor에 진입하기 전에 semantic parser가
`requested_output_not_produced:price_forecast`로 실패하여 `semantic_plan_incomplete`가
되었다. 따라서 PF02는 `STABLE_RECOVERED`가 아니라 `FLAKY`다. 이 실패는
`temporal_continuation`의 unit/entity/date contract 문제가 아니라 semantic plan
생성 변동이다. 이번 iteration에서는 이를 질문 특례나 planner 완화로 보정하지 않았다.

## Trace

### Semantic requirements

성공 trace의 typed requirements는 다음 두 branch다.

```text
1. domain=price, metric=price_series,
   mineral=니켈, period=trailing_months(6), criterion_mode=REPRESENTATIVE
2. domain=price, metric=price_forecast,
   mineral=니켈, period=future_horizon(1), criterion_mode=REPRESENTATIVE
```

질문에는 동일 기간 비교, 차이, side-by-side 의미가 없다. 따라서 temporal
continuation이 요구된다.

### Generated branches and binding

성공 trace의 raw AAST는 다음 구조였다.

```text
retrieve_nickel_price_6m
retrieve_nickel_forecast
join_price_and_forecast(left, right, join_key=[date], how=full)
```

정규화 후 graph는 다음과 같다.

```text
retrieve_nickel_price_6m
retrieve_nickel_forecast
compare(
  operation=temporal_continuation,
  left_field=value,
  right_field=predicted_price
)
```

두 branch 모두 root composition에 연결되고, forecast branch의
`predicted_price` output contract도 보존된다.

### Boundary compatibility

| 항목 | historical | forecast | 판정 |
|---|---|---|---|
| entity | 니켈 | 니켈 | compatible |
| metric | price | price_forecast | temporal continuation contract에서 compatible |
| criterion | REPRESENTATIVE / LME CASH | REPRESENTATIVE / LME CASH | compatible |
| unit | USD/톤 | USD/톤 | compatible |
| period | trailing 6 months | future horizon | non-overlapping temporal roles |
| date | observed date | forecast_date | canonical date로 정렬 |
| provenance | observed | forecast | `observation_type` 보존 |

`temporal_continuation`은 동일 날짜를 side-by-side로 맞추지 않는다. observed의
마지막 날짜 이하인 forecast row는 기준월 중복으로 제외하고, 이후 forecast row만
붙인다.

## 최초 causal boundary

### 성공 실행

최초 잠재 divergence는 `Generated AAST → Composition Operator`였다.

Gemma가 `JOIN(full, date)` 또는 `COMPARE(side_by_side)`를 만들었지만, typed
requirements가 historical→future continuation을 명시하고 기존 operator로
결정 가능하므로 relation normalization이 이를 `temporal_continuation`으로
변환했다. 이후 validation, capability calls, TypedResult, final projection은
정상이다.

### 실패 실행

fresh run 1회는 다음 단계에서 중단됐다.

```text
semantic parser
→ requested_output_not_produced:price_forecast
→ semantic_plan_incomplete
```

따라서 이 실행에서는 AAST branch, relation operator, capability, TypedResult에
도달하지 않았다. `temporal_continuation` failure로 분류하지 않고
`FLAKY / PLAN_GENERATION`으로 분리한다.

## PF02 fresh ×3

| Run | AAST/normalization | capability calls | result | 판정 |
|---:|---|---|---|---|
| 1 | semantic parser 이전 실패 | 미진입 | `semantic_plan_incomplete` | fail |
| 2 | `JOIN → temporal_continuation` | price.series + forecast.price | 154-row continuation | success |
| 3 | `JOIN → temporal_continuation` | price.series + forecast.price | 154-row continuation | success |

Strict content 기준으로는 `2/3`이며, 안정성 분류는 `FLAKY`다.

## Existing contract reuse

새 operator는 만들지 않았다.

- `live_multihop._normalize_relation_contract`: typed requirement와 graph shape를
  사용해 generic join/side-by-side를 continuation으로 정규화
- `relational_ops.execute_relation`: 기존 `temporal_continuation` 실행
- canonical fields: historical `value/date`, forecast `predicted_price/forecast_date`
- output: `TIME_SERIES`, `observation_type=observed|forecast`, provenance 유지

명시적 compare/difference/same-period 요청은 기존 side-by-side/alignment 의미를
유지한다.

## Regression

관련 테스트:

```text
test_live_multihop.py
test_live_relations.py
test_semantic_group_alignment.py
→ 117 passed
```

전체 회귀:

```text
rag_core: 1557 passed / 0 failed
rag_chat: 155 passed / 1 known legacy contract failure
```

보호 sentinel은 모두 non-abstain으로 완료되었다.

```text
REG02, REG05, MP07, ADD01, ADD49, GM02, ADD27: regression 없음
```

18002는 변경하지 않았다.

## Repair decision

이번 iteration에서 추가 코드는 수정하지 않았다. temporal composition contract는
이미 원하는 경로로 동작하며, 남은 1/3 실패는 semantic parser output 변동이다.
이를 PF02 전용 retry, 질문 문자열 분기, validator 완화로 숨기지 않았다.

PF02 상태: **FLAKY**

## Complexity Delta

```text
Files changed: audit artifact 1개; 이번 iteration production code 0개
New classes: 0
New public contracts: 0
New registry entries: 0
New special-case branches: 0
New central-dispatch branches: 0
Removed branches: 0
Duplicated contract sources added: 0
Duplicated contract sources removed: 0
Responsibility growth detected: false
Verdict: COMPLEXITY_PASS
```

기존 temporal normalization과 relation executor는 이전 iteration의 공통 contract며,
이번에는 이를 재사용했다. 기존 semantic parser와 legacy composite 경로의 병렬성은
별도 `REFACTOR_CANDIDATE`로 유지한다.

## Contract Delta

```text
New contracts: 없음
Modified contracts: 없음
Removed contracts: 없음
Canonical source of truth:
  Typed semantic requirements + existing relational temporal_continuation contract
Consumers:
  live_multihop normalization, relational_ops executor, TypedResult/projection
Duplicated mappings remaining:
  기존 semantic/legacy presentation 경로의 병렬 mapping
```

## 다음 단계

PF02는 source/data blocked가 아니라 continuation 경로 자체는 회복되었으나,
semantic parser 변동으로 `FLAKY` 상태다. 추가 QA cluster로 확장하지 않고,
후속 iteration에서 공통 semantic output preservation/plan stability를 별도로
검토해야 한다.
