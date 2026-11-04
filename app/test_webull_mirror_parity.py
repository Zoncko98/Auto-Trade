"""Cross-engine parity tests: Schwab and Webull are separate implementations.

Schwab's original functions are imported only in these tests. Webull's
production module must not import or call Schwab's strategy at runtime.
"""
import ast
import sys
import unittest
from datetime import datetime,timedelta,timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parent))
from webull_stock_strategy import (
    STOCK_SCAN_SYMBOLS, MAX_RANKED, STOCK_SOURCE, _rank_quote,
    _ranked_candidates, _cross_signal, _choose_entry,
    scan_webull_stock,
)
from autonomous_selector import (
    UNIVERSE, MAX_SCAN, quote_rank, ranked_candidates, choose_entry,
)
from live_order_safety import cross_signal,LiveBlocked
from webull_signals import WebullSignalError
from test_webull_stock_mirror import BrokerFixture, M5, NOW

class IndependentMirrorParity(unittest.TestCase):
    def test_production_import_graph_has_no_schwab_strategy_dependency(self):
        root=Path(__file__).resolve().parent
        for file in ("webull_stock_strategy.py","webull_worker.py"):
            syntax=ast.parse((root/file).read_text())
            imports=set()
            for node in ast.walk(syntax):
                if isinstance(node,ast.Import):
                    imports.update(alias.name for alias in node.names)
                elif isinstance(node,ast.ImportFrom):
                    imports.add(node.module or "")
            self.assertTrue({"autonomous_selector","live_order_safety","shared_strategy"}.isdisjoint(imports),
                            f"{file} unexpectedly imports Schwab strategy")
        self.assertFalse((root/"webull_shared_stock.py").exists())
        self.assertEqual(STOCK_SOURCE,"WEBULL_MIRROR_SCHWAB_M5")
    def test_copied_universe_and_screening_parameters_initially_match(self):
        from webull_stock_strategy import (
            MIN_PRICE,MAX_PRICE,MIN_VOLUME,MAX_SPREAD_PCT
        )
        from autonomous_selector import (
            MIN_PRICE as S_MIN,MAX_PRICE as S_MAX,
            MIN_VOLUME as S_VOL,MAX_SPREAD_PCT as S_SPREAD,
        )
        self.assertEqual(STOCK_SCAN_SYMBOLS,UNIVERSE)
        self.assertEqual(MAX_RANKED,MAX_SCAN)
        self.assertEqual((MIN_PRICE,MAX_PRICE,MIN_VOLUME,MAX_SPREAD_PCT),
                         (S_MIN,S_MAX,Decimal(S_VOL),S_SPREAD))
    def test_ranking_and_rejections_agree_with_schwab_across_broker_independent_quotes(self):
        cases=[
          ("5.18","5.19","1000000","1.2",0),
          ("5.18","5.19","500000","-1.2",0),
          ("6","6.04","200000","5",0),
          ("5","5.04","199999","0",0),
          ("3.00","3.01","250000","1",0),
          ("31","31.02","250000","1",0),
          ("5.18","5.19","1000000","13",0),
          ("5.18","5.19","1000000","0",75),
          ("5.18","5.19","1000000","NaN",0),
          ("5.18","5.19","1000000","0",-8),
          ("5.20","5.19","1000000","0",0),
        ]
        for bid,ask,volume,change,age in cases:
            with self.subTest(bid=bid,ask=ask,volume=volume,change=change,age=age):
                row={"assetMainType":"EQUITY","quote":{
                    "bidPrice":bid,"askPrice":ask,"totalVolume":volume,
                    "netPercentChange":change,
                    "quoteTime":int((NOW-timedelta(seconds=age)).timestamp()*1000)}}
                try:
                    expected=quote_rank("F",row,NOW)
                except (LiveBlocked,ValueError,TypeError):
                    expected=None
                try:
                    actual=_rank_quote("F",row,NOW)
                except (WebullSignalError,ValueError,TypeError):
                    actual=None
                self.assertEqual(actual,expected)
    def test_completed_candle_cross_signal_identical_over_150_synthetic_histories(self):
        from random import Random
        random=Random(19697)
        start=NOW-timedelta(minutes=36)
        for i in range(150):
            prices=[]
            value=Decimal("8")
            for _ in range(6):
                value+=Decimal(random.randint(-10,10))/100
                prices.append(str(value))
            rows=[{"datetime":int((start+timedelta(minutes=5*n)).timestamp()*1000),
                   "close":p} for n,p in enumerate(prices)]
            # Additional scenarios include missing, duplicates, old, and insufficient.
            if i%11==0:rows=rows[:-1]
            if i%17==0:rows[3]["datetime"]=rows[2]["datetime"]
            if i%23==0:
                rows=[dict(x,datetime=x["datetime"]-3600000) for x in rows]
            try:
                reference=cross_signal(rows,NOW)
            except (LiveBlocked,KeyError,ValueError,TypeError):
                reference=None
            try:
                independent=_cross_signal(rows,NOW)
            except (WebullSignalError,KeyError,ValueError,TypeError):
                independent=None
            self.assertEqual(independent,reference,f"history {i} mismatch")
    def test_mirror_does_not_change_if_schwab_strategy_function_is_replaced(self):
        with patch("autonomous_selector.choose_entry",
                   side_effect=AssertionError("Shared Schwab engine was invoked")):
            _,signal=scan_webull_stock(BrokerFixture(),("F",),NOW)
        self.assertIsNotNone(signal)
        self.assertIn("Webull mirrored stock strategy",signal["reason"])
    def test_continuation_entry_matches_schwab_selection_independently(self):
        bid,ask=Decimal("5.18"),Decimal("5.19")
        quotes={"F":{"assetMainType":"EQUITY","quote":{
            "bidPrice":str(bid),"askPrice":str(ask),
            "quoteTime":int(NOW.timestamp()*1000),
            "totalVolume":"1000000","netPercentChange":"1.2"}}}
        local=_ranked_candidates(quotes,NOW,("F",))
        reference=ranked_candidates(quotes,NOW,universe=("F",))
        self.assertEqual(local,reference)
        candles=[{"datetime":int(datetime.fromisoformat(x["time"]).timestamp()*1000),
                  "close":x["close"]} for x in M5]
        actual=_choose_entry(local,lambda _:candles,NOW)
        expected=choose_entry(reference,lambda _:candles,NOW,True)
        self.assertEqual(actual.candle,expected.candle)
        self.assertEqual(actual.bid,expected.bid)
        self.assertEqual(actual.ask,expected.ask)
        self.assertEqual(actual.reason.replace("Webull mirrored stock strategy",
                        "shared stock strategy"),expected.reason)

if __name__=="__main__":unittest.main()
