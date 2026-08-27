# -*- coding: utf-8 -*-
"""documents/산출물 -> PostgreSQL(komis_demo) `mineral_risk.doc_chunk` pgvector 적재.

build_index.py(DuckDB)와 **병렬 구조**다 — 로딩(ingest.load_documents)·청킹
(chunk.chunk_document)·임베딩(embed.encode_passages)은 완전히 같은 코드를 쓰고,
저장소만 DuckDB 대신 Postgres+pgvector다. 기존 rag/index/rag.duckdb는 건드리지
않는다(이번 작업은 추가이지 대체가 아님 — BM25 절반은 여전히 DuckDB FTS).

왜 pgvector인가: 2026-08-11 사용자 결정. komis_demo에 pgvector 0.8.2가 이미
설치돼 있어(실측) Qdrant 컨테이너를 새로 띄울 이유가 없어졌다. 상세는
data_lake/db/schema_pgvector.sql 헤더와 CONTAINER_ARCHITECTURE.md §0·§4.

2026-08-27: rag/ragkit/build_pgvector_index.py에서 inhouse/ingest/vectorize/로 이동
(ETL 전용 스크립트라 서빙 패키지 rag/ragkit에서 분리 — ingest/README.md 참고).
로딩·청킹·임베딩 라이브러리(rag.ragkit.{ingest,chunk,embed})는 rag_chat 컨테이너의
런타임 의존이라 그대로 rag/ragkit에 남겨 두고 여기서 import만 한다.

실행(cwd=inhouse/ — CLAUDE.md §2 표준 실행 관례):
    cd inhouse && python -m ingest.vectorize.build_pgvector_index
    cd inhouse && python -m ingest.vectorize.build_pgvector_index --schema-only
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from collections import Counter
from pathlib import Path

_INHOUSE_ROOT = Path(__file__).resolve().parents[2]
if str(_INHOUSE_ROOT) not in sys.path:
    sys.path.insert(0, str(_INHOUSE_ROOT))

from ingest import status as ingest_status  # noqa: E402
from rag.ragkit.chunk import chunk_document  # noqa: E402
from rag.ragkit.embed import DIM, encode_passages  # noqa: E402
from rag.ragkit.ingest import load_documents  # noqa: E402
from services.shared.config import get_settings  # noqa: E402
from services.shared.db import apply_schema_pg, pg_connect  # noqa: E402
from services.shared.logging_config import configure_logging  # noqa: E402

SCHEMA_SQL = _INHOUSE_ROOT / "data_lake/db/schema_pgvector.sql"

#: 벡터 저장소 구분(§4 addendum의 source_type) — 이 스크립트는 비정형 문서만 넣는다.
SOURCE_TYPE = "unstructured"

_COLUMNS = (
    "chunk_id", "doc_id", "commodity_code", "src", "pub_date", "seq", "txt",
    "source_path", "week", "title", "section_heading", "char_len",
    "source_type", "indexed_at", "embedding",
)


def _vector_literal(vec) -> str:
    """pgvector 텍스트 리터럴. pgvector-python이 없어(airgap, pip 전제 불가)
    파이썬 객체 어댑터를 쓸 수 없으므로 '[v1,v2,...]' 문자열 + ::vector 캐스트로
    넣는다. str(list)의 공백 포맷에 기대지 않고 명시적으로 만든다."""

    return "[" + ",".join(repr(float(x)) for x in vec) + "]"


def _pub_date(doc_date: str):
    """DocRecord.doc_date(YYMMDD, 없으면 "")를 DATE로. 파싱 실패 시 None."""

    if not doc_date or len(doc_date) != 6 or not doc_date.isdigit():
        return None
    try:
        return dt.date(2000 + int(doc_date[:2]), int(doc_date[2:4]), int(doc_date[4:6]))
    except ValueError:
        return None


def _src(week: str) -> str:
    """schema_core.doc_chunk.src(VARCHAR(40)) — 원천 구분. EXTRA_ROOTS 문서는
    week가 "외부자료:<라벨>" 형태(ingest.py)라 접두사로 구분된다."""

    return week.split(":", 1)[0] if ":" in week else "documents/산출물"


def build(schema_only: bool = False, run: "ingest_status.RunHandle | None" = None) -> int:
    settings = get_settings()
    schema = settings.PG_SCHEMA  # 항상 mineral_risk — public에는 절대 쓰지 않는다
    n_stmt = apply_schema_pg(str(SCHEMA_SQL))
    print(f"스키마 적용 완료: {SCHEMA_SQL.name} ({n_stmt} statements) -> {schema}.doc_chunk")
    if schema_only:
        return 0

    docs = load_documents()
    all_chunks = []
    for d in docs:
        all_chunks.extend((d, c) for c in chunk_document(d))
    print(f"문서 {len(docs)}건, 청크 {len(all_chunks)}개 — 임베딩 계산 중(e5-small, {DIM}차원)...")

    vectors = encode_passages([c.text for _, c in all_chunks])

    now = dt.datetime.now()
    rows = []
    for (d, c), vec in zip(all_chunks, vectors):
        rows.append((
            c.chunk_id, c.doc_id, None, _src(d.week), _pub_date(d.doc_date), c.chunk_order,
            c.text, d.source_path, d.week, d.title, c.section_heading, len(c.text),
            SOURCE_TYPE, now, _vector_literal(vec),
        ))

    # 재발 방지 가드(2026-08-27 실사고): documents/산출물 로딩이 어떤 이유로든
    # 0건이면(예: cwd가 잘못돼 ROOT를 못 찾음 — rag/ragkit/ingest.py의 2026-08-11
    # 버그수정 이력과 같은 종류의 실패) 아래 DELETE가 그대로 실행되고 재적재는
    # 0행이라 결과적으로 전체 코퍼스가 삭제된다(실측: 이 경로로 mineral_risk.
    # doc_chunk 138,825행이 통째로 날아간 사고 발생, 원본 OKF 마크다운이 살아있어
    # 재생성으로 복구). 빈 결과로 기존 데이터를 지우지 않는다 — 명시적으로
    # 비우고 싶으면 이 가드를 우회하지 말고 직접 SQL을 실행할 것.
    if not rows:
        print(f"⚠ 청크 0개 — DELETE/재적재를 건너뜁니다(빈 코퍼스로 기존 "
              f"{schema}.doc_chunk를 지우는 사고 방지). documents/산출물 로딩 경로를 "
              f"먼저 확인할 것(cwd=inhouse/ 인지 등).", flush=True)
        if run is not None:
            run.metrics.update({"docs": len(docs), "chunks": 0, "aborted_empty": True})
        return 0

    from psycopg2.extras import execute_values

    collist = ",".join(_COLUMNS)
    template = "(" + ",".join(["%s"] * (len(_COLUMNS) - 1)) + ",%s::vector)"

    con = pg_connect()
    try:
        with con.cursor() as cur:
            # 자기 갈래(source_type=SOURCE_TYPE)만 DELETE 후 재적재한다 — 예전엔
            # "이 테이블의 유일한 writer"를 전제로 WHERE 없이 전체 DELETE했으나,
            # build_pgvector_okf.py가 나중에 같은 테이블에 별도 갈래(source_type=
            # "okf_report")를 적재하게 되면서 그 전제가 깨졌다(2026-08-27 실사고·
            # main-agent 코드리뷰로 발견: cron 체인 순서(index→okf)로 정합성을
            # 맞추는 방식은 index.py 단독 수동 실행이나 체인 도중 실패 시 OKF
            # 138,825행이 즉시 전부 삭제되고 다음 okf 실행 전까지 복구 안 되는
            # 구멍이 있었다). build_pgvector_okf.py와 동일한 "자기 갈래만" 패턴으로
            # 통일 — 실행 순서·부분실패와 무관하게 항상 안전하다.
            cur.execute(f"DELETE FROM {schema}.doc_chunk WHERE source_type = %s", (SOURCE_TYPE,))
            deleted = cur.rowcount
            execute_values(
                cur, f"INSERT INTO {schema}.doc_chunk ({collist}) VALUES %s",
                rows, template=template, page_size=200,
            )
            cur.execute(f"SELECT count(*) FROM {schema}.doc_chunk WHERE source_type = %s", (SOURCE_TYPE,))
            total = cur.fetchone()[0]
        con.commit()
    finally:
        con.close()

    print(f"적재 완료: {schema}.doc_chunk — 기존 {deleted}행 삭제, {len(rows)}행 삽입, 대상갈래 현재 {total}행")
    if run is not None:
        run.metrics.update({"docs": len(docs), "chunks": len(rows), "deleted": deleted, "total": total})

    # 파일별 청크 수·글자 수 집계 → ingest.source_file/file_stage_status
    chunk_counts: Counter = Counter()
    char_counts: Counter = Counter()
    doc_by_id = {}
    for d, c in all_chunks:
        chunk_counts[d.doc_id] += 1
        char_counts[d.doc_id] += len(c.text)
        doc_by_id[d.doc_id] = d

    status_con = ingest_status.pg_connect_safe()
    try:
        for doc_id, d in doc_by_id.items():
            ingest_status.upsert_source_file(
                doc_id, file_name=Path(d.source_path).name, file_ext=d.ext,
                source_path=d.source_path, source_group=_src(d.week),
                doc_date=_pub_date(d.doc_date), con=status_con,
            )
        ingest_status.bulk_file_stage_status(
            [(doc_id, "success", char_counts[doc_id], chunk_counts[doc_id], None)
             for doc_id in doc_by_id],
            stage="vectorize", con=status_con,
        )
    finally:
        ingest_status.commit_close_safe(status_con)

    return total


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--schema-only", action="store_true", help="DDL만 적용하고 적재는 건너뜀")
    args = ap.parse_args()
    configure_logging()
    with ingest_status.pipeline_run("vectorize.build_pgvector_index", args=vars(args)) as run:
        build(schema_only=args.schema_only, run=run)
