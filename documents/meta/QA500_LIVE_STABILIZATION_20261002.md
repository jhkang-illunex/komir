# Live 공통 원인 안정화 — 2026-10-02

## 범위와 판정

`iterative-audit`로 이전 live repair의 잔여 공통 오류를 재현·수정했다.
질문별 분기, 새 Action, semantic regex를 추가하지 않았다. **전체 운영 안정화 완료를
선언하지 않는다.** 오프라인 계약 감사와 실제 Gemma의 반복 의미 정확도는 별개다.
이 문서는 QA500 전체의 자연어 실행 결과가 아니라 아래 대표 live 사례의 증분 검증이다.

운영 `18002`는 `komir-rag-chat:audit-safety22` 그대로이며 시작 시각
`2026-10-01T12:02:54.490338051Z`가 유지되었다. `18011`도 변경하지 않았다.
검증만 `127.0.0.1:18012`, 별도 History PostgreSQL, 업무 DB read-only로 수행했다.
업무 DB 변경·운영 재시작·커밋·푸시는 하지 않았다.

최종 검증 이미지: `komir-rag-chat:qa-live-stability33-r10`

`sha256:75a96f09ffcc2f3dd591c5a413d0aadef815100d89e68636926b8267b9c79ed6`

## 재현된 공통 원인과 변경

| 경계 | 실제 실패 | 공통 수정 |
|---|---|---|
| parser → AST | 집계 leaf에 데이터 입력 누락 | 기존 입력 arity를 schema에 노출, 실패 계획·오류를 구조화하여 bounded repair |
| parser → 조회 | 광종이 없는 생산량 조회가 no_data로 진행 | resource leaf의 static mineral 또는 upstream binding 필수 검증 |
| History → InputRef | 반복 참조 ID가 계속 길어져 80자 제한 초과 | 외부 참조와 내부 node ID 분리, 내부 ID 고정 길이 hash |
| History → parser | `history:turn:step`을 없는 `result:turn:step`으로 생성 | 실제 참조 목록 제공, namespace 변경 금지; 없는 참조는 계속 거절 |
| refresh → runtime | 여러 광종인데 첫 광종만 price.series 실행 | 기존 fan-out에 price.series 연결, 각 Action에 단일 mineral/minerals 전달 |
| Action → TypedResult | 가격 metric 누락, schema의 value가 실제 행에 없음 | 가격 metric 복구, 가격·생산·매장 단일 metric의 strict field만 value에 연결 |
| ForEach → validation | 출력이 원본 문서의 필드 계약을 상속 | 실제 항목별 envelope 필드 선언, flat price/title 오인 거절 |
| PARTIAL → projection → history | 실패 행만 status를 보존하여 성공 필터가 빈 결과 | 모든 partial 행의 status/reason/output/unit 보존 |
| projection → aggregate/chart | unit 열 제거·alias로 혼합 단위가 은폐 | 기존 TypedResult 제약 보존, unit alias 위조 차단, 혼합 단위 합계·자동 차트 차단 |
| DB unit → renderer | WT001/006/007 단위가 typed 결과와 본문에서 불일치 | 실제 코드 마스터로 확인한 단위 registry 재사용; 미확인 WT008은 추정하지 않음 |
| 실패 → SSE | 계획 오류와 mapping/category 실패가 데이터 부재·Advisor 실패로 뭉침 | 계획 실패 별도 reason, 공개 허용된 원인 코드만 전송, 내부 예외·접속정보 비공개 |

주요 변경: `live_multihop.py`, `semantic_ir.py`, `analytical_aggregate.py`,
`chatbot.py`, `chatbot_graph.py`, `chatbot_events.py`, `_mcp_tools_common.py`,
`renderers/price.py`. 기존 미커밋 변경과 이번 증분을 혼동하지 않는다.

추가 회귀: `test_live_parser_contract_feedback.py`, `test_live_price_fanout.py`,
`test_live_plan_failure.py`, `test_live_adapter_failure_diagnostics.py`,
`test_price_unit_registry.py`. 기존 partial projection 테스트 1개는 광종 B 선택
기대값을 그대로 두고 새 status 보존 계약만 명시했다.

## 검증 기준

독립 SQL은 2024년 구리 생산량의 확인된 17개 국가 모집단을 사용했다.
SU/OT 등의 제외·단위·원천 행은 SQL 산출물에 남겼다. 상위 5개 합계와 전체 합계를
혼동하지 않았다.

- 전체 합계: 6,998,520.20
- 평균: 411,677.658823529412
- 합계 − 평균: 6,586,842.541176470588
- 칠레: 2,098.1
- Top-5 합계: 6,024,000
- 가격기준 502 확인 관측: 2026-09-30, 22,916.73

실제 SSE 원문, 요청 시각·session·이미지 식별자, Gemma 출력·repair·AST·Action trace,
저장된 TypedResult와 독립 SQL을 `qa500_live_stabilization_20261002/`에 보존했다.
이전 실패를 삭제하거나 마지막 성공으로 대체하지 않았다. 같은 프로세스의 동일한 독립
질문은 AST cache hit일 수 있으므로, 반복 SSE와 cold-restart Gemma 실행을 구분한다.

