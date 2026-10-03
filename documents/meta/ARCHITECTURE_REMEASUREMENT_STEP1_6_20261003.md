# Architecture Re-measurement — Steps 1–6

## 결론 / 판정

- 기존 분류를 그대로 적용하면 **live module 책임 12 → 12**, **LiveOperatorFactory 책임 9 → 8**이다. 이는 이관 실패가 아니라, 넓은 책임 범주가 아직 완전히 비워지지 않았다는 뜻이다.
- Aggregate, Extremum, Ordering, Filter, Calculation의 **operator-node 실행 경로**와 Relation builder는 별도 handler가 소유한다. 그러나 Projection, source canonicalization, graph repair, source 호출 후 계산 등은 live에 남아 있다.
- 기존 **Step 7 Temporal continuation extraction을 유지**한다. 다음 순서는 **Temporal → source-result adapter의 순수 이동 → 동등성이 입증된 catalog 선언 한 묶음의 소유권 정리**를 권고한다. 큰 함수부터 기계적으로 잘라내는 순서는 아니다.
- 현 상태: `DECOMPOSITION_REVIEW_REQUIRED`, `REFACTOR_REQUIRED`(계획된 점진 정리 필요). Steps 1–6의 behavioral acceptance를 취소하거나 새 semantic repair를 승인하는 판정이 아니다.
- 이번 작업은 read-only 정적 감사다. **이 문서만 신규 작성**했으며 코드·테스트·QA·image·container·DB·18002를 변경하거나 실행 검증하지 않았다.

## 1. 기준과 측정 방법

### Evidence / identity

| 항목 | 근거 |
|---|---|
| Git HEAD | `979fd3f980bb10af74a218cc6e07bada110e76de` |
| 실제 감사 source | HEAD 자체가 아니라 승인 Steps 1–6이 누적된 dirty working tree. 기존 변경/미추적 파일을 보존 |
| live source SHA-256 | `a144eb1b9f4bb2f42b06fb4e98ccd757180adc4b612067d8d55f95356fa8a3ae` |
| 초기 책임 기준 | [초기 Architecture Audit B.1](GOLDEN_V1_ARCHITECTURE_AUDIT_MIGRATION_PLAN_20261003.md) |
| 최신 behavioral 근거 | [Step 6 acceptance](RELATION_MIGRATION_STEP6_20261003.md) |
| sealed evidence | `/home/nuri/.codex/validation-evidence/relation-step6-20261003` |
| source 대조 | Step 6 `source_snapshot`의 live/relational 파일과 byte 동일. `source_checksums.json` 중 로컬 core/chat 경로로 대응한 155파일 전부 일치; 이것을 전체 229파일 재검증이라고 부르지 않음 |
| regression | 기존 저장 결과: rag_core **1691 passed**, rag_chat **155 passed / 동일 known legacy failure 1**. 이번 감사에서는 재실행 안 함 |
| Golden 의미 | Behavioral Reference는 비교 기준. Certified Product Golden의 known contamination/미인증 상태는 변경하지 않음 |

측정은 `python3` 표준 라이브러리 `ast`, `pathlib`, `hashlib`와 read-only `git show/status`를 사용했다. 앱 import/테스트/QA 요청은 하지 않았다.

Architecture 의사결정은 CRITICAL 범위로 취급하되 이번 승인 범위는 분석 1회다. read-only 독립 검토에서도 책임 12→12 / 9→8 및 Temporal 우선순위의 근거를 확인했다. `inhouse/`와 `.agents/`의 tracked/untracked 파일 600개를 경로·내용 hash로 비교한 감사 전후 fingerprint는 동일하다: `ab56938e4bc7dfa7de831f5de5de7c9bd129d22a4ba28c64ffb481a78aee9471`.

- Module LOC: `len(text.splitlines())`, 주석/빈 줄 포함.
- 함수/class LOC: `end_lineno - lineno + 1`; decorator 줄은 제외, 내부 함수는 포함.
- If 수: 해당 AST 안의 `ast.If` 수(내부 함수 포함). McCabe complexity나 독립 책임 수와 다르다.
- 기존 central operator 조건 지표: Factory 내부 `If.test`의 `node.operator` 조건. registry 항목 수나 source action 분기 수는 포함하지 않는다.
- 책임 수: 초기 B.1의 범주별로 **일부라도 의미/전후 정책을 계속 소유하면 잔존**. 단순 등록·의존성 주입은 별도 domain 책임으로 중복 집계하지 않는다.
- 초기 HEAD의 top-level 함수와 현재 함수 AST를 비교한 결과 **변경된 top-level 함수 없음**. 이번 이관이 주로 Factory와 새 handler에 집중됐다는 근거다.

