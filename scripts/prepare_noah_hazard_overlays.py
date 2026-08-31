"""
Normalize pre-clipped Project NOAH hazard GeoJSON files for APA-CIS.

This intentionally does not scrape NOAH. Use it after downloading/clipping
NOAH source data with QGIS, ogr2ogr, or another GIS workflow.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE_DIR = ROOT / "data" / "raw" / "noah" / "r2"
DEFAULT_OUTPUT_DIR = ROOT / "data" / "geospatial" / "noah"
CATALOG_PATH = ROOT / "data" / "reference" / "noah_hazard_overlays.json"


DEFAULT_SCENARIOS = {
    "flood_5yr",
    "flood_25yr",
    "flood_100yr",
    "landslide",
    "debris_flow",
    "storm_surge_ssa1",
    "storm_surge_ssa2",
    "storm_surge_ssa3",
    "storm_surge_ssa4",
}


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, separators=(",", ":"))


def _catalog_lookup(catalog: dict[str, Any]) -> dict[str, dict[str, Any]]:
    lookup: dict[str, dict[str, Any]] = {}
    for hazard in catalog.get("hazards", []):
        for scenario in hazard.get("scenarios", []):
            lookup[scenario["id"]] = {
                "family": hazard["family"],
                "label": hazard["label"],
                "attribute": hazard["attribute"],
                "levels": hazard["levels"],
                "scenario": scenario["id"],
                "scenario_label": scenario["label"],
            }
    return lookup


def _normal_level(value: Any) -> str | None:
    if value is None or value == "":
        return None
    try:
        return str(int(float(value)))
    except (TypeError, ValueError):
        return str(value).strip()


def _normalize_feature(feature: dict[str, Any], spec: dict[str, Any]) -> dict[str, Any] | None:
    geometry = feature.get("geometry")
    if not geometry:
        return None

    props = feature.get("properties") or {}
    raw_level = (
        props.get("hazard_level")
        or props.get(spec["attribute"])
        or props.get("Var")
        or props.get("VAR")
        or props.get("HAZ")
        or props.get("SS")
        or props.get("LH")
        or props.get("GRIDCODE")
    )
    level = _normal_level(raw_level)
    if level not in {"1", "2", "3"}:
        return None

    level_def = spec["levels"].get(level, {})
    compact_props = {
        "hazard_family": spec["family"],
        "hazard_source": "Project NOAH",
        "scenario": spec["scenario"],
        "scenario_label": spec["scenario_label"],
        "hazard_level": int(level),
        "hazard_label": level_def.get("label", level),
    }

    original_attr = spec["attribute"]
    if original_attr in props:
      compact_props[original_attr] = props[original_attr]

    return {
        "type": "Feature",
        "properties": compact_props,
        "geometry": geometry,
    }


def normalize_layer(scenario_id: str, source_dir: Path, output_dir: Path, spec: dict[str, Any]) -> dict[str, Any]:
    source_path = source_dir / f"{scenario_id}.geojson"
    if not source_path.exists():
        return {
            "id": scenario_id,
            "status": "missing",
            "source": str(source_path),
            "message": "Place a pre-clipped Region 2 GeoJSON with this filename to generate the frontend overlay.",
        }

    data = _read_json(source_path)
    if data.get("type") != "FeatureCollection":
        raise ValueError(f"{source_path} is not a GeoJSON FeatureCollection")

    normalized = []
    dropped = 0
    for feature in data.get("features", []):
        result = _normalize_feature(feature, spec)
        if result:
            normalized.append(result)
        else:
            dropped += 1

    output_path = output_dir / f"{scenario_id}_r2.geojson"
    _write_json(
        output_path,
        {
            "type": "FeatureCollection",
            "name": f"project_noah_{scenario_id}_r2",
            "features": normalized,
        },
    )
    return {
        "id": scenario_id,
        "status": "ready",
        "source": str(source_path),
        "output": str(output_path),
        "feature_count": len(normalized),
        "dropped_features": dropped,
        "size_bytes": output_path.stat().st_size,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Normalize Project NOAH hazard overlays.")
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--scenario", action="append", choices=sorted(DEFAULT_SCENARIOS))
    args = parser.parse_args()

    catalog = _read_json(CATALOG_PATH)
    lookup = _catalog_lookup(catalog)
    scenarios = args.scenario or sorted(DEFAULT_SCENARIOS)
    results = [
        normalize_layer(scenario, args.source_dir, args.output_dir, lookup[scenario])
        for scenario in scenarios
    ]

    summary_path = args.output_dir / "noah_overlay_build_status.json"
    _write_json(
        summary_path,
        {
            "generated_by": "scripts/prepare_noah_hazard_overlays.py",
            "source_dir": str(args.source_dir),
            "results": results,
        },
    )
    for result in results:
        print(f"{result['id']}: {result['status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
