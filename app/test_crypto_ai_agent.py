import unittest
import tempfile
from pathlib import Path
from datetime import datetime,timezone,timedelta
from crypto_ai_agent import _parse,cycle,PredictionUnavailable
from crypto_prediction_lab import load

class Tests(unittest.TestCase):
 def test_schema(self):
  self.assertEqual(_parse('{"direction":"UP","horizon_hours":4,"reason":"Strong momentum observed"}')["direction"],"UP")
  for v in ('{"direction":"BUY","horizon_hours":1,"reason":"Too optimistic maybe"}',
            '{"direction":"UP","horizon_hours":true,"reason":"String reason yes"}',
            '{"direction":"DOWN","horizon_hours":4,"reason":"valid reason","order":"BUY"}'):
   with self.assertRaises(PredictionUnavailable):_parse(v)
 def test_cycle_no_broker_calls(self):
  now=datetime(2026,10,31,9,30,tzinfo=timezone.utc)
  bars=[{"timestamp":(now-timedelta(hours=26-i)).isoformat(),"close":100+i} for i in range(26)]
  with tempfile.TemporaryDirectory() as d:
   out=cycle(Path(d)/"audit.json",fetch=lambda pair:bars,
             predict=lambda pair,b:({"direction":"UP","horizon_hours":1,"reason":"Trend continues in this scenario"},"local_ai"),now=now)
   self.assertEqual(len(out["recorded"]),2)
   self.assertEqual(len(load(Path(d)/"audit.json")),2)
   self.assertEqual(out["summary"]["live_trades"],0)
 def test_fail_closed_provider(self):
  now=datetime(2026,10,31,9,30,tzinfo=timezone.utc)
  bars=[{"timestamp":(now-timedelta(hours=26-i)).isoformat(),"close":100+i} for i in range(26)]
  with tempfile.TemporaryDirectory() as d:
   out=cycle(Path(d)/"audit.json",fetch=lambda pair:bars,
             predict=lambda *x:(_ for _ in ()).throw(PredictionUnavailable("offline")),now=now)
   self.assertEqual(out["recorded"],[])
if __name__=="__main__":unittest.main()
