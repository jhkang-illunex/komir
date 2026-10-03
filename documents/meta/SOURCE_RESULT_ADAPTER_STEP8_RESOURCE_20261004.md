# Step 8 마지막 저위험 subset — resource.rank physical normalization

## Acceptance / 종료 판정

**PASS_SCOPED_RESOURCE_RANK_ADAPTER_PARITY — STEP8_COMPLETE**

`resource.rank`의 physical total→production/reserves 컬럼 변환만 dedicated adapter로 이동했다. 승인된 저위험 Step 8 tranche를 종료한다. 모든 source-specific logic이 제거됐다는 의미는 아니다. Step 9 Catalog ownership cleanup을 권고하며 **자동 진행하지 않는다**.

| 검증 | 결과 |
|---|---:|
| Row old/new differential | 3,348 / 3,348 동일 |
| Raw→TypedResult differential | 8,820 / 8,820 동일 |
| 미이관 capability parity | 36 / 36 동일 |
| 저장 graph parity | 7 / 7 동일 |
| 새 characterization cases | 82, 전체/targeted scope에서 통과 |
| Targeted regression | 390 passed / 6 subtests |
| rag_core | **1998 passed / 0 failed / 695 subtests** |
| rag_chat | **155 passed / 동일 known legacy failure 1건 / 15 subtests** |
| 신규 regression / 의미 계약 변경 | 0 / 0 |

Full QA57·Strict 갱신·QA recovery·source query 변경·image rebuild·배포·Step 9·commit/push 없음. **18002와 18012 모두 변경하지 않았다.** 수정 코드는 host working tree이며 실행 중 이미지에 반영하지 않았다.

## 1. Baseline과 evidence identity

- HEAD: `979fd3f980bb10af74a218cc6e07bada110e76de`. 실제 비교 기준은 Steps 1–7 + Step 8 indicator/trade 누적 working tree이며 clean HEAD가 아니다.
- Baseline core 1916/1916, chat 155/156(known failure). 기존 사용자/이전 migration 변경을 보존했다.
- Frozen live SHA256: `2f217db5795e286ae01b487edf5f0db40e2e3bb41cffa42927fd6d22bf435484`.
- After live SHA256: `a82c8325d3d312bd15d07c5a7b3680a91e98bca4294824e79ea34490487e806c`.
- Resource adapter SHA256: `a048208b1786ede876cecdd6df95414b44f7c2072121ed92150f196b65b5c9ed`.
- 직전 trade evidence 30개 파일 해시 불변. Manifest SHA256: `b9bfe1d2a653e58bd9f156ea1b4f21e3bf2ca9a36a18ca062242bc01e991690b`.
- Frozen source는 직전 sealed `live_multihop.py.after`와 byte-identical.
- 18002 `komir-rag-chat-18002`: image `sha256:0d3e757a3d04e75e7b60d7e6917df544b31d4a782d5f7722fb8ddcd3652b466a` 유지.
- 18012 `komir-temporal-step7`: image `sha256:2213f8fcc6dcf3b1cfcb98145d474a82c326f7c0c67f65d1628f95a52f35eb6c` 유지.
- Container ID/image/Created/StartedAt/mount 속성/config hash 전후 동일. Restart/cache flush 없음.
- Durable evidence: `/home/nuri/.codex/validation-evidence/adapter-step8-resource-20261004`.

old/current module에 동일 입력을 넣는 host deterministic 검증이며 source/LLM network를 호출하지 않았다. 저장 graph/differential harness는 socket connect를 차단했다. 실제 production 데이터의 정확성·Product Golden 인증을 새로 주장하지 않는다.

## 2. Pre-change responsibility / contract characterization

`iterative-audit`의 HIGH source-boundary 기준, Architecture/Complexity/Regression 및 Decomposition Guard를 적용했다. `qa-build`는 behavior characterization에만 사용했다. 구현 1회, deterministic 검증, 독립 read-only audit를 수행했다.

| 사전 점검 | 결정 |
|---|---|
| 기존 책임 | `_typed_from_retrieval`이 resource reader의 total 컬럼을 직접 해석 |
| 적절한 owner | physical mapping만 resource-rank adapter; envelope와 scalar binding은 현 owner 유지 |
| 기존 contract | ActionSlots.metric, semantic_capabilities의 ResourceRanking 선언, 기존 FACT_SET TypedResult |
| 재사용 경계 | indicator/trade와 동일한 pure row adapter + 기존 action gate. 새 framework/LegacyResultAdapter 재설계 불필요 |
| 새 개념 유입 | 없음; 기존 resource 지식을 live에서 이동 |
| 기존 중복 | Registry/resource metric와 runtime scalar/alias map은 이미 중복. 이번에 통합하지 않음 |
| 두 번째 실행 정본 | 없음; 기존 실행 본문 제거 후 adapter가 유일한 physical rename owner |
| 공통성 | action scope의 모든 production/reserves rows에 적용, QA/질문/광종 특례 없음 |
| 중앙 분기 | 기존 gate 재사용. 신규 dispatch 0 |
| 분해 근거 | 실패 owner를 독립 순수 함수에서 식별·테스트 가능; 단순 LOC 감소 목적 아님 |

