// Shared UI primitives for ichi-scorecard.
// All elements assume the dark theme defined in ichi-scorecard.html.

const { useState, useMemo, useRef, useEffect } = React;

// ─── InfoTip — portal-based hover tooltip ────────────────────────────────────
// Usage:  <InfoTip>What this thing does.</InfoTip>
// A singleton <TipLayer /> mounts the bubble at <body> so it never clips
// inside scroll containers or table cells.
function InfoTip({ children, label = 'i', size = 'sm' }) {
  const ref = useRef(null);
  const show = () => {
    const r = ref.current.getBoundingClientRect();
    window.__showTip && window.__showTip({
      x: r.left + r.width / 2,
      y: r.top,
      text: children,
    });
  };
  const hide = () => window.__hideTip && window.__hideTip();
  return (
    <span
      ref={ref}
      className={'info-tip info-tip-' + size}
      onMouseEnter={show}
      onMouseLeave={hide}
      onFocus={show}
      onBlur={hide}
      tabIndex={0}
      role="button"
      aria-label="More info"
    >{label}</span>
  );
}

function TipLayer() {
  const [tip, setTip] = useState(null);
  useEffect(() => {
    window.__showTip = (t) => setTip(t);
    window.__hideTip = () => setTip(null);
    return () => { delete window.__showTip; delete window.__hideTip; };
  }, []);
  if (!tip) return ReactDOM.createPortal(<div></div>, document.body);
  // Place above the trigger, clamped to viewport edges.
  const W = 280;
  const left = Math.max(12, Math.min(window.innerWidth - W - 12, tip.x - W / 2));
  const placeAbove = tip.y > 130;
  const top = placeAbove ? tip.y - 12 : tip.y + 22;
  return ReactDOM.createPortal(
    <div
      className={'tip-bubble ' + (placeAbove ? 'tip-above' : 'tip-below')}
      style={{ left, top, width: W, transform: placeAbove ? 'translateY(-100%)' : 'none' }}
    >
      <div className="tip-bubble-text">{tip.text}</div>
      <div className="tip-bubble-arrow" style={{ left: tip.x - left }}></div>
    </div>,
    document.body
  );
}

// ─── Score bar + number ──────────────────────────────────────────────────────
function scoreColor(score) {
  if (score >= 14) return '#39ff14';
  if (score >= 11) return '#00ff88';
  if (score >= 7)  return '#ffaa00';
  if (score >= 4)  return '#ff8855';
  return '#ff3860';
}

function ScoreBar({ score, max = 18, width = 84 }) {
  const c = scoreColor(score);
  return (
    <div className="score-bar" style={{ width }}>
      <div className="score-bar-track">
        <div className="score-bar-fill" style={{
          width: `${(score / max) * 100}%`,
          background: c,
          boxShadow: `0 0 8px ${c}55`,
        }}></div>
      </div>
      <div className="score-bar-num mono" style={{ color: c }}>
        {score}<span className="dim">/{max}</span>
      </div>
    </div>
  );
}

// Compact, no number; for inline density
function ScorePip({ score, max = 18 }) {
  const c = scoreColor(score);
  const above60 = score / max >= 0.6;
  return (
    <span className="score-pip mono" style={{
      color: above60 ? c : '#666',
      borderColor: above60 ? c + '55' : '#2a2a3a',
      background: above60 ? c + '12' : 'transparent',
    }}>
      <span className="score-pip-dot" style={{ background: above60 ? c : '#555' }}></span>
      {score}/{max}
    </span>
  );
}

// ─── ADX badge ───────────────────────────────────────────────────────────────
function AdxBadge({ adx, plusDI, minusDI, compact = false }) {
  let icon, color, bg, label;
  if (adx >= 40)      { icon = '🔥'; color = '#ff3860'; bg = '#ff386018'; label = 'STRONG'; }
  else if (adx >= 25) { icon = '↗';  color = '#ffaa00'; bg = '#ffaa0018'; label = 'TREND';  }
  else                { icon = '~';  color = '#888';    bg = '#88888812'; label = 'FLAT';   }

  if (compact) {
    return (
      <span className="adx-chip mono" style={{ color, background: bg, borderColor: color + '44' }}>
        <span style={{ marginRight: 4 }}>{icon}</span>{adx.toFixed(1)}
      </span>
    );
  }
  return (
    <span className="adx-chip mono" style={{ color, background: bg, borderColor: color + '44' }} title={`+DI ${plusDI} / -DI ${minusDI}`}>
      <span style={{ marginRight: 4 }}>{icon}</span>
      ADX {adx.toFixed(1)} <span className="dim" style={{ marginLeft: 4 }}>{label}</span>
    </span>
  );
}

