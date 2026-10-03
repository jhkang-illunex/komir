# Architecture Cleanup Step 2 — Extremum mechanical extraction

## 판정

**Step 2 acceptance: PASS.** ARG_MAX/ARG_MIN만 기존 등록형 builder/FunctionStep 경로로
이관했다. 알고리즘·semantic policy 변경, QA recovery, Full QA57, Strict 갱신은 없다.
**18002 미변경. Step 3 Sort/Rank는 시작하지 않는다.**

| 검증 | 결과 |
|---|---|
| old/new boundary differential | **797/797 일치** |
| old/new Runtime/composition/SSE differential | **12/12 일치** |
| 실제 candidate container에서 동일 differential | **797 + 12 일치**, host 결과와도 전체 동일 |
| targeted/contract tests | **156 passed**, 3.40s |
| live old/new | **7/7 응답·terminal 일치**, graph/TypedResult exact 6/7 |
| rag_core 전체 | **1589 passed / 0 failed**, 695 subtests, 40.72s |
| rag_chat 동일 scope | **155 passed / 동일 known legacy failure 1**, 15 subtests, 6.41s |

core는 기존 1573개 검증 유지 + 신규 registered Extremum 테스트 16개다.
Certified Product Golden은 `NOT_CERTIFIED_WITH_KNOWN_REASONS` 그대로이며,
known-invalid behavior를 이번 단계에서 개선하거나 PASS로 승격하지 않았다.

## 기준점 / 환경

- 비교 기준은 **Step 1 acceptance 당시 working tree**다. git HEAD
  `979fd3f980bb10af74a218cc6e07bada110e76de`만으로 비교하지 않았다.
- Step1 `live_multihop.py`를 수정 전에 복사하고, 봉인된 Step1 source checksum과 일치 확인.
- old image: `sha256:2403b1a7ba8e607261aaeb286e13445e13fc7e4eccaf2b527b2e5ebf250af571`.
- new tag: `komir-rag-chat:extremum-step2-20261003`.
- new image ID: `sha256:1f09dc8fe7ef32d7760c381d04c52272ff998628c4b28a5d2da7be6ed73f513b`.
- local RepoDigests는 `[]`. 위 SHA는 image ID이며 registry manifest digest라고 부르지 않음.
- new container: `komir-extremum-step2` /
  `0f0eee94f6f5cfe021c98d336d66c65320aa96ee1255aca8537ed12d2e92cd87`.
- 18012만 사용. Env/extra_hosts/network/readonly resource mounts는 Step1과 동일.
- host/container **224 files checksum 일치**, Gemma/MCP 정상 후 live QA 진행.
- revision label은 Golden parent이며 clean Golden 소스라는 의미가 아니다.
  `komir.validation=extremum-step2-working-tree`, build timestamp, source checksums로 식별한다.
- Step1 image/container는 삭제하지 않고 stopped 상태로 보존했다.

## Pre-change 책임 점검

위험도는 승인된 architecture migration으로 CRITICAL 절차를 적용했다.
production 구현 라운드 1회; 신규 검증 graph의 upstream metadata 오류는 harness/test에서만
보정했다. validator나 기존 oracle/fixture를 완화하지 않았다.

| 질문 | 판단 |
|---|---|
| 기존 책임 | `_derive`가 다양한 연산과 Extremum 선택 및 공통 metadata finalization을 함께 소유 |
| 이관 소유자 | `operator_handlers/extremum.py`는 기존 Extremum 선택만 소유 |
| 기존 확장점 | StepFactory / builder registry / StepHandler / FunctionStep / PipeRuntime 재사용 |
| canonical owner | 기존 field resolver, `_numeric`, 공통 row finalization을 그대로 소비 |
| 새 domain/source 개념 | 없음 |
| 중복 의미 정의 | 없음; alias/numeric/entity extraction을 handler에서 재정의하지 않음 |
| QA 특례 | 없음 |
| 중앙 branching | 증가 없이 registry entry 2개 추가 및 legacy branch 1개 제거 |
| 구조 변경 필요성 | 승인된 책임 추출만 수행; 새 hierarchy/scheduler/framework 불필요 |

## 책임 이동

```text
AAST → 기존 PipeLowerer / StepFactory.build
     → registered ARG_MAX / ARG_MIN builder
     → 기존 FunctionStep
     → 옮긴 Extremum 선택 알고리즘
     → 공통 _finalize_derived_rows
     → 기존 TypedResult / PipeRuntime

미이관 연산 → 기존 legacy path
```

- legacy `_derive`의 ARG_MAX/ARG_MIN body 31행을 제거했다.
- legacy routing operator 집합 및 공유 PARTIAL guard 대상에서도 두 operator를 제거했다.
- handler가 기존 순서대로 any-input PARTIAL 검사 → 첫 source 선택 → 기존 row 해석 →
  non-strict field resolution → numeric 우선/ISO date fallback → 기존 tie 처리를 수행한다.
