"""
scripts/fetch_chirps/fetch_daily.py
Automated CHIRPS daily rainfall ingestion for APA-CIS.

Downloads the CHIRPS v2.0 global daily GeoTIFF and, when rasterio is
available, samples rainfall at each municipal centroid. If rasterio is not
installed, the raw raster and manifest are still saved and the pipeline
continues using NASA POWER rainfall as fallback.
"""

import gzip
import re
import shutil
import sys
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.utils import (
    PROJECT_ROOT,
    load_config,
    load_municipalities,
    log_etl_event,
    retry_get,
    save_json,
    setup_logger,
    today_pht,
)

logger = setup_logger(__name__, "fetch_chirps.log")
cfg = load_config()

BASE_URL = cfg["chirps"]["base_url"].rstrip("/")
RETRY_ATTEMPTS = cfg["chirps"].get("retry_attempts", 3)
TIMEOUT = cfg["chirps"].get("timeout_seconds", 90)
REQUEST_DELAY = cfg["chirps"].get("request_delay_seconds", 1.0)


def chirps_daily_url(target_date: date) -> str:
    """Return CHIRPS daily GeoTIFF gzip URL for a target date."""
    year = target_date.year
    ymd = target_date.strftime("%Y.%m.%d")
    return f"{BASE_URL}/{year}/chirps-v2.0.{ymd}.tif.gz"


def discover_latest_available_date(target_date: date) -> date:
    """Find the latest CHIRPS daily raster available on or before target_date."""
    index_url = f"{BASE_URL}/{target_date.year}/"
    resp = retry_get(index_url, retries=1, delay=1.0, timeout=TIMEOUT, logger=logger)
    if resp is None:
        logger.warning("Could not read CHIRPS directory index; trying requested date.")
        return target_date

    pattern = re.compile(r"chirps-v2\.0\.(\d{4})\.(\d{2})\.(\d{2})\.tif\.gz")
    available = []
    for year, month, day in pattern.findall(resp.text):
        d = date(int(year), int(month), int(day))
        if d <= target_date:
            available.append(d)

    if not available:
        logger.warning("No CHIRPS daily rasters found on or before %s", target_date)
        return target_date

    latest_available = max(available)
    if latest_available != target_date:
        logger.warning(
            "CHIRPS raster for %s is not published yet; using latest available %s",
            target_date,
            latest_available,
        )
    return latest_available


def download_chirps_tif(target_date: date) -> Optional[Path]:
    """Download and unzip one CHIRPS daily GeoTIFF."""
    url = chirps_daily_url(target_date)
    raw_dir = PROJECT_ROOT / cfg["paths"]["raw_chirps"] / target_date.strftime("%Y/%m")
    raw_dir.mkdir(parents=True, exist_ok=True)

    gz_path = raw_dir / f"chirps-v2.0.{target_date.strftime('%Y.%m.%d')}.tif.gz"
    tif_path = raw_dir / f"chirps-v2.0.{target_date.strftime('%Y.%m.%d')}.tif"

    if tif_path.exists():
        logger.info(f"CHIRPS raster already exists: {tif_path}")
        return tif_path

    logger.info(f"Downloading CHIRPS daily raster: {url}")
    resp = retry_get(url, retries=RETRY_ATTEMPTS, delay=5.0, timeout=TIMEOUT, logger=logger)
    if resp is None:
        return None

    with open(gz_path, "wb") as file:
        file.write(resp.content)

    with gzip.open(gz_path, "rb") as src, open(tif_path, "wb") as dst:
        shutil.copyfileobj(src, dst)

    save_json({
        "source": "CHIRPS v2.0 global daily",
        "source_url": url,
        "downloaded_at": __import__("datetime").datetime.utcnow().isoformat(),
        "target_date": target_date.isoformat(),
        "raw_gzip": str(gz_path),
        "tif": str(tif_path),
    }, raw_dir / f"chirps_manifest_{target_date.isoformat()}.json")

    time.sleep(REQUEST_DELAY)
    logger.info(f"Saved CHIRPS raster: {tif_path}")
    return tif_path


