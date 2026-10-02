# QA57 ROI cluster audit — 2026-10-03

## 범위와 기준

- 공식 CONTENT_PASS baseline: `33/57 (57.89%)`
- 검증 환경: `18012`, 컨테이너 `komir-rag-chat-qa-resource-r13`, 이미지
  `komir-rag-chat:resource-population-r13`
- 운영 `18002`: `komir-rag-chat:current-session-r19`, 변경 없음
- 전체 57건 live replay: 실행하지 않음
- 기준 artifact: `QA57_CONTENT_BASELINE_20261002.md`,
  `DIRECT_CAPABILITY_NONPASS_AUDIT_20261002.md`,
  `AAST_COMPOSITION_REANALYSIS_20261002.md`,
  `EXECUTION_FAILED_AUDIT_20261002.md`

현재 baseline 33에서 과거 baseline의 회복 항목(DOC04, MP01, ADD27, CN08,
ADD16, GM01)을 제외하여 이번 audit 대상 24건을 산출했다. 원문/trace가 없는
항목을 새로 실행하여 PASS로 만들지 않았고, 기존 trace와 이번 fast probe를
분리했다.

## 24건 재분류

| category | QA |
|---|---|
| `BLOCKED_DATA` / `EXTERNAL_DATA_BLOCKED` | PF01, PF02, PF03, MP05, CN04, CN05, CN07, GM12 |
| `SOURCE_OR_EVIDENCE_BLOCKED` | DOC02, NEWS03, IX02, GM05, GM08, GM11, GM13 |
| `AAST_COMPOSITION_FAILURE` | IX01, MP04, GM02, ADD03 |
| `CAPABILITY_PROJECTION` | MP03 |
| `RENDERER_FORMAT_FAILURE` | MI02, ADD45 |
| `DIRECT_CRITERION_OR_ESCALATION` | ADD01, ADD49 |
| 합계 | **24** |

세부 근거는 다음과 같다.

- PF01/PF02/CN04/CN05/CN07/GM12는 forecast 원천 또는 가격기준/문서
  evidence가 없거나 검증되지 않아 코드로 회복할 수 없다. PF03은 forecast
  결과의 공통 날짜가 없어 `no_comparable_rows`가 발생한다.
- DOC02/NEWS03/IX02/GM05/GM08/GM11/GM13은 문서·지표·원천 evidence의
  부재, 잘못된 문서 evidence, 또는 가격기준 mapping 부재가 최초 원인이다.
- IX01/MP04/GM02/ADD03은 각각 semantic operation 선택, resource source,
  entity/metric 보존, extremum/date escalation 문제다.
- MP03은 과거 `projection_field_unavailable:country` trace와 달리 현재
  실행에서는 `trade.country_rank`와 `price.series`가 모두 성공하고,
  country/share 및 최신 price 표가 생성됐다.
- MI02/ADD45는 실행 내용은 있으나 format/oracle 표지 차이다.
- ADD01/ADD49는 direct capability가 실행되었지만 DB의 광종→가격기준
  mapping이 비어 `price_criterion_mapping_missing`으로 끝난다. 대표 기준
  registry만으로 serial을 추측하지 않았다.

## ROI cluster 판정

현재 trace를 기준으로 2건 이상을 회복할 수 있고 architecture freeze 안에서
안전하게 수정 가능한 deterministic cluster는 이번 차수에 확인되지 않았다.

| 후보 | 대상 | 판정 | 사유 |
|---|---|---|---|
| trade projection/canonical alias | MP03, GM05, GM13 | 보류 | MP03은 현재 성공했지만 GM05는 `country` 필드 누락이 아니라 문서 이미지가 trade call의 evidence로 잘못 선택됐고, GM13은 price criterion mapping 부재다. 하나의 alias 수정으로 해결되지 않는다. |
| price criterion default | ADD01, ADD49, CN05, CN07, GM13 | `SOURCE_BLOCKED` | 실제 `ai_prc_mnrl_map` serial이 없으므로 대표 기준 YAML만으로 조회 대상을 만들 수 없다. 임의 serial/정답을 추가하면 provenance 계약 위반이다. |
| forecast metric/period | PF01, PF02, PF03, CN04, CN05, CN07, GM12 | `EXTERNAL_DATA_BLOCKED` | forecast capability/data가 현재 검증 환경에 없으며, PF03은 추가로 날짜 교집합도 없다. |
| branch/AAST | IX01, MP04, GM02, ADD03 | 후순위 | semantic planning, resource source, entity binding, direct escalation이 섞여 있어 단일 deterministic contract로 2건 이상 회복된다는 근거가 없다. |
| renderer labels | MI02, ADD45 | 제외 | content가 아닌 format/oracle 문제이며 이번 목표인 answer coverage와 분리한다. |

## Fast probes와 sentinel

이번 환경의 기존 sentinel trace와 이번 probe를 연결해 확인했다.

- Direct: `오늘 니켈 가격 얼마야?` — 완료, price citation 1개
- Navigation: `리튬 가격 화면으로 가줘` — page recommendation 완료
- AAST: `니켈 가격 추이랑 우리나라 수입국 구성 같이 보여줘` — 완료,
  price/trade branches 및 citations 확인
- Validator: `세계 리튬 매장량 중 칠레 비중은?` — 완료, resource citation 확인
- Resource: `희토류 생산량과 매장량 상위국을 알려줘` — 완료, 두 branch 확인
- Document: `이번 달 전략광종 월간동향에 나온 광종들 가격 어때?` — 문서
  mineral list와 price branch 완료
