"""
scripts/fetch_pagasa/update_severe_weather.py
Lightweight PAGASA severe-weather refresh for APA-CIS.

Runs only from the scheduled automation every 30 minutes and updates the
frontend-consumed severe-weather fields without running the full climate pipeline
or refreshing unrelated PAGASA products.
"""

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.fetch_pagasa.pagasa_ingestor import (
    PAGASA_URLS,
    parse_severe_weather_bulletin,
    scrape_pagasa_page,
)
from scripts.utils import PROJECT_ROOT, load_config, load_json, log_etl_event, save_json, setup_logger, today_pht

logger = setup_logger("severe_weather_update", "severe_weather_update.log")
cfg = load_config()
AUTO_FETCH_INTERVAL_MINUTES = 30
SCHEDULE_EVENT_NAME = "schedule"


def _running_from_schedule() -> bool:
    """Return True when invoked by the GitHub Actions cron schedule."""
    return os.getenv("GITHUB_EVENT_NAME") == SCHEDULE_EVENT_NAME


def _load_current_pagasa(latest_path: Path) -> dict:
    current = load_json(latest_path)
    if isinstance(current, dict):
        return current
    return {
        "as_of": today_pht().isoformat(),
        "source_urls": {
            "typhoon": PAGASA_URLS["typhoon"],
        },
        "enso": {},
        "farm_weather": {},
        "typhoon": {},
        "scrape_status": {},
    }


def _fetch_severe_weather_only(fetched_at: str) -> tuple[dict, str]:
    html_text = scrape_pagasa_page(PAGASA_URLS["typhoon"], "severe_weather_bulletin")
    if not html_text:
        return {
            "active": False,
            "source_url": PAGASA_URLS["typhoon"],
            "summary": "Could not fetch PAGASA Severe Weather Bulletin page.",
            "as_of": today_pht().isoformat(),
            "fetched_at": fetched_at,
            "fetched_at_utc": fetched_at,
            "auto_fetch_interval_minutes": AUTO_FETCH_INTERVAL_MINUTES,
        }, "failed"

    typhoon = parse_severe_weather_bulletin(html_text)
    typhoon["fetched_at"] = fetched_at
    typhoon["fetched_at_utc"] = fetched_at
    typhoon["auto_fetch_interval_minutes"] = AUTO_FETCH_INTERVAL_MINUTES
    return typhoon, "success"


def run() -> dict:
    if os.getenv("GITHUB_ACTIONS") == "true" and not _running_from_schedule():
        raise RuntimeError("PAGASA severe-weather refresh is restricted to scheduled runs only.")

    run_date = today_pht().isoformat()
    fetched_at = datetime.now(timezone.utc).isoformat()
    logger.info("=== PAGASA Severe Weather Auto Fetch ===")

    raw_pagasa = PROJECT_ROOT / cfg["paths"]["raw_pagasa"]
    latest_path = raw_pagasa / "pagasa_current.json"
    dated_path = raw_pagasa / f"pagasa_current_{run_date}.json"
    status_path = PROJECT_ROOT / "data" / "pipeline_status.json"

    pagasa_data = _load_current_pagasa(latest_path)
    typhoon, scrape_status = _fetch_severe_weather_only(fetched_at)

    pagasa_data["as_of"] = run_date
    pagasa_data["fetched_at"] = fetched_at
    pagasa_data["fetched_at_utc"] = fetched_at
    pagasa_data.setdefault("source_urls", {})["typhoon"] = PAGASA_URLS["typhoon"]
    pagasa_data.setdefault("scrape_status", {})["typhoon"] = scrape_status
    pagasa_data["typhoon"] = typhoon
    pagasa_data["severe_weather_auto_fetch"] = {
        "mode": "scheduled_only",
        "interval_minutes": AUTO_FETCH_INTERVAL_MINUTES,
        "last_checked_utc": fetched_at,
    }

    save_json(pagasa_data, latest_path)
    save_json(pagasa_data, dated_path)

    status = load_json(status_path) or {}
    status["severe_weather_last_checked"] = fetched_at
    status["severe_weather_as_of"] = typhoon.get("as_of") or run_date
    status["severe_weather_active"] = bool(typhoon.get("active"))
    status["severe_weather_region2_affected"] = bool(typhoon.get("region2_affected"))
    status["severe_weather_system"] = " ".join(
        part for part in [typhoon.get("disturbance_type"), typhoon.get("name")] if part
    )
    status["severe_weather_bulletin_number"] = typhoon.get("bulletin_number") or ""
    status["severe_weather_auto_fetch_interval_minutes"] = AUTO_FETCH_INTERVAL_MINUTES
    status["severe_weather_auto_fetch_mode"] = "scheduled_only"
    save_json(status, status_path)

    log_etl_event(
        source="pagasa_severe_weather",
        run_date=run_date,
        records_fetched=1 if scrape_status == "success" else 0,
        records_valid=1 if typhoon else 0,
        status=scrape_status,
        message=(
            f"scheduled_only=true; interval_minutes={AUTO_FETCH_INTERVAL_MINUTES}; "
            f"active={bool(typhoon.get('active'))}; "
            f"region2={bool(typhoon.get('region2_affected'))}; "
            f"system={status['severe_weather_system'] or 'none'}"
        ),
    )

    logger.info(
        "Severe weather auto fetch interval=%smin active=%s region2=%s system=%s bulletin=%s",
        AUTO_FETCH_INTERVAL_MINUTES,
        bool(typhoon.get("active")),
        bool(typhoon.get("region2_affected")),
        status["severe_weather_system"] or "none",
        typhoon.get("bulletin_number") or "",
    )
    logger.info("=== PAGASA Severe Weather Auto Fetch Complete ===")
    return pagasa_data


if __name__ == "__main__":
    run()