// ─── Cloud badge ─────────────────────────────────────────────────────────────
function CloudBadge({ cloud }) {
  const m = {
    ABOVE:   { label: 'Above ☁', color: '#00ff88', bg: '#00ff8814' },
    IN:      { label: 'IN ☁',    color: '#7c3aed', bg: '#7c3aed20' },
    BELOW:   { label: 'Below ☁', color: '#ff3860', bg: '#ff386014' },
    UNKNOWN: { label: '— ☁',     color: '#5f5f72', bg: '#1a1a2e'   },
  }[cloud] || { label: '—', color: '#5f5f72', bg: '#1a1a2e' };
  return (
    <span className="cloud-badge mono" style={{ color: m.color, background: m.bg, borderColor: m.color + '55' }}>
      {m.label}
    </span>
  );
}

function FwdCloud({ fwd }) {
  if (fwd === 'BULL') return <span className="fwd-cloud mono" style={{ color: '#00ff88' }}>FWD ✓</span>;
  if (fwd === 'BEAR') return <span className="fwd-cloud mono" style={{ color: '#ff3860' }}>FWD ✗</span>;
  return <span className="fwd-cloud mono" style={{ color: '#5f5f72' }}>FWD —</span>;
}

// ─── Signal flag chips ───────────────────────────────────────────────────────
function flagStyle(flag) {
  if (flag === 'SQUEEZE')              return { color: '#7c3aed', bg: '#7c3aed20', border: '#7c3aed66' };
  if (flag.startsWith('VOL'))          return { color: '#4fc3f7', bg: '#4fc3f718', border: '#4fc3f755' };
  if (flag === 'RSI-DIV↑')             return { color: '#00ff88', bg: '#00ff8818', border: '#00ff8855' };
  if (flag === 'RSI-DIV↓')             return { color: '#ff3860', bg: '#ff386018', border: '#ff386055' };
  if (flag === 'RS:STRONG↑')           return { color: '#39ff14', bg: '#39ff1418', border: '#39ff1455' };
  if (flag === 'RS:WEAK↓')             return { color: '#ff8855', bg: '#ff885518', border: '#ff885566' };
  return { color: '#888', bg: '#88888812', border: '#444' };
}

function flagTip(flag) {
  if (flag === '⭐ PERFECT')  return 'Every Ichimoku condition fires simultaneously — price above cloud, cloud green, TK above KJ, Chikou clear, steep angle. Rare. When it fires the chart is textbook-clean in every dimension at once.';
  if (flag === 'TRP↑')        return 'Triple sweep: price wicked below a prior swing low and closed back above it at least once in the last 60 bars. Repeated stop-hunting below support that keeps getting rejected — buyers absorbing supply at that level.';
  if (flag === 'SNY↑')        return 'Sanyaku (三役): full three-way Ichimoku alignment just turned on in the last 5 bars — price above cloud, Tenkan above Kijun, Chikou above past price. A fresh trigger, not a stale condition.';
  if (flag === '☁↑')          return 'Cloud curling: the current cloud is still red (bearish) but the future cloud projected 26 bars ahead just flipped green. Structure is rotating before price catches up — an early warning.';
  if (flag === 'TRAP')        return 'Kumo trap: price wicked down through the bottom of the cloud in the last 5 bars and snapped back inside or above it. Bears tried to push through, failed, and are now trapped short.';
  if (flag === 'SQUEEZE')     return 'BB squeeze: Bollinger Band width is near its narrowest point in 125 bars. Volatility is compressed — a large move is statistically due. Doesn\'t tell you direction, just that the calm won\'t last.';
  if (flag.startsWith('VOL')) return `Volume spike: today's up-bar volume is ${flag.replace('VOL ', '')} the 20-bar average. Real buying participation behind the move — not drifting higher on thin air.`;
  if (flag === 'RSI-DIV↑')    return 'Bullish RSI divergence: price made a lower low recently but RSI made a higher low. Momentum is recovering while price was still falling — a sign that selling pressure is exhausting itself.';
  if (flag === 'RSI-DIV↓')    return 'Bearish RSI divergence: price made a higher high but RSI made a lower high. Momentum is weakening behind an apparently strong move — a warning that the rally may be running out of fuel.';
  if (flag === 'RS:STRONG↑')  return 'Relative strength: this coin is outperforming BTC over the last 7–14 days. Capital is rotating into it specifically, not just riding a broad market move.';
  if (flag === 'RS:WEAK↓')    return 'Relative weakness: this coin is lagging BTC over the last 7–14 days. Even when the market runs, it isn\'t keeping up — a sign of distribution or lack of interest.';
  return null;
}

