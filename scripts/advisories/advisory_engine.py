"""
scripts/advisories/advisory_engine.py
Rule-based agricultural advisory engine for APA-CIS.

Evaluates climate indicator outputs against a rule matrix and generates
actionable advisories for DA RFO 02, LGUs, municipal agriculturists, and farmers.

Advisory formats:
  - Technical bulletin (DA RFO 02 / PAO / RAO)
  - LGU/MAO advisory
  - SMS-friendly (≤160 chars)
  - Social media (Facebook-ready)

DA RFO 02 — APA-CIS Climate Information Service, Cagayan Valley
"""

import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

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

logger = setup_logger(__name__, "advisory_engine.log")
cfg = load_config()

ISSUER = "DA-RFO2 APA"
ASSISTANCE_CONTACT = "0916-708-9707"
ASSISTANCE_FACEBOOK = "DA RFO2 APA Facebook page"
ASSISTANCE_EMAIL = "darfo2apa@gmail.com"


def load_cra_measures() -> Dict:
    """Load CRA adaptation measure matrix for advisory enrichment."""
    path = PROJECT_ROOT / cfg["paths"].get("reference", "data/reference") / "cra_adaptation_measures.json"
    return load_json(path) or {"rules": {}, "default": []}


CRA_MEASURES = load_cra_measures()


def _cra_measures_for_rule(rule_id: str) -> List[str]:
    measures = CRA_MEASURES.get("rules", {}).get(rule_id)
    if measures:
        return measures
    return CRA_MEASURES.get("default", [])


def _calendar_crop_family(crop: str) -> str:
    crop = (crop or "").lower()
    if crop.startswith("rice"):
        return "rice"
    if crop.startswith("corn"):
        return "corn"
    return crop


def _calendar_stage_matches(rule_stage: str, calendar_stage: Dict) -> bool:
    rule_stage = (rule_stage or "").lower()
    if rule_stage == "all":
        return True
    risk_stage = (calendar_stage.get("risk_stage") or "").lower()
    raw_stage = (calendar_stage.get("calendar_stage") or "").lower()
    if rule_stage in (risk_stage, raw_stage):
        return True
    if rule_stage == "reproductive" and risk_stage in ("reproductive", "tasseling", "grain_fill", "flowering"):
        return True
    if rule_stage == "vegetative" and risk_stage in ("vegetative", "transplanting", "seedbed"):
        return True
    if rule_stage in ("harvesting", "postharvest") and risk_stage in ("ripening", "maturation"):
        return True
    return False


def _calendar_anchor_for_rule(indicators: Dict, rule: Dict) -> Dict:
    context = indicators.get("indicators", {}).get("crop_calendar_context", {}) or {}
    current_stages = context.get("current_stages", []) or []
    affected_crops = rule.get("affected_crops") or ["all"]
    affected_stages = rule.get("affected_stages") or ["all"]
    affected_families = {_calendar_crop_family(crop) for crop in affected_crops}
    matches = []

    for stage in current_stages:
        crop_match = "all" in affected_families or stage.get("crop") in affected_families
        stage_match = any(_calendar_stage_matches(rule_stage, stage) for rule_stage in affected_stages)
        if crop_match and stage_match:
            matches.append(stage)

    if not matches and ("all" in affected_families or "all" in affected_stages):
        matches = current_stages

    return {
        "anchored": bool(matches),
        "source": context.get("source"),
        "period": context.get("period_label"),
        "municipality": context.get("municipality"),
        "province": context.get("province"),
        "matched_current_stages": matches,
        "note": (
            "Advisory is anchored to matching current ACAP rice/corn calendar stage(s)."
            if matches else
            context.get("note") or "No matching current ACAP rice/corn stage for this advisory rule."
        ),
    }


OPERATION_ADVISORY_SPECS = {
    "land_preparation": {
        "name": "Defer Land Preparation",
        "description": "plowing, harrowing, puddling, bed preparation",
        "affected_stages": ["land_prep", "seedbed"],
        "responsible_office": "MAO + AEWs + machinery operators",
        "action": "defer heavy land preparation; resume when fields are trafficable and not waterlogged or powder-dry",
    },
    "transplanting": {
        "name": "Defer Transplanting / Crop Establishment",
        "description": "rice transplanting, direct seeding, crop establishment",
        "affected_stages": ["seedbed", "transplanting", "vegetative"],
        "responsible_office": "MAO + AEWs + seedling nursery coordinators",
        "action": "hold transplanting or seeding until soil moisture and field access are stable",
    },
    "fertilizer_application": {
        "name": "Defer Fertilizer Application",
        "description": "basal, side-dress, and top-dress fertilizer",
        "affected_stages": ["vegetative", "reproductive", "tasseling", "grain_fill"],
        "responsible_office": "MAO + AEWs",
        "action": "delay fertilizer application to avoid runoff, leaching, volatilization, or poor uptake",
    },
    "spraying": {
        "name": "Defer Pesticide / Foliar Spraying",
        "description": "pesticide, fungicide, herbicide, and foliar application",
        "affected_stages": ["vegetative", "reproductive", "tasseling", "grain_fill"],
        "responsible_office": "MAO + Crop Protection Center + AEWs",
        "action": "reschedule spraying for a clear, low-wind window to avoid wash-off and drift",
    },
    "irrigation": {
        "name": "Defer Irrigation",
        "description": "supplemental irrigation and pump operation",
        "affected_stages": ["all"],
        "responsible_office": "MAO + NIA + Irrigators Associations",
        "action": "pause irrigation to avoid over-saturation; prioritize drainage and canal checks first",
    },
    "harvesting": {
        "name": "Defer Harvesting",
        "description": "manual harvest, combine harvest, hauling from field",
        "affected_stages": ["ripening", "maturation", "harvesting", "postharvest"],
        "responsible_office": "MAO + DA Mechanization/Postharvest Unit",
        "action": "defer harvest or machine entry until fields can carry workers and equipment safely",
    },
    "drying": {
        "name": "Defer Open-Air Grain Drying",
        "description": "sun-drying of palay or corn grain",
        "affected_stages": ["ripening", "maturation", "harvesting", "postharvest"],
        "responsible_office": "MAO + DA Mechanization/Postharvest Unit",
        "action": "avoid open sun-drying; use covered temporary storage or mechanical drying where available",
    },
    "pest_monitoring": {
        "name": "Defer Field Pest Monitoring",
        "description": "field scouting and IPM inspection",
        "affected_stages": ["vegetative", "reproductive", "tasseling", "grain_fill"],
        "responsible_office": "MAO + Crop Protection Center + AEWs",
        "action": "delay field entry if unsafe, then prioritize scouting as soon as rainfall and access improve",
    },
}


def _operation_defer_reasons(operation: str, indicators: Dict) -> List[str]:
    obs = indicators.get("observations", {})
    fw = indicators.get("indicators", {}).get("field_workability", {})
    rain_24h = fw.get("rain_24h_mm", obs.get("rainfall_24h_mm") or 0) or 0
    rain_48h = fw.get("rain_48h_mm", obs.get("rainfall_48h_mm") or 0) or 0
    cdd = fw.get("cdd", indicators.get("indicators", {}).get("cdd") or 0) or 0
    wind = fw.get("wind_speed_ms", obs.get("wind_speed_ms"))
    humidity = fw.get("humidity_pct", obs.get("humidity_pct"))
    reasons = []

    if operation in ("land_preparation", "transplanting", "harvesting", "pest_monitoring"):
        if rain_24h >= 20 or rain_48h >= 80:
            reasons.append("fields may be waterlogged or unsafe for workers and machinery")
        elif rain_24h >= 10 or rain_48h >= 20:
            reasons.append("recent rainfall can cause soil compaction, rutting, or poor crop establishment")
    if operation in ("fertilizer_application", "spraying", "harvesting", "drying"):
        if rain_24h >= 10 or rain_48h >= 25:
            reasons.append("rainfall increases runoff, wash-off, grain wetting, or harvest loss risk")
    if operation == "spraying":
        if wind is not None and wind >= 5:
            reasons.append("wind speed is high enough to increase spray drift risk")
        if humidity is not None and humidity >= 85:
            reasons.append("high humidity and wet canopy can reduce spray effectiveness")
    if operation == "drying":
        if humidity is not None and humidity >= 85:
            reasons.append("high humidity slows drying and increases mold or grain-quality risk")
        if rain_24h >= 5:
            reasons.append("recent rain makes open-air drying unreliable")
    if operation in ("land_preparation", "transplanting") and cdd >= 14:
        reasons.append("extended dry spell can reduce seedling survival and field preparation quality")
    if operation == "irrigation":
        reasons.append("recent rainfall is enough that irrigation can be paused to prevent over-saturation")

    return reasons or ["field-workability thresholds classify this operation as defer for current local conditions"]


