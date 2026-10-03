"""Freeze trade-country-rank selection and aliasing, not new data validation."""

from copy import deepcopy
from unittest.mock import Mock, patch

import pytest

from inhouse.rag_core.ragkit import live_multihop as live
from inhouse.rag_core.ragkit import trade_rank_result_adapter as adapter
from inhouse.rag_core.ragkit.action_contract import ActionCall, ActionSlots, Period
from inhouse.rag_core.ragkit.action_results import ActionResult, RetrievalResult
from inhouse.rag_core.ragkit.pipe_runtime import ResultStatus
from inhouse.rag_core.ragkit.semantic_ir import ValueType
from inhouse.rag_core.retrieval.evidence import Evidence


METRICS = ("import_amount", "export_amount", "import_weight", "export_weight")


def select(rows):
    return adapter.select_country_rank_rows(rows, resolve_field=live._resolve_row_field)


def canonicalize(rows, metric="import_amount"):
    return adapter.canonicalize_trade_rank_rows(rows, metric, base_column_name=live._base_column_name)


@pytest.mark.parametrize("rows", [[], [{}], [{"country": "A", "total": 10}],
                                  [{"share_percentage": 20}, {"country": "A"}]])
def test_no_ranked_rows_returns_original_list_without_creating_share(rows):
    before = deepcopy(rows)
    assert select(rows) is rows and rows == before


def test_ranked_subset_keeps_order_duplicate_rows_and_row_identity():
    first = {"country": "B", "share_percentage": 2}
    second = {"country": "A", "share_percentage": 99}
    rows = [{"note": "supplement"}, first, {"country": "C"}, second, first]
    before = deepcopy(rows)
    result = select(rows)
    assert result is not rows and result == [first, second, first]
    assert result[0] is first and result[1] is second and result[2] is first
    assert rows == before


@pytest.mark.parametrize("country,share", [
    (None, None), ("", ""), (False, False), (0, 0), ("A", "not-numeric"), ("A", -10),
])
def test_selection_requires_resolved_keys_not_valid_values(country, share):
    row = {"country": country, "share_percentage": share}
    result = select([{}, row])
    assert len(result) == 1 and result[0] is row


@pytest.mark.parametrize("row,accepted", [
    ({"국가명": "A", "비중": 1}, True),
    ({"country_name(label)": "A", "share_pct(percent)": 1}, True),
    ({"country": None, "국가명": "A", "share_percentage": None, "share_pct": 1}, True),
    ({"country_name": "A", "country_name(label)": "B", "share_pct": 1}, True),
    ({"country_name": "A", "국가명": "B", "share_percentage": 1}, False),
    ({"country": "A", "share_pct": 1, "share": 2}, False),
    ({"country(a)": "A", "country(b)": "B", "share_percentage": 1}, False),
    ({"country_extra": "A", "share_percentage": 1}, False),
    ({"COUNTRY": "A", "share_percentage": 1}, False),
    ({"country": "A", "export_share": 1}, False),
    ({"": "A", "share_percentage": 1}, False),
])
def test_shared_strict_resolver_exact_alias_and_ambiguity_behavior(row, accepted):
    anchor = {"country": "anchor", "share_percentage": 100}
    result = select([row, anchor])
    assert result == ([row, anchor] if accepted else [anchor])
    assert result[-1] is anchor


def test_selection_injects_strict_resolver_and_short_circuits_country():
    resolver = Mock(wraps=live._resolve_row_field)
    missing = {"note": "not a country"}
    ranked = {"country": "A", "share_percentage": 1}
    result = adapter.select_country_rank_rows([missing, ranked], resolve_field=resolver)
    assert result == [ranked]
    assert [(call.args[1], call.kwargs) for call in resolver.call_args_list] == [
        ("country", {"strict": True}), ("country", {"strict": True}),
        ("share_percentage", {"strict": True}),
    ]


@pytest.mark.parametrize("metric", METRICS)
@pytest.mark.parametrize("total_key", ["total", "TOTAL", " total (금액) ", "총계(중량)"])
def test_unique_total_maps_to_each_declared_metric_without_numeric_conversion(metric, total_key):
    row = {"country": "A", "share_percentage": "12.3%", total_key: "1,234.50"}
    result = canonicalize([row], metric)[0]
    assert result is not row and result[metric] == "1,234.50"
    assert all(result[key] == value for key, value in row.items())
    assert set(result) == set(row) | {metric} and metric not in row


