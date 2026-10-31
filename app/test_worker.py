"""Worker integration tests: server-side Start/Pause/Stop and heartbeat."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from dashboard_control import default_control, write_atomic


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.state=self.root/"state"
        self.state.mkdir()
        self.logs=self.root/"logs"

    def run_worker(self):
        env=os.environ.copy()
        env.update({
            "STATE_DIR":str(self.state), "LOG_DIR":str(self.logs),
            "LIVE_TRADING":"false", "AI_MODEL":"", "AI_OLLAMA_URL":"",
            "ALLOW_OPTIONS":"false", "ALLOW_MARGIN":"false",
            "ALLOW_SHORT_SELLING":"false",
        })
        result=subprocess.run([sys.executable,"bot.py","--once"],
            env=env,cwd=Path(__file__).parent,capture_output=True,text=True,timeout=8)
        self.assertEqual(result.returncode,0,result.stdout+"\n"+result.stderr)
        return json.loads((self.state/"runtime_status.json").read_text())

    def test_missing_control_is_stopped(self):
        result=self.run_worker()
        self.assertEqual(result["mode"],"stopped")
        self.assertEqual(result["trades"],0)
        self.assertTrue(result["paper_only"])

    def test_mode_changes_are_applied(self):
        control=default_control()
        control["mode"]="paused"
        write_atomic(self.state/"control.json",control)
        self.assertEqual(self.run_worker()["mode"],"paused")
        control["mode"]="running"
        control["revision"]=1
        write_atomic(self.state/"control.json",control)
        self.assertEqual(self.run_worker()["mode"],"running")
        self.assertEqual(self.run_worker()["trades"],0)

    def test_invalid_control_is_error_not_running(self):
        (self.state/"control.json").write_text('{"mode":"running"}')
        env=os.environ.copy()
        env.update({
            "STATE_DIR":str(self.state),"LOG_DIR":str(self.logs),
            "LIVE_TRADING":"false","AI_MODEL":"","AI_OLLAMA_URL":"",
        })
        result=subprocess.run([sys.executable,"bot.py","--once"],
            env=env,cwd=Path(__file__).parent,capture_output=True,text=True,timeout=8)
        self.assertNotEqual(result.returncode,0)
        runtime=json.loads((self.state/"runtime_status.json").read_text())
        self.assertEqual(runtime["mode"],"error")


if __name__=="__main__":
    unittest.main(verbosity=2)