### 이관한 계약과 그대로 둔 envelope

| 항목 | Before = After |
|---|---|
| Adapter input | 기존 evidence→rows→common canonicalization 이후 list[dict], action.slots.metric |
| Physical key | `key.split('(', 1)[0].casefold()`가 `total` 또는 `총계`인 컬럼 |
| Metric selection | 정확한 `production`→`production_volume`, `reserves`→`reserves_volume`. metric casefold/strip 추가 없음 |
| Column operation | **rename**, 원래 total 이름 제거. 여러 key가 canonical 이름으로 합쳐지면 dict 입력 순서의 마지막 값 유지 |
| Canonical collision | 기존 canonical key도 위치에 따라 total 값으로 덮어써짐. 이를 수정하지 않음 |
| Fallback | canonical key가 없으면 exact `total`→`총계` 순서 확인하는 기존 fallback 그대로 보존 |
| Value / rank | 값 파싱·numeric 추론·rank 계산 없음. rank/share/기타 컬럼 유지. downstream의 기존 scalar→value fill은 live에 남음 |
| Cardinality | 행 수·순서·중복 그대로. 지원 metric은 shallow row copy, 미지원 metric은 원본 list identity 유지 |
| Invalid behavior | source key trim/str 변환 없음. non-string key의 AttributeError, unhashable metric의 TypeError 유지 |
| Entity / period | common envelope의 input/row/slots entity 선택과 기존 aliases/dedup, slots.period JSON 유지 |
| Metric / output | Registry는 canonical_metric=resource / ResourceRanking, runtime은 slots.metric / FACT_SET. 기존 표현 차이 통합하지 않음 |
| Unit | row unit 보존, common `_typed_unit` 그대로. 단위 생성·추론 없음 |
| Evidence / provenance | evidence identity/order, source/provenance dedup, warnings, 기존 dummy도 그대로 유지 |
| Status / failure | normalization은 status guard보다 먼저. non-success/no evidence→기존 EMPTY, public failure allowlist, table 없는 evidence success fallback 유지 |

`resource`라는 새 metric을 허용하지 않았다. Raw ActionSlots가 허용하는 metric literal만 사용하고 unsupported 입력의 helper 수준 기존 실패도 별도로 검증했다. PARTIAL/FAIL을 성공으로 바꾸지 않았으며, 원래 raw non-success가 EMPTY로 변환되는 동작도 유지했다.

Trade adapter와 total이라는 표면 이름은 같지만 의미가 다르다. Trade는 unique total일 때 canonical field를 추가하고 physical key를 유지한다. Resource는 key rename/collision을 수행한다. 공통 normalizer로 합치지 않았다.

## 3. 구현 범위

```text
RetrievalResult + ActionCall
  → common evidence/row canonicalization (unchanged)
  → existing resource.rank gate
      → resource_rank_result_adapter.canonicalize_resource_rank_rows
  → existing scalar/value binding + status + TypedResult envelope (unchanged)
  → existing downstream operators
```

- 새 `inhouse/rag_core/ragkit/resource_rank_result_adapter.py`: typing.Any 외 의존성 없음, reverse live import 없음.
- live의 기존 resource if gate는 유지하고 본문 15 LOC(주석 포함, 실행 span 13 LOC)를 1행 delegation으로 교체.
- `_call_action`의 resource population/country 선택, country alias, source reader, Registry, Planner, Projection, History, Renderer는 미변경.
- 새 `test_resource_rank_result_adapter.py`: 227 LOC / 16개 test 함수 / 82 parametrized cases. 기존 tests/QA fixture는 이번 subset에서 변경하지 않음.
- Frozen 본문에서 test-only AST로 추출한 old function과 비교했다. 복제 알고리즘을 production에 남기지 않음.

## 4. 검증 근거와 한계

| 검증 | 구성 / 범위 |
|---|---|
| 사전 characterization | source 수정 전 9개 사례 기록: production/reserves, 순서 충돌, whitespace, unsupported metric, invalid key/metric, empty |
| Row differential | 93 row variants × 4 population shapes × 9 metric forms = 3,348. 값/타입/순서/exception type+message, 원본 불변·shallow identity 비교 |
| Raw→TypedResult | 21 evidence texts × 5 허용 metric × 7 status × 3 unit × 4 evidence/action selection = 8,820 |
| 미이관 parity | 12 capability × 3 status = 36. price/forecast/inventory/trade/indicator/resource.yoy/document |
| Saved graph | GM01/GM02 각 3개 저장 변형 + Golden ADD16 = 7. 신규 독립 QA 7개가 아님 |
| Static AST proof | 이동 본문, thin gate, envelope, 나머지 live 전체 AST, legacy body 부재: 5개 검증 통과 |
| 독립 감사 | material High/Critical finding 0; 계산·alias·envelope 의미 변경 없음 |