def _operation_calendar_anchor(indicators: Dict, spec: Dict) -> Dict:
    rule_like = {
        "affected_crops": ["rice_irrigated", "rice_rainfed", "corn_yellow", "corn_white"],
        "affected_stages": spec.get("affected_stages", ["all"]),
    }
    anchor = _calendar_anchor_for_rule(indicators, rule_like)
    if anchor.get("anchored"):
        return anchor

    context = indicators.get("indicators", {}).get("crop_calendar_context", {}) or {}
    current_stages = context.get("current_stages", []) or []
    return {
        **anchor,
        "anchored": bool(current_stages),
        "matched_current_stages": current_stages,
        "note": (
            "Operation advisory is tied to the municipality's current ACAP rice/corn stage(s); "
            "the operation may be preparatory or postharvest relative to the active stage."
            if current_stages else anchor.get("note")
        ),
    }


def _operation_severity(operation: str, indicators: Dict) -> str:
    fw = indicators.get("indicators", {}).get("field_workability", {})
    overall = fw.get("overall_class")
    high_impact = {"land_preparation", "transplanting", "harvesting", "drying", "irrigation"}
    if overall == "not_workable" or operation in high_impact:
        return "warning"
    return "advisory"


def _generate_operation_defer_advisories(indicators: Dict, mun: Dict) -> List[Dict]:
    fw = indicators.get("indicators", {}).get("field_workability", {})
    operations = fw.get("operations") or {}
    if not operations:
        return []

    generated = []
    for operation, status in operations.items():
        if status != "defer":
            continue
        spec = OPERATION_ADVISORY_SPECS.get(operation)
        if not spec:
            continue
        reasons = _operation_defer_reasons(operation, indicators)
        anchor = _operation_calendar_anchor(indicators, spec)
        stage_text = "; ".join(
            f"{stage.get('crop_label')} season {stage.get('season')} - {stage.get('calendar_stage_label')}"
            for stage in anchor.get("matched_current_stages", [])
        ) or "no active rice/corn stage"
        severity = _operation_severity(operation, indicators)
        rule_name = f"Operations Advisory - {spec['name']}"
        reason_text = "; ".join(reasons)

        generated.append({
            "rule_id": f"OPERATIONS_DEFER_{operation.upper()}",
            "rule_name": rule_name,
            "severity": severity,
            "category": "operations_advisory",
            "operation": operation,
            "operation_status": "defer",
            "affected_crops": ["rice_irrigated", "rice_rainfed", "corn_yellow", "corn_white"],
            "affected_stages": spec.get("affected_stages", ["all"]),
            "calendar_anchor": anchor,
            "responsible_office": spec["responsible_office"],
            "adaptation_measures": _cra_measures_for_rule("default"),
            "adaptation_source": CRA_MEASURES.get("meta", {}).get("source", "CRA Compendium"),
            "texts": {
                "bulletin": (
                    f"{rule_name.upper()} - {mun['municipality']}: {spec['description']} should be deferred. "
                    f"Basis: {reason_text}. ACAP calendar anchor: {anchor.get('period') or 'current period'} - {stage_text}. "
                    f"Recommended action: {spec['action']}."
                ),
                "sms": (
                    f"DA OPS: Defer {spec['name'].replace('Defer ', '').lower()} in {mun['municipality']}. "
                    f"{reasons[0].capitalize()}. Check MAO guidance."
                ),
                "lgu": (
                    f"{rule_name.upper()} - {mun['municipality']}\n"
                    f"Operation: {spec['description']}\n"
                    f"Why defer: {reason_text}.\n"
                    f"ACAP calendar: {anchor.get('period') or 'current period'} - {stage_text}.\n"
                    f"LGU/MAO action: {spec['action']}; inform affected barangays and reschedule support services."
                ),
                "facebook": (
                    f"{rule_name} - {mun['municipality']}: Please defer {spec['description']} for now. "
                    f"Reason: {reasons[0]}. Current crop calendar basis: {stage_text}. "
                    "Coordinate with your Municipal Agriculturist for the next safe field window."
                ),
            },
        })

    return generated


# ═══════════════════════════════════════════════════════════════════════════════
# 1. ADVISORY RULE DEFINITIONS
# ═══════════════════════════════════════════════════════════════════════════════

# Each rule is a dict:
# {
#   "rule_id": str,
#   "name": str,
#   "trigger_fn": callable(indicators, mun) -> bool,
#   "severity": "info" | "advisory" | "warning" | "danger",
#   "affected_crops": list,
#   "affected_stages": list,
#   "bulletin_text": callable(indicators, mun) -> str,
#   "sms_text": callable(indicators, mun) -> str,
#   "lgu_text": callable(indicators, mun) -> str,
#   "fb_text": callable(indicators, mun) -> str,
#   "responsible_office": str,
# }

def _get_ind(indicators: Dict, key: str, default=None):
    """Safe nested accessor for indicators dict."""
    return indicators.get("indicators", {}).get(key, default)


def _get_obs(indicators: Dict, key: str, default=None):
    """Safe nested accessor for observations dict."""
    return indicators.get("observations", {}).get(key, default)


def _get_hazard(indicators: Dict, key: str, default=None):
    """Safe nested accessor for official hazard context."""
    return indicators.get("official_hazards", {}).get(key, default)


def _normalise_municipality(mun: Dict) -> Dict:
    """Return a municipality record with both config and advisory key names."""
    if not mun:
        return {}
    name = mun.get("municipality") or mun.get("name")
    return {**mun, "municipality": name, "name": mun.get("name") or name}


