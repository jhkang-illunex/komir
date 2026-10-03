# Legacy → Typed Contract Migration Audit — 2026-10-03

## 범위와 기준

- 환경: 18012 검증 환경만 사용; 18002 변경 없음
- 기준 baseline: authoritative Strict `21/57`
- 대상: 최신 QA57 failure map의 `PLAN_GAP`, `CAPABILITY_GAP`, `COMPOSITION_GAP` 및 해당 경로의 기존 capability
- Full QA57 replay: 미실행
- 판정 원칙: legacy implementation의 실제 output 의미가 TypedResult/Registry로 결정적으로 증명되는 경우만 metadata migration 후보로 판정
- `trade.concentration`의 `import_share` alias 승격은 수행하지 않음. concentration/HHI와 CountryShare는 다른 semantic type임

## Capability별 대조

| Capability | 실제 legacy output | 현재 TypedResult ValueType | Registry output metadata | 영향 QA | 분류 | 예상 recovery |
|---|---|---|---|---|---|---:|
| `trade.country_rank` | country, total/import amount, share_pct, period, unit | `COUNTRY_SHARE` | CountryShare contract는 직전 iteration에서 승격 완료 | GM14는 여전히 잘못된 `trade.concentration` 선택 | `PLAN_SELECTION_GAP` | 0 |
| `trade.concentration` | country, total, share_pct 및 metadata hhi; semantic 목적은 concentration/HHI | `FACT_SET` | 전용 spec 없음; concentration scalar가 TypedResult field로 완결되지 않음 | GM14 | `LEGACY_TYPED_OUTPUT_INCOMPLETE` + downstream `PLAN_SELECTION_GAP` | 0 |
| `trade.monthly` | month, import_amount, import_weight, transaction_count; 실제 관측기간 metadata | `TRADE_SERIES` | 전용 spec 없음; `month`→canonical `period` 선언도 없음 | MP03의 과거 경로(현재 Strict CONTENT_PASS) | `LEGACY_TYPED_CONTRACT_MISMATCH` | 0 즉시; migration 후보 |
| `trade.indicator` | metric별로 TSI/RCA/TII, growth, country_dependency의 서로 다른 field 집합 | `FACT_SET` | metric variant/output type spec 없음 | 현재 authoritative 21건의 직접 영향 미확정 | `LEGACY_TYPED_OUTPUT_INCOMPLETE` | 0 즉시; parameterized contract 필요 |
| `indicator.series` | indicator, value, date/period, unit, provenance | `TIME_SERIES` | 기존 CAPABILITY_OUTPUTS만 있고 action spec 없음 | IX02, CN09, CN08, ADD18(stale) | `LEGACY_TYPED_OUTPUT_INCOMPLETE` | layer 1~3; strict 0 확정 |
| `resource.rank` | country/country_code, production/reserves value, year, unit, provenance | `FACT_SET` | 기존 semantic_v2/field aliases에 분산, Registry action spec 없음 | GM01, ADD16, ADD25 | `LEGACY_TYPED_OUTPUT_INCOMPLETE` | composition 후 0~3 |
| `resource.yoy` | mineral, prior_year, prior_tonnes, year, tonnes, change_tonnes, change_pct | `FACT_SET` | Registry action spec 없음 | MP04 | `LEGACY_TYPED_OUTPUT_INCOMPLETE` | layer 후보 1 |
| `price.volatility_rank` | rank, mineral, first/last date/price, pct_change | `MINERAL_RANKING` | Registry action spec 없음 | 최신 21건 직접 영향 미확정 | `LEGACY_TYPED_CONTRACT_MISMATCH` | 0 즉시; 별도 probe 필요 |

`inventory.latest`, `inventory.series`, `price.overview`, `price.series`는 이미 Registry action
metadata가 존재하므로 이번 migration 누락 목록에서 제외했다. Document capability는 표준
TypedResult 누락보다 evidence/source field 문제(DOC02 등)가 우선이므로 metadata 승격 대상으로
분류하지 않았다.

## 분류 결과

### LEGACY_TYPED_CONTRACT_MISMATCH

- `trade.monthly`: executor와 `TRADE_SERIES`는 존재하지만 Registry가 metric-specific
  series contract와 canonical period를 선언하지 않는다.
- `price.volatility_rank`: executor와 `MINERAL_RANKING`은 존재하지만 Registry가 rank/date/
  price-change output을 선언하지 않는다.

### LEGACY_TYPED_OUTPUT_INCOMPLETE

- `trade.concentration`: 실제 concentration 경로는 존재하지만 scalar HHI의 canonical output
  field/type이 완결되지 않는다. raw `share_pct`를 `import_share`로 승격하는 것은 금지한다.
- `trade.indicator`: metric별 output shape가 다르므로 단일 FactSet metadata로는 불충분하다.
- `indicator.series`, `resource.rank`, `resource.yoy`: semantic output은 결정적이며 action
  metadata만 누락되어 이번 iteration에서 Registry 승격했다.

