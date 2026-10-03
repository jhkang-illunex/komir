# GM14 trade.concentration output contract audit

- 실행 환경: 18012 검증 환경
- 운영 18002: 변경 없음
- 대상: GM14
- 기준: 최신 trace, `trade.concentration` Registry/TypedResult 경계
- 코드 수정: 없음

## 결론

GM14는 `import_share` alias 누락이 아니다. `trade.concentration`은 aggregate concentration/HHI 결과를 반환하고, `import_share`는 국가별 수입 비중(`CountryShare`)을 의미하는 별도 semantic output이다.

현재 `trade.concentration` output에는 `import_share`를 결정적으로 유도할 값/contract가 선언되어 있지 않다. 임의 numeric field 매핑이나 alias 추가는 의미를 바꾸므로 수행하지 않았다.

최종 분류: **CAPABILITY_GAP**

## Trace

### Semantic requirement

최신 trace에서 parser가 생성한 requirement는 다음과 같다.

```text
price/current, price_group=strategic
trade/concentration, flow=import, scope=KR
```

### AAST candidate

무역 branch는 다음 구조였다.

```text
retrieve_concentration:
  domain=trade
  metric=concentration
  flow=import
  scope=KR

project_concentration:
  fields=[mineral, import_share]
```

후속 join은 `mineral` 기준으로 가격 branch와 결합하고, 최종 projection은 `right.import_share`를 요구했다.

### 최초 causal failure

`AST candidate → output field validation`

검증 오류:

```text
ast_incomplete: project_concentration requires field(s) ['import_share']
not produced by upstream;
available fields: ['concentration', 'entity', 'evidence', 'mineral', 'source', '광종']
```

동일 오류가 fresh 실행 3회에서 재현되었고, 모두 `semantic_plan_incomplete`으로 종료되어 Capability 실행/TypedResult 생성 단계에는 진입하지 못했다.

## Contract 비교

| 경계 | 확인 결과 |
|---|---|
| `trade.concentration` capability | 존재; 국가별 수입 원자료를 HHI/집중도 결과로 반환하는 경로 |
| Raw/available output | `concentration` 및 식별/evidence 필드; `import_share` 없음 |
| TypedResult semantic type | 현재 concentration 전용 `CountryShare`/`import_share` 선언 없음 |
| Projection request | `import_share` 요구 |
| 의미 관계 | alias가 아님. aggregate concentration과 country-level import share는 다른 output semantics |
| downstream composition | 가격 결과와 `right.import_share`를 mineral 기준으로 join하려 했으나 upstream output contract에서 중단 |

`semantic_capabilities.py`의 registry에도 `trade.concentration`에 대한 `output_fields` 선언은 없고, `CAPABILITY_OUTPUTS`에는 concentration output type이 별도 선언되어 있지 않다. 반면 `import_share`는 planner의 country-share/country-rank field vocabulary에 존재한다. 이는 물리 row alias가 아니라 서로 다른 capability output vocabulary가 혼재한 상태다.

## 판정

### 1. 동일 의미 canonical field 존재 여부

아니오. `concentration`을 `import_share`로 이름만 바꾸는 것은 HHI/집중도 aggregate를 국가별 비중으로 오인하게 만든다.

### 2. TypedResult canonicalization 손실 여부

현재 실행은 TypedResult 생성 전 output validation에서 중단되므로 canonicalization 손실로 볼 수 없다.

### 3. `import_share` 계산/Capability 필요 여부

예. `import_share`를 답하려면 국가별 수입액과 전체 분모를 사용한 country-share 결과 또는 이를 직접 제공하는 `trade.country_rank`/동등 capability가 필요하다. 현재 `trade.concentration`만으로는 결정할 수 없다.

따라서 `CAPABILITY_GAP`이며, 별도 계산 primitive 또는 capability selection/semantic requirement contract 검토가 필요한 항목이다. 이번 범위에서는 구현하지 않는다.

## 반복 probe

| 실행 | 결과 | 최초 오류 |
|---:|---|---|
| 1 | FAIL / safe abstention | `project_concentration`의 `import_share` 미생성 |
| 2 | FAIL / safe abstention | 동일 |
| 3 | FAIL / safe abstention | 동일 |

질문별 특례, validator 완화, 임의 numeric mapping은 적용하지 않았다. 기존 stable sentinel과 rag_core는 코드가 변경되지 않았으므로 이번 audit에서 재실행하지 않았다.

## Architecture & Complexity Guard

### Complexity Delta

| 항목 | 결과 |
|---|---|
| Files changed | artifact 1개만 추가 |
| New classes / public contracts | 0 |
| New registry entries | 0 |
| New special-case branches | 0 |
| New central-dispatch branches | 0 |
| Duplicated contract sources added/removed | 0 / 0 |
| Responsibility growth | 없음 |
| Verdict | `COMPLEXITY_PASS` |

### Contract Delta

| 항목 | 결과 |
|---|---|
| New/modified contracts | 없음 |
| Canonical source of truth | 기존 capability/semantic output registry와 실제 trace |
| Consumers | Planner output validation, existing trade capability boundary |
| Remaining duplicated mappings | planner field vocabulary와 capability output declaration 간 불일치가 `REFACTOR_CANDIDATE` |

## 다음 작업 후보

GM14를 회복하려면 먼저 `import_share`의 authoritative semantic owner를 정해야 한다. 안전한 후보는 기존 `trade.country_rank`의 `CountryShare` output contract 재사용 여부를 검토하는 것이며, `trade.concentration` 결과를 alias로 바꾸는 방식은 부적절하다. 이 결정 없이 구현하면 concentration과 country share의 의미가 섞이는 contract drift가 발생한다.
