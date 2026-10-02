# Capability / Calculation / Join Fast Repair — 2026-10-03

## 기준과 범위

- 공식 CONTENT_PASS baseline: `33/57`
- Fast Regression 잠정 기준: MP03 포함 `34/57`
- Architecture Freeze 유지
- AAST, SemanticPlan, Query Gate, Renderer 구조 변경 없음
- 운영 `18002` 변경 없음
- 검증 환경: `18012`, 컨테이너 `komir-rag-chat-qa-cap-r16`
- 이미지: `komir-rag-chat:capability-contract-r16`
- 이미지 ID: `dcea41801f8de5eecb3cfb12029df1203d15c26ead4df546805d14c12d044e8b`

## 공통 원인 확인

### 1. Binary ratio contract

기존 `calculate_ratio`는 하나의 row population 안에 numerator/denominator가
동시에 있어야 했다. 서로 다른 aggregate가 각각 스칼라 결과를 반환하는 경우에는
`ratio_fields_required`가 발생할 수 있었다.

`calculate_ratio_between(left, right, args, resolve)`를 추가하여 두 개의 정상적인
scalar TypedResult를 deterministic하게 결합한다. 각 입력에서 `value` 또는 명시된
typed field만 해석하며 임의의 숫자 열을 선택하지 않는다. provenance, evidence,
period, entity, upstream step 연결을 합쳐 반환한다.

이 변경은 일반 binary ratio contract이며 ADD16 전용 처리가 아니다.

### 2. Side-by-side comparison field resolution

한쪽 metric의 field명이 다른 쪽에도 복사되어 `comparison_field_required`가 나는
경우가 있었다. `side_by_side`에 한하여 해당 입력에서 field가 해석되지 않으면
등록된 canonical measure(`value`, `production_volume`, `reserves_volume`,
`import_value`, `import_amount`, `price`, `inventory`)만 독립적으로 재해석한다.

산술 비교(`difference`, `ratio`, `percent_change`)는 기존처럼 명시 field와 단위/
정렬 계약을 엄격히 요구한다.

### 3. Canonical join key priority

`country`와 `country_name_en`처럼 한 row에 동일 의미 alias가 함께 있으면 strict
resolver가 모호하다고 판단했다. 요청한 canonical key 자체가 있으면 그 key를 우선
사용하도록 정규화했다. alias 값을 임의로 합치거나 국가명을 추정하지 않는다.

## 변경 파일

- `inhouse/rag_core/ragkit/analytical_share.py`
  - 두 TypedResult 입력용 binary ratio contract
- `inhouse/rag_core/ragkit/live_multihop.py`
  - binary ratio dispatch
  - strict canonical field 우선순위
- `inhouse/rag_core/ragkit/relational_ops.py`
  - side-by-side 입력별 canonical measure 재해석
- `inhouse/rag_core/tests/test_live_relations.py`
  - binary ratio, cross-metric side-by-side, canonical country join 회귀

## Unit / regression

- 관련 unit 및 AAST coverage: **93 passed**
- 전체 `inhouse/rag_core/tests` + Direct/Query Gate 회귀:
  **1518 passed, 1 failed, 695 subtests**
- 유일한 실패는 `test_parser_advertises_exact_history_namespace_and_rejects_invented_result`로,
  이번 capability/calculation/join 수정과 무관한 기존 parser contract 기대 불일치다.
  이 라운드에서 AAST/parser를 수정하지 않았으므로 해당 실패는 별도 기존 실패로
  보존했다.
- `compileall`, `git diff --check`: 통과

## 18012 Fast Regression

| QA / sentinel | 결과 | 관찰 |
|---|---|---|
| GM01 | 실행 성공 | production/import 결과가 side-by-side 표와 차트로 반환됨 |
| ADD16 | 실행 성공 후보 | 리튬 매장량/칠레 비율 표 생성; 이 live 실행은 compare ratio 경로로 완료됨 |
| GM02 | 미회복 | resource 결과와 trade 결과는 실행됐으나 Gemma가 trade branch를 `trade.monthly`로 선택해 `country_rank` 결과가 없어 `node_intersect`에서 dependency 실패. 이는 AAST/capability selection 문제이며 이번 범위에서 수정하지 않음 |
| MP01 | 회귀 없음 | price/import composite 반환 |
| ADD27 | 회귀 없음 | price series 반환 |
| ADD15 | 회귀 없음 | production/reserves 두 branch 반환 |
| GM08 | 회귀 없음 | document/resource 반환 |
| Direct | 회귀 없음 | 최신 니켈 가격 반환 |

