# Step 8 — Source-result adapter: indicator row subset

## Acceptance

**PASS_SCOPED_INDICATOR_ROW_ADAPTER_PARITY**

`indicator.series`의 source row 정규화와 기존 `IndicatorSeriesRow` 검증만 독립 component로 이동했다. 전체 source-result adapter migration 완료를 의미하지 않는다.

- row normalization/validation differential **412/412 동일**.
- raw RetrievalResult → TypedResult differential **11,536/11,536 동일**.
- 미이관 capability control **12/12 동일**.
- 저장 graph **2/2 동일**: IX02, CN08. CN08의 `unit_unavailable` 유지.
- targeted **293 passed / 3 subtests**, 신규 characterization **74 cases**.
- rag_core **1829 passed / 0 failed / 695 subtests** = Step 7의 1755 + 신규 74.
- rag_chat **155 passed / 동일 known legacy failure 1건 / 15 subtests**.
- 의미 계약·source query·Catalog·Planner·계산·Projection·History·Renderer 변경 0.
- Full QA57, Strict 갱신, Step 9, 이미지 빌드/배포, commit/push는 수행하지 않았다.

## 1. Source / evidence identity

| 항목 | 값 |
|---|---|
| git parent | `979fd3f980bb10af74a218cc6e07bada110e76de` |
| 실제 기준 | Steps 1–7 누적 dirty source. clean Golden HEAD라고 표시하지 않음 |
| pre-Step8 live SHA256 | `a144eb1b9f4bb2f42b06fb4e98ccd757180adc4b612067d8d55f95356fa8a3ae` |
| post-Step8 live SHA256 | `f63227d157bbdb95e9e007246910c146aa94c996c09d82f5cc70a1ad6c2bf74e` |
| 새 indicator adapter SHA256 | `919d5cac428c372b21b546637aeb3b15343dac0b42094efcdf9d89a1ccd78e28` |
| 18012 | 기존 `komir-temporal-step7`, `komir-rag-chat:temporal-step7-20261003` 유지 |
| 18012 image ID | `sha256:2213f8fcc6dcf3b1cfcb98145d474a82c326f7c0c67f65d1628f95a52f35eb6c` |
| 배포 상태 | 이번 수정은 **host source / offline deterministic 검증만 완료**. 18012 이미지에 반영되었다고 주장하지 않음 |
| 보호 확인 | 18002와 18012의 ID/image/Created/StartedAt/mount 속성/config hash 전후 동일 |
| 불변 근거 | Step 7 sealed evidence 45개 모두 SHA256 일치 |
| Step 7 manifest SHA256 | `f5003347c5f41531cf1a60b9070ac618a20a3487933b09edad29c2ad65a926a3` |
| Step 8 evidence | `/home/nuri/.codex/validation-evidence/adapter-step8-20261003` |

Behavioral Reference V1과 `NOT_CERTIFIED_WITH_KNOWN_REASONS`를 유지한다. 개발용 evidence, 불완전 기간, unit 부재를 개선·인증하지 않는다. source/DB 조회·수정과 모델 재호출은 없다.

## 2. Pre-change audit / ownership

iterative-audit의 HIGH source boundary 검증과 Architecture/Complexity/Regression/Decomposition Guard를 적용했다. qa-build는 deterministic characterization에만 사용했다. 이전 QA backlog는 이번 scope가 아니다.

| 사전 질문 | 근거 / 결정 |
|---|---|
| 현재 책임 / 소속 적합성 | live의 공통 envelope 조립과 indicator physical decoding이 혼재. 물리 필드 해석은 dedicated adapter 소속이 적절 |
| semantic owner | 기존 `IndicatorSeriesRow` + 기존 normalization body. 새 semantic schema를 만들지 않음 |
| 기존 seam | `_typed_from_retrieval` 안의 row-normalize / row-validate pure helper 두 곳 |
| LegacyResultAdapter 검토 | `legacy_bridge.LegacyResultAdapter`는 raw/action→TypedResult callable. 기존 live 변환 진입점을 유지하고 그 내부 subset만 이관. `LegacyActionStep` 교체는 I/O/Step migration까지 확대되므로 하지 않음 |
| 새 개념 / 두 번째 정본 | 없음. helper 본문을 원위치에서 제거; shared resolver/numeric 함수는 그대로 주입 |
| 재사용성 | indicator 종류·QA·질문과 무관한 기존 row 계약. 새 alias나 단위 추론 없음 |
| 중앙 분기 증가 | 없음. 기존 두 indicator 선택 지점은 그대로 위임 |
| 구조 변경 필요 | physical alias decoding·row validation의 failure owner를 단독 모듈로 식별할 수 있게 하는 승인된 좁은 extraction |

