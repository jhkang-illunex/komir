# PLAN_GAP / FLAKY_PLAN 재분류 — 2026-10-03

## 범위

- 대상: 최신 18012 trace와 기존 recovery/AAST trace에서 PLAN_GAP 또는 FLAKY_PLAN으로
  남은 QA
- 코드 수정: 없음
- QA57 Full Replay: 실행하지 않음
- 운영 18002: 변경 없음
- 기준: `Typed Requirement → Semantic Parser output → requested outputs → AAST candidate`

## 결론

PF02에서 확인된 다음 causal contract는 다른 QA에서 반복되지 않았다.

```text
Typed Requirement에 price_forecast output이 필요함
→ Semantic Parser가 price_forecast branch/output을 생성하지 않음
→ requested_output_not_produced:price_forecast
→ AAST 실행 이전 중단
```

현재 증거상 이 패턴은 PF02 단독이다. 다른 `semantic_plan_incomplete` QA들은 AAST가
생성된 뒤 composition, output type, dependency, capability selection 또는 navigation
경계에서 중단되거나, parser 원문 trace가 없어 동일 contract로 확정할 수 없다.

따라서 `requested_output_not_produced` 기반 공통 parser repair cluster는 **2건 미만**이며,
이번 단계에서 PLAN_GAP 공통 repair를 적용하지 않는다.

## QA별 재분류

| QA | Typed Requirement | Parser/plan 관측 | AAST candidate | 최초 divergence | 분류 |
|---|---|---|---|---|---|
| PF02 | `price_series(trailing 6M)` + `price_forecast(future)` | 3회 중 1회 `requested_output_not_produced:price_forecast`; 2회는 두 requirement 보존 | 2회 생성; generic join이 continuation으로 정규화 | 실패 1회는 Semantic Parser output contract | `FLAKY_PLAN`, exact pattern |
| IX01 | indicator/index + price + relation/compare | requirement는 존재; parser output 누락 증거 없음 | AAST 생성 후 indicator/calculation contract 및 final join dependency 실패 | AAST composition/calculation | `PLAN_GAP`, parser omission 아님 |
| CN01 | price extrema/date + document/news branch | 요구 branch가 존재하는 AAST 생성 | 요구되지 않은 `price_change_data`가 추가되고 root에 연결되지 않음 | AAST branch reachability | `PLAN_GAP`, branch overgeneration |
| CN09 | indicator period change + document/news branch | requirements/AAST 생성 | `change_pct` output 보장 없이 filter가 field 요구 | AAST output type/field contract | `PLAN_GAP`, output type mismatch |
| GM14 | price + trade concentration/import share | 두 branch requirement 존재 | concentration output에 없는 `import_share`를 projection이 요구 | AAST output contract/projection binding | `PLAN_GAP`, output type mismatch |
| ADD03 | price series + argmax/date | argmax/root requirement 및 graph 생성 trace | retrieval/criterion/data 단계에서 실패; parser output omission 아님 | capability/data 이후 boundary | `PLAN_GAP` stale/secondary; parser cluster 제외 |
| ADD06 | price + derived YoY/change output | derived requirement 보존 여부가 필요한 복합 plan | 기존 trace는 semantic plan incomplete/derived output 보존 문제로 기록 | derived metric preservation | `PLAN_GAP`, exact requested-output 오류 미확인 |
| ADD32 | unsupported combination | unsupported requirement/capability 조합 | 기존 capability 범위 밖 또는 selection mismatch | capability discovery/selection | `REQUIREMENT_UNSUPPORTED` |
| ADD25 | price compare/dependency | dependency requirement 존재 | upstream result availability/binding 실패 | dependency edge/result binding | `PLAN_GAP`, parser omission 아님 |
| ADD45 | navigation/resource location | Gate/navigation plan incomplete | data AAST가 아니라 navigation route plan에서 중단 | Gate/route planning | `PLAN_GAP`, parser cluster 제외 |
| ADD46 | navigation/resource location | Gate/navigation plan incomplete | navigation plan에서 중단 | Gate/route planning | `PLAN_GAP`, parser cluster 제외 |
| MP03 | trade country rank + current price | 반복 probe에서 branch completeness 변동 | AAST/capability 실행까지 도달; import rank+price 결합이 실행마다 변동 | model/plan branch stability | `FLAKY_PLAN`, requested-output 오류 아님 |
| GM02 | resource rank + trade country rank + intersection | 반복 probe에서 intersection 결과 변동 | 두 branch는 생성되나 downstream intersection/entity set이 변동 | dependency/join plan stability | `FLAKY_PLAN`, requested-output 오류 아님 |

