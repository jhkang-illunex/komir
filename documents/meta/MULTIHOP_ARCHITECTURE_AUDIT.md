# Conversational BI Multi-hop 실행 구조 분석 및 구현 계획

작성일: 2026-09-30  
대상 브랜치: `multihop_work`  
기준 커밋: `34bac9e42`

## 1. 현재 Natural Language → Answer 실제 경로

현재 외부 진입점은 `inhouse/rag_chat/app/routers/chat.py`의 `POST /pubchat`,
`POST /prichat`이다.

```text
HTTP 요청
  → _run_chat / _run_chat_session
  → 세션 조회 및 in-process session lock
  → FAQ·메뉴·clarification·기존 follow-up 특수 경로
  → extract_action_plan
       (legacy parser 또는 semantic_intent → IntentCall → ActionPlan)
  → validate_action_plan
  → rag_core.ragkit.chatbot.chat_turn
       → raw chat history 로드
       → pre-gate
       → retrieve_evidence(include_action_results=True)
            → action dependency 순서 계산
            → route 생성
            → MCP/RDB/PageIndex/Vector 조회
            → Evidence 생성 및 검증
            → ActionResult 결합
       → action/evidence별 결정적 renderer 또는 LLM composer
       → citation 검사 및 abstain 처리
       → ChatEvent(session/status/delta/table/chart/done)
  → router의 SSE framing
  → 기존 Streamlit SSE client
```

문서 질의는 `chat.py`에서 `chatbot.chat_turn`으로 직접 연결되고, page 질의는
별도 recommendation graph를 사용한다. 외부 wire contract는 router의 모듈 문서와
`streamlit_demo/api_client.py`, `streamlit_demo/chatbot.py`가 함께 정의한다.

## 2. 현재 intent / actor / action / tool 구조

### Semantic layer

`semantic_intent.py`는 이미 `SemanticPlan`과 `SemanticRequirement`를 제공한다.
metric, mineral, period, operation, selection, context reference를 타입화하지만,
복합 질의를 독립 requirement 목록으로만 다루며 의존성 그래프는 만들지 않는다.
semantic mode는 `off|shadow|enabled`이고 enabled에서도 legacy shortcut 및 legacy
LLM fallback이 남아 있어 1st-order 호환을 우선한다.

### Action layer

`action_contract.py`의 흐름은 대략 다음과 같다.

```text
자연어/semantic requirement
  → IntentCall
  → action_plan_from_intent
  → ActionCall(ActionId + ActionSlots + depends_on)
  → validate_action_plan
  → 기존 action별 route/retrieval
```

`ActionId`는 `price.*`, `trade.*`, `resource.*`, `mine.*`, `document.*` 등 실제
tool capability에 가까운 물리 action이다. `ActionSlots`는 기존 actor/tool 호출에
필요한 typed 입력을 가진다. `depends_on`은 존재하지만 ID 목록일 뿐 selector나
typed input binding을 표현하지 않는다.

### Retrieval / tool layer

`chatbot_graph.py`가 route를 계산하고, MCP wrapper와 `common/komis_raw.py`,
PageIndex, vector/document facts를 호출한다. 결과는 주로 `Evidence`로 정규화되고,
`ActionResult`는 성공/실패와 evidence 목록을 보관한다.

### Rendering / transport layer

`chatbot.py`가 action 조합별 결정적 renderer와 LLM composer를 함께 수행한다.
`chatbot_events.py`가 표·차트 payload를 만들고, `streaming.py`와 router가 SSE로
변환한다. 현재 Frontend가 의존하는 session/status/delta/table/chart/done 이벤트와
payload는 변경 대상이 아니다.

## 3. 2nd / 3rd / N-order가 깨지는 정확한 지점

1. `SemanticPlan`이 expression tree/DAG가 아니라 requirement 목록이다. 현재 prompt도
   복합 질의는 독립 requirement로 분해하고 dependency graph는 만들지 않도록 한다.
2. semantic resolver는 price rank와 resource ordinal처럼 이전 결과에 의존하는 선택을
   capability 부재로 거부한다. `TopK`, `ArgMax`, `Reference(index/filter)`를 표현할
   공통 노드가 없다.
3. `ActionCall.depends_on`은 정적 실행 순서만 표현한다. `상위 3개`, `그중`, `세 번째`,
   `그 결과의 수입액` 같은 selector와 입력 binding이 없다.
4. `retrieve_evidence` 뒤쪽의 동적 action 추가 로직이 evidence markdown/질문 문자열을
   다시 읽어 mineral을 추출한다. price/news, weekly, export-control, monthly trend 등
   여러 QA별 분기가 이 방식으로 연결된다. 이는 typed result가 아닌 문자열 전달이다.
