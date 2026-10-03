# Architecture V1 Step 12 — Presentation seam extraction / final checkpoint

## 결론

**Step 12 acceptance: PASS. Architecture V1: READY_WITH_KNOWN_DEBT.**

- Frozen-old/new ChatEvent 결정론적 비교 **2,048/2,048 일치**, 저장 graph **17/17 일치**.
- 신규 presentation characterization **86 old / 86 new PASS**, 기존 targeted **46 PASS**.
- rag_core **2334 passed / 0 failed / 695 subtests**, rag_chat **155 passed / 동일 known legacy failure 1건 / 15 subtests**. 신규 회귀 0. 전체 테스트가 모두 green이라고 주장하지 않는다.
- `_result_events`: **168 → 2 LOC**. 요청의 약 335 LOC가 아니라 실제 Step11 working tree의 AST/물리 행 기준 168이 출발점이다.
- 새 클래스·parallel renderer·transport abstraction·semantic contract·QA 특례 0.
- **18002/18012 미변경**, image build/deploy 없음. Full QA57, Strict/Product Golden 갱신 없음.
- Certified Product Golden은 **NOT_CERTIFIED_WITH_KNOWN_REASONS** 그대로다. 이번 PASS는 제품 정확도 인증이 아니다.

## 1. Baseline 및 evidence identity

- Golden parent `979fd3f980bb10af74a218cc6e07bada110e76de`, branch `multihop_work`.
- 실제 Step12 baseline은 parent + 승인된 Step1–11 누적 working tree다. clean Golden HEAD와 동일하다고 주장하지 않는다.
- [Step11](OUTPUT_COVERAGE_DIAGNOSTICS_STEP11_20261004.md) acceptance PASS: core2248, chat155+known1.
- scratch `/tmp/komir-presentation-step12.pwNoJK`.
- durable evidence `/home/nuri/.codex/validation-evidence/presentation-step12-20261004`의 `manifest.json`에 frozen source, 현재 source hash, full differential, 실행 로그, 구조 측정, 독립 감사, artifact를 봉인한다.
- 이전 Step11 evidence 45개 파일 checksum 불변 확인. 이전 evidence/artifact는 덮어쓰지 않는다.
- 보호 container `komir-rag-chat-18002`, `komir-temporal-step7`: ID/image/Created/StartedAt/config hash/mount 전후 동일. source 수정은 host checkout에만 존재한다.

## 2. Responsibility pre-audit

`iterative-audit`의 Architecture/Contract/Complexity/Regression/Decomposition Guard를 적용했다. 구조 migration 및 observable SSE 경계이므로 독립 사전/사후 감사와 결정론적 differential을 수행했다. 구현 1회이며 의미 개선 반복은 하지 않았다. `qa-build`는 기존 동작의 fixture/characterization에만 사용했다. 신규 QA/corpus/oracle 0; frozen 실행과 충돌하는 semantic expectation을 도입하지 않았다.

| 범주 | 기존 `_result_events` 책임 | Step12 owner | 유지/부채 |
|---|---|---|---|
| A Selection / orchestration | status/shape 우선순위, 재귀 composite, 완료 child 수 | `presentation_events` | 순서가 있는 callable composition. 질문/intent 접근 없음 |
| B Canonical presenters | text/list/table/chart, 일반 PARTIAL summary | `canonical_presenters` | 기존 table_block/chart_spec 재사용; table→chart 조합 |
| B Failure / Composite | failure 선택, child 반복 및 parent PARTIAL | `presentation_events` | 가격/일반표/composite의 PARTIAL 의미를 합치지 않음 |
| C Event assembly | delta/done/citations, source index, block/data reference prefix | `presentation_event_assembly` | 기존 ChatEvent payload, 순서, 누락 필드까지 보존 |
| D Compatibility | snapshot list→TypedResult children, document text, latest-price/physical keys/unit code, chart unit gate | `presentation_compatibility` | `DEFERRED_PRESENTATION_RESPONSIBILITY`; canonical source semantics로 승격하지 않음 |

