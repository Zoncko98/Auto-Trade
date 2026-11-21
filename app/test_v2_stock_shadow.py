"""Stock V1 history -> read-only V2 controller/AI shadow end-to-end tests."""
from datetime import datetime,timedelta,timezone
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase,main
from unittest.mock import patch
import json,sqlite3

from trader_v2.stock_shadow import (
    capture_schwab_candles,run_once,status,SYMBOLS,StockShadowError)
from trader_v2.market_sources import schwab_market_quote
from autonomous_selector import UNIVERSE
import live_worker
import dashboard_server


class V2StockShadowTests(TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.now=datetime(2026,11,23,16,12,0,tzinfo=timezone.utc)
        self.symbol="F"

    def bars(self,prices=None):
        prices=prices or (10,10,10,10,10,11)
        start=datetime(2026,11,23,15,35,0,tzinfo=timezone.utc)
        return [{"datetime":int((start+timedelta(minutes=5*i)).timestamp()*1000),
                 "close":str(price)} for i,price in enumerate(prices)]

    def quote(self,symbol,now):
        doc={"schema":1,"source":"schwab_broker_quotes",
             "observed_at":now.isoformat(),
             "symbols":{symbol:{"quote_timestamp":(now-timedelta(seconds=2)).isoformat(),
                                "bid":"10.49","ask":"10.51","last":"10.50",
                                "tradable":True}}}
        return schwab_market_quote(doc,symbol,now=now)

    def capture(self,bars=None):
        return capture_schwab_candles(self.root,self.symbol,
                                     self.bars() if bars is None else bars,now=self.now)

    def test_universe_is_exactly_existing_schwab_eligible_universe(self):
        self.assertEqual(SYMBOLS,tuple(UNIVERSE))
        self.assertEqual(len(SYMBOLS),24)

    def test_real_5m_candles_produce_buy_shadow_without_order_submission(self):
        self.assertTrue(self.capture())
        invocations=[]
        def review(candidate,quote,now):
            invocations.append((candidate.side.value,quote.market_open))
            return {"state":"PASS","reason":"test only",
                    "model":"synthetic-model","latency_ms":150}
        doc=run_once(self.root,now=self.now,review=review,quote_loader=self.quote)
        item=next(r for r in doc["reports"] if r["symbol"]==self.symbol)
        self.assertEqual(item["state"],"CANDIDATE_SHADOW_ONLY")
        self.assertEqual(item["signal"],"BUY")
        self.assertEqual(item["ai_shadow"]["state"],"PASS")
        self.assertEqual(item["ai_shadow"]["latency_ms"],150)
        self.assertEqual(item["ai_shadow"]["model"],"synthetic-model")
        self.assertEqual(invocations,[("BUY",False)])
        self.assertFalse(item["broker_executable"])
        self.assertFalse(item["market_session_verified"])
        self.assertEqual(doc["live_orders_submitted"],0)
        self.assertEqual(doc["simulated_orders_submitted"],0)
        self.assertEqual(doc["broker_sdk_calls"],0)
        self.assertEqual(doc["signals_recorded"],1)
        self.assertFalse((self.root/"live"/"orders.json").exists())
        self.assertFalse((self.root/"schwab_token.json").exists())

    def test_duplicate_scan_is_persistently_idempotent_and_no_second_ai_call(self):
        self.capture()
        calls=[]
        def review(candidate,quote,now):
            calls.append(candidate.symbol)
            return {"state":"VETO","reason":"diagnostic"}
        first=run_once(self.root,now=self.now,review=review,quote_loader=self.quote)
        repeat=run_once(self.root,now=self.now,review=review,quote_loader=self.quote)
        self.assertEqual(calls,["F"])
        self.assertEqual(repeat["signals_recorded"],first["signals_recorded"])
        row=repeat["reports"][0]
        self.assertEqual(row["ai_shadow"]["state"],"VETO")
        self.assertTrue(row["ai_shadow"]["reused_persisted_review"])
        with sqlite3.connect(
            self.root/"v2"/"stock_shadow"/"signal_observations.sqlite3") as db:
            self.assertEqual(db.execute(
                "SELECT COUNT(*) FROM stock_signals").fetchone()[0],1)

    def test_no_signal_and_stale_candles_never_trigger_ai(self):
        self.capture(self.bars((10,10,10,10,10,10)))
        seen=[]
        report=run_once(self.root,now=self.now,
            review=lambda *a,**k:seen.append(True),quote_loader=self.quote)
        self.assertEqual(report["reports"][0]["state"],"NO_SIGNAL")
        report=run_once(self.root,now=self.now+timedelta(minutes=25),
            review=lambda *a,**k:seen.append(True),quote_loader=self.quote)
        self.assertEqual(report["reports"][0]["state"],"STALE_CANDLES")
        self.assertEqual(seen,[])

    def test_stale_or_missing_quote_blocks_even_genuine_buy(self):
        self.capture()
        doc=run_once(self.root,now=self.now,
            quote_loader=lambda sym,now:schwab_market_quote({
               "schema":1,"source":"schwab_broker_quotes",
               "observed_at":now.isoformat(),
               "symbols":{sym:{"quote_timestamp":(
                    now-timedelta(minutes=8)).isoformat(),
                   "bid":"10","ask":"10.1","last":"10","tradable":True}}},
                sym,now=now))
        row=doc["reports"][0]
        self.assertEqual(row["state"],"SOURCE_UNAVAILABLE")
        self.assertIn("EXCHANGE_QUOTE_STALE",row["reason"])
        self.assertEqual(doc["signals_recorded"],0)

    def test_gapped_bars_block_candidate(self):
        rows=self.bars()
        rows[3]["datetime"]+=300000
        with self.assertRaises(StockShadowError):
            self.capture(rows)  # duplicate closed times
        rows=self.bars()[:-1]
        rows[3]["datetime"]-=300000
        with self.assertRaises(StockShadowError):
            self.capture(rows)

    def test_invalid_input_cannot_replace_last_verified_history(self):
        self.capture()
        path=self.root/"v2"/"stock_shadow"/"candles"/"f.json"
        before=path.read_bytes()
        with self.assertRaises((ValueError,StockShadowError)):
            self.capture(self.bars((10,10,10,10,10,"NaN")))
        self.assertEqual(path.read_bytes(),before)
        self.assertEqual(path.stat().st_mode&0o077,0)

    def test_source_capture_failure_does_not_change_v1_candles(self):
        bars=self.bars()
        with patch.object(live_worker,"recent_candles",return_value=bars),patch(
            "trader_v2.stock_shadow.capture_schwab_candles",
            side_effect=OSError("synthetic storage failure")):
            result=live_worker._shadow_stock_history(object(),"F",self.now)
        self.assertIs(result,bars)

    def test_unstarted_status_is_readonly_and_no_fs_side_effect(self):
        report=status(self.root)
        self.assertEqual(report["state"],"NOT_STARTED")
        self.assertFalse(report["live_orders_authorized"])
        self.assertFalse((self.root/"v2").exists())

    def test_api_is_authenticated_and_never_creates_state(self):
        with patch.object(dashboard_server,"UNIFIED_APP",True),patch.object(
             dashboard_server,"STATE_DIR",self.root):
            h=dashboard_server.Handler.__new__(dashboard_server.Handler)
            h.path="/api/v2/stock-shadow"
            h._nonce=lambda:None
            h._json=lambda code,body,headers=None:(code,body)
            code,body=h.do_GET()
            self.assertEqual(code,401)
            self.assertFalse((self.root/"v2").exists())
            h._nonce=lambda:"synthetic-session"
            code,body=h.do_GET()
            self.assertEqual(code,200)
            self.assertFalse(body["live_orders_authorized"])

    def test_status_reports_heartbeat_and_private_non_live_journal(self):
        self.capture()
        result=run_once(self.root,now=self.now,quote_loader=self.quote,
            review=lambda *a,**k:{"state":"NOT_CONFIGURED"})
        root=self.root/"v2"/"stock_shadow"
        for name in ("stock.lock","status.json","signal_observations.sqlite3"):
            path=root/name
            self.assertTrue(path.is_file())
            self.assertEqual(path.stat().st_mode&0o077,0)
        self.assertEqual(result["universe_size"],24)


if __name__=="__main__":main()
