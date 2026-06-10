/**
 * cis-map.js
 * Leaflet map initialisation and layer management for APA-CIS.
 * Renders GeoJSON point layers with colour-coded markers and
 * interactive pop-ups for each municipality.
 *
 * DA RFO 02 — Climate Information Service, Cagayan Valley
 */

const CISMap = (() => {

  let _map = null;
  let _currentLayer = null;
  let _currentLayerName = 'rainfall_24h';
  let _geojsonLayer = null;

  // ── Legend definitions per layer ───────────────────────────────────────────
  const LEGENDS = {
    rainfall_24h: {
      title: 'Rainfall (24h)',
      items: [
        { color:'#E3F2FD', label:'Dry (< 1 mm)' },
        { color:'#64B5F6', label:'Light (1–10 mm)' },
        { color:'#1E88E5', label:'Moderate (10–25 mm)' },
        { color:'#1565C0', label:'Heavy (25–50 mm)' },
        { color:'#880E4F', label:'Very Heavy (50–100 mm)' },
        { color:'#B71C1C', label:'Extreme (> 100 mm)' },
      ]
    },
    drought_watch: {
      title: 'Drought Watch (CDD)',
      items: [
        { color:'#E8F5E9', label:'No dry spell (< 10 days)' },
        { color:'#FFF9C4', label:'Watch (10–13 days)' },
        { color:'#FFCC80', label:'Warning (14–20 days)' },
        { color:'#B71C1C', label:'Critical (21+ days)' },
      ]
    },
    heat_stress: {
      title: 'Heat Stress (WBGT)',
      items: [
        { color:'#4CAF50', label:'Low (WBGT < 28°C)' },
        { color:'#FF9800', label:'Moderate (28–32°C)' },
        { color:'#FF5722', label:'High (32–35°C)' },
        { color:'#B71C1C', label:'Danger (> 35°C)' },
      ]
    },
    field_workability: {
      title: 'Field Workability',
      items: [
        { color:'#4CAF50', label:'Workable' },
        { color:'#FFC107', label:'Caution' },
        { color:'#FF5722', label:'High Risk' },
        { color:'#B71C1C', label:'Not Workable' },
        { color:'#9C27B0', label:'Drought Caution' },
      ]
    },
    rainfall_anomaly: {
      title: 'Rainfall Anomaly (30-day)',
      items: [
        { color:'#B71C1C', label:'Far Below Normal (< 60%)' },
        { color:'#FF7043', label:'Below Normal (60–80%)' },
        { color:'#A5D6A7', label:'Near Normal (80–120%)' },
        { color:'#1E88E5', label:'Above Normal (120–150%)' },
        { color:'#0D47A1', label:'Far Above Normal (> 150%)' },
      ]
    },
    crop_risk: {
      title: 'Crop Stage Risk',
      items: [
        { color:'#4CAF50', label:'Minimal (0–1)' },
        { color:'#FFC107', label:'Low (1–2)' },
        { color:'#FF9800', label:'Moderate (2–3)' },
        { color:'#FF5722', label:'High (3–4)' },
        { color:'#B71C1C', label:'Critical (4–5)' },
      ]
    },
    municipal_risk: {
      title: 'Municipal Risk Score',
      items: [
        { color:'#4CAF50', label:'Low (0–15)' },
        { color:'#FFC107', label:'Moderate (15–30)' },
        { color:'#FF9800', label:'Elevated (30–50)' },
        { color:'#FF5722', label:'High (50–70)' },
        { color:'#B71C1C', label:'Critical (70–100)' },
      ]
    },
    advisory_status: {
      title: 'Advisory Status',
      items: [
        { color:'#4CAF50', label:'No Active Advisory' },
        { color:'#2196F3', label:'Information' },
        { color:'#FF9800', label:'Advisory' },
        { color:'#FF5722', label:'Warning' },
        { color:'#B71C1C', label:'Danger' },
      ]
    },
  };

  // ── Colour functions per layer ─────────────────────────────────────────────
  const COLOUR_FNS = {
    rainfall_24h: (props) => {
      const mm = props.rainfall_mm;
      if (mm === null || mm === undefined) return '#E0E0E0';
      if (mm < 1)   return '#E3F2FD';
      if (mm < 10)  return '#64B5F6';
      if (mm < 25)  return '#1E88E5';
      if (mm < 50)  return '#1565C0';
      if (mm < 100) return '#880E4F';
      return '#B71C1C';
    },
    drought_watch:    (props) => props.color || '#E0E0E0',
    heat_stress:      (props) => props.color || '#4CAF50',
    field_workability:(props) => props.color || '#4CAF50',
    rainfall_anomaly: (props) => props.color || '#A5D6A7',
    crop_risk:        (props) => props.color || '#4CAF50',
    municipal_risk:   (props) => props.color || '#4CAF50',
    advisory_status:  (props) => props.color || '#4CAF50',
  };

  // ── Popup content builders ─────────────────────────────────────────────────
  const POPUP_FNS = {
    rainfall_24h: (props) => `
      <b>${props.municipality}</b><br>
      <span style="color:#546E7A">${props.province}</span><br>
      <hr style="margin:4px 0">
      Rainfall (24h): <b>${props.rainfall_mm !== null ? props.rainfall_mm + ' mm' : '—'}</b><br>
      Class: <b>${(props.class || '').replace('_', ' ')}</b>
    `,
    drought_watch: (props) => `
      <b>${props.municipality}</b><br>
      <span style="color:#546E7A">${props.province}</span><br>
      <hr style="margin:4px 0">
      CDD: <b>${props.cdd ?? '—'} days</b><br>
      Status: <b style="color:${props.color}">${(props.drought_class || 'unknown').toUpperCase()}</b>
    `,
    heat_stress: (props) => `
      <b>${props.municipality}</b><br>
      <span style="color:#546E7A">${props.province}</span><br>
      <hr style="margin:4px 0">
      WBGT: <b>${props.wbgt ?? '—'}°C</b><br>
      Status: <b style="color:${props.color}">${(props.heat_class || '').toUpperCase()}</b><br>
      T-max: <b>${props.tmax_c ?? '—'}°C</b>
    `,
    field_workability: (props) => `
      <b>${props.municipality}</b><br>
      <span style="color:#546E7A">${props.province}</span><br>
      <hr style="margin:4px 0">
      Field Status: <b style="color:${props.color}">${(props.workability_class || '').replace('_',' ')}</b><br>
      <small>${props.workability_label || ''}</small>
    `,
    rainfall_anomaly: (props) => `
      <b>${props.municipality}</b><br>
      <span style="color:#546E7A">${props.province}</span><br>
      <hr style="margin:4px 0">
      Anomaly: <b>${props.anomaly_mm !== null ? (props.anomaly_mm > 0 ? '+' : '') + props.anomaly_mm + ' mm' : '—'}</b><br>
      % of Normal: <b>${props.pct_of_normal ?? '—'}%</b><br>
      Class: <b>${(props.anomaly_class || '').replace('_',' ')}</b>
    `,
    crop_risk: (props) => `
      <b>${props.municipality}</b><br>
      <span style="color:#546E7A">${props.province}</span><br>
      <hr style="margin:4px 0">
      Crop: <b>${(props.crop || '').replace('_',' ')}</b><br>
      Risk Score: <b style="color:${props.color}">${props.risk_score ?? '—'}/5</b><br>
      Class: <b>${(props.risk_class || '').toUpperCase()}</b>
    `,
    municipal_risk: (props) => `
      <b>${props.municipality}</b><br>
      <span style="color:#546E7A">${props.province}</span><br>
      <hr style="margin:4px 0">
      Risk Score: <b style="color:${props.color}">${props.risk_score ?? '—'}/100</b>
    `,
    advisory_status: (props) => `
      <b>${props.municipality}</b><br>
      <span style="color:#546E7A">${props.province}</span><br>
      <hr style="margin:4px 0">
      Advisory Status: <b style="color:${props.color}">${(props.severity || 'none').toUpperCase()}</b><br>
      ${props.advisory_count ? `Active advisories: <b>${props.advisory_count}</b><br>` : ''}
      ${props.primary_advisory ? `<small>${props.primary_advisory}</small>` : ''}
    `,
  };

  // ── Initialise Leaflet map ─────────────────────────────────────────────────
  function init(containerId = 'leaflet-map') {
    if (_map) return; // Already initialised

    _map = L.map(containerId, {
      center: [17.2, 121.8],   // Cagayan Valley centroid
      zoom: 8,
      zoomControl: true,
      attributionControl: true,
    });

    // OSM base tile
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      attribution: '© OpenStreetMap contributors',
      maxZoom: 18,
    }).addTo(_map);

    // Satellite overlay option (disabled by default)
    const satellite = L.tileLayer(
      'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
      { attribution: 'Tiles © Esri', maxZoom: 18, opacity: 0 }
    );

    // Region 2 boundary label
    L.control.scale({ imperial: false }).addTo(_map);
  }

  // ── Switch active layer ────────────────────────────────────────────────────
  async function switchLayer(layerName) {
    if (!_map) {
      console.error('Map not initialised. Call CISMap.init() first.');
      return;
    }

    _currentLayerName = layerName;

    // Remove existing GeoJSON layer
    if (_geojsonLayer) {
      _map.removeLayer(_geojsonLayer);
      _geojsonLayer = null;
    }

    try {
      const geojson = await CISData.getGeoJSON(layerName);
      _renderGeoJSONLayer(geojson, layerName);
      _updateLegend(layerName);
      _updateLayerSidebarActive(layerName);
      _updateDataInfo(layerName);
    } catch (err) {
      console.warn(`Could not load layer ${layerName}:`, err);
      // If no real data yet, show demo circles on the map
      _renderDemoLayer(layerName);
      _updateLegend(layerName);
      _updateLayerSidebarActive(layerName);
    }
  }

  // ── Render GeoJSON features as circle markers ─────────────────────────────
  function _renderGeoJSONLayer(geojson, layerName) {
    const colorFn = COLOUR_FNS[layerName] || (() => '#2196F3');
    const popupFn = POPUP_FNS[layerName] || ((p) => `<b>${p.municipality}</b>`);

    _geojsonLayer = L.geoJSON(geojson, {
      pointToLayer: (feature, latlng) => {
        const color = colorFn(feature.properties);
        return L.circleMarker(latlng, {
          radius: 9,
          fillColor: color,
          color: 'rgba(0,0,0,0.3)',
          weight: 1,
          opacity: 1,
          fillOpacity: 0.85,
        });
      },
      onEachFeature: (feature, layer) => {
        const p = feature.properties;
        layer.bindPopup(
          `<div style="font-size:12px;min-width:140px;line-height:1.6">${popupFn(p)}</div>`,
          { maxWidth: 220, offset: [0, -4] }
        );
        layer.on('mouseover', function() { this.openPopup(); });
      },
    }).addTo(_map);
  }

  // ── Demo circles (no real data) ────────────────────────────────────────────
  function _renderDemoLayer(layerName) {
    const rows = CISData.getMunicipalRows('all');
    if (!rows.length) return;

    const features = rows.map(r => ({
      type: 'Feature',
      geometry: { type: 'Point', coordinates: [r.lon, r.lat] },
      properties: {
        municipality: r.municipality,
        province: r.province,
        rainfall_mm: r.observations?.rainfall_24h_mm,
        drought_class: r.indicators?.drought_class,
        heat_class: r.indicators?.heat_stress?.heat_class,
        color: _getDemoColor(layerName, r),
        workability_class: r.indicators?.field_workability?.overall_class,
        risk_score: r.indicators?.municipal_risk_score,
        anomaly_class: r.indicators?.rainfall_anomaly?.anomaly_class,
        pct_of_normal: r.indicators?.rainfall_anomaly?.pct_of_normal,
        anomaly_mm: r.indicators?.rainfall_anomaly?.anomaly_mm,
        tmax_c: r.observations?.tmax_c,
        wbgt: r.indicators?.heat_stress?.wbgt_approx,
        cdd: r.indicators?.cdd,
      }
    }));

    _renderGeoJSONLayer({ type: 'FeatureCollection', features }, layerName);
  }

  function _getDemoColor(layerName, r) {
    if (layerName === 'drought_watch') {
      const m = { none:'#E8F5E9', watch:'#FFF9C4', warning:'#FFCC80', critical:'#B71C1C' };
      return m[r.indicators?.drought_class] || '#E0E0E0';
    }
    if (layerName === 'heat_stress') {
      const m = { low:'#4CAF50', moderate:'#FF9800', high:'#FF5722', danger:'#B71C1C' };
      return m[r.indicators?.heat_stress?.heat_class] || '#4CAF50';
    }
    return '#1E88E5';
  }

  // ── Legend renderer ────────────────────────────────────────────────────────
  function _updateLegend(layerName) {
    const el = document.getElementById('map-legend');
    if (!el) return;
    const def = LEGENDS[layerName];
    if (!def) { el.innerHTML = ''; return; }

    el.innerHTML = `
      <div class="legend-title">${def.title}</div>
      ${def.items.map(item => `
        <div class="legend-item">
          <span class="legend-swatch" style="background:${item.color}"></span>
          ${item.label}
        </div>
      `).join('')}
    `;
  }

  function _updateLayerSidebarActive(layerName) {
    document.querySelectorAll('.layer-item').forEach(el => el.classList.remove('active-layer'));
    const active = document.getElementById(`li-${layerName}`);
    if (active) active.classList.add('active-layer');
  }

  function _updateDataInfo(layerName) {
    const asofEl = document.getElementById('map-asof-label');
    const meta = CISData.getPipelineStatus();
    if (asofEl && meta) {
      asofEl.textContent = meta.as_of_date || '—';
    }
  }

  // ── Fly to a municipality ──────────────────────────────────────────────────
  function flyTo(lat, lon, zoom = 12) {
    if (_map) _map.flyTo([lat, lon], zoom, { duration: 1.2 });
  }

  // ── Expose ─────────────────────────────────────────────────────────────────
  return { init, switchLayer, flyTo };
})();
