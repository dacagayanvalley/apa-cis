/**
 * cis-main.js
 * Application bootstrap for APA-CIS frontend.
 * Handles: initial data load, module switching, top-bar updates,
 * province filter wiring, and global event handlers.
 *
 * DA RFO 02 — APA-CIS Climate Information Service, Cagayan Valley
 */

// ── Module registry ─────────────────────────────────────────────────────────
const MODULES = ['dashboard', 'map', 'advisory', 'municipal', 'planning', 'severe', 'pdf'];
let _mapInitialised = false;
let _activeModule = 'dashboard';

// ── Global module switcher ──────────────────────────────────────────────────
function switchModule(name, btnEl) {
  if (!MODULES.includes(name)) return;
  _activeModule = name;

  // Show/hide module panels
  MODULES.forEach(m => {
    const el = document.getElementById(`module-${m}`);
    if (el) el.classList.toggle('active', m === name);
  });

  // Update nav button states
  document.querySelectorAll('.mnav-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.module === name);
  });

  // Lazy-init map on first visit
  if (name === 'map' && !_mapInitialised) {
    setTimeout(() => {
      CISMap.init('leaflet-map');
      CISMap.switchLayer('rainfall_24h');
      _mapInitialised = true;
    }, 50);
  }

  // Re-render planning on each visit (data may have loaded since)
  if (name === 'planning') CISPlanning.renderAll();
  if (name === 'municipal') CISMunicipal.renderAll();
  if (name === 'advisory') CISAdvisory.renderAll();
  if (name === 'pdf' && window.CISAdvisoryPDF) CISAdvisoryPDF.renderAll();
  if (name === 'severe') CISSevereWeather.renderAll();
}

// ── Province filter (dashboard only) ───────────────────────────────────────
function filterProvince(province, btnEl) {
  document.querySelectorAll('.ptab').forEach(b => b.classList.remove('active'));
  if (btnEl) btnEl.classList.add('active');
  CISData.setProvince(province);
  CISDashboard.handleProvinceFilter(province);
}

// ── Table search/sort (global handlers wired from HTML) ─────────────────────
function filterTable(value) {
  CISDashboard.filterTable(value);
}
function sortTable(value) {
  CISDashboard.sortTable(value);
}
function switchLayer(layerName) {
  CISMap.switchLayer(layerName);
}
function filterMunicipalityList(value) {
  CISMunicipal.filterMunicipalityList(value);
}
function filterAdvisories() {
  CISAdvisory.filterAdvisories();
}
function generateRegionalBulletin() {
  CISAdvisory.generateRegionalBulletin();
}
function copySMS() {
  CISAdvisory.copySMS();
}
function copyFacebook() {
  CISAdvisory.copyFacebook();
}

// ── Top-bar: data freshness indicator ──────────────────────────────────────
function _updateFreshness(meta) {
  const dot   = document.getElementById('freshness-dot');
  const label = document.getElementById('freshness-label');
  if (!dot || !label) return;

  if (!meta) {
    dot.className   = 'freshness-dot error';
    label.textContent = 'No pipeline data found';
    return;
  }

  const isDemo = meta._demo;
  const asOf   = meta.as_of_date;
  const generatedAt = meta.generated_at ? _formatDateTime(meta.generated_at) : null;
  const lastRun = meta.pipeline_last_run || null;
  const fallbackAsOf = meta.pipeline_data_as_of || null;

  if (isDemo) {
    dot.className   = 'freshness-dot stale';
    label.textContent = 'Demo mode — run pipeline for live data';
    return;
  }

  if (asOf) {
    const days = Math.round(
      (Date.now() - new Date(asOf).getTime()) / 86400000
    );
    if (days <= 1) {
      dot.className   = 'freshness-dot';           // green pulse
      label.textContent = `Data: ${asOf}; fetched ${generatedAt || lastRun || 'today'}`;
    } else if (days <= 7) {
      dot.className   = 'freshness-dot stale';
      label.textContent = `Data: ${asOf} (${days} days ago); fetched ${generatedAt || lastRun || 'unknown'}`;
    } else {
      dot.className   = 'freshness-dot error';
      label.textContent = `Data: ${asOf} (${days} days old — pipeline may have failed)`;
    }
    if (fallbackAsOf && fallbackAsOf !== asOf) {
      label.title = `Pipeline fallback data as of ${fallbackAsOf}. Generated ${generatedAt || 'unknown'}.`;
    }
  }
}