function Flag({ children }) {
  const ref = useRef(null);
  const tip = flagTip(children);
  const s = flagStyle(children);
  const show = () => {
    if (!tip || !ref.current) return;
    const r = ref.current.getBoundingClientRect();
    window.__showTip && window.__showTip({ x: r.left + r.width / 2, y: r.top, text: tip });
  };
  const hide = () => window.__hideTip && window.__hideTip();
  return (
    <span
      ref={ref}
      className="flag-chip mono"
      style={{ color: s.color, background: s.bg, borderColor: s.border, cursor: tip ? 'help' : 'default' }}
      onMouseEnter={show}
      onMouseLeave={hide}
    >
      {children}
    </span>
  );
}

function Flags({ flags }) {
  if (!flags || !flags.length) return <span className="dim mono" style={{ fontSize: 10 }}>—</span>;
  return <span className="flag-row">{flags.map(f => <Flag key={f}>{f}</Flag>)}</span>;
}

// ─── Funding chip ────────────────────────────────────────────────────────────
function FundingChip({ funding }) {
  const pct = (funding * 100).toFixed(3);
  const color = funding < -0.005 ? '#4fc3f7' : funding < 0 ? '#7fcfff' : funding > 0.008 ? '#ffaa00' : '#bbbbcc';
  return <span className="mono" style={{ color }}>{funding >= 0 ? '+' : ''}{pct}%</span>;
}

function fmtOi(oi) {
  if (oi >= 1e9) return '$' + (oi / 1e9).toFixed(2) + 'B';
  if (oi >= 1e6) return '$' + (oi / 1e6).toFixed(1) + 'M';
  return '$' + (oi / 1e3).toFixed(0) + 'K';
}

// ─── Symbol tile ─────────────────────────────────────────────────────────────
function SymTile({ sym, sector }) {
  return (
    <span className="sym-tile">
      <span className="sym-tile-name mono">{sym}</span>
      {sector ? <span className="sym-tile-sector">{sector}</span> : null}
    </span>
  );
}

// ─── Sort header ─────────────────────────────────────────────────────────────
function SortHeader({ id, label, sortKey, sortDir, onSort, align = 'left', tip }) {
  const active = sortKey === id;
  const arrow = !active ? '↕' : sortDir === 'desc' ? '↓' : '↑';
  return (
    <th onClick={() => onSort(id)} style={{ textAlign: align, cursor: 'pointer', userSelect: 'none' }}>
      {label}{tip && <InfoTip>{tip}</InfoTip>} <span className={active ? 'sort-arrow active' : 'sort-arrow'}>{arrow}</span>
    </th>
  );
}

function useSort(initialKey, initialDir = 'desc') {
  const [sortKey, setSortKey] = useState(initialKey);
  const [sortDir, setSortDir] = useState(initialDir);
  const onSort = (k) => {
    if (k === sortKey) setSortDir(d => d === 'desc' ? 'asc' : 'desc');
    else { setSortKey(k); setSortDir('desc'); }
  };
  return { sortKey, sortDir, onSort };
}

// ─── Sparkline — last N daily scores ─────────────────────────────────────────
function Sparkline({ data, width = 56, height = 18, max = 18 }) {
  if (!data || data.length < 2) return null;
  const last = data[data.length - 1];
  const first = data[0];
  const stroke = scoreColor(last);
  const trend = last - first;
  const trendColor = trend > 0 ? '#00ff88' : trend < 0 ? '#ff3860' : '#888';
  const step = width / (data.length - 1);
  const pts = data.map((v, i) => `${(i * step).toFixed(1)},${(height - (v / max) * height).toFixed(1)}`).join(' ');
  return (
    <span className="spark" title={`7d: ${data.join(' → ')}  (Δ ${trend >= 0 ? '+' : ''}${trend})`}>
      <svg width={width} height={height} style={{ display: 'block' }}>
        <polyline points={pts} fill="none" stroke={stroke} strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
        <circle cx={width} cy={height - (last / max) * height} r="1.8" fill={stroke} />
      </svg>
      <span className="spark-delta mono" style={{ color: trendColor }}>
        {trend > 0 ? '▲' : trend < 0 ? '▼' : '·'}{Math.abs(trend) || ''}
      </span>
    </span>
  );
}

