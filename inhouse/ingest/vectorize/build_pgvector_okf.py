# -*- coding: utf-8 -*-
"""문서-OKF(대용량 보고서 갈래: USGS·조달청보고서·Argus) → pgvector 청킹·임베딩.

`build_pgvector_index.py`(같은 디렉토리, documents/산출물 76건, `rag.ragkit.ingest.
load_documents()` 직접 소스)와 나란한 두 번째 적재 경로다 — 합치지 않은 이유:
그 스크립트는 "이 테이블의 유일한 writer"를 전제로 매번 `DELETE FROM doc_chunk`
전체를 지우고 재적재한다(주석에 명시). 이 스크립트가 같은 방식으로 돌면 서로
지웠다 채웠다 하며 상대 적재분을 날린다 — 그래서 이 스크립트는 **자기가 넣은
행만**(`src` 컬럼으로 구분) 지우고 다시 넣는다, 전체 테이블은 건드리지 않는다.

청킹·임베딩 로직(`rag.ragkit.chunk.chunk_document`·`rag.ragkit.embed.
encode_passages`)은 그대로 재사용 — DocRecord를 OKF 파일의 YAML 프론트매터에서
구성해 넘긴다(본문만 청킹 대상, 프론트매터는 제외).

실행(cwd=inhouse/; 2026-08-27 services/ingestion/ → ingest/vectorize/ 이동):
    python -m ingest.vectorize.build_pgvector_okf
    python -m ingest.vectorize.build_pgvector_okf --source-group 조달청보고서
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from collections import Counter
from pathlib import Path

import yaml

_INHOUSE_ROOT = Path(__file__).resolve().parents[2]
if str(_INHOUSE_ROOT) not in sys.path:
    sys.path.insert(0, str(_INHOUSE_ROOT))

from ingest import status as ingest_status  # noqa: E402
from rag.ragkit.chunk import chunk_document  # noqa: E402
from rag.ragkit.embed import DIM, encode_passages  # noqa: E402
from rag.ragkit.ingest import DocRecord  # noqa: E402
from services.shared.db import pg_connect  # noqa: E402
from services.shared.config import get_settings  # noqa: E402

from .build_pgvector_index import _COLUMNS, _vector_literal  # noqa: E402

OKF_DOCUMENTS_ROOT = _INHOUSE_ROOT / "data_lake/semi_structure/okf_documents"

#: 이 스크립트가 다루는 대용량 보고서 갈래. documents/산출물·외부자료는
#: build_pgvector_index.py 소관이라 여기서 건드리지 않는다(중복 임베딩 방지).
SOURCE_GROUPS = ("생산매장량_USGS", "조달청보고서", "Argus_비철금속_일일")

#: schema_pgvector.sql의 doc_chunk.source_type — documents/산출물 쪽("unstructured")과
#: 구분해 어느 파이프라인이 넣었는지 한눈에 알 수 있게 한다.
SOURCE_TYPE = "okf_report"  # source_type VARCHAR(16) — 실측으로 발견(20자 값은 잘림 에러)


def _load_okf_record(path: Path) -> DocRecord:
    """OKF 마크다운 1건(YAML 프론트매터 + 본문) → DocRecord(본문만 raw_text에)."""

    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise ValueError(f"OKF 프론트매터 없음: {path}")
    _, front_raw, body = text.split("---\n", 2)
    front = yaml.safe_load(front_raw) or {}
    return DocRecord(
        doc_id=str(front.get("doc_id", "")).removeprefix("doc_")[:16] or path.stem[:16],
        source_path=str(front.get("resource", "")),
        week=str(front.get("source_group", "")),
        series_key="",
        doc_date="",
        title=str(front.get("title", path.stem)),
        ext=str(front.get("fmt", "pdf")),
        raw_text=body,
    )


def build(
    source_groups: tuple[str, ...] = SOURCE_GROUPS,
    run: "ingest_status.RunHandle | None" = None,
) -> int:
    settings = get_settings()
    schema = settings.PG_SCHEMA  # mineral_risk — public엔 절대 안 씀

    paths: list[Path] = []
    for group in source_groups:
        paths.extend(sorted((OKF_DOCUMENTS_ROOT / group).rglob("*.md")))
    print(f"대상 문서 {len(paths)}건({', '.join(source_groups)})", flush=True)

    all_chunks = []
    for path in paths:
        doc = _load_okf_record(path)
        all_chunks.extend((doc, c) for c in chunk_document(doc))
    print(f"청크 {len(all_chunks)}개 — 임베딩 계산 중(e5-small, {DIM}차원)...", flush=True)

    vectors = encode_passages([c.text for _, c in all_chunks])

    now = dt.datetime.now()
    rows = []
    for (d, c), vec in zip(all_chunks, vectors):
        rows.append((
            c.chunk_id, c.doc_id, None, d.week, None, c.chunk_order,
            c.text, d.source_path, d.week, d.title, c.section_heading, len(c.text),
            SOURCE_TYPE, now, _vector_literal(vec),
        ))

    # 재발 방지 가드(2026-08-27 실사고): OKF 마크다운 로딩이 0건이면(예: cwd가
    # 잘못됐거나 data_lake/semi_structure/okf_documents/가 아직 비어있는 워크트리)
    # 아래 DELETE(자기 src만 지우는 방식이라도)가 그대로 실행되고 재적재는 0행이라
    # 그 갈래(USGS/조달청보고서/Argus)가 통째로 삭제된다(실측: 이 경로로
    # mineral_risk.doc_chunk 138,825행 삭제 사고 발생, 원본이 살아있어 재생성으로
    # 복구). 빈 결과로 기존 데이터를 지우지 않는다.
    if not rows:
        print(f"⚠ 청크 0개 — DELETE/재적재를 건너뜁니다(빈 코퍼스로 기존 "
              f"{schema}.doc_chunk 갈래를 지우는 사고 방지). {OKF_DOCUMENTS_ROOT}/"
              f"{{{','.join(source_groups)}}} 경로부터 확인할 것.", flush=True)
        if run is not None:
            run.metrics.update({"docs": len(paths), "chunks": 0, "aborted_empty": True})
        return 0

    from psycopg2.extras import execute_values

    collist = ",".join(_COLUMNS)
    template = "(" + ",".join(["%s"] * (len(_COLUMNS) - 1)) + ",%s::vector)"

    con = pg_connect()
    try:
        with con.cursor() as cur:
            # 전체 DELETE 금지(build_pgvector_index.py의 documents/산출물 적재분을
            # 지우게 됨) — src(=OKF source_group)로 이 스크립트가 넣은 행만 지운다.
            cur.execute(
                f"DELETE FROM {schema}.doc_chunk WHERE src = ANY(%s)",
                (list(source_groups),),
            )
            deleted = cur.rowcount
            execute_values(
                cur, f"INSERT INTO {schema}.doc_chunk ({collist}) VALUES %s",
                rows, template=template, page_size=200,
            )
            cur.execute(
                f"SELECT count(*) FROM {schema}.doc_chunk WHERE src = ANY(%s)",
                (list(source_groups),),
            )
            total = cur.fetchone()[0]
        con.commit()
    finally:
        con.close()

    print(f"적재 완료: {schema}.doc_chunk — 기존 {deleted}행 삭제, {len(rows)}행 삽입, 대상갈래 현재 {total}행")
    if run is not None:
        run.metrics.update({"docs": len(paths), "chunks": len(rows), "deleted": deleted, "total": total})

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
                doc_id, file_name=Path(d.source_path).name if d.source_path else doc_id,
                file_ext=d.ext, source_path=d.source_path, source_group=d.week, con=status_con,
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
    ap.add_argument("--source-group", action="append", dest="groups", choices=SOURCE_GROUPS)
    args = ap.parse_args()
    with ingest_status.pipeline_run("vectorize.build_pgvector_okf", args=vars(args)) as run:
        build(tuple(args.groups) if args.groups else SOURCE_GROUPS, run=run)
