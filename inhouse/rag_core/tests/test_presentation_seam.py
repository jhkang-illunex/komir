"""Characterize the legacy result-to-ChatEvent seam without executing retrieval."""

from copy import deepcopy
from datetime import date

import pytest

from inhouse.rag_core.ragkit import live_multihop as live
from inhouse.rag_core.ragkit.pipe_runtime import ResultStatus, TypedResult
from inhouse.rag_core.ragkit.semantic_ir import ValueType
from inhouse.rag_core.retrieval.evidence import Evidence


class FixedDate(date):
    @classmethod
    def today(cls):
        return cls(2026, 10, 4)


@pytest.fixture(autouse=True)
def fixed_clock(monkeypatch):
    monkeypatch.setattr(live, "date", FixedDate)


def result(value, result_type=ValueType.FACT_SET, **kwargs):
    return TypedResult.success(result_type, value, **kwargs)


def events(value, result_type=ValueType.FACT_SET, **kwargs):
    return live._result_events(result(value, result_type, **kwargs))


def of_type(items, kind):
    return [item.data for item in items if item.type == kind]


def snapshot(value=None, **kwargs):
    return {"mineral": "니켈", "metric": "price", "status": "success",
            "value": {"price": 10} if value is None else value, **kwargs}


def price_events(item, **kwargs):
    return events([item], ValueType.COMPOSITE, **kwargs)


@pytest.mark.parametrize("status", [ResultStatus.ABSTAINED, ResultStatus.EMPTY,
                                   ResultStatus.FAILED, ResultStatus.DEPENDENCY_FAILED])
@pytest.mark.parametrize("reason", [None, "rejected"])
def test_terminal_failure_rows_precede_abstention_without_rejected_citations(status, reason):
    items = [snapshot(status="failed", reason="bad", output="price"),
             snapshot(status="success"), {"metric": "reserves"}, "ignored"]
    emitted = events(items, ValueType.COMPOSITE, status=status, failure_reason=reason,
                     source=("rejected-source",), evidence=("private-evidence",))
    assert [event.type for event in emitted] == ["table", "delta", "done"]
    assert emitted[0].data["block_id"] == "multihop-item-outcomes"
    assert emitted[0].data["columns"] == ["광종", "요청 결과", "상태", "사유"]
    assert emitted[0].data["rows"] == [["니켈", "price", "failed", "bad"],
                                       ["", "reserves", "unknown", "unspecified_failure"]]
    assert emitted[0].data["source_index"] is None
    assert emitted[1].data == {"delta": reason or "확인 가능한 근거가 없어 답변할 수 없습니다."}
    assert emitted[-1].data == {"done": True, "abstained": True,
                               "abstain_reason": reason or "source_unavailable", "citations": []}
    assert "private-evidence" not in str(emitted) and "rejected-source" not in str(emitted)


@pytest.mark.parametrize("status", [ResultStatus.ABSTAINED, ResultStatus.EMPTY,
                                   ResultStatus.FAILED, ResultStatus.DEPENDENCY_FAILED])
def test_terminal_failure_overrides_other_renderable_value(status):
    emitted = events("do not present", status=status, failure_reason="blocked", source=("hidden",))
    assert [(e.type, e.data) for e in emitted] == [
        ("delta", {"delta": "blocked"}),
        ("done", {"done": True, "abstained": True, "abstain_reason": "blocked", "citations": []}),
    ]


