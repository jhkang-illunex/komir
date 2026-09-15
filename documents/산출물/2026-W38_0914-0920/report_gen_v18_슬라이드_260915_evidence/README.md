# report_gen v18.pptx — 대상 5(광물지도-핵심광물지도(매장량) 내용 보강) evidence

산출물: `documents/산출물/2026-W37_0907-0913/요약분석_정리결과물/
분석요약_개선_결과작업_v18.pptx`(21슬라이드, git 미추적 — pptx 예외 원칙).
규칙은 v14~v17과 동일 — 기존 적색은 전부 흑색, **v17 결과와 다른 부분만 적색**.

사용자 지시(2026-09-15, 대상 5 광물지도 - 핵심광물지도(매장량)):
- 국가별 순위 및 변화에 상위 3개국 + 값 + 증감률 표출
- 주요 변화 중 크게 증가/감소한 국가 최소 2개 이상 표출 + 증가/감소 폭이 급격해진
  기간 표출(예: "2023~2025년 OOOO만톤(XX%)으로 급격히 상향되어")
- 상위 1위 국가 표출(단일 국가 기준) 총정리(예: "단일 국가 기준 1위인 칠레를
  상회하고 있어 복수의 중소 매장국에도 상당한 자원이 분포되어 있음을 알 수 있습니다")
- 내용이 부실 → 공단 템플릿(`AI 통계분석 요약답변_수급지도광물지도.pdf` §3)의 같은
  문단 참고해 보완

## 1. report_gen 변경(`inhouse/report_gen/app/analysis/`)

| 절 | 전(v17) | 후(v18) |
|---|---|---|
| 세계 매장량 현황 | current_state + period_total_change 2문장 | + `world_total_trend`: "연도별 세계 매장량 합계는 2021년 약 8.80억톤 → 2022년 약 8.90억톤 → 2023년 약 10억톤 → 2024년 약 9.80억톤 → 2025년 약 9.80억톤입니다." |
| 국가별 순위 및 변화 | 1·2·3위 값·비중 + 교차비교 | + `top3_period_change`: "조회기간(2021~2025년) 상위 3개국의 매장량 변화는 칠레 약 2억톤→약 1.80억톤(10% 감소), 호주 약 9,300만톤→약 1억톤(7.53% 증가), 페루 약 7,700만톤→약 8,500만톤(10.39% 증가)입니다." + `top3_concentration`: "상위 3개국의 매장량 집중도(CR3)는 37.24%이며, 상위 5개국까지 합산하면(CR5) 전체의 53.57%를 차지합니다." |
| 주요 변화 | 증가 1국·감소 1국 1문장(`extreme_change_countries`) | 방향별 상위 2개국, 국가당 1문장(`extreme_increase_1/2`·`extreme_decrease_1/2`) + 급변 구간("특히 2022년 약 3,100만톤에서 2023~2025년 약 8,000만톤(세계 비중 8.16%)으로 급격히 상향돼 변화가 집중됐습니다" / 중립형 "연도별로는 … 구간의 변화 폭이 가장 컸습니다") + `top_country_vs_others`: "기타 국가 합산은 2025년 약 2.10억톤(21.43%)으로, 단일 국가 기준 1위인 칠레(약 1.80억톤, 18.37%)를 상회하고 있어 복수의 중소 매장국에도 상당한 매장량이 분포돼 있습니다." |

- 구현은 전부 `summary.py` 후처리(append) — 프로즌 `additional_summary.py` 무수정.
  기타 국가 합산은 KOMIS 비중표(`komis_share_response`) `_ETC_` 행(`input_data.py::
  _parse_komis_map_mineral_share_others` 신설)에서 읽어 `is_other=True` 관측치로 얹는다.
- `report_render.py` 분리 절 설정을 evidence_id 튜플로, `models.py`
  MAJOR_CHANGES_MAX_SENTENCES 7→10, `prompts.py` MINERAL_MAP 문장수 범위 확대,
  프롬프트 `mineral_map_summary.md` 갱신 — **배포 시 seed_prompts 재실행 필요**.
- 테스트 18 passed(신규 `test_map_mineral_ranking_detail_and_major_changes`).
- 판단이 갈리는 점 7건(괄호 %의 뜻, "급격히" 임계값, 방향별 2개국, 총정리 위치, 기타
  국가 정의, 슬라이드 분량, 생산량 동일 적용)은 `../report_gen_피드백반영_애매사항_
  기록_260915.md` #10~#16.

## 2. 재현·검증

```
KOMIR_ROOT=/path/to/komir python3 <이 폴더>/refetch_v18_sources.py   # 입력·절차 v17과 동일
KOMIR_ROOT=/path/to/komir python3 <이 폴더>/build_v18_full.py        # v10.pptx 복사 → v18.pptx, v17.pptx 대비 적색
```
- `v18_sources.json` vs `v17_sources.json`(request_id 제외) 차이: `map_mineral_baseline_full`·
  `map_mineral_production` 2건뿐(core 2→3문장, major 4→10/3→9문장, observation_count
  +4/+5는 `_ETC_` 관측치, data_version). 나머지 19건 동일.
- 저장된 v18.pptx: 적색 6곳 = 슬라이드 20(매장량)·21(생산량)의 본문 문단 2(연도별
  합계)·4(상위 3개국 변화+CR3)·6(주요 변화). 템플릿 잔존 적색→흑색 67 run.
- **레이아웃 조정**: 본문이 v17 약 500자 → 약 1,400자로 늘어 12pt·5.12in 상자(아래로만
  자라는 spAutoFit)로는 슬라이드 아래로 넘친다(추정 46줄 ≈ 9in). 이 두 슬라이드만
  `rebuild_map_mineral_slide`에서 상자 폭을 표 직전까지(6.6in), 글꼴을 9pt로 줄였다
  (추정 26줄 ≈ 3.9in, 상자 top 2.1in → 6.0in 안). LibreOffice가 없어 렌더링 실측은
  못 했다 — PowerPoint에서 열어 넘침 여부 확인 필요.
