"""Autonomous, deterministic Schwab stock/ETF candidate screening.

No user-entered ticker, share amount, or cloud-AI access is required.
This is an experimental model, not an earnings forecast.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from math import log10
from live_order_safety import LiveBlocked, money, quote_levels, cross_signal

# Initial liquid-equity candidate universe, not a fixed trading instruction.
# Each run checks LIVE prices, liquidity and momentum; no symbol is mandatory.
UNIVERSE = (
    "F", "T", "PFE", "AAL", "CCL", "SOFI", "SNAP", "NU",
    "WBD", "NIO", "NOK", "VALE", "UAA", "PLUG", "RIG", "LUMN",
    "KGC", "AG", "CLF", "BTG", "BBD", "HIMS", "GOLD", "ACHR",
)
MAX_SCAN = 8
MIN_VOLUME = 200_000
MIN_PRICE = Decimal("5")
MAX_PRICE = Decimal("25")
MAX_SPREAD_PCT = Decimal("0.02")


@dataclass(frozen=True)
class Candidate:
    symbol: str
    bid: Decimal
    ask: Decimal
    score: Decimal
    candle: int
    reason: str


def quote_rank(symbol: str, data: dict, now: datetime):
    """Return a quote ranking only for an affordable, liquid security."""
    if not isinstance(data, dict):
        raise LiveBlocked("Invalid candidate quote")
    bid, ask = quote_levels(data, now)
    if ask < MIN_PRICE or ask > MAX_PRICE:
        raise LiveBlocked("Candidate outside the budgeted share-price band")
    quote = data.get("quote") or {}
    volume = money(quote.get("totalVolume", data.get("totalVolume")), "volume")
    if volume < MIN_VOLUME:
        raise LiveBlocked("Insufficient candidate liquidity")
    instrument_type = data.get("assetMainType")
    if instrument_type is not None and instrument_type != "EQUITY":
        raise LiveBlocked("Candidate is not a common stock or ETF")
    spread = (ask - bid) / ask
    if spread > MAX_SPREAD_PCT:
        raise LiveBlocked("Candidate bid-ask spread too wide")
    net = money(quote.get("netPercentChange", 0), "daily % change")
    # Real liquidity outweighs day-momentum; very extreme moves are avoided.
    if abs(net) > 12:
        raise LiveBlocked("Excessively volatile candidate")
    score = (Decimal(str(log10(float(volume)))) - spread * 80
             + max(Decimal("-3"), min(Decimal("3"), net)) / 4)
    return score, bid, ask


def ranked_candidates(quote_map: dict, now: datetime, universe=UNIVERSE):
    """Rank live quotes, never assume that configured symbols are tradable."""
    if not isinstance(quote_map, dict):
        raise LiveBlocked("Schwab quote batch is not an object")
    results = []
    for sym in universe:
        try:
            row = quote_map[sym]
            score, bid, ask = quote_rank(sym, row, now)
            results.append((score, sym, bid, ask))
        except (KeyError, LiveBlocked, TypeError, ValueError):
            continue
    results.sort(key=lambda x: (-x[0], x[1]))
    return results[:MAX_SCAN]


def choose_entry(ranked, candle_lookup, now: datetime, can_buy):
    """Find highest-ranked valid BUY crossover, choose shares from cash later.

    candle_lookup(symbol) returns actual Schwab five-minute candle rows. All
    candidates are checked against complete bar timestamps and prices.
    """
    if not can_buy:
        return None
    for score, sym, bid, ask in ranked:
        try:
            signal, candle = cross_signal(candle_lookup(sym), now)
        except (LiveBlocked, KeyError, TypeError, ValueError):
            continue
        if signal == "BUY":
            reason = (f"automatic live liquidity rank={score:.3f}; "
                      "confirmed 3/5-bar upward crossover; "
                      f"bid={bid}, ask={ask}")
            return Candidate(sym, bid, ask, score, candle, reason)
    return None
