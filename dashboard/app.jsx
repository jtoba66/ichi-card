// ichi-scorecard — top bar, scanner control grid, bottom stats, app shell.

const { useState: useStateA, useEffect: useEffectA, useRef: useRefA } = React;

function useCountdown() {
  const [secsLeft, setSecsLeft] = useStateA(() => {
    if (!window.__nextRefresh) return null;
    return Math.max(0, Math.round((window.__nextRefresh - Date.now()) / 1000));
  });
  useEffectA(() => {
    const id = setInterval(() => {
      if (!window.__nextRefresh) { setSecsLeft(null); return; }
      setSecsLeft(Math.max(0, Math.round((window.__nextRefresh - Date.now()) / 1000)));
    }, 10000); // update every 10s — no need for per-second granularity
    return () => clearInterval(id);
  }, []);
  return secsLeft;
}

function TopBar({ refreshing, dashView, setDashView, notifCount, onBellClick }) {
  const D = window.ICHI_DATA;
  const secsLeft = useCountdown();
  const scannedAt = D._scannedAt ? new Date(D._scannedAt) : new Date();
  const today = scannedAt;
  const dateStr = today.toLocaleDateString('en-GB', { weekday: 'short', day: '2-digit', month: 'short', year: 'numeric' });
  const timeStr = today.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', hour12: true });

  const nextLabel = refreshing
    ? 'refreshing…'
    : secsLeft != null
      ? `↺ ${Math.ceil(secsLeft / 60)}m`
      : null;

  const stats = [
    { k: 'Scan', v: <><span style={{ color: '#e0e0e0' }}>{D.COINS.length}</span> <span className="dim">coins ·</span> {timeStr} <span className="dim">UTC</span>{nextLabel && <span className="auto-refresh-badge" style={{ opacity: refreshing ? 1 : 0.6 }}>{nextLabel}</span>}</>, tone: '#bbb', tip: <span><b>{D.COINS.length} coins</b> scanned at {timeStr} UTC. Auto-refreshes every 10 minutes. Universe: top-200 USDT-quoted Binance perpetual pairs by 30-day volume.</span> },
    { k: 'Top bull',       v: `${D.topBull.sym} · ${D.topBull.score1d}/18`, tone: '#00ff88', tip: <span>Highest 1-day <b>Ichimoku bull score</b>. Click to open detail.</span>, onClick: () => window.__openToken && window.__openToken(D.topBull.sym) },
    { k: 'Squeeze setups', v: <>{D.squeezeSetups.length} <span className="qs-arrow mono">→</span></>, tone: '#7c3aed', tip: <span>Coins with all three: <b>BB-squeeze active</b>, <b>negative perp funding</b>, <b>bull score ≥ 11/18</b>. <b>Click to see the list.</b></span>, onClick: () => window.__activate && window.__activate('funding', { topN: 100, squeezeOnly: true }) },
  ];

  return (
    <header className="topbar">
      <div className="brand">
        <div className="brand-mark">
          <svg viewBox="0 0 24 24" width="22" height="22">
            <path d="M2 12 L7 12 L9 7 L13 17 L15 12 L22 12" stroke="#7c3aed" strokeWidth="2" fill="none" strokeLinecap="round" strokeLinejoin="round"/>
            <circle cx="9" cy="7" r="1.4" fill="#00ff88"/>
            <circle cx="13" cy="17" r="1.4" fill="#ff3860"/>
          </svg>
        </div>
        <div className="brand-text">
          <div className="brand-name mono">ichi-scorecard</div>
          <div className="brand-tag mono dim">Ichimoku scoring engine · v0.4.1</div>
        </div>
      </div>
      <div className="dash-toggle">
        <button className={'dash-toggle-btn' + (dashView === 'A' ? ' active' : '')} onClick={() => setDashView('A')}>
          A · Scanner
        </button>
        <button className={'dash-toggle-btn' + (dashView === 'B' ? ' active' : '')} onClick={() => setDashView('B')}>
          B · Events
        </button>
        {dashView === 'B' && (
          <span className="dash-b-warning" title="Dashboard B signals are exploratory — not walk-forward validated">
            ⚠ unvalidated
          </span>
        )}
        <button className="notif-bell-btn" onClick={onBellClick} title="Notification centre">
          🔔
          {notifCount > 0 && <span className="notif-bell-badge">{notifCount > 99 ? '99+' : notifCount}</span>}
        </button>
      </div>
      <div className="topbar-date mono dim">{dateStr}</div>
      <div className="quick-stats" style={{ gridTemplateColumns: 'repeat(3, 1fr)' }}>
        {stats.map(s => (
          <div key={s.k} className={'qs-pill' + (s.onClick ? ' clickable' : '')} onClick={s.onClick}>
            <div className="qs-k mono dim">{s.k}<InfoTip>{s.tip}</InfoTip></div>
            <div className="qs-v mono" style={{ color: s.tone }}>{s.v}</div>
          </div>
        ))}
      </div>
    </header>
  );
}

