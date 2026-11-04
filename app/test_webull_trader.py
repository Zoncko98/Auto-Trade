"""Webull isolated stocks + crypto engine: no live broker writes in tests."""
import json,os,sys,tempfile,unittest
from datetime import datetime,timezone,timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent))
from webull_journal import WebullJournal,JournalBlocked
from webull_broker import WebullBroker,WebullError
from webull_worker import _order,_live_gate,run_cycle,WebullBlocked
from webull_trade_config import read as read_policy,save as save_policy,WebullPolicyError
from webull_risk import save as save_risk,DEFAULT as RISK_DEFAULT
from webull_signals import evaluate,WebullSignalError

NOW=lambda:datetime.now(timezone.utc)
def quote():return {"symbol":"F","bid":"9.99","ask":"10","quote_time":int(NOW().timestamp()*1000)}
def bars():
    now=NOW()
    return [{"time":(now-timedelta(minutes=i)).isoformat(),"close":str(9.5+(7-i)*0.07)}
            for i in range(7,0,-1)]

class FakeBroker:
    environment="production"
    def __init__(self):
        self.previews=[]
        self.submissions=[]
        self.details={}
        self.available=[{"account_id":"stock1","account_class":"EQUITY"},
                        {"account_id":"crypto1","account_class":"CRYPTO"}]
        self.holdings=[]
        self.existing=[]
    def accounts(self):return self.available
    def verify_account(self,id):
        rows=[x for x in self.available if x["account_id"]==id]
        if len(rows)!=1:raise WebullError("Not authenticated")
        return rows[0]
    def open_orders(self,id):return self.existing
    def balance(self,id):
        self.verify_account(id)
        return {"total_asset_currency":"USD","total_net_liquidation_value":"1000",
                "total_cash_balance":"1000","total_market_value":"0",
                "total_day_profit_loss":"0",
                "account_currency_assets":[{"currency":"USD","buying_power":"500",
                                             "cash_balance":"500","settled_cash":"500"}]}
    def positions(self,id):return self.holdings
    def quote(self,symbol,asset):return quote()
    def bars(self,symbol,asset):return bars()
    def preview(self,account,order):
        self.previews.append((account,dict(order)))
        return {"estimated_cost":"10.00","success":True}
    def place(self,account,order):
        self.submissions.append((account,dict(order)))
        return {"orders":[{"client_order_id":order["client_order_id"],
                           "status":"SUBMITTED"}]}
    def order_detail(self,account,id):
        if id not in self.details:raise WebullError("Not yet reported")
        return self.details[id]

