# ingest — 파일 기반 보고서 정제·색인 패키지

파일로 들어오는 보고서(PDF/HWP/XLS/md/docx)를 **정제(추출) → 문서-OKF → PageIndex 트리 →
pgvector 임베딩**까지 태우는 ETL 전용 패키지. 2026-08-27에 흩어져 있던 모듈을 한곳으로
모아 독립시켰다(아래 "출처"). 서빙 레이어(`services/`)·챗봇(`rag/ragkit`)과는 **런타임
의존이 한 방향**이다 — 이 패키지가 `rag.ragkit.{ingest,chunk,embed}`·`services.shared.
{db,config,pageindex_client}`·`geo.extractors`를 import하고, 반대 방향 import는 없다
(검색·챗봇 코드는 이 패키지가 만든 **산출물 파일/테이블**만 읽는다).

```
ingest/
├─ paths.py             # ★ 디렉토리 계약(2026-09-16): landing/processing/data_lake — .env INGEST_*_DIR, 미설정=레거시
├─ registry.py          # ★ 소스 그룹 표(키·landing 폴더·레거시 원본·출력명·태그·유료/private 정책·in_all)
├─ run_chain.py         # ★ 체인 진입점(컨테이너 cron·호스트 crontab 공용): 락·로그·단계 순서·실패 처리·prune
├─ prune.py             # ★ landing에서 사라진 원본의 okf/pageindex/doc_chunk 정리(기본 dry-run)
├─ pipeline.py          # run_extraction(): 해시 dedup·재사용·원자적 쓰기·매니페스트 (라이브러리)
├─ models.py            # DocumentRecord/ExtractionManifest pydantic 계약
├─ source_policy.py     # 유료 출처(WoodMac·Argus·AsianMetal) 차단 정책
├─ parsers/             # 포맷별 파서 → 마크다운 정규화 (pdf: geo.extractors 3단 폴백, hwp: pyhwp,
│                         xlsx: openpyxl 시트→마크다운 표 — 2026-09-16 구현)
├─ extract/             # 원본 파일 → md/parquet 정제 스크립트(입력 소스별 1파일)
│  ├─ pdf_extract_shareable.py   # 외부공개 가능 PDF(zip) → pdf_extract/shareable/  (RAG 코퍼스 편입)
│  ├─ pdf_extract_restricted.py  # 0807 비축월보 → pdf_extract/restricted_diagnosis_only/ (★RAG 금지)
│  ├─ ingest_reports.py          # 폴더 일괄 텍스트화(pypdf, 표 미보존 — 레거시)
│  ├─ extract_woodmac_xls.py     # WoodMac 워크북(xls) → long 시계열 parquet
│  └─ hwp_extract.py             # HWP 5.0 평문 추출(OLE 직접 파싱, ingest_reports 전용)
├─ okf/build_okf_documents.py        # documents/산출물 + USGS·조달청·Argus PDF + 광산자료(--what mines) → okf_documents/
├─ pageindex/build_pageindex_trees.py # okf_documents/ → pageindex_trees/*.tree.json (LLM 요약 선택)
└─ vectorize/
   ├─ build_pgvector_index.py       # documents/산출물·외부자료 → mineral_risk.doc_chunk (전량 재적재)
   ├─ build_pgvector_okf.py         # okf_documents/{USGS,조달청,Argus} → doc_chunk (src 단위 재적재)
   └─ backfill_doc_chunk_pub_date.py # doc_chunk.pub_date 백필(title 정규식)
```

## 디렉토리 계약 — landing / processing / data_lake (2026-09-16)

