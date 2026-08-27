# 컨테이너화·챗봇·리포트 아키텍처 설계안 (2026-08-05)

> **범위**: 이 문서는 설계안만 다룬다(사용자 확정: "이번 세션은 설계안만, 구현은 다음").
> 실제 코드 구현·기존 테이블 마이그레이션·서비스 기동은 **후속 세션**에서 진행한다.
> 이 문서 자체가 다음 세션의 작업 지시서 역할을 한다.

## 0. 확정된 요구사항 (사용자 확인 완료, 2026-08-05)

| 항목 | 결정 |
|---|---|
| DB 기술 | DuckDB 임베디드(현행) → **진짜 클라이언트-서버 RDB(Postgres 등)로 이관** |
| 이번 세션 범위 | **설계안만**(디렉토리 구조+Containerfile/compose 스켈레톤). 구현은 다음 세션 |
| "광종 리스트" 아웃풋 | 기존 진단·예측·지수 모델 결과를 서빙하는 **API** |
| 챗봇 서버 | komir 레포지토리 내에 **새 FastAPI 챗봇 서비스**를 신규 구축 |
| `geo/`·`mineral_supply_risk/`·`rag/` → `engine/` 통합 | **실행 완료(2026-08-05, 같은 날 트리거 조건 미충족 상태에서 위험 감수하고 즉시 진행 재확정)** — §2-1. 시스템 crontab 갱신은 main 병합 시점에 별도 처리 필요(미완료) |
| 벡터DB | ~~Qdrant로 확정(2026-08-05 추기)~~ → **2026-08-11 재정정: pgvector로 결정 변경.** 8/5 폐기 사유는 "Postgres는 외부서비스라 확장 설치 권한 보장 없음"이었는데, 실측(`pg_available_extensions`·`pg_extension`) 결과 komis_demo DB에 **pgvector 0.8.2가 이미 설치돼 있고 접속 계정(`postgres`)도 슈퍼유저**임을 확인 — 우려했던 리스크 자체가 없었다. Qdrant를 별도로 기동·운영할 이유가 없어져 정형 RDB와 동일한 Postgres에 벡터까지 같이 둔다(신규 컨테이너·서비스 불필요, 사용자 결정) — §4·§5·§7 |

및 사용자 원 요구사항 8개(요약): ①airgap+podman 배포 ②LLM/embedding·DB는 외부서비스,
.env로 접속정보만 ③3대 아웃풋(광종 리스트·RAG·Report) ④RAG-챗봇 연동(user_id·
session_id·히스토리) ⑤챗봇 스트리밍 ⑥RAG는 비정형(pdf/hwp/docx/doc/xlsx/xls/csv)+
정형(RDB) 둘 다 ⑦Report도 비정형+정형 기반 템플릿 작성 ⑧Report는 RDB에 주기적 저장.

> **2026-08-06 갱신 예고**: 아래 §0-1에서 이 문서의 전제를 하나 깬다 — "airgap 단일
> 존"이 아니라 **DMZ(수집)/망연계/in-house(airgap) 3단 분리**가 실제 배포 목표였음이
> 이번에 확인됐다. §0의 결정 사항 자체는 무효화되지 않지만(Qdrant·챗봇 신규 구축 등은
> 그대로 유효), "수집기까지 포함해 전부 하나의 airgap 환경에서 돈다"는 암묵 전제로
> 쓰인 §2·§5·§7의 일부 서술은 §0-1 기준으로 다시 읽어야 한다. 절 전체를 새로
> 쓰지 않고 해당 지점마다 "(§0-1 참고, 2026-08-06)" 각주를 달아 무엇이 바뀌었는지
> 표시하는 방식을 택했다 — 8/5 하루짜리 결정과 8/6 하루짜리 결정이 뒤섞여 있으니
> 날짜 태그를 신뢰할 것.

## 0-1. 배포 토폴로지 재정의 (2026-08-06, 사용자 확인)

8/5 설계는 "airgap 환경 하나"를 전제로 수집기까지 포함해 전부 그 안에서 돈다고
가정했다. 실제로는 **두 개의 물리적으로 분리된 시스템**에 나눠 배포된다 — 8/6
대화에서 사용자가 직접 확인·정정.

