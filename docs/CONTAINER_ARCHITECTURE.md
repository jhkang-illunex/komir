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
| 벡터DB | **Qdrant로 확정**(2026-08-05 추기) — pgvector(Postgres 확장) 방식 폐기. 정형 RDB(Postgres)와 달리 Qdrant는 **komir이 직접 도커/podman으로 기동·소유**(LLM·정형DB처럼 외부서비스 아님) — §4·§5·§7 |

및 사용자 원 요구사항 8개(요약): ①airgap+podman 배포 ②LLM/embedding·DB는 외부서비스,
.env로 접속정보만 ③3대 아웃풋(광종 리스트·RAG·Report) ④RAG-챗봇 연동(user_id·
session_id·히스토리) ⑤챗봇 스트리밍 ⑥RAG는 비정형(pdf/hwp/docx/doc/xlsx/xls/csv)+
정형(RDB) 둘 다 ⑦Report도 비정형+정형 기반 템플릿 작성 ⑧Report는 RDB에 주기적 저장.

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
└── docs/CONTAINER_ARCHITECTURE.md  # 본 문서
```

## 2-1. `engine/` 통합 마이그레이션 — **실행 완료(2026-08-05, 같은 날 후속)**

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
# ── DB(외부 서비스, 필수) ──
MSR_DB=postgresql+psycopg2://user:pw@host:5432/minerals   # 정형 팩트·마트·out_* 전체
                                                            # (기존 DuckDB 경로 대체)
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
QDRANT_URL=http://qdrant:6333       # deploy/podman-compose.yml 내부 서비스명 기본값
QDRANT_COLLECTION=doc_chunks

# ── 챗봇 서비스 ──
CHAT_SESSION_TTL_DAYS=90           # 세션 히스토리 보존기간
CHAT_STREAM_CHUNK_MS=50            # SSE 청크 전송 간격(선택)

# ── 리포트 스케줄러 ──
REPORT_SCHEDULE_CRON="0 6 * * MON" # 매주 월요일 06:00(예시)
REPORT_TEMPLATE_DIR=/app/templates
```

## 4. DB 스키마 확장안 (`db/schema_addendum_v2.sql`, 설계만 — 미적용)

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

**벡터DB = Qdrant로 확정(2026-08-05, 사용자 결정)**: pgvector(Postgres 확장) 방식은
폐기한다 — 정형 DB는 §0 요구사항②상 "외부 서비스"라 komir 팀이 확장 설치 권한을
갖는다는 보장이 없다는 리스크가 있었다(적대적 검증에서 지적됨). Qdrant는 반대로
**komir이 직접 podman으로 기동·소유**하는 구성요소로 만들어 이 리스크를 원천 제거한다
(§7). `doc_chunk.chunk_id`가 Qdrant 포인트 ID와 동일한 값을 쓰는 조인 키 — 청크
텍스트·메타는 Postgres(`doc_chunk`), 임베딩 벡터는 Qdrant, 검색 시 두 곳을 조회해
기존 `rag/ragkit/retrieve.py`의 RRF 융합 로직 그대로 결합한다(§5).

## 5. RAG "정형+비정형 동시 활용" 설계

요구사항 ⑥·⑦(RAG·Report 둘 다 비정형+정형 동시 사용)에 대한 구체 설계:

- **비정형 경로**: `rag/ragkit`(하이브리드 BM25+dense, RRF) 그대로 재사용하되 **저장소가
  둘로 나뉜다**(2026-08-05 Qdrant 결정 반영) — dense 임베딩은 **Qdrant**(컬렉션
  `QDRANT_COLLECTION`, 포인트 ID=`doc_chunk.chunk_id`), BM25 텍스트는 **Postgres
  `doc_chunk.txt_tsv`**(§4). 검색 시 두 조회 결과를 `rag/ragkit/retrieve.py`의 기존
  RRF 융합 함수에 그대로 넣는다 — **융합 로직 자체는 무변경**, 데이터 소스만 교체.
  대상 코퍼스는 `documents/산출물/`에서 실제 원천 포맷(pdf/hwp/docx/doc/xlsx/xls/csv)
  까지 확장. 포맷별 파서(`services/ingestion/parsers/`)가 **텍스트+표를 마크다운으로
  정규화**한 뒤 기존 `chunk.py`(헤딩 기반 청킹)에 그대로 태운다 — 청킹·임베딩 로직
  재구현 없음. hwp는 airgap 제약상 순수 파이썬 파서(예: `pyhwp` 계열, 인터넷 접속
  없이 사전 설치) 필요 — LibreOffice headless 변환 경로는 무거워서 컨테이너 이미지
  크기 문제, 1차는 경량 파서만, 실패율 높으면 2차로 검토.
