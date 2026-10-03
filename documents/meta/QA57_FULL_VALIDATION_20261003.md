# QA57 Full E2E Validation — 2026-10-03

## 1. 범위와 변경 제한

- QA corpus: 기존 `QA57_CONTENT_BASELINE_20261002.md`의 57건
- 실행: 2026-10-03 04:08:05 KST 전후, 각 QA 신규 독립 세션, 1회
- 대상: 검증 포트 `18012`만
- 운영 `18002`: 변경·재시작·배포 없음
- 코드 수정·이미지 재빌드·repair iteration: 없음
- 원본 SSE 증적: `/tmp/qa57_full_validation_20261003.8Y7pNP/user_qa_pair_audit_20261003_040805.json`
- 서버 trace: 18012 컨테이너 로그의 `aast_coverage_trace`, `multihop_action_trace`

이번 문서의 `CONTENT_PASS`는 HTTP 200, `done=true`, non-abstain만으로 판정하지
않았다. 기존 source-backed oracle과 현재 응답의 핵심 entity/metric/period/value/
branch/evidence를 대조했다. forecast 응답은 Data Audit의 정책에 따라 `DEV_DUMMY`
source를 정상 업무 답변의 근거로 인정하지 않았다.

## 2. 검증 환경 고정

| 항목 | 값 / 결과 |
|---|---|
| git commit | `fa423722caeb86bfb83e6561e3b355b20da2ef38` |
| working tree | clean (artifact 작성 전 확인) |
| 18012 container | `komir-rag-chat-qa-inventory-r31`, running |
| 18012 image | `komir-rag-chat:inventory-capability-r31` |
| image ID | `sha256:fa4a4e2d46f9f7041e885d1ecca8213483d7ee43195ad92243696fccc8fa08f0` |
| container started | `2026-10-02T18:03:15.437674819Z` |
| health | `GET /healthz = 200`, replay 전후 동일 |
| Gemma/vLLM | `127.0.0.1:52302/v1/models = 200`, `gemma-4-26b-a4b` |
| DB | 컨테이너 `PG_DSN` 설정 확인, psycopg2 `select 1` 성공 |
| source mounts | 18012의 OKF/PageIndex mount 유지, 컨테이너 교체 없음 |
| 주요 설정 | `RAG_ALLOW_DUMMY=1`, `MCP_CALL_TIMEOUT_SECONDS=180`, `DEBUG` 미설정 |
| 환경 판정 | `VALIDATION_ENVIRONMENT_FAILURE` 없음; replay 진행 가능 |

## 3. 최종 집계

### 3.1 최상위 분류

| Category | Count | 전체 비율 | 실패(39건) 중 |
|---|---:|---:|---:|
| `CONTENT_PASS` | 18 | 31.58% | - |
| `AAST_FAILURE` | 11 | 19.30% | 28.21% |
| `CAPABILITY_FAILURE` | 18 | 31.58% | 46.15% |
| `RENDER_FAILURE` | 0 | 0.00% | 0.00% |
| `DATA_BLOCKED` | 10 | 17.54% | 25.64% |
| 합계 | **57** | **100%** | **100%** |

`AAST_FAILURE`: IX01, MP07, CN01, CN09, GM11, GM14, REG05, ADD06, ADD25,
ADD45, ADD46.

`CAPABILITY_FAILURE`: MI02, DOC02, NEWS03, IX02, MP04, MP09, CN08, GM01,
GM13, REG02, REG06, ADD01, ADD03, ADD12, ADD16, ADD18, ADD38, ADD49.

`DATA_BLOCKED`: PF01, PF02, PF03, MP05, CN04, CN05, CN07, GM05, GM12, ADD40.

### 3.2 실행·정답·안전 상태

| 지표 | 결과 |
|---|---:|
| `EXECUTION_PASS` (non-abstain, terminal 완료) | 28/57 |
| `PARTIAL` (harness 표지) | 20/57 |
| `FAIL` (harness 표지) | 29/57 |
| `VALID_ABSTENTION` | 6건 |
| `WRONG_CONFIDENT_ANSWER` 의심 | 3건 (PF01, CN07, ADD40: forecast 응답에 DEV_DUMMY 정책 적용 시) |
| `SSE_TERMINAL_FORMAT_PASS` | 57/57 |
| `FORMAT_PASS` (업무 의미 형식) | 별도 확정하지 않음; domain content와 분리 |
| `E2E_PASS` | 18/57 |

`VALID_ABSTENTION`은 PF02, PF03, CN04, CN05, GM12, MP05이다. GM05는 응답 안에
`projection_field_unavailable:country`를 노출한 PARTIAL이라 안전한 abstention으로
세지 않았다. forecast가 포함된 non-abstain 응답은 값이 보였다는 이유로 CONTENT_PASS로
승격하지 않았다.