## 2. Responsibility recount

### live module: 12 → 12

| 초기 동일 범주 | 현재 소유 근거 | Step 1–6 효과 / 잔여 |
|---|---|---|
| AST/model I/O schema | `AST*Model`, `AST_PROMPT` | 유지 |
| LLM retry/cache | `_parse_ast`, `_AST_CACHE` | 유지 |
| graph normalization/coverage repair | `_normalize_relation_contract`, coverage helpers | 유지; execution 추출과 별개 |
| history binding | materialization/context/alias/reference helpers | 유지; 보호 경계 |
| evidence row decoding | `_rows`, `_typed_from_retrieval` | 유지 |
| field/unit/date canonicalization | resolver/canonicalize/unit/date/filter helpers | 유지; handler도 callback으로 소비 |
| capability resolution/slots | `_action_id`, `_action_slots` | 유지 |
| operator 구현 | `_derive` Projection, `_finalize_derived_rows` | 6 family의 node 실행/routing은 이동. 범주 자체는 남음 |
| retrieval/fan-out | `_retrieve`, `_foreach`, `_call_action` | 유지 |
| runtime/session 조립·저장 | `run_live_multihop`, history result 저장 | 유지 |
| trace/diagnostics | coverage trace, action trace, `record_legacy_comparison` | 유지 |
| SSE/presentation | `live_run_events`, `_result_events` | 유지; 이번 cleanup 후순위 |

### LiveOperatorFactory: 9 → 8

| 초기 동일 범주 | 현재 | 근거 |
|---|---|---|
| 1. Step dispatch | 잔존 | `build` 2092–2130, `_build_legacy` 2132–2141 |
| 2. saved history entity 복원 | 잔존 | `__init__` 2072–2090, `_entity` 2143–2153 |
| 3. typed input → action slot binding | 잔존 | `_retrieve` 2344–2382의 role/충돌/date 검사 |
| 4. row selection/projection | 잔존 | `_derive` 2159–2322; latest selection도 `_call_action`에 잔존 |
| 5. calculation/aggregation routing | **부분 잔존** | CALCULATE/AGGREGATE node는 handler로 이동했지만 `_call_action`의 `indicator.series + period_change → calculate_series(endpoint_change)` routing/args 구성은 남음 |
| 6. join/compare routing | **제거** | `build_relation_step`이 FunctionStep/실행 위임을 소유. Factory에는 등록과 resolver 주입만 남음 |
| 7. source invocation/result postprocess | 잔존 | `_call_action`: primitive 질문, retrieval, TypedResult, country/latest/output 후처리 |
| 8. multi-entity/ForEach + partial merge | 잔존 | `_retrieve` fan-out, `_foreach` |
| 9. evidence validation | 잔존 | `_validate` 2338–2342 |

**9 → 7로 표시하지 않는 이유:** 계산 **node 경로**의 이관 완료와 Factory 전체의 계산 routing 책임 소멸은 다르다. 초기 기준도 helper 위임 전후의 domain 정책을 소유하면 책임으로 세었다. indicator calculation args를 바꾸면 여전히 Factory를 수정해야 하므로 범주 5를 보수적으로 유지한다. source I/O 자체(범주 7)와 계산 연산 선택/인자(범주 5)는 독립 변경 이유다. 이를 지금 수정하자는 뜻은 아니다.

세부 family 소유권은 실제 개선됐다: extrema/tie, ordering/TopK, filter predicate, aggregate 실행, CALCULATE family routing, relation FunctionStep construction을 바꾸기 위해 legacy `_derive`를 수정할 필요가 없다. 다만 공통 resolver/finalizer 정책 변경은 아직 live를 건드린다.

## 3. LOC / hotspot 재측정

| 지표 | 초기 HEAD | 현재 | 변화 |
|---|---:|---:|---:|
| live module | 3057 | 2928 | −129 |
| LiveOperatorFactory | 627 | 493 | −134 |
| `_derive` | 352 | 164 | −188 |
| central operator conditions | 15 | 6 | −9 |
| `relational_ops.py` | 323 | 323 | 0 |
| `execute_relation` | 308 | 308 | 0 |

### 함수 hotspot Top 10 — live + relation 범위

