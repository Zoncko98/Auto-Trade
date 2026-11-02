import tempfile,unittest
from datetime import datetime,timezone
from robinhood_order_pass import review_order,submit_approved,OrderPassBlocked

class Fake:
 def __init__(self):self.writes=[]
 def list_accounts(self):
  return [{"account_number":"a","status":"active","is_api_tradable":True,
           "buying_power_currency":"USD","buying_power":"20"}]
 def orders(self,account):return []
 def quote(self,symbol):
  return {"results":[{"symbol":symbol,"bid":"9.99","ask":"10.00"}]}
 def trading_pairs(self):
  return [{"symbol":"BTC-USD","is_api_tradable":True,
           "min_order_amount":"1","max_order_size":"100","asset_increment":"0.001"}]
 def submit_order(self,account,intent):
  self.writes.append(intent)
  return {"id":"broker-ack"}
class OrderPassTests(unittest.TestCase):
 def setUp(self):
  self.now=datetime(2026,11,2,21,0,tzinfo=timezone.utc)
  self.policy={"enabled":True,"account":"a","max_order_usd":"5",
                "verified_broker_minimum_usd":"1"}
  self.signal={"technical_approved":True,"ai_approved":True,
                "symbol":"BTC-USD","at":self.now.isoformat()}
 def test_approved_order_pass_records_before_submission(self):
  with tempfile.TemporaryDirectory() as d:
   f=Fake()
   x=submit_approved(d,f,self.policy,self.signal,self.now)
   self.assertTrue(x["broker_acknowledged"])
   self.assertFalse(x["fill_verified"])
   self.assertEqual(len(f.writes),1)
   with self.assertRaises(OrderPassBlocked):
    submit_approved(d,f,self.policy,self.signal,self.now)
 def test_no_ai_no_order(self):
  with tempfile.TemporaryDirectory() as d:
   f=Fake();self.signal["ai_approved"]=False
   with self.assertRaises(OrderPassBlocked):
    submit_approved(d,f,self.policy,self.signal,self.now)
   self.assertFalse(f.writes)
 def test_insufficient_budget(self):
  with tempfile.TemporaryDirectory() as d:
   f=Fake();f.list_accounts=lambda:[{"account_number":"a","status":"active",
     "is_api_tradable":True,"buying_power_currency":"USD","buying_power":"1.86"}]
   with self.assertRaises(Exception):
    review_order(d,f,self.policy,self.signal,self.now)
