# Capability Data Audit — 2026-10-03

## 범위와 판정 기준

Capability Fast Regression의 `no_data`, 가격 기준 mapping, source/evidence 실패를
실제 읽기 전용 DB/source 조회로 재분류했다. 감사 기준 시점은 2026-10-03이며,
운영 컨테이너 18002·운영 DB·검증 이미지·소스 코드는 변경하지 않았다. 아래 수치는
`public.ko_mnrl_prc`, `public.ko_mnrl_prc_crtr`, `public.ai_prc_mnrl_map`,
`public.ko_rsrc_prdctn_quty`, `public.ai_mnrl_prc_frcst`,
`public.ai_hs_mtrl_flow`, `public.ko_cstm_cmmrc`, `public.ai_news`를 직접 조회한
결과다.

판정은 capability의 `no_data` 반환을 그대로 신뢰하지 않고, 원천 행 존재·기간·단위·
기준·필터 전후 결과를 확인해 결정했다.

## QA별 감사 결과

중복 대상(CN05, CN07)은 하나의 감사 행으로 통합하지 않고, 아래 표에 한 번씩만
기록했다. 가격과 forecast가 함께 있는 경우에도 최종 차단 원인은 별도 열에 보존했다.

| QA ID | 기존 reason | 실제 source 존재 | 기간 충족 | observation 수 | 최종 분류 | recoverable | 예상 수정 위치 |
|---|---|---|---|---:|---|---|---|
| ADD01 | `price_criterion_mapping_missing` | 예: 리튬 가격 기준 516, 771–773과 관측값 존재 | 최신값 가능 | 4,076(516), 1,117(771), 1,116(772), 1,942(773) | `CRITERION_AMBIGUOUS` | 조건부 | 가격 기준 선택 정책/criterion registry |
| ADD49 | `projection_field_unavailable:value` / mapping 미확정 | 예: 동 501, 503 관측값 존재 | 최신값 가능 | 6,254(501), 5,495(503) | `CRITERION_AMBIGUOUS` | 조건부 | 동 기준 mapping 및 광종 source-key 정규화 |
| GM13 | `price_criterion_mapping_missing` | 예: 코발트 542, 543, 708, 709, 791 관측값 존재 | 최신값 가능(기준별 상이) | 1,061, 2,294, 4,133, 4,138, 3,704 | `CRITERION_AMBIGUOUS` | 조건부 | composite price criterion policy |
| CN05 | forecast/source contract 미확보 | 예: 리튬 가격 773 및 forecast 773 존재 | 현재·forecast 기간 가능 | 1,942 price + 72 forecast | `CRITERION_AMBIGUOUS` | 조건부 | criterion 선택 후 forecast binding |
| CN07 | forecast/source/evidence 미확보 | 예: 리튬 price 773 및 forecast 773 존재 | 가격·forecast 기간 가능; 뉴스는 별도 evidence scope | 1,942 price + 72 forecast | `CRITERION_AMBIGUOUS` | 조건부 | criterion policy; news evidence는 별도 확인 |
| MP04 | `resource.yoy` no_data | 예: MNRL0002 생산량 행 존재 | 2019–2025 공식 연속 연도, 2024/2025 비교 가능 | 90 total; 공식 2019–2025 행과 2024/2025 값 확인 | `DATA_ACCESS_FAILURE` | 예 | resource adapter의 code/population/filter binding |
| ADD03 | `price.series` no_data | 예: 아연 기준 561, 581 관측값 존재 | 2010년 이후 argmax 가능 | 8,466 total(2010-01-04–2027-07-03 범위) | `CRITERION_AMBIGUOUS` | 조건부 | criterion 선택 정책 후 extremum 실행 |
| GM05 | `projection_field_unavailable:country` | 용도 문서 evidence는 있으나 mapped HS의 trade 행 없음 | 국가 순위 기간 충족 불가 | 활성 manganese HS mapping은 있으나 `ko_cstm_cmmrc` 0행 | `DATA_ABSENT` | 아니오 | source 데이터 보강/수집; 코드 우회 금지 |
| PF01 | 외부 forecast source 미확보 | 예: 니켈 502 price와 forecast 존재 | 현재 + 다음월 target 202610 가능 | 6,262 price + 72 forecast | `DATA_ACCESS_FAILURE` | 예 | forecast capability 입력/criterion/filter |
| PF02 | forecast metric/period contract 미확보 | 예: 니켈 502 price와 202610–202809 forecast 존재 | trailing price + forecast horizon 원천 존재 | 6,262 price + 72 forecast | `DATA_ACCESS_FAILURE` | 예 | forecast period/metric binding |
| PF03 | `no_comparable_rows` | 예: price와 forecast 모두 존재 | 일별 price와 월별 target의 직접 공통 key 없음 | 6,262 price + 72 forecast | `DATA_QUALITY_BLOCKED` | 아니오(이번 범위) | 명시적 시간축 비교 계약 필요 |
| CN04 | 외부 forecast source 미확보 | 부분 존재: forecast는 LI/NI/CO/REE/CU 기준으로 존재 | 요청된 의존도 집합 전체의 forecast coverage 미확정 | 기준별 72행씩, 전체 집합은 미충족 | `EXTERNAL_DATA_BLOCKED` | 아니오 | 외부/추가 forecast source 또는 범위 확정 |
| GM12 | 외부 forecast source 미확보 | 일부 존재: MNRL0001/2/3, 0006, 0008 | 5종 전체 forecast coverage는 확인되지 않음 | 확인된 기준별 72행; 전체 요구 집합은 불완전 | `EXTERNAL_DATA_BLOCKED` | 아니오 | 5종 전체 forecast source coverage |

### 가격 기준 세부 확인

