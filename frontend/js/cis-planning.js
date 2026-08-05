/**
 * cis-planning.js
 * Planning Dashboard + Municipal Profile modules for APA-CIS.
 *
 * Planning Dashboard:
 *   - Priority intervention cards
 *   - Top-20 priority municipality list
 *   - Intervention type matrix
 *
 * Municipal Profile:
 *   - Scrollable municipality selector
 *   - Full climate profile, crop calendar, risk history, adaptation options
 *
 * DA RFO 02 &mdash; APA-CIS Climate Information Service
 */

const CISPlanning = (() => {

  // ── Planning Dashboard ────────────────────────────────────────────────────

  function renderPlanningCards() {
    const rows = CISData.getMunicipalRows('all');

    const dangerCount = rows.filter(r => {
      const adv = CISData.getAdvisoryForMunicipality(r.psgc);
      return adv?.highest_severity === 'danger';
    }).length;

    const warningCount = rows.filter(r => {
      const adv = CISData.getAdvisoryForMunicipality(r.psgc);
      return adv?.highest_severity === 'warning';
    }).length;

    const droughtCount = rows.filter(r =>
      ['watch','warning','critical'].includes(r.indicators?.drought_class)
    ).length;

    const heatCount = rows.filter(r =>
      ['high','danger'].includes(r.indicators?.heat_stress?.heat_class)
    ).length;

    _setEl('pc-danger', dangerCount);
    _setEl('pc-warning', warningCount);
    _setEl('pc-drought', droughtCount);
    _setEl('pc-heat', heatCount);
  }

  function renderPriorityList() {
    const container = document.getElementById('priority-list');
    if (!container) return;

    const priority = CISData.getPriorityMunicipalities(20);
    if (!priority.length) {
      container.innerHTML = '<div class="loading-msg">No priority data available &mdash; run the pipeline first.</div>';
      return;
    }

    container.innerHTML = priority.map((item, i) => `
      <div class="priority-item ${item.severity}"
           onclick="CISMunicipal.selectByPSGC('${item.psgc}'); switchModule('municipal', null);"
           style="cursor:pointer">
        <div class="pi-rank">${i + 1}</div>
        <div class="pi-mun">
          <div class="pi-mun-name">${item.municipality}</div>
          <div class="pi-prov">${item.province}</div>
          <div class="pi-advisory">${item.primary_advisory || ''}</div>
        </div>
        <div style="text-align:right">
          <span class="pill pill-${item.severity === 'danger' ? 'danger' : item.severity === 'warning' ? 'warning' : item.severity === 'advisory' ? 'advisory' : 'safe'}"
                style="margin-bottom:4px;display:block">
            ${item.severity.toUpperCase()}
          </span>
          <div style="font-size:10px;color:#90A4AE">${item.advisory_count} advisory</div>
        </div>
        <div class="pi-score">
          <div class="pi-score-num">${item.risk_score}</div>
          <div class="pi-score-label">Risk Score</div>
        </div>
      </div>
    `).join('');
  }

  function renderInterventionMatrix() {
    const container = document.getElementById('intervention-matrix');
    if (!container) return;

    const rows = CISData.getMunicipalRows('all');
    const droughtCritical = rows.filter(r => r.indicators?.drought_class === 'critical').length;
    const droughtWatch    = rows.filter(r => ['watch','warning','critical'].includes(r.indicators?.drought_class)).length;
    const heatHigh        = rows.filter(r => ['high','danger'].includes(r.indicators?.heat_stress?.heat_class)).length;
    const notWorkable     = rows.filter(r => r.indicators?.field_workability?.overall_class === 'not_workable').length;

    const interventions = [
      {
        icon: '&#128167;', title: 'Emergency Irrigation',
        trigger: 'CDD &ge; 21 days (rainfed)',
        count: droughtCritical, countLabel: 'municipalities need immediate water',
        actions: ['Coordinate with NIA for emergency allocation', 'Activate SPIS pump irrigation', 'Deploy mobile water pumps']
      },
      {
        icon: '&#127793;', title: 'Drought-Tolerant Seeds',
        trigger: 'Dry spell watch/warning',
        count: droughtWatch, countLabel: 'municipalities under dry spell',
        actions: ['Pre-position DTR seed buffer', 'Issue free seeds to affected farmers', 'Coordinate with PhilRice/BPI']
      },
      {
        icon: '&#128203;', title: 'Crop Insurance (PCIC)',
        trigger: 'Danger/Warning advisories',
        count: rows.filter(r => {
          const a = CISData.getAdvisoryForMunicipality(r.psgc);
          return ['danger','warning'].includes(a?.highest_severity);
        }).length,
        countLabel: 'municipalities for insurance follow-up',
        actions: ['Facilitate PCIC crop insurance enrollment', 'Coordinate loss assessment', 'Fast-track claims processing']
      },
      {
        icon: '&#127973;', title: 'Heat & Labour Protection',
        trigger: 'WBGT high/danger',
        count: heatHigh, countLabel: 'municipalities with high heat risk',
        actions: ['Issue heat advisory to AEWs/MAOs', 'Coordinate with DOH-CHD 02', 'Restrict field work 9AM&ndash;4PM']
      },
    ];

    container.innerHTML = interventions.map(intv => `
      <div class="int-card">
        <div class="int-card-icon">${intv.icon}</div>
        <div class="int-card-title">${intv.title}</div>
        <div class="int-card-trigger"><strong>Trigger:</strong> ${intv.trigger}</div>
        <div class="int-card-count">${intv.count}</div>
        <div class="int-card-count-label">${intv.countLabel}</div>
        <ul style="margin:8px 0 0;padding-left:16px;font-size:11px;color:#546E7A;line-height:1.7">
          ${intv.actions.map(a => `<li>${a}</li>`).join('')}
        </ul>
      </div>
    `).join('');
  }

  function renderAll() {
    renderPlanningCards();
    renderPriorityList();
    renderInterventionMatrix();
  }

  return { renderAll, renderPlanningCards, renderPriorityList, renderInterventionMatrix };

  function _setEl(id, val) {
    const el = document.getElementById(id);
    if (el) el.textContent = val;
  }
})();