| 구분 | 결정 | 비고 |
|---|---|---|
| 배포 존 | **DMZ(수집)** → **망연계** → **in-house(airgap)** 3단 | DMZ와 in-house는 별개 시스템. §7 podman-compose는 in-house만의 것으로 범위 축소 |
| DMZ 수집기 범위 | `dmz/geo_collectors/`(구 `engine/geo/collectors`, GDELT/GKG) + `dmz/msr_collectors/`(구 `engine/mineral_supply_risk/msr/collectors`, 관세청·ECOS·KOMIS·거래소 등) **전부** — 2026-08-06 물리적으로도 `git mv`로 이 경로에 반영 완료 | 사용자 확인: "둘 다 DMZ로" |
| DMZ 제약 | **LLM 사용 불가**. 원본 파일(csv/pdf/hwp/docx 등)을 로컬로 다운로드 → in-house 전달로 역할 종료. 가공·추출·DB 직접 적재 없음 | **직접 코드 재확인(2026-08-06, 적대적 검증에서 최초 진단 오류 발견·정정)**: `dmz/msr_collectors/customs_api.py`의 `collect()`는 이미 `sink` 콜백으로 fetch/load가 분리돼 있어 그 자체는 DMZ에 그대로 둬도 됨. 실제로 즉시 DB에 쓰는 지점은 collectors가 아니라 **`inhouse/mineral_supply_risk/scripts/backfill_customs_monthly.py`·`collect_annual_bycountry.py`의 `_sink` 콜백**(collect 호출과 같은 프로세스에서 DB upsert) — DMZ 분리 리팩터 대상은 collectors가 아니라 이 **드라이버 스크립트들**(§8에 정정 반영) |
| 망연계 전달 | **단방향 네트워크 경로**, 자동화 가능하나 **보안감사 SDK/솔루션이 중간에서 데이터 감사(CDR류) 후 전달** | 이 감사 게이트웨이는 komir이 빌드·배포하는 대상이 아님 — 외부 보안 인프라와의 **연동 지점**으로만 문서화(§7) |
| in-house ingestion | **공용 LLM ETL 엔진** 하나가 원문 1건당 두 산출물을 동시 생성 | ① 기존 geo-OKF(`inhouse/data_lake/semi_structure/okf/`, 구 `geo_data/okf/` — metrics/events/issues/index, 지수·진단/예측 피처용, 소량 파생 지식층) ② 신규 **문서-OKF**(원문 텍스트+섹션/표 구조 보존 — Qdrant 청킹과 PageIndex 트리의 공통 소스). 실물 확인 결과 geo-OKF의 `sources/*.md`는 원문 포인터+메타데이터뿐 원문 전체가 없어(§5 실사) 문서-OKF가 별도로 필요하다는 게 8/6 대화의 결론 |
| 상위 data-lake(2026-08-06 구조 확정, 08-06 3분류로 재정정) | **RDB와 동일 시스템이 아니라, RDB를 포함하는 더 큰 논리적 상위 개념**(사용자 확인). **정형/비정형/벡터 3파트**로 구성 — 벡터를 정형·비정형 어디에도 억지로 끼워넣지 않고 독립 파트로 둔 것(사용자 판단, 타당함 — 벡터는 저장엔진·접근패턴이 관계형/문서와 다른 별개 데이터 형태) | 아래 세 행이 data-lake의 하위 영역. 이전에 "RDB=data-lake 동일 시스템"·"Qdrant는 data-lake 소속 아님"으로 정리한 건 둘 다 오독이었음(사용자 재정정). 물리적으로는 `inhouse/data_lake/{db,semi_structure,vector_db}`(2026-08-06 반영) |
| ├ 정형 데이터 = **`data_lake.rdb`** | data-lake **안에 속한 정형 파트**. 벤더 후보 Oracle·PostgreSQL 등(미확정) — 개발 단계는 Oracle. 가공된 정형 데이터, RAG의 정형 피처, 진단/예측 모델 피처가 전부 여기 적재 | `inhouse/data_lake/db/schema_addendum_v2.sql`(§4)의 `tsvector`/`GIN`은 **Postgres 전용 문법**이라 최종 벤더가 Oracle이면 Oracle Text(CONTEXT 인덱스) 등으로 다시 써야 함 — 벤더 미확정 상태라 지금은 구현 안 함, 열어둠 |
| ├ 비정형 데이터 | data-lake **안에 속한 비정형 파트** — OKF·PageIndex 등으로 채움(사용자 확정) | 원문 보존(OKF)과 그 위의 구조 인덱스(PageIndex) 둘 다 "문서" 성격이라 같은 파트로 묶임 |
| └ 벡터 데이터 = **Qdrant**(픽스) | data-lake **안에 속한 벡터 파트** — Qdrant로 확정(2026-08-05 결정 유지) | **논리적 소속(data-lake 벡터 파트)과 물리적 소유는 별개 축** — Qdrant는 상위 data-lake가 이미 갖춘 기존 인프라가 아니라 **komir 쪽에서 in-house 시스템에 같이 붙여서(직접 podman으로 소유·기동) 반입**하는 컴포넌트(사용자 확인, §0 2026-08-05 결정과 일치) |
| 비정형 검색 | **Qdrant**(벡터, data-lake 벡터 파트) + **PageIndex**(트리 기반 LLM 추론 탐색, data-lake 비정형 파트) 이원화, **둘 다 확정**(사용자 확인 — RAG·Report 공용 3-도구 중 하나로 명시). **온톨로지 기반 접근은 배제**(사용자 판단: 난이도상 어려움) | 문서-OKF가 두 인덱스의 공통 소스. PageIndex는 대량·구조화된 보고서(WoodMac/Argus/USGS 등)에서 벡터 검색만으로 답하기 어려운 질의를 보완하는 목적. **미확정으로 남은 건 세부 구현**(정확히 어떤 백킹 스토어·라이브러리를 쓸지)뿐, 채택 여부 자체는 확정 |
| RAG/Report 도구 공유 | RAG 챗봇에 필요한 도구 3종(① RDB 정형 조회 ② VectorDB 조회 ③ PageIndex 조회)을 **Report 생성기도 동일하게 필요** — `inhouse/services/shared/retrieval/`로 공용 구현(사용자 확인) | 호출 패턴은 다름: RAG는 매 턴 LLM이 동적으로 도구 선택(에이전트형), Report는 템플릿 섹션마다 필요한 도구가 정적으로 매핑될 가능성이 높음(§6) |

**아직 미확정으로 남겨둔 것**(추측으로 채우지 않음): `data_lake.rdb` 최종 벤더(Oracle·
PostgreSQL 등 후보, 개발단계만 Oracle 확정), 비정형 하위 영역(OKF·PageIndex)의 세부
구현(백킹 스토어 등), DMZ↔in-house 물리 배포(컨테이너/VM/베어메탈) 형태.

## 1. 기존 자산 실사 결과 (재사용 대상 — 새로 안 만든다)

설계 전 실제 코드를 전수 확인했다(재구현 방지, CLAUDE.md §4 "구조가 모델을 앞선다"
원칙 — 새 코드보다 기존 자산 재사용이 우선).

| 자산 | 위치 | 상태 |
|---|---|---|
| DB 어댑터(DuckDB↔SQLAlchemy URL 동일 API) | `mineral_supply_risk/db/dbio.py` | **이미 존재**. `apply_schema`/`write_df`/`read_sql`이 `target` 문자열의 `://` 유무로 DuckDB/서버DB를 자동 분기. Postgres는 `sa.create_engine("postgresql+psycopg2://...")`로 코드 변경 없이 바로 됨(현재 독스트링은 Oracle/MariaDB/MSSQL만 예시로 들었지만 SQLAlchemy 방언이라 Postgres도 동일 패턴). **버그 1건 발견**: `apply_schema`의 DuckDB 분기(40~42행)가 함수 인자에 없는 `schema` 변수를 참조 — DuckDB 대상 호출 시 `NameError`. 구현 착수 시 최우선 수정 대상(1줄 수준, 설계 범위 밖이라 지금은 수정 안 함).
| 포터블 스키마(DuckDB→Oracle/MariaDB/MSSQL 이관용 DDL) | `mineral_supply_risk/db/schema_core.sql` | **이미 존재**. `fact_*`·`mart_*`·`geo_index`·`geo_event`·`out_diagnosis_alert`·`out_import_forecast`·`out_report`·**`doc_chunk`**까지 정의돼 있음 — 특히 `doc_chunk`는 "⑥챗봇(RAG) 문서 청크" 용도로 이미 예정돼 있었다(주석 원문 확인). Postgres는 방언표에 없지만 Oracle/MariaDB/MSSQL보다 ANSI에 더 가까워 이관 부담이 더 작음.
| 외부 LLM 연동 어댑터 | `geo/llm/openai_compat.py` 등 | **이미 존재**, provider 무관(rule/mock/openai_compat/anthropic). `rag/ragkit/generate.py`가 이미 재사용 중 — 챗봇 서비스도 그대로 재사용.
| RAG 검색 파이프라인(하이브리드 BM25+dense, RRF) | `rag/ragkit/{ingest,chunk,tokenize_ko,embed,retrieve,generate,build_index,eval_retrieval}.py` | **이미 존재**(오늘 사용자가 직접 커밋). 비정형 문서(`documents/산출물/`) 대상, dense 임베딩은 로컬 `intfloat/multilingual-e5-small`(작고 로컬 실행 — airgap 번들링에 유리). **session_id/user_id/streaming 개념은 전무**(확인됨) — 이번 설계의 신규 작업 대상. 현재 자체 `rag/index/rag.duckdb`(BM25 FTS+dense 벡터 동거)에 저장 중 — 이관 시 **dense 벡터는 Qdrant, BM25 텍스트+메타는 `doc_chunk`(Postgres tsvector)로 분리**(§4·§5, 2026-08-05 pgvector안 폐기).
| 모델 재현·설명가능성 로직 | `dashboards/streamlit_app.py` | **이미 존재**(이번 세션 초반 구현). Ridge 진단·alert 규칙엔진·ExtraTrees 예측·SHAP 설명 전부 read-only 재적합 함수 호출로 구현돼 있음 — **"광종 리스트" API의 비즈니스 로직 원본**으로 그대로 이식(챗봇처럼 새로 만들 게 아니라 뽑아서 옮기는 작업).
| 컨테이너 스캐폴딩 | 루트 `docker-compose.yml`, `collector/{Dockerfile,docker-compose.yml}`, `mineral_supply_risk/Dockerfile`, `geo/{Dockerfile,docker-compose.yml}` | **이미 존재**하고 대체로 실제 코드와 일치(공상적 문서 아님) — `geo/docker-compose.yml`의 `host.docker.internal:host-gateway`로 호스트측 로컬 LLM 접속 패턴은 이번 airgap 설계에도 그대로 재사용. `mineral_supply_risk/Dockerfile`은 이미 `sqlalchemy` 설치를 포함(서버DB 염두). 다만 geo 최신 서브커맨드(`gkg-parse` 등) 일부 compose 서비스 누락 — 구현 단계에서 갱신 필요.
| Report 생성기 | — | **전무**(신규 개발). `out_report` 스키마만 존재(0건 참조) — 이걸 확장해서 쓴다.
| 정형 데이터 검색기(RAG용) | — | **전무**(신규 개발). `rag/README.md`가 "구조화 데이터 질문은 스코프 밖"이라고 명시적으로 뺐던 부분 — 이번 요구사항으로 새로 채워야 함.

