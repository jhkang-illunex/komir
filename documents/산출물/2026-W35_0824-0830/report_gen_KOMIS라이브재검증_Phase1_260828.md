# KOMIS 라이브 재검증 Phase 1 — price_base_metals 기준점 구현 (2026-08-28)

## 배경
`report_gen_price_base_metals_부실요약_원인조사_260828.md`에서 확정한
KOMIS `dataAvg.stdMap.{WEEK,MONTH,YEAR}` 패스스루 설계를 실제로 구현하고,
승인받은 3개 항목(1: stdMap 패스스루, 2: 재고량 지원, 3: 정적 덤프 재수집)
+ 검증(4)까지 완료했다. Phase 2(price 나머지 3종)·Phase 3(map 3종)·
Phase 4(indicator_composite·forecast_price)는 아직 손대지 않았다 —
이 문서는 Phase 1만 다룬다.

## 1) stdMap 패스스루 구현
- `models.py`: `PriceKomisPeriodAverage`/`PriceKomisPeriodComparisons` 신설,
  `AnalysisSummaryRequest.komis_period_comparisons: dict | None`(price_* 4종
  전용, geo_events와 같은 검증 패턴) 추가.
- `komir_summary.py::calculate_price_summary`: week/month/year 루프에서
  `komis_period_comparisons`에 해당 기간이 있으면 그 값을 그대로 쓰고(자체
  롤링창 재계산·희소관측 dedup 스킵), 없으면 기존 `_avg_before()` 폴백 —
  **기간별 독립 판단**이라 혼합 케이스(예: week만 KOMIS 제공, month/year는
  폴백)도 정상 동작(직접 재현 확인).
- `summary.py`: `_komis_period_comparisons_from_request()` 신설(geo_events
  helper와 동일 패턴), `_analyze_price`에 배선.
- `routers/analysis.py`: `MineralDateRangeSummaryRequest`에 같은 필드 미러링
  (라우터→`AnalysisSummaryRequest` 조립이 `model_dump()` 스프레드 방식이라
  이름이 같아야 전달됨 — geo_events 때와 같은 필수 조건).
- `prompts.py`: week/month/year 문장 템플릿은 무수정(KOMIS 제공값이든
  자체계산이든 같은 문장 형태라 LLM 지침 변경 불필요).
- DAY는 패스스루 대상에서 뺐다 — 이 계산기가 인접 관측치로 직접 계산한
  day_over_day가 이미 KOMIS와 일치함을 원인조사에서 확인했기 때문(재계산할
  필요 없는 값은 옮기지 않는다는 원칙).

## 2) 재고량(inventory) 지원 추가
- `komir_summary.py::calculate_price_summary`: `current_position`에
  `inventory_level` 근거 추가 — latest 관측치의 inventory + (있으면) 가장
  최근 inventory-보유 이전 관측치 대비 등락(`observations[-2]`가 아니라
  "latest 이전 중 inventory가 있는 가장 최근 관측"을 찾는다 — 재고량은
  가격과 달리 결측 가능성이 있어서, 이 방식으로 하지 않으면 조용히 누락됨).
- **KOMIS `invtPrcnt`와의 일치를 실측으로 검증**(passthrough 아님, 자체
  계산): 라이브 캡처 동(673행) 전수 대조 결과 672/672 정확히 일치
  (day_over_day 가격과 같은 이유 — 둘 다 "인접 관측치 직접 비교"라 KOMIS의
  일별 등락 산식과 원래 같다. WEEK/MONTH/YEAR와 달리 재구현이 필요 없는
  케이스임을 확인 후 이 방식을 택함).
- 문장에 "LME"·"톤" 등 단위·거래소를 하드코딩하지 않았다 — 기존
  `day_over_day` 등 다른 가격 지표도 문장에 단위를 안 쓰는 것과 같은 관행을
  따름(price_minor_metals/iron_energy/other는 LME 기준이 아닐 수 있어
  하드코딩하면 거짓 문장이 될 위험).
- `current_position` 하드 캡(models.py `SummaryNarrative.current_position`
  max_length=3)과의 충돌 여부 확인: 이 섹션에 들어갈 수 있는 근거는
  period_range/no_price_range(1) + compare_overall_change(price_minor_metals
  전용, 1) + inventory_level(1) = 최대 3으로 정확히 캡과 같다 — room 가드
  (`current_position_count < 3`)를 넣어 안전하게 처리, 3종 claim이 동시에
  있는 경계 케이스(price_minor_metals + 비교광종 + inventory)를 실제로
  재현해 크래시 없음을 확인(아래 검증 참고).
