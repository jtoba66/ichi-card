# ichi-scorecard — Project State
_Last updated: 2026-05-13_

---

## What This Is

A rule-based Ichimoku scoring engine for crypto. Every symbol gets scored 0–18 on a set of bull/bear rules derived from the Ichimoku system.

**Identity shift (2026-05-11): this is a high-conviction filter, not a general scanner.**

Walk-forward validation on 3 years / 48 symbols / 7 OOS windows established:
- Score ≥13/18: 100% positive OOS windows, mean WF IC +0.055, mean 30d return +12% vs +4.5% universe
- Score <13: walk-forward IC near-zero or negative — noise, not signal
- The score below 13 has no confirmed predictive value. Don't act on it.

The threshold is a **stability cliff, not a mean IC cliff**: at 13, WF std drops to 0.030 (lowest in sweep) and all 7 windows stay positive. At ≥14 the mean return is higher (+13%) but variance explodes (std 0.099) because sample sizes shrink.

Use the dashboard as: "what crossed ≥13 today?" — typically 0–5 coins. That's the output. A long list is a misconfigured filter.

Snapshot on file: `data/snapshot_1d_3y.parquet` (48 symbols, 3y, 40,922 rows). Run `ichi evaluate --load data/snapshot_1d_3y.parquet` to reproduce.

---

## Architecture Overview

```
Exchange APIs (CCXT)
       │
  data/fetcher.py  ←→  data/cache.py (parquet files)
       │
  data/universe.py  (CoinGecko top-200 + exchange discovery)
       │
  indicators/ichimoku.py  →  indicators/precompute.py
       │
  rules/registry.py  →  scoring/engine.py
       │
  cli/<command>.py          api/main.py (FastAPI)
                                 │
                            dashboard/  (React 18 + Babel CDN)
                             api.js → app.jsx → scanners.jsx
                                        token-detail.jsx
                                        components.jsx
```

---

## Core Stack

| Layer | Tool | Why |
|---|---|---|
| Data fetch | CCXT | multi-exchange, unified API |
| Universe | CoinGecko free `/coins/markets` | ranked by market cap |
| Storage | Parquet via pandas | fast incremental updates |
| Indicators | Pure pandas/numpy | no TA-Lib dependency |
| CLI | Click | simple command composition |
| Concurrency | ThreadPoolExecutor | parallel symbol scoring |
| API server | FastAPI + uvicorn | serves live scan data to dashboard |
| Dashboard | React 18 + Babel standalone (CDN) | no build step, single-file JSX |

---

## Dashboard

**Status: Live — serving real Binance data**

Located at `dashboard/`. Served by `python3 -m http.server 7890 --directory dashboard` on port 7890. The React app fetches from the FastAPI backend on port 8000.

### Dashboard A — Scanners
| Panel | Description |
|---|---|
| Daily Scan | Ranked bull/bear score table with regime filter (ALL/TRENDING/STRONG), watchlist filter, bear mode toggle |
| Multi-TF Scan | 4h/1d/1w scores side by side, `Align≥` filter, highlighted fully-aligned rows |
| Coiled Spring | Laggard cards: strong weekly + compressed daily, coil score formula |
| Sector Rotation | Sector leaderboard + drill-down with top coins per sector |
| Funding + OI | Perp funding rate, OI, squeeze/neg-funding/overleveraged signal rows |
| Alerts | Threshold crossings (NEW / DROPPED) vs previous scan |

### Dashboard B — Reversal & Event Detection
A second dashboard mode toggled via the TopBar A/B button (persisted to `localStorage`). Shows pattern-detection events rather than raw scores.

| Panel | Description |
|---|---|
| Kumo Breakout Transitions | Coins just transitioning ABOVE/BELOW cloud with bull score + conditions (TK, CS, Cloud) |
| Line & Cloud Retests | Price testing TK, KJ, cloud top, cloud bottom — retest type + bounce history |
| TK/KJ Balance Point | Flat Kijun + price near it — balance score, proximity %, ADX |
| Kumo Twists | Upcoming Span A/B crossovers in the projected cloud — bars until, current twist direction |
| E2E Opportunities | Edge-to-edge cloud trade setups — entry zone, target, R/R ratio |
| Cloud Curling | Span B flattening/turning — direction, strength, bars since curl started |
| MTF Event Bar | Always-visible full-width panel: per-coin event count across all scanners and timeframes |

