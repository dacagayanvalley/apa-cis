"""
scripts/indicators/compute_indicators.py
Core climate indicator engine for APA-CIS.

Computes all agricultural climate indicators from NASA POWER daily data
and the 1991-2020 climatology baseline.

Indicators computed:
  - Consecutive Dry Days (CDD) and drought watch class
  - Consecutive Wet Days (CWD)
  - Rainfall anomaly and percent of normal
  - Heat stress index (WBGT approximation)
  - Reference evapotranspiration (FAO-56 Penman-Monteith, simplified)
  - Irrigation demand proxy (ETo - rainfall)
  - Field workability index
  - Crop-stage risk score
  - Municipal climate risk composite score

DA RFO 02 — APA-CIS Climate Information Service
"""

import math
import re
import sys
import unicodedata
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.utils import (
    PROJECT_ROOT,
    load_config,
    load_json,
    load_municipalities,
    log_etl_event,
    save_json,
    setup_logger,
    today_pht,
)

logger = setup_logger(__name__, "compute_indicators.log")
cfg = load_config()
thresholds = cfg["thresholds"]


# ═══════════════════════════════════════════════════════════════════════════════
# 1. DATA LOADING HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def load_recent_daily(psgc: str, n_days: int = 30) -> List[Dict]:
    """
    Load last n_days of daily records for a single municipality.
    Reads from data/processed/daily/ archive.
    """
    records = []
    base = PROJECT_ROOT / cfg["paths"]["processed_daily"]
    ref_date = today_pht()

    for i in range(n_days):
        d = ref_date - timedelta(days=i)
        year_str = d.strftime("%Y")
        month_str = d.strftime("%m")
        path = base / year_str / month_str / f"weather_{d.isoformat()}.json"

        data = load_json(path)
        if data and "data" in data:
            for rec in data["data"]:
                if rec.get("psgc") == psgc:
                    records.append(rec)
                    break  # Found our municipality

    return sorted(records, key=lambda x: x["date"])


def load_latest_all_municipalities() -> Dict[str, Dict]:
    """
    Load the most recent daily record for every municipality.
    Returns dict keyed by PSGC.
    """
    latest_path = (
        PROJECT_ROOT / cfg["paths"]["processed_daily"] / "weather_latest.json"
    )
    data = load_json(latest_path)
    if not data:
        return {}
    return {rec["psgc"]: rec for rec in data.get("data", [])}


def load_latest_chirps_rainfall() -> Dict[str, Dict]:
    """Load latest CHIRPS municipal rainfall records, keyed by PSGC."""
    latest_path = (
        PROJECT_ROOT / cfg["paths"]["processed_daily"] / "chirps_rainfall_latest.json"
    )
    data = load_json(latest_path)
    if not data:
        return {}
    return {rec["psgc"]: rec for rec in data.get("data", [])}


def load_climatology() -> Dict[str, Dict]:
    """Load flattened climatology: {psgc: {month_str: {normals}}}"""
    clim_path = PROJECT_ROOT / "config" / "climatology_flat.json"
    data = load_json(clim_path)
    return data or {}


def load_pagasa_current() -> Dict:
    """Load latest reviewed/semi-automated PAGASA product bundle."""
    pagasa_path = PROJECT_ROOT / cfg["paths"]["raw_pagasa"] / "pagasa_current.json"
    return load_json(pagasa_path) or {}


def load_latest_apa_cis() -> Dict[str, Dict]:
    """Load latest APA CIS weather records, keyed by local PSGC."""
    path = PROJECT_ROOT / cfg["paths"].get("raw_apa_cis", "data/raw/apa_cis") / "apa_cis_current.json"
    data = load_json(path) or {}
    return {rec["psgc"]: rec for rec in data.get("data", []) if rec.get("psgc")}


def load_latest_up_noah() -> Dict[str, Dict]:
    """Load latest UP NOAH municipal weather records, keyed by local PSGC."""
    path = PROJECT_ROOT / cfg["paths"].get("raw_up_noah", "data/raw/up_noah") / "up_noah_current.json"
    data = load_json(path) or {}
    if not cfg.get("up_noah", {}).get("enabled", True):
        return {}
    return {rec["psgc"]: rec for rec in data.get("data", []) if rec.get("psgc")}


def load_acap_current() -> Dict:
    """Load latest ACAP crop-calendar and 10-day weather snapshot."""
    path = PROJECT_ROOT / cfg["paths"].get("raw_acap", "data/raw/acap") / "acap_current.json"
    return load_json(path) or {}


def load_acap_cropping_calendars() -> Dict:
    """Load normalized ACAP rice/corn cropping calendars for advisory anchoring."""
    path = PROJECT_ROOT / cfg["paths"].get("reference", "data/reference") / "acap_cropping_calendars.json"
    return load_json(path) or {}


def _norm_name(value: str) -> str:
    value = (value or "").replace("Ã±", "ñ").replace("Ã‘", "Ñ")
    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower()
    text = re.sub(r"\bcity of\b", " ", text)
    text = re.sub(r"\bcity\b", " ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _calendar_key_part(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", _norm_name(value))


def _current_calendar_period(ref_date: date) -> str:
    suffix = "15" if ref_date.day <= 15 else "30"
    return f"{ref_date.month:02d}_{suffix}_CAL"


def _calendar_stage_code(raw_stage: Optional[str]) -> Optional[str]:
    if not raw_stage:
        return None
    return re.sub(r"_\d+$", "", str(raw_stage))


def _risk_stage_from_calendar(raw_stage: Optional[str], crop_key: str) -> Optional[str]:
    stage = _calendar_stage_code(raw_stage)
    if not stage:
        return None
    if crop_key == "rice":
        return {
            "prep": "land_prep",
            "seed": "seedbed",
            "plant": "transplanting",
            "veg": "vegetative",
            "vegat": "vegetative",
            "vegpi": "reproductive",
            "repro": "reproductive",
            "mat": "ripening",
        }.get(stage, stage)
    if crop_key == "corn":
        return {
            "prep": "land_prep",
            "seed": "seedbed",
            "plant": "vegetative",
            "vegleaf": "vegetative",
            "vegtass": "tasseling",
            "repro": "grain_fill",
            "mat": "maturation",
        }.get(stage, stage)
    return stage


def _risk_crop_from_calendar(crop_key: str, irrigation_status: str) -> str:
    if crop_key == "rice":
        return "rice_irrigated" if irrigation_status == "irrigated" else "rice_rainfed"
    if crop_key == "corn":
        return "corn_yellow"
    return crop_key


