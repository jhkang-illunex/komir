# report_gen v13.pptx — 검수 후속(API 3건·슬라이드 스크립트 3건 정정) evidence

산출물: `documents/산출물/2026-W37_0907-0913/요약분석_정리결과물/
분석요약_개선_결과작업_v13.pptx`(21슬라이드, git 미추적 — pptx 예외 원칙).
사용자 지시(2026-09-13): "3. 노출 1,2번 수정후 api를 다시 빌드 하고 배포후,
나온 결과물을 v13 슬라이드를 작성하고, 템플릿 파일들도 다시 생성해주세요".

## 1. API 수정 3건(`inhouse/report_gen`)

| # | 파일 | 내용 |
|---|---|---|
| 1 | `app/analysis/map_presentation.py::import_history_fact` | 전년 비교 문장 정정 — ①map_global인데 "수입액"으로 하드코딩 → page_id별 라벨(`세계 교역 총액`/`수입액`) ②전년 응답은 연간(1/1~12/31) 전체, 당해는 조회 종료일까지 집계라 "전년 동기 대비"가 사실과 달라 "전년 대비"로 ③"참고로" 접두어 제거 |
| 2 | `app/analysis/komir_summary.py` (no_export_data) | D-10(조회기간 표기)이 수출 결측 폴백 문장에만 빠져 있던 것을 `_query_period_phrase`로 통일 |
| 3 | `app/analysis/report_render.py::_PRICE_KEY_METRIC_ORDER` | 비교광종 조회 시 생기는 `compare_overall_change_pct`("{비교광종} 대비 조회기간 변화율차", %p)를 마크다운 주요 지표 표에도 노출(사용자 결정 "3. 노출"). 라벨은 광종명이 들어가 동적이라 `metric.label` 사용 |
| - | `app/analysis/resources/prompts/map_korea_summary.md`·`map_global_summary.md` | LLM 지시문의 "전년 동기" 표현을 새 문장에 맞게 갱신(`seed_prompts.py`로 DB 반영) |
| 4 | `app/analysis/summary.py::_validate_llm_summary` | (후속 지시 "미수정을 수정해주세요 D-10 반영") map_korea/map_global의 current_state·export_summary·no_export_data 근거에 `조회기간(…)` 구절이 있으면 LLM 출력에도 그대로 있어야 통과 — 없으면 규칙 기반 폴백. 직접 테스트: 원문 통과(None), "2026년 한국의"로 바꾼 변형은 "조회기간(…) 표기를 누락하거나 변경했다"로 거부 |
| 5 | `app/analysis/summary.py::_mineral_map_latest_year_change` | (후속 지시 "숫자 모순성 해결") 표 "전년 대비 변화율"이 국가별 합계로 계산돼 본문(공식 `_TOTAL_` 우선)과 모순(동 매장량 표 -3.42% vs 본문 0%) → 본문과 같은 규칙(공식 총계 우선, 없으면 그 해 관측치 합)으로 통일. 동 매장량 표 0%로 일치 |

검증: pyflakes(수정 3파일 클린), `python3 -m unittest discover -s tests`
14/14, `scripts/komis_dump_smoke_test.py` 395콤보 0 mismatch/0
internal_error. 인프로세스 렌더링으로 새 문장 확인 후 이미지
`komir-report-gen:260913-v13` 빌드 → `komir-report-gen-test` 교체 →
`seed_prompts.py`(13건) → `/admin/prompts/reload` → 실컨테이너
`POST /api/v1/analysis/maps/global-trade`·`/maps/domestic-trade`·
`/prices/base-metals`로 세 변경 모두 라이브 확인.

라이브(실LLM 경로) 확인 중 LLM 정제가 map_korea의 `조회기간(2026년) 한국의
…`를 `2026년 한국의 …`로 고쳐 쓰는 것을 발견 → 후속 지시로 위 4번 검증
추가, `komir-report-gen:260913-v13b`로 재배포 후 같은 호출 2회 모두
"조회기간(2026년) 한국의 …"로 나오는 것을 확인. map_mineral도 재배포본에서
표 "전년 대비 변화율 0%" 확인. v13.pptx·v13_sources.json은 이 재배포본
코드로 다시 만들었다(복붙 대조 21/21·203문장·표 전부 일치 재확인).

## 2. 슬라이드 스크립트 정정 3건 + 표 행 보완(`build_v13_full.py`)

검수에서 찾은 v12 스크립트 버그:
1. **표 잔존값** — 매핑에 없는(=API가 그 지표를 안 낸) 행을 손대지 않아
   v10 값이 남았다(우라늄 슬라이드 7·8 "연속 추세 2"는 API에 없는 값).
   → `blank_labels`로 "-" 처리.
