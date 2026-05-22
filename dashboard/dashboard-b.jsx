// Dashboard B — Reversal & Event Detection
// Layout mirrors Dashboard A: card grid → click → results below.
// MTF Event View always visible at bottom (like Dashboard A's bottom stats bar).

const { useState: useSt, useEffect: useEff, useRef: useRef_B } = React;

// ── Abbreviation tooltip dictionary ──────────────────────────────────────────
const TIPS = {
  // Ichimoku lines
  TK:           'Tenkan-sen — 9-period midpoint. The "fast" line. Shows short-term momentum.',
  KJ:           'Kijun-sen — 26-period midpoint. The equilibrium line. Price tends to revert to it.',
  CS:           'Chikou Span — current close plotted 26 bars back. When it is above/inside the cloud, past price action confirms the move.',
  CLOUD:        'Kumo cloud — the area between Senkou Span A and B. Support/resistance zone. Thick = strong, thin = weak.',

  // CondBadge: separate tips for MET vs NOT MET
  COND_TK_ON:    'TK cross ✓ — Tenkan-sen crossed above Kijun-sen recently (within 10 bars). Fresh momentum signal — the fast line just overtook the slow line.',
  COND_TK_OFF:   'TK cross ✗ — No recent Tenkan/Kijun crossover detected. This coin has not had a fresh bullish cross yet.',
  COND_CS_ON:    'Chikou Span ✓ — The lagging line (close shifted 26 bars back) is inside or above the cloud. This means price 26 bars ago already pushed through the cloud level — historical support confirmed.',
  COND_CS_OFF:   'Chikou Span ✗ (grey) — The lagging line is still below the cloud. The move has not yet cleared its own historical resistance. Full trend confirmation is missing.',
  COND_CLOUD_ON: 'Cloud condition ✓ — The forward cloud is either curling upward (Span A slope turning positive while still bearish) or just twisted bullish. The future cloud structure is turning in favour of bulls.',
  COND_CLOUD_OFF:'Cloud condition ✗ — The forward cloud is still bearish and flat. No structural turn in the cloud yet.',
  SPAN_A:       'Senkou Span A — midpoint of (TK + KJ) plotted 26 bars forward. The faster cloud edge.',
  SPAN_B:       'Senkou Span B — 52-period midpoint plotted 26 bars forward. The slower cloud edge.',
  // Retest labels
  'RT-TK':      'Retest of Tenkan-sen — price pulling back to touch the fast line from above.',
  'RT-KJ':      'Retest of Kijun-sen — price pulling back to touch the equilibrium line. Deeper pullback.',
  'RT-CT':      'Retest of Cloud Top — price testing the top edge of the Kumo. Deep pullback; most significant support.',
  'RT-CB':      'Retest of Cloud Bottom — price testing the cloud\'s bottom edge. Last line of defence. A close below invalidates the bull setup.',
  // Event badges
  E2E:          'Edge-to-Edge — price has entered the Kumo cloud. It often travels to the opposite edge.',
  CURL:         'Cloud Curling — leading cloud\'s Span A slope is turning upward while the cloud is still bearish. Earliest warning before a twist.',
  TWIST:        'Kumo Twist — Span A and Span B are about to cross, changing cloud polarity. Time pivot.',
  BAL:          'Balanced zone — price is within ±5% of the Kijun. Equilibrium; cleanest launch point for a directional move.',
  // States
  JUST_TWISTED: 'Cloud just twisted — Span A crossed above Span B this bar or last bar. Freshest signal.',
  IMMINENT:     'Twist imminent — cloud flip expected within 5 bars.',
  EARLY:        'Early warning — Span A slope turning up, but twist is more than 5 bars away.',
  BULL_TWIST:   'Bull Twist — cloud flipping from bearish (Span B > Span A) to bullish (Span A > Span B).',
  BEAR_TWIST:   'Bear Twist — cloud flipping from bullish to bearish. Watch for distribution.',
  FROM_BELOW:   'Entry from below — price entered the cloud from below. Bullish E2E setup; target is the cloud top.',
  FROM_ABOVE:   'Entry from above — price entered the cloud from above. Bearish E2E setup; target is the cloud bottom.',
  CONFIRMED:    'Confirmed E2E — bull score ≥ 10, future cloud is bullish, and entry was this bar.',
  CRITICAL:     'Critical support — a close below cloud bottom invalidates the entire bull setup for this coin.',
  // Balance zones
  EXTENDED:     'Extended zone — price is more than +15% above the Kijun. Statistically overextended; reversion likely.',
  ABOVE_ZONE:   'Above zone — price is +5% to +15% above Kijun. Trending but not overextended.',
  BALANCED:     'Balanced zone — price is within ±5% of Kijun. Equilibrium; high-quality entry zone.',
  BELOW_ZONE:   'Below zone — price is more than 5% below Kijun. Weakening or bearish.',
  // Groups
  GROUP_A:      'Group A — confirmed uptrend: bull score ≥ 13 AND price above the cloud.',
  GROUP_B:      'Group B — post-breakout: price broke above cloud within the last 10 bars.',
  // Column headers
  COL_BARS_AGO:     'Number of bars since this event fired. Lower = fresher.',
  COL_CONDITIONS:   'Which of the 3 reversal conditions are met: TK cross, Chikou position, Cloud curl.',
  COL_VOL:          'Volume ratio — current bar volume vs 20-bar rolling average. > 1x = above-average participation.',
  COL_DISTANCE:     'How far price is above the level, as a percentage. Closer = more immediate retest.',
  COL_SLOPE:        'Direction the line is moving: RISING, FLAT, or FALLING.',
  COL_KJ_DIST:      'Distance between price and the Kijun-sen as a percentage. Positive = above KJ.',
  COL_TK_DIST:      'Distance between price and the Tenkan-sen as a percentage.',
  COL_TWIST_IN:     'How many bars until Span A and Span B cross.',
  COL_SPANA_SLOPE:  '% change in Senkou Span A over the last 5 bars. Positive = cloud accelerating upward.',
  COL_THICK:        'Cloud thickness as % of price. Thicker cloud = stronger support/resistance.',
  COL_PRICE_POS:    'Where current price sits relative to the cloud: ABOVE, IN, or BELOW.',
  COL_TARGET_PCT:   'Percentage gain from entry to the opposite cloud edge (E2E target).',
  COL_BARS_AGO_E2E: 'How many bars ago price entered the cloud. 0 = just entered this bar.',
  COL_SCORE:        'Ichimoku bull score out of 18. How many of the 18 rules are currently bullish.',
  COL_BOUNCE:       'Whether the TK Bounce rule is confirmed in the 18-rule scorecard for this coin.',
  COL_ALIGNED:      'How many timeframes (4h / 1d) have at least one active event.',
};

// Lightweight hover tooltip for abbreviations — reuses the portal TipLayer
function AbbTip({ children, id, style }) {
  const ref = useRef_B(null);
  const tip = TIPS[id] || id;
  return (
    <span
      ref={ref}
      style={{ borderBottom: '1px dotted #555', cursor: 'help', ...style }}
      onMouseEnter={() => {
        if (!ref.current || !window.__showTip) return;
        const r = ref.current.getBoundingClientRect();
        window.__showTip({ x: r.left + r.width / 2, y: r.top, text: tip });
      }}
      onMouseLeave={() => window.__hideTip?.()}
    >{children}</span>
  );
}

// ── Data hook ────────────────────────────────────────────────────────────────

function useEvents() {
  const [data, setData] = useSt(window.__EVENTS_DATA || null);
  useEff(() => {
    if (!data) {
      fetch(window.API_BASE + '/api/events')
        .then(r => r.json())
        .then(d => { window.__EVENTS_DATA = d; setData(d); })
        .catch(() => {});
    }
    const onEvents = (e) => setData(e.detail);
    window.addEventListener('ichi:events', onEvents);
    return () => window.removeEventListener('ichi:events', onEvents);
  }, []);
  return data;
}

