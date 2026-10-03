# QA57 Authoritative Full Strict Replay — 2026-10-03

## 1. 범위와 판정 원칙

- 대상: `QA57_CONTENT_BASELINE_20261002.md`의 57건
- 대상 환경: 18012 검증 환경만
- 운영 18002: 변경 없음
- 코드/prompt/Capability/Validator 수정: 없음
- Full replay: QA별 fresh session으로 1회
- 최종 채택 run: 컨테이너 재시작 후 실행한 clean run
- Strict 판정: 실행 상태가 아니라 content oracle 기준

초기 실수로 106건 기본 corpus 실행이 시작되었으나 2건 후 중단했다. 이후 18012
컨테이너를 재시작하여 전역 cache를 비우고 정확히 QA57 ID만 다시 실행했다. 아래 수치는
두 번째 clean run만 사용한다.

## 2. Validation identity

| 항목 | 값 |
|---|---|
| image tag | `komir-rag-chat:cn08-period-change-r3` |
| image digest | `sha256:1684d72c47730f556549b7519984b7a0b7ad8a0d3cea9ce9b333218be2401bed` |
| container | `komir-rag-chat-cn08-r3` |
| source SHA | `fa423722caeb86bfb83e6561e3b355b20da2ef38` |
| container restart | `2026-10-03T08:50:47Z` |
| health | `/healthz` HTTP 200 |
| Gemma/vLLM | `gemma-4-26b-a4b`, `/v1/models` HTTP 200 |
| source checksum | 핵심 source host/container 일치 |
| working tree | dirty; 코드 수정 없이 기존 상태 유지 |

## 3. 실행 결과

실행 artifact:

- raw: `/tmp/qa57_authoritative_20261003_clean/user_qa_pair_audit_20261003_175120.json`
- report: `/tmp/qa57_authoritative_20261003_clean/user_qa_pair_audit_20261003_175120.md`

| 실행 상태 | 건수 |
|---|---:|
| PASS | 8 |
| PARTIAL | 26 |
| FAIL | 23 |
| abstained | 23 |

실행 상태는 strict content와 동일하지 않다. 예를 들어 PARTIAL이어도 요구 branch와
값이 모두 있으면 CONTENT_PASS가 될 수 있고, PASS여도 내용이 불완전하면 탈락한다.

## 4. Strict 결과

**`STRICT_CONTENT_PASS = 21 / 57 (36.84%)`**

현재 strict CONTENT_PASS:

`MI01, MI03, MI04, DOC04, NEWS01, MP01, MP03, MP06, MP07, GM02, GM04, GM08, REG02, REG03, REG04, REG05, ADD15, ADD27, ADD47, ADD48, ADD49`

Provisional recovery 5건의 재판정:

| QA | Full Strict 결과 |
|---|---|
| REG05 | 유지: `CONTENT_PASS` |
| MP07 | 유지: `CONTENT_PASS` |
| ADD01 | 불일치: 다수 시계열 행을 반환하고 latest identity/date가 보존되지 않아 `CAPABILITY_GAP` |
| ADD49 | 유지: `CONTENT_PASS` |
| REG02 | 유지: `CONTENT_PASS` |

따라서 provisional `22/57` 중 4건이 이번 clean full strict에서 확인되었고, ADD01은
이번 실행에서 회복을 확정하지 않는다.

## 5. 최신 first-causal failure map

| Category | QA |
|---|---|
| `PLAN_GAP` | IX01, CN01, CN09, GM11, GM14, ADD03, ADD06, ADD18, ADD45, ADD46 |
| `CAPABILITY_GAP` | MI02, DOC02, MP04, GM13, ADD01, ADD38 |
| `COMPOSITION_GAP` | IX02, GM01, REG06, ADD16, ADD25 |
| `SOURCE_ADAPTER_GAP` | ADD12 |
| `EVIDENCE_GAP` | NEWS03, MP09 |
| `DATA_GAP` / `DATA_QUALITY_GAP` | PF01, PF02, PF03, MP05, CN04, CN05, CN07, GM05, GM12, ADD40 |
| `REQUIREMENT_UNSUPPORTED` | ADD32 |

합계는 36건이며, 별도 `RENDER_FAILURE`는 0건이다. `PF01`, `CN07`, `ADD40`은
DEV_DUMMY 또는 검증되지 않은 forecast provenance가 답변에 포함되어
`WRONG_CONFIDENT` 의심 상태를 유지한다.

