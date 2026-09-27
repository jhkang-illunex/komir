"""2차전지 원료 광종 resource adapter."""
from __future__ import annotations
from pathlib import Path
import yaml
from .evidence import Evidence

_RESOURCE = Path(__file__).resolve().parents[1] / "ragkit" / "resources" / "battery_minerals.yml"

def fetch_battery_minerals_evidence() -> tuple[list[Evidence], list[str]]:
    payload = yaml.safe_load(_RESOURCE.read_text(encoding="utf-8")) or {}
    group = (payload.get("groups") or {}).get("secondary_battery") or {}
    minerals = group.get("minerals") or []
    if payload.get("source_verified") is not True or not minerals:
        return [], ["battery_minerals_source_unavailable"]
    text = "| 분류 | 광종 |\n|---|---|\n" + "\n".join(
        f"| {group.get('label', '2차전지 원료 광종')} | {mineral} |" for mineral in minerals)
    return [Evidence(kind="structured", source=payload.get("source", "resource"),
                     section=group.get("label", "2차전지 원료 광종"), text=text)], []
