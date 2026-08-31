# Project NOAH Hazard Integration Scan

APA-CIS target: add Project NOAH hazard context to the existing Region 2 climate/advisory map without replacing the current municipal climate layers.

Implementation status:

- Done: Region 2 boundary prep script and frontend boundary overlays.
- Done: NOAH hazard overlay catalog and full PMTiles frontend mode for all 9 Project NOAH hazard layers.
- Done: NOAH GeoJSON normalization script for optional pre-clipped local hazard files.
- Done: municipal exposure analytics JSON contract and frontend planning/profile summaries.
- Pending: generate exact exposure hectares/percentages after clipped Region 2 source geometry is available.

## Best Integration Shape

The current APA-CIS map uses Leaflet and renders one municipal point GeoJSON layer at a time from `data/geospatial/*.geojson`. Project NOAH data is polygon/vector hazard data, so the clean integration is:

1. Keep APA-CIS municipal climate points as the active operational layer.
2. Add NOAH hazards as optional polygon overlays, grouped into Flood, Landslide, and Storm Surge.
3. Use PMTiles for full-resolution interactive display and clipped local GeoJSON only for offline/exposure workflows.
4. Add municipal exposure summaries into the advisory and planning views after geoprocessing.

Avoid scraping the NOAH web app directly. Use the published data/services and keep source attribution visible.

## Hazard Categories

### Flood

Recommended overlay set:

- Flood 5-year return period
- Flood 25-year return period
- Flood 100-year return period

Attributes:

- `Var = 1`: low hazard
- `Var = 2`: medium hazard
- `Var = 3`: high hazard

Useful sources:

- Project NOAH / BetterGov PMTiles: `flood_5yr`, `flood_25yr`, `flood_100yr`
- ArcGIS FeatureServer found for 5-year and 25-year flood layers
- RDAC catalog has a 100-year Project NOAH flood shapefile resource

APA-CIS use:

- High-value overlay for Cagayan River, Magat River, low-lying rice and corn production areas.
- Add municipal flags such as `flood_high_area_ha`, `flood_medium_area_ha`, and `flood_100yr_high_pct`.
- Advisory tie-in: raise confidence/severity when 24h rainfall or PAGASA severe weather affects a municipality with high NOAH flood exposure.

### Landslide

Recommended overlay set:

- Landslide hazard zones
- Debris flow / alluvial fan zones

Attributes:

- `HAZ = 1`: low hazard
- `HAZ = 2`: medium hazard
- `HAZ = 3`: high hazard

Useful sources:

- Project NOAH / BetterGov PMTiles: `landslide`, `debris_flow`
- RDAC catalog has Project NOAH landslide shapefile resources

APA-CIS use:

- Most relevant for upland rainfed areas and road/access risk in Nueva Vizcaya, Quirino, upland Isabela, and western/northern Cagayan.
- Add municipal flags such as `landslide_high_area_ha`, `debris_flow_high_area_ha`, and `upland_farm_access_risk`.
- Advisory tie-in: when rainfall is heavy or multi-day wet spell is detected, surface barangay/municipality planning guidance for slope and road access.

### Storm Surge

Recommended overlay set:

- Storm Surge Advisory 1: 2.01 m to 3 m peak
- Storm Surge Advisory 2: 3.01 m to 4 m peak
- Storm Surge Advisory 3: 4.01 m to 5 m peak
- Storm Surge Advisory 4: above 5 m peak

Attributes:

- `HAZ = 1`: low hazard
- `HAZ = 2`: medium hazard
- `HAZ = 3`: high hazard

Useful sources:

- Project NOAH / BetterGov PMTiles: `storm_surge_ssa1`, `storm_surge_ssa2`, `storm_surge_ssa3`, `storm_surge_ssa4`
- ArcGIS FeatureServer has four Project NOAH Storm Surge Advisory layers

APA-CIS use:

- Most relevant for Batanes, coastal Cagayan, and Pacific-facing Isabela municipalities.
- Add municipal flags such as `storm_surge_ssa4_high_area_ha`, `storm_surge_max_advisory`, and `coastal_agri_assets_exposed`.
- Advisory tie-in: combine with PAGASA cyclone signals and severe weather module for evacuation/logistics language for coastal production, seed storage, and livestock assets.

## Data Routes

### Route A: PMTiles + MapLibre

Current implementation for the frontend.

- Use the BetterGov combined PMTiles layer names directly.
- Add MapLibre GL JS and the PMTiles protocol beside the existing Leaflet map.
- Show the MapLibre NOAH view only when at least one NOAH hazard overlay is selected.

Pros:

- Handles the full Project NOAH dataset without committing multi-GB raw files or browser-heavy GeoJSON.
- Supports all 9 flood, landslide, debris-flow, and storm-surge layers.
- Fits GitHub Pages because the large vector tiles stay on the published data mirror.

Risks:

- Requires internet access to the PMTiles mirror and CDN map libraries.
- Boundaries currently remain on the Leaflet operational map, not the separate NOAH PMTiles mode.

### Route B: Cagayan Valley clipped GeoJSON