- MP01 sentinel: price series + Korea import composition — 완료
- ADD27 sentinel: `니켈 가격 추이 좀 보여줘` — price series 결과 완료

추가로 18012에서 `니켈 수입 상위국이랑 현재가격 알려줘`를 fresh session으로
실행했다. `trade.country_rank` 5행과 `price.series` 최신값 1행이 모두 최종
SSE 표에 존재해 MP03은 **PROVISIONAL_CONTENT_PASS 후보 1건**으로 기록한다.
이는 이번 차수의 공통 수정 회복이 아니므로 baseline 33을 변경하지 않는다.

`망간 용도랑 주요 수입국 알려줘`는 용도 문서는 성공했으나 trade projection의
입력 evidence가 국가행이 아닌 문서 이미지 표로 판정되어
`projection_field_unavailable:country`가 남았다. `코발트 현황 브리핑해줘`는
trade/resource/document branch가 실행됐지만 price는
`price_criterion_mapping_missing`으로 실패했다. 두 결과는 하나의 alias
수정으로 합칠 수 없다.

## 회귀와 다음 처리 판단

- 소스 수정: 없음
- 이미지 재빌드/18012 교체: 없음
- 18002 변경: 없음
- 기존 unit regression: 이전 fast 기준 `203 passed`; 이번에는 artifact와
  trace만 추가했고 실행 경로를 변경하지 않았다.
- sentinel regression: 관찰된 0건
- 신규 `PROVISIONAL_CONTENT_PASS`: MP03 1건(공통 수정 없음)
- 공식 baseline: `33/57 (57.89%)` 유지
- 잠정 후보: `34/57 (59.65%)`로 별도 기록 가능하나 full replay 전 공식 점수로
  승격하지 않는다.

다음 ROI 후보는 source contract가 보강된 뒤의 trade/document evidence 재검증이다.
현재 상태에서 그것을 코드 alias나 fixture로 대체하면 질문별 성공을 만들게 되므로
이번 차수에는 수정하지 않았다. 40/57 조건에 도달하지 않았으므로 full 57 replay도
실행하지 않았다.

## AAST composition r14 fast validation (2026-10-03)

### 적용한 공통 수정

1. `resource production → presentation project → calculate(yoy)` 그래프도 기존
   `resource.yoy` capability 경계로 정규화했다. 중간 projection은 발표용 구조로만
   취급하고, 원천 retrieve와 downstream root를 보존한다.
2. Coverage violation이 `ENTITY_PRESERVATION_FAILED`이고 typed trade requirement에
   `scope`가 있는 경우, 단일 bounded repair에서 그 scope만 matching trade retrieve에
   복원한다. `reporter_country`/`partner_country`를 추측하거나 다른 graph를 다시
   생성하지 않는다.

관련 unit/regression: `99 passed`, `compileall` 및 `git diff --check` 통과.

### 실제 18012 live 결과

새 이미지 `komir-rag-chat:aast-composition-r14`를 검증 포트 18012에만 기동했다.
운영 `komir-rag-chat-18002`는 `current-session-r19` 그대로 유지했다.

| QA | AAST 이후 최초 blocker | 판정 |
|---|---|---|
| IX01 | `indicator_output_contract_invalid` → index calculation unsupported → `final_minerals_join` dependency failure | `SOURCE/EVIDENCE 또는 calculation contract` — AAST는 실행됨 |
| MP04 | price branch 성공, `resource` branch가 `retrieval unavailable: no_data` | `TRUE_DATA_ABSENCE/EXTERNAL_DATA_BLOCKED` — AAST는 실행됨 |
| GM02 | scope bounded repair 성공; 두 rank 결과 실행 후 `join: missing_join_key` | `JOIN_ALIGN/PROJECTION` — AAST는 실행됨 |
| ADD03 | `arg_max` graph와 period 보존 정상; 아연 retrieval `no_data` | `TRUE_DATA_ABSENCE` — AAST는 실행됨 |

즉 4건 모두 이번 수정 후 AAST 단계에서 더 이상 `semantic_plan_incomplete`로
종료되지 않았으며 Capability/관계 연산 단계까지 진입했다. 그러나 실제
`CONTENT_PASS` 회복은 0건이다. MP04와 ADD03은 데이터 부재이고, IX01은
indicator/calculation evidence contract, GM02는 실제 join key materialization
문제이므로 하나의 추가 AAST 수정으로 묶지 않았다.

### Sentinel 결과

같은 r14 이미지에서 MP01, ADD27, ADD15, GM08, Direct는 완료되었다. ADD16은
`ratio_fields_required`, GM01은 `comparison_field_required`, Navigation은
LLM semantic classification이 `menu/navigate`를 `UNKNOWN_CAPABILITY`로 반환해
실패했다. 이 세 항목은 이번 AAST 수정으로 새로 발생한 것으로 단정하지 않고,
기존 sentinel baseline과의 재현 비교가 필요한 별도 Gate/calculation/compare
cluster로 남긴다. 따라서 이번 iteration의 sentinel regression은 **확정할 수 없음**이며
공식 점수는 갱신하지 않는다.

- 신규 `PROVISIONAL_CONTENT_PASS`: 0건
- 공식 baseline: `33/57`
- 잠정 baseline: `34/57` (기존 MP03만 유지)
- 18002 변경: 없음
