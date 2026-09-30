import unittest

from inhouse.rag_core.ragkit.legacy_bridge import LegacyOperatorFactory
from inhouse.rag_core.ragkit.lowering import PipeLowerer
from inhouse.rag_core.ragkit.multihop_orchestrator import GemmaBrainAdapter, MultiHopOrchestrator
from inhouse.rag_core.ragkit.pipe_runtime import FunctionStep, ResultStatus, TypedResult
from inhouse.rag_core.ragkit.semantic_ir import Operator, RequirementNode, SemanticProgram, ValueType


class MultiHopOrchestratorTests(unittest.IsolatedAsyncioTestCase):
    async def test_ast_is_lowered_executed_validated_and_rendered(self):
        program = SemanticProgram(
            nodes=(RequirementNode("answer", Operator.CALCULATE, expected_type=ValueType.SCALAR_METRIC),),
            roots=("answer",),
        )

        def build(**kwargs):
            return FunctionStep(
                kwargs["node"].node_id,
                kwargs["node"].operator.value,
                lambda _context, _inputs: TypedResult.success(
                    ValueType.SCALAR_METRIC,
                    42,
                    evidence=("rdb:1",),
                    provenance=("step:answer",),
                ),
                dependencies=kwargs["dependencies"],
                bindings=kwargs["bindings"],
            )

        result = await MultiHopOrchestrator(PipeLowerer(LegacyOperatorFactory({"calculate": build}))).execute(
            program,
            session_id="s1",
            turn_id="t1",
            pipe_id="p1",
            evidence_validator=lambda typed: typed.sufficient and bool(typed.evidence),
        )

        self.assertEqual(result.execution.status, ResultStatus.SUCCESS)
        self.assertEqual(result.root_result.value, 42)
        self.assertEqual(result.presentation.typed_result.provenance, ("step:answer",))

    async def test_evidence_failure_becomes_abstain(self):
        program = SemanticProgram(nodes=(RequirementNode("answer", Operator.CALCULATE),), roots=("answer",))

        def build(**kwargs):
            return FunctionStep(
                kwargs["node"].node_id,
                "calculate",
                lambda _c, _i: TypedResult.success(ValueType.SCALAR_METRIC, 42),
                dependencies=kwargs["dependencies"],
                bindings=kwargs["bindings"],
            )

        result = await MultiHopOrchestrator(PipeLowerer(LegacyOperatorFactory({"calculate": build}))).execute(
            program,
            session_id="s1",
            turn_id="t1",
            pipe_id="p1",
            evidence_validator=lambda _typed: False,
        )
        self.assertEqual(result.root_result.status, ResultStatus.ABSTAINED)
        self.assertEqual(result.presentation.abstain_reason, "evidence validation failed")


class GemmaAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_only_structured_program_is_accepted(self):
        adapter = GemmaBrainAdapter(
            lambda **_kwargs: {"nodes": [{"node_id": "x", "operator": "calculate"}], "roots": ["x"]}
        )
        program = await adapter.parse("질문", None)
        self.assertEqual(program.roots, ("x",))

