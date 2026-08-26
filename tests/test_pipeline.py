from __future__ import annotations

import unittest

from src.pipeline import _half_hour, _hour, build_model_readiness_report, build_supply_recovery_scenario


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


class ModelReadinessTest(unittest.TestCase):
    def test_loaded_panel_and_local_inventory_are_reported_separately(self) -> None:
        panel_dates = ["20231007", "20231014"]
        panel = [{"date": date} for date in panel_dates]
        local_dates = {
            source: {f"202310{day:02d}" for day in range(2, 16)}
            for source in ["od", "stay", "bus", "subway", "tpss"]
        }
        report = build_model_readiness_report(panel, panel, panel, panel, panel, local_dates)
        self.assertEqual(report["analysis_panel_complete_cross_source_date_count"], 2)
        self.assertEqual(report["local_complete_cross_source_date_count"], 14)
        self.assertEqual(report["local_complete_saturdays"], ["20231007", "20231014"])
        self.assertEqual(report["local_normal_saturday_count"], 1)


if __name__ == "__main__":
    unittest.main()