| 순위 | 함수 | 줄 / LOC | If 수 | 독립적으로 바뀌는 주요 정책 |
|---|---|---:|---:|---|
| 1 | `_normalize_relation_contract` | live 442–839 / **398** | 65 | derived resource/indicator rewrite, trade scope/flow/share, forecast/continuation, compare field/date 추론 |
| 2 | `execute_relation` | relation 16–323 / **308** | 66 | dependency/evidence barrier, keyed join/broadcast, side-by-side, arithmetic, temporal, envelope |
| 3 | `_parse_ast` | live 1093–1272 / **180** | 16 | model payload, retry, cache, normalization/validation/coverage 순서 |
| 4 | `_result_events` | live 2761–2928 / **168** | 34 | composite 재구성, latest price 선택, unit/citation/table/chart/SSE |
| 5 | `_derive` | live 2159–2322 / **164** | 25 | Projection + domain compatibility + identity/status |
| 6 | `run_live_multihop` | live 2575–2703 / **129** | 10 | history cutoff/materialization, parser/lowering/runtime 조립, persistence, tracing |
| 7 | `_normalize_history_aliases` | live 1293–1413 / **121** | 11 | reference namespace/type, active result, alias/refresh graph binding |
| 8 | `_typed_from_retrieval` | live 1722–1839 / **118** | 20 | evidence decoding, action-specific fields/types/metric, public failure, identity/unit/provenance |
| 9 | `_action_slots` | live 1955–2052 / **98** | 19 | period/country/domain/criterion→typed slots |
| 10 | `_call_action` | live 2476–2563 / **88** | 15 | source call shaping, history policy, canonicalization, calculation/country/latest postprocess |

기타 필수 경계: `_validate_live_contract` 78 LOC/27 If; `_retrieve` 77/13; `_resolve_row_field` 72 LOC; `_foreach` 53 LOC; `_materialize_history_requirements` 50 LOC; `_semantic_context_payload` 58 LOC; `_resolve_history_references` 43 LOC; `record_legacy_comparison` 46 LOC. History 전체가 이관 대상이라는 의미는 아니다.

### Guard 적용

- module 2928 >1500; 함수 398/308 >200: `DECOMPOSITION_REVIEW_REQUIRED`.
- Factory는 **493 <500**이지만 책임 **8 ≥3**으로 여전히 분해 검토 대상이다.
- `_derive`는 **164 <200**이나 기존 >150 HIGH와 다중 정책 책임 기준에 해당한다. LOC 문턱 아래가 안전 판정은 아니다.
- 조건 6개는 ENTITY/FOR_EACH/PROJECT/VALIDATE_EVIDENCE 4개 dispatch + PROJECT 실행 guard + PROJECT/COMPOSITE finalization이다. 이를 “독립 operator 6개”라고 해석하지 않는다. 별도로 default retrieval와 source action/domain 분기가 남아 있다.
- handler 등록 항목은 10개(operator ID) / 6 family. 중앙에서 family별 알고리즘을 직접 처리하는 조건문과 같지 않다. 다만 새 family의 wiring은 아직 `build`의 composition root에서 등록해야 한다. 완전한 plugin 자동발견 구조라고 주장하지 않는다.

## 4. `_derive` 잔여 책임

아래는 25개 If를 정책 묶음으로 분류한 것이다. 이름은 derive지만 현재 실행 family는 **PROJECT 하나**다.

| 경로 / 줄 | 위임인가, 실제 의미인가 | 목표 owner / 향후 순서 | 최종 thin Factory에 유지? |
|---|---|---|---|
| 2159–2166 source/rows/fields 준비 + PROJECT guard | input adaptation | Projection handler | 아니오; 등록만 |
| 2167–2176 aliases/reserved unit/collision | 실제 validation 정책 | Projection contract | 아니오 |
| 2177–2181 DOCUMENT_EVIDENCE→MINERAL_SET | document-derived entity 의미 변환 | 먼저 compatibility 그대로 격리; 이후 document output owner 별도 검토 | 아니오 |
| 2182–2194 empty list, heterogeneous unit warning, MineralSet row화 | cardinality/status/type 정책 | Projection adapter/finalization | 아니오 |
| 2195–2260 price optional/ALL identity field 제거·보존 | 실제 price output compatibility; 반복 선언 존재 | Price Output Spec과 proven-equivalent 소비자. catalog 준비 후 Projection | 아니오 |
| 2261–2285 resolver, inventory fallback, metric→value table | domain/physical field 해석 | source adapter/Output Spec; 지금 alias 통합 금지 | 아니오 |
| 2286–2302 unit/source/single entity metadata fallback, missing field | canonical metadata projection + fail-closed | Projection contract | 아니오 |
| 2303–2317 input completeness, alias output, PARTIAL status/reason/output/unit | 실제 output/status 정책 | Projection handler | 아니오 |
| 2318–2322 distinct + finalization 호출 | dedup 의미 + helper 위임 | Projection handler → 기존 finalizer | 아니오 |

