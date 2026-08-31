# UP NOAH Weather Overlay Integration

This guide explains how APA-CIS should use the UP NOAH weather updates page as
the second weather source after APA CIS and before CHIRPS/NASA POWER.

## Current Source Priority

1. APA CIS municipal weather records
2. UP NOAH sampled weather overlays
3. CHIRPS rainfall, rainfall only
4. NASA POWER daily weather fallback

The indicator engine reads UP NOAH from:

```text
data/raw/up_noah/up_noah_current.json
```

If this file is missing, empty, stale, or does not contain numeric municipal
values, the app continues to CHIRPS and then NASA POWER.

## NOAH Weather Layers Found

The current NOAH weather page loads georeferenced raster overlays from
`https://webgis-static.up.edu.ph/api`.

Rainfall:

```text
contours/1hr_latest_rainfall_contour.png
contours/3hr_latest_rainfall_contour.png
contours/6hr_latest_rainfall_contour.png
contours/12hr_latest_rainfall_contour.png
contours/24hr_latest_rainfall_contour.png
rainfall/rainmap_gtif_day1.png
```

Temperature:

```text
temperature/HI_1.png
temperature/t2m_1.png
```

The current public page exposes a 3-hour rainfall overlay, not a 2-hour rainfall
overlay.

## Required Municipal JSON Shape

Create `data/raw/up_noah/up_noah_current.json` with this shape:

```json
{
  "source": "up_noah",
  "source_url": "https://noah.up.edu.ph/weather-updates/rainfall-contour",
  "date": "YYYY-MM-DD",
  "method": "raster_overlay_sampling",
  "data": [
    {
      "psgc": "0201500000",
      "municipality": "Tuguegarao City",
      "province": "Cagayan",
      "date": "YYYY-MM-DD",
      "source": "up_noah",
      "method": "raster_overlay_sampling",
      "rainfall_1h_mm": null,
      "rainfall_3h_mm": null,
      "rainfall_6h_mm": null,
      "rainfall_12h_mm": null,
      "rainfall_24h_mm": null,
      "rainfall_tomorrow_mm": null,
      "heat_index_c": null,
      "tmax_c": null
    }
  ]
}
```

`rainfall_24h_mm`, `heat_index_c`, and `tmax_c` are the fields currently used
by the indicator engine. The other rainfall windows are preserved for municipal
profiles, QA, and future dashboard widgets.

## Step-by-Step Conversion

1. Download the PNG overlay files listed above.
2. Georeference each overlay using the coordinates embedded in the NOAH map app.
   Current rainfall contours use:

   ```text
   northwest: 115.35,21.55
   northeast: 128.25,21.55
   southeast: 128.25,3.85
   southwest: 115.35,3.85
   ```

   Tomorrow rainfall and temperature overlays use:

   ```text
   northwest: 116.855,19.402
   northeast: 127.055,19.402
   southeast: 127.055,5.205
   southwest: 116.855,5.205
   ```

3. Clip or mask sampling to Region 2 municipal boundaries.
4. For each municipality, sample the raster by centroid first, then by multiple
   interior points if the centroid falls outside colored pixels.
5. Convert sampled colors/classes to millimeters or degrees using the matching
   NOAH legend.
6. Write one record per municipality to `up_noah_current.json`.
7. Run the pipeline:

   ```text
   python scripts/run_pipeline.py --skip-fetch
   ```

8. Inspect the dashboard source panel. Municipalities with valid NOAH rainfall
   should show `UP NOAH` as the rainfall source when APA CIS is unavailable.

## QA Rules

- Do not overwrite APA CIS values with NOAH values.
- Do not treat raw PNG colors as exact station observations.
- Store the sampling method and source date in every record.
- Keep nulls when a municipality cannot be sampled confidently.
- If a NOAH endpoint changes or a raster fails to download, leave
  `up_noah_current.json` missing or empty so the app falls back automatically.
