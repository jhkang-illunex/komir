# QA57 Full E2E Validation — `fa423722c` — 2026-10-03

## 1. 검증 범위

- 코드 수정: 없음
- QA repair: 없음
- 운영 `18002`: 변경·재시작·배포 없음
- 검증 포트: `18012`
- r31 결과 `18/57`: `VALIDATION_ENVIRONMENT_DRIFT`로 무효 처리, 공식 baseline으로 사용하지 않음
- QA corpus: `QA57_CONTENT_BASELINE_20261002.md`의 57건
- 실행: 각 QA 독립 session, 정확히 1회
- 잘못 기본 선택된 QA106 실행은 03/106에서 중단했으며 결과에 포함하지 않음

## 2. 환경 고정 및 사전 검증

| 항목 | 확인 결과 |
|---|---|
| build source SHA | `fa423722caeb86bfb83e6561e3b355b20da2ef38` |
| validation image | `komir-rag-chat:qa57-fa423-validation-20261003` |
| image digest | `sha256:0cb927a75830f9453c57b37d198724772a0bce355fb71b49a2cd796dfb0ed803` |
| image/container | `komir-rag-chat-qa57-fa423` / `faf536689b17f9d3d0d57b702c73c961e227babd1b550a3372797174eaa45fc7` |
| container image ID | image digest와 일치 |
| build timestamp label | `2026-10-03T04:02:35Z` |
| OCI revision label | `fa423722caeb86bfb83e6561e3b355b20da2ef38` |
| container start | `2026-10-03T04:04:18.830287379Z` |
| `/healthz` | HTTP 200 |
| Gemma/vLLM | `127.0.0.1:52302/v1/models` HTTP 200, `gemma-4-26b-a4b` |
| DB | PostgreSQL `select 1` 성공 |
| MCP/source startup | 앱 startup 완료, MCP subprocess 경로 활성화; OKF/PageIndex read-only mount 확인 |
| document mount | `/app/data_lake/semi_structure/okf_documents` read-only |
| PageIndex mount | `/app/data_lake/semi_structure/pageindex_trees` read-only |
| network/extra host | Docker `bridge`, `host.docker.internal:host-gateway` |
| 주요 설정 | `QUERY_GATE_ENABLED=0`, `SEMANTIC_INTENT_MODE=enabled`, `RAG_ALLOW_DUMMY=1`, `LLM_TEMPERATURE=0`, timeout 180/240초 |

### 핵심 source checksum

| 파일 | host | image |
|---|---|---|
| `rag_core/ragkit/live_multihop.py` | `e6ff6033598f04d1084ba037fb8b8748cb4198cb8f00854dde3893d7c1a2c766` | 동일 |
| `rag_core/ragkit/semantic_v2.py` | `b835e6d742afc544c0e3e028d9fe97794a6a3b7a072be81138fdb2dfde7f9e7d` | 동일 |
| `rag_core/ragkit/chatbot_graph.py` | `45288982c0e5661f6ff3e8ec9b4c4b109d8f2f9c00c72de9112dc260640fc7ce` | 동일 |

환경 동일성 검증은 모두 통과했으므로 QA57 replay를 진행했다.

## 3. 실행 요약

원본 runner 결과:

- `PASS`: 7
- `PARTIAL`: 19
- `FAIL`: 31
- SSE terminal: 57/57
- 총 실행 시간: 559.01초
- 평균 latency: 9.81초
- median: 6.95초
- p95: 24.82초
- 가장 느린 QA: `MP05 57.06s`, `GM12 37.03s`, `IX01 31.69s`, `GM14 24.82s`, `PF02 23.93s`

Raw 실행 결과는 다음 임시 경로에 생성됐다.

`/tmp/qa57_full_fa423_20261003.bQRYlc/user_qa_pair_audit_20261003_130928.json`

## 4. 최종 content 분류

기존 oracle의 snapshot/freshness 정책과 Data Audit을 유지하고, 실행 완료나 HTTP 200을
content 성공으로 승격하지 않는 보수적 판정을 적용했다.

| Category | Count | QA |
|---|---:|---|
| `CONTENT_PASS` | **16** | `MI01, MI03, MI04, DOC04, NEWS01, MP03, MP06, GM02, GM04, GM08, REG03, REG04, ADD15, ADD27, ADD47, ADD48` |
| `AAST_FAILURE` | 21 | `PF02, IX01, MP05, MP07, MP09, NEWS03, CN01, CN08, CN09, GM11, GM14, REG02, REG05, REG06, ADD03, ADD06, ADD18, ADD25, ADD32, ADD45, ADD46` |
| `CAPABILITY_FAILURE` | 12 | `MI02, DOC02, IX02, MP01, MP04, GM01, GM13, ADD01, ADD12, ADD16, ADD38, ADD49` |
| `DATA_BLOCKED` | 8 | `PF01, PF03, CN04, CN05, CN07, GM05, GM12, ADD40` |
| `RENDER_FAILURE` | 0 | - |
| **합계** | **57** |  |

