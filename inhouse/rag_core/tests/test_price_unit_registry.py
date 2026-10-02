"""Verified source-code normalization; no DB, MCP or LLM calls.

Independent metadata: public.st_code_mst, checked 2026-10-02;
SQL/bindings/rows archived in /tmp/stability33-units.json (not a test dependency).
"""
import ast
from copy import deepcopy
from pathlib import Path

import pytest

from rag_core.ragkit import chatbot_events as events
from rag_core.ragkit.live_multihop import _typed_unit
from rag_core.retrieval.evidence import Evidence


@pytest.mark.parametrize("code,source_label,expected", [
    ("WT001", "kg", "USD/kg"),
    ("WT006", "lb", "USD/lb"),
    ("WT007", "mt", "USD/톤"),
])
def test_verified_units_reach_live_table_and_chart_without_mutating_evidence(code, source_label, expected):
    raw_unit = f"가격기준=synthetic; 통화코드=PR001; 중량단위코드={code}"
    evidence = Evidence(
        kind="structured", source="synthetic", section="price", unit=raw_unit,
        text=("| price_date | price | price_currency_code | weight_unit_code |\n"
              "| --- | --- | --- | --- |\n"
              f"| 20260101 | 10 | PR001 | {code} |\n"
              f"| 20260102 | 20 | PR001 | {code} |"),
    )
    before = deepcopy(evidence)
    table = events.extract_markdown_tables(evidence.text)[0]
    table_before = deepcopy(table)
    assert events._PRICE_CURRENCY_CODES["PR001"] == "USD"
    assert events._PRICE_WEIGHT_CODES[code] == source_label
    assert events._price_unit_from_codes(["PR001"], [code]) == expected
    assert _typed_unit(evidence.unit) == expected
    block = events.table_block(table, block_id="t", source_index=1, source_label="synthetic", unit=raw_unit)
    chart = events.chart_spec(table, block_id="c", data_ref="t", source_index=1, source_label="synthetic", unit=raw_unit)
    assert chart is not None
    assert chart["spec"]["y_unit"] == expected
    assert block["rows"][0][-2:] == ["USD", source_label]
    assert [row[1] for row in block["rows_typed"]] == [10, 20]
    assert evidence == before
    assert table == table_before


@pytest.mark.parametrize("currency,weight", [
    ("PR001", "WT008"), ("PR001", "WT999"),
    ("PR999", "WT001"), ("PR001", "WT003"),
])
def test_unverified_units_fail_closed(currency, weight):
    assert events._price_unit_from_codes([currency], [weight]) is None
    assert _typed_unit(f"통화코드={currency}; 중량단위코드={weight}") is None


def test_existing_strategic_registry_agrees_on_shared_verified_codes():
    # Inspect the existing literal without importing/starting the MCP server.
    path = Path(events.__file__).with_name("_mcp_tools_common.py")
    tree = ast.parse(path.read_text(encoding="utf-8"))
    registries = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            try:
                value = ast.literal_eval(node)
            except (ValueError, TypeError):
                continue
            if {"WT001", "WT002", "WT007"} <= value.keys():
                registries.append(value)
    assert registries, "existing strategic weight registry not found"
    for registry in registries:
        for code in ("WT001", "WT002", "WT007"):
            assert events._PRICE_WEIGHT_CODES[code] == registry[code]
