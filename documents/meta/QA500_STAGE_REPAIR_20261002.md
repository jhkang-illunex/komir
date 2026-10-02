# QA500 남은 7문항의 재계획 진단 보완

## 범위

요청대로 남은 실패 분석·공통 수정·별도 holdout만 수행했다. 전체 모델 안정성 평가,
운영/SSE 검증, 배포, 컨테이너 재시작, 공유 DB 변경, commit/push는 수행하지 않았다.
qa-build 및 iterative-audit을 적용했다. 모든 파일 수정은 주 작업자가 담당했고 감사는
읽기 전용이었다. 운영18002는 audit-safety22, 검증18011은 audit-relations30으로 유지했다.

## 원인 분리

직전 기록의 실패 7문항(실패 실행 8회)을 실제 semantic_plan 및 오류와 대조했다.

| 대상 | 최초 잘못된 연결 / 해석 | 처리 |
|---|---|---|
| H3, H4, R4, V2 | Aggregate 출력은 max_price/min_price인데 Select가 원시 value 참조 | 거절 유지, 연산 단계 계약을 재계획 진단에 제공 |
| M1 | 평균/건수 requirement와 Join은 있으나 Project가 평균 source에서 건수 요청 | 거절 유지, 정의된 source별 필드를 진단에 제공 |
| EXT500-037/039 | 기존 Gold는 high_price/low_price, 모델은 value 최대/최소 | 자동 치환 금지. 원문만으로 두 해석이 모호함을 별도 표시 |

마지막 두 질문의 기존 실패 판정은 보존했다. high/low Gold와 다르다는 사실만으로
확정적인 모델 의미 오류라고 단정하지 않는다. 점수 개선을 위한 Gold 변경도 하지 않았다.
원본 응답·중간 requirement·Program은 직전 및 이번 jsonl에 보존되어 있다.

## 최소 수정

`inhouse/rag_core/ragkit/semantic_v2.py`의 두 오류 진단만 보완했다.

1. Aggregate→Select의 input_field, aggregation, group_by, output_field,
   supplied selection을 stage_contract로 제공한다. 원시 필드와 집계 출력은
   자동 alias가 아님을 명시한다. 기존 그룹·측정값·요청 출력을 삭제해 통과시키지 말도록 한다.
2. 요청한 Project 필드가 없으면 정의된 source별 생성 필드를 제공한다.
   다른 source로 자동 변경하거나 누락 컬럼을 만들어내지 않는다.

원본 candidate, validator 수락 조건, Logical AST, lowering 규칙, schema vocabulary,
기본 prompt, 재시도 횟수와 토큰 예산은 변경하지 않았다. 기존 bounded 재계획 경로를
재사용했다. 질문·광종·QA ID 분기, semantic regex, 새 Action/operator 추가는 각각 0이다.
수정된 피드백은 Gold가 아니라 현재 candidate의 계약만 사용한다.

## 독립 재현 / 감사

- `test_semantic_stage_diagnostics.py`: 수정 전 10 FAIL → 수정 후 10 PASS.
- 가격/생산량/수입액 × max/min/mean을 교차 검증했다. 원본 selection 및 output source
  불변도 확인했다. 기존 진단 테스트와 합쳐 21 PASS.
- 독립 읽기 감사에서 신규 테스트 10 PASS, High/Critical 0.
- 진단 표현의 한계: Calculate가 끼어 있는 조합까지 완전한 stage trace를 제공하는
  것은 아니다. 이번 변경은 집계 후 존재하지 않는 필드에 대한 진단이며 실행 의미의
  자동 복구가 아니다. 별도 구조나 넓은 연산 확장은 하지 않았다.
- 저장된 76개 동일 requirement를 최종 compiler/평가기에서 재실행: 판정 변화 0.
  따라서 유효하지 않은 기존 계획을 조용히 수락하여 점수를 높인 것이 아니다.

## 실제 Gemma 집중 재검증

