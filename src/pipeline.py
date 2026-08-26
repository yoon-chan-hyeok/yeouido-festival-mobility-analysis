from __future__ import annotations

import csv
import datetime as dt
import html
import json
import math
import os
import re
from collections import Counter, defaultdict
from pathlib import Path

from .io_utils import normalize_code, normalize_name, parse_number, read_csv_rows, read_json, write_csv, write_json
from .spatial import find_single, load_bus_stops_in_yeouido, load_yeouido_geometry


RELEASE_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = RELEASE_ROOT.parent
CONFIG = read_json(RELEASE_ROOT / "config.json")
TABLE_DIR = RELEASE_ROOT / "outputs" / "tables"
FIGURE_DIR = RELEASE_ROOT / "outputs" / "figures"
REPORT_DIR = RELEASE_ROOT / "outputs" / "reports"
PUBLIC_DIR = RELEASE_ROOT / "data" / "public"


def _ensure_dirs() -> None:
    for path in [TABLE_DIR, FIGURE_DIR, REPORT_DIR, PUBLIC_DIR]:
        path.mkdir(parents=True, exist_ok=True)


def _date_file(prefix: str, date: str) -> Path:
    matches = list((WORKSPACE_ROOT / "raw_data").rglob(f"{prefix}_{date}_1.csv"))
    if not matches:
        raise FileNotFoundError(f"No {prefix} raw file for {date}")
    preferred = [path for path in matches if f"{prefix}_sat_data" in str(path) or "sat_data" in str(path)]
    return sorted(preferred or matches, key=lambda path: len(str(path)))[0]


def _hour(value) -> int | None:
    try:
        result = int(str(value or "").strip().replace("`", "").split(":")[0])
        return result if 0 <= result <= 23 else None
    except ValueError:
        return None


def _half_hour(value) -> int | None:
    try:
        result = int(str(value or "").strip().replace("`", ""))
        return result if result in {0, 30} else None
    except ValueError:
        return None


def load_od_panel(dates: list[str]) -> tuple[list[dict], dict]:
    yeouido = CONFIG["yeouido_hdong_code"]
    seoul_prefix = CONFIG["seoul_code_prefix"]
    mode_names = {0: "car", 1: "bus"}
    output = []
    audits = []
    for date in dates:
        path = _date_file("od", date)
        buckets = defaultdict(lambda: {"od_cnts": 0.0, "weighted_duration": 0.0, "source_rows": 0})
        source_rows = valid_rows = scope_rows = 0
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                source_rows += 1
                origin = normalize_code(row.get("origin_hdong_cd"))
                destination = normalize_code(row.get("dest_hdong_cd"))
                modal = int(parse_number(row.get("modal"), default=-999))
                duration = parse_number(row.get("od_duration_avg"), default=-1)
                count = parse_number(row.get("od_cnts"), default=-1)
                if count <= 0 or duration < 0:
                    continue
                valid_rows += 1
                flow = None
                time_hour = None
                if origin == yeouido and destination.startswith(seoul_prefix) and destination != yeouido:
                    flow = "departure"
                    time_hour = _hour(row.get("start_time"))
                elif destination == yeouido and origin.startswith(seoul_prefix) and origin != yeouido:
                    flow = "arrival"
                    time_hour = _hour(row.get("end_time"))
                if flow is None or time_hour is None:
                    continue
                scope_rows += 1
                for mode in ["all", mode_names.get(modal)]:
                    if mode is None:
                        continue
                    bucket = buckets[(flow, mode, time_hour)]
                    bucket["od_cnts"] += count
                    bucket["weighted_duration"] += count * duration
                    bucket["source_rows"] += 1
        for (flow, mode, time_hour), values in sorted(buckets.items()):
            output.append(
                {
                    "date": date,
                    "flow": flow,
                    "mode": mode,
                    "hour": time_hour,
                    **values,
                    "avg_duration": values["weighted_duration"] / values["od_cnts"] if values["od_cnts"] else "",
                }
            )
        audits.append(
            {
                "date": date,
                "source_file": str(path.relative_to(WORKSPACE_ROOT)),
                "source_rows": source_rows,
                "valid_rows": valid_rows,
                "scope_rows": scope_rows,
                "scope_rate": scope_rows / source_rows if source_rows else 0,
            }
        )
    return output, {"files": audits}


def load_stay_panel(dates: list[str]) -> tuple[list[dict], dict]:
    output = []
    audits = []
    for date in dates:
        path = _date_file("stay", date)
        buckets = defaultdict(float)
        source_rows = matched_rows = 0
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                source_rows += 1
                if normalize_code(row.get("hdong_cd")) != CONFIG["yeouido_hdong_code"]:
                    continue
                time_hour = _hour(row.get("time"))
                if time_hour is None:
                    continue
                matched_rows += 1
                buckets[time_hour] += parse_number(row.get("stay_cnts"))
        output.extend({"date": date, "hour": hour, "stay_cnts": value} for hour, value in sorted(buckets.items()))
        audits.append(
            {
                "date": date,
                "source_file": str(path.relative_to(WORKSPACE_ROOT)),
                "source_rows": source_rows,
                "matched_rows": matched_rows,
                "scope_rate": matched_rows / source_rows if source_rows else 0,
            }
        )
    return output, {"files": audits}


def _clean(value) -> str:
    return str(value or "").strip().strip("`")


def _source_row_date(row: dict) -> str:
    try:
        return f"{int(_clean(row['YEAR'])):04d}{int(_clean(row['MONTH'])):02d}{int(_clean(row['DAY'])):02d}"
    except (KeyError, ValueError):
        return ""


def load_bus_panel(dates: list[str], gis_stops: list[dict]) -> tuple[list[dict], list[dict]]:
    name_counts = Counter(row["normalized_stop_name"] for row in gis_stops if row["normalized_stop_name"])
    valid_names = set(name_counts)
    output = []
    audits = []
    for date in dates:
        path = find_single(WORKSPACE_ROOT / "seoul_new_data", f"TBDM_TRANSIT_STAT_BUS_{date}.csv")
        buckets = defaultdict(lambda: {"geton": 0.0, "getoff": 0.0})
        source_rows = matched_rows = ambiguous_rows = 0
        source_pairs, matched_pairs, observed_reference_names = set(), set(), set()
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                if _source_row_date(row) != date:
                    continue
                source_rows += 1
                station_id = _clean(row.get("STATION_ID"))
                name = normalize_name(_clean(row.get("STATION_NM")))
                source_pairs.add((station_id, name))
                if name not in valid_names:
                    continue
                time_hour = _hour(_clean(row.get("HOUR")))
                half_hour = _half_hour(_clean(row.get("HALF_HOUR")))
                if time_hour is None or half_hour is None:
                    continue
                matched_rows += 1
                matched_pairs.add((station_id, name))
                observed_reference_names.add(name)
                ambiguous_rows += int(name_counts[name] > 1)
                bucket = buckets[(time_hour, half_hour)]
                bucket["geton"] += parse_number(_clean(row.get("GETON_CNT")))
                bucket["getoff"] += parse_number(_clean(row.get("GETOFF_CNT")))
        for (time_hour, half_hour), values in sorted(buckets.items()):
            output.append(
                {"date": date, "hour": time_hour, "half_hour": half_hour, **values, "total": values["geton"] + values["getoff"]}
            )
        audits.append(
            {
                "source": "bus_30min_to_yeouido_gis",
                "date": date,
                "join_key": "normalized station name",
                "source_rows": source_rows,
                "matched_rows": matched_rows,
                "matched_row_rate": matched_rows / source_rows if source_rows else 0,
                "source_unique_units": len(source_pairs),
                "matched_unique_units": len(matched_pairs),
                "matched_unique_rate": len(matched_pairs) / len(source_pairs) if source_pairs else 0,
                "target_reference_units": len(valid_names),
                "observed_reference_units": len(observed_reference_names),
                "reference_coverage_rate": len(observed_reference_names) / len(valid_names) if valid_names else 0,
                "ambiguous_matched_rows": ambiguous_rows,
                "excluded_reason": "name absent from Yeouido GIS; duplicate GIS names retained only in area aggregate",
            }
        )
    return output, audits


