# Step 9 — Catalog ownership cleanup

## Acceptance

**PASS_SCOPED_DECLARATION_OWNERSHIP_PARITY**

동등성이 입증된 10개 계약의 21개 중복 리터럴 선언을 domain 소유 선언 10개로 정리했다. **측정 subset의 중복 정본 11→0**이다. 저장소 전체 catalog 중복이 0이라는 의미는 아니다.

| 검증 | 결과 |
|---|---:|
| Catalog/resolver old-new | 9,340 / 9,340 동일 |
| Semantic produced/requested output | 5,495 / 5,495 동일 |
| IR field/validation | 13,468 / 13,468 동일 |
| Coverage entry | 2,115 / 2,115 동일 |
| Raw→TypedResult control | 576 / 576 동일 |
| Saved graph | 17 / 17 동일 |
| Targeted / capability contract matrix | 422 passed |
| rag_core | **2081 passed / 0 failed / 695 subtests** |
| rag_chat | **155 passed / 동일 known legacy failure 1건 / 15 subtests** |

신규 semantic contract·Registry entry·planner/coverage acceptance 변경·QA recovery 0. **18002/18012 변경 없음**. Full QA57, Strict 갱신, image build/deploy, Step 10, commit/push 없음.

## 1. 기준점 / evidence

- HEAD `979fd3f980bb10af74a218cc6e07bada110e76de` + Steps 1–8 누적 working tree를 실제 기준으로 사용했다. clean HEAD라고 주장하지 않는다.
- Baseline core 1998/1998, chat 155/156(동일 known failure), Step 8 COMPLETE.
- Step8 live SHA256 `a82c8325d3d312bd15d07c5a7b3680a91e98bca4294824e79ea34490487e806c` 유지.
- Step8 sealed evidence 28개 파일의 checksum 불변.
- Frozen before: semantic_capabilities / semantic_ir / aast_coverage / live_multihop.
- Container ID, image ID, Created/StartedAt, mount 속성, config hash 전후 동일. 환경값 원문을 artifact에 노출하지 않고 hash만 기록했다.
- 18012는 `komir-temporal-step7` 이미지 유지. 이번 host 소스가 컨테이너에 반영됐다는 주장은 하지 않는다.
- Durable evidence: `/home/nuri/.codex/validation-evidence/catalog-step9-20261004`.

기존 Behavioral Reference V1와 Product Golden `NOT_CERTIFIED_WITH_KNOWN_REASONS`를 분리한다. dummy/known-invalid behavior를 이번에 수정하거나 PASS로 재인증하지 않았다.

## 2. Pre-change audit / 실제 의미 분류

`iterative-audit` HIGH cross-contract 기준과 Architecture/Complexity/Decomposition Guard를 적용했다. `qa-build`는 신규 QA 추가가 아닌 characterization/conformance 테스트에만 사용했다. 구현 1회와 독립 read-only audit를 수행했다.

| 선언 종류 | 실제 의미와 소비자 | 이번 판단 |
|---|---|---|
| Registry `output_fields` | canonical capability가 해석된 뒤 IR의 projection 허용 후보. 현재 row 존재/비NULL 보장 아님 | 동일 price 두 선언만 공통 owner |
| IR `_METRIC_FIELDS` | Registry resolution 실패 시 fallback 허용 집합, live parser diagnostics에도 사용 | 동일 alias 쌍 6개만 정리 |
| `CAPABILITY_OUTPUTS` | typed requirement가 제공한다고 선언하는 semantic token 집합 | 동일 inventory series 토큰만 정리 |
| guaranteed fields | 현 catalog가 모든 필드의 실제 공급을 보장하지 않음. adapter/runtime 검증과 구별 필요 | 새 보장 선언 생성 금지 |
| optional fields | `unit`, criterion identity, provenance 등은 실제 source/status에 따라 없을 수 있음 | 허용 필드를 필수/guaranteed로 승격하지 않음 |
| args-dependent fields/output | bounded inventory latest, resource_operation, price extremum 등 | 조건·우선순위·fallback 그대로 |
| semantic output type | `ResourceRanking`, `PriceSeries`, `CountryShare` 등 catalog 의미 분류 | runtime ValueType과 합치지 않음 |
| canonical metric | Registry의 resource/country_share와 runtime production/import_amount 등은 서로 다른 축 | 통합 보류 |
| physical source aliases | source 컬럼 해석, 충돌·공백·case·strict resolution 정책 포함 | Step8 adapter/기존 resolver owner 그대로 |