def _stage_label(stage: Optional[str]) -> str:
    labels = {
        "prep": "Preparation",
        "seed": "Seedling",
        "plant": "Planting / Newly planted",
        "veg": "Vegetative",
        "vegat": "Vegetative / Active tillering",
        "vegpi": "Reproductive / Panicle initiation",
        "vegleaf": "Vegetative / Leaf development",
        "vegtass": "Vegetative / Tasseling",
        "repro": "Reproductive",
        "mat": "Maturing",
    }
    return labels.get(stage or "", (stage or "No active stage").replace("_", " ").title())


def _calendar_entry_for_municipality(mun: Dict, calendars: Dict) -> Optional[Dict]:
    municipal_key = (
        f"{_calendar_key_part(mun.get('province'))}|"
        f"{_calendar_key_part(mun.get('name') or mun.get('municipality'))}"
    )
    return (calendars.get("municipalities") or {}).get(municipal_key)


def _calendar_context_for_municipality(mun: Dict, calendars: Dict, ref_date: date) -> Dict:
    """Return current rice/corn stages from the ACAP municipal crop calendar."""
    entry = _calendar_entry_for_municipality(mun, calendars)
    period_key = _current_calendar_period(ref_date)
    period_meta = next(
        (period for period in calendars.get("periods", []) if period.get("key") == period_key),
        {"key": period_key, "label": period_key},
    )
    context = {
        "available": bool(entry),
        "source": "ACAP rice/corn cropping calendar workbooks",
        "period_key": period_key,
        "period_label": period_meta.get("label", period_key),
        "municipality": entry.get("municipality") if entry else mun.get("name") or mun.get("municipality"),
        "province": entry.get("province") if entry else mun.get("province"),
        "current_stages": [],
    }
    if not entry:
        context["note"] = "No municipal ACAP rice/corn crop-calendar row loaded; seasonal default used."
        return context

    irrigation_status = mun.get("irrigation_status", "rainfed")
    for crop_key, seasons in (entry.get("crops") or {}).items():
        for season in seasons:
            raw_stage = (season.get("periods") or {}).get(period_key)
            calendar_stage = _calendar_stage_code(raw_stage)
            if not calendar_stage:
                continue
            risk_crop = _risk_crop_from_calendar(crop_key, irrigation_status)
            risk_stage = _risk_stage_from_calendar(raw_stage, crop_key)
            context["current_stages"].append({
                "crop": crop_key,
                "crop_label": crop_key.title(),
                "season": season.get("season"),
                "calendar_stage": calendar_stage,
                "calendar_stage_label": _stage_label(calendar_stage),
                "risk_crop": risk_crop,
                "risk_stage": risk_stage,
                "raw_stage": raw_stage,
            })

    if context["current_stages"]:
        context["note"] = "Current rice/corn stages are anchored to the municipal ACAP crop calendar."
    else:
        context["note"] = "Municipal ACAP calendar found, but no rice/corn stage is active in the current half-month period."
    return context


def _crop_stage_risk_from_calendar(
    calendar_context: Dict,
    cdd: int,
    cwd: int,
    rainfall_7d: Optional[float],
    tmax_c: Optional[float],
    humidity_pct: Optional[float],
    irrigation_status: str,
) -> Dict:
    candidates = []
    for stage in calendar_context.get("current_stages", []):
        risk = compute_crop_stage_risk(
            cdd=cdd, cwd=cwd, rainfall_7d=rainfall_7d,
            tmax_c=tmax_c, humidity_pct=humidity_pct,
            crop=stage["risk_crop"], crop_stage=stage["risk_stage"],
            irrigation_status=irrigation_status,
        )
        risk.update({
            "calendar_crop": stage["crop"],
            "calendar_crop_label": stage["crop_label"],
            "calendar_stage": stage["calendar_stage"],
            "calendar_stage_label": stage["calendar_stage_label"],
            "calendar_season": stage["season"],
            "calendar_period": calendar_context.get("period_label"),
        })
        candidates.append(risk)

    if not candidates:
        return {}

    primary = dict(max(candidates, key=lambda item: item.get("risk_score", 0)))
    primary["calendar_anchored"] = True
    primary["calendar_context_note"] = calendar_context.get("note")
    primary["candidate_count"] = len(candidates)
    primary["all_current_calendar_risks"] = [dict(candidate) for candidate in candidates]
    return primary


# ═══════════════════════════════════════════════════════════════════════════════
# 2. INDIVIDUAL INDICATOR FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════════

def compute_cdd(records: List[Dict]) -> Tuple[int, str]:
    """
    Consecutive Dry Days (current streak) and drought watch class.

    A dry day is defined as rainfall < 1.0 mm (WMO standard).

    Args:
        records: List of daily records, oldest first

    Returns:
        (current_cdd, drought_class)
        drought_class: "none" | "watch" | "warning" | "critical"
    """
    dry_threshold = thresholds["rainfall"]["dry_day_mm"]
    watch_days = thresholds["dry_spell"]["watch_days"]
    warning_days = thresholds["dry_spell"]["warning_days"]
    critical_days = thresholds["dry_spell"]["critical_days"]

    cdd = 0
    # Walk backwards from most recent
    for rec in reversed(records):
        rain = rec.get("rainfall_mm")
        if rain is None:
            continue  # Skip missing values
        if rain < dry_threshold:
            cdd += 1
        else:
            break  # Streak ends

    if cdd >= critical_days:
        drought_class = "critical"
    elif cdd >= warning_days:
        drought_class = "warning"
    elif cdd >= watch_days:
        drought_class = "watch"
    else:
        drought_class = "none"

    return cdd, drought_class


def compute_cwd(records: List[Dict]) -> int:
    """
    Consecutive Wet Days (current streak, >= 1 mm/day).
    """
    wet_threshold = thresholds["rainfall"]["dry_day_mm"]
    cwd = 0
    for rec in reversed(records):
        rain = rec.get("rainfall_mm")
        if rain is None:
            continue
        if rain >= wet_threshold:
            cwd += 1
        else:
            break
    return cwd


def compute_accumulated_rainfall(
    records: List[Dict],
    days: int = 7
) -> Optional[float]:
    """Sum rainfall over the last `days` days."""
    recent = records[-days:] if len(records) >= days else records
    vals = [r["rainfall_mm"] for r in recent if r.get("rainfall_mm") is not None]
    if not vals:
        return None
    return round(sum(vals), 2)


