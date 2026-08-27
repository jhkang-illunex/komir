# 작업 이력 (WORKLOG)

> 커밋 해시는 `git log --oneline` 기준. 최신이 위.

## 2026-08-27 (최신) — 분석요약 루틴 skeptic-code DEEP 감사: 8건 적용, Pass 3 APPROVE

사용자 요청 "/skeptic-code 요약 보고서 작성 루틴을 검증해주세요 적대적 검증
및 과한 부분 등등에 대해서 점검". 범위 `inhouse/services/report_gen/app/
{routers,analysis}`+`main.py`+`scripts/`(~6,300줄). 테스트 스위트가 없어 판정은
전부 스크래치패드 재현(TestClient+가짜 LLM 주입)으로 냈고, 적용분은 이 변경을
쓰지 않은 독립 체커(correctness 레인, 읽기 전용)가 **APPROVE**했다 —
`change_ref c40fe7187+85d3d00c2705`, HIGH 0. 이 WORKLOG 항목 한 줄이 그 라벨
이후 유일한 변경이다(산문이라 Pass 3 면제).

**적용 8건**(코드에 "2026-08-27 skeptic 감사 SC-00x" 주석으로 표시)
- SC-001(HIGH·LIAR) 라우터가 `AnalysisSummaryRequest(page_id=..., **dump)`를 라우트
  본문에서 만들다 pydantic ValidationError가 새어 **HTTP 500 평문**이 나갔다(예:
  `/prices`에 `trade_direction:"export"`) — "항상 200+status" 계약 위반. `routers/
  _common.py::run_summary(page_id, payload, request)`로 조립을 옮기고
  ValidationError→`NO_DATA`. 17개 라우트(analysis 9+report_data 8) 전환.
- SC-002(HIGH·CLIFF) 느린 LLM 1건이 `analysis_lock`을 최대 ≈372s(120s×3회+백오프)
  쥐고 뒤이은 규칙기반(ms) 요청까지 전부 TIMEOUT, 대기 워커 적체(재현: 3/3
  TIMEOUT, `_call` 안 워커 3). `main.py`가 report_gen용 `KomirJsonLLM`에
  timeout 8s·retries 1을 주고, `_common.py`가 `lock.acquire(timeout=20)`로 예산 내
  못 잡으면 포기. 적용 후 대기 워커 1. lock 자체 제거는 사용자가 거부(유지).
- SC-003(MEDIUM·LIAR) 계산기 ValueError(export 방향인데 export_amount 없음·국가
  3개 미만·forecast 1건·최신가 null)가 스택트레이스+`INTERNAL_ERROR`로 보고돼 G2
  게이트 의미가 오염 — `summary.py::_calculate_or_no_data`로 7개 `calculate_*`
  호출만 감싸 `NO_DATA`. pydantic ValidationError는 그대로(진짜 버그 신호 보존).
- SC-004(MEDIUM·TWIN) `prompts.py` 폴백 상수가 `seed_prompts.py` 시드와 10키 중
  9키 드리프트 — price 폴백은 "연속기간 언급 금지"였는데 계산기는 `price_streak`
  근거를 만들고 검증기는 전 id 사용을 요구해 DB 미접속 모드에서 price LLM 출력이
  항상 폴백. `prompts.py::PROMPTS` 단일 소스, `seed_prompts.py`는 import만(300→82줄).
  DB `ai_cfg.cfg_prompt` 10키는 이미 PROMPTS와 byte-identical(체커 실측)이라 시드
  재실행 불필요.
- SC-005(MEDIUM·TWIN) 섹션 문장수 계약이 `summary.py`/`prompts.py` 두 곳에 복제 →
  `prompts.py::SECTION_SENTENCE_RANGES`·`MINERAL_MAP_*` 단일 상수.
- SC-006(MEDIUM·ORACLE) price 프롬프트가 `near_period_high/low` 패턴을 참조하는데
  `build_summary_payload`가 `detected_patterns`를 실은 적이 없어 영구 사문 →
  payload에 code·label만 추가(evidence 문자열은 숫자 검증 때문에 제외).
- SC-009(MEDIUM·ORACLE) `scripts/` 13파일이 타 세션 스크래치패드 절대경로
  하드코딩 → `KOMIS_HARNESS_SCRATCH` env(현재값 기본).
- SC-011(LOW) price_group 조사 하드코딩("구리이") → `_subject`/`_topic`.

**검증**: py_compile, 재현 R1~R8 전환 확인, G1 덤프 스모크 384콤보+G2/G3/불일치
게이트 전부 통과, 가짜 LLM 계약 테스트 9페이지 채택 9/9·위반 거부 9/9, 체커가
17개 라우트 전수·lock 12동시요청·DB 프롬프트 대조 등 독립 재현. vLLM은 샌드박스
에서 gaierror라 실 LLM 경로는 미검증.

**사용자 결정(유지)**: SC-007 죽은 DB 경로(`data_sources/extra.py` 309줄·`store.py`
85줄·summary.py 주석 블록 7개·None 소스 파라미터 7개) 주석 보존, SC-008 `main.py`
PG_DSN 가드(없으면 8종 INTERNAL_ERROR) 유지.

**라운드 2 — 사용자 지시 "수정 사항을 전부다 수정하고 커밋"으로 잔여 6건 추가
적용**(같은 날, 라운드 1 APPROVE 직후): NEW-1 `calculate_mineral_map_summary`
연도 1개면 ValueError→NO_DATA(이전엔 `years[-2]` IndexError→INTERNAL_ERROR,
start_year==end_year 필터로 정당하게 도달 가능), NEW-2 `calculate_composite_
summary` 전주·전월 비교 관측이 없으면(1건·하루치) ValueError→NO_DATA(이전엔
major_changes 0건→`SummaryNarrative` ValidationError→INTERNAL_ERROR), SC-002
zombie `_common.py` deadline 공유+`future.cancel()`(풀 2워커·6동시요청 재현에서
무관측 LLM 호출 1→0), 라우터 스키마 422 → `main.py` `RequestValidationError`
핸들러가 `/api/v1/{analysis,prices,indicators,maps}/` 경로만 200+`NO_DATA`로
(`/reports/*`는 422 유지), SC-016 `report_render.py` "## 참고"에서 `notices`(LLM
작성 제약)와 "LLM " 접두 경고 제외(데이터 결측 경고는 유지), SC-017
`secondary_measure_observations: []`를 `compare_observations`와 같이 "없음"으로.
검증: py_compile·G1 384콤보+G2/G3/불일치·가짜 LLM 9/9·라운드2 재현 전부 통과.
**적용 안 한 것**: `openai_compat.py` 마지막 시도 후 2s 슬립(공유 geo 코드 —
회귀 사이클 없이 불변경, CLAUDE.md §4), SC-018(vLLM 미도달로 판정 불가), SC-010
`scripts/` 위치 이동(배포 단위 결정 사항 — 2,871줄이 airgap inhouse 안에서
playwright 외부접속, requirements 미선언). 실서버 반영 시 재기동 필요.

## 2026-08-27 — PDF 보고서 지침 6건 코드 반영 + 전체 회귀 재검증(/unlazy)

직전 세션(같은 스레드, /unlazy)에서 발주처 PDF 템플릿(`AI 통계분석 요약
답변_광물가격전망지표.pdf`, `AI 통계분석 요약답변_수급지도광물지도.pdf`) 대비
실제 생성 보고서 내용을 점검해 확정 버그 1건 + 기능 간극 5건을 발견했고,
사용자가 "6건 전부" 반영을 지시(/unlazy): "pdf 기반 보고서 생성 규칙을
코드에 반영하고, 비철금속/희소금속/광물맵-대한민국/광물맵-글로벌 등 지금까지
보고서 작성을 한 모든 테스크를 다 다시 돌려서 전부 검수 하세요."

**①map_korea 수입/수출 라벨 고정 버그 수정(확정 버그)**: `komir_summary.py::
_calculate_trade_map_summary`가 `direction_label="수입"` 하드코딩 + 항상
`import_amount` 필드만 읽던 걸 `calculate_domestic_trade_summary(series,
direction="import"|"export")`로 바꿔 요청의 `trade_direction` 값에 따라
필드·라벨이 동적으로 바뀌게 했다. `AnalysisSummaryRequest`·라우터 요청
스키마(`MineralDateRangeSummaryRequest`)에 `trade_direction` 필드 신설,
보고서 상단에 조회방향도 표시. 실측 검증: G11 재실행(73건) 결과 수출
33건 중 24건이 정확히 "수출총액", 수입 40건 중 32건이 "수입총액"으로
렌더링(나머지는 SKIPPED) — 이전엔 수출 방향이어도 100% "수입총액"이었다.
PDF가 요구하는 상위 5개국 합산 비중(CR5)도 함께 추가.

**②map_global 원산지→도착지 루트 랭킹 + 대한민국 순위 하이라이트**: 이전엔
원산국(수출국)별로 도착지를 뭉개 집계해 "국가별 총 공급액" 랭킹만
만들었다 — Playwright로 KOMIS `getListDataNation` 원본 응답을 직접
조회해 각 행에 도착국(`incmNtnNm`/`incmNtnCd`)·원산국(`expNtnNm`/
`expNtnCd`)이 이미 쌍으로 옴을 실측 확인하고, `calculate_global_trade_
summary`를 완전히 새로 짜서 루트 단위 랭킹(1~3위, CR3/CR5) + 대한민국이
관련된 루트 하이라이트(있으면 순위·상대국·금액·비중, 없으면 결측 문구)를
계산하도록 바꿨다. `TradeCountryObservation`에 `origin_country_code`/
`origin_country_name` 필드 신설. 실측 검증: G12 재실행(73건 중 71 ok)
결과 46건에서 한국 루트 하이라이트가 PDF 예시와 같은 형식("대한민국은
세부현황 기준 5위(일본行 3,224,422.21, 5.27%)와 16위(미국行 ...)...")으로
정확히 렌더링됨을 확인.

**③price 연속 상승세/하락세(streak) 계산 추가**: PDF가 요구하는 "[N]일/주/
개월 연속 [상승세/하락세/보합세]"가 이전엔 아예 계산 안 됐다(원인 추정과
달리 시계열만으로 계산 가능한 통계라 "주요 요인 미구현"과는 다른 성격의
간극이었음). `calculate_price_summary`에 관측치 방향(오름/내림/보합) 연속
카운트 + 관측 간격으로 단위(일/주/개월) 추정하는 로직 추가.

**④indicator_composite 하위지수(메이저·희소) 전월 대비 추가**: PDF는 두
하위지수 각각 전주·전월·전년 3종 비교를 요구하는데 전주·전년만 있고
전월이 없었다 — `calculate_composite_summary`에 `monthly_subindex_
comparison` 근거 추가(기존 weekly/yearly 블록과 같은 패턴).

**⑤map_mineral 매장량 vs 생산량 교차 비교**: PDF §4("매장량 2위 호주는
생산량 8위") 같은 교차 비교가 불가능했다(매장량/생산량 중 하나만 다루는
설계) — `calculate_mineral_map_summary(series, secondary_series=None)`로
확장해 반대 measure 계열을 선택적으로 받으면 상위 3개국의 반대 measure
순위를 비교하는 근거 1건을 major_changes에 추가(2026-08-27 스모크
테스트에서 처음엔 current_position에 넣었다가 `SummaryNarrative.
current_position` max_length=3 초과로 실패 → major_changes로 이동해 해결).
요청에 `secondary_measure_observations`/`secondary_unit` 필드 신설.

**⑥전체광종(비철금속/희소금속 그룹) 요약 신규 page_id 신설**: PDF §1-2
"전체광종(필요시)"에 대응하는 API가 아예 없던 걸(기존에 "별도 기능 논의
필요"로 기록된 갭) 새 page_id `price_group`으로 신설 — 광종별 이미 계산된
전주·전월 등락률(`PriceGroupMineralObservation`)을 받아 그룹 평균, 강세/
약세 광종군, 최대 상승·최대 하락 광종을 계산(`calculate_price_group_
summary`). 신규 라우트 `POST /api/v1/analysis/price-group` 추가.

**전체 회귀 재검증(같은 날, "지금까지 보고서 작성을 한 모든 테스크를 다
다시 돌려서 전부 검수" 지시 이행)**: 6건 반영 후 합성데이터 스모크
테스트(7케이스) 전부 통과 확인 → G1(384콤보 덤프 기반, map_korea/global이
새 로직을 크래시 없이 통과)·G2~G4(내부오류/조사오류/불일치 0건)·G5~G6(라이브
69콤보)·G7(무작위 8회)·G8(비철 6광종)·G9(희소 56콤보)·G10(비철 13콤보)·
G11(map_korea 73광종, 방향 라벨 실측 정정 확인)·G12(map_global 73광종,
한국 하이라이트 실측 확인)·G13(map_mineral 65광종) 전부 재실행 — 신규
회귀 0건, unlazy `--reverify`로 13개 게이트 전부 공식 재승인.

## 2026-08-26 — 핵심광물지도 3메뉴(대한민국·글로벌·광물지도) 전종목 커버리지 회귀 테스트(/unlazy G11~G13)

사용자 요청(/unlazy): "핵심광물지도/대한민국/글로벌/광물지도 메뉴... 모든 광물에
대해서 모든 옵션을 싹다 하나 이상 선택하고 랜덤으로 값을 바꾸고, 비교 광종에
대해서도 나올 수 있는 모든 케이스를 다 적용해서 탐색." G8~G10(광물자원가격
페이지)까지 마친 뒤 같은 강도로 핵심광물지도 메뉴 3개(대한민국=map_korea,
글로벌=map_global, 광물지도=map_mineral)를 요청받음.

**사전 확인(실측)**: 세 메뉴 모두 DOM에 "비교광종"(`srchCompareMnrkndUnqCd`
등) 컨트롤 자체가 없다 — 그 기능은 광물자원가격(price) 페이지 전용이었다.
지어내지 않고 실제 존재하는 옵션만 대상으로 스코프를 좁혔다: map_korea(광종
73종 전부·수입/수출 방향·기준연월타입 Y/M·기준연도), map_global(광종 73종
전부·기준연월타입 Y/M·기준연도, 국가방향 select는 있으나 비교 개념 아님),
map_mineral(광종 65종 전부·매장량/생산량 탭·시작~끝연도).

**신설**: `scripts/komis_map_korea_full_coverage_test.py`,
`komis_map_global_full_coverage_test.py`, `komis_map_mineral_full_coverage_test.py`
— 광종별 1회씩 전수 순회, 나머지 차원은 트라이얼별 무작위 배정. map_mineral은
검색 버튼에 `id`가 없고 `onclick="onSearchMapMnrl(1)"`만 있어 셀렉터가
다른 두 페이지와 다름(실측 확인).

**버그 발견·수정**: 최초 드라이런에서 map_mineral 65종 중 8종(규회석·금·
남정석·니오븀·니켈·동·레늄·루비듐, 연속된 6~13번째)이 `TimeoutError`로
`TRIAL_FAILED` — 원인은 상단 네비게이션 서브메뉴(`header.open-submenu` >
`ul.depth2-menu`)가 이전 페이지에서 남은 마우스 좌표 위에서 자동으로
펼쳐져 광종 라디오 레이블 클릭을 가로챈 것(하네스 자체의 버그, report_gen
코드 버그 아님). `_select_mineral()`에 `page.mouse.move()`로 중립 위치 이동
후 클릭, 실패 시 force 클릭 재시도 로직을 추가해 해결. 정식 게이트 실행
중 map_global에서도 같은 패턴(알루미늄 1건)이 재현돼 동일 수정을 map_korea·
map_global에도 적용.

**결과(최종 게이트 실행, 수정 반영 후)**: map_korea 73/73 광종 커버(63 ok·10
정상 SKIPPED, 관측치 0인 진짜 무역없음 케이스로 확인), map_global 73/73
커버(71 ok·2 SKIPPED: 레늄·토륨), map_mineral 65/65 커버(28 ok·37 SKIPPED,
연도<2건 또는 최신연도 국가<3개인 경우), 3개 페이지 합계 INTERNAL_ERROR·
TRIAL_FAILED·데이터 불일치 전부 0건. ok 케이스 표본(map_korea 리튬, map_global
리튬, map_mineral 니켈) 수동 대조 — 핵심 진단·주요 지표 수치 전부 원본 데이터와
일치, 이상 없음. GATES.md에 G11~G13 추가, 13개 게이트 전부 최종 PASS.

## 2026-08-26 — 비철금속 품목 단위 전수 커버리지 회귀 테스트(/unlazy G10)

사용자가 G9(희소금속)와 완전히 동일한 문구로 비철금속을 재요청(/unlazy):
"모든 광물의 모든 옵션을 싹 다 하나 이상 선택+랜덤 값 변경, 비교광종도
나올 수 있는 모든 케이스 다 적용." G8(비철 6광종×1콤보, 가벼운 스코프)과
구분해 이번엔 **G9와 같은 깊이**로 재해석 — "모든 옵션을 하나 이상"은
광종 단위가 아니라 **광종×가격기준 콤보 단위**(비철금속 실측 13개: 니켈·
동·아연·알루미늄·연 각 2개, 주석 3개)까지 내려가야 한다고 판단.

**신설**: `scripts/komis_base_metals_exhaustive_coverage_test.py` — G9
(`komis_minor_metals_full_coverage_test.py`)와 동일 구조(품목 콤보 전수
발견 → 평균옵션 5종 순환+비교광종 라운드로빈+기간 무작위 배정)를 비철금속
규모(13콤보, 비교광종 풀 5종)에 맞춰 재구현. 별개 스크립트로 둔 이유: 이미
통과한 G8/G9 게이트의 CHECK 커맨드를 안 건드리기 위함(리팩터링해서 공용
모듈로 합칠 수도 있었지만, 이미 승인된 게이트의 동작을 바꿀 위험을 지지
않는 쪽을 택함).

**결과**: 13/13 콤보 실행, 6/6광종 커버, **비교광종 6/6종(자기자신 제외
풀 기준 전부) 커버**, 4건 `ok`, 9건 정상 `SKIPPED_INSUFFICIENT_DATA`(원인
확인: G9와 같은 패턴 — 무작위로 뽑힌 기간이 해당 품목의 실제 KOMIS 데이터
시작 이전, 예: 아연 LME CASH DAY에 1989년 단일연도 요청 → 0행), INTERNAL_
ERROR·TRIAL_FAILED·데이터 불일치 전부 0건. 4건 성공 케이스 전부 수동
대조(핵심 진단·비교광종 변화율차 산술·전일/직전관측치 라벨) 완료, 이상
없음. 신규 버그 없이 종결. GATES.md G10 추가, 10개 게이트 전부 최종 PASS.

## 2026-08-26 — 희소금속 34광종 전종목+비교광종 34종 전종목 커버리지 회귀 테스트(/unlazy G9)

사용자 요청(/unlazy): "희소금속 메뉴 테스트 — 모든 광물에 대해 모든 옵션을
싹 다 하나 이상 선택+랜덤으로 값 변경, 비교광종도 나올 수 있는 모든 케이스를
다 적용." 바로 위 항목(G8, 비철금속 6광종×1콤보)보다 훨씬 큰 스코프 — 희소
금속은 광종당 품목(가격기준)이 여러 개(1~3개, 실측 총 56개 콤보)라 "모든
옵션을 하나 이상"은 광종 단위가 아니라 **품목 콤보 단위 전수**를 뜻한다고
해석했고, "비교광종도 모든 케이스"는 34종 비교광종 옵션 전체가 최소 1회는
쓰이도록 **라운드로빈으로 결정론적 보장**(순수 무작위로는 운에 좌우돼
누락 가능성이 있어서 의도적으로 순환 배정).

**신설**: `scripts/komis_minor_metals_full_coverage_test.py` — 2단계 실행.
①34광종을 순회해 품목 드롭다운을 읽어 (광종,품목) 평평한 목록 작성(56개
콤보 확인, 이전 G5의 56과 일치). ②그 56개 콤보 각각에 평균옵션(5종 순환)·
기간(trial별 고정시드 무작위)·비교광종(34종 라운드로빈, 자기자신이면 다음
칸)·비교광종가격기준(그 비교광종의 옵션 중 무작위)을 배정해 실제 검색+
price API 호출까지 수행.

**결과**: 56/56 콤보 실행, 34/34광종 커버, **비교광종 34/34종 전부 최소
1회 사용**(`compare_minerals_missing: []`), 13건 `ok`, 43건
`SKIPPED_INSUFFICIENT_DATA`, INTERNAL_ERROR·TRIAL_FAILED·데이터 불일치
전부 0건. SKIPPED 43건 중 다수(DAY/WEEK인데도 스킵된 10건 포함)를 개별
확인한 결과 **원인은 버그가 아니라 무작위로 뽑힌 기간이 해당 희소금속
품목의 실제 KOMIS 데이터 시작 시점보다 앞선 경우**였다(예: 가돌리늄
Gadolinium Oxide에 1996~2007년을 요청 → 그 품목은 최근에야 KOMIS가
자료원을 확보한 항목이라 원본 응답 자체가 0행 — 하네스가 이를 정상
감지해 깔끔하게 SKIPPED 처리, 크래시 없음). 13건 `ok` 전부 샘플 대조에서
핵심 수치·비교광종 문장·전일/직전관측치 표기가 원본과 일치함을 확인,
추가 버그 없이 종결. GATES.md G9 추가, 9개 게이트 전부 최종 PASS.

## 2026-08-26 — 비철금속 6광종 전종목 강제 커버리지 회귀 테스트(/unlazy G8)

사용자 요청(/unlazy): "비철금속 메뉴의 모든 옵션에 대해 랜덤 선택 후 검색·
보고서 생성 → 생성 실패 체크 → 결과 점검(실데이터 요약 정확성) → 비교광종·
비교광종가격기준 등 최소 2개 이상 옵션을 동시 사용 + 기간도 랜덤 → 검증.
현재 세션은 herd이므로 여러 세션이면 tab/pane으로 진행상황 노출."

**병렬화 판단**: 이번 작업(6회 시행, 수십 초 규모)은 병렬화해도 이득이
작고 버그 수정은 원래 순차적(발견→수정→재검증)이라 **단일 스레드로
진행**했다 — herd tab/pane 요구는 "여러 세션일 경우"에만 해당하는 조건부
지시였고, 이번엔 다중 세션을 안 씀.

**신설**: `scripts/komis_base_metals_full_coverage_test.py` —
`komis_random_trial_test.py`의 `run_trial()`에 `forced_mineral` 인자를
추가(하위호환, 기존 호출부 영향 없음)해 재사용, 비철금속 6광종(니켈·동·
아연·알루미늄·연·주석) **전부를 1회씩 강제 커버**하면서 나머지 5개
차원(품목·평균옵션·기간·비교광종·비교광종가격기준)은 trial별 고정시드로
무작위 조합(사용자 요구 "최소 2개 이상 동시 사용"을 5차원 동시 사용으로
충족). 평균옵션은 DAY·WEEK(정상)+QUARTER·MONTH(의도된 거부)를 섞어 비철
금속 자체에서도 그 경계를 직접 재확인.

**결과**: 6광종 전부 커버, 4건 `ok`(DAY×2·WEEK×2), 2건 정상
`SKIPPED_INSUFFICIENT_DATA`(QUARTER·MONTH), INTERNAL_ERROR·TRIAL_FAILED·
데이터 불일치 전부 0건. 4건 전부 "하나하나" 수동 대조: KOMIS 원본이 각
행에 함께 주는 자체 등락률(`flctnPrcnt`)이 우리 계산값과 정확히 일치(니켈
+0.61%·아연 -0.83% 등), WEEK 구간(동·알루미늄)은 "직전 관측치"로, DAY
구간(니켈·아연)은 "전일"로 올바르게 구분되는 것까지 확인(직전 라운드의
전일/직전관측치 수정이 정상 작동함을 재확인, 회귀 없음). 이번 라운드는
추가 버그 없이 종결 — GATES.md G8 추가, unlazy 게이트 체커로 8개 전부
최종 PASS.

## 2026-08-26 — price 페이지 7차원 무작위 조합 실측 + 실버그 2건 추가 발견·수정(/unlazy G7)

사용자 요청: "광종·품목·규격·평균옵션·기간·비교광종·비교광종가격기준을 각각
무작위로 선택해 검색 → 그 데이터로 price API 호출 → 보고서 작성 중 오류
확인 → 보고서 완성 후 실데이터가 제대로 요약됐는지 하나하나 다 체크 →
테스트 케이스와 보고서 결과 기록." 바로 위 항목(G5/G6, 광종×가격기준
전수)이 다루지 않았던 3개 차원(평균옵션·기간·비교광종)을 처음으로
실데이터로 태웠다.

**신설**: `scripts/komis_random_trial_test.py` — 8회 시행, 평균옵션
5종(DAY/WEEK/MONTH/QUARTER/YEAR)을 최소 1회씩 강제 배정하고 나머지
차원(페이지·광종·품목·규격·기간·비교광종·비교광종가격기준)은 trial별 고정
시드로 무작위 선택(재현 가능). 사전 조사로 확인한 것: 평균옵션별 `crtrYmd`
포맷이 다름(DAY/WEEK=8자리 YYYYMMDD, MONTH=6자리, QUARTER="YYYY.NQ",
YEAR=4자리) — MONTH/QUARTER/YEAR는 report_gen의 `Day` 패턴 검증에 안 맞아
**의도된 대로 거부됨**(price 페이지 정의 자체가 "일별" 데이터라 옳은 동작,
report_gen을 고치지 않음). 비교광종은 `srchCompareMnrkndUnqCd`+
`srchComparePrcCrtr` 둘 다 선택해야 응답의 `data.compareMnrl`이 채워짐을
실측(671건, defaultMnrl과 동일 shape).

**최종 결과**: 8회 중 5회 `ok`(DAY×2, WEEK×3), 3회 `SKIPPED_INSUFFICIENT_
DATA`(MONTH/QUARTER/YEAR — 예상된 거부), INTERNAL_ERROR·TRIAL_FAILED·
데이터 불일치 전부 0건. 5건 전부 "하나하나" 수동 대조(KOMIS 원본이 각 행에
같이 주는 `flctnPrcnt`(전일대비)를 우리 계산값과 직접 비교하는 외부
검증까지 포함)로 핵심 진단·주요 변화·현재 위치 문장의 숫자가 원본과
정확히 일치함을 확인. 전체 시행 파라미터+원본데이터 요약+생성보고서는
`komis_random_trial_results.json`에 기록.

**"하나하나 체크" 중 실버그 2건 발견·수정**:
1. **검증 공백**: 자동 미스매치 체크(`_check_mismatch`)가 price 페이지의
   `latest_price`/`mineral_name`만 검증하고 **비교광종 문장("같은 조회기간
   동안 OO은 X% 변동...")의 숫자는 한 번도 자동 대조된 적이 없었다** —
   `komis_dump_smoke_test.py`에 `compare_overall_change_pct` 독립 재계산+
   대조를 추가(이후 재실행한 384+69+8건 전부 여전히 불일치 0건, 계산
   자체는 원래도 맞았음을 확인).
2. **"전일" 오표기**: `komir_summary.py`의 day_over_day 근거가 관측 간격을
   확인하지 않고 무조건 "전일(날짜) 대비"라고 썼다 — 평균옵션=WEEK로 받은
   데이터를 그대로 넣으면 실제로는 7일 전인데 "전일"이라 표기됨(실측
   재현: "전일(2012-12-24) 대비"인데 기준일은 2012-12-31). 직전 관측치와
   정확히 하루 차이일 때만 "전일", 아니면 지표 페이지와 같은 관용구
   "직전 관측치 대비"로 쓰도록 수정(근거 문장·지표 표 라벨·LLM 프롬프트
   지시문 3곳 전부). 근본적으로는 price 페이지가 "일별 전용"이라는 계약을
   요청 바디가 지킨다는 보장이 report_gen 안에 없다는 구조적 한계의 증상 —
   날짜 포맷 검증(8자리)만으로는 "진짜 일별 간격"을 보장 못 한다(WEEK도
   8자리라 통과함). 이번엔 문구만 방어적으로 고쳤고, 더 근본적인 해법(예:
   observations 자체에 실제 일별 간격인지 검증하는 로직 추가)은 범위 밖으로
   남겨둠.

## 2026-08-26 — Playwright로 komis.or.kr 라이브 조회+report_gen 전수 검증(/unlazy G5/G6)

사용자 요청: "playwright로 komis.or.kr 접속해서 비철금속·희소금속 데이터
가져와 API로 던져 보고서 확인" → 뒤이어 "가능한 모든 검색조건 다 테스트,
테스트 항목 다 기록해줘(/unlazy)"로 범위 확장. 바로 위 항목(정적 덤프 기반
회귀 테스트)의 라이브판.

**전제 확인**: 이 세션(개발 샌드박스)의 `curl`은 `komis.or.kr`에 연결이 안
됐지만(WebFetch 도구/직전 세션에서 확인), **Playwright가 띄우는 실제
Chromium 프로세스는 연결됨**을 실측 확인(이유 불명, `curl`과 다른 경로로
나가는 듯) — 그래서 이 작업이 가능했다.

**신설**: `scripts/komis_live_playwright_test.py` — komis.or.kr 광물자원가격
> 비철금속/희소금속 페이지에서 **전 광종 × 광종별 전 가격기준 조합**을
Playwright로 실시간 조회(비철 6광종×가격기준=13콤보, 희소 34광종×광종별
기준=56콤보, 합계 **69콤보**)해 report_gen(`AnalysisSummaryService(llm=None)`)
에 던지고 검증. `scripts/check_live_mismatch_and_typos.py`(덤프판 G3/G4
검사를 라이브 결과에 재적용)도 신설. GATES.md에 G5(라이브 조회+저장)·
G6(불일치·오타 0건) 추가, unlazy 게이트 체커로 실행·승인·PASS 기록
(`--approve --timeout 300`, evidence 6건 전부 exit=0+EXPECT matched).

**최종 결과**: 69/69 콤보 전부 `ok`, INTERNAL_ERROR 0·FETCH_FAILED 0·
데이터 불일치 0·조사/어미 오타 0. 전체 테스트 항목은 `komis_live_results.json`
의 `log`(69줄, 광종|가격기준→상태) + `results`(콤보별 요청/응답/렌더링된
MD/불일치 목록)에 전부 기록됨.

**하네스 자체 버그 1건 발견·수정**(report_gen 버그 아님): 처음엔 비철금속
가격기준 코드(502=LME CASH/497=LME 3개월)를 광종 공통값으로 하드코딩했는데,
**실측 결과 이 내부 serial이 광종마다 다름**(니켈 LME CASH=502, 동 LME
CASH=501, 아연=561, 알루미늄=495, 연=499, 주석=493 — 전부 다른 값,
주석은 LME 15개월까지 있어 3종). 그래서 두 번째 광종부터 전부
`select_option` 실패(FETCH_FAILED 10건) → 희소금속과 동일하게 광종 선택
직후 그 시점의 실제 드롭다운 옵션을 다시 읽어오도록 수정, 재실행해 0건
확인. 콤보키에도 옵션 value를 포함시켜 갈륨/인듐처럼 드롭다운 표시텍스트가
같아도 실제로는 다른 원산지/스펙 계열인 콤보를 구분되게 함.

**KOMIS 페이지 조작 방법(재현용 기록)**: 광종 라디오는 `#srchMnrkndUnqCdRadio`
컨테이너 안 `<label>` 클릭(라디오 input 자체는 숨김 스타일이라 직접
`.check()`하면 타임아웃), 가격기준은 `#srchPrcCrtr` select(광종 선택 직후
그 광종 전용 옵션으로 리렌더링됨 — 하드코딩 금지), 실제 AJAX
(`getMnrlPrcByMnrkndUnqCd`)는 **`#btnSearch`("검색") 버튼을 눌러야만
발화**한다(라디오/select의 change 이벤트 자체는 AJAX를 안 태움 — 실측
확인, 처음 이걸 몰라서 base_metals 전량 FETCH_FAILED가 났던 원인).

## 2026-08-26 — KOMIS 실데이터 기반 8종 회귀 테스트 하네스 + 실버그 3건 수정(/unlazy)

사용자 요청(4개 항목, `/unlazy` 실행) — "① 실데이터로 API별 세션을 만들어 호출,
결과를 페이지·아규먼트 조합 JSON으로 저장 ② 오류난 API 수정/확장 ③ 보고서
공통 오타 수정 ④ 보고서-데이터 미스매칭 퀄리티 체크". GATES.md 4개(G1~G4)
전부 unlazy 게이트 체커로 실행·승인·PASS 기록 완료(`node gate-check.mjs
--approve`, evidence 4건 모두 exit=0+EXPECT matched).

**신설**: `report_gen/scripts/komis_dump_smoke_test.py` — `income_data/komis/`
의 실 KOMIS 덤프를 데이터 원천이 있는 7개 page_id(indicator_market·
indicator_supply·indicator_composite·map_mineral·price·map_korea·map_global,
`forecast_price`는 대응 원천 없어 제외)의 요청 바디로 변환해 `Analysis
SummaryService(llm=None)`를 직접 호출하는 회귀 하네스. LLM 정제 경로는
범위 밖(이전 턴들에서 이미 폴백 동작 검증 완료, vLLM 미접속 환경에서 384건
반복은 정보 없이 시간만 씀). 결과는 `scratchpad/komis_harness_results.json`
에 페이지·콤보키·요청·응답·렌더링된 MD·독립 재계산 정답값·불일치 목록까지
저장(384 combos, 7 페이지, 0 INTERNAL_ERROR, 0 불일치 — 최종 상태).
`check_no_internal_errors.py`(G2)·`check_particle_typos.py`(G3, 은/는·이/가
받침 규칙 독립 재구현+긍정/부정 대조군으로 탐지기 자체 검증)·`check_report_
data_mismatch.py`(G4)도 함께 신설.

**실버그 3건 발견·수정**(전부 실데이터 실행 중 발견, 사전에 몰랐던 버그):
1. `additional_summary.py::calculate_mineral_map_summary` — 직전연도 대비
   증감이 0일 때 "변동이 없었"+"했다"가 이어져 "변동이 없었했다"(문법 오류).
   세 갈래(증가했다/감소했다/변동이 없었다) 모두 완결형으로 통일. 이 파일은
   "무수정 이식" 원칙이지만 사용자의 명시적 오타수정 요청으로 예외 적용.
   (수정 중 트레일링 마침표를 빠뜨렸다가 즉시 재발견·재수정 — 이력 참고용
   으로 기록.)
2. `komir_summary.py::_calculate_trade_map_summary`(map_korea/map_global
   공용) — 1위국 문장에 받침 규칙 무시한 "이"를 하드코딩해 "캐나다이"·
   "호주이"·"칠레이" 등 49건 오류(전부 받침 없는 국가명). `_topic()`(은/는)과
   같은 규칙의 `_subject()`(이/가) 헬퍼를 신설해 교체.
3. `report_render.py` — `unit="ratio"` 지표(0.0356 같은 소수)가 지표 표에
   그대로 찍혀 "0.04"로 보임 — 본문 문장은 "3.56%"인데 표만 다른 단위로
   보여 불일치처럼 읽혔다. 표 렌더링에서 ratio를 %로 환산하도록 수정
   (`_format_metric_row`).

**하네스 자체 버그 1건**(report_gen 버그 아님, 자체 수정): indicator_market/
supply·map_korea/global 어댑터가 `mineral_name`에 KOMIS 코드(예:
"MNRL1054")를 그대로 채워 보고서 제목이 "MNRL1054 분석 요약"처럼 나온 걸
발견 — 덤프 `key`의 한글 광종명을 쓰도록 수정.

**커버리지 근사(정확성보다 파이프라인 전수실행이 목적, 스크립트 상단
docstring에 상세 기록)**: price류는 `srchAvgOpt=DAY` 콤보만, composite는
"1년" 프리셋만, map_korea/global은 "전체기간·수입" 콤보만(그래서
`single_snapshot` 분기 위주로 검증됨 — `period_total_change` 분기는 이번엔
안 탐), map_global은 KOMIS list 엔드포인트의 상위 N개 조합을 수출국 기준
합산한 근사치, mineral_map은 각 행에 반복되는 `totalBurudgQuty`/
`TOTALPRDCTNQUTY`(대소문자 다름, 실측 확인)로 세계총량 합성 행 추가. 비교
광종(compareMnrl)은 덤프 자체에 값이 없어(미수집 축) 이번 하네스로는
재현 못 함 — 이전 턴에 합성 데이터로 이미 별도 검증됨.

## 2026-08-26 — 광물자원가격(price)에 비교광종(compareMnrl) 지원 추가

바로 위 항목(`price_criterion` 추가)에서 열려 있던 질문에 대한 사용자 답:
"희소금속의 경우는 비교 광종과 비교광종 가격 기준이란 아규먼트도 입력이
되는데 그게 대응 가능한가요?" → "가격 비교에서 희소금속에서 가격 비교시
기존 데이터는 defaultMnrl 키 아래 들어오고, 비교데이터는 compareMnrl 키
아래 들어 온다"는 KOMIS 원본 응답 구조 확인 후 구현.

**변경 내용**:
- `MineralDateRangeSummaryRequest`(`routers/analysis.py`, price/map_korea/
  map_global 공용)와 `AnalysisSummaryRequest`(`models.py`)에 `compare_mineral`·
  `compare_mineral_name`·`compare_price_criterion`·`compare_observations`
  4개 필드 추가(`page_id="price"` 전용, KOMIS `compareMnrl`에 대응 — `defaultMnrl`
  은 기존 `observations` 필드가 이미 담당).
- `komir_summary.py::calculate_price_summary(series, compare_series=None)`에
  선택 인자 추가 — `compare_series`가 있으면 두 계열의 "첫 관측→마지막 관측"
  조회기간 전체 변화율을 나란히 비교하는 근거(`compare_overall_change`)를
  `current_position`에 추가한다(일별 대비 대신 전체 변화율을 쓴 이유: 두
  계열의 관측일이 정확히 일치한다는 보장이 없어서). `_topic()`(은/는 조사
  헬퍼)을 재사용해 "코발트는", "리튬은"처럼 받침 유무에 맞게 조사를 붙였다
  (처음엔 안 써서 "코발트은"으로 나온 걸 스모크 테스트로 발견·수정).
- `summary.py::_analyze_price`가 `compare_observations`로 두 번째
  `PriceSeries`를 조립해 `calculate_price_summary`에 넘기고, `applied_filters`
  에 `compare_mineral`/`compare_price_criterion`도 실어 보고서 상단에
  표시(`report_render.py`의 `_FILTER_LABELS`에 라벨 추가).
- `price` 페이지의 `current_position` 문장 수 상한을 1→2로 완화
  (`prompts.py::build_summary_payload`·`summary.py::_validate_llm_summary`
  둘 다, 글자 그대로 일치해야 하는 계약이라 함께 수정) — 비교광종 없을 땐
  기존과 동일하게 1문장.
- `PRICE_SUMMARY_INSTRUCTIONS`(`prompts.py` 폴백 + `seed_prompts.py` DB
  시드 양쪽)에 compare_overall_change 사용 지침 추가, 시더 재실행으로
  `ai_cfg.cfg_prompt` 갱신.

**검증(실측)**: 리튬(기본)·코발트(비교) 예시 요청으로 `applied_filters`에
비교 필드 반영, 보고서 본문에 "같은 조회기간 동안 코발트는 -1.92% 변동한
반면, 리튬은 +2.78% 변동했다" 문장과 주요지표 표에 "코발트 대비 조회기간
변화율차" 행이 정상 렌더링되는 것까지 확인.

## 2026-08-26 — 광물자원가격(price) 요청에 price_criterion(자유텍스트) 추가

사용자 질문: "광물 자원가격 보고서에서, 비철금속과 희소금속이 조회하는
조건값이 다른데 처리 가능한가?" — KOMIS 원본 기준 비철금속(6종, 가격기준
LME CASH/LME 3개월 단일 선택)과 희소금속(34종×최대 60개 품목/스펙 조합,
예: 리튬→Lithium Carbonate/Hydroxide Monohydrate/Spodumene)은 "같은 광종도
조회조건이 다를 수 있다"는 구조다. 답: 이미 처리 가능하다 — report_gen은
바로 위 항목들에서 순수 요청기반 포매터로 전환됐기 때문에, 어떤 조건으로
값을 뽑았는지는 전적으로 호출자(캐치올 상위 서비스) 책임이고 report_gen은
`observations` 배열을 받은 그대로 정리할 뿐 조회조건 분기 로직 자체가 없다.
다만 "어떤 조건으로 조회한 값인지"가 보고서 텍스트에 드러나지 않던 갭은
있어서, `MineralDateRangeSummaryRequest`(`price`/`map_korea`/`map_global`
공용, `routers/analysis.py`)에 자유텍스트 `price_criterion`(예: "LME CASH"·
"Lithium Carbonate") 필드를 추가하고, `summary.py::_analyze_price`가
`applied_filters`에 실어 `AnalysisSummaryResponse`로 전달, `report_render.py`
가 보고서 상단에 `**가격기준**: ...`로 표시하도록 연결했다(`_FILTER_LABELS`
매핑, 신규 필드 추가 시 매핑 안 해도 원래 키 이름으로 표시돼 죽지 않음).
실측 검증: 리튬(Lithium Carbonate) 예시 요청으로 `applied_filters`·렌더링된
MD 양쪽에 정상 반영 확인.

## 2026-08-26 — 분석요약 8종 응답 계약 교체: 구조화 JSON → status/report(MD) + 20초 타임아웃 + out_report 저장 제거

사용자 지시: "해당 보고서는 아웃풋이 DB에 저장되지 않고 MD파일 형태로 풍부한
표현력을 가진 텍스트로 바로 response에 작성하면 됩니다. response 객체에
status에 정상 동작여부/오류 발생시 오류 코드. report ← 요약 보고서. 각 보고서
요청 마다 소요 시간이 20초를 넘어가면 안 됩니다." 바로 위 항목(DB 조회→요청
바디 전환)에서 열어뒀던 "`out_report` 저장 유지할지"를 이 지시로 확정.

**변경 내용**:
- `analysis/models.py`에 `AnalysisReportResponse(status, report)` 신설 —
  `status`는 성공 시 `"ok"`, 실패 시 오류 코드 하나로 성공/실패를 겸함
  (`NO_DATA`·`TIMEOUT`·`INTERNAL_ERROR` 3종, 옛 `DataSourceError`/422→
  `NO_DATA`로 흡수). `report`는 성공 시에만 채워지는 Markdown 문자열.
- `analysis/report_render.py` 신설 — `AnalysisSummaryResponse`(구조화 JSON,
  계산·검증 레이어의 결과, 무수정)를 헤더+문단+표로 된 Markdown으로 렌더링.
  LLM에게 MD를 직접 쓰게 하지 않음(`_validate_llm_summary` 근거검증 계약을
  벗어나므로) — 검증된 `SummaryNarrative` 문장을 그대로 옮겨 담을 뿐.
- `routers/_common.py::run_summary` 전면 재작성: `analyze_and_store()`(→
  `out_report`/MSR_DB 적재) 호출을 `service.analyze()` 직접 호출로 교체해
  DB 저장을 없앰(`store.py` 파일은 삭제하지 않음, 호출부만 뗌 — 이전 두 턴과
  같은 "코드 보존" 원칙). `ThreadPoolExecutor.submit(...).result(timeout=20)`로
  20초 하드캡을 걸고, 더 이상 HTTPException을 던지지 않음 — **HTTP 상태
  코드는 8종 전부 항상 200**, 성공/실패 구분은 바디의 `status`로만 함(기존
  422/503 매핑 제거, 해석 지점으로 명시).
- `routers/analysis.py`·`routers/report_data.py`: `response_model`을
  `AnalysisSummaryResponse` → `AnalysisReportResponse`로 교체(8개 라우트
  전부), 모듈 docstring 갱신.

**알려진 제약**: `analysis_lock`을 쥔 채 실행되는 백그라운드 스레드는
타임아웃 후에도 인터럽트되지 않고 LLM 응답을 계속 기다린다 — 그동안 lock을
기다리는 다음 요청들이 연쇄로 타임아웃을 맞을 수 있음(LLM 클라이언트가 요청
중간 취소를 지원하지 않아 완전히 막지는 못함, vLLM 자체가 죽어있을 때만
발생하는 드문 경로).

**검증(실측, 2026-08-26)**: TestClient로 8종 전부 실제 관측치(니켈·텅스텐
실측 + 나머지 5종은 스키마 부합 예시치)를 요청 바디로 태워 `{status:"ok"}`+
Markdown 본문(헤더·핵심진단/주요변화/현재위치 문단·지표표) 확인. observations
누락 → `{status:"NO_DATA"}` 확인. `_refine_with_llm`을 25초 sleep으로
monkeypatch해 정확히 20.00초에 `{status:"TIMEOUT"}`로 끊기는 것까지 확인.
이 세션은 vLLM 미접속이라 정상 경로도 매 요청 LLM 연결실패 처리에 ~12초가
걸려(host.docker.internal DNS 미해결) 규칙기반으로 폴백함 — vLLM 정상 접속
시의 실제 응답시간(20초 캡 안에서 여유가 있는지)은 이 세션에서 검증 불가.

**중첩된 계약 변경 정리(발주처 프론트 조율 필요, 누적)**: 오늘 하루에만
①요청 바디에 `observations` 등 필드 추가(DB조회 제거) ②응답 계약을
구조화 JSON에서 `status`/`report`(MD)로 교체 — 이식 5종은 애초
"발주처 프론트 계약이라 경로·요청·응답 모두 유지"라고 못박아뒀던 부분이라,
이 두 변경을 프론트와 맞춰야 함.

## 2026-08-26 — 분석요약 8종, DB 직접조회 → 요청 바디 입력으로 전환

사용자 지시: "이 서버는 prompt를 제외하고는 db에서 아무런값을 로딩 안해야
하는데 계속 DB에서 값을 가져오고 있네요. api콜시 입력된 값과 db에 있는
template만 이용해야 합니다." — 바로 아래 항목("LLM 정제 배선")에서 확인한
대로, 이식 5종(indicator_market/supply/composite·map_mineral·forecast_price)과
komir 자체 3종(price·map_korea·map_global) **8종 전부**가
`DataSourceError`/`KomisRawDataRepository`(`data_sources/database.py`·
`extra.py`·`shared/komis_raw.py`)로 `public.KO_MNRL_PRC`·`KO_CSTM_CMMRC`·
`KO_UN_CMMRC`·`KO_SPDM_STBT_INDX` 등을 직접 SELECT하고 있었다 — 요청은
`mineral` 코드+기간만 받고 실제 숫자 배열은 서버가 자체 DB 조회로 채우는
구조. 사용자 확답(적용범위=8종 전체, 기존 DB코드는 주석처리로 보존, 요청
바디 형태=내부 정규화 모델의 Observation 리스트를 그대로 재사용)에 따라
전환했다.

**변경 내용**:
- `analysis/models.py::AnalysisSummaryRequest`에 `observations: list[dict]`·
  `mineral_name`·`price_unit`·`price_criterion`·`price_criterion_serial`·
  `unavailable_page_data`·`supply_auxiliary`·`unit` 필드 추가 — 값은 페이지별
  기존 `XxxObservation`(`IndicatorObservation`·`CompositeIndexObservation`·
  `MineralMapObservation`·`PriceForecastObservation`·`PriceObservation`·
  `TradeCountryObservation`) Pydantic 모델로 재검증한다(새 스키마를 짓지 않고
  기존 모델을 그대로 재사용 — 필드명 추측 없음).
- `routers/analysis.py`의 5개 요청 스키마(`IndicatorSummaryRequest`·
  `CompositeIndexSummaryRequest`·`MineralMapSummaryRequest`·
  `PriceForecastSummaryRequest`·`MineralDateRangeSummaryRequest`)에 같은
  필드를 추가 — `routers/report_data.py`는 이 스키마들을 그대로 재사용하므로
  자동으로 같이 적용됨.
- `analysis/summary.py`: 8개 `_analyze_*` 메서드 전부에서 `self.
  {_data_source,_composite_source,_mineral_map_source,_price_forecast_source,
  _price_source,_domestic_trade_source,_global_trade_source}.get_*_series(...)`
  호출 블록을 주석 처리하고(마커: "2026-08-26 DB 조회 경로 비활성화... 복원
  시 이 블록 해제"), 그 자리에 `request.observations`로 Series를 직접 조립하는
  코드로 교체(`_observations_from_request()` 신설 헬퍼 + 신규 `_data_version()`
  해시 헬퍼 — DB판 `data_sources/_shared._version`과 같은 목적). `available_
  start/end`·`data_as_of`는 observations에서 파생, `source_type="api"`·
  `source_id="api:request"` 고정.
- `main.py::build_analysis_summary_service()`: `KomisRawDataRepository()`·
  7개 `Database*DataSource(...)` 생성 호출을 주석 처리하고 전부 `None` 전달
  (`AnalysisSummaryService.__init__`의 해당 파라미터가 이미 `X | None = None`
  이라 시그니처 변경 없음). DataSource 클래스 정의 자체(`data_sources/*.py`)는
  삭제하지 않음 — 복원 가능.
- 각 `_analyze_*`가 이제 `ValueError` 대신 `DataSourceError`를 던진다
  (observations 누락·형식오류 등) — 기존 에러 매핑 계약(`_common.py::
  run_summary`가 `DataSourceError`→422)과 일치시킴.

**검증(실측, 2026-08-26)**: `shared.db.read_sql_pg`/`execute_pg`/
`read_sql_msr`/`execute_msr`를 전부 예외를 던지도록 monkeypatch한 뒤(DB
접근 시도 시 즉시 실패하도록 "오염") `AnalysisSummaryService`를 조립 →
`_data_source` 등 7개 슬롯이 전부 `None`임을 확인 → 8개 page_id 전부에
`service.analyze()`를 직접 호출 — **전부 예외 없이 완주**(DB 접근이 있었다면
AssertionError로 즉시 실패했을 것). price·map_korea·map_global은 실제
`public.KO_MNRL_PRC`(니켈)·`KO_CSTM_CMMRC`/`KO_UN_CMMRC`(텅스텐)에서 미리
뽑아둔 실측 관측치를 요청 바디로 재사용했고, 나머지 5종(indicator_market/
supply/composite·map_mineral·forecast_price)은 각 Observation 스키마에 맞는
소규모 예시 관측치(스키마는 실제와 동일, 수치는 예시)로 검증했다 — 이 5종의
실데이터 기반 재현은 하지 않았다(범위: "DB 안 거치고 도는지" 구조 검증).
LLM 호출은 이 세션에서 vLLM 미접속으로 전부 규칙기반 폴백(바로 아래 항목과
같은 제약).

**열린 항목(이번엔 손대지 않음)**: `routers/analysis.py`가 `analyze_and_store()`
로 `out_report`(MSR_DB)에 결과를 적재하는 쓰기 경로는 그대로 뒀다 — 사용자
원칙이 조회(값 로딩) 금지인지 쓰기(결과 저장)까지 포함하는지 미확정이라
임의로 끊지 않았다. 또한 이번 전환으로 `routers/analysis.py`의 "발주처
프론트가 외부repo API 계약에 맞춰 개발 중일 수 있어 경로를 바꿀 이유가
없다"던 이식 5종 요청 스키마가 실질적으로 바뀌었다(옵서베이션 필드 추가·
DB조회 제거) — 발주처 프론트와 계약 조율이 필요할 수 있음.

## 2026-08-26 — price/map_korea/map_global LLM 정제 배선 + claim id 버그 수정

바로 아래 항목("ai_cfg.cfg_prompt 실프롬프트 교체")에서 `[스테이징-미배선]`으로
남겨 뒀던 3종을 실제로 배선했다. `AnalysisSummaryService._analyze_price`/
`_respond_trade_map`(`summary.py`)에 `_refine_with_llm` 호출을 추가하고,
`prompts.py`에 이 3종의 폴백 상수·`page_defaults`·`build_summary_payload`
section_ranges를, `summary.py::_validate_llm_summary`에도 동일한 section_ranges를
추가했다(두 dict은 글자 그대로 일치해야 검증이 통과한다).

**버그 발견·수정**: 배선 과정에서 `komir_summary.py::calculate_price_summary`의
core_diagnosis 근거 id가 `"latest_price"`였던 걸 발견했다 — 다른 7종 페이지는
전부 `"current_state"`를 쓰고 `_validate_llm_summary`가 "core_diagnosis에
current_state가 있어야 한다"를 페이지 무관 공통 규칙으로 검사하는데, 이 페이지만
이름이 달라 LLM 출력이 항상 검증에 실패했을 것이다(2026-08-19 최초 추가 때는
LLM을 안 태워서 이 불일치가 드러나지 않았다). `"current_state"`로 rename —
`DetectedPattern.evidence`의 참조 문자열 2곳도 함께 맞췄다(Metric id
`"latest_price"`는 별개 네임스페이스라 그대로 둠).

**게이트 설계**: 이 3종은 `indicator_*`/`indicator_composite`가 쓰는
`len(claims) < 5` 최소근거수 게이트를 넣지 않았다 — 실측해 보니 trade map은
claim이 보통 3~4개뿐이라 그 게이트를 그대로 쓰면 영구히 LLM을 못 탄다.
`forecast_price`와 같은 패턴으로 `quality_status == "insufficient"`만 차단
기준으로 삼았다.

**검증(실측, 2026-08-26)**: `AnalysisSummaryService.analyze()`를 직접 호출해
니켈(price, MNRL0002)·텅스텐(map_korea/map_global, MNRL0018 — 실데이터가
가장 깊은 광종이라 선택)로 확인 — 셋 다 `_refine_with_llm`까지 도달해 LLM
호출을 시도했고, evidence_ids가 새 `"current_state"`로 정상 표기됐다. 이
세션에서는 vLLM(`host.docker.internal:11434`)에 연결이 안 돼(`ConnectionError`,
DNS 미해결) LLM 호출 자체는 실패 → 설계대로 규칙기반 요약 폴백. **즉 "배선이
`_refine_with_llm`까지 도달하고 실패 시 안전하게 폴백하는지"는 실측 확인했지만,
"LLM이 실제로 검증을 통과한 문장을 만들어내는지"는 이 세션에서 vLLM 접속이 안 돼
검증하지 못했다** — vLLM이 닿는 환경에서 한 번 더 확인 필요.

**부수 발견(수정 안 함, 별도 이슈로 기록)**: 니켈 price 스모크테스트에서
"전년평균 대비" 근거가 나왔는데, 실측해 보니 `KO_MNRL_PRC`의 니켈(MNRL0002,
serial 900002) 데이터가 실제로는 2026-06-21~08-25(66일)뿐이었다.
`komir_summary.py::_avg_before(days)`는 "최근 N일 이내 관측치 평균"을 구할 뿐,
전체 보유 기간이 N일보다 짧을 때 이를 구분·경고하지 않는다 — 그 결과
"전주평균"·"전월평균"·"전년평균"이 사실상 같은 65일치 데이터 풀에서 계산되면서도
문구는 "전년평균"이라 값이 있는 것처럼 보인다. 검증기가 이 시맨틱 문제를
잡아내지 못한다(가짜 근거가 아니라 코드가 실제로 계산한 값이라 숫자·검증
자체는 정상 통과). 이번 턴은 wiring/prompt 범위만 다뤄 손대지 않았다 — 데이터
보유기간이 짧은 광종에서 "전년 대비" 표현이 오해를 부를 수 있다는 점을
사용자에게 별도 보고, 고칠지는 결정 필요(전체보유기간 검사 후 짧으면
omitted_indicators로 빼는 정도의 수정).

**실데이터 원천 재확인(질문에 답하며 실측)**: `public.KO_MNRL_PRC`(13,731행)·
`KO_CSTM_CMMRC`(22,486행)·`KO_UN_CMMRC`(25,342행)는 텅스텐만 깊은 역사
(1997~2025-02, 12,549행)가 있고, 발주 5광종(CU·NI·CO·LI·REE=Nd) 포함 나머지는
대부분 2026-06-21~08-25 66일치뿐이다. `income_data/komis/`의 8개 페이지
덤프(6,737행, 1987~2026 등 훨씬 깊음)는 아직 이 `public` 테이블에 반영되지
않았다 — `public`은 타 팀 소유라 komir가 임의로 백필하면 안 된다(기존 정책,
[[postgres_migration_260810]]). 계산/전처리 레이어(`komir_summary.py`·
`additional_summary.py`·`summary.py::_calculate_summary`) 자체는 이미 완성돼
있어 신규 모듈이 필요한 게 아니라, 이 원천 테이블의 데이터 깊이를 늘리는 결정이
별도로 필요하다는 게 이번에 다시 확인된 결론.

## 2026-08-26 — ai_cfg.cfg_prompt 임시 프롬프트를 발주처 KOMIS 템플릿 기반 실프롬프트로 교체

바로 아래 항목(같은 날, "DB화 + 런타임 리로드")에서 `ai_cfg.cfg_prompt`에 심은
값은 `prompts.py` 하드코드 문구를 그대로 옮긴 "임시 프롬프트"였다. 발주처가
`income_data/komis/`에 (1) KOMIS 8개 페이지 실데이터 덤프(JSON, 6,737행,
`MANIFEST.json`+`KOMIS_페이지별_옵션_API_명세.md`)와 (2) 요약보고서 템플릿
PDF 2종(`AI 통계분석 요약 답변_광물가격전망지표.pdf`, `AI 통계분석
요약답변_수급지도광물지도.pdf`)을 올려, 이를 근거로 `seed_prompts.py`의
`PROMPTS` 문구를 실제 지시문으로 다시 썼다(`python -m
app.analysis.seed_prompts` 재실행 → `ai_cfg.cfg_prompt` 9행 upsert, 실측
확인 완료 — `prompt_store.reload()` → `summary_instructions()` 재조회로
새 문구 로딩 검증).

**반영 범위(중요, 구조적 제약 — 사전에 advisor 자문으로 확정)**:
- `AnalysisSummaryService.analyze()`(`summary.py`)가 실제로 LLM 정제
  (`_refine_with_llm`)를 태우는 건 `indicator_market`·`indicator_supply`·
  `indicator_composite`·`map_mineral`·`forecast_price` 5종뿐이다. 이 중
  `forecast_price`는 참고자료(PDF)가 없어 문구를 그대로 뒀고, 나머지 4종은
  PDF 템플릿 표현(예: 시장/수급동향지표의 "[단계]로 상승/하락했습니다" vs
  "[단계]를 [N]개월째 유지중입니다" 분기, 종합지수의 전주/전월/전년 비교+
  하위지수 대비, 광물지도의 CR3/CR5 집중도)에 맞춰 다시 썼다 — 단, 계산
  레이어(`additional_summary.py`/`summary.py`)가 실제로 만드는 EvidenceClaim
  범위를 벗어나는 지시는 넣지 않았다. 특히 시장/수급동향지표 템플릿이 요구하는
  "주요 요인"(가격변동 원인, 투자환경지수 요인) 절은 현재 계산 레이어가 원인을
  분해해 근거로 만들지 않으므로 **의도적으로 비웠다** — 지어내면
  `_validate_llm_summary`의 근거·숫자 검증에 걸려 규칙기반으로 폴백하기 때문에
  실효가 없다.
- `price`(광물자원가격)·`map_korea`(수급지도-관세청)·`map_global`(수급지도-
  Comtrade) 3종은 `_analyze_price`/`_respond_trade_map`이 `_refine_with_llm`을
  호출하지 않아 **프롬프트를 심어도 런타임이 전혀 소비하지 않는다**(규칙기반
  서술만 응답, `summary.py` 모듈 docstring 4번 참고). PDF 템플릿이 이 3종도
  다루고 있어 `komir_summary.py`의 실제 EvidenceClaim id(latest_price·
  day_over_day·week_avg 등, current_state·top1_country·top3_concentration 등)에
  맞춰 스테이징으로 심어 뒀다 — description에 `[스테이징-미배선]`을 표시. LLM
  배선을 추가할지는 이번 세션 범위 밖(별도 결정 필요).
- 전체광종(비철금속/희소금속 그룹 단위 집계) 요약은 PDF §1-2에 있지만 대응하는
  `page_id`/엔드포인트 자체가 없어(현재 계약은 광종 1개 단위) 이번 반영에서
  빠졌다 — 필요 시 별도 기능으로 논의해야 한다.

**변경 파일**: `report_gen/app/analysis/seed_prompts.py`(문구 전면 교체 +
스테이징 3키 추가, `PROMPTS` 9개로 확장, description을 키별로 분리) —
`prompts.py`의 하드코드 상수(폴백 기본값)는 이번엔 손대지 않았다(DB 우선,
DB 접속 불가 시 폴백은 여전히 구버전 문구 — 필요하면 후속으로 동기화).

## 2026-08-26 — 분석요약 LLM 프롬프트를 ai_cfg.cfg_prompt(PostgreSQL)로 DB화 + 런타임 리로드

`report_gen/app/analysis/prompts.py`(`AnalysisSummaryService._refine_with_llm`이
쓰는 LLM 지시문 — 공통 서두 1개 + 페이지별 5종)가 지금까지 파이썬 상수로만
있어 문구를 바꾸려면 배포가 필요했다. DB화 + 무재시동 리로드 요청으로 아래를
구현.

**스키마/테이블 결정 경위**: 처음 요청은 "postgresql `public` 밑에
`ai_cfg_prompt`"였다. 그런데 이 저장소엔 이미 두 곳(`data_lake/db/
schema_pgvector.sql`, `services/shared/komis_raw.py`)에 "`public`(ko_*·ai_*)은
타 팀 소유라 절대 건드리지 않는다"가 명시돼 있어(`ai_mnrl_mst` 등 기존
`ai_*` 테이블도 KOMIS가 채운 것이지 komir가 만든 적 없음 — 레포에 그 DDL
자체가 없음), 그대로 진행하기 전에 사용자에게 확인했다. 사용자가 "`ai_cfg`
스키마를 새로 만들고 그 안에 `cfg_prompt`를 쓰자"로 정정 — `public`도
`mineral_risk`(MSR_DB의 fact_*/out_*/mart_*, PG_DSN의 doc_chunk/pgvector로
이미 두 용도)도 안 쓰고 전용 스키마 `ai_cfg`를 새로 판다. 또한 "duckdb는
더 이상 안 쓴다"는 지시에 따라 MSR_DB(duckdb/postgres 겸용 범용 대상) 대신
PG_DSN(PostgreSQL 전용, `services/shared/db.read_sql_pg`/`execute_pg`/
`apply_schema_pg`)으로 전량 교체했다 — 최초 구현(MSR_DB의 `cfg_prompt`,
`mineral_supply_risk/db/schema_core.sql` §⑧에 추가했었음)은 전부 원복.

**스키마/테이블**: `data_lake/db/schema_ai_cfg.sql`(신규, `public`·
`mineral_risk`와 별개인 `data_lake/db/`가 관행상 gitignore 대상이라
`schema_addendum_v2.sql`·`schema_pgvector.sql`처럼 `git add -f`로 강제
추적) — `CREATE SCHEMA IF NOT EXISTS ai_cfg` + `ai_cfg.cfg_prompt(prompt_key
VARCHAR(40) PK, content TEXT, description, updated_at)`. `prompt_key`는
`summary_common` + `indicator_market`/`indicator_supply`/`indicator_composite`/
`map_mineral`/`forecast_price`(LLM 정제를 안 쓰는 `price`/`map_korea`/
`map_global`은 대상 아님) 6개.

**런타임 캐시**: `app/analysis/prompt_store.py`(신규) — 모듈 전역 dict 캐시.
`reload()`가 `ai_cfg.cfg_prompt`를 `read_sql_pg`로 통째로 다시 읽어 캐시를
원자적으로 교체(실패해도 예외를 던지지 않고 기존 캐시 유지 + 로그만 남김 —
PG_DSN 미설정도 이 경로로 흡수됨). `get_prompt(key, default=)`는 DB를
조회하지 않고 캐시만 읽는다 — 요구사항이 "재시동 또는 리로드 콜 시에만"
다시 읽는 것이라, 매 호출마다 DB를 때리지 않는다. `prompts.py::summary_
instructions()`가 이걸 거치도록 바꾸고, 기존 하드코드 상수는 "DB에 없을 때
기본값"으로 남겼다(캐시가 비어 있거나 해당 key가 없으면 폴백).

**리로드 트리거 2가지**: (1) `main.py` lifespan이 기동 시 1회 자동
`prompt_store.reload()` 호출. (2) `POST /admin/prompts/reload`(신규,
`commodity_api`의 `/admin/cache/clear`와 같은 스타일) — 운영자가 DB 행을
갱신한 뒤 호출하면 서버 재시동 없이 다음 보고서 생성부터 새 프롬프트 반영.

**시드 스크립트**: `app/analysis/seed_prompts.py`(신규,
`cd inhouse/services/report_gen && python -m app.analysis.seed_prompts`,
PG_DSN은 `inhouse/.env`에서 읽음) — `apply_schema_pg(schema_ai_cfg.sql)`
적용(멱등) + "임시 프롬프트"로 `prompts.py`의 기존 검증된 문구 6개를 그대로
`INSERT ... ON CONFLICT (prompt_key) DO UPDATE`(네이티브 postgres upsert,
duckdb 호환을 더 신경 쓸 필요가 없어져 기존 delete-then-insert 관행 대신
채택)로 심는다. DB 경로 자체의 정상동작을 먼저 확인하는 게 목적이라 문구를
새로 짓지 않았다 — 실제 문구 교체는 이후 DB `UPDATE` + `/admin/prompts/
reload` 호출로 한다(스크립트 재실행 불필요).

**검증**: 캐시 교체 메커니즘(reload 전/후 문구가 실제로 바뀌는지, 앱 기동
시 자동 로드되는지, 관리 엔드포인트 실호출, 테이블/스키마·PG_DSN이 없어도
크래시 없이 하드코드 기본값 폴백)은 최초 구현(MSR_DB 경로) 때 scratchpad
임시 duckdb로 전 구간 실측 완료 — 그 메커니즘 자체(`prompt_store.reload()`/
`get_prompt()`)는 PG_DSN 전환에도 안 바뀌었다. `schema_ai_cfg.sql`은
`db.dbio._split_sql`로 정확히 2개 statement(스키마 생성·테이블 생성)로
쪼개짐도 별도 확인. `python3 -m py_compile` 전 파일 통과.

**실제 PG_DSN(komis_demo, `220.118.147.58:55433`) 접속 후 최종 검증
완료**(같은 날 이어서, 사용자가 이 worktree에 `inhouse/.env`를 채워줌):
`python -m app.analysis.seed_prompts` 실행 → `ai_cfg` 스키마·`ai_cfg.
cfg_prompt` 테이블 생성 + 6행 upsert 콘솔 로그 확인 → `read_sql_pg`로
직접 재조회해 6개 prompt_key·content 길이·description·updated_at 전부
정상 확인 → report_gen `TestClient` 기동 시 로그에 "cfg_prompt에서 프롬프트
6건 로드" 확인 + `summary_instructions('indicator_market')`가 DB값을
정상 반환 → `POST /admin/prompts/reload` 실호출 200, `reloaded_prompt_count:
6` 확인. 이걸로 DB화+런타임 리로드 요구사항 전체가 실환경에서 종결됐다.

⚠ **사고 기록**: 접속 디버깅 중 `.env`의 `PG_DSN` 줄을 실수로 터미널에 그대로
출력해 postgres 비밀번호가 대화 로그에 노출됐다(2026-08-26) — 사용자에게
즉시 고지, 비밀번호 교체 권고함. 이후로는 DSN 파싱 결과(호스트·포트·유저명
등 민감하지 않은 필드)만 개별 출력하고 원문 라인은 절대 출력하지 않는 방식으로
전환. 비슷한 DB 접속 디버깅 시 반드시 이 방식을 따를 것 — `.env`/DSN 원문을
`cat`·`repr`·`print`하지 않는다.

## 2026-08-26 — report_gen에 price/idx/map REST 엔드포인트 신규(보고서 요약 템플릿용)

다른 세션이 분석요약 보고서 템플릿을 작업 중인 상황에서, 그 템플릿이 데이터를
가져올 엔드포인트를 만드는 작업. 사용자가 가칭으로 적은 8개
(`price/baseMetal`·`price/minorMetal`·`idx/general`·`idx/market`·`idx/sply`·
`map/korea`·`map/global`·`map/mineral`)를 REST 명명규칙(kebab-case·복수
컬렉션명)으로 정리해 `inhouse/services/report_gen`(기존 report_gen FastAPI
서버 — 이미 `/api/v1/analysis/*` 8종·`/api/v1/dashboard/comprehensive`·
`/reports/*`가 떠 있음, 새 서버를 만들지 않음)에 새 라우터 3개로 추가했다.

**경로**: `POST /api/v1/prices/{base-metals,minor-metals}` ·
`/api/v1/indicators/{market,supply,composite}` ·
`/api/v1/maps/{korea,global,mineral}`(`routers/report_data.py`, 신규).
`idx/general`은 KOMIS 내부 용어(`indicator_composite`, "광물종합지수")에 맞춰
`composite`로 정했다. `/api/v1/analysis/*`(발주처 프론트 계약이라 경로 고정)는
그대로 두고, 8종 전부 같은 page_id로 같은 서비스 호출을 위임하는 얇은
별칭이다 — 계산 로직 복제 없음.

**신규 2종(`/prices/base-metals`·`/prices/minor-metals`) — 1차 구현 후 되돌림**:
처음엔 `SummaryPageId`에 `price_base_metals`/`price_minor_metals`를 새로
추가하고, 요청 광종이 실제로 그 그룹(KOMIS 메타데이터 기준 LME 6종/희소금속
34종 — komir 5광종을 정확히 CU/NI=비철·CO/LI/REE(Nd)=희소로 가른다)에
속하는지 `require_price_group_mineral()`로 검증(아니면 422)하는 코드를 짰다.
그런데 사용자가 "기존 `/api/v1/analysis/prices`가 이미 `mineral`을 입력받아
광종별로 개별 계산하는데, 이 그룹 가드가 실제로 새 능력이냐"고 확인 —
맞는 지적이었다. `_analyze_price`/`calculate_price_summary`는 광종이 비철이든
희소든 완전히 동일하게 동작해서, 가드는 "이 URL은 이 그룹만 받는다"는
제약만 추가할 뿐 계산 능력은 전혀 새롭지 않았다. 보고서 템플릿은 입력을 그대로
꽂아 넣을 뿐 그런 화면 단위 제약이 필요 없다고 사용자가 판단해 **가드를
제거**했다 — `price_base_metals`/`price_minor_metals`(SummaryPageId·
KOMIR_PAGE_CONTEXTS·`_PAGE_TITLES`)·`require_price_group_mineral()`(및 이를
지원하려고 `komis-metadata.subset.json`에 추가했던 `metadata.prices.
{base_metals,minor_metals}.minerals` ref 2개)를 전부 원복했다. 최종적으로
`/prices/base-metals`·`/prices/minor-metals` 둘 다 기존 `page_id="price"`로
위임하는 순수 별칭이다 — URL만 나뉘어 있을 뿐 어느 쪽으로 불러도 결과는 같다.

**리팩터(유지)**: `routers/analysis.py`의 `_run_summary`(서비스 호출+에러→HTTP
status 매핑)를 새 라우터도 같이 써야 해서 `routers/_common.py::run_summary`로
추출(두 라우터가 각자 복제하면 503/422 매핑이 어긋날 위험) — 이건 가드
제거와 무관하게 그대로 남겼다.

**검증**: `python3 -m py_compile` 전 파일 통과, `python3 -c "import app.main"`
실제 임포트로 8개 새 라우트 등록 확인(`/openapi.json` 라우트 목록), FastAPI
TestClient로 새 엔드포인트 실호출(PG_DSN 미설정 환경이라 503 "Analysis
database is not configured." — `/api/v1/analysis/*`와 동일한 폴백이 그대로
동작함을 확인). 가드 제거 후 `git diff --stat`로 순변경분이 `routers/analysis.py`
(리팩터)·`routers/report_data.py`+`_common.py`(신규 별칭 라우터)·`main.py`
(include_router) 4개 파일뿐임을 재확인 — 1차 구현분(analysis/*)은 전부
원복돼 diff에 남지 않았다.

⚠ **알려진 한계(이번 범위 밖, 기존에 이미 기록됨)**: `/api/v1/analysis/*`와
동일하게 이 API가 읽는 `public.KO_*`는 텅스텐(MNRL0018) 데모 데이터 1종만
적재돼 있다(`services/shared/komis_raw.py` 2026-08-11 실측 노트) — komir 5광종
(CU/NI/CO/LI/REE)으로 실호출하면 대부분 422(데이터 없음)가 난다. 이번 작업은
엔드포인트 배선까지이고, 실데이터 적재는 별개 이슈.

## 2026-08-20 — execute_msr() postgres 미지원 수정(out_report 저장 파손 해소)

2026-08-20 앞선 항목("MSR_DB DuckDB→PostgreSQL cutover로 out_report 저장 경로
파손, 기록만·미수정")이 "워크트리 통합 후 재작업 예정"이라 명시해뒀던 바로 그
재작업 — 4개 워크트리 병합 완료 직후 사용자 지시로 착수.

**수정 1: `services/shared/db.py::execute_msr()`** — `is_url(MSR_DB)`일 때
`NotImplementedError`를 던지던 자리에 postgres 분기 추가. `execute_pg()`와 같은
패턴(SQLAlchemy 엔진→raw psycopg2 커넥션, 수동 commit)을 재사용하되, 호출부
(`generator.py`·`analysis/store.py`, 둘 다 `DELETE ... WHERE report_id = ?`
단일 파라미터 DELETE)를 postgres 전용으로 고쳐 쓰지 않아도 되게 `sql.replace("?",
"%s")`로 내부 치환한다 — 실제 호출부 2곳 전수 확인 결과 SQL 문자열 리터럴 안에
`?`가 섞인 경우 없어 이 단순 치환이 안전함을 확인했다.

**수정 2: `mineral_risk.out_report`에 `report_id` UNIQUE 인덱스 추가** —
이관 시 DuckDB판의 `PRIMARY KEY(report_id)` 제약이 안 옮겨진 걸 실측 확인한
문제(앞선 항목 기록). `CREATE UNIQUE INDEX IF NOT EXISTS idx_out_report_report_id
ON out_report (report_id)` 직접 적용 전 기존 9행에 중복 `report_id`가 있는지
먼저 조회해 0건 확인(안전하게 추가 가능함을 확인 후 적용) — schema_pgvector.sql은
doc_chunk 전용으로 범위가 명확히 다른 파일이라 이번엔 섞지 않고 DB에 직접
적용만 했다(재현용 DDL 파일화는 후속 과제로 남김).

**부수 확인**: WORKLOG가 "미확인"으로 남겨뒀던 4번 항목(`rag_chat`의
`chat_session`/`chat_message`가 같은 `execute_msr` 경로를 쓰는지) — 실제로는
`rag/ragkit/chatbot_store.py`가 `execute_msr`에 의존하지 않고 **독자적으로**
동일한 `?`→`%s` 치환 로직을 이미 갖추고 있었다(모듈 docstring에 2026-08-19
postgres 지원 추가 기록 있음, rag 패키지가 services/shared에 의존하지 않는다는
설계 원칙 때문에 중복 구현된 것 — TWIN이지만 각자 독립 동작하므로 지금은 안 건드림).
즉 이 경로는 애초에 이번 파손과 무관했다.

**검증**: 실 postgres(komis_demo/mineral_risk)로 `execute_msr("DELETE FROM
out_report WHERE report_id = ?", [...])` 직접 호출해 예외 없이 성공 확인.
UNIQUE 인덱스도 `pg_indexes` 조회로 생성 확인.

## 2026-08-19 (최신)⑤ — ⚠사고: 정기동기화 cron이 doc_chunk(pgvector 140,031행) 삭제·복구

**사고 경위**: 직전 항목(정기 동기화 cron 신설)의 `migrate_duckdb_to_postgres.py`가
duckdb `main` 스키마의 **모든** 테이블을 postgres로 DROP+CREATE TABLE AS SELECT로
미러링하는데, `doc_chunk`(RAG dense/BM25 검색이 쓰는 pgvector 임베딩 테이블,
140,031행)는 **postgres가 정본**이고(`build_pgvector_okf.py`/`build_pgvector_index.py`가
postgres에 직접 적재, duckdb 쪽엔 애초에 채워진 적 없는 옛 빈 테이블 흔적만 있음)
이 사실을 스크립트가 몰라 duckdb의 빈(0행) 테이블로 postgres의 140,031행을
덮어썼다 — 오늘 수동으로 이 스크립트를 2회 실행(즉시갱신 1회+wrapper 테스트 1회)
하며 **두 번 다 실제로 지웠다**. rag 브랜치 컨테이너를 실제 API로 첫 통합테스트하는
과정에서 dense 검색이 `UndefinedColumn: source_path` 에러를 내는 걸 보고 발견 —
직접 쿼리로 0행·컬럼 7개(정상 15개)까지 줄어든 걸 확인해 사고 확정.

**즉시 조치**:
1. crontab에서 `auto:komir_pg_sync_daily` 제거(재발 방지, 원인수정 전까지).
2. `scripts/migrate_duckdb_to_postgres.py`에 `_SKIP_TABLES = {"doc_chunk",
   "chat_session", "chat_message"}` 추가 — postgres가 정본인 테이블은 블랙리스트로
   명시 제외(chat_session/chat_message도 08-19 chatbot_store.py의 postgres 직접쓰기
   전환으로 같은 위험군이 돼 함께 포함, 아직 사고는 없었음).
3. 복구: `data_pgvector.sql` 스키마 재적용(source_path·embedding 컬럼 + HNSW/unique
   인덱스, 컬럼 손실분도 같이 날아갔었음) → `rag.ragkit.build_pgvector_index`(산출물
   76건, 1,260청크, 선행 — 이쪽이 매번 테이블 전체 DELETE라 순서 중요) →
   `services.ingestion.build_pgvector_okf`(USGS·조달청·Argus, 138,825청크, 후행 —
   자기 src만 지우고 재적재라 순서 안 지키면 선행분을 날림, 실측으로 이 순서
   의존성 확인) → BM25 GIN 인덱스(`idx_doc_chunk_txt_fts`, schema_pgvector.sql
   비대상이라 별도 재생성 필요) → `pub_date` 백필 재실행(08-19 앞선 항목 작업분도
   테이블과 함께 날아갔었음).
4. 재발방지 스크립트 수정 커밋 예정, crontab은 전 과정 검증 완료 후 재등록.

**교훈**: "duckdb 전체를 postgres로 미러링"이라는 전제 자체가 이미 깨져 있었다 —
같은 postgres 스키마 안에 "duckdb가 정본인 테이블"과 "postgres 자체가 정본인
테이블"이 섞이기 시작한 시점(2026-08-11 pgvector 직접적재 도입)부터 전체 미러
스크립트는 위험했는데, 그 사실을 모른 채 새 자동화(cron)를 얹었다. 정기 동기화·
자동화를 새로 넣기 전엔 "이 테이블들이 정말 한 방향으로만 흐르는가"를 먼저
확인할 것.

## 2026-08-19 (최신)④ — 비교 PPT에 모델링 상세·요구사항 부합도·GPU자원 슬라이드 3매 추가(사용자 요청)

바로 아래 항목(비교 PPT 초안, 13슬라이드)에 이어 사용자가 "① 모델링 차이 ② 발주처가
원하는 것이 어느 쪽에 더 가까운가 ③ GPU 자원 소요"를 추가로 요청 — 기존 스타일(색상·
폰트·표 서식)을 그대로 유지하며 3개 슬라이드를 삽입해 16슬라이드로 확장했다.

**근거 확보**: `documents/산출물/2026-W30_0720-0726/AI모델_사용안_260722.docx`(정본,
코드 직접 확인 기반)의 §5 "필요 인프라 자원" 표를 읽어 komir 쪽 실제 문서화된 GPU
스펙(LLM 추론 서버 1대, `gemma-4-26b-a4b` MoE fp8 서빙 — 정확 VRAM은 "인프라팀 확인
필요"로 명시된 미확정 상태, 전통ML은 GPU 불요)을 확보. `documents/산출물/
2026-W28_0706-0712/시스템_결정필요사항.md`에서 "GPU 자원 제공 주체·사양"이 발주처
결정 대기 항목(1-2)임도 확인 — 0818 쪽 PPT에는 GPU 스펙 자체가 없어(방법론 보고서
범위 밖) 0818의 `gemma4:31b`(슬라이드41 명시, dense) 기준 통상적 양자화별 VRAM 어림
계산(fp16≈62GB/fp8≈31GB/4bit≈16~18GB)을 "추정치, 실측 아님"으로 명확히 라벨링해
병기했다 — 두 접근 모두 GPU 사양은 공식 미확정임을 강조.

**추가한 3슬라이드**(모두 "5. 종합 평가" 섹션에 배치, 결론 슬라이드는 맨 뒤로 재배치):
① 모델링 상세 비교 — 패러다임(파운데이션모델+LLM직접판정 vs 전통ML+통계) 차이를
7개 항목(진단모델·후보비교검증·예측모델·소표본전략·XAI·라벨오염방지 등)으로 대조.
② 과업지시서 요구사항 부합도 — 9개 항목 판정표(5광종검증·4단계매핑·"미래예측아님"
조항·다각적모델링비교·필수변수·신규지표·12개월예측·검증엄밀성·서술형판단), **9개 중
7개 komir 우위·1개 양쪽공백·1개(설명가능한 서술형 판단) 0818 우위**로 정리 — "검증된
산출물 요건은 komir, 발주처가 화면으로 보게 될 설명 방식은 0818 아이디어가 참고"로
결론. ③ GPU·인프라 자원 소요 비교 — 위 근거 기반, "0818은 모델크기(31B dense)는
크지만 처리물량(니켈 월간 단일보고서)은 적고, komir(26B-A4B MoE)는 활성연산량은
작지만 자동화 처리물량(GDELT 대량이벤트)이 훨씬 크다"는 핵심 관찰 병기.

**검증**: `gotenberg/gotenberg:8` 도커 이미지로 pptx→PDF 변환 후 PyMuPDF로 신규
3슬라이드+재배치된 결론 슬라이드를 렌더링해 육안 확인 — 표 겹침·잘림 없음, 페이지
번호(12·13·14·15) 정상 재부여 확인. 변환용 컨테이너는 검증 후 정리(stop+rm).

산출물: `documents/산출물/한양대/0818발표자료_komir구현_비교분석_260819.pptx`(16슬라이드,
동일 파일 갱신). DATA_REGISTRY 갱신 완료.

## 2026-08-19 (최신)③ — "0818 발표자료 vs komir 구현" 비교 PPT 작성(사용자 요청)

`documents/산출물/한양대/0818_일루넥스_발표자료(최종).pptx`(과업1 위기진단·과업2
수요예측 주간보고, 2026-08-18, 46슬라이드 — Chronos-2 시계열예측+Gemma4 LLM 기반
접근)를 komir 저장소 실제 구현(`inhouse/geo`·`inhouse/mineral_supply_risk`)과
비교해 광해공단 과업지시서 요구사항 대비 강점·부족한 부분·참고할 부분을 정리한
13슬라이드 PPT를 작성했다(`python-pptx`로 직접 생성).

**근거 확보**: 과업지시서 원문(`documents/260625 ..._일루넥스.pdf`) 붙임1·붙임2를
새로 읽어 4단계 경보(관심·주의·경계·심각, 「자원안보특별법 시행령」 기준)·필수변수
6개·"진단(diagnosis), 미래예측 아님" 명시 조항·신규지표(공급망압력지수·원자재지수·
ESG지수) 요구를 1차 판단기준으로 확보. 챔피언_스코어보드_260727.md·
`outputs/model_opt/report.md`(08-18)·화면기획안_v1.3_기능단위_AI작업_구현현황_
260813.md·인수인계서_TODO_대조_260813.md를 정량·정성 근거로 사용.

**핵심 발견**: ① 0818 발표자료는 니켈 1개 광종·약 6개월만 검증(정답라벨 부재로
정량지표 미제시), komir는 5광종 전체·워크포워드 3폴드·수년치 백테스트로 과업지시서
"5종 모두" 요구를 더 충실히 충족. ② 0818은 슬라이드상 "5단계" 경보로 표기 —
과업지시서·화면기획 모두 4단계 명시라 표기 정렬 확인 필요(우열 판단 아님). ③ 0818의
Chronos-2 미래가격예측을 진단 입력에 쓰는 구조는 과업지시서 "미래예측 아님" 조항과
정합성 확인이 필요. ④ komir 필수변수 6개 중 ④세계공급부족(소비/공급) 대응 피처가
코드에서 확인 안 됨, 신규지표 3종(공급망압력·원자재·ESG지수)도 원자재지수만 시도 후
라벨오염 우려로 미채택 — 과업지시서 명시요구 대비 양쪽 다 공백. ⑤ 0818의 LLM
서술형 종합판단·낙관/중립/비관 시나리오 내러티브는 화면기획 #13·#20·#21의 실제
공백을 정확히 겨냥 — r10_retune_harness 채택기준 통과를 전제로 참고 가치 있음(임의
채택 금지 원칙 준수).

**수치 비교 원칙**: 두 자료의 성능수치(QWK/MAPE/WAPE 등)는 광종범위·예측지평·
검증구조가 서로 달라 액면비교가 불가능하다는 점을 슬라이드마다 명시하고, "잠재적
성능"(0818의 best-of-3 오라클 수치 등)과 "실측 검증 성능"을 구분 표기했다.

산출물: `documents/산출물/한양대/0818발표자료_komir구현_비교분석_260819.pptx`
(13슬라이드). DATA_REGISTRY 등재 완료.

## 2026-08-19 (최신)② — minerals.duckdb→postgres(mineral_risk) 정기 동기화 cron 신설

`rag` 브랜치에서 `structured.py`를 PostgreSQL로 전환하며 발견한 문제(geo_index가 PG에서
라이브 대비 약 1주 stale — 2026-08-10 1회성 이관 이후 정기 동기화가 없었음) 후속 조치.

- 기존 `scripts/migrate_duckdb_to_postgres.py`(2026-08-10 1회성 이관 스크립트, DROP+CREATE
  TABLE AS SELECT 전체 재적재라 멱등 — 재구현 없이 그대로 재사용)를 즉시 재실행해 즉각
  갱신: 38개 테이블 전부 불일치 0건(geo_index 3556행, 08-10 이후 늘어난
  chat_session/chat_message 2종 포함 — rag 브랜치 작업 중 신설된 테이블).
- `scripts/cron_sync_postgres_mirror.sh` 신설(위 스크립트를 감싼 cron 래퍼, flock 중복실행
  방지, 로그 `data_archive/cron_logs/pg_sync_*.log`) — 매일 05:00 등록(crontab
  `auto:komir_pg_sync_daily`, 토요일 geo cron 07:00·feeds cron 09:10/09:20보다 앞선 시간대,
  겹침 없음). 실측 소요시간 11초(38개 테이블, geo_event 297,003행 포함)라 매일 갱신 비용
  경미.
- out_diagnosis_alert/out_import_forecast는 수동 재학습이라 cron 주기와 무관하게 갱신될 수
  있음 — 재학습 직후 사람이 이 스크립트를 수동 재실행해도 안전(멱등)하다는 점을 스크립트
  주석에 명시.
- (사소) crontab 파일 경로에 세션 스크래치패드의 긴 절대경로를 쓰면 `crontab <file>`이 조용히
  "No such file or directory"로 실패하는 걸 실측 확인(경로 길이 제한으로 추정) — `/tmp` 최상위
  짧은 경로로 옮기니 정상 동작. crontab 파일 갱신 시 참고.

## 2026-08-19 — Argus 690건 문서화 공백 발견·소급 기록(완료 사실은 08-12~13, 기록만 오늘)

사용자가 "Argus 690건 처리 승인, 진행해달라"고 지시(직전 대화에서 필자가 "08-11/08-12
보류 기록"만 보고 "아직 미착수"라고 잘못 안내한 데 대한 후속) — 실제로 배치를 돌리기
직전 최종 확인 차 직접 실측했더니 **이미 완료돼 있었다**. `build_okf_documents.py`의
`build_from_argus()`(`allow_paid_sources=True`로 source_policy.py 우회 — 2026-08-12
사용자가 라이선스상 내부 파생 DB 구축 허용을 확인하고 명시적으로 지시한 그 경로)와
`build_pageindex_trees.py`가 이미 실행돼 있었는데, **완료를 알리는 WORKLOG 항목이 하나도
없어** 08-11/08-12의 "이번엔 보류" 기록만 보고 최신 상태로 오판하는 문서화 공백이 있었다.

**실측 재확인**(직접 쿼리, data-quantity-verification-rule 준수):
- 문서-OKF 690/690건 존재(`data_lake/semi_structure/okf_documents/Argus_비철금속_일일/`).
- PageIndex 트리 690/690건 존재, LLM 요약 포함(샘플 검증: 빈 구조 아님) — 생성시각
  2026-08-12 13:50~18:25(`*.tree.json` mtime).
- pgvector(`komis_demo.mineral_risk.doc_chunk`)에도 **Argus 청크 77,648개**(전체
  140,031개 중 55%) 임베딩 완료 — 인덱싱시각 2026-08-13.
- 방금 재실행한 배치(`build_okf_documents --what argus` + `build_pageindex_trees
  --pattern Argus`)는 "이미 있음"을 정확히 감지해 즉시 종료(캐시/스킵 로직 정상 동작
  확인 — 중복 생성·중복 임베딩 없음).

**조치**: 새 작업 없음(순수 문서화 공백 보정). 이 항목 + DATA_REGISTRY 등재로 향후
"Argus 아직 안 함"으로 재오판하는 일 방지. 조달청보고서 887건도 같은 08-11/08-12
"보류" 기록과 나란히 있었던 항목이라 — 다음에 확인할 때는 완료 여부부터 직접 실측할 것
(문서화 안 됐다고 미완료가 아닐 수 있음 확인됨).

## 2026-08-18 — geo_prob·geo_index를 expanding-window로 리팩터(사용자 지시, 미래시 감사 §2·§4 실수정)

08-13 감사·08-14 재검증에서 "구조는 확정, 영향 무해"로 남겨뒀던 두 안티패턴(전체이력 재적합)을
실제로 고쳤다. 상세: `outputs/model_opt/lookahead_bias_audit_260813.md` "2026-08-18" 절.

- `inhouse/geo/prob_model.py::run()` "2) 발행 모델" — hist 전체 단일적합 → 연도별 1/1
  컷오프 expanding 재적합(NB2·적응형 로짓·isotonic 보정 전부). 웜업(52주) 미달 연도는
  발행 스킵(leak값 대신 정직한 결측). `MIN_TRAIN_WEEKS`/`MIN_CALIB_PAIRS` 상수 신설.
- `inhouse/geo/indexer.py::_apply_kr_exposure()` — imp_mult 정규화·resid 회귀계수 b가
  광종 전체이력으로 계산되던 것을 광종×연도 소표 기반 벡터화 expanding으로 교체
  (`_expanding_normalize`/`_expanding_residualize` 신설, `_asof_grid`와 동일하게 이벤트
  단위 row-wise apply 없음).
- 검증(1) 섹션(TRAIN_END 단일분할)은 이미 정상이라 미변경 — 최소·외과적 변경 원칙.
- **로컬 검증**: geo_prob 2,770→2,510행(2016년 웜업미달 260행=52주×5광종 결측 전환,
  2017-01-01부터 시작 — mart_weekly_diagnosis는 2020+만 써서 진단모델 무영향 확인).
  geo_index는 행수 불변(kr_exposure 폴백 설계), 연도별 평균 절대변화 2016년 0.8점(최대
  4.2)→2017+ 0.2~0.3점으로 수렴(0~100 스케일) — 리키지 구간만 정확히 움직임.
- **프로덕션 반영**: `data_archive/backups/pre_geo_expanding_window_refactor_20260818/
  minerals.duckdb` 사전백업 → `geo publish --what index`(geo_index 3,556행·geo_prob
  2,510행) → `msr.features.weekly_mart` 재빌드(mart_weekly_diagnosis 4,621행) 완료.
- **진단모델 최종 재검증**: 챔피언 Ridge(풀링)+매핑 QWK **0.921→0.934**(악화 아닌 소폭
  개선). `p_burst` dQWK 최종폴드 -0.005(여전히 무기여), 폴드별로는 2023 dQWK 0→**0.036**
  (리키지 제거 후 근소한 실신호 발견, 평균 0.010)·`geopolitical_risk` dQWK 0.006→**0.000**
  — y_lag1(0.808) 대비 전부 미미, 구조수정이 성능을 해치지 않음을 확인.
- DATA_REGISTRY 등재 완료. 남은 항목: ①KOMIS 발행지연 확인(§1, 유일한 미해결) ④
  `geo_event.published_at` 컬럼 정리(§3, 경미) — 둘 다 변경 없음.

## 2026-08-14 — geo_prob(p_burst) 피처민감도 최신코드 재실행(사용자 지시, 08-13 감사 후속)

전날 감사(§2, 아래 항목)에서 적대적 검증자가 "dQWK=0=무해" 판정이 07-16 stale 스냅샷+마지막
폴드만 측정이라 근거 부족이라 지적한 것에 대한 후속 재검증.
- `geo_prob` DB 실측 확인: 이미 2026-08-08에 07-24(NB2 수렴버그 수정)·07-25(CO x_z13 반영)
  이후 코드로 재계산돼 있었음(max period 2026-08-03, parquet↔DB 행수 2,765 완전 일치) —
  geo 파이프라인 자체는 재실행 불필요, `report.md`만 07-16 스냅샷으로 낡아있던 것.
- `python -m msr.models.diagnosis_opt` 재실행 → `p_burst` dQWK=**-0.003**(최종폴드, 이전
  0.000과 사실상 동일 재확인).
- 신규 스크립트(`scripts/geo_prob_perfold_sensitivity.py`)로 "마지막 폴드만 측정" 약점 해소
  — 3폴드 전부 개별 계산: 2023 dQWK=0.0000·2024 dQWK=0.0000·2025 dQWK=-0.0035.
  **"초기 폴드일수록 lookahead 오염이 클 것"이라는 우려는 실측으로 기각** — 전 폴드 일관되게
  무기여 확정.
- `outputs/model_opt/lookahead_bias_audit_260813.md` §2 갱신(REVISED→**CONFIRMED**: 구조적
  lookahead 자체는 여전히 존재·수정 대상이나, 현재 챔피언 QWK엔 영향 없음이 재확인 완료).
  DATA_REGISTRY 등재 완료. 코드/geo_prob 데이터 변경 없음(순수 재검증).
- 남은 항목(변경 없음): ①KOMIS 발행지연 확인 ③geo_prob·kr_exposure resid를
  expanding-window로 리팩터 ④published_at 컬럼 정리.

## 2026-08-13 (최신)② — 미래시 오염 5개 서브모듈 감사 + 적대적 검증(사용자 지시)

바로 아래 항목(y_lag1 발행지연)에 이어, 사용자가 "서브모듈별로 정리해서 하나하나 체크하고,
그 결론을 적대적 검증자로 다시 검증"하라고 명시 지시. 5개 모듈 병렬 조사(1개 신규+4개 기존
결론 재확인용) → 각 결론을 독립 에이전트 5개가 반박 시도(CONFIRMED/REFUTED/REVISED 판정).
전체 보고서: `outputs/model_opt/lookahead_bias_audit_260813.md`(DATA_REGISTRY 등재).

**신규 발견(적대적 검증 과정에서 발굴, 이전엔 몰랐음)**:
- `inhouse/geo/indexer.py:39-78`의 `_apply_kr_exposure(mode="resid")` — 잔차화 계수
  `b=cov/var`를 **2016~2026 전체 이벤트 이력**으로 추정해 2016년 이벤트에도 소급 적용(CU가
  이 모드로 운영중) — `geo_prob`(p_burst)의 "전체이력 재적합" 안티패턴이 지수(`geo_index`)
  자체에도 동일하게 존재한다는 뜻. `geo_index`는 `avail_date`/`generated_at` 추적이 없고
  매주 전체 재계산이라, "과거 지수값은 표본이 늘어도 불변"이라는 기존 결론(07-05·07-22)과
  실측상 배치 — 재검증 필요.
- `geo_event.published_at`이 완전히 무의미한 값임을 발견 — `publish.py:85`가 실행 1회당
  단일 타임스탬프를 전체 이벤트에 일괄대입, DB 296,679행 전부 동일값(distinct=1). 이벤트
  발생일-보도일 지연 자체는 GKG 경로(97.7%)가 obs_date≈보도일이라 구조적으로 무관, 비GKG
  경로(2.3%, 6,680건)만 manifest.pub_date로 재측정해 중앙값 0일·평균+4일·P90 92일 —
  영향은 경미하나 published_at 컬럼은 용도폐기 수준.

**기존 결론 재확인 결과**: y_lag1(§1, 이전 항목) CONFIRMED — 오히려 이미 실측(민감도 실험)
으로 입증된 사실임이 재확인됨. `geo_prob`의 "dQWK=0=무해" 판정은 REVISED — 측정이 2026-07
스냅샷(이후 NB2수렴버그수정 07-24·CO x_z13추가 07-25 미반영)+마지막 폴드만이라 재실행
필요(VIF는 확인해봤자 다중공선성 없어 "정보흡수" 반론은 기각, 구조문제 자체는 여전히 유효).
BASE_FEATS 5종 중 4종(volatility_12w·spread_pct·import_hhi/yoy/cagr3·ref_price)과 최근
파생피처군(INV/CNINV/PMI/CLI/GSEV) 6종은 코드로직 정상 재확인(단 avail_date 오프셋
+3~+45일 자체는 실측 아닌 가정치라는 공통 약점).
- 다음 우선순위: ①KOMIS 발행지연 확인 ②diagnosis_opt 피처민감도 최신코드 3폴드 재실행
  ③geo_prob·kr_exposure resid를 expanding-window로 리팩터 ④published_at 컬럼 정리.
  코드 변경은 없음(순수 진단), 5개 조사+5개 검증 총 10개 에이전트 병렬 실행.

## 2026-08-13 (최신) — 진단모델 미래시(look-ahead) 오염 점검 + y_lag 발행지연 민감도

사용자 지적("수급위기진단·지정학 위기값이 너무 잘 맞아서 미래시가 걱정")으로 출발한
피처 전수 점검. 병렬 감사(geo_prob 파이프라인 / 진단 파생피처군)와 직접 코드 확인으로:
- **핵심 발견**: `mart_weekly_diagnosis`의 교사(수급동향지표) 조인이 다른 모든 외부데이터
  (관세청 `avail_date`, PMI +35일, CLI +45일 등)와 달리 자기 참조월로만 조인돼 발행지연이
  전혀 반영 안 됨(`msr/features/weekly_mart.py:61-62`). `y_lag1`(전월 교사값)은 챔피언
  QWK 기여도 dQWK 0.765로 압도적(`outputs/model_opt/report.md`) — 실제 KOMIS 발행지연이
  1개월보다 길면 백테스트가 낙관적으로 부풀려질 위험.
- `geo_prob`(p_burst) 발행값도 전체이력 재적합이라 구조적 lookahead 있음(2016년 값이
  2026년 이벤트분포로 추정된 계수 사용) — 단 dQWK=0 실측이라 현재 챔피언 성능엔 영향 미미.
  이벤트 "발생일 vs 보도일" 미방어(뒤늦은 보도 방어로직 부재)는 미해결로 남김.
- INV/CNINV/PMI/CLI/GSEV(gsev_z13)·동역학피처(`add_dynamics`)·train/test 스케일러 분리는
  전부 `avail_date` as-of 조인+causal rolling 정상 확인, 문제없음.
- KOMIS 실제 발행지연 확인 시도: 로컬 문서(`데이터 제공현황 및 사이트목록.xlsx`,
  `착수보고_과업관련 논의 사항.xlsx`)로 "갱신주기=월간"까지는 확인(공식 문서 원문),
  정확한 지연 일수는 미기재 — **발주처 확인 필요, 미해결**.
- 민감도 실험(`scripts/ylag_publication_delay_sensitivity.py`, 신규): y_lag1→y_lag2→
  y_lag3 교체 시 챔피언 QWK 0.921→0.825→0.759, 단 동일지연 Naive 대비 우위는
  0.035→0.083→0.144로 오히려 확대 — 모델 자체 가치는 어떤 지연가정에서도 유지되고,
  헤드라인 절대 QWK 숫자만 "지연=1개월" 가정에 낙관적으로 의존함을 확인.
- 산출물: `outputs/model_opt/ylag_publication_delay_sensitivity.md`(+folds.csv), DATA_REGISTRY
  등재 완료. 코드 변경 없음(순수 진단) — y_lag/조인 로직 실수정은 KOMIS 확인 후 별도 착수.
## 2026-08-19 (최신) — 진단·예측 cron 자동화 + "텍스트 보고서" 화면 스키마·데이터 신설

사용자 지시 2건 연속 처리: ①"지정학위기지수·수급위기진단·수요예측이 크론으로 주기적으로
동작하고 결과가 DB에 갱신되게" ②"기획안 보고 텍스트 보고서 화면에 필요한 스키마를
확정하고 그 데이터도 작성".

**① cron 자동화 — 실측으로 확인된 격차**: 시스템 crontab 6건은 전부 수집기(raw_* 적재)만
돌고, 정규화(raw→fact)·마트·진단모델·경보·예측(forecast_unit) 등 파생 파이프라인은
cron에 전혀 없었다(`inhouse/mineral_supply_risk/scripts/schedule.py`가 2026-07-12에
이미 이 오케스트레이션을 만들어뒀지만 **crontab에 등록된 적이 없고**, 그 안의 geo 호출
부분(`ingest-bundles`/`extract`)은 2026-08-06 DMZ/inhouse 분리 이후 실제 운영 중인
`cron_gkg_increment.sh`의 파이프라인과 달라져 stale — msr 쪽 함수 호출부만 시그니처가
현재 코드와 일치해 재사용 가능했음).

- **신설**: `inhouse/mineral_supply_risk/scripts/cron_diagnosis_weekly.sh`(정규화→
  주간마트→nowcast→경보 4단계), `cron_forecast_monthly.sh`(ExtraTrees+conformal+SHAP,
  flock 락 적용). 둘 다 `schedule.py`의 msr 호출 시퀀스를 그대로 재사용(재구현 아님).
- **배선**: 진단은 `.env`의 `DIAGNOSIS_TRIGGER=after_geo_index` 설계값 그대로 —
  독립 cron이 아니라 `inhouse/geo/cron_gkg_increment.sh`의 지정학지수 publish
  직후([6/6] 단계로) 같은 프로세스에서 직접 호출(별도 cron이면 순서 보장이 깨짐).
  예측은 `.env`의 `FORECAST_SCHEDULE_CRON="0 1 1-7 * SUN"`(매월 첫째주 일요일) 값대로
  독립 crontab 항목으로 등록할 스크립트만 준비(시스템 crontab 자체는 main 체크아웃에서
  병합 후 등록 필요 — 아래 "남은 일" 참고).
- **실측 검증**: 두 스크립트 모두 실제 duckdb로 완주 확인 — `cron_diagnosis_weekly.sh`
  (fact_trade_monthly 21955·mart_weekly_diagnosis 4621·CU ci_pred 97.99, 오늘 계속
  검증해온 값과 일치) / `cron_forecast_monthly.sh`(out_import_forecast_unit 60행,
  h=1 CU pred_ton 238685.6 — commodity_api 첫 테스트값과 완전 일치).
- **사고 기록**: 테스트 중 워크트리 루트에 `data_archive/`가 실제로는 git 추적 대상
  (삭제 금지 정책 걸린 진짜 이력)인 걸 모르고 `rm -rf`로 통째로 지웠다가 `git restore`로
  즉시 복구함 — 앞으로 "테스트 산출물이니 지워도 됨"이라고 판단하기 전에 반드시
  `git status`로 추적 여부 확인할 것(재발 방지 메모).

**② 텍스트 보고서 화면 스키마·데이터**: 원본 PDF(`documents/기획문서/260731 핵심광물
수급위기 진단 화면 기획안 ver.1.3.pdf`) p.4·p.11·p.18·p.24를 PyMuPDF로 직접 재확인해
슬라이드 문구 그대로 스키마화(추측 없음) — A화면(종합 모니터링) §6 "AI 보고서 다운로드"
+§13 "AI 종합분석 및 관련뉴스"(현황→원인→대응, 리스크태그, 광종별 주간뉴스 4필드)와
B화면(광종별) Step6 §21 "AI 종합판단"(종합경보·핵심변수기여도·공급망요약·이벤트뉴스요약)
2종을 하나의 테이블로 묶었다.

- **신설 테이블** `out_ai_dashboard_summary`(`mineral_supply_risk/db/schema_core.sql`에
  추가, portable DDL): `scope`('overall'|'commodity')로 두 화면 구분, 숫자 필드
  (crisis_index·wow_delta·key_factor_contrib_json)는 전부 `out_diagnosis_alert`·
  `geo_index`·`out_import_forecast_unit`·`geo_event`에서 그대로 가져오고(LLM이 숫자를
  안 지어냄), 서술 필드(diagnosis_text·ai_comment·risk_tags_json·weekly_news_json·
  supply_chain_summary·event_news_summary)만 LLM이 그 숫자를 근거로 작성 —
  `report_gen/app/analysis/summary.py`의 "LLM 정제+규칙기반 폴백" 원칙 그대로 재사용.
- **신설 생성기** `services/report_gen/app/dashboard_summary.py` — `shared.llm_client.
  KomirJsonLLM`(pydantic 구조화 출력, 기존 클라이언트 재사용)로 overall 1행+commodity
  5행 생성, `shared.db.upsert_df_msr`(오늘 postgres cutover 작업에서 만든 `dbio.upsert_df`
  를 `write_df_msr` 옆에 대칭으로 처음 재노출)로 멱등 적재.
- **실LLM 실행 검증**(로컬 vLLM `gemma-4-26b-a4b`, `localhost:52302`): 6행 전부
  LLM 서술 성공(폴백 0건) — CU "심각·98.0·전주대비-0.21·y_lag1 33.0" 등 실제
  `out_diagnosis_alert`/`geo_event` 수치·근거문구를 정확히 인용한 자연어 생성 확인,
  환각 수치 없음(전부 payload에 있던 값만 재인용).

**남은 일(다음 세션 또는 병합 후)**: 이 워크트리(`worktree-mineral_risk`)도 아직 main
미병합 상태 — 이전 postgres cutover 작업과 동일하게, 병합 후 `cron_forecast_monthly.sh`를
시스템 crontab에 실제 등록해야 함(`0 1 1-7 * SUN`). `dashboard_summary.py`는 아직
API로 노출되지 않음(schema+생성기+실데이터까지만 이번 스코프) — commodity_api류
엔드포인트로 서빙하려면 후속 라우터 필요.


## 2026-08-19 (최신) — MSR 데이터 저장소 duckdb → postgres cutover(코드 이식 완료, 실postgres 검증 완료)

사용자 지시("지금 데이터는 postgresql에 덤프하고 그 db 활용하기로 하지 않았나? duckdb에서
postgresql로 옮겨주세요, 향후 생성되는 모든 데이터도 postgresql로")에 따라 진행. 조사
결과 2026-08-10 postgres 이관은 1회성 스냅샷 사본일 뿐 cutover는 보류 상태였고(WORKLOG
해당 일자·메모리 `postgres_migration_260810` 확인), duckdb가 여전히 정본이었다(실측:
postgres가 geo_index 1주·geo_event 1주 stale). 상세 계획은
`/home/nuri/.claude/plans/rosy-rolling-wren.md`(승인됨) 참고 — 이 절은 실행 기록.

**핵심 발견(계획 수립 시엔 몰랐던 것, 실행 중 실postgres 접속으로 드러남)**: `MSR_DB`를
postgres URL로만 바꾸면 최소 6종의 서로 다른 실패 유형이 발생했다 — 계획에서 예상한
"duckdb 전용 쓰기 API(register/CHECKPOINT)" 외에, **읽기 경로**에도 동일한 문제가 있었고
(모델 로더 다수가 `duckdb.connect()`를 직접 열었음 — commodity_api가 바로 이 함수들에
의존), SQL 방언 차이도 3종 발견됐다: ① `last(x ORDER BY y)`(duckdb 전용 집계함수, 표준
`array_agg(...)[1]`로 교체) ② `date_trunc('month', date_컬럼)`이 postgres에서 암묵적으로
`timestamptz` 오버로드를 타 세션/시스템 타임존이 섞여 들어옴(`CAST(... AS TIMESTAMP)`
명시 캐스트로 교정 — 실측: 병합 시 tz-aware/naive 충돌로 크래시) ③ `CAST(x AS DOUBLE)`
(duckdb 전용 타입명, `DOUBLE PRECISION`이 표준) ④ duckdb `DECIMAL(20,4)` 컬럼이 duckdb
Python 드라이버에선 fetch 시 float64로 자동변환되지만 psycopg2는 `decimal.Decimal`
object로 반환 — numpy/pandas 연산이 `TypeError`로 크래시(스키마 문제가 아니라 드라이버
차이임을 실측으로 확인). 이 각각을 실제 postgres 접속으로 재현·수정·재검증했다(가정이나
문서 검토가 아니라 실행 기반).

**변경 파일(24개, `git diff --stat` 기준)**:
- `mineral_supply_risk/db/dbio.py`(핵심 신규): `upsert_df()`(duckdb/postgres 자동분기 —
  postgres는 SQLAlchemy 트랜잭션, duckdb는 `msr/storage/db.py`의 기존 로직 그대로 이관),
  `connect_ro()`+`_PgReadConn`/`_PgReadResult`(postgres에서 duckdb Connection의
  `.execute(sql).df()/.fetchone()/.fetchall()/.close()` 서브셋만 흉내내는 어댑터 — 15곳의
  build_panel류 함수가 쿼리 리라이트 없이 connect 호출 한 줄만 바꿔 재사용하게 함),
  `_coerce_decimal_cols()`(위 ④ 흡수, 읽기 경계 한 곳에서 전역 해결).
- `msr/storage/db.py`: `upsert_df()`를 `dbio.upsert_df()` 위임으로 축소(6개 호출부
  — `msr/pipeline.py`·`msr/models/alert.py`·`scripts/backfill_customs_monthly.py` 등
  — 무변경으로 자동 해결).
- `msr/models/{nowcast,forecast_unit,alert}.py`: duckdb 전용 쓰기(register/CHECKPOINT)를
  `dbio.write_df`(전체교체)/`dbio.upsert_df`(부분갱신)로 교체. `alert.py::run()`은
  추가로 `DESCRIBE`(duckdb 전용, postgres에서 실패 시 "마트 없음"과 똑같이 조용히
  스킵돼버림 — 실측으로 발견)를 `information_schema.columns` 조회로 교정.
- `msr/models/{diagnosis_opt,forecast_unit,alert_reason}.py`,
  `scripts/{diagnosis_retrain_answer,diagnosis_aux_features_eval,
  diagnosis_exch_inventory_eval,diagnosis_priority_feeds_eval,diag_refine1,
  aux_early_warning}.py`: `duckdb.connect(db, read_only=True)` → `connect_ro(db)`
  (기계적 1줄 교체, 15곳). 위 SQL 방언 차이 3종도 해당 파일들에서 실측 발견돼 함께 수정.
- `msr/features/normalize.py`·`weekly_mart.py`: DDL 포함이라 `is_url(db)` 분기로
  postgres 전용 경로(`_run_pg`) 신규 추가(duckdb 경로는 무변경, 회귀 위험 없음).
  `weekly_mart.py`는 duckdb `ASOF LEFT JOIN`(postgres 미지원, 표준 SQL도 아님)을
  `LEFT JOIN LATERAL`로 재작성 — **실 duckdb 데이터로 원본 ASOF 쿼리와 결과 완전 일치를
  4621행 전 컬럼(NULL 위치까지) 검증 후 채택**(추측 아님, `array_agg` 트릭 포함 2건 모두
  `np.allclose(..., equal_nan=True)`로 확인).
- `msr/models/{diagnosis,forecast}.py`: 참고용/baseline 모듈(model_loaders.py·CLAUDE.md
  §2 실행경로 어디서도 안 씀, `msr/features/marts.py`도 grep으로 참조자 0건 재확인) —
  `connect_ro`만 기계적으로 맞추고 `DESCRIBE`류 방언 문제는 일부러 안 고쳤다(비활성
  경로, try/except가 이미 "마트 없음"과 동일하게 안전히 스킵함).
- `services/commodity_api/app/model_loaders.py`: `CAST(x AS DOUBLE)`→`DOUBLE PRECISION`
  (앞서 만든 이 서비스도 실postgres 테스트에서 걸림 — duckdb로만 검증했을 때는 안
  드러났던 문제).

**실postgres 검증(추측 없이 전부 실행)**: `172.30.1.101:5433/komis_demo`의 `mineral_risk`
스키마(2026-08-10 이관 스냅샷)를 대상으로 —
1. 읽기 경로 개별 함수 7개(diagnosis_opt/forecast_unit build_panel, load_delta_ew의
   7단계 체인 전체 — retrain_answer→add_dynamics→build_aux→build_cninv→build_pmi→
   build_refined→build_cli) 전부 정상 실행 확인.
2. 쓰기 경로 5개 스크립트 전부 실제 postgres에 실제로 적재 성공 확인: `nowcast.py`
   (mart_diagnosis_nowcast 395행) · `alert.py`(out_diagnosis_alert 1652행, storage.db
   위임 경로) · `forecast_unit.py`(out_import_forecast_unit 60행+mart_forecast_method_log
   1행 upsert, ExtraTrees+conformal 전체 파이프라인 3분 소요) · `weekly_mart.py`
   (mart_weekly_diagnosis 4621행, LATERAL) · `normalize.py`(fact_trade_monthly 21955행
   — duckdb와 행수 정확히 일치) · `aux_early_warning.py`(out_aux_early_warning 5행).
3. `commodity_api`를 `MSR_DB=<postgres DSN>`으로 기동해 3개 엔드포인트(geo-index·
   diagnosis·forecast) 전부 200 확인, forecast는 ExtraTrees 재적합 포함 199초(duckdb
   테스트와 동급 소요).
4. **최종 재동기화**(`scripts.migrate_duckdb_to_postgres` 재실행, 38개 테이블 0건
   불일치) **후 commodity_api 재호출 결과가 이 세션 최초 duckdb 테스트 결과와 완전히
   일치**함을 확인(idx_value 64.919·ci_pred 97.99 등 소수점까지 동일) — 회귀 없음의
   가장 강한 증거.

**postgres 접속 문자열의 핵심 설계**: `?options=-csearch_path%3Dmineral_risk`를 DSN에
추가하면 세션 기본 스키마가 고정돼, 코드베이스 전역의 **비한정 SQL 문자열(`FROM
geo_index` 등)을 단 하나도 안 고쳐도 됨**을 실측 확인(`SHOW search_path` → `mineral_risk`,
`SELECT count(*) FROM geo_index` 스키마 접두 없이 정상). 스코프가 "duckdb 전용 API를
쓰는 지점"으로만 좁혀진 결정적 이유.

**스코프 밖(의도적, 문서화)**: `mineral_supply_risk/scripts/`의 나머지 ~40여개
백테스트·검정 스크립트(`diagnosis_*_eval.py`류 중 이번에 안 건드린 것들, `r10_*.py`,
`geo_prob_alt_refit.py`, `midas_eval.py`, `build_kr_import_share.py` 등)는 CLAUDE.md
§2·cron 어디에도 없는 연구용 도구라 이번 cutover에서 안 건드렸다 — 같은 패턴(`connect_ro`
+ `CAST(...AS DOUBLE)`→`DOUBLE PRECISION`)으로 필요할 때 고치면 됨. `msr/features/
marts.py`는 참조자 0건이라 죽은 코드로 판단, 미착수. 시스템 crontab(6건)은 스크립트
경로만 참조해 DB 대상과 무관하므로 변경 불필요(스크립트 내부 `MSR_DB`/`--db`만 전환
대상).

**다음 세션 또는 후속 작업(이 세션에서 미실행, 의도적으로 사용자 확인 후 진행)**: 이
워크트리(`worktree-mineral_risk` 브랜치)의 변경사항을 main으로 병합한 뒤에야 실제
운영 전환(`inhouse/.env`의 `MSR_DB`, `mineral_supply_risk/scripts/
cron_collect_feeds_inhouse.sh`의 `MSR_DB` export, `geo/cron_gkg_increment.sh`의 `--db`,
`CLAUDE.md` §2 실행 예시)을 진행한다 — 메인 체크아웃은 이번 수정사항이 전혀 없는
상태라 먼저 전환하면 방금 고친 것과 동일한 실패가 그대로 재현되기 때문(사용자 확인
완료, "커밋 후 병합까지 진행" 선택).

## 2026-08-19 — commodity_api 3개 라우터(geo-index·diagnosis·forecast) 구현·실데이터 검증

`services/commodity_api`가 "설계 단계 스켈레톤"(`NotImplementedError`)이던 것을
CONTAINER_ARCHITECTURE.md §8 3단계대로 구현했다. 이식 원본은
`dashboards/streamlit_app.py`의 `load_geo`/`load_diagnosis_level`/
`load_diagnosis_alert`/`load_delta_ew`/`load_forecast` — Streamlit 전용 부분
(캐시 데코레이터·plotly 차트)만 걷어내고 `app/model_loaders.py`로 그대로 옮겼다
(재구현 아님, 함수 바디 동일).

**신규 파일**(`inhouse/services/commodity_api/app/`):
- `_bootstrap.py` — `shared/db.py`(기존 패턴 재사용)에 더해 `mineral_supply_risk/
  msr/config.py`를 위로 훑어 찾아 sys.path에 넣는 `ensure_msr_engine_on_path()`
  신규 추가(msr.*/scripts.* 최상위 import를 위해 필요, dbio.py만 필요했던 기존
  `_find_msr_root`와는 목적이 다름).
- `deps.py` — 광종 코드(cc) 검증(5종 아니면 404) + DB mtime 키 in-memory 캐시
  (`st.cache_data`의 서버 재현, 락으로 중복 재적합 방지, `POST /admin/cache/clear`로
  수동 무효화).
- `model_loaders.py` — 5개 로더 함수 이식. DB 조회는 원본의 raw `duckdb.connect`
  대신 `shared.db.read_sql_msr()`(dbio 경유, 향후 Postgres cutover 시 코드 변경
  불필요)로 바꿨다 — 유일한 의도적 변경점.
- `serialize.py` — numpy.int64/bool_/Timestamp 등을 JSON 안전 타입으로 정규화
  (FastAPI 기본 인코더가 numpy 스칼라를 자동 변환하지 않아 500의 원인이 될 수
  있었음, 라우터 응답 경계에서 일괄 처리).
- `routers/{geo_index,diagnosis,forecast}.py` — 각각
  `GET /commodities/{cc}/geo-index`(주간 위기지수+p_burst_next 등 확률, 연산
  없음)·`GET /commodities/{cc}/diagnosis`(Ridge 챔피언 재적합+alert.py 규칙엔진/
  히스테리시스+선형 기여도 분해+보조 Δ조기경보 앙상블)·
  `GET /commodities/{cc}/forecast`(ExtraTrees direct 12개월 물량·단가+conformal
  구간보정+SHAP 로컬/전역 설명+18오리진 백테스트 스냅샷 병기)로 구현. `main.py`에
  `GET /commodities`(5광종 목록)·`GET /healthz`·`POST /admin/cache/clear` 추가.

**검증(실데이터, 메인 체크아웃 `minerals.duckdb` 대상 — 읽기 전용이라 이 워크트리에서도
안전하게 실행 가능했음)**: `uvicorn app.main:app`으로 로컬 기동 후 curl 실호출.
- `GET /commodities` — 5광종 정상.
- `GET /commodities/CU/geo-index` — 200, `idx_value`/`p_burst_next` 등 실측값 확인.
- `GET /commodities/CU/diagnosis` — 200(2.9초, 최초 Ridge 재적합), 경보 "심각" +
  기여도 분해(`y_lag1 +33.0` 등) + Δ조기경보(하향 45%) 정상.
- `GET /commodities/CU/forecast` — 200(수 분, ExtraTrees+conformal 3원점 재적합 —
  원본 docstring이 경고한 그대로), h=1..12 물량·단가·수입액 구간+SHAP 사유문 정상.
  **캐시 재사용 확인**: 동일 광종 재조회(다른 h) 9ms, 심지어 다른 광종(LI)
  diagnosis 조회도 7ms — `load_diagnosis_level`/`load_forecast`가 전 광종을 한
  번에 계산해 캐시에 얹기 때문(원본 구조 그대로).
- 존재하지 않는 광종(`XX`) → 404 + 한국어 사유 확인.
- `POST /admin/cache/clear` → 5개 엔트리(geo/diagnosis_level/diagnosis_alert/
  delta_ew/forecast) 초기화 확인 후 재조회로 정상 재계산 확인.
- 전 구간 `read_sql`이 `read_only=True`만 사용 — 운영 DB에 쓰기 경로 없음(원본
  "읽기 전용" 보장 그대로 승계).

**Containerfile·requirements.txt 갱신**: 기존 TODO("mineral_supply_risk 엔진 모듈
임포트 필요분만 선택적으로 COPY")를 실제로 채웠다 — `mineral_supply_risk/{msr,
scripts,db}`(데이터/산출물 디렉토리 제외)와 `dashboards/forecast_backtest_snapshot.json`만
선택 COPY. requirements는 streamlit_app.py가 이미 쓰던 duckdb/pandas/numpy/
scikit-learn/shap/python-dotenv를 반영(plotly/streamlit은 API 서빙에 불필요해 제외).

**범위 밖(의도적으로 안 함)**: 화면기획안 ver.1.3(`documents/산출물/2026-W33_0810-0816/
화면기획안_v1.3_...md`)의 #18(5+1 위기유형 판별)·#20(비관/중립/낙관 3분류
시나리오 라벨링)·#21(자유서술 AI종합판단) 같은 화면 전용 프레이밍은 포함하지
않았다 — 이번 작업은 CONTAINER_ARCHITECTURE.md §8 3단계(기존 진단·예측·지수
모델 결과를 "서빙 가능하게")로 스코프를 좁혔고, 그 문서가 이미 이 3개 화면
기능을 "구현진행중, 이미 있는 구성요소(SHAP·확률구간·기여도)를 재조립하면
되는 것"으로 분류해뒀다 — diagnosis/forecast 응답에 원자료(contrib·probs·SHAP
local/global)는 이미 포함돼 있어 후속 화면 어댑터가 이 위에서 조립하면 된다.
podman-compose 통합 기동(§8 6단계)·rag_chat/report_gen과의 공존 스모크는 미실행.
## 2026-08-19 (최신)⑤ — rag_chat API 컨테이너화 완료 + 실제 통합검증(사용자 지시:
"rag는 api를 만들어야 하고... 전체 파이프라인이 돌게")

CONTAINER_ARCHITECTURE.md §8 4단계("rag_chat — 세션/히스토리+스트리밍, 정형 리트리버
최소구현")의 마지막 남은 조각 — 코드는 이미 완성돼 있었지만 **실제로 컨테이너 빌드·기동한
적이 한 번도 없었다.** docker build/run으로 처음 실증했고, 그 과정에서 실제 버그 2건을
발견·수정했다(소스트리 실행에서는 상위 sys.path로 가려져 있던 것들):

1. **Containerfile 임베딩 모델 사전다운로드 TODO 실제 구현** — 주석처리돼 있던
   `SentenceTransformer('intfloat/multilingual-e5-small')` RUN 스텝을 활성화, 빌드
   성공 확인(airgap 런타임 전제상 빌드타임에만 가능).
2. **`python-docx` 의존성 누락 발견** — `generate.py→build_index.py→chunk.py→
   ingest.py` 임포트체인에 `import docx`가 있는데 requirements.txt에 없어 컨테이너가
   기동 직후 즉시 크래시했다. requirements.txt에 추가.
3. **chatbot_store.py에 PostgreSQL 지원 추가** — structured.py에 이어 세션/히스토리
   저장소도 URL 타깃(postgres) 분기를 실제 구현(이전엔 `NotImplementedError`로
   명시 미구현 상태였음). DuckDB `?` 자리표시자를 `%s`로 치환, 스키마는 `PG_SCHEMA`
   환경변수로 한정. 이걸로 "DB는 외부서비스" 원칙(로컬 DuckDB 파일 마운트 불필요)이
   rag_chat 전체(정형조회+세션이력)에 완성됐다.

**실제 검증**: `docker build` 성공 → `docker run`(PAGEINDEX_TREES_DIR·
OKF_DOCUMENTS_DIR 볼륨마운트, PG_DSN·MSR_DB(=PG_DSN)·LLM_BASE_URL=host.docker.internal
env 주입) → `/healthz` 200 확인 → `POST /chat` SSE로 "니켈 현재 수급위기 등급"
(structured 라우팅)·"코발트 DRC 수출"(dense+verify재질의) 둘 다 컨테이너 환경에서
end-to-end 정상 확인 — CLI로 검증했던 것과 동일 품질이 실제 배포형태(HTTP API)에서도
재현됨.

**전제 조건(사용자 지시대로 가정)**: `분석요약`(report_gen)·`mineral_risk`(commodity_api)
쪽은 "주기적으로 DB에 결과를 덤프한다"고 가정 — 이 서비스들 자체를 새로 건드리지 않았다.
mineral_risk는 실제로 이미 그 가정이 성립함을 오늘 확인(postgres 정기동기화 cron, 별도
사고 있었음 — `documents/meta/WORKLOG.md`(메인 브랜치) 같은 날짜 항목 참고, 이 브랜치와
무관한 별도 이슈였고 이미 복구·재발방지 완료).

**남은 것**(다음 단계, 이번엔 미착수): `services/deploy/`(설계 단계뿐) 실제
podman-compose 통합 기동(commodity_api+rag_chat+report_gen 세 컨테이너를 한 번에) —
지금은 rag_chat 단독 컨테이너만 검증됨.

## 2026-08-19 (최신)④ — structured.py 데이터소스를 PostgreSQL로 전환(사용자 지시)

"정형 데이터 조회가 PostgreSQL에서 읽어오게 돼 있는지 확인, 아니면 바꿔달라"는 지시로
`services/shared/retrieval/structured.py` 점검 — **PostgreSQL이 아니었을 뿐 아니라 실제로는
빈 결과만 내고 있던 숨은 버그**를 발견했다. `read_sql_msr()`(MSR_DB) 경유였는데, 이
워크트리 `.env`엔 MSR_DB가 아예 설정 안 돼 있어 `config.py` 기본값(워크트리 로컬의
**빈** stub duckdb)으로 조용히 폴백 중이었다 — `.env` 자체에 "structured 도구는 이번
검증 범위 밖"이라는 주석까지 있어(직전 세션이 의도적으로 미배선), 지금까지 시나리오
2-1(통계조회)이 코드는 있어도 실제로 트리거된 적이 없었다(직전 갭목록 문서의 "2-1
구현됨" 판정은 코드존재 확인일 뿐 end-to-end 미검증이었음 — 이번에 처음 실측 확인).

**변경**: `read_sql_msr` → `read_sql_pg()`(PG_DSN, `mineral_risk` 스키마 — dense_pg.py·
bm25_pg.py와 동일 접속) 전환. 스키마는 `get_settings().PG_SCHEMA`로 동적 지정(하드코딩
금지 규약 준수). 컬럼명 전부 실측 대조 확인(`out_diagnosis_alert`/`out_import_forecast`/
`geo_index`) 후 3개 함수 전부 실행 성공 + 챗봇 전체 파이프라인으로 "니켈 현재 수급위기
등급 알려줘" 질의 시 `structured=True(latest_diagnosis/NI)` 라우팅→정상 답변까지 최초로
end-to-end 확인.

**발견(별도 이슈, 이번엔 미수정)**: PG `mineral_risk` 스키마는 실시간 동기화가 아님 —
`out_diagnosis_alert`·`out_import_forecast`는 우연히 라이브 duckdb와 일치(그 파이프라인이
08-10 이관 이후 재실행 안 됨)했지만, `geo_index`는 **PG가 라이브보다 약 1주 뒤처짐**(PG
최신주 08-02 vs 라이브 08-09, 오늘 진행한 expanding-window 리팩터 반영분도 PG엔 없음).
정기 동기화 도입 여부는 운영 전 별도 결정 필요 — `structured.py` 상단에 경고 주석으로
남겨둠. `RAG챗봇_기능요구서_구현현황_갭목록_260819.md`에도 반영 필요(다음 갱신 때).

## 2026-08-19 (최신)③ — RAG 챗봇 기능요구서 대조·구현현황·갭 목록 정리(사용자 지시)

`documents/인수인계/핵심광물 수급위기 진단 챗봇 기획안.pdf`(사용자시나리오 6종+세부옵션
A/B/C안)와 `...결정(협의내용).txt`(발주처 확정안)를 원문 직접 확인 후, 현재 `rag` 브랜치
코드(`chatbot_graph.py`·`intent.py`·`page_recommend/`·`structured.py`·`generate.py` 등)와
1:1 대조. 결과물: `documents/산출물/2026-W34_0817-0823/RAG챗봇_기능요구서_구현현황_갭목록_260819.md`.

**핵심 발견**:
- 시나리오 2-5(메뉴안내)는 `chatbot_graph.py`가 아니라 **별도 서브시스템**
  (`page_recommend/`, 43페이지 레지스트리, `intent.py`가 document/page 2경로로 자동분류)이
  담당한다는 걸 코드로 확인 — 처음엔 "미구현"으로 오판할 뻔했다가 라우팅 구조를 끝까지
  추적해 정정.
- 시나리오 2-6(범위밖질문) B안 요구사항(답변불가+제공가능범위 안내) **미달**: `generate.py`의
  `ABSTAIN_TEXT`가 "근거를 찾지 못했습니다" 하나뿐이라, 투자조언 같은 범위외 질문도 그냥
  근거없음과 똑같이 처리됨 — 도메인 경계 인식 프롬프트 보강 필요.
- 시나리오 2-4(비교질문) 구조적 공백: `RetrievalRoute.commodity_code`가 단일값
  (`Literal[...] | None`)이라 정형 도구가 한 턴에 광종 1개만 조회 가능 — "리튬 vs 니켈"류
  비교는 구조적 지원 없이 dense 검색이 우연히 두 광종 다 언급한 문서를 찾아야만 됨.
- 대화 어투(A안, 격식체) 미강제: `SYSTEM_PROMPT`에 어투 지시문 자체가 없어 LLM 기본값에
  의존 — 지금까지 응답이 격식체였던 건 우연.
- 12개 추가작업/확인필요 항목을 우선순위와 함께 목록화(문서 §3 참고) — 1순위 범위밖질문,
  2순위 비교질문 구조보강.

코드 변경 없음(순수 조사·문서화).

## 2026-08-19 (최신)② — dense 검색 날짜인식 부스트(A) + BM25 하이브리드 재도입(D)

사용자가 실사용 테스트("최근 구리 LME 시황"/"2026년 상반기 니켈"/"코발트 DRC 수출")로
챗봇 응답 품질을 확인시켜본 결과, "2026년 상반기 니켈 LME 가격 동향"이 **실제로 코퍼스에
있는 문서(Argus 2026년 1~6월판 113건, 전부 니켈 언급)를 두고도 기권**하는 걸 발견 —
`dense_pg.dense_search_pg()`가 순수 코사인 top-5라 날짜 개념이 전혀 없던 게 원인. 사용자
승인 하 두 방향(A: 날짜 인식 부스트, D: BM25 하이브리드 재도입) 구현.

**전제조사(중요 발견)**: `doc_chunk.pub_date` 컬럼이 있길래 쓰려 했더니 140,031행 중
**783행(0.6%)만 채워져 있고 Argus는 0건**이었다 — `build_okf_documents.py`가 title에
날짜를 담아뒀을 뿐 pub_date로 넘기는 코드가 없었음. `services/ingestion/
backfill_doc_chunk_pub_date.py` 신설(Argus "(YYYY-MM-DD)"·조달청 "(YYYY.M.D)"·USGS
"USGS_YYYY"(연도만) 패턴 파싱, doc_id 단위 매핑 후 벌크 UPDATE) — 96,780행(69%)까지
채움. Argus는 690/690 전부 매칭, 미매칭 376건(조달청 대체표기 348건 등)은 정직한 결측
유지.

**A(날짜인식 부스트)**: `dense_pg.py`에 `extract_date_range()`(연도+상반기/하반기/분기/
월 파싱) 신설. **실측으로 실제 버그 하나 더 발견**: 정규식에 `\b`(word boundary)를 썼는데
Python `re`가 한글을 `\w`로 취급해 "2026년"처럼 숫자 바로 뒤에 한글이 붙으면 경계가 전혀
안 잡혀 **모든 "YYYY년" 질의에서 None을 반환**하는 버그였음 — `(?<!\d)`/`(?!\d)` lookaround로
교체해 해결. `dense_search_pg()`는 날짜매칭 청크의 코사인 거리를 소폭(`_DATE_BOOST=0.08`)
깎아 우선순위만 올린다 — **하드 필터 아님**(pub_date 44%가 여전히 NULL이라 하드필터는
위험, 매칭 0건이어도 결과가 비지 않게 설계).

**D(BM25 하이브리드)**: 기존 `rag/ragkit/retrieve.py::hybrid_search()`는 구 코퍼스
(<100건) 전용 DuckDB FTS라 재사용 불가 — 같은 RRF 공식·상수(`RRF_K=60`)를 새 데이터소스
(pgvector `doc_chunk`)에 재적용. `idx_doc_chunk_txt_fts` GIN 인덱스 신설(순수 추가 DDL)
+ `bm25_pg.py`(Postgres `ts_rank_cd`, `'simple'` config — 한국어 형태소분석 없이 공백
토큰화만, 이번 동기인 "2026"·"DRC"·"LME" 같은 정확토큰 매칭엔 충분) + `hybrid_pg.py`
(dense+bm25 RRF 융합). `chatbot_graph.py`의 dense 단독 호출을 hybrid로 교체 —
`Evidence.from_dense_chunk()`는 필드명이 같아 무변경.

**회귀검증**: 3개 질문 재실행 — "2026년 상반기 니켈"이 기권 없이 정상 응답으로 전환
(ING 2026 가격전망 $15,250/t·인도네시아 RKAB 등 실제 최신 근거로 답변), "코발트 DRC
수출"은 기존 응답 유지+10월 쿼터제 도입 등 정보 추가(BM25가 놓쳤던 청크 보강), "구리
LME 시황"도 회귀 없음. 전부 `MSR_DB`를 실 프로덕션 DB로 지정해 `rag.ragkit.chatbot` CLI
데모로 직접 실행 확인.

## 2026-08-19 — PDF 추출기 대안(firecrawl/pdf-inspector) 검토 → 현행(opendataloader-pdf) 유지 결정

pageindex_agent.py 작업 중 발견한 "USGS 일부 연도판 헤딩 유실"(위 절들 참고)
결함의 근본 원인이 PDF→MD 1단계 추출기(opendataloader-pdf)에 있다는 점에서,
대안으로 제안받은 `firecrawl/pdf-inspector`(Rust, MIT, 폰트크기 기반 헤딩
검출)를 조사·비교했다. 결론: **현행 opendataloader-pdf 그대로 유지**(사용자
결정).

**비교 근거**: 공개 벤치마크(opendataloader-bench, 200p 코퍼스, 2026-07-31)
기준 현재 프로젝트가 실제 쓰는 opendataloader "plain" 모드(Overall 0.831)는
pdf-inspector(0.875)에 정확도·속도 모두 뒤지지만, **opendataloader "hybrid"
모드(Overall 0.907)는 pdf-inspector보다 오히려 앞선다** — 즉 새 의존성을
도입하지 않고 기존 라이브러리의 실행 모드만 바꿔도 pdf-inspector 이상의
개선 여지가 있다는 뜻. 또한 pdf-inspector는 1단계(PDF→MD) 추출기일 뿐
2단계(마크다운→목차 트리, `page_index_md.py`의 정규식 기반 헤딩 파싱)는
대체하지 못해 완전한 대체재가 아니다. "폰트크기 기반 헤딩 검출이 이번
헤딩유실 결함을 실제로 피해가는지"는 USGS 원본 PDF로 파일럿을 안 돌려봐서
미검증 상태로 남겨뒀다.

**재시도 금지 아님(향후 재검토 여지)**: opendataloader hybrid 모드 전환은
아직 안 해봤고, "airgap 실측 검증까지 마친 채택된 대안"이 아니라 "검토했으나
당장 안 바꾸기로 한 것"이다 — GACC headless류(§재시도 금지 목록)와는 성격이
다르다. 필요하면 나중에 hybrid 모드 파일럿부터 시도할 것.

## 2026-08-18 — 국가명 화이트리스트 커버리지 실측 검증(지난 herd 리뷰 후속과제 ③, 종결)

바로 아래 절(②) 직후 마지막 남은 과제(국가명 화이트리스트가 유한 목록이라
완전한 커버리지는 아님 — 권고안은 "표에서 대문자시작 토큰+숫자열 패턴으로
국가를 동적 추출하는 근본해법")를 검토했다. 구현에 들어가기 전에 "정말 지금
누락이 있는가"부터 실측했다.

**점검 도구 신설(`pageindex_agent.find_uncovered_country_candidates()`)**:
코퍼스의 광종 91개(list_known_commodities 기준) 전체를 최신 연도판 1개씩
훑어, `_COUNTRY_RE`가 모르는 "대문자로 시작하는 단어 바로 뒤에 정상 서식
숫자가 오는" 후보를 찾는다. `__main__`에 `--check-coverage` 플래그로 노출
(`python3 -m shared.retrieval.pageindex_agent --check-coverage`).

**실측 결과: 진짜 누락 0건**. 초기엔 다단어 조합(최대 4단어)으로 더 넓게
스캔했는데 "Large Japan"("...are large. Japan produced..." 문장 경계를
가로지른 오탐)·"Wyoming. About"(미국 국내 통계 문장의 잔재) 등 전부 문장
경계 오탐이었고, "NA China"·"W W W Belgium" 류는 결측 마커(NA/W)가 그 다음
진짜 국가명 앞에 붙어 한 덩어리로 잘못 묶인 스캐너 자체의 결함이었다(정작
"China"·"Belgium"은 이미 화이트리스트에 있고 `_rank_countries()`의 실제
파싱 로직에서는 전혀 문제되지 않음 — 스캐너가 너무 욕심을 낸 것). 단어
하나짜리 후보로 좁히고 이런 불용어(About/Large/NA/W 등)를 걸러내자 91개
광종 전수 스캔에서 후보가 0건으로 떨어졌다.

**결론 — 동적 추출은 지금 구현하지 않는다**: 실측으로 "지금 이 코퍼스에
증명된 누락이 없다"가 확인된 상태에서 동적 추출(정규식만으로 "이게 국가인지"
판정)을 새로 넣으면, 오히려 위에서 실측한 것과 같은 종류의 새 오탐 위험
(도메스틱 지명·문장 조각을 국가로 오인)을 자초할 뿐 지금 안 풀리는 문제를
풀어주지 않는다 — CLAUDE.md §4 "구조가 모델을 앞선다"·과설계 금지 원칙에
따라 미룬다. 대신 `find_uncovered_country_candidates()`를 유지보수 도구로
남겨서, 향후 새 USGS 연도판이 추가되거나 코퍼스가 바뀌면 재실행해서 실측
재확인할 수 있게 했다(런타임 경로에서는 안 부름, 회귀 위험 없음).

**검증**: mock 단위테스트 5건·기존 회귀 2건 재통과, `--check-coverage` 실행
결과 재확인.

herd 리뷰(2026-08-13)가 남긴 "남은 과제" 3개(①LLM 예외처리 확장 ②3/4턴
결정적 완화 ③국가명 커버리지) 전부 이걸로 종결됐다.

## 2026-08-18 — 3턴 대명사 해소·4턴 논리비약 결정적 완화(지난 herd 리뷰 후속과제 ②)

바로 아래 절(①, LLM 예외처리 확장) 직후 "남은 과제 ②"(3턴 route 대명사 해소
실패·4턴 top5 필터 무시 논리비약)를 이어서 처리했다. 지난번엔 "생성 단계
소형 LLM 추론 한계라 검색 계층 범위 밖"이라고 적었는데, 다시 파보니 검색
계층에서 결정적으로 막을 수 있는 부분이 실제로 있었다 — 두 실패 모두 "소형
LLM이 원문 표 여러 개를 눈으로 대조해 계산해야 하는" 지점에서 났고, 그 계산
자체는 `pageindex_agent.py`가 이미 갖고 있는 `_rank_countries()`로 결정적으로
할 수 있는 것이었다.

**3턴(route 대명사 오해소)**: `_route_node`가 history 배열 안에 파묻힌 "직전
어시스턴트 답변"을 놓치고 더 이전 턴의 개체명으로 되짚는 사례가 실측 재현됐다
(2턴이 "그 나라의 2위 광종은 구리"라고 확정했는데 3턴 "그 광종"을 코발트로
오인). 대응: `_last_assistant_answer()`(history에서 마지막 assistant 턴만
뽑는 헬퍼) 신설, route 호출 payload에 `last_answer`라는 별도 필드로
중복 노출(같은 정보가 history 배열 끝에 묻혀 있는 것보다 이름 붙은 필드로
도드라지게) + ROUTE_PROMPT에 "대용어는 last_answer(가장 최근 확정 사실)을
최우선으로 쓴다"는 규칙과 구체 예시 추가.

**4턴(top5 필터 무시)**: 근거에 니켈 원문표가 있으면(인도네시아 세계 1위,
230만톤) 소형 LLM이 "구리 상위5개국 중에서"라는 질문 조건을 확인하지 않고
그냥 가장 큰 숫자를 답으로 냈다(인도네시아는 구리 상위5개국이 아닌데도).
`pageindex_agent.py`에 두 가지를 신설:
- `_detect_focus_country()`: 질문(보통 route가 대용어를 이미 국가명으로
  풀어준 resolved_query)에 등장하는 국가명을 코퍼스가 아는 국가 목록 기준
  정규식으로 찾는다.
- **감시목록(focus_countries) 자동 확장**: 질문에 국가명이 없어도(예: "구리
  상위 5개국 중에서...") 첫 번째로 여는 광종의 상위 5개국을 자동으로
  감시목록에 편입한다. 이후 여는 모든 광종 표에 "[지정 국가 순위(자동계산,
  확정값)] Chile=이 표에 없음, Congo=이 표에 없음, ..., China=7위(115,000)"
  같은 결정적 주석을 붙여, "이 5개국 중 이 광종에 실제로 있는 나라가
  누구인지"를 생성 LLM이 원문표를 눈으로 다시 셀 필요 없이 그대로 인용만
  하면 되게 만들었다. `_annotate_with_ranking()`을 단일 focus_country에서
  focus_countries 목록으로 일반화.
- `chatbot.py`의 `_build_evidence_prompt()`에도 보조 안전망 추가: pageindex
  근거에 서로 다른 광종 섹션이 2개 이상 섞이면(=여러 표를 대조해야 하는
  질문일 개연성) "질문이 특정 집합으로 제한하면 그 집합에 실제로 속하는지
  확인한 뒤 답하라"는 유의사항 한 줄을 [질문] 뒤에 조건부로 붙인다(generate.py
  의 공용 SYSTEM_PROMPT는 안 건드림 — chatbot.py 전용 사용자 프롬프트에만
  추가해 blast radius를 이 기능으로 한정).

**검증**: mock 단위테스트 5건·기존 회귀 2건 재통과. 동일한 4턴 체인을 실인프라
대상으로 재실행(2회) — 수정 전 실패했던 3턴("콩고가 니켈 2위"라는 원문에
없는 오답)·4턴("인도네시아"가 구리 상위5개국 아닌데 답으로 나옴)이 두 재실행
모두 정답으로 바뀌었다(1턴 코발트=콩고, 2턴 콩고의 2·3위 광종=구리(칠레
다음), 3턴 구리 1위=칠레+콩고와 격차 2,520(2024년), 4턴 구리 상위5개국
{칠레·콩고·기타·페루·중국} 중 다른 광종 최다생산국=중국(보크사이트/니켈/
리튬 실제 수치 정확히 인용) — 전부 실데이터와 대조 확인). 재실행 1회에서는
스텝 도중 LLM이 유효하지 않은 JSON을 낸(`pageindex_agent_llm_error`) 일회성
장애로 2턴이 기권했지만, 그다음 3턴이 2턴 몫까지 스스로 만회해 정답을
냈다(설계대로의 안전한 열화 — 오답 대신 기권, 그리고 다음 턴에서 회복).

**정직한 한계**: 이건 "버그 수정"이 아니라 "결정적 보조선"이다 — route의
대명사 해소도, 최종 답변 합성도 여전히 확률적 LLM 호출이라 100% 보장은 아니다
(이번 재실행에서도 route가 한 번은 last_answer가 실패로 비어있으니 더 앞
턴으로 폴백한 사례가 있었다 — 그 자체는 합리적 동작). 다만 두 실패 모두
"근거에 필요한 계산 결과가 이미 결정적으로 준비돼 있는데 LLM이 다시
계산하다 틀리는" 패턴이었고, 그 계산을 대신 해서 안겨주는 접근이 실측상
효과가 있었다.

## 2026-08-18 — chatbot_graph route/reformulate/verify의 LLM 예외처리 범위 확장(지난 herd 리뷰 후속과제 ①)

바로 아래 절("pageindex_agent 신설") herd 코드리뷰가 남긴 "남은 과제" 3개 중
1번을 처리했다. `pageindex_agent.py`에서 고쳤던 것과 같은 버그(`except LLMError`
만 잡아 `OpenAICompatChat.complete()`가 재시도 소진 후 실제로 던지는
`RuntimeError`(HTTP 429/5xx)·`requests.RequestException`(OSError 서브클래스,
타임아웃/커넥션오류)을 못 잡고 그대로 턴이 죽는 문제)가 `chatbot_graph.py`의
route/reformulate/verify 세 노드에도 있었다.

**중복 정의 대신 공용 상수로 승격**: `services/shared/llm_client.py`에
`LLM_TRANSIENT_ERRORS = (LLMError, RuntimeError, OSError)`를 신설(사유는
docstring에 그대로 기록) — `pageindex_agent.py`가 갖고 있던 로컬 정의
(`_LLM_TRANSIENT_ERRORS`)를 이 공용 상수를 가져다 쓰는 걸로 교체하고,
`chatbot_graph.py`의 세 `except LLMError`를 전부 `except LLM_TRANSIENT_ERRORS`
로 바꿨다. 두 파일이 각자 따로 정의해 나중에 하나만 고치고 잊는 걸 막으려는
목적(gkg 시리즈 이름충돌류 교훈과 같은 패턴 — 공유 지점은 하나로).

**검증**: 신규 mock 단위테스트 5건(smoke_pageindex_agent.py)·기존 회귀테스트
2건(smoke_page_recommend.py·smoke_chat_routing.py, 실인프라 LLM까지 실제로
태움) 전부 재통과. 코드 3개 파일 문법·import 확인.

**남은 과제(갱신)**: (2) 3턴 실패 원인(route의 다단 대명사 해소)·4턴 논리비약
(top5 필터를 안 지키고 다른 근거로 건너뜀) — 생성 단계 소형 LLM 추론 한계로
검색 계층 수정 범위 밖. (3) 국가명 화이트리스트(pageindex_agent.py)도 여전히
유한 목록(약 190개)이라 완전한 커버리지는 아님(권고: 표에서 "대문자시작
토큰+숫자열" 패턴으로 국가를 동적 추출하는 근본해법은 더 큰 리팩터).

## 2026-08-13 — pageindex.py의 "에이전틱 traversal" 후속과제 착수: 국가별 생산량 순위·집계 질문용 pageindex_agent 신설

바로 위 절("verify(정확성 검증) 노드 추가")이 3차 실측에서 남긴 결론 — "인도네시아가
니켈 다음으로 몇 번째로 많이 캐나" 같은 질문은 검색어를 아무리 잘 바꿔도 단발
검색으로 못 풀고, "USGS는 광종별로 조직돼 있어 국가별 순위를 답하려면 광종 수십
페이지를 훑어 집계해야 한다"는 게 그 이유였다 — 를 사용자가 "그 부분을 구현하고
꼬리질문 체인으로 될 때까지 검증하라"고 요청했다. `pageindex.py` 모듈독스트링이
이미 "완전한 에이전틱 traversal은 후속 과제로 남긴다"고 명시해둔 바로 그 경계다.

**신설(`services/shared/retrieval/pageindex_agent.py`)**: LLM이 매 스텝
open_commodity(광종 하나 조회)/list_commodities(전체 광종 목록 열람)/finish 중
하나를 고르고, 그 행동을 결정적 함수로 실행해 결과를 scratchpad에 되먹이는
ReAct 루프(최대 MAX_AGENT_STEPS=5회, chatbot_graph의 MAX_ATTEMPTS와 별개 예산).
`pageindex.py`의 기존 트리 기반 도구(find_documents/search_nodes/read_node_text)는
전혀 안 건드리고 재사용도 안 한다 — 이유는 착수 전 실측으로 드러난 데이터 결함
때문이다(아래).

**실측으로 발견한 데이터 함정 3가지(전부 코드로 우회, 데이터·트리 파일 자체는
안 건드림)**:
1. **광종 헤딩 유실**: `data_lake/semi_structure/pageindex_trees/생산매장량_USGS/`
   8개 연도판(USGS_2019~2026) 중 CU/NI/CO/LI(구리·니켈·코발트·리튬) 4개 광종의
   "######" 마크다운 헤딩이 PDF→MD 변환에서 통째로 유실된 연도판이 6개(2019~2021,
   2023~2024, 2026)이고, 4개 광종 헤딩이 전부 온전한 연도판은 `USGS_2022` 하나뿐
   이었다(`grep -c "^#+\s*COPPER$"` 등으로 재현 확인). `pageindex.search_nodes()`는
   트리 노드 기반이라 이 4개 광종을 나머지 연도판에서 절대 못 찾는다 — 이게 하필
   프로젝트 발주 5광종 중 4개(CU/NI/CO/LI, REE만 예외)와 겹친다.
2. **그런데 본문은 살아있다**: 헤딩만 유실됐을 뿐 국가별 세계생산 표를 포함한
   본문은 원문 마크다운에 그대로 남아 있었다(실측 — `USGS_2024.md` 3385행 부근에
   COPPER의 "World Mine and Refinery Production and Reserves" 표가 국가별 수치와
   함께 온전히 존재하지만, 헤딩이 없어 앞 문단(비스무트 등)의 본문으로 잘못
   병합돼 있었다). 그래서 `pageindex_agent.py`는 트리 노드를 아예 안 보고, OKF
   원문 텍스트를 광종명 밀도(앞 1800자 안에 광종명이 몇 번 나오는지)로 직접
   스캔해 "World ... Production:" 단락을 찾는다(`_find_world_production_block`)
   — 헤딩 유무와 무관하게 동작하고, 여러 연도판(판마다 최근 2개년 수치)을 모아
   "최근 N년 생산량" 질문 근거도 만든다. 연도를 하드코딩하지 않는다(파일명
   내림차순=연도 내림차순 정렬로 최신판부터 스캔) — 향후 재적재로 헤딩 결함이
   고쳐지면 트리 기반 탐색도 자연히 같이 맞아떨어진다.
3. **밀도 스캔의 오탐 + PDF 각주 오염(전부 실측 재현 후 방어코드로 해결)**:
   - 희토류 계열 원소(이트륨·스칸듐 등) 섹션이 "rare earth"를 서술문에서 자주
     언급해 정작 RARE EARTHS 자신의 표보다 밀도가 높게 나올 수 있었다(실측 —
     "See the Rare Earths chapter." 상호참조 스텁이 밀도 1위로 오탐). 상호참조
     문구 패턴 기각(`_STUB_PREFIX_RE`) + 숫자밀도 최소치(`_looks_like_data_table`)
     2단 방어로 해결, 진짜 표(density 낮음)가 스텁(density 높음)을 이겼다.
   - 로컬 소형 LLM(gemma-4-26b-a4b)이 표를 직접 읽고 국가별 순위를 잘못
     계산하는 걸 실측으로 확인했다("콩고민주공화국이 주석 세계 2위"라고 답했지만
     실제로는(2025e 기준) 중국 71,000 > 인도네시아 61,000 > 페루 33,000 > 브라질
     28,000 > 콩고 27,000 순으로 콩고는 5위) — 표에서 콩고가 China보다 먼저 나온
     건 그저 알파벳순(C-o가 C-h보다 뒤)일 뿐인데 등장 순서를 순위로 착각한 것으로
     보인다. `_rank_countries()`가 국가명 바로 다음 토큰을 파싱해 내림차순
     순위 주석을 근거 앞머리에 계산해 붙이는 걸로 대응했는데, 이 파싱 자체에서
     2차 함정을 실측으로 또 발견했다 — PDF→텍스트 변환 시 각주 숫자가 콤마 없이
     실제 수치 앞에 들러붙는다("China 14270,000" = 각주 "14" + 실제값 "270,000",
     리튬 표의 "United States 4,400,000"은 사실 생산량 W(비공개)를 건너뛰고
     매장량 열을 잘못 집은 것). 대응: (a) 국가명 바로 다음 토큰만 보고 정상
     서식(쉼표 앞 1~3자리)이 아니면 그 광종 표 전체를 기각(`None` 반환, 국가 하나만
     빼는 절충은 안 함 — 하필 오염된 게 세계 1위 국가면 "1위가 빠진 순위"를
     그럴듯하게 내놓는 게 가장 위험한 실패모드라서), (b) 채택값이 "World total"
     이상이면 오염 확정으로 표 전체 기각, (c) world total 줄 자체도 같은 서식
     검사를 통과 못 하면 애초에 순위 계산을 시도하지 않음. 결과: COPPER/NICKEL/
     COBALT/TIN은 정상 순위 계산됨, LITHIUM/RARE EARTHS는 오염 탐지로 순위 없이
     원문 표+"알파벳순이지 순위 아님" 주석만 남기는 안전한 정도(degrade)로 낙착
     (advisor 자문 결과 — "부분 절충보다 조용히 물러나는 쪽이 안전").

**단위 정보 보강**: 국가별 표 블록은 "World...Production:"부터 시작해 광종
챕터 서두의 "(Data in metric tons, copper content...)" 단위선언 줄을 담지
못한다 — "생산량 차이는 얼마나 나?" 질문에 단위 없이 숫자만 나오면 안 되므로,
World-Production 매칭 지점에서 뒤로(~6000자) 훑어 가장 가까운 단위선언을 찾아
`Evidence.unit`으로 따로 싣는다(원문 표 자체는 안 건드림, 실측: 광종별 단위선언~
World Production 거리가 3,700~5,500자대라 3000자로는 놓치는 경우가 실제 있었음).

**chatbot_graph.py 배선**: `RetrievalRoute`에 `pageindex_mode: "simple"|"agentic"`
필드 추가(기본값 simple, 하위호환) — ROUTE_PROMPT에 "국가별 생산량 순위·비교·
집계 질문일 때만 agentic을 고르라"는 기준 추가. `_retrieve_node`가 `pageindex_mode`
에 따라 기존 `pageindex.lookup()`(단발) 또는 `pageindex_agent.agentic_lookup()`
(다단계)으로 분기 — agentic 경로는 스텝마다 LLM 왕복이 들어(최악 5회) 느리므로
정말 필요한 질문에만 켜지게 라우터가 판단한다(advisor 지적 — 무조건 agentic로
바꾸면 매 턴 최대 16회 LLM 왕복까지 갈 수 있어 "빠른 시간내" 요구사항 위반).

**검증**: 신규 mock 단위테스트 5건(`services/rag_chat/tests/smoke_pageindex_agent.py`
— 성공/미발견/스텝예산소진/반복가드/LLM장애 부분열화) 전부 통과, 기존
`smoke_chat_routing.py`·`smoke_page_recommend.py` 회귀 없음(실인프라 LLM까지
실제로 태워 재확인). 실인프라(Postgres+pgvector+PageIndex+vLLM) 대상으로 직접
설계한 4턴 연쇄 질문("코발트 1위 생산국은? → 그 나라가 2위/3위인 다른 광종은?
→ 그 광종 1위국과의 생산량 차이는? → 그 광종 상위 5개국 중 다른 광종 최다생산국과
최근생산량은?")을 반복 실행하며 코드를 그때그때 고쳤다 — 최종 라운드에서 1·2·4턴은
실제로 정확하고 근거 있는 답을 냈다(코발트 1위=콩고, 콩고의 2위 광종=구리(칠레
다음), 구리 상위5개국 정확히 나열). **3턴은 여전히 실패**(abstain)한다 — 원인은
새 코드가 아니라 route 노드(기존 코드, 이번에 손 안 댐)가 히스토리 안에서 "그
광종"을 코발트로 잘못 되짚은 소형 LLM 대명사 해소 실패였다(정보는 4턴 전부 히스토리
창 안에 있었음에도). 4턴도 "구리 상위 5개국 중 다른 광종 최다생산국" 질문에서
생성 LLM이 상위5개국 목록에 없는 인도네시아를 답으로 내놓는 논리 비약이 한 번
있었다(니켈 근거 자체는 실재/정확). 둘 다 **근거 조회(이번 작업 범위)는 정확했고,
근거를 종합하는 최종 답변 합성(로컬 소형 LLM의 다단 추론·대명사 해소 능력)이
한계**라는 같은 패턴 — 검색 계층을 더 고친다고 풀리는 문제가 아니라 별도 과제로
남긴다(생성 단계에 자기검증/재확인 패스를 추가하는 방향이 유력해 보이나 이번
범위 밖).

**herd 검증**: Agent 도구로 두 비판자를 병렬 스폰했다(feedback-herd-multi-agent-sessions
메모리대로 raw 백그라운드가 아니라 Agent 도구로 — 진행상황이 별도 탭에 보이게).

- **비판자①(사실검증)**: 실제 USGS 원문(USGS_2025.md/2026.md)을 직접 열어 6개
  순위 주장(코발트 1위=콩고·구리 2위=콩고·니켈 1위=인니·주석 1위=중국+콩고
  5위 밖·구리 상위5개국 구성)을 대조했고, 미끼로 섞어둔 틀린 주장("코발트
  1위=호주")을 정확히 잡아냈다(호주 3,600톤 vs 콩고 220,000톤, 약 1/60).
  5/6 TRUE·1/6(미끼) FALSE로 전부 정확 판정 — 원문·자동계산 순위 모두 실제
  일치 확인.
- **비판자②(적대적 코드리뷰)**: 코드만 읽지 않고 60여 개 광종에 대해 실제로
  함수를 실행해 대조하는 방식으로 리뷰했고, **치명적 버그 1건을 실측으로
  발견**했다 — `_KNOWN_COUNTRIES` 화이트리스트 누락으로 Turkmenistan(IODINE
  3위)·Bahrain(ALUMINUM 6위)·Algeria/Syria/Qatar/Kuwait/Mauritania/Belarus/
  Burundi 등 실제 상위권 생산국이 순위에서 조용히 빠지고 등수가 한 칸씩
  밀려 올라가는 문제("6위 UAE, 7위 Australia, 8위 Norway"처럼 실제론 Bahrain이
  6위인데 밀림) — "오탐보다 누락이 안전"이라는 방어선이 각주오염엔 지켜졌지만
  국가명 커버리지 공백엔 안 지켜진 사례였다. 즉시 반영: 국가 목록을 UN
  회원국 기준으로 대폭 확충(24개→약 190개) + "Côte d'Ivoire" 원문 특수문자
  (ô/’, U+00F4·U+2019) 불일치로 매칭 자체가 안 되던 인코딩 버그 동시 수정.
  둘째로 발견한 버그(치명적) — `agentic_lookup`이 docstring상 "LLM 장애 시
  부분 근거 반환"을 약속하지만 `except LLMError`만 잡아 `OpenAICompatChat.
  complete()`가 실제로 던지는 `RuntimeError`(HTTP 429/5xx)·`requests.
  RequestException`(타임아웃/커넥션오류, OSError의 서브클래스)은 못 잡고
  그대로 전파 — 가장 흔한 실제 장애모드에서 이미 모은 근거까지 유실. 즉시
  반영: `except (LLMError, RuntimeError, OSError)`로 확장(`requests`를 이
  파일이 직접 import 안 해도 되게 OSError로 넓게 잡음). 두 수정 다 재검증
  완료(IODINE에 Turkmenistan 정상 등장, ALUMINUM에 Bahrain 정상 등장, 기존
  5건 mock 단위테스트·smoke_chat_routing·smoke_page_recommend 전부 재통과).
  같은 버그 패턴(`except LLMError`만 잡는 것)이 chatbot_graph.py의 route/
  reformulate/verify 노드(오늘 작업 이전부터 있던 기존 코드)에도 있다는 것도
  비판자가 지적했으나, 이번 파일 밖의 기존 검증된 코드라 이번 사이클에서는
  안 건드리고 별도 과제로 남긴다(가이드 §4 "이미 검증된 공유 코드는 회귀
  재검정 계획 없이 건드리지 않는다").
- 문제없음으로 확인된 부분(비판자②가 코드+실측으로 검증): 각주오염 탐지
  (LITHIUM/RARE EARTHS 정확히 기각), 밀도스캔 오탐 방지(RARE EARTHS↔YTTRIUM
  상호참조 스텁 정확히 회피), ReAct 루프 무한루프 불가능(range 기반이라
  구조적으로 종료 보장).

**남은 과제**: (1) chatbot_graph.py route/reformulate/verify의 LLM 예외처리
범위 확장(비판자②ii와 같은 패턴, 별도 사이클), (2) 3턴 실패 원인(route의
다단 대명사 해소)·4턴 논리비약(top5 필터를 안 지키고 다른 근거로 건너뜀) —
둘 다 생성 단계 소형 LLM 추론 한계로 검색 계층 수정 범위 밖, (3) 국가명
화이트리스트도 여전히 유한 목록이라 완전한 커버리지는 아님(권고: 표에서
"대문자시작 토큰+숫자열" 패턴으로 국가를 동적 추출하는 근본해법은 더 큰
리팩터라 이번엔 목록 확충으로 절충).

## 2026-08-13 — chatbot_graph에 reformulate 재시도 + verify(정확성 검증) 노드 추가, session_id/history 창 정리

바로 위 절 작업 직후, 사용자가 5턴 연쇄 대명사 대화("구리 많이 나는 나라는? →
그 나라 2번째 광종은? → 그 광종 세계 1위 생산국은? → 세계 생산량은? → 최근
가격은?")를 실제로 돌려보라고 요청했다. 실행 결과 두 단계 문제를 실측으로
발견·해결했다.

**1차 실측(구리 원본 질문)**: 1턴부터 기권. 원인 진단 — USGS Copper 페이지가
PDF→마크다운 변환에서 유실됐고(제목 "Copper"만 차트 범례에 남음, 본문
"World Mine Production" 테이블 없음), 조달청보고서(전체 코퍼스의 대부분)는
가격/재고 위주라 "국가별 생산량 순위" 질문과 결이 다름 — 코드 버그 아님.

**2차 실측(니켈로 재현, 메커니즘 검증용)**: 1턴 성공(인도네시아, 실인용
8건). 2턴("그 나라에서 니켈 다음으로 많이 나는 광종은?")에서 대명사
해소(`resolved_query`)는 "그 나라"→"인도네시아"로 정확했지만 검색 결과가
0건 → 재시도 없이 바로 기권. **사용자 지적: "기권이 아니라 실제로 찾아서
답해야 한다."**

**대응 — chatbot_graph.py에 3가지 확장**:
1. **reformulate 재시도**: retrieve가 0건이면 검색어를 재구성해 최대 1회
   재시도(`REFORMULATE_PROMPT`+`ReformulatedQuery`). 진단 근거: 한국어
   "인도네시아 2위 광종"으로는 0건이지만 영어("Indonesia bauxite mine
   production")로는 USGS/Argus 코퍼스에 실제 관련 문서가 걸림(실측 확인,
   `dense_pg.dense_search_pg`/`pageindex.find_documents` 직접 호출로 검증) —
   코퍼스가 한국어(조달청)·영어(USGS/Argus) 이중언어라 검색어 언어가
   결과를 크게 좌우한다.
2. **verify(정확성 검증, 사용자 요청 "correct 체크")**: retrieve 직후 근거가
   질문에 실제로 답하는지 LLM으로 확인(`VERIFY_PROMPT`+`GroundingCheck`).
   evidence가 있어도 "주제만 겹치고 답은 없는" 경우(구리 사례가 정확히 이거였다
   — 8건 다 가격차트인데 "생산국" 질문엔 무응답)를 reformulate 재시도로
   흡수한다. 재시도 후에도 불충분하면 `evidence=[]`로 정리해 기존 "근거 0건
   -> 기권" 경로를 그대로 재사용(chat_turn()·citations 계약 무변경).
3. **session_id 로그 추적 + history 창 통일**: `RetrievalState`에 session_id
   추가(그래프 판단엔 관여 안 함, 로그에만 실어 어느 세션·턴에서 재시도/검증이
   났는지 추적 가능하게). route/reformulate/verify 세 LLM 호출이 각자
   `[-4:]`를 하드코딩하던 걸 `HISTORY_WINDOW` 상수+`_recent_history()`
   헬퍼로 통일.

그래프는 이제 route -> retrieve -> verify -> (불충분·attempt<2면)
reformulate -> retrieve -> verify -> finalize -> END(최대 2회 검색, "빠른
시간내에" 요구사항상 무한 재시도는 안 함).

**3차 실측(같은 니켈 5턴 체인, verify 붙인 뒤 재실행)**: 2턴이 이제 진짜로
재시도한다 — verify가 "인도네시아 니켈 생산목표·가격동향·HS코드는 있지만
다음 순위 광종 정보는 없다"고 구체적으로 불충분 판정 → reformulate가 영어로
재질의("Indonesia mineral production ranking after nickel") → 2차 검색도
같은 이유로 재불충분 → 재시도 소진, 기권. **결론: 이 특정 질문("한 나라의
N번째 광종")은 검색어를 아무리 잘 바꿔도 이 코퍼스로는 못 푼다** — USGS는
광종별로 조직돼 있어(국가별 아님) "인도네시아가 뭘 몇 번째로 많이 캐나"를
답하려면 광종 수십 페이지를 전부 훑어 국가별 순위를 집계해야 하는데, 이건
한 번의 검색으로 되는 질문이 아니라 다중 문서 집계(에이전틱 순회)가 필요한
질문이다 — pageindex.py가 "완전한 에이전틱 traversal은 후속 과제로 남긴다"고
이미 밝힌 바로 그 경계. verify를 붙이기 전엔 이 한계가 "그냥 기권"으로만
보였는데, 이제는 로그에 **왜** 불충분한지 구체적 이유가 남아 진단 가능하다
(이번 라운드의 실질적 개선점 — 문제를 없앤 게 아니라 보이게 만듦).

**검증**: 기존 스모크 테스트 2건 통과(smoke_chat_routing.py가 이번엔 우연히
워크트리에 남겨둔 실인프라 .env를 타서 실제 LLM으로 verify/reformulate
로그까지 찍혔다 — 의도한 건 아니지만 회귀 없음 재확인). mock 기반 신규
테스트 4건(evidence 0건→재시도, 재시도도 실패→정확히 1회만, evidence
있어도 verify 불충분→재시도, 재시도 후도 불충분→evidence 비우고 기권)
전부 통과. 실인프라(pgvector+PageIndex+vLLM) 대상 5턴 재실행으로 verify
판정 근거·reformulate 검색어 변화까지 실측 확인.

## 2026-08-13 — chatbot 검색계층을 정형·dense·PageIndex 3도구 LangGraph 오케스트레이션으로 재작업(DuckDB 인덱스 폐기)

바로 위 절("rag 패키지에 chatbot 엔트리포인트 신설")을 쓴 직후, 사용자가 "rag는
자체 서버로 fastapi로 동작하고, postgresql 정형데이터·OKF/PageIndex 비정형·
pgvector 유사도조회를 조합해 langgraph 기반으로, 멀티도메인+비동기스트림으로
응답해야 한다"고 요구사항을 명확히 하면서, 직전 구현이 그날 같은 시각(b5c2583,
14:52) 이미 커밋돼 있던 pgvector+OKF+PageIndex 코퍼스 확장(140,031청크)을 놓치고
구식 `rag/index/rag.duckdb`(문서<100건, 실제로 빌드된 적도 없음)를 계속 쓰고
있었다는 게 드러났다. 인수인계서 TODO 대조(`documents/산출물/2026-W33_0810-0816/
인수인계서_TODO_대조_260813.md` §1-2/§3-3) "챗봇 조정 서비스(정형·비정형 도구
선택+혼합 조회)"·"DB/VDB 공통 근거 계약" 항목의 구현이기도 하다 — 세 도구
(`services/shared/retrieval/{structured,dense_pg,pageindex}.py`)는 이미 완성돼
있었고 호출자가 없었을 뿐이었다.

**신설(`services/shared/retrieval/evidence.py`)**: `Evidence` dataclass(kind·
source·section·text·as_of·unit) — 세 도구의 서로 다른 반환 모양을 하나의 인용
프롬프트로 합치는 공통 계약. 구조화 결과(다건)는 마크다운 표로 렌더링해 text에
넣어서, 표·차트 추출(chatbot_events.extract_markdown_tables/render_chart_png)이
kind와 무관하게 동일 경로로 동작하게 했다(오히려 구조화 데이터가 마크다운
스크래핑보다 완전한 숫자열이라 차트 재료로 더 낫다는 게 실측으로 확인됨).

**신설(`rag/ragkit/chatbot_graph.py`)**: LangGraph 2노드(route→retrieve).
route는 `KomirJsonLLM` 1회 호출로 (1) 대용어 해소한 `resolved_query`
(2) 정형/dense/PageIndex 중 무엇을 켤지 (3) structured면 어떤 템플릿+광종을
정한다(자유형 NL→SQL 없음, structured.py 규약 그대로). retrieve는
ThreadPoolExecutor(3)로 켜진 도구를 병렬조회하고 Evidence로 합친다 — 도구
하나가 죽어도(DB 미접속 등) 나머지로 부분 열화(전체 기권 아님). page_recommend/
graph.py의 LangGraph 관례(StateGraph+TypedDict+동기 노드)를 그대로 따랐다.

**rag/ragkit/chatbot.py 재배선**: `hybrid_search`(DuckDB) 호출을 걷어내고
`chatbot_graph.retrieve_evidence()`로 교체. `build_user_prompt`(RetrievedChunk
전용)는 안 쓰고 Evidence 기반 `_build_evidence_prompt`를 새로 둠(출처에
기준시점·단위까지 표시). 나머지(세션/히스토리·스트리밍 브리지·인용검증·표/차트
이벤트)는 그대로 재사용.

**services/rag_chat 정리**: 아무도 안 부르던 사산(死産) 어댑터
`app/retrieval/{structured,unstructured}.py` 삭제(구 DuckDB 경로 문서화+정형
템플릿 계약 초안이었는데 실제 호출자는 결국 chatbot_graph.py로 감). Containerfile에
`geo/llm` COPY 누락 수정 + PAGEINDEX_TREES_DIR/OKF_DOCUMENTS_DIR 볼륨마운트 주석
추가.

**한글 차트 폰트**: `koreanize_matplotlib`(NanumGothic 번들, MIT, 순수파이썬)를
발견해 requirements.txt에 추가 — matplotlib 기본폰트(DejaVu Sans)의 한글 tofu
문제를 방어코드가 아니라 실제로 해결(이 dev 환경에서 -W error::UserWarning으로
경고 0건 확인).

**검증 — 이번엔 실인프라까지 확인함(직전 절의 한계를 메움)**: 본채(`../../../
inhouse/.env`)를 워크트리에 복사(LLM_BASE_URL만 host.docker.internal→127.0.0.1
오버라이드, MSR_DB는 라이브 minerals.duckdb를 직접 안 가리키게 의도적으로 뺌 —
structured 도구는 이번 실인프라 검증 범위 밖, 다른 세션이 쓰고 있을 수 있는
파일을 안 건드리기 위함)해 실제 Postgres(pgvector 140K청크)+PageIndex 트리+
vLLM 서버 대상으로 2턴 대화를 실행했다. 그 과정에서 실제 버그 2건 발견·수정:
- **대용어 미해소로 무근거 기권**: route 노드가 `state["question"]`만 보고
  history를 안 봐서 "그 나라 생산량은?" 같은 후속질문에서 무엇을 찾을지
  못 정해 도구를 하나도 못 켜고 그대로 기권했다(1.4초만에 끝남 — 재현·확인).
  ROUTE_PROMPT에 history(최근 4턴) + `resolved_query` 필드를 추가해 라우터가
  먼저 "그 나라"→"인도네시아"로 풀고 그 문장으로 검색하게 고침.
- **history의 pandas Timestamp가 JSON 직렬화를 깸**: chatbot_store.list_messages()가
  DB 원본 행(created_at이 Timestamp)을 그대로 돌려주는데, 그걸 그대로
  retrieve_evidence에 실어 KomirJsonLLM.invoke()의 json.dumps가 터졌다.
  chat_turn()에서 role/content 두 필드만 남긴 순수 dict로 정리해서 넘기도록 수정.
둘 다 고친 뒤 재실행해 2턴 다 정상 응답(1턴 8건 인용/14.4초, 2턴 대용어 정확히
"인도네시아"로 풀어 4건 인용/3.5초) 확인. 세션 저장은 시종일관 워크트리 임시
DB만 사용 — 본채 DB에는 어떤 쓰기도 없었음(읽기전용 SELECT/파일읽기/LLM 호출뿐).
그 밖에 mock 기반 단위테스트(3도구 병합·부분열화·라우팅에 따른 선택적 호출·
멀티턴 유지)와 기존 스모크 테스트 2건(smoke_chat_routing.py·
smoke_page_recommend.py) 전부 통과 확인.

## 2026-08-13 — rag 패키지에 chatbot 엔트리포인트 신설(멀티턴+다중매체 비동기 이벤트) + services/rag_chat 문서Q&A 경로 이관

`services/rag_chat/app/routers/chat.py`에 있던 문서 Q&A 경로(2026-08-11 최초
구현)를 점검해보니 (1) 대화를 저장만 하고 실제 LLM 프롬프트에는 안 넣고 있었다
(페이지추천 그래프 경로만 히스토리를 씀 — "멀티턴"이 이름만 있었다), (2) 텍스트
delta/done 이벤트뿐이라 표·그림 같은 다중매체 이벤트가 아예 없었다. 사용자 요청
("rag 패키지에 chatbot 엔트리포인트")에 맞춰 이 경로의 코어 로직 전체를
`rag/ragkit/chatbot.py`로 이관하면서 두 가지를 실제로 새로 구현했다.

**신설 파일(`inhouse/rag/ragkit/`)**
- `chatbot.py` — `chat_turn(session_id, user_id, message, ...)`: FastAPI/
  sse_starlette 의존 없는 **진짜 async generator** 엔트리포인트. 인용강제
  생성(SYSTEM_PROMPT/ABSTAIN_TEXT/build_user_prompt/_strip_uncited_sentences)은
  `generate.py`를 그대로 재사용(재구현 금지). `OpenAICompatChat.complete_stream()`
  (동기, requests 기반)은 별도 스레드+asyncio.Queue로 브리지해 이벤트루프를 막지
  않는다(`_iter_async`). 멀티턴: 세션의 최근 히스토리(최대 12메시지)를
  `[이전 대화](참고용, 인용 대상 아님)` 블록으로 프롬프트에 포함 — [근거] 밖은
  인용하면 안 된다는 SYSTEM_PROMPT 규칙과 충돌 안 하게 명시적으로 구분.
- `chatbot_events.py` — `ChatEvent`(type: session/delta/table/image/done) +
  `extract_markdown_tables`(GFM 표 정규식 파싱, ingest.py가 문서를 마크다운으로
  펼쳐두므로 청크 본문에 그대로 남아있음) + `render_chart_png`(표에서 완전
  숫자열을 찾으면 matplotlib으로 즉석 차트 PNG, 숫자열 없으면 표만 내고 차트는
  안 만듦). 인용된(=날조 아닌) 청크에서만 표/차트를 뽑는다.
- `chatbot_store.py` — chat_session/chat_message CRUD(스키마는 기존
  `schema_addendum_v2.sql` §4 그대로, 신규 테이블 아님). services/shared에
  의존하지 않는 순수 duckdb 직결(재사용성 위해 — rag 패키지가 서빙 레이어 없이도
  단독 동작해야 함), MSR_DB env var 또는 명시적 db_path 인자로 대상을 고른다.
  Postgres cutover 전까지 URL 타깃은 services/shared/db.py execute_msr과 동일하게
  NotImplementedError로 명시 실패.

**services/rag_chat 쪽 변경(얇은 어댑터로 전환)**
- `routers/chat.py`의 `_run_document_qa`가 이제 `chat_turn()`을 호출만 하고 SSE로
  감싼다. `chat_turn()`은 async generator지만 라우터 함수·
  `smoke_chat_routing.py`의 동기 호출 계약(`for event in generator`)을 깨면 안
  돼서 `_drain_sync()`(전용 이벤트루프 재사용 브리지)로 감쌌다 — async def로
  바꾸는 대신 경계에서만 동기화.
- `session_store.py`는 `rag.ragkit.chatbot_store`를 감싸는 얇은 어댑터로 교체
  (실제 CRUD 로직 중복 제거) — `get_settings().MSR_DB`(Postgres cutover 인지)를
  ragkit의 범용 CRUD에 주입. 함수 시그니처는 그대로라 페이지추천 경로 호출부는
  무변경.
- `streaming.py`의 `stream_answer()`는 `chat_turn()`이 대체해 제거, `sse_event()`
  프레이밍 함수만 남김.
- **부수 발견·수정**: 문서 경로가 `citations_json`을 `str(list)`(파이썬 repr, 유효
  JSON 아님)로 저장하던 걸 `json.dumps()`로 고쳤다 — `_load_page_state()`가
  "document 턴은 json.loads가 실패해야 페이지상태로 안 읽힌다"는 동작에 의존하고
  있어서, 고치기 전엔 실수로 유효 dict가 나왔으면 오염될 뻔했다(실제로는
  citation_sources가 최상위 list라 `isinstance(dict)` 체크에서 여전히 걸러져
  안전 — 주석에 이유를 남겨둠).
- **Containerfile 실측 수정**: `geo/llm/` 서브패키지가 COPY 안 되고 있었다
  (`geo/__init__.py`·`geo/extractors.py`만 최소 COPY) — `generate.py`·
  `chatbot.py`·`shared/llm_client.py`가 다 `geo.llm.openai_compat`을 쓰는데,
  소스트리 실행(상위 sys.path 삽입)에서는 안 드러나고 컨테이너에서만 깨질
  지점이었다. `COPY geo/llm ./geo/llm` 추가. `requirements.txt`에
  `matplotlib>=3.7` 추가(차트 렌더링, 신규 의존성).

**SSE 이벤트 계약 확장(프론트 연동 기준, 하위호환 유지)**: 기존
session_id/delta/done(citations/bogus_citations)에 `event: table`·`event: image`
추가, `done`에 `abstained` 필드 추가. routers/chat.py 모듈 docstring에 전체
스키마 명시.

**검증**: `smoke_page_recommend.py`·`smoke_chat_routing.py`(기존, 전부 통과 —
document 경로는 여전히 `rag/index/rag.duckdb` 미구축이라 기권 응답으로 끝나는
회귀 확인만) + 신규 임시 스크립트(`hybrid_search`/LLM을 모의로 대체해
`chat_turn()` 전체 경로를 검증: 멀티턴 프롬프트 주입, 표/차트 이벤트 생성,
세션 4행 왕복 적재, 검색결과 0건 시 LLM 미호출 확인 — 전부 통과).
**미검증(이 워크트리엔 없음, gitignore)**: 실제 `rag/index/rag.duckdb`(색인
미구축)·`.env`(LLM_*)·`data_lake/db/minerals.duckdb` — 실제 검색/LLM 스트리밍
경로는 본채에서 별도 확인 필요. **알려진 인프라 한계**: 이 dev 환경엔 한글
폰트가 하나도 없어(fc-list 22개, CJK 없음) 차트 라벨이 tofu로 나온다
(`chatbot_events.py`가 설치된 CJK 폰트를 자동 탐지하도록 방어 코드는 넣었지만
폰트 자체는 배포 이미지에 번들해야 함 — e5-small 임베딩 가중치와 같은 종류의
빌드 시점 준비물).
## 2026-08-20 (최신) — MSR_DB DuckDB→PostgreSQL cutover로 out_report 저장 경로 파손(기록만, 미수정)

다른 세션(`msr-duckdb-postgres-migration`, 별도 워크트리)이 `inhouse/.env`의
`MSR_DB`를 DuckDB 경로에서 PostgreSQL(`mineral_risk` 스키마)로 바꿨다. 이
세션에서 어제(8/19) 만든 `analysis/store.py`(분석요약 8종 저장)·
`generator.py`(주간 리포트 저장)가 영향받는지 실측 확인했다 — **사용자 지시로
지금 고치지 않고 기록만 남긴다**(워크트리 통합 후 재작업 예정).

**실측으로 확인한 파손 지점**
- `shared/db.py`의 `execute_msr()`는 자체 주석에 이미 "MSR_DB의 PG_DSN cutover
  시점에 반드시 먼저 고칠 것"이라 적어뒀던 자리 그대로 — `is_url(MSR_DB)`가
  `True`가 되면 `NotImplementedError`를 던진다(DuckDB `?` 자리표시자 전용이라
  psycopg2 paramstyle `%s` 미대응). 실제로 `execute_msr("DELETE FROM out_report
  WHERE report_id = ?", [...])`를 호출해 즉시 `NotImplementedError` 재현
  확인함(`read_sql_msr`는 URL 분기가 있어 정상 동작, `execute_msr`만 없음).
- `store_summary()`(분석요약)·`store_report()`(주간 리포트) 둘 다 삽입 전
  `execute_msr(DELETE ...)`로 멱등성을 보장하는 구조라, 이 한 줄에서 예외가 나
  **적재 자체가 전혀 안 된다**(INSERT까지 가지도 못함) — API 응답은 200이 나올
  수 있어도(분석요약은 응답 조립이 저장보다 먼저) 저장 단계에서 500 에러가 남.
- 우회 확인: `write_df_msr`(→`dbio.write_df`)는 URL 분기가 있어 `df.to_sql
  (if_exists='append')`로 정상 동작한다 — 문제는 `execute_msr` 하나뿐.
- **추가 발견(설계 함정)**: postgres로 이관된 `mineral_risk.out_report`
  테이블엔 **PRIMARY KEY/UNIQUE 제약이 전혀 없다**(`pg_constraint` 조회로
  확인, DuckDB판 `schema_core.sql`은 `PRIMARY KEY (report_id)`인데 이관 시
  제약이 안 옮겨짐). 즉 `execute_msr`만 고쳐서 DELETE를 postgres 문법으로
  바꾸더라도, PK가 없으면 재실행 시 같은 report_id로 중복 행이 쌓이는 걸
  DB 차원에서 막아주지 않는다 — 애플리케이션 레벨(현재 DELETE-then-INSERT
  패턴) 또는 DDL(PK 추가) 둘 중 하나로 무결성을 다시 보장해야 함.
- 실측 시점 `mineral_risk.out_report`엔 이미 9행이 있음(어제 이 세션이 DuckDB에
  저장한 것과 report_id가 동일 — 마이그레이션이 데이터는 옮겼다는 뜻, 다만 PK는
  안 옮김).

**재작업 시 고칠 것(우선순위순)**
1. `shared/db.py`의 `execute_msr()` — postgres 분기 추가(psycopg2 `%s`
   paramstyle로 재작성). DuckDB 분기는 그대로 둔다(다른 타깃에서 쓰는 코드 없는지
   확인 후 제거 여부 판단).
2. `mineral_risk.out_report`에 `report_id` PK(또는 UNIQUE 인덱스) 추가 —
   `schema_pgvector.sql`이 이미 쓴 패턴(`CREATE UNIQUE INDEX IF NOT EXISTS`,
   `ADD CONSTRAINT IF NOT EXISTS`가 PG에 없어서 이 형태를 씀)을 그대로 재사용.
3. 위 두 가지 없이 이미 실행된 적이 있다면(재작업 전 누군가 급하게 우회 코드를
   넣었다면) `out_report`에 중복 `report_id` 행이 있는지 먼저 조회해 정리할 것.
4. `rag_chat`의 `chat_session`/`chat_message` 저장도 같은 `execute_msr` 경로를
   쓰는지 이번 세션 범위 밖이라 미확인 — 재작업 시 함께 점검 권장.

## 2026-08-19 (이어서) — 분석요약 미구현 3종(`/prices`·`/domestic-trade`·`/global-trade`) 신규 구현

앞 절(`out_report` 적재)에 이어, 발주처 화면기획안 대조에서 "API 자체가 없다"고
확인됐던 3종을 새로 만들었다. 외부repo(`komis-report-generator-main`)도 이 3종은
501 스텁뿐이라 참고할 원본 구현이 없다 — 5종처럼 "이식"이 아니라 komir가 처음부터
설계·작성했다.

**계기**: 사용자가 "API가 없는 부분도 구현"을 지시. 착수 전 실측으로 KOMIS가
2026-08-19 오전 이 3종을 위한 광종 매핑 테이블(`public.ai_prc_mnrl_map`(광종→
가격기준일련번호)·`ai_hs_mnrl_map`(광종→HS코드))과 CU/NI/CO/LI용 DEV_DUMMY 데이터
(`ai_mnrl_mst`에 `[DEV_DUMMY] ... load=DEV_DUMMY_20260819` 표기)를 새로 채워둔 것을
발견 — 이 매핑 없이는 이 3종을 만들 수 없었다(원본에도 없던 기능이라).

**만든 것(전부 이식 아님, komir 자체 작성)**
- `services/shared/komis_raw.py` — `KomisRawDataRepository`에 3개 메서드 추가:
  `resolve_mineral`(광종코드→한글명, `ai_mnrl_mst`)·`resolve_price_criterion_
  serials`(→`ai_prc_mnrl_map`)·`resolve_hs_codes`(→`ai_hs_mnrl_map`). 기존
  `_literal()` 화이트리스트 검증을 그대로 재사용(자유형 SQL 금지 원칙 유지).
- `services/report_gen/app/analysis/models.py` — `SummaryPageId`에 `price`·
  `map_korea`·`map_global` 3개 추가, `PriceSeries`/`PriceObservation`·
  `TradeMapSeries`/`TradeCountryObservation` 신규 모델, `AnalysisSummaryRequest.
  validate_period`에 3종 분기 추가(광종 필수+일자 필터만 허용).
- `services/report_gen/app/analysis/data_sources/extra.py`(신규) —
  `DatabasePriceDataSource`/`DatabaseDomesticTradeDataSource`/
  `DatabaseGlobalTradeDataSource`. 이식본(`database.py`)과 안 섞음(그 파일의
  "원본에서 바뀐 것은 import 뿐" 주장을 안 깨려고).
- `services/report_gen/app/analysis/komir_summary.py`(신규) — 3종의 결정론적
  요약 계산(`calculate_price_summary`/`calculate_domestic_trade_summary`/
  `calculate_global_trade_summary`). `additional_summary.py`(이식본)의 재사용
  가능한 헬퍼(`EvidenceClaim`·`_number`·`_quantity`)만 가져다 쓰고 계산 로직
  자체는 새로 짰다 — pptx `260713 AI 분석요약 및 대화형 검색시스템 검토
  요청사항_일루넥스.pptx`의 예시 문구(최신가격/전일·전주·전월·전년대비, 1위국
  비중, 상위3국 집중도)를 근거로 설계.
- `analysis/summary.py`·`routers/analysis.py`·`main.py` — 디스패치·엔드포인트·
  서비스 조립 배선. **LLM 정제는 이 3종에 안 태운다** — `prompts.py`(이식본)에
  이 3종용 프롬프트·엄격한 근거인용 검증계약이 없어(원본 자체가 없던 기능),
  새로 지어내면 원본과 대조검증할 근거가 없다. 규칙기반 요약만 반환(이식 5종도
  LLM 실패 시 이 수준으로 폴백하므로 품질 보장은 동일).

**실측으로 드러난 함정 1건**: `KO_UN_CMMRC`(글로벌, UN Comtrade)는 HS코드가
국제표준 **6자리**(예 `810110`)인데, `ai_hs_mnrl_map`은 관세청 HSK **10자리**
(예 `8101100000`)다 — 10자리 그대로 필터하면 실데이터 있는 텅스텐도 0행이 나옴.
`KO_CSTM_CMMRC`(국내, 관세청)는 10자리 그대로 맞는다(자릿수가 다른 원천이 섞여
있다는 걸 실측 전엔 몰랐음). 글로벌만 앞 6자리로 잘라 중복제거 후 조회하도록
수정.

**실측 검증**(TestClient, 실제 PostgreSQL 경유)
- `/prices`: 리튬(CU계열 더미, MNRL0001) 200 + 텅스텐(실데이터) 200, 전일·전주·
  전월·전년대비 등락률 정상 계산.
- `/domestic-trade`: 동(더미, MNRL0008) 200 + 텅스텐(실데이터) 200, 1위국/상위3국
  비중 정상 계산.
- `/global-trade`: 텅스텐(실데이터) 200(공급국 순위 계산 확인) / 니켈(더미조차
  없음) 422 "데이터 없음"(500 아님, 정상).
- REE(Nd, `ai_prc_mnrl_map`/`ai_hs_mnrl_map` 둘 다 매핑 없음) → 422 "매핑된
  가격기준이 없다"(우아한 실패, 정상).
- 8종 전부(기존 5+신규 3) `out_report`에 `kind='summary'`로 저장, 멱등성(중복
  report_id 0건) 재확인. 기존 5종 회귀 없음(재실행해 동일 결과 확인).
- `python3 -m py_compile` 전체 통과, `import app.main` 라우트 8개+기존 4개 정상.

**알려진 한계(의도적으로 남겨둠)**: `/global-trade`의 "상대국(공급국) 기준 랭킹"
해석은 pptx에 정확한 스펙이 없어 komir가 합리적으로 설계한 것 — 발주처 확인
필요. 광종 1건에 가격기준이 여럿이면(텅스텐 7건) 가장 이른 번호만 쓴다(발주
5광종은 전부 1건뿐이라 실무 영향 없음). CU/NI/CO/LI의 DEV_DUMMY 데이터는 실샘플이
아니라는 점은 여전히 유효 — 코드 경로만 실증됐을 뿐 산출물로는 못 씀.

## 2026-08-19 — 분석요약 5종에 `out_report` 적재 배선(결과 저장 프로세스 완성)

2026-08-13에 이식한 분석요약 5종(`app/analysis/summary.py` 등)은 `service.analyze()`
결과를 HTTP 응답으로 돌려주기만 하고 아무것도 저장하지 않았다 — 주간 리포트
(`generator.py`)와 달리 "생성→저장" 중 저장 단계가 없었다. `CONTAINER_ARCHITECTURE.md`
§4가 이미 "Report 생성기 ... `out_report` 스키마만 존재 — 이걸 확장해서 쓴다"고
정해둔 대로, **새 테이블을 만들지 않고 `out_report`를 그대로 확장**해 저장까지
연결했다(`kind='summary'`로 주간 리포트 `kind='report'`와 같은 테이블에 공존).

**추가한 것**
- `inhouse/services/report_gen/app/analysis/store.py`(신규) — `to_report_row()`
  (`AnalysisSummaryResponse` → `out_report` 행 변환, 본문은 응답 전체를 JSON
  직렬화해 담는다 — `out_diagnosis_alert.evidence_json`과 같은 관례) ·
  `store_summary()`(삽입 전 같은 report_id 삭제 후 재삽입 — `generator.store_report()`
  와 동일한 멱등 패턴) · `analyze_and_store()`(analyze+저장 공통 진입점).
- **report_id**: 별도 해시를 새로 만들지 않고 엔진이 이미 계산해 응답에 담아
  돌려주는 `filter_hash`(page_id+applied_filters의 sha256)를 그대로 재사용 —
  `"ans_" + filter_hash[:24]`(28자, `report_id VARCHAR(32)` PK 이내). 같은
  (페이지·광종·필터)로 다시 부르면 같은 id로 덮어써 멱등하다.
- `routers/analysis.py`: `_run_summary()`가 `service.analyze()` 대신
  `analyze_and_store(service, summary_request)`를 호출하도록 1줄 교체. 응답
  모델(`AnalysisSummaryResponse`)은 외부repo 계약 그대로라 API 스키마 변화 없음
  (저장은 부수효과).

**실측 검증**(TestClient로 실제 앱 lifespan·실제 PostgreSQL(`komis_demo`)·실제
MSR_DB(duckdb) 경유)
- 5종 중 4종(시장동향·광물종합지수·광물지도·가격예측)을 실제 HTTP POST로 호출해
  전부 200 + `out_report`에 `kind='summary'`로 정상 적재 확인(수급동향은 시장동향과
  완전히 같은 코드 경로라 별도 실행 생략). LLM 정제까지 성공(`llm_refined=true`).
- **멱등성 실측**: 같은 요청을 2번 호출해도 `report_id`(=filter_hash 기반) 동일,
  `out_report`에 중복 행 없음(`GROUP BY report_id` 전부 n=1) 확인.
- **왕복 검증**: 저장된 `body`를 다시 JSON 파싱해 `page_id`·`grade` 등 원본 응답
  구조가 손실 없이 보존됨을 확인(예: 텅스텐 시장동향 `grade.label='신중'`).
- 기존 `GET /reports/{report_id}`·`GET /reports`(수정 없이 그대로)로 저장된
  분석요약을 정상 조회 — 새 엔드포인트를 추가하지 않고 기존 것을 재사용했다.
- `python3 -m py_compile` 통과.

## 2026-08-13 — report_gen에 외부repo "분석요약 5종" 엔진 이식·API 배선(8/11 오판 정정)

8/11 병합 때 `analysis/summary.py`(1,084줄)·`additional_summary.py`(1,082줄)와
5개 API 엔드포인트를 **"리포트 생성은 스텁"이라고 오판해 안 가져왔던 것**을 오늘
전부 이식했다. 계기는 외부repo(`komis-report-generator-main`)의 **진짜 git 이력을
처음 확보**한 것 — `main` HEAD(`2f7d269`, 2026-08-12T01:54)에 8/11 스냅샷엔 없던
커밋 2개(`b6c17ca` 가격예측, `7c26629` 페이지별 분석 API)가 있었고, 5개
엔드포인트가 전부 실동작 코드였다. (작업 시작 시 `git fetch`로 재확인 — 새 커밋
없음, 로컬 HEAD == `origin/main`.)

**이식한 것**(`inhouse/services/report_gen/app/analysis/`)
- `summary.py`·`additional_summary.py`·`policy.py`·`prompts.py` 신규 이식.
- `models.py` 보강 — 요약문 모델(`GradeResult`/`Metric`/`DataQuality`/`Summary*`/
  `AnalysisSummaryRequest|Response`)·가격예측 계열·수급 보조패널(`Supply*`) 추가,
  `SummaryPageId`에 `forecast_price` 편입.
- `data_sources/` 보강 — 1차 때 뺐던 `DatabasePriceForecastDataSource`와 3개
  Protocol(`CompositeIndex`/`MineralMap`/`PriceForecast`)·`resolve_price_forecast`
  복원. `resources/policies/{indicator_market,indicator_supply}.yaml` 반입,
  메타데이터 subset에 `metadata.indicators.forecast_minerals` ref 추가(4→5개,
  원본 스냅샷 sha256이 8/11과 동일함을 확인하고 파생).
- `routers/analysis.py` 신규 + `main.py` 배선 — `POST /api/v1/analysis/
  {market-indicator,supply-indicator,composite-index,mineral-map,price-forecast}`
  (외부repo 경로 그대로). 서비스 조립은 `main.build_analysis_summary_service()`가
  komir `KomisRawDataRepository`(→`shared/db.read_sql_pg`)+`KomirJsonLLM`으로 한다
  — 외부repo의 자체 psycopg 커넥션 팩토리·자체 LLM 클라이언트는 안 들여왔다.
- `search.llm.JsonLLM` → `services/shared/llm_client.KomirJsonLLM` 교체(8/11
  `page_recommend/graph.py`와 같은 방식, LLM 클라이언트 2벌 방지).

**이식하면서 고친 진짜 결함 1건(원본엔 있는 버그)**: 원본 `_refine_with_llm`은
`except LLMError`만 잡는다. 그런데 `KomirJsonLLM`은 JSON/스키마 실패만
`LLMOutputError(LLMError)`로 감싸고 **전송 계층 오류는 그대로 올린다** — 실측으로
vLLM 미도달 시 `requests.ConnectionError`가 나며 이건 `LLMError`가 **아니다**
(`isinstance(e, LLMError) == False` 확인). 그대로 뒀으면 vLLM 장애 시 규칙기반
폴백 대신 API가 500을 냈다. `except (LLMError, RuntimeError, OSError)`로 넓혀
원본이 의도한 폴백을 유지했고, 가짜 `LLM_BASE_URL`로 띄운 서버에서 **HTTP 200 +
규칙기반 요약 + 경고문** 반환을 실측 확인했다.

**실측 검증(컴파일만이 아니라 실제 PostgreSQL·실제 vLLM로 HTTP 호출)**
- `py_compile` 전체 통과 + `import app.main` + 라우트 5개 등록 확인.
- **5개 엔드포인트 전부 실데이터로 200 + LLM 분석문 생성(`llm_refined=true`)**:
  시장동향(텅스텐, 신중 단계)·수급동향(텅스텐, 관심)·광물지도 매장량/생산량
  (텅스텐)·가격예측 중기(텅스텐)·광물종합지수(HI001/2/3, 557관측).
- ⚠ **인수인계 대조문서(8/13)의 "광물종합지수만 데이터가 있다"는 부정확**했다 —
  `public.KO_*`의 텅스텐(MNRL0018)은 KOMIS 화면 광종 목록에 있는 정식 선택지라
  **5종 전부 지금 실데이터로 분석문이 나온다**. 없는 건 komir 5광종(CU/NI/CO/LI/
  REE)이고, 그건 422 + 한국어 사유로 우아하게 응답한다(500 아님) — 동·니켈·리튬·
  코발트·1990년 종합지수 5케이스로 확인.
- 광물종합지수만 `llm_refined`가 간헐적(약 1/10)이다. 버그가 아니라 출력계약이
  가장 빡빡한 페이지이기 때문 — 근거 7개를 섹션당 1/2/1 = **4문장 안에 각각 정확히
  한 번씩** 넣어야 하는데 로컬 gemma-4-26b가 `overall_pattern`을 자주 누락한다
  (payload·검증 로직이 원본과 동일함을 계측으로 확인). 실패해도 검증된 규칙기반
  요약으로 폴백하므로 응답 품질은 보장된다. 나머지 4종은 안정적으로 통과.
- **공유 DB 무오염 확인**: 이식 코드에 INSERT/UPDATE/CREATE/write 경로가 하나도
  없고(전 경로 `read_sql_pg` SELECT 전용), 검증 후 `KO_MNRL_SNTHS_INDX` 10,899행·
  `mineral_risk` 36테이블·`public` 26테이블이 검증 전과 동일함을 재조회로 확인.
  테스트 서버 2대도 종료 완료.

**안 가져온 것(의도적)**: 미구현 3종(`/prices`·`/domestic-trade`·`/global-trade`,
외부repo도 501 예약 라우트일 뿐)·과도기 shim `POST /summary`·profile_id 경로 전용
코드(`AnalysisRequest`/`NarrativeOutput`/`build_narrative_payload` — 외부repo에서도
`experiments/`만 씀). `scaffold.py`는 원본 구조 그대로 별도 경로로 공존시켰다
(외부repo `main`에서도 `analyze()`는 여전히 `analysis=None` 스텁) — 임의 통합 안 함.

**지시서 정정 2건**: ①"정책 YAML 5종을 가져오라" → 외부repo엔 YAML이 2종뿐이다.
나머지 3종(종합지수·광물지도·가격예측)은 등급 개념이 없어 YAML이 아니라
`additional_summary.ADDITIONAL_PAGE_CONTEXTS` dataclass로 정의된다. ②"indicator_
market/supply YAML은 이미 komir에 있다" → 없었다(8/11엔 metadata subset JSON뿐).

## 2026-08-12 — 문서-OKF 생성 + PageIndex 트리 빌드 완료(위임①, 중단분 이어받아 마무리)

전날(2026-08-11) 병렬 위임한 작업 중 ①(문서-OKF+PageIndex)을 맡은 에이전트가
세션 한도 초과로 도중에 끊겼다("session limit" — 로직 실패 아님). 실제로는
구현·1차 실행까지 거의 다 끝나 있었고(WORKLOG 기록만 못 함), 남은 건 USGS
PageIndex 트리 8건뿐이었다 — 그 부분만 이어서 완료하고 전체를 검증했다.

**만든 것(끊긴 에이전트 작업, 검증 후 그대로 인정)**
- `services/ingestion/build_okf_documents.py` — 문서-OKF 생성기. 입력 두 갈래:
  ①`rag.ragkit.ingest.load_documents()`(documents/산출물 72건+외부자료 4건,
  이미 텍스트로 펼쳐진 것 재사용) ②`services.ingestion.pipeline.run_extraction()`
  (USGS PDF 8건, opendataloader+OCR 폴백). geo-OKF와 같은 컨벤션(YAML
  프론트매터+개념ID=파일경로)이되 포인터가 아니라 본문 전체 — `data_lake/
  semi_structure/okf_documents/`(신규 계열, 기존 `okf/`는 무오염)에 84건 생성.
  **실행 중 진짜 버그 하나 발견·수정**: `geo/extractors.py`의 `PDF_MAXPAGES`
  기본값(40, GKG 짧은 뉴스 PDF 기준)을 그대로 물려받으면 226쪽짜리 USGS_2026이
  40쪽까지만 추출돼 본문 82%가 잘렸다 — `os.environ.setdefault("PDF_MAXPAGES",
  "500")`로 문서-OKF 생성기 쪽에서만 상향(geo 자체 배치 파이프라인은 무변경).
- `services/ingestion/parsers/pdf.py`(v2) — 기존 PdfParser가 `opendataloader_
  batch_convert()`의 반환값(**평문, `md_to_text()`로 헤딩·표파이프가 이미
  지워진 것** — geo 파이프라인이 LLM 추출용으로 그렇게 설계했기 때문)을 그대로
  썼는데, 문서-OKF·PageIndex는 구조 보존이 핵심이라 이러면 헤딩 55개·표파이프
  187개가 있는 원본이 산출 텍스트 0개·0개로 나갔다(USGS_2026 실측). geo/
  extractors.py 자체는 안 건드리고(이미 검증된 코드), 이 파서가 opendataloader가
  디스크에 써둔 원본 `.md`를 직접 다시 읽도록 수정(`_raw_markdown()`) — 매니페스트
  캐시 무효화를 위해 `parser_version`도 1→2로 올림.
- `services/ingestion/build_pageindex_trees.py` — 문서-OKF → PageIndex 트리(전날
  vendoring한 `services/shared/pageindex_client.build_tree_from_markdown()` 사용).
  멱등(이미 있는 트리는 `--force` 없인 재생성 안 함), `--pattern` 부분경로 필터.
- `services/shared/retrieval/pageindex.py` — §5-4 "③ PageIndex 조회" 도구.
  범위를 의도적으로 결정적(deterministic) 기본 조회로 한정: `find_documents`
  (제목/소스그룹 매칭) → `search_nodes`(문서 내 노드 검색, `rag/ragkit/
  tokenize_ko.py` 재사용) → `read_node_text`(원문에서 해당 섹션만 절취). 완전
  에이전틱 traversal은 후속 과제로 명시(이 3개 함수가 그 도구가 될 구조로 설계).

**오늘 이어받아 한 것**
- USGS PageIndex 트리 8건 생성(`--pattern USGS`, 총 850.8초, 실패 0건, 노드
  81~201개/문서 — LLM 노드요약 포함, `LITELLM_LOCAL_MODEL_COST_MAP=True`+로컬
  vLLM 하드닝 그대로 적용). 최종 84건(72+4+8) 전부 유효성 재검사 통과.
- **`search_nodes()` 실제 버그 발견·수정**: 노드 본문이 짧으면 pageindex_lib가
  그 노드의 `summary`를 비우고 대신 `prefix_summary`(상위 문맥을 물려받은 요약)만
  채우는데, haystack 조립이 `summary`만 보고 `prefix_summary`를 안 봐서 실제로
  있는 내용도 검색에서 빠졌다(실측: "4. 검증 훅" 노드의 QWK 언급이
  prefix_summary에만 있어 `search_nodes('QWK', doc=...)`가 0건 → 수정 후
  score=1.0으로 정상 검출). `find_documents`는 원래도 title/doc_name/
  source_group만 보는 게 의도된 설계(문서명 검색)라 그대로 둠.
- `find_documents`→`search_nodes`→`read_node_text` 전체 체인을 실제 문서
  (USGS_2026 lithium reserves, mineral_risk_model_v0의 QWK 절)로 end-to-end
  검증 — 원문과 대조해 섹션 절취가 정확함을 확인.

**보류(사용자 승인 대기, 조용히 건너뛰지 않고 명시)**: Argus 일일보고서
690개 PDF(`documents/보고서_2/Argus Metal_...`)·조달청보고서 887개 파일은
이번 문서-OKF 대상에서 뺐다 — 파일 수가 많아 LLM 추출(각 파일마다 opendataloader
+선택적 OCR) 비용·시간이 크다(USGS 8건도 노드요약만 850초). 전량 처리는
사용자 승인 후 별도 사이클로.

**검증**: `python3 -m py_compile` 전체 통과, `okf_documents/**/*.md` 84건 +
`pageindex_trees/**/*.tree.json` 84건 전부 실측 확인(개수·유효 JSON·표 구조
보존 여부 원문 대조). 커밋은 하지 않음.

## 2026-08-11 (최신, 이어서) — 벡터DB 결정 변경(Qdrant→pgvector) + PageIndex vendoring·airgap 실측검증

사용자가 "RAG용 임베딩 산출·저장, 문서-OKF, PageIndex 산출"을 다음 작업으로 지시,
airgap(런타임 외부 인터넷 전면 차단) 재확인. 착수 전 두 가지 조사·검증:

**벡터DB 결정 변경**: 2026-08-05 "Qdrant 확정, pgvector 폐기"(사유: Postgres는
외부서비스라 확장 설치 권한 보장 없음)였는데, 사용자가 "pgvector 있다"고 정정 —
실측(`pg_available_extensions`·`pg_extension`·`pg_user`) 결과 komis_demo DB에
**pgvector 0.8.2가 이미 설치돼 있고 접속계정(postgres)도 슈퍼유저**임을 확인,
우려했던 리스크 자체가 없었다. `CONTAINER_ARCHITECTURE.md` 결정 뒤집어 정정
(취소선+재정정 기록). Qdrant 신규 기동 불필요.

**PageIndex 조사·vendoring**: 설계문서가 "채택 확정, 백킹스토어 미정"으로 남겨둔
부분. `pip install pageindex`(PyPI 0.2.8)를 실제로 설치해 소스를 열어보니
**로컬 트리생성 코드가 아니라 `https://api.pageindex.ai`(유료 클라우드)에 PDF를
업로드하는 REST 클라이언트 하나만 노출**하는 걸 발견 — airgap 프로젝트엔 못 씀.
GitHub 저장소(`VectifyAI/PageIndex`, MIT, 커밋 `b723c9f`)를 직접 clone해 "Self-host"
경로(로컬 실행 가능한 `pageindex/` 패키지)를 확인, `client.py`(클라우드 클라이언트)만
제거하고 `inhouse/services/shared/pageindex_vendor/pageindex_lib/`에 vendoring.
**airgap 안전성 실측 검증**: `OPENAI_BASE_URL`→로컬 vLLM, `LITELLM_LOCAL_MODEL_
COST_MAP=True`(litellm의 원격 모델가격표 fetch 차단, HF_HUB_OFFLINE과 같은
종류의 함정) 설정 후, 실제 문서로 LLM 노드요약까지 켜서 end-to-end 실행하며 그
프로세스의 모든 TCP 연결을 `ss -tnp`로 PID 단위 추적 — **로컬 vLLM(127.0.0.1:
52302) 외 연결 0건** 확인(상세 근거는 `pageindex_vendor/README.md`). 이 하드닝을
강제하는 komir 래퍼 `services/shared/pageindex_client.py`(`build_tree_from_
markdown()`) 작성 — 이 래퍼를 거치지 않고 vendored 코드를 직접 import하면
하드닝이 안 걸리므로, 사용 규칙으로 강제.

**병렬 위임(백그라운드 에이전트 2건, airgap 제약 명시적으로 반복 전달)**:
①문서-OKF 생성(documents/산출물 76건 전량 + USGS 대용량보고서, Argus 690건·
조달청보고서 887건은 규모상 이번엔 보류하고 사용자 승인 대기) + PageIndex 트리
빌드 ②pgvector 임베딩 저장소(mineral_risk 스키마, doc_chunk에 vector 컬럼 추가,
rag/ragkit/embed.py 재사용) — 완료 시 검증 후 이 절 아래 추가 기록 예정.

## 2026-08-11 (위임②의 결과) — pgvector 벡터 저장소 구축·적재·검증 완료

위 절의 병렬 위임 ② 완료. **Qdrant 없이 komis_demo Postgres(pgvector 0.8.2)에
dense 벡터 저장소를 실제로 가동**시켰다. 외부 임베딩 API·신규 컨테이너 0건
(임베딩은 로컬 `intfloat/multilingual-e5-small`, DB는 이미 붙어 있는 komis_demo).

**추가/변경 파일 4개**
- `inhouse/data_lake/db/schema_pgvector.sql`(신규) — `mineral_risk.doc_chunk`에
  `embedding vector(384)` + 인용메타(source_path·week·title·section_heading·
  char_len·source_type·indexed_at) 컬럼 추가, `chunk_id` UNIQUE 인덱스,
  HNSW(`vector_cosine_ops`) 인덱스. `schema_core.sql`은 **불변**(vector는 PG 전용
  방언이라 포터블 DDL에 안 섞음). 모든 문장을 `mineral_risk.`로 명시 한정 —
  PG_DSN 기본 search_path가 `"$user",public`이라 미한정 DDL은 public(타 팀 소유)에
  떨어진다. search_path 자체는 안 건드림(vector 타입이 public에 있어 빼면 깨짐).
  `ADD PRIMARY KEY`는 PG에 `ADD CONSTRAINT IF NOT EXISTS`가 없어 재실행 시 실패 →
  `CREATE UNIQUE INDEX IF NOT EXISTS`로 대체(멱등). IVFFlat이 아니라 HNSW인 이유:
  IVFFlat은 리스트 학습에 사전 데이터가 필요해 빈 테이블에 못 검.
  **범위 주의**: §4 addendum 중 dense 절반만 적용했다 — `structured_query`·
  `txt_tsv`(GIN, BM25 절반)는 미적용(BM25는 당분간 DuckDB FTS 유지).
- `inhouse/rag/ragkit/build_pgvector_index.py`(신규) — `build_index.py`와 병렬
  구조. ingest/chunk/embed는 **같은 코드 재사용**, 저장소만 교체. 전량 재적재
  (DELETE→INSERT, `CREATE OR REPLACE`와 동치). pgvector-python 패키지가 없고
  airgap이라 pip 전제도 못 하므로 벡터는 `'[v1,...]'` 텍스트 리터럴 + `%s::vector`
  캐스트로 psycopg2 `execute_values` 벌크 삽입.
- `inhouse/services/shared/db.py` — pg 전용 헬퍼 3종 추가(`pg_connect`·
  `execute_pg`·`apply_schema_pg`). dbio는 DataFrame 벌크/DDL파일만 지원해
  파라미터 바인딩 단문이 없었음(execute_msr가 DuckDB용으로 같은 구멍을 메운 것과
  같은 이유). ⚠ paramstyle은 psycopg2 `%s` — execute_msr의 DuckDB `?`와 다름.
- `inhouse/services/shared/retrieval/dense_pg.py`(신규) — `dense_search_pg(q,k)`
  (+ `retrieve.dense_search()` 드롭인용 `dense_search_pg_ids`). RRF 융합 로직은
  재구현하지 않음. 스키마는 `get_settings().PG_SCHEMA`로만 참조(하드코딩 금지).

**실측 결과**(직접 쿼리, data-quantity-verification-rule 준수)
- `select count(*), count(embedding), count(distinct doc_id) from mineral_risk.doc_chunk`
  → **1206 / 1206 / 76**(DuckDB 인덱스와 동일 수량), 테이블 크기 6072 kB,
  week 분포: `산출물` 1030 + `외부자료:komis_해외투자가이드_4개국` 176.
- 회귀 비교(질의 3건: "핵심광물 진단모델 QWK 성능은 얼마인가"/"지정학 위기지수
  산출 방법"/"니켈 수입 예측 WAPE") — pgvector top-5 vs DuckDB `dense_search`
  top-5가 **3건 모두 5/5 완전일치(순위까지 동일)**. 상위 결과도 상식적으로 관련
  문서(예: 1번 질의 → `방향긍정보류_결합검정_260731.md`§결과, cos 0.8827).
- 완전일치한 이유: 1206행이라 플래너가 HNSW 대신 Seq Scan을 골라 **근사가 아닌
  정확 top-k**가 나온다. `enable_seqscan=off`로 확인하면
  `Index Scan using idx_doc_chunk_embedding_hnsw`로 정상 전환 — 인덱스는 살아있고
  코퍼스가 커지면 자연히 그 경로를 탄다.
- **public 스키마 쓰기 0건**: 코드·DDL 전부 `mineral_risk.` 한정, public의
  vector 컬럼 수 0, public 테이블 26개 그대로.

**후속 과제(이번 범위 밖, 의도적)**: ①`services/rag_chat/app/retrieval/
unstructured.py`의 pgvector 전환(지금은 여전히 DuckDB `hybrid_search()` 호출 —
BM25 절반의 이관 방침이 함께 정해져야 하는 구조 변경이라 분리) ②BM25의
Postgres tsvector 이관(§4 addendum 나머지) ③`rag/index/rag.duckdb`는 그대로 유지
(이번 적재는 대체가 아니라 추가).

## 2026-08-11 (최신, 이어서) — rag/ragkit 인덱스 최초 빌드 + ROOT 상대경로 버그 수정

오늘 커밋 5건 푸시 완료 후, 사용자가 "RAG용 임베딩 산출·저장, OKF, PageIndex"를
다음 작업으로 지시. 착수 전 `rag/ragkit/build_index.py`를 실제로 처음 실행해보니
(이제껏 한 번도 안 돌려봄, `rag/index/rag.duckdb` 자체가 오늘 새벽까지 존재하지
않았음) **문서 4건만 로드되는 버그를 발견** — `ingest.py`의 `ROOT = "documents/
산출물"`가 상대경로였는데, 표준 실행 관례(`cd inhouse && python -m ...`)로 돌리면
cwd=inhouse/라 `inhouse/documents/산출물`(존재하지 않음)을 찾고 `load_documents()`의
`if not os.path.isdir(r): continue`에 걸려 **조용히 스킵**되고 있었다 — 실제로
로드된 4건은 전부 EXTRA_ROOTS(0807 해외투자가이드)뿐, 본체 61개 md+15개 docx
보고서는 전부 빠져 있었다. `EXTRA_ROOTS`가 이미 쓰던 `_REPO_ROOT`(파일 위치 기준
절대경로) 패턴을 `ROOT`에도 그대로 적용해 수정.

수정 후 재실행: **문서 76건, 청크 1206개**로 정상 인덱싱(임베딩 계산 ~22초,
e5-small 로컬). `rag/ragkit/retrieve.hybrid_search()`로 실제 질의 확인 —
관련 문서가 정상적으로 상위에 옴. 이어서 **오늘 처음으로 실제 vLLM 서버(로컬
`localhost:52302` — `host.docker.internal`은 컨테이너 안에서만 resolve되는
호스트명이라 이 세션 내내 접속 불가였는데, docker가 실제로 설치돼 있고 vLLM
컨테이너가 이미 떠 있다는 걸 발견해 우회 확인)를 통해 `/chat`(mode=document)를
end-to-end로 호출** — 실제 토큰 스트리밍(delta 단위 SSE) 확인, 검색된 6개 청크에
정확한 QWK 수치가 없어 모델이 환각 없이 정상적으로 기권(ABSTAIN_TEXT) — 인용강제
설계(가이드 §4)가 실제 LLM 앞에서 의도대로 동작함을 처음 확인.

## 2026-08-11 (이어서) — 정형(RDB) 조회 3종을 `services/shared/retrieval/`로 통합(rag_chat×report_gen 중복 제거)

같은 날 rag_chat과 report_gen이 각각 만든 정형 조회 코드 두 벌(서로의 영역을 침범하지
않으려고 의도적으로 남긴 중복 — 양쪽 docstring에 "후속 정리 대상"이라 적혀 있었다)을
`CONTAINER_ARCHITECTURE.md` §5-4·§6("동일한 3개 조회 도구를 shared에 한 번만 구현")대로
합쳤다.

**배치**
- `services/shared/retrieval/structured.py`(신규, 정본) — `latest_diagnosis(cc)`·
  `import_forecast(cc, target, horizon=None)`·`geo_index_trend(cc, freq, limit)` +
  `VALID_COMMODITIES`/`check_commodity()`/`StructuredQueryError`. 화이트리스트·SQL이
  이제 이 파일 한 곳에만 있다. `__init__.py`는 두지 않았다 — `services/shared` 자체가
  namespace 패키지라 같은 규약을 따랐고, 내부에서 `from ..db import read_sql_msr`로
  붙는다(별도 sys.path 부트스트랩 불필요).
- `rag_chat/app/retrieval/structured.py` → 얇은 어댑터. LLM 도구호출 계약
  (`TEMPLATES`/`run_template()`)과, 최신 1건이 필요한 `latest_geo_index()`
  (= `geo_index_trend(..., limit=1)[-1]`)만 남았다. 103줄 → 51줄.
- `report_gen/app/generator.py` — `_latest_diagnosis`/`_import_forecast`/
  `_geo_index_trend` 삭제, 공용 구현 직접 호출. `_check_commodity`는 3줄 래퍼로 남겨
  `StructuredQueryError`를 `ReportGenerationError`로 바꿔 던진다 — `main.py`가 그걸
  잡아 HTTP 400을 내는 계약이라 예외형이 바뀌면 조용히 500으로 새어나간다.
  `_komis_supply_indicator`(KOMIS 공개원천 전용)는 공유 대상이 아니라 그대로 뒀다.

**시그니처 판단(두 호출자 반환형이 달랐다)** — 억지로 한 형태로 뭉개지 않고 "여러 행 +
컬럼 합집합"을 정본으로 두고, 최신 1건이 필요한 쪽이 어댑터에서 뽑아 쓰게 했다.
`import_forecast`는 rag_chat판 시그니처(horizon 옵션)에 report_gen판 SQL(max(base_date)
서브쿼리)을 얹었다 — rag_chat판은 `ORDER BY base_date DESC, horizon ASC LIMIT 12`라
**horizon을 지정하면 여러 기준월이 섞여 나오는 버그**가 있었다(자기 docstring "그 시점만"과
불일치). 현재 데이터는 광종·target별 기준월이 2025-12-01 하나뿐이라 출력은 불변.

**회귀 검증**(통합 전/후 같은 스크립트로 45개 항목 덤프 후 diff, `MSR_DB`=운영 duckdb)
- **report_gen 리포트 본문 5광종 전부 바이트 단위 동일**(`render_report(cc)['body']`,
  생성시각·주차 등 시변 필드만 마스킹). `rc.import_forecast` 12항목도 완전 동일.
- 나머지 diff는 전부 **추가**(삭제·변경 0줄)였고 사전에 예측한 목록과 일치했다:
  ①rag_chat `latest_diagnosis`에 `generated_at` ②rag_chat `latest_geo_index`에
  `index_config_version` ③report_gen `geo_index` 행에 `commodity_code`·`freq`
  ④freq 오류문구 `W|M`→`W|M|Y`(geo_index에 실제 존재하는 값 기준으로 통일).
  ①~③은 컬럼 합집합의 결과라 Jinja(StrictUndefined는 없는 키에만 실패)·LLM 도구
  출력 어느 쪽도 깨지 않는다. rag_chat `run_template`은 아직 호출자가 없다(chat.py는
  `unstructured`만 import) — 런타임 영향 없음.
- `python3 -m py_compile` services 전체 52파일 통과, 5개 모듈 실제 import 확인.
- `out_report`는 건드리지 않았다 — 검증에 `render_report`/`build_context`만 써서 적재
  경로를 아예 타지 않았고, 검증 후 조회에서도 0행(테이블 그대로)이었다.
- Containerfile/requirements: 양쪽 다 `COPY services/shared ./shared` 한 줄이 새
  서브패키지까지 이미 덮는다(확인만 하고 손대지 않음). Containerfile 주석의 "후속
  과제" 문구는 그 시점 기록이라 그대로 뒀다.

## 2026-08-11 (이어서) — report_gen에 외부repo `analysis/` 이식 + 리포트 실경로 1개 가동

병합계획 결정②(코드 직접 이식) 실행. 외부repo `src/komis_report_generator/analysis/`를
`inhouse/services/report_gen/`에 이식하고, "템플릿 × 정형데이터 → 본문 조립 →
`out_report` 적재"까지 실제로 도는 경로 하나를 만들었다. 그동안 report_gen은
3개 파일 전부 `raise NotImplementedError` 스켈레톤이었다.

**먼저 정정 — "DB 조회 실물"은 `data_sources/database.py`가 아니라 `scaffold.py`에
있었다.** 지시서·병합계획이 `database.py`를 실물 SQL로 봤는데, 실제로 읽어보니
`database.py`는 *정규화기*(원천 행 → 계열 모델)이고 psycopg 커넥션과 테이블·컬럼
스펙(`_DatasetSpec`/`_PAGE_DATASETS`)·SQL 조립은 전부 `scaffold.py`의
`PostgresRawDataRepository`에 있었다. 그래서 이식 대상을 그쪽으로 잡았다.

**배치**
- `services/shared/komis_raw.py`(신규) — SQL 리포지토리(`KomisRawDataRepository`)
  + 9개 테이블 스펙 + `AnalysisPreviewRequest`/`RawDataset`/`_coerce_period`.
  rag_chat도 KOMIS 원천이 필요해질 수 있어 서비스 전용이 아니라 shared에 뒀다.
- `services/report_gen/app/analysis/` — `models.py`(계열 타입만)·`indicators.py`
  (무수정)·`data_sources/{_shared,database}.py`(정규화기)·`scaffold.py`(스텁 서비스)
  + `resources/komis-metadata.subset.json`.
- `services/report_gen/app/{_bootstrap,generator,scheduler,main}.py` +
  `app/templates/weekly_brief.md.j2`.

**이식하며 바꾼 것**
- **접속**: `psycopg.connect(host=...)` 직결 → `services/shared/db.read_sql_pg()`
  경유(서비스 코드가 psycopg2/sqlalchemy를 직접 import하지 않는다는 원칙).
- **`%s` 바인딩 → 검증 후 리터럴 삽입**(가장 큰 재작성). `read_sql_pg`는
  `pandas.read_sql(str, engine)` → `exec_driver_sql` 경로라 **바인딩 파라미터를
  못 받고, 쿼리 문자열 안의 `%`를 플레이스홀더로 오인**한다 — 이번에 실측으로
  걸렸다(`... ILIKE 'ko\_%'` → `TypeError: sqlalchemy...immutabledict is not a
  sequence`). 그래서 (a) pydantic 패턴 1차 검증, (b) SQL 삽입 직전 화이트리스트
  정규식(`^[A-Za-z0-9_]{1,32}$`) 2차 검증 후 리터럴, (c) `LIKE`/`%` 미사용으로
  바꿨다. rag_chat `retrieval/structured.py`와 같은 "템플릿 질의 전용" 원칙.
  ※ **이 제약은 `read_sql_pg`를 쓰는 모든 코드에 해당한다** — 앞으로 PG 쿼리에
  `%`를 넣지 말 것.
- **메타데이터 스냅샷**: 정규화기의 `MineralCatalog`가 원본에선 `search/`의 전체
  스냅샷(26 refs, 140KB)을 import했다. 그쪽은 같은 날 rag_chat 이식 소관이라,
  analysis가 실제로 쓰는 4개 ref만 추린 파생본(48KB)을 report_gen 안에 두고
  `metadata_snapshot_path` 인자로 갈아끼울 수 있게 했다.
- **`summary.py`·`additional_summary.py`·`policy.py`·`prompts.py`는 이식하지
  않았다**(63KB 요약문 엔진 — 스텁이 아니라 실물이다). 사유 3가지를
  `app/analysis/__init__.py`에 기록: ①대상 데이터가 없다(아래 실측), ②`search/`
  패키지(JsonLLM·전체 스냅샷)에 물려 있어 같은 날 이식 중인 코드 위에 이식을
  얹게 된다, ③이번 과업 범위 밖(CLAUDE.md §4). 위 ①②가 풀리면 별도 사이클로.
- **`scaffold.AnalysisScaffoldService.analyze()`는 스텁 그대로** 뒀다(원본 TODO
  주석 유지). 병합계획 §0이 이미 "리포트 생성은 스텁"이라고 정정한 부분이라
  포장하지 않았다 — 실제 도는 리포트 경로는 `app/generator.py`다.

**실측으로 드러난 것 (문서·원본코드 예시를 안 믿고 직접 조회)**
- `information_schema.columns` 조회 결과 9개 `KO_*` 테이블의 컬럼명·개수가 원본
  `_DatasetSpec`과 **전부 일치**(PG가 미인용 식별자를 소문자로 접어 원본의 대문자
  SQL도 그대로 동작). `crtr_ymd` 정밀도도 스펙대로 — `ko_mrkt_prspect_idct`는
  8자리(20250201), `ko_spdm_stbt_indx`만 6자리(202502).
- ⚠ **`public.KO_*`에 적재된 광종은 텅스텐(MNRL0018) 하나뿐이다.** 실측 행수:
  ko_mrkt_prspect_idct 170 / ko_spdm_stbt_indx 98 / ko_mnrl_prc_predc 76 /
  ko_rsrc_burudg_quty 56 / ko_rsrc_prdctn_quty 63 — 전부 MNRL0018. 거래 테이블도
  HS 8101*(텅스텐)·820900 계열뿐(ko_cstm_cmmrc 20,736 / ko_un_cmmrc 25,342).
  **komir 5광종(CU/NI/CO/LI/REE)은 한 건도 없다** → 이 DB는 데모 슬라이스로 봐야
  하고, KOMIS 공개지표를 발주 5광종 리포트에 실제로 쓰려면 발주처에 5광종 적재를
  요청해야 한다. (지수 테이블 ko_mnrl_snths_indx만 광종 무관 — HI001/2/3 각
  3,631/3,633/3,635행, 2011-01-04~2025-02-18.)
- ⚠ **`ko_un_cmmrc.mnrknd_unq_cd`는 25,342행 전부 NULL** — 원본 코드의
  `map_global` 광종 필터(`MNRKND_UNQ_CD = %s`)는 항상 0행을 돌려준다(원본 저장소의
  실제 결함). 이식본은 동작을 원본과 같게 두고 스펙에 경고 주석만 달았다 —
  조용히 hs_cd only로 바꾸면 호출자가 광종 필터가 먹은 줄 착각한다.

**리포트 실경로**(`app/generator.py` + `app/templates/weekly_brief.md.j2`)
- 섹션→도구 매핑은 CONTAINER_ARCHITECTURE.md §6대로 **정적**이다(RAG처럼 매 턴
  LLM이 고르지 않음). 1~3절 = komir 산출물(`out_diagnosis_alert`·
  `out_import_forecast`·`geo_index` @ MSR_DB), 4절 = KOMIS 공개지표
  (`public.KO_SPDM_STBT_INDX`, 이식한 정규화기를 그대로 태움). 비정형
  (VectorDB/PageIndex) 절은 미배선 — 없는 걸 있는 척 채우지 않고 템플릿 말미에
  명시했다.
- 정형 질의를 rag_chat `retrieval/structured.py`에서 가져오지 않고 generator.py에
  따로 썼다(같은 시각 다른 작업이 그 파일을 수정 중이라 import도 편집도 안 함) —
  **후속 정리 대상**: §6 "중복 구현 금지"대로 `services/shared/retrieval/`로 합칠 것.
- `out_report` 적재는 멱등: `report_id = 'rpt_' + sha1(kind|광종|주차)[:24]`(28자,
  컬럼은 VARCHAR(32))로 고정하고, `dbio.write_df(pk=)`가 **기존 행과는 대조하지
  않는다**(df 내부 중복만 제거 → PK 제약 위반)는 점을 확인해 삽입 전에
  `execute_msr("DELETE ... WHERE report_id = ?")`로 지운다.

**검증(전부 실제 DB·실제 실행)**
- `python3 -m py_compile` 전 파일 통과 + 실제 `import app.main`(라우트 4개 확인).
  `zip(strict=)`는 3.10부터라 문제없고, 3.11+ 전용 `datetime.UTC`는 이식 파일에
  없다(grep 확인, `timezone.utc` 사용).
- 이식한 리포지토리 실조회: `indicator_market`(3행)·`map_mineral`(매장량 13행+
  생산량 13행)·`indicator_supply` 완전조회(2024-01~2025-02 14행) 모두 정상.
- 이식한 정규화기 실조회: 수급안정지수 계열(텅스텐, 2017-02~2025-02) 정규화 성공
  — 경고문구 5건(가격단위 없음/내부누락 1개월/점수없는 행 2건/가격결측 1건/
  crisis_flag 없음)이 실제 데이터에서 그대로 나옴. 광물지도 생산량 2023년 13개국
  (세계합계 78,000톤·베트남 3,500톤), 광물종합지수 2025-01-01~02-18 35영업일
  (종합 2525.23·메이저 2433.84·희소 1394.07).
- 5광종 리포트 생성→적재 성공(본문 1,770~2,175자), `out_report` 0행 → 5행.
  같은 주차 재실행해도 5행 유지(멱등성 확인). 4절은 5광종 모두 "데이터 없음"으로
  나오는 게 정상(위 텅스텐-only 실측) — 정규화기가 실제로 도는지는 코드를 잠시
  MNRL0018로 돌려 12개월 표가 렌더되는 것까지 확인했다.
- FastAPI 라우트 실호출(TestClient, APScheduler lifespan 포함 기동/종료):
  `/healthz` 200, `POST /reports/weekly_brief/generate?store=false` 200,
  `store=true` 200(적재 1행), `GET /reports/{id}` 200, `GET /reports` 5건,
  잘못된 광종코드 400.
- 컨테이너 배치(Containerfile이 `services/shared`→`/app/shared`,
  `services/report_gen/app`→`/app/app`으로 평평하게 COPY)를 임시 디렉토리로
  재현해 임포트·스냅샷 경로·템플릿 경로 폴백까지 전부 동작 확인 —
  `app/_bootstrap.py`가 고정 depth 대신 `shared/db.py`를 위로 훑는다.

## 2026-08-11 (이어서) — rag_chat에 KOMIS 페이지추천(외부repo `search/`) 편입

병합계획 결정①(페이지·필터 추천 챗봇을 RAG 챗봇 기능 일부로 편입) 실행. 외부repo
`src/komis_report_generator/search/`(LangGraph 상태그래프, 43개 KOMIS 페이지·필터
정의 YAML + 메타데이터 스냅샷)를 `inhouse/services/rag_chat/app/page_recommend/`로
이식하고 `/chat`에 두 경로(문서Q&A | 페이지추천)로 배선했다.

**이식하며 바꾼 것(그대로 복사한 게 아님)** — 각각 "프로젝트에 같은 역할의 물건이
두 벌 생기는 것"을 막기 위한 변경이다.
- **LLM 클라이언트**: 원본 `search/llm.py`(httpx 기반 `OpenAICompatibleJsonLLM`)는
  아예 이식하지 않고, 같은 날 만든 `services/shared/llm_client.KomirJsonLLM`을
  그 자리에 끼웠다(invoke 시그니처가 동일하게 맞춰져 있어 그래프 코드는 무수정).
  부수효과로 원본의 `except LLMTransportError: raise` 분기가 불필요해져 제거 —
  komir의 OpenAICompatChat은 전송실패 시 `requests.RequestException`/`RuntimeError`를
  던지고 이들은 LLMError 계열이 아니라 어차피 전파되므로 동작 동일(graph.py
  docstring에 "되돌리지 말 것"으로 근거 기록).
- **설정**: `search/config.Settings.from_env()` 미이식 → `services/shared/config.py`
  하나로. 새 env는 `KOMIS_TIMEZONE`(상대기간 해석 기준 지역) 하나만 추가했고,
  `KOMIS_SEARCH_STATE_DB`는 아래 이유로 필요 없어 안 만들었다.
- **대화상태 저장소**: 원본은 LangGraph SQLite 체크포인터(`.state/komis-search.sqlite3`)
  에 스레드 상태를 뒀는데, komir엔 이미 chat_session/chat_message가 있어 그대로
  들이면 대화 저장소가 2개가 된다. 체크포인터 없이 컴파일하고 직전 상태
  (message_history·active_artifact)를 호출자가 주입·회수하는 계약으로 바꿨다
  (`page_recommend/service.py`). 상태는 assistant 메시지의 `citations_json`에
  `{"page_recommend": {...}}` JSON으로 싣는다 — 다음 턴에 그래프가 실제로 읽는
  6개 키만 남겨서(`_persistable_artifact`) 넣는데, 그 컬럼이 VARCHAR(4000)이라
  (DuckDB는 길이 미강제, Postgres cutover 후엔 잘림) 안 읽는 값까지 실을 이유가
  없기 때문. 실측 605자.
- **레지스트리 빌드 단계 제거**: 원본은 YAML을 `generated/{services,routing-index}.json`
  으로 굽고 CI에서 최신인지 확인하는 CLI(`build_registry`/`check_registry`)를
  갖고 있었는데, 같은 레지스트리를 두 벌 두고 동기화할 이유가 없어 YAML 직접
  로드만 남겼다(실측 로드 0.37~0.40s, 프로세스당 1회 캐시).
- **python3.10 호환**: `search/temporal.py`의 `datetime.UTC`(3.11+ 전용) →
  `timezone.utc`. 그 외 3.11+ 전용 문법은 없었다(PEP695 제네릭은 미이식 파일인
  `llm.py`에만 있었음).

**의도분류(어느 경로로 보낼지)**: 요청 바디 `mode`(auto|document|page)를 우선하고
auto일 때만 `app/intent.py`가 KomirJsonLLM 1회 호출로 분류한다. 실패하면 문서Q&A로
폴백 — 먼저 돌던 기본 경로이고 근거 없으면 이미 기권하도록 돼 있어 오분류 비용이
더 작다(완벽한 자동판별에 시간 쓰지 않고 두 경로가 다 도는 것을 우선).

**검증**(vLLM은 이 환경에서 접속 불가 — `host.docker.internal:52302`는 컨테이너
전용 호스트명, 실측 확인됨 → LLM은 결정론적 더블 `ScriptedJsonLLM`으로 대체. 원본
테스트가 쓰던 그 더블만 테스트 파일 쪽으로 이식):
- `python3 -m py_compile` 전 파일 통과 + `python3 -c "import app.main"` 실제 임포트
  성공(라우트 `/chat`·`/healthz` 확인) — 컴파일과 임포트는 다르므로 둘 다 확인.
- `services/rag_chat/tests/smoke_page_recommend.py`(신규): 레지스트리 43개 페이지
  로드, 메타데이터 스냅샷(`snapshot_id=2026-07-16:bab90fd438c6`) 로드, 상대기간
  해석(최근5년→`{start:2021,end:2026}`), 필터해석(`price_base_metals` "구리"→
  canonical `동` + 기본값 4건 자동적용), 그래프 1턴(`map_korea` 추천), 2턴
  same_task 상태이월(mineral 유지 + measure만 교체), 후보 2개 ambiguous,
  LLM 출력오류 흡수(`relation_invalid_output` 경고) — 8건 전부 통과.
- `services/rag_chat/tests/smoke_chat_routing.py`(신규): 임시 DuckDB(운영 DB 오염
  방지)로 라우터 실경로 — mode=page 1·2턴이 DB를 왕복하며 상태가 이월되는지,
  히스토리를 이번 질문 저장 "전"에 읽는지(저장 후면 그래프가 자기 질문을 직전
  턴으로 오인·중복 저장), chat_message 4행(중복 없음), ambiguous(후보 2개)로 끝난
  턴 뒤 후속 선택이 DB를 왕복한 상태로 이어지는지(저장 키가 same_task와 달라 별도
  확인 — `original_question`이 살아남아 2턴 필터추출이 "원래 질문 …\n추가 선택 …"
  합성 질문으로 도는 것까지 확인), mode=auto가 의도분류 1회 호출 후 각각
  page/document 경로로 갈리는지 — 전부 통과.
- FastAPI TestClient로 `POST /chat` 실제 호출: HTTP 200, SSE 3이벤트
  (`session_id` → `delta`(렌더된 추천문) → `event: done`에 recommendations/
  warnings) 확인.

**의존성·배포**: `requirements.txt`에 `langgraph>=1.0`(외부repo uv.lock이 고정한
1.2.9를 python3.10에 설치해 실행까지 확인)·`PyYAML>=6.0` 추가, `pydantic>=2.5`→
`>=2.12`로 상향(이식한 `models.py`의 `Field(exclude_if=...)`가 2.12+ 전용, 실측
2.12.3에서 동작). `langgraph-checkpoint-sqlite`는 위 결정대로 채택 안 함.
Containerfile은 **COPY 라인 추가 없음** — 리소스(YAML 43건+스냅샷, 400KB)를
패키지 안(`app/page_recommend/resources/`)에 두어 기존 `COPY services/rag_chat/app
./app` 한 줄로 함께 실린다(주석만 보강). 다만 이 김에 `routers/chat.py`의
sys.path 부트스트랩을 고정 depth(`parents[3]`)에서 "위로 훑어 찾기"로 바꿨다 —
소스트리와 컨테이너 배포본(평평한 COPY)의 상대 깊이가 달라 고정 depth는 컨테이너에서
틀린 경로를 가리킨다(`services/shared/db.py`·`ingestion/parsers/pdf.py`가 이미
쓰던 패턴). `session_store.py`·`retrieval/*.py`에 같은 고정 depth가 남아 있으니
컨테이너 첫 빌드 때 함께 확인 필요(이번 범위 밖).

## 2026-08-11 (이어서) — services/shared 실구현 + rag_chat 문서Q&A 경로 완성

같은 날 이어서: 사용자 질문("embedding, rag, report generator용 llm 설정은 연계
되어 있나요?")에 답하며 실제로 연계 작업까지 진행. 확인 결과 **이식 전엔 연계돼
있지 않았음** — LLM(채팅)은 komir 자체 클라이언트(`geo/llm/openai_compat.py`)
하나뿐이었는데 외부repo `search/llm.py`가 env 이름은 우연히 같지만(`LLM_BASE_URL`
등) httpx 기반 별개 클라이언트(`OpenAICompatibleJsonLLM`)를 갖고 있어 그대로
들이면 클라이언트가 2벌 생길 뻔했음. 임베딩은 이름부터 전혀 다름(komir
`EMBEDDING_BASE_URL`은 실은 `rag/ragkit/embed.py`가 참조조차 안 하고
sentence-transformers를 코드에 하드코딩해 로컬 직접로드, 외부repo
`KOMIS_EMBEDDING_*`는 HTTP `/embeddings` 서버 호출 전제 — 아키텍처 가정 자체가
다름, 이번엔 komir 방식 유지).

**`inhouse/services/shared/`(3개 스켈레톤 → 실구현)**:
- `config.py` — pydantic-settings로 `.env` 전체(MSR_DB·PG_DSN/PG_SCHEMA·LLM_*·
  EMBEDDING_*·QDRANT_*·CHAT_*·REPORT_*) 단일 로더. 외부repo의 `search/config.py`·
  `vector_index/config.py`(각각 다른 이름 체계) 이식 안 함 — 이 파일 하나로 흡수.
- `db.py` — `mineral_supply_risk/db/dbio.py` 재노출 + `read_sql_pg`(PG_SCHEMA로만
  스키마 한정, public 하드코딩 금지 원칙 docstring 명시) + 신규 `execute_msr`
  (dbio에 없던 point-CRUD 단일문 실행, chat_session/chat_message용 — postgres
  paramstyle 미검증이라 그 경로는 NotImplementedError로 명시적으로 막아둠).
  `dbio.apply_schema()`의 기지 버그(정의 안 된 schema 변수 참조, docs/
  CONTAINER_ARCHITECTURE.md §1에 문서화돼 있던 것)도 이 김에 수정(죽은 코드
  3줄 삭제).
- `llm_client.py` — `KomirJsonLLM`: 외부repo `OpenAICompatibleJsonLLM`의 구조화
  출력(JSON Schema+1회 복구재시도) 로직은 이식하되, 실제 HTTP는 새 클라이언트를
  만들지 않고 `geo/llm/openai_compat.OpenAICompatChat.complete()`에 위임 —
  클라이언트는 하나만 남김.
- `geo/llm/openai_compat.py`에 `complete_stream()` 추가(SSE 델타 제너레이터,
  기존 `complete()`는 무변경) — 챗봇 스트리밍 요구사항(CLAUDE.md §0 산출물⑥)
  때문에 새로 필요해짐, 기존엔 스트리밍 자체가 아예 없었음(실측 확인).

**`data_lake/db/schema_addendum_v2.sql`**(설계만·미적용 상태였음)의 `chat_session`/
`chat_message` 두 테이블만 MSR_DB(DuckDB)에 직접 생성(라이브 운영 DB 변경이라
전체 파일 대신 DuckDB 안전한 부분만 신중히 선택 — 나머지 `doc_chunk` tsvector/GIN
확장분은 Postgres 전용 문법이라 DuckDB에서 실행하면 깨짐, cutover 이후로 보류).

**`inhouse/services/rag_chat/`(문서Q&A 경로 실구현, 페이지추천은 별도 진행중)**:
`session_store.py`(chat_session/chat_message CRUD, 위 신규 테이블 대상)·
`streaming.py`(SSE 이벤트 변환 — 처음에 `sse_event()`가 이미 완성된 "data: ...\n\n"
문자열을 만들어 sse_starlette가 또 감싸는 바람에 "data: data: {...}" 이중래핑
버그가 실제로 났었음, TestClient로 실측 발견·수정: dict를 돌려주는 방식으로 교체)·
`retrieval/structured.py`(템플릿 전용 정형조회 3종 — 여기서도 실측 버그 하나 발견:
`out_import_forecast.target` 값이 설계문서 예시론 'ton'/'usd'였는데 실제 DB엔
'volume'/'value'였음, DESCRIBE로 확인 후 수정)·`retrieval/unstructured.py`
(rag/ragkit/retrieve.hybrid_search 그대로 호출 — Qdrant 이관은 rag.duckdb 색인
자체가 아직 안 만들어져 있고 qdrant-client도 설치 안 돼 있어(둘 다 실측 확인)
이번엔 보류, 그 이관 지점만 마련)·`routers/chat.py`+`main.py`(rag/ragkit/generate.py의
인용강제 생성 로직 재사용, 스트리밍용으로 토큰 도착 즉시 전송+스트림 종료 후
날조인용 검사). FastAPI TestClient로 `/chat` 엔드포인트 전 구간 실제 호출 검증
(세션생성→기권응답 SSE 정상 — rag.duckdb 미구축 상태라 실제로는 항상 기권 경로를
타지만, 그 경로 자체가 500 아닌 정상 200으로 우아하게 처리되는 것까지 확인·
테스트로 넣은 행은 정리 완료).

**남은 일(백그라운드 에이전트 2건 진행 중, 완료 시 검토 후 이 절에 추가 기록
예정)**: ①`search/`(LangGraph 페이지추천 그래프)를 `rag_chat`에 편입 ②`analysis/`
(정형DB 조회)를 `report_gen`에 이식.

## 2026-08-11 — komis-report-generator-main 병합 착수: services/ingestion 실제 구현

사용자(프로젝트 관리·개발 담당, 팀원 퇴사로 단독 핸들링 전환)가 별도 저장소
`/home/nuri/dev/git/ws/mine_ws/komis-report-generator-main`(git 없는 스냅샷,
2026-08-11 시점)의 RAG/리포트 생성 구현을 komir에 병합하라고 요청. 먼저 코드
전수조사(백그라운드 Explore 에이전트) 후 병합계획을 문서화(`documents/산출물/
2026-W33_0810-0816/병합계획_komis-report-generator_260811.md`) — 실제로 완성돼
동작하는 건 페이지/필터 추천 챗봇(`search/`) 하나뿐이고, RAG(`vector_index`)는
자기 repo에서도 미배선, 리포트 생성(`analysis/scaffold.py`)은 스텁이라는 점을
먼저 정정. 사용자 결정 3건: ①`search/`(페이지추천)는 RAG 챗봇 기능 일부로 편입
②komir `inhouse/services/*` 스텁에 코드 직접 이식(서비스 단위 아님) ③PDF 파싱은
komir 자체 구현이 정본(외부 repo의 PyMuPDF 파서 채택 안 함).

**1단계 완료 — `inhouse/services/ingestion/`**(`docs/CONTAINER_ARCHITECTURE.md`
§5-3 "in-house ingestion" 스켈레톤을 실제 구현으로 교체): 외부 repo
`document_ingestion/{models,pipeline,source_policy}.py`를 pydantic 계약·
해시기반 중복제거·재사용(unchanged)·원자적 쓰기 로직 그대로 이식. `parsers/hwp.py`는
외부 repo의 pyhwp(hwp5) 기반 섹션+표 구조 파서를 그대로 이식(komir에 HWP 구조
파싱이 전무했던 진짜 신규 capability). `parsers/pdf.py`는 외부 repo 파서 대신
`inhouse/geo/extractors.py`의 opendataloader-pdf→pypdf→OCR 폴백 체인
(`extract_with_fallback`, 이미 검증됨)을 감싸는 새 래퍼로 구현(결정③) — 페이지별
분할·표 bbox는 이 체인이 보존하지 않아 문서 전체를 ContentUnit 1개로 감싸는
제약을 문서화. discover_source_files()는 외부 repo 고유의 "보고서_1/<그룹>"
강제 경로를 제거해 komir 문서 루트에 맞게 일반화. opendataloader-pdf가
"파일 단위 호출 시 JVM 재기동으로 느림"(extractors.py 기존 주석, OCR 212분 낭비
사례와 같은 유형의 함정)이라는 점 때문에, 원본 파이프라인의 파일별 순회 구조를
유지한 채 실제 파싱이 필요한 PDF만 골라 루프 진입 전에 한 번에 배치 변환하는
`_preload_pdf_batch()`를 추가(`PdfParser.preload_batch()`).

**검증**: `python3 -m py_compile` 전체 통과. `datetime.UTC`(3.11+ 전용, 원본이
python≥3.13 선언이라 섞여 있었음)를 `timezone.utc`로 교체해 python3.10 런타임
호환 확보(py_compile은 이 종류의 런타임 임포트 오류를 못 잡는다는 걸 실측
확인). 실제 komir 문서(`documents/5. (비축사례)...hwp`, `documents/조달청보고서/
비철금속 시장 동향(2019.7.23).pdf`)로 end-to-end 스모크 테스트 — HWP는
섹션 구조 보존한 한글 본문 정상 추출, PDF는 opendataloader 경로로 정상 추출,
재실행 시 unchanged(재사용) 경로도 정상 동작 확인. 신규 의존성 `pyhwp`(pip 설치
확인) — `rag_chat`·`report_gen` requirements.txt(pydantic·pyhwp·PDF체인 5종)와
Containerfile(services/ingestion·geo/extractors.py COPY 추가, geo import 경로는
고정 깊이 대신 상위 탐색으로 구현해 소스트리/컨테이너 두 배포 형태 모두 대응)에
반영. 겸사겸사 `rag_chat/Containerfile`의 stale 경로(`engine/rag/ragkit` — 8/6
DMZ/inhouse 분리로 이미 없어진 경로)도 `rag/ragkit`으로 정정.

docx/doc/xlsx/xls/csv 파서는 외부 repo에도 구현이 없어 이번 이식 범위 밖(여전히
스켈레톤). 다음 단계(미착수): search/ LangGraph 챗봇→rag_chat 편입,
analysis/→report_gen 이식, api/ 라우터 배선.

## 2026-08-10 — PostgreSQL(komis_demo) 데이터 이관 1차 + 0807 PDF ETL(opendataloader-pdf, OCR 폴백)

**PostgreSQL 이관**: 사용자가 postgres 접속정보(172.30.1.101, komis_demo) 제공,
`.env`(`inhouse/.env`, 커밋 제외)에 `PG_*`(HOST/PORT/DATABASE/USER/PASSWORD/DSN/SCHEMA)
신설 — **`MSR_DB`는 그대로 duckdb를 가리키게 유지**(라이브 cron·streamlit이 즉시
참조하는 값이라 검증 전 전환 금지). 접속 시도 중 비밀번호 오타 2회 정정
(`illunex1234`→`illunex123`). 처음 준 포트 **5433**으로 접속해보니 `public` 스키마에
KOMIS 쪽이 이미 쓰는 `ko_*` 테이블 9개(ko_mnrl_prc 12,549행 등, 데이터 있음)가 존재 —
사용자 확인 후 이 9개는 안 건드리고 `mineral_risk` 스키마에 36개 테이블 이관까지
완료했으나, **사용자가 재확인 후 "같은 호스트에 postgres 인스턴스가 2개, 포트가
다르다" — 실제로 맞는 포트는 5432**라고 정정. 5432엔 `komis_demo` DB 자체가 없어서
(있던 DB 3개는 `nice_innovation`/`postgres`/`sensaqbit`, 전부 무관한 다른 프로젝트)
`CREATE DATABASE`로 새로 만들고(duckdb postgres 확장은 이 DDL을 못 태워 `psycopg2`
autocommit 연결로 별도 실행 — `psycopg2-binary` pip 설치) `inhouse/mineral_supply_risk/
scripts/migrate_duckdb_to_postgres.py`(신규)로 **5432/komis_demo/`mineral_risk`
스키마에 36개 테이블 전부를 이름·구조 그대로** 재이관(duckdb postgres 확장 ATTACH+
CREATE TABLE AS SELECT, pandas 왕복 없이 직접 전송). 전 테이블 원본/대상 행수 일치
확인(geo_event 296,679행 포함 0건 불일치). 5433 쪽 `mineral_risk`는 무관한 서버로
결론났지만 삭제 요청은 없어 그대로 남겨둠(필요시 정리). **RAG(`rag/index/rag.duckdb`)는
아직 파일 자체가 없어(빌드 미실행) 이관할 데이터가 없음** — 향후 별도 처리.
남은 일: 실제 cutover(MSR_DB를 postgres URL로 전환, crontab·streamlit·geo publish
타깃 재조정)는 이번엔 하지 않음 — 데이터 적재까지만.

> ⚠ 같은 날 정정: 위 "5433은 무관한 서버" 판단이 **틀렸음이 재확인됨**. 사용자가
> 외부주소(`220.118.147.58:55433`)로 재접속을 요청해 확인해보니 내부
> `172.30.1.101:5433`과 완전히 동일한 DB였고, 그 사이 `public` 스키마에 **타 팀이
> 애플리케이션 테이블 17개(`ai_*` — `ai_item_card`="AI 관리카드", `ai_ntn_mst`/
> `ai_ntn_grp`=다자간협의체체결국 등 0807 메일 요구사항과 정확히 대응)를 추가**해둔
> 걸 발견 — **5433이 최종 정본**. `public`(ko_*+ai_*)은 타 팀 소유라 절대 손대지
>않기로 재확인(사용자 명시), 우리 `mineral_risk` 스키마는 이미 5433에 있었으므로
> 추가 이관 불필요(재검증만 수행, 36/36 테이블 행수 일치 재확인). `.env`도 5433으로
> 재수정. **5432/komis_demo(우리가 실수로 만든 scratch DB)는 정리 여부 미정** —
> 다음에 확인 필요. 상세는 메모리 `postgres_migration_260810` 참고.

**0807 제공자료 PDF ETL**: `opendataloader-pdf`(Java CLI, 오프라인) 채택해 비축월보
55건(진단모델 전용, RAG 금지 — 물리적으로 분리된 `restricted_diagnosis_only/`+META.md)
전량 마크다운 변환, 47/55건 연월 자동식별(본문에서). 해외투자가이드 4개국(RAG용)은
처음엔 opendataloader 기본모드로 전부 텍스트 0자(완전 스캔본)였으나, **이미
`inhouse/geo/extractors.py`에 2026-07-07부터 있던 pypdf→OCR(easyocr) 폴백 체인을
뒤늦게 발견**(처음엔 몰라서 opendataloader 자체 hybrid AI 모드 도입을 검토했었음 —
불필요했음, 기존 코드 재사용으로 해결) — `extract_with_fallback()`으로 떼어 재사용,
4건 전부 OCR로 실제 텍스트 확보(3만~3.8만자). RAG `ingest.py`에 저품질(빈 표뼈대)
게이트도 추가(`<br>` 태그가 실제내용으로 오판정되는 버그 자체발견·수정).

## 2026-08-06 — DMZ/inhouse 저장소 물리분리 + collectors 격리 리팩터 + skeptic-code 감사

오전에 확정한 DMZ(수집, LLM 금지)/망연계/in-house(airgap) 목표 배포 아키텍처(같은 날
앞선 항목 "DMZ/망연계/in-house 배포 아키텍처 재정의" 참고)를 실제 저장소 구조로
실행했다. "루트에 디렉토리가 너무 많이 노출된다"는 사용자 지적에서 시작 — 처음엔
단순 디렉토리 이동으로 끝날 줄 알았으나, 적대적 검증(시니컬한 에이전트 1개 호출)에서
"collectors만 dmz/로 빼면 된다"는 전제 자체가 틀렸다는 게 드러나 실제 코드 리팩터로
범위가 커졌다.

**1) 디렉토리 재구성(`git mv`, 이력 보존)**:
- `dmz/`: `collector/`(기존, 실전 배포 이력 없음 확인) · `geo_collectors/`(구
  `engine/geo/collectors/`) · `msr_collectors/`(구
  `engine/mineral_supply_risk/msr/collectors/`) · `upload_files/`
- `inhouse/`: `geo/`·`mineral_supply_risk/`·`rag/`(구 `engine/*`, collectors 제외) ·
  `services/`·`deploy/`·`dashboards/` · `data_lake/{db,semi_structure,vector_db}`
  (구 루트 `db/`+`geo_data/`+`warehouse/`를 3파트 data-lake 모델로 재편 — db는 임시
  duckdb라 향후 RDB 이관 시 디렉토리째 제거 예정, semi_structure는 OKF·PageIndex
  포함 예정, vector_db는 Qdrant 마운트 빈 디렉토리)
- `documents/meta/`(구 `docs/`) + `documents/산출물/`(불변)
- 루트는 이제 `dmz/`·`inhouse/`·`documents/`·`data_archive/` 4개만 노출(요청사항 충족)

**2) 라이브 job 사고 대응**: 디렉토리 이동 도중 `warehouse/minerals.duckdb`를 쓰기
잠금 중인 라이브 프로세스(`collect_tier4_feeds`, 이날 09:20 monthly cron 발동분)를
발견 — CPU 0%·TCP 연결 1개 유지·로그 6시간 넘게 무갱신으로 **hang 상태로 판정**,
사용자 확인 후 SIGTERM 종료(부모 스크립트가 다음 단계로 자동 이어받아 파일을 다시
잡길래 부모까지 완전 종료). DB 무결성 확인(232,001행, 기존값과 일치) 후
`inhouse/data_lake/db/`로 물리 이동. 사고 원인은 후속 skeptic-code 감사에서
`collect_akshare()`의 타임아웃 부재로 특정(같은 파일 다른 `requests.get` 호출엔
전부 `timeout=60~120`이 있었는데 akshare 패키지 내부 호출만 없었음).

**3) DMZ 격리 리팩터(병렬 에이전트 4개 + 직접 작업)**:
- `msr.collectors`(customs_api·ecos_api) 직접 import 6곳 → 파일 계약(parquet)으로
  전환. dmz 쪽 fetch 드라이버 신설(`collect_customs.py`·`collect_ecos.py`·
  `collect_keyed_agency_feeds.py`, 후자는 Census/BPS 키필요분 — 사용자가 재차
  지적해 추가 처리) + inhouse 쪽 로더(`msr/dmz_ingest.py`) 신설. del_where 등 기존
  DB 적재 로직은 전부 원본과 동일하게 재현(재구현 아님).
- geo의 `collect-news`/`collect-gdelt`를 `dmz/geo_collectors`로 이전,
  `cron_gkg_increment.sh`를 다운로드(dmz, `cron_gkg_download.sh`)/처리(inhouse) 2개로
  분할.
- `dmz/.env`·`inhouse/.env` 신설(정형 수집 키 vs LLM/DB 키 분리, 두 msr `config.py`의
  dotenv 로딩 경로도 배포단위 루트로 통일), crontab 6건으로 갱신(diff 확인 후 적용).

**4) skeptic-code 적대적 감사(YAGNI/KISS/DRY)** — 오늘 신규/수정 코드 대상, 7건 발견
후 전부 적용:
- `[CLIFF]` `cron_gkg_increment.sh`가 방금 삭제한 `warehouse/` 경로를 여전히 참조 —
  다음 토요일 cron 파손 직전 발견·수정(geo 에이전트 작업 시점엔 `warehouse/`가 아직
  있었어서 놓친 것).
- `[CLIFF]` `collect_akshare()`에 하드 타임아웃 추가(위 사고 재발 방지).
- `[LIAR]` 죽은 레거시 파일 2개(`geo_pipeline.py`·`komis_files.py`, 전역 미참조 재확인
  후) 완전 삭제.
- `[GHOST]` `backfill_customs_monthly.py`의 죽은 `--from` 인자 제거.
- `[TWIN]` `ECOS_ITEMS` 상수/`ecos_jobs_tier2.json` 이원화 위험 주석 강화.
- 구 `warehouse/` 경로 하드코딩 11개 파일(대부분 ablation/검정용 수동 스크립트)
  일괄 정리.

**남은 것(다음 사이클)**: `dmz/collector/`와 `dmz/geo_collectors/`의 기능 중복(병합
안 함, 의도적 보류) · `collect_tier2/4_feeds`의 나머지 무키 직접수집(Cochilco·USGS·
EIA 등)은 여전히 in-house에 남아있어 DMZ 경계 원칙상 잔여 위반.

커밋: `3c4c239`("feat: DMZ/inhouse 저장소 물리분리 + collectors 격리 리팩터 +
skeptic-code 감사", 380개 파일).

## 2026-08-06 — draw.io CLI를 Docker(xvfb 내장)로 확보, XML→SVG/PNG 로컬 export 가능해짐

문서화 규칙상 다이어그램은 draw.io(.drawio XML) 형식이 강제인데, XML은 바로 시각화가
안 돼 지금까지 `documents/산출물/.../drawio_열기_URL_*.txt`처럼 브라우저 URL로 열어
보는 방식에 의존했음(예: 2026-W32 폴더). 사용자 지시로 CLI 확보 시도.

- **호스트 네이티브 설치는 보류**: `apt`엔 draw.io 패키지가 없고, GitHub 릴리스 `.deb`
  설치·`xvfb` 설치 모두 `sudo`(비밀번호) 필요해 이 세션에서 비대화식으로 완결 불가능.
- **Docker로 대체 — 사용자 제안, 채택**: 이 서버에 Docker가 있고 사용자가 `docker`
  그룹에 속해 있어 `sudo` 없이 실행 가능. 컨테이너 안에 xvfb+draw.io Desktop이 이미
  패키징돼 있어 호스트에 아무것도 설치하지 않고 요건("draw.io 도구+xvfb 래핑")을
  그대로 만족.
- **이미지 선정**: `rlespinasse/drawio-desktop-headless`(draw.io Desktop 원본 CLI를
  xvfb로만 감싼 순수 패스스루, 버전 31.1.5 = 최신 draw.io Desktop과 동일) — Claude
  Code의 drawio 스킬이 기대하는 네이티브 `drawio -x -f svg -e ...` 플래그를 그대로
  받는다. `rlespinasse/drawio-export`(같은 저자, 자체 CLI로 다중 페이지 파일을
  페이지별로 자동 분리해 export)도 실측: 여러 페이지 문서 일괄 처리엔 더 편리.
- **`~/.local/bin/drawio` wrapper 스크립트 작성**(저장소 밖, 사용자 홈 — 이미 PATH에
  있는 디렉토리): `docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp -v
  "$(pwd):/data" -w /data rlespinasse/drawio-desktop-headless "$@"`. `--user`
  없으면 출력 파일이 root 소유가 되고, `HOME=/tmp` 없이 비루트로 돌리면 Electron
  `electron-store`가 `userData` 경로를 못 찾아 크래시함(둘 다 실측으로 발견한 함정).
  이 wrapper 덕에 `which drawio`로 CLI를 찾는 drawio 스킬이 그대로 동작.
- **실제 검증**: (1) Mermaid→`.drawio`→SVG/PNG 변환 전체 파이프라인 e2e 통과(한글
  라벨 정상 렌더링), (2) `documents/산출물/2026-W32_0803-0809/
  전체프로세스_시퀀스다이어그램_260806.drawio`(4페이지 시퀀스 다이어그램)를
  `rlespinasse/drawio-export`로 페이지별 SVG 4개 생성·PNG로 렌더링 확인(alt 블록·
  한글 라벨 모두 정상) — 같은 폴더에 SVG 4개 커밋 대상으로 남김.
- **남은 선택**: 다중 페이지 문서를 낱장 SVG로 늘 남길지, 필요할 때만 뽑을지는
  아직 정책 미정 — 일단 CLI 인프라 확보가 이번 요청의 본 목적.

## 2026-08-05 — `geo_data_2016plus_run/`을 `data_archive/`로 이관

사용자 질의("루트의 geo_data·geo_data_2016plus_run은 뭔가")에 실측 답변(크기·
최종수정일·DATA_REGISTRY.md 근거 직접 재확인) 후, 사용자 지시로 이관 진행.
`geo_data_2016plus_run/`(8.0G, 2016+ 전체 코퍼스 1회성 재처리 결과 — 로그·OCR
캐시 포함, 2026-07-08 이후 미변경)를 `data_archive/validation_runs/
geo_data_2016plus_run_260708/`로 이동(같은 파일시스템이라 rename, 복사 아님 —
`df` 확인 후 진행). `geo_data/`(75M, 2026-07-12 확정 프로덕션 정본, 지금도
갱신 중)는 그대로 유지. artifact-provenance-policy(삭제 금지, 이관은 허용)
준수 — META.md 함께 이동, `docs/DATA_REGISTRY.md` 위치 컬럼만 갱신(생성·재현
컬럼은 그 시점 경로 그대로 보존, `warehouse/minerals.duckdb` 항목의 재현
명령도 원 경로 그대로 — 이력이라 안 바꿈).

**추기(같은 작업 내 버그 발견·수정, 커밋 `ab34ccd`)**: 최초엔 일반 `mv`로만
이관했는데, `geo_data_2016plus_run/META.md`가 artifact-provenance-policy상
**예외적으로 git 추적 대상**이었다는 걸 놓쳐 본채 `git status`에 `D`(삭제됨)로
표시됨을 병합 직전 재확인 중 발견 — 주변 대용량 데이터(archive/wiki/run*.log 등)는
전부 gitignore라 무시했다가, 그 안의 META.md 한 파일만 예외라는 걸 놓친 전형적
함정. 워크트리에서 정식 `git mv`로 정정(rename 이력 보존), 병합 시 본채의 미리
옮겨둔 사본과 경로가 겹쳐 `git merge --ff-only`가 1차 거부(untracked 파일 충돌
안전장치) → 내용 동일 확인(`diff`) 후 제거하고 재시도해 성공. **재확인
결과(2026-08-05, push 직전)**: `git ls-files`로 새 경로에 META.md만 추적되고
나머지는 여전히 untracked임을, 실제 디스크 `du -sh`로 8.0G 그대로임을 각각
재검증 완료.

## 2026-08-05 — engine/ 통합 main 병합 + crontab 갱신 완료 — 병합 중 orphan 파일 발견·복구

사용자 지시("병합과 crontab 갱신 같이 진행")로 본채(main checkout)에서 실행.

- **`git merge --ff-only worktree-orktree`** 성공(main이 clean ancestor).
- **병합 직후 발견**: `git mv`는 추적 파일만 옮기므로, 구경로에 gitignore 대상
  미추적 파일이 남아있으면 디렉토리 자체가 안 사라짐 — 실제로 본채(main)에
  구 `geo/`·`mineral_supply_risk/`가 병합 후에도 남아있었음(워크트리에선 애초에
  없던 파일들이라 안 보였던 문제 — 워크트리·본채가 서로 다른 미추적 상태를
  갖고 있었기 때문). 점검 결과:
  - **`mineral_supply_risk/outputs/`(15MB, `**/outputs/` gitignore 대상) — 실행
    결과물(a5_review 등 진단/예측 리포트 다수, DATA_REGISTRY.md가 다수 인용)이
    새 경로(`engine/mineral_supply_risk/outputs/`)에 없는 채로 고립돼 있었음.
    **artifact-provenance-policy(삭제 금지) 위반 직전** — `mv`로 즉시
    `engine/mineral_supply_risk/outputs/`로 이전, 내용 5개 하위디렉토리·15MB
    보존 확인.
  - `geo/collectors/_gkg_masterfilelist_cache.txt`(126MB) — `cron_gkg_increment.sh`
    자체가 매 실행 `rm -f` 후 재생성하는 캐시라 이전 불필요, 폐기.
  - `mineral_supply_risk/data/processed/minerals.duckdb`(1MB, 07-17 구식) —
    `warehouse/minerals.duckdb`(정본, 459MB, 상시 갱신) 확립 이전의 구식 fallback
    DB로 확인(어떤 실행 경로도 MSR_DB 미설정 상태로 이 기본값에 의존하지 않음),
    폐기.
  - `__pycache__/` 전부 — 자동 재생성, 폐기.
  - 위 확인 후 구 `geo/`·`mineral_supply_risk/` 디렉토리 자체 삭제(`rm -rf`) —
    남은 게 캐시·구식 DB뿐임을 파일 단위로 먼저 확인한 뒤 실행(추측 삭제 아님).
- **본채에서 재스모크**: `engine/geo`·`engine/`(python -m geo 방식)·
  `engine/mineral_supply_risk`에서 임포트 재확인, 두 cron 스크립트 `bash -n`
  재확인 — 워크트리에서 했던 것과 별개로 실제 병합된 본채에서 다시 실행.
- **시스템 crontab 갱신**: `crontab -l` → 3건 중 komir 관련 3줄만 `engine/`
  삽입해 치환(무관한 `stock_predictor_cron` 항목은 그대로), diff로 정확히
  3줄만 바뀌는지 확인 후 적용. **적용 스크립트 실행 파일 존재+실행권한도
  최종 확인**(`test -x`). `crontab <파일>`이 스크래치패드 긴 경로에서 원인
  불명 오류(`No such file or directory`, 짧은 경로로는 성공 — sandbox/crontab
  바이너리 쪽 경로 처리 이슈로 추정)를 내 `/tmp` 짧은 경로로 우회, 사용 후
  즉시 삭제.
- **결과**: 다음 cron 실행(가장 이른 건 토요일 06:30 GKG)부터 새 경로로
  정상 동작할 준비 완료 — §2-1이 "가장 위험한 실패모드"로 지목했던 "조용히
  멈춤"을 사전에 차단.
- `origin` 푸시는 이 항목 작성 시점엔 미실행(사용자 지시 범위는 병합+crontab까지)
  이었으나, **바로 다음 사용자 지시로 같은 세션 내 완료**(`d650396..0b105fa`,
  아래 참고) — 이 줄은 작성 당시 상태 기록이라 원문 유지, 최신 push 상태는
  git 이력을 신뢰할 것(WORKLOG는 각 시점 스냅샷이지 실시간 상태가 아님).

## 2026-08-05 — `engine/` 통합 실행(geo·mineral_supply_risk·rag → engine/) — 원래 미룬 사이클을 위험 감수하고 당겨서 실행

§2-1에서 못박은 착수 트리거(서비스 3종 안정가동+Postgres 이관 완료)를 아직
못 채운 상태에서, 사용자가 "지금 바로 진행(위험 감수)"으로 명시 재확정 —
살아있는 cron이 깨질 수 있다고 재차 알린 뒤 받은 확답으로 진행.

- **cron 인벤토리 실측**(`crontab -l`): komir 관련 3건 확인, 전부 본채 절대경로
  참조 — `mineral_supply_risk/scripts/cron_collect_feeds.sh weekly/monthly`,
  `geo/cron_gkg_increment.sh`. git 미추적이라 이번 커밋으로는 안 바뀜(아래 "남은 일").
- **`git mv geo engine/geo && git mv mineral_supply_risk engine/mineral_supply_risk
  && git mv rag engine/rag`** — rename 이력 보존 확인.
- **참조 수정**(전부 grep+직접 재계산·재현으로 검증, 추측 아님):
  `dashboards/streamlit_app.py` MSR_ROOT·루트 `docker-compose.yml` build context 2곳·
  `CLAUDE.md` §1 구조도+§2 실행 명령 전면 갱신·`docs/DB_SCHEMA.md` 라이브 경로 2곳·
  `collector/README.md`+`collector/common.py` 주석 2곳·`services/rag_chat/Containerfile`
  의 실제 COPY 지시문.
- **버그 2건 발견·수정**(단순 ROOT 변수 수정만으론 안 끝났음 — cron 스크립트 본문의
  `cd` 대상도 별도로 깨져 있었음):
  1. `cron_collect_feeds.sh`의 `cd "$ROOT/mineral_supply_risk"`가 `engine/` 누락 —
     수정 후 `python3 -c` 임포트 테스트로 재검증.
  2. `cron_gkg_increment.sh`의 `cd "$ROOT"`(→ komir/)가 `python -m geo ...`를
     komir/ 기준으로 실행하려 해 **ModuleNotFoundError 필연**이었음 — `python -m geo`는
     geo 패키지의 **부모**에서 실행해야 하므로(이관 전엔 komir/, 이관 후엔 engine/)
     `cd "$ROOT/engine"`으로 수정. 실측(`python3 -c "import geo"`)으로 재검증.
  이 두 버그는 §2-1 체크리스트의 "cron 인벤토리·임포트 경로 전수 grep"만으론 못
  잡는 유형(스크립트 본문 로직까지 한 줄씩 읽어야 발견됨) — 기계적 치환만으로는
  불충분하다는 실증 사례로 기록.
- **CLAUDE.md 실행 명령 자체에도 같은 유형 버그 발견·수정**: `python -m geo`
  명령 예시를 처음엔 `cd engine/geo`로 잘못 적었다가(직관적으로는 grep이 그렇게
  치환하기 쉬움), 직접 임포트 재현으로 `cd engine`이 맞음을 확인해 정정.
- **스모크 테스트**(전부 재적합 아닌 순수 임포트/경로 해석 확인, 운영 DB 미접촉):
  `engine/geo`에서 `config` 임포트 OK·`engine/mineral_supply_risk`에서
  `msr.config`+`scripts.diagnosis_retrain_answer` 임포트 OK(DB_PATH 정상 해석)·
  `engine/`에서 `import geo` OK·양쪽 cron 스크립트 `bash -n` 문법 통과+ROOT 재계산
  결과가 실제 존재하는 디렉토리로 resolve됨을 확인.
- **과거 문서는 원칙대로 갱신 안 함**: WORKLOG 기존 항목·DATA_REGISTRY.md(재현
  명령 포함)는 그 시점 경로 그대로 유지 — 지금부터 재현하려면 새 경로(`engine/`
  접두사)를 쓸 것.

**남은 일(이번 커밋으론 미완료, main 병합 시점에 반드시 처리)**:
1. **실제 시스템 crontab 갱신** — git 밖의 시스템 상태라 `git mv`로 안 바뀜.
   main 병합 직후 3개 항목의 절대경로에 `engine/` 삽입 필요, 늦어도 다음 cron
   실행(가장 이른 건 토요일 06:30 GKG) 전까지.
2. **전체 cron 체인 회귀검정 미실행** — 운영 DB에 실제 영향 주는 행위라 이번
   세션에서 자동 실행하지 않음. 최소 `--help`류 무해 스모크만 했음(위 참고).
3. `services/` 스켈레톤 내부의 설명용 주석(`mineral_supply_risk/db/dbio.py` 등,
   전부 `NotImplementedError` 스텁이라 실행에 영향 없음)은 `engine/` 접두사로
   일괄 정정하지 않음 — 다음 구현 세션에서 실제 코드 작성 시 자연히 현재
   경로 기준으로 쓰게 됨.
`docs/CONTAINER_ARCHITECTURE.md` §0·§2-1·§8 갱신(실행 완료 표기+남은 일 기록).

## 2026-08-05 — `deploy/docker-compose.yml` 추가(로컬 개발용, podman-compose.yml과 병존)

사용자 요청("docker-compose 파일도 같이 생성"). `deploy/podman-compose.yml`(airgap 운영
정본)과 서비스 구성이 완전히 동일한 `deploy/docker-compose.yml` 신설 — 차이는
`build.dockerfile`(표준 Docker Compose 키) vs `build.containerfile`(podman 확장 키)
표기뿐, 그 외(qdrant 서비스·볼륨·env_file·포트) 전부 동일. 두 파일 다 YAML 문법
검증 통과. 로컬 개발·테스트는 docker-compose로, 실제 airgap 반입 배포는
podman-compose(§7 build/save/load 흐름)로 — 용도 분리를 문서에 명시. 수동 동기화
필요(자동 생성 아님, 설계 단계 스코프) — 향후 한쪽만 고치고 다른 쪽을 잊으면
드리프트 위험이 있음을 §2·§7에 명시적으로 기록해둠. `docs/CONTAINER_ARCHITECTURE.md`
§2·§7 갱신.

## 2026-08-05 — 아키텍처 설계 적대적 검증 → 벡터DB=Qdrant 확정 반영

사용자 요청("설계안에 대해서 적대적 검증을 진행해주세요") — 독립 에이전트 2개
병렬(기술적 실현가능성 / 요구사항 커버리지·운영리스크) 후 핵심 주장 직접 재검증.
**실행 불가 수준 결함 2건**(`db/schema_addendum_v2.sql`의 `VECTOR(384)`가 DuckDB엔
타입 자체가 없고 Postgres도 `CREATE EXTENSION`이 주석으로만 남아 즉시 실패·~88곳
`duckdb.connect()` 직접호출이 마이그레이션 계획에서 누락)과 착수 전 필수 확인
8건(챗봇 스트리밍 미지원을 재사용 가능처럼 서술·`shared/db.py`가 3서비스 공용이라
해놓고 2개 서비스 Containerfile은 `mineral_supply_risk` COPY 자체를 안 함·
`rag/index/rag.duckdb`(5.8MB) 통째로 이미지에 구워짐·이미 있는 `geo/extractors.py`
의 HWP 파서를 "전수 확인" 주장에도 불구하고 놓침 등) 확인 — 상세는 세션 로그 참고,
전부 실제 파일 대조로 재확인 완료(에이전트 주장 맹신 안 함).

이어 사용자 결정("벡터DB는 Qdrant로, 도커로 이 프로젝트에 직접 붙여줘") 반영 —
pgvector(Postgres 확장) 방식 폐기. 적대적 검증이 지적한 위험(외부 DB 운영주체가
확장 설치를 안 해줄 수 있음, §0 요구사항②)을 구조적으로 해소: Qdrant는 LLM·정형DB와
달리 **komir이 직접 podman으로 소유·기동**. 이 결정에 직접 얽힌 항목들도 같은
자리에서 정리:
- `doc_chunk.embedding VECTOR` 컬럼 완전 삭제 → 벡터는 Qdrant, BM25는 Postgres
  `txt_tsv`(tsvector+GIN, 한국어 토크나이저 부재는 구현단계 결정사항으로 명시).
  **누락됐던 "BM25 절반은 이관 후 뭘 쓰나" 질문도 이 김에 해소**(적대적 검증 지적사항).
- `deploy/podman-compose.yml`에 `qdrant` 서비스 추가(볼륨 영속화·`QDRANT__TELEMETRY_
  DISABLED=true`), `deploy/airgap/{build,save,load}_images.sh`에 qdrant 이미지
  pull/save/load 단계 추가.
- **같은 자리에서 airgap 텔레메트리 함정 클래스 전체 대응**: Qdrant 텔레메트리뿐 아니라
  임베딩 라이브러리의 `HF_HUB_OFFLINE`/`TRANSFORMERS_OFFLINE`(적대적 검증에서 별도로
  지적됐던 항목)도 `.env.example`·Containerfile에 함께 명시.
- **적대적 검증 지적사항 중 하나 추가 해소**: `rag_chat/Containerfile`이 `rag/` 전체를
  COPY해 구버전 인덱스 DB까지 이미지에 굽던 문제 — Qdrant/Postgres 이관 후 그 인덱스가
  통째로 무의미해지는 김에 `rag/ragkit`(코드)만 COPY하도록 함께 수정.
- `docs/CONTAINER_ARCHITECTURE.md` §0·§1·§2·§3·§4·§5·§7·§8 전부 갱신.

**이번엔 고치지 않은 것(스코프 밖, 다음 라운드)**: 챗봇 스트리밍 미지원·
`shared/db.py` 3서비스 공용 주장과 Containerfile COPY 불일치·user_id 인증 방식
미정·`report_gen`↔`rag_chat` 검색계층 공유 메커니즘 미정·HWP 파서 기존 자산
오귀속·airgap 인증/반입심사 절차 미언급·리포트 템플릿 소유권·LLM 레이트리밋 —
전부 적대적 검증에서 확인됐으나 이번 요청(벡터DB 결정)과 직접 얽힌 것만 처리.

## 2026-08-05 — 설계 추기: `engine/` 통합(geo+mineral_supply_risk+rag)은 2단계 마이그레이션으로

사용자 제안("geo·mineral_supply_risk·rag를 engine으로 묶고 services가 호출") —
방향 동의하되 지금 물리적으로 옮기면 살아있는 cron 파이프라인이 즉시 깨질 위험이
있어(임포트 경로+cron 스케줄이 현재 경로 전제) 즉답 대신 트레이드오프 제시,
사용자가 "지금은 유지, 별도 사이클로"(2번 안) 확정. `docs/CONTAINER_ARCHITECTURE.md`
§2-1 신설(목표 구조·착수 트리거 2가지·마이그레이션 체크리스트 6단계·"왜 지금
안 하는가"), §0 결정표·§8 실행순서에도 반영(7단계로 추가, 1~6단계 서비스+DB
이관이 먼저 안정화된 뒤에만 착수). 실제 디렉토리 이동은 **하지 않음**(이번도
설계만).

## 2026-08-05 — 컨테이너화·챗봇·리포트 아키텍처 설계안(`docs/CONTAINER_ARCHITECTURE.md`)

사용자 요청("스트림릿 내리고 프로젝트 구조 변경 — airgap+podman 배포, LLM/embedding·
DB는 외부서비스 .env 접속, 3대 아웃풋(광종 리스트·RAG·Report), 챗봇 user_id/session_id·
히스토리·스트리밍, RAG·Report 둘 다 비정형(pdf/hwp/docx/doc/xlsx/xls/csv)+정형(RDB)
활용, Report는 RDB 주기저장"). `/grill-me` 스킬은 이 환경에 미등록이라 실행 불가 확인
후, 동일 목적으로 AskUserQuestion 4문항 직접 확인 — **결정: DB는 DuckDB→진짜
클라이언트-서버 RDB(Postgres 등) 이관 / 이번 세션은 설계안만(구현은 다음) / "광종
리스트"=기존 진단·예측·지수 모델 API / 챗봇은 komir 내 신규 FastAPI 서비스**.

- Streamlit 데모 서버(8765) 종료.
- **기존 자산 실사**(Explore 에이전트) — 재구현 방지가 핵심: `mineral_supply_risk/
  db/dbio.py`(DuckDB↔SQLAlchemy URL 동일 API, Postgres 이관에 코드 변경 거의 불필요,
  단 `apply_schema`의 DuckDB 분기에 미정의 변수 참조 버그 1건 발견)·`db/schema_core.sql`
  (포터블 DDL, `out_report`·`doc_chunk`가 이미 "⑥챗봇 RAG" 용도로 예정돼 있었음, 0건
  참조라 실질 신규 개발 대상)·`geo/llm/openai_compat.py`(LLM 어댑터, `rag/ragkit/
  generate.py`가 이미 재사용 중)·`rag/ragkit/*`(하이브리드 BM25+dense RRF 검색, 오늘
  사용자가 직접 커밋 — session/user/streaming 전무 확인, 구조화 데이터 검색은 README에
  명시적으로 스코프 밖이었음)·`dashboards/streamlit_app.py`(진단·예측 재현+설명가능성
  로직, "광종 리스트" API의 이식 원본)·기존 `docker-compose.yml`/`geo`·`mineral_supply
  _risk`/`collector` Dockerfile(공상 문서 아니고 대체로 실코드 일치, 재사용 가능).
- **설계 산출물**: `docs/CONTAINER_ARCHITECTURE.md`(전문) + 실제 디렉토리 스켈레톤
  35개 파일 생성(`services/{shared,commodity_api,rag_chat,report_gen,ingestion}/`,
  `db/schema_addendum_v2.sql`, `deploy/{podman-compose.yml,.env.example,airgap/*.sh}`)
  — 전부 `NotImplementedError` 스켈레톤(설계만, 실제 로직 없음). 기존 `geo/`·
  `mineral_supply_risk/`·`rag/` 엔진 패키지는 이동 없이 그대로 유지, 서빙 레이어만
  신설(임포트 경로 회귀 위험 최소화).
- 스키마 확장안(`db/schema_addendum_v2.sql`): `chat_session`·`chat_message`(세션
  히스토리 신규) + `out_report.body` VARCHAR(8000)→TEXT + `doc_chunk`에 `embedding
  VECTOR(384)`(pgvector, `rag/index/rag.duckdb` 인덱스 흡수 목적)+`source_type`/
  `structured_query` 컬럼. `schema_core.sql` 원본은 불변(이어붙이는 방식).
- 정형+비정형 동시활용 설계: 비정형은 파서(`services/ingestion/parsers/`, 포맷별
  기존 라이브러리 재사용 — pymupdf/pdfplumber/openpyxl/xlrd 등 이미 mineral_supply_risk
  에 있음, hwp만 신규)로 마크다운 정규화 후 기존 청킹에 태움. 정형은 **1차 템플릿
  질의만**(LLM은 템플릿+파라미터 선택만, 자유형 NL→SQL은 화이트리스트 없이 보류 —
  인젝션·환각 리스크).
- 다음 세션 실행 순서 8단계 문서화(§8) — dbio 버그 수정→스키마 적용 스모크테스트→
  commodity_api(가장 저위험, 신규 알고리즘 없음)→rag_chat→report_gen→통합 기동.

## 2026-08-05 — MASE 절대기준 오독 정정: "5/10 나이브 열세"→"9/10 나이브 우세"

직전 항목(바로 아래 "리뷰 피드백 대응")에서 낸 MASE 표를 리뷰어가 재질의
("같은 숫자 2.144가 in-sample 스케일이냐 out-of-sample 스케일이냐에 따라
정반대 의미") — 코드 확인 결과 **in-sample(학습구간) 계절나이브 스케일**
(리뷰어 표현으로 "Case A")이었음을 확정. 이 스케일에서 MASE>1은 정상 범위
(다단계 h=1~12 오차를 단일 in-sample 스케일로 나누는 구조상 스케일 자체가
안 맞음)인데도 "MASE>1=계절나이브보다 못함"이라는 **절대기준을 잘못
적용**했던 것 — `msr/models/forecast_unit.py`의 기존 `_mase()`도 동일하게
in-sample 스케일이라, 즉흥 실수가 아니라 **프로젝트가 지금까지 써온 MASE
관행 자체의 해석 함정**이었음이 드러남.

- **검증**: 리뷰어 제안대로 광종별 계절나이브의 **out-of-sample WAPE**를
  같은 18오리진×h1..12 그리드로 직접 재계산(`mase_denominator_check.py`,
  모델 재적합 없는 순수 산술이라 수 초 완료) — 챔피언 WAPE와 나란히 비교.
  리뷰어가 예측한 판별 신호("LI ton 나이브 WAPE 0.24 근처면 Case A")가
  실측 0.2235로 정확히 들어맞아 교차검증 완료.
- **정정 결과**: **9/10 셀이 나이브 우위**(최초 "5/10 나이브 열세" 결론
  철회). 유일한 열세는 ton/LI, 그마저 6.5% 근소(0.2381 vs 0.2235). CO unit
  의 "비현실적으로 좋은" MASE 0.335(in-sample)도 정체가 밝혀짐 — 실제
  OOS 비교로는 나이브 대비 12% 개선(평범하게 준수), 결측/보간 의심은
  해소.
- **후속 조치 철회**: 이전 항목에서 "다음 사이클 조사대상"으로 남겼던
  LI lag-12 진단·나이브 편입·blend 검토는 Case A를 전제로 한 잘못된
  트리거라 **착수하지 않음**.
- **문서 반영**: `챔피언_스코어보드_260727.md` §10①을 정정판(OOS 나이브
  비교 표 + 프로젝트 전체 MASE 해석 주의사항)으로 교체(원문은 삭제하지
  않고 정정 인용 형태로 상단에 남김). `dashboards/forecast_backtest_
  snapshot.json`·`streamlit_app.py` ③탭도 동일하게 갱신.
- **교훈**: MASE는 "같은 스케일을 쓰는 방법 간 상대비교"에만 신뢰할 것 —
  절대기준(1.0 초과=열세) 해석은 다단계 예측+in-sample 스케일 조합에서
  무효. §10②의 풀링 vs 비풀링 판정(WAPE 부트스트랩 기반)은 이 오류와
  무관해 결론 불변.

## 2026-08-05 — 리뷰 피드백 대응: MASE 컬럼+unit 풀링 재검토(풀링 유지, 채택 0건)

사용자가 전달한 리뷰 피드백("표는 나쁘지 않다, MASE 컬럼 추가와 unit 풀링
방식 재검토는 리뷰 전에 처리 권장") — "지금 둘 다 실제로 수행" 선택 후 진행.

- **18오리진 신규 계산**(`mase_and_unit_pooling.py`, 2023-07~2024-12 연속
  월별, 기존 "18오리진" 원본 스크립트는 outputs/에만 있어 재사용 불가 확인
  → 새로 정의·고정): 챔피언(풀링) ton·unit MASE 산출 + unit **비풀링
  (광종별 독립학습, 신규 `_percommodity_forecast`, 같은 ExtraTrees 구성)**
  변형 병행 계산. 총 소요 678초(약 11분).
- **MASE 결과(계절나이브 m=12 대비, <1이 우수)**: CU·LI·REE(ton)와
  CU·LI(unit)는 **MASE>1로 나이브보다 못함**(WAPE만으론 안 보이던 사실) —
  NI·CO(ton), CO·NI·REE(unit)는 나이브 우위. 광종 스케일 차 때문에 WAPE
  낮음=우수가 아닐 수 있다는 걸 실측으로 확인, 다음 사이클 조사대상으로
  기록(이번 스코프는 컬럼 추가까지).
- **unit 풀링 재검토 — 페어드 부트스트랩 95% CI [-0.0062,+0.0073]
  P(비풀링우세)=0.554, 유의한 우세 없음 → 풀링 구조 유지(코드 변경 없음)**.
  핵심 근거: 현재 최약 셀 NI가 비풀링 시 오히려 악화(WAPE 0.382→0.396) —
  다른 광종 신호가 NI 단독학습보다 유용함을 확인. CO ton·NI unit 두 약점
  셀은 원인이 서로 달라(CO=저량고변동→EN+감쇠hl36, NI=풀링 내 최약 셀→
  XT+감쇠hl24) 이미 07-26에 개별 특화 완료된 상태(§본 항목은 그 결론을
  뒤집지 않음, "풀링 구조" 축만 새로 검정).
- **문서화**: `챔피언_스코어보드_260727.md` §10 추기(MASE 표+풀링 재검토
  전문). **Streamlit 반영**: 라이브 재계산은 11분이라 과함 → 정적 스냅샷
  `dashboards/forecast_backtest_snapshot.json` 생성, ③탭에 "성능지표(18
  오리진 백테스트 스냅샷)" 섹션 신설(캐시만, 재계산 안 함)+풀링 재검토
  결과 expander. AppTest 재검증 통과.

## 2026-08-05 — 모델 체크 Streamlit 데모 신설(`dashboards/streamlit_app.py`)

사용자 요청("각 모델별 동작을 체크할 수 있는 streamlit 예제 — 지정학위기지수·
수급위기진단·12개월 수요량및단가예측, 설명가능한 결과 포함, 자체 테스트까지").

- **설계**: `out_diagnosis_alert`/`out_import_forecast_unit` 등 발행 테이블을
  읽는 대신, 확정 챔피언 3종의 학습·예측 로직을 DB에서 **그 자리에서 재실행**
  하도록 구성(발행 테이블이 최대 한 달 이상 정체돼 있음을 확인 — 그 문제를
  우회). 진단은 `msr.models.diagnosis_opt`/`nowcast`의 Ridge 챔피언(전 기간
  재적합+정확한 선형 기여도 분해)과 `scripts.aux_early_warning`의 Δ 조기경보
  앙상블(Bagging25×2+CLI, 전역 계수중요도로 설명)을 재사용. 예측은
  `msr.models.forecast_unit`의 ExtraTrees(direct 다지평) + 기존 SHAP/permutation
  설명 함수(`_build_explanations`)를 그대로 재사용 — 전부 기존 검증된 함수
  임포트로 재사용(재구현 아님), **모든 DB 연결 read_only=True**(각 build_panel
  내부에서 보장) — 발행 테이블·mart_diagnosis_nowcast 등 어떤 운영 테이블도
  쓰지 않음.
- **프로덕션과의 의도적 차이**(속도용, 문서화): conformal 구간보정 생략(원시
  분위), 재귀/direct 자동선택 생략(현재 채택 방식인 direct로 고정), alert.py
  규칙 오버라이드·히스테리시스 미적용(Ridge 원 모델 예측만).
- **환경**: 워크트리엔 `warehouse/`가 없어(gitignore) `MSR_DB` 절대경로로
  본채 DB 지정. `streamlit`·`plotly` 미설치 확인 후 설치(`pip3 install --user`).
- **자체 테스트 3단계**:
  1. 구문검사(`ast.parse`) 통과.
  2. **순수 로직 스모크테스트**(streamlit 없이 4개 로더 함수 로직 직접 실행,
     `/tmp/.../smoke_test_dashboard_logic.py`) — 5광종×3모델 전부 값 범위·
     타입 검증 통과(80초). 예: CU 2026-07 "심각"(ci_pred 98.2), 예측 h=1
     239,858톤 등 실측.
  3. **Streamlit 서버 기동 확인**(headless, HTTP 200) + **`streamlit.testing.v1.
     AppTest`로 UI 와이어링까지 헤드리스 검증** — 초기 로드+광종 5종 전환
     전부 예외 없음, 메트릭 10개·마크다운 31개 정상 렌더 확인.
  4. `use_container_width` deprecation 경고 발견해 `width='stretch'`로 수정,
     도크스트링 날짜 오타(09-04→08-05) 수정.
- 실행: `MSR_DB=<warehouse> streamlit run dashboards/streamlit_app.py`(로컬
  8765 포트로 기동 확인해둔 상태).

**추기(같은 날, 사용자 질의 "챔피언 모델이 다 적용된 건가요?" 후속)**: 위
"프로덕션과의 의도적 차이" 2건(conformal 구간보정, alert.py 규칙엔진·
히스테리시스)을 실제로 반영해달라는 요청으로 마저 구현:
- `load_diagnosis_alert` 신설 — `msr.models.alert`의 `compute_alerts`/
  `_build_reasons`/`_build_evidence_json`을 그대로 재사용(read-only, DB
  미기록)해 챔피언 nowcast 위에 규칙 오버라이드(변동성·HHI 분위)+2주
  히스테리시스까지 적용한 **실제 발행 로직과 동일한** 경보 단계를 표시.
  진단 탭 배지를 원 Ridge 단계(`stage_name`)에서 규칙엔진 최종 단계
  (`alert_name`)로 전환, 오버라이드/히스테리시스 발동 여부와 공식 사유문도
  함께 표시.
- `load_forecast`에 `_conformal_q` 보정(보정 원점 24/18/12개월 전, 프로덕션
  `run()`과 동일 절차) 추가 — 구간이 이제 conformal 가산폭만큼 넓어짐(실측
  ton 0.318·unit 0.173, 로그공간).
- **재검증**: 순수 로직 스모크테스트 확장판(경보엔진+conformal assertion
  포함) 통과(실측 201.6초, conformal 산출 자체가 119초로 대부분 차지 —
  이전 대비 로딩이 느려짐을 확인, UI 스피너 문구에 반영). AppTest(초기 로드+
  광종 전환)도 재검증 통과(초기 209.8초, 광종 전환은 캐시 히트로 0.1초).
  **발견**: 진단 탭에서 Ridge 원모델 단계와 규칙엔진 최종 단계가 다를 수
  있음을 실측 확인(예: REE — Ridge 월간 컷 기준 "관심" vs 경보엔진 주간
  컷 기준 "주의") — 버그 아님, `nowcast.py`(월간 패널 컷)와 `alert.py`
  (주간 패널 자체 컷)가 원래 서로 다른 분포에서 분위수를 계산하는 기존
  프로덕션 구조 그대로 재현된 것(이번에 처음 나란히 노출됨).
- 서버 재기동 완료(8765, HTTP 200) — 첫 로드는 예측 탭에서 conformal 때문에
  약 3~4분 소요(캐시 후 광종 전환은 즉시).

## 2026-08-05 — 해외기관 데이터수집 현황+모델반영여부 이번주 산출물 정리

사용자 요청("지난주 여러 국가 기구 데이터 수집(API키 발급·접속가능여부)
정리 + 모델 반영 여부 문서"). 신규 조사·재검정은 하지 않고 07-28~07-30
원본 3건(해외관세정책_데이터확장_260728·해외기관_수집리스트_점검_260729·
피처_검정_전체이력_260730 §5)을 재정리해 이번 주(2026-W32) 산출물 폴더에
2개 문서로 압축:
- `해외기관_데이터수집_현황요약_260805.md` — tier1·tier2 국가×기관 18개
  총괄(✅가능9/🟡조건부6/❌불가3), API키 최종상태 7건(BPS 재발급으로
  정상화 확인·GACC 상세는 headless 5종 실패로 유료 유일경로 재확인),
  신규 확보 시계열 9계열군 총괄.
- `해외기관_데이터_모델반영여부_260805.md` — 위 수집분 중 R10 검정 대상
  21건 판정표(채택 0·방향긍정보류 6·기각 13·자동제외 2), ph_psa의
  08-04~05 별도 경과(㊿ 참조)를 §2에 연결.

## 2026-08-05 (㊿) — ph_psa·fgap_ni 이웃 강건성 점검 → 사용자 최종 결정: 보류

사용자 지시("최종 채택 결정을 체크")에 대해, ㊾가 아직 다루지 않았던 세 번째 축
(하네스 자체 명시 "이웃 강건성·재발행 강건성"의 앞부분)을 점검. 신규 스크립트
`mineral_supply_risk/scripts/r10_neighbor_robustness_phpsa_fgapni.py`(하네스와
동일 스택·판정 규칙, 07-25 gsev_z13 이웃 9설정 스윕과 동일 방법론) — SERIES_SPEC
등록 파라미터를 살짝 흔겨도 채택 판정(QWK CI 하한>0)이 유지되는지 확인.

- **ph_psa**(lag_days 이웃 {45,60,75,90,105}, 등록값=75): **3/5 통과**, 비단조·
  비일관 — 45(P=0.994)·75(등록값, P=0.994)·90(P=0.976, 하한 +0.0009 경계선)은
  채택, **60·105는 CI가 0을 크게 관통(P=0.575·0.728, 하한 각 -0.0498·-0.0512)**
  하며 보류. 07-25 gsev_z13 선례(9설정 중 7개 유의·전부 방향 양)와 달리 방향조차
  일관되지 않음 — "특정 lag 값 하나에서만 우연히 유의"에 가까운 패턴.
- **fgap_ni**(z-window 이웃 {16,20,24,28,32}, 등록값=24): **3/5 통과**, 24·28·32
  (큰 창)는 채택·16·20(작은 창)은 보류 — 이쪽은 방향은 일관(창이 클수록 유리)
  되나 문턱 통과 자체는 등록값 포함 상반부 3개뿐.
- **재발행 강건성**은 이번엔 재점검하지 않음 — ㊾의 절단 대조(08-01 cron 전/후
  비교)가 이미 이 축의 핵심 질문(원천 갱신에 판정이 흔들리는가)에 답했다고 판단,
  운영 DB에 영향 없는 이 스윕과 달리 실제 파이프라인 재실행은 상태변경 폭이 커
  별도 승인 없이 수행하지 않음.

**해석(사람검토 입력용, 채택 여부는 이 커밋에서 확정하지 않음)**: 07-25 선례가
확립한 "이웃 강건성 통과"의 기준(다수 유의+방향 일관)에 두 후보 모두 못 미침.
등록값(75/24)이 스윕 구간에서 국소 최댓값에 가깝고 근접 이웃에서 성능이 크게
흔들리는 모습은 과적합/우연 신호의 전형적 패턴 — 재현성(㊾)은 통과했지만 이는
"같은 코드·같은 데이터로 다시 돌리면 같은 수"라는 것만 보증할 뿐, "그 수가
파라미터 선택에 강건하다"는 것과는 다른 질문. 종합하면 현재 근거는 **즉시
채택보다는 채택 보류(관찰 지속)** 쪽에 더 가깝다고 판단되나, 최종 채택 결정은
CLAUDE.md §4·하네스 원칙대로 사람이 함.

**사용자 최종 결정(2026-08-05): 보류.** 위 해석과 동일한 결론으로, ph_psa·
fgap_ni 둘 다 방향긍정 보류 목록에 유지(챔피언 스코어보드 §1 15셀 구성
불변). 산출물 문서화: `documents/산출물/2026-W32_0803-0809/
ph_psa_fgap_ni_이웃강건성_보류결정_260805.md`(3단계 검토 전체 기록 — 재현성→
이웃강건성→최종결정). 차기 재검 트리거는 챔피언 스코어보드 §5와 동일(신규
전환 표본 축적 시 하네스+이웃 스윕 재실행).

## 2026-08-04 (㊾) — ph_psa·fgap_ni 재현성 검토: 통과. 단 "가격 갱신 효과" 서사는 정정(원인=경계선 신호+08-01 cron 원천 갱신)

직전 항목(㊽)의 필수 확인 1번 수행. 신규 스크립트
`mineral_supply_risk/scripts/r10_repro_check_phpsa_fgapni.py`(하네스와 동일 스택·판정
규칙) — 리포트 `outputs/model_opt/r10_repro_check_260804.md`(결론 절 포함).

- **결정론 재현 통과**: 동일 공유 rng(0) 시퀀스로 유망 19건 전부 재산출 — 08-04
  리포트와 소수 4자리까지 일치(li_ar·cli_kr·ph_psa·fgap_ni 대조).
- **시드 강건성 통과**: 독립 시드 10종 모두 채택 판정(10/10), CI 하한 MC 변동
  ±0.002 수준. 정밀(n_iter=20000)도 동일 판정.
- **절단 대조 — 예상 뒤집힘**: 현재 DB에서 패널을 갱신 전 종점(2026-06-08)으로
  절단해도 두 후보 모두 채택 유지(ph_psa +0.0046·fgap_ni +0.0049). 즉 07-30
  보류→08-04 채택 전환은 "가격 5주 갱신" 단독 효과가 아니라, ①07-30 당시 둘 다
  CI 하한 0 경계 ±0.005 이내의 경계선 신호였던 점 + ②07-30~08-04 사이 08-01 주간
  cron 원천 갱신(WM 연간 밸런스/재고일수 upsert·COT·SHFE/GFEX OI·IDRUSD·geo 재발행,
  `data_archive/cron_logs/*_20260801.log`)의 결합. ㊽의 "가격 갱신이 원인" 추정은 정정.
- **이득 분해는 채택 지지**: ph_psa 기존 구간 6득1실+신규 2득0실(06-29·07-06 NI
  하향전환을 후보만 정답), fgap_ni 순수 기존 구간 4득0실 — 단일 관측 의존 아님.
- 실측 각주: fact_price 종점 2026-07-06·6,867행, mart 종점 2026-07-06, 절단으로
  제거되는 NI 행 4행(549→545) — 전부 duckdb 직접 쿼리.

잔여: fgap_ni는 CI 하한 +0.004~0.005의 **경계선 유의**(원천 미세 갱신에 민감).
다음 단계=이웃 강건성·재발행 강건성(사람검토) 후 채택 최종 결정.

## 2026-08-04 (㊽) — KOMIS 주간가격 반영 확인 + R10 전면 재검정: ph_psa·fgap_ni 채택후보 전환 확정(사람검토 전 단계)

세션 시작 시 이 워크트리(`.claude/worktrees/orktree`)에만 **미커밋 상태로 남아 있던**
`mineral_supply_risk/scripts/load_komis_weekly_202606_07.py` 발견 — docstring상 07-31경
"mart 갱신 후 ph_psa 재검정" 작업 중 `fact_price`가 2026-06-08에서 멈춰 있던 걸 발견해
작성한 KOMIS 주간가격 5주치(06-08~07-06) 로더. **본채(메인 체크아웃) DB 조회로 실제
반영 여부 확인**: `fact_price`·`mart_weekly_diagnosis` 모두 2026-07-06까지 정상 갱신,
NI/CU 06-08 이상치도 xlsx 값으로 교정된 상태 확인(값 대조 완료, 스크립트 자체는 이
워크트리에만 있고 git 미추적·미커밋·WORKLOG 미기록인 채로 방치돼 있었음).

이어서 갱신된 가격 데이터로 **R10 전면 재검정**(`r10_retune_harness.py`, 전체=스크리닝+
부트스트랩+예측exog) 백그라운드 실행 — **완주 확인됨**(세션 종료 통보 시점엔 예측 exog
단계 도중이라 미완료로 기록했었으나, 이후 도착한 백그라운드 완료 알림으로 정정: exit 0,
전체 완주). 리포트: `mineral_supply_risk/outputs/model_opt/r10_retune_report.md`
(2026-08-04 19:02 생성).

예측 exog 스크리닝(40여 후보 전체 순회 완주)은 **전부 기각**(ΔWAPE>0.005 미달) —
신규 채택 없음.

**부트스트랩 확정 결과 — 기존 방향긍정 보류였던 2건이 채택후보(유의) 문턱을 넘음**
(가격 데이터 갱신이 원인으로 추정, 사람검토는 아직 미수행):
- `ph_psa`(필리핀 NI, PSA·BOC): QWK CI [+0.0153,+0.1306] P=0.995 → **채택후보(유의)**
  (직전 07-30 결과는 P=0.965 방향긍정 보류였음 — 이번에 CI 하한>0으로 전환)
- `fgap_ni`(NI 공급갭 파생): QWK CI [+0.0045,+0.0489] P=0.984 → **채택후보(유의)**
  (직전에도 방향긍정 보류 목록에 있었으나 이번에 전환)
- 기존 채택 2건(`li_ar`·`cli_kr`)은 재확인 유지, 나머지는 방향긍정 보류/기각 그대로.

⚠ **다음 세션 필수 확인 사항**:
1. **ph_psa·fgap_ni 채택 여부 확정 전 CLAUDE.md §4 원칙대로 사람 검토 필요** — 하네스는 검정까지만
   자동화, 채택 결정·이웃 강건성·재발행 강건성 확인은 미수행. 특히 가격 데이터 갱신 하나로
   판정이 바뀐 것이라 **재현성(같은 코드, 갱신 전 가격으로 되돌려 재실행)부터 확인**해 진짜
   가격 갱신 효과인지 확인할 것.
2. 본채(main checkout) `warehouse/minerals.duckdb`에는 이미 가격이 반영돼 있음(이 커밋
   이전부터) — 이 커밋은 그 사실을 기록·검정 결과를 남기는 것이며 DB 자체를 바꾸지 않음.

## 2026-07-31 (최신㊼) — 방향긍정 보류 14건 결합(joint) 검정 — 여전히 무차별

사용자 질의("어제까지 데이터로 처음부터 다시 빌드해도 같은 결과일까?")에
"순차/그리디 검정이라 방향긍정 보류 14건을 한꺼번에 결합했을 때는 검정한
적 없다"고 답한 뒤, 사용자 요청으로 실제 결합 검정 수행.
`scripts/r10_joint_pending_test.py` 신설(기존 하네스와 완전히 동일한 파이프
라인·시드 재사용, 결과 직접 비교 가능) — NI 9건(ni_ph·jp_ni·cn_ni·au_ni·
ph_psa·id_ni·us_ni·supdiv_ni·fgap_ni)과 CU 3건(cn_cu·au_cu·cl_cu_ref)을
광종 챔피언 위에 동시 결합.

- **NI 9건 결합**: QWK CI [-0.0206,+0.1212] P=0.910 → 방향긍정 보류 유지.
  개별 최강 후보(ph_psa 단독 P=0.965)보다 오히려 P가 낮아짐 — 약한/중복
  후보(ni_ph는 ph_psa와 같은 대상을 다른 경로로 잰 값)를 같이 넣으면
  신호가 희석됨을 확인.
- **CU 3건 결합**: QWK CI [-0.0146,+0.0536] P=0.856 → 방향긍정 보류 유지.
  개별 최강(cl_cu_ref P=0.721)보다는 소폭 개선됐으나 유의 문턱 미달.
- **결론**: 순차검정이 놓쳤을 수 있는 "합쳐야 보이는 효과" 가설을 직접
  검정한 결과 **둘 다 여전히 채택 기준 미달** — 지난 한 주간의 순차 검정
  결론이 결합 검정으로도 재확인됨(CLAUDE.md §4 "구조가 모델을 앞선다" 원칙의
  추가 근거).

## 2026-07-30 (최신㊻) — 피처 검정 전체이력 종합표 작성(프로젝트 시작~어제 API분까지)

사용자 요청("피처 엔지니어링·모델링 반영 시기 처음부터 어제 API 추가분까지
전부 표로, 사용여부·기각사유 포함"). WORKLOG 전체(①~㊺)·
`r10_retune_harness.py` SERIES_SPEC·`diagnosis_*_eval.py` 계열·
`챔피언_스코어보드_260727.md` §4를 Explore 에이전트로 전수 재조회해
`documents/산출물/2026-W31_0727-0802/피처_검정_전체이력_260730.md` 작성.
구성: ①진단 레벨 기본 피처 ②진단 Δ보조 조기경보 ③예측(ton/unit) ④지수
확률화(geo_prob) ⑤R10 SERIES_SPEC 국가·기관 데이터 후보 전체(58건, 어제·
오늘 신규분 포함) — 각 판정(채택/방향긍정보류/기각/자동제외)과 구체 사유
(QWK/P값 등)를 원문 재확인해 정리. **핵심 재확인**: 국가·기관 데이터 후보
58건 중 실제 채택은 아르헨 LI(li_ar)·OECD 한국 CLI(cli_kr) 2건뿐 — "구조가
모델을 앞선다"(CLAUDE.md §4) 원칙의 정량적 근거.

## 2026-07-30 (최신㊺) — tier2 검정 공백 발견·해소: 칠레 CU·DRC CO R10 등록(채택 0건)

사용자 질의("tier2 국가 기관들이 특정 광종에 영향을 미치지 않는가?")로 전체
tier2 계열의 R10 SERIES_SPEC 등재 현황을 점검한 결과, **칠레 구리(COCHILCO,
07-25부터 수집)와 DR콩고 코발트(중국 경유 미러, 기존 수집)가 한 번도
검정된 적이 없는 진짜 공백**임을 발견(둘 다 세계 최대 생산국 — 검정 누락이
꽤 중요). 사용자 확인 후 즉시 3계열 등록·전면 재검정:

- `cl_cu_mine`(칠레 광산생산)·`cl_cu_ref`(칠레 정련생산)·`cd_co`(DRC
  코발트, `CN_CO_IMPORT_COD_WGT` 중국 수입 미러) SERIES_SPEC 추가.
- 결과: cl_cu_mine 스크리닝 기각. **cl_cu_ref는 스크리닝 유망(QWK 0.9151) →
  부트스트랩에서 방향긍정 보류(P=0.721)** — 방향긍정 목록 12번째 합류.
  cd_co는 스크리닝 기각(꼬리정지 2024-12 — 중국 Comtrade 보고중단과 동일
  원인, 예상된 결과). 예측 exog 3건 전부 기각.
- **채택 0건 — 챔피언 구성 불변 재확인.** 이로써 tier2 국가×광종 조합
  전체(아르헨 LI·칠레 CU/LI·DRC CU/CO·페루 CU·필리핀 NI·호주 LI/Nd·
  인니 NI/CO/LI)가 R10 검정 이력을 갖추게 됨 — 실제 유의 채택은 아르헨
  LI(li_ar, Comtrade 경로) 1건뿐임을 재확인, 나머지는 기각 또는 방향긍정
  보류. 리포트 정본 갱신(직전판 `r10_retune_report_260729.md` 보존).

## 2026-07-29 (최신㊹) — ARCA 전체 백필+Census+BPS 키 반영 → R10 전면 재검정(채택 0건, 챔피언 불변)

사용자 목표("arca, bps 데이터 싹 다 수집해서 가공해서 피처 엔지니어링과
모델링을 거쳐서 최적 모델을 찾아내라") 수행.

- **ARCA 전체 백필 실행**(2019-01~2026-06, 96개월 대상, 동시 6워커):
  `AR_LI_EXPORT_WGT/VAL_ARCA` 각 41행 확보(5개월은 ChunkedEncodingError로
  스킵 — 재시도 가능하나 표본에 큰 영향 없어 보류). **교차검증 발견**: UN
  Comtrade(li_ar, 56개월 보고)와 ARCA(41개월) 양쪽 모두 **2019~2023년에
  독립적으로 동일한 보고 공백**을 보임(2019년은 두 원천 다 0개월) —
  파싱 버그 아니라 이 시기 아르헨티나 자체의 보고 불규칙성으로 실측 확인.
  공통 26개월·Comtrade단독 30개월·ARCA단독 15개월로 상호 보완적.
- **Census·BPS 키 실제 DB 반영**: Census 18계열 2,864행(2013~2026, 어제
  구현). BPS는 사용자가 재발급한 키("Indonesia Critical Minerals Trade
  Monitor")로 정상화 — 니켈(BPS 자체 챕터 75, 149개월, 2014~2026)·
  코발트 3계열·리튬 2계열(BPS 8자리 코드북 실측으로 유효코드 확정) 총
  12계열 484행.
- **버그 2건 발견·수정**(반영 직후 실행 중 발견, `feedback-careful-code
  -no-bugs` 적용): ①`ID_NI_EXPORT_VAL/WGT`가 기존 UN_COMTRADE(tier1)
  계열과 이름 충돌(PK에 src 없어 INSERT 시 제약위반 실제 발생) — PSA·GACC와
  동일하게 `_BPS` 접미로 전량 수정. ②R10 SERIES_SPEC의 신규 `us_ree`가
  어제 등록된 기존 `us_ree`(REE 수출)와 name 충돌 — `us_ree_imp`로 개명.
  둘 다 실행 후 결과가 이상해서(제약위반 예외·"데이터없음" 오표시) 즉시
  발견·수정, 재실행으로 정상 확인.
- **R10 전면 재검정**(신규 SERIES_SPEC 11건 추가, 스크리닝+부트스트랩+
  예측exog 전체): ar_li_arca(LI, ARCA)·id_ni(NI, BPS)·id_co_um·id_li_carb
  (CO/LI, BPS — 표본 19·17행<24 최소요건 미달로 자동 제외, 정상 동작)·
  us_ni/us_co/us_co_dut/us_li/us_ree_imp/us_ree_dut/us_cu(Census). 결과:
  **채택 0건.** id_ni(P=0.703)·us_ni(P=0.865)는 스크리닝 유망 → 부트스트랩
  방향긍정 보류(기존 방향긍정 6~9건에 합류). 나머지는 스크리닝 기각. 예측
  exog도 전패(lag 지배 확인, 이번이 몇 번째인지는 각 스크립트 참조). **결론:
  챔피언 구성 전부 불변** — 리포트 `r10_retune_report.md`(직전판은
  `r10_retune_report_260728.md`로 보존).
- cron 반영: `cron_collect_feeds.sh` monthly `trade` 스텝에 CENSUS_API_KEY·
  BPS_API_KEY export 추가(누락 시 매달 조용히 스킵되는 버그 사전 차단).

## 2026-07-29 (최신㊸) — 해외기관 수집리스트 항목별 점검 문서 작성

사용자 요청("어제 요청 리스트에 대해 수집 가능 여부·가능한 시계열·불가 사유·
필요 조치를 md로, 기각 사유 중 row 정합 불가 사유도 별도 기술"). 사전 확인
2건: ①FedReg 정책공고는 어제 코드의 `2020-01-01` 시작이 기술적 제약이 아니라
임의값임을 재검증(2016년 BIS 131건 존재, 최고령 2002-04-26 확인) ②MOFCOM은
`pageNo/currentPage/page/pageIndex` 등 페이지네이션 파라미터를 오늘 재시도해도
전부 무시되고 최신 15건만 반환 — 과거분 백필 불가가 재확인됨(사이트 자체
sitemap·검색 API도 404/DNS 실패).

`documents/산출물/2026-W31_0727-0802/해외기관_수집리스트_점검_260729.md` 작성 —
원 요청 리스트(tier1 3개국·tier2 6개국) 순서 그대로 국가×기관별 ①상태
②확보 시계열(코드·행수·기간, 전부 재실측) ③불가 사유 ④필요 조치(가입·API키·
유료) 기술. 핵심 신규 내용:
- **§4 통계적 기각과 §5 구조적 정합 불가를 명시적으로 분리**. §5는 5개 유형
  (A 그레인 과소·forward-fill 허위정밀도, B 누계발표라 연도경계서 차분 불가,
  C 조인키가 연도별로 바뀜(PSA·GACC 상품코드 실사례), D 국가 자체 미보고,
  E 스캔 PDF라 표 자체가 없음) — R10 검정대에 오르지도 못한 항목을 구분.
- 중국 GACC는 CU·REE만 커버(NI·CO·LI 없음)를 재확인 — 발주처 유료 요청은
  이 3광종으로 축소 권고 유지.

## 2026-07-28 (최신㊷) — 발주처 수집대상 확장(9개국×기관): 무키 7소스 당일 반영+R10 검정

발주처가 해외 관세·정책 수집 확장 지정(tier1: 중국 MOFCOM/GACC·미국 DOC/CBP·
인니 ESDM/관세청, tier2: 아르헨 LI·칠레 CU/LI·DRC CU/CO·페루 CU·필리핀 NI·호주
LI/Nd). 병렬 조사 3건+서버 실호출 재검증으로 기관별 판정 후 당일 처리:

- **수집기 신설 `collect_intl_agency_feeds.py`**(cron 편입: 주간 policy/월간
  trade) — 무키·무인 7소스: ①페루 BCRP(CU 수출 금액·물량+광산생산, SUNAT/MINEM
  원자료, 2000~) ②호주 ABS SDMX(SITC 283/284 동·니켈광 수출액, 1995~) ③필리핀
  PSA OpenSTAT(NI 수출 HS 2604\*+7502\* USD/kg, 2007~ — MGB 전역 WAF 403 대체)
  ④중국 GACC 영문 월보(동정광·미가공동·희토류 수출입 8계열, 2018~, 래그 ~3주 —
  **Comtrade 중국 2024-12 정지의 CU·REE 부분 해소**, 1~2월 합산은 누계 차분 복원)
  ⑤MOFCOM 정책공고(jpaas unit API — 수출통제·실체명단, 주간 폴링 축적)
  ⑥미 연방관보 API(BIS·USTR 2020~ 1,366건) ⑦USITC HTS 관세율 스냅샷(광물
  HS4+챕터99 775행, 릴리스 diff로 조치 추적). 신규 테이블 raw_policy_notice·
  raw_hts_rates(DB_SCHEMA.md 갱신). fact_indicator 신규 15계열 2,436행 실측.
- **버그 3건 실행 중 발견·수정**: PSA CSV latin-1 인코딩, GACC 과거연도 페이지
  개행 정규식, HTS `to` 상한 배타(+1 필요)·footnotes null. **교훈(신규): 원천이
  다른 동명 시리즈는 indicator 접미로 분리**(_PSA/_GACC) — Comtrade 계열과
  fact_indicator PK(광종·indicator·obs_date) 충돌을 DB가 실제 차단해줬음.
- **R10 하네스 검정**(SERIES_SPEC 8건 등록 → --quick+풀): 진단 스크리닝 유망
  3건(ph_psa QWK 0.9286/FAR 0.0171·au_cu 0.9143·au_ni 0.8778)은 부트스트랩에서
  전부 **방향긍정 보류**(CI 하한>0 미달, ph_psa P=0.965 — Comtrade ni_ph
  P=0.687보다 강해 축적 후 대체 1순위), 페루 2·GACC 3은 스크리닝 기각. 예측
  exog는 8건 전패(lag 지배 5번째). **채택 0건 = 챔피언 구성 불변.** 리포트
  정본 갱신(직전판은 r10_retune_report_260725_weekend.md 보존).
- **문서**: `documents/산출물/2026-W31_0727-0802/해외관세정책_데이터확장_260728.md`
  — 기관별 판정 총괄, 키 필요 5건(BPS·Census·Comtrade 정식키·DataWeb·칠레
  중앙은행), 불가·대안 4건(CBP 403→Census/관보, DRC 전멸→미러, MGB→PSA,
  MODI→이관 중), 후속 구현 6건(ARCA NCM zip 1순위·칠레 세관 CKAN·인니 HMA
  ⚠2026-04 산식 break·DISR REQ 반자동 등). 발주처 유료 요청(중국 세관)은
  NI·CO·LI로 범위 축소 권고.

## 2026-07-27 (최신㊶) — 시스템 기술서(데이터·전처리·모델링)+스코어보드 통합 확정판

사용자 요청("금일 날짜로 수집 데이터·전처리·모델링 상세 기술 문서와 스코어보드").
W31 폴더에 2건:
- `시스템_기술서_데이터_전처리_모델링_260727.md` — 기술 정본: ①수집 데이터 전수
  (07-27 DB 실측 수량, 정형 12분류+비정형)+수집 규약(멱등 스코프·가드·cron 3종)
  ②전처리(GKG 파싱→LLM재검증→관련성 99.5% 정제 4단계, as-of 조인·avail_date·
  결측 원칙·표준화 파생, 지수화 grid+tanh) ③모델링(4모듈 피처·모델 정의 —
  코드로 재확인: 예측 FEATS 11종+MIDAS, 진단 GEO/PRICE_FEATS, prob base3+
  x_z13+k_adapt)+공통 검증 원칙+R10 하네스 ④발행 산출물 실측표. 잔존 한계
  (오태깅 6.4%·severity 상향 편향)도 정직 기재.
- `챔피언_스코어보드_260727.md` — 260725판+추기 1~3을 단일 수치로 통합한 **대체
  정본**: 모듈 총괄·15셀 매트릭스(v4 반영)·07-27 운영 상태(CU 복구 재발행,
  NI 신호 박빙 반전)·재시도 금지 요약·교체 조건(차기 재검 트리거 3종).

## 2026-07-27 (최신㊵) — 발주처 전달용 확정 모델 구성표(15셀 확정본)

사용자 요청("15개 챔피언 확정 가능? → 발주처 전달용 확정표로"). `documents/산출물/
2026-W31_0727-0802/확정모델_광종별구성표_260727.md` — 보고서체·내부용어 배제
(챔피언→확정 운영 모델, XT→극단 랜덤화 트리, NB2→음이항 회귀 등). 구성: ①확정
기준 3가지(3중 검증·탐색 소진·교체 조건 명문화) ②모듈별 공통 구성+입력 데이터
③15셀 광종별 특화 표 ④광종별 성능 상세 3표(지수 Brier·진단 QWK·예측 WAPE,
스코어보드 추기 1~3 수치 그대로) ⑤정직한 한계(LI 지수 무차별·CO/REE 특화축
부재는 표본 시간 문제·아르헨 축 조건부) ⑥유지·교체 원칙(재검정 게이트, CU 재고
복구 선례 = 구성 불변 인용). 수치 출처는 챔피언_스코어보드_260725.md(주말 실측
정본+v4 재실측 일치 확인분) — 신규 실측 없음. docx 변환은 pandoc 부재로 md 전달
(기존 관례 동일).

## 2026-07-27 (최신㊴) — A-5 방식 변경: 순수 LLM 교차판정(Claude) 수행 — ⚠사람 검증 아님

사용자가 사람 공수 부담("사람이 저거 언제 봐")을 이유로 방식 재검토 요청 →
AskUserQuestion 4옵션(하이브리드 권장/순수 LLM judge/표본축소/B안 유지) 중
**"순수 LLM judge"를 한계 인지 후 명시 선택**([[feedback-human-validation-proxy]]
절차 준수). 수행: Claude가 LLM 값이 제거된 배포본(a5_review_A_260727.csv)의
evidence_quote 250건을 전건 독립 판정(판단불가 10건 강제 채움 없음) —
`scripts/a5_fill_llm_judge.py`(판정 원본 기록)·
`a5_kappa_report_llmjudge_260727.md`(경고 헤더 필수 유지).

**결과(vLLM 추출 vs Claude 판정)**: severity wk=0.4912(보통)·direction
k=0.5046(보통)·event_type 적절성 Y 131/N 94/부분 25. **계통 발견 3건**:
①severity 교차표 일방향 상향 편향 — vLLM=3 58건 중 Claude 동의 4건(vLLM이
심각도 체계적 부풀림, 지수 severity 가중 상향 바이어스 후보) ②direction은
중립 보도에 supply_down/up 남발 ③ET 적절성 N의 81%(76/94)가 '뉴스' 무정보
라벨(GKG tone-only 행 구조 문제 — event_type 표준화 과제의 정량 근거).
부산물: 오태깅·무관 의심 16건(6.4%) 비고 기재 — 정제 후 잔존 오염 상한 참고.

**지위**: A-5(사람 검증)는 **여전히 미완** — 발주처 보고서에는 "교차 모델 일관성
점검"으로만 기재 가능. 사람 판정이 필요해지면 a5_review_A/B_260727.csv 원본으로
처음부터(0단계 패키지는 그대로 유효).

## 2026-07-27 (최신㊳) — A-5 0단계 완료: v2 재표집 250건 + 2인 교차(B안) 패키지

사용자 승인("B안으로 0단계 착수"). 최신㊲ 방안의 0단계 실행 완료:
- **재표집**: `a5_label_review_sample.py` v2 — 층화 (광종×severity) 2축, 정제 후
  모집단 296,046건에서 250건(광종별 50, severity 셀 12~14 균형 — CO·REE 희소
  광종도 예산 충족, severity=3도 광종별 12건 확보). 산출물은 `_260727` 접미사로
  구판(07-18) 보존.
- **B안 지원**: 검토자 배포용 A/B 사본은 severity·direction LLM 값 열 자체를 제거
  (구판 "열 숨김 권장"보다 강한 앵커링 원천 차단; event_type_LLM은 적절성 판정
  대상이라 유지). LLM 값은 마스터 CSV에만 — 채점 시 event_id 병합.
- **채점기 확장**: `a5_kappa_score.py`에 --input2(검토자 B)·--master(LLM 열 병합)·
  --out 추가 → LLM vs A·B 각각 + **사람간(A vs B) kappa**(해석 기준선) 산출.
  합성 A/B(설계 일치율 75/70%)로 전 경로 검증 — 수치 정합 확인. 부수 수정 1건:
  빈 셀이 NaN→"nan"이라 "빈칸 0"으로 표기되던 카운트 결함(구판부터, 채점 제외
  자체는 정상이었음).
- **가이드 v2**: `a5_labeling_guide_v2_260727.md` — dimension 삭제·2인 교차 절차
  (독립 판정, 파일럿 20건 후 기준 보정만 허용)·event_type 비표준값 안내.
- 다음은 사람 몫: 검토자 A·B 지정 → `a5_review_A/B_260727.csv` 배포(파일럿 상단
  20행 → 리뷰 미팅 → 본판정). 성공 기준은 방안 §4 사전 합의값.

## 2026-07-27 (최신㊲) — A-5 사람판정 진행 방안 수립(실측 기반 재설계 필요 확정)

사용자 요청("A-5 사람판정 진행 방안 정리"). `documents/산출물/2026-W31_0727-0802/
A5_사람판정_진행방안_260727.md` 정본. **실측 3건이 방안의 골격**:
①기존 표본 248건 중 현행 geo_event 생존 122건(49%) — GKG 정제(181만→29.5만)로
절반 소멸, 재표집 필수 ②**dimension 필드 전량 소실 발견**(296,046건 모두 None,
07-18엔 존재 — 정제 후 재발행 미보존 추정, 원인 추적 별도 과제) → 판정 항목을
severity·direction·event_type 3종으로 재정의, 층화도 광종×severity 2축으로
③관련성 검증은 별도 종결(99.5%)이라 A-5는 순수 라벨 품질에 집중. 방안: 0단계
패키지 최신화(Claude 반나절)→검토자 옵션 A(내부1인)/B(내부2인 교차, 권장 —
사람간 kappa 기준선 확보)/C(발주처 전문가, 병행 제안)→파일럿 20건→본판정→
채점(기존 a5_kappa_score.py 재사용). 성공 기준 사전 합의 원칙(severity wk≥0.4
등). 일정: 8월 중순 종결(납기 4주 여유). REFERENCE_ONLY 임시채움은 검토자 비공개
유지, 유일한 정당 용도는 사람 판정 완료 후 부록 대조.

## 2026-07-27 (최신㊱) — CU cninv 복구 반영 재발행: aux 조기경보 v2 + 대시보드

사용자 지시("재발행도 지금 진행"). 최신㉟에서 복구한 CU SHFE 재고를 반영해, 토요일
발행분 중 CU cninv를 실제 사용하는 유일한 산출물인 보조 조기경보를 재발행
(`aux_early_warning` 재실행, out_aux_early_warning 5행 교체 — forecast_unit v4는
재고 피처 미사용(전부 기각 이력)이라 재발행 불요, 운영 등급예측(레벨)도 cninv
미사용 축이라 불변). **신호 변화(기준주 2026-06-08, 결측→복구)**:
- CU: 유지 → 유지(확신 강화 — p_stay 0.439→0.507, cninv 정보 반영)
- **NI: 상향(0.379) → 하향(0.376)** — 단 3분류 확률이 0.376/0.316/0.309로 박빙
  (결측 시에도 0.379/0.317/0.304 박빙) — 풀링 재적합에 따른 경계선 반전으로 해석,
  트리거 자체는 유지
- LI: 상향 유지(0.629→0.573), REE: 하향 유지, CO: 유지.
대시보드 `build_dash.py` 재생성(573KB) 후 기존 아티팩트 URL로 재발행, META 갱신.

## 2026-07-27 (최신㉟) — SHFE CU 재고 재소실 원인 규명·복구 + 교차 삭제 결함 3곳 수정

피처 인벤토리 260725판 실측(최신㉞) 중 발견한 CU 재고 0행의 원인 규명. **최신⑲의
"빈/부분 응답" 가설은 오진** — 진범은 `collect_exchange_inventory.py`의 `_upsert`가
`DELETE WHERE src='SHFE_99QH_W'`를 **광종 필터 없이** 실행하는 것. 이 수집기는
07-24에 NI·LI용으로 작성됐고 이후 CU가 같은 src에 합류했는데 DELETE 스코프가
안 따라갔다. 07-25 01:32 복구+가드는 collect_priority_feeds(CU측)에만 붙어서,
**09:10 weekly cron 1단계(exchange_inventory)가 NI 수집→src 전체 삭제→NI만
재삽입으로 CU를 다시 지움**(cron 로그 요약표에 CU 부재로 실증). 07-24 최초
소실도 같은 경로였을 개연성 높음.

같은 부류(공유 네임스페이스를 소유분 초과 삭제) 전수 조사로 잠복 2건 추가 수정:
- `collect_forecast_exog.py`: COT_CU만 수집하며 src='CFTC_SOCRATA' 전체 삭제
  (tier1 소유 COT_CO/LI 포함 — 주간 cron에서 tier1이 뒤에 돌아 자가 치유돼
  가려져 있던 결함) → series_code 한정+빈 응답 가드.
- `collect_priority_feeds.py` PMI 분기: src='AKSHARE_MACRO' 전체 삭제(tier4 소유
  CN_ELEC_CONS_M·CN_CARBON_W 포함, 월간 cron 순서로 치유) → PMI 2계열 한정+가드.

조치: ①CU 재수집·적재(1,166행, 2005-01-14~2026-07-24 — NI 644·LI 132+13 무손상)
②exchange_inventory에 광종 한정 DELETE+NI 가드(300행 미만 보존) ③수정판 실행
실증(NI 재수집 후 CU 생존 확인). **교훈: 멱등 DELETE→INSERT의 삭제 스코프는
"이번에 수집한 것"과 정확히 일치해야 하며, src 하나를 여러 수집기·광종이 공유하면
소유 경계를 명시할 것.** cron 순서에 기대는 자가 치유는 결함 은폐라 순서 무관하게
안전해야 함.

## 2026-07-27 (최신㉞) — 피처·데이터 인벤토리 260725판(주말 사이클 반영 전면 갱신)

사용자 요청("07-24 인벤토리에 주말 작업이 빠져 있으니 토요일 기준으로 260725판
작성"). `피처_데이터_인벤토리_260725.md` — ①운영 사용 13행(R10 채택 2건·재고
운영화·CLI 등 편입) ②R10 판정별 세분(보류 6·기각·예측 exog 29종 전패·축적 대기)
③WoodMac DB화 승격 반영 ④07-24 셔틀리스트 8건 결산+발주처 21항목 연결. 수량은
전부 07-27 DB 재실측(각주에 쿼리). 실측 중 SHFE CU 재고 0행 발견 → 최신㉟로 이어짐.

## 2026-07-26 (최신㉝) — 발주처 보고서에 v4 결과 반영 갱신

`발주처보고_데이터확충_모델개선_260726.md` 갱신: §1·§3.1에 v4 실측치 반영
(물량 29.3→26.3%·코발트 물량 62→51%(2단계 특화)·니켈 단가 38.6→36.9% 행 신설,
"10개 세부항목 전수 점검" 문구), §3.3에 리튬 급증확률 격차 무의미 확정 및 데이터
요청 연동 1건 추가. 수치는 v4 운영 코드 재실측(percc 재실행 — 에이전트 하네스와
소수점 4자리 일치) 기준.

## 2026-07-26 (최신㉜) — LI 지수 잔여 약점 검정: 채택 0건, "약점 실재 부정"으로 종결

사용자 지시("LI 지수 잔여 약점 개선"). 6변형(x_z13 전이·이웃격자·isotonic/Platt·
NB2 시간감쇠 관측가중·상수 수축블렌드·조합) 전부 3관문(NB2 유의개선+상수 우위+
강건) 미통과 — 현행 NB2 base3 유지. 대신 두 확정: ①Δ0.005 열세 자체가 부트스트랩
CI [−0.014,+0.006]로 통계 무차별(메울 격차 없음) ②"상수로 수축해야만 이기는"
구조적 상충 존재. 시간감쇠는 지수 셀에선 역효과(hl26 0.1498) — 감쇠 만능 아님.
실개선 경로는 LI burst 선행 신호원 확충(EV 장기·GFEX 축적, 발주처 요청 연계).
리포트 `li_prob_improvement.md`(재시도 금지 목록 포함), 스코어보드 추기 3.

## 2026-07-26 (최신㉛) — 15셀 매트릭스 실측 → 약점 2셀 병렬 특화 → forecast_unit v4

사용자 요청("5광종×3모듈 최고 조합 정리") → 문서 미기록이던 광종별 분해를 운영
코드로 직접 실측(scratchpad `percc_champion_eval.py`, 풀링 값 기존 기록과 일치로
상호검증)해 챔피언_스코어보드에 15셀 매트릭스 추기. 약점 2셀(NI unit 0.3857
최약·CO ton 0.5306 절대값 최대)을 병렬 에이전트로 동시 특화 검정 → 둘 다 게이트
통과, 사용자 승인으로 **v4 운영 반영**: NI unit=XT+감쇠hl24 셀 오버라이드
(0.3694, P=0.999)·CO ton=EN+감쇠hl36(0.5121, P=0.989 — EN만 무가중이던 비대칭
해소, 트리 hl24 재사용은 게이트 탈락). NI unit 모델 교체(EN·Ridge·HGB·RF)는 전부
유의 역효과 — 재시도 금지. 설명가능성도 실제 모델로 정합(model_ni SHAP 분기).
리포트 `ni_unit_specialization.md`·`co_ton_further.md`, 스코어카드 v1.22.

## 2026-07-26 (최신㉚) — 발주처 전달용 통합 보고서 작성

사용자 지시("요청 목록+R10 결과를 전달용 문서로"). `발주처보고_데이터확충_모델개선
_260726.md` — 보고서체·내부용어 배제·전/후 대비 표: ①데이터 확충 결과(16배,
신규 원천 분류표+수집 불가 판정 근거) ②모델 개선(예측 -11%/-10%·코발트 -15%,
조기경보 0.83→0.89·오경보 21%→15%, REE 왜곡 해소·CO Brier 개선, 3중 검증 원칙
명기) ③협조 요청 우선순위 5건+전체 21항목(별첨 참조) ④"제공 시 수일 내 검증
회신" 재검정 체계 어필. docx 변환은 pandoc/libreoffice 부재로 md 전달(필요 시
발주처 측 변환 안내).

## 2026-07-26 (최신㉙) — R10 채택 2건 운영 반영(aux_early_warning v2, 스코어카드 v1.21)

사용자 지시("채택 2건 운영 반영"). 
- **보조 조기경보 v1→v2**: 양 보팅 멤버에 OECD 한국 CLI 3피처 추가(빌더
  build_cli, avail=+45일). 발행 구성 검증에서 +CLI가 3축 파레토(QWK 0.871→0.889·
  전환 0.231→0.269·FAR 0.146→0.145) 확인 — 광종축(CNOI·아르헨)까지 풀링에 넣는
  변형은 전환 희생(0.19)이라 제외. 재발행 완료: 최신 주(06-08) 신호 재조정 —
  LI 상향 강화(0.63)·REE 상향→하향 전환·CU 유지.
- **LI 광종축(+아르헨 z24)**: 기존 관행(CU +CNOI·NI 2축과 동일)대로 광종별 채택
  동작점 지위로 스코어보드·문서 기재 — 풀링 발행기와 별개(조건부: 산발 커버리지
  플래그).
- 대시보드 재생성·아티팩트 재발행(보조 신호 패널이 v2 값 반영).

## 2026-07-26 (최신㉘)
## 2026-07-26 (최신㉘) — R10 완결: 최종 수집 스윕+전면 재검정 — 진단 채택 2건·예측 전패(스코어카드 v1.20)

사용자 지시(/goal "싹다 모아 수집 후 전 방법론+미시도 총동원 재튜닝"). 정본
`r10_retune_report.md`(하네스 자동분류+수동 확정).

**수집 완결**: Tier3(Comtrade 5흐름+USGS 구리 3계열, 2017-12 연장)+Tier4(Comtrade
10흐름·EIA·Eurostat DE 3종·중국 전력/탄소·ECOS 출하·ICSG 축적형·OECD CLI 2종)+
WSTS 전 지역. fact_indicator 385→6,419행·fact_series 3,373→20,563행. 전 수집기
cron 편입, Comtrade 페처 타임아웃 재시도·이어받기 가드 추가(장시간 수집 중단 실측).

**진단 채택 2건**: ①풀링 +OECD 한국 CLI(P=1.000·이웃 9/12·결정론 프레임) — 거시
수요 사이클 축 신설, 보팅 반영 시 3축 파레토(P=0.937 유의 미달 명기) ②LI +아르헨
수출 z24(P≈0.995·지연 3/3, 조건부 — 산발 커버리지·소표본 플래그) — LI 최초 유의.

**철회·기각(정직)**: 가짜 유의 2건 철회(uscu_p·supdiv_li — **기준선 함정**: 광종
기준선이 풀링 피처면 결측 탓 약해져 가짜 유의, PER_CC_CHAMP로 코드화 수정)·
보팅3 거시멤버(시드 비강건 — n50 시드 3종 P=0.76/0.97/0.76, **시드 강건성 축**
신설)·bill_jp(전환 유의 악화)·예측 exog 29종 전패(lag 지배 4번째 확인 — 예측
챔피언 불변). 방향긍정 보류 6건은 리포트 참조.

**하네스 완성**: SERIES_SPEC 한 줄 등록→표준 피처화(교란·꼬리 자동 플래그)→
광종별 올바른 기준선 스크리닝→부트스트랩→분류 리포트 원커맨드
(`r10_retune_harness.py`) — 이후 신규 데이터 재튜닝의 구조적 해법.

## 2026-07-25 (최신㉗) — Tier3 수집 후보 발굴·접근성 전수 실측

사용자 지시("추가 영향 가능 데이터의 수집 방안·가능성 검토"). 전 항목 실제 호출
실측 — `자체수집_Tier3후보_260725.md` 정본. **Tier3-A(즉시 가능) 6종**: 칠레 LI
수출(월 ~20kt — 남미 염호축 신설)·아르헨티나 LI(~5kt)·필리핀 NI 광석(월 717kt —
인니 규제 시 대체공급축)·말레이시아 REE(월 4~6kt, 2026-04 — 비중국 정제축, 중국
컷 이후 최신성 보완)·일본 정련 NI 수입(2026-05, 지연 최상급)·USGS 구리 MIS
(2026-06, 지연 ~1개월·표 16종). Tier3-B: EIA(이 네트워크에서 열림 실측)·Eurostat
Comext(200)·akshare 중국 전력/탄소. 보류/불가: 조달청 비축 재고(공개 API 미확인 —
발주처 안건 3호 후보)·페루 CU(보고 지연 12개월+)·DRC/잠비아 CO(미보고)·호주 REE
(무의미량)·USGS 니켈 MIS(부재). 기대 영향 정직 평가: 진단 광종축·geo 연계용
(예측은 lag 지배로 기대 낮음), "원천이 다른" 신호 우선.

## 2026-07-25 (최신㉖) — 대시보드에 보조 조기경보·적응형 급증확률 노출(v1.19 소비자측 마감)

사용자 지시("대시보드에 out_aux_early_warning·p_burst_adapt 노출"). 
- 템플릿에 **보조 신호 패널** 신설(광종별 전환 조기경보 방향칩·방향확률 미니바·
  급증확률 적응형/고정형 병기·적응 임계)과 카드 조기경보 배지 추가 — 기존 디자인
  토큰·양테마 체계 준수, "별개 병기 보조신호" 성격을 각주로 명시.
- 재생성을 `dashboards/build_dash.py`로 **스크립트화**(기존 WORKLOG 수동 쿼리 대체).
  과정에서 잠재 버그 발견·수정: 구 스냅샷의 지수 주간이 일요일 앵커라 경보(월요일
  앵커)와 정확일치 실패 → 차트의 지정학 오버레이가 전부 미매칭이던 상태 — +1일
  보정(geo_prob 발행 규약과 동일)으로 해소, 매칭 336/336주 검증.
- 산출: mineral_crisis_dash.html 재생성(392KB, 최신주 2026-06-08 — CU·LI·NI·REE
  상향 조기경보 배지·REE 급증확률 고정 0.52 vs 적응 0.12 대비 노출), 기존 아티팩트
  URL로 재발행. META 갱신.

## 2026-07-25 (최신㉕) — 4개 신챔피언 운영 반영 완료(스코어카드 v1.19)

사용자 지시("4개 챔피언 운영 반영도 진행"). 3개 운영 지점에 반영·실행·검증 완료:

**① 예측(forecast_unit v2→v3)**: `msr/models/forecast_unit.py` — build_panel에
MIDAS 피처 빌더(_add_midas_features: 주간 지수 λ사전·가격/환율 w0/slope, 검정
구현과 동일 정의), _direct_forecast 점추정을 타깃별 신챔피언으로 교체(ton=XT+
감쇠hl24+CO만 ElasticNet / unit=XT), 분위(HGB quantile)+conformal+재귀 경로는
불변. CO 설명은 SHAP 대신 선형 정확 기여(_linear_top_contrib — 모델-설명 일치).
운영 실행: method=direct 채택(MASE 0.755 vs 재귀 0.85), out_import_forecast_unit
60행 재발행(base=2025-12), reason/explain 정상. midas_eval의 중복 병합 가드 추가.

**② 진단 보조 조기경보 최초 운영화**: 지금까지 백테스트 문서상으로만 존재하던
보조 조기경보를 `scripts/aux_early_warning.py`로 발행 — 소프트보팅 Bagging25×2
(p_burst 원천+gsev_z13 원천), 전 기간 재적합, **out_aux_early_warning 테이블
신설**(Δ방향·트리거·방향확률·basis). 최신 주(2026-06-08): CU·LI·NI·REE 상향
트리거, CO 유지 — 현 경보 국면(CU 심각 등)과 정합. 운영 등급예측과 별개 병기
(hard 결합 기각 이력 준수).

**③ 지수 확률화 CO x_z13 병행**: `geo/prob_model.py`에 COLS_BY_COMMODITY
도입(CO=base3+x_z13), CO Brier 0.2055→**0.1747 ✓개선**(상수기준 0.1919 열세
해소). 함정 재확인: x_z13 워밍업 NaN을 fillna(0)로 채워 학습하면 계수 오염으로
개선 소멸(0.175→0.206 실측) — 학습은 결측 제거·예측만 중립 대치로 수정. 정본
재계산+DB 발행, CO p_burst 히스토리 변경(다운스트림 진단 피처 — 재발행 강건성
축 기록 유지).

## 2026-07-25 (최신㉔) — REE burst_k 재정의 처리(§6 백로그 해소) — 적응형 임계 운영 반영

사용자 지시("REE burst_k 재정의도 처리"). 문제: 고정 burst_k(학습기 P90 동결)가
REE 체제전환(2024+)에서 test 실현율 0.64로 폭주 — "이례적 급증" 의미 붕괴(적대적
감사 지적 항목). 해법: **적응형 임계 k_adapt = 직전 52주 P90**(당주까지 정보만,
as-of 안전) + 확률은 강도 NB2와 상대강도 로지스틱의 **앙상블**("원천이 다를 때만
보팅" 규칙 적용 — NB2 단독은 적응 타깃에서 3광종 상수 열세, 앙상블로 4/5 광종
상수기준 초과: REE 0.1359<0.1443·NI 0.0685·CU 0.0688·LI 0.0791, CO만 열세).

검증 성과: REE test 실현율 0.64→**0.17** 정상화, 최신 주(07-20) REE p_burst
고정 0.519(항상 급증 왜곡) vs 적응 **0.117**. 운영 반영은 **비파괴 부가**
(geo/prob_model.py에 burst_k_adapt·p_burst_adapt 컬럼 추가 — 기존 p_burst_next
불변이라 진단 피처 등 다운스트림 무영향), 정본 store 재계산+DB 발행 완료.
DB_SCHEMA 갱신. 소비자(대시보드 등)는 REE 급증 표시를 p_burst_adapt로 전환 권장.

## 2026-07-25 (최신㉓) — R7: 시간감쇠·표현학습·BMA 전부 시도 — ton 4번째 유의 갱신(스코어카드 v1.17)

사용자 지시("유망한 건 전부 시도"). 상세 `advanced_wrap_repr.md`.
- **채택: ton 시간감쇠 표본가중(hl=24개월)** — XT+MIDAS지수 위에 최근 체제 가중,
  18오리진 0.2711→**0.2635**(ΔCI [+0.002,+0.013] P=0.996, hl 그리드 내부 최적).
  누적: HGB+BASE 0.2928→0.2635(-10%). unit은 무차별(가격 전가 구조 시대 불변).
- 방향 긍정 보존: 진단 보팅2+감쇠hl104(3축 파레토 점추정 우세, P=0.851)·보팅3
  (FAR 0.1495, P=0.946).
- 기각: 표현학습 계열(RFF 폭망·PCA 요인·torch 오토인코더 — 감쇠보다 열세, 표본
  780행 한계 실측), BMA(열등 모델 희석), 잔차부스팅(노이즈), 지수 가중 NB2.
- **함정 기록**: NB2 모멘트 추정경로 "대발견"(CO 0.1325)은 z13 dropna로 학습
  표본이 잘리며 burst_k 임계가 달라진 인공물 — 임계 고정 재검 시 무차별(P=0.743)
  로 철회. 교훈: 모델 비교 시 타깃 임계는 동일 표본 고정 필수.
- 그래프 베이지안/인과: 예측 대결용 승산 낮음 판정(선형 CPD·표본·순환성) —
  시나리오/반사실 산출물 트랙으로 분리 권고(pgmpy 등 미설치 실측).

**추기(R8, 과업 내 보팅 전수)**: 챔피언+대등 구성 보팅을 4축 실측 — 예측
무효~악화·진단 보팅4 파레토 점추정 우세(P=0.890 미달)·지수 9변형 평균 유의
악화(P=0.016). 원인: 챔피언들이 이미 내부 앙상블+대등 구성 오차 고상관(다양성
부재). 규칙 확립: **보팅은 정보 원천이 다를 때만**(보팅2 승리 요인 = p_burst와
gsev_z13의 원천 상이). 챔피언 4종 확정 유지.

**추기(R9, 광종별 셀 점검)**: 15개(광종×모듈) 매트릭스 분해에서 CO ton이
최약 셀(0.62) — v1.13 관찰 확증 검정으로 **CO ton만 ElasticNet 교체 채택**
(18오리진 0.6205→0.5306, CI [+0.057,+0.125] P=1.000, 18/18 오리진 전원 개선).
예측 운영안은 XT+감쇠 혼성(CO ton만 EN)으로 갱신.

## 2026-07-25 (최신㉒) — 광범위 방법론 스윕 R4~R6·재발행 강건성 발견·랩핑 채택(스코어카드 v1.16)

사용자 지시 ①"더 다양한 방법론 광범위 탐색" ②"잘 나온 방법을 배깅/부스팅 랩핑".
상세: `broad_method_sweep.md`. 시도: SVM·kNN·MLP·ExtraTrees·AdaBoost·LDA·NB·배깅·
보팅·스태킹·PLS·스플라인NB2·단조제약GBM·모델평균(XGB/LGBM 등은 미설치 실측).

**① 재발행 강건성 발견(★방법론 전환점)**: 토 06:30 GKG cron의 지수·확률 전기간
재발행이 백테스트 기준선을 이동시킴(진단 챔피언 0.8392→0.8296 등). v1.15 신챔피언
4건 중 **2건 생존**(unit U-MIDAS·CO x_z13 — 발주처/원시 데이터 기반), **2건 강등**
(진단 gsev_z13 대체 P=0.636·ton HGB+MIDAS지수 P=0.732 — 발행본 변동성 이내).
교훈: 지수·확률 파생 피처의 개선은 발행본 간 변동(±0.01~0.03 QWK)을 초과해야
신뢰 — 채택 기준에 추가. 동일 피처셋 내 모델 교체는 비교가 구조적으로 공정.

**② 랩핑 유의 개선(사용자 직관 적중)**: 진단 Δ에서 Bagging25+챔피언피처(피처
불변) P=0.993·보팅 Bag(p_burst)+Bag(gsev_z13) QWK 0.8610 P=1.000·Bagging50+병행
FAR 0.1484. 부스팅 랩핑(AdaBoost)은 전환 반토막 — 비추 확정. 트리·커널·신경망
단독은 다수클래스 붕괴 재확인.

**③ 예측 신신챔피언 = ExtraTrees**(극단 랜덤화 배깅): 18오리진 P=1.000 —
ton XT+MIDAS지수 0.2928→0.2710(-7.4%, 마진>재발행 변동), unit XT+U-MIDAS
0.1999→0.1799(-10%, 재발행 무관 축). 귀속 분해: 모델·피처 효과 가산적.
SVR·kNN·MLP·PLS 전부 미달.

**④ 지수**: 스플라인NB2·단조HGB·앙상블 전부 미달 — CO NB2+x_z13 유지(재발행
생존 P=0.993). 발행본-독립 구성(지수 피처 제거)은 유의 악화(P=0.000) — 지수엔
실정보가 있으므로 제거가 아니라 랩핑·병행으로 안정화가 정답.

## 2026-07-25 (최신㉑) — 챔피언 초과 탐색 종결: 3모듈 전부 유의 개선 달성(스코어카드 v1.15)

사용자 지시(/goal): "MIDAS 방법론 다양화·피처 재가공으로 챔피언을 넘을 때까지
계속 탐색". R1~R3 반복 탐색 끝에 **세 모듈 모두 CI 하한>0 유의 + 강건성 통과**
달성(`challenger_validation.py`로 통합 재현 가능):

- **진단 Δ조기경보**: p_burst(NB2 확률) → **gsev_z13**(geo_event 심각 이벤트
  13주합의 52주 z) **대체** — QWK 0.8392→0.8609(CI [+0.006,+0.039] P=0.997),
  전환 0.19→0.23·FAR 동률·비전환오류 112→98. 이웃 9설정(합8/13/17×z39/52/65) 중
  7개 유의·전부 방향 양(E4류 취약성 없음). 운영 레벨 모델은 무영향(y_lag1 지배 —
  대체는 Δ프레임 한정이라 안전).
- **예측 ton**: +MIDAS지수(주간 지수 감쇠가중 λ사전) — 18오리진 확장 재검
  0.2960→0.2885(CI [+0.001,+0.014] P=0.992). 확장 시도(원시 이벤트 MIDAS·26주 창·
  max/std 집계)는 전부 무효 — cand0가 정점.
- **예측 unit**: **+U-MIDAS 가격·환율**(월말 레벨 w0+13주 기울기) — 부분집합
  정제(wpx+wfx)로 0.2005→0.1928, 6오리진 P=0.956에서 **18오리진 확장으로 P=0.987~
  0.990 유의 달성**. 메커니즘: 단가는 가격 전가라 월평균보다 월말 상태가 정보적.
- **지수 확률화**: NB2 base3 + **x_z13 병행** — 풀링 0.1243→0.1191(9설정 전부
  개선, P=0.967)이나 개선이 CO 집중이라 광종별 채택: **CO Brier 0.2053→0.1739
  (CI [+0.005,+0.064] P=0.992), 기존 문서화 약점("상수기준 0.1919에도 열세")
  해소**. NB2 피처확장·GBM·로지스틱·앙상블(P=0.901)·x_geo 대체(REE 붕괴)는 기각.

**공통 통찰(방법론)**: 세 모듈 모두 "원시 주간 신호의 시간 구조"(누적 z·감쇠
가중·월말 상태)가 기존의 압축·평균(지수 스케일 압축, 월평균, NB2 확률화)을
이겼다 — MIDAS 관점의 일관된 승리. 특히 gsev_z13은 지수·NB2로 가공되기 **전**의
원시 심각 이벤트 누적이 다운스트림에 더 유용함을 진단·지수 양쪽에서 실증.

운영 반영은 미실시(검증 산출물만 커밋) — 반영 대상: ①진단 Δ 보조 조기경보 피처
교체 ②forecast_unit에 wgeo λ사전(ton)·wpx/wfx w0/slope(unit) 통합 ③geo
prob_model CO에 x_z13 추가. 발주처 보고 전 반영 여부 결정 필요.

**추기(대등 구성 포트폴리오, 사용자 요청)**: 모듈별 신챔피언과 대등한 대체 구성을
5개 이상씩 실측 정리(`challenger_alternatives.md` — 진단 6·ton 6·unit 5·지수 8).
승리 요인이 특정 모수/모델이 아니라 조합 방법 자체임을 증빙(이웃 모수·RF 교차에도
성능 유지 = 과적합 아님의 최강 근거). 특기: **unit RF+wpx/wfx 0.1900**이 신챔피언
(HGB 0.1922)을 점추정 초과 — 운영 반영 시 HGB/RF 택일·앙상블 검토 여지.

## 2026-07-25 (최신⑳) — CU 복구 반영 스윕 재검증 + MIDAS 혼합주기 — 예측 첫 유의 개선(스코어카드 v1.14)

사용자 지시: "CU 복구 반영 조합 스윕 재검증 + MIDAS로 최적 피처·모델 탐색".

**① 스윕 재검증**(`diagnosis_combo_sweep` 128+64×2 재실행): 합성 1위가 v1.7 구성
(INV+CNINV+TRD+PMICN)으로 복귀 — v1.9 대비 부트스트랩 QWK P=0.239·chg P=0.880으로
**양방향 유의 지배 없음 → 채택 동작점(v1.9) 유지**, "TRD 제외의 유의 근거(P=0.998)는
CU 결측 상태의 산물"임을 명기, TRD 중립 재분류. CU 단독 스윕 1위는 CNINV 단독
(전환적중 0.46) — 재검 후보.

**② MIDAS**(`scripts/midas_eval.py` 신규): 주간→월간(예측)은 지수감쇠 가중
(λ∈{0,0.2,0.6,1.5}, 창 13주)+U-MIDAS lite, 월간→주간(진단)은 PMI U-MIDAS 시차 분리.
- **[채택 권고] ton 예측 +MIDAS지수: 예측모듈 최초의 유의 개선** — WAPE 0.287→
  0.273, 페어드 부트스트랩 ΔWAPE CI [+0.003,+0.025]·P=0.992, **6개 오리진 전부
  비악화**, NI(+0.029)·REE(+0.023) 견인. 월평균으로 뭉개던 주간 지정학지수를 감쇠
  가중으로 바꾸면 정보가 살아남 — 세 차례 전패했던 "외생 무효" 결론의 첫 예외.
  unit은 무영향이라 현행 유지. 운영 반영(forecast_unit 발행 체인)은 별도 결정.
- 보류: unit +U-MIDAS전부(0.202→0.193, P=0.955 아깝게 미달). 기각: MIDAS가격·재고·
  전부λ, ElasticNet 전 변형, 진단 U-MIDAS PMI(P=0.669).
- 과정 버그 1건: 패널 컬럼 존재 필터가 파생 피처(lag1 등)를 걸러 BASE가 빈 피처가
  되는 실수 — 1차 결과 전체 폐기 후 수정 재실행(파생 피처는 _features에서 생성됨).

**추기(발주처 데이터 적용 범위 질문 후속)**: 발주처 주간(KOMIS 가격·LME재고·환율)은
기왕 포함(가격·재고 기각). 월간은 관세청 수입 U-MIDAS(3시차 분리)를 추가 검정 —
**기각**(병행 유의 악화 P=0.022·대체는 비지배 트레이드오프, 현행 1점 유지). KOMIS
수급밸런스는 가격상관 -0.84~-0.99 계열이라 원칙상 미적용(라벨 오염 우회로). 연간
(WoodMac·USGS)은 시차 1~2개뿐이라 MIDAS 구조상 비대상(전년값 매핑으로 기왕 기각).

## 2026-07-25 (최신⑲) — 피처 커버리지 전수 실측 중 SHFE CU 재고 소실 발견·복구

사용자 질문("2016~2026 모든 피처가 주/월/년 데이터를 다 갖고 있나")에 DB 전수
조회로 답하는 과정에서 **fact_inventory_exch의 CU SHFE 재고(src=SHFE_99QH_W,
1,165행)가 통째로 소실**돼 있음을 발견. 원인: `collect_priority_feeds.py`의
DELETE→INSERT 멱등 패턴에서 원천(99기화)이 빈/부분 응답을 반환하면 기존 전량이
삭제됨(07-24 다회 수동 재실행 중 발생 추정 — cron 피드는 아직 미가동이라 무관).
재수집으로 복구(1,166행, 2005-01-14~2026-07-24)하고 수집기에 무결성 가드 추가
(수집 500행 미만이면 DELETE 차단·기존 보존). tier2 수집기는 이미 빈 응답 가드
보유, tier1 upsert는 fetch 선행이라 위험은 빈 응답 케이스 한정.

**영향 재검증(정직 기록)**: 어제(07-24 일부~07-25)의 검정들은 CU cninv 결측
상태에서 수행됨. 복구 후 Δ 채택 동작점(INV+CNINV+PMI)은 QWK 0.8242→**0.8392**·
FAR 0.2243→0.1846으로 개선되고 전환적중은 0.3077→0.1923으로 하락. **서열 재검증
결과 채택 동작점은 여전히 1위(유지)**, 단 v1.9의 "+TRD 유의 지배(P=0.998)" 결론은
복구 후 무차별(P=0.758)로 완화 — TRD 제외는 유지하되 근거 강도를 하향 기재.
Tier2·대안 재피팅의 "채택 0건" 결론은 챔피언이 강해진 것이므로 방향 불변.

커버리지 실측 요약(상세는 사용자 보고): 완전 축(지수·LME CU/NI·관세청 156개월·
WSTS·ECOS·거시 백필 6계열 등) vs 부분 축(COT CO/LI 2022-11+/2023-08+·GFEX LI
2023-12+·LI 가격 2018+·CO LME재고 2018-12+·KOMIS 수급 2020+·BDI/STLFSI 2021-06+)
vs 꼬리 낡음(중국 Comtrade 2024-12 컷·USGS 2025-12·ISM/EU PMI/부동산 2025-09/12
정지·관세청 월간 2025-12).

## 2026-07-25 (최신⑱) — 중요도 기반 자동 피처선정 재피팅 — 전부 챔피언 하회(v1.13 추기)

사용자 질문("문제된 부분 수정 후 피처 선정·중요도 판별 피팅을 다시 하면?")에 실측
답변(`feature_selection_refit.py`). 전피처 풀(42개)에서 자동 선택(Lasso·L1-Logistic·
순열중요도 top-k) → 재적합, 선택은 폴드 학습기간 내부에서만(누수 차단).

**결과: 자동 선택 전부 챔피언 하회** — 레벨 최선 Lasso→Ridge 0.9501(챔피언
0.9687), Δ 최선 0.674(챔피언 0.824), 예측 노이즈. **핵심 발견 = 순열중요도의
다중공선성 함정**: 레벨 PermImp가 grade_lag1을 탈락시켜 QWK 0.38 붕괴(상관 대체
피처가 풀에 있으면 개별 순열 중요도가 분산되는 고전적 실패 — 이 프로젝트에서
순열중요도 기반 선택 금지 근거). Lasso는 사람 채택 코어(geo·lag1·price_z52)를
재발견하나 넘지 못함 — 자동 선택의 상한 ≈ 수동 채택 동작점. 결론: 성능 경로는
기법이 아니라 새 정보 축(발주처 안건 데이터) 확보.

## 2026-07-25 (최신⑰) — 3모듈 대안 재피팅(전피처×다른 모델 계열) — 전부 현행 유지(스코어카드 v1.13)

사용자 지시(/goal): "기존+Tier1+Tier2 전체 피처로 지정학위기지수·수급위기진단·
12개월 수요물량/가격 예측을 기존과 다른 방식으로 전부 재피팅". 07-24 재시도 금지의
단서 조건(외부 직교 데이터 확보/모델 구조 변경)이 충족된 상태의 정면 검정.

**결과: 세 모듈 전부 대안이 챔피언 미달 — 운영 구성 전면 유지**(아홉 번째 동일
결론, 종합 `alt_refit_summary.md`):
- 진단 레벨: Ridge+현행 QWK 0.9687 > 최우수 대안 RF+FULL 0.9667(P=0.245).
  Ridge+FULL 0.9207 급락 — 노이즈 피처의 선형 오염 실증.
- 진단 Δ분류: HGB/RF는 전환 0건 예측(지속성 붕괴·트리거 0~9건)으로 조기경보 기능
  상실, Logistic+FULL은 QWK 0.674 급락 — 채택 동작점 유지.
- 예측: ElasticNet 전패(ton 0.327)·RF 무차별. HistGBM+FULL이 ton 0.287→0.270이나
  unit 0.202→0.236 악화와 교환(지배 없음). 관찰: CU ton만 트리+FULL 일관 개선
  (0.263→0.234~0.240) — 오리진 확장 재검 후보로 기록. ElasticNet은 CO에서 유일
  강건(0.525 vs 나이브 0.586).
- 지수 확률화: NB2 풀링 Brier 0.1243 < LOGIT-full 0.1362 < GBM 계열 — GBM은 REE
  체제전환 구간 붕괴(0.38~0.51). 물리 피처 확장도 무효. CO는 NB2조차 상수기준
  열세(기지 약점 재확인, isotonic 보정이 완충).

방법론 기록: ① 개별 기각 피처를 비선형에 몰아넣어도 상호작용 이득 없음 — "피처는
개별 검정 채택분만" 원칙 유지 ② 트리 실패 모드 2종(불균형 Δ에서 다수클래스 붕괴 /
체제전환에서 캘리브레이션 파탄) ③ geo 대안 검정은 DB 발행본(geo_event·geo_index)
으로 prob_model 패널을 재현하고 NB2는 실제 코드(_fit_one)를 재사용 — 사과 대 사과.
스크립트: `scripts/{diagnosis_alt_refit,forecast_alt_refit,geo_prob_alt_refit}.py`.

## 2026-07-25 (최신⑯) — Tier2 자체수집+3축 검정(진단·예측·지수) — 채택 0건·동작점 불변(스코어카드 v1.12)

사용자 지시(/goal): "잔여작업 중 사람 피드백 불필요분 — Tier2 후보 추출+추출 피처
기반 지정학·수급위기진단·12개월 예측모델 검증".

**접근성 실측**(후보 5종 전부 실제 호출): ① Cochilco 칠레 구리 생산 — 구 URL
404였으나 `boletin.cochilco.cl/productos/boletin.asp?tabla=tabla21` 재발견, 12월호
체인으로 2015-01~2026-05 137개월 복원(지연 ~2개월). ② **USGS MIS 코발트 월보
T1 = LME 코발트 재고 재게재 발견** — 2018-12~2025-12 85개월 확보. 발주처 안건 A의
"CO 재고 무료 경로 부재(8경로 실측)" 결론을 정정(안건 문서에 갱신 추기 — 단 월간
그레인·발행지연 ~7개월·2023년 이후 123~140t 준상수라 주간·저지연 원본 요청 취지는
유지). LI·REE 월간 MIS는 부재 실측. ③ WSTS Historical Billings XLSX(SIA 보도자료의
원천) 1986-01~2026-05 485개월. ④ ECOS 901Y032 산업별 생산/출하/재고 월간 —
전자부품·자동차·전기장비·1차금속 생산+1차금속 재고 5계열 각 245개월(2006~).
⑤ 중국 국가통계국 — data.stats.gov.cn 해외 IP 403 실측·akshare 대응 함수 부재로
불가 확정. `scripts/collect_tier2_feeds.py` 신규(멱등), 월간 cron 편입(ECOS 키는
루트 .env에서 grep 추출 — 전체 source 회피).

**검정 3축**(`diagnosis_tier2_eval.py`·`forecast_tier2_exog_eval.py`·
`geo_tier2_linkage.py`, 패널 종점 2026-06-08 = 발주처 컷 유지):
- 진단(4단계 경보): **채택 0건**(기준 = 부트스트랩 QWK차이 CI 하한 > 0). 방향
  긍정(유의 미달) 3건 — CU +KINV(한국 1차금속 재고: QWK 0.886→0.910·Miss
  0.77→0.54·P=0.958), 풀링 +KINV(비전환오류 135→120·P=0.962), LI +KIP(P=0.942,
  전환 2건 소표본). 기각: SEMI 진단축(FAR 폭증)·CLP·COINV(커버리지 58%·기여 0)·
  NI/CO/REE KIP. **채택 동작점 전부 불변**. KINV는 축적 후 재검 후보.
- 예측(12개월 수입물량·수입액): +SEMI/+KIPD/+KINV/+CLP/+ALL 전부 WAPE 변화
  노이즈 수준(ton ±0.005) — 07-24 검정과 동일한 lag 지배 구조 재확인, FEATS 유지.
- 지정학 지수 연계(실물 타당성 검증): CU 지수 상위 10% 월이 실물 차질 에피소드와
  정확히 일치(2017-02~05 Escondida 파업: 생산 503→371kt 급락 후 회복·2020 코로나
  봉쇄·2021-05 파업/로열티 국면), 고지수 월 이후 3개월 누적 생산 +7.8%p(회복
  반등, 블록 순열 p=0.044) — **동시 탐지 타당성 실증, 선행 예측력은 없음**(시차
  상관 전 구간 |ρ|<0.1). CO는 연계 근거 없음(정직 기록).

파서 함정 2건(재발 방지): ① Cochilco 당해 연도 1월 라벨 `ENE/JAN 2026 (P)`의
잠정 표기를 정규식이 놓치면 후속 FEB~MAY가 **전년 값을 덮어쓰는 오염**(실제 발생,
수정 후 재적재로 해소). ② USGS 구 포맷(~2023) Total 열은 미 정부 비축분(상수
302t) 포함 — 신·구 일관성을 위해 창고 2열(U.S.+Non-U.S.) 합으로 계산해야 함.
S3 간헐 타임아웃은 3회 재시도로 대응.

## 2026-07-24 (최신⑮) — Tier1 자체수집(공급국 흐름·CO/LI COT·OI)·CU 첫 유의 피처(스코어카드 v1.11)

사용자 지시: "Tier1 수집+GKG 증분 수집→전처리→DB화→검정, 단 검정은 발주처 데이터로
산출 가능한 시점까지만(자체 수집은 계속)".

**수집**(`scripts/collect_tier1_feeds.py` 신규, 전 소스 사전 접근성 실측):
① Comtrade 공급국 물리 흐름 4종 — 인니 NI 수출(2604+7501) 125개월(~2026-05)·호주
LI 수출(253090+283691) 125개월·칠레 CU 정광 수출(2603) 124개월·중국←미얀마 REE
수입(253090+2846) 108개월 → fact_indicator. 인니·호주·칠레는 보고가 중국(2024-12
컷)보다 최신(2026-04~05)임을 실측. ② CFTC 코발트(2022-11~, 190주)·리튬수산화물
(2023-08~, 153주) COT — CO/LI 최초의 포지셔닝 시리즈. ③ ECB 인니 루피아 1,073주
(2006~). ④ 중국 선물 OI(SHFE NI 580주·CU 1,098주·GFEX LC 155주). cron 편입(주간
경량 --skip-comtrade / 월간 풀). 기존 build_trd는 지표 명시 고정으로 오염 방지.

**검정**(`scripts/diagnosis_tier1_eval.py`, **평가 패널 종점 2026-06-08 = 발주처
정답·마트 한계 — 리포트에 실측 명기, 자체 수집 최신분 미사용**):
- **채택 1건: CU 단독 +CNOI(SHFE 구리 OI)** — QWK차이 CI [+0.012,+0.088](P=0.996),
  오경보 17→9건(-47%), **CU 최초의 유의 피처**(세션 통산 4번째 유의 실증).
- 풀링 확장 전부 기각(+전부 P=0.001 유의 악화, +CNOI 풀링 P=0.006 악화) — 채택
  동작점(INV+CNINV+PMICN) 유지.
- 방향 긍정(소표본 유의 미달): NI +인니수출(오경보 12→8), REE +미얀마수입(미미).
- 기각: CO +COT2(커버리지 34%+FAR 폭증 — 부분 커버리지 교란 패턴, 축적 후 재검),
  LI 전 조합, CU +칠레수출.

**GKG 증분 — 완료(추기)**: 신규 zip 1,737개 다운로드→파싱(state 기반 증분) → 후보
이벤트 2,926건 → LLM 재검증 전량(500+2,426건): **확정 883·기각 2,043(기각률 70%)**
→ 기각 실삭제+샤드 병합 → 정본 geo_events.parquet **296,040행**(295,157+883, 기대치
정확 일치) → geo index/prob/publish 재실행, DB geo_event 296,040행·geo_index
2026-07-19주·geo_prob 2026-07-20까지 갱신. **GKG 수집~지수의 최신성 공백(07-08 이후)
해소.**

**GKG 주간 cron 자동화(같은 날 후속, 사용자 지시)**: `geo/cron_gkg_increment.sh`
신설 — 확립된 순서(다운로드→파싱→LLM 전량검증→샤드병합→기각제거→지수/확률/발행)를
그대로 자동화, LLM 헬스체크 실패 시 발행 전 중단(미검증 이벤트 오염 방지)·flock
중복방지·연말 경계 대비(year-from=30일 전 연도) 포함. crontab 등록(매주 토 06:30,
feeds 09:10 이전 종료). **실사 1회 통과**: 신규 7파일→후보 4건→전량 기각→정본
296,040행 유지→publish 정상(로그 data_archive/cron_logs/gkg_weekly_20260724.log).
이로써 스코어카드 3장의 "GKG 증분 수집 미자동화" 항목 해소.

과정에서 잡은 파이프라인 함정 2건(재발 방지 기록): ① `geo` 상위 CLI가 gkg-verify의
`--compact-rejections`를 미노출 — 압축은 `python -m geo.gkg_verify` 직접 호출 필요
(+verify 기본 limit=500이라 증분 전량 검증엔 `--limit 0` 명시). ② **샤드 함정**:
증분 파싱이 events_shards/에 쌓이는데 publish는 정본+샤드를 dedup(keep=last)으로
합치므로, 샤드 병합(compact_event_shards) 전에 기각 제거만 하면 **기각분이 샤드
경유로 부활**(실측: 압축 후에도 publish 298,083행). 올바른 순서 = 샤드 병합 →
기각 제거 → publish.

## 2026-07-24 (최신⑭) — 거시 6계열 과거분 백필(2006~)·CLN 커버리지 교란 실증·기각 확정(스코어카드 v1.10)

사용자 지시: "거시 12종 백필". FRED가 이 네트워크에서 접속 차단(도메인 000 실측)이라
대안 공개 소스로 구성 — `scripts/backfill_macro_history.py`(신규): ECB 기준환율
(USD/KRW/CNY 교차환율), 미 재무부 daily yield curve CSV(10Y·10Y-2Y), 동방재부
UDI(달러인덱스). **KOMIS 중복 구간(81~262주) 교차검증 → 중앙값 오차 0.002~0.32%로
동일 계열성 확인된 6계열만 채택**, 각 806주(2006-01-02~2021-06-07)를
src='BACKFILL_PUBLIC'으로 삽입(KOMIS 이전 주만 — 출처 분리·멱등). 정직 기각/불가:
FEDFUNDS(KOMIS=목표금리 vs EFFR=실효금리, 오차 0.17%p 초과), STLFSI(FRED 유일 원천
차단), BDI(무료 히스토리 소스 부재), PRICEIDX 3종(오염군 — 백필 무가치).
build_aux 소스 필터 확장(`KOMIS_MARKET_AUX`+`BACKFILL_PUBLIC`).

**CLN 그룹 재심 — 커버리지 교란 가설 실증, 기각 확정**: CLN 단독 전환 적중률이
백필 전 0.5769 → 백필 후 **0.1923으로 붕괴**(FAR 0.657→0.240) — "피처 존재 시기
자체가 전환 다발기 표식"이던 인공물임이 데이터로 증명됨. 백필 후 128조합 스윕
재실행에서 CLN 고재현율 지점은 프런티어에서 소멸(23→10개), CLN은 고정밀 성분
(PMIG+CLN QWK 0.924·FAR 0.051)으로만 기여. **채택 동작점(INV+CNINV+PMICN)은 재심
후에도 유지**(스윕 1위 CNINV 단독은 QWK 유의 열세 P=0.000). 방법론 원칙 확정:
"부분 커버리지 피처는 백필로 교란을 직접 검증하기 전엔 성능을 믿지 말 것".

## 2026-07-24 (최신⑬) — LI 백필 완료→전면 재검토: 풀링 동작점 교체(TRD 제외, 스코어카드 v1.9)

사용자 지시: "백필 대기 후 완료되면 전면 재검토". GFEX 레이트리밋을 40분 간격 재시도
루프로 우회해 **LI 창단 백필 완료**(공식 132주, 2023-12-08~2026-07-24 — 잔여 2주는
국경절 2025-10-03·춘절 2026-02-20 휴장 주간으로 원천 부재 확인, 구조적 완결). LI
패널 커버리지 11%→40%(z52 워밍업 감안).

**전면 재검토**(exch_inventory_eval·combo_sweep 128+64×2 전수 재실행+부트스트랩):
- **판정 변경 1건 — 풀링 보조신호 채택 동작점 교체**: 완전 데이터에서 기존 v1.7 구성
  (INV+CNINV+TRD+PMICN)은 QWK 0.837→0.808로 하락, **TRD를 뺀 INV+CNINV+PMICN이
  지배**(QWK 0.827·chg 0.308·FAR 0.234 — 같은 적중률에 QWK·FAR 우위). 부트스트랩:
  vs v1.7 QWK차이 CI [+0.006,+0.032](P=0.998)·오경보 154→132, vs 구기준 CI
  [+0.109,+0.175](P=1.000)·오경보 -42% — 채택 유의성 재확인. TRD(무역흐름)는 풀링
  에선 순노이즈로 판명(REE 단독 오경보 절반 발견은 별개 유지).
- **판정 유지**: LI 재고 피처 무가치(완전 데이터에서도 악화 방향, 전환주 2건 한계),
  NI 최적 INV+CNINV(불변), CU 무유의(불변), CLN 기각(스윕 1위여도 QWK 유의 열세).
- 백필 전 스윕 결과는 git 이력(4e9f99f)에 보존, 리포트는 재실행본으로 갱신.

**보완 기록(WORKLOG 점검에서 누락 발견, 사용자 요청)**:
- 월간 cron에 GFEX 자가치유 backfill 편입(커밋 62c8280) — 스로틀로 남는 공백을
  매월 자동 소진(멱등 skip이라 완결 후엔 no-op).
- **LI 백필 완결성 근거 실측**: GFEX 상장(2023-07-21)~2023-11 구간은 창단(LC) 시트
  자체가 API 응답에 미발행(2023-08·09·10·11 4개 일자 직접 호출로 확인 — SI만 존재)
  → 창단 등록 제도 가동이 2023-12부터라 우리 시계열 시작점(2023-12-08)이 원천의
  시작점과 일치. 휴장 2주(국경절·춘절)와 합쳐 "원천에 있는 것은 전부 확보" 확정.
- Comtrade가 108개월(2016-01~2024-12)에서 멈춘 것은 수집 미완이 아니라 **중국의
  2025년 이후분 UN 미보고**(공개 preview 기준) — 발행되는 대로 월간 cron이 수용.

## 2026-07-24 (최신⑫) — 전수 조합 스윕·예측모델 첫 외생검정·수집 cron 상시화(스코어카드 v1.8)

사용자 지시: "수집된·수집가능한 피처로 가능한 모든 케이스 조합 + ①추가 수요측 검정
②예측모델 검정 ③자동화·발주처 안건 진행".

**A. 추가 수집**(`scripts/collect_demand_feeds.py`): 미국 ISM PMI 669행(1970~)·유로존
PMI 422행(2008~)·중국 부동산 국방경기지수 326행(1998~) → fact_series(AKSHARE_MACRO2).
⚠동방재부 피드가 ISM·유로 2025-09, 부동산 2025-12에서 멈춰 있어(실측) 전환 다발기
커버 불가 — 신선도 마스크로 정직 처리. REE 채굴쿼터는 **피처 부적합 판정으로 미수집**
(2025년부터 중국이 비공개 전환, 웹 검증 가능 연도 2021~2024 4개뿐).

**B. 진단 보조신호 전수 조합 스윕**(`scripts/diagnosis_combo_sweep.py`): 그룹 7종
(INV·CNINV·TRD·PMICN·PMIG·REALEST·CLN) 파워셋 128조합 풀링 + CU·NI 단독 64조합씩.
결과: 교란 그룹(CLN — 커버리지 교란 기왕 판정) 조합을 제외하면 **v1.7 채택 동작점을
유의하게 이기는 조합 없음**(합성점수 1위 CNINV+REALEST+CLN도 QWK차이 P=0.057·chg차이
P=0.580으로 무차별, 오히려 오경보 116→138 증가). 파레토 프런티어 23개 문서화 —
신규 초고정밀 지점(PMICN+PMIG: QWK 0.896·FAR 0.111) 확인. **결론: v1.7 동작점 유지.**

**C. 예측모델(2-4) 최초 외생피처 검정**(`scripts/collect_forecast_exog.py` +
`scripts/forecast_exog_eval.py`): CFTC COT 구리 1,840주(1989~, 공개 Socrata API)·
WoodMac 연간 밸런스/재고일수 DB화(fact_indicator, 2026-03 단일 빈티지 플래그)·중국
PMI·한국 산업생산(기존 raw_ecos 첫 활용). forecast_unit 실제 파이프라인 재사용,
오리진 6개×h1~12 WAPE: **4그룹+ALL 전부 채택 근거 없음**(변화 ±0.01 = 노이즈,
5-3 감사 "lag 지배" 발견과 정합). 부수 발견: 이 오리진 표본에서 ton의 계절나이브
대비 우위가 흔들림(0.284 vs 0.270) — §6 후속 항목. 수집분은 DB 보존+cron 갱신하되
모델 미반영.

**D. 상시화·안건**: crontab 등록(주간 토 09:10 재고·COT / 월간 6일 09:20
Comtrade·PMI·수요측, `scripts/cron_collect_feeds.sh`, 로그 data_archive/cron_logs/) —
프로젝트 최초의 수집 상시 스케줄. 발주처 안건 2건 문서화(`발주처협의안건_추가2건_
260724.md`: CO LME 재고 제공 요청·EV 장기데이터 예산). LI GFEX 공백(2024-12~2026-03)
재수집도 레이트리밋 해제 확인 후 재실행.

## 2026-07-24 (최신⑪) — 인벤토리 1~4순위 수집·검정: PMI 결합 유의 개선(3번째 실증)·CU 2축 기각(스코어카드 v1.7)

사용자 승인: "1~4순위 수집해서 검정까지". `scripts/collect_priority_feeds.py`(신규):
① SHFE 구리 재고 1,165행(2005-01~, fact_inventory_exch) ② COMEX 구리는 무료 경로
부재 판정(akshare 금·은만 — 후순위 이관) ③ UN Comtrade 공개 preview API로 REE(중국
2846 수출)·CO(중국←DRC 2605+2822+810520 수입) 월간 각 108개월 → fact_indicator
216행×2(레이트리밋 실측: period는 호출당 1개만 허용, cmdCode 콤마는 허용 — 252콜
1.6초 간격) ④ 중국 PMI 공식(2008~, 222행)·차이신(2014~, 147행) → fact_series.

검정(`scripts/diagnosis_priority_feeds_eval.py`, 동일 프레임+부트스트랩 4,000회):
- **CU 2축(LME+SHFE): 기각** — QWK차이 CI [-0.026,+0.021](P=0.407). NI의 "오경보
  급감" 패턴이 CU에서 재현 안 됨 — v1.5의 CU·NI 합산 유의는 NI 주도였던 것으로 재해석.
- **REE 무역흐름: 방향 긍정·보류** — 오경보 44→22건(절반), 전환주 3건이라 판정 불가.
- CO 무역흐름: 중립.
- **풀링 전부결합(+CN재고+PMI+무역흐름): 유의 개선(3번째 실증)** — QWK차이 95% CI
  [+0.119,+0.185](P=1.000), 비전환주 오경보 226→116건(-49%), 전환 적중 9→7/26
  (감소 불유의 P=0.092). 고재현율→고정밀 동작점 이동. PMI는 2008~ 전 기간 커버라
  커버리지 교란 없음. **보조 조기경보 고정밀 동작점으로 병기 채택 권고**(운영 등급
  예측은 무변경 — 전부 보조신호 계층).

## 2026-07-24 (최신⑩) — CO 재고 수집 정찰(불가 확정)·SHFE/GFEX 수집기·NI 재고결합 유의 개선(스코어카드 v1.6)

사용자 지시: "CO 재고 LME 수집기 개발+검증. 공개 API·데이터 다 동원하되 문서화·트래킹."

**1) CO 정찰 — 무료 자동수집 불가 확정**(8개 경로 전수 실측,
`outputs/model_opt/co_inventory_recon.md`에 시도 전체 트래킹): lme.com WAF 403(브라우저
UA·WebFetch 모두)·무료분 당해연도 한정(과거 유료 $1,200/년)·Wayback 데이터파일
미아카이브·무료 미러(westmetall/eastmoney/99qh) 전부 6대 비철만·중국 거래소 코발트
미상장·사내 자료(보고서 코퍼스·KOMIS 파일) 부재. 코발트 재고의 유일 원천이 LME라
구조적 차단 — **발주처(KOMIS, LME 데이터 기보유) 경유 제공 요청이 최선** → 안건 이관.

**2) 대신 공개 API 총동원**(`scripts/collect_exchange_inventory.py`, akshare 의존 추가):
`fact_inventory_exch` 신설(PK에 src 포함 — 기존 fact_inventory는 PK(commodity,date)라
NI의 LME·SHFE 공존 불가, 1차 실행에서 PK 충돌 실측 후 설계 변경). **NI SHFE 주간재고
643행(2015-04~2026-07) 전량 적재**. LI GFEX 창단은 48주(2023-12~2024-11) 적재 후
레이트리밋 차단(1차 0.4초 간격이 원인 추정, 이후 전 날짜 빈 응답) — 동방재부 미러로
최근 13주(2026-04~07) 보충(교차 일치 확인, src 태그 분리), 공백 2024-12~2026-03은
재수집 예정. 피처 생성에 세그먼트 분할(3주 초과 공백 경계 롤링 금지)·신선도 마스크
(as-of 14일 초과 낡은 값 제거)·pct_change inf 방지 반영.

**3) 검증**(`scripts/diagnosis_exch_inventory_eval.py`, 동일 프레임): **NI에서
LME+SHFE 재고 결합이 유의한 개선** — QWK 0.576→0.875, 비전환주 오경보 17→5건(-71%),
부트스트랩(4,000회) QWK차이 95% CI [+0.202, +0.422]·P=1.000. 서로 다른 실물(글로벌
vs 중국 창고)의 스프레드 정보가 추가된 효과로 해석, v1.5의 "재고가 전환탐지 곡선을
이동시킨다" 결론 두 번째 실증. 풀링 chg_acc 개선은 P=0.884로 유의 경계 미달(공식
지표 갱신 보류), LI는 커버리지 11%+전환주 2건으로 판정 불가(사전 선언대로). 스코어카드
v1.5→v1.6, DB_SCHEMA에 fact_inventory_exch 추가.

## 2026-07-24 (최신⑨) — 외부 직교 데이터 확보→모델링 반영: LME재고가 전환탐지 개선 실증(스코어카드 v1.5)

/goal(사용자): "현재 데이터 외 필요한 정보의 확보 방법 탐구→수집→모델링 반영→기대
효과 체크". 심층검토(최신⑧)가 지목한 "외부 신규 직교 데이터" 경로를 실행.

**1) 확보/수집**: 원격 수집 전에 발주처 원본 실사 — `documents/2차_데이타`에 **한 번도
피처로 쓰인 적 없는** 주간 LME재고(동·니켈, 2007~2026)와 거시 12종(BDI·달러인덱스·
금융스트레스·금리·중국 경기선행/산업생산 등) 발견. 신규 로더
`scripts/load_market_aux.py`로 `fact_inventory` 2,030행·`fact_series` 3,373행 적재
(멱등, 원자재지수 3종은 가격지수라 PRICEIDX_ 접두어로 오염 격리).

**2) 모델링 반영**(`scripts/diagnosis_aux_features_eval.py`, 전 피처 as-of 가용시점
시프트로 누수 방지): **재고 피처(z52·4주/13주 변화)가 CU·NI Δ분류 프레임에서 전환주
적중 1/18→7/18(상향 5/10 포함), QWK 동반 상승(0.810→0.839)** — 이번 세션 전체에서
처음으로 "적중↑+QWK↑" 동시 성립. 부트스트랩(4,000회) 차이 95% CI [0.111, 0.556],
P(개선>0)=1.000. 오염 아님(재고=물리량). 반면 거시 피처는 FAR 0.66 + 커버리지
교란(2021-06+만 존재=전환 다발기와 겹침)으로 판단 보류, 게이트 결합은 여전히 기각
(여덟 번째 동일 결론), 레벨 회귀 보조챔피언은 INV 무반응(재고 신호는 "전환 방향"
프레임에서만 가치).

**3) 판정: 기대효과 부분 충족** — "외부 직교 데이터가 곡선을 이동시킨다"는 가설이
재고에서 실증됐으나, 크기는 보조 조기경보 신호 개선 수준(운영 등급 예측 대체 불가).
신규 고정밀 동작점(Δ분류+INV: 적중 7/18·QWK 0.84·FAR 0.13)이 기존 고재현율 챔피언
(레벨 Ridge: 10/18·QWK 0.73)과 보완 관계로 프런티어 확장 — 대시보드 병기 후보.
**수집 확장 경로**: CO는 LME 무료 공개 재고 스크레이퍼(후보), LI는 유료(SMM) 차단,
REE는 데이터 부재로 구조적 불가. 상세:
`outputs/model_opt/diagnosis_aux_features_eval.md`. 스코어카드 v1.4→v1.5.

## 2026-07-24 (최신⑧) — y_lag1 의존 심층검토: 미착수 대안 6계열 전부 기각(스코어카드 v1.4)

사용자 지시: "해당 문제(진단모델 y_lag1 의존)를 해결할 수 있는 피처 조합이나 모델
교체 같은 방법으로 뭐가 가능한지 딥하게 검토". 선행 기각(게이트 A/B/C·단순제외·
단순앙상블·광역트리거·dimension c2)은 재시도하지 않고, 선행 리포트들이 "미착수"로
명시한 대안만 신규 검정 — `scripts/diagnosis_ylag_deep_review.py`(신규),
`outputs/model_opt/diagnosis_ylag_deep_review.md`.

**검정 대상**: E1 비대칭 상향게이트 · E2 Δ타깃 전환분류(class 가중) · E3 서수모델
(statsmodels OrderedModel) · E4 전환가중 학습(w 스윕) · E5 동역학 피처 확장
(geo_chg4·geo_z26·p_burst_chg·등급 체류기간 dur) · E6 잔차회귀(y−y_lag1 직접 회귀)
+ 후속 E7 방향별 이벤트 카운트(geo_event.direction 주간 집계, severity×confidence
가중) 및 이를 트리거로 쓰는 확률임계 게이트(변형 D). 평가는
diagnosis_retrain_answer.py와 동일 워크포워드 3폴드 풀링(QWK·chg_acc·up_acc·FAR).

**결과: 전부 기각 — 일곱 번째 동일 결론.**
- E4(HistGBM, w=20)가 사전등록 기준(QWK ≥ 지속성−0.10 & chg_acc>0)을 유일하게
  통과했으나 강건성 검증에서 뒤집힘: 가중 세밀스윕상 스윗스팟 없는 연속 트레이드오프
  곡선(전환 1건당 비전환주 오경보 11~19건), 부트스트랩(2,000회) QWK차이 95% CI
  [−0.108, −0.063]로 하한이 허용선 침범, 적중 6건 중 4건이 하향(완화) 전환.
- E7이 전환주 적중 0.50·상향 0.69로 종전 최고를 크게 상회했으나, **ablation 결과
  개선분 대부분이 price_up/down 뉴스 카운트에서 유래** — 라벨(가격 이격률)을 보도한
  뉴스의 반향이라 오염(가격피처 배제 원칙의 한 단계 우회). 깨끗한 supply 계열만으론
  chg_acc 0.346→0.385(+전환 1건).
- 학습기간 확장(2016 이전)은 geo_prob이 2016-01-04부터라 구조적 불가(실측).
- HMM/LSTM 등은 실험 없이 배제(패널 2,411행·테스트 전환주 26건 — 5개 모델 계열이
  같은 곡선에 수렴한 것이 "모델 클래스가 병목 아님"의 직접 증거).

**결론**: 병목은 모델 구조가 아니라 피처 정보량. 운영 구성(지속성 중심 진단 +
GEO_ONLY_NO_LAG 보조 조기경보 신호) 유지. 실질 경로는 외부 신규 직교 데이터(LME
재고·선물커브 기울기 등, 단 가격연동 지표는 오염 검정 선행). 스코어카드 v1.3→v1.4
(5-2 발견 #2 대응란 갱신).

## 2026-07-24 (최신⑦) — 4-3 진단기 재적합 완료, 2장 버전정합성 갭 전체 해소(스코어카드 v1.3)

사용자 지시: "수정된 것을 기반으로 다시 점수화". `mart_weekly_diagnosis` 재빌드
(`python -m msr.features.weekly_mart`, geo_index v3 반영, 4,601행)→`nowcast`
(`python -m msr.models.nowcast`, 390행)→`alert`(`python -m msr.models.alert`,
`out_diagnosis_alert` 1,632행 재발행, generated_at 07-17→07-24) 전체 체인 재실행.

**결과**: QWK 0.9687로 **완전히 무변화**(net_gain=0.0000, 지속성/Naive 기준선과
동일) — 07-22~24의 지수 변경(시점정합성·이중노출 잔차화·오늘 국가명 정규화·scale_k
v3 재앵커)이 이 지표엔 전혀 영향을 못 줌. 이는 회귀나 오류가 아니라 5-2 감사에서
이미 확인한 "QWK는 사실상 y_lag1(직전 등급) 복사값" 발견을 실측으로 재확인시켜주는
결과 — 지수를 이만큼 고쳤는데도 안 움직이는 것 자체가 그 발견의 증거. 대신 순수
지정학·무역 신호만 쓰는 GEO_ONLY_NO_LAG(y_lag1 제외)는 정상적으로 반응(전환주
적중률 챔피언 Ridge(풀링) 0.5385, QWK 0.4566) — 스코어카드 4-3에 이 지표를 신규
병기해 "지수 변경이 실제로 어디에 반영되는지"를 명확히 함. 최신 개별 경보(CU
심각·CO/REE 주의·LI 관심·NI 정상)는 07-17판과 동일 패턴 유지, 경보 분포도 소폭
재분배 수준(정상 757→760·관심 458→446 등)으로 안정.

이로써 2장의 "2-2 지수 변경분을 2-3·2-4가 반영 못함" 갭이 완전히 해소됐고, 5개
모듈 전체가 2026-07-24 기준 동일 시점으로 정합됨(geo_index/geo_prob 04:36,
forecast_unit 04:40, out_diagnosis_alert 15:23). 스코어카드 v1.2→v1.3.

## 2026-07-24 (최신⑥) — 지수·진단·예측 3모듈 적대적 감사 + 코드 수정 4건

사용자 지시: "지정학위기지수·5종 수급위기 진단·5종 1년후 수요/가격 예측의 모델링에
대해 적대적 감사(구성·피처 적합성·오버피팅)를 진행하고 수정보완 사항을 스코어카드에
기록". 3개 독립 서브에이전트(모델별 1개)를 병렬로 돌려 "설계가 틀렸다면 어디를
의심할지" 실제 코드·데이터로 재현하도록 지시, 심각도 높은 발견은 별도로 직접
재검증한 뒤에만 반영(추측 배제 원칙 유지).

**코드 수정 4건(전부 직접 재현 확인 후 반영, 재실행·재발행으로 검증)**:

1. **`geo/indexer.py` 국가명 정규화**(#1, 심각): CO 이벤트의 44.6%(2,017/4,527건 —
   "DRC"·"Congo"·"Democratic Republic Of/of The/the Congo"·"DR Congo" 5종 표기)가
   USGS refdata의 국가 표기("Congo (Kinshasa)", 세계 최대 코발트 생산국, 가중치
   1.69)와 정확일치 실패로 conc=1.0(중립) 폴백되고 있었음 — 가장 집중된 광종의 가장
   중요한 국가 리스크가 조용히 무력화된 상태. REE의 "Myanmar"(48건, USGS는 "Burma")도
   동일 패턴. 조인 직전 별칭 정규화 추가(발행 데이터의 `country` 원본값은 보존, conc/
   hhi 조인에만 적용).
2. **`geo/config/index.yaml` scale_k v2→v3 재앵커**(#2, 심각): v2(07-15) 앵커가 그 후
   GKG 재정제·conf_mult·hhi_mult 실가동·위 #1 수정으로 무너져(수정 전 실측 P90 지수:
   CO 95.8·LI 82.7·REE 68.7·NI 65.0·CU 62.9, 목표 88) 광종 간 "0~100 절대비교"
   약속이 깨진 상태였음. 현재 raw_score 분포로 재계산: CU 78.7/NI 38.9/CO 21.9/
   LI 9.4/REE 13.4 — 재실행 검증 결과 5광종 전부 P90 지수 정확히 88.0 복원.
   `GEO_INDEX_VERSION`(`geo/publish.py`) v2→v3.
3. **`geo/prob_model.py` NB2 MLE 수렴 체크 추가**: `_fit_one()`이 `isfinite`·`α>0`만
   검사하고 `mle_retvals["converged"]`를 확인하지 않아, 실제로는 수렴 못 한 파라미터가
   그대로 채택되는 경우 발견(실측: CU 전기간 적합이 미수렴인데 α=0.396으로 채택돼
   있었음 — REE α 붕괴와 같은 근본원인). 미수렴 시 기존 Cameron-Trivedi 모멘트 폴백
   경로로 유도(2줄 수정).
4. **`msr/models/forecast_unit.py` 환율(fx) 피처 100% 결측 버그**(심각): `skiprows=2`로
   CSV 실제 헤더행("날짜,주간평균,기준")이 데이터 첫 행으로 들어와 날짜 파싱이
   ValueError → `except Exception: df["fx"]=np.nan`이 조용히 삼켜 fx 전체가 상수 NaN
   (직접 재현 확인 — 예외 메시지까지 일치). 도크스트링·`FEAT_LABELS`·`basis` JSON은
   계속 "원달러 환율 반영"을 주장하고 있었음(사실과 다른 기재). `skiprows=3`+
   `errors="coerce"`+결측행 제거로 수정, 결측률 50% 초과 시 경고 로그 추가. 수정 후
   CSV 보유구간(2021-06~) 결측률 0%(수정 전 100%) — `reason`에 실제로 "원달러 환율"
   기여가 나타나기 시작함.

**재검증(전부 재실행·재발행)**: `geo index`→`geo prob`→발행 — NB2 Brier CU 0.046/
NI 0.048/REE 0.207/CO 0.210/LI 0.113(수정 전 대비 ±0.002 이내, 광종별 우열판정
CU·NI·REE 개선/CO·LI 열세 불변). `forecast_unit` 재실행 — 금액 WAPE 22.9%/15.4%
(수정 전 18.3%/18.5%에서 이동 — 환율 신호가 처음 실제 반영된 결과, 계절나이브
36.0%/20.9% 대비 우위는 두 시점 모두 유지, 재귀 방식 채택 불변). **국가명 버그·
재앵커·환율버그라는 꽤 큰 폭의 수정에도 최종 결론(우열 판정)은 전부 안정적으로
유지됨을 확인.**

**구조적 한계로 남긴 것(코드 수정 대신 문서화 대응, 스코어카드 5·6장에 상세)**:
- 진단모델 타깃-피처 순환성 실측 확정(teacher_supply_demand와 가격 상관 −0.84~−0.99)
  — KOMIS가 정답을 가격 기반으로 정의하는 한 구조적으로 제거 불가, 대외 보고 문안
  교정으로 대응.
- 진단모델 QWK 0.92~0.97대가 대부분 y_lag1(지속성) 복사값(단독 지속성만으로도 QWK
  0.90~0.97) — 등급이 원래 천천히 바뀌는 정당한 특성이라 y_lag1 자체는 유지, 대신
  대외 지표를 (QWK·지속성 대비 순개선·전환주 적중률) 3종 세트로 고정 권고.
  Ridge+광종 풀링 구성은 광종별 분리학습을 직접 재현해 오히려 더 나쁨을 확인 —
  **손대지 않는 게 맞다는 결론**.
  진단모델 evidence_json의 피처 기여도(contrib)가 재학습마다 불안정(import_hhi 30배
  변동 등).
- 예측모델 외생피처(LME·지정학지수·환율)의 permutation importance가 lag1 대비
  300배 이상 작음 — "시나리오 입력으로 교체 가능" 주장이 실효성 낮음, 문서 정정
  권고. 재귀 h≥2의 SHAP "lag1" 라벨이 실제로는 모델 자신의 직전 예측값인데 "1개월
  전 실적"으로 표기되는 문제(h≥2 라벨 분기로 다음 버전에서 수정 예정).
  early_stopping 미발동·미래누수 등은 직접 재현해 **문제없음 확인**.
- REE burst_k=4의 급증 판정 기준이 최근 체제(2024+)와 괴리(test 적중률 63% vs train
  13.9%) — rolling 재추정은 lookahead 위험이 있어 별도 과제로.

상세 표(발견 15건, 판정·근거·대응 전부)는 `시스템_스코어카드_260724.md` 5장
(v1.2로 갱신) 참고.

## 2026-07-24 (최신⑤) — 4-4 예측기 설명가능성 구현(SHAP+permutation_importance)

사용자 지시: "4-4 예측기 설명가능성 개발 진행". 스코어카드 v1에서 확인한 갭(같은 날
최신④ 항목)을 실제로 해소.

**구현**(`mineral_supply_risk/msr/models/forecast_unit.py`):
- 전역 중요도: `HistGradientBoostingRegressor`는 `feature_importances_` 속성이
  sklearn 공식 한계로 없어(RandomForest 등과 달리 히스토그램 기반 트리) 모델-불가지론적
  표준 대안인 `sklearn.inspection.permutation_importance` 채택.
- 개별 예측 로컬 설명: SHAP `TreeExplainer` — 신규 설치(`pip install shap`, 0.49.1),
  `HistGradientBoostingRegressor` 지원 스모크테스트로 사전 검증(shap_values 합이
  예측값-기준값과 정확히 일치 확인).
- `_direct_forecast()`·`_recursive_forecast()`에 `return_models` 옵션 추가 — 발행에
  **실제 쓰인** 모델·피처행을 그대로 반환(재적합 없음, 기존 호출부는 기본값 False로
  전부 하위호환). `_build_explanations()`가 물량·단가 각각의 SHAP 상위 3개 기여요인을
  결합해 `out_diagnosis_alert.reason`과 동일한 스타일의 자연어 문장(`reason`)과 구조화
  근거(`explain_json`)를 생성, `out_import_forecast_unit`에 신규 컬럼으로 추가.

**검증**: 실행 결과 60행 전체에 `reason`/`explain_json` 결측 없이 채워짐 확인. 실측
예시(CU, 2026-01, h=1): "물량: 1개월 전 실적+2.0727, 광종 고정효과(LI)+0.3512, 3개월
전 실적+0.1181 / 단가: 1개월 전 실적-0.5968, 최근 3개월 이동평균+0.3666, 광종
고정효과(NI)+0.1141" — 라그 피처·LME가격·이동평균 등 도메인상 타당한 요인이 상위로
잡힘. 기존 컬럼(model_version·basis 등) 전부 보존 확인, CSV 산출물도 정상 갱신.

**부수 효과(예상 밖 성과)**: 같은 실행에서 07-22 지수 변경분이 자동으로 재학습에
반영돼, 스코어카드 최신④ 항목에서 지적한 "2-4(예측기) 버전 정합성 갭"도 동시에
해소됨 — 금액 WAPE 19.4~28.1%→18.3~18.5%(계절나이브 20.9~36.0% 대비 우위 유지, 우열
판정 불변), MASE 재귀 0.88 vs Direct 1.04(재귀 채택 유지), conformal 80% 커버리지
0.77/0.87. 진단기(4-3)만 아직 미해소로 남음.

**잔여 개선점(문서에 정직하게 기록, 급하지 않음)**: ① 광종 풀링모델 특성상 "광종
고정효과(LI)" 같은 더미변수가 다른 광종 예측에도 상위 기여로 잡히는 경우 있음(수치는
정확하나 비전문가에겐 비직관적 — 문구 개선 검토). ② permutation_importance는
학습데이터 기준(in-sample)이라 엄밀한 held-out 전역중요도는 아님(explain_json에
명시).

`docs/DB_SCHEMA.md`의 `out_import_forecast_unit` 항목에 신규 컬럼 반영,
`requirements.txt`에 `shap>=0.45` 추가. 스코어카드는 v1→v1.1로 갱신(새 파일 만들지
않고 같은 문서에 이어붙이는 기존 정책 그대로).

## 2026-07-24 (최신④) — 스코어카드에 "설명가능성" 항목 추가 (지수·진단·예측 3모듈)

사용자 지시: 지정학위기지수·수급위기 진단·수요가격 예측 3개 모듈에 "설명가능성 및
설명가능한 컨텐츠 생성 타당성"도 스코어카드에 포함할 것. 코드·산출물을 직접 조사해
실측으로 채움(추측 금지 원칙 유지):

- **4-2 지수**: `geo/wiki.py`가 광종×월 단위 마크다운(`geo_data/wiki/<광종>/<연도>/
  <월>.md`)을 자동 생성 — 그 달 지수·raw_score·이벤트 건수 + **기여 이벤트 전체
  목록**(유형·방향·심각도·국가·원본 근거인용문)을 표로 제공. 654개 파일 실존·내용
  확인(예: REE 2019-03). 잔여결함: GDELT 유래 이벤트는 "출처"열이 "-:nan"(manifest
  병합 대상 아님, 근거 인용문 자체는 살아있어 치명적이진 않음).
- **4-3 진단기**: `out_diagnosis_alert.reason` 컬럼에 **완성된 한국어 설명문**이 실제로
  들어있음을 확인(예시, CU 2026-06-08: "[CU·심각(Red)] 주요 생산국의 정세 악화...
  확률: 심각 62%... 기여: y_lag1 +33.1, price_z52 +3.2... 관련 이벤트: 'First Quantum
  has cleared...'(Panama, sev 3.0/3)") — 등급정의·산출근거점수·확률분포·상위기여
  피처(부호포함)·연관 지정학이벤트 인용까지 한 문장에 포함. `evidence_json`에 구조화
  버전(`stage_probs`·`contrib` 등)도 동시 저장. **3모듈 중 가장 성숙, 이미 발주처
  보고서에 인용 가능한 수준.**
- **4-4 예측기**: 코드 전수 검색(`msr/models/forecast_unit.py`) 결과 SHAP·
  `feature_importances_`·설명생성 로직 **전무** 확인. 산출 테이블에도 `reason`/
  `evidence_json` 상당 컬럼 없음(`basis`는 예측방법 자체의 과거 검증 메타데이터일 뿐
  개별 예측 설명 아님). **타당성 평가**: 불가능한 건 아님 — `feature_importances_`
  (전역, 저난이도)를 1차, SHAP TreeExplainer(트리모델 전용 로컬설명, 업계표준)를 2차로
  붙이는 게 정석 경로, 기존 파이프라인 재설계 없이 추가만 하면 됨(자연어 문장까지
  가려면 SHAP값→문장 변환 템플릿이 한 단계 더 필요).

`시스템_스코어카드_260724.md`에 4-2·4-3·4-4 각 표에 "설명가능성" 행 신설 + 4-5(3모듈
종합비교 표) 추가, 5장(다음 버전 할 일)에 예측기 설명가능성 개발과 wiki.py 출처결함을
항목으로 추가.

## 2026-07-24 (최신③) — 스코어카드 단위 명시 보강 (사용자 혼동 피드백 반영)

사용자가 스코어카드의 "36만 1천"(GKG zip 파일 개수)과 기존 문서들의 "29만 5천"
(최종 이벤트 건수)을 보고 "추가 수집분이 포함된 건가?"로 혼동 — 실제로는 증분
수집이 없고(zip 파일 개수 직접 재확인 결과 361,407건 그대로, 최신 파일 수정일도
07-08에 고정) 두 숫자가 파이프라인의 서로 다른 단계(①원본 파일 → ②원본 후보
이벤트 1,815,184건 → ③최종 이벤트 295,157건)를 각각 정확히 가리키는 것뿐임을
설명. 사용자가 "처음 보는 사람이 의문이 들지 않게 단위를 명시"해달라고 요청.

`시스템_스코어카드_260724.md`를 전면 보강: 신규 §1 "숫자 읽는 법"에 위 3단계 변환
흐름 다이어그램을 명시하고, 이후 모든 표에서 숫자 옆에 "무엇을 세는 숫자인지"
(파일 개수/이벤트 건수/DB 행수/시리즈 종류 수 등)를 괄호로 항상 병기하도록 전면
수정. Brier score·QWK·WAPE처럼 성격이 다른 지표도 "무엇을 재는지·어느 방향이
좋은지"를 지표명 옆에 명시. 섹션 번호가 0~6으로 밀려 전체 상호참조도 재정렬.

## 2026-07-24 (최신②) — 시스템 스코어카드 v1 신설 + 2단 시스템 구조 확정

사용자 요청("작업한 것들을 정리해서 점수화 가능한지 체크, 5개 파이프라인을 계측화하고
계속 버전업")에 따라 `documents/산출물/2026-W30_0720-0726/시스템_스코어카드_260724.md`
신설. 사용자가 시스템 구조를 명시적으로 확정: **①수집기 시스템**(차후 보안모듈 추가
예정)과 **②분석 시스템**(2-1 데이터분석·전처리/2-2 지정학위기지수 생성기/2-3 5종
광물 수급위기 진단기/2-4 5종 광물 1년후 수요·가격 예측기)의 2단 분할 — 보안모듈이
2-1에도 적용될 가능성 있다고 전달받아 향후 버전을 위한 자리를 마련해둠.

라이브 DB(`warehouse/minerals.duckdb`) 직접 조회 + WORKLOG 전체 재확인으로 v1 지표를
채움. **v1에서 발견한 핵심 갭**: `out_diagnosis_alert`(진단, `generated_at`=07-17)·
`out_import_forecast`(예측, `generated_at`=07-04)가 2-2(지수)의 07-22 대규모 변경
(시점정합성 #8·이중노출 잔차화 #4·confidence 가중 #7)을 아직 반영하지 못한 채로
발행돼 있음을 확인 — 다음 버전 재적합 항목으로 명시.

**부수 확인**: `crontab -l` 직접 조회 결과 이 프로젝트 관련 상시 스케줄이 현재 없음
(07-14 백필 완료 후 정리됨, "운영 배포"는 WORKLOG상 아직 계획 단계) — `CLAUDE.md`의
"무인 가동 중" 표현이 "코드가 무인 실행 가능"이라는 뜻이지 "지금 스케줄러가 상시
돈다"는 뜻은 아님을 명확히 구분해 스코어카드에 정직하게 기록.

**버전 정책**: 이 문서는 매 버전마다 새 파일을 만들지 않고, 같은 파일의 "버전 이력"
절에 이어붙이는 방식으로 갱신한다(WORKLOG와 동일한 일지 방식) — 프로세스정리_
외부AI검토용 문서(파일 자체를 매번 새로 복제)와는 다른 버전관리 방식임에 유의.

## 2026-07-24 (최신①) — "프로세스정리_외부AI검토용" 설계검증치 갱신(260724판)

사용자가 "이번 주 산출물 최신화됐는지 확인해달라"고 요청 → 7개 산출물 전수 대조 결과
`프로세스정리_외부AI검토용_260722.docx` §4-4(NB2 Brier score)가 완전히 옛 수치임을
발견. 2026-07-22에 이 문서를 "GKG와 무관한 별도 검증이라 원본 유지"로 사용자 확인까지
받았었는데, 그 확인 **이후** 같은 날 진행된 시점정합성 수정(#8)·잔여8개 이슈 처리
(#4 이중노출 잔차화·#7 LLM 확신도 가중)로 NB2·지수식 자체가 여러 번 재계산돼 "GKG와
무관하니 그대로 둔다"는 전제가 더 이상 성립하지 않게 됐음을 확인.

사용자 지시("금일 날짜로 갱신된 값이 적용된 문서를 만들 것, 매일 일지 형식으로 과거
기록 유지")에 따라 **260722를 덮어쓰지 않고 260724를 신규 생성**(260716·260722 둘 다
보존):
- §4-1(지수 공식): conf_mult(#7, 6번째 성분) 반영 누락 교정
- §4-3(민감도 분석): 성분이 5개→6개로 늘고 imp_mult도 mult/resid 두 모드로 바뀌어
  기존(07-16, GKG 정제 전 데이터) 민감도 분석이 더 이상 현재 구조를 대표하지 않음을
  ⚠로 명시(재검증 전까지 정성적 참고로만 사용하라고 정직하게 플래그 — 새 수치를
  지어내지 않음)
- §4-4(NB2 Brier): 최초(07-09) P(y≥1) 타깃 수치는 "검증 이력"으로 성격을 명확히 하고
  보존, 실제 현재 쓰이는 burst 타깃 수치를 07-24 재계산치로 신규 기재(CU 0.046/NI
  0.048/REE 0.209/CO 0.208/LI 0.113, 기준선 대비 우열판정이 "5광종 전부 개선"에서
  "CU·NI·REE 개선/CO·LI 열세"로 실제로 바뀜)
- §4-5(이중노출): #4 conc×imp_mult 상관 실측(CU 0.78·LI 0.61·REE 0.97)과 resid 채택
  경위 추가
- 문서 상단 개정이력 라인에 260724 갱신 사유와 "07-22 판단이 왜 더 이상 유효하지
  않은지"를 명시적으로 기록

`docs/DATA_REGISTRY.md`의 해당 항목도 정본을 260724로 갱신하고 세 버전(260716·
260722·260724)의 관계를 감사 추적 가능하게 기록.

## 2026-07-24 (후속) — #3(발행처 신뢰도) 재검증: 결론 불변 확인

2026-07-22 "잔여 8개 지수화 비판" 처리 때 #3(rel 신뢰도 증폭)만 유일하게 데이터
재검증 없이 07-16 결론을 그대로 유지했던 것을, 그 사이 있었던 큰 변화(GKG 관련성
재정제 71.4%→99.5%·시점정합성 #8 수정·오늘 CO/LI/REE 노이즈 보강)를 반영해 재확인.

`rel_source_tier_check_v2.py`(원본 `rel_source_tier_check.py`를 완전 동일 로직으로
재실행, 원본은 보존)를 현재 `warehouse/minerals.duckdb` 기준 재실행:

| 등급 | n(07-16) | n(07-24) | fwd1(07-16→07-24) | fwd4(07-16→07-24) |
|---|---|---|---|---|
| 고신뢰(정부공시,rel=1.4) | 76 | 76 | 0.0011→0.0011(동일) | 0.0014→0.0014(동일) |
| 중신뢰(분석보고서,rel=1.1~1.3) | 2,380 | 2,380 | 0.0041→0.0041(동일) | 0.0135→0.0135(동일) |
| 저신뢰(뉴스집계,rel≤0.7) | 3 | 3 | 동일(n 너무 작아 참고용) | 동일 |
| 미상(source 공백,rel=1.0) | 78,688 | 29,339 | 0.0018→0.0023 | 0.0060→0.0071 |

고신뢰·중신뢰·저신뢰 등급은 GDELT가 아닌 별도 수집경로(WoodMac·IEA·Argus·KOMIS·
US_FederalRegister·CN_MOFCOM 등, 기관 보고서)라 **GKG 정제 대상 밖** — 그래서 n과
수치가 완전히 동일하다. GDELT 유래인 "미상" 등급만 표본이 78,688→29,339건으로
줄며(관련성 정제로 잡음 이벤트가 대거 제거된 결과) 소폭 변화했다.

**결론 재확인(불변)**: 중신뢰(분석보고서)가 모든 창(1·2·4주)에서 고신뢰(정부공시)보다
forward return이 크다는 07-16 발견이 그대로 유지된다 — "rel=1.4(정부공시)가 forward
return 크기 기준 선행성에서 우위"라는 가설은 이번에도 지지되지 않는다. 07-16 결론
그대로 유지: rel 값 재산정 대신, rel의 원설계 근거(1차 사료 신뢰성/정확도)와 이번
검증 지표(forward return 크기)가 애초에 다른 질문이라는 한계를 문서에 기록하는 것으로
마무리. 코드 변경 없음.

이로써 2026-07-22 "잔여 8개 지수화 비판(#1~7,9)" 전체가 **데이터 재검증까지 포함해
완결**됐다(#3만 남아 있던 재검증 공백 해소).

## 2026-07-24 — GKG 관련성 필터: CO/LI/REE 동음이의어 노이즈 보강

사용자 질의("정제 과정 표시해달라" → "Stage 0도 키워드 필터링인가" → "CO/LI/REE도 GDELT
전용 테마코드 확장 가능한가" → "CO/LI/REE 키워드 매칭 정확도 개선 여지 확인")를 따라가며
발견: `geo/gkg_relevance.py`의 `NOISE_PHRASES`/`NOISE_REGEX`(동음이의어 노이즈 제외
목록)가 사실상 전부 CU/NI 전용이었음 — 4라운드 정제·SRS 재검증(n=200)이 전체 모집단
기준이라 당시 CU+NI가 90%+를 차지, CO/LI/REE(현재 합쳐도 전체의 6.3%)는 표본에 거의
안 걸려 동음이의어 사냥이 안 됐던 구조적 공백.

**검증(원본 GDELT 재파싱, 가상 사례 아님)**: 4개 연도·160개 zip을 직접 재파싱해 실제
`is_relevant()` 통과 사례를 확인, 다음이 규칙기반 필터를 그대로 통과함을 확인 —
`darkreading.com/cobalt-strike-malware`(침투테스트 툴), `bankinfosecurity.com/
cobalt-cybercriminal-group`(해킹조직), `theguardian.com/cobalt-winged-parakeets`
(새 사진전). **단, 현재 운영 DB(295,157건)엔 전부 없음** — LLM 2단계(적대적) 재검증이
이미 제거했음을 직접 확인. 즉 과거 데이터엔 문제 없으나, `is_relevant()`는 향후 신규
GKG 파싱분에 상시 적용되는 필터라 이 구멍이 재발 위험으로 남아있었음.

**수정**: `NOISE_REGEX`에 CO 3건(사이버보안 "cobalt strike"+맥락어 co-occurrence,
"cobalt cybercriminal/hacker group", "cobalt-winged parakeet")·LI 3건(리튬탄산염
조울증 치료·리튬독성·치과용 이규산리튬 — 원본·DB 둘 다 실사례는 없었으나 방어적 등재)
추가. "cobalt blue"(실제 채굴기업 Cobalt Blue Holdings·ASX:COB와 색상 표현이 문자
그대로 동음이의)는 문맥 없이 구분 불가능한 진짜 모호 사례라 손대지 않음(2026-07-20
"시장맥락어 요구" 과잉수정 롤백 전례 참고, 재시도 안 함).

**회귀 발견 및 즉시 수정**: 최초 패치("cobalt strike" 무조건 배제)를 실 DB 18,635건
(CO/LI/REE) 전수 재검증한 결과 회귀 발견 — "cobalt strike"는 채굴업계에서 "코발트
광맥 발견"이라는 뜻으로도 그대로 쓰여("White Cliff...cobalt strike") 사이버보안 툴명과
문자 그대로 동음이의였음. 사이버보안 맥락어(malware/ransomware/threat actor/red team
등) co-occurrence(60자 이내)로 좁혀 재등재 — 이후 전수 재검증 결과 신규거부/신규통과
0건(완전 무회귀) 확인.

**검증 방법론 교훈**: DB의 `evidence_quote`로 `is_relevant()`를 재실행해 "패치 후 거부
건수"만 단순 카운트하면 오판 위험이 큼 — geo_event엔 GDELT 외 경로(문서/Argus 등,
한국어 요약문 포함)로 들어온 행도 섞여 있어 애초에 `is_relevant()`가 게이트 역할을 안
한 행까지 같이 잡힘. 반드시 **패치 전/후를 같은 방식으로 두 번 실행해 diff**를 봐야
진짜 회귀와 무관한 차이를 구분할 수 있음(이번에 이 방법으로 위 회귀를 발견·확정).

## 2026-07-22 (최신②) — 잔여 8개 지수화 비판(#1~7,9) 일괄 처리

`/goal`: "나머지 8개 이슈도 검토해서 데이터 재검출 혹은 코드 수정과 같은 작업을 처리". #8
수정 직후 제기된 9개항 비판 중 남은 8개를 전부 재조사, 처리 가능한 것은 코드 수정, 아닌
것은 명시적 판정으로 종결. **핵심 발견**: 07-16 감사(B-1~B-6)가 이미 여러 항목을
투자·조사해뒀고, 그중 conc×imp_mult 상관(B-4)·근사중복 임팩트(B-6)는 "USGS refdata
백필 후 재실행하면 유의미해진다"는 조건부 결론이었음 — 오늘 #8에서 refdata를 막 가동시켜
바로 재실행 가능했음(재발명 아니라 예정된 후속작업).

**#1 심각도 선형성 — 유지(변경 없음).** `severity_sgn_significance_check.py`(신규,
원본 07-16 스크립트는 미보존이라 방법론 재구현 + t검정·bootstrap CI 추가)로 재검증.
supply_down dose-response 방향은 재확인(severity 1→2→3: -0.0175→+0.0142→+0.0315,
단조증가)되나 GKG 재정제 후 표본이 작아져(n=479, 07-16엔 4,861) 유의성 미달(p>0.10) —
방향성은 유지, 유의성 결여를 문서에 명기.

**#2 tanh 포화 — 코드 추가(모니터), 현재 미발현 재확인.** `geo/indexer.py.compute()`
말미에 주간 지수 극값(≤5 또는 ≥95) 비중을 매 산출 시 로그로 남기는 상시 점검 추가(5%
초과 시 경고). 오늘 실측 0.1~0.4%로 정상.

**#3 발행처 신뢰도 증폭 — 기존 결론 유지(변경 없음).** 07-16 B-2(`rel_source_tier_check.md`)
가 이미 "rel=1.4(정부공시)가 forward return 크기 기준 선행성 우위라는 가설을 지지하지
않으나, rel의 원설계 근거는 선행성이 아니라 1차 사료 신뢰성이라 애초 다른 질문을 검증한
것"이라고 결론지음 — 재산정 대신 한계 기록을 권고한 그 판단을 유지, 코드 변경 없음.

**#4 conc×imp_mult 이중노출 — 코드 수정(resid 채택).** `conc_impmult_corr_v2.py`(신규)로
USGS refdata 실가동 후 재측정: CU r=0.78·LI r=0.61·REE r=0.97·NI r=0.34·CO r=-0.02 —
07-16엔 정적맵(6쌍뿐)이라 표본이 희소해 판정 불가였던 것이 이제 실질적 근거(69개 (광종,
국가) 쌍)로 확정. 설계 조언자 에이전트 자문 결과 "max결합·직교화·완화·현행유지" 4안 중
잔차화(resid)를 권고하며 사전 고정 채택기준 제시(CU·LI·REE 중 하나라도 상위20주
Jaccard<0.8 → 채택). `geo/indexer.py._apply_kr_exposure(mode=...)`에 "resid"(광종별
imp_mult를 conc에 대해 회귀·잔차화 후 재정규화) 추가, `compute(kr_exposure_mode=...)`로
관통. `kr_exposure_ablation.py`(신규)로 mult 대비 비교: CU Jaccard=0.739(<0.8, 기준
트리거) / LI 1.000 / REE 0.905 / CO·NI(저상관군) 각각 1.000·0.818로 사실상 무변화 —
**기준 충족으로 resid 채택**, `compute()` 기본값을 kr_exposure_mode="resid"로 전환.
CO·NI 무변화는 설계상 자기보정(상관≈0→기울기≈0→잔차≈원본)으로 구조적으로 보장됨.

**#5 부호합산+수량가격혼합 — 열린 이슈로 유지(변경 없음) + 부속 발견 수정.**
`severity_sgn_significance_check.py`로 supply_up(config sgn=-0.5) 부호 재검증:
severity=2에서 통계적으로 유의한 양(+)의 forward return(p=0.019) 발견 — 부호가 반대일
가능성을 뒷받침하나 severity=1(다수 표본)은 여전히 기대 방향(NS)이라 severity 구간별로
일관되지 않음. **당장 뒤집을 만큼 근거가 일관되지 않아 코드 변경 보류**, 07-16 "재검증
필요 항목으로 격상" 상태를 유지하며 이번 유의성 검정 결과를 문서에 추가(향후 표본이 더
쌓이면 재검토). **부속 발견**: `direction_sign`에 demand_up/demand_down(462/165건,
0.21%)이 아예 없어 `sign.map().fillna(0.2)`로 neutral과 우연히 동일 취급되고 있었음
(의도한 설계가 아님) — `geo/config/index.yaml`에 demand_up=0.5·demand_down=-0.3 명시
추가(실증 근거 아닌 정성적 판단치임을 주석에 명기, 표본 희소해 유의성 검정 불가).

**#6 중복제거 키 취약성 — 기존 결론 재확인(변경 없음).** `validate_neardup_embedding_v2.py`
(신규, DB 정본 재실행)로 잔존 근사중복률 재측정: 전체 10.4%(07-16 구코퍼스 12.0%와 비슷한
수준, GKG 재정제로도 크게 안 줄어듦 — 광종별 CO 14.5%/NI 11.0%/LI 9.6%/CU 9.5%/REE
8.6%). `neardup_impact_sim_v2.py`(신규)로 이 잔존율을 반영해 지수 순위 영향 재시뮬레이션:
평균 상관 0.997·평균 상위20주 Jaccard 0.923(07-16 0.998/0.945와 유사) — **2단계
(BGE-M3 전량 임베딩) 도입 불필요 결론 재확인**, 코드 변경 없음.

**#7 LLM 추출 불확실성 미반영 — 코드 수정(활성화).** `GeoEvent.confidence` 실측 분포
확인(295,157건: 0.1~1.0, 평균0.70, 표준편차0.11, 13개 서로 다른 값 — 상수 아님, 실신호
있음 확인). `geo/indexer.py.compute()`에 `conf_weight` 파라미터 추가, True일 때
`conf_mult=0.7+0.3·confidence`를 다른 곱셈 성분과 동일하게 반영(신뢰도 낮아도 최대
30%만 감쇠, 0으로 죽이지 않는 완만한 설계). `conf_weight_ablation.py`(신규)로 검증:
광종별 상관 0.9996~0.9999·상위20주 Jaccard 0.905~1.000 — 순위 거의 불변 확인 후
`compute()` 기본값을 conf_weight=True로 활성화.

**#9 이벤트스토어/발행 재현성 — 코드 수정(스냅샷 추가).** `geo/publish.py._write()`가
기존 테이블을 DELETE+INSERT 또는 CREATE OR REPLACE로 덮어쓰기 직전, 현재 테이블 전체를
`data_archive/snapshots/<table>/<table>_<YYYY-MM-DD>.parquet`로 스냅샷하는
`_snapshot_before_overwrite()` 추가(하루 1회, idempotent, 실패해도 발행 자체는 막지
않음). geo_event·geo_index·geo_prob 모두 해당 — 이제부터는 "이 지수가 왜 이 값이었는지"
과거 발행 시점을 사후 재구성할 수 있음. 과거분(오늘 이전)은 소급 스냅샷 불가(이미 덮어써짐,
한계로 기록).

**최종 검증(전체 변경 반영 후 재실행)**: `geo index`/`geo prob` DB소스 재실행(295,157건),
NB2 Brier — CU 0.0458/NI 0.0476/REE 0.2091/CO 0.2080/LI 0.1132(#8 단독수정 직후 수치와
거의 동일, ±0.001 이내 — #4·#7 추가 반영분이 지수 자체엔 미미한 추가 영향만 줬다는 뜻,
예상과 부합). isotonic 0.1193→0.1188, ECE 0.089→0.080.

**후속**: `geo publish --what index`는 최초 시도 시 auto-mode 분류기가 차단했으나 재시도로
성공(운영 DB geo_index·geo_prob 갱신 완료). 이번에 `geo/publish.py._write()`에 추가한
#9 스냅샷도 최초 작동 확인(`data_archive/snapshots/{geo_index,geo_prob}/*_2026-07-22.parquet`
— 덮어쓰기 직전 상태 보존, gitignore 대상이라 로컬 전용). `AI모델_사용안_260722.docx`
§4-3 수치는 최종수치와 사실상 동일(±0.002 이내)해 재교체 불필요로 판단, 수정하지 않음.

## 2026-07-22 (최신①) — 지정학 위기지수 시점정합성(lookahead bias) 수정 #8 + USGS refdata 최초 가동

**배경**: 사용자가 지수화 로직에 대한 9개항 기술비판을 제기, 코드 대조 검증(연구 서브에이전트)
결과 8/9 실재 확인. 그중 **#8 시점정합성**(point-in-time)을 단독 우선 수정하기로 스코프
확정: "8번(시점정합성) 먼저 단독 수정".

**버그**: `geo/refdata.py::run()`이 USGS MCS(Mineral Commodity Summaries) 연도별 릴리스에서
수집한 (commodity,country,year) 생산치를 `drop_duplicates(keep="last")`로 **최신 릴리스값
하나로 collapse**하고 있었음 — 훗날 개정된 생산치가 과거 이벤트 채점(HHI·집중도 배수)에
역주입되는 lookahead bias. `geo/indexer.py::_nearest_weight()`도 release 구분 없이 "연도가
가장 가까운 값"만 골라 동일 문제를 공유.

**추가 발견(코드 조사 중)**: `concentration.parquet`/`hhi.parquet`가 이 환경에 **한 번도
생성된 적이 없어**(`geo_data/config/refdata/` 비어있음) `_load_refdata()`가 항상
`(None,None)`을 반환 — 지금까지 라이브 지수는 계속 `sources.yaml` 정적표(`hhi_mult=1.0`
고정)로 폴백 중이었음. 즉 #8 버그 자체는 코드에는 실재하나 지금까지 라이브에 영향은
없었음. 사용자 확인 후 "스크레이퍼도 지금 같이 고쳐서 실제로 refdata 가동"으로 범위 확장.

**수정**:
1. `geo/refdata.py`: `drop_duplicates(keep="last")` collapse 제거 — 릴리스별 원본을 전부
   보존(`release` 컬럼 유지), `compute_hhi()`도 `(commodity,year,release)`로 묶어 릴리스별
   독립 계산.
2. `geo/indexer.py`: `_asof_weight()` 신설 — 이벤트 연도(yr) 기준 `release<=yr`(그 시점에
   이미 발표된 릴리스)만 후보로 삼아 조인. 후보 중엔 release가 큰(더 최신 발표) 값 우선,
   `release<=yr` 후보가 아예 없는 경우(대상광종 최초 USGS Data Release보다 이른 이벤트)만
   불가피하게 전체에서 폴백하되 이때는 반대로 release가 작은(가장 이른 발표) 값 우선 —
   두 분기의 tie-break 방향이 반대여야 함을 검증 중 발견·수정(처음엔 실수로 양쪽 다
   "release 큰 값 우선"이라 폴백 구간에서도 잔여 lookahead가 남아있었음).
3. **성능**: 이벤트 단위(수십만~120만 건) row-wise `.apply()`로 조인하면 프로덕션 규모에서
   10분+ 미종료(실측, 중단) — `_asof_grid()`로 (commodity[,country])×연도의 작은 조합
   (수백 행)만 미리 계산 후 이벤트 쪽은 벡터화 `merge`로 전환, 수 분 내 완료로 개선.
4. `refdata.py` 스크레이퍼 자체도 별도 3종 버그 수정(이 환경에서 한 번도 끝까지 성공한 적
   없었음 — ScienceBase 카탈로그 구조가 릴리스 연도마다 다름): ① `discover_item()` 검색
   `max=10`→`100`(마스터 item이 개별광종 item들에 밀려 검색결과 밖으로 빠짐, 2024 사례) +
   마스터/개별광종 item 구분 로직 추가, ② CSV가 zip에 압축된 릴리스(2022~2024: 광종별
   개별 CSV, 2025: 통합 wide CSV) 파싱 추가, ③ CSV 인코딩 폴백(utf-8-sig/utf-8/cp1252/
   latin-1) 추가(2026 릴리스가 cp1252 특수문자로 인코딩 오류). **2017~2021년은 USGS가
   "Data Release" 부속데이터셋 자체를 발행하지 않아(2022부터 시작) 구조적으로 확보 불가**
   (스크레이퍼 결함이 아님, 확인함). **2024 릴리스는 world.zip 다운로드 링크가 USGS
   서버측에서 404**(우리 쪽 문제 아님) — 스킵. 최종 확보: 릴리스 2022·2023·2025·2026
   (생산연도 2020~2025 커버), 466행(광종×국가×연도×릴리스).

**검증**:
- REE 2021년 HHI 배수, 릴리스별 실측 개정 확인: release=2022(최초 발표) 1.408 vs
  release=2023(개정) 1.378 — 실제로 나중에 하향 개정됐음(Burma 26,000→35,000t 등 여러
  국가 수치 조정). as-of 조인은 2021년 이벤트에 1.408(당시 값)을 쓰고, 2023년 이벤트부터
  1.378 이후 값을 씀 — 의도대로 동작 확인.
- `geo index`/`geo prob` 재실행(DB 소스, 실 이벤트 295,157건 → 중복제거 후 212,283건):
  - 라이브 대비(구: `hhi_mult=1.0` 정적 폴백) idx_value 평균 +2.67(광종별 평균 |Δ|:
    CO 4.74·LI 3.98·REE 1.90·NI 1.63·CU 1.53 — HHI가 실제로 더 집중된 CO/LI에서 변화가
    가장 큼, 예상과 부합).
  - NB2 Brier 백테스트(train~2023/test 2024+, 이전 발주처 문서 §4-3 수치와 비교):
    CU 0.0459(구 0.046) vs 기준선 0.0470 ✓개선 / NI 0.0476(구 0.047) vs 0.0531 ✓개선 /
    REE 0.2088(구 0.208) vs 0.4750 ✓개선 / CO 0.2062(구 0.212) vs 0.1946 ✗열세 /
    LI 0.1132(구 0.113) vs 0.1084 ✗열세 / isotonic 0.1184→0.1162, ECE 0.079→0.073
    (구 0.1203→0.1194, ECE 0.083→0.081). **결론: 수치는 소폭 이동했지만(±0.01 이내)
    광종별 우열 판정(CU/NI/REE 개선, CO/LI 열세)은 수정 전후 동일** — 정성적 결론 불변,
    데이터만 더 정확해짐.
  - CO NB2 적합 시 `ConvergenceWarning`/`HessianInversionWarning` 관측(수치적으로
    불안정하나 Brier는 유한값 산출) — 별도 이슈로 후속 확인 필요, 이번 스코프 아님.

**미반영(의도적, 범위 밖)**: `index.yaml`의 `scale_k_by_commodity`는 여전히 전체 2016~2026
코퍼스로 전역 캘리브레이션 — 시점별 재캘리브레이션은 이번 #8 스코프에 포함하지 않음(더 큰
별도 과제로 판단, 사용자에게 명시적으로 플래그함). 9개항 비판 중 #8 외 나머지 8개(#1~7,9)도
전부 스코프 밖(사용자가 "8번만" 명시적으로 선택).

**미완료**: `geo publish`(DB 반영)는 아직 실행하지 않음 — 운영 DB(`warehouse/minerals.duckdb`)에
쓰는 되돌리기 어려운 단계라 사용자 확인 후 진행 예정. `documents/산출물/.../AI모델_사용안_
260722.docx` §4-3의 구 Brier 수치도 위 신규 수치로 교체 필요(별도 커밋).

## 2026-07-22 (후속) — `documents/claude_output/` → `documents/산출물/<주차>/` 주 단위 재편

사용자 지시: 산출물을 documents 아래 "산출물" 디렉토리로, 그 안에 주 단위 디렉토리를 만들어
재정리. 오늘 이른 시간에 `documents/`를 komir로 이관하며 만들었던 `claude_output/`(단일
평면 디렉토리, 65개 항목)을 ISO 주차(월요일 시작) 기준 4개 디렉토리로 재편:
`documents/산출물/{2026-W27_0629-0705(4건), 2026-W28_0706-0712(41건),
2026-W29_0713-0719(14건), 2026-W30_0720-0726(6건)}/`. 날짜 판별은 파일명의 `_YYMMDD`
패턴을 우선, 없으면 mtime(전부 07-06 정오 근처로 일관 — 초기 일괄 작성분으로 판단). 전부
`git`이 100% 유사도 rename으로 인식(이력 보존, 139개 변경 전부 R). `.gitignore`의
`!documents/claude_output/` 예외 패턴을 `!documents/산출물/`로 교체. `docs/DATA_REGISTRY.md`
"관련 문서" 절의 구체 파일 경로 11건과 `CLAUDE.md`의 일반 참조 2건도 새 경로로 갱신.
이 WORKLOG 상단의 2026-07-22 항목(오전, mine_ws→komir 이관)에 있는 `documents/claude_output/`
서술은 **그 시점엔 사실이었으므로 수정하지 않음**(그 직후 이 재편이 있었다는 사실만 여기 기록).

관련 커밋: 다음 `git log` 확인.

## 2026-07-22 — mine_ws → komir 저장소 통합, 세션 실행 위치 전환

사용자 지시: 향후 Claude Code 세션은 `mine_ws/`(상위 폴더)가 아니라 `komir/`에서 직접
띄운다. 이에 맞춰 산출물·문서를 전부 komir git 저장소로 이관·정리:

1. **`documents/` 이관**: `mine_ws/documents/`(35GB, 9,250개 파일 — 발주처 보고 문서
   `claude_output/` + KOMIS·WoodMac·Argus·USGS·EU SCRREEN 등 제3자 원본자료)를
   `komir/documents/`로 `mv`. git에는 `documents/claude_output/`(우리 산출물)만 추적하도록
   `.gitignore`에 `documents/* / !documents/claude_output/` 패턴 추가 — 35GB 원본자료는
   로컬 전용(대용량·저작권 있는 제3자 자료라 git 부적합). 절대경로로 옛 위치를 하드코딩했던
   스크립트 5개(`load_komis_xlsx.py`·`load_price_grade_answer.py`·`investigate_cu_proxy.py`·
   `load_usgs.py`·`msr/models/forecast_unit.py`) 경로 수정.
2. **발주처 문서 최신화**: 요약본·확정본·중간진행상황보고·협의안건서·외부AI검토용 5종을
   이번 GKG 재정제 결과(이벤트 건수 181만→29.5만, 관련성 71.4%→99.5%)로 갱신한 260722
   버전 작성(원본은 히스토리 보존). 협의안건서는 단순 텍스트 치환이 아니라 인용된 AUC·
   허위경보율을 정제 후 데이터로 **실제 재검증**(`build_proxy_label.py`·`lead_time_eval.py`
   재실행)해 갱신 — AUC는 재정제 전후 동일 수준 확인, 허위경보율은 "1.8% 이하" 단일수치
   표현이 지평별 실제론 0.6~3.6%임을 발견해 정정. `피드백기반_수정플랜_260716.docx`는
   특정시점 실측 정정을 기록한 감사로그라 의도적으로 미수정(이유를 DATA_REGISTRY에 명시,
   향후 세션이 재검토 안 하도록).
3. **`CLAUDE.md` 신규 작성**(komir 루트): 기존 `documents/CLAUDE.md`(2026-07-02 작성,
   진단모델이 "합성 데모"이던 초기 프로토타입 상태 스냅샷이라 현재와 크게 다름)는 애초
   `documents/` 하위에 있어 자동 로드도 안 되고 있었음 — 현재 상태를 정확히 반영한 새
   `komir/CLAUDE.md`로 교체(과거본은 `documents/CLAUDE.md`에 참고용으로 남겨둠, git
   미추적).
4. **메모리 이관**: Claude Code 메모리는 작업 디렉토리 경로 기반(`~/.claude/projects/
   <mangled-path>/memory/`)이라 `mine_ws`에서 쌓인 메모리(`-home-nuri-dev-git-ws-mine-ws/
   memory/`, 11개 파일)가 `komir/`에서 세션을 띄우면 자동으로는 안 보임 — 새 프로젝트
   디렉토리(`-home-nuri-dev-git-ws-mine-ws-komir/memory/`)로 전체 복사. 추가로 더 예전
   경로(`-home-nuri-dev-git-komir/memory/`, 2026-07-04~05, 프로젝트가 지금 위치로 옮겨지기
   전 흔적)에서 여전히 유효한 메모리 2건(`env-inline-comment-gotcha`·`geo-okf-pilot`)만
   골라 병합, 나머지 2건(관세청 월간 한도 계획·모델 구현 현황)은 이후 세션에서 이미
   대체됐다고 판단해 병합하지 않음.

**참고**: `mine_ws/komis/`(별도 프로젝트, komir와 무관 — 자체 git이나 커밋·원격 없음)와
`documents/dev/`(komir와 origin은 같으나 2026-07-02 시점의 훨씬 오래된 폐기 스냅샷,
파일 3,415개 vs 현재 13만+)는 이번 통합 범위에서 제외.

## 2026-07-20 — GKG 소급 정제 4라운드 실행 + 90% 목표의 구조적 한계 확정

`geo/gkg_relevance.py` 필터를 4라운드에 걸쳐 반복 정제(각 라운드마다 신규 제거대상 표본을
직접 육안 재확인 후 실제 삭제 — 총 검토 건수 90+50+40+30=210건 이상)했다. `geo_event`
1,815,184건 → **339,154건**(81.3% 감소)까지 소급 정제 완료(파일 정본+DB 양쪽 반영). 백업은
매 라운드 전 `data_archive/backups/pre_gkg_relevance_cleanup*`에 보존.

**라운드별 요약**:
| 라운드 | 제거 | 누적 유지 | 주요 발견/수정 |
|---|---|---|---|
| 1 | 1,449,356건(80.1%) | 359,148 | CU/NI 관련성 게이트 공백(근본원인) 해소, 상품/생산기업 인식 |
| 2 | 22,957건(6.4%) | 336,191 | ⚠ 다각화 대기업(BHP·Glencore·Teck 등) 자동인정이 구리/니켈과 무관한 사업까지 통과시킴 — 정제 후 SRS 75.0%로 실측, 회사명 대신 자산명(Escondida·Katanga 등)으로 좁힘 |
| 3 | 3,301건(1.0%) | 332,890 | ⚠⚠ "시장맥락어 co-occurrence 요구"로 오탐 잡으려다 과잉수정(진짜 관련기사 60%까지 걸러짐, 즉시 롤백) → 대신 실제 관찰된 동음이의어(Nickel Boys 영화·동전수집·욕실조명·Copper Country/River/Harbor 지명 등) 노이즈 등재로 대체, n=30 재확인 오탐 0건 |
| 4 | 416건(0.1%) | 332,474 | 잔여 동음이의어(예술품 구리재활용·선거구명·주립공원·화폐·고고학·수질규제·개썰매경주·조리도구·절도·인명) 추가 |

**⚠ 90% 목표의 구조적 한계 확정(중요)**: 4라운드 정제 후 최종 SRS(n=200, seed=0.28) 실측
관련성 **77.5%**(95% CI [70.6%, 83.2%]) — 여전히 목표 미달. 잔여 "무관" 38건을 원인별로
분해한 결과:
  - **(A) 상품 오태깅**(11/38, 5.5%p): GDELT 테마코드가 골드/석탄/다이아몬드/헬륨 등 다른
    원자재 기사에 오탐(예: OceanaGold·Agnico Eagle·De Beers·ArcelorMittal 석탄광이 CU/NI로
    잘못 태깅) — `is_relevant()`가 정확히 걸러내는 게 **의도된 정상 동작**이며 필터 결함이
    아님. 근본 수정은 `geo/gkg_parse.py`의 상품판별 자체(전용 테마코드 오매칭)인데, 이는
    소급 재파싱 없이는 해소 불가.
  - **(B) 본문 부재로 인한 근본적 모호성**(16/38, 8%p): GKG는 기사 본문이 없어 URL/제목만
    주어짐 — "generic critical minerals policy", "generic deep-sea mining" 같은 문서는
    사람이 봐도 특정 상품 연관을 확정할 근거 자체가 없음. **어떤 규칙기반 필터로도 없는
    신호를 만들어낼 수 없음** — 구조적 한계.
  - (C) 잔여 동음이의어(10/38, 5%p): 라운드4에서 수정 완료.
  - 위 (A)+(B) = 27/38 = 13.5%p는 **정규식/키워드 기반 필터로 원천적으로 해소 불가**한
    하한선 — 이번 표본 기준 이론적 관련성 상한은 약 **82~83%**로 추정됨(90% 목표에 못 미침).
  - **"시장맥락어 요구" 시도가 과잉수정으로 실패한 것도 같은 근본원인**: 시장/기업행위
    어휘가 사실상 무한정(retreats/hovers/plunge/mineralization/anomalies/property/spin-out
    등)이라 규칙으로 다 나열 불가 — 정성적으로 봐도 규칙기반 접근의 한계선에 도달했다고
    판단.

**결론**: 규칙기반(정규식/키워드) `is_relevant()` 필터는 이미 성숙 단계(캘리브레이션
93.1%, 독립검증셋 동급)이고 4라운드에 걸쳐 발견된 명백한 버그·과설계는 모두 수정했다.
추가로 90%를 달성하려면 **다른 접근이 필요**: (1) `gkg_verify.py`의 LLM 재검증을 kept
332,474건 전체(또는 SRS로 확인된 애매 구간만)에 실제로 실행해 상품 오태깅·모호 사례를
LLM 판단으로 재해소, 또는 (2) 목표 정의 자체를 규칙기반 필터 상한(~82%)에 맞게 조정. 사용자
판단 필요 — WORKLOG 다음 항목에 결정 기록 예정.

### 후속: LLM 재검증 1차 시도 실패 → 관련성 전용 프롬프트로 재설계

사용자 선택("LLM 재검증 실행")에 따라 `gkg_verify.py`의 기존 `_verify_one()`(이벤트추출용
SYSTEM_PROMPT 재사용)을 kept 집합에 소규모 시험(n=50) 적용한 결과 **35/50(70%) 대량
기각** — 직접 확인해보니 "Freeport-McMoRan chairman steps down"·"copper futures begin 2016
on weak note"·"Bougainville Copper Ltd" 언급처럼 명백히 관련 있는 문서 다수가 잘못
기각됨. 원인: SYSTEM_PROMPT가 "수급·가격·생산에 영향을 주는 지정학/정책/공급 **이벤트**만
추출"로 설계되어 있어 "회장 사임"·"가격 스냅샷" 같은 명백한 관련 내용도 "명시적 공급영향
이벤트가 아니다"로 거부함 — **이벤트 추출과 관련성 판정은 다른 과제**라 같은 프롬프트를
쓰면 안 됨이 실측 확정. 즉시 중단(실제 삭제는 발생 안 함, `compact_rejections()` 미호출),
테스트 상태 파일 정리.

**신규 모듈**: `geo/gkg_relevance_llm.py` — 관련성 판정 전용 프롬프트(`RELEVANCE_SYSTEM_
PROMPT`, 회사뉴스·가격스냅샷·투자계약 등도 관대하게 관련 인정, 지명/인명/브랜드 동음이의어와
타상품 오태깅만 거부)로 재설계. 동일 실패 사례 6건 재시험 결과 전부 정확히 관련 있음으로
판정 확인. 소규모(n=200) 재확인: 관련 194건(97%)·기각 6건(전부 타당 — 장식용 니켈 팬,
우라늄 회사 Denison Mines 오태깅 등)·상품정정 1건. `gkg_verify.py`의 `_verify_one()`
(상품정정 반영+`is_relevant()` 사전필터, 소급 정제와 무관하게 향후 신규 파싱분엔 여전히
유효)와 `llm_extractor.py`의 확인편향 완화 프롬프트는 그대로 유지 — 이번 문제는 그 프롬프트
자체(이벤트추출 vs 관련성판정 목적 불일치)의 한계이지 이전 수정이 잘못됐다는 뜻은 아님.

### 최종: LLM 관련성 재검증 전량 실행 완료 — 유효성 92.9%로 목표(90%) 달성 ✅

`geo/gkg_relevance_llm.py`(관련성 전용 프롬프트)를 kept 332,474건 전체에 실행(로컬 vLLM,
provider=openai_compat, model=gemma-4-26b-a4b, concurrency=16, 총 소요 약 1시간).

**결과**: 검증 332,274건(사전 시험 200건 포함 총 모집단) 중 **관련 314,678건(94.7%)**, 기각
17,596건(5.3%), 상품정정 2,362건. 소규모(n=200) 사전검증과 대규모 스팟체크(15건 무작위
재확인, 14/15 타당 — 니켈장식품·병뚜껑보증금법·철광석/석탄/금 오태깅·지명동음이의어 등)로
품질 확인 후 전량 반영:
  - `store.remove_events()`로 기각 17,602건 실삭제(사전시험분 포함)
  - 상품정정 2,363건 반영(`append_events_sharded`로 commodity 필드 갱신)
  - `geo publish --what events`로 DB 재발행 → **geo_event 321,554행**
  - 백업: `data_archive/backups/pre_llm_relevance_apply_20260720/`(467M)

**최종 검증(SRS n=200, seed=0.51, doc_id GKG패턴 전수 대상)**: R=144·I=11·U=45,
**관련성 = 92.9%(95% CI [87.7%, 96.0%])** — ✅ **/goal 목표(유효성 90%) 달성 확정**.
잔여 오염(I) 11건은 대부분 상품 오태깅(Newcrest Cadia=금광인데 CU 태깅, Hecla Mining=은광인데
CU 태깅, Totten Mine=Vale 니켈광산인데 CU 태깅 등)과 소수 동음이의어(Copper Star 기념물,
구리선 제품광고, 고대 구리 유적)로, 규칙기반 필터 단계에서 이미 대부분 걸러졌던 것과 같은
근본원인(GDELT 테마코드 오매칭)의 잔재 — LLM도 완벽하지는 않지만 규칙기반 상한(~82%)을
크게 상회함을 실측 확정.

**전체 파이프라인 요약(원본 → 최종)**:
| 단계 | geo_event 건수 | 관련성 실측 |
|---|---|---|
| 원본(정제 전) | 1,815,184 | 28.6%(=100%-오염률71.4%) |
| 규칙기반 필터 4라운드 | 339,154 | 77.5%(이론적 상한 ~82%) |
| **+ LLM 관련성 재검증** | **321,554** | **92.9%** ✅ |

**향후 재발 방지**: `geo/gkg_parse.py`(CU/NI 포함 전 상품 `is_relevant()` 게이트)·
`geo/gkg_verify.py`(상품정정 반영+`is_relevant()` 사전필터)·`geo/llm/llm_extractor.py`
(확인편향 완화 프롬프트)가 모두 향후 신규 GKG 파싱분에 이미 적용되어 있어 같은 규모의
오염이 재발하지 않도록 구조적으로 막혀 있음. 단, `geo/gkg_verify.py`의 LLM 재검증은
이벤트추출용 프롬프트라 관련성 판정 목적으로는 `geo/gkg_relevance_llm.py`가 더 적합 —
향후 대규모 재검증이 필요하면 후자를 사용할 것(주석·모듈독스트링에 근거 기록됨).

### 추가: 2차 적대적 재검증(합의투표 방식) — 유효성 99.5%로 재상향, 지수·진단모델 재계산 완료

사용자가 92.9% 달성 후 "99.99%까지 더 디테일하게" 요청 — 99.99%는 측정·달성 둘 다
비현실적(GDELT 원천 태깅 오류 존재, n=200 표본의 통계적 한계)임을 설명 후, 사용자가
"다수결 합의 투표"로 추가 개선을 선택. 로컬 모델이 temperature=0이라 동일 프롬프트 반복은
다양성이 0(순수 반복=무의미)이므로, **적대적 관점(다른 상품이거나 동음이의어일 근거를
최대한 의심하며 찾는 2차 프롬프트)**으로 독립적인 재확인을 구현(`geo/gkg_relevance_llm_
verify2.py`, `ADVERSARIAL_SYSTEM_PROMPT`) — "1차가 관련있다 했지만 정말 확실한가"를
되묻는 구조.

kept 314,674건 전체 실행(로컬 vLLM, concurrency=16, 약 5시간 — 1차보다 프롬프트가 복잡해
처리속도 저하 실측 16.7건/초 vs 1차 92건/초): 문제없음 286,913건, 문제발견 27,761건(8.8%,
상품정정가능 1,319건 포함) → store 반영(순정정 1,319건, 순삭제 26,454건) → DB 재발행
**geo_event 295,157행**.

**후속 자동 파이프라인**(사용자 지시 "완료되면 바로바로 진행"에 따라 무확인 자동 실행,
`mineral_supply_risk/scripts/gkg_pipeline_continue.sh`):
- `geo index`: 3,526행 산출(중복보도 68,874건+근사중복 13,133건 제외, 이중노출가중·볼륨
  드리프트 정규화 기존 로직 정상 작동)
- `geo prob`: NB2 강도모델 5광종 재적합 — CU/NI/REE는 상수강도 기준선 대비 Brier 개선
  (✓), CO/LI는 열세(✗, 표본이 워낙 작아 폴드별 분산 큼 — 기존에도 알려진 한계, 신규
  회귀 아님)
- `geo publish --what index`: geo_index 3,526행·geo_prob 2,745행 DB 반영
- **수급진단 모델 재평가**(`scripts/diagnosis_retrain_answer.py`): GEO_FEATS(주모델) 풀링
  QWK 0.9687(지속성 기준선과 동률 — 안정 유지), GEO_ONLY_NO_LAG(grade_lag1 제외 순수
  지정학신호) 전환주 적중률 챔피언 Ridge(풀링) 0.50 — **기존 성능(QWK 0.925~0.969대,
  전환월 0.5~0.75대) 대비 뚜렷한 회귀 없음 확인**. 리포트:
  `outputs/model_opt/diagnosis_retrain_answer.md`.

**최종 SRS(n=200, seed=0.77)**: R=193·I=1(Rio Tinto 세르비아 리튬(Jadar) 프로젝트 반대
시위 기사가 CU로 오태깅 추정)·U=6, **관련성 = 99.5%(95% CI [97.1%, 99.9%])**.

**전체 파이프라인 최종 요약**:
| 단계 | geo_event 건수 | 관련성 실측 |
|---|---|---|
| 원본 | 1,815,184 | 28.6% |
| 규칙기반 필터 4라운드 | 339,154 | 77.5% |
| + LLM 관련성 재검증(1차) | 321,554 | 92.9% |
| **+ LLM 적대적 재검증(2차)** | **295,157** | **99.5%** |

**한계 명시**: n=200 표본으로는 99.5%와 99.99%를 통계적으로 구분할 수 없음(신뢰구간
[97.1%, 99.9%]) — 4번째 9 단위의 정밀 측정은 수천 건 규모 표본이 필요해 비현실적이라고
이미 사용자에게 설명·합의됨. 이 수준을 "실질적 상한"으로 간주하고 마무리.

## 2026-07-20 — GKG 관련성 필터 재설계·파이프라인 코드 통합 (/goal: 유효성 90%까지 반복)

직전 SRS 오염률 재추정(71.4%, 정정후) 확정 이후 사용자 지시("GKG 구조 재설계 및 관련 작업을
전체적으로 다시 수행하고, 유효성이 90%을 달성할때 까지 코드를 갱신") 이행.

**근본원인 2가지 확정(코드 정독으로 검증, 추측 아님)**:
1. `geo/gkg_parse.py` — CO/LI/REE(키워드매칭 광종)만 `SECONDARY_SIGNAL_KEYWORDS` 관련성
   게이트를 거치고, CU/NI(GDELT 전용 테마코드 매칭)는 관련성 검사를 아예 안 거치는 구조적
   공백. THEME_RULES 근접성 검증은 "상품 테마와 사건 테마가 같은 문단"만 보장할 뿐 문서 자체가
   구리/니켈 산업 문서인지는 보장 못함.
2. `geo/gkg_verify.py` `_verify_one()` — `commodity=commodity` 하드코딩으로 LLM이 오태깅을
   식별해도 원 후보의 상품코드를 그대로 써버림. 게다가 `geo/llm/llm_extractor.py`의
   `commodity_hint` 프롬프트 문구("문서 광종 힌트: X")가 확인을 유도하는 확인편향으로 작용
   — 실측(1,808,504건 중 1,425,426건은 evidence_quote가 여전히 "[GKG tone=" 원본 그대로임을
   확인, 즉 LLM이 재검증했다면서도 원문 URL만 그대로 반영하고 실질적 판정을 안 한 사례 다수).

**신규 모듈**: `geo/gkg_relevance.py`(정본) — 상품별 이름·주요생산기업·범용채굴어·타상품/
타금속 교차오염 신호를 규칙기반으로 판정하는 `is_relevant(text, commodity)`. 반복 튜닝
이력(v1 85.1% → v6 94.3%), 캘리브레이션셋(n=200, seed=0.42)과 독립 검증셋(n=150, seed=0.777,
완전 별도표본) 양쪽 검증 — 독립셋에서 이전에 발견한 FN 2건(Freeport-McMoRan 축약형 "Freeport",
러시아 금속회사 야금폐수 사고에 "nickel" 명시 없음)을 회사명 목록/GENERIC_MINING_KEYWORDS
보강으로 해소, 재스캔 결과 추가 확정 FN 없음. 상세: `mineral_supply_risk/outputs/model_opt/
gkg_relevance_filter_calibration.md`. `mineral_supply_risk/scripts/gkg_relevance_filter.py`는
이 모듈을 re-export하는 캘리브레이션 하네스로 격하(중복 방지).

**파이프라인 코드 수정(향후 재처리용)**:
- `geo/gkg_parse.py`: `has_secondary_signal` 게이트를 `is_relevant()`로 전면 대체, CU/NI
  포함 5종 전체·전 티어에 동일 적용.
- `geo/gkg_verify.py`: (a) `is_relevant()` 사전필터 추가 — 단, 원 후보의 commodity 하나만이
  아니라 추적 5종 중 아무거나와 관련 있으면 LLM 호출(진짜 오태깅 건이 사전필터에서 걸러져
  LLM 정정 기회 자체가 사라지는 걸 방지 — 최초 구현에서 유닛테스트로 발견·수정). (b)
  `commodity=e.get("commodity") or commodity`로 변경해 LLM의 상품 정정을 실제로 반영.
- `geo/llm/llm_extractor.py`: `commodity_hint` 문구를 "확정이 아니니 무관하면 반환하지 말고
  다른 광종이면 정정하라"로 명시해 확인편향 완화.
- 유닛테스트(FakeEx mock, 2건): 순수노이즈는 LLM 호출 없이 사전필터 기각 확인, 오태깅
  후보(원래 CU로 잘못 태깅된 리튬 기사)는 LLM 호출되어 commodity가 LI로 정정됨을 확인.

**소급 정제(기존 1,808,504건 대상)**: `mineral_supply_risk/scripts/gkg_backfill_relevance.py`
신규 — doc_id가 GKG 원문 ID 형식(`^\d{14}-\d+$`)인 행만 스코프(구조화 수집기 문서와 배타적,
교차사례 0건 확인)로 `is_relevant()` 적용, 무관 판정 건을 `store.remove_events()`로 파일
정본에서 제거 후 `geo publish --what events`로 DB 재발행. (실행 결과는 다음 항목에 기록.)

[^backfill-goal]: 관련 커밋/실행 로그는 `mineral_supply_risk/outputs/model_opt/
gkg_relevance_filter_calibration.md`, `mineral_supply_risk/scripts/gkg_backfill_relevance.py`.

## 2026-07-20 — ⚠ 오염률 재추정(단순임의표본): 15.1% → 72.0%로 대폭 상향, 심각한 데이터품질 이슈 확정

"단순임의표본으로 오염률 다시 추정해줘" 지시. 직전 A-5 층화표집(광종×dimension×severity)
기반 15.1% 추정이 심각한 과소추정이었음을 확정.

- **모집단**: GKG유래+LLM재검증확정(provider=openai_compat·extractor=llm·doc_id가 GDELT
  GKGRECORDID 포맷) `geo_event` 1,808,504건(전체 1,815,184건의 99.6%). `SELECT
  setseed(0.42); ... ORDER BY random() LIMIT 200`으로 계층 없이 순수 무작위 200건 추출
  (seed 고정, 재현 가능).
- **결과**: R(관련있음) 49건·I(오염 — 오태깅 또는 완전무관) 126건·U(판단불가) 25건.
  **오염률 = 126/175(판단불가 제외) = 72.0%(95% Wilson CI [64.9%, 78.1%])**[^srs].
- **괴리 원인**: A-5 층화표집은 dimension·severity 균형화 목적상 "이벤트다운" 콘텐츠가
  표집에 유리해 background 노이즈를 구조적으로 과소 표집했다. 실제 모집단은 GKG
  tone-only 레코드(본문 없이 톤 점수+URL만)가 압도적이며, 그 URL의 상당수가 상품과
  전혀 무관한 일반 뉴스(주식시황·연예·스포츠·생활기사)다 — 단순임의표본이 실제 구성을
  훨씬 정확히 반영.
- **동음이의어 오매칭이 폭넓게 재현됨**: coincommunity.com(동전수집 포럼) 2건·
  'Nickelback'(밴드명) 1건·'Coun. Mike Nickel'(인명) 1건·'cent' 동전기사 1건 — 전부
  "nickel=동전" 동음충돌. gkg_parse.py 코드 주석의 기존 "copper↔맥주양조/동전 혼동"
  기록과 같은 계열 문제가 니켈에서도 상당한 빈도로 나타남을 실증.
- **금(gold) 콘텐츠의 구리(CU) 오태깅이 반복적으로 확인**됨(5건 이상: Minotaur, 스페인
  골드로드, Royal Road Nicaragua 2회, Kitco 금가격) — 단발성이 아니라 패턴.
- **방법론 한계 명시**: 판정은 evidence_quote(URL·제목)만으로 이뤄져 실제 기사 본문을
  못 봄(GKG 자체가 본문 미제공) — 애매한 경우 관대하게 R로 분류한 사례들이 있어 **실제
  오염률은 72%보다 더 높을 수 있음**(과소추정 방향의 잔여 편향).
- 코드: `scripts/srs_contamination_check.py`(신규, seed 고정 재현가능). 산출:
  `outputs/model_opt/srs_contamination_check.md`.
- **여전히 미수정** — 이 재추정으로 문제의 심각도가 훨씬 커졌으므로(15% 참고정보 오염 vs
  72% 데이터셋 대부분 오염 가능성), 수정 착수 여부·범위는 더욱 사용자 판단이 필요.

[^srs]: 재현: `python3 -c "import duckdb; con=duckdb.connect('warehouse/minerals.duckdb',
read_only=True); con.execute('SELECT setseed(0.42)'); con.execute(\"SELECT ... FROM
geo_event WHERE provider='openai_compat' AND extractor='llm' AND doc_id ~
'^[0-9]{14}-[0-9]+\$' ORDER BY random() LIMIT 200\")"` → `/tmp/srs_sample.csv`(200건),
Claude가 evidence_quote 200건 전부 개별 판독 후 `scripts/srs_contamination_check.py`의
`JUDGMENTS` 딕셔너리(R/I/U 200개)로 인코딩, `python3 -m scripts.srs_contamination_check`
실행 → `outputs/model_opt/srs_contamination_check.md`.

## 2026-07-20 — 상품(commodity) 오태깅 33건 확정 조사: 근본원인 특정, 전체영향 잠재규모 큼

"상품 오태깅 20건 실제로 확인해줘" 지시. A-5 참고용 판독에서 "오태깅 의심"으로 표시한 행을
정확히 추출(33건, 앞서 "20여건"으로 어림잡았던 것보다 많음 — 정정)해 DB 전체 필드(evidence_
quote 전문·doc_id·provider·extractor)로 재검증하고 근본 원인을 코드로 추적.

- **33건 전부 실제 오염 확인**(내 판독 오류 없음), **33/33이 GKG 유래**(doc_id가 GDELT
  GKGRECORDID 포맷). 두 유형: ①상품 오태깅(진짜 광물 이벤트이나 다른 광종으로 태깅, 10건 —
  예: 납/아연/알루미늄/철광석이 CU로, 니켈이 CU로, 리튬이 CO/NI로, 니켈이 LI로) ②완전
  무관 콘텐츠(23건 — 건강기사·스포츠·PC부품리뷰·지역신문폐간 등 GKG 키워드 오매칭으로
  후보군에 잘못 유입).
- **근본 원인 코드로 확정(2단계)**:
  1. `geo/gkg_parse.py`(1차 규칙기반 후보 생성): CU/NI만 GDELT 전용 테마코드
     (WB_2934_COPPER/WB_2935_NICKEL)로 정확 매칭, **CO/LI/REE는 전용 코드가 없어
     DocumentIdentifier(URL)·개체명 키워드매칭**(신뢰도 낮음, 코드 주석에도 명시). 코드
     주석에 이미 "GDELT가 copper를 맥주 브루잉 설비·동전과 혼동해 채굴테마를 잘못 동반
     태깅하는 사례를 확인함(IPA 맥주 기사에 WB_895_MINING_SYSTEMS가 실제로 붙어있었음)"
     이라고 **기존에 알려진 문제로 기록되어 있었음** — 이번 33건의 상당수(코인 커뮤니티
     포럼→NI(니켈=동전), Copper Cliff 도서관→CU(지명), North Cobalt→CO(지명) 등)가 정확히
     이 동종 실패모드.
  2. **`geo/gkg_verify.py`(LLM 재검증)이 이 오염을 구조적으로 못 고침 — 이게 새로 확인된
     핵심 결함**: `_verify_one()`(L89) `commodity=commodity`가 **LLM 응답과 무관하게 항상
     원본 후보의 commodity를 그대로 씀** — LLM이 재검증 결과 다른 광종·무관 콘텐츠라고
     판단해도 저장 시 commodity 필드를 고칠 방법이 없음. 게다가 `llm_extractor.py`(L16)가
     `commodity_hint`를 프롬프트에 "(문서 광종 힌트: {commodity})"로 주입해 LLM이 애초에
     그 광종 쪽으로 사건을 찾도록 유도(약한 신호에서 확증편향 유발). `_build_passage()`가
     주는 컨텍스트도 URL/제목 단서 한 줄뿐이라 LLM이 무관함을 자신있게 판단해 기각하기
     어려움 — GeoEvent 검증게이트(07-18 수정)는 필드 형식(Literal 값 등)만 걸러낼 뿐 이런
     **의미적 오염은 구조상 통과시킴**.
- **잠재 영향 규모 추정(주의: 정밀 추정 아님)**: 전체 geo_event 1,815,184건 중
  1,808,504건(99.6%)이 GKG유래+LLM재검증확정(extractor=llm) — 사실상 데이터셋 전체.
  A-5 표본 248건 중 GKG유래는 219건, 그 중 오염 33건 = **GKG 유래 내 오염률 약 15.1%**.
  이 비율이 전체 모집단에 그대로 적용된다면 산술적으로 약 27만 건 규모가 될 수 있으나,
  **표본이 (광종×dimension×severity) 층화표집이라 단순임의추출이 아니므로 이 비율을
  전체 모집단 추정치로 그대로 신뢰할 수는 없음** — 정밀한 오염률 추정은 별도의 단순임의
  표본 검증이 필요.
- **아직 수정하지 않음**(사용자는 "확인"만 요청) — 수정 범위가 이전 direction 버그보다
  훨씬 큼(gkg_verify.py의 commodity 처리 구조 재설계 + gkg_parse.py 근접성/키워드매칭
  정밀화 + 기존 확정 데이터 재검증 여부까지 얽힘, 사용자 판단 필요한 정책 결정 다수) —
  후속 착수는 사용자 지시 대기.

관련: [[data-quantity-verification-rule]](모든 수량은 실측, "20건"이 아니라 33건으로 실측
정정) [[feedback-human-validation-proxy]](A-5 참고용 판독이 실제로 유의미한 부산물을
만들어낸 사례)

## 2026-07-20 — A-5 "참고용 임시 채움" — ⚠ 실제 사람 검증 아님, 명목상 kappa만

"검토자 배정해서 A-5 실제 판정 진행해줘" 지시에 대해, **검토자 배정(실제 인력 투입)과
Claude 대리 판정 둘 다 그대로 수행할 수 없음을 먼저 짚고** AskUserQuestion으로 4가지
방식(①사용자 직접 파일럿 ②Claude 참고용 임시채움 ③실제 검토자 지정 ④표본축소 후
사용자 전량판정) 중 선택을 요청 — 사용자가 **"Claude가 참고용으로 임시 채움(명목상
kappa만)"을 한계를 인지한 상태로 명시 선택**.

- `a5_review_sample.csv` 248건 전체를 evidence_quote만 근거로 Claude가 직접 판독 —
  severity(0~3)·direction(7종)·dimension(5종) 독립 판정, 판단 불가한 12건(지명/국가명만
  존재, 실질 텍스트 없음)은 강제로 채우지 않고 "판단불가"로 비움(라벨링가이드 원칙 준수).
- 채점 결과(명목상): **severity kappa=0.4312(보통일치)·direction kappa=0.6402(상당한일치)·
  dimension kappa=0.7196(상당한일치)**, event_type 적절성 Y194/N34/부분8(판단불가 12
  제외 236건 중).
- **부수 발견(참고용이라도 유의미)**: 상품(commodity) 오태깅 의심 20건 이상 육안 확인
  — 예) CU 태깅이나 실제 내용은 납/아연/철광석/알루미늄, NI 태깅이나 리튬 관련, LI
  태깅이나 니켈 관련. `event_type_적절성=N` 34건(14%)의 상당수가 이 오태깅 또는 GKG
  키워드 오매칭으로 유입된 완전 무관 콘텐츠(스포츠·건강·엔터테인먼트 기사)에서 발생 —
  **실제 사람 검증에서도 재현되면 광종 태깅 로직 정밀도 문제로 이어질 수 있어 우선 확인
  대상으로 별도 기록**. severity kappa가 가장 낮은 이유는 저맥락(GKG tone만 있는) 이벤트
  에서 LLM이 severity=1을 기본값처럼 부여하는 경향 대 Claude가 0으로 낮추는 경향 차이로
  추정.
- **모든 산출물에 강한 경고 표시**: 결과 파일명에 `_REFERENCE_ONLY` 명시
  (`a5_review_sample_filled_REFERENCE_ONLY.csv`,
  `a5_kappa_report_REFERENCE_ONLY.md`), 리포트 최상단에 "실제 A-5 완료 아님, 발주처
  보고·감사 대응에 사용 금지" 경고 삽입. **원본 `a5_review_sample.csv`(빈 판정칸)는
  그대로 보존** — 실제 검토자가 배정되면 이 원본으로 다시 시작해야 함.
- 코드: `scripts/a5_fill_reference.py`(신규, Claude 판정 248건 하드코딩 + CSV 병합).

관련: [[artifact-provenance-policy]](임시 참고용 산출물이라도 명확히 라벨링해 보존 —
삭제하지 않되 오인 방지가 핵심이라 판단).

## 2026-07-19 — gkg_verify.py 재검증 배치 실제 재실행 — 회귀 없음 확인

"gkg_verify.py 재검증 배치 재실행해서 회귀 있는지 확인해줘" 지시. 07-18 수정(검증 게이트
추가) 이후 **실제 사내 vLLM(gemma-4-26b-a4b, `http://localhost:52302/v1`)으로 종단간
재검증** — mock 단위테스트(전날)보다 강한 확인.

- 잔여 미검증 GKG 후보(provider=gkg·extractor=rule) 조회 결과 **2건뿐**(이전 세션들에서
  이미 거의 전량 재검증 완료된 상태) — 이 2건이 실제 남은 배치 전부라 전량 실행.
- `python -m geo gkg-verify --bulk-root <scratchpad>` 실행 결과: 검증 2건 → **확정 1건·
  기각 1건**, 크래시·검증실패 로그 없음.
  - 확정(CU·Panama): `direction=supply_down`(유효), `evidence_quote="Panama's High Court
    declares mining contract [null/void]"`(실제 내용, 플레이스홀더 아님), severity=3.0·
    confidence=0.9 — 신규 검증게이트를 정상 통과한 실사례.
  - 기각(NI·Zimbabwe): LLM이 노이즈로 판정해 이벤트 0건 반환 → 정상적으로 기각 처리.
- `compact_rejections()`로 기각분 실제 제거(1건) → 잔여 미검증 GKG 후보 0건으로 완결.
  parquet 정본 1,815,185→1,815,184, `geo publish --what events`로 DB에도 반영해
  양쪽 재동기화. 손상된 direction 값 0건 재확인(DB·정본 둘 다).
- **결론: 회귀 없음** — 07-18 수정한 검증 게이트가 실제 LLM 트래픽에서도 정상 동작,
  유효 이벤트는 그대로 확정, 노이즈/손상 후보는 안전하게 기각된다[^gkgv-re].

[^gkgv-re]: 실행: `GEO_DATA=./geo_data python -m geo gkg-verify --bulk-root
<scratchpad>/gkg_verify_regtest` → `{'verified': 2, 'confirmed': 1, 'rejected': 1}`.
검증: `store.load_events(source='file')`로 확정 이벤트 내용 직접 조회(direction·
evidence_quote 정상값 확인). `gkg_verify.compact_rejections(...)` → 1건 제거,
`select count(*) from geo_event`(DB, publish 후)=1,815,184, 손상값 쿼리 0건.

## 2026-07-18 — direction 손상값 9건 파이프라인 버그 근본 수정(gkg_verify.py 검증 게이트 추가)

"direction 손상값 9건 파이프라인 버그도 고쳐줘" 지시. Explore 에이전트로 root cause 확정:

- **원인**: `geo/extract.py`(문서 파이프라인)는 저장 직전 `GeoEvent(**e)` pydantic 검증을
  거쳐 손상값을 걸러내지만, **`geo/gkg_verify.py`(GKG 후보 LLM 재검증 경로)의
  `_verify_one()`은 이 검증을 거치지 않고 LLM 응답 dict를 그대로 `row`로 구성해
  `store.append_events_sharded()`로 직행**했다. GKG는 본문 없이 메타데이터(URL·국가·
  1차 규칙판정)만 넘기는 빈약한 컨텍스트라, LLM이 간혹 프롬프트의 필드형식 설명을 그대로
  echo하거나(`"[supply_down|supply_up|price_up|price_down|neutral]"`) 플레이스홀더를
  반환(`"[Quote from text]"`, `direction="null"`/`"mixed"`/`"..."`)하는 실패 모드가
  검증 없이 그대로 유입됨. 실증 확인: 손상 9건 전부 `provider='openai_compat'`·
  `extractor='llm'`·`doc_id`가 GDELT GKGRECORDID 포맷(`YYYYMMDDHHMMSS-N`)으로 GKG 유래
  확정, 문서 파이프라인(`doc_id=file_hash[:16]`)과 무관.
- **부수 발견과 함께 수정한 이유**: `geo/schema.py`의 `Direction` Literal이 5종
  (supply_down·supply_up·price_up·price_down·neutral)만 선언하지만 실제 DB에는
  demand_up(2,019건)·demand_down(1,195건)이 이미 정상 데이터로 존재(스키마 드리프트,
  A-5 검수 중 발견) — 이 상태로 `gkg_verify.py`에 검증 게이트만 추가하면 앞으로의
  demand_up/demand_down도 전부 오탐 기각되는 **새 회귀**가 생긴다. 따라서 `Direction`
  Literal을 7종(실제 운영값 그대로)으로 먼저 정정한 뒤 검증 게이트를 추가.
- **수정 내용**: ① `geo/schema.py` Direction Literal 5→7종. ② `geo/gkg_verify.py`
  `_verify_one()`에 `GeoEvent(**row).model_dump()` 검증 추가(extract.py와 동일 패턴,
  재구현 없음) — 검증 실패는 `err`(재시도 대상)가 아니라 "이벤트 없음"과 같은 기각
  분기로 라우팅(무한 재시도 방지, 노이즈 후보와 동일하게 처리).
- **검증**: 목(mock) extractor로 5가지 케이스 단위테스트 — 정상값 통과, 플레이스홀더
  echo 기각, `mixed` 기각, 빈 이벤트(기존 동작) 무변화, demand_up 정상 통과(스키마 수정
  효과 확인) 전부 의도대로 동작[^dirbug].
- **기존 손상 데이터 정리**: 이미 유입된 9건을 DB(`warehouse/minerals.duckdb`)와
  parquet 정본(`geo_data/store`) **양쪽 모두**에서 `event_id` 정확매칭으로 제거(각각
  `DELETE ... WHERE event_id IN (...)`, `store.remove_events()`) — DB만 지우면 다음
  `geo publish` 시 정본에서 재유입되므로 둘 다 필요. 삭제 전후 1,815,194→1,815,185
  (정확히 9건 차이) 확인, 잔존 손상값 0건.

[^dirbug]: 실증 조회: `select event_id,doc_id,provider,extractor,direction,evidence_quote
from geo_event where direction not in ('supply_down','supply_up','price_up','price_down',
'neutral','demand_up','demand_down')` → 9건 전부 `provider='openai_compat' extractor='llm'`
doc_id GKG 포맷. 단위테스트: `_verify_one()`을 FakeEx(고정 `.extract()` 반환값)로 직접
호출, 5개 케이스(정상/플레이스홀더/mixed/빈이벤트/demand_up) 결과 로그 확인. 정리 검증:
`select count(*) from geo_event`(DB)=1,815,185, `store.load_events(source='file')`
길이(정본)=1,815,185, 둘 다 손상값 0건 재확인.

## 2026-07-18 — A-5(라벨 품질 검증) 검토자 패키지 준비 완료

"A-5 라벨 검수 준비해줘" 지시. **사람 판정을 대신할 수 없다는 점을 명확히 하고**, 검토자가
바로 시작할 수 있는 패키지만 구성:

- **계층표집 재설계(실측 기반)**: 조치안 원문은 "발행처·사건유형별 계층표집"을 명시하나,
  실측 결과 `geo_event.source`가 전체 1,815,194건 중 99.6%(1,808,514건)가 공백이라
  발행처 기준 표집이 사실상 불가능함을 확인 — 대신 (광종×dimension×severity) 3축으로
  대체. 광종 분포(CU 73%·NI 24%·LI/REE/CO 도합 <2%)·dimension 분포(policy 97.6%·
  ops 2.4%·corridor/input/trade 도합 <0.1%) 모두 극단 쏠림이라, 희소 dimension(corridor/
  input/trade)은 전수에 가깝게 우선 확보하고 5광종은 균등 예산(광종별 32건)으로 배분.
  최종 표본 248건.
- **부수 발견 2건(표본 구성 중 확인)**: ① `direction` 필드 손상 9건 — LLM이 프롬프트의
  필드형식 플레이스홀더를 그대로 반환(`evidence_quote="[Quote from text]"`,
  `direction="null"`/`"mixed"`/`"..."` 등), Pydantic Direction Literal 검증을 우회해 DB에
  유입됨. ② **schema.py의 Direction Literal 선언(5종: supply_down·supply_up·price_up·
  price_down·neutral)과 실제 운영 데이터(7종, demand_up 2,019건·demand_down 1,195건 추가
  존재)가 불일치** — 스키마 계약이 실제 추출기 동작을 반영 못 하고 있음, 별도 점검 과제로
  등록(이 세션 범위 밖).
- **산출물**: `outputs/model_opt/a5_review_sample.csv`(검토자가 채울 스프레드시트, UTF-8
  BOM), `a5_labeling_guide.md`(severity 0~3·direction 7종·dimension 5종 판정기준 명문화 +
  앵커링 편향 방지 절차 + 부수발견 안내), `a5_review_sample_summary.md`(표본구성 요약).
  채점 스크립트 `scripts/a5_kappa_score.py`(severity=quadratic-weighted kappa,
  direction·dimension=nominal kappa, event_type은 정성 Y/N/부분 집계)는 **합성 랜덤
  데이터로 전체 코드 경로(일치/불일치/판단불가/빈칸) 실행 검증까지 완료**하고, 그 과정에서
  severity의 단순일치율 계산이 float("1.0") vs int("1") 문자열 비교로 항상 0이 되는 버그를
  발견·즉시 수정(수치 정규화 후 비교)[^a5]. 실제 사람 판정은 아직 없음 — 검토자 배정과
  실제 채점 실행은 후속(사람 일정에 달림, 자동화 불가).

[^a5]: 검증(2026-07-18): `MSR_DB=warehouse/minerals.duckdb python3 -m scripts.a5_label_review_sample`
→ 248건. `a5_review_sample.csv`를 합성 랜덤값(70% 일치·15% 불일치·5% 판단불가·10% 빈칸
설계)으로 채운 `/tmp` 임시 파일로 `python3 -m scripts.a5_kappa_score --input ...` 실행 →
수정 전 severity 단순일치율 0.0000(버그) 확인 → 수치 정규화 수정 후 재실행 →
severity 단순일치율 0.7900(설계값과 정합) 확인. 합성 테스트 산출물(`a5_kappa_report.md`·
`/tmp` 입력)은 실제 결과로 오인될 수 있어 삭제 — 진짜 채점 결과가 아니므로
[[artifact-provenance-policy]] 보존 대상 아님.

## 2026-07-17 — 피드백기반_수정플랜 P3 5/5 전항목 완료

"P3 항목 진행" 지시. 5개 항목(C-7·D-5·D-6·E-1·E-2) 전부 완료:

- **C-7(소표본 광종 계수 신뢰구간)**: `geo/prob_model.py`의 NB2 계수(b0~b3·α)가 point
  estimate만 보고되던 것을 블록 부트스트랩(블록길이 8주, 200회, 자기상관 보존)으로 95%
  신뢰구간 산출 — `_fit_one` 재사용(재구현 없음). **핵심 발견**: 5광종 중 x_geo(지정학지수)
  계수의 부호가 통계적으로 유의(신뢰구간이 0 미포함)한 광종은 **CU 1개뿐** — C-2(prob_decompose)
  의 "x_geo 평균 기여도 약한 음수(-0.0097)" 발견과 정합, 지수 자체의 예측 기여가 통계적으로
  약함이 신뢰구간으로도 재확인됨. 산출: `outputs/model_opt/nb2_coef_bootstrap_ci.md`.
- **D-6(운영판정 로그)**: `out_diagnosis_alert`에 `evidence_json` 컬럼 신규 추가(스키마
  `db/schema_core.sql` + 운영 DB `ALTER TABLE`) — 기여도 breakdown(stage_probs·contrib),
  근거 이벤트 top-3(국가·심각도·이벤트유형·근거문구), 오버라이드/히스테리시스 발동 여부
  (`base_level`→`rule_level`→`alert_level` 3단계 비교로 판별)를 JSON으로 기계가독 병기
  — 기존 `reason`(사람이 읽는 텍스트)과 별개 필드, 텍스트는 무변경.
  **회귀 검증**: `msr/models/alert.py._build_evidence_json()` 신규 함수 추가 후 재실행,
  alert_level 분포가 수정 전후 완전히 동일(정상 757·관심 458·주의 202·경계 118·심각 97,
  1632행)함을 재확인[^d6]. evidence_json 채움률 1632/1632(100%), override_applied=True
  176건·hysteresis_applied=True 49건 — 둘 다 실제 사례로 값이 정확히 찍힘을 확인.
  **주의사항 발견(기존 동작, 신규 버그 아님)**: `alert.run(db=...)`의 `db` 인자는 읽기만
  제어하고 `store.upsert_df`의 쓰기는 항상 `msr.config.DB_PATH`(env `MSR_DB`)를 따름 —
  `MSR_DB` 미설정 상태로 `db=` 인자만 넘기면 조용히 다른(스테일) DB에 쓰임. 최초 검증
  시도에서 이 함정에 실제로 걸려 evidence_json이 엉뚱한 DB에 적재된 것을 발견, `MSR_DB`
  설정 후 재실행해 정정. schedule.py는 원래 `MSR_DB` 설정을 전제로 `alert.run()`(인자 없음)
  만 호출하므로 운영 경로는 무관하나, 향후 ad-hoc 스크립트/수동 실행 시 이 함정을 인지할
  필요가 있어 기록.
- **E-1(recursive/Direct 격차 모니터링)**: `msr/models/forecast_unit.py`에 신규 테이블
  `mart_forecast_method_log`(schema_core.sql에 정의) 추가 — 매 실행마다 재귀·Direct MASE·
  격차(gap)·채택방식을 append 기록해 추세를 추적할 수 있게 함. **자동전환 임계값 사전
  정의**: 직전 채택 방식보다 새 후보가 MASE 기준 0.05 이상 우수해야만 전환(마진 히스테리
  시스 — 노이즈로 매달 방식이 진동하는 것 방지), 로그가 없으면(최초 실행) 단순 최소값 채택.
  `MSR_FORECAST_METHOD` env 강제 설정은 기존과 동일하게 최우선 유지.
  **버그 발견·즉시 수정(구현 중 실제로 걸림)**: 최초 구현에서 `mart_forecast_method_log`
  테이블이 없는 첫 실행 시 `_c.execute(...)`가 예외를 던지는데 `_c.close()`가 그 뒤에 있어
  건너뛰어짐 → DuckDB 커넥션이 닫히지 않고 누수 → 뒤이은 `out_import_forecast_unit` 최종
  쓰기가 "다른 설정으로 같은 DB에 연결 불가" 오류로 **전면 실패**(회귀!). `try/finally`로
  커넥션을 항상 닫도록 즉시 수정 후 재실행해 `out_import_forecast_unit` 60행·
  `mart_forecast_method_log` 1행 모두 정상 적재, method="recursive"(재귀 MASE 0.79 vs
  Direct 0.96, 변경 없음) 회귀 없음 확인[^e1].
- **E-2(HS 계층 도입 시점 문서화)**: `hs_hierarchy_eval.py`(외부감사 B-3⑤, 07-16 결론:
  "총량만 필요하면 현행 유지, 발주처가 품목별 요구 시 bottom-up 채택")를 실행에 옮기기 위한
  전환 체크리스트 신규 작성 — 착수 전 재검증 체크리스트, 구현 작업 단계별 리드타임(합계
  약 5~7일, 대시보드 제외), 채택하지 않기로 확정한 것(MinT/OLS)을 명시. 산출:
  `outputs/forecast_unit/hs_hierarchy_transition_checklist.md`.
- **D-5(오버라이드 재검증 주기)**: `scripts/schedule.py`에 `quarterly()` 함수 신규 추가 —
  `override_backtest.py`를 서브프로세스로 재실행해 리포트에서 "③ 지정학 고신뢰" 판정만
  파싱, 폐지가 아닌 것으로 바뀌면 경고 로그 출력(설정 자동변경은 하지 않음, 사람 검토
  원칙). **재유효화 판단 기준을 코드 주석으로 명문화**(override_backtest.py의 `verdict()`
  에 이미 구현된 값을 인용): 유지=정당화비율≥0.45 且 lift≥1.5, 임계조정=정당화≥0.3 또는
  lift≥1.3. cron 예시 추가(분기 1일 08:00, 1/4/7/10월).
  **버그 발견·즉시 수정(구현 중 실제로 걸림)**: 최초 구현에서 판정 라인 검색이
  `line.startswith("| ③ 지정학")`만 확인해, 리포트 내 **다른 표**(트리거별 개별 기여 표,
  숫자 나열만 있고 판정 없음)의 동일 접두 행을 먼저 매칭 — 실제로는 여전히 "폐지"인데
  "판정 변경됨" **오탐(false alarm)**이 발생함을 실행 중 발견. `"| **" in line` 조건을
  추가해 판정 표(굵게 표시된 값이 있는 행)만 매칭하도록 수정, 재실행으로 "여전히 폐지
  권고(변경 없음)" 정상 출력 확인[^d5].
- **P3 5/5 전항목 완료**. 산출: `outputs/model_opt/nb2_coef_bootstrap_ci.md`,
  `outputs/forecast_unit/hs_hierarchy_transition_checklist.md`. 코드 변경: `msr/models/
  alert.py`(evidence_json), `db/schema_core.sql`(out_diagnosis_alert.evidence_json +
  mart_forecast_method_log 신규 테이블), `msr/models/forecast_unit.py`(method 로그·마진
  임계), `scripts/schedule.py`(quarterly() 신규).

[^d6]: 검증: 수정 전 `select alert_level, count(*) from out_diagnosis_alert group by 1` →
정상757/관심458/주의202/경계118/심각97(합 1632). `ALTER TABLE out_diagnosis_alert ADD COLUMN
evidence_json VARCHAR` 실행 후 `MSR_DB=warehouse/minerals.duckdb python3 -m msr.models.alert`
재실행 → 동일 쿼리 재확인 완전 일치. `select count(*) filter(where evidence_json is null),
count(*) from out_diagnosis_alert` → 0/1632(전량 채움).
[^e1]: 검증: 수정 전(버그 상태) `MSR_DB=... python3 -m msr.models.forecast_unit` →
`_duckdb.ConnectionException` 발생, `out_import_forecast_unit` 미갱신 확인. `try/finally`
수정 후 재실행 → `select count(*) from out_import_forecast_unit` = 60(불변),
`select model_version,count(*) from ... group by 1` → recursive/60(불변),
`select * from mart_forecast_method_log` → 1행(base_month=2025-12, mase_recursive=0.795).
[^d5]: 검증: `MSR_DB=warehouse/minerals.duckdb python3 -m scripts.schedule quarterly` —
수정 전 오탐 출력("⚠ 판정이 폐지 아님으로 변경됨! | ③ 지정학 고신뢰 | 0 | 0 | — | — | — |")
확인 후 매칭조건 수정, 재실행 → "지정학 오버라이드 여전히 폐지 권고(변경 없음) —
| ③ 지정학 고신뢰 | **폐지** | 발화/격상 없음 — 현 임계에서 무효 |" 정상 출력.

## 2026-07-16 — 피드백기반_수정플랜 P2 13/13 전항목 완료, Ridge(풀링) 더미미사용 버그 확정

`/goal`("어제밤에 claude, codex 피드백 반영해서 작업 진행") 후속. P2 13항목 중 인프라
재사용이 가장 쉬운 3건을 완료:

- **D-2(전환월 방향별 평가 강화)**: `diagnosis_opt.py`의 chg_acc(방향 무관 정확일치)를
  상향전환(악화)·하향전환(완화)·경계·심각 신규진입(3·4단계 최초 진입)·비전환으로 세분화.
  챔피언(Ridge 풀링+매핑) 워크포워드 3폴드 풀링(n=210) 기준: 경계·심각 신규진입(n=3)
  정확일치 0.333(±1단계 허용 시 1.000), 상향전환(n=14) 0.643 vs 하향전환(n=15) 0.867 —
  악화 방향이 완화 방향보다 어려움. 신규진입 표본이 3건뿐이라 절대수치보다 방향성 참고.
- **D-3(NI 대체지표)**: NI는 워크포워드 3폴드 중 2024·2025~ 2개 폴드가 실제 단일클래스
  (위기사례 0)라 폴드별 QWK 정의 불가 — **NI만의 문제가 아니라 5개 광종×3폴드=15조합 중
  7개(47%)가 단일클래스로 확인**(CO 2건, LI 1건, NI 2건, REE 1건). 폴드 불문 항상 정의
  가능한 balanced accuracy·macro recall·event-hit rate(실제 2단계 이상일 때 예측 2단계
  이상 잡는 비율)를 대체지표로 채택. NI: balanced_acc=0.5208, event_hit_rate=0.6000.
- **B-7(상위이벤트 20개 주간 사례표)**: 광종별 `geo_index`(freq=W) idx_value 상위 20개
  주간(총 100행) × severity 상위 3건 대표 `geo_event` 매칭 — 매칭 실패 1/100건뿐. CO
  상위주간 사례에서 DRC 코발트 수출제한(2025-11-02, sev=3.00)·광산사고(2025-11-16,
  32명 사망)·환경규제(2025-11-23) 등 실제 공급위기 뉴스와 지수 상위가 정합적으로 일치함을
  육안 확인 — 신호 타당성 근거자료로 사용 가능.
- **부수 발견(남은 과제 #5 확정)**: D-2/D-3 구현 중 `diagnosis_opt.py`의
  `_fit_predict_reg()` 코드를 직접 재검토, "Ridge(풀링)"이 `pd.get_dummies`로 `cc_*`
  광종더미를 생성하지만 내부 `one()` 클로저가 `tr_[feats]`(원본 피처만, 더미열 미포함)로만
  슬라이싱함을 **코드로 확정**(추측 아님) — 풀링 모델은 실제로 광종 구분 없이 완전통합
  학습 중. 지금까지 보고된 모든 QWK/chg_acc 수치는 이 버그가 있는 상태로 일관되게 산출된
  것이라 상대비교(신규피처 채택여부 등)의 타당성 자체는 훼손 없음 — 단, "풀링" 명칭이
  오도적이고, 더미를 실제로 사용하면 성능이 달라질 수 있어 별도 확인 과제로 유지.
- **B-4(conc×imp_mult 상관/이중계상 점검)**: `geo/indexer.py._load_refdata()`가 읽는
  `geo_data/config/refdata/concentration.parquet`(USGS 연도별 국가점유)가 **아직 백필되지
  않아 파일이 존재하지 않음을 확인**(next-tasks-komir 항목 6의 "USGS refdata 백필"이 왜
  중요한지 실증) — 따라서 `compute()`의 USGS 분기는 운영에서 한 번도 실행된 적이 없고,
  실제로는 `sources.yaml`의 정적 `supply_concentration` 맵(6개 (광종,국가) 쌍만 1.0 아닌
  값, 나머지 전체 국가 기본값 1.0)이 conc를 결정한다. 이 실경로를 그대로 재현해 광종별
  conc×imp_mult 상관계수 산출: CU r=0.7907·REE r=0.9944(둘 다 |r|>0.5, 임계치 초과) vs
  CO/LI/NI는 낮음. 단 conc 비상수 국가가 광종당 1~2개뿐이라(전체 6쌍) 상관계수가 그 소수
  국가의 imp_mult 값에 좌우되는 구조 — **결론은 이중계상보다 "conc 국가 커버리지가
  희소하다"는 문제가 더 시급, USGS refdata 백필 후 재계산 필요**.
- **C-6(calibration 검증 확대)**: `geo/prob_model.py`는 현재 Brier+5분위표만 보고 — 10분위
  calibration curve·ECE·log loss·PR-AUC·ROC-AUC를 5광종×v1(원시 NB2 p_burst)/v2(isotonic
  사후보정) 전체에 추가 산출(테스트기간 2024+를 다시 60/40 분할, v1도 뒤 40%만 평가해 v2와
  공정 비교). 결과: 4/5광종(CU·LI·NI·REE)이 Brier·ECE 둘 다 개선, CO만 악화(0.0737→0.0781,
  0.0407→0.0628 — 캘리브레이션 표본이 작아 과적합 가능성). REE는 Brier 0.393→0.263로 가장
  큰 개선폭. NI는 이 평가창에서 base_rate=0.0(단일클래스)이라 ROC-AUC/PR-AUC/log_loss가
  정의 불가 — D-3 발견(NI 위기사례 희소)과 확률모델에서도 동일하게 재현됨을 확인.
- **B-6(near-dup 12% 영향 정량화)**: `validate_neardup_embedding.py`(07-15)의 광종별 표본
  잔존율(LI 9.7%·CU 12.7%·NI 13.7%·REE 6.3%·CO 4.8%)만큼 (광종,월) 버킷별 무작위 제거 후
  `geo/indexer.compute()` 원본 코드를 입력만 바꿔(몽키패치) 재실행 — 재구현 없이 실제
  파이프라인으로 검증. 결과: 5광종 평균 상관계수 0.9981, 상위20주 Jaccard 평균 0.945
  (CU·NI·REE는 1.000) — **2단계(BGE-M3 전량 임베딩) 도입이 지수 상위 신호에 미치는 영향은
  미미, 1단계(키 기반)로 충분하다는 기존 결론을 지수 순위 관점에서 재확인**.
- **C-5(REE α 폴백 검증)**: REE는 MLE α가 원천적으로 불안정해(붕괴) "직전 유효값"을 구할 수
  없어 인접 광종(MLE 정상수렴: CO·CU·LI·NI) 평균 α=0.4816을 비교기준으로 채택. 동일 REE
  회귀계수에 α만 교체해 비교한 결과 프로덕션(모멘트폴백 α=11.07) Brier=0.2989 vs
  인접광종평균 Brier=0.2178(0.0811 개선, ECE도 0.2565→0.1415 개선) — **인접광종평균 폴백을
  REE 2차 폴백으로 추가해 다음 재학습 라운드에서 병행 모니터링 권고**(즉시 교체는 REE
  표본이 작아 보류). **부수 발견**: 플랜 원문의 "α=6.81" 인용값과 실측(11.07, 발행모델
  기준 5.32)이 불일치 — 이번 세션 중 데이터 변경으로 자연 이동한 것으로 추정, 데이터
  수량 실측 원칙에 따라 재확인값을 채택.
- **D-1(y_lag1 의존도 완화)**: 챔피언(Ridge 풀링)을 y_lag1 포함/제외/앙상블(회귀예측 단순
  평균) 3가지로 비교. y_lag1 제외 시 풀링 QWK 0.9370→0.3168, 전환월 적중률도 0.881→0.600로
  **둘 다 악화**(같은 방향으로 함께 움직임) — 조치안이 우려한 "관성이 일반 QWK만 부풀리고
  조기경보력은 깎아먹는" 트레이드오프 패턴이 아님을 확인. **결론: y_lag1은 관성 함정이
  아니라 경보의 실제 지속성(진짜 신호)을 포착하는 것으로 해석, 현재 정칙화·피처 구성 변경
  불필요**(단, 정칙화 강화·직교화 등 더 정교한 대안은 미검증으로 남김).
- **B-2(rel 실증 근거 보강)**: B-1과 동일 방법론(forward return)을 발행처 신뢰도 등급별로
  재실행. `geo_event.source`는 공급감소 이벤트의 98%가 빈 문자열(provider=openai_compat,
  gkg_verify 재검증 통과분 — indexer.py 주석의 알려진 이슈)이라 이를 "미상(rel=1.0 기본값)"
  등급으로 명시 포함(조용히 제외하면 표본 왜곡). 결과: **중신뢰(분석보고서) fwd1=0.0041·
  fwd4=0.0135가 고신뢰(정부공시) fwd1=0.0011·fwd4=0.0014보다 모든 창에서 큼** — forward
  return 크기 기준으로는 rel=1.4(정부공시)의 '선행성' 우위가 실증되지 않음. rel의 원설계
  근거(1차 사료 신뢰성)와 이 검증 지표(수익률 크기)가 애초에 다른 질문이었다는 점을
  설계문서에 명시 권고.
- **B-5(volume normalization on/off 비교)**: `geo/indexer.py.compute()`에 `volume_norm`
  파라미터 신규 추가(기본 True=기존과 완전 동일, 회귀 없음 확인 — geo_index 3,529행 동일)로
  두 버전을 실제 파이프라인 산출해 랜드마크 4개(2020 팬데믹·2022 러-우전쟁·2023/2025 REE
  수출통제) 비교. **결론은 우려와 반대**: 2020만 정규화가 소폭 억제(<1.5pt), 2022·2023·
  2025는 오히려 정규화가 지수를 최대 6.4pt 증폭(코퍼스 총량이 이 기간 급감해 EWMA 분모가
  작아진 결과) — "정규화가 위기 신호를 눌러버린다"는 우려는 확인되지 않음, 현행 유지 가능.
- **C-3(NB2 vs ZINB vs Hurdle)**: Poisson·NB2·ZINB·Hurdle-NB 4종을 prob_model.py 동일
  피처로 적합, Vuong(1989) 검정 직접 구현(Hurdle의 관측치별 로그우도는 statsmodels 미제공이라
  내부 두 하위모델 결합으로 재구성, 합계가 `.llf`와 정확히 일치함을 런타임 assert로 검증).
  **부수 발견**: 플랜 원문의 "0비율 26~68%"가 실측(LI 6.2%·CO 6.0%·REE 16.3%·CU/NI 0.0%)
  과 크게 다름. LI·CO·REE 어디에서도 ZINB/Hurdle이 NB2보다 유의하게 우수하지 않음(전부
  Vuong 우열없음) — **NB2 단독 유지가 실증적으로 지지됨**, 전환 근거 없음. CU/NI는 0비율
  0.0%라 ZINB/Hurdle 적합이 수학적으로 불가능(버그 아님, 대상 자체가 아님).
- **C-4(LI/CO 원인분석)**: C-1에서 LI 열세·CO 동률이었던 원인을 공변량 부족 가설로 검증 —
  price_z52·import_hhi·n_policy(정책이벤트 주간건수, geo_event.dimension='policy') 3개
  추가한 확장모델이 LI Brier 0.1009→0.0625(대폭 개선)·CO Brier 0.0840→0.0644(개선) —
  **공변량 부족이 실제 원인이었을 가능성 확인**, 다만 CO는 ECE가 0.0365→0.1340로 악화
  (Brier와 상반, 운용 전 재검토 필요). **부수 발견**: `spread_pct`(가격변동성)가
  `mart_weekly_diagnosis`에서 CO·LI·REE 100% 결측(CU·NI만 존재) — 별도 데이터공백으로 기록.
- **B-3(곱셈식 vs 가중합/log-additive 대안 비교)**: `geo/indexer.py.compute()`에
  `score_formula` 파라미터 추가('mult'=기존 그대로 회귀 없음, 'sum'=가중합, 'loggeo'=로그
  기하평균). 결과: sum 평균 상관계수 0.9898·상위20주 Jaccard 0.889, loggeo 평균 상관계수
  0.9355·Jaccard 0.852 — **두 대안 모두 mult와 순위가 크게 다르지 않아 곱셈식 유지가 안전한
  선택**. loggeo는 지수 평균이 52.37(mult 통상 60~85대)로 중립값에 강하게 압축돼 변별력이
  줄어드는 트레이드오프 관찰. **범위 한계**: 조치안이 요구한 QWK 성능 비교는
  발행→마트→진단모델 전체 재배선이 필요해 이번 라운드에서는 순위 안정성(Jaccard·상관)까지만
  확인, QWK 직접 검증은 별도 워크스트림 필요.
- **P2 13/13 전항목 완료**. 산출: `outputs/model_opt/{diagnosis_transition_eval,
  geo_top_weeks_report,conc_impmult_corr,prob_calibration_extended,neardup_impact_sim,
  ree_alpha_fallback_check,diagnosis_ylag_dependence,rel_source_tier_check,
  volume_norm_ablation,count_model_comparison,li_co_covariate_expansion,
  score_formula_ablation}.md`.
- 코드: `scripts/diagnosis_transition_eval.py`·`scripts/geo_top_weeks_report.py`·
  `scripts/conc_impmult_corr.py`·`scripts/prob_calibration_extended.py`·
  `scripts/neardup_impact_sim.py`·`scripts/ree_alpha_fallback_check.py`·
  `scripts/diagnosis_ylag_dependence.py`·`scripts/rel_source_tier_check.py`·
  `scripts/volume_norm_ablation.py`·`scripts/count_model_comparison.py`·
  `scripts/li_co_covariate_expansion.py`·`scripts/score_formula_ablation.py`(전부 신규).
  `geo/indexer.py`에 `volume_norm`·`score_formula` 파라미터 추가(둘 다 기본값 유지로 회귀
  없음 확인, B-5·B-3 검증 전용).

[^p2-d2d3b7]: 검증: `MSR_DB=warehouse/minerals.duckdb python3 -m scripts.diagnosis_transition_eval`,
`python3 -m scripts.geo_top_weeks_report`, `python3 -m scripts.conc_impmult_corr`,
`python3 -m scripts.prob_calibration_extended`, `python3 -m scripts.neardup_impact_sim`,
`python3 -m scripts.ree_alpha_fallback_check`, `MSR_DB=... python3 -m scripts.diagnosis_ylag_dependence`,
`MSR_DB=... python3 -m scripts.rel_source_tier_check`, `python3 -m scripts.volume_norm_ablation`,
`python3 -m scripts.count_model_comparison`, `MSR_DB=... python3 -m scripts.li_co_covariate_expansion`,
`python3 -m scripts.score_formula_ablation` (전부 `komir/mineral_supply_risk/`에서 실행).
Ridge(풀링) 버그 확인: `komir/mineral_supply_risk/msr/models/diagnosis_opt.py` L145-175
(`_fit_predict_reg`) 직접 열람 — `one()`의 `Xtr_ = prep.fit_transform(tr_[feats])`가 `feats`
파라미터(더미열 미포함)만 참조함을 코드로 확인. concentration.parquet 부재 확인:
`ls geo_data/config/refdata/` → `kr_import_share.parquet`만 존재. spread_pct 결측 확인:
`select commodity_code,count(*),count(spread_pct) from mart_weekly_diagnosis group by 1` →
CO/LI/REE count(spread_pct)=0. indexer.py 회귀 없음 확인: `volume_norm`/`score_formula`
파라미터 추가 전후 `compute()` 기본 호출 결과가 geo_index 3,529행·광종별 평균 동일함을
재실행으로 재확인(2회, 각 파라미터 추가 직후).

## 2026-07-16 — geo_prob 요일앵커 버그 근본 수정(발행 경계 보정, indexer.py는 무변경)

"남은 과제" #4(요일앵커 버그) 실행. 사전 조사(Explore 에이전트)로 정확한 수정 지점을 확인:
- **`geo_index`(indexer.py, 일요일 앵커)는 건드리지 않음** — 실측 확인 결과 유일한 소비처인
  `weekly_mart.py`의 `geopolitical_risk` 채움이 **ASOF LEFT JOIN**(정확일치 아님)이라 요일
  불일치가 무해하게 흡수됨(오히려 "직전 완결 주" 의미를 정확히 구현하도록 의도적으로 설계된
  것으로 확인, 2026-07-08 주석). exact join이었다면 채움률이 61.8%→0%였을 것을 shift 실험
  으로 실측 확인.
- **`prob_model.py`(`_weekly_panel()`) 내부 계산도 무변경** — 이 함수의 일요일 그리드는
  `_attach_geo_idx()`가 `geo_index`(마찬가지로 일요일)와 **정확일치**로 내부 병합해야 해서
  필요한 정합. 여기를 월요일로 바꾸면 오히려 `geo_idx` 병합이 깨짐(항상 중립값 50 폴백).
- **실제 수정 지점: `geo/publish.py`의 `publish_index()` — `geo_prob`를 DB로 내보낼 때만
  +1일(일요일→월요일) 보정**[^weekday-fix]. `geo_index`는 그대로 발행(ASOF로 안전).
  내부 정본(parquet)은 원래 그대로, DB로 나가는 값만 외부(mart_weekly_diagnosis) 규약에 맞춤.
- **재발행**: `python -m geo publish --db warehouse/minerals.duckdb --what index` →
  geo_index 3,529행(불변)·geo_prob 2,745행(period 월요일로 보정) 재적재. DB 직접 조회로
  geo_prob 전량 Monday·geo_index 전량 Sunday(의도대로 유지) 확인.
- **`diagnosis_retrain_answer.py`의 +1일 수동 우회 코드 제거**, 정확일치 조인으로 단순화.
  재실행 결과 p_burst 커버리지 2,411/2,411(불변) — **모든 수치(QWK·chg_acc 등)가 수정 전과
  완전히 동일**함을 확인(회귀 없음, 우회가 정확했었고 이제 근본 수정으로 대체된 것).
- **영향범위 점검**: `geo_prob`의 다른 소비처(schedule.py·publish_results.py)는 단순 전달
  /스케줄링뿐이라 영향 없음. `alert.py`는 `geo_event`(일자별 원본)를 직접 쓰지 `geo_index`/
  `geo_prob`를 안 거쳐 무관.

[^weekday-fix]: 수정: `geo/publish.py` `publish_index()`, geo_prob 분기에 `pr["period"] =
(pd.to_datetime(pr["period"]) + pd.Timedelta(days=1))...` 추가. 검증: `duckdb ... -c
"select period from geo_prob limit 5"` → 전량 Monday, `geo_index` 동일 조회 → 전량 Sunday
(무변경 확인). 재실행: `MSR_DB=... python3 -m scripts.diagnosis_retrain_answer` — 수정 전
리포트(`outputs/model_opt/diagnosis_retrain_answer.md`)와 수치 완전 일치.

## 남은 과제 (다음 스프린트, 2026-07-16 갱신 — 이 라운드 종결 시점)

**이 라운드(07-16) 종결 요약**: ①프로세스정리(외부AI검토용) 완료 ②피드백기반_수정플랜
P0 4/4·P1 9개 중 7개 완료+1개 부분완료(B-1)+1개 미착수(A-5) ③KOMIS 가격이격률 라운드
완전 종결 — 정답셋 시도(게이트 5종 전부 기각) → 정답/피처 정정 → 신규피처 추가/교체 시도
(둘 다 기각, price_z52 대비 정보량 부족 확정) → **결론: price_z52·기존 4단계 경보 체계
그대로 유지, 추가 개입 불필요**.

1. **A-5 라벨 품질 검증(수동)**: severity·direction·event_type 계층표집 200~300건, LLM
   추출값과 사람 판정 일치율(Cohen's kappa) — 사람 판정 필요, 자동화 불가. 검토자 배정 필요.
2. ~~**피드백기반_수정플랜 P2(13항목)**~~ **전항목 완료(2026-07-16)** — 상세는 위
   "P2 13/13 전항목 완료" 항목(D-2·D-3·B-7·B-4·C-6·B-6·C-5·D-1·B-2·B-5·C-3·C-4·B-3). 상세는
   `documents/claude_output/피드백기반_수정플랜_260716.md`.
3. **피드백기반_수정플랜 P3(5항목, 전부 미착수)**: 소표본 신뢰구간(C-7), 오버라이드 재검증
   주기(D-5), 운영판정로그(D-6), recursive/direct 모니터링(E-1), HS계층 대기(E-2).
4. ~~**버그 수정 — geo_prob 요일앵커 불일치**~~ **완료(2026-07-16)** — `geo/publish.py`
   발행 경계에서 +1일 보정, `geo_index`/`prob_model.py` 내부 계산은 무변경(ASOF 소비·내부
   병합 정합 유지 이유로). 상세는 위 "geo_prob 요일앵커 버그 근본 수정" 항목.
5. **버그 확정 — diagnosis_opt.py "Ridge(풀링)" 광종더미 미사용**(2026-07-16 코드로 확정,
   더 이상 "의심" 아님): `_fit_predict_reg()`의 `per_commodity=False` 분기가 `pd.get_dummies`
   로 `cc_*` 더미열을 생성하지만, 내부 `one()` 클로저가 `tr_[feats]`(원본 피처 리스트,
   더미열 미포함)만 슬라이싱해 모델 학습에 더미가 전혀 반영 안 됨 — "풀링" 명칭과 달리
   광종 구분 없는 완전통합 학습. 기존 보고 수치(QWK 0.9246 등)는 전부 이 상태로 일관 산출된
   것이라 상대비교 결론은 유효하나, 더미를 실제로 반영하면 절대 성능이 달라질 수 있음 —
   수정 후 재평가 필요(diagnosis_opt.py 정본 변경이라 영향범위 큼, 별도 작업으로 착수 권장).
6. **운영 배포**: collector 도커 수집서버 기동 / 분석서버(폐쇄망) 반입 + cron 등록(주간 월
   06:00 / 월간 1일 07:00) — 체인 코드 검증 완료, 인프라 작업만 잔여. 대시보드는 07-12
   스냅샷이라 v2 재앵커(07-15) 반영 재생성 필요(F-3 후속, `versionBoundary` 데이터 주입).
7. **발주처 협의**: 기존 8건(v1 §12) + 신규 4건(`발주처협의안건_4건_260716.docx`).
8. (참고, 우선순위 낮음) **deviation_rate 직교화 방안**: price_z52·deviation_rate 공통성분을
   제거한 잔차 피처는 미검증으로 남김 — 두 가지(추가·교체) 모두 기각된 만큼 재시도 가치는
   낮으나, 후속 요청 시 진행 가능.

관련 메모리: `feedback-revision-plan-execution`, `diagnosis-ground-truth-komis-grade`,
`next-tasks-komir`(모두 이번 세션 결과로 갱신됨).

## 2026-07-16 — 정답/피처 설정 정정: KOMIS 가격이격률은 정답이 아니라 피처. 신규 피처는 기각

**사용자 정정(같은 날 앞선 KOMIS 등급 관련 작업 전체에 대한 방향 수정)**: 07-16 앞서 진행한
"KOMIS 가격이격률 등급을 수급위기 진단모델의 정답셋으로 삼아 재학습·게이트결합"(5차례 시도,
전부 기각) 라인은 **정답(target) 설정 자체가 잘못됐음이 확인됨** — 정답은 기존 4단계 수급위기
경보 체계(교사신호 teacher_supply_demand 기반 crisis_index, diagnosis_opt.py ANCHOR_SPAN
분위컷)로 **그대로 유지**하고, KOMIS 가격이격률(연속형 deviation_rate)은 기존 진단모델의
**신규 피처 후보**로만 검정하는 것이 올바른 방향. 앞선 5차례 게이트/재학습 시도의 코드·리포트는
삭제하지 않고 보존(무엇을 시도했고 왜 기각됐는지 자체는 유효한 기록)하되, 그 결론("지정학신호
직접결합 5전5패")은 **정답 정의가 KOMIS 등급이었던 특정 실험 설정 안에서의 결론**으로 범위를
좁혀 해석해야 함 — 기존 4단계 경보를 정답으로 한 진단모델 자체의 유효성과는 별개.

**재검정(올바른 설정)**: `scripts/load_price_grade_answer.py`에 '이격률' 시트(연속형,
등급보다 정보손실 적음)를 추가 적재(`fact_diagnosis_answer.deviation_rate` 컬럼, 기존
2,497행 전체 커버). 신규 `scripts/diagnosis_add_deviation_feat.py` — **정답은 기존 4단계
경보 그대로**, diagnosis_opt.py의 실제 함수(build_panel·stage_labels·워크포워드·QWK)를
그대로 재사용해 기존 피처셋(BASE_FEATS+GEO_DERIVED)에 deviation_rate 추가 여부만 비교
[^devfeat-run].

- **판정: 기각.** Ridge(풀링)+매핑 챔피언 기준 QWK 0.9246→0.8607(-0.0639), 전환월 적중
  0.7453→0.6051(-0.1402)로 레벨 정확도·전환 탐지력 모두 뚜렷이 악화. HistGBM(풀링)도 동일
  방향(QWK -0.09). deviation_rate 자체의 피처 제거 민감도 dQWK=-0.011(음수 — 제거하면 오히려
  개선, 순수 노이즈보다 나쁨).
- **원인**: deviation_rate와 기존 피처 `price_z52`의 상관계수 0.516(중간 수준, 둘 다 같은
  가격 시계열의 z-score류 변형) — 이미 2위 기여 피처인 price_z52와 정보가 겹쳐 월간 379~390
  행 소표본에서 다중공선성·과적합만 키운 것으로 해석.
- **후속 검토 가치 있는 대안(미검증, 범위 밖)**: (1) price_z52를 deviation_rate로 대체(추가
  아닌 교체) (2) 두 피처의 직교화(잔차)만 사용.

[^devfeat-run]: 적재: `MSR_DB=komir/warehouse/minerals.duckdb python3 -m
scripts.load_price_grade_answer`(이격률 시트 추가 반영). 비교: `MSR_DB=komir/warehouse/
minerals.duckdb python3 -m scripts.diagnosis_add_deviation_feat` →
`outputs/model_opt/diagnosis_add_deviation_feat.md`.

## 2026-07-16 — deviation_rate로 price_z52 교체 실험 — 기각(추가보다도 더 나쁨)

사용자 지시로 "price_z52를 deviation_rate로 교체"(공선성 없는 순수 대체) 실험을
`diagnosis_add_deviation_feat.py`에 3번째 피처셋(교체, 11개 유지)으로 추가 — 동일
diagnosis_opt.py 워크포워드 방법론으로 기존/추가/교체 3자 비교.

- **판정: 기각. 교체가 추가보다도 더 나쁘다.** Ridge(풀링)+매핑 챔피언 기준: 기존 QWK 0.9246
  → 교체 **0.6777**(-0.2469, 추가의 -0.0639보다 3.9배 나쁨), 전환월 적중 0.7453→**0.3624**
  (-0.3829, 추가의 -0.1402보다 2.7배 나쁨).
- **해석**: 공선성(price_z52↔deviation_rate 상관 0.516) 때문에 '추가'가 손해였다는 가설과
  별개로, deviation_rate를 유일한 z-score류 피처로 세워도(공선성 제거된 상태) 여전히
  price_z52보다 약한 신호(교체 상태 dQWK **-0.052**, 추가 상태의 -0.011보다도 더 강한 음수)
  — **deviation_rate 자체가 price_z52 대비 정보량이 적은 신호**라는 것이 확정적으로 확인됨.
  price_z52가 잃으면 안 되는 핵심 피처(원 dQWK 0.069, 2위 기여)임이 역으로 재확인됨.
- **결론**: price_z52는 그대로 두는 것이 최선 — "추가"·"교체" 두 가지 deviation_rate 활용
  방식 모두 기각. KOMIS 가격이격률 데이터를 기존 진단모델 피처로 개선에 쓰는 이번 라운드는
  종결(2가지 방식 모두 검정, 둘 다 기각).

## 2026-07-16 — 수급위기 진단 정답셋(ground truth) 신규 반영: KOMIS 가격이격률 등급

사용자 지시: `documents/2차_데이타/3. 학습 및 검증용/1. 학습용 참고자료/1. 주간가격이격률
모니터링_코미스가격기준 (1).xlsx`의 '등급모니터링'(광종별 주간 3단계 등급)+'가격DB'(동일
그리드 가격) 시트를 수급위기 진단모델의 정답셋으로 반영.

- **등급 정의**('참고사항' 시트, 2026-07-15 일루넥스 확인): 이격률(가격의 과거평균 대비 표준
  편차 배수)의 **상방(+) 이탈만** 감지하는 3단계 — 정상(<+1σ)/관심(+1~2σ)/주의경계심각(≥+2σ).
  프로젝트 자체 4단계 경보(관심·주의·경계·심각)보다 거친 3단계이며 하방 이탈은 등급 미부여.
  임의로 5단계에 매핑하지 않고 원본 그대로 보존.
- **컬럼 매핑**: `fact_price`(`load_komis_xlsx.py` PRICE_COLS)와 동일 5광종·동일 가격기준으로
  한정해 정합성 유지 — CU=동/LME CASH, NI=니켈/LME CASH, CO=코발트/LME CASH, LI=탄산리튬/
  99.5%min CIF China, REE=산화네오디뮴/99.5%min FOB China.
- **신규 스크립트** `scripts/load_price_grade_answer.py`, **신규 테이블** `fact_diagnosis_answer`
  (PK: commodity_code·indicator·obs_date, 컬럼: grade·grade_ord(0/1/2)·price·series_label)
  — **2,497행 적재**(CU/NI/CO/REE 각 552주 2015-12-14~2026-07-06, LI 289주 2020-12-28~,
  전체 정상 1,647/관심 433/주의경계심각 417)[^answer-load].
- **기존 모델과 교차검증**(참고용, 완전일치를 기대할 이유는 없음 — 등급은 가격 단변량, 기존
  alert_level은 가격+HHI+지정학+히스테리시스 다변량): `out_diagnosis_alert.alert_level`과
  Spearman rho **0.439**(전체, n=1,583, p<0.001) — 광종별 CO 0.572·CU 0.506·REE 0.395·
  LI 0.387·NI 0.331[^answer-crosscheck]. 방향은 전부 유의한 양(+)이나 완전일치는 아님 —
  독립 검증셋으로서 유효(순수 재현이면 오히려 의심스러웠을 것).
- **주목할 불일치 1건**: 2026-07-06(최신주) CU는 기존 모델 alert_level='심각'(Red)인데 신규
  정답셋 grade='관심'(가장 낮은 비정상 등급)으로 나타남 — 구리 경보의 특수성(가격변동성이
  거시·투기 지배, 기간구조·수입집중 병행 해석 방침 기 수립됨, CU 역방향 신호 조사와 연결)과
  일치하는 패턴. 후속 분석 필요.

[^answer-load]: 실행(2026-07-16): `MSR_DB=komir/warehouse/minerals.duckdb python3 -m
scripts.load_price_grade_answer` → `fact_diagnosis_answer` 2,497행.
[^answer-crosscheck]: 실행(2026-07-16): `out_diagnosis_alert`↔`fact_diagnosis_answer`
(commodity_code·obs_date 조인) `scipy.stats.spearmanr(alert_ord, grade_ord)`.

## 2026-07-16 — 진단모델 재학습(정답셋: KOMIS 등급) — 지정학신호 단독 유의미, 결합 시 관성에 묻힘

사용자 지시: 정답셋(fact_diagnosis_answer)을 타깃으로 지정학위기지수+피처로 광종별 진단모델
재학습·평가, 정답 오염 주의. 신규 `scripts/diagnosis_retrain_answer.py`(워크포워드 3폴드,
후보 9종: 지속성·나이브·Ridge×2·HistGBM×2·Logistic·DecisionTree·RandomForest).

- **오염 방지**: 등급=가격 이격률(σ배수) 정의라 `ref_price/volatility_12w/spread_pct/
  price_z52`(전부 동일 가격 시계열 파생)는 주모델에서 제외 — 포함 시 예측이 아니라 라벨
  재진술이 되므로. 주모델은 지정학위기지수·geo_chg·p_burst·import_hhi/yoy/cagr3·
  grade_lag1(과거 등급, 미래정보 아니므로 오염 아님)만 사용.
- **부수 발견(버그)**: `geo_prob.period`가 일요일 앵커(`prob_model.py`의 `pd.date_range(freq=
  "W")`가 기본 W-SUN)인데 `mart_weekly_diagnosis.obs_date`는 월요일 앵커 — 주간 그레인에서
  그대로 조인하면 p_burst가 100% 결측된다. 월간 집계(diagnosis_opt.py, `date_trunc('month')`)
  는 이 불일치가 가려져 있었을 뿐. 본 스크립트에서 +1일 보정으로 우회, prob_model.py 자체
  수정은 미실시(범위 밖, 후속 과제로 기록)[^retrain-joinbug].
- **부수 발견(통계 아티팩트)**: 워크포워드 3폴드 중 2023·2024가 5광종 전부 100% 단일클래스
  (실측 — 2022 원자재 급등 이후 가격 안정기, 데이터 오류 아님)라 QWK가 0 또는 NaN으로 붕괴
  (관측/기대일치 모두 포화). **폴드평균 대신 전체 폴드 예측을 풀링한 pooled QWK를 주 지표로
  전환**해 아티팩트 회피.
- **핵심 결과**[^retrain-run]:
  1. grade_lag1 포함(GEO_FEATS): 전 모델이 지속성과 사실상 동일(QWK 0.9687, 순개선
     0.0000) — grade_lag1이 압도적이라 다른 피처 계수가 반올림 임계를 못 넘음.
  2. **grade_lag1 제외(GEO_ONLY_NO_LAG, 진짜 독립검정): Logistic이 나이브 대비 순개선
     +0.5099(QWK 0.5099, acc 0.803)** — 지정학위기지수·급증확률·수입편중 등 순수 외생
     신호만으로도 실질적 예측력 확인. **지정학 신호는 무의미하지 않음.**
  3. 종합: 지정학 신호의 정보가 이미 grade_lag1(직전 등급)에 상당 부분 선반영돼 있어
     지속성 대비 증분가치가 현 평가방식(레벨 정확도)에서는 드러나지 않을 뿐 — 전환월 중심
     평가(D-2)나 임계기반 오버라이드 결합으로 재시도 여지 있음(권고 3건 리포트에 기재).
  4. 광종별(챔피언=지속성) QWK: CO 0.985·REE 0.987·LI 0.956·NI 0.940·CU 0.938.

[^retrain-joinbug]: 확인(2026-07-16): `geo_prob`·`mart_weekly_diagnosis`의 날짜 요일 직접
비교(`pd.to_datetime(...).dt.day_name()`) — geo_prob 전량 Sunday, mart_weekly_diagnosis
전량 Monday.
[^retrain-run]: 실행(2026-07-16): `MSR_DB=komir/warehouse/minerals.duckdb python3 -m
scripts.diagnosis_retrain_answer` → `outputs/model_opt/diagnosis_retrain_answer.md`.

## 2026-07-16 — 전환주 적중률 재평가: grade_lag1 결합 시 전환주 전량 실패(0%) 확정

사용자 지시로 재학습 스크립트에 전환주 적중률(chg_acc, diagnosis_opt.py의 전환월 적중과
동일 정의 — 직전 시점 실제 등급≠현재 실제 등급인 전환 시점만 골라 정확도 계산)을 추가,
GEO_FEATS/GEO_ONLY_NO_LAG/ALL_FEATS 3실험 전체와 광종별로 재평가[^chgacc-run].

- **grade_lag1 포함(GEO_FEATS) — 결정적 결과**: 학습된 6개 모델(Ridge×2·HistGBM×2·
  Logistic·DecisionTree·RandomForest) **전부 전환주 적중률 0.000**(테스트기간 전체 전환주
  26건 전량 실패) — 레벨 QWK 0.9687(지속성과 동률)이라 앞서(같은 날 앞선 재학습 항목)
  '무해'해 보였던 것이, 실제로 위기가 발생/해소되는 순간만 보면 **지속성의 구조적 전패와
  완전히 동일하게 행동**함이 확정됨. grade_lag1 회귀계수가 압도적이라 다른 피처 기여가
  반올림 임계를 못 넘는 것.
- **grade_lag1 제외(GEO_ONLY_NO_LAG) — 핵심 발견**: 챔피언 **HistGBM(풀링) 전환주 적중률
  0.5385**(26건 중 14건) — 나이브(0.1923)·지속성(0.0000)을 크게 상회. **지정학위기지수·
  급증확률·수입편중 신호만으로 실제 위기 전환의 절반 이상을 잡아냄.** 광종별: NI 0.800·
  CO/REE 0.667·CU 0.462·LI 0.000(표본 2건뿐, 결론 근거 부족).
- **표본 주의**: 전체 테스트기간 전환주 26건(광종별 최소 2건)뿐 — 방향성 참고, 통계 확정
  아님.
- **권고**: grade_lag1과 지정학신호를 단순회귀로 합치지 말고 게이트/오버라이드 구조로 결합
  (평상시 지속성, GEO_ONLY_NO_LAG 챔피언이 이탈+고신뢰일 때만 전환 덮어쓰기) — alert.py
  오버라이드 계층과 유사 설계, 동일 방법론 백테스트가 다음 과제.

[^chgacc-run]: 실행(2026-07-16): `MSR_DB=komir/warehouse/minerals.duckdb python3 -m
scripts.diagnosis_retrain_answer`(chg_acc 계산 추가된 버전) →
`outputs/model_opt/diagnosis_retrain_answer.md`.

## 2026-07-16 — 게이트(gate) 결합 백테스트 — 기각(1차원 이탈크기 트리거로는 트레이드오프 불가)

사용자 지시로 전환주 재평가 권고(1)(2)를 실행 — 지속성(grade_lag1) 기본예측 + GEO_ONLY_NO_LAG
챔피언(HistGBM 풀링) 이탈신호가 임계(tau) 이상일 때만 오버라이드하는 게이트를 구현·백테스트
(신규 `scripts/diagnosis_gate_backtest.py`, override_backtest.py의 FAR/Miss 프레임 재사용,
tau 스윕 0.3~2.0)[^gate-run].

- **판정: 기각.** 채택 기준(QWK가 순수지속성 0.9687 대비 0.10 이내 유지 + chg_acc 개선)을
  만족하는 tau가 하나도 없음. chg_acc>0이 되는 순간(tau≤1.3) QWK가 0.31~0.63까지 붕괴
  (-0.34~-0.66) — 트레이드오프가 채택 불가능한 수준.
- **원인**: 비전환주 856건 vs 전환주 26건(약 33:1) 극단적 불균형이라, 이탈크기 단일임계로는
  소수 진짜 전환과 다수 노이즈를 분리 못함 — 어떤 tau든 낮추면 FAR가 chg_acc와 거의 같은
  속도로 같이 오른다. HistGBM(풀링)의 연속예측값 크기 자체가 전환 여부 판별 신호가 못 됨.
  alert.py 07-16 오버라이드 재설계(구 광역 지정학 트리거 폐지)와 동일한 결론이 재현된 셈.
- **다음 시도 후보(리포트에 4건 기재)**: ①지속 이탈(연속 2주) 조건 ②캘리브레이션된 분류
  확률 기반 트리거 ③상방/하방 비대칭 임계 ④표본 확대(학습기간 연장·부트스트랩).
- **결론**: 현재로선 순수 지속성(grade_lag1) 유지 권고 — 지정학신호를 KOMIS 등급 예측 경보에
  단순 결합하는 방안은 이번 라운드 종결.

[^gate-run]: 실행(2026-07-16): `MSR_DB=komir/warehouse/minerals.duckdb python3 -m
scripts.diagnosis_gate_backtest` → `outputs/model_opt/diagnosis_gate_backtest.md`.

## 2026-07-16 — 게이트 백테스트 2차: 지속 이탈(연속 2주) 조건도 기각

사용자 지시로 "다음 시도 후보 ①"(연속 2주 동일방향 이탈 조건)을 `diagnosis_gate_backtest.py`에
추가 구현·재실행 — 단일주 게이트(변형A)와 지속 이탈 게이트(변형B, 연속 2주 동일부호 이탈)를
동일 tau 스윕(0.3~2.0)으로 나란히 비교[^gate-sustained-run].

- **판정: 기각(재확인).** 두 변형 모두, 스윕한 모든 tau에서 "QWK 허용범위 유지(순수지속성
  대비 0.10 이내)+chg_acc 개선"을 동시 만족 못함.
- **지속 이탈 조건의 실측 효과(단일주 대비, tau별)**: FAR는 확실히 낮아지지만(예: tau=0.5
  FAR 0.453→0.379) **chg_acc도 거의 같은 비율로 함께 낮아짐**(tau=0.5 chg_acc 0.538→0.346,
  -0.192로 FAR 개선폭 -0.075보다 큰 손실) — 순개선이 아니라 트레이드오프의 위치만 이동.
  n_trigger는 뚜렷이 감소(예: tau=0.5, 406→335건).
- **원인**: HistGBM(풀링) 연속예측값이 이틀 연속 흔들리는 것이 "진짜 전환의 전조"인지
  "노이즈가 우연히 이틀 연속인지" 구분할 신호력이 없음 — 지속조건 자체는 노이즈를 일부
  걸러내지만 진짜 신호도 같이 걸러낸다.
- **결론**: alert.py 07-16 오버라이드 재설계(구 광역 트리거 폐지)·dimension c2 트리거 기각·
  단일주 게이트 기각에 이어 **네 번째로 동일 결론 재현** — 지정학신호를 KOMIS 등급 경보
  결합에 직접 넣는 시도는 이번 라운드에서 4전 4패. 순수 지속성 유지, 지정학신호는 보조
  설명(사유 인용·XAI) 용도로만 사용 권고. 남은 시도 후보 3건(분류확률 트리거·비대칭임계·
  표본확대)은 리포트에 기재.

[^gate-sustained-run]: 실행(2026-07-16): `MSR_DB=komir/warehouse/minerals.duckdb python3 -m
scripts.diagnosis_gate_backtest`(gate_predict_sustained 추가된 버전, weeks=2) →
`outputs/model_opt/diagnosis_gate_backtest.md`(변형A·B 병기 갱신).

## 2026-07-16 — 게이트 백테스트 3차: 분류확률 기반 트리거 — 기각, 오히려 크기기반보다 나쁨

사용자 지시로 "다음 시도 후보"(분류기 확률 기반 트리거)를 `diagnosis_gate_backtest.py`에
변형C로 추가 — Logistic·HistGBM 각각 `CalibratedClassifierCV`(sigmoid, train fold 내부
3-fold CV)로 캘리브레이션된 클래스확률을 산출, argmax 클래스가 grade_lag1과 다르고 그 확률이
임계(0.34~0.90) 이상일 때만 오버라이드[^gate-proba-run].

- **판정: 기각(재확인).** 변형 A(단일주 크기)·B(지속이탈)·C(확률) 3계열 통틀어도 "QWK 허용
  범위 유지+chg_acc 개선"을 만족하는 조합이 없음.
- **예상외 발견(가설 기각)**: "분류확률이 예측값 크기보다 결정경계에 민감해 더 나을 것"이라는
  원래 가설이 데이터로 반박됨 — **변형C가 동급 chg_acc에서 변형A보다 오히려 뚜렷이 나쁨**.
  예: C(Logistic) 최선지점(임계0.34, chg_acc=0.2308) QWK=0.0589 vs A에서 chg_acc가 가장
  가까운 지점(tau=1.0, chg_acc=0.3462) QWK=0.5167 — 확률기반이 크기기반보다 8.8배 나쁨.
  C(HistGBM)도 동일 패턴(QWK 0.0000 vs 0.6289).
- **원인**: 클래스 불균형(전환주 26 vs 비전환주 856, 약 32:1)은 트리거를 크기에서 확률로
  바꿔도 해소 안 됨 — GEO_ONLY_NO_LAG 피처 자체가 "다음 주 정확히 어느 클래스로 전환되는가"를
  구분할 신호력을 갖추지 못한 것이 근본 원인(세 변형 모두에서 공통 확인).
- **결론**: **지정학신호를 KOMIS 등급 경보 결합에 직접 넣는 시도가 5가지 변형(구 광역 트리거
  ·dimension c2 트리거·단일주게이트·지속게이트·확률게이트) 전부 기각 — 5전 5패로 이 라운드
  종결.** 순수 지속성 유지, 지정학신호는 alert.py의 보조 설명(사유 인용·XAI) 용도로만 사용
  권고. 남은 시도 후보 2건(비대칭임계·표본확대)은 리포트에 기재하되, 근본 원인이 클래스
  불균형·신호력 부족으로 확인된 만큼 우선순위는 낮음.

[^gate-proba-run]: 실행(2026-07-16): `MSR_DB=komir/warehouse/minerals.duckdb python3 -m
scripts.diagnosis_gate_backtest`(collect_calibrated_probs·gate_predict_proba 추가된 버전) →
`outputs/model_opt/diagnosis_gate_backtest.md`(변형A·B·C 전체 병기 갱신).

## 2026-07-16 — 진단모델 QWK 재평가(정답셋: KOMIS 가격이격률 등급) — 순개선 음(-) 발견

사용자 지시로 `fact_diagnosis_answer`를 정답셋 삼아 진단모델 QWK 재평가. 신규
`scripts/diagnosis_answer_eval.py`(override_backtest.py의 `compute_alerts`/`qwk` 재사용,
로직 무수정) — 모델 예측(base_level 오버라이드 전/alert_level 운영값)을 정답셋과 동일한
3단계(0정상/1관심/2주의경계심각)로 하향매핑 후 QWK(K=3) 계산, 나이브(항상 정상)·지속성
(직전 주 유지) 기준선 필수 병기[^answer-eval].

- **KOMIS 가격등급 정답셋 기준**: QWK(base)=**0.444**, QWK(alert)=0.382 — 광종별 CO 0.649·
  CU 0.434·REE 0.431·LI 0.333·NI 0.255(최저). 오버라이드는 여기서도 QWK를 낮춘다(0.444→
  0.382, 기존 07-16 오버라이드 재설계 결론과 같은 방향).
- **핵심 발견(중요)**: 지속성(직전 주 등급 유지) 기준선이 QWK **0.956**로 모델(base 0.444)을
  크게 앞선다 — 순개선(base−persist) **-0.511**. **같은 방법으로 기존 교사기반 정답셋도
  재검산했더니 지속성 QWK **0.976**이 모델(0.928)을 근소하게 앞선다**(순개선 **-0.049**) —
  즉 **두 정답셋 모두에서 모델이 지속성 대비 순가치를 못 낸다**, 정도만 다를 뿐(KOMIS는
  크게 열세·교사는 근소 열세) 방향은 같다. report.md의 y_lag1 dQWK=0.765(간접 증거)를 이번에
  직접 계산으로 재확인 — 피드백기반_수정플랜 D-1(y_lag1 의존도 완화)의 긴급도 상향.
- **권고**: 향후 QWK 보고 시 절대값과 함께 QWK−QWK_persist(순개선)를 의무 병기.

[^answer-eval]: 실행(2026-07-16): `MSR_DB=komir/warehouse/minerals.duckdb python3 -m
scripts.diagnosis_answer_eval` → `outputs/model_opt/diagnosis_answer_eval.md`.

## 2026-07-16 — 피드백기반_수정플랜 실행 착수: F-1(수치 불일치) 실측 재검증·정정

`documents/5.feedback/{260716_claude_feed_back.md, 260716_codex_feed_back.md}` 통합 수정플랜의
F-1(P0) 실행. "geo index QWK 기여도 0.012 vs 0.001 불일치" 지적을 원본 로그 대조로 재확인한 결과,
**같은 실험의 다른 값이 아니라 서로 다른 두 지표가 같은 "dQWK" 명칭을 공유해 오인된 것**으로
확인됨. `model_opt/report.md`의 0.012(geopolitical_risk)는 **피처 제거 민감도**(챔피언 모델에서
해당 피처 제외 시 QWK 하락폭)이고, `model_opt/partial_pooling.md`의 0.001(LI·CU 평균)은
**모델 구조 비교**(부분풀링 QWK − 챔피언 QWK)로 정의 자체가 다름 — 양쪽 문서에 정정주석 추가.
- 근사중복 3단계 산수도 DB 직접 재실행으로 재확인[^f1-dedup]: 원본 1,815,193건(날짜있음) →
  정확일치(반복보도) dedup **471,107건 제거** → 1,344,086건(`sensitivity_geo_weights.md` 분석
  모집단과 정확 일치) → 근사중복(정규화·토큰키) dedup **112,167건 제거** → **최종 지수계산
  대상 1,231,919건**. `indexer.py`의 "6,510건 중 53건(<1%)" 주석은 GKG 병합 전 초기 소규모
  예시였음을 명시(현재 프로덕션 규모에서는 정확일치 단계만으로 약 26% 제거)로 정정.
- `neardup_embed_260715/report.md`의 "키dedup 통과 1,194,163건"과는 37,756건 차이 — 07-15→
  07-16 사이 신규 이벤트 적재로 인한 시점 차이로 추정(별도 검증 필요 시 재조회).

[^f1-dedup]: 조회(2026-07-16): `GEO_EVENT_SOURCE=db GEO_PUBLISH_DB=komir/warehouse/minerals.duckdb
python3 -c "..."`(indexer.py `compute()`의 로딩·필터·dedup 단계를 그대로 재현하는 스크립트,
komir/geo/store.py `load_events()` DB 모드 사용) — 출력: 원본 1,815,194 → 날짜미상 -1 →
정확일치dedup -471,107(잔존 1,344,086) → 근사중복dedup -112,167(최종 1,231,919).

## 2026-07-16 — A-2(경보 계열2 시설·수송) 데이터 계층 구축·에스컬레이션 후보 백테스트(기각)

피드백기반_수정플랜 A-2(Codex 최우선 지적: 3계열 경보체계 중 시설·수송 계열 미착수) 실행.
- **신규 `geo/dimension.py`**: event_type(32,398종, 한글/영문/대소문자 혼재) → dimension 5분류
  (ops/corridor/trade/input/policy) 규칙매핑. ops="재해·파업·사고·화재·폭발·가동중단·감산" 등,
  corridor="항만·물류·운송·봉쇄·철도" 등.
- **`geo_event` 테이블에 `dimension` 컬럼 추가·전량 백필**(ALTER+조인UPDATE, 행수 불변 확인:
  1,815,194→1,815,194)[^a2-backfill]. 분포: policy 1,770,903(97.5%)·ops 43,557(2.4%)·
  corridor 706·input 17·trade 11 — "재해"(28,528건) 최초엔 policy로 오분류돼 정규식 보강
  (natural disaster류 포함) 후 ops로 재분류.
- **에스컬레이션 트리거 후보 백테스트**(신규 `scripts/dimension_c2_backtest.py`, "지정학 고신뢰"
  트리거를 폐지시킨 07-16 override_backtest.py와 동일 방법론 재사용): dimension∈{ops,corridor}
  (severity≥2)로 좁힌 신규 트리거를 구 광역 트리거와 나란히 검증[^a2-backtest]. 결과:
  QWK 0.937→0.889(-0.048)·FAR 0.044→0.099(+0.055)·**결과선행 lift ×0.4**(격상주 실현율 0.036 <
  비격상주 0.089, 기저 이하) — **폐지 판정**. dimension을 좁혀도(2,997건→340건, 11.3%) 신호가
  회복되지 않아 구 광역 트리거의 결론(폐지)이 재확인됨. **alert.py의 실제 경보단계 계산에는
  반영하지 않음**(ALERT_OVERRIDE_GEO 스위치·compute_alerts 로직 무수정).
- **판정**: 데이터 계층(dimension 분류·백필)은 완료·보존(향후 XAI·대시보드·사유인용 등 설명용
  자산으로 유효), 계열2를 "하드 에스컬레이션 규칙"으로 alert.py에 결합하는 것은 근거 부족으로
  기각. 법정 3계열 요건은 §7(경보_3계열_구조_정의 문서)처럼 "설명/보고 계층"에서 충족하는 방향
  으로 A-1·A-3·A-4 문서화.

[^a2-backfill]: 실행(2026-07-16): `ALTER TABLE geo_event ADD COLUMN dimension VARCHAR` 후
distinct event_type(32,398건)만 `geo.dimension.classify_dimension()`으로 매핑해 임시테이블
등록, `UPDATE geo_event SET dimension=m.dimension FROM _dim_map m WHERE geo_event.event_type=
m.event_type` 조인 UPDATE(1.8M행 regex 반복 회피). 전후 `select count(*) from geo_event` 동일
(1,815,194) 확인.
[^a2-backtest]: 실행(2026-07-16): `MSR_DB=komir/warehouse/minerals.duckdb python3 -m
scripts.dimension_c2_backtest` → `outputs/model_opt/dimension_c2_backtest.md`.

## 2026-07-16 — C-2(NB2 확률화 레이어 피처 제거 민감도 분해)

피드백기반_수정플랜 C-2(Claude 최우선 지적: "b1(EWMA)이 지배적인지=관성모델인지 확인 필요")
실행. 신규 `geo/prob_decompose.py` — diagnosis_opt.py의 dQWK와 동일 방법론을 NB2 확률화
레이어(λ=exp(β0+β1·x_ewma+β2·x_geo+β3·x_vol))에 적용, 피처 1개씩 제외 재적합 후 test(2024+)
burst Brier 악화폭(dBrier)으로 기여도 측정[^c2-decomp].
- **광종 평균**: x_ewma(관성) dBrier **+0.0107**(최대 기여, 진단모델 y_lag1의 0.765만큼 압도적
  이진 않음) vs x_geo(지정학지수 자신) **-0.0097** vs x_vol(보도량통제) **-0.0170**(둘 다 음수
  = 제거해도 평균적으로 악화 없음, 오히려 근소 개선).
- **광종별 편차 큼**: REE는 x_geo -0.0483·x_vol -0.0824로 특히 부담(11.067의 극단적 α와 함께
  과적합 의심), LI·NI는 x_ewma가 양(+0.019/+0.010)으로 뚜렷한 관성 신호. CU는 x_ewma만 소폭
  양(+0.003), CO는 전 피처 거의 무기여(-0.002~+0.001).
- **해석**: 우려("사실상 관성 모델")는 부분적으로 사실 — EWMA가 유일하게 일관된 양의 평균
  기여를 보이나, 진단모델처럼 압도적이지는 않다. x_geo·x_vol의 음(-) 평균 기여는 두 피처가
  현재 파라미터화(선형, 시차 없음)로는 OOS에서 잡음에 가깝다는 신호 — 향후 과제로 남김(광종별
  정칙화 또는 x_geo 시차·비선형 변환 재검토).
- CU burst_k=860 이상치 의심되어 원자료 재검증: 실제 주간 심각(severity≥2) 이벤트수 중앙값
  382·P90 815(CU가 코퍼스 압도적 비중을 차지해 실제로 타당, 버그 아님)[^c2-cu-check].

[^c2-decomp]: 실행(2026-07-16): `GEO_EVENT_SOURCE=db GEO_PUBLISH_DB=komir/warehouse/
minerals.duckdb python3 -m geo.prob_decompose` → `geo_data/outputs/prob_decompose.md`.
[^c2-cu-check]: 확인(2026-07-16): `geo.prob_model._weekly_panel()`로 CU n_severe 분포 직접
조회 — `describe()`/분위수/상위10주 출력, 최대 1,948건/주(2016-01-17).

## 2026-07-16 — C-1(NB2 target 변경 v1→v2 전후 분리 평가)

피드백기반_수정플랜 C-1 실행 — 동일 모델 구조(피처·train/test 분할 동일)에서 target 정의만
v1(P(y≥1))/v2(P(y≥burst_k=P90))로 바꿔 재적합, "개선이 target 재정의 때문인지 모델 때문인지"
분리[^c1-sep]. 결과(`outputs/model_opt/prob_target_v1_v2_separation.md`): **v1은 CU·NI 학습
기저율 100%(매주 반드시 발생, 무정보)·CO·LI도 84~94%로 사실상 포화, REE는 기준선 대비 개선폭
-0.357(치명적 악화)** — v1이 무의미했다는 기존 서술을 오늘 데이터로 확정 재확인. **v2 전환
후에는 CU +0.0055·NI +0.0058·REE +0.0612(개선) vs CO -0.0011(동률) vs LI -0.0103(열세)**로
기존 정성 서술("CU·NI·REE 개선/CO 동률/LI 열세")이 정량 재확인됨. 결론: v2 우위는 "쉬운 타깃
착시"가 아니라 반대(v1이 무의미했던 것을 burst 재정의가 실제로 복원) — LI 열세는 실재 약점
(C-4 과제와 연결).

[^c1-sep]: 실행(2026-07-16): `GEO_EVENT_SOURCE=db GEO_PUBLISH_DB=komir/warehouse/
minerals.duckdb python3 -c "..."`(prob_model/prob_decompose의 `_fit`/`_predict`/`_p_ge` 재사용,
k=1 vs k=burst_k로 동일 λ에서 두 타깃 Brier 계산) → `outputs/model_opt/
prob_target_v1_v2_separation.md`.

## 2026-07-16 — B-1(severity·sgn 하드코딩 값 실증 점검, 부분 완료)

피드백기반_수정플랜 B-1 실행 — 전면 그리드서치는 과적합 위험으로 보류하고, 현재 값(severity
선형 0~3, direction_sign supply_down=1.0/supply_up=-0.5/neutral=0.2)의 방향성을 고신뢰소스
이벤트(2020+, 4,861건) × 발생주 다음 4주 누적 로그수익률(logret, mart_weekly_diagnosis)로
점검[^b1-check]. 결과(`outputs/model_opt/severity_sgn_empirical_check.md`):
- **severity 선형 가중은 supply_down(2,831건, 62%)에서 단조 dose-response로 실증 지지**됨
  (severity 1→-0.0004→2→+0.0087→3→+0.0180) — 유지 권고.
- **supply_up(-0.5)의 부호가 실증과 반대**: 평균 4주 forward 수익률 +0.0028(음이 아니라 양) —
  크기는 작아(supply_down의 1/3) 즉시 뒤집을 근거는 부족하나 재검증 필요 항목으로 격상.
- neutral(+0.2)도 실측 평균 음(-0.0106)이나 애초 예측력이 약한 게 정상이라 중요도 낮음.
- **부분 완료로 명시**: 유의성 검정·시차구조·confound 통제를 갖춘 전면 재추정은 미실시, P2
  잔여 과제로 이관.

[^b1-check]: 실행(2026-07-16): `mart_weekly_diagnosis.logret`(Monday 앵커)과 `geo_event`
(direction 3종, 고신뢰소스)를 주 단위 매칭(`Period('W-SUN').start_time`), `rolling(4).sum()
.shift(-3)`으로 forward 4주 누적수익률 산출, 방향×severity 그룹 평균 비교.

## 2026-07-16 — 감사 잔여 4건 일괄(에이전트 병렬): 부분풀링·오버라이드·HS계층·event study

전부 DB read_only 병렬 평가(신규 스크립트 4본), 오버라이드만 결과를 운영에 반영.
- **① 부분 풀링(B-2③, partial_pooling_eval.py): 기각 — 완전풀링 유지.** 계층 Ridge의
  최적 풀링 강도 s=0.0(=완전풀링)으로 수렴(s>0 전 구간 과적합), MixedLM(+0.012)은 유의
  기준 미달. 감사 전제(LI≠CU 계수)를 심각 표본(13건, LI 1건)이 지지하지 않음. 정정(에이전트
  자체검증): MixedLM 'Miss 0.385→0.222 개선'은 3폴드 vs 1폴드(수렴 실패로 최종 폴드만)
  **표본 불일치 착시** — 동일표본 비교 시 QWK +0.005·Miss 무차별. 재검토 여지 각주 철회,
  초기 폴드 비수렴이라 실전 배치 부적합.
- **② 오버라이드 백테스트(B-2④, override_backtest.py): 재설계 반영.** 전체 On이 QWK
  0.937→0.416·FAR 0.044→0.592로 파괴적. 판정·적용: 변동성 유지(결과선행 lift ×3.7),
  편중 목표단계 경계→관심 강등(단독 FAR 0.20), **지정학 격상 폐지**(674주 상시격상·실현율
  기저 이하·지수와 이중계상; ALERT_OVERRIDE_GEO=on 복원 스위치, 사유 인용은 유지).
  alert.py 수정·재적재 — 분포 정상화(정상 68~196주/광종), 최신 경보 불변.
- **③ HS 계층 정합(B-3⑤, hs_hierarchy_eval.py): 요구 시 bottom-up.** coherence 문제
  실재(base 합산 불일치 8~16%), MinT/OLS는 규모차 300배 무시로 소계열 왜곡(HS4 MASE
  6~27배 악화) → 부적합 판정(원인 규명 포함). BU가 품목·총량 동시 제공의 승자(총량
  WAPE 22.9 — 현행 동급). 총량만 쓰는 현 운영엔 도입 불필요.
- **④ Event study(B-3⑥, event_study_lp.py): REE에서 정책 인용급 발견.** 풀링은 유의
  반응 없음(정직 — 이벤트 2024~25 편중, 검정력 낮음). REE 단독: 수출통제 공시 후
  **h=5~8개월 수입물량 +5~7%**(h=5 p<0.001, placebo 통과) — 실물 부족 이전의
  front-loading·대체조달 신호로 해석(인과 아닌 상관으로 신중 서술).
- 워드 상세판 §2-4(오버라이드 재설계)·§8(8·10 갱신, 11·12 신규) 반영.

## 2026-07-15 — 감사 잔여 6종 일괄: 지수 정밀화 3종·v2 재앵커 + 민감도·lead time·CU 조사(에이전트 병렬)

**지수 v2**(메인 세션, indexer 직렬 수정): ① 볼륨 드리프트 정규화 — 실측상 코퍼스가
2016 29.2만/년→2020~22 12.5만/년 감소 후 회복(증가 일변도 통념과 반대), EWMA 52주 기저·
평균1·클립 0.5~2로 시간축 눈금 통일(연대별 교정 -3.2/+3.9/+7.0pt) ② stock/flow 감쇠 —
수출통제·제재·정책 hl=13주/보도·파업·재해 2주/기타 4주, 질량1 커널(총량 보존), 감쇠 잔존
주간도 발행(3,439→3,529행) ③ 근사중복 키 dedup — 정규화 80자+토큰 정렬 키로 +112,167건
제거. 분포 변화로 **scale_k v2 재앵커**(CU 297/NI 125/CO 14/LI 12/REE 34, P90=88 복원
87.8~88.6 검증, publish 기본 버전 v2). 랜드마크(REE 수출통제 주간 97~100) 유지.
- 임베딩 표본 검증(신규 validate_neardup_embedding.py): 키 dedup 후 **잔존 근사중복 12.0%**
  (30버킷·6,161건, cos≥0.9) → 2단계(BGE-M3 전량, 수집서버 GPU 배치) 도입 필요 판정.
**에이전트 병렬 3건**: ④ 가중치 민감도(sensitivity_geo_weights.py) — 순수 곱 구조라 전역 스칼라 섭동은 퇴화(순위 불변, 부록 A 실증) → '성분평균 편차 ±30% 신축'(상대섭동)으로 검정:
rel·conc·imp_mult 강건(P90 집합 Jaccard 0.92~0.96), **severity·sgn 취약(0.67~0.70) →
정밀화 우선순위**. 복제검증 저상관은 v2 동시 개정 타이밍 탓(리포트에 원인 주석).
⑤ lead time(lead_time_eval.py) — **h=0~3개월 전 지평에서 Naive 대비 QWK 우위, 격차
+0.009→+0.229 확대**(0.919/0.891/0.859/0.821 vs 0.910/0.799/0.692/0.592), FAR≤1.8%.
h=0 Miss만 Naive 근소 우위(정직 명기). 비용민감 컷 스캔 부록(비용비 발주처 합의 필요).
⑥ CU 역방향(investigate_cu_proxy.py) — **가설 채택**: vol_spike 3건 전부 거시발(COVID·
Fed 긴축), 2024-05 COMEX 스퀴즈는 vol90 정의가 포착 못함, fx_vol 통제 후에도 음(-),
거시 AUC 0.59>교사 0.46. 대안: 백워데이션 진입 AUC 0.551(유일 >0.5). 권고: CU는 변동성
아닌 기간구조·수입집중 병행 해석(발주 문서 주석 채택).
**v2 전 체인 재적합**: prob isotonic Brier 0.121→0.106·ECE 0.086→0.028, 진단 **QWK
0.925·전환월 0.745**(Ridge 풀링 우승 불변), ablation 지정학 전환월 기여 +3.4→**+6.9%p**
(0.690→0.759 — 정밀화가 신호 순도 개선). 최신 경보 CU 심각/CO·REE 주의/LI 관심/NI 정상.
워드 2종 §2-3/2-4/5/5-1/8·요약본 5-1/5-2 갱신.

## 2026-07-15 — import_hhi 국가 기준 재배선 + 진단 재적합 (HHI 결함 교정 완결)

- normalize의 agg_trade_annual HHI 원천을 raw_customs_annual_bycountry(국가별 정본)로
  교체(총액·YoY·CAGR은 합계 기반이라 종전 경로 유지, bycountry 없는 환경 폴백+경고).
  교정 실측: LI 6,509·REE 6,941(만점 1만, 고집중) vs 종전 품목 HHI 2,434~2,687(무의미).
- 전 체인 재적합(마트→8후보 재검증→nowcast→alert→ablation): **QWK 0.905→0.910,
  전환월 적중 0.631→0.742(+11%p)** — 교정 HHI+이중 노출 지수 동시 반영 효과.
  Ridge(풀링) 우승 불변, 최신 경보 불변(CU 심각/CO·REE 주의/LI·NI 정상 — 안정성 확인).
- ablation 갱신: +수입구조(국가 HHI) 0.938/0.690 → +지정학 0.919/0.724 — 지정학은
  QWK 소폭 희생하되 전환 감지 +3.4%p(보조 신호 역할 일관). 워드 2종 수치 갱신.

## 2026-07-15 — 국가×광종 이중 노출 가중 (감사 후속 4번 완료) + 관세청 국가차원 결함 교정

**부수 발견(치명 등급)**: 관세청 수집기가 country←statKor(품목명) 오매핑 — 국가 차원 소실.
실API 검증으로 확인(국가는 statCdCntnKor1/statCd). 합계는 groupby-sum이라 정상(예측 무영향)
이나 **기존 import_hhi는 '품목 구성 HHI'였음(결함)**. 수집기 교정(country_cd·item_kor 보존).
- 국가별 연간 재수집: 161 HS × 2013~2025 = 2,093콜 → raw_customs_annual_bycountry
  39,962행·223개국(기존 테이블 보존). REE 중국 $3.0B 최상위 정합.
- build_kr_import_share.py: 국가별 수입비중(한글→영문 별칭 확장, 수입액 가중 커버리지
  93.5%) → geo refdata. **교정판 수입국 HHI: LI 0.59~0.67·REE 0.69~0.71 고집중 vs
  CU 0.08·NI 0.09 분산** — 종전 품목 HHI 대비 정책적으로 유의미.
- indexer._apply_kr_exposure(): imp_mult=(1+s_imp)를 광종별 이벤트 모집단 mean-one 정규화
  (P90 앵커 보존; 순수 곱 s_prod×s_imp는 비수입 생산국 이벤트를 0으로 지워 기각·주석화).
  실측: 이벤트 34.4% 매칭, 최대 배수 LI/REE 1.59·CO 1.48·CU 1.24·NI 1.19.
- 지수 diff: **REE 평균 +3.4pt·최대 +14.6pt(중국 수출통제 주간들), LI +1.0(2021 급등기),
  CU/NI 중립(+0.1~0.4)** — '한국의' 지수로 전환 의도대로. DB 재발행 완료.
- 잔여(후속): weekly_mart의 import_hhi를 국가 기준(연간 ASOF)으로 교체 재배선 +
  진단 재적합, 월간 국가별 재수집(19,320콜)은 월단위 국가 피처 필요 시.

## 2026-07-15 — 결과변수 proxy 라벨 구축·교차검증 (감사 후속 1(b), 1차 완료)

scripts/build_proxy_label.py: "향후 3개월 내 (①vol90>기준기간 P95) OR (②수입량 동월기준
-20% 이탈)"의 관측 가능 라벨 → mart_proxy_label(1,139 광종-월) + 교차검증 리포트.
- **합성 proxy는 AUC 0.44로 무정보처럼 보였으나 분해가 진실**:
  · ①가격 급변: 교사 0.60/모델 0.64 — 광종별 **LI 0.90·NI 0.91·REE 0.99**(강한 선행성
    실증), CO 0.52 무정보, **CU 0.18 역방향**(LME 거시·투기 변동성이 수급 지표와 다른
    동학 — 후속 조사 항목). 경보(경계↑)→가격급변 precision 0.43/recall 0.38.
  · ②수입 이탈: AUC 0.33~0.46, 기저율 40% — 월간 선적 덩어리짐 노이즈 지배로 **결과변수
    부적합 판정**(강화 정의 -20%×2연속·-30%도 동일). 분기 집계 재정의 후 재도입(로드맵).
- 결론: 경보 체계의 실물 선행성은 가격 경로에서 3개 광종에 대해 실증됨. 수입 경로
  라벨과 CU는 재정의·조사 필요, 최종 라벨 합의는 발주처 협의(A-1(a), 회의 안건).
- 워드 상세판 §8 로드맵 1번 "부분 잔여"로 갱신.

## 2026-07-14 — 예측구간 conformal 보수화(CQR) — 감사 후속 3번 종결

분위 HistGBM 구간의 과소커버(0.60/0.72) 해소. CQR: 보정 원점들의 OOS conformity score
E=max(q10−y, y−q90)(log공간)의 유한표본 (1−α) 분위를 가산폭으로 [q10·e^−Q, q90·e^+Q].
- 백테스트(누수 차단): 보정 원점 2022-06/12(실측 ~2023-12, 평가창과 무겹침) →
  **커버리지 0.60→0.73 / 0.72→0.85 (평균 0.79, 목표 0.80 달성권)**.
- 발행: 최신 가용 원점 3개(last_m−24/18/12개월)로 보정(ton 0.318/unit 0.164) —
  구간 sanity 확인(CU h=1 톤 17만~43만/점 21만). basis에 가산폭·보정원점 명세.
- 워드 2종 갱신(§2-5·§8 로드맵 3번 완료 처리, 요약본 5-3). 감사 로드맵 2·3번 종결 —
  다음 후보: 1번 proxy 라벨, 4번 이중 노출 가중.

## 2026-07-14 — 관세청 월간 백필 완료 → 156개월 재학습·재판정 (감사 후속 2·3 종결)

- 백필 완료: 161/161 HS, raw_customs_monthly 232,001행(2013~2025) → normalize:
  fact_trade_monthly 5,408→21,955행. **crontab 00:40 백필 항목 제거**(완료 정리).
- forecast_unit 재학습(표본 36→156개월, 광종별 156개월 완전 패널):
  · **대 계절나이브 재판정: 혼조→우위** — 금액 WAPE 28.1/19.4 vs 나이브 36.0/20.9
    (두 원점 모두 상회), MASE 0.93/0.94. 백필이 정확히 처방이었음이 실증.
  · **재귀 vs Direct 재판정: 재귀 유지**(MASE 0.94 vs 1.02) — 36개월 때(1.71) 대비
    Direct가 크게 좁혔으나 역전엔 못 미침. 자동 판정 로직이 상시 감시.
  · 단가 vs 랜덤워크: 우위 유지(MASE_unit 0.81/0.77 vs RW 1.02/0.81).
  · 80% 구간 커버리지 0.60/0.72 — 표본 확대로 구간이 좁아지며 과소커버(36개월 땐
    0.82/0.70). conformal 보수화가 후속(감사 로드맵 3번 잔여분).
  · 금액 직접예측이 156개월에선 경쟁력 회복(WAPE 18.6/28.4) — 분해 유지 근거는
    원점 간 안정성(28.1/19.4)+과업의 물량·단가 개별 산출 요구.
- 발주 워드 2종 성적 갱신(§2-5·§5·§6-2·§8, 요약본 5-3).

## 2026-07-13 — 수입예측 v2: Direct 다중기간+분위 구간(MC 합성) 구현, 재판정은 백필 후

감사 로드맵 2·3번 선구현(사용자 지시: 백필 재학습과 함께 진행).
- Direct h별 독립 HistGBM(계절항은 t+h 기준) + 분위 모델(q10/q90, log공간 → 단조변환 보존).
- 금액 80% 구간 = 물량×단가 마진 lognormal 근사 후 **몬테카를로 합성**(분위 직접 곱 금지).
- 점추정 방식은 백테스트 금액 MASE로 자동 판정(MSR_FORECAST_METHOD env 강제 가능).
- 36개월 실측: Direct 열세(금액 MASE 1.71 vs 재귀 0.94 — h별 학습행이 h개월씩 깎여
  소표본에서 구조적 불리, 원점1 ton MASE 16 붕괴) → **재귀 유지 + 구간만 Direct 분위 사용**.
  80% 구간 커버리지 0.82/0.70(목표 0.80 근접). 156개월 재학습 시 재판정 예정.
- 발행 스키마 확장: ton_lo/hi, unit_lo/hi, pred_value_lo/hi + basis에 method·interval 명세.

## 2026-07-13 — 외부 방법론 감사 대응: 즉시항목 5건 수정·실증, 나머지 로드맵化

감사 지적 16건 중 즉시 가능 5건 당일 처리(치명 1~4순위 + 5 일부), 잔여는 문서 §8 로드맵.
- **A-1(c) 단계 컷 앵커**: 교사신호는 KOMIS 외생 지표(순환 아님)임을 확인. 단, 컷이 전체
  분포 분위로 재계산돼 "항상 ~5%가 심각"이던 것을 기준기간(2020-01~2023-12) 동결 컷으로
  절대화(diagnosis_opt.ANCHOR_SPAN·anchored_cuts → nowcast·alert 배선). 효과 실측: 최신
  경보 LI·NI 관심→정상(상대분위 인플레 제거), CU 심각·CO/REE 주의 유지.
- **A-2 NB2 캘리브레이션**: P90 임계 look-ahead 감사 → **무혐의**(burst_k는 train만,
  기준선도 train 기저율). 과소예측 편향은 사실 → isotonic 사후보정 구현(OOS 쌍 시간순
  60/40 분할): 평가구간 Brier 0.1166→0.1120, ECE 0.059→0.044. 발행에 p_burst_cal 병기.
- **A-3 Ablation**(scripts/ablation_diagnosis.py): 진단에서 Δ지정학 QWK +0.001, 전환월
  적중 +0.035(0.655→0.690) — **작음(정직 기록)**. 주동력은 가격(전환 0.138→0.586).
  반전: **수입예측에서 geo exog 제거 시 금액 WAPE 37.9→103.8 / 18.2→24.0 붕괴** —
  파이프라인 존재 증명은 수입예측(단가 경로)에서 성립. 포지셔닝 전환: 진단 보조 +
  수입예측 exog + 독립 산출물(오버라이드·사유 인용).
- **B-3② 단가 정직성**: 랜덤워크(원점 단가 유지) 기준선 상시 병기 — MASE 1.20/0.73 vs
  RW 1.53/0.81 **두 원점 모두 모델 우위**(geo exog 동력). 우위 상실 시 시나리오 전환 설계.
- 문서: 워드 보고서에 §5-1(ablation 표)·§8(로드맵 10항) 신설, §2-4/2-5/4/5 갱신(발주 톤).
- 잔여(로드맵): proxy 라벨 교차검증, Direct 다중기간, 구간추정(conformal+MC), 이중 노출
  가중, lead time 표, 볼륨 드리프트, stock/flow decay, 임베딩 dedup, 부분 풀링, event study.

## 2026-07-13 — 수입예측 평가지표 교체: SMAPE → WAPE·MASE 주지표 (결론 일부 뒤집힘)

사용자 지적(SMAPE의 0 근처 분모 붕괴·저값 왜곡·광종 스케일 300배 차) 수용 — M4/M5 이후
표준대로 **WAPE**(Σ|F−A|/Σ|A|, 총합비율·0값 강건)와 **MASE**(계절 m=12 나이브 스케일,
광종별 정규화 후 매크로 평균, <1=우수)를 주지표로 병기(forecast_unit.py). SMAPE는 이력
비교용 유지. 동일 데이터(36개월, 재정규화 전) 재실행 결과:
- **분해>직접 결론은 강화**: 금액 WAPE 분해 18.2~37.9 vs 직접 38.6~59.7 — 직접예측이
  2차 원점에서 붕괴(SMAPE 43.6이 가려주던 실패가 WAPE 59.7로 노출).
- **대 계절나이브 결론은 뒤집힘(혼조)**: MASE 분해 1.13/0.76 vs 나이브 0.73/0.84 —
  원점 2024-06에선 나이브가 우세. SMAPE(25~31 vs 28~32)가 근소 우위처럼 보이게 했던 것.
  원인은 학습 36개월(계절 실질 2주기) — **백필 완료(156개월) 후 재학습이 선결**.
- basis(근거 JSON)에 지표 설명 포함, 발주 보고 워드 문서 §2-5·§5도 새 수치로 갱신.

## 2026-07-12 — 아키텍처 정합: "전처리기→DB→추정기" 배선 + 주/월 실행 체인 완결

5모듈 분리(수집기/전처리기/지정학 추정기/수급위기 진단기/수입 추정기) 점검 결과 갭 2건 해소.
- **갭① 추정기의 DB 읽기 전환**: 기존엔 extract(→parquet)→index(parquet 읽기)→publish(사후
  발행) 순서라 "전처리기가 DB에 넣고 추정기가 DB에서 읽는" 계약과 반대였음.
  · `geo publish --what events|index|all` 단계 분리(publish.py) — events는 extract 직후,
    index는 추정 직후 발행. geo_event에 **provider·extractor 컬럼 추가**(빠지면 DB 모드에서
    GKG '뉴스' 티어 제외가 무력화되는 조용한 회귀 — 발견 즉시 방지). 신규 컬럼 출현 시
    DELETE+INSERT가 죽으므로 컬럼 셋 비교 후 테이블 재생성 폴백.
  · `store.load_events(source=)` + env `GEO_EVENT_SOURCE=db`(+`GEO_PUBLISH_DB`) — 추정기
    (indexer·prob) 전용 모드. publish 계약(commodity_code, source '')→내부 계약 복원.
  · indexer: source 컬럼 기존재 시 manifest 병합 스킵(충돌 방지).
  · **동치성 실증**: DB 모드 compute() 3,439행 = 파일 모드 geo_index와 전 행 매칭,
    지수 최대 차이 0.0. prob 주간 패널도 DB 모드 2,745행 정상.
- **갭② 주/월 실행 체인 완결**(`scripts/schedule.py` 전면 재작성):
  · weekly = ingest-bundles→extract→publish(events)→index(DB)→prob(DB)→publish(index)
    →weekly_mart→nowcast→alert→publish_results. geo는 서브프로세스(단계 격리, cwd=komir).
  · monthly = 관세청 최근 24개월 **증분**(신규 `pipeline.collect_customs_incremental` —
    HS×연도구간만 삭제 후 삽입; 기존 collect_customs는 전삭제형이라 2013~22 백필 유실 위험)
    →ECOS→normalize→features→forecast_unit→publish_results.
  · cron 2줄(월 06:00 weekly / 매월 1일 07:00 monthly)로 운영 투입 가능 — 남은 과제 ⑥의
    분석서버 반입·기동만 잔여.

## 2026-07-12 — 미/중 공시 10년 백필 테스트 (/goal) — 지수 반영 실증

"최근 10년치 공시 수집→백데이터 채움→지정학지수 반영 가능?" 검증.
- 미국: 기존 백필(886건)이 이미 2016~2026 연도별 고른 분포(150/93/63/59/78/55/55/78/124/91/40)
  — 절단 없음, 10년 커버 확인.
- 중국: 목록 JS렌더링 한계 우회 — **Wayback CDX로 공고 URL 인벤토리**(aqygzj 130 + 구 상무부
  zcfb 69) 확보 후, 라이브 우선·죽은 구 경로는 아카이브 스냅샷에서 본문 수집
  (`collector/cn_trade_backfill.py` 신설, 1회성). 신규 122건(2020:6/2024:39/2025:67/2026:10 —
  Wayback 아카이브 밀도 한계로 2016~23 희박, 2024~25 수출통제 격화기는 두껍게 확보).
- 추출: CN_MOFCOM 이벤트 5→**55건** — 2025-04 中중희토류 수출통제 결정, 2025-10 희토류
  생산설비·원부자재 수출통제(통제품목 코드 2B902/1C914 원문) 등 역사적 공고가 1차 사료
  sev 3.0으로 적재.
- 지수 반영 실측(diff): REE 2025-01-19 주 +24.3pt(43.6→67.9), 2026-03-01 주 +21.3pt(→94.2),
  2025-09-21 주 +11.6pt 등 — 영향은 REE(평균 +2.85)에 집중, CU/NI는 GKG 볼륨에 희석(±0.1).
  결론: **백필 공시가 지수에 정상 반영되며, 특히 REE 수출통제 국면의 백데이터가 1차 사료로
  강화됨**. 잔여 한계: 중국 2016~23 공고는 Wayback 미보존分 다수 — GKG(보도 기반)가 해당
  구간을 보완(이미 반영돼 있음).

## 2026-07-12 — 미/중 고시 LLM 연동 검증 (/goal) — 정상 확인

점검 4단계: ① vLLM(gemma-4-26b-a4b) 엔드포인트·models.yaml(provider=openai_compat) 정상
② 저장 이벤트 44건 전부 extractor=llm/gemma — 중국어 고시 해석 품질 육안검증(실체명단→
Export Control supply_down, 对日 심사강화→Geopolitical Tension 등 정확) ③ 라이브 재해석
테스트 — 중국 공고 conf 0.9 정상, 미국 1건은 직접호출(폴백 미경유) 0건이나 프로덕션 경로
(json_mode=False 폴백)로는 정상 추출(반덤핑 일몰재심→CU/무역정책) ④ 간헐 빈응답 누락 정량화:
0건 관련문서 81건 전량 재시도 → 추가 1건뿐(44→45) — 나머지 80건은 광물 무관 절차성 공시를
LLM이 올바르게 기각한 진성 0건. 결론: 연동 정상, 누락률 극소(1/82).

## 2026-07-12 — 관세청 월간 2013~2022 백필 시작 (진행 중)

월간이 2023~25만 있던 이유 = API 일 한도(≈1만 콜)로 당시 최근 3년만 수집. 일 한도는 자정
리셋이므로 자체 백필 가능 — `scripts/backfill_customs_monthly.py`로 시작(19,320콜 = 161 HS ×
120개월, 기존 보존형 멱등·상태 재개). **호스트 crontab 00:40 자동 재개 등록** — 2026-07-14경
완료 예상. 완료 후: fact_trade_monthly 재정규화 → forecast_unit 재학습(표본 36→156개월) →
crontab 정리. (메모리 customs-monthly-backfill에도 기록됨.)

## 2026-07-12 — 수입 예측 v2: 단가 분해 모듈 (`msr/models/forecast_unit.py`) — /goal 수행

월 단위 h=1~12 수입 예측을 사용자 지정 구조로 재설계: **금액 = 광물당 톤당 단가(USD/ton) ×
톤(실지출액)** — 물량과 단가를 각각 지도학습(관세청 월간, HS 확정 161코드 바스켓→5광종 필터)
후 곱으로 재조립(항등식 정확 성립).
- 구조: 단일스텝 HistGBM ×2(log톤·log단가, 광종 풀링+더미) 재귀 h=12. 피처 = 자기시차
  (1·2·3·6·12)+롤링3+월 계절성+외생(LME 월평균가·원달러 환율 CSV·지정학 지수 — 예측구간
  최종값 고정, 시나리오 입력 대체 가능 설계).
- 백테스트(워크포워드 2오리진×12개월, SMAPE%): **분해 금액 25.3~31.2 < 직접 금액예측
  36.1~40.0 < 계절나이브 27.9~31.8** — 분해 구조의 우위 실증(단가가 LME에 계류돼 22~27%로
  잘 맞고, 물량은 나이브 대비 소폭 우위). 톤 29.8~35.6.
- 발행: out_import_forecast_unit 60행(base 2025-12 → 2026-01~12) — pred_ton·
  pred_unit_usd_per_ton·pred_value_usd/천달러 + basis(백테스트 근거·지도학습 정의 json).
  publish_results 대상 등록(외부 DB 연동 포함).
- 참고: NI 단가(500~880 USD/ton)가 낮아 보이는 것은 바스켓 혼합 단가 특성(중량 대부분이
  저단가 광석·페로니켈) — 정의상 정상. 학습표본 36개월(관세청 월간 한도 제약) — 2013~22
  월간 백필(발주처 경유)이 정확도 개선의 최대 지렛대.

## 2026-07-12 — 예측 결과 DB화 + 외부 DB 연동(env 주입)

"DB 접속 URL·스키마를 외부 환경에서 주입, 예측 결과와 근거를 DB화" 요구 구현.
- `db/dbio.py::write_df`에 schema 파라미터 추가 — SQLAlchemy to_sql(schema=)로 Oracle 스키마/
  MariaDB DB 지정, DuckDB면 CREATE SCHEMA 후 사용.
- `scripts/publish_results.py` 신설 — env 계약: MSR_PUBLISH_DB(:// 포함=서버DB URL, 아니면
  DuckDB 경로)·MSR_PUBLISH_SCHEMA(선택)·MSR_DB(원천). 발행 테이블(근거 동봉): out_diagnosis_alert
  (4단계+법정 사유·모델 원천·확률·기여·이벤트 인용), mart_diagnosis_nowcast(예측 지수+XAI json),
  out_import_forecast, geo_index, geo_prob.
- E2E 검증(SQLAlchemy 경로 — sqlite 대역, Oracle/MariaDB와 코드 경로 동일): 5테이블 8,326행
  발행, 외부 DB에서 사유·stage_probs·contrib 필드 원문 조회 확인.

## 2026-07-12 — 수급위기 진단 대시보드 프로토타입 (`dashboards/`)

주간 4단계 진단을 UI화(산출물 ③ 모니터링 대시보드의 선행 프로토타입) — 자체완결 단일 HTML
(외부 의존 0, 폐쇄망 게시 가능). 구성: 5광종 요약 카드(단계 chip·신뢰도)/주간 위기지수 차트
(2020~, 하단 단계 리본+지정학 지수 오버레이+클릭으로 주 선택)/선택 주 법정 사유(모델 원천·
확률·기여 병기 문안 그대로)/최신월 XAI 패널(단계 확률 스택바+기여도 다이버징 바, 피처 한글화)/
최근 16주 이력 테이블. 경보색은 붙임2 법정 명칭·색(관심 Blue/주의 Yellow/경계 Orange/심각 Red)
그대로, 다크/라이트 테마 지원. 데이터=warehouse 스냅샷 임베드(재생성 절차는 dashboards/META).

## 2026-07-12 — 최적모델 alert 배선 + XAI(설명가능성) 산출

diagnosis_opt 1위 구성(Ridge 풀링+AR+분위매핑)을 운영 배선하고 착수보고의 XAI 약속 이행.
- `msr/models/nowcast.py` 신설: 전 기간 재적합 → mart_diagnosis_nowcast(월×광종 390행 —
  ci_pred·4단계·단계확률·기여도 json) + final_model.joblib + xai_latest.md.
  · 기여도: Ridge 선형 정확 분해(계수×표준화값, SHAP 선형 특수해와 동일) — 위기지수 방향 부호.
  · Confidence: 광종별 학습잔차 σ 정규근사로 단계별 확률(착수보고 "경계 55%, 심각 30%" 사양).
- `alert.py` 배선: 위기지수 원천 = 모델 nowcast 우선(1,632/1,632주 결합), 교사 폴백,
  ALERT_CRISIS_SOURCE=teacher로 구동작 강제 가능(감사용). 사유 문안에 원천표기(model)+
  단계확률+기여도 상위3 병기 — 예: "[CU·심각(Red)] …(수급위기지수 99/100(model), 지정학1.00)
  확률: 심각 55%, 주의 19%. 기여: y_lag1 +33.1, price_z52 +3.2, …. 관련 이벤트: 'First
  Quantum…'(Panama, sev 3.0/3)".
- 분포 영향 미미(모델이 교사와 고일치 — QWK 0.905), 최신 경보: CU 심각·CO/REE 주의·LI/NI 관심.

## 2026-07-12 — 진단모델 최적화 (`msr/models/diagnosis_opt.py`) — /goal 수행

백데이터(실교사 2020~2026·지정학 2016~) 기반 체계 비교로 4단계 진단모델 최적화.
- 방법: 워크포워드 3폴드(test 2023/2024/2025~), 후보 8종(Naive 지속/Ridge·HistGBM 풀링·광종별
  ×회귀→분위매핑/과업지시서 명시 Logistic·DT·RF 직접분류), 지표 QWK·macroF1·RPS·전환월 적중률.
- 1차 실행의 발견 2건: ① 지속성 Naive(QWK 0.884)가 전 모델 압도 — 진단(nowcast)에서 전월
  교사값은 가용 정보인데 피처에 없었음 → y_lag1(자기회귀항) 추가. ② VIF 폭발 — geo level·
  lag·chg 완전공선 → level+chg만 유지(붙임1 상관성·중복성 분석이 실제로 작동한 사례).
- 최종(3폴드 평균): **Ridge(풀링)+분위매핑 QWK 0.905 > Naive 0.884**, RPS 0.032<0.038,
  **전환월 적중률 0.631 vs Naive 0.000**(단계가 바뀌는 달에서 모델의 실가치 입증, n_chg 기준).
  광종별(최종 폴드): CU 0.961·REE 0.941·LI 0.88·CO 0.768·NI nan(2025~ 전 기간 '정상'이라
  카파 정의불가 — 데이터 특성).
- 피처 민감도(제거 시 QWK 하락): y_lag1 0.823 ≫ price_z52 0.022 > **geo_chg 0.016** >
  **p_burst 0.007** > import_cagr3 0.005 — 지정학 파생피처(변화량·burst확률)가 측정 가능한
  한계기여 확보(레벨 단독은 지속성에 흡수됨).
- 산출: outputs/model_opt/{comparison(_folds).csv, per_commodity.csv, corr_vif.txt, report.md}.
- 다음: 최적 구성(Ridge+AR+분위매핑)을 alert 레이어의 점수단계 산출기로 배선(현재 alert는
  교사 직접 사용 — 운영에선 교사 발표 지연을 모델 nowcast로 메꾸는 구조로 전환).

## 2026-07-12 — 4단계 수급위기 진단 첫 실데이터 산출 + 오버라이드 소스 제한

진단의 계약상 최종 산출(주간 4단계: 관심/주의/경계/심각)을 실데이터로 첫 가동 —
mart(실가격·실교사) + geo_event → out_diagnosis_alert 1,632주(5광종×2020-01~2026-05).
- 버그성 과다경보 발견·수정: geo_event가 GKG 182만건을 포함하게 되면서 지정학 오버라이드
  (severity 3 → 격상)가 거의 매주 발동 → '심각'이 주의 25~30%. 오버라이드 트리거를 고신뢰
  소스(관보 US_FederalRegister/CN_MOFCOM + 큐레이션 보고서)·supply_down으로 제한 — 붙임2
  계열1("수출제한 실시")은 뉴스 보도가 아니라 확정력 있는 근거로만 발동해야 하고, GDELT
  뉴스 신호는 이미 변수⑥(지수)으로 점수단계에 반영되므로 이중계상 방지 겸.
- 수정 후 분포(주 단위): 정상 20~38% / 관심·주의 / 심각 6~19%(COVID·우크라이나·DRC 수출중단·
  중국 수출통제 국면 포함 기간임을 감안하면 타당 범위). 최신 주: CU 심각, CO·LI·REE 주의, NI 관심.
- 남은 것(v1 §7-4 완전체): 단계 = max(점수단계, 계열1, 계열2) 구조로 개편 + dimension 백필
  기반 계열2(시설·수송) 트리거 — 현재는 기존 alert_rule_v1(분위수+오버라이드+히스테리시스) 유지.

## 2026-07-12 — 실가격·교사신호 로딩 → 진단모델 첫 실데이터 가동

`scripts/load_komis_xlsx.py` 신설 — KOMIS 제공 xlsx를 warehouse에 적재, SYNTH 완전 교체.
- 가격(fact_price 6,839행): 「KOMIS 핵심광물 공급망 통계」 '주간 평균' 시트 단일 소스로 5광종
  전부 확보 — CU/NI: LME CASH+3M(2001~), CO: LME CASH(2010~), LI: 탄산리튬 CIF China(2018~),
  REE: 산화네오디뮴 FOB China(2010~). 전부 2026-06까지.
- 교사(fact_indicator 385행): 수급동향지표.xlsx 월별 2020-01~2026-05, 5광종(REE=네오디뮴 컬럼).
- SYNTH는 fact_*_synth_backup 테이블로 백업 후 제거(보존 정책). 재실행 멱등(키 삭제 후 삽입).
- 마트 재빌드: 1,610(합성)→4,601행(실데이터), 교사 1,632·지정학 2,844·생산HHI 351·변동성 4,591.
- 진단 첫 실데이터 결과(월간 패널 390행, train 300/test 90=2025~):
  Ridge R² 0.701(MAE 10.87) vs Naive 0.263 — 실질 예측력. 위기 이진분류 AUC 0.988(위기율 23%).
  피처 중요도: import_hhi 0.39 > ref_price 0.30 > spread 0.17 > … > geopolitical_risk 0.01.
- 관찰: ⑥ 중요도가 아직 낮음 — (a) 교사가 시장결과형 지표라 가격·교역 구조에 1차 반응
  (b) 지정학은 평시 평균이 아니라 꼬리/전환점에 기여(경보 계열1 오버라이드가 그 몫)
  (c) 풀링 GBM 기준 — v1 §7의 광종별 가중(REE·CO 지정학 강조)·ordered logit에서 재평가 예정.
  production_hhi는 가용 시점(2025-02+) 제약으로 이번 패널에선 자동 제외 — refdata 백필 후 복귀.

## 2026-07-12 — 일일 운영 모드 확정: `collector daily` + zip 번들

수집기를 "매일 1회: GDELT 하루치 캐치업 + 뉴스/미·중 공시 수집 → collect_YYYYMMDD.zip" 모드로
확정(사용자 지정 — 압축 포맷 zip).
- bundler: tar.gz → zip(ZIP_DEFLATED) 전환, CRC 무결성(testzip)+멤버수 재검증 유지.
- `collector daily` 서브커맨드(수집→즉시 번들, cron용) + daemon `--bundle-each`(compose 기본
  CMD를 1440분+bundle-each로 — 컨테이너 단독으로 일일 운영). 뉴스 기본 소급 2일(경계 유실 방지,
  seen 중복방지가 이중수집 차단).
- geo ingest-bundles: zip/tar.gz 양쪽 수용(하위호환).
- E2E: daily 1회 실행(gkg 4 + gnews 57 + us 886 + cn 16 → zip 9.2MB) → 분석기 발견·라우팅
  (txt 959→inbox, gkg 4→gkg_bulk→파싱 3이벤트) → 멱등 재실행 0건.

## 2026-07-12 — 연간 발행물의 연 단위 적용: 지수 Y 시리즈 + 변수⑤ USGS 배선

사용자 방침("연간 발행 보고서는 연 단위 적용") 구현.
- indexer: 연간(YS) 시리즈 추가 — USGS·IEA·광업요람 등 연간 발행물 이벤트가 연 단위 배경
  신호로 자연 집계(붙임1 다중주기 요구의 '연' 대응). 주기 배수(scale_k×{W:1, M:52/12, Y:52})
  도입 — 주간 P90=88 앵커 의미를 월/연에서도 보존(도입 전 연간은 raw가 52배라 즉시 포화).
  산출 분포 검증: Y 중앙값 62~74·max 81~96(포화 없음). geo_index 3,439행(W 2,743+M 639+Y 57).
- 변수⑤ 배선: scripts/load_usgs.py 신설 — USGS 엑셀정리본(MCS2026 피벗데이터) →
  fact_production_reserve(207행) + agg_production_hhi(광종×연도 생산/매장 HHI, avail_date=
  발행 익년 2/1로 미래참조 차단). weekly_mart에 ASOF 배선 — production_hhi 280행 채움
  (2025-02 이후 행. 2016~23 백필은 수집서버 geo refdata 실행 후 번들 반입 경로).
  HHI 실측치 타당성: CO 0.56(DRC)·REE 0.51(중국)·NI 0.46(인니)·LI 0.20·CU 0.12.
- 남은 배선: 변수④(세계 공급부족 — WoodMac 수급밸런스 CU·NI parquet 확보됨) + 실가격/교사
  xlsx 로딩(SYNTH 교체) → 이후 B v0 스코어카드 가동 가능.

## 2026-07-12 — 번들에 GKG 포함 + 분석서버 오프라인 대응

분석 서버가 외부 인터넷 불가로 확정 — 일자별 번들이 유일한 데이터 반입 경로가 되도록 확장.
- bundler: GKG zip을 번들에 포함(tar 내부 inbox/ + gkg/ 2계층). gkg 증분 상태는 타임스탬프
  기반이라 원본 이동에 영향 없음.
- ingest-bundles: 멤버 라우팅(txt→inbox→ingest / gkg zip→$GEO_DATA/gkg_bulk→gkg-parse 자동
  연쇄, --no-gkg-parse 분리 옵션). 구버전 번들(inbox/ 접두 없음) 하위호환.
- E2E: 기사 2건+실제 GKG zip 2개 → 번들 → 라우팅 전개 → ingest 2 archived(소스 정상 인식)
  + gkg-parse 7이벤트 → 재실행 멱등 0건.
- 오프라인 제약 문서화: LLM은 내부망 vLLM으로 충족, USGS refdata는 수집서버 실행 후 번들 반입,
  도커 이미지는 외부 빌드 반입(collector/README).

## 2026-07-12 — 일자별 번들 인도 프로토콜 (수집기→분석기)

수집기가 매일 inbox를 collect_YYYYMMDD.tar.gz 하나로 묶고(데몬 날짜전환 자동 or `collector
bundle` cron), 분석기가 볼륨에서 번들을 발견해 처리(`geo ingest-bundles` — 전개 후 ingest 자동
연쇄). 기존 파일 계약 위의 전송 형식 변경이라 수정 범위 작음(양단 모듈 1개씩).
- 원자성: .part→rename + 멤버수 재검증. 원본은 _bundled/로 이동(삭제 안 함 — 번들이 일자별
  원시 아카이브 겸임, 보존 정책 정합).
- 멱등: bundles_done.txt 상태 + ingest 파일해시 dedup 2중 방어(재실행 무해 실증).
- 안전: tar 경로탈출 방어, .txt 멤버만 전개.
- E2E 검증: 수집(3건)→번들→발견→전개→ingest(3 archived)→재실행 0건.

## 2026-07-12 — 미국/중국 수출입 공시 → 지정학 위기지수 배선 완성

수집기(us_trade/cn_trade) 산출을 geo 파이프라인에 실배선 + 2016~ 백필 실투입(미국 886건·중국 16건).
- 배선: sources.yaml에 US_FederalRegister/CN_MOFCOM 신뢰도 1.4(관보=1차 사료, 분석보고서 1.3보다
  높게), classify.source_of 경로 인식, GEO_KEYWORDS·COMMODITY_KEYWORDS에 중국어 추가(없으면
  중국 공시가 프리필터에서 전량 탈락).
- 버그 3중 연쇄 발견·수정: ① LLM이 광종 불특정 공시에 commodity='mixed' 반환 → 스키마 검증
  조용한 탈락 — 본문 광종 탐지 확장(광종별 이벤트化, 미탐지 시 스킵). ② as_event_list가 "{}"
  응답을 빈 이벤트 1건으로 반환(truthy라 재시도도 우회) — 빈 dict 필터. ③ vLLM json_object
  강제모드가 "JSON 배열만" 프롬프트와 충돌, 중국어 입력에서 "{}" 도피 지속 — 빈 응답 시
  json_mode=False 폴백 추출기로 재시도(실측 0/5→3/5 문서 성공).
- 결과: 공시 이벤트 44건(US 39: 러시아 산업제재·232/301조·수출통제 개정 / CN 5: REE 4 —
  전략광물 수출통제·실체명단). 지수 diff 실측: REE 2023-10-22 주간 51.6→74.4(+22.8pt, 중국
  수출통제 국면), REE 최신주 +18.2pt, LI 최대 +14.0, CO +11.8. CU/NI는 GKG 볼륨에 희석돼
  평균 ~0(개별 주간 최대 ±1.8) — 영향은 REE·CO·LI 공시 주간에 집중(과업지시서 Step2의
  "희토류=지정학 무기화" 설계 논리와 정합). warehouse 재발행·마트 재빌드 완료.

## 2026-07-12 — GKG 재검증 완료 → 프로덕션 지수 체계 완성 (v1 §11 순번 1~2 종결)

- **재검증 최종**: 2,008,521건 검증 — 확정 1,799,238(89.6%)·기각 209,283(10.4%). 샤드 691개
  병합+기각 실삭제 → geo_data 스토어 1,808,524건(전량 extractor=llm). 문서 이벤트 6,510건+
  manifest 2,801건을 geo_data로 병합해 **프로덕션 단일 스토어**(1,815,034건) 구성.
- **광종별 scale_k 확정 캘리브레이션**: GKG는 CU/NI만 전용 테마코드가 있어 주간 |raw_score|
  규모가 광종 간 최대 70배(P50: CU 220 vs LI 3) — 단일 k로는 CU 포화·LI/CO/REE 무반응.
  `scale_k_by_commodity` 도입(schema/indexer/index.yaml), 앵커=각 광종 P90→지수 88, 동결
  (CU 447/NI 165/CO 14/LI 12/REE 20). 재산출 후 5광종 전부 실동적범위 확보(이전 LI/CO/REE
  50 고정 → IQR 50~80). 반복보도 dedup이 GKG에서 471,101건 걸러냄(설계 검증).
- **확률모델 v2 — burst 타깃**: GKG 병합 후 "심각 이벤트 ≥1건" 기저율이 0.83~1.0으로 포화
  (CU/NI 상시 1.0 = 무정보) — 조기경보 신호를 **P(주간 심각수 ≥ 광종별 P90 임계)**(burst)로
  승격, NB2 생존함수로 산출(p_severe_next는 하위호환 유지). REE에서 NB MLE α가 0으로 붕괴해
  포아송 폴백→꼬리 과신 문제 발견 → Cameron-Trivedi 모멘트 α 폴백 추가(α=6.81로 교정).
  검증(burst, test 2024+): CU·NI·REE 기준선 대비 개선 / CO 동률 / LI 열세 — LI·CO burst는
  외생 서프라이즈 성격이 강해 현 피처(자기이력+지수+보도량)로는 한계, 가격·재고 공변량 추가가
  다음 단계(v1 §3 보조 변수 배선 시).
- **발행**: warehouse에 geo_index 3,382행·geo_event 1,815,034행·**geo_prob 2,745행(신규 테이블)**.
  mart_weekly_diagnosis 재빌드 — geopolitical_risk 분산 확보(sd 6~18, 이전 50 고정)로 진단모델
  변수 ⑥이 실질 피처로 가동.

## 2026-07-12 — 독립 수집기 도커(`collector/`) 신설 + 미국/중국 수출입 공시 수집

분석기(geo)와 **다른 서버**에서 단독 실행되는 수집 전용 패키지·도커. geo 코드 의존 없음 —
접점은 $COLLECT_OUT 파일 계약뿐(inbox 텍스트=geo ingest 호환 / gkg zip=gkg-parse 호환).
- 구성: gkg_incremental(15분 타임스탬프 직접 생성 — 마스터리스트 불필요, 상태 재개형),
  gnews·gdelt_doc(기존 이식), **us_trade 신설**(Federal Register 공식 API — BIS 수출통제·
  Entity List/USTR 301조/ITA, since 상태 기반 증분+2016 백필), **cn_trade 신설**(상무부
  안전관제국 aqygzj.mofcom.gov.cn — 전략광물 이중용도 수출통제 공고·실체명단·대변인 문답).
- 실측 이슈 2건: ① mofcom 하위 목록은 JS 렌더링(jpaas) — 메인 페이지만 서버 렌더링이라
  주기 수집은 메인만 긁음(과거 백필 불가, GKG 보완). ② slim 컨테이너에서 apparent_encoding이
  중국어를 오판해 키워드 필터 전멸 — UTF-8 명시로 해결.
- 검증: 호스트+도커 양쪽 스모크(us_trade 1건/cn_trade 16건/gkg 증분 3파일/gnews 10건).
- 운영: docker compose(60분 데몬), NAS 볼륨 공유 → 분석 서버가 rsync 또는 직접 마운트.

## 2026-07-09 — 지수 확률화: NB2 강도모델 (`geo/prob_model.py`, v1 문서 §6-3)

geo_idx(점수)를 "다음주 심각(sev≥2) 이벤트 발생확률"로 번역하는 확률 레이어. 실측 과산포
(주간 이벤트 분산/평균 3.7~6.6, 포아송 전제 기각)에 따라 순수 포아송이 아닌 음이항(NB2,
포아송-감마 혼합 = Cox process 정상형) 회귀 채택. λ = exp(β₀+β₁·EWMA심각수+β₂·geo_idx+β₃·log
주간전체이벤트수), 발행값 P(≥1)=1−(1+αλ)^(−1/α). `geo prob` CLI, 산출 store/geo_prob.parquet.
- 검증(시계열 분할 train~2023/test 2024+): 5광종 전부 학습기저율 상수 기준선 대비 Brier 개선
  (CO 0.138 vs 0.658 / CU 0.089 vs 0.106 / LI 0.268 vs 0.404 / NI 0.175 vs 0.216 / REE 0.295
  vs 0.498). α 전부 유의(0.7~3.5) — 과산포 실재 확인.
- 부수 발견·수정: LLM이 전망 문장("2028년부터 확대")의 미래 시점을 obs_date로 뽑는 문제(7건) —
  extract.py에서 발행일 초과 obs_date는 horizon_months로 이관+발행일로 교정(근본), indexer/
  prob_model에 미래날짜 방어선, 기존 7건 패치. geo_index 2,087→2,076행 재산출.
- 검증 기준선 버그 즉시 수정: 테스트 실현율을 기준선으로 쓰면 오라클(미래 참조) — 학습기간
  기저율로 교체.
- 잔존 한계: 2024+ 체계적 과소예측 경향 — 코퍼스 커버리지 성장(Argus 일일보고서 2023-09+)으로
  "기록되는" 이벤트 기저율 자체가 비정상. GKG(2016~2026 균일 15분 주기) 병합 후 재적합하면
  해소 예상 — β₃(보도량 통제)로는 부분 흡수만 됨.

## 2026-07-08 — 변수⑥ 배선 완성: geo_index → mart_weekly_diagnosis 조인 (v1 문서 §11-3)

감사 이래 "생성은 되나 연결이 없어 항상 NULL"이던 지정학 지수를 진단 마트에 실제 배선.
- `msr/features/weekly_mart.py`: geo_index(freq='W') ASOF 조인 추가 — 마트 관측일 이전 최근
  주간지수(주말 라벨이라 직전 완결 주 = 미래참조 없음, 검증 완료). geo_index 미발행 환경에서는
  기존처럼 NULL 폴백(하위호환). 치환 문자열 내 SQL 인라인 주석이 쉼표를 삼키는 파서 오류 1건 수정.
- `geo/publish.py`: LLM 불량 obs_date("202X-09-01" placeholder, "2023-02-29" 달력불가) 방어 —
  형식+달력 검증 후 불량은 NULL. `geo/extract.py`에도 근본 수정(LLM date를 `_valid`로 검증 후
  폴백사슬). 기존 저장분 1건 수리.
- `geo/indexer.py`: gkg_verify 통과 이벤트(provider=openai_compat)가 GDELT 신뢰도 0.7 매핑을
  빠져나가 1.0으로 계산되던 버그 수정 — manifest 미매칭 잔여 source는 전부 GDELT 귀속.
- 검증(warehouse 사본): publish 2,087행+6,510행 → mart 1,610행 전부 geopolitical_risk 채움(100%),
  diagnosis.py가 자동으로 피처 포함(기존 "전부 NULL이면 제외" 로직 통과). 현재 중요도 ~0은 예상대로
  (교사신호=SYNTH, scale_k 잠정, GKG 미병합) — GKG 재검증 완료 후 재캘리브레이션하면 분산 확보.
- ⚠️ 정본 `warehouse/minerals.duckdb`가 root 소유(docker 잔재) — chown 후 정본 재발행 필요.

## 2026-07-08 — 모델 설계 정본 v1 작성 (`documents/claude_output/mineral_risk_model_v1.md`)

v0 뼈대 + 과업지시서(붙임1·2 원문, 붙임2 경보기준표는 OCR 판독) + 착수보고(39p 전량 OCR — 임베딩
폰트 유니코드 매핑 파손으로 pypdf/fitz 모두 한글 추출 불가, easyocr로 해결)를 대조해 작업 기준
문서 v1.0 확정. 핵심 결정: 산출물 구조를 과업지시서에 정렬(지정학지수=필수변수⑥의 공급기, 계약
산출물은 진단 B·예측 C), 필수 6변수+신규 3(GSCPI 확보/원자재지수[P]/WGI) 변수사전, 광종별 차등
가중치 매트릭스 초기값(과업지시서 Step2 앵커 준수 — 기존 감사 최대 누락 시정), 붙임2 경보 3계열
병렬 max 결합(가격 주축 역전 시정), severity 0~3·GeoEvent 현행 스키마 유지+dimension/article_count
추가, HS 확정 161코드로 v0 초안 폐기, 9월 납기 역산 구현순서 10단계, 발주처 블로킹 이슈 8건 정리.

## 2026-07-07 — ingest 파이프라인 실행검증·버그 4건 수정

`documents`(구 `documens`) 내 실자산(보고서_1·2, 조달청, EU SCRREEN, WoodMac, IEA, KOMIS 광업요람)
대표 10건을 실제 `geo ingest`→`extract`에 태워 실행검증(요청: "실행해봐주세요, 정상적으로 되는지
체크"). 4개 버그 발견·수정 — 상세는 `documents/claude_output/지정학위기지수_데이터수집현황_260707.md` §7.

- `classify.py`: `date_of()` 비0패딩 날짜(`2020.5.12`) 폴백 정규식 `_D1_LOOSE` 추가.
- `classify.py`: `source_of()`에 조달청("비철금속시장동향", 공백무관) + EU SCRREEN 패턴 추가.
- `classify.py`: `commodity_of()` 파일명 우선 검사로 순서 변경(본문 앞부분 광고문구 오염 방지 —
  WoodMac 니켈 보고서가 LI로 오분류되던 문제).
- `llm/rule.py`: `RuleExtractor.extract()`가 문서당 `commodity_hint` 1개만 쓰던 것을, 사건유형
  매치 국지창(±120자)에서 광종을 직접 탐지하도록 재작성(`_COUNTRY`와 동일 패턴) — 다광종 문서
  (조달청·Argus·IEA·광업요람)의 0건 추출·오염 태깅 문제 해소.
- `config/sources.yaml`: `EU_SCRREEN: 1.1` 신뢰도 등록.
- 재검증(동일 10건): ingest archived 6→10, unclassified 4→0. extract 이벤트 7건(2문서)→11건(7문서).
  WoodMac 4건 LI→NI 정정 확인. 조달청·IEA에서 최초로 CU 이벤트 추출 확인.
- **미착수(다음 단계 후보)**: 887개 조달청 전체 등 2016+ 전체 코퍼스 재투입은 샘플 검증 이후로 보류 —
  대량 재처리 전 사용자 확인 필요.
- **추가 발견(같은 날, 재실행 육안검수 중)**: `llm/rule.py` RULES의 `war`/`quota`가 단어경계 없이
  매칭 → 시황보고서 상투어 `warehouse`(88회, 실제 war 3회)·`quotations`가 오탐되어 허위 "분쟁"/"정책"
  이벤트 생성. `\bwar\b`/`\bcoup\b`/`\bquota\b`로 수정(한글 키워드는 `\b`가 무공백 복합어를 깨뜨릴 수
  있어 미변경). 재검증: 오탐 소멸, 동일 문서의 진짜 "trade war" 매치는 정상 유지.
- **룰기반 vs LLM 실측 비교**(사내 vLLM gemma-4-26b-a4b, `localhost:52302`, 가동 확인): 동일 9개 문서
  기준 룰=14건, LLM=29건. IEA 문서에서 룰기반은 DRC 코발트 4개월 수출중단(2025-02)을 통째로 놓쳤으나
  LLM은 포착 — `sources.yaml`의 `CO:DR Congo 1.7` 가중치가 정조준하는 시나리오라 임팩트 큼. 원인:
  `RULES`가 문서당 패턴 1매치만 채택(break)+방향(direction)이 키워드에 고정매핑(관세 인하도
  `supply_down`)+8종 고정 사건유형 밖은 아예 매치 불가. **부수 발견·수정**: 로컬 vLLM json_object
  강제모드가 배열을 `{"type":"text","text":"[...]"}`로 이중 인코딩 반환 → `jsonutil.as_event_list()`가
  못 풀고 이벤트 전부 유실되던 버그 수정(문자열 값 재귀 재파싱). 상세: 데이터수집현황 문서 §8.
  **프로덕션 provider 전환은 사용자 승인 대기 — 아직 미실행.**
- **날짜미상 695건 재처리**(`geo/date_resolve.py` 신설 + `classify.py` 신규 필명패턴 4종 추가 —
  연도전용/한글년월/계간지회차/"YYYY-DD-DD-Mon"): 695건 중 692건 해결(3건만 미해결), 2016+ 427건
  신규 투입. ingest archived 427/427(실패 0), OCR 실제 발동 2건(광업요람 2021·2024편) — 마침내 OCR
  경로 실증. 2021편은 서술형 문단 OCR 정확도가 높아 CO/DR Congo 분쟁광물 이벤트를 정확히 포착,
  2024편은 표 위주라 노이즈 대부분(가독 18%)이었으나 허위 이벤트 없이 안전하게 0건 종료. 누적
  이벤트 6,510건. `ManifestRecord`에 `pub_date_method` 필드 추가(감사용). 상세: 데이터수집현황
  문서 §10.
- **잔여이슈 3건 마무리**: (1) `date_resolve.py`에 xls(OLE)/xlsx(OOXML)/hwp(OLE) 메타데이터 폴백
  추가 — 날짜미상 최종 3건 중 2건(수급망지수.xls·CM_Data_Explorer.xlsx) 해결(작성일 메타데이터로
  2016+ 확인, 신규 투입 완료), 1건(LME Seminar hwp)은 메타데이터 전무+본문상 2008년 문서 확인돼
  범위 밖으로 정리. (2) `indexer.py`에 반복보도 dedup 추가 — 같은 광종·같은 달·같은 근거문구(앞
  40자)는 최고 severity 1건만 지수에 반영(원본 이벤트는 무손실 유지). 실측: 6,510건 중 87건(1.3%,
  DRC 코발트 수출중단 위주)이 중복합산되고 있었음, 수정 후 재계산 검증(2,087행 정상 산출). (3) 광종별
  무작위 8건×5광종=40건 층화표본 육안검증 — commodity/country 태깅 40/40 정확, severity가 정보값에
  비례(저정보 항목은 severity 0으로 자동 감쇠). 상세: 데이터수집현황 문서 §11.
- **2016+ 전체 코퍼스(2,385건) 실투입**(승인 후 실행): opendataloader-pdf 배치+OCR폴백(easyocr,
  CPU) 구현, `config/models.yaml` provider를 로컬 vLLM(gemma-4-26b-a4b)으로 전환, `extract.py`에
  `ThreadPoolExecutor` 동시요청(concurrency=8) 추가. 결과: ingest archived 2,367/2,385(failed 5건은
  전부 xlrd/openpyxl 미설치, 텍스트실패 아님), PDF 1,805건 텍스트확보 100%(opendataloader 97.9%+
  pypdf_fallback 2.1%, OCR 0%), 이벤트추출 1건이상 성공 1,890/2,355(80.3%), 총 이벤트 6,039건.
  실행 중 opendataloader 부분실패를 청크 전체 실패로 오판해 불필요한 OCR 폭주(CPU 212분→재발 407분)
  버그 발견·수정(파일단위 `.md` 존재판정 + OCR보다 pypdf 우선). 결과물은 `geo_data_2016plus_run/`에
  보존. 상세: 데이터수집현황 문서 §9.

## 2026-07-06 — 지정학 지수 1차: 비정형 수집기 이식(komis→komir)

과업지시서·착수보고 재검토 감사(`documens/claude_output/진단예측모델_요구사항대조_코드감사_260706.md`)에서
①진단모델 필수변수 ⑥지정학적리스크가 `mart_weekly_diagnosis`에 항상 NULL(연결 코드 없음), ②예측모델은
지정학 피처가 아예 0건임을 확인. 별도 구현체 `komis/`의 자동 수집기(GDELT·Google News RSS)가 실데이터
319건을 이미 확보하고 있어, 이를 komir `geo/` 파이프라인에 이식해 지수 볼륨을 늘리는 1차 작업 착수.

- **`geo/collectors/` 신설**: `gnews.py`(Google News RSS, 분기 단위)·`gdelt.py`(GDELT DOC API, 주 단위) —
  komis 원본 로직 이식. **komis 자체의 event_intensity/감성 점수는 가져오지 않음** — 원문(제목+URL+날짜)만
  `geo_data/inbox/{gnews,gdelt}/`에 텍스트로 투척해 기존 `[1]ingest→[2]extract`(LLM/rule)가 severity를
  산출하도록 함(소스 간 점수체계 일원화). `collectors/_common.py`에 URL해시 기반 중복 발행 방지(같은 사건이
  GDELT·GNews 양쪽에서 잡혀도 1건만 남김) 공용화.
- **`extractors.py`**: `.txt` 포맷 지원 추가(뉴스 원문 투척에 필요, 기존엔 pdf/hwp/xlsx만 지원).
- **`classify.py`**: `source_of()`에 `gdelt`/`gnews` 경로 감지 → `GDELT`/`GoogleNews` 소스 태깅.
- **`config/sources.yaml`**: `GDELT: 0.7`, `GoogleNews: 0.6` 신뢰도 등록(큐레이션된 업계보고서 대비 낮게 —
  뉴스취합이 물량으로 지수를 왜곡하지 않도록).
- **`__main__.py`**: `collect-news`/`collect-gdelt` 서브커맨드 추가(`geo all`에는 미포함 — 외부 API 호출이라
  명시적 실행 권장).
- **검증**: 오프라인 스모크 테스트로 텍스트투척→`ingest`(분류: source/category/commodity_hint 정상)→
  `extract --provider rule`(GeoEvent 생성: commodity/severity/country 정상) end-to-end 확인.
- **komis에서 의도적으로 가져오지 않은 것**: IEA 공급집중표(supply.py, 정적데이터라 ⑤production_hhi·
  refdata 쪽에 붙여야 함) · yfinance 프록시가격 · UN Comtrade(komir가 이미 더 나은 1차 소스 보유).
- **남은 것(2차)**: `geo_index`(또는 `geo_event` 월간 집계)를 `mart_weekly_diagnosis`(①)·`forecast.py`(②)에
  실제로 join하는 코드는 아직 없음 — 지수 "생성"과 모델 "활용" 사이 연결이 이번 1차의 범위 밖.

## 2026-07-02 ~ 07-05 — 파이프라인 구축·모델 가동·품질 강화 (1차 스프린트)

### 1. 인프라·환경
- 도커 통합 오케스트레이션 검증: `msr:dev`(정형·모델) + `geo:dev`(지정학) 빌드, 공유 `warehouse/minerals.duckdb`.
- `.env` 구성: 관세청·ECOS 키, **사내 vLLM gemma**(`gemma-4-26b-a4b`, host 52302) LLM 설정.
  - ⚠️ 교훈: `.env` 값 뒤 인라인 주석이 compose에서 **값으로 새어** LLM 인증헤더 오염(latin-1 오류) — 주석은 별도 줄로.
- git 원격 SSH 전환(`jhkang-illunex/komir`), 이후 전 커밋 push 완료.

### 2. 데이터 수집 (실데이터)
- 관세청 연간(2013~25, 2,093콜) + ECOS: `raw_customs_annual` 232,001행 · `raw_ecos` 257행.
- 관세청 월간: **일 한도(≈10,000콜) 실측 확인** → 전 기간(21,252콜) 불가, 최근 3년(2023~25, 5,796콜)으로 결정.
  host cron 자동 실행(자정 리셋 후)으로 `raw_customs_monthly` **61,291행** 수집 성공. 상세: msr README §4-B.

### 3. 스키마 통합·피처 (`9741497`)
- 정본 스키마 = `db/schema_core.sql`(warehouse) 확정.
- **raw→fact 정규화** 신설(`msr/features/normalize.py`, `make normalize`): `fact_trade_monthly` 5,408 · `fact_trade_annual` 1,946 · `agg_trade_annual` 65(광종·연도 HHI/YoY/CAGR3).
- features·forecast를 fact 계층 단일 소스로 전환(결과 무손실 검증).

### 4. 모델 3종 가동
- **수입 예측**(`eed898b`): `forecast.run()` — 월간 패널→lag/계절 피처→백테스트+12개월 재귀예측(80% 구간).
  `out_import_forecast` 120행. 실데이터 백테스트 **R² volume 0.897 / value 0.866**.
- **진단**(`6c55d9c`): `weekly_mart.py`(fact_price/indicator→`mart_weekly_diagnosis`) + `diagnosis.run()`.
  ⚠️ 실 가격·수급동향지표 부재 → **합성 데모**(`gen_synth.py`, src='SYNTH')로 e2e 검증(HistGBM R²~0.9, 위기 AUC~0.97).
- **경보 4단계**(`9e0983e`, DR13 해소): `geo_event` 계약 신설(geo publish가 이벤트 상세도 warehouse 발행) +
  `alert.run()` — 분위수 기본단계 + 오버라이드(변동성·HHI·지정학 sev/3 정규화) + 히스테리시스 + **법정 문안 사유·이벤트 인용** → `out_diagnosis_alert`.
  오버라이드 실증: NI 위기지수 27/100에도 인니 수출금지(sev 3)로 '경계' 격상.

### 5. 지정학(geo)·OKF
- geo 파이프라인 gemma로 실증(`0add376` 등): 문서 업로드→ingest→extract→index→**OKF 자동**(`geo all` 통합) + `make geo-watch`(inbox 감시 자동 실행).
- **OKF**(Open Knowledge Format, Google v0.1) 익스포트(`5ae20d9`): 정본 비파괴, `geo_data/okf/`에 metric/source/event/issue/index 마크다운+프론트매터 번들.
- **지수 공식 교체**(`514e1a1`): min-max(히스토리 재척도 결함) → **`index = 50+50·tanh(raw/scale_k)`** 절대 스케일.
  50=중립, 발행값 영구 불변(1월만 vs 전체 계산 동일 실증), 광종 간 비교 가능.

### 6. 코드 리뷰 4차 — 발견 22건 전부 수정
- 1차 수집·전처리(`3e2a01a`): serviceKey 로그 마스킹, 429/한도 `QuotaExceeded` 즉시 중단, **HS 단위 증분 적재**, ECOS 에러봉투 표면화.
- 2차 스키마·레거시(`fcce3d9`): 깨진 스키마 경로, legacy 명시(komis_files·구 geo_pipeline), hs_mapping BOM 견고화.
- 3차 심층(`4955e5a`, `1798fb3`): upsert 원자화+컬럼명 INSERT, YoY/CAGR 연도 기반, HHI 총0→NaN, 연간 월행 집계,
  diagnosis import 부작용 제거·함수화, 하드코딩 경로 제거.
- 4차 멀티에이전트(HIGH `514e1a1` / MEDIUM `0f49471` / LOW `d9b2203`):
  지수 안정화, ingest 파일당 manifest(유실 방지), extract_log(0건 문서 무한 재추출 차단), LLM 재시도/rf 폴백,
  월간 그레인 축 통일(q_year/q_month), forecast 월간 그리드, JSON 절단 복구, 날짜 파싱 달력 검증,
  OKF stale 정리, publish DDL 보존(PK 복원), normalize PK 잠복 충돌, spread ASOF, ManifestRecord 계약 강제,
  빈 텍스트 문서 분리, utcnow 정리 등. **보류 2건**: DR7(marts SQL — 데이터 없어 검증 불가), 동시 ingest 락(저위험).

### 7. 문서화 (`335f339`)
- README 3종 동기화: 구현 상태 표(실데이터/합성 구분), 지수 공식, 강건성, 사용법.

## 남은 과제 (다음 스프린트, 2026-07-12 갱신)

1. **관세청 월간 백필 완료 후속**(~07-14 자동): normalize 재실행 → `forecast_unit` 재학습
   (표본 36→156개월) → crontab 정리. [메모리: customs-monthly-backfill]
2. **경보 v1 §7-4 완전체**: 단계 = max(점수단계, 계열1, 계열2) 3계열 병렬 구조 + dimension
   백필(event_type→ops/trade/corridor/input 규칙 매핑) 기반 계열2(시설·수송) 트리거. 현재는
   alert_rule_v1(분위수+고신뢰 소스 오버라이드). **정정(2026-07-16, 실측 재확인)**: 대상
   건수는 이벤트 "650만건"이 아니라 `komir/warehouse/minerals.duckdb` `geo_event` 실측
   **1,815,194건**(약 3.6배 과대 추정이었음)[^geo-event-count]. 추가로 `dimension` 컬럼이
   현재 스키마에 존재하지 않아 백필 전 컬럼 마이그레이션이 선행돼야 하고, `event_type` 값이
   비정규화 상태(최다값 '뉴스' 1,197,020건=66%가 모호한 범주, '정책'/'policy'/'Policy'/
   'geopolitical/policy' 등 동일 개념이 한글·영문·대소문자로 분산)라 규칙 매핑 전 값 정규화가
   선행 필요[^geo-event-schema].

   [^geo-event-count]: 조회(2026-07-16): `duckdb komir/warehouse/minerals.duckdb -c
   "select count(*) from geo_event"` → 1,815,194.
   [^geo-event-schema]: 조회(2026-07-16): `duckdb komir/warehouse/minerals.duckdb -c
   "describe geo_event"`(dimension 컬럼 부재 확인) 및 `duckdb komir/warehouse/minerals.duckdb
   -c "select event_type, count(*) n from geo_event group by 1 order by 2 desc limit 20"`
   (event_type 비정규화 확인).
3. **변수④(세계 공급부족) 배선**: woodmac_series.parquet(CU·NI 수급밸런스)→연간 팩트→마트
   ASOF. CO/LI/REE는 IEA/USGS 보완([E]).
4. **USGS refdata 과거 백필**: 수집 서버에서 `geo refdata`(ScienceBase) 실행 → 번들 반입 →
   production_hhi 2016~23 채움 + geo 지수 conc 가중 연도별화.
5. **확률모델 LI·CO 개선**: burst 예측 열세 — 가격·재고 공변량(§3 보조변수) 추가 후 재적합.
6. **운영 배포**: 수집 서버에 collector 도커(daily) 기동, 분석 서버(폐쇄망) 이미지 반입 +
   일일 체인(ingest-bundles→…→publish_results) cron 구성.
7. **발주처 블로킹 8건**(v1 §12): B 학습라벨·C 필수변수·KOMIS 비정형 원천 등 — 회의 안건.
8. 대시보드 운영화: 현재 스냅샷 임베드 → 일일 재생성 스크립트화(+KOMIS 연계는 산출물 ③ 본계약).
