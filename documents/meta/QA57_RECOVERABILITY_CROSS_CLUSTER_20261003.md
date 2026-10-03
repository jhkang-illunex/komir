# QA57 Recoverability Cross-Cluster Audit — 2026-10-03

## 범위

- 기준: `QA57_AUTHORITATIVE_STRICT_20261003.md`의 최신 21개 non-PASS recoverable 후보
- 대상 image: `komir-rag-chat:cn08-period-change-r3`
- 코드 수정: 없음
- QA57 replay/image rebuild/18002 변경: 없음
- 기존 coarse category보다 최신 first-causal boundary와 필요한 primitive를 우선함

## 1. QA별 재분류

| QA | First Causal Boundary | Required Primitive/Contract | Existing Primitive | Recovery Type |
|---|---|---|---|---|
| IX01 | upstream results → relation/calculation | temporal relation + dependency binding | compare/calculate 일부 | CONTRACT_EXTENSION |
| CN01 | branch → root reachability | required branch/root reachability | branch/root graph | CONTRACT_EXTENSION |
| CN09 | output type → projection/filter | derived output type preservation | output/projection contract | CONTRACT_EXTENSION |
| GM11 | document-derived entity → expansion | dynamic entity expansion/coverage | `for_each` 일부 | CONTRACT_EXTENSION |
| GM14 | branch output → projection | output semantic type compatibility | capability registry/projection | CONTRACT_EXTENSION |
| ADD03 | requirement → argmax plan | ordered extremum with date lineage | `arg_max` + sort | REUSE 가능성 있음 |
| ADD06 | derived metric → plan output | YoY/derived metric preservation | growth/change primitive | CONTRACT_EXTENSION |
| ADD18 | series result → date projection | time-series date/value contract | `price.series`/series projection | CONTRACT_EXTENSION |
| ADD45 | Gate → navigation plan | navigation target resolution | navigation/Gate path | REUSE 가능성 낮음 |
| ADD46 | Gate → navigation plan | navigation target resolution | navigation/Gate path | REUSE 가능성 낮음 |
| MI02 | document result → requested concept | concept/evidence output completeness | document retrieval | BLOCKED/EVIDENCE |
| DOC02 | document result → title projection | document title output contract | document projection | CONTRACT_EXTENSION |
| MP04 | production result → derived comparison | YoY + comparison dependency | growth/compare 일부 | CONTRACT_EXTENSION |
| GM13 | price selection → canonical output | criterion/default population contract | representative-price registry | CONTRACT_EXTENSION |
| ADD01 | latest requirement → cardinality/projection | latest single-observation contract | `latest_value` 일부 | CONTRACT_EXTENSION |
| ADD38 | multi-entity result → projection | entity identity preservation | typed projection | CONTRACT_EXTENSION |
| IX02 | left/right series → join | date/entity/unit alignment | join/compare | REUSE 가능성 있음 |
| GM01 | resource/trade results → join | country-key alignment | join/compare | REUSE 가능성 있음 |
| REG06 | two price series → compare | criterion/entity/period alignment | join/compare | REUSE 가능성 있음 |
| ADD16 | population → scalar → ratio | typed reduction + dependency | aggregate/ratio | REUSE 가능성 있음 |
| ADD25 | branches → dependency | typed dependency binding | compare/dependency | CONTRACT_EXTENSION |

## 2. Cross-Cluster Matrix

| Rank | Primitive/Contract | QA IDs | Count | Reuse/Extension/New | Cost | Risk | Expected Recovery |
|---:|---|---|---:|---|---|---|---:|
| 1 | canonical join/alignment key | IX02, GM01, REG06 | 3 | REUSE + small contract extension | MEDIUM | MEDIUM | 2~3 |
| 2 | output semantic type/canonical projection | CN09, GM14, DOC02, ADD38 | 4 | CONTRACT_EXTENSION | MEDIUM | MEDIUM | 2~3 |
| 3 | derived metric + comparison dependency | IX01, MP04, ADD06 | 3 | existing calculate/compare extension | MEDIUM | MEDIUM/HIGH | 1~2 |
| 4 | typed reduction/scalar dependency | ADD16, ADD25 | 2 | existing aggregate/ratio + dependency extension | MEDIUM | MEDIUM | 1~2 |
| 5 | navigation target/Gate resolution | ADD45, ADD46 | 2 | existing Gate path; contract likely separate | LOW | LOW | 1~2 |
| 6 | ordered extremum/date lineage | ADD03 | 1 | `arg_max` + canonical date | LOW/MEDIUM | MEDIUM | 1 |
| 7 | latest/cardinality | ADD01 | 1 | latest-value contract extension | LOW | MEDIUM | 1 |
| 8 | dynamic entity expansion/coverage | GM11 | 1 | `for_each`/coverage extension | HIGH | HIGH | 0~1 |
| 9 | series date/value projection | ADD18 | 1 | series contract extension | LOW/MEDIUM | MEDIUM | 1 |
| 10 | criterion/default population | GM13 | 1 | registry/resource contract extension | MEDIUM | MEDIUM | 1 |
| 11 | concept/evidence completeness | MI02 | 1 | evidence/content gap | HIGH | HIGH | 0 |

