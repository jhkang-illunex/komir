# CN08 Unit Provenance Audit — 2026-10-03

## 결론

CN08의 최초 causal failure는 `SOURCE_UNIT_ABSENT`이다.

원천 `public.KO_MNRL_SNTHS_INDX`에 unit 컬럼이 없고, 실제 조회 행에도 unit 값이
없다. 따라서 Source Adapter가 기존 unit을 누락한 것이 아니며, TypedResult와
Projection에서 뒤늦게 제거된 것도 아니다. `calculate_series(endpoint_change)`가
입력 series의 단위 일관성을 확인하는 단계에서 `unit_unavailable`로 fail-closed
한다.

이번 audit에서는 임의로 `index`, `point` 등의 unit을 생성하지 않았고 코드를 수정하지
않았다. CN08은 현재 `BLOCKED_UNIT_CONTRACT`로 유지한다.

## 검증 환경

- 검증 이미지: `komir-rag-chat:cn08-period-change-r3`
- 이미지 digest: `sha256:1684d72c47730f556549b7519984b7a0b7ad8a0d3cea9ce9b333218be2401bed`
- source SHA: `fa423722caeb86bfb83e6561e3b355b20da2ef38`
- 검증 container: `komir-rag-chat-cn08-r3` (`16763215c11...`)
- 운영 18002: 변경 없음

## Unit provenance trace

### 1. Raw Source

Source schema와 실제 DB를 직접 확인했다.

```text
table: public.KO_MNRL_SNTHS_INDX
columns:
  indx_se_cd  varchar
  crtr_ymd    varchar
  indx        numeric
  prvdy_cprs  numeric
  uplmt       numeric
  lwlmt       numeric
  center      numeric
```

최근 행 예시는 다음과 같다.

```text
('HI001', '20260905', 3651.45, 23.31, NULL, NULL, NULL)
('HI002', '20260905', 3011.24,  9.57, NULL, NULL, NULL)
('HI003', '20260905', 2925.65, 14.47, NULL, NULL, NULL)
```

총 행 수는 `12,105`이며, schema와 행 모두 `unit`/단위 필드를 제공하지 않는다.
저장 schema registry도 동일하게 `INDX_SE_CD, CRTR_YMD, INDX, PRVDY_CPRS,
UPLMT, LWLMT, CENTER`만 선언한다.

### 2. Source Adapter / Capability

`indicator.series` adapter는 다음 canonicalization을 수행한다.

```text
indx / series / center → value
crtr_ymd               → date
indx_se_cd             → indicator
```

unit 정규화는 수행할 값이 있을 때만 동작하며, 이 source에는 unit 값이 없으므로
`unit=None`이 보존된다. Physical source field가 상위 계층으로 누출되어 unit으로
오인된 흔적은 확인되지 않았다.

### 3. IndicatorSeriesInput

CN08 입력의 의미는 다음과 같이 확정된다.

```text
indicator: composite_index
operation: period_change
period: requested range/trailing period
value field: value
date field: date
```

`IndicatorSeriesInput`은 source unit을 임의로 선언하는 입력이 아니다. 따라서 여기서
unit을 보정하지 않았다. adapter 단계에서 이미 `unit=None`인 상태가 정상적으로
전달된다.

### 4. calculate_series Input

기존 공용 analytical primitive가 사용된다.

```text
calculation: endpoint_change
field: value
time_field: date
output_field: change_pct
endpoint_policy: inside
```

`endpoint_change`의 의미는 기존 구현상 다음과 같다.

```text
(end - start) / abs(start) * 100
```

즉 CN08에서 계산하려는 결과는 원 지수의 물리 단위를 그대로 표시하는 값이
아니라 percentage change이며, 기존 primitive의 출력 unit은 `%`로 정의되어 있다.

### 5. Calculated TypedResult

계산은 결과 TypedResult를 생성하기 전에 중단된다. `calculate_series`의 unit
검증에서 입력 행들의 unit과 source unit을 확인하지만 모두 비어 있어 다음 실패가
발생한다.

```text
failure_reason: unit_unavailable
first failing boundary: calculate_series input unit validation
```

따라서 calculated output의 `%` unit이 손실된 것이 아니다. 계산 결과 자체가 아직
생성되지 않았다.

### 6. TypedResult / Projection

`_typed_from_retrieval` 단계의 unit은 `None`이다. projection에는 계산된
`change_pct` TypedResult가 도달하지 않으므로 projection이 unit을 제거한 증거는
없다. CN08의 `unit_unavailable`은 Projection failure가 아니다.

## Failure classification

| 구분 | 판정 | 근거 |
|---|---|---|
| `SOURCE_UNIT_ABSENT` | primary | 원천 schema와 실제 행에 unit 필드/값이 없음 |
| `SOURCE_ADAPTER_UNIT_LOSS` | 아님 | adapter가 존재하는 unit을 제거한 증거 없음 |
| `TYPED_INPUT_UNIT_LOSS` | 아님 | 입력 시점부터 unit이 source에 없음 |
| `CALCULATION_OUTPUT_UNIT_CONTRACT_MISSING` | secondary contract tension | 공용 primitive가 입력 unit 존재를 요구하지만, `endpoint_change` 출력 자체는 `%`로 결정됨 |
| `PROJECTION_UNIT_LOSS` | 아님 | calculation이 projection 이전에 중단됨 |