`ADD32`는 unsupported combination이 주 원인이지만, 현재 기록 체계상 AAST/plan
composition failure로 포함했다. `PF03`, `CN04`, `GM05`, `GM12`는 기존 Data Audit의
`BLOCKED_VALID`를 적용했다. `CN05`와 criterion ambiguity는 자동으로 answerable 분모에서
제외하지 않았다.

### 안전성 보조 지표

- `WRONG_CONFIDENT_ANSWER` 의심: `PF01, CN07, ADD40` — forecast 결과가 보였지만
  현재 정책상 DEV_DUMMY forecast를 정답으로 승격하지 않음
- `VALID_ABSTENTION`: `PF02, PF03, CN04, CN05, GM12, MP05` 6건
- `SSE_TERMINAL_FORMAT_PASS`: 57/57
- `FORMAT_PASS`: 업무 의미 형식은 content와 분리하여 미승격

## 5. Accuracy

- Raw Content Accuracy: **16/57 (28.07%)**
- `BLOCKED_VALID`: 4건 (`GM05, PF03, CN04, GM12`)
- Answerable Accuracy: **16/53 (30.19%)**
- 기존 공식 `33/57`: 이번 측정의 분모·oracle 기준으로 유지하되, 현재 결과는 공식 baseline보다 낮음

### 기존 공식 PASS와 비교

기존 공식 33건 중 현재 content fail인 regression은 **20건**이다.

`MP01, MP07, MP09, CN01, CN08, CN09, GM01, GM14, REG02, REG05, REG06, ADD06, ADD12, ADD16, ADD18, ADD25, ADD32, ADD38, ADD40, ADD46`

기존 공식 PASS 집합 밖에서 새로 content pass가 된 QA는 다음 3건이다.

`MP03, GM02, GM08`

따라서 이전 r31의 `18/57`을 baseline으로 사용하지 않으며, 이번 `16/57`도 최신 기능의
개선 점수로 해석하지 않고 현재 고정 이미지의 측정값으로만 기록한다.

## 6. QA별 결과 요약

아래 표는 각 QA의 runner 상태와 최초 관찰 reason을 보존한 요약이다.

