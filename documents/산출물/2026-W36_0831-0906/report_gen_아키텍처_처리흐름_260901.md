# report_gen(요약보고서 생성 서비스) 아키텍처·처리흐름

> 2026-09-01 작성. `inhouse/services/report_gen/`의 현재(HEAD `575979a52`) 코드
> 기준 — 요청 처리 파이프라인 전체 흐름 문서다. 데이터 접근 계층(Postgres
> 스키마 구분·MCP 등)은 챗봇 쪽 이야기라 이 문서 범위가 아니다. 배포 구조는
> `documents/meta/CONTAINER_ARCHITECTURE.md` 참고.

## 1. 개요

`report_gen`은 KOMIS 5개 메뉴 계열(시장동향지표·수급동향지표·핵심광물지표
(광물종합지수)·핵심광물지도(3종)·광물자원가격(4종)·수입가격예측)에 대한
**분석요약(MD 보고서 텍스트)** 을 생성하는 FastAPI 서비스다. `/api/v1/analysis/*`
아래 **11개 page_id**를 지원한다:

`indicator_market` · `indicator_supply` · `indicator_composite` · `map_mineral` ·
`forecast_price` · `price_base_metals` · `price_minor_metals` · `price_iron_energy` ·
`price_other` · `map_korea`(수급지도-국내) · `map_global`(수급지도-해외)

각 요청은 **결정론적 계산**(코드가 원자료로부터 근거·수치를 직접 산출)과
**LLM 정제**(그 근거를 자연어 문장으로 다듬되, 근거 밖 서술은 검증에서 걸러짐)
두 단계를 거쳐 Markdown으로 렌더링된다. 이 서비스는 자체 DB를 조회하지 않는다
— "prompt/template를 제외하고는 DB에서 값을 로딩하지 않는다"는 설계 원칙에
따라 계산에 쓰는 원자료(observations, 또는 KOMIS AJAX 원본 JSON)는 **요청
바디로 받는다**(주 호출자는 `streamlit_demo`).

## 2. 요청 처리 파이프라인

```
Client(streamlit_demo)
  → FastAPI Router(routers/analysis.py, 11개 엔드포인트)
  → run_summary(routers/_common.py) — 요청조립 + Semaphore(8) lock + 20초 예산
  → AnalysisSummaryService._dispatch(analysis/summary.py) — page_id별 분기
  → 데이터 소스 선택(요청 바디: observations 또는 komis_*_response 원본 JSON)
  → calculate_*_summary(analysis/komir_summary.py) — 결정론적 EvidenceClaim 생성
  → _refine_with_llm(summary.py) — ai_cfg.cfg_prompt 지시문으로 LLM 정제 + 검증
  → render_markdown_report(analysis/report_render.py) — MD 렌더링
  → AnalysisReportResponse({status, report})
```

### 2-1. 진입 — `routers/analysis.py`

11개 엔드포인트(`POST /api/v1/analysis/indicators/market` 등, 2026-09-03
"광물전망지표"(`indicators/`)·"핵심광물지도"(`maps/`) 그룹으로 재편 — 이전엔
`market-indicator`처럼 평면 경로였다)는 각각 page_id
전용 Pydantic 요청 모델(`IndicatorSummaryRequest`·`PriceSummaryRequest`·
`DomesticTradeSummaryRequest`·`GlobalTradeSummaryRequest` 등, `analysis/models.py`)
로 바디를 받아 `run_summary(page_id, payload, request)` 한 줄만 호출한다 — 계산
로직은 전혀 갖지 않는다.

⚠ 과거엔 `/api/v1/{prices,indicators,maps}/...` REST 명명규칙 별칭 라우터
(`routers/report_data.py`)가 같은 서비스를 재사용하며 병존했으나, **2026-08-31
실제 호출자가 코드베이스 전체에 하나도 없음을 grep으로 확인해 제거**했다
(`routers/report_data.py` 파일 자체 삭제, `main.py`도 더 이상 import하지 않음).
현재는 `/api/v1/analysis/*` 11종이 유일한 분석요약 경로다. (`main.py` 최상단
모듈 docstring은 이 REST 별칭 계열을 아직 기술하고 있어 코드 상태와 어긋난다
— 문서 갱신이 필요한 낡은 주석으로 확인됨, 이번 작업 범위 밖이라 코드는
건드리지 않았다.)

### 2-2. 공통 실행기 — `routers/_common.py::run_summary`

