import tempfile,unittest
from datetime import datetime,timezone
from robinhood_order_pass import review_sell,submit_sell_approved,OrderPassBlocked
from robinhood_order_journal import OrderJournal
from uuid import uuid4
class Fake:
 def __init__(self):self.writes=[]
 def list_accounts(self):
  return [{"account_number":"acct","status":"active","is_api_tradable":True}]
 def orders(self,account):return []
 def trading_pairs(self):
  return [{"symbol":"BTC-USD","is_api_tradable":True,"min_order_amount":"1",
           "asset_increment":"0.001","max_order_size":"100"}]
 def positions(self,account):
  return [{"asset_code":"BTC","total_quantity":"2",
           "quantity_available_for_trading":"2"}]
 def quote(self,symbol):
  return {"results":[{"symbol":symbol,"bid":"9.99","ask":"10"}]}
 def submit_order(self,account,intent):
  self.writes.append(intent);return {"id":"broker-ack"}
class SellTests(unittest.TestCase):
 def setUp(self):
  self.at=datetime(2026,11,3,0,tzinfo=timezone.utc)
  self.policy={"enabled":True,"account":"acct","max_order_usd":"5"}
  self.signal={"technical_exit":True,"at":self.at.isoformat(),"symbol":"BTC-USD"}
 def test_sell_existing_only_and_journal(self):
  with tempfile.TemporaryDirectory() as d:
   j=OrderJournal(d);prior=str(uuid4())
   j.record_intent("acct",prior,"BTC-USD","2","10",side="buy")
   j.reconcile("acct",[{"client_order_id":prior,"state":"filled",
                       "filled_asset_quantity":"2"}])
   f=Fake()
   out=submit_sell_approved(d,f,self.policy,self.signal,self.at)
   self.assertTrue(out["broker_acknowledged"])
   self.assertFalse(out["fill_verified"])
   self.assertEqual(f.writes[0]["side"],"sell")
   self.assertLessEqual(float(f.writes[0]["asset_quantity"]),2)
   with self.assertRaises(OrderPassBlocked):
    submit_sell_approved(d,f,self.policy,self.signal,self.at)
 def test_cannot_sell_unowned(self):
  with tempfile.TemporaryDirectory() as d:
   f=Fake();f.positions=lambda account:[]
   with self.assertRaises(OrderPassBlocked):review_sell(d,f,self.policy,self.signal,self.at)
   self.assertFalse(f.writes)
 def test_cannot_sell_below_exchange_min(self):
  with tempfile.TemporaryDirectory() as d:
   f=Fake();f.positions=lambda account:[{"asset_code":"BTC","quantity_available_for_trading":"0.001"}]
   with self.assertRaises(OrderPassBlocked):review_sell(d,f,self.policy,self.signal,self.at)
 def test_cannot_sell_when_disabled(self):
  with tempfile.TemporaryDirectory() as d:
   f=Fake();self.policy["enabled"]=False
   with self.assertRaises(OrderPassBlocked):review_sell(d,f,self.policy,self.signal,self.at)
