# ingest — 파일 기반 보고서 정제·색인 패키지

파일로 들어오는 보고서(PDF/HWP/XLS/md/docx)를 **정제(추출) → 문서-OKF → PageIndex 트리 →
pgvector 임베딩**까지 태우는 ETL 전용 패키지. 2026-08-27에 흩어져 있던 모듈을 한곳으로
모아 독립시켰다(아래 "출처"). 서빙 레이어(`services/`)·챗봇(`rag/ragkit`)과는 **런타임
의존이 한 방향**이다 — 이 패키지가 `rag.ragkit.{ingest,chunk,embed}`·`services.shared.
{db,config,pageindex_client}`·`geo.extractors`를 import하고, 반대 방향 import는 없다
(검색·챗봇 코드는 이 패키지가 만든 **산출물 파일/테이블**만 읽는다).

```
ingest/
├─ pipeline.py          # run_extraction(): 해시 dedup·재사용·원자적 쓰기·매니페스트 (라이브러리)
├─ models.py            # DocumentRecord/ExtractionManifest pydantic 계약
├─ source_policy.py     # 유료 출처(WoodMac·Argus·AsianMetal) 차단 정책
├─ parsers/             # 포맷별 파서 → 마크다운 정규화 (pdf: geo.extractors 3단 폴백, hwp: pyhwp)
├─ extract/             # 원본 파일 → md/parquet 정제 스크립트(입력 소스별 1파일)
│  ├─ pdf_extract_shareable.py   # 외부공개 가능 PDF(zip) → pdf_extract/shareable/  (RAG 코퍼스 편입)
│  ├─ pdf_extract_restricted.py  # 0807 비축월보 → pdf_extract/restricted_diagnosis_only/ (★RAG 금지)
│  ├─ ingest_reports.py          # 폴더 일괄 텍스트화(pypdf, 표 미보존 — 레거시)
│  ├─ extract_woodmac_xls.py     # WoodMac 워크북(xls) → long 시계열 parquet
│  └─ hwp_extract.py             # HWP 5.0 평문 추출(OLE 직접 파싱, ingest_reports 전용)
├─ okf/build_okf_documents.py        # documents/산출물 + USGS·조달청·Argus PDF → okf_documents/
├─ pageindex/build_pageindex_trees.py # okf_documents/ → pageindex_trees/*.tree.json (LLM 요약 선택)
└─ vectorize/
   ├─ build_pgvector_index.py       # documents/산출물·외부자료 → mineral_risk.doc_chunk (전량 재적재)
   ├─ build_pgvector_okf.py         # okf_documents/{USGS,조달청,Argus} → doc_chunk (src 단위 재적재)
   └─ backfill_doc_chunk_pub_date.py # doc_chunk.pub_date 백필(title 정규식)
```

## 실행 — 항상 `cwd=inhouse/`에서 `python -m ingest.<sub>.<module>`

```bash
cd komir/inhouse

# 1) 원본 정제
python -m ingest.extract.pdf_extract_shareable          # 외부공개 PDF → shareable/
python -m ingest.extract.pdf_extract_restricted         # 0807 비축월보 → restricted_diagnosis_only/
python -m ingest.extract.extract_woodmac_xls '<glob>' out.parquet
python -m ingest.extract.ingest_reports <root> out.parquet [--zips]

# 2) 문서-OKF (대용량 PDF 갈래는 내부에서 ingest.pipeline.run_extraction 호출)
python -m ingest.okf.build_okf_documents --what all      # artifacts|usgs|jodalcheong|argus|all

# 3) PageIndex 트리 (LLM 요약은 .env LLM_BASE_URL — 호스트 셸에선 env로 덮어쓸 것)
LLM_BASE_URL=http://localhost:52302/v1 python -m ingest.pageindex.build_pageindex_trees --limit 10
python -m ingest.pageindex.build_pageindex_trees --no-summary   # LLM 없이 구조만

# 4) pgvector 적재
python -m ingest.vectorize.build_pgvector_index          # documents/산출물 (DELETE 전량 후 재적재)
python -m ingest.vectorize.build_pgvector_okf            # OKF 대용량 갈래 (자기 src만 재적재)
python -m ingest.vectorize.backfill_doc_chunk_pub_date --dry-run
```

산출물 위치는 전부 `inhouse/data_lake/semi_structure/{pdf_extract,okf_documents,pageindex_trees}/`
(gitignore) + Postgres `mineral_risk.doc_chunk` — 이동 전과 **동일**(경로·테이블·스키마 불변,
이번 재구성은 코드 위치만 바꿨다).

## 지켜야 할 불변식
- **restricted 분리**: `extract/pdf_extract_restricted.py`의 산출물(`restricted_diagnosis_only/`)은
  발주처 명시로 진단모델 개발 전용 — `rag/`·`okf/`·`vectorize/` 어디에서도 그 경로를 소스로
  추가하지 말 것(`grep -rn restricted_diagnosis_only inhouse/rag inhouse/ingest` 결과가
  restricted 스크립트 자신뿐이어야 정상).
- **유료 출처**: `source_policy.py`가 기본 차단. `allow_paid_sources=True`는 Argus 내부 전용
  인덱스(`okf/build_okf_documents.py --what argus`)에서만 켠다(2026-08-12 사용자 확인).
- **doc_chunk writer 2개**: `build_pgvector_index.py`는 테이블 전량 DELETE, `build_pgvector_okf.py`는
  자기 `src`만 DELETE — 실행 순서는 index → okf(반대로 돌리면 okf 적재분이 날아감).
