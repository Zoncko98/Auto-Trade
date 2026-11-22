"""No broker POST or V1-journal mutation in Schwab V2 preflight."""
import json
from datetime import datetime,timezone,timedelta
from decimal import Decimal as D
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase,main
from unittest.mock import Mock,patch
from trader_v2.schwab_migration_probe import probe_schwab,run_once
from trader_v2.launch_gates import launch_status

NOW=datetime(2026,11,23,16,0,tzinfo=timezone.utc)

class SchwabSignedPreflight(TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state=Path(self.tmp.name)
        live=self.state/"live"
        live.mkdir(mode=0o700)
        self.journal=live/"orders.json"
        self.save_journal([])
        self.account={"securitiesAccount":{"currentBalances":{
              "unsettledCash":"0","pendingDeposits":"0"}}}
        self.broker=SimpleNamespace(get_quote=Mock(return_value={"SPY":{
            "quote":{"bidPrice":"510","askPrice":"510.01"}}}))
        for name,output in [
            ("live_worker.confirm_account",self.account),
            ("live_worker.current_broker_orders",[]),
            ("live_worker.market_is_normal",True),
            ("live_worker.result",{"SPY":{"quote":{}}}),
            ("live_order_safety.position_snapshot",({},D("0"))),
            ("live_order_safety.equity_value",D("100")),
            ("live_order_safety.verified_cash",D("100")),
            ("live_order_safety.quote_levels",(D("510"),D("510.01"))),
        ]:
            ctx=patch(name,return_value=output)
            mock=ctx.start()
            self.addCleanup(ctx.stop)
            setattr(self,name.split(".")[-1],mock)
    def save_journal(self,orders,*,halted=False):
        self.journal.write_text(json.dumps({
            "version":1,"halted":halted,"orders":orders}))
        self.journal.chmod(0o600)
    def run_probe(self,**kwargs):
        return probe_schwab(self.state,self.broker,"selected-hash",
             now=kwargs.get("now",NOW))

    def test_signed_preflight_reports_evidence_but_never_cuts_over(self):
        before=self.journal.read_bytes()
        r=self.run_probe()
        self.assertTrue(r["account_verified"])
        self.assertTrue(r["holdings_verified"])
        self.assertTrue(r["local_journal_matched"])
        self.assertTrue(r["signed_settled_cash_verified"])
        self.assertTrue(r["broker_session_verified"])
        self.assertTrue(r["broker_product_verified"])
        self.assertEqual(r["broker_open_order_count"],0)
        self.assertEqual(r["local_unresolved_count"],0)
        self.assertFalse(r["cutover_ready"])
        self.assertFalse(r["v2_live_order_authority"])
        self.assertEqual(self.journal.read_bytes(),before)
    def test_missing_settlement_fields_never_inferred_from_buying_power(self):
        self.account["securitiesAccount"]["currentBalances"]={"buyingPower":"10000"}
        r=self.run_probe()
        self.assertTrue(r["holdings_verified"])
        self.assertFalse(r["signed_settled_cash_verified"])
        self.assertEqual(r["first_blocker"],"SCHWAB_SETTLED_CASH_NOT_CERTIFIED")
        self.assertFalse(r["cutover_ready"])
    def test_market_closed_and_quote_unavailable_are_distinct(self):
        self.market_is_normal.return_value=False
        r=self.run_probe()
        self.assertFalse(r["broker_session_verified"])
        self.assertEqual(r["quote_timestamp_verified_symbols"],0)
        self.assertEqual(r["first_blocker"],"SCHWAB_MARKET_SESSION_NOT_OPEN_OR_UNVERIFIED")
        self.assertEqual(self.broker.get_quote.call_count,0)
    def test_broker_open_orders_require_reconciliation(self):
        self.current_broker_orders.return_value=[
            {"orderId":1,"status":"WORKING"}]
        r=self.run_probe()
        self.assertEqual(r["broker_open_order_count"],1)
        self.assertEqual(r["first_blocker"],"SCHWAB_OPEN_OR_UNRESOLVED_ORDERS")
        self.assertFalse(r["cutover_ready"])
    def test_local_terminal_order_requires_matching_signed_order(self):
        self.save_journal([{"order_id":"991","state":"FILLED","quantity":1}])
        r=self.run_probe()
        self.assertFalse(r["local_journal_matched"])
        self.assertEqual(r["first_blocker"],
            "SCHWAB_SIGNED_ORDER_HISTORY_OR_LOCAL_JOURNAL_UNVERIFIED")
    def test_signed_historical_fill_quantity_mismatch_blocks(self):
        self.save_journal([{"order_id":"991","state":"FILLED","quantity":2}])
        self.current_broker_orders.return_value=[
            {"orderId":991,"status":"FILLED","filledQuantity":1}]
        r=self.run_probe()
        self.assertFalse(r["local_journal_matched"])
        self.assertFalse(r["cutover_ready"])
    def test_pending_local_order_is_counted_not_cleared(self):
        self.save_journal([{"order_id":None,"state":"SUBMITTING"}])
        r=self.run_probe()
        self.assertEqual(r["local_unresolved_count"],1)
        self.assertEqual(r["first_blocker"],"SCHWAB_OPEN_OR_UNRESOLVED_ORDERS")
    def test_signed_observation_writes_private_redacted_report_only(self):
        old=self.journal.stat().st_mtime_ns
        r=run_once(self.state,self.broker,"selected-hash",now=NOW)
        self.assertFalse(r["v2_live_order_authority"])
        status=self.state/"v2"/"broker_migration"/"schwab.json"
        self.assertEqual(status.stat().st_mode&0o077,0)
        self.assertNotIn("selected-hash",status.read_text())
        self.assertEqual(self.journal.stat().st_mtime_ns,old)
        with patch("trader_v2.launch_gates.mapping") as risk:
            risk.return_value={"state":"SAVED_V1_NUMERIC_LIMITS_VALIDATED"}
            launch=launch_status(self.state,"schwab",now=NOW)
        gates={x["name"]:x["verified"] for x in launch["gates"]}
        self.assertTrue(gates["SIGNED_ACCOUNT"])
        self.assertTrue(gates["SIGNED_HOLDINGS"])
        self.assertTrue(gates["SIGNED_ORDER_HISTORY"])
        self.assertTrue(gates["SIGNED_MARKET_SESSION"])
        self.assertTrue(gates["SIGNED_SETTLED_FUNDING"])
        self.assertTrue(gates["EXECUTABLE_BROKER_QUOTE"])
        self.assertFalse(gates["V1_WORKER_STOPPED"])
        self.assertFalse(gates["EXCLUSIVE_WRITER_OWNERSHIP"])
        self.assertFalse(launch["live_v2_order_authority"])
        self.assertEqual(launch["state"],"BLOCKED")
    def test_expired_signed_report_is_not_trusted(self):
        run_once(self.state,self.broker,"selected-hash",now=NOW)
        row=launch_status(self.state,"schwab",now=NOW+timedelta(hours=2))
        self.assertFalse(row["signed_observation_fresh"])

if __name__=="__main__":main()
