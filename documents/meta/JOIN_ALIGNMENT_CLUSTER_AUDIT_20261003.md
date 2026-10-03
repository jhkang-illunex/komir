# Canonical Join / Alignment Cluster Audit — 2026-10-03

## 범위와 판정

- 대상: IX02, GM01, REG06
- 검증 환경: 18012 `komir-rag-chat-cn08-r3`
- 운영 18002: 변경 없음
- 코드 수정: 없음
- QA57 full replay: 수행하지 않음
- 현재 authoritative strict baseline: 21/57
- 기준: 최신 trace의 최초 causal boundary. HTTP 200, 실행 완료, 표 생성만으로
  strict content pass로 판정하지 않음.

각 대상은 fresh session으로 3회 재실행했다. audit runner의 형식 상태는 IX02
`PARTIAL` 3/3, GM01 `PARTIAL` 3/3, REG06 `FAIL` 3/3이었다. 아래 분류는
runner의 coarse 상태가 아니라 typed trace와 AAST를 기준으로 재분류했다.

## 요약

| QA | semantic result type | canonical metric | entity / scope | period | unit | cardinality | 실제 semantic key | 최초 causal boundary | 판정 |
|---|---|---|---|---|---|---:|---|---|---|
| IX02 | `PriceSeries` + `IndicatorSeries` | `price_series` + `series` | 니켈 / composite index `HI001` | price trailing 12개월 / indicator period 미확정 | USD/톤 / indicator unit 미보존 | 261 / 60 | 양쪽 raw에 `date` | indicator raw result → projection | `OUTPUT_CONTRACT` / `PROJECTION_CONTRACT` |
| GM01 | `ResourceRanking` + `TradeCountryRank` | production + import_amount/country_rank | 코발트 / WORLD + KR | resource year 2025 / trade trailing period | 톤 / USD | 12 / 5 | 양쪽 raw에 `country` | compare composition: country key 미결속 | `COMPOSITION_OPERATOR` / `JOIN_CONTRACT` |
| REG06 | `PriceSeries` + empty price result | current + current | 니켈 + 텅스텐 | latest / latest | nickel price row 존재, tungsten 미확정 | 60 / 0 | date는 nickel에만 관측 | tungsten capability input/source binding | `CRITERION_BINDING` / `SOURCE_ADAPTER` |

## QA별 trace

### IX02

Semantic requirement는 다음 두 branch를 보존했다.

- price: `price_series`, mineral=니켈, trailing 12개월, `REPRESENTATIVE`
- indicator: `series`, indicator=`composite_index`, variant=`composite`

AAST는 두 retrieve와 두 project를 만든 뒤 `compare(operation=side_by_side,
left_field=price, right_field=series, sort_key=date)`를 root로 생성했다. validator는
통과했고 root execution도 `success`였다. 두 raw typed result의 key는 다음과 같았다.

- price: `date`, `price`, `value`, `price_criterion`, `price_measure_label` 등
- indicator: `date`, `value`, `indicator`, 물리 `indx(지수)` 등. canonical `series` row
  field는 trace에 없음

따라서 날짜라는 후보 key 자체가 없는 것이 아니다. 그러나 indicator project가
`series`를 요청했고, 실제 canonicalized output에는 `value`만 남아 right series가
빈 상태가 됐다. 최종 표도 price 쪽 행만 `SUCCESS`이고 `right.date/right.series`가
비어 있었다.

**최초 causal boundary:** `Indicator TypedResult → Projection/output contract`.
이 단계가 해결되지 않은 상태에서 date join을 보완하는 것은 잘못된 수정이다.

### GM01

Semantic requirement는 다음 두 ranked set을 요구했다.

- resource: 코발트 production, `WORLD`, country ranking
- trade: 코발트 import country rank, `KR`, country ranking

AAST에는 resource rank와 trade country rank가 모두 존재하고 root compare도 생성됐다.
두 upstream raw result 모두 국가 식별자인 `country`를 보유했다.

- resource raw: `country`, `country_code`, `total`, `unit`, `year`
- trade raw: `country`, `import_amount`, rank/share/total 계열 필드

기존 boundary canonicalization은 resource `total`을 production 계열 field로,
trade `import_amount`/total 계열을 import 계열 metric으로 변환할 수 있는 정보를
가지고 있다. 그러나 generated compare는 `operation=side_by_side`만 있고
`join_key=country` 또는 `left_on/right_on`이 없다. 또한 이 질문의 “비교”가
국가 집합의 side-by-side인지 교집합인지에 대한 relation contract도 AAST에 없다.
행 순서나 첫 숫자 필드로 결합할 수 없다.

