# QA57 Fast/Full 재현성 차이 감사 — 2026-10-03

## 결론 요약

이번 단계에서는 코드, 프롬프트, Validator, 이미지, 운영 `18002`를 수정하지 않았다. 현재 clean image에서 fresh session 반복 실행을 수행한 결과, 차이는 단일 원인으로 설명되지 않는다.

1. Fast의 `35~37/57`은 Full의 `CONTENT_PASS`와 동일한 판정값이 아니다. Fast artifact의 수치는 실행 완료·marker·후보 결과를 포함한 잠정치이고, Full은 branch/값/evidence를 포함한 content oracle을 적용한다. 따라서 두 수치를 직접 비교한 것 자체에 `RUNNER_CONTRACT_DRIFT`가 있다.
2. 동일 clean container에서 fresh session으로 반복해도 일부 QA의 AAST/결과가 달라졌다. `GM02`, `ADD16`, `ADD15`, `GM08`, `MP03`에서 변동을 확인했으므로 `MODEL_NONDETERMINISM` 또는 모델-수리 경로의 비결정성이 실제로 관찰됐다.
3. session history 오염은 확인되지 않았다. 각 요청은 새 UUID session을 사용했고, trace의 `semantic_history`/`context_turns`는 비어 있었다. 다만 AST cache는 프로세스 전역으로 공유되므로 관측 대상이며, 현재 cache key에는 질의·모델·semantic history가 포함된다.
4. 현재 clean Full의 `16/57`을 Fast의 `35~37/57`과 같은 지표로 해석할 수 없다. 18002는 변경하지 않았다.

## 1. 검증 범위와 불변 조건

- 코드 수정: 없음
- prompt/Validator 수정: 없음
- 이미지 재빌드/교체: 없음
- 운영 `18002`: 변경·재시작·배포 없음
- 검증 container: `komir-rag-chat-qa57-fa423`
- image digest: `sha256:0cb927a75830f9453c57b37d198724772a0bce355fb71b49a2cd796dfb0ed803`
- source SHA: `fa423722caeb86bfb83e6561e3b355b20da2ef38`
- Full raw: `/tmp/qa57_full_fa423_20261003.bQRYlc/user_qa_pair_audit_20261003_130928.json`
- 동일 user/payload 반복 raw: `/tmp/qa57_exact_user_repro_20261003.json`

clean Full 환경의 source checksum/image digest 일치는 직전 검증에서 확인되었다. 이번 감사는 그 container를 그대로 사용했다.

## 2. Session isolation 및 공유 상태

### 요청 단위 상태

`inhouse/rag_chat/tests/audit_user_qa_pairs.py`의 `ask()`는 QA마다 `uuid4()`로 새 `session_id`를 생성하고 다음 형태로 POST한다.

```json
{"user_id":"qa-pair-audit","session_id":"<new-uuid>","message":"<question>"}
```

`conversation_id`는 보내지 않는다. 서버는 `session_id`를 기준으로 history를 읽으며, fresh UUID에는 이전 turn/result가 없어야 한다. `history_context.py`의 `ConversationContext`도 session별 turn/result index를 사용한다.

### 재사용되는 상태

| 상태 | 관찰 | 오염 판단 |
|---|---|---|
| session/history/result store | 새 UUID, trace의 `context_turns=0`, `semantic_history=[]` | 교차 QA 오염 증거 없음 |
| AST cache | 모듈 전역 `_AST_CACHE`, 최대 128 | 공유됨. cache key가 `model/question/semantic_history`를 포함 |
| parser cache | 별도 global parser cache 근거 없음 | 미관찰 |
| MCP client/process | 프로세스 전역 client/resource 경로 | 공유됨. session 결과 혼입 증거 없음 |
| session lock | `session_id`별 lock | 서로 다른 QA에는 공유되지 않음 |
| DB/source connection | 컨테이너 프로세스 공유 | 데이터 접근 상태는 공유되나 session history와 별개 |

`live_multihop.py`의 `_ast_cache_key()`는 `model + question + semantic_history`를 정렬 JSON으로 묶는다. fresh session의 빈 history끼리는 동일 질문에 cache hit가 가능하지만, history가 다른 후속 질문의 AST를 그대로 재사용하는 키는 아니다. cache가 전역이라는 사실은 `CACHE_CONTAMINATION` 위험 요인이지만 이번 실험에서 교차 결과 혼입은 관찰하지 못했다.

## 3. Fast Runner와 Full Runner 계약 비교

| 항목 | 현재 Full | Fast artifact/실행 | 감사 판단 |
|---|---|---|---|
| HTTP route | `/pubchat` | `/pubchat` | 동일 경로 확인 |
| session | QA별 fresh UUID | 대부분 fresh UUID | 원칙상 동일 |
| history | 빈 fresh context | fresh 또는 sentinel context | 기록별 확인 필요 |
| concurrency | 순차 | 순차 | 차이 근거 없음 |
| runner retry | 없음 | 없음 | 앱 내부 parser/repair는 별도 |
| timeout | clean Full 240초 | 기록에 180/240 혼재 | 계약 차이 가능 |
| image | `qa57-fa423` clean | 과거 r19 등 별도 image | 동일 image 아님 |
| content oracle | branch/value/evidence 기준 | 실행·marker·후보 중심 | **핵심 차이** |
| 결과 의미 | 공식 Full 측정 | 잠정 Fast candidate | 직접 비교 금지 |

