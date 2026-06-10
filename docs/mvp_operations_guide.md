# APA-CIS MVP Operations Guide

This MVP publishes municipal-level agriculture climate decisions for Cagayan Valley using:

- NASA POWER for automated daily agroclimatic variables.
- CHIRPS for automated daily rainfall raster download and optional municipal rainfall sampling.
- PAGASA semi-automated entry for official advisories, ENSO, 10-day outlooks, and typhoon signal context.
- Static JSON/GeoJSON outputs for GitHub Pages.
- Optional Supabase/PostGIS schema for the next phase.

## Daily ETL Flow

1. NASA POWER fetch
   - Script: `scripts/fetch_nasa_power/fetch_daily.py`
   - Output: `data/processed/daily/weather_latest.json`
   - Use: weather observations, heat stress, ETo, wind, humidity, solar, NASA fallback rainfall.

2. CHIRPS fetch
   - Script: `scripts/fetch_chirps/fetch_daily.py`
   - Raw output: `data/raw/chirps/YYYY/MM/*.tif`
   - Processed output, if `rasterio` is installed: `data/processed/daily/chirps_rainfall_latest.json`
   - Use: preferred 24-hour rainfall source when available.

3. PAGASA ingestion
   - Script: `scripts/fetch_pagasa/pagasa_ingestor.py`
   - Stable output: `data/raw/pagasa/pagasa_current.json`
   - Use: official ENSO, seasonal outlook, 10-day provincial advisories, typhoon signal context.

4. Indicator computation
   - Script: `scripts/indicators/compute_indicators.py`
   - Output: `data/processed/indicators/indicators_latest.json`
   - Map outputs: `data/geospatial/*.geojson`

5. Advisory engine
   - Script: `scripts/advisories/advisory_engine.py`
   - Output: `data/advisories/daily/advisories_latest.json`
   - Formats: bulletin, SMS, LGU memo, Facebook text.

## Running Locally

```bash
pip install -r requirements.txt
python scripts/fetch_pagasa/pagasa_ingestor.py --create-template
python scripts/run_pipeline.py
cd frontend
python -m http.server 8080
```

Open `http://localhost:8080`.

## PAGASA Semi-Automated Workflow

1. Download the latest official PAGASA products:
   - Farm Weather Forecast
   - 10-Day Regional Agri-Weather Information
   - Monthly Agro-Climatic Outlook
   - ENSO advisory
   - Tropical cyclone bulletin, if applicable

2. Fill:

```text
data/raw/pagasa/manual_entry_template.json
```

3. Save the completed file as:

```text
data/raw/pagasa/manual_entry_YYYY-MM-DD.json
```

4. Ingest it:

```bash
python scripts/fetch_pagasa/pagasa_ingestor.py --ingest-entry data/raw/pagasa/manual_entry_YYYY-MM-DD.json
```

5. Run the pipeline:

```bash
python scripts/run_pipeline.py --skip-fetch
```

## CHIRPS Notes

The MVP downloads official CHIRPS daily GeoTIFF files automatically. Municipal sampling requires `rasterio`, which is intentionally optional because it is a heavier geospatial dependency.

Without `rasterio`:

- Raw CHIRPS rasters are downloaded and logged.
- Indicators continue using NASA POWER rainfall.
- Dashboard source panel shows NASA rainfall active.

With `rasterio`:

- The script samples rainfall at municipal centroids.
- `chirps_rainfall_latest.json` is created.
- Indicators use CHIRPS rainfall for `rainfall_24h_mm`.
- NASA rainfall remains in `nasa_power_rainfall_24h_mm` for audit/fallback.

## GitHub Pages Deployment

1. Publish the repository to GitHub.
2. In repository settings, enable GitHub Actions write permission:
   - Settings -> Actions -> General -> Workflow permissions -> Read and write permissions.
3. Enable GitHub Pages:
   - Settings -> Pages -> Deploy from branch.
   - Branch: `main`.
   - Folder: `/frontend`.
4. Run the workflow manually once from the Actions tab.
5. Confirm these files are created and committed:
   - `data/processed/daily/weather_latest.json`
   - `data/processed/indicators/indicators_latest.json`
   - `data/advisories/daily/advisories_latest.json`
   - `data/geospatial/rainfall_24h.geojson`
   - `data/geospatial/drying_risk.geojson`
   - `data/raw/pagasa/pagasa_current.json`
   - `data/pipeline_status.json`

## MVP Advisory Rules

The rule engine now covers:

- PAGASA tropical cyclone wind signal active
- Extreme rainfall
- Harvest disruption from rainfall
- Postharvest drying risk
- Critical/warning/watch dry spell
- High irrigation demand
- Heat stress
- Wet-spell disease watch
- Fertilizer defer
- Spraying defer
- Below-normal rainfall

Every advisory carries:

- `rule_id`
- severity
- affected crops/stages
- responsible office
- technical bulletin text
- SMS text
- LGU advisory text
- Facebook-ready text

## Data Quality Checklist

- Check source panel on the dashboard.
- Confirm PAGASA context date is current.
- Confirm rainfall source is CHIRPS where sampling is available or NASA fallback otherwise.
- Validate advisories with MAO/PAO/RAED before public release.
- Do not publish personally identifiable RSBSA farmer data.
- Keep raw PAGASA PDFs and raw CHIRPS rasters out of Git history.
