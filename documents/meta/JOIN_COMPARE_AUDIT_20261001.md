# Join / Compare iterative-audit (2026-10-01)

## 범위와 결과

이전 live-contract audit에서 명시 기권 처리한 Join/Compare를 실제 live
SemanticProgram → lowering → LangGraph → typed result 경로에 구현했다.
기존 Action/Tool, 업무 DB, frontend wire protocol은 변경하지 않았다.
신규 질문별 분기·semantic regex·Intent·Action은 0개다.
기존 dirty 변경은 보존했으며 이번 작업은 아직 커밋하지 않았다.

위험도 HIGH(계산·근거·부분 실패). iterative-audit에 따라 수정 전 실패 재현,
계약 수정, 결정론적 테스트, 실제 Gemma/SSE, 집중 감사·수정을 수행했다.
별도 외부 premium 모델 감사는 수행하지 않았으며 자체 감사와 실행 근거를 사용했다.

## 변경 파일과 계약

- `inhouse/rag_core/ragkit/relational_ops.py`: 두 typed input의 키 기반 Join/Compare.
- `live_multihop.py`: 실제 연산 연결, 등록된 필드 alias의 엄격한 해석,
  기존 통화/중량 코드 기반 단위 정규화, AST 계약 안내와 기간 검증 재파싱.
- `semantic_ir.py`: 두 입력·조회 결과·키·비교 필드 검증, downstream 출력 필드 보존.
- `tests/test_live_relations.py`: 신규 회귀 29개.

Join은 inner/left/full, 단일/복합 키와 서로 다른 좌우 키 이름을 지원한다.
입력 완료 순서가 아니라 InputRef 순서를 사용한다. 중복/NULL 키는 거절하며,
암묵적 row-order zip이나 Cartesian expansion은 하지 않는다.
원천 필드는 left./right. namespace로 분리하고 양쪽 기간·단위·대상·출처를 보존한다.

Compare는 side_by_side, difference(left-right), ratio(left/right),
percent_change((left-right)/abs(right)*100)를 지원한다.
수치 계산은 알려진 동일 단위에서만 실행한다. 통화 환산은 수행하지 않는다.
0 분모·NULL·비유한 값·짝 없는 날짜는 계산 성공으로 처리하지 않는다.
성공과 결손이 섞이면 PARTIAL, 계산 가능한 행이 없으면 EMPTY다.
거절된 upstream evidence를 outer join으로 되살리거나 불완전 모집단을 성공으로
승격하지 않는다. 후속 Project에서 계산 결과를 사용하는 runtime 회귀도 통과했다.

## 재현과 회귀

- 구현 전 신규 테스트: 13 FAIL / 5 PASS. unsupported Join/Compare가 주요 원인.
- 기존 전체 기준: 710 PASS / 146 subtests PASS.
- 최종 전체: **739 PASS / 146 subtests PASS / 0 FAIL**, 23.27초.
- 기존 PASS→FAIL: **0**.
- routing smoke, compileall, git diff --check, Docker build, health 확인 통과.
- 전체 명령: `python3 -m pytest -q inhouse/rag_core/tests`.
- 로그: `/tmp/komir-relations30-regression.log`.

집중 감사에서 증거가 승인되지 않은 EMPTY 입력, output 필드 충돌,
substring alias 오인, row 단위 불일치, 완료 순서가 뒤집힌 입력을 추가 검증했다.
실제 DB의 주석 포함 열 이름과 기준 설명이 섞인 단위 문자열도 회귀에 포함했다.

## 실제 배포 검증

운영 `komir-rag-chat-18002`는 audit-safety22 그대로이며 재시작하지 않았다.
운영 image SHA256: `31b7ed55fded35d8e4a7f172e5882fc394c05bded47075417e85894bc468e9e9`.
검증 포트 18011만 재사용했다. 현재 컨테이너 `komir-rag-chat-audit30`,
이미지 `komir-rag-chat:audit-relations30`, SHA256
`5c7915c49aae9af85a5083a2a0351314545b67c3e08975caf800454f81e789b2`.
시작 시각 `2026-10-01T13:50:28.873315833Z`.
기존 개발 데이터/더미 허용 설정을 유지했다. 실제 공식 시세 정확성 검증이라는 뜻은 아니다.

