"""Webull-owned stock signal engine mirroring Schwab's current M5 entry rules.

Independent implementation: NO imports from Schwab strategy/worker/risk modules.
Changes to Schwab do not change Webull. The parity test suite compares them.

Only signal screening: no AI, account selection, journal, or order submission.
Webull's broker API supplies all quotes, snapshots, and five-minute bars.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from math import log10
import re

from webull_broker import positive, WebullError
from webull_signals import _quote, _time, core_stock_session, WebullSignalError

# Intentional *copies* of Schwab's current candidate universe and screening
# thresholds. These constants are Webull-owned, and can diverge independently.
STOCK_SCAN_SYMBOLS = (
    "F", "T", "PFE", "AAL", "CCL", "SOFI", "SNAP", "NU",
    "WBD", "NIO", "NOK", "VALE", "UAA", "PLUG", "RIG", "LUMN",
    "KGC", "AG", "CLF", "BTG", "BBD", "HIMS", "GOLD", "ACHR",
)
MAX_RANKED = 8
MIN_VOLUME = Decimal("200000")
MIN_PRICE = Decimal("3")
MAX_PRICE = Decimal("30")
MAX_SPREAD_PCT = Decimal("0.01")
STOCK_SOURCE = "WEBULL_MIRROR_SCHWAB_M5"


@dataclass(frozen=True)
class _Candidate:
    symbol: str
    bid: Decimal
    ask: Decimal
    score: Decimal
    candle: int
    reason: str


def _number(value, label):
    if value is None or isinstance(value, bool):
        raise WebullSignalError("Missing or invalid " + label)
    try:
        amount = Decimal(str(value))
    except (ValueError, TypeError, ArithmeticError):
        raise WebullSignalError("Invalid " + label) from None
    if not amount.is_finite():
        raise WebullSignalError("Non-finite " + label)
    return amount


def _rank_quote(symbol, data, now):
    """Independent mirror of Schwab's quote_rank and quote_levels constraints."""
    if not isinstance(data, dict):
        raise WebullSignalError("Invalid candidate quote")
    quote = data.get("quote")
    if not isinstance(quote, dict):
        raise WebullSignalError("Missing candidate quote")
    bid = _number(quote.get("bidPrice"), "bid")
    ask = _number(quote.get("askPrice"), "ask")
    age = Decimal(str(now.timestamp())) - _number(quote.get("quoteTime"), "quote time") / 1000
    if (bid < 5 or ask < 5 or bid > ask or
            (ask - bid) / ask > Decimal("0.02")):
        raise WebullSignalError("Invalid or excessive bid/ask spread")
    if age < -5 or age > 60:
        raise WebullSignalError("Quote stale or invalid")
    if ask < MIN_PRICE or ask > MAX_PRICE:
        raise WebullSignalError("Candidate outside price band")
    volume = _number(quote.get("totalVolume", data.get("totalVolume")), "volume")
    if volume < MIN_VOLUME:
        raise WebullSignalError("Insufficient candidate liquidity")
    asset_type = data.get("assetMainType")
    if asset_type is not None and asset_type != "EQUITY":
        raise WebullSignalError("Not stock or ETF")
    spread = (ask - bid) / ask
    if spread > MAX_SPREAD_PCT:
        raise WebullSignalError("Candidate spread too wide")
    change = _number(quote.get("netPercentChange", 0), "daily % change")
    if abs(change) > 12:
        raise WebullSignalError("Excessively volatile candidate")
    score = (Decimal(str(log10(float(volume)))) - spread * 80
             + max(Decimal("-3"), min(Decimal("3"), change)) / 4)
    return score, bid, ask


def _ranked_candidates(quote_map, now, universe):
    """Copy of the Schwab candidate ranking, kept locally for Webull."""
    result = []
    for sym in universe:
        try:
            score, bid, ask = _rank_quote(sym, quote_map[sym], now)
            result.append((score, sym, bid, ask))
        except (KeyError, WebullSignalError, TypeError, ValueError):
            continue
    result.sort(key=lambda row: (-row[0], row[1]))
    return result[:MAX_RANKED]


