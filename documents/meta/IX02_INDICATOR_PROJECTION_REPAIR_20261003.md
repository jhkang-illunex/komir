# IX02 Indicator Projection Contract Audit — 2026-10-03

## 기준

- authoritative Strict baseline: `21/57`
- rag_core golden: `1557/1557`
- 대상: IX02만
- 운영 18002: 변경 없음
- QA57 full replay: 수행하지 않음

## Contract 확인

기존 코드와 테스트에서 `indicator.series`의 canonical numeric output은 `value`로
확정되어 있었다.

- `IndicatorSeriesRow`/TypedResult의 numeric field: `value`
- source aliases: `series`, `indx`, `center` → canonical `value`
- shared resolver: `_resolve_row_field(..., "series", strict=True)`가 source `value`를
  반환
- `indicator.series` row canonicalization: `_canonical_indicator_rows()`가 물리
  `indx(지수)`를 `value`로 변환
- `series`는 별도 physical/canonical numeric column이 아니라 AAST projection vocabulary

따라서 새 canonical field나 IX02 전용 mapping을 추가하지 않았다. 기존 공통 resolver와
TypedResult contract가 authoritative source다.

## 적용/검증

소스 수정은 없었다. 18012 프로세스만 재시작해 현재 소스의 공통 contract를 재로딩했다.

관련 unit tests:

```text
5 passed, 48 deselected
```

전체 rag_core:

```text
1557 passed, 1 warning, 695 subtests passed
```

IX02 fresh session 3회:

| Run | AAST/Capability | Projection alias | 최종 결과 | 판정 |
|---:|---|---|---|---|
| 1 | 정상 실행 | `series → value` 경계 통과 | indicator right 값이 최종 compare 표에 채워지지 않음 | `LAYER_RECOVERED` |
| 2 | 정상 실행 | 동일 | 동일 | `LAYER_RECOVERED` |
| 3 | 정상 실행 | 동일 | 동일 | `LAYER_RECOVERED` |

실제 raw indicator TypedResult에는 `date`, `value`, `indicator`, `indx(지수)`가
존재했다. 이후 최종 표는 price left 행만 채워지고 `right.date/right.series`가 비었다.
따라서 projection alias 자체는 canonical boundary에서 해결됐지만, 다음 compare 단계의
date alignment/intersection이 남은 blocker다. 이는 이번 범위에서 수정하지 않았다.

`STABLE_RECOVERED` 조건인 strict content 3/3은 충족하지 못했다.

## Sentinel

기존 sentinel `MP07, REG02, REG05, ADD01, ADD49`도 live probe를 수행했다. 모두 SSE
종료와 표 응답은 생성됐으나 runner의 기대 표지 검사에서는 `PARTIAL`로 표시됐다.
이번 iteration에는 sentinel의 content oracle을 재평가하거나 수정하지 않았으므로 신규
strict regression으로 집계하지 않는다. rag_core에는 regression이 없었다.

## 결과

- IX02: `LAYER_RECOVERED`
- IX02: `STABLE_RECOVERED` 아님
- provisional Strict: `21/57` 유지
- 남은 blocker: date-based compare alignment / right series materialization
- source/data blocker: 아님

## Complexity Delta

- Files changed: artifact 1개; production source 0개
- New classes: 0
- New public contracts: 0
- New registry entries: 0
- New special-case branches: 0
- New central-dispatch branches: 0
- Removed branches: 0
- Duplicated contract sources added/removed: 0/0
- Responsibility growth: 없음
- Verdict: `COMPLEXITY_PASS`

## Contract Delta

- New contracts: 없음
- Modified contracts: 없음
- Canonical source of truth: existing Indicator TypedResult + shared canonical field resolver
- Consumers: indicator adapter, TypedResult canonicalization, generic projection, relation runtime
- Duplicated mappings remaining: 기존 legacy alias mapping debt는 유지되며 이번 iteration에서
  추가되지 않음

## 종료

이번 iteration에서는 IX02의 `series` 의미가 `value`의 projection alias라는 점을
확인했고, 기존 공통 계약이 이미 이를 표현하고 있어 코드 수정은 하지 않았다. 남은
date alignment 문제는 별도 Join/Composition 작업으로 분리한다.
