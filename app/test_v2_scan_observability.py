"""Durable, read-only, simulated-only V2 paper scan scorecard regressions."""
from datetime import datetime,timedelta,timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase,main
import json,os,sqlite3
from trader_v2.scan_observability import capture_scan,read_scorecards

class PaperScanScorecardTests(TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/"v2"/"fresh_paper"
        self.root.mkdir(parents=True,mode=0o700)
        self.now=datetime(2026,11,21,9,13,tzinfo=timezone.utc)

    def report(self,*,symbol="BTCUSD",state="NO_SIGNAL",at=None,
               ai="NOT_INVOKED",signal=None,equity="1000"):
        return {"symbol":symbol,"simulated_only":True,
            "live_orders_submitted":0,"scan_state":state,
            "reason":state,"at":(at or self.now).isoformat(),
            "signal":signal,"virtual_cash":equity,
            "virtual_equity":equity,
            "ai_shadow":{"state":ai,"changed_order_authority":False}}

    def test_no_source_file_is_created_by_status_read(self):
        cards=read_scorecards(self.root,now=self.now)
        self.assertEqual(cards["BTCUSD"]["state"],"NOT_RECORDED")
        self.assertEqual(cards["ETHUSD"]["sample_minutes"],0)
        self.assertFalse((self.root/"paper_scan_history.sqlite3").exists())

    def test_first_scan_creates_private_event_store(self):
        capture_scan(self.root,self.report())
        path=self.root/"paper_scan_history.sqlite3"
        self.assertTrue(path.is_file())
        self.assertEqual(path.stat().st_mode&0o077,0)
        cards=read_scorecards(self.root,now=self.now)
        self.assertEqual(cards["BTCUSD"]["sample_minutes"],1)
        self.assertEqual(cards["BTCUSD"]["no_signal_minutes"],1)
        self.assertEqual(cards["BTCUSD"]["synthetic_pnl_usd"],"0.00")
        self.assertEqual(cards["ETHUSD"]["state"],"NOT_RECORDED")

    def test_repeat_same_minute_is_idempotent_for_signal_and_fill_counts(self):
        capture_scan(self.root,self.report(state="FILLED",signal="BUY",
                            ai="VETO",equity="996.50"))
        capture_scan(self.root,self.report(state="NO_SIGNAL",ai="NOT_INVOKED",
                          at=self.now+timedelta(seconds=12),equity="995.50"))
        card=read_scorecards(self.root,now=self.now+timedelta(seconds=14))["BTCUSD"]
        self.assertEqual(card["sample_minutes"],1)
        self.assertEqual(card["signal_minutes"],1)
        self.assertEqual(card["fill_minutes"],1)
        self.assertEqual(card["ai_shadow"]["VETO"],1)
        self.assertEqual(card["synthetic_pnl_usd"],"-4.50")
        with sqlite3.connect(self.root/"paper_scan_history.sqlite3") as db:
            self.assertEqual(db.execute("SELECT attempts FROM paper_scans").fetchone()[0],2)

    def test_different_minutes_and_account_isolation(self):
        capture_scan(self.root,self.report())
        capture_scan(self.root,self.report(symbol="ETHUSD",state="DATA_UNAVAILABLE"))
        capture_scan(self.root,self.report(state="FILLED",signal="BUY",ai="PASS",
            at=self.now+timedelta(minutes=1),equity="990"))
        cards=read_scorecards(self.root,now=self.now+timedelta(minutes=2))
        self.assertEqual(cards["BTCUSD"]["sample_minutes"],2)
        self.assertEqual(cards["BTCUSD"]["fill_minutes"],1)
        self.assertEqual(cards["BTCUSD"]["ai_shadow"]["PASS"],1)
        self.assertEqual(cards["ETHUSD"]["sample_minutes"],1)
        self.assertEqual(cards["ETHUSD"]["data_error_minutes"],1)
        self.assertEqual(cards["BTCUSD"]["synthetic_pnl_usd"],"-10.00")
        self.assertEqual(cards["BTCUSD"]["max_paper_drawdown_pct"],"1.00")

    def test_unsafe_access_and_live_broker_claims_refused(self):
        with self.assertRaises(ValueError):
            capture_scan(self.root,{**self.report(),"live_orders_submitted":1})
        with self.assertRaises(ValueError):
            capture_scan(self.root,{**self.report(),"simulated_only":False})
        with self.assertRaises(ValueError):
            capture_scan(self.root,{**self.report(),"virtual_equity":"NaN"})
        self.assertFalse((self.root/"paper_scan_history.sqlite3").exists())
        self.root.chmod(0o777)
        with self.assertRaises(PermissionError):
            capture_scan(self.root,self.report())
        self.root.chmod(0o700)

    def test_history_is_strictly_time_bounded(self):
        capture_scan(self.root,self.report(at=self.now-timedelta(days=8)))
        cards=read_scorecards(self.root,now=self.now,hours=24)
        self.assertEqual(cards["BTCUSD"]["state"],"NOT_RECORDED")
        cards7=read_scorecards(self.root,now=self.now,hours=168)
        self.assertEqual(cards7["BTCUSD"]["sample_minutes"],0)
        with self.assertRaises(ValueError):
            read_scorecards(self.root,now=self.now,hours=999)

    def test_bad_or_public_db_not_read_and_symlink_refused(self):
        target=self.root/"source.txt"
        target.write_text("sensitive fixture")
        (self.root/"paper_scan_history.sqlite3").symlink_to(target)
        self.assertEqual(read_scorecards(self.root)["BTCUSD"]["state"],"NOT_RECORDED")
        with self.assertRaises(PermissionError):
            capture_scan(self.root,self.report())
        self.assertEqual(target.read_text(),"sensitive fixture")

if __name__=="__main__":main()
