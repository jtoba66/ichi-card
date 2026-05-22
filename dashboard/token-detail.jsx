// Token detail modal — full 18-rule scorecard + all stats for a coin.

const { useState: useStateT, useEffect: useEffectT } = React;

function TokenDetailHost() {
  const [sym, setSym] = useStateT(null);
  useEffectT(() => {
    window.__openToken  = (s) => setSym(s);
    window.__closeToken = () => setSym(null);
    const esc = (e) => { if (e.key === 'Escape') setSym(null); };
    window.addEventListener('keydown', esc);
    return () => window.removeEventListener('keydown', esc);
  }, []);
  if (!sym) return null;
  const coin = window.ICHI_DATA.COINS.find(c => c.sym === sym);
  if (!coin) return null;
  return ReactDOM.createPortal(<TokenDetail coin={coin} onClose={() => setSym(null)} />, document.body);
}

function CrossRef({ label, value, sub, tone }) {
  return (
    <div className="td-cross" style={{ '--accent': tone }}>
      <div className="td-cross-k mono dim">{label}</div>
      <div className="td-cross-v mono" style={{ color: tone }}>{value}</div>
      <div className="td-cross-sub mono dim">{sub}</div>
    </div>
  );
}

function TokenDetail({ coin, onClose }) {
  const rules = window.ICHI_DATA.rulesFor(coin);
  const sections = [...new Set(rules.map(r => r.sec))];
  const total = rules.filter(r => r.passed).length;
  const D = window.ICHI_DATA;
  const dailyRank = D.byScore1d.findIndex(c => c.sym === coin.sym) + 1;
  const bearRank = D.byBearScore.findIndex(c => c.sym === coin.sym) + 1;
  const mtfAligned = [coin.score4h, coin.score1d, coin.score1w].filter(s => s >= 11).length;
  const coilEntry = D.coiled.find(c => c.sym === coin.sym);
  const sectorMeta = D.sectorStats.find(s => s.sector === coin.sector);
  const alertStatus = D.alertStatusMap[coin.sym];

  return (
    <div className="td-overlay" onClick={onClose}>
      <div className="td-modal" onClick={e => e.stopPropagation()}>
        <header className="td-head">
          <div className="td-head-left">
            <div className="td-sym mono">{coin.sym}</div>
            <span className="sector-pill big">{coin.sector}</span>
            <span className="td-univ dim mono">Binance · USDT perp</span>
          </div>
          <div className="td-head-right">
            <div className="td-score-big mono" style={{ color: scoreColor(coin.score1d) }}>
              {coin.score1d}<span className="dim">/18</span>
            </div>
            <div className="td-score-lbl mono dim">1d bull score<InfoTip>The headline number — count of rules below in the bullish state on the daily timeframe.</InfoTip></div>
            <button className="td-close" onClick={onClose} aria-label="Close">✕</button>
          </div>
        </header>

        <div className="td-statgrid">
          <Stat label="1w score" tone={scoreColor(coin.score1w)} v={`${coin.score1w}/18`}
            tip="Weekly bull score. Macro / structural read — if 1w is high, the larger context favors the bull side regardless of short-term wobbles." />
          <Stat label="4h score" tone={scoreColor(coin.score4h)} v={`${coin.score4h}/18`}
            tip="4-hour bull score. Tactical timing layer for entries when daily and weekly agree." />
          <Stat label="Cloud" v={coin.cloud === 'IN' ? 'IN ☁' : coin.cloud === 'ABOVE' ? 'Above ☁' : 'Below ☁'} tone={coin.cloud === 'ABOVE' ? '#00ff88' : coin.cloud === 'IN' ? '#7c3aed' : '#ff3860'}
            tip="Price position vs the Ichimoku Kumo (cloud). Above = bullish, Below = bearish, IN = consolidation / decision zone." />
          <Stat label="Fwd cloud" v={coin.fwdCloud === 'BULL' ? '✓ Bull' : '✗ Bear'} tone={coin.fwdCloud === 'BULL' ? '#00ff88' : '#ff3860'}
            tip="Color of the projected cloud 26 bars into the future. ✓ Bull = green cloud ahead, meaning rising support is expected. ✗ Bear = red cloud ahead, meaning overhead resistance is building. Ichimoku draws this in advance so you can see structural support/resistance before price gets there." />
          <Stat label="ADX" v={coin.adx.toFixed(1)} tone={coin.adx >= 40 ? '#ff3860' : coin.adx >= 25 ? '#ffaa00' : '#888'}
            tip="Average Directional Index (14). Trend strength regardless of direction. ≥40 strong trend, 25–39 trending, <25 chop." />
          <Stat label="+DI / −DI" v={`${coin.plusDI.toFixed(1)} / ${coin.minusDI.toFixed(1)}`} tone={coin.plusDI > coin.minusDI ? '#00ff88' : '#ff3860'}
            tip="Directional movement components of ADX. +DI > −DI means up-trend dominant; reverse means down-trend dominant." />
          <Stat label="Funding" v={`${coin.funding >= 0 ? '+' : ''}${(coin.funding * 100).toFixed(3)}%`} tone={coin.funding < -0.005 ? '#4fc3f7' : coin.funding > 0.012 ? '#ffaa00' : '#bbb'}
            tip="8-hour perpetual funding rate. Positive = longs are paying shorts — market is crowded to the buy side. Negative = shorts are paying longs — bears are under pressure and any bullish catalyst can force them to buy back, causing a rapid price spike (a squeeze)." />
          <Stat label="Open Interest" v={fmtOi(coin.oi)} tone="#4fc3f7"
            tip="Total dollar value of all open perpetual futures positions. Higher OI = more money is at stake and a larger forced-buying (or forced-selling) event will happen if those positions unwind. A squeeze on high-OI coins moves further and faster." />
          <Stat label="Volume" v={`${coin.volMult.toFixed(1)}× SMA20`} tone={coin.volMult >= 1.5 ? '#4fc3f7' : '#888'}
            tip="Last bar's volume relative to its 20-bar simple moving average. ≥1.5× counts as a 'high volume' confirmation." />
          <Stat label="RSI Div" v={coin.rsiDiv ? (coin.rsiDiv === 'BULL' ? '↑ Bull' : '↓ Bear') : 'None'} tone={coin.rsiDiv === 'BULL' ? '#00ff88' : coin.rsiDiv === 'BEAR' ? '#ff3860' : '#888'}
            tip="RSI divergence in the last 30 bars. Bull div = price makes a lower low but RSI makes a higher low — momentum is recovering even as price dips, which signals hidden buying pressure. Bear div = price makes a higher high but RSI makes a lower high — price is rising on weakening momentum, a warning sign." />
          <Stat label="Rel Strength" v={coin.rs ? (coin.rs === 'STRONG' ? '↑ Strong' : '↓ Weak') : 'Neutral'} tone={coin.rs === 'STRONG' ? '#39ff14' : coin.rs === 'WEAK' ? '#ff8855' : '#888'}
            tip="Performance vs BTC over the last 14 days. Strong = outperforming; weak = underperforming. The leaders in any rotation print strong RS." />
          <Stat label="BB Squeeze" v={coin.squeeze ? '✓ Active' : '—'} tone={coin.squeeze ? '#7c3aed' : '#888'}
            tip="Bollinger Band width is in the bottom 20% of its 6-month range — volatility is compressed and an expansion is statistically due." />
          <Stat label="Bear score" v={`${coin.bearScore}/18`} tone={scoreColor(18 - coin.bearScore)}
            tip="Count of the 18 Ichimoku rules currently in a bearish state. High = multiple warning flags firing at once. The bear scan uses this number instead of the bull score." />
          <Stat label="Chikou angle" v={`${coin.chikouAngle >= 0 ? '+' : ''}${coin.chikouAngle.toFixed(1)}°`} tone={coin.chikouAngle > 10 ? '#00ff88' : coin.chikouAngle < -10 ? '#ff3860' : '#888'}
            tip="Slope of the Chikou Span in degrees. The Chikou is today's closing price plotted 26 bars back in time — think of it as overlaying the current price on top of the chart from a month ago. A rising angle means today's price is climbing above that historical level (bullish). A falling angle means it is sinking below it. Beyond ±10° is considered meaningful trend." />
        </div>

        <section className="td-section">
          <header className="td-section-head">
            <h4>18-Rule Scorecard<InfoTip>Each rule is a binary yes/no question about Ichimoku geometry. The headline score is the count of rules in the bullish state. Hover any rule's <span className="info-tip" style={{margin:'0 2px'}}>i</span> for what it measures.</InfoTip></h4>
            <div className="td-section-meta mono">{total} passed · {18 - total} failed</div>
          </header>
          <div className="td-rule-grid">
            {sections.map(sec => (
              <div key={sec} className="td-rule-section">
                <div className="td-rule-section-head mono">
                  <span className="td-rule-sec-name">{sec}</span>
                  <span className="dim">
                    {rules.filter(r => r.sec === sec && r.passed).length}/{rules.filter(r => r.sec === sec).length}
                  </span>
                </div>
                {rules.filter(r => r.sec === sec).map(r => (
                  <div key={r.id} className={'td-rule' + (r.passed ? ' pass' : ' fail')}>
                    <span className="td-rule-state mono">{r.passed ? '✓' : '✗'}</span>
                    <span className="td-rule-num mono dim">{String(r.id).padStart(2, '0')}</span>
                    <span className="td-rule-name">{r.name}</span>
                    <InfoTip>{r.tip}</InfoTip>
                  </div>
                ))}
              </div>
            ))}
          </div>
        </section>

        <section className="td-section">
          <header className="td-section-head">
            <h4>Active Signal Flags<InfoTip>Extra signals that fire on top of the 18-rule score when specific patterns are present — e.g. SQUEEZE (volatility compressed, expansion due), RSI-DIV↑ (price dipping but momentum recovering), RS:STRONG↑ (outperforming BTC), VOL 2×+ (volume spike). These same tags appear as coloured labels in the scanner tables.</InfoTip></h4>
          </header>
          <div className="td-flags-row">
            {coin.flags.length === 0
              ? <span className="dim mono">No flags firing</span>
              : <Flags flags={coin.flags} />}
          </div>
        </section>

        <section className="td-section">
          <header className="td-section-head">
            <h4>Across Scanners<InfoTip>Quick read of how {coin.sym} ranks in every scanner without leaving this view.</InfoTip></h4>
            <div className="td-section-meta mono"><WatchStar sym={coin.sym} /> watchlist</div>
          </header>
          <div className="td-cross-grid">
            <CrossRef label="Daily Scan" value={`#${dailyRank} of ${window.ICHI_DATA.COINS.length}`} sub={`bull score ${coin.score1d}/18`} tone={scoreColor(coin.score1d)} />
            <CrossRef label="Bear Rank" value={`#${bearRank} of ${window.ICHI_DATA.COINS.length}`} sub={`bear score ${coin.bearScore}/18`} tone={scoreColor(18 - coin.bearScore)} />
            <CrossRef label="Multi-TF" value={`${mtfAligned}/3 aligned`} sub={`1w ${coin.score1w} · 1d ${coin.score1d} · 4h ${coin.score4h}`} tone={mtfAligned === 3 ? '#00ff88' : mtfAligned === 2 ? '#ffaa00' : '#888'} />
            <CrossRef label="Coiled Spring" value={coilEntry ? coilEntry.coil.toFixed(1) : '—'} sub={coilEntry ? `compression ${(coin.score1w - coin.score1d)}` : 'not coiling'} tone={coilEntry ? '#7c3aed' : '#666'} />
            <CrossRef label="Sector" value={coin.sector} sub={sectorMeta ? `avg ${sectorMeta.avgBull.toFixed(1)} · ${sectorMeta.pctAbove11}% ≥11` : ''} tone="#4fc3f7" />
            <CrossRef label="Funding+OI" value={`${coin.funding >= 0 ? '+' : ''}${(coin.funding * 100).toFixed(3)}%`} sub={`OI ${fmtOi(coin.oi)}${coin.squeeze && coin.funding < 0 && coin.score1d >= 11 ? ' · 🔥 SQUEEZE' : ''}`} tone={coin.funding < -0.005 ? '#4fc3f7' : coin.funding > 0.012 ? '#ffaa00' : '#bbb'} />
            <CrossRef label="7d trend" value={`${coin.scoreTrend >= 0 ? '+' : ''}${coin.scoreTrend}`} sub={<Sparkline data={coin.scoreHist} width={70} height={16} />} tone={coin.scoreTrend > 0 ? '#00ff88' : coin.scoreTrend < 0 ? '#ff3860' : '#888'} />
            <CrossRef
              label="Alert status"
              value={alertStatus === 'new' ? '🔔 NEW crossing' : alertStatus === 'dropped' ? '📉 DROPPED' : '— stable'}
              sub={alertStatus === 'new' ? 'just crossed above threshold' : alertStatus === 'dropped' ? 'just fell below threshold' : 'no threshold change this scan'}
              tone={alertStatus === 'new' ? '#00ff88' : alertStatus === 'dropped' ? '#ff3860' : '#666'}
            />
          </div>
        </section>

        <footer className="td-foot mono dim">
          esc or click outside to close · 1d=daily · 4h=four-hour · 1w=weekly
        </footer>
      </div>
    </div>
  );
}

function Stat({ label, v, tone, tip }) {
  return (
    <div className="td-stat">
      <div className="td-stat-k mono dim">{label}<InfoTip>{tip}</InfoTip></div>
      <div className="td-stat-v mono" style={{ color: tone }}>{v}</div>
    </div>
  );
}

Object.assign(window, { TokenDetailHost, TokenDetail, CrossRef });
