/**
 * cis-noah-map.js
 * Complete Project NOAH PMTiles hazard map for APA-CIS.
 */

const CISNOAHMap = (() => {
  const PMTILES_URL = 'https://huggingface.co/datasets/bettergovph/project-noah-hazard-maps/resolve/main/PMTiles/noah_hazard_maps.pmtiles';
  const SOURCE_URL = `pmtiles://${PMTILES_URL}`;
  const activeLayers = new Set();
  let map = null;
  let loadPromise = null;

  const LAYERS = {
    flood_5yr: {
      id: 'noah-flood-5yr',
      sourceLayer: 'flood_5yr',
      label: 'Flood 5-Year',
      attribute: 'Var',
      colors: { 1: '#bfdbfe', 2: '#60a5fa', 3: '#2563eb' },
    },
    flood_25yr: {
      id: 'noah-flood-25yr',
      sourceLayer: 'flood_25yr',
      label: 'Flood 25-Year',
      attribute: 'Var',
      colors: { 1: '#a7f3d0', 2: '#34d399', 3: '#047857' },
    },
    flood_100yr: {
      id: 'noah-flood-100yr',
      sourceLayer: 'flood_100yr',
      label: 'Flood 100-Year',
      attribute: 'Var',
      colors: { 1: '#93c5fd', 2: '#3b82f6', 3: '#1d4ed8' },
    },
    landslide: {
      id: 'noah-landslide',
      sourceLayer: 'landslide',
      label: 'Landslide',
      attribute: 'HAZ',
      colors: { 1: '#fde68a', 2: '#f59e0b', 3: '#b45309' },
    },
    debris_flow: {
      id: 'noah-debris-flow',
      sourceLayer: 'debris_flow',
      label: 'Debris Flow',
      attribute: 'HAZ',
      colors: { 1: '#fde68a', 2: '#f59e0b', 3: '#b45309' },
    },
    storm_surge_ssa1: {
      id: 'noah-storm-surge-ssa1',
      sourceLayer: 'storm_surge_ssa1',
      label: 'Storm Surge SSA 1',
      attribute: 'HAZ',
      colors: { 1: '#fef9c3', 2: '#fde047', 3: '#ca8a04' },
    },
    storm_surge_ssa2: {
      id: 'noah-storm-surge-ssa2',
      sourceLayer: 'storm_surge_ssa2',
      label: 'Storm Surge SSA 2',
      attribute: 'HAZ',
      colors: { 1: '#fed7aa', 2: '#fb923c', 3: '#c2410c' },
    },
    storm_surge_ssa3: {
      id: 'noah-storm-surge-ssa3',
      sourceLayer: 'storm_surge_ssa3',
      label: 'Storm Surge SSA 3',
      attribute: 'HAZ',
      colors: { 1: '#fecaca', 2: '#ef4444', 3: '#b91c1c' },
    },
    storm_surge_ssa4: {
      id: 'noah-storm-surge-ssa4',
      sourceLayer: 'storm_surge_ssa4',
      label: 'Storm Surge SSA 4',
      attribute: 'HAZ',
      colors: { 1: '#fecdd3', 2: '#f43f5e', 3: '#9f1239' },
    },
  };

  function toggleLayer(layerName, enabled) {
    const layerDef = LAYERS[layerName];
    if (!layerDef) return;

    if (enabled) activeLayers.add(layerName);
    else activeLayers.delete(layerName);

    if (!activeLayers.size) {
      _showNOAHMode(false);
      _setStatus('Optional overlays load only when selected.');
      return;
    }

    _showNOAHMode(true);
    _loadMap()
      .then(() => {
        Object.entries(LAYERS).forEach(([name, def]) => {
          if (map.getLayer(def.id)) {
            map.setLayoutProperty(def.id, 'visibility', activeLayers.has(name) ? 'visible' : 'none');
          }
        });
        _setStatus(`Project NOAH PMTiles active: ${Array.from(activeLayers).map(name => LAYERS[name].label).join(', ')}.`);
      })
      .catch((err) => {
        console.warn('Could not initialize Project NOAH PMTiles map:', err);
        _setStatus('Project NOAH PMTiles could not load. Check internet access and retry.');
      });
  }

  function _loadMap() {
    if (loadPromise) return loadPromise;
    loadPromise = new Promise((resolve, reject) => {
      if (!window.maplibregl || !window.pmtiles) {
        reject(new Error('MapLibre GL JS or PMTiles library is unavailable.'));
        return;
      }

      const protocol = new pmtiles.Protocol();
      maplibregl.addProtocol('pmtiles', protocol.tile);

      map = new maplibregl.Map({
        container: 'noah-map',
        center: [121.8, 17.2],
        zoom: 7,
        maxZoom: 14,
        style: {
          version: 8,
          sources: {
            osm: {
              type: 'raster',
              tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
              tileSize: 256,
              attribution: '© OpenStreetMap contributors',
            },
            noah: {
              type: 'vector',
              url: SOURCE_URL,
              attribution: 'Project NOAH / UP Resilience Institute / PAGASA; BetterGov mirror; ODC-ODbL',
            },
          },
          layers: [
            { id: 'osm', type: 'raster', source: 'osm' },
          ],
        },
      });

      map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right');
      map.addControl(new maplibregl.ScaleControl({ unit: 'metric' }), 'bottom-left');

      map.on('load', () => {
        Object.entries(LAYERS).forEach(([name, def]) => _addHazardLayer(name, def));
        map.resize();
        resolve();
      });
      map.on('error', (event) => {
        if (!map.loaded()) reject(event.error || new Error('MapLibre load error'));
      });
    });
    return loadPromise;
  }

  function _addHazardLayer(name, def) {
    if (map.getLayer(def.id)) return;
    map.addLayer({
      id: def.id,
      type: 'fill',
      source: 'noah',
      'source-layer': def.sourceLayer,
      layout: { visibility: activeLayers.has(name) ? 'visible' : 'none' },
      paint: {
        'fill-color': [
          'match',
          ['to-number', ['get', def.attribute]],
          1, def.colors[1],
          2, def.colors[2],
          3, def.colors[3],
          'rgba(158,158,158,0.35)',
        ],
        'fill-opacity': 0.55,
        'fill-outline-color': 'rgba(26,26,46,0.28)',
      },
    });

    map.on('click', def.id, (event) => {
      const props = event.features?.[0]?.properties || {};
      const rawLevel = Number(props[def.attribute]);
      const levelLabel = { 1: 'Low', 2: 'Medium', 3: 'High' }[rawLevel] || 'Unknown';
      new maplibregl.Popup()
        .setLngLat(event.lngLat)
        .setHTML(`
          <div style="font-size:12px;line-height:1.55">
            <b>Project NOAH ${def.label}</b><br>
            Hazard level: <b>${levelLabel}</b><br>
            <small>Planning and preparedness overlay. Verify before high-impact decisions.</small>
          </div>
        `)
        .addTo(map);
    });

    map.on('mouseenter', def.id, () => { map.getCanvas().style.cursor = 'pointer'; });
    map.on('mouseleave', def.id, () => { map.getCanvas().style.cursor = ''; });
  }

  function _showNOAHMode(enabled) {
    const leafletEl = document.getElementById('leaflet-map');
    const noahEl = document.getElementById('noah-map');
    if (!leafletEl || !noahEl) return;
    leafletEl.hidden = enabled;
    noahEl.hidden = !enabled;
    if (enabled && map) map.resize();
  }

  function _setStatus(message) {
    const el = document.getElementById('map-overlay-status');
    if (el) el.textContent = message;
  }

  return { toggleLayer };
})();