ADVISORY_RULES = [

    {
        "rule_id": "PAGASA_TCWS_ACTIVE",
        "name": "PAGASA Tropical Cyclone Wind Signal Active",
        "trigger_fn": lambda ind, mun: (
            bool(_get_hazard(ind, "typhoon_active"))
            and int(_get_hazard(ind, "tcws_signal", 0) or 0) > 0
        ),
        "severity": "danger",
        "affected_crops": ["all"],
        "affected_stages": ["all"],
        "bulletin_text": lambda ind, mun: (
            f"OFFICIAL PAGASA TROPICAL CYCLONE ADVISORY - {mun['municipality']}, {mun['province']}: "
            f"TCWS Signal No. {_get_hazard(ind, 'tcws_signal', 0)} is active "
            f"for the province due to {_get_hazard(ind, 'typhoon_name', 'an active tropical cyclone')}. "
            "Suspend field operations, secure machinery and harvested produce, avoid exposed coastal/upland areas, "
            "and coordinate with MDRRMC/MAO for pre-disaster agriculture actions."
        ),
        "sms_text": lambda ind, mun: (
            f"PAGASA TCWS {_get_hazard(ind, 'tcws_signal', 0)}: Suspend farm work in {mun['municipality']}. "
            "Secure crops/equipment. Coordinate with MAO/MDRRMC."
        ),
        "lgu_text": lambda ind, mun: (
            f"PAGASA TCWS ADVISORY - {mun['municipality']}\n"
            f"Signal No. {_get_hazard(ind, 'tcws_signal', 0)} is active for {mun['province']}.\n"
            "Actions: suspend field operations, secure harvest and inputs, pre-position assessment teams, "
            "and prepare crop damage documentation."
        ),
        "fb_text": lambda ind, mun: (
            f"PAGASA TCWS ALERT - {mun['municipality']}, {mun['province']}\n\n"
            "Suspend farm operations and secure harvested crops, machinery, and livestock areas. "
            "Coordinate with your MAO and MDRRMC for assistance."
        ),
        "responsible_office": "PAGASA + DA RFO 02 + LGU MDRRMC + MAO",
    },

    {
        "rule_id": "POSTHARVEST_DRYING_RISK",
        "name": "Postharvest Drying Risk",
        "trigger_fn": lambda ind, mun: (
            _get_ind(ind, "postharvest_drying_risk", {}).get("drying_class")
            in ("high_risk", "unsuitable")
        ),
        "severity": "warning",
        "affected_crops": ["rice_irrigated", "rice_rainfed", "corn_yellow", "corn_white"],
        "affected_stages": ["harvesting", "postharvest"],
        "bulletin_text": lambda ind, mun: (
            f"POSTHARVEST DRYING RISK - {mun['municipality']}: "
            f"Drying class is {_get_ind(ind, 'postharvest_drying_risk', {}).get('drying_class', 'unknown')}. "
            "Avoid open sun-drying if rain/high humidity persists. Prioritize mechanical dryers, tarpaulins, "
            "covered temporary storage, and rapid hauling to postharvest facilities."
        ),
        "sms_text": lambda ind, mun: (
            f"DA WARNING: Drying risk in {mun['municipality']}. Use mechanical dryer/covered storage; avoid wet grain spoilage."
        ),
        "lgu_text": lambda ind, mun: (
            f"POSTHARVEST ADVISORY - {mun['municipality']}\n"
            "Coordinate mobile dryers, tarpaulins, and storage support for farmers harvesting rice/corn."
        ),
        "fb_text": lambda ind, mun: (
            f"POSTHARVEST ADVISORY - {mun['municipality']}: High drying risk. "
            "Use mechanical dryers or covered storage to protect palay/mais quality."
        ),
        "responsible_office": "MAO + DA Mechanization/Postharvest Unit",
    },

    {
        "rule_id": "IRRIGATION_HIGH_DEMAND",
        "name": "High Irrigation Demand",
        "trigger_fn": lambda ind, mun: (
            _get_ind(ind, "irrigation_demand", {}).get("priority") in ("high", "critical")
        ),
        "severity": "warning",
        "affected_crops": ["rice_irrigated", "rice_rainfed", "corn_yellow", "hvcc"],
        "affected_stages": ["vegetative", "reproductive", "flowering", "tasseling"],
        "bulletin_text": lambda ind, mun: (
            f"IRRIGATION PRIORITY - {mun['municipality']}: "
            f"Estimated irrigation demand is {_get_ind(ind, 'irrigation_demand', {}).get('demand_mm', 'N/A')} mm/day "
            f"with {_get_ind(ind, 'irrigation_demand', {}).get('priority', 'unknown')} priority. "
            "Prioritize supplemental irrigation for rainfed and reproductive-stage crops."
        ),
        "sms_text": lambda ind, mun: (
            f"DA ADVISORY: Irrigation priority in {mun['municipality']}. Prioritize reproductive-stage rice/corn and rainfed fields."
        ),
        "lgu_text": lambda ind, mun: (
            f"IRRIGATION ADVISORY - {mun['municipality']}\n"
            "Coordinate water scheduling with NIA/irrigators associations and identify rainfed barangays needing support."
        ),
        "fb_text": lambda ind, mun: (
            f"IRRIGATION ADVISORY - {mun['municipality']}: Prioritize water for stressed rice/corn crops, especially rainfed areas."
        ),
        "responsible_office": "MAO + NIA + Irrigators Associations",
    },

    {
        "rule_id": "WET_SPELL_DISEASE_WATCH",
        "name": "Wet Spell Disease Watch",
        "trigger_fn": lambda ind, mun: (
            (_get_ind(ind, "cwd", 0) or 0) >= 3
            and (_get_obs(ind, "humidity_pct", 0) or 0) >= 80
        ),
        "severity": "advisory",
        "affected_crops": ["rice_irrigated", "rice_rainfed", "corn_yellow", "hvcc"],
        "affected_stages": ["vegetative", "reproductive"],
        "bulletin_text": lambda ind, mun: (
            f"WET SPELL DISEASE WATCH - {mun['municipality']}: "
            f"{_get_ind(ind, 'cwd', 0)} consecutive wet days and high humidity may favor fungal/bacterial diseases. "
            "Increase field scouting for rice blast/sheath blight and corn fungal diseases. Spray only when rain and wind conditions are safe."
        ),
        "sms_text": lambda ind, mun: (
            f"DA WATCH: Wet/humid days in {mun['municipality']}. Scout crops for disease; spray only in clear, low-wind weather."
        ),
        "lgu_text": lambda ind, mun: (
            f"DISEASE WATCH - {mun['municipality']}\n"
            "Ask AEWs to intensify field scouting and report pest/disease symptoms by barangay."
        ),
        "fb_text": lambda ind, mun: (
            f"DISEASE WATCH - {mun['municipality']}: Wet and humid conditions. Inspect rice/corn fields and consult AEW before spraying."
        ),
        "responsible_office": "MAO + Crop Protection Center + AEWs",
    },

    # ── TYPHOON / HEAVY RAIN ─────────────────────────────────────────────────
    {
        "rule_id": "RAIN_EXTREME_24H",
        "name": "Extreme Rainfall — All Operations Suspend",
        "trigger_fn": lambda ind, mun: (
            (ind.get("observations", {}).get("rainfall_24h_mm") or 0) >= 100
        ),
        "severity": "danger",
        "affected_crops": ["all"],
        "affected_stages": ["all"],
        "bulletin_text": lambda ind, mun: (
            f"DANGER — Extreme rainfall recorded in {mun['municipality']}, {mun['province']} "
            f"({(ind.get('observations',{}).get('rainfall_24h_mm') or 0):.1f} mm/24h). "
            "Suspend ALL field operations. Avoid crossing rivers and flood-prone areas. "
            "Secure harvested produce in elevated dry storage. Activate DRRM protocols. "
            "Coordinate with MDRRMC, SWDO, and MAO for rapid damage assessment. "
            "Pre-position emergency seed buffer and postharvest equipment."
        ),
        "sms_text": lambda ind, mun: (
            f"DA ALERT: Extreme rain in {mun['municipality']}. Suspend all farm work. "
            "Secure produce. Contact MAO for assistance."
        ),
        "lgu_text": lambda ind, mun: (
            f"AGRICULTURAL EMERGENCY ADVISORY — {mun['municipality']}\n"
            f"Extreme rainfall ({(ind.get('observations',{}).get('rainfall_24h_mm') or 0):.1f} mm/24h) "
            "requires immediate action:\n"
            "1. Advise farmers to suspend all field operations immediately.\n"
            "2. Coordinate with MDRRMC for damage assessment teams.\n"
            "3. Pre-position tarpaulins and drying facilities.\n"
            "4. Activate emergency seed replacement protocols.\n"
            "5. Document affected crop areas for PCIC crop insurance filing."
        ),
        "fb_text": lambda ind, mun: (
            f"⛈️ DA RFO 02 WEATHER ALERT — {mun['municipality']}, {mun['province']}\n\n"
            f"Extreme rainfall of {(ind.get('observations',{}).get('rainfall_24h_mm') or 0):.0f} mm "
            "has been recorded in your area.\n\n"
            "⚠️ SUSPEND all farm operations\n"
            "🌾 Secure harvested crops from rain\n"
            "🚫 Avoid rivers and flood areas\n"
            "📞 Contact your Municipal Agriculturist for assistance\n\n"
            "#DARFOCagayanValley #AgriculturalAdvisory #TayoNaHanda"
        ),
        "responsible_office": "DA RFO 02 + MDRRMC + MAO",
    },

    {
        "rule_id": "RAIN_HARVEST_RISK",
        "name": "Harvest Disruption Risk — Rainfall > 20mm",
        "trigger_fn": lambda ind, mun: (
            (ind.get("observations", {}).get("rainfall_24h_mm") or 0) >= 20
        ),
        "severity": "warning",
        "affected_crops": ["rice_irrigated", "rice_rainfed", "corn_yellow"],
        "affected_stages": ["harvesting", "ripening"],
        "bulletin_text": lambda ind, mun: (
            f"Harvest disruption risk in {mun['municipality']} due to rainfall of "
            f"{(ind.get('observations',{}).get('rainfall_24h_mm') or 0):.1f} mm/24h. "
            "Farmers in ripening or harvesting stages should: (1) Defer combine harvester "
            "deployment to avoid bogging; (2) Protect cut stalks from further wetting; "
            "(3) Prioritize mechanical drying over sun-drying for collected grain. "
            "Postharvest drying risk is ELEVATED. Coordinate with DA mechanization "
            "service providers for mobile dryer access."
        ),
        "sms_text": lambda ind, mun: (
            f"DA ADVISORY: Rain risk for harvest in {mun['municipality']}. "
            "Defer harvest, use mechanical dryer if available. Call MAO for help."
        ),
        "lgu_text": lambda ind, mun: (
            f"HARVEST ADVISORY — {mun['municipality']}\n"
            f"Rainfall of {(ind.get('observations',{}).get('rainfall_24h_mm') or 0):.1f} mm "
            "may disrupt ongoing harvest operations.\n"
            "Recommended actions:\n"
            "1. Advise farmers to assess field conditions before deploying machinery.\n"
            "2. Coordinate with RCEF mechanization pool for mobile dryer deployment.\n"
            "3. Issue tarpaulin assistance where needed.\n"
            "4. Document areas where harvest was deferred for scheduling follow-up."
        ),
        "fb_text": lambda ind, mun: (
            f"🌧️ HARVEST ADVISORY — {mun['municipality']}\n\n"
            "Rain is affecting harvest conditions. Delay harvesting if fields are wet. "
            "Use mechanical dryers to prevent grain spoilage.\n\n"
            "📞 Contact your Municipal Agriculturist for drying support.\n"
            "#Palay #Mais #Harvest #DARFOCagayanValley"
        ),
        "responsible_office": "MAO + DA Mechanization Unit",
    },

    # ── DROUGHT / DRY SPELL ──────────────────────────────────────────────────
    {
        "rule_id": "DROUGHT_CRITICAL",
        "name": "Critical Dry Spell — CDD ≥ 21 Days",
        "trigger_fn": lambda ind, mun: (
            _get_ind(ind, "cdd", 0) >= 21
            and mun.get("irrigation_status") == "rainfed"
        ),
        "severity": "danger",
        "affected_crops": ["rice_rainfed", "corn_yellow", "hvcc"],
        "affected_stages": ["vegetative", "reproductive"],
        "bulletin_text": lambda ind, mun: (
            f"CRITICAL DRY SPELL — {mun['municipality']} ({mun['province']}): "
            f"{_get_ind(ind, 'cdd', 0)} consecutive dry days recorded. "
            "Rainfed crops in vegetative and reproductive stages face severe stress risk. "
            "IMMEDIATE ACTIONS: (1) Declare drought watch for affected barangays; "
            "(2) Coordinate with NIA/LICA for emergency supplemental irrigation; "
            "(3) Pre-position drought-tolerant seed varieties for replanting; "
            "(4) Facilitate PCIC crop insurance claims for affected farmers; "
            "(5) Activate AMIA drought response protocols at AMIA villages; "
            "(6) Coordinate with DSWD/LGU for affected smallholder farmers."
        ),
        "sms_text": lambda ind, mun: (
            f"DA DANGER: {_get_ind(ind, 'cdd', 0)} dry days in {mun['municipality']}. "
            "Crop stress critical. Contact MAO for irrigation & seed help."
        ),
        "lgu_text": lambda ind, mun: (
            f"DROUGHT EMERGENCY ADVISORY — {mun['municipality']}, {mun['province']}\n\n"
            f"Consecutive Dry Days: {_get_ind(ind, 'cdd', 0)} days\n"
            "Status: CRITICAL — Immediate LGU action required\n\n"
            "Required actions:\n"
            "1. Conduct rapid crop damage assessment by barangay.\n"
            "2. Coordinate with NIA for emergency water allocation.\n"
            "3. Request DA RFO 02 for drought-tolerant seed buffer.\n"
            "4. Pre-enroll affected farmers under PCIC crop insurance.\n"
            "5. Report to DA RFO 02 RAED the number of affected farmers and hectares.\n"
            "6. Activate LGU DRRM Quick Response Fund for affected farmers."
        ),
        "fb_text": lambda ind, mun: (
            f"🔴 DROUGHT ALERT — {mun['municipality']}, {mun['province']}\n\n"
            f"⚠️ {_get_ind(ind, 'cdd', 0)} araw nang walang ulan.\n"
            "Ang mga magsasaka ay inirerekomenda na:\n"
            "✅ Humingi ng tulong sa NIA para sa irigasyon\n"
            "✅ Mag-apply ng PCIC crop insurance\n"
            "✅ Makipag-ugnayan sa Municipal Agriculturist\n\n"
            "📞 DA RFO 02 Hotline: (078) 844-1228\n"
            "#Tagtuyot #DARFOCagayanValley #AMIA"
        ),
        "responsible_office": "DA RFO 02 + NIA + LGU DRRM + AMIA Coordinators",
    },

    {
        "rule_id": "DROUGHT_WARNING",
        "name": "Dry Spell Warning — CDD 14–20 Days",
        "trigger_fn": lambda ind, mun: (
            14 <= _get_ind(ind, "cdd", 0) < 21
        ),
        "severity": "warning",
        "affected_crops": ["rice_rainfed", "corn_yellow"],
        "affected_stages": ["vegetative", "reproductive"],
        "bulletin_text": lambda ind, mun: (
            f"DRY SPELL WARNING — {mun['municipality']}: "
            f"{_get_ind(ind, 'cdd', 0)} consecutive dry days. "
            "Rainfed crops require close monitoring. "
            "Farmers should: (1) Check soil moisture and plant stress symptoms; "
            "(2) Prioritize irrigation for reproductive-stage crops; "
            "(3) Apply mulching to reduce soil moisture loss; "
            "(4) Avoid nutrient application until rain returns. "
            "Municipal agriculturist to prepare damage assessment forms."
        ),
        "sms_text": lambda ind, mun: (
            f"DA WARNING: {_get_ind(ind, 'cdd', 0)} dry days in {mun['municipality']}. "
            "Monitor crops. Irrigate if possible."
        ),
        "lgu_text": lambda ind, mun: (
            f"DRY SPELL WARNING — {mun['municipality']}\n"
            f"Day {_get_ind(ind, 'cdd', 0)} without significant rainfall.\n"
            "Action items:\n"
            "1. Alert barangay agricultural workers to monitor crop conditions.\n"
            "2. Identify rainfed areas with crops in vegetative/reproductive stage.\n"
            "3. Coordinate with NIA for potential supplemental irrigation.\n"
            "4. Prepare stand-by list of farmers for crop loss assistance."
        ),
        "fb_text": lambda ind, mun: (
            f"🟡 DRY SPELL ADVISORY — {mun['municipality']}\n\n"
            f"{_get_ind(ind, 'cdd', 0)} days without significant rain.\n"
            "Farmers, monitor your crops closely and irrigate if possible.\n\n"
            "#DrySpell #DARFOCagayanValley #AMIA #Agriculture"
        ),
        "responsible_office": "MAO + NIA + DA Provincial Office",
    },

    {
        "rule_id": "DROUGHT_WATCH",
        "name": "Dry Spell Watch — CDD 10–13 Days",
        "trigger_fn": lambda ind, mun: (
            10 <= _get_ind(ind, "cdd", 0) < 14
        ),
        "severity": "advisory",
        "affected_crops": ["rice_rainfed", "corn_yellow", "hvcc"],
        "affected_stages": ["vegetative"],
        "bulletin_text": lambda ind, mun: (
            f"DRY SPELL WATCH — {mun['municipality']}: "
            f"{_get_ind(ind, 'cdd', 0)} dry days. Monitor rainfed crops. "
            "Begin irrigation scheduling for sensitive growth stages. "
            "Advisories for fertilizer application: DEFER until rainfall resumes."
        ),
        "sms_text": lambda ind, mun: (
            f"DA WATCH: {_get_ind(ind, 'cdd', 0)} dry days in {mun['municipality']}. "
            "Monitor crops. Defer fertilizer application."
        ),
        "lgu_text": lambda ind, mun: (
            f"DRY SPELL WATCH — {mun['municipality']}: "
            f"{_get_ind(ind, 'cdd', 0)} days without rain. "
            "Advisory to farmers: monitor crops and coordinate with irrigation authorities."
        ),
        "fb_text": lambda ind, mun: (
            f"👀 DRY SPELL WATCH — {mun['municipality']}: "
            f"{_get_ind(ind, 'cdd', 0)} days without significant rain. "
            "Monitor your crops. #DARFOCagayanValley"
        ),
        "responsible_office": "MAO + DA Provincial Office",
    },

    # ── HEAT STRESS ──────────────────────────────────────────────────────────
    {
        "rule_id": "HEAT_DANGER",
        "name": "Dangerous Heat — WBGT Critical",
        "trigger_fn": lambda ind, mun: (
            _get_ind(ind, "heat_stress", {}).get("heat_class") == "danger"
        ),
        "severity": "danger",
        "affected_crops": ["all"],
        "affected_stages": ["all"],
        "bulletin_text": lambda ind, mun: (
            f"DANGEROUS HEAT STRESS — {mun['municipality']}: "
            f"WBGT index in danger zone. "
            "SUSPEND all field work from 9:00 AM to 4:00 PM. "
            "Ensure field workers rest in shade and drink water every 15 minutes. "
            "Monitor livestock — ensure shade, ventilation, and clean water for poultry/swine. "
            "Coordinate with RHU/BHS on heat-related illness protocols. "
            "Apply irrigation to vegetable crops early morning or late afternoon only."
        ),
        "sms_text": lambda ind, mun: (
            f"DA HEAT ALERT: Dangerous heat in {mun['municipality']}. "
            "NO farm work 9AM-4PM. Drink water. Protect livestock."
        ),
        "lgu_text": lambda ind, mun: (
            f"HEAT STRESS EMERGENCY — {mun['municipality']}\n"
            "WBGT index in dangerous range.\n"
            "1. Issue public health advisory with RHU.\n"
            "2. Restrict field labor 9AM–4PM.\n"
            "3. Coordinate BAI for livestock heat stress monitoring.\n"
            "4. Ensure water availability at farm sites."
        ),
        "fb_text": lambda ind, mun: (
            f"🌡️ HEAT DANGER ALERT — {mun['municipality']}\n\n"
            "Mapanganib na init ngayon!\n"
            "⛔ Huwag magtrabaho sa bukid mula 9AM–4PM\n"
            "💧 Uminom ng maraming tubig\n"
            "🐔 Bantayan ang mga hayop\n\n"
            "#HeatStress #DARFOCagayanValley"
        ),
        "responsible_office": "DA RFO 02 + BAI + DOH-CHD 02 + RHU",
    },

    {
        "rule_id": "HEAT_HIGH",
        "name": "High Heat Stress — Restrict Fieldwork",
        "trigger_fn": lambda ind, mun: (
            _get_ind(ind, "heat_stress", {}).get("heat_class") == "high"
        ),
        "severity": "warning",
        "affected_crops": ["all"],
        "affected_stages": ["all"],
        "bulletin_text": lambda ind, mun: (
            f"HIGH HEAT STRESS — {mun['municipality']}: "
            "Avoid prolonged field work from 10:00 AM to 2:00 PM. "
            "Ensure adequate hydration for farm workers. "
            "Monitor heat-sensitive crops (vegetables, high-value crops). "
            "Reschedule spraying and transplanting to early morning hours. "
            "Check livestock ventilation and water supply."
        ),
        "sms_text": lambda ind, mun: (
            f"DA ADVISORY: High heat in {mun['municipality']}. "
            "Avoid farm work 10AM-2PM. Stay hydrated."
        ),
        "lgu_text": lambda ind, mun: (
            f"HEAT STRESS ADVISORY — {mun['municipality']}\n"
            "High heat conditions: schedule farm work early morning or late afternoon."
        ),
        "fb_text": lambda ind, mun: (
            f"☀️ HEAT ADVISORY — {mun['municipality']}: "
            "High heat conditions. Avoid fieldwork 10AM–2PM. "
            "#DARFOCagayanValley #HeatStress"
        ),
        "responsible_office": "MAO + RHU",
    },

    # ── AGRONOMIC OPERATIONS ─────────────────────────────────────────────────
    {
        "rule_id": "FERTILIZER_DEFER",
        "name": "Defer Fertilizer Application — Rain Risk",
        "trigger_fn": lambda ind, mun: (
            (ind.get("observations", {}).get("rainfall_24h_mm") or 0) >= 15
            or (ind.get("observations", {}).get("rainfall_48h_mm") or 0) >= 25
        ),
        "severity": "advisory",
        "affected_crops": ["rice_irrigated", "rice_rainfed", "corn_yellow"],
        "affected_stages": ["vegetative", "reproductive"],
        "bulletin_text": lambda ind, mun: (
            f"FERTILIZER APPLICATION ADVISORY — {mun['municipality']}: "
            "Current rainfall conditions increase risk of nutrient loss through leaching "
            "and runoff. DEFER basal and top-dress fertilizer application until 2–3 dry "
            "days are observed. Consider split-application strategy when conditions improve. "
            "For critical growth stages, consult AEW/MAO before proceeding."
        ),
        "sms_text": lambda ind, mun: (
            "DA ADVISORY: Do not apply fertilizer today due to rain risk. "
            "Wait 2-3 dry days. Less waste, better yield."
        ),
        "lgu_text": lambda ind, mun: (
            f"AGRI-OPERATIONS ADVISORY — {mun['municipality']}\n"
            "Advise farmers to postpone fertilizer application. "
            "Rain will reduce fertilizer efficacy and increase runoff to waterways."
        ),
        "fb_text": lambda ind, mun: (
            f"🌱 FERTILIZER REMINDER — {mun['municipality']}:\n"
            "Hindi magandang maglagay ng pataba ngayon dahil may ulan. "
            "Maghintay ng 2–3 araw na tuyo para mas epektibo ang pataba. "
            "#PatubaAdvice #DARFOCagayanValley"
        ),
        "responsible_office": "MAO + Municipal AEW",
    },

    {
        "rule_id": "SPRAYING_DEFER",
        "name": "Defer Pesticide/Foliar Spraying",
        "trigger_fn": lambda ind, mun: (
            (ind.get("observations", {}).get("rainfall_24h_mm") or 0) >= 10
            or (ind.get("observations", {}).get("rainfall_48h_mm") or 0) >= 20
        ),
        "severity": "advisory",
        "affected_crops": ["all"],
        "affected_stages": ["vegetative", "reproductive"],
        "bulletin_text": lambda ind, mun: (
            f"SPRAYING ADVISORY — {mun['municipality']}: "
            "Do not apply pesticides or foliar fertilizers in rainy conditions. "
            "Rain within 4–6 hours of application will wash off chemicals, "
            "reducing efficacy and increasing environmental contamination risk. "
            "Reschedule spraying to early morning hours on clear days."
        ),
        "sms_text": lambda ind, mun: (
            "DA ADVISORY: Do not spray pesticides when raining. "
            "Reschedule to clear morning. Saves money, protects water."
        ),
        "lgu_text": lambda ind, mun: (
            f"SPRAYING ADVISORY — {mun['municipality']}: "
            "Rainfall expected. Advise farmers to defer all pesticide and foliar spraying."
        ),
        "fb_text": lambda ind, mun: (
            f"🚫 SPRAYING ADVISORY — {mun['municipality']}: "
            "Huwag mag-spray ng pesticide habang may ulan. "
            "Mag-schedule sa maliwanag na umaga. #PestControl #DARFOCagayanValley"
        ),
        "responsible_office": "MAO + PLGU Agricultural Division",
    },

    # ── RAINFALL ANOMALY ─────────────────────────────────────────────────────
    {
        "rule_id": "BELOW_NORMAL_RAINFALL",
        "name": "Below-Normal Monthly Rainfall",
        "trigger_fn": lambda ind, mun: (
            _get_ind(ind, "rainfall_anomaly", {}).get("anomaly_class") in ("below", "far_below")
        ),
        "severity": "advisory",
        "affected_crops": ["rice_rainfed", "corn_yellow"],
        "affected_stages": ["vegetative", "reproductive"],
        "bulletin_text": lambda ind, mun: (
            f"BELOW-NORMAL RAINFALL ADVISORY — {mun['municipality']}: "
            f"Rainfall this month is at "
            f"{_get_ind(ind, 'rainfall_anomaly', {}).get('pct_of_normal', 'N/A')}% of normal. "
            "Rainfed crop areas face increased drought risk. "
            "Recommend: (1) Prioritize drought-tolerant varieties for next planting; "
            "(2) Identify water sources for supplemental irrigation; "
            "(3) Maintain crop residue cover to conserve soil moisture; "
            "(4) Monitor PAGASA seasonal outlook for extended dry spell risk."
        ),
        "sms_text": lambda ind, mun: (
            f"DA INFO: Rainfall in {mun['municipality']} is below normal this month. "
            "Monitor crops and prepare for possible drought."
        ),
        "lgu_text": lambda ind, mun: (
            f"BELOW-NORMAL RAINFALL NOTICE — {mun['municipality']}\n"
            f"Monthly rainfall at {_get_ind(ind, 'rainfall_anomaly', {}).get('pct_of_normal', 'N/A')}% "
            "of 30-year average. Coordinate with DA for drought preparedness."
        ),
        "fb_text": lambda ind, mun: (
            f"📊 RAINFALL UPDATE — {mun['municipality']}:\n"
            f"Ang ulan ngayong buwan ay mababa kaysa karaniwan "
            f"({_get_ind(ind, 'rainfall_anomaly', {}).get('pct_of_normal', 'N/A')}% ng normal). "
            "Bantayan ang inyong mga pananim. #Ulan #DARFOCagayanValley"
        ),
        "responsible_office": "DA RFO 02 RAED + MAO",
    },
]


