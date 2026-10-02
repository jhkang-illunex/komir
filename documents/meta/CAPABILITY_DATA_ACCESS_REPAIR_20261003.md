# Capability Data Access Repair — 2026-10-03

## 범위

검증 환경 `komir-rag-chat:capability-data-audit-r20`만 수정·검증했다. 컨테이너는
`18012`에 기동했고 `18002`의 `current-session-r19`는 변경하지 않았다.

대상은 실제 원천 행이 확인된 `MP04`, `PF01`, `PF02`다. 질문별 분기, 값 하드코딩,
AAST/Renderer 신규 구조는 추가하지 않았다.

## 최초 원인

### MP04

읽기 전용 DB 확인 결과 `MNRL0002` 생산량의 공식 모집단(`se_cd='-'`)에 2024·2025
행이 존재하고, `WT002` 정규화 톤 단위도 존재한다. 현재 repository의
`fetch_production_yoy`는 다음 결과를 반환한다.

```text
prior_year=2024, prior_tonnes=3710000.0
year=2025, tonnes=3900000.0
change_tonnes=190000.0, change_pct=5.1213...
```

따라서 MP04의 현재 live 실패는 원천 행 소실이 아니라 AAST compare/계획 계약의
실패다. 실제 trace에서 `node_prod_yoy`까지 생성되었지만 `node_compare_results`에
`comparison field` 또는 `left_field/right_field`가 없어 validator가 중단했다.
이번 source/binding 수정으로 AAST를 우회하여 PASS로 판정하지 않았다.

### PF01 / PF02

기존 forecast adapter는 레거시 `KO_MNRL_PRC_PREDC`만 바라보고, 실제 현재 예측
행이 있는 `public.ai_mnrl_prc_frcst`를 사용하지 않았다. 또한 레거시 fallback의
물리 컬럼 키 대소문자가 `RawDataset`의 소문자 컬럼과 맞지 않아 행을 버릴 수 있었다.

## 적용한 공통 수정

- `KomisRawDataRepository`의 `forecast_price`를 `AI_MNRL_PRC_FRCST`의 `BASE`
  시나리오, 기준 serial, target 월로 조회하도록 연결했다.
- 같은 기준의 최신 실측 가격을 `KO_MNRL_PRC`에서 연결하고, 예측 행을
  `forecast_date`, `current_price`, `predicted_price`, `unit`, criterion metadata로
  정규화했다.
- AI 원천이 비어 있거나 실패하면 레거시 원천으로 열화한다.
- evidence adapter가 canonical forecast 행과 소문자 레거시 행을 모두 읽도록
  period/date 및 forecast field 해석을 공통화했다.

## 원천 확인

`MNRL0002`의 실제 AI forecast에서 `BASE` 24개월 행을 확인했다. 첫 행은
`2026-10-01`, criterion `LME CASH` serial `502`, current price `22916.73`,
predicted price `16710.8847`, unit `USD/톤`이다. `MNRL0003`도 같은 adapter로
정규화되는 것을 확인했다.

## 검증 결과

### 단위/통합 테스트

```text
13 passed in 0.44s
```

forecast AI 원천 선택·BASE 월 정규화·레거시 fallback·canonical evidence table을
검증했다.

### 18012 실제 SSE Fast Regression

| QA | 결과 | 관찰 |
|---|---|---|
| PF01 | 실행 완료 | 가격 1행 + `AI_MNRL_PRC_FRCST` 24행, forecast_date/current_price/predicted_price/unit 전달 |
| PF02 | 계획 중단 | `질문을 처리할 실행 계획을 생성하지 못했습니다`; source adapter까지 도달하지 않음 |
| MP04 | 기권 | `dependency_unavailable`; 실제 source는 있으나 AAST compare field 누락이 최초 원인 |
| GM02 | 실행 완료 | resource country result 반환 |
| GM01 | 실행 완료 | production/trade capability 모두 성공, 비교 결과까지 도달 |
| ADD16 | 기권 | 기존 `comparison_alignment_required` |
| MP01 | 부분 완료 | 가격 값은 반환했으나 다른 branch upstream 실패 |
| MP03 | 기권 | `dependency_unavailable` |
| ADD27 | 기권 | `retrieval unavailable: no_data` |
| ADD15 | 실행 완료 | production/reserves 표 2개 반환 |
| GM08 | 실행 완료 | 용도/세계 생산국 표 반환 |
| Direct | 실행 완료 | 니켈 최신값 `23111.69`, source `public.KO_MNRL_PRC` |

PF01은 이 수정으로 source 접근과 typed evidence까지 회복되었다. PF02와 MP04는
이번 수정의 source contract 범위를 넘어 각각 계획/AAST contract에서 중단되므로
CONTENT_PASS로 과장하지 않는다.

## 잠정 판정

- 신규 `PROVISIONAL_CONTENT_PASS`: PF01 1건 후보
- MP04: source access는 정상 확인, live content는 AAST contract blocker로 유지
- PF02: forecast source는 정상 확인, live semantic planning blocker로 유지
- 잠정 Fast Regression: 기존 `35/57`에서 **PF01 회복 후보 포함 최대 `36/57`**
  (공식 full replay 전 잠정치)
- sentinel에서 이번 수정으로 인한 신규 regression은 확인하지 못했다. ADD16,
  ADD27, MP03은 기존 blocker가 재현된 것이며 이번 수정의 회귀로 분류하지 않는다.

## 남은 Data Access / 다음 ROI

남은 두 대상은 데이터 부재가 아니다.

1. MP04 — `resource.yoy` 결과를 compare에 연결할 때 typed comparison field를
   보존하는 AAST/compare contract.
