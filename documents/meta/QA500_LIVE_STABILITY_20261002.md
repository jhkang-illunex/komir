# 전체 회귀·반복 안정성·실제 SSE 검증

## 판정: NOT_READY

`iterative-audit`으로 사전 격리 점검과 사후 독립 감사를 수행했다. 코드 회귀는 통과하지만
실제 live 경로에서 의미 오류와 실행 실패가 재현되어 배포 게이트를 통과하지 못했다.
이번 요청은 검증이므로 production 구현을 추가 수정하지 않았다. 기존 미커밋 변경도
보존했다. 500문항 전체를 운영 데이터로 실행했다는 의미가 아니다.

## 실행 환경 / 변경 범위

| 대상 | 이미지 | 처리 |
|---|---|---|
| 운영 18002 | `komir-rag-chat:audit-safety22`, `31b7ed55…` | 유지, health 및 전용 신규 세션 2건 SSE |
| 기존 검증 18011 | `komir-rag-chat:audit-relations30`, `5c7915c4…` | 유지, health 확인 |
| 새 검증 127.0.0.1:18012 | `komir-rag-chat:qa-stability-sse31`, `952c21c5…` | 현 소스 빌드, 실제 SSE, 검증 서버만 cold restart |

현재 작업트리는 dirty이므로 HEAD만으로 이미지 내용을 설명하지 않았다. 핵심 소스
SHA-256과 이미지 내부 파일 해시가 일치함을 확인했다. 운영·기존 검증 이미지의
semantic_v2/live_multihop 파일은 현재 소스와 다르다.

새 검증 환경은 기존 실제 PostgreSQL 데이터를 읽되 연결에
`default_transaction_read_only=on`을 적용하고 `SHOW transaction_read_only=on`으로
확인했다. 이는 읽기 전용 계정/RBAC 구현이 아니라 이번 연결의 방어 설정이다.
세션용 MSR_DB와 MULTIHOP_HISTORY_DSN은 별도 `komir-qa-history31` PostgreSQL로
분리했고, 필요한 history 테이블은 그곳에만 생성했다. 외부 포트는 노출하지 않았다.
PageIndex/OKF는 운영과 같은 경로의 읽기 전용 마운트다. env allowlist로 수집기 키와
Langfuse 원격 전송 설정은 배제했다. 비밀값은 산출물에 기록하지 않았다.

초기 읽기 전용 옵션 URI의 공백이 `+`로 인코딩되어 psycopg2 연결에 실패했다.
`%20`으로 바로잡고 검증 컨테이너를 다시 만들었다. 초기 요청은
`excluded-preflight/`로 분리했고 최종 23회 SSE 판정에 포함하지 않았다.

운영 18002의 두 정상 API 요청은 `qa-sse31` 전용 사용자·신규 세션을 사용했다.
**정상 API 처리에 따른 운영 테스트 대화/history 저장 부수효과가 있다.** 따라서
“운영 DB 쓰기 0”이라고 주장하지 않는다. 수동 업무 데이터 수정/삭제, 운영 schema
migration 실행, 운영 서버 교체·재시작, commit/push는 하지 않았다.

## 경로 차이: V2와 live는 동일하지 않다

실제 모델은 Gemma `gemma-4-26b-a4b`, temperature=0이다.

- 반복 평가: `parse_v2_shadow` → SemanticRequirementV2 → deterministic planner →
  lowering → 격리 synthetic backend → 독립 SQL. Gold는 평가기에만 사용했다.
- SSE: `MULTIHOP_ORCHESTRATOR_MODE=enabled`, `SEMANTIC_INTENT_MODE=enabled`의
  live `ASTProgramModel`/SemanticProgram 또는 기존 ActionPlan 경로.
- V2가 production 응답을 소유하도록 전환하지 않았다. SSE 통과를 V2 운영 배포
  통과로 보거나, V2 단위 테스트를 live parser 보장으로 해석하지 않는다.
- 실제 SSE에는 AST cache hit가 있다. 같은 답변 반복을 새 모델 생성 안정성으로
  집계하지 않았다. 별도 V2 반복 120회는 이 live AST 캐시를 사용하지 않았다.

## 실제 Gemma 반복 평가

기존 core28 + U4 + V4 + W4, 총40문항을 각각 3회 호출했다. 새 질문이나 새 정답
fixture는 추가하지 않았으며, 실패 기록도 모두 보존했다.

