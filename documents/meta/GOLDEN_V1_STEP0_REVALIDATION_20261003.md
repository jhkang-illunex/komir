# Golden V1 Step 0 재검증 — 2026-10-03

## 1. 결론: NOT_CERTIFIED / STOP_BEFORE_STEP1

Golden commit `979fd3f980bb10af74a218cc6e07bada110e76de`에서 회귀 테스트 수치는 재현됐지만, **clean source/image/config/snapshot 전체의 동일성 및 기존 Strict 21 PASS set 인증은 완료되지 않았다.** Aggregate migration과 Step 1은 시작하지 않았다.

불일치는 두 가지로 분리한다.

1. **VALIDATION_ENVIRONMENT_DRIFT**: 원본 PostgreSQL16.14/vector0.8.2와 복원 검증 DB16.15/vector0.8.7이 다르다. 이 차이는 QA 실행 후 발견했다. 최초 preflight에서 DB 접속/schema는 확인했지만 engine/extension exact-version 검사를 누락했다. 따라서 이번 replay는 인증 가능한 동일 환경 실행이 아니다. 이 누락은 검증 절차의 오류이며 숨기거나 사후 PASS로 처리하지 않는다.
2. **기존 Strict 판정의 provenance/content 검증 공백**: 기존 PASS12건의 실제 TypedResult evidence에 비실제 개발 더미 경고가 있는데 최종 응답에서는 경고가 사라져 있다. REG05는 추가로 원천 DUMMY_LOAD가 확인된다. 기존 PASS20/21의 답변이 그대로이므로 이를 코드 변경에 의한 신규 regression13건으로 부르지 않는다.

이번 작업에서 새 공식 baseline을 선언하지 않는다. 기존 authoritative21/57 및21/53 문서는 수정하지 않았다. 아래 8개는 내용 검토 후 남은 **미인증 PASS 후보**일 뿐, 새로운 Golden Strict가 아니다.

## 2. Acceptance 대조

| Gate | 기대 | 실제 확인 | 판정 |
|---|---|---|---|
| clean source | Golden SHA | 동일 SHA, detached checkout clean | 확인 |
| app source/image | checksum 일치 | 핵심 source/resource221파일, mismatch0 | 확인 |
| config/source runtime | 동일 DB 엔진/확장 포함 | PostgreSQL 및 vector 버전 불일치 | 실패 |
| rag_core |1560/1560|1560 passed,695 subtests,42.15s|재현|
| rag_chat |155 passed+known1|155 passed,known1,15 subtests,6.80s|재현|
| QA57 Strict |21/57 및 기존21 ID 보존|기존21 중13 인증 불가; 잔여 후보8|미인증|
| Answerable |21/53|잔여 후보 기준8/53; 분모53은 과거 비교용 유지|미인증|
| 18002 |미변경|container/image/StartedAt 동일|확인|

후보 비율은 8/57=14.04%, 과거 분모 비교는8/53=15.09%. **공식 score 재산정이나 분모 재정의가 아니다.** 남은8개도 dummy caveat 부재만으로 원천 진위를 인증했다고 주장하지 않는다.

## 3. 고정한 실행 identity와 한계

