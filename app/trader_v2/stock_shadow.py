"""Read-only Schwab V1 five-minute candle handoff and V2 stock shadow scans.

No broker clients, order adapters, simulated fills, V1 risk mutations, or
authentication calls. We only consume V1's EXISTING genuine completed candle
responses and last broker quote cache, retaining original timestamps.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
import argparse
import fcntl
import json
import os
import signal
import sqlite3
import stat
import time

from autonomous_selector import UNIVERSE
from .models import Candle, AssetClass, utc, amount
from .strategies import StockController
from .market_sources import schwab_market_quote, MarketSourceError
from .readonly_adapters import private_json
from .recorded_replay import _atomic_json
from .ai_shadow import shadow_review

VERSION = "schwab-stock-shadow-1"
SYMBOLS = tuple(UNIVERSE)
SOURCE = "SCHWAB_V1_5M_REGULAR_HISTORY"
CONTROLLER = StockController()
POLL_SECONDS = 30
MAX_REVIEW_PER_CYCLE = 4
_STOP = False


class StockShadowError(ValueError):
    pass


def _private_dir(path):
    path = Path(path)
    if path.is_symlink():
        raise StockShadowError("SHADOW_DIRECTORY_UNSAFE")
    path.mkdir(parents=True, mode=0o700, exist_ok=True)
    st = path.stat()
    if not stat.S_ISDIR(st.st_mode) or st.st_mode & 0o077:
        raise StockShadowError("SHADOW_DIRECTORY_UNSAFE")
    return path


def _root(state_dir):
    return Path(state_dir) / "v2" / "stock_shadow"


def capture_schwab_candles(state_dir, symbol, bars, *, now=None):
    """Capture the exact V1 5m history without fabricating 1m or OHLC bars.

    The V1 caller may ignore ANY failure and continue with the unmodified
    original response. Incomplete/unverified bars never enter V2.
    """
    now = utc(now or datetime.now(timezone.utc))
    if symbol not in SYMBOLS or not isinstance(bars, list) or len(bars) > 300:
        raise StockShadowError("CANDLE_INPUT_UNSUPPORTED")
    cutoff = now - timedelta(seconds=60)
    observed = {}
    for row in bars:
        if not isinstance(row, dict) or type(row.get("datetime")) is not int:
            raise StockShadowError("CANDLE_SCHEMA_INVALID")
        ms = row["datetime"]
        if ms <= 0 or ms % 300000 != 0:
            raise StockShadowError("CANDLE_TIME_UNALIGNED")
        opened = datetime.fromtimestamp(ms / 1000, timezone.utc)
        closed = opened + timedelta(minutes=5)
        if closed > cutoff or (now - closed).total_seconds() > 14 * 86400:
            continue
        if closed in observed:
            raise StockShadowError("DUPLICATE_CANDLE")
        close = amount(str(row.get("close")), "stock candle close", False)
        observed[closed] = Candle(symbol, closed, close, True)
    if not observed:
        return False
    collected = sorted(observed.values(), key=lambda x: x.observed_at)[-100:]
    parent = _private_dir(Path(state_dir) / "v2")
    root = _private_dir(parent / "stock_shadow")
    folder = _private_dir(root / "candles")
    _atomic_json(folder / (symbol.lower() + ".json"), {
        "version": VERSION, "symbol": symbol, "source": SOURCE,
        "captured_at": now.isoformat(), "granularity_seconds": 300,
        "market_session_verified": False, "broker_executable": False,
        "bars": [{"closed_at": c.observed_at.isoformat(), "close": str(c.close)}
                 for c in collected]
    })
    return True


def _load_closed(state_dir, symbol):
    doc = private_json(_root(state_dir) / "candles" / (symbol.lower() + ".json"),
                       maximum=65000)
    if (not doc or doc.get("version") != VERSION or doc.get("source") != SOURCE
        or doc.get("symbol") != symbol or doc.get("granularity_seconds") != 300
        or doc.get("market_session_verified") is not False
        or doc.get("broker_executable") is not False):
        raise StockShadowError("V1_CANDLE_HISTORY_UNAVAILABLE")
    rows = doc.get("bars")
    if not isinstance(rows, list) or not 1 <= len(rows) <= 100:
        raise StockShadowError("V1_CANDLE_HISTORY_INVALID")
    candles = []
    last = None
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("closed_at"), str):
            raise StockShadowError("V1_CANDLE_HISTORY_INVALID")
        closed = utc(datetime.fromisoformat(row["closed_at"]))
        if last is not None and closed <= last:
            raise StockShadowError("V1_CANDLE_TIME_NONMONOTONIC")
        if closed.timestamp() % 300 != 0:
            raise StockShadowError("V1_CANDLE_TIME_UNALIGNED")
        last = closed
        candles.append(Candle(symbol, closed,
                              amount(row.get("close"), "close", False), True))
    return candles


@contextmanager
def _lock(root):
    root = _private_dir(root)
    fd = os.open(root / "stock.lock",
                 os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_mode & 0o077:
            raise StockShadowError("STOCK_SHADOW_LOCK_UNSAFE")
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _open_events(root):
    path = root / "signal_observations.sqlite3"
    if path.is_symlink():
        raise StockShadowError("SHADOW_JOURNAL_UNSAFE")
    if not path.exists():
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.close(fd)
        except FileExistsError:
            pass
    if path.stat().st_mode & 0o077:
        raise StockShadowError("SHADOW_JOURNAL_UNSAFE")
    db = sqlite3.connect(str(path), timeout=7)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=FULL")
    db.execute("""CREATE TABLE IF NOT EXISTS stock_signals (
        symbol TEXT NOT NULL,
        candle_closed_at TEXT NOT NULL,
        signal TEXT NOT NULL,
        ai_state TEXT NOT NULL,
        reason TEXT NOT NULL,
        recorded_at TEXT NOT NULL,
        PRIMARY KEY(symbol,candle_closed_at)
    )""")
    return db


def _event(db, symbol, candle_at):
    return db.execute(
        "SELECT signal,ai_state,reason FROM stock_signals "
        "WHERE symbol=? AND candle_closed_at=?",
        (symbol, candle_at)).fetchone()


def run_once(state_dir, *, now=None, review=shadow_review, quote_loader=None):
    """Read-only quote/history-to-shadow evaluation for all 24 Schwab symbols."""
    now = utc(now or datetime.now(timezone.utc))
    root = _private_dir(_private_dir(Path(state_dir) / "v2") / "stock_shadow")
    with _lock(root):
        quote_doc = private_json(Path(state_dir) / "live" /
                                 "broker_market_snapshot.json", maximum=30000)
        records = []
        reviewed = 0
        db = _open_events(root)
        try:
            for symbol in SYMBOLS:
                record = {
                    "symbol": symbol, "state": "WAITING_FOR_V1_HISTORY",
                    "source": SOURCE, "signal": None,
                    "ai_shadow": {"state": "NOT_INVOKED"},
                    "market_session_verified": False, "broker_executable": False,
                    "live_orders_submitted": 0, "recorded_candle_count": 0,
                }
                try:
                    bars = _load_closed(state_dir, symbol)
                    record["recorded_candle_count"] = len(bars)
                    record["last_closed_bar_at"] = bars[-1].observed_at.isoformat()
                    if len(bars) < CONTROLLER.long + 1:
                        record["state"] = "WARMING_UP"
                    elif (now - bars[-1].observed_at).total_seconds() > 900:
                        record["state"] = "STALE_CANDLES"
                    elif (now - bars[-1].observed_at).total_seconds() < -2:
                        record["state"] = "FUTURE_CANDLES_REJECTED"
                    elif any((b.observed_at - a.observed_at).total_seconds() != 300
                             for a, b in zip(
                                 bars[-(CONTROLLER.long+1):-1],
                                 bars[-CONTROLLER.long:])):
                        record["state"] = "GAPPED_CANDLES"
                    else:
                        reading = (quote_loader(symbol, now) if quote_loader
                                   else schwab_market_quote(quote_doc, symbol, now=now))
                        if reading.symbol != symbol or reading.asset_class is not AssetClass.STOCK:
                            raise StockShadowError("QUOTE_IDENTITY_INVALID")
                        if not reading.source_tradable or reading.last is None:
                            raise StockShadowError("QUOTE_TRADABILITY_OR_LAST_UNVERIFIED")
                        record["last_quote_at"] = reading.observed_at.isoformat()
                        candidate = CONTROLLER.candidate("v2-shadow-schwab", bars)
                        if candidate is None:
                            record["state"] = "NO_SIGNAL"
                        else:
                            record["signal"] = candidate.side.value
                            record["candidate_at"] = candidate.signal_at.isoformat()
                            record["state"] = "CANDIDATE_SHADOW_ONLY"
                            record["first_blocker"] = "V1_WRITER_OWNS_ORDERS_AND_V2_SESSION_UNVERIFIED"
                            existing = _event(db, symbol, record["candidate_at"])
                            if existing:
                                record["ai_shadow"] = {
                                    "state": existing[1], "reason": existing[2],
                                    "reused_persisted_review": True
                                }
                            else:
                                if reviewed < MAX_REVIEW_PER_CYCLE:
                                    ai = review(candidate, reading.to_inert_snapshot(), now=now)
                                    reviewed += 1
                                    if not isinstance(ai, dict):
                                        raise StockShadowError("AI_SHADOW_SCHEMA_INVALID")
                                    ai_state = str(ai.get("state", "UNAVAILABLE"))[:40]
                                    ai_reason = str(ai.get("reason", ""))[:160]
                                    record["ai_shadow"] = {
                                        "state": ai_state, "reason": ai_reason,
                                        "model": str(ai.get("model",""))[:96],
                                        "latency_ms": max(0,min(60000,
                                            int(ai.get("latency_ms",0) or 0))),
                                        "changed_order_authority": False,
                                    }
                                else:
                                    ai_state, ai_reason = "NOT_INVOKED", "SHADOW_REVIEW_BUDGET"
                                    record["ai_shadow"] = {"state": ai_state,
                                                           "reason": ai_reason}
                                if ai_state != "NOT_INVOKED":
                                    db.execute("""INSERT OR IGNORE INTO stock_signals
                                        (symbol,candle_closed_at,signal,ai_state,reason,recorded_at)
                                        VALUES(?,?,?,?,?,?)""",
                                        (symbol, record["candidate_at"],candidate.side.value,
                                         ai_state, ai_reason,now.isoformat()))
                except (StockShadowError, MarketSourceError, ValueError, TypeError,
                        OverflowError, OSError) as exc:
                    record["state"] = "SOURCE_UNAVAILABLE"
                    record["reason"] = (str(exc)[:90] if isinstance(
                        exc, (StockShadowError, MarketSourceError))
                        else "INVALID_SOURCE_EVIDENCE")
                records.append(record)
            db.commit()
            counters = dict(db.execute(
                "SELECT symbol,COUNT(*) FROM stock_signals GROUP BY symbol").fetchall())
        finally:
            db.close()
        report = {
            "version": VERSION, "observed_at": now.isoformat(),
            "mode": "READ_ONLY_V2_STOCK_SHADOW",
            "source": SOURCE, "universe_size": len(SYMBOLS),
            "live_orders_authorized": False, "live_orders_submitted": 0,
            "broker_sdk_calls": 0, "simulated_orders_submitted": 0,
            "market_session_verified": False,
            "signals_recorded": sum(counters.values()),
            "reports": records,
        }
        _atomic_json(root / "status.json", report)
        return report


def status(state_dir):
    doc = private_json(_root(state_dir) / "status.json", maximum=65000)
    if not doc or doc.get("version") != VERSION:
        return {"mode": "READ_ONLY_V2_STOCK_SHADOW",
                "state": "NOT_STARTED", "live_orders_authorized": False,
                "reports": []}
    try:
        now = datetime.now(timezone.utc)
        age = int((now - utc(datetime.fromisoformat(doc["observed_at"]))).total_seconds())
    except (ValueError, TypeError, KeyError):
        age = None
    result = dict(doc)
    result["heartbeat_age_sec"] = age
    result["state"] = "RUNNING" if age is not None and -2 <= age <= 180 else "STALE_WORKER"
    result["live_orders_authorized"] = False
    return result


def _stop(_sig, _frame):
    global _STOP
    _STOP = True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--state-dir", required=True)
    args = parser.parse_args()
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    while not _STOP:
        start = time.monotonic()
        try:
            report = run_once(args.state_dir)
            counts = {}
            for row in report["reports"]:
                state = row["state"]
                counts[state] = counts.get(state, 0) + 1
            print("V2 stock shadow scan", len(report["reports"]),
                  "sources", counts, flush=True)
        except Exception as exc:
            print("V2 stock shadow read-only error", type(exc).__name__,
                  flush=True)
        while not _STOP and time.monotonic() - start < POLL_SECONDS:
            time.sleep(1)


if __name__ == "__main__":
    main()