5. `ActionResult`에는 value, result type, entity, metric, period, unit, provenance,
   upstream가 없어 후속 action이 안전하게 소비할 수 없다.
6. `ALLOWED_MULTI`, `COMPOSABLE_MULTI_ACTIONS`, answer contract가 허용된 action ID
   조합을 닫힌 목록으로 관리한다. 새 조합마다 예외를 추가하게 된다.
7. `multi_action_state.py`는 같은 action family의 짧은 follow-up과 한 단계 price
   context만 저장한다. 이전 ranking의 typed rows나 ordinal binding은 저장하지 않는다.
8. application history는 `chat_message`의 raw content와 압축된 citations JSON 중심이다.
   semantic AST, Pipe, bindings, evidence lifecycle을 first-class로 저장하지 않는다.
9. async는 현재 blocking graph를 thread/queue로 감싼 형태다. Step 단위 cancellation,
   timeout, safe concurrency, tool lifecycle event가 없다.
10. Langfuse 연동은 chat root와 LLM generation 중심이며 Pipe/Step/tool/evidence/
    renderer 계층을 관찰하는 adapter가 없다.

## 4. 재사용할 기존 component

- `ActionSlots`, `ActionCall`, 기존 action validator 및 source access gate
- `MCPClient`, `_mcp_tools_common.py`, `common/komis_raw.py`
- `Evidence`, `document_facts`, PageIndex/vector/RDB retrieval adapter
- 기존 evidence verification, citation index 검사, abstain 정책
- `chatbot_events.py`의 table/chart 변환기와 현재 SSE adapter
- `chatbot_store.py`의 session/message lifecycle
- 기존 `chat_turn` 및 1st-order renderer
- semantic mode의 `off|shadow|enabled` 운영 스위치와 기존 회귀 테스트
- `langfuse_tracing.py`의 optional/no-op 동작

새 계층은 위 actor/action/tool을 대체하지 않고 adapter로 감싼다.

## 5. 축소하거나 격리할 special-case

즉시 삭제하지 않고 새 Pipe 경로가 회귀 검증된 뒤 단계적으로 축소한다.

- 질문별 legacy parser helper와 exact action combination gate
- `retrieve_evidence` 내부의 질문/evidence text 재파싱 기반 동적 action 추가
- `multi_action_state`의 한국어 marker 중심 follow-up 해석
- action ID 집합에 따른 renderer 분기와 고정 answer contract 의존
- ActionPlan/Resolve/Action 사이의 단순 forwarding DTO

반대로 source permission, unsupported/data unavailable, evidence sufficiency,
citation 검증, FAQ/menu 보안 경계는 제거하지 않는다.

## 6. 제안 Semantic AST / Requirement IR

실제 tool 이름이 아닌 의미 연산을 표현하는 별도 typed IR을 둔다.

```text
Program
  nodes: RequirementNode[]
  roots: NodeId[]

RequirementNode
  node_id
  operator: Entity | Retrieve | RetrieveDocument | Filter | Project | Sort |
            Rank | TopK | Aggregate | Compare | ArgMax | ArgMin | Join |
            Calculate | ResolveReference | ValidateEvidence
  inputs: InputRef[]
  args: typed operator arguments
  expected_type
  constraints
  evidence_requirement

InputRef
  source_node
  selector: all | index(n) | field(name) | predicate(expr)
```

공통 값은 `Entity`, `Metric`, `TimeRange`, `Filter`, `Sort`, `Reference`,
`Projection`, `Calculation`으로 정규화한다. 예를 들어 “가격 상승률 상위 3개 중
수입액이 가장 큰 광물”은 `EntitySet → Retrieve(price) → Calculate(change) →
Rank → TopK → Retrieve(import, binding) → ArgMax`로 표현한다.

모델은 이 구조만 제안한다. 날짜·단위·operator type·dependency·tool capability의
검증과 normalization은 코드가 수행한다.

## 7. Typed Result / Binding schema

모든 Step 결과는 자연어가 아닌 다음 contract를 따른다.

```text
TypedResult
  status: success | partial | empty | failed | abstained
  result_type: MineralSet | MineralRanking | TimeSeries | TradeSeries |
               CountryShare | ScalarMetric | FactSet | DocumentEvidence |
               Table | Chart | Composite
  value
  entity / metric / period / unit
  source
  evidence[]
  provenance[]
  confidence / sufficiency
  upstream_step_ids[]
  warnings / failure_reason
```

`InputBinding`은 upstream `TypedResult`와 selector를 명시하고, bridge가 이를
`ActionSlots`로 fan-out하거나 단일 값으로 축약한다. downstream action에 raw text나
LLM이 만든 답변을 재입력하지 않는다.

