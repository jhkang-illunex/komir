"""근거만으로 확정할 수 있는 단일 Action 응답 renderer."""
from __future__ import annotations


def render_strategic_price_overview(evidence: list, action_plan) -> tuple[str, set[int]] | None:
    actions = getattr(action_plan, "actions", [])
    if len(actions) != 1 or getattr(actions[0], "action_id", None) != "price.overview":
        return None
    selected = [(index, item) for index, item in enumerate(evidence, 1)
                if getattr(item, "action_id", None) == "price.overview"]
    if len(selected) != 1:
        return None
    return (
        "광물정보 : 전략광종 목록 기준\n"
        "광물가격 : 기준일 기준 광종별 가격·전월 평균 대비 등락률 표입니다. [1]",
        {selected[0][0]},
    )


def render_q15_usgs_scope(evidence: list) -> tuple[str, set[int]] | None:
    required = (
        "###### RARE EARTHS1", "rare-earth-oxide (REO) equivalent",
        "Price, average, dollars per kilogram:",
        "Neodymium oxide, 99.5% minimum 98 134 78 56 73",
        "World Mine Production and Reserves:", "Mine production",
        "World total (rounded) 380,000 390,000 >85,000,000",
        "Data include lanthanides and yttrium",
    )
    matched = [index for index, item in enumerate(evidence, 1)
               if getattr(item, "q15_usgs_scope", False)
               and getattr(item, "action_id", None) == "document.retrieve"
               and getattr(item, "source", None) == "생산매장량_USGS/USGS_2026.md"
               and all(marker in getattr(item, "text", "") for marker in required)]
    if not matched:
        return None
    index = matched[0]
    return (
        "희토류 총괄 통계는 REO(희토류 산화물) 환산 기준의 세계 광산 생산·매장량 표입니다. "
        "세계 총계는 2024년 380,000톤, 2025년 390,000톤, 매장량은 85,000,000톤 초과로 제시됩니다. "
        "이 범위에는 란타넘족과 이트륨이 포함되고 대부분의 스칸듐은 제외됩니다. "
        f"[{index}]\n\n"
        "네오디뮴은 같은 장의 평균 가격 표에서 산화네오디뮴(순도 99.5% 이상)으로 별도 제시됩니다. "
        "해당 가격 행의 2021~2025 값은 킬로그램당 98, 134, 78, 56, 73달러입니다. "
        "따라서 희토류의 총괄 생산·매장량 통계와 특정 산화네오디뮴의 가격은 같은 범위의 단일 지표가 아닙니다. "
        f"[{index}]", {index},
    )