- Branch: `multihop_work`; HEAD: `979fd3f980bb10af74a218cc6e07bada110e76de`.
- Clean worktree: `/tmp/komir-golden-v1-step0.nPB2FT/source`; 실행 후에도 tracked/untracked 변경 없음.
- App tag: `komir-rag-chat:golden-v1-979fd3f98-step0`.
- 실제 app image ID: `sha256:a4fbcf8ee2f65b9869ef9fbb79d2ab60ea9dbc5fb98978ec0660949a8a3a2f0c`.
- 로컬 build의 RepoDigests는 빈 배열이다. 위 값은 image config ID이며 registry manifest digest로 부르지 않는다. 전체 Docker image archive를 별도 보존했다.
- OCI label SHA는 Golden SHA, build timestamp는 `2026-10-03T10:28:31.545342+00:00`.
- Container: `komir-golden-v1-step0`; `127.0.0.1:18012 → 8002`.
- 기존 검증 container `komir-rag-chat-cn08-r3`는 정지·보존. 새 검증 container는 인증 후보가 아니라 진단용 상태로 남겼다.
- 기존 pinned dependency image에 Golden의 app/common/rag_core/ingest source를 교체한 검증 이미지. requirements checksum 동일. 테스트는 clean checkout의 hostPython3.10.12, app은Python3.12.15; package manifests를 각각 저장했다.
- Gemma endpoint: `http://host.docker.internal:52302/v1`, model `gemma-4-26b-a4b`, client temperature0. vLLM image/command/mount 기록 보존; 공유 model을 재시작하거나 변경하지 않았다. prefix cache가 활성화되어 있어 완전한 server-cache 초기화를 주장하지 않는다.
- MCP: local stdio, clone PG_DSN/MSR_DB 상속. 실제 mineral resolver 요청 성공.
- PG_DSN/MSR_DB만 isolated snapshot clone으로 전환. 비밀값은 보고서/저장소에 남기지 않았다.
- 대표가격 resource SHA256: `46e6fe9a4ae299c9dd62b5867f749fca4f38569668480d0a2ab49503d995ae1c`.
- 원래 /data_lake의 DuckDB 파일1개를 복제하여 read-only mount. 기존 설정에 별도 OKF/PageIndex mount는 없었으며 임의 자료를 추가하지 않았다.
- `RAG_ALLOW_DUMMY=1`은 이전 검증 환경에서 그대로 유지했다. 실행 허용 flag는 Strict에서 개발 데이터를 실제 근거로 PASS 승인하는 권한이 아니다.

### DB snapshot

- pg_dump consistent snapshot: 2026-10-03T10:27:45.358846+00:00 ~10:29:01.654768+00:00.
- dump460,133,562bytes, SHA256 `d16170f23ce3e58d8fbec976b82ea2903d65a387fff9314ce7826f384af37830`.
- DuckDB SHA256 `e05b2421bbcbd5c1c4241b7503516e75006d8c699fad7fa61029f6effe123607`.
- 원본 DB는 읽기만 했다. session/history 쓰기는 clone의 새 UUID에만 발생.
- public/mineral_risk data-only fingerprint: 실행 **도중/이후** 모두 `341be4d0d4316a9cd4da90aaaa952f38d931a1e344910ff21bf24d8d18e71954`. 실행 전 fingerprint라고 소급 주장하지 않는다.
- 원본: PostgreSQL16.14, vector0.8.2, en_US.utf8.
- clone: PostgreSQL16.15, vector0.8.7, en_US.utf8.
- 이 version drift가 특정 QA 오답의 원인이라는 A/B 증거는 없다. 동일성 gate 실패와 내용 결함을 독립적으로 기록한다.
- 과거 authoritative run은 `fa423… + dirty source`의 다른 시점 snapshot이었다. 과거 데이터와 현재 snapshot이 완전히 동일하다는 인증 자료도 없다.

## 4. QA57 실행 방식 / 행동 재현성

- 전체57건 정확히1회, 원문/순서/endpoint/payload 기준 유지.
- fresh UUID57개; 각 QA의 semantic history source/selected turns0, history_used=false.
- 동일 user `qa-pair-audit`, /pubchat, sequential, per-QA timeout240s, 추가 retry0.
- SSE done57/57, response session ID 일치57/57.
- 실행 시간 UTC10:32:54.285915~10:41:02.349119, 총488.063s.
- latency mean8.562s, median5.346s, p95(nearest rank)24.720s.
- 느린5개: GM12 36.934, IX01 31.994, GM14 24.720, PF02 23.947, IX02 22.802초.
- **final answer 문자열 동일53/57**, 기존PASS21 중동일20/21.
- 변화: MI02, IX02, MP04, GM04. 반복 probe를 하지 않아 모델 비결정성/환경/metadata 변경 기여도를 분리 확정하지 않는다.
- runtime marker PASS8/PARTIAL25/FAIL24는 strict oracle과 별개. 후보PASS8과 숫자가 같은 것은 동일 판정이라는 의미가 아니다.
- 과거의 follow-up형 ADD12도 이번 corpus 지시대로 fresh session. reference 미해결을 새로운 history regression으로 간주하지 않는다.