Row/Raw 비교에는 값뿐 아니라 type_tree를 사용하여 list/tuple·key/value 타입을 구분했다. 예외 타입/메시지도 비교했다. 실제 임의 숫자 선택·합산·행 제거는 추가되지 않았다.

Saved graph는 resource `_retrieve→_call_action→Raw→TypedResult` 경로를 실행한다. Raw envelope는 **저장 evidence로 success fixture를 재구성**했고 미이관 source 결과는 저장 TypedResult로 고정했다. 원래 source status/실제 DB의 재현을 주장하지 않는다. execution/root/presentation/SSE/call payload가 old/new 동일했다.

- GM01/GM02 저장 변형 6개 root success 유지.
- ADD16 root **ABSTAINED / comparison_alignment_required** 유지. denominator/population recovery 없음.
- 기존 permissive/known-invalid: physical/canonical 충돌 후 기존 `value`와 metric field가 달라질 수 있음, no-table evidence fallback, dummy provenance, unit 부재 모두 보존.
- 처음 differential harness가 ActionSlots의 허용 외 metric을 구성하여 ValidationError가 났다. **harness 입력만 허용 literal로 수정**했고 제품 코드는 바꾸지 않았다. 직접 helper의 invalid metric parity는 별도 유지. 최초 로그도 evidence에 보존.
- 새 unit test 초안의 `Ni` alias 기대 오류 2건은 frozen behavior에 맞춰 assertion만 바로잡았다. alias 코드 변경 없음.

### 정확한 regression scope

repository root에서 다음을 실행했다.

```bash
PYTHONDONTWRITEBYTECODE=1 python3 /tmp/komir-adapter-step8-resource.mhbZeG/characterize.py
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:inhouse:inhouse/rag_chat python3 /tmp/komir-adapter-step8-resource.mhbZeG/validate.py diff
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:inhouse:inhouse/rag_chat python3 /tmp/komir-adapter-step8-resource.mhbZeG/validate.py graphs
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:inhouse:inhouse/rag_chat python3 -m pytest -q -p no:cacheprovider inhouse/rag_core/tests/test_resource_rank_result_adapter.py inhouse/rag_core/tests/test_live_resource_population.py inhouse/rag_core/tests/test_trade_rank_result_adapter.py inhouse/rag_core/tests/test_indicator_result_adapter.py inhouse/rag_core/tests/test_live_multihop.py inhouse/rag_core/tests/test_live_audit_safety.py inhouse/rag_core/tests/test_live_relations.py
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:inhouse:inhouse/rag_chat python3 -m pytest -q -p no:cacheprovider inhouse/rag_core/tests
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:inhouse:inhouse/rag_chat python3 -m pytest -q -p no:cacheprovider inhouse/rag_chat/tests
PYTHONDONTWRITEBYTECODE=1 python3 /tmp/komir-adapter-step8-resource.mhbZeG/resource_measure.py
git diff --check
```

- Targeted: 390 passed / 6 subtests / 1.98s.
- Core: **1998 passed / 695 subtests / 42.11s** = 1916 + 82. 기존 Pydantic lifespan warning 1개 유지.
- Chat: **155 passed / 1 failed / 15 subtests / 6.42s**.
- 동일 known failure: `test_sse_cancellation.py::test_disconnect_stops_real_ast_retry_before_blocking_invocation_returns[legacy_control-False]`.
- 신규 failure/status drift 0. Full QA/Strict 점수는 평가·갱신하지 않음.

## 5. Before / after 구조 지표

| 지표 | Before | After | Delta |
|---|---:|---:|---:|
| live_multihop.py | 2835 | 2821 | −14 |
| _typed_from_retrieval | 122 | 108 | −14 |
| LiveOperatorFactory | 493 | 493 | 0 |
| _derive | 164 | 164 | 0 |
| Central operator conditions | 6 | 6 | 0 |
| Legacy resource normalization body (주석 포함) | 15 | 0 | −15; 1행 delegation으로 대체 |
| New adapter module / function | 0 / 0 | 32 / 20 | +32 / +20 |
| Live AST If count | 371 | 368 | −3 |
| Live + 새 resource adapter If count | 371 | 371 | 0; 기존 3개 조건 이동 |
| Live 넓은 책임 범주 | 12 | 12 | 공통 adapter 범주 잔존 |
| Factory 넓은 책임 범주 | 8 | 8 | factory body 미변경 |

