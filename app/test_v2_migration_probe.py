"""Broker-signed V2 migration probe: offline acceptance and no-order tests."""
from __future__ import annotations
from datetime import datetime,timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest
from trader_v2.migration_probe import _probe,run_once
from trader_v2.readonly_adapters import private_json

class FakeSignedClient:
    def __init__(self,now):
        self.now=now;self.calls=[];self.orders_list=[]
        self.accounts=[{"account_number":"acc1","status":"active",
            "is_api_tradable":True,"buying_power_currency":"USD",
            "buying_power":"20"}]
        self.holdings=[{"asset_code":"BTC","total_quantity":"0.2"}]
        self.pairs=[{"symbol":"BTC-USD","is_api_tradable":True,
            "min_order_amount":"1","asset_increment":"0.001","max_order_size":"10"}]
        self.quotes={"BTC-USD":{"results":[{"symbol":"BTC-USD",
            "quote_timestamp":now.isoformat(),"last":"100","bid":"99.9","ask":"100.1"}]}}
    def list_accounts(self):
        self.calls.append("list_accounts");return self.accounts
    def positions(self,account):
        self.calls.append("positions");return self.holdings
    def orders(self,account):
        self.calls.append("orders");return self.orders_list
    def trading_pairs(self):
        self.calls.append("trading_pairs");return self.pairs
    def quote(self,symbol):
        self.calls.append("quote");return self.quotes[symbol]
    def submit_order(self,*a,**k):
        raise AssertionError("PROBE MUST NEVER SUBMIT")
    def cancel_order(self,*a,**k):
        raise AssertionError("PROBE MUST NEVER CANCEL")

class ProbeTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.now=datetime.now(timezone.utc).replace(microsecond=0)
        self.client=FakeSignedClient(self.now)
        self.policy={"enabled":True,"account":"acc1"}

    def report(self):
        return _probe(self.root,self.client,self.policy,now=self.now)

    def test_signed_reconciliation_does_not_claim_cutover(self):
        report=self.report()
        self.assertTrue(report["account_verified"])
        self.assertTrue(report["holdings_verified"])
        self.assertTrue(report["broker_history_verified"])
        self.assertTrue(report["local_journal_matched"])
        self.assertEqual(report["broker_open_order_count"],0)
        self.assertEqual(report["quote_timestamp_verified_symbols"],1)
        self.assertFalse(report["cutover_ready"])
        self.assertFalse(report["settled_cash_verified"])
        self.assertFalse(report["broker_session_verified"])
        self.assertEqual(report["first_blocker"],"V1_WRITER_HANDOFF_AND_BROKER_SESSION_REQUIRED")

    def test_policy_disarmed_never_calls_broker(self):
        self.policy["enabled"]=False
        result=self.report()
        self.assertEqual(result["first_blocker"],"V1_ACCOUNT_OPERATOR_PERMISSION_NOT_ARMED")
        self.assertEqual(self.client.calls,[])

    def test_broker_account_auth_missing_fails_closed(self):
        self.client.accounts=[]
        self.assertEqual(self.report()["first_blocker"],
                         "SIGNED_ACCOUNT_UNAVAILABLE_OR_INELIGIBLE")

    def test_high_precision_signed_holdings_are_observed_not_discarded(self):
        self.client.holdings=[{"asset_code":"BTC","total_quantity":"1.123456789012345678"},
                              {"asset_code":"ETH","total_quantity":"0E-18"}]
        report=self.report()
        self.assertTrue(report["holdings_verified"])
        self.assertEqual(report["holdings_rows_observed"],2)
        self.assertEqual(report["first_blocker"],
            "V1_WRITER_HANDOFF_AND_BROKER_SESSION_REQUIRED")

    def test_signed_positions_missing_fails_closed(self):
        self.client.holdings=None
        result=self.report()
        self.assertEqual(result["first_blocker"],"SIGNED_HOLDINGS_UNVERIFIED")
        self.assertEqual(result["holdings_failure_category"],"SIGNED_POSITIONS_NOT_LIST")

    def test_signed_holdings_transport_failure_reports_only_safe_exception_class(self):
        self.client.positions=lambda account:(_ for _ in ()).throw(TimeoutError("SECRET_TOKEN"))
        report=self.report()
        self.assertEqual(report["first_blocker"],"SIGNED_HOLDINGS_UNVERIFIED")
        self.assertEqual(report["holdings_failure_category"],"SIGNED_POSITIONS_REQUEST_FAILED")
        self.assertEqual(report["holdings_error_class"],"TimeoutError")
        self.assertNotIn("SECRET_TOKEN",__import__("json").dumps(report))

    def test_active_broker_order_blocks(self):
        self.client.orders_list=[{"client_order_id":"abc","state":"open"}]
        result=self.report()
        self.assertEqual(result["broker_open_order_count"],1)
        self.assertEqual(result["first_blocker"],
                         "OPEN_BROKER_OR_LOCAL_ORDER_RECONCILIATION_REQUIRED")

    def test_duplicate_provider_order_id_does_not_evict_legacy_lock(self):
        self.client.orders_list=[{"client_order_id":"abc","state":"filled"},
                                  {"client_order_id":"abc","state":"filled"}]
        self.assertEqual(self.report()["first_blocker"],
                         "SIGNED_BROKER_ORDER_HISTORY_UNVERIFIED")

    def test_local_unresolved_order_not_in_signed_history_blocks(self):
        from robinhood_order_journal import OrderJournal
        j=OrderJournal(self.root)
        j.record_intent("acc1","missing","BTC-USD","1","100")
        result=self.report()
        self.assertEqual(result["local_unresolved_count"],1)
        self.assertEqual(result["first_blocker"],
                         "LOCAL_INTENT_NOT_FOUND_IN_SIGNED_BROKER_HISTORY")

    def test_local_unresolved_even_if_signed_broker_present_blocks(self):
        from robinhood_order_journal import OrderJournal
        j=OrderJournal(self.root)
        j.record_intent("acc1","open123","BTC-USD","1","100")
        self.client.orders_list=[{"client_order_id":"open123","state":"open"}]
        result=self.report()
        self.assertEqual(result["first_blocker"],
                         "OPEN_BROKER_OR_LOCAL_ORDER_RECONCILIATION_REQUIRED")

    def test_local_historical_fill_requires_actual_signed_order(self):
        from robinhood_order_journal import OrderJournal
        journal=OrderJournal(self.root)
        journal.record_intent("acc1","my-bot-1","BTC-USD","1","100")
        journal.reconcile("acc1",[{
            "client_order_id":"my-bot-1","state":"filled",
            "filled_asset_quantity":"1","average_price":"100",
            "fee_charged":"0.25","updated_at":self.now.isoformat()}])
        missing=self.report()
        self.assertEqual(missing["first_blocker"],
            "HISTORICAL_V1_FILL_MISSING_FROM_SIGNED_BROKER")
        self.client.orders_list=[{
            "client_order_id":"my-bot-1","state":"filled",
            "filled_asset_quantity":"1","average_price":"100",
            "fee_charged":"0.25"}]
        verified=self.report()
        self.assertEqual(verified["first_blocker"],
            "V1_WRITER_HANDOFF_AND_BROKER_SESSION_REQUIRED")
        self.assertTrue(verified["local_journal_matched"])

    def test_historical_broker_fill_quantity_mismatch_blocks(self):
        from robinhood_order_journal import OrderJournal
        journal=OrderJournal(self.root)
        journal.record_intent("acc1","my-bot-2","BTC-USD","1","100")
        journal.reconcile("acc1",[{
            "client_order_id":"my-bot-2","state":"filled",
            "filled_asset_quantity":"1","average_price":"100",
            "fee_charged":"0","updated_at":self.now.isoformat()}])
        self.client.orders_list=[{
            "client_order_id":"my-bot-2","state":"filled",
            "filled_asset_quantity":"0.5","average_price":"100",
            "fee_charged":"0"}]
        self.assertEqual(self.report()["first_blocker"],
            "HISTORICAL_V1_FILL_QTY_OR_PRICE_MISMATCH")

    def test_missing_quote_timestamp_blocks_live_cutover(self):
        self.client.quotes["BTC-USD"]["results"][0].pop("quote_timestamp")
        result=self.report()
        self.assertEqual(result["quote_timestamp_verified_symbols"],0)
        self.assertEqual(result["first_blocker"],
                         "BROKER_QUOTE_TIMESTAMP_OR_LAST_TRADE_UNVERIFIED")

    def test_invalid_increment_blocks(self):
        self.client.pairs[0]["asset_increment"]="NaN"
        self.assertEqual(self.report()["first_blocker"],
                         "SIGNED_PAIR_INCREMENT_OR_MINIMUM_UNVERIFIED")

    def test_status_writes_private_redacted_json_only(self):
        policy_file=self.root/"robinhood"/"risk_policy.json"
        policy_file.parent.mkdir(parents=True,mode=0o700)
        policy_file.write_text(json.dumps({"enabled":True,"account":"acc1"}))
        policy_file.chmod(0o600)
        result=run_once(self.root,self.client,now=self.now)
        file=self.root/"v2"/"broker_migration"/"robinhood_crypto.json"
        self.assertTrue(file.is_file())
        self.assertEqual(file.stat().st_mode&0o077,0)
        text=file.read_text()
        self.assertNotIn("acc1",text)
        self.assertNotIn("private_key",text)
        self.assertFalse(result["v2_live_order_authority"])
        self.assertEqual(private_json(file)["first_blocker"],
                         "V1_WRITER_HANDOFF_AND_BROKER_SESSION_REQUIRED")

if __name__=="__main__":unittest.main()
