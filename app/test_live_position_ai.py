import unittest
from datetime import datetime,timezone,timedelta
from live_position_ai import review_held
class Tests(unittest.TestCase):
 def setUp(self):self.now=datetime(2026,10,31,tzinfo=timezone.utc)
 def test_review_is_advisory(self):
  d=review_held({"F":3},self.now,reviewer=lambda s,n:(False,"weak headlines"))
  self.assertEqual(d["F"]["status"],"review_required")
  self.assertFalse(d["F"]["execution_authorized"])
 def test_outage_keeps_safety_independent(self):
  def fail(*args):raise OSError("offline")
  d=review_held({"F":3},self.now,reviewer=fail)
  self.assertEqual(d["F"]["status"],"ai_unavailable")
 def test_interval(self):
  old={"F":{"at":self.now.isoformat(),"status":"previous"}}
  d=review_held({"F":3},self.now+timedelta(minutes=5),old,reviewer=lambda *args: (_ for _ in ()).throw(AssertionError()))
  self.assertEqual(d["F"]["status"],"previous")
 def test_new_review_after_interval(self):
  old={"F":{"at":self.now.isoformat(),"status":"previous"}}
  d=review_held({"F":3},self.now+timedelta(minutes=16),old,reviewer=lambda s,n:(True,"ok"))
  self.assertEqual(d["F"]["status"],"evidence_positive")
if __name__=="__main__":unittest.main()
