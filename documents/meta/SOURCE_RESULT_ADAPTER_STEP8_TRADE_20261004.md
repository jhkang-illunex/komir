# Step 8 — trade.country_rank adapter subset

## Acceptance

**PASS_SCOPED_TRADE_RANK_ADAPTER_PARITY**

첫 [indicator subset](SOURCE_RESULT_ADAPTER_STEP8_20261003.md) 이후 다음 독립 subset인 `trade.country_rank`의 row membership과 typed metric binding만 추출했다. semantic 개선·QA recovery·전체 adapter migration 완료를 뜻하지 않는다.

| 검증 | 결과 |
|---|---:|
| row old/new differential | 3,008 / 3,008 동일 |
| raw→TypedResult differential | 7,140 / 7,140 동일 |
| 미이관 capability control | 36 / 36 동일 |
| 저장 graph | 6 / 6 동일 — GM01/GM02 각 3개 저장 변형 |
| 새 characterization tests | 87 passed |
| targeted | 296 passed / 3 subtests |
| rag_core | **1916 passed / 0 failed / 695 subtests** |
| rag_chat | **155 passed / 동일 known legacy failure 1건 / 15 subtests** |

Full QA57·Strict 갱신·source query·image rebuild·컨테이너 교체·Step 9·commit/push 없음. **18002 변경 없음**. 이번 source 수정은 18012 이미지에 반영하지 않았다.

## 1. Baseline / frozen identity

- git parent: `979fd3f980bb10af74a218cc6e07bada110e76de`.
- 실제 비교 기준: Steps 1–7 + Step 8 indicator 누적 working tree. clean HEAD로 오인하지 않음.
- 기준 regression: core 1829/1829, chat 155/156(동일 known failure).
- frozen live SHA256: `f63227d157bbdb95e9e007246910c146aa94c996c09d82f5cc70a1ad6c2bf74e`.
- migrated live SHA256: `2f217db5795e286ae01b487edf5f0db40e2e3bb41cffa42927fd6d22bf435484`.
- trade adapter SHA256: `2657b87f2bea591ad2c4c6bcd823724c51ae5c964e06ecaeee57fbe74dad34af`.
- 직전 sealed evidence 25파일 SHA256 불변. 직전 manifest SHA256: `f482429e5a162acfb04149f63feeb388d5d7f61dee1168fb5b08fe6b6c058d81`.
- 18012: `komir-temporal-step7`, image `sha256:2213f8fcc6dcf3b1cfcb98145d474a82c326f7c0c67f65d1628f95a52f35eb6c` 유지.
- 18002/18012의 container ID, image, Created/StartedAt, mount 속성, config hash 전후 동일.
- evidence: `/home/nuri/.codex/validation-evidence/adapter-step8-trade-20261004`.

old/new는 같은 프로세스에서 서로 다른 frozen/current module을 읽고 동일 fixture를 주입했다. source/LLM 요청과 persistent cache에 의존하지 않았다. 컨테이너 재시작·캐시 flush를 하지 않았다. Behavioral Reference와 Product Golden 미인증/known contamination 상태는 유지한다.

## 2. Selection / pre-change responsibility check

iterative-audit의 HIGH source boundary, Architecture/Complexity/Regression/Decomposition Guard를 적용했다. qa-build는 boundary characterization에만 사용했다. 구현 1회 후 deterministic 검증과 독립 read-only 감사를 수행했다.

| 점검 | 결정 |
|---|---|
| 기존 책임 | live가 country/share 표 membership과 physical total→typed metric binding을 직접 소유 |
| 적절한 owner | dedicated trade-rank row adapter. source query·공통 envelope·계산은 소유하지 않음 |
| 왜 이번 후보인가 | inventory의 독립 body는 거의 없지만 trade rank는 순수 함수 두 개가 있고, 4개 metric과 source field 선택 규칙이 이미 명확 |
| 기존 contract | `COUNTRY_SHARE`, ActionSlots.metric, 기존 Registry CountryShare 선언, 기존 strict resolver |
| 기존 extension boundary | 첫 subset과 동일 pure adapter 함수 + dependency injection. LegacyResultAdapter/StepFactory/Runtime interface 변경 불필요 |
| 새 개념 / 두 번째 정본 | 없음. 기존 본문 제거, shared alias/base-column parser는 동일 함수를 주입 |
| QA 특례 여부 | QA·질문·광종·국가와 무관한 기존 capability scope |
| 중앙 분기 증가 | 없음. 기존 trade gate 재사용, 중복 비-trade early-return guard 제거 |
| 구조 변경 필요성 | membership/total binding의 실패 owner를 단독 component에서 확인 가능. 단순 파일 크기 감소 목적이 아님 |
| 이번에 하지 않는 일 | share 계산, total 합산, unit 판단, registry metric 통합, source status 수정, source/Planner 변경 |

