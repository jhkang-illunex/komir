# QA57 Root Cause Cluster Repair — 2026-10-03

## 범위

- 기준 strict baseline: `17/57`
- 대상: `AAST_FAILURE 12 + CAPABILITY_FAILURE 18`, 총 30건
- 운영 18002: 변경 없음
- 검증: 18012만 사용
- `DATA_BLOCKED 10`, `RENDER_FAILURE 0`은 이번 수정 대상에서 제외
- QA57 full replay는 수행하지 않음
- 18012 이미지: `komir-rag-chat:qa-contract-r23-20261003`
- digest: `sha256:20003dfb0241a8316557cd3dfe02ede3484816a7490915c57caa9682080a726`

## 1. Failure cluster

최초 causal failure를 기준으로 분류했다. `semantic_plan_incomplete`, `all_roots_failed`는
최종 표지가 아니라 trace의 첫 contract violation으로 세분화했다.

### AAST_FAILURE — 12건

| Subcategory | QA | Count |
|---|---|---:|
| REQUIREMENT_PRESERVATION / BRANCH_MISSING | MP07, CN01, GM11, GM14, ADD06, ADD46 | 6 |
| COMPOSITION_OPERATOR | IX01, CN09 | 2 |
| DEPENDENCY_BINDING | ADD25 | 1 |
| CAPABILITY_SELECTION | ADD32 | 1 |
| PERIOD/ENTITY/SCOPE_BINDING | REG05 | 1 |
| ROUTE/PLAN ESCALATION | ADD45 | 1 |
| 합계 |  | **12** |

### CAPABILITY_FAILURE — 18건

| Subcategory | QA | Count |
|---|---|---:|
| PROJECTION / CANONICAL_FIELD | DOC02, MP04, MP09, CN08, ADD01, ADD18, ADD38, ADD49 | 8 |
| JOIN_ALIGNMENT | IX02, GM01, ADD16 | 3 |
| CRITERION_BINDING | GM13, ADD03 | 2 |
| INPUT/OUTPUT_CONTRACT | MI02, REG06 | 2 |
| CALCULATION / AGGREGATION | REG02 | 1 |
| SOURCE_ADAPTER | ADD12 | 1 |
| RETRIEVAL_EVIDENCE | NEWS03 | 1 |
| 합계 |  | **18** |

Data Audit 정책에 따라 `PF01, PF02, PF03, MP05, CN04, CN05, CN07, GM05, GM12, ADD40`은
별도 `DATA_BLOCKED`로 유지했다.

### Projection cluster live audit

18012 r23에서 `DOC02, MP04, MP09, CN08, ADD01, ADD18, ADD38, ADD49`를 묶어
확인했다. 결과는 `FAIL 6 / PARTIAL 2`였다. `DOC02`는 document retrieval validation
실패 후 `title`이 비어 있었고, `ADD01/ADD38`은 upstream `no_data` 또는 price
project 실패였다. `ADD49`는 criterion mapping 실패 뒤 `value` projection이
실행됐다. `MP04`는 resource YoY row가 없어 `year` projection이 실패했고,
`CN08`은 indicator calculation contract가 먼저 실패했다. 현재 upstream field가
존재한다는 공통 증거가 없어 alias를 느슨하게 바꾸지 않았다. `MP09`의 partial
price 결과도 누락된 document branch를 회복시키지 못한다.

## 2. Regression 교차 분석

초기 상태는 `rag_core 1486 passed / 69 failed`, `rag_chat 154 passed / 2 failed`였다.
공통 원인은 다음 순서로 확인됐다.

