import tempfile,unittest
from robinhood_policy import read_policy,save_policy,PolicyError
class PolicyTests(unittest.TestCase):
 def setUp(self):
  self.pairs=[{"symbol":"BTC-USD","is_api_tradable":True,
               "min_order_amount":"1","asset_increment":"0.000001",
               "max_order_size":"100"}]
  self.accounts=[{"account_number":"test-123","status":"active","is_api_tradable":True,"buying_power_currency":"USD","buying_power":"20"}]
 def test_saved_settings_do_not_enable_orders(self):
  with tempfile.TemporaryDirectory() as d:
   doc=save_policy(d,{"account":"test-123","enabled":False,
                     "max_order_usd":"5","verified_broker_minimum_usd":"0"},self.accounts,self.pairs)
   self.assertTrue(doc["configured"])
   self.assertFalse(doc["enabled"])
   self.assertEqual(read_policy(d)["max_order_usd"],"5")
 def test_arm_after_verified_pair_and_cash(self):
  with tempfile.TemporaryDirectory() as d:
   result=save_policy(d,{"account":"test-123","enabled":True,"max_order_usd":"5",
                   "verified_broker_minimum_usd":"0"},self.accounts,self.pairs)
   self.assertTrue(result["enabled"])
   self.assertEqual(result["verified_broker_minimum_usd"],"1")
 def test_cannot_arm_when_cash_too_low(self):
  with tempfile.TemporaryDirectory() as d:
   self.accounts[0]["buying_power"]="1.86"
   with self.assertRaises(PolicyError):
    save_policy(d,{"account":"test-123","enabled":True,"max_order_usd":"5",
                   "verified_broker_minimum_usd":"0"},self.accounts,self.pairs)
 def test_invalid_account_and_limit(self):
  with tempfile.TemporaryDirectory() as d:
   for account,limit in (("wrong","5"),("test-123","26"),("test-123","nan")):
    with self.assertRaises(PolicyError):
     save_policy(d,{"account":account,"max_order_usd":limit,
                    "verified_broker_minimum_usd":"0"},self.accounts,self.pairs)