| 문항 기준 | 수 |
|---|---:|
| 세 번 모두 PASS | 33 |
| 반복 간 변동 | 5 |
| 세 번 모두 정상 unsupported | 2 |
| 미실행/PENDING | 0 |

120회 실행: **PASS106 / LOGICAL_PLAN_INCOMPLETE8 / UNSUPPORTED_CORRECT6**.
변동 문항은 H3, R4, R6, V2, Z4다. 성공한 반복만 골라 PASS하지 않았다.
기존 500문항 전체의 자연어 성공률로 확대할 수 없으며, 가격 high/low 표현의
모호한 Gold 계약도 기존 기록대로 남아 있다. 모델 반복 안정성 전체 해결 아님.

## 실제 SSE: wire와 의미 판정 분리

검증·운영·재시작 포함 **23회** 요청을 원시 SSE와 JSON으로 저장했다.
22회는 done 1개로 정상 종료, 1회는 의도적으로 클라이언트가 연결을 종료했다.
HTTP는 모두200이었다. 별도의 빈 메시지 요청은 예상대로 HTTP422다.

검사한 wire 계약: JSON 파싱, status 1~4, done 단일·최후 이벤트, table 필수 필드,
행 너비, 중복 컬럼/블록 ID, chart의 앞선 table 참조, citation index/source.
이 검사 범위의 wire 오류는0이다. 브라우저 UI 실제 렌더링 테스트는 아니다.

| 의미 판정 | 수 | 내용 |
|---|---:|---|
| PASS | 7 | 가격3, 시계열2, 순수 실행요청 거절1, 다른 사용자 세션 접근 거절1 |
| PARTIAL | 5 | 보고서 광종별 가격: 16개 중2성공/14실패 |
| FAIL | 7 | 후속3, 합계/조합2, 운영가격1, 취소 전파1 |
| 출력 요구 충족 미확정 | 2 | usage+price: 가격 성공, 용도 설명은 시장동향 발췌로 반환 |
| 안전한 기권이나 사유 분류 부족 | 2 | 미지원 광종/미래 실측값 모두 validation_failed |
| 합계 | 23 | wire 정상과 semantic PASS는 별개 |

### 독립 SQL

- 니켈502: LME CASH, MNRL0002, PR001/WT002. 최신 관측일2026-09-30,
  통상가격22,916.73. 검증 서버의 재시작 전후 최신값과 일치한다.
- 2025-10~2026-09 니켈502 월평균12행: 원시 관측을 별도 SQL로 집계하여 두 SSE의
  월/평균값과 비교했다. 허용 오차0.000001 미만으로 전부 일치한다.
- 구리2024: 실제 관측 mineral code는 MNRL0008, 원천19행.
  SU/OT를 제외한17국 합계 **6,998,520.20톤**, 국가별 평균 **411,677.658823529412톤**,
  합계-평균 **6,586,842.541176470588톤**. 상위5국만 합하면 **6,024,000톤**으로 다르다.
  원천 국가·단위·구분과 정규화 ton 필드를 함께 저장했다. SU 세계합계와 국가 모집단
  합계를 혼동하지 않았다. `RAG_ALLOW_DUMMY=1` 환경의 DB 대조이지 공식 실측 보증이 아니다.
- 니켈2030년 실제 가격 관측은 별도 조회0건. 미래값을 생성해 답하지는 않았다.

## 확인된 실패 경계

### 1. High: 후속 projection을 새 조회로 바꾸고 성공 반환

가격 조회 뒤 “방금 조회된 광종은 무엇인가요?”가 이전 entity를 복원한 뒤 새
`retrieve(domain=price)`를 실행해 60행 가격표로 답했다. 최종 abstained=false다.
history 복원 성공과 사용자 요구 충족은 다르다. 출력 의미 검증 누락이며 false success다.
근거: `sse/price-followup.json.gz`, `sql.json.gz`의 해당 session.

### 2. 합계 계약 불일치 + 전체 모집단 누락

live AST는 `aggregate.args={calculation:sum,field:production_volume}`을 생성했고
runtime은 `aggregation`과 실제 생성된 측정 필드를 요구해 `unsupported_aggregate_contract`.
더 중요하게, 앞선 resource 조회는 전체17국이 아니라 기본 Top5의5행이다.
키 이름만 치환하면 잘못된 합계를 전체 합계처럼 답할 수 있으므로 안전한 수정이 아니다.
합계·평균·차이 조합은 별도 실행에서 선행 입력 없는 집계 노드로 `missing_input`,
후속 단계 `DEPENDENCY_FAILED`가 기록됐다. 실제 데이터 부재로 분류하지 않는다.

