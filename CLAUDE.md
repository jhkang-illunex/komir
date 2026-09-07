# CLAUDE.md — 핵심광물 수급위기 진단·수요예측 시스템

> **Always respond in Korean (한국어로 답변할 것, 코드나 입력된 텍스트가 아닌한).**

> Claude Code가 이 파일을 세션 시작 시 자동 로드합니다. 2026-07-22부터 세션은 이 저장소
> (`komir/`)에서 직접 띄웁니다 — 상위 `mine_ws/`가 아닙니다.
> 상세 이력은 이 파일이 아니라 `documents/meta/WORKLOG.md`(날짜별 변경·버그·결정, 최신이 위)와
> `documents/meta/DATA_REGISTRY.md`(산출물 색인)가 정본입니다. 자동 로드되는 메모리 시스템에도
> 그동안의 작업·사용자 선호·프로젝트 맥락이 정리되어 있으니 먼저 확인할 것.
>
> **2026-08-06 DMZ/inhouse 물리 분리**: 저장소를 배포 단위 두 개로 재구성했다 — 외부망과
> 닿는 `dmz/`(수집기만, LLM 없음)와 airgap `inhouse/`(지수·진단·예측·RAG·서빙). 계기는
> 적대적 감사에서 나온 지적으로, `engine/geo`·`engine/mineral_supply_risk` 안에 수집기
> (collectors) 코드가 분석/모델 코드와 같은 패키지에 물려 있어 airgap 컨테이너가 수집기의
> 외부망 의존성(HTTP 클라이언트 등)까지 직접 import하는 구조였던 문제 — 이번 재구성으로
> 수집기를 `dmz/geo_collectors/`·`dmz/msr_collectors/`로 물리 분리해 inhouse 쪽엔 수집기
> 코드 자체가 존재하지 않게 만들었다. 상세는 §1 하단 "경로 이관 주의" 및
> `documents/산출물/2026-W32_0803-0809/목표아키텍처_DMZ_inhouse_흐름_260806.md` 참고.

## 0. 과업 개요
- **발주**: 광해광업공단/KOMIS. AI 기반 핵심광물 수급위기 진단·수요예측.
- **대상 5광종**: CU(동)·NI(니켈)·CO(코발트)·LI(리튬)·REE(희토류, 대표원소 **네오디뮴 Nd 확정**).
- **납기**: 2026년 9월 중순.
- **산출물**: ①수급위기 진단모델(4단계 경보) ②12개월 수입물량·수입액 예측 ③지정학 위기지수
  ④모니터링 대시보드 ⑤운영 DB 발행. ⚠2026-09-07부터 진단·예측·지수 파이프라인(①~③ 산출
  코드)은 `expired/`로 격리·cron 중단(사용자 결정) — 산출 데이터는 postgres에 동결 보존,
  현재 가동 중인 것은 챗봇(rag_chat)·요약보고서(report_gen)·streamlit_demo다.