# ═══════════════════════════════════════════════════════════════════════════════
# 2. ADVISORY EVALUATION ENGINE
# ═══════════════════════════════════════════════════════════════════════════════

def evaluate_municipality(
    indicators: Dict,
    mun: Dict,
) -> List[Dict]:
    """
    Run all advisory rules against a municipality's indicators.

    Returns:
        List of triggered advisory dicts, sorted by severity.
    """
    triggered = []
    severity_order = {"danger": 0, "warning": 1, "advisory": 2, "info": 3}

    for rule in ADVISORY_RULES:
        try:
            if rule["trigger_fn"](indicators, mun):
                calendar_anchor = _calendar_anchor_for_rule(indicators, rule)
                advisory = {
                    "rule_id": rule["rule_id"],
                    "rule_name": rule["name"],
                    "severity": rule["severity"],
                    "affected_crops": rule["affected_crops"],
                    "affected_stages": rule["affected_stages"],
                    "calendar_anchor": calendar_anchor,
                    "responsible_office": rule["responsible_office"],
                    "adaptation_measures": _cra_measures_for_rule(rule["rule_id"]),
                    "adaptation_source": CRA_MEASURES.get("meta", {}).get("source", "CRA Compendium"),
                    "texts": {
                        "bulletin": rule["bulletin_text"](indicators, mun),
                        "sms": rule["sms_text"](indicators, mun),
                        "lgu": rule["lgu_text"](indicators, mun),
                        "facebook": rule["fb_text"](indicators, mun),
                    },
                }
                triggered.append(advisory)
        except Exception as exc:
            logger.warning(f"Rule {rule['rule_id']} error for {mun.get('municipality')}: {exc}")

    triggered.extend(_generate_operation_defer_advisories(indicators, mun))

    # Sort by severity (most critical first)
    triggered.sort(key=lambda a: severity_order.get(a["severity"], 99))
    return triggered