- 선택된 원본 row 객체를 유지하므로 date와 row-level lineage도 그대로 남는다.
- 공통 finalization **11행 본문은 변경 없이** `_finalize_derived_rows`로 이동했다.
  기존 연산과 새 handler 모두 같은 구현을 호출하며 entity normalization을 복제하지 않는다.
- 이 공통 tail에 있던 기존 Projection result-type 처리도 내용은 동일하다.
  Projection/Calculation/Relation의 실행 body 및 의미는 수정하지 않았다.
- node ID/operation/dependency/binding을 그대로 FunctionStep에 전달한다.
  timeout=None, max_retries=0, 기존 cancel/status propagation을 유지한다.

### 의도적으로 보존한 기존 동작

- tie: default first, all/first/error, unsupported policy 및 ambiguous tie 사유 그대로.
- field가 없거나 rows가 없으면 기존처럼 선택/tie 검사를 건너뛰는 동작 유지.
- 후보 없음의 EMPTY는 기존에 전달하던 evidence/source/provenance/upstream ID만 유지한다.
  빠져 있던 metadata를 새로 보완하지 않았다.
- numeric 문자열 및 date 처리, source-first selection, mixed-unit에 대한 기존 처리 유지.
- raw/typed lineage, unit/metric/entity/status/warnings/failure와 known contamination 유지.
- 계산 중 선점 취소/timeout 같은 새로운 runtime 동작을 추가하지 않았다.

## 결정론적 old/new 비교

old factory는 **실제 Step1 source snapshot**을 별도 모듈로 로드했다.
`__file__`은 변경 없는 설치 package의 `common` 위치 탐색에만 연결했고, 실행 code는 frozen
snapshot에서 읽었다. 새 구현을 expected oracle로 복사하거나 대체하지 않았다.

- 797건: 두 operator × tie all/first/error/invalid × 다양한 row shape × 모든 ResultStatus,
  missing input, secondary PARTIAL, MINERAL_SET, field/metric_field, 인접 연산 15건 포함.
- row 조건: 원본 date/lineage, reversed dates, null/zero/negative, 동일 값 tie,
  missing field, invalid numeric/bool, ISO date, basic numeric date, mixed unit,
  list/Mapping/scalar/tuple/empty 등을 포함.
- 인접 실행 비교는 Project/TopK/Filter/Sort/Rank의 공통 finalization을 확인한다.
  Calculate/Relation은 정적 unchanged 확인 + 전체 regression으로 검증했다.
- 12개 graph: ARG_MAX/MIN × 6 ResultStatus에 대해 source → Extremum → Projection 실행.
  모든 TypedResult, runtime event/status/failure, root, presentation, SSE 및 호출 순서/횟수 일치.
- network tripwire를 사용했다. 고정 graph의 source handler 호출은 old/new 각 1회,
  Extremum의 추가 backend 호출은 0회다. 이를 live 전체 backend 호출 수로 확대 해석하지 않는다.
- 같은 differential을 실제 Python 3.12 candidate container에서도 실행했고,
  host Python 3.10 산출물과 전체 일치했다.
- old snapshot 및 new live module/handler SHA256를 differential에 기록했다.

## 영향 live QA / sentinel

저장된 Behavioral Reference V1 QA57 graph에는 ARG_MAX/ARG_MIN 노드가 없었다.
따라서 saved live 성공 표본이 있다고 주장하지 않고, 관련 ADD03를 fresh ×3,
REG02/REG04/GM08/ADD49를 각 1회 **old 및 new 각각** 실행했다. 총 14 requests이며 Full QA57이 아니다.

| 항목 | old/new 결과 |
|---|---|
| ADD03 ×3 | 모두 같은 응답·abstain/terminal, `retrieval unavailable: no_data` → EMPTY 유지 |
| REG02 | graph/TypedResults/응답/terminal 동일; 현재 latest retrieval 경로 |
| REG04 | graph/TypedResults/응답/terminal 동일; Aggregate 60행 평균 그대로 |
| GM08 | graph/TypedResults/응답/terminal 동일 |
| ADD49 | graph/TypedResults/응답/terminal 동일 |

ADD03의 이번 generated graph에는 ARG_MAX가 있지만 upstream EMPTY가 전파된다.
이를 non-empty live Extremum 성공 또는 source absence의 새 확정으로 부르지 않는다.
실제 선택 알고리즘의 non-empty 보존 근거는 deterministic differential과 contract tests다.

### ADD03 첫 old 실행의 ID 차이

첫 old 실행만 node/root/InputRef 이름이 다르다. bijective ID rename 외 graph 내용은 동일하다.
**같은 Step1 image의 old 2·3회부터 new 3회와 graph 및 모든 TypedResults가 정확히 같다.**
따라서 이 차이는 이미 old에서 관찰된 planner-generated ID 변동이며 migration이 추가한
dependency identity 변경이 아니다. 고정 입력의 node/InputRef identity는 differential에서 그대로다.
raw 차이를 숨기지 않으며 graph/TypedResult exact parity는 **6/7**, 응답/terminal은 **7/7**로 기록한다.

