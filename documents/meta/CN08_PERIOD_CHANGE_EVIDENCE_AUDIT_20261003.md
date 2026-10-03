# CN08 period-change / document-evidence audit — 2026-10-03

## 범위와 검증 상태

- 대상: CN08 `지난달 광물종합지수 변동이랑 월간동향 요약 같이 보여줘`
- 운영 18002: 변경 없음
- 검증 컨테이너: `komir-rag-chat-cn08-r3`
- 이미지: `komir-rag-chat:cn08-period-change-r3`
- 이미지 digest: `sha256:1684d72c47730f556549b7519984b7a0b7ad8a0d3cea9ce9b333218be2401bed`
- source SHA: `fa423722caeb86bfb83e6561e3b355b20da2ef38`
- QA57 full replay: 수행하지 않음

## Requirement 분해

### Calculation branch

```text
domain=indicator
metric=series
indicator=composite_index
indicator_variant=composite
operation=period_change
period=trailing_months(1)
output=period change over the selected series
```

### Evidence branch

```text
domain=document
metric=retrieve
document_type=report
topic=광물종합지수 변동 / 월간동향
output=monthly-trend document evidence
```

두 branch는 독립 root이며, calculation 결과가 document 검색의 입력이 되는 dependency는 없다.

## 최초 causal failure

### 변경 전

```text
indicator.series source series
  → generic calculate(period_change)
  → unsupported_calculation_contract
```

문서 branch는 같은 graph에서 별도로 실행되며, 문서 retrieval 결과가 calculation failure의 원인은 아니다.

### 적용한 공통 수정

1. Typed semantic requirement가 `indicator.operation=period_change`를 명시할 때만,
   `retrieve(indicator.series) → calculate(period_change)` AST 표현을
   `indicator.series(indicator_operation=period_change)`로 정규화했다.
2. 기존 `analytical_series.calculate_series`의 `endpoint_change` primitive를
   indicator typed output 경계에서 재사용해 기간 변화 계산을 수행하도록 연결했다.
3. indicator canonicalizer가 이미 존재하는 `date=YYYYMMDD`도 ISO 날짜로 정규화하도록 보완했다.

질문 문자열, QA ID, 광종별 분기는 추가하지 않았다. AST/AAST 구조, Renderer, document retrieval 구조는 수정하지 않았다.

## 변경 후 CN08 fresh ×3

| Run | AAST/Capability path | Calculation branch | Evidence branch | 최종 상태 | 최초 잔여 blocker |
|---:|---|---|---|---|---|
| 1 | `indicator.series(period_change)` + `document.retrieve` | capability 진입 후 fail-closed | success | PARTIAL | `unit_unavailable` |
| 2 | 동일 | capability 진입 후 fail-closed | success | PARTIAL | `unit_unavailable` |
| 3 | 동일 | capability 진입 후 fail-closed | success | PARTIAL | `unit_unavailable` |

세 실행 모두 기존 `unsupported_calculation_contract`와 `invalid_series_date`는 재현되지 않았다.
현재 원천 indicator rows에는 canonical `value`와 날짜가 있으나 계산 primitive가 요구하는
검증된 `unit`이 없다. 단위를 임의로 `index` 등으로 생성하지 않았으므로 strict CONTENT_PASS로 승격하지 않았다.

판정: `BLOCKED` — calculation output contract의 unit 요건과 source indicator unit 부재가 남아 있음.
Evidence branch는 3/3 retrieval 성공으로 `EVIDENCE_LAYER_RECOVERED`에 해당한다.
CN08 전체는 calculation blocker 때문에 `STABLE_RECOVERED`가 아니다.

## 보호 sentinel

검증 이미지에서 fresh session으로 다음을 실행했다.

| QA | Shadow execution status |
|---|---|
| REG02 | success |
| REG05 | success |
| MP07 | success |
| ADD01 | success |
| ADD49 | success |
| GM02 | success |
| ADD27 | success |

기존 stable sentinel regression은 관찰되지 않았다. sentinel의 strict content 재평가는 이번 CN08 작업의 점수 집계에 포함하지 않았다.

## 테스트

- 관련 live multihop / normalization / series tests: `5 passed`
- `PYTHONPATH=.:inhouse pytest -q inhouse/rag_core/tests`: `1557 passed`, `0 failed`, `695 subtests passed`
- `PYTHONPATH=.:inhouse pytest -q inhouse/rag_chat/tests`: `155 passed`, `1 known legacy contract failure`
  - 기존 SSE legacy-control cancellation 기대치(`3 calls`)가 현재 `4 calls`가 되는 실패이며 이번 변경의 CN08 경로와 무관하다.

## Complexity Delta

- Files changed in this iteration: `live_multihop.py`, `test_live_multihop.py`, this artifact
- New classes: `0`
- New public contracts: `0`
- New registry entries: `0`
- New special-case branches: `0` (QA/question/mineral 기준 없음)
- New central-dispatch branches: `0`
- Removed branches: `0`
- Duplicated contract sources added: `0`
- Duplicated contract sources removed: `0`
- Responsibility growth: `false`; existing AST normalization and capability typed-output boundary만 사용
- Verdict: `COMPLEXITY_PASS`
- Pre-existing legacy alias/renderer mapping duplication: `REFACTOR_CANDIDATE`로 유지

## Contract Delta

- Modified contracts:
  - `indicator.series` AST equivalent form: `calculate(period_change)` → typed `indicator_operation=period_change`
  - indicator date canonicalization: compact date → ISO date
  - indicator period-change execution: existing `endpoint_change` primitive binding
- Canonical source of truth:
  - `IndicatorSeriesInput` / `ActionSlots.indicator_operation`
  - `analytical_series.calculate_series` endpoint-change contract
- Consumers: AST normalization, `_action_slots`, live capability execution, canonical TypedResult conversion
- New semantic types: `0`
- Remaining duplicated mappings: legacy composite-index text formatter와 live typed path에 period-change 표현 책임이 부분적으로 병존함. 이번 iteration에서는 Renderer/legacy 경로를 변경하지 않고 `REFACTOR_CANDIDATE`로 기록한다.

## 다음 blocker

CN08의 다음 저비용 검토 후보는 indicator source가 제공하는 unit contract와
`calculate_series`의 unit validation 간 공통 정합성이다. source에 unit이 실제로 존재하지 않는다면
임의 보정 없이 `DATA_QUALITY_GAP` 또는 `CALCULATION_GAP`으로 유지해야 한다.

다음 roadmap 후보는 사용자 지시대로 PF02이며, 이번 iteration에서는 처리하지 않았다.
