import tempfile
import unittest
from pathlib import Path
from datetime import datetime,timezone,timedelta
from crypto_prediction_lab import record,resolve,summary,load

class CryptoPredictionTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory()
  self.addCleanup(self.tmp.cleanup)
  self.path=Path(self.tmp.name)/"predictions.json"
  self.start=datetime(2026,10,31,0,tzinfo=timezone.utc)
 def forecast(self):
  return record(self.path,"BTC/USD",1,"UP",self.start.isoformat(),100,
                "Mocked research hypothesis",now=self.start+timedelta(minutes=15))
 def test_record_and_resolve_future(self):
  self.forecast()
  bar={"timestamp":(self.start+timedelta(hours=1)).isoformat(),"close":102}
  self.assertEqual(resolve(self.path,{"BTC/USD":[bar]},now=self.start+timedelta(minutes=30)),0)
  self.assertEqual(resolve(self.path,{"BTC/USD":[bar]},now=self.start+timedelta(hours=2)),1)
  self.assertEqual(resolve(self.path,{"BTC/USD":[bar]},now=self.start+timedelta(hours=3)),0)
  self.assertTrue(load(self.path)[0]["outcome"]["direction_correct"])
  self.assertGreater(summary(self.path)["hypothetical_net_usd"],0)
 def test_stale_blocked(self):
  with self.assertRaises(ValueError):
   record(self.path,"BTC/USD",1,"UP",self.start.isoformat(),100,"reason",
          now=self.start+timedelta(hours=3))
 def test_duplicate_locked(self):
  self.forecast()
  with self.assertRaises(ValueError):self.forecast()
 def test_no_simulated_fallback(self):
  self.forecast()
  x=summary(self.path)
  self.assertEqual(x["live_trades"],0)
  self.assertFalse(x["paper_is_fallback"])
if __name__=="__main__":unittest.main()