## 3. Adapter responsibility inventory — 이동 전 실제 동작

아래는 이상적인 schema가 아니라 **현재 live 변환이 실제로 만드는 결과**다. Registry의 semantic 이름과 TypedResult metric/ValueType의 차이도 그대로 기록한다. physical column은 원본 Evidence markdown table에서 읽으며, source 구조 자체는 바꾸지 않는다.

### 3.1 공통 처리 계약 E (모든 subset에 적용)

1. 첫 `ActionResult`의 evidence가 있으면 우선, 없으면 top-level evidence 사용. 뒤 action을 새로 병합하지 않음.
2. Evidence.text의 표를 `_rows`로 읽고 `_canonicalize_row` 수행. 기존의 두 차례 canonicalization을 그대로 유지.
3. canonical key가 이미 있으면 null이더라도 덮어쓰지 않음. source key와 unknown column 보존.
4. `value`가 없으면 공통 price→inventory→production_volume→reserves_volume→import_value 우선순위 유지.
5. action status가 success가 아니거나 evidence가 없으면 `TypedResult.empty`; PARTIAL/FAIL 문자열도 이 경계에서는 EMPTY가 될 수 있음. 이를 새 정책으로 고치지 않음.
6. public failure allowlist는 기존 resource population / price criterion 코드만 통과. 나머지 `retrieval unavailable: {status}`. evidence/warnings 보존, success용 entity/metric/period/unit/source/provenance를 실패 결과에 새로 추가하지 않음.
7. 성공 시 input entities→row entity→slots mineral(s), 기존 alias/dedup. period는 slots의 JSON을 사용.
8. unit은 첫 truthy Evidence.unit의 `_typed_unit` 결과. row unit과 상충해도 새 reconciliation 없음. unit이 없으면 None.
9. source는 evidence.source 순서 보존 dedup, provenance는 requirement ID + source_id/source. dummy도 그대로 보존.
10. evidence는 있지만 table rows가 없으면 성공 payload가 Evidence 목록으로 fallback. cardinality를 임의로 줄이지 않음.

### 3.2 Domain/capability별 field / type inventory