def sample_municipal_centroids(tif_path: Path, target_date: date) -> List[Dict]:
    """Sample CHIRPS rainfall at municipal centroids using rasterio."""
    try:
        import rasterio
    except ImportError:
        logger.warning(
            "rasterio is not installed; CHIRPS raster downloaded but municipal "
            "sampling was skipped. NASA POWER rainfall will remain the fallback."
        )
        return []

    municipalities = load_municipalities()
    records = []

    with rasterio.open(tif_path) as dataset:
        coords = [(m["lon"], m["lat"]) for m in municipalities]
        sampled = list(dataset.sample(coords))

    for mun, values in zip(municipalities, sampled):
        raw_value = float(values[0]) if values is not None and len(values) else None
        rainfall = None
        if raw_value is not None and raw_value > -9000:
            rainfall = round(max(0.0, raw_value), 2)

        records.append({
            "psgc": mun["psgc"],
            "municipality": mun["name"],
            "province": mun["province"],
            "date": target_date.isoformat(),
            "source": "chirps",
            "source_file": str(tif_path),
            "rainfall_mm": rainfall,
            "lat": mun["lat"],
            "lon": mun["lon"],
        })

    return records


def save_daily_output(records: List[Dict], target_date: date) -> Optional[Path]:
    """Save sampled municipal CHIRPS rainfall records."""
    if not records:
        return None

    year_str = target_date.strftime("%Y")
    month_str = target_date.strftime("%m")
    out_dir = PROJECT_ROOT / cfg["paths"]["processed_daily"] / year_str / month_str
    out_path = out_dir / f"chirps_rainfall_{target_date.isoformat()}.json"
    latest_path = PROJECT_ROOT / cfg["paths"]["processed_daily"] / "chirps_rainfall_latest.json"

    output = {
        "meta": {
            "generated_at": __import__("datetime").datetime.utcnow().isoformat(),
            "date": target_date.isoformat(),
            "source": "CHIRPS v2.0 daily rainfall",
            "municipality_count": len(records),
            "method": "municipal centroid raster sampling",
        },
        "data": records,
    }
    save_json(output, out_path)
    save_json(output, latest_path)
    logger.info(f"Saved CHIRPS municipal rainfall: {latest_path}")
    return out_path


def run(target_date: Optional[date] = None) -> None:
    """Fetch and process CHIRPS rainfall for one day."""
    if target_date is None:
        target_date = today_pht() - timedelta(days=2)
    requested_date = target_date
    target_date = discover_latest_available_date(target_date)

    logger.info(f"=== CHIRPS Daily Rainfall Fetch: {target_date} ===")
    tif_path = download_chirps_tif(target_date)
    if tif_path is None:
        log_etl_event(
            source="chirps_daily",
            run_date=requested_date.isoformat(),
            records_fetched=0,
            records_valid=0,
            status="failed",
            message="Could not download CHIRPS raster",
        )
        return

    records = sample_municipal_centroids(tif_path, target_date)
    save_daily_output(records, target_date)

    status = "success" if records else "warning"
    log_etl_event(
        source="chirps_daily",
        run_date=requested_date.isoformat(),
        records_fetched=len(load_municipalities()),
        records_valid=len(records),
        status=status,
        message=(
            f"Sampled {len(records)} municipal rainfall records"
            if records else "Raster downloaded; rasterio unavailable for sampling"
        ),
    )
    logger.info("=== CHIRPS fetch complete ===")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Fetch CHIRPS daily rainfall for Cagayan Valley")
    parser.add_argument("--date", type=str, default=None, help="Target date YYYY-MM-DD")
    args = parser.parse_args()
    run(date.fromisoformat(args.date) if args.date else None)
