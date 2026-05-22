"""Universe discovery: top N coins by market cap via CoinGecko + exchange fallback.

Exchange priority chain: Binance → Bybit → OKX → KuCoin → MEXC.
Universe map is cached to data/universe_map.json for 24 hours.
"""
from __future__ import annotations

import json
import logging
import time
import urllib.request
from datetime import datetime
from pathlib import Path

import ccxt

logger = logging.getLogger(__name__)

_EXCHANGE_CHAIN: list[str] = ["binance", "bybit", "okx", "kucoin", "mexc"]

_UNIVERSE_MAP_FILE = Path(__file__).resolve().parents[3] / "data" / "universe_map.json"
_UNIVERSE_MAP_TTL = 24 * 3600  # seconds

# Stablecoins, pegged assets, and wrapped tokens — no directional Ichimoku signal
_EXCLUDE_BASES: set[str] = {
    # Stablecoins
    "USDT", "USDC", "FDUSD", "TUSD", "BUSD", "DAI", "USDD", "USDP", "GUSD",
    "USD1", "PYUSD", "FRAX", "LUSD", "CRVUSD", "GHO", "USDX", "USDE", "USDB",
    "USDS", "USDG", "USDY", "USDM", "USDTB", "EURS", "EURT", "EUROC",
    # Gold / commodity pegs
    "PAXG", "XAUT",
    # Wrapped / liquid staking tokens
    "WBTC", "WETH", "STETH", "WSTETH", "BBTC", "CBBTC", "WEETH", "EZETH", "RETH",
    "HBTC", "TBTC", "BTCB",
}

# Minimum symbol length — filters noise like "M", "CC"
_MIN_SYMBOL_LEN = 2

# Hardcoded fallback if both CoinGecko and exchange discovery fail
_FALLBACK_PAIRS: list[tuple[str, str]] = [
    ("BTC/USDT", "binance"), ("ETH/USDT", "binance"), ("SOL/USDT", "binance"),
    ("BNB/USDT", "binance"), ("XRP/USDT", "binance"), ("DOGE/USDT", "binance"),
    ("ADA/USDT", "binance"), ("AVAX/USDT", "binance"), ("LINK/USDT", "binance"),
    ("DOT/USDT", "binance"),
]


# ── CoinGecko ─────────────────────────────────────────────────────────────────

