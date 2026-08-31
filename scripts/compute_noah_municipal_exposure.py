"""
Compute municipality-level Project NOAH hazard exposure for APA-CIS.

The script is intentionally defensive:
- with Shapely and prepared Region 2 NOAH GeoJSON, it computes polygon
  intersections and hazard exposure percentages;
- without local hazard geometry, it still emits a stable source-readiness
  report so the frontend and pipeline do not break.
"""

from __future__ import annotations

import argparse
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
MUNICIPALITIES_PATH = ROOT / "config" / "municipalities.json"
MUNICIPAL_BOUNDARIES_PATH = ROOT / "data" / "boundaries" / "municipalities_simplified.geojson"
NOAH_DIR = ROOT / "data" / "geospatial" / "noah"
CATALOG_PATH = ROOT / "data" / "reference" / "noah_hazard_overlays.json"
SOURCE_INDEX_PATH = ROOT / "data" / "reference" / "noah_region2_source_files.json"
OUTPUT_PATH = ROOT / "data" / "processed" / "noah" / "municipal_hazard_exposure.json"

LEVELS = ("1", "2", "3")
LEVEL_NAMES = {"1": "low", "2": "medium", "3": "high"}
RISK_ORDER = {"unknown": 0, "low": 1, "moderate": 2, "high": 3, "very_high": 4}
REGION2_PROVINCES = ["Batanes", "Cagayan", "Isabela", "Nueva Vizcaya", "Quirino"]
DEBRIS_FLOW_DIRECT_URLS = [
    "https://huggingface.co/datasets/bettergovph/project-noah-hazard-maps/resolve/main/Landslide/DebrisFlowAlluvialFan/Philippines_AlluvialFan.zip",
    "https://huggingface.co/datasets/bettergovph/project-noah-hazard-maps/resolve/main/Landslide/DebrisFlowAlluvialFan/Philippines_DebrisFlow.zip",
]


def _load_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def _scenario_specs(catalog: dict[str, Any]) -> dict[str, dict[str, Any]]:
    specs: dict[str, dict[str, Any]] = {}
    for hazard in catalog.get("hazards", []):
        for scenario in hazard.get("scenarios", []):
            specs[scenario["id"]] = {
                "id": scenario["id"],
                "family": hazard["family"],
                "family_label": hazard["label"],
                "label": scenario["label"],
                "attribute": hazard["attribute"],
                "pmtiles_layer": scenario.get("pmtiles_layer"),
            }
    return specs


