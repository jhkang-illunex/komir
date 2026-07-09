# 작업 이력 (WORKLOG)

> 커밋 해시는 `git log --oneline` 기준. 최신이 위.

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

## 남은 과제 (다음 스프린트)
1. **실 데이터 투입** — 진단·경보 실운영 전환의 유일한 블로커:
   - KOMIS xlsx(가격·수급동향지표) 입수 시 `collect-komis` 어댑터 작성(파서는 `komis_files.py`에 있음 — warehouse 계약으로 브릿지 필요) + `SYNTH` 행 삭제 후 재학습.
   - 실 지정학 문서는 `geo_data/inbox`에 넣으면 즉시 자동(파일명에 날짜 필수).
   - USGS(→`production_hhi`)·관세청 전기간(운영계정 트래픽 상향 신청) 병행.
2. 보류 리뷰 2건(DR7·ingest 락)은 canonical 데이터/동시 실행 요구 발생 시 처리.
3. (선택) OKF-정본 승격 실험, geo-watch 상시화(systemd).
