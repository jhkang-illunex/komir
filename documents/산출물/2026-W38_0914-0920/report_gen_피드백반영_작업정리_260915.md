# report_gen 발주처 피드백 대상 1~6 반영 — 작업 정리(2026-09-15)

워크트리 `report-summary`(브랜치 `worktree-report-summary`)에서 하루 동안 진행한
발주처 피드백 반영 작업의 총정리. 상세 경위는 `documents/meta/WORKLOG.md` 2026-09-15
항목(대상별 7건), 판단이 갈린 점은 `report_gen_피드백반영_애매사항_기록_260915.md`
#1~#21, 슬라이드 재현은 `report_gen_v14~v19_슬라이드_260915_evidence/`가 정본이다.

## 1. 결과 요약

| 항목 | 상태 |
|---|---|
| git | 워크트리 커밋 13건 → `origin/main` fast-forward 푸시 → 본 저장소 main에서 mnrl_report 미커밋분과 병합(`5b47c03d8`, 사용자 실행). origin/main = 본 저장소 main = 워크트리 = `5b47c03d8` |
| API 배포 | `komir-report-gen:260915-mapmineral-years`(포트 18003) 가동 중. seed_prompts 13건 재시드·reload 완료, 실 HTTP 라우트로 라이브 확인 |
| 슬라이드 | `요약분석_정리결과물/분석요약_개선_결과작업_v19.pptx`(최종, v13 대비 누적 적색 36곳), v18은 대상 5 단계본. pptx는 git 미추적 |
| 테스트 | `inhouse/report_gen/tests` 20 passed(신규 4건) + 정적 덤프 440건 스윕(예외 0) |
| 잔여 | streamlit(8501) 재기동(광물지도 연도 연동 반영), 애매사항 #1~#21 발주처 확인, v19.pptx 넘침 여부 PowerPoint 실열람 |

## 2. 대상별 반영 내용

| 대상 | 발주처 요청 | 반영(코드) | 슬라이드 |
|---|---|---|---|
| 1 광물자원가격 비교광종 | 가격비율 표기 3건 | `komir_summary._relative_value_fact`: 비율·평균 %, "니켈 대비 동의 가격비율" | v14 |
| 2 광물종합지수 | 전주·전월·전년 대비 + 평균 지수, "구성 광종(가중치)은" | `summary._append_composite_period_average`(조회기간 평균 지수 metric), 문구 교체. 전주·전월·전년은 코드가 이미 계산 — 호출 측 조회 창(1년 이상) 문제 | v15 |
| 3 국내수급지도 | "수입 집중도(CR3)" 표기 | `komir_summary` import_concentration 문장 | v16 |
| 4 글로벌수급지도 | "KOMIS 차트 기준" 접두어 삭제 | `komir_summary` country_yearly_trend | v17 |
| 5 광물지도-매장량 | 상위 3개국 값+증감률 / 증감 국가 2개 이상+급변 기간 / 1위 vs 기타 총정리 / 내용 보강 | `summary.py` 후처리 신설: `top3_period_change`·`top3_concentration`·`extreme_increase_1/2`·`extreme_decrease_1/2`(+`_mineral_map_sharpest_interval`)·`top_country_vs_others`(KOMIS 비중표 `_ETC_`)·`world_total_trend` | v18 |
| 6 광물지도-생산량 | 생산 집중도(CR3) 해석 / 조회기간 추세·상승하락 / 매장량 대비 생산량 비율 낮은·높은 국가 / 변동폭 국가 / 내용 보강 | CR3 해석 구절·순위 표기, `world_total_recent_trend`(±2% 보합), `reserve_production_ratio_low/high`(순위 차 2계단, 프로즌 cross_measure_comparison 대체), `volatility_country`(양방향 국가만) | v19 |

공통: 프로즌 계산기 `additional_summary.py`는 무수정(전부 `summary.py` append 후처리),
`report_render._MAJOR_CHANGES_SPLIT_SECTIONS` 튜플화, `MAJOR_CHANGES_MAX_SENTENCES` 7→12,
`prompts.py` MINERAL_MAP 문장수 범위 확대, 프롬프트 md 갱신(→ seed_prompts 재실행 필요, 완료).

## 3. 사용자 확인 질문에서 나온 후속 변경

- **"복붙만 한 거 맞지요?"** → 본문은 API 렌더 결과와 문자 단위 동일. 표는 API 값+스크립트
  포매터였고 유일한 차이(API "약 9.80억" vs 슬라이드 "약 9.8억")를 지시로 해소:
  `map_presentation.compact_quantity`에 `_trim_trailing_zero` 적용 → 지도 3페이지 본문·표
  전부 "소수점 3자리에서 반올림, 2자리 표시, 끝자리 0 생략"으로 통일(`ec41f0960`).
- **"v19는 v13 이후 모든 수정 누적 적색"** → 대조 기준 v18→v13(`96bc95d27`), 이후 트림 반영으로 36곳.
- **"광물지도 HTTP API에 조회연도 추가"** → `MineralMapSummaryRequest`에 `start_year`/`end_year`
  복원(2026-08-30 제거분), 재배포 `260915-mapmineral-years`(`09fd38a83`).
- **"streamlit 후속 연결, 기본값"** → `views/report_demo.py` map_mineral 연도 콤보박스(기본
  2021~2025)를 payload에도 실음(`67da856ae`). 가동 중 streamlit은 재기동 필요.

## 4. 검증 기록

- 요청 항목 ↔ 현재 출력 대조 39개 검사(대상 1~6, v19 소스 21건): 요청 항목 전부 충족.
  스크립트 FAIL 4건은 검사식이 "현재"라는 단어를 예상 못 한 오판.
- 정적 덤프 65광종×매장량/생산량×스냅샷 유무×전기간/2년 = 440건: 정상 416, 기존 NO_DATA
  조건 24(국가 3개 미만·연도 1개), 예외·300자 초과·비격식 종결 0. 스윕에서 발견한 결함
  1건(스트론튬 생산량, 옛 교차비교 문장 방향 뒤집힘) → 낮은 국가 문턱 3→2계단으로 수정.
- 슬라이드 입력 교정: v13~v18의 교차비교 스냅샷이 다년 합산 덤프(호주 생산량 575만톤)였음
  → v19부터 chart 2025년 행 단일연도 스냅샷(73만톤·3.17%, 템플릿 일치).
- 라이브: 배포 컨테이너 실 HTTP 라우트로 매장량·생산량·국내수급지도 호출, 2019~2025 응답에
  start_year 2021을 넣어 "2021년보다 … 4년간" 확인, Swagger에 연도 필드 노출 확인.

## 5. 알려진 한계·주의

- 템플릿과의 산식 차이: 기간 표기 "4년간"(코드) vs "5년간"(템플릿, 프로즌 문구). 동 생산량
  변동폭 국가가 러시아(31.54%)로 템플릿 인도네시아(약 25.5%)와 다름(템플릿 산식 미확인).
- 반대 measure 스냅샷은 단일연도 응답이어야 함(다년이면 KOMIS가 합산값을 줌). 반대 measure
  비중의 분모는 스냅샷 국가 합계(공식 총계 없음).
- 워크트리 세션은 본 저장소 git 작업이 불가(사용자 `!` 명령도 차단) — 별도 터미널 안내로 해결.
