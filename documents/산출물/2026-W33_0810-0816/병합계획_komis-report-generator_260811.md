# komis-report-generator-main → komir 병합 계획 (초안, 2026-08-11)

> 실행 전 검토용. 아직 파일 이동/복사/수정은 하지 않았음. 아래 결정 3건에 대한
> 답을 받은 뒤 실행에 들어간다.

## 0. 먼저 기대치 정정

"RAG 및 report 생성 관련 구현 일부가 있다"는 원 요청과 달리, 실제로 코드를
읽어보면:
- **완성되어 실제로 동작하는 것**: 43개 KOMIS 서비스 페이지·필터를 추천해주는
  LangGraph 챗봇(`search/`) 뿐. FastAPI 앱(`api/app.py`)에 유일하게 연결된
  기능이기도 하다.
- **RAG(벡터검색) 요소**: 코드는 있지만(`vector_index/`, `llm_tools/`) 자체
  README가 "챗봇 그래프에 아직 등록 안 됨"이라 명시 — 미배선 상태.
- **리포트(수치 분석) 생성**: `analysis/scaffold.py`의 실제 분석 로직이
  `analysis=None`을 반환하는 스텁 — DB 조회(`data_sources/database.py`)만
  실물이고 "리포트 생성"이라 부를 결과물은 아직 없다.

즉 가져올 수 있는 건 "완성된 RAG/리포트 시스템"이 아니라 **개별 컴포넌트**다.
komir 쪽 `inhouse/services/{rag_chat,report_gen,ingestion}/`도 전부
`raise NotImplementedError` 스켈레톤이라, 이번 작업은 스텁↔부분구현을
맞추는 조립에 가깝다.

## 1. 확인된 사실

- 외부 저장소는 git이 아님(스냅샷 export, 전체 mtime 2026-08-11 11:11 동일) —
  머지가 아니라 "특정 시점 코드를 복사해오는 이관"으로 취급해야 함.
- `pyproject.toml`은 `requires-python = ">=3.13"`, `uv` 관리. 다만
  `search/graph.py`·`vector_index/service.py`·`analysis/scaffold.py`·
  `api/app.py` 4개 핵심 파일을 로컬 python3.10으로 `py_compile` 검증 →
  전부 통과(3.13 전용 문법 없음, python3.13 자체는 이 머신에 설치돼있지
  않아 실행까지는 확인 못 함). 즉 "3.10에서 절대 못 돌린다"는 아니지만,
  선언된 최소버전과 komir의 나머지 코드(python3.10 관례)가 다르다는 사실은
  남는다.
- 이 외부 저장소의 `analysis/data_sources/database.py`가 **komir가 8/10에
  postgres에서 발견한 것과 정확히 같은 9개 `ko_*` 테이블**(KO_MNRL_PRC 등)을
  조회한다 — 같은 `komis_demo` DB를 보는 게 거의 확실. 전부 SELECT(읽기)만
  하고 쓰기는 없음 → **"public 스키마는 건드리지 않는다" 원칙에 위배되지
  않음**(단순 참고사항, 걱정할 부분 아님).
- `ai_*` 17개 테이블(다른 팀 소유로 확인됨)은 이 저장소 코드 어디에도
  등장하지 않음 — 이 저장소와는 무관한, 제3의 팀 작업으로 보임.

## 2. 서브패키지별 실태와 제안