사전 점검의 결론: 이번 동작은 새 기능이 아니라 선언 owner 변경이다. domain별 spec 모듈이 canonical declaration을 소유하고 기존 catalog/IR lookup이 소비한다. 기존 Registry/IR interface, 등록 순서와 의미를 바꿀 필요가 없다. 단순 상수 모듈만 필요하므로 새 class/Protocol/framework/dispatcher를 만들지 않았다.

## 3. 실제 정리한 declaration inventory

경로 prefix: `inhouse/rag_core/ragkit/capability_specs/`.

| # | 동일 semantic fact | 기존 선언 위치/개수 | 단일 owner | 소비자 / 보존 의미 |
|---|---|---:|---|---|
| 1 | Price criterion modes | overview + series / 2 | `price.PRICE_CRITERION_MODES` | Registry; REPRESENTATIVE/EXPLICIT/ALL 그대로 |
| 2 | Price identity tuple | overview + series / 2 | `price.PRICE_IDENTITY_FIELDS` | Registry→identity lookup→Projection; tuple 순서 그대로 |
| 3 | Price allowed output fields | overview + series / 2 | `price.PRICE_ALLOWED_OUTPUT_FIELDS` | Registry→IR; **allowed**, not guaranteed |
| 4 | Indicator IR fallback | indicator + series / 2 | `indicator.INDICATOR_IR_FIELDS` | IR fallback/diagnostics; Registry의 indicator fields와 구별 |
| 5 | Price-change IR fallback | price_change + price_change_rate / 2 | `price.PRICE_CHANGE_IR_FIELDS` | IR fallback; volatility 집합과 합치지 않음 |
| 6 | Import amount IR fallback | import_value + import_amount / 2 | `trade.IMPORT_AMOUNT_IR_FIELDS` | IR fallback; share/weight와 합치지 않음 |
| 7 | Import change IR fallback | import_change + import_value_change / 2 | `trade.IMPORT_CHANGE_IR_FIELDS` | IR fallback; amount 자체와 구별 |
| 8 | Production IR fallback | production + production_volume / 2 | `resource.PRODUCTION_IR_FIELDS` | IR fallback; physical adapter map과 별개 |
| 9 | Reserves IR fallback | reserves + reserves_volume / 2 | `resource.RESERVES_IR_FIELDS` | IR fallback; production과 별개 |
| 10 | Inventory series semantic outputs | table series/inventory_series + bounded latest branch / 3 | `inventory.INVENTORY_SERIES_SEMANTIC_OUTPUTS` | produced_outputs / requested-output coverage, 기존 기간 조건 유지 |

10개 fact의 21개 literal occurrence→10개 선언. 중복 초과 occurrence `Σ(count−1)`는 11→0. 같은 값을 test에서 기대값으로 재기록한 것은 production owner로 세지 않는다.

실제 제거는 기존 literal 21곳을 reference로 교체한 것이다. Catalog entry, alias key, field member, required args, output type, canonical metric은 추가/삭제하지 않았다. Resource의 production/reserves 양쪽 field union이나 import_share/country_share 유사 집합은 **정리 대상에 포함하지 않았다**.

## 4. Owner와 의존 방향

```text
domain capability_specs (immutable declaration values only)
       ├─ price allowance / identity / modes
       ├─ domain IR fallback field sets
       └─ inventory semantic tokens
                ↓
existing semantic_capabilities index / lookup
existing semantic_ir fallback lookup
                ↓
existing resolver / validation / diagnostics consumers
```

