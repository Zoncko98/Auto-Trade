import os,subprocess,tempfile,unittest,sys
from pathlib import Path

class UnifiedAccountWorkerTests(unittest.TestCase):
 def test_paper_account_check_requires_no_schwab_authorization(self):
  with tempfile.TemporaryDirectory() as root:
   env=dict(os.environ,STATE_DIR=root,LIVE_TRADING="false",LIVE_MODE="DISABLED")
   proc=subprocess.run([sys.executable,str(Path(__file__).parent/"live_worker.py"),
       "--account","paper","--check"],env=env,capture_output=True,text=True,timeout=8)
   self.assertEqual(proc.returncode,0,proc.stdout+proc.stderr)
   self.assertIn("Paper account only",proc.stdout)
   self.assertFalse((Path(root)/"live"/"orders.json").exists())
