import unittest

from inhouse.rag_core.ragkit.legacy_bridge import LegacyOperatorFactory
from inhouse.rag_core.ragkit.lowering import PipeLowerer
from inhouse.rag_core.ragkit.pipe_runtime import FunctionStep, InputBinding
from inhouse.rag_core.ragkit.semantic_ir import InputRef, Operator, RequirementNode, SemanticProgram, ValueType


class MultiHopLoweringTests(unittest.TestCase):
    def test_lowering_preserves_semantic_dependencies_and_selectors(self):
        program = SemanticProgram(
            nodes=(
                RequirementNode("rank", Operator.RANK, expected_type=ValueType.MINERAL_RANKING),
                RequirementNode(
                    "top",
                    Operator.TOP_K,
                    inputs=(InputRef("rank", "index", 1),),
                    args={"k": 3},
                    expected_type=ValueType.MINERAL_SET,
                ),
            ),
            roots=("top",),
        )

        def build(**kwargs):
            node = kwargs["node"]
            return FunctionStep(
                node.node_id,
                node.operator.value,
                lambda _c, _i: None,
                dependencies=kwargs["dependencies"],
                bindings=kwargs["bindings"],
            )

        pipe = PipeLowerer(LegacyOperatorFactory({"rank": build, "top_k": build})).lower(program, pipe_id="p1")

        self.assertEqual(pipe.steps[1].dependencies, ("rank",))
        self.assertEqual(pipe.steps[1].bindings["input_0"], InputBinding("rank", "index", 1))