Physical column normalization라는 세부 책임 1개는 live에서 실제 제거됐다. 공통 aliases/type/envelope와 resource country 후처리가 남아 있어 전체 source adapter 책임이 제거된 것으로 세지 않는다.

### Complexity Delta

- Files changed: production 2 / test 1 / artifact 1. 이전 누적 dirty files 제외.
- New classes / Registry entries / public semantic contracts: 0 / 0 / 0.
- 내부 callable 경계: 1개 relocation, 새 abstraction/framework 0.
- New special-case branches: QA/question/entity/answer 모두 0.
- New central-dispatch branches: 0. 제거된 live 조건 3개는 adapter로 이동, 전체 분기 순증가 0.
- Duplicated contract sources added/removed: 0/0. production 본문 복제 없음; 기존 catalog 중복을 해결한 것은 아님.
- Largest modified function: `_typed_from_retrieval` 108 LOC; adapter function 20 LOC.
- 기존 largest containing class 493 LOC, 기존 maximum function 398 LOC는 미변경.
- Largest modified module: 2821 LOC.
- Responsibility growth: false.
- Verdict: **COMPLEXITY_WARN / REFACTOR_CANDIDATE** 유지. Module>1500, 독립 책임≥3, 기존 dispatcher 조건≥5로 `DECOMPOSITION_REVIEW_REQUIRED` 유지. subset acceptance PASS와 전체 architecture debt는 별도다.

### Contract Delta

- New / modified / removed semantic contracts: **0 / 0 / 0**.
- 실행 owner만 변경: physical `total/총계`→declared resource measure는 새 resource adapter가 단독 소유.
- Canonical declaration owner: 기존 `semantic_capabilities.CAPABILITY_ARGUMENTS`, typed action의 ActionSlots.metric. Registry 선언 자체를 수정하지 않음.
- Consumers: `_typed_from_retrieval`→기존 TypedResult→Calculation/Join/Projection.
- 남은 `DUPLICATED_CONTRACT_SOURCE`: Registry metric/type/fields와 runtime map, common `_CANONICAL_FIELD_ALIASES`/resolver, scalar binding의 production/reserves field map, presentation 관련 unit 변환. 이번에는 consolidate하지 않았다.
- Adapter는 physical conversion만 소유한다. common metadata/semantic field catalog 전체를 새 local map으로 복제하지 않았다.

## 6. 남은 inventory와 Step 8 종료

| 잔여 영역 | 위험 / coupling | 권고 |
|---|---|---|
| inventory.latest/series | MEDIUM/HIGH; 독립 normalization body보다 공통 alias/type/metric envelope 의존 | 단독 이동으로 envelope/alias 복제 금지, catalog owner부터 확정 |
| trade.monthly/concentration/indicator, resource.yoy | HIGH; common envelope와 output semantic/type map 결합 | Step 9 ownership 분석 이후 좁은 단계로 계획 |
| resource country selection/population/fan-out/value binding | HIGH; country/metric/dependency 정책 결합 | 이번 physical subset 밖, 의미 변경과 분리 |
| price/forecast | HIGH; criterion/cardinality/unit/provenance/as-of/latest 후처리 결합 | 후순위 유지 |
| complex document/default evidence fallback | HIGH; row/Evidence dual payload·entity/evidence completeness 결합 | 후순위 유지 |
| common row aliases/unit/TypedResult envelope / action merge | HIGH; 여러 domain 공유, catalog 중복 | catalog ownership 정리 선행 |
| indicator period_change post-processing | HIGH; calculation routing/unit contract와 결합 | 별도 경계, 이번 범위 밖 |

**STEP8_COMPLETE**: indicator/trade/resource의 독립 저위험 source-normalization 이관은 종료한다. 다음에 같은 방식으로 안전하게 자를 독립 body보다 공통 envelope/alias/catalog 및 identity 의미가 주요 잔여 책임이다. 추가 domain 파일 분리보다 **Step 9 Catalog ownership cleanup**이 다음 구조적 ROI가 높다.

이는 Step 9 실행 승인이 아니며 여기서 멈춘다. Certified Product Golden의 known contamination, QA별 blocker, Strict 점수는 변경하지 않는다.

## 7. 증거 보존 / rollback

evidence에는 frozen source, new source/test, 전후 diff, characterization, 전체 differential, 저장 graph, 회귀 로그, 구조/identity JSON, 독립 감사, manifest를 저장하고 read-only로 봉인한다. 재실행은 별도 writable scratch로 복사하여 수행한다. 기존 sealed artifact는 덮어쓰지 않는다.

Rollback 범위는 이번 live import/delegation 변경, resource adapter, 새 characterization test로 한정한다. HEAD reset으로 이전 Steps 1–8 전체를 지우지 않는다. 운영/검증 컨테이너는 그대로 유지한다.