## Regression

실행 순서: differential → targeted/contract → 영향 live/sentinel → core 전체 → chat 동일 scope.

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:inhouse:inhouse/rag_chat python3 -m pytest -q -p no:cacheprovider inhouse/rag_core/tests
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:inhouse:inhouse/rag_chat python3 -m pytest -q -p no:cacheprovider inhouse/rag_chat/tests
```

기존 테스트·assertion·oracle는 수정하지 않았고 신규 `test_registered_extremum.py`만 추가했다.
targeted 범위: registered Extremum/Aggregate, extremum lineage, QA500 common contracts,
live multihop, runtime, contract matrix.

known legacy failure는 이전과 정확히 같은
`test_sse_cancellation.py::test_disconnect_stops_real_ast_retry_before_blocking_invocation_returns[legacy_control-False]`
이며 actual call 4 / expected 3을 유지한다. 신규 failure 0.

## Complexity Delta / 필수 before-after

| 지표 | Step1 before | Step2 after |
|---|---:|---:|
| live_multihop.py LOC | 3055 | **3035** |
| LiveOperatorFactory LOC | 623 | **602** |
| `_derive` LOC | 337 | **296** |
| central operator condition 수 | 14 | **13** |
| legacy Extremum 실행 body LOC | 31 | **0** |
| 신규 handler module LOC | 0 | **61** |

LOC는 빈 줄/주석 포함 물리 행수다. 중앙 condition은 class의 AST If test에서
`*.operator`를 참조하는 조건 수로 Step1과 같은 방법을 사용했다.
중앙 legacy routing operator membership은 10→8, PARTIAL guard membership은 6→4다.

- Step2 files changed: **production 2 + 신규 test 1 + 이 artifact 1**.
  기존 Step1 작업과 이전 미추적 문서는 유지했다.
- New classes / public contracts: **0 / 0**.
- New registry entries: **2**, 하나의 기존 의미를 보존하는 Extremum builder 공유.
- New QA/question/entity special cases: **0 / 0 / 0**.
- New central-dispatch branches: **0**; removed legacy branch **1**.
- Duplicated contract sources added/removed: **0 / 0**.
- Largest modified method: **296 LOC**; class **602**, module **3035**.
- Responsibility growth: **없음**. 선택 책임을 handler로 이동; generic/runtime 책임 추가 없음.
- **변경량 COMPLEXITY_PASS**. 기존 큰 module/class와 legacy dispatcher의
  REFACTOR_CANDIDATE/REFACTOR_REQUIRED 부채는 남으며 이 단계에서 확대 정리하지 않는다.

## Contract Delta

- New / modified / removed **semantic contract: 0 / 0 / 0**.
- Extremum 알고리즘 owner만 `_derive` → `operator_handlers.extremum`으로 이동.
- Canonical field/numeric owner는 기존 `_resolve_row_field` / `_numeric` 그대로 주입.
- entity/result metadata finalization owner는 단일 `_finalize_derived_rows`.
- Consumers: 기존 StepFactory / FunctionStep / PipeRuntime.
- 기존 alias/renderer duplication 부채는 untouched. 이번 범위에 추가 mapping/중복 normalization 없음.
- 별도 읽기 전용 audit에서 actionable finding 없음. 새 source fingerprints 지적은 evidence 보강 후 재실행으로 반영.

## 무결성 / Evidence / 종료

- Step1 봉인 evidence **45 files** checksum 모두 유지.
- source checksum상 Step1 대비 app 변경은 `live_multihop.py`, `operator_handlers/extremum.py` 두 파일뿐.
- source DB public/mineral_risk fingerprint before/after:
  `341be4d0d4316a9cd4da90aaaa952f38d931a1e344910ff21bf24d8d18e71954` 동일.
  fresh session 쓰기는 검증 clone의 ai_chatbot에 한정한다.
- 18002 container ID/image/StartedAt/mount unchanged. 운영 재시작·배포·요청 없음.
- private evidence: `/home/nuri/.codex/validation-evidence/extremum-step2-20261003`.
- 49 files manifest SHA256:
  `d2298191c2fe9fc44afe908d61e5666663db4ae22ffc5fc0fe0c5e833acd0170`.
- source snapshots/patch, host/container differential, live raw/session/TypedResults,
  tests/logs, image/checksums, protected identities, independent audit 포함.
  credentials/env secrets는 복사하지 않았다.

현재 18012는 Step2 candidate이며 Step1 container/image는 rollback용으로 보존했다.
commit/push, Full QA57, Strict 갱신, QA repair, **Step3 Sort/Rank는 수행하지 않고 종료한다.**
