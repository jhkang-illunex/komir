# 후속 참조 경계 국부 수정 및 검증

## 작업 원칙

전체 요청 흐름은 원인 추적에 사용하고, 수정은 의미가 처음 손실되는 계약에 한정한다.
특정 질문·QA ID·광종·국가에 따른 분기와 semantic regex는 추가하지 않는다.
검증 기준은 HTTP 200이나 schema validity가 아니라 대상·필드·값·기간 보존이다.
같은 경계의 테스트에 대상 종류, 모집단 크기, 기간, 표현을 바꾼 반례를 포함한다.
새로운 실패가 다른 책임 경계에 있으면 기존 수정의 성공으로 포장하지 않는다.

## 확인한 원인과 수정 범위

직전 턴의 최종 선택 결과는 7개였지만, 그 턴에 보존된 inherited ENTITY
중간 결과는 원래 모집단 16개였다. 모델 context가 둘을 모두 출력 후보로 제공했고
후속 재조회에서 중간 결과를 선택했다. 최종 출력과 실행 중간 결과의 구분 문제다.

- `live_multihop.py`: 모델에게 제공하는 기본 history는 턴의 명시적 root output으로 제한.
  저장된 중간 결과 자체는 삭제하지 않는다.
- `reference_scope=active/explicit_history`로 현재 결과 참조와 명시적 과거 결과 참조를 구분.
  기존 InputRef를 유지한다. inherited ENTITY scratch를 최종 출력처럼 참조하지 못하게 검증한다.
- 다중 root에 `previous` 등의 불명확한 별칭이 오면 첫 root로 대체하지 않는다.
- 저수준의 정당한 원래 모집단 참조는 유지한다. 모든 intermediate 접근을 일괄 금지한
  초기안은 기존 HHI 모집단 복원 회귀를 깨뜨려 철회했다.
- 재조회 성공 결과에도 `status/reason/output` 메타데이터를 보존하도록 가격 typed contract를 맞췄다.
- `semantic_ir.py`: 가격의 실제 출력 metadata field 계약과 validation 오류 진단을 정합화했다.

추가·수정 테스트: `test_live_reference_output_boundary.py`, `test_live_price_fanout.py`.
국가 및 기간 참조, 16→7·3→1·31→5 모집단, 다중 root, 명시적 과거 원본 참조를 검증했다.
새 Action·질문별 special-case·semantic regex: 각각 0.

## 검증 결과

| 검증 | 결과 | 주장 범위 |
|---|---:|---|
| 전체 rag_core | 1449 PASS / 695 subtests | 기존 회귀 실패 0 |
| 앱·common | 163 PASS / 17 subtests | 기존 회귀 실패 0 |
| 실제 Gemma 참조 질문 | 9/9 | 참조 대상 선택 검증, 최종 수치 응답 검증 아님 |
| 실제 Gemma 국가·기간 holdout | 6/6 | 참조 선택·기간 보존 검증 |
| 최종 이미지 SSE | 10 요청 | 아래 실패를 포함하므로 10 PASS로 집계하지 않음 |
| 기존 SSE assertion | 19/20 | 단축 표현의 가격 재호출 0건; 재호출 여부만으로 의미 판정하지 않음 |

실제 SSE에서 명시적 재조회 두 표현은 선택된 7개에 대해서만 가격을 조회하고
최종 본문에 가격을 반환했다. 원래 16개 목록으로 돌아가는 명시적 참조도 확인했다.
단축 표현은 아래 의미 실패가 있으므로 전체 완료로 판정하지 않는다.

## 남은 재현 가능한 실패: repair가 가격 필드를 제거

3턴: 문서 광종별 가격 → 성공 광종 목록 → “그 목록 가격 다시 보여줘”.

직전 projection은 광종 목록이고 가격 value가 없다. 모델은 처음 `value`를 요청하지만
validation 실패 후 재계획하면서 `value`를 제거했다. 최종 root는
`mineral/output/reason/status/unit`뿐이다. 7개 대상으로 범위는 정확하지만 가격이 없다.
최종 SSE는 “7개 처리 완료”와 메타데이터 표를 출력하므로 **의미 실패**다.

이는 7→16 참조 범위 확대와 별개인 repair output coverage 문제다.
“다시 보여줘”가 새 조회를 반드시 뜻하지는 않으므로 새 조회 0회를 단독 실패 근거로 삼지 않는다.
실패 근거는 가격을 요청했는데 저장 가격 복원도 새 가격 조회도 없고 최종 가격값도 없다는 점이다.
근거: `reference_boundary_20261002/sse/refresh-short.json`.

이를 특정 표현을 재조회로 강제 분류해서 숨기지 않았다. 다음 수정 경계는
재계획 전후 requested output coverage 및 선택된 대상에 한정한 저장 값 복원이다.
첫 번째 잘못된 모델 AST 전체를 정답처럼 고정하는 방식도 피해야 한다.
### 국부 수정 결과

재계획 계약에 다음 일반 불변식을 추가했다.

- `reference`/`refresh` 계획의 repair는 이전 root projection field를 축소할 수 없다.
- 저장 snapshot에 해당 field가 없으면 동일 InputRef를 소비하는 새 조회를 생성해야 한다.
- 새 조회를 추가한 repair는 `result_access=refresh`여야 한다.
- 새 독립 `query`의 첫 계획에서 모델이 추정한 잘못된 field는 이 불변식의 대상이 아니며,
  기존 AST validation이 정정할 수 있다.

검증 이미지 `komir-rag-chat:qa-reference-boundary34-r6`에서 실제 Gemma/SSE를 재실행했다.
단축 표현, 명시적 재조회 2개 표현 모두 선택된 7개 광물의 실제 `value`를 반환했고,
가격 없는 메타데이터 성공 응답은 재현되지 않았다. 문서 선택·성공 목록 필터·재조회
대상은 모두 동일한 7개로 유지됐다. `done.abstained=false`, HTTP 200, SSE table 완료를
확인했다.

최종 회귀: rag_core **1450 PASS / 695 subtests**, app/common **163 PASS / 17 subtests**.
compileall 및 `git diff --check` 통과. 운영 18002/18011 및 업무 DB는 변경하지 않았다.

이 수정은 가격 재조회 repair의 출력 계약만 다루며, 모든 자연어 안정성을 증명한다고
확장해석하지 않는다. 실제 확인한 동일 패턴의 3개 표현에서는 미해결 실패가 0건이다.

## 배포 및 근거

- 검증 전용: loopback 18012, `komir-rag-chat:qa-reference-boundary34-r3`.
- 이미지: `sha256:8caffeb62dd5e72073080b86cd2a03d20e13cf0ba27d5f52453a03b53299b3f3`.
- 운영 18002: `komir-rag-chat:audit-safety22`, 시작 시각 `2026-10-01T12:02:54.490338051Z` 유지.
- 운영 18002/18011 및 업무 DB 변경 없음. 커밋·푸시·운영 배포하지 않음.
- 실제 Gemma 출력, 변환 Program, 참조 expected/actual, SSE, 이미지 식별자,
  회귀 출력은 `reference_boundary_20261002/`에 보존.
- 소스 경계의 독립 증분 감사에서 High/Critical은 발견되지 않았으나,
  위 실제 SSE의 의미 실패는 별도로 남는다. 코드 감사 통과를 E2E 통과로 대체하지 않는다.