- **geo.extractors 재사용**: PDF 폴백 체인은 `inhouse/geo/extractors.py`가 정본(2026-07-07 검증).
  페이지 상한은 `PDF_MAXPAGES`/`OCR_MAXPAGES` env로, `build_okf_documents.py`가 import 전에
  setdefault(500/60) — 이 순서를 바꾸지 말 것(extractors가 import 시점에 읽음).

## 컨테이너
`services/rag_chat/Containerfile`·`services/report_gen/Containerfile`이 `COPY ingest ./ingest`로
이 패키지를 통째로 싣는다(런타임 import는 현재 없고 공통 모듈 동봉 목적).

독립 ingestion 컨테이너(§5-3 주간 스케줄 트리거)는 2026-08-27 구현 완료 —
`ingest/Containerfile`(빌드 컨텍스트 `inhouse/`)·`ingest/entrypoint.sh`·
`ingest/cron_ingest_weekly.sh`, `deploy/{docker,podman}-compose.yml`의 `ingestion` 서비스.

- **WORKDIR가 `/app`이 아니라 `/komir/inhouse`**: `okf/pageindex/vectorize` 모듈은
  `parents[2]`로, `extract` 모듈·`rag/ragkit/ingest.py`는 `parents[3]`+`"inhouse"`로
  경로를 찾는데, 소스트리에서만 둘이 우연히 일치한다. `/app` 평면 배치로 COPY하면
  후자가 존재하지 않는 `/inhouse`를 가리켜 `load_documents()`가 조용히 빈 결과를
  내고, `build_pgvector_index`의 전량 재적재가 코퍼스를 지워버린다(2026-08-27 실제
  사고 — `vectorize/build_pgvector_{index,okf}.py`의 "재발 방지 가드" 참고). 소스트리
  상대구조를 그대로 미러링해 해결.
- **cron 데몬은 supercronic**(Debian cron 아님) — 전통 cron은 자식 잡에 `env_file`
  주입 환경(`PG_DSN`·`INGEST_TRIGGERED_BY` 등)을 전달하지 않는다.
- **⚠ supercronic PID 1 함정(2026-08-27 실측)**: supercronic이 컨테이너 PID 1로
  직접 실행되면(entrypoint.sh가 `exec`로 자리를 넘김) 볼륨 마운트가 있는 조건에서
  내장 프로세스 reaping이 `Failed to fork exec: no such file or directory`로 즉시
  죽는다. `deploy/{docker,podman}-compose.yml`의 `init: true`(컨테이너 내장 tini를
  PID 1로 둠)로 우회 — 이 옵션을 빼면 컨테이너가 재시작 루프에 빠진다.
- 필요한 COPY는 `ingest/`·`geo/{__init__,extractors}.py`·`rag/ragkit/`·
  `services/shared/`(평탄화 안 함, `services.shared.*` 완전경로 import 그대로 보존)·
  `mineral_supply_risk/db/`·`data_lake/db/schema_pgvector.sql`(`requirements.txt` 참고,
  `sqlalchemy`가 한때 빠져 있던 실측 함정도 그 파일에 기록됨).
- 볼륨 마운트(다른 3개 서비스엔 없음): `documents/`(원본, ro)·
  `data_lake/semi_structure/`(산출물, rw).
- 스케줄은 `.env`의 `INGESTION_SCHEDULE_CRON`(기존 예약 변수, 새 변수 안 만듦).
  주간 체인 순서: `pdf_extract_shareable → pdf_extract_restricted → build_okf_documents
  --what all → (LLM 응답 시)build_pageindex_trees → build_pgvector_index →
  build_pgvector_okf → backfill_doc_chunk_pub_date`(`cron_ingest_weekly.sh` 참고).
  `ingest_reports`·`extract_woodmac_xls`는 위치인자 필요·ad-hoc 소스라 체인 밖(수동 실행).

## 출처(2026-08-27 이동 전 위치, `git log --follow`로 이력 추적 가능)
| 지금 | 이전 |
|---|---|
| `pipeline.py` `models.py` `source_policy.py` `parsers/` | `services/ingestion/` (2026-08-11 komis-report-generator 이식본) |
| `okf/build_okf_documents.py` `pageindex/build_pageindex_trees.py` | `services/ingestion/` |
| `vectorize/build_pgvector_okf.py` `vectorize/backfill_doc_chunk_pub_date.py` | `services/ingestion/` |
| `vectorize/build_pgvector_index.py` | `rag/ragkit/build_pgvector_index.py` |
| `extract/pdf_extract_shareable.py` | `rag/ragkit/pdf_extract.py` |
| `extract/pdf_extract_restricted.py` `extract/ingest_reports.py` `extract/extract_woodmac_xls.py` | `mineral_supply_risk/scripts/` |
| `extract/hwp_extract.py` | `mineral_supply_risk/msr/utils/hwp_extract.py` |

남겨 둔 것(의도적): `geo/okf.py`(geo-OKF, `python -m geo all`의 한 단계 — 문서-OKF와 다른 계열),
`rag/ragkit/{ingest,chunk,embed,tokenize_ko}.py`(rag_chat 컨테이너 런타임 의존 라이브러리),
`rag/ragkit/build_index.py`(레거시 DuckDB 인덱스), `services/shared/pageindex_client.py`+
`pageindex_vendor/`(검색 쪽과 공유하는 래퍼).
