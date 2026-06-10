"""
scripts/advisories/weekly_summary.py
Generates a weekly climate and advisory summary for DA RFO 02.
Runs every Monday via GitHub Actions.

Output:
  - data/advisories/weekly/weekly_summary_YYYY-MM-DD.json
  - data/advisories/weekly/weekly_summary_latest.json
  - data/advisories/weekly/weekly_bulletin_YYYY-MM-DD.txt

DA RFO 02 — APA-CIS Climate Information Service
"""

import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.utils import (
    PROJECT_ROOT, load_config, load_json, save_json,
    setup_logger, today_pht, PROVINCES, log_etl_event,
)

logger = setup_logger(__name__, "weekly_summary.log")
cfg = load_config()


def build_weekly_summary() -> dict:
    """
    Aggregate last 7 days of advisory and indicator data
    into a weekly provincial summary report.
    """
    ref_date = today_pht()
    week_start = ref_date - timedelta(days=6)

    summary = {
        "meta": {
            "generated_at": __import__("datetime").datetime.utcnow().isoformat(),
            "week_start": week_start.isoformat(),
            "week_end": ref_date.isoformat(),
            "report_type": "weekly_climate_summary",
        },
        "regional_highlights": [],
        "province_summaries": {},
        "advisory_counts": {},
        "trend": {},
    }

    # Aggregate daily advisory files for the past 7 days
    adv_path = PROJECT_ROOT / cfg["paths"]["advisories_daily"]
    weekly_advisory_data = []

    for i in range(7):
        d = week_start + timedelta(days=i)
        day_file = adv_path / f"advisories_{d.isoformat()}.json"
        day_data = load_json(day_file)
        if day_data:
            weekly_advisory_data.append({"date": d.isoformat(), "data": day_data})

    if not weekly_advisory_data:
        logger.warning("No daily advisory files found for the past 7 days.")
        # Use latest available
        latest = load_json(adv_path / "advisories_latest.json")
        if latest:
            weekly_advisory_data = [{"date": ref_date.isoformat(), "data": latest}]

    # Province-level stats
    for province in PROVINCES:
        # Collect advisory counts across the week
        danger_days = 0
        warning_days = 0
        affected_muns = set()

        for day_entry in weekly_advisory_data:
            day_advisories = day_entry["data"].get("advisories", {})
            for psgc, adv in day_advisories.items():
                if adv.get("province") == province:
                    sev = adv.get("highest_severity", "none")
                    if sev == "danger": danger_days += 1
                    elif sev == "warning": warning_days += 1
                    affected_muns.add(psgc)

        summary["province_summaries"][province] = {
            "days_with_danger": danger_days,
            "days_with_warning": warning_days,
            "unique_municipalities_affected": len(affected_muns),
            "week_status": (
                "critical" if danger_days >= 3 else
                "elevated" if warning_days >= 3 else
                "moderate" if affected_muns else
                "normal"
            ),
        }

    # Use latest indicators for trend indicators
    latest_ind = load_json(
        PROJECT_ROOT / cfg["paths"]["indicators"] / "indicators_latest.json"
    )
    if latest_ind:
        rows = list(latest_ind.get("data", {}).values())
        drought_count = sum(1 for r in rows
                           if r.get("indicators", {}).get("drought_class") in ("watch", "warning", "critical"))
        heat_count    = sum(1 for r in rows
                           if r.get("indicators", {}).get("heat_stress", {}).get("heat_class") in ("high", "danger"))

        summary["regional_highlights"] = [
            f"{drought_count} municipalities under dry spell watch/warning/critical",
            f"{heat_count} municipalities with high or dangerous heat stress",
            f"Week covered {len(weekly_advisory_data)} of 7 possible days of advisory data",
        ]

        summary["trend"] = {
            "drought_municipalities": drought_count,
            "heat_risk_municipalities": heat_count,
            "data_days_available": len(weekly_advisory_data),
        }

    return summary


def generate_weekly_bulletin(summary: dict) -> str:
    """Generate plain-text weekly bulletin for DA communications."""
    meta = summary["meta"]
    lines = [
        "DA RFO 02 — WEEKLY AGRICULTURAL CLIMATE SUMMARY",
        f"Period: {meta['week_start']} to {meta['week_end']}",
        f"Issued by: DA RFO 02 RAED / APA-CIS",
        "=" * 56,
        "",
        "REGIONAL HIGHLIGHTS:",
    ]
    for h in summary.get("regional_highlights", []):
        lines.append(f"  • {h}")

    lines.extend(["", "PROVINCIAL WEEKLY STATUS:"])
    for province, pdata in summary.get("province_summaries", {}).items():
        status = pdata["week_status"].upper()
        lines.append(
            f"  {province}: {status} | "
            f"{pdata['unique_municipalities_affected']} municipalities affected | "
            f"Danger-days: {pdata['days_with_danger']} | "
            f"Warning-days: {pdata['days_with_warning']}"
        )

    lines.extend([
        "",
        "This summary is auto-generated by the APA-CIS pipeline.",
        "For full municipal-level details, access the CIS portal.",
        f"DA RFO 02 Hotline: (078) 844-1228 / (078) 396-0558",
        f"\nEnd of Weekly Summary — {meta['week_end']}",
    ])
    return "\n".join(lines)


def run():
    logger.info("=== Weekly Summary Generator ===")
    summary = build_weekly_summary()

    ref_date = today_pht()
    weekly_path = PROJECT_ROOT / cfg["paths"]["advisories_weekly"]
    weekly_path.mkdir(parents=True, exist_ok=True)

    save_json(summary, weekly_path / f"weekly_summary_{ref_date.isoformat()}.json")
    save_json(summary, weekly_path / "weekly_summary_latest.json")

    bulletin = generate_weekly_bulletin(summary)
    (weekly_path / f"weekly_bulletin_{ref_date.isoformat()}.txt").write_text(bulletin)
    (weekly_path / "weekly_bulletin_latest.txt").write_text(bulletin)

    logger.info(f"Weekly summary saved → {weekly_path}")
    log_etl_event(
        source="weekly_summary", run_date=ref_date.isoformat(),
        records_fetched=7, records_valid=summary["trend"].get("data_days_available", 0),
        status="success", message=f"Week {summary['meta']['week_start']} – {summary['meta']['week_end']}",
    )


if __name__ == "__main__":
    run()