def compute_rainfall_anomaly(
    observed_mm: float,
    normal_mm: float,
) -> Dict:
    """
    Compute rainfall anomaly, percent of normal, and classification.

    Args:
        observed_mm: Observed monthly (or period) rainfall in mm
        normal_mm: 1991-2020 normal for the same period

    Returns:
        dict with anomaly_mm, pct_of_normal, anomaly_class
    """
    t = thresholds["rainfall_anomaly"]

    if not normal_mm or normal_mm <= 0:
        return {"anomaly_mm": None, "pct_of_normal": None, "anomaly_class": "unknown"}

    anomaly_mm = round(observed_mm - normal_mm, 2)
    pct = round((observed_mm / normal_mm) * 100, 1)

    if pct < t["far_below_pct"]:
        cls = "far_below"
    elif pct < t["below_pct"]:
        cls = "below"
    elif pct <= t["near_normal_max_pct"]:
        cls = "near_normal"
    elif pct <= t["far_above_pct"]:
        cls = "above"
    else:
        cls = "far_above"

    return {
        "anomaly_mm": anomaly_mm,
        "pct_of_normal": pct,
        "anomaly_class": cls,
    }


def compute_heat_stress(tmax_c: float, humidity_pct: float) -> Dict:
    """
    Heat stress classification using a simplified WBGT (Wet Bulb Globe
    Temperature) approximation.

    Reference: Liljegren et al. (2008) simplified outdoor WBGT

    Args:
        tmax_c: Daily maximum temperature (°C)
        humidity_pct: Relative humidity (%)

    Returns:
        dict with wbgt_approx, heat_class, heat_label, color
    """
    t = thresholds["heat_stress"]

    # Simplified outdoor WBGT approximation
    # Based on Bernard & Barrow (1989) and ISO 7243 simplified formula
    # WBGT_outdoor ≈ 0.7 * Tw + 0.2 * Tg + 0.1 * Tdb
    # Simplified to 2-factor using Tmax and RH:
    # Tw (wet bulb) approximated via Stull (2011):
    #   Tw = Tmax * atan(0.151977 * (RH+8.313659)^0.5) + atan(Tmax+RH)
    #        - atan(RH-1.676331) + 0.00391838*(RH^1.5)*atan(0.023101*RH) - 4.686035
    rh = humidity_pct
    tw = (
        tmax_c * math.atan(0.151977 * (rh + 8.313659) ** 0.5)
        + math.atan(tmax_c + rh)
        - math.atan(rh - 1.676331)
        + 0.00391838 * (rh ** 1.5) * math.atan(0.023101 * rh)
        - 4.686035
    )
    # Globe temp approximation: Tg ≈ Tmax + 2 (outdoor sunny conditions)
    tg = tmax_c + 2.0
    # WBGT outdoor (simplified 3-component, no solar input)
    wbgt = 0.7 * tw + 0.2 * tg + 0.1 * tmax_c
    wbgt = round(wbgt, 1)

    if wbgt < t["low_wbgt"]:
        cls, label, color = "low", "Low Heat Stress", "#4CAF50"
    elif wbgt < t["moderate_wbgt"]:
        cls, label, color = "moderate", "Moderate Heat Stress", "#FF9800"
    elif wbgt < t["high_wbgt"]:
        cls, label, color = "high", "High Heat Stress", "#FF5722"
    else:
        cls, label, color = "danger", "Dangerous Heat", "#B71C1C"

    return {
        "wbgt_approx": wbgt,
        "heat_class": cls,
        "heat_label": label,
        "heat_color": color,
        "advisory_restrict_fieldwork": cls in ("high", "danger"),
        "advisory_livestock_risk": cls in ("high", "danger"),
    }


def compute_eto(
    tmax_c: float,
    tmin_c: float,
    humidity_pct: float,
    wind_ms: float,
    solar_mj: float,
    altitude_m: float = 50.0,
) -> Optional[float]:
    """
    FAO-56 Penman-Monteith Reference Evapotranspiration (simplified).

    Returns ETo in mm/day, or None if inputs are invalid.

    Reference: Allen et al. (1998) FAO Irrigation and Drainage Paper No. 56
    """
    try:
        tmean = (tmax_c + tmin_c) / 2.0

        # Slope of saturation vapor pressure curve (kPa/°C)
        delta = (
            4098
            * (0.6108 * math.exp(17.27 * tmean / (tmean + 237.3)))
            / (tmean + 237.3) ** 2
        )

        # Atmospheric pressure (kPa)
        pressure = 101.3 * ((293.0 - 0.0065 * altitude_m) / 293.0) ** 5.26

        # Psychrometric constant (kPa/°C)
        gamma = 0.000665 * pressure

        # Saturation vapor pressure (kPa)
        e_sat_max = 0.6108 * math.exp(17.27 * tmax_c / (tmax_c + 237.3))
        e_sat_min = 0.6108 * math.exp(17.27 * tmin_c / (tmin_c + 237.3))
        e_sat = (e_sat_max + e_sat_min) / 2.0

        # Actual vapor pressure
        e_act = e_sat * (humidity_pct / 100.0)

        # Net radiation approximation
        # Rns (shortwave): 0.77 albedo factor for reference crop
        Rns = (1 - 0.23) * solar_mj

        # Rnl (longwave, simplified)
        sigma = 4.903e-9  # MJ/(m²·day·K⁴)
        Rnl = (
            sigma
            * ((tmax_c + 273.16) ** 4 + (tmin_c + 273.16) ** 4)
            / 2.0
            * (0.34 - 0.14 * math.sqrt(e_act))
            * (1.35 * (solar_mj / (0.75 * solar_mj + 0.001)) - 0.35)
        )
        Rn = Rns - Rnl

        # Soil heat flux (G) = 0 for daily
        G = 0.0

        # ETo (mm/day)
        numerator = (
            0.408 * delta * (Rn - G)
            + gamma * (900.0 / (tmean + 273.0)) * wind_ms * (e_sat - e_act)
        )
        denominator = delta + gamma * (1.0 + 0.34 * wind_ms)

        eto = numerator / denominator
        return round(max(0.0, eto), 2)

    except (ZeroDivisionError, ValueError, TypeError):
        return None


