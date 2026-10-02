# QA106 18012 Iterative Audit — 2026-10-02

## 범위

- 대상: 2026-10-02 source-backed oracle miss 34건
- 검증 포트: `127.0.0.1:18012`
- 최종 검증 이미지: `komir-rag-chat:qa106-contract-r5`
- 운영 포트 18002: 변경하지 않음
- 원본 기준: `qa106_grounded_comparison_20261002.csv`
- 재실행 원장: `qa106_miss_replay_20261002.json`

## 반복 감사 결과

실제 SSE에서 다음 공통 계약 문제를 수정했다.

1. 날짜 필드만 있는 시계열에서 `group_by=year/month`를 요청하면 날짜에서
   typed temporal grouping key를 결정적으로 파생한다.
2. `inventory.latest`와 `indicator.series`가 retrieval 경계에서 metric을
   잃지 않도록 typed metric을 보존한다.
3. 재고 원천의 `재고량`·`원시 단위 코드`를 표준 projection의 값·단위 필드로
   연결하되, 일반 분석 field resolver의 누락 필드 실패 계약은 유지한다.

질문별 route, 광물명, QA ID 분기, semantic regex, 신규 Action은 추가하지 않았다.

## 34건 재실행 집계

| 구분 | 건수 |
|---|---:|
| 수정 전 oracle miss | 34 |
| 수정 후 SSE 성공 | 2 |
| 수정 후 미해결 | 32 |
| 확인된 fixture 추가 대상 | 0 |

수정 후 성공:

- `REG04` 니켈 가격 연도별 평균 — `table`, citation `public.KO_MNRL_PRC`
- `REG05` 니켈 LME 재고량 — `table`, citation `public.ko_mnrl_prc + public.ko_mnrl_prc_crtr`

## 남은 원인 분포

| 분류 | 건수 | 대표 원인 |
|---|---:|---|
| parser/계획 생성 | 13 | `semantic_plan_incomplete`, `all_roots_failed` |
| typed projection 계약 | 6 | `date`, `country`, `mineral`, `document` 필드 누락 |
| dependency/join 조합 | 6 | `dependency_unavailable`, downstream join 실패 |
| 비교·기간 정렬 | 2 | `comparison_alignment_required` |
| 데이터/외부/adapter 계약 | 5 | 가격기준 매핑, forecast, retrieval validation, adapter, ambiguous |

이 분류의 합계는 32건이다. 현재 trace만으로 실제 데이터 부재로 확정할 수 없는
항목은 fixture gap으로 승격하지 않았다.

## 대표 trace

- 연도 평균: `retrieve(price)` 성공 → `aggregate(field=price, group_by=year)` 성공
  → `project(year, avg_price)` → SSE table/done 성공
- 재고: `inventory.latest` 성공 → `project(date, inventory, unit, value)`에서
  원천 `재고량`·`원시 단위 코드`를 typed projection으로 연결 → SSE table/done 성공
- 리튬 최신 가격: `price_criterion_mapping_missing` — 대표 기준 registry가
  있어도 DB 광종-기준 매핑이 없으므로 fixture로 가격을 만들어내지 않음
- 가격–지수 비교: 양쪽 retrieval 여부와 별개로 공통 날짜 정렬 계약에서
  `dependency_unavailable`/`comparison_alignment_required`가 남음
- 중국 수출통제 뉴스: Gemma가 `UNSUPPORTED_REQUEST`를 반환해
  `semantic_plan_incomplete`로 종료. 문서 fixture를 추가해 해결할 문제가 아님

## 검증

- focused contract tests: 통과
- `rag_core` 전체: `1454 passed`, `695 subtests passed`
- `compileall`: 통과
- `git diff --check`: 통과
- 최종 r5 health check: 통과
- 최종 34건 재실행 transport 오류: 0

## 결론

fixture 추가만으로 18012의 정답률을 올릴 수 있는 것으로 확정된 건은 이번
34건에서 없었다. 실제 개선된 2건은 공통 typed contract 수정으로 회복됐다.
나머지는 parser/계획, projection/join, 가격기준 매핑 또는 외부 데이터 의존을
각각 별도 감사해야 하며, 임의 synthetic row 추가로 PASS 처리하지 않는다.

## r6/r7 공통 contract audit

추가 수정은 다음 범위로 제한했다.

1. `UNKNOWN_CAPABILITY`를 안전 요청으로 확정하지 않고, bounded parser repair에서
   일반 데이터·문서·메뉴 질의로 재평가하도록 했다. 명시적인 안전 사유는 계속
   terminal unsupported로 유지한다.
2. `source`는 행의 물리 column이 없더라도 단일 provenance를 가진 TypedResult의
   metadata projection으로 사용할 수 있도록 했다. 복수 source는 계속 거부한다.
3. compare 입력이 typed metric을 갖는 경우 비교 field/date key를 AST 구조에서만
   보완한다. raw query, QA ID, 광종 문자열은 읽지 않는다.

focused contract tests: `64 passed`
full `rag_core` regression: `1454 passed`, `695 subtests passed`

최종 검증 이미지: `komir-rag-chat:qa106-contract-r7`
검증 포트: `18012` (운영 `18002` 미변경)

고정 57개 fresh-session replay 결과는
`documents/meta/qa106_answerable_r7.json`에 저장했다.

- 실행: 57/57
- transport error: 0
- non-abstain 후보: 25/57 (43.9%)
- abstain: 32/57

이는 내용 정답 확정 수가 아니라 실행·응답 후보 coverage다. 내용 정확도는
oracle numeric/content 비교를 별도 수행해야 하며, non-abstain을 자동 PASS로
승격하지 않았다.

기준선 23개 중 첫 replay에서 기권으로 보인 6개는 재실행 결과 4개가 회복되어
코드 regression으로 확정되지 않았고, `MI01`과 `DOC02`는 반복 기권으로 남았다.
따라서 현재 모델/문서 경로에는 실행 변동성이 존재하며, 이번 라운드의 net
accuracy 증가를 2건으로 단정하지 않는다.

이번 공통 수정으로 재현성 있게 확인된 회복은 `NEWS03`의
`UNKNOWN_CAPABILITY` 오판 완화이며, 가격기준 미매핑·resource category·문서
근거 부재는 데이터/계약 부족으로 남겼다. fixture와 운영 18002에는 변경이 없다.
