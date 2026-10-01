import json
from pathlib import Path


FIXTURE = Path(__file__).with_name("qa_structured_fixture_20261001.json")


def _rows(table):
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["tables"][table]


def test_fixture_matches_current_structured_contracts_and_boundaries():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert set(data["tables"]) == {
        "fact_price", "fact_trade_annual", "fact_production_reserve",
        "fact_inventory", "fact_indicator",
    }
    assert {r["commodity_code"] for r in _rows("fact_price")} == {"NI", "CU", "LI"}
    assert any(r["val"] is None for r in _rows("fact_price"))
    assert any(r["val"] == 0 for r in _rows("fact_production_reserve"))
    assert len([r for r in _rows("fact_trade_annual") if r["commodity_code"] == "CU"]) == 2


def test_price_latest_and_three_month_argmax_are_deterministic():
    rows = [r for r in _rows("fact_price") if r["commodity_code"] == "NI"]
    assert max(rows, key=lambda r: r["val"])["obs_date"] == "2026-02-15"
    assert rows[-1]["obs_date"] == "2026-03-15"


def test_trade_shares_and_hhi_preserve_tie_and_null():
    rows = [r for r in _rows("fact_trade_annual") if r["commodity_code"] == "CU"]
    values = [r["imp_usd"] for r in rows if r["imp_usd"] is not None]
    total = sum(values)
    shares = [v / total for v in values]
    assert shares == [0.5, 0.5]
    assert sum(s * s for s in shares) == 0.5
    assert any(r["imp_usd"] is None for r in _rows("fact_trade_annual"))


def test_production_and_reserves_remain_distinct_metrics():
    rows = _rows("fact_production_reserve")
    production = sum(r["val"] or 0 for r in rows if r["metric"] == "production")
    reserves = sum(r["val"] or 0 for r in rows if r["metric"] == "reserves")
    assert production == 90
    assert reserves == 300


def test_v2_lowering_contract_covers_fixture_metrics():
    from rag_core.ragkit.semantic_v2 import (
        EntityRef, LegacyActionLowerer, Metric, SemanticRequirementPlanV2,
        SemanticRequirementV2, TimeRange, logical_program_from_requirements,
    )

    plan = SemanticRequirementPlanV2(requirements=[
        SemanticRequirementV2(requirement_id="p", entity=EntityRef(value="니켈"), metric=Metric.PRICE, time_range=TimeRange(kind="latest")),
        SemanticRequirementV2(requirement_id="t", entity=EntityRef(value="니켈"), metric=Metric.CONCENTRATION),
        SemanticRequirementV2(requirement_id="r", entity=EntityRef(value="니켈"), metric=Metric.PRODUCTION),
    ])
    program = logical_program_from_requirements(plan)
    assert {call.action_id for call in LegacyActionLowerer().lower(program)} == {
        "price.series", "trade.concentration", "resource.rank",
    }


def test_v2_lowering_contract_covers_inventory_and_indicator():
    from rag_core.ragkit.semantic_v2 import (
        EntityRef, LegacyActionLowerer, Metric, SemanticRequirementPlanV2,
        SemanticRequirementV2,
    )

    plan = SemanticRequirementPlanV2(requirements=[
        SemanticRequirementV2(requirement_id="inventory", entity=EntityRef(value="니켈"), metric=Metric.INVENTORY),
        SemanticRequirementV2(requirement_id="index", entity=EntityRef(value="광물종합지수"), metric=Metric.INDICATOR, indicator="composite_index"),
    ])
    program = __import__("rag_core.ragkit.semantic_v2", fromlist=["logical_program_from_requirements"]).logical_program_from_requirements(plan)
    calls = LegacyActionLowerer().lower(program)
    assert [call.action_id for call in calls] == ["inventory.latest", "indicator.series"]
    assert calls[1].slots.indicator == "composite_index"
