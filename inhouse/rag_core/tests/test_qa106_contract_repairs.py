"""Regression tests for contracts observed in the 18012 QA106 trace.

These tests use typed synthetic rows only.  They do not define production
answers and do not select a question-specific route.
"""

from inhouse.rag_core.ragkit.analytical_aggregate import aggregate
from inhouse.rag_core.ragkit.live_multihop import _capability_rows, _resolve_row_field
from inhouse.rag_core.ragkit.pipe_runtime import TypedResult
from inhouse.rag_core.ragkit.semantic_ir import ValueType


def test_date_series_can_be_grouped_by_semantic_year():
    source = TypedResult.success(
        ValueType.TIME_SERIES,
        [
            {"date": "2025-01-15", "price": 10, "unit": "USD/mt"},
            {"date": "2025-02-15", "price": 20, "unit": "USD/mt"},
            {"date": "2026-01-15", "price": 30, "unit": "USD/mt"},
        ],
        metric="price",
        unit="USD/mt",
    )
    result = aggregate(
        source,
        {"field": "price", "aggregation": "average", "group_by": ["year"], "output_field": "avg_price"},
        lambda rows, field: _resolve_row_field(rows, field, strict=True),
    )
    assert result.failure_reason is None
    assert result.value == [{"year": 2025, "avg_price": 15.0}, {"year": 2026, "avg_price": 30.0}]


def test_typed_projection_maps_inventory_observation_to_value():
    from inhouse.rag_core.ragkit.live_multihop import LiveOperatorFactory

    factory = object.__new__(LiveOperatorFactory)
    source = TypedResult.success(
        ValueType.SCALAR_METRIC,
        [{"obs_date": "2026-03-15", "inventory": 700, "unit": "ton"}],
        metric="inventory",
        unit="ton",
    )
    result = factory._derive(
        type("Node", (), {"operator": "project", "args": {"fields": ["date", "value", "unit"]}})(),
        {"source": source},
    )
    assert result.failure_reason is None
    assert result.value == [{"date": "2026-03-15", "value": 700, "unit": "ton"}]


def test_typed_inventory_projection_accepts_source_display_column():
    from inhouse.rag_core.ragkit import live_multihop

    rows = [{"기준일": "2026-03-15", "재고량": 700, "단위": "ton"}]
    assert live_multihop._resolve_row_field(rows, "재고량", strict=True) == "재고량"


def test_inventory_projection_contract_is_metric_scoped():
    rows = [{"date": "2026-03-15", "value": 700, "unit": "ton"}]
    assert _resolve_row_field(rows, "inventory", strict=True) is None


def test_trade_share_projection_prefers_canonical_column_over_annotated_duplicate():
    rows = [{
        "country": "인도네시아",
        "share_pct": 25.47,
        "share_pct(수입금액 비중(%, 기간 전체 국가 합계 대비))": 25.47,
    }]
    assert _resolve_row_field(rows, "share_percentage", strict=True) == "share_pct"


def test_country_rank_typed_result_excludes_unrelated_evidence_tables():
    rows = [
        {"country": "인도네시아", "share_pct": 25.47,
         "share_pct(수입금액 비중)": 25.47},
        {"기관": "자료원", "발표일": "2026-01-01"},
    ]
    assert _capability_rows(rows, "trade.country_rank") == rows[:1]
