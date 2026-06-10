"""
scripts/fetch_nasa_power/fetch_daily.py
Fetches daily agroclimatic data from NASA POWER API for all
Cagayan Valley municipalities and writes to data/processed/daily/.

DA RFO 02 — APA-CIS Climate Information Service

NASA POWER API docs: https://power.larc.nasa.gov/docs/services/api/
Community: AG (Agroclimatology)
Parameters:
  PRECTOTCORR  — Precipitation corrected (mm/day)
  T2M_MAX      — Daily max temperature at 2m (°C)
  T2M_MIN      — Daily min temperature at 2m (°C)
  T2M          — Daily mean temperature at 2m (°C)
  RH2M         — Relative humidity at 2m (%)
  WS2M         — Wind speed at 2m (m/s)
  WD2M         — Wind direction at 2m (degrees)
  ALLSKY_SFC_SW_DWN — Solar radiation (MJ/m²/day)
  GWETROOT     — Root zone soil wetness (0–1)
"""

import sys
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, List, Optional

# Allow running as script from any working directory
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.utils import (
    PROJECT_ROOT,
    load_config,
    load_municipalities,
    log_etl_event,
    nasa_date_key,
    retry_get,
    save_json,
    setup_logger,
    today_pht,
    validate_humidity,
    validate_rainfall,
    validate_temperature,
    validate_wind,
)

logger = setup_logger(__name__, "fetch_nasa_power.log")
cfg = load_config()


# ── Constants ─────────────────────────────────────────────────────────────────
BASE_URL = "https://power.larc.nasa.gov/api/temporal/daily/point"
PARAMETERS = cfg["nasa_power"]["daily_parameters"]
COMMUNITY = cfg["nasa_power"]["community"]
REQUEST_DELAY = cfg["nasa_power"]["request_delay_seconds"]
RETRY_ATTEMPTS = cfg["nasa_power"]["retry_attempts"]
TIMEOUT = cfg["nasa_power"]["timeout_seconds"]
LAG_DAYS = cfg["nasa_power"]["lag_days"]


# ── Core fetch function ───────────────────────────────────────────────────────
def fetch_one_municipality(
    lat: float,
    lon: float,
    psgc: str,
    target_date: date,
) -> Optional[Dict]:
    """
    Fetch one day's data for a single municipality centroid.

    Returns a cleaned record dict or None on failure.
    """
    date_str = target_date.strftime("%Y%m%d")
    params = {
        "parameters": PARAMETERS,
        "community": COMMUNITY,
        "longitude": round(lon, 4),
        "latitude": round(lat, 4),
        "start": date_str,
        "end": date_str,
        "format": "JSON",
    }

    resp = retry_get(
        BASE_URL, params=params,
        retries=RETRY_ATTEMPTS,
        delay=2.0,
        timeout=TIMEOUT,
        logger=logger,
    )
    if resp is None:
        return None

    try:
        raw = resp.json()
        param_data = raw["properties"]["parameter"]
        key = date_str  # NASA POWER keys are YYYYMMDD

        record = {
            "psgc": psgc,
            "date": target_date.isoformat(),
            "source": "nasa_power",
            "source_url": resp.url,
            "rainfall_mm": validate_rainfall(
                param_data.get("PRECTOTCORR", {}).get(key)
            ),
            "tmax_c": validate_temperature(
                param_data.get("T2M_MAX", {}).get(key)
            ),
            "tmin_c": validate_temperature(
                param_data.get("T2M_MIN", {}).get(key)
            ),
            "tmean_c": validate_temperature(
                param_data.get("T2M", {}).get(key)
            ),
            "humidity_pct": validate_humidity(
                param_data.get("RH2M", {}).get(key)
            ),
            "wind_speed_ms": validate_wind(
                param_data.get("WS2M", {}).get(key)
            ),
            "wind_dir_deg": validate_wind(
                param_data.get("WD2M", {}).get(key)
            ),
            "solar_mj": None,
            "soil_moisture": None,
        }

        # Solar radiation (0–50 MJ/m²/day is realistic)
        solar_raw = param_data.get("ALLSKY_SFC_SW_DWN", {}).get(key)
        if solar_raw is not None and float(solar_raw) != -999.0:
            v = float(solar_raw)
            record["solar_mj"] = v if 0 <= v <= 50 else None

        # Root zone soil wetness (0.0 to 1.0)
        sw_raw = param_data.get("GWETROOT", {}).get(key)
        if sw_raw is not None and float(sw_raw) != -999.0:
            v = float(sw_raw)
            record["soil_moisture"] = v if 0 <= v <= 1 else None

        return record

    except (KeyError, ValueError, TypeError) as exc:
        logger.warning(f"Parse error for PSGC {psgc} on {target_date}: {exc}")
        return None