| Root Cause | QA Count | Regression 증적 | 예상 회복 | 위험 |
|---|---:|---|---:|---|
| price `criterion_mode` typed input이 actual fixture adapter에 미등록 | 가격/series 경로 | fixture `unconsumed_slots criterion_mode` 연쇄 실패 | QA 직접 회복 근거 없음; regression 다수 | 낮음 |
| inventory.series action registry/metric routing 불일치 | REG05 관련 | 미정의 `_canonical`, action registry 미등록 | inventory backend cluster | 낮음 |
| AAST branch/selection/period 보존 | 12 | semantic plan/branch trace | 공통 수정 후보 | 높음 |
| canonical projection/alias | 8 | projection field 실패 | 2건 이상 가능성 | 중간~높음 |
| join/alignment | 3 | compare/alignment 실패 | 2건 이상 가능성 | 중간 |
| history namespace stale assertion | 0 | parser contract test 1건 | QA 회복 없음 | 낮음 |
| legacy SSE cancellation retry contract | 0 | rag_chat test 1건 | QA 회복 없음 | 높음; 이번 범위 제외 |

## 3. 적용한 공통 수정

- `inhouse/rag_core/tests/qa500_actual_execution.py`
  - `criterion_mode`를 fixture consumed/round-trip contract에 추가
  - `inventory.series`를 actual replay action registry에 추가
- `inhouse/rag_core/ragkit/live_multihop.py`
  - `_action_id()`의 존재하지 않는 `_canonical()` 호출을 일반 문자열 normalization으로 교체
- `inhouse/rag_core/tests/test_live_parser_contract_feedback.py`
  - 현재 parser의 명시적 `history:` namespace contract에 맞춰 stale repair 기대를 정리
- `inhouse/rag_chat/tests/test_retrieval_routing.py`
  - typed `criterion_mode=REPRESENTATIVE`를 공통 routing assertion에 반영

질문/QA/mineral별 분기나 정답 하드코딩은 추가하지 않았다.

## 4. 검증 결과

- targeted actual/contract/series: 최종 **196 passed** 계열, inventory cluster **117 passed**
- history/semantic/routing: **109 passed**
- 전체 `rag_core`: **1543 passed / 0 failed / 695 subtests / 1 warning**
- 전체 `rag_chat`: **155 passed / 1 failed / 15 subtests**

남은 `rag_chat` 1건은 `test_sse_cancellation.py::...legacy_control-False`이며, 현재
legacy SSE 경로의 실제 호출 4회를 기존 3회로 기대하는 retry-count contract 차이다.
이번 기능 cluster의 production 동작을 임의 변경하지 않고 별도 blocker로 남겼다.

### 18012 Fast Regression ×3

대상: `MP01, MP03, GM02, GM08, REG03, REG05, ADD15, ADD27`.

| QA | 1회 | 2회 | 3회 | strict 관찰 |
|---|---|---|---|---|
| MP01 | PARTIAL | PARTIAL | PARTIAL | 3/3 내용 branch 유지 |
| MP03 | PARTIAL | PARTIAL | PARTIAL | 1/3만 import rank + price 완전 유지 |
| GM02 | PARTIAL | PARTIAL | PARTIAL | 1/3만 정확한 intersection; 2회는 과다 country |
| GM08 | PARTIAL | PARTIAL | PARTIAL | 3/3 usage + production 내용 유지 |
| REG03 | PARTIAL | PARTIAL | PARTIAL | 3/3 latest price 내용 유지 |
| REG05 | FAIL | FAIL | FAIL | 0/3 plan generation |
| ADD15 | PARTIAL | PARTIAL | PARTIAL | 3/3 production/reserves 내용 유지 |
| ADD27 | PARTIAL | PARTIAL | PARTIAL | 3/3 price series 내용 유지 |

Fast `PARTIAL`은 strict content pass가 아니다. 신규 `STABLE_RECOVERED`는 **0건**이고,
strict provisional baseline은 **17/57 유지**다. MP03·GM02는 계획 변동으로 FLAKY 후보다.

## 5. 장부와 다음 ROI

| 항목 | 결과 |
|---|---:|
| 신규 STABLE_RECOVERED | 0 |
| FLAKY 후보 | MP03, GM02 |
| strict provisional | 17/57 |
| AAST_FAILURE | 12 (full replay 미실행으로 공식 수치 유지) |
| CAPABILITY_FAILURE | 18 (full replay 미실행으로 공식 수치 유지) |
| DATA_BLOCKED | 10, 변경 없음 |
| RENDER_FAILURE | 0 |
| 기존 STABLE_PASS regression | 0 관찰 |
| WRONG_CONFIDENT | 3, PF01/CN07/ADD40 유지 |