### 3.3 Accuracy

- Raw Content Accuracy: **18/57 (31.58%)**
- Data Audit에서 `BLOCKED_VALID`로 제외한 QA: GM05, PF03, CN04, GM12 (4건)
- Answerable Accuracy: **18/53 (33.96%)**
- `CRITERION_AMBIGUOUS`는 자동으로 분모에서 제외하지 않았다.
- Wrong confident answer: **3건 의심**; forecast source 정책을 적용하면 안전한 DATA_BLOCKED가
  되어야 하나 현재 이미지가 값을 출력했다.

## 4. 오늘 회복 후보의 full replay 결과

QA ID 기준으로 중복 제거하여 판정했다.

| QA | 현재 결과 | 관찰 |
|---|---|---|
| MP03 | `CONTENT_PASS` | 국가 순위와 최신 가격 표가 모두 존재 |
| GM01 | `CAPABILITY_FAILURE` | 생산 branch는 있으나 무역 쪽 값이 비교 결과에 채워지지 않음 |
| GM02 | `CONTENT_PASS` | 생산 상위국과 한국 수입 상위국의 교집합 2개국 반환 |
| ADD16 | `CAPABILITY_FAILURE` | `comparison_alignment_required` |
| PF01 | `DATA_BLOCKED` + wrong-confident 의심 | 가격과 forecast 표는 있으나 forecast는 DEV_DUMMY 정책 대상 |
| PF02 | `VALID_ABSTENTION / DATA_BLOCKED` | `semantic_plan_incomplete` |
| ADD15 | `CONTENT_PASS` | production/reserves 각각 5개국 표·차트 반환 |
| GM08 | `CONTENT_PASS` | 용도와 생산국 표 반환 |
| MP01 | `CONTENT_PASS` | 가격 시계열과 한국 수입국 구성 반환 |
| ADD27 | `CONTENT_PASS` | 가격 시계열 표·차트 반환 |

잠정 후보가 모두 공식 PASS로 유지되지는 않았다. 특히 GM01·ADD16·PF01·PF02는
현재 이미지에서 회복되지 않았다.

## 5. 기존 공식 PASS 회귀

기존 공식 33건 집합(`QA57_ROI_CLUSTER_AUDIT_20261003.md`의 보완집합)과 현재
CONTENT_PASS를 ID로 비교했다.

`PREVIOUS_CONTENT_PASS → CURRENT_FAIL` **18건**:

`MP07, MP09, CN01, CN08, CN09, GM01, GM14, REG02, REG05, REG06, ADD06,
ADD12, ADD16, ADD18, ADD25, ADD38, ADD40, ADD46`

현재 새로 CONTENT_PASS로 관찰된 이전 non-PASS는 **3건**:

`MP03, GM02, GM08`

따라서 이번 replay는 이전 공식 33/57을 유지하거나 개선한 결과가 아니며, 이미지
상태 간 비교 없이 순증가로 보고해서는 안 된다. 현재 측정값은 **18/57**이다.

## 6. QA별 결과

`trace/session`은 서버 로그에서 확보된 경우 기록했다. 기존 audit runner는 요청 UUID를
raw JSON에 저장하지 않아 fast path 일부는 `NOT_PERSISTED`로 표시했다. 해당 QA의
최종 응답 전문·terminal·citations는 위 raw JSON에 보존되어 있다.

