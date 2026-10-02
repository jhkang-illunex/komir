# QA500 실패 trace / 집계 연결 경계 검증 — 2026-10-02

## 범위와 결론

qa-build + iterative-audit으로 실패 원본 보존, 동일 모집단 집계의 연결 계약,
최종 출력의 extremum lineage를 검증했다. 질문별 규칙으로 모델의 누락된 의미를
대입하지 않았다. 이번 범위의 구현·평가는 완료했지만 **모델 반복 안정성은 미해결**이다.
운영 SSE 검증이나 QA500 전체 재실행 결과가 아니다.

## 변경과 재현

- `common/llm/base.py`, `openai_compat.py`: 실제 응답 모델과 finish_reason 보존.
- `common/llm_client.py`: 매 시도의 raw_content, parsed_json, schema 오류,
  usage, 종료 사유 보존. 토큰 예산·재시도 횟수·기본 출력 모드는 변경하지 않았다.
- `ragkit/semantic_v2.py`: 실패 예외의 허용된 진단 필드를 semantic attempt에 연결.
  헤더 등 임의 transport 정보를 복사하지 않고, 잘못된 record 형식도 안전하게 처리한다.
  실패 응답을 실행 계획으로 승격하지 않는다.
- 같은 파일의 그룹 비교 연결: 명시적 side_by_side, 동일 모집단·기간·metric·dimension,
  두 집계 결과라는 조건에서만 생략된 join_key를 공통 group identity로 연결한다.
  서로 다른 기간, 원시 series, selection/limit, 산술 비교, 명시된 잘못된 key는
  추측하거나 덮어쓰지 않는다. source requirement도 변경하지 않는다.
- 테스트 평가기 `qa500_linkage_eval.py`: 날짜별 max→argmax와 min→argmin의
  증명 가능한 동등성만 인정한다. 평균·합계·반대 집계·다른 그룹을 같은 의미로 보지 않는다.

실패 trace 테스트는 수정 전 6 FAIL에서 최종 9 PASS, 그룹 연결은 수정 전 양성
3 FAIL에서 최종 18 PASS다. 독립 감사에서 평가기의 `output_field=value`가
원시 측정값처럼 해석되는 High를 추가 재현했다. 우연히 숫자가 같은 잘못된 집계도
거절하도록 incoming lineage를 사용해 수정했고 extremum 테스트 8 PASS다.
서로 다른 연도의 month를 자동 연결할 위험도 차단했다. 최종 독립 감사 High/Critical 0.

실제 Gemma를 32 output tokens로 제한한 별도 진단 실행에서 두 시도 모두
finish_reason=length, OUTPUT_TRUNCATED, raw_content 97자를 보존했다.
최종 PARSER_MISSING_OUTPUT이며 logical/lowering 결과는 없다. 이 실패 주입은
정상 QA 76회 통계에서 제외했다.

## 같은 원본 208회 replay: 효과 분리

기존 저장된 requirement를 사용했고 새 모델 호출이나 질문 재해석은 하지 않았다.

| 판정 단계 | PASS | LOGICAL_PLAN_INCOMPLETE | RESULT_MISMATCH | OUTPUT_CONTRACT_FAIL | PARSER_MISSING_OUTPUT | 정상 unsupported |
|---|---:|---:|---:|---:|---:|---:|
| 과거 판정 | 156 | 27 | 3 | 7 | 3 | 12 |
| 같은 계획 + 수정 평가기 | 163 | 27 | 3 | 0 | 3 | 12 |
| 같은 requirement + 수정 compiler | 165 | 25 | 3 | 0 | 3 | 12 |

7회는 **평가기의 잘못된 거절 수정**이지 모델 개선이 아니다. 추가 2회만 공통
compiler 연결 수정 효과다(H1 object repeat1 / schema repeat3). Replay 회귀 0.
나머지 누락·잘못된 의미는 실패로 유지했다. 수정 전후 산출물을 모두 보존했다.

## 실제 Gemma 반복 검증

실제 endpoint `127.0.0.1:52302/v1`, 모델 `gemma-4-26b-a4b`, temperature=0.
production V2 parser → synthetic backend → 독립 SQL 비교이며 mock 모델은 아니다.
재시도가 있어 아래 QA 실행 수와 HTTP completion 수는 같지 않을 수 있다.

