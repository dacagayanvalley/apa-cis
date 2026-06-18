"""
Build a normalized ACAP rice/corn cropping calendar JSON for the frontend.

The source XLSX files use strict OOXML workbook metadata that some readers do
not list as ordinary worksheets, so this parser reads the worksheet XML
directly from the package.
"""

import json
import re
import unicodedata
import xml.etree.ElementTree as ET
from pathlib import Path
from zipfile import ZipFile

PROJECT_ROOT = Path(__file__).resolve().parents[1]
NS = {"m": "http://purl.oclc.org/ooxml/spreadsheetml/main"}

SOURCE_FILES = {
    "rice": Path(r"C:\Users\Jeff Factora\Downloads\2026\APA\ACAP_rice_cropping_calendar.xlsx"),
    "corn": Path(r"C:\Users\Jeff Factora\Downloads\2026\APA\ACAP_corn_cropping_calendar.xlsx"),
}
OUTPUT_PATH = PROJECT_ROOT / "data" / "reference" / "acap_cropping_calendars.json"

PERIOD_LABELS = {
    "01_15_CAL": "Jan 1-15",
    "01_30_CAL": "Jan 16-31",
    "02_15_CAL": "Feb 1-15",
    "02_30_CAL": "Feb 16-29",
    "03_15_CAL": "Mar 1-15",
    "03_30_CAL": "Mar 16-31",
    "04_15_CAL": "Apr 1-15",
    "04_30_CAL": "Apr 16-30",
    "05_15_CAL": "May 1-15",
    "05_30_CAL": "May 16-31",
    "06_15_CAL": "Jun 1-15",
    "06_30_CAL": "Jun 16-30",
    "07_15_CAL": "Jul 1-15",
    "07_30_CAL": "Jul 16-31",
    "08_15_CAL": "Aug 1-15",
    "08_30_CAL": "Aug 16-31",
    "09_15_CAL": "Sep 1-15",
    "09_30_CAL": "Sep 16-30",
    "10_15_CAL": "Oct 1-15",
    "10_30_CAL": "Oct 16-31",
    "11_15_CAL": "Nov 1-15",
    "11_30_CAL": "Nov 16-30",
    "12_15_CAL": "Dec 1-15",
    "12_30_CAL": "Dec 16-31",
}

STAGE_LABELS = {
    "prep": "Preparation",
    "seed": "Seedling",
    "plant": "Planting / Newly planted",
    "veg": "Vegetative",
    "vegat": "Vegetative / Active tillering",
    "vegpi": "Reproductive / Panicle initiation",
    "vegleaf": "Vegetative / Leaf development",
    "vegtass": "Vegetative / Tasseling",
    "repro": "Reproductive",
    "mat": "Maturing",
}


def _column_letters(cell_ref):
    return re.match(r"([A-Z]+)", cell_ref).group(1)


def _column_index(col):
    value = 0
    for char in col:
        value = value * 26 + ord(char) - 64
    return value - 1


def _key(value):
    text = unicodedata.normalize("NFD", str(value or "").strip().lower())
    text = "".join(char for char in text if unicodedata.category(char) != "Mn")
    text = re.sub(r"^city of\s+", "", text)
    text = re.sub(r"\s+city$", "", text)
    return re.sub(r"[^a-z0-9]", "", text)


def _worksheet_rows(path, sheet_name):
    with ZipFile(path) as package:
        shared_strings = []
        shared_root = ET.fromstring(package.read("xl/sharedStrings.xml"))
        for item in shared_root.findall("m:si", NS):
            shared_strings.append("".join(t.text or "" for t in item.findall(".//m:t", NS)))

        sheet_root = ET.fromstring(package.read(f"xl/worksheets/{sheet_name}.xml"))
        rows = []
        for row in sheet_root.findall(".//m:sheetData/m:row", NS):
            cells = []
            for cell in row.findall("m:c", NS):
                idx = _column_index(_column_letters(cell.attrib["r"]))
                while len(cells) <= idx:
                    cells.append(None)
                value = cell.find("m:v", NS)
                if value is None:
                    cells[idx] = None
                elif cell.attrib.get("t") == "s":
                    cells[idx] = shared_strings[int(value.text)]
                else:
                    cells[idx] = value.text
            rows.append(cells)
        return rows


