# History Isolation Contract — 2026-10-03

## 범위

- 목적: self-contained query가 이전 history를 상속하지 않도록 제한
- 멀티턴 기능: 유지
- 변경 금지: 새 planner/execution layer, Capability, Renderer, 운영 `18002`
- 검증 포트: `18012`
- 이미지: `komir-rag-chat:history-isolation-r1-20261003`
- image ID: `sha256:d2606d0700a77025a5d29e28537a1783b925b66ae65564534d3139a25e1c0190`
- container: `komir-rag-chat-qa57-fa423`

## 구현

기존 `_history_for_action_query()`를 공통 경계로 재사용하고, `history_is_required()`를
추가했다. 현재 질문에 명시된 entity/metric이 있으면 history를 비우고, `그중`,
`그 국가`, `아까`, `같은 기간`, `이전 결과` 등 현재 문장만으로 대상을 결정할 수 없는
reference 표현이 있을 때만 history를 통과시킨다.

적용 지점:

- `action_contract`: 공통 history requirement 판정
- app router: gate/action-plan에 선택된 history만 전달
- `chatbot.chat_turn`: legacy retrieval/generation에 선택된 history만 전달
- `live_multihop.run_live_multihop`: 독립 query면 저장된 typed `ConversationContext`를
  현재 AST parsing/coverage/resolve에서 차단

trace에는 다음을 남긴다.

```text
history_resolution session=... history_used=true|false
source_turns=... selected_turns=...
```

독립 query의 저장 결과 자체는 삭제하지 않으며, 현재 turn의 context 입력만 제한한다.

## 결정론적 unit test

관련 semantic test와 live runtime test:

- `test_semantic_intent.py`: 52 passed
- `test_live_multihop.py`, `test_multihop_runtime.py`,
  `test_terminal_event_contract.py`, `test_semantic_intent.py`: **107 passed**

검증 중 발견한 `get_context()` await 오류는 history 경계 구현에서 즉시 수정했고,
최종 107개 targeted test에는 남아 있지 않다.

## 실제 18012 SSE 검증

### 독립성 stability probe

대표 6개 QA에 대해 fresh history 3회와 unrelated dirty history 3회를 실행했다.
dirty history는 먼저 `리튬 가격 전망 알려줘`를 실행한 뒤 대상 질문을 실행했다.

| QA | Fresh | Dirty | history trace | Semantic divergence | AAST divergence |
|---|---:|---:|---|---|---|
| GM02 | 3/3 완료 | 3/3 완료 | 양쪽 `history_used=false` | 없음 | 없음 |
| ADD16 | 0/3 content, 동일 abstain | 0/3 content, 동일 abstain | 양쪽 `history_used=false` | 없음 | 없음 |
| ADD15 | 3/3 완료 | 3/3 완료 | 양쪽 `history_used=false` | 없음 | 없음 |
| GM08 | 3/3 완료 | 3/3 완료 | 양쪽 `history_used=false` | 없음 | 없음 |
| MP03 | 3/3 완료 | 3/3 완료 | 양쪽 `history_used=false` | 1회 plan/output hash 차이 | history 기인 증거 없음 |
| ADD27 | 3/3 완료 | 3/3 완료 | 양쪽 `history_used=false` | 없음 | 없음 |

핵심 결과:

- history 사용으로 인한 독립 query의 의미 오염: **0건 관찰**
- `MP03`의 fresh 변동은 dirty history와 직접 대응하지 않았으며, 기존 모델/계획
  비결정성 잔여로 분리했다.
- `ADD16`의 `calculation_field_unavailable`은 fresh/dirty 모두 동일했다.

### 명시값 우선

동일 session에서 다음을 실행했다.

1. `리튬 가격 알려줘`
2. `니켈 가격 알려줘`

두 번째 turn의 trace는 `history_used=false`, `selected_turns=0`이었다. 결과는
리튬이 아닌 니켈 기준으로 실행됐다. 첫 번째 리튬 질의의 criterion mapping 실패는
기존 source/criterion blocker이며 이번 history 변경과 무관하다.

### 정상 후속

1. `니켈 수입 상위국 알려줘`
2. `그중 중국 비중은?`

두 번째 turn은 chatbot/live trace 모두 `history_used=true`로 기록되었고,
`selected_turns=2/1`이 확인됐다. 즉 typed history 경로는 선택되었다. 다만 이
실제 데이터 실행은 기존 `semantic_plan_incomplete`로 종료되어 content PASS는
아니다. 이는 history 차단으로 인한 실패가 아니라 후속 semantic/runtime blocker다.

### 기간 후속

1. `니켈 최근 1년 가격 추이`
2. `그중 최근 3개월만 보여줘`

두 번째 turn은 `history_used=true`, live context `selected_turns=1`이었다. entity는
이전 typed result에서 참조하도록 허용되고 현재 period 3개월은 현재 질문이 우선된다.
실행은 기존 `upstream step failed: node_4`로 종료되었으며, period filter의 runtime
계약 문제로 기록한다. 이번 변경에서 우회하지 않았다.

## Cache 확인

AST cache는 프로세스 전역 `_AST_CACHE`지만 key는 `model`, `question`,
`semantic_history`를 포함한다. 독립 query에서는 history를 빈 context로 정규화한
뒤 AST를 생성하므로 dirty history 때문에 별도 history-dependent AST를 재사용하지
않는다. cache hit/miss 구조 자체는 변경하지 않았다.

## 잔여 모델 비결정성

`temperature=0`인 clean 18012에서도 `MP03`의 fresh 반복 중 plan/output hash가
달라졌다. 이는 history contamination이 아니라 기존 Gemma/repair/tool 응답의
비결정성 후보로 남긴다. 이번 범위에서 seed, sampling, prompt, retry 정책은
변경하지 않았다.

## 회귀/배포

- 18002: 변경 없음
- QA57 full replay: 수행하지 않음
- 관련 unit/runtime: 107 passed
- history contract 오류: 최종 targeted test에서 0
- 신규 history isolation regression: 0
- 후속 execution blocker: 기존 `semantic_plan_incomplete`, `upstream step failed`

이번 검증은 history 사용 여부와 경계 분리까지 완료한 것이며, 기존 후속 질문의
실행 실패를 성공으로 승격하지 않는다.
