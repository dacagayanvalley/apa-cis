"""
Prepare Region 2 administrative boundary overlays for the APA-CIS frontend.

The source GeoJSON files are treated as data only. This script removes unusable
features, keeps a compact set of display fields, and writes a small manifest so
the map can load context layers consistently.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


DEFAULT_SOURCE_DIR = Path(
    r"C:\Users\Jeff Factora\Downloads\GitHub\cagvalagrithematicmaps\data"
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = ROOT / "data" / "boundaries"

LAYERS = {
    "provinces": {
        "source": "provinces_simplified.geojson",
        "output": "provinces_simplified.geojson",
        "label": "Province Boundaries",
        "fields": [
            "ADM2_EN",
            "ADM2_PCODE",
            "ADM1_EN",
            "ADM1_PCODE",
            "AREA_SQKM",
        ],
    },
    "districts": {
        "source": "districts_simplified.geojson",
        "output": "districts_simplified.geojson",
        "label": "District Boundaries",
        "fields": [
            "DISTRICT",
            "district",
            "ADM2_EN",
            "province",
            "ADM1_EN",
            "ADM1_PCODE",
            "AREA_SQKM",
        ],
    },
    "municipalities": {
        "source": "municipalities_simplified.geojson",
        "output": "municipalities_simplified.geojson",
        "label": "Municipal Boundaries",
        "fields": [
            "municipality",
            "ADM3_EN",
            "ADM3_PCODE",
            "province",
            "ADM2_EN",
            "ADM2_PCODE",
            "ADM1_EN",
            "ADM1_PCODE",
            "AREA_SQKM",
        ],
    },
    "barangays": {
        "source": "barangay_boundaries.geojson",
        "output": "barangay_boundaries.geojson",
        "label": "Barangay Boundaries",
        "fields": [
            "ADM4_EN",
            "ADM4_PCODE",
            "ADM3_EN",
            "ADM3_PCODE",
            "ADM2_EN",
            "ADM2_PCODE",
            "ADM1_EN",
            "ADM1_PCODE",
        ],
    },
}


def _read_geojson(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if data.get("type") != "FeatureCollection":
        raise ValueError(f"{path} is not a GeoJSON FeatureCollection")
    if not isinstance(data.get("features"), list):
        raise ValueError(f"{path} does not contain a feature list")
    return data


def _compact_properties(props: dict[str, Any], fields: list[str]) -> dict[str, Any]:
    compact: dict[str, Any] = {}
    for field in fields:
        value = props.get(field)
        if value is not None and value != "":
            compact[field] = value
    return compact


def _prepare_layer(layer_id: str, spec: dict[str, Any], source_dir: Path, output_dir: Path) -> dict[str, Any]:
    source_path = source_dir / spec["source"]
    output_path = output_dir / spec["output"]
    data = _read_geojson(source_path)

    features: list[dict[str, Any]] = []
    dropped = 0
    for feature in data["features"]:
        geometry = feature.get("geometry")
        if not geometry:
            dropped += 1
            continue
        props = feature.get("properties") or {}
        features.append(
            {
                "type": "Feature",
                "properties": _compact_properties(props, spec["fields"]),
                "geometry": geometry,
            }
        )

    prepared = {
        "type": "FeatureCollection",
        "name": f"apa_cis_{layer_id}_r2",
        "crs": data.get("crs"),
        "features": features,
    }
    with output_path.open("w", encoding="utf-8") as handle:
        json.dump(prepared, handle, ensure_ascii=False, separators=(",", ":"))

    return {
        "id": layer_id,
        "label": spec["label"],
        "path": f"../data/boundaries/{spec['output']}",
        "source_file": str(source_path),
        "feature_count": len(features),
        "dropped_null_geometry": dropped,
        "size_bytes": output_path.stat().st_size,
    }


def prepare_boundaries(source_dir: Path, output_dir: Path) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    layers = [
        _prepare_layer(layer_id, spec, source_dir, output_dir)
        for layer_id, spec in LAYERS.items()
    ]
    manifest = {
        "generated_by": "scripts/prepare_boundary_overlays.py",
        "source_note": "Administrative boundary files are treated as data only.",
        "region": "Region II (Cagayan Valley)",
        "layers": layers,
    }
    with (output_dir / "boundary_manifest.json").open("w", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare Region 2 boundary overlays.")
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()

    manifest = prepare_boundaries(args.source_dir, args.output_dir)
    for layer in manifest["layers"]:
        print(
            f"{layer['id']}: {layer['feature_count']} features, "
            f"{layer['dropped_null_geometry']} dropped, {layer['size_bytes']} bytes"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
