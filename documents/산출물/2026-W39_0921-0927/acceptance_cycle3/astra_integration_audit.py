"""실제 AC41 정상 대조군에서 한 결함씩 주입하는 독립 읽기 감사."""
from pathlib import Path
import copy
import json
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "inhouse"))
from common.config import get_settings
from common.db import pg_connect
from rag_core.retrieval import pageindex
from rag_chat.tests import acceptance_integrations as target
import psycopg2

trees = pageindex.load_trees()
spec = target.fixture("AC41")
target_ids = {item["doc_id"] for item in spec["documents"]}
results = []


def check(label, wanted, *, tree_data=None, adapter=None, connect=pg_connect):
    status, errors, detail = target.verify_case(
        {"id": "AC41"}, trees=trees if tree_data is None else tree_data,
        pageindex=pageindex if adapter is None else adapter,
        connect=connect, settings=get_settings,
    )
    ids = [item["id"] for item in detail["required_checks"]]
    exact_manifest = ids == list(target.REQUIRED_CHECK_IDS["AC41"]) and len(set(ids)) == len(ids)
    row = {"label": label, "wanted": wanted, "actual": status,
           "accepted": status == wanted and exact_manifest, "manifest_exact": exact_manifest,
           "errors": errors, "checks": detail["required_checks"]}
    results.append(row)
    print(json.dumps(row, ensure_ascii=False))


check("actual_control", "PASS")
stale = copy.deepcopy(trees)
for tree in stale:
    if tree["doc_id"] in target_ids:
        tree["okf_body_sha256"] = "STALE"
check("stale_tree_hash", "FAIL", tree_data=stale)

for key, value in (("resource", "wrong.pdf"), ("okf_path", "wrong.md"),
                   ("line_num", 999999), ("body_line_offset", 999999),
                   ("doc_id", "doc_wrong")):
    def altered_search(*args, _key=key, _value=value, **kwargs):
        return [{**hit, _key: _value} for hit in pageindex.search_nodes(*args, **kwargs)]
    adapter = SimpleNamespace(OKF_DOCUMENTS_ROOT=pageindex.OKF_DOCUMENTS_ROOT,
                              search_nodes=altered_search, read_node_text=pageindex.read_node_text)
    check("wrong_hit_" + key, "FAIL", adapter=adapter)

facts = {item["doc_id"]: item["fact"] for item in spec["documents"]}
adapter = SimpleNamespace(OKF_DOCUMENTS_ROOT=pageindex.OKF_DOCUMENTS_ROOT,
                          search_nodes=pageindex.search_nodes,
                          read_node_text=lambda hit: facts[hit["doc_id"]])
check("forged_fact_only_node_text", "FAIL", adapter=adapter)

original_fetch = target._fetch_chunks
def wrong_chunk(*args, **kwargs):
    status, chunks, error = original_fetch(*args, **kwargs)
    if chunks:
        chunks = [{**chunk, "text": "old unrelated chunk"} for chunk in chunks]
    return status, chunks, error
with patch.object(target, "_fetch_chunks", side_effect=wrong_chunk):
    check("old_chunk_text", "FAIL")

with patch.object(target, "_vector_doc_id", side_effect=lambda value: value):
    check("wrong_full_vector_id", "FAIL")

def unavailable():
    raise psycopg2.OperationalError("independent fixture: database unavailable")
check("db_unavailable_only", "BLOCKED_ENV", connect=unavailable)
check("stale_hash_and_db_unavailable", "FAIL", tree_data=stale, connect=unavailable)