// ─── Scanner control grid ────────────────────────────────────────────────────
const SCANNERS = [
  {
    id: 'daily', name: 'Daily Scan',
    desc: 'Ranks all coins by Ichimoku bull score',
    accent: '#00ff88',
    defaults: { timeframe: '1d', minScore: 13, regime: 'ALL' },
    tip: <span>Computes the <b>18-point bull score</b> for every coin on the chosen timeframe and returns a ranked table. The bread-and-butter scan — run it first thing in the morning to see what is structurally strong.</span>,
  },
  {
    id: 'mtf', name: 'Multi-TF Scan',
    desc: 'Scores each coin across 3 timeframes',
    accent: '#4fc3f7',
    defaults: {},
    tip: <span>Scores each coin on <b>4h, 1d, and 1w</b> simultaneously. Rows where all three are ≥ 11/18 ("fully aligned") are highlighted — these are the highest-conviction setups across horizons.</span>,
  },
  {
    id: 'coil', name: 'Coiled Spring',
    desc: 'Finds laggards primed to move',
    accent: '#7c3aed',
    defaults: { weeklyMin: 12, dailyMax: 7 },
    tip: <span>Hunts for coins that are <b>structurally bullish on weekly</b> but <b>compressed on daily</b> — i.e. setting up rather than already running. Cards with an <b>IN ☁</b> badge are at maximum compression (price inside the cloud).</span>,
  },
  {
    id: 'sector', name: 'Sector Rotation',
    desc: 'Groups coins by sector strength',
    accent: '#ffaa00',
    defaults: { timeframe: '1d' },
    tip: <span>Aggregates scores by category (L1, L2, DeFi, AI, Meme…) so you can see <b>which sector capital is rotating into</b>. The right panel drills into the top 3 sectors with their best coins.</span>,
  },
  {
    id: 'funding', name: 'Funding + OI',
    desc: 'Perp funding rates, squeeze setups',
    accent: '#39ff14',
    defaults: { topN: 30, squeezeOnly: false },
    tip: <span>Joins bull score with <b>perpetual funding rate</b> and <b>open interest</b>. Highlights three patterns: 🔥 squeeze setups (bull + neg funding + BB squeeze), ⚡ negative funding crowds, ⚠️ overleveraged longs.</span>,
  },
  {
    id: 'alerts', name: 'Alerts',
    desc: 'Threshold crossing tracker',
    accent: '#ff3860',
    defaults: { minScore: 13 },
    tip: <span>Diffs the current scan against the previous one and surfaces <b>threshold crossings</b>. NEW = just crossed above your min score (entry candidates). DROPPED = fell below (exit / weakness warning).</span>,
  },
];