### PLAN_SELECTION_GAP

- `GM14`: `trade.country_rank`의 CountryShare contract는 존재하지만 현재 requirement가
  `trade.concentration`으로 확정되어 잘못된 output type을 선택한다. metadata 승격만으로
  GM14를 회복하지 않는다.

### TRUE_CAPABILITY_GAP

- 이번에 감사한 existing capability 집합에서는 추가 TRUE_CAPABILITY_GAP을 확정하지 않았다.
  `import_share` 구현은 `trade.country_rank`에 존재하며, 부족한 것은 GM14의 selection/
  composition 경계다. ADD16/ADD25의 reduction, DOC02의 title, forecast/evidence 문제는
  각각 별도 composition/evidence/data 계층이다.

## 적용한 metadata 승격

`semantic_capabilities.py`의 기존 `CAPABILITY_ARGUMENTS` Registry에 다음 세 spec을 추가했다.

| Capability | Output type | Canonical fields |
|---|---|---|
| `indicator.series` | `IndicatorSeries` | indicator, value, date, period, unit, source, provenance |
| `resource.rank` | `ResourceRanking` | country, country_code, mineral, production/reserves, value, year, period, unit, source, provenance |
| `resource.yoy` | `ResourceChange` | mineral, prior_year, prior_tonnes, year, tonnes, change_tonnes, change_pct, value, period, unit, source, provenance |

`resource.yoy`가 새 `resource.rank` surface metric에 먼저 매칭되지 않도록 derived
capability 우선순위를 유지했다. 이는 새 dispatcher branch가 아니라 기존 `_action_id`의
구체적인 derived operation 우선 규칙이다.

## 영향 QA probe

변경 image `komir-rag-chat:legacy-typed-audit-r1`로 fresh session 단건 probe를 수행했다.
이번 probe는 full replay가 아니며 strict recovery를 주장하지 않는다.

| QA | 결과 | 관찰 |
|---|---|---|
| IX02 | `semantic_plan_incomplete` | indicator metadata 승격만으로 planner composition은 미회복 |
| CN09 | `semantic_plan_incomplete` | period_change + evidence branch plan gap 유지 |
| ADD16 | `comparison_alignment_required` | resource metadata 후에도 scalar reduction/alignment 필요 |
| ADD25 | `dependency_unavailable` | price multi-entity dependency 문제 유지 |
| MP04 | `projection_field_unavailable:year` | resource.yoy source 접근 이후 projection/period field gap 잔존 |

따라서 이번 metadata 승격으로 신규 `STABLE_RECOVERED` 또는 strict provisional 증가를
주장하지 않는다. GM14는 사용자 지시에 따라 추가 수정하지 않았다.

## 검증

- 관련 contract/semantic/AAST tests: `92 passed`
- rag_core: `1560 passed / 0 failed` (기존 1558 테스트 + 신규 contract tests 2개)
- rag_chat: 이번 iteration에서 실행하지 않음; 기존 `155 passed / 1 known legacy failure` 유지
- 18002: 변경 없음

## Complexity Delta

```text
Files changed:
  inhouse/rag_core/ragkit/semantic_capabilities.py
  inhouse/rag_core/ragkit/live_multihop.py
  inhouse/rag_core/tests/test_semantic_capabilities.py
  this audit artifact
New classes: 0
New public contracts: 0 (existing Registry metadata extended)
New registry entries: 3 capability specs
New special-case branches: 0
New central-dispatch branches: 0
Removed branches: 0
Duplicated contract sources added: 0
Duplicated contract sources removed: 0
Largest modified method: existing _action_id, small ordering-only compatibility change
Responsibility growth detected: false
Verdict: COMPLEXITY_PASS
```

기존 `_METRIC_FIELDS`/legacy alias와 Registry metadata의 중복은 `REFACTOR_CANDIDATE`로
남아 있다. 이번 iteration에서는 구조 refactor를 수행하지 않았다.

## Contract Delta

```text
New contracts: 0
Modified contracts:
  indicator.series → IndicatorSeries output metadata
  resource.rank → ResourceRanking output metadata
  resource.yoy → ResourceChange output metadata
Canonical source of truth: Capability Registry (CAPABILITY_ARGUMENTS)
Consumers: canonical capability resolver, planner/coverage output validation, typed boundary
Derived-resolution compatibility: resource.yoy remains more specific than resource.rank
Duplicated mappings remaining: semantic_v2 CAPABILITIES, _METRIC_FIELDS, live row aliases
```

## 결론

metadata-only migration으로 즉시 여러 strict QA가 회복되지는 않았다. 가장 큰 남은 공통
문제는 `trade.indicator`의 metric-variant typed contract, `trade.monthly`의 period canonical
field, `trade.concentration`과 CountryShare의 selection/composition 분리다. 이들은 단순
metadata 추가로 의미를 보장할 수 없으므로 다음 ROI iteration에서 별도 contract audit 후
처리해야 한다. 현재 provisional Strict는 `21/57`로 유지한다.