`MP07`, `REG05`는 이전 PLAN/AAST blocker에서 각각 stable recovery/provisional recovery로
분리되어 이번 remaining PLAN_GAP 목록에서 제외했다. `REG02`도 ordered-last contract
복구 후 제외한다.

## PF02 상세 비교

### 정상 2회

```text
Typed Requirements:
  price_series / trailing_months(6) / 니켈
  price_forecast / future_horizon(1) / 니켈

Raw AAST:
  retrieve historical
  retrieve forecast
  join(full, date)

Normalized AAST:
  compare(operation=temporal_continuation,
          left_field=value,
          right_field=predicted_price)
```

두 branch가 root에 연결되고 `temporal_continuation`이 observed 131행과 forecast
23행을 시간순으로 결합했다.

### 실패 1회

```text
Semantic parser
→ requested_output_not_produced:price_forecast
→ semantic_plan_incomplete
→ AAST/capability 미진입
```

이 실패는 기존 temporal operator의 field/date/unit contract가 아니라 parser의
requested output completeness 변동이다.

## 동일 causal contract 판정

### 동일한 `requested_output_not_produced` 패턴

| Causal contract | QA 수 | QA |
|---|---:|---|
| Semantic Parser가 Typed Requirement의 required output/branch를 누락 | 1 | PF02 |

다른 QA에서는 `requested_output_not_produced:price_forecast` 또는 동등한 직접 증거가
확인되지 않았다. `semantic_plan_incomplete`라는 coarse reason만으로 공통 parser bug로
확장하지 않았다.

### 표면상 공통이지만 실제로 다른 패턴

| Coarse 표지 | 실제 최초 원인 | QA |
|---|---|---|
| `semantic_plan_incomplete` | composition/calculation dependency | IX01, CN09 |
| `semantic_plan_incomplete` | branch overgeneration/reachability | CN01 |
| `semantic_plan_incomplete` | output semantic type mismatch | GM14 |
| `semantic_plan_incomplete` | dependency/result binding | ADD25 |
| `semantic_plan_incomplete` | navigation route/Gate | ADD45, ADD46 |
| `semantic_plan_incomplete` | unsupported capability combination | ADD32 |
| `semantic_plan_incomplete` | derived metric preservation | ADD06 |

## 공통 repair 판정

`requested_output_not_produced` cluster는 1건이므로 공통 parser repair의 예상 recovery는
현재 1건(PF02)뿐이다. PF02 자체도 2/3 성공하여 `FLAKY_PLAN`이며, parser가 누락된
output을 질문 원문에서 임의로 다시 생성하는 bounded repair는 이번 단계의 근거가
부족하다.

따라서 다음을 적용하지 않았다.

- parser prompt 수정
- missing output 강제 삽입
- 질문 문자열/QA ID 분기
- 전체 semantic plan 재생성
- AAST validator 완화

판정: **PLAN_GAP 공통 repair 소진**

향후 PF02를 다시 다룬다면 semantic parser의 requested-output completeness를 공통
typed contract로 안정화하는 별도 작업이 필요하다. 단, 다른 QA에서도 동일 오류가 2건
이상 재현된다는 증거가 먼저 필요하다.

## Architecture & Complexity Guard

이번 audit는 분석과 artifact 작성만 수행했다.

### Complexity Delta

```text
Files changed: audit artifact 1개
New classes: 0
New public contracts: 0
New registry entries: 0
New special-case branches: 0
New central-dispatch branches: 0
Removed branches: 0
Duplicated contract sources added: 0
Duplicated contract sources removed: 0
Largest modified method/class/module: 코드 변경 없음
Responsibility growth detected: false
Verdict: COMPLEXITY_PASS
```

기존 semantic parser와 legacy/AAST 경계의 병렬성은 기존 `REFACTOR_CANDIDATE`로
유지하며, 이번 분석에서 확장하지 않았다.

### Contract Delta

```text
New contracts: 없음
Modified contracts: 없음
Removed contracts: 없음
Canonical source of truth: Typed Requirement, Capability Registry, AAST/coverage contract
Consumers: parser output validation, AAST candidate generation, coverage/runtime
Duplicated mappings remaining: 기존 parser/AAST coarse failure reporting 및 legacy mapping
```

## 현재 상태

- 공식 Strict baseline: `17/57`
- provisional Strict: `22/57`
- PF02: `FLAKY_PLAN` (2/3 temporal continuation, 1/3 parser failure)
- 공통 `requested_output_not_produced` cluster: 1건
- 공통 PLAN_GAP repair: 소진 판정
- rag_core/rag_chat 및 18002: 변경 없음
- QA57 Full Replay: 실행하지 않음