최종 상태는 `BLOCKED_UNIT_CONTRACT`이다. 현재 근거만으로 source 지수의 물리
단위를 임의 생성하여 계산을 통과시키는 것은 허용하지 않는다.

## 동일 calculation primitive 영향 조사

`calculate_series`의 공용 계약은 `endpoint_change`, `periodic_return`, `base100`,
`threshold_first`, `correlation`에 공통으로 사용된다.

- `endpoint_change`, `periodic_return`: 출력 unit은 `%`지만 입력 series의 unit
  일관성을 확인한다.
- `base100`: 출력 unit은 `index`이며 입력 source unit 확인 후 계산한다.
- `threshold_first`: source unit을 결과에 전달해야 하므로 입력 unit이 필요하다.
- `correlation`: 각 operand의 unit field 계약을 별도로 요구한다.
- `difference`, `growth/YoY`, `ratio/share/percentage`는 별도 runtime 경로와
  canonical field 계약을 사용하므로 CN08의 `unit_unavailable`과 동일하다고
  추정하지 않았다.

현재 CN08에서 재현된 직접 영향은 `indicator.series → endpoint_change` 경로다.
동일 source의 다른 operation이 같은 문제를 갖는지는 해당 operation의 입력/출력
의미를 별도로 확인해야 하며, 이번 audit에서 unit을 완화하지 않았다.

## 현재 CN08 검증 결과

현재 r3 이미지에서 CN08을 fresh session으로 3회 확인했다.

| 실행 | AAST/Capability | Calculation | Evidence branch | 최종 상태 |
|---:|---|---|---|---|
| 1 | 진입 | `unit_unavailable` | success | PARTIAL |
| 2 | 진입 | `unit_unavailable` | success | PARTIAL |
| 3 | 진입 | `unit_unavailable` | success | PARTIAL |

기존 `unsupported_calculation_contract`와 `invalid_series_date`는 더 이상 최초
오류가 아니다. Evidence branch는 3/3 성공했지만, calculation branch가 실패하므로
CN08은 `STABLE_RECOVERED`가 아니다.

보호 sentinel은 동일 r3 이미지에서 다음 결과를 확인했다.

```text
REG02, REG05, MP07, ADD01, ADD49, GM02, ADD27: shadow execution success
```

추가 회귀:

- `rag_core`: `1557 passed / 0 failed`
- `rag_chat`: `155 passed / 1 known legacy contract failure`
- 18002: 변경 없음

## Repair decision

수정하지 않았다.

현재 가능한 선택지는 다음 두 가지인데, 둘 다 이번 단계에서 근거 없이 적용할 수
없다.

1. source schema에 실제 unit metadata를 추가한다.
2. 공용 calculation contract가 단일 series의 percentage change에 대해 source unit
   없이도 계산 가능한지 명시적으로 재정의한다.

1은 source/data contract 변경이며, 2는 여러 calculation 경로에 영향을 주는 공용
계산 계약 변경이다. 현재 원천 지수의 physical unit이 무엇인지 확정하지 않은 채
`index` 또는 임의 단위를 주입하는 것은 하지 않았다.

## Architecture & Complexity Guard

### Complexity Delta

이번 unit provenance audit에서 production code는 변경하지 않았다.

```text
Files changed: audit artifact 1개
New classes: 0
New public contracts: 0
New registry entries: 0
New special-case branches: 0
New central-dispatch branches: 0
Removed branches: 0
Duplicated contract sources added: 0
Duplicated contract sources removed: 0
Largest modified method LOC: 변경 없음
Largest modified class LOC: 변경 없음
Largest modified module LOC: 변경 없음
Responsibility growth detected: false
Verdict: COMPLEXITY_PASS
```

기존 `chatbot.py`의 composite-index 표현 경로와 generic `calculate_series`는 이미
각자 존재하는 병렬 경로다. 이번 audit에서 새 중복 mapping을 추가하지 않았으며,
향후 `REFACTOR_CANDIDATE`로 검토할 수 있지만 이번 범위에서 구조 변경하지 않는다.

### Contract Delta

```text
New contracts: 없음
Modified contracts: 없음
Removed contracts: 없음
Canonical source of truth:
  - KO_MNRL_SNTHS_INDX source schema/catalog
  - IndicatorSeriesInput contract
  - calculate_series analytical contract
Consumers:
  - indicator.series adapter
  - _typed_from_retrieval
  - calculate_series
  - downstream projection (CN08에서는 도달하지 않음)
Duplicated mappings remaining:
  - legacy composite-index presentation path와 generic calculation path의 기존 병렬성
```

## 다음 단계

CN08은 source unit이 확정되거나 공용 `endpoint_change` unit contract가 명시적으로
개정될 때까지 `BLOCKED_UNIT_CONTRACT`로 유지한다. 다음 후보인 PF02는 별도
iteration에서 처리한다.
