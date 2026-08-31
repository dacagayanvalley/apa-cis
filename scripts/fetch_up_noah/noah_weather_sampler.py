"""
scripts/fetch_up_noah/noah_weather_sampler.py
Sample public UP NOAH weather raster overlays at Region 2 municipal centroids.

The NOAH weather updates page exposes PNG overlays, not a municipal API. This
script downloads those overlays, samples municipal centroid pixels, classifies
the sampled colors against NOAH legend classes, and writes a compact JSON file
that the APA-CIS indicator engine can consume as the second-priority weather
source after APA CIS.
"""

from __future__ import annotations

import argparse
import math
import sys
import time
from datetime import date
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

try:
    from PIL import Image
except ImportError:  # pragma: no cover - exercised by operator environment
    Image = None

from scripts.utils import (
    PROJECT_ROOT,
    load_config,
    load_municipalities,
    save_json,
    setup_logger,
    today_pht,
)

logger = setup_logger("fetch_up_noah", "fetch_up_noah.log")
cfg = load_config()

RGB = Tuple[int, int, int]
Bounds = Tuple[float, float, float, float]  # west, north, east, south

RAINFALL_BOUNDS: Bounds = (115.35, 21.55, 128.25, 3.85)
FORECAST_TEMP_BOUNDS: Bounds = (116.855, 19.402, 127.055, 5.205)

RAINFALL_COLORS: List[Tuple[str, RGB]] = [
    ("light", (17, 194, 195)),
    ("moderate", (15, 62, 247)),
    ("heavy", (12, 10, 151)),
    ("intense", (255, 151, 8)),
    ("torrential", (255, 50, 17)),
]

FORECAST_COLORS: List[Tuple[str, RGB]] = [
    ("cloudy", (160, 160, 160)),
    ("0-30mm", (19, 150, 230)),
    ("30-60mm", (15, 62, 247)),
    ("60-100mm", (12, 28, 120)),
    ("100-140mm", (246, 247, 14)),
    ("140-200mm", (255, 50, 17)),
    ("200-400mm", (188, 0, 119)),
    (">=400mm", (0, 0, 0)),
]

TEMP_COLORS: List[Tuple[str, RGB]] = [
    ("0-5c", (255, 255, 255)),
    ("5-10c", (214, 239, 250)),
    ("10-15c", (20, 192, 233)),
    ("15-20c", (14, 231, 226)),
    ("20-27c", (14, 238, 127)),
    ("27-33c", (252, 249, 17)),
    ("33-40c", (255, 142, 8)),
    ("40-50c", (255, 45, 16)),
    (">=50c", (143, 0, 0)),
]

LAYER_SPECS = {
    "rainfall_1h_mm": {
        "path": "contours/1hr_latest_rainfall_contour.png",
        "bounds": RAINFALL_BOUNDS,
        "palette": RAINFALL_COLORS,
        "ranges": [(0, 2.5), (2.5, 7.5), (7.5, 15), (15, 30), (30, None)],
    },
    "rainfall_3h_mm": {
        "path": "contours/3hr_latest_rainfall_contour.png",
        "bounds": RAINFALL_BOUNDS,
        "palette": RAINFALL_COLORS,
        "ranges": [(0, 20), (20, 40), (40, 60), (60, 70), (70, None)],
    },
    "rainfall_6h_mm": {
        "path": "contours/6hr_latest_rainfall_contour.png",
        "bounds": RAINFALL_BOUNDS,
        "palette": RAINFALL_COLORS,
        "ranges": [(0, 40), (40, 80), (80, 120), (120, 160), (160, None)],
    },
    "rainfall_12h_mm": {
        "path": "contours/12hr_latest_rainfall_contour.png",
        "bounds": RAINFALL_BOUNDS,
        "palette": RAINFALL_COLORS,
        "ranges": [(0, 60), (60, 120), (120, 180), (180, 240), (240, None)],
    },
    "rainfall_24h_mm": {
        "path": "contours/24hr_latest_rainfall_contour.png",
        "bounds": RAINFALL_BOUNDS,
        "palette": RAINFALL_COLORS,
        "ranges": [(0, 100), (100, 200), (200, 300), (300, 400), (400, None)],
    },
    "rainfall_tomorrow_mm": {
        "path": "rainfall/rainmap_gtif_day1.png",
        "bounds": FORECAST_TEMP_BOUNDS,
        "palette": FORECAST_COLORS,
        "ranges": [(None, None), (0, 30), (30, 60), (60, 100), (100, 140), (140, 200), (200, 400), (400, None)],
    },
    "heat_index_c": {
        "path": "temperature/HI_1.png",
        "bounds": FORECAST_TEMP_BOUNDS,
        "palette": TEMP_COLORS,
        "ranges": [(0, 5), (5, 10), (10, 15), (15, 20), (20, 27), (27, 33), (33, 40), (40, 50), (50, None)],
    },
    "tmax_c": {
        "path": "temperature/t2m_1.png",
        "bounds": FORECAST_TEMP_BOUNDS,
        "palette": [
            ("20-21c", (255, 255, 255)),
            ("21-22c", (31, 18, 220)),
            ("22-23c", (14, 91, 244)),
            ("23-24c", (21, 142, 249)),
            ("24-25c", (18, 192, 233)),
            ("25-26c", (14, 231, 226)),
            ("26-27c", (14, 238, 127)),
            ("27-28c", (120, 238, 63)),
            ("28-29c", (252, 249, 17)),
            ("29-30c", (255, 210, 8)),
            ("30-31c", (255, 142, 8)),
            ("31-32c", (255, 91, 8)),
            ("32-33c", (255, 45, 16)),
            ("33-34c", (242, 0, 0)),
            ("34-35c", (190, 0, 0)),
            ("35-36c", (143, 0, 0)),
        ],
        "ranges": [(20, 21), (21, 22), (22, 23), (23, 24), (24, 25), (25, 26), (26, 27), (27, 28), (28, 29), (29, 30), (30, 31), (31, 32), (32, 33), (33, 34), (34, 35), (35, 36)],
    },
}