def load_subway_panel(dates: list[str]) -> tuple[list[dict], list[dict]]:
    selected_names = {normalize_name(name) for name in CONFIG["subway_station_names"]}
    output = []
    audits = []
    for date in dates:
        path = find_single(WORKSPACE_ROOT / "seoul_new_data", f"TBDM_TRANSIT_STAT_SUBWAY_{date}.csv")
        buckets = defaultdict(lambda: {"geton": 0.0, "getoff": 0.0})
        source_rows = matched_rows = 0
        observed_names = set()
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                if _source_row_date(row) != date:
                    continue
                source_rows += 1
                name = normalize_name(_clean(row.get("STATION_NM")))
                if name not in selected_names:
                    continue
                time_hour = _hour(_clean(row.get("HOUR")))
                half_hour = _half_hour(_clean(row.get("HALF_HOUR")))
                if time_hour is None or half_hour is None:
                    continue
                matched_rows += 1
                observed_names.add(name)
                bucket = buckets[(time_hour, half_hour)]
                bucket["geton"] += parse_number(_clean(row.get("GETON_CNT")))
                bucket["getoff"] += parse_number(_clean(row.get("GETOFF_CNT")))
        for (time_hour, half_hour), values in sorted(buckets.items()):
            output.append(
                {"date": date, "hour": time_hour, "half_hour": half_hour, **values, "total": values["geton"] + values["getoff"]}
            )
        audits.append(
            {
                "source": "subway_30min_station_filter",
                "date": date,
                "join_key": "configured normalized station name",
                "source_rows": source_rows,
                "matched_rows": matched_rows,
                "matched_row_rate": matched_rows / source_rows if source_rows else 0,
                "source_unique_units": len(selected_names),
                "matched_unique_units": len(observed_names),
                "matched_unique_rate": len(observed_names) / len(selected_names),
                "target_reference_units": len(selected_names),
                "observed_reference_units": len(observed_names),
                "reference_coverage_rate": len(observed_names) / len(selected_names),
                "ambiguous_matched_rows": 0,
                "excluded_reason": "station not in configured Yeouido subway station list",
            }
        )
    return output, audits


def load_tpss_panel(dates: list[str], gis_stops: list[dict]) -> tuple[list[dict], list[dict]]:
    stop_ids = {row["gis_stop_id"] for row in gis_stops if row["gis_stop_id"]}
    totals = defaultdict(float)
    source_rows = Counter()
    matched_rows = Counter()
    matched_stops = defaultdict(set)
    matched_routes = defaultdict(set)
    for path in sorted((WORKSPACE_ROOT / "tpss_sta_route_hturn_202310").glob("*.csv")):
        with path.open("r", encoding="cp949", newline="") as handle:
            reader = csv.reader(handle)
            next(reader, None)
            for row in reader:
                if len(row) < 29:
                    continue
                date = normalize_code(row[0])
                if date not in dates:
                    continue
                source_rows[date] += 1
                stop_id = normalize_code(row[2])
                if stop_id not in stop_ids:
                    continue
                matched_rows[date] += 1
                matched_stops[date].add(stop_id)
                matched_routes[date].add(normalize_code(row[1]))
                for time_hour in range(24):
                    totals[(date, time_hour)] += parse_number(row[4 + time_hour])
    output = [
        {"date": date, "hour": hour, "stop_count": value}
        for (date, hour), value in sorted(totals.items())
    ]
    audits = []
    for date in dates:
        audits.append(
            {
                "source": "tpss_to_yeouido_gis",
                "date": date,
                "join_key": "GIS STN_IDN == TPSS station ID",
                "source_rows": source_rows[date],
                "matched_rows": matched_rows[date],
                "matched_row_rate": matched_rows[date] / source_rows[date] if source_rows[date] else 0,
                "source_unique_units": len(stop_ids),
                "matched_unique_units": len(matched_stops[date]),
                "matched_unique_rate": len(matched_stops[date]) / len(stop_ids) if stop_ids else 0,
                "target_reference_units": len(stop_ids),
                "observed_reference_units": len(matched_stops[date]),
                "reference_coverage_rate": len(matched_stops[date]) / len(stop_ids) if stop_ids else 0,
                "ambiguous_matched_rows": 0,
                "observed_route_ids": len(matched_routes[date]),
                "excluded_reason": "station ID outside exact Yeouido GIS stop-ID set",
            }
        )
    return output, audits


def load_kikmix_audit() -> dict:
    path = find_single(WORKSPACE_ROOT / "데이터분석 분야_데이터정의서", "KIKmix_20230701.csv")
    source_rows = 0
    matches = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            source_rows += 1
            if normalize_code(row.get("행정동코드")) == CONFIG["yeouido_hdong_code"]:
                matches.append(row)
    if not matches:
        raise ValueError("Yeouido administrative code is absent from KIKmix_20230701.csv")
    return {
        "source_file": str(path.relative_to(WORKSPACE_ROOT)),
        "source_rows": source_rows,
        "matched_rows": len(matches),
        "yeouido_hdong_code": CONFIG["yeouido_hdong_code"],
        "sido_names": sorted({row.get("시도명", "") for row in matches}),
        "sgg_names": sorted({row.get("시군구명", "") for row in matches}),
        "hdong_names": sorted({row.get("읍면동명", "") for row in matches}),
    }


def group_hour(panel: list[dict], metrics: list[str]) -> list[dict]:
    buckets = defaultdict(lambda: defaultdict(float))
    for row in panel:
        for metric in metrics:
            buckets[(row["date"], int(row["hour"]))][metric] += float(row[metric])
    return [{"date": date, "hour": hour, **values} for (date, hour), values in sorted(buckets.items())]