def compute_field_workability(
    rain_24h: Optional[float],
    rain_48h: Optional[float],
    cdd: int,
    wind_ms: Optional[float] = None,
    humidity_pct: Optional[float] = None,
) -> Dict:
    """
    Field workability index for scheduling agriculture operations.

    Returns status for: land prep, transplanting, fertilizer, spraying,
    irrigation, harvesting.
    """
    t = thresholds["field_workability"]
    dry_alert_cdd = t["dry_alert_cdd"]

    rain_24h = rain_24h or 0.0
    rain_48h = rain_48h or 0.0

    # Overall workability
    if rain_24h >= t["not_workable_24h"] or rain_48h >= 80:
        overall = "not_workable"
        overall_label = "Not Workable — Heavy rain, waterlogged fields"
        color = "#B71C1C"
    elif rain_24h >= t["high_risk_24h"]:
        overall = "high_risk"
        overall_label = "High Risk — Defer heavy operations"
        color = "#FF5722"
    elif rain_24h >= t["caution_24h"]:
        overall = "caution"
        overall_label = "Caution — Light work only"
        color = "#FF9800"
    elif cdd >= dry_alert_cdd:
        overall = "drought_caution"
        overall_label = "Drought Caution — Irrigate first before field operations"
        color = "#FFC107"
    else:
        overall = "workable"
        overall_label = "Workable — Safe for field operations"
        color = "#4CAF50"

    # Operation-specific assessments
    def safe(condition: bool) -> str:
        return "safe" if condition else "defer"

    spraying_safe = rain_24h < 5 and rain_48h < 15
    if wind_ms is not None:
        spraying_safe = spraying_safe and wind_ms < 5

    drying_safe = rain_24h < 5
    if humidity_pct is not None:
        drying_safe = drying_safe and humidity_pct < 85

    ops = {
        "land_preparation": safe(rain_24h < 20 and cdd < 21),
        "transplanting": safe(rain_24h < 25 and cdd < 14),
        "fertilizer_application": safe(rain_24h < 10 and rain_48h < 25),
        "spraying": safe(spraying_safe),
        "irrigation": safe(cdd >= 5 or rain_24h < 3),
        "harvesting": safe(rain_24h < 10 and rain_48h < 20),
        "drying": safe(drying_safe),
        "pest_monitoring": safe(rain_24h < 30),
    }

    return {
        "overall_class": overall,
        "overall_label": overall_label,
        "color": color,
        "rain_24h_mm": rain_24h,
        "rain_48h_mm": rain_48h,
        "cdd": cdd,
        "operations": ops,
        "wind_speed_ms": wind_ms,
        "humidity_pct": humidity_pct,
    }


def compute_postharvest_drying_risk(
    rainfall_mm: Optional[float],
    humidity_pct: Optional[float],
    wind_ms: Optional[float],
    solar_mj: Optional[float],
) -> Dict:
    """Assess grain drying suitability from rain, humidity, wind, and solar."""
    rainfall_mm = rainfall_mm or 0.0
    humidity_pct = humidity_pct if humidity_pct is not None else 80.0
    wind_ms = wind_ms if wind_ms is not None else 1.0
    solar_mj = solar_mj if solar_mj is not None else 10.0

    score = 0
    reasons = []
    if rainfall_mm >= 5:
        score += 3
        reasons.append("rainfall >= 5 mm")
    if humidity_pct >= 85:
        score += 2
        reasons.append("humidity >= 85%")
    if solar_mj < 12:
        score += 1
        reasons.append("low solar radiation")
    if wind_ms < 1:
        score += 1
        reasons.append("low wind")

    if score >= 5:
        cls = "unsuitable"
    elif score >= 3:
        cls = "high_risk"
    elif score >= 1:
        cls = "caution"
    else:
        cls = "suitable"

    return {
        "drying_class": cls,
        "risk_score": min(score, 6),
        "reasons": reasons,
        "recommend_mechanical_drying": cls in ("high_risk", "unsuitable"),
    }


def compute_irrigation_demand(
    eto_mm: Optional[float],
    rainfall_mm: Optional[float],
    irrigation_status: str = "rainfed",
) -> Dict:
    """
    Irrigation demand proxy = ETo - Rainfall (when positive).

    Args:
        eto_mm: Reference ETo (mm/day)
        rainfall_mm: Daily rainfall (mm)
        irrigation_status: 'irrigated' | 'partial' | 'rainfed'

    Returns:
        demand_mm, demand_class, priority
    """
    if eto_mm is None or rainfall_mm is None:
        return {"demand_mm": None, "demand_class": "unknown", "priority": "low"}

    demand = max(0.0, eto_mm - rainfall_mm)
    demand = round(demand, 2)

    if demand <= 0:
        cls = "none"
    elif demand < 2:
        cls = "low"
    elif demand < 5:
        cls = "moderate"
    elif demand < 8:
        cls = "high"
    else:
        cls = "critical"

    # Priority higher for rainfed areas
    priority_map = {
        "rainfed": {"none": "low", "low": "medium", "moderate": "high",
                    "high": "critical", "critical": "critical"},
        "partial": {"none": "low", "low": "low", "moderate": "medium",
                    "high": "high", "critical": "high"},
        "irrigated": {"none": "low", "low": "low", "moderate": "low",
                     "high": "medium", "critical": "high"},
    }

    priority = priority_map.get(irrigation_status, priority_map["rainfed"]).get(cls, "low")

    return {
        "demand_mm": demand,
        "demand_class": cls,
        "priority": priority,
    }


def compute_crop_stage_risk(
    cdd: int,
    cwd: int,
    rainfall_7d: Optional[float],
    tmax_c: Optional[float],
    humidity_pct: Optional[float],
    crop: str = "rice_rainfed",
    crop_stage: str = "vegetative",
    irrigation_status: str = "rainfed",
) -> Dict:
    """
    Crop-stage climate risk score (0–5 scale).

    Risk sources:
    - Drought risk (CDD relative to crop water requirement)
    - Flood/excess water risk (7-day rainfall, CWD)
    - Heat stress during sensitive stages
    - Humidity-driven disease risk

    Returns:
        risk_score (0–5), risk_class, risk_components
    """
    drought_score = 0.0
    flood_score = 0.0
    heat_score = 0.0
    disease_score = 0.0

    # ── Drought risk by crop stage ────────────────────────────────────────
    drought_thresholds = {
        "rice_irrigated": {"vegetative": 7, "reproductive": 5, "ripening": 10},
        "rice_rainfed": {"vegetative": 5, "reproductive": 4, "ripening": 8},
        "corn_yellow": {"vegetative": 7, "tasseling": 4, "grain_fill": 5},
        "corn_white": {"vegetative": 7, "tasseling": 4, "grain_fill": 5},
        "hvcc": {"vegetative": 5, "flowering": 4, "maturation": 7},
    }

    sensitive_stage = drought_thresholds.get(crop, {}).get(crop_stage, 7)

    if irrigation_status == "rainfed":
        if cdd >= sensitive_stage * 2:
            drought_score = 5.0
        elif cdd >= sensitive_stage * 1.5:
            drought_score = 4.0
        elif cdd >= sensitive_stage:
            drought_score = 3.0
        elif cdd >= sensitive_stage * 0.5:
            drought_score = 1.5
    else:
        # Irrigated areas: lower drought risk
        drought_score = min(drought_score * 0.3, 2.0)

    # ── Flood risk by crop stage ──────────────────────────────────────────
    if rainfall_7d is not None:
        flood_thresholds = {
            "land_prep": 150,       # Very tolerant
            "seedbed": 80,
            "transplanting": 60,
            "vegetative": 100,
            "reproductive": 60,     # Very sensitive
            "ripening": 40,
            "harvesting": 30,       # Critical — harvest loss
        }
        flood_limit = flood_thresholds.get(crop_stage, 80)

        if rainfall_7d >= flood_limit * 2:
            flood_score = 5.0
        elif rainfall_7d >= flood_limit * 1.5:
            flood_score = 4.0
        elif rainfall_7d >= flood_limit:
            flood_score = 3.0
        elif rainfall_7d >= flood_limit * 0.5:
            flood_score = 1.5

    # ── Heat stress by crop stage ─────────────────────────────────────────
    if tmax_c is not None:
        heat_sensitive_stages = {"reproductive", "tasseling", "grain_fill", "flowering"}
        threshold = 35.0 if crop_stage in heat_sensitive_stages else 38.0

        if tmax_c >= threshold + 3:
            heat_score = 4.0
        elif tmax_c >= threshold:
            heat_score = 3.0
        elif tmax_c >= threshold - 2:
            heat_score = 1.5

    # ── Disease risk (high humidity) ──────────────────────────────────────
    if humidity_pct is not None:
        if humidity_pct >= 90 and cwd >= 5:
            disease_score = 3.0
        elif humidity_pct >= 80 and cwd >= 3:
            disease_score = 2.0
        elif humidity_pct >= 75:
            disease_score = 1.0

    # ── Composite score ───────────────────────────────────────────────────
    composite = round(
        max(drought_score, flood_score)  # Dominant hazard
        + 0.3 * heat_score
        + 0.2 * disease_score,
        2
    )
    composite = min(composite, 5.0)

    if composite >= 4:
        risk_class = "critical"
        risk_color = "#B71C1C"
    elif composite >= 3:
        risk_class = "high"
        risk_color = "#FF5722"
    elif composite >= 2:
        risk_class = "moderate"
        risk_color = "#FF9800"
    elif composite >= 1:
        risk_class = "low"
        risk_color = "#FFC107"
    else:
        risk_class = "minimal"
        risk_color = "#4CAF50"

    return {
        "risk_score": composite,
        "risk_class": risk_class,
        "risk_color": risk_color,
        "components": {
            "drought": round(drought_score, 2),
            "flood": round(flood_score, 2),
            "heat": round(heat_score, 2),
            "disease": round(disease_score, 2),
        },
        "crop": crop,
        "crop_stage": crop_stage,
    }


