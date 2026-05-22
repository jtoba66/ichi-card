// Live data loader — fetches from FastAPI backend, builds window.ICHI_DATA
// in the same shape that data.js produced so all dashboard components work unchanged.

const API_BASE = (() => {
  // When served by the Python static server on port 7890, point to the FastAPI server.
  if (window.location.port === '7890' || window.location.protocol === 'file:') {
    return 'http://localhost:8000';
  }
  // Otherwise assume same origin (prod VPS with nginx proxy).
  return '';
})();

// ─── 18 canonical scoring rules (matches registry.py scoring_rule_ids exactly) ─
const RULES = [
  { id: 1,  rule_id: 'above_cloud',    sec: 'Cloud',    name: 'Price above Kumo',       tip: 'Close is above both Span A and Span B. The most fundamental bullish condition — everything else is on shakier ground without this.' },
  { id: 2,  rule_id: 'kumo_bullish',   sec: 'Cloud',    name: 'Cloud bullish (A > B)',  tip: 'Span A is currently above Span B — the cloud at the current bar is green. A red cloud is outright bearish structure regardless of price position.' },
  { id: 3,  rule_id: 'above_kijun',   sec: 'Cloud',    name: 'Price above Kijun',      tip: 'Close is above the Kijun-sen (26-bar midpoint). Kijun acts as a magnet and equilibrium level — price above it means bulls control the mid-term anchor.' },
  { id: 4,  rule_id: 'full_bull',      sec: 'Cloud',    name: 'Full bull alignment',    tip: 'Price is above the cloud, Tenkan is above Kijun, and Chikou is above the historical price — all three simultaneous. The textbook Ichimoku buy confirmation.' },
  { id: 5,  rule_id: 'bull_stack',     sec: 'TK / KJ',  name: 'Bull stack',             tip: 'Price, Tenkan, and Kijun are stacked in the correct bull order (price > TK > KJ or close to it). When the stack is intact, pullbacks are shallower and cleaner.' },
  { id: 6,  rule_id: 'tk_bullish',     sec: 'TK / KJ',  name: 'Tenkan bullish',         tip: 'Tenkan-sen (9-bar midpoint) is rising and above Kijun. The faster line leading confirms short-term momentum is healthy.' },
  { id: 7,  rule_id: 'tk_rising',      sec: 'TK / KJ',  name: 'TK slope rising',        tip: 'Tenkan slope ≥ +0.33% over 5 bars. Demanding actual acceleration, not a flat or drifting line.' },
  { id: 8,  rule_id: 'kj_rising',      sec: 'TK / KJ',  name: 'KJ slope rising',        tip: 'Kijun-sen is rising over the last 5 bars. A rising Kijun means the 26-bar equilibrium itself is moving up — a strong structural signal.' },
  { id: 9,  rule_id: 'both_rising',    sec: 'TK / KJ',  name: 'Both TK & KJ rising',    tip: 'Tenkan AND Kijun are both sloping upward simultaneously. When both lines rise together, momentum is broad-based rather than just one component leading.' },
  { id: 10, rule_id: 'no_tk_cross',    sec: 'TK / KJ',  name: 'No bearish TK cross',    tip: 'Tenkan has not crossed below Kijun in the last 10 bars. A recent TK death cross is a hard warning even if price looks ok — this rule blocks it.' },
  { id: 11, rule_id: 'angle_gte10',    sec: 'TK / KJ',  name: 'TK angle ≥ 10°',         tip: 'Geometric angle of Tenkan relative to the price axis is at least 10°. Filters out coins that are drifting sideways with a flat TK — demands real velocity.' },
  { id: 12, rule_id: 'tk_bounce',      sec: 'Chikou',   name: 'TK bounce support',      tip: 'Price recently bounced off the Tenkan-sen and held. This pattern shows the TK line is acting as live support rather than just a passive indicator.' },
  { id: 13, rule_id: 'chikou_cleared', sec: 'Chikou',   name: 'Chikou cleared price',   tip: 'The Chikou Span (today\'s close overlaid 26 bars back) is above all recent price highs in that window. When the Chikou sits below old price clusters it acts as a ceiling — clearing them removes that overhead obstacle.' },
  { id: 14, rule_id: 'above_price',    sec: 'Chikou',   name: 'Chikou above price',     tip: 'Chikou Span is above the high of the price bar at the same historical position. A stricter version of chikou clearance — must be above the candle high, not just the close.' },
  { id: 15, rule_id: 'triple_sweep',   sec: 'Sanyaku',  name: 'Triple sweep base',      tip: 'Price has tested a prior support level three times without breaking below it, then reclaimed that level. Repeated testing-and-holding shows strong buyer absorption — a foundation being built rather than broken.' },
  { id: 16, rule_id: 'obv_rising',     sec: 'Confirm',  name: 'OBV rising',             tip: 'On-Balance Volume is trending upward over the last 10 bars. OBV confirms that volume flows are accumulating, not distributing, behind the price move.' },
  { id: 17, rule_id: 'high_volume',    sec: 'Confirm',  name: 'Volume confirming',      tip: 'Volume on the most recent up-bar is ≥ 1.5× its 20-bar average. Real participation — not a drift higher on thin air.' },
  { id: 18, rule_id: 'no_div',         sec: 'Confirm',  name: 'No bearish RSI div',     tip: 'No bearish RSI divergence in the last 30 bars. Bearish divergence (price makes a higher high while RSI makes a lower high) signals weakening momentum behind an apparently strong move — a serious warning sign that blocks the score.' },
];

