# AAST composition non-PASS 재분석 — 2026-10-02

## 범위

- 기준: `DIRECT_CAPABILITY_REPAIR_20261002.md`
- 대상: 기존 `AAST_COMPOSITION_FAILURE` 17건
- 검증 환경: `18012`, `komir-rag-chat:direct-capability-r3`
- 운영 `18002`: 변경 없음
- 이번 단계: 코드·프롬프트·fixture 수정 없음
- 실제 replay: 17건, `FAIL 12 / PARTIAL 5`

분류는 `all_roots_failed`, `dependency_unavailable` 같은 종합 상태가 아니라
parser/AST 생성 → ActionPlan/capability call → runtime relation의 최초 원인을
우선했다.

## Category accounting

| category | 건수 |
|---|---:|
| ARGUMENT_PRESERVATION | 1 |
| BRANCH_COVERAGE | 1 |
| DEPENDENCY_BINDING | 1 |
| JOIN_ALIGN | 1 |
| CAPABILITY_SELECTION | 5 |
| SOURCE_DATA_RETRIEVAL *(추가 공통 category)* | 6 |
| RENDERER_FORMAT_FAILURE *(추가 공통 category)* | 1 |
| PLAN_GENERATION_GAP *(추가 공통 category)* | 1 |
| **합계** | **17** |

`SOURCE_DATA_RETRIEVAL`, `RENDERER_FORMAT_FAILURE`, `PLAN_GENERATION_GAP`은
질문별 분기가 아니라 기존 AAST failure에서 실제 원인이 아닌 항목을 분리하기 위한
공통 진단 category다.

## QA별 분석