function filterTF(list, tf) {
  if (!tf || tf === 'ALL') return list || [];
  return (list || []).filter(r => r.timeframe === tf);
}

// ── Shared small components ───────────────────────────────────────────────────

function TFBadge({ tf }) {
  const colors = { '4h': '#4fc3f7', '1d': '#00ff88', '1w': '#ffaa00' };
  const c = colors[tf] || '#888';
  return (
    <span style={{
      fontSize: 10, fontFamily: 'JetBrains Mono,monospace', fontWeight: 600,
      padding: '1px 5px', borderRadius: 3,
      border: `1px solid ${c}66`, color: c,
    }}>{tf}</span>
  );
}

const COND_TIP_KEYS = {
  TK:  { on: 'COND_TK_ON',    off: 'COND_TK_OFF'    },
  CS:  { on: 'COND_CS_ON',    off: 'COND_CS_OFF'     },
  '☁': { on: 'COND_CLOUD_ON', off: 'COND_CLOUD_OFF'  },
};

function CondBadge({ label, on }) {
  const ref = useRef_B(null);
  const tipKey = (COND_TIP_KEYS[label] || {})[on ? 'on' : 'off'] || label;
  return (
    <span
      ref={ref}
      style={{
        display: 'inline-block', marginRight: 3,
        fontSize: 10, fontFamily: 'JetBrains Mono,monospace',
        padding: '1px 5px', borderRadius: 3,
        background: on ? '#00ff8820' : '#ffffff08',
        border: `1px solid ${on ? '#00ff8855' : '#ffffff15'}`,
        color: on ? '#00ff88' : '#555',
        cursor: 'help',
      }}
      onMouseEnter={() => {
        if (!ref.current || !window.__showTip) return;
        const r = ref.current.getBoundingClientRect();
        window.__showTip({ x: r.left + r.width / 2, y: r.top, text: TIPS[tipKey] || tipKey });
      }}
      onMouseLeave={() => window.__hideTip?.()}
    >{label}</span>
  );
}

function SymWithTip({ sym, color, tip }) {
  const ref = useRef_B(null);
  return (
    <span
      ref={ref}
      className="clickable"
      style={{ color }}
      onClick={() => window.__openToken?.(sym)}
      onMouseEnter={() => {
        if (!ref.current || !window.__showTip) return;
        const r = ref.current.getBoundingClientRect();
        window.__showTip({ x: r.left + r.width / 2, y: r.top, text: tip });
      }}
      onMouseLeave={() => window.__hideTip?.()}
    >{sym}</span>
  );
}

function DBEmptyState({ msg }) {
  return <div style={{ padding: '28px 0', textAlign: 'center', color: '#555', fontFamily: 'JetBrains Mono,monospace', fontSize: 12 }}>
    {msg || 'No events detected on this scan.'}
  </div>;
}

function useSortB(col, asc = true) {
  const [s, setS] = useSt({ col, asc });
  const toggle = (c) => setS(p => ({ col: c, asc: p.col === c ? !p.asc : asc }));
  return [s, toggle];
}

function SortHeaderB({ col, label, sort, onSort }) {
  const active = sort.col === col;
  return (
    <th style={{ cursor: 'pointer', userSelect: 'none', whiteSpace: 'nowrap', color: active ? 'var(--accent)' : 'var(--dim)' }}
      onClick={() => onSort(col)}>
      {label}{active ? (sort.asc ? ' ▲' : ' ▼') : ''}
    </th>
  );
}

// ── 6 event panel result tables ───────────────────────────────────────────────

