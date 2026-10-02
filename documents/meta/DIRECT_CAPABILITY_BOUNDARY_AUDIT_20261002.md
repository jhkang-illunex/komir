# Direct Capability Boundary Audit (2026-10-02)

## 범위와 결론

이번 감사는 Query Gate의 실행 구조를 변경하지 않고, 현재 `COMPLEX`로 분류된
QA106 개발 subset 91건을 기존 physical capability/action contract만으로 재분류한
결과다. 106개는 실제 사용자 workload의 무작위 표본이 아니므로 아래 비율은
`QA106 development subset 내 분포`로만 해석한다.

판정 기준은 다음과 같다.

- `DIRECT_CAPABILITY`: 하나의 기존 executable capability와 완전히 해소된 slot으로
  최종 결과를 만들 수 있음. 내부적으로 여러 행을 읽는 것은 추가 capability 의존으로
  보지 않는다.
- `DIRECT_CAPABILITY_MAP`: 동일 capability를 여러 독립 entity에 적용하고 결과 간
  rank/compare/join이 없음.
- `COMPOSITE_AAST`: 둘 이상의 capability/operation 사이에 data dependency, 비교,
  집계 조합, 문서→구조화 데이터 전달, 또는 이전 결과 참조가 있음.
- `UNRESOLVED`: 현재 contract만으로 단일 호출 여부를 안전하게 확정할 수 없음.
- `UNSUPPORTED`: 정상 데이터 capability가 아니라 내부 자원/존재하지 않는 entity 등
  현재 허용 범위 밖의 요구.

## 현재 contract 근거

현재 V2 registry에는 `document.retrieve`, `price.series`, `trade.monthly`,
`trade.concentration`, `resource.rank`, `inventory.latest`, `indicator.series`가
등록되어 있다 (`inhouse/rag_core/ragkit/semantic_v2.py:971-979`). Lowerer는
logical `Retrieve`만 physical Action으로 내리고, `Calculate/Filter/Sort/TopK/
Project`는 runtime logical step으로 남긴다 (`semantic_v2.py:982-1015`).

Legacy catalog에는 `price.compare`, `price.overview`, `resource.price_cross_rank`,
`resource.yoy`, `forecast.price`, `trade.country_rank`, `trade.hs_summary` 등도
실행 가능한 Action으로 등록되어 있다 (`inhouse/rag_core/ragkit/action_contract.py:
189-194`). 따라서 Direct 판정은 질문 문자열이나 QA ID가 아니라 이 catalog의
입력 slot과 결과 contract를 기준으로 했다.

## 전체 COMPLEX 91건 분포

| 분류 | 건수 | QA106 내 비율 |
|---|---:|---:|
| DIRECT_CAPABILITY | 35 | 38.5% |
| DIRECT_CAPABILITY_MAP | 2 | 2.2% |
| COMPOSITE_AAST | 47 | 51.6% |
| UNRESOLVED | 4 | 4.4% |
| UNSUPPORTED | 3 | 3.3% |
| 합계 | **91** | **100%** |

### DIRECT_CAPABILITY (35)

```text
DOC01 DOC03 NEWS01 NEWS02 NEWS03
MP05 MP07
REG01 REG02 REG03 REG04 REG05 REG06 REG07 REG08
ADD01 ADD03 ADD04 ADD06 ADD09 ADD11 ADD13 ADD14 ADD16 ADD18 ADD19
ADD21 ADD22 ADD25 ADD27 ADD30 ADD32 ADD34 ADD37 ADD40
```

대표 contract는 다음과 같다.

- `price.series`: REG02/03, ADD01/03/06/27
- `price.compare`: REG06, ADD25
- `inventory.latest`: REG05
- `trade.country_rank` 또는 `trade.concentration`: REG01/08, ADD11/13/14
- `resource.rank`/`resource.price_cross_rank`: ADD16, MP05
- `indicator.series`: ADD18/19
- `price.overview`: MP07
- `document.retrieve`: DOC01/03, NEWS01/02/03, ADD30/32/34/37/40
- `forecast.price`: REG07, ADD04/21/22

`ADD04`와 `REG07` 등은 구조적으로 Direct이지만 미래/전망 source가 실제로
없으면 실행 결과는 `DATA_UNAVAILABLE`이 된다. 이는 boundary 분류와 데이터
answerability를 혼동하지 않기 위해 별도로 남긴다.

### DIRECT_CAPABILITY_MAP (2)

```text
GM04 ADD38
```

- GM04: 고정된 복수 광종 각각에 동일한 `trade.country_rank`를 독립 적용
- ADD38: 복수 광종 각각에 동일한 최신 가격 조회를 독립 적용

두 사례 모두 entity별 결과를 취합할 수 있지만, 한 entity 결과가 다른 entity의
입력이 되지 않고 cross-entity rank/compare가 없으므로 Composite로 올리지 않았다.

### COMPOSITE_AAST (47)

```text
PF01 PF02 PF03 IX01 IX02 MP01 MP02 MP03 MP04 MP06 MP08 MP09
CN01 CN02 CN03 CN04 CN05 CN06 CN07 CN08 CN09
GM01 GM02 GM03 GM05 GM06 GM07 GM08 GM09 GM10 GM11 GM12 GM13 GM14
ADD05 ADD07 ADD08 ADD10 ADD15 ADD17 ADD26 ADD28 ADD29 ADD31 ADD36 ADD39 ADD50
```

공통 dependency 예시는 다음과 같다.

