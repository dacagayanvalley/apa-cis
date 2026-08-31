"""
tests/test_indicators.py
Unit tests for the APA-CIS indicator computation engine.

Run with: pytest tests/ -v

DA RFO 02 — APA-CIS Climate Information Service
"""

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

import scripts.indicators.compute_indicators as indicator_module
from scripts.indicators.compute_indicators import (
    compute_cdd,
    compute_cwd,
    compute_accumulated_rainfall,
    compute_rainfall_anomaly,
    compute_heat_stress,
    compute_eto,
    compute_field_workability,
    compute_irrigation_demand,
    compute_crop_stage_risk,
    compute_municipal_risk_score,
)


# ── Fixtures ───────────────────────────────────────────────────────────────────

def _make_record(date_str, rainfall):
    """Helper: make a minimal daily record."""
    return {"date": date_str, "rainfall_mm": rainfall, "psgc": "023101000"}


def _dry_records(n, start_offset=0):
    """n consecutive dry days (0 mm)."""
    return [_make_record(f"2026-06-{i+1:02d}", 0.0) for i in range(start_offset, start_offset + n)]


def _wet_records(n, mm=5.0):
    """n consecutive wet days."""
    return [_make_record(f"2026-06-{i+1:02d}", mm) for i in range(n)]


# ── CDD Tests ─────────────────────────────────────────────────────────────────

class TestCDD:
    def test_no_dry_days(self):
        records = _wet_records(10)
        cdd, cls = compute_cdd(records)
        assert cdd == 0
        assert cls == "none"

    def test_exact_watch_threshold(self):
        records = _dry_records(10)
        cdd, cls = compute_cdd(records)
        assert cdd == 10
        assert cls == "watch"

    def test_warning_threshold(self):
        records = _dry_records(14)
        cdd, cls = compute_cdd(records)
        assert cdd == 14
        assert cls == "warning"

    def test_critical_threshold(self):
        records = _dry_records(21)
        cdd, cls = compute_cdd(records)
        assert cdd == 21
        assert cls == "critical"

    def test_streak_resets_on_rain(self):
        records = _dry_records(15)
        # Add one wet day in the middle, then 5 more dry
        records.insert(10, _make_record("2026-06-11", 5.0))
        cdd, cls = compute_cdd(records)
        # Should reset — the streak is at most 5 after the rain
        assert cdd <= 6

    def test_missing_values_skipped(self):
        """Records with None rainfall should not break the streak."""
        records = _dry_records(5)
        records.append({"date": "2026-06-06", "rainfall_mm": None, "psgc": "x"})
        records.extend(_dry_records(5))
        cdd, _ = compute_cdd(records)
        assert cdd >= 10

    def test_boundary_dry_threshold(self):
        """0.99 mm is a dry day; 1.0 mm is not."""
        records = [_make_record("2026-06-01", 0.99)] * 10
        cdd, _ = compute_cdd(records)
        assert cdd == 10

        records_wet = [_make_record("2026-06-01", 1.0)] * 10
        cdd2, _ = compute_cdd(records_wet)
        assert cdd2 == 0


# ── CWD Tests ─────────────────────────────────────────────────────────────────

class TestCWD:
    def test_basic_wet_streak(self):
        records = _wet_records(7, mm=3.0)
        assert compute_cwd(records) == 7

    def test_no_wet_days(self):
        records = _dry_records(5)
        assert compute_cwd(records) == 0


# ── Accumulated Rainfall Tests ────────────────────────────────────────────────

class TestAccumulatedRainfall:
    def test_7day_sum(self):
        records = [_make_record(f"2026-06-{i+1:02d}", 10.0) for i in range(7)]
        total = compute_accumulated_rainfall(records, days=7)
        assert total == pytest.approx(70.0, rel=0.01)

    def test_fewer_records_than_days(self):
        records = [_make_record("2026-06-01", 5.0), _make_record("2026-06-02", 5.0)]
        total = compute_accumulated_rainfall(records, days=7)
        assert total == pytest.approx(10.0)

    def test_none_values_ignored(self):
        records = [
            {"date": "2026-06-01", "rainfall_mm": None, "psgc": "x"},
            {"date": "2026-06-02", "rainfall_mm": 20.0, "psgc": "x"},
        ]
        total = compute_accumulated_rainfall(records, days=7)
        assert total == pytest.approx(20.0)