price/forecast와 복잡한 document는 여전히 제외했다. trade와 resource 모두 `total`을 사용하지만 기존 처리 의미가 달라 공통 normalizer로 합치지 않았다.

## 3. Selected subset contract inventory

| 항목 | 그대로 보존한 계약 |
|---|---|
| 입력 | 기존 common evidence extraction / row canonicalization을 이미 거친 list[dict] |
| 표 membership | strict resolver로 `country`와 `share_percentage` key가 모두 식별되는 행을 선택. 값의 유효성 검사와 다름 |
| cardinality | qualifying rows의 원래 순서·중복·row identity 유지. 하나도 없으면 `ranked or rows`로 원래 목록 반환 |
| physical mapping | 유일한 `total` 또는 `총계` base column → 선언된 import_amount/export_amount/import_weight/export_weight |
| metric handling | 기존 `str(metric or '').casefold()`만 적용. trim/새 alias 추가 없음. unsupported metric은 원본 목록 그대로 |
| canonical 우선 | canonical key가 있으면 None/빈 문자열/0도 덮어쓰지 않음 |
| total 모호성 | 2개 이상이면 값이 같아도 선택하지 않음. 없는 total을 다른 숫자에서 추론하지 않음 |
| 값/identity | numeric conversion 없이 원본 total value와 physical columns 보존. 지원 metric에서는 각 row shallow copy |
| TypedResult | 기존 COUNTRY_SHARE, metric은 기존 slots.metric. Registry의 canonical_metric=country_share로 바꾸지 않음 |
| entity / period | common envelope의 input entities/row/slots alias-dedup과 slots.period JSON 유지 |
| unit / criterion | row unit 그대로, envelope `_typed_unit` 그대로. 가격 criterion 정책 없음, 새 단위 생성 없음 |
| evidence/source/provenance | 표에서 일부 rows가 제외돼도 evidence bundle은 그대로. 기존 source/provenance dedup와 warnings 유지 |
| status / failure | 정규화는 기존처럼 status guard보다 먼저. non-success/no evidence→EMPTY, public failure allowlist, evidence-only fallback 등 공통 envelope 불변 |

다음 known-invalid/permissive behavior도 유지했다: null country/share라도 key가 식별되면 membership 통과, qualifying row가 없어도 전체 rows를 COUNTRY_SHARE로 반환 가능, evidence만 있고 표가 없으면 Evidence 목록으로 성공 fallback, dummy provenance 보존. 이를 개선하거나 product correctness로 인증하지 않는다.

## 4. Implementation / removed legacy body

```text
RetrievalResult + ActionCall
  → common evidence/table canonicalization (unchanged)
  → existing action_id == trade.country_rank gate
      → trade_rank_result_adapter.select_country_rank_rows
      → trade_rank_result_adapter.canonicalize_trade_rank_rows
  → common status / TypedResult envelope (unchanged)
  → existing downstream operators
```

Production:

- 새 `inhouse/rag_core/ragkit/trade_rank_result_adapter.py`.
- live의 `_capability_rows` 16 LOC와 `_canonicalize_trade_rank_rows` 20 LOC 제거.
- 기존 trade gate 안에서 selection→normalization 순서 유지.
- `_capability_rows`의 비-trade 반환은 단순 `return rows`였으므로 해당 no-op 호출 제거.
- shared `_resolve_row_field`, `_base_column_name`은 callback으로 그대로 사용. adapter→live reverse import 없음.
- indicator adapter, Registry, `_typed_unit`, source execution/후처리, Projection은 미변경.

Tests:

- 새 `test_trade_rank_result_adapter.py`: 17개 함수 / 87 parametrized cases.
- 기존 `test_live_multihop.py`의 호출 2곳과 `test_qa106_contract_repairs.py`의 호출 1곳만 새 owner로 변경. assertion 의미 변경 없음.

## 5. Differential / saved graph evidence

| 검사 | 구성 / 결과 |
|---|---|
| Row | 94 row variants × 4 population shapes × 8 metric forms = 3,008. 원본 불변, membership row identity/order, fallback list identity, total ambiguity 포함 |
| Raw→TypedResult | 17 evidence text variants × 5 metric × 7 status × 3 unit × 4 evidence/action 선택 = 7,140 |
| 미이관 control | 12 capability × 3 status = 36. price/forecast/inventory/resource/indicator/다른 trade/document 포함. membership gate가 다른 action에 퍼지지 않음 |
| Saved graph | GM01/GM02 각각 Golden/Step6 old/Step6 new 저장 graph = 6. 두 QA의 저장 변형이지 독립 QA 6종이 아님 |
| Static parity | membership·metric-binding 본문 동등, envelope 동등, 나머지 전체 live module AST 동등, legacy helpers 부재: 5 assertions 통과 |

