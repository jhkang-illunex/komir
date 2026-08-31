# report_gen — price_base_metals 정의문 "최고가·최저가" 삭제 (2026-08-31)

## 배경
사용자가 광물자원가격 분석요약 실측 피드백에서 지적: 보고서 첫 줄(페이지
정의문)이 "실거래가·최저가·최고가 추이"라고 말하지만, 실제로는
`hghstPrc == lowstPrc == cmercPrc`가 100%이고 2025년 이후 행은 아예
0.00 — 최고가·최저가 컬럼이 정보량 0이라는 지적.

## 실측 검증
`income_data/komis/komis_01_base_metals.json`(실제 KOMIS API 덤프,
121개 요청 결과)로 hi/lo/close 일치율을 집계:

| 계열 | 단위 | non-zero 행 | hi==lo==close |
|---|---|---|---|
| 니켈\|LME CASH | DAY | 5,794 | 5,794 (100%) |
| 니켈\|LME CASH | WEEK | 1,198 | 1 |
| 니켈\|LME CASH | MONTH/QUARTER/YEAR | 276/92/23 | 0 |
| 니켈\|LME 3개월 | DAY | 5,035 | 5,035 (100%) |

→ **DAY 단위에서만, 그리고 LME 계열에서만** 발생. WEEK 이상 집계에서는
정상적으로 서로 다른 고가·저가가 나온다(그 구간 내 여러 날의 값을
집계하니 당연히 달라짐) — LME 현물가는 하루에 정산가 1개뿐이라 일별
고가/저가 개념 자체가 없는 구조적 특성으로 보인다.

`income_data/komis/komis_02_minor_metals.json`로 희소금속(가돌리늄
DAY 3,132행 중 non-zero 167행, 갈륨 DAY 6,860행 중 non-zero 6,841행)을
같은 방식으로 검사한 결과 **hi==lo==close 0건** — 희소금속은 실제로
서로 다른 고가·저가 데이터를 갖고 있다. 즉 이 결함은 **비철금속(LME)
DAY 계열에 한정**되고, 희소금속에는 없다.

철광석·에너지(price_iron_energy)·기타(price_other, 금·은·백금족·흑연)는
원천 덤프 파일이 없어 이번에 검증하지 못했다 — **추정으로 같은 수정을
적용하지 않았다.**

## 변경
`app/analysis/komir_summary.py::KOMIR_PAGE_CONTEXTS["price_base_metals"]`
의 `definition`에서 "최저가·최고가"를 제거:

- 이전: "선택한 비철금속(LME 기준)의 일별 실거래가·최저가·최고가
  추이를 보여주는 자료다."
- 이후: "선택한 비철금속(LME 기준)의 일별 실거래가 추이를 보여주는
  자료다."

`price_minor_metals`(정상 데이터 확인됨)·`price_iron_energy`·
`price_other`(미검증)는 그대로 둠.

## 왜 본문 계산(period_range)은 이미 안전했는가
`calculate_price_summary`의 `has_full_hilo_coverage`(2026-08-30 "0.00
오염" 수정 때 만든 값기반 게이트)가 관측치 전체에 고가·저가가 빠짐없이
있을 때만 "최고 X, 최저 Y" 문장을 쓰고, 하나라도 없으면(이번 사례처럼
0.00이 섞이면) "조회기간 관측치(실거래가) 기준"으로 자동 폴백한다 —
**이 로직은 이미 값 기반이라 페이지·계열에 상관없이 정확했다.** 이번에
고친 건 그 동적 판단과 별개로 정적으로 박혀 있던 정의문 한 줄뿐이다.

## 검증
- `KOMIR_PAGE_CONTEXTS["price_base_metals"].definition` import 재확인.
- `scripts/komis_dump_smoke_test.py` 회귀 395콤보(8페이지) 전부
  mismatch 0 유지.

## 남은 작업 (별도 후속, 이번 커밋 범위 아님)
사용자가 같은 피드백에서 요청한 8개 통계 확장 레이어(변동성·추세위치
MA/RSI·백분위·낙폭국면(MDD)·재고 해석·상대가치(Cu/Al)·연도별
수익률표·계절성)는 이 커밋과 분리해 별도로 계획 확인 후 진행한다.

## 커밋
`app/analysis/komir_summary.py` — main-agent 승인 후 재빌드·재기동 필요.