function ScannerCard({ s, opts, setOpts, isActive, isRunning, onRun, onActivate, lastRun }) {
  return (
    <div
      className={'scanner-card' + (isActive ? ' active' : '')}
      style={{ '--accent': s.accent }}
      onClick={(e) => {
        // any non-control click activates the panel
        const t = e.target;
        if (t.closest('button, .opt-chip, .opt-menu, .opt-toggle, .info-tip, .tip-bubble')) return;
        onActivate && onActivate();
      }}
      title={isActive ? '' : 'Click to view results'}
    >
      <div className="sc-head">
        <div className="sc-title-row">
          <div className="sc-name">{s.name}<InfoTip size="md">{s.tip}</InfoTip></div>
          {isActive && <span className="sc-active-dot mono" style={{ color: s.accent }}>● ACTIVE</span>}
        </div>
        <div className="sc-desc">{s.desc}</div>
      </div>
      <div className="sc-options">
        <OptionsControls scannerId={s.id} opts={opts} setOpts={setOpts} />
      </div>
      <div className="sc-foot">
        <div className="sc-last mono dim">
          {lastRun ? `last: ${lastRun}` : 'never run'}
        </div>
        <button
          className={'run-btn' + (isRunning ? ' running' : '')}
          onClick={onRun}
          disabled={isRunning}
          style={{ '--accent': s.accent }}
        >
          {isRunning ? <><span className="spinner"></span> Running…</> : <>▶ Run</>}
        </button>
      </div>
    </div>
  );
}

