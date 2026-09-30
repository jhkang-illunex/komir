# Semantic Regex Boundary Audit

기준일: 2026-09-30

## 범위

신규 semantic/multi-hop 경로와 직접 연결된 `action_contract.py`,
`semantic_intent.py`, `multi_action_state.py`, `live_multihop.py`,
`chatbot_graph.py`를 감사했다. `streaming.py`, ingestion, SSE table parser,
deployment identifier 검증처럼 자연어 의미를 결정하지 않는 코드는 별도 대상에서
제외했다.

## 정적 inventory

아래 수는 정규식 및 contains/prefix/suffix 패턴이 있는 소스 라인의 수이며, 동일
라인의 여러 표현은 한 라인으로 센 보수적 inventory다.

| 파일 | 후보 라인 | 판정 |
|---|---:|---|
| `action_contract.py` | 183 | legacy lexical/semantic 혼재 |
| `semantic_intent.py` | 15 | 기간·수치 normalization이 대부분, 일부 message 재해석 |
| `multi_action_state.py` | 8 | context mutation lexical heuristic |
| `live_multihop.py` | 2 | binding/reference identifier normalization |
| `chatbot_graph.py` | 52 | legacy route/evidence/table normalization |
| 합계 | 260 | 후보 라인 기준 |

신규 semantic 경로에 이번 라운드에서 추가한 semantic regex는 0개다.

## 분류

- LEXICAL: 날짜·기간·숫자·퍼센트·identifier·공백/구두점·SSE/table 형식 검사.
- NORMALIZATION: 광종 alias, source identifier, column/date/unit alias. 가능하면
  registry와 typed slot을 우선하며 정규식은 형식 확인에만 사용한다.
- SEMANTIC: legacy `action_contract.py`의 phrase/contains shortcut,
  `multi_action_state.py`의 reference marker, `chatbot_graph.py`의 legacy intent
  route. 이 영역은 기존 회귀 보호를 위해 이번 라운드에서 제거하지 않고
  **legacy-only**로 격리할 후속 대상이다.

## 이번 라운드 경계 수정

`semantic_capabilities.py`에 typed `(domain, metric) -> produced outputs`
registry를 추가했다. `SemanticPlan.requested_outputs`는 Gemma가 생성하는
semantic output contract이며, validator는 raw query를 읽지 않고 AST requirement와
registry만 비교한다. 누락 output은
`requested_output_not_produced:<outputs>`로 실패한다.

따라서 용도와 최신 가격을 요구하는 AST는 `usage`, `latest_price` coverage를
검사할 수 있고, 가격이라는 단어가 원문에 있다는 이유만으로 가격 node를 삽입하지
않는다. AST가 불완전하면 다음 단계에서 bounded Gemma repair/reparse를 연결하고,
이번 변경에는 regex repair를 추가하지 않는다.

## 남은 legacy debt

현재 production 기본 모드는 legacy/Shadow 호환성을 위해 semantic parser보다
legacy shortcut이 먼저 실행될 수 있다. 이를 즉시 제거하면 기존 Q30 회귀가 깨질 수
있으므로 별도 migration 라운드에서 capability registry와 shadow diff를 확인한 뒤
enabled 경로의 우선순위를 전환해야 한다. 이 문서의 SEMANTIC 후보는 신규 semantic
판단에 재사용하지 않는 것을 원칙으로 한다.

## 검증 지표

- 신규 semantic regex: 0
- typed output coverage unit tests: 2
- raw query를 읽지 않는 coverage 검사: 통과
- legacy semantic 후보 제거: 0 (회귀 보호를 위해 의도적으로 보류)
