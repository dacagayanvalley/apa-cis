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
  let _sortKey = 'risk_desc';
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
      const chirpsCount = rows.filter(r => r.observations?.rainfall_source === 'chirps').length;
      const nasaCount = rows.filter(r => r.observations?.rainfall_source !== 'chirps').length;
      rainfallEl.textContent = chirpsCount
        ? `CHIRPS used in ${chirpsCount} municipalities; NASA fallback in ${nasaCount}`
        : 'NASA POWER rainfall active; CHIRPS fallback not yet sampled';
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
    _sortKey = key;
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
    rows = _sortRows(rows, _sortKey);

    _renderTableRows(rows);
  }

  function _sortRows(rows, key) {
    switch (key) {
      case 'risk_desc':
        return rows.sort((a, b) =>
          (b.indicators?.municipal_risk_score || 0) - (a.indicators?.municipal_risk_score || 0));
      case 'drought_desc':
        const dOrder = { critical:0, warning:1, watch:2, none:3 };
        return rows.sort((a, b) =>
          (dOrder[a.indicators?.drought_class] ?? 4) - (dOrder[b.indicators?.drought_class] ?? 4));
      case 'rain_desc':
        return rows.sort((a, b) =>
          (b.observations?.rainfall_24h_mm || 0) - (a.observations?.rainfall_24h_mm || 0));
      case 'alpha':
        return rows.sort((a, b) => a.municipality.localeCompare(b.municipality));
      default:
        return rows;
    }
  }

  function _renderTableRows(rows) {
    const tbody = document.getElementById('mun-tbody');
    if (!tbody) return;

    if (!rows.length) {
      tbody.innerHTML = '<tr><td colspan="11" class="loading-row">No municipalities match your search.</td></tr>';
      return;
    }

    const fmt = CISData.fmt;

    tbody.innerHTML = rows.map(r => {
      const obs = r.observations || {};
      const ind = r.indicators || {};
      const hs  = ind.heat_stress || {};
      const fw  = ind.field_workability || {};
      const adv = CISData.getAdvisoryForMunicipality(r.psgc);
      const severity = adv?.highest_severity || 'none';

      return `
        <tr onclick="CISDashboard.openMunicipalProfile('${r.psgc}')" style="cursor:pointer">
          <td><strong>${r.municipality}</strong></td>
          <td>${r.province}</td>
          <td>${fmt.formatRainfall(obs.rainfall_24h_mm)}</td>
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