### 기존 abstraction을 그대로 사용하는 이유

`presentation.Renderer`는 `ExecutionPresentation` envelope를 생성하지만 기존 live 이벤트 경로는 root TypedResult를 직접 사용한다. 이 envelope를 재정의하거나 단일 TableResult로 composite를 억지 변환하면 기존 복수 이벤트/재귀 계약이 바뀐다. 두 파일 `presentation.py`, `chatbot_events.py`는 **byte-identical**이다.

추가 구조는 함수 composition이며 새 BaseRenderer/Protocol hierarchy, RenderModel, scheduler, transport protocol을 만들지 않았다. `VALUE_PRESENTERS`의 세 등록 항목은 text/list/table이라는 실제 기존 use case다. 상위 route는 **첫 일치**, 일반 value composition은 **일치 presenter의 순차 조합**이라는 차이를 그대로 둔다. 자동 plugin discovery를 구현했다고 주장하지 않는다.

### Pre-change / decomposition 판단

- 원래 함수는 명확한 typed input/ChatEvent output이 있지만 독립 변경 이유가 10개 이상이고 failure 소유자를 알기 위해 전체를 읽어야 했다.
- 기존 ChatEvent/table/chart helper와 pure function 경계가 재사용 가능하다.
- 새 개념 추가가 아니라 책임 위치 변경이다. physical price mapping은 compatibility로 이동하며 source adapter에 복제하지 않는다.
- `_result_events`는 wrapper만 남고, event index 문제는 assembly, table/chart 문제는 presenter, snapshot/가격 문제는 compatibility에서 국소적으로 확인 가능하다.
- 일반 presenter 추가는 ordered tuple에 등록/조합하면 되며 live의 중앙 if/elif를 늘릴 필요가 없다. 복합 child는 같은 `present` callback을 재사용한다.

## 3. 경계와 보존한 계약

```text
live_run_events(root TypedResult)
  → _result_events (compatibility wrapper; row_date / lazy today 주입)
  → presentation_events (ordered selection + recursive composition)
      ├─ canonical_presenters → existing table_block / chart_spec
      ├─ presentation_compatibility (frozen legacy policies)
      └─ presentation_event_assembly
  → existing ChatEvent sequence → existing SSE consumer
```

Presenter는 TypedResult와 좁은 row-date/clock callback만 받는다. question, Gemma, planner, factory, session, DB, 전체 live module 참조가 없다. `WHAT`을 재해석하지 않는다.

보존한 주요 비대칭/실패 동작:

1. failure outcomes table 생성은 status 검사보다 먼저다. 실패 표의 literal `status != "success"`와 가격 선택의 casefold 비교를 통합하지 않았다.
2. terminal failure는 delta→done, rejected citation을 추가하지 않고 `bogus_citations`도 기존처럼 생략한다.
3. snapshot duplicate key는 덮어쓰되 insertion order는 유지한다. snapshot에서 기존에 옮기지 않던 entity/metric/upstream 정보를 새로 채우지 않는다.
4. composite child 순서와 heading, child done 제거, completed 계산, non-Typed child가 denominator에 남는 동작, source 중복 제거 범위를 보존한다.
5. child의 최상위 `source_index`만 재매핑하고 block_id/data_ref에 prefix를 붙인다. source_label/nested payload는 임의 교정하지 않는다.
6. 가격은 기존 latest/date resolver와 원래 tie/first-row fallback을 사용한다. 미래 날짜만 존재하면 버리고, `today()`를 각 해당 행에서 lazy 호출한다. 날짜를 한 번 고정하거나 새 정렬 규칙을 만들지 않는다.
7. 가격 physical field 우선순위와 unit code 해석은 기존 `_verified_display_unit`/`_price_unit_from_codes`를 소비한다. 새로운 alias/unit/criterion inference가 없다.
8. 일반 mapping→single-row list, DocumentEvidence 객체의 text join, 빈/unsupported 값의 서로 다른 abstain reason을 보존한다.
9. 표의 column union/row 문자열/markdown, source_index=1 기본값, 차트의 unit eligibility와 heterogeneous warning을 보존한다.
10. 세 종류 PARTIAL 문구의 내용과 위치를 각각 유지한다. plain/price의 duplicate citations와 composite의 dedup을 합치지 않는다.

