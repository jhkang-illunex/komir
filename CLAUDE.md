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

## 1. 저장소 구조 (2026-07-22 기준, 실제 상태)
```
komir/
├─ geo/                  # 지정학 위기지수 파이프라인(비정형: GKG·뉴스·공시 → LLM 추출 → 지수)
│  ├─ gkg_parse.py gkg_verify.py gkg_relevance.py gkg_relevance_llm*.py   # GKG 관련성 정제
│  ├─ ingest.py extract.py index.py prob_model.py publish.py schema.py
│  └─ llm/{base,openai_compat,llm_extractor,jsonutil}.py  # provider 무관 LLM 어댑터
├─ mineral_supply_risk/  # 정형 파이프라인(관세청·ECOS·KOMIS·가격) + 진단/예측 모델
│  ├─ msr/{collectors,features,models,storage}/
│  └─ scripts/           # 백필·백테스트·검증·A-5·GKG정제 등 실행 스크립트 다수
├─ warehouse/minerals.duckdb   # ★ canonical 운영 DB(gitignore, 로컬 전용 — geo_event·geo_index·
│                                geo_prob·fact_*·mart_*·out_* 등 전 테이블)
├─ geo_data/              # geo 파이프라인 정본 store(parquet, gitignore) — inbox/archive/store
├─ docs/{WORKLOG.md, DATA_REGISTRY.md, DB_SCHEMA.md}  # ★ 작업이력·산출물색인·DB스키마 정본
├─ documents/              # 2026-07-22 mine_ws 최상위에서 이관
│  ├─ 산출물/<주차>/        # 우리가 작성한 보고서·분석 산출물 — git 추적됨. 주차 폴더명은
│  │                          ISO 주차 기준(예: 2026-W30_0720-0726). 구 claude_output/도
│  │                          같은 날 이 구조로 재편됨(git rename, 이력 보존)
│  └─ (그 외)               # KOMIS·WoodMac·Argus·USGS·EU SCRREEN 등 제3자 원본자료(35GB) —
│                             git 미추적(.gitignore), 로컬 전용
├─ data_archive/           # 검증 실행 로그·백업(삭제 금지 정책, artifact-provenance-policy 참고)
└─ dashboards/              # 웹 대시보드
```
- `mine_ws/komis/`(별도 프로젝트, 무관)·`documents/dev/`(komir의 훨씬 오래된 폐기 스냅샷)는
  이 저장소와 무관 — 참고 금지.
- `README.md`·`documents/CLAUDE.md`는 2026-07-02 초기 프로토타입 상태 스냅샷이라 **상당수
  내용이 낡음**(당시 "합성 데모"였던 진단모델이 지금은 실데이터로 QWK 0.97대 운영 중 등) —
  현재 상태는 이 파일과 WORKLOG/DATA_REGISTRY를 신뢰할 것.

## 2. 실행 방법(현재 실제로 쓰는 방식 — README의 docker-compose `make` 흐름과 다를 수 있음)
```bash
# geo 파이프라인
cd komir && python -m geo gkg-parse --bulk-root <path>   # GKG 벌크 파싱
python -m geo gkg-verify --bulk-root <path>               # LLM 재검증
python -m geo index && python -m geo prob                 # 지수·확률 산출
python -m geo publish --db warehouse/minerals.duckdb --what all

# 정형/진단/예측 (mineral_supply_risk/)
cd mineral_supply_risk
MSR_DB=../warehouse/minerals.duckdb python -m scripts.diagnosis_retrain_answer
MSR_DB=../warehouse/minerals.duckdb python -m scripts.<기타 스크립트>
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