Notification system: `alerts.js` polls `/api/events/poll` every 5 min, deduplicates by `symbol:timeframe:type`, fires `ichi:events` CustomEvent and `ichi:notif-update`. Bell icon in TopBar opens `NotifCenter` drawer with timestamped history (max 200), mark-all-read, and clear.

### Dashboard files
| File | Purpose |
|---|---|
| `ichi-scorecard.html` | Entry point: CSS variables, layout, all `<style>` |
| `api.js` | Fetches from FastAPI, adapts API coin shape → dashboard shape, builds `window.ICHI_DATA` |
| `components.jsx` | Shared: `InfoTip`, `SortHeader`, `ScoreLegend`, `Sparkline`, `WatchStar`, score colours |
| `app.jsx` | `AppLoader` (loading/error shell), `App`, `TopBar` (A/B toggle + bell), `DashBTFSelector`, `NotifCenter` |
| `scanners.jsx` | All 6 scanner result panels + `ResultsArea` router |
| `token-detail.jsx` | Full token detail modal: 18-rule grid, stat bar, cross-scanner refs, Cmd-K palette |
| `dashboard-b.jsx` | Dashboard B: 6 `BEventCard` panels, `MTFEventBar`, all tables with hover tooltips on abbreviations |
| `alerts.js` | Standalone IIFE: polling loop, deduplication, toast/sound/browser-notif, `IchiAlerts` API |

### Running
```bash
# Terminal 1 — API server (auto-scans on startup)
cd ichi-scorecard
uv run python -m uvicorn ichi.api.main:app --port 8000

# Terminal 2 — Static file server
python3 -m http.server 7890 --directory ichi-scorecard/dashboard
```

Then open: http://localhost:7890/ichi-scorecard.html

---

## API Layer (`src/ichi/api/`)

**Status: Working**

| File | Purpose |
|---|---|
| `api/scanner.py` | `run_full_scan()` — 3 TF scans (1d/4h/1w) concurrently; `run_event_scan()` — runs 6 event detectors across all symbols × `[1d, 4h]` TFs |
| `api/history.py` | File-based 7-day score history at `data/score_history.json` for sparkline data |
| `api/main.py` | FastAPI app; background `_scan_loop()` thread repeats every 10 min independently of browser; in-memory `_events_cache` updated after each full scan |
| `api/event_scanner.py` | 6 detector functions: `find_transitions`, `find_retest_alerts`, `find_balance_map`, `find_kumo_twists`, `find_e2e_opportunities`, `find_cloud_curling` |

### Endpoints
| Endpoint | What |
|---|---|
| `GET /api/health` | `{"ok": true}` liveness probe |
| `GET /api/data` | Returns `{status, scanned_at, coin_count, coins[]}` — `status` is `scanning/ready/error` |
| `POST /api/refresh` | Triggers a new background scan; no-ops if already scanning |
| `GET /api/events` | Returns full `_events_cache` with all 6 event lists + `scanned_at` |
| `GET /api/events/poll?since=<ISO>` | Returns `{changed: false}` if nothing new since `since`; otherwise full event payload |

### Scan loop
Server scans independently of the browser every 10 minutes via a daemon `threading.Thread` started at FastAPI startup. Event scan runs immediately after each full scan completes.

---

## CLI Commands

### `ichi universe [--rebuild] [--top 200]`
**Status: Working**

Builds and caches a universe map (`data/universe_map.json`) of the top-N coins by market cap. Uses CoinGecko free API to rank, then discovers which exchange has each pair via CCXT `load_markets()` across 5-exchange chain: Binance → Bybit → OKX → KuCoin → MEXC. Cache has 24h TTL to avoid repeated API hits.

Stablecoins are excluded via both a blocklist (`_EXCLUDE_BASES`) and a filter requiring `sym.isalpha()`. All future commands route data fetches through this map automatically.

---

### `ichi refresh [--timeframes 1d,4h,1w] [--top 200] [--workers 8]`
**Status: Working**

