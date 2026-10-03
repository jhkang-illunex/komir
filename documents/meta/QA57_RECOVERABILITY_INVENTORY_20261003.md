# QA57 Recoverability Inventory — 2026-10-03

## 기준

- 공식 Strict baseline: `17/57`
- provisional: `21/57`
- rag_core: `1553 passed / 0 failed`
- rag_chat: `155 passed / 1 known legacy failure`
- 운영 18002: 변경 없음
- QA57 full replay: 수행하지 않음

기존 Strict artifact와 최신 18012 trace를 합쳐 복구 방식 기준으로 재분류했다. 실행 완료나
HTTP 200은 CONTENT_PASS로 계산하지 않았다.

## Recoverability taxonomy 및 QA 분류

| QA | 분류 | 최초 boundary / blocker |
|---|---|---|
| MI02 | EVIDENCE_GAP | element-level evidence 부족 |
| DOC02 | EVIDENCE_GAP | document result에 title 자체가 없음 |
| NEWS03 | EVIDENCE_GAP | 중국 수출통제 specificity/evidence mismatch |
| PF01 | EVIDENCE_GAP | DEV_DUMMY/외부 forecast evidence |
| PF02 | PLAN_GAP | historical + forecast temporal branch 보존 |
| PF03 | DATA_QUALITY_GAP | historical/forecast 공통 time key 부족 |
| IX01 | PLAN_GAP | semantic plan/compare composition |
| MP04 | SOURCE_ADAPTER_GAP | production YoY source binding/materialization |
| MP05 | DATA_GAP | source/data policy |
| MP07 | CONTRACT_BUG → recovered pending | price overview contract; 일부 price population은 별도 |
| MP09 | EVIDENCE_GAP | document evidence validation |
| CN01 | PLAN_GAP | plan generation/composition |
| CN04 | DATA_GAP | external forecast source |
| CN05 | REQUIREMENT_UNSUPPORTED | criterion/forecast ambiguity |
| CN07 | EVIDENCE_GAP | DEV_DUMMY/forecast provenance |
| CN08 | COMPOSITION_GAP + CAPABILITY_GAP | period_change와 document evidence 분리 필요 |
| CN09 | PLAN_GAP | plan generation |
| GM01 | CONTRACT_BUG 후보 / stale 재확인 | compare output binding; 최신 성공 trace와 old 분류 충돌 |
| GM05 | DATA_GAP | active manganese trade source 부재 |
| GM11 | DATA_GAP/SOURCE_ADAPTER_GAP | AAST 이후 resource source |
| GM12 | DATA_GAP | external forecast source |
| GM13 | COMPOSITION_GAP + EVIDENCE_GAP | briefing/document 품질 |
| GM14 | PLAN_GAP | multi-branch selection |
| REG02 | PLAN_GAP | ordered `last`의 `order_by` 누락 |
| REG05 | CONTRACT_BUG → recovered pending | inventory.series registry/type contract |
| REG06 | SOURCE_ADAPTER_GAP | price project upstream |
| ADD01 | CONTRACT_BUG → recovered pending | representative criterion mapping |
| ADD03 | PLAN_GAP | arg-max/root coverage |
| ADD06 | PLAN_GAP | semantic plan incomplete |
| ADD12 | SOURCE_ADAPTER_GAP | adapter/transport unavailable |
| ADD16 | COMPOSITION_GAP | population reduce → scalar ratio |
| ADD18 | CONTRACT_BUG 후보 / stale 재확인 | indicator 실행 성공 trace 존재 |
| ADD25 | COMPOSITION_GAP | dependency/result binding |
| ADD32 | REQUIREMENT_UNSUPPORTED/PLAN_GAP | unsupported combination |
| ADD38 | SOURCE_ADAPTER_GAP | price source empty before projection |
| ADD40 | EVIDENCE_GAP | external forecast evidence |
| ADD45 | PLAN_GAP | navigation plan incomplete |
| ADD46 | PLAN_GAP | navigation plan incomplete |
| ADD49 | CONTRACT_BUG → recovered pending | representative criterion mapping |

참고: `IX02`는 `series → value` canonical alias 수정 후 CAPABILITY_LAYER_RECOVERED이며,
`REG05/MP07/ADD01/ADD49`는 다음 full replay 전까지 provisional이다. `GM01/ADD18/NEWS03`
은 저장된 old classification과 최신 성공 trace가 충돌해 stale 재확인이 필요하다.

DOC02는 title이 실제 upstream에 없으므로 projection alias bug로 완화하지 않는다. ADD38도
source가 빈 결과라 projection만 수정하지 않는다. ADD16은 world 다중 행을 scalar denominator로
줄이는 단계가 없어 positional join을 사용할 수 없다.

## Primitive / contract inventory