## 5. 기존21 PASS set 재인증

원래 set:

`MI01 MI03 MI04 DOC04 NEWS01 MP01 MP03 MP06 MP07 GM02 GM04 GM08 REG02 REG03 REG04 REG05 ADD15 ADD27 ADD47 ADD48 ADD49`

내용 PASS 후보8:

`MI01 MI03 MI04 DOC04 NEWS01 GM08 ADD47 ADD48`

재인증하지 못한13:

`MP01 MP03 MP06 MP07 GM02 GM04 REG02 REG03 REG04 REG05 ADD15 ADD27 ADD49`

- 위13 중 REG05 제외12: 실제 TypedResult evidence에 “개발용 더미(예시)…실제 값이 아닙니다”가 존재한다.
- REG05: 최종272380/20260908의 원천 행 등록자DUMMY_LOAD, unitWT002. production provenance가 확인되지 않아 별도 suspect.
- REG04: 출력17794.403833333334는20260713~20261002 최근60행 평균. 같은 snapshot의2026년197관측값 평균17389.810355329948과 다르다. 연간 요구가60행으로 축소된 기존 내용 결함.
- GM04: 망간 수입국 대신 용도 문서, 흑연 한국 수입국 대신 세계무역 문서. required branches 불충족.
- MP07: 여러 가격 공란/원시 unit code도 남음.
- 신규 strict recovery로 인증한 QA0. 실패13을 새 구현 회귀나 순점수 감소로 확정하지 않는다.

### Wrong-confident provenance

Typed evidence dummy caveat QA24건 중 실제 최종 수치 응답을 낸20건:

`PF01 MP01 MP03 MP04 MP06 MP07 MP09 CN07 GM01 GM02 GM04 GM13 REG02 REG03 REG04 ADD01 ADD15 ADD27 ADD40 ADD49`

모든 최종 SSE event에서 해당 더미 경고가 표시되지 않았다. REG05까지 포함하면 provenance suspect21건이다. 이는21건 모두의 숫자가 수학적으로 거짓이라고 증명했다는 뜻이 아니라, 비실제/미확인 출처를 구분하지 않은 응답 위험을 뜻한다.

PF03/REG06/ADD16/ADD25는 dummy caveat가 있어도 최종 기권이므로 위20건에 넣지 않았다. PF01/CN07/ADD40은 PASS로 승격하지 않았다.

## 6. QA별 진단 장부

아래는 final answer 및 저장된 typed evidence를 사람이 검토한 진단이다. 환경 동일성 실패로 인증된 새로운 oracle score가 아니며, application oracle/QA fixture는 수정하지 않았다. raw AAST·requirements·results·session·질문 원문은 private evidence에 보존한다.

