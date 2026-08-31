/**
 * cis-data.js
 * Central data loader for APA-CIS frontend.
 * Fetches, caches, and normalises all JSON data files
 * produced by the Python ETL pipeline.
 *
 * DA RFO 02 — Climate Information Service, Cagayan Valley
 */

const CISData = (() => {

  // ── Data paths (relative to frontend root) ─────────────────────────────────
  const PATHS = {
    indicators:    '../data/processed/indicators/indicators_latest.json',
    advisories:    '../data/advisories/daily/advisories_latest.json',
    regionalBulletin:'../data/advisories/daily/regional_bulletin_latest.txt',
    pipelineStatus:'../data/pipeline_status.json',
    pagasaData:    '../data/raw/pagasa/pagasa_current.json',
    acapData:      '../data/raw/acap/acap_current.json',
    acapCropCalendars:'../data/reference/acap_cropping_calendars.json',
    noahOverlayCatalog:'../data/reference/noah_hazard_overlays.json',
    noahExposure:  '../data/processed/noah/municipal_hazard_exposure.json',
    boundaries: {
      provinces:      '../data/boundaries/provinces_simplified.geojson',
      districts:      '../data/boundaries/districts_simplified.geojson',
      municipalities: '../data/boundaries/municipalities_simplified.geojson',
      barangays:      '../data/boundaries/barangay_boundaries.geojson',
    },
    noahGeojson: {
      flood_5yr:       '../data/geospatial/noah/flood_5yr_r2.geojson',
      flood_25yr:      '../data/geospatial/noah/flood_25yr_r2.geojson',
      flood_100yr:      '../data/geospatial/noah/flood_100yr_r2.geojson',
      landslide:        '../data/geospatial/noah/landslide_r2.geojson',
      debris_flow:      '../data/geospatial/noah/debris_flow_r2.geojson',
      storm_surge_ssa1: '../data/geospatial/noah/storm_surge_ssa1_r2.geojson',
      storm_surge_ssa2: '../data/geospatial/noah/storm_surge_ssa2_r2.geojson',
      storm_surge_ssa3: '../data/geospatial/noah/storm_surge_ssa3_r2.geojson',
      storm_surge_ssa4: '../data/geospatial/noah/storm_surge_ssa4_r2.geojson',
    },
    geojson: {
      rainfall_24h:     '../data/geospatial/rainfall_24h.geojson',
      drought_watch:    '../data/geospatial/drought_watch.geojson',
      heat_stress:      '../data/geospatial/heat_stress.geojson',
      field_workability:'../data/geospatial/field_workability.geojson',
      rainfall_anomaly: '../data/geospatial/rainfall_anomaly.geojson',
      crop_risk:        '../data/geospatial/crop_risk.geojson',
      drying_risk:      '../data/geospatial/drying_risk.geojson',
      municipal_risk:   '../data/geospatial/municipal_risk.geojson',
      advisory_status:  '../data/geospatial/advisory_status.geojson',
    }
  };

  // ── In-memory cache ────────────────────────────────────────────────────────
  const _cache = {};
  let _currentProvince = 'all';
  let _indicators = null;
  let _advisories = null;
  let _pagasaData = null;
  let _acapData = null;
  let _acapCropCalendars = null;
  let _noahExposure = null;
  let _pipelineStatus = null;
  let _municipalities = null; // Loaded from municipalities.json

  // ── Public API ─────────────────────────────────────────────────────────────

  /**
   * Load all required data for initial render.
   * Returns promise resolving to { indicators, advisories, status }
   */
  async function loadAll() {
    try {
      const [indicatorsResult, advisoriesResult, statusResult, pagasaResult, acapResult, acapCalendarResult, noahExposureResult] = await Promise.allSettled([
        fetchJSON(PATHS.indicators),
        fetchJSON(PATHS.advisories),
        fetchJSON(PATHS.pipelineStatus),
        fetchJSON(PATHS.pagasaData, { bustCache: true }),
        fetchJSON(PATHS.acapData),
        fetchJSON(PATHS.acapCropCalendars),
        fetchJSON(PATHS.noahExposure),
      ]);

      if (indicatorsResult.status !== 'fulfilled') throw indicatorsResult.reason;
      const indicators = indicatorsResult.value;
      const advisories = advisoriesResult.status === 'fulfilled' ? advisoriesResult.value : null;
      const status = statusResult.status === 'fulfilled' ? statusResult.value : null;
      const pagasaData = pagasaResult.status === 'fulfilled' ? pagasaResult.value : null;
      const acapData = acapResult.status === 'fulfilled' ? acapResult.value : null;
      const acapCropCalendars = acapCalendarResult.status === 'fulfilled' ? acapCalendarResult.value : null;
      const noahExposure = noahExposureResult.status === 'fulfilled' ? noahExposureResult.value : null;

      _indicators = indicators;
      _advisories = advisories;
      _pagasaData = pagasaData;
      _acapData = acapData;
      _acapCropCalendars = acapCropCalendars;
      _noahExposure = noahExposure;
      _pipelineStatus = status;

      return { indicators, advisories, status, pagasaData, acapData, acapCropCalendars, noahExposure };
    } catch (err) {
      console.warn('CISData.loadAll using demo fallback:', err);
      // Return demo/sample data so the UI doesn't stay blank during dev
      _indicators = _getDemoIndicators();
      _advisories = null;
      _pagasaData = null;
      _acapData = null;
      _acapCropCalendars = null;
      _noahExposure = null;
      _pipelineStatus = null;
      return { indicators: _indicators, advisories: _advisories, status: _pipelineStatus };
    }
  }

  /**
   * Get a GeoJSON layer by name.
   */
  async function getGeoJSON(layerName) {
    if (_cache[layerName]) return _cache[layerName];
    const path = PATHS.geojson[layerName];
    if (!path) throw new Error(`Unknown layer: ${layerName}`);
    const data = await fetchJSON(path);
    _cache[layerName] = data;
    return data;
  }

  async function getBoundaryGeoJSON(layerName) {
    const cacheKey = `boundary:${layerName}`;
    if (_cache[cacheKey]) return _cache[cacheKey];
    const path = PATHS.boundaries[layerName];
    if (!path) throw new Error(`Unknown boundary layer: ${layerName}`);
    const data = await fetchJSON(path);
    _cache[cacheKey] = data;
    return data;
  }

  async function getNOAHGeoJSON(layerName) {
    const cacheKey = `noah:${layerName}`;
    if (_cache[cacheKey]) return _cache[cacheKey];
    const path = PATHS.noahGeojson[layerName];
    if (!path) throw new Error(`Unknown NOAH layer: ${layerName}`);
    const data = await fetchJSON(path);
    _cache[cacheKey] = data;
    return data;
  }

  async function getNOAHOverlayCatalog() {
    if (_cache.noahOverlayCatalog) return _cache.noahOverlayCatalog;
    const data = await fetchJSON(PATHS.noahOverlayCatalog);
    _cache.noahOverlayCatalog = data;
    return data;
  }

  function getNOAHExposure() {
    return _noahExposure;
  }

  async function getRegionalBulletin() {
    return fetchText(PATHS.regionalBulletin);
  }

  /**
   * Get all municipal indicator records, optionally filtered by province.
   */
  function getMunicipalRows(province = 'all') {
    if (!_indicators || !_indicators.data) return [];
    const rows = Object.values(_indicators.data);
    if (province === 'all') return rows;
    return rows.filter(r => r.province === province);
  }

  /**
   * Get advisory data for a specific municipality by PSGC.
   */
  function getAdvisoryForMunicipality(psgc) {
    if (!_advisories || !_advisories.advisories) return null;
    return _advisories.advisories[psgc] || null;
  }

  /**
   * Get all municipalities with active advisories, filtered by severity and province.
   */
  function getActiveAdvisories(severityFilter = 'all', provinceFilter = 'all') {
    if (!_advisories || !_advisories.advisories) return [];
    const sevOrder = { danger: 0, warning: 1, advisory: 2, info: 3 };

    let items = Object.entries(_advisories.advisories).map(([psgc, data]) => ({
      psgc,
      ...data,
    }));

    if (severityFilter !== 'all') {
      const minSev = sevOrder[severityFilter] || 3;
      items = items.filter(a => (sevOrder[a.highest_severity] || 99) <= minSev);
    }
    if (provinceFilter !== 'all') {
      items = items.filter(a => a.province === provinceFilter);
    }

    items.sort((a, b) =>
      (sevOrder[a.highest_severity] || 99) - (sevOrder[b.highest_severity] || 99)
    );
    return items;
  }

  /**
   * Get indicator record for a single municipality by PSGC.
   */
  function getIndicatorByPSGC(psgc) {
    if (!_indicators || !_indicators.data) return null;
    return _indicators.data[psgc] || null;
  }

  /**
   * Compute summary stats for the stat cards (filtered by province).
   */
  function getSummaryStats(province = 'all') {
    const rows = getMunicipalRows(province);
    if (!rows.length) return null;

    const rainfallValues = rows
      .map(r => r.observations?.rainfall_24h_mm)
      .filter(v => v !== null && v !== undefined);

    const tmaxValues = rows
      .map(r => r.observations?.tmax_c)
      .filter(v => v !== null && v !== undefined);

    const droughtMuns = rows.filter(r =>
      r.indicators?.drought_class && r.indicators.drought_class !== 'none'
    );

    const heatHighMuns = rows.filter(r =>
      ['high', 'danger'].includes(r.indicators?.heat_stress?.heat_class)
    );

    const workableMuns = rows.filter(r =>
      r.indicators?.field_workability?.overall_class === 'workable'
    );

    // Active advisories for this province set
    let advCount = 0;
    if (_advisories && _advisories.advisories) {
      advCount = Object.values(_advisories.advisories)
        .filter(a => province === 'all' || a.province === province)
        .length;
    }

    return {
      avgRainfall: rainfallValues.length
        ? (rainfallValues.reduce((a, b) => a + b, 0) / rainfallValues.length).toFixed(1)
        : '—',
      maxTmax: tmaxValues.length ? Math.max(...tmaxValues).toFixed(1) : '—',
      maxTmaxMun: tmaxValues.length
        ? rows.find(r => r.observations?.tmax_c === Math.max(...tmaxValues))?.municipality
        : '',
      droughtCount: droughtMuns.length,
      droughtCritical: droughtMuns.filter(r => r.indicators?.drought_class === 'critical').length,
      activeAdvisories: advCount,
      heatHighCount: heatHighMuns.length,
      workableCount: workableMuns.length,
      totalMuns: rows.length,
    };
  }

  /**
   * Get priority municipality list from advisory report.
   */
  function getPriorityMunicipalities(limit = 20) {
    if (!_advisories || !_advisories.priority_municipalities) return [];
    return _advisories.priority_municipalities.slice(0, limit);
  }

  /**
   * Get province summary from advisory report.
   */
  function getProvinceSummary() {
    return _advisories?.summary_by_province || {};
  }

  /**
   * Get pipeline status / data freshness.
   */
  function getPipelineStatus() {
    return {
      ...(_pipelineStatus || {}),
      ...(_indicators?.meta || {}),
      pipeline_last_run: _pipelineStatus?.last_run || null,
      pipeline_data_as_of: _pipelineStatus?.data_as_of || null,
      pipeline_steps: _pipelineStatus?.steps || null,
      pipeline_status: _pipelineStatus?.status || null,
    };
  }

  function getPAGASAData() {
    return _pagasaData;
  }

  function getACAPData() {
    return _acapData;
  }

  function getACAPCropCalendars() {
    return _acapCropCalendars;
  }

  /**
   * Set current province filter (affects getMunicipalRows default).
   */
  function setProvince(province) {
    _currentProvince = province;
  }

  // ── Formatters ─────────────────────────────────────────────────────────────

  function formatRainfall(mm) {
    if (mm === null || mm === undefined) return '—';
    return `${parseFloat(mm).toFixed(1)} mm`;
  }

  function formatTemp(c) {
    if (c === null || c === undefined) return '—';
    return `${parseFloat(c).toFixed(1)}°C`;
  }

  function formatPercent(pct) {
    if (pct === null || pct === undefined) return '—';
    return `${pct}%`;
  }

  function severityPill(severity) {
    const map = {
      danger: ['pill pill-danger', '🔴 Danger'],
      warning: ['pill pill-warning', '🟠 Warning'],
      advisory: ['pill pill-advisory', '🟡 Advisory'],
      info: ['pill pill-unknown', 'ℹ Info'],
      none: ['pill pill-safe', '✅ Clear'],
    };
    const [cls, label] = map[severity] || ['pill pill-none', severity || '—'];
    return `<span class="${cls}">${label}</span>`;
  }

  function droughtPill(cls) {
    const map = {
      critical: ['pill pill-danger', 'Critical'],
      warning:  ['pill pill-warning', 'Warning'],
      watch:    ['pill pill-advisory', 'Watch'],
      none:     ['pill pill-safe', 'None'],
    };
    const [pcls, label] = map[cls] || ['pill pill-none', '—'];
    return `<span class="${pcls}">${label}</span>`;
  }

  function heatPill(cls) {
    const map = {
      danger:   ['pill pill-danger', 'Danger'],
      high:     ['pill pill-warning', 'High'],
      moderate: ['pill pill-advisory', 'Moderate'],
      low:      ['pill pill-safe', 'Low'],
    };
    const [pcls, label] = map[cls] || ['pill pill-none', '—'];
    return `<span class="${pcls}">${label}</span>`;
  }

  function workabilityPill(cls) {
    const map = {
      workable:        ['pill pill-safe', 'Workable'],
      caution:         ['pill pill-advisory', 'Caution'],
      high_risk:       ['pill pill-warning', 'High Risk'],
      not_workable:    ['pill pill-danger', 'Not Workable'],
      drought_caution: ['pill pill-advisory', 'Drought'],
    };
    const [pcls, label] = map[cls] || ['pill pill-none', '—'];
    return `<span class="${pcls}">${label}</span>`;
  }

  function riskScoreBadge(score) {
    if (score === null || score === undefined) return '<span class="pill pill-none">—</span>';
    let cls = score >= 70 ? 'pill-danger' : score >= 50 ? 'pill-warning' :
              score >= 30 ? 'pill-advisory' : 'pill-safe';
    return `<span class="pill ${cls}">${score}</span>`;
  }

  // ── Internal helpers ───────────────────────────────────────────────────────

  async function fetchJSON(url, options = {}) {
    const requestUrl = options.bustCache ? _withCacheBuster(url) : url;
    const resp = await fetch(requestUrl, options.bustCache ? { cache: 'no-store' } : undefined);
    if (!resp.ok) throw new Error(`HTTP ${resp.status} for ${url}`);
    return resp.json();
  }

  function _withCacheBuster(url) {
    const separator = url.includes('?') ? '&' : '?';
    return `${url}${separator}v=${Date.now()}`;
  }

  async function fetchText(url) {
    const resp = await fetch(url);
    if (!resp.ok) throw new Error(`HTTP ${resp.status} for ${url}`);
    return resp.text();
  }

  /**
   * Demo/fallback data when running without a backend (dev mode).
   * Generates synthetic records for all 92 municipalities.
   */
  function _getDemoIndicators() {
    const provinces = {
      '0231': 'Cagayan', '0314': 'Isabela',
      '0356': 'Nueva Vizcaya', '0670': 'Quirino', '0201': 'Batanes'
    };
    const data = {};
    const droughtClasses = ['none', 'none', 'none', 'watch', 'warning', 'critical'];
    const heatClasses = ['low', 'moderate', 'high', 'danger'];
    const workClasses = ['workable', 'workable', 'caution', 'high_risk', 'not_workable'];

    // Synthetic placeholder rows — will be replaced once pipeline runs
    const DEMO_MUNIS = [
      {psgc:'023101000', name:'City of Tuguegarao', province:'Cagayan', lat:17.6132, lon:121.7270},
      {psgc:'023106000', name:'Aparri', province:'Cagayan', lat:18.3567, lon:121.6406},
      {psgc:'031401000', name:'City of Ilagan', province:'Isabela', lat:17.1486, lon:121.8693},
      {psgc:'031409000', name:'Cauayan City', province:'Isabela', lat:16.9300, lon:121.7750},
      {psgc:'031435000', name:'Santiago City', province:'Isabela', lat:16.6875, lon:121.5503},
      {psgc:'035601000', name:'Bayombong', province:'Nueva Vizcaya', lat:16.4832, lon:121.1497},
      {psgc:'035613000', name:'Solano', province:'Nueva Vizcaya', lat:16.5230, lon:121.1890},
      {psgc:'067001000', name:'Cabarroguis', province:'Quirino', lat:16.5113, lon:121.5088},
      {psgc:'020100000', name:'Basco', province:'Batanes', lat:20.4487, lon:121.9701},
    ];

    DEMO_MUNIS.forEach((m, i) => {
      const rain = Math.random() * 40;
      const cdd = Math.floor(Math.random() * 25);
      const tmax = 28 + Math.random() * 10;
      const humidity = 60 + Math.random() * 30;
      const droughtCls = cdd >= 21 ? 'critical' : cdd >= 14 ? 'warning' : cdd >= 10 ? 'watch' : 'none';
      const heatIdx = tmax > 37 ? 3 : tmax > 35 ? 2 : tmax > 32 ? 1 : 0;
      const riskScore = Math.round(Math.random() * 80);

      data[m.psgc] = {
        psgc: m.psgc, municipality: m.name, province: m.province,
        lat: m.lat, lon: m.lon,
        as_of_date: new Date().toISOString().slice(0,10),
        observations: {
          rainfall_24h_mm: parseFloat(rain.toFixed(1)),
          tmax_c: parseFloat(tmax.toFixed(1)),
          tmin_c: parseFloat((tmax - 7 - Math.random()*3).toFixed(1)),
          tmean_c: parseFloat((tmax - 3.5).toFixed(1)),
          humidity_pct: parseFloat(humidity.toFixed(0)),
          wind_speed_ms: parseFloat((2 + Math.random()*4).toFixed(1)),
        },
        indicators: {
          cdd, drought_class: droughtCls, cwd: 0,
          rainfall_anomaly: { anomaly_mm: rain - 15, pct_of_normal: 60 + Math.random()*80, anomaly_class: 'near_normal' },
          heat_stress: { heat_class: heatClasses[heatIdx], wbgt_approx: 28 + Math.random()*10, heat_color: '#FF9800' },
          eto_mm: parseFloat((3 + Math.random()*3).toFixed(2)),
          irrigation_demand: { demand_mm: Math.max(0, 5 - rain/10), demand_class: 'moderate', priority: 'medium' },
          field_workability: { overall_class: rain > 50 ? 'not_workable' : cdd > 14 ? 'drought_caution' : 'workable', operations: {} },
          municipal_risk_score: riskScore,
        },
        _demo: true,
      };
    });

    return {
      meta: { generated_at: new Date().toISOString(), as_of_date: new Date().toISOString().slice(0,10), municipality_count: DEMO_MUNIS.length, _demo: true },
      data,
    };
  }

  // ── Public surface ─────────────────────────────────────────────────────────
  return {
    loadAll, getGeoJSON, getBoundaryGeoJSON, getNOAHGeoJSON,
    getNOAHOverlayCatalog, getNOAHExposure, getRegionalBulletin, getMunicipalRows, getAdvisoryForMunicipality,
    getActiveAdvisories, getIndicatorByPSGC, getSummaryStats,
    getPriorityMunicipalities, getProvinceSummary, getPipelineStatus,
    getPAGASAData, getACAPData, getACAPCropCalendars, setProvince,
    fmt: { formatRainfall, formatTemp, formatPercent,
           severityPill, droughtPill, heatPill, workabilityPill, riskScoreBadge }
  };
})();