| Rank | QA IDs | Category | Required primitive/contract | Input → Output | Existing reuse | Cost | Risk | 예상 회복 |
|---:|---|---|---|---|---|---|---|---:|
| 1 | ADD16, ADD25 | COMPOSITION_GAP | `reduce_scalar` + typed dependency binding | `FactSet → ScalarMetric`; `ResultRef → typed arg` | aggregate/compare 일부 재사용 | 중간 | 높음 | 1–2 |
| 2 | REG02 | PLAN_GAP/CONTRACT_BUG | `ordered_last` | `TimeSeries + order_by(date) → ScalarMetric` | 기존 aggregate `last` 재사용 | 낮음 | 낮음 | 1 |
| 3 | CN08 및 indicator change | CAPABILITY/COMPOSITION_GAP | `period_change` | `IndicatorSeries → ChangeMetric/Series` | indicator typed operation/renderer 일부 존재 | 중간 | 중간 | 1+ |
| 4 | PF02 | PLAN_GAP | `temporal_continuation` branch preservation | `Observed + Forecast → TimeSeries` | 기존 relational operator 존재 | 중간 | 중간 | 1 |
| 5 | IX02 | CONTRACT_BUG | `series → value` canonical alias | `IndicatorRow(value) → projection` | 기존 resolver 재사용 | 완료 | 낮음 | 1 |
| 6 | MP04, REG06 | SOURCE_ADAPTER_GAP | source binding/materialization | `TypedArgs → RawRows → TypedResult` | 기존 adapter 재사용 | 중간~높음 | 중간 | 2 |
| 7 | ADD38 | SOURCE_ADAPTER_GAP | map identity/source availability | `PriceEnvelope[] → mineral rows` | for_each envelope 계약 | 중간 | 중간 | 1 |
| 8 | DOC02 | EVIDENCE_GAP | document title/output policy | `DocumentResult → title` | document result 계약 재검토 | 중간 | 중간 | 1 |
| 9 | MP07, GM13 | DATA_QUALITY/COMPOSITION | population completeness + briefing evidence | `PartialPriceSet → safe composite` | status/partial 보존 | 높음 | 높음 | 1–2 |

`ordered_last`는 새 executor가 필요 없다. planner가 `order_by=date`를 넣으면 기존 aggregate가
처리한다. `period_change`는 단순 alias가 아니며 period, endpoint, unit, evidence 계약이
필요하다. `temporal_continuation`도 새 operator보다 branch preservation이 우선이다.

## ROI 결정

### IMPLEMENT_NEXT

1. **REG02** — 기존 aggregate `last`에 typed `order_by=date`를 연결. 낮은 위험.
2. **ADD16/ADD25** — 기존 aggregate/compare/dependency를 조합하는 scalar reduction cluster.
3. **CN08** — indicator `period_change`와 document evidence를 분리하고 기존 typed operation
   재사용 가능성을 검증.
4. **PF02** — 기존 `temporal_continuation`을 historical/forecast branch 보존에 연결.

### DEFER

- MP04/REG06 source adapter: source binding audit 후 수정.
- DOC02 title policy: title 필수/선택 업무 규칙 확인 필요.
- ADD38: source row 존재 여부 확인 전 projection 수정 금지.
- GM01/ADD18/NEWS03: stale 분류 재확인 후 처리.
- GM13: document briefing 품질과 price branch 분리 후 처리.

### BLOCKED

- PF01, CN07, ADD40: DEV_DUMMY/외부 forecast provenance.
- PF03: 공통 temporal key 부족.
- CN04, GM12: 외부 forecast source 부재.
- CN05: criterion/forecast ambiguity.
- GM05, MP05: source/data 부재 정책.
- MP07 일부 광종 price population: DATA_GAP인지 DATA_QUALITY_GAP인지 source audit 필요.

## 30대 Strict 진입 경로

1. 기존 pending recovery는 full replay 전까지 strict 숫자에 섞지 않는다.
2. `REG02 ordered_last`를 기존 aggregate에 연결한다.
3. `ADD16/ADD25 reduce_scalar/dependency`를 하나의 composition cluster로 검증한다.
4. `CN08 period_change`와 document evidence를 분리한다.
5. `PF02 temporal continuation`을 검증한다.
6. stable recovery 누적 후 QA57 full strict replay를 한 번 수행한다.

이 순서는 source/evidence/data blocked 항목을 억지로 PASS시키지 않으면서 기존 primitive
재사용으로 30대에 접근할 가능성이 가장 높은 경로다.

## Architecture & Complexity Guard

이번 단계는 코드 수정 없이 artifact만 작성했다.

### Complexity Delta

- Files changed: 본 artifact 1개
- New classes/public contracts/registry entries: 0
- New special-case branches: 0
- New central-dispatch branches: 0
- Removed branches: 0
- Duplicated contract sources added/removed: 0/0
- Responsibility growth: 없음
- Verdict: `COMPLEXITY_PASS`

기존 live alias/renderer mapping 중복은 `REFACTOR_CANDIDATE`로 유지한다.

### Contract Delta

- New/modified/removed contracts: 없음
- Canonical source of truth: Capability Registry, TypedResult, aggregate/relational operator contracts
- Consumers: 다음 implementation iteration의 planner/typed boundary/registry handlers
- Remaining duplicated mappings: `_METRIC_FIELDS`, live row aliases, legacy renderer aliases

## 결론

다음 구현 우선순위는 `REG02 ordered_last` → `ADD16/ADD25 scalar reduction/dependency` →
`CN08 period_change` → `PF02 temporal continuation`이다. IX02는 layer recovery가 끝났고,
나머지 source/evidence/data 항목은 현재 코드로 억지 회복하지 않는다. 이번 단계에서는 코드,
prompt, image, 18002를 변경하지 않았다.