## 6. Flaky 및 layer recovery 표지

이번 replay는 1회이므로 새로 3회 안정성을 주장하지 않는다. 기존 반복 probe와 이번
결과를 합쳐 다음을 별도 표기한다.

- `FLAKY_PLAN`: PF02 — 과거 3회 중 parser omission 1회, 이번 clean run도 forecast/data 정책으로 strict 불통과
- `FLAKY`: MP03, GM02 — 기존 반복 probe에서 branch/plan 변동 확인
- layer-recovered but non-pass: GM11, IX02, CN08, PF02

이 표지는 `STRICT_CONTENT_PASS`와 합산하지 않는다.

## 7. Answerable Accuracy

기존 Data Audit의 `BLOCKED_VALID` 4건을 제외한 분모 53을 유지했다.

- CONTENT_PASS: `21/57 (36.84%)`
- Answerable Accuracy: `21/53 (39.62%)`
- DATA_BLOCKED: 10
- WRONG_CONFIDENT 의심: 3 (`PF01`, `CN07`, `ADD40`)
- VALID_ABSTENTION: 기존 blocked-valid 정책 기준으로 별도 유지

## 8. 과거 기준과의 비교

| 비교 기준 | 결과 |
|---|---:|
| 이전 공식 Strict | 17/57 |
| 이번 authoritative Strict | 21/57 |
| 회복 | 4건 순증 후보: `REG02, REG05, MP07, ADD49` |
| provisional 22/57와의 차이 | `ADD01` strict 미확정 |

이전 17건 대비 실제 회복으로 확인된 QA는 위 4건이다. Fast/Provisional/Layer-Recovered
표지는 strict PASS로 자동 승격하지 않았다.

## 9. 회귀 및 테스트

코드가 변경되지 않았으므로 regression suite는 상태 확인만 수행했다.

- `rag_core`: **1557 passed / 0 failed**, 695 subtests passed, 1 warning
- `rag_chat`: **155 passed / 1 known legacy failure**, 15 subtests passed
- known failure: legacy SSE cancellation 경로에서 semantic AST retry 호출 수가 기대치와 다름
- 18002: 변경·재시작·배포 없음

## 10. 성능

clean run runner 측정값:

- 총 latency 합계: 501.59초
- 평균: 8.80초
- median: 5.98초
- p95: 24.00초
- timeout: 0
- Top 5: GM12 36.97초, IX01 32.13초, GM14 24.78초, PF02 24.00초, CN09 21.30초

## 11. Architecture & Complexity Guard

이번 iteration은 검증과 artifact 작성만 수행했다.

### Complexity Delta

```text
Files changed: authoritative audit artifact 1개
New classes: 0
New public contracts: 0
New registry entries: 0
New special-case branches: 0
New central-dispatch branches: 0
Removed branches: 0
Duplicated contract sources added: 0
Duplicated contract sources removed: 0
Responsibility growth detected: false
Verdict: COMPLEXITY_PASS
```

### Contract Delta

```text
New contracts: 없음
Modified contracts: 없음
Removed contracts: 없음
Canonical source of truth: 기존 Typed Requirement, Capability Registry, AAST/coverage contract, content oracle
Consumers: QA runner, trace classification, strict content evaluation
Duplicated mappings remaining: 기존 parser/AAST coarse reason과 legacy mapping
```

## 12. 다음 ROI 상위 3개

1. `PLAN_GAP` 재발현 cluster: IX01/CN01/CN09/GM14 — 최신 first-causal trace를 기준으로
   composition/output/branch 원인을 다시 분리한다.
2. `COMPOSITION_GAP`: IX02/GM01/REG06/ADD16/ADD25 — 양쪽 TypedResult와 canonical key가
   모두 존재하는 경우만 공통 join/dependency contract 후보로 검토한다.
3. `CAPABILITY_GAP`: ADD01/DOC02/MP04/GM13/ADD38 — canonical output/projection/source
   boundary를 구분하며 projection을 느슨하게 하지 않는다.

Full replay는 완료했으므로 이번 작업은 여기서 종료한다. 결과가 낮거나 변동하더라도
이번 iteration에서는 코드를 수정하지 않았다.