동일 QA는 하나의 primary cluster에만 배정했다. 예를 들어 ADD25는 join처럼 보일 수
있지만 최신 trace의 최초 경계가 `dependency binding`이므로 join cluster에 중복 배정하지
않았다.

## 3. Existing Primitive 재사용성

### REUSE 가능성이 높은 항목

- IX02/GM01/REG06: 양쪽 결과의 canonical key가 실제 존재하는 경우 기존 join/compare를
  재사용할 수 있다. positional join은 허용하지 않는다.
- ADD16/ADD25: 기존 aggregate/ratio/compare 조합과 typed dependency로 표현 가능한지
  먼저 확인한다. reduction 의미가 확정되지 않으면 중단한다.
- ADD03: 기존 `arg_max`와 canonical date ordering 조합을 우선 검토한다.

### CONTRACT_EXTENSION이 필요한 항목

- CN09/GM14/DOC02/ADD38: capability output semantic type과 projection field를 Registry/
  TypedResult에서 단일 선언으로 연결해야 한다.
- IX01/MP04/ADD06: derived metric과 temporal comparison의 base metric, period, output
  type을 보존해야 한다.
- ADD01: `latest_value` cardinality와 date identity를 명시해야 한다. ADD01 전용 보정은
  금지한다.

### 신규 primitive가 필요한 것으로 확정된 항목

현재 확정된 `NEW_PRIMITIVE`는 없다. 기존 primitive로 표현 가능 여부를 먼저 검증해야 한다.

### BLOCKED에 가까운 항목

- MI02: 현재 source/evidence가 질문의 금속 기본특성 요구를 충분히 보장하지 않음.
- GM11: dynamic entity expansion과 document-derived population 보존 문제가 있어 높은 위험이다.

## 4. Architecture Friction

| 항목 | 관찰 |
|---|---|
| 반복 수정 module | `live_multihop`/semantic planning 경계와 TypedResult/projection 경계가 반복적으로 변경됨 |
| central dispatcher | 새 기능을 추가할 때 LiveOperator/legacy alias 경계를 건드릴 위험이 있음 |
| duplicated contract 후보 | legacy alias mapping, projection field mapping, Registry output metadata가 일부 병렬 존재 |
| physical schema leakage | source adapter boundary 밖에서 alias/field 의미가 재해석되는 경로가 남아 있음 |
| REFACTOR_CANDIDATE | legacy alias/projection mapping 정리; 이번 iteration에서는 수행하지 않음 |
| REFACTOR_REQUIRED | 현재는 아님. 공통 contract extension으로 최소 수정 가능한 후보가 남아 있음 |

상위 3개 cluster는 기존 Registry/TypedResult/join/calculation 경계를 활용할 수 있어,
이번 audit 증거만으로 architecture checkpoint를 선언할 정도의 friction은 아니다. 다만
새 중앙 `if/elif`나 QA별 mapping을 추가하면 즉시 `COMPLEXITY_WARN`으로 재평가해야 한다.

## 5. ROI 판단

확실한 2개 이상 cluster가 세 개 이상 존재한다.

- join/alignment: 3건, 예상 2~3건
- output semantic/projection: 4건, 예상 2~3건
- derived metric/comparison: 3건, 예상 1~2건
- reduction/dependency 및 navigation도 각각 2건 이상이다.

따라서 이론상 예상 recovery는 +5 이상이지만, 실제 recovery는 typed requirement의 의미가
충분하고 canonical key/field가 존재하는 QA로 제한해야 한다. source/evidence 부족과
business semantic ambiguity를 점수에 포함하지 않는다.

## 6. Decision

### `CONTINUE_RECOVERY`

이유:

1. 2건 이상 공통 cluster가 세 개 이상 존재한다.
2. 상위 cluster는 기존 primitive와 Registry/TypedResult contract를 재사용할 수 있다.
3. 예상 strict recovery가 보수적으로도 +5 이상이다.
4. 신규 execution architecture 없이 contract extension으로 접근 가능하다.
5. 다만 중앙 dispatcher 증가와 duplicated mapping 추가는 금지한다.

### 다음 구현 대상 3개

1. IX02/GM01/REG06 — canonical join/alignment
2. CN09/GM14/DOC02/ADD38 — output semantic type/canonical projection
3. IX01/MP04/ADD06 — derived metric/comparison dependency

ADD16/ADD25 reduction/dependency는 위 cluster 이후의 다음 후보로 둔다. ADD01, GM11,
MI02는 단일 또는 고위험 항목이므로 공통 cluster 근거가 추가될 때까지 후순위다.

## 7. Architecture & Complexity Guard

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

### Contract Delta

```text
New contracts: 없음
Modified contracts: 없음
Removed contracts: 없음
Canonical source of truth: Capability Registry/Spec, Typed Requirement, TypedResult, existing operator contracts
Consumers: planner/AAST validation, capability runtime, join/calculation/projection
Duplicated mappings remaining: legacy alias/projection mapping; REFACTOR_CANDIDATE
```

이번 단계에서는 code, replay, image, 18002를 변경하지 않았다.
