"""Fetch funding rates and open interest from perpetual futures markets.

Only available for coins with active perp markets (typically top ~120 by market cap).
Uses CCXT unified API — works across Binance, Bybit, OKX.

Perp symbol format: BTC/USDT:USDT  (CCXT linear perp unified format)
"""
from __future__ import annotations

import logging

import ccxt

logger = logging.getLogger(__name__)

# Exchanges that support linear perps with CCXT
_PERP_EXCHANGES = ["binance", "bybit", "okx"]


def _spot_to_perp(symbol: str) -> str:
    """Convert spot symbol to linear perp: 'BTC/USDT' → 'BTC/USDT:USDT'."""
    if ":" in symbol:
        return symbol
    base, quote = symbol.split("/")
    return f"{base}/{quote}:{quote}"


def _make_perp_exchange(exchange_id: str) -> ccxt.Exchange:
    exchange_class = getattr(ccxt, exchange_id)
    ex = exchange_class({"enableRateLimit": True})
    ex.options["defaultType"] = "future"
    return ex


def fetch_funding_rate(symbol: str, exchange_id: str = "binance") -> dict | None:
    """Return current funding rate info for a symbol.

    Returns dict with:
        funding_rate   — current rate (e.g. 0.0001 = 0.01%)
        funding_pct    — rate as percentage
        next_funding   — ISO timestamp of next funding event
        exchange       — which exchange
    Returns None if perp not available.
    """
    if exchange_id not in _PERP_EXCHANGES:
        exchange_id = "binance"
    perp_sym = _spot_to_perp(symbol)
    try:
        ex = _make_perp_exchange(exchange_id)
        data = ex.fetch_funding_rate(perp_sym)
        rate = float(data.get("fundingRate") or 0)
        return {
            "symbol": symbol,
            "funding_rate": rate,
            "funding_pct": round(rate * 100, 4),
            "next_funding": data.get("nextFundingDatetime"),
            "exchange": exchange_id,
        }
    except Exception as exc:
        logger.debug("%s funding rate unavailable on %s: %s", symbol, exchange_id, exc)
        return None


def fetch_open_interest(symbol: str, exchange_id: str = "binance") -> dict | None:
    """Return current open interest for a symbol's perp market.

    Returns dict with:
        oi_contracts   — OI in base currency contracts
        oi_usd         — OI in USD (contracts × mark price)
        exchange       — which exchange
    Returns None if perp not available.

    Note: most exchanges don't return openInterestValue via CCXT, so oi_usd
    is computed from contracts × last mark price fetched via fetch_ticker.
    """
    if exchange_id not in _PERP_EXCHANGES:
        exchange_id = "binance"
    perp_sym = _spot_to_perp(symbol)
    try:
        ex = _make_perp_exchange(exchange_id)
        data = ex.fetch_open_interest(perp_sym)
        contracts = float(data.get("openInterest") or 0)
        oi_usd = float(data.get("openInterestValue") or 0)

        # Most exchanges (Binance included) don't populate openInterestValue via CCXT.
        # Compute from contracts × current mark price instead.
        if oi_usd == 0 and contracts > 0:
            try:
                ticker = ex.fetch_ticker(perp_sym)
                price = float(ticker.get("last") or ticker.get("close") or 0)
                if price > 0:
                    oi_usd = contracts * price
            except Exception:
                pass

        return {
            "symbol": symbol,
            "oi_contracts": contracts,
            "oi_usd": oi_usd if oi_usd > 0 else None,
            "exchange": exchange_id,
        }
    except Exception as exc:
        logger.debug("%s OI unavailable on %s: %s", symbol, exchange_id, exc)
        return None


def fetch_funding_and_oi(symbol: str, exchange_id: str = "binance") -> dict:
    """Fetch funding rate + OI using a single exchange connection.

    Uses fetch_ticker on the perp market which returns both mark price and raw OI
    in one round-trip. Falls back to fetch_open_interest if ticker OI is missing.
    """
    if exchange_id not in _PERP_EXCHANGES:
        exchange_id = "binance"
    perp_sym = _spot_to_perp(symbol)
    result: dict = {
        "symbol": symbol, "exchange": exchange_id,
        "funding_rate": None, "funding_pct": None, "next_funding": None,
        "oi_contracts": None, "oi_usd": None,
    }
    try:
        ex = _make_perp_exchange(exchange_id)

        # Funding rate
        try:
            fr = ex.fetch_funding_rate(perp_sym)
            rate = float(fr.get("fundingRate") or 0)
            result["funding_rate"] = rate
            result["funding_pct"] = round(rate * 100, 4)
            result["next_funding"] = fr.get("nextFundingDatetime")
        except Exception as exc:
            logger.debug("%s funding unavailable: %s", symbol, exc)

        # Price via ticker, OI via dedicated endpoint
        price = 0.0
        try:
            ticker = ex.fetch_ticker(perp_sym)
            price = float(ticker.get("last") or ticker.get("close") or 0)
        except Exception as exc:
            logger.debug("%s ticker unavailable: %s", symbol, exc)

        # Binance: use dedicated /fapi/v1/openInterest endpoint
        contracts = 0.0
        try:
            base = perp_sym.split("/")[0]  # "BTC" from "BTC/USDT:USDT"
            quote = perp_sym.split("/")[1].split(":")[0]  # "USDT"
            binance_sym = base + quote  # "BTCUSDT"
            oi_resp = ex.fapiPublicGetOpenInterest({"symbol": binance_sym})
            contracts = float(oi_resp.get("openInterest") or 0)
        except Exception:
            # Fallback: CCXT unified fetch_open_interest
            try:
                oi_data = ex.fetch_open_interest(perp_sym)
                contracts = float(oi_data.get("openInterest") or 0)
            except Exception as exc:
                logger.debug("%s OI unavailable: %s", symbol, exc)

        if contracts > 0 and price > 0:
            result["oi_contracts"] = contracts
            result["oi_usd"] = contracts * price

    except Exception as exc:
        logger.debug("%s funding+OI failed on %s: %s", symbol, exchange_id, exc)

    return result