function _formatDateTime(value) {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString('en-PH', {
    timeZone: 'Asia/Manila',
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

// ── Top-bar: ENSO badge ─────────────────────────────────────────────────────
function _isSevereWeatherActiveForRegion() {
  const typhoon = CISData.getPAGASAData()?.typhoon || {};
  const isFinal = typhoon.is_final || String(typhoon.bulletin_status || '').toLowerCase() === 'final';
  return Boolean(!isFinal && typhoon.active && typhoon.region2_affected);
}

function _updateSevereWeatherNavState() {
  const btn = document.querySelector('.mnav-btn[data-module="severe"]');
  if (!btn) return;
  const typhoon = CISData.getPAGASAData()?.typhoon || {};
  const activeForRegion = _isSevereWeatherActiveForRegion();
  btn.classList.toggle('severe-alert', activeForRegion);
  btn.title = activeForRegion
    ? `${typhoon.disturbance_type || 'Weather disturbance'} ${typhoon.name || ''} affects Region 2. Open urgent severe-weather advisory.`
    : 'Open PAGASA severe-weather monitoring module.';
}
function _updateENSOBadge() {
  // Best-effort: ENSO status from PAGASA or fallback
  const badge = document.getElementById('enso-badge');
  if (!badge) return;
  const pagasa = CISData.getPAGASAData();
  const enso = pagasa?.enso?.phase || pagasa?.enso?.enso_phase || 'unknown';
  badge.classList.remove('el-nino', 'la-nina');
  if (enso === 'el_nino') badge.classList.add('el-nino');
  if (enso === 'la_nina') badge.classList.add('la-nina');
  badge.textContent = `ENSO: ${enso.replace('_', ' ').toUpperCase()}`;
}

// ── Application bootstrap ───────────────────────────────────────────────────
async function initCIS() {
  console.log('[APA-CIS] Initialising Climate Information Service...');

  try {
    // Load all data
    const { indicators, advisories, status, pagasaData } = await CISData.loadAll();

    // Update freshness in topbar
    _updateFreshness(CISData.getPipelineStatus());
    _updateENSOBadge();

    // Render the default module. Severe Weather takes priority only when
    // PAGASA has an active bulletin affecting Cagayan Valley.
    CISDashboard.renderAll('all');
    if (_activeModule === 'pdf' && window.CISAdvisoryPDF) CISAdvisoryPDF.renderAll();
    _updateSevereWeatherNavState();
    if (_isSevereWeatherActiveForRegion()) {
      switchModule('severe', document.querySelector('.mnav-btn[data-module="severe"]'));
    } else {
      switchModule('dashboard', document.querySelector('.mnav-btn[data-module="dashboard"]'));
    }

    console.log(
      `[APA-CIS] Data loaded: ${indicators?.meta?.municipality_count || 0} municipalities, ` +
      `${advisories?.meta?.municipalities_with_advisories || 0} with advisories`
    );

    // Show demo banner if no real data
    if (indicators?.meta?._demo) {
      const strip = document.getElementById('alert-strip');
      if (strip) {
        strip.innerHTML = `
          ⚙️ <strong>Demo Mode</strong> — The pipeline has not run yet.
          Synthetic placeholder data is shown for UI testing.
          Run <code>python scripts/run_pipeline.py</code> to load real climate data.
        `;
        strip.classList.remove('hidden');
        strip.style.borderLeftColor = '#1565C0';
        strip.style.background = '#E3F2FD';
        strip.style.color = '#0D47A1';
      }
    }

  } catch (err) {
    console.error('[APA-CIS] Init failed:', err);
    const tbody = document.getElementById('mun-tbody');
    if (tbody) {
      tbody.innerHTML = `
        <tr><td colspan="11" class="loading-row">
          ⚠️ Could not load climate data. Make sure the pipeline has run and data files exist in data/.
          Check the browser console for details.
        </td></tr>
      `;
    }
  }
}

// ── DOM ready ────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', initCIS);
