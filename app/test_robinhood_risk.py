import unittest
from robinhood_risk import preflight,RiskDenied

class RiskTests(unittest.TestCase):
 def setUp(self):
  self.account={"account_number":"a1","status":"active","is_api_tradable":True,
     "buying_power_currency":"USD","buying_power":"1.86"}
  self.policy={"enabled":True,"account":"a1","max_order_usd":"5",
               "verified_broker_minimum_usd":"1"}
 def test_small_account_respects_minimum(self):
  with self.assertRaisesRegex(RiskDenied,"insufficient"):
   preflight(self.account,self.policy,"BTC-USD","50000","0.1")
 def test_disabled_fails(self):
  self.policy["enabled"]=False
  with self.assertRaises(RiskDenied):
   preflight(self.account,self.policy,"BTC-USD","50000","0.1")
 def test_large_account_budget(self):
  self.account["buying_power"]="20"
  self.assertEqual(preflight(self.account,self.policy,"BTC-USD","50000","0.1")["budget_usd"],"5")
 def test_unreconciled_fails(self):
  self.account["buying_power"]="20"
  with self.assertRaises(RiskDenied):
   preflight(self.account,self.policy,"BTC-USD","50000","0.1",1)
