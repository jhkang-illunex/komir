# Capability Failure Root-Cause Audit — 2026-10-03

## 범위와 검증 상태

- 대상: 이전 Strict Full Validation의 `CAPABILITY_FAILURE` 18건
- 실행 환경: 18012 검증 컨테이너, 새 criterion-contract 이미지
- 운영 18002: 미변경 확인
- 목표: 기존 분류를 최신 trace의 최초 causal contract 기준으로 재분류하고, 공통 recoverable cluster만 수정
- QA57 full replay: 실행하지 않음

기존 18건 중 최신 실행에서 이미 정상 완료된 항목은 Capability failure로 유지하지 않았다. `HTTP 200`이 아니라 action trace, typed-result trace, root failure를 기준으로 판정했다.

## 최신 재분류

| QA | 최신 최초 causal failure | 분류 | 현재 판정 |
|---|---|---|---|
| MI02 | 정상 capability/document 실행 | STALE_CAPABILITY_CLASSIFICATION | 현재 Capability failure 아님 |
| DOC02 | document row에 `title` canonical field가 없음 | OUTPUT_CONTRACT | source output contract gap |
| NEWS03 | document retrieval/table 정상 | STALE_CAPABILITY_CLASSIFICATION | 현재 Capability failure 아님 |
| IX02 | indicator/price branch의 source coverage 및 후속 비교 입력 실패 | SOURCE_ADAPTER / JOIN_ALIGNMENT | source/data 확인 필요 |
| MP04 | `resource.yoy`가 source production row를 결과로 materialize하지 못함 | SOURCE_ADAPTER | Data Audit상 source 존재, recoverable 후보 |
| MP09 | document retrieval evidence validation 실패; price branch는 정상 | SOURCE_ADAPTER / RETRIEVAL_EVIDENCE | evidence contract 확인 필요 |
| CN08 | indicator branch의 `unsupported_calculation_contract` | CALCULATION_CONTRACT | document branch도 별도 retrieval 실패 |
| GM01 | resource/trade branches 정상 실행 | STALE_CAPABILITY_CLASSIFICATION | 현재 Capability failure 아님 |
| GM13 | price branch의 criterion mapping 실패(수정 전); 수정 후 branches 실행 | CRITERION_BINDING | Capability layer recovered, 복합 결과는 strict 미확정 |
| REG02 | `aggregate_order_required` | CALCULATION_CONTRACT | `first/last` order contract 누락 |
| REG06 | price project upstream 실패 | SOURCE_ADAPTER / PROJECTION_CONTRACT | 양쪽 canonical row 존재 여부 추가 확인 필요 |
| ADD01 | 대표 criterion mapping 실패(수정 전) | CRITERION_BINDING | 공통 수정 후 STABLE_RECOVERED 3/3 후보 |
| ADD03 | AAST에서 `max_price_node` root coverage 실패 | AAST_FAILURE | Capability failure 아님 |
| ADD12 | source adapter unavailable | SOURCE_TRANSPORT | backend/source transport 확인 필요 |
| ADD16 | 두 resource result의 ratio alignment 실패 | JOIN_ALIGNMENT | 두 결과의 canonical key/ratio 입력 contract 확인 필요 |
| ADD18 | indicator.series 정상 실행 및 table/chart 생성 | STALE_CAPABILITY_CLASSIFICATION | 현재 Capability failure 아님 |
| ADD38 | price map 결과에서 `mineral` projection field unavailable | OUTPUT_CONTRACT / PROJECTION_CONTRACT | map envelope identity contract gap |
| ADD49 | 대표 criterion mapping 실패(수정 전) | CRITERION_BINDING | 공통 수정 후 STABLE_RECOVERED 3/3 후보 |

### 재분류 요약

- 최신 Capability failure로 계속 남은 항목: 11건
- 이전 Capability failure가 아닌 것으로 확인: 4건 (`MI02`, `NEWS03`, `GM01`, `ADD18`)
- AAST failure로 재분류: 1건 (`ADD03`)
- 공통 criterion cluster로 회복: 3건 (`ADD01`, `ADD49`, `GM13`)
- 나머지는 source/evidence/join/calculation/output contract가 서로 달라 단일 cluster로 합치지 않음

## Root Cause Matrix

| 순위 | Root Cause | QA | 수 | 공통 contract | 예상 회복 | 위험 |
|---:|---|---|---:|---|---:|---|
| 1 | CRITERION_BINDING | ADD01, ADD49, GM13 | 3 | mineral identity → criterion catalog → representative selection | 2 strict + 1 capability-layer | 낮음 |
| 2 | OUTPUT/PROJECTION_CONTRACT | DOC02, ADD38 | 2 | canonical output field와 source envelope의 차이 | source field가 실제 존재하는 경우만 | 중간 |
| 3 | JOIN_ALIGNMENT | IX02, ADD16 | 2 | canonical entity/date/value key와 ratio/compare operands | source key 존재 시 1~2 | 높음 |
| 4 | SOURCE_ADAPTER / TRANSPORT | MP04, REG06, ADD12, MP09 | 4 | source binding, evidence transport, document validation | source 존재 확인 후 | 중간~높음 |
| 5 | CALCULATION_CONTRACT | CN08, REG02 | 2 | period change 및 ordered aggregate operand | 0~2 | 중간 |
| 6 | AAST_FAILURE | ADD03 | 1 | aggregate/arg-max branch root coverage | 이번 iteration 제외 | 중간 |

