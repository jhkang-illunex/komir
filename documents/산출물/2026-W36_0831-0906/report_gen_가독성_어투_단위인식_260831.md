# report_gen — 현재 위치 가독성·정의문 어투·조회단위(주/월/분기/년) 인식 (2026-08-31)

## 배경
통계확장 8개층 라이브 검증 후 사용자 피드백 3건:
1. "현재 위치에 해당하는 문구가 많은건 좋은데 읽기 힘듭니다. 적절히
   문장을 자르는게 필요."
2. 제목 어투 통일: "일별 실거래가 추이를 보여주는 자료다" → "…자료입니다".
3. "실 데이터 간격이 다르면 주, 월, 분기, 년 단위 구분한 자료를 인식
   할 수 있나요?"

## 1) 가독성 — current_position 4문장 초과 시 목록(bullet) 렌더링
`app/analysis/report_render.py::render_markdown_report` — 기존엔 절 안의
모든 문장을 공백으로 이어붙여 한 문단으로 렌더링했다(3~5문장까지는
괜찮았지만 current_position이 최대 9문장까지 늘면서 가독성이 떨어짐).
`current_position`이 3문장 초과일 때만 `- 문장` 형태의 목록으로 바꾼다
(core_diagnosis·major_changes는 문장 수가 적고 의도적으로 서술 흐름을
잇는 절이라 문단 형태 유지).

## 2) 어투 통일 — 정의문 "…다." → "…입니다."
LLM 정제 본문은 이미 "-습니다"체(폴리트)로 쓰이는데 정적 정의문(제목
줄)만 "-다"체였다. `page_definition` 원문(`komir_summary.py`의
`KOMIR_PAGE_CONTEXTS`·외부repo "무수정 이식"인 `additional_summary.py`의
`ADDITIONAL_PAGE_CONTEXTS`)은 손대지 않고, **렌더링 시점**에
`report_render.py::_to_polite_copula()`로 변환한다 — 정의문 11종이
전부 "…(명사)다." 계사 종결형이라(예: "자료다"="자료"+"이다") "다."→
"입니다."가 정확한 변환이다(일반 한국어 활용 변환이 아니라 이 특정
종결형에만 적용). `additional_summary.py`를 직접 고치지 않아 "무수정
이식" 불변식을 지킨다.

## 3) 조회단위(DAY/WEEK/MONTH/QUARTER/YEAR) 인식
### 3-1. 진짜 버그 발견 — MONTH/QUARTER/YEAR 조회가 아예 동작 안 하고 있었다
`app/analysis/summary.py::_komis_crtr_ymd_to_date`가 KOMIS `crtrYmd`를
항상 "YYYYMMDD"(8자리)로 가정하고 `s[6:8]`로 슬라이스했다. 실측
(`income_data/komis/komis_01_base_metals.json`) 결과 KOMIS는 조회단위별로
형식이 전부 다르다:

| 단위 | crtrYmd 예시 |
|---|---|
| DAY/WEEK | `"20260825"`(8자리) |
| MONTH | `"202608"`(6자리) |
| QUARTER | `"2026.3Q"` |
| YEAR | `"2026"`(4자리) |

MONTH/QUARTER/YEAR는 `s[6:8]`가 빈 문자열이 되어 `"2026-08-"`처럼 깨진
날짜가 나갔고, `PriceObservation.date`의 `Day` 패턴 검증(`^\d{4}-...`)에
걸려 **그 요청 전체가 실패**했다 — 즉 지금까지 월/분기/년 단위로 가격을
조회하면 항상 실패하고 있었다(회귀 하네스가 DAY/WEEK 표본만 써서 이
결함이 안 드러났었다). 4가지 형식 전부 정규화하도록 수정 — MONTH는
그 달 1일, QUARTER는 그 분기 첫 달 1일(Q1→01월/Q2→04월/Q3→07월/
Q4→10월), YEAR는 1월 1일로 대표일을 잡는다(실제 관측일이 아니라
간격판별·정렬용 근사치).

### 3-2. 통계 확장 6개층의 일간(daily) 암묵 가정 제거
`app/analysis/komir_summary.py::_detect_granularity` 신설 — 관측치
날짜 간격의 중앙값으로 일/주/개월/분기/년을 판별하고, 그에 맞는 연간
관측 횟수(252/52/12/4/1)를 돌려준다.
- **변동성**(`_volatility_fact`): 연율화 계수를 하드코딩 √252 대신
  판별된 `periods_per_year`로 계산.
- **이동평균+RSI**(`_ma_rsi_fact`): "20일선"/"14일 기준" 같은 하드코딩
  라벨을 판별된 단위로("20주선"/"14개월 기준" 등) 표시.

**이번에 안 한 것(설계 결정 필요, 다음 확인 필요)**: 이동평균 창
크기(20/60/120/250)·RSI 기간(14) 자체는 "관측치 개수" 기준 그대로다 —
예를 들어 주간 데이터의 "20주선"은 일간의 "20일선"(약 1개월)과 실제
걸치는 기간이 다르다(20주≈4.6개월). 창 크기를 단위별로 다시
캘리브레이션(예: 주간은 4/13/26/52주, 월간은 1/3/6/12개월처럼 일간의
1개월/3개월/6개월/1년과 시간상 동등하게)할지는 별도 확인이 필요하다.

## 검증
- 회귀 395콤보 mismatch 0 유지(이 하네스는 DAY/WEEK 표본만 써서
  MONTH/QUARTER/YEAR 커버리지는 없음 — 아래 실측으로 별도 확인).
- 실측(니켈, income_data 5개 조회단위 전부) — DAY/WEEK/MONTH/QUARTER는
  `_parse_komis_price_response`부터 계산까지 정상 동작 확인(수정 전엔
  MONTH/QUARTER/YEAR가 날짜 파싱 단계에서 전부 실패했음). YEAR는
  관측치가 25건뿐이라 MA20 1개만 계산 가능해(정배열 판단엔 2개
  이상 필요) 이동평균 서술은 생략되고 RSI만 나옴 — 설계된 대로 동작.

## 커밋
`app/analysis/report_render.py`·`app/analysis/komir_summary.py`·
`app/analysis/summary.py` — main-agent 승인 후 재빌드·재기동
(+ `seed_prompts` 재실행은 이번엔 output_contract를 안 건드려 불필요)
필요.