def compare_sum(panel: list[dict], metric: str, controls: list[str], strict_date: str) -> list[dict]:
    lookup = {(row["date"], int(row["hour"])): float(row[metric]) for row in panel}
    rows = []
    for hour in range(24):
        target = lookup.get((CONFIG["event_date"], hour), 0.0)
        normal = sum(lookup.get((date, hour), 0.0) for date in controls) / len(controls)
        strict = lookup.get((strict_date, hour), 0.0)
        rows.append(
            {
                "hour": hour,
                "target": target,
                "normal_avg": normal,
                "strict_20231014": strict,
                "target_minus_normal": target - normal,
                "target_over_normal": target / normal if normal else "",
                "is_event_window": int(hour in CONFIG["event_impact_hours"]),
            }
        )
    return rows


def _pooled(rows: list[dict]) -> float | None:
    count = sum(float(row["od_cnts"]) for row in rows)
    return sum(float(row["weighted_duration"]) for row in rows) / count if count else None


def compare_od(panel: list[dict], controls: list[str], strict_date: str) -> list[dict]:
    buckets = defaultdict(list)
    for row in panel:
        buckets[(row["flow"], row["mode"], int(row["hour"]), row["date"])].append(row)
    output = []
    for flow in ["arrival", "departure"]:
        for mode in ["all", "car", "bus"]:
            for hour in range(24):
                target_rows = buckets.get((flow, mode, hour, CONFIG["event_date"]), [])
                normal_rows = [row for date in controls for row in buckets.get((flow, mode, hour, date), [])]
                strict_rows = buckets.get((flow, mode, hour, strict_date), [])
                target_duration = _pooled(target_rows)
                normal_duration = _pooled(normal_rows)
                strict_duration = _pooled(strict_rows)
                target_count = sum(float(row["od_cnts"]) for row in target_rows)
                strict_count = sum(float(row["od_cnts"]) for row in strict_rows)
                normal_count = sum(
                    sum(float(row["od_cnts"]) for row in buckets.get((flow, mode, hour, date), [])) for date in controls
                ) / len(controls)
                output.append(
                    {
                        "flow": flow,
                        "mode": mode,
                        "hour": hour,
                        "target_avg_duration": target_duration if target_duration is not None else "",
                        "normal_pooled_avg_duration": normal_duration if normal_duration is not None else "",
                        "strict_20231014_avg_duration": strict_duration if strict_duration is not None else "",
                        "duration_diff": target_duration - normal_duration if target_duration is not None and normal_duration is not None else "",
                        "target_od_cnts": target_count,
                        "normal_avg_od_cnts": normal_count,
                        "strict_20231014_od_cnts": strict_count,
                        "od_cnts_diff": target_count - normal_count,
                        "is_event_window": int(hour in CONFIG["event_impact_hours"]),
                    }
                )
    return output


def _sum_columns(rows: list[dict], columns: list[str]) -> dict:
    return {column: sum(float(row[column]) for row in rows) for column in columns}


def summary_from_compare(compare: list[dict], source: str) -> dict:
    columns = ["target", "normal_avg", "strict_20231014", "target_minus_normal"]
    return {
        "source": source,
        "all_day": _sum_columns(compare, columns),
        "event_window_18_23": _sum_columns([row for row in compare if row["is_event_window"]], columns),
    }


def _safe_ratio(numerator: float, denominator: float) -> float | str:
    return numerator / denominator if denominator else ""


def build_hourly_feature_table(
    od_compare: list[dict],
    stay_compare: list[dict],
    bus_compare: list[dict],
    subway_compare: list[dict],
    tpss_compare: list[dict],
) -> list[dict]:
    departure_bus = {
        int(row["hour"]): row
        for row in od_compare
        if row["flow"] == "departure" and row["mode"] == "bus"
    }
    stay = {int(row["hour"]): row for row in stay_compare}
    bus = {int(row["hour"]): row for row in bus_compare}
    subway = {int(row["hour"]): row for row in subway_compare}
    tpss = {int(row["hour"]): row for row in tpss_compare}
    rows = []
    for hour in range(24):
        od_row = departure_bus[hour]
        stay_row = stay[hour]
        bus_row = bus[hour]
        subway_row = subway[hour]
        tpss_row = tpss[hour]
        event_bus = float(bus_row["target"])
        normal_bus = float(bus_row["normal_avg"])
        event_supply = float(tpss_row["target"])
        normal_supply = float(tpss_row["normal_avg"])
        event_load = _safe_ratio(event_bus, event_supply)
        normal_load = _safe_ratio(normal_bus, normal_supply)
        stress = _safe_ratio(float(event_load), float(normal_load)) if event_load != "" and normal_load != "" else ""
        rows.append(
            {
                "hour": hour,
                "is_event_window": int(hour in CONFIG["event_impact_hours"]),
                "event_departure_bus_od_cnts": od_row["target_od_cnts"],
                "normal_departure_bus_od_cnts": od_row["normal_avg_od_cnts"],
                "departure_bus_od_cnts_diff": od_row["od_cnts_diff"],
                "event_departure_bus_avg_duration_min": od_row["target_avg_duration"],
                "normal_departure_bus_avg_duration_min": od_row["normal_pooled_avg_duration"],
                "departure_bus_duration_diff_min": od_row["duration_diff"],
                "event_stay_cnts": stay_row["target"],
                "normal_stay_cnts": stay_row["normal_avg"],
                "stay_cnts_diff": stay_row["target_minus_normal"],
                "event_bus_boardings_proxy": event_bus,
                "normal_bus_boardings_proxy": normal_bus,
                "bus_boardings_proxy_diff": bus_row["target_minus_normal"],
                "event_subway_boardings_proxy": subway_row["target"],
                "normal_subway_boardings_proxy": subway_row["normal_avg"],
                "subway_boardings_proxy_diff": subway_row["target_minus_normal"],
                "event_tpss_stop_count": event_supply,
                "normal_tpss_stop_count": normal_supply,
                "tpss_stop_count_diff": tpss_row["target_minus_normal"],
                "event_boardings_per_stop_count": event_load,
                "normal_boardings_per_stop_count": normal_load,
                "demand_supply_stress_index": stress,
            }
        )
    return rows


