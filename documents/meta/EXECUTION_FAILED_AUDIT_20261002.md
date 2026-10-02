# execution_failed 5건 원인 분석 — 2026-10-02

## 범위와 기준

- 대상: 기존 full replay에서 `execution_failed`였던 5건
- 대상 QA: `PF01, PF02, PF03, CN07, CN08`
- 검증 환경: `18012`, `komir-rag-chat:aast-content-r9`
- 운영 `18002`: 변경 없음
- 전체 57건 replay: 수행하지 않음
- 분석용 제한 replay: 위 5건만 수행

## 공통 최초 causal failure

5건 모두 Capability 호출 전에 AAST Coverage Validator에서 기간 비교 예외가 발생했다.

`aast_coverage.py:350`의 다음 연산이 `_period_signature()`가 반환하는 dict를 set 원소로
사용한다.

```text
planned_periods = {_period_signature(node.args.get("period")) for node in candidates}
TypeError: unhashable type: 'dict'
```

따라서 공개 SSE의 `execution_failed`는 Capability runtime 오류가 아니라 Validator의
공통 runtime contract 오류다. 해당 단계 이후의 Capability Input/Output, TypedResult,
Projection, Renderer는 실행되지 않았다.

## QA별 분석

| QA | 질문 | 최초 causal failure | 1차 category | 후속 관찰 |
|---|---|---|---|---|
| PF01 | 니켈 현재 가격이랑 다음달 전망 같이 알려줘 | Validator 기간 비교 `TypeError` | `RUNTIME` | semantic requirement의 `price_forecast + future_horizon(1)`를 AAST가 `price + time_series`로 생성. `METRIC_PRESERVATION_FAILED`, `PERIOD_PRESERVATION_FAILED`도 존재 |
| PF02 | 니켈 지난 6개월 가격이랑 향후 전망 이어서 보여줘 | Validator 기간 비교 `TypeError` | `RUNTIME` | 가격 6개월 branch는 생성되지만 전망 branch가 `indicator` 또는 `production`으로 변형됨. previous-result dependency route도 감지되나 실행 전 중단 |
| PF03 | 니켈 지금 가격이 전망치 보다 높은 편이야? | 기존 replay: `execution_failed`; r9 제한 replay: Validator 단계에서 `semantic_plan_incomplete` | `RUNTIME` | bounded repair가 `price_forecast + future_horizon(1)`와 compare graph를 생성한 실행도 있었으나 재검증에서 동일 dict/set 예외 또는 coverage invalid. forecast capability/data 미확보도 별도 blocker |
| CN07 | 리튬 가격 전망이랑 최근 관련 뉴스 같이 알려줘 | Validator 기간 비교 `TypeError` | `RUNTIME` | 문서 branch는 생성되지만 forecast requirement가 `price + time_series`로 변형됨. forecast 외부 데이터 의존 가능성 있음 |
| CN08 | 지난달 광물종합지수 변동이랑 월간동향 요약 같이 보여줘 | Validator 기간 비교 `TypeError` | `RUNTIME` | indicator retrieve → project와 document retrieve 두 branch가 생성됨. Validator 이후의 capability/retrieval 상태는 관찰되지 않음 |

## 경계별 판정

| 경계 | PF01 | PF02 | PF03 | CN07 | CN08 |
|---|---|---|---|---|---|
| Semantic Requirement | 생성됨 | 생성됨/forecast 누락 변동 | 생성됨 | 생성됨 | 생성됨 |
| AAST | forecast metric/period 손실 | forecast branch metric 변형 | 초기 AST 변형, repair 시도 | forecast branch 변형 | 두 branch 구조 존재 |
| Validator | **TypeError** | **TypeError** | **TypeError/invalid** | **TypeError** | **TypeError** |
| Capability Input | 미도달 | 미도달 | 미도달 | 미도달 | 미도달 |
| Capability Output | 미도달 | 미도달 | 미도달 | 미도달 | 미도달 |
| TypedResult | 미도달 | 미도달 | 미도달 | 미도달 | 미도달 |
| Projection/Renderer | 미도달 | 미도달 | 미도달 | 미도달 | 미도달 |

## Category 분포

### Primary category — QA 단위 단일 분류

```text
RUNTIME / VALIDATOR_RUNTIME_CONTRACT: 5
CAPABILITY_INPUT: 0
CAPABILITY_OUTPUT: 0
CANONICAL_RESOLUTION: 0 (최초 실패 기준)
TYPED_RESULT_CONTRACT: 0
PROJECTION: 0
JOIN_ALIGN: 0
RETRIEVAL_EVIDENCE: 0 (최초 실패 기준)
SOURCE_DATA: 0 (Validator 이전 차단)
```