// rulesFor: match by rule_id against actual API results.
function rulesFor(coin) {
  const tf1d = coin._raw1d;
  if (tf1d && tf1d.rules && Array.isArray(tf1d.rules)) {
    const ruleMap = {};
    for (const r of tf1d.rules) ruleMap[r.rule_id] = r;
    return RULES.map(r => ({ ...r, passed: ruleMap[r.rule_id]?.qualifies_bull ?? false }));
  }
  // Fallback: approximate from bull score when no rule detail available
  const target = coin.score1d;
  function hash(str, salt = 0) {
    let h = 2166136261 ^ salt;
    for (let i = 0; i < str.length; i++) { h ^= str.charCodeAt(i); h = Math.imul(h, 16777619); }
    return ((h >>> 0) % 100000) / 100000;
  }
  const sectionBias = { Cloud: 1.0, 'TK / KJ': 0.95, Chikou: 0.85, Sanyaku: 0.7, Confirm: 0.9 };
  const out = RULES.map(r => ({ ...r, _score: hash((coin.sym || '') + ':rule:' + r.id, r.id) * sectionBias[r.sec] }));
  out.sort((a, b) => b._score - a._score);
  for (let i = 0; i < out.length; i++) out[i].passed = i < target;
  out.sort((a, b) => a.id - b.id);
  return out;
}

// ─── Map raw API coin → dashboard coin shape ──────────────────────────────────
function adaptCoin(raw) {
  const tf1d = raw['1d'] || {};
  const tf4h = raw['4h'] || {};
  const tf1w = raw['1w'] || {};

  const score1d = tf1d.bull ?? raw.bull ?? 0;
  const score4h = tf4h.bull ?? 0;
  const score1w = tf1w.bull ?? 0;
  const bearScore = tf1d.bear ?? raw.bear ?? 0;

  // History: [{date, bull, bear}] → extract just bull scores oldest-first, pad to 7
  const hist = (raw.history || []).slice(-7);
  const scoreHist = Array(Math.max(0, 7 - hist.length)).fill(score1d).concat(hist.map(h => h.bull ?? 0));
  const scoreTrend = scoreHist[6] - scoreHist[0];

  // Derive rsiDiv from flags or bullish/bearish_div booleans
  let rsiDiv = null;
  if (raw.bullish_div) rsiDiv = 'BULL';
  else if (raw.bearish_div) rsiDiv = 'BEAR';

  // Derive rs from rs_label
  let rs = null;
  if (raw.rs_label && raw.rs_label.includes('STRONG')) rs = 'STRONG';
  else if (raw.rs_label && raw.rs_label.includes('WEAK')) rs = 'WEAK';

  // plusDI / minusDI
  const plusDI = tf1d.plus_di ?? raw.plus_di ?? 20;
  const minusDI = tf1d.minus_di ?? raw.minus_di ?? 15;

  // Funding: API returns 8h raw rate (e.g. 0.0001). Keep as-is.
  const funding = raw.funding_rate ?? 0;
  const oi = raw.oi_usd ?? 0;

  const coin = {
    sym: raw.symbol,
    sector: raw.sector || 'Other',
    score1d,
    score4h,
    score1w,
    bearScore,
    adx: raw.adx ?? tf1d.adx ?? 0,
    plusDI,
    minusDI,
    cloud: (['ABOVE','IN','BELOW'].includes(raw.cloud) ? raw.cloud : (tf1d.cloud || 'IN')),
    fwdCloud: (raw.fwd_cloud === 'BULL' || raw.fwd_cloud === 'BEAR') ? raw.fwd_cloud : (tf1d.fwd_cloud || 'BULL'),
    volMult: raw.vol_ratio ?? tf1d.vol_ratio ?? 1.0,
    rsiDiv,
    rs,
    squeeze: raw.bb_squeeze ?? tf1d.bb_squeeze ?? false,
    chikouAngle: raw.chikou ?? tf1d.chikou ?? 0,
    funding,
    oi,
    flags: raw.flags ?? tf1d.flags ?? [],
    scoreHist,
    scoreTrend,
    // Keep raw TF data for rulesFor
    _raw1d: tf1d,
    _raw4h: tf4h,
    _raw1w: tf1w,
    _rawFundingRate: raw.funding_rate,
  };
  return coin;
}