Fetches/updates OHLCV parquet cache for all universe symbols across one or more timeframes. Runs in parallel. Uses incremental fetch — only downloads bars since the last cached timestamp.

---

### `ichi scan [--timeframe 1d] [--top 200] [--min-score 0] [--regime-filter]`
**Status: Working**

Scores every symbol against the 18 Ichimoku rules. Outputs ranked bull/bear table with ADX regime label, +DI/-DI direction, and inline flags (SQUEEZE, VOL Nx, RSI-DIV↑). Saves state to `data/scan_state.json` for delta tracking. Shows notable score changes vs previous run (threshold: ±3 points).

Return dict now includes: `cloud` (ABOVE/IN/BELOW), `fwd_cloud` (BULL/BEAR), `bearish_div` (boolean) — added for dashboard/API use.

---

### `ichi mtfscan [--timeframes 1w,1d,4h] [--top 200]`
**Status: Working**

Multi-timeframe scan. Scores each symbol on each timeframe independently, then shows a combined table: `1w / 1d / 4h` scores side by side with ADX, cloud position, and future cloud direction. Designed to find alignment across timeframes.

---

### `ichi lagscan [--weekly-min 6] [--daily-max 12] [--top 200]`
**Status: Working**

Coiled-spring scanner. Finds coins that are lagging (strong weekly score but muted daily) — not yet moved, but set up for a move. Scores each on a "coil score" combining:
- Weekly bull strength
- Gap between weekly and daily score (bigger = more compressed)
- Cloud position (in-cloud = maximum compression)
- Future cloud direction (bullish = upcoming support)
- ADX compression (lower = more coiled)
- +DI > -DI (directional bias)
- Bollinger squeeze
- RSI divergence
- Volume ratio

Filters: `weekly_bull ≥ N`, `daily_bull ≤ M`, `+DI > -DI`. Summary shows breakdown of in-cloud, future-cloud-bullish, ultra-low-ADX, squeeze, and divergence counts.

---

### `ichi sectorscan [--timeframe 1d] [--top 200]`
**Status: Working**

Groups all symbols into 11 hardcoded sectors (L1, L2, DeFi, Meme, AI, Gaming, Exchange, Infrastructure, Privacy, LST, Other) and aggregates average bull score, % above 11/18, and average ADX per sector. Shows leading vs lagging sectors and drills into top 3 with individual coin breakdown.

---

### `ichi funding [--top 100] [--min-score 0] [--squeeze-only]`
**Status: Working**

Fetches current perpetual funding rates and open interest for each symbol alongside their bull score. Flags:
- **SQUEEZE SETUP** — negative funding + bull ≥ 11 (shorts paying longs, bullish setup)
- **neg funding** — negative funding + bull ≥ 8
- **overleveraged** — funding > 0.05% + bull < 8 (crowded long, danger)

OI is fetched via Binance's dedicated `/fapi/v1/openInterest` endpoint (`fapiPublicGetOpenInterest`) since `fetch_ticker` doesn't include OI. Falls back to CCXT unified `fetch_open_interest` for non-Binance exchanges.

---

### `ichi alerts [--min-score 14] [--timeframe 1d]`
**Status: Working**

Threshold alerting. Runs a full scan and partitions into: NEW (crossed above threshold since last run), DROPPED (fell below), already above, already below. Appends crossing events to `data/alerts.log` with timestamps. State persisted in `data/alerts_state.json`.

---

### `ichi chart <symbol> [--timeframe 1d]`
**Status: Working**

Renders an Ichimoku chart for a single symbol to a local PNG (`<symbol>_local.png`). Visualises cloud, TK lines, chikou, and recent candles.

---

### `ichi evaluate`
**Status: Working**

Runs walk-forward evaluation of rule predictive power. Uses IC (Information Coefficient) scoring to measure how well each rule predicts future returns. Reads from snapshot parquets in `data/`.

---

### `ichi calibrate`
**Status: Working**

Calibrates rule weights/thresholds using historical data. Outputs `params.yaml` which all commands load at startup.

---

### `ichi journal`
**Status: Working**

Trade journal CLI. Logs trades with entry/exit/P&L and associates them with scan scores at time of entry.

---

