# AAST Content Repair 2026-10-02

## 범위

- 검증 포트: `18012`
- 운영 포트 `18002`: 변경하지 않음
- 검증 이미지: `komir-rag-chat:aast-content-r4`
- 이미지 digest: `sha256:4f669d44bd06ca868c249918d5b614a22deddd3f25fbbed42f04f7153d58eed5`
- 공식 content baseline: `27/57 (47.37%)`

이번 라운드는 실행 성공 여부와 content correctness를 분리했다. HTTP 200,
`done=true`, non-abstain은 CONTENT_PASS로 계산하지 않았다.

## 적용한 공통 수정

1. 페이지 추천 renderer가 registry의 검색 필터 계약을 `screen_guidance`로
   projection하도록 수정했다. 질문 문자열이나 QA ID 분기는 없다.
2. semantic parser fallback에 typed resolution error를 보존하고, 독립적인
   `forecast.price` branch가 빠진 legacy map fallback만 `BRANCH_COVERAGE_REQUIRED`
   로 AAST에 승격하도록 direct contract를 수정했다. 기타 legacy composite
   fallback 전체를 일괄 승격하지 않는다.
3. 기존 `forecast.price` branch 누락 회귀 테스트와 페이지 검색조건 projection
   테스트를 추가했다.

## 6건 replay

| QA | 결과 | 최초 원인/근거 |
|---|---|---|
| DOC04 | `CONTENT_PASS` | 페이지 registry의 기간·검색대상·검색어 입력 계약이 최종 안내에 포함됨 |
| ADD45 | `FORMAT_PASS` 후보, `CONTENT_PASS` 아님 | 페이지·URL·리튬 필터 binding은 정상이나 엄밀한 oracle 문구와는 다름 |
| CN04 | `CONTENT_FAIL` | 무역 map만 실행되던 경로를 차단하고 `semantic_plan_incomplete`로 종료. 가격전망 branch 실행 없음 |
| REG06 | `CONTENT_FAIL` | 니켈 결과와 텅스텐의 조회 불가/기준 선택 필요를 함께 보존. 전체 비교로 위장하지 않음 |
| MI02 | `CONTENT_FAIL` | 현재 근거는 니켈 공급구조·용도 문서이며, oracle의 원자번호·금속 기본특성 근거가 아님 |
| NEWS03 | `CONTENT_FAIL` | 최근 일반 뉴스는 반환되지만 중국 수출통제 주제 evidence는 확인되지 않음 |

6건 중 새 `CONTENT_PASS`는 1건(DOC04), 의미 보존 기반 `FORMAT_PASS` 후보는
1건(ADD45)이다. 나머지 4건을 근거 부족 상태에서 성공으로 만들지 않았다.

## 11건 content-gap replay

기존 11건(`MI02, DOC04, NEWS03, MP01, MP06, CN04, REG02, REG03, REG06,
ADD27, ADD45`)은 전체 57건 replay에서 같은 이미지와 fresh session으로
재확인했다.

- projection 회복: DOC04
- format-only 회복: ADD45
- evidence mismatch 유지: MI02, NEWS03
- branch/data 제한 유지: CN04, REG06
- snapshot 정상화로 의미상 통과 가능한 oracle 항목: MP01, MP06, REG02, REG03
- ADD27: 가격 추이 요구에 최신값만 반환되는 별도 projection/content gap

## 전체 replay 결과

57건 전체 SSE replay는 `/tmp/aast-content-r4-57-new/`에 저장했다. 기존
content-pass 집합 27건 중 이번 수정 때문에 새로 실패한 항목은 0건이다.
현재 replay에서 MP01이 `semantic_plan_incomplete`으로 종료된 실행이 있었으나,
동일 현상은 `aast-content-r2` replay에도 존재했고 이번 두 수정이 원인이 아니다.
trace상 AAST validator가 `scope=KR`를 AST에 없다고 판정하는 별도 기존 문제다.

공식 baseline에 DOC04 회복을 반영하고, 이 기존 MP01 실행 변동을 별도 회귀로
계산하면 이번 이미지의 관측 content 상태는 다음과 같다.

```text
공식 baseline                       27/57 (47.37%)
이번 수정으로 회복                  +1 (DOC04)
이번 수정으로 발생한 regression      0
별도 기존 MP01 관측 실패             1
현재 관측 content-pass               27/57 (47.37%)
```

즉 이번 라운드의 공통 수정은 DOC04의 content를 회복했지만, 기존 MP01의
별도 AAST validator 문제와 상쇄되어 공식 점수 순증으로 나타나지 않았다.

## 회귀 검증

- `PYTHONPATH=.:inhouse pytest -q inhouse/rag_core/tests`
  - **1461 passed**, 1 warning, 695 subtests passed
- 대상 app unit tests
  - direct/page 관련 **14 passed**
- 전체 `inhouse/rag_chat/tests`
  - 154 passed, 1 failed, 15 subtests passed
  - 실패: 기존 `test_sse_cancellation`의 `legacy_control` 호출 횟수 기대치
    (`expected 3`, observed 4). 이번 content 수정과 무관한 기존 cancellation
    contract 차이로 별도 기록하며, CONTENT_PASS 회귀로 계산하지 않았다.

## 남은 원인

- CN04: forecast branch를 생성·실행할 수 없는 semantic/lowering 경로. 현재는
  무역 branch만 성공한 부분응답을 내지 않도록 차단한다.
- REG06: 텅스텐 가격기준/관측 데이터가 확인되지 않아 완전한 공통기간 비교 불가.
- MI02: 현재 document evidence와 질문의 금속 기본특성 oracle이 불일치.
- NEWS03: 현재 뉴스 fixture/data 범위에서 중국 수출통제 evidence가 없음.
- ADD27: 시계열을 요구했으나 최종 projection이 최신값으로 축약되는 문제.
- MP01: 기존 AAST coverage validator의 `scope=KR` 보존 판정 문제.

이번 라운드에서는 위 데이터·AAST·시계열 projection 문제를 질문별 규칙,
정답 하드코딩, evidence validator 완화로 우회하지 않았다.
