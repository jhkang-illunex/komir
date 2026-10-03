# Capability Low-Cost Cluster Audit — 2026-10-03

## 범위와 기준

- 검증 환경: 18012, `capability-boundary-r4-20261003`
- 운영 18002: 미변경
- 공식 Strict baseline: `17/57`
- 작업 전 잠정 Strict 후보: `21/57`
- QA57 전체 replay: 수행하지 않음
- 대상: DOC02/ADD38, IX02/ADD16, CN08/REG02

각 항목은 최신 18012 trace의 최초 causal boundary를 기준으로 판정했다.
`HTTP 200`이나 non-abstain만으로 CONTENT_PASS를 계산하지 않았다.

## Cluster 결과

| Cluster | QA | 최초 causal boundary | 결과 |
|---|---|---|---|
| Output / Projection | DOC02 | `Raw document result → Projection` | `UNRECOVERED`: 결과 행에 `게시월`, `광종 목록`, `문서`, `문서 요약`만 있고 `title`이 없음. projection 완화 대상 아님. |
| Output / Projection | ADD38 | `Source retrieval → TypedResult` | `UNRECOVERED`: `price.series`가 `no_data`/빈 결과를 반환하고 projection의 `mineral`도 채울 값이 없음. source/data 문제. |
| Join / Alignment | IX02 | `TypedResult → Projection` | 공통 alias 수정 후 `STABLE_RECOVERED` 후보. indicator TypedResult는 `date/value`를 보유하고 AST projection은 semantic `series`를 요청했다. `series → value` canonical resolution을 추가했다. |
| Join / Alignment | ADD16 | `Typed operands → comparison alignment` | `UNRECOVERED`: world reserves가 여러 국가 행인 반면 Chile는 필터된 행이다. scalar denominator/aggregate가 없어 positional 또는 임의 join으로 고칠 수 없음. |
| Calculation | CN08 | `Typed operand → calculation contract` | `UNRECOVERED`: indicator branch는 성공하지만 `period_change`가 generic calculate contract에 없음. 문서 branch도 evidence validation failure. 이번 단계에서 신규 calculation/business rule을 추가하지 않음. |
| Calculation | REG02 | `AAST aggregate arguments → aggregate contract` | `UNRECOVERED`: `last(value)`에 `order_by`가 없어 `aggregate_order_required`. 단순 runtime 완화가 아니라 plan contract 문제이며 CN08과 공통 최초 원인이 아님. |

## 적용한 공통 수정

`indicator.series`의 canonical output은 `value`이다. AST의 semantic projection vocabulary인
`series`가 물리 컬럼으로 오인되지 않도록 기존 `_resolve_row_field(..., strict=True)`의
공통 alias contract에 다음을 추가했다.

```text
series → {series, value}
```

정확한 `series` 컬럼이 있으면 그것을 우선하고, 없고 canonical `value`가 하나만 있으면
`value`를 사용한다. 임의 숫자 컬럼 선택은 하지 않는다.

### IX02 live probe

- fresh session 1: 비교표 생성, abstain 없음
- fresh session 2: 비교표 생성, abstain 없음
- fresh session 3: 비교표 생성, abstain 없음
- 기존 failure `projection_field_unavailable:series`: 재현되지 않음

따라서 IX02는 `AAST_FAILURE`가 아니라 해당 capability projection 경계에서
`CAPABILITY_LAYER_RECOVERED`/`STABLE_RECOVERED` 후보로 기록한다. strict content의 최종
판정은 full replay oracle에서 확정한다.

## 보호 sentinel

동일 18012 이미지에서 fresh session으로 확인했다.

| Sentinel | 결과 |
|---|---|
| REG05 | 실행 정상, inventory series 표 생성 |
| ADD01 | 실행 정상, lithium criterion/unit 결과 생성 |
| ADD49 | 실행 정상, copper price 결과 생성 |
| GM02 | 실행 정상, 국가 결과 생성 |
| ADD27 | 실행 정상, price series 표 생성 |
| MP07 | 3/3 실행은 완료되나 가격 없는 광종 행이 포함됨. strict content sentinel 회귀/데이터 품질 blocker로 유지 |

MP07 문제는 `indicator.series` alias 수정과 무관한 `price.overview` 결과 품질 문제로
분리했다. 이번 iteration에서 수정하지 않았다.

## 테스트

- indicator/series 및 관련 targeted tests: `185 passed`
- `PYTHONPATH=.:inhouse pytest -q inhouse/rag_core/tests`: `1553 passed / 0 failed`, 1 warning, 695 subtests
- `PYTHONPATH=.:inhouse pytest -q inhouse/rag_chat/tests`: `155 passed / 1 known legacy contract failure`
- known failure: `test_disconnect_stops_real_ast_retry_before_blocking_invocation_returns[legacy_control-False]`
- 새 rag_core regression: `0`

## 회복 집계

- 신규 `STABLE_RECOVERED`: IX02 1건 후보
- `CAPABILITY_LAYER_RECOVERED`: IX02 1건
- `FLAKY`: 없음(IX02 3/3 동일한 실행 성공)
- `UNRECOVERED`: DOC02, ADD38, ADD16, CN08, REG02
- 잠정 Strict 후보: `21/57` 유지. IX02는 full replay 전까지 provisional candidate로만 기록하며 공식 수치에는 더하지 않음.

## Complexity Delta

- Files changed: `inhouse/rag_core/ragkit/live_multihop.py`, 관련 unit test 1개
- New classes: 0
- New public contracts: 0
- New registry entries: 0
- New special-case branches: 0
- New central-dispatch branches: 0
- Removed branches: 0
- Duplicated contract sources added: 0
- Duplicated contract sources removed: 0
- Largest modified method LOC: 기존 `_resolve_row_field` 내 alias entry만 추가
- Largest modified class LOC: 변경 없음
- Largest modified module LOC: 기존 모듈, 구조적 증가 없음
- Responsibility growth detected: `false`
- Verdict: `COMPLEXITY_PASS`

기존 `_resolve_row_field`에 alias가 누적되는 legacy mapping duplication은 기존
`REFACTOR_CANDIDATE`로 유지한다. 이번 수정으로 새 dispatcher나 별도 mapping source를
추가하지 않았다.

## Contract Delta

- New contracts: 없음
- Modified contracts: `indicator.series` semantic projection alias resolution
- Removed contracts: 없음
- Canonical source of truth: existing canonical row-field resolver + existing `indicator.series` TypedResult (`value`)
- Consumers: AAST project execution, compare input projection, indicator series runtime
- Duplicated mappings remaining: legacy `_METRIC_FIELDS`/field-alias layers remain; 이번 iteration에서는 구조 refactor하지 않음

## 다음 작업

1. MP07: price overview에서 실제 가격이 없는 행을 composite output에 섞는 source/partial-result 품질 contract 감사
2. CN08: `indicator.series`의 명시적 `period_change` capability/calculation contract와 document evidence를 분리 분석
3. ADD16: world population을 scalar denominator로 만드는 semantic/AAST composition contract 분석
4. DOC02/ADD38: source/document output 자체의 부족 여부 확인

이번 iteration의 저비용 deterministic projection cluster는 IX02에서 회복되었으며, 추가
cluster는 최초 causal boundary가 달라 안전하게 공통화할 수 없어 중단했다. 18002에는
배포하지 않았다.