추가로 이전 r15 trace에서 확인한 MP04/ADD03은 각각 resource 원천 `no_data`/
`dependency_unavailable`, 아연 원천 `no_data`로 남아 있다. 이번 iteration에서는
데이터를 임의 생성하거나 source/evidence를 우회하지 않았다.

## Direct criterion / projection 판정

ADD01/ADD49 및 관련 가격 질의의 `price_criterion_mapping_missing`은 현재 원천
광종-가격기준 mapping이 확인되지 않는 source contract 문제다. 대표 기준 목록만으로
serial을 추정하지 않았고, 이번 수정에서 변경하지 않았다.

## 점수 및 상태

- 이번 공통 수정으로 확정된 공식 full-replay CONTENT_PASS 증가는 없음
- 공식 baseline: `33/57`
- 기존 잠정치: `34/57` (MP03 포함) 유지
- ADD16/GM01은 fast execution/content 후보로 기록하되 full replay 전 공식 점수로
  승격하지 않음
- 57건 full replay: 실행하지 않음
- 18002: 미변경

## 남은 ROI 후보

1. GM02의 trade capability 선택/AAST branch 보존 — 이번 architecture freeze 범위 밖
2. MP04/ADD03의 원천 데이터 availability audit
3. 가격기준 mapping source contract 보강 후 ADD01/ADD49/CN05/CN07/GM13 재검증
4. 기존 parser history namespace 테스트 실패 별도 정리

## GM02 capability-selection repair r18

### 원인

GM02의 첫 trace는 다음과 같았다.

```text
required output: RankedCountrySet
selected physical output: TradeTimeSeries
retrieve metric: import_value
downstream rank field: import_value
```

`domain=trade`라는 넓은 분류만으로는 두 output contract를 구분할 수 없어
coverage validator가 잘못된 `trade.monthly` 선택을 통과시켰다. 이후 join 문제가
발생한 것이 아니라, join 이전 capability selection이 최초 divergence였다.

### 적용한 공통 수정

- AAST coverage validator가 `trade.country_rank` 요구에 대해 `import_value`/
  `export_value` 기반 trade series retrieve를 `TradeTimeSeries`로 판정
- `CAPABILITY_SELECTION_MISMATCH` violation에 required/planned output type을 기록
- typed requirement가 이미 `trade.country_rank`이고 해당 physical retrieve가
  하나로 결정될 때만 bounded repair 1회 수행
  - import: `import_value → import_amount`
  - export: `export_value → export_amount`
  - `operation=country_rank` 추가
  - downstream rank field도 같은 canonical metric으로 변경
  - 기존 `scope`, mineral, graph edge는 보존
- scope preservation violation이 capability violation과 함께 발생해도 같은
  deterministic repair에서 처리

질문 문자열, QA ID, 광종명, 정답값은 사용하지 않았다. 기존 AAST 구조나 Query Gate를
추가하지 않았다.

### r18 실제 SSE

- 이미지: `komir-rag-chat:gm02-capability-selection-r18`
- 이미지 ID: `6f1c3b02e3566bf2b751e6d2475f1c45f0bcd11a22b4166ef13247b983acda4c`
- 컨테이너: `komir-rag-chat-qa-gm02-r18`
- 포트: `18012`
- 운영 `18002`: `komir-rag-chat:current-session-r19`, 변경 없음

실제 repair trace:

```text
node_import_lithium_kr:
  metric=import_amount
  operation=country_rank
  scope=KR
  action_id=trade.country_rank
node_import_rank_kr:
  field=import_amount
node_intersect: success
node_final_countries: success
root: success / fact_set
```

GM02 SSE는 HTTP 200, table, done 이벤트를 생성했고 `upstream step failed` 없이
최종 country intersection에 도달했다.

### r18 fast regression

| 항목 | 결과 |
|---|---|
| GM02 | capability selection repair 및 join 포함 최종 실행 성공 |
| MP01 | 성공, 기존 composite 결과 유지 |
| ADD27 | 성공, price series 유지 |
| ADD15 | 성공, production/reserves 두 branch 유지 |
| Direct | 성공 |

관련 unit: **50 passed**. 전체 `inhouse/rag_core/tests`: **1511 passed, 1 failed,
695 subtests**. 유일한 실패는 기존
`test_parser_advertises_exact_history_namespace_and_rejects_invented_result`이며,
이번 capability validator/repair 변경과 무관한 parser history namespace 기대
불일치다. 이번 수정으로 기존 PASS regression은 관찰되지 않았다.