@pytest.mark.parametrize("metric", METRICS)
@pytest.mark.parametrize("value", [None, "", 0])
def test_existing_canonical_value_including_null_wins_over_total(metric, value):
    row = {metric: value, "total": 999}
    result = canonicalize([row], metric)[0]
    assert result == row and result is not row and result[metric] is value


@pytest.mark.parametrize("row", [
    {}, {"other": 1}, {"subtotal": 1}, {"total_amount": 1}, {"total[USD]": 1},
    {"total": 1, "총계": 1}, {"total(import)": 1, "total(weight)": 2},
    {"TOTAL": 1, " total (same)": 1},
])
def test_absent_or_ambiguous_total_is_not_inferred_even_when_values_equal(row):
    result = canonicalize([row])
    assert result == [row] and result[0] is not row
    assert "import_amount" not in result[0]


@pytest.mark.parametrize("value", [None, "", True, "bad", "NaN"])
def test_unique_total_keeps_invalid_value_without_validation(value):
    result = canonicalize([{"total": value}])
    assert result[0]["import_amount"] is value


@pytest.mark.parametrize("metric", [None, "", " import_amount ", "import_value", "production", 0])
def test_unsupported_metric_is_exact_identity_and_does_not_inspect_columns(metric):
    rows = [{"total": 1, "nested": {"keep": True}}]
    base = Mock(side_effect=AssertionError("unsupported metric inspected"))
    result = adapter.canonicalize_trade_rank_rows(rows, metric, base_column_name=base)
    assert result is rows and result[0] is rows[0]
    base.assert_not_called()


def test_casefold_copy_depth_empty_list_and_base_callback():
    rows = [{"TOTAL (USD)": 1, "nested": {"keep": True}}, {"other": 2}]
    before = deepcopy(rows)
    base = Mock(wraps=live._base_column_name)
    result = adapter.canonicalize_trade_rank_rows(rows, "IMPORT_AMOUNT", base_column_name=base)
    assert result[0]["import_amount"] == 1 and "import_amount" not in result[1]
    assert rows == before and result is not rows
    assert all(new is not old for new, old in zip(result, rows))
    assert result[0]["nested"] is rows[0]["nested"]
    assert [call.args[0] for call in base.call_args_list] == ["TOTAL (USD)", "nested", "other"]
    empty = []
    assert canonicalize(empty) == [] and canonicalize(empty) is not empty


def action(metric="import_amount", action_id="trade.country_rank"):
    return ActionCall(requirement_id="rank", action_id=action_id,
                      slots=ActionSlots(metric=metric, mineral="니켈", period=Period(kind="latest")))


def evidence(text, name="source", source_id="physical"):
    return Evidence("structured", name, "fixture", text, unit="USD/t", source_id=source_id)


def raw_result(call, items, status="success", reason=None, action_evidence=None):
    item = ActionResult(call.requirement_id, call.action_id, call.slots, status,
                        items if action_evidence is None else action_evidence,
                        warnings=["existing_warning"], failure_reason=reason)
    return RetrievalResult(None, [item], items, ["top_level_warning"])


@pytest.mark.parametrize("metric", METRICS)
def test_raw_boundary_selects_then_maps_while_preserving_full_evidence_and_envelope(metric):
    call = action(metric)
    ranked = evidence("| country | share_percentage | total(USD) |\n| --- | --- | --- |\n| B | 1 | 900 |\n| A | 2 | 100 |")
    supplement = evidence("| note | total |\n| --- | --- |\n| extra | 777 |", "supplement", None)
    raw = raw_result(call, [ranked, supplement, ranked])
    before = deepcopy(raw)
    result = live._typed_from_retrieval(raw, call, input_entities=["니켈"])
    assert result.status == ResultStatus.SUCCESS and result.sufficient and result.failure_reason is None
    assert result.result_type == ValueType.COUNTRY_SHARE and result.metric == metric
    assert [row["country"] for row in result.value] == ["B", "A", "B", "A"]
    assert [row[metric] for row in result.value] == ["900", "100", "900", "100"]
    assert [row["share_percentage"] for row in result.value] == ["1", "2", "1", "2"]
    assert all("value" not in row for row in result.value)
    assert result.entity == ("니켈",) and result.unit == "USD/톤"
    assert result.period == call.slots.period.model_dump(mode="json")
    assert result.evidence == (ranked, supplement, ranked) and result.evidence[0] is ranked
    assert result.source == ("source", "supplement")
    assert result.provenance == ("rank:physical", "rank:supplement")
    assert result.warnings == ("existing_warning",) and raw == before


