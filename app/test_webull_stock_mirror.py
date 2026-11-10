"""Webull stock entry equivalence with the Schwab shared 5-minute selector.

No network or brokerage orders; uses synthetic Webull depth/snapshot/M5 responses.
"""
import sys
import unittest
from datetime import datetime,timedelta,timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent))
from webull_stock_strategy import scan_webull_stock,revalidate_webull_stock,STOCK_SOURCE
from shared_strategy import select_entry
from webull_signals import WebullSignalError
from webull_broker import WebullBroker,WebullError
from types import SimpleNamespace

NOW=datetime(2026,11,4,15,46,tzinfo=timezone.utc)  # 10:46 ET, regular market
SYMBOL="F"
M5=[{"time":(datetime(2026,11,4,15,10,tzinfo=timezone.utc)+timedelta(minutes=5*i)).isoformat(),
     "close":str(x),"trading_sessions":"RTH"} for i,x in enumerate(
         ("5.10","5.11","5.13","5.14","5.16","5.18"))]
DEPTH={"symbol":SYMBOL,"bid":"5.18","ask":"5.19","quote_time":NOW.isoformat()}
SNAP={"symbol":SYMBOL,"volume":"1000000","change_ratio":"0.012",
      "last_trade_time":int(NOW.timestamp()*1000)}

class BrokerFixture:
    def __init__(self,depth=None,snapshot=None,bars=None):
        self.depth=depth or DEPTH
        self.snapshot=snapshot or SNAP
        self.candles=bars if bars is not None else M5
        self.calls=[]
        self.orders=[]
    def quote(self,symbol,asset):
        self.calls.append(("quote",symbol,asset))
        return self.depth
    def stock_snapshot(self,symbol):
        self.calls.append(("snapshot",symbol))
        return self.snapshot
    def bars(self,symbol,asset,period="M1"):
        self.calls.append(("bars",symbol,asset,period))
        return self.candles
    def place(self,*args,**kwargs):
        self.orders.append((args,kwargs))
        raise AssertionError("Discovery may not place an order")