# ── Batch fetch for all municipalities ───────────────────────────────────────
def fetch_all_municipalities(target_date: date) -> List[Dict]:
    """
    Fetch NASA POWER daily data for ALL Cagayan Valley municipalities.

    Args:
        target_date: The date to fetch (should be >= lag_days ago)

    Returns:
        List of valid records
    """
    municipalities = load_municipalities()
    results = []
    failed = []

    logger.info(
        f"Fetching NASA POWER daily data for {target_date} "
        f"({len(municipalities)} municipalities)..."
    )

    for i, mun in enumerate(municipalities):
        record = fetch_one_municipality(
            lat=mun["lat"],
            lon=mun["lon"],
            psgc=mun["psgc"],
            target_date=target_date,
        )
        if record:
            results.append(record)
            logger.debug(
                f"[{i+1}/{len(municipalities)}] {mun['name']}: "
                f"rain={record['rainfall_mm']} mm, "
                f"tmax={record['tmax_c']}°C"
            )
        else:
            failed.append(mun["psgc"])
            logger.warning(f"Failed: {mun['name']} ({mun['psgc']})")

        # Rate-limit: pause between requests
        time.sleep(REQUEST_DELAY)

    if failed:
        logger.warning(f"Failed municipalities ({len(failed)}): {failed}")

    return results


# ── Save output ───────────────────────────────────────────────────────────────
def save_daily_output(records: List[Dict], target_date: date) -> Path:
    """
    Save daily records to data/processed/daily/YYYY/MM/weather_YYYY-MM-DD.json
    and also update the rolling 'latest' file.
    """
    cfg = load_config()
    year_str = target_date.strftime("%Y")
    month_str = target_date.strftime("%m")

    # Versioned archive file
    archive_path = (
        PROJECT_ROOT
        / cfg["paths"]["processed_daily"]
        / year_str
        / month_str
        / f"weather_{target_date.isoformat()}.json"
    )

    # Latest file (overwritten daily — used by frontend)
    latest_path = (
        PROJECT_ROOT
        / cfg["paths"]["processed_daily"]
        / "weather_latest.json"
    )

    output = {
        "meta": {
            "generated_at": __import__("datetime").datetime.utcnow().isoformat(),
            "date": target_date.isoformat(),
            "source": "NASA POWER (Community: AG)",
            "parameters": PARAMETERS,
            "municipality_count": len(records),
            "lag_note": f"NASA POWER data has approximately {LAG_DAYS}-day lag",
        },
        "data": records,
    }

    save_json(output, archive_path)
    save_json(output, latest_path)

    logger.info(f"Saved {len(records)} records → {archive_path}")
    logger.info(f"Updated latest → {latest_path}")
    return archive_path


# ── Fetch historical range (backfill) ─────────────────────────────────────────
def fetch_range(start_date: date, end_date: date) -> None:
    """
    Backfill historical data for a date range.
    Useful for initial setup or filling gaps.

    Note: This is slow (~1.5s × municipalities × days).
    For bulk historical data, use the monthly endpoint instead.
    """
    from scripts.utils import date_range

    dates = date_range(start_date, end_date)
    logger.info(
        f"Backfilling {len(dates)} days "
        f"({start_date} → {end_date})..."
    )

    total_records = 0
    for d in dates:
        records = fetch_all_municipalities(d)
        if records:
            save_daily_output(records, d)
            log_etl_event(
                source="nasa_power_daily",
                run_date=d.isoformat(),
                records_fetched=len(load_municipalities()),
                records_valid=len(records),
                status="success",
            )
            total_records += len(records)
        else:
            log_etl_event(
                source="nasa_power_daily",
                run_date=d.isoformat(),
                records_fetched=len(load_municipalities()),
                records_valid=0,
                status="failed",
                message="No records returned",
            )
        time.sleep(2)  # Extra pause between dates

    logger.info(f"Backfill complete. Total records: {total_records}")


