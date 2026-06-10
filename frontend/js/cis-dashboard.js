/**
 * cis-dashboard.js
 * Renders the Climate Dashboard module:
 *   - 6 summary stat cards
 *   - Alert strip for critical/danger municipalities
 *   - Full municipal indicators table with search and sort
 *
 * DA RFO 02 — APA-CIS Climate Information Service
 */

const CISDashboard = (() => {

  let _currentProvince = 'all';
  let _sortKey = 'risk';
  let _sortDir = 'desc';
  let _searchTerm = '';
  let _allRows = [];

  // ── Render stat cards ──────────────────────────────────────────────────────
  function renderStatCards(province = 'all') {
    const stats = CISData.getSummaryStats(province);
    if (!stats) return;

    _setCard('sc-rainfall-val', stats.avgRainfall + ' mm', stats.avgRainfall > 50 ? 'warning-card' : '');
    _setCard('sc-temp-val', stats.maxTmax + '°C',
      parseFloat(stats.maxTmax) >= 36 ? 'danger-card' : parseFloat(stats.maxTmax) >= 33 ? 'warning-card' : '');
    document.getElementById('sc-temp-sub').textContent = stats.maxTmaxMun || '';

    _setCard('sc-drought-val', stats.droughtCount, stats.droughtCritical > 0 ? 'danger-card' : stats.droughtCount > 0 ? 'warning-card' : '');
    document.getElementById('sc-drought-sub').textContent =
      stats.droughtCritical > 0 ? `${stats.droughtCritical} in critical` : '';

    _setCard('sc-advisory-val', stats.activeAdvisories, stats.activeAdvisories > 0 ? 'warning-card' : '');
    _setCard('sc-heat-val', stats.heatHighCount, stats.heatHighCount > 3 ? 'warning-card' : '');
    _setCard('sc-workability-val', `${stats.workableCount}/${stats.totalMuns}`,
      stats.workableCount / (stats.totalMuns || 1) < 0.5 ? 'warning-card' : '');
    document.getElementById('sc-workability-sub').textContent = 'safe for field operations today';
  }

  function renderSourcePanel() {
    const rainfallEl = document.getElementById('source-rainfall');
    const pagasaEl = document.getElementById('source-pagasa');
    const rows = CISData.getMunicipalRows('all');
    const pagasa = CISData.getPAGASAData();

    if (rainfallEl && rows.length) {
      const cisCount = rows.filter(r => r.observations?.rainfall_source === 'apa_cis').length;
      const chirpsCount = rows.filter(r => r.observations?.rainfall_source === 'chirps').length;
      const nasaCount = rows.length - cisCount - chirpsCount;
      rainfallEl.textContent = cisCount
        ? `APA CIS used in ${cisCount}; CHIRPS in ${chirpsCount}; NASA fallback in ${nasaCount}`
        : (chirpsCount
          ? `CHIRPS used in ${chirpsCount} municipalities; NASA fallback in ${nasaCount}`
          : 'NASA POWER rainfall active; APA CIS/CHIRPS fallback not yet sampled');
    }

    if (pagasaEl) {
      if (!pagasa) {
        pagasaEl.textContent = 'No current PAGASA product loaded';
      } else {
        const enso = pagasa.enso?.phase || pagasa.enso?.enso_phase || 'unknown ENSO';
        const date = pagasa.entry_date || pagasa.as_of || 'undated';
        const typhoon = pagasa.typhoon?.active ? `; TC active: ${pagasa.typhoon.name || 'yes'}` : '';
        pagasaEl.textContent = `${enso} as of ${date}${typhoon}`;
      }
    }
  }

  function _setCard(valueId, value, extraClass = '') {
    const el = document.getElementById(valueId);
    if (!el) return;
    el.textContent = value;
    const card = el.closest('.stat-card');
    if (card) {
      card.classList.remove('danger-card', 'warning-card');
      if (extraClass) card.classList.add(extraClass);
    }
  }

  // ── Render alert strip ────────────────────────────────────────────────────
  function renderAlertStrip(province = 'all') {
    const strip = document.getElementById('alert-strip');
    if (!strip) return;

    const advisories = CISData.getActiveAdvisories('danger', province);
    if (advisories.length === 0) {
      strip.classList.add('hidden');
      return;
    }

    const names = advisories.slice(0, 5).map(a =>
      `${a.municipality} (${a.province})`
    ).join(', ');
    const more = advisories.length > 5 ? ` + ${advisories.length - 5} more` : '';

    strip.innerHTML = `
      🔴 DANGER ALERT: ${advisories.length} municipalities require immediate action —
      ${names}${more}.
      <a href="#" onclick="switchModule('advisory', null); return false;" style="color:inherit;text-decoration:underline;margin-left:8px">
        View Advisories →
      </a>
    `;
    strip.classList.remove('hidden');
  }

  // ── Build and render the municipal table ───────────────────────────────────
  function renderTable(province = 'all') {
    _currentProvince = province;
    _allRows = CISData.getMunicipalRows(province);
    _applyFiltersAndRender();
  }

  function filterTable(searchTerm) {
    _searchTerm = searchTerm.toLowerCase();
    _applyFiltersAndRender();
  }

  function sortTable(key) {
    const legacy = {
      risk_desc: ['risk', 'desc'],
      drought_desc: ['drought', 'asc'],
      rain_desc: ['rainfall', 'desc'],
      alpha: ['municipality', 'asc'],
    };

    if (legacy[key]) {
      [_sortKey, _sortDir] = legacy[key];
      _applyFiltersAndRender();
      return;
    }

    if (_sortKey === key) {
      _sortDir = _sortDir === 'asc' ? 'desc' : 'asc';
    } else {
      _sortKey = key;
      _sortDir = ['municipality', 'province'].includes(key) ? 'asc' : 'desc';
    }
    _applyFiltersAndRender();
  }

  function _applyFiltersAndRender() {
    let rows = [..._allRows];

    // Search filter
    if (_searchTerm) {
      rows = rows.filter(r =>
        r.municipality.toLowerCase().includes(_searchTerm) ||
        r.province.toLowerCase().includes(_searchTerm)
      );
    }

    // Sort
    rows = _sortRows(rows, _sortKey, _sortDir);

    _renderTableRows(rows);
    _renderSortIndicators();
  }

  function _sortRows(rows, key, dir) {
    const dOrder = { critical:0, warning:1, watch:2, none:3 };
    const heatOrder = { danger:0, high:1, moderate:2, low:3 };
    const workOrder = { not_workable:0, high_risk:1, drought_caution:2, caution:3, workable:4 };
    const sevOrder = { danger:0, warning:1, advisory:2, info:3, none:4 };

    const valueFor = (r) => {
      const obs = r.observations || {};
      const ind = r.indicators || {};
      const adv = CISData.getAdvisoryForMunicipality(r.psgc);
      switch (key) {
        case 'municipality': return r.municipality || '';
        case 'province': return r.province || '';
        case 'rainfall': return obs.rainfall_24h_mm ?? -Infinity;
        case 'forecast_rain': return _forecastRainOrder(r.forecast_10_day?.rainfall_class);
        case 'forecast_weather': return r.forecast_10_day?.weather_cover || '';
        case 'forecast_tmax': return r.forecast_10_day?.tmax_range_c?.[1] ?? -Infinity;
        case 'tmax': return obs.tmax_c ?? -Infinity;
        case 'humidity': return obs.humidity_pct ?? -Infinity;
        case 'cdd': return ind.cdd ?? -Infinity;
        case 'drought': return dOrder[ind.drought_class] ?? 9;
        case 'heat': return heatOrder[ind.heat_stress?.heat_class] ?? 9;
        case 'fieldwork': return workOrder[ind.field_workability?.overall_class] ?? 9;
        case 'risk': return ind.municipal_risk_score ?? -Infinity;
        case 'advisory': return sevOrder[adv?.highest_severity || 'none'] ?? 9;
        default: return '';
      }
    };

    return rows.sort((a, b) => {
      const av = valueFor(a);
      const bv = valueFor(b);
      let cmp = 0;
      if (typeof av === 'string' || typeof bv === 'string') {
        cmp = String(av).localeCompare(String(bv));
      } else {
        cmp = (av || 0) - (bv || 0);
      }
      return dir === 'asc' ? cmp : -cmp;
    });
  }

  function _renderSortIndicators() {
    document.querySelectorAll('#mun-table th.sortable').forEach(th => {
      const active = th.dataset.sortKey === _sortKey;
      th.classList.toggle('sorted', active);
      th.setAttribute('aria-sort', active ? (_sortDir === 'asc' ? 'ascending' : 'descending') : 'none');
      const indicator = th.querySelector('.sort-indicator');
      if (indicator) indicator.textContent = active ? (_sortDir === 'asc' ? '▲' : '▼') : '↕';
    });
  }

  function _renderTableRows(rows) {
    const tbody = document.getElementById('mun-tbody');
    if (!tbody) return;

    if (!rows.length) {
      tbody.innerHTML = '<tr><td colspan="14" class="loading-row">No municipalities match your search.</td></tr>';
      return;
    }

    const fmt = CISData.fmt;

    tbody.innerHTML = rows.map(r => {
      const obs = r.observations || {};
      const ind = r.indicators || {};
      const hs  = ind.heat_stress || {};
      const fw  = ind.field_workability || {};
      const forecast = r.forecast_10_day || {};
      const adv = CISData.getAdvisoryForMunicipality(r.psgc);
      const severity = adv?.highest_severity || 'none';

      return `
        <tr onclick="CISDashboard.openMunicipalProfile('${r.psgc}')" style="cursor:pointer">
          <td><strong>${r.municipality}</strong></td>
          <td>${r.province}</td>
          <td>${fmt.formatRainfall(obs.rainfall_24h_mm)}</td>
          <td>${_forecastRainPill(forecast.rainfall_class, forecast.available)}</td>
          <td>${_forecastText(forecast.weather_cover, forecast.date_range)}</td>
          <td>${_forecastTmax(forecast.tmax_range_c)}</td>
          <td>${fmt.formatTemp(obs.tmax_c)}</td>
          <td>${fmt.formatPercent(obs.humidity_pct)}</td>
          <td>${ind.cdd ?? '—'}</td>
          <td>${fmt.droughtPill(ind.drought_class)}</td>
          <td>${fmt.heatPill(hs.heat_class)}</td>
          <td>${fmt.workabilityPill(fw.overall_class)}</td>
          <td>${fmt.riskScoreBadge(ind.municipal_risk_score)}</td>
          <td>${fmt.severityPill(severity)}</td>
        </tr>
      `;
    }).join('');
  }

  function _forecastText(value, title) {
    if (!value) return '<span class="muted-cell">No ACAP forecast</span>';
    return `<span title="${_escapeAttr(title || '')}">${_escapeHtml(value)}</span>`;
  }

  function _forecastTmax(range) {
    if (!range || range.length < 2) return '<span class="muted-cell">—</span>';
    return `${parseFloat(range[0]).toFixed(1)}-${parseFloat(range[1]).toFixed(1)}°C`;
  }

  function _forecastRainPill(value, available) {
    if (!available || !value) return '<span class="pill pill-none">No Data</span>';
    const label = String(value).replace(/_/g, ' ');
    const cls = /heavy|storm|intense/i.test(label) ? 'pill-warning' :
                /light|isolated/i.test(label) ? 'pill-advisory' : 'pill-safe';
    return `<span class="pill ${cls}">${_escapeHtml(label)}</span>`;
  }

  function _forecastRainOrder(value) {
    const label = String(value || '').toLowerCase();
    if (label.includes('heavy') || label.includes('storm')) return 3;
    if (label.includes('moderate')) return 2;
    if (label.includes('light')) return 1;
    if (!label) return -1;
    return 0;
  }

  function _escapeHtml(str) {
    return String(str || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  }

  function _escapeAttr(str) {
    return _escapeHtml(str).replace(/"/g, '&quot;');
  }

  // ── Navigate to municipal profile when row is clicked ─────────────────────
  function openMunicipalProfile(psgc) {
    switchModule('municipal', null);
    CISMunicipal.selectByPSGC(psgc);
  }

  // ── Province filter handler ────────────────────────────────────────────────
  function handleProvinceFilter(province) {
    _currentProvince = province;
    renderStatCards(province);
    renderAlertStrip(province);
    renderTable(province);
  }

  // ── Render all dashboard components ───────────────────────────────────────
  function renderAll(province = 'all') {
    renderSourcePanel();
    renderStatCards(province);
    renderAlertStrip(province);
    renderTable(province);
  }

  return { renderAll, renderStatCards, renderAlertStrip, renderTable,
           renderSourcePanel, filterTable, sortTable, handleProvinceFilter, openMunicipalProfile };
})();
