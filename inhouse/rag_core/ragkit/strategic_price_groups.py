"""발주처 지정 전략광종 가격 그룹 YAML의 좁은 읽기 전용 loader."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml


StrategicPriceGroup = Literal["strategic_six", "strategic_ten", "battery_five"]
_RESOURCE = Path(__file__).with_name("resources") / "strategic_price_groups.yaml"


@dataclass(frozen=True)
class StrategicPriceMember:
    group: StrategicPriceGroup
    group_label: str
    label: str
    price_mineral: str


def load_strategic_price_members(
    groups: tuple[StrategicPriceGroup, ...] = ("strategic_six", "strategic_ten"),
) -> list[StrategicPriceMember]:
    """YAML 정본 순서대로 가격 원천 조회용 멤버를 돌려준다."""
    try:
        payload = yaml.safe_load(_RESOURCE.read_text(encoding="utf-8"))
        configured = payload["groups"]
        if payload.get("schema_version") != 1:
            raise ValueError("unsupported schema")
    except (OSError, TypeError, ValueError, yaml.YAMLError, KeyError) as exc:
        raise RuntimeError("전략광종 가격 그룹 설정을 읽을 수 없습니다.") from exc
    result: list[StrategicPriceMember] = []
    for group in groups:
        raw_group = configured.get(group)
        if not isinstance(raw_group, dict) or not isinstance(raw_group.get("label"), str):
            raise RuntimeError(f"전략광종 가격 그룹 설정이 올바르지 않습니다: {group}")
        seen: set[str] = set()
        for raw_member in raw_group.get("minerals", []):
            if not isinstance(raw_member, dict):
                raise RuntimeError(f"전략광종 가격 멤버 설정이 올바르지 않습니다: {group}")
            label, price_mineral = raw_member.get("label"), raw_member.get("price_mineral")
            if not isinstance(label, str) or not isinstance(price_mineral, str) or not label or not price_mineral:
                raise RuntimeError(f"전략광종 가격 멤버 설정이 올바르지 않습니다: {group}")
            if label in seen:
                raise RuntimeError(f"전략광종 가격 그룹에 중복 광종이 있습니다: {group}/{label}")
            seen.add(label)
            result.append(StrategicPriceMember(group, raw_group["label"], label, price_mineral))
    return result