| ID | 최상위 | route | flag / 최초 원인 | latency(s) | trace/session |
|---|---|---|---|---:|---|
| MI01 | CONTENT_PASS | DIRECT/MAP | execution pass | 2.33 | fd7438c2… |
| MI02 | CAPABILITY_FAILURE | DIRECT/MAP | partial content/evidence gap | 14.90 | a5cec9ad… |
| MI03 | CONTENT_PASS | DIRECT/MAP | execution pass | 2.93 | a6323efc… |
| MI04 | CONTENT_PASS | DIRECT/MAP | execution pass | 2.35 | 66e7917a… |
| DOC02 | CAPABILITY_FAILURE | AAST | `projection_field_unavailable:title` | 4.65 | not persisted |
| DOC04 | CONTENT_PASS | GATE/FAQ/NAV | execution pass | 0.19 | not persisted |
| NEWS01 | CONTENT_PASS | DIRECT/MAP | execution pass | 3.28 | not persisted |
| NEWS03 | CAPABILITY_FAILURE | DIRECT/MAP | news result not specific to China control | 3.13 | not persisted |
| PF01 | DATA_BLOCKED | AAST | DEV_DUMMY/external forecast policy | 4.94 | 2672fcab… |
| PF02 | DATA_BLOCKED | unresolved | `semantic_plan_incomplete` | 24.20 | 5db084b0… |
| PF03 | DATA_BLOCKED | AAST | `comparison_alignment_required` / no valid common time key | 10.92 | c5a0796d… |
| IX01 | AAST_FAILURE | unresolved | `semantic_plan_incomplete` | 32.13 | 517aaa21… |
| IX02 | CAPABILITY_FAILURE | AAST | upstream project steps failed | 7.66 | 9e1be0ef… |
| MP01 | CONTENT_PASS | AAST+CAP | two branches present | 7.47 | 6555ecaa… |
| MP03 | CONTENT_PASS | AAST+CAP | rank + current price present | 8.44 | e8630403… |
| MP04 | CAPABILITY_FAILURE | AAST | production/Yoy branch missing result | 13.51 | d5344078… |
| MP05 | DATA_BLOCKED | unresolved | plan incomplete; data status not re-confirmed | 21.66 | db304dbe… |
| MP06 | CONTENT_PASS | AAST+CAP | usage + current price | 4.54 | a11434a1… |
| MP07 | AAST_FAILURE | unresolved | `semantic_plan_incomplete` | 11.04 | 18b16b68… |
| MP09 | CAPABILITY_FAILURE | AAST | price output only; monthly evidence branch absent | 9.07 | 546cbe81… |
| CN01 | AAST_FAILURE | AAST | `semantic_plan_incomplete` | 10.93 | 99fc8681… |
| CN04 | DATA_BLOCKED | unresolved | `EXTERNAL_DATA_BLOCKED` | 18.19 | 73ea3440… |
| CN05 | DATA_BLOCKED | unresolved | criterion/forecast policy | 16.76 | f98a3a8b… |
| CN07 | DATA_BLOCKED | AAST | forecast output uses blocked source policy | 5.42 | adf9c731… |
| CN08 | CAPABILITY_FAILURE | AAST | `all_roots_failed` | 5.66 | 2cf9b752… |
| CN09 | AAST_FAILURE | unresolved | `semantic_plan_incomplete` | 22.81 | 6e37c52f… |
| GM01 | CAPABILITY_FAILURE | AAST+CAP | right trade values absent in compare result | 9.85 | d4c2bfba… |
| GM02 | CONTENT_PASS | AAST+CAP | country intersection returned | 10.05 | a8afda60… |
| GM04 | CONTENT_PASS | DIRECT/MAP | five trade branches returned | 15.31 | c1368471… |
| GM05 | DATA_BLOCKED | AAST | `DATA_ABSENT` trade branch; usage branch partial | 6.86 | not persisted |
| GM08 | CONTENT_PASS | AAST+CAP | usage + resource ranking | 6.28 | not persisted |
| GM11 | AAST_FAILURE | unresolved | `semantic_plan_incomplete` | 10.49 | not persisted |
| GM12 | DATA_BLOCKED | unresolved | `EXTERNAL_DATA_BLOCKED` | 37.11 | not persisted |
| GM13 | CAPABILITY_FAILURE | AAST | `price_criterion_mapping_missing` | 6.15 | f79640e9… |
| GM14 | AAST_FAILURE | unresolved | `semantic_plan_incomplete` | 24.86 | 18eb6833… |
| REG02 | CAPABILITY_FAILURE | DIRECT/MAP | `aggregate_order_required` | 5.49 | 8da02940… |
| REG03 | CONTENT_PASS | DIRECT/MAP | latest observed table | 4.52 | 43259084… |
| REG04 | CONTENT_PASS | DIRECT/MAP | yearly average table | 5.04 | ab985794… |
| REG05 | AAST_FAILURE | unresolved | `semantic_plan_incomplete` | 12.05 | b15b4c73… |
| REG06 | CAPABILITY_FAILURE | DIRECT/MAP | upstream price projects failed | 7.00 | ff9938e1… |
| ADD01 | CAPABILITY_FAILURE | DIRECT/MAP | latest price projection failed | 4.58 | bb4e8213… |
| ADD03 | CAPABILITY_FAILURE | AAST | `price_criterion_mapping_missing` | 5.19 | 36c20444… |
| ADD06 | AAST_FAILURE | DIRECT/MAP | `semantic_plan_incomplete` | 12.97 | 9b0c1adf… |
| ADD12 | CAPABILITY_FAILURE | DIRECT/MAP | `adapter_unavailable` | 4.23 | not persisted |
| ADD15 | CONTENT_PASS | AAST | production/reserves 5+5 | 9.45 | 3ae09c57… |
| ADD16 | CAPABILITY_FAILURE | DIRECT/MAP | `comparison_alignment_required` | 7.74 | 37b2e232… |
| ADD18 | CAPABILITY_FAILURE | DIRECT/MAP | `projection_field_unavailable:date` | 10.59 | 1541fa10… |
| ADD25 | AAST_FAILURE | DIRECT/MAP | `dependency_unavailable` | 9.95 | 8872cbef… |
| ADD27 | CONTENT_PASS | DIRECT/MAP | time series table + chart | 4.53 | a2f70236… |
| ADD32 | CONTENT_PASS | AAST | document/news evidence | 9.14 | 1dc455f8… |
| ADD38 | CAPABILITY_FAILURE | unresolved | `projection_field_unavailable:mineral` | 3.73 | 681a81cc… |
| ADD40 | DATA_BLOCKED | AAST | report + forecast; forecast policy block | 6.10 | 3b282716… |
| ADD45 | AAST_FAILURE | GATE/NAV | `semantic_plan_incomplete` | 3.05 | 4a558a1d… |
| ADD46 | AAST_FAILURE | GATE/NAV | `semantic_plan_incomplete` | 3.27 | not persisted |
| ADD47 | CONTENT_PASS | GATE/FAQ/NAV | concept answer | 0.20 | not persisted |
| ADD48 | CONTENT_PASS | GATE/FAQ/NAV | capability answer | 0.20 | not persisted |
| ADD49 | CAPABILITY_FAILURE | DIRECT/MAP | `projection_field_unavailable:value` | 2.36 | 555c0039… |

