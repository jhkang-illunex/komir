# QA57 non-PASS causal audit — direct-capability-r1

- 이미지: `komir-rag-chat:direct-capability-r1`
- 검증 포트: `18012` (운영 `18002` 미변경)
- 대상: non-PASS 34건 (`PARTIAL` 17, `FAIL` 16, `BLOCKED_DATA` 1)
- 범위: 분석 및 artifact 작성만 수행. 코드/이미지/런타임 설정은 변경하지 않음.

## 방법과 증거 수준

기존 audit JSON의 `answer/actions/sources/terminal`과 18012 컨테이너의 `query_gate`, `direct_capability`, `multihop_shadow_compare` 로그를 대조했다. `semantic_plan_incomplete`, `all_roots_failed`는 coarse summary로 취급하고 `steps[*].failure`를 최초 원인으로 우선했다.

기존 JSON에는 session ID가 없어서 시간순 query_gate와 결과 순서를 결합했다. 따라서 직접 pipe trace가 있는 건은 `HIGH`, 응답/action과 로그를 결합한 건은 `MEDIUM`, 응답 중심 판단은 `LOW`로 표시했다. 다음 실행부터는 QA ID와 session ID를 함께 저장해야 한다.

## Category accounting

root cause는 한 QA에 하나만 부여했다.

| category | count |
|---|---:|
| CAPABILITY_FAILURE | 8 |
| AAST_COMPOSITION_FAILURE | 17 |
| RENDERER_FORMAT_FAILURE | 5 |
| BLOCKED_DATA | 4 |
| **TOTAL** | **34** |

Execution path accounting: `DIRECT 12`, `MAP 1`, `AAST 21` (합계 34). Direct/Map non-PASS는 13건이다. 일부는 renderer/평가 표지 문제이고, 일부는 direct candidate가 복합 요구를 완결하지 못한 사례다.

## QA별 분석