@pytest.mark.parametrize("children,partial,abstained", [
    ({}, False, True),
    ({"skip": "not typed"}, True, True),
    ({"ok": result("ok")}, False, False),
    ({"ok": result("ok"), "skip": 4}, True, False),
    ({"fail": TypedResult.abstain("blocked")}, True, True),
    ({"ok": result("ok"), "fail": TypedResult.abstain("blocked")}, True, False),
    ({"partial": result("some", status=ResultStatus.PARTIAL)}, False, False),
])
def test_composite_completed_count_includes_skipped_entries_in_denominator(children, partial, abstained):
    emitted = events(children, ValueType.COMPOSITE)
    headings = [d["delta"] for d in of_type(emitted, "delta") if d["delta"].startswith("\n")]
    expected = [f"\n{key}\n" for key, child in children.items() if isinstance(child, TypedResult)]
    if partial:
        expected.append("\n일부 요청 결과만 확인되었습니다.")
    assert headings == expected
    assert len(of_type(emitted, "done")) == 1
    assert emitted[-1].data == {"done": True, "abstained": abstained, "citations": [], "bogus_citations": []}


def test_mapping_sources_deduplicate_in_order_including_failed_child_and_parent_partial():
    children = {"second": result("two", source=("b", "b", "a")),
                "first": TypedResult.abstain("blocked", source=("rejected", "a"))}
    emitted = events(children, ValueType.COMPOSITE, source=("parent-only",), status=ResultStatus.PARTIAL)
    assert [d["delta"] for d in of_type(emitted, "delta")] == [
        "\nsecond\n", "two", "\nfirst\n", "blocked", "\n일부 요청 결과만 확인되었습니다.",
    ]
    # Legacy mapping aggregation uses child.source even for an abstaining child.
    assert emitted[-1].data["citations"] == [
        {"index": 1, "source": "b"}, {"index": 2, "source": "a"}, {"index": 3, "source": "rejected"},
    ]


def test_nested_composite_prefixes_blocks_refs_and_only_remaps_top_level_source_index():
    leaf = result([{"label": "A", "value": 1}, {"label": "B", "value": 2}], source=("leaf",))
    inner = result({"leaf-id": leaf}, ValueType.COMPOSITE, source=("inner-envelope",))
    emitted = events({"intro": result("intro", source=("first",)), "outer": inner}, ValueType.COMPOSITE)
    table, chart = of_type(emitted, "table")[0], of_type(emitted, "chart")[0]
    assert table["block_id"] == "outer-leaf-id-multihop-table"
    assert chart["block_id"] == "outer-leaf-id-multihop-chart"
    assert chart["data_ref"] == table["block_id"]
    assert table["source_index"] == chart["source_index"] == 2
    assert table["meta"]["source_index"] == chart["meta"]["source_index"] == 1
    assert table["source"] == chart["source"] == "leaf"
    assert emitted[-1].data["citations"] == [
        {"index": 1, "source": "first"}, {"index": 2, "source": "inner-envelope"},
    ]


@pytest.mark.parametrize("status,abstained", [("success", False), ("partial", False),
                                               ("failed", True), ("empty", True)])
def test_nonprice_snapshot_compat_uses_typed_children(status, abstained):
    emitted = price_events(snapshot("inventory text", metric="inventory", status=status,
                                    output="series", source=["inventory-source"], reason="blocked"))
    assert emitted[0].data == {"delta": "\n니켈:series\n"}
    assert emitted[-1].data["abstained"] is abstained
    assert emitted[-1].data["citations"] == [{"index": 1, "source": "inventory-source"}]
    assert not of_type(emitted, "table")
    assert ("inventory text" in str(emitted)) is (not abstained)


@pytest.mark.parametrize("field,value", [("status", "SUCCESS"), ("status", "Partial"),
                                         ("status", "unknown"), ("result_type", "FACT_SET")])
def test_nonprice_snapshot_enum_conversion_remains_case_sensitive(field, value):
    with pytest.raises(ValueError):
        price_events(snapshot("text", metric="inventory", **{field: value}))


def test_snapshot_duplicate_key_overwrites_without_reordering_and_skips_nontyped_items():
    items = [snapshot("old", metric="inventory", output="series"),
             "ignored", snapshot("middle", mineral="구리", metric="inventory", output="series"),
             snapshot("replacement", metric="inventory", output="series")]
    emitted = events(items, ValueType.COMPOSITE)
    assert [d["delta"] for d in of_type(emitted, "delta")] == [
        "\n니켈:series\n", "replacement", "\n구리:series\n", "middle",
    ]
    assert emitted[-1].data["abstained"] is False


