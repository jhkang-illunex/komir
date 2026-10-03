# Typed History Materialization / AAST Boundary Audit

일자: 2026-10-03
검증 대상: 18012 (`history-materialization-r2-20261003`)
운영 18002: 변경하지 않음

## 범위

독립 질의의 History Isolation은 기존 완료 계약으로 유지하고, 후속 질의에서만
Typed History가 현재 Semantic Requirement를 채우는 경계를 점검했다. QA57 전체
replay는 실행하지 않았다.

## 변경 내용

- `live_multihop._materialize_history_requirements()`를 추가했다.
  - 현재 requirement의 명시값을 보존한다.
  - 후속 requirement에서 비어 있는 typed slot만 성공한 최신 TypedResult에서 채운다.
  - `relation=independent`, `context_ref=null`로 materialized requirement를 만든다.
  - 성공한 typed result가 없으면 `HISTORY_BINDING_FAILURE`로 기록한다.
- Semantic parser에는 raw conversation history 대신 선택된 typed history projection만
  전달한다. 독립 질의에는 빈 history를 전달한다.
- materialization이 끝나면 AAST parser에는 빈 `ConversationContext`를 전달하여 과거
  turn이 다시 semantic source로 경쟁하지 않도록 했다. provenance는 boundary log에 남긴다.
- 기존 `_resolve_history_references()`와 TypedResult 저장 경로는 재사용했다.

## 단위 검증

```text
test_history_requirement_materializes_only_missing_slots: PASS
test_live_multihop.py + test_semantic_intent.py: 96 passed
```

## 실제 18012 follow-up 검증

| 패턴 | History 선택 | Materialized requirement | AAST 입력 | 3회 결과 |
|---|---|---|---|---|
| 니켈 수입 상위국 → 그중 중국 비중 | 선택 시도 | 첫 턴이 `projection_field_unavailable:import_value`로 성공 TypedResult를 만들지 못해 `HISTORY_BINDING_FAILURE` | 미확정 값을 추측하지 않음 | 3/3 동일한 binding blocker |
| 니켈 최근 1년 가격 추이 → 그중 최근 3개월 | 선택 | `mineral=니켈`, `period=trailing_months(3)`, `relation=independent`, `context_ref=null` | 과거 context 0개. 현재 requirement만 전달 | 3/3 동일 materialization; 이후 `그중`의 rank selection capability 미지원으로 AAST 실패 |
| 리튬 가격 → 그럼 니켈은? | 현재 질문의 `mineral=니켈` 우선 | history 미사용 | 현재 니켈 price series 경로 | 3/3 완료, 이전 리튬 오염 없음 |

### 관찰된 경계 로그

```text
history_boundary history_used=true
materialized_requirements=[... mineral=니켈, period=3개월, relation=independent ...]
history_boundary complete=true ast_context_turns=0
```

첫 번째 패턴은 이전 결과가 실패했으므로 국가 집합을 만들어 내지 않았다. 이는
history를 요약문으로 복구한 척하지 않는 fail-closed 동작이다. 두 번째 패턴은
History Boundary 이후의 남은 실패가 `price rank selection is not an existing Action
capability`인 AAST/capability 범위 문제이며, 이번 작업 범위에서 수정하지 않았다.

## 독립 질의 회귀

기존 independent isolation 결과와 이번 실제 검증을 함께 확인했다.

- explicit current entity/period가 있는 질의는 `history_used=false` 유지
- `리튬 가격` 이후 `그럼 니켈은?`에서 최종 entity는 니켈
- 이전 리튬 가격이 니켈 결과에 섞이지 않음
- 독립 질의의 raw history가 AAST input으로 전달되지 않음

## 반복 안정성

- A 패턴: 3회 중 3회 동일 `HISTORY_BINDING_FAILURE`
- B 패턴: 3회 중 3회 동일 materialized requirement와 동일 후속 blocker
- C 패턴: 3회 중 3회 동일 current entity 우선 결과

이번 반복에서 History Binding 자체의 변동은 확인되지 않았다. AAST 이후의
`price rank selection` 실패는 History Contract와 분리했다.

## 미수정 / 제한

- `AAST`, `Capability`, `Renderer`, Query Gate의 대규모 변경 없음
- 국가 집합을 임의 생성하는 보정 없음
- QA ID·질문 문자열 특례 없음
- 18002 배포·재시작 없음
- QA57 full replay 없음

## 결론

Typed History가 필요한 후속 질의에서는 선택된 TypedResult에서 현재 requirement의
누락 slot을 materialize하고, 그 뒤 AAST에는 resolved current requirement만 전달하는
경계가 동작한다. 성공한 이전 결과가 없을 때는 명시적 binding blocker로 남긴다.
현재 남은 대표 blocker는 A의 선행 capability 실패와 B의 기존 AAST/capability
selection 범위이며, 이번 History Boundary 수정의 회귀로 확인되지 않았다.