def compute_municipal_risk_score(indicators: Dict, mun: Dict) -> float:
    """
    Composite municipal climate risk ranking score (0–100).
    Used for DA intervention prioritization.
    """
    score = 0.0

    # Drought component (0-40 points)
    cdd = indicators.get("cdd", 0)
    drought_map = {"none": 0, "watch": 15, "warning": 30, "critical": 40}
    score += drought_map.get(indicators.get("drought_class", "none"), 0)

    # Flood component (0-25 points)
    rain_7d = indicators.get("rainfall_7d_mm") or 0
    if rain_7d >= 200:
        score += 25
    elif rain_7d >= 100:
        score += 15
    elif rain_7d >= 50:
        score += 8

    # Heat stress component (0-20 points)
    heat_map = {"low": 0, "moderate": 5, "high": 15, "danger": 20}
    score += heat_map.get(indicators.get("heat_class", "low"), 0)

    # Irrigation vulnerability (0-15 points)
    irr_map = {"rainfed": 15, "partial": 8, "irrigated": 2}
    score += irr_map.get(mun.get("irrigation_status", "rainfed"), 8)

    return round(min(score, 100), 1)


# ═══════════════════════════════════════════════════════════════════════════════
# 3. MAIN COMPUTATION PIPELINE
# ═══════════════════════════════════════════════════════════════════════════════