`_finalize_derived_rows` 12 LOC도 entity fallback과 PROJECT COMPOSITE→FACT_SET 정책을 소유한다. helper가 짧아도 완전한 generic envelope 함수는 아니다. 현재 migrated handler가 주입받는 callback의 동작을 보존한 뒤 소유권을 정리해야 한다. 단지 `_derive`를 80 LOC 이하로 만들기 위한 분할은 권고하지 않는다.

## 5. live 2928 LOC 구성

AST 함수 span을 한 영역에만 배정한 **중복 없는 LOC 장부**다. 함수 내부의 로그 등 cross-cutting 코드는 주 책임에 포함한다. 따라서 순수 알고리즘 LOC 추정이나 책임 개수와 동일하지 않다.

| 영역 | LOC | extraction 가능성 / 제약 |
|---|---:|---|
| graph normalization/coverage/repair | 660 | 규칙 순서/graph mutation 결합이 높음. 조건·규칙별 input/output snapshot 먼저, 이후 기존 pure helper composition; planner rewrite 금지 |
| AST/model/cache 함수 | 193 | prompt/retry/cache 정책을 함께 보존해야 함; 우선순위 낮음 |
| history helpers + Factory snapshot/entity 복원 | 358 | 이미 안정화된 closed boundary, 이번 우선순위에서 제외 |
| source-result / canonical / field-unit-date helpers | 402 | 기존 LegacyResultAdapter callable 경계 활용 가능. resolver는 handler/Projection/SSE도 소비하므로 통째 relocation 금지 |
| action resolution/slots/invocation/fan-out | 369 | source I/O, 계산 후처리, concurrency/status merge 분리 후보. adapter 이동과 동시에 재설계 금지 |
| Projection + finalizer | 176 | registered handler seam 존재하나 price/document/alias 의미가 결합. 후순위 |
| Step assembly/input/evidence check | 56 | wiring 유지, evidence 정책은 별도 소유권 후보 |
| runtime/session orchestration | 129 | 최종 live entry/composition root의 핵심 잔존 후보 |
| legacy comparison trace/result persistence | 46 | 진단과 session 저장이 함께 있으므로 단순 logging 모듈로 옮기면 안 됨 |
| SSE/presentation | 173 | 기존 presentation boundary 후보; 현재 보류 |
| 나머지 schema/prompt/import/상수/decorator/공백 | 366 | 별도 runtime 책임처럼 계산하지 않음 |
| **합계** | **2928** | |

즉 모듈이 큰 주된 이유는 **새 handler body가 안에 쌓여서가 아니라, 기존 top-level planner/source/history/presentation 함수들이 그대로 남았기 때문**이다.

## 6. Migrated handler 위치와 의존성

모두 `inhouse/rag_core/ragkit/operator_handlers/`에 이미 존재한다.

| 파일 | Module LOC | builder LOC | 실제 owner / 주입 경계 |
|---|---:|---:|---|
| aggregate.py | 40 | 27 | aggregate args/order binding → 기존 analytical_aggregate; resolver 주입 |
| extremum.py | 61 | 52 | extrema/tie/row selection; resolver/numeric/finalize 주입 |
| ordering.py | 64 | 56 | ordering/upstream rank/TopK; no-input rank는 retrieve callback |
| filtering.py | 101 | 92 | predicate/filter 정책; period/country/resolver/finalize 주입 |
| calculation.py | 51 | 40 | 기존 연산 helper family routing; mapping change와 series 의미 분리 |
| relation.py | 21 | 12 | 기존 execute_relation에 동일 입력 위임 |
| 합계(6개) | **338** | | `__init__.py` 1 LOC 별도 |

위치는 적절하다. handler에서 live 모듈로 reverse import하지 않으며, 기존 TypedResult/FunctionStep/semantic_ir/helper와 callback에 의존한다. 함수 계열별 failure owner를 찾기 쉬워졌고 기존 family의 내부 변경은 legacy dispatcher body 변경을 요구하지 않는다.

