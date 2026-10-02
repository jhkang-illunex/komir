# AAST ORACLE 재평가 결과

## 범위

- 대상 이미지: `komir-rag-chat:aast-coverage-r1`
- 검증 포트: `18012`
- 운영 `18002`: 변경·재시작하지 않음
- 대상: `MP01`, `MP06`, `REG02`, `REG03`, `ADD27`
- 코드, AAST, Capability, Validator, Renderer: 변경 없음

## 판정 용어

- `EXECUTION_PASS`: 실행 완료
- `CONTENT_PASS`: 동일 snapshot에서 의미·값·단위·기간이 oracle 요구와 일치
- `FORMAT_PASS`: 요청 출력 형식 준수
- `E2E_PASS`: execution/content/format/evidence 모두 충족
- `ORACLE_STALE`: 실행 결과가 최신 snapshot과 일치하지만 oracle이 과거 snapshot에 고정됨
- `ORACLE_AMBIGUOUS`: oracle의 기준일·기간·출력 의미가 질문에서 결정되지 않음
- `CONTENT_FAIL`: 동일 snapshot으로 정렬해도 질문 요구를 충족하지 못함

## 공통 snapshot 확인

18012 실행 결과의 가격 최신 관측값은 다음과 같다.

```text
기준일: 2026-10-01
니켈 LME CASH: 23,111.69 USD/mt
전일 대비: +194.96 (+0.85%)
```

기존 oracle은 2026-09-08 값 `16,745.53 USD/톤`에 고정되어 있었다. 질문에 과거
기준일이 명시되지 않은 경우 2026-09-08을 현재 정답으로 강제하지 않았다.

## QA별 재평가

| QA | 질문의 시간 의미 | 실제 실행 snapshot / TypedResult | 동일 snapshot 판정 | 사유 |
|---|---|---|---|---|
| MP01 | 날짜 미지정 가격 추이 + 한국 수입국 구성 | `price.series` 니켈 시계열과 `trade.country_rank` 한국 수입국 결과가 모두 생성됨. 가격 2026-07~10, 수입 조회 기간 2025-11~2026-07 | `CONTENT_PASS` | 니켈·가격·수입국 metric과 두 branch가 보존됨. 기존 oracle은 2026-09-08 일부 가격 설명만 포함해 불완전/과거 snapshot임 |
| MP06 | “지금” = 최신 관측값 | usage document + `price.series latest_value`, 2026-10-01 / 23,111.69 USD/mt | `CONTENT_PASS` | usage와 최신 가격 모두 존재하며 질문 의미와 일치. 기존 2026-09-08 가격은 stale |
| REG02 | “오늘” = 현재 시점에서 사용 가능한 최신 관측값 | 2026-10-01 / 23,111.69 USD/mt / +0.85% | `CONTENT_PASS` | 2026-10-02 현재 DB의 최신 관측일은 10-01로 보이며, 미래 10-02 행을 만들지 않음. 기존 oracle만 stale |
| REG03 | “최근” = 최신 관측값 | 2026-10-01 / 23,111.69 USD/mt / +0.85% | `CONTENT_PASS` | entity/metric/unit/latest 의미 일치. 기존 oracle만 stale |
| ADD27 | “가격 추이” = 기간별 시계열 | 최종 rendered answer에는 2026-10-01 최신값 1건만 존재. time-series 전체 TypedResult/표가 최종 출력되지 않음 | `CONTENT_FAIL` | snapshot을 맞춰도 기간별 추이 요구가 충족되지 않음. 단순 oracle stale 문제가 아님 |

## 기존 oracle 5건의 재분류

| 분류 | 건수 | QA |
|---|---:|---|
| `CONTENT_PASS` | 4 | MP01, MP06, REG02, REG03 |
| `CONTENT_FAIL` | 1 | ADD27 |
| `ORACLE_STALE` | 4 | MP01, MP06, REG02, REG03의 기존 고정 oracle |
| `ORACLE_AMBIGUOUS` | 0 | - |

`ORACLE_STALE`는 QA 전체의 최종 판정이 아니라 기존 oracle snapshot에 대한 진단이다.
최종 QA 판정은 최신 snapshot 기준의 `CONTENT_PASS`/`CONTENT_FAIL`로 계산했다.

## answerable 57 재집계

기존 보수적 판정:

```text
CONTENT_PASS: 23/57 (40.35%)
```

재평가 후:

```text
CONTENT_PASS: 27/57 (47.37%)
CONTENT_FAIL: 30/57
```

변경:

```text
23 → 27
증가: +4건, +7.02%p
```

증가 사유는 점수 상승을 위한 정답 완화가 아니라, 질문이 과거 날짜를 요구하지 않는
최신/현재 질의 4건의 oracle을 현재 정상 snapshot 기준으로 재정렬했기 때문이다.
ADD27은 시계열 요구가 실제 결과에 없으므로 계속 `CONTENT_FAIL`이다.

## 향후 oracle 최소 개선안

대규모 evaluation framework 변경 없이 oracle metadata에 다음 필드를 추가하는 방식을
권장한다.

```text
oracle_kind: STATIC | SNAPSHOT | DYNAMIC_LATEST
as_of: date | null
freshness_policy: exact_date | latest_observation_on_or_before | fixed_snapshot
period_contract: latest_value | time_series | range | null
unit: canonical unit | null
```

- `STATIC`: 개념 설명, navigation, 고정 문서 사실
- `SNAPSHOT`: 특정 실행일·특정 관측일을 재현해야 하는 QA
- `DYNAMIC_LATEST`: “오늘/현재/최근/latest” 질의. 평가 시 실행 시점의
  `latest_observation_on_or_before`를 사용

가격 추이 질문은 `DYNAMIC_LATEST`만으로 부족하므로 `period_contract=time_series`도
함께 기록해야 한다.

## 검증 상태

- 18012 health: 200
- 18002 health: 200, 기존 이미지 유지
- 기존 코드 회귀: 변경 없음
- 본 작업의 코드 수정: 없음

상태: **재평가 완료 / artifact 작성 완료 / 서버 변경 없음**
