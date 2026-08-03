"""
scripts/fetch_pagasa/update_severe_weather.py
Lightweight PAGASA severe-weather refresh for APA-CIS.

Runs on the 3-hour PAGASA Severe Weather Bulletin cadence and updates
frontend-consumed PAGASA JSON without running the full climate pipeline.
"""

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.fetch_pagasa.pagasa_ingestor import fetch_live_pagasa_data
from scripts.utils import PROJECT_ROOT, load_config, load_json, log_etl_event, save_json, setup_logger, today_pht

logger = setup_logger("severe_weather_update", "severe_weather_update.log")
cfg = load_config()


def run() -> dict:
    run_date = today_pht().isoformat()
    logger.info("=== PAGASA Severe Weather Refresh ===")

    pagasa_data = fetch_live_pagasa_data()
    typhoon = pagasa_data.get("typhoon") or {}
    raw_pagasa = PROJECT_ROOT / cfg["paths"]["raw_pagasa"]

    latest_path = raw_pagasa / "pagasa_current.json"
    dated_path = raw_pagasa / f"pagasa_current_{run_date}.json"
    status_path = PROJECT_ROOT / "data" / "pipeline_status.json"

    save_json(pagasa_data, latest_path)
    save_json(pagasa_data, dated_path)

    status = load_json(status_path) or {}
    status["severe_weather_last_checked"] = datetime.now(timezone.utc).isoformat()
    status["severe_weather_as_of"] = typhoon.get("as_of") or run_date
    status["severe_weather_active"] = bool(typhoon.get("active"))
    status["severe_weather_region2_affected"] = bool(typhoon.get("region2_affected"))
    status["severe_weather_system"] = " ".join(
        part for part in [typhoon.get("disturbance_type"), typhoon.get("name")] if part
    )
    status["severe_weather_bulletin_number"] = typhoon.get("bulletin_number") or ""
    save_json(status, status_path)

    log_etl_event(
        source="pagasa_severe_weather",
        run_date=run_date,
        records_fetched=1,
        records_valid=1 if typhoon else 0,
        status="success",
        message=(
            f"active={bool(typhoon.get('active'))}; "
            f"region2={bool(typhoon.get('region2_affected'))}; "
            f"system={status['severe_weather_system'] or 'none'}"
        ),
    )

    logger.info(
        "Severe weather active=%s region2=%s system=%s bulletin=%s",
        bool(typhoon.get("active")),
        bool(typhoon.get("region2_affected")),
        status["severe_weather_system"] or "none",
        typhoon.get("bulletin_number") or "",
    )
    logger.info("=== PAGASA Severe Weather Refresh Complete ===")
    return pagasa_data


if __name__ == "__main__":
    run()