| QA | Semantic requirement | 실제 AAST/ActionPlan 및 call | 최초 손실/실패 stage | category | 공통 수정 가능성 |
|---|---|---|---|---|---|
| PF03 | 니켈 현재 가격과 전망 비교; 동일 기준시점·비교값 | `price.series(nickel)` + `price.series(nickel, topic=forecast)` → `compare(value,value, join_key=date)` | 두 call은 성공했으나 relation executor에서 공통 date가 없어 `no_comparable_rows` | JOIN_ALIGN | 있음. date/as-of alignment contract |
| IX01 | 광물지수 상승과 함께 오른 광종; 지수·광종별 변화 비교 | `price.series(광물지수)` + `document.retrieve(광종 목록)` → `for_each(price_change)` → compare | 지수 요구가 `price.series`/`광물지수`로 physical capability에 잘못 매핑되고, 광종 변화 branch도 문서 목록 의존으로 구성됨 | CAPABILITY_SELECTION | 있음. indicator capability와 price-change capability의 semantic binding |
| IX02 | 니켈 가격 추세와 광물종합지수 추세를 날짜 기준 비교 | `price.series(nickel)` + `indicator.series(mineral_index)` → `compare(join_key=date)` | AST의 entity/metric/date key는 보존됐으나 indicator call이 `no_data`; 이후 compare dependency 실패 | SOURCE_DATA_RETRIEVAL | 코드 우회 불가. indicator source/coverage 확인 필요 |
| MP01 | 니켈 가격 추이 + 한국 수입국 구성 | `price.series(nickel)` + `document.retrieve(topic=질문 전체)` | 수입국 구성 requirement가 `trade.country_rank`가 아니라 document retrieval로 변환됨 | CAPABILITY_SELECTION | 있음. metric/dimension → capability registry mapping |
| MP06 | 니켈 용도 + 현재 가격 | `document.retrieve(mineral=nickel, topic=use)` + `price.series(latest)` | 두 root와 두 call은 모두 성공. 응답 표지/렌더링 판정만 PARTIAL | RENDERER_FORMAT_FAILURE | AAST 수정 대상 아님 |
| MP09 | 니켈 가격 추이 + 최근 월간동향 내용 | Action trace에는 price series 2개만 존재; AAST roots도 `price_ts`, `price_recent`뿐 | 월간동향 document branch가 AST 생성 시 누락 | BRANCH_COVERAGE | 있음. requested branch 대조 validator로 선차단 가능 |
| CN05 | 리튬 주요 수입국 + 가격 전망 | 무역 rank/top5/project + 가격 + forecast/project call 생성 | branch는 모두 생성됐으나 price/forecast mapping이 `price_criterion_mapping_missing`, country projection도 source schema와 불일치 | SOURCE_DATA_RETRIEVAL | mapping/source contract 문제; AAST 조합 자체는 보존 |
| CN07 | 리튬 가격 전망 + 관련 뉴스 | `price.series(lithium)` + `document.retrieve(lithium price outlook news)` | 뉴스 branch는 성공했으나 price call이 `price_criterion_mapping_missing` | SOURCE_DATA_RETRIEVAL | mapping/data contract 문제 |
| CN08 | 지난달 광물종합지수 변동 + 월간동향 요약 | `indicator.series(trailing_months=1)` + `document.retrieve(monthly_trends)` | indicator는 `no_data`, document는 `validation_failed`; AST branch는 모두 존재 | SOURCE_DATA_RETRIEVAL | source/evidence coverage 문제 |
| CN09 | 지수 하락 주의 주요 뉴스 | production/import graph가 아닌 lithium 생산·수입 top/join graph로 생성됨 | 질문 metric/topic과 AST operation이 불일치; 요구한 index/news branch가 보존되지 않음 | CAPABILITY_SELECTION | 있음. requirement-to-plan operation contract |
| GM02 | 리튬 세계 생산 상위국 ∩ 한국 수입 상위국 | 실제 call은 `resource.rank(graphite, production)` + `resource.rank(graphite, reserves)`; rank/join/filter 없음 | entity가 lithium에서 graphite로 바뀌고, 요청된 두 모집단 교집합 graph가 사라짐 | ARGUMENT_PRESERVATION | 있음. entity/metric/operation coverage validator |
| GM11 | 흑연 공급 현황 종합 | 이 replay에서 semantic parser/AAST trace가 남지 않고 종합 실패만 반환 | ActionPlan 생성 전후 원본 trace 부재로 최초 stage 확정 불가; 실행 가능한 trace가 없는 진단 gap | PLAN_GENERATION_GAP | 있음. 실패 시 raw parser/plan trace 보존 필요 |
| GM12 | 2차전지 5종 가격 + 전망 | document → ForEach(price) 및 document → ForEach(price_change) → join(mineral) | 두 ForEach와 projection은 생성됐지만 두 입력이 PARTIAL이라 join validator가 `partial_row_status_required`로 중단 | DEPENDENCY_BINDING | 있음. partial typed result의 join 입력 contract |
| ADD01 | 리튬 최신 가격 | AAST 미진입. direct candidate가 ambiguous로 종료 | 가격 기준/대표 기준 미확정 상태가 direct/plan boundary에서 종료 | CAPABILITY_SELECTION | 있음. 대표 price criterion 정책/계약 필요 |
| ADD03 | 아연 2010년 이후 최고가와 날짜 | AAST 미진입. direct candidate가 ambiguous로 종료 | 기간 + extremum + date output을 direct capability가 완결하지 못하고 AAST escalation도 발생하지 않음 | CAPABILITY_SELECTION | 있음. direct completeness와 AAST escalation contract |
| ADD49 | 구리 가격 | AAST 미진입. direct candidate가 ambiguous로 종료 | 단순 가격 질의가 대표 기준 mapping 실패를 ambiguous로 종료 | CAPABILITY_SELECTION | 있음. price criterion binding |

## Information loss stage

