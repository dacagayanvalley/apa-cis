/**
 * cis-access-monitor.js
 * Privacy-conscious access monitoring for APA-CIS.
 * Persists locally by default and syncs to Supabase when configured.
 */

const CISAccessMonitor = (() => {
  const STORAGE_KEY = 'apa_cis_access_monitor_v1';
  const VISITOR_KEY = 'apa_cis_visitor_id';
  const SESSION_KEY = 'apa_cis_session_id';
  const PROFILE_KEY = 'apa_cis_visitor_profile_v1';
  const MAX_LOCAL_EVENTS = 500;

  let _client = null;
  let _authUser = null;
  let _filter = '';
  let _cache = { sessions: [], events: [] };

  async function init() {
    _ensureIds();
    _initSupabase();
    await _loadAuthUser();
    _hydrateProfileForm();
    _renderAuthState();
    logEvent('page_view', { module: window._activeModule || 'dashboard' });
    renderAll();
  }

  function _initSupabase() {
    const cfg = window.CIS_MONITORING_CONFIG || {};
    const state = document.getElementById('monitoring-sync-state');
    if (window.supabase && cfg.supabaseUrl && cfg.supabaseAnonKey) {
      _client = window.supabase.createClient(cfg.supabaseUrl, cfg.supabaseAnonKey);
      if (state) state.textContent = 'Supabase monitoring enabled';
      _client.auth.onAuthStateChange(async (_event, session) => {
        _authUser = session?.user || null;
        if (_authUser) await _mergeAuthProfile(_authUser);
        _hydrateProfileForm();
        _renderAuthState();
        logEvent(_authUser ? 'auth_signed_in' : 'auth_signed_out', { module: 'monitoring' });
        renderAll();
      });
    } else if (state) {
      state.textContent = 'Local monitoring mode';
    }
  }

  async function _loadAuthUser() {
    if (!_client) return;
    try {
      const { data } = await _client.auth.getUser();
      _authUser = data?.user || null;
      if (_authUser) await _mergeAuthProfile(_authUser);
    } catch (err) {
      console.warn('[APA-CIS] Auth user lookup failed:', err);
    }
  }

  async function _mergeAuthProfile(user) {
    const localProfile = getProfile();
    const metadata = user.user_metadata || {};
    const profile = {
      email: user.email || localProfile.email || '',
      auth_user_id: user.id,
      identity_source: 'supabase_auth',
      name: localProfile.name || metadata.full_name || metadata.name || '',
      agency: localProfile.agency || metadata.agency || '',
      role: localProfile.role || metadata.role || '',
      office_location: localProfile.office_location || metadata.office_location || '',
    };
    _setProfile(profile);
    await _syncUserProfile(profile);
  }

  async function _syncUserProfile(profile = getProfile()) {
    if (!_client || !_authUser) return;
    try {
      const payload = {
        auth_user_id: _authUser.id,
        email: _authUser.email || profile.email || null,
        name: profile.name || null,
        agency: profile.agency || null,
        role: profile.role || null,
        office_location: profile.office_location || null,
        updated_at: new Date().toISOString(),
      };
      await _client.from('user_profiles').upsert(payload, { onConflict: 'auth_user_id' });
    } catch (err) {
      console.warn('[APA-CIS] User profile sync failed:', err);
    }
  }

  function _ensureIds() {
    if (!localStorage.getItem(VISITOR_KEY)) {
      localStorage.setItem(VISITOR_KEY, _uuid());
    }
    if (!sessionStorage.getItem(SESSION_KEY)) {
      sessionStorage.setItem(SESSION_KEY, _uuid());
    }
  }

  function _uuid() {
    if (crypto.randomUUID) return crypto.randomUUID();
    return 'id-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2);
  }

  function getVisitorId() {
    _ensureIds();
    return localStorage.getItem(VISITOR_KEY);
  }

  function getSessionId() {
    _ensureIds();
    return sessionStorage.getItem(SESSION_KEY);
  }

  function getProfile() {
    try {
      return JSON.parse(localStorage.getItem(PROFILE_KEY) || '{}');
    } catch (_) {
      return {};
    }
  }

  function _setProfile(profile) {
    localStorage.setItem(PROFILE_KEY, JSON.stringify({ ...getProfile(), ...profile, updated_at: new Date().toISOString() }));
  }

  function _readStore() {
    try {
      return JSON.parse(localStorage.getItem(STORAGE_KEY) || '{"sessions":[],"events":[]}');
    } catch (_) {
      return { sessions: [], events: [] };
    }
  }

  function _writeStore(store) {
    store.events = (store.events || []).slice(-MAX_LOCAL_EVENTS);
    localStorage.setItem(STORAGE_KEY, JSON.stringify(store));
  }

  function _deviceSummary() {
    const ua = navigator.userAgent || '';
    const mobile = /Mobi|Android|iPhone|iPad/i.test(ua);
    const browser = ua.includes('Edg/') ? 'Edge' : ua.includes('Chrome/') ? 'Chrome' : ua.includes('Firefox/') ? 'Firefox' : ua.includes('Safari/') ? 'Safari' : 'Browser';
    return `${browser} / ${mobile ? 'Mobile' : 'Desktop'}`;
  }

  function _baseSession(moduleName) {
    const profile = getProfile();
    const location = profile.geo || {};
    return {
      visitor_id: getVisitorId(),
      session_id: getSessionId(),
      auth_user_id: _authUser?.id || profile.auth_user_id || null,
      email: _authUser?.email || profile.email || null,
      identity_source: _authUser ? 'supabase_auth' : 'self_declared',
      name: profile.name || '',
      agency: profile.agency || '',
      role: profile.role || '',
      office_location: profile.office_location || '',
      latitude: location.latitude ?? null,
      longitude: location.longitude ?? null,
      location_accuracy_m: location.accuracy ?? null,
      location_consented: Boolean(location.latitude && location.longitude),
      device: _deviceSummary(),
      user_agent: navigator.userAgent || '',
      language: navigator.language || '',
      module_name: moduleName || 'dashboard',
      last_seen_at: new Date().toISOString(),
    };
  }

  async function logEvent(eventType, details = {}) {
    const moduleName = details.module || window._activeModule || 'dashboard';
    const session = _baseSession(moduleName);
    const event = {
      event_id: _uuid(),
      visitor_id: session.visitor_id,
      session_id: session.session_id,
      auth_user_id: session.auth_user_id,
      event_type: eventType,
      module_name: moduleName,
      path: location.pathname,
      details,
      created_at: session.last_seen_at,
    };

    const store = _readStore();
    const existing = store.sessions.findIndex(s => s.session_id === session.session_id);
    if (existing >= 0) {
      store.sessions[existing] = { ...store.sessions[existing], ...session };
    } else {
      store.sessions.push(session);
    }
    store.events.push(event);
    _writeStore(store);
    _cache = store;

    if (_client) {
      try {
        await _client.from('access_sessions').upsert(session, { onConflict: 'session_id' });
        await _client.from('access_events').insert(event);
      } catch (err) {
        console.warn('[APA-CIS] Access monitor Supabase sync failed:', err);
      }
    }

    if (document.getElementById('module-monitoring')?.classList.contains('active')) renderAll();
  }

  async function loadData() {
    if (_client && _authUser) {
      try {
        const [sessionsRes, eventsRes] = await Promise.all([
          _client.from('access_sessions').select('*').order('last_seen_at', { ascending: false }).limit(250),
          _client.from('access_events').select('*').order('created_at', { ascending: false }).limit(500),
        ]);
        if (!sessionsRes.error && !eventsRes.error) {
          _cache = { sessions: sessionsRes.data || [], events: eventsRes.data || [] };
          return _cache;
        }
      } catch (err) {
        console.warn('[APA-CIS] Access monitor read failed:', err);
      }
    }
    _cache = _readStore();
    return _cache;
  }

  async function renderAll() {
    const data = await loadData();
    _renderCards(data);
    _renderTable(data);
    _renderSummaries(data);
    _renderAuthState();
  }

  function _renderCards(data) {
    const visitorCount = new Set(data.sessions.map(s => s.visitor_id)).size;
    const locationCount = data.sessions.filter(s => s.location_consented || (s.latitude && s.longitude)).length;
    _setText('mon-visitors', visitorCount);
    _setText('mon-sessions', data.sessions.length);
    _setText('mon-locations', locationCount);
    _setText('mon-events', data.events.length);
  }

  function _renderTable(data) {
    const tbody = document.getElementById('monitoring-tbody');
    if (!tbody) return;
    const term = _filter.toLowerCase();
    const eventCounts = data.events.reduce((acc, ev) => {
      acc[ev.session_id] = (acc[ev.session_id] || 0) + 1;
      return acc;
    }, {});
    let rows = [...data.sessions].sort((a, b) => String(b.last_seen_at || '').localeCompare(String(a.last_seen_at || '')));
    if (term) {
      rows = rows.filter(s => [s.name, s.email, s.agency, s.role, s.office_location, s.module_name, s.device, s.identity_source].join(' ').toLowerCase().includes(term));
    }
    if (!rows.length) {
      tbody.innerHTML = '<tr><td colspan="8" class="loading-row">No access records match the filter.</td></tr>';
      return;
    }
    tbody.innerHTML = rows.slice(0, 100).map(s => `
      <tr>
        <td>${_formatDateTime(s.last_seen_at)}</td>
        <td><strong>${_escapeHtml(s.name || 'Unidentified')}</strong><small>${_escapeHtml(s.email || s.identity_source || 'self-declared')}</small></td>
        <td>${_escapeHtml(s.agency || 'Not provided')}</td>
        <td>${_escapeHtml(s.role || '--')}</td>
        <td>${_formatLocation(s)}</td>
        <td>${_escapeHtml(s.device || '--')}</td>
        <td>${_escapeHtml(_moduleLabel(s.module_name))}</td>
        <td>${eventCounts[s.session_id] || 0}</td>
      </tr>
    `).join('');
  }

  function _renderSummaries(data) {
    _renderSummaryList('monitoring-agencies', _countBy(data.sessions, 'agency', 'Not provided'));
    _renderSummaryList('monitoring-modules', _countBy(data.events, 'module_name', 'dashboard'), _moduleLabel);
  }

  function _countBy(rows, key, fallback) {
    return rows.reduce((acc, row) => {
      const label = row[key] || fallback;
      acc[label] = (acc[label] || 0) + 1;
      return acc;
    }, {});
  }

  function _renderSummaryList(id, counts, formatter = value => value) {
    const el = document.getElementById(id);
    if (!el) return;
    const rows = Object.entries(counts).sort((a, b) => b[1] - a[1]).slice(0, 8);
    if (!rows.length) {
      el.innerHTML = '<div class="monitoring-empty">No records yet.</div>';
      return;
    }
    el.innerHTML = rows.map(([label, count]) => `
      <div class="monitoring-summary-row">
        <span>${_escapeHtml(formatter(label))}</span>
        <strong>${count}</strong>
      </div>
    `).join('');
  }

  async function signIn(event) {
    if (event) event.preventDefault();
    const email = document.getElementById('monitor-email')?.value.trim();
    if (!_client) {
      _setAuthStatus('Supabase is not configured yet. Add CIS_MONITORING_CONFIG to enable email sign-in.', 'warning');
      return;
    }
    if (!email) {
      _setAuthStatus('Enter an email address first.', 'warning');
      return;
    }
    const profile = getProfile();
    try {
      const { error } = await _client.auth.signInWithOtp({
        email,
        options: {
          emailRedirectTo: window.location.href.split('#')[0],
          data: {
            name: profile.name || undefined,
            agency: profile.agency || undefined,
            role: profile.role || undefined,
            office_location: profile.office_location || undefined,
          },
        },
      });
      if (error) throw error;
      _setProfile({ email, identity_source: 'supabase_auth_pending' });
      _setAuthStatus(`Sign-in link sent to ${email}. Open it in this browser to verify identity.`, 'success');
      logEvent('auth_link_requested', { module: 'monitoring' });
    } catch (err) {
      _setAuthStatus(err.message || 'Could not send sign-in link.', 'error');
    }
  }

  async function signOut() {
    if (!_client) return;
    try {
      await _client.auth.signOut();
      _authUser = null;
      _setProfile({ auth_user_id: null, identity_source: 'self_declared' });
      _renderAuthState();
      logEvent('auth_signed_out', { module: 'monitoring' });
    } catch (err) {
      _setAuthStatus(err.message || 'Could not sign out.', 'error');
    }
  }

  async function saveProfile(event) {
    if (event) event.preventDefault();
    _setProfile({
      name: document.getElementById('monitor-name')?.value.trim() || '',
      agency: document.getElementById('monitor-agency')?.value.trim() || '',
      role: document.getElementById('monitor-role')?.value || '',
      office_location: document.getElementById('monitor-office-location')?.value.trim() || '',
      email: _authUser?.email || document.getElementById('monitor-email')?.value.trim() || getProfile().email || '',
      auth_user_id: _authUser?.id || getProfile().auth_user_id || null,
      identity_source: _authUser ? 'supabase_auth' : 'self_declared',
    });
    await _syncUserProfile();
    logEvent('profile_saved', { module: 'monitoring' });
    renderAll();
  }

  function _hydrateProfileForm() {
    const profile = getProfile();
    _setValue('monitor-name', profile.name || '');
    _setValue('monitor-agency', profile.agency || '');
    _setValue('monitor-role', profile.role || '');
    _setValue('monitor-office-location', profile.office_location || '');
    _setValue('monitor-email', _authUser?.email || profile.email || '');
  }

  function _renderAuthState() {
    const configured = Boolean(_client);
    const title = document.getElementById('monitor-auth-title');
    const sub = document.getElementById('monitor-auth-sub');
    const email = document.getElementById('monitor-email');
    const signInBtn = document.getElementById('monitor-signin-btn');
    const signOutBtn = document.getElementById('monitor-signout-btn');
    const profileState = document.getElementById('monitor-profile-state');

    if (!configured) {
      if (title) title.textContent = 'Local profile mode';
      if (sub) sub.textContent = 'Add Supabase configuration to enable verified email identity and central log reads.';
      if (email) email.disabled = true;
      if (signInBtn) signInBtn.disabled = true;
      if (signOutBtn) signOutBtn.hidden = true;
      if (profileState) profileState.textContent = 'Self-declared profile';
      _setAuthStatus('Authentication is disabled until Supabase credentials are configured.', 'neutral');
      return;
    }

    if (_authUser) {
      if (title) title.textContent = 'Signed in';
      if (sub) sub.textContent = `Verified as ${_authUser.email}`;
      if (email) email.disabled = true;
      if (signInBtn) signInBtn.hidden = true;
      if (signOutBtn) signOutBtn.hidden = false;
      if (profileState) profileState.textContent = 'Verified profile';
      _setAuthStatus('Verified identity is attached to access sessions and profile updates.', 'success');
    } else {
      if (title) title.textContent = 'Optional sign-in';
      if (sub) sub.textContent = 'Send a magic link to verify name, agency, and email for central monitoring.';
      if (email) email.disabled = false;
      if (signInBtn) {
        signInBtn.hidden = false;
        signInBtn.disabled = false;
      }
      if (signOutBtn) signOutBtn.hidden = true;
      if (profileState) profileState.textContent = 'Self-declared profile';
      _setAuthStatus('Not signed in. Sessions are logged as self-declared until email is verified.', 'neutral');
    }
  }

  function _setAuthStatus(message, tone = 'neutral') {
    const el = document.getElementById('monitor-auth-status');
    if (!el) return;
    el.textContent = message;
    el.classList.remove('success', 'warning', 'error', 'neutral');
    el.classList.add(tone);
  }

  function requestLocation() {
    if (!navigator.geolocation) {
      alert('Browser location is not available on this device.');
      return;
    }
    navigator.geolocation.getCurrentPosition(position => {
      _setProfile({
        geo: {
          latitude: Number(position.coords.latitude.toFixed(6)),
          longitude: Number(position.coords.longitude.toFixed(6)),
          accuracy: Math.round(position.coords.accuracy || 0),
          captured_at: new Date().toISOString(),
        }
      });
      logEvent('location_enabled', { module: 'monitoring' });
      renderAll();
    }, () => {
      logEvent('location_denied', { module: 'monitoring' });
      alert('Location permission was not granted.');
    }, { enableHighAccuracy: false, timeout: 10000, maximumAge: 3600000 });
  }

  function filterDashboard(value) {
    _filter = value || '';
    _renderTable(_cache);
  }

  function exportCsv() {
    const rows = _cache.sessions || [];
    const header = ['last_seen_at','name','email','agency','role','office_location','latitude','longitude','identity_source','device','module_name','session_id','visitor_id','auth_user_id'];
    const csv = [header.join(',')].concat(rows.map(row => header.map(key => _csvCell(row[key])).join(','))).join('\n');
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `apa-cis-access-monitor-${new Date().toISOString().slice(0, 10)}.csv`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    logEvent('export_csv', { module: 'monitoring' });
  }

  function _csvCell(value) {
    return '"' + String(value ?? '').replace(/"/g, '""') + '"';
  }

  function _setText(id, value) {
    const el = document.getElementById(id);
    if (el) el.textContent = value;
  }

  function _setValue(id, value) {
    const el = document.getElementById(id);
    if (el) el.value = value;
  }

  function _formatLocation(session) {
    if (session.latitude && session.longitude) {
      const coords = `${Number(session.latitude).toFixed(4)}, ${Number(session.longitude).toFixed(4)}`;
      return `<span title="Accuracy: ${session.location_accuracy_m || '--'} m">${coords}</span>`;
    }
    return _escapeHtml(session.office_location || 'Not provided');
  }

  function _formatDateTime(value) {
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) return '--';
    return parsed.toLocaleString('en-PH', {
      timeZone: 'Asia/Manila',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  }

  function _moduleLabel(value) {
    const labels = {
      dashboard: 'Climate Dashboard',
      map: 'Map Layers',
      advisory: 'Agri Advisory',
      municipal: 'Municipal Profile',
      planning: 'Planning Dashboard',
      severe: 'Severe Weather',
      monitoring: 'Access Monitor',
    };
    return labels[value] || value || '--';
  }

  function _escapeHtml(str) {
    return String(str || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g, '&quot;');
  }

  return { init, logEvent, renderAll, saveProfile, requestLocation, filterDashboard, exportCsv, signIn, signOut };
})();
window.CISAccessMonitor = CISAccessMonitor;