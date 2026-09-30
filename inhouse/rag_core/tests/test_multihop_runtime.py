import asyncio
import unittest

from inhouse.rag_core.ragkit.history_context import InMemoryHistoryStore, Turn, UserUtterance
from inhouse.rag_core.ragkit.pipe_runtime import (
    ExecutionContext,
    FunctionStep,
    InputBinding,
    Pipe,
    PipeRuntime,
    ResultStatus,
    TypedResult,
)
from inhouse.rag_core.ragkit.semantic_ir import (
    InputRef,
    Operator,
    RequirementNode,
    SemanticProgram,
    ValueType,
)


class MultiHopRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_langgraph_executes_fanout_then_typed_binding(self):
        async def source_a(_context, _inputs):
            await asyncio.sleep(0.01)
            return TypedResult.success(ValueType.MINERAL_RANKING, ["Cu", "Ni", "Li"], entity=("Cu", "Ni", "Li"))

        async def source_b(_context, _inputs):
            await asyncio.sleep(0.01)
            return TypedResult.success(ValueType.TRADE_SERIES, {"Cu": 10, "Ni": 20, "Li": 5})

        async def consume(_context, inputs):
            selected = inputs["mineral"].value
            return TypedResult.success(ValueType.SCALAR_METRIC, {"mineral": selected, "value": 20})

        pipe = Pipe(
            "rank-import-argmax",
            (
                FunctionStep("rank", "rank", source_a),
                FunctionStep("imports", "retrieve", source_b),
                FunctionStep(
                    "select",
                    "arg_max",
                    consume,
                    dependencies=("rank", "imports"),
                    bindings={"mineral": InputBinding("rank", "index", 1), "values": InputBinding("imports")},
                ),
            ),
        )

        result = await PipeRuntime().execute(pipe, ExecutionContext(session_id="s1", turn_id="t1"))

        self.assertEqual(result.status, ResultStatus.SUCCESS)
        self.assertEqual(result.results["select"].value["mineral"], "Ni")
        self.assertEqual(result.results["select"].upstream_step_ids, ("imports", "rank"))
        self.assertEqual([event.event_type for event in result.events].count("pipe_completed"), 1)

    async def test_retry_is_deterministic_and_failure_blocks_downstream(self):
        attempts = 0

        async def flaky(_context, _inputs):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise RuntimeError("temporary tool error")
            return TypedResult.success(ValueType.SCALAR_METRIC, 7)

        async def downstream(_context, _inputs):
            return TypedResult.success(ValueType.SCALAR_METRIC, 8)

        retry_pipe = Pipe("retry", (FunctionStep("tool", "retrieve", flaky, max_retries=1),))
        retry_result = await PipeRuntime().execute(retry_pipe)
        self.assertEqual(retry_result.status, ResultStatus.SUCCESS)
        self.assertEqual(attempts, 2)

        failing_pipe = Pipe(
            "failure",
            (
                FunctionStep("tool", "retrieve", lambda _c, _i: TypedResult.failed("no data")),
                FunctionStep("next", "calculate", downstream, dependencies=("tool",)),
            ),
        )
        failure_result = await PipeRuntime().execute(failing_pipe)
        self.assertEqual(failure_result.status, ResultStatus.FAILED)
        self.assertEqual(failure_result.results["next"].status, ResultStatus.FAILED)
        self.assertIn("upstream step failed", failure_result.results["next"].failure_reason)

    async def test_invalid_typed_selector_becomes_step_failure(self):
        pipe = Pipe(
            "invalid-selector",
            (
                FunctionStep("source", "retrieve", lambda _c, _i: TypedResult.success(ValueType.MINERAL_SET, ["Ni"])),
                FunctionStep(
                    "select",
                    "resolve_reference",
                    lambda _c, _i: TypedResult.success(ValueType.SCALAR_METRIC, "unreachable"),
                    bindings={"item": InputBinding("source", "index", 1)},
                ),
            ),
        )

        result = await PipeRuntime().execute(pipe)

        self.assertEqual(result.results["select"].status, ResultStatus.FAILED)
        self.assertIn("index out of range", result.results["select"].failure_reason)

    async def test_field_binding_projects_a_sequence_of_typed_rows(self):
        pipe = Pipe(
            "field-sequence",
            (
                FunctionStep(
                    "source", "retrieve",
                    lambda _c, _i: TypedResult.success(
                        ValueType.TRADE_SERIES,
                        [{"price_change_rate": -3.0}, {"price_change_rate": 1.5}],
                    ),
                ),
                FunctionStep(
                    "project", "project",
                    lambda _c, inputs: TypedResult.success(ValueType.SCALAR_METRIC, inputs["rates"].value),
                    bindings={"rates": InputBinding("source", "field", "price_change_rate")},
                ),
            ),
        )
        result = await PipeRuntime().execute(pipe)
        self.assertEqual(result.status, ResultStatus.SUCCESS)
        self.assertEqual(result.results["project"].value, [-3.0, 1.5])


class SemanticIRTests(unittest.TestCase):
    def test_program_is_inspectable_and_rejects_cycles(self):
        program = SemanticProgram(
            nodes=(
                RequirementNode("rank", Operator.RANK, expected_type=ValueType.MINERAL_RANKING),
                RequirementNode("top", Operator.TOP_K, (InputRef("rank"),), {"k": 3}, ValueType.MINERAL_SET),
            ),
            roots=("top",),
        )
        self.assertEqual(SemanticProgram.from_dict(program.to_dict()).to_dict(), program.to_dict())
        with self.assertRaisesRegex(ValueError, "cycle"):
            SemanticProgram(
                nodes=(
                    RequirementNode("a", Operator.FILTER, (InputRef("b"),)),
                    RequirementNode("b", Operator.FILTER, (InputRef("a"),)),
                ),
                roots=("a",),
            )


class SemanticHistoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_context_keeps_typed_turn_not_only_raw_text(self):
        store = InMemoryHistoryStore()
        turn = Turn("t1", "s1", UserUtterance("가격 상승률 상위 3개"))
        await store.append_turn(turn)
        context = await store.get_context("s1")
        self.assertEqual(context.latest.utterance.text, "가격 상승률 상위 3개")
        await store.save_result("s1", "t1", await PipeRuntime().execute(Pipe("p", ())))
        self.assertIsNotNone((await store.get_context("s1")).latest.result)