- `prompts.py::PRICE_SUMMARY_INSTRUCTIONS`에 `inventory_level` 근거 사용
  지침(있으면 그대로 옮기고 단위·거래소 지어내지 않기, 없으면 언급하지
  않기) 추가.

## 3) 정적 덤프 재수집
`income_data/komis/komis_01_base_metals.json`(gitignore 영역, 로컬 전용)에서
니켈 외 5광종(동·아연·알루미늄·연·주석)의 `getMnrlPrcByMnrkndUnqCd`
DAY 콤보가 전부 0행이던 문제(원인조사에서 발견)를 해결했다. 레포에
수집 스크립트가 없어(검색 결과 無) Playwright로 새로 라이브 재수집(11건,
전부 673행) 후 해당 응답만 덤프 파일에 패치 — 원본이 없던 "주석|LME 15개월"
조합도 신규로 확보됐다. 원본 캡처는
`report_gen_KOMIS라이브재검증_Phase1_260828_evidence/recollected_base_metals_day_raw_260828.json`에
보존.

**부수 발견·수정**: 재수집 데이터로도 회귀 스위트를 정상 검증하려면
`komis_dump_smoke_test.py::adapt_price_pages()`의 하드코딩된
`"page_id": "price"`(2026-08-27 `price_base_metals`/`price_minor_metals`
분리 이후 무효 리터럴 — 원인조사에서 이미 확인했던 "니켈 외 internal_error
58건"의 진짜 원인)를 `page_id` 파라미터로 바꿔 호출부에서
`"price_base_metals"`/`"price_minor_metals"`를 넘기도록 고쳤다. 하네스
스크립트 전용 수정이며 report_gen 프로덕션 코드와는 무관.

## 4) 검증
### 4-1. 라이브 재현(스크린샷과 재대조) — 완전 일치
`komis_dump_smoke_test.py` 재실행 결과, 동|LME 3개월 표본(가장 최근 값 기준)의
`report_markdown`:
```
전일(2026년 8월 26일) 대비 -0.70% 변동했다.
전주평균(14,098.10) 대비 +0.98% 수준이다.
전월평균(13,543.93) 대비 +5.11% 수준이다.
전년평균(9,966.51) 대비 +42.84% 수준이다.
... (중간 "조회기간 중 최고 10,930.00, 최저 8,191.00였다" 문장은 아래
"남은 한계" 3번째 항목 참고 — 이 검증의 성공 근거가 아니라 별도로 발견한
품질 문제다)
2026년 8월 27일 기준 재고량은 235,575.00이다. 전일(2026년 8월 26일) 대비 -0.80% 변동했다.
```
스크린샷 수치(-0.70%/+0.98%/+5.11%/+42.84%)와 **소수점 둘째자리까지 정확히
일치** — 이번엔 실제 어댑터→계산기 파이프라인 전체를 통과한 결과다(원인조사
때는 손으로 만든 재현 스크립트였다).

### 4-2. 회귀 스위트 전수 재실행 — 6광종+34희소금속 실측 대조
패치 전/후 대조:

| | 패치 전(원인조사 문서 기록) | 패치 후 |
|---|---|---|
| price 계열 internal_error | 58건(니켈만 검증되던 상태) | **0건** |
| price_base_metals ok/count | (page_id 무효라 전량 실패) | **13/13** |
| price_minor_metals ok/count | 56/56(기존에도 정상) | 56/56 |
| price 계열 mismatches | 검증 자체가 안 됨 | **0건**(week/month/year를 KOMIS stdMap 기대값과 대조하는 신규 체크 포함) |
| 전체 8개 페이지 internal_error | 58 | **0** |

`_check_mismatch`에 `week_avg_change_pct`/`month_avg_change_pct`/
`year_avg_change_pct`를 KOMIS `stdMap` 기대값과 대조하는 체크를 신규로
추가했다 — 이번 재실행에서 **6개 비철금속 + 34개 희소금속(가격기준별
콤보 총 69건)이 이 체크를 전부 통과**했다(0 mismatches, tol=0.02%p).
전체 요약·표본 2건은
`report_gen_KOMIS라이브재검증_Phase1_260828_evidence/`에 보존(META.md 동봉).

### 4-3. 경계 케이스 재현 — 크래시 없음
- 혼합 케이스(week만 KOMIS 제공, month/year는 폴백): 정상 동작, 각 기간
  독립적으로 처리됨을 확인.
- `komis_period_comparisons` 없음(하위호환 폴백): 기존과 동일하게 롤링창
  값(전주 +0.13%) 산출 — 회귀 없음.
- `current_position` 3-claim 동시 발생(price_minor_metals + 비교광종 +
  inventory_level): 실제 재현 결과 크래시 없이 정상 렌더링.

## 파일 변경 목록
- `inhouse/services/report_gen/app/analysis/models.py`
- `inhouse/services/report_gen/app/analysis/komir_summary.py`
- `inhouse/services/report_gen/app/analysis/summary.py`
- `inhouse/services/report_gen/app/analysis/prompts.py`
- `inhouse/services/report_gen/app/routers/analysis.py`
- `inhouse/services/report_gen/scripts/komis_dump_smoke_test.py`(하네스 전용)
- `income_data/komis/komis_01_base_metals.json`(gitignore, 로컬 데이터 패치 — 레포 커밋 대상 아님)

## 남은 한계·확인 필요 사항
- 재고량 `invt` 결측이 KOMIS에서 "0.00"으로 오는지("가격 필드처럼 결측=0
  관행"인지) 아니면 필드 자체가 없는지는 **동·니켈 673행에서 0 발생이
  전혀 없어 판별 불가**였다 — 두 광종 모두 재고 추적이 활발해 결측 사례가
  없었을 뿐일 수 있다. price_minor_metals/iron_energy/other로 확장 시
  실제 0 값이 나오면 재검증 필요(현재 코드는 `_nonzero` 게이트를 재고량에
  적용하지 않았다 — 가격과 달리 재고 0톤은 물리적으로 가능해서, 섣불리
  결측 취급하면 반대로 문제가 될 수 있어서다).
- `komis_period_comparisons.average_price`는 KOMIS 응답에 직접 없어
  `latest_price - flctnPrc`로 역산한다(어댑터·라이브 검증 스크립트 둘 다
  같은 방식) — 이 역산 자체가 항상 맞는지는 별도로 검증하지 않았다(다만
  검증 4-2에서 change_pct 자체는 광범위하게 대조했으므로, 문장에 노출되는
  등락률 숫자는 신뢰할 수 있다 — average_price는 문장에만 쓰이고 별도
  key_metric 검증 대상은 아니었다).
- **(3, 신규 발견) `period_range`(조회기간 최고·최저) 문장이 최근 데이터에서
  깨진다** — 동 표본의 "조회기간 중 최고 10,930.00, 최저 8,191.00였다"는
  현재가(14,236.00)보다도 낮다. 원인 확인: KOMIS가 최근 구간(2026년)의
  `hghstPrc`/`lowstPrc`를 `0.00`으로 보내고, 이 계산기의 `_nonzero()`가
  `0.00`을 결측으로 걸러내면서 `period_range`가 초기 구간(2024년 초, 실제
  값이 있던 시기)의 값만으로 계산돼 최근 실거래가보다 낮은 "최고가"가
  나온다. **내 이번 변경이 만든 버그는 아니지만**(이 계산 로직은 그대로다),
  Phase 1이 처음으로 이 페이지에 KOMIS 실데이터 전 구간(1987~2026)을 흘려
  보내면서 실제로 드러난 품질 문제다 — 이전엔 짧은 관측치로만 테스트해
  안 보였다. 발주처가 보면 "숫자가 깨졌다"고 읽을 만한 문제라 Phase 2
  지시에서 처방 여부를 결정해야 한다(처방 후보: period_range를 hghst/lowst
  대신 commerce_price의 min/max로 폴백, 또는 hghst/lowst가 전부 결측인
  구간이 섞이면 그 사실을 명시하는 문장으로 대체 — 결정은 main-agent 몫,
  코드는 아직 안 건드림).

Phase 2(price_minor_metals/iron_energy/other에 같은 stdMap 구조가 그대로
적용되는지)는 이미 이번 회귀 스위트에서 부분적으로 검증됐다(4-2의 34개
희소금속 콤보가 전부 통과) — 다만 사용자가 요청한 "라이브로 재확인"은
정적 덤프가 아니라 실시간 접속 기준이라, Phase 2 보고에서 별도로
라이브 재확인을 추가할지 확인이 필요하다.