Presentation/transport는 완전히 독립된 중간 모델까지 분리하지 않았다. presenters는 기존 ChatEvent와 table/chart wire helper를 조합한다. SSE socket/stream/lifetime은 계속 기존 transport가 소유하며 새 resource acquisition이 없다. wire 모델 결합은 명시적 잔여 부채다.

## 4. 검증

| 검증 | 결과 | 범위 |
|---|---:|---|
| Frozen-old/new event differential | **2048/2048, mismatch 0** | status/type/value matrix, text/list/table/chart/no-chart, invalid payload exception, document, composite/snapshot, source/citation, future/overlap/tie/unit, 두 as-of clock 및 saved TypedResult |
| 저장 graph replay | **17/17 동일** | 기존 graph input 그대로; source를 저장 evidence로 재구성. execution/root/TypedResult/presentation/SSE/action 호출 비교, network tripwire |
| 신규 characterization frozen old | **86 passed** | old 함수와 원래 import를 in-memory 복원. current unchanged helper 사용 |
| 신규 characterization current | **86 passed** | wrapper 포함 실제 현재 경로, clock 호출 횟수, nested remapping, 빈 mapping, known quirks |
| 기존 presentation 영향 tests | **46 passed** | price fanout, live contract repair, parser feedback |
| rag_core 전체 | **2334 passed, 1 warning, 695 subtests / 43.07s** | baseline2248 + 신규86, 신규 failure 0 |
| rag_chat 동일 scope | **155 passed, 1 known failed, 15 subtests / 6.35s** | baseline과 동일 test ID/reason |
| scope / immutable evidence | **PASS** | live의 `_result_events` 외 모든 top-level 함수/class AST 동일, presentation/chatbot_events byte 동일, Step11 45파일 checksum 동일 |

같은 known failure:

`inhouse/rag_chat/tests/test_sse_cancellation.py::test_disconnect_stops_real_ast_retry_before_blocking_invocation_returns[legacy_control-False]` → `LivePlanError: semantic_plan_incomplete`.

core의 Pydantic forward-reference warning도 PASS 수나 semantic recovery로 해석하지 않는다.

