import unittest
from datetime import datetime,timezone
from shadow_momentum import shadow_scan

class ShadowTest(unittest.TestCase):
 def test_no_order_and_cost_check(self):
  now=datetime(2026,11,2,19,0,tzinfo=timezone.utc)
  t=int(now.timestamp()*1000)
  quote={"F":{"assetMainType":"EQUITY","quote":{"bidPrice":10,"askPrice":10.02,
    "quoteTime":t,"totalVolume":1000000,"netPercentChange":1}}}
  candles=[{"datetime":t-300000*(7-i),"close":v}
      for i,v in enumerate([9.9,9.94,9.96,9.98,10,10.04,10.08])]
  result=shadow_scan(quote,lambda symbol:candles,now)
  self.assertEqual(result["mode"],"SHADOW_ONLY")
  self.assertEqual(result["simulated_orders"],0)
  self.assertEqual(result["candidate"]["symbol"],"F")
 def test_no_momentum(self):
  now=datetime(2026,11,2,19,0,tzinfo=timezone.utc)
  t=int(now.timestamp()*1000)
  quote={"F":{"assetMainType":"EQUITY","quote":{"bidPrice":10,"askPrice":10.02,
    "quoteTime":t,"totalVolume":1000000,"netPercentChange":0}}}
  candles=[{"datetime":t-300000*(7-i),"close":10} for i in range(7)]
  result=shadow_scan(quote,lambda symbol:candles,now)
  self.assertIsNone(result["candidate"])
