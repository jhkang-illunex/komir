"""Characterize indicator row adaptation, including legacy permissive cases."""

from copy import deepcopy
from unittest.mock import Mock

import pytest

from inhouse.rag_core.ragkit import live_multihop as live
from inhouse.rag_core.ragkit.action_contract import ActionCall, ActionSlots, Period
from inhouse.rag_core.ragkit.action_results import ActionResult, RetrievalResult
from inhouse.rag_core.ragkit.indicator_result_adapter import (
    canonical_indicator_rows,
    validate_indicator_output,
)
from inhouse.rag_core.ragkit.pipe_runtime import ResultStatus
from inhouse.rag_core.ragkit.semantic_ir import ValueType
from inhouse.rag_core.retrieval.evidence import Evidence


def action(**slots):
    return ActionCall(requirement_id="indicator", action_id="indicator.series",
                      slots=ActionSlots(**{"indicator": "composite_index", **slots}))


def normalize(rows, call=None):
    return canonical_indicator_rows(rows, call or action(),
                                    resolve_field=live._resolve_row_field, numeric=live._numeric)


@pytest.mark.parametrize("raw,expected", [
    ("20260901", "2026-09-01"), (20260901, "2026-09-01"),
    (" 20260901 ", "2026-09-01"), ("20261345", "2026-13-45"),
    (" 2026-09-01 ", " 2026-09-01 "), ("invalid", "invalid"),
    (None, None), ("", ""), (202609, 202609),
])
def test_existing_date_only_reformats_eight_digits(raw, expected):
    row = {"date": raw, "crtr_ymd": "19990101", "value": 1}
    result = normalize([row])[0]
    assert result["date"] == expected
    assert result["crtr_ymd"] == "19990101" and row["date"] == raw


@pytest.mark.parametrize("fields,expected", [
    ({"crtr_ymd": "20260101", "obs_date": "20260201"}, "2026-01-01"),
    ({"crtr_ymd": None, "obs_date": "20260201"}, "2026-02-01"),
    ({"crtr_ymd": "", "obs_date": "20260201"}, ""),
    ({"observed_date": " 2026-03-01 ", "period": "20260401"}, "2026-03-01"),
    ({"period": " 2026-04 "}, "2026-04"),
    ({"crtr_ymd(기준일자)": "20260905"}, "2026-09-05"),
    ({"date(관측일)": "20260905"}, "2026-09-05"),
    ({"year": 2024, "period": "20260905"}, "2024"),
])
def test_alias_date_resolution_priority_and_label_support(fields, expected):
    result = normalize([{**fields, "value": 1}])[0]
    assert result["date"] == expected
    assert all(result[key] == value for key, value in fields.items())


@pytest.mark.parametrize("fields,expected", [
    ({"series": "1,234.5%", "indx": 2, "center": 3}, 1234.5),
    ({"series": "bad", "indx": "2", "center": 3}, 2.0),
    ({"series": None, "indx": "NaN", "center": "3%"}, 3.0),
    ({"series": True, "indx": "Infinity", "center": 0}, 0.0),
    ({"series(label)": "4"}, 4.0), ({"indx(지수)": "5"}, 5.0),
    ({"center(이동평균)": "6"}, 6.0),
    ({"series": "7", "series(label)": "8"}, 7.0),
    ({"series(a)": "7", "series(b)": "8", "indx": "9"}, 9.0),
])
def test_explicit_numeric_aliases_use_first_resolvable_finite_value(fields, expected):
    result = normalize([{**fields, "date": "20260101"}])[0]
    assert result["value"] == expected and type(result["value"]) is float
    assert all(result[key] == value for key, value in fields.items())


@pytest.mark.parametrize("fields", [
    {"arbitrary": 123}, {"index": 123}, {"series": "NaN"}, {"indx": "Infinity"},
    {"series": True, "center": None}, {"series(a)": 1, "series(b)": 2},
])
def test_invalid_or_undeclared_numeric_rows_are_kept_not_repaired(fields):
    rows = [{"date": "20260101", **fields}]
    result = normalize(rows)
    assert len(result) == 1 and "value" not in result[0]
    assert validate_indicator_output(result, action()) == "indicator_output_contract_invalid"
    assert all(result[0][key] == value for key, value in fields.items())