2. PF02 — `trailing historical price + future forecast`를 하나의 유효한 계획으로
   만드는 semantic planning contract.

두 항목은 이번 iteration에서 source adapter를 더 느슨하게 하거나 값을 대체하지
않고 유지했다.

## 후속 bounded repair — r21/r22

`r21`에서는 두 공통 정규화를 적용했다.

- `calculate(yoy)`가 `resource.yoy`로 정규화된 뒤에도 compare 입력의 canonical
  값 필드가 `production_volume`으로 남지 않고 `change_pct`로 추론되도록 했다.
- semantic requirement에 `price_forecast`와 `future_horizon`이 있으면 미래 가격
  retrieve의 누락된 metric을 `price_forecast`로 보완했다. trailing historical
  retrieve에는 적용하지 않았다.

`r22`에서는 forecast TypedResult의 canonical 출력 필드가 `predicted_price`임을
compare contract에 반영했다. 모델이 forecast 쪽을 `value`로 표현한 경우에만
typed output contract에 맞춰 `predicted_price`로 교정한다.

추가 단위 테스트 후 관련 묶음은 `50 passed`였다.

### r22 Fast Regression

- `PF01`: 실행 완료. 현재 가격 1행과 forecast 24행이 전달됨.
- `PF02`: historical 6개월 131행과 forecast 24행 모두 capability 실행까지 도달.
  최종 compare는 `PARTIAL`(24개 처리, 131개 처리 불가)로 남아 CONTENT_PASS 아님.
  잔여 원인은 서로 다른 temporal population을 side-by-side로 표현하는 runtime
  결과 contract이며, 이번 iteration의 bounded repair 횟수를 초과해 수정하지 않았다.
- `MP04`: `resource.yoy` live MCP 결과가 `no_data`로 반환되어 compare에 도달하지
  못함. 컨테이너 내부 repository 직접 호출에서는 2024/2025 행과 YoY 값이
  확인되므로 실제 최초 blocker는 source adapter 자체가 아니라 live MCP 호출
  경계의 결과 전달/출처 정책으로 남겼다.

sentinel 결과: `GM02`, `GM01`, `ADD16`, `ADD15`, `GM08`, Direct는 실행 완료;
`MP01`은 기존 부분 성공, `MP03`/`ADD27`은 기존 blocker가 재현되었다. 이번
contract 수정으로 신규 sentinel regression은 확인되지 않았다.

현재 잠정치는 PF01만 확정 가능한 회복 후보로 추가되어 **최대 36/57**이다.
PF02는 실행 도달은 회복했지만 PARTIAL이고, MP04는 source 전달 blocker이므로
둘 다 CONTENT_PASS로 산정하지 않는다.

## PF02 temporal continuation — r24 (2026-10-03)

### 원인 확인

PF02의 Gemma semantic requirement는 다음 두 독립 branch였다.

- `price_series` / `trailing_months(6)` / 니켈
- `price_forecast` / `future_horizon(1)` / 니켈

사용자 요구에는 compare/difference/same-period 의미가 없는데, 생성된 AAST가
두 branch를 `COMPARE(operation=side_by_side)`로 묶었다. r22까지는 이 때문에
관측 시계열 131행과 forecast 24행을 같은 날짜 키로 정렬하려다 24개만 성공하고
131개가 처리 불가가 되었다.

### 공통 수정

질문 문자열이나 QA ID를 사용하지 않고, typed semantic requirement와 graph
operator만 검사하도록 정규화했다.

- historical trailing series + future forecast가 같은 entity이고
- semantic requirement에 명시적 comparison operation이 없으며
- generic `JOIN` 또는 `COMPARE(side_by_side)` graph인 경우

기존 relation primitive의 `COMPARE(operation=temporal_continuation)`으로 정규화한다.
relation executor는 관측 행을 먼저 날짜순으로 내보내고, 기준일 이후 forecast만
뒤에 붙인다. 관측/forecast `observation_type`과 source/provenance를 보존하며,
단위 또는 entity가 호환되지 않으면 성공으로 보정하지 않는다. 명시적 비교
requirement는 side-by-side/alignment 경로를 유지한다.

변경 파일:

- `inhouse/rag_core/ragkit/live_multihop.py`
- `inhouse/rag_core/ragkit/relational_ops.py`
- 관련 `test_live_multihop.py`, `test_live_relations.py`

### 검증

- 관련 unit/regression: **99 passed**, `git diff --check` 통과
- 검증 이미지: `komir-rag-chat:capability-data-audit-r24`
- 검증 포트: 18012 (`komir-rag-chat-qa-capability-r24`)
- 운영 18002: `komir-rag-chat:current-session-r19` 유지

PF02 실제 SSE:

- HTTP 200, `done.abstained=false`
- 154행: 관측 131행 + 기준일 이후 forecast 23행
- forecast의 기준월 중복 행은 관측값과 중복하지 않도록 제외
- citations: `public.KO_MNRL_PRC`, `public.AI_MNRL_PRC_FRCST`

명시적 temporal comparison sentinel도 실행했으나, 선택한 기존 sentinel들은
각각 기존 `semantic_plan_incomplete` 또는 `dependency_unavailable`에서 중단되어
이번 continuation 정규화가 적용되지 않았다. 이번 변경으로 발생한 새로운 sentinel
회귀는 확인하지 못했으며, 해당 blocker들은 이번 작업 범위 밖이다.

PF02는 이제 side-by-side alignment 실패가 아닌 시간순 continuation으로 실행되지만,
콘텐츠 oracle 재평가 전까지 공식 CONTENT_PASS에는 반영하지 않는다.
