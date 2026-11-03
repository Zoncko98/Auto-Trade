"""Full worker-to-signed-adapter mock lifecycle without touching Robinhood."""
import json,tempfile,unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path
from unittest.mock import patch
from robinhood_worker import run_once
from robinhood_order_journal import OrderJournal
from uuid import uuid4

class SimulatedBroker:
 def __init__(self):self.submissions=[]
 def list_accounts(self):
  return [{"account_number":"acct","status":"active","is_api_tradable":True,
           "buying_power_currency":"USD","buying_power":"20"}]
 def trading_pairs(self):
  return [{"symbol":"BTC-USD","asset_code":"BTC","quote_code":"USD",
           "is_api_tradable":True,"min_order_amount":"1",
           "asset_increment":"0.001","max_order_size":"100"}]
 def quote(self,symbol):
  return {"results":[{"symbol":symbol,"bid":"9.99","ask":"10.00"}]}
 def orders(self,account):return []
 def positions(self,account):
  return [{"asset_code":"BTC","total_quantity":"2",
           "quantity_available_for_trading":"2"}]
 def submit_order(self,account,intent):
  self.submissions.append(dict(intent))
  return {"id":"synthetic-broker-ack"}

class FullWorkerExecutionTests(unittest.TestCase):
 def scenario(self,rising):
  broker=SimulatedBroker()
  now=datetime.now(timezone.utc)
  prices=["9.88","9.92","9.95"] if rising else ["10.15","10.10","10.05"]
  with tempfile.TemporaryDirectory() as tmp:
   path=Path(tmp)/"robinhood";path.mkdir()
   (path/"risk_policy.json").write_text(json.dumps({
    "enabled":True,"account":"acct","max_order_usd":"5",
    "verified_broker_minimum_usd":"1"}))
   if not rising:
    j=OrderJournal(tmp);prior=str(uuid4())
    j.record_intent("acct",prior,"BTC-USD","2","10",side="buy")
    j.reconcile("acct",[{"client_order_id":prior,"state":"filled",
                         "filled_asset_quantity":"2"}])
   (path/"quote_history.json").write_text(json.dumps([
    {"symbol":"BTC-USD","mid":mid,
     "at":(now-timedelta(seconds=elapsed)).isoformat()}
    for mid,elapsed in zip(prices,[400,260,130])]))
   with patch("robinhood_crypto_execution.RobinhoodCryptoTradingAdapter.from_state_authorized",return_value=broker),        patch("local_ai_gateway.installed_models",return_value=["qwen3.5:9b"]),        patch("ai_research.approve_entry",return_value=(True,"Validated AI news approval")),        patch("ai_research.research_evidence",return_value={"model":"qwen3.5:9b"}):
    result=run_once(tmp,broker)
    self.assertEqual(result["universe_size"],1)
    self.assertEqual(result["quotes_checked"],1)
    self.assertEqual(len(broker.submissions),1)
    self.assertEqual(result["pending_order_intents"],1)
    self.assertFalse(result["last_order_confirmed"])
    self.assertTrue(OrderJournal(tmp).pending())
    first_side=broker.submissions[0]["side"]
    self.assertEqual(first_side,"buy" if rising else "sell")
    second=run_once(tmp,broker)
    self.assertEqual(len(broker.submissions),1)
    self.assertTrue(OrderJournal(tmp).pending())
   return result
 def test_buy_approval_to_signed_adapter(self):
  result=self.scenario(True)
  self.assertEqual(result["execution_status"],"ORDER_ACCEPTED")
 def test_sell_existing_holding_to_signed_adapter(self):
  result=self.scenario(False)
  self.assertEqual(result["execution_status"],"SELL_ORDER_ACCEPTED")
