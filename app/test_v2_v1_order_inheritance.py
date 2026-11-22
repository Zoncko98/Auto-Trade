"""Signed V1 journal inheritance refuses resets/unsafe broker records."""
import json,sqlite3
from datetime import datetime,timezone,timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
from trader_v2.v1_order_inheritance import (
    inherit_records,read_inherited,V1InheritanceUnavailable
)

NOW=datetime(2026,11,23,16,0,tzinfo=timezone.utc)

class PureV1Counts(TestCase):
    def test_robinhood_signed_exit_symbol_cooldown_and_prior_counts(self):
        rows=[
          {"account":"rh1","client_order_id":"a","side":"buy","status":"filled",
           "symbol":"BTC-USD","created_at":(NOW-timedelta(hours=1)).isoformat()},
          {"account":"rh1","client_order_id":"b","side":"sell","status":"filled",
           "symbol":"BTC-USD","created_at":(NOW-timedelta(minutes=8)).isoformat(),
           "filled_at":(NOW-timedelta(minutes=6)).isoformat()},
          {"account":"another","client_order_id":"x","side":"buy","status":"filled",
           "symbol":"ETH-USD","created_at":NOW.isoformat()},
        ]
        result=inherit_records("robinhood_crypto","rh1",rows,now=NOW,
            policy={"reentry_cooldown_minutes":30})
        self.assertEqual((result.entries_today,result.exits_today),(1,1))
        self.assertEqual(result.reentry_blocked_symbols,frozenset({"BTC-USD"}))
        self.assertFalse(result.all_buys_blocked)
    def test_robinhood_no_default_cooldown_or_unknown_status(self):
        row={"account":"rh1","client_order_id":"1","side":"buy","status":"filled",
             "symbol":"BTC-USD","created_at":NOW.isoformat()}
        with self.assertRaises(V1InheritanceUnavailable):
            inherit_records("robinhood_crypto","rh1",[row],now=NOW,policy={})
        row["status"]="pending"
        with self.assertRaises(V1InheritanceUnavailable):
            inherit_records("robinhood_crypto","rh1",[row],now=NOW,
                policy={"reentry_cooldown_minutes":30})
    def test_robinhood_signed_manual_external_sale_retains_cooldown(self):
        row={"account":"rh1","side":"external_reduction",
             "external_broker_order_ids":["broker-sell-id"],
             "status":"externally_reconciled","symbol":"ETH-USD",
             "created_at":NOW.isoformat(),
             "filled_at":(NOW-timedelta(minutes=2)).isoformat()}
        result=inherit_records("robinhood_crypto","rh1",[row],now=NOW,
                policy={"reentry_cooldown_minutes":30})
        self.assertEqual(result.exits_today,1)
        self.assertIn("ETH-USD",result.reentry_blocked_symbols)
        row["external_broker_order_ids"]=[]
        with self.assertRaises(V1InheritanceUnavailable):
            inherit_records("robinhood_crypto","rh1",[row],now=NOW,
                      policy={"reentry_cooldown_minutes":30})

    def test_schwab_last_filled_sale_blocks_same_day_buy(self):
        row={"order_id":"100","action":"SELL","state":"FILLED","symbol":"SPY",
             "created_at":(NOW-timedelta(minutes=20)).isoformat()}
        result=inherit_records("schwab","sha123",[row],now=NOW,
                policy={"max_orders_per_day":10})
        self.assertTrue(result.all_buys_blocked)
        self.assertEqual(result.exits_today,1)
        follow=inherit_records("schwab","sha123",[row],
                      now=NOW+timedelta(days=1),policy={"max_orders_per_day":10})
        self.assertFalse(follow.all_buys_blocked)
    def test_schwab_global_daily_order_limit_is_mandatory(self):
        row={"order_id":"100","action":"BUY","state":"FILLED","symbol":"SPY",
             "created_at":NOW.isoformat()}
        result=inherit_records("schwab","sha123",[row],now=NOW,
            policy={"max_orders_per_day":2})
        self.assertEqual(result.max_daily_total_orders,2)
        with self.assertRaises(V1InheritanceUnavailable):
            inherit_records("schwab","sha123",[row],now=NOW)
        with self.assertRaises(V1InheritanceUnavailable):
            inherit_records("schwab","sha123",[row],now=NOW,
                  policy={"max_orders_per_day":101})
    def test_webull_daily_order_history_cannot_reset(self):
        row={"account":"webull1","client_id":"a","side":"BUY","status":"FILLED",
             "symbol":"AAPL","created_at":NOW.isoformat()}
        result=inherit_records("webull","webull1",[row],now=NOW)
        self.assertEqual(result.entries_today,1)
        self.assertEqual(result.exits_today,0)
    def test_missing_created_at_and_duplicate_identity_fail(self):
        record={"account":"webull1","client_id":"a","side":"BUY","status":"FILLED",
             "symbol":"AAPL"}
        with self.assertRaises(V1InheritanceUnavailable):
            inherit_records("webull","webull1",[record],now=NOW)
        record["created_at"]=NOW.isoformat()
        with self.assertRaises(V1InheritanceUnavailable):
            inherit_records("webull","webull1",[record,record],now=NOW)
    def test_account_mismatch_schwab_not_silently_ignored(self):
        row={"account":"another","order_id":"100","action":"BUY","state":"FILLED",
            "symbol":"SPY","created_at":NOW.isoformat()}
        with self.assertRaises(V1InheritanceUnavailable):
            inherit_records("schwab","this-account",[row],now=NOW,
                    policy={"max_orders_per_day":10})
    def test_inheritance_does_not_change_input(self):
        row={"account":"webull1","client_id":"a","side":"BUY","status":"FILLED",
             "symbol":"AAPL","created_at":NOW.isoformat()}
        raw=json.dumps([row])
        inherit_records("webull","webull1",[row],now=NOW)
        self.assertEqual(json.dumps([row]),raw)

