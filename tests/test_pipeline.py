from __future__ import annotations

import unittest

from src.pipeline import _half_hour, _hour, build_supply_recovery_scenario


class TimeParsingTest(unittest.TestCase):
    def test_hour_parser_rejects_half_hour_marker(self) -> None:
        self.assertEqual(_hour("`23`"), 23)
        self.assertIsNone(_hour("30"))

    def test_half_hour_parser_keeps_both_bins(self) -> None:
        self.assertEqual(_half_hour("`00`"), 0)
        self.assertEqual(_half_hour("`30`"), 30)
        self.assertIsNone(_half_hour("15"))


class ScenarioTest(unittest.TestCase):
    def test_normal_supply_restore_is_not_labeled_as_bus_count(self) -> None:
        bus = [
            {
                "hour": hour,
                "target": 20.0,
                "normal_avg": 10.0,
                "strict_20231014": 10.0,
                "target_minus_normal": 10.0,
                "target_over_normal": 2.0,
                "is_event_window": int(hour in range(18, 24)),
            }
            for hour in range(24)
        ]
        supply = [
            {
                "hour": hour,
                "target": 5.0,
                "normal_avg": 10.0,
                "strict_20231014": 10.0,
                "target_minus_normal": -5.0,
                "target_over_normal": 0.5,
                "is_event_window": int(hour in range(18, 24)),
            }
            for hour in range(24)
        ]
        rows, report = build_supply_recovery_scenario(bus, supply)
        self.assertEqual(rows[18]["stress_index_after_normal_supply_restore"], 2.0)
        self.assertTrue(report["status"].startswith("descriptive stress test"))


if __name__ == "__main__":
    unittest.main()
