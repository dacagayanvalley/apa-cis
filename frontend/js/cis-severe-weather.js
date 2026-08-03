/**
 * cis-severe-weather.js
 * PAGASA severe weather module for official disturbance-aware agri advisories.
 */

const CISSevereWeather = (() => {
  let _allRows = [];
  let _allAffected = [];
  let _items = [];
  let _selected = null;
  let _sortKey = 'score';
  let _sortDir = 'desc';

  const PROVINCES = ['Batanes', 'Cagayan', 'Isabela', 'Nueva Vizcaya', 'Quirino'];

  function renderAll() {
    const pagasa = CISData.getPAGASAData() || {};
    const typhoon = pagasa.typhoon || {};
    _allRows = CISData.getMunicipalRows('all');
    _allAffected = _affectedRows(_allRows, typhoon).map(row => _buildItem(row, typhoon));
    const provinceFilter = document.getElementById('sw-province-filter')?.value || 'all';
    _items = _sortItems(
      _allAffected.filter(item => provinceFilter === 'all' || item.province === provinceFilter)
    );

    _renderStatus(typhoon, _allAffected);
    _renderTable(typhoon);
    _renderSortIndicators();
    _renderSummary(typhoon);

    if (_items.length) {
      const stillSelected = _items.find(item => item.psgc === _selected?.psgc);
      selectMunicipality((stillSelected || _items[0]).psgc);
    } else {
      _selected = null;
      _renderEmptyDetail(typhoon);
    }
  }

  function sortTable(key) {
    if (_sortKey === key) {
      _sortDir = _sortDir === 'asc' ? 'desc' : 'asc';
    } else {
      _sortKey = key;
      _sortDir = ['municipality', 'province', 'severity'].includes(key) ? 'asc' : 'desc';
    }
    renderAll();
  }

  function selectMunicipality(psgc) {
    _selected = _items.find(item => item.psgc === psgc) || null;
    document.querySelectorAll('#sw-tbody tr').forEach(tr => {
      tr.classList.toggle('selected-row', tr.dataset.psgc === psgc);
    });
    if (!_selected) return;
    const title = document.getElementById('sw-detail-title');
    const detail = document.getElementById('sw-detail');
    if (title) title.textContent = `Severe Weather - ${_selected.municipality}`;
    if (detail) detail.innerHTML = _detailHTML(_selected);
  }

  function _affectedRows(rows, typhoon) {
    if (!typhoon.active || !typhoon.region2_affected) return [];
    const affectedPsgc = new Set((typhoon.affected_municipalities || []).map(item => item.psgc));
    const signalLevels = typhoon.signal_levels || {};
    return rows.filter(row => affectedPsgc.has(row.psgc) || (signalLevels[row.province] || 0) > 0);
  }

  function _unaffectedRows(province = null) {
    const affectedPsgc = new Set(_allAffected.map(item => item.psgc));
    return _allRows
      .filter(row => !affectedPsgc.has(row.psgc))
      .filter(row => !province || row.province === province)
      .sort((a, b) => (a.province || '').localeCompare(b.province || '') || (a.municipality || '').localeCompare(b.municipality || ''));
  }

  function _buildItem(row, typhoon) {
    const obs = row.observations || {};
    const ind = row.indicators || {};
    const signal = (typhoon.signal_levels || {})[row.province] || typhoon.signal_level || 0;
    const rainOverride = _pagasaRainOverride(row, typhoon, signal);
    const windOverride = _pagasaWindOverride(row, typhoon, signal);
    const rain24 = rainOverride.rain24 ?? Number(obs.rainfall_24h_mm || 0);
    const rain48 = rainOverride.rain48 ?? Number(obs.rainfall_48h_mm || 0);
    const wind = windOverride.windMs ?? Number(obs.wind_speed_ms || 0);
    const tmax = Number(obs.tmax_c || 0);
    const fieldClass = ind.field_workability?.overall_class || 'unknown';
    const baseRisk = Number(ind.municipal_risk_score || 0);

    let score = signal * 22 + Math.min(baseRisk, 100) * 0.25;
    if (rain24 >= 100) score += 35;
    else if (rain24 >= 50) score += 25;
    else if (rain24 >= 25) score += 15;
    else if (rain24 >= 10) score += 8;
    if (rain48 >= 120) score += 18;
    else if (rain48 >= 60) score += 10;
    if (wind >= 15) score += 18;
    else if (wind >= 10) score += 10;
    else if (wind >= 6) score += 5;
    if (tmax >= 36) score += 8;
    if (['not_workable', 'high_risk'].includes(fieldClass)) score += 12;

    const severity = score >= 70 ? 'danger' : score >= 45 ? 'warning' : 'advisory';
    return {
      psgc: row.psgc,
      municipality: row.municipality,
      province: row.province,
      asOf: row.as_of_date,
      typhoon,
      signal,
      rain24,
      rain48,
      wind,
      windKmh: windOverride.windKmh,
      windRangeKmh: windOverride.windRangeKmh,
      gustinessKmh: windOverride.gustinessKmh,
      rainSource: rainOverride.source || 'APA-CIS municipal weather',
      windSource: windOverride.source || 'APA-CIS municipal weather',
      tmax,
      humidity: obs.humidity_pct,
      fieldClass,
      heatClass: ind.heat_stress?.heat_class || 'low',
      cropRisk: ind.crop_stage_risk?.risk_class || 'unknown',
      score: Math.round(score),
      severity,
      actions: _actions({ signal, rain24, rain48, wind, tmax, fieldClass }),
    };
  }

  function _pagasaRainOverride(row, typhoon, signal) {
    const payloads = _weatherPayloads(row, typhoon, signal);
    for (const payload of payloads) {
      const rain24 = _numberFromAny(payload.data, [
        'rainfall_24h_mm', 'rain_24h_mm', 'rainfall_mm', 'forecast_rainfall_mm',
        'expected_rainfall_mm', 'max_rainfall_mm', 'amount_mm'
      ]);
      const rain48 = _numberFromAny(payload.data, [
        'rainfall_48h_mm', 'rain_48h_mm', 'expected_rainfall_48h_mm', 'max_rainfall_48h_mm'
      ]);
      if (rain24 !== null || rain48 !== null) {
        return { rain24, rain48, source: payload.source };
      }
    }
    return { rain24: null, rain48: null, source: '' };
  }

  function _pagasaWindOverride(row, typhoon, signal) {
    const payloads = _weatherPayloads(row, typhoon, signal);
    for (const payload of payloads) {
      const gustinessKmh = _numberFromAny(payload.data, [
        'gustiness_kmh', 'wind_gustiness_kmh', 'max_gust_kmh', 'gust_kmh', 'wind_gust_kmh'
      ]);
      const sustainedKmh = _numberFromAny(payload.data, [
        'max_sustained_wind_kmh', 'sustained_wind_kmh', 'wind_speed_kmh', 'expected_wind_kmh'
      ]);
      const range = _windRangeFromPayload(payload.data);
      const windKmh = gustinessKmh ?? (range ? range.max : sustainedKmh);
      if (windKmh !== null && windKmh !== undefined) {
        return {
          windMs: windKmh / 3.6,
          windKmh,
          windRangeKmh: range,
          gustinessKmh,
          source: payload.source,
        };
      }
    }

    const tcwsRange = _tcwsWindRange(typhoon, signal);
    if (tcwsRange) {
      return {
        windMs: tcwsRange.max / 3.6,
        windKmh: null,
        windRangeKmh: tcwsRange,
        gustinessKmh: null,
        source: `PAGASA TCWS ${signal}`,
      };
    }
    return { windMs: null, windKmh: null, windRangeKmh: null, gustinessKmh: null, source: '' };
  }

  function _weatherPayloads(row, typhoon, signal) {
    const municipalityPayload = _findWeatherPayload([
      typhoon.weather_by_municipality,
      typhoon.municipality_weather,
      typhoon.rainfall_by_municipality,
      typhoon.wind_by_municipality,
      typhoon.affected_municipalities,
    ], row, 'municipality');
    const provincePayload = _findWeatherPayload([
      typhoon.weather_by_province,
      typhoon.province_weather,
      typhoon.rainfall_by_province,
      typhoon.wind_by_province,
    ], row, 'province');

    return [
      municipalityPayload && { data: municipalityPayload, source: 'PAGASA municipal severe-weather advisory' },
      provincePayload && { data: provincePayload, source: 'PAGASA provincial severe-weather advisory' },
      typhoon.weather && { data: typhoon.weather, source: 'PAGASA severe-weather bulletin' },
      typhoon.rainfall && { data: typhoon.rainfall, source: 'PAGASA rainfall advisory' },
      typhoon.wind && { data: typhoon.wind, source: 'PAGASA wind advisory' },
      typhoon.gustiness_kmh !== undefined && { data: typhoon, source: 'PAGASA severe-weather bulletin' },
      signal && typhoon.tcws_wind_ranges && { data: (typhoon.tcws_wind_ranges[String(signal)] || typhoon.tcws_wind_ranges[`TCWS ${signal}`] || {}), source: `PAGASA TCWS ${signal}` },
    ].filter(Boolean);
  }

  function _findWeatherPayload(collections, row, scope) {
    for (const collection of collections) {
      if (!collection) continue;
      if (Array.isArray(collection)) {
        const found = collection.find(item => _matchesWeatherPayload(item, row, scope));
        if (found) return found;
      } else if (typeof collection === 'object') {
        const keys = scope === 'province'
          ? [row.province]
          : [row.psgc, row.municipality, `${row.municipality}, ${row.province}`];
        for (const key of keys) {
          if (key && collection[key]) return collection[key];
        }
      }
    }
    return null;
  }

  function _matchesWeatherPayload(item, row, scope) {
    if (!item || typeof item !== 'object') return false;
    if (scope === 'province') return item.province === row.province;
    return item.psgc === row.psgc || (item.municipality === row.municipality && (!item.province || item.province === row.province));
  }

  function _numberFromAny(source, keys) {
    if (!source || typeof source !== 'object') return null;
    for (const key of keys) {
      const value = _numericValue(source[key]);
      if (value !== null) return value;
    }
    const range = _numericRange(source.rainfall_range_mm || source.wind_range_kmh || source.range_kmh || source.range);
    return range ? range.max : null;
  }

  function _numericValue(value) {
    if (value === null || value === undefined || value === '') return null;
    if (typeof value === 'number' && Number.isFinite(value)) return value;
    const match = String(value).match(/\d+(?:\.\d+)?/);
    return match ? Number(match[0]) : null;
  }

  function _numericRange(value) {
    if (value === null || value === undefined || value === '') return null;
    const nums = String(value).match(/\d+(?:\.\d+)?/g);
    if (!nums?.length) return null;
    const parsed = nums.map(Number).filter(Number.isFinite);
    return parsed.length ? { min: Math.min(...parsed), max: Math.max(...parsed) } : null;
  }

  function _windRangeFromPayload(source) {
    if (!source || typeof source !== 'object') return null;
    if (source.min_wind_kmh !== undefined || source.max_wind_kmh !== undefined) {
      const min = _numericValue(source.min_wind_kmh);
      const max = _numericValue(source.max_wind_kmh);
      if (min !== null || max !== null) return { min: min ?? max, max: max ?? min };
    }
    return _numericRange(source.wind_range_kmh || source.expected_wind_kmh || source.range_kmh || source.range);
  }

  function _tcwsWindRange(typhoon, signal) {
    if (!signal) return null;
    const ranges = typhoon.tcws_wind_ranges || {};
    const parsed = _windRangeFromPayload(ranges[String(signal)] || ranges[`TCWS ${signal}`] || {});
    if (parsed) return parsed;
    const defaults = {
      1: { min: 39, max: 61 },
      2: { min: 62, max: 88 },
      3: { min: 89, max: 117 },
      4: { min: 118, max: 184 },
      5: { min: 185, max: 220 },
    };
    return defaults[signal] || null;
  }
  function _sortItems(items) {
    const severityOrder = { danger: 0, warning: 1, advisory: 2 };
    const valueFor = item => {
      switch (_sortKey) {
        case 'municipality': return item.municipality || '';
        case 'province': return item.province || '';
        case 'signal': return item.signal || 0;
        case 'rain24': return item.rain24 || 0;
        case 'wind': return item.wind || 0;
        case 'tmax': return item.tmax || 0;
        case 'score': return item.score || 0;
        case 'severity': return severityOrder[item.severity] ?? 9;
        default: return item.score || 0;
      }
    };
    return [...items].sort((a, b) => {
      const av = valueFor(a);
      const bv = valueFor(b);
      let cmp = typeof av === 'string' || typeof bv === 'string'
        ? String(av).localeCompare(String(bv))
        : av - bv;
      return _sortDir === 'asc' ? cmp : -cmp;
    });
  }

  function _renderStatus(typhoon, affectedAll) {
    const active = Boolean(typhoon.active);
    const affected = Boolean(typhoon.region2_affected);
    _setText('sw-status', active ? (affected ? 'Active and affecting Region 2' : 'Active outside Region 2') : 'No active PAGASA bulletin');
    _setText('sw-issued', typhoon.issued_at ? `Issued ${typhoon.issued_at}` : `Checked ${typhoon.as_of || 'today'}`);
    _setText('sw-system', active ? `${typhoon.disturbance_type || 'Weather Disturbance'} ${typhoon.name || ''}`.trim() : 'None detected');
    _setText('sw-validity', typhoon.valid_until || 'Monitor PAGASA for updates');
    _setText('sw-affected-count', affectedAll.length ? `${affectedAll.length} municipalities` : '0 municipalities');
    _setText('sw-affected-provinces', (typhoon.affected_provinces || []).join(', ') || 'No Cagayan Valley municipalities matched');

    const highest = [...affectedAll].sort((a, b) => b.score - a.score)[0];
    _setText('sw-highest-risk', highest ? _severityLabel(highest.severity) : 'Clear');
    _setText('sw-highest-risk-sub', highest ? `${highest.municipality}, ${highest.province} (${highest.score})` : 'No localized severe-weather advisory');

    const card = document.getElementById('sw-status-card');
    if (card) card.classList.toggle('severe-active', active && affected);
    const clear = document.getElementById('sw-clear-state');
    if (clear) {
      clear.classList.toggle('hidden', active && affected);
      clear.textContent = active
        ? 'PAGASA has an active severe-weather bulletin, but no Cagayan Valley municipality was matched in the current parsed affected areas.'
        : 'No active PAGASA tropical cyclone bulletin is detected. Keep routine monitoring active and refresh after the next pipeline run.';
    }
    const link = document.getElementById('severe-source-link');
    if (link && typhoon.source_url) link.href = typhoon.source_url;
  }

  function _renderTable(typhoon) {
    const tbody = document.getElementById('sw-tbody');
    if (!tbody) return;
    if (!typhoon.active || !typhoon.region2_affected) {
      tbody.innerHTML = '<tr><td colspan="8" class="loading-row">No affected Cagayan Valley municipalities detected from the active PAGASA bulletin.</td></tr>';
      return;
    }
    if (!_items.length) {
      tbody.innerHTML = '<tr><td colspan="8" class="loading-row">No municipalities match this filter.</td></tr>';
      return;
    }
    tbody.innerHTML = _items.map(item => `
      <tr data-psgc="${item.psgc}" onclick="CISSevereWeather.selectMunicipality('${item.psgc}')" style="cursor:pointer">
        <td><strong>${_escape(item.municipality)}</strong></td>
        <td>${_escape(item.province)}</td>
        <td>${item.signal ? `TCWS ${item.signal}` : '-'}</td>
        <td>${_formatRain(item)}</td>
        <td>${_formatWind(item)}</td>
        <td>${item.tmax ? item.tmax.toFixed(1) + ' C' : '-'}</td>
        <td>${item.score}</td>
        <td>${_severityPill(item.severity)}</td>
      </tr>
    `).join('');
  }

  function _renderSortIndicators() {
    document.querySelectorAll('#sw-table th.sortable').forEach(th => {
      const active = th.dataset.sortKey === _sortKey;
      th.classList.toggle('sorted', active);
      th.setAttribute('aria-sort', active ? (_sortDir === 'asc' ? 'ascending' : 'descending') : 'none');
      const indicator = th.querySelector('.sort-indicator');
      if (indicator) indicator.textContent = active ? (_sortDir === 'asc' ? '▲' : '▼') : '↕';
    });
  }

  function _renderSummary(typhoon) {
    const summaryEl = document.getElementById('sw-provincial-summary');
    const regionalEl = document.getElementById('sw-regional-actions');
    if (summaryEl) summaryEl.innerHTML = _provincialSummaryHTML(typhoon);
    if (regionalEl) regionalEl.innerHTML = _regionalActionsHTML(typhoon);
  }

  function _provincialSummaryHTML(typhoon) {
    if (!typhoon.active || !typhoon.region2_affected) {
      return '<div class="ops-empty">No active Region 2 severe-weather exposure to summarize.</div>';
    }
    return PROVINCES.map(province => {
      const affected = _allAffected.filter(item => item.province === province);
      const unaffected = _unaffectedRows(province);
      const bySignal = _groupBySignal(affected);
      return `
        <div class="province-summary-card">
          <div class="province-summary-head">
            <div>
              <strong>${_escape(province)}</strong>
              <span>TCWS ${Math.max(0, ...affected.map(item => item.signal || 0)) || '-'}</span>
            </div>
            <div class="province-summary-counts">
              <span>${affected.length} affected</span>
              <span>${unaffected.length} not affected</span>
            </div>
          </div>
          <div class="province-summary-body">
            <div class="province-summary-section affected">
              <div class="adaptation-title">Affected Municipalities by TCWS</div>
              ${affected.length ? Object.entries(bySignal).map(([signal, items]) => `
                <div class="sw-signal-group"><b>${signal}</b><span>${items.map(item => _escape(item.municipality)).join(', ')}</span></div>
              `).join('') : '<div class="muted-cell">No affected municipalities parsed for this province.</div>'}
            </div>
            <div class="province-summary-section unaffected">
              <div class="adaptation-title">Municipalities Not Affected</div>
              <div class="sw-muni-list">${unaffected.length ? unaffected.map(row => _escape(row.municipality)).join(', ') : 'None'}</div>
            </div>
          </div>
          <div class="province-summary-section actions">
            <div class="adaptation-title">Provincial DA / LGU Agri Action</div>
            <ul>${_provincialActions(province, affected, unaffected).map(action => `<li>${_escape(action)}</li>`).join('')}</ul>
          </div>
        </div>
      `;
    }).join('');
  }

  function _regionalActionsHTML(typhoon) {
    if (!typhoon.active || !typhoon.region2_affected) {
      return '<div class="ops-empty">No active Region 2 severe-weather advisory. Maintain routine monitoring.</div>';
    }
    const affectedProvinces = [...new Set(_allAffected.map(item => item.province))];
    const highestSignal = Math.max(0, ..._allAffected.map(item => item.signal || 0));
    const highRiskCount = _allAffected.filter(item => ['danger', 'warning'].includes(item.severity)).length;
    const actions = [
      `Activate regional APA-CIS severe-weather monitoring for ${affectedProvinces.join(', ')} under highest parsed TCWS ${highestSignal || '-'}.`,
      'Issue synchronized DA RFO 02, PAO, MAO, and LGU agri advisories after each PAGASA bulletin cycle and whenever local DRRMO reports change.',
      'Prioritize affected municipalities for field validation, drainage clearing support, seedling/nursery protection, and post-event crop damage assessment.',
      'Keep non-affected municipalities on standby monitoring; do not relax routine flood, wind, heat, and crop disease surveillance while the disturbance is active.',
    ];
    if (highRiskCount) actions.push(`${highRiskCount} affected municipalities are at Warning/Danger level from combined PAGASA and APA-CIS local indicators; prioritize these for rapid coordination.`);
    return `
      <div class="regional-actions-card">
        <div class="adaptation-title">Regional DA / LGU Agri Action</div>
        <ul>${actions.map(action => `<li>${_escape(action)}</li>`).join('')}</ul>
      </div>
    `;
  }

  function _groupBySignal(items) {
    return items.reduce((groups, item) => {
      const key = item.signal ? `TCWS ${item.signal}` : 'No TCWS parsed';
      groups[key] = groups[key] || [];
      groups[key].push(item);
      return groups;
    }, {});
  }

  function _provincialActions(province, affected, unaffected) {
    if (!affected.length) {
      return [`Keep ${province} on monitoring status; no municipality is currently parsed as affected by the PAGASA bulletin.`];
    }
    const maxSignal = Math.max(...affected.map(item => item.signal || 0));
    const heavyRain = affected.filter(item => item.rain24 >= 25).length;
    const restricted = affected.filter(item => ['not_workable', 'high_risk'].includes(item.fieldClass)).length;
    const actions = [
      `Coordinate PAO/MAO advisories for ${affected.length} affected municipalities under ${maxSignal ? 'TCWS ' + maxSignal : 'PAGASA affected-area listing'}.`,
      'Suspend or defer spraying, fertilizer application, and exposed field operations in affected municipalities during rainbands or gusty wind periods.',
      'Secure nurseries, seedling trays, irrigation pumps, harvested produce, and drying facilities before conditions worsen.',
    ];
    if (heavyRain) actions.push(`${heavyRain} affected municipalities already show at least 25 mm rainfall in 24h; prioritize drainage checks and flood reporting.`);
    if (restricted) actions.push(`${restricted} affected municipalities have restricted field-workability indicators; hold field operations until local conditions improve.`);
    if (unaffected.length) actions.push(`For ${unaffected.length} not-affected municipalities, maintain bulletin monitoring and prepare standby rapid assessment teams.`);
    return actions;
  }

  function _detailHTML(item) {
    return `
      <div class="severe-advisory-card ${item.severity}">
        <div class="severe-advisory-kicker">${_escape(item.typhoon.summary || 'PAGASA Severe Weather Bulletin')}</div>
        <h3>${_severityLabel(item.severity)} level for ${_escape(item.municipality)}</h3>
        <p>${_escape(_narrative(item))}</p>
      </div>
      <div class="severe-metrics-grid">
        <div><span>TCWS</span><strong>${item.signal || '-'}</strong></div>
        <div><span>Rain 24h</span><strong>${_formatRainValue(item)}</strong><small>${_escape(item.rainSource)}</small></div>
        <div><span>Wind</span><strong>${_formatWindValue(item)}</strong><small>${_escape(item.windSource)}</small></div>
        <div><span>Max Temp</span><strong>${item.tmax ? item.tmax.toFixed(1) + ' C' : '-'}</strong></div>
      </div>
      <div class="severe-actions">
        <div class="adaptation-title">Recommended DA / LGU Agri Actions</div>
        <ul>${item.actions.map(action => `<li>${_escape(action)}</li>`).join('')}</ul>
      </div>
      <div class="severe-source-note">
        Official trigger: PAGASA Severe Weather Bulletin. Rainfall and wind/gustiness values use PAGASA severe-weather advisory data when available; APA-CIS municipal weather remains the fallback for missing fields. Validate high-impact actions with PAGASA, MDRRMO/CDRRMO, MAO/PAO, and field reports.
      </div>
    `;
  }

  function _renderEmptyDetail(typhoon) {
    const title = document.getElementById('sw-detail-title');
    const detail = document.getElementById('sw-detail');
    if (title) title.textContent = 'Selected Municipality';
    if (detail) detail.innerHTML = `
      <div class="adv-empty-state">
        <div style="font-size:40px;margin-bottom:12px;">!</div>
        <p>${typhoon.active ? 'No affected municipality is available for the current filter.' : 'No active PAGASA severe-weather bulletin is detected.'}</p>
      </div>
    `;
  }

  function _formatRain(item) {
    return `${_formatRainValue(item)}<div class="muted-cell">${_escape(item.rainSource)}</div>`;
  }

  function _formatRainValue(item) {
    return `${Number(item.rain24 || 0).toFixed(1)} mm`;
  }

  function _formatWind(item) {
    return `${_formatWindValue(item)}<div class="muted-cell">${_escape(item.windSource)}</div>`;
  }

  function _formatWindValue(item) {
    if (item.windRangeKmh) return `${item.windRangeKmh.min}-${item.windRangeKmh.max} km/h`;
    if (item.windKmh) return `${item.windKmh.toFixed(0)} km/h`;
    return item.wind ? `${item.wind.toFixed(1)} m/s` : '-';
  }
  function _actions(item) {
    const actions = [
      'Monitor PAGASA bulletins and local DRRMO instructions; update MAO/PAO field teams every advisory cycle.',
      'Suspend non-essential field travel in areas with strong winds, flooding, landslide risk, or unsafe river crossings.',
    ];
    if (item.signal >= 1 || item.wind >= 6) {
      actions.push('Secure seedling trays, nurseries, greenhouse covers, irrigation pumps, drying mats, and lightweight farm structures.');
      actions.push('Advise farmers to avoid pesticide or foliar spraying while gusty winds and rainbands are expected.');
    }
    if (item.rain24 >= 25 || item.rain48 >= 60) {
      actions.push('Defer fertilizer application and land preparation; clear canals and check drainage around rice, corn, and vegetable fields.');
      actions.push('Pre-position rapid assessment forms for possible flooding, lodging, erosion, and crop damage validation.');
    }
    if (item.tmax >= 35) {
      actions.push('Maintain heat precautions for field teams and livestock handlers during breaks between rainbands.');
    }
    if (['not_workable', 'high_risk'].includes(item.fieldClass)) {
      actions.push('Classify field operations as restricted until rainfall, wind, and soil conditions improve.');
    }
    actions.push('Prioritize mature crop harvest only when conditions are safe; avoid forced harvesting during active warning conditions.');
    return actions;
  }

  function _narrative(item) {
    const system = `${item.typhoon.disturbance_type || 'weather disturbance'} ${item.typhoon.name || ''}`.trim();
    const rainText = item.rain24 >= 50 ? 'heavy recent rainfall' : item.rain24 >= 25 ? 'moderate recent rainfall' : 'localized rainfall monitoring';
    const windText = item.signal || item.wind >= 6 ? 'wind-sensitive farm operations should be restricted' : 'wind impact is currently limited in the available indicators';
    return `${system || 'The active PAGASA bulletin'} affects ${item.province}. Based on ${rainText} (${item.rainSource}), ${_formatWindValue(item)} wind (${item.windSource}), and field-workability status (${item.fieldClass}), ${windText}.`;
  }

  function _severityLabel(severity) {
    return severity === 'danger' ? 'Danger' : severity === 'warning' ? 'Warning' : 'Advisory';
  }

  function _severityPill(severity) {
    const cls = severity === 'danger' ? 'pill-danger' : severity === 'warning' ? 'pill-warning' : 'pill-advisory';
    return `<span class="pill ${cls}">${_severityLabel(severity)}</span>`;
  }

  function _setText(id, value) {
    const el = document.getElementById(id);
    if (el) el.textContent = value || '--';
  }

  function _escape(value) {
    return String(value || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  return { renderAll, sortTable, selectMunicipality };
})();