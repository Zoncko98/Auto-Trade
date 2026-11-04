"""Webull crypto discovery-only streaming from the public Coinbase ticker.

Webull stock scanning uses the broker's own native quote/bar endpoints.
Coinbase quotes cannot replace fresh Webull executable bid/ask, account,
risk or reconciliation checks. No WebSocket handler submits orders.
"""
from __future__ import annotations
import json
import os
import signal
import stat
import threading
import time
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

from dashboard_control import write_atomic

COINBASE_URL = "wss://ws-feed.exchange.coinbase.com"
COINS = ("BTCUSD", "ETHUSD", "SOLUSD", "DOGEUSD", "XRPUSD", "AVAXUSD")
COINBASE_PRODUCTS = {s[:-3] + "-USD": s for s in COINS}
MAX_FILE = 250_000

class StreamError(ValueError):
    pass

def _path(root):
    return Path(root) / "webull" / "ws_market.json"

def _secure_parent(root):
    folder = Path(root) / "webull"
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    if folder.is_symlink() or not folder.is_dir():
        raise StreamError("Unsafe Webull market-data directory")
    if folder.stat().st_mode & 0o077:
        os.chmod(folder, 0o700)
    if folder.stat().st_mode & 0o077:
        raise StreamError("Webull market-data directory is not private")
    return folder

def read_snapshot(root):
    target = _path(root)
    try:
        st = target.lstat()
        if not stat.S_ISREG(st.st_mode) or st.st_size > MAX_FILE or st.st_mode & 0o077:
            return {}
        record = json.loads(target.read_text())
        if not isinstance(record, dict) or not isinstance(record.get("feeds"), dict) or not isinstance(record.get("quotes"), dict):
            return {}
        age = time.time() - float(record["updated_epoch"])
        if not 0 <= age <= 35:
            return {}
        return record
    except (OSError, ValueError, TypeError, KeyError):
        return {}

def feed_status(root):
    snapshot = read_snapshot(root)
    feeds = snapshot.get("feeds", {})
    spreads = []
    for symbol, quote in sorted(snapshot.get("quotes", {}).get("CRYPTO", {}).items()):
        if symbol not in COINS or not isinstance(quote,dict):
            continue
        try:
            bid,ask=Decimal(str(quote["bid"])),Decimal(str(quote["ask"]))
            age=time.time()-float(quote["event_epoch"])
            if not 0<=age<=90 or not 0<bid<=ask or not ask.is_finite():
                continue
            spread=float((ask-bid)/ask*100)
            if not 0<=spread<=100:continue
            spreads.append({"symbol":symbol,"source":"COINBASE_WS",
                            "spread_pct":round(spread,4),
                            "quote_age_seconds":round(age,1),
                            "fresh":age<=30,"executable_webull_quote":False})
        except (KeyError,TypeError,ValueError,InvalidOperation,OverflowError):
            continue
    return {"crypto": feeds.get("coinbase", {"status": "STARTING"}),
            "crypto_spreads": spreads,
            "stock_discovery_source": "WEBULL_NATIVE",
            "execution_quote_source": "WEBULL_BROKER_ONLY",
            "discovery_only": True}

def _price(raw):
    if isinstance(raw, bool) or not isinstance(raw, (str, int, float, Decimal)):
        raise StreamError("Price missing")
    try:
        v = Decimal(str(raw))
    except (InvalidOperation, ValueError):
        raise StreamError("Invalid feed price") from None
    if not v.is_finite() or v <= 0 or v > Decimal("100000000"):
        raise StreamError("Invalid feed price")
    return str(v)

def _timestamp(raw):
    if not isinstance(raw, str) or len(raw) > 48:
        raise StreamError("Missing feed timestamp")
    try:
        stamp = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            raise StreamError("Time zone required")
        epoch = stamp.timestamp()
        if not -10 <= time.time() - epoch <= 1200:
            raise StreamError("Market observation expired or in future")
        return epoch
    except (ValueError, OverflowError):
        raise StreamError("Invalid market timestamp") from None