class SharedStockTests(unittest.TestCase):
    def test_same_schwab_m5_selection_continuation_under_webull_market_data(self):
        broker=BrokerFixture()
        diagnostics,selected=scan_webull_stock(broker,[SYMBOL],NOW)
        self.assertIsNotNone(selected)
        self.assertEqual(selected["symbol"],SYMBOL)
        self.assertEqual(selected["source"],STOCK_SOURCE)
        self.assertTrue(selected["technical_approved"])
        self.assertIn("continuing momentum",selected["reason"])
        self.assertEqual(selected["bars"],6)
        self.assertEqual(selected["spread_pct"],0.1927)
        self.assertIn(("bars","F","EQUITY","M5"),broker.calls)
        self.assertEqual(broker.orders,[])
        # Schwab's reference selector is imported ONLY in this parity test.
        # Production Webull must have a separate local implementation.
        quote_map={"F":{"assetMainType":"EQUITY","quote":{
           "bidPrice":"5.18","askPrice":"5.19","quoteTime":int(NOW.timestamp()*1000),
           "totalVolume":"1000000","netPercentChange":"1.2"}}}
        converted=[{"datetime":int(datetime.fromisoformat(b["time"]).timestamp()*1000),
                    "close":b["close"]} for b in M5]
        reference,_=select_entry(quote_map,lambda _:converted,NOW,universe=(SYMBOL,))
        self.assertIsNotNone(reference)
        self.assertEqual(selected["shared_candle"],reference.candle)
        self.assertEqual(selected["reason"],
                         reference.reason.replace("shared stock strategy",
                                                  "Webull mirrored stock strategy"))
        self.assertEqual(diagnostics[0]["technical_approved"],True)
    def test_revalidation_uses_own_mirrored_5_minute_signal(self):
        broker=BrokerFixture()
        selected=revalidate_webull_stock(broker,"F",NOW)
        self.assertEqual(selected["source"],STOCK_SOURCE)
        self.assertTrue(selected["technical_approved"])
        self.assertEqual([x for x in broker.calls if x[0]=="bars"][0][-1],"M5")
        stale=BrokerFixture(bars=[{"time":(NOW-timedelta(minutes=40+i*5)).isoformat(),
                                   "close":"5.2"} for i in range(6)])
        with self.assertRaises(WebullSignalError):
            revalidate_webull_stock(stale,"F",NOW)
    def test_bad_market_data_never_generates_trade(self):
        broken=(
          BrokerFixture(depth=dict(DEPTH,quote_time=(NOW-timedelta(seconds=80)).isoformat())),
          BrokerFixture(depth=dict(DEPTH,bid="5.00")),
          BrokerFixture(snapshot=dict(SNAP,volume="1")),
          BrokerFixture(snapshot=dict(SNAP,symbol="MSFT")),
          BrokerFixture(snapshot=dict(SNAP,change_ratio="NaN")),
          BrokerFixture(bars=[]),
        )
        for broker in broken:
            with self.subTest(broker=broker.__dict__):
                rows,candidate=scan_webull_stock(broker,[SYMBOL],NOW)
                self.assertIsNone(candidate)
                self.assertFalse(rows[0]["technical_approved"])
                self.assertFalse(broker.orders)
    def test_crypto_strategy_still_separate_from_schwab_stock_strategy(self):
        from webull_worker import CRYPTOS,STOCKS,MAX_STOCKS_PER_CYCLE
        self.assertNotIn("BTCUSD",STOCKS)
        self.assertIn("BTCUSD",CRYPTOS)
        self.assertEqual(MAX_STOCKS_PER_CYCLE,len(STOCKS))
        self.assertEqual(len(STOCKS),24)
    def test_expanded_discovery_rotates_without_increasing_per_cycle_quote_budget(self):
        from webull_stock_strategy import (
            STOCK_DISCOVERY_UNIVERSE, STOCKS_PER_CYCLE, rotating_stock_batch,
            STOCK_SCAN_SYMBOLS)
        self.assertGreaterEqual(len(STOCK_DISCOVERY_UNIVERSE), 75)
        self.assertEqual(len(STOCK_DISCOVERY_UNIVERSE), len(set(STOCK_DISCOVERY_UNIVERSE)))
        self.assertEqual(STOCKS_PER_CYCLE, 24)
        self.assertEqual(tuple(rotating_stock_batch(0)), STOCK_SCAN_SYMBOLS)
        seen = set()
        for offset in range(0, len(STOCK_DISCOVERY_UNIVERSE), STOCKS_PER_CYCLE):
            batch = rotating_stock_batch(offset)
            self.assertEqual(len(batch), STOCKS_PER_CYCLE)
            self.assertEqual(len(batch), len(set(batch)))
            seen.update(batch)
        self.assertEqual(seen, set(STOCK_DISCOVERY_UNIVERSE))
        self.assertEqual(rotating_stock_batch(len(STOCK_DISCOVERY_UNIVERSE)),
                         rotating_stock_batch(0))

    def test_live_broker_m5_and_snapshot_validate_symbol_and_order_is_never_called(self):
        broker=WebullBroker.__new__(WebullBroker)
        calls=[]
        def history(*args,**kwargs):
            calls.append((args,kwargs))
            return SimpleNamespace(status_code=200,
               json=lambda:{"symbol":"F","result":M5})
        broker.data=SimpleNamespace(market_data=SimpleNamespace(
            get_history_bar=history,
            get_snapshot=lambda *a,**k:SimpleNamespace(status_code=200,
                json=lambda:[dict(SNAP)])))
        self.assertEqual(broker.bars("F","EQUITY",period="M5"),M5)
        self.assertEqual(calls[0][0],("F","US_STOCK","M5"))
        self.assertEqual(calls[0][1]["trading_sessions"],"RTH")
        self.assertEqual(broker.stock_snapshot("F")["volume"],"1000000")
        with self.assertRaises(WebullError):
            broker.stock_snapshot("MSFT")
        with self.assertRaises(WebullError):
            broker.bars("F","EQUITY",period="M15")

if __name__=="__main__":unittest.main()