정확한 실행 명령:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:inhouse:inhouse/rag_chat python3 /tmp/komir-presentation-step12.pwNoJK/validate_presentation.py
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:inhouse:inhouse/rag_chat python3 /tmp/komir-presentation-step12.pwNoJK/evidence_helpers.py graphs
bash /tmp/komir-presentation-step12.pwNoJK/frozen_presentation_tests.command.sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:inhouse:inhouse/rag_chat python3 -m pytest -q -p no:cacheprovider inhouse/rag_core/tests/test_presentation_seam.py
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:inhouse:inhouse/rag_chat python3 -m pytest -q -p no:cacheprovider inhouse/rag_core/tests/test_live_price_fanout.py inhouse/rag_core/tests/test_live_contract_repair.py inhouse/rag_core/tests/test_live_parser_contract_feedback.py
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:inhouse:inhouse/rag_chat python3 -m pytest -q -p no:cacheprovider inhouse/rag_core/tests
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:inhouse:inhouse/rag_chat python3 -m pytest -q -p no:cacheprovider inhouse/rag_chat/tests
```

pytest는 매번 새 프로세스이고 cacheprovider/bytecode 쓰기를 끈다. live model이나 shared cache를 재시작하지 않았다. 두 포트에 요청/배포하지 않았다. 저장 graph는 live 재측정이나 Strict PASS 판정이 아니다.

독립 감사: 신규 High/Critical 미발견. 2,048개 full record, 17개 graph, source hash/AST 검사 및 regression 로그를 별도로 확인했다. compatibility debt가 해결됐다는 과대 주장을 금지한다.

## 5. Step12 Complexity Delta

| 지표 | Before | After |
|---|---:|---:|
| live_multihop.py | 2666 | **2501** |
| LiveOperatorFactory | 337 | **337** |
| `_derive` | 5 | **5** |
| central operator conditions | 4 | **4** |
| `_result_events` | 168 | **2** |
| live의 presentation 선택 정책 body | 7 (status/snapshot/mapping/latest/text/list/table) | **0**, 해당 정책은 composition에 보존 |
| 새 selection/composition 모듈 | 0 | 77 |
| 새 canonical presenter 모듈 | 0 | 68 |
| 새 event assembly 모듈 | 0 | 38 |
| 새 compatibility 모듈 | 0 | 122 |

- Step12 files: production **5** (live 1변경 + 신규4), test **1**; artifact/WORKLOG 별도.
- New classes **0**, new semantic/public wire contracts **0**. 내부 callable seam 4개 모듈; 신규 type system 없음.
- 등록/조합 항목: 기존 동작 3 value presenter + 상위 ordered route 4개/기본 fallback1. 신규 capability/operator registry entries **0**.
- New special-case branches **0**; QA/question/entity branches **0**; new central-dispatch branches **0**.
- Removed legacy body: `_result_events`의 기존 **167행 body** 제거, wrapper 1행 body로 대체. 선택 정책 자체를 지웠다고 주장하지 않는다.
- Duplicated contract sources added **0**. domain alias owner 합치기 **0**. success done/citation payload assembly는 공통 helper를 소비하고 abstain payload는 별도 유지한다.
- Largest new/modified presentation function **31 LOC**. live의 미변경 최대 함수398, Factory337, module2501은 기존 부채다.
- Responsibility growth **false**. 원래 정책을 locality별로 이동; 실행·source 의미를 새로 학습하지 않음.
- Verdict **COMPLEXITY_WARN / REFACTOR_CANDIDATE**, scoped acceptance PASS.

`DECOMPOSITION_REVIEW_REQUIRED`는 live>1500, normalizer398, relation263, 기존 parser180 HIGH 및 compatibility의 서로 독립적인 정책 묶음 때문에 남는다. compatibility122행을 LOC만 줄이려고 여러 파일로 추가 분해하지 않았다. 현재는 함수별로 테스트 가능한 책임이며 후속 semantic owner migration은 별도 승인/동등성 검증이 필요하다.

## 6. Contract Delta / deferred responsibility

- New semantic contracts **0**, modified semantics **0**, removed semantic contracts **0**.
- Modified ownership: `_result_events`의 선택/표현/event assembly/legacy compatibility 책임을 좁은 함수로 이동.
- Authoritative owners: TypedResult/ResultStatus는 PipeRuntime, semantic type은 Semantic IR, ChatEvent/table/chart/display-unit은 기존 chatbot_events, 실행 presentation envelope는 기존 presentation. Step9 capability_specs의 선언을 변경하거나 display schema로 다시 정의하지 않았다.
- Consumers: live_run_events wrapper, recursive composite, canonical presenters, 기존 SSE consumer. planner/coverage/Capability는 이번 seam을 소비하지 않는다.
- Remaining duplicated mappings: source alias/price physical interpretation과 display compatibility의 유사 규칙, Projection compatibility, `_typed_unit`의 display-unit helper 의존, Step9 `DEFERRED_CONTRACT_OWNERSHIP`. 동등성을 증명하지 않은 rule union을 하지 않았다.

`DEFERRED_PRESENTATION_RESPONSIBILITY`:

1. document/snapshot→typed children 변환과 누락 metadata.
2. per-entity latest-price selection, future-date 제외, physical date/price keys, unit-code compatibility.
3. price/warning별 chart unit eligibility.
4. nested citation remapping의 기존 제한과 failed child source 포함.
5. Presenter와 ChatEvent wire 형식의 결합, ExecutionPresentation envelope와 live protocol adapter의 두 기존 경로.

## 7. Architecture V1 final checkpoint — Step1~12

| 구조 지표 | Golden V1 초기 | 최종 |
|---|---:|---:|
| live_multihop.py LOC | 3057 | **2501** |
| LiveOperatorFactory LOC | 627 | **337** |
| `_derive` LOC | 352 | **5** |
| central operator conditions (Factory AST If에서 node.operator 검사) | 15 | **4** |
| `_result_events` LOC | 168 | **2** |
| execute_relation LOC | 308 | **263** |
| relational_ops.py LOC | 323 | **279** |
| 등록형 operator family / ID | 0 / 0 | **7 / 11** |
| dedicated source-result adapter | 0 | **3** (indicator.series, trade.country_rank, resource.rank) |
| 독립 temporal component | 0 | **1** |
| deterministic output coverage diagnostic | 0 | **1** |
| domain capability_specs 모듈 | 0 | **5** |
| Step9 측정 subset의 중복 선언 초과 occurrence | 11 | **0** (10 facts / 21 literals→10 owners) |
| Step11 exact set difference 알고리즘 owner | 2 | **1** |
| rag_core | 1560 | **2334**, 신규 regression0 |
| rag_chat | 155 + known1 | **155 + 동일 known1** |

Repository 전체의 duplicated contract source가 0이라는 뜻은 아니다. 측정 subset과 algorithm ownership 수는 서로 다른 단위이므로 합산하지 않는다.

남은 `REFACTOR_CANDIDATE`:

- graph normalization/repair (`_normalize_relation_contract`398), model parsing/retry/cache (`_parse_ast`180), History/materialization 연결부. 이번에 의미를 변경하지 않음.
- relation263의 join/compare/alignment/operand role/metadata 책임. temporal만 이미 분리.
- 공통 source envelope, price/forecast/document, action slot/type/metric 및 alias ownership의 미입증 중복.
- Projection compatibility와 presentation compatibility; 기존 renderer physical/unit 정책.
- thin factory의 ENTITY/FOR_EACH/VALIDATE_EVIDENCE/legacy retrieval 및 source post-processing 잔여 책임.

Known semantic/product debt는 그대로 보존한다: provenance contamination/DEV_DUMMY/DUMMY_LOAD, 미인증 Product Golden, ADD16 reduction ambiguity, CN08 unit, REG04 population 평균, planner/output composition gaps 및 model nondeterminism. 테스트 PASS 증가는 QA57 Strict 상승이 아니다. 과거 21/57 또는 21/53을 이번 refactor에서 재인증하지 않는다.

Architecture V1은 **READY_WITH_KNOWN_DEBT**: 승인된 12개 scope의 migration/evidence가 있고 현재 전체 회귀에서 신규 실패가 없으며 확장 책임이 국소화됐다. 모든 부채 해소 또는 제품 release 승인이라는 의미는 아니다.

## 8. Commit / push boundary

사용자 승인에 따라 Architecture V1 누적 변경만 현재 `multihop_work`에 커밋/푸시한다. test helper 변경은 legacy private `_derive` 호출을 실제 registered build/execute 경로로 연결한 것이며 oracle expectation을 완화하지 않았다. iterative-audit skill diff는 앞서 승인된 영구 Decomposition Guard 추가이며 관련 artifact와 함께 포함한다.

사전 검토: tracked/untracked diff, source/test/artifact 범위, secret/credential, generated cache/build/temp 제외. frozen/differential raw는 위 외부 evidence 경로에 보관하고 git에 넣지 않는다. 정확한 생성 commit SHA/remote SHA/clean 상태는 커밋 이후 git 자체와 완료 보고로 확인한다(이 문서에 자기 commit SHA를 미리 만들어 적지 않는다).

Step12 이후 추가 작업으로 자동 진행하지 않는다. 18002/18012, QA57/Strict/Product Golden은 그대로 유지한다.
