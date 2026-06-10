/**
 * cis-advisory.js
 * Agri-Operations Advisory module for APA-CIS.
 * Renders the advisory list, full advisory detail cards,
 * field operations quick-reference table, and bulletin generator.
 *
 * DA RFO 02 — APA-CIS Climate Information Service
 */

const CISAdvisory = (() => {

  let _selectedPSGC = null;
  let _selectedAdvisory = null;
  let _selectedTab = {}; // Per rule_id: 'bulletin' | 'sms' | 'lgu' | 'facebook'

  // ── Render advisory list panel ────────────────────────────────────────────
  function renderAdvisoryList(severityFilter = 'all', provinceFilter = 'all') {
    const container = document.getElementById('adv-list');
    if (!container) return;

    const items = CISData.getActiveAdvisories(severityFilter, provinceFilter);

    if (!items.length) {
      container.innerHTML = `
        <div class="adv-empty-state" style="padding:30px 16px;">
          <div style="font-size:32px;margin-bottom:8px;">✅</div>
          <p style="font-size:12px;color:#546E7A;">No active advisories match the current filters.</p>
        </div>
      `;
      return;
    }

    container.innerHTML = items.map(item => {
      const sev = item.highest_severity || 'none';
      const sevLabel = {
        danger: '🔴 Danger', warning: '🟠 Warning',
        advisory: '🟡 Advisory', info: 'ℹ Info', none: '✅ Clear'
      }[sev] || sev;
      const primary = item.advisories?.[0]?.rule_name || '';

      return `
        <div class="adv-item sev-${sev}${_selectedPSGC === item.psgc ? ' selected' : ''}"
             onclick="CISAdvisory.selectAdvisory('${item.psgc}')">
          <div class="adv-item-top">
            <span class="adv-mun-name">${item.municipality}</span>
            <span class="pill pill-${sev === 'danger' ? 'danger' : sev === 'warning' ? 'warning' : sev === 'advisory' ? 'advisory' : 'safe'}" style="font-size:9px">${sevLabel}</span>
          </div>
          <div class="adv-province">${item.province}</div>
          <div class="adv-primary-rule">${primary}</div>
        </div>
      `;
    }).join('');
  }

  // ── Select a municipality and render its detail panel ─────────────────────
  function selectAdvisory(psgc) {
    _selectedPSGC = psgc;

    // Highlight the selected item
    document.querySelectorAll('.adv-item').forEach(el => el.classList.remove('selected'));
    const adv = CISData.getAdvisoryForMunicipality(psgc);
    const ind = CISData.getIndicatorByPSGC(psgc);

    _selectedAdvisory = adv;

    // Update detail panel header
    const header = document.getElementById('adv-detail-header');
    if (header && adv) {
      header.textContent = `${adv.municipality}, ${adv.province} — ${adv.advisory_count} Active Advisories`;
    }

    // Render detail content
    renderAdvisoryDetail(adv, ind);

    // Render ops table
    renderOpsTable(ind);

    // Highlight in list
    const items = document.querySelectorAll('.adv-item');
    items.forEach(el => {
      if (el.getAttribute('onclick')?.includes(psgc)) el.classList.add('selected');
    });
  }

  // ── Render full advisory detail ────────────────────────────────────────────
  function renderAdvisoryDetail(adv, ind) {
    const container = document.getElementById('adv-detail-content');
    if (!container) return;

    if (!adv || !adv.advisories || !adv.advisories.length) {
      container.innerHTML = `
        <div class="adv-empty-state">
          <p style="color:#546E7A">No advisory data available for this municipality.</p>
        </div>
      `;
      return;
    }

    const obsSection = ind ? `
      <div style="background:#F8FBF8;border:1px solid #DDE2EA;border-radius:4px;padding:10px 12px;margin-bottom:12px;font-size:11px;">
        <strong>Current Conditions</strong> &nbsp;·&nbsp; As of ${ind.as_of_date || '—'}
        <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:6px;margin-top:6px;">
          <div>Rainfall: <strong>${ind.observations?.rainfall_24h_mm ?? '—'} mm</strong></div>
          <div>T-max: <strong>${ind.observations?.tmax_c ?? '—'}°C</strong></div>
          <div>CDD: <strong>${ind.indicators?.cdd ?? '—'} days</strong></div>
          <div>Risk Score: <strong>${ind.indicators?.municipal_risk_score ?? '—'}/100</strong></div>
        </div>
      </div>
    ` : '';

    const rulesHTML = adv.advisories.map(rule => {
      const ruleId = rule.rule_id;
      const activeTab = _selectedTab[ruleId] || 'bulletin';
      const texts = rule.texts || {};
      const sevColors = { danger:'#FFEBEE', warning:'#FFF3E0', advisory:'#FFFDE7', info:'#E3F2FD' };
      const measures = (rule.adaptation_measures || []).slice(0, 5);
      const measuresHTML = measures.length ? `
        <div class="adaptation-box">
          <div class="adaptation-title">Recommended Adaptation Measures</div>
          <ul>
            ${measures.map(m => `<li>${_escapeHtml(m)}</li>`).join('')}
          </ul>
          <div class="adaptation-source">Source: ${_escapeHtml(rule.adaptation_source || 'CRA Compendium')}</div>
        </div>
      ` : '';

      return `
        <div class="adv-rule-card">
          <div class="adv-rule-header ${rule.severity}" style="background:${sevColors[rule.severity] || '#F5F5F5'}">
            <span class="pill pill-${rule.severity === 'danger' ? 'danger' : rule.severity === 'warning' ? 'warning' : rule.severity === 'advisory' ? 'advisory' : 'unknown'}"
                  style="font-size:9px">${rule.severity.toUpperCase()}</span>
            <span class="adv-rule-name">${rule.rule_name}</span>
          </div>
          <div style="padding:8px 12px 0">
            <small style="color:#546E7A">Affected crops: ${(rule.affected_crops || []).join(', ')}</small>
            &nbsp;·&nbsp;
            <small style="color:#546E7A">Responsible: ${rule.responsible_office || '—'}</small>
          </div>
          <div class="adv-tabs" id="tabs-${ruleId}">
            ${['bulletin','sms','lgu','facebook'].map(tab => `
              <button class="adv-tab${activeTab === tab ? ' active' : ''}"
                      onclick="CISAdvisory.switchTab('${ruleId}','${tab}')">
                ${{bulletin:'📄 Bulletin', sms:'📱 SMS', lgu:'🏛 LGU', facebook:'📘 Facebook'}[tab]}
              </button>
            `).join('')}
          </div>
          <div class="adv-tab-content" id="tab-content-${ruleId}">
            ${_escapeHtml(texts[activeTab] || 'No text available.')}
          </div>
          ${measuresHTML}
        </div>
      `;
    }).join('');

    container.innerHTML = obsSection + rulesHTML;
  }

  // ── Switch advisory text tab (bulletin/sms/lgu/facebook) ──────────────────
  function switchTab(ruleId, tab) {
    _selectedTab[ruleId] = tab;

    // Update tab buttons
    const tabsEl = document.getElementById(`tabs-${ruleId}`);
    if (tabsEl) {
      tabsEl.querySelectorAll('.adv-tab').forEach(btn => {
        btn.classList.toggle('active', btn.textContent.toLowerCase().includes(tab));
      });
    }

    // Update content
    const contentEl = document.getElementById(`tab-content-${ruleId}`);
    if (contentEl && _selectedAdvisory) {
      const rule = _selectedAdvisory.advisories?.find(r => r.rule_id === ruleId);
      if (rule?.texts) {
        contentEl.textContent = rule.texts[tab] || 'No text available.';
      }
    }
  }

  // ── Render field operations quick-reference table ─────────────────────────
  function renderOpsTable(ind) {
    const wrap = document.getElementById('ops-table-wrap');
    if (!wrap) return;

    if (!ind) {
      wrap.innerHTML = '<div class="ops-empty">Select a municipality to see field operations guidance.</div>';
      return;
    }

    const fw = ind.indicators?.field_workability;
    if (!fw || !fw.operations) {
      wrap.innerHTML = '<div class="ops-empty">No field workability data available.</div>';
      return;
    }

    const ops = fw.operations;
    const opLabels = {
      land_preparation:     ['🚜 Land Preparation', 'Ploughing, harrowing, puddling'],
      transplanting:        ['🌱 Transplanting', 'Moving seedlings to field'],
      fertilizer_application:['💊 Fertilizer Application', 'Basal and top-dressing'],
      spraying:             ['🧴 Pesticide Spraying', 'Foliar and pest management'],
      irrigation:           ['💧 Irrigation', 'Supplemental watering'],
      harvesting:           ['🌾 Harvesting', 'Combine or manual harvest'],
      drying:               ['☀️ Grain Drying', 'Sun-drying or mechanical'],
      pest_monitoring:      ['🔍 Pest Monitoring', 'Scouting and IPM'],
    };

    const overallColor = fw.color || '#4CAF50';
    const overallClass = fw.overall_class || '—';

    wrap.innerHTML = `
      <div style="background:${overallColor}15;border:1px solid ${overallColor};border-radius:4px;padding:8px 12px;margin-bottom:10px;font-size:12px;">
        <strong>Overall Field Status:</strong>
        <span style="color:${overallColor};font-weight:700;margin-left:6px">${fw.overall_label || overallClass}</span>
        &nbsp;·&nbsp;
        Rain (24h): ${fw.rain_24h_mm ?? '—'} mm
        &nbsp;·&nbsp;
        CDD: ${fw.cdd ?? '—'} days
      </div>
      <table class="ops-table">
        <thead>
          <tr>
            <th>Operation</th>
            <th>Description</th>
            <th>Status</th>
            <th>Note</th>
          </tr>
        </thead>
        <tbody>
          ${Object.entries(opLabels).map(([key, [icon, desc]]) => {
            const status = ops[key] || 'safe';
            const isSafe = status === 'safe';
            return `
              <tr>
                <td>${icon}</td>
                <td>${desc}</td>
                <td class="${isSafe ? 'ops-safe' : 'ops-defer'}">${isSafe ? '✅ SAFE' : '⛔ DEFER'}</td>
                <td style="font-size:11px;color:#546E7A">${isSafe ? 'Proceed as planned' : 'Wait for better conditions'}</td>
              </tr>
            `;
          }).join('')}
        </tbody>
      </table>
    `;
  }

  // ── Bulletin generator ────────────────────────────────────────────────────
  async function generateRegionalBulletin() {
    const output = document.getElementById('bulletin-output');
    if (!output) return;

    try {
      output.value = await CISData.getRegionalBulletin();
      return;
    } catch (err) {
      console.warn('Could not load generated regional bulletin; using browser fallback:', err);
    }

    // Fallback: assemble a simple bulletin from loaded advisory data.
    const advData = CISData.getActiveAdvisories('all', 'all');
    if (!advData.length) {
      output.value = 'No active advisories found. Run the pipeline first.';
      return;
    }

    const sevOrder = { danger:0, warning:1, advisory:2, info:3 };
    const today = new Date().toLocaleDateString('en-PH', { dateStyle: 'long' });

    const dangMuns = advData.filter(a => a.highest_severity === 'danger');
    const warnMuns = advData.filter(a => a.highest_severity === 'warning');

    let bulletin = `DA RFO 02 REGIONAL AGRICULTURAL ADVISORY\n`;
    bulletin += `Date: ${today}\n`;
    bulletin += `Coverage: Cagayan Valley (Region 02)\n`;
    bulletin += `Issued by: DA-RFO2 APA\n`;
    bulletin += `${'='.repeat(58)}\n\n`;
    bulletin += `SITUATION OVERVIEW:\n`;
    bulletin += `  Active advisories: ${advData.length} municipalities\n`;
    bulletin += `  Danger alerts: ${dangMuns.length}\n`;
    bulletin += `  Warnings: ${warnMuns.length}\n\n`;

    if (dangMuns.length) {
      bulletin += `DANGER MUNICIPALITIES — IMMEDIATE ACTION REQUIRED:\n`;
      dangMuns.forEach((m, i) => {
        bulletin += `  ${i+1}. ${m.municipality}, ${m.province}\n`;
        if (m.advisories?.[0]) bulletin += `     → ${m.advisories[0].rule_name}\n`;
      });
      bulletin += `\n`;
    }

    if (warnMuns.length) {
      bulletin += `WARNING MUNICIPALITIES:\n`;
      warnMuns.slice(0,10).forEach((m, i) => {
        bulletin += `  ${i+1}. ${m.municipality}, ${m.province}`;
        if (m.advisories?.[0]) bulletin += ` — ${m.advisories[0].rule_name}`;
        bulletin += `\n`;
      });
      bulletin += `\n`;
    }

    bulletin += `RECOMMENDED DA ACTIONS:\n`;
    if (dangMuns.length) bulletin += `  • Deploy field verification teams to danger municipalities\n`;
    bulletin += `  • Coordinate with MAOs for damage assessment and advisory dissemination\n`;
    bulletin += `  • Alert PCIC liaisons for potential crop insurance activation\n`;
    bulletin += `  • Pre-position emergency seeds and postharvest equipment\n`;
    bulletin += `\n`;
    bulletin += `For full advisory details, visit the APA-CIS portal.\n`;
    bulletin += `For assistance: 0916-708-9707; DA RFO2 APA Facebook page; arfo2apa@gmail.com\n`;
    bulletin += `\nEnd of Advisory - ${today}\n`;

    output.value = bulletin;
  }

  function copySMS() {
    if (!_selectedAdvisory) {
      alert('Please select a municipality first, then click Copy SMS Advisory.');
      return;
    }
    const firstRule = _selectedAdvisory.advisories?.[0];
    if (!firstRule?.texts?.sms) return;
    navigator.clipboard.writeText(firstRule.texts.sms)
      .then(() => alert('SMS advisory copied to clipboard.'));
  }

  function copyFacebook() {
    if (!_selectedAdvisory) {
      alert('Please select a municipality first, then click Copy Facebook Post.');
      return;
    }
    const firstRule = _selectedAdvisory.advisories?.[0];
    if (!firstRule?.texts?.facebook) return;
    navigator.clipboard.writeText(firstRule.texts.facebook)
      .then(() => alert('Facebook post copied to clipboard.'));
  }

  function filterAdvisories() {
    const sev = document.getElementById('adv-severity-filter')?.value || 'all';
    const prov = document.getElementById('adv-province-filter')?.value || 'all';
    renderAdvisoryList(sev, prov);
  }

  // ── Helper ─────────────────────────────────────────────────────────────────
  function _escapeHtml(str) {
    return (str || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  }

  // ── Render all ─────────────────────────────────────────────────────────────
  function renderAll() {
    renderAdvisoryList();
  }

  return {
    renderAll, renderAdvisoryList, selectAdvisory, switchTab,
    filterAdvisories, generateRegionalBulletin, copySMS, copyFacebook
  };
})();