def _parse_date(value) -> Optional[date]:
    if not value:
        return None
    if isinstance(value, date):
        return value
    text = str(value).replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        try:
            return date.fromisoformat(str(value)[:10])
        except ValueError:
            return None


def _days_old(value, ref_date: date) -> Optional[int]:
    parsed = _parse_date(value)
    if not parsed:
        return None
    return max(0, (ref_date - parsed).days)


def _source_label(source: str) -> str:
    labels = {
        "apa_cis": "APA CIS",
        "up_noah": "UP NOAH",
        "chirps": "CHIRPS",
        "nasa_power": "NASA POWER",
    }
    return labels.get(source or "", source or "unknown")


def _source_age(indicators: Dict, ref_date: date) -> Dict:
    obs = indicators.get("observations", {})
    hazards = indicators.get("official_hazards", {})
    rainfall_source = obs.get("rainfall_source") or indicators.get("data_sources", {}).get("rainfall_used")
    if rainfall_source == "apa_cis":
        source_date = obs.get("apa_cis_record_date") or indicators.get("as_of_date")
    elif rainfall_source == "up_noah":
        source_date = obs.get("up_noah_record_date") or indicators.get("as_of_date")
    elif rainfall_source == "chirps":
        source_date = obs.get("chirps_record_date") or indicators.get("as_of_date")
    else:
        source_date = indicators.get("as_of_date")

    return {
        "weather_source": _source_label(indicators.get("data_sources", {}).get("weather")),
        "rainfall_source": _source_label(rainfall_source),
        "rainfall_source_date": source_date,
        "rainfall_age_days": _days_old(source_date, ref_date),
        "pagasa_source_date": hazards.get("pagasa_source_date"),
        "pagasa_age_days": _days_old(hazards.get("pagasa_source_date"), ref_date),
        "acap_source_date": hazards.get("acap_ten_day_source_date"),
        "acap_age_days": _days_old(hazards.get("acap_ten_day_source_date"), ref_date),
    }