### Secondary semantic/data observations

```text
AAST capability selection / metric-period preservation issue: PF01, PF02, PF03, CN07 (4)
forecast capability 또는 외부 전망 데이터 확인 필요: PF01, PF02, PF03, CN07 (4)
복합 branch graph가 생성된 항목: CN08 (1)
```

이 secondary 항목은 Validator runtime 예외를 고친 뒤에야 실제 Capability/Source 상태를
판정할 수 있으므로 현재 `SOURCE_DATA` 또는 `RETRIEVAL_EVIDENCE`로 확정하지 않았다.

## 저비용 회복 후보

1. **공통 Validator dict/set 예외 제거**
   - 5건 모두의 최초 실행 차단 원인
   - deterministic contract 수정 1개로 5건 모두 다음 단계까지 진행 가능
2. **CN08**
   - indicator + document 두 branch가 이미 AAST에 존재
   - Validator 예외 제거 후 실제 indicator/document retrieval 상태를 확인할 수 있음
   - 현재 기준 예상 저비용 회복 후보: 1건
3. **PF01/PF02/PF03/CN07**
   - Validator 예외 제거만으로는 forecast metric/period 보존과 `forecast.price` capability/data가 남음
   - 외부 전망 데이터가 없으면 `EXTERNAL_DATA_BLOCKED`로 남겨야 함
   - 현재 코드 수정 없이 회복 가능하다고 판단할 수 없음

## 결론

- 5건 모두 공통적인 최초 실패는 `RUNTIME` 성격의 Validator contract bug다.
- MP01과 같은 저비용 deterministic contract 후보는 Validator 예외 수정이며, 5건을 공통으로 다음 단계까지 진행시킬 수 있다.
- 단, 4건은 forecast requirement가 AAST에서 `price`로 변형된 별도 semantic/capability 문제와 외부 전망 데이터 의존이 있다.
- CN08은 AAST branch가 이미 보존되어 있어 Validator 수정 후 1건의 저비용 회복 후보로 우선 재평가할 가치가 있다.
- 이번 단계에서는 코드와 57건 full replay를 수정·실행하지 않았다.

## Validator runtime repair round — r11

- 검증 이미지: `komir-rag-chat:aast-content-r11`
- image ID: `sha256:a2fbfab5f4e283d941129a8218313c0286531cb1dcf4a299ec00c57f0bf9bc6e`
- 검증 포트: `18012`
- 운영 `18002`: 변경 없음
- full replay: 수행하지 않음

### 적용한 공통 수정

`_period_signature()`가 scalar/year/range/structured period를 정렬된 hashable tuple로
정규화하도록 수정했다. 또한 복수 branch가 같은 capability를 공유할 때 기간을
`next(set)`으로 임의 선택하지 않고, 요구 signature가 후보 signature 집합 또는
이미 낮춰진 typed plan에 존재하는지 검사하도록 수정했다. 질문·QA별 분기는 없다.

### Fast Regression 결과

| QA | Validator 이후 경계 | 결과 | 실제 다음 blocker |
|---|---|---|---|
| PF01 | VALID → capability 실행 | PARTIAL | 현재 가격 성공, `forecast.price`는 `no_data` |
| PF02 | invalid graph 차단 | `semantic_plan_incomplete` | forecast branch의 metric/period 보존 실패가 남음; TypeError 아님 |
| PF03 | invalid graph 차단 | `semantic_plan_incomplete` | forecast branch의 metric/period 보존 실패가 남음; TypeError 아님 |
| CN07 | VALID → capability 실행 | PARTIAL | 뉴스 retrieval 성공, forecast branch `no_data` |
| CN08 | invalid graph 차단 | `semantic_plan_incomplete` | indicator `series`와 계획의 `indicator` contract 및 projection field 불일치 |

5건 모두에서 `TypeError: unhashable type: 'dict'`는 재현되지 않았다.
PF01·CN07은 Validator를 통과해 실제 capability 단계까지 도달했고, PF02·PF03·CN08은
Validator가 runtime 예외 대신 의미 보존 위반을 명시적으로 차단했다. forecast 4건을
PASS로 판정하지 않았으며, 이번 범위에서 forecast capability·외부 데이터·AAST planning은
수정하지 않았다. CN08의 content PASS도 아직 확인되지 않았다.

### Sentinel 결과