`ai_prc_mnrl_map`에서 감사 대상 중 명확한 활성 mapping은 니켈 502와 망간 815가
확인됐다. 리튬·동·코발트·아연은 유효 관측값이 여러 기준에 걸쳐 있으나 단일 대표
기준 mapping이 없다. 따라서 번호가 존재한다는 이유로 첫 기준을 선택하지 않았다.

- 리튬: 516, 771, 772, 773 등. 최신 관측 기간과 단위가 기준별로 다르다.
- 동: 501 LME CASH, 503 LME 3개월. 둘 다 장기간 관측값이 있다.
- 코발트: 542/543/708/709/791. 자료원·조건·관측 기간이 서로 다르다.
- 아연: 561 LME CASH, 581 LME 3개월. 2010년 이후 양쪽 모두 관측값이 있다.

이들은 `DATA_ABSENT`가 아니라 `CRITERION_AMBIGUOUS`다. 사용자가 기준을
지정하거나 검증된 대표 기준 정책이 추가되면 공통 criterion binding으로 회복할 수
있지만, 현재 감사에서 임의 mapping을 만들지는 않았다.

### MP04 생산량 확인

생산량 source key는 `MNRL0002`(니켈)이며, 2019–2026 행이 존재한다. 공식
`se_cd='-'` 기준 합계는 2019–2023, 2024, 2025에 각각 존재하고, 2024/2025는
전년 비교에 필요한 두 시점이 모두 있다. 2026은 공식 행이 없고 DEV 행만 있으므로
최신 공식 연도와 잠정/개발 행을 혼용하면 안 된다. 즉 원천 부재가 아니라 code,
population 또는 공식행 filter가 adapter에서 잘못 적용된 `DATA_ACCESS_FAILURE`다.

### GM05 무역/evidence 확인

망간(MNRL0004)의 HS mapping은 `ai_hs_mtrl_flow`와 활성 item mapping에 존재한다.
그러나 해당 활성 HS code로 `ko_cstm_cmmrc`를 조회한 결과 행이 0건이었다. 문서
용도 evidence가 있다는 사실은 무역 국가 순위 행을 만들어주지 않는다. 따라서 용도
branch는 별도 evidence로 유지하고, 국가 순위 branch는 현재 snapshot에서
`DATA_ABSENT`로 판정한다.

### Forecast source 확인

`ai_mnrl_prc_frcst`에는 base 202609, target 202610–202809, BASE/OPT/PESS,
model `DEV_DUMMY`인 72행 묶음이 다음 기준으로 존재한다.

| source key | criterion | rows | 비고 |
|---|---:|---:|---|
| MNRL0001 | 773 | 72 | 리튬 |
| MNRL0002 | 502 | 72 | 니켈 |
| MNRL0003 | 709 | 72 | 코발트 |
| MNRL0006 | 757 | 72 | 희토류 계열 source key |
| MNRL0008 | 501 | 72 | 동 |

따라서 PF01/PF02의 forecast 원천이 전혀 없는 것은 아니다. PF03은 일별 실제
가격과 월별 forecast target을 같은 날짜 key로 비교하려는 문제이므로 안전한
공통 시간축이 없는 `DATA_QUALITY_BLOCKED`로 분리했다. CN04/GM12는 요구된
전체 집합과 forecast source coverage가 일치하지 않아 `EXTERNAL_DATA_BLOCKED`로
남겼다.

## 집계와 ROI

| 최종 분류 | 건수 | 코드 수정 ROI |
|---|---:|---|
| `DATA_ABSENT` | 1 | 제외: source 행 자체가 없음 |
| `PERIOD_NO_DATA` | 0 | 해당 없음 |
| `PERIOD_INSUFFICIENT` | 0 | 해당 없음 |
| `DATA_ACCESS_FAILURE` | 3 | 1순위 recoverable: MP04/PF01/PF02 공통 adapter/binding 조사 |
| `DATA_QUALITY_BLOCKED` | 1 | 제외: 시간축/품질 계약 결정 필요 |
| `EVIDENCE_RETRIEVAL_FAILURE` | 0 확정 | 별도 문서 evidence 재확인 대상은 있으나 이번 DB 감사에서 확정하지 않음 |
| `EXTERNAL_DATA_BLOCKED` | 2 | 제외: 전체 forecast source coverage 부족 |
| `CRITERION_AMBIGUOUS` | 6 | 자동 수정 제외: 대표 기준 정책 또는 사용자 선택 필요 |

`CRITERION_MAPPING_GAP` 중 단일 기준이 확정되어 바로 매핑할 수 있는 건수는
0건이다. 니켈 502와 망간 815는 이미 mapping이 확인됐고, 나머지 감사 대상은
복수 유효 기준이어서 mapping을 임의로 추가하면 의미가 바뀐다.

따라서 이번 감사에서 공통 수정으로 회복 가능한 예상 QA는 우선 3건
(MP04, PF01, PF02)이다. 다만 PF01/PF02는 forecast adapter가 502와 월별
target을 실제 capability contract에 전달하는지 별도 검증이 필요하다. 가격 기준
정책이 확정되면 조건부로 ADD01, ADD49, GM13, CN05, CN07, ADD03까지 추가
회복 후보가 될 수 있으나 현재는 자동 회복 수에 포함하지 않는다.

## 변경·검증 범위

- 코드 수정: 없음
- 이미지 재빌드/재시작: 없음
- 18002: 변경 없음
- 57건 full replay: 실행하지 않음
- 감사 산출물: 본 문서

이 문서는 기존 `CAPABILITY_DATA_AUDIT_PENDING_20261003.md`의 provisional reason을
덮어쓰지 않고, 실제 source 조회로 확정한 재분류 결과를 추가로 남긴다.