## 8. AST → LangGraph DAG / Pipe lowering

```text
parse → normalize → reference resolve → type/constraint validate
      → topological lowering → Pipe(Step[]) → async execution
```

외부 API는 `Pipe`, `Step`, `InputBinding`, `Dependency`만 노출한다. Pipe를
LangGraph `StateGraph`의 typed execution state로 lowering하고, dependency가 없는
Step은 LangGraph가 안전하게 병렬 스케줄링한다. 각 Step에 timeout/cancellation/
retry/status/provenance를 부여한다. 순환, 미해결 reference, 빈 binding, 단위 불일치는
실행 전에 deterministic abstain/error로 끝낸다. 단순 조회는 기존 graph 경로를 유지하고,
새 StateGraph는 multi-hop Pipe에만 사용한다.

## 9. 기존 action/tool Bridge

`LegacyActionStep` adapter가 typed binding을 기존 `ActionCall`/`ActionSlots`로
변환하고, 기존 route/MCP/RDB/PageIndex 호출을 실행한다. 결과는 Evidence와 기존
검증기를 거쳐 `TypedResult`로 복원한다.

기존 1st-order는 현재 `chat_turn` 경로를 그대로 사용한다. Pipe가 필요한 질의만
새 orchestrator를 사용하며, 최종 결과는 기존 `ChatEvent`로 변환한다. Renderer는
canonical `ExecutionResult`를 만들고, protocol adapter가 현재 SSE payload로
encode한다. 내부 event와 외부 wire event는 동일시하지 않는다.

## 10. 단계별 migration plan

1. **Contract**: IR, TypedResult, InputBinding, Step/Pipe, ExecutionResult의 작은
   불변 모델과 serialization 테스트 추가.
2. **Runtime**: async DAG runtime, timeout/cancellation, no-op tracer, deterministic
   topological execution 추가. 아직 production route에 연결하지 않는다.
3. **Bridge**: 기존 ActionCall 하나를 실행하는 LegacyActionStep과 Evidence→TypedResult
   변환기를 추가하고 기존 action을 재사용한다.
4. **Context**: `HistoryStore` interface와 semantic turn envelope를 추가한다. 초기에는
   기존 `citations_json` 호환 저장을 사용하고, DB schema migration은 별도 검토한다.
5. **Renderer/Protocol**: canonical result와 기존 SSE adapter를 연결하고 wire contract
   golden test를 고정한다.
6. **Vertical slice**: ranking → TopK → typed binding → 재조회 → ArgMax 한 종류를
   generic operator 조합으로 end-to-end 구현한다. 질문별 branch는 추가하지 않는다.
7. **Multi-turn**: semantic history에서 `그중`, ordinal, 이전 result reference를
   deterministic하게 resolve하고 ambiguity만 model candidate resolution으로 보낸다.
8. **Replacement**: 기존 dynamic text parsing과 조합별 special-case를 shadow 비교 후
   축소한다. legacy fallback은 regression 종료 전 유지한다.
9. **Live verification**: unit/contract/QA, `git diff --check`, Docker build,
   service health, 실제 SSE, cancellation/tool failure 로그를 순서대로 검증한다.

이번 라운드의 구현 범위는 1~5와 6의 실행 가능한 최소 기반이다. 기존 container
재배포, 공유 DB migration, branch merge/commit은 현재 권한과 작업 범위에서 수행하지
않는다.

## 11. 테스트 계획

- IR schema, operator type check, date/unit normalization, cycle/unresolved reference
- TypedResult provenance/evidence/upstream 및 empty/partial/abstain contract
- Pipe topological order, safe concurrency, timeout, cancellation, failed dependency
- legacy action bridge와 기존 Evidence attribution
- 1st-order 기존 semantic/action regression
- 2nd-order retrieve→sort/compare/calculate/TopK
- 3rd-order rank→select→re-retrieve 및 multi-turn `그중`/`세 번째`
- RDB→document, document Fact→RDB mixed source
- 기간/단위/데이터 없음/잘못된 reference/빈 intermediate/tool failure/evidence 부족
- SSE event order, required fields, table/chart/citation/done golden contract
- text-only, text+table, text+chart, composite, abstain, disconnect cancellation

## 12. 예상 영향 파일

### 1차 추가/변경 후보

- `inhouse/rag_core/ragkit/semantic_ir.py`
- `inhouse/rag_core/ragkit/pipe_runtime.py`
- `inhouse/rag_core/ragkit/lowering.py`
- `inhouse/rag_core/ragkit/legacy_bridge.py`
- `inhouse/rag_core/ragkit/multihop_orchestrator.py`
- `inhouse/rag_core/ragkit/history_context.py`
- `inhouse/rag_core/ragkit/presentation.py`
- `inhouse/common/langfuse_tracing.py` 또는 별도 tracer adapter
- `inhouse/rag_core/ragkit/chatbot.py`의 legacy/Pipe 선택 boundary
- `inhouse/rag_chat/app/routers/chat.py`는 wire adapter 연결 시 최소 변경

