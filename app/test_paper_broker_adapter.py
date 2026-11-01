import tempfile,unittest
from pathlib import Path
from paper_broker_adapter import PaperBrokerAdapter
class PaperAccountAdapterTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory()
  self.addCleanup(self.temp.cleanup)
  self.adapter=PaperBrokerAdapter(self.temp.name,
   quote_provider=lambda symbol:{"symbol":symbol,"price":10.0,
       "timestamp":"2026-11-01T19:30:00+00:00"})
 def test_buy_sell_state_and_idempotency(self):
  ref="paper-primary"
  buy={"symbol":"SPY","side":"BUY","quantity":2,"client_order_id":"buy-1"}
  entry=self.adapter.submit_order(ref,buy)
  self.assertEqual(entry["status"],"FILLED_SIMULATED")
  self.assertEqual(self.adapter.balances(ref)["cash"],"80.00")
  self.assertEqual(len(self.adapter.orders(ref)),1)
  self.assertEqual(self.adapter.submit_order(ref,buy),entry)
  self.assertEqual(len(self.adapter.orders(ref)),1)
  sell={"symbol":"SPY","side":"SELL","quantity":2,"client_order_id":"sell-1"}
  self.adapter.submit_order(ref,sell)
  self.assertEqual(self.adapter.positions(ref),[])
  self.assertEqual(self.adapter.balances(ref)["cash"],"100.00")
  self.assertTrue((Path(self.temp.name)/"paper_account.json").is_file())
 def test_cannot_buy_beyond_cash(self):
  with self.assertRaises(ValueError):
   self.adapter.submit_order("paper-primary",{
    "symbol":"SPY","side":"BUY","quantity":20,"client_order_id":"too-big"})
 def test_no_short_or_unknown_account(self):
  with self.assertRaises(ValueError):
   self.adapter.submit_order("paper-primary",{
    "symbol":"SPY","side":"SELL","quantity":1,"client_order_id":"short"})
  with self.assertRaises(Exception):self.adapter.balances("schwab")
if __name__=="__main__":unittest.main()