def _source_qa_flags(indicators: Dict, ref_date: date) -> List[str]:
    flags = []
    obs = indicators.get("observations", {})
    hazards = indicators.get("official_hazards", {})
    source_age = _source_age(indicators, ref_date)

    rainfall_source = (obs.get("rainfall_source") or "").lower()
    if rainfall_source == "nasa_power":
        flags.append("Rainfall is NASA POWER fallback; treat as lower-confidence local observation.")
    if source_age["rainfall_age_days"] is None:
        flags.append("Rainfall source date unavailable.")
    elif source_age["rainfall_age_days"] > 1 and rainfall_source in ("apa_cis", "up_noah", "chirps"):
        flags.append(f"Rainfall source is {source_age['rainfall_age_days']} days old.")
    if not hazards.get("acap_ten_day_available"):
        flags.append("ACAP 10-day forecast not available for this province.")
    if hazards.get("review_status") in (None, "unreviewed", "default_fallback"):
        flags.append("PAGASA context needs staff review before official dissemination.")
    if obs.get("rainfall_24h_mm") is None:
        flags.append("24-hour rainfall missing.")
    if obs.get("tmax_c") is None:
        flags.append("Maximum temperature missing.")
    return flags or ["Sources passed automated freshness and completeness checks."]


def _confidence_from_flags(flags: List[str], indicators: Dict) -> str:
    source = (indicators.get("observations", {}).get("rainfall_source") or "").lower()
    blocker_flags = [flag for flag in flags if "missing" in flag.lower() or "unavailable" in flag.lower()]
    review_flags = [flag for flag in flags if "review" in flag.lower() or "fallback" in flag.lower()]
    if source in ("apa_cis", "up_noah") and not blocker_flags and not review_flags:
        return "high"
    if blocker_flags or source == "nasa_power":
        return "low"
    return "medium"


