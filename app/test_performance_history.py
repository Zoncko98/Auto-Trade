import tempfile
import unittest
from pathlib import Path
from datetime import datetime, timedelta, timezone
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
from app.dashboard_server import _performance_points

class PerformanceHistoryTests(unittest.TestCase):
    def test_filters_and_bounds(self):
        now=datetime.now(timezone.utc)
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/"performance.jsonl"
            with path.open("w") as handle:
                handle.write('{"timestamp":"bad","equity":9}\n')
                handle.write('{"timestamp":"'+(now-timedelta(days=10)).isoformat()+'","equity":1}\n')
                for i in range(8):
                    handle.write('{"timestamp":"'+now.isoformat()+'","equity":'+str(i)+'}\n')
            self.assertEqual(len(_performance_points(path,1,maximum=3)),3)
            self.assertEqual([p["equity"] for p in _performance_points(path,1,maximum=3)],[5,6,7])
            self.assertEqual(len(_performance_points(path,0,maximum=20)),9)
    def test_missing_history(self):
        self.assertEqual(_performance_points(Path("/nonexistent/performance.jsonl"),1),[])