## 1. 저장소 구조 (2026-09-07 기준, 실제 상태 — services/ 해체+expired/ 격리 반영)
```
komir/
├─ dmz/                    # DMZ 존 배포 단위(외부망 접근, LLM 없음 — 수집기 전용)
│  ├─ collector/           # 독립 수집 도커(미배포 상태, dmz/collector/README.md 참고)
│  ├─ geo_collectors/      # 구 engine/geo/collectors — GDELT·GKG·뉴스 수집
│  ├─ msr_collectors/      # 구 engine/mineral_supply_risk/msr/collectors — 관세청·ECOS·
│  │                         KOMIS 등 정형 수집
│  └─ upload_files/        # 제3자 원본자료 수동 투척함(WoodMac·기업주가 zip 등)
├─ inhouse/                # in-house(airgap) 존 배포 단위 — RAG·서빙(챗봇·리포트)
│  ├─ common/              # ★2026-09-07 신설(services/ 해체) — 전 서비스 공용 인프라·조회:
│  │                          config·db·dbio(구 msr db 코어)·logging_config·llm_client·
│  │                          llm/(구 geo/llm — openai_compat 등 LLM HTTP 어댑터)·
│  │                          docs_static(+static_docs/)·komis_raw(KOMIS 원천 조회)·
│  │                          structured(out_*/geo_* 서빙 조회).
│  │                          의존 방향: 앱/도메인 → common 단방향(역참조 금지)
│  ├─ rag_core/            # 문서 기반 RAG — 챗봇 도메인 코어 라이브러리(★2026-09-07 rag에서
│  │  │                       개명: 서비스가 아니라 ingest·rag_chat·streamlit이 참조하는 코어임을
│  │  │                       이름으로 명시. "common만 참조" 규칙의 유일한 의도적 예외 대상)
│  │  ├─ ragkit/{ingest,chunk,tokenize_ko,embed,retrieve,generate,build_index,eval_retrieval}.py
│  │  ├─ retrieval/        # ★2026-09-07 구 services/shared/retrieval 편입 — pageindex·
│  │  │                       pageindex_agent·dense_pg·bm25_pg·hybrid_pg·access·evidence
│  │  └─ pageindex_client.py + pageindex_vendor/   # 구 services/shared에서 편입
│  ├─ ingest/              # ★2026-08-27 신설 — 파일 기반 보고서 정제·색인 독립 패키지
│  │  │                      (구 services/ingestion + rag/ragkit ETL 2종 + mineral_supply_risk
│  │  │                       파일 추출기 4종을 한곳으로). 실행은 cwd=inhouse에서
│  │  │                       python -m ingest.<sub>.<module> — inhouse/ingest/README.md 정본
│  │  ├─ pipeline.py models.py source_policy.py parsers/   # 추출 파이프라인 코어
│  │  ├─ extract/          # pdf_extract_{shareable,restricted}·ingest_reports·woodmac_xls·hwp_extract
│  │  ├─ okf/              # build_okf_documents.py (문서-OKF)
│  │  ├─ pageindex/        # build_pageindex_trees.py
│  │  └─ vectorize/        # build_pgvector_{index,okf}.py·backfill_doc_chunk_pub_date.py
│  ├─ rag_chat/            # 서빙: RAG 챗봇 SSE API(구 services/rag_chat, 컨테이너 가동 중)
│  ├─ report_gen/          # 서빙: 요약보고서 9종 API(구 services/report_gen, 컨테이너 가동 중)
│  │       # 서빙 공통 사항은 documents/meta/CONTAINER_ARCHITECTURE.md
│  ├─ streamlit_demo/       # 개발 데모 멀티페이지(komis-report-generator-main/streamlit_demo
│  │                          이식, 2026-08-27) — 챗봇(rag_chat SSE, 동작)·요약보고서(report_gen
│  │                          9종, 동작)·데이터관리(동작) + 진단예측·프롬프트관리(stub)
│  └─ data_lake/
│     ├─ db/                # 정형 파트 — minerals.duckdb(★ canonical 운영 DB, gitignore,
│     │                       geo_event·geo_index·geo_prob·fact_*·mart_*·out_* 등 전 테이블)
│     │                       + schema_addendum_v2.sql. 임시 duckdb이며 향후 실제 RDB로
│     │                       이관되며 제거 예정
│     ├─ semi_structure/    # 구 geo_data(이름 변경) — geo 파이프라인 정본 store(parquet,
│     │                       gitignore) — inbox/archive/store
│     └─ vector_db/         # 벡터 파트(Qdrant 마운트, RAG용)
├─ deploy/                  # 컨테이너화·airgap 배포(compose 2종+airgap 스크립트 —
│                              ★2026-09-07 inhouse/deploy에서 루트로 승격, build context는
│                              ../inhouse). documents/meta/CONTAINER_ARCHITECTURE.md 참고
├─ expired/                 # ★2026-09-07 신설 — 사용하지 않는 패키지 임시 보관(사용자 결정:
│  │                          "유지만 하고 사용하지 않음, 참조 경로도 없어야 함"). live 코드가
│  │                          이 안을 import하는 것 금지. 관련 host cron 7건도 같은 날 제거
│  │                          (백업: data_archive/crontab_backup_260907_expired_move.txt)
│  ├─ geo/                  # 구 inhouse/geo — 지정학 위기지수 파이프라인(llm/·extractors.py는
│  │                          살아있는 인프라라 common/·ingest/로 흡수 후 이동)
│  ├─ mineral_supply_risk/  # 구 inhouse/mineral_supply_risk — 진단·예측 모델+스크립트
│  │                          (db/dbio.py는 common/dbio.py로 흡수 후 이동)
│  ├─ commodity_api/        # 구 서빙 API — msr 모델 코드 의존+미가동이라 함께 격리
│  ├─ dashboard_expire/     # 구 dashboards 데모
│  └─ Makefile              # 구 inhouse/Makefile(초기 프로토타입 docker-compose 흐름)
├─ documents/               # 2026-07-22 mine_ws 최상위에서 이관
│  ├─ meta/{WORKLOG.md, DATA_REGISTRY.md, DB_SCHEMA.md, CONTAINER_ARCHITECTURE.md}  # 구 docs/
│  │       # (이름 변경만, 내용 정본 지위는 그대로) ★ 정본
│  ├─ 산출물/<주차>/         # 우리가 작성한 보고서·분석 산출물 — git 추적됨. 주차 폴더명은
│  │                           ISO 주차 기준(예: 2026-W30_0720-0726). 구 claude_output/도
│  │                           같은 날 이 구조로 재편됨(git rename, 이력 보존)
│  └─ (그 외)                # KOMIS·WoodMac·Argus·USGS·EU SCRREEN 등 제3자 원본자료(35GB) —
│                              git 미추적(.gitignore), 로컬 전용
└─ data_archive/            # 검증 실행 로그·백업(삭제 금지 정책, artifact-provenance-policy
                               참고) — 어느 배포 단위에도 속하지 않는 로컬 이력
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
- **경로 이관 주의(2026-08-06)**: 위 2026-08-05 이관으로 생긴 `engine/`가 이날 다시
  없어지고 `dmz/`·`inhouse/` 두 배포 단위로 쪼개졌다 — `engine/geo`→`inhouse/geo`,
  `engine/mineral_supply_risk`→`inhouse/mineral_supply_risk`, `engine/rag`→`inhouse/rag`,
  두 패키지 안의 `collectors/`는 각각 `dmz/geo_collectors/`·`dmz/msr_collectors/`로 분리
  이동. 루트 `services/`·`deploy/`·`dashboards/`는 `inhouse/` 아래로, 루트 `collector/`·
  `upload_files/`는 `dmz/` 아래로, 루트 `db/schema_addendum_v2.sql`은
  `inhouse/data_lake/db/`로, 루트 `geo_data/`는 `inhouse/data_lake/semi_structure/`로
  이름을 바꿔 이동, 루트 `docs/`는 `documents/meta/`로 이동, `warehouse/minerals.duckdb`는
  `inhouse/data_lake/db/minerals.duckdb`로 이동했다(라이브 프로세스의 쓰기 락 때문에
  물리 이동은 별도로 신중하게 진행 — 이 경로 표기가 최종 목적지). 과거 WORKLOG·
  DATA_REGISTRY 항목의 구 경로(`engine/...`, `docs/...`, `geo_data/...` 등) 표기는
  **그 시점 기록이라 갱신하지 않았음**, 재현할 땐 아래 §2의 새 경로를 쓸 것.
- **경로 이관 주의(2026-09-07)**: `inhouse/services/`를 해체했다 — 목적은 inhouse 직속
  디렉토리가 "개별 서비스 또는 데이터"로만 남게 하고 모듈 간 지식·코드 결합을 끊는 것.
  `services/shared`는 두 성격으로 분해: 전 서비스 공용(config·db·logging_config·
  llm_client·docs_static·komis_raw·retrieval/structured.py)은 신설 `inhouse/common/`으로,
  챗봇 도메인 전용(retrieval 나머지 7종·pageindex_client·pageindex_vendor)은
  `inhouse/rag/`(현 `rag_core/` — 같은 날 개명)로. `services/{commodity_api,rag_chat,report_gen}`은 inhouse 직속으로
  승격. 효과: 구 shared→ragkit 역참조가 rag 패키지 내부화되어 **순환 의존 소멸**,
  의존 방향은 앱(rag_chat·report_gen·streamlit_demo·ingest) → 도메인(rag_core)
  → common 단방향(ingest→rag_core 단방향 참조는 의도적 허용). import 철자도
  `shared.*`/`services.shared.*` 이중 표기에서 `common.*`/`rag.retrieval.*`로 단일화됐고,
  sys.path 부트스트랩은 마커(`common/llm_client.py`·`common/db.py`) 탐색 단일 방식으로
  통일(소스트리와 컨테이너 /app 레이아웃이 동일해짐). 과거 WORKLOG·DATA_REGISTRY의
  `services/...` 표기는 그 시점 기록이라 갱신하지 않았음.
- **경로 이관 주의(2026-09-07 후속, 같은 날)**: 미사용 패키지 격리 — `inhouse/geo`·
  `inhouse/mineral_supply_risk`·`inhouse/commodity_api`·`inhouse/dashboard_expire`가
  `expired/`(komir 루트, dmz/inhouse와 동급)로 이동. 살아있는 인프라만 흡수:
  `geo/llm`→`common/llm`, `geo/extractors.py`→`ingest/extractors.py`,
  `mineral_supply_risk/db/dbio.py`→`common/dbio.py`. live 코드에서 expired/ 참조 금지.

## 2. 실행 방법(현재 실제로 쓰는 방식 — README의 docker-compose `make` 흐름과 다를 수 있음)
```bash
# 파일 기반 보고서 정제·색인(inhouse/ingest/, 2026-08-27 독립) — cwd=inhouse/
cd komir/inhouse
python -m ingest.okf.build_okf_documents --what all         # 문서-OKF
python -m ingest.pageindex.build_pageindex_trees --no-summary
python -m ingest.vectorize.build_pgvector_index && python -m ingest.vectorize.build_pgvector_okf

