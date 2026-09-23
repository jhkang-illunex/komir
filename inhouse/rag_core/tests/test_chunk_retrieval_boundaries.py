from __future__ import annotations

from rag_core.ragkit.chunk import chunk_document
from rag_core.ragkit.ingest import DocRecord


def _doc(text: str) -> DocRecord:
    return DocRecord(
        doc_id="test-document",
        source_path="source",
        week="test",
        series_key="",
        doc_date="",
        title="Test report",
        ext="md",
        raw_text=text,
    )


def test_hwp_bullet_rows_do_not_mix_different_commodities():
    nickel_row = (
        "니 켈 ▪ 추가 하락 전망 ▪ 재고 증가 ▪ 가격 추가 하락 가능성에 무게"
    )
    chunks = chunk_document(
        _doc(
            "# 품목별 전망\n"
            "구 리 ▪ 공급 감소 ▪ 가격 상승 전망\n"
            f"{nickel_row}\n"
            "주 석 ▪ 가격 하락 제한 전망\n"
        )
    )

    matches = [chunk.text for chunk in chunks if "니 켈" in chunk.text]
    assert matches == [nickel_row]
    assert "구 리" not in matches[0]
    assert "주 석" not in matches[0]
    assert "추가 하락 전망" in matches[0]
    assert "가격 추가 하락" in matches[0]


def test_long_english_prose_keeps_fact_sentence_as_its_own_chunk():
    fact = "Estimated world lithium production increased to 290,000 tons in 2025."
    filler = (
        "Mineral statistics provide a consistent historical record for analysts, "
        "policy makers, producers, and consumers around the world. "
    )
    chunks = chunk_document(_doc("# FOREWORD\n" + filler * 850 + fact + " " + filler * 4))

    matches = [chunk.text for chunk in chunks if fact in chunk.text]
    assert matches == [fact]
