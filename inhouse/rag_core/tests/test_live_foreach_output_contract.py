import asyncio
from unittest.mock import AsyncMock

import pytest

from inhouse.rag_core.ragkit.live_multihop import LiveOperatorFactory
from inhouse.rag_core.ragkit.pipe_runtime import TypedResult
from inhouse.rag_core.ragkit.semantic_ir import Operator, RequirementNode, ValueType


@pytest.mark.parametrize("extra,expected", [
    ({}, "latest_value"),
    ({"period": {"kind": "trailing_months", "trailing_months": 3}}, "time_series"),
    ({"output": "latest_value", "period": {"kind": "trailing_months", "trailing_months": 3}}, "latest_value"),
])
def test_foreach_materializes_same_output_contract_as_snapshot(extra, expected):
    factory = LiveOperatorFactory(message="", session_id="fixture", profile="public", llm=None, history=[])
    factory._call_action = AsyncMock(return_value=TypedResult.success(ValueType.TIME_SERIES, [{"price": 7}]))
    node = RequirementNode("each", Operator.FOR_EACH, args={"domain": "price", "metric": "price", **extra})
    source = TypedResult.success(ValueType.MINERAL_SET, ["A", "B"], entity=("A", "B"))
    result = asyncio.run(factory._foreach(node, {"source": source}))
    assert factory._call_action.await_count == 2
    for call in factory._call_action.call_args_list:
        assert call.args[0].args["output"] == expected
    assert {row["output"] for row in result.value} == {expected}
