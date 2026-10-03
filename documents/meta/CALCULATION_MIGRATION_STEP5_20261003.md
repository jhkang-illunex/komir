# Architecture Migration Step 5 — Calculation routing extraction

## 판정과 범위

**Acceptance: `PASS_SCOPED_CALCULATION_BEHAVIOR_PARITY`.**

CALCULATE의 routing/argument adaptation을 기존 등록형 handler로 이동했다. 기존 series/share/ratio 알고리즘은 변경하지 않았다. inline mapping change는 analytical series와 의미를 합치지 않고 별도의 작은 helper로 **기존 수식을 한 번만 이동**했다. migrated legacy execution body는 제거했다. `DEFERRED_CALCULATION_BRANCH = 0`.

- rag_core: **1641 → 1672 passed / 0 failed**. 증가 31개는 characterization tests이며 QA 회복 수가 아니다.
- rag_chat: **155 passed / 동일 known legacy failure 1건**.
- QA57 Full Replay, Strict 점수 갱신, QA recovery, Step 6 Relation 수행 없음.
- 운영 **18002 변경 없음**. 검증 **18012만** 후보 이미지로 전환했다.
- Behavioral Reference parity만 판정한다. Certified Product Golden은 계속 `NOT_CERTIFIED_WITH_KNOWN_REASONS`이며 기존 dummy/known-invalid 동작을 고치지 않았다.

## 1. Identity / isolation / evidence

| 항목 | 값 |
|---|---|
| git parent | `979fd3f980bb10af74a218cc6e07bada110e76de` |
| source state | Golden parent + 기존 Step 1–4 dirty changes + 이번 Step 5; clean Golden SHA로 표시하지 않음 |
| frozen old source | `/tmp/komir-calculation-step5.yvyUBD/step4_live_multihop.py` |
| old image | `komir-rag-chat:filter-step4-20261003` |
| old image ID | `sha256:e8dca207d2f1b2173bb199e534c69cb5eaa21db31a2a55ba3f78a93243ffe0da` |
| new image | `komir-rag-chat:calculation-step5-20261003` |
| new image ID | `sha256:84e763798fa8aa672cc265fe550881ccdf625cc08277681f35ebaaf1dffa4037` |
| candidate container | `komir-calculation-step5` / `481d4845cec3…` / `127.0.0.1:18012` |
| production container | `komir-rag-chat-18002` / `dd4a39b93365…`; image ID/start time/mounts 불변 |
| source/config preflight | host/container **228 files 일치**, env/extra_hosts/network/readonly mounts 동일; Gemma/MCP/health 정상 |
| source DB fingerprint | 전후 `341be4d0d4316a9cd4da90aaaa952f38d931a1e344910ff21bf24d8d18e71954` 동일 |
| raw evidence bundle | `/home/nuri/.codex/validation-evidence/calculation-step5-20261003` |

새 이미지의 revision/build timestamp label과 실제 container image ID를 저장했다. local image ID를 사용하며 registry RepoDigest를 임의로 만들지 않았다. 후보 live 요청은 `preflight.json=PASS`와 실제 image ID 일치를 확인한 **뒤에만** 실행했다. 각 요청은 새 UUID session, history 없는 동일 public endpoint/payload를 사용했다. 모델/DB/resource 설정은 변경하지 않았다. env-file의 secret은 evidence에 복사하지 않았다.

Frozen source는 기존 Step 4 sealed checksum 및 old container 실제 파일과 일치한다. Step 4 sealed evidence **64파일**의 checksum도 유지됐다. DB fingerprint는 기존과 동일한 `public/mineral_risk` 범위다. fresh session 저장용 `ai_chatbot` 쓰기는 정상 검증 동작이며 원천 데이터 변경으로 계산하지 않는다.

Docker inspect가 mount 배열 순서를 바꾸어 반환하는 경우는 destination 정렬 후 **모든 mount 속성**을 비교했다. ID/image/StartedAt은 그대로 비교했다. 이는 환경 측정의 배열 순서 처리이며 QA oracle 변경이 아니다.

## 2. Semantic pre-audit — family별 기존 contract

근거: frozen `_derive`, `analytical_series.py`, `analytical_share.py`, `_numeric`, `_finalize_derived_rows`. 동일 수식/이름만으로 계약을 통합하지 않았다.

