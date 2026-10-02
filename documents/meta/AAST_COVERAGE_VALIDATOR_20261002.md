# AAST Coverage Validator 검증 결과

## 범위

- 기준: `AAST_COMPOSITION_REANALYSIS_20261002.md`
- 검증 포트: `18012`
- 검증 이미지: `komir-rag-chat:aast-coverage-r1`
- 이미지 digest: `sha256:d60172707059bc447f980a46bac447d205cc1acb3ccd8f6a29cc078485e51196`
- 운영 `18002`: 변경·재시작하지 않음 (`komir-rag-chat:audit-safety22`)
- 신규 Action, Direct/Gate 경로, Renderer, join partial 정책, source/data mapping: 변경 없음

## 구현

`inhouse/rag_core/ragkit/aast_coverage.py`에 raw query를 읽지 않는 결정론적 검증기를
추가했다. 기존 semantic requirement snapshot과 `SemanticProgram`을 비교하며 다음을
검증한다.

- entity/mineral, metric, country/scope, date/period 보존
- root 도달성 및 requirement branch 수
- capability 선택 일치
- 입력 node 존재와 upstream dependency
- Compare/Join의 두 입력과 alignment key/field

검증 실패 시 `live_multihop._parse_ast`에서 coverage repair를 정확히 한 번 호출한다.
수정은 LLM에 violation 목록과 기존 AAST를 전달하는 bounded repair이며, 원문 재해석·물리
Action 선택·값 보정은 하지 않는다. 재검증 실패 또는 repair 호출 오류는 기존
`semantic_plan_incomplete` 경로로 종료한다.

실패 trace에는 다음을 함께 남긴다.

- `semantic_requirements`
- parser의 raw structured output/record
- `raw_action_plan`
- `raw_aast`
- validation violation 목록
- `repair.attempted` 및 성공/실패 결과

ActionPlan의 semantic snapshot은 private attribute로만 전달되어 기존 public ActionPlan
계약에는 노출되지 않는다.

명시 reason은 다음 7종이다: `ENTITY_PRESERVATION_FAILED`,
`METRIC_PRESERVATION_FAILED`, `PERIOD_PRESERVATION_FAILED`, `BRANCH_COVERAGE_FAILED`,
`CAPABILITY_SELECTION_MISMATCH`, `DEPENDENCY_BINDING_FAILED`, `JOIN_CONTRACT_FAILED`.

## Validator unit test

`test_aast_coverage_validator.py` 및 관련 parser diagnostic 테스트: **26 passed**.

검증 대상에는 잘못된 lithium/graphite entity, trade capability가 document로 치환된 경우,
document branch 누락, typed period 누락, relation input/key 위반, 정상 graph가 포함된다.

## 대표 5건 실제 SSE replay

최신 이미지에서 실제 Gemma와 live runtime으로 각각 신규 session을 사용했다.

| QA | 결과 | Validator 관찰 |
|---|---|---|
| IX01 `광물지수 오를때 같이 오른 광종은 뭐야?` | `semantic_plan_incomplete` | graph/계획 생성 실패로 실행 차단 |
| MP01 `니켈 가격 추이랑 우리나라 수입국 구성 같이 보여줘` | PASS | `trade.country_rank` branch 누락을 검출 후 1회 repair, 2 branch 실행 |
| MP09 `니켈 가격 추이랑 최근 월간 동향 내용 같이 알려줘` | PASS | document branch 누락을 검출 후 1회 repair, 가격+문서 3 root 실행 |
| GM02 `리튬 세계 생산 상위국 중 우리 수입 상위국에 들어가는 나라는?` | `semantic_plan_incomplete` | WORLD/KR scope 보존 위반을 검출; repair 후에도 위반하여 실행 차단 |
| CN09 `광물종합지수 떨어진 주에 주요 뉴스 뭐 있었어?` | PASS | 실제 indicator 결과와 문서 결과가 결합되어 완료 |

GM02 trace에서 repair 결과가 scope를 복원했지만 Validator가 여전히
`ENTITY_PRESERVATION_FAILED`를 반환했고, `repair.success=false`와 최종 violation이
보존되었다. 이는 잘못된 graph를 실행하지 않은 정상적인 fail-closed 결과다.

## QA replay 집계

원본 audit source를 그대로 replay했으며 HTTP 200 자체를 PASS로 세지 않았다.

### AAST composition 17건

| 상태 | 건수 |
|---|---:|
| PASS | 4 |
| `semantic_plan_incomplete` | 5 |
| `execution_failed` | 3 |
| `dependency_unavailable` | 1 |
| `all_roots_failed` | 1 |
| `ambiguous` | 3 |
| 합계 | 17 |

### 기존 non-PASS 34건

| 상태 | 건수 |
|---|---:|
| PASS | 11 |
| `semantic_plan_incomplete` | 11 |
| `execution_failed` | 5 |
| `dependency_unavailable` | 1 |
| `source_unavailable` | 1 |
| `all_roots_failed` | 2 |
| `ambiguous` | 3 |
| 합계 | 34 |

### answerable 57건

| 상태 | 건수 |
|---|---:|
| PASS | 34 |
| `semantic_plan_incomplete` | 10 |
| `execution_failed` | 5 |
| `ambiguous` | 3 |
| `source_unavailable` | 2 |
| `all_roots_failed` | 2 |
| `dependency_unavailable` | 1 |
| 합계 | 57 |

기존 source-backed oracle와 비교한 보수적 content 판정은 **23/57 (40.35%)**이다.
숫자 근거가 겹치거나 oracle text가 포함된 경우만 세었으며, 단순 non-abstain을 정답으로
세지 않았다. 기존 기준 23/57 대비 content accuracy 증가는 확인되지 않았다.

## 5건 사전 차단 및 repair 결과

- Validator가 직접 violation을 기록한 대표 건: MP01, MP09, GM02
- bounded repair 성공: MP01, MP09, CN09 경로에서 누락 branch 복원 후 실행
- bounded repair 실패/재검증 실패: GM02
- 계획 생성 자체가 완료되지 않아 Validator 이전에 종료: IX01
- repair 호출 오류도 `repair.attempted=true`, `success=false`, 예외와 원래 graph를
  함께 기록하도록 보완했다.

## 전체 회귀

최종 소스 기준:

```text
PYTHONPATH=.:inhouse pytest -q inhouse/rag_core/tests
1461 passed, 1 warning, 695 subtests passed
```

기존 PASS → FAIL: **0**.

compileall 및 `git diff --check`도 통과했다. 18012 컨테이너 health check는 200이며,
운영 18002 health check도 200으로 유지되지만 운영 컨테이너에는 이번 변경을 반영하지
않았다.

## 남은 항목

Validator가 해결하지 않는 것으로 남긴 항목은 의도적으로 우회하지 않았다.

- 실제 날짜 교집합 부재와 partial join 정책: runtime/data contract 문제
- retrieval/evidence 실패: source/data 문제
- 전망·외부 문서 의존: external/document data 문제
- ambiguous: 사용자 조건 부족
- 모델이 graph 자체를 만들지 못한 경우: parser/planner 문제

이번 변경은 coverage violation을 실행 전에 차단하고 원인 trace를 남기는 것이 목적이며,
source/data 부족이나 join partial 정책을 PASS로 바꾸지 않는다.

상태: **18012 검증 완료 / 18002 미변경**