| Subset | Physical → canonical fields | 실제 TypedResult metric / ValueType | Semantic output / cardinality |
|---|---|---|---|
| **indicator.series** | date/crtr_ymd/obs_date/observed_date/period → date; series/indx/center → value; indicator 없을 때 slots.indicator | `indicator` / TIME_SERIES | Registry IndicatorSeries; row 수·순서 보존, invalid row 삭제 없음, E의 evidence fallback |
| trade.country_rank | country·share가 있는 표 우선; 유일 total/총계 → 선언된 import/export_amount/weight. 공통 country/share_pct alias도 적용 | slots.metric / COUNTRY_SHARE | Registry CountryShare, canonical_metric=country_share와 runtime 측정 metric이 서로 다른 표현; 선택된 국가 rows |
| resource.rank | total/총계 → production_volume 또는 reserves_volume; 선언된 metric field → value(없을 때만); year/country/mass aliases | production 또는 reserves / FACT_SET | Registry ResourceRanking; country population/rank rows. 후단 country filter 별도 |
| resource.yoy | 자체 local 변환 없이 공통 aliases와 원본 year/prior_year/tonnes/change_pct 등 보존 | slots.metric / FACT_SET(default) | Registry ResourceChange/resource_yoy와 runtime metric/type 표현 차이 잔존 |
| inventory.latest / series | invt/재고/재고량/quantity → inventory → value, 공통 date aliases | inventory / FACT_SET 또는 TIME_SERIES | Registry output fields 선언. 이 변환기 자체는 latest를 단건으로 강제하지 않음 |
| trade.monthly | 공통 date/country/import_value aliases, 나머지 원본 source columns | slots.metric 또는 trade_metric / TRADE_SERIES | series rows; 독립 date alignment/집계는 여기서 하지 않음 |
| trade.concentration / trade.indicator | 공통 aliases 외 HHI/CRn/indicator source 표를 임의 새 필드로 만들지 않음 | slots.metric 또는 trade_metric / FACT_SET(default) | 원본 표 cardinality 유지. ConcentrationMetric을 CountryShare로 변경하지 않음 |
| price.series / overview | cmerc_prc/통상가격/latest_price → price; criterion label/serial alias; date, 선언된 price→value | price / TIME_SERIES 또는 FACT_SET | PriceSeries/PriceOverview; source criterion별 rows. latest 후처리는 별도 |
| price.volatility_rank / 기타 action | 공통 alias만 적용; 별도 physical normalization 없음 | slots.metric 또는 trade_metric / MINERAL_RANKING(나머지는 default FACT_SET) | 원본 rows / E fallback; runtime default를 개선하지 않음 |
| forecast.price | 공통 alias만; forecast physical fields는 원본 그대로, temporal operator가 소비 | price_forecast / FACT_SET(default) | forecast rows; provenance/observed boundary 검증 강화 없음 |
| document.retrieve / lookup | Evidence markdown에서 공통 mineral/country/date 등; 없던 title/field 생성 안 함 | slots.metric 또는 trade_metric / DOCUMENT_EVIDENCE | rows 또는 Evidence 목록. source document extraction은 별도 |

### 3.3 Unit / identity / entity / evidence / failure inventory

모든 행은 E의 status/source/provenance 규칙을 상속한다.

| Subset | Unit / identity / entity | 추가 failure / post-processing |
|---|---|---|
| indicator | row.unit은 원본 보존, envelope.unit은 E. indicator는 기존 값 우선. price criterion 해석 안 함. entity는 E | `IndicatorSeriesRow.model_validate`; 실패 `indicator_output_contract_invalid`→EMPTY. 검증된 모델값으로 rows를 대체하지 않음. `_call_action`의 period_change→endpoint_change는 미이관 |
| trade country rank | 금액/중량 단위는 E; country identity와 typed metric 보존. total이 복수면 추측하지 않음 | country/share 표 selection과 typed total binding 잔존; 파생 share 생성 안 함 |
| resource rank / yoy | source mass/year/country, E unit·entity. population completeness 결정 안 함 | public resource failure 코드 보존; country alias filter/fail-closed 후처리 잔존 |
| inventory | source basis/physical columns/row.unit 보존, mineral E; price criterion 정책 없음 | latest vs series ValueType만 다름; source query/cardinality/filter 미변경 |
| trade monthly / concentration / indicator | country/scope/period/원본 unit; 의미 변환 없이 E | downstream join/calculation 문제를 여기서 보정하지 않음 |
| price | REPRESENTATIVE/EXPLICIT/ALL selection은 기존 upstream contract. label/serial/measure/unit identity + E | `_call_action` latest as_of 필터·max date 및 row status/reason/output 보충 잔존 |
| forecast | source/provider/forecast fields 및 evidence 원형. E unit | DEV_DUMMY 포함 provenance 동작 보존. period/criterion 보강 안 함 |
| document / default actions | evidence source/section/caveat, 공통 alias가 읽은 row entity + slots | 빈 표와 source 0-row 구별 정책 E 유지. `_foreach` document→MineralSet 처리 잔존 |

### 3.4 Source/action-specific post-processing 잔존

`LiveOperatorFactory._call_action`: ActionSlots/ActionPlan 구성, price volatility 기본 population, document topic/history 처리, source 호출, indicator endpoint calculation, resource country filter, price latest row selection과 row annotations.