| 단계 | 역할 | .env(호스트 실행) | 컨테이너(compose 고정) | 미설정 시(레거시) |
|---|---|---|---|---|
| **landing** | 처음 데이터가 들어오는 곳(원본, ro). 하위 폴더 = 소스 그룹(`registry.py` `landing_subdir`: `usgs`·`jodalcheong`·`argus`·`mines`·`incoming`·`shareable`·`restricted`) | `INGEST_LANDING_DIR` | `/komir/landing` ← `INGEST_LANDING_HOST_DIR` | 그룹별 기존 위치(`documents/…`, `documents/보고서_2/…`, `nas_document/학습데이터`, `inhouse/incoming`, `documents/0807/*.zip`) |
| **processing** | 작업 중 산출물 — 그룹별 `manifest.json`·`documents.jsonl`·`texts/`, `_ocr_cache(_md)`, `shareable/`, `restricted_diagnosis_only/`, `_logs/`, `_locks/`. 해시 재사용이 매니페스트에 의존하므로 **영속 볼륨** | `INGEST_PROCESSING_DIR` | `/komir/processing` ← `INGEST_PROCESSING_HOST_DIR` | `inhouse/data_lake/semi_structure/pdf_extract` |
| **data_lake** | 정리 완료 — `okf_documents/`(문서-OKF)·`pageindex_trees/`(트리). 검색 계층·rag_chat이 ro로 읽음 | `INGEST_DATA_LAKE_DIR` | `/komir/data_lake` ← `INGEST_DATA_LAKE_HOST_DIR` | `inhouse/data_lake/semi_structure` |

- 경로는 **`ingest/paths.py`만** 안다(okf·pageindex·vectorize·parsers·extract, `rag_core/ragkit/ingest.py`,
  `rag_core/retrieval/pageindex.py`가 전부 여기서 받음). 컨테이너 WORKDIR가 `/komir/inhouse`여야 맞던
  경로 함정(아래 "컨테이너" 절)은 이걸로 사라졌지만 Containerfile은 그대로 둔다(변경 최소).
- 세 값을 비워 두면 2026-09-16 이전 경로와 **완전히 동일**하게 동작한다(`tests/test_paths_registry.py`가
  상수 단위로 검사). 새 레이아웃으로 옮길 때 그룹 폴더명(`out_dirname` = `doc_chunk.src` = 트리
  `source_group`)은 바뀌지 않으므로 기존 색인과 그대로 맞물린다.
- 새 레이아웃 1회 이관(호스트): `pdf_extract/*` → `$INGEST_PROCESSING_DIR/`, `okf_documents`·`pageindex_trees`
  → `$INGEST_DATA_LAKE_DIR/`로 `mv`, 원본은 `$INGEST_LANDING_DIR/<subdir>/`에 복사·마운트. `python -m
  ingest.run_chain --list`로 해석된 경로·그룹 존재 여부를 먼저 확인할 것.
- 그룹 추가 = `registry.py`에 한 줄(코드 함수 아님). `in_all=True`면 주간 체인에 자동 포함되고, 원본
  폴더가 없으면 예외가 아니라 건너뛴다(마운트 안 된 그룹 때문에 체인이 죽지 않게).

### 체인 실행(컨테이너 cron·호스트 crontab 공용)

```bash
cd inhouse
python -m ingest.run_chain --list                   # 해석된 경로·그룹·단계만 출력(변경 없음)
python -m ingest.run_chain                          # 전체: shareable → restricted → okf → pageindex → pgvector_index → pgvector_okf → backfill → prune(dry-run)
python -m ingest.run_chain --steps okf,pageindex    # 일부 단계만(순서는 고정)
python -m ingest.run_chain --prune-apply            # prune 실제 삭제(안전장치: 그룹 50% 초과 거부, landing 없으면 건너뜀)
python -m ingest.run_chain --trigger cron           # 상태 테이블 trigger='cron'(cron 래퍼가 씀)
```
- 락: `processing/_locks/chain.lock`(flock), 로그: `processing/_logs/chain_<시각>.log`(stdout과 동시 기록).
- okf·pgvector_index·pgvector_okf 실패 → 이후 단계 중단(빈 입력으로 기존 데이터를 지우는 사고 방지).
  pageindex는 LLM 미응답 시 `--no-summary`로 구조만 만든다(예전엔 통째로 건너뜀).
- 호스트 crontab: `0 0 * * SUN /path/komir/inhouse/ingest/cron_ingest_weekly.sh`(래퍼가 .env를 읽고
  run_chain 호출) 또는 `docker compose -f deploy/docker-compose.yml run --rm ingestion python3 -m ingest.run_chain --trigger cron`.
  컨테이너 상주형은 기존대로 `INGESTION_SCHEDULE_CRON`(entrypoint.sh → supercronic → run_chain).

