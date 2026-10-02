# QA500 계약 부족 분해·fixture 보완

이번 범위는 기존 원장의 `ACTUAL_PLAN_CONTRACT_GAP` 245 QA다. 500개 질문을
다시 생성하거나 기존 원장을 덮어쓰지 않았다. qa-build를 적용하되 운영 서버·DB,
Gemma 프롬프트, schema vocabulary, Action/Tool/SSE는 변경하지 않았다.

## 분해 결과

245건 모두 ID·질문·원본 raw SHA·requirement·Logical node·실패 이유·필수 계약을
연결했다. 다음은 **QA 단위 중복 발생 수**이며 합산해서 245가 되는 표가 아니다.

| 누락/불일치 계약 | QA |
|---|---:|
| Join 연결 키 | 85 |
| Compare 피연산 필드 | 98 |
| 입력 개수 | 43 |
| upstream 생성 필드 / projection | 88 |
| 문서 범위 | 46 |
| 기간 표현 | 23 |
| physical slot vocabulary | 15 |
| 광종 binding | 38 |

분류 미완료 QA 0. 그러나 **최초 책임 경계가 모두 확정됐다는 뜻은 아니다.**
관계 키/필드가 requirement 단계부터 누락된 것으로 직접 확인된 고유 QA 168,
관계 입력 개수가 requirement부터 맞지 않는 QA 41, 그 밖의 원인에 별도 의미 검토가
필요한 QA 165다(세 수치 역시 중복). 구조 비교만으로 parser와 schema 책임을 단정하지 않았다.

## 대표 증거와 Gold 분리

- EXT500-009: 월평균과 관측일 수. 실제 requirement의 `join_key=null`,
  `fields=["month"]`; 실제 Logical Join에는 `join_key=null`만 있다.
  fields를 Join key로 해석한다는 계약은 없으므로 adapter에서 몰래 채우지 않았다.
  독립 Gold에는 명시적인 month key를 두고 평균/count를 결합해 SQL과 비교했다.
  니켈/구리/리튬/코발트 × 각 지정 연도 4개 Gold는 모두 일치했다.
- EXT500-037: 최고/최저 차이. Compare에 필드와 연산 관계가 없다.
  현재 RelationshipSpec은 `operation="difference"`를 허용하지 않는다.
  별도 단항 Calculate에 difference를 넣는 것과 두 결과를 차감하는 것은 다르다.
  이를 데이터 부족으로 분류하거나 신규 schema를 임의로 추가하지 않았다.
- EXT500-202: 금액/중량 순위 차이 조건. 실제 Compare의
  `predicate={"abs_diff_threshold":3}`가 planner에서 사라졌다.
  지원되지 않는 관계 predicate를 조용히 무시하지 않고 명시적으로 거절하도록 했다.

## Fixture와 수정 반복

신규 `test_qa500_contract_matrix.py` 34 tests:

- 완전한 SemanticRequirement → Logical AST → price.series lowering → 합성 runtime → 독립 SQL.
- Join/Compare 키·필드·입력 누락, 상충하는 compare operand: 명시 실패.
- 월별 평균+관측일 수 4변형: 결과·기간·광종·provenance 검증.
- 문서 범위, 지수 slot, 생산량/매장량 metric 보존.
- concrete 기간, placeholder 날짜, 역전 기간, 0개월.
- 정적 광종 누락에서 기본 광종/이력으로 대체 금지.
- 모든 projection 필드 확인, 단위 metadata 보존/부재 시 거절.
- 실제 저장된 Gemma의 누락 키는 Gold 실행 후에도 그대로 실패.
- schema 표현 불가 관계를 부정 테스트로 고정. 이 테스트 PASS는 기능 지원 PASS가 아니다.
- 245개 원장 누락·중복·자동 PASS 승격 방지.

재현 후 최소 수정한 production 경계는 두 파일 세 항목이다.

