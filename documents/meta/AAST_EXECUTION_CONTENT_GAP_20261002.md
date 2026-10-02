# AAST execution/content gap audit

## Scope

- Image: `komir-rag-chat:aast-coverage-r1`
- Validation port: `18012`
- Production `18002`: not changed or restarted
- Source replay: answerable QA 57 replay at `/tmp/aast-r1-57/summary.json`
- Oracle: `documents/meta/qa106_grounded_comparison_20261002.csv`
- Code changes: none in this audit

## PASS terminology

이후 보고서에서는 단독 `PASS`를 사용하지 않는다.

- `EXECUTION_PASS`: 요청 경로가 오류·abstain 없이 완료됨
- `CONTENT_PASS`: 결과 내용이 source-backed oracle과 일치함
- `FORMAT_PASS`: 요청된 표/차트/문장 등 출력 형식을 준수함
- `E2E_PASS`: execution, content, format, evidence 조건을 모두 충족함

현재 57건의 보수적 content 판정은 숫자 근거 일치 또는 oracle text 포함만
`CONTENT_PASS`로 인정했다. 따라서 `FORMAT_PASS`와 `CONTENT_PASS`는 독립 지표다.

## Accounting

| 지표 | 건수 |
|---|---:|
| answerable QA | 57 |
| EXECUTION_PASS | 34 |
| CONTENT_PASS | 23 |
| EXECUTION_PASS ∧ not CONTENT_PASS | **11** |

따라서 분석 대상은 정확히 11건이다. HTTP 200, `done=true`, non-abstain은 content
정답으로 계산하지 않았다.

## 11건 분석

`TypedResult` 열은 replay 시 구조화 결과와 table/citation payload에서 확인 가능한
최종 typed payload를 요약한 것이다. 직접 execution trace가 없는 navigation/document
경로는 SSE의 result envelope와 citation으로 확인 가능한 범위만 기록했으며, 값이
없다고 추정하지 않았다.

| QA | Expected oracle | Capability/AAST 최종 TypedResult | 최종 rendered answer | 최초 divergence | 분류 |
|---|---|---|---|---|---|
| MI02 | 니켈=Ni, 원자번호 28, 은백색·내식성 | `document.retrieve`가 니켈 공급구조·배터리·제련 문서를 반환 | 금속 기본 특성이 아니라 공급망·품위·용도 설명 | retrieval/evidence 내용 | `EVIDENCE_MISMATCH` |
| DOC04 | 월간 게시판의 기간·검색어·검색범위 사용법 | navigation이 전략광종/희소금속 2개 페이지 추천 | 두 게시판 선택 안내만 표시, 검색 조작법 누락 | navigation projection | `PROJECTION_MISMATCH` |
| NEWS03 | 중국 수출통제 관련 기사 2건 | `document.retrieve`가 최근 일반 자원뉴스 목록 반환 | 중국 수출통제와 무관한 최신 뉴스 목록 | topic/date evidence | `EVIDENCE_MISMATCH` |
| MP01 | 가격 추이와 한국 수입국 구성의 source-backed 결과 | `price.series` + `trade.country_rank`; 가격 2026-07~10, 수입국 top list 보존 | 두 branch 표는 생성됐으나 oracle의 2026-09 기준과 시점 불일치 | oracle as-of | `ORACLE_MISMATCH` |
| MP06 | 용도 + 2026-09-08 가격 16,745.53 | usage document + `price.series` latest 2026-10-01/23,111.69 | 용도와 현재 가격은 반환되나 oracle 기준일·값과 다름 | oracle as-of | `ORACLE_MISMATCH` |
| CN04 | 수입 의존도 조건 광종과 가격 전망의 명시적 결과 | 광물정보·수입 1위국/비중은 있으나 forecast branch 없음 | 수입 구조만 표시되고 가격 전망은 없음 | branch coverage/result | `MISSING_BRANCH` |
| REG02 | 2026-09-08 니켈 16,745.53 | `price.series` latest 2026-10-01/23,111.69 | 최신 관측값을 반환했으나 과거 oracle과 다름 | oracle as-of | `ORACLE_MISMATCH` |
| REG03 | 2026-09-08 니켈 16,745.53 | `price.series` latest 2026-10-01/23,111.69 | 최신 관측값을 반환했으나 과거 oracle과 다름 | oracle as-of | `ORACLE_MISMATCH` |
| REG06 | 니켈·텅스텐 공통기간 변동률 비교 | price compare에서 니켈 결과만 실질적으로 생성, 텅스텐은 기준/값 없음 | 니켈 표와 텅스텐 조회 불가가 함께 표시됨 | branch/result completeness | `MISSING_BRANCH` |
| ADD27 | 니켈 가격 추이/최신 기준값 2026-09-08 oracle | `price.series` latest 2026-10-01/23,111.69 | 최신 관측값을 반환했으나 과거 oracle과 다름 | oracle as-of | `ORACLE_MISMATCH` |
| ADD45 | 희소금속 가격 화면 navigation 안내 | `price_minor_metals` navigation recommendation과 리튬 filter | 같은 페이지·URL·filter를 더 긴 설명과 함께 반환 | oracle text exactness/format | `RENDERER_FORMAT` |

