# 멀티홉 multi_action typed state 계약 — 2026-09-27 12:33:39 KST

## 범위

- 대상: `inhouse/rag_core/ragkit`의 복합 수치 Action과 `/pubchat`·`/prichat`
  세션 후속 턴
- 목표: 이전 성공 복합 조회의 기간·대상·지표를 답변 문자열이나 LLM 히스토리가
  아닌 typed state로 보존
- 제외: DB 스키마 변경, `expired/`, 페이지추천·문서·예측·진단 action 간 상태 전이,
  이미지 재배포

## 계약

- `RagTurnStateV1`/`CarryActionV1`/`CarrySlotsV1`은 whitelist된 대상·기간·지표
  슬롯만 저장한다. 원문, 인용, 수치, 경고, 메뉴·dataset·topic·출력 형식은 저장하지
  않는다.
- 성공한 동일 action-family의 2~4개 requirement만 상태 후보가 된다. 실패·부분 결과,
  이질 action 조합은 상속하지 않는다.
- `FollowupBindingV1`은 어떤 requirement에서 어떤 필드를 상속했는지 표현한다.
  명시된 광종·기간·상위 N은 이전 값보다 우선한다. 다중 metric의 단일 metric 변경처럼
  requirement 선택이 불명확하면 `context_ambiguous`로 닫는다. 허용 슬롯 외의
  새 의미 토큰(예: 가격)은 Planner를 우회하지 않는다.
- 세션 저장은 기존 `citations_json`의 versioned envelope를 사용한다. legacy citation
  배열과 기존 page/clarification metadata는 상태 없음으로 유지한다. UTF-8 3,800 byte를
  넘으면 citation을 bounded projection으로 줄이고, 상태 자체가 들어가지 않으면
  non-carry marker를 남겨 VARCHAR(4000) 절단·raw-history fallback을 막는다.
- public/private profile이 다르거나 완결된 새 질문이면 상태를 읽거나 병합하지 않는다.

## 구현·검증

- 구현: `multi_action_state.py`(상태·병합), `chatbot.py`(성공 Action 결과에서 상태
  생성·envelope 저장), `routers/chat.py`(최신 assistant 상태 로드·Planner 우회 병합).
- `test_multi_action_state`는 round-trip, legacy/프로필 격리, 광종·기간·상위 N 명시값
  우선, metric 모호성 차단, 가격 새 의도의 비병합, observed range가 있을 때만 같은 기간
  병합, non-carry marker, 완결 질문 비상속, Router의 Planner 우회 병합을 검증한다.
- 회귀: `test_multi_action_state`, `test_action_contract`,
  `test_action_contract_audit`, `test_action_result_composition`,
  `test_acceptance_module_boundaries` 총 **131 passed**; `py_compile`,
  `git diff --check` 통과.
- Sol 최종 차분 감사: HIGH/CRITICAL 잔존 없음. `top_n` 재검증, 명시 기간 우선,
  `이것도` 참조 토큰, oversized citation/state의 최종 바이트 상한을 재현 검증했다.

## 잔여 제약

- “같은 기간”은 requirement별 `observed_period`가 모두 같은 ISO date range일 때만 그
  range를 사용한다. 누락·불일치·연도만 있는 기준시점은 명확화로 닫는다. “같은 조건”은
  이전 요청 `Period`를 보존한다.
- 현 세션 잠금은 프로세스 로컬이다. 다중 worker 전환 전에는 DB turn-version 또는
  advisory lock으로 stale turn 경쟁을 막아야 한다.
