"""V2 3h/24h why-no-trade diagnostics and verified simulated fill regressions."""
from datetime import datetime,timedelta,timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase,main
import json,os,sqlite3

from trader_v2.scan_observability import capture_scan
from trader_v2.paper_activity import read_activity

class PaperActivityTests(TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)/"v2"/"fresh_paper"
        self.root.mkdir(mode=0o700,parents=True)
        self.now=datetime(2026,11,21,14,0,tzinfo=timezone.utc)

    def scan(self,symbol="BTCUSD",minutes_ago=10,state="NO_SIGNAL",
             reason=None,side=None,ai="NOT_INVOKED",equity="999.90"):
        return {"symbol":symbol,"simulated_only":True,"live_orders_submitted":0,
            "scan_state":state,"reason":reason or state,"signal":side,
            "at":(self.now-timedelta(minutes=minutes_ago)).isoformat(),
            "ai_shadow":{"state":ai},"virtual_equity":equity,
            "virtual_cash":equity}

    def make_fills(self,rows):
        path=self.root/"sim.sqlite3"
        with sqlite3.connect(path) as db:
            db.execute("""CREATE TABLE sim_orders(
                key TEXT PRIMARY KEY,account_id TEXT NOT NULL,
                intent_document TEXT NOT NULL,broker_order_id TEXT NOT NULL,
                quantity TEXT NOT NULL,price TEXT NOT NULL,
                fee TEXT NOT NULL,created_at TEXT NOT NULL)""")
            for i,(sym,minutes_ago,side,fee) in enumerate(rows):
                db.execute("INSERT INTO sim_orders VALUES(?,?,?,?,?,?,?,?)",
                  (str(i),"v2-paper-"+sym.lower(),json.dumps({"side":side,
                   "symbol":sym}),str(i),"1","100",fee,
                   (self.now-timedelta(minutes=minutes_ago)).isoformat()))
        path.chmod(0o600)

    def test_no_files_created_by_read_and_fill_state_not_fabricated(self):
        doc=read_activity(self.root,now=self.now)
        self.assertEqual(set(doc),{"BTCUSD","ETHUSD"})
        self.assertEqual(doc["BTCUSD"]["scans_state"],"NOT_RECORDED")
        self.assertEqual(doc["BTCUSD"]["fills_state"],"FILL_LEDGER_UNAVAILABLE")
        self.assertIsNone(doc["BTCUSD"]["simulated_fills"])
        self.assertFalse((self.root/"sim.sqlite3").exists())
        self.assertFalse((self.root/"paper_scan_history.sqlite3").exists())
        self.assertFalse(doc["BTCUSD"]["live_orders_authorized"])

    def test_last_three_hours_blockers_not_confused_with_fills(self):
        capture_scan(self.root,self.scan(minutes_ago=175,state="NO_SIGNAL",equity="1000"))
        capture_scan(self.root,self.scan(minutes_ago=65,state="BLOCKED",
            reason="ENTRY_DAILY_COUNT_LIMIT",side="BUY",ai="PASS",equity="999.90"))
        capture_scan(self.root,self.scan(minutes_ago=15,state="BLOCKED",
            reason="NO_LONG_HOLDING",side="SELL",ai="VETO",equity="999.90"))
        capture_scan(self.root,self.scan(symbol="ETHUSD",minutes_ago=10,
            state="BLOCKED",reason="ENTRY_DAILY_COUNT_LIMIT",
            side="BUY",ai="UNAVAILABLE",equity="999.85"))
        capture_scan(self.root,self.scan(minutes_ago=250,state="FILLED",side="BUY",
            ai="PASS",equity="998"))
        self.make_fills([("BTCUSD",240,"BUY","0.01"),("ETHUSD",10,"SELL","0.02")])
        doc=read_activity(self.root,now=self.now,hours=3)
        btc=doc["BTCUSD"]
        self.assertEqual(btc["scan_minutes"],3)
        self.assertEqual(btc["signal_minutes"],2)
        self.assertEqual(btc["entry_blocked_minutes"],1)
        self.assertEqual(btc["exit_blocked_minutes"],1)
        self.assertEqual(btc["rejection_reasons"],
                         {"ENTRY_DAILY_COUNT_LIMIT":1,"NO_LONG_HOLDING":1})
        self.assertEqual(btc["ai_shadow"]["PASS"],1)
        self.assertEqual(btc["ai_shadow"]["VETO"],1)
        self.assertEqual(btc["window_equity_change_usd"],"-0.10")
        self.assertEqual(btc["simulated_fills"],0)
        self.assertEqual(btc["fills_state"],"SIMULATED_LEDGER_VERIFIED")
        self.assertEqual(btc["simulated_fee_usd"],"0.00")
        self.assertEqual(doc["ETHUSD"]["simulated_sells"],1)
        self.assertEqual(doc["ETHUSD"]["simulated_fee_usd"],"0.02")
        self.assertFalse(doc["ETHUSD"]["live_orders_authorized"])
        daily=read_activity(self.root,now=self.now,hours=24)
        self.assertEqual(daily["BTCUSD"]["simulated_fills"],1)
        self.assertEqual(daily["BTCUSD"]["simulated_buys"],1)
        self.assertEqual(daily["BTCUSD"]["simulated_fee_usd"],"0.01")
        self.assertEqual(daily["BTCUSD"]["signal_minutes"],3)

    def test_duplicate_scan_minute_is_one_observation_not_fake_fills(self):
        capture_scan(self.root,self.scan(state="BLOCKED",
            reason="ENTRY_DAILY_COUNT_LIMIT",side="BUY",ai="PASS"))
        capture_scan(self.root,self.scan(state="NO_SIGNAL",minutes_ago=9,ai="NOT_INVOKED"))
        capture_scan(self.root,self.scan(state="BLOCKED",
            reason="ENTRY_DAILY_COUNT_LIMIT",side="BUY",ai="PASS",
            equity="999.80"))
        self.make_fills([])
        doc=read_activity(self.root,now=self.now)["BTCUSD"]
        self.assertEqual(doc["scan_minutes"],2)
        self.assertEqual(doc["entry_blocked_minutes"],1)
        self.assertEqual(doc["simulated_fills"],0)
        self.assertEqual(doc["simulated_fee_usd"],"0.00")

    def test_unverified_simulated_ledger_never_claims_zero_fills(self):
        self.make_fills([("BTCUSD",10,"BUY","0.01")])
        db=self.root/"sim.sqlite3"
        with sqlite3.connect(db) as connection:
            connection.execute("UPDATE sim_orders SET fee='NaN'")
        doc=read_activity(self.root,now=self.now)
        self.assertEqual(doc["BTCUSD"]["fills_state"],"FILL_LEDGER_UNVERIFIED")
        self.assertIsNone(doc["BTCUSD"]["simulated_fills"])
        self.assertIsNone(doc["ETHUSD"]["simulated_fills"])

    def test_public_ledger_and_symlink_not_trusted(self):
        self.make_fills([("BTCUSD",10,"BUY","0.01")])
        path=self.root/"sim.sqlite3"
        path.chmod(0o644)
        self.assertIsNone(read_activity(self.root,now=self.now)["BTCUSD"]["simulated_fills"])
        path.chmod(0o600)
        replacement=self.root/"sim2.sqlite3"
        path.rename(replacement)
        path.symlink_to(replacement)
        self.assertEqual(read_activity(self.root,now=self.now)["ETHUSD"]["fills_state"],
                         "FILL_LEDGER_UNAVAILABLE")

    def test_non_rolling_window_and_naive_time_rejected(self):
        with self.assertRaises(ValueError):
            read_activity(self.root,hours=72,now=self.now)
        with self.assertRaises(ValueError):
            read_activity(self.root,now=datetime(2026,11,21,14,0))

if __name__=="__main__":main()