2. **표 행 부재** — 템플릿 표에 없는 행(동 "연속 추세")은 추가를 못 해
   API 출력이 누락됐다. → `ensure_table_row()`(앞 행 XML 복제 삽입).
3. **절 제목 접미어** — 수출 탭/국가필터 슬라이드에서 "글로벌 교역
   현황(수출 탭)"처럼 API 절 제목을 바꿨다. → 접미어 제거.
4. 같은 메커니즘으로 그동안 "우선순위 낮음"으로 보류했던 표 행 2종도
   채웠다 — map_global의 "{국가} 연도별 교역액 변화" 3행(바차트 상위 3개국,
   국가필터 슬라이드처럼 응답에 없으면 복제 원본에서 딸려온 행 제거),
   map_mineral의 "최대 증가 국가" 행.
5. 슬라이드 2(목차, v10 템플릿 손글씨)의 "희소금석" 오타 → "희소금속"
   (API 본문이 아닌 템플릿 텍스트라 스크립트에서 수정).

## 3. 재현(이 폴더만으로 완결)

```
python3 <이 폴더>/refetch_v13_sources.py   # raw/ → v13_sources.json (report_gen 21건 실호출)
python3 <이 폴더>/build_v13_full.py        # v10.pptx 복사 → v13.pptx 21슬라이드
```
- `raw/`: 라이브 원본 17개(가격 4·지수 3·수급패널 1은 v12 evidence의
  `live_*.json`, 글로벌수급지도 4·국내수급지도 생산품유형 5는 세션 중
  `/tmp`에만 있던 `li_*.json`·`cu_map_korea_scope*.json`을 옮겨 담음).
  map_korea baseline·국가필터와 map_mineral은 `income_data/komis/` 정적
  덤프(라이브 대조로 값 동일 확인, v12 정정 3 참고).
- v12까지는 `refetch_v12_sources.py`가 가격 4종·광물종합지수를 정적
  덤프(8/17~8/27)에서 만들고 라이브 값은 캐시에 손으로 덧대 재현이 안
  맞았다(검수 발견). v13 스크립트는 `raw/`의 라이브 원본을 직접 읽는다 —
  evidence 폴더 복사본으로 다시 실행해 `v13_sources.json`이 바이트 단위로
  동일함을 확인했다.

## 4. 검증 — v13.pptx가 report_gen 출력의 복붙인지

`render_markdown_report()`(실제 렌더러)를 v13_sources.json 21건에 직접 돌려
슬라이드와 대조:
- 절 제목·순서: 21/21 일치(v12는 18·19 불일치).
- 본문 문장: 렌더 문장 203개 전부 슬라이드에 있음(누락 0), 슬라이드 문장
  중 API 출력에 없는 것 0.
- 주요 지표 표: 라벨 집합·순서·값 전부 일치(v12는 "연속 추세" 잔존값 1건·
  누락 1건, 렌더에만 있는 행 4종).
- zip 무결성 정상, 빨간색 run 0.
- 국가필터 슬라이드(15·19)의 "-" 행은 고정 행 템플릿에서 API가 그 지표를
  안 낼 때의 표시(렌더 표엔 행 자체가 없음) — v12와 동일한 의도적 차이.

## 5. 템플릿 문서 4종 재생성

`documents/산출물/2026-W37_0907-0913/report_gen_10페이지_업무지시서_준수점검_260909/`
- `01_메뉴별_최종_답변_템플릿.md`
- `AI통계분석_요약답변_광물자원가격.md` / `_핵심광물지도.md` / `_광물전망지표.md`

방법: 395콤보 하네스 결과의 마크다운 전체 + v13 소스 21건 = 실제 출력
415건에서 문장 유형을 전수 추출(숫자·일자·국가명 마스킹)해 문장 인벤토리를
만들고, 조건 분기는 계산기 f-string을 직접 읽어 옮겼다. 이전 판에서 실제
출력과 달랐던 것: D-10 조회기간 표기(12곳), 전년비교 문장(라벨·동기·참고로),
"참고:" 절 제목, 비교광종 표 행, 가격 문장 방향어("변동했습니다"→"상승/
하락/보합했습니다"), "조회기간 관측치(실거래가) 기준" 표기, 광물지도 주요
변화 상세형, "수입·수출 규모 추이" 절·route_yearly_trend 미기재, 수급
수입증가율 문장 형태, 지수 위치 "낮고"→"낮으며" 등.

## 6. 미반영·후속

- map_mineral "직전 관측연도 … 0톤, 0% 변동이 없었습니다" 문구는 코드
  그대로(어색하지만 사실) — 문구 다듬기는 별도 지시 시.
- 이번 세션의 report_gen 코드 변경은 전부 미커밋 상태(사용자 지시 대기).
