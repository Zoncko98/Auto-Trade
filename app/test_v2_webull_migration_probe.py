from decimal import Decimal as D
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, main
from unittest.mock import patch
from datetime import datetime,timezone
import sqlite3

from trader_v2.webull_migration_probe import probe_webull


class SignedWebull:
    def __init__(self,open_orders=None,balance=None,positions=None):
        self.opens=open_orders if open_orders is not None else []
        self.bal=balance or {
            "total_cash_balance":"100","total_net_liquidation_value":"100",
            "total_market_value":"0"}
        self.pos=positions if positions is not None else []
        self.reads=[]
    def verify_account(self,account):
        self.reads.append("account")
        return {"account_id":account}
    def balance(self,account):
        self.reads.append("balance")
        return self.bal
    def positions(self,account):
        self.reads.append("positions")
        return self.pos
    def open_orders(self,account):
        self.reads.append("open_orders")
        return self.opens
    def quote(self,symbol,asset):
        self.reads.append("quote")
        return {"symbol":symbol,"quote_time":"2026-11-23T16:00:00+00:00",
            "bid":"100","ask":"100.1","last":"100.05"}
    def order_detail(self,account,client_id):
        self.reads.append("order_detail")
        return {"orders":[{
            "client_order_id":client_id,"status":"FILLED",
            "order_id":"broker-a","filled_quantity":"2",
            "filled_price":"10","fee_charged":"0.01",
        }]}


