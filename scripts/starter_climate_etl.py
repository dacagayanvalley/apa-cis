"""
Starter climate ETL snippets for APA-CIS.

This file is intentionally small and readable. It complements the production
pipeline in scripts/run_pipeline.py and can be used as a reference when adding
new data sources such as CHIRPS, PAGASA manual products, or Supabase exports.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterable

import requests


NASA_POWER_DAILY_URL = "https://power.larc.nasa.gov/api/temporal/daily/point"


@dataclass
class Municipality:
    psgc: str
    name: str
    province: str
    lat: float
    lon: float
    irrigation_status: str = "rainfed"


def fetch_nasa_power_daily(mun: Municipality, target_date: date) -> dict:
    """Fetch one day of NASA POWER agroclimatic data for a municipality."""
    ymd = target_date.strftime("%Y%m%d")
    params = {
        "parameters": "PRECTOTCORR,T2M_MAX,T2M_MIN,T2M,RH2M,WS2M,ALLSKY_SFC_SW_DWN,GWETROOT",
        "community": "AG",
        "longitude": round(mun.lon, 4),
        "latitude": round(mun.lat, 4),
        "start": ymd,
        "end": ymd,
        "format": "JSON",
    }
    response = requests.get(NASA_POWER_DAILY_URL, params=params, timeout=45)
    response.raise_for_status()
    payload = response.json()
    values = payload["properties"]["parameter"]

    def get(parameter: str):
        value = values.get(parameter, {}).get(ymd)
        if value in (None, -999, -999.0):
            return None
        return float(value)

    return {
        "psgc": mun.psgc,
        "municipality": mun.name,
        "province": mun.province,
        "date": target_date.isoformat(),
        "source": "nasa_power",
        "rainfall_mm": get("PRECTOTCORR"),
        "tmax_c": get("T2M_MAX"),
        "tmin_c": get("T2M_MIN"),
        "tmean_c": get("T2M"),
        "humidity_pct": get("RH2M"),
        "wind_speed_ms": get("WS2M"),
        "solar_mj": get("ALLSKY_SFC_SW_DWN"),
        "soil_moisture": get("GWETROOT"),
    }


def chirps_daily_download_url(target_date: date) -> str:
    """
    Return the standard CHIRPS daily GeoTIFF URL pattern.

    A production implementation should download this raster, clip it to Region 2,
    zonally aggregate by municipality polygon, then write rainfall_mm by PSGC.
    """
    year = target_date.year
    ymd = target_date.strftime("%Y.%m.%d")
    return (
        "https://data.chc.ucsb.edu/products/CHIRPS-2.0/global_daily/tifs/p05/"
        f"{year}/chirps-v2.0.{ymd}.tif.gz"
    )


def load_pagasa_manual_entry(path: Path) -> dict:
    """
    Load a reviewed PAGASA product captured manually or from a parsed PDF.

    Expected keys:
    product_type, issue_date, valid_start, valid_end, affected_areas,
    headline, body, source_url
    """
    with path.open("r", encoding="utf-8") as file:
        entry = json.load(file)

    required = ["product_type", "issue_date", "valid_start", "valid_end", "headline", "body"]
    missing = [key for key in required if not entry.get(key)]
    if missing:
        raise ValueError(f"PAGASA entry missing required keys: {missing}")
    return entry


def percent_of_normal(observed_mm: float | None, normal_mm: float | None) -> float | None:
    if observed_mm is None or normal_mm in (None, 0):
        return None
    return round((observed_mm / normal_mm) * 100.0, 1)


def rainfall_anomaly(observed_mm: float | None, normal_mm: float | None) -> dict:
    pct = percent_of_normal(observed_mm, normal_mm)
    if pct is None:
        return {"anomaly_mm": None, "pct_of_normal": None, "class": "unknown"}

    anomaly = round(observed_mm - normal_mm, 1)
    if pct < 60:
        cls = "far_below"
    elif pct < 80:
        cls = "below"
    elif pct <= 120:
        cls = "near_normal"
    elif pct <= 150:
        cls = "above"
    else:
        cls = "far_above"

    return {"anomaly_mm": anomaly, "pct_of_normal": pct, "class": cls}


def consecutive_dry_days(records: Iterable[dict], dry_threshold_mm: float = 1.0) -> int:
    """Compute current dry-day streak from records ordered oldest to newest."""
    streak = 0
    for record in reversed(list(records)):
        rain = record.get("rainfall_mm")
        if rain is None:
            continue
        if rain < dry_threshold_mm:
            streak += 1
        else:
            break
    return streak


def consecutive_wet_days(records: Iterable[dict], wet_threshold_mm: float = 1.0) -> int:
    """Compute current wet-day streak from records ordered oldest to newest."""
    streak = 0
    for record in reversed(list(records)):
        rain = record.get("rainfall_mm")
        if rain is None:
            continue
        if rain >= wet_threshold_mm:
            streak += 1
        else:
            break
    return streak


def heat_stress_class(tmax_c: float | None, humidity_pct: float | None) -> str:
    """
    Simple heat stress class for starter use.

    The production pipeline uses a WBGT approximation. This fallback is useful
    when only max temperature and humidity are available.
    """
    if tmax_c is None:
        return "unknown"
    if tmax_c >= 38 or (tmax_c >= 36 and (humidity_pct or 0) >= 75):
        return "danger"
    if tmax_c >= 35:
        return "high"
    if tmax_c >= 32:
        return "moderate"
    return "low"


def crop_stage_risk(cdd: int, rain_7d_mm: float, tmax_c: float, crop_stage: str) -> dict:
    """Transparent starter crop-stage risk score."""
    drought = 0
    flood = 0
    heat = 0

    drought_limit = 5 if crop_stage in {"reproductive", "tasseling", "flowering"} else 8
    if cdd >= drought_limit * 3:
        drought = 5
    elif cdd >= drought_limit * 2:
        drought = 4
    elif cdd >= drought_limit:
        drought = 3

    flood_limit = 40 if crop_stage in {"ripening", "harvesting"} else 80
    if rain_7d_mm >= flood_limit * 2:
        flood = 5
    elif rain_7d_mm >= flood_limit:
        flood = 3

    heat_limit = 35 if crop_stage in {"reproductive", "tasseling", "flowering"} else 38
    if tmax_c >= heat_limit + 3:
        heat = 4
    elif tmax_c >= heat_limit:
        heat = 3

    score = min(5, max(drought, flood) + 0.3 * heat)
    risk_class = "critical" if score >= 4 else "high" if score >= 3 else "moderate" if score >= 2 else "low"
    return {
        "risk_score": round(score, 1),
        "risk_class": risk_class,
        "components": {"drought": drought, "flood": flood, "heat": heat},
    }


def generate_advisory(record: dict, indicators: dict) -> list[dict]:
    """Generate starter advisories with explainable trigger values."""
    advisories = []
    rain = record.get("rainfall_mm") or 0
    cdd = indicators.get("cdd") or 0
    heat = indicators.get("heat_class")

    if rain >= 100:
        advisories.append({
            "rule_id": "RAIN_EXTREME_24H",
            "severity": "danger",
            "operation": "all_fieldwork",
            "trigger_values": {"rainfall_24h_mm": rain, "threshold_mm": 100},
            "message": "Suspend field operations, secure harvest, and coordinate with LGU DRRM and MAO.",
        })
    if cdd >= 14:
        advisories.append({
            "rule_id": "DRY_SPELL_WARNING",
            "severity": "warning" if cdd < 21 else "danger",
            "operation": "irrigation",
            "trigger_values": {"cdd": cdd, "warning_days": 14, "critical_days": 21},
            "message": "Prioritize irrigation for rainfed and reproductive-stage crops.",
        })
    if heat in {"high", "danger"}:
        advisories.append({
            "rule_id": "HEAT_STRESS_FIELDWORK",
            "severity": "warning" if heat == "high" else "danger",
            "operation": "fieldwork",
            "trigger_values": {"heat_class": heat},
            "message": "Shift field work to early morning or late afternoon and provide water and shade.",
        })

    return advisories


def export_geojson(records: Iterable[dict], output_path: Path) -> None:
    """Export point GeoJSON for quick Leaflet preview."""
    features = []
    for record in records:
        lon = record.get("lon")
        lat = record.get("lat")
        if lon is None or lat is None:
            continue
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": {key: value for key, value in record.items() if key not in {"lat", "lon"}},
        })

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as file:
        json.dump({"type": "FeatureCollection", "features": features}, file, indent=2)


def export_csv(records: Iterable[dict], output_path: Path) -> None:
    """Export records to CSV for LGU/DA review."""
    rows = list(records)
    if not rows:
        return
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=sorted(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