## 회귀와 독립 감사

- 최종 rag_core: **1,430 PASS / 695 subtests**.
- rag_chat + common: **163 PASS / 17 subtests**.
- 합계 **1,593 PASS**, 최종 실패 0. 기존 PASS→FAIL 잔존 0.
- compileall, git diff --check, Docker build 실행.
- pydantic_settings의 기존 forward-reference 경고 1건은 남는다.
- 독립 증분 감사에서 unit alias 우회 등 High 반례를 재현한 뒤 수정·재감사했다.
  마지막 변경 범위의 High/Critical 미발견. 이는 live 의미 정확도 전체 PASS를 뜻하지 않는다.

## 최종 실제 SSE 결과

r10 기본 6건 + 문서 3턴 두 세트 + cold-restart 기본 6건·문서 3턴·저장 세션 복귀·반복 계산·취소로
최종 이미지에서 **24요청**을 실행했다. 일반 응답 완료 14, PARTIAL 7(문서 및 상태를 승계한 후속 결과),
매장량 계약 차단 2, 의도적 취소 1이다. wire contract 오류는 0이다.

독립 SQL·저장 root·대상 집합·단위·새 조회 여부 대조는 **22/22 PASS**다.
`stability33-final-checks.json`에 r10/r10b/r10cold 및 이전 세션 재시작 복원 검사가 포함된다.
문서 결과에서 성공한 광종 7개의 목록 참조 및 갱신 가격이 일치하고, partial projection 이후에도
각 광종의 단위가 남는다. 이전 세션 복귀는 새 retrieval 없이 7개 목록을 복원했다.
동일 질문 cache hit인 반복 계산은 별도 기록하며 새 Gemma 호출로 세지 않는다.

| 대표 사례 | 수정 전 실제 실패 | 최종 이미지 결과 |
|---|---|---|
| 생산량 합계−평균 | leaf aggregate·입력 누락 | SQL 6,586,842.541176470588 일치 |
| 전체 생산량 합계 | mineral 누락이 no_data로 진행; value 미연결 | bounded repair 이후 SQL 6,998,520.20 일치 |
| 칠레 단일 국가 | 보호 회귀 | SQL 2,098.1 일치 |
| 니켈 502 최신값 | metric/value 유실 | SQL 22,916.73 일치 |
| 문서 목록 개별 가격 | field 계약 누락·단위 소실 | 7개 성공/9개 실패 사유·단위 보존 |
| 성공 목록 후속 참조 | 성공 status 소실 → 빈 목록 | 7개, 새 조회 없음 |
| 해당 목록 새 가격 조회 | 첫 광종만 조회·잘못된 참조 | 7개 개별 값 일치; 재시작 후에도 동일 |
| 매장량 합계 | category 미확정 | 여전히 기권, 생산량으로 대체하지 않음 |

이번 라운드 **전체 141요청**의 관측 상태(이전 수정 이미지 실패 포함):
RESPONSE_COMPLETED 76 / PARTIAL 27 / FAIL 14 / DATA_CONTRACT_BLOCKED 14 /
SEMANTIC_MISMATCH_TARGET_SCOPE 1 / UNSUPPORTED_CORRECT 3 / CANCELLED 3 /
EXPECTED_ABSTAIN_ZERO_DENOMINATOR 3. 합계 141, wire 오류 0.
RESPONSE_COMPLETED는 전체 의미 정확도 PASS가 아니다. 최종 이미지의 구체 검증은 위 22개 대조다.

## 반복 실행에서 남은 제한

1. Gemma가 기간 메타데이터 `period`를 가격 관측 `date` 대신 project하여 bounded repair에도
   실패한 실행을 보존했다. 검증기를 완화하거나 기간을 임의 치환하지 않았다.
2. 후속 재조회에서 직전 성공 목록 대신 이전 전체 문서 광종 목록을 선택한 실행이 있었다.
   성공값이 맞더라도 대상 집합이 다르면 semantic mismatch다. HTTP 200만으로 통과시키지 않는다.
3. 구리 매장량·니켈 생산량의 category가 유일하게 확정되지 않는 데이터는
   `resource_population_unresolved_category`로 남는다. 임의 category/default 생산량으로 대체하지 않았다.
4. 문서의 16개 광종 중 가격 성공 7개, 나머지 9개에는 mapping 없음/기준 선택 등이 섞여 있다.
   리튬·희토류의 상품 대표성, 구리·코발트 mapping, 일부 대표 기준 설명의 동등성을
   승인 없이 새 alias나 mapping 우회로 해결하지 않았다. 모두 실제 관측 부재라는 뜻이 아니다.
5. 원천에 DEV_DUMMY가 포함된 개발 설정을 그대로 사용했다. 수치를 공식 관측으로 인증한 것이 아니다.

보고서의 실행별 상태는 `request-assessment.json`, 최종 값·집합 대조는
`stability33-final-checks.json`을 함께 읽어야 한다. 전자는 transport/관측 상태이고,
후자가 의미·수치 검증이다. 실패와 기권을 숨기지 않은 **운영 배포 보류** 상태다.