`_retrieve` / `_foreach`: upstream entity binding, multi-entity source fan-out, result merge, explicit failed-item rows, PARTIAL/FAILED/sufficient, unit/source/provenance merge. 이번 extraction과 별개이며 그대로 유지했다.

## 4. Migration 후보 위험도와 선택

| 순위 | 후보 | 상대 위험 | 결정 |
|---|---|---|---|
| 1 | indicator row normalization + row validation | LOW/MEDIUM 단일 subset, 전체 source 경계는 HIGH | **선택**. 기존 typed row, 2개의 순수 함수 seam, criterion 정책 없음, raw differential 구성 가능 |
| 2 | trade.country_rank total binding / table membership | MEDIUM/HIGH | total/shared share/country resolver 정책 결합. resource의 total과 같은 이름이어도 의미가 달라 별도 검증 필요 |
| 3 | inventory latest/series envelope | MEDIUM | mapping이 공통 alias에 대부분 포함. 독립 body가 작아 지금 떼면 공통 envelope/alias 복제가 생길 위험 |
| 4 | resource rank/yoy | HIGH | official population, year/unit/country, value binding과 known blocker가 얽힘 |
| 5 | trade monthly/concentration/indicator | HIGH | 공통 envelope·semantic catalog/type 표현 차이. metadata ownership과 혼합 이관 금지 |
| 제외 | price/forecast | HIGH | criterion/cardinality/unit/provenance 정책 때문에 첫 subset에서 제외 |
| 제외 | complex document/default fallback | HIGH | rows/Evidence dual payload·entity extraction·failure 정책 때문에 제외 |

indicator의 physical value fallback 우선순위는 이 action의 기존 규칙이다. 공통 date/series alias resolver 자체를 새로 정의하거나 이동하지 않고 callback으로 재사용하므로 다른 capability의 alias 의미를 소유하지 않는다.

## 5. Mechanical extraction

```text
RetrievalResult + ActionCall
  → existing common evidence/table canonicalization
  → indicator_result_adapter.canonical_indicator_rows
  → existing status / evidence guard
  → indicator_result_adapter.validate_indicator_output
  → existing common TypedResult envelope
  → unchanged _call_action post-processing / PipeRuntime
```

- 새 파일: `inhouse/rag_core/ragkit/indicator_result_adapter.py`.
- 정규화와 validator의 원래 호출 순서를 그대로 보존했다.
- `resolve_field` / `numeric`은 기존 함수를 주입한다. reverse import나 새 alias table 없음.
- `IndicatorSeriesRow`가 row validation 정본이다. date/calendar 엄격성, bool/NaN coercion 등 기존 허용 동작을 강화하지 않았다.
- canonical date/value/indicator가 있으면 그대로 우선. invalid rows도 삭제하지 않음.
- `_typed_from_retrieval`의 공통 typed envelope·type/metric map은 그대로 유지했다.
- 기존 private helper 테스트 3곳은 새 함수로 import/call만 변경하고 assertion은 유지했다.
- `LegacyResultAdapter`/StepFactory/PipeRuntime interface, Registry entries 변경 없음.

## 6. Verification / limits

### Deterministic old/new

`live_multihop.before.py`는 이 작업 직전 source 복사본이다. HEAD나 이전 Golden 구현으로 비교 대상을 바꾸지 않았다.

| 검사 | 결과 | 범위 |
|---|---:|---|
| normalization/validation | 412 동일 | missing/null/canonical 우선, physical·annotated field, 유효/무효 date, numeric/zero/NaN/inf, mixed·empty rows |
| raw→TypedResult | 11,536 동일 | 103 row cases × 7 status × 4 unit × 4 evidence/action 선택. 값/status/failure/metadata/warnings/provenance 포함 |
| 다른 capability control | 12 동일 | 선택하지 않은 price/trade/inventory/resource/forecast/document action의 변환 경로 |
| saved graph | 2 동일 | IX02 Step6 저장 graph, CN08 Step0 저장 graph; indicator `_retrieve→_call_action`→adapter→후단까지 실행 |
| AST parity | 5 assertions 통과 | 정규화 body 이름 치환 후 동일, validator 동일, envelope delegation 원복 후 동일, 나머지 모든 함수/클래스 동일, legacy 두 함수 제거 |

