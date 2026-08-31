# report_gen — srchAvgOpt/srchField/srchStartDate/srchEndDate 명시 입력 (2026-08-31)

## 배경
직전 커밋(`d04062eb8`, `report_gen_기간커버리지_게이트_260831.md`)에서
"평균옵션을 별도 입력으로 새로 받기보다 관측치 자체의 실제 폭으로
판단한다"고 결정했는데, 사용자가 바로 후속 지시를 줬다:

> 평균옵션 : srchAvgOpt DAY, WEEK, MONTH, QUATER, YEAR
> 기간 구분자 : srchField, year, month
> 월간 기간 시작/종료 : srchStartDate/srchEndDate yyyy-mm
> 년간 기간 시작/종료 : srchStartDate/srchEndData yyyy
> 이걸 입력으로 받게 할 예정입니다.

즉 추론이 아니라 KOMIS 조회 파라미터 그대로를 명시 입력으로 받길
원한다 — 이전 결정을 뒤집는 요청이라 그대로 반영한다(추론은 fallback
으로 유지).

## ⚠ 이전에 제거된 start_date/end_date와 다른 점
`_DateRangeMineralRequest`의 `start_date`/`end_date`는 2026-08-30에
"이미 komis_response로 받은 시계열을 사후에 다시 좁히는 중복 필터"라는
이유로 제거됐다. 이번 4개 필드는 다르다 — **observations를 다시
잘라내지 않는다**, 계산 로직(기간 커버리지 판단·이동평균/RSI/변동성
단위 라벨)에만 쓰는 **메타데이터**다. "무엇을 보여줄지"가 아니라
"보여주는 값을 어떻게 해석할지"를 결정한다 — 그래서 같은 "중복 필터
금지" 원칙에 안 걸린다(코드 주석에도 이 구분을 명시해뒀다).

## 구현
`app/routers/analysis.py::PriceSummaryRequest` + `app/analysis/models.py::
AnalysisSummaryRequest`에 4개 필드 추가(price_* 4종 전용, page_id 검증):
- `srch_avg_opt: Literal["DAY","WEEK","MONTH","QUARTER","YEAR"] | None`
- `srch_field: Literal["year","month"] | None`
- `srch_start_date`/`srch_end_date: str | None` — `srch_field="year"`면
  `YYYY`, `"month"`면 `YYYY-MM` 형식만 허용(정규식 검증), `srch_field`
  없이 날짜만 주면 거부, start>end면 거부.

`komir_summary.py::calculate_price_summary`가 이 4개를 새 kwarg로
받아:
1. `srch_avg_opt`가 있으면 `_detect_granularity`가 날짜간격 추론 대신
   바로 그 값을 쓴다(변동성 연율화 계수, 이동평균/RSI 단위 라벨).
2. `srch_field`+`srch_start_date`+`srch_end_date`가 있으면
   `_requested_span_days()`로 계산한 캘린더 일수를 전주/전월/전년
   비교의 기간 커버리지 게이트(`total_span_days`)에 쓴다 — 없으면
   기존처럼 `observations`의 실제 날짜 폭으로 대체(하위호환).

둘 다 "명시 입력이 있으면 우선, 없으면 추론"이라 기존 동작은 안
깨진다(하위호환) — 다른 자동채움+오버라이드 필드들과 같은 패턴.

## 검증
- pydantic 검증 5종(정상/형식오류/page_id제한/srch_field누락/
  start>end) 전부 의도대로 통과·거부 확인.
- 실측(니켈, 24년치 6,227건 관측치를 그대로 두고 `srch_field=month,
  srch_start_date=srch_end_date="2026-08"`로 "실제 조회기간은 1개월"만
  명시) — 관측치엔 24년치 데이터가 있는데도 **명시된 조회기간을
  존중해 전년평균 대비가 정확히 생략**됨(observations가 아니라 명시
  입력이 우선한다는 것 확인) + 사유 warnings 기록.
- 회귀 395콤보 mismatch 0 유지.

## 커밋
`app/routers/analysis.py`·`app/analysis/models.py`·
`app/analysis/summary.py`·`app/analysis/komir_summary.py` — main-agent
승인 후 재빌드·재기동(seed_prompts 불필요, output_contract 미변경).