def _valid_until(ref_date: date) -> str:
    return (ref_date + timedelta(days=1)).isoformat()


def _decision_support_for_municipality(
    indicators: Dict,
    adv_data: Dict,
    ref_date: date,
) -> Dict:
    advisories = adv_data.get("advisories", [])
    primary = advisories[0] if advisories else {}
    crop_risk = indicators.get("indicators", {}).get("crop_stage_risk", {})
    calendar_context = indicators.get("indicators", {}).get("crop_calendar_context", {})
    calendar_anchor = primary.get("calendar_anchor") or {
        "anchored": False,
        "period": calendar_context.get("period_label"),
        "matched_current_stages": calendar_context.get("current_stages", []),
        "note": calendar_context.get("note"),
    }
    official = indicators.get("official_hazards", {})
    flags = _source_qa_flags(indicators, ref_date)
    source_age = _source_age(indicators, ref_date)

    return {
        "hazard": primary.get("rule_name", "No active advisory"),
        "severity": adv_data.get("highest_severity", "none"),
        "confidence": _confidence_from_flags(flags, indicators),
        "source_age": source_age,
        "source_qa_flags": flags,
        "official_pagasa_warning": {
            "typhoon_active": bool(official.get("typhoon_active")),
            "typhoon_name": official.get("typhoon_name"),
            "tcws_signal": official.get("tcws_signal", 0),
            "pagasa_source_date": official.get("pagasa_source_date"),
            "review_status": official.get("review_status"),
        },
        "affected_crop_stage": {
            "crop": crop_risk.get("crop") or (primary.get("affected_crops") or ["all"])[0],
            "stage": crop_risk.get("crop_stage") or (primary.get("affected_stages") or ["all"])[0],
            "risk_class": crop_risk.get("risk_class"),
            "risk_score": crop_risk.get("risk_score"),
            "calendar_anchored": crop_risk.get("calendar_anchored", False),
            "calendar_crop": crop_risk.get("calendar_crop"),
            "calendar_stage": crop_risk.get("calendar_stage"),
            "calendar_stage_label": crop_risk.get("calendar_stage_label"),
            "calendar_season": crop_risk.get("calendar_season"),
            "calendar_period": crop_risk.get("calendar_period") or calendar_context.get("period_label"),
            "calendar_anchor": calendar_anchor,
            "current_rice_corn_stages": calendar_context.get("current_stages", []),
            "acap_crop_calendar_available": official.get("acap_crop_calendar_available", False),
            "crop_calendar_decision_point": official.get("crop_calendar_decision_point"),
        },
        "immediate_farmer_action": primary.get("texts", {}).get("sms")
            or primary.get("texts", {}).get("bulletin")
            or "Continue monitoring and follow MAO/DA advisories.",
        "lgu_da_action": primary.get("texts", {}).get("lgu")
            or "MAO/DA field staff should verify local conditions and prepare advisory dissemination.",
        "public_advisory": primary.get("texts", {}).get("facebook")
            or "Monitor official DA-RFO2 APA and PAGASA updates.",
        "sms_ready": primary.get("texts", {}).get("sms", ""),
        "when_to_recheck": "Re-check after the next 6:00 AM PHT pipeline run, and immediately when PAGASA issues or updates warnings.",
        "valid_until": _valid_until(ref_date),
    }


def _summarise_sources(data: Dict, ref_date: date) -> Dict:
    source_counts = {}
    confidence_counts = {"high": 0, "medium": 0, "low": 0}
    pagasa_dates = set()
    acap_dates = set()
    qa_flags = {}

    for indicators in data.values():
      obs = indicators.get("observations", {})
      source = obs.get("rainfall_source") or "unknown"
      source_counts[source] = source_counts.get(source, 0) + 1
      flags = _source_qa_flags(indicators, ref_date)
      confidence_counts[_confidence_from_flags(flags, indicators)] += 1
      for flag in flags:
          qa_flags[flag] = qa_flags.get(flag, 0) + 1
      hazards = indicators.get("official_hazards", {})
      if hazards.get("pagasa_source_date"):
          pagasa_dates.add(str(hazards.get("pagasa_source_date"))[:10])
      if hazards.get("acap_ten_day_source_date"):
          acap_dates.add(str(hazards.get("acap_ten_day_source_date"))[:10])

    return {
        "rainfall_source_counts": source_counts,
        "confidence_counts": confidence_counts,
        "pagasa_source_dates": sorted(pagasa_dates),
        "acap_source_dates": sorted(acap_dates),
        "top_qa_flags": sorted(qa_flags.items(), key=lambda item: item[1], reverse=True)[:5],
    }


def generate_all_advisories(indicators_data: Dict) -> Dict:
    """
    Generate advisories for all municipalities.

    Args:
        indicators_data: Output from compute_indicators.run()

    Returns:
        Advisory report dict
    """
    municipalities = {m["psgc"]: m for m in load_municipalities()}
    ref_date = today_pht()

    report = {
        "meta": {
            "generated_at": __import__("datetime").datetime.utcnow().isoformat(),
            "advisory_date": ref_date.isoformat(),
            "total_municipalities": 0,
            "municipalities_with_advisories": 0,
            "danger_count": 0,
            "warning_count": 0,
        },
        "advisories": {},
        "summary_by_province": {},
        "priority_municipalities": [],
    }

    data = indicators_data.get("data", {})
    report["meta"]["total_municipalities"] = len(data)
    report["source_summary"] = _summarise_sources(data, ref_date)

    for psgc, indicators in data.items():
        mun = _normalise_municipality(municipalities.get(psgc, {}))
        if not mun:
            continue

        advisories = evaluate_municipality(indicators, mun)
        if advisories:
            report["advisories"][psgc] = {
                "municipality": mun["municipality"],
                "province": mun["province"],
                "advisory_count": len(advisories),
                "highest_severity": advisories[0]["severity"],
                "advisories": advisories,
            }
            report["advisories"][psgc]["decision_support"] = _decision_support_for_municipality(
                indicators,
                report["advisories"][psgc],
                ref_date,
            )
            report["meta"]["municipalities_with_advisories"] += 1
            if advisories[0]["severity"] == "danger":
                report["meta"]["danger_count"] += 1
            elif advisories[0]["severity"] == "warning":
                report["meta"]["warning_count"] += 1

    # Province summary
    from scripts.utils import PROVINCES
    for province in PROVINCES:
        prov_advisories = [
            v for v in report["advisories"].values()
            if v["province"] == province
        ]
        report["summary_by_province"][province] = {
            "municipalities_with_advisories": len(prov_advisories),
            "highest_severity": prov_advisories[0]["highest_severity"]
                if prov_advisories else "none",
            "danger_count": sum(1 for a in prov_advisories if a["highest_severity"] == "danger"),
            "warning_count": sum(1 for a in prov_advisories if a["highest_severity"] == "warning"),
        }

    # Priority municipalities (by risk score + severity)
    priority = []
    for psgc, adv_data in report["advisories"].items():
        ind = data.get(psgc, {})
        priority.append({
            "psgc": psgc,
            "municipality": adv_data["municipality"],
            "province": adv_data["province"],
            "severity": adv_data["highest_severity"],
            "confidence": adv_data.get("decision_support", {}).get("confidence", "unknown"),
            "advisory_count": adv_data["advisory_count"],
            "risk_score": ind.get("indicators", {}).get("municipal_risk_score", 0),
            "primary_advisory": adv_data["advisories"][0]["rule_name"]
                if adv_data["advisories"] else "",
            "farmer_action": adv_data.get("decision_support", {}).get("immediate_farmer_action", ""),
            "lgu_da_action": adv_data.get("decision_support", {}).get("lgu_da_action", ""),
        })

    severity_order = {"danger": 0, "warning": 1, "advisory": 2, "info": 3}
    priority.sort(key=lambda x: (severity_order.get(x["severity"], 99), -x["risk_score"]))
    report["priority_municipalities"] = priority[:20]  # Top 20

    return report


