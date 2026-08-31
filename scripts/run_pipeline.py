"""
scripts/run_pipeline.py
Master pipeline orchestrator for APA-CIS daily data update.

Execution order:
  1. Fetch APA CIS and ACAP public regional data
  2. Sample UP NOAH public weather overlays
  3. Fetch NASA POWER daily fallback data (all municipalities)
  4. Ingest PAGASA data (PDF inbox + live scrape)
  5. Compute climate indicators (CDD, anomaly, heat stress, ETo, etc.)
  6. Compute Project NOAH municipal exposure analytics when local overlays exist
  7. Generate agricultural advisories (rule-based engine)
  8. Export GeoJSON map layers
  9. Log all results

Run this script via GitHub Actions or cron daily at 6 AM PHT.

Usage:
  python scripts/run_pipeline.py              # Normal daily run
  python scripts/run_pipeline.py --date 2026-06-01  # Specific date
  python scripts/run_pipeline.py --skip-fetch  # Indicators only (no API calls)

DA RFO 02 — APA-CIS Climate Information Service
"""

import sys
import time
import traceback
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.utils import (
    PROJECT_ROOT,
    load_config,
    log_etl_event,
    save_json,
    setup_logger,
    today_pht,
)

logger = setup_logger("pipeline", "pipeline.log")
cfg = load_config()


def run_step(name: str, fn, *args, **kwargs):
    """
    Run a pipeline step with error handling and timing.
    Returns (success: bool, result: any).
    """
    logger.info(f"--- STEP: {name} ---")
    start = time.time()
    try:
        result = fn(*args, **kwargs)
        elapsed = time.time() - start
        logger.info(f"✓ {name} completed in {elapsed:.1f}s")
        return True, result
    except Exception as exc:
        elapsed = time.time() - start
        logger.error(f"✗ {name} FAILED after {elapsed:.1f}s: {exc}")
        logger.error(traceback.format_exc())
        return False, None