| Family / authoritative owner | Input/cardinality / required args | Unit / PARTIAL / invalid policy | Output / status / provenance |
|---|---|---|---|
| Series / `analytical_series.calculate_series` | 첫 input의 비어 있지 않은 Mapping rows; TIME_SERIES/FACT_SET/SCALAR_METRIC. exact operation, field 또는 metric_field, time_field; operation별 frequency/group/bounds/other_field | routing은 모든 input 중 PARTIAL이면 `incomplete_population`. helper는 source SUCCESS, sufficient, evidence, warning/failure, date/duplicate/null/unit 검증. unit 미정이면 `unit_unavailable`. zero base 거절 | output_field 기본 value. endpoint/periodic `%`, base100 `index`, correlation `1`, threshold 원 단위. operation/group별 TIME_SERIES/FACT_SET/SCALAR_METRIC. helper의 replace 기반 evidence/provenance 및 실패 envelope 보존 |
| Share / HHI / `analytical_share.calculate_share` | 첫 input의 nonempty list[dict]; field 기본 value; group_by 선택. HHI `output=contributions` 별도 기존 형태 | PARTIAL routing 거절; aggregate_nulls_excluded warning/row status 검사. nonnegative finite, bool 거절. group별 units 일치, **모든 unit None은 기존대로 허용**. total<=0 거절 | 원 numeric field를 share로 교체, row unit 제거. share COUNTRY_SHARE/%; HHI scalar 또는 contributions COUNTRY_SHARE/HHI(0-10000). 성공은 source replace; 기존 status/provenance 보존. helper 실패는 기존 plain abstain |
| `division / percentage / percent` aliases / Calculation routing → share helper | lower 처리 후 기존 population-share로 argument copy/adaptation. row-local 나눗셈 아님 | share와 동일. operand/denominator를 새로 추론하지 않음 | share contract 그대로. 새 alias 없음 |
| Single-source ratio / `analytical_share.calculate_ratio` | Mapping 또는 nonempty list[dict]. numerator_field/left_field 및 denominator_field/right_field 필수; output_field 기본 ratio. 입력 2개가 **아닌** 경우 첫 input 사용, 기존 3-input 동작도 보존 | row status 검사, float finite, denominator!=0. signed/bool 허용 기존 동작 보존. unit/period 호환성 추가 검사 없음. `%`는 as_percentage=True 또는 args.unit='%' | SCALAR_METRIC, metric ratio/percentage, unit ratio/%. operand columns 제거 후 결과 field; 다른 row fields 보존. SUCCESS로 replace하는 기존 동작 및 남은 metadata 유지. 실패 plain abstain |
| Two-input ratio / `analytical_share.calculate_ratio_between` | exact 2 inputs, mapping insertion/InputRef binding 순서의 left=numerator/right=denominator. 각각 Mapping 또는 singleton list[Mapping]. explicit fields 또는 각 value | **PARTIAL 공통 검사 전에 선택**. 두 결과 SUCCESS+sufficient 아니면 `incomplete_ratio_inputs`. multi-row `ratio_scalar_inputs_required`; finite/zero 검사. unit/metric/scope 일치 추가 검사 없음 | 새 SCALAR_METRIC singleton; % 또는 ratio. metadata/evidence/upstream IDs 기존 순서로 결합. period가 같으면 유지, 다르면 None. 실패 plain abstain |
| Inline `change_pct / percent_change` / 새 위치 `analytical_mapping_change.calculate_mapping_change` | exact-case aliases, 첫 input.value가 Mapping. 고정 start/end; list[Mapping]은 해당하지 않음. 기존 `_numeric` comma/% 허용 | 모든 input PARTIAL 거절. start/end finite, start!=0; **date/evidence/unit 검증 없음**. invalid → `invalid_calculation_operands` | 원 mapping + 고정 change_pct를 단일 row list로 변환. `(end-start)/abs(start)*100`. 기존 finalizer가 result type/metric/unit/status/failure/evidence/provenance 유지. `%` unit을 새로 만들지 않음 |

### 보존한 차이와 known-invalid behavior

