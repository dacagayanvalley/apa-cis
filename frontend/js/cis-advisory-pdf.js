/**
 * cis-advisory-pdf.js
 * Region/province/municipal weather advisory PDF generator.
 * APA style is based on the supplied advisory image; DRRM and AMIA are selectable draft modes until templates arrive.
 */

var CISAdvisoryPDF = (() => {
  const PROVINCES = ['Batanes', 'Cagayan', 'Isabela', 'Nueva Vizcaya', 'Quirino'];
  const APA_TEMPLATE_SRC = 'assets/templates/apa-weather-disturbance-template.jpg';
  const AMIA_TEMPLATE_SRC = 'assets/templates/amia-weather-disturbance-template.jpg';
  let _ready = false;
  let _apaImagePromise = null;
  let _amiaImagePromise = null;

  function renderAll() {
    _ensureDefaults();
    _populateMunicipalities();
    renderPreview();
    _ready = true;
  }

  function _ensureDefaults() {
    const dateEl = document.getElementById('pdf-issue-date');
    if (dateEl && !dateEl.value) dateEl.value = new Date().toISOString().slice(0, 10);
    const validityEl = document.getElementById('pdf-validity');
    if (validityEl && !validityEl.value) validityEl.value = 'Today until next update';
    const preparedEl = document.getElementById('pdf-prepared-by');
    if (preparedEl && !preparedEl.value) preparedEl.value = 'DA RFO 02 / APA-CIS';
    const systemEl = document.getElementById('pdf-system-name');
    if (systemEl && !systemEl.value) systemEl.value = _defaultWeatherSystem();
    const issueNoEl = document.getElementById('pdf-issue-no');
    if (issueNoEl && !issueNoEl.value) issueNoEl.value = _defaultIssueNo();
  }

  function _defaultWeatherSystem() {
    const typhoon = CISData.getPAGASAData()?.typhoon || {};
    if (typhoon.active) return `${typhoon.disturbance_type || 'Weather Disturbance'} ${typhoon.name || ''}`.trim();
    return 'Weather Disturbance Advisory';
  }

  function _defaultIssueNo() {
    const today = new Date().toISOString().slice(0, 10).replace(/-/g, '');
    return `R02-${today}`;
  }

  function _config() {
    return {
      level: document.getElementById('pdf-level')?.value || 'region',
      template: document.getElementById('pdf-template')?.value || 'apa',
      type: document.getElementById('pdf-advisory-type')?.value || 'severe',
      province: document.getElementById('pdf-province')?.value || 'all',
      psgc: document.getElementById('pdf-municipality')?.value || '',
      systemName: document.getElementById('pdf-system-name')?.value.trim() || _defaultWeatherSystem(),
      issueNo: document.getElementById('pdf-issue-no')?.value.trim() || _defaultIssueNo(),
      preparedBy: document.getElementById('pdf-prepared-by')?.value.trim() || 'DA RFO 02 / APA-CIS',
      issueDate: document.getElementById('pdf-issue-date')?.value || new Date().toISOString().slice(0, 10),
      validity: document.getElementById('pdf-validity')?.value.trim() || 'Today until next update',
    };
  }

  function _populateMunicipalities() {
    const select = document.getElementById('pdf-municipality');
    if (!select) return;

    const cfg = _config();
    const current = select.value;
    let rows = CISData.getMunicipalRows('all')
      .slice()
      .sort((a, b) => `${a.province} ${a.municipality}`.localeCompare(`${b.province} ${b.municipality}`));
    if (cfg.province !== 'all') rows = rows.filter(row => row.province === cfg.province);

    if (!rows.length) {
      select.innerHTML = '<option value="">No municipality data loaded</option>';
      return;
    }

    const active = new Set(CISData.getActiveAdvisories('all', 'all').map(a => a.psgc));
    select.innerHTML = rows.map(row => {
      const suffix = active.has(row.psgc) ? ' - active advisory' : '';
      return `<option value="${_escapeAttr(row.psgc)}">${_escapeHtml(row.municipality)}, ${_escapeHtml(row.province)}${suffix}</option>`;
    }).join('');

    const firstActive = rows.find(row => active.has(row.psgc));
    select.value = rows.some(row => row.psgc === current) ? current : firstActive?.psgc || rows[0].psgc;
  }

  function _targetRows(cfg) {
    const all = CISData.getMunicipalRows('all');
    if (cfg.level === 'region') return all;
    if (cfg.level === 'province') return all.filter(row => row.province === cfg.province && cfg.province !== 'all');
    const selected = cfg.psgc ? CISData.getIndicatorByPSGC(cfg.psgc) : null;
    return selected ? [selected] : [];
  }

  function _targetLabel(cfg, rows) {
    if (cfg.level === 'region') return 'Cagayan Valley (Region 2)';
    if (cfg.level === 'province') return cfg.province === 'all' ? 'Selected Province' : `Province of ${cfg.province}`;
    const row = rows[0];
    return row ? `${row.municipality}, ${row.province}` : 'Selected Municipality';
  }

  function _targetAdvisories(cfg, rows) {
    const rowIds = new Set(rows.map(row => row.psgc));
    return CISData.getActiveAdvisories('all', 'all').filter(item => {
      if (cfg.level === 'region') return true;
      if (cfg.level === 'province') return item.province === cfg.province;
      return rowIds.has(item.psgc);
    });
  }

  function renderPreview() {
    if (!_ready) _populateMunicipalities();
    const cfg = _config();
    _syncControlVisibility(cfg);
    _populateMunicipalities();
    const latestCfg = _config();
    const rows = _targetRows(latestCfg);
    const advisories = _targetAdvisories(latestCfg, rows);
    const preview = document.getElementById('pdf-preview');
    const visualPreview = document.getElementById('pdf-visual-preview');
    const status = document.getElementById('pdf-status-list');
    if (!preview) return;

    const text = _buildAdvisoryText(latestCfg, rows, advisories);
    preview.textContent = text;
    const hasDesignedTemplate = ['apa', 'amia'].includes(latestCfg.template);
    preview.hidden = hasDesignedTemplate;
    if (visualPreview) visualPreview.hidden = !hasDesignedTemplate;
    if (latestCfg.template === 'apa') _renderApaPreview(latestCfg, rows, advisories);
    if (latestCfg.template === 'amia') _renderAmiaPreview(latestCfg, rows, advisories);
    _renderTemplateReference(latestCfg);

    if (status) {
      const stats = _summarizeRows(rows, advisories);
      status.innerHTML = `
        <div class="pdf-status-item"><i class="pdf-status-icon">&#127970;</i><span>Level</span><strong>${_escapeHtml(_levelLabel(latestCfg.level))}</strong></div>
        <div class="pdf-status-item"><i class="pdf-status-icon">&#128205;</i><span>Target</span><strong>${_escapeHtml(_targetLabel(latestCfg, rows))}</strong></div>
        <div class="pdf-status-item"><i class="pdf-status-icon">&#128196;</i><span>Template</span><strong>${_escapeHtml(_templateLabel(latestCfg.template))}</strong></div>
        <div class="pdf-status-item"><i class="pdf-status-icon">&#9888;</i><span>Type</span><strong>${_escapeHtml(_typeLabel(latestCfg.type))}</strong></div>
        <div class="pdf-status-item"><i class="pdf-status-icon">&#127960;</i><span>Municipalities</span><strong>${stats.total}</strong></div>
        <div class="pdf-status-item"><i class="pdf-status-icon">&#128226;</i><span>Active advisories</span><strong>${advisories.length}</strong></div>
        <div class="pdf-status-item"><i class="pdf-status-icon">&#128308;</i><span>Highest severity</span><strong>${_escapeHtml(stats.highestSeverity)}</strong></div>
      `;
    }
  }

  function _syncControlVisibility(cfg) {
    const province = document.getElementById('pdf-province')?.closest('label');
    const municipality = document.getElementById('pdf-municipality')?.closest('label');
    if (province) province.style.display = cfg.level === 'region' ? 'none' : 'grid';
    if (municipality) municipality.style.display = cfg.level === 'municipal' ? 'grid' : 'none';
    const provinceSelect = document.getElementById('pdf-province');
    if (cfg.level === 'municipal' && provinceSelect?.value === 'all') provinceSelect.value = 'Cagayan';
    if (cfg.level === 'region' && provinceSelect) provinceSelect.value = 'all';
  }

  function _renderTemplateReference(cfg) {
    const el = document.getElementById('pdf-template-reference');
    if (!el) return;
    if (cfg.template === 'apa') {
      el.innerHTML = '<img src="assets/templates/apa-weather-disturbance-template.jpg" alt="APA advisory template reference">';
      return;
    }
    if (cfg.template === 'amia') {
      el.innerHTML = '<img src="assets/templates/amia-weather-disturbance-template.jpg" alt="AMIA advisory template reference">';
      return;
    }
    el.innerHTML = `<div class="pdf-template-placeholder"><strong>${_escapeHtml(_templateLabel(cfg.template))}</strong><span>Template image to follow. Current PDF uses the shared advisory layout.</span></div>`;
  }

  function _buildAdvisoryText(cfg, rows, advisories) {
    const stats = _summarizeRows(rows, advisories);
    const target = _targetLabel(cfg, rows);
    const title = _advisoryTitle(cfg, target);
    const sections = cfg.type === 'severe' ? _severeSections(cfg, rows, advisories, stats) : _normalSections(cfg, rows, advisories, stats);
    const lines = [];

    lines.push(_templateHeader(cfg.template));
    lines.push('Adapting Philippine Agriculture to Climate Change');
    lines.push(title.toUpperCase());
    lines.push('');
    lines.push(`ADVISORY LEVEL: ${_levelLabel(cfg.level)}`);
    lines.push(`TARGET AREA: ${target}`);
    lines.push(`WEATHER SYSTEM / SUBJECT: ${cfg.systemName}`);
    lines.push(`ISSUED: ${_formatDate(cfg.issueDate)}`);
    lines.push(`NO.: ${cfg.issueNo}`);
    lines.push(`VALIDITY: ${cfg.validity}`);
    lines.push(`PREPARED BY: ${cfg.preparedBy}`);
    lines.push('');
    lines.push(sections.hazardTitle.toUpperCase());
    sections.hazard.forEach(line => lines.push(`- ${line}`));
    lines.push('');
    lines.push('INAASAHANG EPEKTO SA AGRIKULTURA');
    sections.impacts.forEach(line => lines.push(`- ${line}`));
    lines.push('');
    lines.push('MGA REKOMENDASYON');
    Object.entries(sections.recommendations).forEach(([group, items]) => {
      lines.push(group.toUpperCase());
      items.forEach(item => lines.push(`- ${item}`));
      lines.push('');
    });
    lines.push('COORDINATION AND MONITORING');
    lines.push('- Makipag-ugnayan sa Department of Agriculture, LGU, at lokal na tanggapan ng agrikultura para sa maagap na kaukulang impormasyon at tulong.');
    lines.push('- Patuloy na subaybayan ang opisyal na ulat at babala ng DOST-PAGASA at lokal na awtoridad.');
    lines.push('');
    lines.push('FOOTER NOTE');
    lines.push('Ang advisory na ito ay inilalabas sa ilalim ng APA-CIS para sa suporta sa climate-informed agriculture operations sa Cagayan Valley.');
    lines.push(`Data coverage: ${stats.total} municipalities; active advisories: ${advisories.length}; highest severity: ${stats.highestSeverity}.`);
    if (cfg.template !== 'apa') lines.push(`${_templateLabel(cfg.template)} visual template pending; using shared draft format.`);
    return lines.join('\n');
  }

  function _severeSections(cfg, rows, advisories, stats) {
    const typhoon = CISData.getPAGASAData()?.typhoon || {};
    const affected = advisories.slice(0, 6).map(a => a.municipality).filter(Boolean);
    return {
      hazardTitle: cfg.type === 'severe' ? 'Malakas na Pag-ulan / Weather Disturbance' : 'Farm Weather Advisory',
      hazard: [
        `${cfg.systemName || 'Weather disturbance'} may affect ${_targetLabel(cfg, rows)}. ${typhoon.active ? 'PAGASA context indicates an active weather disturbance.' : 'Review latest PAGASA bulletin for official track and warning information.'}`,
        `Average rainfall today: ${stats.avgRainfall}; maximum temperature: ${stats.maxTemp}.`,
        affected.length ? `Priority areas based on loaded advisories: ${affected.join(', ')}${advisories.length > affected.length ? ', and others.' : '.'}` : 'No active municipal advisory rule was loaded for the selected target area.',
      ],
      impacts: [
        'Maaaring bahain ang palayan, maisan, gulayan, at iba pang taniman lalo na sa mabababang lugar at malapit sa ilog.',
        'Maaaring maantala ang pagtatanim, pag-aani, pagpapatuyo, pag-spray, at iba pang gawain sa bukid.',
        'Maaaring tumaas ang panganib sa palaisdaan, manukan, paghahayupan, makinarya, at nakahandang ani dahil sa ulan, hangin, pagbaha, o pagguho ng lupa.',
      ],
      recommendations: _recommendationGroups('severe'),
    };
  }

  function _normalSections(cfg, rows, advisories, stats) {
    return {
      hazardTitle: 'Normal Days Farm Weather Situation',
      hazard: [
        `Current farm weather situation for ${_targetLabel(cfg, rows)} based on latest APA-CIS loaded indicators.`,
        `Average rainfall today: ${stats.avgRainfall}; maximum temperature: ${stats.maxTemp}; dry spell watch areas: ${stats.droughtWatch}.`,
        'Use this advisory for routine field planning, irrigation scheduling, heat-stress management, and municipal coordination.',
      ],
      impacts: [
        'Field operations may proceed where field workability is favorable, subject to local validation.',
        'Rainfed areas with elevated consecutive dry days may require irrigation planning or crop monitoring.',
        'High-temperature areas may require adjusted work hours and livestock water management.',
      ],
      recommendations: _recommendationGroups('normal'),
    };
  }

  function _recommendationGroups(type) {
    if (type === 'severe') {
      return {
        agrikultura: [
          'Anihin ang mga hinog na pananim bago lumala ang panahon, kung maaari.',
          'Linisin ang mga kanal at tiyaking maayos ang daluyan ng tubig upang mabawasan ang pagbaha.',
          'Ipagpaliban ang paglalagay ng abono at pestisidyo habang may tuloy-tuloy na pag-ulan.',
        ],
        'manukan at paghahayupan': [
          'Ilipat ang mga alagang hayop sa mataas at ligtas na lugar.',
          'Panatilihing tuyo ang pakain at tiyaking may sapat na malinis na inuming tubig.',
          'Regular na obserbahan ang kalagayan ng mga alagang hayop pagkatapos ng masamang panahon.',
        ],
        palaisdaan: [
          'Siguraduhing nakaseguro ang fish cage, lambat, bangka, at iba pang kagamitan.',
          'Patibayin ang pilapil at bantayan ang kalidad ng tubig.',
          'Iwasan ang pangingisda habang may masamang panahon.',
        ],
        'operasyon sa bukid': [
          'Ipagpaliban ang gawaing-bukid habang may malakas na pag-ulan o delikadong hangin.',
          'Ilagay sa ligtas na lugar ang makinarya, binhi, abono, at naaning produkto.',
          'Iwasang magbiyahe ng produktong agrikultura sa bahain o delikadong kalsada.',
        ],
      };
    }
    return {
      agrikultura: [
        'Ituloy ang field operations kung ligtas ang kondisyon ng lupa at panahon.',
        'I-monitor ang moisture ng lupa at magpatubig kung mataas ang consecutive dry days.',
        'Planuhin ang abono at pest management batay sa forecast rainfall at local field condition.',
      ],
      'heat stress at manggagawa': [
        'Iwasan ang mabibigat na gawain sa pinakamainit na oras ng araw kung mataas ang heat index.',
        'Maglaan ng tubig, lilim, at pahinga para sa field workers.',
        'Bantayan ang livestock at poultry ventilation sa mainit na araw.',
      ],
      'postharvest': [
        'Gamitin ang maaraw at tuyo na oras para sa pagpapatuyo ng ani.',
        'Ihanda ang covered drying area o mechanical dryer kung may inaasahang pag-ulan.',
      ],
      coordination: [
        'I-update ang MAO/PAO monitoring reports at ipasa ang field observations sa DA RFO 02.',
        'Gamitin ang municipal risk score para sa prioritization ng technical assistance.',
      ],
    };
  }

  function _summarizeRows(rows, advisories) {
    const rainfall = rows.map(r => r.observations?.rainfall_24h_mm).filter(v => v !== null && v !== undefined);
    const temps = rows.map(r => r.observations?.tmax_c).filter(v => v !== null && v !== undefined);
    const droughtWatch = rows.filter(r => ['watch', 'warning', 'critical'].includes(r.indicators?.drought_class)).length;
    const severityOrder = { danger: 0, warning: 1, advisory: 2, info: 3, none: 4 };
    const highestSeverity = advisories.map(a => a.highest_severity || 'none').sort((a, b) => (severityOrder[a] ?? 9) - (severityOrder[b] ?? 9))[0] || 'none';
    return {
      total: rows.length,
      avgRainfall: rainfall.length ? `${(rainfall.reduce((a, b) => a + b, 0) / rainfall.length).toFixed(1)} mm` : '--',
      maxTemp: temps.length ? `${Math.max(...temps).toFixed(1)} C` : '--',
      droughtWatch,
      highestSeverity,
    };
  }

  function _advisoryTitle(cfg, target) {
    const scope = cfg.level === 'region' ? 'Cagayan Valley' : target;
    if (cfg.type === 'severe') return `Tropical Cyclone / Weather Disturbance Advisory para sa Agrikultura - ${scope}`;
    return `Farm Weather Advisory para sa Agrikultura - ${scope}`;
  }

  async function downloadPDF() {
    renderPreview();
    const cfg = _config();
    const rows = _targetRows(cfg);
    const advisories = _targetAdvisories(cfg, rows);
    const target = _targetLabel(cfg, rows);
    const safeName = `${cfg.template}-${cfg.type}-${cfg.level}-${target}`.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
    const filename = `apa-cis-advisory-${safeName}-${cfg.issueDate}.pdf`;
    const text = document.getElementById('pdf-preview')?.textContent || _buildAdvisoryText(cfg, rows, advisories);
    const blob = cfg.template === 'apa'
      ? await _createApaDesignedPDF(cfg, rows, advisories)
      : cfg.template === 'amia'
        ? await _createAmiaDesignedPDF(cfg, rows, advisories)
        : _createSimplePDF(text, cfg);
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    document.documentElement.dataset.pdfLastDownload = filename;
    URL.revokeObjectURL(url);
  }

  async function _renderApaPreview(cfg, rows, advisories) {
    const canvas = document.getElementById('pdf-apa-canvas');
    if (!canvas) return;
    try {
      await _drawApaCanvas(canvas, cfg, rows, advisories);
    } catch (error) {
      const ctx = canvas.getContext('2d');
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      ctx.fillStyle = '#fff';
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      ctx.fillStyle = '#173b24';
      ctx.font = '700 34px Arial, Helvetica, sans-serif';
      ctx.fillText('APA template preview could not be loaded.', 80, 120);
      console.warn('APA PDF preview failed', error);
    }
  }

  async function _drawApaCanvas(canvas, cfg, rows, advisories) {
    canvas.width = 1280;
    canvas.height = 1920;
    const ctx = canvas.getContext('2d');
    const img = await _loadApaTemplateImage();
    ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
    _drawApaMasks(ctx);
    _drawApaDynamicContent(ctx, cfg, rows, advisories);
  }

  function _loadApaTemplateImage() {
    if (!_apaImagePromise) {
      _apaImagePromise = new Promise((resolve, reject) => {
        const img = new Image();
        img.onload = () => resolve(img);
        img.onerror = reject;
        img.src = APA_TEMPLATE_SRC;
      });
    }
    return _apaImagePromise;
  }

  async function _renderAmiaPreview(cfg, rows, advisories) {
    const canvas = document.getElementById('pdf-apa-canvas');
    if (!canvas) return;
    try {
      await _drawAmiaCanvas(canvas, cfg, rows, advisories);
    } catch (error) {
      const ctx = canvas.getContext('2d');
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      ctx.fillStyle = '#fff';
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      ctx.fillStyle = '#075f2d';
      ctx.font = '700 34px Arial, Helvetica, sans-serif';
      ctx.fillText('AMIA template preview could not be loaded.', 80, 120);
      console.warn('AMIA PDF preview failed', error);
    }
  }

  async function _drawAmiaCanvas(canvas, cfg, rows, advisories) {
    canvas.width = 1414;
    canvas.height = 2000;
    const ctx = canvas.getContext('2d');
    const img = await _loadAmiaTemplateImage();
    ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
    _drawAmiaMasks(ctx);
    _drawAmiaDynamicContent(ctx, cfg, rows, advisories);
  }

  function _loadAmiaTemplateImage() {
    if (!_amiaImagePromise) {
      _amiaImagePromise = new Promise((resolve, reject) => {
        const img = new Image();
        img.onload = () => resolve(img);
        img.onerror = reject;
        img.src = AMIA_TEMPLATE_SRC;
      });
    }
    return _amiaImagePromise;
  }

  function _drawAmiaMasks(ctx) {
    _rect(ctx, 0, 323, 1414, 96, '#ffffff');
    _rect(ctx, 32, 420, 1347, 142, '#f9f58a');
    _rect(ctx, 44, 610, 500, 474, '#ffffff');
    _rect(ctx, 40, 1104, 505, 436, '#ffffff');
    _rect(ctx, 590, 625, 780, 608, '#bfeeff');
    _rect(ctx, 560, 1255, 820, 286, '#ffffff');
    _rect(ctx, 42, 1556, 1332, 210, '#ffffff');
    _rect(ctx, 42, 1804, 1332, 140, '#ffffff');
  }

  function _drawAmiaDynamicContent(ctx, cfg, rows, advisories) {
    const stats = _summarizeRows(rows, advisories);
    const sections = cfg.type === 'severe' ? _severeSections(cfg, rows, advisories, stats) : _normalSections(cfg, rows, advisories, stats);
    const target = _targetLabel(cfg, rows).replace('Province of ', '').replace(', ', ' - ');
    const systemName = (cfg.type === 'severe' ? cfg.systemName : 'Normal Farm Weather').toUpperCase();
    const bulletin = cfg.type === 'severe' ? cfg.issueNo.replace(/^R02-/, 'BULLETIN ') : 'NORMAL FARM WEATHER OUTLOOK';

    _centerText(ctx, bulletin.toUpperCase(), 707, 358, 32, '#050505', '900', 720, 36);
    _centerText(ctx, `Issued ${_formatShortDate(cfg.issueDate)} | ${cfg.validity}`, 707, 386, 18, '#111111', '600', 720, 22);
    _drawAmiaGlance(ctx, cfg, rows, advisories, stats, systemName);
    _drawAmiaStormPanel(ctx, cfg, stats, systemName);
    _drawAmiaMapPanel(ctx, cfg, rows, advisories, stats);
    _drawAmiaForecastPanel(ctx, cfg, rows, advisories);
    _drawAmiaTcwsPanel(ctx, cfg, rows, advisories, stats);
    _drawAmiaAdvisoryRows(ctx, sections.recommendations);
    _drawAmiaSupportRows(ctx);
    _fitText(ctx, `Department of Agriculture Regional Field Office No. 02 - ${target}`, 206, 1960, 29, '#ffffff', '900', 900);
  }

  function _drawAmiaGlance(ctx, cfg, rows, advisories, stats, systemName) {
    _roundRect(ctx, 32, 420, 1348, 145, 11, '#f9f58a', '#075f2d', 4);
    _roundRect(ctx, 49, 385, 267, 72, 18, '#075f2d');
    _centerText(ctx, 'AT A GLANCE', 182, 431, 30, '#ffffff', '900', 230, 34);
    _circle(ctx, 86, 503, 21, '#050505');
    _centerText(ctx, cfg.type === 'severe' ? 'S' : 'N', 86, 513, 24, '#ffffff', '900', 28, 28);
    _fitText(ctx, systemName, 122, 512, 30, '#050505', '900', 380);
    _line(ctx, 456, 440, 456, 545, '#075f2d', 2);
    _fitText(ctx, 'Max Winds', 554, 469, 21, '#050505', '900', 200);
    _fitText(ctx, cfg.type === 'severe' ? '65 km/h' : stats.maxTemp, 554, 508, 31, '#050505', '900', 190);
    _fitText(ctx, cfg.type === 'severe' ? 'Gustiness: up to 80 km/h' : `Avg rainfall: ${stats.avgRainfall}`, 554, 539, 17, '#050505', '700', 250);
    _line(ctx, 783, 440, 783, 545, '#075f2d', 2);
    _drawArrowIcon(ctx, 832, 494);
    _fitText(ctx, 'Movement', 890, 469, 21, '#050505', '900', 200);
    _fitText(ctx, cfg.type === 'severe' ? 'Monitor track' : 'Routine', 890, 508, 25, '#050505', '900', 220);
    _fitText(ctx, 'next bulletin', 890, 539, 20, '#050505', '900', 220);
    _line(ctx, 1060, 440, 1060, 545, '#075f2d', 2);
    _drawRainIcon(ctx, 1115, 493);
    _fitText(ctx, cfg.type === 'severe' ? 'Heavy Rainfall' : 'Farm Weather', 1170, 484, 22, '#050505', '900', 170);
    _fitText(ctx, advisories.length ? `${advisories.length} advisory areas` : 'Possible in some areas', 1170, 520, 16, '#050505', '600', 180);
  }

  function _drawAmiaStormPanel(ctx, cfg, stats, systemName) {
    _roundRect(ctx, 46, 610, 495, 475, 8, '#ffffff', '#e21a0c', 4);
    _rect(ctx, 46, 610, 495, 62, '#e21a0c');
    _fitText(ctx, systemName, 70, 652, 30, '#ffffff', '900', 455);
    const rows = [
      ['\u25CF', 'Location / Coverage', `${_targetLabel(cfg, _targetRows(cfg))}. Generated from loaded APA-CIS municipal indicators and latest PAGASA context.`],
      ['\u224B', 'Intensity', `Rainfall ${stats.avgRainfall}; maximum temperature ${stats.maxTemp}; active advisories ${stats.total ? stats.highestSeverity : 'none'}.`],
      ['\u25B6', 'Present Movement', cfg.type === 'severe' ? 'Monitor PAGASA track and bulletin updates.' : 'Routine farm-weather monitoring.'],
      ['\u25C9', 'Extent of Weather Risk', 'Localized flooding, strong wind, heat stress, or field-workability risks depend on municipal conditions.'],
    ];
    let y = 706;
    rows.forEach(row => {
      _line(ctx, 46, y - 34, 541, y - 34, '#e21a0c', 2);
      _centerText(ctx, row[0], 80, y + 15, 37, '#050505', '900', 50, 40);
      _line(ctx, 108, y - 34, 108, y + 76, '#e21a0c', 2);
      _fitText(ctx, row[1], 124, y, 20, '#050505', '900', 385);
      _wrapCanvasTextFit(ctx, row[2], 124, y + 28, 385, 72, 18, '#050505', '600', 4);
      y += 110;
    });
  }

  function _drawAmiaMapPanel(ctx, cfg, rows, advisories, stats) {
    _strokeRect(ctx, 590, 625, 780, 608, '#444444', 2);
    _rect(ctx, 615, 645, 730, 560, '#c8eefb');
    ctx.globalAlpha = 0.32;
    for (let x = 630; x < 1340; x += 105) _line(ctx, x, 645, x, 1205, '#6096aa', 1);
    for (let y = 670; y < 1200; y += 85) _line(ctx, 615, y, 1345, y, '#6096aa', 1);
    ctx.globalAlpha = 1;
    _rect(ctx, 690, 654, 510, 42, '#050505');
    _centerText(ctx, `Track and Intensity Forecast of ${cfg.systemName}`, 945, 681, 19, '#ffffff', '800', 490, 22);
    _drawLuzonShape(ctx, 888, 810, 220, 300);
    _drawStormTrackAmia(ctx);
    _multiText(ctx, [_targetLabel(cfg, rows), `Rainfall: ${stats.avgRainfall}`, `Highest severity: ${stats.highestSeverity}`], 1115, 915, 20, 28, '#1e1e1e', '800', 230);
    _fitText(ctx, 'Source: DOST-PAGASA / APA-CIS', 600, 1245, 21, '#222222', '500', 500);
  }

  function _drawAmiaForecastPanel(ctx, cfg, rows, advisories) {
    _roundRect(ctx, 44, 1106, 500, 432, 8, '#ffffff', '#ff6a1a', 4);
    _rect(ctx, 44, 1106, 500, 58, '#ff6a1a');
    _centerText(ctx, 'FORECAST POSITIONS', 294, 1145, 31, '#ffffff', '900', 450, 34);
    const target = _targetLabel(cfg, rows).replace('Province of ', '');
    const rowsText = [
      ['12-Hour Forecast', cfg.type === 'severe' ? `Near ${target}` : `Farm weather over ${target}`, cfg.type === 'severe' ? 'TS\n65 km/h' : 'NORMAL'],
      ['24-Hour Forecast', 'Monitor local rainfall, wind, heat, and field-workability updates.', cfg.type === 'severe' ? 'TS\n45 km/h' : 'WATCH'],
      ['36-Hour Forecast', 'Update advisory after next PAGASA and APA-CIS data refresh.', cfg.type === 'severe' ? 'LOW' : 'INFO'],
    ];
    let y = 1210;
    rowsText.forEach(row => {
      _line(ctx, 44, y - 30, 544, y - 30, '#ff6a1a', 2);
      _wrapCanvasTextFit(ctx, row[0], 62, y + 8, 160, 72, 20, '#050505', '900', 3);
      _wrapCanvasTextFit(ctx, row[1], 238, y + 8, 220, 72, 19, '#050505', '500', 4);
      _wrapCanvasTextFit(ctx, row[2], 466, y + 8, 60, 72, 24, '#050505', '500', 3);
      _line(ctx, 225, y - 30, 225, y + 92, '#ff6a1a', 2);
      _line(ctx, 454, y - 30, 454, y + 92, '#ff6a1a', 2);
      y += 122;
    });
  }

  function _drawAmiaTcwsPanel(ctx, cfg, rows, advisories, stats) {
    _roundRect(ctx, 560, 1264, 820, 274, 8, '#ffffff', '#ffc928', 4);
    _rect(ctx, 560, 1264, 820, 58, '#ffc928');
    _centerText(ctx, cfg.type === 'severe' ? 'TROPICAL CYCLONE WIND SIGNALS (TCWS) IN EFFECT' : 'LOCAL FARM WEATHER WATCH IN EFFECT', 970, 1304, 25, '#ffffff', '900', 760, 30);
    _centerText(ctx, cfg.type === 'severe' ? '1' : 'i', 670, 1409, 55, '#050505', '900', 80, 60);
    _line(ctx, 760, 1323, 760, 1538, '#d6b21f', 2);
    _fitText(ctx, _targetLabel(cfg, rows), 785, 1372, 26, '#050505', '900', 540);
    _wrapCanvasTextFit(ctx, `Warning lead time and risk level should be validated with PAGASA, MDRRMO/CDRRMO, MAO/PAO, and field reports. Current loaded severity: ${stats.highestSeverity}.`, 785, 1415, 530, 85, 21, '#050505', '500', 4);
  }

  function _drawAmiaAdvisoryRows(ctx, groups) {
    _roundRect(ctx, 42, 1556, 1332, 210, 8, '#ffffff', '#075f2d', 4);
    _rect(ctx, 42, 1556, 1332, 52, '#075f2d');
    _centerText(ctx, "FARMERS' ADVISORY / CLIMATE RESILIENT AGRICULTURE PRACTICES", 708, 1593, 30, '#ffffff', '900', 1200, 34);
    const labels = ['CROPS', 'INFRASTRUCTURE', 'IRRIGATION', 'LIVESTOCK', 'FARM MACHINERY', 'HARVEST & STORAGE'];
    const icons = ['\u2618', '\u2302', '\u27F3', '\u25C9', '\u25A3', '\u25A4'];
    const items = Object.values(groups).flat().slice(0, 6);
    labels.forEach((label, i) => {
      const x = 50 + i * 220;
      if (i) _line(ctx, x - 8, 1608, x - 8, 1766, '#075f2d', 2);
      _centerText(ctx, label, x + 110, 1632, 18, '#075f2d', '900', 200, 22);
      _centerText(ctx, icons[i], x + 35, 1684, 40, '#075f2d', '700', 55, 42);
      _wrapCanvasTextFit(ctx, items[i] || 'Maintain monitoring and coordinate with MAO/PAO.', x + 68, 1668, 140, 75, 16, '#050505', '500', 4);
    });
  }

  function _drawAmiaSupportRows(ctx) {
    _roundRect(ctx, 42, 1805, 1332, 140, 8, '#ffffff', '#1155a3', 4);
    _rect(ctx, 42, 1805, 1332, 52, '#1155a3');
    _centerText(ctx, 'DA RFO 02 SUPPORTS', 708, 1842, 31, '#ffffff', '900', 800, 34);
    const supports = ['INPUTS & FARM MATERIALS', 'WEATHER & CLIMATE SERVICES', 'FARM MACHINERY & TECHNICAL ASSISTANCE', 'TRAINING & EXTENSION SERVICES', 'LIVESTOCK SUPPORT'];
    supports.forEach((label, i) => {
      const x = 54 + i * 264;
      if (i) _line(ctx, x - 12, 1858, x - 12, 1944, '#1155a3', 2);
      _fitText(ctx, label, x + 55, 1890, 16, '#1155a3', '900', 190);
      _wrapCanvasTextFit(ctx, i === 0 ? 'Pre-positioned materials and farm inputs' : i === 1 ? 'Climate information services and early warnings' : i === 2 ? 'Machinery and field support' : i === 3 ? 'Technical assistance and resilient practices' : 'Animal health support', x + 55, 1918, 185, 40, 13, '#050505', '500', 3);
    });
  }

  function _drawArrowIcon(ctx, x, y) {
    ctx.fillStyle = '#050505';
    ctx.beginPath();
    ctx.moveTo(x - 25, y - 28);
    ctx.lineTo(x + 30, y);
    ctx.lineTo(x - 25, y + 28);
    ctx.lineTo(x - 10, y);
    ctx.closePath();
    ctx.fill();
  }

  function _drawStormTrackAmia(ctx) {
    const pts = [[850,1024], [878,985], [910,940], [946,892], [1005,860], [1088,925]];
    ctx.strokeStyle = '#1e4dd8';
    ctx.lineWidth = 4;
    ctx.beginPath();
    pts.forEach((p, i) => i ? ctx.lineTo(p[0], p[1]) : ctx.moveTo(p[0], p[1]));
    ctx.stroke();
    pts.forEach((p, i) => _circle(ctx, p[0], p[1], i < 2 ? 6 : 5, '#ffffff', '#1e4dd8', 3));
  }
  function _drawApaMasks(ctx) {
    _rect(ctx, 0, 226, 1280, 206, '#ffffff');
    _rect(ctx, 14, 435, 612, 540, '#ffffff');
    _rect(ctx, 648, 434, 600, 726, '#ffffff');
    _rect(ctx, 22, 970, 604, 186, '#ffffff');
    _rect(ctx, 22, 1168, 1226, 482, '#ffffff');
    _rect(ctx, 22, 1650, 1028, 178, '#eeeeee');
    _rect(ctx, 1055, 1650, 208, 178, '#ffffff');
  }

  function _drawApaDynamicContent(ctx, cfg, rows, advisories) {
    const stats = _summarizeRows(rows, advisories);
    const sections = cfg.type === 'severe' ? _severeSections(cfg, rows, advisories, stats) : _normalSections(cfg, rows, advisories, stats);
    const target = _targetLabel(cfg, rows).replace('Province of ', '').replace(', ', ' - ');
    const isSevere = cfg.type === 'severe';
    const title = isSevere ? 'TROPICAL CYCLONE ADVISORY PARA SA AGRIKULTURA' : 'FARM WEATHER ADVISORY PARA SA AGRIKULTURA';
    const system = isSevere ? cfg.systemName.toUpperCase() : 'NORMAL FARM WEATHER';

    _centerText(ctx, title, 640, 280, 36, '#063b16', '900', 1130, 40);
    _centerText(ctx, target.toUpperCase(), 640, 320, 38, '#063b16', '900', 1130, 40);
    _drawCycloneIcon(ctx, 52, 366, isSevere);
    _fitText(ctx, system, 90, 388, 48, '#050505', '900', 770);
    _roundRect(ctx, 982, 342, 280, 70, 16, '#39a6db');
    _multiText(ctx, [`Issued ${_formatShortDate(cfg.issueDate)}`, `No. ${cfg.issueNo}`], 1008, 368, 21, 27, '#ffffff', '800', 230);

    _drawMapPanel(ctx, cfg, rows, advisories, stats);
    _drawWindPanel(ctx, cfg, rows, advisories);
    _drawBlueInfoPanel(ctx, 648, 434, 600, 246, sections.hazardTitle.toUpperCase().replace(' / WEATHER DISTURBANCE', ''), sections.hazard.slice(0, 3), 'rain');
    _drawGreenInfoPanel(ctx, 648, 686, 600, 474, 'INAASAHANG EPEKTO SA AGRIKULTURA', sections.impacts);
    _drawRecommendations(ctx, sections.recommendations);
    _drawCoordinationFooter(ctx, cfg, stats);
  }

  function _drawMapPanel(ctx, cfg, rows, advisories, stats) {
    _strokeRect(ctx, 14, 435, 612, 500, '#222222', 2);
    _rect(ctx, 139, 466, 354, 36, '#050505');
    _multiText(ctx, ['Track and Intensity / Advisory Map', `${_formatDate(cfg.issueDate)} - ${cfg.systemName}`], 148, 486, 14, 16, '#ffffff', '800', 330);
    _rect(ctx, 33, 451, 578, 448, '#c8eefb');
    ctx.globalAlpha = 0.3;
    for (let x = 40; x < 610; x += 82) _line(ctx, x, 451, x, 899, '#6096aa', 1);
    for (let y = 470; y < 900; y += 68) _line(ctx, 33, y, 611, y, '#6096aa', 1);
    ctx.globalAlpha = 1;
    _drawLuzonShape(ctx, 182, 606, 190, 250);
    _drawStormTrack(ctx);
    _multiText(ctx, [cfg.level.toUpperCase(), _targetLabel(cfg, rows), `Rainfall: ${stats.avgRainfall}`, `Highest severity: ${stats.highestSeverity}`], 373, 682, 15, 22, '#1e1e1e', '700', 220);
    _fitText(ctx, 'Source: DOST-PAGASA / APA-CIS loaded monitoring data', 16, 960, 18, '#222222', '400', 610);
  }

  function _drawWindPanel(ctx, cfg, rows, advisories) {
    _roundRect(ctx, 20, 972, 608, 186, 12, '#ffffff', '#3aa6d8', 3);
    _roundRect(ctx, 20, 972, 608, 45, 12, '#3aa6d8');
    _centerText(ctx, 'LAKAS NG HANGIN NG BAGYO', 324, 1003, 25, '#ffffff', '900', 560, 28);
    _circle(ctx, 62, 1084, 29, '#182298');
    _centerText(ctx, '1', 62, 1094, 38, '#ffffff', '900', 44, 40);
    const affected = advisories.slice(0, 10).map(a => a.municipality).filter(Boolean);
    const areaText = affected.length
      ? `Ang mga lugar na may aktibong advisory ay kinabibilangan ng ${affected.join(', ')}${advisories.length > affected.length ? ', at iba pa.' : '.'}`
      : `Ang piling bahagi ng ${_targetLabel(cfg, rows)} ay maaaring makaranas ng pabugso-bugsong hangin depende sa lokal na kondisyon.`;
    _wrapCanvasTextFit(ctx, areaText, 92, 1040, 500, 100, 19, '#060606', '800', 6);
  }

  function _drawBlueInfoPanel(ctx, x, y, w, h, title, lines, icon) {
    _roundRect(ctx, x, y, w, h, 14, '#ffffff', '#2aa0d5', 4);
    _roundRect(ctx, x, y, w, 52, 14, '#39a6db');
    _circle(ctx, x + 48, y + 48, 40, '#e6f6ff', '#176b9d', 3);
    _drawRainIcon(ctx, x + 49, y + 48);
    _centerText(ctx, title, x + w / 2 + 30, y + 34, 26, '#ffffff', '900', w - 130, 30);
    _wrapCanvasTextFit(ctx, lines.join(' '), x + 59, y + 90, w - 82, h - 108, 22, '#080808', '800', 8);
  }

  function _drawGreenInfoPanel(ctx, x, y, w, h, title, lines) {
    _roundRect(ctx, x, y, w, h, 12, '#ffffff', '#087637', 4);
    _roundRect(ctx, x, y, w, 50, 12, '#087637');
    _centerText(ctx, title, x + w / 2, y + 34, 25, '#ffffff', '900', w - 40, 28);
    let cy = y + 88;
    lines.slice(0, 4).forEach(line => {
      _checkIcon(ctx, x + 30, cy - 3, 18);
      cy = _wrapCanvasTextFit(ctx, line, x + 60, cy, w - 90, 88, 21, '#050505', '800', 5) + 11;
    });
  }

  function _drawRecommendations(ctx, groups) {
    _roundRect(ctx, 22, 1170, 1226, 48, 10, '#087637');
    _centerText(ctx, 'MGA REKOMENDASYON', 635, 1204, 26, '#ffffff', '900', 1000, 30);
    _line(ctx, 635, 1218, 635, 1650, '#222222', 2);
    _line(ctx, 22, 1434, 1248, 1434, '#222222', 2);
    const names = Object.keys(groups).slice(0, 4);
    const boxes = [[22, 1218, 613, 216], [635, 1218, 613, 216], [22, 1434, 613, 216], [635, 1434, 613, 216]];
    names.forEach((name, index) => {
      const box = boxes[index];
      const x = box[0], y = box[1], w = box[2];
      _centerText(ctx, name.toUpperCase(), x + w / 2, y + 39, 24, '#087637', '900', w - 40, 28);
      _circle(ctx, x + 88, y + 117, 48, '#ffffff', '#087637', 4);
      _simpleSectorIcon(ctx, x + 88, y + 117, index);
      let cy = y + 83;
      groups[name].slice(0, 3).forEach(item => {
        _checkIcon(ctx, x + 150, cy - 5, 10);
        cy = _wrapCanvasTextFit(ctx, item, x + 172, cy, w - 192, 56, 15, '#050505', '800', 4) + 4;
      });
    });
  }

  function _drawCoordinationFooter(ctx, cfg, stats) {
    _strokeRect(ctx, 22, 1650, 1226, 84, '#222222', 2);
    _circle(ctx, 176, 1681, 12, '#ff7d35');
    _circle(ctx, 176, 1715, 12, '#ff7d35');
    _wrapCanvasTextFit(ctx, 'Makipag-ugnayan sa Department of Agriculture, mga LGU, at lokal na tanggapan ng agrikultura para sa maagap na kaukulang impormasyon at tulong.', 210, 1683, 970, 30, 16, '#050505', '800', 2);
    _wrapCanvasTextFit(ctx, 'Patuloy na subaybayan ang mga opisyal na ulat at babala ng DOST-PAGASA at mga lokal na awtoridad.', 210, 1714, 970, 30, 16, '#050505', '800', 2);
    _wrapCanvasTextFit(ctx, `Ang advisory na ito ay inilalabas sa ilalim ng Adapting Philippine Agriculture to Climate Change (APA) Project para sa ${_targetLabel(cfg, _targetRows(cfg))}. Data coverage: ${stats.total} municipalities.`, 36, 1788, 990, 88, 20, '#171717', '400', 4, 'italic');
  }

  async function _createApaDesignedPDF(cfg, rows, advisories) {
    const canvas = document.createElement('canvas');
    await _drawApaCanvas(canvas, cfg, rows, advisories);
    const bytes = _dataUrlToBytes(canvas.toDataURL('image/jpeg', 0.94));
    return _createImageOnlyPDF(bytes, 595.28, 892.92, canvas.width, canvas.height);
  }

  async function _createAmiaDesignedPDF(cfg, rows, advisories) {
    const canvas = document.createElement('canvas');
    await _drawAmiaCanvas(canvas, cfg, rows, advisories);
    const bytes = _dataUrlToBytes(canvas.toDataURL('image/jpeg', 0.94));
    return _createImageOnlyPDF(bytes, 595.28, 841.89, canvas.width, canvas.height);
  }

  function _createImageOnlyPDF(jpegBytes, pageWidth, pageHeight, imageWidth, imageHeight) {
    const encoder = new TextEncoder();
    const chunks = [];
    const offsets = [0];
    let position = 0;
    const addString = value => { const bytes = encoder.encode(value); chunks.push(bytes); position += bytes.length; };
    const addBytes = bytes => { chunks.push(bytes); position += bytes.length; };
    const objectCount = 5;
    addString('%PDF-1.4\n');
    const addObject = (id, body) => { offsets[id] = position; addString(`${id} 0 obj\n${body}\nendobj\n`); };
    addObject(1, '<< /Type /Catalog /Pages 2 0 R >>');
    addObject(2, '<< /Type /Pages /Kids [3 0 R] /Count 1 >>');
    addObject(3, `<< /Type /Page /Parent 2 0 R /MediaBox [0 0 ${pageWidth} ${pageHeight}] /Resources << /XObject << /Im1 4 0 R >> >> /Contents 5 0 R >>`);
    offsets[4] = position;
    addString(`4 0 obj\n<< /Type /XObject /Subtype /Image /Width ${imageWidth || 1280} /Height ${imageHeight || 1920} /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode /Length ${jpegBytes.length} >>\nstream\n`);
    addBytes(jpegBytes);
    addString('\nendstream\nendobj\n');
    const stream = `q\n${pageWidth} 0 0 ${pageHeight} 0 0 cm\n/Im1 Do\nQ`;
    addObject(5, `<< /Length ${encoder.encode(stream).length} >>\nstream\n${stream}\nendstream`);
    const xrefOffset = position;
    addString(`xref\n0 ${objectCount + 1}\n0000000000 65535 f \n`);
    for (let i = 1; i <= objectCount; i += 1) addString(`${String(offsets[i]).padStart(10, '0')} 00000 n \n`);
    addString(`trailer\n<< /Size ${objectCount + 1} /Root 1 0 R >>\nstartxref\n${xrefOffset}\n%%EOF`);
    return new Blob(chunks, { type: 'application/pdf' });
  }

  function _dataUrlToBytes(dataUrl) {
    const base64 = dataUrl.split(',')[1] || '';
    const binary = atob(base64);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
    return bytes;
  }

  function _rect(ctx, x, y, w, h, fill) { ctx.fillStyle = fill; ctx.fillRect(x, y, w, h); }
  function _strokeRect(ctx, x, y, w, h, color, width) { ctx.strokeStyle = color; ctx.lineWidth = width; ctx.strokeRect(x, y, w, h); }
  function _line(ctx, x1, y1, x2, y2, color, width) { ctx.strokeStyle = color; ctx.lineWidth = width; ctx.beginPath(); ctx.moveTo(x1, y1); ctx.lineTo(x2, y2); ctx.stroke(); }
  function _circle(ctx, x, y, r, fill, stroke, width) { ctx.beginPath(); ctx.arc(x, y, r, 0, Math.PI * 2); ctx.fillStyle = fill; ctx.fill(); if (stroke) { ctx.strokeStyle = stroke; ctx.lineWidth = width || 2; ctx.stroke(); } }
  function _roundRect(ctx, x, y, w, h, r, fill, stroke, width) { ctx.beginPath(); ctx.moveTo(x + r, y); ctx.arcTo(x + w, y, x + w, y + h, r); ctx.arcTo(x + w, y + h, x, y + h, r); ctx.arcTo(x, y + h, x, y, r); ctx.arcTo(x, y, x + w, y, r); ctx.closePath(); if (fill) { ctx.fillStyle = fill; ctx.fill(); } if (stroke) { ctx.strokeStyle = stroke; ctx.lineWidth = width || 2; ctx.stroke(); } }
  function _font(size, weight, style) { return `${style ? `${style} ` : ''}${weight || '700'} ${size}px 'Arial Narrow', 'Roboto Condensed', Arial, Helvetica, sans-serif`; }
  function _fitText(ctx, text, x, y, size, color, weight, maxWidth) { let s = size; ctx.fillStyle = color; ctx.textBaseline = 'alphabetic'; do { ctx.font = _font(s, weight); s -= 1; } while (ctx.measureText(text).width > maxWidth && s > 14); ctx.fillText(text, x, y); }
  function _centerText(ctx, text, x, y, size, color, weight, maxWidth) { let s = size; ctx.fillStyle = color; ctx.textAlign = 'center'; ctx.textBaseline = 'alphabetic'; do { ctx.font = _font(s, weight); s -= 1; } while (ctx.measureText(text).width > maxWidth && s > 14); ctx.fillText(text, x, y); ctx.textAlign = 'left'; }
  function _multiText(ctx, lines, x, y, size, lineHeight, color, weight, maxWidth) { lines.forEach((line, index) => _fitText(ctx, line, x, y + index * lineHeight, size, color, weight, maxWidth)); }
  function _measureWrapLines(ctx, text, maxWidth, size, weight, style) {
    ctx.font = _font(size, weight, style);
    const words = String(text || '').split(/\s+/).filter(Boolean);
    const lines = [];
    let line = '';
    words.forEach(word => {
      const test = line ? `${line} ${word}` : word;
      if (ctx.measureText(test).width > maxWidth && line) { lines.push(line); line = word; }
      else line = test;
    });
    if (line) lines.push(line);
    return lines;
  }
  function _wrapCanvasText(ctx, text, x, y, maxWidth, lineHeight, size, color, weight, maxLines, style) {
    const lines = _measureWrapLines(ctx, text, maxWidth, size, weight, style).slice(0, maxLines);
    ctx.font = _font(size, weight, style);
    ctx.fillStyle = color;
    ctx.textBaseline = 'alphabetic';
    lines.forEach((line, index) => ctx.fillText(line, x, y + index * lineHeight));
    return y + lines.length * lineHeight;
  }
  function _wrapCanvasTextFit(ctx, text, x, y, maxWidth, maxHeight, size, color, weight, maxLines, style) {
    let s = size;
    let lh = Math.max(13, Math.round(size * 1.12));
    let lines = _measureWrapLines(ctx, text, maxWidth, s, weight, style);
    while ((lines.length > maxLines || lines.length * lh > maxHeight) && s > 11) {
      s -= 1;
      lh = Math.max(12, Math.round(s * 1.12));
      lines = _measureWrapLines(ctx, text, maxWidth, s, weight, style);
    }
    lines = lines.slice(0, Math.min(maxLines, Math.floor(maxHeight / lh)));
    ctx.font = _font(s, weight, style);
    ctx.fillStyle = color;
    ctx.textBaseline = 'alphabetic';
    lines.forEach((line, index) => ctx.fillText(line, x, y + index * lh));
    return y + lines.length * lh;
  }
  function _formatShortDate(value) { const d = new Date(value); if (Number.isNaN(d.getTime())) return value; const day = String(d.getDate()).padStart(2, '0'); const month = d.toLocaleDateString('en-PH', { month: 'long' }); return `${day} ${month} ${d.getFullYear()}`; }
  function _drawCycloneIcon(ctx, x, y, severe) { _circle(ctx, x, y, 33, severe ? '#9c9c9c' : '#2da3d5'); _circle(ctx, x + 3, y - 2, 10, '#ffffff'); }
  function _drawRainIcon(ctx, x, y) { ctx.fillStyle = '#243081'; ctx.beginPath(); ctx.arc(x - 11, y - 8, 15, Math.PI, Math.PI * 2); ctx.arc(x + 7, y - 13, 20, Math.PI, Math.PI * 2); ctx.arc(x + 25, y - 7, 14, Math.PI, Math.PI * 2); ctx.fill(); ctx.strokeStyle = '#243081'; ctx.lineWidth = 4; for (let i = -20; i <= 28; i += 16) _line(ctx, x + i, y + 14, x + i - 9, y + 34, '#243081', 4); }
  function _checkIcon(ctx, x, y, r) { _circle(ctx, x, y, r, '#087637'); ctx.strokeStyle = '#ffffff'; ctx.lineWidth = Math.max(4, r / 3); ctx.beginPath(); ctx.moveTo(x - r * 0.45, y); ctx.lineTo(x - r * 0.12, y + r * 0.35); ctx.lineTo(x + r * 0.52, y - r * 0.45); ctx.stroke(); }
  function _drawLuzonShape(ctx, x, y, w, h) { ctx.fillStyle = '#f6d98d'; ctx.strokeStyle = '#bfa35c'; ctx.lineWidth = 2; ctx.beginPath(); ctx.moveTo(x + w * 0.55, y); ctx.bezierCurveTo(x + w * 0.15, y + h * 0.1, x, y + h * 0.45, x + w * 0.22, y + h * 0.72); ctx.bezierCurveTo(x + w * 0.45, y + h, x + w * 0.86, y + h * 0.88, x + w * 0.75, y + h * 0.55); ctx.bezierCurveTo(x + w, y + h * 0.22, x + w * 0.82, y + h * 0.02, x + w * 0.55, y); ctx.fill(); ctx.stroke(); }
  function _drawStormTrack(ctx) { const pts = [[438,867], [409,832], [375,786], [344,739], [310,694], [281,650]]; ctx.strokeStyle = '#1e4dd8'; ctx.lineWidth = 4; ctx.beginPath(); pts.forEach((p, i) => i ? ctx.lineTo(p[0], p[1]) : ctx.moveTo(p[0], p[1])); ctx.stroke(); pts.forEach(p => _circle(ctx, p[0], p[1], 5, '#ffffff', '#1e4dd8', 3)); }
  function _simpleSectorIcon(ctx, x, y, index) { ctx.strokeStyle = '#087637'; ctx.lineWidth = 5; ctx.beginPath(); if (index === 0) { ctx.moveTo(x, y + 28); ctx.lineTo(x, y - 20); ctx.moveTo(x, y - 4); ctx.quadraticCurveTo(x - 34, y - 20, x - 20, y + 14); ctx.moveTo(x, y - 8); ctx.quadraticCurveTo(x + 34, y - 28, x + 20, y + 10); } else if (index === 1) { ctx.arc(x - 18, y + 5, 14, 0, Math.PI * 2); ctx.moveTo(x + 18, y + 18); ctx.lineTo(x + 32, y - 22); ctx.lineTo(x + 5, y - 8); } else if (index === 2) { ctx.moveTo(x - 36, y); ctx.quadraticCurveTo(x, y - 30, x + 38, y); ctx.quadraticCurveTo(x, y + 30, x - 36, y); ctx.moveTo(x + 12, y - 4); ctx.arc(x + 17, y - 4, 2, 0, Math.PI * 2); } else { ctx.rect(x - 28, y - 18, 46, 32); ctx.arc(x - 15, y + 23, 8, 0, Math.PI * 2); ctx.arc(x + 18, y + 23, 8, 0, Math.PI * 2); } ctx.stroke(); }
  function _createSimplePDF(text, cfg) {
    const pageWidth = 595.28;
    const pageHeight = 841.89;
    const margin = 42;
    const fontSize = 9.5;
    const lineHeight = 12;
    const maxChars = 88;
    const usableLines = Math.floor((pageHeight - margin * 2) / lineHeight);
    const wrappedLines = _wrapTextForPDF(text, maxChars);
    const pages = [];
    for (let i = 0; i < wrappedLines.length; i += usableLines) pages.push(wrappedLines.slice(i, i + usableLines));
    if (!pages.length) pages.push(['No advisory content available.']);

    const objects = [];
    const addObject = content => { objects.push(content); return objects.length; };
    const catalogId = addObject('');
    const pagesId = addObject('');
    const fontId = addObject('<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>');
    const boldFontId = addObject('<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>');
    const pageIds = [];

    pages.forEach((lines, pageIndex) => {
      const stream = _pdfPageStream(lines, margin, pageWidth, pageHeight, fontSize, lineHeight, pageIndex, cfg);
      const contentId = addObject(`<< /Length ${_byteLength(stream)} >>\nstream\n${stream}\nendstream`);
      const pageId = addObject(`<< /Type /Page /Parent ${pagesId} 0 R /MediaBox [0 0 ${pageWidth} ${pageHeight}] /Resources << /Font << /F1 ${fontId} 0 R /F2 ${boldFontId} 0 R >> >> /Contents ${contentId} 0 R >>`);
      pageIds.push(pageId);
    });

    objects[catalogId - 1] = `<< /Type /Catalog /Pages ${pagesId} 0 R >>`;
    objects[pagesId - 1] = `<< /Type /Pages /Kids [${pageIds.map(id => `${id} 0 R`).join(' ')}] /Count ${pageIds.length} >>`;
    let pdf = '%PDF-1.4\n';
    const offsets = [0];
    objects.forEach((object, index) => {
      offsets.push(_byteLength(pdf));
      pdf += `${index + 1} 0 obj\n${object}\nendobj\n`;
    });
    const xrefOffset = _byteLength(pdf);
    pdf += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n`;
    for (let i = 1; i < offsets.length; i += 1) pdf += `${String(offsets[i]).padStart(10, '0')} 00000 n \n`;
    pdf += `trailer\n<< /Size ${objects.length + 1} /Root ${catalogId} 0 R >>\nstartxref\n${xrefOffset}\n%%EOF`;
    return new Blob([pdf], { type: 'application/pdf' });
  }

  function _pdfPageStream(lines, x, pageWidth, pageHeight, fontSize, lineHeight, pageIndex, cfg) {
    const commands = [];
    const isApa = cfg.template === 'apa';
    if (isApa) {
      commands.push('0.93 0.90 0.82 rg', `0 ${pageHeight - 62} ${pageWidth} 62 re f`);
      commands.push('0.00 0.45 0.24 rg', `0 ${pageHeight - 79} ${pageWidth} 17 re f`);
      commands.push('0.20 0.68 0.88 rg', `0 ${pageHeight - 112} ${pageWidth} 33 re f`);
      commands.push('1 1 1 rg', `0 ${pageHeight - 123} ${pageWidth} 14 re f`);
    } else if (cfg.template === 'drrm') {
      commands.push('0.55 0.08 0.08 rg', `0 ${pageHeight - 86} ${pageWidth} 86 re f`);
    } else {
      commands.push('0.10 0.45 0.25 rg', `0 ${pageHeight - 86} ${pageWidth} 86 re f`);
    }
    commands.push('0 0 0 rg');
    commands.push('BT', `/F1 ${fontSize} Tf`, `${x} ${pageHeight - x - (pageIndex === 0 ? 92 : 0)} Td`);
    lines.forEach((line, index) => {
      if (index > 0) commands.push(`0 -${lineHeight} Td`);
      const upper = line && line === line.toUpperCase() && line.length < 90;
      commands.push(upper ? `/F2 ${Math.min(fontSize + 1.5, 12)} Tf` : `/F1 ${fontSize} Tf`);
      commands.push(`(${_escapePDFText(line)}) Tj`);
    });
    commands.push('ET');
    return commands.join('\n');
  }

  async function copyPreview() {
    const text = document.getElementById('pdf-preview')?.textContent || '';
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
      alert('Advisory text copied.');
    } catch (_) {
      alert('Copy failed. You can manually select the preview text.');
    }
  }

  function _wrapTextForPDF(text, maxChars) {
    const output = [];
    String(text || '').split('\n').forEach(line => {
      const clean = line.replace(/\t/g, '  ');
      if (!clean) { output.push(''); return; }
      let current = '';
      clean.split(/\s+/).forEach(word => {
        if (!current) current = word;
        else if ((current + ' ' + word).length <= maxChars) current += ' ' + word;
        else { output.push(current); current = word; }
      });
      if (current) output.push(current);
    });
    return output;
  }

  function _escapePDFText(value) {
    return String(value || '').replace(/[^\x09\x0A\x0D\x20-\x7E]/g, '').replace(/\\/g, '\\\\').replace(/\(/g, '\\(').replace(/\)/g, '\\)');
  }

  function _byteLength(value) { return new Blob([value]).size; }
  function _templateHeader(template) { return { apa: 'APA TEMPLATE - DA RFO 02 / APA / FAO / GCF', drrm: 'DRRM TEMPLATE - WEATHER AND DISASTER RISK ADVISORY', amia: 'AMIA TEMPLATE - CLIMATE RESILIENT AGRICULTURE ADVISORY' }[template] || 'ADVISORY TEMPLATE'; }
  function _levelLabel(level) { return { region: 'Region 2 Level', province: 'Province Level', municipal: 'Municipal Level' }[level] || level; }
  function _templateLabel(template) { return { apa: 'APA Template', drrm: 'DRRM Template', amia: 'AMIA Template' }[template] || template; }
  function _typeLabel(type) { return type === 'severe' ? 'Severe Weather / Disturbance' : 'Normal Days / Farm Weather'; }
  function _formatDate(value) { const d = new Date(value); return Number.isNaN(d.getTime()) ? value : d.toLocaleDateString('en-PH', { year: 'numeric', month: 'long', day: '2-digit' }); }
  function _escapeHtml(str) { return String(str || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g, '&quot;'); }
  function _escapeAttr(str) { return _escapeHtml(str).replace(/'/g, '&#39;'); }

  return { renderAll, renderPreview, downloadPDF, copyPreview };
})();

globalThis.CISAdvisoryPDF = CISAdvisoryPDF;

function _bindAdvisoryPDFEvents() {
  document.documentElement.dataset.advisoryPdfModule = 'loaded';
  document.addEventListener('click', event => {
    const actionEl = event.target.closest('[data-pdf-action]');
    if (actionEl) {
      const action = actionEl.dataset.pdfAction;
      if (action === 'download') CISAdvisoryPDF.downloadPDF();
      if (action === 'preview') CISAdvisoryPDF.renderPreview();
      if (action === 'copy') CISAdvisoryPDF.copyPreview();
      return;
    }
    if (event.target.closest('[data-module="pdf"]')) setTimeout(() => CISAdvisoryPDF.renderAll(), 80);
  });
  document.addEventListener('input', event => {
    if (event.target.matches('[data-pdf-input="preview"]')) CISAdvisoryPDF.renderPreview();
  });
  document.addEventListener('change', event => {
    if (event.target.matches('[data-pdf-input="preview"]')) CISAdvisoryPDF.renderPreview();
  });
}

if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', _bindAdvisoryPDFEvents);
else _bindAdvisoryPDFEvents();