function OptionsControls({ scannerId, opts, setOpts }) {
  if (scannerId === 'daily') {
    return (
      <>
        <OptChip label="TF" value={opts.timeframe || '1d'}
          options={['4h','1d','1w']}
          descOf={v => ({ '4h': 'Intraday swing', '1d': 'Daily trend', '1w': 'Weekly structure' }[v])}
          onChange={v => setOpts({ ...opts, timeframe: v })} />
        <OptChip label="Min score" value={opts.minScore ?? 13}
          options={[7,9,11,13,15]}
          descOf={v => ({ 7: 'Early / watchlist', 9: 'Developing setup', 11: 'Approaching signal', 13: 'Validated threshold', 15: 'Elite alignment' }[v])}
          onChange={v => setOpts({ ...opts, minScore: v })} />
        <OptChip label="Regime" value={opts.regime || 'ALL'}
          options={['ALL','TRENDING','STRONG']}
          descOf={v => ({ ALL: 'No ADX filter', TRENDING: 'ADX ≥ 25 — trending', STRONG: 'ADX ≥ 40 — strong trend' }[v])}
          onChange={v => setOpts({ ...opts, regime: v })} />
        <InfoTip>Filters by ADX (trend strength). <b>ALL</b> = no filter. <b>TRENDING</b> = ADX ≥ 25 — the market is moving directionally, not choppy. <b>STRONG</b> = ADX ≥ 40 — a powerful sustained trend. Fewer results but higher-quality momentum setups.</InfoTip>
        <button className={'opt-toggle' + (opts.watchOnly ? ' on' : '')} onClick={(e) => { e.stopPropagation(); setOpts({ ...opts, watchOnly: !opts.watchOnly }); }}>
          {opts.watchOnly ? '★ Watch' : '☆ Watch'}
        </button>
      </>
    );
  }
  if (scannerId === 'mtf') {
    return (
      <>
        <span className="opt-chip static">4h</span>
        <span className="opt-chip static">1d</span>
        <span className="opt-chip static">1w</span>
        <OptChip label="Align" value={opts.minAligned ?? 0}
          options={[0, 1, 2, 3]}
          displayOf={v => v === 0 ? 'Any' : v === 3 ? 'All 3' : `${v}+`}
          descOf={v => ({ 0: 'Show all coins', 1: '1+ TF bullish', 2: '2+ TFs bullish', 3: 'All 3 TFs bullish' }[v])}
          onChange={v => setOpts({ ...opts, minAligned: v })} />
        <button className={'opt-toggle' + (opts.watchOnly ? ' on' : '')} onClick={(e) => { e.stopPropagation(); setOpts({ ...opts, watchOnly: !opts.watchOnly }); }}>
          {opts.watchOnly ? '★ Watch' : '☆ Watch'}
        </button>
      </>
    );
  }
  if (scannerId === 'coil') {
    return (
      <>
        <OptChip label="Weekly ≥" value={opts.weeklyMin ?? 12}
          options={[10,11,12,13,14]}
          descOf={v => `Weekly score must be ≥ ${v} — strong higher-TF structure`}
          onChange={v => setOpts({ ...opts, weeklyMin: v })} />
        <OptChip label="Daily ≤" value={opts.dailyMax ?? 7}
          options={[5,6,7,8,9]}
          descOf={v => `Daily score must be ≤ ${v} — price hasn't moved yet`}
          onChange={v => setOpts({ ...opts, dailyMax: v })} />
      </>
    );
  }
  if (scannerId === 'sector') {
    return <OptChip label="TF" value={opts.timeframe || '1d'} options={['4h','1d','1w']}
      descOf={v => ({ '4h': 'Intraday swing', '1d': 'Daily trend', '1w': 'Weekly structure' }[v])}
      onChange={v => setOpts({ ...opts, timeframe: v })} />;
  }
  if (scannerId === 'funding') {
    return (
      <>
        <OptChip label="Show" value={opts.topN ?? 30} options={[15,30,50,100]}
          descOf={v => `Show top ${v} coins by bull score`}
          onChange={v => setOpts({ ...opts, topN: v })} />
        <OptChip label="Min score" value={opts.minScore ?? 0}
          options={[0, 8, 11, 13]}
          descOf={v => ({ 0: 'All coins', 8: 'Emerging setup', 11: 'Strong bull signal', 13: 'Very strong' }[v])}
          onChange={v => setOpts({ ...opts, minScore: v })} />
        <button className={'opt-toggle' + (opts.squeezeOnly ? ' on' : '')} onClick={(e) => { e.stopPropagation(); setOpts({ ...opts, squeezeOnly: !opts.squeezeOnly }); }}>
          {opts.squeezeOnly ? '✓ Squeeze only' : 'Squeeze only'}
        </button>
        <button className={'opt-toggle' + (opts.watchOnly ? ' on' : '')} onClick={(e) => { e.stopPropagation(); setOpts({ ...opts, watchOnly: !opts.watchOnly }); }}>
          {opts.watchOnly ? '★ Watch' : '☆ Watch'}
        </button>
      </>
    );
  }
  if (scannerId === 'alerts') {
    return <OptChip label="Min score" value={opts.minScore ?? 13} options={[9,11,13,15]}
      descOf={v => ({ 9: 'Developing setup', 11: 'Approaching signal', 13: 'Validated threshold', 15: 'Elite alignment' }[v])}
      onChange={v => setOpts({ ...opts, minScore: v })} />;
  }
  return null;
}

function OptChip({ label, value, options, onChange, displayOf, descOf }) {
  const [open, setOpen] = useStateA(false);
  const ref = useRefA(null);
  useEffectA(() => {
    if (!open) return;
    function handleOutside(e) {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false);
    }
    document.addEventListener('mousedown', handleOutside);
    return () => document.removeEventListener('mousedown', handleOutside);
  }, [open]);
  const disp = displayOf ? displayOf(value) : value;
  return (
    <span ref={ref} className="opt-chip" onClick={() => setOpen(o => !o)}>
      <span className="opt-k mono dim">{label}</span>
      <span className="opt-v mono">{disp}</span>
      <span className="opt-caret">{open ? '▴' : '▾'}</span>
      {open && (
        <span className="opt-menu" onClick={e => e.stopPropagation()}>
          {options.map((o) => (
            <span key={o} className={'opt-menu-item mono' + (o === value ? ' selected' : '')}
              onClick={() => { onChange(o); setOpen(false); }}>
              <span className="opt-menu-check">{o === value ? '✓' : ' '}</span>
              <span className="opt-menu-content">
                <span className="opt-menu-val">{displayOf ? displayOf(o) : o}</span>
                {descOf && <span className="opt-menu-desc dim">{descOf(o)}</span>}
              </span>
            </span>
          ))}
        </span>
      )}
    </span>
  );
}

