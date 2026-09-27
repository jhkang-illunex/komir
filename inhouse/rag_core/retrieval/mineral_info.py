"""광물정보 구조화 adapter.

검증된 YAML만 사용한다. mineral_risk를 데이터 원천으로 조회하지 않는다.
"""
from __future__ import annotations

from pathlib import Path
import yaml

from .evidence import Evidence

_RESOURCE = Path(__file__).resolve().parents[1] / "ragkit" / "resources" / "mineral_info_data.yml"


def _yaml_record(mineral: str) -> dict | None:
    """검증 완료된 편집형 YAML 값을 우선 반환한다."""
    if not _RESOURCE.exists():
        return None
    payload = yaml.safe_load(_RESOURCE.read_text(encoding="utf-8")) or {}
    record = (payload.get("minerals") or {}).get(mineral)
    if not isinstance(record, dict) or record.get("source_verified") is not True:
        return None
    return record


def fetch_mineral_info_evidence(mineral: str) -> tuple[list[Evidence], list[str]]:
    record = _yaml_record(mineral)
    if record:
        lines = ["| 광종 | 속성 | 값 |", "|---|---|---|"]
        for key in ("uses", "element_symbol", "atomic_number", "atomic_weight", "characteristics", "major_ores"):
            value = record.get(key)
            if value not in (None, [], ""):
                rendered = ", ".join(map(str, value)) if isinstance(value, list) else str(value)
                lines.append(f"| {mineral} | {key} | {rendered} |")
        lines.append(f"| {mineral} | 출처 | {record.get('source_url')} |")
        return [Evidence(kind="structured", source="Royal Society of Chemistry", section="광물정보", text="\n".join(lines), as_of=record.get("source_published_at") or record.get("source_accessed_at"))], []
    return [], [f"mineral_info_not_verified:{mineral}"]
