import tempfile,unittest
from datetime import datetime,timezone
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
from model_monitor import update_scorecard

class CalibrationTests(unittest.TestCase):
 def test_prediction_scored_only_after_observed_bar(self):
  with tempfile.TemporaryDirectory() as td:
   records={"SOFI":[{"date":"2026-10-30","close":10.0}]}
   chosen=[{"ticker":"SOFI","as_of":"2026-10-30","reference_close":10.0,
            "chronos_bolt":{"log_return_quantiles":[-0.05,0.01,0.05]}}]
   at=datetime(2026,10,30,tzinfo=timezone.utc)
   first=update_scorecard(td,records,chosen,at,"2026-11-02T09:30:00-05:00")
   self.assertEqual(first["scored_predictions"],0)
   second=update_scorecard(td,records,chosen,at,"2026-11-02T09:30:00-05:00")
   self.assertEqual(second["scored_predictions"],0)
   records["SOFI"].append({"date":"2026-11-02","close":10.2})
   third=update_scorecard(td,records,chosen,at,"2026-11-03T09:30:00-05:00")
   self.assertEqual(third["scored_predictions"],1)
   self.assertEqual(third["quantile_interval_coverage"],1.0)
   self.assertEqual(third["status"],"insufficient_sample")
   self.assertGreater(third["mean_absolute_log_return_error"],0)
if __name__=="__main__":unittest.main()