- domain 모듈은 서로 다른 의미를 다른 이름으로 선언한다. allowed fields, IR fallback, produced tokens를 단일 catch-all output schema로 합치지 않는다.
- consumer의 기존 dictionary API와 registration order를 그대로 유지한다. lookup 용도로만 소비하지만 기존 public dict API를 MappingProxy로 강제 변경하지는 않았다. 새 불변성 exception을 만드는 것도 behavior change이기 때문이다.
- 6개 IR alias 쌍은 `set(CONST)`로 **각각 별도 mutable set**을 생성한다. 한 alias의 set 수정이 다른 alias/owner에 전파되는 새로운 공유 상태를 방지한다.
- frozenset/tuple 선언은 공유해도 mutation이 불가능하다. tuple 순서는 보존하며 set iteration을 새로운 ordering/selection 규칙으로 사용하지 않는다.
- 새로운 central semantic mapping/dispatch 없음. domain 모듈은 상수·문서만 가지며 source query, runtime, catalog selection을 import하지 않는다.

## 5. DEFERRED_CONTRACT_OWNERSHIP

| 보류 항목 | 동등하지 않거나 증명이 부족한 근거 | 현재/목표 owner |
|---|---|---|
| Registry fields ↔ IR fallback | price Registry에는 value/cmerc_prc 없음, IR fallback에는 있음. indicator Registry에는 period/provenance, IR에는 series가 있음 | 각 allowance owner 유지; 향후 명시적 schema layer 구분 |
| allowed ↔ guaranteed/optional | 행/단위/criterion 공급을 실제 source가 결정. metadata만으로 필수 여부 판단 불가 | domain output spec + adapter validation, 별도 승인 후 |
| Registry semantic type ↔ runtime ValueType | ResourceRanking↔FACT_SET, PriceSeries↔TIME_SERIES는 동일 enum 아님 | semantic catalog와 runtime result type 각각 유지 |
| canonical metric ↔ runtime measure | resource↔production/reserves, country_share↔import/export amount/weight | semantic identity와 physical measure binding 분리 유지 |
| coverage capability lookup ↔ catalog resolver | coverage는 intent/period/operation/fallback을 사용. inventory bounded latest 등을 단순 resolver로 대체하면 selection 범위가 달라짐 | validator-specific contract 유지 |
| physical alias ↔ canonical field list | resource total rename/collision과 trade unique-total copy는 다름; whitespace/strict resolver 정책도 다름 | dedicated source adapter / existing resolver |
| args-dependent output production | resource_operation·average+sum·price selection·bounded period가 output을 바꿈 | 기존 semantic functions 유지, field union으로 대체 금지 |
| resource measure mapping 두 곳 | adapter physical rename과 runtime scalar binding의 순서/기존 value 보존 책임이 다름 | 현 owner 유지, 전후 변환 계약을 별도로 검증해야 함 |
| price/forecast/document incomplete metadata | 선언되지 않은 field/type/guarantee를 실제 구현만 보고 추측 보완하면 planner 범위 확대 가능 | 미보완, 별도 semantic 작업 |
| catalog API deep read-only enforcement | 기존 dict 반환/외부 소비의 mutation 가능 API까지 변경하면 단순 ownership 이동이 아님 | 이번 interface 유지, 별도 compatibility 검토 |

위 표는 잔여 후보 inventory이며 저장소 전체 중복 건수의 완전한 census가 아니다. 이번 subset 밖의 중복을 0으로 보고하지 않는다.

## 6. Differential / regression

### Old/new 조건

같은 프로세스에서 frozen/current module을 로드했다. frozen IR은 frozen catalog lookup을, frozen coverage는 frozen IR enum/program을 사용하도록 연결했다. Runtime raw comparison은 frozen/current live를 사용하며 old live의 catalog lookup/identity field consumer를 frozen catalog에 연결했다. persistent cache나 LLM에 의존하지 않는다.

