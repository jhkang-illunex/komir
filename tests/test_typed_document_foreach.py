import asyncio

from inhouse.rag_core.ragkit.lowering import PipeLowerer
from inhouse.rag_core.ragkit.pipe_runtime import ExecutionContext, FunctionStep, PipeRuntime, TypedResult
from inhouse.rag_core.ragkit.semantic_ir import InputRef, Operator, RequirementNode, SemanticProgram, ValueType


def test_document_mineral_set_foreach_preserves_entity_evidence_and_status():
    program = SemanticProgram(
        nodes=(
            RequirementNode("doc", Operator.RETRIEVE_DOCUMENT, expected_type=ValueType.DOCUMENT_EVIDENCE),
            RequirementNode("minerals", Operator.PROJECT, inputs=(InputRef("doc", "field", "mineral_set"),),
                            expected_type=ValueType.MINERAL_SET),
            RequirementNode("per_mineral", Operator.FOR_EACH, inputs=(InputRef("minerals"),),
                            args={"operation": "price_current", "period": "latest", "as_of": "2026-10-01"},
                            expected_type=ValueType.COMPOSITE),
        ),
        roots=("per_mineral",),
    )

    async def document(_context, _inputs):
        return TypedResult.success(
            ValueType.DOCUMENT_EVIDENCE,
            {"mineral_set": ["니켈", "리튬"]},
            entity=("니켈", "리튬"), evidence=("fixed-report-evidence",),
            source=("report",), provenance=("report:fixed-2026-03",),
        )

    async def minerals(_context, inputs):
        source = inputs["input_0"]
        values = source.value
        return TypedResult.success(ValueType.MINERAL_SET, values,
                                   entity=tuple(values), evidence=source.evidence,
                                   source=source.source, provenance=source.provenance,
                                   upstream_step_ids=("doc",))

    async def foreach(_context, inputs):
        source = inputs["input_0"]
        rows = {}
        for mineral in source.value:
            rows[mineral] = {
                "mineral_id": mineral, "status": "success", "price": 100,
                "evidence": list(source.evidence), "provenance": list(source.provenance),
                "period": "latest", "as_of": "2026-10-01",
            }
        return TypedResult.success(ValueType.COMPOSITE, rows, entity=tuple(source.value),
                                   evidence=source.evidence, source=source.source,
                                   provenance=source.provenance, upstream_step_ids=("minerals",))

    class Factory:
        def build(self, node, dependencies, bindings):
            handlers = {"doc": document, "minerals": minerals, "per_mineral": foreach}
            return FunctionStep(node.node_id, node.operator.value, handlers[node.node_id],
                                dependencies=dependencies, bindings=bindings)

    result = asyncio.run(PipeRuntime().execute(PipeLowerer(Factory()).lower(program, pipe_id="fixed-foreach"),
                                               ExecutionContext(session_id="fixture", turn_id="1")))
    output = result.results["per_mineral"]
    assert output.status.value == "success"
    assert set(output.value) == {"니켈", "리튬"}
    assert all(row["evidence"] == ["fixed-report-evidence"] for row in output.value.values())
    assert all(row["status"] == "success" for row in output.value.values())