**최초 causal boundary:** `RankedCountrySet × RankedCountrySet → composition`
단계의 country-key binding/operator contract. 공통 country key의 존재는 확인됐지만,
그 key를 사용할 join semantics가 명시되지 않아 deterministic join을 수행할 수 없다.

### REG06

Semantic requirement와 raw action plan은 니켈과 텅스텐의 독립 current price branch
두 개를 모두 생성했다. AAST는 두 retrieve와 `side_by_side` compare를 생성했고
bounded repair 결과에는 `join_key=date`가 있었다.

그러나 capability trace는 반복 3회 모두 다음과 같았다.

- nickel `price.series`: row_count=60, date/value/criterion 계열 존재
- tungsten `price.series`: row_count=0, failure=`price_criterion_selection_required`
- compare: dependency unavailable

즉 date key를 정규화하거나 join하는 단계까지 도달하지 않았다. right input 자체가
criterion binding/source selection에서 비어 있으므로 positional join 또는 빈 결과를
임의로 보정할 수 없다.

**최초 causal boundary:** `Typed Capability Args → price source/criterion binding`.
이는 canonical join failure가 아니라 source/criterion contract blocker다.

## Shared contract 판정

세 QA에 동일한 canonical alignment contract가 있다는 증거는 없다.

| 비교 | 공통점 | 결정적 차이 | 동일 cluster 여부 |
|---|---|---|---|
| IX02 ↔ GM01 | 두 branch 결과를 함께 표현하려 함 | IX02는 indicator projection field 손실, GM01은 country join semantics 미결속 | 아니오 |
| IX02 ↔ REG06 | 둘 다 compare AST | IX02는 양쪽 raw result가 있으나 right projection 손실, REG06은 tungsten source/criterion 결과가 0행 | 아니오 |
| GM01 ↔ REG06 | 둘 다 price/resource 계열이 아님 | GM01은 country key가 양쪽에 존재, REG06은 right input 자체 없음 | 아니오 |

따라서 이번 iteration에서 Registry/TypedResult/Canonical Field Resolver를 공통 확장하면
최소 한 QA에는 맞지 않는 완화가 된다. 수정하지 않았다.

### 분류 결과

- IX02: `OUTPUT_CONTRACT / PROJECTION_CONTRACT`; 날짜 alignment 이전 blocker
- GM01: `COMPOSITION_OPERATOR / JOIN_CONTRACT`; country key는 존재하지만 join 의미와
  key binding이 없음
- REG06: `CRITERION_BINDING / SOURCE_ADAPTER`; tungsten source result가 없어 join 불가
- `STALE_FAILURE_CLASSIFICATION`: 없음. 세 건 모두 현재 3회 trace에서 동일 blocker 재현
- `BLOCKED`: REG06은 데이터 자체 없음으로 확정하지 않고 `price_criterion_selection_required`
  상태의 source/criterion binding blocker로 유지

## Regression / architecture guard

이번 audit은 코드 수정이 없으므로 join/alignment test, rag_core, rag_chat를 변경 후
실행하지 않았다. 기존 golden은 유지된다.

### Complexity Delta

- Files changed: artifact 1개
- New classes: 0
- New public contracts: 0
- New registry entries: 0
- New special-case branches: 0
- New central-dispatch branches: 0
- Removed branches: 0
- Duplicated contract sources added: 0
- Duplicated contract sources removed: 0
- Largest modified method/class/module LOC: 해당 없음
- Responsibility growth detected: 없음
- Verdict: `COMPLEXITY_PASS` (분석만 수행)

기존 legacy alias/renderer mapping의 중복 위험은 이번 audit에서 해소하지 않았으며,
기존 기록대로 후속 `REFACTOR_CANDIDATE`로 유지한다. 이번 결과를 근거로 중앙 dispatcher에
QA별 join 분기를 추가하지 않는다.

### Contract Delta

- New contracts: 없음
- Modified contracts: 없음
- Removed contracts: 없음
- Canonical source of truth: 기존 Capability Registry / TypedResult / AAST operator contract
- Consumers: 기존 planner, validator, capability executor, projection
- Duplicated mappings remaining: 기존 alias/physical-field mapping 후보는 유지되며
  이번 iteration에서 추가되지 않음

## 결론 및 다음 분리 작업

Canonical Join/Alignment 하나의 공통 repair cluster는 성립하지 않는다. 다음 작업은
서로 분리해야 한다.

1. GM01: `RankedCountrySet` 간 relation/국가 key binding contract를 별도 분석하되,
   side-by-side와 intersection 의미를 추측하지 않는다.
2. IX02: indicator `value/series` output contract를 projection 이전 canonical owner에서
   확인한다.
3. REG06: tungsten criterion selection/source binding을 Data/Capability 계층에서
   확인한다.

이번 iteration에서는 코드, 이미지, 18002, QA57 full replay를 변경하지 않았다.