### 3. 저장 복원과 후속 필드 실패를 구분

재시작 전 보고서 후속은 filter field 누락으로 AST validation 실패했다.
재시작 후에는 저장된16개 결과 복원과 success 필터2개 선택이 확인됐지만,
Project가 실제 `mineral` 대신 `entity`를 요청해 `projection_field_unavailable:entity`.
저장 유실이라고 단정하지 않는다. live 결과는 `result_json`과
`history:<turn_id>:<step_id>` 참조를 통해 복원된다. `result_id=NULL`/빈 snapshot만 보고
persistence 실패를 선언하지 않았다.

### 4. PARTIAL 정보가 화면에서 축소됨

보고서에서16개 광종을 확보하고16개 항목 결과를 저장했다. 리튬·희토류2성공,
14개는 `empty / retrieval unavailable:validation_failed`다. 원천 데이터가 실제로
없다는 판정과 다르다. 화면에는 두 가격표와 일반적인 일부 실패 문구만 있고 실패
광종별 이유가 없다. 성공값 폐기는 없지만 전체 요구 성공으로 판정할 수 없다.
fresh/history/cold restart에서 이 결과가 관찰됐다.

### 5. 취소 전파 미완료

클라이언트는0.095초에 두 이벤트 수신 후 연결을 종료했다. 그러나 서버에서는 해당
질문의 AST 재시도와 오류 로그가 계속됐다. 영구 orphan task가 남았다는 증거는
아니지만 expensive operation의 즉시 취소는 통과하지 못했다.

### 6. 운영 버전 차이

운영가격 요청은 `slot_unresolved`, 새 검증이미지는 같은 질문에 정상 가격이다.
운영보고서 요청은 새 이미지와 같은 PARTIAL이다. 두 요청만으로 운영 전체 기능을
판정하지 않았으며 운영 이미지를 교체하지 않았다.

## 독립 audit 및 regression

읽기 전용 독립 감사자는 실제 저장 결과·SSE·코드 경계를 대조했다.
**Critical0 / High1 / 배포 판정 NOT_READY**. High는 후속질문의 false success다.
합계/모집단, projection, PARTIAL, 취소는 별도 배포 차단 실패로 유지했다.
숫자 PASS나 done=true로 전체 성공을 주장하지 말라는 감사 결과를 반영했다.

- rag_core 시작/최종: **1335 PASS / 687 subtests / 0 FAIL**.
- rag_chat + common 시작/최종: **152 PASS / 17 subtests / 1 FAIL**.
- 실패: `PublicPrivateBoundaryTest.test_composite_index_is_publicly_allowed`.
  해당 테스트는 실제 MCP/검색을 호출했고 evidence=[]로 실패했다. 격리된 mock-only
  테스트라는 설명과 실제 실행이 다르다. core 통과로 숨기거나 임의 skip하지 않았다.
- 이번 라운드 production code 변경0, 신규 PASS→FAIL0. 전체 테스트가0FAIL은 아니다.
- Docker build, compileall, git diff --check 통과.
- Langfuse 원격 자격증명 검증, 브라우저 UI, 실제 tool/LLM timeout 주입,
  multi-worker failover 검증은 미수행이다. 이들을 통과했다고 보고하지 않는다.

## 재현 근거 / 잔여 자원

[자동 집계](qa500_live_stability_20261002/summary.json),
[반복 평가](qa500_live_stability_20261002/stability-summary.json),
[이미지·설정 식별](qa500_live_stability_20261002/environment.json).
동일 디렉터리에 raw SSE, 질문/세션별 판정, 독립 SQL, 서버 로그,
실패한 초기 환경 기록, 회귀 로그와 재현 스크립트를 보존했다.

검증18012와 격리 PostgreSQL은 재현용으로 유지했다. 실패 preflight 컨테이너는
정지 상태로 보존했다. 운영18002와 기존18011의 이미지·시작 시각은 변하지 않았다.
이번 결과는 배포 승인이 아니며, 후속 수정에서는 우선 **live parser/runtime 계약과
모집단 완전성**을 함께 다뤄야 한다. V2에만 추가 규칙을 넣어 해결된 것처럼 보이면 안 된다.
