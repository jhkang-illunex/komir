# Live 공통 계약 수정 및 실제 SSE 재검증

## 판정: NOT_READY — 공통 결함 수정, 전체 운영 안정화는 미완료

`iterative-audit`과 `qa-build`를 적용했다. 질문별 분기/semantic regex/새 Action은
추가하지 않았다. 기존 dirty worktree의 QA500 작업은 보존했고 이번 회차의 수정은
live 계약, 결과 연결, 전체 모집단 조회, cancellation과 해당 테스트에 제한했다.
500개 전체를 실제 운영 데이터로 재실행한 결과는 아니다.

## 수정 및 검증 경계

| 공통 원인 | 수정 |
|---|---|
| 집계 field·입력 계약 불일치 | live aggregate의 입력/aggregation/field 검증, 실패 시 최대 3회 구조 재생성. raw query 재해석 없음 |
| 전체 합계를 기본 Top-5로 계산 | resource_population=all → 기존 tool top_n=None → SQL limit 미적용. 명시 Top-N과 충돌하면 거절 |
| 국가 선택 누락·이름 불일치 | resource_country 및 country Filter가 원천 국가코드/국문/영문을 사용. 하나의 alias가 복수 코드면 기권 |
| 저장 결과 projection이 재조회/빈 출력으로 변환 | query/reference/refresh 계약, 권한 있는 history ENTITY만 참조, evidence 없는 계획용 Entity 제외, entity/mineral 정규화 |
| COMPOSITE 목록 projection이 가격 renderer로 전달 | Project 결과를 FACT_SET으로 전달하고 partial·evidence·provenance 보존 |
| PARTIAL에서 실패 항목이 사라짐 | 성공 항목과 실패 상태·사유 표 모두 보존. 전체 실패는 성공으로 표시하지 않음 |
| ForEach latest label과 실제 조회 결과 불일치 | output default를 실제 하위 호출에도 적용. latest 결과 snapshot은 기준시점 이하 관측 1행 |
| disconnect 후 AST 재시도 지속 | request-local cancellation 전달, generator/thread bridge 종료. 이미 실행 중인 동기 LLM 호출 자체의 즉시 중단은 보장하지 않음 |
| 회귀가 실제 MCP 가용성에 의존 | composite-index 테스트에 deterministic MCP fixture 적용. production retrieval은 그대로 |

관련 파일:

- `inhouse/rag_core/ragkit/live_multihop.py`, `semantic_ir.py`, `action_contract.py`
- `inhouse/rag_core/ragkit/chatbot_graph.py`, `_mcp_tools_common.py`
- `inhouse/common/komis_raw.py`
- `inhouse/rag_chat/app/streaming.py`, `app/routers/chat.py`
- 새 테스트 `test_live_contract_repair.py`, `test_live_resource_population.py`,
  `test_live_country_alias.py`, `test_live_foreach_output_contract.py`, `test_sse_cancellation.py`
- 기존 테스트 `test_live_multihop.py`, `test_retrieval_routing.py`

대상 파일에는 이전 작업의 미커밋 diff도 포함된다. 전체 git diff를 이번 수정만의
변경량으로 집계하지 않았다. commit/push는 수행하지 않았다.

## 실행 환경

- 운영18002: `komir-rag-chat:audit-safety22` 유지. 시작시각
  `2026-10-01T12:02:54.490338051Z` 그대로. 이번 회차 운영 요청·교체·재시작 없음.
- 기존18011 유지. 검증은 **127.0.0.1:18012** 하나만 사용.
- 최종 검증 이미지 `komir-rag-chat:qa-live-repair32-r4`:
  `sha256:5b9b4e350ebfd8e12ad0c904b88c91d0640f9e73e26f5524927e08b1dee3243a`.
- 기본 Containerfile로 dependency 포함 이미지를 빌드한 후 동일 `/app/common`,
  `/app/rag_core`, `/app/app` 경로에 수정 소스를 반영했다. fixtures는 이미지에 주입하지 않았다.
