"""Full mocked worker cycle for take-profit and trailing, never submits real orders."""
import json,tempfile,unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path
from decimal import Decimal
from unittest.mock import patch
from robinhood_order_journal import OrderJournal
from robinhood_exit_tracker import ExitTracker
from robinhood_worker import run_once

class FakeBroker:
 def __init__(self,price):
  self.price=Decimal(str(price));self.submissions=[]
 def list_accounts(self):
  return [{"account_number":"acct","status":"active","is_api_tradable":True,
           "buying_power":"100","buying_power_currency":"USD"}]
 def trading_pairs(self):
  return [{"symbol":"BTC-USD","asset_code":"BTC","quote_code":"USD",
           "is_api_tradable":True,"min_order_amount":"0.1",
           "asset_increment":"0.001","max_order_size":"100"}]
 def quote(self,symbol):
  bid=self.price;ask=bid+Decimal("0.01")
  return {"results":[{"symbol":symbol,"bid":str(bid),"ask":str(ask)}]}
 def orders(self,account):return []
 def positions(self,account):
  return [{"asset_code":"BTC","total_quantity":"2",
           "quantity_available_for_trading":"2"}]
 def submit_order(self,account,intent):
  self.submissions.append(dict(intent))
  return {"id":"mock-ack-id"}

class WorkerProfitTests(unittest.TestCase):
 def scenario(self,current_bid,previous_peak=None):
  now=datetime.now(timezone.utc)
  with tempfile.TemporaryDirectory() as root:
   folder=Path(root)/"robinhood";folder.mkdir()
   (folder/"risk_policy.json").write_text(json.dumps({
     "enabled":True,"account":"acct","max_order_usd":"5",
     "max_total_exposure_usd":"25","max_daily_loss_usd":"5",
     "max_open_positions":3,"verified_broker_minimum_usd":"0.1",
     "min_hold_minutes":15,"min_profit_pct":"1","stop_loss_pct":"2",
     "fee_buffer_pct":"0.25","take_profit_pct":"3",
     "trailing_activation_pct":"2","trailing_drawdown_pct":"0.75",
     "max_single_asset_exposure_pct":"60","min_add_interval_minutes":30}))
   journal=OrderJournal(root)
   journal.record_intent("acct","old-filled-buy","BTC-USD","2","10")
   journal.reconcile("acct",[{"client_order_id":"old-filled-buy","state":"filled",
      "filled_asset_quantity":"2","average_price":"10","fee_charged":"0.19",
      "updated_at":(now-timedelta(minutes=40)).isoformat()}])
   if previous_peak:
    ExitTracker(root).update("acct",journal.positions(),{"BTC-USD":Decimal(str(previous_peak))})
   broker=FakeBroker(current_bid)
   with patch("robinhood_crypto_execution.RobinhoodCryptoTradingAdapter.from_state_authorized",return_value=broker),\
        patch("local_ai_gateway.installed_models",return_value=["qwen3.5:9b"]):
    result=run_once(root,broker)
   self.assertEqual(len(broker.submissions),1)
   self.assertEqual(broker.submissions[0]["symbol"],"BTC-USD")
   self.assertEqual(broker.submissions[0]["side"],"sell")
   self.assertIn(result["execution_status"],("SELL_ORDER_ACCEPTED","SELL_SUBMITTED_UNCONFIRMED"))
   self.assertFalse(result["last_order_confirmed"])
   self.assertEqual(len(journal.pending()),1)
   self.assertEqual(result["exit_peak_state"],"PERSISTED")
   self.assertEqual(result["exit_fee_buffer_source"],"broker_fill_history")
   self.assertEqual(result["exit_fee_buffer_pct"],"0.997500")
   return result
 def test_take_profit_triggers_actual_worker_sell_path(self):
  result=self.scenario("10.60")
  self.assertIn("TAKE_PROFIT",result["execution_reason"])
  self.assertEqual(result["exit_position_status"][0]["status"],"TAKE_PROFIT")
 def test_trailing_eligible_triggers_actual_worker_sell_path(self):
  result=self.scenario("10.41",previous_peak="10.50")
  self.assertIn("TRAILING_PROFIT",result["execution_reason"])
  self.assertEqual(result["exit_position_status"][0]["status"],"TRAILING_PROFIT")
if __name__=="__main__":unittest.main()
