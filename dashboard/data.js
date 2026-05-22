// Mock universe — deterministic so scores stay stable across reloads.
// 200 coins, 9 sectors. Scores 0–18. Ichimoku-flavored signal flags.

const SECTORS = {
  L1:      ['BTC','ETH','SOL','BNB','ADA','AVAX','DOT','ATOM','NEAR','APT','SUI','SEI','TON','TRX','XRP','ALGO','HBAR','EGLD','ICP','KAS','TIA','INJ','KAVA','FTM','XTZ','ZIL','ONE','FLOW'],
  L2:      ['ARB','OP','MATIC','MNT','STRK','METIS','LRC','IMX','SKL','MANTA','BLAST','ZK','SCR','LINEA','BASE','TAIKO'],
  DeFi:    ['UNI','AAVE','MKR','SNX','CRV','COMP','SUSHI','LDO','GMX','PENDLE','DYDX','1INCH','BAL','RUNE','CAKE','FXS','YFI','CVX','JOE','VELO','AERO','MORPHO','ENA','ETHFI'],
  Meme:    ['DOGE','SHIB','PEPE','WIF','BONK','FLOKI','MEME','BOME','MEW','POPCAT','BRETT','PNUT','GOAT','MOG','TURBO','NEIRO','PONKE','FARTCOIN','TRUMP','SLERF'],
  AI:      ['FET','TAO','RNDR','AGIX','WLD','OCEAN','GRT','AKT','ARKM','NMR','CTXC','PHB','AI','PAAL','PHA','TURING'],
  RWA:     ['ONDO','POLYX','MKR','PENDLE','OM','TRU','LCX','RIO','TOKEN','PROPS','REQ'],
  Gaming:  ['AXS','SAND','MANA','GALA','APE','ENJ','PIXEL','RON','BEAM','GMT','MAGIC','ILV','PRIME','GHST','MAVIA','XAI','PORTAL','ACE','ALICE'],
  Infra:   ['LINK','FIL','AR','THETA','HNT','RLC','ANKR','LPT','API3','BAND','NKN','POKT','POWR','IOTA','STORJ','HOLO','OCEAN','MASK','RSS3'],
  Privacy: ['XMR','ZEC','DASH','SCRT','ROSE','RAILGUN','OXT','KEEP','FIRO'],
};

// Flatten to a unique universe; preserve first sector seen for sector mapping.
const SECTOR_OF = {};
const UNIVERSE = [];
for (const [sector, syms] of Object.entries(SECTORS)) {
  for (const s of syms) {
    if (!SECTOR_OF[s]) {
      SECTOR_OF[s] = sector;
      UNIVERSE.push(s);
    }
  }
}