def generate_regional_bulletin(report: Dict) -> str:
    """
    Generate a single regional advisory bulletin text from the advisory report.
    Suitable for DA RFO 02 official communications.
    """
    today = report["meta"]["advisory_date"]
    danger = report["meta"]["danger_count"]
    warning = report["meta"]["warning_count"]
    total_adv = report["meta"]["municipalities_with_advisories"]
    source_summary = report.get("source_summary", {})
    source_counts = source_summary.get("rainfall_source_counts", {})
    confidence_counts = source_summary.get("confidence_counts", {})
    pagasa_dates = ", ".join(source_summary.get("pagasa_source_dates", [])) or "not available"
    acap_dates = ", ".join(source_summary.get("acap_source_dates", [])) or "not available"

    lines = [
        f"DA RFO 02 REGIONAL AGRICULTURAL ADVISORY",
        f"Date: {today}",
        f"Valid until: {(date.fromisoformat(today) + timedelta(days=1)).isoformat()}, unless superseded by newer PAGASA/DA-RFO2 APA updates",
        f"Coverage: Cagayan Valley (Region 02)",
        f"Issued by: {ISSUER}",
        "=" * 60,
        f"\nSITUATION OVERVIEW:",
        f"  Active advisories: {total_adv} municipalities",
        f"  Danger alerts: {danger}",
        f"  Warnings: {warning}",
        f"  Confidence: high {confidence_counts.get('high', 0)}, medium {confidence_counts.get('medium', 0)}, low {confidence_counts.get('low', 0)}",
        "",
    ]

    lines.extend([
        "SOURCE TIMESTAMPS AND QA:",
        f"  APA CIS rainfall municipalities: {source_counts.get('apa_cis', 0)}",
        f"  UP NOAH rainfall municipalities: {source_counts.get('up_noah', 0)}",
        f"  CHIRPS rainfall municipalities: {source_counts.get('chirps', 0)}",
        f"  NASA POWER fallback municipalities: {source_counts.get('nasa_power', 0)}",
        f"  PAGASA source date(s): {pagasa_dates}",
        f"  ACAP 10-day source date(s): {acap_dates}",
    ])
    for flag, count in source_summary.get("top_qa_flags", []):
        lines.append(f"  QA flag ({count} municipalities): {flag}")
    lines.append("")

    lines.extend([
        "PAGASA / ACAP / CIS SUMMARY:",
        "  PAGASA warnings are integrated where TCWS, ENSO, seasonal outlook, or farm-weather context is available.",
        "  ACAP 10-day provincial forecast and crop-calendar references are used as planning context.",
        "  APA CIS is prioritized first; UP NOAH sampled weather overlays are second; CHIRPS/NASA remain fallbacks.",
        "",
    ])

    # Provincial summaries
    lines.append("PROVINCIAL STATUS:")
    for province, summary in report["summary_by_province"].items():
        if summary["municipalities_with_advisories"] > 0:
            lines.append(
                f"  {province}: {summary['municipalities_with_advisories']} municipalities "
                f"with advisories (highest: {summary['highest_severity'].upper()})"
            )

    # Priority municipalities
    if report["priority_municipalities"]:
        lines.append("\nPRIORITY MUNICIPALITIES FOR IMMEDIATE ACTION:")
        for i, mun in enumerate(report["priority_municipalities"][:10], 1):
            lines.append(
                f"  {i}. {mun['municipality']}, {mun['province']} "
                f"[{mun['severity'].upper()}, confidence: {mun.get('confidence', 'unknown')}] - {mun['primary_advisory']}"
            )

    lines.extend([
        "",
        "ACTION TIERS:",
        "  Farmers: Follow the municipal advisory SMS/action text; adjust field work, irrigation, spraying, harvest, and drying based on local MAO guidance.",
        "  LGUs / MAOs: Verify barangay-level field conditions, disseminate SMS advisories, and report affected farmers/hectares to DA-RFO2 APA.",
        "  DA Operations: Prioritize validation teams, irrigation coordination, postharvest support, seeds, crop protection, and PCIC coordination in danger/warning municipalities.",
        "  Public: Monitor DA RFO2 APA and PAGASA updates; avoid sharing unofficial advisories without source date and valid-until information.",
    ])

    if report["priority_municipalities"]:
        lines.append("\nSMS-READY PRIORITY ADVISORIES:")
        for mun in report["priority_municipalities"][:5]:
            sms = (mun.get("farmer_action") or "").replace("\n", " ")
            lines.append(f"  {mun['municipality']}: {sms[:160]}")

    lines.extend([
        "",
        "For full advisory details, visit the APA-CIS portal.",
        f"For assistance, contact {ISSUER}: {ASSISTANCE_CONTACT}; {ASSISTANCE_FACEBOOK}; {ASSISTANCE_EMAIL}.",
        f"\nEnd of Advisory - {today}",
    ])

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
# 3. SAVE AND EXPORT
# ═══════════════════════════════════════════════════════════════════════════════

def save_advisory_outputs(report: Dict) -> None:
    ref_date = today_pht()

    # Full advisory JSON
    adv_path = PROJECT_ROOT / cfg["paths"]["advisories_daily"]
    daily_file = adv_path / f"advisories_{ref_date.isoformat()}.json"
    latest_file = adv_path / "advisories_latest.json"
    save_json(report, daily_file)
    save_json(report, latest_file)
    logger.info(f"Advisory report saved → {latest_file}")

    # Regional bulletin text
    bulletin = generate_regional_bulletin(report)
    bulletin_file = adv_path / f"regional_bulletin_{ref_date.isoformat()}.txt"
    bulletin_latest = adv_path / "regional_bulletin_latest.txt"
    with open(bulletin_file, "w") as f:
        f.write(bulletin)
    with open(bulletin_latest, "w") as f:
        f.write(bulletin)
    logger.info(f"Regional bulletin saved → {bulletin_latest}")

    # GeoJSON for advisory map layer
    _save_advisory_geojson(report)


def _save_advisory_geojson(report: Dict) -> None:
    municipalities = {m["psgc"]: m for m in load_municipalities()}
    features = []
    severity_color = {
        "danger": "#B71C1C", "warning": "#FF5722",
        "advisory": "#FF9800", "info": "#2196F3", "none": "#4CAF50",
    }

    for psgc, mun in municipalities.items():
        adv_data = report["advisories"].get(psgc, {})
        severity = adv_data.get("highest_severity", "none")
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [mun["lon"], mun["lat"]]},
            "properties": {
                "psgc": psgc,
                "municipality": mun["name"],
                "province": mun["province"],
                "severity": severity,
                "advisory_count": adv_data.get("advisory_count", 0),
                "primary_advisory": adv_data.get("advisories", [{}])[0].get("rule_name", "")
                    if adv_data.get("advisories") else "",
                "color": severity_color.get(severity, "#9E9E9E"),
            },
        })

    geojson = {"type": "FeatureCollection", "features": features}
    geo_path = PROJECT_ROOT / cfg["paths"]["geospatial"] / "advisory_status.geojson"
    save_json(geojson, geo_path)
    logger.info(f"Advisory GeoJSON saved → {geo_path}")


# ═══════════════════════════════════════════════════════════════════════════════
# 4. ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════════

def run() -> None:
    logger.info("=== APA-CIS Advisory Engine ===")

    # Load latest indicators
    ind_path = PROJECT_ROOT / cfg["paths"]["indicators"] / "indicators_latest.json"
    indicators_data = load_json(ind_path)
    if not indicators_data:
        logger.error(f"No indicator data found at {ind_path}. Run indicator engine first.")
        return

    report = generate_all_advisories(indicators_data)
    save_advisory_outputs(report)

    mwadv = report["meta"]["municipalities_with_advisories"]
    logger.info(
        f"=== Advisory engine complete — "
        f"{mwadv} municipalities with active advisories ==="
    )

    log_etl_event(
        source="advisory_engine",
        run_date=today_pht().isoformat(),
        records_fetched=report["meta"]["total_municipalities"],
        records_valid=mwadv,
        status="success",
        message=f"Danger: {report['meta']['danger_count']}, "
                f"Warning: {report['meta']['warning_count']}",
    )


if __name__ == "__main__":
    run()
