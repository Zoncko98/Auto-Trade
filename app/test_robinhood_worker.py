import tempfile,unittest
from pathlib import Path
from robinhood_worker import run_once
class WorkerTests(unittest.TestCase):
 def test_read_only_monitor(self):
  class Fake:
   def list_accounts(self):
    return [{"status":"active","is_api_tradable":True,"buying_power":"1.86","buying_power_currency":"USD"}]
   def quote(self,symbol):return {"results":[{"symbol":symbol}]}
   def submit_order(self,*args):raise AssertionError("No live orders!")
  with tempfile.TemporaryDirectory() as d:
   result=run_once(d,Fake())
   self.assertEqual(result["quotes_checked"],4)
   self.assertFalse(result["live_orders_allowed"])
   self.assertFalse(result["last_order_confirmed"])
   self.assertTrue((Path(d)/"robinhood"/"worker_status.json").is_file())