다음 ROI 순위:

1. `DOC02, MP04, MP09, CN08, ADD01, ADD18, ADD38, ADD49`의 projection/canonical field.
   upstream TypedResult에 실제 field가 있는 경우에만 공통 alias contract를 검토한다.
2. `IX02, GM01, ADD16`의 canonical entity/period join alignment.
3. 12 AAST failure의 branch/requirement preservation. typed requirement만으로 결정 가능한
   coverage 보완만 시도한다.

Forecast/외부 evidence와 legacy SSE cancellation은 이번 round의 recoverable QA로 세지
않았다. QA57 full replay 조건(+5 stable recovery 또는 작업 종료)은 충족하지 않았다.

## 6. AAST Cluster Repair Round 2 — trade ranked-country output contract

### 원인

`GM11`의 semantic requirement는 `trade.country_rank`(export)였고, AAST lowering은
`metric=export_amount`, `operation=country_rank`를 생성했다. 기존 Coverage Validator의
metric alias가 import 계열만 포함하여 `METRIC_PRESERVATION_FAILED`를 발생시켰다.
이는 질문/광종 특례가 아니라 `RankedCountrySet` 출력 semantics와 flow별 measure의
공통 equivalence 누락이다.

### 수정

- `inhouse/rag_core/ragkit/aast_coverage.py`
  - country-rank metric equivalence에 `export_share`, `export_value`, `export_amount`,
    `export_weight` 및 `import_weight`를 추가했다.
  - 기존 plain trade time-series 거부 contract는 유지했다.
- `inhouse/rag_core/tests/test_aast_coverage_validator.py`
  - export country-rank typed output contract 회귀 테스트를 추가했다.

### 검증

- validator/lowering targeted: **22 passed**
- `GM11` live fresh session ×3: AAST Coverage Validation **3/3 valid**
- `GM11` 이후 최초 실패: resource branch `row_count=0`, trade branch
  `source_unavailable`; 최종 상태는 `all_roots_failed`.
- 따라서 이번 수정으로 AAST failure는 downstream Capability/Data failure로 이동했지만,
  strict CONTENT_PASS 회복은 **0건**이다.
- 전체 `rag_core`: **1544 passed / 0 failed / 695 subtests / 1 warning**
- 전체 `rag_chat`: **155 passed / 1 known legacy contract failure / 15 subtests**
- 기존 sentinel regression: **0건**
- 신규 `STABLE_RECOVERED`: **0건**, strict provisional은 **17/57 유지**

18012 검증 이미지: `komir-rag-chat:qa-contract-r24-20261003`,
image digest `sha256:56b99bfca73fee1d...` (전체 digest는 실행 로그/컨테이너 metadata에 보존).
18002는 변경하지 않았다.

### 다음 ROI

 다음 공통 후보는 `CN01/CN09` 등에서 반복되는 unreachable intermediate branch와
composition operator coverage다. 다만 deterministic하게 하나의 연결이 결정되는지 먼저
확인해야 하며, GM11처럼 source/data failure로 이동한 항목은 AAST 회복으로 CONTENT_PASS를
추정하지 않는다.

## 7. 남은 AAST 재정렬

GM11을 `AAST_RECOVERED_PENDING_REPLAY`로 분리한 뒤 남은 11건은 다음과 같이
재분류했다. 전체 replay 전이므로 공식 AAST count는 변경하지 않는다.

| Cluster | QA | 공통 contract | 회복성 | 위험 |
|---|---|---|---|---|
| COMPOSITION_OPERATOR / unreachable branch | CN01, CN09 | 중간 aggregate/date/news branch의 root 연결 | 낮음~중간 | 높음 |
| REQUIREMENT/PLAN generation | MP07, REG05 | typed requirement가 있으나 candidate AAST 미생성 | 불명확 | 높음 |
| MULTI-BRANCH selection | GM14 | price와 import-share branch 보존 | 가능성 있음 | 높음 |
| DERIVED metric boundary | ADD06 | price + YoY/변화율 output 보존 | 단일 | 중간 |
| DEPENDENCY binding | ADD25 | upstream result availability/binding | source 의존 | 높음 |
| NAVIGATION routing | ADD45, ADD46 | 데이터 AAST가 아닌 resource navigation route | 서로 다른 route | 중간 |
| COMPOSITION/unsupported | IX01, ADD32 | indicator/news 또는 문서 조합 지원 범위 | 불명확 | 높음 |