// ─── Derived aggregates (mirrors data.js logic) ───────────────────────────────
function coilScore(c) {
  if (c.score1w < 10 || c.score1d > 8) return null;
  const compression = c.score1w - c.score1d;
  const adxBonus = c.adx < 20 ? 2 : 0;
  const cloudBonus = c.cloud === 'IN' ? 3 : 0;
  return Math.round((compression + adxBonus + cloudBonus) * 10) / 10;
}

function buildIchiData(coins) {
  const UNIVERSE = coins.map(c => c.sym);
  const SECTOR_OF = {};
  const sectorSet = new Set();
  for (const c of coins) {
    SECTOR_OF[c.sym] = c.sector;
    sectorSet.add(c.sector);
  }
  const SECTORS = [...sectorSet].sort();

  const byScore1d = [...coins].sort((a, b) => b.score1d - a.score1d);
  const topBull = byScore1d[0] || null;
  const byBearScore = [...coins].sort((a, b) => b.bearScore - a.bearScore);
  const topBear = byBearScore[0] || null;

  const coiled = coins
    .map(c => ({ ...c, coil: coilScore(c) }))
    .filter(c => c.coil != null && c.coil >= 4)
    .sort((a, b) => b.coil - a.coil);

  const squeezeSetups = coins.filter(c => c.squeeze && c.funding < 0 && c.score1d >= 11);

  const sectorMap = {};
  for (const c of coins) {
    if (!sectorMap[c.sector]) sectorMap[c.sector] = [];
    sectorMap[c.sector].push(c);
  }
  const sectorStats = Object.entries(sectorMap).map(([sector, members]) => {
    const avgBull = members.reduce((s, c) => s + c.score1d, 0) / members.length;
    const pctAbove11 = members.filter(c => c.score1d >= 11).length / members.length;
    const avgAdx = members.reduce((s, c) => s + c.adx, 0) / members.length;
    const top = [...members].sort((a, b) => b.score1d - a.score1d).slice(0, 4);
    return { sector, members: members.length, avgBull: Math.round(avgBull * 10) / 10, pctAbove11: Math.round(pctAbove11 * 100), avgAdx: Math.round(avgAdx * 10) / 10, top };
  }).sort((a, b) => b.avgBull - a.avgBull);

  // Alerts: compare current score vs oldest history entry (7 days ago)
  const threshold = 11;
  const newAbove = [], dropped = [];
  let aboveCount = 0, belowCount = 0;
  for (const c of coins) {
    const now = c.score1d;
    // Use second-to-last history entry as "previous" if available
    const prev = c.scoreHist.length >= 2 ? c.scoreHist[c.scoreHist.length - 2] : now;
    if (now >= threshold && prev < threshold) newAbove.push({ ...c, prev, now });
    if (now < threshold && prev >= threshold) dropped.push({ ...c, prev, now });
    if (now >= threshold) aboveCount++; else belowCount++;
  }
  const alerts = {
    threshold,
    newAbove: newAbove.sort((a, b) => b.now - a.now).slice(0, 8),
    dropped: dropped.sort((a, b) => a.now - b.now).slice(0, 8),
    aboveCount,
    belowCount,
  };

  const alertStatusMap = {};
  for (const a of alerts.newAbove) alertStatusMap[a.sym] = 'new';
  for (const a of alerts.dropped) alertStatusMap[a.sym] = 'dropped';

  return { UNIVERSE, COINS: coins, SECTOR_OF, SECTORS, byScore1d, topBull, byBearScore, topBear, coiled, squeezeSetups, sectorStats, alerts, alertStatusMap, RULES, rulesFor };
}

// ─── Public API ───────────────────────────────────────────────────────────────

// Poll until scan is ready, then resolve with ICHI_DATA.
// No hard timeout — first cold scan can take 5–10 min. Polls until ready or error.
window.loadData = function () {
  return new Promise((resolve, reject) => {
    const POLL_MS = 4000;
    let consecutiveFails = 0;
    const MAX_FAILS = 5; // give up only after 5 consecutive network failures

    function poll() {
      fetch(API_BASE + '/api/data')
        .then(r => r.json())
        .then(resp => {
          consecutiveFails = 0;
          if (resp.status === 'ready' && resp.coins && resp.coins.length > 0) {
            const adapted = resp.coins.map(adaptCoin);
            window.ICHI_DATA = buildIchiData(adapted);
            window.ICHI_DATA._scannedAt = resp.scanned_at;
            resolve(window.ICHI_DATA);
          } else if (resp.status === 'error') {
            reject(new Error('Scan error: ' + (resp.error || 'unknown')));
          } else {
            setTimeout(poll, POLL_MS);
          }
        })
        .catch(err => {
          consecutiveFails++;
          if (consecutiveFails >= MAX_FAILS) {
            reject(new Error('API unreachable after ' + MAX_FAILS + ' attempts: ' + err.message));
          } else {
            setTimeout(poll, POLL_MS);
          }
        });
    }

    poll();
  });
};

window.refreshData = function () {
  return fetch(API_BASE + '/api/refresh', { method: 'POST' }).then(r => r.json());
};

window.API_BASE = API_BASE;