@pytest.mark.parametrize("metric", [None, "import_amount"])
def test_raw_no_ranked_rows_falls_back_without_share_calculation(metric):
    call = action(metric)
    item = evidence("| year | total |\n| --- | --- |\n| 2024 | 100 |")
    result = live._typed_from_retrieval(raw_result(call, [item]), call, input_entities=[])
    assert result.status == ResultStatus.SUCCESS and result.result_type == ValueType.COUNTRY_SHARE
    assert result.value == [{"year": "2024", "total": "100", **({"import_amount": "100"} if metric else {})}]
    assert result.metric == metric and result.evidence == (item,)


@pytest.mark.parametrize("status,reason,expected", [
    ("validation_failed", "internal:private detail", "retrieval unavailable: validation_failed"),
    ("no_data", None, "retrieval unavailable: no_data"),
    ("source_unavailable", None, "retrieval unavailable: source_unavailable"),
    ("validation_failed", "resource_population_conflict:private detail", "resource_population_conflict"),
])
def test_raw_failure_keeps_evidence_warnings_but_not_success_metadata(status, reason, expected):
    call = action()
    item = evidence("| country | share_percentage | total |\n| --- | --- | --- |\n| A | 9 | 100 |")
    result = live._typed_from_retrieval(raw_result(call, [item], status, reason), call, input_entities=["니켈"])
    assert result.status == ResultStatus.EMPTY and not result.sufficient and result.value is None
    assert result.result_type == ValueType.COUNTRY_SHARE and result.failure_reason == expected
    assert result.evidence == (item,) and result.warnings == ("existing_warning",)
    assert result.source == result.provenance == result.entity == ()
    assert result.metric is None and result.unit is None and result.period is None


@pytest.mark.parametrize("action_has_evidence", [False, True])
def test_raw_action_evidence_precedes_top_level_with_empty_fallback(action_has_evidence):
    call = action()
    top = evidence("| total |\n| --- |\n| 1 |", "top", None)
    selected = evidence("| total |\n| --- |\n| 2 |", "selected")
    raw = raw_result(call, [top], action_evidence=[selected] if action_has_evidence else [])
    result = live._typed_from_retrieval(raw, call, input_entities=[])
    expected = selected if action_has_evidence else top
    assert result.status == ResultStatus.SUCCESS and result.evidence == (expected,)
    assert result.value[0]["import_amount"] == ("2" if action_has_evidence else "1")
    assert result.source == (expected.source,)
    assert result.provenance == (f"rank:{expected.source_id or expected.source}",)


@pytest.mark.parametrize("has_evidence", [False, True])
def test_raw_empty_table_and_missing_evidence_keep_existing_status(has_evidence):
    call = action()
    items = [evidence("No markdown table.")] if has_evidence else []
    result = live._typed_from_retrieval(raw_result(call, items), call, input_entities=[])
    assert result.evidence == tuple(items) and result.result_type == ValueType.COUNTRY_SHARE
    if has_evidence:
        assert result.status == ResultStatus.SUCCESS and result.value == items
        assert result.provenance == ("rank:physical",)
    else:
        assert result.status == ResultStatus.EMPTY and result.value is None
        assert result.failure_reason == "retrieval unavailable: success"


@pytest.mark.parametrize("action_id", ["trade.monthly", "document.retrieve"])
def test_non_country_rank_action_never_calls_trade_helpers(action_id):
    call = action(action_id=action_id)
    item = evidence("| country | share_percentage | total |\n| --- | --- | --- |\n| A | 9 | 100 |")
    with patch.object(adapter, "select_country_rank_rows", side_effect=AssertionError("wrong selection gate")) as selection, \
         patch.object(adapter, "canonicalize_trade_rank_rows", side_effect=AssertionError("wrong normalization gate")) as normalization:
        result = live._typed_from_retrieval(raw_result(call, [item]), call, input_entities=[])
    selection.assert_not_called()
    normalization.assert_not_called()
    assert result.status == ResultStatus.SUCCESS
    assert "import_amount" not in result.value[0] and result.value[0]["total"] == "100"
