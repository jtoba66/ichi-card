// Dashboard B — alert delivery: sound, browser notifications, DOM toasts, polling.
// All functions are pure side-effects; no React dependency.

(function () {
  'use strict';

  // ── Deduplication ─────────────────────────────────────────────────────────
  const _seen = new Set();

  function _alertKey(ev) {
    return `${ev.symbol}:${ev.timeframe}:${ev._type}`;
  }

  function _isNew(ev) {
    const k = _alertKey(ev);
    if (_seen.has(k)) return false;
    _seen.add(k);
    return true;
  }

  // ── Notification history ──────────────────────────────────────────────────
  const _history = [];  // newest first, max 200
  let _unreadCount = 0;

  function getHistory()     { return [..._history]; }
  function getUnreadCount() { return _unreadCount; }

  function markAllRead() {
    _history.forEach(e => { e.read = true; });
    _unreadCount = 0;
    window.dispatchEvent(new CustomEvent('ichi:notif-update', { detail: { unreadCount: 0 } }));
  }

  function clearHistory() {
    _history.length = 0;
    _unreadCount = 0;
    window.dispatchEvent(new CustomEvent('ichi:notif-update', { detail: { unreadCount: 0, cleared: true } }));
  }

  // ── Audio (Web Audio API) ─────────────────────────────────────────────────
  let _audioCtx = null;

  function _ensureAudio() {
    if (!_audioCtx) _audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    return _audioCtx;
  }

  function _beep(freq, dur, gain) {
    try {
      const ctx = _ensureAudio();
      const osc = ctx.createOscillator();
      const g   = ctx.createGain();
      osc.connect(g);
      g.connect(ctx.destination);
      osc.frequency.value = freq;
      osc.type = 'sine';
      g.gain.setValueAtTime(gain, ctx.currentTime);
      g.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + dur);
      osc.start(ctx.currentTime);
      osc.stop(ctx.currentTime + dur);
    } catch (e) { /* audio permission denied */ }
  }

  function _soundAlert(priority) {
    if (priority === 'signal') {
      // Three ascending tones — distinct from informational alerts
      _beep(440, 0.18, 0.28);
      setTimeout(() => _beep(660, 0.16, 0.24), 160);
      setTimeout(() => _beep(880, 0.20, 0.30), 320);
    } else if (priority === 'high') {
      _beep(880, 0.18, 0.25);
      setTimeout(() => _beep(1100, 0.14, 0.2), 200);
    } else {
      _beep(660, 0.14, 0.15);
    }
  }

  // ── Browser notifications ─────────────────────────────────────────────────
  let _notifPermission = 'default';

  function _requestNotifPermission() {
    if (!('Notification' in window)) return;
    Notification.requestPermission().then(p => { _notifPermission = p; });
  }

  function _browserNotif(title, body, requireInteraction) {
    if (_notifPermission !== 'granted') return;
    new Notification(title, { body, requireInteraction: !!requireInteraction });
  }

  // ── DOM toasts ────────────────────────────────────────────────────────────
  function _toast(msg, color, dur) {
    const container = document.getElementById('toast-container');
    if (!container) return;
    const el = document.createElement('div');
    el.style.cssText = [
      'pointer-events:auto',
      'padding:10px 16px',
      'border-radius:6px',
      'border:1px solid ' + color + '44',
      'background:#0f0f1aee',
      'color:' + color,
      'font-family:JetBrains Mono,monospace',
      'font-size:11px',
      'line-height:1.5',
      'max-width:320px',
      'box-shadow:0 4px 16px #0008',
      'opacity:0',
      'transition:opacity 0.25s',
    ].join(';');
    el.textContent = msg;
    container.appendChild(el);
    requestAnimationFrame(() => { el.style.opacity = '1'; });
    setTimeout(() => {
      el.style.opacity = '0';
      setTimeout(() => el.remove(), 300);
    }, dur || 6000);
  }

  // ── Signal alert classification ───────────────────────────────────────────
  const SIGNAL_NAMES = {
    1: 'Sanyaku Confirmation', 2: 'Balanced Breakout',
    3: 'KJ Break Retest',     4: 'E2E Entry',
    5: 'Twist Breakout',      6: 'Cloud Curling Confirmed',
    7: 'Four-Level Retest',   9: 'Chikou S/R Retest',
  };

  function classifySignalAlert(sig) {
    const name = SIGNAL_NAMES[sig.signal_type] || `Signal ${sig.signal_type}`;
    const sub  = sig.signal_subtype ? ` (${sig.signal_subtype})` : '';
    const hosoda = sig.hosoda_active ? ' ⚡ HOSODA' : '';
    const sym  = sig.symbol.replace('USDT', '');
    return {
      priority: 'signal',
      label:    `[SIGNAL] ${name}${sub}: ${sym} ${sig.timeframe}${hosoda}`,
      body:     `Entry: ${sig.entry_price} · Score: ${sig.bull_score}/18 · ${sig.cloud_state}`,
      symbol:   sym,
      tf:       sig.timeframe,
      type:     `SIG${sig.signal_type}${sig.signal_subtype || ''}`,
      color:    '#7c3aed',
    };
  }

  function _processSignals(signals) {
    if (!signals || !signals.length) return;
    signals.forEach(sig => {
      const key = `signal:${sig.signal_id}`;
      if (_seen.has(key)) return;
      _seen.add(key);

      const classified = classifySignalAlert(sig);
      const ts = new Date().toISOString();
      const entry = {
        id:       ts + Math.random(),
        ts,
        type:     classified.type,
        priority: 'signal',
        symbol:   classified.symbol + '/USDT',
        tf:       classified.tf,
        summary:  classified.body,
        color:    '#7c3aed',
        read:     false,
        isSignal: true,
        hosoda:   !!sig.hosoda_active,
      };
      _history.unshift(entry);
      if (_history.length > 200) _history.pop();
      _unreadCount++;

      window.dispatchEvent(new CustomEvent('ichi:notif-update', {
        detail: { entry, unreadCount: _unreadCount }
      }));

      _soundAlert('signal');
      _browserNotif(classified.label, classified.body, true);

      // Purple toast, 15s duration
      const container = document.getElementById('toast-container');
      if (container) {
        const el = document.createElement('div');
        el.style.cssText = [
          'pointer-events:auto',
          'padding:10px 16px',
          'border-radius:6px',
          'border:1px solid #7c3aed88',
          'background:#1a0f2eee',
          'color:#c4b5fd',
          'font-family:JetBrains Mono,monospace',
          'font-size:11px',
          'line-height:1.5',
          'max-width:360px',
          'box-shadow:0 4px 20px #7c3aed44',
          'opacity:0',
          'transition:opacity 0.25s',
        ].join(';');
        el.innerHTML = `<span style="color:#7c3aed;font-weight:700">${classified.label}</span><br><span style="color:#a78bfa">${classified.body}</span>`;
        container.appendChild(el);
        requestAnimationFrame(() => { el.style.opacity = '1'; });
        setTimeout(() => {
          el.style.opacity = '0';
          setTimeout(() => el.remove(), 300);
        }, 15000);
      }
    });
  }

  // ── Event summaries ───────────────────────────────────────────────────────
  const COLORS = {
    transition:    '#00ff88',
    retest:        '#4fc3f7',
    kumo_twist:    '#ffaa00',
    e2e:           '#7c3aed',
    cloud_curling: '#39ff14',
  };

  function _evSummary(ev) {
    switch (ev._type) {
      case 'transition':    return `TK cross ${ev.bars_ago}b ago · ${ev.conditions_met}/3 conditions · cloud ${ev.cloud_position}`;
      case 'retest':        return `Retesting ${ev.level} at ${ev.distance_pct.toFixed(2)}% above`;
      case 'kumo_twist':    return `${ev.twist_direction.replace('_',' ')} in ${ev.bars_until_twist} bars`;
      case 'e2e':           return `E2E from below · target +${ev.target_pct.toFixed(1)}% · cloud ${ev.cloud_thickness_pct}% thick`;
      case 'cloud_curling': return `Cloud ${ev.state} · price ${ev.price_position} cloud`;
      default:              return '';
    }
  }

  // ── Dispatch ──────────────────────────────────────────────────────────────
  function _dispatch(ev) {
    if (!_isNew(ev)) return;

    const color    = COLORS[ev._type] || '#e0e0e0';
    const priority = ev._priority || 'normal';
    const summary  = _evSummary(ev);
    const ts       = new Date().toISOString();

    // Store in history
    const entry = {
      id:       ts + Math.random(),
      ts,
      type:     ev._type,
      priority,
      symbol:   ev.symbol,
      tf:       ev.timeframe,
      summary,
      color,
      read:     false,
    };
    _history.unshift(entry);
    if (_history.length > 200) _history.pop();
    _unreadCount++;

    // Notify React components
    window.dispatchEvent(new CustomEvent('ichi:notif-update', {
      detail: { entry, unreadCount: _unreadCount }
    }));

    _soundAlert(priority);
    _browserNotif(`${ev.symbol} · ${ev._type}`, summary, false);
    _toast(`${ev.symbol} ${ev.timeframe}  ${summary}`, color);
  }

  // ── Event filtering and tagging ───────────────────────────────────────────
  function _tagType(list, type, priority) {
    return list.map(ev => ({ ...ev, _type: type, _priority: priority || 'normal' }));
  }

  function _processEvents(data) {
    // Named signals fire first — highest priority
    if (data.new_signals_data && data.new_signals_data.length) {
      _processSignals(data.new_signals_data);
    }

    const all = [
      ..._tagType(data.transition_events  || [], 'transition',    'high'),
      ..._tagType(data.retest_alerts      || [], 'retest',        'normal'),
      ..._tagType(data.kumo_twists        || [], 'kumo_twist',    'normal'),
      ..._tagType(data.e2e_opportunities  || [], 'e2e',           'high'),
      ..._tagType(data.cloud_curling      || [], 'cloud_curling', 'normal'),
    ];
    // Reduce noise: only fire confirmed/full-cluster events
    all.filter(ev => {
      if (ev._type === 'transition' && !ev.full_cluster) return false;
      if (ev._type === 'e2e'        && !ev.confirmed)    return false;
      return true;
    }).forEach(_dispatch);
  }

  // ── Polling loop ──────────────────────────────────────────────────────────
  let _lastSince = null;
  let _pollTimer = null;
  const POLL_MS  = 60 * 1000;

  function _poll() {
    const url = window.API_BASE + '/api/events/poll'
      + (_lastSince ? '?since=' + encodeURIComponent(_lastSince) : '');
    fetch(url)
      .then(r => r.json())
      .then(data => {
        if (data.changed === false) return;
        if (data.scanned_at) _lastSince = data.scanned_at;
        _processEvents(data);
        window.__EVENTS_DATA = data;
        window.dispatchEvent(new CustomEvent('ichi:events', { detail: data }));
      })
      .catch(() => {});
  }

  function startPolling() {
    if (_pollTimer) return;
    _requestNotifPermission();
    _poll();
    _pollTimer = setInterval(_poll, POLL_MS);
  }

  function stopPolling() {
    if (_pollTimer) { clearInterval(_pollTimer); _pollTimer = null; }
  }

  // ── Public API ────────────────────────────────────────────────────────────
  window.IchiAlerts = {
    startPolling,
    stopPolling,
    toast:          _toast,
    getHistory,
    getUnreadCount,
    markAllRead,
    clearHistory,
  };
})();