// Deterministic PRNG from string
function hash(str, salt = 0) {
  let h = 2166136261 ^ salt;
  for (let i = 0; i < str.length; i++) {
    h ^= str.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return ((h >>> 0) % 100000) / 100000;
}

function rand(sym, salt) { return hash(sym + ':' + salt, salt * 31); }

function pick(sym, salt, arr) {
  return arr[Math.floor(rand(sym, salt) * arr.length)];
}

// Build a per-coin record
function buildCoin(sym) {
  const sector = SECTOR_OF[sym];
  // Bias L1/L2/DeFi to slightly stronger scores; memes more volatile.
  const sectorBias = { L1: 2, L2: 1.5, DeFi: 1, Infra: 0.5, AI: 1.2, RWA: 0.8, Gaming: -0.5, Meme: 0, Privacy: -1 }[sector] || 0;

  const score4h = Math.max(0, Math.min(18, Math.round(rand(sym, 1) * 18 + sectorBias - 1)));
  const score1d = Math.max(0, Math.min(18, Math.round(rand(sym, 2) * 18 + sectorBias)));
  const score1w = Math.max(0, Math.min(18, Math.round(rand(sym, 3) * 18 + sectorBias + 0.5)));

  const adx = Math.round((rand(sym, 4) * 50 + 8) * 10) / 10;
  const plusDI = Math.round((15 + rand(sym, 5) * 35) * 10) / 10;
  const minusDI = Math.round((10 + rand(sym, 6) * 30) * 10) / 10;

  // cloud relationship
  const cloud = pick(sym, 7, ['ABOVE', 'ABOVE', 'ABOVE', 'IN', 'BELOW']);
  const fwdCloud = rand(sym, 8) > 0.4 ? 'BULL' : 'BEAR';

  const volMult = Math.round((0.6 + rand(sym, 9) * 2.4) * 10) / 10;
  const rsiDiv = rand(sym, 10) > 0.78 ? 'BULL' : rand(sym, 11) > 0.92 ? 'BEAR' : null;
  const rs = rand(sym, 12) > 0.65 ? 'STRONG' : rand(sym, 13) > 0.7 ? 'WEAK' : null;
  const squeeze = rand(sym, 14) > 0.78;

  // funding rate -2% .. +1.5%
  const funding = Math.round(((rand(sym, 15) - 0.6) * 0.025) * 10000) / 10000;
  // OI: $5M to $4.2B, with BTC/ETH dominating
  const oiBase = { BTC: 4200, ETH: 2800, SOL: 1400, BNB: 720 }[sym] ?? (10 + rand(sym, 16) * 600);
  const oi = Math.round(oiBase * 1e6);

  // 7-day daily score history (oldest → newest). Last entry == score1d.
  const scoreHist = [];
  for (let i = 6; i >= 0; i--) {
    const drift = (rand(sym, 30 + i) - 0.5) * 6;
    const s = Math.max(0, Math.min(18, Math.round(score1d + drift)));
    scoreHist.push(s);
  }
  scoreHist[6] = score1d;
  const scoreTrend = scoreHist[6] - scoreHist[0];

  const flags = [];
  if (squeeze) flags.push('SQUEEZE');
  if (volMult >= 1.5) flags.push(`VOL ${volMult.toFixed(1)}x`);
  if (rsiDiv === 'BULL') flags.push('RSI-DIV↑');
  if (rsiDiv === 'BEAR') flags.push('RSI-DIV↓');
  if (rs === 'STRONG') flags.push('RS:STRONG↑');
  if (rs === 'WEAK') flags.push('RS:WEAK↓');

  // Bear score: roughly the inverse of bull, with independent noise so they're not perfectly mirrored
  const bearScore = Math.max(0, Math.min(18, Math.round(18 - score1d + Math.round((rand(sym, 17) - 0.5) * 5))));
  // Chikou angle in degrees: slope of the lagged-close line. Positive = rising, negative = dropping.
  const chikouAngle = Math.round((rand(sym, 18) - 0.35) * 80);

  return {
    sym, sector,
    score4h, score1d, score1w, bearScore,
    adx, plusDI, minusDI,
    cloud, fwdCloud,
    volMult, rsiDiv, rs, squeeze, chikouAngle,
    funding, oi,
    flags,
    scoreHist, scoreTrend,
  };
}

const COINS = UNIVERSE.map(buildCoin);

// Sort canonical lists for the dashboard
const byScore1d = [...COINS].sort((a, b) => b.score1d - a.score1d);
const topBull = byScore1d[0];
const byBearScore = [...COINS].sort((a, b) => b.bearScore - a.bearScore);
const topBear = byBearScore[0];

// Coil score: 1w high (≥11) and 1d low (≤7) → laggard primed
function coilScore(c) {
  if (c.score1w < 10 || c.score1d > 8) return null;
  // higher when weekly is strong, daily is depressed, and ADX is bottoming
  const compression = (c.score1w - c.score1d);
  const adxBonus = c.adx < 20 ? 2 : 0;
  const cloudBonus = c.cloud === 'IN' ? 3 : 0;
  return Math.round((compression + adxBonus + cloudBonus) * 10) / 10;
}
const coiled = COINS
  .map(c => ({ ...c, coil: coilScore(c) }))
  .filter(c => c.coil != null && c.coil >= 4)
  .sort((a, b) => b.coil - a.coil);

const squeezeSetups = COINS.filter(c => c.squeeze && c.funding < 0 && c.score1d >= 11);

// Sector aggregates
const sectorStats = Object.keys(SECTORS).map(sector => {
  const members = COINS.filter(c => c.sector === sector);
  const avgBull = members.reduce((s, c) => s + c.score1d, 0) / members.length;
  const pctAbove11 = members.filter(c => c.score1d >= 11).length / members.length;
  const avgAdx = members.reduce((s, c) => s + c.adx, 0) / members.length;
  const top = [...members].sort((a, b) => b.score1d - a.score1d).slice(0, 4);
  return {
    sector,
    members: members.length,
    avgBull: Math.round(avgBull * 10) / 10,
    pctAbove11: Math.round(pctAbove11 * 100),
    avgAdx: Math.round(avgAdx * 10) / 10,
    top,
  };
}).sort((a, b) => b.avgBull - a.avgBull);

// Alerts simulation: pretend previous scan had different scores
const alerts = (() => {
  const newAbove = [];
  const dropped = [];
  let above = 0, below = 0;
  const threshold = 11;
  for (const c of COINS) {
    const prev = Math.max(0, Math.min(18, c.score1d + Math.round((rand(c.sym, 20) - 0.5) * 6)));
    const now = c.score1d;
    if (now >= threshold && prev < threshold) newAbove.push({ ...c, prev, now });
    if (now < threshold && prev >= threshold) dropped.push({ ...c, prev, now });
    if (now >= threshold) above++; else below++;
  }
  const sortedNew = newAbove.sort((a, b) => b.now - a.now).slice(0, 8);
  const sortedDrop = dropped.sort((a, b) => a.now - b.now).slice(0, 8);
  return {
    threshold,
    newAbove: sortedNew,
    dropped: sortedDrop,
    aboveCount: above,
    belowCount: below,
  };
})();

// Quick lookup: 'new' | 'dropped' | undefined (stable) per symbol
const alertStatusMap = {};
for (const a of alerts.newAbove) alertStatusMap[a.sym] = 'new';
for (const a of alerts.dropped)  alertStatusMap[a.sym] = 'dropped';

window.ICHI_DATA = {
  UNIVERSE, COINS, SECTOR_OF, SECTORS: Object.keys(SECTORS),
  byScore1d, topBull, byBearScore, topBear,
  coiled, squeezeSetups, sectorStats, alerts, alertStatusMap,
};

// ─── 18-rule scorecard definitions ───────────────────────────────────────────
// Sectioned per LuxAlgo "Ichimoku Theories" layout: Cloud, TK/KJ, Chikou,
// Sanyaku/Structure, Confirmation.
const RULES = [
  { id: 1,  sec: 'Cloud',         name: 'Price above Kumo',        tip: 'Current close is above both Span A and Span B. Most fundamental bullish condition — if false, every other rule is on shakier ground.' },
  { id: 2,  sec: 'Cloud',         name: 'Future cloud bullish',    tip: 'Looking 26 bars ahead, Span A > Span B (green cloud projected). Forward-looking signal that the structural bid will persist.' },
  { id: 3,  sec: 'Cloud',         name: 'Forward cloud thick',     tip: 'Projected cloud thickness ≥ 1% of price. A thin cloud is brittle; a thick cloud is durable support / hard resistance.' },
  { id: 4,  sec: 'Cloud',         name: 'SSB rising',              tip: 'Senkou Span B slope is positive over the last 10 bars. SSB rising = the slow base of the cloud is curling up — the highest-confidence trend confirmation Ichimoku gives.' },
  { id: 5,  sec: 'Cloud',         name: 'Cloud curling up',        tip: 'Span A has just crossed above Span B or the cloud edges are turning higher — early signal the Kumo is flipping bullish.' },
  { id: 6,  sec: 'Cloud',         name: 'Away from Span B',        tip: 'Price is ≥ 3% above SSB. Avoids low-quality entries right on top of the cloud where reversion risk is highest.' },
  { id: 7,  sec: 'TK / KJ',       name: 'TK above KJ',             tip: 'Tenkan (9) is above Kijun (26) with no bearish cross in the last 10 bars. The classic momentum filter.' },
  { id: 8,  sec: 'TK / KJ',       name: 'TK slope rising',         tip: 'Tenkan slope ≥ +0.33% over 5 bars. Faster line is accelerating up — fresh momentum, not stale.' },
  { id: 9,  sec: 'TK / KJ',       name: 'TK angle ≥ 10°',          tip: 'Geometric angle of TK relative to price axis ≥ 10°. Filters out drift; demands real velocity.' },
  { id: 10, sec: 'TK / KJ',       name: 'Kijun flat or rising',    tip: 'Kijun is not falling. Flat = equilibrium support, rising = trend confirmed. Falling KJ is a hard veto.' },
  { id: 11, sec: 'Chikou',        name: 'Chikou cleared price',    tip: 'The Chikou Span (today\'s price overlaid 26 bars back) is trading above all recent price peaks in that historical window. This matters because when the Chikou sits below old price clusters it acts as a ceiling — clearing them removes that overhead obstacle.' },
  { id: 12, sec: 'Chikou',        name: 'Chikou clear of cloud',   tip: 'Chikou is not stuck inside the past cloud. A chikou trapped in old kumo is a known reversal pattern.' },
  { id: 13, sec: 'Chikou',        name: 'No bearish CS trap',      tip: 'The Chikou Span has not just completed a false breakdown — where it briefly drops below old price levels then snaps back. That reversal pattern signals fading momentum even when the rest of the score looks bullish, so this rule vetoes it.' },
  { id: 14, sec: 'Sanyaku',       name: 'Sanyaku Koten active',    tip: 'All three core Ichimoku conditions are true at once: price is above the cloud (structural uptrend), Tenkan is above Kijun (short-term momentum is up), and the Chikou is above the price from 26 bars ago (historical momentum confirms). This simultaneous three-way alignment is the standard Ichimoku buy signal.' },
  { id: 15, sec: 'Sanyaku',       name: 'Triple sweep base',       tip: 'Price has tested a prior support level three times without breaking below it, then reclaimed that level. This repeated testing-and-holding shows strong buyer absorption at that price — a foundation is being built rather than broken.' },
  { id: 16, sec: 'Sanyaku',       name: 'No fakeout (10 bars)',    tip: 'No false breakdown then reversal in the last 10 bars. Filters out chop-prone names.' },
  { id: 17, sec: 'Confirm',       name: 'Volume confirming',       tip: 'Volume on the most recent up-bar is ≥ 1.5× its 20-bar SMA. Real participation, not a drift higher on no flow.' },
  { id: 18, sec: 'Confirm',       name: 'No bearish RSI div',      tip: 'No bearish RSI divergence in the last 30 bars. Bearish divergence is when price makes higher highs but RSI makes lower highs — it means upward price movement is happening on weakening momentum, which historically precedes reversals. Finding this pattern on an otherwise-strong setup is a serious warning sign, so this rule blocks the score.' },
];

// Compute pass/fail per rule for a coin, deterministically biased by its score.
function rulesFor(coin) {
  const target = coin.score1d;  // how many rules should pass (roughly)
  // Probability each rule passes, with structural bias by section.
  const sectionBias = { Cloud: 1.0, 'TK / KJ': 0.95, Chikou: 0.85, Sanyaku: 0.7, Confirm: 0.9 };
  const out = [];
  let passed = 0;
  for (const r of RULES) {
    const h = hash(coin.sym + ':rule:' + r.id, r.id);
    // Sort rules by hash, pick top `target` to be bullish — but weight by section.
    const score = h * sectionBias[r.sec];
    out.push({ ...r, _score: score });
  }
  out.sort((a, b) => b._score - a._score);
  for (let i = 0; i < out.length; i++) {
    out[i].passed = i < target;
  }
  out.sort((a, b) => a.id - b.id);
  return out;
}

window.ICHI_DATA.RULES = RULES;
window.ICHI_DATA.rulesFor = rulesFor;
