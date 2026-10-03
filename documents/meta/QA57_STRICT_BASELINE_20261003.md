# QA57 Strict Baseline — 2026-10-03

## 1. 검증 범위와 변경 제한

- 대상: `QA57_CONTENT_BASELINE_20261002.md`의 57건
- 실행: 2026-10-03, 각 QA 신규 session 1회
- 대상 서버: 18012 검증 환경만
- 운영 18002: 변경·재시작·배포 없음
- 이번 단계의 코드·prompt·Capability·Validator·image 변경: 없음
- 원본 실행 결과: `/tmp/qa57_strict_20261003/user_qa_pair_audit_20261003_141600.json`
- 실행 명령:
  `PYTHONPATH=inhouse/rag_chat:inhouse/rag_core:inhouse python3 inhouse/rag_chat/tests/audit_user_qa_pairs.py --base-url http://127.0.0.1:18012 --case-ids <QA57 IDs> --output-dir /tmp/qa57_strict_20261003 --timeout 180`

## 2. Validation identity

| 항목 | 확인 결과 |
|---|---|
| image tag | `komir-rag-chat:history-materialization-r2-20261003` |
| image digest | `sha256:889f6a8c4a8490dcb8b81db0e7bb120bdd2521d19eb39cc5b59803fe853e86e6` |
| container | `komir-rag-chat-qa57-fa423` / `80593abe3e9f` |
| source SHA label | `fa423722c` |
| host HEAD | `fa423722caeb86bfb83e6561e3b355b20da2ef38` |
| image build timestamp | `2026-10-03T14:06:28+0900` (container label; UTC image created `2026-10-03T05:06:28Z`) |
| working tree | dirty; validation 시점의 변경 파일과 image 내부 핵심 source checksum을 별도로 대조 |
| source checksum | host/container 일치: `live_multihop.py`, `semantic_intent.py`, `chat.py` |
| Gemma/vLLM | `http://127.0.0.1:52302/v1/models` HTTP 200; `gemma-4-26b-a4b` |
| DB | PostgreSQL `220.118.147.58:55433/komis_demo`, read-only `select 1` 성공 |
| MCP/source | 18012 health 및 source 호출 경로 정상 |
| resource mounts | OKF/PageIndex read-only mount 존재 |
| health | 18012 `/healthz` HTTP 200 |

image와 source checksum은 일치했지만 checkout 자체는 clean하지 않았다. 이 사실은 baseline의 재현 조건이다. `latest` tag는 사용하지 않았다.

## 3. Strict result

### 3.1 최종 수치

**`STRICT_CONTENT_PASS = 17 / 57 (29.82%)`**

| 지표 | 수치 |
|---|---:|
| CONTENT_PASS | 17 |
| AAST_FAILURE | 12 |
| CAPABILITY_FAILURE | 18 |
| RENDER_FAILURE | 0 |
| DATA_BLOCKED | 10 |
| 합계 | 57 |
| WRONG_CONFIDENT | 3 |
| VALID_ABSTENTION | 6 |
| SSE terminal 완료 | 57/57 |
| timeout | 0 |
| Answerable Accuracy | 17/53 (32.08%) |

`EXECUTION_PASS`/HTTP 200/PARTIAL은 CONTENT_PASS로 승격하지 않았다. `DATA_BLOCKED` 10건은 기존 Data Audit 정책을 재사용했다. 그중 `PF01`, `CN07`, `ADD40`은 DEV_DUMMY 또는 외부 forecast 근거를 정상 업무 답변으로 인정할 수 없어 `WRONG_CONFIDENT_SUSPECT`로 표시했다.

`Answerable Accuracy`의 분모는 기존 Data Audit의 `BLOCKED_VALID` 4건(`GM05`, `PF03`, `CN04`, `GM12`)을 제외한 53건이다. `CRITERION_AMBIGUOUS`는 자동 제외하지 않았다.

### 3.2 Runner 관찰값과 strict 판정