function TransitionTable({ tf }) {
  const data = useEvents();
  const [sort, onSort] = useSortB('bars_ago', true);
  const rows = [...filterTF(data?.transition_events, tf)].sort((a, b) => {
    const v = sort.col === 'bars_ago' ? a.bars_ago - b.bars_ago : b.bull_score - a.bull_score;
    return sort.asc ? v : -v;
  });
  if (!rows.length) return <DBEmptyState msg="No transition events on this scan." />;
  return (
    <table className="db-table">
      <thead><tr>
        <th>Symbol</th><th>TF</th>
        <SortHeaderB col="bars_ago" label={<AbbTip id="COL_BARS_AGO">Bars Ago</AbbTip>} sort={sort} onSort={onSort} />
        <th><AbbTip id="COL_CONDITIONS">Conditions</AbbTip></th>
        <SortHeaderB col="bull_score" label={<AbbTip id="COL_SCORE">Score</AbbTip>} sort={sort} onSort={onSort} />
        <th><AbbTip id="COL_PRICE_POS">Cloud Pos</AbbTip></th>
        <th><AbbTip id="COL_VOL">Vol Ratio</AbbTip></th>
      </tr></thead>
      <tbody>
        {rows.map((r, i) => (
          <tr key={i} className={'db-tr' + (r.full_cluster ? ' db-tr-green' : '') + (r.bars_ago > 10 ? ' db-tr-dim' : '')}>
            <td className="mono fw6">
              {r.full_cluster && <span style={{ color: '#ffaa00', marginRight: 4 }}>★</span>}
              <span className="clickable" onClick={() => window.__openToken?.(r.symbol.replace('/USDT',''))}>{r.symbol.replace('/USDT','')}</span>
            </td>
            <td><TFBadge tf={r.timeframe} /></td>
            <td className="mono">{r.bars_ago}b</td>
            <td><CondBadge label="TK" on={r.tk_cross_ok} /><CondBadge label="CS" on={r.chikou_ok} /><CondBadge label="☁" on={r.cloud_curl_ok} /></td>
            <td className="mono" style={{ color: scoreColor(r.bull_score || 0) }}>{r.bull_score ?? '—'}</td>
            <td className="mono dim">{r.cloud_position}</td>
            <td className="mono dim">{r.vol_ratio != null ? r.vol_ratio.toFixed(2) + 'x' : '—'}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function RetestTable({ tf }) {
  const data = useEvents();
  const [sort, onSort] = useSortB('distance_pct', true);
  const rows = [...filterTF(data?.retest_alerts, tf)].sort((a, b) => {
    if (a.group !== b.group) return a.group < b.group ? -1 : 1;
    const v = sort.col === 'distance_pct' ? a.distance_pct - b.distance_pct : b.bull_score - a.bull_score;
    return sort.asc ? v : -v;
  });
  const levelColor = l => l === 'CLOUD BOTTOM' ? '#ff3860' : l === 'CLOUD TOP' ? '#ffaa00' : '#4fc3f7';
  if (!rows.length) return <DBEmptyState msg="No active retest setups." />;
  return (
    <table className="db-table">
      <thead><tr>
        <th>Symbol</th><th>TF</th><th>Level</th>
        <SortHeaderB col="distance_pct" label={<AbbTip id="COL_DISTANCE">Distance</AbbTip>} sort={sort} onSort={onSort} />
        <th><AbbTip id="COL_SLOPE">Slope</AbbTip></th>
        <SortHeaderB col="bull_score" label={<AbbTip id="COL_SCORE">Score</AbbTip>} sort={sort} onSort={onSort} />
        <th><AbbTip id="GROUP_A">Group</AbbTip></th>
        <th><AbbTip id="COL_BOUNCE">Bounce Hist</AbbTip></th>
        <th>Note</th>
      </tr></thead>
      <tbody>
        {rows.map((r, i) => (
          <tr key={i} className={'db-tr' + (r.critical ? ' db-tr-red' : r.distance_pct < 0.5 ? ' db-tr-amber' : '')}>
            <td className="mono fw6">
              <SymWithTip
                sym={r.symbol.replace('/USDT','')}
                color={r.bounce_history ? '#00ff88' : undefined}
                tip={r.bounce_history
                  ? 'Green = TK Bounce rule confirmed in the 18-rule scorecard — this coin has a track record of bouncing from this level. Higher conviction retest.'
                  : 'White = no confirmed bounce history in the scorecard for this level.'}
              />
            </td>
            <td><TFBadge tf={r.timeframe} /></td>
            <td className="mono" style={{ color: levelColor(r.level) }}>{r.level}</td>
            <td className="mono">{r.distance_pct.toFixed(2)}%</td>
            <td className="mono" style={{ color: r.slope === 'FALLING' ? '#ffaa00' : undefined }}>{r.slope === 'FALLING' ? '⚠ ' : ''}{r.slope}</td>
            <td className="mono" style={{ color: scoreColor(r.bull_score || 0) }}>{r.bull_score ?? '—'}</td>
            <td className="mono dim"><AbbTip id={r.group === 'A' ? 'GROUP_A' : 'GROUP_B'}>{r.group}</AbbTip></td>
            <td className="mono dim">{r.bounce_history ? '✓' : '—'}</td>
            <td className="mono dim" style={{ fontSize: 10, color: r.critical ? '#ff3860' : undefined }}>
              {r.critical ? <AbbTip id="CRITICAL">CRITICAL</AbbTip> : r.broke_out_bars_ago != null ? `Breakout ${r.broke_out_bars_ago}b ago` : ''}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function BalanceTable({ tf }) {
  const data = useEvents();
  const rows = [...filterTF(data?.balance_map, tf)].sort((a, b) => Math.abs(b.kj_distance_pct) - Math.abs(a.kj_distance_pct));
  const zoneColor = z => z === 'EXTENDED' ? '#ff3860' : z === 'ABOVE' ? '#ffaa00' : z === 'BALANCED' ? '#00ff88' : '#888';
  if (!rows.length) return <DBEmptyState msg="No balance data." />;
  return (
    <table className="db-table">
      <thead><tr>
        <th>Symbol</th><th>TF</th><th>Zone</th>
        <th><AbbTip id="COL_KJ_DIST">KJ Dist %</AbbTip></th>
        <th><AbbTip id="COL_TK_DIST">TK Dist %</AbbTip></th>
        <th><AbbTip id="COL_SLOPE">KJ Slope</AbbTip></th>
        <th><AbbTip id="COL_SCORE">Score</AbbTip></th>
      </tr></thead>
      <tbody>
        {rows.map((r, i) => (
          <tr key={i} className="db-tr">
            <td className="mono fw6"><span className="clickable" onClick={() => window.__openToken?.(r.symbol.replace('/USDT',''))}>{r.symbol.replace('/USDT','')}</span></td>
            <td><TFBadge tf={r.timeframe} /></td>
            <td className="mono fw6" style={{ color: zoneColor(r.zone) }}>
              <AbbTip id={r.zone === 'EXTENDED' ? 'EXTENDED' : r.zone === 'ABOVE' ? 'ABOVE_ZONE' : r.zone === 'BALANCED' ? 'BALANCED' : 'BELOW_ZONE'}>{r.zone}</AbbTip>
            </td>
            <td className="mono">{r.kj_distance_pct > 0 ? '+' : ''}{r.kj_distance_pct}%</td>
            <td className="mono dim">{r.tk_distance_pct > 0 ? '+' : ''}{r.tk_distance_pct}%</td>
            <td className="mono dim">{r.kj_slope}</td>
            <td className="mono" style={{ color: scoreColor(r.bull_score || 0) }}>{r.bull_score ?? '—'}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function KumoTwistTable({ tf }) {
  const data = useEvents();
  const [sort, onSort] = useSortB('bars_until_twist', true);
  const rows = [...filterTF(data?.kumo_twists, tf)].sort((a, b) => {
    const v = sort.col === 'bars_until_twist' ? a.bars_until_twist - b.bars_until_twist : b.bull_score - a.bull_score;
    return sort.asc ? v : -v;
  });
  const dirColor = d => d === 'BULL_TWIST' ? '#00ff88' : '#ff3860';
  if (!rows.length) return <DBEmptyState msg="No twists approaching in the next 20 bars." />;
  return (
    <table className="db-table">
      <thead><tr>
        <th>Symbol</th><th>TF</th>
        <SortHeaderB col="bars_until_twist" label={<AbbTip id="COL_TWIST_IN">Twist In</AbbTip>} sort={sort} onSort={onSort} />
        <th>Direction</th><th>Current Cloud</th>
        <SortHeaderB col="bull_score" label={<AbbTip id="COL_SCORE">Score</AbbTip>} sort={sort} onSort={onSort} />
        <th>Action Note</th>
      </tr></thead>
      <tbody>
        {rows.map((r, i) => (
          <tr key={i} className={'db-tr' + (r.bars_until_twist <= 3 ? ' db-tr-amber' : '')}>
            <td className="mono fw6"><span className="clickable" onClick={() => window.__openToken?.(r.symbol.replace('/USDT',''))}>{r.symbol.replace('/USDT','')}</span></td>
            <td><TFBadge tf={r.timeframe} /></td>
            <td className="mono">{r.bars_until_twist}b</td>
            <td className="mono fw6" style={{ color: dirColor(r.twist_direction) }}>
              <AbbTip id={r.twist_direction}>{r.twist_direction.replace('_',' ')}</AbbTip>
            </td>
            <td className="mono dim">{r.current_cloud}</td>
            <td className="mono" style={{ color: scoreColor(r.bull_score || 0) }}>{r.bull_score ?? '—'}</td>
            <td className="mono dim" style={{ fontSize: 10 }}>{r.action_note}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function E2ETable({ tf }) {
  const data = useEvents();
  const [showAbove, setShowAbove] = useSt(false);
  const [sort, onSort] = useSortB('cloud_thickness_pct', false);
  let rows = filterTF(data?.e2e_opportunities, tf);
  if (!showAbove) rows = rows.filter(r => r.direction === 'FROM_BELOW');
  rows = [...rows].sort((a, b) => {
    const v = sort.col === 'cloud_thickness_pct' ? b.cloud_thickness_pct - a.cloud_thickness_pct : b.target_pct - a.target_pct;
    return sort.asc ? v : -v;
  });
  return (
    <>
      <div style={{ marginBottom: 8 }}>
        <button className={'opt-toggle' + (showAbove ? ' on' : '')} style={{ fontSize: 10 }}
          onClick={() => setShowAbove(v => !v)}>
          {showAbove ? '✓ Showing FROM ABOVE' : 'Show FROM ABOVE entries'}
        </button>
      </div>
      {!rows.length ? <DBEmptyState msg="No E2E setups detected." /> : (
        <table className="db-table">
          <thead><tr>
            <th>Symbol</th><th>TF</th><th>Direction</th>
            <th>Entry</th><th>Target</th>
            <SortHeaderB col="target_pct" label={<AbbTip id="COL_TARGET_PCT">Target %</AbbTip>} sort={sort} onSort={onSort} />
            <SortHeaderB col="cloud_thickness_pct" label={<AbbTip id="COL_THICK">Cloud Thick</AbbTip>} sort={sort} onSort={onSort} />
            <th><AbbTip id="COL_BARS_AGO_E2E">Bars Ago</AbbTip></th>
            <th><AbbTip id="COL_SCORE">Score</AbbTip></th>
            <th>Flag</th>
          </tr></thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i} className={'db-tr' + (r.confirmed ? ' db-tr-green' : '')}>
                <td className="mono fw6"><span className="clickable" onClick={() => window.__openToken?.(r.symbol.replace('/USDT',''))}>{r.symbol.replace('/USDT','')}</span></td>
                <td><TFBadge tf={r.timeframe} /></td>
                <td className="mono dim" style={{ fontSize: 10 }}>
                  <AbbTip id={r.direction === 'FROM_BELOW' ? 'FROM_BELOW' : 'FROM_ABOVE'}>{r.direction}</AbbTip>
                </td>
                <td className="mono dim">{r.entry_price}</td>
                <td className="mono dim">{r.target_price}</td>
                <td className="mono" style={{ color: '#00ff88' }}>+{r.target_pct}%</td>
                <td className="mono dim">{r.cloud_thickness_pct}%</td>
                <td className="mono dim">{r.entered_bars_ago}b</td>
                <td className="mono" style={{ color: scoreColor(r.bull_score || 0) }}>{r.bull_score ?? '—'}</td>
                <td className="mono" style={{ fontSize: 10, color: r.confirmed ? '#00ff88' : '#555' }}>
                  {r.confirmed ? <AbbTip id="CONFIRMED">CONFIRMED</AbbTip> : '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}

function CloudCurlingTable({ tf }) {
  const data = useEvents();
  const STATE_ORDER = { JUST_TWISTED: 0, IMMINENT: 1, EARLY: 2 };
  const [sort, onSort] = useSortB('state', true);
  const rows = [...filterTF(data?.cloud_curling, tf)].sort((a, b) => {
    if (sort.col === 'state') {
      const d = (STATE_ORDER[a.state] || 0) - (STATE_ORDER[b.state] || 0);
      return sort.asc ? d || (a.bars_to_twist - b.bars_to_twist) : -d || (a.bars_to_twist - b.bars_to_twist);
    }
    return sort.asc ? (b.bull_score - a.bull_score) : (a.bull_score - b.bull_score);
  });
  const stateColor = s => s === 'JUST_TWISTED' ? '#00ff88' : s === 'IMMINENT' ? '#ffaa00' : '#888';
  if (!rows.length) return <DBEmptyState msg="No cloud curling detected." />;
  return (
    <table className="db-table">
      <thead><tr>
        <th>Symbol</th><th>TF</th>
        <SortHeaderB col="state" label="State" sort={sort} onSort={onSort} />
        <th><AbbTip id="COL_TWIST_IN">Bars to Twist</AbbTip></th>
        <th><AbbTip id="COL_SPANA_SLOPE">SpanA Slope</AbbTip></th>
        <th><AbbTip id="COL_THICK">Cloud Thick</AbbTip></th>
        <SortHeaderB col="bull_score" label={<AbbTip id="COL_SCORE">Score</AbbTip>} sort={sort} onSort={onSort} />
        <th><AbbTip id="COL_PRICE_POS">Price Pos</AbbTip></th>
      </tr></thead>
      <tbody>
        {rows.map((r, i) => (
          <tr key={i} className={'db-tr' + (r.state === 'JUST_TWISTED' ? ' db-tr-green' : r.state === 'IMMINENT' ? ' db-tr-amber' : '')}>
            <td className="mono fw6"><span className="clickable" onClick={() => window.__openToken?.(r.symbol.replace('/USDT',''))}>{r.symbol.replace('/USDT','')}</span></td>
            <td><TFBadge tf={r.timeframe} /></td>
            <td className="mono fw6" style={{ color: stateColor(r.state) }}>
              <AbbTip id={r.state}>{r.state.replace(/_/g,' ')}</AbbTip>
            </td>
            <td className="mono dim">{r.bars_to_twist === 99 ? '—' : r.bars_to_twist + 'b'}</td>
            <td className="mono dim">{r.span_a_lead_slope > 0 ? '+' : ''}{r.span_a_lead_slope}</td>
            <td className="mono dim">{r.cloud_thickness_pct}%</td>
            <td className="mono" style={{ color: scoreColor(r.bull_score || 0) }}>{r.bull_score ?? '—'}</td>
            <td className="mono dim">{r.price_position}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

// ── MTF Event View — always visible at bottom ─────────────────────────────────

const EVENT_COLORS = {
  TK: '#00ff88', 'RT-TK': '#4fc3f7', 'RT-KJ': '#4fc3f7',
  'RT-CT': '#ffaa00', 'RT-CB': '#ff3860',
  E2E: '#7c3aed', CURL: '#39ff14', TWIST: '#ffaa00', BAL: '#888',
};

function buildMTF(data) {
  if (!data) return [];
  const map = {};
  const add = (sym, tf, label, full) => {
    if (!map[sym]) map[sym] = { symbol: sym, '4h': [], '1d': [], score1d: 0 };
    if (!map[sym][tf]) map[sym][tf] = [];
    map[sym][tf].push({ label, full: !!full });
  };
  (data.transition_events   || []).forEach(r => add(r.symbol, r.timeframe, 'TK',    r.full_cluster));
  (data.retest_alerts        || []).forEach(r => {
    const l = r.level === 'TK' ? 'RT-TK' : r.level === 'KJ' ? 'RT-KJ' : r.level === 'CLOUD TOP' ? 'RT-CT' : 'RT-CB';
    add(r.symbol, r.timeframe, l, false);
  });
  (data.e2e_opportunities    || []).forEach(r => add(r.symbol, r.timeframe, 'E2E',  r.confirmed));
  (data.cloud_curling        || []).forEach(r => add(r.symbol, r.timeframe, 'CURL', r.state === 'JUST_TWISTED'));
  (data.kumo_twists          || []).forEach(r => add(r.symbol, r.timeframe, 'TWIST', false));
  (data.transition_events    || []).forEach(r => { if (r.timeframe === '1d' && map[r.symbol]) map[r.symbol].score1d = r.bull_score || 0; });
  return Object.values(map).map(row => ({
    ...row,
    aligned: ['4h','1d'].filter(tf => (row[tf]||[]).length > 0).length,
  })).sort((a,b) => b.aligned - a.aligned || b.score1d - a.score1d);
}

function EventBadge({ label, full }) {
  const ref = useRef_B(null);
  const color = EVENT_COLORS[label] || '#888';
  return (
    <span
      ref={ref}
      style={{
        display:'inline-block', marginRight:3, marginBottom:2,
        fontSize:9.5, fontFamily:'JetBrains Mono,monospace', fontWeight:600,
        padding:'1px 4px', borderRadius:3,
        background: color+'18', border:`1px solid ${color}55`, color,
        cursor: 'help',
      }}
      onMouseEnter={() => {
        if (!ref.current || !window.__showTip) return;
        const r = ref.current.getBoundingClientRect();
        window.__showTip({ x: r.left + r.width / 2, y: r.top, text: TIPS[label] || label });
      }}
      onMouseLeave={() => window.__hideTip?.()}
    >{full ? '★' : ''}{label}</span>
  );
}

function MTFEventBar({ data }) {
  const [expanded, setExpanded] = useSt(null);
  const rows = buildMTF(data);
  const TFS = ['4h', '1d'];

  if (!rows.length) return (
    <div className="db-mtf-bar">
      <div className="db-mtf-bar-head">
        <span className="mono" style={{ fontSize: 12, fontWeight: 600 }}>MTF Event View</span>
        <InfoTip>Multi-timeframe alignment: a signal appearing on multiple timeframes simultaneously is stronger. Use this to find convergence.</InfoTip>
      </div>
      <DBEmptyState msg="No multi-timeframe events yet." />
    </div>
  );

  return (
    <div className="db-mtf-bar">
      <div className="db-mtf-bar-head">
        <span className="mono" style={{ fontSize: 12, fontWeight: 600 }}>MTF Event View</span>
        <span className="db-count-badge mono">{rows.length}</span>
        <InfoTip>Multi-timeframe alignment: a signal appearing on both 4h and 1d simultaneously is stronger. Stars (★) mark full-cluster or confirmed events.</InfoTip>
      </div>
      <div style={{ overflowX: 'auto' }}>
        <table className="db-table">
          <thead><tr>
            <th>Symbol</th>
            {TFS.map(tf => <th key={tf}><TFBadge tf={tf} /> Events</th>)}
            <th><AbbTip id="COL_ALIGNED">Aligned</AbbTip></th>
            <th><AbbTip id="COL_SCORE">1d Score</AbbTip></th>
            <th>Drill</th>
          </tr></thead>
          <tbody>
            {rows.map((r, i) => {
              const isExp = expanded?.sym === r.symbol;
              return (
                <React.Fragment key={i}>
                  <tr className={'db-tr' + (r.aligned >= 2 ? ' db-tr-amber' : '')}>
                    <td className="mono fw6">
                      {r.aligned >= 2 && <span style={{ color: '#ffaa00', marginRight: 4 }}>★</span>}
                      <span className="clickable" onClick={() => window.__openToken?.(r.symbol.replace('/USDT',''))}>{r.symbol.replace('/USDT','')}</span>
                    </td>
                    {TFS.map(tf => (
                      <td key={tf}>{(r[tf]||[]).map((ev,j) => <EventBadge key={j} label={ev.label} full={ev.full} />)}</td>
                    ))}
                    <td className="mono" style={{ color: r.aligned >= 2 ? '#ffaa00' : '#888' }}>{r.aligned}/{TFS.length}</td>
                    <td className="mono" style={{ color: scoreColor(r.score1d) }}>{r.score1d || '—'}</td>
                    <td>
                      {TFS.map(tf => (
                        <button key={tf}
                          className={'dashb-tf-btn mono' + (isExp && expanded.tf === tf ? ' active' : '')}
                          style={{ fontSize: 9.5, padding: '1px 6px', marginRight: 3 }}
                          onClick={() => setExpanded(isExp && expanded.tf === tf ? null : { sym: r.symbol, tf })}>
                          {tf}
                        </button>
                      ))}
                    </td>
                  </tr>
                  {isExp && (
                    <tr className="db-tr-expand">
                      <td colSpan={6} style={{ paddingLeft: 24, paddingBottom: 10 }}>
                        <MTFExpanded symbol={r.symbol} tf={expanded.tf} data={data} row={r} />
                      </td>
                    </tr>
                  )}
                </React.Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function MTFExpanded({ symbol, tf, data, row }) {
  const evs = row[tf] || [];
  const bm = (data?.balance_map    || []).find(r => r.symbol === symbol && r.timeframe === tf);
  const te = (data?.transition_events || []).find(r => r.symbol === symbol && r.timeframe === tf);
  return (
    <div style={{ display: 'flex', gap: 24, flexWrap: 'wrap', fontSize: 11 }}>
      <div>
        <div className="mono dim" style={{ fontSize: 10, marginBottom: 4 }}>{symbol} · {tf} active events</div>
        <div>{evs.length ? evs.map((e,i) => <EventBadge key={i} label={e.label} full={e.full} />) : <span className="dim">none</span>}</div>
      </div>
      {bm && (
        <div className="mono dim" style={{ fontSize: 10, lineHeight: 2 }}>
          <div>KJ dist: <span style={{ color:'#e0e0e0' }}>{bm.kj_distance_pct > 0 ? '+' : ''}{bm.kj_distance_pct}%</span></div>
          <div>KJ slope: <span style={{ color:'#e0e0e0' }}>{bm.kj_slope}</span></div>
          <div>Zone: <span style={{ color:'#e0e0e0' }}>{bm.zone}</span></div>
        </div>
      )}
      {te && (
        <div className="mono dim" style={{ fontSize: 10, lineHeight: 2 }}>
          <div>TK cross: <span style={{ color:'#e0e0e0' }}>{te.bars_ago}b ago</span></div>
          <div>Chikou: <span style={{ color:'#e0e0e0' }}>{te.chikou_state}</span></div>
          <div>Cloud pos: <span style={{ color:'#e0e0e0' }}>{te.cloud_position}</span></div>
        </div>
      )}
    </div>
  );
}

// ── Notification Center ───────────────────────────────────────────────────────

function NotifCenter({ open, onClose }) {
  const [entries, setEntries] = useSt(() => window.IchiAlerts?.getHistory() || []);
  const ref = useRef_B(null);

  useEff(() => {
    const update = () => setEntries(window.IchiAlerts?.getHistory() || []);
    window.addEventListener('ichi:notif-update', update);
    return () => window.removeEventListener('ichi:notif-update', update);
  }, []);

  // Close on outside click
  useEff(() => {
    if (!open) return;
    const handler = (e) => { if (ref.current && !ref.current.contains(e.target)) onClose(); };
    setTimeout(() => document.addEventListener('mousedown', handler), 0);
    return () => document.removeEventListener('mousedown', handler);
  }, [open]);

  const fmt = (iso) => {
    const d = new Date(iso);
    return d.toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit', hour12: true });
  };

  const priorityDot = (p) => (
    <span style={{ width: 7, height: 7, borderRadius: '50%', display: 'inline-block', flexShrink: 0,
      background: p === 'high' ? '#ff3860' : '#ffaa00', marginRight: 8, marginTop: 1 }} />
  );

  return (
    <div className={'notif-drawer' + (open ? ' open' : '')} ref={ref}>
      <div className="notif-drawer-head">
        <span className="mono" style={{ fontWeight: 600, fontSize: 13 }}>Notifications</span>
        <div style={{ display: 'flex', gap: 8 }}>
          {entries.length > 0 && (
            <>
              <button className="notif-action-btn" onClick={() => { window.IchiAlerts?.markAllRead(); setEntries(window.IchiAlerts?.getHistory() || []); }}>
                Mark all read
              </button>
              <button className="notif-action-btn" style={{ color: '#ff386099' }} onClick={() => { window.IchiAlerts?.clearHistory(); setEntries([]); }}>
                Clear
              </button>
            </>
          )}
          <button className="notif-close-btn" onClick={onClose}>✕</button>
        </div>
      </div>
      <div className="notif-drawer-body">
        {entries.length === 0
          ? <div style={{ padding: '40px 20px', textAlign: 'center', color: '#555', fontFamily: 'JetBrains Mono,monospace', fontSize: 12 }}>
              No notifications yet.<br />Signals fire automatically every minute.
            </div>
          : entries.map((e) => (
              <div key={e.id} className={'notif-entry' + (e.read ? ' notif-read' : '')}
                style={{ borderLeftColor: e.color || '#888' }}>
                <div style={{ display: 'flex', alignItems: 'flex-start', gap: 0 }}>
                  {priorityDot(e.priority)}
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 3 }}>
                      <span className="mono fw6" style={{ fontSize: 12, color: '#e0e0e0' }}>{e.symbol.replace('/USDT','')}</span>
                      <TFBadge tf={e.tf} />
                      <span style={{
                        fontSize: 9.5, fontFamily: 'JetBrains Mono,monospace', fontWeight: 600,
                        padding: '1px 5px', borderRadius: 3,
                        background: (e.color || '#888') + '20',
                        border: `1px solid ${(e.color || '#888')}44`,
                        color: e.color || '#888',
                      }}>{e.type}</span>
                      {!e.read && <span style={{ fontSize: 8, background: '#7c3aed', borderRadius: 10, padding: '1px 5px', color: '#fff', fontFamily: 'JetBrains Mono,monospace' }}>NEW</span>}
                    </div>
                    <div className="mono dim" style={{ fontSize: 10.5, lineHeight: 1.5 }}>{e.summary}</div>
                    <div className="mono dim" style={{ fontSize: 10, marginTop: 4, color: '#444' }}>{fmt(e.ts)}</div>
                  </div>
                </div>
              </div>
            ))
        }
      </div>
    </div>
  );
}

// ── Signal Log Panel ─────────────────────────────────────────────────────────

const SIGNAL_NAMES = {
  1: 'Sanyaku', 2: 'Balanced Breakout', 3: 'KJ Break Retest',
  4: 'E2E Entry', 5: 'Twist Breakout', 6: 'Cloud Curling',
  7: 'Four-Level Retest', 9: 'Chikou S/R Retest',
};

function useSignals(tab) {
  const [data, setData] = useSt(null);
  const [loading, setLoading] = useSt(false);

  useEff(() => {
    setLoading(true);
    fetch(window.API_BASE + '/api/signals?tab=' + tab)
      .then(r => r.json())
      .then(d => { setData(d); setLoading(false); })
      .catch(() => setLoading(false));
  }, [tab]);

  // Refresh on new signal notifications
  useEff(() => {
    const refresh = () => {
      fetch(window.API_BASE + '/api/signals?tab=' + tab)
        .then(r => r.json())
        .then(d => setData(d))
        .catch(() => {});
    };
    window.addEventListener('ichi:notif-update', refresh);
    return () => window.removeEventListener('ichi:notif-update', refresh);
  }, [tab]);

  return { data, loading };
}

function fmtRelTime(iso) {
  if (!iso) return '—';
  const diff = Date.now() - new Date(iso).getTime();
  const m = Math.floor(diff / 60000);
  if (m < 60) return m + 'm ago';
  const h = Math.floor(m / 60);
  if (h < 24) return h + 'h ago';
  return Math.floor(h / 24) + 'd ago';
}

function SignalTypeBadge({ type, subtype }) {
  const name = SIGNAL_NAMES[type] || `Sig ${type}`;
  const sub  = subtype ? subtype.replace(String(type), '') : '';
  return (
    <span style={{
      fontSize: 10, fontFamily: 'JetBrains Mono,monospace',
      padding: '1px 5px', borderRadius: 3, marginRight: 4,
      background: '#7c3aed20', border: '1px solid #7c3aed55', color: '#c4b5fd',
    }}>{type}{sub}</span>
  );
}

function SigReturnCell({ val, label }) {
  if (val == null) return <span className="mono dim">—</span>;
  const color = val > 0 ? '#00ff88' : val < 0 ? '#ff3860' : '#888';
  return <span className="mono" style={{ color }}>{val > 0 ? '+' : ''}{val.toFixed(1)}%{label ? <span className="dim" style={{ fontSize: 9 }}> {label}</span> : null}</span>;
}

function SigRow({ row, expanded, onToggle }) {
  const meta = (() => { try { return JSON.parse(row.signal_metadata || '{}'); } catch { return {}; } })();
  const warnLog = (() => { try { return JSON.parse(row.warning_log || '[]'); } catch { return []; } })();
  const sym = (row.symbol || '').replace('USDT', '');
  const hosoda = row.hosoda_active;
  const cooc   = row.cooccurrence_count > 0;
  const statusColor = row.status === 'OPEN' ? '#00ff88' : '#555';

  return (
    <React.Fragment>
      <tr className="db-tr" style={{ cursor: 'pointer' }} onClick={onToggle}>
        <td className="mono dim" style={{ fontSize: 10 }}>
          <SignalTypeBadge type={row.signal_type} subtype={row.signal_subtype} />
          {SIGNAL_NAMES[row.signal_type] || '—'}
        </td>
        <td className="mono fw6">
          <span className="clickable" onClick={e => { e.stopPropagation(); window.__openToken?.(sym); }}>{sym}</span>
        </td>
        <td><TFBadge tf={row.timeframe} /></td>
        <td className="mono dim" style={{ fontSize: 10 }}>{fmtRelTime(row.fired_at)}</td>
        <td className="mono dim" style={{ fontSize: 10 }}>{row.entry_price ? Number(row.entry_price).toLocaleString(undefined, { maximumFractionDigits: 4 }) : '—'}</td>
        <td><SigReturnCell val={row.return_7d} label="7d" /></td>
        <td><SigReturnCell val={row.return_30d} label="30d" /></td>
        <td>
          <span className="mono" style={{ fontSize: 10, color: statusColor, fontWeight: 600 }}>{row.status}</span>
        </td>
        <td className="mono dim" style={{ fontSize: 9.5 }}>{row.exit_condition ? row.exit_condition.replace(/_/g, ' ') : '—'}</td>
        <td style={{ textAlign: 'center' }}>{hosoda ? <span title="Hosoda count confluence">⚡</span> : '—'}</td>
        <td style={{ textAlign: 'center' }}>
          {cooc ? <span style={{ fontSize: 9, background: '#ffaa0020', border: '1px solid #ffaa0055', color: '#ffaa00', borderRadius: 3, padding: '1px 4px', fontFamily: 'JetBrains Mono,monospace' }}>CO-OCC</span> : '—'}
        </td>
      </tr>
      {expanded && (
        <tr className="db-tr-expand">
          <td colSpan={11} style={{ paddingLeft: 20, paddingBottom: 10, paddingTop: 6 }}>
            <div style={{ display: 'flex', gap: 32, flexWrap: 'wrap', fontSize: 11 }}>
              {Object.keys(meta).length > 0 && (
                <div>
                  <div className="mono dim" style={{ fontSize: 10, marginBottom: 4 }}>Signal Metadata</div>
                  {Object.entries(meta).map(([k, v]) => (
                    <div key={k} className="mono dim" style={{ fontSize: 10, lineHeight: 1.8 }}>
                      {k}: <span style={{ color: '#e0e0e0' }}>{v != null ? String(v) : '—'}</span>
                    </div>
                  ))}
                </div>
              )}
              {warnLog.length > 0 && (
                <div>
                  <div className="mono dim" style={{ fontSize: 10, marginBottom: 4 }}>Warning Log</div>
                  {warnLog.map((w, i) => (
                    <div key={i} className="mono" style={{ fontSize: 10, lineHeight: 1.8,
                      color: w.tier === 2 ? '#ffaa00' : '#888' }}>
                      Bar {w.bar} · Tier {w.tier} · {w.condition.replace(/_/g, ' ')}
                    </div>
                  ))}
                </div>
              )}
              {row.hosoda_number && (
                <div className="mono dim" style={{ fontSize: 10 }}>
                  <div style={{ marginBottom: 4 }}>Hosoda</div>
                  <div>Count: <span style={{ color: '#c4b5fd' }}>{row.hosoda_number}</span></div>
                  <div>Pivot: <span style={{ color: '#c4b5fd' }}>{row.hosoda_pivot_type}</span></div>
                </div>
              )}
            </div>
          </td>
        </tr>
      )}
    </React.Fragment>
  );
}

function SignalRecentTable({ rows }) {
  const [expanded, setExpanded] = useSt(null);
  if (!rows.length) return <DBEmptyState msg="No signals in the last 14 days. Run a backfill or wait for the next scan." />;
  return (
    <div style={{ overflowX: 'auto' }}>
      <table className="db-table">
        <thead><tr>
          <th>Type</th><th>Symbol</th><th>TF</th><th>Fired</th><th>Entry</th>
          <th>7d Ret</th><th>30d Ret</th><th>Status</th><th>Exit</th>
          <th title="Hosoda confluence">⚡</th><th>Co-occ</th>
        </tr></thead>
        <tbody>
          {rows.map((r, i) => (
            <SigRow key={r.signal_id || i} row={r}
              expanded={expanded === (r.signal_id || i)}
              onToggle={() => setExpanded(p => p === (r.signal_id || i) ? null : (r.signal_id || i))}
            />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function SignalOpenTable({ rows }) {
  const [expanded, setExpanded] = useSt(null);
  const riskColor = r => {
    const wl = (() => { try { return JSON.parse(r.warning_log || '[]'); } catch { return []; } })();
    const maxTier = wl.reduce((m, w) => Math.max(m, w.tier || 0), 0);
    return maxTier >= 2 ? '#ff3860' : maxTier >= 1 ? '#ffaa00' : '#00ff88';
  };
  if (!rows.length) return <DBEmptyState msg="No open signal instances." />;
  return (
    <div style={{ overflowX: 'auto' }}>
      <table className="db-table">
        <thead><tr>
          <th>Type</th><th>Symbol</th><th>TF</th><th>Fired</th><th>Entry</th>
          <th>7d Ret</th><th>30d Ret</th><th>Status</th><th>Exit</th>
          <th title="Hosoda confluence">⚡</th><th>Co-occ</th>
          <th>Days Open</th><th title="Max adverse excursion so far">MAE</th>
          <th title="Max favorable excursion so far">MFE</th><th>Exit Risk</th>
        </tr></thead>
        <tbody>
          {rows.map((r, i) => (
            <React.Fragment key={r.signal_id || i}>
              <tr className="db-tr" style={{ cursor: 'pointer' }}
                onClick={() => setExpanded(p => p === (r.signal_id || i) ? null : (r.signal_id || i))}>
                <td className="mono dim" style={{ fontSize: 10 }}>
                  <SignalTypeBadge type={r.signal_type} subtype={r.signal_subtype} />
                  {SIGNAL_NAMES[r.signal_type] || '—'}
                </td>
                <td className="mono fw6">
                  <span className="clickable" onClick={e => { e.stopPropagation(); window.__openToken?.((r.symbol||'').replace('USDT','')); }}>{(r.symbol||'').replace('USDT','')}</span>
                </td>
                <td><TFBadge tf={r.timeframe} /></td>
                <td className="mono dim" style={{ fontSize: 10 }}>{fmtRelTime(r.fired_at)}</td>
                <td className="mono dim" style={{ fontSize: 10 }}>{r.entry_price ? Number(r.entry_price).toLocaleString(undefined, { maximumFractionDigits: 4 }) : '—'}</td>
                <td><SigReturnCell val={r.return_7d} label="7d" /></td>
                <td><SigReturnCell val={r.return_30d} label="30d" /></td>
                <td><span className="mono" style={{ fontSize: 10, color: '#00ff88', fontWeight: 600 }}>OPEN</span></td>
                <td className="mono dim" style={{ fontSize: 9.5 }}>—</td>
                <td style={{ textAlign: 'center' }}>{r.hosoda_active ? '⚡' : '—'}</td>
                <td style={{ textAlign: 'center' }}>{r.cooccurrence_count > 0 ? <span style={{ fontSize: 9, background: '#ffaa0020', border: '1px solid #ffaa0055', color: '#ffaa00', borderRadius: 3, padding: '1px 4px', fontFamily: 'JetBrains Mono,monospace' }}>CO-OCC</span> : '—'}</td>
                <td className="mono dim">{r.days_open != null ? r.days_open + 'd' : '—'}</td>
                <td className="mono" style={{ fontSize: 10, color: r.mae != null ? (r.mae < -5 ? '#ff3860' : r.mae < -2 ? '#ffaa00' : '#888') : '#555' }}>
                  {r.mae != null ? (r.mae > 0 ? '+' : '') + r.mae.toFixed(1) + '%' : '—'}
                </td>
                <td className="mono" style={{ fontSize: 10, color: r.mfe != null ? '#00ff88' : '#555' }}>
                  {r.mfe != null ? '+' + r.mfe.toFixed(1) + '%' : '—'}
                </td>
                <td><span className="mono fw6" style={{ fontSize: 10, color: riskColor(r) }}>{riskColor(r) === '#ff3860' ? 'RED' : riskColor(r) === '#ffaa00' ? 'AMBER' : 'OK'}</span></td>
              </tr>
              {expanded === (r.signal_id || i) && (() => {
                const meta = (() => { try { return JSON.parse(r.signal_metadata || '{}'); } catch { return {}; } })();
                const wl   = (() => { try { return JSON.parse(r.warning_log || '[]'); } catch { return []; } })();
                return (
                  <tr className="db-tr-expand">
                    <td colSpan={16} style={{ paddingLeft: 20, paddingBottom: 10, paddingTop: 6 }}>
                      <div style={{ display: 'flex', gap: 32, flexWrap: 'wrap', fontSize: 11 }}>
                        {Object.keys(meta).length > 0 && (
                          <div>
                            <div className="mono dim" style={{ fontSize: 10, marginBottom: 4 }}>Metadata</div>
                            {Object.entries(meta).map(([k, v]) => (
                              <div key={k} className="mono dim" style={{ fontSize: 10, lineHeight: 1.8 }}>
                                {k}: <span style={{ color: '#e0e0e0' }}>{v != null ? String(v) : '—'}</span>
                              </div>
                            ))}
                          </div>
                        )}
                        {wl.length > 0 && (
                          <div>
                            <div className="mono dim" style={{ fontSize: 10, marginBottom: 4 }}>Warnings ({wl.length})</div>
                            {wl.map((w, j) => (
                              <div key={j} className="mono" style={{ fontSize: 10, lineHeight: 1.8, color: w.tier >= 2 ? '#ffaa00' : '#888' }}>
                                Bar {w.bar} · T{w.tier} · {w.condition.replace(/_/g,' ')}
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    </td>
                  </tr>
                );
              })()}
            </React.Fragment>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function SignalPerfTable({ stats }) {
  if (!stats || !stats.length) return <DBEmptyState msg="No performance data yet. Run a backfill to generate historical signal instances." />;
  const gradeColor = g => g === 'STRONG' ? '#00ff88' : g === 'MODERATE' ? '#ffaa00' : g === 'WEAK' ? '#ff3860' : '#555';
  return (
    <div style={{ overflowX: 'auto' }}>
      <table className="db-table">
        <thead><tr>
          <th>Signal</th><th>N</th><th>Closed</th>
          <th><AbbTip id="COL_SCORE">Mean 30d Ret</AbbTip></th>
          <th>Win Rate</th><th title="Mean winner / abs(mean loser)">W/L</th>
          <th>Avg Bars</th>
          <th title="Mean max adverse excursion (closed)">Mean MAE</th>
          <th title="75th-pct max adverse excursion (worst-end)">P75 MAE</th>
          <th title="Conservative max leverage: 0.5 / abs(P75 MAE)">Lev Est</th>
          <th title="Hosoda confluence lift">⚡ Lift</th>
          <th>Grade</th>
        </tr></thead>
        <tbody>
          {stats.map((r, i) => (
            <tr key={i} className="db-tr">
              <td className="mono dim" style={{ fontSize: 11 }}>
                <SignalTypeBadge type={r.signal_type} subtype={null} />
                {r.signal_name}
              </td>
              <td className="mono dim">{r.n_instances}</td>
              <td className="mono dim">{r.n_closed}</td>
              <td><SigReturnCell val={r.mean_return_30d} /></td>
              <td className="mono" style={{ color: (r.win_rate || 0) >= 0.6 ? '#00ff88' : (r.win_rate || 0) >= 0.5 ? '#ffaa00' : '#888' }}>
                {r.win_rate != null ? (r.win_rate * 100).toFixed(1) + '%' : '—'}
              </td>
              <td className="mono" style={{ fontSize: 10, color: (r.win_loss_ratio || 0) >= 1.5 ? '#00ff88' : (r.win_loss_ratio || 0) >= 1.0 ? '#ffaa00' : '#888' }}>
                {r.win_loss_ratio != null ? r.win_loss_ratio.toFixed(2) : '—'}
              </td>
              <td className="mono dim">{r.mean_exit_bars != null ? r.mean_exit_bars.toFixed(0) : '—'}</td>
              <td className="mono" style={{ fontSize: 10, color: r.mean_mae != null ? (r.mean_mae < -5 ? '#ff3860' : r.mean_mae < -2 ? '#ffaa00' : '#888') : '#555' }}>
                {r.mean_mae != null ? r.mean_mae.toFixed(1) + '%' : '—'}
              </td>
              <td className="mono" style={{ fontSize: 10, color: r.p75_mae != null ? (r.p75_mae < -8 ? '#ff3860' : r.p75_mae < -4 ? '#ffaa00' : '#888') : '#555' }}>
                {r.p75_mae != null ? r.p75_mae.toFixed(1) + '%' : '—'}
              </td>
              <td className="mono dim" style={{ fontSize: 10 }}>
                {r.lev_safe_est != null ? r.lev_safe_est.toFixed(1) + 'x' : '—'}
              </td>
              <td className="mono dim" style={{ fontSize: 10 }}>
                {r.hosoda_yes_mean_30d != null && r.hosoda_no_mean_30d != null
                  ? <><span style={{ color: '#c4b5fd' }}>⚡{r.hosoda_yes_mean_30d > 0 ? '+' : ''}{r.hosoda_yes_mean_30d.toFixed(1)}%</span>
                     <span className="dim"> vs {r.hosoda_no_mean_30d > 0 ? '+' : ''}{r.hosoda_no_mean_30d.toFixed(1)}%</span></>
                  : '—'}
              </td>
              <td>
                <span className="mono fw6" style={{ fontSize: 10, color: gradeColor(r.grade) }}>{r.grade}</span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function SignalLogPanel() {
  const [tab, setTab] = useSt('recent');
  const { data, loading } = useSignals(tab);

  const tabStyle = (t) => ({
    padding: '5px 14px',
    fontFamily: 'JetBrains Mono,monospace',
    fontSize: 11,
    fontWeight: tab === t ? 700 : 400,
    color: tab === t ? '#c4b5fd' : '#555',
    background: tab === t ? '#7c3aed20' : 'transparent',
    border: `1px solid ${tab === t ? '#7c3aed55' : '#ffffff10'}`,
    borderRadius: 4,
    cursor: 'pointer',
  });

  const rows = data?.rows || [];
  const stats = data?.stats || [];

  return (
    <div className="db-mtf-bar" style={{ marginTop: 16 }}>
      <div className="db-mtf-bar-head" style={{ marginBottom: 12 }}>
        <span className="mono" style={{ fontSize: 12, fontWeight: 600 }}>
          Signal Log
          <span style={{ marginLeft: 6, fontSize: 10, color: '#7c3aed', fontWeight: 400 }}>
            Named Ichimoku signals — tracked with exit conditions and forward returns
          </span>
        </span>
        <InfoTip>8 named Ichimoku signal types (Signals 1–7 and 9) derived from Ikagi/Hosoda theory. Each instance is logged on detection, tracked with exit conditions, and evaluated for predictive edge. ⚡ = Hosoda candle count confluence. CO-OCC = co-occurrence with another signal within 5 bars.</InfoTip>
        <div style={{ display: 'flex', gap: 6 }}>
          {['recent', 'open', 'performance'].map(t => (
            <button key={t} style={tabStyle(t)} onClick={() => setTab(t)}>
              {t.toUpperCase()}
            </button>
          ))}
        </div>
      </div>

      {loading
        ? <div className="mono dim" style={{ padding: '20px 0', textAlign: 'center', fontSize: 12 }}>Loading…</div>
        : tab === 'performance'
          ? <SignalPerfTable stats={stats} />
          : tab === 'open'
            ? <SignalOpenTable rows={rows} />
            : <SignalRecentTable rows={rows} />
      }
    </div>
  );
}

// ── 6 event cards (Dashboard A pattern) ──────────────────────────────────────

const B_CARDS = [
  {
    id: 'transition',
    name: 'Transition Events',
    desc: 'Fresh TK cross + chikou + cloud curl — earliest reversal cluster',
    accent: '#00ff88',
    tip: <span>A fresh TK cross combined with the chikou entering the cloud and the forward cloud curling upward are the earliest Ichimoku reversal signals. Full cluster (all 3) triggers a HIGH priority alert.</span>,
    countKey: 'transition_events',
    Table: TransitionTable,
  },
  {
    id: 'retest',
    name: 'Line & Cloud Retests',
    desc: 'Price testing TK / KJ / cloud top / cloud bottom from above',
    accent: '#4fc3f7',
    tip: <span>In a confirmed uptrend, the four Ichimoku support levels are ideal re-entry points on pullbacks. Cloud bottom retests are CRITICAL — a close below invalidates the bull setup.</span>,
    countKey: 'retest_alerts',
    Table: RetestTable,
  },
  {
    id: 'e2e',
    name: 'Edge-to-Edge (E2E)',
    desc: 'Price just entered the cloud — trade to the opposite edge',
    accent: '#7c3aed',
    tip: <span>When price enters the Kumo it often travels to the opposite edge. Entry: first close inside cloud. Target: far edge. Failure: close back outside from entry side. Thick clouds = bigger range.</span>,
    countKey: 'e2e_opportunities',
    Table: E2ETable,
  },
  {
    id: 'cloud_curling',
    name: 'Cloud Curling',
    desc: 'Leading cloud transitioning bearish → bullish — early warning',
    accent: '#39ff14',
    tip: <span>Cloud curling fires before any confirmed breakout. When SpanA slope turns upward while the cloud is still bearish, the cloud will soon flip. Earliest Ichimoku signal — highest false-signal rate.</span>,
    countKey: 'cloud_curling',
    Table: CloudCurlingTable,
  },
  {
    id: 'kumo_twist',
    name: 'Kumo Twist Calendar',
    desc: 'Upcoming dates when leading cloud changes polarity',
    accent: '#ffaa00',
    tip: <span>A Kumo Twist is when projected Senkou Span A and B are about to cross. These are time pivots — the market often makes a directional decision around them.</span>,
    countKey: 'kumo_twists',
    Table: KumoTwistTable,
  },
  {
    id: 'balance',
    name: 'Balance / Imbalance',
    desc: 'Price distance from Kijun equilibrium across all coins',
    accent: '#888',
    tip: <span>The Kijun represents equilibrium. Extended (&gt;+15%) = reversion likely. Balanced (±5%) = cleanest launching point for the next move.</span>,
    countKey: 'balance_map',
    Table: BalanceTable,
  },
];

function BEventCard({ card, data, tf, isActive, onActivate }) {
  const count = filterTF(data?.[card.countKey], tf).length;
  return (
    <div
      className={'scanner-card b-event-card' + (isActive ? ' active' : '')}
      style={{ '--accent': card.accent }}
      onClick={(e) => {
        if (e.target.closest('.info-tip,.tip-bubble')) return;
        onActivate();
      }}
      title={isActive ? '' : 'Click to view results'}
    >
      <div className="sc-head">
        <div className="sc-title-row">
          <div className="sc-name">{card.name}<InfoTip size="md">{card.tip}</InfoTip></div>
          {isActive && <span className="sc-active-dot mono" style={{ color: card.accent }}>● ACTIVE</span>}
        </div>
        <div className="sc-desc">{card.desc}</div>
      </div>
      <div style={{ flex: 1 }} />
      <div className="sc-foot" style={{ justifyContent: 'space-between', alignItems: 'center' }}>
        <span className="mono dim" style={{ fontSize: 11 }}>
          {data ? (count > 0 ? <span style={{ color: card.accent, fontWeight: 600 }}>{count} active</span> : 'none') : '…'}
        </span>
        <span className="mono dim" style={{ fontSize: 10 }}>
          {data?.scanned_at ? new Date(data.scanned_at).toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', hour12: true }) : ''}
        </span>
      </div>
    </div>
  );
}

// ── Top-level DashboardB ──────────────────────────────────────────────────────

function DashboardB({ tf }) {
  const data = useEvents();
  const [activeCard, setActiveCard] = useSt('transition');

  const active = B_CARDS.find(c => c.id === activeCard);

  return (
    <div className="dash-b-area">

      {/* Card grid — mirrors Dashboard A's scanner grid */}
      <section className="scanner-grid">
        {B_CARDS.map(card => (
          <BEventCard
            key={card.id}
            card={card}
            data={data}
            tf={tf}
            isActive={activeCard === card.id}
            onActivate={() => setActiveCard(card.id)}
          />
        ))}
      </section>

      {/* Active panel results — mirrors Dashboard A's results-area */}
      <div className="results-area">
        <div className="b-results-head">
          <span className="mono" style={{ fontWeight: 600, color: active?.accent, fontSize: 13 }}>{active?.name}</span>
          <span className="mono dim" style={{ fontSize: 11 }}>{active?.desc}</span>
        </div>
        {active && <active.Table tf={tf} />}
      </div>

      {/* MTF Event View — always visible, like Dashboard A's bottom stats */}
      <MTFEventBar data={data} />

      {/* Signal Log Panel — tracked named signals with IC stats */}
      <SignalLogPanel />
    </div>
  );
}
