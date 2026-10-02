# QA500 requirement → planner → output 계약 보완

## 범위와 판정

실제 Gemma V2 shadow 출력과 공통 synthetic SQLite 실행을 검증했다. 운영 SSE,
PostgreSQL Action/Tool E2E 또는 배포 검증이 아니다. 운영 18002·검증 18011·운영 DB는
변경하지 않았다. 기존 QA500 원장 및 과거 실패 기록은 보존했다.

모델은 `gemma-4-26b-a4b`, endpoint는 로컬 `52302/v1`, 기준시점은 `2026-10-01`이다.
Gold는 모델 출력 이후 평가에만 사용했다. 모델 입력에 정답·Gold AST·QA ID를 넣지 않았다.

## 확인한 공통 원인과 수정

`inhouse/rag_core/ragkit/semantic_v2.py`의 공통 계약을 보완했다.

- 집계 결과 컬럼 이름과 관계 결과의 식별자가 없어 downstream Project가 요구한 필드를
  찾지 못했다. `output_field`, `relationship_id`, requested output의 `aliases`를 연결했다.
- Compare의 산술 연산을 명시할 수 없어 별도 요구나 Join에 잘못 끼워 넣었다.
  기존 Compare runtime의 `side_by_side/difference/ratio/percent_change`를 관계 계약으로 연결했다.
- Join key는 단일/복수 필드를 받는다. Compare operand의 `left/right` 역할을 검증한다.
- requested output별 source/fields/aliases를 Project로 보존한다. 알 수 없는 source는 거절한다.
  명시된 upstream 컬럼이 유일할 때만 이름을 해소하며 모호한 이름을 추측하지 않는다.
- 필수 기간, 엔티티, 관계 입력, Join key, Compare alignment, 집계 후 선택 필드를
  typed requirement만으로 검증한다. 오류를 Gemma에 전달하는 재계획은 최대 1회다.
  기존 LLM client의 schema 재시도와 별개이며 양쪽이 사용되면 원본 completion은 최대 4회다.
- derived entity를 기존 InputRef edge로 보존하고 static validation과 분리했다.
  다만 V2 lowerer의 derived entity materialization은 여전히 미지원이므로 명시적으로 거절한다.
  MineralSet을 static 광종이나 `None`으로 바꿔 실행하지 않는다.
- Join → Project의 `unit`은 metadata에서 제공될 수 있으므로 정적 컬럼 검사만으로 거절하지 않는다.
  실제 runtime은 여전히 단위 부재를 검사한다.

새 Action/Intent/operator, 질문 문자열 분기, 광종별 production 분기, semantic regex 추가는 0이다.
live routing, 기존 Action/Tool/Data/SSE는 이번 연결 수정으로 교체하지 않았다.

## 실제 모델 실행 결과

모든 라운드의 저장된 LogicalProgram을 최종 엄격한 oracle로 재실행했다. 재판정은 신규 모델
호출이나 계획 재작성 없이 수행했다. 최초 판정과 재판정 파일을 모두 남겼다.

| 실행 | 질문 수 | PASS | 명시적 unsupported 정상 | 기타 실패 |
|---|---:|---:|---:|---:|
| 수정 전 대상 질문 | 8 | 0 | 0 | 8 |
| repair 1 | 16 | 1 | 2 | 13 |
| repair 2 | 16 | 7 | 2 | 7 |
| repair 3 | 16 | 9 | 2 | 5 |
| repair 4 | 16 | 12 | 2 | 2 |
| 수정 후 별도 holdout | 6 | 5 | 0 | 1 |

repair 4의 원래 대상 EXT500-009~012, EXT500-037~040은 **8/8 PASS**다.
월별 평균·관측 건수, 최고가/최저가의 시점과 차이를 포함한다.
혼합 관리자/스크립트 요청 M1/M2는 정상 데이터 결과를 보존했고, 순수 권한 변경/SQL 실행
N1/N2는 unsupported였다. 이는 소규모 표본 검증이며 보안 전체를 입증하지 않는다.

총 실제 모델 질의 실행은 78회(8 + 16×4 + 6), 고유 질문은 22개다.
내부 schema/contract 재시도 수는 이 질의 횟수와 구분한다.
500건 전체 성공률 또는 245건 해결 수로 환산하지 않는다.

## 남은 실패: 성공으로 완화하지 않음

