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
  self.assertIn("4 samples",row["signal_reason"])
  self.assertEqual(row["history_points"],1)

 def test_low_positive_momentum_explains_no_signal(self):
  now=datetime(2026,11,3,0,0,tzinfo=timezone.utc)
  history=[{"symbol":"BTC-USD","mid":str(x),
    "at":(now-timedelta(minutes=m)).isoformat()}
    for m,x in [(9,100),(6,100.03),(3,100.06)]]
  row=observe(history,"BTC-USD",
    {"results":[{"symbol":"BTC-USD","bid":"100.09","ask":"100.11"}]},now)
  self.assertEqual(row["signal"],"NO_SIGNAL")
  self.assertIn("below +0.5%",row["signal_reason"])
  self.assertTrue(row["trend_up"])
 def test_excessive_spread_explains_no_signal(self):
  now=datetime(2026,11,3,0,0,tzinfo=timezone.utc)
  history=[{"symbol":"BTC-USD","mid":str(x),
    "at":(now-timedelta(minutes=m)).isoformat()}
    for m,x in [(9,100),(6,100.2),(3,100.4)]]
  row=observe(history,"BTC-USD",
    {"results":[{"symbol":"BTC-USD","bid":"100.2","ask":"101.0"}]},now)
  self.assertEqual(row["signal"],"NO_SIGNAL")
  self.assertIn("Spread exceeds",row["signal_reason"])
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

class RobinhoodEntryQuality(unittest.TestCase):
 def test_rejects_late_momentum_spike(self):
  now=datetime(2026,11,9,0,0,tzinfo=timezone.utc)
  history=[{"symbol":"SOL-USD","mid":str(v),"at":(now-timedelta(minutes=m)).isoformat()} for m,v in [(9,100),(6,100.15),(3,100.3)]]
  row=observe(history,"SOL-USD",{"results":[{"symbol":"SOL-USD","bid":"101.18","ask":"101.2"}]},now)
  self.assertEqual(row["signal"],"NO_SIGNAL")
  self.assertIn("late momentum",row["signal_reason"])
 def test_rejects_wide_but_previously_accepted_spread(self):
  now=datetime(2026,11,9,0,0,tzinfo=timezone.utc)
  history=[{"symbol":"SOL-USD","mid":str(v),"at":(now-timedelta(minutes=m)).isoformat()} for m,v in [(9,100),(6,100.2),(3,100.4)]]
  row=observe(history,"SOL-USD",{"results":[{"symbol":"SOL-USD","bid":"100.55","ask":"100.9"}]},now)
  self.assertEqual(row["signal"],"NO_SIGNAL")
  self.assertIn("0.25%",row["signal_reason"])