def compute_all_indicators() -> Dict:
    """
    Compute all indicators for all municipalities.
    Reads from the daily archive and outputs to data/processed/indicators/.
    """
    municipalities = load_municipalities()
    climatology = load_climatology()
    chirps_rainfall = load_latest_chirps_rainfall()
    pagasa_current = load_pagasa_current()
    apa_cis_current = load_latest_apa_cis()
    up_noah_current = load_latest_up_noah()
    acap_current = load_acap_current()
    acap_cropping_calendars = load_acap_cropping_calendars()
    ref_date = today_pht()
    current_month = str(ref_date.month)

    results = {}
    logger.info(f"Computing indicators for {len(municipalities)} municipalities...")

    for mun in municipalities:
        psgc = mun["psgc"]

        # Load 30 days of daily records for this municipality
        records = load_recent_daily(psgc, n_days=30)
        if not records:
            logger.warning(f"No records for {mun['name']} ({psgc})")
            continue

        latest = records[-1]  # Most recent day
        cis_rec = apa_cis_current.get(psgc)
        noah_rec = up_noah_current.get(psgc)
        chirps_rec = chirps_rainfall.get(psgc) if cfg["chirps"].get("use_for_rainfall_if_available", True) else None
        chirps_is_current = chirps_rec and chirps_rec.get("date") == latest.get("date")
        chirps_rain = chirps_rec.get("rainfall_mm") if chirps_is_current else None
        cis_rain = cis_rec.get("rainfall_mm") if cis_rec else None
        noah_rain = noah_rec.get("rainfall_24h_mm") if noah_rec else None
        rain_24h = (
            cis_rain if cis_rain is not None
            else noah_rain if noah_rain is not None
            else chirps_rain if chirps_rain is not None
            else latest.get("rainfall_mm")
        )
        if cis_rain is not None:
            rainfall_source = "apa_cis"
        elif noah_rain is not None:
            rainfall_source = "up_noah"
        elif chirps_rain is not None:
            rainfall_source = "chirps"
        else:
            rainfall_source = latest.get("source", "nasa_power")
        rain_48h = compute_accumulated_rainfall(records, days=2)
        rain_7d = compute_accumulated_rainfall(records, days=7)
        rain_30d = compute_accumulated_rainfall(records, days=30)
        noah_tmax = noah_rec.get("tmax_c") if noah_rec else None
        tmax = (
            cis_rec.get("tmax_c") if cis_rec and cis_rec.get("tmax_c") is not None
            else noah_tmax if noah_tmax is not None
            else latest.get("tmax_c")
        )
        noah_heat_index = noah_rec.get("heat_index_c") if noah_rec else None
        tmin = latest.get("tmin_c")
        tmean = latest.get("tmean_c")
        humidity = latest.get("humidity_pct")
        wind = (
            cis_rec.get("wind_speed_ms") if cis_rec and cis_rec.get("wind_speed_ms") is not None
            else noah_rec.get("wind_speed_ms") if noah_rec and noah_rec.get("wind_speed_ms") is not None
            else latest.get("wind_speed_ms")
        )
        solar = latest.get("solar_mj")
        weather_source = "apa_cis" if cis_rec else ("up_noah" if noah_rec else latest.get("source", "nasa_power"))

        # Consecutive days
        cdd, drought_class = compute_cdd(records)
        cwd = compute_cwd(records)

        # Monthly anomaly vs climatology
        clim = climatology.get(psgc, {}).get(current_month, {})
        normal_monthly = clim.get("rainfall_mm")
        anomaly = compute_rainfall_anomaly(rain_30d or 0, normal_monthly) if normal_monthly else {}

        # Heat stress
        heat = compute_heat_stress(tmax, humidity) if (tmax and humidity) else {}

        # ETo
        eto = None
        if all(v is not None for v in [tmax, tmin, humidity, wind, solar]):
            eto = compute_eto(
                tmax_c=tmax, tmin_c=tmin, humidity_pct=humidity,
                wind_ms=wind, solar_mj=solar,
                altitude_m=mun.get("elevation_m", 50),
            )

        # Irrigation demand
        irr_demand = compute_irrigation_demand(
            eto, rain_24h, mun.get("irrigation_status", "rainfed")
        )

        # Field workability
        workability = compute_field_workability(rain_24h, rain_48h, cdd, wind, humidity)
        drying_risk = compute_postharvest_drying_risk(rain_24h, humidity, wind, solar)

        # Crop-stage risk anchored to ACAP municipal rice/corn calendars when available.
        month = ref_date.month
        default_crop = "rice_rainfed" if month in [6, 7, 8, 9, 10] else "corn_yellow"
        default_stage = "vegetative"
        calendar_context = _calendar_context_for_municipality(
            mun, acap_cropping_calendars, ref_date
        )
        crop_risk = _crop_stage_risk_from_calendar(
            calendar_context=calendar_context,
            cdd=cdd, cwd=cwd, rainfall_7d=rain_7d,
            tmax_c=tmax, humidity_pct=humidity,
            irrigation_status=mun.get("irrigation_status", "rainfed"),
        )
        if not crop_risk:
            crop_risk = compute_crop_stage_risk(
                cdd=cdd, cwd=cwd, rainfall_7d=rain_7d,
                tmax_c=tmax, humidity_pct=humidity,
                crop=default_crop, crop_stage=default_stage,
                irrigation_status=mun.get("irrigation_status", "rainfed"),
            )
            crop_risk.update({
                "calendar_anchored": False,
                "calendar_context_note": calendar_context.get("note"),
            })

        # Municipal composite risk score
        indicator_bundle = {
            "cdd": cdd, "drought_class": drought_class,
            "rainfall_7d_mm": rain_7d, "heat_class": heat.get("heat_class", "low"),
        }
        municipal_risk_score = compute_municipal_risk_score(indicator_bundle, mun)

        official_hazards = _official_hazards_for_municipality(
            mun, pagasa_current, acap_current, calendar_context
        )
        results[psgc] = {
            "psgc": psgc,
            "municipality": mun["name"],
            "province": mun["province"],
            "lat": mun["lat"],
            "lon": mun["lon"],
            "as_of_date": (
                cis_rec.get("date") if cis_rec
                else noah_rec.get("date") if noah_rec
                else latest.get("date")
            ),
            "observations": {
                "rainfall_24h_mm": rain_24h,
                "rainfall_source": rainfall_source,
                "apa_cis_rainfall_24h_mm": cis_rain,
                "apa_cis_tmax_c": cis_rec.get("tmax_c") if cis_rec else None,
                "apa_cis_wind_speed_ms": cis_rec.get("wind_speed_ms") if cis_rec else None,
                "apa_cis_record_date": cis_rec.get("date") if cis_rec else None,
                "up_noah_rainfall_1h_mm": noah_rec.get("rainfall_1h_mm") if noah_rec else None,
                "up_noah_rainfall_3h_mm": noah_rec.get("rainfall_3h_mm") if noah_rec else None,
                "up_noah_rainfall_6h_mm": noah_rec.get("rainfall_6h_mm") if noah_rec else None,
                "up_noah_rainfall_12h_mm": noah_rec.get("rainfall_12h_mm") if noah_rec else None,
                "up_noah_rainfall_24h_mm": noah_rain,
                "up_noah_rainfall_tomorrow_mm": noah_rec.get("rainfall_tomorrow_mm") if noah_rec else None,
                "up_noah_heat_index_c": noah_heat_index,
                "up_noah_tmax_c": noah_tmax,
                "up_noah_record_date": noah_rec.get("date") if noah_rec else None,
                "up_noah_method": noah_rec.get("method") if noah_rec else None,
                "nasa_power_rainfall_24h_mm": latest.get("rainfall_mm"),
                "chirps_rainfall_24h_mm": chirps_rain,
                "chirps_record_date": chirps_rec.get("date") if chirps_rec else None,
                "rainfall_48h_mm": rain_48h,
                "rainfall_7d_mm": rain_7d,
                "rainfall_30d_mm": rain_30d,
                "tmax_c": tmax,
                "heat_index_c": noah_heat_index,
                "tmin_c": tmin,
                "tmean_c": tmean,
                "humidity_pct": humidity,
                "wind_speed_ms": wind,
                "solar_mj": solar,
            },
            "indicators": {
                "cdd": cdd,
                "cwd": cwd,
                "drought_class": drought_class,
                "rainfall_anomaly": anomaly,
                "heat_stress": heat,
                "eto_mm": eto,
                "irrigation_demand": irr_demand,
                "field_workability": workability,
                "postharvest_drying_risk": drying_risk,
                "crop_stage_risk": crop_risk,
                "crop_calendar_context": calendar_context,
                "municipal_risk_score": municipal_risk_score,
            },
            "official_hazards": official_hazards,
            "forecast_10_day": _acap_municipality_ten_day(mun, acap_current),
            "data_sources": {
                "weather": weather_source,
                "rainfall_used": rainfall_source,
                "rainfall_fallback": _rainfall_fallback_note(rainfall_source),
                "priority_order": "APA CIS > UP NOAH > CHIRPS rainfall > NASA POWER",
            },
        }

    return results


def _rainfall_fallback_note(source: str) -> Optional[str]:
    if source == "apa_cis":
        return None
    if source == "up_noah":
        return "APA CIS rainfall unavailable for this municipality; using UP NOAH sampled weather overlay."
    if source == "chirps":
        return "APA CIS/UP NOAH rainfall unavailable for this municipality; using CHIRPS."
    return "APA CIS/UP NOAH/CHIRPS rainfall unavailable or stale; using NASA POWER."


def _acap_province_ten_day(province: str, acap_data: Dict) -> Dict:
    for item in acap_data.get("ten_day_forecast", []) if isinstance(acap_data, dict) else []:
        if (item.get("name") or "").lower() == (province or "").lower():
            return item
    return {}


