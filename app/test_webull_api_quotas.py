"""Webull rate-limit, account eligibility and AI pipeline regression tests.
No network, credentials, browser or order submissions are involved.
"""
import json,os,tempfile,time,sys,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent))
from webull_broker import WebullBroker,WebullError
from webull_worker import run_cycle,_scan,account_readiness
from webull_trade_config import save as save_policy
from webull_risk import save as save_risk,DEFAULT as RISK_DEFAULT
from webull_account_preferences import save as save_prefs

class TestWebullQuotaAndEligibility(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        (self.root/"webull").mkdir(mode=0o700)
        (self.root/"config").mkdir(mode=0o700)
        (self.root/"config"/"webull_openapi.json").write_text("TEST ONLY NO CREDENTIAL")
    def test_shared_quota_token_is_atomic_private_and_serialized(self):
        a=WebullBroker.__new__(WebullBroker)
        b=WebullBroker.__new__(WebullBroker)
        a._state=self.root;b._state=self.root
        a._limit("balance",.12)
        started=time.monotonic()
        b._limit("balance",.12)
        self.assertGreaterEqual(time.monotonic()-started,.1)
        f=self.root/"webull"/".throttle_balance"
        self.assertEqual(f.stat().st_mode & 0o077,0)
    def test_account_list_cached_for_repeated_checks_and_dashboard_instances(self):
        data={"accounts":[{"account_id":"only1","account_type":"INDIVIDUAL_MARGIN"}]}
        calls=[0]
        def sdk_list():
            calls[0]+=1
            return SimpleNamespace(status_code=200,json=lambda:data)
        a=WebullBroker.__new__(WebullBroker)
        a._state=self.root
        a.trade=SimpleNamespace(account_v2=SimpleNamespace(get_account_list=sdk_list))
        self.assertEqual(a.accounts()[0]["account_type"],"INDIVIDUAL_MARGIN")
        self.assertEqual(a.verify_account("only1")["account_type"],"INDIVIDUAL_MARGIN")
        b=WebullBroker.__new__(WebullBroker)
        b._state=self.root
        b.trade=SimpleNamespace(account_v2=SimpleNamespace(get_account_list=sdk_list))
        self.assertEqual(b.accounts()[0]["account_id"],"only1")
        self.assertEqual(calls[0],1)
        with self.assertRaises(WebullError):
            a.verify_account("not-authorized")
    def test_cash_brokerage_accounts_hidden_but_crypto_and_margin_present(self):
        cash=account_readiness({"account_id":"c","account_type":"INDIVIDUAL_CASH"},True)
        margin=account_readiness({"account_id":"m","account_type":"INDIVIDUAL_MARGIN"},True)
        crypto=account_readiness({"account_id":"x","account_type":"CRYPTO"},True)
        self.assertEqual(cash["status"],"CASH_ACCOUNT_EXCLUDED_FROM_TRADING")
        self.assertFalse(cash["stocks_cash_eligible"])
        self.assertTrue(margin["stocks_cash_eligible"])
        self.assertTrue(crypto["crypto_cash_eligible"])
        root=Path(__file__).resolve().parent.parent
        js=(root/"web"/"app.js").read_text()
        brokers=(root/"web"/"brokers.js").read_text()
        self.assertIn('!/CASH/i.test(a.account_type||"")',js)
        self.assertIn('!/CASH/i.test(a.account_type||"")',brokers)
    def test_selected_balance_only_avoids_nontrading_api_reads(self):
        class Broker:
            environment="production"
            def __init__(self): self.balance_calls=[]
            def accounts(self):
                return [{"account_id":"c","account_type":"INDIVIDUAL_CASH"},
                        {"account_id":"m","account_type":"INDIVIDUAL_MARGIN"},
                        {"account_id":"x","account_type":"CRYPTO"}]
            def balance(self,account):
                self.balance_calls.append(account)
                return {"total_asset_currency":"USD","total_net_liquidation_value":"1000",
                        "total_cash_balance":"500","total_day_profit_loss":"0"}
        save_risk(self.root,dict(RISK_DEFAULT))
        save_prefs(self.root,{"allow_margin_accounts":True})
        policy={"enabled":True,"stock_account":"m","crypto_account":"",
                "trade_stocks":True,"trade_crypto":False}
        save_policy(self.root,policy,Broker().accounts(),"ENABLE_WEBULL_LIVE")
        b=Broker()
        with patch("webull_worker._scan",return_value=[]):
            report=run_cycle(self.root,b)
        self.assertEqual(b.balance_calls,["m"])
        self.assertTrue(report["live_orders_allowed"])
        self.assertEqual(len(report["account_summaries"]),1)
        self.assertEqual(report["account_summaries"][0]["account_id"],"m")
        self.assertEqual(len(report["broker_accounts"]),3)
    def test_selected_balance_http_429_marks_armed_but_blocks_new_entries(self):
        class Broker:
            environment="production"
            def accounts(self):return [{"account_id":"m","account_type":"INDIVIDUAL_MARGIN"}]
            def balance(self,account):raise WebullError("Webull API rejected request (HTTP 429)")
        save_risk(self.root,dict(RISK_DEFAULT))
        save_prefs(self.root,{"allow_margin_accounts":True})
        save_policy(self.root,{"enabled":True,"stock_account":"m","crypto_account":"",
            "trade_stocks":True,"trade_crypto":False},Broker().accounts(),"ENABLE_WEBULL_LIVE")
        with patch("webull_worker._scan",return_value=[]):
            result=run_cycle(self.root,Broker())
        self.assertEqual(result["execution_status"],"ARMED_ACCOUNT_DATA_UNAVAILABLE")
        self.assertEqual(result["execution_reason"],"BROKER_RATE_LIMITED_HTTP_429")
        self.assertEqual(result["approved_candidates"],[])
    def test_crypto_candidate_uses_existing_validated_ai_research(self):
        import webull_worker
        class FakeScanBroker:
            def quote(self,sym,asset):return {"bid":"10","ask":"10.02","quote_time":time.time()}
            def bars(self,sym,asset):return []
        original_evaluate=webull_worker.evaluate
        def evaluate(symbol,asset,*args,**kwargs):
            if asset=="CRYPTO" and symbol=="BTCUSD":
                return {"symbol":symbol,"asset":asset,"source":"COINBASE_WS",
                        "technical_approved":True,"momentum_pct":.7,"spread_pct":.08,
                        "bars":8,"reason":"Qualified rising momentum",
                        "at":webull_worker._now().isoformat(),"bid":"10","ask":"10.02",
                        "mid":"10.01"}
            return {"symbol":symbol,"asset":asset,"technical_approved":False,
                    "reason":"NO_SIGNAL"}
        with patch("webull_worker.evaluate",side_effect=evaluate),\
             patch("webull_worker.time.sleep",return_value=None),\
             patch("ai_research.research_evidence",return_value={"model":"fixture"}),\
             patch("ai_research.approve_entry",return_value=(True,"PASS")) as ai:
            result=_scan(self.root,FakeScanBroker(),0,{})
            self.assertEqual(len(result),1)
            self.assertEqual(result[0]["symbol"],"BTCUSD")
            self.assertTrue(result[0]["ai_approved"])
            ai.assert_called_once()
            self.assertEqual(ai.call_args.args[0],"BTC-USD")

if __name__=="__main__":unittest.main()
