import tempfile,unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path
from dashboard_control import write_atomic,default_control
from paper_account_runtime import paper_tick
from paper_broker_adapter import PaperBrokerAdapter

class PaperSharedStrategyTests(unittest.TestCase):
 def setUp(self):
  self.root=tempfile.TemporaryDirectory()
  self.addCleanup(self.root.cleanup)
  self.now=datetime(2026,11,2,16,0,tzinfo=timezone.utc)
  c=default_control();c["mode"]="running"
  write_atomic(Path(self.root.name)/"control.json",c)
 def test_identical_strategy_paper_fill(self):
  when=int(self.now.timestamp()*1000)
  q={"quote":{"bidPrice":10.95,"askPrice":11.0,"quoteTime":when,
              "totalVolume":1000000,"netPercentChange":0},
     "assetMainType":"EQUITY"}
  candles=[{"datetime":when-300000*(6-i)-120000,"close":v}
           for i,v in enumerate([10,9,8,7,8,11])]
  class R:
   status_code=200
   def __init__(self,value):self.value=value
   def json(self):return self.value
  class FakeMarket:
   def get_quotes(self,symbols):
    return R({sym:q for sym in symbols if sym=="F"})
   def get_price_history_every_five_minutes(self,symbol,need_extended_hours_data=False):
    return R({"candles":candles})
  result=paper_tick(FakeMarket(),self.root.name,self.now,
             approve=lambda sym,when:(True,"fixture approval"))
  self.assertEqual(result["decision"],"PAPER_BUY")
  a=PaperBrokerAdapter(self.root.name)
  self.assertEqual(len(a.orders(a.account_ref)),1)
  self.assertEqual(a.orders(a.account_ref)[0]["symbol"],"F")
  self.assertTrue(a.balances(a.account_ref)["paper_only"])
 def test_stopped_does_not_read_market(self):
  c=default_control();write_atomic(Path(self.root.name)/"control.json",c)
  class Broken:
   def get_quotes(self,symbols):raise AssertionError("Unexpected feed")
  self.assertEqual(paper_tick(Broken(),self.root.name,self.now)["decision"],"PAUSED")