따라서 GM11 외에 동일 deterministic contract가 2건 이상 확정된 cluster는 아직 없다.
CN01/CN09는 표면상 branch 누락이지만 실제로는 서로 다른 unreachable graph가 필요하고,
MP07/REG05/ADD45/ADD46은 planner 또는 gate 계층 문제라 이번 AAST preservation contract로
안전하게 묶지 않았다. 질문별 repair나 새 operator를 도입하지 않고 보류한다.

현재 관측 기준:

- `AAST_LAYER_RECOVERED`: GM11 1건(다음 full replay 대기)
- `STABLE_RECOVERED`: 0건
- `FLAKY_AAST`: 기존 MP03, GM02
- 공식 `AAST_FAILURE`: 12건 유지(전체 replay 전)
- 예상 잔여 AAST: 11건 + GM11 replay 대기

## 8. CN01 / CN09 / GM14 composition trace audit

코드 수정 없이 18012 r24에서 fresh session으로 각 1회 trace했다.

| QA | Requirements / outputs | AAST roots / branches | 최초 causal failure | 분류 |
|---|---|---|---|---|
| CN01 | `price_series + period_extrema(value,date)` 및 `document.retrieve` | roots=`max_price_date, news_search`; `price_data_nickel→max_price_date`, `news_search`; `price_change_data`는 root 연결 없음 | 요구사항에 없는 `price_change_data`가 생성되어 `BRANCH_COVERAGE_FAILED: unreachable node` | BRANCH_OVERGENERATION / graph reachability |
| CN09 | `indicator.series + period_change` 및 `document.retrieve` | `idx_series_retrieval→idx_change_calc→idx_drop_filter→news_retrieval`, root=`news_retrieval` | `period_change` upstream이 `change_pct`를 산출한다는 보장이 없는데 filter가 해당 field를 요구하여 `ast_incomplete` | OUTPUT_TYPE_MISMATCH / typed field contract |
| GM14 | `price(current, strategic)` 및 `trade.concentration(import, KR)` | price/concentration 각각 project 후 `join_results→final_projection` | `trade.concentration` output에 `import_share`가 없는데 projection이 요구하여 `ast_incomplete` | OUTPUT_TYPE_MISMATCH / projection contract |

### Reachability 및 공통성 판정

- CN01은 branch가 과잉 생성된 뒤 root에 연결되지 않은 경우다. 요구 branch 누락이
  아니라 불필요 branch 제거 또는 graph 생성 문제다.
- CN09는 모든 node가 root에서 reachable하지만 indicator calculation의 output schema와
  filter field가 불일치한다. root coverage 문제가 아니다.
- GM14도 graph는 reachable하지만 concentration의 실제 typed output과 projection 요구가
  불일치한다. CN09와 표면적으로는 output mismatch이나 서로 다른 capability schema이며,
  현재 contract만으로 하나의 deterministic repair를 결정할 근거가 없다.

결론적으로 세 QA는 동일한 `Requirement→Branch→Dependency→Composition→Root` 표면을
사용하지만 최초 causal failure는 서로 다르다. 공통 수정 조건(최소 2건 동일 최초 원인,
기존 typed requirement만으로 단일 repair 결정)을 충족하지 않으므로 이번 단계에서는
수정하지 않았다.

- `AAST_LAYER_RECOVERED`: 추가 0건
- `FLAKY_AAST`: 추가 0건
- 기존 `GM11 AAST_RECOVERED_PENDING_REPLAY` 유지
- regression 실행: 코드 변경 없음으로 생략
- 다음 ROI: `MP07 / REG05` plan-generation cluster

## 9. MP07 / REG05 Plan Generation Trace Audit