- `price + forecast`: PF01-03, CN04-07, GM12
- `document/entity extraction → structured query`: MP06/08/09, GM05/07/08/09/14
- `structured result → document/date alignment`: CN01/02/06/08/09, ADD36/39
- `resource/trade/price cross-source comparison`: MP01-04, GM01-03/11/13, ADD17
- `previous result reference`: ADD28/29/31
- `period/metric map 후 비교·집계`: ADD05/07/08/10/15/26/50

단일 Action 이름이 결과에 포함되어 있더라도, upstream 결과를 downstream 입력으로
사용하거나 기간·metric별 결과를 다시 비교/집계하면 Composite로 분류했다.

### UNRESOLVED (4)

```text
ADD20 ADD23 ADD24 ADD35
```

- ADD20: 최근 1년 위기 단계 광종 목록을 반환하는 현재 단일 indicator contract가
  확인되지 않음
- ADD23: 미래 시점의 실제 월별 가격은 `forecast.price`와 실제 관측 가격의
  의미가 충돌하므로 단일 capability로 확정하지 않음
- ADD24: 광종→HS code 목록 enumeration contract가 `trade.hs_summary`의
  필수 `hs_code` 입력과 직접 일치하지 않음
- ADD35: 공급망 보고용 synthesis/우선순위 산출 contract가 현재 catalog에서
  단일 실행 capability로 확정되지 않음

이 항목들은 Direct로 낮추지 않았고, 이번 감사에서 새로운 capability를 추가하지
않았다.

### UNSUPPORTED (3)

```text
ADD41 ADD42 ADD43
```

- ADD41: 공단 내부 대시보드/위기진단 점수라는 보호된 내부 자원 요청
- ADD42: 명시적 내부용 자료 접근 요청
- ADD43: 현재 canonical entity/capability로 확인되지 않는 언옵테늄 요청

## provisional answerable 57 중 AST_REQUIRED/COMPLEX 45

| 분류 | 건수 |
|---|---:|
| DIRECT_CAPABILITY | 18 |
| DIRECT_CAPABILITY_MAP | 2 |
| COMPOSITE_AAST | 25 |
| UNRESOLVED | 0 |
| UNSUPPORTED | 0 |
| 합계 | **45** |

Direct 후보 18건:

```text
NEWS01 NEWS03 MP05 MP07 REG02 REG03 REG04 REG05 REG06
ADD01 ADD03 ADD06 ADD16 ADD18 ADD25 ADD27 ADD32 ADD40
```

Map 후보 2건:

```text
GM04 ADD38
```

나머지 25건은 문서/구조화 결합, 전망 결합, 기간·결과 비교, 또는 typed
history/reference가 필요하여 AAST 경계에 남는다.

## Gate에 대한 판단

현재 r4 Query Gate의 실제 동작은 NAVIGATION만 fast-path 종료하고,
SIMPLE_LOOKUP/FAQ_CONCEPT/COMPLEX는 기존 경로로 승격한다. 따라서 이번 audit의
Direct 35건을 즉시 `SIMPLE_LOOKUP`으로 라우팅해야 한다는 결론은 아니다.

권고하는 다음 경계는 다음과 같다.

```text
Gate
  → route 후보
  → typed capability resolution
  → 단일 Action + 완전한 slot + output contract 확인
      → direct executor (AAST와 같은 Action executor 공유)
  → map이면 독립 worklist/ForEach
  → dependency/composition이면 기존 AAST
```

특히 다음은 Direct로 잘못 낮추면 안 된다.

- `price.series` 하나가 있어도 forecast/document/compare가 함께 요구되는 경우
- 같은 Action을 여러 번 호출하더라도 결과를 다시 rank/aggregate하는 경우
- 문서에서 광종 목록을 먼저 추출해야 하는 경우
- `InputRef`, 이전 turn, 날짜 정렬이 필요한 경우
- 미래 실제값과 전망값을 혼동할 수 있는 경우

## 관측 결과와 제한

- 검증 컨테이너: `komir-rag-chat:query-gate-r4`, `18012`
- 운영 컨테이너: `komir-rag-chat:audit-safety22`, `18002`; 변경하지 않음
- 기존 QA106 Gate 결과: NAVIGATION 4, FAQ_CONCEPT 9, SIMPLE_LOOKUP 2,
  COMPLEX 91
- 이 문서는 boundary audit 결과이며 direct executor 구현, route 변경, 신규
  capability 추가를 수행하지 않았다.
- 실제 데이터 부재/외부 문서 부재는 Direct 구조 판정과 별개의 runtime 상태다.

## 결론

현재 질문 집합에서 `Single Capability`와 `Capability Map`은 실제로 존재한다.
전체 COMPLEX 91건 중 contract상 37건(35 direct + 2 map)이 data dependency
없는 저비용 후보이며, provisional answerable의 AST_REQUIRED 45건 중 20건이
후보이다. 반면 47건은 명확한 cross-capability dependency를 가지므로 AAST가
필요하다.

다만 이 수치는 QA106 개발 subset의 구조적 분포이지 전체 사용자 workload의
처리 비율 추정치가 아니다. 다음 구현을 검토할 때는 direct 후보에 대해 먼저
동일 executor, 동일 evidence/provenance, 동일 abstain 정책을 재사용하는
contract-level resolver를 설계하고, 단일 Action contract가 요구 output을
완전히 보장하지 못하면 즉시 AAST로 escalation해야 한다.
