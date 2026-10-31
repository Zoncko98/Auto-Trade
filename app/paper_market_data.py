"""Public timestamped quotes for the existing paper-only worker.

No Schwab credentials, orders or live-workspace dependencies. A failed,
delayed, or closed feed yields no new observations and never invents prices.
"""
from __future__ import annotations
import csv
import json
import math
import os
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.request import Request, urlopen

STOCKS = {"SPY", "QQQ", "AAPL", "MSFT"}
CRYPTO = {"BTCUSD": "XBTUSD", "ETHUSD": "ETHUSD"}
SYMBOLS = STOCKS | set(CRYPTO)

def _get_json(url, opener=urlopen):
    req = Request(url, headers={"User-Agent": "AutoTrader-Paper/1.0"})
    with opener(req, timeout=8) as r:
        blob = r.read(500001)
    if len(blob) > 500000:
        raise ValueError("Market response exceeds size limit")
    return json.loads(blob)

def _stock(symbol, now, getter):
    from urllib.parse import quote
    doc = getter("https://query1.finance.yahoo.com/v8/finance/chart/" +
                 quote(symbol) + "?interval=1m&range=1d")
    item = doc["chart"]["result"][0]
    ts = item["timestamp"]
    closes = item["indicators"]["quote"][0]["close"]
    for stamp, close in reversed(list(zip(ts, closes))):
        if close is not None and math.isfinite(float(close)) and float(close) > 0:
            when = datetime.fromtimestamp(int(stamp), timezone.utc)
            # A forming one-minute bar must not become an executable paper quote.
            if when + timedelta(minutes=1) <= now:
                return {"timestamp": when.isoformat(), "symbol": symbol, "price": float(close)}
    raise ValueError("No completed market bar")

def _crypto(symbol, now, getter):
    doc = getter("https://api.kraken.com/0/public/OHLC?pair=" +
                 CRYPTO[symbol] + "&interval=1")
    if doc.get("error"):
        raise ValueError("Public crypto market feed error")
    rows = next(v for k,v in doc["result"].items() if k!="last")
    if not isinstance(rows, list):
        raise ValueError("Invalid market candles")
    for row in reversed(rows):
        when = datetime.fromtimestamp(int(row[0]), timezone.utc)
        price = float(row[4])
        if when + timedelta(minutes=1) <= now and math.isfinite(price) and price > 0:
            return {"timestamp": when.isoformat(), "symbol": symbol, "price": price}
    raise ValueError("No completed crypto bar")

def recent_quote(symbol, now=None, getter=_get_json):
    if symbol not in SYMBOLS:
        raise ValueError("Unrecognized public paper symbol")
    now = now or datetime.now(timezone.utc)
    row = _stock(symbol, now, getter) if symbol in STOCKS else _crypto(symbol, now, getter)
    at = datetime.fromisoformat(row["timestamp"])
    age = (now - at).total_seconds()
    if age < 0 or age > 600:
        raise ValueError("Quote unavailable or older than 10 minutes")
    return row

def append_new_quotes(path, observations):
    """Atomic bounded CSV. Only real source timestamps, never arrival time."""
    path = Path(path)
    if not observations:
        return 0
    rows = []
    if path.exists():
        with path.open(newline="", encoding="utf-8") as inp:
            reader = csv.DictReader(inp)
            if set(reader.fieldnames or []) != {"timestamp", "symbol", "price"}:
                raise ValueError("Existing paper price CSV has an invalid schema")
            rows = list(reader)[-230:]
    seen = {(row["symbol"], row["timestamp"]) for row in rows}
    count = 0
    for row in observations:
        key = (row["symbol"], row["timestamp"])
        if key not in seen:
            rows.append(row)
            seen.add(key)
            count += 1
    if not count:
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".paper-prices-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", newline="", encoding="utf-8") as out:
            writer = csv.DictWriter(out, fieldnames=["timestamp", "symbol", "price"])
            writer.writeheader()
            writer.writerows(rows[-240:])
            out.flush()
            os.fsync(out.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return count

def poll(path, symbols, now=None, quote=recent_quote):
    now = now or datetime.now(timezone.utc)
    received = []
    failures = {}
    for symbol in sorted(symbols & SYMBOLS):
        try:
            received.append(quote(symbol, now=now))
        except Exception as exc:
            failures[symbol] = type(exc).__name__
    count = append_new_quotes(path, received)
    return {"added": count, "market_count": len(received),
            "unavailable": failures, "checked_at": now.isoformat()}