## 2. 목표 디렉토리 구조

기존 3개 "엔진" 패키지(`geo/`·`mineral_supply_risk/`·`rag/`)는 그대로 두고, 그 위에
서빙 레이어(`services/`)와 배포 레이어(`deploy/`)를 신설한다 — 엔진(배치·모델)과
서빙(API·챗봇·리포트)을 분리하는 통상적 패턴. 기존 코드 이동은 **하지 않는다**(임포트
경로가 전부 깨지는 위험 — 구현 단계에서 별도 회귀검정 사이클로).

```
komir/
├── geo/                          # 기존 유지 — 엔진(비정형 지정학 지수 파이프라인)
├── mineral_supply_risk/          # 기존 유지 — 엔진(정형 파이프라인+진단/예측 모델)
│   └── db/                       # 기존 dbio.py·schema_core.sql — services/shared가 임포트
├── rag/                          # 기존 유지 — 엔진(RAG 검색 코어), ragkit는 services/rag_chat이 임포트
├── dashboards/                   # 기존 유지(사람용 보조 데모) — streamlit_app.py 로직은
│                                    services/commodity_api로 "이식"(복사 후 리팩터, 원본은
│                                    당분간 병존 — 급격한 폐기 금지, CLAUDE.md §4 원칙)
├── services/                     # ★ 신설 — 서빙 레이어(3대 아웃풋 + 공통 모듈)
│   ├── shared/                   # 3개 서비스 공통 라이브러리
│   │   ├── db.py                 # mineral_supply_risk/db/dbio.py 재노출(+버그수정판)
│   │   ├── llm_client.py         # geo/llm/openai_compat.py 재노출 래퍼
│   │   └── config.py             # .env 통합 로더(Pydantic Settings)
│   ├── commodity_api/            # ① 광종 리스트 API
│   │   ├── Containerfile
│   │   ├── requirements.txt
│   │   └── app/
│   │       ├── main.py           # FastAPI 앱 엔트리
│   │       ├── routers/
│   │       │   ├── diagnosis.py  # /commodities/{cc}/diagnosis (dashboards §② 로직 이식)
│   │       │   ├── forecast.py   # /commodities/{cc}/forecast  (dashboards §③ 로직 이식)
│   │       │   └── geo_index.py  # /commodities/{cc}/geo-index (dashboards §① 로직 이식)
│   │       └── deps.py
│   ├── rag_chat/                 # ② RAG 챗봇
│   │   ├── Containerfile
│   │   ├── requirements.txt
│   │   └── app/
│   │       ├── main.py           # FastAPI + SSE 스트리밍 엔드포인트
│   │       ├── routers/chat.py   # POST /chat (user_id·session_id 필수)
│   │       ├── session_store.py  # chat_session/chat_message CRUD(§4 신규 테이블)
│   │       ├── retrieval/
│   │       │   ├── unstructured.py  # rag/ragkit 재사용 — dense는 Qdrant, BM25는 Postgres
│   │       │   │                      tsvector 조회 후 기존 RRF 융합 로직 그대로(§5)
│   │       │   └── structured.py    # 신규: NL→SQL 또는 템플릿 질의(§5)
│   │       └── streaming.py      # LLM 토큰 스트림 → SSE 청크 변환
│   ├── report_gen/               # ③ Report 생성
│   │   ├── Containerfile
│   │   ├── requirements.txt
│   │   └── app/
│   │       ├── main.py           # 수동 트리거 API(POST /reports/{template}/generate)
│   │       ├── templates/        # jinja2 템플릿(광종별 주간 리포트 등)
│   │       ├── generator.py      # 템플릿×(비정형 검색+정형 쿼리)→본문 조립
│   │       └── scheduler.py      # APScheduler cron → generator 호출 → out_report 저장(§6)
│   └── ingestion/                # 비정형 원천 수집·파싱 공통(RAG+Report 겸용)
│       └── parsers/
│           ├── pdf.py hwp.py docx.py doc.py xlsx.py xls.py csv.py  # 포맷별 파서(§7)
├── db/                            # ★ 신설(경량) — 서비스 공통 스키마 확장분만
│   └── schema_addendum_v2.sql    # chat_session/chat_message + out_report.body TEXT화 +
│                                    doc_chunk BM25용 tsvector+GIN 인덱스(§4, 벡터는 Qdrant라
│                                    이 테이블엔 없음) — schema_core.sql은 불변, 이 파일을
│                                    이어서 적용하는 방식(원본 훼손 없음)
├── deploy/                        # ★ 신설 — airgap·podman 배포
│   ├── podman-compose.yml        # ★정본★ — 3개 서비스 + qdrant(공식 이미지, komir이
│   │                                직접 소유·기동) 오케스트레이션. 정형DB·LLM은 .env로
│   │                                외부 참조만(§0). airgap 운영 배포 대상.
│   ├── docker-compose.yml        # 로컬 개발·테스트 편의용(2026-08-05 추가) — 구성은
│   │                                podman-compose.yml과 동일, build 키 표기만 다름
│   │                                (`dockerfile` vs `containerfile`). 수동 동기화 필요.
│   ├── .env.example              # 통합 환경변수 계약(§3, 두 compose 파일 공용)
│   └── airgap/
│       ├── build_images.sh       # (연결망) podman build 전체(qdrant는 pull, 나머진 build)
│       ├── save_images.sh        # podman save → tar 묶음(qdrant 공식 이미지 포함)
│       └── load_images.sh        # (반입망) podman load
└── docs/CONTAINER_ARCHITECTURE.md  # 본 문서(당시 경로 — 2026-08-06 documents/meta/로 이동,
                                      # 지금 위치는 documents/meta/CONTAINER_ARCHITECTURE.md)
```

## 2-1. `engine/` 통합 마이그레이션 — **실행 완료(2026-08-05, 같은 날 후속)**