def test_time_series_output_routes_price_snapshot_through_compat_path():
    emitted = price_events(snapshot("series-text", output="time_series"))
    assert [d["delta"] for d in of_type(emitted, "delta")] == ["\n니켈:time_series\n", "series-text"]


def test_snapshot_missing_identity_uses_original_list_index_and_missing_status_fails():
    items = ["skip", {"metric": "inventory", "value": "not success", "reason": "missing-status"}]
    emitted = events(items, ValueType.COMPOSITE)
    assert [d["delta"] for d in of_type(emitted, "delta")] == [
        "\n1:result\n", "missing-status", "\n일부 요청 결과만 확인되었습니다.",
    ]
    assert emitted[-1].data["abstained"] is True


def test_each_price_entity_is_selected_separately_with_lazy_today_calls(monkeypatch):
    calls = []

    class CountingDate(FixedDate):
        @classmethod
        def today(cls):
            calls.append("today")
            return super().today()

    monkeypatch.setattr(live, "date", CountingDate)
    rows = [{"date": "bad", "price": 0}, {"date": "2026-10-03", "price": 3},
            {"date": "2026-10-04", "price": 4}, {"date": "2026-10-05", "price": 5}]
    items = [snapshot(rows, mineral="니켈", source=["unknown"]),
             snapshot([{ "date": "2026-10-03", "price": 8}], mineral="구리", source=["known"])]
    before = deepcopy(items)
    emitted = events(items, ValueType.COMPOSITE, source=("known",))
    assert calls == ["today"] * 4  # One per parseable date, including future rows.
    assert emitted[0].data == {"delta": "니켈: 4 (2026-10-04 기준)\n구리: 8 (2026-10-03 기준)"}
    tables = of_type(emitted, "table")
    assert [t["block_id"] for t in tables] == ["multihop-price-1", "multihop-price-2"]
    assert [t["source_index"] for t in tables] == [None, 1]
    assert [t["source"] for t in tables] == ["unknown", "known"]
    assert items == before


@pytest.mark.parametrize("rows,price,observed", [
    ([{"date": "2026-10-03", "price": 3}, {"date": "2026-10-04", "price": 4},
      {"date": "2026-10-05", "price": 5}], "4", "2026-10-04"),
    ([{"date": "2026-10-04", "price": 4}, {"date": "2026-10-04", "price": 40}], "4", "2026-10-04"),
    ([{"date": "bad", "price": 7}, {"price": 8}], "7", "bad"),
    ([{"price": 7}, {"price": 8}], "7", ""),
    ([{"price": 7}, {"date": "2026-10-03", "price": 3}], "3", "2026-10-03"),
    ([{"CRTR_YMD": "20261004", "value": 6}], "6", "20261004"),
    ([{"observed_date": "2026-10-04T12:00:00", "latest_price": 9}], "9", "2026-10-04T12:00:00"),
    ([{"시점": "2026-10-04", "price": 2}], "2", ""),
])
def test_latest_price_selection_preserves_date_display_and_first_ties(rows, price, observed):
    emitted = price_events(snapshot(rows, source=["s"]), source=("s", "s"))
    table = of_type(emitted, "table")[0]
    assert table["rows"] == [["니켈", price, observed]]
    assert table["block_id"] == "multihop-price-1"
    assert table["source_index"] == 1 and table["source"] == "s"
    assert of_type(emitted, "delta")[0] == {"delta": f"니켈: {price}" + (f" ({observed} 기준)" if observed else "")}
    assert emitted[-1].data["citations"] == [{"index": 1, "source": "s"}, {"index": 2, "source": "s"}]
    assert not of_type(emitted, "chart")


