# Direct Capability Execution Audit (2026-10-02)

## 배포 범위

- 검증 이미지: `komir-rag-chat:direct-capability-r1`
- 검증 포트: `18012`
- 운영 이미지/포트: `komir-rag-chat:audit-safety22` / `18002` 유지
- 이전 검증 컨테이너: `komir-rag-chat-qa106-contract-r5-pre-direct-r1` 보존
- Renderer/SSE wire contract: 변경하지 않음

## 구현

### 추가된 경계

`inhouse/rag_core/ragkit/direct_capability.py`에 typed `ActionPlan` 전용 검증기를
추가했다.

검증기는 raw query, QA ID, confidence, history를 읽지 않는다.

1. ActionPlan이 존재하고 plan validation을 통과하는지 확인
2. required slot이 모두 materialize 되었는지 확인
3. dependency/input binding이 없는지 확인
4. 단일 Action이면 `direct`
5. 동일 Action + 독립 entity 반복이고 slot fingerprint가 동일하면 `map`
6. 혼합 Action, dependency, binding, 모호한 slot은 명시적 이유와 함께 `ast`

Map은 현재 `price.series`, `trade.country_rank`에만 제한했다. Map의 각 호출도
기존 `retrieve_evidence`와 Action adapter를 사용한다.

### Executor 공유

Direct 실행은 `chat_turn(execution_mode="direct", action_plan=...)`으로 기존
`retrieve_evidence`/Action/Renderer 경로를 호출한다. AAST 경로도 같은 executor를
사용한다. Direct 모드에서는 AAST 생성 단계만 건너뛰며, 데이터 조회·evidence·SSE
생성은 별도 구현하지 않았다.

실제 코드 변경:

- `inhouse/rag_core/ragkit/direct_capability.py`
- `inhouse/rag_core/ragkit/chatbot.py`
- `inhouse/rag_chat/app/routers/chat.py`
- `inhouse/rag_chat/tests/test_direct_capability.py`

## 단위 검증

- Direct/Gate/기존 routing/cancellation: **31 passed**
- 신규 Direct contract tests: 단일 Direct, Map, dependency escalation,
  composition escalation, 기간 차이 보존
- 전체 rag_core: **1454 passed, 695 subtests passed, 1 warning**
- `compileall`: PASS
- `git diff --check`: PASS

## 실제 18012 SSE 검증

### Direct

질문: `최근 니켈 가격 얼마야?`

```text
Query Gate: COMPLEX
Direct candidate: price.series
Contract: VALID
Execution mode: direct
AAST trace: 없음
SSE: DONE / abstained=false
결과: 2026-10-01 니켈 가격 23,111.69 USD/톤
표: 1개
citation: public.KO_MNRL_PRC
```

### AAST escalation

질문: `니켈은 어디에 쓰이고 지금은 얼마야?`

```text
Direct candidate: composition_required
Execution: 기존 AAST
AST roots: document usage + latest price
두 branch: success
SSE: DONE / abstained=false
```

질문: `니켈 가격 추이랑 광물 종합지수 추세 비교해주세요`

```text
Direct candidate: composition_required
Execution: 기존 AAST
price branch: success
indicator branch: no_data
final: dependency_unavailable
```

Direct가 backend 장애나 복합 질의를 성공처럼 숨기지 않는 것을 확인했다.

### 기존 fast path

`리튬 가격 화면으로 가줘`는 기존 `NAVIGATION → page_recommend` 경로를 유지했다.

## QA106 answerable 57 재실행

독립 session으로 57건을 새 이미지에서 실행했다.

실행 원장:

- [raw JSON](</home/nuri/.codex/worktrees/6ae2/komir/documents/meta/direct_capability_qa106_r1/user_qa_pair_audit_20261002_145520.json)
- [SSE audit report](</home/nuri/.codex/worktrees/6ae2/komir/documents/meta/direct_capability_qa106_r1/user_qa_pair_audit_20261002_145520.md)

### SSE/marker 보조 집계

| 상태 | 건수 |
|---|---:|
| PASS | 23 |
| PARTIAL | 17 |
| FAIL | 16 |
| BLOCKED_DATA | 1 |
| 합계 | **57** |

이 PASS 23건은 기존 질문별 marker/SSE 보조 판정이며, 내용 정답률로 직접
해석하지 않았다.

### 기존 content oracle 비교

기존 `qa106_grounded_comparison_20261002.csv`의 oracle answer와 새 응답을
동일한 보조 규칙으로 비교한 결과:

| 비교 결과 | 건수 |
|---|---:|
| CONTENT_EXACT | 9 |
| NUMERIC_SUPPORT_REVIEW | 5 |
| CONTENT_REVIEW | 43 |
| 합계 | **57** |

`CONTENT_REVIEW`는 자동 비교만으로 의미 일치를 확정할 수 없다는 뜻이며 PASS가
아니다. 따라서 이번 Direct Layer만으로 기존 content accuracy `23/57`이
상승했다고 주장하지 않는다. 동일 기준의 보수적 answerable baseline은 **23/57**로
유지된다.

## Direct/AAST 관측

현재 실행 로그에서 확인된 대표 경로는 다음과 같다.

```text
Direct:
query_gate → direct_capability(price.series) → execution_mode=direct → executor

Composite:
query_gate → direct_capability(COMPOSITION_REQUIRED) → existing_ast → AAST → executor
```

현재 단일 실행 샘플의 Direct 성공은 확인했으며, 복합 질의는 AAST로 격리됐다.
Map contract는 단위 테스트로 entity identity/order와 기간 차이 보존을 확인했다.

## 남은 제한

- Direct 후보 ActionPlan은 기존 typed semantic/action parser가 생성한다. Direct
  validator는 누락된 semantic requirement를 복구하지 않는다.
- `price.series`와 `trade.country_rank`의 Map은 독립 반복에만 열려 있다. 결과
  간 rank/compare/join이 추가되면 AAST로 승격한다.
- 데이터 부재, forecast 부재, evidence 부족은 Direct에서 AAST 재시도로 숨기지
  않는다.
- 18002에는 이미지나 프로세스 변경을 적용하지 않았다.