이번 단계에서 GM02를 `PROVISIONAL_CONTENT_PASS`로 승격할지는 content oracle의
intersection 국가값 비교가 필요하므로, execution success와 content success를
분리해 기록한다. 공식 `CONTENT_PASS 33/57`, Fast Regression 잠정 기준 `34/57`은
full replay 전까지 유지한다.

## r19 Capability boundary Fast Regression — 2026-10-03

### 범위

- 사용자 기준 Fast Regression 잠정 baseline: `35/57`
- Architecture Freeze 유지: AAST, SemanticPlan, Query Gate, Renderer 미수정
- 운영 `18002` 미변경
- 검증 컨테이너: `komir-rag-chat-qa-capability-r19`, 포트 `18012`
- 이미지: `komir-rag-chat:capability-contract-r19`
- 이미지 ID: `9f9cd050b69d75ef27c968afa19046858b4c9b7707d2fbc2fbc49462f8defb16`
- 57건 full replay는 실행하지 않음

### 적용한 공통 수정

`trade.country_rank` Capability가 물리 컬럼 `total(<표시명>)`만 반환하는 경우,
선언된 typed metric이 `import_amount/export_amount/import_weight/export_weight`이고
해당 `total` 컬럼이 하나일 때만 canonical metric field를 추가했다. 이 변환은
Capability boundary에서만 수행하며, 일반 문서/임의 trade series에는 적용하지 않는다.
복수 `total` 컬럼은 의미가 모호하므로 추가하지 않는다. 따라서 downstream compare와
projection은 물리 표시명을 직접 해석하지 않고 canonical field를 사용한다.

변경 파일:

- `inhouse/rag_core/ragkit/live_multihop.py`
- `inhouse/rag_core/tests/test_live_multihop.py`

### Fast Regression 결과

| QA/sentinel | 결과 | 관찰 |
|---|---|---|
| GM01 | 실행 성공 후보 | production/import 양쪽 Capability가 성공하고 side-by-side 표/차트가 반환됨. r18의 `comparison_field_required` 제거 |
| GM02 | 회귀 없음 | country intersection 표 반환; capability selection bounded repair 유지 |
| ADD16 | 회귀 없음 | reserves ratio 표 반환 |
| MP03 | 회귀 없음 | country rank + current price 표 반환. 일부 upstream 실패 표시는 별도 보존 |
| MP01 | 회귀 없음 | price series + import composition 표 반환 |
| ADD27 | 회귀 없음 | price time series 표/차트 반환 |
| ADD15 | 회귀 없음 | production/reserves 두 branch 반환 |
| GM08 | 회귀 없음 | use 문서 + resource ranking 반환 |
| Direct | 회귀 없음 | 최신 니켈 가격 반환 |
| Navigation | 기존 실패 재현 | `semantic_plan_incomplete`; 이번 Capability boundary 수정으로 발생한 오류가 아님. Query Gate/AAST는 이번 범위에서 수정하지 않음 |

GM01의 실제 trace는 양쪽 입력이 모두 `SUCCESS`였고, 무역 행의 물리 키가
`total(수입금액합계(USD))`였으며 수정 후 `import_amount`가 추가되어 compare가
`SUCCESS`로 종료되었다. 관련 결과에는 production/import 값과 각 source가 함께
남았다.

### 테스트

- 관련 unit 및 relation regression: **78 passed**
- `compileall`, `git diff --check`: 통과
- 전체 rag_core regression: 기존 기준 `1511 passed / 1 known failure / 695 subtests`
  (parser history namespace 기대 불일치; 이번 Capability 변경과 무관)

### 점수 및 잔여 목록

- 이번 r19 수정으로 공식 full-replay 점수는 갱신하지 않음
- Fast Regression 잠정 baseline: **35/57 유지**
- 이번 r19에서 신규 `PROVISIONAL_CONTENT_PASS`는 content oracle 재검증 전까지
  추가하지 않음. GM01은 execution/content 후보로만 보존한다.
- `ADD01/ADD49/GM13` 가격 기준 mapping, `GM05` trade evidence, `MP04/ADD03`의
  no_data, forecast 계열은 Capability 코드로 우회하지 않고
  `documents/meta/CAPABILITY_DATA_AUDIT_PENDING_20261003.md`에 분리했다.
- Renderer-only 항목은 이번 수정 대상에서 제외했다.