- **정형 경로(신규, `structured.py`)**: 두 방식 중 하나를 구현 단계에서 선택 —
  1) **템플릿 질의**(권장, 안전): 자주 묻는 질문 패턴(현재 등급? 12개월 예측? 최근
     위기지수?)을 사전 정의된 파라미터화 SQL로 매핑, LLM은 "어떤 템플릿+파라미터"만
     판단(함수 호출/툴콜 방식) — `out_diagnosis_alert`·`out_import_forecast`·
     `geo_index`를 직접 조회, SQL 인젝션·환각 리스크 낮음.
  2) **자유형 NL→SQL**: LLM이 임의 SQL을 생성 — 유연하지만 검증 없이는 위험(운영
     DB 직접 노출). 하려면 읽기전용 계정+쿼리 화이트리스트(SELECT만, 특정 스키마만)
     필수.
  **권고**: 1차는 ①(템플릿 질의)만 구현, ②는 필요성이 실제로 확인되면 추가.
- **응답 조립**: `generate.py`(기존)에 정형 결과를 "표 형태로 직렬화한 컨텍스트 블록"으로
  얹어 동일한 인용강제 프롬프트에 흘려보낸다 — 별도 생성 파이프라인 불필요.

## 6. Report 생성기 설계

- **템플릿**: jinja2, 광종×주기(주간/월간)별 템플릿을 `services/report_gen/app/templates/`에
  둔다(발주처 산출물 documents/산출물/ 문서들의 구조를 1차 템플릿 소스로 역산).
- **데이터 조립**: RAG의 구조화 리트리버(§5)+비정형 리트리버를 그대로 재사용해 템플릿의
  각 섹션 플레이스홀더를 채운다 — Report와 RAG가 검색 계층을 공유(중복 구현 금지).
- **주기 저장(요구사항 ⑧)**: `services/report_gen/app/scheduler.py`(APScheduler, cron)가
  주기 실행 → `generator.py` 호출 → 결과를 `out_report`(§4 TEXT 확장판)에 `dbio.write_df`로
  적재. 수동 트리거용 API(`POST /reports/{template}/generate`)도 병행 제공(주기 대기 없이
  즉시 필요할 때).

## 7. Airgap·podman 배포 전략

- 이미지는 **연결망에서 1회 빌드**(`deploy/airgap/build_images.sh`) → `podman save`로
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
  값 다 `deploy/.env.example`·서비스 `Containerfile`에 명시할 것.

## 8. 단계별 실행 순서 (다음 세션 제안)

1. `db/dbio.py`의 `apply_schema` 버그 수정(1줄) — Postgres 이관의 최소 전제조건.
2. `db/schema_addendum_v2.sql` 실제 적용 스크립트 작성+로컬 Postgres(podman)로 스모크
   테스트(DuckDB 원본 스키마와 나란히 비교, 데이터 이관 없이 스키마만 우선) — `txt_tsv`
   GENERATED 컬럼이 DuckDB에서 실패하는지 이 시점에 확인. 로컬 Qdrant(podman)도 같이
   띄워 `QDRANT_COLLECTION` 생성(차원 384, 코사인 거리) 스모크 테스트 병행.
3. `services/commodity_api` — `dashboards/streamlit_app.py`의 로직(§1 표) 이식, FastAPI
   라우터화. 이게 가장 낮은 리스크(신규 알고리즘 없음, 이미 검증된 함수 재사용).
4. `services/rag_chat` — 세션/히스토리 테이블+스트리밍부터(구조는 명확), 정형 리트리버는
   템플릿 질의 방식으로 최소 구현.
5. `services/report_gen` — commodity_api·rag_chat이 자리잡은 뒤 마지막(의존성 가장 큼).
6. `deploy/` podman-compose 통합 기동 테스트(로컬 Postgres+로컬 LLM 서버로 airgap 시뮬레이션).
7. ~~(Phase 2, §2-1 트리거 조건 충족 후) `engine/` 통합 마이그레이션~~ — **2026-08-05
   같은 날 트리거 조건(1~6단계 완료) 미충족 상태에서 사용자 위험 감수 재확정으로
   앞당겨 실행됨**(§2-1). 이 문서의 나머지 서비스 코드 경로 표기는 실행 전 기준으로
   남아있는 곳이 있을 수 있음 — 실제 구현 착수 시 `engine/` 접두사 기준으로 확인할 것.

각 단계는 CLAUDE.md §4 원칙대로 **검증 가능한 성공 기준**을 먼저 정의하고 착수한다
(예: 3단계 성공 기준 = 기존 Streamlit 데모와 API 응답값이 동일 광종·동일 시점에서
수치 일치, 7단계 성공 기준 = 이관 후 첫 주간 cron 체인 완주+정본 DB 갱신 확인).
