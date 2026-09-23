"""AC28~30/39~41 메타데이터 대조 재현용 읽기 전용 스크립트.

실행:
  PYTHONPATH=inhouse python3 documents/산출물/2026-W39_0921-0927/acceptance_cycle3/terra_metadata_evidence_260923.py
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import yaml

from common.config import get_settings
from common.db import pg_connect
from ingest.paths import get_paths
from rag_core.retrieval.dense_pg import dense_search_pg
from rag_core.retrieval.pageindex import find_documents


REPO = Path(__file__).resolve().parents[4]
FIXTURES = REPO / "inhouse/rag_chat/tests/acceptance_fixtures.json"
OKF_ROOT = get_paths().okf_documents
TREE_ROOT = get_paths().pageindex_trees


def okf_body(path: Path) -> str:
    return path.read_text(encoding="utf-8").split("---\n", 2)[2].lstrip("\n")


def rank_for(doc_id: str, hits: list[dict]) -> tuple[int, float] | None:
    for rank, hit in enumerate(hits, 1):
        if hit["doc_id"] == doc_id:
            return rank, hit["score"]
    return None


def main() -> None:
    fixtures = json.loads(FIXTURES.read_text(encoding="utf-8"))
    rows = [
        ("AC28", fixtures["AC28"]["resource"], "조달청보고서/2009년_1월_로이터_비철금속_가격_전망_자료_2.md", fixtures["AC28"]["okf_fact"]),
        ("AC29", fixtures["AC29"]["resource"], fixtures["AC29"]["okf_path"], fixtures["AC29"]["okf_fact"]),
        ("AC30", fixtures["AC30"]["resource"], fixtures["AC30"]["okf_path"], fixtures["AC30"]["okf_fact"]),
        ("AC39", fixtures["AC39"]["resource"], fixtures["AC39"]["okf_path"], fixtures["AC39"]["okf_fact"]),
    ]
    rows.extend((f"AC41-{i}", item["resource"], item["okf_path"], item["fact"])
                for i, item in enumerate(fixtures["AC41"]["documents"], 1))

    print("[source -> extracted text -> OKF -> tree]")
    tree_by_okf = {}
    for path in TREE_ROOT.rglob("*.tree.json"):
        tree = json.loads(path.read_text(encoding="utf-8"))
        tree_by_okf[tree.get("okf_path")] = tree
    for case, resource, rel, fact in rows:
        okf = OKF_ROOT / rel
        body = okf_body(okf)
        tree = tree_by_okf[rel]
        extract_group = "usgs" if case == "AC39" else "mines" if case == "AC30" else "jodalcheong"
        extract_path = get_paths().processing / extract_group / "texts" / f"{tree['doc_id']}.txt"
        print(json.dumps({
            "case": case, "original_exists": (REPO / resource).is_file(),
            "extract_text_path": str(extract_path.relative_to(REPO)),
            "extract_text_chars": len(extract_path.read_text(encoding="utf-8")),
            "okf_path": rel, "okf_body_chars": len(body), "fact_in_okf": fact in body,
            "doc_id": tree.get("doc_id"), "tree_document_date": tree.get("document_date"),
            "tree_minerals": tree.get("minerals"), "tree_keywords": tree.get("content_keywords"),
            "tree_okf_body_sha256": tree.get("okf_body_sha256"),
        }, ensure_ascii=False, sort_keys=True))

    print("[pgvector rows]")
    schema = get_settings().PG_SCHEMA
    con = pg_connect()
    try:
        with con.cursor() as cur:
            for case, resource, _rel, _fact in rows:
                cur.execute(
                    f"SELECT doc_id, count(*), min(pub_date), max(pub_date) "
                    f"FROM {schema}.doc_chunk WHERE source_path=%s GROUP BY doc_id ORDER BY doc_id",
                    (resource,),
                )
                print(case, cur.fetchall())
    finally:
        con.close()

    print("[AC29 PageIndex rank simulation]")
    query, target_id = "LME Seminar 니켈", fixtures["AC29"]["doc_id"]
    print("before", rank_for(target_id, find_documents(query, limit=10000)))
    with tempfile.TemporaryDirectory() as temp_dir:
        copied_root = Path(temp_dir)
        for source in TREE_ROOT.rglob("*.tree.json"):
            dest = copied_root / source.relative_to(TREE_ROOT)
            dest.parent.mkdir(parents=True, exist_ok=True)
            if source.name == "1019_LME_Seminar에서_발표한_품목별_동향_및_전망.tree.json":
                tree = json.loads(source.read_text(encoding="utf-8"))
                tree["minerals"] = ["구리", "니켈"]
                dest.write_text(json.dumps(tree, ensure_ascii=False), encoding="utf-8")
            else:
                dest.symlink_to(source)
        print("after", rank_for(target_id, find_documents(query, limit=10000, trees_root=copied_root)))

    print("[AC39 dense top10 exact fact]")
    fact = fixtures["AC39"]["okf_fact"]
    for hit in dense_search_pg(fixtures["AC39"]["query"], k=10, _allow_fallback=False):
        print(json.dumps({"rank": hit.dense_rank, "doc_id": hit.doc_id,
                           "source_path": hit.source_path, "fact_present": fact in hit.text},
                          ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