## Indicator / Data Modules

### `indicators/ichimoku.py`
Computes all 5 Ichimoku lines: Tenkan-sen (9), Kijun-sen (26), Chikou (26-bar lag), Span A (26-bar lead), Span B (52-bar lead). Columns: `tk, kj, chikou, span_a, span_b, span_a_lead, span_b_lead`. The `_lead` columns are the **unshifted** future cloud — they sit at the current bar index already, so cloud direction at bar `i` is `span_a_lead[i] > span_b_lead[i]`.

### `indicators/precompute.py`
Pre-computes all expensive per-bar series once so rules can read columns instead of recalculating. Columns produced:

| Column | What |
|---|---|
| `_rsi` | RSI(14) |
| `_obv` | On-Balance Volume |
| `_bearish_div` | Bearish RSI divergence (price HH + RSI LL) |
| `_bullish_div` | Bullish RSI divergence (price LL + RSI HL) |
| `_momentum_angle` | atan(5-bar slope) in degrees |
| `_chikou_angle` | atan(10-bar chikou slope) in degrees |
| `_tk_slope5` | 5-bar % slope of Tenkan |
| `_kj_slope5` | 5-bar % slope of Kijun |
| `_kj_slope10` | 10-bar % slope of Kijun |
| `_span_a_lead_slope5` | 5-bar % slope of future Span A |
| `_span_b_slope10` | 10-bar % slope of Span B |
| `_tk_near_count` | Consecutive bars close was within 1.5% of TK line (capped at last 100 bars) |
| `_swing_high` | Swing high pivots (lookback=5) |
| `_swing_low` | Swing low pivots (lookback=20) |
| `_adx` | ADX(14) |
| `_plus_di` | +DI(14) |
| `_minus_di` | -DI(14) |
| `_bb_upper/lower/mid/width/pct` | Bollinger Bands (20, 2σ) |
| `_bb_squeeze` | True when BB width ≤ 125-bar min × 1.05 |
| `_vol_ratio` | Current volume / 20-bar rolling mean |
| `_kj_flat` | True when Kijun 10-bar slope % is near-zero (≤0.05%) |
| `_kj_dist_pct` | % distance from close to Kijun |
| `_cloud_top` | max(span_a, span_b) at current bar |
| `_cloud_bot` | min(span_a, span_b) at current bar |
| `_cloud_top_lead` | max(span_a_lead, span_b_lead) — future cloud ceiling |
| `_cloud_bot_lead` | min(span_a_lead, span_b_lead) — future cloud floor |
| `_near_cloud_top` | True when close is within 1% of cloud top |
| `_near_cloud_bot` | True when close is within 1% of cloud bottom |
| `_near_tk` | True when close is within 1.5% of Tenkan |
| `_near_kj` | True when close is within 1.5% of Kijun |
| `_span_b_flat` | True when Span B 10-bar slope % is near-zero (≤0.03%) |
| `_twist_bars` | Bars until next Span A/B crossover in projected cloud |
| `_chikou_above` | True when chikou is above price 26 bars ago |
| `_bounce_history` | Count of prior successful bounces from this level in last 100 bars |

### `indicators/helpers.py`
Low-level indicator functions: `slope_pct`, `momentum_angle`, `chikou_angle`, `swing_pivots`, `liquidity_sweeps`, `consecutive_near_line` (O(n × 100) after fix), `obv`, `rsi`, `adx`, `divergence`, `bollinger`, `bb_squeeze`.

### `indicators/relative_strength.py`
`relative_strength(coin_df, btc_df)` — computes coin return minus BTC return over 7/14/30-day windows. Returns `rs_score` (count of periods outperforming BTC) and a `rs_label`. Wired into `_score_symbol` and surfaced in dashboard coin dicts as `rs_label` / `rs_score`.

### `data/universe.py`
- CoinGecko `/coins/markets` → ranked list of top-N by market cap
- 5-exchange fallback chain discovers which exchange has each pair
- Universe map cached 24h at `data/universe_map.json`
- `get_exchange_for(symbol)` → exchange_id (used by fetcher for auto-routing)
- `top_n_by_marketcap(n)` → list of pair strings for CLI commands

