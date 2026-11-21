"""Authenticated historical V2 replay route and permission tests."""
import csv
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
import dashboard_server


class RecordedReplayApiTests(unittest.TestCase):
    def handler(self, path, *, authorized=True, csrf=True, body=None, origin=True):
        handler = dashboard_server.Handler.__new__(dashboard_server.Handler)
        handler.path = path
        handler._nonce = lambda: "valid-session" if authorized else None
        handler._csrf_ok = lambda: authorized and csrf
        handler._same_origin = lambda: origin
        handler._body = lambda: body if body is not None else {"symbol": "BTCUSD"}
        handler._json = lambda status, data, more=None: (status, data)
        return handler

    def seeded(self, folder):
        root = Path(folder)
        path = root/"prices.csv"
        now = datetime(2026, 11, 2, tzinfo=timezone.utc)
        prices = [10,10,10,10,10,10,10,10,10,11,12,13,12,11,10,
                  9,8,9,10,11,12,13,12,11]
        with path.open("w",newline="",encoding="utf-8") as f:
            rows = csv.writer(f)
            rows.writerow(["timestamp","symbol","price"])
            for i,price in enumerate(prices):
                rows.writerow([(now+timedelta(minutes=i)).isoformat(),
                               "BTCUSD",str(price)])
        path.chmod(0o600)

    def test_unauthenticated_get_is_rejected_before_tape_read(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(
                dashboard_server,"STATE_DIR",Path(tmp)),patch.object(
                dashboard_server,"UNIFIED_APP",True):
            status, payload = self.handler("/api/v2/replay", authorized=False).do_GET()
            self.assertEqual(status,401)
            self.assertEqual(payload["error"],"Sign in required")
            self.assertFalse((Path(tmp)/"v2").exists())

    def test_authorized_get_is_read_only_and_reports_candles(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.seeded(tmp)
            with patch.object(dashboard_server,"STATE_DIR",Path(tmp)),patch.object(
                    dashboard_server,"UNIFIED_APP",True):
                status,data=self.handler("/api/v2/replay").do_GET()
            self.assertEqual(status,200)
            self.assertEqual(data["state"],"AVAILABLE")
            self.assertFalse(data["live_orders_authorized"])
            self.assertEqual(data["symbols"][0]["symbol"],"BTCUSD")
            self.assertFalse((Path(tmp)/"v2").exists())

    def test_replay_post_requires_same_origin_and_csrf(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.seeded(tmp)
            with patch.object(dashboard_server,"STATE_DIR",Path(tmp)),patch.object(
                    dashboard_server,"UNIFIED_APP",True):
                for values,code in [
                    ({"authorized":False},403),
                    ({"csrf":False},403),
                    ({"origin":False},403),
                ]:
                    with self.subTest(values=values):
                        status,_=self.handler("/api/v2/replay/run",**values).do_POST()
                        self.assertEqual(status,code)
                        self.assertFalse((Path(tmp)/"v2").exists())

    def test_valid_post_returns_real_persistent_simulation_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.seeded(tmp)
            with patch.object(dashboard_server,"STATE_DIR",Path(tmp)),patch.object(
                    dashboard_server,"UNIFIED_APP",True):
                status,result=self.handler("/api/v2/replay/run").do_POST()
                self.assertEqual(status,200)
                self.assertTrue(result["simulated_only"])
                self.assertFalse(result["broker_credentials_used"])
                self.assertEqual(result["live_orders_submitted"],0)
                self.assertGreater(result["journal"]["events"],0)
                cached_code,cached=self.handler("/api/v2/replay/run").do_POST()
                self.assertEqual(cached_code,200)
                self.assertEqual(result,cached)

    def test_bad_payload_is_rejected_before_creating_account(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.seeded(tmp)
            with patch.object(dashboard_server,"STATE_DIR",Path(tmp)),patch.object(
                    dashboard_server,"UNIFIED_APP",True):
                status,_=self.handler("/api/v2/replay/run",
                    body={"symbol":"BTCUSD","broker":"schwab"}).do_POST()
                self.assertEqual(status,400)
                status,_=self.handler("/api/v2/replay/run",
                    body={"symbol":"UNKNOWN"}).do_POST()
                self.assertEqual(status,409)
            self.assertFalse((Path(tmp)/"v2").exists())


if __name__=="__main__":
    unittest.main()