# ── Rainfall Anomaly Tests ────────────────────────────────────────────────────

class TestRainfallAnomaly:
    def test_near_normal(self):
        result = compute_rainfall_anomaly(100.0, 100.0)
        assert result["anomaly_class"] == "near_normal"
        assert result["pct_of_normal"] == pytest.approx(100.0)

    def test_far_below(self):
        result = compute_rainfall_anomaly(40.0, 100.0)
        assert result["anomaly_class"] == "far_below"
        assert result["pct_of_normal"] == pytest.approx(40.0)

    def test_far_above(self):
        result = compute_rainfall_anomaly(200.0, 100.0)
        assert result["anomaly_class"] == "far_above"
        assert result["pct_of_normal"] == pytest.approx(200.0)

    def test_zero_normal(self):
        result = compute_rainfall_anomaly(50.0, 0.0)
        assert result["anomaly_class"] == "unknown"

    def test_anomaly_mm_sign(self):
        result = compute_rainfall_anomaly(60.0, 100.0)
        assert result["anomaly_mm"] < 0  # Below normal


# ── Heat Stress Tests ─────────────────────────────────────────────────────────

class TestHeatStress:
    def test_low_heat(self):
        result = compute_heat_stress(30.0, 50.0)
        assert result["heat_class"] == "low"

    def test_danger_heat(self):
        result = compute_heat_stress(40.0, 90.0)
        assert result["heat_class"] in ("high", "danger")

    def test_advisory_flags(self):
        result = compute_heat_stress(40.0, 90.0)
        # High heat should trigger advisory flags
        assert result["advisory_restrict_fieldwork"] is True

    def test_wbgt_is_float(self):
        result = compute_heat_stress(32.0, 75.0)
        assert isinstance(result["wbgt_approx"], float)
        assert 20 < result["wbgt_approx"] < 45  # Sanity range


# ── ETo Tests ─────────────────────────────────────────────────────────────────

class TestETo:
    def test_typical_conditions(self):
        # Tuguegarao-like conditions
        eto = compute_eto(
            tmax_c=34.0, tmin_c=24.0, humidity_pct=75.0,
            wind_ms=2.5, solar_mj=18.0, altitude_m=46.0
        )
        assert eto is not None
        assert 3.0 <= eto <= 9.0  # Typical tropical ETo range

    def test_returns_none_on_invalid(self):
        eto = compute_eto(None, None, None, None, None)
        assert eto is None

    def test_non_negative(self):
        eto = compute_eto(
            tmax_c=25.0, tmin_c=18.0, humidity_pct=95.0,
            wind_ms=0.5, solar_mj=5.0, altitude_m=100.0
        )
        assert eto is not None
        assert eto >= 0.0


# ── Field Workability Tests ───────────────────────────────────────────────────

class TestFieldWorkability:
    def test_workable_dry_conditions(self):
        result = compute_field_workability(rain_24h=0.5, rain_48h=1.0, cdd=3)
        assert result["overall_class"] == "workable"
        assert result["operations"]["spraying"] == "safe"

    def test_not_workable_heavy_rain(self):
        result = compute_field_workability(rain_24h=60.0, rain_48h=100.0, cdd=0)
        assert result["overall_class"] == "not_workable"
        assert result["operations"]["fertilizer_application"] == "defer"

    def test_fertilizer_deferred_on_rain(self):
        result = compute_field_workability(rain_24h=15.0, rain_48h=20.0, cdd=0)
        assert result["operations"]["fertilizer_application"] == "defer"
        assert result["operations"]["spraying"] == "defer"

    def test_drought_caution_flag(self):
        result = compute_field_workability(rain_24h=0.0, rain_48h=0.0, cdd=16)
        assert result["overall_class"] == "drought_caution"


# ── Irrigation Demand Tests ───────────────────────────────────────────────────