# AC40은 실제 데이터의 FAIL을 정상 대조군으로 사용하지 않는다. 독립 고정 본문으로
# 정확한 node를 제공한 대조군을 먼저 PASS시킨 뒤 각 결함을 한 개씩 주입한다.
with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    okf = root / "fixed.md"
    okf.write_text("---\ndoc_id: doc_control\n---\n\n# Root\nfixed fact\n", encoding="utf-8")
    pinned = dict(resource="source.pdf", doc_id="doc_control", okf_path="fixed.md",
                  query="unchanged query", fact="fixed fact", line_start=2, line_end=2,
                  body_sha256=target._body_sha256(okf))
    base_tree = {**pinned, "body_line_offset": 4, "okf_body_sha256": pinned["body_sha256"],
                 "structure": [{"node_id": "n", "line_num": 1, "nodes": []}]}
    base_hit = {key: base_tree[key] for key in ("resource", "doc_id", "okf_path", "body_line_offset")}
    base_hit.update(node_id="n", line_num=1)
    real_fixture = target.fixture
    for mutation in (None, "tree_sha", "resource", "okf_path", "line_num", "both_offsets", "read_text"):
        tree, hit = copy.deepcopy(base_tree), dict(base_hit)
        if mutation == "tree_sha": tree["okf_body_sha256"] = "STALE"
        if mutation in {"resource", "okf_path"}: hit[mutation] = "wrong"
        if mutation == "line_num": hit["line_num"] = 999999
        if mutation == "both_offsets": tree["body_line_offset"] = hit["body_line_offset"] = 999999
        calls = []
        def search(query, **kwargs):
            calls.append((query, kwargs))
            return [hit]
        page = SimpleNamespace(OKF_DOCUMENTS_ROOT=root, search_nodes=search,
                               read_node_text=lambda _hit: "fixed fact" if mutation == "read_text" else "# Root\nfixed fact")
        with patch.object(target, "fixture", side_effect=lambda cid: pinned if cid == "AC40" else real_fixture(cid)):
            status, errors, detail = target.verify_case({"id": "AC40"}, trees=[tree], pageindex=page,
                                                        connect=pg_connect, settings=get_settings)
        wanted = "PASS" if mutation is None else "FAIL"
        assert calls[0][0] == pinned["query"] and calls[0][1]["doc"] == pinned["doc_id"]
        assert calls[0][1]["node_limit"] == 5
        ids = [row["id"] for row in detail["required_checks"]]
        exact = ids == list(target.REQUIRED_CHECK_IDS["AC40"])
        row = dict(label="AC40_" + str(mutation), actual=status, wanted=wanted,
                   accepted=status == wanted and exact, manifest_exact=exact, errors=errors)
        print(json.dumps(row, ensure_ascii=False))
        results.append(row)

# 실제 원본 정상 대조와 원본별 관계를 깨뜨린 독립 입력을 함께 검사한다.
hwp = target.fixture("AC29")
status, _, _ = target._verify_hwp_original(ROOT / hwp["resource"], hwp)
assert status == "PASS", status
wrong_rows = ["니켈 전망 없음", "구리 니켈과 달리 추가 하락 전망 가격 추가 하락"]
with patch.object(target, "_hwp_text_and_rows", return_value=(" ".join(wrong_rows), wrong_rows, None)):
    status, _, _ = target._verify_hwp_original(Path("unused.hwp"), hwp)
assert status == "FAIL", "other commodity row accepted"
print("HWP actual source PASS; other-commodity fact row FAIL")

excel = target.fixture("AC30")
status, _, _ = target._verify_excel_original(ROOT / excel["resource"], excel)
assert status == "PASS", status
body = target._body_text(Path(pageindex.OKF_DOCUMENTS_ROOT) / excel["okf_path"])
assert target._verify_excel_okf_table(body, excel)[0]
swapped = body.replace("41875", "TEMP_SWAP").replace("303.748134", "41875").replace("TEMP_SWAP", "303.748134")
assert not target._verify_excel_okf_table(swapped, excel)[0]
print("Excel actual source/OKF PASS; same-row column swap FAIL")

from rag_core.retrieval.access import PRIVATE_ONLY_SOURCE_GROUPS
with patch("rag_core.retrieval.dense_pg.dense_search_pg", return_value=[]) as dense:
    target._dense_search(target.fixture("AC39"))
assert dense.call_args.args == (target.fixture("AC39")["query"],)
assert dense.call_args.kwargs == dict(k=10, exclude_src=PRIVATE_ONLY_SOURCE_GROUPS, _allow_fallback=False)
print("actual dense function boundary: fixed query, k=10, public filter, no fallback")

ledger = target._CheckLedger("AC40")
ledger.record(target.REQUIRED_CHECK_IDS["AC40"][0], "PASS")
status, errors, detail = ledger.finish([])
assert status == "FAIL" and len(detail["required_checks"]) == 3
try:
    ledger.record(target.REQUIRED_CHECK_IDS["AC40"][0], "PASS")
except AssertionError:
    print("duplicate required check rejected")
else:
    raise AssertionError("duplicate required check survived")

failed = [row["label"] for row in results if not row["accepted"]]
print(json.dumps({"cases": len(results), "unexpected": failed}, ensure_ascii=False))
assert not failed, failed