| stage | QA | 관찰 |
|---|---|---|
| Semantic requirement/AST 생성 | GM02, CN09, IX01 | 광종·metric·요구 operation이 자연어 의미와 다르게 AST에 나타남 |
| AST → ActionPlan capability 선택 | MP01, IX01 | 국가 구성/지수 요구가 document 또는 price capability로 변환됨 |
| AST branch construction | MP09 | 월간동향 document branch가 root와 node에서 누락됨 |
| Action execution/source contract | IX02, CN05, CN07, CN08, CN09, ADD15 계열 | 필요한 call은 존재하지만 no_data, mapping_missing, validation_failed로 결과 미생성 |
| Runtime relation/dependency | PF03, GM12 | date alignment 또는 PARTIAL input 상태가 relation 단계에서 거부됨 |
| Gate/direct boundary | ADD01, ADD03, ADD49 | AAST로 승격되지 않고 ambiguous에서 종료 |
| Presentation only | MP06 | semantic/action/실행은 성공했으나 표지 판정만 PARTIAL |
| Diagnostic observability | GM11 | 실패 시 parser/plan raw trace가 없어 최초 stage 확정 불가 |

## Coverage validator 검토

공통 validator는 실행 전에 다음을 검사하는 것이 유효하다.

1. **Entity 보존**: requirement의 entity set과 retrieve/for_each 입력 entity set 비교
2. **Metric 보존**: price, import_value, production, indicator 등 metric 비교
3. **Dimension 보존**: country, country_code, mineral, date/period 보존
4. **Branch coverage**: requested output/requirement 수와 roots·terminal capability branch 수 비교
5. **Dependency edge**: upstream output type이 downstream required input type과 호환되는지 검사
6. **Join key**: date/country/mineral key가 양쪽 output schema에 존재하는지 사전 검사
7. **Capability selection**: semantic metric/dimension에 대응하는 capability가 선택됐는지 검사

### 사전 차단 가능 건수

- **엄격한 AAST graph coverage 기준: 5건**
  - IX01, MP01, MP09, GM02, CN09
  - requirement와 AST/call의 entity·metric·branch·operation 불일치를 실행 전에 탐지 가능
- **Gate/direct boundary까지 포함한 넓은 기준: 8건**
  - 위 5건 + ADD01, ADD03, ADD49
  - ambiguous에서 AAST escalation이 누락된 경우를 별도 탐지 가능

다음은 coverage validator만으로 해결할 수 없다.

- PF03: 실제 관측 기간/날짜 교집합 부족
- IX02, CN05, CN07, CN08: source/data/evidence/mapping 부재
- GM12: partial 상태의 join 정책 결정 필요
- MP06: renderer/format 판정 문제
- GM11: 실패 trace 보존 자체가 필요

## 공통 수정 우선순위

1. **Requirement-to-capability coverage validator** — 8건 사전 차단 가능
2. **Entity/metric/operation 보존 contract** — GM02, CN09, IX01, MP01 등 최소 5건
3. **Branch coverage validator** — MP09 및 복합 요구 일반 검출
4. **Price criterion / source mapping diagnostics** — ADD01, ADD03, ADD49, CN05, CN07
5. **Typed partial result join contract** — GM12
6. **Date/as-of alignment contract** — PF03, IX02
7. **Failure-stage trace 보존** — GM11

이번 분석에서 실제 AAST composition 문제가 아닌 것으로 재분류된 QA는
**10건**이다.

- source/data/retrieval: IX02, CN05, CN07, CN08, CN09, ADD15 = 6건
- renderer-only: MP06 = 1건
- direct/gate criterion boundary: ADD01, ADD03, ADD49 = 3건

나머지 **7건**은 AAST 전단 또는 runtime composition contract의 공통 문제로
분류된다: PF03, IX01, MP01, MP09, GM02, GM11, GM12.

## 증적

- 17건 replay raw SSE: `/tmp/aast-r3-17/user_qa_pair_audit_20261002_164852.json`
- 17건 replay report: `/tmp/aast-r3-17/user_qa_pair_audit_20261002_164852.md`
- r3 내부 parser/action/AAST trace: 검증 컨테이너 로그의 2026-10-02 16:48:52 이후 구간