def build_supply_recovery_scenario(bus_compare: list[dict], tpss_compare: list[dict]) -> tuple[list[dict], dict]:
    supply = {int(row["hour"]): row for row in tpss_compare}
    rows = []
    for bus_row in bus_compare:
        hour = int(bus_row["hour"])
        supply_row = supply[hour]
        event_demand = float(bus_row["target"])
        normal_demand = float(bus_row["normal_avg"])
        event_supply = float(supply_row["target"])
        normal_supply = float(supply_row["normal_avg"])
        restored_supply = max(event_supply, normal_supply)
        added_to_normal = restored_supply - event_supply
        normal_load = _safe_ratio(normal_demand, normal_supply)
        current_load = _safe_ratio(event_demand, event_supply)
        restored_load = _safe_ratio(event_demand, restored_supply)
        required_supply = event_demand / float(normal_load) if normal_load not in {"", 0} else ""
        rows.append(
            {
                "hour": hour,
                "is_event_window": int(hour in CONFIG["event_impact_hours"]),
                "event_boardings_proxy": event_demand,
                "normal_boardings_proxy": normal_demand,
                "event_stop_count": event_supply,
                "normal_stop_count": normal_supply,
                "added_stop_count_to_restore_normal_supply": added_to_normal,
                "restored_stop_count": restored_supply,
                "event_boardings_per_stop_count": current_load,
                "normal_boardings_per_stop_count": normal_load,
                "current_stress_index": _safe_ratio(float(current_load), float(normal_load)) if current_load != "" and normal_load != "" else "",
                "stress_index_after_normal_supply_restore": _safe_ratio(float(restored_load), float(normal_load)) if restored_load != "" and normal_load != "" else "",
                "stop_count_index_required_for_normal_load": required_supply,
                "additional_stop_count_index_for_normal_load": float(required_supply) - event_supply if required_supply != "" else "",
            }
        )

    window = [row for row in rows if row["is_event_window"]]
    event_demand = sum(row["event_boardings_proxy"] for row in window)
    normal_demand = sum(row["normal_boardings_proxy"] for row in window)
    event_supply = sum(row["event_stop_count"] for row in window)
    normal_supply = sum(row["normal_stop_count"] for row in window)
    restored_supply = max(event_supply, normal_supply)
    normal_load = normal_demand / normal_supply if normal_supply else 0
    current_load = event_demand / event_supply if event_supply else 0
    restored_load = event_demand / restored_supply if restored_supply else 0
    required_supply = event_demand / normal_load if normal_load else 0
    report = {
        "status": "descriptive stress test; not optimization, dispatch recommendation, or causal policy effect",
        "window": "18:00-23:59",
        "event_boardings_proxy": event_demand,
        "normal_boardings_proxy": normal_demand,
        "event_stop_count": event_supply,
        "normal_stop_count": normal_supply,
        "supply_gap_to_normal": max(normal_supply - event_supply, 0),
        "event_boardings_per_stop_count": current_load,
        "normal_boardings_per_stop_count": normal_load,
        "current_stress_index": current_load / normal_load if normal_load else None,
        "stress_index_after_normal_supply_restore": restored_load / normal_load if normal_load else None,
        "stop_count_index_required_for_normal_load": required_supply,
        "additional_stop_count_index_for_normal_load": max(required_supply - event_supply, 0),
        "interpretation": "Restoring the TPSS stop-count index to the normal Saturday level does not restore the normal per-stop demand burden when demand remains elevated.",
    }
    return rows, report


def inventory_local_source_dates() -> dict[str, set[str]]:
    """Inventory dated source files without loading their row-level contents."""
    date_sets = {name: set() for name in ["od", "stay", "bus", "subway", "tpss"]}
    raw_root = WORKSPACE_ROOT / "raw_data"
    if raw_root.exists():
        for path in raw_root.rglob("*.csv"):
            for source in ["od", "stay"]:
                match = re.fullmatch(rf"{source}_(20\d{{6}})_1\.csv", path.name, flags=re.IGNORECASE)
                if match:
                    date_sets[source].add(match.group(1))

    seoul_root = WORKSPACE_ROOT / "seoul_new_data"
    if seoul_root.exists():
        patterns = {
            "bus": re.compile(r"TBDM_TRANSIT_STAT_BUS_(20\d{6})\.csv", re.IGNORECASE),
            "subway": re.compile(r"TBDM_TRANSIT_STAT_(?:SUBWAY|TRAIN)_(20\d{6})\.csv", re.IGNORECASE),
        }
        for path in seoul_root.rglob("*.csv"):
            for source, pattern in patterns.items():
                match = pattern.fullmatch(path.name)
                if match:
                    date_sets[source].add(match.group(1))

    range_pattern = re.compile(
        r"tpss_sta_route_hturn_(20\d{2})\.(\d{2})\.(\d{2})-(\d{2})\.(\d{2})\.csv",
        re.IGNORECASE,
    )
    for folder in WORKSPACE_ROOT.glob("tpss_sta_route_hturn_*"):
        if not folder.is_dir():
            continue
        for path in folder.glob("*.csv"):
            match = range_pattern.fullmatch(path.name)
            if not match:
                continue
            year, start_month, start_day, end_month, end_day = map(int, match.groups())
            start = dt.date(year, start_month, start_day)
            end_year = year + int(end_month < start_month)
            end = dt.date(end_year, end_month, end_day)
            current = start
            while current <= end:
                date_sets["tpss"].add(current.strftime("%Y%m%d"))
                current += dt.timedelta(days=1)
    return date_sets


def build_model_readiness_report(
    od_panel: list[dict],
    stay_panel: list[dict],
    bus_panel: list[dict],
    subway_panel: list[dict],
    tpss_panel: list[dict],
    local_date_sets: dict[str, set[str]] | None = None,
) -> dict:
    panel_date_sets = {
        "od": {row["date"] for row in od_panel},
        "stay": {row["date"] for row in stay_panel},
        "bus": {row["date"] for row in bus_panel},
        "subway": {row["date"] for row in subway_panel},
        "tpss": {row["date"] for row in tpss_panel},
    }
    panel_complete_dates = set.intersection(*panel_date_sets.values())
    local_date_sets = local_date_sets or panel_date_sets
    local_complete_dates = set.intersection(*local_date_sets.values())
    local_saturdays = {
        date for date in local_complete_dates
        if dt.datetime.strptime(date, "%Y%m%d").strftime("%A") == "Saturday"
    }
    normal_saturdays = local_saturdays - {CONFIG["event_date"]}
    return {
        "status": "predictive benchmark withheld because the local common window contains only one event Saturday and one normal Saturday",
        "analysis_panel_dates_by_source": {name: sorted(values) for name, values in panel_date_sets.items()},
        "analysis_panel_complete_cross_source_dates": sorted(panel_complete_dates),
        "analysis_panel_complete_cross_source_date_count": len(panel_complete_dates),
        "local_raw_dates_by_source": {name: sorted(values) for name, values in local_date_sets.items()},
        "local_complete_cross_source_dates": sorted(local_complete_dates),
        "local_complete_cross_source_date_count": len(local_complete_dates),
        "local_complete_saturdays": sorted(local_saturdays),
        "local_normal_saturday_count": len(normal_saturdays),
        "event_date_count": int(CONFIG["event_date"] in local_complete_dates),
        "readiness_interpretation": "Fourteen calendar dates can support date-grouped exploratory checks, but one event date cannot establish out-of-event generalization and one normal Saturday is not a stable same-weekday benchmark.",
        "candidate_target": "Yeouido departure-bus travel-time difference in minutes",
        "candidate_features": [
            "departure bus OD count",
            "stay population",
            "bus boarding proxy",
            "subway boarding proxy",
            "TPSS stop count",
            "hour and event-window flag",
        ],
        "selection_plan": [
            {"model": "Ridge", "role": "interpretable regularized baseline"},
            {"model": "Gradient Boosting", "role": "primary nonlinear tabular candidate"},
            {"model": "Random Forest", "role": "robustness comparison for nonlinear interactions"},
            {"model": "SVR", "role": "scaled-feature comparison when the sample grows"},
        ],
        "validation_plan": "group observations by date and hold out entire dates; never use a random row split",
        "primary_metric": "MAE in minutes, compared with a normal-Saturday baseline",
    }