| QA | 과거21 set | 이번 진단 | 근거/잔여 blocker | latency(s) |
|---|---|---|---|---|
| MI01 | PASS | 내용 PASS 후보 | 질문한 니켈 용도 제공; canonical mineral information과 일치 | 2.173 |
| MI02 | — | 미충족/미인증 | 기본 금속 정체/특성 대신 value-chain 및 품위별 산업 설명; 핵심 basic-information 요구 불충족 | 9.159 |
| MI03 | PASS | 내용 PASS 후보 | Cu/원자번호29/적갈색/전도성 제공; mineral information과 일치 | 2.69 |
| MI04 | PASS | 내용 PASS 후보 | 요구한 망간 광석 종류와 명칭 제공 | 2.119 |
| DOC02 | — | 미충족/미인증 | projection_field_unavailable:title | 2.94 |
| DOC04 | PASS | 내용 PASS 후보 | 월간동향 기간/검색어/검색범위 사용법 제공 | 0.084 |
| NEWS01 | PASS | 내용 PASS 후보 | 동일 snapshot의 최신 자원뉴스 제목/날짜 목록 제공 | 3.131 |
| NEWS03 | — | 미충족/미인증 | 중국 수출통제 요청에 일반 최신 뉴스 반환; 요청 주제 evidence 불충족 | 2.83 |
| PF01 | — | 미충족/미인증 | forecast/price evidence에 명시적 개발 더미 caveat; 응답에서 경고 없이 실제 수치처럼 출력 | 4.43 |
| PF02 | — | 미충족/미인증 | semantic_plan_incomplete; historical/forecast 연속 응답 미생성 | 23.947 |
| PF03 | — | 미충족/미인증 | 최종 비교가 기권; upstream dummy price/forecast도 확인 | 10.409 |
| IX01 | — | 미충족/미인증 | semantic_plan_incomplete | 31.994 |
| IX02 | — | 미충족/미인증 | semantic_plan_incomplete; 이번 run에서 compare 결과 없음 | 22.802 |
| MP01 | PASS | 미충족/미인증 | price 및 trade evidence에 개발 더미 caveat; 값 출력은 있으나 real-data strict 요건 위반 | 6.74 |
| MP03 | PASS | 미충족/미인증 | trade/price evidence에 개발 더미 caveat; current-price branch가 다수 행도 반환 | 7.67 |
| MP04 | — | 미충족/미인증 | production YoY projection_field_unavailable:year로 부분 응답; 가격 evidence도 dummy | 6.358 |
| MP05 | — | 미충족/미인증 | semantic_plan_incomplete | 21.113 |
| MP06 | PASS | 미충족/미인증 | 용도는 존재하나 현재가격 evidence가 개발 더미 | 4.128 |
| MP07 | PASS | 미충족/미인증 | 원천 dev_dummy caveat; 여러 광종 가격 공란/원시 단위 코드 출력 | 3.615 |
| MP09 | — | 미충족/미인증 | 최신 월간동향 요구에 2022/2023 가격 일부 표; price evidence도 dummy | 4.584 |
| CN01 | — | 미충족/미인증 | semantic_plan_incomplete | 11.955 |
| CN04 | — | 미충족/미인증 | semantic_plan_incomplete | 19.816 |
| CN05 | — | 미충족/미인증 | semantic_plan_incomplete | 15.623 |
| CN07 | — | 미충족/미인증 | forecast evidence DEV_DUMMY; 경고 없는 전망 수치 응답 | 5.144 |
| CN08 | — | 미충족/미인증 | all_roots_failed: calculation unit_unavailable, document validation_failed를 typed snapshot에서 별도 확인 | 4.726 |
| CN09 | — | 미충족/미인증 | semantic_plan_incomplete | 21.218 |
| GM01 | — | 미충족/미인증 | production/trade 양쪽 evidence가 개발 더미; 출력 구조와 무관하게 strict 제외 | 9.205 |
| GM02 | PASS | 미충족/미인증 | 집합 교집합은 중국/아르헨티나로 계산되나 production/trade evidence 모두 개발 더미 | 9.375 |
| GM04 | PASS | 미충족/미인증 | trade evidence dummy; 망간 수입국 대신 용도 문서, 흑연은 한국 수입국이 아닌 세계 무역 문서 | 13.921 |
| GM05 | — | 미충족/미인증 | 용도 branch 성공, import branch projection_field_unavailable:country | 6.292 |
| GM08 | PASS | 내용 PASS 후보 | 텅스텐 용도와 국가별 생산량 제공; resource evidence unit=톤, 2025, caveat 없음 | 5.931 |
| GM11 | — | 미충족/미인증 | resource retrieval validation_failed; 문서 표만으로 공급현황 요구 미충족 | 5.346 |
| GM12 | — | 미충족/미인증 | semantic_plan_incomplete | 36.934 |
| GM13 | — | 미충족/미인증 | price/trade evidence 개발 더미; briefing strict 미충족 | 5.6 |
| GM14 | — | 미충족/미인증 | semantic_plan_incomplete | 24.72 |
| REG02 | PASS | 미충족/미인증 | 현재가24310.4/20261002는 evidence 개발 더미 및 source DEV_DUMMY_WAS | 5.021 |
| REG03 | PASS | 미충족/미인증 | 최신가격 evidence 개발 더미; final은 KOMIS 공식 데이터라고 표시 | 3.639 |
| REG04 | PASS | 미충족/미인증 | 연평균17794.403833은 20260713~20261002 최근60행 평균; 원천 연간 범위 누락, dummy 포함 | 4.622 |
| REG05 | PASS | 미충족/미인증 | 272380/20260908 원천 등록자 DUMMY_LOAD, unit WT002; production provenance 미확정 | 3.63 |
| REG06 | — | 미충족/미인증 | upstream step failed: project_nickel, project_tungsten | 6.253 |
| ADD01 | — | 미충족/미인증 | latest 대신60개 series rows, date identity 없음; price evidence dummy | 4.539 |
| ADD03 | — | 미충족/미인증 | semantic_plan_incomplete | 11.807 |
| ADD06 | — | 미충족/미인증 | semantic_plan_incomplete | 13.768 |
| ADD12 | — | 미충족/미인증 | 독립 fresh session의 방금 답변 reference 미해결; 조회 불가 응답 | 3.941 |
| ADD15 | PASS | 미충족/미인증 | 생산/매장량 두 표와 두 차트가 있으나 양쪽 resource evidence 모두 개발 더미 | 8.931 |
| ADD16 | — | 미충족/미인증 | comparison_alignment_required; scalar denominator 요구 미충족 | 7.256 |
| ADD18 | — | 미충족/미인증 | semantic_plan_incomplete | 10.273 |
| ADD25 | — | 미충족/미인증 | dependency_unavailable | 9.762 |
| ADD27 | PASS | 미충족/미인증 | 시계열 보존은 정상이나 source evidence가 개발 더미 | 4.071 |
| ADD32 | — | 미충족/미인증 | 요청하신 데이터를 조회할수 없습니다; 핵심 근거/요약 없음 | 5.219 |
| ADD38 | — | 미충족/미인증 | projection_field_unavailable:mineral; 요구 가격 표 없음 | 3.53 |
| ADD40 | — | 미충족/미인증 | forecast evidence DEV_DUMMY; 문서+forecast strict 제외 | 4.853 |
| ADD45 | — | 미충족/미인증 | semantic_plan_incomplete | 2.906 |
| ADD46 | — | 미충족/미인증 | semantic_plan_incomplete | 2.866 |
| ADD47 | PASS | 내용 PASS 후보 | 핵심광물 정의/중요성과 정의 출처 제공 | 0.084 |
| ADD48 | PASS | 내용 PASS 후보 | 지원 질문 범위와 기간/광종/국가 안내 제공 | 0.077 |
| ADD49 | PASS | 미충족/미인증 | 12087.43 USD/톤 copper row가 DEV_DUMMY_WAS; price evidence도 개발 더미 | 2.238 |