Best fallback for offline use and municipal exposure calculations.

- Download province-level shapefiles for Batanes, Cagayan, Isabela, Nueva Vizcaya, and Quirino.
- Clip/dissolve/simplify to Region 2.
- Export static files under `data/geospatial/noah/`.
- Load with Leaflet `L.geoJSON` as optional overlays or use the files for Python exposure summaries.

Pros:

- Works without third-party PMTiles availability once generated.
- Easy to intersect with municipality or barangay boundaries in the Python pipeline.

Risks:

- Source polygons are extremely dense; simplification, tiling, or per-province splitting is required.
- ODbL share-alike obligations apply to adapted derivative layers.

### Route C: ArcGIS FeatureServer overlays

Useful for quick prototypes and storm surge checks.

- Use ArcGIS REST query endpoints or a Leaflet Esri plugin.
- Query by Cagayan Valley bounding box and paginate/object-id chunk where needed.

Pros:

- No preprocessing for some layers.
- FeatureServer supports JSON/GeoJSON/PBF on layer endpoints where exposed.

Risks:

- Max record count is commonly 2,000, so direct full-region queries can truncate.
- Flood coverage through ArcGIS appears incomplete compared with the full NOAH PMTiles/shapefile route.

## Implemented Frontend Build

1. Added a `NOAH Hazards` overlay group in the Map Layers module, with toggles independent of the existing radio-button municipal layers.
2. Added all published PMTiles source layers:
   - `flood_5yr`
   - `flood_25yr`
   - `flood_100yr`
   - `landslide`
   - `debris_flow`
   - `storm_surge_ssa1`
   - `storm_surge_ssa2`
   - `storm_surge_ssa3`
   - `storm_surge_ssa4`
3. Added a source/disclaimer panel:
   - Source: Project NOAH / UP Resilience Institute / PAGASA
   - License: Open Data Commons Open Database License
   - Note: hazard maps are for planning and preparedness, not parcel-level engineering decisions.
4. Added optional ETL outputs for offline/local processing:
   - `data/geospatial/noah/*_r2.geojson`
   - `data/processed/noah/municipal_hazard_exposure.json`
5. Added municipal exposure summaries with a robust source-readiness fallback while exact clipped geometry remains pending.

## Current Workflow

Refresh administrative boundaries:

```bash
python scripts/prepare_boundary_overlays.py
```

The frontend loads NOAH from the PMTiles mirror by default. Prepare optional local NOAH overlays after clipping source hazard files to Region 2:

```bash
python scripts/prepare_noah_hazard_overlays.py
```

Compute municipal exposure analytics:

```bash
python scripts/compute_noah_municipal_exposure.py
```

Expected source filenames under `data/raw/noah/r2/`:

- `flood_100yr.geojson`
- `flood_5yr.geojson`
- `flood_25yr.geojson`
- `landslide.geojson`
- `debris_flow.geojson`
- `storm_surge_ssa1.geojson`
- `storm_surge_ssa2.geojson`
- `storm_surge_ssa3.geojson`
- `storm_surge_ssa4.geojson`

## Implementation Notes

- Use Cagayan Valley bounds roughly covering lon `120.8` to `122.7`, lat `15.6` to `21.2`, then refine with region/province boundaries.
- Preserve original hazard attributes (`Var`, `HAZ`) and add normalized fields such as `hazard_level`, `hazard_label`, `hazard_family`, `scenario`.
- For web performance, simplify polygons for zoomed-out display and keep a less simplified version only if municipal exposure calculations need it.
- The analytics script computes exact polygon intersections only when Shapely and local Region 2 hazard GeoJSON are available. Otherwise it emits source-readiness metadata so the dashboard stays accurate without fabricated exposure percentages.
- Use separate overlays instead of turning NOAH hazards into the single active radio layer, because staff will need to compare static hazard exposure against live rainfall, drought, and advisory layers.

## Sources Checked

- Project NOAH site and NOAH Studio: https://noah.up.edu.ph/
- BetterGov Project NOAH Hazard Maps dataset: https://huggingface.co/datasets/bettergovph/project-noah-hazard-maps
- ArcGIS Storm Surge Hazard Map FeatureServer: https://services1.arcgis.com/IwZZTMxZCmAmFYvF/arcgis/rest/services/Storm_Surge_Hazard_Map/FeatureServer
- ArcGIS Flood Control 5 Year FeatureServer: https://services1.arcgis.com/IwZZTMxZCmAmFYvF/ArcGIS/rest/services/Flood_Control_5_Year/FeatureServer
- ArcGIS Flood Control 25 Year FeatureServer: https://services1.arcgis.com/IwZZTMxZCmAmFYvF/ArcGIS/rest/services/Flood_Control_25_Year/FeatureServer
- RDAC Project NOAH flood catalog: https://ricelytics.philrice.gov.ph/data_catalog/dataset/100-year-rain-return-scenario-flood-hazard-maps-project-noah
- RDAC Project NOAH landslide catalog: https://ricelytics.philrice.gov.ph/data_catalog/dataset/landslide-hazard-maps-with-lidar-and-high-resolution-imagery-project-noah