def _svg_line_chart(
    path: Path,
    title: str,
    x_label: str,
    y_label: str,
    series: list[tuple[str, str, list[tuple[float, float]]]],
    shade_event_window: bool = True,
) -> None:
    width, height = 1000, 520
    margin = {"left": 85, "right": 35, "top": 65, "bottom": 70}
    all_points = [point for _, _, points in series for point in points if point[1] is not None and math.isfinite(point[1])]
    xs = [point[0] for point in all_points]
    ys = [point[1] for point in all_points]
    x_min, x_max = min(xs), max(xs)
    y_min, y_max = min(ys), max(ys)
    if y_min == y_max:
        y_min, y_max = y_min - 1, y_max + 1
    pad = (y_max - y_min) * 0.08
    y_min, y_max = y_min - pad, y_max + pad
    plot_w = width - margin["left"] - margin["right"]
    plot_h = height - margin["top"] - margin["bottom"]
    sx = lambda value: margin["left"] + (value - x_min) / (x_max - x_min or 1) * plot_w
    sy = lambda value: margin["top"] + (y_max - value) / (y_max - y_min) * plot_h
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#fffdf8"/>',
        f'<text x="{width/2}" y="34" text-anchor="middle" font-family="Segoe UI, sans-serif" font-size="22" font-weight="700">{html.escape(title)}</text>',
    ]
    if shade_event_window and x_min <= 18 <= x_max:
        shade_end = min(23, x_max)
        parts.append(f'<rect x="{sx(18):.1f}" y="{margin["top"]}" width="{sx(shade_end)-sx(18):.1f}" height="{plot_h}" fill="#f59e0b" opacity="0.10"/>')
    for index in range(6):
        value = y_min + (y_max - y_min) * index / 5
        y = sy(value)
        parts.append(f'<line x1="{margin["left"]}" y1="{y:.1f}" x2="{width-margin["right"]}" y2="{y:.1f}" stroke="#d6d3d1"/>')
        parts.append(f'<text x="{margin["left"]-10}" y="{y+4:.1f}" text-anchor="end" font-family="Segoe UI" font-size="12">{value:.1f}</text>')
    for index in range(7):
        value = x_min + (x_max - x_min) * index / 6
        x = sx(value)
        label = f"{value:.0f}" if abs(value) >= 10 or value.is_integer() else f"{value:.1f}"
        parts.append(f'<text x="{x:.1f}" y="{height-margin["bottom"]+25}" text-anchor="middle" font-family="Segoe UI" font-size="12">{label}</text>')
    for name, color, points in series:
        clean_points = [(x, y) for x, y in points if y is not None and math.isfinite(y)]
        polyline = " ".join(f"{sx(x):.1f},{sy(y):.1f}" for x, y in clean_points)
        parts.append(f'<polyline points="{polyline}" fill="none" stroke="{color}" stroke-width="3" stroke-linejoin="round"/>')
        for x, y in clean_points:
            parts.append(f'<circle cx="{sx(x):.1f}" cy="{sy(y):.1f}" r="3.2" fill="{color}"/>')
    legend_x = margin["left"]
    for name, color, _ in series:
        parts.append(f'<line x1="{legend_x}" y1="50" x2="{legend_x+24}" y2="50" stroke="{color}" stroke-width="4"/>')
        parts.append(f'<text x="{legend_x+31}" y="54" font-family="Segoe UI" font-size="13">{html.escape(name)}</text>')
        legend_x += 220
    parts.append(f'<text x="{width/2}" y="{height-15}" text-anchor="middle" font-family="Segoe UI" font-size="14">{html.escape(x_label)}</text>')
    parts.append(f'<text x="20" y="{height/2}" text-anchor="middle" transform="rotate(-90 20 {height/2})" font-family="Segoe UI" font-size="14">{html.escape(y_label)}</text>')
    parts.append("</svg>")
    path.write_text("\n".join(parts), encoding="utf-8")


def make_gis_scope_figure(polygons: list[list[tuple[float, float]]], gis_stops: list[dict]) -> None:
    width, height = 1000, 560
    margin = 55
    points = [point for ring in polygons for point in ring]
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    x_min, x_max = min(xs), max(xs)
    y_min, y_max = min(ys), max(ys)
    scale = min((width - 2 * margin) / (x_max - x_min), (height - 2 * margin) / (y_max - y_min))
    sx = lambda value: margin + (value - x_min) * scale
    sy = lambda value: height - margin - (value - y_min) * scale
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#f6f1e7"/>',
        '<text x="50" y="38" font-family="Segoe UI, sans-serif" font-size="23" font-weight="700" fill="#15251f">Yeouido GIS analysis scope</text>',
        '<text x="50" y="61" font-family="Segoe UI, sans-serif" font-size="13" fill="#53615b">2017 administrative boundary (EPSG:5186) and 2019 bus-stop points</text>',
    ]
    for ring in polygons:
        polygon = " ".join(f"{sx(x):.1f},{sy(y):.1f}" for x, y in ring)
        parts.append(f'<polygon points="{polygon}" fill="#d8e9df" stroke="#1f6b53" stroke-width="2.5"/>')
    for stop in gis_stops:
        parts.append(
            f'<circle cx="{sx(float(stop["x_epsg5186"])):.1f}" cy="{sy(float(stop["y_epsg5186"])):.1f}" r="4" fill="#e85d3f" opacity="0.78" stroke="#ffffff" stroke-width="0.8"/>'
        )
    parts.extend(
        [
            f'<rect x="{width-275}" y="26" width="225" height="68" rx="8" fill="#fffdf8" stroke="#c8c2b8"/>',
            f'<circle cx="{width-250}" cy="51" r="5" fill="#e85d3f"/><text x="{width-236}" y="56" font-family="Segoe UI" font-size="13">Bus stops: {len(gis_stops)}</text>',
            f'<rect x="{width-255}" y="67" width="12" height="12" fill="#d8e9df" stroke="#1f6b53"/><text x="{width-236}" y="78" font-family="Segoe UI" font-size="13">Yeouido boundary</text>',
            '</svg>',
        ]
    )
    (FIGURE_DIR / "actual_gis_scope.svg").write_text("\n".join(parts), encoding="utf-8")


