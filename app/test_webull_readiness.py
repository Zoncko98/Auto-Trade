"""Webull capital-availability and explicit expansion confirmation regressions."""
import json,tempfile,unittest
from decimal import Decimal
from datetime import datetime,timezone
from pathlib import Path
from webull_worker import stock_buy_budget,WebullBlocked
from webull_stock_strategy import scan_webull_stock
from webull_trade_config import save as save_policy, WebullPolicyError
from webull_risk import save as save_risk,DEFAULT as RISK_DEFAULT
from test_webull_stock_mirror import BrokerFixture,NOW

class FundingTests(unittest.TestCase):
 def balance(self,market="0"):
  return {"total_asset_currency":"USD","total_net_liquidation_value":"140.13",
    "total_cash_balance":"91.21","total_market_value":market,
    "total_day_profit_loss":"-0.26","account_currency_assets":[
    {"currency":"USD","cash_balance":"91.21","settled_cash":"91.21"}]}
 def test_stock_budget_obeys_all_caps(self):
  x=stock_buy_budget(self.balance(),{"max_order_usd":80,"max_position_pct":10},"EQUITY")
  self.assertEqual(Decimal(x["max_new_stock_usd"]),Decimal("14.013"))
  self.assertEqual(x["status"],"BUDGET_AVAILABLE")
  self.assertIs(x["fractional_shares_allowed"],False)
 def test_existing_market_holdings_can_exhaust_cash_only_exposure(self):
  x=stock_buy_budget(self.balance("48.92"),{"max_order_usd":80,"max_position_pct":10},"EQUITY")
  self.assertEqual(x["max_new_stock_usd"],"0")
  self.assertEqual(x["status"],"EXPOSURE_OR_CASH_BUDGET_EXHAUSTED")
 def test_no_margin_debt_bypass(self):
  b=self.balance()
  b["used_margin"]="1.00"
  with self.assertRaises(WebullBlocked):stock_buy_budget(b,{"max_order_usd":80,"max_position_pct":10},"INDIVIDUAL_MARGIN")
 def test_whole_share_budget_filters_crossover_without_orders(self):
  broker=BrokerFixture()
  rows,candidate=scan_webull_stock(broker,["F"],NOW,max_buy_usd=Decimal("4"))
  self.assertIsNone(candidate)
  self.assertEqual(rows[0]["reason"],"WEBULL_STOCK_BUDGET_BELOW_WHOLE_SHARE")
  self.assertFalse([x for x in broker.calls if x[0]=="bars"])
  self.assertFalse(broker.orders)
  _,candidate=scan_webull_stock(BrokerFixture(),["F"],NOW,max_buy_usd=Decimal("5.19"))
  self.assertIsNotNone(candidate)

class DailyEvidenceTests(unittest.TestCase):
 def test_daily_rollup_retains_session_and_veto_counts(self):
  from webull_worker import _persist
  with tempfile.TemporaryDirectory() as td:
   report={"updated_at":"2026-11-12T15:20:00+00:00",
     "execution_status":"ARMED_NO_ORDER","execution_reason":"NO_QUALIFIED_STOCK",
     "signals":[{"asset":"EQUITY","reason":"WEBULL_MIRROR_NO_M5_ENTRY"},
                {"asset":"CRYPTO","reason":"No qualifying momentum"}],
     "market_readiness":{"stocks":{"candidates":0},"crypto":{"candidates":1}},
     "ai_reviews":[{"asset":"CRYPTO","approved":False}],
     "approved_candidates":[],"pending_orders":[]}
   _persist(td,report)
   summary=json.loads((Path(td)/"webull"/"scan_daily_summary.json").read_text())
   day=summary["2026-11-12"]
   self.assertEqual(day["stock_session_scans"],1)
   self.assertEqual(day["crypto_technical_candidate_cycles"],1)
   self.assertEqual(day["ai_rejected_cycles"],1)
   self.assertEqual(day["submission_cycles"] if "submission_cycles" in day else 0,0)
   self.assertEqual(day["execution_statuses"]["ARMED_NO_ORDER"],1)
   self.assertEqual(len(json.loads((Path(td)/"webull"/"decision_history.json").read_text())),1)
 def test_history_rollup_is_bounded_and_does_not_submit(self):
  from webull_worker import _persist
  with tempfile.TemporaryDirectory() as td:
   for i in range(124):
    _persist(td,{"updated_at":"2026-11-12T21:40:00+00:00",
      "execution_status":"ARMED_NO_ORDER","signals":[],
      "market_readiness":{"stocks":{"candidates":0},"crypto":{"candidates":0}}})
   recent=json.loads((Path(td)/"webull"/"decision_history.json").read_text())
   self.assertEqual(len(recent),120)
   summary=json.loads((Path(td)/"webull"/"scan_daily_summary.json").read_text())
   self.assertEqual(summary["2026-11-12"]["cycles"],124)

class PermissionTests(unittest.TestCase):
 def test_expanding_crypto_requires_fresh_explicit_authorization(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td)
   save_risk(root,dict(RISK_DEFAULT))
   accounts=[{"account_id":"stocks"},{"account_id":"crypto"}]
   existing={"enabled":True,"trade_stocks":True,"stock_account":"stocks",
     "trade_crypto":False,"crypto_account":""}
   with self.assertRaises(WebullPolicyError):
    save_policy(root,existing,accounts)
   self.assertTrue(save_policy(root,existing,accounts,"ENABLE_WEBULL_LIVE")["enabled"])
   wider=dict(existing,trade_crypto=True,crypto_account="crypto")
   with self.assertRaisesRegex(WebullPolicyError,"authorization"):
    save_policy(root,wider,accounts)
   self.assertFalse(save_policy(root,existing,accounts)["trade_crypto"])
   self.assertTrue(save_policy(root,wider,accounts,"ENABLE_WEBULL_LIVE")["trade_crypto"])
 def test_frontend_provides_confirmation_for_already_armed_scopes(self):
  source=(Path(__file__).resolve().parent.parent/"web"/"app.js").read_text()
  markup=(Path(__file__).resolve().parent.parent/"web"/"index.html").read_text()
  self.assertIn('webull-live-update',source)
  self.assertIn('webull-live-update',markup)
  self.assertIn('webull-stock-headroom',markup)
if __name__=="__main__":unittest.main()