// ─── Dashboard B TF selector ─────────────────────────────────────────────────
function DashBTFSelector({ value, onChange }) {
  const tfs = ['4h', '1d', '1w', 'ALL'];
  return (
    <div className="dashb-tf-selector">
      <span className="mono dim" style={{ fontSize: 11 }}>Timeframe:</span>
      {tfs.map(tf => (
        <button key={tf}
          className={'dashb-tf-btn mono' + (value === tf ? ' active' : '')}
          onClick={() => onChange(tf)}>
          {tf}
        </button>
      ))}
    </div>
  );
}

// ─── Bottom stats bar ────────────────────────────────────────────────────────
function BottomStats() {
  const D = window.ICHI_DATA;
  const mostCoiled = D.coiled[0];
  const bestSqueeze = D.squeezeSetups.sort((a, b) => a.funding - b.funding)[0];
  const leadSector = D.sectorStats[0];

  const items = [
    {
      label: 'Top Bull',
      sym: D.topBull.sym,
      sector: D.topBull.sector,
      v: `${D.topBull.score1d}/18`,
      sub: `ADX ${D.topBull.adx.toFixed(1)} · ${D.topBull.cloud === 'ABOVE' ? 'Above ☁' : D.topBull.cloud === 'IN' ? 'IN ☁' : 'Below ☁'}`,
      tone: '#00ff88',
      tip: <span>The coin with the <b>highest 1-day bull score</b>. <b>Click to open detail.</b></span>,
      onClick: () => window.__openToken && window.__openToken(D.topBull.sym),
    },
    {
      label: 'Top Bear',
      sym: D.topBear.sym,
      sector: D.topBear.sector,
      v: `${D.topBear.bearScore}/18`,
      sub: `ADX ${D.topBear.adx.toFixed(1)} · ${D.topBear.fwdCloud === 'BEAR' ? 'Fwd ☁ Bear' : 'Fwd ☁ Bull'}`,
      tone: '#ff3860',
      tip: <span>The coin with the <b>highest bear score</b> — most Ichimoku rules in a bearish state right now. <b>Click to open detail.</b></span>,
      onClick: () => window.__openToken && window.__openToken(D.topBear.sym),
    },
    {
      label: 'Most Coiled',
      sym: mostCoiled?.sym ?? '—',
      sector: mostCoiled?.sector,
      v: mostCoiled ? `${mostCoiled.coil.toFixed(1)}` : '—',
      sub: mostCoiled ? `1w ${mostCoiled.score1w} · 1d ${mostCoiled.score1d}` : '',
      tone: '#7c3aed',
      tip: <span>Highest <b>coil score</b> across the universe. <b>Click to open Coiled Spring.</b></span>,
      onClick: () => window.__activate && window.__activate('coil'),
    },
    {
      label: 'Best Squeeze',
      sym: bestSqueeze?.sym ?? '—',
      sector: bestSqueeze?.sector,
      v: bestSqueeze ? `${(bestSqueeze.funding * 100).toFixed(3)}%` : '—',
      sub: bestSqueeze ? `score ${bestSqueeze.score1d}/18 · OI ${(bestSqueeze.oi/1e6).toFixed(0)}M` : '',
      tone: '#39ff14',
      tip: <span>Most-negative funding among bull squeeze candidates. <b>Click to see all squeeze setups.</b></span>,
      onClick: () => window.__activate && window.__activate('funding', { topN: 100, squeezeOnly: true }),
    },
    {
      label: 'Leading Sector',
      sym: leadSector.sector,
      sector: `${leadSector.members} coins`,
      v: `${leadSector.avgBull.toFixed(1)}/18`,
      sub: `${leadSector.pctAbove11}% ≥11 · ADX ${leadSector.avgAdx.toFixed(1)}`,
      tone: '#4fc3f7',
      tip: <span>Sector with the <b>highest average 1-day bull score</b>. <b>Click to open Sector Rotation.</b></span>,
      onClick: () => window.__activate && window.__activate('sector'),
    },
  ];

  return (
    <footer className="bottom-stats">
      {items.map(it => (
        <div key={it.label} className={'bs-cell' + (it.onClick ? ' clickable' : '')} style={{ '--accent': it.tone }} onClick={it.onClick}>
          <div className="bs-label mono dim">{it.label}<InfoTip>{it.tip}</InfoTip></div>
          <div className="bs-main">
            <span className="bs-sym mono">{it.sym}</span>
            {it.sector && <span className="bs-sector mono dim">· {it.sector}</span>}
          </div>
          <div className="bs-v mono" style={{ color: it.tone }}>{it.v}</div>
          <div className="bs-sub mono dim">{it.sub}</div>
        </div>
      ))}
    </footer>
  );
}

