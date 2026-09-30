import unittest
from datetime import datetime, timezone

from inhouse.rag_core.ragkit.history_context import PostgresHistoryStore, Turn, UserUtterance
from inhouse.rag_core.ragkit.pipe_runtime import ExecutionResult, ResultStatus, TypedResult
from inhouse.rag_core.ragkit.semantic_ir import Operator, RequirementNode, SemanticProgram, ValueType


class HistoryStorePersistenceContractTests(unittest.TestCase):
    def setUp(self):
        self.program = SemanticProgram(
            (RequirementNode("root", Operator.ENTITY, args={"values": ["니켈"]}),),
            ("root",),
        )
        self.result = ExecutionResult(
            "pipe-1", ResultStatus.SUCCESS,
            {"root": TypedResult.success(ValueType.MINERAL_SET, [{"광종": "니켈"}], entity=("니켈",), provenance=("fixture",))},
            (),
        )

    def test_postgres_payload_roundtrip_rehydrates_typed_turn(self):
        turn = Turn(
            "turn-1", "session-1", UserUtterance("니켈 결과", datetime.now(timezone.utc)),
            semantic_program=self.program, result=self.result, bindings=self.result.results,
        )
        row = (
            turn.turn_id, turn.utterance.text, turn.utterance.created_at,
            self.program.to_dict(), "pipe-1",
            {"pipe_id": "pipe-1", "status": "success", "results": {"root": {
                "result_type": "mineral_set", "value": [{"광종": "니켈"}], "status": "success",
                "entity": ["니켈"], "provenance": ["fixture"], "sufficient": True,
            }}},
            (),
        )
        recovered = PostgresHistoryStore._turn_from_row("session-1", row)
        self.assertEqual(recovered.turn_id, turn.turn_id)
        self.assertEqual(recovered.semantic_program.to_dict(), self.program.to_dict())
        self.assertEqual(recovered.result.results["root"].value, [{"광종": "니켈"}])
        self.assertEqual(recovered.result.results["root"].provenance, ("fixture",))

    def test_postgres_store_requires_safe_schema_and_positive_ttl(self):
        with self.assertRaises(ValueError):
            PostgresHistoryStore("postgresql://localhost/db", schema="ai_chatbot;drop")
        with self.assertRaises(ValueError):
            PostgresHistoryStore("postgresql://localhost/db", ttl_days=0)
