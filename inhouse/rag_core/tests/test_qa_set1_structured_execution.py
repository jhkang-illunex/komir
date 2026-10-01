import json
from collections import defaultdict
from pathlib import Path

import pytest


ROOT = Path(__file__).parent
GOLD = ROOT / "qa_build_set1_structured_gold_20261001.json"
FIXTURE = ROOT / "qa_structured_fixture_extended_20261001.json"
CODE = {
    "니켈":"NI", "구리":"CU", "동":"DONG", "리튬":"LI", "코발트":"CO",
    "텅스텐":"W", "흑연":"GR", "망간":"MN", "아연":"ZN", "희토류":"REE",
}


def _rows(case, tables):
    entity = case["entity"]
    code = CODE.get(entity) if entity else None
    metric = case["metric"]
    if metric == "price":
        rows = tables["fact_price"]
    elif metric in {"import_value", "concentration"}:
        rows = tables["fact_trade_annual"]
    elif metric in {"production", "reserves"}:
        rows = [r for r in tables["fact_production_reserve"] if r["metric"] == metric]
    elif metric == "inventory":
        rows = tables["fact_inventory"]
    elif metric == "indicator":
        rows = tables["fact_indicator"]
    else:
        return []
    if code:
        rows = [r for r in rows if r["commodity_code"] == code]
    return rows


def _execute(case, tables):
    rows = _rows(case, tables)
    assert rows, f"fixture has no rows for {case['qa_id']}"
    values = [r.get("val", r.get("imp_usd")) for r in rows]
    numeric = [v for v in values if isinstance(v, (int, float))]
    assert numeric, case["qa_id"]
    current = rows
    for op in case["operations"][1:]:
        if op.startswith("GroupBy(country)"):
            grouped = defaultdict(float)
            for row in current:
                value = row.get("imp_usd", row.get("val"))
                if value is not None:
                    grouped[row["country"]] += value
            current = [{"country": k, "value": v} for k, v in grouped.items()]
        elif op == "Aggregate":
            current = [{"value": sum((r.get("value", r.get("val", r.get("imp_usd"))) or 0) for r in current)}]
        elif op == "Calculate":
            current = [{**r, "calculated": True} for r in current]
        elif op.startswith("Sort"):
            current = sorted(current, key=lambda r: r.get("value", r.get("val", 0)), reverse=True)
        elif op.startswith("Select"):
            current = current[:1]
        elif op == "Project":
            current = [{k: v for k, v in r.items() if k in {"country", "obs_date", "value", "val"}} for r in current]
    assert current, case["qa_id"]
    return current


@pytest.mark.parametrize("index", range(87))
def test_each_structured_qa_executes_against_union_fixture(index):
    gold = json.loads(GOLD.read_text(encoding="utf-8"))["cases"][index]
    tables = json.loads(FIXTURE.read_text(encoding="utf-8"))["tables"]
    result = _execute(gold, tables)
    assert result