1. `AnalysisSummaryRequest(page_id=page_id, **payload.model_dump())`로 요청을
   조립한다 — 페이지 전용 필드 불일치로 `ValidationError`가 나면 라우트 밖으로
   새지 않고 `status="NO_DATA"`로 흡수한다(2026-08-27 skeptic 감사 SC-001 수정).
2. `deadline = now + 20초`(`REQUEST_BUDGET_SECONDS`)를 잡고, 8-스레드 풀
   (`_EXECUTOR`, 11종 엔드포인트 공유)에 작업을 제출한다.
3. 작업 본문은 `request.app.state.analysis_lock`(**Semaphore(8)**, 부하테스트로
   확인한 안정적 동시성 상한 — 2026-08-28 이전엔 `Lock()`으로 완전 직렬화였다)을
   남은 예산 안에서 `acquire(timeout=)`한다. 못 잡으면 즉시 포기.
4. lock을 잡았어도 (LLM이 배선된 서비스이고) 남은 예산이 LLM 호출 1회 상한
   (`ANALYSIS_LLM_TIMEOUT_SECONDS`)보다 짧으면 애초에 `service.analyze()`를
   부르지 않고 포기한다 — "아무도 안 읽는 LLM 호출이 lock을 예산 너머까지
   쥐는" zombie를 막는 안전장치(2026-08-27 skeptic 감사 Pass 3 실측).
5. **HTTP 상태 코드는 이 11종 전부 항상 200**이다. 성공/실패는 응답 바디의
   `status` 하나로만 구분한다: `"ok"`(report 포함) · `"NO_DATA"`(원자료 부족/
   요청 스키마 위반) · `"TIMEOUT"`(20초 초과 또는 lock 획득 실패) ·
   `"INTERNAL_ERROR"`(그 외 예외, 상세는 서버 로그에만). 요청 스키마 자체가
   깨진 경우(`RequestValidationError`, 예: 알 수 없는 필드)도 `main.py`의
   전역 예외 핸들러가 `/api/v1/analysis/` 경로에 한해 FastAPI 기본 422 대신
   200+`NO_DATA`로 바꿔치기한다(2026-08-27 Pass 3에서 발견한 계약 간극의
   수정) — 이 "항상 200" 계약은 `/api/v1/analysis/*`에만 적용되고,
   `/reports/*`·`/api/v1/dashboard/*`는 FastAPI 표준 상태코드를 그대로 쓴다.

### 2-3. 페이지 분기 — `analysis/summary.py::AnalysisSummaryService._dispatch`

```python
if page_id == "indicator_composite": _analyze_composite()
if page_id == "map_mineral":         _analyze_mineral_map()
if page_id == "forecast_price":      _analyze_price_forecast()
if page_id in (price_base_metals, price_minor_metals,
               price_iron_energy, price_other): _analyze_price()
if page_id == "map_korea":           _analyze_domestic_trade()
if page_id == "map_global":          _analyze_global_trade()
else:                                 _analyze_indicator()   # market/supply
```

각 `_analyze_*`는 (a) 원자료를 요청 바디에서 읽고 (b) `calculate_*_summary`류
결정론적 함수를 호출해 `EvidenceClaim` 목록을 만든 뒤 (c) `_refine_with_llm`으로
넘긴다.

### 2-4. 데이터 소스 — 요청 바디 2가지 형태

DB 조회 코드(`analysis/data_sources`)는 **2026-08-26에 호출부만 주석 처리**
(파일은 보존, 복원 가능)하고 요청 바디 입력으로 전환됐다. 요청 바디는 두 형태
중 하나(또는 병행)를 받는다:

1. **가공된 observations** — `IndicatorObservation` 등 komir 자체 스키마 배열.
2. **KOMIS AJAX 원본 JSON passthrough**(`komis_response`/`komis_snapshot_response`/
   `komis_share_response`/`komis_bar_chart_response`/`komis_route_share_response`
   등, page_id별로 다름) — `summary.py`의 `_parse_komis_*_response` 계열
   함수(예: `_parse_komis_price_response`·`_parse_komis_map_korea_response`·
   `_parse_komis_map_mineral_snapshot_response`)가 KOMIS 사이트의 실제 AJAX
   응답 모양을 그대로 받아 내부 스키마로 변환한다. 클라이언트(streamlit_demo)가
   KOMIS 응답을 손으로 매핑하지 않고 그대로 전달할 수 있게 하는 passthrough
   패턴으로, map_korea/map_global/map_mineral/price 계열 전부에 걸쳐 있다.

### 2-5. 결정론적 근거 계산 — `analysis/komir_summary.py`

