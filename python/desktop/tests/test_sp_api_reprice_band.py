#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""追従帯判定の単体テスト。"""

from __future__ import annotations

import unittest
from datetime import datetime

from desktop.services.sp_api_reprice_band import (
    is_follow_rule,
    partition_skus_by_follow_band,
    resolve_active_rule_for_sku,
    sku_is_in_follow_band,
)


class TestSpApiRepriceBand(unittest.TestCase):
    def test_is_follow_rule_price_trace(self) -> None:
        self.assertTrue(is_follow_rule({"action": "priceTrace", "value": 1}))
        self.assertFalse(is_follow_rule({"action": "price_down_1"}))
        self.assertFalse(is_follow_rule({"action": "clearance"}))
        self.assertTrue(is_follow_rule({"action": "tp_down", "tp_target": "tp0_follow"}))

    def test_sku_follow_band_with_fake_config(self) -> None:
        config = {
            "default_profile": "6",
            "rule_profiles": {
                "6": {
                    "reprice_rules": [
                        {"days_from": 90, "action": "priceTrace", "tp_target": "tp0_follow"},
                        {"days_from": 180, "action": "price_down_1", "tp_target": "tp1"},
                    ]
                }
            },
        }
        today = datetime(2026, 10, 23)
        self.assertTrue(
            sku_is_in_follow_band("20260801-B000TEST-6-1000-1", config=config, today=today)
        )
        self.assertFalse(
            sku_is_in_follow_band("20260401-B000TEST-6-1000-1", config=config, today=today)
        )

    def test_partition_skus(self) -> None:
        config = {
            "default_profile": "6",
            "rule_profiles": {
                "6": {
                    "reprice_rules": [
                        {"days_from": 90, "action": "priceTrace"},
                        {"days_from": 365, "action": "price_down_1"},
                    ]
                }
            },
        }
        today = datetime(2026, 10, 23)
        parts = partition_skus_by_follow_band(
            ["20260801-X-6-1", "20260101-Y-6-1"],
            config=config,
            today=today,
        )
        self.assertIn("20260801-X-6-1", parts["follow"])
        self.assertIn("20260101-Y-6-1", parts["weekly"])

    def test_resolve_active_rule_returns_profile(self) -> None:
        config = {
            "default_profile": "6",
            "rule_profiles": {
                "3": {"reprice_rules": [{"days_from": 30, "action": "maintain"}]},
                "6": {"reprice_rules": [{"days_from": 30, "action": "priceTrace"}]},
            },
        }
        rule, days, profile = resolve_active_rule_for_sku(
            "20261001-B0-3-1000-1",
            config=config,
            today=datetime(2026, 10, 20),
        )
        self.assertEqual(profile, "3")
        self.assertEqual(rule["action"], "maintain")
        self.assertGreaterEqual(days, 0)


if __name__ == "__main__":
    unittest.main()