잔여 coupling은 `resolve`, `numeric`, `finalize`, `filter_period`, `resolve_country`, no-input rank의 `retrieve` callback이다. 이는 동작 보존을 위한 명시적 seam이며, 새 parallel framework의 근거가 아니다. filtering builder 92 LOC는 기존 >80 warning이지만 family 책임이 국소화되어 있어 LOC만으로 재분할하지 않는다.

## 7. 가장 큰 God Responsibility 3개

1. **Typed graph repair/normalization**: `_normalize_relation_contract`에 resource derived metric, indicator period_change, trade scope/flow/share, forecast binding, temporal composition, output-field inference가 집중. 실행 handler 추출로 줄지 않았다. 규칙 순서와 재작성 dependency 때문에 high risk.
2. **Source 결과의 의미 재구성**: `_typed_from_retrieval` + canonical helpers + `_call_action` 후처리. physical table decoding, metric/type 선언, unit, public failure, population/entity, 계산과 latest 선택까지 live 경로에 남아 있다. Registry/adapter/presentation 간 owner가 겹친다.
3. **Relation의 여러 결합 의미**: `execute_relation`에 typed key indexing/cardinality, scalar broadcast, side-by-side field inference, arithmetic comparison, temporal continuation, partial metadata가 함께 있다. Step 6은 routing만 이동했고 이 책임은 의도적으로 그대로다.

Projection과 SSE도 후속 후보지만, Product/History/Renderer 경계를 지금 동시에 정리하지 않는다.

### Single Source of Truth / duplication 재확인

| 현재 중복/누출 | 근거 | 목표 owner / 주의 |
|---|---|---|
| metric→field | normalizer `value_fields`, `_derive.metric_value_fields`, registry/IR output fields | Capability Output Spec. declaration의 optional/guaranteed 차이를 합치지 않음 |
| physical aliases | `_resolve_row_field`, `_CANONICAL_FIELD_ALIASES`, indicator/trade canonicalization | source adapter; exact/annotated/fuzzy/ambiguous 정책이 달라 무조건 통합 금지 |
| price identity | `_derive` 반복 4-field sets와 `capability_identity_fields` | 기존 price Spec; absence/optional/ALL behavior 고정 필요 |
| action→metric/ValueType | `_typed_from_retrieval`와 Registry semantic declarations | Spec을 소비하는 adapter. semantic output type와 runtime ValueType을 동일하다고 가정하지 않음 |
| unit parsing/presentation | `_typed_unit`이 display helpers 사용; `_result_events`도 raw unit code 해석 | adapter unit contract / presentation label 분리 후보; unit 보정 금지 |
| temporal fields | Relation의 `crtr_ymd/forecast_date/predicted_price`, graph normalizer의 forecast fields | 현행 Temporal helper 소유권 격리부터. 새 alias/canonical policy로 치환 금지 |

`DUPLICATED_CONTRACT_SOURCE` 및 기존 `REFACTOR_CANDIDATE` 유지. 이번 감사에서 중복을 추가하거나 제거하지 않았다.

## 8. Step 7 재평가 / 다음 3단계

| 후보 | 경계/구조적 ROI | 기계적 이관 위험 | 우선순위 |
|---|---|---|---|
| Temporal continuation | 독립 입력/출력 family와 조기 return. relation 96–142의 **47줄** 조건 포함 block을 기존 helper composition으로 격리 | HIGH 유지: 공통 guard/metadata/ValueError catch, PARTIAL, date/as-of 그대로 유지. 다른 후보보다 범위가 작음 | **1 — 기존 Step 7 유지** |
| Source-result adapter | evidence/physical schema→TypedResult라는 기존 callable 경계. 여러 operator에 이익 | HIGH: shared resolver, evidence fallback, failure precedence, 단위 display 의존성 | **2 — Step 8을 좁게 시작** |
| Catalog ownership cleanup | source adapter와 Projection의 duplicated truth 축소 | HIGH: 표면상 같은 선언도 priority/allowed/optional 의미가 다름 | **3 — proven-equivalent 한 묶음만** |
| Remaining live planner/graph/history | 잔여 LOC는 크지만 control order와 state coupling이 큼 | HIGH; History closed boundary, planner acceptance/retry/cache 변화 위험 | 앞 3개 뒤 재평가 |
| Projection preparation/extraction | registry handler seam 가능, Factory 책임 감소 여지 | HIGH: document conversion/price identity/metadata fallback/COMPOSITE. source/catalog owner 미정이면 debt를 다른 파일로 옮기기만 함 | 기존 Step 10 후순위 유지 |