SAMPLE_OFFSETS = [
    (0.0, 0.0),
    (0.02, 0.0),
    (-0.02, 0.0),
    (0.0, 0.02),
    (0.0, -0.02),
    (0.05, 0.0),
    (-0.05, 0.0),
    (0.0, 0.05),
    (0.0, -0.05),
]


def midpoint(value_range: Tuple[Optional[float], Optional[float]]) -> Optional[float]:
    low, high = value_range
    if low is None and high is None:
        return None
    if high is None:
        return float(low) if low is not None else None
    if low is None:
        return float(high)
    return round((low + high) / 2.0, 2)


def class_label(value_range: Tuple[Optional[float], Optional[float]], unit: str) -> str:
    low, high = value_range
    if low is None and high is None:
        return "cloudy/no-rainfall-value"
    if high is None:
        return f">={low:g}{unit}"
    return f"{low:g}-{high:g}{unit}"


def color_distance(a: RGB, b: RGB) -> float:
    return math.sqrt(sum((a[idx] - b[idx]) ** 2 for idx in range(3)))


def is_no_data(pixel: Tuple[int, ...]) -> bool:
    r, g, b = pixel[:3]
    alpha = pixel[3] if len(pixel) > 3 else 255
    if alpha < 20:
        return True
    if r > 245 and g > 245 and b > 245:
        return True
    return False


def classify_pixel(pixel: Tuple[int, ...], spec: Dict, unit: str) -> Dict:
    rgb = tuple(pixel[:3])
    palette = spec["palette"]
    ranked = sorted(
        (
            (idx, name, color_distance(rgb, ref_rgb), ref_rgb)
            for idx, (name, ref_rgb) in enumerate(palette)
        ),
        key=lambda item: item[2],
    )
    idx, name, distance, ref_rgb = ranked[0]
    value_range = spec["ranges"][idx]
    confidence = "high" if distance <= 35 else "medium" if distance <= 70 else "low"
    if distance > 105:
        return {
            "value": None,
            "class": "unclassified-color",
            "rgb": list(rgb),
            "distance": round(distance, 1),
            "confidence": "low",
        }
    return {
        "value": midpoint(value_range),
        "class": class_label(value_range, unit),
        "legend_name": name,
        "rgb": list(rgb),
        "matched_rgb": list(ref_rgb),
        "distance": round(distance, 1),
        "confidence": confidence,
    }


def lonlat_to_pixel(lon: float, lat: float, bounds: Bounds, width: int, height: int) -> Optional[Tuple[int, int]]:
    west, north, east, south = bounds
    if lon < west or lon > east or lat < south or lat > north:
        return None
    x = round((lon - west) / (east - west) * (width - 1))
    y = round((north - lat) / (north - south) * (height - 1))
    return int(x), int(y)


def sample_layer(image, lon: float, lat: float, spec: Dict, unit: str) -> Dict:
    width, height = image.size
    for lon_offset, lat_offset in SAMPLE_OFFSETS:
        pixel_xy = lonlat_to_pixel(lon + lon_offset, lat + lat_offset, spec["bounds"], width, height)
        if not pixel_xy:
            continue
        pixel = image.getpixel(pixel_xy)
        if is_no_data(pixel):
            continue
        result = classify_pixel(pixel, spec, unit)
        result["pixel"] = list(pixel_xy)
        result["sample_offset"] = [lon_offset, lat_offset]
        return result
    return {
        "value": None,
        "class": "no-data",
        "confidence": "none",
    }


def download_file(url: str, path: Path, timeout: int, retries: int, delay: float) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(url, timeout=timeout)
            resp.raise_for_status()
            path.write_bytes(resp.content)
            return True
        except Exception as exc:
            logger.warning("NOAH download attempt %s/%s failed for %s: %s", attempt, retries, url, exc)
            if attempt < retries:
                time.sleep(delay * attempt)
    return False


