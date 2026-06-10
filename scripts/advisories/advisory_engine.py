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
from datetime import date
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
                advisory = {
                    "rule_id": rule["rule_id"],
                    "rule_name": rule["name"],
                    "severity": rule["severity"],
                    "affected_crops": rule["affected_crops"],
                    "affected_stages": rule["affected_stages"],
                    "responsible_office": rule["responsible_office"],
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

    # Sort by severity (most critical first)
    triggered.sort(key=lambda a: severity_order.get(a["severity"], 99))
    return triggered


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
            "advisory_count": adv_data["advisory_count"],
            "risk_score": ind.get("indicators", {}).get("municipal_risk_score", 0),
            "primary_advisory": adv_data["advisories"][0]["rule_name"]
                if adv_data["advisories"] else "",
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

    lines = [
        f"DA RFO 02 REGIONAL AGRICULTURAL ADVISORY",
        f"Date: {today}",
        f"Coverage: Cagayan Valley (Region 02)",
        f"Issued by: DA RFO 02 — Regional Agricultural Extension Division (RAED)",
        "=" * 60,
        f"\nSITUATION OVERVIEW:",
        f"  Active advisories: {total_adv} municipalities",
        f"  Danger alerts: {danger}",
        f"  Warnings: {warning}",
        "",
    ]

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
                f"[{mun['severity'].upper()}] — {mun['primary_advisory']}"
            )

    lines.extend([
        "",
        "For full advisory details, visit the APA-CIS portal.",
        "For assistance, contact DA RFO 02 at (078) 844-1228 / (078) 396-0558.",
        f"\nEnd of Advisory — {today}",
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