## 경계별 판정

### Renderer 이전에 이미 갈라진 건

- MI02, NEWS03: retrieval/evidence가 질문의 주제·내용을 보존하지 못함
- CN04: 요구된 forecast branch가 최종 result에 없음
- REG06: 텅스텐 branch/result가 완성되지 않음

이 4건은 Renderer만 고쳐서는 회복되지 않는다.

### TypedResult는 실행됐으나 oracle과 시점이 다른 건

- MP01, MP06, REG02, REG03, ADD27

이 5건은 현재 데이터 기준 최신값/시계열이 실제로 반환됐다. oracle은 2026-09-08
기준 snapshot인데 replay는 2026-10-01 관측값을 사용했다. 따라서 이 5건을 곧바로
wrong value로 판정하지 않고 `ORACLE_MISMATCH`로 분리했다. 비교에는 oracle as-of와
실행 as-of를 먼저 일치시켜야 한다.

### Renderer/projection에서 회복 가능성이 있는 건

- DOC04: navigation capability가 반환한 두 추천에는 게시판 URL이 있으나, 질문의
  “검색 방법”에 필요한 검색조건 projection이 없다.
- ADD45: 의미상 페이지·URL·리튬 filter는 맞지만 oracle과 문구/부가 설명이 다르다.

엄밀한 content oracle 기준으로는 두 건 모두 CONTENT_PASS가 아니지만, ADD45는
의미·resource binding이 보존되어 `FORMAT_PASS` 후보로 별도 평가해야 한다.

## Category distribution

| Category | 건수 |
|---|---:|
| `WRONG_VALUE` | 0 |
| `MISSING_BRANCH` | 2 |
| `WRONG_ENTITY_METRIC_PERIOD` | 0 확정 |
| `PROJECTION_MISMATCH` | 1 |
| `EVIDENCE_MISMATCH` | 2 |
| `RENDERER_FORMAT` | 1 |
| `ORACLE_MISMATCH` | 5 |
| 합계 | 11 |

## 회복 가능성 및 우선순위

1. **oracle as-of 정렬**: 5건. 실행시점과 oracle 기준일을 동일하게 만든 뒤 재평가하면
   실제 content 오판을 가장 많이 줄일 수 있다. 이는 production code 수정이 아니라
   평가 계약 정렬 문제다.
2. **document/news topic·period evidence 보존 검증**: 2건. document capability의
   검색 조건과 evidence topic/date가 TypedResult까지 유지되는지 공통 검증한다.
3. **composite requested branch coverage**: 2건. forecast와 비교 대상 branch가
   계획·result에 모두 존재하는지 Validator/실행 결과로 분리한다.
4. **navigation projection contract**: 1건. resource registry가 제공하는 검색방법
   metadata를 navigation result에 포함할 수 있는지 확인한다.
5. **navigation renderer wording/format**: 1건. 의미가 이미 보존된 ADD45는 마지막에
   format oracle과 별도로 평가한다.

## 결론

11건 모두를 capability 실행 오류로 볼 수 없다.

- 데이터/계획 내용 divergence: 4건
- oracle 기준시점 불일치: 5건
- projection/format: 2건

현재 artifact 기준으로 `EXECUTION_PASS=34`를 정답률로 표현하면 안 된다. 이후에는
최소 `EXECUTION_PASS`, `CONTENT_PASS`, `FORMAT_PASS`, `E2E_PASS`를 분리해 보고해야 한다.

상태: **분석 완료 / 코드 수정 없음 / 18002 미변경**