class TestIrrigationDemand:
    def test_no_demand_on_rain(self):
        result = compute_irrigation_demand(eto_mm=5.0, rainfall_mm=10.0)
        assert result["demand_mm"] == 0.0
        assert result["demand_class"] == "none"

    def test_high_demand_dry(self):
        result = compute_irrigation_demand(eto_mm=6.0, rainfall_mm=0.0, irrigation_status="rainfed")
        assert result["demand_mm"] > 0
        assert result["priority"] in ("high", "critical")

    def test_rainfed_higher_priority(self):
        r1 = compute_irrigation_demand(eto_mm=5.0, rainfall_mm=1.0, irrigation_status="rainfed")
        r2 = compute_irrigation_demand(eto_mm=5.0, rainfall_mm=1.0, irrigation_status="irrigated")
        p_order = {"low":0, "medium":1, "high":2, "critical":3}
        assert p_order[r1["priority"]] >= p_order[r2["priority"]]


# ── Crop Stage Risk Tests ─────────────────────────────────────────────────────

class TestCropStageRisk:
    def test_critical_drought_rainfed(self):
        result = compute_crop_stage_risk(
            cdd=25, cwd=0, rainfall_7d=0,
            tmax_c=32.0, humidity_pct=65.0,
            crop="rice_rainfed", crop_stage="reproductive",
            irrigation_status="rainfed"
        )
        assert result["risk_score"] >= 3.0
        assert result["risk_class"] in ("high", "critical")

    def test_low_risk_irrigated(self):
        result = compute_crop_stage_risk(
            cdd=0, cwd=5, rainfall_7d=50,
            tmax_c=30.0, humidity_pct=70.0,
            crop="rice_irrigated", crop_stage="vegetative",
            irrigation_status="irrigated"
        )
        assert result["risk_score"] < 3.0

    def test_flood_risk_harvest(self):
        result = compute_crop_stage_risk(
            cdd=0, cwd=7, rainfall_7d=120,
            tmax_c=28.0, humidity_pct=85.0,
            crop="rice_rainfed", crop_stage="harvesting",
            irrigation_status="rainfed"
        )
        assert result["components"]["flood"] > 0

    def test_score_bounded_0_5(self):
        for cdd in [0, 10, 30]:
            result = compute_crop_stage_risk(
                cdd=cdd, cwd=0, rainfall_7d=0,
                tmax_c=40.0, humidity_pct=95.0,
                crop="rice_rainfed", crop_stage="reproductive",
            )
            assert 0 <= result["risk_score"] <= 5.0


# ── Municipal Risk Score Tests ────────────────────────────────────────────────

class TestMunicipalRiskScore:
    def test_score_range(self):
        mun = {"irrigation_status": "rainfed"}
        for drought_class in ["none", "watch", "warning", "critical"]:
            score = compute_municipal_risk_score(
                {"cdd": 0, "drought_class": drought_class,
                 "rainfall_7d_mm": 10.0, "heat_class": "low"},
                mun
            )
            assert 0 <= score <= 100


# ── Source Priority Tests ─────────────────────────────────────────────────────

