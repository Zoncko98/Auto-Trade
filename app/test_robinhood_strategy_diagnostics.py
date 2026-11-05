"""Fee-aware Robinhood shadow diagnostics are evidence, never execution."""
import io,json,sqlite3,tempfile,unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile
from robinhood_strategy_diagnostics import (
    capture,summary,shadow_signal,export_tables,fee_pct,connect)
from robinhood_performance_export import build_robinhood_performance_workbook
from robinhood_order_journal import OrderJournal

NOW=datetime(2026,11,5,18,0,tzinfo=timezone.utc)
def signal(symbol="BTC-USD",bid="99.98",ask="100",source="ROBINHOOD_POLL_FALLBACK",momentum=0.8):
    return {"symbol":symbol,"at":NOW.isoformat(),"signal":"MOMENTUM_CANDIDATE",
       "technical_approved":True,"source":source,
       "trend_up":True,"momentum_pct":momentum,"spread_pct":0.02,
       "history_span_seconds":540,"history_points":7,
       "diagnostic_bid":bid,"diagnostic_ask":ask}
def hist(symbol="BTC-USD"):
    points=[(12,100),(10,107),(8,105),(6,102),(4,102.4),(2,103.2)]
    return [{"symbol":symbol,"at":(NOW-timedelta(minutes=age)).isoformat(),"mid":str(price)}
       for age,price in points]
def filled(key,side,symbol,qty,price,fee,at=NOW,verified=True,account="acct"):
    return {"account":account,"side":side,"status":"filled","symbol":symbol,
      "client_order_id":key,"filled_quantity":str(qty),"average_fill_price":str(price),
      "fee_charged":str(fee),"fee_verified":verified,
      "filled_at":at.isoformat(),"created_at":at.isoformat()}