`calculate_domestic_trade_summary`·`calculate_global_trade_summary`·
`calculate_mineral_map_summary` 등이 원자료로부터 `_EvidenceClaim`(section·fact·
evidence_id·required 여부)을 직접 산출한다 — 이 단계는 LLM을 쓰지 않고, 숫자·
사실 판단은 전부 여기서 확정된다. LLM은 이 근거를 "문장으로 다듬을 뿐" 새로운
사실을 만들지 않는다(§2-6의 검증이 이를 강제).

### 2-6. LLM 정제 — `_refine_with_llm`(summary.py)

1. **용량 사전 검사**: 근거 개수(demand)가 출력 계약의 최대 수용량(capacity =
   Σ절 문장상한 × 문장당 근거상한)을 넘으면 LLM을 아예 호출하지 않고 바로
   경고 첨부 후 규칙기반으로 반환한다(Pass 3 R3-F2 — 산술적으로 불가능한
   요청으로 LLM을 헛되이 부르지 않음).
2. **예산 확인**: 남은 요청 예산이 LLM 1회 호출 상한보다 짧으면 호출을
   건너뛴다(R3-F1).
3. **최대 2회 시도**: `KomirJsonLLM.invoke(task="analysis_summary", instructions=
   summary_instructions(page_id), payload=..., output_model=SummaryNarrative)`를
   호출 → `_validate_llm_summary()`로 "인용한 evidence_id가 실제로 존재하는가"
   등을 검증 → 실패하면 검증 오류를 다음 시도의 프롬프트에 실어 재시도.
4. **예외 처리**: `LLMError`/`RuntimeError`/`OSError`(전송 실패·vLLM 다운 등)를
   전부 잡아 규칙기반 폴백으로 떨어진다 — 외부repo 원본은 `LLMError`만 잡았는데
   komir의 `KomirJsonLLM`은 전송 오류를 그대로 올리는 계층이 하나 더 있어
   같이 잡지 않으면 vLLM 장애 시 500이 났다(이력 있는 의도적 확장).
5. 2회 모두 실패하면 검증 사유를 `data_quality.warnings`에 담아 규칙기반
   응답을 반환한다 — **이 경고는 응답 본문(Markdown)에는 안 나간다**(§2-7).

### 2-7. 렌더링 — `analysis/report_render.py::render_markdown_report`

검증된 `AnalysisSummaryResponse`(구조화 JSON, LLM 정제본이든 규칙기반이든)를
Markdown으로 조립한다:
- 제목(`# {mineral} 분석 요약 — {page_definition}`, 정의문 어미를 존댓말로 변환)
- 절 3개(핵심 진단·주요 변화·현재 위치) — `current_position`이 3문장 초과면
  문단이 아니라 불릿 목록으로 렌더링(2026-08-31, 통계확장으로 최대 9문장까지
  늘어난 뒤 가독성 문제 수정)
- 주요 지표 표(단위가 `"ratio"`면 0.0356 대신 3.56%로 변환 — 본문 서술과
  단위를 맞추기 위한 조치)
- `data_quality.warnings`(LLM 검증 실패 사유, 데이터 결측 등)는 **응답 텍스트에서
  뺀다** — 대신 매 요청마다 서버 로그에 남긴다(`llm_refined` 여부 포함,
  2026-08-28 SC-018: 공개 응답 계약에 `llm_refined` 필드가 없어 클라이언트가
  정제/폴백 여부를 구분 못 하는 문제를 로그 레벨에서 보강).

## 3. 프롬프트/DB 계약 — `ai_cfg.cfg_prompt`

- 프롬프트 본문은 `prompts.py::PROMPTS`가, 페이지 정책(이름·정의·작성제약·
  `policy_version`)과 출력 계약(`SECTION_SENTENCE_RANGES` 등)은
  `prompts.py::code_page_config()`가 **코드 상수**로 소유한다.
- `python -m app.analysis.seed_prompts`(cwd=`inhouse/services/report_gen`)가
  이 코드 상수를 `ai_cfg.cfg_prompt`(PostgreSQL, 스키마는 `mineral_risk`/
  `public`과 별개인 `ai_cfg` 전용)에 `ON CONFLICT (prompt_key) DO UPDATE`로
  멱등 upsert한다. **코드 상수를 바꾼 뒤엔 반드시 재실행해야 DB에 반영된다**
  — 컨테이너를 재빌드·재기동해도 이 시딩 스크립트를 따로 돌리지 않으면
  `resolve_page_config()`가 여전히 옛 DB 행을 읽는다(2026-09-01 SC-RG-001
  적용 시에도 이 순서를 지켰다: 코드 수정 → 컨테이너 재빌드 → `seed_prompts`
  재실행 → `/admin/prompts/reload`).