Runner 관찰값은 `PASS 7 / PARTIAL 20 / FAIL 30`이었다. 이는 실행 상태이며 content 정답과 다르다. strict CONTENT_PASS 집합은 다음과 같다.

`MI01, MI03, MI04, DOC04, NEWS01, MP01, MP03, MP06, GM02, GM04, GM08, REG03, REG04, ADD15, ADD27, ADD47, ADD48`

### 3.3 Stability

| 상태 | 수치 | 기준 |
|---|---:|---|
| STABLE_PASS | 5 | 기존 반복 probe에서 3/3 확인: `GM02, MP03, GM08, ADD15, ADD27` |
| FLAKY_PASS | 0 | 이번 strict PASS 중 변동이 확인된 항목 없음 |
| STABILITY_UNPROBED | 12 | 이번 요청은 1회 full replay이므로 별도 3회 probe 미실시 |

STABLE/FLAKY는 CONTENT_PASS와 별도 표지이며, unprobed 12건을 stable로 간주하지 않았다.

## 4. QA별 최종 판정

| QA | Runner | Strict | Route / 최초 원인 |
|---|---|---|---|
| MI01 | PASS | CONTENT_PASS | DIRECT/MAP; concept lookup |
| MI02 | PARTIAL | CAPABILITY_FAILURE | DIRECT/MAP; element-level content/evidence 부족 |
| MI03 | PASS | CONTENT_PASS | DIRECT/MAP; concept lookup |
| MI04 | PASS | CONTENT_PASS | DIRECT/MAP; concept lookup |
| DOC02 | FAIL | CAPABILITY_FAILURE | AAST; `projection_field_unavailable:title` |
| DOC04 | PASS | CONTENT_PASS | FAQ/GATE; board search 안내 |
| NEWS01 | PASS | CONTENT_PASS | DIRECT/MAP; recent news |
| NEWS03 | PASS | CAPABILITY_FAILURE | DIRECT/MAP; China export-control specificity/evidence mismatch |
| PF01 | PARTIAL | DATA_BLOCKED | AAST; DEV_DUMMY/외부 forecast policy |
| PF02 | FAIL | DATA_BLOCKED | unresolved; forecast source/semantic binding blocked |
| PF03 | FAIL | DATA_BLOCKED | AAST; comparable common time key 없음 |
| IX01 | FAIL | AAST_FAILURE | unresolved; `semantic_plan_incomplete` |
| IX02 | FAIL | CAPABILITY_FAILURE | AAST; index/price upstream project 실패 |
| MP01 | PARTIAL | CONTENT_PASS | AAST+CAP; price와 Korea import share 양 branch |
| MP03 | PARTIAL | CONTENT_PASS | AAST+CAP; import rank와 current price |
| MP04 | PARTIAL | CAPABILITY_FAILURE | AAST; production/YoY 결과 projection 실패 |
| MP05 | FAIL | DATA_BLOCKED | unresolved; source/data policy |
| MP06 | PARTIAL | CONTENT_PASS | AAST+CAP; usage와 current price |
| MP07 | FAIL | AAST_FAILURE | unresolved; `semantic_plan_incomplete` |
| MP09 | PARTIAL | CAPABILITY_FAILURE | AAST; monthly evidence branch 누락 |
| CN01 | FAIL | AAST_FAILURE | unresolved; `semantic_plan_incomplete` |
| CN04 | FAIL | DATA_BLOCKED | external forecast |
| CN05 | FAIL | DATA_BLOCKED | criterion/forecast ambiguity |
| CN07 | PARTIAL | DATA_BLOCKED | DEV_DUMMY forecast/evidence policy |
| CN08 | FAIL | CAPABILITY_FAILURE | AAST roots/evidence 결과 실패 |
| CN09 | FAIL | AAST_FAILURE | unresolved; `semantic_plan_incomplete` |
| GM01 | PARTIAL | CAPABILITY_FAILURE | AAST+CAP; compare right trade values 누락 |
| GM02 | PARTIAL | CONTENT_PASS | AAST+CAP; country intersection |
| GM04 | PARTIAL | CONTENT_PASS | DIRECT/MAP; trade country composition |
| GM05 | PARTIAL | DATA_BLOCKED | AAST; active manganese trade source `DATA_ABSENT` |
| GM08 | PARTIAL | CONTENT_PASS | AAST+CAP; usage와 production ranking |
| GM11 | FAIL | AAST_FAILURE | unresolved; `semantic_plan_incomplete` |
| GM12 | FAIL | DATA_BLOCKED | external forecast |
| GM13 | PARTIAL | CAPABILITY_FAILURE | AAST; price criterion mapping |
| GM14 | FAIL | AAST_FAILURE | unresolved; `semantic_plan_incomplete` |
| REG02 | FAIL | CAPABILITY_FAILURE | DIRECT/MAP; aggregate order contract |
| REG03 | PASS | CONTENT_PASS | DIRECT/MAP; latest price |
| REG04 | PARTIAL | CONTENT_PASS | DIRECT/MAP; yearly average |
| REG05 | FAIL | AAST_FAILURE | unresolved; `semantic_plan_incomplete` |
| REG06 | FAIL | CAPABILITY_FAILURE | DIRECT/MAP; upstream price projects |
| ADD01 | FAIL | CAPABILITY_FAILURE | DIRECT/MAP; latest price projection |
| ADD03 | FAIL | CAPABILITY_FAILURE | AAST; price criterion mapping |
| ADD06 | FAIL | AAST_FAILURE | DIRECT/MAP; `semantic_plan_incomplete` |
| ADD12 | FAIL | CAPABILITY_FAILURE | DIRECT/MAP; adapter unavailable |
| ADD15 | PARTIAL | CONTENT_PASS | AAST; production/reserves tables |
| ADD16 | FAIL | CAPABILITY_FAILURE | DIRECT/MAP; comparison alignment |
| ADD18 | FAIL | CAPABILITY_FAILURE | DIRECT/MAP; `projection_field_unavailable:date` |
| ADD25 | FAIL | AAST_FAILURE | DIRECT/MAP; dependency unavailable |
| ADD27 | PARTIAL | CONTENT_PASS | DIRECT/MAP; price series |
| ADD32 | FAIL | AAST_FAILURE | AAST; unsupported combination in this run |
| ADD38 | FAIL | CAPABILITY_FAILURE | unresolved; `projection_field_unavailable:mineral` |
| ADD40 | PARTIAL | DATA_BLOCKED | AAST; Wood Mackenzie/forecast evidence policy |
| ADD45 | FAIL | AAST_FAILURE | GATE/NAV; plan incomplete |
| ADD46 | FAIL | AAST_FAILURE | GATE/NAV; plan incomplete |
| ADD47 | PARTIAL | CONTENT_PASS | FAQ/GATE; concept |
| ADD48 | PARTIAL | CONTENT_PASS | FAQ/GATE; capability help |
| ADD49 | FAIL | CAPABILITY_FAILURE | DIRECT/MAP; `projection_field_unavailable:value` |