실제 질문:

- Join: 니켈과 리튬의 최근 1개월 가격을 날짜 기준 내부 조인한 결과를 보여줘.
- Compare: 니켈과 리튬의 최근 1개월 통상가격을 같은 날짜끼리 비교해서 니켈 가격에서
  리튬 가격을 뺀 차이를 날짜별로 보여줘.
- Ratio: 같은 두 시계열에서 니켈 가격을 리튬 가격으로 나눈 비율을 날짜별로 요청.

| 실행 | session_id | 실제 결과 |
|---|---|---|
| Join | 1eb0a5a8-9624-421c-ae4c-29e6662d1144 | 22개 날짜 일치 행, 양쪽 가격·출처·표·단일 done |
| Ratio | 93eb3dd5-bc09-4ca8-9373-68dbe0743dcf | 22개 계산 성공 + 2개 unmatched_key, PARTIAL |
| Difference 최초 | cb409706-1681-4c6a-9469-cd8abcd0a3df | Gemma 비교 field 누락, 3회 재파싱 후 실패. backend 미도달 |
| Difference 재실행1 | c80024c9-df40-4b12-911a-3f1aae200a1a | 22개 계산 성공 + 2개 결손, PARTIAL, 7.04초 |
| Difference 재실행2 | 07778dde-6aa1-4e67-9800-9430320635d5 | 동일 결과, 1.22초. 캐시 가능성이 있어 독립 Gemma 안정성 증명으로 세지 않음 |

성공 AST는 Entity 두 개 → Retrieve(price, trailing_months=1) 두 개 →
Compare(join_key=date, left_field=price, right_field=price, operation=difference/ratio)다.
실제 source는 `public.KO_MNRL_PRC`. 2026-09-30 입력은 22916.73 / 13335.89 USD/톤,
차이 **9580.84**, 비율 **1.7184252419598542**다.
SSE의 rows_typed를 별도 Python Decimal로 다시 계산한 결과, 각 실행의 22개
성공 행 모두 오차 1e-8 이내였다. Join 날짜 대조 오류도 0개였다.
이는 독립 산술 대조이며 원천값의 독립 SQL 검증으로 주장하지 않는다.

SSE 원본은 `/tmp/komir-relations{27,28,30}-{case}.sse`, 재실행은
`/tmp/komir-relations30-difference-repeat{1,2}.sse`에 보존했다.
임시 파일이므로 장기 artifact 저장소는 아니다.

## 남은 문제와 한계

1. 실제 Gemma의 비교 field 누락/불필요한 단일 입력 Compare 생성 변동이 남았다.
   schema-valid와 의미 성공을 동일시하지 않는다. 실패 기록을 삭제하지 않았다.
2. 니켈·구리 비교는 구리 Retrieve가 advisor_rejected였다. 실제 원인은
   `대표 가격기준 'LME CASH'이 광종 MNRL0008에 매핑되어 있지 않습니다.`이며
   source_audit RDB 0행이었다. 가격기준을 임의로 바꾸지 않았고 관계 실행기는
   dependency_unavailable로 종료했다. Join/Compare 산술 실패와 구분한다.
3. 지정일 두 가격 차이 질문은 기존 legacy FAQ shortcut에서 원천 차이 설명으로
   먼저 소비되는 사례가 있었다(session 813961f1-bdf3-4e39-b62c-fcf88e9298ab).
   이번 관계 실행기 수정으로 그 라우팅까지 해결했다고 주장하지 않는다.
4. 기본 표는 양쪽 원천 필드와 메타데이터를 넓게 표시한다. 기존 자동 chart는
   date를 숫자로 해석하고 status를 축으로 선택하는 등 표현 품질 문제가 있다.
   이번 SSE 검증의 PASS 범위는 계산값·표·출처·상태 보존이며 차트 의미 품질은 제외한다.
5. 다대다 join, 단위 환산, 3개 이상 입력의 암묵 조합은 지원하지 않는다.
   정확한 두 입력 계약을 여러 AST node로 합성해야 한다.

결론: typed Join/Compare 실행과 실제 데이터 SSE 연결은 확인했다.
모든 자연어 비교 질문의 안정적 성공이나 운영 배포 완료를 의미하지 않는다.