@pytest.mark.parametrize("value", [
    [], [{"date": "2026-10-05", "price": 5}],
    [{"price": 7}, {"date": "2026-10-05", "price": 5}],
    ["invalid", {"price": 7}], {"price": None}, {"price": "None"}, {"price": ""},
    {"other": 7}, "plain text",
])
def test_unpresentable_price_snapshot_never_falls_back_from_future_dated_rows(value):
    emitted = price_events(snapshot(value), source=("not-cited",))
    assert [(e.type, e.data) for e in emitted] == [
        ("delta", {"delta": "표시할 수 있는 검증된 결과가 없습니다."}),
        ("done", {"done": True, "abstained": True, "abstain_reason": "presentation_unavailable", "citations": []}),
    ]


@pytest.mark.parametrize("unit,row_unit,expected", [
    (" usd / kg ", None, "USD/kg"), (None, "t", "t"),
    ("통화코드=PR001;중량단위코드=WT002", None, "USD/톤"),
    ("통화코드=PR001; 중량단위코드=WT001", None, "USD/kg"),
    ("통화코드=BAD;중량단위코드=WT002", None, None),
    ("PR001/WT002", "USD/kg", None),
    (None, None, None),
])
def test_price_verified_units_and_code_fallback_preserve_item_precedence(unit, row_unit, expected):
    emitted = price_events(snapshot({"price": 0, "단위": row_unit}, unit=unit))
    assert emitted[0].data["delta"] == "니켈: 0" + (f" {expected}" if expected else "")
    assert of_type(emitted, "table")[0]["meta"]["unit"] == expected


def test_price_physical_key_priority_partial_message_and_failed_rows_after_prices():
    items = [snapshot({"price": 1, "cmerc_prc(통상가격)": 8}, mineral=" 니켈 "),
             snapshot(status="failed", reason="blocked", output="price")]
    emitted = events(items, ValueType.COMPOSITE, status=ResultStatus.PARTIAL)
    assert [e.type for e in emitted] == ["delta", "table", "delta", "table", "done"]
    assert emitted[0].data == {"delta": "니켈: 8"}
    assert emitted[2].data == {"delta": "\n일부 항목은 조회하지 못했습니다."}
    assert emitted[3].data["rows"] == [["니켈", "price", "failed", "blocked"]]


def test_price_uppercase_success_is_rendered_and_also_reported_as_failure_row():
    emitted = price_events(snapshot(status="SUCCESS"))
    assert emitted[0].data == {"delta": "니켈: 10"}
    assert of_type(emitted, "table")[-1]["rows"] == [["니켈", "price", "SUCCESS", "unspecified_failure"]]
    assert emitted[-1].data["abstained"] is False


@pytest.mark.parametrize("value,text", [("plain", "plain"), (["a", "b"], "a\nb"),
                                      ([""], ""), (["a", ""], "a\n")])
def test_plain_text_and_string_list_preserve_content_and_duplicate_citations(value, text):
    emitted = events(value, source=("s", "s"))
    assert [(e.type, e.data) for e in emitted] == [
        ("delta", {"delta": text}),
        ("done", {"done": True, "abstained": False,
                  "citations": [{"index": 1, "source": "s"}, {"index": 2, "source": "s"}], "bogus_citations": []}),
    ]


def test_document_evidence_list_joins_text_without_reading_metadata():
    documents = [Evidence("pageindex", "doc", "section", "one"), Evidence("dense", "other", "x", "two")]
    emitted = events(documents, ValueType.DOCUMENT_EVIDENCE, source=("declared",))
    assert emitted[0].data == {"delta": "one\n\ntwo"}
    assert emitted[-1].data["citations"] == [{"index": 1, "source": "declared"}]


