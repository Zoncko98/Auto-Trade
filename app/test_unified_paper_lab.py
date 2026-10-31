import tempfile,unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path
from unified_paper_lab import cycle,report
class Tests(unittest.TestCase):
 def setUp(self):
  self.folder=tempfile.TemporaryDirectory()
  self.addCleanup(self.folder.cleanup)
  self.file=Path(self.folder.name)/"paper.json"
  self.start=datetime(2026,10,31,12,tzinfo=timezone.utc)
  self.bars=[{"timestamp":(self.start-timedelta(hours=26-i)).isoformat(),"close":float(100+i)} for i in range(26)]
 def model(self,symbol,bars):
  return ({"direction":"UP","horizon_hours":1,"reason":"Mock momentum test only"},"local_ai")
 def test_separate_accounts_and_duplicates(self):
  first=cycle(self.file,get_bars=lambda symbol:self.bars,predict=self.model,now=self.start)
  self.assertEqual(len(first["added"]),6)
  self.assertEqual(first["report"]["accounts"]["equity"]["predictions"],4)
  self.assertEqual(first["report"]["accounts"]["crypto"]["predictions"],2)
  second=cycle(self.file,get_bars=lambda symbol:self.bars,predict=self.model,now=self.start)
  self.assertEqual(second["added"],[])
  self.assertTrue(second["report"]["paper_only"])
 def test_offline_ai_fails_closed(self):
  def error(*args):raise ConnectionError("offline")
  result=cycle(self.file,get_bars=lambda symbol:self.bars,predict=error,now=self.start)
  self.assertEqual(result["added"],[])
  self.assertEqual(result["report"]["accounts"]["equity"]["virtual_equity"],100)
 def test_future_only(self):
  cycle(self.file,get_bars=lambda symbol:self.bars,predict=self.model,now=self.start)
  nextbar={"timestamp":(self.start+timedelta(hours=1)).isoformat(),"close":130.}
  data=self.bars+[nextbar]
  outcome=cycle(self.file,get_bars=lambda symbol:data,predict=self.model,now=self.start+timedelta(hours=2))
  self.assertEqual(outcome["settled"],6)
  self.assertGreater(outcome["report"]["accounts"]["equity"]["virtual_equity"],100)
if __name__=="__main__":unittest.main()
