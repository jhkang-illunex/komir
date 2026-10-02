# QA57 ROI Fast Repair — 2026-10-02

## 범위

- 공식 full-replay baseline: `27/57 (47.37%)`
- 이번 라운드 시작 provisional 후보: `31/57`
- 운영 `18002`: 변경하지 않음 (`komir-rag-chat:current-session-r19`, running)
- 검증 `18012`: `komir-rag-chat:resource-population-r8`, running
- 검증 범위: ADD16·GM01 cluster 및 기존 경로 sentinel, 57건 full replay 미실행

## 공통 수정

1. `analytical_share`/live calculate
   - `division`, `percentage`, `percent`를 기존 population-share 계산의 semantic alias로 정규화
   - 명시적인 `ratio`는 numerator/denominator typed field가 있을 때만 계산
   - 불완전 population·0 분모·비수치 operand는 기존 fail-closed 계약 유지
2. `relational_ops`
   - 키 없는 독립 다중행 `COMPARE(operation=side_by_side)`는 행 위치로 pairing하지 않고
     `comparison_side=left|right`로 독립 행을 보존
   - side-by-side에 비교 field가 없거나 country/entity 같은 dimension을 field로 준 경우
     등록된 canonical metric field만 결정론적으로 추론
   - difference/ratio/percent_change와 keyed multi-row 비교는 계속 explicit alignment 필요
3. `live_multihop` field resolution
   - day-level date가 없는 연간 resource row에서는 유일한 `year` field를 date projection의
     temporal alias로 보존; 월/일을 임의 생성하지 않음

## Fast Regression 결과

관련 unit/regression: **157 passed** (`test_live_relations.py`, `test_qa500_series.py`)

| QA | 결과 | 실제 근거 |
|---|---|---|
| ADD16 | `PROVISIONAL_CONTENT_PASS` 후보 | SSE 완료, 2025 snapshot에서 칠레 매장량 비중 24.86%, resource citation 유지 |
| GM01 | `PROVISIONAL_CONTENT_PASS` 후보 | SSE 완료, 생산 12행 + 수입 151행, `comparison_side` left 12/right 151 |
| ADD27 | 기존 회복 유지 | SSE 완료 |
| MP01 | 기존 회복 유지 | SSE 완료 |
| 희토류 생산·매장량 상위국 | 기존 resource 회귀 유지 | SSE 완료, production/reserves 2 branch |
| 오늘 니켈 가격 | Direct sentinel 유지 | SSE 완료 |

GM01의 중간 실패는 `comparison_alignment_required`와 `comparison_field_required`로 재현됐다.
키 없는 독립 모집단 presentation을 일반화했으며 산술 비교에는 적용하지 않았다.

## 다음 cluster로 남은 항목

- **MP04**: 현재 live trace의 최초 실패는 `AAST Coverage Validator → METRIC_PRESERVATION_FAILED`.
  Semantic requirement `resource_yoy`에 대해 AST가 `production` retrieval + `yoy` calculate를
  만들었으나 derived metric equivalence가 없다. 결과를 임의 생성하지 않고 semantic planning/
  derived-metric contract로 분리했다.
- **GM13**: 현재 live trace는 `semantic_plan_incomplete`; 단순 runtime contract로 확정할
  근거가 없어 별도 semantic cluster로 유지했다.
- 문서 sentinel의 source unavailable은 데이터/evidence 상태이며 이번 contract 수정의
  회복 대상으로 세지 않았다.

## 잠정 점수

ADD16·GM01의 실제 회복 후보를 기존 `31/57`에 누적하면 **최대 `33/57 (57.89%)` provisional**이다.
이는 full replay 전 잠정치이며 공식 baseline을 변경하지 않는다.

## 배포 경계

검증 이미지와 컨테이너만 r8로 교체했다. 운영 18002는
`komir-rag-chat:current-session-r19`, `running`으로 유지됐다.

