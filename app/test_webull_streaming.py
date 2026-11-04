"""Streaming discovery tests use fixture messages only: no network or broker orders."""
import json
import os
import sys
import tempfile
import time
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parent))

from dashboard_control import write_atomic
from webull_streaming import (
    FeedBook, _price, _timestamp, read_snapshot, market_observation, feed_status,
    StreamError)
from webull_signals import evaluate, WebullSignalError
from webull_worker import _scan, _order
from webull_journal import WebullJournal

NOW = lambda: datetime.now(timezone.utc)

class StreamingTests(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.root = Path(t.name)
        (self.root / "webull").mkdir(mode=0o700)

    def stock_quote(self, sym="AAPL", seconds=0, bid=100, ask=100.05):
        return {"T":"q","S":sym,"bp":bid,"ap":ask,
                "t":(NOW()-timedelta(seconds=seconds)).isoformat()}

    def coinbase_quote(self, sym="BTC-USD", price="70000", seconds=0):
        t=(NOW()-timedelta(seconds=seconds)).isoformat()
        return {"type":"ticker","product_id":sym,"best_bid":"69999",
                "best_ask":"70001","price":price,"time":t}

    def _write_book(self, book):
        write_atomic(self.root/"webull"/"ws_market.json", book.snapshot())
        return read_snapshot(self.root)

    def test_crypto_public_market_quote_and_completed_m1_bars(self):
        book=FeedBook()
        book.set_status("coinbase","CONNECTED")
        self.assertTrue(book.coinbase_ticker(self.coinbase_quote()))
        self.assertFalse(book.coinbase_ticker(self.coinbase_quote(sym="TRUMP-USD")))
        self.assertFalse(book.coinbase_ticker({**self.coinbase_quote(), "best_ask":"1"}))
        self.assertFalse(book.coinbase_ticker({**self.coinbase_quote(), "best_bid":"NaN"}))
        self.assertFalse(book.coinbase_ticker(self.coinbase_quote(seconds=100)))
        snap=self._write_book(book)
        self.assertIsNone(market_observation(snap,"CRYPTO","BTCUSD"))
        self.assertEqual(snap["quotes"]["CRYPTO"]["BTCUSD"]["source"],"COINBASE_WS")
        status=feed_status(self.root)
        self.assertEqual(len(status["crypto_spreads"]),1)
        self.assertEqual(status["crypto_spreads"][0]["symbol"],"BTCUSD")
        self.assertLess(status["crypto_spreads"][0]["spread_pct"],0.5)
        self.assertFalse(status["crypto_spreads"][0]["executable_webull_quote"])
        self.assertNotIn("key",status["crypto_spreads"][0])
        # Only after six actual completed minute observations can this source
        # be used for momentum discovery. It cannot submit an order.
        now=NOW()
        for i in range(7,0,-1):
            minute=(now-timedelta(minutes=i)).replace(second=0,microsecond=0).isoformat()
            book.bars[("CRYPTO","BTCUSD")][minute]=str(69500+(7-i)*70)
        snap=self._write_book(book)
        obs=market_observation(snap,"CRYPTO","BTCUSD")
        self.assertEqual(obs["source"],"COINBASE_WS")
        signal=evaluate("BTCUSD","CRYPTO",obs["quote"],obs["bars"],source=obs["source"])
        self.assertEqual(signal["source"],"COINBASE_WS")
        self.assertLess(signal["spread_pct"],0.5)
        self.assertNotIn("broker_order_id",signal)

    def test_stock_always_uses_webull_native_not_removed_iex_feed(self):
        book=FeedBook()
        book.set_status("coinbase","CONNECTED")
        row=self.coinbase_quote()
        self.assertTrue(book.coinbase_ticker(row))
        self.assertEqual(book.snapshot()["quotes"]["EQUITY"] if "EQUITY" in book.snapshot()["quotes"] else {},{})
        # Reject historical or forged IEX snapshots and use Webull stock REST.
        old_snapshot={"updated_epoch":time.time(),
                      "feeds":{"alpaca":{"status":"AUTHENTICATED"},
                               "coinbase":{"status":"CONNECTED"}},
                      "quotes":{"EQUITY":{"AAPL":{"source":"ALPACA_IEX_WS",
                          "bid":"100","ask":"100.05","event_epoch":time.time(),
                          "quote_time":NOW().isoformat(),
                          "bars":[{"time":NOW().isoformat(),"close":"100"}]*7}}}}
        self.assertIsNone(market_observation(old_snapshot,"EQUITY","AAPL"))
        self.assertEqual(feed_status(self.root)["stock_discovery_source"],"WEBULL_NATIVE")
        with self.assertRaises(WebullSignalError):
            evaluate("AAPL","EQUITY",{"bid":"100","ask":"100.05",
                "quote_time":NOW().isoformat()},[],source="ALPACA_IEX_WS")

    def test_staleness_and_external_quote_fail_closed(self):
        book=FeedBook()
        book.set_status("coinbase","CONNECTED")
        book.coinbase_ticker(self.coinbase_quote())
        for i in range(7,0,-1):
            t=(NOW()-timedelta(minutes=i)).replace(second=0,microsecond=0).isoformat()
            book.bars[("CRYPTO","BTCUSD")][t]="70000"
        snap=self._write_book(book)
        self.assertIsNotNone(market_observation(snap,"CRYPTO","BTCUSD"))
        snap["quotes"]["CRYPTO"]["BTCUSD"]["event_epoch"]=time.time()-95
        self.assertIsNone(market_observation(snap,"CRYPTO","BTCUSD"))
        write_atomic(self.root/"webull"/"ws_market.json",
                     dict(snap,updated_epoch=time.time()-100))
        self.assertEqual(read_snapshot(self.root),{})
        with self.assertRaises(WebullSignalError):
            evaluate("BTCUSD","CRYPTO",{"bid":"1","ask":"2",
                  "quote_time":NOW().isoformat()},[],source="UNTRUSTED_FEED")
        self.assertNotIn("stock_feed_configured",feed_status(self.root))
        self.assertNotIn("stocks",feed_status(self.root))

    def test_removed_stock_feed_has_no_api_or_frontend_configuration(self):
        root=Path(__file__).resolve().parent.parent
        api=(root/"app"/"dashboard_server.py").read_text()
        runtime=(root/"app"/"unified_runtime.py").read_text()
        ui=(root/"web"/"brokers.js").read_text()
        trade_ui=(root/"web"/"app.js").read_text()
        stream=(root/"app"/"webull_streaming.py").read_text()
        self.assertNotIn("/api/webull/stock-feed",api)
        self.assertNotIn("alpaca_iex_credentials.json",runtime)
        self.assertNotIn("alpaca_iex_credentials.json",stream)
        self.assertNotIn("ALPACA_IEX",stream)
        self.assertNotIn("ALPACA_IEX",trade_ui)
        self.assertNotIn("Alpaca IEX",ui)
        self.assertNotIn("IEX WebSocket",ui)
        self.assertIn("Coinbase",ui)
        self.assertIn("Webull native OpenAPI",trade_ui)
        self.assertIn("COINBASE_URL",stream)
        self.assertIn("webull-feed",runtime)
        # Standalone Alpaca broker roadmap remains unchanged.
        self.assertIn('data-workspace="alpaca"',(root/"web"/"index.html").read_text())

    def test_stream_discovery_does_not_replace_webull_execution_quote(self):
        from webull_worker import WebullBlocked
        from webull_signals import WebullSignalError
        from webull_streaming import FeedBook
        class Broker:
            def __init__(self):self.place_calls=0
            def quote(self,symbol,asset):
                return {"symbol":symbol,"bid":"9","ask":"10",
                        "quote_time":NOW().isoformat()}
            def place(self,account,payload):
                self.place_calls+=1
                raise AssertionError("No broker orders allowed")
        root=self.root
        report={}
        book=FeedBook()
        book.set_status("coinbase","CONNECTED")
        book.coinbase_ticker(self.coinbase_quote(sym="BTC-USD"))
        for i in range(7,0,-1):
            bar=(NOW()-timedelta(minutes=i)).replace(second=0,microsecond=0).isoformat()
            book.bars[("CRYPTO","BTCUSD")][bar]=str(69000+(7-i)*100)
        self._write_book(book)
        fake=Broker()
        # External discovery produces technical signals without polling Webull.
        # Legacy broker fallback still runs for unavailable stream symbols.
        class ScanBroker(Broker):
            def bars(self,symbol,asset):
                return [{"time":(NOW()-timedelta(minutes=i)).isoformat(),"close":"9.5"}
                        for i in range(7,0,-1)]
        with patch("ai_research.approve_entry",return_value=(True,"Allowed")),\
             patch("ai_research.research_evidence",return_value={"model":"fixture"}):
            _scan(root,ScanBroker(),0,report)
        self.assertEqual(report["signals"][3]["source"],"COINBASE_WS")
        self.assertEqual(fake.place_calls,0)
        # Even if downstream AI approves, Webull's 10% executable spread
        # blocks the real order before any intent or broker write.
        signal={"at":NOW().isoformat(),"symbol":"BTCUSD","asset":"CRYPTO",
                "technical_approved":True,"ai_approved":True,"ask":"70001",
                "source":"COINBASE_WS"}
        journal=WebullJournal(root)
        with self.assertRaises(WebullSignalError):
            _order(root,fake,{"enabled":False},{},journal,
                   "acct","BTCUSD","CRYPTO","BUY",signal,"0.001","70001","AI")
        self.assertEqual(fake.place_calls,0)
        self.assertEqual(journal.recent(),[])

if __name__=="__main__":
    unittest.main()