| QA | 상태 | path | capability/branch | 최초 causal failure | category | 공통 수정 | trace |
|---|---|---|---|---|---|---|---|
| MI02 | PARTIAL | DIRECT | document.retrieve | 금속 특성 답변은 있으나 원소/특성 표지가 output에 없음 | RENDERER_FORMAT_FAILURE | 있음 | MEDIUM |
| DOC04 | PARTIAL | DIRECT | navigation/FAQ | 두 월간동향 게시판은 반환되나 질문/기대 표지와 presentation 불일치 | RENDERER_FORMAT_FAILURE | 있음 | MEDIUM |
| PF01 | PARTIAL | AAST | price + forecast | price 성공, forecast 결과 없음 | BLOCKED_DATA | 외부 전망 data | MEDIUM |
| PF02 | PARTIAL | AAST | price series + forecast | 6개월 price 성공, forecast 결과 없음 | BLOCKED_DATA | 외부 전망 data | MEDIUM |
| PF03 | FAIL | AAST | price + forecast → compare | 두 입력은 성공했으나 `no_comparable_rows` | AAST_COMPOSITION_FAILURE | temporal compare | HIGH |
| IX01 | FAIL | AAST | indicator + correlated mineral | compare 필수 field가 semantic plan에서 누락 | AAST_COMPOSITION_FAILURE | Compare contract | MEDIUM |
| IX02 | FAIL | AAST | price + indicator → compare | `comparison_field_required` | AAST_COMPOSITION_FAILURE | typed compare field | HIGH |
| MP01 | PARTIAL | AAST | price + import composition | price branch만 남고 import branch 누락 | AAST_COMPOSITION_FAILURE | root/branch coverage | MEDIUM |
| MP03 | PARTIAL | AAST | trade.country_rank + price | `projection_field_unavailable:country`; price는 성공 | CAPABILITY_FAILURE | trade output schema | HIGH |
| MP04 | FAIL | AAST | price + production → join | 최초 `resource_population_unresolved_category`; join/projection 연쇄 실패 | CAPABILITY_FAILURE | resource binding | HIGH |
| MP05 | BLOCKED_DATA | AAST | production rank + price | `source_unavailable`; 전체 질문을 검증할 원천 없음 | BLOCKED_DATA | source/data | HIGH |
| MP06 | PARTIAL | AAST | usage document + price | 니켈 요청에 Iron Ore 문서가 선택됨 | AAST_COMPOSITION_FAILURE | document/entity binding | HIGH |
| MP09 | PARTIAL | AAST | price + monthly document | price 성공, monthly document branch 누락 | AAST_COMPOSITION_FAILURE | root/branch coverage | MEDIUM |
| CN04 | PARTIAL | MAP | trade.country_rank + forecast | import branch 반환, forecast branch 없음 | BLOCKED_DATA | 외부 전망 data | MEDIUM |
| CN05 | FAIL | DIRECT | price.overview candidate | 복합 요구가 단일 price overview로 축약 | AAST_COMPOSITION_FAILURE | direct completeness | MEDIUM |
| CN07 | FAIL | AAST | price + news | news retrieval `validation_failed` | AAST_COMPOSITION_FAILURE | document/evidence branch | MEDIUM |
| CN08 | FAIL | DIRECT | price.series candidate | index 변동+monthly summary를 price 단일 capability로 축약 | AAST_COMPOSITION_FAILURE | direct completeness | MEDIUM |
| CN09 | PARTIAL | DIRECT | indicator.series | indicator 수치 성공, 뉴스 branch 없음 | AAST_COMPOSITION_FAILURE | document branch preservation | MEDIUM |
| GM01 | FAIL | AAST | production + Korea import | resource population/dependency unresolved | CAPABILITY_FAILURE | population binding | HIGH |
| GM02 | FAIL | AAST | production/import top-k → join | production unresolved, join `dependency_unavailable` | AAST_COMPOSITION_FAILURE | dependency propagation | HIGH |
| GM05 | PARTIAL | AAST | usage document + trade rank | usage 성공, trade `validation_failed`, country projection dependency failed | CAPABILITY_FAILURE | trade output/evidence | HIGH |
| GM08 | PARTIAL | AAST | usage document + world production | document 일부만 반환, production branch 미완료 | CAPABILITY_FAILURE | production binding | MEDIUM |
| GM11 | FAIL | AAST | multi-source graphite briefing | retrieval/evidence/category로 roots 전체 실패 | AAST_COMPOSITION_FAILURE | multi-branch planning | MEDIUM |
| GM12 | FAIL | MAP | 5 minerals price + forecast | `semantic_plan_incomplete`; map이 복합 requirement를 표현하지 못함 | AAST_COMPOSITION_FAILURE | map/composite boundary | HIGH |
| GM13 | FAIL | AAST | usage document + import countries | trade `validation_failed` → country projection/rank dependency failed | CAPABILITY_FAILURE | trade result schema | HIGH |
| ADD01 | FAIL | DIRECT | price candidate | lithium 대표 기준/범위 unresolved 후 ambiguous 종료 | AAST_COMPOSITION_FAILURE | criterion escalation | HIGH |
| ADD03 | FAIL | DIRECT | price candidate | 2010년 이후 최고가+날짜를 direct가 완결하지 못함 | AAST_COMPOSITION_FAILURE | extremum/date binding | HIGH |
| ADD06 | PARTIAL | DIRECT | price.series | `+61.54% 변동`은 있으나 기대 output명/표지 `변화율`이 없음 | RENDERER_FORMAT_FAILURE | derived output label | MEDIUM |
| ADD15 | FAIL | AAST | production + reserves top-5 | 두 root retrieval validation 실패, 이후 모든 step upstream empty | AAST_COMPOSITION_FAILURE | dual-root contract | MEDIUM |
| ADD16 | PARTIAL | DIRECT | resource.rank | reserves share 요청이 칠레 production 값으로 반환 | CAPABILITY_FAILURE | metric/field binding | HIGH |
| ADD25 | PARTIAL | MAP | price.series | 3개 entity 중 니켈만 표시, 구리/코발트 결과 누락 | CAPABILITY_FAILURE | map identity/partial aggregation | HIGH |
| ADD47 | PARTIAL | DIRECT | FAQ/document | 핵심광물 정의/중요성은 답했으나 `중요` 표지 불일치 | RENDERER_FORMAT_FAILURE | concept output contract | LOW |
| ADD48 | PARTIAL | DIRECT | FAQ/document | 지원 범주는 답했으나 `질문` 표지 불일치 | RENDERER_FORMAT_FAILURE | help output contract | LOW |
| ADD49 | FAIL | DIRECT | price candidate | 구리 대표 기준/시점 unresolved 후 ambiguous 종료 | AAST_COMPOSITION_FAILURE | criterion policy/escalation | HIGH |