- 런타임에는 `resolve_page_config(page_id)`가 DB 행(`output_contract` 등)이
  있으면 코드 기본값을 오버라이드한다 — DB 값이 깨져 있으면(JSON 형식 오류 등)
  경고 로그를 남기고 코드 기본값으로 안전하게 되돌아간다.
- `POST /admin/prompts/reload`는 서버 재시동 없이 `ai_cfg.cfg_prompt` 캐시를
  다시 읽는다 — DB 행을 손으로 UPDATE했거나 `seed_prompts`를 재실행한 뒤
  다음 요청부터 바로 반영하고 싶을 때 호출한다.

## 4. 안전장치

| 장치 | 위치 | 목적 |
|---|---|---|
| `Semaphore(8)` + `acquire(timeout=)` | `routers/_common.py` | 느린 LLM 호출 1건이 lock을 독점해 나머지 요청까지 연쇄 TIMEOUT 나는 것 방지(2026-08-27 SC-002, 2026-08-28 8-동시성으로 완화) |
| deadline 공유 + zombie 포기 | 〃 | 이미 클라이언트가 TIMEOUT을 받은 뒤에도 아무도 안 읽는 LLM 호출이 lock을 쥐는 것 방지 |
| `ValidationError`/`RequestValidationError` → `NO_DATA` | `routers/_common.py`+`main.py` | 요청 스키마 불일치가 500/422 평문으로 새지 않고 "항상 200" 계약을 지킴 |
| `except Exception → INTERNAL_ERROR`(상세는 `logging.exception`만) | `routers/_common.py`, 그리고 2026-09-01부터 `main.py::generate()`(레거시 `/reports/{template}/generate`)도 동일 계약 | 클라이언트에 원시 예외 문자열(스택트레이스 등 내부 정보) 노출 방지 — 오늘(SC-RG-002) `main.py`의 레거시 엔드포인트가 유일하게 `str(exc)`를 그대로 노출하던 것을 통일 |
| `_refine_with_llm`의 용량 사전검사 + 2회 재시도 + LLM 예외 포착 | `summary.py` | 근거 검증 실패·LLM 장애 시 항상 검증된 규칙기반 응답으로 안전하게 낙하 |

## 5. 알려진 설계 결정(현재도 유효)

- **`price_group` 외부 인터페이스 제거**(2026-08-31, `de2bd6336`): 사용자
  피드백으로 `/api/v1/analysis/price-group` 엔드포인트를 없앴다 — 내부
  `_analyze_price_group` 코드 자체는 `_dispatch`에 분기가 남아 있으나(보존
  원칙), 외부에서 도달할 라우트가 없어 사실상 죽은 진입점이다.
- **광물자원가격 통계 확장 6+2층**(2026-08-28, `c6f763f2b`): `price_*` 4개
  page_id에 변동성·MA+RSI·백분위·낙폭국면·재고해석·상대가치(6개) +
  연도별수익률표·계절성(2개)을 추가 — `current_position` 절이 최대 9문장까지
  늘어난 계기이자, §2-7의 목록 렌더링 분기가 생긴 이유.
- **`komis_*_response` passthrough 패턴**(2026-08-30~31): map_korea·map_global·
  map_mineral·price 4계열 전부, 클라이언트가 KOMIS AJAX 원본을 그대로 보내고
  서버가 파싱하는 구조로 통일 — 손 매핑(사람이 필드를 일일이 옮겨적는 방식)을
  없애는 게 목적이었다(챗봇 쪽 `komis_raw_lookup` 신설과 같은 날 배경 문제
  의식 — "이미 있는 원천 데이터 재발명 금지").
- **DB 조회 비활성화는 삭제가 아니라 주석 처리**(2026-08-26): 요청 바디 입력
  전환 원칙에 따라 기존 DB 조회 호출부는 지우지 않고 주석으로 남겨 복원
  가능하게 유지한다 — `summary.py` 곳곳의 `# if self._data_source is None: ...`
  블록이 그 흔적이다.

## 부록. 이번 조사 중 발견한 범위 밖 사항

`main.py` 최상단 모듈 docstring이 2026-08-31에 제거된
`/api/v1/{prices,indicators,maps}/...` REST 별칭 라우터(`routers/report_data.py`)를
여전히 기술하고 있어 코드 상태와 어긋난다 — 문서 갱신이 필요하지만 이번
작업(문서 작성) 범위 밖이라 코드는 건드리지 않았다. 후속 과제로 남긴다.