| 대상 | 문항 | 반복 | QA 실행 | 모든 반복 PASS | 변동 | 모두 실패 | 모든 반복 정상 거절 |
|---|---:|---:|---:|---:|---:|---:|---:|
| 기존 core | 28 | 2 | 56 | 20 | 5 | 1 | 2 |
| 기존 holdout U | 4 | 2 | 8 | 4 | 0 | 0 | 0 |
| 새 holdout V | 4 | 3 | 12 | 3 | 1 | 0 | 0 |
| 합계 | 36 | — | 76 | 27 | 6 | 1 | 2 |

실행 기준 PASS 64, RESULT_MISMATCH 2, LOGICAL_PLAN_INCOMPLETE 6,
UNSUPPORTED_CORRECT 4. 성공한 실행만 골라 문항 PASS로 집계하지 않았다.
실패 문항: EXT500-037, EXT500-039, H3, H4, M1, R4, V2.
R4는 두 번 모두 실패, 나머지 여섯 문항은 반복 간 변동이다.
시도별 schema 오류 7회와 truncation 1회도 기록했다. 복구된 시도가 포함되므로
이를 최종 실패 QA 수로 해석하지 않는다.

새 V 4건은 실행 전에 정의한 코발트 월별 평균/건수, 알루미늄 최고/최저 날짜와
차액, 아연 생산 국가별 평균/건수, 흑연 수입 국가별 평균/건수다.
기존 2nd-order 연산의 대상·기간·표현 변형이며 새 operator coverage는 0이다.
기존 32건을 재사용했으며 신규 질문 중복 복제나 별도 정답용 DB는 만들지 않았다.
음성 oracle 테스트에만 같은 날짜의 다른 값 한 행을 격리 fixture에 추가했다.

모든 실제 실행은 최종 동일 평가기로 재판정했고 변경된 최종 상태는 0건이다.
진단 record 방어 코드만 실행 시점과 최종 source hash가 다르며 모델 요청·계획
의미는 동일하다. 과거 round와 반복 수·평가기·표본이 달라 직접 성공률 상승을
주장하지 않는다. Gold는 평가기에서만 사용한다.

## 회귀 / 과적합 방지

- Baseline: 1290 PASS / 687 subtests / 0 FAIL.
- Final rag_core: 1325 PASS / 687 subtests / 0 FAIL, 39.76초.
- 신규 테스트 35개. 기존 PASS→FAIL 0. 기존 테스트 기대값 변경 0.
- compileall 및 git diff --check PASS.
- 신규 semantic regex, 질문별 production special-case, Action/operator, prompt patch: 각각 0.
- 기본 json_object 유지. json_schema 강제 모드를 활성화하지 않았다.
- 운영18002·검증18011, 공유 DB, 배포, commit/push 변경 없음.

## Corpus accounting / 남은 한계

이번 반복 검증 대상 기준:

```text
TOTAL_CORPUS: 36
REGISTERED: 36
PASS: 27
FAILED: 7
CAPABILITY_GAP: 0
UNSUPPORTED: 2
BLOCKED: 0
PENDING: 0
36 = 27 + 7 + 0 + 2 + 0 + 0
```

남은 문제는 실제 모델의 의미 누락·잘못된 연산/필드 생성과 반복 변동이다.
여기서 CAPABILITY_GAP=0은 이 소규모 대상의 분류이며 시스템 전체 지원을 뜻하지 않는다.
값이나 필드를 암묵적으로 보정하면 false success가 되므로 실패를 유지했다.
현재 근거만으로 추가 prompt patch나 범용성 없는 자동 복구는 채택하지 않았다.

근거: [집계와 질문별 판정](qa500_trace_boundary_20261002/summary.json),
[전체 회귀 출력](qa500_trace_boundary_20261002/final2-regression.log).
같은 디렉터리에 raw/captured/rejudged/replay 기록과 truncation 진단을 보존했다.

STATUS: DONE — 이번 제한된 구현·검증 범위 완료; 모델 안정성 전체 해결 아님.