| 경로 | QA | 결과 |
|---|---|---|
| AAST + Validator | MP01 | 정상 완료, price series와 국가별 수입 구성 반환 |
| AAST | ADD27 | 정상 완료, series 반환 |
| AAST | CN09 | 정상 완료, 2024 production 합계 반환 |
| Direct | REG02 | 정상 완료, 가격기준 502 최신 가격 반환 |
| Navigation | ADD45 | 정상 페이지 추천 완료 |

sentinel regression: `0`

### 테스트 및 실행 시간

- Validator/contract 관련 테스트: `16 passed`
- 관련 regression 묶음: `92 passed`
- 대상 live SSE: 5건, 약 10초~15초/건
- sentinel live SSE: 5건, 약 1.5초~10.5초/건
- 57건 full replay: 미실행

공식 content baseline은 full replay를 하지 않았으므로 `27/57 (47.37%)`로 유지한다.
ADD27·MP01의 기존 잠정 회복을 포함한 잠정치는 `29/57 (50.88%)`이며, CN08 신규 회복은
이번 검증에서 확인되지 않아 `30/57`로 올리지 않는다.

## r14 — Capability boundary typed contract Fast Regression

### 변경 범위

- `ForecastCapabilityInput`: `metric=price_forecast`, `future_horizon`,
  `operation`을 Pydantic runtime contract로 검증했다.
- `IndicatorSeriesInput`/`IndicatorSeriesRow`: indicator·period·operation과
  canonical `value/date/indicator` output을 검증했다.
- `AAST Coverage Validator`: `price` domain에 남아 있는 `price_forecast`를
  `forecast.price`로, indicator의 semantic `series`를 canonical `indicator`와
  동등하게 비교한다. structured period는 기존 hashable signature을 사용한다.
- indicator 원천 numeric alias `series/indx/center`는 Capability boundary에서
  canonical `value`로만 변환한다.

질문별 분기, 정답 하드코딩, 전체 AAST 재작성은 추가하지 않았다.

### r14 Fast Regression

| 대상 | 실제 결과 | 최초/현재 blocker |
|---|---|---|
| PF02 | `ABSTAIN`, `semantic_plan_incomplete` | Gemma AAST가 forecast branch를 `price`/`indicator`로 생성하거나 `future_horizon`을 누락해 validator가 `CAPABILITY_SELECTION_MISMATCH`/`PERIOD_PRESERVATION_FAILED`로 차단. typed executor 미진입 |
| PF03 | `ABSTAIN`, `semantic_plan_incomplete` | 동일한 forecast capability/period 보존 실패. 외부 forecast 데이터 유무와 별개로 실행 전 graph가 invalid |
| CN08 | `ABSTAIN`, `semantic_plan_incomplete` | r14 실제 Gemma가 indicator retrieve 뒤 `filter(field=series)`를 생성하고 재시도에서도 같은 graph를 생성해 parser/AST projection contract 단계에서 중단. `indx→value` alias 단위 테스트는 통과했으나 live path 미진입 |

Sentinel 5건은 모두 SSE 완료·비기권으로 회귀가 없었다: MP01, ADD27, CN09,
Direct(`리튬 최신 가격 얼마야?`), Navigation(`리튬 가격 화면으로 가줘`).
추가 sentinel 3건도 모두 완료·비기권이었다.

### 검증 수치

- typed/coverage 대상 unit: `39 passed`
- 관련 Fast Regression 묶음: `251 passed, 79 subtests passed`
- 대상 live SSE: 3건 모두 HTTP 200/SSE done이나 content 성공은 0건
- sentinel live SSE: 8건 중 abstain 0건
- r14 이미지: `komir-rag-chat:aast-content-r14`
- r14 image ID: `sha256:ded0a80050843627bd66df3b07984de1b8c163ac814a379c7ccc3fb7596d7a3a`
- 검증 컨테이너: `komir-rag-chat-qa106-direct-r4`, `18012`
- 운영 `18002`: 변경하지 않음
- 57건 full replay: 미실행

따라서 공식 content baseline은 `27/57 (47.37%)`, ADD27·MP01을 포함한 잠정
예상치는 `29/57 (50.88%)`로 유지한다. 이번 contract 수정만으로 PF02/PF03/CN08의
신규 `CONTENT_PASS`는 확인되지 않았다. PF02/PF03은 forecast capability/data의
실제 결과 이전에 parser/AAST 보존 문제가 남아 있고, CN08은 실제 Gemma의 filter
field 생성이 남은 공통 frontend/AST contract 문제다.