// ─── Score breakdown popover (categories of the 18-rule score) ──────────────
function ScoreBadge({ coin, score, tf = '1d' }) {
  const c = scoreColor(score);
  const onClick = (e) => { e.stopPropagation(); window.__openToken && window.__openToken(coin.sym); };
  // Compute per-section pass counts from rulesFor
  const tipNode = React.useMemo(() => {
    if (!coin) return null;
    const rules = window.ICHI_DATA.rulesFor(coin);
    const sections = {};
    for (const r of rules) {
      sections[r.sec] ??= { pass: 0, total: 0 };
      sections[r.sec].total++;
      if (r.passed) sections[r.sec].pass++;
    }
    return (
      <span>
        <b>{coin.sym} · {tf} score breakdown</b><br/>
        {Object.entries(sections).map(([s, v]) =>
          <span key={s} style={{ display: 'inline-block', marginRight: 10 }}>
            {s}: <b>{v.pass}/{v.total}</b>
          </span>
        )}
        <br/><span style={{ color: '#9999b3' }}>Click row for full rule list.</span>
      </span>
    );
  }, [coin, tf]);
  return (
    <span className="score-badge mono" style={{ color: c, borderColor: c + '55', background: c + '14' }} onClick={onClick}>
      <span className="score-badge-num">{score}</span>
      <span className="score-badge-max dim">/18</span>
      <InfoTip>{tipNode}</InfoTip>
    </span>
  );
}

// ─── Watchlist star ──────────────────────────────────────────────────────────
const WATCH_KEY = 'ichi.watchlist.v1';
function loadWatch() {
  try { return new Set(JSON.parse(localStorage.getItem(WATCH_KEY) || '[]')); }
  catch { return new Set(); }
}
function useWatch() {
  const [watch, setWatch] = useState(loadWatch);
  useEffect(() => {
    const sync = () => setWatch(loadWatch());
    window.addEventListener('ichi-watch-changed', sync);
    return () => window.removeEventListener('ichi-watch-changed', sync);
  }, []);
  const toggle = (sym) => {
    const next = new Set(watch);
    if (next.has(sym)) next.delete(sym); else next.add(sym);
    localStorage.setItem(WATCH_KEY, JSON.stringify([...next]));
    setWatch(next);
    window.dispatchEvent(new Event('ichi-watch-changed'));
  };
  return { watch, toggle, has: (s) => watch.has(s) };
}

function WatchStar({ sym, compact = false }) {
  const { has, toggle } = useWatch();
  const on = has(sym);
  return (
    <span
      className={'watch-star' + (on ? ' on' : '') + (compact ? ' compact' : '')}
      onClick={(e) => { e.stopPropagation(); toggle(sym); }}
      title={on ? 'Remove from watchlist' : 'Add to watchlist'}
      role="button"
    >{on ? '★' : '☆'}</span>
  );
}

// ─── Score legend strip ──────────────────────────────────────────────────────
function ScoreLegend() {
  const buckets = [
    { range: '0–3',   label: 'Bearish', color: '#ff3860', tip: 'Most rules failing — the Ichimoku structure is actively bearish. Do not look for longs here. Only relevant if you are looking for short setups.' },
    { range: '4–6',   label: 'Weak',    color: '#ff8855', tip: 'Majority of rules still failing, but some bearish pressure is easing. Could be starting to bottom or could keep falling — no clear direction yet. Watch, do not act.' },
    { range: '7–10',  label: 'Setup',   color: '#ffaa00', tip: 'Roughly half the rules are passing. Structure is neutral — possibly building toward a move. Worth adding to your watchlist, but not a confirmed buy signal yet.' },
    { range: '11–13', label: 'Strong',  color: '#00ff88', tip: 'Bullish structure confirmed across the majority of checks. This is the standard entry zone — enough evidence of trend strength to consider a position.' },
    { range: '14–18', label: 'Extreme', color: '#39ff14', tip: 'Near-perfect Ichimoku alignment. Very high confidence, but these coins have usually already moved — size carefully and be aware you may be entering late.' },
  ];
  return (
    <div className="score-legend">
      <span className="sl-title mono dim">SCORE LEGEND<InfoTip>Every coin gets a 0–18 score from the 18-rule Ichimoku checklist. Colors map to buckets so you can scan a table without reading the numbers.</InfoTip></span>
      <span className="sl-buckets">
        {buckets.map(b => (
          <span key={b.range} className="sl-bucket">
            <span className="sl-swatch" style={{ background: b.color, boxShadow: `0 0 6px ${b.color}66` }}></span>
            <span className="sl-range mono" style={{ color: b.color }}>{b.range}</span>
            <span className="sl-label">{b.label}</span>
            <InfoTip>{b.tip}</InfoTip>
          </span>
        ))}
      </span>
      <span className="sl-hint mono dim">⌘K to search · ★ watchlist</span>
    </div>
  );
}

