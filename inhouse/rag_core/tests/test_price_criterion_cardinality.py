from common.komis_raw import RawDataset
from rag_core.ragkit._mcp_tools_common import (
    _attach_selected_price_identity,
    _expand_all_price_measures,
    _select_representative_price_measure,
)
from rag_core.ragkit.live_multihop import LiveOperatorFactory
from rag_core.ragkit.pipe_runtime import TypedResult
from rag_core.ragkit.semantic_ir import InputRef, Operator, RequirementNode, ValueType


def test_all_price_measures_keep_source_criterion_and_expand_series():
    dataset = RawDataset(
        source_table="KO_MNRL_PRC",
        columns=["crtr_ymd", "lowst_prc", "hghst_prc", "cmerc_prc"],
        rows=[{
            "crtr_ymd": "20261001",
            "lowst_prc": 10,
            "hghst_prc": 20,
            "cmerc_prc": 15,
        }],
        row_count=1,
    )

    expanded = _expand_all_price_measures(
        dataset,
        serial=502,
        criterion=("LME CASH", "USD", "WT007"),
    )

    assert len(expanded.rows) == 3
    assert {row["price_measure"] for row in expanded.rows} == {
        "low_price", "high_price", "normal_price",
    }
    assert {row["price"] for row in expanded.rows} == {10, 15, 20}
    assert {row["price_criterion_serial"] for row in expanded.rows} == {502}
    assert {row["price_criterion"] for row in expanded.rows} == {"LME CASH"}
    assert expanded.metadata["preserve_price_criterion_identity"] is True


def test_all_price_measures_skip_null_source_measure():
    dataset = RawDataset(
        source_table="KO_MNRL_PRC",
        columns=["crtr_ymd", "lowst_prc", "hghst_prc", "cmerc_prc"],
        rows=[{
            "crtr_ymd": "20261001",
            "lowst_prc": None,
            "hghst_prc": 20,
            "cmerc_prc": 15,
        }],
        row_count=1,
    )

    expanded = _expand_all_price_measures(
        dataset,
        serial=502,
        criterion=("LME CASH", "USD", "WT007"),
    )

    assert len(expanded.rows) == 2
    assert all(row["price_measure"] != "low_price" for row in expanded.rows)


def test_representative_price_keeps_only_normal_measure():
    dataset = RawDataset(
        source_table="KO_MNRL_PRC",
        columns=["crtr_ymd", "lowst_prc", "hghst_prc", "cmerc_prc"],
        rows=[{
            "crtr_ymd": "20261001",
            "lowst_prc": 10,
            "hghst_prc": 20,
            "cmerc_prc": 15,
        }],
        row_count=1,
    )

    representative = _select_representative_price_measure(dataset)

    assert representative.columns == ["crtr_ymd", "cmerc_prc"]
    assert representative.rows == [{"crtr_ymd": "20261001", "cmerc_prc": 15}]
    assert representative.metadata["representative_price_measure"] is True


def test_lithium_surface_name_uses_canonical_representative_criterion():
    from rag_core.ragkit.representative_price_criteria import representative_price_criterion

    assert representative_price_criterion("리튬") == {
        "criterion": "99.5%min CIF China", "unit": "USD/kg"
    }


def test_all_price_projection_preserves_series_identity_when_fields_are_implicit():
    source = TypedResult.success(
        ValueType.TIME_SERIES,
        [{
            "date": "2026-10-01", "price": 10,
            "price_measure": "low_price", "price_measure_label": "최저가격",
            "price_criterion": "LME CASH", "price_criterion_serial": 502,
        }],
        metric=None,
    )
    node = RequirementNode(
        node_id="project", operator=Operator.PROJECT,
        inputs=(InputRef("source"),), args={"fields": ["date", "price"]},
    )

    result = object.__new__(LiveOperatorFactory)._derive(node, {"source": source})

    assert result.status.value == "success"
    assert result.value[0]["price_measure"] == "low_price"
    assert result.value[0]["price_criterion_serial"] == 502


def test_selected_representative_price_materializes_criterion_identity():
    dataset = RawDataset(
        source_table="KO_MNRL_PRC",
        columns=["date", "price"],
        rows=[{"date": "2026-10-01", "price": 10}],
        row_count=1,
    )

    selected = _attach_selected_price_identity(
        dataset, serial=502, criterion=("LME CASH", "PR001", "WT002"),
    )

    assert selected.rows[0]["price_criterion"] == "LME CASH"
    assert selected.rows[0]["price_criterion_serial"] == 502