@pytest.mark.parametrize("value", [None, "", "bad", "12.5", "NaN", True, 0])
def test_existing_canonical_value_blocks_alias_conversion(value):
    rows = [{"date": "20260101", "value": value, "series": "999"}]
    result = normalize(rows)
    assert result[0]["value"] is value and result[0]["series"] == "999"


@pytest.mark.parametrize("slot,fields,expected", [
    ("composite_index", {}, {"indicator": "composite_index"}),
    ("supply_stability", {}, {"indicator": "supply_stability"}),
    (None, {}, {}),
    ("composite_index", {"indicator": "external_identity"}, {"indicator": "external_identity"}),
    ("composite_index", {"indicator": None}, {"indicator": None}),
    ("composite_index", {"indicator": ""}, {"indicator": ""}),
])
def test_indicator_default_never_replaces_existing_identity(slot, fields, expected):
    row = {"date": "20260101", "value": 1, **fields}
    result = normalize([row], action(indicator=slot))[0]
    assert {key: value for key, value in result.items() if key == "indicator"} == expected


@pytest.mark.parametrize("changes,valid", [
    ({}, True), ({"value": "12.5"}, True), ({"value": True}, True),
    ({"value": "NaN"}, True), ({"date": "not-a-date"}, True),
    ({"indicator": "different_from_action"}, True), ({"extra": {"kept": 1}}, True),
    ({"value": None}, False), ({"value": "1,234"}, False),
    ({"date": None}, False), ({"date": 20260101}, False),
    ({"indicator": ""}, False), ({"indicator": None}, False), ({"unit": 1}, False),
])
def test_validation_does_not_convert_or_reconcile_rows(changes, valid):
    rows = [{"date": "2026-01-01", "value": 1, "indicator": "composite_index", **changes}]
    before = deepcopy(rows)
    result = validate_indicator_output(rows, action(indicator="market_outlook"))
    assert result == (None if valid else "indicator_output_contract_invalid")
    assert rows == before
    assert type(rows[0]["value"]) is type(before[0]["value"])


def test_empty_and_mixed_rows_preserve_count_order_and_input():
    assert normalize([]) == [] and validate_indicator_output([], action()) is None
    rows = [{"date": "20260201", "series": "2", "nested": {"keep": True}},
            {"date": None, "value": None}, {"date": "20260101", "center": "1"}]
    before = deepcopy(rows)
    result = normalize(rows)
    assert rows == before and len(result) == 3
    assert [row["date"] for row in result] == ["2026-02-01", None, "2026-01-01"]
    assert all(new is not old for new, old in zip(result, rows))
    assert result[0]["nested"] is rows[0]["nested"]
    assert validate_indicator_output(result, action()) == "indicator_output_contract_invalid"


def test_resolver_and_numeric_are_injected_without_changing_strictness():
    resolver, numeric = Mock(wraps=live._resolve_row_field), Mock(wraps=live._numeric)
    rows = [{"crtr_ymd(기준일자)": "20260101", "indx(지수)": "5"}]
    result = canonical_indicator_rows(rows, action(), resolve_field=resolver, numeric=numeric)
    assert result[0]["date"] == "2026-01-01" and result[0]["value"] == 5.0
    assert all(call.kwargs == {"strict": True} for call in resolver.call_args_list)
    numeric.assert_called_once_with("5")


def evidence(text, source="fixture", source_id="physical_source"):
    return Evidence("structured", source, "fixture", text, unit="USD/t",
                    source_id=source_id, action_id="indicator.series")


def raw_result(call, items, *, status="success", action_evidence=None, reason=None):
    item = ActionResult(call.requirement_id, call.action_id, call.slots, status,
                        items if action_evidence is None else action_evidence,
                        warnings=["existing_warning"], failure_reason=reason)
    return RetrievalResult(None, [item], items, ["top_level_warning"])