## 7. 주요 공통 원인

- AAST/planner: `semantic_plan_incomplete` 8건 이상과 unresolved fast path가 여전히
  존재한다. 이번 문서에서는 planner를 수정하지 않았다.
- Capability/projection: price criterion mapping, projection field(`title`, `value`,
  `date`, `mineral`), comparison/alignment, aggregate ordering이 관찰됐다.
- Source/data: forecast source는 현재 표에 반환되지만 Data Audit상 `DEV_DUMMY`이며,
  일반 챗봇의 유효 근거로 사용하지 않았다. GM05는 trade source 행이 없어
  `DATA_ABSENT`이다. PF03은 일별 관측과 월별 forecast의 공통 time key가 없다.
- Renderer-only: 이번 재생에서 렌더러에 도달한 뒤 형식만으로 실패한 건은 확정하지
  못했다. 표·차트가 존재해도 내용 요구 branch가 빠지면 상위 category로 분류했다.

## 8. 성능

- 전체 replay wall time: 약 **449초** (57건 순차 요청 기준; 마지막 응답 시각 기준)
- 평균 latency: **9.25초**
- 중앙값: **7.00초**
- p95: **24.20초**
- timeout: **0건**
- 가장 느린 5건: `GM12 37.11s`, `IX01 32.13s`, `PF02 24.20s`, `GM14 24.86s`,
  `CN09 22.81s`
- route별 세부 latency는 runner가 route를 raw JSON에 저장하지 않아 이 artifact의
  QA별 route 표와 함께만 확인했다.

## 9. 테스트 상태

검증 후 코드 수정 없이 현재 checkout에서 `PYTHONPATH=.:inhouse python3 -m pytest -q
inhouse/rag_core/tests`를 실행했다.

- **1,482 passed / 69 failed / 679 subtests passed / 1 warning**
- 실패는 기존 기록의 `1513 passed / 1 known parser-history failure`와 일치하지 않는
  다수의 local fixture/runtime contract failure로 확인됐다.
- 대표 최초 원인은 `DEPENDENCY_FAILED`, fixture call/row contract 불일치,
  join/compare runtime 결과 불일치다.
- 이 결과를 수정하거나 숨기지 않았으며, 테스트 환경 차이 또는 현재 checkout과
  검증 이미지 간 코드 상태 차이를 다음 작업의 별도 blocker로 남긴다.
- 18012 health는 replay 전후 200, 컨테이너는 계속 running이다.

## 10. 결론 및 다음 우선순위

현재 고정된 18012 상태의 측정값은 **Raw Content Accuracy 18/57 (31.58%)**,
Data Audit의 4개 `BLOCKED_VALID`를 제외한 **Answerable Accuracy 18/53 (33.96%)**다.
기존 공식 33/57 대비 회귀 18건이 확인되었고, 신규 content pass는 MP03·GM02·GM08
3건이다. 이는 이미지/환경 상태 차이를 먼저 확인해야 하며, 이번 단계에서 수정·재배포하지
않는다.

다음 ROI는 코드 수정 전에 다음을 분리하는 것이다.

1. 18012 image와 공식 33/57 산출에 사용한 검증 이미지의 실제 commit/image 차이 확인
2. price criterion/projection contract(`REG02`, `ADD01`, `ADD03`, `ADD18`, `ADD38`, `ADD49`)
3. AAST `semantic_plan_incomplete` cluster
4. trade comparison value binding(`GM01`)과 resource ratio alignment(`ADD16`)
5. `DEV_DUMMY` forecast 출력의 fail-closed 여부

이 문서는 분석·검증 결과만 기록한다. 이 단계에서는 코드·이미지·18002를 변경하지 않았다.
