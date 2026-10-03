# ADD16 / ADD25 Reduction·Dependency Audit — 2026-10-03

## 결론

최신 18012 r5 trace 기준으로 ADD16과 ADD25는 같은 `multi-row → scalar` 공통
contract가 아니다. 이번 단계에서는 코드를 수정하지 않았다.

| QA | 최초 causal boundary | 판정 | 이유 |
|---|---|---|---|
| ADD16 | `multi-row resource TypedResult → ratio operands` | `BLOCKED` / `REDUCTION_SEMANTICS_AMBIGUOUS` | world population을 `sum`으로 축약해야 하는 것은 명확하지만, AAST에 aggregate가 없고 ratio인지 percentage인지 typed output contract가 완결되지 않음 |
| ADD25 | `independent price.series → date join/dependency` | `FLAKY` | reduction 대상이 아니며 3회 중 1회 dependency 실패, 2회 graph 실행 성공 |

따라서 두 QA를 하나의 공통 reduction 수정으로 묶지 않았다.

## 검증 환경

- 18012 image: `sha256:a9116155ea385914dbfb506cd03574a4c54c6b8a5b0a1052f4b9eadf375870f9`
- 18012 container: `komir-rag-chat-recoverability-r5`
- 18002: 변경 없음
- QA57 full replay: 실행하지 않음

## ADD16

질문: `세계 리튬 매장량 중 칠레 비중은?`

### Graph

반복 trace에서 다음 두 형태가 관찰됐다.

```text
resource.rank(metric=reserves_volume, mineral=리튬, scope=WORLD)
resource.rank(metric=reserves_volume, mineral=리튬)
  → filter(country=칠레)
  → project(reserves_volume)
  → compare(operation=ratio)
```

또는:

```text
world reserves retrieve
Chile reserves retrieve → filter(country=칠레)
→ project(reserves_volume) 양쪽
→ calculate(calculation=division)
```

### Upstream 상태

- world resource branch: `resource.rank`, metric `reserves`, resource population `all`
- Chile branch: `resource.rank`, metric `reserves`, country filter `칠레`
- 두 branch 모두 source 접근/TypedResult 생성까지 성공
- world branch는 국가별 다중 행
- Chile branch는 country filter 후 scalar 후보가 될 수 있는 결과
- unit/metric은 양쪽 모두 reserves 계열로 호환 가능

### 최초 causal failure

1. world multi-row 결과가 `aggregate(sum)`로 축약되지 않음
2. relation/calculate가 raw multi-row를 ratio operand로 받음
3. 결과적으로:
   - `comparison_alignment_required`
   - `calculation_field_unavailable`
   가 발생

### 기존 primitive 재사용성

기존 `aggregate(sum)` 자체는 존재하고, 입력은 `FactSet → ScalarMetric`으로 축약할
수 있다. 따라서 연산 primitive가 완전히 없는 것은 아니다.

그러나 현재 AAST에는 다음 정보가 모두 확정되어 있지 않다.

- denominator reduction이 반드시 `SUM`인지
- ratio 결과를 `0.2486`처럼 비율로 낼지 `24.86%`처럼 percentage로 낼지
- 결과 output field/unit이 무엇인지
- world population의 completeness가 계산에 충분한지

질문의 `비중`은 percentage를 강하게 시사하지만, 이번 단계에서 원문을 다시 해석해
AST에 business rule을 생성하는 것은 허용 범위를 넘는다. 따라서 기존 aggregate를
자동 삽입하는 것은 아직 deterministic bounded repair가 아니다.

### ADD16 판정

`CAPABILITY_LAYER_RECOVERED`가 아니다. 두 upstream capability는 성공했으므로
Capability 자체보다 `PLAN_GAP / COMPOSITION_GAP`에 가깝다.

필요한 명시 contract는 다음과 같다.

```text
Population<resource.reserves, scope=WORLD>
→ Aggregate(sum, field=reserves_volume)
→ ScalarMetric<resource.reserves, scope=WORLD>
→ Ratio/Percentage(numerator=Chile, denominator=WorldTotal)
```

이 contract가 typed requirement/registry에 명시되기 전에는 수정하지 않는다.

### ADD16 fresh ×3

| Run | Session | Final reason | 결과 |
|---:|---|---|---|
| 1 | `ce081ade-21be-472d-b719-5a6fc195fdff` | `comparison_alignment_required` | 실패 |
| 2 | `7803b088-9b99-46f7-bf41-d180238f3ba6` | `comparison_alignment_required` | 실패 |
| 3 | `fa3bf72e-931a-4415-82e8-8bf8bdfe7042` | `calculation_field_unavailable` | 실패 |

AAST는 3회 모두 world/Chile branch를 생성했으나 scalar reduction이 없었다.

## ADD25

질문: `구리, 니켈, 코발트 최근 1년 가격 추이 비교해줘`

### Graph

정상 실행 trace에서 다음 graph가 생성됐다.

```text
price.series(구리, trailing_months=12)
price.series(니켈, trailing_months=12)
price.series(코발트, trailing_months=12)
→ join/compare on date
→ side_by_side 또는 multi-join output
```

