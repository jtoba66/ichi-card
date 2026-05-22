// Scanner result views. One <ResultsArea kind=...> renders the right panel.

const { useState: useStateS, useMemo: useMemoS } = React;

// ─── 3a. Daily Scan ──────────────────────────────────────────────────────────
function DailyScanResults({ minScore, regime, watchOnly }) {
  const { COINS } = window.ICHI_DATA;
  const [bearMode, setBearMode] = useStateS(false);
  const scoreField = bearMode ? 'bearScore' : 'score1d';
  const { sortKey, sortDir, onSort } = useSort(scoreField);
  const { has: inWatch } = useWatch();

  const rows = useMemoS(() => {
    let r = COINS.filter(c => c[scoreField] >= minScore);
    if (regime === 'TRENDING') r = r.filter(c => c.adx >= 25);
    if (regime === 'STRONG')   r = r.filter(c => c.adx >= 40);
    if (watchOnly) r = r.filter(c => inWatch(c.sym));
    const dir = sortDir === 'desc' ? -1 : 1;
    return [...r].sort((a, b) => {
      const va = a[sortKey], vb = b[sortKey];
      if (typeof va === 'number') return (va - vb) * dir;
      return String(va).localeCompare(String(vb)) * -dir;
    });
  }, [minScore, regime, sortKey, sortDir, watchOnly, inWatch, scoreField]);

  const modeBtn = (label, active, onClick) => (
    <button onClick={onClick} style={{
      fontFamily: "'JetBrains Mono',monospace", fontSize: 11, fontWeight: 600,
      padding: '4px 10px', borderRadius: 4, cursor: 'pointer',
      border: `1px solid ${active ? (bearMode ? '#ff3860' : '#00ff88') : '#2a2a3a'}`,
      background: active ? (bearMode ? '#ff386022' : '#00ff8822') : 'transparent',
      color: active ? (bearMode ? '#ff3860' : '#00ff88') : '#555',
      transition: 'all 0.12s',
    }}>{label}</button>
  );

  return (
    <div className="panel">
      <div className="panel-head">
        <h3>
          {bearMode ? 'Bear Scan' : 'Daily Scan'}
          <span className="dim"> — 1d {bearMode ? 'bear' : 'bull'} score</span>
          <InfoTip size="md">{bearMode
            ? <span>Bear score: how many of the 18 rules are in a <b>bearish state</b>. High = multiple warning signs firing simultaneously. Not just "not bullish" — actively bearish geometry.</span>
            : <span>Bull score: how many of the 18 Ichimoku rules are in a <b>bullish state</b> right now. 18/18 = textbook perfect setup. ≥ 11 = structurally strong enough to consider.</span>
          }</InfoTip>
        </h3>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          {modeBtn('▲ Bull', !bearMode, () => setBearMode(false))}
          {modeBtn('▼ Bear', bearMode,  () => setBearMode(true))}
          <div className="panel-meta mono">{rows.length} results · min {minScore}/18 <span className="dim">({bearMode ? 'bear' : 'bull'} score)</span> · {regime}</div>
          {!bearMode && <div className="validated-stat-badge">≥13 avg +12% / 30d · 100% OOS · 7 windows</div>}
        </div>
      </div>
      <div className="table-wrap">
        <table className="data-table">
          <thead>
            <tr>
              <th style={{ width: 32 }}></th>
              <th style={{ width: 44 }}>#</th>
              <SortHeader id="sym" label="Symbol" sortKey={sortKey} sortDir={sortDir} onSort={onSort} />
              <th>Sector</th>
              <SortHeader id={scoreField} label="Score" sortKey={sortKey} sortDir={sortDir} onSort={onSort} />
              <th>Trend 7d<InfoTip>7-day history of the daily score (oldest left → today right). The ▲/▼ number next to the chart shows the net change — ▲3 means the score rose 3 points this week, ▼2 means it fell 2. A rising trend on a coin already at ≥11 signals strengthening momentum.</InfoTip></th>
              <SortHeader id="adx" label="ADX" sortKey={sortKey} sortDir={sortDir} onSort={onSort} align="right" tip="Average Directional Index — measures trend strength regardless of direction. < 20 = flat/choppy. ≥ 25 = trending. ≥ 40 = strong sustained move. The Regime filter uses these thresholds." />
              <th style={{ textAlign: 'right' }}>+DI / −DI<InfoTip>Directional movement. <b>+DI {'>'} −DI</b> = buyers dominant (green). <b>−DI {'>'} +DI</b> = sellers dominant (red). Part of the ADX system.</InfoTip></th>
              <th>Cloud<InfoTip>Price vs the Ichimoku cloud. <b>Above ☁</b> = bullish zone. <b>IN ☁</b> = inside cloud, indecision. <b>Below ☁</b> = bearish zone.</InfoTip></th>
              <th>Fwd ☁<InfoTip>The cloud <b>26 bars ahead</b>. ✓ Bull = future cloud is green (rising support). ✗ Bear = red cloud ahead (resistance building). Forward-looking — acts as early warning.</InfoTip></th>
              <th>Flags<InfoTip>Signal flags that fire on top of the score when specific patterns are detected. <b>SQUEEZE</b> = Bollinger Band volatility compressed, a big move is statistically due. <b>VOL 2×+</b> = volume spike above average. <b>RSI-DIV↑</b> = price dipping but momentum recovering (hidden buying). <b>RS:STRONG↑</b> = outperforming BTC. Multiple flags at once strengthen the case.</InfoTip></th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && (
              <tr><td colSpan={11}><EmptyState
                title={watchOnly ? 'No watchlisted coins meet the filter.' : 'No coins match the current filter.'}
                hint={watchOnly ? 'Turn off Watch-only or ★ more coins.' : `Try lowering min score (now ${minScore}/18) or relaxing regime (now ${regime}).`}
              /></td></tr>
            )}
            {rows.map((c, i) => {
              const VALIDATED_THRESHOLD = 13;
              const prevAbove = i > 0 && rows[i-1][scoreField] >= VALIDATED_THRESHOLD;
              const thisAbove = c[scoreField] >= VALIDATED_THRESHOLD;
              const showDivider = !bearMode && !prevAbove && thisAbove === false && i > 0 && rows[i-1][scoreField] >= VALIDATED_THRESHOLD;
              const isNoisezone = !bearMode && c[scoreField] < VALIDATED_THRESHOLD;
              return (
                <React.Fragment key={c.sym}>
                  {!bearMode && i > 0 && rows[i-1][scoreField] >= VALIDATED_THRESHOLD && c[scoreField] < VALIDATED_THRESHOLD && (
                    <tr className="score-divider-row">
                      <td colSpan={11}>
                        <span className="score-divider-label">── below validated threshold (≥13) · signal becomes noise ──</span>
                      </td>
                    </tr>
                  )}
                  <tr onClick={() => window.__openToken(c.sym)} title="Click to open full detail"
                      className={isNoisezone ? 'row-noisezone' : ''}>
                    <td><WatchStar sym={c.sym} compact /></td>
                    <td className="mono dim">{String(i + 1).padStart(2, '0')}</td>
                    <td><span className="sym mono">{c.sym}</span></td>
                    <td><span className="sector-pill">{c.sector}</span></td>
                    <td><ScoreBadge coin={c} score={c[scoreField]} tf={bearMode ? 'bear' : '1d'} /></td>
                    <td><Sparkline data={c.scoreHist} /></td>
                    <td style={{ textAlign: 'right' }}><AdxBadge adx={c.adx} compact /></td>
                    <td className="mono" style={{ textAlign: 'right', color: c.plusDI > c.minusDI ? '#00ff88' : '#ff3860' }}>
                      {c.plusDI.toFixed(1)} <span className="dim">/</span> {c.minusDI.toFixed(1)}
                    </td>
                    <td><CloudBadge cloud={c.cloud} /></td>
                    <td><FwdCloud fwd={c.fwdCloud} /></td>
                    <td><Flags flags={c.flags} /></td>
                  </tr>
                </React.Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ─── 3b. Multi-TF Scan ───────────────────────────────────────────────────────
function MultiTFResults({ watchOnly, minAligned }) {
  const { COINS } = window.ICHI_DATA;
  const { sortKey, sortDir, onSort } = useSort('aligned');
  const { has: inWatch } = useWatch();
  const rows = useMemoS(() => {
    let r = COINS.map(c => {
      const aligned = [c.score4h, c.score1d, c.score1w].filter(s => s >= 11).length;
      return { ...c, aligned };
    });
    if (minAligned > 0) r = r.filter(c => c.aligned >= minAligned);
    if (watchOnly) r = r.filter(c => inWatch(c.sym));
    const dir = sortDir === 'desc' ? -1 : 1;
    return r.sort((a, b) => {
      const va = a[sortKey], vb = b[sortKey];
      if (typeof va === 'number') return (va - vb) * dir || (b.score1d - a.score1d);
      return String(va).localeCompare(String(vb)) * -dir;
    });
  }, [sortKey, sortDir, watchOnly, inWatch, minAligned]);

  return (
    <div className="panel">
      <div className="panel-head">
        <h3>Multi-TF Scan <span className="dim">— alignment across 4h · 1d · 1w</span><InfoTip size="md"><span>Shows every coin scored on all three timeframes simultaneously. Rows highlighted in teal have all three (4h, 1d, 1w) scoring ≥ 11/18 — these are the <b>highest-conviction setups</b> where short, medium, and long-term all agree.</span></InfoTip></h3>
        <div className="panel-meta mono">{rows.length} results · {rows.filter(r => r.aligned === 3).length} fully aligned</div>
      </div>
      <div className="table-wrap">
        <table className="data-table">
          <thead>
            <tr>
              <th style={{ width: 32 }}></th>
              <th style={{ width: 44 }}>#</th>
              <SortHeader id="sym" label="Symbol" sortKey={sortKey} sortDir={sortDir} onSort={onSort} />
              <th>Sector</th>
              <SortHeader id="score1w" label="1w" sortKey={sortKey} sortDir={sortDir} onSort={onSort} />
              <SortHeader id="score1d" label="1d" sortKey={sortKey} sortDir={sortDir} onSort={onSort} />
              <SortHeader id="score4h" label="4h" sortKey={sortKey} sortDir={sortDir} onSort={onSort} />
              <SortHeader id="aligned" label="Aligned" sortKey={sortKey} sortDir={sortDir} onSort={onSort} tip="How many of the 3 timeframes (4h, 1d, 1w) have a score ≥ 11/18. ●●● 3/3 = all three agree the coin is in bullish structure — the highest-conviction setup. ●●○ 2/3 = two timeframes agree. ○○○ = no alignment." />
              <th>Cloud<InfoTip>Price vs the Ichimoku cloud on the daily timeframe. Above ☁ = bullish zone, IN ☁ = inside cloud (decision), Below ☁ = bearish.</InfoTip></th>
              <SortHeader id="adx" label="ADX" sortKey={sortKey} sortDir={sortDir} onSort={onSort} tip="Average Directional Index — trend strength regardless of direction. < 20 = flat. ≥ 25 = trending. ≥ 40 = strong sustained move." />
              <th>Flags<InfoTip>Active signal flags on the daily timeframe — SQUEEZE (volatility coiled), RSI-DIV↑ (hidden strength), RS:STRONG↑ (outperforming BTC), VOL (volume spike). Same flags as Daily Scan.</InfoTip></th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && (
              <tr><td colSpan={11}><EmptyState title="No coins match the current filter." hint={watchOnly ? "Turn off Watch-only or ★ some coins from the Daily Scan." : "Lower the Align≥ filter to see more results."} /></td></tr>
            )}
            {rows.map((c, i) => (
              <tr key={c.sym} className={c.aligned === 3 ? 'row-aligned' : ''} onClick={() => window.__openToken(c.sym)} title="Click to open full detail">
                <td><WatchStar sym={c.sym} compact /></td>
                <td className="mono dim">{String(i + 1).padStart(2, '0')}</td>
                <td><span className="sym mono">{c.sym}</span></td>
                <td><span className="sector-pill">{c.sector}</span></td>
                <td><ScorePip score={c.score1w} /></td>
                <td><ScorePip score={c.score1d} /></td>
                <td><ScorePip score={c.score4h} /></td>
                <td>
                  <span className="aligned-count mono" data-n={c.aligned}>
                    {'●'.repeat(c.aligned)}{'○'.repeat(3 - c.aligned)} <span className="dim">{c.aligned}/3</span>
                  </span>
                </td>
                <td><CloudBadge cloud={c.cloud} /></td>
                <td><AdxBadge adx={c.adx} compact /></td>
                <td><Flags flags={c.flags} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ─── 3c. Coiled Spring ───────────────────────────────────────────────────────
function CoiledSpringResults({ weeklyMin, dailyMax }) {
  const { COINS } = window.ICHI_DATA;
  const cards = useMemoS(() => {
    const filtered = COINS.filter(c => c.score1w >= weeklyMin && c.score1d <= dailyMax);
    return filtered.map(c => {
      const compression = (c.score1w - c.score1d);
      const adxBonus = c.adx < 20 ? 2 : 0;
      const cloudBonus = c.cloud === 'IN' ? 3 : 0;
      const coil = Math.round((compression + adxBonus + cloudBonus) * 10) / 10;
      return { ...c, coil };
    }).sort((a, b) => b.coil - a.coil).slice(0, 12);
  }, [weeklyMin, dailyMax]);

  return (
    <div className="panel">
      <div className="panel-head">
        <h3>Coiled Spring <span className="dim">— laggards primed to move</span></h3>
        <div className="panel-meta mono">{cards.length} setups · weekly ≥ {weeklyMin} · daily ≤ {dailyMax}</div>
      </div>
      <div className="coil-grid">
        {cards.map(c => (
          <div key={c.sym} className={'coil-card' + (c.cloud === 'IN' ? ' compressed' : '')} onClick={() => window.__openToken(c.sym)}>
            <div className="coil-card-top">
              <div className="coil-sym mono">{c.sym}</div>
              <span className="sector-pill">{c.sector}</span>
            </div>
            <div className="coil-score-block">
              <div className="coil-score-num mono" style={{ color: scoreColor(Math.min(18, Math.round(c.coil))) }}>
                {c.coil.toFixed(1)}
              </div>
              <div className="coil-score-label">coil score<InfoTip>Composite score = <b>(1w score − 1d score)</b> + <b>+2</b> if ADX &lt; 20 (trend is flat, more room to explode) + <b>+3</b> if price is inside the cloud (maximum compression). Typical range is 4–15. Score ≥ 6 is worth watching. ≥ 10 = strong compression with high expansion potential.</InfoTip></div>
            </div>
            <div className="coil-tf-row">
              <div><span className="dim mono">1w</span> <span className="mono" style={{ color: scoreColor(c.score1w) }}>{c.score1w}</span></div>
              <div><span className="dim mono">1d</span> <span className="mono" style={{ color: scoreColor(c.score1d) }}>{c.score1d}</span></div>
              <div><span className="dim mono">4h</span> <span className="mono" style={{ color: scoreColor(c.score4h) }}>{c.score4h}</span></div>
            </div>
            <div className="coil-badges">
              <CloudBadge cloud={c.cloud} />
              <FwdCloud fwd={c.fwdCloud} />
              <AdxBadge adx={c.adx} compact />
            </div>
            <div className="coil-flags"><Flags flags={c.flags} /></div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── 3d. Sector Rotation ─────────────────────────────────────────────────────
function SectorRotationResults() {
  const { sectorStats } = window.ICHI_DATA;
  const topThree = sectorStats.slice(0, 3);
  const maxAvg = Math.max(...sectorStats.map(s => s.avgBull));

  return (
    <div className="panel">
      <div className="panel-head">
        <h3>Sector Rotation <span className="dim">— relative strength across categories</span></h3>
        <div className="panel-meta mono">{sectorStats.length} sectors</div>
      </div>
      <div className="sector-layout">
        <div className="sector-leaderboard">
          <div className="sub-h" style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            Leaderboard
            <span className="mono dim" style={{ fontSize: 10, fontWeight: 400, display: 'flex', gap: 10 }}>
              <span>avg score<InfoTip>Average 1-day bull score across every coin in this sector. Higher = the sector is broadly in bullish Ichimoku structure, not just 1–2 coins pulling up the average.</InfoTip></span>
              <span>% ≥11<InfoTip>Percentage of coins in this sector scoring ≥ 11/18 (the "structurally bullish" threshold). High % means broad sector participation — the move isn't concentrated.</InfoTip></span>
              <span>ADX<InfoTip>Average ADX across the sector. ≥ 25 = sector is trending directionally. ≥ 40 = strong sustained move.</InfoTip></span>
              <span>n<InfoTip>Number of coins tracked in this sector within the 200-coin universe.</InfoTip></span>
            </span>
          </div>
          {sectorStats.map(s => (
            <div key={s.sector} className="sector-row">
              <div className="sector-row-name">{s.sector}</div>
              <div className="sector-row-bar">
                <div className="sector-row-track">
                  <div className="sector-row-fill" style={{
                    width: `${(s.avgBull / maxAvg) * 100}%`,
                    background: scoreColor(Math.round(s.avgBull)),
                  }}></div>
                </div>
                <div className="mono" style={{ color: scoreColor(Math.round(s.avgBull)) }}>
                  {s.avgBull.toFixed(1)}<span className="dim">/18</span>
                </div>
              </div>
              <div className="sector-row-meta">
                <span className="sector-pct mono">{s.pctAbove11}% ≥11</span>
                <AdxBadge adx={s.avgAdx} compact />
                <span className="dim mono">n={s.members}</span>
              </div>
            </div>
          ))}
        </div>
        <div className="sector-drill">
          <div className="sub-h">Top 3 — coin drill-down</div>
          {topThree.map(s => (
            <div key={s.sector} className="sector-drill-block">
              <div className="sector-drill-head">
                <span className="sector-pill big">{s.sector}</span>
                <span className="dim mono">avg {s.avgBull.toFixed(1)}/18 · {s.pctAbove11}% ≥11</span>
              </div>
              <div className="sector-drill-grid">
                {s.top.map(c => (
                  <div key={c.sym} className="mini-card" onClick={() => window.__openToken(c.sym)}>
                    <div className="mini-card-top">
                      <span className="sym mono">{c.sym}</span>
                      <span className="mono" style={{ color: scoreColor(c.score1d) }}>{c.score1d}/18</span>
                    </div>
                    <div className="mini-card-bar">
                      <div style={{ width: `${(c.score1d / 18) * 100}%`, background: scoreColor(c.score1d) }}></div>
                    </div>
                    <div className="mini-card-bot">
                      <CloudBadge cloud={c.cloud} />
                      <AdxBadge adx={c.adx} compact />
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ─── 3e. Funding + OI ────────────────────────────────────────────────────────
function FundingOIResults({ topN, squeezeOnly, watchOnly, minScore }) {
  const { COINS } = window.ICHI_DATA;
  const { sortKey, sortDir, onSort } = useSort('oi');
  const { has: inWatch } = useWatch();
  const rows = useMemoS(() => {
    let r = COINS.filter(c => c.oi >= 20e6);
    if (squeezeOnly) r = r.filter(c => c.squeeze && c.funding < 0 && c.score1d >= 11);
    if (minScore > 0) r = r.filter(c => c.score1d >= minScore);
    if (watchOnly) r = r.filter(c => inWatch(c.sym));
    const dir = sortDir === 'desc' ? -1 : 1;
    return [...r].sort((a, b) => {
      const va = a[sortKey], vb = b[sortKey];
      if (typeof va === 'number') return (va - vb) * dir;
      return String(va).localeCompare(String(vb)) * -dir;
    }).slice(0, topN);
  }, [topN, squeezeOnly, watchOnly, minScore, sortKey, sortDir, inWatch]);

  function signalFor(c) {
    if (c.squeeze && c.funding < 0 && c.score1d >= 11) return { tag: '🔥 SQUEEZE SETUP', cls: 'sig-squeeze' };
    if (c.funding < -0.005) return { tag: '⚡ neg funding', cls: 'sig-neg' };
    if (c.funding > 0.012)  return { tag: '⚠️ overleveraged', cls: 'sig-over' };
    return { tag: '—', cls: '' };
  }

  return (
    <div className="panel">
      <div className="panel-head">
        <h3>Funding + OI <span className="dim">— perp positioning & squeeze candidates</span></h3>
        <div className="panel-meta mono">{rows.length} results · {squeezeOnly ? 'SQUEEZE ONLY' : 'all signals'}</div>
      </div>
      <div className="table-wrap">
        <table className="data-table">
          <thead>
            <tr>
              <th style={{ width: 32 }}></th>
              <th style={{ width: 44 }}>#</th>
              <SortHeader id="sym" label="Symbol" sortKey={sortKey} sortDir={sortDir} onSort={onSort} />
              <SortHeader id="score1d" label="Score" sortKey={sortKey} sortDir={sortDir} onSort={onSort} tip="1-day Ichimoku bull score (0–18). Higher = more rules in a bullish state. Used alongside funding to find setups where structure and positioning both favour longs." />
              <SortHeader id="funding" label="Funding" sortKey={sortKey} sortDir={sortDir} onSort={onSort} align="right" tip="8-hour perpetual funding rate. Positive = longs paying shorts (crowded long side). Negative = shorts paying longs — bears are under pressure. Negative funding on a bullish chart is the core squeeze setup." />
              <SortHeader id="oi" label="OI (USD)" sortKey={sortKey} sortDir={sortDir} onSort={onSort} align="right" tip="Total dollar value of all open perpetual futures positions. Higher OI = more money at stake. A squeeze or flush on high-OI coins moves further and faster than low-OI ones." />
              <th>Cloud<InfoTip>Price vs the Ichimoku cloud. Above ☁ = bullish zone. IN ☁ = inside cloud, indecision. Below ☁ = bearish zone.</InfoTip></th>
              <SortHeader id="adx" label="ADX" sortKey={sortKey} sortDir={sortDir} onSort={onSort} tip="Trend strength. < 20 = flat. ≥ 25 = trending. ≥ 40 = strong sustained move." />
              <th>Signal<InfoTip>🔥 <b>SQUEEZE SETUP</b> = bull score ≥11 + negative funding + BB squeeze all firing at once — the primary setup this scan looks for. ⚡ <b>neg funding</b> = shorts are paying longs, squeeze fuel present. ⚠️ <b>overleveraged</b> = funding rate above 0.012%, too many crowded longs, risk of a sudden flush down.</InfoTip></th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && (
              <tr><td colSpan={9}><EmptyState title="No coins match." hint={squeezeOnly ? 'Squeeze-only is on — try turning it off.' : 'Lower the OI floor or widen filters.'} /></td></tr>
            )}
            {rows.map((c, i) => {
              const s = signalFor(c);
              return (
                <tr key={c.sym} className={s.cls} onClick={() => window.__openToken(c.sym)} title="Click to open full detail">
                  <td><WatchStar sym={c.sym} compact /></td>
                  <td className="mono dim">{String(i + 1).padStart(2, '0')}</td>
                  <td><span className="sym mono">{c.sym}</span></td>
                  <td><ScoreBadge coin={c} score={c.score1d} /></td>
                  <td style={{ textAlign: 'right' }}><FundingChip funding={c.funding} /></td>
                  <td className="mono" style={{ textAlign: 'right' }}>{fmtOi(c.oi)}</td>
                  <td><CloudBadge cloud={c.cloud} /></td>
                  <td><AdxBadge adx={c.adx} compact /></td>
                  <td className="mono signal-cell">{s.tag}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ─── 3f. Alerts ──────────────────────────────────────────────────────────────
function AlertsResults({ minScore }) {
  const { alerts } = window.ICHI_DATA;
  const newAbove = alerts.newAbove.filter(a => a.now >= minScore);
  const dropped = alerts.dropped;

  return (
    <div className="panel">
      <div className="panel-head">
        <h3>Alerts <span className="dim">— threshold crossings at {minScore}/18</span><InfoTip size="md"><span>Compares the current scan to the previous one. <b>NEW</b> = coins that just crossed above your minimum score threshold — fresh entry candidates. <b>DROPPED</b> = coins that just fell below it — exit or weakness warning. Use the Min chip to change the threshold.</span></InfoTip></h3>
        <div className="panel-meta mono">{alerts.aboveCount} above · {alerts.belowCount} below</div>
      </div>
      <div className="alerts-grid">
        <div className="alerts-col">
          <div className="alerts-col-head new">🔔 NEW <span className="dim">crossed above</span> <span className="count mono">{newAbove.length}</span></div>
          <div className="alerts-list">
            {newAbove.map(a => <AlertCard key={a.sym} a={a} dir="up" />)}
            {newAbove.length === 0 && <div className="empty mono">no new crossings this scan</div>}
          </div>
        </div>
        <div className="alerts-col">
          <div className="alerts-col-head dropped">📉 DROPPED <span className="dim">fell below</span> <span className="count mono">{dropped.length}</span></div>
          <div className="alerts-list">
            {dropped.map(a => <AlertCard key={a.sym} a={a} dir="down" />)}
            {dropped.length === 0 && <div className="empty mono">no drops this scan</div>}
          </div>
        </div>
      </div>
      <div className="alerts-summary mono dim">
        {alerts.aboveCount} symbols already above {minScore}/18 · {alerts.belowCount} below threshold · universe 200
      </div>
    </div>
  );
}

function AlertCard({ a, dir }) {
  const color = dir === 'up' ? '#00ff88' : '#ff3860';
  return (
    <div className="alert-card" onClick={() => window.__openToken(a.sym)} title="Click to open full detail" style={{ borderColor: color + '55', background: color + '0a' }}>
      <div className="alert-top">
        <span className="sym mono">{a.sym}</span>
        <span className="alert-arrow mono" style={{ color }}>
          {a.prev} <span className="dim">→</span> {a.now}
        </span>
      </div>
      <div className="alert-mid">
        <AdxBadge adx={a.adx} compact />
        <CloudBadge cloud={a.cloud} />
      </div>
      <div className="alert-flags"><Flags flags={a.flags} /></div>
    </div>
  );
}

// ─── Dispatcher ──────────────────────────────────────────────────────────────
function ResultsArea({ active }) {
  if (!active) return null;
  const { kind, opts } = active;
  switch (kind) {
    case 'daily':   return <DailyScanResults    minScore={opts.minScore} regime={opts.regime} watchOnly={opts.watchOnly} />;
    case 'mtf':     return <MultiTFResults watchOnly={opts.watchOnly} minAligned={opts.minAligned ?? 0} />;
    case 'coil':    return <CoiledSpringResults weeklyMin={opts.weeklyMin} dailyMax={opts.dailyMax} />;
    case 'sector':  return <SectorRotationResults />;
    case 'funding': return <FundingOIResults    topN={opts.topN} squeezeOnly={opts.squeezeOnly} watchOnly={opts.watchOnly} minScore={opts.minScore ?? 0} />;
    case 'alerts':  return <AlertsResults       minScore={opts.minScore} />;
    default: return null;
  }
}

Object.assign(window, { ResultsArea });