- series `endpoint_change`와 inline change는 입력 shape/date/unit/evidence/failure/status가 다르다. inline을 series alias로 바꾸지 않았다.
- series는 evidence/unit이 필요하지만 inline은 필요하지 않다. ratio와 share 사이에도 bool/row-status/negative/metadata 정책 차이가 있다.
- binary ratio는 exactly-two 입력 및 binding 순서에 의존한다. PARTIAL 사유는 unary/share의 `incomplete_population`이 아니라 `incomplete_ratio_inputs`다.
- 3 inputs ratio는 기존처럼 첫 결과로 row-local 계산한다. 추가 input PARTIAL 검사는 유지한다. 이 동작을 개선하지 않았다.
- series의 exact operation 검사, share/ratio의 lower/casefold 검사, unhashable args의 기존 exception 경로를 유지한다.
- CN08 unit 부재, ADD16 denominator/reduction, dummy provenance, REG04 60행 평균, alias 통합, planner/capability/Projection/History/Renderer/oracle은 수정하지 않았다.

## 3. Responsibility pre-check와 migration

`LiveOperatorFactory`의 실행 family 선택/산술 delegation을 줄이는 승인된 CRITICAL mechanical migration이다. 기존 StepFactory 등록 dictionary/StepHandler/FunctionStep/PipeRuntime가 적합한 경계이며 새 framework는 불필요하다.

```text
CALCULATE AAST node + ordered InputRef bindings
    → existing StepFactory registration
    → build_calculation_step / existing FunctionStep
        → existing analytical_series.calculate_series
        → existing analytical_share.calculate_share / calculate_ratio / calculate_ratio_between
        → extracted legacy mapping-change helper → existing finalizer
    → existing PipeRuntime → unchanged TypedResult / result events
```

- handler 소유: 기존 family routing, 기존 PARTIAL precedence, alias argument adaptation, helper 호출.
- helper 소유: 계산/검증/output-unit/failure 의미. 기존 series/share/ratio 파일은 byte checksum 불변.
- inline helper: 기존 mapping 알고리즘 1개를 단일 위치로 옮김. 새 calculation capability/type/spec/alias가 아니다.
- `_build_legacy`에서 CALCULATE 제거. `_derive`의 binary-ratio shortcut과 CALCULATE elif body 제거. `_derive`에는 CALCULATE-specific condition/본문이 남지 않는다.
- `_call_action`의 기존 `calculate_series` 사용은 별도 Capability 내부 경로이므로 유지했다. 이것을 CALCULATE node legacy body로 오인하여 삭제하지 않았다.
- Factory의 나머지 methods, module helpers, Projection body는 AST 비교로 불변 확인. resolver/numeric/finalizer는 기존 interface injection을 재사용한다.
- test 4개 파일의 private `_derive` CALCULATE 호출만 등록형 entry로 변경했다. 기존 assertion/semantic fixture는 완화하지 않았다.

## 4. Deterministic differential / characterization

실제 frozen Step 4 코드를 별도 module로 load하여 old/new에 동일 input을 넣었다. 예상값으로 재구현한 old algorithm은 사용하지 않았다. network tripwire를 적용했다.

| 검증 | 결과 |
|---|---:|
| Boundary differential (모든 family, 모든 ResultStatus, args/shape/0–3 input/invalid/evidence/unit/warning) | **5485/5485 동일** |
| 실제 PipeLowerer → PipeRuntime → root/presentation/SSE, operand 순서·all/index/field selector·dependency failure | **108/108 동일** |
| 후보 container에서 동일 differential | host evidence와 **전체 JSON 동일** |
| Step 4 saved ADD16 CALCULATE graph | **5/5 동일**, calculation_field_unavailable 유지 |
| 이번 old/new live graph/source 고정 cross-executor replay | **16/16 동일** |
| Targeted/contract tests | **247 passed**, 3 subtests; 2.26s |
| rag_core 전체 | **1672 passed**, 695 subtests; 40.47s |
| rag_chat 동일 scope | **155 passed / known 1 failed**, 15 subtests; 6.52s |

Boundary 비교에는 TypedResult의 모든 필드와 exception type/message, step ID/operation/dependencies/bindings/timeout/retry를 포함했다. runtime graph는 execution/status/failure/upstream IDs/call count/presentation/SSE까지 비교했다. 새 tests는 취소 전 실행 차단과 기존 FunctionStep 기본 timeout=None/retry=0도 확인한다. timeout/retry scheduler 자체는 변경하지 않았다.

Behavioral Reference Step 0 저장 graph에는 CALCULATE node가 **0개**다. 없는 Golden CALCULATE input을 있다고 주장하지 않는다. 보완 근거는 봉인된 Step 4의 실제 CALCULATE graph 5개, 이번 live CALCULATE graph 2개, 결정론적 family/selector matrix다.

