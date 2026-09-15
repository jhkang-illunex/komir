# report_gen v15.pptx — 대상 2(광물종합지수) 피드백 반영분 적색 표시 evidence

산출물: `documents/산출물/2026-W37_0907-0913/요약분석_정리결과물/
분석요약_개선_결과작업_v15.pptx`(21슬라이드, git 미추적 — pptx 예외 원칙).
규칙은 v14와 동일 — 기존 적색은 전부 흑색, **v14 결과와 다른 부분만 적색**.

사용자 지시(2026-09-15, 대상 2 광물종합지수 - 광물전망지표):
- 전주 대비, 전월 대비, 전년 대비 증감률, 평균 지수 표출(현재 전주 대비만 표출).
- "구성 광종은 유연탄(25.6%)·…" → "구성 광종(가중치)은 …"으로 오해 없게.

## 1. report_gen 변경(`inhouse/report_gen/app/analysis/summary.py`)

| # | 내용 |
|---|---|
| 1 | `_replace_composite_subindex_narrative` — 지수별 문장의 " 구성 광종은 …" → " 구성 광종(가중치)은 …" |
| 2 | `_append_composite_period_average`(신설, `_analyze_composite`에서 호출) — key_metrics에 `period_average_composite_index`("조회기간 평균 지수", 포인트, basis=기간·건수) 추가. 프로즌 계산기(`additional_summary.py`)는 손대지 않고 summary.py 후처리 패턴으로 |
| - | 전주·전월·전년 대비(`weekly/monthly/yearly_composite_change`)는 **코드가 이미 계산**하고 있었다. v13/v14에 전주만 나온 건 입력 창 때문 — KOMIS `getLineChartIndx` 기본(1개월 프리셋, 2026-08-13~09-11) 응답엔 한 달 전·1년 전 시점 관측치가 없다. 셋 다 보려면 호출 측이 `srchDateS`를 1년 이상 전으로 잡아야 한다 |

테스트 `test_composite_period_average_and_weight_label` 추가(주간 60건, 14개월) —
전주·전월·전년 metric 3종 존재, 평균 라벨·단위·값, 렌더 본문 "구성 광종(가중치)은",
표에 "조회기간 평균 지수" 행. `python3 -m pytest tests -q` 16 passed.

템플릿 정본 2종 갱신(`report_gen_10페이지_업무지시서_준수점검_260909/`):
`01_메뉴별_최종_답변_템플릿.md`(4·5·6번 문장, 주요 지표 표), `AI통계분석_요약답변_광물전망지표.md`(2-1 지수별 변화·주요 지표).

## 2. 입력 — 종합지수만 바뀜, 나머지 20건은 v14와 동일

외부망이 막혀 라이브 1년 재조회는 못 했다. 정적 덤프 `income_data/komis/
komis_03_mineral_index.json`의 "광물종합지수|전체(2016~)" 프리셋(2016-01-04~
2026-08-24)을 요청 필터 `start_date="2025-07-01"`로 잘라 썼다(조회기간
2025-07-01~2026-08-24). "1년" 프리셋(2025-08-26~)은 1년 전 시점(2025-08-24)
이전 관측치가 2일 모자라 전년 대비가 안 나온다 — 그래서 전체기간+필터.
같은 엔드포인트에 `srchDateS`만 넓힌 것과 같은 입력이다.

결과(`v15_sources.json` vs `v14_sources.json`): 차이는 `indicator_composite` 1건뿐.
- 주요 지표: 현재 3종 + 전주 2.01% · 전월 2.93% · 전년 34.56% + 조회기간 평균 지수 3,065.18포인트.
- 지수별 변화 3문장 모두 "전주·전월·전년 대비 … 구성 광종(가중치)은 …" 형태.
- 조회기간이 14개월로 늘어 기존 로직의 `medium_long_term_contrast`·`overall_pattern`
  문장(한 달·1년 비교치가 있을 때만)도 함께 등장 — 새 기능이 아니라 기존 조건부 문장.

## 3. 재현

```
KOMIR_ROOT=/path/to/komir python3 <이 폴더>/refetch_v15_sources.py   # → v15_sources.json (21건)
KOMIR_ROOT=/path/to/komir python3 <이 폴더>/build_v15_full.py        # v10.pptx 복사 → v15.pptx, v14.pptx 대비 적색
```
raw/는 v13 evidence, 정적 덤프는 `income_data/komis/`(gitignore)를 읽는다.

`build_v15_full.py`에서 v14 스크립트 대비 바뀐 것:
- `rebuild_composite_slide` — 표에 "전월 대비"·"전년 대비"·"조회기간 평균 지수" 행을
  API가 낼 때만 앞 행 복제로 삽입(v13 `ensure_table_row` 패턴), 평균 행 단위 셀은
  복제 원본의 "%"가 아니라 metric.unit("포인트")로 바로잡음.
- 종합지수 슬라이드(v10 템플릿)엔 검색 옵션 캡션 도형이 없어, 시장동향지표
  슬라이드의 "TextBox 11"을 복제해 같은 자리에 붙이고 입력 창을 명시했다.
- 대조 기준 v13.pptx → v14.pptx.

## 4. 검증(저장된 v15.pptx를 다시 열어 v14.pptx와 독립 대조)

- zip 정상, 슬라이드 21/21. 텍스트가 다른 위치 17곳 — 전부 슬라이드 11(광물종합지수):
  본문 문단 3개(지수 요약·지수별 변화·지수 위치), 표 값 4셀·신규 행 3개(9셀), 캡션 1개.
- 적색 run 36개 = 위 차이 위치와 정확히 일치. 저장본 명시 색상: FF0000 36(전부
  슬라이드 11), 000000 243, 테마색 31333F 436 — 그 외 적색 계열 없음.
- 슬라이드 1~10·12~21은 v14와 텍스트 동일(v14에서 적색이던 비교광종 4문장도
  v15에선 v14와 같으므로 흑색).

## 5. 후속

- report_gen 컨테이너(18003)는 아직 v13b 이미지 — main 병합 후 재빌드 필요
  (프롬프트 DB 변경 없음).
- 실제 화면에서 전월·전년 대비가 보이려면 KOMIS 호출 측(프론트)이 종합지수
  조회 시작일을 1년 이상 전으로 넘겨야 한다 — 코드 변경이 아니라 호출 파라미터 문제.