Fast artifact 자체가 `full replay 전 잠정치`, `execution/content 후보`라고 명시한다. 따라서 Fast의 35~37은 Full의 `CONTENT_PASS` 분모에 대응하는 35~37이 아니다. PARTIAL, 한 branch만 반환된 응답, marker가 있는 실행 완료를 Fast 후보로 포함한 기록이 있다. 이 계약 차이가 16과 35~37 사이의 큰 격차를 설명하는 1차 원인이다.

## 4. 동일 clean container fresh-session 반복

대표 8개를 3회씩, 모두 새 session으로 순차 호출했다. 첫 반복 묶음은 fresh `qa57-repro` user, 추가 검증은 Full runner와 같은 `user_id=qa-pair-audit` 및 동일 JSON payload 계약으로 8건을 1회 호출했다.

| QA | 실행 완료/3 | 관찰된 변동 | content 관찰 |
|---|---:|---|---:|
| `GM02` | 3/3 | 2개국 표와 4개국 목록으로 결과 변동 | 보수적 1/3만 교집합 의미에 근접 |
| `GM01` | 3/3 | 동일 partial 비교 결과 | 0/3 완전 충족 |
| `ADD16` | 0/3 | `comparison_alignment_required`와 `calculation_field_unavailable` 교대 | 0/3 |
| `MP01` | 3/3 | 동일 price branch 중심 결과 | import branch 누락, 0/3 완전 충족 |
| `ADD27` | 3/3 | 동일 price series | 3/3 내용 충족 후보 |
| `ADD15` | 3/3 | 두 branch는 유지되나 table/project node shape 변동 | 3/3 내용 충족 후보 |
| `GM08` | 3/3 | 두 branch 유지, projection shape 변동 | 3/3 내용 충족 후보 |
| `MP03` | 3/3 | rank table와 country projection shape 변동 | 핵심 두 결과는 3/3 |

보수적으로 수동 content 판단을 적용하면 24회 중 약 10회가 핵심 content를 충족한다. 이는 runner의 `non-abstain` 비율이 content 정확도가 아님을 다시 보여준다.

### Full과 동일 user/payload 추가 확인

`/tmp/qa57_exact_user_repro_20261003.json`의 결과:

| QA | HTTP | abstained | terminal hash |
|---|---:|---:|---|
| `GM02` | 200 | false | `f85a357453ad` |
| `GM01` | 200 | false | `22f6f186aed8` |
| `ADD16` | 200 | true | `004a6d972017` |
| `MP01` | 200 | false | `af2e945dcf59` |
| `ADD27` | 200 | true | `9a4686e343c3` |
| `ADD15` | 200 | false | `88fbc2dda246` |
| `GM08` | 200 | false | `3ae26b11ef82` |
| `MP03` | 200 | false | `9cf47c167eea` |

동일 user/payload에서도 `ADD16`은 abstain으로 바뀌었고 `ADD27`도 이번 1회는 `semantic_plan_incomplete`가 되었다. 즉 사용자 ID 차이로 설명되지 않는 실행 변동이 확인됐다.

## 5. Sequential contamination 검사

8개를 같은 프로세스에서 순서대로 실행했지만 매번 fresh UUID를 사용했다. 독립 호출과 연속 호출 모두 `semantic_history=[]`/`context_turns=0`인 trace가 확인되며, 이전 QA의 `result_id`, `history:` 또는 `result:` reference가 다음 fresh query로 들어간 증거는 없다.

따라서 현재 증거상:

- `SESSION_STATE_CONTAMINATION`: **0건 관찰**
- `CACHE_CONTAMINATION`: **0건 입증**, 다만 전역 AST cache는 위험 표면으로 기록
- 연속 호출에서 발생한 결과 변동: `MODEL_NONDETERMINISM` 또는 parser/repair 경로 변동으로 분류

이 실험은 별도 process를 매번 재기동한 isolation 검증은 아니므로, 전역 cache나 MCP client 내부 상태가 전혀 없다고 결론내리지는 않는다.

## 6. Full AAST_FAILURE 21건 cluster

clean Full artifact의 21건은 다음과 같이 분류된다.

| 실제 trace signature | 건수 | QA |
|---|---:|---|
| `semantic_plan_incomplete` | 14 | `PF02, IX01, MP05, MP07, CN01, CN09, GM11, GM14, REG05, ADD03, ADD06, ADD18, ADD45, ADD46` |
| dependency/branch coverage | 4 | `MP09, CN08, REG06, ADD25` |
| capability selection/unsupported composition | 1 | `ADD32` |
| retrieval/semantic branch mismatch | 1 | `NEWS03` |
| aggregate contract | 1 | `REG02` |
| **합계** | **21** | |

