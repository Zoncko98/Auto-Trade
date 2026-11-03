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
    save_stock_feed, stock_feed_configured, StreamError)
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

    def test_stock_auth_feed_quote_and_bars(self):
        book=FeedBook()
        book.set_status("alpaca","AUTHENTICATED")
        self.assertTrue(book.alpaca_event(self.stock_quote()))
        self.assertFalse(book.alpaca_event(self.stock_quote(bid=101,ask=100)))
        self.assertFalse(book.alpaca_event({**self.stock_quote(), "t":"2020-01-01T12:00:00Z"}))
        self.assertFalse(book.alpaca_event({**self.stock_quote(), "S":"FAKEPACA"}))
        for i in range(7,0,-1):
            t=(NOW()-timedelta(minutes=i)).replace(second=0,microsecond=0).isoformat()
            self.assertTrue(book.alpaca_event({"T":"b","S":"AAPL","c":str(99+(7-i)*0.1),"t":t}))
        snap=self._write_book(book)
        obs=market_observation(snap,"EQUITY","AAPL")
        self.assertEqual(obs["source"],"ALPACA_IEX_WS")
        self.assertEqual(obs["quote"]["bid"],"100")
        self.assertEqual(len(obs["bars"]),7)
        book.set_status("alpaca","AUTH_ERROR")
        self.assertIsNone(market_observation(self._write_book(book),"EQUITY","AAPL"))

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
        self.assertFalse(feed_status(self.root)["stock_feed_configured"])

    def test_stock_feed_credentials_are_private_and_not_in_status(self):
        payload={"key":"testkey123456","secret":"testsecret123456"}
        saved=save_stock_feed(self.root,payload)
        self.assertTrue(saved["configured"])
        f=self.root/"webull"/"alpaca_iex_credentials.json"
        self.assertEqual(f.stat().st_mode & 0o077,0)
        self.assertEqual(f.parent.stat().st_mode & 0o077,0)
        response=json.dumps(feed_status(self.root))
        self.assertNotIn(payload["key"],response)
        self.assertNotIn(payload["secret"],response)
        for bad in ({"key":"a","secret":"toolongsecret"},
                    {"key":"A"*30,"secret":("secre" + chr(10) + "there")},
                    {"enabled":True}, {"key":"A"*30,"secret":"secretsecret","env":"sip"}):
            with self.assertRaises(StreamError):
                save_stock_feed(self.root,bad)
        self.assertTrue(stock_feed_configured(self.root))
        save_stock_feed(self.root,{"enabled":False})
        self.assertFalse(f.exists())

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
