from __future__ import annotations

import csv
import json
import re
import struct
from pathlib import Path
from typing import Iterable, Iterator


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_number(value, default: float = 0.0) -> float:
    text = str(value or "").strip().replace(",", "").replace("`", "")
    if not text:
        return default
    try:
        return float(text)
    except ValueError:
        return default


def normalize_code(value) -> str:
    text = str(value or "").strip().replace("`", "")
    if text.endswith(".0"):
        text = text[:-2]
    return text


def normalize_name(value) -> str:
    text = str(value or "").strip().replace("`", "")
    return re.sub(r"\s+", "", text)


def detect_csv_encoding(path: Path, candidates: Iterable[str] = ("utf-8-sig", "cp949", "euc-kr")) -> str:
    for encoding in candidates:
        try:
            with path.open("r", encoding=encoding, newline="") as handle:
                handle.readline()
            return encoding
        except UnicodeDecodeError:
            continue
    raise UnicodeDecodeError("unknown", b"", 0, 1, f"Unable to decode {path}")


def read_dbf(path: Path, encodings: Iterable[str] = ("utf-8", "cp949", "euc-kr")) -> Iterator[dict]:
    """Minimal DBF reader sufficient for the bundled Seoul shapefiles."""
    with path.open("rb") as handle:
        header = handle.read(32)
        record_count = struct.unpack("<I", header[4:8])[0]
        header_length = struct.unpack("<H", header[8:10])[0]
        record_length = struct.unpack("<H", header[10:12])[0]

        fields = []
        while True:
            block = handle.read(32)
            if not block or block[0] == 0x0D:
                break
            name = block[:11].split(b"\x00", 1)[0].decode("ascii", errors="ignore")
            fields.append((name, block[16]))

        handle.seek(header_length)
        for _ in range(record_count):
            record = handle.read(record_length)
            if not record or record[0] == 0x2A:
                continue
            offset = 1
            row = {}
            for name, width in fields:
                raw = record[offset:offset + width]
                offset += width
                decoded = None
                for encoding in encodings:
                    try:
                        decoded = raw.decode(encoding).strip()
                        break
                    except UnicodeDecodeError:
                        continue
                row[name] = decoded if decoded is not None else raw.decode("latin1", errors="ignore").strip()
            yield row


def read_polygon_shapefile(path: Path) -> list[dict]:
    """Read Polygon records without requiring geopandas/fiona."""
    records = []
    with path.open("rb") as handle:
        handle.read(100)
        while True:
            record_header = handle.read(8)
            if len(record_header) < 8:
                break
            record_number, content_words = struct.unpack(">2i", record_header)
            content = handle.read(content_words * 2)
            if len(content) < 4:
                continue
            shape_type = struct.unpack("<i", content[:4])[0]
            if shape_type == 0:
                records.append({"record_number": record_number, "bbox": None, "rings": []})
                continue
            if shape_type not in {5, 15, 25}:
                records.append({"record_number": record_number, "bbox": None, "rings": []})
                continue
            bbox = struct.unpack("<4d", content[4:36])
            part_count, point_count = struct.unpack("<2i", content[36:44])
            part_starts = list(struct.unpack("<" + "i" * part_count, content[44:44 + part_count * 4]))
            point_offset = 44 + part_count * 4
            points = [
                struct.unpack("<2d", content[point_offset + index * 16:point_offset + (index + 1) * 16])
                for index in range(point_count)
            ]
            rings = []
            for index, start in enumerate(part_starts):
                end = part_starts[index + 1] if index + 1 < len(part_starts) else point_count
                if end - start >= 3:
                    rings.append(points[start:end])
            records.append({"record_number": record_number, "bbox": bbox, "rings": rings})
    return records


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8-sig")
        return
    fieldnames = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def read_csv_rows(path: Path, numeric_fields: Iterable[str] = ()) -> list[dict]:
    rows = []
    numeric_fields = set(numeric_fields)
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            for field in numeric_fields:
                if field in row and row[field] != "":
                    row[field] = parse_number(row[field])
            rows.append(row)
    return rows