동일 최초 causal failure가 확인된 3건은 criterion cluster뿐이었다. Projection, join, source, calculation 항목은 표면 증상이 비슷해도 최초 실패 boundary가 달라 이번 iteration에서 억지로 공통화하지 않았다.

## 적용한 공통 수정

### Criterion catalog fallback

가격 Capability가 사용하는 `resolve_price_criterion_serials()`에서:

1. `ai_prc_mnrl_map`을 우선 사용
2. 해당 snapshot에서 매핑 projection이 비어 있으면 `KO_MNRL_PRC_CRTR`의 광종-criterion 관계 사용
3. 짧은/legacy mineral code는 `ai_mnrl_mst`의 canonical Korean name으로 catalog를 재조회
4. 대표 기준 선택은 기존 representative registry와 metadata 일치로만 수행
5. source에 없는 기준을 생성하거나 첫 행을 임의 선택하지 않음

대표 registry에는 surface name `리튬`을 canonical representative criterion `99.5%min CIF China`로 추가했다. 이는 질문/QA 특례가 아니라 기존 대표가격 resource의 canonical alias 보완이다.

### 검증 결과

- 관련 unit: `18 passed`
- 전체 common + rag_core: `1574 passed, 1 warning, 697 subtests`
- rag_chat: `155 passed, 1 known legacy failure, 15 subtests`
- ADD01: fresh 3/3 success, table 3/3
- ADD49: fresh 3/3 success, table 3/3
- GM13: fresh 3/3 execution success, table 4/4; strict content는 복합 document 결과 품질 때문에 `CAPABILITY_LAYER_RECOVERED`로만 기록
- sentinel: MP07 success, REG05 success, GM02 success, ADD27 success
- 기존 18002 image/digest: 변경 없음

## Recovery ledger

- `STABLE_RECOVERED` 후보: `ADD01`, `ADD49` (+2)
- `CAPABILITY_LAYER_RECOVERED`: `GM13` (+1; strict 승격 아님)
- `FLAKY`: 이번 대상에서는 확인되지 않음
- `UNRECOVERED`: DOC02, IX02, MP04, MP09, CN08, REG02, REG06, ADD12, ADD16, ADD38
- 잠정 strict: 기존 `19/57`에 +2 후보 → `21/57` 잠정

이번 iteration에서 QA57 full replay를 하지 않았으므로 공식 strict baseline은 변경하지 않는다.

## 제외 및 다음 ROI

- `DATA_BLOCKED/SOURCE_BLOCKED` 후보: IX02, REG06, ADD12, MP09는 source/evidence 직접 확인 전 수정하지 않음
- `DOC02`, `ADD38`: canonical output field가 실제 upstream에 존재하는지 확인 전 projection 완화 금지
- `ADD16`, `IX02`: 양쪽 결과에 공통 canonical key가 있다는 증거 전 positional join 금지
- `CN08`, `REG02`: calculation contract가 기존 operator로 유일하게 표현되는지 확인 후 별도 처리
- `ADD03`: AAST branch/root coverage cluster로 분리

다음 ROI 순서는 (1) `DOC02/ADD38`의 실제 canonical field 존재 여부, (2) `REG02/CN08` calculation contract, (3) `ADD16` canonical ratio alignment이다. Source/evidence가 확인되지 않으면 코드 수정 대신 Data/Evidence blocked로 유지한다.

## Complexity Delta

- Files changed: `inhouse/common/komis_raw.py`, `inhouse/common/tests/test_komis_raw_aggregation.py`, `inhouse/rag_core/ragkit/resources/representative_price_criteria.yaml`, `inhouse/rag_core/tests/test_price_criterion_cardinality.py`
- New classes: 0
- New public contracts: 0
- New registry entries: 0; existing representative registry entry 1개 보완
- New special-case branches: 0
- New central-dispatch branches: 0
- Removed branches: 0
- Duplicated contract sources added: 0
- Duplicated contract sources removed: 0
- Largest modified method LOC: `resolve_price_criterion_serials()` 약 40 LOC 수준
- Largest modified class LOC: 기존 `KomisRawDataRepository` (기존 클래스, 책임 추가는 source-boundary 내부로 제한)
- Largest modified module LOC: 기존 `inhouse/common/komis_raw.py`
- Responsibility growth detected: false
- Verdict: `COMPLEXITY_PASS` (기존 legacy alias/renderer mapping 중복은 `REFACTOR_CANDIDATE`로 유지)

## Contract Delta

- New contracts: 없음
- Modified contracts: source-side mineral→price-criterion resolution fallback; representative registry surface alias
- Removed contracts: 없음
- Canonical source of truth: `ai_prc_mnrl_map` 우선, snapshot projection 부재 시 `KO_MNRL_PRC_CRTR` + `ai_mnrl_mst` 관계
- Consumers: price source adapter, `price.series`, `price.overview`, Direct/AAST 공용 executor
- Duplicated mappings remaining: legacy renderer/alias mappings 일부 존재; 이번 수정에서 추가하지 않았으며 `DUPLICATED_CONTRACT_SOURCE`/`REFACTOR_CANDIDATE`로 추적

`QA-specific branch = 0`, `question-string branch = 0`, `entity-specific execution branch = 0`, `answer hardcoding = 0`.