숫자상 가장 큰 normalizer를 먼저 옮기지 않는다. Temporal은 failure-owning boundary를 명확히 만들 수 있는 작은 실제 의미 단위이며, source/catalog는 소비자가 많아 더 넓은 characterization이 필요하다. 비교 결과 **원래 7→8→9 순서를 바꿀 충분한 근거는 없다**. 단 다음 scope를 명시적으로 좁힌다.

1. **Temporal pure execution extraction**: `execute_relation`의 공통 two-input/status/evidence/row/PARTIAL 검사 이후 위치에서 기존 continuation body를 위임. 기존 registered relation handler/FunctionStep/PipeRuntime는 유지. helper는 prepared operands/rows/args/metadata/resolver를 받아 기존 TypedResult를 반환. 공통 catch 안에서 호출하며 입력 순서·object/row copy·예외·provenance 순서 불변. 새로운 temporal registry/TypedOperator 계층 불필요. 한 commit으로 rollback 가능.
2. **Source-result adapter의 좁은 기계적 이동**: `_typed_from_retrieval`와 그 전용 decoding/adaptation 책임부터 기존 `LegacyResultAdapter` callable 형태에 맞춰 격리. generic resolver/finalizer/country/date 규칙을 새로 합치지 않는다. `_call_action` source I/O/indicator 계산/latest 후처리까지 한 번에 이관하지 않는다. 독립 rollback 단위로 더 나눈다.
3. **Catalog declaration ownership 한 묶음**: actual output/type/identity 선언 중 현행 소비자 결과가 완전히 동등한 subset만 owner 한 곳으로 연결. 기존 의미가 다르면 보류. Registry metadata 보충, output coverage 확대, semantic alias union은 feature이므로 이 단계에서 하지 않는다.

### 추천하는 바로 다음 작업 하나

**Step 7 Temporal continuation mechanical extraction**만 별도 승인 범위에서 실행하는 것을 권고한다. 아직 시작하지 않았다.

이 단계의 책임 감소는 `execute_relation` 내부에서 발생한다. live/Factory의 기존 B.1 범주 수까지 감소한다고 예측하지 않는다.

필수 보존 항목: 현재 날짜 문자열 정규화, observed 마지막 날짜를 경계로 forecast `<=` 제외, rows 내부 복제와 출력 순서, `metric="price"`, unit/entity의 현재 느슨한 검사, criterion 검사 부재, provenance/warnings/partial 상태의 현재 동작. known-invalid behavior를 이관 과정에서 고치지 않는다.

향후 검증: Step 6 saved differential의 temporal cases + empty/failed/partial/dependency/exception precedence + reverse InputRef + 동일 runtime/SSE graph parity → targeted tests → rag_core 전체 → rag_chat 동일 scope. 기존 non-temporal relation 결과까지 불변이어야 한다. 새 PASS/사라진 failure는 성공 지표가 아니라 drift 조사 대상이다.

## 9. Complexity / Contract Delta — 이번 감사 한정

```text
Files changed: 신규 audit artifact 1; source/test/config 0
New classes: 0
New public contracts: 0
New registry entries: 0
New special-case branches: 0
New central-dispatch branches: 0
Removed branches: 0
Duplicated contract sources added/removed: 0 / 0
Largest modified method/class/module LOC: N/A (source 수정 없음)
Responsibility growth detected: 이번 변경 0; 기존 live 12 / Factory 8 잔존
Verdict: DECOMPOSITION_REVIEW_REQUIRED + REFACTOR_REQUIRED (기존 debt)
```

```text
New/modified/removed contracts: 0 / 0 / 0
Canonical source of truth: 변경 없음
  Capability 의미: 기존 Registry/Spec
  operator execution: 기존 analytical/relational helper와 registered handler
  runtime envelope/barrier: TypedResult / PipeRuntime
Consumers: live assembly, handlers, parser/coverage, Projection/presentation
Remaining duplicated mappings: 위 7절 목록; 의미 통합/수정 없음
```

기존 dirty source/test/skill/artifact를 수정·정리·commit하지 않았다. regression 수치는 저장된 Step 6 결과이며 이번 감사가 새 테스트 통과를 주장하지 않는다. Full QA57/Strict 갱신, Step 7 실행, image/server/18002 변경 없이 종료한다.
