"""Supervised read-only Webull broker readiness lifecycle, no broker posts."""
from datetime import datetime,timezone,timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase,main
import json,sqlite3

from trader_v2.webull_probe_runner import run_once,result_status
from test_v2_webull_migration_probe import SignedWebull

class AutoWebullProbeTests(TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        path=self.root/"webull"
        path.mkdir(mode=0o700)
        policy={"enabled":True,"stock_account":"selected-acc",
                "crypto_account":"","trade_stocks":True,"trade_crypto":False}
        dest=path/"trading_policy.json"
        dest.write_text(json.dumps(policy))
        dest.chmod(0o600)
        journal=path/"orders.sqlite3"
        with sqlite3.connect(journal) as db:
            db.execute("""CREATE TABLE orders (
               client_id TEXT,account TEXT,status TEXT,quantity TEXT,
               filled_qty TEXT,filled_price TEXT,fee TEXT,broker_id TEXT,
               side TEXT,asset TEXT,created_at TEXT,symbol TEXT DEFAULT 'AAPL')""")
        journal.chmod(0o600)
        self.now=datetime.now(timezone.utc).replace(microsecond=0)

    def test_supervised_signed_get_status_is_private_bounded_and_not_crossover(self):
        signed=SignedWebull()
        first=run_once(self.root,signed_broker=signed,now=self.now)
        self.assertEqual(first["first_blocker"],
          "WEBULL_POSITIONS_SETTLEMENT_AND_SINGLE_WRITER_HANDOFF_REQUIRED")
        self.assertTrue(first["broker_account_verified"])
        self.assertTrue(first["broker_open_orders_verified"])
        self.assertFalse(first["settled_cash_verified"])
        self.assertFalse(first["v1_writer_handoff_verified"])
        self.assertFalse(first["live_order_authority"])
        dest=self.root/"v2/broker_migration/webull.json"
        self.assertEqual(dest.stat().st_mode&0o077,0)
        self.assertNotIn("selected-acc",dest.read_text())
        snapshot=result_status(self.root,now=self.now)
        self.assertEqual(snapshot["state"],"FRESH_READ_ONLY_PREFLIGHT")
        self.assertFalse(snapshot["live_order_authority"])
        old_calls=len(signed.reads)
        cached=run_once(self.root,now=self.now)
        self.assertFalse(cached["live_order_authority"])
        self.assertEqual(len(signed.reads),old_calls)

    def test_expired_observation_never_claims_current_authorization(self):
        signed=SignedWebull()
        run_once(self.root,signed_broker=signed,now=self.now)
        stale=result_status(self.root,now=self.now+timedelta(minutes=21))
        self.assertEqual(stale["state"],"NOT_YET_VERIFIED_OR_STALE")
        self.assertFalse(stale["cutover_ready"])
        self.assertFalse(stale["live_order_authority"])
        self.assertEqual(stale["first_blocker"],"SIGNED_WEBULL_PREFLIGHT_REQUIRED")

if __name__=="__main__":
    main()