def _cross_signal(candles, now):
    """Independent version of Schwab's 3/5 completed M5-bar crossover."""
    if len(candles) < 6:
        raise WebullSignalError("Insufficient candle history")
    rows = sorted(candles, key=lambda row: row["datetime"])
    clean = []
    cutoff_ms = int(now.timestamp() * 1000) - 60000
    for row in rows:
        t = int(row["datetime"])
        close = _number(row.get("close"), "close")
        if 0 < t + 300000 <= cutoff_ms and close > 0:
            clean.append((t, close))
    if len(clean) < 6 or clean[-1][0] + 300000 < int(now.timestamp() * 1000) - 12 * 60000:
        raise WebullSignalError("Market candles missing or stale")
    if len(set(t for t, _ in clean)) != len(clean):
        raise WebullSignalError("Duplicate candle timestamps")
    p = [value for _, value in clean[-6:]]
    short_prev = sum(p[-4:-1]) / 3
    long_prev = sum(p[-6:-1]) / 5
    short_now = sum(p[-3:]) / 3
    long_now = sum(p[-5:]) / 5
    if short_prev <= long_prev and short_now > long_now:
        return "BUY", clean[-1][0]
    if short_prev >= long_prev and short_now < long_now:
        return "SELL", clean[-1][0]
    return "HOLD", clean[-1][0]


def _choose_entry(ranked, candle_lookup, now, can_buy=True):
    """Mirrors Schwab's crossover-or-continuation selector, independent code."""
    if not can_buy:
        return None
    for score, sym, bid, ask in ranked:
        try:
            signal, candle = _cross_signal(candle_lookup(sym), now)
        except (WebullSignalError, KeyError, TypeError, ValueError):
            continue
        reason = None
        if signal == "BUY":
            reason = "confirmed 3/5-bar upward crossover"
        elif signal == "HOLD":
            try:
                rows = sorted(candle_lookup(sym), key=lambda x: x["datetime"])
                cutoff = int(now.timestamp() * 1000) - 60000
                completed = [(int(b["datetime"]), _number(b["close"], "close"))
                             for b in rows if int(b["datetime"]) + 300000 <= cutoff]
                tail = completed[-4:]
                if (len(tail) == 4 and tail[-1][0] == candle and
                        len({t for t, _ in tail}) == 4 and
                        all(tail[i][1] > tail[i-1][1] for i in range(1, 4))
                        and tail[0][1] > 0):
                    momentum = (tail[-1][1] / tail[0][1] - 1) * 100
                    if Decimal("0.4") <= momentum <= Decimal("2"):
                        reason = f"continuing momentum {momentum:.2f}% over three completed bars"
            except (WebullSignalError, KeyError, ValueError, TypeError, ArithmeticError):
                pass
        if reason:
            return _Candidate(sym, bid, ask, score, candle,
                f"Webull mirrored stock strategy rank={score:.3f}; {reason}; bid={bid}, ask={ask}")
    return None


def _safe_data_reason(exc):
    # Never leak signed Webull request headers through error diagnostics.
    if isinstance(exc, (WebullError, WebullSignalError)) or type(exc).__name__ == "ServerException":
        code = re.search(r"HTTP (?:Status: )?([45]\d\d)", str(exc))
        if code:
            return "MARKET_DATA_WEBULL_HTTP_" + code.group(1)
        if isinstance(exc, WebullSignalError):
            msg = re.sub(r"[^A-Z0-9]+", "_", str(exc).upper()).strip("_")[:78]
            return "MARKET_DATA_SIGNAL_" + msg
    return "MARKET_DATA_" + type(exc).__name__.upper()[:64]


