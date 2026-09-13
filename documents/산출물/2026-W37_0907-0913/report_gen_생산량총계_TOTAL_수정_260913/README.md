# map_mineral 세계총계 버그 발견·수정 (2026-09-13)

> 사용자 제보: "저기 생산량 총계가 따로 데이터로 제공되고 광물지도/동
> 2021~2025 생산량 총계가 23000000인데 보고서 요약으로 나온값과 다른데?"

## 원인

핵심광물지도(`map_mineral`)의 "세계 {광종} {매장량/생산량}" 헤드라인은
`additional_summary.py::_world_total()`이 계산하는데, 이 함수는 **지도
(`getListMapMnrlChartData`)에 개별 국가로 나열된 값만 더한 합계**였다.
KOMIS는 별도의 국가별 생산량/매장량 비중표(`getListMnrlTablePrdctnBurgudg`)
에서 **공식 세계총계(`_TOTAL_`, 코드 SU)** 와, 지도에 개별 표시되지 않는
**"기타국가"(`_ETC_`, 코드 OT)** 를 따로 내려준다 — 이 기타국가 생산량이
지도 합계에서 통째로 빠져 있었다.

동 2025년 생산량 기준:

| | 값 |
|---|---|
| 지도에 나열된 국가 합계(수정 전 report_gen 표시값) | 20,013,000 |
| KOMIS 공식 세계총계(`_TOTAL_`) | **23,000,000**(사용자 제보값과 일치) |
| 차액 ≈ 기타국가(`_ETC_`) | 3,000,000 |

## 87쌍 전수 스윕으로 확인한 사실

`income_data/komis/komis_08_mineral_map.json`(65광종×매장량/생산량,
실측치 있는 87쌍)을 전수 스윕한 결과, **지도합계가 `_TOTAL_`보다 컸던
경우는 단 1건도 없었다.** 32쌍은 `지도합계 + _ETC_ ≈ _TOTAL_`로 거의
정확히 일치, 49쌍은 기타국가가 0이라 이미 일치, 나머지는 오차범위 내.

이는 코드 3곳(`input_data.py`·`additional_summary.py`·`models.py`)에
남아 있던 기존 주석 — "`_TOTAL_`이 지도합계보다 체계적으로 4~11배
작다"(2026-08-31 기록) — 와 정반대다. 세 곳 모두 이 조사 결과로 정정
했다(당시 경위는 재현하지 않았으나, 이미 신뢰불가로 폐기된
`totalBurudgQuty`/`TOTALPRDCTNQUTY`류 필드와 혼동했을 가능성 — 그
필드는 "조회기간 전체 합산값"이라 연도별 분모로 못 쓴다는 게 앞서
확정돼 있었다).

## 수정 내용

- `input_data.py`: `_parse_komis_map_mineral_share_totals(raw, end_year)`
  신설 — `komis_share_response`의 `_TOTAL_`행(before1~5)에서 연도별
  공식총계 dict를 뽑는다. 응답 자체엔 연도 정보가 없어, chart·share
  엔드포인트가 항상 같은 `srchDateE`로 호출된다는 실측을 근거로
  `end_year`를 `before1`로 놓고 역산한다.
- `summary.py::_analyze_mineral_map`: 위 dict를 `is_total=True` 관측치로
  series에 얹는다. `additional_summary.py::_world_total()`은 이미
  "official(`is_total=True`) 관측치가 있으면 그걸 우선 쓴다"는 폴백을
  갖고 있었다(2026-09-09에 다른 신뢰불가 필드 때문에 꺼져 있었을 뿐) —
  **계산 함수 자체(frozen)는 무수정**, 값을 흘려보내는 입력 계층만 고쳤다.
  조회기간이 5년보다 넓어 `before5`보다 과거 연도가 있으면 그 해는
  자동으로 기존 지도합계 폴백을 그대로 탄다(5년 창 안에서는 시작·현재
  연도 모두 `_TOTAL_` 기준이라 변화율 계산도 일관됨 — 혼합 분모 문제
  없음, 직접 확인).

## 검증

1. `python3 -m unittest discover -s tests` — 14/14 PASS.
2. `scripts/komis_dump_smoke_test.py` — 395콤보, map_mineral 104/104 ok,
   mismatch 0.
3. `verify_world_total.py`(이 폴더) — report_gen 자신의 파서를 재사용
   하지 않고 원본 JSON에서 `_TOTAL_`(before1)을 독립 재계산해 대조.
   **87/87 일치**(0 mismatch).
4. 재배포(`docker build`+컨테이너 교체+`seed_prompts`+`/admin/prompts/
   reload`) 후 실 HTTP 라이브 확인: 동 생산량 2021~2025 →
   "2025년 세계 동 생산량은 약 2,300만톤" + 칠레 1위 23.04%. KOMIS
   자체 `rate` 필드(칠레 23.04%)와 정확히 일치 — 수정 전엔 26.48%로
   어긋났었다.

## 영향 범위 및 v10.pptx 반영

`_world_total()`은 헤드라인 총계뿐 아니라 조회기간 변화율(%)·CR3/CR5·
1위국 비중 등 map_mineral 수치 전부의 분모다. `요약분석_정리결과물/
분석요약_개선_결과작업_v10.pptx` 슬라이드18(baseline)·19(교차비교)·
20(생산량버그확인)이 전부 수정 전 값으로 박제돼 있어 수정된 API로
재조회해 갱신했다(동 매장량 9.80억톤, 생산량 2,300만톤). zip 무결성·
재오픈·red-run 0건 확인.

## 재현

`verify_world_total.py` — 단독 실행 가능(`python3 verify_world_total.py`,
inhouse/report_gen을 sys.path에 추가해 실제 서비스 코드 직접 호출).