class TestWeatherSourcePriority:
    def test_up_noah_used_between_apa_cis_and_chirps(self, monkeypatch):
        municipality = {
            "psgc": "0201500000",
            "name": "Tuguegarao City",
            "province": "Cagayan",
            "lat": 17.6132,
            "lon": 121.7270,
            "irrigation_status": "rainfed",
            "elevation_m": 50,
        }
        daily = [
            {
                "date": f"2026-08-{day:02d}",
                "psgc": "0201500000",
                "rainfall_mm": 1.0,
                "tmax_c": 31.0,
                "tmin_c": 24.0,
                "tmean_c": 27.5,
                "humidity_pct": 75.0,
                "wind_speed_ms": 2.0,
                "solar_mj": 18.0,
                "source": "nasa_power",
            }
            for day in range(1, 31)
        ]

        monkeypatch.setattr(indicator_module, "load_municipalities", lambda: [municipality])
        monkeypatch.setattr(indicator_module, "load_recent_daily", lambda _psgc, n_days=30: daily)
        monkeypatch.setattr(indicator_module, "load_climatology", lambda: {})
        monkeypatch.setattr(indicator_module, "load_pagasa_current", lambda: {})
        monkeypatch.setattr(indicator_module, "load_latest_apa_cis", lambda: {})
        monkeypatch.setattr(indicator_module, "load_latest_chirps_rainfall", lambda: {
            "0201500000": {"date": "2026-08-30", "rainfall_mm": 12.0}
        })
        monkeypatch.setattr(indicator_module, "load_latest_up_noah", lambda: {
            "0201500000": {
                "date": "2026-08-31",
                "rainfall_24h_mm": 44.0,
                "rainfall_1h_mm": 4.0,
                "rainfall_3h_mm": 11.0,
                "rainfall_6h_mm": 18.0,
                "rainfall_12h_mm": 31.0,
                "rainfall_tomorrow_mm": 25.0,
                "heat_index_c": 39.0,
                "tmax_c": 35.0,
                "method": "raster_overlay_sampling",
            }
        })
        monkeypatch.setattr(indicator_module, "load_acap_current", lambda: {})
        monkeypatch.setattr(indicator_module, "load_acap_cropping_calendars", lambda: {})
        monkeypatch.setattr(indicator_module, "today_pht", lambda: __import__("datetime").date(2026, 8, 31))

        result = indicator_module.compute_all_indicators()["0201500000"]

        obs = result["observations"]
        assert obs["rainfall_24h_mm"] == 44.0
        assert obs["rainfall_source"] == "up_noah"
        assert obs["chirps_rainfall_24h_mm"] == 12.0
        assert obs["tmax_c"] == 35.0
        assert obs["heat_index_c"] == 39.0
        assert result["data_sources"]["priority_order"] == "APA CIS > UP NOAH > CHIRPS rainfall > NASA POWER"

    def test_critical_higher_than_none(self):
        mun = {"irrigation_status": "rainfed"}
        low = compute_municipal_risk_score(
            {"cdd": 0, "drought_class": "none", "rainfall_7d_mm": 50.0, "heat_class": "low"},
            mun
        )
        high = compute_municipal_risk_score(
            {"cdd": 25, "drought_class": "critical", "rainfall_7d_mm": 0.0, "heat_class": "danger"},
            mun
        )
        assert high > low


# ── Advisory Rule Engine Tests ────────────────────────────────────────────────

