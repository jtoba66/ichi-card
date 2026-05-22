"""Sector / category mapping for top crypto assets.

Used by sectorscan to group coins and show rotation between categories.
Hardcoded for reliability — no extra API calls needed.
"""
from __future__ import annotations

# fmt: off
_SECTOR_MAP: dict[str, str] = {
    # Layer 1
    "BTC": "L1", "ETH": "L1", "SOL": "L1", "ADA": "L1", "AVAX": "L1",
    "DOT": "L1", "ATOM": "L1", "NEAR": "L1", "ICP": "L1", "APT": "L1",
    "SUI": "L1", "SEI": "L1", "TON": "L1", "TRX": "L1", "HBAR": "L1",
    "XRP": "L1", "XLM": "L1", "ALGO": "L1", "VET": "L1", "XTZ": "L1",
    "EGLD": "L1", "IOTA": "L1", "XEC": "L1", "KAS": "L1", "TAO": "L1",
    "NEO": "L1", "ETC": "L1", "BCH": "L1", "LTC": "L1",
    # Layer 2 / Scaling
    "ARB": "L2", "OP": "L2", "POL": "L2", "STX": "L2", "IMX": "L2",
    "MNT": "L2", "STRK": "L2", "ZK": "L2", "INJ": "L2",
    # DeFi
    "UNI": "DeFi", "AAVE": "DeFi", "CRV": "DeFi", "CAKE": "DeFi",
    "COMP": "DeFi", "LDO": "DeFi", "RUNE": "DeFi", "GRT": "DeFi",
    "DYDX": "DeFi", "JUP": "DeFi", "RAY": "DeFi", "PENDLE": "DeFi",
    "CVX": "DeFi", "GLM": "DeFi", "SYRUP": "DeFi", "MORPHO": "DeFi",
    "FLUID": "DeFi", "EIGEN": "DeFi", "ENA": "DeFi", "ETHFI": "DeFi",
    "ZRO": "DeFi", "ONDO": "DeFi", "AKT": "DeFi",
    # Meme
    "DOGE": "Meme", "SHIB": "Meme", "PEPE": "Meme", "FLOKI": "Meme",
    "BONK": "Meme", "WIF": "Meme", "FARTCOIN": "Meme", "TRUMP": "Meme",
    "CHEEMS": "Meme", "LUNC": "Meme", "JASMY": "Meme", "FLR": "Meme",
    # AI / Data
    "FET": "AI", "RENDER": "AI", "GRASS": "AI", "VIRTUAL": "AI",
    "GRT": "AI", "PRIME": "AI",
    # Gaming / Metaverse
    "AXS": "Gaming", "SAND": "Gaming", "MANA": "Gaming", "GALA": "Gaming",
    "CHZ": "Gaming", "APE": "Gaming",
    # Exchange tokens
    "BNB": "Exchange", "OKB": "Exchange", "KCS": "Exchange",
    "MX": "Exchange", "HTX": "Exchange", "WBT": "Exchange",
    "BGB": "Exchange", "CRO": "Exchange", "GT": "Exchange",
    # Infrastructure / Oracles
    "LINK": "Infrastructure", "QNT": "Infrastructure", "DOT": "Infrastructure",
    "ATOM": "Infrastructure", "FIL": "Infrastructure", "AR": "Infrastructure",
    "DCR": "Infrastructure", "GNO": "Infrastructure", "CFX": "Infrastructure",
    "TRAC": "Infrastructure",
    # Privacy
    "XMR": "Privacy", "ZEC": "Privacy", "DASH": "Privacy",
    # Liquid Staking / Restaking
    "LDO": "LST", "ETHFI": "LST", "EIGEN": "LST",
    # Other / Misc
    "TWT": "Other", "SFP": "Other", "CHZ": "Other", "JST": "Other",
    "SUN": "Other", "BTT": "Other", "WIN": "Other", "XCN": "Other",
    "DEXE": "Other", "BDX": "Other", "KAIA": "Other", "TIA": "Other",
    "PYTH": "Other", "JTO": "Other", "WLD": "Other", "THETA": "Other",
    "VVV": "Other", "HYPE": "Other", "BAT": "Other", "NEO": "Other",
}
# fmt: on

_DEFAULT_SECTOR = "Other"


def get_sector(symbol: str) -> str:
    """Return sector for a base symbol (e.g. 'BTC'). Defaults to 'Other'."""
    base = symbol.replace("/USDT", "")
    return _SECTOR_MAP.get(base, _DEFAULT_SECTOR)


def all_sectors() -> list[str]:
    """Return sorted list of all known sector names."""
    return sorted(set(_SECTOR_MAP.values()))