def download_layers(run_date: date) -> Dict[str, Path]:
    noah_cfg = cfg.get("up_noah", {})
    base_url = noah_cfg.get("static_api_url", "https://webgis-static.up.edu.ph/api").rstrip("/")
    raw_root = PROJECT_ROOT / cfg["paths"].get("raw_up_noah", "data/raw/up_noah")
    overlay_dir = raw_root / "overlays" / run_date.isoformat()
    timeout = int(noah_cfg.get("timeout_seconds", 45))
    retries = int(noah_cfg.get("retry_attempts", 3))
    delay = float(noah_cfg.get("request_delay_seconds", 0.5))
    downloaded = {}

    for layer_name, spec in LAYER_SPECS.items():
        url = f"{base_url}/{spec['path']}"
        out_path = overlay_dir / spec["path"].replace("/", "_")
        if download_file(url, out_path, timeout=timeout, retries=retries, delay=delay):
            downloaded[layer_name] = out_path
            logger.info("Downloaded UP NOAH %s overlay to %s", layer_name, out_path)
        else:
            logger.warning("UP NOAH %s overlay unavailable; layer will be null", layer_name)
    return downloaded


def open_images(paths: Dict[str, Path]) -> Dict[str, object]:
    images = {}
    for layer_name, path in paths.items():
        try:
            images[layer_name] = Image.open(path).convert("RGBA")
        except Exception as exc:
            logger.warning("Unable to read UP NOAH overlay %s at %s: %s", layer_name, path, exc)
    return images


def build_record(mun: Dict, images: Dict[str, object], run_date: date) -> Dict:
    record = {
        "psgc": mun["psgc"],
        "municipality": mun["name"],
        "province": mun["province"],
        "lat": mun.get("lat"),
        "lon": mun.get("lon"),
        "date": run_date.isoformat(),
        "source": "up_noah",
        "method": "raster_overlay_centroid_sampling",
        "sampling_note": "Values are legend-class estimates from public UP NOAH PNG overlays, not station observations.",
    }
    qa = {}
    for layer_name, image in images.items():
        unit = "c" if layer_name.endswith("_c") else "mm"
        sample = sample_layer(image, float(mun["lon"]), float(mun["lat"]), LAYER_SPECS[layer_name], unit)
        record[layer_name] = sample["value"]
        qa[layer_name] = {k: v for k, v in sample.items() if k != "value"}
    record["qa"] = qa
    return record


def write_output(records: List[Dict], downloaded: Dict[str, Path], run_date: date) -> Dict:
    raw_root = PROJECT_ROOT / cfg["paths"].get("raw_up_noah", "data/raw/up_noah")
    output = {
        "source": "up_noah",
        "source_name": "UP NOAH Weather Updates",
        "source_url": cfg.get("up_noah", {}).get("weather_updates_url", "https://noah.up.edu.ph/weather-updates/rainfall-contour"),
        "date": run_date.isoformat(),
        "method": "raster_overlay_centroid_sampling",
        "method_note": "Municipal values are estimated from georeferenced NOAH image overlays using legend-class midpoints/lower bounds.",
        "records_total": len(records),
        "records_with_rainfall_24h": sum(1 for rec in records if rec.get("rainfall_24h_mm") is not None),
        "records_with_heat_index": sum(1 for rec in records if rec.get("heat_index_c") is not None),
        "records_with_tmax": sum(1 for rec in records if rec.get("tmax_c") is not None),
        "downloaded_layers": {name: str(path.relative_to(PROJECT_ROOT)) for name, path in downloaded.items()},
        "data": records,
    }
    dated_path = raw_root / f"up_noah_{run_date.isoformat()}.json"
    current_path = raw_root / "up_noah_current.json"
    save_json(output, dated_path)
    save_json(output, current_path)
    return output


def run(target_date: Optional[date] = None) -> Dict:
    if Image is None:
        raise RuntimeError("Pillow is required for UP NOAH PNG sampling. Install with: pip install -r requirements.txt")
    if not cfg.get("up_noah", {}).get("enabled", True):
        logger.info("UP NOAH weather sampling disabled in config/settings.yaml")
        return {}

    run_date = target_date or today_pht()
    downloaded = download_layers(run_date)
    images = open_images(downloaded)
    municipalities = load_municipalities()
    records = [build_record(mun, images, run_date) for mun in municipalities]
    output = write_output(records, downloaded, run_date)
    logger.info(
        "UP NOAH sampling complete: %s records, %s with 24h rainfall, %s with heat index, %s with tmax",
        output["records_total"],
        output["records_with_rainfall_24h"],
        output["records_with_heat_index"],
        output["records_with_tmax"],
    )
    return output


def parse_args(argv: Optional[Iterable[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch and sample UP NOAH weather overlays.")
    parser.add_argument("--date", help="Override output date as YYYY-MM-DD.")
    return parser.parse_args(argv)


def main(argv: Optional[Iterable[str]] = None) -> int:
    args = parse_args(argv)
    target_date = date.fromisoformat(args.date) if args.date else None
    run(target_date)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