def _convert_quote(symbol, depth, snapshot, now):
    if not isinstance(snapshot, dict) or snapshot.get("symbol") != symbol:
        raise WebullSignalError("Webull stock snapshot symbol mismatch")
    bid, ask, spread = _quote(depth, now)
    volume = positive(snapshot.get("volume"))
    ratio = _number(snapshot.get("change_ratio"), "change ratio")
    if abs(ratio) > Decimal("1"):
        raise WebullSignalError("Webull daily change invalid")
    raw_time = depth.get("quote_time") or depth.get("time") or depth.get("timestamp")
    when = _time(raw_time)
    row = {"assetMainType": "EQUITY", "quote": {
        "bidPrice": str(bid), "askPrice": str(ask),
        "quoteTime": int(when.timestamp() * 1000),
        "totalVolume": str(volume), "netPercentChange": str(ratio * 100)}}
    return row, float(spread)


def _convert_bars(rows):
    if not isinstance(rows, list):
        raise WebullSignalError("Webull five-minute bar history missing")
    result = []
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        if row.get("trading_sessions") not in (None, "RTH"):
            continue
        try:
            stamp = _time(row["time"])
            close = positive(row["close"])
        except (KeyError, ValueError, TypeError, WebullError, OverflowError):
            continue
        epoch = int(stamp.timestamp() * 1000)
        if epoch in seen:
            raise WebullSignalError("Duplicate Webull five-minute bar")
        seen.add(epoch)
        result.append({"datetime": epoch, "close": str(close)})
    result.sort(key=lambda x: x["datetime"])
    return result[-150:]


def scan_webull_stock(broker, symbols, now=None):
    """Use Webull quotes and local M5 logic; never use Schwab runtime objects."""
    now = now or datetime.now(timezone.utc)
    if not core_stock_session(now):
        return ([{"symbol": sym, "asset": "EQUITY", "source": STOCK_SOURCE,
                  "technical_approved": False,
                  "reason": "Outside conservative US core stock session"}
                 for sym in symbols], None)
    quoted, spreads, reasons = {}, {}, {}
    for symbol in symbols:
        try:
            depth = broker.quote(symbol, "EQUITY")
            snapshot = broker.stock_snapshot(symbol)
            quoted[symbol], spreads[symbol] = _convert_quote(symbol, depth, snapshot, now)
        except Exception as exc:
            reasons[symbol] = _safe_data_reason(exc)
    ranked = _ranked_candidates(quoted, now, symbols)
    eligible = {sym for _, sym, _, _ in ranked}
    for sym in symbols:
        if sym in quoted and sym not in eligible:
            reasons[sym] = "WEBULL_MIRROR_PRICE_VOLUME_OR_SPREAD_GATE"
    candles = {}
    for _, sym, _, _ in ranked:
        try:
            candles[sym] = _convert_bars(broker.bars(sym, "EQUITY", period="M5"))
        except Exception as exc:
            reasons[sym] = _safe_data_reason(exc)

    def lookup(sym):
        if sym not in candles:
            raise WebullSignalError("Webull M5 bars unavailable")
        return candles[sym]

    selected = _choose_entry(ranked, lookup, now)
    diagnostics = []
    signal = None
    for sym in symbols:
        chosen = selected is not None and sym == selected.symbol
        if chosen:
            bid, ask = selected.bid, selected.ask
            signal = {"symbol": sym, "asset": "EQUITY", "source": STOCK_SOURCE,
                      "at": now.isoformat(), "technical_approved": True,
                      "technical_exit": False, "ai_approved": False,
                      "bid": str(bid), "ask": str(ask), "mid": str((bid + ask) / 2),
                      "spread_pct": round(spreads[sym], 4),
                      "momentum_pct": 0.0, "bars": len(candles[sym]),
                      "reason": selected.reason, "shared_candle": selected.candle}
        diagnostics.append({"symbol": sym, "asset": "EQUITY", "source": STOCK_SOURCE,
                            "technical_approved": chosen,
                            "spread_pct": round(spreads[sym], 4) if sym in spreads else None,
                            "reason": selected.reason if chosen else reasons.get(
                                sym, "WEBULL_MIRROR_NO_M5_ENTRY")})
    return diagnostics, signal


def revalidate_webull_stock(broker, symbol, now=None):
    _, signal = scan_webull_stock(broker, (symbol,), now)
    if signal is None:
        raise WebullSignalError("Webull mirrored M5 crossover no longer qualifies")
    return signal