> **후속 갱신(2026-08-06)**: 아래 `engine/` 레이아웃은 이 절이 기록하는 시점(8/5)의
> 실제 상태였으나, 다음날 §0-1의 DMZ/in-house 분리가 물리적으로도 실행되면서
> `engine/`는 다시 없어지고 `dmz/`·`inhouse/` 두 배포 단위로 쪼개졌다(`engine/geo`→
> `inhouse/geo`, `engine/mineral_supply_risk`→`inhouse/mineral_supply_risk`,
> `engine/rag`→`inhouse/rag`, 두 패키지의 `collectors/`는 각각 `dmz/geo_collectors/`·
> `dmz/msr_collectors/`로 분리). 이 절 자체는 8/5 시점 기록이라 갱신하지 않고 그대로
> 둔다 — 현재 정본 트리는 `CLAUDE.md` §1 참고.

`geo/`·`mineral_supply_risk/`·`rag/`를 `engine/` 아래로 묶어 서빙 레이어(`services/`)와
물리적으로도 분리하는 안 — 원래는 "서비스 3종+Postgres 이관이 먼저 안정화된 뒤"로
미루기로 합의했었으나(트리거 조건 미충족), **사용자가 위험을 인지한 상태에서 즉시
진행을 명시적으로 재확정**해 같은 날 실행했다. 아래는 실행 기록이며, 아직 남은
후속 조치(§ 끝 "남은 일")가 있다.

### 실제 구조 (실행됨)

```
komir/
├── engine/
│   ├── geo/                      # git mv geo → engine/geo (완료, rename 이력 보존)
│   ├── mineral_supply_risk/      # git mv mineral_supply_risk → engine/mineral_supply_risk (완료)
│   └── rag/                      # git mv rag → engine/rag (완료)
├── services/                     # (§2, 변경 없음)
├── db/
├── deploy/
└── ...
```

### 실행 기록 — 무엇을 확인·고쳤나

1. **cron 인벤토리**(실제 `crontab -l` 확인): komir 관련 3건 전부 확인 —
   `mineral_supply_risk/scripts/cron_collect_feeds.sh weekly`(토 09:10)·
   `〃 monthly`(매월 6일 09:20)·`geo/cron_gkg_increment.sh`(토 06:30). 전부
   **본채(main checkout)의 절대경로**를 참조 — git으로 추적되지 않으므로 `git mv`로는
   안 바뀜, 별도 시스템 조치 필요(아래 "남은 일" 참고).
2. **임포트 경로 grep**: `sys.path.insert` 84건 확인 — 전부 `os.path.dirname(__file__)`
   기준 **상대경로**라 각 패키지를 통째로 옮기는 것만으로는 내부 임포트가 깨지지
   않음(패키지 내부 상대 깊이가 그대로라서). 깨지는 건 **패키지 바깥에서 그 경로를
   가리키던 곳**뿐 — 아래 3.
3. **git mv** 세 패키지, 한 커밋(§8 착수 시 실행분과 동일 커밋에 포함).
4. **바깥 참조 수정 완료**:
   - `dashboards/streamlit_app.py`의 `MSR_ROOT` 상대경로에 `engine` 한 단 추가.
   - `mineral_supply_risk/scripts/cron_collect_feeds.sh`·`geo/cron_gkg_increment.sh`의
     `ROOT="$(cd "$(dirname "$0")/../.." && pwd)"` 류 계산에 `..` 한 단 추가(한 단
     더 깊어졌으므로) — **수정 후 실제 bash로 재계산해 `komir/`로 정확히 resolve됨을
     확인**(추측 아님).
   - 루트 `docker-compose.yml`의 `build.context`(`./mineral_supply_risk`→
     `./engine/mineral_supply_risk`, `./geo`→`./engine/geo`).
   - `CLAUDE.md` §1 구조도·§2 실행 명령 전면 갱신(날짜도 2026-08-05로 갱신).
   - `docs/DB_SCHEMA.md`의 `schema_core.sql` 등 라이브 경로 참조 2곳.
   - `collector/README.md`·`collector/common.py`의 `geo/collectors/...` 주석 2곳.
   - `services/rag_chat/Containerfile`의 실제 `COPY` 지시문(유일하게 기능적으로
     깨졌을 지점 — 나머지 services/ 내 참조는 전부 `NotImplementedError` 스켈레톤
     안의 설명용 주석/독스트링이라 실행에 영향 없어 이번엔 그대로 둠, 다음 구현
     세션에서 실제 코드 작성 시 자연히 현재 경로 기준으로 쓰게 됨).
5. **과거 문서는 갱신하지 않음**(원칙 유지): `docs/WORKLOG.md`·`docs/DATA_REGISTRY.md`의
   기존 항목들은 그 시점 경로 그대로 — 특히 DATA_REGISTRY.md는 "재현 명령"까지 담고
   있어 문자 그대로 복사하면 구 경로라 실패하지만, 이력 문서의 특성상 의도적으로
   그대로 둠(과거 산출물이 그 경로에서 만들어졌다는 사실 자체가 기록 가치).

### 남은 일(이 실행으로 아직 못 끝낸 것)

- **실제 시스템 `crontab` 갱신 — main 병합 시점에 반드시 같이 처리**: git으로
  추적되지 않는 시스템 crontab 3건이 여전히 구 절대경로를 가리킨다. main 병합
  전까지는 본채 파일이 안 바뀌어 무해하지만, **병합하는 순간부터 다음 cron
  실행(가장 이른 건 토요일 06:30 GKG)까지 사이에 crontab도 같이 고쳐야 한다** —
  안 그러면 정확히 이 프로젝트가 "가장 위험한 실패 모드"라 불러온 "조용히 멈춤"이
  실제로 발생한다.
- **회귀검정(§ 원 체크리스트 5번)은 미실행** — 전체 주간/월간 cron 체인을 수동
  트리거해 정상 완주를 확인하는 건 이번 세션 스코프에서 하지 않았다(운영 DB에
  실제 영향을 주는 행위라 별도 확인 없이 실행하지 않음). 최소한 각 스크립트의
  `--help`나 무해한 하위커맨드로 임포트·경로 해석만 스모크 테스트하는 것을 권장.

## 3. 통합 `.env` 계약 (기존 컨벤션 확장 — 새 접두사 만들지 않음)

기존 `geo/.env.example`·`mineral_supply_risk/.env.example`·루트 `.env.example`가 이미
쓰던 이름을 그대로 확장한다(실사 결과 §1 참고 — `MSR_DB`가 이미 SQLAlchemy URL을
받는다는 주석까지 있었음).

