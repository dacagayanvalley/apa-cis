# APA-CIS — Climate Information Service
**DA RFO 02 · Cagayan Valley (Region 02)**

[![Pipeline](https://github.com/dacagayanvalley/apa-cis/actions/workflows/daily_pipeline.yml/badge.svg)](https://github.com/dacagayanvalley/apa-cis/actions)

Municipal-level agricultural climate information service for Batanes, Cagayan, Isabela, Nueva Vizcaya, and Quirino. Provides daily climate indicators, drought watch, heat stress, crop-stage risk, and automated agricultural advisories — deployed on GitHub Pages with zero infrastructure cost.

---

## MVP Implementation Update

This repository now includes the minimum viable municipal agriculture CIS stack:

- NASA POWER automated daily weather fetch for all Cagayan Valley municipalities.
- CHIRPS automated rainfall raster download with optional municipal centroid sampling when `rasterio` is installed.
- Semi-automated PAGASA official product workflow with a stable `data/raw/pagasa/pagasa_current.json` output.
- Source-aware indicators that prefer CHIRPS rainfall when available and keep NASA POWER as fallback.
- Added postharvest drying risk, official PAGASA typhoon signal context, irrigation priority, and wet-spell disease watch rules.
- Added `data/geospatial/drying_risk.geojson` for the Leaflet map.
- Added Supabase/PostGIS schema and OpenAPI starter files under `api/`.

Operational runbook: `docs/mvp_operations_guide.md`

Architecture and gap assessment: `docs/cis_upgrade_assessment.md`

---

## What It Does

| Capability | Detail |
|---|---|
| **Daily ETL** | Fetches NASA POWER agroclimatic data for all 92 municipalities at 6 AM PHT via GitHub Actions |
| **Climate Indicators** | CDD/CWD, rainfall anomaly vs 1991–2020 normals, WBGT heat stress, FAO-56 ETo, irrigation demand, field workability |
| **Advisory Engine** | 10 rule-based advisory types with 4 output formats each (bulletin, SMS, LGU, Facebook) |
| **Map Layers** | 8 GeoJSON layers rendered in Leaflet: rainfall, drought watch, heat, workability, anomaly, crop risk, municipal risk, advisory status |
| **Planning Dashboard** | Priority municipality ranking for DA intervention, province summaries, intervention type matrix |
| **PAGASA Integration** | Semi-automated workflow: PDF inbox processor + public page scraping + manual entry template |

---

## Quick Start

### 1. Clone and install

```bash
git clone https://github.com/dacagayanvalley/apa-cis.git
cd apa-cis
pip install -r requirements.txt
```

### 2. Build climatology baseline (one-time, ~30 minutes)

```bash
python scripts/fetch_nasa_power/build_climatology.py
```

This fetches 1991–2020 monthly normals for all 92 municipalities from NASA POWER and saves them to `config/climatology_1991_2020.json` and `config/climatology_flat.json`.

### 3. Run the daily pipeline manually

```bash
# Normal daily run (fetches data from today minus 5-day NASA lag)
python scripts/run_pipeline.py

# Specify a date
python scripts/run_pipeline.py --date 2026-06-01

# Skip fetch (indicators + advisories only, uses existing daily data)
python scripts/run_pipeline.py --skip-fetch
```

### 4. View the dashboard

Open `frontend/index.html` in your browser, or serve it with any static server:

```bash
cd frontend && python -m http.server 8080
# → http://localhost:8080
```

---

## Automated Daily Pipeline (GitHub Actions)

The pipeline runs automatically every day at **6:00 AM Philippine Standard Time** via `.github/workflows/daily_pipeline.yml`.

**Pipeline steps:**
1. `scripts/fetch_nasa_power/fetch_daily.py` — Fetches NASA POWER data for all 92 municipalities
2. `scripts/fetch_pagasa/pagasa_ingestor.py` — Processes PAGASA PDF inbox and scrapes public pages
3. `scripts/indicators/compute_indicators.py` — Computes all climate indicators
4. `scripts/advisories/advisory_engine.py` — Evaluates 10 advisory rules, generates outputs
5. Commits updated JSON/GeoJSON files to `main` branch → triggers GitHub Pages rebuild

**Data output files updated daily:**
```
data/processed/daily/weather_latest.json     ← Latest weather observations
data/processed/indicators/indicators_latest.json  ← All indicators (92 muns)
data/advisories/daily/advisories_latest.json ← Advisory report
data/geospatial/*.geojson                    ← 8 Leaflet map layers
data/pipeline_status.json                   ← Pipeline run status
```

---

## Data Sources

### NASA POWER (Primary — Automated)
- **URL:** https://power.larc.nasa.gov/api/temporal/daily/point
- **Community:** AG (Agroclimatology)
- **Lag:** ~5 days behind real-time
- **Parameters:** Rainfall, Tmax, Tmin, Tmean, RH, Wind speed/direction, Solar radiation, Soil wetness
- **Coverage:** Global; centroid-based point values for each municipality

### CHIRPS / NASA POWER Monthly (Climatology Baseline)
- Used to build the 1991–2020 monthly normals for rainfall anomaly calculation
- Run `build_climatology.py` once to generate the baseline

### PAGASA (Semi-Automated)
PAGASA does not provide a public machine-readable API. Three ingestion modes are provided:

| Mode | How |
|---|---|
| **PDF Inbox** | Drop PAGASA PDFs into `data/raw/pagasa/`. The ingestor extracts Region 2 text automatically. |
| **Web Scraping** | Scrapes PAGASA public pages for ENSO status and farm weather text. |
| **Manual Entry** | CIS staff fills `data/raw/pagasa/manual_entry_template.json` after reviewing official PAGASA advisories. |

To create the manual entry template:
```bash
python scripts/fetch_pagasa/pagasa_ingestor.py --create-template
```

To ingest a completed entry:
```bash
python scripts/fetch_pagasa/pagasa_ingestor.py --ingest-entry data/raw/pagasa/manual_entry_2026-06-10.json
```

---

## Climate Indicators

| Indicator | Method | Thresholds |
|---|---|---|
| **Consecutive Dry Days (CDD)** | WMO: < 1 mm/day | Watch: 10d · Warning: 14d · Critical: 21d |
| **Consecutive Wet Days (CWD)** | ≥ 1 mm/day streak | Used for disease risk |
| **Rainfall Anomaly** | Observed vs 1991–2020 monthly normal | Far Below: <60% · Below: 60–80% · Near: 80–120% · Above: >120% |
| **Heat Stress (WBGT)** | Stull (2011) wet-bulb + ISO 7243 WBGT | Low: <28 · Moderate: 28–32 · High: 32–35 · Danger: >35 |
| **ETo** | FAO-56 Penman-Monteith (simplified) | mm/day |
| **Irrigation Demand** | ETo − Rainfall (daily) | Priority adjusted for irrigation_status |
| **Field Workability** | Rule-based by rainfall + CDD | 8 operation types assessed |
| **Crop-Stage Risk** | Composite score (drought + flood + heat + disease) | 0–5 scale |
| **Municipal Risk Score** | Composite 0–100 | Drought class + 7d rain + heat + irrigation vulnerability |

---

## Advisory Rules

| Rule ID | Trigger | Severity |
|---|---|---|
| `RAIN_EXTREME_24H` | Rainfall ≥ 100 mm/24h | 🔴 Danger |
| `RAIN_HARVEST_RISK` | Rainfall ≥ 20 mm during harvest season | 🟠 Warning |
| `DROUGHT_CRITICAL` | CDD ≥ 21 days, rainfed areas | 🔴 Danger |
| `DROUGHT_WARNING` | CDD 14–20 days | 🟠 Warning |
| `DROUGHT_WATCH` | CDD 10–13 days | 🟡 Advisory |
| `HEAT_DANGER` | WBGT danger class | 🔴 Danger |
| `HEAT_HIGH` | WBGT high class | 🟠 Warning |
| `FERTILIZER_DEFER` | Rainfall ≥ 15 mm/24h | 🟡 Advisory |
| `SPRAYING_DEFER` | Rainfall ≥ 10 mm/24h | 🟡 Advisory |
| `BELOW_NORMAL_RAINFALL` | Monthly anomaly class = below/far_below | 🟡 Advisory |

Each rule generates four text formats:
- **Technical Bulletin** — For DA RFO 02 / PAO / RAO official use
- **SMS** (≤160 chars) — For farmer text dissemination
- **LGU Advisory** — For MAO/PAO distribution
- **Facebook Post** — For DA social media (Filipino/English)

---

## Project Structure

```
apa-cis/
├── config/
│   ├── municipalities.json          # 92 municipalities, PSGC codes, lat/lon, climate type
│   ├── settings.yaml                # All thresholds, API config, paths
│   ├── climatology_1991_2020.json   # Generated by build_climatology.py
│   └── climatology_flat.json        # Quick-lookup version
│
├── scripts/
│   ├── utils.py                     # Shared: config, logging, validators, HTTP
│   ├── run_pipeline.py              # Master orchestrator
│   ├── fetch_nasa_power/
│   │   ├── fetch_daily.py           # Daily NASA POWER fetch
│   │   └── build_climatology.py     # One-time 30-year baseline builder
│   ├── fetch_pagasa/
│   │   └── pagasa_ingestor.py       # Semi-automated PAGASA workflow
│   ├── indicators/
│   │   └── compute_indicators.py    # All indicator functions + GeoJSON export
│   └── advisories/
│       ├── advisory_engine.py       # 10-rule advisory engine
│       └── weekly_summary.py        # Weekly provincial summary
│
├── frontend/
│   ├── index.html                   # 5-module dashboard
│   ├── css/cis.css
│   └── js/
│       ├── cis-data.js              # Data loader + formatters
│       ├── cis-map.js               # Leaflet map + layer switcher
│       ├── cis-dashboard.js         # Stat cards + municipal table
│       ├── cis-advisory.js          # Advisory list, detail, bulletin generator
│       ├── cis-planning.js          # Planning dashboard + municipal profile
│       └── cis-main.js              # Bootstrap + module switcher
│
├── data/
│   ├── raw/nasa_power/              # Raw API responses (gitignored for size)
│   ├── raw/pagasa/                  # PAGASA PDFs + manual entries
│   ├── processed/daily/             # weather_YYYY-MM-DD.json per day
│   ├── processed/indicators/        # indicators_latest.json
│   ├── advisories/daily/            # advisories_latest.json
│   ├── advisories/weekly/           # weekly_summary_latest.json
│   └── geospatial/                  # 8 GeoJSON layers for Leaflet
│
├── tests/
│   └── test_indicators.py           # 46 unit tests (pytest)
│
├── .github/workflows/
│   └── daily_pipeline.yml           # GitHub Actions: 6 AM PHT daily
│
├── logs/                            # ETL run logs (gitignored)
├── requirements.txt
└── README.md
```

---

## Running Tests

```bash
pytest tests/ -v
# 46 tests — all should pass
```

---

## Deployment to GitHub Pages

1. Push this repository to GitHub (e.g. `dacagayanvalley/apa-cis`)
2. Enable GitHub Pages: **Settings → Pages → Source: Deploy from branch → main → /frontend**
3. GitHub Actions will run daily at 6 AM PHT and commit updated data files
4. The dashboard will be live at `https://dacagayanvalley.github.io/apa-cis/`

**`.gitignore` recommendations** — exclude large/sensitive files:
```
data/raw/nasa_power/        # Large raw API responses
logs/                       # Pipeline logs
config/climatology_1991_2020.json  # Large (regenerate on setup)
data/raw/pagasa/*.pdf       # Copyrighted PAGASA materials
```

---

## Key Contacts

| Role | Office | Hotline |
|---|---|---|
| Regional Executive Director | DA RFO 02 | (078) 844-1228 |
| RAED Chief | DA RFO 02 | (078) 396-0558 |
| AMIA/CRAO Coordinator | DA RFO 02 | — |
| PAGASA RegSynOp | PAGASA Reg. Office 02 | — |

---

## References

- Allen et al. (1998). FAO Irrigation and Drainage Paper No. 56 — Penman-Monteith ETo
- Stull (2011). Wet-bulb temperature from relative humidity and air temperature. *J. Appl. Meteorology Climatology*
- Bernard & Barrow (1989). WBGT approximation for outdoor workers
- NASA POWER Project. https://power.larc.nasa.gov/
- PAGASA. https://www.pagasa.dost.gov.ph/
- WMO (2008). Guide to Hydrological Practices — Dry spell threshold definitions

---

*Developed for DA RFO 02 Cagayan Valley under the APA Project — Adaptation and Protection through Agriculture. Built on GitHub Pages + GitHub Actions (zero infrastructure cost).*