| QA | Runner | 분류 | 최초 reason |
|---|---|---|---|
| MI01 | PASS | CONTENT_PASS | document retrieval |
| MI02 | PARTIAL | CAPABILITY_FAILURE | expected marker `원소` 미검출 |
| MI03 | PASS | CONTENT_PASS | document retrieval |
| MI04 | PASS | CONTENT_PASS | document retrieval |
| DOC02 | FAIL | CAPABILITY_FAILURE | `projection_field_unavailable:title` |
| DOC04 | PASS | CONTENT_PASS | navigation/FAQ content |
| NEWS01 | PASS | CONTENT_PASS | document retrieval |
| NEWS03 | PASS | AAST_FAILURE | generic recent-news output으로 중국 수출통제 요구를 보존하지 못함 |
| PF01 | PARTIAL | DATA_BLOCKED | forecast policy/DEV_DUMMY 의심 |
| PF02 | FAIL | AAST_FAILURE | `semantic_plan_incomplete` |
| PF03 | FAIL | DATA_BLOCKED | `comparison_alignment_required`, 기존 blocked-valid |
| IX01 | FAIL | AAST_FAILURE | `semantic_plan_incomplete` |
| IX02 | FAIL | CAPABILITY_FAILURE | composite/index·price upstream failure |
| MP01 | PARTIAL | CAPABILITY_FAILURE | price branch만 반환, import projection 누락 |
| MP03 | PARTIAL | CONTENT_PASS | import rank + current price 내용 확인 |
| MP04 | FAIL | CAPABILITY_FAILURE | production/price upstream failure |
| MP05 | FAIL | AAST_FAILURE | `semantic_plan_incomplete` |
| MP06 | PARTIAL | CONTENT_PASS | use-case + price 내용 확인 |
| MP07 | FAIL | AAST_FAILURE | `semantic_plan_incomplete` |
| MP09 | PARTIAL | AAST_FAILURE | price branch만 반환, document branch 누락 |
| CN01 | FAIL | AAST_FAILURE | `semantic_plan_incomplete` |
| CN04 | FAIL | DATA_BLOCKED | external/forecast blocked-valid |
| CN05 | FAIL | DATA_BLOCKED | criterion/forecast ambiguity |
| CN07 | PARTIAL | DATA_BLOCKED | DEV_DUMMY forecast + news marker 미검출 |
| CN08 | FAIL | AAST_FAILURE | `all_roots_failed` |
| CN09 | FAIL | AAST_FAILURE | `semantic_plan_incomplete` |
| GM01 | PARTIAL | CAPABILITY_FAILURE | comparison right-side import fields 누락 |
| GM02 | PARTIAL | CONTENT_PASS | country intersection 반환 |
| GM04 | PARTIAL | CONTENT_PASS | multi-mineral country composition 반환 |
| GM05 | PARTIAL | DATA_BLOCKED | document/trade source 부족 |
| GM08 | PARTIAL | CONTENT_PASS | use + production country 반환 |
| GM11 | FAIL | AAST_FAILURE | `semantic_plan_incomplete` |
| GM12 | FAIL | DATA_BLOCKED | external forecast blocked-valid |
| GM13 | PARTIAL | CAPABILITY_FAILURE | `price_criterion_mapping_missing` |
| GM14 | FAIL | AAST_FAILURE | `semantic_plan_incomplete` |
| REG02 | FAIL | AAST_FAILURE | `aggregate_order_required` |
| REG03 | PASS | CONTENT_PASS | `price.series` |
| REG04 | PARTIAL | CONTENT_PASS | yearly average result |
| REG05 | FAIL | AAST_FAILURE | `semantic_plan_incomplete` |
| REG06 | FAIL | AAST_FAILURE | compare upstream failure |
| ADD01 | FAIL | CAPABILITY_FAILURE | latest price upstream failure |
| ADD03 | FAIL | AAST_FAILURE | `semantic_plan_incomplete` |
| ADD06 | FAIL | AAST_FAILURE | `semantic_plan_incomplete` |
| ADD12 | FAIL | CAPABILITY_FAILURE | `adapter_unavailable` |
| ADD15 | PARTIAL | CONTENT_PASS | production/reserves tables |
| ADD16 | FAIL | CAPABILITY_FAILURE | `comparison_alignment_required` |
| ADD18 | FAIL | AAST_FAILURE | `semantic_plan_incomplete` |
| ADD25 | FAIL | AAST_FAILURE | `dependency_unavailable` |
| ADD27 | PARTIAL | CONTENT_PASS | price series |
| ADD32 | FAIL | AAST_FAILURE | `unsupported_combination` |
| ADD38 | FAIL | CAPABILITY_FAILURE | `projection_field_unavailable:mineral` |
| ADD40 | PARTIAL | DATA_BLOCKED | DEV_DUMMY forecast policy |
| ADD45 | FAIL | AAST_FAILURE | `semantic_plan_incomplete` |
| ADD46 | FAIL | AAST_FAILURE | `semantic_plan_incomplete` |
| ADD47 | PARTIAL | CONTENT_PASS | FAQ concept |
| ADD48 | PARTIAL | CONTENT_PASS | FAQ concept |
| ADD49 | FAIL | CAPABILITY_FAILURE | `projection_field_unavailable:value` |

## 7. 결론

이번 clean validation은 환경 고정 조건을 통과한 이미지에서 실행됐다. 그러나 content
결과는 `16/57`로, 기존 공식 `33/57`보다 낮다. 이번 단계에서는 그 원인을 더 수정하거나
QA별 repair하지 않았다.

확정된 사실은 다음과 같다.

1. r31의 무효 결과와 달리 이번 실행물은 현재 HEAD source와 image checksum이 일치한다.
2. `GM02`, `MP03`, `GM08`은 현재 clean image에서도 content 후보로 관찰됐다.
3. `MP01`, `GM01`, `ADD16` 등 Fast Regression 회복 후보는 이번 자연어 full replay에서
   다시 실패/부분 결과가 됐다.
4. 따라서 남은 차이는 최신 코드 자체의 공통 semantic/AAST·capability 실패 또는 Gemma
   planning 변동 가능성이 있으며, 이번 1회 replay만으로 `MODEL_NONDETERMINISM`을
   확정할 수는 없다.
5. 기존 공식 PASS regression과 wrong-confident forecast는 별도 지표로 보존했다.

이번 작업의 최종 상태는 **검증 완료, 수정 없음**이다. 18002는 기존 상태로 유지됐다.