### `data/fetcher.py`
`fetch_ohlcv(symbol, timeframe)` — looks up exchange from universe map, loads parquet cache, fetches only new bars, saves back. Pagination: advances `since_ms` by 1ms after each batch to avoid re-fetching.

### `data/cache.py`
Parquet read/write. Cache path: `data/ohlcv/{SYMBOL}{EXCHANGE}_{timeframe}.parquet`.

### `data/funding.py`
CCXT perp market wrapper. Converts spot pair `BTC/USDT` → `BTC/USDT:USDT`, sets `defaultType: future`, fetches funding rate and open interest. Works on Binance/Bybit/OKX only. OI value unreliable (see funding command known issue).

### `data/sectors.py`
Hardcoded sector map across 11 sectors covering ~150 top coins. `get_sector(symbol)` → sector name, defaulting to `"Other"`.

### `rules/`
18 scoring rules, each returning bull/bear qualification. Rules are registered in `RuleRegistry.canonical()` and evaluated by `scoring/engine.py` against precomputed columns. Rules cover: price vs cloud, cloud colour/direction, TK cross, TK vs KJ, chikou position, chikou angle, price angle, slope, momentum, swing patterns.

### `scoring/engine.py`
`evaluate(df, i, registry)` → `Scorecard` with `bull_score`, `bear_score`, `grade`, per-rule breakdown.

### `calibration/params.py`
Loads `params.yaml` (or defaults). Applied globally at CLI startup via `apply_params()`. Parameters include ADX thresholds, rule weights, etc.

---

## Bug Fixes Applied

| # | File | Bug | Fix |
|---|---|---|---|
| 1 | `helpers.py` | `slope_pct` divides by zero when past price = 0 | `.replace(0, NaN)` on denominator |
| 2 | `helpers.py` | `adx()` divides by zero when ATR = 0 (flat market) | `safe_atr = atr.replace(0, NaN)` before DI calc |
| 3 | `fetcher.py` | Pagination: `last_ts <= since_ms` could drop exact-boundary candle | Changed to `last_ts < since_ms` |
| 4 | `precompute.py` | `_vol_ratio` divides by zero when rolling mean volume = 0 | `.replace(0, NaN)` on denominator |
| 5 | `scan.py` | `bool(NaN)` returns `True` — squeeze/div flags fire falsely on NaN bars | Added `pd.isna()` guard before `bool()` cast |
| 6 | `precompute.py` / `helpers.py` | `consecutive_near_line` was O(n²): 10-min runtime on lagscan | Added `max_lookback=100` cap + numpy array inner loop |
| 7 | `token-detail.jsx` | Chikou angle showed 12+ decimal places (`+47.32153058°`) | Changed to `.toFixed(1)` |
| 8 | `dashboard-b.jsx` | Retest Alerts `bounce_history` color (green vs white) had no explanation | Added `SymWithTip` component with hover tooltip explaining green = prior bounce confirmed |

---

## Signal Tracking System (`src/ichi/signal/`)

**Status: Implemented — ready for full-universe backfill validation**

Nightly signal logging, tracking, and performance analysis for 8 named Ichimoku signal types (Signals 1–7, 9).

### Architecture

```
signal/detector.py   — 8 detectors + onset-detection gate + SQLite schema (signals.db)
signal/jobs.py       — 3 jobs: run_tracker, run_backfill, run_signal_ic
signal/levels.py     — Chikou S/R level derivation and storage
```

### DB schema (`data/signals.db`)
| Table | Purpose |
|---|---|
| `signal_log` | One row per signal instance; columns include mae, mfe, duration_bars, exit_return, hosoda_active, is_backfill |
| `chikou_levels` | Derived support/resistance levels for Signal 9 |
| `cooccurrence_log` | Signal co-firing pairs within 5-bar window |

### CLI commands
```bash
uv run python -m ichi.signal.jobs backfill [--top=N] [--timeframes=1d,4h,1w]
uv run python -m ichi.signal.jobs track
uv run python -m ichi.signal.jobs signal-ic
uv run python -m ichi.signal.jobs clear-backfill
```

