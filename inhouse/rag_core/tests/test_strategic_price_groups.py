# -*- coding: utf-8 -*-
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from rag_core.ragkit.strategic_price_groups import load_strategic_price_members  # noqa: E402


class StrategicPriceGroupsTest(unittest.TestCase):
    def test_yaml_preserves_user_specified_groups_and_alias(self):
        six = load_strategic_price_members(("strategic_six",))
        ten = load_strategic_price_members(("strategic_ten",))
        battery = load_strategic_price_members(("battery_five",))
        self.assertEqual([item.label for item in six], ["유연탄", "우라늄", "철광석", "구리", "아연", "니켈"])
        self.assertEqual([item.label for item in battery], ["리튬", "니켈", "코발트", "망간", "흑연"])
        self.assertEqual([item.label for item in ten], ["리튬", "니켈", "코발트", "망간", "흑연", "네오디윰", "디스프로슘", "터븀", "세륨", "란탄"])
        self.assertEqual(next(item.price_mineral for item in six if item.label == "구리"), "동")
        self.assertEqual(next(item.price_mineral for item in ten if item.label == "네오디윰"), "네오디뮴")
