# GM14 trade.country_rank / CountryShare legacy typed audit

- 검증 환경: 18012 전용
- 운영 18002: 변경 없음
- 기준 baseline: Strict 21/57, rag_core 1557/1557
- 코드 수정: 기존 `trade.country_rank` Registry metadata와 contract test만 보완
- QA57 Full Replay: 미실행

## 결론

기존 `trade.country_rank`는 국가별 수입 비중을 이미 반환하고 있었다. Raw result의 `share_pct`/국가별 수입금액을 capability boundary에서 canonical field로 보존하고, `_typed_from_retrieval`은 `ValueType.COUNTRY_SHARE`를 사용한다.

따라서 새 Capability가 필요한 상태가 아니라, Registry에 기존 CountryShare output contract가 선언되지 않은 **`LEGACY_TYPED_CONTRACT_MISMATCH`**였다.

다만 GM14의 현재 semantic requirement는 여전히 `trade.concentration`으로 생성된다. `trade.concentration`은 `ConcentrationMetric`만 반환하므로 GM14는 CountryShare branch에 도달하지 못한다.

GM14 최종 상태: **`PLAN/COMPOSITION_GAP` 유지**

## `trade.country_rank` 실제 output

### Raw Result

기존 trade ranking adapter/test contract에서 다음 의미가 확인됐다.

```text
country
import_amount / export_amount
share_pct 또는 annotated share_pct
period
unit
```

### Canonical TypedResult

`_typed_from_retrieval` 및 projection contract는 다음 semantic output을 제공한다.

```text
ValueType.COUNTRY_SHARE
country
import_amount 또는 export_amount
share_percentage / import_share alias
period
unit
provenance
```

`share_pct`와 `share_pct(수입금액 비중...)`가 동시에 있을 때는 canonical exact field를 우선한다. positional row나 임의 numeric field 선택은 사용하지 않는다.

### CountryShare contract

Registry에 기존 실행 capability를 다음처럼 선언했다.

```text
action_id       = trade.country_rank
output_type     = CountryShare
surface metrics = country_rank | country_share | import_share
canonical metric= country_share
canonical fields= country, share_percentage, import_amount/export_amount,
                  period, unit, provenance
compat aliases  = import_share, country_share
```

`value`도 기존 downstream compatibility를 위해 declared output field로 유지했다. 새 executor나 capability는 추가하지 않았다.

## GM14 trace

현재 fresh 실행 3회 모두 동일했다.

```text
Semantic Requirement:
  price/current + trade/concentration(flow=import, scope=KR)

AAST candidate:
  retrieve_concentration
  project_concentration(fields=[mineral, import_share])
  join(price, concentration, key=mineral)
  final_projection(right.import_share)

first failure:
  project_concentration output validation
```

오류:

```text
project_concentration requires ['import_share']
available=['concentration', 'entity', 'evidence', 'mineral', 'source', '광종']
```

즉 기존 CountryShare contract가 존재해도 현재 GM14 graph는 `trade.country_rank`를 호출하지 않는다. `concentration`을 `import_share` alias로 바꾸면 HHI/집중도와 국가별 비중 의미가 혼합되므로 수정하지 않았다.

## 판정

| 항목 | 판정 |
|---|---|
| 기존 country-share 실행 기능 | 존재 |
| TypedResult CountryShare 표현 | 존재 |
| Registry 선언 | 기존에는 부족, 이번에 승격 |
| 새 Capability 필요 | 아니오 |
| GM14가 country_rank를 선택하는가 | 아니오 |
| GM14 recovery | 미회복; `PLAN/COMPOSITION_GAP` |
| 임의 alias/numeric mapping | 적용하지 않음 |

`trade.concentration → ConcentrationMetric`과 `trade.country_rank → CountryShare`를 함께 조합하는 graph는 타입상 표현 가능하지만, GM14의 현재 requirement가 concentration으로 잘못 확정된 상태라 deterministic composition repair가 추가로 필요하다. 이는 CountryShare capability 부재가 아니라 semantic requirement/capability selection 경계의 후속 과제다.

## 검증

### Tests

- 관련 semantic/country-share/live multihop tests: **66 passed**
- rag_core 전체: **1558 passed, 0 failed**, 1 warning, 695 subtests

### GM14 fresh ×3

| Run | Result | First failure |
|---:|---|---|
| 1 | FAIL | `trade.concentration` projection에서 `import_share` 미생성 |
| 2 | FAIL | 동일 |
| 3 | FAIL | 동일 |

따라서 `STABLE_RECOVERED`나 `LAYER_RECOVERED`로 승격하지 않는다.

## 유사 Legacy → Typed Contract migration 후보

| 후보 | 관찰 | 우선순위 |
|---|---|---:|
| `trade.concentration` | action은 존재하지만 semantic output type/allowed fields가 Registry에 미선언 | 높음 |
| `trade.country_rank` | 이번에 CountryShare contract 승격 완료 | 완료 |
| `trade.monthly` | trade series output type/fields가 중앙 Registry에서 명시적으로 확인 필요 | 중간 |
| `trade.indicator` | metric별 result type/field contract가 분산되어 있는지 추가 audit 필요 | 중간 |
| `resource.rank` | production/reserves별 output fields가 runtime과 Registry에 중복될 가능성 | 중간 |

## Complexity Delta

| 항목 | 결과 |
|---|---|
| Files changed | `semantic_capabilities.py`, 관련 contract test, 본 artifact |
| New classes | 0 |
| New public contracts | 새 capability 아님; 기존 `trade.country_rank` metadata 승격 1건 |
| New registry entries | action entry 1건, 기존 action의 metadata |
| New special-case branches | 0 |
| New central-dispatch branches | 0 |
| Removed branches | 0 |
| Duplicated contract sources added | 0 |
| Responsibility growth | 없음; Registry가 기존 output metadata 소유 |
| Verdict | `COMPLEXITY_PASS` |

## Contract Delta

| 항목 | 결과 |
|---|---|
| Modified contract | `trade.country_rank → CountryShare` output contract |
| Canonical source of truth | `semantic_capabilities.CAPABILITY_ARGUMENTS` 및 기존 TypedResult executor |
| Consumers | plan/output validation, canonical capability resolution, projection field validation |
| Remaining duplicated mappings | trade field vocabulary와 일부 legacy runtime mapping은 `REFACTOR_CANDIDATE` |

## 다음 과제

GM14를 회복하려면 `수입 비중`을 concentration으로 잘못 표현하는 경우와 명시적 HHI/집중도 요구를 deterministic하게 구분하는 공통 semantic selection contract가 필요하다. 이번 iteration에서는 질문 문자열 특례나 ConcentrationMetric 의미 변경을 하지 않고 중단한다.
