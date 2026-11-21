"""V2 fresh crypto paper API is authenticated and never order-capable."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import unittest
import dashboard_server


class FreshPaperAPI(unittest.TestCase):
    def handler(self,path,authenticated=True):
        h=dashboard_server.Handler.__new__(dashboard_server.Handler)
        h.path=path
        h._nonce=lambda: "valid-session" if authenticated else None
        h._json=lambda status,body,more=None:(status,body)
        return h

    def test_unauthenticated_fresh_status_not_exposed(self):
        with TemporaryDirectory() as folder,patch.object(
            dashboard_server,"STATE_DIR",Path(folder)),patch.object(
            dashboard_server,"UNIFIED_APP",True):
            result,body=self.handler("/api/v2/paper-fresh",False).do_GET()
            self.assertEqual(result,401)
            self.assertNotIn("reports",body)
            self.assertFalse((Path(folder)/"v2").exists())

    def test_authorized_fresh_status_readonly_and_independent(self):
        with TemporaryDirectory() as folder,patch.object(
            dashboard_server,"STATE_DIR",Path(folder)),patch.object(
            dashboard_server,"UNIFIED_APP",True):
            result,body=self.handler("/api/v2/paper-fresh").do_GET()
            self.assertEqual(result,200)
            self.assertFalse(body["live_orders_authorized"])
            self.assertFalse(body["broker_credentials_used"])
            self.assertEqual(body["ai_mode"],"OFF_BASELINE")
            self.assertEqual(len(body["reports"]),2)
            self.assertTrue(all(x["scan_state"]=="NOT_SCANNED"
                                for x in body["reports"]))
            self.assertFalse((Path(folder)/"v2").exists())

    def test_runtime_only_start_when_existing_paper_setting_enabled(self):
        import unified_runtime
        s=Path(unified_runtime.__file__).read_text(encoding="utf-8")
        self.assertIn('enabled["v2_paper"]=bool(cfg["paper_enabled"])',s)
        self.assertIn('spawn("v2-paper",["-m","trader_v2.fresh_paper"',s)
        self.assertIn('stop_process("v2-paper")',s)
        self.assertIn('v2_paper_last_spawn>=120',s)
        self.assertNotIn("LIVE_TRADING=\"true\"","v2-paper")


if __name__=="__main__":
    unittest.main()
