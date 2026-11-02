import tempfile,unittest
from robinhood_policy import read_policy,save_policy,PolicyError
class PolicyTests(unittest.TestCase):
 def setUp(self):
  self.accounts=[{"account_number":"test-123","status":"active","is_api_tradable":True}]
 def test_saved_settings_do_not_enable_orders(self):
  with tempfile.TemporaryDirectory() as d:
   doc=save_policy(d,{"account":"test-123","enabled":False,
                     "max_order_usd":"5","verified_broker_minimum_usd":"0"},self.accounts)
   self.assertTrue(doc["configured"])
   self.assertFalse(doc["enabled"])
   self.assertEqual(read_policy(d)["max_order_usd"],"5")
 def test_cannot_arm_via_settings(self):
  with tempfile.TemporaryDirectory() as d:
   with self.assertRaises(PolicyError):
    save_policy(d,{"account":"test-123","enabled":True,"max_order_usd":"5",
                   "verified_broker_minimum_usd":"0"},self.accounts)
 def test_invalid_account_and_limit(self):
  with tempfile.TemporaryDirectory() as d:
   for account,limit in (("wrong","5"),("test-123","26"),("test-123","nan")):
    with self.assertRaises(PolicyError):
     save_policy(d,{"account":account,"max_order_usd":limit,
                    "verified_broker_minimum_usd":"0"},self.accounts)