## 실행 — 항상 `cwd=inhouse/`에서 `python -m ingest.<sub>.<module>`

```bash
cd komir/inhouse

# 1) 원본 정제
python -m ingest.extract.pdf_extract_shareable          # 외부공개 PDF → shareable/
python -m ingest.extract.pdf_extract_restricted         # 0807 비축월보 → restricted_diagnosis_only/
python -m ingest.extract.extract_woodmac_xls '<glob>' out.parquet
python -m ingest.extract.ingest_reports <root> out.parquet [--zips]

# 2) 문서-OKF (대용량 PDF 갈래는 내부에서 ingest.pipeline.run_extraction 호출)
python -m ingest.okf.build_okf_documents --what all      # artifacts + registry in_all 그룹(원본 없는 그룹은 건너뜀)
python -m ingest.okf.build_okf_documents --what mines    # 그룹 하나(registry 키), --group-root로 원본 루트 덮어쓰기 가능

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

## 광산자료 갈래(2026-09-16, 사용자 지시 "학습데이터 광산 자료를 public 챗봇에서 제공")

- 원본: `<repo>/nas_document/학습데이터/<광종>/`(NAS 심볼릭링크) — 동(구리)·니켈·코발트·리튬·
  우라늄·철광석 6개 폴더, 광산별 생산·매장량 기업 공시(연간보고서·NI 43-101·분기 생산보고·
  Kazatomprom 광산 정리 xlsx 등) PDF 136 + xlsx 18(png 1건은 대상 아님).
- 경로: `pdf_extract/mines/` → `okf_documents/광산자료/<광종>/*.md`(source_group=`광산자료`,
  description·tags·`commodity_hint`에 광종 폴더명) → `pageindex_trees/광산자료/…` →
  `doc_chunk.src='광산자료'`(`build_pgvector_okf.py` SOURCE_GROUPS에 추가됨).
- public 노출: `rag_core/retrieval/access.py`의 `PRIVATE_ONLY_SOURCE_GROUPS`는 Argus뿐이라
  새 갈래는 자동으로 public·private 양쪽에서 검색된다(기업 공시 자료라 라이선스 제한 없음).
- 주간 체인 포함(`registry.py` `in_all=True`): 새 레이아웃에선 `landing/mines/`에 NAS를 마운트하면
  자동으로 돌고, 레거시(호스트)에선 `nas_document/학습데이터` 심볼릭링크를 쓴다. 원본 폴더가 없는
  환경(예: 마운트 안 한 컨테이너)에선 건너뛴다. 수동 실행: `build_okf_documents --what mines` →
  `build_pageindex_trees --pattern 광산자료 --no-summary` → `build_pgvector_okf --source-group 광산자료`.
  워크트리에서 돌렸으면 산출물(`okf_documents/광산자료`·`pageindex_trees/광산자료`·
  `pdf_extract/mines`)을 메인 체크아웃 data_lake로 복사해야 rag_chat 컨테이너(ro 마운트)가
  PageIndex 트리를 본다. doc_chunk는 DB라 즉시 반영.
- `discover_source_files`는 파일을 resolve해 그룹 루트 아래인지 검사하므로 원본 폴더 안에
  다른 곳을 가리키는 심볼릭링크를 두면 "escapes its source group"으로 실패한다(NAS 원본 자체는 통과).

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
- 스케줄은 `.env`의 `INGESTION_SCHEDULE_CRON`(기존 예약 변수, 새 변수 안 만듦). crontab 한 줄은
  `python3 -m ingest.run_chain --trigger cron`(2026-09-16, 단계 순서는 run_chain.py "디렉토리 계약" 절).
  `ingest_reports`·`extract_woodmac_xls`는 위치인자 필요·ad-hoc 소스라 체인 밖(수동 실행).
- 볼륨(2026-09-16): `landing`(ro)·`processing`(rw)·`data_lake`(rw) 3개 — 호스트 경로는 `deploy/.env`의
  `INGEST_*_HOST_DIR`, 컨테이너 안은 `/komir/{landing,processing,data_lake}`(compose environment).
  rag-chat도 `data_lake`를 ro로 마운트하고 `INGEST_DATA_LAKE_DIR`를 받는다.

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