def _iso_minute(epoch):
    return datetime.fromtimestamp(int(epoch // 60) * 60, timezone.utc).isoformat()

class FeedBook:
    def __init__(self):
        self.lock = threading.RLock()
        self.rows = {"CRYPTO": {}}
        self.feeds = {"coinbase": {"status": "CONNECTING", "last_received_at": None}}
        self.bars = defaultdict(dict)

    def set_status(self, provider, status):
        with self.lock:
            self.feeds[provider]["status"] = status

    def _touch(self, provider):
        self.feeds[provider]["last_received_at"] = datetime.now(timezone.utc).isoformat()

    def coinbase_ticker(self, raw):
        if not isinstance(raw, dict) or raw.get("type") != "ticker":
            return False
        product = raw.get("product_id")
        if product not in COINBASE_PRODUCTS:
            return False
        try:
            bid = _price(raw.get("best_bid"))
            ask = _price(raw.get("best_ask"))
            close = _price(raw.get("price"))
            epoch = _timestamp(raw.get("time"))
            if Decimal(bid) > Decimal(ask):
                raise StreamError("Crossed feed market")
            if time.time() - epoch > 90:
                return False
        except StreamError:
            return False
        sym = COINBASE_PRODUCTS[product]
        with self.lock:
            previous = self.rows["CRYPTO"].get(sym)
            if previous and epoch < previous.get("event_epoch", 0):
                return False
            self.bars[("CRYPTO", sym)][_iso_minute(epoch)] = close
            self._trim("CRYPTO", sym)
            self.rows["CRYPTO"][sym] = {
                "bid": bid, "ask": ask, "quote_time": raw["time"],
                "event_epoch": epoch, "source": "COINBASE_WS"}
            self._touch("coinbase")
        return True

    def _trim(self, asset, symbol):
        entry = self.bars[(asset, symbol)]
        cutoff = time.time() - 21 * 60
        for minute in list(entry):
            try:
                ts = datetime.fromisoformat(minute).timestamp()
            except ValueError:
                ts = 0
            if ts < cutoff:
                entry.pop(minute, None)
        if len(entry) > 25:
            for minute in sorted(entry)[:-25]:
                entry.pop(minute, None)

    def snapshot(self):
        with self.lock:
            quotes = {}
            for asset, items in self.rows.items():
                quotes[asset] = {}
                for symbol, row in items.items():
                    if time.time() - row["event_epoch"] <= 90:
                        quotes[asset][symbol] = {
                            **row,
                            "bars": [{"time": k, "close": v}
                                     for k, v in sorted(self.bars[(asset, symbol)].items())]}
            return {"updated_epoch": time.time(), "feeds": json.loads(json.dumps(self.feeds)),
                    "quotes": quotes}

def market_observation(snapshot, asset, symbol):
    """Return a fresh discovery quote and completed bars, never an execution quote."""
    if not isinstance(snapshot, dict) or asset != "CRYPTO":
        return None
    source = "COINBASE_WS"
    feed = snapshot.get("feeds", {}).get("coinbase", {})
    if feed.get("status") != "CONNECTED":
        return None
    row = snapshot.get("quotes", {}).get(asset, {}).get(symbol)
    if not isinstance(row, dict) or row.get("source") != source:
        return None
    try:
        if not 0 <= time.time() - float(row["event_epoch"]) <= 90:
            return None
        if len(row.get("bars", [])) < 6:
            return None
    except (TypeError, ValueError):
        return None
    return {"quote": {k: row[k] for k in ("bid", "ask", "quote_time")},
            "bars": row["bars"], "source": source}

def _coinbase(book, stop):
    import websocket
    products = list(COINBASE_PRODUCTS)
    delay = 4
    while not stop.is_set():
        def opened(ws):
            book.set_status("coinbase", "CONNECTED")
            ws.send(json.dumps({"type": "subscribe", "product_ids": products,
                                "channels": ["ticker"]}))
        def received(_ws, msg):
            try:
                obj = json.loads(msg)
                book.coinbase_ticker(obj)
            except (TypeError, ValueError, json.JSONDecodeError):
                return
        def closed(_ws, _code, _reason):
            book.set_status("coinbase", "RECONNECTING")
        def failed(_ws, _exc):
            book.set_status("coinbase", "RECONNECTING")
        try:
            ws = websocket.WebSocketApp(COINBASE_URL, on_open=opened,
                  on_message=received, on_close=closed, on_error=failed)
            ws.run_forever(ping_interval=25, ping_timeout=10)
        except Exception:
            book.set_status("coinbase", "RECONNECTING")
        stop.wait(delay)
        delay = min(delay * 2, 60)

def main():
    state = Path(os.environ.get("STATE_DIR", "/state"))
    _secure_parent(state)
    stop = threading.Event()
    for number in (signal.SIGINT, signal.SIGTERM):
        signal.signal(number, lambda *_: stop.set())
    book = FeedBook()
    threading.Thread(target=_coinbase, args=(book, stop), daemon=True).start()
    while not stop.is_set():
        write_atomic(_path(state), book.snapshot())
        stop.wait(5)

if __name__ == "__main__":
    main()
