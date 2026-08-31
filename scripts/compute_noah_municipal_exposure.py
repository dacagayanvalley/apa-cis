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
import zipfile
from io import BytesIO
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote

import requests

ROOT = Path(__file__).resolve().parents[1]
MUNICIPALITIES_PATH = ROOT / "config" / "municipalities.json"
MUNICIPAL_BOUNDARIES_PATH = ROOT / "data" / "boundaries" / "municipalities_simplified.geojson"
NOAH_DIR = ROOT / "data" / "geospatial" / "noah"
CATALOG_PATH = ROOT / "data" / "reference" / "noah_hazard_overlays.json"
SOURCE_INDEX_PATH = ROOT / "data" / "reference" / "noah_region2_source_files.json"
OUTPUT_PATH = ROOT / "data" / "processed" / "noah" / "municipal_hazard_exposure.json"
RAW_NOAH_DOWNLOADS = ROOT / "data" / "raw" / "noah" / "downloads"

LEVELS = ("1", "2", "3")
LEVEL_NAMES = {"1": "low", "2": "medium", "3": "high"}
RISK_ORDER = {"unknown": 0, "low": 1, "moderate": 2, "high": 3, "very_high": 4}
REGION2_PROVINCES = ["Batanes", "Cagayan", "Isabela", "Nueva Vizcaya", "Quirino"]
DEBRIS_FLOW_DIRECT_URLS = [
    "https://huggingface.co/datasets/bettergovph/project-noah-hazard-maps/resolve/main/Landslide/DebrisFlowAlluvialFan/Philippines_AlluvialFan.zip",
    "https://huggingface.co/datasets/bettergovph/project-noah-hazard-maps/resolve/main/Landslide/DebrisFlowAlluvialFan/Philippines_DebrisFlow.zip",
]
SCENARIO_SOURCE_FOLDERS = {
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
        feature = record.get("boundary_feature")
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


def _load_direct_geometry_tools():
    try:
        import shapefile
        from pyproj import CRS, Transformer
        from shapely.geometry import Polygon, shape
        from shapely.validation import make_valid
        from shapely.strtree import STRtree
    except Exception:
        return None
    return {
        "shapefile": shapefile,
        "CRS": CRS,
        "Transformer": Transformer,
        "Polygon": Polygon,
        "shape": shape,
        "make_valid": make_valid,
        "STRtree": STRtree,
    }


def _download_zip(url: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(url, stream=True, timeout=180) as response:
        response.raise_for_status()
        with path.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    handle.write(chunk)


def _local_source_zips(source_index: dict[str, Any] | None, scenario_id: str, download_missing: bool = False) -> list[Path]:
    folders = {item["folder"]: item.get("files", []) for item in (source_index or {}).get("folders", [])}
    paths: list[Path] = []
    for folder in SCENARIO_SOURCE_FOLDERS.get(scenario_id, []):
        for item in folders.get(folder, []):
            rel_path = item.get("path")
            if not rel_path:
                continue
            local_path = RAW_NOAH_DOWNLOADS / rel_path
            if download_missing and (not local_path.exists() or local_path.stat().st_size <= 0):
                url = item.get("download_url")
                if url:
                    print(f"Downloading {rel_path}", flush=True)
                    _download_zip(url, local_path)
            if local_path.exists() and local_path.stat().st_size > 0:
                paths.append(local_path)
    if scenario_id == "debris_flow":
        for url in DEBRIS_FLOW_DIRECT_URLS:
            rel_path = unquote(url.split("/resolve/main/", 1)[-1])
            local_path = RAW_NOAH_DOWNLOADS / rel_path
            if download_missing and (not local_path.exists() or local_path.stat().st_size <= 0):
                print(f"Downloading {rel_path}", flush=True)
                _download_zip(url, local_path)
            if local_path.exists() and local_path.stat().st_size > 0:
                paths.append(local_path)
    return paths


def _zip_shapefile_members(path: Path) -> tuple[bytes, bytes, bytes, str | None]:
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        shp_name = next((name for name in names if name.lower().endswith(".shp")), None)
        shx_name = next((name for name in names if name.lower().endswith(".shx")), None)
        dbf_name = next((name for name in names if name.lower().endswith(".dbf")), None)
        prj_name = next((name for name in names if name.lower().endswith(".prj")), None)
        if not shp_name or not shx_name or not dbf_name:
            raise ValueError(f"{path} does not contain a complete shapefile")
        prj = archive.read(prj_name).decode("utf-8", errors="ignore") if prj_name else None
        return archive.read(shp_name), archive.read(shx_name), archive.read(dbf_name), prj


def _direct_transformer(prj: str | None, tools: dict[str, Any]):
    if not prj:
        return None
    try:
        crs = tools["CRS"].from_wkt(prj)
    except Exception:
        return None
    if crs.to_epsg() == 4326:
        return None
    return tools["Transformer"].from_crs(crs, tools["CRS"].from_epsg(4326), always_xy=True)


def _shape_part_polygons(shape_obj: Any, transformer: Any, polygon_cls: Any):
    points = shape_obj.points
    starts = list(shape_obj.parts) + [len(points)]
    for idx in range(len(starts) - 1):
        raw_ring = points[starts[idx]:starts[idx + 1]]
        if len(raw_ring) < 4:
            continue
        if transformer:
            ring = [transformer.transform(x, y) for x, y in raw_ring]
        else:
            ring = raw_ring
        if ring[0] != ring[-1]:
            ring.append(ring[0])
        try:
            geom = polygon_cls(ring)
            if not geom.is_valid:
                geom = geom.buffer(0)
            if not geom.is_empty and geom.area > 0:
                yield geom
        except Exception:
            continue


def _compute_from_local_zips(
    records: dict[str, dict[str, Any]],
    specs: dict[str, dict[str, Any]],
    source_index: dict[str, Any] | None,
    already_ready: set[str],
    download_missing: bool = False,
) -> tuple[set[str], str | None]:
    tools = _load_direct_geometry_tools()
    if not tools:
        return set(), "Install shapely, pyshp, and pyproj to compute direct ZIP intersections."

    municipality_items = []
    for record in records.values():
        feature = record.get("boundary_feature")
        if not feature or not feature.get("geometry"):
            continue
        geom = tools["shape"](feature["geometry"])
        if not geom.is_valid:
            geom = tools["make_valid"](geom)
        if geom.is_empty:
            continue
        municipality_items.append((record["psgc"], geom))
    if not municipality_items:
        return set(), "Municipal boundary geometries are missing."

    municipality_geoms = [item[1] for item in municipality_items]
    municipality_tree = tools["STRtree"](municipality_geoms)
    direct_ready: set[str] = set()
    note_parts = []

    for scenario_id, spec in specs.items():
        if scenario_id in already_ready:
            continue
        zip_paths = _local_source_zips(source_index, scenario_id, download_missing=download_missing)
        if not zip_paths:
            continue
        covered_provinces = {_province_from_path(path.name) for path in zip_paths}

        area_by_psgc_level = {
            record["psgc"]: {level: 0.0 for level in LEVELS}
            for record in records.values()
        }
        processed_parts = 0
        for zip_path in zip_paths:
            try:
                shp, shx, dbf, prj = _zip_shapefile_members(zip_path)
                transformer = _direct_transformer(prj, tools)
                reader = tools["shapefile"].Reader(shp=BytesIO(shp), shx=BytesIO(shx), dbf=BytesIO(dbf))
            except Exception as exc:
                note_parts.append(f"{scenario_id}: could not read {zip_path.name}: {exc}")
                continue

            for shape_record in reader.iterShapeRecords():
                props = shape_record.record.as_dict()
                raw_level = (
                    props.get("hazard_level")
                    or props.get(spec["attribute"])
                    or props.get("Var")
                    or props.get("VAR")
                    or props.get("HAZ")
                    or props.get("LH")
                    or props.get("SS")
                    or props.get("ALLUVIAL")
                    or props.get("GRIDCODE")
                )
                try:
                    level = str(int(float(raw_level)))
                except (TypeError, ValueError):
                    continue
                if scenario_id == "debris_flow" and level == "4":
                    level = "3"
                if level not in LEVELS:
                    continue

                for hazard_part in _shape_part_polygons(shape_record.shape, transformer, tools["Polygon"]):
                    processed_parts += 1
                    for idx in municipality_tree.query(hazard_part):
                        psgc, mun_geom = municipality_items[int(idx)]
                        if not _bbox_intersects(mun_geom.bounds, hazard_part.bounds):
                            continue
                        try:
                            exposed = mun_geom.intersection(hazard_part)
                        except Exception:
                            try:
                                exposed = tools["make_valid"](mun_geom).intersection(tools["make_valid"](hazard_part))
                            except Exception:
                                continue
                        if not exposed.is_empty:
                            area_by_psgc_level[psgc][level] += exposed.area

        if not processed_parts:
            continue
        direct_ready.add(scenario_id)

        for record in records.values():
            if record["province"] not in covered_provinces:
                continue
            mun_geom = next((geom for psgc, geom in municipality_items if psgc == record["psgc"]), None)
            stats = _blank_level_stats()
            max_level = None
            if mun_geom and record.get("area_sqkm") and mun_geom.area > 0:
                for level in LEVELS:
                    pct = max(0.0, min(100.0, (area_by_psgc_level[record["psgc"]][level] / mun_geom.area) * 100.0))
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
                "method": "direct_noah_zip_part_intersection",
                "source_zips": [str(path.relative_to(RAW_NOAH_DOWNLOADS)).replace("\\", "/") for path in zip_paths],
            }

    return direct_ready, "; ".join(note_parts) if note_parts else None


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
    parser.add_argument("--scenario", action="append", help="Limit computation to one or more scenario IDs.")
    parser.add_argument("--download-missing", action="store_true", help="Download missing source ZIPs before computing.")
    args = parser.parse_args(argv)

    municipalities = _load_json(MUNICIPALITIES_PATH, [])
    boundaries = _load_json(MUNICIPAL_BOUNDARIES_PATH, {"features": []})
    catalog = _load_json(CATALOG_PATH, {"hazards": []})
    source_index = _load_json(SOURCE_INDEX_PATH, None)

    specs = _scenario_specs(catalog)
    if args.scenario:
        requested = set(args.scenario)
        unknown = requested - set(specs)
        if unknown:
            raise ValueError(f"Unknown NOAH scenario(s): {', '.join(sorted(unknown))}")
        specs = {key: value for key, value in specs.items() if key in requested}
    source_status = _source_lookup(source_index)
    records = _build_municipal_records(municipalities, boundaries)
    ready, exact_note = _compute_exact(records, specs)
    direct_ready, direct_note = _compute_from_local_zips(
        records,
        specs,
        source_index,
        ready,
        download_missing=args.download_missing,
    )
    ready = ready | direct_ready
    notes = [note for note in (exact_note, direct_note) if note]
    _apply_source_status(records, specs, source_status, ready)
    summary = _summarize_records(records)

    output = {
        "meta": {
            "generated_by": "scripts/compute_noah_municipal_exposure.py",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "status": "computed" if ready else "pending_local_geometry",
            "method": "municipality_polygon_intersection" if ready else "source_readiness_only",
            "exact_note": "; ".join(notes) if notes else None,
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