class WebullPreflightTests(TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.account="webull-account"
        self.policy={
            "enabled":True,"stock_account":self.account,
            "crypto_account":"","trade_stocks":True,"trade_crypto":False
        }
    def journal(self,rows=()):
        p=self.root/"webull/orders.sqlite3"
        p.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
        with sqlite3.connect(p) as db:
            db.execute("""CREATE TABLE orders(
              client_id TEXT, account TEXT, status TEXT, quantity TEXT,
              filled_qty TEXT, filled_price TEXT, fee TEXT, broker_id TEXT,
              side TEXT, asset TEXT, created_at TEXT, symbol TEXT DEFAULT 'AAPL')""")
            for record in rows:
                db.execute("INSERT INTO orders(client_id,account,status,quantity,filled_qty,filled_price,fee,broker_id,side,asset,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                           record)
        p.chmod(0o600)
        return p
    def record(self,status="FILLED"):
        return ("a"*32,self.account,status,"2","2","10","0.01",
                "broker-a","BUY","EQUITY","2026-11-21T14:30:00+00:00")
    def test_no_policy_no_signed_apis(self):
        b=SignedWebull()
        report=probe_webull(self.root,b,{"enabled":False})
        self.assertEqual(report["first_blocker"],"SELECT_ONE_WEBULL_ACCOUNT_FOR_MIGRATION")
        self.assertFalse(report["cutover_ready"])
        self.assertEqual(b.reads,[])
    def test_disarmed_selected_account_still_runs_read_only_audit(self):
        self.journal([])
        b=SignedWebull()
        policy={**self.policy,"enabled":False}
        report=probe_webull(self.root,b,policy)
        self.assertTrue(report["broker_account_verified"])
        self.assertTrue(report["signed_historical_fills_verified"])
        self.assertEqual(report["first_blocker"],"WEBULL_OPERATOR_NOT_ARMED")
        self.assertFalse(report["v1_operator_armed"])
        self.assertFalse(report["live_order_authority"])
        self.assertIn("open_orders",b.reads)

    def test_broker_history_over_quota_budget_is_not_queried(self):
        self.journal([
          ("abc"+str(i).zfill(29), self.account, "FILLED","2","2","10","0.01",
           "broker-a","BUY","EQUITY","2026-11-21T14:30:00+00:00")
          for i in range(9)
        ])
        b=SignedWebull()
        report=probe_webull(self.root,b,self.policy)
        self.assertEqual(report["first_blocker"],
                         "WEBULL_HISTORICAL_SIGNED_BATCH_REQUIRED")
        self.assertNotIn("order_detail",b.reads)
        self.assertFalse(report["cutover_ready"])

    def test_refuses_ambiguous_two_account_selection(self):
        b=SignedWebull()
        policy={**self.policy,"trade_crypto":True,"crypto_account":"different"}
        r=probe_webull(self.root,b,policy)
        self.assertEqual(r["first_blocker"],"SELECT_ONE_WEBULL_ACCOUNT_FOR_MIGRATION")
    def test_signed_balance_unknown_never_proves_funding(self):
        b=SignedWebull(balance={"total_cash_balance":"110",
            "total_net_liquidation_value":"100","total_market_value":"0"})
        self.assertEqual(probe_webull(self.root,b,self.policy)["first_blocker"],
                         "WEBULL_SIGNED_CASH_OR_EQUITY_UNVERIFIED")
    def test_broker_open_orders_block_after_signed_checks(self):
        b=SignedWebull(open_orders=[{"order_id":"open"}])
        report=probe_webull(self.root,b,self.policy)
        self.assertEqual(report["first_blocker"],
                         "WEBULL_BROKER_OPEN_ORDERS_REQUIRE_RECONCILIATION")
        self.assertEqual(report["broker_open_order_count"],1)
    def test_missing_journal_does_not_create_it(self):
        b=SignedWebull()
        report=probe_webull(self.root,b,self.policy)
        self.assertEqual(report["first_blocker"],"LOCAL_WEBULL_JOURNAL_UNAVAILABLE")
        self.assertFalse((self.root/"webull/orders.sqlite3").exists())
    def test_local_partial_intent_requires_reconciliation(self):
        self.journal([self.record("PARTIAL_FILLED")])
        b=SignedWebull()
        report=probe_webull(self.root,b,self.policy)
        self.assertEqual(report["local_unresolved_count"],1)
        self.assertEqual(report["first_blocker"],"WEBULL_LOCAL_UNRESOLVED_ORDERS")
    def test_local_terminal_signed_fill_verified_still_no_cutover(self):
        path=self.journal([self.record()])
        mtime=path.stat().st_mtime_ns
        b=SignedWebull(positions=[{"instrument_type":"EQUITY","symbol":"AAPL","quantity":"2"}])
        report=probe_webull(self.root,b,self.policy)
        self.assertTrue(report["broker_positions_verified"])
        self.assertTrue(report["broker_position_inventory_reconciled"])
        self.assertEqual(report["signed_historical_fill_count"],1)
        self.assertTrue(report["signed_historical_fills_verified"])
        self.assertFalse(report["cutover_ready"])
        self.assertFalse(report["settled_cash_verified"])
        self.assertFalse(report["v1_writer_handoff_verified"])
        self.assertEqual(report["live_v2_orders_submitted"],0)
        self.assertEqual(path.stat().st_mtime_ns,mtime)
    def test_signed_settled_cash_is_verified_but_not_handoff(self):
        self.journal([])
        bal={"total_asset_currency":"USD","total_cash_balance":"100",
             "total_net_liquidation_value":"100","total_market_value":"0",
             "account_currency_assets":[{"currency":"USD","cash_balance":"100",
                 "settled_cash":"50","held_amount":"5","frozen_amount":"0"}]}
        report=probe_webull(self.root,SignedWebull(balance=bal),self.policy)
        self.assertTrue(report["settled_cash_verified"])
        self.assertFalse(report["cutover_ready"])
        self.assertEqual(report["first_blocker"],
                         "WEBULL_SESSION_AND_SINGLE_WRITER_HANDOFF_REQUIRED")

    def test_structural_signed_positions_do_not_prove_funding_or_handoff(self):
        self.journal([])
        b=SignedWebull(positions=[{"instrument_type":"EQUITY","symbol":"AAPL","quantity":"5"}])
        report=probe_webull(self.root,b,self.policy)
        self.assertTrue(report["broker_positions_verified"])
        self.assertTrue(report["broker_position_inventory_reconciled"])
        self.assertEqual(report["broker_external_position_symbols"],1)
        self.assertFalse(report["settled_cash_verified"])
        self.assertFalse(report["cutover_ready"])

    def test_malformed_signed_stock_position_fails_closed(self):
        self.journal([])
        b=SignedWebull(positions=[{"instrument_type":"EQUITY","symbol":"AAPL","quantity":"1.5"}])
        report=probe_webull(self.root,b,self.policy)
        self.assertEqual(report["first_blocker"],"WEBULL_FRACTIONAL_POSITION_UNSUPPORTED")
        self.assertFalse(report["broker_position_inventory_reconciled"])

    def test_signed_holdings_below_bot_inventory_fails_closed(self):
        self.journal([self.record()])
        b=SignedWebull(positions=[{"instrument_type":"EQUITY","symbol":"AAPL","quantity":"1"}])
        report=probe_webull(self.root,b,self.policy)
        self.assertEqual(report["first_blocker"],"WEBULL_BOT_INVENTORY_EXCEEDS_SIGNED_HOLDINGS")
        self.assertFalse(report["broker_position_inventory_reconciled"])
        self.assertFalse(report["cutover_ready"])

    def test_signed_stock_permission_and_quote_are_independent_gates(self):
        self.journal([])
        b=SignedWebull()
        now=datetime(2026,11,23,16,0,2,tzinfo=timezone.utc)
        with patch("webull_worker._can_trade_account",return_value=True),patch(
             "webull_signals.core_stock_session",return_value=True):
            report=probe_webull(self.root,b,self.policy,now=now)
        self.assertTrue(report["broker_product_verified"])
        self.assertEqual(report["broker_quote_timestamp_verified_symbols"],1)
        self.assertTrue(report["core_stock_session_observed"])
        self.assertFalse(report["cutover_ready"])
        self.assertIn("quote",b.reads)

    def test_quote_without_last_never_proves_executable_signed_price(self):
        self.journal([])
        b=SignedWebull()
        def no_last(sym,asset):
            raw=SignedWebull.quote(b,sym,asset)
            raw.pop("last")
            return raw
        b.quote=no_last
        now=datetime(2026,11,23,16,0,2,tzinfo=timezone.utc)
        with patch("webull_worker._can_trade_account",return_value=True),patch(
             "webull_signals.core_stock_session",return_value=True):
            report=probe_webull(self.root,b,self.policy,now=now)
        self.assertTrue(report["broker_product_verified"])
        self.assertEqual(report["broker_quote_timestamp_verified_symbols"],0)
        self.assertFalse(report["cutover_ready"])

    def test_market_window_closed_skips_market_quote_but_does_not_forge_permission(self):
        self.journal([])
        b=SignedWebull()
        with patch("webull_worker._can_trade_account",return_value=True),patch(
             "webull_signals.core_stock_session",return_value=False):
            report=probe_webull(self.root,b,self.policy)
        self.assertTrue(report["broker_product_verified"])
        self.assertFalse(report["core_stock_session_observed"])
        self.assertEqual(report["broker_quote_timestamp_verified_symbols"],0)
        self.assertNotIn("quote",b.reads)

    def test_webull_invalid_signed_fill_economics_fail_closed(self):
        self.journal([self.record()])
        b=SignedWebull()
        def wrong(account,client):
            return {"orders":[{"client_order_id":client,"status":"FILLED",
                "order_id":"broker-a","filled_quantity":"2",
                "filled_price":"11","fee_charged":"0.01"}]}
        b.order_detail=wrong
        report=probe_webull(self.root,b,self.policy)
        self.assertEqual(report["first_blocker"],
                         "WEBULL_HISTORICAL_FILL_ECONOMICS_MISMATCH")


if __name__=="__main__":
    main()