```bash
# ── DB(외부 서비스, 필수) ── 벤더 미확정(§0-1, 2026-08-06) — 개발단계는 Oracle
# 예시는 개발단계 기준(Oracle). SQLAlchemy 방언만 바뀌면 dbio.py 코드 변경 없음(§1).
MSR_DB=oracle+cx_oracle://user:pw@host:1521/?service_name=data_lake.rdb   # 정형 팩트·마트·out_* 전체
                                                            # = data_lake.rdb, 상위 data-lake의 정형 하위 영역(§0-1) — data-lake 자체와 동일 시스템 아님
                                                            # (기존 DuckDB 경로 대체, 최종 벤더 결정 시 URL만 교체)
MSR_PUBLISH_SCHEMA=                                        # 선택, 스키마 분리 시

# ── LLM/임베딩(외부 서비스, 필수 — 기존 geo 컨벤션 그대로) ──
LLM_PROVIDER=openai_compat
LLM_BASE_URL=http://<host>:<port>/v1
LLM_MODEL=<모델명>
LLM_API_KEY=
LLM_TEMPERATURE=0
EMBEDDING_BASE_URL=                # 비워두면 로컬 e5-small(컨테이너 내 로컬 실행, 임베딩은
                                    # LLM 서버와 분리 — 작아서 airgap 이미지에 번들 가능)
EMBEDDING_MODEL=intfloat/multilingual-e5-small

# ── 벡터DB(komir이 직접 소유·기동 — LLM/정형DB와 달리 "외부 서비스"가 아님, §0) ──
QDRANT_URL=http://qdrant:6333       # inhouse/deploy/podman-compose.yml 내부 서비스명 기본값
QDRANT_COLLECTION=doc_chunks

# ── 챗봇 서비스 ──
CHAT_SESSION_TTL_DAYS=90           # 세션 히스토리 보존기간
CHAT_STREAM_CHUNK_MS=50            # SSE 청크 전송 간격(선택)

# ── 리포트 스케줄러 ──
REPORT_SCHEDULE_CRON="0 6 * * MON" # 매주 월요일 06:00(예시)
REPORT_TEMPLATE_DIR=/app/templates

# ── AI 서버군 갱신 스케줄(2026-08-06 확정, §0-1) — 하드코딩 금지, 값 변경 후 서비스
#    재시작으로 반영. "매월 첫째주 일요일" 표현은 순수 cron 문자열로는 부족할 수 있음
#    (day-of-month·day-of-week AND 결합 필요 — APScheduler CronTrigger(day='1-7',
#    day_of_week='sun') 패턴 참고, 목표아키텍처_DMZ_inhouse_흐름_260806.md §2-2 상세) ──
INGESTION_SCHEDULE_CRON="0 0 * * SUN"     # 정형+비정형+RAG 인덱스 전체, 매주 일요일
DIAGNOSIS_TRIGGER=after_geo_index          # cron 아님 — 지정학위기지수 갱신 직후 이벤트 체이닝
FORECAST_SCHEDULE_CRON="0 1 1-7 * SUN"     # 매월 첫째주 일요일만(day-of-month 1-7 AND SUN)

# ── DMZ 수집기 스케줄(2026-08-06 확정, 소스별 차등 — 목표아키텍처_DMZ_inhouse_
#    흐름_260806.md §2-3 상세) — 뉴스는 촘촘히, 저빈도 통계 API는 하루 한 번,
#    반차단 이력 있는 소스는 더 신중하게. 값은 DMZ 쪽 .env, 서비스 재시작 반영 ──
GKG_COLLECT_CRON="0 * * * *"               # GDELT/GKG, 매시 정각(Tier 0)
TIER1_MARKET_COLLECT_CRON="0 */4 * * *"    # 거래소재고·COT, 4시간마다(Tier 1)
TIER2_STATS_COLLECT_CRON="0 2 * * *"       # 관세청·ECOS·Comtrade 등 정형 통계, 일 1회(Tier 2)
TIER3_POLICY_COLLECT_CRON="0 3 * * SAT"    # MOFCOM 등 정책공고류, 주 1회 유지(Tier 3)
TIER4_UNSTABLE_COLLECT_CRON="0 4 * * SAT"  # GACC 등 반차단 소스, 주 1회 이하(Tier 4)
DMZ_TO_INHOUSE_TRANSFER_CRON="0 1 * * *"   # airgap 전달, 매일 새벽 1시(전 Tier 공통)
```

## 4. DB 스키마 확장안 (`inhouse/data_lake/db/schema_addendum_v2.sql`, 설계만 — 미적용)

`schema_core.sql`은 건드리지 않고(회귀 위험 최소화, CLAUDE.md §4 "최소·외과적 변경"),
아래를 별도 파일로 이어 붙이는 방식을 제안한다.

```sql
-- 챗봇 세션·히스토리(신규 — user_id/session_id 요구사항)
CREATE TABLE IF NOT EXISTS chat_session (
  session_id  VARCHAR(36) NOT NULL,
  user_id     VARCHAR(80) NOT NULL,
  title       VARCHAR(200),
  created_at  TIMESTAMP, updated_at TIMESTAMP,
  PRIMARY KEY (session_id)
);
CREATE TABLE IF NOT EXISTS chat_message (
  message_id   VARCHAR(36) NOT NULL,
  session_id   VARCHAR(36) NOT NULL,
  role         VARCHAR(16),              -- user/assistant/system
  content      TEXT,
  citations_json VARCHAR(4000),          -- 인용 청크 id 등(비정형+정형 출처 둘 다)
  created_at   TIMESTAMP,
  PRIMARY KEY (message_id)
);

-- out_report.body 확장: VARCHAR(8000) → TEXT(실제 보고서 본문엔 부족한 크기였음)
ALTER TABLE out_report ALTER COLUMN body TYPE TEXT;   -- Oracle: CLOB / MSSQL: NVARCHAR(MAX)

-- doc_chunk 확장: 벡터는 여기 두지 않는다(2026-08-05 결정 — 아래 "벡터DB=Qdrant" 참고).
-- BM25 절반(현재 rag/ragkit이 DuckDB FTS로 하던 것)의 Postgres 대응은 tsvector+GIN.
ALTER TABLE doc_chunk ADD COLUMN source_type VARCHAR(16);   -- 'unstructured'|'structured'
ALTER TABLE doc_chunk ADD COLUMN structured_query TEXT;     -- source_type='structured'일 때
                                                              -- 원 SQL/근거 쿼리 보존(감사용)
ALTER TABLE doc_chunk ADD COLUMN txt_tsv tsvector
  GENERATED ALWAYS AS (to_tsvector('simple', txt)) STORED;  -- 한국어 전용 tsvector 설정이
  -- 기본 제공되지 않음('simple'은 형태소 분석 없이 단순 토큰화) — rag/ragkit/tokenize_ko.py의
  -- 한글 bigram 전처리를 txt에 미리 적용해 저장할지, pg 한국어 확장(예: mecab 연동)을 쓸지는
  -- 구현 단계 결정 필요. DuckDB 개발환경에는 이 GENERATED 문법이 없어 별도 분기 필요(주의).
CREATE INDEX IF NOT EXISTS idx_doc_chunk_tsv ON doc_chunk USING GIN (txt_tsv);
```

> **2026-08-11 구현 반영(실행 완료)**: 아래 "벡터DB = Qdrant" 문단은 §0 표대로
> 뒤집혔다 — 벡터는 **pgvector로 komis_demo의 `mineral_risk.doc_chunk`에 직접**
> 들어간다(Qdrant 미기동). 실제 적용 DDL은 `inhouse/data_lake/db/schema_pgvector.sql`
> (신규, 이 §4 블록을 대체하는 게 아니라 dense 절반만 적용 — `structured_query`·
> `txt_tsv`(GIN)는 아직 미적용, BM25는 당분간 `rag/index/rag.duckdb`의 DuckDB FTS).
> 적재는 `rag/ragkit/build_pgvector_index.py`, 조회는
> `services/shared/retrieval/dense_pg.py::dense_search_pg()`.
> 2026-08-11 실측: `mineral_risk.doc_chunk` 1,206행(문서 76건), `embedding vector(384)`
> 전행 채움, HNSW(`vector_cosine_ops`) 인덱스 생성, public 스키마 쓰기 0건.
> 상세는 WORKLOG 2026-08-11 "pgvector 벡터 저장소 구축·적재·검증 완료" 절.

