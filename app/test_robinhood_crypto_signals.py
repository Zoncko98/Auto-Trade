import unittest
from datetime import datetime,timezone,timedelta
from robinhood_crypto_signals import observe
class Signals(unittest.TestCase):
 def test_approval_cannot_be_inferred_from_technicals(self):
  now=datetime(2026,11,2,21,0,tzinfo=timezone.utc)
  hist=[{"symbol":"BTC-USD","mid":v,"at":(now-timedelta(minutes=m)).isoformat()}
        for m,v in [(9,100),(6,100.2),(3,100.4)]]
  q={"results":[{"symbol":"BTC-USD","bid":"100.79","ask":"100.81"}]}
  row=observe(hist,"BTC-USD",q,now)
  self.assertTrue(row["technical_approved"])
  self.assertFalse(row["ai_approved"])
  self.assertFalse(row["execution_eligible"])
 def test_no_history_no_signal(self):
  row=observe([],"BTC-USD",{"results":[{"symbol":"BTC-USD","bid":"10","ask":"10.01"}]})
  self.assertEqual(row["signal"],"INSUFFICIENT_HISTORY")

 def test_rotating_market_samples_qualify_within_hour(self):
  now=datetime(2026,11,3,0,0,tzinfo=timezone.utc)
  history=[{"symbol":"ZEC-USD","mid":str(x),
    "at":(now-timedelta(minutes=m)).isoformat()}
    for m,x in [(42,100),(28,100.2),(14,100.5)]]
  quote={"results":[{"symbol":"ZEC-USD","bid":"100.99","ask":"101.01"}]}
  observation=observe(history,"ZEC-USD",quote,now)
  self.assertTrue(observation["technical_approved"])
  self.assertFalse(observation["ai_approved"])
 def test_old_rotating_sample_is_not_eligible(self):
  now=datetime(2026,11,3,0,0,tzinfo=timezone.utc)
  history=[{"symbol":"ZEC-USD","mid":str(x),
    "at":(now-timedelta(minutes=m)).isoformat()}
    for m,x in [(91,100),(80,100.2),(75,100.5)]]
  quote={"results":[{"symbol":"ZEC-USD","bid":"100.99","ask":"101.01"}]}
  observation=observe(history,"ZEC-USD",quote,now)
  self.assertFalse(observation["technical_approved"])