이 분포는 Full에서 반복되는 공통 AAST/semantic 경로 문제를 나타내지만, 이번 감사에서는 수정하지 않았다. Fast의 일부 성공 후보가 이 21건에 포함되지 않았던 것은 모델 output이 매번 동일하다는 보장이 없고, Fast가 partial/candidate를 content PASS로 세지 않았기 때문이다.

## 7. Model nondeterminism 및 설정

clean container에서 확인한 주요 설정:

- model: `gemma-4-26b-a4b`
- provider: `openai_compat`
- temperature: `0`
- structured output: JSON model contract
- AST max tokens: 1400
- `top_p`, `top_k`, `seed`: 애플리케이션 환경에 명시되지 않음

temperature 0인데도 동일 fresh session에서 결과가 달라졌다. 따라서 원인을 temperature 하나로 단정할 수 없고, vLLM/backend seed 미고정, bounded repair 중 선택 변동, tool/retrieval 응답 순서, 공유 process 상태가 남는다. 확정된 관찰은 `MODEL_NONDETERMINISM` 또는 모델-계획 경로 비결정성이며, 설정은 변경하지 않았다.

## 8. DEV_DUMMY forecast 점검

기존 Data Audit에서 `PF01`, `CN07`, `ADD40`은 forecast 결과가 DEV_DUMMY 또는 정책상 실제 forecast로 승격할 수 없는 source/provenance와 연결된 것으로 기록되어 있다. 이번 감사에서는 source filtering/provenance validation 보강, production DB의 DEV_DUMMY 제거, forecast 값 승격을 수행하지 않았다.

세 QA는 `WRONG_CONFIDENT_SUSPECT`로 유지하며 전체 content PASS 후보에서 제외한다. 이는 16 대 35 격차의 주원인으로 집계하지 않고 별도 안전성 문제로 분리한다.

## 9. 원인별 판정

| 원인 | 판정 | 설명/영향 |
|---|---|---|
| `SESSION_STATE_CONTAMINATION` | 미관찰 | 새 UUID, 빈 history, cross-session reference 없음 |
| `RUNNER_CONTRACT_DRIFT` | **확정** | Fast candidate/marker와 Full content oracle이 다른 지표 |
| `MODEL_NONDETERMINISM` | **관찰됨** | 동일 clean image/fresh session에서도 5개 대표 QA 변동 |
| `AAST_COMMON_REGRESSION` | 현재 결과에 존재 | Full AAST failure 21건; 최근 도입 여부는 이 감사만으로 미확정 |
| `CACHE_CONTAMINATION` | 미입증/위험 요인 | 전역 AST cache 존재, key는 비교적 격리적 |
| `DEV_DATA_CONTAMINATION` | 3건 의심/기록 | `PF01, CN07, ADD40`, forecast provenance 위반 의심 |
| `OTHER` | 역사적 환경 차이 | 과거 Fast r19 image/env snapshot이 Full clean과 완전히 동일하지 않음 |

설명 가능한 영향 수는 중복 가능하다. `RUNNER_CONTRACT_DRIFT`는 Fast 35~37과 Full 16의 지표 차이 전체에 영향을 주며, `MODEL_NONDETERMINISM`은 반복 변동이 관찰된 5개 QA(`GM02, ADD16, ADD15, GM08, MP03`)를 직접 설명한다. AAST 21건은 현재 Full failure 집합이고, DEV_DUMMY는 3건이다. session/cache contamination을 QA 수로 할당할 근거는 없다.

## 10. 최종 판정

**`MIXED`**

- 1차 원인: `RUNNER_CONTRACT_DRIFT` — Fast 잠정 candidate와 Full content oracle의 판정 계약이 다름
- 2차 원인: `MODEL_NONDETERMINISM`/계획 경로 비결정성 — 같은 clean container의 반복에서도 AST/abstain/projection이 달라짐
- 별도 문제: 현재 clean 상태의 AAST 공통 failure 21건 및 DEV_DUMMY forecast 3건
- 현재 근거로는 session state contamination을 주원인으로 볼 수 없음

따라서 clean Full의 `16/57`을 그대로 기능 regression으로, Fast의 `35~37/57`을 정확도 회복으로 각각 확정해서는 안 된다. 다음 측정에서는 동일 image digest, 동일 request contract, 동일 content oracle, seed/structured-generation 설정과 반복 규칙을 함께 고정해야 한다.

## 11. 후속 조치 제안(이번 감사에서는 수행하지 않음)

1. Fast와 Full이 동일한 `user_id/session payload`, timeout, retry, oracle을 쓰도록 runner 계약을 통합한다.
2. 같은 digest에서 대표 QA를 반복하여 AST, repair, capability call, final content를 모두 비교한다.
3. AST cache hit/miss와 cache key hash를 trace에 남긴다. history가 빈 fresh query에 cache hit가 나도 결과를 content PASS로 간주하지 않는다.
4. vLLM seed/top-p/top-k 및 structured decoding 설정을 읽기 전용으로 artifact에 기록한다.
5. DEV_DUMMY provenance는 content oracle 이전에 차단하고 `WRONG_CONFIDENT_SUSPECT`로 별도 집계한다.

이번 단계는 분석과 artifact 작성만 수행했으며, 코드·이미지·운영 서버에는 변경이 없다.