**벡터DB = Qdrant로 확정(2026-08-05, 사용자 결정)** ~~(2026-08-11 무효 — 위 상자 참고)~~: pgvector(Postgres 확장) 방식은
폐기한다 — 정형 DB는 §0 요구사항②상 "외부 서비스"라 komir 팀이 확장 설치 권한을
갖는다는 보장이 없다는 리스크가 있었다(적대적 검증에서 지적됨). Qdrant는 반대로
**komir이 직접 podman으로 기동·소유**하는 구성요소로 만들어 이 리스크를 원천 제거한다
(§7). `doc_chunk.chunk_id`가 Qdrant 포인트 ID와 동일한 값을 쓰는 조인 키 — 청크
텍스트·메타는 Postgres(`doc_chunk`), 임베딩 벡터는 Qdrant, 검색 시 두 곳을 조회해
기존 `rag/ragkit/retrieve.py`의 RRF 융합 로직 그대로 결합한다(§5).

## 5. 수집→ETL→검색 설계 (2026-08-06 재정의 — §0-1 DMZ/in-house 분리 반영)

요구사항 ⑥·⑦(RAG·Report 둘 다 비정형+정형 동시 사용)에 대한 구체 설계. 8/5안은
"수집부터 검색까지 한 존에서 돈다"는 전제였는데, §0-1에서 확인된 대로 **수집(DMZ)과
가공·검색(in-house)이 물리적으로 분리**된다 — 아래는 그 경계를 반영해 다시 짠 흐름이다.

### 5-1. DMZ — 수집(대부분 변경 없음, 드라이버 스크립트만 리팩터 필요)

`dmz/geo_collectors/`·`dmz/msr_collectors/`(구 `engine/geo/collectors`·
`engine/mineral_supply_risk/msr/collectors`, 2026-08-06 물리 이동 완료)가 그대로 이 역할.
LLM 호출 없음, 원본 파일(csv/pdf/hwp/docx/xlsx/xls 등)을 로컬 다운로드 후 in-house로
전달하면 역할 종료. **직접 코드 확인(2026-08-06)**: `dmz/msr_collectors/customs_api.py`의
`collect()`는 이미 `sink` 콜백으로 fetch/load가 분리돼 있어 그 자체는 DB에 결합돼
있지 않다 — 즉시 DB에 쓰는 지점은 collectors가 아니라 `inhouse/mineral_supply_risk/
scripts/backfill_customs_monthly.py`·`collect_annual_bycountry.py`가 정의하는 `_sink` 콜백
(collect 호출과 **같은 프로세스**에서 DB upsert)이다. DMZ 분리 리팩터 대상은
"collectors 자체"가 아니라 **이 드라이버 스크립트들**(§8에 정정 반영) — DMZ 쪽
드라이버는 `sink=<로컬 파일 저장>`으로, in-house 쪽 별도 로더가 그 파일을 읽어
`_sink`가 하던 DB upsert를 대신하도록 쪼개면 된다.

**수집 스케줄(2026-08-06 확정)**: 소스 성격별 차등 주기 — GKG/GDELT는 1시간마다,
거래소재고 등 시장데이터는 4시간마다, 관세청·ECOS·Comtrade 등 저빈도 통계 API는
일 1회, MOFCOM 등 정책공고류는 주 1회(기존 검증된 주기 유지), GACC 등 반차단
소스는 주 1회 이하로 신중하게. airgap 전달은 전 Tier 공통 매일 새벽 1시. 상세
표·근거는 `목표아키텍처_DMZ_inhouse_흐름_260806.md` §2-3, `.env` 변수는 §3 참고.

### 5-2. 망연계 — 감사 게이트웨이 (komir 빌드 대상 아님)

단방향 자동 네트워크 경로, 중간에 보안감사 SDK/솔루션이 데이터 감사(CDR 등) 후 전달.
komir 쪽에서 이 구간에 대해 아는 건 "인터페이스 지점"뿐 — 감사 게이트웨이 자체의
구현·배포는 이 문서 범위 밖(§7에 연동 지점만 표기).

### 5-3. in-house ingestion — 공용 LLM ETL 엔진 (신규 통합 설계)

> **경로 이관(2026-08-27)**: 이 절에서 `inhouse/services/ingestion/…`으로 적힌 코드는 전부
> `inhouse/ingest/`로 옮겨 독립 패키지가 됐다(`parsers/`·`pipeline.py`는 그대로,
> 빌더는 `ingest/okf/`·`ingest/pageindex/`·`ingest/vectorize/` 하위). 같은 날
> `rag/ragkit/{pdf_extract,build_pgvector_index}.py`와 `mineral_supply_risk`의 파일 추출기
> 4종(`pdf_extract_restricted`·`ingest_reports`·`extract_woodmac_xls`·`hwp_extract`)도
> `ingest/extract/`·`ingest/vectorize/`로 합류. 아래 본문의 옛 경로 표기는 그 시점 기록이라
> 갱신하지 않았다 — 현재 구조·실행법은 `inhouse/ingest/README.md`가 정본.

기존 8/5안은 `inhouse/services/ingestion/parsers/*`(포맷별 파서)가 텍스트+표를 마크다운으로
정규화한 뒤 `inhouse/rag/ragkit`의 `chunk.py`에 태우는 **RAG 전용** 경로였다. 8/6 대화에서
이걸 **진단/예측 모델의 비정형 피처 파이프라인(`inhouse/geo`의 LLM 추출 엔진)과
합치기로** 했다 — 같은 원문을 두 번 파싱/두 번 LLM 호출하지 않고, **한 번의 ETL
패스에서 두 산출물을 동시에** 낸다.

**갱신 스케줄(2026-08-06 확정)**: 이 ingestion(정형+비정형+RAG 인덱스 전부)은 **매주
일요일** 트리거 — 지정학위기지수는 그 안에서 갱신, 수급진단모델은 그 직후 체이닝(같은
일요일), 12개월 예측은 매월 첫째주 일요일만. 스케줄은 `.env`(`INGESTION_SCHEDULE_CRON`
등, §3)로 주입하고 서비스 재시작으로 반영 — 상세 표·"매월 첫째주" 스냅샷 처리 로직은
`documents/산출물/2026-W32_0803-0809/목표아키텍처_DMZ_inhouse_흐름_260806.md` §2-2 참고.

- **입력**: DMZ에서 감사 통과 후 전달된 원본 파일(csv/pdf/hwp/docx/xlsx/xls 등) +
  GDELT/GKG 뉴스 원문.