// ─── Cmd-K command palette ───────────────────────────────────────────────────
function CmdK() {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState('');
  const [idx, setIdx] = useState(0);
  const inputRef = useRef(null);
  const { COINS } = window.ICHI_DATA;

  useEffect(() => {
    const onKey = (e) => {
      const k = (e.key || '').toLowerCase();
      if ((e.metaKey || e.ctrlKey) && k === 'k') { e.preventDefault(); setOpen(o => !o); setQ(''); setIdx(0); }
      else if (e.key === '/' && document.activeElement?.tagName !== 'INPUT') { e.preventDefault(); setOpen(true); setQ(''); setIdx(0); }
      else if (e.key === 'Escape' && open) { setOpen(false); }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open]);

  useEffect(() => { if (open) setTimeout(() => inputRef.current?.focus(), 30); }, [open]);

  const results = useMemo(() => {
    if (!open) return [];
    const qu = q.trim().toLowerCase();
    if (!qu) return COINS.slice(0, 20);
    return COINS
      .map(c => {
        const sym = c.sym.toLowerCase();
        let score = 0;
        if (sym === qu) score = 100;
        else if (sym.startsWith(qu)) score = 60;
        else if (sym.includes(qu)) score = 30;
        else if (c.sector.toLowerCase().includes(qu)) score = 15;
        else return null;
        return { c, score };
      })
      .filter(Boolean)
      .sort((a, b) => b.score - a.score || b.c.score1d - a.c.score1d)
      .slice(0, 24)
      .map(x => x.c);
  }, [q, open]);

  useEffect(() => { setIdx(0); }, [q]);

  const pick = (c) => { setOpen(false); window.__openToken && window.__openToken(c.sym); };
  const onKeyDown = (e) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); setIdx(i => Math.min(results.length - 1, i + 1)); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setIdx(i => Math.max(0, i - 1)); }
    else if (e.key === 'Enter' && results[idx]) { e.preventDefault(); pick(results[idx]); }
  };

  if (!open) return null;
  return ReactDOM.createPortal(
    <div className="cmdk-overlay" onClick={() => setOpen(false)}>
      <div className="cmdk-modal" onClick={e => e.stopPropagation()}>
        <div className="cmdk-input-wrap">
          <span className="cmdk-prompt mono dim">⌘K</span>
          <input
            ref={inputRef}
            className="cmdk-input mono"
            placeholder="Search 200 coins by symbol or sector…"
            value={q}
            onChange={e => setQ(e.target.value)}
            onKeyDown={onKeyDown}
          />
          <span className="cmdk-hint mono dim">{results.length} match{results.length === 1 ? '' : 'es'}</span>
        </div>
        <div className="cmdk-results">
          {results.map((c, i) => (
            <div
              key={c.sym}
              className={'cmdk-row' + (i === idx ? ' active' : '')}
              onMouseEnter={() => setIdx(i)}
              onClick={() => pick(c)}
            >
              <span className="cmdk-sym mono">{c.sym}</span>
              <span className="sector-pill">{c.sector}</span>
              <ScoreBar score={c.score1d} width={84} />
              <CloudBadge cloud={c.cloud} />
              <AdxBadge adx={c.adx} compact />
            </div>
          ))}
          {results.length === 0 && (
            <div className="cmdk-empty mono dim">No matches. Try a symbol like "btc" or a sector like "defi".</div>
          )}
        </div>
        <div className="cmdk-foot mono dim">
          <span>↑↓ navigate</span><span>↵ open</span><span>esc close</span>
        </div>
      </div>
    </div>,
    document.body
  );
}

// ─── Empty state ─────────────────────────────────────────────────────────────
function EmptyState({ title, hint }) {
  return (
    <div className="empty-state">
      <div className="empty-state-icon mono">∅</div>
      <div className="empty-state-title">{title}</div>
      {hint && <div className="empty-state-hint mono dim">{hint}</div>}
    </div>
  );
}

Object.assign(window, {
  ScoreBar, ScorePip, AdxBadge, CloudBadge, FwdCloud,
  Flag, Flags, FundingChip, fmtOi, SymTile,
  SortHeader, useSort, scoreColor,
  InfoTip, TipLayer,
  Sparkline, ScoreBadge, WatchStar, useWatch, ScoreLegend, CmdK, EmptyState,
});
