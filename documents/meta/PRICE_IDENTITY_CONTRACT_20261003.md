# Price Identity Output Contract Audit

작성일: 2026-10-03

## 검증 범위

- 검증 환경: 18012 only
- 운영 18002: 변경 없음 (`komir-rag-chat:deploy-price-representative-r1`, running)
- source HEAD: `fa423722caeb86bfb83e6561e3b355b20da2ef38`
- 검증 이미지: `komir-rag-chat:price-identity-r2-20261003`
- image digest: `sha256:e2f10adf60368fe502256ecc4a528ae06186fc9f268bbb3af109da5feeb7038c`
- container: `komir-rag-chat-price-identity-r2`
- container id: `87cb212d4ce533b6ac9ab2006ba5d18b2c1461f6babc096bb0ce97159a361b89`

QA57 full replay는 수행하지 않았다.

## 최초 원인

대표/명시 criterion의 source adapter가 선택된 가격 기준을 `unit` 메타데이터에만 남기고 canonical row field로 materialize하지 않았다. 그 결과 `price.series`의 TypedResult/projection 단계에서 값·날짜는 유지되지만 최종 table에는 가격 기준 identity가 빠질 수 있었다.

반면 `ALL` 경로는 이미 `price_measure`, `price_criterion`, `price_measure_label`, `price_criterion_serial`을 row에 확장하고 있었다. 즉 criterion mode별 source output contract가 일관되지 않았다.

## 적용한 공통 contract

`semantic_capabilities.CAPABILITY_ARGUMENTS`를 capability output contract의 기준으로 확장했다.

가격 capability에 다음 metadata를 선언했다.

| Capability | canonical metric | output type | criterion modes | identity fields |
|---|---|---|---|---|
| `price.overview` | `price` | `PriceOverview` | REPRESENTATIVE / EXPLICIT / ALL | `price_measure`, `price_criterion`, `price_measure_label`, `price_criterion_serial` |
| `price.series` | `price` | `PriceSeries` | REPRESENTATIVE / EXPLICIT / ALL | 동일 |

선택된 REPRESENTATIVE/EXPLICIT criterion은 source adapter 경계에서 canonical row fields로 materialize한다. 이후 기존 TypedResult와 projection이 같은 identity contract를 소비한다. `ALL`의 실제 source criterion/measure cardinality는 기존 확장 경로를 유지한다.

추가된 동작은 source에 실제 criterion metadata가 있는 경우에만 field를 추가하며, 없는 identity를 생성하지 않는다.

## 검증 결과

### MP07

질의: `전략광종 가격 현황 한눈에 보여줘`

| 반복 | 실행 | abstained | identity columns | 결과 |
|---:|---|---|---|---|
| 1 | 성공 | false | `price_criterion`, `price_measure_label` | 회복 |
| 2 | 성공 | false | `price_criterion`, `price_measure_label` | 회복 |
| 3 | 성공 | false | `price_criterion`, `price_measure_label` | 회복 |

표에 실제 기준 identity가 유지되었고, 관측된 기준은 LME CASH, 페로망간, -194 FOB China, 산화네오디뮴/디스프로슘/란탄/세륨/터븀이다.

판정: `STABLE_RECOVERED 3/3` (가격 identity strict blocker 기준)

### Price mode probes

| Mode | 질의 유형 | 결과 |
|---|---|---|
| REPRESENTATIVE latest | 오늘 니켈 가격 | 대표 기준 LME CASH 유지, 성공 |
| REPRESENTATIVE series | 최근 1년간 니켈 가격 추이 | 시계열 13행과 `price_criterion`/`price_measure_label` 유지, 성공 |
| EXPLICIT | 최근 1년간 니켈 LME CASH 가격 추이 | 단일 LME CASH series와 identity 유지, 성공 |
| ALL | 최근 1년간 니켈 모든 가격 추이 | 39행(13개 시점 × 최저/최고/통상), `price_measure`/criterion identity 유지, 성공 |

ALL은 대표가격으로 축약되지 않았고, REPRESENTATIVE/EXPLICIT은 복수 criterion으로 확장되지 않았다.

## 회귀 검증

- 가격/identity 관련 targeted tests: `84 passed`, `11 subtests passed`
- `rag_core`: `1551 passed`, `0 failed`, `695 subtests passed`, 1 기존 warning
- `rag_chat`: `155 passed`, `1 known legacy contract failure`, 15 subtests
- known legacy failure: `test_disconnect_stops_real_ast_retry_before_blocking_invocation_returns[legacy_control-False]` (legacy control retry count 4 vs 기존 기대 3)
- 기존 stable sentinel: 이번 price probe 및 회귀 suite에서 신규 regression 없음

## Complexity Delta

- 이번 iteration 수정 파일: `semantic_capabilities.py`, `live_multihop.py`, `_mcp_tools_common.py`, 관련 price tests
- New special-case branches: 0
- New central-dispatch branches: 0
- New registry entries: `price.series` contract spec 1개; 기존 `price.overview` metadata 확장
- New public contracts: 기존 registry spec metadata(`canonical_metric`, `output_type`, `criterion_modes`, `identity_fields`) 확장
- Duplicated contract sources added: 0
- Duplicated contract sources removed: source adapter의 criterion materialization 누락 1개 경로 제거
- Responsibility growth: 없음. source identity materialization은 source adapter boundary에, output identity 선언은 registry에 두었다.
- Largest modified method/class/module: 이번 변경으로 구조적 threshold 초과를 새로 만들지 않음
- Architecture status: `COMPLEXITY_WARN`

기존 중복 source는 남아 있다. `live_multihop`의 legacy field alias와 renderer의 표시 alias가 registry identity metadata와 병존하므로 `DUPLICATED_CONTRACT_SOURCE` 경고 및 장기 `REFACTOR_CANDIDATE`다. 이번 release-critical 수정에서 대규모 통합 refactor는 수행하지 않았다.

## Contract Delta

- Modified contracts: `price.overview`, `price.series` output identity contract; representative/explicit source row canonicalization
- Canonical source of truth: `semantic_capabilities.CAPABILITY_ARGUMENTS`의 capability spec
- Consumers: semantic IR output fields, live TypedResult/projection, source adapter canonical row materialization
- Remaining duplicated mappings: legacy `_resolve_row_field`/`_CANONICAL_FIELD_ALIASES`, presentation renderer aliases
- Renderer architecture: 변경하지 않음

## 다음 blocker

가격 identity는 MP07과 주요 price mode probe에서 회복됐다. 남은 작업 후보는 가격 identity와 무관한 기존 QA57 AAST/Capability/Data blocker이며, 이번 iteration에서는 다루지 않았다.
