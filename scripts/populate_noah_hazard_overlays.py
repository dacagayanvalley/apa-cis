"""
Download and convert Region 2 Project NOAH hazard data into web GeoJSON.

Raw source ZIPs are stored under data/raw/noah/ and are intentionally ignored
by Git. Prepared, simplified overlays are written to data/geospatial/noah/.
"""

from __future__ import annotations

import json
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import unquote

import requests
import shapefile
from pyproj import CRS, Transformer

from list_noah_region2_sources import main as list_sources


ROOT = Path(__file__).resolve().parents[1]
SOURCE_INDEX = ROOT / "data" / "reference" / "noah_region2_source_files.json"
RAW_DIR = ROOT / "data" / "raw" / "noah" / "downloads"
OUTPUT_DIR = ROOT / "data" / "geospatial" / "noah"
STATUS_PATH = OUTPUT_DIR / "noah_overlay_build_status.json"

REGION2_BBOX = (120.65, 15.55, 122.85, 21.25)
SIMPLIFY_TOLERANCE_DEG = 0.0012
COORD_PRECISION = 5

SCENARIOS = {
    "flood_5yr": {
        "folders": ["Flood/5yr"],
        "attribute": "Var",
        "family": "flood",
        "label": "Flood 5-year rain return period",
    },
    "flood_25yr": {
        "folders": ["Flood/25yr"],
        "attribute": "Var",
        "family": "flood",
        "label": "Flood 25-year rain return period",
    },
    "flood_100yr": {
        "folders": ["Flood/100yr"],
        "attribute": "Var",
        "family": "flood",
        "label": "Flood 100-year rain return period",
    },
    "landslide": {
        "folders": ["Landslide/LandslideHazards"],
        "attribute": "HAZ",
        "family": "landslide",
        "label": "Landslide susceptibility",
    },
    "debris_flow": {
        "direct_urls": [
            "https://huggingface.co/datasets/bettergovph/project-noah-hazard-maps/resolve/main/Landslide/DebrisFlowAlluvialFan/Philippines_AlluvialFan.zip",
            "https://huggingface.co/datasets/bettergovph/project-noah-hazard-maps/resolve/main/Landslide/DebrisFlowAlluvialFan/Philippines_DebrisFlow.zip",
        ],
        "attribute": "HAZ",
        "family": "landslide",
        "label": "Debris flow and alluvial fan",
    },
    "storm_surge_ssa1": {
        "folders": ["Storm Surge/StormSurgeAdvisory1"],
        "attribute": "HAZ",
        "family": "storm_surge",
        "label": "Storm Surge Advisory 1",
    },
    "storm_surge_ssa2": {
        "folders": ["Storm Surge/StormSurgeAdvisory2"],
        "attribute": "HAZ",
        "family": "storm_surge",
        "label": "Storm Surge Advisory 2",
    },
    "storm_surge_ssa3": {
        "folders": ["Storm Surge/StormSurgeAdvisory3"],
        "attribute": "HAZ",
        "family": "storm_surge",
        "label": "Storm Surge Advisory 3",
    },
    "storm_surge_ssa4": {
        "folders": ["Storm Surge/StormSurgeAdvisory4"],
        "attribute": "HAZ",
        "family": "storm_surge",
        "label": "Storm Surge Advisory 4",
    },
}

LEVEL_LABELS = {"1": "Low", "2": "Medium", "3": "High"}
LEVEL_FIELD_CANDIDATES = (
    "hazard_level",
    "Var",
    "VAR",
    "HAZ",
    "GRIDCODE",
    "gridcode",
    "GRID",
    "grid",
    "ALLUVIAL",
    "alluvial",
)


def _download(url: str) -> Path:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    marker = "/resolve/main/"
    if marker in url:
        relative = unquote(url.split(marker, 1)[1])
    else:
        relative = url.rsplit("/", 1)[-1]
    path = RAW_DIR / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.stat().st_size > 0:
        return path
    print(f"Downloading {url}", flush=True)
    with requests.get(url, stream=True, timeout=120) as response:
        response.raise_for_status()
        with path.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    handle.write(chunk)
    return path


def _load_source_index() -> dict[str, list[dict[str, Any]]]:
    if not SOURCE_INDEX.exists():
        list_sources()
    with SOURCE_INDEX.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    return {folder["folder"]: folder["files"] for folder in data["folders"]}


def _scenario_urls(scenario: dict[str, Any], index: dict[str, list[dict[str, Any]]]) -> list[str]:
    if "direct_urls" in scenario:
        return scenario["direct_urls"]
    urls = []
    for folder in scenario.get("folders", []):
        urls.extend(item["download_url"] for item in index.get(folder, []))
    return urls


def _zip_members(path: Path) -> tuple[bytes, bytes, bytes, str | None]:
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


def _transformer(prj: str | None) -> Transformer | None:
    if not prj:
        return None
    try:
        crs = CRS.from_wkt(prj)
    except Exception:
        return None
    if crs.to_epsg() == 4326:
        return None
    return Transformer.from_crs(crs, CRS.from_epsg(4326), always_xy=True)


def _bbox_intersects(bbox: Iterable[float], transformer: Transformer | None) -> bool:
    minx, miny, maxx, maxy = bbox
    corners = [(minx, miny), (minx, maxy), (maxx, miny), (maxx, maxy)]
    if transformer:
        corners = [transformer.transform(x, y) for x, y in corners]
    xs = [p[0] for p in corners]
    ys = [p[1] for p in corners]
    b = (min(xs), min(ys), max(xs), max(ys))
    return not (
        b[2] < REGION2_BBOX[0]
        or b[0] > REGION2_BBOX[2]
        or b[3] < REGION2_BBOX[1]
        or b[1] > REGION2_BBOX[3]
    )


