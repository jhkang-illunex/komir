"""광물정보 구조화 adapter.

`ai_mnrl_sect`가 비어 있으면 값을 추정하지 않고 명시적으로 기권한다.
"""
from __future__ import annotations

from pathlib import Path
import yaml

from common.config import get_settings
from common.db import pg_connect
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
    schema = "public"
    con = pg_connect()
    try:
        with con.cursor() as cur:
            cur.execute(
                f"SELECT mnrknd_unq_cd, mnrl_nm_ko, mnrl_nm_en FROM {schema}.ai_mnrl_mst "
                "WHERE use_yn='Y' AND mnrl_nm_ko=%s LIMIT 1", (mineral,))
            master = cur.fetchone()
            if not master:
                return [], [f"mineral_info_not_found:{mineral}"]
            code, name_ko, name_en = master
            cur.execute(
                f"SELECT * FROM {schema}.ai_mnrl_sect WHERE mnrknd_unq_cd=%s", (code,))
            columns = [desc[0] for desc in cur.description or ()]
            rows = cur.fetchall()
    except Exception as exc:  # noqa: BLE001
        return [], [f"mineral_info_query_failed:{type(exc).__name__}"]
    finally:
        con.close()
    if not rows:
        return [], [f"mineral_info_properties_unavailable:{code}"]
    lines = ["| 광종 | 영문명 | 속성 | 값 |", "|---|---|---|---|"]
    for row in rows:
        values = dict(zip(columns, row))
        for key, value in values.items():
            if key == "mnrknd_unq_cd" or value in (None, ""):
                continue
            lines.append(f"| {name_ko} | {name_en or ''} | {key} | {value} |")
    if len(lines) == 2:
        return [], [f"mineral_info_properties_unavailable:{code}"]
    return [Evidence(kind="structured", source="KOMIS 광물정보", section="광물정보", text="\n".join(lines), as_of=None)], []
