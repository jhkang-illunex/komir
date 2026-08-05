# CLAUDE.md — 핵심광물 수급위기 진단·수요예측 시스템

> Claude Code가 이 파일을 세션 시작 시 자동 로드합니다. 2026-07-22부터 세션은 이 저장소
> (`komir/`)에서 직접 띄웁니다 — 상위 `mine_ws/`가 아닙니다.
> 상세 이력은 이 파일이 아니라 `docs/WORKLOG.md`(날짜별 변경·버그·결정, 최신이 위)와
> `docs/DATA_REGISTRY.md`(산출물 색인)가 정본입니다. 자동 로드되는 메모리 시스템에도
> 그동안의 작업·사용자 선호·프로젝트 맥락이 정리되어 있으니 먼저 확인할 것.

## 0. 과업 개요
- **발주**: 광해광업공단/KOMIS. AI 기반 핵심광물 수급위기 진단·수요예측.
- **대상 5광종**: CU(동)·NI(니켈)·CO(코발트)·LI(리튬)·REE(희토류, 대표원소 **네오디뮴 Nd 확정**).
- **납기**: 2026년 9월 중순.
- **산출물**: ①수급위기 진단모델(4단계 경보) ②12개월 수입물량·수입액 예측 ③지정학 위기지수
  ④모니터링 대시보드 ⑤운영 DB 발행. 전 구간 실데이터로 무인 가동 중(주간/월간 cron 체인).

## 1. 저장소 구조 (2026-08-05 기준, 실제 상태 — 같은 날 `engine/` 편입 반영)
```
komir/
├─ engine/                # 배치·분석 코어(2026-08-05 신설 — geo/mineral_supply_risk/rag를
│  │                         이 아래로 편입, 서빙 레이어(services/)와 물리적으로 분리)
│  ├─ geo/                # 지정학 위기지수 파이프라인(비정형: GKG·뉴스·공시 → LLM 추출 → 지수)
│  │  ├─ gkg_parse.py gkg_verify.py gkg_relevance.py gkg_relevance_llm*.py  # GKG 관련성 정제
│  │  ├─ ingest.py extract.py index.py prob_model.py publish.py schema.py
│  │  └─ llm/{base,openai_compat,llm_extractor,jsonutil}.py  # provider 무관 LLM 어댑터
│  ├─ mineral_supply_risk/  # 정형 파이프라인(관세청·ECOS·KOMIS·가격) + 진단/예측 모델
│  │  ├─ msr/{collectors,features,models,storage}/
│  │  └─ scripts/         # 백필·백테스트·검증·A-5·GKG정제 등 실행 스크립트 다수
│  └─ rag/                # 문서 기반 RAG(하이브리드 BM25+dense, 2026-08-05 1차 구현)
│     └─ ragkit/{ingest,chunk,tokenize_ko,embed,retrieve,generate,build_index,eval_retrieval}.py
├─ services/               # 서빙 레이어(2026-08-05 설계, 스켈레톤뿐 — 구현 전)
│  └─ {shared,commodity_api,rag_chat,report_gen,ingestion}/  # docs/CONTAINER_ARCHITECTURE.md
├─ deploy/                 # 컨테이너화·airgap 배포(설계 단계, docs/CONTAINER_ARCHITECTURE.md)
├─ warehouse/minerals.duckdb   # ★ canonical 운영 DB(gitignore, 로컬 전용 — geo_event·geo_index·
│                                geo_prob·fact_*·mart_*·out_* 등 전 테이블. engine/ 편입과
│                                무관하게 루트에 그대로 유지)
├─ geo_data/              # geo 파이프라인 정본 store(parquet, gitignore) — inbox/archive/store
├─ docs/{WORKLOG.md, DATA_REGISTRY.md, DB_SCHEMA.md, CONTAINER_ARCHITECTURE.md}  # ★ 정본
├─ documents/              # 2026-07-22 mine_ws 최상위에서 이관
│  ├─ 산출물/<주차>/        # 우리가 작성한 보고서·분석 산출물 — git 추적됨. 주차 폴더명은
│  │                          ISO 주차 기준(예: 2026-W30_0720-0726). 구 claude_output/도
│  │                          같은 날 이 구조로 재편됨(git rename, 이력 보존)
│  └─ (그 외)               # KOMIS·WoodMac·Argus·USGS·EU SCRREEN 등 제3자 원본자료(35GB) —
│                             git 미추적(.gitignore), 로컬 전용
├─ data_archive/           # 검증 실행 로그·백업(삭제 금지 정책, artifact-provenance-policy 참고)
└─ dashboards/              # 웹 대시보드(streamlit_app.py — 모델 재현·설명가능성 데모)
```
- `mine_ws/komis/`(별도 프로젝트, 무관)·`documents/dev/`(komir의 훨씬 오래된 폐기 스냅샷)는
  이 저장소와 무관 — 참고 금지.