검증 harness의 최초 graph fixture는 inline change에 필요한 start/end를 선언하지 않은 price retrieve graph라 기존 validator에서 거절됐다. 제품 validator를 바꾸지 않고 그 부적합 graph fixture를 제외했다. inline mapping 경계는 direct FunctionStep differential/characterization으로 검증하고 series/share/ratio는 검증 가능한 graph로 검사했다.

### 실행 command / scope

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:inhouse:inhouse/rag_chat python3 /tmp/komir-calculation-step5.yvyUBD/differential.py
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:inhouse:inhouse/rag_chat python3 -m pytest -q -p no:cacheprovider inhouse/rag_core/tests/test_registered_calculation.py inhouse/rag_core/tests/test_qa500_series.py inhouse/rag_core/tests/test_qa500_common_contracts.py inhouse/rag_core/tests/test_live_audit_safety.py inhouse/rag_core/tests/test_live_relations.py
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:inhouse:inhouse/rag_chat python3 -m pytest -q -p no:cacheprovider inhouse/rag_core/tests
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:inhouse:inhouse/rag_chat python3 -m pytest -q -p no:cacheprovider inhouse/rag_chat/tests
```

known failure는 `test_sse_cancellation.py::test_disconnect_stops_real_ast_retry_before_blocking_invocation_returns[legacy_control-False]`, 예상 calls=3 / 실제 4로 baseline과 동일하다. skip/xfail/assertion 변경 없음. 기존 pydantic warning 1건도 유지됐다.

## 5. Live parity — 모델/검색 변동 분리

old 8회 + new 8회, 각각 fresh session. QA57 전체 실행이나 score 산정이 아니다.

| 대상 | raw answer/terminal/TypedResult | Graph | fixed graph/source old/new |
|---|---|---|---|
| CN08 run1 | 다름 | 다름 | 동일 |
| CN08 run2 | document evidence/source 수 다름 | 동일 | 동일 |
| ADD16 | 동일; calculation_field_unavailable | 동일 | 동일 |
| REG02 | 동일; success | 동일 | 동일 |
| REG04 | 동일; 기존 aggregate result | 동일 | 동일 |
| ADD15 | 동일 | 동일 | 동일 |
| ADD49 | 동일 | 동일 | 동일 |
| ADD27 | 동일 | 동일 | 동일 |

- raw/terminal/TypedResult parity **6/8**, graph parity **7/8**. 이를 8/8 raw parity라고 보고하지 않는다.
- CN08 old run1은 document `validation_failed`로 all_roots_failed, old run2는 document 일부 반환으로 PARTIAL이었다. **코드 교체 전에도 변동**했다. 후보 두 번은 PARTIAL, 문서 evidence가 2개로 달랐다.
- CN08 indicator branch는 old/new 모두 `unit_unavailable`. 이번 live graph는 두 retrieve root이고 CALCULATE node를 만들지 않았다. 따라서 CN08 응답 변화는 CALCULATE migration 성공/QA 회복으로 계산하지 않는다.
- 새/옛 graph와 upstream TypedResult를 각각 고정하여 양 executor에서 실행했을 때 **16개 모두 동일**했다. CN08의 graph 차이와 document-retrieval output 차이는 관찰했으나 document 검색 변동의 세부 내부 원인을 이번 범위에서 단정하지 않는다.
- REG02 이번 live graph는 entity→retrieve로 같았다. ordered_last 경로 자체는 기존 registered Aggregate/date-binding tests와 전체 rag_core로 보호했다. live 한 번으로 ordered_last 3/3 안정성을 재인증하지 않는다.
- SSE terminal은 16회 모두 정확히 1회 종료. known contamination/provenance는 보존했으며 Product PASS로 승격하지 않았다.

## 6. 구조 지표 / Complexity Delta

측정: physical module LOC; AST start/end 기준 class/method LOC; 중앙 조건은 LiveOperatorFactory 내부 If.test에 `.operator`가 포함된 조건 수. 기존 Steps와 동일 기준이다.

| 지표 | Before | After |
|---|---:|---:|
| live_multihop.py LOC | 2952 | **2928** |
| LiveOperatorFactory LOC | 517 | **493** |
| `_derive` LOC | 199 | **170** |
| central operator conditions | 10 | **8** |
| legacy CALCULATE execution LOC (binary shortcut + calculation branch) | 29 | **0** |
| new Calculation handler module LOC | 0 | **51** |
| handler builder LOC | 0 | **40** |
| extracted mapping helper module LOC | 0 | **20** |
| remaining CALCULATE legacy branches / `_derive` CALCULATE references | 2 / 있음 | **0 / 없음** |

`_derive` 잔여 책임: Relation delegation, 기존 COMPARE PARTIAL guard, canonical/domain projection 및 공통 row finalizer 호출. 기존 Relation early return으로 guard가 도달하지 않는 구조도 이번 scope에서 청소하지 않았다. Factory에는 retrieval/action routing, entity/history-result lookup, for_each, evidence validation 등 기존 독립 책임이 남아 있다.

### Complexity Delta

- Files changed 이번 scope: **application 3 + test 5 + artifact 1**. 기존 Steps/skill dirty changes는 이번 변경에 포함하지 않는다.
- New classes: **0**.
- New public semantic contracts: **0**. 내부 extraction callable 2개(builder, mapping helper).
- New registry entries: **1**, 기존 CALCULATE operator의 등록이며 새 operator 아님.
- New special-case branches: **0**; QA/question/entity/answer hardcoding 각각 **0**.
- New central-dispatch branches: **0**; 기존 operator conditions **2 감소**.
- Removed branches: 기존 CALCULATE binary shortcut/main branch **2**. handler의 6개 기존 family/partial routing condition은 소유 위치 이동이지 새 의미 추가가 아님.
- Duplicated contract sources added/removed: **0 / 0**. algorithm 복제 **0**.
- Largest modified method/class/module LOC: **170 / 493 / 2928**.
- Responsibility growth: **false**. 중앙 factory에서 Calculation routing 책임 1개 감소. 계산 실패 owner는 handler→지정 analytical helper로 국소화됐다.
- Verdict: 추출 범위의 parity/책임 분리는 **PASS**. 전체 구조는 **COMPLEXITY_WARN / REFACTOR_CANDIDATE / DECOMPOSITION_REVIEW_REQUIRED** 유지(module>1500, method>150 HIGH, 중앙 조건8, factory 독립 책임3+). 테스트 통과만으로 전체 architecture clean을 주장하지 않는다.

## 7. Contract Delta

| 항목 | 내용 |
|---|---|
| Modified contract | 외부 semantic contract 없음; CALCULATE 실행 entry만 legacy `_derive`→registered builder |
| New/removed semantic contracts | 0 / 0 |
| Authoritative owners | series: analytical_series; population/ratio: analytical_share; mapping change: 추출 helper; routing: calculation handler |
| Consumers | StepFactory, FunctionStep, 기존 PipeRuntime; TypedResult/Projection/Renderer consumer 불변 |
| Argument/field/unit/alias changes | 없음 |
| Metadata/failure owner | 기존 helper 또는 기존 `_finalize_derived_rows`; 새 해석/보정 없음 |
| Remaining duplication | 기존 Projection/legacy alias 및 planner/output metadata 부채는 그대로. 이번에 새 mapping을 복제하지 않음 |

기존 handler 등록 경계로 CALCULATE 전체를 격리했다. 이후 같은 family 확장은 해당 helper/handler 책임 내에서 가능하며 central factory에 domain condition을 더할 필요가 없다. 모든 계산을 하나의 새 spec/type system으로 통합하지 않았다.

## 8. Acceptance / 종료

- migrated calculation behavioral parity: PASS (host/container 동일).
- 신규 regression: 0; 기존 failure/status 변화: 동일 결정론적 입력에서 0.
- legacy body 제거, 중앙 조건 순감소, 특례/algorithm duplication/contract duplication 증가0: PASS.
- 독립 read-only auditor: 구체적 semantic drift/HIGH·CRITICAL finding 없음. 실행 증거는 별도로 위 검증으로 확보했다.
- 18002/image/start time/mounts 및 원천 DB 불변 확인.
- Strict baseline/Certified Product Golden 재인증 없음. CN08 등 알려진 문제 미수정.
- **Step 5에서 종료. Step 6 Relation 자동 진행 없음.**

주요 근거 파일: evidence bundle의 `acceptance.json`, `differential.json`, `container_differential.json`, `saved_graphs.json`, `live_cross_replay.json`, `live_drift.json`, `source_checksums.json`, `complexity.json`, `rag_core.log`, `rag_chat.log`, `manifest.json`. Frozen old source와 실행 scripts도 함께 봉인한다.