- **처리**: `inhouse/services/ingestion/parsers/*`(포맷 정규화) → LLM 추출(기존
  `inhouse/geo/extract.py`류 로직 재사용) → **두 갈래로 기록**:
  1. **geo-OKF**(기존, 변경 없음): `metrics/`·`events/`·`issues/`·`index/` — 지정학
     위기지수·진단/예측 모델의 numeric 피처용 소량 파생 지식층. `inhouse/data_lake/
     semi_structure/okf/`(구 `geo_data/okf/`) 실물 확인 결과 `sources/*.md`는 원문
     포인터+메타데이터뿐(원문 본문 없음,
     `n_chars`도 발췌 길이일 뿐) — 애초에 RAG용으로 쓰게 설계되지 않았음.
  2. **문서-OKF**(신규): 원문 텍스트 전체 + 섹션/표 구조를 보존하는 별도 OKF 계열.
     geo-OKF와 같은 컨벤션(개념ID=파일경로, YAML 프론트매터)을 따르되 내용은
     "포인터"가 아니라 "본문". **Qdrant 청킹**과 **PageIndex 트리**가 공통으로 이
     문서-OKF를 소스로 삼는다.
  - 두 산출물 모두 상위 data-lake의 비정형 저장소로 들어간다는 게 사용자의 현재
    구상(§0-1, "OKF 유지가 좋지 않을까") — 저장소 자체는 아직 미확정.
- **정형 결과**: 같은 ETL 패스에서 나온 정형 값(수치·표 데이터)은 RDB(§0-1, 개발단계
  Oracle)에 적재 — RAG 정형 피처, 진단/예측 모델 피처가 공용으로 여기서 로딩.

> **실측 노트(2026-08-10)**: 위 "포맷 정규화" 단계의 PDF 처리 부분을 먼저
> `opendataloader-pdf`(오프라인 동작, Markdown/JSON 출력)로 단독 검증했다(0807
> 발주처 제공자료 반영 작업, `documents/산출물/2026-W33_0810-0816/
> 발주처_0807_제공자료_반영계획_260810.md` §4 참고) — 아직 LLM 추출·geo-OKF/문서-OKF
> 이원화까지 통합한 건 아니고, PDF→마크다운(표 구조 보존) 단계만 별도로 뗀
> `inhouse/mineral_supply_risk/scripts/pdf_extract_restricted.py`·
> `inhouse/rag/ragkit/pdf_extract.py`로 선행 적용. 문서 유형에 따라 텍스트 추출률
> 편차가 크다는 게 확인됨(HWP발 정기간행물=양호, 차트·스캔 위주 디자인 보고서=거의
> 0) — **처음엔 opendataloader-pdf 자체 hybrid AI 모드(SmolVLM 백엔드 서버 필요)가
> 유일한 해법이라 오판했으나, `inhouse/geo/extractors.py`가 2026-07-07부터 이미
> 같은 문제(GKG 스캔본 PDF)를 pypdf→OCR(easyocr, CPU, 디스크캐시) 폴백으로 풀어놓은
> 걸 뒤늦게 발견** — 새 백엔드 없이 그 검증된 체인을 `extract_with_fallback()`으로
> 떼어 재사용했다(§5-3의 "포맷 정규화"가 문서 유형과 무관하게 커버되는 셈 —
> hybrid AI 모드는 여전히 안 씀, 아래 항목은 그 미채택 옵션 설명으로 유지).

### 5-4. in-house 검색 — 3개 도구, RAG·Report 공유

RAG 챗봇과 Report 생성기가 **동일한 3개 조회 도구**를 쓴다(사용자 확인, 8/6) —
`inhouse/services/shared/retrieval/`에 한 번만 구현:

1. **RDB 정형 조회**(`structured.py`): 템플릿 질의 방식 권장(안전) — 자주 묻는 질문
   패턴을 사전 정의된 파라미터화 SQL로 매핑, LLM은 "어떤 템플릿+파라미터"만 판단.
   자유형 NL→SQL은 검증 없이는 위험(운영 DB 직접 노출) — 필요성이 실제로 확인되면
   추가 검토.
2. **VectorDB 조회**(Qdrant, 확정): 문서-OKF를 청킹해 dense 임베딩, 기존
   `rag/ragkit/retrieve.py`의 RRF 융합 로직 재사용(BM25 파트너는 §4의 `doc_chunk`
   전문검색 — 벤더가 Oracle이면 Oracle Text로, Postgres면 tsvector로, 미확정 상태
   그대로 열어둠).
3. **PageIndex 조회**(확정): 문서-OKF의 원문 구조에서 만든 목차/섹션
   트리를 LLM이 타고 들어가며 탐색 — 벡터 유사도만으로 답하기 어려운 대량·구조화된
   보고서(WoodMac/Argus/USGS 등)를 보완하는 목적. 온톨로지 방식은 배제됨. 채택 자체는
   확정, 백킹 스토어 등 구현 세부만 미정.

**호출 패턴은 서비스마다 다르다**: RAG 챗봇은 매 턴 LLM이 세 도구 중 무엇을 쓸지
동적으로 판단(에이전트형 tool-use). Report 생성기는 템플릿 섹션마다 필요한 도구가
정적으로 정해질 가능성이 높음(§6) — 도구 구현은 공유하되 "언제 무엇을 부르는가"의
결정 로직은 공유하지 않는다.

## 6. Report 생성기 설계

- **템플릿**: jinja2, 광종×주기(주간/월간)별 템플릿을 `inhouse/services/report_gen/app/templates/`에
  둔다(발주처 산출물 documents/산출물/ 문서들의 구조를 1차 템플릿 소스로 역산).
- **데이터 조립**: §5-4의 3개 공용 도구(RDB/VectorDB/PageIndex)를 그대로 재사용해
  템플릿의 각 섹션 플레이스홀더를 채운다 — Report와 RAG가 검색 계층을 공유(중복
  구현 금지). 섹션→도구 매핑은 정적(예: "지표 요약" 섹션→RDB 고정 쿼리, "최근 동향"
  섹션→PageIndex/VectorDB 검색)일 가능성이 높음 — RAG처럼 매 턴 동적으로 도구를
  고르는 구조는 아닐 것으로 예상(§5-4).
- **주기 저장(요구사항 ⑧)**: `inhouse/services/report_gen/app/scheduler.py`(APScheduler, cron)가
  주기 실행 → `generator.py` 호출 → 결과를 `out_report`(§4 TEXT 확장판)에 `dbio.write_df`로
  적재. 수동 트리거용 API(`POST /reports/{template}/generate`)도 병행 제공(주기 대기 없이
  즉시 필요할 때).

## 7. Airgap·podman 배포 전략

> **범위 축소(§0-1, 2026-08-06)**: 아래 podman-compose 구성은 **in-house 존만**의
> 것이다. DMZ의 수집기(`dmz/geo_collectors/`, `dmz/msr_collectors/` — 2026-08-06
> 물리 이동 완료, 구 `engine/geo/collectors`·`engine/mineral_supply_risk/msr/collectors`)는
> 별도 시스템에 별도로 배포되며(컨테이너 여부 포함 형태 미정), 이 compose 파일에
> 포함되지 않는다. 망연계 감사 게이트웨이는 komir이 만들지 않는 외부 보안 인프라 —
> DMZ→in-house 경계에 "파일이 감사를 통과해 들어오는 지점"이 있다는 것만 ingestion
> 설계(§5-3)에 전제로 반영한다.

- 이미지는 **연결망에서 1회 빌드**(`inhouse/deploy/airgap/build_images.sh`) → `podman save`로
  tar 아카이브화 → 물리 반입 → airgap 환경에서 `podman load`. LLM/임베딩 서버·DB는
  이미지에 포함하지 않고 **항상 외부 서비스**(§0 ②, `.env`로만 연결) — 이미지 자체는
  가볍고 airgap 환경 요구사항(내부 네트워크 반입 규정)에 맞음.
