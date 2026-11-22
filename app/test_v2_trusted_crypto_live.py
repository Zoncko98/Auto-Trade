"""Production Robinhood V2 callbacks: mocked broker API, no live POST."""
from datetime import datetime,timezone,timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
import sqlite3
from decimal import Decimal as D
from trader_v2.trusted_crypto_live import (
    closed_crypto_bars,merged_bot_inventory,
    verified_robinhood_parity,signed_robinhood_grant,scanner_factory,
    signed_v1_worker_stopped)
from trader_v2.live_executor import production_callbacks,account_cycle

class TrustedCryptoRuntimeTests(TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.account="testaccount"

    def test_real_production_callbacks_never_run_under_v1_owner(self):
        grant,scanner,parity=production_callbacks(self.root)
        with patch("trader_v2.live_executor._selected",return_value=self.account),patch(
            "trader_v2.live_executor.launch_status") as signed,patch(
            "trader_v2.trusted_crypto_live.RobinhoodCryptoTradingAdapter",
            create=True) as adapter:
            output=account_cycle(self.root,"robinhood_crypto",
                grant_provider=grant,scanner_factory=scanner,
                strategy_parity=parity)
        self.assertEqual(output["reason"],"V1_RETAINS_ORDER_WRITER")
        signed.assert_not_called()
        adapter.assert_not_called()
        self.assertFalse((self.root/"v2/events.sqlite3").exists())

    def test_explicit_broker_scope_rejects_unwired_providers(self):
        with self.assertRaises(ValueError):
            scanner_factory(self.root,"webull",self.account,None)

    def test_missing_v2_receipts_never_create_false_bot_inventory(self):
        with patch("trader_v2.trusted_crypto_live.v1_inventory",return_value={}):
            with self.assertRaises(Exception):
                merged_bot_inventory(self.root,self.account)
        self.assertFalse((self.root/"v2/events.sqlite3").exists())

    def test_live_parity_never_implicitly_arms_unconfigured_account(self):
        self.assertFalse(verified_robinhood_parity(self.root,"robinhood_crypto",self.account))
        self.assertIsNone(signed_robinhood_grant(self.root,"robinhood_crypto",self.account))
        self.assertFalse((self.root/"v2/events.sqlite3").exists())

    def test_candles_are_genuine_existing_closed_minute_observations(self):
        root=self.root/"v2/fresh_paper"
        root.mkdir(parents=True,mode=0o700)
        path=root/"tick_bars.sqlite3"
        now=datetime(2026,11,22,17,0,tzinfo=timezone.utc)
        with sqlite3.connect(path) as db:
            db.execute("CREATE TABLE tick_bars(symbol TEXT,minute_start INTEGER,quote_at TEXT,close TEXT)")
            start=int(now.timestamp())-900
            for i in range(16):
                db.execute("INSERT INTO tick_bars VALUES(?,?,?,?)",
                    ("BTCUSD",start+i*60,now.isoformat(),str(10+i)))
        path.chmod(0o600)
        candles=closed_crypto_bars(self.root,"BTC-USD",now=now)
        self.assertEqual(len(candles),15)
        self.assertEqual(candles[-1].symbol,"BTC-USD")
        self.assertEqual(candles[-1].close,D("24"))
        self.assertTrue(all(c.closed for c in candles))
        with self.assertRaises(ValueError):
            closed_crypto_bars(self.root,"SOL-USD",now=now)

    def test_v1_worker_proc_scan_not_operator_flag(self):
        with patch("pathlib.Path.is_dir",return_value=False):
            self.assertFalse(signed_v1_worker_stopped())

if __name__=="__main__":
    __import__("unittest").main()