기존 runner는 모든 fast path의 `session_id`를 raw JSON에 보존하지 않았다. 따라서 위 표의 trace/session은 컨테이너 로그에서 확인 가능한 AAST 항목만 별도 보존되며, fast path는 `NOT_PERSISTED`다. 이는 QA를 재실행하지 않고 남긴 관측 한계다.

## 5. 과거 기준과 비교

비교 대상은 과거 공식 `33/57`이며, Fast Regression의 35~37 provisional 및 이전 무효 r31의 18/57은 공식 baseline으로 사용하지 않는다.

### 5.1 기존 33 PASS → 현재 FAIL

`MP07, MP09, CN01, CN08, CN09, GM01, GM14, REG02, REG05, REG06, ADD06, ADD12, ADD16, ADD18, ADD25, ADD38, ADD40, ADD46, ADD32`

총 **19건**이다. 기존 artifact에 기록된 18건에 이번 실행의 `ADD32` 실패가 추가됐다.

### 5.2 현재 새로 CONTENT_PASS로 관찰된 기존 non-PASS

`MP03, GM02, GM08` 3건이다.

이 결과는 33 baseline 대비 순증가로 표시하지 않고, QA ID별 변화를 위 목록으로 분리했다. 현재 독립 strict 측정값은 17/57이다.