| 검증 | 구성 / 판정 |
|---|---|
| 사전 declaration proof | 10개 fact의 값·정확한 멤버·tuple 순서·IR mutable set 독립성 확인, 21 occurrences 기록 |
| Catalog 9,340 | 모든 existing specs/table/IR values, domain×surface metric×args, identity lookup, unknown action. 값·타입·예외·등록 키 순서 동일 |
| Outputs 5,495 | 기존 semantic 키 + unknown, period dict/object, resource operations, selection, mixed aggregate requirements, requested-output error 문자열 |
| IR 13,468 | catalog-qualified/fallback metric × projection fields, 성공과 validation rejection 모두 비교 |
| Coverage 2,115 | 위 IR이 수용한 graph 각각에 실제 validate_aast 진입, report/violation parity |
| Raw→TypedResult 576 | 12 capability × 4 metric × 4 status × 3 raw evidence shape. source/metric/unit/provenance/status/type/failure 보존 |
| Saved graph 17 | 동일 program / 저장 evidence 입력, root/status/failure/SSE/execution/capability call 비교 |
| Static | 두 semantic 파일의 constant substitution 복원 후 전체 AST 동일. live/coverage byte-identical |

Saved graph는 Step6 old/new 및 Golden 저장 변형이다. GM01, GM02, ADD25, REG02, ADD27, IX02, REG06, PF03, ADD16 총 9개 QA ID의 17개 graph이며 fresh QA 17건이 아니다. Raw source envelope는 저장 Evidence에서 success fixture로 재구성했고 그 외 source 결과는 저장 TypedResult다. 따라서 실제 DB/LLM/Strict content 인증은 아니다.

ADD25 저장 버전별 success/EMPTY 차이는 old/new 각각 동일했다. REG06 dependency failure와 PF03/ADD16 comparison_alignment_required abstain도 그대로다. 이를 QA recovery로 세지 않는다.

### 실행 command