- 컨테이너 내부 live source hash `97fde55ea205452415cffd56bfff40afe58d1c454eb739923c510f45d037ff80`
  및 app/common 해시가 작업 소스와 일치.
- 실제 Gemma와 PageIndex/OKF readonly mount, 실제 업무 PostgreSQL 읽기 전용 연결.
  `SHOW transaction_read_only=on` 확인. 세션은 별도 `komir-qa-history31` PostgreSQL.
  업무 데이터 수정/삭제·운영 migration 없음. RAG_ALLOW_DUMMY 개발 설정은 유지했으며
  SQL 수치 일치를 공식 실측값 인증으로 해석하지 않는다.
- 내부 parser/raw output/Action slots trace는 검증 환경에서만 활성화.

## 실제 SSE 결과 — 실패 실행도 보존

회차 r1~r4 및 검증 재시작 후 총 **47요청**: HTTP200 47, done45, 의도적 취소2,
검사한 wire 오류0. HTTP200은 의미 성공이 아니다.

| 전체 실행 판정 | 건수 |
|---|---:|
| 요청 결과 PASS | 23 |
| PARTIAL | 4 |
| 산술 일치, 자연어 차이 방향 모호 | 4 |
| FAIL | 11 |
| 정상 unsupported | 2 |
| 다른 사용자 접근 거절 | 1 |
| client cancellation | 2 |
| 합계 | 47 |

마지막 r4만 17요청: PASS9 / PARTIAL1 / 차이 방향 모호1 / FAIL3 /
정상 거절1 / 소유권 거절1 / 취소1. 각 요청 원문·세션·시각·이미지 해시·원시 SSE와
개별 판정은 `qa500_live_repair_20261002/semantic-summary.json` 및 `sse/`에 있다.
r1/r2/r3 결과를 r4 성공으로 덮어쓰지 않았다.

### 독립 SQL 및 구조화 결과

| 대상 | SQL | 최종 SSE/저장 root |
|---|---:|---|
| 구리2024 국가 합계 | 6,998,520.20톤 | 동일 |
| 평균 | 411,677.658823529412톤 | 동일 허용 부동소수 오차 |
| 칠레 단일값 | 2,098.1톤 | 칠레 1행, 동일 |
| Top-5 합계 | 6,024,000톤 | 전체 합계와 다름; 순위 5개 회귀 유지 |
| 니켈502 최신 통상가격 | 22,916.73, 2026-09-30 | 동일 |

생산량 19행에서 SU/OT를 제외한 코드가 식별되는 17국가 모집단을 사용한다.
원천 `prdctn_quty_ton`과 단위/구분을 검사하며 “공식 세계 총량”으로 일반화하지 않는다.
SU/OT 포함 원천 행과 SQL/bindings는 저장했다. 130국가 synthetic fixture로
기본 상한100을 넘겨도 full 조회 130행이 보존됨을 별도로 검증했다.

평균·합계의 구조화 root를 Compare 입력으로 사용하며 LLM이 다시 계산하지 않는다.
원문 “평균과 합계, 둘의 차이”는 r1 합계−평균, r2~r4 평균−합계로 달라졌다.
각 산술은 맞지만 동일 질문의 방향 안정성은 통과로 주장하지 않는다.
명확한 “합계에서 평균을 빼줘”는 r3/r4 모두 Gemma가 조회 없이 aggregate를 생성해
3회 검증 후 실패했다. **SSE execution_failed지만 최초 실패 단계는 parser/plan이다.**

### 문서·후속 참조·복원

