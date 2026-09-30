import asyncio

from inhouse.rag_core.ragkit.action_results import RetrievalResult, classify_item
from inhouse.rag_core.ragkit.history_context import InMemoryHistoryStore, Turn, UserUtterance


def test_snapshots_are_session_scoped_and_projected_by_output():
    async def run():
        store = InMemoryHistoryStore()
        await store.create_session("s1")
        await store.append_turn(Turn("t1", "s1", UserUtterance("prices")))
        result = RetrievalResult(action_plan=None)
        result.item_results = {
            ("NI", "latest_price"): classify_item(key=("NI", "latest_price"), value=10),
            ("LI", "latest_price"): classify_item(key=("LI", "latest_price"), value=20),
            ("LI", "trailing_3_month_price_series"): classify_item(
                key=("LI", "trailing_3_month_price_series"), failure_reason="no_data"),
        }
        snapshots = result.snapshots(turn_id="t1", result_id="t1:r1")
        await store.save_result_snapshots("s1", "t1", "t1:r1", snapshots)
        latest = await store.get_result_snapshots("s1", output_id="latest_price", status="success")
        assert [row["mineral_id"] for row in latest] == ["NI", "LI"]
        series = await store.get_result_snapshots("s1", output_id="trailing_3_month_price_series", status="success")
        assert series == ()
        assert await store.get_result_snapshots("other", output_id="latest_price") == ()
        context = await store.get_context("s1")
        compacted = context.compact(keep_turns=1)
        assert compacted.result_index[0]["turn_id"] == "t1"
        assert compacted.result_index[0]["result_id"] == "t1:r1"
        assert [row["mineral_id"] for row in compacted.project_snapshots(output_id="latest_price")] == ["NI", "LI"]

    asyncio.run(run())