def _season_number(raw):
    match = re.search(r"_(\d+)$", str(raw or ""))
    return int(match.group(1)) if match else None


def _normalize_calendar_row(header, row, scope):
    values = {header[i]: row[i] if i < len(row) else None for i in range(len(header))}
    periods = {key: values.get(key) for key in header if key.endswith("_CAL") and values.get(key)}
    if not periods:
        return None

    seasons = sorted({_season_number(value) for value in periods.values() if _season_number(value)})
    return {
        "scope": scope,
        "province": values.get("prov"),
        "municipality": values.get("muni"),
        "crop": values.get("crop"),
        "season": seasons[0] if len(seasons) == 1 else None,
        "periods": periods,
    }


def _stage_code(raw):
    return re.sub(r"_\d+$", "", str(raw or ""))


def _parse_calendar(path, crop):
    municipal_rows = _worksheet_rows(path, "sheet1")
    header = municipal_rows[0]
    municipal = []
    for row in municipal_rows[1:]:
        item = _normalize_calendar_row(header, row, "municipal")
        if item:
            municipal.append(item)

    reference = []
    if crop == "rice":
        reference_rows = _worksheet_rows(path, "sheet3")
        reference_header = reference_rows[0]
        for row in reference_rows[1:]:
            item = _normalize_calendar_row(reference_header, row, "province_reference")
            if item:
                reference.append(item)
    else:
        seen = set()
        for item in municipal:
            signature = tuple(
                (period, _stage_code(value), _season_number(value))
                for period, value in item["periods"].items()
            )
            ref_key = (item["province"], item["season"], signature)
            if ref_key in seen:
                continue
            seen.add(ref_key)
            reference.append({
                **item,
                "scope": "province_reference",
                "municipality": None,
            })

    return municipal, reference


def main():
    calendar = {
        "meta": {
            "source_files": {crop: str(path) for crop, path in SOURCE_FILES.items()},
            "period_count": len(PERIOD_LABELS),
        },
        "periods": [
            {"key": key, "label": label, "month": label.split()[0]}
            for key, label in PERIOD_LABELS.items()
        ],
        "stage_labels": STAGE_LABELS,
        "municipalities": {},
        "province_reference": {},
    }

    for crop, path in SOURCE_FILES.items():
        municipal, reference = _parse_calendar(path, crop)
        for item in municipal:
            municipality_key = f"{_key(item['province'])}|{_key(item['municipality'])}"
            entry = calendar["municipalities"].setdefault(
                municipality_key,
                {
                    "province": item["province"],
                    "municipality": str(item["municipality"]).strip(),
                    "crops": {},
                },
            )
            entry["crops"].setdefault(crop, []).append({
                "season": item["season"],
                "periods": item["periods"],
            })

        for item in reference:
            province_key = _key(item["province"])
            entry = calendar["province_reference"].setdefault(
                province_key,
                {"province": item["province"], "crops": {}},
            )
            entry["crops"].setdefault(crop, []).append({
                "season": item["season"],
                "periods": item["periods"],
            })

    for bucket in [
        *calendar["municipalities"].values(),
        *calendar["province_reference"].values(),
    ]:
        for entries in bucket["crops"].values():
            entries.sort(key=lambda row: (row.get("season") or 99, list(row["periods"].keys())[0]))

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(calendar, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"Wrote {OUTPUT_PATH} with "
        f"{len(calendar['municipalities'])} municipalities and "
        f"{len(calendar['province_reference'])} provincial references."
    )


if __name__ == "__main__":
    main()
