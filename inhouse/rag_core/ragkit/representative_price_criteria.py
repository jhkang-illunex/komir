from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

_PATH = Path(__file__).with_name("resources") / "representative_price_criteria.yaml"


def representative_price_criterion(mineral_name: str | None) -> dict[str, str] | None:
    if not mineral_name:
        return None
    data: dict[str, Any] = yaml.safe_load(_PATH.read_text(encoding="utf-8")) or {}
    criteria = data.get("criteria", {})
    value = criteria.get(mineral_name.strip())
    return dict(value) if isinstance(value, dict) else None