r1~r3 문서 가격은 16항목 중 2성공/14검증 실패였고, r4는 latest 출력 인자를
실제 호출까지 전달한 상태에서 **7성공/9검증 실패**였다. 성공 집합도 달라졌으므로
문서 가격 조회 전체의 수치·단위·모델 안정성 통과로 확대하지 않는다.
실패는 `retrieval unavailable: validation_failed`이며 데이터 부재의 증거가 아니다.
성공 일부 항목의 단위 코드는 evidence에 있지만 정규화 표시 단위는 None으로 남아 있다.

r4 성공 항목은 망간·크롬·티타늄·안티모니·몰리브덴·니오븀·네오디뮴이다.
각 성공 snapshot은 latest 1행이다. 후속 성공 광종 projection은 이 7개와 일치하고
새 retrieve/for_each 없이 저장된 typed 결과만 사용한다.
검증 컨테이너 cold restart 후 동일 세션에서도 동일 목록을 복원했다.
이번 live 기록의 DB result_id 컬럼은 null이며 `history:<turn_id>:<step_id>` binding으로
복원했다. result_id 기반 영속 복원까지 검증했다고 주장하지 않는다.

“지금 다시 조회”는 재시작 후 Gemma가 downstream projection에 없는 period 필드를
요청하여 실패했다. 갱신 후 새 결과 생성 완료로 보고하지 않는다.
다른 user_id의 같은 session 접근은 error+done, 결과 미노출을 확인했다.
실제 인증 보안 전체/RBAC 검증이라는 의미는 아니다.

## 독립 audit / 회귀

첫 독립 감사에서 history prefix 신뢰/참조 node hijack을 발견하여 권한 있는 ENTITY와
root ancestry 검증으로 수정했다. 다음 감사의 국가 alias 복수 코드 문제도 동일 국가의
여러 연도와 구분해 해결했다. 최종 증분 감사 **Critical0 / High0**.
이는 변경 diff의 판정이며 서비스 전체 READY를 의미하지 않는다.

- rag_core **1,382 PASS / 695 subtests / 0 FAIL**.
- rag_chat + common **163 PASS / 17 subtests / 0 FAIL**.
- 보호 backend/관련 계약 표적 회귀 **275 PASS**.
- 독립 SQL·구조화 입력·저장 projection·접근 거절 assertions **8/8**.
- Docker build, compileall, git diff --check 통과.
- 최종 기존 PASS→FAIL **0**. 중간 resource_country 과잉 제한으로 15실패가 발생했으나
  정상 country binding을 복원하고 재실행했다. 실패 로그도 보존했다.
- app 테스트 첫 명령은 PYTHONPATH 누락으로 collection 실패했다. 기존 환경대로
  `PYTHONPATH=inhouse:.` 재실행한 위 163건 결과와 구분한다.
- 실브라우저 UI, Langfuse 원격 전송, 부하/장시간 soak 검증은 하지 않았다.

## 남은 배포 차단 사항

1. 명시적 합계−평균의 조회 dependency를 Gemma가 누락하는 반복 실패.
2. 모호한 “둘의 차이”의 방향 불안정. 정답 방향을 질문별로 주입하지 않음.
3. 매장량 조회 validation_failed → aggregate_input_incomplete. 생산량으로 대체하지 않음.
4. 문서 광종별 가격 검증 실패 및 일부 단위 표시 미확정. 성공 수만 보고 배포하지 않음.
5. history 대상 갱신 요청의 projection field 계약 위반.
6. parser 실패가 공개 응답에서 포괄적 execution_failed로 나타나는 진단 한계.

추가 구조 확장/질문별 prompt 패치 없이 이번 audit round를 닫으며 운영 배포는 보류한다.

## 진단 중 보안 주의

수동 schema 확인 명령에서 잘못된 URI scheme을 psycopg2에 전달하여 연결 문자열이
도구 오류 출력에 한 차례 포함됐다. 값은 재기재하지 않으며 저장 산출물은 URI/토큰을
redact했다. 노출된 연결 자격증명의 교체를 권고한다. 자격증명을 임의 변경하지 않았다.