def _coingecko_top_symbols(n: int = 250) -> list[str]:
    """Return top-N base symbols (uppercase) by market cap from CoinGecko free API."""
    pages = (n // 250) + (1 if n % 250 else 0)
    symbols: list[str] = []
    for page in range(1, pages + 1):
        url = (
            "https://api.coingecko.com/api/v3/coins/markets"
            f"?vs_currency=usd&order=market_cap_desc&per_page=250&page={page}"
            "&sparkline=false&price_change_percentage=24h"
        )
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "ichi-scorecard/1.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())
            for coin in data:
                sym = coin.get("symbol", "").upper()
                if (sym
                        and len(sym) >= _MIN_SYMBOL_LEN
                        and sym not in _EXCLUDE_BASES
                        and sym.isascii()
                        and sym.isalpha()):  # no numerics or special chars in base
                    symbols.append(sym)
        except Exception as exc:
            logger.warning("CoinGecko page %d failed: %s", page, exc)
            break
        if page < pages:
            time.sleep(1.5)  # free tier rate limit: ~10 req/min
    return symbols[:n]


# ── Exchange discovery ─────────────────────────────────────────────────────────

def _build_exchange_map(symbols: list[str]) -> dict[str, str]:
    """For each symbol, discover which exchange in the chain has a USDT spot pair."""
    # Load markets for each exchange once, in parallel would be nice but keep it simple
    exchange_markets: dict[str, set[str]] = {}
    for ex_id in _EXCHANGE_CHAIN:
        try:
            ex = getattr(ccxt, ex_id)({"enableRateLimit": True})
            markets = ex.load_markets()
            exchange_markets[ex_id] = set(markets.keys())
            logger.debug("%s: %d markets loaded", ex_id, len(exchange_markets[ex_id]))
        except Exception as exc:
            logger.warning("Could not load markets for %s: %s", ex_id, exc)
            exchange_markets[ex_id] = set()

    result: dict[str, str] = {}
    for base in symbols:
        pair = f"{base}/USDT"
        for ex_id in _EXCHANGE_CHAIN:
            if pair in exchange_markets.get(ex_id, set()):
                result[pair] = ex_id
                break
        # If no exchange found, skip (coin not tradeable via USDT on any supported exchange)

    return result


# ── Cache I/O ─────────────────────────────────────────────────────────────────

def _load_cached_map() -> dict | None:
    """Return cached universe map if it exists and is within TTL."""
    if not _UNIVERSE_MAP_FILE.exists():
        return None
    try:
        with open(_UNIVERSE_MAP_FILE) as f:
            state = json.load(f)
        age = time.time() - state.get("timestamp", 0)
        if age > _UNIVERSE_MAP_TTL:
            return None
        return state
    except Exception:
        return None


_UNIVERSE_SNAPSHOTS_DIR = _UNIVERSE_MAP_FILE.parent / "universe"


def _save_map(pair_to_exchange: dict[str, str]) -> None:
    _UNIVERSE_MAP_FILE.parent.mkdir(parents=True, exist_ok=True)
    state = {"timestamp": time.time(), "pairs": pair_to_exchange}
    with open(_UNIVERSE_MAP_FILE, "w") as f:
        json.dump(state, f, indent=2)
    # Also write a dated snapshot for universe versioning / backfill bias-avoidance
    today = datetime.utcnow().strftime("%Y-%m-%d")
    _UNIVERSE_SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    snapshot_path = _UNIVERSE_SNAPSHOTS_DIR / f"universe_{today}.json"
    with open(snapshot_path, "w") as f:
        json.dump(state, f, indent=2)


def get_universe_at_date(date: str) -> dict[str, str]:
    """Return {pair: exchange_id} map as of the given date (YYYY-MM-DD).

    Searches data/universe/ for the closest snapshot on or before the given date.
    Falls back to universe_map.json if no dated snapshot is available.
    """
    target = date
    snapshots: list[str] = []
    if _UNIVERSE_SNAPSHOTS_DIR.exists():
        for p in sorted(_UNIVERSE_SNAPSHOTS_DIR.glob("universe_*.json")):
            snap_date = p.stem.replace("universe_", "")
            if snap_date <= target:
                snapshots.append(snap_date)

    if snapshots:
        best = snapshots[-1]  # latest on-or-before target
        snap_path = _UNIVERSE_SNAPSHOTS_DIR / f"universe_{best}.json"
        try:
            with open(snap_path) as f:
                state = json.load(f)
            return state.get("pairs", {})
        except Exception:
            pass

    # Fallback: current universe_map.json
    cached = _load_cached_map()
    if cached:
        return cached["pairs"]
    return {}


# ── Public API ────────────────────────────────────────────────────────────────

def build_universe(n: int = 200, force: bool = False) -> dict[str, str]:
    """Return {pair: exchange_id} map for top-N coins by market cap.

    Uses cached result if < 24h old. Pass force=True to rebuild.
    """
    if not force:
        cached = _load_cached_map()
        if cached:
            return cached["pairs"]

    click_echo = _maybe_click_echo()
    click_echo(f"Building universe map (top {n} by market cap)…")

    symbols = _coingecko_top_symbols(n + 50)  # fetch extra to account for exclusions
    if not symbols:
        logger.warning("CoinGecko returned no symbols — using Binance volume fallback")
        return _binance_volume_fallback(n)

    click_echo(f"  CoinGecko: {len(symbols)} candidates after filtering")
    click_echo(f"  Discovering exchange availability across {_EXCHANGE_CHAIN}…")

    pair_map = _build_exchange_map(symbols[:n + 20])

    # Trim to requested N
    # Preserve market-cap order (symbols list is already ordered)
    ordered: dict[str, str] = {}
    for sym in symbols:
        pair = f"{sym}/USDT"
        if pair in pair_map and len(ordered) < n:
            ordered[pair] = pair_map[pair]

    if not ordered:
        return _binance_volume_fallback(n)

    _save_map(ordered)
    click_echo(f"  Universe: {len(ordered)} pairs found, saved to {_UNIVERSE_MAP_FILE.name}")
    return ordered


def top_n_by_marketcap(n: int = 200) -> list[str]:
    """Return list of USDT pair strings (e.g. 'BTC/USDT') for top-N by market cap."""
    pair_map = build_universe(n)
    return list(pair_map.keys())[:n]


def get_exchange_for(symbol: str) -> str:
    """Return exchange_id for a given pair (e.g. 'BTC/USDT'). Defaults to 'binance'."""
    cached = _load_cached_map()
    if cached:
        return cached["pairs"].get(symbol, "binance")
    return "binance"


# Keep backward-compat alias used by older CLI commands
def top_n_usdt_pairs(n: int = 30, exchange_id: str = "binance") -> list[str]:
    """Backward-compat wrapper — prefers market-cap universe, falls back to volume."""
    try:
        return top_n_by_marketcap(n)
    except Exception:
        return _binance_volume_fallback(n)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _binance_volume_fallback(n: int) -> dict[str, str] | list[str]:
    """Use Binance 24h volume as fallback when CoinGecko+exchange discovery fails."""
    try:
        ex = ccxt.binance({"enableRateLimit": True})
        tickers = ex.fetch_tickers()
        pairs = [
            sym for sym, t in tickers.items()
            if sym.endswith("/USDT")
            and t.get("quoteVolume")
            and sym.split("/")[0] not in _EXCLUDE_BASES
            and sym.replace("/USDT", "").isascii()
        ]
        pairs.sort(key=lambda s: float(tickers[s].get("quoteVolume") or 0), reverse=True)
        return {p: "binance" for p in pairs[:n]}
    except Exception:
        return {p: ex_id for p, ex_id in _FALLBACK_PAIRS[:n]}


def _maybe_click_echo():
    """Return click.echo if available, else a no-op (for import-time safety)."""
    try:
        import click
        return click.echo
    except ImportError:
        return lambda *a, **kw: None
