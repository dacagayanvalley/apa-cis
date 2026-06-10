"""
scripts/fetch_nasa_power/build_climatology.py
Builds the 1991-2020 monthly climatology baseline for all Cagayan Valley
municipalities using the NASA POWER monthly API endpoint.

This script is run ONCE (or annually) — not in the daily pipeline.
Output: config/climatology_1991_2020.json

DA RFO 02 — APA-CIS Climate Information Service
"""

import sys
import time
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
    validate_humidity,
    validate_rainfall,
    validate_temperature,
)

logger = setup_logger(__name__, "build_climatology.log")
cfg = load_config()

BASE_URL = "https://power.larc.nasa.gov/api/temporal/monthly/point"
PARAMETERS = cfg["nasa_power"]["monthly_parameters"]
BASELINE_START = cfg["chirps"]["baseline_start"]   # 1991
BASELINE_END = cfg["chirps"]["baseline_end"]         # 2020
COMMUNITY = cfg["nasa_power"]["community"]


def fetch_monthly_series(
    lat: float,
    lon: float,
    psgc: str,
    start_year: int = BASELINE_START,
    end_year: int = BASELINE_END,
) -> Optional[Dict]:
    """
    Fetch monthly means for all parameters over the baseline period.
    Returns dict keyed by YYYYMM.
    """
    params = {
        "parameters": PARAMETERS,
        "community": COMMUNITY,
        "longitude": round(lon, 4),
        "latitude": round(lat, 4),
        "start": str(start_year),
        "end": str(end_year),
        "format": "JSON",
    }

    resp = retry_get(BASE_URL, params=params, retries=3, delay=3.0, timeout=60, logger=logger)
    if resp is None:
        return None

    try:
        return resp.json()["properties"]["parameter"]
    except (KeyError, ValueError) as exc:
        logger.error(f"Parse error for PSGC {psgc}: {exc}")
        return None


def compute_monthly_normals(param_data: Dict) -> Dict:
    """
    Compute 30-year monthly normals (means) from the raw time series.

    Returns:
        {
          "1": {"rainfall_mm": 80.2, "tmax_c": 32.1, "tmin_c": 22.5, "tmean_c": 27.3, "humidity_pct": 78.0},
          "2": {...},
          ...
          "12": {...}
        }
    """
    import statistics

    normals = {}
    for month in range(1, 13):
        monthly_values = {
            "rainfall_mm": [],
            "tmax_c": [],
            "tmin_c": [],
            "tmean_c": [],
            "humidity_pct": [],
        }

        for year in range(BASELINE_START, BASELINE_END + 1):
            key = f"{year}{month:02d}"

            rain = validate_rainfall(param_data.get("PRECTOTCORR", {}).get(key))
            if rain is not None:
                monthly_values["rainfall_mm"].append(rain)

            tmax = validate_temperature(param_data.get("T2M_MAX", {}).get(key))
            if tmax is not None:
                monthly_values["tmax_c"].append(tmax)

            tmin = validate_temperature(param_data.get("T2M_MIN", {}).get(key))
            if tmin is not None:
                monthly_values["tmin_c"].append(tmin)

            tmean = validate_temperature(param_data.get("T2M", {}).get(key))
            if tmean is not None:
                monthly_values["tmean_c"].append(tmean)

            rh = validate_humidity(param_data.get("RH2M", {}).get(key))
            if rh is not None:
                monthly_values["humidity_pct"].append(rh)

        # Compute means with enough data (at least 20 years)
        normals[str(month)] = {
            var: round(statistics.mean(vals), 2) if len(vals) >= 20 else None
            for var, vals in monthly_values.items()
        }
        # Also compute standard deviation for anomaly scoring
        for var, vals in monthly_values.items():
            if len(vals) >= 10:
                normals[str(month)][f"{var}_std"] = round(statistics.stdev(vals), 2)
            else:
                normals[str(month)][f"{var}_std"] = None

    return normals


def build_all_climatology() -> Dict:
    """
    Build climatology baseline for all municipalities.

    Returns:
        {
            "meta": {...},
            "municipalities": {
                "023101000": {
                    "name": "City of Tuguegarao",
                    "normals": {"1": {...}, "2": {...}, ...}
                },
                ...
            }
        }
    """
    municipalities = load_municipalities()
    result = {
        "meta": {
            "baseline_period": f"{BASELINE_START}–{BASELINE_END}",
            "source": "NASA POWER (Community: AG)",
            "generated_at": __import__("datetime").datetime.utcnow().isoformat(),
            "note": "Monthly normals computed as arithmetic mean over 30-year baseline",
        },
        "municipalities": {},
    }

    total = len(municipalities)
    for i, mun in enumerate(municipalities):
        psgc = mun["psgc"]
        logger.info(
            f"[{i+1}/{total}] {mun['name']} ({mun['province']}) — "
            f"lat={mun['lat']}, lon={mun['lon']}"
        )

        param_data = fetch_monthly_series(mun["lat"], mun["lon"], psgc)
        if param_data is None:
            logger.warning(f"Skipping {mun['name']} — no data returned")
            continue

        normals = compute_monthly_normals(param_data)
        result["municipalities"][psgc] = {
            "name": mun["name"],
            "province": mun["province"],
            "lat": mun["lat"],
            "lon": mun["lon"],
            "normals": normals,
        }

        # Save intermediate checkpoint every 10 municipalities
        if (i + 1) % 10 == 0:
            checkpoint_path = PROJECT_ROOT / "config" / "climatology_checkpoint.json"
            save_json(result, checkpoint_path)
            logger.info(f"Checkpoint saved at {i+1} municipalities")

        time.sleep(cfg["nasa_power"]["request_delay_seconds"])

    return result


def run() -> None:
    logger.info(
        f"=== Building 1991-2020 Climatology Baseline "
        f"({len(load_municipalities())} municipalities) ==="
    )

    climatology = build_all_climatology()

    output_path = PROJECT_ROOT / "config" / "climatology_1991_2020.json"
    save_json(climatology, output_path)
    logger.info(f"Climatology saved → {output_path}")

    # Also save a flattened version for quick lookup
    flat = {}
    for psgc, data in climatology["municipalities"].items():
        flat[psgc] = data["normals"]
    flat_path = PROJECT_ROOT / "config" / "climatology_flat.json"
    save_json(flat, flat_path)
    logger.info(f"Flat lookup saved → {flat_path}")

    log_etl_event(
        source="nasa_power_climatology",
        run_date=__import__("datetime").date.today().isoformat(),
        records_fetched=len(load_municipalities()),
        records_valid=len(climatology["municipalities"]),
        status="success",
        message=f"Baseline {BASELINE_START}-{BASELINE_END}",
    )


if __name__ == "__main__":
    run()