def write_portfolio_page(summary: dict, scenario: dict) -> None:
    od = summary["od_departure_bus_event_window"]
    bus = summary["bus_boardings"]["event_window_18_23"]
    subway = summary["subway_boardings"]["event_window_18_23"]
    tpss = summary["tpss_supply"]["event_window_18_23"]
    html_text = f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>여의도 불꽃축제 교통 분석</title>
  <style>
    :root {{ --ink:#17231f; --muted:#627069; --paper:#f7f1e5; --card:#fffdf8; --green:#185c49; --orange:#e85d3f; --line:#d8d0c3; }}
    * {{ box-sizing:border-box; }} body {{ margin:0; color:var(--ink); background:var(--paper); font-family:"Noto Sans KR","Malgun Gothic",sans-serif; line-height:1.65; }}
    header {{ padding:80px max(6vw,28px) 64px; background:radial-gradient(circle at 80% 20%,#f4b15c66,transparent 26%),linear-gradient(135deg,#102c24,#1e604e); color:white; }}
    header p {{ max-width:760px; color:#d9ebe4; }} h1 {{ margin:0 0 18px; max-width:900px; font-family:Georgia,"Nanum Myeongjo",serif; font-size:clamp(38px,6vw,74px); line-height:1.08; }}
    main {{ width:min(1160px,90vw); margin:0 auto; padding:56px 0 90px; }} h2 {{ margin-top:64px; font-size:30px; }}
    .metrics {{ display:grid; grid-template-columns:repeat(4,1fr); gap:16px; margin-top:-88px; position:relative; }} .metric,.card {{ background:var(--card); border:1px solid var(--line); box-shadow:0 10px 30px #23372f18; }}
    .metric {{ padding:22px; min-height:160px; }} .metric b {{ display:block; color:var(--orange); font-size:30px; margin:8px 0; }} .metric small,.note {{ color:var(--muted); }}
    .grid {{ display:grid; grid-template-columns:repeat(2,1fr); gap:22px; }} .card {{ padding:20px; }} .card img {{ width:100%; display:block; }}
    table {{ width:100%; border-collapse:collapse; background:var(--card); }} th,td {{ padding:13px; text-align:left; border-bottom:1px solid var(--line); }} th {{ background:#e5efe9; }}
    code {{ background:#e9e1d4; padding:2px 5px; }} a {{ color:var(--green); }}
    @media(max-width:800px) {{ .metrics,.grid {{ grid-template-columns:1fr; }} .metrics {{ margin-top:-36px; }} header {{ padding-top:55px; }} }}
  </style>
</head>
<body>
<header><p>2023-10-07 서울세계불꽃축제 사례</p><h1>불꽃축제 뒤 길어진 귀가 시간, 수요와 운행 변화를 함께 봤습니다</h1><p>SKT OD·체류인구, 서울시 버스·지하철 30분 관측치, TPSS 정차횟수와 행정동 GIS를 결합하고 행사일과 같은 요일의 자료를 비교했습니다.</p></header>
<main>
  <section class="metrics">
    <div class="metric"><small>버스 OD 이동시간</small><b>+{od['difference_minutes']:.2f}분</b><span>18~23시 여의도 출발, OD 건수 가중평균</span></div>
    <div class="metric"><small>버스 승차 관측치</small><b>+{bus['target_minus_normal']/bus['normal_avg']*100:.1f}%</b><span>{bus['target']:.0f} 대 {bus['normal_avg']:.1f}</span></div>
    <div class="metric"><small>지하철 승차 관측치</small><b>+{subway['target_minus_normal']/subway['normal_avg']*100:.1f}%</b><span>{subway['target']:.0f} 대 {subway['normal_avg']:.1f}</span></div>
    <div class="metric"><small>TPSS 정차횟수</small><b>{tpss['target_minus_normal']/tpss['normal_avg']*100:.1f}%</b><span>{tpss['target']:.0f} 대 {tpss['normal_avg']:.1f}</span></div>
  </section>
  <h2>분석 질문</h2><p>불꽃축제 뒤 길어진 귀가 시간을 방문객 증가만으로 설명할 수 있을까? 행사 종료 전후의 수요 관측치, 버스 정차횟수와 이동시간을 같은 시간대에 놓고 비교했습니다.</p>
  <h2>주요 결과</h2><div class="grid">
    <div class="card"><img src="outputs/figures/actual_od_bus_duration.svg" alt="버스 이동시간 비교"></div>
    <div class="card"><img src="outputs/figures/actual_demand_supply_change.svg" alt="수요와 정차횟수 변화"></div>
    <div class="card"><img src="outputs/figures/actual_bus_boardings.svg" alt="버스 승차 관측치"></div>
    <div class="card"><img src="outputs/figures/actual_subway_boardings.svg" alt="지하철 승차 관측치"></div>
  </div>
  <h2>공급 회복 스트레스 테스트</h2>
  <table><tr><th>18~23시 지표</th><th>값</th></tr>
    <tr><td>현재 행사일 수요/공급 부담 ÷ 평상시 부담</td><td>{scenario['current_stress_index']:.2f}배</td></tr>
    <tr><td>정차횟수를 평상시 수준으로 회복한 뒤 부담</td><td>{scenario['stress_index_after_normal_supply_restore']:.2f}배</td></tr>
    <tr><td>평상시 정차횟수까지의 차이</td><td>{scenario['supply_gap_to_normal']:.1f} 정차횟수 지표</td></tr>
  </table>
  <p class="note">이 계산은 관측된 정차횟수 지표를 사용한 설명적 스트레스 테스트입니다. 실제 버스 대수, 최적 배차, 정책의 인과효과를 뜻하지 않습니다.</p>
  <h2>GIS 범위와 결합 감사</h2><div class="card"><img src="outputs/figures/actual_gis_scope.svg" alt="여의도 GIS 분석 범위"></div>
  <p>행정동 경계 내부의 2019년 버스정류장 59개를 추출했습니다. 버스 30분 자료는 정규화한 정류장명, TPSS는 GIS 정류장 ID의 정확 일치만 사용했습니다. 누락과 중복은 <a href="outputs/tables/join_audit.csv">join audit</a>에 남겼습니다.</p>
  <h2>재현</h2><p><code>python run_all.py</code> 이후 <code>python validate_release.py</code>를 실행합니다. 원시자료는 라이선스와 개인정보 고려로 포함하지 않았고, 공개 폴더에는 날짜·시간 집계본만 제공합니다.</p>
  <p><a href="https://github.com/yoon-chan-hyeok/yeouido-festival-mobility-analysis">GitHub 저장소</a> · <a href="https://github.com/yoon-chan-hyeok/yeouido-festival-mobility-analysis/blob/main/docs/METHODOLOGY.md">방법론</a> · <a href="https://github.com/yoon-chan-hyeok/yeouido-festival-mobility-analysis/blob/main/docs/MODEL_SELECTION.md">모델 선택 기준</a></p>
</main></body></html>"""
    (RELEASE_ROOT / "index.html").write_text(html_text, encoding="utf-8")


def make_figures(od_compare, bus_compare, subway_compare, tpss_compare, scenario_rows) -> None:
    _svg_line_chart(
        FIGURE_DIR / "actual_bus_boardings.svg",
        "Yeouido-area bus boardings",
        "Hour",
        "Boardings",
        [
            ("Event Saturday", "#2563eb", [(row["hour"], float(row["target"])) for row in bus_compare]),
            ("Normal Saturday average", "#dc2626", [(row["hour"], float(row["normal_avg"])) for row in bus_compare]),
        ],
    )
    _svg_line_chart(
        FIGURE_DIR / "actual_subway_boardings.svg",
        "Yeouido subway boardings",
        "Hour",
        "Boardings",
        [
            ("Event Saturday", "#2563eb", [(row["hour"], float(row["target"])) for row in subway_compare]),
            ("Normal Saturday average", "#dc2626", [(row["hour"], float(row["normal_avg"])) for row in subway_compare]),
        ],
    )
    departure_bus = [row for row in od_compare if row["flow"] == "departure" and row["mode"] == "bus"]
    _svg_line_chart(
        FIGURE_DIR / "actual_od_bus_duration.svg",
        "OD-count-weighted bus travel time: Yeouido departures to Seoul",
        "Hour",
        "Minutes",
        [
            ("Event Saturday", "#2563eb", [(row["hour"], float(row["target_avg_duration"])) for row in departure_bus if row["target_avg_duration"] != ""]),
            ("Normal Saturday pooled", "#dc2626", [(row["hour"], float(row["normal_pooled_avg_duration"])) for row in departure_bus if row["normal_pooled_avg_duration"] != ""]),
        ],
    )
    supply_lookup = {row["hour"]: row for row in tpss_compare}
    demand_change, supply_change = [], []
    for row in bus_compare:
        supply = supply_lookup[row["hour"]]
        demand_change.append((row["hour"], (float(row["target"]) / float(row["normal_avg"]) - 1) * 100 if row["normal_avg"] else 0))
        supply_change.append((row["hour"], (float(supply["target"]) / float(supply["normal_avg"]) - 1) * 100 if supply["normal_avg"] else 0))
    _svg_line_chart(
        FIGURE_DIR / "actual_demand_supply_change.svg",
        "Event Saturday change versus normal Saturdays",
        "Hour",
        "Change (%)",
        [("Bus boarding demand", "#2563eb", demand_change), ("TPSS stop-count supply", "#dc2626", supply_change)],
    )
    window = [row for row in scenario_rows if row["is_event_window"]]
    _svg_line_chart(
        FIGURE_DIR / "actual_supply_recovery_stress_test.svg",
        "Demand-supply stress test: observed versus normal-supply restore",
        "Hour",
        "Stress index (normal = 1)",
        [
            ("Observed event", "#e85d3f", [(row["hour"], float(row["current_stress_index"])) for row in window]),
            ("After normal-supply restore", "#185c49", [(row["hour"], float(row["stress_index_after_normal_supply_restore"])) for row in window]),
            ("Normal baseline", "#6b7280", [(row["hour"], 1.0) for row in window]),
        ],
        shade_event_window=False,
    )


def main() -> dict:
    _ensure_dirs()
    event_date = CONFIG["event_date"]
    normal_dates = CONFIG["normal_saturdays_primary"]
    sensitivity_dates = CONFIG["normal_saturdays_sensitivity"]
    od_dates = sensitivity_dates + [event_date]
    october_dates = [event_date] + CONFIG["october_normal_saturdays"]

    polygons, dong_meta, dong_path = load_yeouido_geometry(WORKSPACE_ROOT, CONFIG["yeouido_hdong_code"])
    gis_stops, gis_audit = load_bus_stops_in_yeouido(WORKSPACE_ROOT, polygons)
    kikmix_audit = load_kikmix_audit()
    od_cache = TABLE_DIR / "actual_od_date_hour_panel.csv"
    stay_cache = TABLE_DIR / "actual_stay_date_hour_panel.csv"
    raw_audit_cache = REPORT_DIR / "raw_source_audit.json"
    force_rebuild = os.environ.get("FORCE_REBUILD", "0") == "1"
    if od_cache.exists() and stay_cache.exists() and not force_rebuild:
        od_panel = read_csv_rows(od_cache, ["hour", "od_cnts", "weighted_duration", "source_rows", "avg_duration"])
        stay_panel = read_csv_rows(stay_cache, ["hour", "stay_cnts"])
        missing_od_dates = sorted(set(od_dates) - {row["date"] for row in od_panel})
        missing_stay_dates = sorted(set(od_dates) - {row["date"] for row in stay_panel})
        cached_audits = read_json(raw_audit_cache) if raw_audit_cache.exists() else {}
        od_audit = cached_audits.get("od", {"cache_status": "loaded release-local raw-derived panel"})
        stay_audit = cached_audits.get("stay", {"cache_status": "loaded release-local raw-derived panel"})
        od_audit["cache_reuse"] = True
        od_audit["rescanned_missing_dates"] = missing_od_dates
        stay_audit["cache_reuse"] = True
        stay_audit["rescanned_missing_dates"] = missing_stay_dates
        if missing_od_dates:
            added, added_audit = load_od_panel(missing_od_dates)
            od_panel.extend(added)
            od_audit["added_raw_audit"] = added_audit
        if missing_stay_dates:
            added, added_audit = load_stay_panel(missing_stay_dates)
            stay_panel.extend(added)
            stay_audit["added_raw_audit"] = added_audit
        write_csv(od_cache, sorted(od_panel, key=lambda row: (row["date"], row["flow"], row["mode"], float(row["hour"]))))
        write_csv(stay_cache, sorted(stay_panel, key=lambda row: (row["date"], float(row["hour"]))))
    else:
        od_panel, od_audit = load_od_panel(od_dates)
        stay_panel, stay_audit = load_stay_panel(od_dates)
        write_csv(od_cache, od_panel)
        write_csv(stay_cache, stay_panel)
        write_json(raw_audit_cache, {"od": od_audit, "stay": stay_audit})
    bus_panel, bus_audits = load_bus_panel(october_dates, gis_stops)
    subway_panel, subway_audits = load_subway_panel(october_dates)
    tpss_panel, tpss_audits = load_tpss_panel(october_dates, gis_stops)

    od_compare = compare_od(od_panel, normal_dates, CONFIG["strict_common_control_date"])
    od_compare_sensitivity = compare_od(od_panel, sensitivity_dates, CONFIG["strict_common_control_date"])
    stay_compare = compare_sum(stay_panel, "stay_cnts", normal_dates, CONFIG["strict_common_control_date"])
    stay_compare_sensitivity = compare_sum(stay_panel, "stay_cnts", sensitivity_dates, CONFIG["strict_common_control_date"])
    bus_hour = group_hour(bus_panel, ["geton", "getoff", "total"])
    subway_hour = group_hour(subway_panel, ["geton", "getoff", "total"])
    bus_compare = compare_sum(bus_hour, "geton", CONFIG["october_normal_saturdays"], CONFIG["strict_common_control_date"])
    subway_compare = compare_sum(subway_hour, "geton", CONFIG["october_normal_saturdays"], CONFIG["strict_common_control_date"])
    tpss_compare = compare_sum(tpss_panel, "stop_count", CONFIG["october_normal_saturdays"], CONFIG["strict_common_control_date"])
    feature_table = build_hourly_feature_table(
        od_compare, stay_compare, bus_compare, subway_compare, tpss_compare
    )
    scenario_rows, scenario_report = build_supply_recovery_scenario(bus_compare, tpss_compare)
    local_source_dates = inventory_local_source_dates()
    model_readiness = build_model_readiness_report(
        od_panel, stay_panel, bus_panel, subway_panel, tpss_panel, local_source_dates
    )
    table_payloads = {
        "actual_od_date_hour_panel.csv": od_panel,
        "actual_stay_date_hour_panel.csv": stay_panel,
        "actual_bus_30min_panel.csv": bus_panel,
        "actual_subway_30min_panel.csv": subway_panel,
        "actual_tpss_hour_panel.csv": tpss_panel,
        "actual_od_event_vs_saturday.csv": od_compare,
        "actual_od_event_vs_saturday_sensitivity_including_20230930.csv": od_compare_sensitivity,
        "actual_stay_event_vs_saturday.csv": stay_compare,
        "actual_stay_event_vs_saturday_sensitivity_including_20230930.csv": stay_compare_sensitivity,
        "actual_bus_boarding_event_vs_saturday.csv": bus_compare,
        "actual_subway_boarding_event_vs_saturday.csv": subway_compare,
        "actual_tpss_event_vs_saturday.csv": tpss_compare,
        "actual_hourly_feature_table.csv": feature_table,
        "actual_supply_recovery_stress_test.csv": scenario_rows,
    }
    for filename, rows in table_payloads.items():
        write_csv(TABLE_DIR / filename, rows)
    for filename in [
        "actual_od_event_vs_saturday.csv", "actual_stay_event_vs_saturday.csv",
        "actual_bus_boarding_event_vs_saturday.csv", "actual_subway_boarding_event_vs_saturday.csv",
        "actual_tpss_event_vs_saturday.csv",
        "actual_hourly_feature_table.csv", "actual_supply_recovery_stress_test.csv",
    ]:
        write_csv(PUBLIC_DIR / filename, table_payloads[filename])

    audit_rows = bus_audits + subway_audits + tpss_audits
    audit_rows.append(
        {
            "source": "gis_bus_stops_within_yeouido_polygon",
            "date": "static",
            "join_key": "point-in-polygon EPSG:5186",
            "source_rows": gis_audit["source_rows"],
            "matched_rows": gis_audit["inside_yeouido_rows"],
            "matched_row_rate": gis_audit["inside_yeouido_rows"] / gis_audit["source_rows"],
            "source_unique_units": gis_audit["source_rows"],
            "matched_unique_units": gis_audit["inside_yeouido_unique_stop_ids"],
            "matched_unique_rate": "",
            "target_reference_units": gis_audit["source_rows"],
            "observed_reference_units": gis_audit["inside_yeouido_unique_stop_ids"],
            "reference_coverage_rate": "",
            "ambiguous_matched_rows": gis_audit["ambiguous_name_count"],
            "excluded_reason": "missing coordinates or outside Yeouido administrative polygon",
        }
    )
    audit_rows.append(
        {
            "source": "kikmix_yeouido_code_lookup",
            "date": "20230701",
            "join_key": "administrative dong code 1156054000",
            "source_rows": kikmix_audit["source_rows"],
            "matched_rows": kikmix_audit["matched_rows"],
            "matched_row_rate": kikmix_audit["matched_rows"] / kikmix_audit["source_rows"],
            "source_unique_units": kikmix_audit["source_rows"],
            "matched_unique_units": 1,
            "matched_unique_rate": 1.0,
            "target_reference_units": 1,
            "observed_reference_units": 1,
            "reference_coverage_rate": 1.0,
            "ambiguous_matched_rows": 0,
            "excluded_reason": "non-Yeouido code-reference rows; this is a lookup audit, not a failed join",
        }
    )
    write_csv(TABLE_DIR / "join_audit.csv", audit_rows)
    exclusion_rows = []
    for row in audit_rows:
        target_units = row.get("target_reference_units")
        observed_units = row.get("observed_reference_units")
        if isinstance(target_units, (int, float)) and isinstance(observed_units, (int, float)):
            exclusion_rows.append(
                {
                    "source": row["source"],
                    "date": row["date"],
                    "reason": row["excluded_reason"],
                    "excluded_reference_unit_count": max(0, target_units - observed_units),
                    "treatment": "excluded from exact-key analysis; no forced match",
                }
            )
        if float(row.get("ambiguous_matched_rows") or 0) > 0:
            exclusion_rows.append(
                {
                    "source": row["source"],
                    "date": row["date"],
                    "reason": "duplicate normalized GIS stop name",
                    "excluded_reference_unit_count": row["ambiguous_matched_rows"],
                    "treatment": "retained only in Yeouido-area aggregate; excluded from coordinate-level attribution",
                }
            )
    write_csv(TABLE_DIR / "join_exclusion_reasons.csv", exclusion_rows)
    make_figures(od_compare, bus_compare, subway_compare, tpss_compare, scenario_rows)
    make_gis_scope_figure(polygons, gis_stops)
    write_json(REPORT_DIR / "supply_recovery_stress_test.json", scenario_report)
    write_json(REPORT_DIR / "model_readiness.json", model_readiness)

    departure_event = [
        row for row in od_compare
        if row["flow"] == "departure" and row["mode"] == "bus" and row["is_event_window"]
    ]
    event_count = sum(float(row["target_od_cnts"]) for row in departure_event)
    normal_count = sum(float(row["normal_avg_od_cnts"]) for row in departure_event)
    event_duration = sum(float(row["target_avg_duration"]) * float(row["target_od_cnts"]) for row in departure_event) / event_count
    normal_duration = sum(float(row["normal_pooled_avg_duration"]) * float(row["normal_avg_od_cnts"]) for row in departure_event) / normal_count
    summary = {
        "analysis_status": "actual raw data reanalysis completed",
        "event_date": event_date,
        "primary_normal_saturdays": normal_dates,
        "sensitivity_normal_saturdays": sensitivity_dates,
        "sensitivity_only_saturday": "20230930",
        "october_normal_saturdays": CONFIG["october_normal_saturdays"],
        "strict_common_control_date": CONFIG["strict_common_control_date"],
        "event_window_hours": CONFIG["event_impact_hours"],
        "spatial": {"dong": dong_meta, "dong_shapefile": str(dong_path.relative_to(WORKSPACE_ROOT)), "bus_stop_audit": gis_audit},
        "administrative_code_reference": kikmix_audit,
        "od_departure_bus_event_window": {
            "event_weighted_avg_duration_minutes": event_duration,
            "normal_weighted_avg_duration_minutes": normal_duration,
            "difference_minutes": event_duration - normal_duration,
            "event_od_count": event_count,
            "normal_avg_od_count": normal_count,
        },
        "bus_boardings": summary_from_compare(bus_compare, "bus boardings within exact-name Yeouido GIS scope"),
        "subway_boardings": summary_from_compare(subway_compare, "configured Yeouido subway stations"),
        "tpss_supply": summary_from_compare(tpss_compare, "TPSS stop counts at exact Yeouido GIS stop IDs"),
        "stay_population": summary_from_compare(stay_compare, "Yeouido stay population"),
        "supply_recovery_stress_test": scenario_report,
        "model_readiness": model_readiness,
        "raw_audits": {"od": od_audit, "stay": stay_audit},
        "privacy": "Only date-hour/event-control aggregates are copied to data/public; raw SKT and station-level source rows are not copied.",
        "runtime_dependencies": "Python standard library only",
    }
    write_json(REPORT_DIR / "actual_reanalysis_summary.json", summary)
    write_portfolio_page(summary, scenario_report)
    return summary


if __name__ == "__main__":
    print(json.dumps(main(), ensure_ascii=False, indent=2))