### 영향 검증 대상

- `action_contract.py`, `action_results.py`, `chatbot_graph.py`
- `chatbot_store.py`, `chatbot_events.py`, `streaming.py`
- `inhouse/streamlit_demo/api_client.py`, `chatbot.py`
- 기존 semantic/action/terminal/SSE/acceptance tests

## 자체 감사 결과 및 결정

### High/Critical 위험

- 기존 ActionPlan과 새 IR을 동시에 바꾸면 1st-order 회귀와 원인 추적이 어려워진다.
- Frontend wire contract를 내부 event model과 혼동하면 즉시 UI 회귀가 발생한다.
- typed history 없이 parser만 확장하면 이전 turn의 잘못된 자연어 답변이 다시 입력된다.
- evidence 검증을 Pipe 후단으로 미루면 검증되지 않은 숫자/순위를 stream할 수 있다.
- 현재 retrieval은 blocking I/O이므로 async façade만 추가하면 cancellation이 실제
  tool까지 전달되지 않는다.

### 확정한 안전장치

- 기존 경로와 SSE schema는 기본 보존한다. orchestration runtime은 LangGraph를 사용하고,
  `PipeRuntime`은 Pipe를 LangGraph `StateGraph`로 컴파일하는 얇은 adapter로 둔다.
- 새 orchestrator는 feature flag와 shadow 비교를 거쳐 점진적으로 활성화한다.
- LLM은 AST 후보와 모호성 후보만 생성하고, binding/type/evidence/execution은 코드가
  결정한다.
- Pipe/Step 결과는 모든 단계에서 provenance와 evidence를 유지한다.
- 이번 라운드에는 사용자 질문별 if/else, 새 physical intent, 기존 검증 우회,
  destructive DB migration을 추가하지 않는다.

## 13. 실제 서비스 통합 감사 결과 (2026-09-30)

`MULTIHOP_ORCHESTRATOR_MODE=shadow` 별도 컨테이너에서 Gemma 4 계열의
schema-constrained AST를 실제 호출하고, AST→LangGraph Pipe→기존 `ActionCall`/
`retrieve_evidence` bridge를 실행했다. `price_change_rate`/`import_value`처럼
domain이 생략된 model metric, 영문 광종 alias, 잘못 생성된 root, 비정규 history alias를
기존 IR/Binding contract 안에서 정규화했다. 단순 질의는 기존 경로를 유지하고 legacy
ActionResult를 typed semantic history에 기록한다.

실제 SSE에서는 기존 `status`, `table`, `chart`, `done` event와 citation/abstain payload가
그대로 유지되는 것을 확인했다. `enabled` 모드에서도 신규 Pipe 결과는 기존 ChatEvent
경계로 전달되며, 근거 부족 결과는 숫자를 생성하지 않고 `abstained=true`로 종료한다.

동일 session 4턴 검증에서는 1턴 legacy price 결과가 typed history에 저장되고, 2턴의
`그중`/기간 filter가 해당 binding을 사용했으며, 3턴은 price history와 수입 조회를
병렬 dependency로 구성한 뒤 수입 데이터 부족을 abstain했다. 4턴의 ordinal/document
reference도 typed binding으로 resolve되며 대상 row가 없을 때 selector failure가
Pipe `FAILED`로 변환되어 기존 SSE abstain 경로로 내려간다.

실서비스 검증 blocker는 orchestration에서 우회하지 않았다.

- PageIndex tree mount가 없는 이미지에서는 PageIndex retrieval이 실패한다.
- 현재 연결 DB에는 `public.ai_hs_mnrl_map`이 없어 무역 조회가 실패한다.
- 기존 `komis_price_volatility_ranking` tool은 `_any_dummy` NameError를 반환한다.
- application history는 현재 `InMemoryHistoryStore`이므로 단일 프로세스 검증용이며,
  재시작·다중 worker 영속성은 후속 HistoryStore backend 작업으로 남아 있다.

위 blocker 때문에 가격 ranking→TopK→수입 ArgMax의 실제 수치 성공을 주장하지 않는다.
다만 AST, dependency, 기존 tool 호출, evidence validation, deterministic abstain 및
기존 SSE까지의 서비스 경로는 확인했다. PostgreSQL/PageIndex/OKF/Frontend protocol은
이번 통합에서 수정하지 않았다.
