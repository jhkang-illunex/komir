from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ingest.pageindex.build_derived_facts import build_all, extract_document_facts
from rag_core.retrieval import document_facts
from rag_core.ragkit.action_contract import extract_action_plan, validate_action_plan


def _write_okf(root: Path, name: str = "2026-04_희소금속월간동향_더프라임.md") -> Path:
    path = root / "희소금속 월간동향" / name
    path.parent.mkdir(parents=True)
    path.write_text(
        "---\n"
        "doc_id: doc-test\n"
        "title: 2026-04_희소금속월간동향_더프라임\n"
        "source_group: 희소금속 월간동향\n"
        "minerals: [리튬]\n"
        "---\n"
        "# 제목\n"
        "2026. 4 리듬(Lithium) 희로류(Rare Earths) 망간(Manganese) 코발트(Cobalt)\n"
        "월간 가격 동향\n"
        "## 시장 주요 이슈\n"
        "광물 가격이 상승했고 공급 제약 우려가 커졌다.\n",
        encoding="utf-8",
    )
    return path


def test_extract_document_facts_keeps_provenance_and_ocr_aliases(tmp_path):
    root = tmp_path / "okf"
    path = _write_okf(root)
    facts = extract_document_facts(path, okf_root=root)
    assert facts["document_month"] == "2026-04"
    assert facts["mineral_list"][:4] == ["리튬", "희토류", "망간", "코발트"]
    assert facts["summary"].startswith("광물 가격이 상승")
    assert facts["facts"][0]["source_span"]["line_start"] >= 1
    assert facts["okf_body_sha256"]


def test_build_and_fetch_document_facts_sidecar(tmp_path):
    okf_root = tmp_path / "okf"
    trees_root = tmp_path / "trees"
    _write_okf(okf_root)
    result = build_all(okf_root=okf_root, trees_root=trees_root)
    assert result == {"candidate_count": 1, "done": 1, "skipped": 0, "stale": 0, "failed": 0}
    evidence, warnings = document_facts.fetch_document_facts_evidence(
        "2026년 4월 희소금속 월간동향 광종 목록", root=trees_root,
    )
    assert not warnings
    assert len(evidence) == 1
    assert "리튬" in evidence[0].text and "희토류" in evidence[0].text


def test_monthly_summary_uses_facts_action():
    plan = extract_action_plan("가장 최근 희소금속 월간 동향의 내용을 요약해줘", llm=None)
    assert plan.actions[0].action_id == "document.facts.retrieve"
    assert validate_action_plan(plan).approved