repository root, 동일 PYTHONPATH / regression scope:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 /tmp/komir-catalog-step9.T35Syi/precheck.py
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:inhouse:inhouse/rag_chat python3 /tmp/komir-catalog-step9.T35Syi/validate_catalog.py catalog
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:inhouse:inhouse/rag_chat python3 /tmp/komir-catalog-step9.T35Syi/validate_catalog.py raw
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:inhouse:inhouse/rag_chat python3 /tmp/komir-catalog-step9.T35Syi/validate_catalog.py graphs
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:inhouse:inhouse/rag_chat python3 -m pytest -q -p no:cacheprovider inhouse/rag_core/tests/test_catalog_ownership.py inhouse/rag_core/tests/test_semantic_capabilities.py inhouse/rag_core/tests/test_aast_coverage_validator.py inhouse/rag_core/tests/test_semantic_v2_contract.py inhouse/rag_core/tests/test_semantic_v2_linkage.py inhouse/rag_core/tests/test_qa500_contract_matrix.py inhouse/rag_core/tests/test_indicator_result_adapter.py inhouse/rag_core/tests/test_trade_rank_result_adapter.py inhouse/rag_core/tests/test_resource_rank_result_adapter.py
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:inhouse:inhouse/rag_chat python3 -m pytest -q -p no:cacheprovider inhouse/rag_core/tests
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:inhouse:inhouse/rag_chat python3 -m pytest -q -p no:cacheprovider inhouse/rag_chat/tests
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:inhouse:inhouse/rag_chat python3 /tmp/komir-catalog-step9.T35Syi/measure.py
git diff --check
```

- Targeted 422 passed / 3.44s.
- Core **2081 passed** = baseline 1998 + 신규 characterization 83. 695 subtests, 42.43s. 기존 Pydantic lifespan warning 1개 유지.
- Chat **155 passed / known failure 1**, 15 subtests, 6.44s. 정확한 failure: `test_sse_cancellation.py::test_disconnect_stops_real_ast_retry_before_blocking_invocation_returns[legacy_control-False]`.
- 신규 unit test 초기 4건은 생성자 validation exception 포착 범위 오류였다. 테스트만 고쳤고 기대 behavior나 제품 코드는 수정하지 않았다.
- 독립 read-only 감사: material High/Critical finding 0. 실제 검증 범위와 deferred 경계를 별도 검토했다.

## 7. Before / after 및 Architecture Guard

| 지표 | Before | After |
|---|---:|---:|
| 선택한 계약 수 | 10 | 10 |
| 해당 production literal 선언 수 | 21 | 10 |
| 해당 중복 정본 수 | 11 | 0 |
| semantic_capabilities.py LOC | 237 | 236 |
| semantic_ir.py LOC | 484 | 488 |
| 새 domain spec LOC | 0 | price13 + indicator3 + trade8 + resource8 + inventory3 + init5 = 40 |
| live_multihop.py / Factory / _derive | 2821 / 493 / 164 | 동일 |
| central operator conditions | 6 | 6 |

### Complexity Delta

- Files changed: production 8 (기존 2 + 신규 6), 신규 test 1 (223 LOC), artifact 1. 이전 누적 dirty changes 제외.
- New classes / public semantic contracts / Registry entries: **0 / 0 / 0**. 내부 상수 이름 10개 relocation, 새 framework 0.
- New QA/question/entity/answer special cases: **0**.
- New central-dispatch branches / removed executable branches: **0 / 0**.
- Duplicated contract sources added/removed: **0 / 11**, 명시한 subset 기준.
- Largest function/class in modified modules: 기존 `completeness_issues` 236 LOC / `SemanticProgram` 350 LOC, 본문 미변경. 실제 메서드 로직 변경 0.
- Largest modified module: semantic_ir 488 LOC. 기존 live 2821 LOC 미변경.
- Responsibility growth: **false**. 중앙 catalog에 새 의미를 추가하지 않고 domain 선언 owner로 옮겼다.
- Verdict: **COMPLEXITY_WARN / REFACTOR_CANDIDATE** 유지. 기존 큰 validator/live 책임에 `DECOMPOSITION_REVIEW_REQUIRED`가 남는다. 전체 architecture PASS로 확대 해석하지 않는다.

실패 owning boundary는 기존 semantic/IR validation으로 그대로 국소화되며, 동일 필드 집합의 변경은 두 literal을 수정하지 않고 domain 선언 한 곳에서 가능하다. 중앙 실행 분기 수는 증가하지 않았다. 모든 신규 capability를 중앙 파일 수정 없이 등록할 수 있는 완성된 plugin 구조를 이번에 만들지는 않았다.

### Contract Delta

- New / modified / removed **semantic contracts 0 / 0 / 0**.
- Ownership relocation: 10개 동등 선언을 5개 domain spec module이 소유.
- Canonical source of truth: 위 declaration inventory의 owner. lookup은 기존 semantic_capabilities/semantic_ir.
- Consumers: resolver, IR field inference, produced/requested output validator, live diagnostic/identity lookup.
- Remaining duplicated mappings: §5의 deferred inventory. physical alias, coverage-specific selection, runtime metric/type는 이번에 통합하지 않음.

## 8. Architecture V1 1차 checkpoint readiness

**READY_WITH_KNOWN_DEBT — host-source behavioral checkpoint 가능.**

1. Step1–8 이관 후 Step9의 승인된 동등 선언 ownership 정리가 완료됐고, 이전 evidence를 보존한 immutable 전후 snapshot/differential이 있다.
2. rag_core 신규 failure 0, rag_chat 동일 known legacy failure만 남는다. 저장 graph의 기존 success/failure/status를 보존했다.
3. 신규 branch/semantic contract/중복 정본 증가 0. 남은 coupling과 deferred ownership이 명시됐다.
4. 이는 **Product Golden 인증, 최신 Full Strict 재측정, 배포 readiness 또는 clean commit 선언이 아니다**. Full QA57 없이 Strict 점수를 변경하지 않는다. Certified Product Golden은 NOT_CERTIFIED_WITH_KNOWN_REASONS 유지.
5. Source checkpoint는 이번 evidence manifest와 누적 working tree 기준이다. Commit/tag/push나 운영/18012 이미지 변경은 별도 승인 없이 수행하지 않는다.

## 9. Rollback / stop boundary

이번 두 semantic 파일의 import/constant reference 치환, capability_specs, 새 test만 작업별 rollback 대상으로 한다. 이전 Steps 전체를 HEAD reset으로 제거하지 않는다. Frozen/current source와 per-file diff, tests/logs/identity/manifest를 durable evidence에 봉인한다. 재실행은 별도 writable scratch copy에서 수행한다.

**Step 10 Projection 자동 진행 없음.** Full QA57, Strict 갱신, 18002/18012 배포 없이 이 결과를 저장하고 종료한다.