## 7. Regression commands와 결과

Workdir: `/tmp/komir-golden-v1-step0.nPB2FT/source`.

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:inhouse:inhouse/rag_chat python3 -m pytest -q -p no:cacheprovider inhouse/rag_core/tests
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:inhouse:inhouse/rag_chat python3 -m pytest -q -p no:cacheprovider inhouse/rag_chat/tests
```

- core:1560 passed,2warnings,695subtests,42.15s.
- chat:155passed/1failed,2warnings,15subtests,6.80s.
- Known failure: `test_disconnect_stops_real_ast_retry_before_blocking_invocation_returns[legacy_control-False]`; invocation count 실제4/expected3. 기존 known signature와 동일.
- 테스트 범위 축소/skip/fixture 수정 없음. clean checkout에서 pytest cache와 bytecode 생성을 억제했다.
- 회귀 tests 재현 성공은 Strict source/provenance 인증을 대체하지 않는다.

## 8. 증거 보존 / integrity

Private evidence root:

`/home/nuri/.codex/validation-evidence/golden-v1-step0-20261003`

- 108개 evidence 파일,5,046,427,709bytes(별도 manifest 제외).
- Git archive, Docker image archive, DB dump, readonly DuckDB, source checksum, redacted config, model identity, 원본 authoritative artifact와 raw,57개 response, typed history/AAST/result snapshot, regression log, 재현 script를 보존.
- `manifest.json` SHA256:
  `de52ec92d7533698b38a0650df76cacc8cf5933e3d3379269640f3008c82e80b`.
- 파일권한0400 + private root0700, SHA256 content-addressed seal. 관리자 변경을 물리적으로 막는 WORM storage는 아니다.
- source/session data를 포함하므로 저장소에 dump를 추가하지 않는다. 비밀 env파일은 이 bundle에서 제외.
- 초기 `preflight.json`의 PASS를 덮어쓰지 않았고, `postflight_environment_drift.json`과 `certification_decision.md`가 최종 인증실패를 명시.
- `strict_adjudication.json`의 PASS/strict_verified_pass 필드는 수동 진단 후보 집계이며 최종 인증 여부는 certification_decision이 우선한다.

읽기 전용 독립 감사도 기존12개dummy+REG05,53/57동일,REG04/GM04불충족 근거를 재확인했다. 잔여8개를 경고 부재만으로 완전한 production truth로 인증할 수 없다는 불확실성을 포함했다.

## 9. Architecture / Complexity / Contract Delta

iterative-audit의 regression·contract·responsibility·central dispatcher·single source 규칙 적용. 불일치가 확인되어 수정/리팩터링으로 전환하지 않고 종료한다.

### Complexity Delta

- Project files changed: 이 Step0 보고서1개 추가. 기존 미추적 Architecture Plan은 보존.
- Production code files changed:0.
- Validation-only scripts: private evidence에 보존; 제품 import/execution path에 추가하지 않음.
- New classes/public contracts/registry entries:0.
- New QA/question/entity special-case execution branches:0.
- New central-dispatch branches / removed branches:0/0.
- Duplicated production contract sources added/removed:0/0.
- Largest modified product method/class/module LOC:N/A(수정 없음).
- Responsibility growth:false.
- Change verdict: **COMPLEXITY_PASS**(제품 구조 변화 없음).
- 기존 Architecture Audit의 REFACTOR_CANDIDATE/REFACTOR_REQUIRED 부채는 그대로. 이번 PASS가 기존 God Method 등 부채가 없다는 뜻은 아님.

### Contract Delta

- New/modified/removed runtime contracts:0/0/0.
- Canonical source of truth: Golden code의 기존 Registry/TypedResult/evidence 계약, 기존 authoritative oracle 문서.
- Consumers: 이번 read-only validation/adjudication.
- Duplicated mappings remaining: 기존 audit 장부 유지, 신규 alias/mapping 없음.
- 기존 no-DEV-production 원칙을 전체 typed evidence에 적용했으며 QA별 runtime repair나 새 metric mapping을 만들지 않았다.
- Evidence caveat→final output 전달 공백은 발견 사항만 기록, Renderer/Capability/History/Oracle 수정 없음.

## 10. 종료 상태

- Golden V1 immutable behavioral baseline: **미확정**.
- Immutable/tamper-evident **실패 검증 근거 묶음**만 확정.
- Step1/Aggregate migration: 미시작.
- 기능 수정, 재실행, repair iteration, commit/push: 없음.
- 18002: image `sha256:0d3e757a3d04e75e7b60d7e6917df544b31d4a782d5f7722fb8ddcd3652b466a`, container/StartedAt `2026-10-02T19:01:29.944957509Z` 미변경.
- 다음 승인 전 해결할 gate는 (a) DBengine/vector까지 동일한 Step0 환경, (b) 기존21 PASS의 provenance/oracle 정합성이다. 이번에는 어느 것도 코드/정책을 바꿔 해결하지 않았다.
