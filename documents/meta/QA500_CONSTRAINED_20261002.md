# QA500: 스키마 강제 생성과 compiler-owned operand 검증

## 결론 / 범위

반복 안정성 전체 해결은 **미완료**다. 서버 측 JSON Schema 강제 생성은 실제 지원되지만,
이번 같은 질문·같은 oracle 반복에서 기존 JSON 모드보다 의미 성공/안정성이 좋아지지 않았다.
따라서 기본값·운영 설정을 바꾸지 않았다. 질문별 prompt/regex/alias 패치는 추가하지 않았다.

작업은 qa-build의 Gold/production 분리와 iterative-audit의 계약 변경 집중 감사에 따라
진행했다. 기존 더티 변경을 보존했다. 운영18002·검증18011·DB·이미지·commit/push 미변경.
18002는 `komir-rag-chat:audit-safety22`, 18011은 `komir-rag-chat:audit-relations30` 그대로다.
이 보고서는 V2 shadow 실제 Gemma + 합성 backend 평가이며 운영 SSE 검증 결과가 아니다.

## 구현

1. `common/llm/openai_compat.py`: 호출별 optional `json_schema`를 전달한다.
   명시적으로 요청한 constrained 모드가 400/401/422 등으로 거절되면 즉시 실패하며
   json_object/무제약 호출로 조용히 내려가지 않는다. 429/5xx는 기존 전송 재시도 정책.
2. `common/llm_client.py`: client config `structured_output_mode="json_schema"`일 때만
   output_model의 실제 schema를 wire에 전달한다. 기본 호출/stream은 변경하지 않았다.
   로컬 Pydantic 검증 및 bounded repair는 유지한다. mode를 호출 기록에 남긴다.
3. `semantic_v2.py`: Compare의 fields가 생략된 경우 **양쪽이 단일 수치 집계 출력임이
   기존 계약에서 확정된 때만** Planner가 실제 output_field/value를 연결한다.
   명시한 필드는 덮어쓰지 않고, 좌우 operand 순서를 유지한다.
   원시 가격 시계열의 value/high_price/low_price 중 하나를 추정하지 않는다.
   source_node가 잘못되면 자동 대체하지 않는다.

새 Semantic field/Action/operator/질문별 특례/semantic regex/모델 prompt 변경: 각각 0.
모든 ID·projection을 모델에서 제거한 것은 아니다. 특히 여러 출력의 참조 의미를 잃지 않고
내부 ID 생성을 완전히 분리하는 작업은 이번 작은 계약 보완으로 해결됐다고 주장하지 않는다.

## 계약 전후 증거

같은 typed plan(가격 max/min 집계 → difference, 명시 operand fields 생략)을 기존
explicit-only 연결 규칙으로 재현하면 `requires comparison field`와 downstream dependency
실패가 발생한다. 수정 후 fields=`[peak, trough]`, adapter gap 없음, SUCCESS,
`difference=10.0 USD/t`이며 합성 DB의 독립 `MAX(value)-MIN(value)`도 10.0이다.
실제 시장 가격이 아닌 공통 deterministic fixture 값이다.

difference/ratio/percent_change, ID 변경·좌우 반전, 없는 source, 명시 잘못된 field,
원시 다중 측정 필드 거절, 전송 실패 시 downgrade 금지, 요청 간 schema 비누수를 검증했다.

기존 음성 테스트 2개는 unique aggregate도 항상 missing fields로 거절하던 기대를 가지고
있었다. 음성 입력을 raw multi-measure로 바꿔 모호성 거절을 유지하고, 같은 aggregate의
fields 생략을 기존 독립 SQL 양성 테스트에 추가했다. 수치 oracle을 바꾸거나 실패 검증을
삭제하지 않았다. 이 계약 기대 변경을 숨긴 채 모든 테스트가 무변경이라고 주장하지 않는다.

## 실제 서버 및 반복 설계

- 실제 endpoint: localhost:52302, model `gemma-4-26b-a4b`, temperature0.
- output budget2000, 기존 schema repair1회 + semantic reparse1회 유지.
- 작은 schema 지원 확인1회 및 schema와 반대 값/추가 key를 요구한3회 모두 통과.
  반대 지시에도 `{marker: SCHEMA_ENFORCED, count: 7}`만 반환했다.
- 실제 SemanticRequirement 전체 schema smoke: T1~T4, 4/4 PASS.
- 기존28문항 ×3회 ×2모드 =168 QA 실행.
- 사전에 고정한 새 표현 U1~U4 ×5회 ×2모드 =40 QA 실행.
- 반복 주평가 합208회, 보조 smoke 포함212회. 내부 repair를 포함한 HTTP completion
  수와 동일하지 않다. 고유 업무 QA는 주평가32 + 보조 smoke4 =36개다.
- 기존 source corpus/원장은 재등록·덮어쓰지 않았다. 새4건은 평가 fixture로만 등록했다.
  모두 기존 2nd-order 연산의 parameter/paraphrase 변형이며 신규 operation coverage는0.