def _acap_has_calendar(mun: Dict, acap_data: Dict) -> bool:
    target = ((mun.get("province") or "").lower(), _norm_name(mun.get("name") or mun.get("municipality", "")))
    for item in acap_data.get("crop_calendar_municipalities", []) if isinstance(acap_data, dict) else []:
        key = ((item.get("province") or "").lower(), _norm_name(item.get("municipality", "")))
        if key == target:
            return True
    return False


def _acap_municipality_ten_day(mun: Dict, acap_data: Dict) -> Dict:
    """Return a compact ACAP 10-day municipal forecast summary."""
    province_doc = _acap_province_ten_day(mun.get("province"), acap_data)
    municipalities = province_doc.get("municipalities", {}) if isinstance(province_doc, dict) else {}
    target = _norm_name(mun.get("name") or mun.get("municipality", ""))
    records = []

    for name, items in municipalities.items():
        if _norm_name(name) == target:
            records = items or []
            break

    if not records:
        return {
            "available": False,
            "source": "ACAP Cagayan Valley",
            "source_date": province_doc.get("date_created") or province_doc.get("_update_time"),
        }

    rain_classes = [str(item.get("rainfall", "")).strip() for item in records if item.get("rainfall")]
    covers = [str(item.get("cover", "")).strip() for item in records if item.get("cover")]
    tmax_values = [item.get("tmax") for item in records if isinstance(item.get("tmax"), (int, float))]
    tmin_values = [item.get("tmin") for item in records if isinstance(item.get("tmin"), (int, float))]
    humidity_values = [item.get("humidity") for item in records if isinstance(item.get("humidity"), (int, float))]
    wind_values = [item.get("wspeed") for item in records if isinstance(item.get("wspeed"), (int, float))]

    def most_common(values: List[str]) -> Optional[str]:
        if not values:
            return None
        return max(set(values), key=values.count)

    return {
        "available": True,
        "source": "ACAP Cagayan Valley",
        "source_date": province_doc.get("date_created") or province_doc.get("_update_time"),
        "date_forecast": records[0].get("date_forecast"),
        "date_range": records[0].get("date_range"),
        "rainfall_class": most_common(rain_classes),
        "weather_cover": most_common(covers),
        "tmax_range_c": [
            round(min(tmax_values), 1),
            round(max(tmax_values), 1),
        ] if tmax_values else None,
        "tmin_range_c": [
            round(min(tmin_values), 1),
            round(max(tmin_values), 1),
        ] if tmin_values else None,
        "avg_humidity_pct": round(sum(humidity_values) / len(humidity_values), 1) if humidity_values else None,
        "avg_wind_speed_ms": round(sum(wind_values) / len(wind_values), 1) if wind_values else None,
        "days": len(records),
        "daily": records[:10],
    }


def _official_hazards_for_municipality(
    mun: Dict,
    pagasa_data: Dict,
    acap_data: Dict = None,
    calendar_context: Dict = None,
) -> Dict:
    """Attach province-level PAGASA context to a municipal indicator record."""
    acap_data = acap_data or {}
    calendar_context = calendar_context or {}
    province = mun.get("province")
    province_key = (province or "").lower().replace(" ", "_")
    typhoon = pagasa_data.get("typhoon", {}) if isinstance(pagasa_data, dict) else {}
    ten_day = pagasa_data.get("ten_day_forecast", {}) if isinstance(pagasa_data, dict) else {}
    seasonal = pagasa_data.get("seasonal_outlook", {}) if isinstance(pagasa_data, dict) else {}

    signal_levels = typhoon.get("signal_levels", {}) if isinstance(typhoon, dict) else {}
    affected_municipalities = typhoon.get("affected_municipalities", []) if isinstance(typhoon, dict) else []
    validation = typhoon.get("municipality_validation", {}) if isinstance(typhoon, dict) else {}
    coverage_scope = validation.get("coverage_scope") or "province_full"
    official_municipality_signal = 0
    official_municipality_match = None
    if isinstance(affected_municipalities, list):
        target_name = _norm_name(mun.get("name") or mun.get("municipality", ""))
        for affected in affected_municipalities:
            if not isinstance(affected, dict):
                continue
            same_psgc = affected.get("psgc") and affected.get("psgc") == mun.get("psgc")
            same_name = (
                _norm_name(affected.get("municipality", "")) == target_name
                and affected.get("province") == province
            )
            if same_psgc or same_name:
                official_municipality_signal = int(affected.get("tcws_signal") or affected.get("signal") or affected.get("signal_level") or 0)
                official_municipality_match = affected
                break
    if coverage_scope in ("municipality", "mixed"):
        tcws_signal = official_municipality_signal
    elif affected_municipalities:
        tcws_signal = official_municipality_signal or signal_levels.get(province, 0)
    else:
        tcws_signal = signal_levels.get(province, 0)
    ten_day_province = ten_day.get(province_key, {}) if isinstance(ten_day, dict) else {}
    acap_ten_day = _acap_province_ten_day(province, acap_data)

    has_crop_calendar = bool(calendar_context.get("available")) or _acap_has_calendar(mun, acap_data)
    current_stages = calendar_context.get("current_stages", [])
    return {
        "pagasa_source_date": pagasa_data.get("entry_date") or pagasa_data.get("as_of"),
        "typhoon_active": bool(typhoon.get("active")),
        "typhoon_name": typhoon.get("name"),
        "tcws_signal": tcws_signal,
        "tcws_coverage_scope": coverage_scope,
        "tcws_municipality_validated": bool(official_municipality_match),
        "tcws_match": official_municipality_match,
        "ten_day_outlook": ten_day_province.get("outlook"),
        "ten_day_rainfall_range_mm": ten_day_province.get("rainfall_range_mm"),
        "ten_day_agri_advisory": ten_day_province.get("agri_advisory"),
        "acap_ten_day_available": bool(acap_ten_day),
        "acap_ten_day_source_date": acap_ten_day.get("date_created") or acap_ten_day.get("_update_time"),
        "acap_ten_day_municipality_count": len(acap_ten_day.get("municipalities", {}) or {}),
        "acap_crop_calendar_available": has_crop_calendar,
        "acap_crop_calendar_period": calendar_context.get("period_label"),
        "acap_crop_calendar_current_stages": current_stages,
        "crop_calendar_decision_point": (
            f"ACAP municipal rice/corn calendar active for {calendar_context.get('period_label')}: "
            + "; ".join(
                f"{stage.get('crop_label')} season {stage.get('season')} - {stage.get('calendar_stage_label')}"
                for stage in current_stages
            )
            if current_stages else (
                "ACAP crop calendar available, but no rice/corn stage is active for the current half-month period."
                if has_crop_calendar else
                "No ACAP crop calendar for this municipality; using seasonal default crop stage."
            )
        ),
        "seasonal_rainfall_outlook": seasonal.get("rainfall_outlook"),
        "enso_phase": (pagasa_data.get("enso", {}) or {}).get("phase")
            or (pagasa_data.get("enso", {}) or {}).get("enso_phase"),
        "review_status": ten_day.get("review_status") or pagasa_data.get("data_source") or "unreviewed",
    }