// ─── App ─────────────────────────────────────────────────────────────────────
const AUTO_REFRESH_MS = 10 * 60 * 1000; // 10 minutes

function App() {
  const [scannerOpts, setScannerOpts] = useStateA(() => {
    const o = {};
    for (const s of SCANNERS) o[s.id] = { ...s.defaults };
    return o;
  });
  const [running, setRunning]   = useStateA(null);
  const [lastRun, setLastRun]   = useStateA({});
  const [active, setActive]     = useStateA({ kind: 'daily', opts: { ...SCANNERS[0].defaults } });
  const [, forceUpdate]         = useStateA(0);
  const [refreshing, setRefreshing] = useStateA(false);
  const [notifOpen,  setNotifOpen]  = useStateA(false);
  const [notifCount, setNotifCount] = useStateA(() => window.IchiAlerts?.getUnreadCount() || 0);

  useEffectA(() => {
    const handler = (e) => setNotifCount(e.detail?.unreadCount ?? 0);
    window.addEventListener('ichi:notif-update', handler);
    return () => window.removeEventListener('ichi:notif-update', handler);
  }, []);

  const handleBellClick = () => {
    setNotifOpen(o => !o);
    if (!notifOpen) window.IchiAlerts?.markAllRead();
  };

  const [dashView, _setDashView] = useStateA(
    () => localStorage.getItem('ichi_dashboard_mode') || 'A'
  );
  const setDashView = (v) => { _setDashView(v); localStorage.setItem('ichi_dashboard_mode', v); };
  const [bTF, _setBTF] = useStateA(
    () => localStorage.getItem('ichi_dash_b_tf') || '1d'
  );
  const setBTF = (v) => { _setBTF(v); localStorage.setItem('ichi_dash_b_tf', v); };

  // Start Dashboard B alert polling once app mounts
  useEffectA(() => {
    if (window.IchiAlerts) window.IchiAlerts.startPolling();
    return () => { if (window.IchiAlerts) window.IchiAlerts.stopPolling(); };
  }, []);

  // Auto-refresh every 10 minutes
  useEffectA(() => {
    // Store next-fire time globally so TopBar can read it
    window.__nextRefresh = Date.now() + AUTO_REFRESH_MS;
    const timer = setInterval(() => {
      setRefreshing(true);
      window.__nextRefresh = Date.now() + AUTO_REFRESH_MS;
      window.refreshData()
        .then(() => window.loadData())
        .then(() => {
          const ts = window.ICHI_DATA?._scannedAt
            ? new Date(window.ICHI_DATA._scannedAt).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false })
            : '—';
          setLastRun({ daily: ts, mtf: ts, coil: ts, sector: ts, funding: ts, alerts: ts });
          forceUpdate(n => n + 1);
        })
        .catch(() => {}) // silent fail — backend may be mid-scan
        .finally(() => setRefreshing(false));
    }, AUTO_REFRESH_MS);
    return () => { clearInterval(timer); delete window.__nextRefresh; };
  }, []);

  useEffectA(() => {
    window.__activate = (id, opts) => {
      const s = SCANNERS.find(x => x.id === id);
      if (!s) return;
      const merged = { ...s.defaults, ...scannerOpts[id], ...(opts || {}) };
      setScannerOpts(prev => ({ ...prev, [id]: merged }));
      setActive({ kind: id, opts: merged });
      document.querySelector('.results-area')?.scrollIntoView?.({ behavior: 'smooth', block: 'nearest' });
    };
    return () => { delete window.__activate; };
  }, [scannerOpts]);

  function runScanner(s) {
    if (running) return;
    setRunning(s.id);
    setTimeout(() => {
      const ts = new Date().toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });
      setLastRun(prev => ({ ...prev, [s.id]: ts }));
      setRunning(null);
      setActive({ kind: s.id, opts: { ...scannerOpts[s.id] } });
    }, 750 + Math.random() * 400);
  }

    // Seed lastRun with scan time once data is available
  useEffectA(() => {
    const ts = window.ICHI_DATA?._scannedAt
      ? new Date(window.ICHI_DATA._scannedAt).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false })
      : '—';
    setLastRun({ daily: ts, mtf: ts, coil: ts, sector: ts, funding: ts, alerts: ts });
  }, []);

  return (
    <div className="app">
      <TipLayer />
      <TokenDetailHost />
      <CmdK />
      <div id="toast-container" />
      {typeof NotifCenter !== 'undefined' && (
        <NotifCenter open={notifOpen} onClose={() => setNotifOpen(false)} />
      )}
      <TopBar refreshing={refreshing} dashView={dashView} setDashView={setDashView}
        notifCount={notifCount} onBellClick={handleBellClick} />

      {dashView === 'A' && (
        <>
          <ScoreLegend />
          <WatchlistStrip onOpen={(s) => window.__openToken(s)} />
          <section className={'scanner-grid' + (active ? ' has-active' : '')}>
            {SCANNERS.map(s => (
              <ScannerCard
                key={s.id} s={s}
                opts={scannerOpts[s.id]}
                setOpts={(o) => setScannerOpts(prev => ({ ...prev, [s.id]: o }))}
                isActive={active.kind === s.id}
                isRunning={running === s.id}
                onRun={() => runScanner(s)}
                onActivate={() => setActive({ kind: s.id, opts: { ...scannerOpts[s.id] } })}
                lastRun={lastRun[s.id]}
              />
            ))}
          </section>
          <main className="results-area">
            <ResultsArea active={active} />
          </main>
          <BottomStats />
        </>
      )}

      {dashView === 'B' && (
        <main className="dash-b-area">
          <div className="dash-b-toolbar">
            <DashBTFSelector value={bTF} onChange={setBTF} />
          </div>
          {typeof DashboardB !== 'undefined'
            ? <DashboardB tf={bTF} />
            : <div className="dash-b-placeholder mono dim">Dashboard B panels loading…</div>
          }
        </main>
      )}
    </div>
  );
}