| 서브패키지 | 실태 | 제안 |
|---|---|---|
| `search/` | 실물, 유일하게 API에 배선됨. LangGraph 기반 페이지/필터 추천 챗봇(SQLite 세션) | **범위 질문**(결정①) — komir가 설계한 "생성형AI 챗봇"(질의응답 RAG)과 다른 기능(페이지 내비게이션 추천)이라 그대로 흡수해도 되는지 확인 필요 |
| `document_ingestion/` | 실물. PDF/HWP 파싱, 중복제거, 유료출처(WoodMac·Argus·AsianMetal 등) 차단 정책 | komir `inhouse/services/ingestion/parsers/`의 스텁을 채울 후보. 단 **komir는 오늘(8/10) opendataloader-pdf+OCR폴백으로 이미 자체 PDF ETL을 만들었음** — 같은 자리를 두 파이프라인이 놓고 경쟁하게 됨(결정③) |
| `vector_index/` | 실물이나 자기 repo에서도 미배선(기본 compose에 없음, GPU 필요한 `experimental-rag` 프로파일에만). Qdrant+TEI 임베딩 | komir `ragkit`(BM25+dense, 산출물 문서 2,830문항 검색평가 이미 완료)과 동일 자리 경쟁(결정③). TEI 서버 방식도 komir가 이미 계획한 로컬 e5-small와 다름 |
| `llm_tools/` | 실물 5/8 도구, 자기 챗봇 그래프에도 미등록 | CONTAINER_ARCHITECTURE.md §5-4가 설계한 "RDB/VectorDB/PageIndex 3개 공용 도구" 개념과 겹침 — 채택 시 그 설계에 맞춰 재배선 필요 |
| `analysis/` | `data_sources/database.py`(실물, postgres 직접 조회)는 유용. `scaffold.py`(실제 분석)는 스텁 | DB 조회 부분만 참고 가치 있음. "리포트 생성기 완성본"은 아님 — 기대치 낮춰서 부분 채용 |
| `api/` | 실물 FastAPI, 그러나 search만 등록 | 그대로 별도 서비스로 두거나, komir `commodity_api`/`rag_chat` 설계에 맞춰 재구성 필요 |

## 3. 결정이 필요한 사항 (3건)

**① `search/`(페이지·필터 추천 챗봇)를 이번 과업 산출물 ⑥(생성형AI챗봇)
범위에 포함할지** — CONTAINER_ARCHITECTURE.md가 설계한 RAG 질의응답
챗봇과는 목적이 다른 기능(웹사이트 내비게이션 추천)이라, 발주 범위에
들어가는 게 맞는지는 코드로 판단할 수 없음.

**② 편입 형태: 서비스 단위 vs 코드 이식**
- (추천) **서비스 단위**: 외부 저장소를 자체 pyproject/uv/런타임을 가진
  독립 배포 단위로 그대로 두고, API로만 연동. komir 자체 설계(§7: 서비스별
  독립 컨테이너, 코드 공유 없음)와 맞고, 외부 repo의 기존 테스트(185개
  통과 확인됨)를 그대로 보존하며, python 버전·uv vs pip 마찰을 원천
  회피함.
- (대안) 코드 이식: `inhouse/services/*` 스텁에 로직을 직접 옮겨 붙이는
  방식. python3.10 호환은 위 py_compile 검증상 가능성 있어 보이나, DB
  접근 방식(psycopg 직접 vs komir의 `dbio.py` 어댑터)·패키지 관리 방식이
  달라 이식 과정에서 상당한 재작성이 필요함.

**③ 같은 자리를 두고 경쟁하는 두 구현 중 정본 지정**
- PDF 파싱: komir가 오늘 만든 `opendataloader-pdf + easyocr 폴백`
  (0807 자료 55+4건 검증완료) vs 외부 repo의 `document_ingestion`
  (pymupdf/pyhwp 기반, 유료출처 차단 정책 포함).
- 벡터검색: komir `ragkit`(BM25+dense, 검색평가 완료·운영 중) vs 외부
  `vector_index`(Qdrant+TEI, 자기 repo에서도 미가동).
- 두 축 모두 komir 쪽이 이미 검증·가동 중이므로, **기본적으로 komir
  구현을 정본으로 유지**하고 외부 repo에서는 "유료출처 차단 정책"처럼
  komir에 없는 부분만 부분 채용하는 방향을 제안. 다른 판단이 있으면
  알려달라.

## 4. 위 결정 이후 실행 순서(예정)

1. ②를 "서비스 단위"로 결정 시: 외부 저장소를 `inhouse/services/` 하위에
   출처·스냅샷 시점을 기록한 형태로 그대로 옮기고, `docker-compose`에
   서비스로 등록, `api/app.py`가 참조하는 postgres 접속정보를
   `inhouse/.env`의 `PG_*` 값(5433, `mineral_risk` 스키마 — `public`은
   절대 안 건드림)에 맞춰 조정.
2. ①에서 `search/`가 범위 포함으로 결정되면 그대로 유지, 제외로 결정되면
   해당 서비스는 komir 배포에서 뺀다.
3. ③에서 정본이 확정되면 CONTAINER_ARCHITECTURE.md §5-4/§6/§7에 최종
   구성을 반영.
4. `document_ingestion/source_policy.py`의 유료출처 차단 로직만 komir
   RAG ingest(`ragkit/ingest.py`)로 이식 검토(별도 소규모 작업, 결정과
   무관하게 가치 있어 보임).