1. `semantic_ir.py`: Project 필드 중 하나만 존재해도 통과하던 검증을 각 필드 검증으로 수정.
2. `semantic_v2.py`: concrete range의 symbolic 날짜/역전 날짜를 lowering 전에 거절.
3. `semantic_v2.py`: Join/Compare predicate가 조용히 사라지는 대신
   `unsupported_relationship_predicate`를 반환. 임의 Filter/연산으로 변환하지 않음.

독립 감사에서 1번 수정이 TypedResult.unit metadata를 잘못 정적 거절하는 회귀를 발견했다.
추가 fixture로 FAIL을 재현한 뒤 unit만 기존 runtime materialization/존재 검증에 맡겼다.
단위가 실제로 없으면 `projection_field_unavailable:unit`으로 실패한다.
질문별 production branch, 새 Action, 새 semantic regex, fixture→production 참조는 추가하지 않았다.

## 실제 재검증

- 시작 전체 회귀: 1,194 PASS / 0 FAIL / 687 subtests.
- 최종 신규 계약 회귀: 34 PASS.
- 최종 전체 rag_core: **1,228 PASS / 0 FAIL / 687 subtests**.
- 기존 PASS→FAIL: 0. compileall / git diff --check 통과.
- 저장된 245 QA / 287턴을 수정 단계별로 재생. 신규 Gemma 호출 0, 운영 SSE 호출 0.
- 최종 재생: 252턴 runtime 경로 재생, 35턴 명시적인 미지원 predicate 계획 거절.
  이 35턴은 고유 35 QA이며, 의미를 잃은 채 실행하던 것을 거절한 것이지 지원 성공이 아니다.
- 실제 자연어 QA의 PASS 승격: **0**. 기존 500건 원장의 4 PASS / 468 FAILED / 28 GAP을
  변경하지 않았다. 계약 fixture의 PASS를 해당 245 질문의 PASS로 세지 않았다.

기존 500건 원장 accounting: 500 = 4 PASS + 468 FAILED + 28 CAPABILITY_GAP;
UNSUPPORTED/BLOCKED/PENDING은 모두 0(이전 평가 상태를 보존, 운영 성공률 아님).
이번 계약 분류 작업 accounting: 대상 245 / 분류 245 / 미분류 0.

## 산출물과 재현

- `inhouse/rag_core/tests/qa500_contract_inventory.py`: 실패 계약의 test-only 분해·현재 재생.
- `inhouse/rag_core/tests/test_qa500_contract_matrix.py`: 독립 Gold/누락/충돌 fixture.
- `qa500_validation_20261002/contract_inventory_round1.json.gz`:
  Project/날짜 경계 수정 후 predicate 보존 감사 전 기록.
- `contract_inventory_round2.json.gz`: predicate 명시 거절 후, unit 회귀 수정 전.
- `contract_inventory_round3.json.gz`: unit 수정 후.
- `contract_inventory_final.json.gz`: 최종 코드 SHA가 포함된 245개 질문별 상세 trace.

```bash
PYTHONPATH=inhouse:. pytest -q inhouse/rag_core/tests/test_qa500_contract_matrix.py
PYTHONPATH=inhouse:. python3 -m inhouse.rag_core.tests.qa500_contract_inventory \
  --replay --output /tmp/qa500-contract-new.json
PYTHONPATH=inhouse:. pytest -q inhouse/rag_core/tests
```

남은 질문 실패는 requirement 누락, 관계 연산의 schema 표현 한계, projection 명명/출처
계약, 문서 범위·기간·derived binding 구분 등이다. 특히 `fields`를 Join key로 추정하거나
predicate를 임의 연산으로 바꾸면 의미가 달라질 수 있어 시행하지 않았다.
계약 fixture 보완 라운드는 완료했지만 245건 기능 수정 완료나 운영 E2E 완료가 아니다.

STATUS: DONE (계약 분해·fixture·재현된 검증 오류 수정 범위)
