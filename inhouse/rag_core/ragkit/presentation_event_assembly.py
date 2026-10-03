"""Existing ChatEvent wire assembly; no result interpretation or transport I/O."""
from __future__ import annotations

from typing import Any, Iterable

from .chatbot_events import ChatEvent
from .pipe_runtime import TypedResult


def delta(text: str) -> ChatEvent:
    return ChatEvent("delta", {"delta": text})


def completed(sources: Iterable[str], *, abstained: bool = False) -> ChatEvent:
    # Do not deduplicate here: only composite orchestration deduplicates sources.
    citations = [{"index": index, "source": source} for index, source in enumerate(sources, 1)]
    return ChatEvent("done", {"done": True, "abstained": abstained,
                              "citations": citations, "bogus_citations": []})


def unavailable(reason: str, message: str) -> list[ChatEvent]:
    # Legacy abstention payload deliberately has no bogus_citations field.
    return [delta(message), ChatEvent("done", {
        "done": True, "abstained": True, "abstain_reason": reason, "citations": [],
    })]


def child_event(event: ChatEvent, output_id: Any, child: TypedResult,
                sources: list[str]) -> ChatEvent:
    data = dict(event.data)
    source_index = data.get("source_index")
    if isinstance(source_index, int) and 0 < source_index <= len(child.source):
        data["source_index"] = sources.index(child.source[source_index - 1]) + 1
    if "block_id" in data:
        data["block_id"] = f"{output_id}-{data['block_id']}"
    if "data_ref" in data:
        data["data_ref"] = f"{output_id}-{data['data_ref']}"
    return ChatEvent(event.type, data)
