# APA-CIS — Climate Information Service
**DA RFO 02 · Cagayan Valley (Region 02)**

[![Pipeline](https://github.com/dacagayanvalley/apa-cis/actions/workflows/daily_pipeline.yml/badge.svg)](https://github.com/dacagayanvalley/apa-cis/actions)

Municipal-level agricultural climate information service for Batanes, Cagayan, Isabela, Nueva Vizcaya, and Quirino. Provides daily climate indicators, drought watch, heat stress, crop-stage risk, and automated agricultural advisories — deployed on GitHub Pages with zero infrastructure cost.

---

## MVP Implementation Update

This repository now includes the minimum viable municipal agriculture CIS stack:

- NASA POWER automated daily weather fetch for all Cagayan Valley municipalities.
- CHIRPS automated rainfall raster download with optional municipal centroid sampling when `rasterio` is installed.
- APA CIS public app scrape for same-day municipal rainfall, maximum temperature, and wind. These values now take priority over NASA/CHIRPS when available.
- ACAP Cagayan Valley scrape for 10-day province forecasts, AMIA village metadata, and crop-calendar municipality references.
- Semi-automated PAGASA official product workflow with a stable `data/raw/pagasa/pagasa_current.json` output.
- Source-aware indicators with priority order: APA CIS > CHIRPS rainfall > NASA POWER fallback.
- CRA Compendium adaptation-measure matrix attached to every triggered advisory.
- Added postharvest drying risk, official PAGASA typhoon signal context, irrigation priority, and wet-spell disease watch rules.
- Added `data/geospatial/drying_risk.geojson` for the Leaflet map.
- Added Region 2 administrative boundary overlays and a full Project NOAH PMTiles hazard map mode for flood, landslide, debris-flow, and storm-surge layers.
- Added Supabase/PostGIS schema and OpenAPI starter files under `api/`.

Operational runbook: `docs/mvp_operations_guide.md`

Architecture and gap assessment: `docs/cis_upgrade_assessment.md`

---

## What It Does

| Capability | Detail |
|---|---|
| **Daily ETL** | Fetches NASA POWER agroclimatic data for all 93 municipalities at 6 AM PHT via GitHub Actions |
| **Climate Indicators** | CDD/CWD, rainfall anomaly vs 1991–2020 normals, WBGT heat stress, FAO-56 ETo, irrigation demand, field workability |
| **Advisory Engine** | 10 rule-based advisory types with 4 output formats each (bulletin, SMS, LGU, Facebook) |
| **Map Layers** | 8 operational GeoJSON layers rendered in Leaflet, Region 2 boundary overlays, and 9 Project NOAH PMTiles hazard layers |
| **Planning Dashboard** | Priority municipality ranking for DA intervention, province summaries, intervention type matrix |
| **PAGASA Integration** | Semi-automated workflow: PDF inbox processor + public page scraping + manual entry template |
| **Regional App Integration** | APA CIS same-day weather scrape plus ACAP 10-day/crop-calendar context |

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

This fetches 1991–2020 monthly normals for all 93 municipalities from NASA POWER and saves them to `config/climatology_1991_2020.json` and `config/climatology_flat.json`.

### 3. Run the daily pipeline manually

```bash
# Normal daily run (fetches data from today minus 5-day NASA lag)
python scripts/run_pipeline.py

# Specify a date
python scripts/run_pipeline.py --date 2026-06-01

# Skip fetch (indicators + advisories only, uses existing daily data)
python scripts/run_pipeline.py --skip-fetch

# Refresh regional public app sources, then recompute indicators/advisories
python scripts/fetch_apa_cis/cis_scraper.py
python scripts/fetch_acap/acap_scraper.py
python scripts/run_pipeline.py --skip-fetch --skip-pagasa
```

### 4. View the dashboard

Serve the repository root so `frontend/` can read the sibling `data/` directory:

```bash
python -m http.server 8080
# → http://localhost:8080/frontend/
```

Opening `frontend/index.html` directly from disk also works in some browsers, but the local server is better for checking map/data fetches.

### 5. Prepare boundaries and NOAH hazard sources

Refresh the Region 2 administrative boundaries from the companion thematic maps repository:

```bash
python scripts/prepare_boundary_overlays.py
```

The frontend loads the full Project NOAH hazard set through the BetterGov PMTiles mirror, so multi-GB NOAH shapefiles are not committed to Git. To refresh the source catalog and verify Region 2 source availability:

```bash
python scripts/list_noah_region2_sources.py
```

For offline fallback or municipal exposure analytics, place pre-clipped Region 2 GeoJSON files in `data/raw/noah/r2/` using these names:

```text
flood_5yr.geojson
flood_25yr.geojson
flood_100yr.geojson
landslide.geojson
debris_flow.geojson
storm_surge_ssa1.geojson
storm_surge_ssa2.geojson
storm_surge_ssa3.geojson
storm_surge_ssa4.geojson
```

Then normalize them for the frontend:

```bash
python scripts/prepare_noah_hazard_overlays.py
```

Generate the municipal exposure analytics:

```bash
python scripts/compute_noah_municipal_exposure.py
```

The main frontend NOAH mode uses PMTiles from the published mirror. The generated files under `data/geospatial/noah/` are optional lightweight local overlays for offline use and exact municipal exposure summaries. When local hazard geometry is still missing, the exposure output reports source readiness by municipality/province without inventing percentages.

---


## Access Monitoring Dashboard

The frontend includes an **Access Monitor** module for data-use monitoring. It records visitor/session IDs, module views, browser/device summary, optional name, verified email when signed in, agency/office, role, and browser location only after the visitor grants permission.

By default, records stay in the visitor's browser `localStorage` so the feature can be tested on GitHub Pages without extra infrastructure. To persist monitoring records centrally and enable email magic-link identity, run `api/supabase_auth_monitoring.sql` in Supabase, enable Supabase Auth email OTP links, add the deployed dashboard URL to the Supabase Auth redirect allow-list, then copy `frontend/js/cis-supabase-config.example.js` to `frontend/js/cis-supabase-config.js` and fill in your project values:

```js
window.CIS_MONITORING_CONFIG = {
  supabaseUrl: 'https://your-project-ref.supabase.co',
  supabaseAnonKey: 'your-public-anon-key',
};
```

The starter row-level security policy allows anonymous inserts from the public app, lets authenticated users update their own `user_profiles` row, and limits central log/profile reading to authenticated Supabase users. If public read access is desired for an internal-only deployment, adjust the policies deliberately because names, emails, agencies, and consented coordinates may be personal data.
---

## Automated Daily Pipeline (GitHub Actions)

The pipeline runs automatically every day at **6:00 AM Philippine Standard Time** via `.github/workflows/daily_pipeline.yml`.

**Pipeline steps:**
1. `scripts/fetch_apa_cis/cis_scraper.py` - Scrapes same-day APA CIS Region 2 municipal weather layers
2. `scripts/fetch_acap/acap_scraper.py` - Scrapes ACAP 10-day forecast, AMIA villages, and crop-calendar metadata
3. `scripts/fetch_nasa_power/fetch_daily.py` - Fetches NASA POWER fallback data for all 93 municipalities
4. `scripts/fetch_chirps/fetch_daily.py` - Downloads/samples CHIRPS rainfall where available
5. `scripts/fetch_pagasa/pagasa_ingestor.py` - Processes PAGASA PDF inbox and scrapes public pages
6. `scripts/indicators/compute_indicators.py` - Computes all climate indicators
7. `scripts/compute_noah_municipal_exposure.py` - Computes or refreshes Project NOAH municipal exposure readiness/analytics
8. `scripts/advisories/advisory_engine.py` - Evaluates advisory rules and attaches CRA adaptation measures
9. Commits updated JSON/GeoJSON files to `main` branch, which triggers GitHub Pages rebuild

**Data output files updated daily:**
```
data/processed/daily/weather_latest.json     ← Latest weather observations
data/raw/apa_cis/apa_cis_current.json       ← Latest APA CIS public weather scrape
data/raw/acap/acap_current.json             ← Latest ACAP 10-day/crop-calendar scrape
data/processed/indicators/indicators_latest.json  ← All indicators (93 muns)
data/advisories/daily/advisories_latest.json ← Advisory report
data/geospatial/*.geojson                    ← 8 Leaflet map layers
data/boundaries/*.geojson                    ← Region 2 boundary overlays
data/geospatial/noah/noah_overlay_build_status.json ← NOAH PMTiles/local overlay status
data/geospatial/noah/*.geojson               ← Optional prepared Project NOAH local overlays
data/processed/noah/municipal_hazard_exposure.json ← NOAH municipal exposure analytics
data/pipeline_status.json                   ← Pipeline run status
```

---

## Data Sources

### APA CIS Public App (Priority Same-Day Source)
- **URL:** https://cis.apa.da.gov.ph/cis
- **Use:** Same-day municipal rainfall, maximum temperature, and wind layers for Region 2
- **Priority:** First source used for current operations when a municipality match is available

### ACAP Cagayan Valley (PAGASA 10-Day / Crop Calendar Context)
- **URL:** https://acap-cagayanvalley.github.io/
- **Use:** Province-level 10-day forecast records, AMIA village metadata, and crop-calendar municipality references
- **Priority:** Used as official/regional context for municipal advisory generation

### NASA POWER (Fallback — Automated)
- **URL:** https://power.larc.nasa.gov/api/temporal/daily/point
- **Community:** AG (Agroclimatology)
- **Lag:** ~5 days behind real-time
- **Parameters:** Rainfall, Tmax, Tmin, Tmean, RH, Wind speed/direction, Solar radiation, Soil wetness
- **Coverage:** Global; centroid-based point values for each municipality
- **Priority:** Used when APA CIS or CHIRPS records are unavailable/stale

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

### Project NOAH Hazard Context

- **URL:** https://noah.up.edu.ph/
- **Use:** Static planning hazard overlays for flood, landslide, debris flow, and storm surge.
- **License:** Open Data Commons Open Database License (ODC-ODbL).
- **Integration:** The dashboard loads all 9 NOAH hazard layers through the BetterGov PMTiles mirror. Municipal exposure analytics are generated from clipped local GeoJSON when available, with source-readiness fallback when exact geometry is not present.
- **Catalog:** `data/reference/noah_hazard_overlays.json`
- **Scan:** `docs/noah_hazard_integration_scan.md`

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
│   ├── municipalities.json          # 93 municipalities, PSGC codes, lat/lon, climate type
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
│   ├── boundaries/                # Region 2 province/district/municipal/barangay overlays
│   ├── raw/nasa_power/              # Raw API responses (gitignored for size)
│   ├── raw/noah/                    # Downloaded/pre-clipped NOAH source files (gitignored)
│   ├── raw/pagasa/                  # PAGASA PDFs + manual entries
│   ├── processed/daily/             # weather_YYYY-MM-DD.json per day
│   ├── processed/indicators/        # indicators_latest.json
│   ├── advisories/daily/            # advisories_latest.json
│   ├── advisories/weekly/           # weekly_summary_latest.json
│   ├── geospatial/                  # 8 GeoJSON layers for Leaflet
│   │   └── noah/                    # NOAH PMTiles status + optional local overlays
│   └── processed/noah/              # Municipal Project NOAH exposure analytics
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
