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
    environment="sandbox"
    def __init__(self):
        self.submissions=[]
        self.details={}
        self.available=[{"account_id":"stock1","account_class":"CASH"},
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
        with self.assertRaises(OSError):_order(self.state,self.b,self.policy,self.risk,
                                self.j,"stock1","F","EQUITY","BUY",signal,"1","10","AI")
        self.assertEqual(len(self.j.pending("stock1")),1)
        with self.assertRaises((JournalBlocked,WebullBlocked)):
            _order(self.state,self.b,self.policy,self.risk,self.j,
                   "stock1","F","EQUITY","BUY",signal,"1","10","AI")
    def test_approved_entry_receipt_not_fill(self):
        self.arm()
        receipt=_order(self.state,self.b,self.policy,self.risk,self.j,
                       "stock1","F","EQUITY","BUY",self.signal(),"1","10","AI")
        self.assertEqual(receipt["state"],"BROKER_ACKNOWLEDGED_UNFILLED")
        self.assertEqual(len(self.b.submissions),1)
        self.assertEqual(self.b.submissions[0][1]["support_trading_session"],"CORE")
        self.assertEqual(self.j.positions("stock1")[0],{})
        self.assertEqual(len(self.j.pending("stock1")),1)
    def test_real_live_gate_remains_locked_until_broker_validation(self):
        self.arm()
        with patch("webull_worker.LIVE_EXECUTION_VERIFIED",False):
            with self.assertRaises(WebullBlocked):
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
        self.assertEqual(report["environment"],"sandbox")
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
    def test_live_activation_rejected_until_broker_sandbox_validated(self):
        proposed=dict(self.policy,enabled=True)
        with self.assertRaises(WebullPolicyError) as caught:
            save_policy(self.state,proposed,self.accounts,"ENABLE_WEBULL_LIVE")
        self.assertIn("sandbox order lifecycle",str(caught.exception))
        self.assertFalse(read_policy(self.state)["enabled"])
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