row/raw 비교는 JSON 값뿐 아니라 `type_tree`로 list/tuple 및 scalar/key/value 타입도 비교했다. 별도 테스트는 row shallow-copy, Evidence identity, unsupported metric identity, resolver short circuit와 strict=True 유지도 확인한다.

저장 graph는 trade `_retrieve→_call_action→raw→TypedResult`를 실제로 실행한다. raw envelope는 **저장 Evidence에서 success fixture로 재구성**했고, 다른 capability upstream은 저장 TypedResult로 고정했다. 따라서 원본 source status 재현·실제 DB 조회·QA recovery 증거가 아니다. saved graph 비교는 execution/root/presentation/SSE/call의 JSON 정규화 동등성이다. network connect는 차단했다.

old/new 6개 graph의 root success가 동일했지만 이번에 새 PASS로 집계하지 않는다. 모든 비교에서 failure/status/provenance drift 0이며 strict oracle을 새로 실행하지 않았다.

### Commands / regression

repository root, 동일 PYTHONPATH/scope:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:inhouse:inhouse/rag_chat python3 /tmp/komir-adapter-step8-trade.ZlM1To/validate.py diff
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:inhouse:inhouse/rag_chat python3 /tmp/komir-adapter-step8-trade.ZlM1To/validate.py graphs
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:inhouse:inhouse/rag_chat python3 -m pytest -q -p no:cacheprovider inhouse/rag_core/tests/test_trade_rank_result_adapter.py inhouse/rag_core/tests/test_indicator_result_adapter.py inhouse/rag_core/tests/test_live_multihop.py inhouse/rag_core/tests/test_qa106_contract_repairs.py inhouse/rag_core/tests/test_live_audit_safety.py inhouse/rag_core/tests/test_live_relations.py
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:inhouse:inhouse/rag_chat python3 -m pytest -q -p no:cacheprovider inhouse/rag_core/tests
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:inhouse:inhouse/rag_chat python3 -m pytest -q -p no:cacheprovider inhouse/rag_chat/tests
python3 /tmp/komir-adapter-step8-trade.ZlM1To/measure.py
git diff --check
```

harness와 frozen source는 durable evidence에도 저장했다. 해당 경로의 validate.py/measure.py로 재실행할 때 readonly evidence를 쓰기 가능한 별도 scratch에 복사해서 사용한다. 기존 sealed evidence를 덮어쓰지 않는다.

- targeted: 296 passed / 3 subtests, 1.26s.
- core: **1916 passed / 0 failed / 695 subtests**, 42.05s = 1829 + 87. 기존 Pydantic lifespan warning 1 유지.
- chat: **155 passed / 1 failed / 15 subtests**, 6.64s. known ID는 `test_sse_cancellation.py::test_disconnect_stops_real_ast_retry_before_blocking_invocation_returns[legacy_control-False]`로 동일.
- 신규 QA corpus/Strict 판정/QA recovery/production fixture 추가: 모두 0.
- 독립 read-only 감사: material High/Critical finding 0. static parity와 evidence 범위/한계를 별도 확인.

## 6. Before / after

| 지표 | Before | After | Delta |
|---|---:|---:|---:|
| live_multihop.py | 2873 | 2835 | −38 |
| _typed_from_retrieval | 120 | 122 | +2, 명시적 callback 연결 |
| LiveOperatorFactory | 493 | 493 | 0 |
| _derive | 164 | 164 | 0 |
| central operator conditions | 6 | 6 | 0 |
| legacy trade helper span | 16+20 | 0 | −36 |
| new adapter module | 0 | 47 | +47 |
| new helper span | 0 | 10+23 | +33 |
| live AST If count | 375 | 371 | −4 |
| live + 새 trade adapter AST If | 375 | 374 | −1, 중복 action guard 제거 |
| live 넓은 책임 범주 | 12 | 12 | source adapter 범주 잔존 |
| Factory 넓은 책임 범주 | 8 | 8 | Factory body 미변경 |

live의 trade row membership/physical total binding 세부 책임 2개가 dedicated row adapter로 이동했다. source selection/공통 metadata map은 남아 있으므로 source adapter 책임 전체를 제거했다고 주장하지 않는다. 새 domain의 자동 등록 구조도 만들지 않았다.

## 7. Complexity Delta / Contract Delta

### Complexity Delta

- Files changed: production 2, tests 3, artifact 1. 기존 누적 dirty changes 제외.
- New classes / registry entries: 0 / 0.
- New public semantic contracts: 0; 내부 pure callable 경계 2개 relocation.
- New QA/question/entity/answer special cases: 0.
- New central-dispatch branches: 0.
- Removed branches: 중복 비-trade early-return guard 1개. live source 조건 3개는 adapter로 이동.
- Duplicated contract sources added/removed: 0/0. 본문 이동은 기존 alias/catalog 중복 debt 해결과 다름.
- Largest modified function: `_typed_from_retrieval` 122 LOC; 새 adapter 최대 23 LOC.
- Largest containing class: Factory 493 LOC(미변경). live의 기존 398 LOC 함수도 미변경.
- Largest modified module: 2835 LOC.
- Responsibility growth: false.
- Verdict: **COMPLEXITY_WARN / REFACTOR_CANDIDATE**, `DECOMPOSITION_REVIEW_REQUIRED` 유지. subset acceptance는 PASS.

module>1500, 독립 변경 이유≥3, 기존 중앙 조건/큰 함수 경고는 남아 있다. 테스트 통과를 전체 architecture PASS로 표시하지 않는다.

### Contract Delta

- New/modified/removed semantic contracts: 0/0/0.
- 실행 소유권만 변경: trade membership/declared metric normalization → 새 adapter.
- Canonical owners: 기존 ActionSlots.metric, Registry CountryShare metadata, 기존 strict resolver/base-column helper. adapter는 기존 physical mapping 알고리즘의 유일한 실행 owner.
- Consumers: `_typed_from_retrieval`→기존 Capability/Runtime/Projection/Relation.
- Remaining duplicated mappings: 공통 alias table vs resolver, Registry metric/type vs runtime map, resource metric mapping의 두 위치, presentation helper를 통한 unit 변환. 이번 migration에서 통합하지 않음.

## 8. Remaining inventory / recommendation

| 우선순위 | 잔여 subset | 위험 | 다음 판단 |
|---|---|---|---|
| 1 | **resource.rank의 physical total→production/reserves row 정규화만** | HIGH source boundary / 국소 body는 좁음 | Step 8 추가 1회 후보. 현행 16행 action block, collision/column rename/dict 순서/선행 status 위치를 그대로 고정해야 함 |
| 보류 | inventory.latest/series | MEDIUM/HIGH coupling | 독립 normalization body보다 공통 alias/type/metric 설정에 의존. 억지 분리 시 envelope/alias 복제 위험 |
| 보류 | trade.monthly/concentration/indicator, resource.yoy | HIGH | 공통 envelope와 semantic catalog/type 표현 소유권이 먼저 필요 |
| 후순위 | price / forecast | HIGH | criterion/cardinality/unit/provenance·latest 후처리 결합 |
| 후순위 | complex document/default evidence fallback | HIGH | row/Evidence dual payload·entity 추출·evidence completeness 결합 |
| 별도 경계 | shared alias/unit/envelope, action fan-out/merge, indicator period_change 후처리 | HIGH | 단순 domain 이동과 묶지 않음. Registry ownership/adapter boundary 계획 필요 |

**권고: Step 8을 resource.rank의 row normalization에 한해 한 번 더 좁게 계속한 뒤 Step 9 Catalog ownership cleanup을 우선 검토한다.**

trade와 resource의 total 처리 방식은 같지 않다. resource는 key rename/collision 및 dict insertion order에 따른 기존 결과를 가질 수 있어 trade adapter를 재사용하도록 바꾸면 semantic drift가 된다. 새 단계에서도 population/단위/country filter/value binding/공통 metric map까지 함께 이동하거나 고치지 않는다.

resource의 좁은 본문까지 이관한 이후 남는 inventory/기타 trade는 공유 metadata와 alias ownership 비중이 크다. 그때는 추가 파일 분리보다 Step 9가 구조적 ROI가 높다. 이 권고는 실행 승인이 아니며 **이번 작업은 여기서 종료**한다.

## 9. Rollback / stop boundary

이번 live import/call 변경 및 두 helper relocation, adapter 파일, 관련 test relocation/new test만 독립 rollback 대상으로 한다. frozen pre-subset source와 작업별 diff를 evidence에 보존했다. HEAD reset은 이전 migration을 지우므로 사용하지 않는다.

Step 9·다음 resource subset 자동 진행 없음. Full QA57·Strict·Product Golden 상태 변경 없음. 18002 및 18012 컨테이너 변경 없음.
