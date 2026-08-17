from __future__ import annotations

from collections import Counter
from pathlib import Path

from .io_utils import normalize_code, normalize_name, parse_number, read_dbf, read_polygon_shapefile


def find_single(root: Path, filename: str) -> Path:
    matches = list(root.rglob(filename))
    if len(matches) != 1:
        raise FileNotFoundError(f"Expected one {filename}, found {len(matches)}: {matches}")
    return matches[0]


def load_yeouido_geometry(workspace_root: Path, yeouido_code: str):
    shp_path = find_single(workspace_root / "seoul_new_data", "seoul_dong_2017year_epsg5186.shp")
    dbf_path = shp_path.with_suffix(".dbf")
    attributes = list(read_dbf(dbf_path))
    shapes = read_polygon_shapefile(shp_path)
    if len(attributes) != len(shapes):
        raise ValueError("Administrative DBF and SHP record counts differ")

    selected = []
    selected_meta = None
    for attr, shape in zip(attributes, shapes):
        code = normalize_code(attr.get("adm_dr_cd"))
        name = str(attr.get("adm_dr_nm") or "").strip()
        if code == yeouido_code or name == "여의동" or name == "여의도동":
            selected = [ring for ring in shape["rings"] if len(ring) >= 3]
            selected_meta = {"code": code, "name": name, "bbox": shape["bbox"]}
            break
    if not selected:
        raise ValueError(f"Yeouido polygon not found for code {yeouido_code}")
    return selected, selected_meta, shp_path


def _point_in_ring(x: float, y: float, ring: list[tuple[float, float]]) -> bool:
    inside = False
    previous = ring[-1]
    for current in ring:
        x1, y1 = previous
        x2, y2 = current
        if ((y1 > y) != (y2 > y)):
            crossing_x = (x2 - x1) * (y - y1) / (y2 - y1) + x1
            if x <= crossing_x:
                inside = not inside
        previous = current
    return inside


def load_bus_stops_in_yeouido(workspace_root: Path, polygons: list[list[tuple[float, float]]]) -> tuple[list[dict], dict]:
    dbf_path = find_single(workspace_root / "seoul_new_data", "TB_E_BUSSTOP_2019.dbf")
    all_rows = list(read_dbf(dbf_path))
    selected = []
    missing_coordinates = 0
    for row in all_rows:
        x = parse_number(row.get("TM_X"), default=float("nan"))
        y = parse_number(row.get("TM_Y"), default=float("nan"))
        if x != x or y != y:
            missing_coordinates += 1
            continue
        if not any(_point_in_ring(x, y, polygon) for polygon in polygons):
            continue
        selected.append(
            {
                "gis_stop_id": normalize_code(row.get("STN_IDN")),
                "gis_stop_name": str(row.get("STN_NM") or "").strip(),
                "normalized_stop_name": normalize_name(row.get("STN_NM")),
                "ars_number": normalize_code(row.get("STTN_ARSNO")),
                "x_epsg5186": x,
                "y_epsg5186": y,
            }
        )
    name_counts = Counter(row["normalized_stop_name"] for row in selected if row["normalized_stop_name"])
    for row in selected:
        row["gis_name_multiplicity"] = name_counts[row["normalized_stop_name"]]
    audit = {
        "source_rows": len(all_rows),
        "missing_coordinate_rows": missing_coordinates,
        "inside_yeouido_rows": len(selected),
        "inside_yeouido_unique_stop_ids": len({row["gis_stop_id"] for row in selected if row["gis_stop_id"]}),
        "inside_yeouido_unique_names": len(name_counts),
        "ambiguous_name_count": sum(1 for count in name_counts.values() if count > 1),
    }
    return selected, audit