## 6. History contract 상태

- QA57의 각 요청은 신규 session으로 시작했다.
- semantic history/conversation/previous result를 QA 간 전달하지 않았다.
- 독립 QA에서는 `history_used=false`가 기대 조건이다.
- 이번 QA57에는 dependent follow-up 자체가 포함되지 않았으므로 typed materialization 성공률을 이 표본으로 재측정하지 않았다.
- History Isolation/Typed Materialization 관련 별도 regression은 사전 결과 `96 passed`로 유지됐다.
- materialization 이후 raw history context가 AAST 의미 입력으로 재주입됐다는 증거는 QA57에서 확인하지 못했다.

## 7. 안전 상태와 DATA_BLOCKED

### WRONG_CONFIDENT_SUSPECT (3)

`PF01, CN07, ADD40`: 응답에는 forecast 표가 있었지만 기존 Data Audit상 DEV_DUMMY 또는 검증되지 않은 외부 forecast 근거다. 따라서 strict CONTENT_PASS가 아니며, 잘못된 confident answer 위험으로 기록했다.

### VALID_ABSTENTION (6)

`PF02, PF03, CN04, CN05, GM12, MP05`.

### DATA_BLOCKED (10)

`PF01, PF02, PF03, MP05, CN04, CN05, CN07, GM05, GM12, ADD40`.

`no_data` 문자열만으로 확정하지 않고 기존 Data Audit의 source/period/evidence 판정을 사용했다.

## 8. 성능

| 지표 | 결과 |
|---|---:|
| 총 실행 시간 | 525.73초 (runner 측정 합계) |
| 평균 latency | 9.22초 |
| median | 6.97초 |
| p95 | 25.24초 |
| timeout | 0 |
| Top 5 | GM12 37.09s, IX01 31.04s, GM14 25.24s, PF02 23.68s, MP05 21.59s |

## 9. Regression suite

정식 실행 명령:

```text
PYTHONPATH=.:inhouse:inhouse/rag_chat pytest -q inhouse/rag_core/tests
PYTHONPATH=.:inhouse:inhouse/rag_chat pytest -q inhouse/rag_chat/tests
```

결과:

- `rag_core`: **1486 passed / 69 failed / 679 subtests passed / 1 warning**, 41.66초
- `rag_chat`: **154 passed / 2 failed / 15 subtests passed**, 6.40초
- 실패는 이번 검증에서 수정하지 않았다.
- 대표 실패 signature는 `DEPENDENCY_FAILED`, fixture call/row contract 불일치, join/compare runtime 결과 불일치, retrieval routing의 criterion argument 불일치, SSE legacy cancellation retry count 불일치다.
- 이전 기록과의 수치 비교는 test command/scope가 달라질 수 있으므로 직접 baseline 등가로 해석하지 않는다.

초기 탐색에서 사용한 잘못된 import 경로 명령은 정식 결과에 포함하지 않았다. 정식 명령과 scope는 위에 고정했다.

## 10. 결론

현재 clean image identity와 source checksum이 확인된 18012에서, fresh-session 1회 strict 평가의 실제 기준선은 **17/57 (29.82%)**다. 이는 과거 공식 33/57이나 Fast Regression provisional 수치와 다른 독립 측정값이다. 이번 작업에서는 원인 수정을 하지 않았고, image rebuild 및 18002 배포도 하지 않았다.

다음 ROI 후보는 코드 수정 없이 이 artifact 기준으로는 `AAST_FAILURE`와 `CAPABILITY_FAILURE`의 공통 regression 원인 재현성 감사이며, 특히 기존 PASS→FAIL 19건과 69/2개 테스트 failure의 공통 환경·contract 원인을 먼저 분리해야 한다.