def run_daily_pipeline(
    target_date: date = None,
    skip_fetch: bool = False,
    skip_chirps: bool = False,
    skip_pagasa: bool = False,
    skip_apa_cis: bool = False,
    skip_up_noah: bool = False,
    skip_acap: bool = False,
) -> dict:
    """
    Execute the full daily pipeline.

    Args:
        target_date: Override the default date (defaults to today - lag_days)
        skip_fetch: Skip NASA POWER fetch (use existing data)
        skip_pagasa: Skip PAGASA ingestor (use cached)

    Returns:
        Pipeline status report dict
    """
    start_total = time.time()
    run_date = today_pht().isoformat()

    report = {
        "run_date": run_date,
        "steps": {},
        "overall_status": "running",
    }

    logger.info("=" * 60)
    logger.info(f"APA-CIS DAILY PIPELINE — {run_date}")
    logger.info("=" * 60)

    # ── Step 1: NASA POWER fetch ──────────────────────────────────────────
    # Regional public apps are preferred by the indicator engine when records
    # match local municipalities; failures leave the fallback stack live.
    if not skip_fetch and not skip_apa_cis and cfg.get("apa_cis", {}).get("enabled", True):
        try:
            from scripts.fetch_apa_cis.cis_scraper import run as apa_cis_run
            success, _ = run_step("APA CIS Public Weather Scrape", apa_cis_run, target_date)
            report["steps"]["apa_cis"] = "success" if success else "warning"
        except Exception as exc:
            logger.error(f"APA CIS step error: {exc}")
            report["steps"]["apa_cis"] = "warning"
    else:
        logger.info("--- STEP: APA CIS Public Weather Scrape --- [SKIPPED]")
        report["steps"]["apa_cis"] = "skipped"

    if not skip_fetch and not skip_acap and cfg.get("acap", {}).get("enabled", True):
        try:
            from scripts.fetch_acap.acap_scraper import run as acap_run
            success, _ = run_step("ACAP Crop Calendar and 10-Day Scrape", acap_run)
            report["steps"]["acap"] = "success" if success else "warning"
        except Exception as exc:
            logger.error(f"ACAP step error: {exc}")
            report["steps"]["acap"] = "warning"
    else:
        logger.info("--- STEP: ACAP Crop Calendar and 10-Day Scrape --- [SKIPPED]")
        report["steps"]["acap"] = "skipped"

    if not skip_fetch and not skip_up_noah and cfg.get("up_noah", {}).get("enabled", True):
        try:
            from scripts.fetch_up_noah.noah_weather_sampler import run as up_noah_run
            success, _ = run_step("UP NOAH Weather Overlay Sampling", up_noah_run, target_date)
            report["steps"]["up_noah"] = "success" if success else "warning"
        except Exception as exc:
            logger.error(f"UP NOAH step error: {exc}")
            report["steps"]["up_noah"] = "warning"
    else:
        logger.info("--- STEP: UP NOAH Weather Overlay Sampling --- [SKIPPED]")
        report["steps"]["up_noah"] = "skipped"

    if not skip_fetch:
        try:
            from scripts.fetch_nasa_power.fetch_daily import run as nasa_run
            lag_days = cfg["nasa_power"]["lag_days"]
            fetch_date = target_date or (today_pht() - timedelta(days=lag_days))
            success, _ = run_step("NASA POWER Daily Fetch", nasa_run, fetch_date)
            report["steps"]["nasa_power"] = "success" if success else "failed"
        except Exception as exc:
            logger.error(f"NASA POWER step error: {exc}")
            report["steps"]["nasa_power"] = "error"
    else:
        logger.info("--- STEP: NASA POWER Daily Fetch --- [SKIPPED]")
        report["steps"]["nasa_power"] = "skipped"

    # CHIRPS rainfall fetch is additive. If centroid sampling is unavailable,
    # the script logs a warning and the indicator engine keeps NASA rainfall.
    if not skip_fetch and not skip_chirps:
        try:
            from scripts.fetch_chirps.fetch_daily import run as chirps_run
            chirps_date = target_date or (today_pht() - timedelta(days=2))
            success, _ = run_step("CHIRPS Daily Rainfall Fetch", chirps_run, chirps_date)
            report["steps"]["chirps"] = "success" if success else "warning"
        except Exception as exc:
            logger.error(f"CHIRPS step error: {exc}")
            report["steps"]["chirps"] = "warning"
    else:
        logger.info("--- STEP: CHIRPS Daily Rainfall Fetch --- [SKIPPED]")
        report["steps"]["chirps"] = "skipped"

    # ── Step 2: PAGASA ingestor ───────────────────────────────────────────
    if not skip_pagasa:
        try:
            from scripts.fetch_pagasa.pagasa_ingestor import run as pagasa_run
            success, _ = run_step("PAGASA Data Ingestor", pagasa_run)
            report["steps"]["pagasa"] = "success" if success else "failed"
        except Exception as exc:
            logger.error(f"PAGASA step error: {exc}")
            report["steps"]["pagasa"] = "error"
    else:
        logger.info("--- STEP: PAGASA Ingestor --- [SKIPPED]")
        report["steps"]["pagasa"] = "skipped"

    # ── Step 3: Indicator computation ────────────────────────────────────
    try:
        from scripts.indicators.compute_indicators import run as ind_run
        success, _ = run_step("Climate Indicator Engine", ind_run)
        report["steps"]["indicators"] = "success" if success else "failed"
    except Exception as exc:
        logger.error(f"Indicator engine error: {exc}")
        report["steps"]["indicators"] = "error"

    # ── Step 4: Static Project NOAH municipal exposure analytics ──────────
    try:
        from scripts.compute_noah_municipal_exposure import main as noah_exposure_run
        success, _ = run_step("Project NOAH Municipal Exposure Analytics", noah_exposure_run, [])
        report["steps"]["noah_exposure"] = "success" if success else "warning"
    except Exception as exc:
        logger.error(f"Project NOAH exposure analytics error: {exc}")
        report["steps"]["noah_exposure"] = "warning"

    # ── Step 5: Advisory generation ───────────────────────────────────────
    try:
        from scripts.advisories.advisory_engine import run as adv_run
        success, _ = run_step("Advisory Engine", adv_run)
        report["steps"]["advisories"] = "success" if success else "failed"
    except Exception as exc:
        logger.error(f"Advisory engine error: {exc}")
        report["steps"]["advisories"] = "error"

    # ── Pipeline complete ─────────────────────────────────────────────────
    total_elapsed = time.time() - start_total
    failed_steps = [k for k, v in report["steps"].items() if v in ("failed", "error")]

    report["overall_status"] = "failed" if failed_steps else "success"
    report["elapsed_seconds"] = round(total_elapsed, 1)
    report["failed_steps"] = failed_steps

    # Save run report
    run_log_path = PROJECT_ROOT / cfg["paths"]["logs"] / f"pipeline_run_{run_date}.json"
    save_json(report, run_log_path)

    if failed_steps:
        logger.warning(f"Pipeline completed with failures: {failed_steps}")
    else:
        logger.info(f"Pipeline completed successfully in {total_elapsed:.1f}s")

    logger.info("=" * 60)

    # Update pipeline status file (read by frontend)
    status_path = PROJECT_ROOT / "data" / "pipeline_status.json"
    save_json({
        "last_run": run_date,
        "status": report["overall_status"],
        "elapsed_seconds": report["elapsed_seconds"],
        "steps": report["steps"],
        "data_as_of": run_date,
        "forecast_as_of": run_date,
        "fallback_observation_as_of": (
            today_pht() - timedelta(days=cfg["nasa_power"]["lag_days"])
        ).isoformat(),
    }, status_path)

    log_etl_event(
        source="daily_pipeline",
        run_date=run_date,
        records_fetched=0,
        records_valid=0,
        status=report["overall_status"],
        message=f"Steps: {report['steps']}",
    )

    return report


# ── CLI Entry Point ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="APA-CIS Daily Pipeline — DA RFO 02 Climate Information Service"
    )
    parser.add_argument("--date", type=str, default=None,
                        help="Override fetch date (YYYY-MM-DD)")
    parser.add_argument("--skip-fetch", action="store_true",
                        help="Skip NASA POWER fetch (indicators only)")
    parser.add_argument("--skip-pagasa", action="store_true",
                        help="Skip PAGASA ingestor")
    parser.add_argument("--skip-chirps", action="store_true",
                        help="Skip CHIRPS rainfall fetch")
    parser.add_argument("--skip-apa-cis", action="store_true",
                        help="Skip APA CIS public weather scrape")
    parser.add_argument("--skip-up-noah", action="store_true",
                        help="Skip UP NOAH weather overlay sampling")
    parser.add_argument("--skip-acap", action="store_true",
                        help="Skip ACAP crop calendar and 10-day scrape")

    args = parser.parse_args()

    target = date.fromisoformat(args.date) if args.date else None
    result = run_daily_pipeline(
        target_date=target,
        skip_fetch=args.skip_fetch,
        skip_chirps=args.skip_chirps,
        skip_pagasa=args.skip_pagasa,
        skip_apa_cis=args.skip_apa_cis,
        skip_up_noah=args.skip_up_noah,
        skip_acap=args.skip_acap,
    )

    sys.exit(0 if result["overall_status"] == "success" else 1)