# ── Monthly batch fetch (more efficient for large ranges) ──────────────────
def fetch_monthly_batch(
    lat: float,
    lon: float,
    psgc: str,
    year: int,
    month: int,
) -> List[Dict]:
    """
    Fetch a full month of daily data in one API call (more efficient
    than day-by-day for backfill/climatology work).
    """
    import calendar
    last_day = calendar.monthrange(year, month)[1]
    start_str = f"{year}{month:02d}01"
    end_str = f"{year}{month:02d}{last_day:02d}"

    params = {
        "parameters": PARAMETERS,
        "community": COMMUNITY,
        "longitude": round(lon, 4),
        "latitude": round(lat, 4),
        "start": start_str,
        "end": end_str,
        "format": "JSON",
    }

    resp = retry_get(
        BASE_URL, params=params,
        retries=RETRY_ATTEMPTS,
        delay=2.0,
        timeout=TIMEOUT,
        logger=logger,
    )
    if resp is None:
        return []

    try:
        raw = resp.json()
        param_data = raw["properties"]["parameter"]
        records = []

        for day in range(1, last_day + 1):
            key = f"{year}{month:02d}{day:02d}"
            target_date = date(year, month, day)
            rec = {
                "psgc": psgc,
                "date": target_date.isoformat(),
                "source": "nasa_power",
                "rainfall_mm": validate_rainfall(
                    param_data.get("PRECTOTCORR", {}).get(key)
                ),
                "tmax_c": validate_temperature(
                    param_data.get("T2M_MAX", {}).get(key)
                ),
                "tmin_c": validate_temperature(
                    param_data.get("T2M_MIN", {}).get(key)
                ),
                "tmean_c": validate_temperature(
                    param_data.get("T2M", {}).get(key)
                ),
                "humidity_pct": validate_humidity(
                    param_data.get("RH2M", {}).get(key)
                ),
                "wind_speed_ms": validate_wind(
                    param_data.get("WS2M", {}).get(key)
                ),
            }
            records.append(rec)

        return records

    except Exception as exc:
        logger.error(f"Monthly batch parse error for PSGC {psgc}: {exc}")
        return []


# ── Main entry point ──────────────────────────────────────────────────────────
def run(target_date: Optional[date] = None) -> None:
    """
    Main function. If no date provided, fetches data for
    today minus LAG_DAYS (the most recent available date).
    """
    if target_date is None:
        # NASA POWER data is available ~5 days behind real-time
        target_date = today_pht() - timedelta(days=LAG_DAYS)

    logger.info(f"=== NASA POWER Daily Fetch: {target_date} ===")

    records = fetch_all_municipalities(target_date)

    if not records:
        logger.error("No records fetched. Aborting save.")
        log_etl_event(
            source="nasa_power_daily",
            run_date=target_date.isoformat(),
            records_fetched=0,
            records_valid=0,
            status="failed",
            message="No records returned from API",
        )
        sys.exit(1)

    save_daily_output(records, target_date)

    log_etl_event(
        source="nasa_power_daily",
        run_date=target_date.isoformat(),
        records_fetched=len(load_municipalities()),
        records_valid=len(records),
        status="success",
        message=f"Fetched {len(records)} municipality records",
    )
    logger.info("=== Fetch complete ===")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Fetch NASA POWER daily data for Cagayan Valley municipalities"
    )
    parser.add_argument(
        "--date", type=str, default=None,
        help="Target date YYYY-MM-DD (default: today minus lag days)"
    )
    parser.add_argument(
        "--backfill-start", type=str, default=None,
        help="Backfill start date YYYY-MM-DD"
    )
    parser.add_argument(
        "--backfill-end", type=str, default=None,
        help="Backfill end date YYYY-MM-DD"
    )
    args = parser.parse_args()

    if args.backfill_start and args.backfill_end:
        fetch_range(
            date.fromisoformat(args.backfill_start),
            date.fromisoformat(args.backfill_end),
        )
    else:
        target = date.fromisoformat(args.date) if args.date else None
        run(target)