- `README.md`·`documents/CLAUDE.md`는 2026-07-02 초기 프로토타입 상태 스냅샷이라 **상당수
  내용이 낡음**(당시 "합성 데모"였던 진단모델이 지금은 실데이터로 QWK 0.97대 운영 중 등) —
  현재 상태는 이 파일과 WORKLOG/DATA_REGISTRY를 신뢰할 것.
- **경로 이관 주의(2026-08-05)**: `geo/`·`mineral_supply_risk/`가 `engine/geo/`·
  `engine/mineral_supply_risk/`로 이동했다 — 과거 WORKLOG·DATA_REGISTRY 항목의 구 경로
  표기는 **그 시점 기록이라 갱신하지 않았음**(당시엔 그 경로가 맞았음), 실제로 명령을
  재현할 땐 아래 §2의 새 경로를 쓸 것.

## 2. 실행 방법(현재 실제로 쓰는 방식 — README의 docker-compose `make` 흐름과 다를 수 있음)
```bash
# geo 파이프라인 — python -m geo는 geo 패키지의 "부모"에서 실행해야 함(cwd=engine/,
# engine/geo 안이 아님 — 실측 확인됨, 2026-08-05 이관 전엔 cwd=komir/였던 것과 동일 원리)
cd komir/engine && python -m geo gkg-parse --bulk-root <path>   # GKG 벌크 파싱
python -m geo gkg-verify --bulk-root <path>               # LLM 재검증
python -m geo index && python -m geo prob                 # 지수·확률 산출
python -m geo publish --db ../warehouse/minerals.duckdb --what all

# 정형/진단/예측 (engine/mineral_supply_risk/) — 여긴 python -m scripts.xxx라 패키지
# 자신의 디렉토리에서 실행(이관 전과 동일 방식, cwd만 한 단 깊어짐)
cd komir/engine/mineral_supply_risk
MSR_DB=../../warehouse/minerals.duckdb python -m scripts.diagnosis_retrain_answer
MSR_DB=../../warehouse/minerals.duckdb python -m scripts.<기타 스크립트>
```
LLM: 로컬 vLLM(`LLM_PROVIDER=openai_compat`, `.env`에 `LLM_BASE_URL`·`LLM_MODEL`). `.env` 값
줄에는 절대 인라인 주석 달지 말 것(env_file 파서가 주석을 값으로 흡수하는 함정 — 메모리
`env-inline-comment-gotcha` 참고).

## 3. 세션 시작 시 권장 순서
1. 이 파일로 방향 파악.
2. 메모리 시스템 확인(자동 로드) — 특히 `next-tasks-komir`(잔여 작업)·`gkg_relevance_redesign_260720`
   (GKG 관련 작업 전 필수 확인, 재발명 방지)·`data-quantity-verification-rule`(수량은 항상 직접
   쿼리로 재확인, 문서값 재인용 금지).
3. `docs/WORKLOG.md` 최상단 최근 항목 확인.
4. 발주처 보고 문서는 `documents/산출물/<주차>/`의 최신 날짜 버전이 정본(예:
   `documents/산출물/2026-W30_0720-0726/핵심광물_시스템구성_요약본_260722.docx`) —
   DATA_REGISTRY.md "관련 문서" 절에 정본/구버전
   구분이 명시되어 있음.

## 4. 코드/실험 작업 원칙 — 구조가 모델을 앞선다
지난 한 주간 신규 피처·데이터 후보 20여 건을 검정했지만 채택은 1건(아르헨 LI)뿐이었다.
새 모델·피처를 추가하는 것보다 아래 구조적 규율을 지키는 쪽이 실제로 결과를 좌우했다.
- **신규 피처·모델 후보는 항상 `r10_retune_harness.py`(SERIES_SPEC 등록형)로 검정** —
  스크리닝→부트스트랩→예측exog 전 단계를 통과해야 "채택". 임의 채택 금지.
- **기존 상태를 먼저 확인**: 새 지표/시리즈 이름을 짓기 전 `fact_indicator`·
  SERIES_SPEC에 동일 이름이 있는지 반드시 조회(PK에 src가 없어 이름 충돌=조용한
  덮어쓰기 위험 — 2026-07-29~30 이틀 연속 실제 발생, WORKLOG 참고).
- **최소·외과적 변경**: 이미 검증된 공유 코드(예: tier1/3/4가 공유하는
  `_comtrade_fetch()`)는 회귀 재검정 계획 없이 건드리지 않는다 — 급해도 별도
  사이클로 분리.
- **검증 가능한 성공 기준**: "개선해줘" 대신 QWK/FAR/WAPE 등 구체 지표+기준선
  대비 임계값으로 성공을 정의한다(채택 기준은 스코어보드·WORKLOG 참조).
- **재시도 금지 목록 준수**: `챔피언_스코어보드_*.md`·메모리에 실패로 기록된
  방향(예: NI unit 모델 교체 4종, GACC headless 5종)은 재시도하지 않는다.
