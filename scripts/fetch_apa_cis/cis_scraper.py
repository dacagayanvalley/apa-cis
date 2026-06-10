"""
Fetch same-day municipal weather layers from the APA CIS public app.

The CIS site exposes public JSON used by its map. We ingest the Region 2
municipal daily layers first, then let the indicator engine prefer these
official/regional values over NASA POWER fallback values.
"""

import re
import sys
import time
import unicodedata
from datetime import datetime
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
    validate_rainfall,
    validate_temperature,
    validate_wind,
)

logger = setup_logger(__name__, "fetch_apa_cis.log")
cfg = load_config()


def _norm_name(value: str) -> str:
    value = (value or "").replace("Ã±", "ñ").replace("Ã‘", "Ñ")
    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower()
    text = re.sub(r"\bcity of\b", " ", text)
    text = re.sub(r"\bcity\b", " ", text)
    text = re.sub(r"\bmunicipality of\b", " ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _extract_app_dates(html: str) -> Dict[str, Optional[str]]:
    def pick(name: str) -> Optional[str]:
        match = re.search(rf'{name}\s*=\s*"([^"]+)"', html)
        return match.group(1) if match else None

    return {
        "date_now": pick("dateNow") or today_pht().isoformat(),
        "forecast_start": pick("fStart"),
        "forecast_end": pick("fEnd"),
    }


def _load_cis_meta(base_url: str, retries: int, timeout: int) -> Dict[str, Dict]:
    url = f"{base_url}/tiles/municipalities/meta"
    resp = retry_get(url, retries=retries, delay=2, timeout=timeout, logger=logger)
    if not resp:
        return {}
    data = resp.json()
    return data if isinstance(data, dict) else {}


def _build_psgc_matcher(cis_meta: Dict[str, Dict]) -> Dict[str, str]:
    local = load_municipalities()
    local_by_name = {
        (m["province"].lower(), _norm_name(m["name"])): m["psgc"]
        for m in local
    }
    matcher = {}
    region_code = cfg["apa_cis"]["region_code"]
    for muncode, item in cis_meta.items():
        if item.get("regcode") != region_code:
            continue
        key = ((item.get("province") or "").lower(), _norm_name(item.get("municipality", "")))
        psgc = local_by_name.get(key)
        if psgc:
            matcher[muncode] = psgc
    return matcher


def _fetch_daily_layer(base_url: str, layer_type: str, run_date: str) -> Dict:
    settings = cfg["apa_cis"]
    resp = retry_get(
        f"{base_url}/daily/data",
        params={"date": run_date, "type": layer_type, "region": settings["region_code"]},
        retries=settings.get("retry_attempts", 3),
        delay=2,
        timeout=settings.get("timeout_seconds", 45),
        logger=logger,
    )
    if not resp:
        return {}
    payload = resp.json()
    return payload if isinstance(payload, dict) else {}


def _clean_value(field: str, raw_value):
    if field == "rainfall_mm":
        value = validate_rainfall(raw_value)
    elif field == "tmax_c":
        value = validate_temperature(raw_value)
    elif field == "wind_speed_ms":
        value = validate_wind(raw_value)
    else:
        value = raw_value
    return round(value, 2) if isinstance(value, float) else value


def run(target_date=None) -> Dict:
    settings = cfg.get("apa_cis", {})
    base_url = settings.get("base_url", "https://cis.apa.da.gov.ph").rstrip("/")
    retries = settings.get("retry_attempts", 3)
    timeout = settings.get("timeout_seconds", 45)

    app_resp = retry_get(settings.get("app_url", f"{base_url}/cis"), retries=retries, delay=2, timeout=timeout, logger=logger)
    app_dates = _extract_app_dates(app_resp.text if app_resp else "")
    run_date = target_date.isoformat() if target_date else app_dates["date_now"]

    cis_meta = _load_cis_meta(base_url, retries, timeout)
    matcher = _build_psgc_matcher(cis_meta)
    records: Dict[str, Dict] = {}
    raw_layers = {}

    for layer_type, out_field in settings.get("daily_types", {}).items():
        payload = _fetch_daily_layer(base_url, layer_type, run_date)
        raw_layers[layer_type] = payload
        layer_data = payload.get("data", {}) if isinstance(payload, dict) else {}
        if isinstance(layer_data, list):
            layer_data = {}

        for muncode, row in layer_data.items():
            psgc = matcher.get(muncode)
            if not psgc:
                continue
            meta = cis_meta.get(muncode, {})
            rec = records.setdefault(psgc, {
                "psgc": psgc,
                "cis_muncode": muncode,
                "municipality": meta.get("municipality"),
                "province": meta.get("province"),
                "date": run_date,
                "source": "apa_cis",
                "wind_direction": row.get("wd") if isinstance(row, dict) else None,
            })
            if isinstance(row, dict):
                rec[out_field] = _clean_value(out_field, row.get("value"))
                if row.get("wd"):
                    rec["wind_direction"] = row.get("wd")
        time.sleep(settings.get("request_delay_seconds", 0.5))

    output = {
        "meta": {
            "generated_at": datetime.utcnow().isoformat(),
            "source_url": settings.get("app_url", f"{base_url}/cis"),
            "api_base_url": base_url,
            "date": run_date,
            "forecast_start": app_dates.get("forecast_start"),
            "forecast_end": app_dates.get("forecast_end"),
            "region_code": settings.get("region_code"),
            "matched_municipalities": len(records),
            "available_layers": list(raw_layers.keys()),
        },
        "data": list(records.values()),
        "raw_layer_summary": {
            name: {
                "field": layer.get("field"),
                "unit": layer.get("unit"),
                "record_count": len(layer.get("data", {}) or {}),
            }
            for name, layer in raw_layers.items()
            if isinstance(layer, dict)
        },
    }

    out_dir = PROJECT_ROOT / cfg["paths"]["raw_apa_cis"]
    save_json(output, out_dir / f"apa_cis_{run_date}.json")
    save_json(output, out_dir / "apa_cis_current.json")
    log_etl_event(
        source="apa_cis_scraper",
        run_date=run_date,
        records_fetched=sum(v.get("record_count", 0) for v in output["raw_layer_summary"].values()),
        records_valid=len(records),
        status="success" if records else "warning",
        message=f"APA CIS matched {len(records)} Region 2 municipalities",
    )
    logger.info("APA CIS scraper saved %s matched records for %s", len(records), run_date)
    return output


if __name__ == "__main__":
    run()