@pytest.mark.parametrize("column,raw_value,expected", [
    ("series", "123.5", 123.5), ("indx(지수)", "123.5", 123.5),
    ("value", "123.5", "123.5"),
])
def test_raw_success_preserves_typed_metadata_and_evidence(column, raw_value, expected):
    call = action(mineral="니켈", period=Period(kind="latest"))
    item = evidence(f"| crtr_ymd(기준일자) | {column} |\n| --- | --- |\n| 20260901 | {raw_value} |")
    raw = raw_result(call, [item])
    before = deepcopy(raw)
    result = live._typed_from_retrieval(raw, call, input_entities=["니켈"])
    assert result.status == ResultStatus.SUCCESS and result.sufficient
    assert result.result_type == ValueType.TIME_SERIES and result.metric == "indicator"
    assert result.value[0]["value"] == expected and type(result.value[0]["value"]) is type(expected)
    assert result.value[0]["date"] == "2026-09-01" and result.value[0]["indicator"] == "composite_index"
    assert result.entity == ("니켈",) and result.unit == "USD/톤"
    assert result.period == call.slots.period.model_dump(mode="json")
    assert result.evidence == (item,) and result.evidence[0] is item
    assert result.source == ("fixture",) and result.provenance == ("indicator:physical_source",)
    assert result.warnings == ("existing_warning",) and result.failure_reason is None
    assert raw == before


@pytest.mark.parametrize("status,reason,expected_reason", [
    ("success", None, "indicator_output_contract_invalid"),
    ("validation_failed", "internal:details", "retrieval unavailable: validation_failed"),
    ("no_data", None, "retrieval unavailable: no_data"),
    ("source_unavailable", "price_criterion_mapping_missing:details", "price_criterion_mapping_missing"),
])
def test_raw_failure_precedence_keeps_evidence_but_not_success_metadata(status, reason, expected_reason):
    call = action(mineral="니켈")
    item = evidence("| series |\n| --- |\n| 123.5 |")
    raw = raw_result(call, [item], status=status, reason=reason)
    result = live._typed_from_retrieval(raw, call, input_entities=["니켈"])
    assert result.status == ResultStatus.EMPTY and not result.sufficient
    assert result.result_type == ValueType.TIME_SERIES and result.failure_reason == expected_reason
    assert result.value is None and result.evidence == (item,)
    assert result.warnings == ("existing_warning",)
    assert result.source == result.provenance == result.entity == ()
    assert result.metric is None and result.unit is None and result.period is None


@pytest.mark.parametrize("action_has_evidence", [False, True])
def test_action_evidence_precedence_and_raw_evidence_fallback(action_has_evidence):
    call = action()
    top = evidence("| date | series |\n| --- | --- |\n| 20260101 | 1 |", "top", None)
    selected = evidence("| date | series |\n| --- | --- |\n| 20260201 | 2 |", "selected")
    raw = raw_result(call, [top], action_evidence=[selected] if action_has_evidence else [])
    result = live._typed_from_retrieval(raw, call, input_entities=[])
    expected = selected if action_has_evidence else top
    assert result.status == ResultStatus.SUCCESS and result.evidence == (expected,)
    assert result.value[0]["value"] == (2.0 if action_has_evidence else 1.0)
    assert result.source == (expected.source,)
    assert result.provenance == (f"indicator:{expected.source_id or expected.source}",)


@pytest.mark.parametrize("has_action", [False, True])
@pytest.mark.parametrize("has_evidence", [False, True])
def test_empty_rows_keep_legacy_evidence_payload_behavior(has_action, has_evidence):
    call = action()
    items = [evidence("No markdown table.")] if has_evidence else []
    raw = raw_result(call, items) if has_action else RetrievalResult(None, [], items)
    result = live._typed_from_retrieval(raw, call, input_entities=[])
    assert result.result_type == ValueType.TIME_SERIES and result.evidence == tuple(items)
    if has_evidence:
        assert result.status == ResultStatus.SUCCESS and result.value == items
        assert result.metric == "indicator" and result.provenance == ("indicator:physical_source",)
    else:
        assert result.status == ResultStatus.EMPTY and result.value is None
        assert result.failure_reason == ("retrieval unavailable: success" if has_action else "retrieval unavailable: no_data")
    assert result.warnings == (("existing_warning",) if has_action else ())