function WatchlistStrip({ onOpen }) {
  const { watch, toggle } = useWatch();
  const { COINS } = window.ICHI_DATA;
  const items = [...watch]
    .map(s => COINS.find(c => c.sym === s))
    .filter(Boolean)
    .sort((a, b) => b.score1d - a.score1d);
  if (items.length === 0) return (
    <div className="watch-strip empty">
      <span className="ws-title mono dim">★ WATCHLIST</span>
      <span className="ws-empty mono dim">Click ☆ on any row to pin a coin here. Survives reload.</span>
    </div>
  );
  return (
    <div className="watch-strip">
      <span className="ws-title mono dim">★ WATCHLIST <span className="ws-count mono">{items.length}</span></span>
      <div className="ws-scroll">
        {items.map(c => (
          <div key={c.sym} className="ws-chip" onClick={() => onOpen(c.sym)}>
            <span className="ws-chip-sym mono">{c.sym}</span>
            <span className="mono" style={{ color: scoreColor(c.score1d), fontWeight: 600 }}>{c.score1d}</span>
            <Sparkline data={c.scoreHist} width={36} height={14} />
            <span className="ws-chip-x mono dim" onClick={(e) => { e.stopPropagation(); toggle(c.sym); }} title="Remove">×</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── App loader — handles API polling before rendering the full UI ────────────
function AppLoader() {
  const [phase, setPhase] = useStateA('loading'); // loading | ready | error
  const [msg, setMsg]     = useStateA('Connecting to scan server…');
  const [errText, setErr] = useStateA('');

  useEffectA(() => {
    let alive = true;
    setMsg('Connecting to scan server…');

    window.loadData()
      .then(() => {
        if (!alive) return;
        setPhase('ready');
      })
      .catch(err => {
        if (!alive) return;
        setPhase('error');
        setErr(err.message || String(err));
      });

    // Poll for status messages
    const id = setInterval(() => {
      fetch(window.API_BASE + '/api/data')
        .then(r => r.json())
        .then(resp => {
          if (!alive) return;
          if (resp.status === 'scanning') setMsg('Scanning markets… this takes 2–4 minutes on first run.');
          else if (resp.status === 'idle')    setMsg('Server idle. Starting scan…');
        })
        .catch(() => setMsg('Waiting for API server on :8000…'));
    }, 4000);

    return () => { alive = false; clearInterval(id); };
  }, []);

  if (phase === 'ready') return <App />;

  if (phase === 'error') return (
    <div style={{ display: 'grid', placeItems: 'center', minHeight: '100vh', gap: 14 }}>
      <div style={{ textAlign: 'center', maxWidth: 480 }}>
        <div style={{ fontSize: 32, marginBottom: 12, color: 'var(--bear)' }}>✕</div>
        <div style={{ fontFamily: 'Space Grotesk, sans-serif', fontSize: 16, color: 'var(--text)', marginBottom: 8 }}>API unavailable</div>
        <div style={{ fontSize: 12, color: 'var(--dim)', marginBottom: 18, lineHeight: 1.6 }}>{errText}</div>
        <div style={{ fontSize: 11, color: 'var(--dim)', background: '#11111e', border: '1px solid var(--line2)', borderRadius: 6, padding: '10px 14px', textAlign: 'left', fontFamily: 'JetBrains Mono, monospace', marginBottom: 18 }}>
          Start the API:<br />
          cd ichi-scorecard<br />
          uv run uvicorn ichi.api.main:app --port 8000
        </div>
        <button className="run-btn" style={{ '--accent': 'var(--bear)' }} onClick={() => { setPhase('loading'); setErr(''); setMsg('Reconnecting…'); }}>
          ↺ Retry
        </button>
      </div>
    </div>
  );

  return (
    <div style={{ display: 'grid', placeItems: 'center', minHeight: '100vh' }}>
      <div style={{ textAlign: 'center', maxWidth: 400 }}>
        <div style={{ width: 40, height: 40, border: '3px solid var(--accent)', borderRightColor: 'transparent', borderRadius: '50%', animation: 'spin 0.8s linear infinite', margin: '0 auto 18px' }}></div>
        <div style={{ fontFamily: 'Space Grotesk, sans-serif', fontSize: 15, color: 'var(--text)', marginBottom: 6 }}>Loading scan data</div>
        <div style={{ fontSize: 11, color: 'var(--dim)' }}>{msg}</div>
      </div>
    </div>
  );
}

ReactDOM.createRoot(document.getElementById('root')).render(<AppLoader />);