18012 r24에서 두 QA를 각각 fresh session 3회 실행했다. 두 QA 모두 3/3 동일하게
AAST candidate 생성 후 output-field contract validation에서 중단되었고, Coverage
Validator에는 진입하지 않았다.

### MP07

- 질문: `전략광종 가격 현황 한눈에 보여줘`
- Typed requirement: `domain=price`, `metric=current`, `price_group=strategic`,
  `criterion_mode=REPRESENTATIVE`
- Candidate AAST: `retrieve(domain=price, metric=current, price_group=strategic)`
  → `project(fields=[mineral, price, price_measure_label, price_criterion,
  price_criterion_serial, unit, date])`
- root: `project_price_summary`
- failure: upstream가 `current/entity/evidence/mineral/source`만 제공한다고 판단되어
  `price`, `date`, criterion fields가 미생성으로 판정
- 분류: `OUTPUT_SEMANTIC_TYPE_UNRESOLVED` / canonical capability resolution 누락
- retry: 각 fresh session에서 동일 candidate와 동일 failure

`price_group=strategic`가 존재하므로 단순 `price.series`가 아니라 기존
`price.overview` capability의 output contract가 선택되어야 한다. 현재 AAST boundary는
surface metric `current`를 generic field lookup으로 처리하고 group argument를
capability selection/output schema에 반영하지 않는다.

### REG05

- 질문: `니켈 LME 재고량 알려줘`
- Typed requirement: `domain=inventory`, `metric=latest`, `mineral=니켈`,
  `criterion_mode=REPRESENTATIVE`
- Candidate AAST: `entity(니켈)` → `retrieve(domain=inventory, metric=latest)`
  → `project(fields=[value, unit, date])`
- root: `node_3`
- failure: upstream가 `latest/entity/evidence/mineral/source`만 제공한다고 판단되어
  `value/date`가 미생성으로 판정
- 분류: `OUTPUT_SEMANTIC_TYPE_UNRESOLVED` / inventory latest canonicalization 누락
- retry: 각 fresh session에서 동일 candidate와 동일 failure

기존 registry에는 `inventory.latest`와 `InventoryObservation` output type이 존재하지만,
AST field validator가 surface metric `latest`를 canonical metric `inventory` 및
`inventory.latest` output schema로 정규화하지 않는다. `inventory.series` registry
존재 여부와 별개로 latest plan의 discovery/output contract가 연결되지 않은 상태다.

### 공통성 판정

두 QA는 동일한 저수준 failure pattern을 공유한다.

`surface metric/arguments`
→ `canonical capability resolution`
→ `capability output semantic type`
→ `field validation`

이 경계가 누락되어 `current`와 `latest`가 각각 물리 capability의 output fields로
확장되지 않는다. 공통 수정 후보는 다음과 같다.

- domain/metric/추가 typed argument를 기준으로 canonical capability를 먼저 결정
- canonical capability의 output schema를 field validator에 전달
- `price.current + price_group`은 기존 `price.overview` contract로 연결
- `inventory.latest`는 기존 `inventory.latest / InventoryObservation` contract로 연결

이는 두 QA를 위한 문자열/ID 특례가 아니라 registry-driven output contract resolution이다.
현재 단계에서는 코드 수정하지 않았으며, 다음 iteration에서 이 공통 contract만 최소
수정 대상으로 삼을 수 있다.

### 반복 결과

| QA | Parser/Requirement | Candidate AAST | Plan validation | Validator 진입 | 3회 안정성 |
|---|---|---|---|---|---|
| MP07 | 3/3 | 3/3 동일 | 3/3 실패 | 0/3 | `PLAN_LAYER_FAIL` |
| REG05 | 3/3 | 3/3 동일 | 3/3 실패 | 0/3 | `PLAN_LAYER_FAIL` |

- `PLAN_LAYER_RECOVERED`: 0건
- `STABLE_RECOVERED`: 0건
- `FLAKY_AAST`: 0건
- 기존 `rag_core 1544 passed / 0 failed` 유지
- rag_chat known legacy failure는 이번 분석에서 변경하지 않음