- 기존 `geo/Dockerfile`의 `host.docker.internal:host-gateway` 패턴(호스트측 로컬
  LLM 접속)을 그대로 재사용 — airgap 환경에서 LLM 서버가 같은 호스트 또는 사설망
  내 별도 서버에 있는 두 경우 모두 커버.
- 임베딩 모델(`multilingual-e5-small`, 로컬 실행)은 가중치를 이미지 빌드 시점에
  **미리 다운로드해 이미지에 포함**(런타임 인터넷 접근 불가 전제) — 모델 자체가
  작아(수백MB) airgap 이미지 크기 부담이 크지 않음.
- `podman-compose.yml`(airgap 운영 정본)은 3개 서비스(`commodity-api`/`rag-chat`/
  `report-gen`)를 각각 독립 기동, DB·LLM 접속정보는 전부 `env_file: [.env]`로 주입 —
  서비스 간 결합 없음(하나 재시작해도 나머지 무영향). **`docker-compose.yml`**(2026-08-05
  추가, 로컬 개발·테스트 편의용)이 구성 동일하게 병존 — `build.dockerfile` vs
  `build.containerfile` 표기 차이만 있고 그 외 완전히 동일(§2). 수정 시 두 파일 다
  반영할 것(자동 생성 없음, 설계 단계 스코프).
- **Qdrant**(2026-08-05 추기): 유일하게 komir이 직접 소유·기동하는 인프라 컴포넌트
  (그 외엔 전부 §0 요구사항②대로 외부 서비스) — 공식 이미지(`qdrant/qdrant`)를
  연결망에서 `podman pull` 후 `save_images.sh`가 다른 3개 이미지와 함께 tar로
  묶는다(직접 build 대상 아님, 이미 완성된 이미지를 그대로 반입). `podman-compose.yml`에
  볼륨 마운트로 데이터 영속화 필요(재기동 시 인덱스 유실 방지).
  **airgap 필수 설정**: Qdrant는 기본적으로 익명 사용량 텔레메트리를 외부로 전송한다
  (`QDRANT__TELEMETRY_DISABLED=true` 환경변수로 꺼야 함) — 임베딩 모델의 HuggingFace
  오프라인 모드 설정(`HF_HUB_OFFLINE=1`/`TRANSFORMERS_OFFLINE=1`, 이것도 이번에 함께
  명시)과 같은 종류의 "airgap이라고 믿었는데 실은 조용히 접속을 시도하는" 함정 — 두
  값 다 `inhouse/deploy/.env.example`·서비스 `Containerfile`에 명시할 것.
- **opendataloader-pdf**(2026-08-10 추기, §5-3 문서-OKF 파서의 PDF 처리 후보):
  Java 11+ 필요한 CLI(pip `opendataloader-pdf`가 JAR을 감싼 얇은 래퍼) — 기본 모드는
  임베딩 모델과 같은 패턴으로 **오프라인·로컬 완결**(클라우드 전송 없음, airgap
  적합, 2026-08-10 실측 확인). 이미지에 JRE 11+ 포함 필요. **주의**: hybrid AI
  OCR 모드(스캔·차트 위주 PDF용)는 별도 로컬 백엔드 서버(SmolVLM 기반, GPU 불요)가
  필요해 모델 가중치를 이미지 빌드 시점에 미리 받아둬야 함 — 기본 모드보다 무거운
  선택지라 이번엔 채택하지 않음(§5-3 아래 실측 노트 참고).

## 8. 단계별 실행 순서 (다음 세션 제안)

0. **(신규, §0-1, 2026-08-06 적대적 검증으로 대상 정정)** `dmz/msr_collectors` 자체가
   아니라 **`inhouse/mineral_supply_risk/scripts/backfill_customs_monthly.py`·
   `collect_annual_bycountry.py`(및 `cron_collect_feeds.sh`가 실제로 구동하는 다른
   드라이버 스크립트 전수 확인 필요)**의 "fetch(collect 호출)"와 "load(`_sink` 콜백의
   DB upsert)"를 분리하는 리팩터 — DMZ/in-house 분리 전제조건. `dmz/msr_collectors/
   customs_api.py`의 `collect()` 자체는 이미 `sink` 콜백으로 fetch/load가 분리돼 있어
   손댈 필요 없음. 성공 기준: 분리 후에도 기존 주간/월간 cron 체인이 동일 산출(같은
   `fact_*` 행 수·값)을 내는지 회귀 확인.
1. `inhouse/mineral_supply_risk/db/dbio.py`(§1 표의 `apply_schema` 버그, 2026-08-06
   `dmz`/`inhouse` 분리 후 경로 — **주의**: `inhouse/data_lake/db/`는 별개 디렉토리로
   `schema_addendum_v2.sql`·`minerals.duckdb`만 담고 있음, §2 참고)의 `apply_schema`
   버그 수정(1줄) — RDB 이관의 최소 전제조건.
2. `inhouse/data_lake/db/schema_addendum_v2.sql` 실제 적용 스크립트 작성+로컬
   Postgres(podman)로 스모크 테스트(DuckDB 원본 스키마와 나란히 비교, 데이터 이관 없이
   스키마만 우선) — `txt_tsv` GENERATED 컬럼이 DuckDB에서 실패하는지 이 시점에 확인.
   로컬 Qdrant(podman)도 같이 띄워 `QDRANT_COLLECTION` 생성(차원 384, 코사인 거리)
   스모크 테스트 병행.
3. `inhouse/services/commodity_api` — `inhouse/dashboards/streamlit_app.py`의 로직
   (§1 표) 이식, FastAPI 라우터화. 이게 가장 낮은 리스크(신규 알고리즘 없음, 이미
   검증된 함수 재사용).
4. `inhouse/services/rag_chat` — 세션/히스토리 테이블+스트리밍부터(구조는 명확), 정형
   리트리버는 템플릿 질의 방식으로 최소 구현.
5. `inhouse/services/report_gen` — commodity_api·rag_chat이 자리잡은 뒤 마지막(의존성
   가장 큼).
6. `inhouse/deploy/` podman-compose 통합 기동 테스트(로컬 Postgres+로컬 LLM 서버로
   airgap 시뮬레이션).
7. ~~(Phase 2, §2-1 트리거 조건 충족 후) `engine/` 통합 마이그레이션~~ — **2026-08-05
   같은 날 트리거 조건(1~6단계 완료) 미충족 상태에서 사용자 위험 감수 재확정으로
   앞당겨 실행됨**(§2-1). 이 문서의 나머지 서비스 코드 경로 표기는 실행 전 기준으로
   남아있는 곳이 있을 수 있음 — 실제 구현 착수 시 `engine/` 접두사 기준으로 확인할 것.

각 단계는 CLAUDE.md §4 원칙대로 **검증 가능한 성공 기준**을 먼저 정의하고 착수한다
(예: 3단계 성공 기준 = 기존 Streamlit 데모와 API 응답값이 동일 광종·동일 시점에서
수치 일치, 7단계 성공 기준 = 이관 후 첫 주간 cron 체인 완주+정본 DB 갱신 확인).
