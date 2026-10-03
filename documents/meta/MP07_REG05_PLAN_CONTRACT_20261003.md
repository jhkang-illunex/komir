# MP07 / REG05 Plan Generation Contract Repair

검증일: 2026-10-03  
검증 환경: 18012 전용  
운영 18002: 변경하지 않음  
Architecture Freeze: 유지

## 결론

두 QA의 공통 최초 원인은 surface metric을 canonical registry로 해석한 뒤
output contract를 연결하는 경계가 slot 정규화와 Validator metric 추론에 가려진
것이었다. 공통 contract를 수정한 뒤 두 QA 모두 fresh session 3/3에서 Plan
Generation, AAST root 생성, Coverage Validation 및 Capability 실행 단계까지
진입했다.

## 변경 사항

### Registry-driven canonical resolution

`semantic_capabilities.CAPABILITY_ARGUMENTS`를 capability metadata의 단일 조회
경계로 사용한다.

| Surface requirement | Canonical capability | Output contract |
|---|---|---|
| `price/current + price_group` | `price.overview` | `PriceOverview` 성격의 price/date/unit/criterion/provenance 필드 |
| `inventory/latest` | `inventory.latest` | `InventoryObservation` 성격의 mineral/value/date/unit/provenance 필드 |
| `inventory/series` | `inventory.series` | inventory/value/date/period/unit/provenance 필드 |

수정 내용:

1. `_action_slots()`가 generic metric 슬롯을 정리하기 전에 registry를 조회하여
   `strategic_price_groups` 같은 canonical argument를 보존한다.
2. AAST coverage metric 추론에서 inventory domain의 `latest`를 일반 price
   `latest`로 오인하지 않도록 domain-qualified metric을 사용한다.
3. `price.overview`를 TypedResult의 canonical `price` metric 및 `FACT_SET`
   output으로 연결한다.
4. source가 제공하는 `price_date`를 canonical `date`로 해석한다.
5. price criterion label/serial은 source에 존재하는 경우만 projection하며,
   annotated physical key도 기존 canonical resolver로 찾는다.

중앙 dispatcher의 새 domain-specific `if/elif` branch: 0  
새 public abstraction: 0  
QA ID/질문 문자열 분기: 0  
Registry metadata 변경: `price.overview`, `inventory.latest`, `inventory.series` 계약 추가

## MP07 trace / 결과

질문: `전략광종 가격 현황 한눈에 보여줘`

### Before

`price/current + strategic`가 `price.overview`로 canonicalize되지 않아 output
schema가 결정되지 않았고 projection validation 전에 plan이 실패했다.

### After

```text
Semantic Requirement
  domain=price, metric=current, criterion_mode=REPRESENTATIVE,
  price_group=strategic
→ registry: price.overview
→ canonical args: strategic_price_groups=[strategic_six, strategic_ten]
→ PriceOverview output contract
→ AAST root: project_price_summary
→ Coverage Validator: valid
→ capability: price.overview
→ projection: success
```

fresh session 결과: 3/3 Plan Layer recovered  
실행 결과: 3/3 `abstained=false`, `semantic_plan_incomplete` 없음,
`projection_field_unavailable` 없음  
최종 표에는 전략광종의 price/date/unit 값이 생성됨. 가격 기준 identity의 최종
표시 여부는 별도 renderer/output contract 관찰 대상으로 남김.

판정: `PLAN_LAYER_RECOVERED` 3/3  
`STABLE_RECOVERED`: 0/3 (최종 criterion 표시까지 포함한 strict content는 이번
iteration의 수정 범위를 넘어 별도 확인 필요)

## REG05 trace / 결과

질문: `니켈 LME 재고량 알려줘`

### Before

`inventory.latest` capability가 registry에는 있었지만 `latest`가
`InventoryObservation` output contract로 연결되지 않아 AAST/plan generation이
`semantic_plan_incomplete`로 종료했다.

### After

```text
Semantic Requirement
  domain=inventory, metric=latest, mineral=니켈
→ registry: inventory.latest
→ InventoryObservation output contract
→ AAST: entity → retrieve(inventory/latest) → project(value, unit, date)
→ Coverage Validator: valid
→ capability: inventory.latest
→ TypedResult: value/date/unit
→ projection: success
```

fresh session 결과: 3/3 Plan Layer recovered  
실행 결과: 3/3 `abstained=false`, `semantic_plan_incomplete` 없음,
`projection_field_unavailable` 없음  
대표 결과: `value=272380`, `unit=WT002`, `date=20260908`  

판정: `PLAN_LAYER_RECOVERED` 3/3  
`STABLE_RECOVERED`: 3/3 content 기준으로 확인

## 유사 capability probe

| Probe | 결과 |
|---|---|
| `price.series`: 최근 1년간 니켈 가격 추이 | 실행 성공, abstain 없음 |
| `inventory.series`: 최근 1년간 니켈 재고 추이 | 실행 성공, abstain 없음 |
| `resource.rank`: 리튬 매장량 상위 5개 국가 | 실행 성공, abstain 없음 |
| Hybrid GM02 | 실행 성공, abstain 없음 |
| trade country rank probe | 기존 projection field `import_value` 실패 관찰; 이번 계약 수정 범위 밖 |
| document title probe | 기존 `title` projection 실패 관찰; 이번 계약 수정 범위 밖 |
| navigation probe | Query Gate 비활성 검증 환경에서 `semantic_plan_incomplete`; 이번 수정 범위 밖 |

위 probe 실패는 MP07/REG05 수정으로 회복된 sentinel regression으로 집계하지
않았으며, 별도 ROI 후보로 남긴다.

## Regression

- 관련 unit/contract tests: **95 passed**
- rag_core 전체: **1549 passed / 0 failed**, 695 subtests, 1 warning
- rag_chat 전체: **155 passed / 1 known legacy contract failure**, 15 subtests
- 기존 golden rag_core `1544/1544`는 신규 테스트 5건이 추가되어 총 1549 passed로
  증가했으며 실패는 없음
- 대상 sentinel(MP07/REG05, price series, inventory series, resource rank, GM02):
  regression 0
- QA57 full replay: 실행하지 않음
- 18002: 변경하지 않음

## 다음 blocker / ROI

1. MP07 최종 renderer 표에 price criterion identity를 안정적으로 표시하는
   projection/output contract 확인
2. trade country rank의 `import_value` canonical projection contract
3. document title field canonical projection contract

MP07/REG05에 대한 Plan Generation 공통 blocker는 제거되었다. 다음 단계는 이
artifact의 결과를 기준으로 Capability/Projection 또는 renderer 경계를 별도로
처리한다.