// Expose _setEl helper used inside both modules
function _setEl(id, val) {
  const el = document.getElementById(id);
  if (el) el.textContent = val;
}


// ════════════════════════════════════════════════════════════════════════════
// MUNICIPAL PROFILE MODULE  (separate from planning, same file for brevity)
// ════════════════════════════════════════════════════════════════════════════

const CISMunicipal = (() => {

  let _selectedPSGC = null;

  // ── Render the scrollable municipality selector list ───────────────────────
  function renderMunicipalityList(filter = '') {
    const container = document.getElementById('mp-list');
    if (!container) return;

    const rows = CISData.getMunicipalRows('all');
    const filterLower = filter.toLowerCase();

    const filtered = filter
      ? rows.filter(r =>
          r.municipality.toLowerCase().includes(filterLower) ||
          r.province.toLowerCase().includes(filterLower))
      : rows;

    const sorted = filtered.sort((a, b) =>
      a.province.localeCompare(b.province) || a.municipality.localeCompare(b.municipality)
    );

    container.innerHTML = sorted.map(r => `
      <div class="mp-item${_selectedPSGC === r.psgc ? ' selected' : ''}"
           onclick="CISMunicipal.selectByPSGC('${r.psgc}')">
        <div class="mp-item-name">${r.municipality}</div>
        <div class="mp-item-prov">${r.province}</div>
      </div>
    `).join('');
  }

  // ── Select and render full profile for a municipality ─────────────────────
  function selectByPSGC(psgc) {
    _selectedPSGC = psgc;
    const ind = CISData.getIndicatorByPSGC(psgc);
    const adv = CISData.getAdvisoryForMunicipality(psgc);

    // Highlight in list
    document.querySelectorAll('.mp-item').forEach(el => el.classList.remove('selected'));
    const item = Array.from(document.querySelectorAll('.mp-item'))
      .find(el => el.getAttribute('onclick')?.includes(psgc));
    if (item) {
      item.classList.add('selected');
      item.scrollIntoView({ block: 'nearest' });
    }

    renderProfile(ind, adv);
  }

  // ── Render the full profile card grid ────────────────────────────────────
  function renderProfile(ind, adv) {
    const content = document.getElementById('mprofile-content');
    if (!content) return;

    if (!ind) {
      content.innerHTML = `<div class="adv-empty-state"><p>No data for this municipality.</p></div>`;
      return;
    }

    const obs = ind.observations || {};
    const indicators = ind.indicators || {};
    const hs = indicators.heat_stress || {};
    const fw = indicators.field_workability || {};
    const cr = indicators.crop_stage_risk || {};
    const id = indicators.irrigation_demand || {};
    const anom = indicators.rainfall_anomaly || {};
    const fmt = CISData.fmt;

    const activeAdvisories = _renderConsolidatedAdvisories(adv, fmt);
    const rainfall7d = obs.rainfall_7d_mm ?? indicators.rainfall_7d_mm;

    content.innerHTML = `
      <div style="margin-bottom:16px">
        <h2 style="font-size:20px;font-weight:800;color:#1B5E20;margin-bottom:2px">${ind.municipality}</h2>
        <div style="font-size:12px;color:#546E7A">${ind.province} &middot; As of ${ind.as_of_date || '&mdash;'} &middot; Source: ${_sourceSummary(obs)}</div>
      </div>

      ${activeAdvisories}

      <div class="mprofile-grid">

        <!-- Current Observations -->
        <div class="mprofile-card">
          <div class="mc-header">📡 Current Observations</div>
          <div class="mc-body">
            <div class="mc-row"><span class="mc-key">Rainfall (24h)</span><span class="mc-val">${fmt.formatRainfall(obs.rainfall_24h_mm)}</span></div>
            <div class="mc-row"><span class="mc-key">Rainfall (7-day)</span><span class="mc-val">${fmt.formatRainfall(rainfall7d)}</span></div>
            <div class="mc-row"><span class="mc-key">T-max</span><span class="mc-val">${fmt.formatTemp(obs.tmax_c)}</span></div>
            <div class="mc-row"><span class="mc-key">T-min</span><span class="mc-val">${fmt.formatTemp(obs.tmin_c)}</span></div>
            <div class="mc-row"><span class="mc-key">T-mean</span><span class="mc-val">${fmt.formatTemp(obs.tmean_c)}</span></div>
            <div class="mc-row"><span class="mc-key">Humidity</span><span class="mc-val">${fmt.formatPercent(obs.humidity_pct)}</span></div>
            <div class="mc-row"><span class="mc-key">Wind Speed</span><span class="mc-val">${obs.wind_speed_ms ?? '&mdash;'} m/s</span></div>
          </div>
        </div>

        <!-- Climate Indicators -->
        <div class="mprofile-card">
          <div class="mc-header">🌡 Climate Indicators</div>
          <div class="mc-body">
            <div class="mc-row"><span class="mc-key">Consecutive Dry Days</span><span class="mc-val">${indicators.cdd ?? '&mdash;'}</span></div>
            <div class="mc-row"><span class="mc-key">Drought Status</span><span class="mc-val">${fmt.droughtPill(indicators.drought_class)}</span></div>
            <div class="mc-row"><span class="mc-key">Rainfall Anomaly</span><span class="mc-val">${anom.pct_of_normal ? anom.pct_of_normal + '% of normal' : '&mdash;'}</span></div>
            <div class="mc-row"><span class="mc-key">Anomaly Class</span><span class="mc-val">${(anom.anomaly_class || '&mdash;').replace('_',' ')}</span></div>
            <div class="mc-row"><span class="mc-key">ETo (mm/day)</span><span class="mc-val">${indicators.eto_mm ?? '&mdash;'}</span></div>
            <div class="mc-row"><span class="mc-key">Irrig. Demand</span><span class="mc-val">${id.demand_mm ?? '&mdash;'} mm/day</span></div>
            <div class="mc-row"><span class="mc-key">Risk Score</span><span class="mc-val">${fmt.riskScoreBadge(indicators.municipal_risk_score)}</span></div>
          </div>
        </div>

        <!-- Risk Assessment -->
        <div class="mprofile-card">
          <div class="mc-header">⚠️ Risk Assessment</div>
          <div class="mc-body">
            <div class="mc-row"><span class="mc-key">Heat Stress</span><span class="mc-val">${fmt.heatPill(hs.heat_class)}</span></div>
            <div class="mc-row"><span class="mc-key">WBGT (approx)</span><span class="mc-val">${hs.wbgt_approx ?? '&mdash;'}°C</span></div>
            <div class="mc-row"><span class="mc-key">Field Work Status</span><span class="mc-val">${fmt.workabilityPill(fw.overall_class)}</span></div>
            <div class="mc-row"><span class="mc-key">Crop Stage Risk</span><span class="mc-val">${cr.risk_score ?? '&mdash;'}/5 (${cr.risk_class || '&mdash;'})</span></div>
            <div class="mc-row"><span class="mc-key">Drought Risk</span><span class="mc-val">${cr.components?.drought ?? '&mdash;'}</span></div>
            <div class="mc-row"><span class="mc-key">Flood Risk</span><span class="mc-val">${cr.components?.flood ?? '&mdash;'}</span></div>
            <div class="mc-row"><span class="mc-key">Disease Risk</span><span class="mc-val">${cr.components?.disease ?? '&mdash;'}</span></div>
          </div>
        </div>

        <!-- Crop Calendar & Operations -->
        <div class="mprofile-card">
          <div class="mc-header">🌾 Field Operations Today</div>
          <div class="mc-body">
            ${_renderOpsCompact(fw.operations)}
          </div>
        </div>

      </div>

      ${_renderObservationExplainer(ind, obs, indicators, fw)}

      ${_renderCropCalendarComparison(ind)}

      <!-- Recommended Adaptations -->
      <div class="mprofile-card" style="margin-top:14px">
        <div class="mc-header">💡 Recommended Adaptation Measures</div>
        <div class="mc-body">${_renderAdaptations(indicators, ind)}</div>
      </div>
    `;
  }

  function _renderObservationExplainer(ind, obs, indicators, fw) {
    const rainfall7d = obs.rainfall_7d_mm ?? indicators.rainfall_7d_mm;
    const items = [
      _explainRain24(obs.rainfall_24h_mm),
      _explainRain7(rainfall7d),
      _explainTmax(obs.tmax_c),
      _explainTmin(obs.tmin_c),
      _explainTmean(obs.tmean_c),
      _explainHumidity(obs.humidity_pct),
      _explainWind(obs.wind_speed_ms),
    ];
    const priority = _buildFarmerScenario(ind, obs, indicators, fw, rainfall7d);

    return `
      <div class="mprofile-card observation-explainer-card">
        <div class="mc-header">Farmer-Friendly Reading of Today's Numbers</div>
        <div class="mc-body">
          <div class="farmer-scenario">
            <span>Plain scenario for ${_escapeInline(ind.municipality)} farmers</span>
            <strong>${_escapeInline(priority)}</strong>
          </div>
          <div class="obs-explainer-grid">
            ${items.map(item => `
              <div class="obs-explainer-item ${item.level}">
                <div class="obs-explainer-top">
                  <span>${_escapeInline(item.label)}</span>
                  <strong>${_escapeInline(item.value)}</strong>
                </div>
                <p>${_escapeInline(item.meaning)}</p>
                <small>${_escapeInline(item.operation)}</small>
              </div>
            `).join('')}
          </div>
        </div>
      </div>
    `;
  }

  function _buildFarmerScenario(ind, obs, indicators, fw, rainfall7d) {
    const rain24 = _num(obs.rainfall_24h_mm);
    const rain7 = _num(rainfall7d);
    const tmax = _num(obs.tmax_c);
    const humidity = _num(obs.humidity_pct);
    const wind = _num(obs.wind_speed_ms);
    const drought = indicators.drought_class;
    const work = fw?.overall_class;

    if (rain24 >= 50 || work === 'not_workable') {
      return 'Fields are likely too wet for heavy field work. Prioritize drainage checks, postpone land preparation and spraying, and protect harvested grains from moisture.';
    }
    if (['warning', 'critical'].includes(drought) || (rain7 !== null && rain7 < 10 && rain24 !== null && rain24 < 5)) {
      return 'The farm has been short of rain. Check soil moisture, schedule supplemental irrigation where available, and avoid fertilizer application unless water is assured.';
    }
    if (tmax >= 36) {
      return 'Heat is the main concern today. Move labor-intensive work to early morning or late afternoon, provide water and rest, and monitor livestock shade.';
    }
    if (humidity >= 85 && rain24 >= 10) {
      return 'Warm, wet, and humid conditions can favor fungal diseases and slow grain drying. Scout rice and corn fields, improve airflow, and avoid storing damp produce.';
    }
    if (wind >= 4) {
      return 'Wind may affect spraying quality. Spray only during calmer periods and use proper nozzle settings to reduce drift.';
    }
    return 'Conditions look generally manageable. Continue routine field monitoring, keep drainage and irrigation ready, and follow the operation status shown above.';
  }

  function _explainRain24(value) {
    const mm = _num(value);
    if (mm === null) return _obsItem('Rainfall (24h)', 'No data', 'No recent rainfall reading is available.', 'Use field observation before deciding on irrigation or field entry.', 'neutral');
    if (mm >= 50) return _obsItem('Rainfall (24h)', `${mm.toFixed(1)} mm`, 'Very heavy rain in the last day; low areas may be waterlogged.', 'Delay plowing, transplanting, fertilizer, and spraying; check drainage first.', 'alert');
    if (mm >= 25) return _obsItem('Rainfall (24h)', `${mm.toFixed(1)} mm`, 'Heavy rain; soil is likely wet and machinery may compact the field.', 'Postpone heavy equipment and wait for field firmness.', 'caution');
    if (mm >= 10) return _obsItem('Rainfall (24h)', `${mm.toFixed(1)} mm`, 'Useful rain; crops likely received moisture today.', 'Irrigation can usually be reduced, but avoid spraying while leaves are wet.', 'good');
    if (mm >= 1) return _obsItem('Rainfall (24h)', `${mm.toFixed(1)} mm`, 'Light rain; it may wet leaves but may not refill soil moisture deeply.', 'Check soil before skipping irrigation.', 'neutral');
    return _obsItem('Rainfall (24h)', `${mm.toFixed(1)} mm`, 'Almost no rain today.', 'For sensitive crops, check soil moisture and irrigation need.', 'caution');
  }

  function _explainRain7(value) {
    const mm = _num(value);
    if (mm === null) return _obsItem('Rainfall (7-day)', 'No data', 'No weekly rainfall reading is available.', 'Use the 24-hour rain and field moisture checks.', 'neutral');
    if (mm >= 100) return _obsItem('Rainfall (7-day)', `${mm.toFixed(1)} mm`, 'The past week has been very wet; water may have accumulated in paddies and low fields.', 'Watch for waterlogging, drainage problems, and disease pressure.', 'alert');
    if (mm >= 40) return _obsItem('Rainfall (7-day)', `${mm.toFixed(1)} mm`, 'The week supplied good moisture for many crops.', 'Reduce unnecessary irrigation and time fertilizer after water stabilizes.', 'good');
    if (mm >= 10) return _obsItem('Rainfall (7-day)', `${mm.toFixed(1)} mm`, 'Rain has been limited but not completely absent.', 'Monitor shallow-rooted crops and newly planted areas.', 'neutral');
    return _obsItem('Rainfall (7-day)', `${mm.toFixed(1)} mm`, 'The week has been dry.', 'Prioritize irrigation, mulching, and drought monitoring.', 'caution');
  }

  function _explainTmax(value) {
    const c = _num(value);
    if (c === null) return _obsItem('T-max', 'No data', 'No daytime heat reading is available.', 'Use local heat observation for worker scheduling.', 'neutral');
    if (c >= 36) return _obsItem('T-max', `${c.toFixed(1)} C`, 'Very hot daytime conditions.', 'Avoid strenuous work from late morning to mid-afternoon; protect workers and livestock.', 'alert');
    if (c >= 33) return _obsItem('T-max', `${c.toFixed(1)} C`, 'Hot conditions can stress crops and workers.', 'Schedule heavy tasks early and keep irrigation checks active.', 'caution');
    return _obsItem('T-max', `${c.toFixed(1)} C`, 'Daytime heat is within a more manageable range.', 'Normal field work may proceed if rain, wind, and soil conditions allow.', 'good');
  }

  function _explainTmin(value) {
    const c = _num(value);
    if (c === null) return _obsItem('T-min', 'No data', 'No night temperature reading is available.', 'Use local field signs for pest and disease monitoring.', 'neutral');
    if (c >= 26) return _obsItem('T-min', `${c.toFixed(1)} C`, 'Warm nights give crops and animals less time to cool down.', 'Monitor heat stress, flowering crops, and livestock comfort.', 'caution');
    if (c <= 20) return _obsItem('T-min', `${c.toFixed(1)} C`, 'Cooler nights may slow some crop growth but reduce heat stress.', 'Watch seedlings in upland or cooler areas.', 'neutral');
    return _obsItem('T-min', `${c.toFixed(1)} C`, 'Night temperature is generally comfortable for many crops.', 'No special night-temperature action is needed.', 'good');
  }

  function _explainTmean(value) {
    const c = _num(value);
    if (c === null) return _obsItem('T-mean', 'No data', 'No average temperature reading is available.', 'Use T-max and T-min to judge heat stress.', 'neutral');
    if (c >= 30) return _obsItem('T-mean', `${c.toFixed(1)} C`, 'The whole day is running hot, not just the afternoon.', 'Expect higher water use by crops and faster soil drying.', 'caution');
    if (c >= 24) return _obsItem('T-mean', `${c.toFixed(1)} C`, 'Average temperature is within a common tropical crop range.', 'Keep normal crop monitoring routines.', 'good');
    return _obsItem('T-mean', `${c.toFixed(1)} C`, 'Average temperature is relatively cool.', 'Growth may be slower in cool upland spots.', 'neutral');
  }

  function _explainHumidity(value) {
    const pct = _num(value);
    if (pct === null) return _obsItem('Humidity', 'No data', 'No humidity reading is available.', 'Use leaf wetness and drying condition in the field.', 'neutral');
    if (pct >= 85) return _obsItem('Humidity', `${pct.toFixed(0)}%`, 'Air is very moist; leaves and grains dry slowly.', 'Scout for fungal diseases and allow more drying time for harvest.', 'caution');
    if (pct < 50) return _obsItem('Humidity', `${pct.toFixed(0)}%`, 'Air is dry; soil and leaves lose water faster.', 'Check irrigation need and avoid spraying during hot dry hours.', 'caution');
    return _obsItem('Humidity', `${pct.toFixed(0)}%`, 'Humidity is moderate for field work.', 'Normal operations may proceed if rain and wind are favorable.', 'good');
  }

  function _explainWind(value) {
    const ms = _num(value);
    if (ms === null) return _obsItem('Wind speed', 'No data', 'No wind reading is available.', 'Check actual field wind before spraying.', 'neutral');
    if (ms >= 8) return _obsItem('Wind speed', `${ms.toFixed(1)} m/s`, 'Strong wind can damage spray coverage and move chemicals off-target.', 'Avoid spraying; secure light materials and monitor exposed crops.', 'alert');
    if (ms >= 4) return _obsItem('Wind speed', `${ms.toFixed(1)} m/s`, 'Breezy conditions can cause spray drift.', 'Spray only in calmer hours and use drift-reducing practices.', 'caution');
    if (ms < 1) return _obsItem('Wind speed', `${ms.toFixed(1)} m/s`, 'Very calm air may slow drying and ventilation.', 'Good for drift control, but watch drying and disease risk if humidity is high.', 'neutral');
    return _obsItem('Wind speed', `${ms.toFixed(1)} m/s`, 'Wind is light enough for most operations.', 'Spraying and field work are more manageable if rain is not present.', 'good');
  }

  function _obsItem(label, value, meaning, operation, level) {
    return { label, value, meaning, operation, level };
  }

  function _num(value) {
    if (value === null || value === undefined || value === '') return null;
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  function _renderConsolidatedAdvisories(adv, fmt) {
    if (!adv || !adv.advisories || !adv.advisories.length) {
      return `
        <div class="mprofile-card" style="margin-bottom:16px">
          <div class="mc-header">Consolidated Advisory</div>
          <div class="mc-body">
            <div style="font-size:12px;color:#546E7A">No active municipal advisory is triggered by the current climate thresholds.</div>
          </div>
        </div>
      `;
    }

    const primary = adv.advisories[0];
    const decision = adv.decision_support || {};
    const cropStage = decision.affected_crop_stage || {};
    const calendarAnchor = cropStage.calendar_anchor || {};
    const sourceAge = decision.source_age || {};
    const qaFlags = decision.source_qa_flags || [];

    return `
      <div class="mprofile-card" style="margin-bottom:16px">
        <div class="mc-header">Decision Advisory</div>
        <div class="mc-body">
          <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px">
            ${fmt.severityPill(decision.severity || primary.severity)}
            <strong>${_escapeInline(decision.hazard || primary.rule_name)}</strong>
          </div>
          <div class="decision-grid">
            ${_decisionItem('Hazard', decision.hazard || primary.rule_name)}
            ${_decisionItem('Confidence / Source Age', `${_titleCase(decision.confidence || 'unknown')} confidence; rainfall ${sourceAge.rainfall_age_days ?? 'N/A'} day(s) old from ${sourceAge.rainfall_source || 'unknown'}`)}
            ${_decisionItem('Affected Crop Stage', `${_labelize(cropStage.crop || 'all')} / ${_labelize(cropStage.stage || 'all')} (${cropStage.risk_class || 'risk not classified'})`)}
            ${_decisionItem('Calendar Anchor', _calendarAnchorSummary(calendarAnchor, cropStage))}
            ${_decisionItem('ACAP Crop Calendar', cropStage.crop_calendar_decision_point || 'No ACAP crop-calendar decision point loaded.')}
            ${_decisionItem('Immediate Farmer Action', decision.immediate_farmer_action || primary.texts?.sms || '')}
            ${_decisionItem('LGU / DA Action', decision.lgu_da_action || primary.texts?.lgu || '')}
            ${_decisionItem('When to Re-check', `${decision.when_to_recheck || 'Re-check after the next pipeline run.'} Valid until ${decision.valid_until || 'next update'}.`)}
          </div>
          <div class="decision-sms">
            <strong>SMS-ready:</strong> ${_escapeInline(decision.sms_ready || primary.texts?.sms || '')}
          </div>
          <div class="decision-qa">
            <strong>Source QA:</strong>
            ${qaFlags.map(flag => `<span>${_escapeInline(flag)}</span>`).join('')}
          </div>
        </div>
      </div>
    `;
  }

  function _decisionItem(label, value) {
    return `
      <div class="decision-item">
        <span>${label}</span>
        <strong>${_escapeInline(value || 'N/A')}</strong>
      </div>
    `;
  }

  function _titleCase(value) {
    return String(value || '').replace(/\b\w/g, char => char.toUpperCase());
  }

  function _labelize(value) {
    return String(value || '').replace(/_/g, ' ');
  }

  function _sourceSummary(obs) {
    const source = obs.rainfall_source || 'nasa_power';
    if (source === 'apa_cis') return `Adapting Philippine Agriculture to Climate Change Climate Information Service (APA-CIS) (${obs.apa_cis_record_date || 'current'})`;
    if (source === 'chirps') return `Climate Hazards Group InfraRed Precipitation with Station data (CHIRPS) (${obs.chirps_record_date || 'latest'})`;
    return 'National Aeronautics and Space Administration POWER (NASA POWER) fallback';
  }

  function _calendarAnchorSummary(anchor, cropStage) {
    const stages = anchor?.matched_current_stages || cropStage.current_rice_corn_stages || [];
    if (!stages.length) return anchor?.note || cropStage.crop_calendar_decision_point || 'No active ACAP rice/corn stage matched this advisory.';
    const period = anchor?.period || cropStage.calendar_period || 'current period';
    const labels = stages.map(stage =>
      `${stage.crop_label || _titleCase(stage.crop)} S${stage.season || '-'}: ${stage.calendar_stage_label || _labelize(stage.calendar_stage)}`
    );
    return `${period} - ${labels.join('; ')}`;
  }

  function _escapeInline(str) {
    return (str || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  }

  function _renderOpsCompact(ops) {
    if (!ops) return '<p style="color:#9E9E9E;font-size:11px">No operations data</p>';
    const labels = {
      land_preparation:'🚜 Land Prep', transplanting:'🌱 Transplanting',
      fertilizer_application:'💊 Fertilizer', spraying:'🧴 Spraying',
      irrigation:'💧 Irrigation', harvesting:'🌾 Harvesting',
      drying:'☀️ Drying', pest_monitoring:'🔍 Pest Monitoring',
    };
    return Object.entries(ops).map(([key, status]) => `
      <div class="mc-row">
        <span class="mc-key">${labels[key] || key}</span>
        <span class="${status === 'safe' ? 'ops-safe' : 'ops-defer'}">${status === 'safe' ? '✅ Safe' : '⛔ Defer'}</span>
      </div>
    `).join('');
  }

  function _renderCropCalendarComparison(ind) {
    const calendars = _getACAPCalendars(ind);
    return `
      <div class="crop-calendar-compare" style="margin-top:14px">
        <div class="mprofile-card">
          <div class="mc-header">Cagayan Valley Crop Calendar Reference</div>
          <div class="mc-body">
            ${_renderACAPCalendarSet(calendars.reference)}
            <div class="calendar-note">${_escapeInline(calendars.referenceNote)}</div>
          </div>
        </div>
        <div class="mprofile-card">
          <div class="mc-header">Municipal Cropping Calendar - ${_escapeInline(ind.municipality)}</div>
          <div class="mc-body">
            ${calendars.municipal ? _renderACAPCalendarSet(calendars.municipal) : _renderNoACAPCalendar()}
            <div class="calendar-note">${_escapeInline(calendars.municipalNote)}</div>
          </div>
        </div>
      </div>
    `;
  }

  function _getACAPCalendars(ind) {
    const data = CISData.getACAPCropCalendars?.();
    if (!data) {
      return {
        reference: null,
        municipal: null,
        referenceNote: 'ACAP crop-calendar reference data is not loaded.',
        municipalNote: 'ACAP municipal crop-calendar data is not loaded.'
      };
    }

    const provinceKey = _municipalityKey(ind.province);
    const municipalKey = `${provinceKey}|${_municipalityKey(ind.municipality)}`;
    const reference = data.province_reference?.[provinceKey] || null;
    const municipal = data.municipalities?.[municipalKey] || null;
    const sourceCount = Object.keys(data.municipalities || {}).length;

    return {
      reference,
      municipal,
      referenceNote: reference
        ? `ACAP provincial reference for ${reference.province}; rice and corn seasons are shown by half-month period.`
        : `No ACAP provincial reference calendar loaded for ${ind.province}.`,
      municipalNote: municipal
        ? `ACAP municipal crop calendar for ${municipal.municipality}, ${municipal.province}; ${sourceCount} municipalities loaded from the rice and corn workbooks.`
        : `No ACAP municipal rice/corn crop calendar row loaded for ${ind.municipality}, ${ind.province}; ${sourceCount} municipalities are available in the workbook extract.`
    };
  }

  function _municipalityKey(value) {
    return String(value || '')
      .toLowerCase()
      .normalize('NFD')
      .replace(/[\u0300-\u036f]/g, '')
      .replace(/^city of\s+/, '')
      .replace(/\s+city$/, '')
      .replace(/[^a-z0-9]/g, '');
  }

  function _renderNoACAPCalendar() {
    return `
      <div class="calendar-empty">
        <strong>Municipal ACAP crop calendar not available for this selection.</strong>
        <span>The regional rice and corn reference remains visible beside this panel for planning comparison.</span>
      </div>
    `;
  }

  function _renderACAPCalendarSet(calendar) {
    if (!calendar) return _renderNoACAPCalendar();
    const data = CISData.getACAPCropCalendars?.();
    const periods = data?.periods || [];
    const stages = data?.stage_labels || {};
    const cropOrder = [
      ['rice', 'Rice'],
      ['corn', 'Corn'],
    ];

    return `
      <div class="acap-calendar">
        ${_renderACAPPeriodHeader(periods)}
        ${cropOrder.map(([cropKey, cropLabel]) =>
          _renderACAPCropRows(cropLabel, calendar.crops?.[cropKey] || [], periods, stages)
        ).join('')}
        ${_renderACAPStageLegend(stages)}
      </div>
    `;
  }

  function _renderACAPPeriodHeader(periods) {
    return `
      <div class="acap-cal-row acap-cal-head">
        <div class="acap-cal-label"></div>
        <div class="acap-cal-slots">
          ${periods.map(period => `
            <div class="acap-cal-month" title="${_escapeInline(period.label)}">
              ${period.key.includes('_15_') ? _escapeInline(period.month) : ''}
            </div>
          `).join('')}
        </div>
      </div>
    `;
  }

  function _renderACAPCropRows(cropLabel, entries, periods, stages) {
    if (!entries.length) {
      return `
        <div class="acap-cal-row">
          <div class="acap-cal-label">${cropLabel}</div>
          <div class="acap-cal-empty-row">No ${cropLabel.toLowerCase()} season row</div>
        </div>
      `;
    }

    return entries.map(entry => `
      <div class="acap-cal-row">
        <div class="acap-cal-label">${cropLabel} S${entry.season || '-'}</div>
        <div class="acap-cal-slots">
          ${periods.map(period => {
            const rawStage = entry.periods?.[period.key] || '';
            const stage = _stageCode(rawStage);
            const label = stage ? (stages[stage] || _titleCase(stage)) : '';
            return `
              <div class="acap-cal-slot stage-${stage || 'none'}"
                   title="${_escapeInline(period.label)}${label ? ': ' + _escapeInline(label) : ''}">
                ${stage ? _stageInitial(stage) : ''}
              </div>
            `;
          }).join('')}
        </div>
      </div>
    `).join('');
  }

  function _renderACAPStageLegend(stages) {
    const legendItems = ['prep', 'seed', 'plant', 'veg', 'vegat', 'vegpi', 'vegleaf', 'vegtass', 'repro', 'mat'];
    return `
      <div class="acap-cal-legend">
        ${legendItems.map(stage => `
          <span><i class="stage-${stage}"></i>${_escapeInline(stages[stage] || _titleCase(stage))}</span>
        `).join('')}
      </div>
    `;
  }

  function _stageCode(rawStage) {
    return String(rawStage || '').replace(/_\d+$/, '');
  }

  function _stageInitial(stage) {
    const map = {
      prep: 'P',
      seed: 'S',
      plant: 'N',
      veg: 'V',
      vegat: 'V',
      vegpi: 'PI',
      vegleaf: 'V',
      vegtass: 'T',
      repro: 'R',
      mat: 'M',
    };
    return map[stage] || stage.slice(0, 1).toUpperCase();
  }

  function _renderCropCalendar() {
    const months = ['J','F','M','A','M','J','J','A','S','O','N','D'];
    const CROPS = [
      { label:'Rice (Wet Season)',  plant:[6,7,8], grow:[8,9,10], harvest:[10,11] },
      { label:'Rice (Dry Season)',  plant:[11,12,1], grow:[1,2,3], harvest:[3,4] },
      { label:'Corn (1st crop)',    plant:[3,4,5], grow:[5,6,7], harvest:[7,8] },
      { label:'Corn (2nd crop)',    plant:[10,11], grow:[11,12,1], harvest:[1,2] },
    ];
    return `<div class="crop-cal">
      ${CROPS.map(crop => `
        <div class="cc-row">
          <span class="cc-label">${crop.label}</span>
          <div class="cc-months">
            ${months.map((m, i) => {
              const mo = i + 1;
              let cls = '';
              if (crop.plant.includes(mo)) cls = 'plant';
              else if (crop.harvest.includes(mo)) cls = 'harvest';
              else if (crop.grow.includes(mo)) cls = 'grow';
              return `<div class="cc-month ${cls}" title="${['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'][i]}">${m}</div>`;
            }).join('')}
          </div>
          <span style="font-size:9px;color:#90A4AE;margin-left:6px">
            🟢 Plant &nbsp; 🟡 Grow &nbsp; 🟠 Harvest
          </span>
        </div>
      `).join('')}
    </div>`;
  }

  function _renderAdaptations(indicators, ind) {
    const adaptations = [];
    const drought = indicators.drought_class;
    const heat = indicators.heat_stress?.heat_class;
    const anom = indicators.rainfall_anomaly?.anomaly_class;

    if (['warning','critical'].includes(drought)) {
      adaptations.push('🌱 Plant drought-tolerant rice varieties (e.g., NSIC Rc480, NSIC Rc352)');
      adaptations.push('💧 Practice alternate wetting and drying (AWD) irrigation to save water');
      adaptations.push('🌾 Apply mulching to conserve soil moisture');
      adaptations.push('📋 Register with PCIC for agricultural crop insurance');
    }
    if (['high','danger'].includes(heat)) {
      adaptations.push('⏰ Schedule field work before 9 AM or after 4 PM');
      adaptations.push('💧 Ensure adequate water and rest for farm workers');
      adaptations.push('🐔 Check livestock shade and ventilation');
      adaptations.push('🌿 Use heat-tolerant crop varieties for replanting');
    }
    if (['below','far_below'].includes(anom)) {
      adaptations.push('📊 Monitor PAGASA seasonal climate outlook for extended dry period risk');
      adaptations.push('🏗 Invest in farm-level water harvesting (farm ponds, rainwater collectors)');
    }
    if (['above','far_above'].includes(anom)) {
      adaptations.push('🚜 Ensure proper field drainage to avoid waterlogging');
      adaptations.push('🌿 Monitor for rice blast and other fungal diseases');
    }

    if (!adaptations.length) {
      adaptations.push('✅ No urgent adaptation measures required at this time.');
      adaptations.push('📅 Continue regular crop monitoring and good agricultural practices.');
    }

    return adaptations.map(a => `
      <div style="padding:5px 0;border-bottom:1px solid #F5F5F5;font-size:12px;color:#37474F">${a}</div>
    `).join('');
  }

  function filterMunicipalityList(filter) {
    renderMunicipalityList(filter);
  }

  function renderAll() {
    renderMunicipalityList();
  }

  return { renderAll, renderMunicipalityList, selectByPSGC, filterMunicipalityList };
})();