## PARTIAL 17 공통 원인

| pattern | count | QA |
|---|---:|---|
| 정상 branch는 성공했지만 다른 requested branch가 누락 | 5 | MP01, MP09, CN04, CN09, GM08 |
| structured output/projection contract 불일치 | 3 | MP03, GM05, GM13 |
| document/entity binding 오류 | 1 | MP06 |
| direct/map 결과의 entity·metric identity 손실 | 2 | ADD16, ADD25 |
| 외부 전망/자료 dependency 부재 | 3 | PF01, PF02, CN04 |
| 내용은 있으나 표지/표현 contract 불일치 | 5 | MI02, DOC04, ADD06, ADD47, ADD48 |

※ 일부 QA는 둘 이상의 현상(예: branch 누락과 외부 data 부재)을 보이지만, category accounting에서는 최초 causal failure 하나만 계산했다.

## 공통 수정 우선순위

1. **Capability output/projection schema 통합**: MP03, GM05, GM13 및 유사 trade/country 질문. `country`, `share`, `import_value`, provenance를 typed output에 보존.
2. **Composite branch coverage validator**: MP01, MP09, CN09, GM08, CN05, CN07, GM12. requested output/root와 실제 실행 root를 비교해 누락을 `INCOMPLETE`로 유지.
3. **Metric/period/entity binding 보존**: MP04, GM01, GM02, ADD16, ADD25, ADD03. reserves/production, entity별 key, extremum date를 lowering 전부터 보존.
4. **Document topic/entity binding**: MP06, CN07, GM08. retrieval 성공만으로 통과시키지 않고 entity/topic과 evidence 일치 검증.
5. **Direct reduction completeness**: CN05, CN08, ADD01, ADD03, ADD49. 한 capability가 모든 requested output을 충족하지 못하면 AAST escalation.
6. **Temporal compare/join contract**: PF03, IX02, MP04. 날짜/as-of 호환성과 `no_comparable_rows`/`comparison_field_required`를 보존.
7. **Renderer contract 정렬**: MI02, DOC04, ADD06, ADD47, ADD48. 내용상 성공과 format/marker 실패를 분리.

## 결론

`all_roots_failed`는 parser 실패 단일 원인이 아니다. 실제 trace에서 `price_criterion_mapping_missing`, `resource_population_unresolved_category`, `projection_field_unavailable`, `retrieval unavailable: validation_failed`, `comparison_field_required`, `no_comparable_rows`가 পৃথ도로 확인된다. 이번 단계에서는 코드 수정·fixture 추가·이미지 재빌드·18012 재시작을 하지 않았다.

현재 content baseline `23/57`은 변경하지 않았고, PARTIAL을 PASS로 승격하지 않았다. 다음 audit 실행에서는 JSON에 `session_id`, `gate_route`, `direct_candidate`, `selected_capability`, `pipe_id`, `root_failure`, `step_failures`를 저장해야 causal attribution을 자동화할 수 있다.
