"""Regressions for Webull's SDK 429 and Robinhood history outage safety."""
import json,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
from datetime import datetime,timezone
from robinhood_worker import run_once
from robinhood_crypto_gateway import RobinhoodUnavailable
from webull_openapi import _portfolio_read_broker,portfolio
from broker_workspace import robinhood_status

class RobinhoodHistoryOutageTests(unittest.TestCase):
 def test_order_history_failure_retains_journal_and_never_submits(self):
  class Broker:
   def list_accounts(self):
    return [{"account_number":"demo","status":"active","is_api_tradable":True,
             "buying_power":"25.00","buying_power_currency":"USD"}]
   def trading_pairs(self):
    return [{"symbol":"BTC-USD","quote_code":"USD","is_api_tradable":True}]
   def quote(self,symbol):
    return {"results":[{"symbol":symbol,"bid":"100","ask":"100.1"}]}
   def orders(self,account):raise RobinhoodUnavailable("broker history unavailable")
   def submit_order(self,*a):raise AssertionError("should not place an order")
   def order(self,*a):raise AssertionError("should not call order")
  with tempfile.TemporaryDirectory() as td:
   p=Path(td)/"robinhood"/"order_intents.json"
   p.parent.mkdir()
   original={"version":1,"orders":[{"account":"demo","client_order_id":"prior",
      "symbol":"BTC-USD","side":"buy","status":"filled","filled_quantity":"1",
      "average_fill_price":"100","fee_charged":"0",
      "filled_at":"2026-11-18T12:00:00+00:00"}]}
   p.write_text(json.dumps(original))
   with patch("local_ai_gateway.installed_models",return_value=[]),patch("local_ai_gateway._settings",return_value=(None,"test-model")):
    result=run_once(td,Broker())
   self.assertEqual(result["worker"],"monitoring_degraded")
   self.assertEqual(result["execution_status"],"BROKER_HISTORY_UNAVAILABLE")
   self.assertEqual(result["broker_order_history_status"],"UNAVAILABLE")
   self.assertEqual(result["risk_check"],"BLOCKED_BROKER_HISTORY_UNAVAILABLE")
   self.assertFalse(result["live_orders_allowed"])
   self.assertEqual(json.loads(p.read_text()),original)
   reported=json.loads((Path(td)/"robinhood"/"worker_status.json").read_text())
   self.assertEqual(reported["execution_status"],"BROKER_HISTORY_UNAVAILABLE")

 def test_status_reports_scanner_degraded_not_offline(self):
  class Broker:
   def list_accounts(self):return [{"account_number":"demo","status":"active",
      "is_api_tradable":True,"buying_power":"10","buying_power_currency":"USD"}]
  with tempfile.TemporaryDirectory() as td:
   state=Path(td);(state/"robinhood").mkdir();(state/"config").mkdir()
   (state/"config"/"robinhood_crypto.json").write_text("private-file-placeholder")
   (state/"robinhood"/"risk_policy.json").write_text(json.dumps({"enabled":True}))
   (state/"robinhood"/"worker_status.json").write_text(json.dumps({
    "worker":"monitoring_degraded","broker_order_history_status":"UNAVAILABLE",
    "execution_status":"BROKER_HISTORY_UNAVAILABLE","updated_at":datetime.now(timezone.utc).isoformat(),
    "risk_check":"BLOCKED_BROKER_HISTORY_UNAVAILABLE","live_orders_allowed":False}))
   with patch("broker_workspace._robinhood_client",return_value=Broker()),patch("broker_workspace._pending_order_diagnostics",return_value=[]):
    x=robinhood_status(td)
   self.assertEqual(x["effective_state"],"BROKER_HISTORY_UNAVAILABLE")
   self.assertTrue(x["worker_fresh"])
   self.assertFalse(x["worker"]["live_orders_allowed"])

class WebullDashboardQuotaTests(unittest.TestCase):
 def test_sdk_read_cache_reuses_client_but_not_after_key_rotation(self):
  class Broker:
   init_count=0
   def __init__(self,path):
    Broker.init_count+=1;self.environment="production"
   def verify_account(self,account):return {"account_id":account}
   def balance(self,account):return {"total_asset_currency":"USD"}
   def positions(self,account):return []
  with tempfile.TemporaryDirectory() as td:
   path=Path(td)/"config";path.mkdir()
   cred=path/"webull_openapi.json";cred.write_text("credential-placeholder")
   with patch("webull_broker.WebullBroker",Broker):
    a=portfolio(td,"verified")
    b=portfolio(td,"verified")
    self.assertEqual(Broker.init_count,1)
    self.assertEqual(a["execution_enabled"],False)
    self.assertEqual(b["execution_enabled"],False)
    time.sleep(.015)
    cred.write_text("rotated-placeholder")
    portfolio(td,"verified")
    self.assertEqual(Broker.init_count,2)

if __name__=="__main__":unittest.main()
