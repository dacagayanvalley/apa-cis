"""
Fetch ACAP Cagayan Valley crop-calendar metadata and 10-day PAGASA products.

ACAP is a static Next.js app backed by public Firestore collections. This
script stores a normalized snapshot for downstream advisory context.
"""

import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.utils import (
    PROJECT_ROOT,
    load_config,
    log_etl_event,
    retry_get,
    save_json,
    setup_logger,
    today_pht,
)

logger = setup_logger(__name__, "fetch_acap.log")
cfg = load_config()


def _decode_firestore(value: Dict[str, Any]) -> Any:
    if "stringValue" in value:
        return value["stringValue"]
    if "integerValue" in value:
        return int(value["integerValue"])
    if "doubleValue" in value:
        return float(value["doubleValue"])
    if "booleanValue" in value:
        return bool(value["booleanValue"])
    if "timestampValue" in value:
        return value["timestampValue"]
    if "nullValue" in value:
        return None
    if "arrayValue" in value:
        return [_decode_firestore(v) for v in value["arrayValue"].get("values", [])]
    if "mapValue" in value:
        return {k: _decode_firestore(v) for k, v in value["mapValue"].get("fields", {}).items()}
    return value


def _decode_document(doc: Dict[str, Any]) -> Dict[str, Any]:
    fields = doc.get("fields", {})
    decoded = {k: _decode_firestore(v) for k, v in fields.items()}
    decoded["_document_name"] = doc.get("name")
    decoded["_create_time"] = doc.get("createTime")
    decoded["_update_time"] = doc.get("updateTime")
    return decoded


def _fetch_json(url: str) -> Dict[str, Any]:
    resp = retry_get(url, retries=2, delay=2, timeout=cfg["acap"].get("timeout_seconds", 45), logger=logger)
    if not resp:
        return {}
    return resp.json()


def _extract_next_data(html: str) -> Dict[str, Any]:
    match = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html)
    if not match:
        return {}
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError:
        return {}


def _calendar_municipalities(provinces_municipalities: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows = []
    for province in provinces_municipalities or []:
        province_name = province.get("label")
        for item in province.get("municipalities", []) or []:
            if item.get("iscalendar"):
                rows.append({
                    "province": province_name,
                    "municipality": item.get("label"),
                    "acap_id": item.get("id"),
                    "has_crop_calendar": True,
                })
    return rows


def _firestore_collection(path: str) -> List[Dict[str, Any]]:
    project_id = cfg["acap"]["firestore_project_id"]
    root = f"https://firestore.googleapis.com/v1/projects/{project_id}/databases/(default)/documents"
    payload = _fetch_json(f"{root}/{path.strip('/')}")
    return [_decode_document(doc) for doc in payload.get("documents", [])]


def run() -> Dict[str, Any]:
    settings = cfg.get("acap", {})
    base_url = settings.get("base_url", "https://acap-cagayanvalley.github.io").rstrip("/")
    home_resp = retry_get(base_url + "/", retries=2, delay=2, timeout=settings.get("timeout_seconds", 45), logger=logger)
    home_data = _extract_next_data(home_resp.text if home_resp else "")
    page_props = home_data.get("props", {}).get("pageProps", {}) if isinstance(home_data, dict) else {}

    route_json = {
        "cropping_calendar_v2": _fetch_json(f"{base_url}/_next/data/nFO9rH3j0SI5jQH_FNcFf/cropping-calendar-v2.json"),
        "weather_services": _fetch_json(f"{base_url}/_next/data/nFO9rH3j0SI5jQH_FNcFf/weather-services.json"),
        "weather_bulletins": _fetch_json(f"{base_url}/_next/data/nFO9rH3j0SI5jQH_FNcFf/bulletins/weather.json"),
    }

    region_doc = settings.get("region_document", "cagayan_valley")
    ten_day = _firestore_collection(f"weather_forecasts/{region_doc}/ten_day")
    seasonal = _firestore_collection(f"weather_forecasts/{region_doc}/seasonal")
    common_tenday = _firestore_collection(f"weather_forecasts/{region_doc}/seasonal_tenday")

    provinces_municipalities = page_props.get("provincesMunicipalities", [])
    calendar_rows = _calendar_municipalities(provinces_municipalities)

    output = {
        "meta": {
            "generated_at": datetime.utcnow().isoformat(),
            "source_url": base_url,
            "firestore_project_id": settings.get("firestore_project_id"),
            "snapshot_date": today_pht().isoformat(),
            "ten_day_province_count": len(ten_day),
            "crop_calendar_municipality_count": len(calendar_rows),
        },
        "villages": page_props.get("villages", []),
        "provinces_municipalities": provinces_municipalities,
        "crop_calendar_municipalities": calendar_rows,
        "ten_day_forecast": ten_day,
        "seasonal_forecast": seasonal,
        "common_tenday": common_tenday,
        "route_metadata": route_json,
    }

    out_dir = PROJECT_ROOT / cfg["paths"]["raw_acap"]
    run_date = today_pht().isoformat()
    save_json(output, out_dir / f"acap_{run_date}.json")
    save_json(output, out_dir / "acap_current.json")
    log_etl_event(
        source="acap_scraper",
        run_date=run_date,
        records_fetched=len(ten_day) + len(seasonal) + len(calendar_rows),
        records_valid=len(ten_day) + len(calendar_rows),
        status="success" if ten_day or calendar_rows else "warning",
        message=f"ACAP ten-day provinces={len(ten_day)}, crop-calendar municipalities={len(calendar_rows)}",
    )
    logger.info("ACAP scraper saved %s ten-day province records", len(ten_day))
    return output


if __name__ == "__main__":
    run()