일부 시도는 `compare_copper_nickel → join(compare, cobalt)` 구조였고, 일부는
각 branch projection 후 `join(date)` 구조였다.

### Upstream 상태

- 세 price.series capability call은 정상 생성됨
- mineral identity와 12개월 period는 보존됨
- reduction은 필요하지 않음
- 핵심 연산은 `date` 기준 multi-series join/alignment

### ADD25 fresh ×3

| Run | Session | Final reason | 결과 |
|---:|---|---|---|
| 1 | `93922a92-06a3-4fda-bd4f-ad8f9c2101f2` | `dependency_unavailable` | 실패 |
| 2 | `b577c919-5a97-432f-a735-ffb8e9faf3d6` | 없음, HTTP 200 non-abstain | 실행 성공 |
| 3 | `5712b3ae-d519-4a38-83c6-dc8756656f05` | 없음, HTTP 200 non-abstain | 실행 성공 |

정상 실행 trace는 36행×13열 table과 chart를 반환했다. 실패 1회는 동일 계열
dependency/join 경계의 반복 변동으로 기록하며, 이번 reduction 수정 대상이 아니다.

### ADD25 판정

`FLAKY`.

기존 primitive인 `price.series`와 `join(date)`는 이미 존재한다. 하지만 현재
실패는 scalar reduction 부재가 아니라 capability dependency 결과의 일관성/전달
문제다. ADD16과 공통 수정으로 묶으면 책임과 contract가 섞인다.

## 공통성 판정

| 비교 항목 | ADD16 | ADD25 | 공통 여부 |
|---|---|---|---|
| Upstream | resource reserves rows | price time series | 없음 |
| Reduction | world rows → scalar 필요 | 불필요 | 없음 |
| Operator | ratio/division | side_by_side/join | 없음 |
| Key | population scope | date | 없음 |
| 최초 failure | scalar operand 부재 | dependency/join 변동 | 없음 |
| 재사용 primitive | aggregate + ratio/percentage | series + date join | 별도 |

결론적으로 현재 단계에서 공통 contract 하나를 수정하는 것은 과적합 또는 책임
혼합 위험이 있다.

## Recovery 상태

- ADD16: `BLOCKED` (`REDUCTION_SEMANTICS_AMBIGUOUS` / plan composition gap)
- ADD25: `FLAKY` (2/3 execution success, strict content 3/3 미확정)
- 신규 `STABLE_RECOVERED`: 0
- provisional strict: `22/57` 유지
- REG02/기존 sentinel: 이번 단계에서는 재실행하지 않음

## 신규 primitive 후보

즉시 구현하지 않는다.

| 후보 | 입력 | 출력 | 필요한 명세 | 이유 |
|---|---|---|---|---|
| typed population total | `FactSet<metric, scope=WORLD>` | `ScalarMetric<total>` | aggregation=`sum`, population completeness, unit | ADD16 denominator에 필요. 단순 `reduce_scalar`로 일반화하면 잘못된 합계 위험 |
| typed percentage ratio | `ScalarMetric<numerator> + ScalarMetric<denominator>` | `ScalarMetric<percentage>` | numerator/denominator identity, zero policy, output unit `%` | ADD16의 `비중` 의미를 명시해야 함 |
| multi-series date join | `TimeSeries[]` | aligned `TimeSeries/FactSet` | inner/full policy, missing date policy | ADD25에 필요할 수 있으나 기존 join이 이미 존재하고 현재 문제는 반복 dependency 변동 |

신규 generic execution framework나 중앙 dispatcher branch는 만들지 않는다.

## Complexity Delta

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
Largest modified method LOC: N/A
Largest modified class LOC: N/A
Largest modified module LOC: N/A
Responsibility growth detected: 없음
Verdict: COMPLEXITY_PASS
```

## Contract Delta

```text
New contracts: 없음
Modified contracts: 없음
Canonical source of truth: 기존 aggregate, ratio/share, price.series, join contracts
Consumers: audit only
Duplicated mappings remaining: 기존 alias/renderer mapping debt; REFACTOR_CANDIDATE 유지
```

## Quality / Regression

이번 iteration에는 코드 수정이 없어 unit/regression suite를 재실행하지 않았다.
직전 golden은 다음과 같다.

- `rag_core`: 1554 passed / 0 failed
- `rag_chat`: 155 passed / 1 known legacy failure
- 18002: 변경 없음

## 다음 우선순위

1. ADD16: typed requirement 또는 capability spec에 `WORLD total → percentage`의
   aggregation/output semantics가 명시된 뒤에만 공통 composition repair 검토
2. ADD25: 기존 date join을 바꾸기 전에 3회 반복 dependency 변동 원인 감사
3. CN08: 이번 iteration 범위 밖이며 자동 진행하지 않음
4. PF02: 이번 iteration 범위 밖이며 자동 진행하지 않음

이번 단계는 ADD16/ADD25에서 안전한 공통 수정 근거가 없으므로 여기서 종료한다.
