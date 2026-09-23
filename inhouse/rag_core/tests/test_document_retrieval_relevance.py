"""공개 OKF의 문서 관계 검색 회귀 검사.

테스트는 고정 파일명으로 조회 로직을 유도하지 않는다. 실제 코퍼스에서 반환된
본문 span이 필요한 광종·관계 표지를 함께 갖는지만 확인한다.
"""
from rag_core.ragkit.action_contract import ActionCall, ActionSlots
from rag_core.ragkit.chatbot_graph import _route_from_action_call
from rag_core.retrieval import pageindex


def _pageindex_texts(route):
    result = pageindex.lookup(route.resolved_query, node_limit=8, with_text=True)
    return [node["text"] for node in result["nodes"]]


def test_lithium_supply_report_recovers_battery_demand_span():
    call = ActionCall(
        requirement_id="lithium", action_id="document.retrieve", intent="document", role="content",
        slots=ActionSlots(mineral="리튬", topic="리튬 수급 이슈"),
    )
    route = _route_from_action_call(call, "리튬 수급 이슈를 설명하는 보고서를 찾아줘")

    texts = _pageindex_texts(route)

    assert "리튬 배터리 수요" in texts[0]
    assert "342,000톤" in texts[0] and "868,000톤" in texts[0]


def test_ternary_battery_report_recovers_nickel_cobalt_relation_without_decoy():
    call = ActionCall(
        requirement_id="ternary", action_id="document.retrieve", intent="document", role="content",
        slots=ActionSlots(minerals=["니켈", "코발트"], topic="삼원계 배터리 수요 관계"),
    )
    route = _route_from_action_call(call, "삼원계 배터리와 니켈·코발트 수요의 관계를 설명하는 보고서를 찾아줘")

    texts = _pageindex_texts(route)

    assert any("NCM" in text and "니켈" in text and "코발트" in text for text in texts)
    assert all("1) 알루미늄" not in text for text in texts)
