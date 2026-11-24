// Dashboard B — Reversal & Event Detection
// Layout mirrors Dashboard A: card grid → click → results below.
// MTF Event View always visible at bottom (like Dashboard A's bottom stats bar).

const { useState: useSt, useEffect: useEff, useRef: useRef_B, useMemo } = React;

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
    // Always fetch fresh on mount — don't rely on potentially stale window cache
    fetch(window.API_BASE + '/api/events')
      .then(r => r.json())
      .then(d => { window.__EVENTS_DATA = d; setData(d); })
      .catch(() => {});
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

function filterEvents(list, tf, minScore) {
  let r = filterTF(list, tf);
  if (minScore > 0) r = r.filter(row => !row.bull_score || row.bull_score >= minScore);
  return r;
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

function TransitionTable({ tf, minScore = 0 }) {
  const data = useEvents();
  const [sort, onSort] = useSortB('bars_ago', true);
  const rows = [...filterEvents(data?.transition_events, tf, minScore)].sort((a, b) => {
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

function RetestTable({ tf, minScore = 0 }) {
  const data = useEvents();
  const [sort, onSort] = useSortB('distance_pct', true);
  const rows = [...filterEvents(data?.retest_alerts, tf, minScore)].sort((a, b) => {
    if (a.group !== b.group) return a.group < b.group ? -1 : 1;
    const v = sort.col === 'distance_pct' ? a.distance_pct - b.distance_pct : b.bull_score - a.bull_score;
    return sort.asc ? v : -v;
  });
  const levelColor = l => l === 'CLOUD BOTTOM' ? '#ff3860' : l === 'CLOUD TOP' ? '#ffaa00' : '#4fc3f7';
  const levelLabel = l => ({
    'TK': 'Tenkan (9-bar)', 'KJ': 'Kijun (26-bar)',
    'CLOUD TOP': 'Cloud Top', 'CLOUD BOTTOM': 'Cloud Bottom ⚠',
  }[l] || l);
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
            <td className="mono" style={{ color: levelColor(r.level) }}>{levelLabel(r.level)}</td>
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

function BalanceTable({ tf, minScore = 0 }) {
  const data = useEvents();
  const rows = [...filterEvents(data?.balance_map, tf, minScore)].sort((a, b) => Math.abs(b.kj_distance_pct) - Math.abs(a.kj_distance_pct));
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

function KumoTwistTable({ tf, minScore = 0 }) {
  const data = useEvents();
  const [sort, onSort] = useSortB('bars_until_twist', true);
  const rows = [...filterEvents(data?.kumo_twists, tf, minScore)].sort((a, b) => {
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
        <th><AbbTip id="COL_PRICE_POS">Price Pos</AbbTip></th>
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
            <td className="mono" style={{ fontSize: 10, color: r.price_position === 'ABOVE' ? '#00ff88' : r.price_position === 'BELOW' ? '#ff3860' : '#7c3aed' }}>
              {r.price_position || r.cloud_position || '—'}
            </td>
            <td className="mono" style={{ color: scoreColor(r.bull_score || 0) }}>{r.bull_score ?? '—'}</td>
            <td className="mono dim" style={{ fontSize: 10 }}>{r.action_note}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function E2ETable({ tf, minScore = 0 }) {
  const data = useEvents();
  const [showAbove, setShowAbove] = useSt(false);
  const [sort, onSort] = useSortB('cloud_thickness_pct', false);
  let rows = filterEvents(data?.e2e_opportunities, tf, minScore);
  if (!showAbove) rows = rows.filter(r => r.direction === 'FROM_BELOW');
  rows = [...rows].sort((a, b) => {
    const v = sort.col === 'cloud_thickness_pct' ? b.cloud_thickness_pct - a.cloud_thickness_pct : b.target_pct - a.target_pct;
    return sort.asc ? v : -v;
  });
  return (
    <>
      <div style={{
        background: '#7c3aed12', border: '1px solid #7c3aed33',
        borderRadius: 5, padding: '7px 12px', marginBottom: 10,
        fontFamily: 'JetBrains Mono,monospace', fontSize: 11, color: '#888', lineHeight: 1.6,
      }}>
        <span style={{ color: '#c4b5fd', fontWeight: 600 }}>Entry</span> first close inside cloud ·{' '}
        <span style={{ color: '#c4b5fd', fontWeight: 600 }}>Target</span> opposite cloud edge ·{' '}
        <span style={{ color: '#ff386099', fontWeight: 600 }}>Invalidated</span> price closes back outside cloud from entry side
      </div>
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

function CloudCurlingTable({ tf, minScore = 0 }) {
  const data = useEvents();
  const STATE_ORDER = { JUST_TWISTED: 0, IMMINENT: 1, EARLY: 2 };
  const [sort, onSort] = useSortB('state', true);
  const rows = [...filterEvents(data?.cloud_curling, tf, minScore)].sort((a, b) => {
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
                style={{ borderLeftColor: e.color || '#888', cursor: 'pointer' }}
                onClick={() => {
                  window.__openToken?.((e.symbol || '').replace('/USDT', ''));
                  onClose();
                }}>
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

const EXIT_LABELS = {
  'PROFIT_TARGET':             '✅ Hit profit target',
  'E2E_PROFIT_CLOUD_TOP':      '✅ Hit cloud target (E2E)',
  'TRAIL_STOP_4ATR':           '🛑 Trailing stop hit',
  'TRAIL_STOP_6ATR':           '🛑 Trailing stop hit',
  'COMBO_TIGHT_STOP':          '🛑 Trailing stop hit',
  'TIMEOUT':                   '⏱ Max hold time reached',
  'KJ_BREAK_RETEST_FAILED':    '🛑 Kijun broke down',
  'BREAKOUT_FAILED_BACK_TO_KJ':'🛑 Breakout reversed to Kijun',
  'E2E_EXIT_CLOUD_BELOW':      '🛑 Fell through cloud bottom',
  'LEVEL_RETEST_FAILED':       '🛑 Level support failed',
  'CHIKOU_LEVEL_BREAK':        '🛑 Chikou level broke',
};
function exitLabel(cond) {
  if (!cond) return '—';
  return EXIT_LABELS[cond] || cond.replace(/_/g, ' ').toLowerCase();
}
const SIGNAL_DESCS = {
  1: 'Sanyaku — All three lines (Tenkan, Kijun, Senkou) converge above cloud with price above all. Strongest alignment signal.',
  2: 'Balanced Breakout — Price breaks above a flat or rising cloud with momentum confirmation. Trend initiation setup.',
  3: 'KJ Break Retest — Price broke the Kijun and returned to retest it as support. Second-entry long on the Kijun from cloud side.',
  4: 'E2E (Edge-to-Edge) — Price enters cloud from outside; trades target the opposite cloud edge. Cloud is the range.',
  5: 'Twist Breakout — Senkou A/B crossover (kumo twist) with price breaking above the newly formed cloud.',
  6: 'Cloud Curling — Senkou B transitions from flat/declining to rising, signalling a structural shift in trend.',
  7: 'Four-Level Retest — All four key Ichimoku levels (Tenkan, Kijun, Senkou A, Senkou B) converge and act as support.',
  9: 'Chikou S/R Retest — Chikou span (lagging line) retests prior price support or resistance 26 bars back.',
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

// ── Binance live price feed ───────────────────────────────────────────────────
// Opens a single combined WebSocket for all unique symbols, returns a map of
// { "BTCUSDT": 67123.45, ... } updated in real time.
function useLivePrices(symbols) {
  const [prices, setPrices] = useSt({});

  useEff(() => {
    if (!symbols || !symbols.length) return;
    const uniq = [...new Set(symbols.map(s => s.toUpperCase()))];
    const streams = uniq.map(s => s.toLowerCase() + '@miniTicker').join('/');
    const url = 'wss://stream.binance.com:9443/stream?streams=' + streams;
    let ws;
    let dead = false;

    function connect() {
      ws = new WebSocket(url);
      ws.onmessage = (ev) => {
        try {
          const { data } = JSON.parse(ev.data);
          if (data && data.c && data.s) {
            setPrices(prev => ({ ...prev, [data.s]: parseFloat(data.c) }));
          }
        } catch {}
      };
      ws.onerror = () => {};
      ws.onclose = () => { if (!dead) setTimeout(connect, 3000); };
    }

    connect();
    return () => { dead = true; try { ws.close(); } catch {} };
  }, [symbols.join(',')]);

  return prices;
}

// ── CoinGecko fallback price feed (30s poll, top 500 by mkt cap) ─────────────
function useCoingeckoPrices() {
  const [cgPrices, setCgPrices] = useSt({});

  useEff(() => {
    const fetchPage = (page) =>
      fetch(`https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&order=market_cap_desc&per_page=250&page=${page}`)
        .then(r => r.json()).catch(() => []);

    const load = async () => {
      try {
        const [p1, p2] = await Promise.all([fetchPage(1), fetchPage(2)]);
        const map = {};
        for (const c of [...(p1 || []), ...(p2 || [])]) {
          if (c.symbol && c.current_price) {
            map[c.symbol.toUpperCase() + 'USDT'] = c.current_price;
          }
        }
        setCgPrices(map);
      } catch {}
    };

    load();
    const id = setInterval(load, 30000);
    return () => clearInterval(id);
  }, []);

  return cgPrices;
}

// Merge Binance WS prices (real-time) with CoinGecko fallback (30s poll).
// WS price wins when available; CG fills the gap for non-Binance tokens.
function usePrices(symbols) {
  const wsPrices = useLivePrices(symbols);
  const cgPrices = useCoingeckoPrices();
  return useMemo(() => {
    const merged = { ...cgPrices };
    for (const [k, v] of Object.entries(wsPrices)) merged[k] = v;
    return merged;
  }, [wsPrices, cgPrices]);
}

function fmtPrice(p) {
  if (p == null) return '—';
  if (p >= 1000) return p.toLocaleString(undefined, { maximumFractionDigits: 2 });
  if (p >= 1)    return p.toLocaleString(undefined, { maximumFractionDigits: 4 });
  return p.toLocaleString(undefined, { maximumFractionDigits: 6 });
}

function LivePnL({ entryPrice, livePrice }) {
  if (!livePrice || !entryPrice) return <span className="mono dim">—</span>;
  const pct = (livePrice - entryPrice) / entryPrice * 100;
  const color = pct > 0 ? '#00ff88' : pct < 0 ? '#ff3860' : '#888';
  return (
    <span className="mono" style={{ color, fontSize: 11, fontWeight: 600 }}>
      {pct > 0 ? '+' : ''}{pct.toFixed(2)}%
    </span>
  );
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

// ── Per-row helpers ───────────────────────────────────────────────────────────

function sigCoin(symbol) {
  const sym = (symbol || '').replace(/USDT$/, '');
  return window.ICHI_DATA?.COINS?.find(c => c.sym === sym) ?? null;
}

function ScoreNow({ symbol }) {
  const coin = sigCoin(symbol);
  if (!coin) return <span className="mono dim">—</span>;
  const t = coin.scoreTrend;
  return (
    <span>
      <span className="mono" style={{ color: scoreColor(coin.score1d) }}>{coin.score1d}</span>
      {t > 1 && <span style={{ color: '#00ff88', fontSize: 10, marginLeft: 2 }}>↑</span>}
      {t < -1 && <span style={{ color: '#ff3860', fontSize: 10, marginLeft: 2 }}>↓</span>}
    </span>
  );
}

function rowRiskTier(r) {
  const wl = (() => { try { return JSON.parse(r.warning_log || '[]'); } catch { return []; } })();
  return wl.reduce((m, w) => Math.max(m, w.tier || 0), 0);
}

function RiskBadge({ tier }) {
  const color = tier >= 2 ? '#ff3860' : tier >= 1 ? '#ffaa00' : '#00ff88';
  const label = tier >= 2 ? 'RED' : tier >= 1 ? 'AMBER' : 'OK';
  return <span className="mono fw6" style={{ fontSize: 10, color }}>{label}</span>;
}

function TierBadge({ tier }) {
  if (!tier) return null;
  const cfg = {
    1: { label: 'T1', color: '#fbbf24', bg: '#fbbf2420', border: '#fbbf2455', title: 'Tier 1 — BTC above cloud + QS 60+ + Hosoda. +20.7% avg/trade, 53.9% win rate.' },
    2: { label: 'T2', color: '#f97316', bg: '#f9731620', border: '#f9731655', title: 'Tier 2 — BTC above cloud + QS 60+. +22.6% avg/trade, 51.2% win rate.' },
    3: { label: 'T3', color: '#4ade80', bg: '#4ade8020', border: '#4ade8055', title: 'Tier 3 — BTC above cloud, all quality. +9.8% avg/trade, 44.8% win rate.' },
  }[tier];
  if (!cfg) return null;
  return (
    <span title={cfg.title} style={{
      fontSize: 9, fontFamily: 'JetBrains Mono,monospace', fontWeight: 700,
      padding: '1px 5px', borderRadius: 3, marginRight: 4,
      background: cfg.bg, border: `1px solid ${cfg.border}`, color: cfg.color,
      cursor: 'help',
    }}>{cfg.label}</span>
  );
}

// ── Track classification (mirrors Python _classify_track) ─────────────────────
function classifyTrack(r) {
  const tf         = r.timeframe || '';
  const tier       = r.tier;
  const btcRegime  = r.btc_regime || ((() => { try { return JSON.parse(r.signal_metadata || '{}'); } catch { return {}; } })().filter || {}).btc_regime;
  const chikouOk   = r.chikou_ok;
  const qs         = parseFloat(r.quality_score) || 0;
  const bullScore  = parseInt(r.bull_score) || 0;
  const sigType    = r.signal_type;

  if (tf === '1d' && (tier === 1 || tier === 2) && btcRegime === 'above') return 'CONFIRMED';
  if (tf === '1d' && chikouOk && qs >= 60 && (btcRegime === 'below' || btcRegime === 'inside')) return 'RECOVERY';
  if (tf === '4h' && tier === 1 && bullScore >= 16) return '4H-QUALITY';
  if (sigType === 4) return 'WATCH';
  return null;
}

function TrackBadge({ track }) {
  if (!track) return <span className="mono dim" style={{ fontSize: 9 }}>—</span>;
  const cfg = {
    'CONFIRMED':  { color: '#00ff88', bg: '#00ff8815', label: 'CONFIRMED',  title: '1d T1/T2, BTC above cloud. 59% win, +9.9% median.' },
    'RECOVERY':   { color: '#ffaa00', bg: '#ffaa0015', label: 'RECOVERY',   title: '1d chikou_ok + QS≥60, BTC below/inside. 44% win, +24% avg.' },
    '4H-QUALITY': { color: '#38bdf8', bg: '#38bdf815', label: '4H-QUALITY', title: '4h T1 + bull_score≥16. 63% win, +6.2% median.' },
    'WATCH':      { color: '#888',    bg: '#88888815', label: 'WATCH',      title: 'E2E in uncertain BTC regime — do not trade yet.' },
  }[track];
  if (!cfg) return null;
  return (
    <span title={cfg.title} style={{
      fontSize: 9, fontFamily: 'JetBrains Mono,monospace', fontWeight: 700,
      padding: '2px 5px', borderRadius: 3,
      background: cfg.bg, border: `1px solid ${cfg.color}50`, color: cfg.color,
      whiteSpace: 'nowrap', cursor: 'help',
    }}>{cfg.label}</span>
  );
}

function BtcRegimePill({ regime }) {
  if (!regime || regime === 'unknown') return null;
  const cfg = {
    'above':  { color: '#00ff88', label: '▲ BTC', title: 'BTC above cloud — bull market' },
    'inside': { color: '#ffaa00', label: '◈ BTC', title: 'BTC inside cloud — uncertain' },
    'below':  { color: '#ff3860', label: '▼ BTC', title: 'BTC below cloud — bear market' },
  }[regime];
  if (!cfg) return null;
  return (
    <span title={cfg.title} style={{
      fontSize: 9, fontFamily: 'JetBrains Mono,monospace', fontWeight: 600,
      padding: '2px 4px', borderRadius: 3,
      background: cfg.color + '15', border: `1px solid ${cfg.color}45`, color: cfg.color,
      cursor: 'help',
    }}>{cfg.label}</span>
  );
}

function fmtDateTime(iso) {
  if (!iso) return '—';
  try {
    const d = new Date(iso);
    const date = d.toLocaleDateString([], { month: 'short', day: 'numeric' });
    const time = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false });
    return `${date} ${time}`;
  } catch { return '—'; }
}

function SignalTypeBadge({ type, subtype }) {
  const name = SIGNAL_NAMES[type] || `Sig ${type}`;
  const desc = SIGNAL_DESCS[type] || '';
  const sub  = subtype ? subtype.replace(String(type), '') : '';
  return (
    <span title={desc} style={{
      fontSize: 10, fontFamily: 'JetBrains Mono,monospace',
      padding: '1px 5px', borderRadius: 3, marginRight: 4,
      background: '#7c3aed20', border: '1px solid #7c3aed55', color: '#c4b5fd',
      cursor: desc ? 'help' : 'default',
    }}>{name}{sub}</span>
  );
}

function SigReturnCell({ val, label }) {
  if (val == null) return <span className="mono dim">—</span>;
  const color = val > 0 ? '#00ff88' : val < 0 ? '#ff3860' : '#888';
  return <span className="mono" style={{ color }}>{val > 0 ? '+' : ''}{val.toFixed(1)}%{label ? <span className="dim" style={{ fontSize: 9 }}> {label}</span> : null}</span>;
}

// ── Filters ───────────────────────────────────────────────────────────────────

function SignalFilterBar({ availTypes, filters, onChange }) {
  const TFS = ['4h', '1d', '1w'];
  return (
    <div style={{
      display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center',
      marginBottom: 10, padding: '6px 10px',
      background: '#ffffff05', borderRadius: 5, border: '1px solid #ffffff0a',
    }}>
      <div style={{ display: 'flex', gap: 3, alignItems: 'center', flexWrap: 'wrap' }}>
        <span className="mono dim" style={{ fontSize: 10, marginRight: 2 }}>Type:</span>
        <button className={'dashb-tf-btn mono' + (!filters.type ? ' active' : '')} style={{ fontSize: 9.5, padding: '1px 7px' }} onClick={() => onChange({ ...filters, type: 0 })}>ALL</button>
        {[1,2,3,4,5,6,7,9].filter(t => availTypes.has(t)).map(t => (
          <button key={t} className={'dashb-tf-btn mono' + (filters.type === t ? ' active' : '')} style={{ fontSize: 9.5, padding: '1px 7px' }}
            onClick={() => onChange({ ...filters, type: filters.type === t ? 0 : t })}>
            {SIGNAL_NAMES[t] || `Sig ${t}`}
          </button>
        ))}
      </div>
      <div style={{ display: 'flex', gap: 3, alignItems: 'center' }}>
        <span className="mono dim" style={{ fontSize: 10, marginRight: 2 }}>TF:</span>
        <button className={'dashb-tf-btn mono' + (!filters.tf ? ' active' : '')} style={{ fontSize: 9.5, padding: '1px 7px' }} onClick={() => onChange({ ...filters, tf: '' })}>ALL</button>
        {TFS.map(tf => (
          <button key={tf} className={'dashb-tf-btn mono' + (filters.tf === tf ? ' active' : '')} style={{ fontSize: 9.5, padding: '1px 7px' }}
            onClick={() => onChange({ ...filters, tf: filters.tf === tf ? '' : tf })}>
            {tf}
          </button>
        ))}
      </div>
      <button className={'dashb-tf-btn mono' + (filters.hosoda ? ' active' : '')} style={{ fontSize: 9.5, padding: '1px 7px' }}
        onClick={() => onChange({ ...filters, hosoda: !filters.hosoda })}>
        ⚡ Hosoda only
      </button>
      <button className={'dashb-tf-btn mono' + (filters.score13 ? ' active' : '')} style={{ fontSize: 9.5, padding: '1px 7px' }}
        onClick={() => onChange({ ...filters, score13: !filters.score13 })}>
        Score ≥13
      </button>
    </div>
  );
}

function applySignalFilters(rows, filters) {
  let r = rows;
  if (filters.type) r = r.filter(x => x.signal_type === filters.type);
  if (filters.tf) r = r.filter(x => x.timeframe === filters.tf);
  if (filters.hosoda) r = r.filter(x => x.hosoda_active);
  if (filters.score13) r = r.filter(x => (sigCoin(x.symbol)?.score1d ?? 0) >= 13);
  return r;
}

// ── Open signals table ────────────────────────────────────────────────────────

function SignalOpenTable({ rows, prices }) {
  const [expanded, setExpanded] = useSt(null);
  const [filters, setFilters] = useSt({ type: 0, tf: '', hosoda: false, score13: false });
  const [sortRisk, setSortRisk] = useSt(true);

  const availTypes = new Set(rows.map(r => r.signal_type));
  const filtered = applySignalFilters(rows, filters);

  const sorted = [...filtered].sort((a, b) => {
    if (sortRisk) {
      const riskDiff = rowRiskTier(b) - rowRiskTier(a);
      if (riskDiff !== 0) return riskDiff;
    }
    return (b.days_open ?? 0) - (a.days_open ?? 0);
  });

  if (!rows.length) return <DBEmptyState msg="No open signal instances." />;

  return (
    <>
      <SignalFilterBar availTypes={availTypes} filters={filters} onChange={setFilters} />
      <div style={{ marginBottom: 8 }}>
        <button className={'dashb-tf-btn mono' + (sortRisk ? ' active' : '')} style={{ fontSize: 10 }}
          onClick={() => setSortRisk(v => !v)}>
          {sortRisk ? '✓ Risk-first sort' : 'Sort by risk first'}
        </button>
      </div>
      {!filtered.length
        ? <DBEmptyState msg="No signals match the current filters." />
        : (
          <div style={{ overflowX: 'auto' }}>
            <table className="db-table">
              <thead><tr>
                <th>Signal</th><th>Coin</th><th>TF</th><th>When</th>
                <th title="Price when the signal fired">Entry</th>
                <th title="Current price — Binance WS or CoinGecko fallback">Price Now</th>
                <th title="Current gain or loss from entry">Live P&L</th>
                <th title="Signal quality score (0–100) based on which rules historically predict good outcomes for this signal type">Quality</th>
                <th title="Approximate ATR trail stop price at entry — rough guide only">~Stop</th>
                <th title="7-day price move since signal fired">7d Move</th>
                <th title="30-day price move since signal fired">30d Move</th>
                <th>Status</th>
                <th title="⚡ = extra candle pattern confirmed this signal">⚡</th>
                <th title="Two different signal types fired on the same coin around the same time">×2</th>
                <th title="How many days since this signal fired without closing">Days Open</th>
                <th title="Worst dip below entry price so far while this trade has been open">Worst Dip</th>
                <th title="Best gain above entry price reached so far while this trade has been open">Best Gain</th>
                <th title="OK = no warning signs · AMBER = one warning · RED = multiple warnings since entry">Risk</th>
              </tr></thead>
              <tbody>
                {sorted.map((r, i) => {
                  const tier = rowRiskTier(r);
                  const meta = (() => { try { return JSON.parse(r.signal_metadata || '{}'); } catch { return {}; } })();
                  const wl   = (() => { try { return JSON.parse(r.warning_log || '[]'); } catch { return []; } })();
                  const sym = (r.symbol || '').replace('USDT', '');
                  const rowClass = 'db-tr' + (tier >= 2 ? ' db-tr-red' : tier >= 1 ? ' db-tr-amber' : '');
                  const filtOpen = meta.filter || {};
                  return (
                    <React.Fragment key={r.signal_id || i}>
                      <tr className={rowClass} style={{ cursor: 'pointer' }}
                        onClick={() => setExpanded(p => p === (r.signal_id || i) ? null : (r.signal_id || i))}>
                        <td className="mono dim" style={{ fontSize: 10 }}>
                          <TierBadge tier={filtOpen.tier} />
                          <SignalTypeBadge type={r.signal_type} subtype={r.signal_subtype} />
                          {SIGNAL_NAMES[r.signal_type] || '—'}
                        </td>
                        <td className="mono fw6">
                          <span className="clickable" onClick={e => { e.stopPropagation(); window.__openToken?.(sym); }}>{sym}</span>
                        </td>
                        <td><TFBadge tf={r.timeframe} /></td>
                        <td className="mono dim" style={{ fontSize: 10 }}>{fmtRelTime(r.fired_at)}</td>
                        <td className="mono dim" style={{ fontSize: 10 }}>{r.entry_price ? fmtPrice(Number(r.entry_price)) : '—'}</td>
                        <td className="mono dim" style={{ fontSize: 11 }}>
                          {prices?.[r.symbol] ? fmtPrice(prices[r.symbol]) : '—'}
                        </td>
                        <td>
                          {r.entry_price ? <LivePnL entryPrice={parseFloat(r.entry_price)} livePrice={prices?.[r.symbol]} /> : <span className="mono dim">—</span>}
                        </td>
                        <td>
                          {r.quality_score > 0
                            ? <span className="mono" style={{ color: qualityColor(r.quality_score), fontSize: 11, fontWeight: 600 }}
                                title={qualityLabel(r.quality_score)}>
                                {Math.round(r.quality_score)}
                              </span>
                            : <span className="mono dim" style={{ fontSize: 10 }}>—</span>}
                        </td>
                        <td className="mono" style={{ fontSize: 10, color: '#ff386070' }}>
                          {r.trail_stop_approx ? fmtPrice(r.trail_stop_approx) : '—'}
                        </td>
                        <td><SigReturnCell val={r.return_7d} /></td>
                        <td><SigReturnCell val={r.return_30d} /></td>
                        <td><span className="mono" style={{ fontSize: 10, color: '#00ff88', fontWeight: 600 }}>Active</span></td>
                        <td style={{ textAlign: 'center' }}>{r.hosoda_active ? <span title="Extra candle pattern confirmed">⚡</span> : '—'}</td>
                        <td style={{ textAlign: 'center' }}>{r.cooccurrence_count > 0 ? <span title="Two signal types fired on this coin around the same time" style={{ fontSize: 9, background: '#ffaa0020', border: '1px solid #ffaa0055', color: '#ffaa00', borderRadius: 3, padding: '1px 4px', fontFamily: 'JetBrains Mono,monospace' }}>×2</span> : '—'}</td>
                        <td className="mono dim">{r.days_open != null ? r.days_open + 'd' : '—'}</td>
                        <td className="mono" style={{ fontSize: 10, color: r.mae != null ? (r.mae < -5 ? '#ff3860' : r.mae < -2 ? '#ffaa00' : '#888') : '#555' }}>
                          {r.mae != null ? (r.mae > 0 ? '+' : '') + r.mae.toFixed(1) + '%' : '—'}
                        </td>
                        <td className="mono" style={{ fontSize: 10, color: r.mfe != null ? '#00ff88' : '#555' }}>
                          {r.mfe != null ? '+' + r.mfe.toFixed(1) + '%' : '—'}
                        </td>
                        <td><RiskBadge tier={tier} /></td>
                      </tr>
                      {expanded === (r.signal_id || i) && (
                        <tr className="db-tr-expand">
                          <td colSpan={19} style={{ paddingLeft: 20, paddingBottom: 10, paddingTop: 6 }}>
                            <div style={{ display: 'flex', gap: 32, flexWrap: 'wrap', fontSize: 11 }}>
                              {filtOpen.tier && (
                                <div>
                                  <div className="mono dim" style={{ fontSize: 10, marginBottom: 4 }}>Filter / Tier</div>
                                  <div className="mono dim" style={{ fontSize: 10, lineHeight: 1.9 }}>
                                    <div>Tier: <TierBadge tier={filtOpen.tier} /></div>
                                    <div>BTC regime: <span style={{ color: filtOpen.btc_regime === 'above' ? '#00ff88' : filtOpen.btc_regime === 'below' ? '#ff3860' : '#ffaa00' }}>{filtOpen.btc_regime || '—'}</span></div>
                                    <div>Chikou: <span style={{ color: filtOpen.chikou_ok ? '#00ff88' : '#888' }}>{filtOpen.chikou_ok ? '✓ confirmed' : 'not confirmed'}</span></div>
                                    <div>Cloud thickness: <span style={{ color: filtOpen.cloud_thickness >= 15 ? '#00ff88' : filtOpen.cloud_thickness >= 5 ? '#ffaa00' : '#888' }}>{filtOpen.cloud_thickness != null ? filtOpen.cloud_thickness.toFixed(1) + '%' : '—'}</span></div>
                                    {filtOpen.twist && <div>Twist: <span style={{ color: filtOpen.twist.bucket === 'bearish_6_10' ? '#00ff88' : filtOpen.twist.bucket === 'bullish_0_5' ? '#ff3860' : '#888' }}>{filtOpen.twist.direction} {filtOpen.twist.bars_ago}b ago</span></div>}
                                    {filtOpen.atr_pct > 0 && <div>ATR%: <span style={{ color: filtOpen.atr_pct >= 5 ? '#00ff88' : '#888' }}>{filtOpen.atr_pct.toFixed(1)}%</span></div>}
                                    {filtOpen.eth_boost && <div style={{ color: '#fbbf24' }}>⚡ ETH consolidating — alt conditions strong</div>}
                                    {filtOpen.priority_boost && !filtOpen.eth_boost && <div style={{ color: '#fbbf24' }}>⚡ Bearish twist 6-10b ago</div>}
                                  </div>
                                </div>
                              )}
                              {Object.keys(meta).filter(k => k !== 'filter').length > 0 && (
                                <div>
                                  <div className="mono dim" style={{ fontSize: 10, marginBottom: 4 }}>Metadata</div>
                                  {Object.entries(meta).filter(([k]) => k !== 'filter').map(([k, v]) => (
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
                      )}
                    </React.Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
        )
      }
    </>
  );
}

// ── Performance table ─────────────────────────────────────────────────────────

function SignalPerfTable({ stats }) {
  if (!stats || !stats.length) return <DBEmptyState msg="No performance data yet. Run a backfill to generate historical signal instances." />;

  const gradeColor = g => g === 'STRONG' ? '#00ff88' : g === 'MODERATE' ? '#ffaa00' : g === 'WEAK' ? '#ff3860' : '#555';
  const sufficient = stats.filter(s => s.n_instances >= 20);
  const developing = stats.filter(s => s.n_instances < 20);
  const [showDev, setShowDev] = useSt(false);

  const PerfRows = ({ rows }) => rows.map((r, i) => (
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
      {/* QS60+ filtered columns */}
      <td className="mono" style={{ fontSize: 10, color: (r.win_rate_qs60 || 0) >= 0.6 ? '#00ff88' : (r.win_rate_qs60 || 0) >= 0.5 ? '#ffaa00' : r.win_rate_qs60 != null ? '#888' : '#333' }}>
        {r.win_rate_qs60 != null
          ? <>{(r.win_rate_qs60 * 100).toFixed(1)}% <span className="dim" style={{ fontSize: 9 }}>({r.n_closed_qs60})</span></>
          : <span style={{ color: '#333' }}>—</span>}
      </td>
      <td className="mono" style={{ fontSize: 10, color: r.mean_exit_return_qs60 != null ? (r.mean_exit_return_qs60 > 15 ? '#00ff88' : r.mean_exit_return_qs60 > 5 ? '#ffaa00' : '#ff3860') : '#333' }}>
        {r.mean_exit_return_qs60 != null
          ? (r.mean_exit_return_qs60 > 0 ? '+' : '') + r.mean_exit_return_qs60.toFixed(1) + '%'
          : <span style={{ color: '#333' }}>—</span>}
      </td>
      <td className="mono" style={{ fontSize: 10, color: (r.win_loss_ratio_qs60 || 0) >= 1.5 ? '#00ff88' : (r.win_loss_ratio_qs60 || 0) >= 1.0 ? '#ffaa00' : r.win_loss_ratio_qs60 != null ? '#888' : '#333' }}>
        {r.win_loss_ratio_qs60 != null ? r.win_loss_ratio_qs60.toFixed(2) : <span style={{ color: '#333' }}>—</span>}
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
  ));

  const TableShell = ({ children }) => (
    <div style={{ overflowX: 'auto', marginBottom: 16 }}>
      <table className="db-table">
        <thead><tr>
          <th>Signal Type</th>
          <th title="Total number of times this signal has ever fired (from history + live scans)">Times Fired</th>
          <th title="How many of those trades have actually closed (hit an exit condition)">Closed</th>
          <th title="On average, how much did the price move 30 days after this signal fired?">Avg 30d Move</th>
          <th title="Out of all closed trades, what % finished in profit? (all signals, unfiltered)">Win Rate</th>
          <th title="Average winning trade size divided by average losing trade size. (all signals, unfiltered)">Win/Loss Size</th>
          <th title="Win rate for QS≥60 signals only — higher quality signals after the IC filter. Number in brackets = sample size." style={{ color: '#fbbf24' }}>QS60+ Win%</th>
          <th title="Average exit return for QS≥60 signals — what a typical filtered trade returned when it closed." style={{ color: '#fbbf24' }}>QS60+ Avg Return</th>
          <th title="Win/Loss ratio for QS≥60 signals only." style={{ color: '#fbbf24' }}>QS60+ W/L</th>
          <th title="How many price bars on average until the trade closed">Avg Duration</th>
          <th title="On average, how far did the price dip below entry before the trade closed?">Avg Worst Dip</th>
          <th title="75% of trades had a worst dip no worse than this — useful for deciding stop loss or position size">Worst Dip (75th%)  </th>
          <th title="Suggested max leverage based on the 75th% worst dip. Keeps your max loss around 50% of position size.">Safe Leverage</th>
          <th title="Does this signal perform better when the extra candle pattern (⚡) is also present?">⚡ Pattern Boost</th>
          <th title="STRONG = clear edge with good stats · MODERATE = some edge · WEAK = poor edge · NOT ENOUGH DATA = fewer than 20 trades">Overall Grade</th>
        </tr></thead>
        <tbody>{children}</tbody>
      </table>
    </div>
  );

  return (
    <>
      {sufficient.length > 0 && (
        <>
          <div style={{
            fontFamily: 'JetBrains Mono,monospace', fontSize: 11, color: '#00ff88',
            padding: '5px 10px', marginBottom: 8,
            background: '#00ff8808', border: '1px solid #00ff8822', borderRadius: 5,
          }}>
            ✓ Validated — {sufficient.length} signal type{sufficient.length !== 1 ? 's' : ''} with ≥20 instances
          </div>
          <TableShell><PerfRows rows={sufficient} /></TableShell>
        </>
      )}
      {developing.length > 0 && (
        <>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8 }}>
            <div style={{
              fontFamily: 'JetBrains Mono,monospace', fontSize: 11, color: '#555',
              padding: '5px 10px', flex: 1,
              background: '#ffffff05', border: '1px solid #ffffff0f', borderRadius: 5,
            }}>
              ○ Building — {developing.length} signal type{developing.length !== 1 ? 's' : ''} with &lt;20 instances · results not statistically reliable
            </div>
            <button className="dashb-tf-btn mono" style={{ fontSize: 10 }}
              onClick={() => setShowDev(v => !v)}>
              {showDev ? 'Hide' : 'Show'}
            </button>
          </div>
          {showDev && (
            <div style={{ opacity: 0.6 }}>
              <TableShell><PerfRows rows={developing} /></TableShell>
            </div>
          )}
        </>
      )}
    </>
  );
}

// ── Shared expanded filter panel (used by Setups + Open) ─────────────────────

function FilterExpandPanel({ meta, row }) {
  const filt = (meta || {}).filter || {};
  return (
    <div style={{ display: 'flex', gap: 28, flexWrap: 'wrap', fontSize: 11 }}>
      <div>
        <div className="mono dim" style={{ fontSize: 10, marginBottom: 4 }}>Entry Details</div>
        <div className="mono dim" style={{ fontSize: 10, lineHeight: 2 }}>
          <div>Fired: <span style={{ color: '#e0e0e0' }}>{fmtRelTime(row.fired_at)}</span></div>
          <div>Entry: <span style={{ color: '#e0e0e0' }}>{row.entry_price ? fmtPrice(Number(row.entry_price)) : '—'}</span></div>
          {row.trail_stop_approx && <div>~Trail stop: <span style={{ color: '#ff3860' }}>{fmtPrice(row.trail_stop_approx)}</span> <span className="dim" style={{ fontSize: 9 }}>(ATR-based estimate)</span></div>}
          {row.return_7d != null && <div>7d move: <SigReturnCell val={row.return_7d} /></div>}
          {row.return_30d != null && <div>30d move: <SigReturnCell val={row.return_30d} /></div>}
          {row.mae != null && <div>Worst dip: <span style={{ color: row.mae < -5 ? '#ff3860' : '#888' }}>{row.mae.toFixed(1)}%</span></div>}
          {row.mfe != null && <div>Best gain: <span style={{ color: '#00ff88' }}>+{row.mfe.toFixed(1)}%</span></div>}
        </div>
      </div>
      {filt.tier && (
        <div>
          <div className="mono dim" style={{ fontSize: 10, marginBottom: 4 }}>Filter / Tier</div>
          <div className="mono dim" style={{ fontSize: 10, lineHeight: 2 }}>
            <div>Tier: <TierBadge tier={filt.tier} /></div>
            <div>BTC regime: <span style={{ color: filt.btc_regime === 'above' ? '#00ff88' : filt.btc_regime === 'below' ? '#ff3860' : '#ffaa00' }}>{filt.btc_regime || '—'}</span></div>
            <div>Chikou: <span style={{ color: filt.chikou_ok ? '#00ff88' : '#888' }}>{filt.chikou_ok ? '✓ confirmed' : '✗ not confirmed'}</span></div>
            <div>Cloud thickness: <span style={{ color: (filt.cloud_thickness || 0) >= 15 ? '#00ff88' : (filt.cloud_thickness || 0) >= 5 ? '#ffaa00' : '#888' }}>{filt.cloud_thickness != null ? filt.cloud_thickness.toFixed(1) + '%' : '—'}</span></div>
            {filt.atr_pct > 0 && <div>ATR%: <span style={{ color: filt.atr_pct >= 5 ? '#00ff88' : '#888' }}>{filt.atr_pct.toFixed(1)}%</span></div>}
            {filt.twist && <div>Twist: <span style={{ color: filt.twist.bucket === 'bearish_6_10' ? '#00ff88' : filt.twist.bucket === 'bullish_0_5' ? '#ff3860' : '#888' }}>{filt.twist.direction} {filt.twist.bars_ago}b ago ({filt.twist.bucket.replace(/_/g,' ')})</span></div>}
            {filt.eth_boost && <div style={{ color: '#fbbf24' }}>⚡ ETH inside cloud — alt boost</div>}
            {filt.priority_boost && !filt.eth_boost && <div style={{ color: '#fbbf24' }}>⚡ Bearish twist 6-10b ago</div>}
          </div>
        </div>
      )}
      {Object.keys(meta || {}).filter(k => k !== 'filter').length > 0 && (
        <div>
          <div className="mono dim" style={{ fontSize: 10, marginBottom: 4 }}>Signal Metadata</div>
          {Object.entries(meta || {}).filter(([k]) => k !== 'filter').map(([k, v]) => (
            <div key={k} className="mono dim" style={{ fontSize: 10, lineHeight: 1.8 }}>
              {k}: <span style={{ color: '#e0e0e0' }}>{v != null ? String(v) : '—'}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Setups table ──────────────────────────────────────────────────────────────

const TF_MAX_BARS = { '4h': 3, '1d': 2, '1w': 1 };

function SetupsTable({ rows, prices }) {
  const [expanded, setExpanded] = useSt(null);

  if (!rows.length) return (
    <DBEmptyState msg="No fresh setups right now. All recent signals are outside the entry window — check Open for running trades." />
  );

  return (
    <>
      <div className="mono dim" style={{ fontSize: 10, padding: '4px 2px 10px', color: '#555' }}>
        Fresh signals still within the entry window — 4h ≤3 bars · 1d ≤2 bars · 1w ≤1 bar. Sorted by track then freshness.
      </div>
      <div style={{ overflowX: 'auto' }}>
        <table className="db-table">
          <thead><tr>
            <th title="Alert track — what to do with this signal">Track</th>
            <th>Signal</th>
            <th>Coin</th>
            <th>TF</th>
            <th title="BTC market regime at signal time">BTC</th>
            <th title="When the signal fired">Fired</th>
            <th title="How fresh the signal is relative to the maximum entry window. Green = very fresh, red = aging out.">Fresh</th>
            <th title="Price when signal fired">Entry</th>
            <th title="Current price — Binance WS for major pairs, CoinGecko for others">Now</th>
            <th title="Move from entry to current price">Move</th>
            <th title="Quality score 0–100 (IC-weighted). Higher = better rule alignment.">QS</th>
            <th title="Approx ATR trail stop at entry. Binance WS / CoinGecko price.">~Stop</th>
            <th title="⚡ Hosoda candle pattern confirmed · ×2 multiple signals on same coin">Extras</th>
            <th></th>
          </tr></thead>
          <tbody>
            {rows.map((r, i) => {
              const id = r.signal_id || i;
              const isExp = expanded === id;
              const sym = (r.symbol || '').replace('USDT', '');
              const meta = (() => { try { return JSON.parse(r.signal_metadata || '{}'); } catch { return {}; } })();
              const filt = meta.filter || {};
              const maxBars = TF_MAX_BARS[r.timeframe] || 2;
              const barsElapsed = r.bars_since_fired ?? 0;
              const freshPct = Math.min(barsElapsed / maxBars * 100, 100);
              const freshColor = freshPct < 40 ? '#00ff88' : freshPct < 75 ? '#ffaa00' : '#ff3860';
              const livePrice = prices?.[r.symbol];
              const entryPrice = r.entry_price ? Number(r.entry_price) : null;
              return (
                <React.Fragment key={id}>
                  <tr className="db-tr" style={{ cursor: 'pointer' }} onClick={() => setExpanded(p => p === id ? null : id)}>
                    <td><TrackBadge track={classifyTrack(r)} /></td>
                    <td className="mono dim" style={{ fontSize: 10, whiteSpace: 'nowrap' }}>
                      <SignalTypeBadge type={r.signal_type} subtype={r.signal_subtype} />
                      {SIGNAL_NAMES[r.signal_type] || '—'}
                    </td>
                    <td className="mono fw6">
                      <span className="clickable" onClick={e => { e.stopPropagation(); window.__openToken?.(sym); }}>{sym}</span>
                    </td>
                    <td><TFBadge tf={r.timeframe} /></td>
                    <td><BtcRegimePill regime={r.btc_regime || filt.btc_regime} /></td>
                    <td className="mono dim" style={{ fontSize: 10, whiteSpace: 'nowrap' }}>{fmtDateTime(r.fired_at)}</td>
                    <td>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                        <div style={{ width: 40, height: 4, background: '#ffffff12', borderRadius: 2 }}>
                          <div style={{ width: freshPct + '%', height: '100%', background: freshColor, borderRadius: 2, transition: 'width 0.3s' }} />
                        </div>
                        <span className="mono dim" style={{ fontSize: 9 }}>{barsElapsed}/{maxBars}b</span>
                      </div>
                    </td>
                    <td className="mono dim" style={{ fontSize: 10 }}>{entryPrice ? fmtPrice(entryPrice) : '—'}</td>
                    <td className="mono dim" style={{ fontSize: 11 }}>{livePrice ? fmtPrice(livePrice) : '—'}</td>
                    <td>{entryPrice && livePrice ? <LivePnL entryPrice={entryPrice} livePrice={livePrice} /> : <span className="mono dim">—</span>}</td>
                    <td>
                      {r.quality_score > 0
                        ? <span className="mono" style={{ color: qualityColor(r.quality_score), fontWeight: 600, fontSize: 11 }} title={qualityLabel(r.quality_score)}>{Math.round(r.quality_score)}</span>
                        : <span className="mono dim">—</span>}
                    </td>
                    <td className="mono" style={{ fontSize: 10, color: '#ff386080' }}>
                      {r.trail_stop_approx ? fmtPrice(r.trail_stop_approx) : '—'}
                    </td>
                    <td style={{ whiteSpace: 'nowrap' }}>
                      {r.hosoda_active && <span title="Hosoda candle pattern confirmed at signal">⚡</span>}
                      {r.cooccurrence_count > 0 && <span title="Multiple signal types fired on this coin" style={{ fontSize: 9, marginLeft: 3, background: '#ffaa0020', border: '1px solid #ffaa0055', color: '#ffaa00', borderRadius: 3, padding: '1px 4px', fontFamily: 'JetBrains Mono,monospace' }}>×2</span>}
                    </td>
                    <td><span className="mono dim" style={{ fontSize: 9 }}>{isExp ? '▲' : '▼'}</span></td>
                  </tr>
                  {isExp && (
                    <tr className="db-tr-expand">
                      <td colSpan={14} style={{ paddingLeft: 20, paddingBottom: 12, paddingTop: 6 }}>
                        <FilterExpandPanel meta={meta} row={{ ...r, trail_stop_approx: r.trail_stop_approx }} />
                      </td>
                    </tr>
                  )}
                </React.Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
    </>
  );
}

// ── History (closed trades) table ─────────────────────────────────────────────

function HistoryTable({ rows }) {
  const [expanded, setExpanded] = useSt(null);
  const [typeFilter, setTypeFilter] = useSt(0);
  const [tfFilter, setTfFilter] = useSt('');
  const [resultFilter, setResultFilter] = useSt('all');
  const [trackFilter, setTrackFilter] = useSt('all');

  if (!rows.length) return <DBEmptyState msg="No closed trades yet. Trades close when they hit a trail stop, profit target, or time limit." />;

  const wins   = rows.filter(r => (r.exit_return || 0) > 0);
  const losses = rows.filter(r => (r.exit_return || 0) < 0);
  const withReturn = rows.filter(r => r.exit_return != null);
  const avgReturn  = withReturn.length ? withReturn.reduce((s, r) => s + r.exit_return, 0) / withReturn.length : null;
  const winRate    = withReturn.length ? (wins.filter(r => r.exit_return != null).length / withReturn.length * 100) : null;

  const availTypes = [...new Set(rows.map(r => r.signal_type))].sort((a, b) => a - b);

  const filtered = rows.filter(r => {
    if (typeFilter && r.signal_type !== typeFilter) return false;
    if (tfFilter && r.timeframe !== tfFilter) return false;
    if (resultFilter === 'wins' && (r.exit_return || 0) <= 0) return false;
    if (resultFilter === 'losses' && (r.exit_return || 0) >= 0) return false;
    if (trackFilter !== 'all' && classifyTrack(r) !== trackFilter) return false;
    return true;
  });

  // Stats for currently filtered view
  const fWins = filtered.filter(r => (r.exit_return || 0) > 0);
  const fWithReturn = filtered.filter(r => r.exit_return != null);
  const fWinRate = fWithReturn.length ? fWins.length / fWithReturn.length * 100 : null;
  const fAvgReturn = fWithReturn.length ? fWithReturn.reduce((s, r) => s + r.exit_return, 0) / fWithReturn.length : null;

  return (
    <>
      {/* Summary strip — updates with filters */}
      <div style={{ display: 'flex', gap: 20, flexWrap: 'wrap', marginBottom: 10, padding: '8px 14px', background: '#ffffff06', borderRadius: 6, alignItems: 'center' }}>
        <span className="mono dim" style={{ fontSize: 11 }}>Showing: <span style={{ color: '#e0e0e0' }}>{filtered.length}</span> / {rows.length}</span>
        {fWinRate != null && <span className="mono dim" style={{ fontSize: 11 }}>Win rate: <span style={{ color: fWinRate >= 50 ? '#00ff88' : '#ff3860', fontWeight: 600 }}>{fWinRate.toFixed(1)}%</span></span>}
        {fAvgReturn != null && <span className="mono dim" style={{ fontSize: 11 }}>Avg return: <SigReturnCell val={fAvgReturn} /></span>}
        <span className="mono dim" style={{ fontSize: 11 }}>Wins: <span style={{ color: '#00ff88' }}>{fWins.length}</span></span>
        <span className="mono dim" style={{ fontSize: 11 }}>Losses: <span style={{ color: '#ff3860' }}>{filtered.filter(r => (r.exit_return || 0) < 0).length}</span></span>
      </div>
      {/* Filter bar */}
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 6, alignItems: 'center' }}>
        {['all', 'wins', 'losses'].map(v => (
          <button key={v} className={'dashb-tf-btn mono' + (resultFilter === v ? ' active' : '')}
            style={{ fontSize: 9.5 }} onClick={() => setResultFilter(v)}>{v}</button>
        ))}
        <span className="mono dim" style={{ fontSize: 10, marginLeft: 8 }}>Track:</span>
        {['all', 'CONFIRMED', 'RECOVERY', '4H-QUALITY'].map(v => (
          <button key={v} className={'dashb-tf-btn mono' + (trackFilter === v ? ' active' : '')}
            style={{ fontSize: 9.5 }} onClick={() => setTrackFilter(v)}>{v}</button>
        ))}
        <span className="mono dim" style={{ fontSize: 10, marginLeft: 8 }}>TF:</span>
        {['', '4h', '1d', '1w'].map(v => (
          <button key={v} className={'dashb-tf-btn mono' + (tfFilter === v ? ' active' : '')}
            style={{ fontSize: 9.5 }} onClick={() => setTfFilter(v)}>{v || 'all'}</button>
        ))}
        <span className="mono dim" style={{ fontSize: 10, marginLeft: 8 }}>Signal:</span>
        <button className={'dashb-tf-btn mono' + (!typeFilter ? ' active' : '')} style={{ fontSize: 9.5 }} onClick={() => setTypeFilter(0)}>all</button>
        {availTypes.map(t => (
          <button key={t} className={'dashb-tf-btn mono' + (typeFilter === t ? ' active' : '')} style={{ fontSize: 9.5 }} onClick={() => setTypeFilter(t)}>
            {SIGNAL_NAMES[t] || `S${t}`}
          </button>
        ))}
      </div>
      {!filtered.length
        ? <DBEmptyState msg="No trades match current filters." />
        : (
          <div style={{ overflowX: 'auto' }}>
            <table className="db-table">
              <thead><tr>
                <th>Track</th><th>Signal</th><th>Coin</th><th>TF</th>
                <th title="When the signal originally fired">Fired</th>
                <th title="Price at signal entry">Entry</th>
                <th title="Price when trade closed">Exit</th>
                <th title="Final profit/loss from entry to exit">P&L</th>
                <th title="Number of bars from entry to exit">Duration</th>
                <th title="What triggered the trade to close">Exit Reason</th>
                <th title="Worst drawdown below entry while trade was open">Worst Dip</th>
                <th title="Highest gain reached above entry before close">Best Gain</th>
                <th>⚡</th>
              </tr></thead>
              <tbody>
                {filtered.map((r, i) => {
                  const id = r.signal_id || i;
                  const isExp = expanded === id;
                  const sym = (r.symbol || '').replace('USDT', '');
                  const meta = (() => { try { return JSON.parse(r.signal_metadata || '{}'); } catch { return {}; } })();
                  const filt = meta.filter || {};
                  const isWin = (r.exit_return || 0) > 0;
                  const isLoss = r.exit_return != null && r.exit_return < 0;
                  return (
                    <React.Fragment key={id}>
                      <tr className={'db-tr' + (isWin ? ' db-tr-green' : isLoss ? ' db-tr-red' : '')}
                        style={{ cursor: 'pointer' }} onClick={() => setExpanded(p => p === id ? null : id)}>
                        <td><TrackBadge track={classifyTrack(r)} /></td>
                        <td className="mono dim" style={{ fontSize: 10, whiteSpace: 'nowrap' }}>
                          <SignalTypeBadge type={r.signal_type} subtype={r.signal_subtype} />
                        </td>
                        <td className="mono fw6">
                          <span className="clickable" onClick={e => { e.stopPropagation(); window.__openToken?.(sym); }}>{sym}</span>
                        </td>
                        <td><TFBadge tf={r.timeframe} /></td>
                        <td className="mono dim" style={{ fontSize: 10, whiteSpace: 'nowrap' }}>{fmtDateTime(r.fired_at)}</td>
                        <td className="mono dim" style={{ fontSize: 10 }}>{r.entry_price ? fmtPrice(Number(r.entry_price)) : '—'}</td>
                        <td className="mono dim" style={{ fontSize: 10 }}>{r.exit_price ? fmtPrice(Number(r.exit_price)) : '—'}</td>
                        <td><SigReturnCell val={r.exit_return} /></td>
                        <td className="mono dim" style={{ fontSize: 10 }}>{r.exit_bar != null ? r.exit_bar + 'b' : '—'}</td>
                        <td className="mono dim" style={{ fontSize: 10 }}>{exitLabel(r.exit_condition)}</td>
                        <td className="mono" style={{ fontSize: 10, color: r.mae != null ? (r.mae < -8 ? '#ff3860' : r.mae < -4 ? '#ffaa00' : '#888') : '#555' }}>
                          {r.mae != null ? r.mae.toFixed(1) + '%' : '—'}
                        </td>
                        <td className="mono" style={{ fontSize: 10, color: r.mfe != null ? '#00ff88' : '#555' }}>
                          {r.mfe != null ? '+' + r.mfe.toFixed(1) + '%' : '—'}
                        </td>
                        <td style={{ textAlign: 'center' }}>{r.hosoda_active ? '⚡' : '—'}</td>
                      </tr>
                      {isExp && (
                        <tr className="db-tr-expand">
                          <td colSpan={13} style={{ paddingLeft: 20, paddingBottom: 10, paddingTop: 6 }}>
                            <div style={{ display: 'flex', gap: 28, flexWrap: 'wrap', fontSize: 11 }}>
                              <div>
                                <div className="mono dim" style={{ fontSize: 10, marginBottom: 4 }}>Trade Result</div>
                                <div className="mono dim" style={{ fontSize: 10, lineHeight: 2 }}>
                                  <div>Entry: <span style={{ color: '#e0e0e0' }}>{r.entry_price ? fmtPrice(Number(r.entry_price)) : '—'}</span></div>
                                  <div>Exit: <span style={{ color: '#e0e0e0' }}>{r.exit_price ? fmtPrice(Number(r.exit_price)) : '—'}</span></div>
                                  <div>Final P&L: <SigReturnCell val={r.exit_return} /></div>
                                  <div>Duration: <span style={{ color: '#e0e0e0' }}>{r.exit_bar != null ? r.exit_bar + ' bars' : '—'}</span></div>
                                  <div>Closed because: <span style={{ color: '#e0e0e0' }}>{exitLabel(r.exit_condition)}</span></div>
                                  <div>Worst dip: <span style={{ color: r.mae != null && r.mae < -5 ? '#ff3860' : '#888' }}>{r.mae != null ? r.mae.toFixed(1) + '%' : '—'}</span></div>
                                  <div>Best gain: <span style={{ color: '#00ff88' }}>{r.mfe != null ? '+' + r.mfe.toFixed(1) + '%' : '—'}</span></div>
                                </div>
                              </div>
                              {filt.tier && (
                                <div>
                                  <div className="mono dim" style={{ fontSize: 10, marginBottom: 4 }}>At-Entry Filter</div>
                                  <div className="mono dim" style={{ fontSize: 10, lineHeight: 2 }}>
                                    <div>Tier: <TierBadge tier={filt.tier} /></div>
                                    <div>BTC regime: <span style={{ color: filt.btc_regime === 'above' ? '#00ff88' : '#ff3860' }}>{filt.btc_regime || '—'}</span></div>
                                    <div>Chikou: <span style={{ color: filt.chikou_ok ? '#00ff88' : '#888' }}>{filt.chikou_ok ? '✓' : '✗'}</span></div>
                                    {filt.atr_pct > 0 && <div>ATR%: <span style={{ color: '#888' }}>{filt.atr_pct.toFixed(1)}%</span></div>}
                                  </div>
                                </div>
                              )}
                              {(r.return_7d != null || r.return_30d != null) && (
                                <div>
                                  <div className="mono dim" style={{ fontSize: 10, marginBottom: 4 }}>Forward Returns</div>
                                  <div className="mono dim" style={{ fontSize: 10, lineHeight: 2 }}>
                                    <div>7d: <SigReturnCell val={r.return_7d} /></div>
                                    <div>30d: <SigReturnCell val={r.return_30d} /></div>
                                  </div>
                                </div>
                              )}
                            </div>
                          </td>
                        </tr>
                      )}
                    </React.Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
        )
      }
    </>
  );
}

// ── Developing (pre-signal) table ─────────────────────────────────────────────

const DEV_COND_CFG = {
  tk_converging:     { label: 'TK converging',     color: '#4fc3f7', tip: 'Tenkan and Kijun within 0.5% of each other and narrowing — TK cross imminent (S1/S2 precursor)' },
  cloud_entry:       { label: 'Entered cloud',      color: '#c4b5fd', tip: 'Price just moved from outside into the cloud — Edge-to-Edge (S4) setup forming' },
  twist_upcoming:    { label: 'Twist incoming',     color: '#ffaa00', tip: 'Future cloud (Span A/B) about to cross within 5 bars — S5/S7 precursor' },
  chikou_near_clear: { label: 'Chikou ~clear',      color: '#00ff88', tip: 'Current close within 2% of clearing the chikou barrier — final confirmation approaching' },
  bb_squeeze:        { label: 'BB squeeze',         color: '#ff9f43', tip: 'Bollinger Bands compressed — volatility consolidation preceding a breakout' },
  kijun_retest:      { label: 'KJ retest zone',     color: '#a78bfa', tip: 'Price testing a flat Kijun from above within 1.5% — classic S2 retest precursor' },
};

function ConditionBadge({ id }) {
  const cfg = DEV_COND_CFG[id] || { label: id, color: '#888', tip: '' };
  const ref = useRef_B(null);
  return (
    <span
      ref={ref}
      style={{
        fontSize: 9, fontFamily: 'JetBrains Mono,monospace', fontWeight: 600,
        padding: '2px 6px', borderRadius: 3, marginRight: 4, marginBottom: 3,
        display: 'inline-block', cursor: 'help',
        background: cfg.color + '18', border: `1px solid ${cfg.color}44`, color: cfg.color,
      }}
      onMouseEnter={() => {
        if (!ref.current || !window.__showTip) return;
        const rect = ref.current.getBoundingClientRect();
        window.__showTip({ x: rect.left + rect.width / 2, y: rect.top, text: cfg.tip });
      }}
      onMouseLeave={() => window.__hideTip?.()}
    >{cfg.label}</span>
  );
}

function DevelopingTable({ rows }) {
  const [tfFilter, setTfFilter] = useSt('');
  const [minConds, setMinConds] = useSt(1);

  if (!rows.length) return <DBEmptyState msg="No developing setups detected on this scan. Run a fresh scan to populate." />;

  const filtered = rows.filter(r => {
    if (tfFilter && r.timeframe !== tfFilter) return false;
    if ((r.condition_count || 0) < minConds) return false;
    return true;
  });

  return (
    <>
      <div style={{ marginBottom: 10, padding: '6px 12px', background: '#ffaa0010', border: '1px solid #ffaa0025', borderRadius: 5 }}>
        <span className="mono" style={{ fontSize: 10, color: '#ffaa00' }}>
          ⚠ Pre-signal — conditions aligning but no signal has fired yet. These are early warnings, not confirmed entries.
        </span>
      </div>
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 10, alignItems: 'center' }}>
        <span className="mono dim" style={{ fontSize: 10 }}>TF:</span>
        {['', '4h', '1d', '1w'].map(v => (
          <button key={v} className={'dashb-tf-btn mono' + (tfFilter === v ? ' active' : '')}
            style={{ fontSize: 9.5 }} onClick={() => setTfFilter(v)}>{v || 'all'}</button>
        ))}
        <span className="mono dim" style={{ fontSize: 10, marginLeft: 8 }}>Min conditions:</span>
        {[1, 2, 3].map(n => (
          <button key={n} className={'dashb-tf-btn mono' + (minConds === n ? ' active' : '')}
            style={{ fontSize: 9.5 }} onClick={() => setMinConds(n)}>{n}+</button>
        ))}
        <span className="mono dim" style={{ fontSize: 10, marginLeft: 8 }}>{filtered.length} coins</span>
      </div>
      {!filtered.length
        ? <DBEmptyState msg="No developing setups match current filters." />
        : (
          <div style={{ overflowX: 'auto' }}>
            <table className="db-table">
              <thead><tr>
                <th>Coin</th>
                <th>TF</th>
                <th title="How many pre-signal conditions are aligning. More = stronger setup forming.">#</th>
                <th>Conditions aligning</th>
                <th title="Current price (from last scan)">Price</th>
                <th title="Numeric details for each condition (e.g. how tight the TK gap is)">Details</th>
              </tr></thead>
              <tbody>
                {filtered.map((r, i) => {
                  const dispSym = (r.symbol || '').replace('USDT', '');
                  const strengthColor = (r.condition_count || 0) >= 3 ? '#00ff88' : (r.condition_count || 0) >= 2 ? '#ffaa00' : '#888';
                  return (
                    <tr key={r.symbol + r.timeframe + i} className="db-tr">
                      <td className="mono fw6">
                        <span className="clickable" onClick={() => window.__openToken?.(dispSym)}>{dispSym}</span>
                      </td>
                      <td><TFBadge tf={r.timeframe} /></td>
                      <td>
                        <span className="mono fw6" style={{ color: strengthColor, fontSize: 13 }}>{r.condition_count}</span>
                      </td>
                      <td style={{ whiteSpace: 'nowrap' }}>
                        {(r.conditions || []).map(c => <ConditionBadge key={c} id={c} />)}
                      </td>
                      <td className="mono dim" style={{ fontSize: 10 }}>{r.close ? fmtPrice(r.close) : '—'}</td>
                      <td className="mono dim" style={{ fontSize: 10 }}>
                        {r.details && Object.entries(r.details).map(([k, v]) => (
                          <span key={k} style={{ marginRight: 12 }}>
                            {k.replace(/_/g,' ')}: <span style={{ color: '#e0e0e0' }}>{typeof v === 'number' ? v.toFixed(2) : String(v)}</span>
                          </span>
                        ))}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )
      }
    </>
  );
}

// ── Signal Log Panel (top-level, used in Dashboard C) ────────────────────────

function BtcRegimeBanner({ regime }) {
  if (!regime || regime === 'above' || regime === 'unknown') return null;
  const isBelow = regime === 'below';
  const color = isBelow ? '#ff3860' : '#ffaa00';
  const bg    = isBelow ? '#ff386015' : '#ffaa0015';
  const msg   = isBelow
    ? '⚠ BTC below cloud — long signals are high risk. Only Signal 4 (E2E) is exempt from this filter.'
    : '⚠ BTC inside cloud — mixed regime. Signals below T3 are suppressed. Only Signal 4 (E2E) passes through.';
  return (
    <div style={{
      padding: '6px 12px', borderRadius: 4, marginBottom: 10,
      border: `1px solid ${color}44`, background: bg,
      color, fontFamily: 'JetBrains Mono,monospace', fontSize: 11,
    }}>{msg}</div>
  );
}

const TAB_CFG = [
  { id: 'setups',     label: 'SETUPS',      desc: 'Fresh entry opportunities still within the window' },
  { id: 'open',       label: 'OPEN',        desc: 'All running trades — managed until exit' },
  { id: 'history',    label: 'HISTORY',     desc: 'Closed trades with full P&L' },
  { id: 'developing', label: 'DEVELOPING',  desc: 'Pre-signal conditions aligning' },
  { id: 'performance',label: 'PERFORMANCE', desc: 'Historical edge by signal type' },
];

function SignalLogPanel() {
  const [tab, setTab] = useSt('setups');

  const { data: setupsData,  loading: setupsLoading  } = useSignals(tab === 'setups'      ? 'setups'      : '__skip__');
  const { data: openData,    loading: openLoading    } = useSignals(tab === 'open'        ? 'open'        : '__skip__');
  const { data: historyData, loading: historyLoading } = useSignals(tab === 'history'     ? 'history'     : '__skip__');
  const { data: devData,     loading: devLoading     } = useSignals(tab === 'developing'  ? 'developing'  : '__skip__');
  const { data: perfData,    loading: perfLoading    } = useSignals(tab === 'performance' ? 'performance' : '__skip__');

  const btcRegime = setupsData?.btc_regime || openData?.btc_regime || historyData?.btc_regime || 'unknown';

  // Gather all symbols needing live prices (setups + open)
  const priceSymbols = useMemo(() => {
    const s = new Set();
    for (const r of setupsData?.rows || []) s.add(r.symbol);
    for (const r of openData?.rows   || []) s.add(r.symbol);
    return [...s];
  }, [setupsData, openData]);

  const prices = usePrices(priceSymbols);

  const isLoading = tab === 'setups'      ? setupsLoading
    : tab === 'open'        ? openLoading
    : tab === 'history'     ? historyLoading
    : tab === 'developing'  ? devLoading
    : perfLoading;

  const tabStyle = (t) => ({
    padding: '5px 14px',
    fontFamily: 'JetBrains Mono,monospace',
    fontSize: 11,
    fontWeight: tab === t ? 700 : 400,
    color: tab === t ? '#c4b5fd' : '#666',
    background: tab === t ? '#7c3aed20' : 'transparent',
    border: `1px solid ${tab === t ? '#7c3aed55' : '#ffffff10'}`,
    borderRadius: 4,
    cursor: 'pointer',
    whiteSpace: 'nowrap',
  });

  const activeDesc = TAB_CFG.find(t => t.id === tab)?.desc || '';

  return (
    <div className="db-mtf-bar">
      <div className="db-mtf-bar-head" style={{ marginBottom: 12, flexWrap: 'wrap', gap: 8 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span className="mono" style={{ fontSize: 12, fontWeight: 600 }}>
            Signal Tracker
          </span>
          <InfoTip>8 named Ichimoku signal types tracked from entry through exit. Setups = fresh signals you can still enter. Open = all running trades. History = closed trades with P&L. Developing = pre-signal conditions forming. Performance = historical edge per signal type. Live prices from Binance WS + CoinGecko fallback.</InfoTip>
          {activeDesc && <span className="mono dim" style={{ fontSize: 10 }}>{activeDesc}</span>}
        </div>
        <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap' }}>
          {TAB_CFG.map(t => (
            <button key={t.id} style={tabStyle(t.id)} onClick={() => setTab(t.id)} title={t.desc}>
              {t.label}
            </button>
          ))}
        </div>
      </div>

      <BtcRegimeBanner regime={btcRegime} />

      {isLoading
        ? <div className="mono dim" style={{ padding: '24px 0', textAlign: 'center', fontSize: 12 }}>Loading…</div>
        : tab === 'setups'
          ? <SetupsTable rows={setupsData?.rows || []} prices={prices} />
          : tab === 'open'
            ? <SignalOpenTable rows={openData?.rows || []} prices={prices} />
            : tab === 'history'
              ? <HistoryTable rows={historyData?.rows || []} />
              : tab === 'developing'
                ? <DevelopingTable rows={devData?.rows || []} />
                : <SignalPerfTable stats={perfData?.stats || []} />
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

function BEventCard({ card, data, tf, minScore, isActive, onActivate }) {
  const count = filterEvents(data?.[card.countKey], tf, minScore).length;
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

function DashboardB({ tf, minScore = 0 }) {
  const data = useEvents();
  const [activeCard, setActiveCard] = useSt('transition');

  const active = B_CARDS.find(c => c.id === activeCard);

  return (
    <div className="dash-b-area">

      {/* Research / unvalidated banner — always visible */}
      <div style={{
        background: '#ffaa0012', border: '1px solid #ffaa0033',
        borderRadius: 6, padding: '8px 14px', marginBottom: 12,
        display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap',
      }}>
        <span style={{ color: '#ffaa00', fontSize: 12 }}>⚠</span>
        <span style={{ fontFamily: 'JetBrains Mono,monospace', fontSize: 11, color: '#ffaa00', fontWeight: 600 }}>Research Mode</span>
        <span style={{ fontFamily: 'JetBrains Mono,monospace', fontSize: 11, color: '#888' }}>
          Dashboard B events are exploratory — not walk-forward validated. Use for discovery and early warning only. Signals below are <b style={{ color: '#ffaa00' }}>not</b> the ≥13 validated threshold.
        </span>
      </div>

      {/* Card grid — mirrors Dashboard A's scanner grid */}
      <section className="scanner-grid">
        {B_CARDS.map(card => (
          <BEventCard
            key={card.id}
            card={card}
            data={data}
            tf={tf}
            minScore={minScore}
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
        {active && <active.Table tf={tf} minScore={minScore} />}
      </div>

      {/* MTF Event View — always visible, like Dashboard A's bottom stats */}
      <MTFEventBar data={data} />
    </div>
  );
}