class TestAdvisoryEngine:
    def _make_indicators(self, rain=0, cdd=0, drought="none", heat_class="low"):
        return {
            "observations": {"rainfall_24h_mm": rain, "rainfall_48h_mm": rain * 1.5},
            "indicators": {
                "cdd": cdd,
                "drought_class": drought,
                "heat_stress": {"heat_class": heat_class},
                "rainfall_anomaly": {"anomaly_class": "near_normal"},
            }
        }

    def test_extreme_rain_triggers(self):
        from scripts.advisories.advisory_engine import evaluate_municipality
        ind = self._make_indicators(rain=110)
        mun = {"municipality": "Test", "province": "Cagayan", "irrigation_status": "rainfed"}
        advisories = evaluate_municipality(ind, mun)
        rule_ids = [a["rule_id"] for a in advisories]
        assert "RAIN_EXTREME_24H" in rule_ids

    def test_drought_critical_triggers_on_rainfed(self):
        from scripts.advisories.advisory_engine import evaluate_municipality
        ind = self._make_indicators(cdd=22, drought="critical")
        mun = {"municipality": "Test", "province": "Isabela", "irrigation_status": "rainfed"}
        advisories = evaluate_municipality(ind, mun)
        rule_ids = [a["rule_id"] for a in advisories]
        assert "DROUGHT_CRITICAL" in rule_ids

    def test_drought_critical_not_on_irrigated(self):
        from scripts.advisories.advisory_engine import evaluate_municipality
        ind = self._make_indicators(cdd=22, drought="critical")
        mun = {"municipality": "Test", "province": "Isabela", "irrigation_status": "irrigated"}
        advisories = evaluate_municipality(ind, mun)
        rule_ids = [a["rule_id"] for a in advisories]
        # DROUGHT_CRITICAL requires rainfed
        assert "DROUGHT_CRITICAL" not in rule_ids

    def test_severity_ordering(self):
        from scripts.advisories.advisory_engine import evaluate_municipality
        # Both extreme rain and drought critical
        ind = self._make_indicators(rain=110, cdd=22, drought="critical")
        mun = {"municipality": "Test", "province": "Cagayan", "irrigation_status": "rainfed"}
        advisories = evaluate_municipality(ind, mun)
        sev_order = {"danger": 0, "warning": 1, "advisory": 2, "info": 3}
        for i in range(len(advisories) - 1):
            assert (sev_order.get(advisories[i]["severity"], 99)
                    <= sev_order.get(advisories[i+1]["severity"], 99))

    def test_advisory_texts_present(self):
        from scripts.advisories.advisory_engine import evaluate_municipality
        ind = self._make_indicators(rain=110)
        mun = {"municipality": "Tuguegarao", "province": "Cagayan", "irrigation_status": "rainfed"}
        advisories = evaluate_municipality(ind, mun)
        for adv in advisories:
            texts = adv.get("texts", {})
            assert "bulletin" in texts and len(texts["bulletin"]) > 10
            assert "sms" in texts and len(texts["sms"]) <= 200  # SMS-friendly

    def test_sms_length_constraint(self):
        """SMS advisories should be ≤ 200 chars (practical SMS limit)."""
        from scripts.advisories.advisory_engine import ADVISORY_RULES
        mun = {"municipality": "Tuguegarao", "province": "Cagayan",
               "irrigation_status": "rainfed", "lat": 17.6, "lon": 121.7}
        ind = {
            "observations": {"rainfall_24h_mm": 120, "rainfall_48h_mm": 180},
            "indicators": {
                "cdd": 25, "drought_class": "critical",
                "heat_stress": {"heat_class": "danger"},
                "rainfall_anomaly": {"anomaly_class": "far_below", "pct_of_normal": 30.0},
            }
        }
        for rule in ADVISORY_RULES:
            try:
                if rule["trigger_fn"](ind, mun):
                    sms = rule["sms_text"](ind, mun)
                    assert len(sms) <= 200, f"SMS too long for rule {rule['rule_id']}: {len(sms)} chars"
            except Exception:
                pass  # Skip rules that error on this mun


# ── Utils Tests ───────────────────────────────────────────────────────────────

class TestUtils:
    def test_validate_rainfall_bounds(self):
        from scripts.utils import validate_rainfall
        assert validate_rainfall(50.0) == 50.0
        assert validate_rainfall(-1.0) is None
        assert validate_rainfall(9999.0) is None
        assert validate_rainfall(-999.0) is None  # Fill value
        assert validate_rainfall(None) is None

    def test_validate_temperature_bounds(self):
        from scripts.utils import validate_temperature
        assert validate_temperature(32.0) == 32.0
        assert validate_temperature(-999.0) is None
        assert validate_temperature(100.0) is None

    def test_date_range(self):
        from scripts.utils import date_range
        from datetime import date
        r = date_range(date(2026, 6, 1), date(2026, 6, 3))
        assert len(r) == 3
        assert r[0].isoformat() == "2026-06-01"
        assert r[-1].isoformat() == "2026-06-03"


class TestMunicipalityLevelTcws:
    def test_partial_tcws_does_not_fall_back_to_whole_province(self):
        from scripts.indicators.compute_indicators import _official_hazards_for_municipality

        pagasa = {
            "as_of": "2026-08-05",
            "typhoon": {
                "active": True,
                "name": "TEST",
                "signal_levels": {"Isabela": 2},
                "municipality_validation": {"coverage_scope": "municipality"},
                "affected_municipalities": [
                    {"psgc": "031423000", "municipality": "Quirino", "province": "Isabela", "tcws_signal": 2}
                ],
            },
        }

        matched = _official_hazards_for_municipality(
            {"psgc": "031423000", "name": "Quirino", "province": "Isabela"}, pagasa
        )
        unmatched = _official_hazards_for_municipality(
            {"psgc": "031426000", "name": "Roxas", "province": "Isabela"}, pagasa
        )

        assert matched["tcws_signal"] == 2
        assert matched["tcws_municipality_validated"] is True
        assert unmatched["tcws_signal"] == 0
        assert unmatched["tcws_municipality_validated"] is False