class SignedV1Reader(TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.ctx=patch("trader_v2.v1_order_inheritance.launch_status",
            return_value={"gates":[{"name":name,"verified":True} for name in (
                "SIGNED_PREFLIGHT_FRESH","SIGNED_ACCOUNT","SIGNED_HOLDINGS",
                "SIGNED_ORDER_HISTORY","NO_OPEN_OR_UNRESOLVED_ORDERS")]})
        self.gate=self.ctx.start()
        self.addCleanup(self.ctx.stop)
    def private(self,relative,doc):
        path=self.root/relative
        path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
        path.parent.chmod(0o700)
        path.write_text(json.dumps(doc))
        path.chmod(0o600)
    def test_webull_signed_history_and_selected_account(self):
        self.private("webull/trading_policy.json",
                     {"enabled":True,"trade_stocks":True,"stock_account":"webull1",
                      "trade_crypto":False,"crypto_account":""})
        path=self.root/"webull/orders.sqlite3"
        with sqlite3.connect(path) as db:
            db.execute("CREATE TABLE orders(account TEXT,client_id TEXT,side TEXT,"
                       "status TEXT,created_at TEXT,fill_at TEXT,symbol TEXT)")
            db.execute("INSERT INTO orders VALUES(?,?,?,?,?,?,?)",(
                 "webull1","a","BUY","FILLED",NOW.isoformat(),NOW.isoformat(),"AAPL"))
        path.chmod(0o600)
        self.assertEqual(read_inherited(self.root,"webull","webull1",now=NOW).entries_today,1)
        with self.assertRaises(V1InheritanceUnavailable):
            read_inherited(self.root,"webull","wrong",now=NOW)
        self.assertTrue(path.exists())
    def test_signed_history_missing_any_gate_fails_before_local_state(self):
        self.gate.return_value={"gates":[]}
        with self.assertRaises(V1InheritanceUnavailable):
            read_inherited(self.root,"webull","webull1",now=NOW)
        self.assertFalse((self.root/"v2").exists())
    def test_robinhood_existing_order_journal_and_cooldown(self):
        self.private("robinhood/risk_policy.json",
                     {"account":"rh1","reentry_cooldown_minutes":30})
        self.private("robinhood/order_intents.json",
          {"version":1,"orders":[
           {"account":"rh1","client_order_id":"a","side":"sell","status":"filled",
             "created_at":NOW.isoformat(),"filled_at":NOW.isoformat(),
             "symbol":"BTC-USD"}]})
        result=read_inherited(self.root,"robinhood_crypto","rh1",now=NOW)
        self.assertEqual(result.exits_today,1)
        self.assertIn("BTC-USD",result.reentry_blocked_symbols)
    def test_schwab_unmatched_live_account_rejected(self):
        self.private("live/risk_settings.json",
                     {"version":1,"settings":{"max_orders_per_day":10}})
        self.private("live/orders.json",
           {"version":1,"halted":False,"orders":[
               {"order_id":"4","action":"BUY","state":"FILLED","symbol":"SPY",
                "created_at":NOW.isoformat()}]})
        with patch("unified_config.settings",return_value={"live_account_hash":"sha123"}):
            result=read_inherited(self.root,"schwab","sha123",now=NOW)
            self.assertEqual(result.entries_today,1)
            with self.assertRaises(V1InheritanceUnavailable):
                read_inherited(self.root,"schwab","another",now=NOW)