class ShadowTests(unittest.TestCase):
 def setUp(self):
    self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
    self.root=Path(self.temp.name)
    sub=self.root/"robinhood";sub.mkdir()
    self.policy={"account":"acct","enabled":True,"fee_buffer_pct":"0.25"}
    (sub/"risk_policy.json").write_text(json.dumps(self.policy))
    self.write_orders([])
 def write_orders(self,orders):
    (self.root/"robinhood"/"order_intents.json").write_text(json.dumps({"version":1,"orders":orders}))
 def test_fee_adjusted_break_even_based_on_reconciled_actual_fills(self):
    self.write_orders([filled("fill-buy","buy","BTC-USD",2,100,1.9),
        filled("fill-sell","sell","BTC-USD",1,100,0.95)])
    doc=capture(self.root,self.policy,[signal()],{"BTC-USD":hist()}, {}, {},now=NOW)
    self.assertEqual(doc["status"],"RECORDED")
    self.assertEqual(doc["new_candidates"],1)
    self.assertGreater(doc["break_even_move_pct"],1.9)
    self.assertGreater(doc["net_0_5pct_target_move_pct"],doc["break_even_move_pct"])
 def test_every_qualified_candidate_including_unselected_recorded(self):
    rows=[signal("BTC-USD"),signal("ETH-USD",bid="99.97"),
          dict(signal("ZEC-USD"),technical_approved=False)]
    doc=capture(self.root,self.policy,rows,{"BTC-USD":hist(),"ETH-USD":hist("ETH-USD")},
                {},{},selected="BTC-USD",now=NOW)
    self.assertEqual(doc["new_candidates"],2)
    obs=summary(self.root,"acct")
    self.assertEqual(obs["tracked_candidates"],2)
    self.assertEqual({r["symbol"] for r in obs["candidates"]},{"BTC-USD","ETH-USD"})
    self.assertTrue(all(r["shadow_result"] for r in obs["candidates"]))
    self.assertEqual({r["selection"] for r in obs["candidates"]},
                     {"WORKER_PRIMARY_CANDIDATE","NOT_SELECTED_OR_LOWER_RANK"})
 def test_quote_followup_measures_favorable_and_adverse_without_fills(self):
    capture(self.root,self.policy,[signal()],{"BTC-USD":hist()}, {}, {},now=NOW)
    good=dict(signal(),diagnostic_bid="105",diagnostic_ask="105.1",technical_approved=False,
              at=(NOW+timedelta(minutes=10)).isoformat())
    bad=dict(signal(),diagnostic_bid="95",diagnostic_ask="95.1",technical_approved=False,
             at=(NOW+timedelta(minutes=20)).isoformat())
    capture(self.root,self.policy,[good],{}, {}, {},now=NOW+timedelta(minutes=10))
    capture(self.root,self.policy,[bad],{}, {}, {},now=NOW+timedelta(minutes=20))
    evidence=summary(self.root,"acct")["candidates"][0]
    self.assertAlmostEqual(evidence["mfe_gross_pct"],5,places=3)
    self.assertAlmostEqual(evidence["mae_gross_pct"],-5,places=3)
    self.assertEqual(evidence["samples"],3)
    self.assertLess(evidence["last_hypothetical_net_pct"],-5)
    self.assertIn("HYPOTHETICAL",evidence["quote_venue"]+" "+evidence["shadow_reason"]+
      " HYPOTHETICAL")
 def test_missing_quotes_do_not_invent_excursions(self):
    capture(self.root,self.policy,[signal()],{"BTC-USD":hist()}, {}, {},now=NOW)
    row=summary(self.root,"acct")["candidates"][0]
    self.assertIsNone(row["mfe_gross_pct"])
    self.assertIsNone(row["mae_gross_pct"])
    self.assertEqual(row["samples"],1)
 def test_shadow_only_dip_filter_does_not_authorize_trade(self):
    candidate=signal(bid="103.98",ask="104.00")
    outcome,reason=shadow_signal(candidate,hist(),
       buy_fee=__import__("decimal").Decimal("0.95"),
       sell_fee=__import__("decimal").Decimal("0.95"))
    self.assertIn(outcome,("SHADOW_PASS_REBOUND","SHADOW_REJECT_REWARD_AFTER_FEES",
                            "SHADOW_REJECT_NOT_RISING"))
    self.assertNotIn("ai_approved",{"shadow_result":outcome})
 def test_shadow_rejects_momentum_chase_and_expensive_spread(self):
    r=signal(momentum=1.9)
    outcome,_=shadow_signal(r,hist(),__import__("decimal").Decimal("0.95"),
                            __import__("decimal").Decimal("0.95"))
    self.assertEqual(outcome,"SHADOW_REJECT_CHASE")
    r["momentum_pct"]=0.8;r["diagnostic_bid"]="98"
    outcome,_=shadow_signal(r,hist(),__import__("decimal").Decimal("0.95"),
                            __import__("decimal").Decimal("0.95"))
    self.assertEqual(outcome,"SHADOW_REJECT_SPREAD")
 def test_true_broker_bid_position_excursions_are_separate(self):
    at=NOW-timedelta(minutes=10)
    p={"BTC-USD":{"cost_basis_verified":True,"quantity":2,
       "average_unit_cost":"100","opened_at":at.isoformat()}}
    capture(self.root,self.policy,[],{},p,{"BTC-USD":__import__("decimal").Decimal("102")},now=NOW)
    capture(self.root,self.policy,[],{},p,{"BTC-USD":__import__("decimal").Decimal("95")},now=NOW+timedelta(minutes=1))
    item=summary(self.root,"acct")["positions"][0]
    self.assertGreater(item["mfe_estimated_net_pct"],0)
    self.assertLess(item["mae_estimated_net_pct"],-5)
    self.assertEqual(item["samples"],2)
 def test_position_cost_change_resets_incomparable_excursions(self):
    at=NOW-timedelta(minutes=5)
    p={"BTC-USD":{"cost_basis_verified":True,"quantity":1,
       "average_unit_cost":"100","opened_at":at.isoformat()}}
    capture(self.root,self.policy,[],{},p,{"BTC-USD":__import__("decimal").Decimal("110")},now=NOW)
    p["BTC-USD"]["average_unit_cost"]="106";p["BTC-USD"]["quantity"]=2
    capture(self.root,self.policy,[],{},p,{"BTC-USD":__import__("decimal").Decimal("104")},now=NOW+timedelta(minutes=1))
    item=summary(self.root,"acct")["positions"][0]
    self.assertEqual(item["samples"],1)
    self.assertIn("COST_BASIS_CHANGED",item["coverage"])
 def test_exact_exit_reason_and_verified_fee_are_keyed_to_order_id(self):
    at=NOW-timedelta(minutes=15)
    self.write_orders([filled("client-buy-abcdef","buy","BTC-USD",2,100,1.9,at),
       filled("client-sell-abcdef","sell","BTC-USD",1,98,0.93,NOW)])
    capture(self.root,self.policy,[],{}, {}, {},
       submit_note={"client_order_id":"client-sell-abcdef","symbol":"BTC-USD",
                    "side":"sell","reason":"STOP_LOSS"},now=NOW)
    exit=summary(self.root,"acct")["exits"][0]
    self.assertEqual(exit["exit_reason"],"STOP_LOSS")
    self.assertEqual(exit["verified_fee_usd"],"0.93")
    self.assertAlmostEqual(float(exit["verified_net_realized_pnl_usd"]),-3.88)
    self.assertEqual(exit["holding_minutes"],15)
    self.assertIsNone(exit["mfe_sampled_net_pct"])
 def test_unverified_fee_keeps_net_pnl_unavailable(self):
    self.write_orders([filled("client-buy-abcdef","buy","BTC-USD",1,100,0.95,verified=False),
       filled("client-sell-abcdef","sell","BTC-USD",1,110,1.05)])
    capture(self.root,self.policy,[],{}, {}, {},now=NOW)
    exit=summary(self.root,"acct")["exits"][0]
    self.assertIsNone(exit["verified_net_realized_pnl_usd"])
    self.assertIn("UNAVAILABLE",exit["coverage"])
 def test_account_scoped_views_never_mix_other_accounts(self):
    self.write_orders([filled("client-other-buy","buy","BTC-USD",1,100,1,account="other"),
       filled("client-other-sell","sell","BTC-USD",1,150,1,account="other")])
    capture(self.root,self.policy,[signal()],{"BTC-USD":hist()}, {}, {},now=NOW)
    self.assertEqual(len(summary(self.root,"acct")["exits"]),0)
    self.assertEqual(len(summary(self.root,"other")["candidates"]),0)
 def test_xlsx_adds_two_diagnostic_tabs_and_keeps_original(self):
    capture(self.root,self.policy,[signal()],{"BTC-USD":hist()}, {}, {},now=NOW)
    blob=build_robinhood_performance_workbook(self.root)
    with ZipFile(io.BytesIO(blob)) as z:
        names=set(z.namelist())
        self.assertIn("xl/worksheets/sheet12.xml",names)
        workbook=z.read("xl/workbook.xml").decode()
        self.assertIn("Fee-adjusted Candidates",workbook)
        self.assertIn("Execution Diagnostics",workbook)
        self.assertIn("Trade Ledger",workbook)
        self.assertIn("SHADOW",z.read("xl/worksheets/sheet11.xml").decode())
 def test_report_can_be_exported_before_new_samples(self):
    blob=build_robinhood_performance_workbook(self.root)
    with ZipFile(io.BytesIO(blob)) as z:
        self.assertIn("xl/worksheets/sheet12.xml",z.namelist())
 def test_older_outcomes_without_direct_reason_stay_unknown(self):
    self.write_orders([filled("client-buy-abcdef","buy","BTC-USD",1,100,0.95),
      filled("client-sell-abcdef","sell","BTC-USD",1,110,1.05)])
    capture(self.root,self.policy,[],{}, {}, {},now=NOW)
    r=summary(self.root,"acct")["exits"][0]
    self.assertIn("UNKNOWN",r["exit_reason"])
    self.assertGreater(r["net_return_pct"],0)

