import tempfile,unittest
from datetime import datetime,timezone,timedelta
from robinhood_order_pass import review_order,submit_approved,OrderPassBlocked
from robinhood_order_journal import OrderJournal
from uuid import uuid4

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
 def fill(self,journal,side,symbol,qty,price,when):
  oid=str(uuid4())
  journal.record_intent("a",oid,symbol,str(qty),str(price),side=side)
  journal.reconcile("a",[{"client_order_id":oid,"state":"filled",
    "filled_asset_quantity":str(qty),"average_price":str(price),
    "fee_charged":"0","updated_at":when.isoformat()}])
  return oid
 def test_daily_realized_loss_blocks_new_buy(self):
  with tempfile.TemporaryDirectory() as d:
   j=OrderJournal(d)
   self.fill(j,"buy","BTC-USD","1","10",self.now-timedelta(hours=2))
   self.fill(j,"sell","BTC-USD","1","8",self.now-timedelta(hours=1))
   self.policy.update({"max_daily_loss_usd":"1","reentry_cooldown_minutes":0})
   with self.assertRaisesRegex(OrderPassBlocked,"Daily realized loss limit reached"):
    review_order(d,Fake(),self.policy,self.signal,self.now)
 def test_total_exposure_blocks_new_buy(self):
  with tempfile.TemporaryDirectory() as d:
   j=OrderJournal(d)
   self.fill(j,"buy","ETH-USD","2","10",self.now-timedelta(hours=1))
   self.policy.update({"max_total_exposure_usd":"20","max_open_positions":3})
   with self.assertRaisesRegex(OrderPassBlocked,"Maximum bot crypto exposure"):
    review_order(d,Fake(),self.policy,self.signal,self.now)
 def test_open_position_limit_blocks_new_symbol(self):
  with tempfile.TemporaryDirectory() as d:
   j=OrderJournal(d)
   for symbol in ("ETH-USD","SOL-USD","DOGE-USD"):
    self.fill(j,"buy",symbol,"0.1","10",self.now-timedelta(hours=1))
   self.policy.update({"max_open_positions":3,"max_total_exposure_usd":"250"})
   with self.assertRaisesRegex(OrderPassBlocked,"Maximum bot open positions"):
    review_order(d,Fake(),self.policy,self.signal,self.now)
 def test_reentry_cooldown_blocks_churn(self):
  with tempfile.TemporaryDirectory() as d:
   j=OrderJournal(d)
   self.fill(j,"buy","BTC-USD","1","9",self.now-timedelta(hours=1))
   self.fill(j,"sell","BTC-USD","1","10",self.now-timedelta(minutes=10))
   self.policy.update({"reentry_cooldown_minutes":30,"max_daily_loss_usd":"5"})
   with self.assertRaisesRegex(OrderPassBlocked,"Re-entry cooldown"):
    review_order(d,Fake(),self.policy,self.signal,self.now)
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