### Key design decisions
- **Onset detection**: signal fires only on the FIRST bar of a new setup episode. In backfill, an in-memory `active` dict per symbol tracks open/closed state with 60-bar timeout + 3-bar cooldown. In live scan, `_db_onset_blocked()` queries the DB.
- **No lookahead**: detectors accept `_bar_i` param so the full df is passed without slicing — no future data visible at bar i.
- **Parallelism**: `run_backfill()` uses `ThreadPoolExecutor(max_workers=8)`. Workers do zero DB writes; main thread batch-inserts per symbol via `_log_signals_batch()`.
- **MAE/MFE**: computed at exit time over `[entry_bar+1, exit_bar]`. Running values updated for still-open signals by tracker. Retroactive fill for CLOSED signals missing them.
- **Universe versioning**: `data/universe/universe_YYYY-MM-DD.json` snapshots for bias-free backfill.

### Grade logic (signal-ic)
- **STRONG**: mean_30d > 5% AND (WR>60% OR WR>45%+WL>1.5 OR WR>33%+WL>3.5)
- **MODERATE**: mean_30d > 2% AND (WR>50% OR WR>40%+WL>1.3 OR WR>28%+WL>2.5)
- **WEAK**: everything else with ≥20 instances
- **INSUFFICIENT DATA**: < 20 instances

### Validation history
| Run | Signals | Notes |
|---|---|---|
| Backfill v1 (181 coins, no onset detection) | 372,073 | Over-inflated; every bar in a bull run fired |
| Backfill v2 (181 coins, onset detection fixed) | 40,082 | ~9× reduction; onset detection working |
| Full 200-coin backfill | Pending | Perf overhaul in place; not yet re-run |

### Next step
```bash
cd /Users/joseph/Documents/tradera/ichi-scorecard

# 1. Clear previous backfill data
uv run python -m ichi.signal.jobs clear-backfill

# 2. Run parallelized backfill (8 workers; should take 15-30 min vs several hours)
uv run python -m ichi.signal.jobs backfill --top=200 --timeframes=1d,4h,1w

# 3. If tracker fails with DB lock, run it separately:
uv run python -m ichi.signal.jobs track

# 4. Review results
uv run python -m ichi.signal.jobs signal-ic
```

---

## Known Issues / Not Yet Done

| Issue | Notes |
|---|---|
| ~~OI shows $0K in `ichi funding` and dashboard~~ | **Fixed** — now uses Binance `/fapi/v1/openInterest` dedicated endpoint. Returns real OI in USD (e.g. BTC ~$8.2B). |
| ~~`liquidity_sweeps` / `divergence` O(n²)~~ | **Fixed** — rewritten to O(n log k) using numpy pivot arrays + binary search two-pointer. |
| ~~Dashboard `rulesFor()` shows 0/18~~ | **Fixed** — RULES array rebuilt with correct `rule_id` strings matching `registry.py`; `rulesFor()` matches by `rule_id` from API `rules[]`. |
| `swing_pivots` is O(n²) | Same pattern as old `consecutive_near_line` — loops over every bar. Not a bottleneck yet since it runs on full history once, but worth noting. |
| First scan is slow (~3–4 min) | Fetches OHLCV for 200 coins × 3 timeframes with parquet caching; subsequent runs are much faster once cache is warm. |
| `detect_signal_9` opens new SQLite connection per bar | During backfill worker threads, each call to detect_signal_9 opens a new read connection to query chikou_levels. This is fine for reads (SQLite allows concurrent readers) but inefficient. No writes in workers so no lock risk. |
| Signal 9 in backfill doesn't see current symbol's new chikou levels | Worker accumulates levels in-memory; they're only saved to DB after worker completes. Signal 9 during backfill only sees levels from prior symbols already committed. Acceptable trade-off for thread safety. |

---

## Data on Disk

```
data/
  universe_map.json        — {pair: exchange_id}, rebuilt daily
  ohlcv/                   — parquet cache per symbol/exchange/timeframe
  scan_state.json          — last scan scores for delta tracking
  alerts_state.json        — last alerts scores
  alerts.log               — append-only threshold crossing log
  score_history.json       — 7-day per-coin score history (for sparklines)
  snapshot_1d.parquet      — historical snapshot for evaluation
  params.yaml              — calibrated rule parameters
```
