from inhouse.rag_core.ragkit.action_results import RetrievalResult, classify_item


def test_foreach_item_failures_are_retained_and_summary_is_partial():
    result = RetrievalResult(action_plan=None, evidence=[])
    result.item_results = {
        ("NI", "price"): classify_item(key=("NI", "price"), value=16_000),
        ("W", "price"): classify_item(key=("W", "price"), failure_reason="ambiguous"),
        ("LI", "price"): classify_item(key=("LI", "price"), failure_reason="no_data"),
    }
    assert result.outcome == "PARTIAL"
    assert result.item_results[("W", "price")].status == "NEEDS_SELECTION"
    assert result.item_results[("LI", "price")].status == "DATA_UNAVAILABLE"


def test_all_failed_items_are_not_success():
    result = RetrievalResult(action_plan=None)
    result.item_results = {
        ("W", "price"): classify_item(key=("W", "price"), failure_reason="ambiguous"),
        ("LI", "price"): classify_item(key=("LI", "price"), failure_reason="source_unavailable"),
    }
    assert result.outcome == "FAILED"