def _source_lookup(source_index: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    folders = {item["folder"]: item.get("files", []) for item in (source_index or {}).get("folders", [])}
    mapping = {
        "flood_5yr": ["Flood/5yr"],
        "flood_25yr": ["Flood/25yr"],
        "flood_100yr": ["Flood/100yr"],
        "landslide": ["Landslide/LandslideHazards"],
        "debris_flow": ["Landslide/DebrisFlowAlluvialFan"],
        "storm_surge_ssa1": ["Storm Surge/StormSurgeAdvisory1"],
        "storm_surge_ssa2": ["Storm Surge/StormSurgeAdvisory2"],
        "storm_surge_ssa3": ["Storm Surge/StormSurgeAdvisory3"],
        "storm_surge_ssa4": ["Storm Surge/StormSurgeAdvisory4"],
    }
    lookup: dict[str, dict[str, Any]] = {}
    for scenario, scenario_folders in mapping.items():
        if scenario == "debris_flow":
            lookup[scenario] = {
                "status": "available",
                "source_file_count": len(DEBRIS_FLOW_DIRECT_URLS),
                "source_provinces": REGION2_PROVINCES,
                "total_source_size_bytes": None,
                "download_urls": DEBRIS_FLOW_DIRECT_URLS,
            }
            continue
        files = []
        for folder in scenario_folders:
            files.extend(folders.get(folder, []))
        provinces = sorted({_province_from_path(item.get("path", "")) for item in files if item.get("path")})
        lookup[scenario] = {
            "status": "available" if files else "not_listed",
            "source_file_count": len(files),
            "source_provinces": [p for p in provinces if p],
            "total_source_size_bytes": sum(int(item.get("size", 0) or 0) for item in files),
        }
    return lookup


def _province_from_path(path: str) -> str:
    name = Path(path).stem
    return {
        "NuevaVizcaya": "Nueva Vizcaya",
    }.get(name, name)


def _key(*parts: str) -> str:
    text = "|".join(str(part or "") for part in parts)
    text = re.sub(r"\([^)]*\)", "", text)
    text = text.lower().replace("city of ", "").replace(" city", "")
    return re.sub(r"[^a-z0-9|]", "", text)


def _blank_level_stats() -> dict[str, dict[str, float]]:
    return {
        name: {"area_ha": 0.0, "pct": 0.0}
        for name in ("low", "medium", "high")
    }


def _risk_class(score: float | None) -> str:
    if score is None:
        return "unknown"
    if score >= 60:
        return "very_high"
    if score >= 35:
        return "high"
    if score >= 15:
        return "moderate"
    return "low"


def _bbox_intersects(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> bool:
    return not (a[2] < b[0] or a[0] > b[2] or a[3] < b[1] or a[1] > b[3])


def _build_municipal_records(municipalities: list[dict[str, Any]], boundaries: dict[str, Any]) -> dict[str, dict[str, Any]]:
    boundary_lookup = {}
    for feature in boundaries.get("features", []):
        props = feature.get("properties") or {}
        boundary_lookup[_key(props.get("province"), props.get("municipality"))] = feature

    records = {}
    for mun in municipalities:
        feature = boundary_lookup.get(_key(mun.get("province"), mun.get("name")))
        area_sqkm = None
        if feature:
            area_sqkm = (feature.get("properties") or {}).get("AREA_SQKM")
        records[mun["psgc"]] = {
            "psgc": mun["psgc"],
            "municipality": mun["name"],
            "province": mun["province"],
            "area_sqkm": round(float(area_sqkm), 3) if area_sqkm else None,
            "geometry_status": "matched" if feature else "missing_boundary",
            "boundary_feature": feature,
            "scenarios": {},
            "summary": {
                "status": "pending",
                "risk_score": None,
                "risk_class": "unknown",
                "highest_hazard_level": None,
                "highest_hazard_label": "Unknown",
                "dominant_hazards": [],
                "exact_scenario_count": 0,
                "available_source_scenario_count": 0,
            },
        }
    return records


def _load_shapely():
    try:
        from shapely.geometry import shape
        from shapely.ops import unary_union
    except Exception:
        return None, None
    return shape, unary_union


def _compute_exact(records: dict[str, dict[str, Any]], specs: dict[str, dict[str, Any]]) -> tuple[set[str], str | None]:
    shape, unary_union = _load_shapely()
    if not shape or not unary_union:
        return set(), "Install shapely to compute polygon intersections."

    municipality_geometries = {}
    for psgc, record in records.items():
        feature = record.pop("boundary_feature", None)
        if feature and feature.get("geometry"):
            geom = shape(feature["geometry"])
            if not geom.is_empty:
                municipality_geometries[psgc] = geom

    ready: set[str] = set()
    for scenario_id, spec in specs.items():
        path = NOAH_DIR / f"{scenario_id}_r2.geojson"
        if not path.exists():
            continue
        data = _load_json(path, {})
        features = data.get("features", [])
        grouped: dict[str, list[Any]] = {level: [] for level in LEVELS}
        for feature in features:
            props = feature.get("properties") or {}
            level = str(props.get("hazard_level") or props.get(spec["attribute"]) or "")
            if level not in grouped or not feature.get("geometry"):
                continue
            geom = shape(feature["geometry"])
            if not geom.is_empty:
                grouped[level].append(geom)

        unions = {
            level: unary_union(geoms)
            for level, geoms in grouped.items()
            if geoms
        }
        if not unions:
            continue
        ready.add(scenario_id)

        for record in records.values():
            psgc = record["psgc"]
            mun_geom = municipality_geometries.get(psgc)
            stats = _blank_level_stats()
            max_level = None
            if mun_geom and record.get("area_sqkm") and mun_geom.area > 0:
                for level, hazard_geom in unions.items():
                    if not _bbox_intersects(mun_geom.bounds, hazard_geom.bounds):
                        continue
                    exposed = mun_geom.intersection(hazard_geom)
                    if exposed.is_empty:
                        continue
                    pct = max(0.0, min(100.0, (exposed.area / mun_geom.area) * 100.0))
                    area_ha = float(record["area_sqkm"]) * 100.0 * pct / 100.0
                    name = LEVEL_NAMES[level]
                    stats[name] = {"area_ha": round(area_ha, 2), "pct": round(pct, 2)}
                    if pct > 0:
                        max_level = max(int(level), int(max_level or 0))

            score = _scenario_score(stats)
            record["scenarios"][scenario_id] = {
                "status": "computed",
                "family": spec["family"],
                "label": spec["label"],
                "pmtiles_layer": spec.get("pmtiles_layer"),
                "hazard_area": stats,
                "risk_score": score,
                "risk_class": _risk_class(score),
                "max_hazard_level": max_level,
                "max_hazard_label": LEVEL_NAMES.get(str(max_level), "none"),
            }
    return ready, None


def _scenario_score(stats: dict[str, dict[str, float]]) -> float:
    score = (
        stats["high"]["pct"] * 1.0
        + stats["medium"]["pct"] * 0.45
        + stats["low"]["pct"] * 0.15
    )
    return round(min(100.0, score), 2)


def _apply_source_status(
    records: dict[str, dict[str, Any]],
    specs: dict[str, dict[str, Any]],
    source_status: dict[str, dict[str, Any]],
    ready: set[str],
) -> None:
    for record in records.values():
        for scenario_id, spec in specs.items():
            existing = record["scenarios"].get(scenario_id)
            src = source_status.get(scenario_id, {})
            province_available = record["province"] in src.get("source_provinces", [])
            if existing:
                existing["source_status"] = "local_geometry_ready"
                existing["source_provinces"] = src.get("source_provinces", [])
                continue
            record["scenarios"][scenario_id] = {
                "status": "pending_local_geometry",
                "family": spec["family"],
                "label": spec["label"],
                "pmtiles_layer": spec.get("pmtiles_layer"),
                "source_status": src.get("status", "not_listed"),
                "source_available_for_province": province_available,
                "source_provinces": src.get("source_provinces", []),
                "source_file_count": src.get("source_file_count", 0),
                "hazard_area": None,
                "risk_score": None,
                "risk_class": "unknown",
                "max_hazard_level": None,
                "max_hazard_label": "Unknown",
            }


def _summarize_records(records: dict[str, dict[str, Any]]) -> dict[str, Any]:
    province_summary: dict[str, dict[str, Any]] = {}
    exact_records = 0
    for record in records.values():
        computed = [item for item in record["scenarios"].values() if item["status"] == "computed"]
        available_sources = [
            item for item in record["scenarios"].values()
            if item.get("source_available_for_province") or item.get("source_status") == "local_geometry_ready"
        ]
        record["summary"]["exact_scenario_count"] = len(computed)
        record["summary"]["available_source_scenario_count"] = len(available_sources)
        if computed:
            exact_records += 1
            best = max(computed, key=lambda item: item.get("risk_score") or 0)
            total_score = min(100.0, math.sqrt(sum((item.get("risk_score") or 0) ** 2 for item in computed)))
            record["summary"].update({
                "status": "computed",
                "risk_score": round(total_score, 2),
                "risk_class": _risk_class(total_score),
                "highest_hazard_level": max((item.get("max_hazard_level") or 0) for item in computed) or None,
                "highest_hazard_label": LEVEL_NAMES.get(
                    str(max((item.get("max_hazard_level") or 0) for item in computed) or ""),
                    "none",
                ),
                "dominant_hazards": [
                    {
                        "scenario": item_id,
                        "label": item["label"],
                        "risk_score": item.get("risk_score") or 0,
                        "risk_class": item.get("risk_class", "unknown"),
                    }
                    for item_id, item in sorted(
                        record["scenarios"].items(),
                        key=lambda pair: pair[1].get("risk_score") or 0,
                        reverse=True,
                    )[:3]
                    if (item.get("risk_score") or 0) > 0
                ],
                "primary_hazard": best["label"] if (best.get("risk_score") or 0) > 0 else "No mapped exposure in prepared local layers",
            })
        else:
            record["summary"].update({
                "status": "pending_local_geometry",
                "primary_hazard": "Awaiting clipped local NOAH geometry",
            })

        prov = province_summary.setdefault(record["province"], {
            "municipality_count": 0,
            "computed_municipalities": 0,
            "pending_municipalities": 0,
            "risk_classes": {"unknown": 0, "low": 0, "moderate": 0, "high": 0, "very_high": 0},
            "available_source_scenario_count": 0,
        })
        prov["municipality_count"] += 1
        if record["summary"]["status"] == "computed":
            prov["computed_municipalities"] += 1
        else:
            prov["pending_municipalities"] += 1
        prov["risk_classes"][record["summary"]["risk_class"]] += 1
        prov["available_source_scenario_count"] = max(
            prov["available_source_scenario_count"],
            record["summary"]["available_source_scenario_count"],
        )

    return {
        "municipality_count": len(records),
        "computed_municipalities": exact_records,
        "pending_municipalities": len(records) - exact_records,
        "province_summary": province_summary,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compute Project NOAH municipal exposure analytics.")
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    args = parser.parse_args(argv)

    municipalities = _load_json(MUNICIPALITIES_PATH, [])
    boundaries = _load_json(MUNICIPAL_BOUNDARIES_PATH, {"features": []})
    catalog = _load_json(CATALOG_PATH, {"hazards": []})
    source_index = _load_json(SOURCE_INDEX_PATH, None)

    specs = _scenario_specs(catalog)
    source_status = _source_lookup(source_index)
    records = _build_municipal_records(municipalities, boundaries)
    ready, exact_note = _compute_exact(records, specs)
    _apply_source_status(records, specs, source_status, ready)
    summary = _summarize_records(records)

    output = {
        "meta": {
            "generated_by": "scripts/compute_noah_municipal_exposure.py",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "status": "computed" if ready else "pending_local_geometry",
            "method": "municipality_polygon_intersection" if ready else "source_readiness_only",
            "exact_note": exact_note,
            "source": "Project NOAH hazard maps via BetterGov PMTiles/source mirror",
            "source_url": "https://huggingface.co/datasets/bettergovph/project-noah-hazard-maps",
            "license": "ODC-ODbL",
            "disclaimer": "Exposure analytics are for planning and preparedness. They are not parcel-level engineering or evacuation determinations.",
            "scenario_count": len(specs),
            "ready_scenarios": sorted(ready),
            "pending_scenarios": sorted(set(specs) - ready),
            **summary,
        },
        "source_status": source_status,
        "data": {
            psgc: {k: v for k, v in record.items() if k != "boundary_feature"}
            for psgc, record in records.items()
        },
    }
    _write_json(args.output, output)
    print(
        f"NOAH exposure analytics: {output['meta']['status']} "
        f"({summary['computed_municipalities']}/{summary['municipality_count']} municipalities computed)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