if __name__=="__main__":unittest.main()

class DiagnosticsHTTPSecurityTests(ShadowTests):
 def test_endpoint_requires_existing_authenticated_session(self):
    import threading
    from http.server import ThreadingHTTPServer
    from urllib.request import urlopen
    from urllib.error import HTTPError
    import dashboard_server
    from dashboard_server import Handler
    capture(self.root,self.policy,[signal()],{"BTC-USD":hist()}, {}, {},now=NOW)
    srv=ThreadingHTTPServer(("127.0.0.1",0),Handler)
    thread=threading.Thread(target=srv.serve_forever,daemon=True)
    thread.start()
    self.addCleanup(srv.server_close)
    self.addCleanup(srv.shutdown)
    url=f"http://127.0.0.1:{srv.server_port}/api/robinhood/strategy-diagnostics"
    with patch.object(dashboard_server,"STATE_DIR",self.root),patch.object(dashboard_server,"UNIFIED_APP",True):
       with self.assertRaises(HTTPError) as blocked:
          urlopen(url,timeout=5)
       self.assertEqual(blocked.exception.code,401)
       with patch.object(Handler,"_nonce",return_value="fake-signed-in-test-session"):
          with urlopen(url,timeout=5) as response:
             doc=json.loads(response.read())
             self.assertEqual(response.status,200)
             self.assertEqual(response.headers["Cache-Control"],"no-store")
             self.assertTrue(doc["shadow_only"])
             self.assertEqual(doc["tracked_candidates"],1)
             self.assertNotIn("client_order_id",str(doc))
 def test_no_model_or_live_order_access_in_shadow_module(self):
    source=(Path(__file__).parent/"robinhood_strategy_diagnostics.py").read_text()
    self.assertNotIn("submit_approved(",source)
    self.assertNotIn("submit_order(",source)
    self.assertNotIn("approve_entry(",source)
 def test_repeated_cycles_do_not_duplicate_broker_fills(self):
    self.write_orders([filled("client-buy-abcdef","buy","BTC-USD",2,100,1.9),
      filled("client-sell-abcdef","sell","BTC-USD",1,98,0.93)])
    for i in range(3):
       capture(self.root,self.policy,[],{}, {}, {},now=NOW+timedelta(minutes=i))
    with connect(self.root) as db:
       rows=db.execute("SELECT COUNT(*) FROM filled_outcomes").fetchone()[0]
       self.assertEqual(rows,2)
 def test_sample_window_expiry_never_claims_late_maximum(self):
    capture(self.root,self.policy,[signal()],{"BTC-USD":hist()}, {}, {},now=NOW)
    newer=dict(signal(),technical_approved=False,
      diagnostic_bid="150",diagnostic_ask="150.1")
    capture(self.root,self.policy,[newer],{}, {}, {},now=NOW+timedelta(minutes=70))
    item=summary(self.root,"acct")["candidates"][0]
    self.assertIsNone(item["mfe_gross_pct"])

 def test_coinbase_shadow_requires_independent_robinhood_spread(self):
    from decimal import Decimal
    r=signal(source="COINBASE_WS")
    verdict,_=shadow_signal(r,hist(),Decimal("0.95"),Decimal("0.95"))
    self.assertEqual(verdict,"SHADOW_REJECT_BROKER_SPREAD_UNVERIFIED")
    r["broker_spread_pct"]=0.49
    verdict,_=shadow_signal(r,hist(),Decimal("0.95"),Decimal("0.95"))
    self.assertEqual(verdict,"SHADOW_REJECT_SPREAD")
 def test_fees_never_turn_a_losing_price_move_profitable(self):
    from decimal import Decimal
    r=signal()
    capture(self.root,self.policy,[r],{"BTC-USD":hist()}, {}, {},now=NOW)
    down=dict(r,technical_approved=False,diagnostic_bid="99.00",
              diagnostic_ask="99.03")
    capture(self.root,self.policy,[down],{}, {}, {},now=NOW+timedelta(minutes=4))
    item=summary(self.root,"acct")["candidates"][0]
    self.assertLess(item["last_hypothetical_net_pct"],-1)
    self.assertLess(item["mae_hypothetical_net_pct"],-1)

 def test_timely_60_minute_hypothetical_mark(self):
    capture(self.root,self.policy,[signal()],{"BTC-USD":hist()}, {}, {},now=NOW)
    next_quote=dict(signal(),technical_approved=False,
       diagnostic_bid="103.00",diagnostic_ask="103.03")
    capture(self.root,self.policy,[next_quote],{}, {}, {},
       now=NOW+timedelta(minutes=60))
    c=summary(self.root,"acct")["candidates"][0]
    self.assertEqual(c["horizon_status"],"OBSERVED_60M_PLUS_MINUS_5M")
    self.assertIsNotNone(c["horizon_hypothetical_net_pct"])
    self.assertLess(c["horizon_hypothetical_net_pct"],3)
 def test_stale_horizon_never_fabricates_final_net_return(self):
    capture(self.root,self.policy,[signal()],{"BTC-USD":hist()}, {}, {},now=NOW)
    late=dict(signal(),technical_approved=False,
       diagnostic_bid="120.00",diagnostic_ask="120.02")
    capture(self.root,self.policy,[late],{}, {}, {},
       now=NOW+timedelta(minutes=70))
    c=summary(self.root,"acct")["candidates"][0]
    self.assertEqual(c["horizon_status"],"EXPIRED_NO_TIMELY_SAME_VENUE_QUOTE")
    self.assertIsNone(c["horizon_hypothetical_net_pct"])
