from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def main() -> None:
    config = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    summary = json.loads((ROOT / "outputs" / "reports" / "actual_reanalysis_summary.json").read_text(encoding="utf-8"))
    checks = []

    def check(name: str, condition: bool, detail: str) -> None:
        checks.append({"check": name, "passed": bool(condition), "detail": detail})

    configured_controls = config["normal_saturdays_primary"] + config["normal_saturdays_sensitivity"] + config["october_normal_saturdays"]
    weekdays = {date: dt.datetime.strptime(date, "%Y%m%d").strftime("%A") for date in sorted(set(configured_controls))}
    check("all configured controls are Saturday", all(day == "Saturday" for day in weekdays.values()), str(weekdays))
    check("event absent from controls", config["event_date"] not in configured_controls, config["event_date"])
    check("holiday Saturday excluded from primary", "20230930" not in config["normal_saturdays_primary"], str(config["normal_saturdays_primary"]))

    required = [
        "README.md", "CLAIM_EVIDENCE_MAP.md", "RELEASE_MANIFEST.md", "docs/DATA_DICTIONARY.md", "docs/data_dictionary.csv",
        "docs/CORRECTIONS.md", "docs/METHODOLOGY.md", "docs/FEATURE_CATALOG.md", "docs/PORTFOLIO_GUIDE.md",
        "docs/MODEL_SELECTION.md", "docs/DATA_PROVENANCE.md", "docs/NEXT_SESSION_HANDOFF.md",
        "outputs/tables/join_audit.csv", "outputs/tables/join_exclusion_reasons.csv",
        "outputs/reports/actual_reanalysis_summary.json", "outputs/reports/raw_source_audit.json",
        "outputs/reports/supply_recovery_stress_test.json", "outputs/reports/model_readiness.json",
        "outputs/tables/actual_hourly_feature_table.csv",
        "outputs/tables/actual_supply_recovery_stress_test.csv", "outputs/figures/actual_od_bus_duration.svg",
        "outputs/figures/actual_gis_scope.svg", "outputs/figures/actual_supply_recovery_stress_test.svg", "index.html",
        "reproduce_public.py", ".github/workflows/validate.yml", "tests/test_pipeline.py",
    ]
    missing = [path for path in required if not (ROOT / path).exists()]
    check("required release files exist", not missing, str(missing))

    public_files = list((ROOT / "data" / "public").glob("*.csv"))
    check("public results labeled actual", bool(public_files) and all(path.name.startswith("actual_") for path in public_files), str([path.name for path in public_files]))
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    forbidden_sunday_dates = ["2023-09-03", "2023-09-10", "2023-09-17", "2023-09-24", "2023-10-01", "2023-10-15"]
    check("README has no old Sunday controls", not any(date in readme for date in forbidden_sunday_dates), str(forbidden_sunday_dates))

    scenario = summary["supply_recovery_stress_test"]
    check(
        "supply restore remains explicitly descriptive",
        scenario["status"].startswith("descriptive stress test") and scenario["stress_index_after_normal_supply_restore"] > 1,
        scenario["status"],
    )
    check(
        "README headline values match recalculated summary",
        "31.99분" in readme and "3.87배" in readme and "2.42배" in readme,
        "OD duration difference and stress-test headline values",
    )

    def half_hour_bins(filename: str) -> set[str]:
        import csv

        with (ROOT / "outputs" / "tables" / filename).open("r", encoding="utf-8-sig", newline="") as handle:
            return {row["half_hour"] for row in csv.DictReader(handle)}

    check("bus panel keeps both half-hour bins", half_hour_bins("actual_bus_30min_panel.csv") == {"0", "30"}, "expected 0 and 30")
    check("subway panel keeps both half-hour bins", half_hour_bins("actual_subway_30min_panel.csv") == {"0", "30"}, "expected 0 and 30")

    readiness = summary["model_readiness"]
    check(
        "analysis panel and local raw-date inventory are distinguished",
        readiness["analysis_panel_complete_cross_source_date_count"] == 2
        and readiness["local_complete_cross_source_date_count"] == 14
        and readiness["local_complete_saturdays"] == ["20231007", "20231014"],
        str({
            "panel": readiness["analysis_panel_complete_cross_source_dates"],
            "local": readiness["local_complete_cross_source_dates"],
        }),
    )
    check(
        "predictive benchmark is withheld for event-generalization limits",
        readiness["event_date_count"] == 1
        and readiness["local_normal_saturday_count"] == 1
        and readiness["status"].startswith("predictive benchmark withheld"),
        readiness["status"],
    )

    link_targets = re.findall(r"\]\(([^)]+)\)", readme)
    html_text = (ROOT / "index.html").read_text(encoding="utf-8")
    link_targets.extend(re.findall(r'(?:href|src)="([^"]+)"', html_text))
    local_targets = [target.split("#", 1)[0] for target in link_targets if not re.match(r"^[a-z]+:", target)]
    missing_links = sorted({target for target in local_targets if target and not (ROOT / target).exists()})
    check("README and portfolio local links resolve", not missing_links, str(missing_links))

    text_extensions = {".md", ".py", ".json", ".html", ".csv", ".txt"}
    text_files = [path for path in ROOT.rglob("*") if path.is_file() and path.suffix.lower() in text_extensions and "_audit" not in path.parts]
    forbidden_evaluation_terms = ["iso" + "tonic reg" + "ression", "mean absolute " + "error", "r-" + "squared", "r" + "²"]
    forbidden_legacy_headlines = ["184" + ",732", "53" + ",214", "13" + ",500명", "4" + ",000만원"]
    term_hits = []
    path_hits = []
    legacy_hits = []
    for path in text_files:
        content = path.read_text(encoding="utf-8", errors="ignore")
        lowered = content.lower()
        if any(term in lowered for term in forbidden_evaluation_terms):
            term_hits.append(str(path.relative_to(ROOT)))
        if re.search(r"[A-Za-z]:\\Users\\", content):
            path_hits.append(str(path.relative_to(ROOT)))
        if any(value in content for value in forbidden_legacy_headlines):
            legacy_hits.append(str(path.relative_to(ROOT)))
    check("removed evaluation claims are absent", not term_hits, str(term_hits))
    check("personal absolute paths are absent", not path_hits, str(path_hits))
    check("legacy presentation headline values are absent", not legacy_hits, str(legacy_hits))

    report = {"passed": all(item["passed"] for item in checks), "checks": checks}
    out = ROOT / "outputs" / "reports" / "release_validation.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if not report["passed"]:
        raise SystemExit(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
