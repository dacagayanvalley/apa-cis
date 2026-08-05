/**
 * cis-advisory-pdf.js
 * Region/province/municipal weather advisory PDF generator.
 * APA style is based on the supplied advisory image; DRRM and AMIA are selectable draft modes until templates arrive.
 */

var CISAdvisoryPDF = (() => {
  const PROVINCES = ['Batanes', 'Cagayan', 'Isabela', 'Nueva Vizcaya', 'Quirino'];
  let _ready = false;

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
    return 'Farm Weather Advisory';
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
    const rows = _targetRows(_config());
    const advisories = _targetAdvisories(_config(), rows);
    const preview = document.getElementById('pdf-preview');
    const status = document.getElementById('pdf-status-list');
    if (!preview) return;

    const text = _buildAdvisoryText(_config(), rows, advisories);
    preview.textContent = text;
    _renderTemplateReference(_config());

    if (status) {
      const stats = _summarizeRows(rows, advisories);
      status.innerHTML = `
        <div class="pdf-status-item"><span>Level</span><strong>${_escapeHtml(_levelLabel(_config().level))}</strong></div>
        <div class="pdf-status-item"><span>Target</span><strong>${_escapeHtml(_targetLabel(_config(), rows))}</strong></div>
        <div class="pdf-status-item"><span>Template</span><strong>${_escapeHtml(_templateLabel(_config().template))}</strong></div>
        <div class="pdf-status-item"><span>Type</span><strong>${_escapeHtml(_typeLabel(_config().type))}</strong></div>
        <div class="pdf-status-item"><span>Municipalities</span><strong>${stats.total}</strong></div>
        <div class="pdf-status-item"><span>Active advisories</span><strong>${advisories.length}</strong></div>
        <div class="pdf-status-item"><span>Highest severity</span><strong>${_escapeHtml(stats.highestSeverity)}</strong></div>
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

  function downloadPDF() {
    renderPreview();
    const cfg = _config();
    const rows = _targetRows(cfg);
    const target = _targetLabel(cfg, rows);
    const text = document.getElementById('pdf-preview')?.textContent || _buildAdvisoryText(cfg, rows, _targetAdvisories(cfg, rows));
    const safeName = `${cfg.template}-${cfg.type}-${cfg.level}-${target}`.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
    const filename = `apa-cis-advisory-${safeName}-${cfg.issueDate}.pdf`;
    const blob = _createSimplePDF(text, cfg);
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