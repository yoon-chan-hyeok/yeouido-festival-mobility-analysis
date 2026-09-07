from __future__ import annotations

import json

from src.io_utils import read_csv_rows, write_csv, write_json
from src.pipeline import (
    FIGURE_DIR,
    PUBLIC_DIR,
    REPORT_DIR,
    TABLE_DIR,
    build_supply_recovery_scenario,
    make_figures,
    write_portfolio_page,
)


def _read(name: str, numeric_fields: list[str]) -> list[dict]:
    return read_csv_rows(PUBLIC_DIR / name, numeric_fields)


def main() -> dict:
    od = _read(
        "actual_od_event_vs_saturday.csv",
        [
            "hour", "target_avg_duration", "normal_pooled_avg_duration", "strict_20231014_avg_duration",
            "duration_diff", "target_od_cnts", "normal_avg_od_cnts", "strict_20231014_od_cnts",
            "od_cnts_diff", "is_event_window",
        ],
    )
    compare_fields = [
        "hour", "target", "normal_avg", "strict_20231014", "target_minus_normal",
        "target_over_normal", "is_event_window",
    ]
    bus = _read("actual_bus_boarding_event_vs_saturday.csv", compare_fields)
    subway = _read("actual_subway_boarding_event_vs_saturday.csv", compare_fields)
    tpss = _read("actual_tpss_event_vs_saturday.csv", compare_fields)

    scenario_rows, scenario_report = build_supply_recovery_scenario(bus, tpss)
    write_csv(TABLE_DIR / "actual_supply_recovery_stress_test.csv", scenario_rows)
    write_json(REPORT_DIR / "supply_recovery_stress_test.json", scenario_report)
    make_figures(od, bus, subway, tpss, scenario_rows)
    summary = json.loads((REPORT_DIR / "actual_reanalysis_summary.json").read_text(encoding="utf-8"))
    write_portfolio_page(summary, scenario_report)
    print(json.dumps(scenario_report, ensure_ascii=False, indent=2))
    return scenario_report


if __name__ == "__main__":
    main()