class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state=Path(self.tmp.name)
        self.b=FakeBroker()
        self.j=WebullJournal(self.state)
        flag=patch("webull_worker.LIVE_EXECUTION_VERIFIED",True)
        flag.start()
        self.addCleanup(flag.stop)
        self.risk=save_risk(self.state,dict(RISK_DEFAULT))
        self.policy={"enabled":False,"stock_account":"stock1","crypto_account":"crypto1",
                     "trade_stocks":True,"trade_crypto":True}
        self.accounts=self.b.accounts()
    def arm(self):
        with self.assertRaises(WebullPolicyError):
            save_policy(self.state,dict(self.policy,enabled=True),self.accounts)
        with patch("webull_trade_config.LIVE_EXECUTION_VERIFIED",True):
            self.policy=save_policy(self.state,dict(self.policy,enabled=True),
                                    self.accounts,"ENABLE_WEBULL_LIVE")
    def signal(self):
        return {"at":NOW().isoformat(),"symbol":"F","asset":"EQUITY",
                "bid":"9.99","ask":"10","technical_approved":True,"ai_approved":True}
    def test_stock_bars_accept_one_unambiguous_live_webull_wrapper(self):
        from types import SimpleNamespace
        broker=WebullBroker.__new__(WebullBroker)
        rows=[{"time":"2026-11-03T14:00:00Z","close":"100.00"},
              {"time":"2026-11-03T14:01:00Z","close":"100.01"}]
        payloads=[
            {"symbol":"AAPL","result":rows},
            {"result":[{"symbol":"AAPL","result":rows}]},
            {"result":rows},
            rows]
        for payload in payloads:
            broker.data=SimpleNamespace(market_data=SimpleNamespace(
                get_history_bar=lambda *args,body=payload,**kwargs:
                    SimpleNamespace(status_code=200,json=lambda:body)))
            self.assertEqual(broker.bars("AAPL","EQUITY"),rows)
    def test_stock_bars_reject_misrouted_or_ambiguous_webull_wrapper(self):
        from types import SimpleNamespace
        broker=WebullBroker.__new__(WebullBroker)
        rows=[{"time":"2026-11-03T14:00:00Z","close":"100.00"}]
        bad=[
            {"symbol":"MSFT","result":rows},
            {"result":[{"symbol":"MSFT","result":rows}]},
            {"result":[{"symbol":"AAPL","result":rows},
                       {"symbol":"MSFT","result":rows}]},
            {"result":[{"time":"2026-11-03T14:00:00Z",
                        "close":"100.00","symbol":"MSFT"}]},
            {"result":[{"symbol":"AAPL","result":"invalid"}]},
            {"result":[]}]
        for body in bad:
            broker.data=SimpleNamespace(market_data=SimpleNamespace(
                get_history_bar=lambda *args,payload=body,**kwargs:
                    SimpleNamespace(status_code=200,json=lambda:payload)))
            with self.assertRaises(WebullError):
                broker.bars("AAPL","EQUITY")
    def test_readonly_stock_data_probe_classifies_three_endpoints(self):
        from types import SimpleNamespace
        broker=WebullBroker.__new__(WebullBroker)
        calls=[]
        def reply(method,status):
            def invoke(*args,**kwargs):
                calls.append((method,args,kwargs))
                return SimpleNamespace(status_code=status)
            return invoke
        market=SimpleNamespace(
            get_snapshot=reply("snapshot",200),
            get_quotes=reply("quote",403),
            get_history_bar=reply("bars",200))
        broker.data=SimpleNamespace(market_data=market)
        result=broker.stock_api_probe()
        self.assertEqual(result["state"],"PARTIAL_STOCK_ENDPOINT_ACCESS")
        self.assertEqual(result["endpoints"]["snapshot"]["status"],"OK")
        self.assertEqual(result["endpoints"]["best_bid_ask"]["status"],"HTTP_403")
        self.assertEqual(result["endpoints"]["minute_bars"]["status"],"OK")
        self.assertFalse(result["orders_submitted"])
        self.assertEqual([r[0] for r in calls],["snapshot","quote","bars"])
        self.assertEqual(calls[1][2]["depth"],1)
        self.assertEqual(calls[0][1],("AAPL","US_STOCK"))
    def test_stock_data_schema_probe_never_copies_raw_payload_or_credentials(self):
        from types import SimpleNamespace
        broker=WebullBroker.__new__(WebullBroker)
        secret="DO_NOT_ECHO_SIGNED_HEADERS_OR_KEYS"
        response=lambda:SimpleNamespace(status_code=200,json=lambda:{
            "data":[{"symbol":"AAPL","quote_time":"2026-11-03T18:00:00Z",
                     "bids":[{"price":"100"}],"sensitive":secret}],
            "access_token":secret,"signature":secret})
        broker.data=SimpleNamespace(market_data=SimpleNamespace(
            get_snapshot=lambda *a,**k:response(),
            get_quotes=lambda *a,**k:response(),
            get_history_bar=lambda *a,**k:response()))
        summary=broker.stock_api_probe()
        self.assertEqual(summary["state"],"ALL_STOCK_ENDPOINTS_AUTHORIZED")
        self.assertEqual(summary["endpoints"]["best_bid_ask"]["schema"]["data_container"],"list")
        self.assertIn("symbol",summary["endpoints"]["best_bid_ask"]["schema"]["data_fields"])
        self.assertNotIn(secret,json.dumps(summary))
    def test_readonly_stock_data_probe_sanitizes_403_and_signed_sdk_errors(self):
        from types import SimpleNamespace
        broker=WebullBroker.__new__(WebullBroker)
        secret="TEST_PRIVATE_KEY_MUST_NEVER_LEAK"
        def forbidden(*args,**kwargs):
            raise RuntimeError("HTTP Status: 403 "+secret)
        market=SimpleNamespace(
            get_snapshot=forbidden,
            get_quotes=forbidden,
            get_history_bar=forbidden)
        broker.data=SimpleNamespace(market_data=market)
        result=broker.stock_api_probe()
        self.assertEqual(result["state"],"ALL_STOCK_ENDPOINTS_FORBIDDEN")
        self.assertTrue(all(v["status"]=="HTTP_403" for v in result["endpoints"].values()))
        self.assertNotIn(secret,json.dumps(result))
        self.assertFalse(result["orders_submitted"])
    def test_real_market_blockers_are_distinguished_without_weakening_risk(self):
        from webull_worker import market_readiness
        summary=market_readiness([
            {"asset":"EQUITY","symbol":"AAPL","technical_approved":False,
             "reason":"MARKET_DATA_WEBULL_HTTP_403"},
            {"asset":"CRYPTO","symbol":"BTCUSD","technical_approved":False,
             "reason":"MARKET_DATA_SIGNAL_BROKER_SPREAD_ABOVE_0_5"}])
        self.assertEqual(summary["stocks"]["status"],"MARKET_DATA_PERMISSION_REQUIRED")
        self.assertEqual(summary["crypto"]["status"],"BROKER_SPREAD_TOO_WIDE")
        self.assertEqual(summary["stocks"]["permission_errors"],1)
        self.assertEqual(summary["crypto"]["spread_blocks"],1)
        self.assertNotIn("enabled",summary)
        self.assertEqual(market_readiness([])["stocks"]["status"],"NOT_SCANNED")
        mixed=market_readiness([
            {"asset":"EQUITY","reason":"MARKET_DATA_WEBULL_HTTP_403"},
            {"asset":"EQUITY","reason":"No qualifying momentum"}])
        self.assertEqual(mixed["stocks"]["status"],"MARKET_DATA_DEGRADED")
    def test_disarmed_ai_pipeline_reviews_candidates_but_never_submits(self):
        from webull_worker import _scan
        signal=dict(self.signal(),technical_approved=True,mid="9.995",
                    momentum_pct=0.75,spread_pct=0.1,source="WEBULL_M1")
        with patch("webull_worker.evaluate",return_value=signal),             patch("ai_research.approve_entry",return_value=(True,"Approved")) as ai,             patch("ai_research.research_evidence",return_value={"model":"test-ai"}):
            report={}
            approved=_scan(self.state,self.b,0,report)
        self.assertTrue(approved)
        self.assertEqual(report["candidates"],6)
        self.assertEqual(len(report["ai_reviews"]),2)
        self.assertEqual(ai.call_count,2)
        self.assertEqual(self.b.submissions,[])
        self.assertTrue(all(x.get("ai_approved") is True for x in approved))
    def test_webull_ui_cannot_select_unverified_margin_account(self):
        js=(Path(__file__).resolve().parent.parent/"web"/"app.js").read_text()
        self.assertIn('a.status==="MARGIN_ACCOUNT_BLOCKED"',js)
        self.assertIn('opt.disabled=!eligible;',js)
        self.assertIn('a.stocks_cash_eligible===true',js)
        self.assertIn('a.crypto_cash_eligible===true',js)
        self.assertIn('Broker account "+suffix+" · "+type',js)
    def test_margin_opt_in_defaults_off_and_has_private_persistence(self):
        from webull_account_preferences import read as pref_read, save as pref_save, PreferenceError
        self.assertEqual(pref_read(self.state),{"allow_margin_accounts":False})
        result=pref_save(self.state,{"allow_margin_accounts":True})
        self.assertTrue(result["allow_margin_accounts"])
        self.assertTrue(pref_read(self.state)["allow_margin_accounts"])
        pref_file=self.state/"webull"/"account_preferences.json"
        self.assertEqual(pref_file.stat().st_mode & 0o077,0)
        self.assertEqual(pref_file.parent.stat().st_mode & 0o077,0)
        for bad in ({"allow_margin_accounts":1},{"allow_margin_accounts":"true"},
                    {"allow_margin_accounts":True,"enabled":True},{}):
            with self.assertRaises(PreferenceError):pref_save(self.state,bad)
        self.assertEqual(pref_read(self.state),{"allow_margin_accounts":True})
    def test_margin_opt_in_is_cash_funded_stocks_only_and_not_live_arm(self):
        from webull_account_preferences import save as pref_save
        from webull_worker import account_readiness
        margin={"account_id":"stock1","account_type":"INDIVIDUAL_MARGIN"}
        self.assertEqual(account_readiness(margin)["status"],"MARGIN_ACCOUNT_BLOCKED")
        prefs=pref_save(self.state,{"allow_margin_accounts":True})
        allowed=account_readiness(margin,prefs["allow_margin_accounts"])
        self.assertTrue(allowed["stocks_cash_eligible"])
        self.assertFalse(allowed["crypto_cash_eligible"])
        self.assertFalse(allowed["margin_borrowing_enabled"])
        self.assertEqual(allowed["status"],"MARGIN_CASH_ONLY_ELIGIBLE")
        self.assertFalse(read_policy(self.state)["enabled"])
        self.arm()
        self.b.available=[margin]
        raw=self.b.balance("stock1")
        self.b.balance=lambda account:dict(raw,used_margin="0",margin_debit="0")
        with patch("webull_worker.core_stock_session",return_value=True):
            result=_live_gate(self.state,self.b,self.policy,self.risk,
                              "stock1","EQUITY","F","BUY","1","10",self.j)
        self.assertEqual(result["asset"],"EQUITY")
        with self.assertRaises(WebullBlocked):
            _live_gate(self.state,self.b,self.policy,self.risk,
                       "stock1","CRYPTO","BTCUSD","BUY","1","10",self.j)
        pref_save(self.state,{"allow_margin_accounts":False})
        with patch("webull_worker.core_stock_session",return_value=True):
            with self.assertRaises(WebullBlocked):
                _live_gate(self.state,self.b,self.policy,self.risk,
                           "stock1","EQUITY","F","BUY","1","10",self.j)
        self.assertEqual(self.b.submissions,[])
    def test_margin_opt_in_rejects_actual_borrowing_and_insufficient_cash(self):
        from webull_account_preferences import save as pref_save
        pref_save(self.state,{"allow_margin_accounts":True})
        self.arm()
        self.b.available=[{"account_id":"stock1","account_type":"INDIVIDUAL_MARGIN"}]
        base=FakeBroker().balance("stock1")
        for broken in (
            dict(base,used_margin="0.01"),
            dict(base,used_margin="0",margin_debit="1"),
            dict(base,used_margin="0",account_currency_assets=[
                {"currency":"USD","buying_power":"500","cash_balance":"-1"}]),
            dict(base,used_margin="0",account_currency_assets=[
                {"currency":"USD","buying_power":"500","cash_balance":"500","settled_cash":"0"}],
                 total_market_value="0")):
            # Reported debt or insufficient actual cash still blocks; a missing
            # settled_cash field alone is normal for Webull margin accounts.
            self.b.balance=lambda account,result=broken:result
            with patch("webull_worker.core_stock_session",return_value=True):
                with self.assertRaises((WebullBlocked,WebullError)):
                    _live_gate(self.state,self.b,self.policy,self.risk,
                               "stock1","EQUITY","F","BUY","1","10",self.j)
        self.assertEqual(self.b.submissions,[])
    def test_profile_margin_toggle_endpoints_and_ui_are_present(self):
        root=Path(__file__).resolve().parent.parent
        html=(root/"web"/"index.html").read_text()
        js=(root/"web"/"app.js").read_text()
        server=(root/"app"/"dashboard_server.py").read_text()
        self.assertIn('id="profile-webull-margin-form"',html)
        self.assertIn('id="profile-webull-margin-enabled"',html)
        self.assertIn("margin borrowing, leverage, short selling",html)
        self.assertIn('request("/api/profile/webull-margin"',js)
        self.assertIn('"allow_margin_accounts":False', (root/"app"/"webull_account_preferences.py").read_text())
        self.assertIn('path == "/api/profile/webull-margin"',server)
        self.assertIn("opt.disabled=!eligible;",js)
    def test_account_types_make_margin_and_crypto_eligibility_explicit(self):
        from webull_worker import account_readiness
        margin=account_readiness({"account_id":"m","account_type":"INDIVIDUAL_MARGIN"})
        self.assertEqual(margin["status"],"MARGIN_ACCOUNT_BLOCKED")
        self.assertFalse(margin["stocks_cash_eligible"])
        self.assertFalse(margin["crypto_cash_eligible"])
        self.assertFalse(account_readiness({"account_id":"s","account_class":"CASH"})["stocks_cash_eligible"])
        self.assertEqual(account_readiness({"account_id":"s","account_class":"CASH"})["status"],
                         "CASH_ACCOUNT_EXCLUDED_FROM_TRADING")
        self.assertTrue(account_readiness({"account_id":"s","account_class":"EQUITY"})["stocks_cash_eligible"])
        self.assertTrue(account_readiness({"account_id":"c","account_class":"CRYPTO"})["crypto_cash_eligible"])
        self.assertFalse(account_readiness({"account_id":"x","account_type":"UNVERIFIED"})["stocks_cash_eligible"])
    def test_stock_order_must_preview_before_journal_or_place(self):
        self.arm()
        self.b.preview=lambda account,order:{"success":False,"errors":[{"error":"preview blocked"}]}
        with self.assertRaises(WebullBlocked):
            _order(self.state,self.b,self.policy,self.risk,self.j,
                   "stock1","F","EQUITY","BUY",self.signal(),"1","10","AI")
        self.assertEqual(self.j.recent(),[])
        self.assertEqual(self.b.submissions,[])
    def test_equity_preview_is_not_an_order_and_crypto_preview_is_unsupported(self):
        from types import SimpleNamespace
        dummy=WebullBroker.__new__(WebullBroker)
        dummy.verify_account=lambda account: True
        calls=[]
        dummy.trade=SimpleNamespace(order_v3=SimpleNamespace(
            preview_order=lambda account,orders:(
                calls.append("preview") or SimpleNamespace(status_code=200,json=lambda:{"estimate":"10"})),
            place_order=lambda account,orders:(
                calls.append("place") or SimpleNamespace(status_code=200,json=lambda:{"ok":True}))))
        order={"combo_type":"NORMAL","client_order_id":"f"*32,"symbol":"F",
           "instrument_type":"EQUITY","market":"US","order_type":"LIMIT",
           "limit_price":"10","quantity":"1","side":"BUY","time_in_force":"DAY",
           "entrust_type":"QTY","support_trading_session":"CORE"}
        self.assertEqual(dummy.preview("stock1",order),{"estimate":"10"})
        self.assertEqual(calls,["preview"])
        with self.assertRaises(WebullError):dummy.preview(
            "crypto1",dict(order,symbol="BTCUSD",instrument_type="CRYPTO"))
        self.assertEqual(calls,["preview"])
    def test_migrates_preexisting_webull_state_to_private_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"webull"
            path.mkdir()
            path.chmod(0o755)
            journal=WebullJournal(tmp)
            self.assertEqual(path.stat().st_mode & 0o077,0)
            self.assertTrue(journal.path.exists())
    def test_journal_duplicate_crash_and_broker_fill(self):
        client_id="a"*32
        self.j.new_intent("stock1",client_id,"F","EQUITY","BUY","1","10","AI approved")
        with self.assertRaises(JournalBlocked):
            WebullJournal(self.state).new_intent("stock1","b"*32,"F","EQUITY","BUY","1","10","duplicate")
        self.j.acknowledged(client_id,{})
        self.assertEqual(len(WebullJournal(self.state).pending("stock1")),1)
        self.assertEqual(self.j.reconcile("stock1",self.b)[0]["state"],"RECONCILIATION_UNAVAILABLE")
        self.b.details[client_id]={"orders":[{"client_order_id":client_id,"status":"PARTIAL_FILLED",
                              "filled_quantity":"0.5","filled_price":"10","filled_time_at":NOW().isoformat()}]}
        self.assertEqual(self.j.reconcile("stock1",self.b)[0]["state"],"PARTIAL_FILLED")
        self.assertTrue(self.j.pending("stock1"))
        self.b.details[client_id]["orders"][0].update(
            status="FILLED",filled_quantity="1",filled_price="10",filled_time_at=NOW().isoformat())
        self.assertEqual(self.j.reconcile("stock1",self.b)[0]["state"],"FILLED")
        self.assertEqual(self.j.pending("stock1"),[])
        owned,pnl=self.j.positions("stock1")
        self.assertEqual(owned["F"]["quantity"],"1")
        self.assertEqual(owned["F"]["cost_basis"],"10")
        self.assertEqual(pnl,"0")
        self.assertEqual(self.j.path.stat().st_mode & 0o077,0)
    def test_ambiguous_submission_does_not_retry(self):
        self.arm()
        signal=self.signal()
        self.b.place=lambda account,order: (_ for _ in ()).throw(OSError("timeout"))
        with patch("webull_worker.core_stock_session",return_value=True):
            with self.assertRaises(OSError):_order(self.state,self.b,self.policy,self.risk,
                                    self.j,"stock1","F","EQUITY","BUY",signal,"1","10","AI")
        self.assertEqual(len(self.j.pending("stock1")),1)
        with self.assertRaises((JournalBlocked,WebullBlocked)):
            _order(self.state,self.b,self.policy,self.risk,self.j,
                   "stock1","F","EQUITY","BUY",signal,"1","10","AI")
    def test_approved_entry_receipt_not_fill(self):
        self.arm()
        with patch("webull_worker.core_stock_session",return_value=True):
            receipt=_order(self.state,self.b,self.policy,self.risk,self.j,
                           "stock1","F","EQUITY","BUY",self.signal(),"1","10","AI")
        self.assertEqual(receipt["state"],"BROKER_ACKNOWLEDGED_UNFILLED")
        self.assertEqual(len(self.b.previews),1)
        self.assertEqual(len(self.b.submissions),1)
        self.assertEqual(self.b.submissions[0][1]["support_trading_session"],"CORE")
        self.assertEqual(self.j.positions("stock1")[0],{})
        self.assertEqual(len(self.j.pending("stock1")),1)
    def test_real_live_gate_allows_authorized_cash_only_without_fake_broker_validation(self):
        self.arm()
        with patch("webull_worker.LIVE_EXECUTION_VERIFIED",False):
            with patch("webull_worker.core_stock_session",return_value=True):
                result=_live_gate(self.state,self.b,self.policy,self.risk,
                                  "stock1","EQUITY","F","BUY","1","10",self.j)
        self.assertEqual(result["asset"],"EQUITY")
        self.assertEqual(self.b.submissions,[])
    def test_live_gate_rejects_sandbox_environment_even_when_policy_armed(self):
        self.arm()
        self.b.environment="sandbox"
        with self.assertRaisesRegex(WebullBlocked,"production API environment"):
            _live_gate(self.state,self.b,self.policy,self.risk,
                       "stock1","EQUITY","F","BUY","1","10",self.j)
        self.assertEqual(self.b.submissions,[])
    def test_no_implicit_live_order(self):
        with self.assertRaises(WebullBlocked):
            _order(self.state,self.b,self.policy,self.risk,self.j,
                   "stock1","F","EQUITY","BUY",self.signal(),"1","10","AI")
        with patch("webull_worker._scan",return_value=[]):
            report=run_cycle(self.state,self.b)
        self.assertEqual(report["execution_status"],"DISARMED")
        self.assertEqual(self.b.submissions,[])
        self.assertEqual(report["environment"],"production")
        self.assertIn("stock1",str(report["broker_accounts"]))
    def test_cash_only_and_daily_loss_limits(self):
        self.arm()
        self.b.available=[{"account_id":"stock1","account_class":"MARGIN"},
                          {"account_id":"crypto1","account_class":"CRYPTO"}]
        with self.assertRaises(WebullBlocked):
            _live_gate(self.state,self.b,self.policy,self.risk,
                       "stock1","EQUITY","F","BUY","1","10",self.j)
        self.b.available=self.accounts
        self.b.balance=lambda id:dict(FakeBroker().balance(id),total_day_profit_loss="-30")
        with self.assertRaises(WebullBlocked):
            _live_gate(self.state,self.b,self.policy,self.risk,
                       "stock1","EQUITY","F","BUY","1","10",self.j)
    def test_external_holdings_limit_and_unsupported_assets(self):
        self.arm()
        self.b.holdings=[{"symbol":"F","instrument_type":"EQUITY","quantity":"1"}]
        with self.assertRaises(WebullBlocked):
            _live_gate(self.state,self.b,self.policy,self.risk,
                       "stock1","EQUITY","F","BUY","1","10",self.j)
        self.b.holdings=[]
        self.b.existing=[{"status":"PENDING"}]
        with self.assertRaises(WebullBlocked):
            _live_gate(self.state,self.b,self.policy,self.risk,
                       "stock1","EQUITY","F","BUY","1","10",self.j)
    def test_operator_cannot_arm_wrong_account(self):
        with patch("webull_trade_config.LIVE_EXECUTION_VERIFIED",True):
            with self.assertRaises(WebullPolicyError):
                save_policy(self.state,dict(self.policy,enabled=True,stock_account="wrong"),
                            self.accounts,"ENABLE_WEBULL_LIVE")
        self.assertFalse(read_policy(self.state)["enabled"])
    def test_status_diagnostics_are_safe_and_precise(self):
        from webull_worker import _safe_public
        class ServerException(Exception):pass
        self.assertEqual(_safe_public(ServerException("HTTP Status: 403, Secret=do-not-print")),
                         "WEBULL_HTTP_403")
        self.assertEqual(_safe_public(WebullSignalError("Broker quote stale")),
                         "SIGNAL_BROKER_QUOTE_STALE")
        self.assertEqual(_safe_public(RuntimeError("secret data here")), "RuntimeError")
    def test_unsupported_quote_timestamp_and_stock_market_hours(self):
        t=datetime(2026,11,3,15,0,tzinfo=timezone.utc)
        q={"bid":"9.99","ask":"10","quote_time":int(t.timestamp()*1000)}
        stock=evaluate("F","EQUITY",q,
            [{"time":(t-timedelta(minutes=i)).isoformat(),"close":str(10-i*0.02)}
             for i in range(7,0,-1)],t)
        self.assertTrue(stock["technical_approved"])
        with self.assertRaises(WebullSignalError):
            evaluate("F","EQUITY",dict(q,quote_time=int((t-timedelta(minutes=20)).timestamp()*1000)),
                     bars(),t)
    def test_broker_payload_requires_stock_session_no_shorting(self):
        from types import SimpleNamespace
        dummy=WebullBroker.__new__(WebullBroker)
        dummy.verify_account=lambda account:True
        dummy.trade=SimpleNamespace(order_v3=SimpleNamespace(
            place_order=lambda account,orders:SimpleNamespace(status_code=200,json=lambda:{"ok":True})))
        order={"combo_type":"NORMAL","client_order_id":"a"*32,"symbol":"F",
           "instrument_type":"EQUITY","market":"US","order_type":"LIMIT",
           "limit_price":"10","quantity":"1","side":"BUY","time_in_force":"DAY",
           "entrust_type":"QTY","support_trading_session":"CORE"}
        self.assertEqual(dummy.place("stock1",order),{"ok":True})
        with self.assertRaises(WebullError):dummy.place("stock1",dict(order,side="SHORT"))
        with self.assertRaises(WebullError):dummy.place("stock1",dict(order,support_trading_session="ALL"))
    def test_live_activation_requires_explicit_consent_and_saved_risk_not_sandbox(self):
        proposed=dict(self.policy,enabled=True)
        with self.assertRaisesRegex(WebullPolicyError,"Explicit live order authorization"):
            save_policy(self.state,proposed,self.accounts)
        with patch("webull_trade_config.LIVE_EXECUTION_VERIFIED",False):
            saved=save_policy(self.state,proposed,self.accounts,"ENABLE_WEBULL_LIVE")
        self.assertTrue(saved["enabled"])
        self.assertTrue(read_policy(self.state)["enabled"])
        self.assertFalse(self.b.submissions)
    def test_saving_only_default_risk_is_not_enough_to_arm(self):
        proposed=dict(self.policy,enabled=True)
        risk_file=self.state/"webull"/"risk_plan.json"
        risk_file.unlink()
        with self.assertRaisesRegex(WebullPolicyError,"Save Webull risk"):
            save_policy(self.state,proposed,self.accounts,"ENABLE_WEBULL_LIVE")
        self.assertFalse(read_policy(self.state)["enabled"])
    def test_live_margin_cash_funding_never_uses_borrowed_buying_power(self):
        from webull_worker import verify_margin_cash_funding,_funds
        baseline=FakeBroker().balance("stock1")
        # Official margin response may omit used_margin and settled_cash.
        self.assertEqual(verify_margin_cash_funding(baseline),Decimal("500"))
        allowed=dict(baseline,used_margin="0",margin_debit="0")
        self.assertEqual(verify_margin_cash_funding(allowed),Decimal("500"))
        # Leverage buying power is ignored; a $15 or greater order cannot
        # use the $50,000 day-buying-power value with only $5 actual cash.
        cash_only=dict(baseline,account_currency_assets=[{"currency":"USD",
            "cash_balance":"5","day_buying_power":"50000",
            "overnight_buying_power":"30000"}])
        self.assertEqual(verify_margin_cash_funding(cash_only),Decimal("5"))
        self.assertEqual(_funds(cash_only)[1],Decimal("5"))
        for invalid in (
            dict(allowed,used_margin="1"),dict(allowed,margin_debit="1"),
            dict(allowed,account_currency_assets=[{"currency":"USD",
                "day_buying_power":"50000"}]),
            dict(allowed,total_cash_balance="-1"),
            dict(allowed,open_margin_calls=["RM"])):
            with self.assertRaises((WebullBlocked,WebullError)):
                verify_margin_cash_funding(invalid)

    def test_open_market_exposure_cap(self):
        self.arm()
        self.b.balance=lambda id:dict(FakeBroker().balance(id),total_market_value="249")
        with self.assertRaises(WebullBlocked):
            _live_gate(self.state,self.b,self.policy,self.risk,
                       "stock1","EQUITY","F","BUY","1","10",self.j)
    def test_profit_peak_resets_for_new_position(self):
        from webull_worker import _peak
        x=_peak(self.state,"stock1","F",Decimal("11"),"2026-01-01T00:00:00Z")
        y=_peak(self.state,"stock1","F",Decimal("10"),"2026-01-01T00:00:00Z")
        z=_peak(self.state,"stock1","F",Decimal("10"),"2026-01-02T00:00:00Z")
        self.assertEqual((x,y,z),(Decimal("11"),Decimal("11"),Decimal("10")))
    def test_disarm_on_credential_rotation(self):
        from webull_trade_config import disarm
        self.arm()
        self.assertTrue(read_policy(self.state)["enabled"])
        disarm(self.state)
        self.assertFalse(read_policy(self.state)["enabled"])

if __name__=="__main__":unittest.main()
