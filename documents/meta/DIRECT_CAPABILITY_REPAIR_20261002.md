# Direct Capability non-PASS repair — 2026-10-02

## 범위와 실행 이미지

- 기준 audit: `DIRECT_CAPABILITY_NONPASS_AUDIT_20261002.md`
- 구현·검증 포트: `18012`
- 검증 컨테이너: `komir-rag-chat-qa106-direct-r3`
- 이미지: `komir-rag-chat:direct-capability-r3`
- 이미지 digest: `sha256:3793a1fa2dda0052405a34eaf90f10e3f06b8b167e5446b624c9bcbd76ae7aec`
- 운영 18002: `komir-rag-chat:audit-safety22` 유지, 변경하지 않음

## 적용한 공통 수정

Capability boundary에서 원천 표기와 내부 semantic field를 함께 보존하도록
`live_multihop`의 typed row 정규화를 보강했다.

- 국가명/국가코드 변형(`country_name`, `country_nm`, `country_code` 등)을
  canonical `country`/`country_code`로 해석
- 생산량·매장량·재고·가격·날짜·연도·단위의 physical alias를 canonical field로 해석
- 원천 row와 provenance는 삭제하지 않고 canonical field를 추가
- `inventory.latest`와 `indicator.series`의 기존 `FACT_SET`/`TIME_SERIES` contract를 유지

QA ID나 질문 문자열 분기, synthetic fixture 추가, AAST/Renderer 변경은 하지 않았다.

추가 테스트:

- `test_typed_boundary_adds_canonical_country_and_metric_fields`
- `test_typed_boundary_normalizes_inventory_observation_fields`

단위/진단 회귀: **44 passed**, 1 existing pydantic warning.

## 8건 replay 결과

| QA | 수정 전 분류 | r3 결과 | 실제 최초 원인 | 판정 |
|---|---|---|---|---|
| MP03 | CAPABILITY_FAILURE | PARTIAL | `trade.monthly`가 국가 차원 없는 시계열을 반환한 뒤 `country` projection을 요구 | AAST semantic/composition 문제로 재분류 |
| MP04 | CAPABILITY_FAILURE | FAIL | `resource_population_unresolved_category`; 생산 원천에 category 계약이 없어 raw adapter가 fail-closed | 실제 데이터/계약 차단 |
| GM01 | CAPABILITY_FAILURE | FAIL | 생산 branch 동일 `resource_population_unresolved_category`; 후속 compare는 dependency 실패 | capability data contract 차단 |
| GM05 | CAPABILITY_FAILURE | FAIL | 문서·무역 action이 `validation_failed`; 무역 결과까지 도달하지 못함 | retrieval/evidence 계약 문제 |
| GM08 | CAPABILITY_FAILURE | PARTIAL | 문서는 성공했으나 production action이 `validation_failed` | production 원천/계약 차단 |
| GM13 | CAPABILITY_FAILURE | FAIL | price는 `price_criterion_mapping_missing`, production/reserves는 category 계약 거절 | price mapping + data contract |
| ADD16 | CAPABILITY_FAILURE | PARTIAL | 현재 실행은 `resource.rank` production 값으로 응답하거나 parser가 ambiguous; reserves 요청의 metric 보존 실패 | parser/AAST binding 문제 |
| ADD25 | CAPABILITY_FAILURE | PARTIAL | price map 결과가 니켈만 최종 presentation; 구리·코발트 branch identity 보존 실패 | map/AAST composition 문제 |

8건 집계: **PARTIAL 3 / FAIL 5**. 공통 canonical field 수정으로 회복된 QA는
없었다. 이는 수정이 무효라는 뜻이 아니라, 이 8건의 관찰된 실패 대부분이
canonical row field보다 앞선 계획·원천 계약 단계에서 발생했다는 뜻이다.

## 34건 replay

18012에서 기존 non-PASS 34건을 재실행했다.

| 분류 | 기준 audit | r3 |
|---|---:|---:|
| PARTIAL | 17 | 17 |
| FAIL | 16 | 16 |
| BLOCKED_DATA | 1 | 1 |
| 합계 | 34 | 34 |

Capability contract 수정으로 추가 회복된 AAST QA: **0건**.

## Answerable 57 replay

57개 content-oracle 대상의 SSE replay는 다음과 같다. 이 숫자는 기존 harness의
SSE/기대 표지 판정이며, `PARTIAL`을 content PASS로 승격하지 않았다.

| 판정 | 기준 | r3 |
|---|---:|---:|
| PASS | 23 | 23 |
| PARTIAL | 17 | 17 |
| FAIL | 16 | 16 |
| BLOCKED_DATA | 1 | 1 |
| 합계 | 57 | 57 |

Content accuracy: **23/57 (40.35%)**, 기준 대비 순증 **0**.
기존 PASS → FAIL: **0건**.

## 남은 8건의 공통 원인 묶음

1. **AAST/semantic composition**: MP03, ADD25. capability executor에 도달한
   데이터의 차원 또는 entity map 자체가 누락됐다.
2. **원천 data contract fail-closed**: MP04, GM01, GM08. `se_cd` category,
   country/year uniqueness, normalized unit 계약이 충족되지 않아 실제 값이 있어도
   안전하게 실행하지 않았다. 이를 코드에서 우회하면 잘못된 모집단/합계가 된다.
3. **retrieval/evidence 또는 criterion contract**: GM05, GM13. 문서 검증 실패와
   price criterion mapping 누락이 capability 실행 전 발생했다.
4. **metric/parser binding**: ADD16. reserves와 production을 구분하는 semantic
   입력이 live Gemma 계획에서 안정적으로 유지되지 않았다.

따라서 이번 라운드에서 코드로 안전하게 일반화할 수 있었던 것은 canonical
TypedResult field boundary이며, 실제 QA 회복을 만들려면 다음 단계의 AAST/semantic
binding 또는 원천 데이터 계약 결정이 필요하다. 해당 계층은 이번 요청 범위에서
수정하지 않았다.

## 전체 rag_core 회귀

```text
1456 passed
695 subtests passed
1 existing pydantic warning
```

회귀 손상: **0건**.

## 검증 증적

- 8건 raw SSE: `/tmp/capability-r3-8-fixed/user_qa_pair_audit_20261002_163605.json`
- 34건 raw SSE: `/tmp/capability-r3-34/user_qa_pair_audit_20261002_163726.json`
- 57건 raw SSE: `/tmp/capability-r3-57/user_qa_pair_audit_20261002_164100.json`
- 내부 trace는 r3에서 `MULTIHOP_INTERNAL_TRACE=1`로 수집했다.

