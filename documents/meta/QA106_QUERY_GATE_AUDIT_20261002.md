# QA106 Lightweight Query Gate Audit (2026-10-02)

최종 검증 이미지: `komir-rag-chat:query-gate-r4`

초기 106 Gate 분류는 `query-gate-r1`, 최종 smoke는 `query-gate-r4`에서
수행했다. r4는 navigation typed hint가 없으면 fast path를 허용하지 않도록
안전 조건을 보강한 이미지다.

검증 포트: `18012` (운영 `18002` 미변경)

## Gate contract

```text
query → QueryGateDecision(route, dependency)
     → NAVIGATION: existing page-recommend handler
     → otherwise: existing semantic/action/AST path
```

Gate는 AST, ActionId, tool, operation graph를 생성하지 않는다. Gate 호출
실패 또는 불확실한 route는 `COMPLEX`로 승격한다. 현재 iteration에서는
`NAVIGATION + dependency=none`만 fast path로 종료하고, `SIMPLE_LOOKUP`과
`FAQ_CONCEPT`는 기존 경로로 승격하여 false fast-path를 피한다.

## 106 QA route distribution

| route | count | note |
|---|---:|---|
| NAVIGATION | 4 | DOC04, ADD12, ADD45, ADD46 |
| FAQ_CONCEPT | 9 | MI01, MI02, MI03, MI04, ADD02, ADD33, ADD44, ADD47, ADD48 |
| SIMPLE_LOOKUP | 2 | DOC02, ADD49; first iteration에서는 AST로 승격 |
| COMPLEX | 91 | 기존 AST/semantic 경로 |
| **total** | **106** | |

## Dependency distribution

| dependency | count |
|---|---:|
| NONE | 102 |
| PREVIOUS_RESULT | 4 |
| PREVIOUS_TURN | 0 |

PREVIOUS_RESULT 후보는 PF02, ADD28, ADD29, ADD31이다. 이들은 Gate가
history를 실행 입력으로 복원해야 하는 유형으로 분류했지만, 현재 fast path로
소비하지 않고 기존 typed history/AST 경로로 보냈다.

## 57 answerable set tier distribution

| tier | count |
|---|---:|
| NAVIGATION | 4 |
| FAQ_CONCEPT | 6 |
| SIMPLE_LOOKUP | 2 |
| AST_REQUIRED/COMPLEX | 45 |
| **total** | **57** |

## Live SSE checks on 18012

- `리튬 가격 화면으로 가줘`: `query_gate → page_recommend`, `done.mode=page`,
  `price_minor_metals` 추천. AST 미진입.
- `수급지도 대한민국 페이지 어디서 봐?`: `query_gate → page_recommend`,
  `done.mode=page`, `map_korea` 추천. AST 미진입.
- `2025년 구리 수입액 보여줘`: `query_gate=COMPLEX → existing AST`; Gate가
  fast path로 가로채지 않음.
- `니켈 수입 상위 5개국을 보여줘`: `query_gate=COMPLEX → existing AST`;
  multi-step query가 fast path로 가로채지 않음.
- 2턴 smoke에서 1턴 독립 질의는 `dependency=none`, 2턴 `그중 가장 많이 오른
  것은?`은 `dependency=true:previous_result`로 기록되고
  `typed_history_resolver_deferred` 후 기존 AST로 승격됐다. 후속 실행은 기존
  `arg field unavailable: price_change`로 기권했으며, 이는 Gate가 아니라
  기존 downstream capability 문제로 분리된다.

실제 로그에서 다음 관측 필드를 확인했다.

```text
query_gate.route
query_gate.confidence
query_gate.dependency
query_gate handler
escalated_to_ast
```

## Scope / known limitation

이번 iteration에서는 SIMPLE_LOOKUP 실행기와 FAQ 전용 실행기를 새로 만들지
않았다. 두 route는 분류만 관측하고 기존 경로로 승격한다. 따라서 이번 결과의
fast-path resolution은 NAVIGATION 4건이며, simple lookup을 무리하게 우회하지
않는다.