def save_indicator_outputs(results: Dict) -> None:
    """Save indicators in multiple formats for frontend consumption."""
    ref_date = today_pht()
    ind_path = PROJECT_ROOT / cfg["paths"]["indicators"]

    # Full indicators JSON (all municipalities)
    full_path = ind_path / f"indicators_{ref_date.isoformat()}.json"
    latest_path = ind_path / "indicators_latest.json"
    output = {
        "meta": {
            "generated_at": __import__("datetime").datetime.utcnow().isoformat(),
            "as_of_date": ref_date.isoformat(),
            "municipality_count": len(results),
        },
        "data": results,
    }
    save_json(output, full_path)
    save_json(output, latest_path)
    logger.info(f"Saved full indicators → {latest_path}")

    # GeoJSON for map layers
    _save_geojson_layers(results)


def _save_geojson_layers(results: Dict) -> None:
    """Export indicator data as GeoJSON for Leaflet map layers."""
    geo_path = PROJECT_ROOT / cfg["paths"]["geospatial"]

    def make_feature(r: Dict, props: Dict) -> Dict:
        return {
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [r["lon"], r["lat"]],
            },
            "properties": {
                "psgc": r["psgc"],
                "municipality": r["municipality"],
                "province": r["province"],
                **props,
            },
        }

    layers = {
        "rainfall_24h": [],
        "drought_watch": [],
        "heat_stress": [],
        "field_workability": [],
        "rainfall_anomaly": [],
        "crop_risk": [],
        "drying_risk": [],
        "municipal_risk": [],
    }

    for psgc, r in results.items():
        obs = r.get("observations", {})
        ind = r.get("indicators", {})

        # Rainfall 24h
        layers["rainfall_24h"].append(make_feature(r, {
            "rainfall_mm": obs.get("rainfall_24h_mm"),
            "class": _rain_class(obs.get("rainfall_24h_mm")),
        }))

        # Drought watch
        layers["drought_watch"].append(make_feature(r, {
            "cdd": ind.get("cdd"),
            "drought_class": ind.get("drought_class"),
            "color": _drought_color(ind.get("drought_class", "none")),
        }))

        # Heat stress
        hs = ind.get("heat_stress", {})
        layers["heat_stress"].append(make_feature(r, {
            "heat_class": hs.get("heat_class"),
            "wbgt": hs.get("wbgt_approx"),
            "color": hs.get("heat_color", "#4CAF50"),
            "tmax_c": obs.get("tmax_c"),
        }))

        # Field workability
        fw = ind.get("field_workability", {})
        layers["field_workability"].append(make_feature(r, {
            "workability_class": fw.get("overall_class"),
            "workability_label": fw.get("overall_label"),
            "color": fw.get("color", "#4CAF50"),
            "operations": fw.get("operations", {}),
        }))

        # Rainfall anomaly
        anom = ind.get("rainfall_anomaly", {})
        layers["rainfall_anomaly"].append(make_feature(r, {
            "anomaly_mm": anom.get("anomaly_mm"),
            "pct_of_normal": anom.get("pct_of_normal"),
            "anomaly_class": anom.get("anomaly_class"),
            "color": _anomaly_color(anom.get("anomaly_class", "unknown")),
        }))

        # Crop risk
        cr = ind.get("crop_stage_risk", {})
        layers["crop_risk"].append(make_feature(r, {
            "risk_score": cr.get("risk_score"),
            "risk_class": cr.get("risk_class"),
            "color": cr.get("risk_color", "#4CAF50"),
            "crop": cr.get("crop"),
        }))

        # Postharvest drying risk
        dr = ind.get("postharvest_drying_risk", {})
        layers["drying_risk"].append(make_feature(r, {
            "drying_class": dr.get("drying_class"),
            "risk_score": dr.get("risk_score"),
            "recommend_mechanical_drying": dr.get("recommend_mechanical_drying"),
            "reasons": dr.get("reasons", []),
            "color": _drying_color(dr.get("drying_class", "unknown")),
        }))

        # Municipal risk composite
        layers["municipal_risk"].append(make_feature(r, {
            "risk_score": ind.get("municipal_risk_score"),
            "color": _risk_score_color(ind.get("municipal_risk_score", 0)),
        }))

    for layer_name, features in layers.items():
        geojson = {"type": "FeatureCollection", "features": features}
        out_path = geo_path / f"{layer_name}.geojson"
        save_json(geojson, out_path)
        logger.info(f"Saved GeoJSON layer → {out_path}")


# ── Color helpers for map layers ──────────────────────────────────────────────
def _rain_class(mm: Optional[float]) -> str:
    if mm is None: return "no_data"
    if mm < 1: return "dry"
    if mm < 10: return "light"
    if mm < 25: return "moderate"
    if mm < 50: return "heavy"
    if mm < 100: return "very_heavy"
    return "extreme"


def _drought_color(cls: str) -> str:
    return {"none": "#E8F5E9", "watch": "#FFF9C4",
            "warning": "#FFCC80", "critical": "#B71C1C"}.get(cls, "#E0E0E0")


def _anomaly_color(cls: str) -> str:
    return {
        "far_below": "#B71C1C", "below": "#FF7043",
        "near_normal": "#A5D6A7", "above": "#1E88E5",
        "far_above": "#0D47A1", "unknown": "#BDBDBD",
    }.get(cls, "#BDBDBD")


def _risk_score_color(score: float) -> str:
    if score >= 70: return "#B71C1C"
    if score >= 50: return "#FF5722"
    if score >= 30: return "#FF9800"
    if score >= 15: return "#FFC107"
    return "#4CAF50"


def _drying_color(cls: str) -> str:
    return {
        "suitable": "#4CAF50",
        "caution": "#FFC107",
        "high_risk": "#FF5722",
        "unsuitable": "#B71C1C",
        "unknown": "#BDBDBD",
    }.get(cls, "#BDBDBD")


# ═══════════════════════════════════════════════════════════════════════════════
# 4. ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════════

def run() -> None:
    logger.info("=== APA-CIS Indicator Engine ===")
    results = compute_all_indicators()
    if not results:
        logger.error("No indicator results computed.")
        return
    save_indicator_outputs(results)
    log_etl_event(
        source="indicator_engine",
        run_date=today_pht().isoformat(),
        records_fetched=len(load_municipalities()),
        records_valid=len(results),
        status="success",
        message=f"Computed {len(results)} municipal indicator sets",
    )
    logger.info(f"=== Done — {len(results)} municipalities processed ===")


if __name__ == "__main__":
    run()