def test_document_mapping_uses_table_not_text_attribute_extraction():
    emitted = events({"text": "one", "section": "part"}, ValueType.DOCUMENT_EVIDENCE)
    assert of_type(emitted, "table")[0]["rows"] == [["one", "part"]]
    assert emitted[0].data["delta"] == "| text | section |\n| --- | --- |\n| one | part |"


def test_empty_plain_mapping_is_a_single_empty_table_not_empty_value_abstention():
    emitted = events({})
    assert of_type(emitted, "table")[0]["columns"] == []
    assert of_type(emitted, "table")[0]["rows"] == [[]]
    assert emitted[-1].data["abstained"] is False


@pytest.mark.parametrize("value,reason", [
    (None, "presentation_unavailable"), ([], "presentation_unavailable"),
    ("", "presentation_unavailable"), (0, "presentation_unavailable"),
    (False, "presentation_unavailable"), (42, "unsupported_presentation_type"),
    (("a",), "unsupported_presentation_type"), (["a", 1], "unsupported_presentation_type"),
    ([Evidence("dense", "s", "x", "")], "unsupported_presentation_type"),
])
def test_unpresentable_values_keep_empty_vs_unsupported_failure_contract(value, reason):
    emitted = events(value, ValueType.DOCUMENT_EVIDENCE, source=("not-cited",))
    assert [(e.type, e.data) for e in emitted] == [
        ("delta", {"delta": reason}),
        ("done", {"done": True, "abstained": True, "abstain_reason": reason, "citations": []}),
    ]


def test_plain_mapping_and_sparse_table_preserve_column_order_nulls_and_input():
    value = [{"label": "A", "value": None}, {"extra": "x", "label": "B", "value": 2}]
    original = deepcopy(value)
    emitted = events(value)
    table = of_type(emitted, "table")[0]
    assert table["columns"] == ["label", "value", "extra"]
    assert table["rows"] == [["A", "None", ""], ["B", "2", "x"]]
    assert table["rows_typed"] == [["A", None, None], ["B", 2.0, "x"]]
    assert table["source_index"] == 1 and table["source"] is None
    assert value == original
    assert of_type(events(value[0]), "table")[0]["rows"] == [["A", "None"]]


@pytest.mark.parametrize("units,metric,warnings,chart", [
    (("t", "t"), None, (), True), (("t", "kg"), None, (), False),
    ((None, None), "price", (), False), ((None, None), None, ("heterogeneous_units",), False),
    ((None, None), None, (), True), (("t", "t"), "price", ("heterogeneous_units",), True),
])
def test_chart_gate_uses_row_units_metric_and_warning_without_hiding_table(units, metric, warnings, chart):
    rows = [{"label": label, "value": n, "unit": unit} for label, n, unit in zip(("A", "B"), (1, 2), units)]
    emitted = events(rows, metric=metric, warnings=warnings)
    assert len(of_type(emitted, "table")) == 1
    assert bool(of_type(emitted, "chart")) is chart
    assert emitted[-1].data["abstained"] is False


@pytest.mark.parametrize("rows,warnings,summary", [
    ([{"status": "SUCCESS"}, {"status": "failed"}], (), "표시된 2개 항목 중 1개 처리 완료, 1개 처리 불가."),
    ([{"status": "partial"}], ("incomplete_population",), "표시된 1개 항목 중 0개 처리 완료, 1개 처리 불가. 선행 결과가 불완전하여 전체 모집단 결과는 아닙니다."),
    ([{"status": "success"}, {"value": 1}], (), "일부 결과만 확인되었습니다. 전체 모집단 결과는 아닙니다."),
    ("partial text", (), "일부 결과만 확인되었습니다. 전체 모집단 결과는 아닙니다."),
])
def test_partial_row_summary_precedes_content_without_turning_done_into_abstention(rows, warnings, summary):
    emitted = events(rows, status=ResultStatus.PARTIAL, warnings=warnings)
    assert emitted[0].data == {"delta": summary + "\n"}
    assert emitted[-1].data["abstained"] is False