# 서빙 2종은 컨테이너(docker run, 이미지 태그=날짜):
#   komir-rag-chat-test(18002)·komir-report-gen-test(18003) — Containerfile은 각 패키지에.
#   report_gen 재배포 후엔 seed_prompts 재실행 필수(메모리 참고).
# streamlit_demo는 호스트에서 streamlit run(포트 8501, cwd=inhouse/streamlit_demo).
```
**2026-09-07 이후 중단된 실행 경로**: geo 파이프라인(`python -m geo ...`)과
정형 진단/예측(`mineral_supply_risk/scripts/*`)은 패키지가 `expired/`로 이동하며
가동 중단됐다(사용자 결정 — 관련 host cron 7건 제거, dmz 수집 cron 포함).
out_*/geo_* 테이블은 중단 시점 데이터로 동결 — 챗봇/리포트의 structured 조회는
그 동결 데이터를 계속 서빙한다. 재가동이 필요하면 crontab 백업
(`data_archive/crontab_backup_260907_expired_move.txt`)과 expired/ 패키지를 복원할 것.
LLM: 로컬 vLLM(`LLM_PROVIDER=openai_compat`, `.env`에 `LLM_BASE_URL`·`LLM_MODEL`). `.env` 값
줄에는 절대 인라인 주석 달지 말 것(env_file 파서가 주석을 값으로 흡수하는 함정 — 메모리
`env-inline-comment-gotcha` 참고).

## 3. 세션 시작 시 권장 순서
1. 이 파일로 방향 파악.
2. 메모리 시스템 확인(자동 로드) — 특히 `next-tasks-komir`(잔여 작업)·`gkg_relevance_redesign_260720`
   (GKG 관련 작업 전 필수 확인, 재발명 방지)·`data-quantity-verification-rule`(수량은 항상 직접
   쿼리로 재확인, 문서값 재인용 금지).
3. `documents/meta/WORKLOG.md` 최상단 최근 항목 확인.
4. 발주처 보고 문서는 `documents/산출물/<주차>/`의 최신 날짜 버전이 정본(예:
   `documents/산출물/2026-W30_0720-0726/핵심광물_시스템구성_요약본_260722.docx`) —
   DATA_REGISTRY.md "관련 문서" 절에 정본/구버전
   구분이 명시되어 있음.

## 4. 코드/실험 작업 원칙 — 구조가 모델을 앞선다
> ⚠ 아래 진단·예측 실험 규율은 msr 파이프라인이 살아있던 시기의 것 — 2026-09-07
> expired/ 격리 후엔 재가동할 때만 유효(원칙 자체는 역사·재발방지 기록으로 보존).
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