- **H1 / OUTPUT_CONTRACT_FAIL**: 월별 평균과 건수 계산은 성공했지만 최종 projection에서
  월 필드를 누락했다. 숫자가 맞아도 월별 결과 식별이 불가능하므로 실패다.
- **H4 / LOGICAL_PLAN_INCOMPLETE**: 차이를 binary 관계가 아닌 별도 가격 requirement로 생성하고
  엔티티/명시적 참조를 누락했다. 제한된 재계획 후에도 실패하여 실행 전에 거절했다.
- **Z5 / RUNTIME_FAIL**: 생산량 평균 aggregation과 `operation=average`를 중복 생성했다.
  집계 후 Calculate가 원래 `value`를 요구하면서 출력 필드 lineage가 끊겼다.
  데이터 부족이 아니라 semantic composition 문제다. holdout 관찰 후 생산 코드를 다시
  튜닝하지 않았고 실패를 그대로 남겼다. 평균 후 재평균의 정당한 의미도 있을 수 있으므로
  두 필드를 무조건 중복 제거하는 수정은 하지 않았다.
- V2 Document → EntitySet → ForEach의 physical materialization은 이번에 지원 완료하지 않았다.

다음 보완 후보는 그룹 차원의 최종 출력 보존, 단항 집계/후속 계산의 입력 필드 계약이다.
질문별 prompt 규칙을 추가하는 방식으로 해결하지 않는다.

## 독립 oracle 및 감사

실제 모델이 만든 프로그램을 그대로 실행하고 별도 SQL로 평균·건수·극값·차이를 계산했다.
기간/대상, 최고·최저 날짜 역할, 출력 컬럼 lineage, 단위, source/provenance를 검사했다.
감사에서 발견한 잘못된 PASS 가능성도 수정했다.

- 최고/최저 날짜 교환 → 실패
- TypedResult 단위 훼손 → 실패
- metadata는 정상이고 행의 별칭 단위만 훼손 → 실패
- source 제거 → 실패
- 요청 필드 누락/모호한 필드/alias 충돌 → 실패

read-only 독립 감사에서 마지막 단위 변조 재현이 정상 거절되는 것을 확인했다.
새 계약 회귀는 `test_semantic_v2_linkage.py`의 22 tests다.
가격 외 생산량·무역, 다른 광종·연도·어순, 복수 requested output도 포함한다.

기존 245 QA/287턴 저장 requirement replay는 151턴 PLAN_REJECTED,
136턴 REPLAYED_NOT_SEMANTIC_PASS다. 조기 validation으로 실패 위치가 옮겨간 것을
질문 해결이나 runtime 신규 회귀로 집계하지 않았다. 질문 PASS 승격은 하지 않았다.

## 회귀 및 재현

시작 전체 regression: 1228 PASS / 687 subtests.
최종 전체 regression: **1250 PASS / 687 subtests / 0 FAIL**, 기존 정상 PASS→FAIL 0.
실제 출력은 함께 보관한 `final-regression.log`를 기준으로 한다. compileall과 git diff --check도 통과했다.
기존 3개 negative contract 테스트는 의도적으로 변경했다: unknown output source 묵인,
Compare operation 표현 불가, unknown reference의 뒤늦은 실패를 새 계약에 맞췄다.
정상 질문의 기대 수치를 통과 목적으로 바꾸지 않았다.

```bash
PYTHONPATH=inhouse:. python3 -m pytest inhouse/rag_core/tests -q
PYTHONPATH=inhouse:. python3 -m inhouse.rag_core.tests.qa500_linkage_eval --output /tmp/new-run.jsonl
PYTHONPATH=inhouse:. python3 -m inhouse.rag_core.tests.qa500_linkage_eval --fresh-holdout --output /tmp/new-holdout.jsonl
```

결과: `qa500_linkage_20261002/summary.json` 및 같은 폴더의 gzip trace.
원본 모델 출력, candidate별 오류/재시도, typed requirement, LogicalProgram, lowering,
synthetic 조회 인자, 노드/최종 결과, source/provenance, 평가 오류를 보존했다.
후기 capture에는 코드/프롬프트 SHA-256, 재판정에는 원본 capture SHA-256도 남긴다.
이 작업은 미커밋·미배포이며 잔여 모델 오류를 모두 해결한 상태는 아니다.