raw/graph harness는 network connect를 차단한다. old/new 결과의 JSON 구조를 비교하며, 이 비교만으로 tuple/list 구분 또는 모든 객체 identity 동일성을 주장하지 않는다. 신규 characterization은 row shallow-copy, 원본 불변, Evidence 객체 동일성, 숫자/string 타입 유지도 별도로 검증한다.

**saved graph 한계:** 저장된 Evidence text/metadata에서 `RetrievalResult(status=success)` fixture를 재구성했다. 원본 source raw status 재현이나 source query replay가 아니다. 다른 domain upstream은 저장 TypedResult로 고정했다. old/new 양쪽에 같은 reconstruction을 제공한 parity이며, saved response 전체가 새로 strict 통과했다는 뜻이 아니다.

IX02 graph의 old/new 최종 성공, CN08의 indicator `unit_unavailable` 및 최종 `all_roots_failed`가 동일했다. 기존 historical artifact의 다른 실행 status와 혼합하여 recovery를 계산하지 않는다.

### Regression commands / results

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:inhouse:inhouse/rag_chat python3 validate.py diff
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:inhouse:inhouse/rag_chat python3 validate.py graphs
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:inhouse:inhouse/rag_chat python3 -m pytest -q -p no:cacheprovider inhouse/rag_core/tests/test_indicator_result_adapter.py inhouse/rag_core/tests/test_live_multihop.py inhouse/rag_core/tests/test_live_parser_contract_feedback.py inhouse/rag_core/tests/test_live_audit_safety.py inhouse/rag_core/tests/test_qa500_series.py
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:inhouse:inhouse/rag_chat python3 -m pytest -q -p no:cacheprovider inhouse/rag_core/tests
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:inhouse:inhouse/rag_chat python3 -m pytest -q -p no:cacheprovider inhouse/rag_chat/tests
git diff --check
```

validate.py/measure.py는 evidence directory에 저장했다. repository root에서 해당 파일의 절대 경로로 실행한다.

- targeted 293 passed / 3 subtests, 2.31s.
- rag_core 1829 passed / 695 subtests, 41.83s. 기존 Pydantic `lifespan` warning 1 유지.
- rag_chat 155 passed / 1 failed / 15 subtests, 6.49s. known ID: `test_sse_cancellation.py::test_disconnect_stops_real_ast_retry_before_blocking_invocation_returns[legacy_control-False]`.
- QA corpus 추가 0, QA recovery 0, Full replay 0, live model 요청 0. synthetic boundary case는 테스트 전용이며 production 데이터에 추가하지 않았다.
- 독립 read-only 감사: material High/Critical finding 0. 검증을 product certification·미이관 domain 전체 보증으로 확대하지 않음.

## 7. Before / after structural accounting

동일 AST span 기준. source-specific 선택 if는 제거하지 않고 위임하므로 central operator 조건 수는 감소하지 않는다.

| 지표 | Before | After | 변화 |
|---|---:|---:|---:|
| live_multihop.py LOC | 2928 | 2873 | −55 |
| LiveOperatorFactory LOC | 493 | 493 | 0 |
| _derive LOC | 164 | 164 | 0 |
| _typed_from_retrieval LOC | 118 | 120 | +2, 명시적 callback 호출 formatting |
| central operator conditions | 6 | 6 | 0 |
| live AST if count | 383 | 375 | −8; 의미 제거가 아니라 adapter로 이동 |
| indicator 전용 legacy 함수 span | 44 + 10 | 0 | −54 |
| dedicated adapter module LOC | 0 | 75 | +75, 설명/import/type signature 포함 |
| dedicated adapter 함수 span | 0 | 48 + 10 | +58 |
| adapter if count | 0 | 8 | 이동된 기존 조건 |
| live 넓은 책임 범주 | 12 | 12 | source adapter 범주 전체가 비워지지 않았으므로 감소 주장 안 함 |
| Factory 넓은 책임 범주 | 8 | 8 | source invocation/후처리 미이관 |
| live의 indicator row 물리해석 + row 검증 책임 | 2 | 0 | dedicated adapter가 2개 세부 작업을 하나의 row adaptation 책임으로 소유 |

failure owning boundary는 새 파일에서 직접 확인할 수 있다. source table decoding 실패와 공통 envelope 실패는 여전히 별도 위치다. 새로운 domain의 자동 등록 구조를 완성했다고 주장하지 않는다. 현재 generic orchestration은 이 indicator subset의 `indx/center` 값 선택 알고리즘을 직접 소유하지 않으며, source 선택·shared alias/metadata 지식은 남아 있다.

## 8. Complexity Delta

| 항목 | 변화 |
|---|---|
| Files changed | production 2, tests 2, 신규 artifact 1. 기존 dirty Step1–7 파일을 이번 변경으로 집계하지 않음 |
| New classes | 0 |
| New public contracts | 외부 semantic/public schema 0; 내부 pure callable 경계 2개 relocation |
| New registry entries | 0 |
| New special-case branches | QA/question/entity 0 |
| New central-dispatch branches | 0 |
| Removed branches | live 내부 indicator 조건 8개 이동; 중앙 선택 분기 삭제 0 |
| Duplicated contract sources added / removed | 0 / 0. 실행 본문의 기존 위치는 제거했으나 기존 alias 중복 debt를 해결한 것은 아님 |
| Largest modified function LOC | `_typed_from_retrieval` 120. 새 component 최대 48. live에 원래 있던 398 LOC 함수는 미변경 |
| Largest containing class LOC | Factory 493, 미변경 |
| Largest modified module LOC | live 2873 |
| Responsibility growth | false. indicator row owner 이동, 공통 envelope 책임 확장 없음 |
| Verdict | **COMPLEXITY_WARN / REFACTOR_CANDIDATE**, `DECOMPOSITION_REVIEW_REQUIRED` 잔존. scoped extraction acceptance PASS |

module>1500, 독립 책임≥3, `_derive` 기존 HIGH, central 조건6의 구조 부채는 그대로 기록한다. 테스트 통과를 전체 architecture PASS로 해석하지 않는다.

## 9. Contract Delta / remaining ownership

- New/modified/removed **semantic** contracts: 0 / 0 / 0.
- 변경된 구현 소유권: indicator physical row normalization + existing row validation → `indicator_result_adapter`.
- Canonical owner: `action_contract.IndicatorSeriesRow`; metadata declaration은 기존 `semantic_capabilities`; shared resolver/numeric과 envelope는 현행 위치 유지.
- Consumers: `_typed_from_retrieval`, existing capability invocation, 이후 Calculation/Projection/PipeRuntime. 소비 계약 수정 없음.
- 새 단위/criterion/cardinality/status/provenance 정책: 0.
- **DUPLICATED_CONTRACT_SOURCE 잔존:** `_CANONICAL_FIELD_ALIASES` vs `_resolve_row_field` alias 집합, `_typed_from_retrieval` type/metric map vs Registry 선언, `_typed_unit`의 presentation unit helper 의존, Projection/renderer의 별도 field knowledge. 이번에는 통합하지 않음.
- source-specific logic 잔존: trade total/membership, resource population fields/filter, price identity/value/latest annotations, shared markdown/alias/unit decoding, forecast/document fallback, action fan-out/merge, indicator period_change 후처리.

## 10. Stop / rollback boundary

첫 indicator subset만 완료했다. 다음 subset 또는 Step 9 Catalog ownership cleanup은 시작하지 않는다.

rollback은 현재 작업의 live import/두 호출/두 함수 이동과 adapter 파일, 관련 test relocation/new test만 대상으로 삼아야 한다. HEAD 전체 checkout/reset은 기존 Steps 1–7을 지우므로 금지한다. 직전 live 원본과 이번 diff를 evidence에 보존했다.

Strict/Answerable 수치는 갱신하지 않으며, Certified Product Golden의 known contamination 및 미인증 상태도 그대로다. 운영 18002 변경 없음.