`qa500_stage_eval.py`로 실제 gemma-4-26b-a4b, temperature=0,
기본 json_object 모드를 사용했다. production V2 parser와 synthetic runtime,
독립 SQL oracle을 사용하며 mock 응답이나 운영 데이터는 사용하지 않았다.

| 대상 | 이전 기록의 반복 상태 | 이번 1회차 | 이번 2회차 |
|---|---|---|---|
| EXT500-037 | 변동 | RESULT_MISMATCH | PASS |
| EXT500-039 | 변동 | PASS | PASS |
| H3 | 변동 | LOGICAL_PLAN_INCOMPLETE | PASS |
| H4 | 변동 | PASS | PASS |
| M1 | 변동 | PASS | PASS |
| R4 | 전회 실패 | PASS | LOGICAL_PLAN_INCOMPLETE |
| V2 | 변동 | PASS | PASS |

기존 실패 대상 7건 중 이번 두 반복 모두 성공 4건, 변동 3건.
14회 실행 기준 PASS 11 / LOGICAL_PLAN_INCOMPLETE 2 / RESULT_MISMATCH 1.
직전 대상 실행은 V2가 3회여서 총15회이며 이번14회와 단순 성공률 상승 비교는 하지 않는다.
실패한 시도도 보존했고 best-of PASS 집계는 하지 않았다.

남은 H3/R4는 날짜별 max/min 집계를 단일값처럼 비교하는 계획을 생성했다.
row selection branch가 따로 있어도 이를 임의로 비교 입력으로 대체하지 않는다.
그룹 identity와 scalar 비교 계약을 유지하여 실패시켰다.
EXT500-037은 앞서 설명한 측정 필드 모호성이 남았다.

## 별도 holdout

첫 모델 호출 전에 W1~W4를 정의했다. 아연/텅스텐의 명시적 통상가격 최대·최소
날짜와 차액, 리튬 월별 평균/건수, 구리 생산 국가별 평균/건수다.
Gold/연산 그래프/독립 SQL은 기존 fixture를 재사용했다. 새 합성 row는 0,
새 operator coverage는 0이며 기존 의미의 대상·기간·표현 변형 4건이다.

4문항 각각 2회: **8/8 PASS**, 문항 기준 **4/4 PASS**.
이 결과를 보고 추가 prompt 조정이나 holdout용 수정은 하지 않았다.
작은 두 번 반복 결과이므로 전체 안정성 또는 미지 질문 일반화의 증명은 아니다.

## 최종 회귀 및 accounting

Baseline rag_core: 1325 PASS / 687 subtests / 0 FAIL.
Final rag_core: **1335 PASS / 687 subtests / 0 FAIL** (39.36초).
기존 PASS→FAIL: **0**. compileall / git diff --check PASS.

이번 범위의 고유 QA만 집계한다. 기존 corpus를 다시 등록하거나 500건 전체 처리로
주장하지 않는다.

```text
TOTAL_CORPUS: 11
REGISTERED: 11
PASS: 8
FAILED: 3
CAPABILITY_GAP: 0
UNSUPPORTED: 0
BLOCKED: 0
PENDING: 0
11 = 8 + 3 + 0 + 0 + 0 + 0
```

기존 재사용 7, 새 holdout 4, 전체22회 실행 PASS19/계획실패2/결과불일치1.
이 수치는 전체 시스템 성공률이 아니다. 남은 모델 생성 오류를 결정적 코드로 추측
복구하지 않았으며 추가 질문별 prompt patch는 채택하지 않았다.

근거: [자동 집계](qa500_stage_repair_20261002/summary.json),
[수정 전 재현](qa500_stage_repair_20261002/before.log),
[전체 회귀](qa500_stage_repair_20261002/final.log).
동일 폴더의 focused/holdout raw jsonl, captured_failure_analysis,
immutable_requirement_replay에 질문별 실행과 비교를 보존했다.

STATUS: DONE — 이번 제한된 실패 경로 보완·검증 완료.
전체 안정성 및 운영 검증은 사용자 지시대로 후속 작업으로 남겼다.