def _linear_simplify(points: list[tuple[float, float]], tolerance: float) -> list[tuple[float, float]]:
    if len(points) <= 4:
        return points
    kept = [points[0]]
    last_x, last_y = points[0]
    for x, y in points[1:-1]:
        if abs(x - last_x) >= tolerance or abs(y - last_y) >= tolerance:
            kept.append((x, y))
            last_x, last_y = x, y
    kept.append(points[-1])
    return kept


def _clean_ring(coords: Iterable[Iterable[float]], transformer: Transformer | None) -> list[list[float]]:
    points = []
    for raw_x, raw_y, *_rest in coords:
        x, y = transformer.transform(raw_x, raw_y) if transformer else (raw_x, raw_y)
        points.append((x, y))
    if len(points) < 4:
        return []
    if points[0] != points[-1]:
        points.append(points[0])
    simplified = _linear_simplify(points[:-1], SIMPLIFY_TOLERANCE_DEG)
    if len(simplified) < 3:
        return []
    simplified.append(simplified[0])
    return [[round(x, COORD_PRECISION), round(y, COORD_PRECISION)] for x, y in simplified]


def _clean_geometry(geometry: dict[str, Any], transformer: Transformer | None) -> dict[str, Any] | None:
    if geometry["type"] == "Polygon":
        rings = [_clean_ring(ring, transformer) for ring in geometry["coordinates"]]
        rings = [ring for ring in rings if ring]
        if not rings:
            return None
        return {"type": "Polygon", "coordinates": rings}
    if geometry["type"] == "MultiPolygon":
        polygons = []
        for polygon in geometry["coordinates"]:
            rings = [_clean_ring(ring, transformer) for ring in polygon]
            rings = [ring for ring in rings if ring]
            if rings:
                polygons.append(rings)
        if not polygons:
            return None
        return {"type": "MultiPolygon", "coordinates": polygons}
    return None


def _hazard_level(properties: dict[str, Any]) -> str | None:
    for field in LEVEL_FIELD_CANDIDATES:
        value = properties.get(field)
        if value is None or value == "":
            continue
        try:
            level = str(int(float(value)))
        except (TypeError, ValueError):
            continue
        if level in LEVEL_LABELS:
            return level
    return None


def _convert_zip(path: Path, scenario_id: str, spec: dict[str, Any]) -> list[dict[str, Any]]:
    shp, shx, dbf, prj = _zip_members(path)
    transformer = _transformer(prj)
    features = []
    reader = shapefile.Reader(shp=BytesIO(shp), shx=BytesIO(shx), dbf=BytesIO(dbf))
    for shape_record in reader.iterShapeRecords():
        shape = shape_record.shape
        if not _bbox_intersects(shape.bbox, transformer):
            continue
        properties = shape_record.record.as_dict()
        level = _hazard_level(properties)
        if not level:
            continue
        geometry = _clean_geometry(shape.__geo_interface__, transformer)
        if not geometry:
            continue
        features.append(
            {
                "type": "Feature",
                "properties": {
                    "hazard_family": spec["family"],
                    "hazard_source": "Project NOAH",
                    "scenario": scenario_id,
                    "scenario_label": spec["label"],
                    "hazard_level": int(level),
                    "hazard_label": LEVEL_LABELS[level],
                    spec["attribute"]: int(level),
                    "source_zip": str(path.relative_to(RAW_DIR)).replace("\\", "/"),
                },
                "geometry": geometry,
            }
        )
    return features


def _write_geojson(scenario_id: str, spec: dict[str, Any], features: list[dict[str, Any]]) -> dict[str, Any]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / f"{scenario_id}_r2.geojson"
    data = {
        "type": "FeatureCollection",
        "name": f"project_noah_{scenario_id}_r2",
        "metadata": {
            "source": "Project NOAH via BetterGov Philippines mirror",
            "license": "ODC-ODbL",
            "region": "Region II (Cagayan Valley)",
            "scenario": scenario_id,
            "scenario_label": spec["label"],
            "simplify_tolerance_degrees": SIMPLIFY_TOLERANCE_DEG,
            "coordinate_precision": COORD_PRECISION,
        },
        "features": features,
    }
    with output_path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, separators=(",", ":"))
    return {
        "id": scenario_id,
        "status": "ready",
        "output": str(output_path),
        "feature_count": len(features),
        "size_bytes": output_path.stat().st_size,
    }


def main() -> int:
    index = _load_source_index()
    results = []
    for scenario_id, spec in SCENARIOS.items():
        urls = _scenario_urls(spec, index)
        if not urls:
            results.append({"id": scenario_id, "status": "missing_sources"})
            print(f"{scenario_id}: no source ZIPs found")
            continue
        features = []
        for url in urls:
            zip_path = _download(url)
            converted = _convert_zip(zip_path, scenario_id, spec)
            features.extend(converted)
            print(f"{scenario_id}: {zip_path.relative_to(RAW_DIR)} -> {len(converted)} features", flush=True)
        results.append(_write_geojson(scenario_id, spec, features))

    with STATUS_PATH.open("w", encoding="utf-8") as handle:
        json.dump(
            {
                "generated_by": "scripts/populate_noah_hazard_overlays.py",
                "source_index": str(SOURCE_INDEX),
                "results": results,
            },
            handle,
            indent=2,
        )
        handle.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