- 양 모드 모두 같은 prompt, semantic compiler hash, 독립 SQL·단위·출처·날짜 역할
  oracle로 평가했다. ProcessPool spawn으로 synthetic network guard를 격리했다.
- U1~U4 결과를 보고 production 튜닝하지 않았다. 소규모·동일 연산군 표본이며 전체
  QA500 또는 일반 BI 정확도로 외삽하지 않는다. 모드 간 latency 우열도 측정하지 않았다.

## 결과 — best-of 금지

### 기존28문항, 각3회

| 항목 | json_object | json_schema |
|---|---:|---:|
| QA 실행 | 84 | 84 |
| PASS 실행 | 62 | 59 |
| LOGICAL_PLAN_INCOMPLETE | 10 | 14 |
| PARSER_MISSING_OUTPUT | 0 | 3 |
| RESULT_MISMATCH | 3 | 0 |
| OUTPUT_CONTRACT_FAIL | 3 | 2 |
| UNSUPPORTED_CORRECT | 6 | 6 |
| 전회 PASS 질문 | 17 | 16 |
| 성공/실패 변동 질문 | 6 | 8 |
| 전회 실패 질문 | 3 | 2 |
| 전회 정상 거절 질문 | 2 | 2 |

### 새4문항, 각5회

| 항목 | json_object | json_schema |
|---|---:|---:|
| PASS 실행 /20 | 19 | 16 |
| 전회 PASS 질문 | 3 | 3 |
| 변동 질문 | 1 | 1 |

U2(기간 내 최대/최소 날짜와 차액)는 기존모드4/5, 강제모드1/5 성공이다.
성공한 회차만 선택하지 않았다. 다른 세 질문은 두 모드 모두5/5이나 장기 안정성의 증명은 아니다.

### 주평가32문항 accounting (모드별)

| 항목 | json_object | json_schema |
|---|---:|---:|
| TOTAL_CORPUS / REGISTERED | 32 /32 | 32 /32 |
| PASS (전회 성공만) | 20 | 19 |
| FAILED (변동 포함) | 10 | 11 |
| CAPABILITY_GAP | 0 | 0 |
| UNSUPPORTED | 2 | 2 |
| BLOCKED | 0 | 0 |
| PENDING | 0 | 0 |

두 모드의 PASS를 합치거나 보조 smoke4건을 반복 안정 PASS에 더하지 않는다.
각 열 `PASS+FAILED+CAPABILITY_GAP+UNSUPPORTED+BLOCKED+PENDING=32`.

## 남은 실패

원본 시계열과 집계 scope 혼동, 잘못된 source/field 연결, 날짜 projection 누락,
통상가격과 일중 최고/최저 혼동이 남는다. 강제 schema는 Python의 교차 필드
model_validator 및 질문 의미를 보장하지 않는다. 출력 길이 제한도 무한 출력 보장을 하지 않는다.
이러한 실패를 DATA_UNAVAILABLE로 바꾸거나 숫자/필드를 임의 대체하지 않았다.

이번 추가 스키마 전송은 **실험용 opt-in**으로 유지한다. 프롬프트를 문제 문장마다 고치는
방식은 사용하지 않았으며, 이번 결과만으로 기본 활성화할 근거는 없다.
후속으로 여러 requested output의 의미 참조를 내부 node/column 명명에서 분리하려면
별도의 작은 계약 설계·독립 holdout 검증이 필요하다. 이번 완료 범위에 포함하지 않는다.

## 회귀 / 감사 / 아티팩트

- Baseline: 1276 PASS /687 subtests /0 FAIL.
- 중간: 기존 음성 기대 충돌1 FAIL을 명시적으로 분석하고 위 계약 테스트로 보완.
- 최종: **1290 PASS /687 subtests /0 FAIL**. 추가14 tests.
- 미해결 기존 PASS→FAIL:0. 계약 기대 조정2개 별도 공개.
- compileall / git diff --check: PASS.
- 독립 targeted audit: High/Critical0. 모호한 필드 및 explicit invalid field를 보정하지
  않는지, schema downgrade/요청 간 누수, legacy ValueError repair 보존을 재확인.

`qa500_constrained_20261002/summary.json`은 모드·QA·회차별 자동 집계와 hash를 담는다.
gzip 원장에는 실패도 그대로 보존했다. terminal LLMOutputError 때 원본 응답을 trace에
담지 않는 기존 관찰 한계는 남아 있으며 해당 실패의 오류 이유·로그는 보존했다.
4xx 예외 종류를 RuntimeError로 좁히는 최소 호환성 수정은 평가 중 수행했으나,
평가 기록에 해당 HTTP 거절은 없었고 성공 요청 본문·모델 prompt·semantic hash는 동일하다.

STATUS: DONE — 이번 제한된 구현·비교·회귀 실행 완료, PENDING0.
모델 반복 안정성 해결/운영 반영 완료라는 뜻이 아니다.
