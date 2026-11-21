"""V2 readiness API must require authentication and never authorize live orders."""
import tempfile,unittest,os
from pathlib import Path
from unittest.mock import patch
import dashboard_server

class V2StatusApiTests(unittest.TestCase):
    def handler(self,authorized):
        h=dashboard_server.Handler.__new__(dashboard_server.Handler)
        h.path="/api/v2/status"
        h._nonce=lambda:"valid-nonce" if authorized else None
        h._json=lambda status,doc,more=None:(status,doc)
        return h
    def test_unauthenticated_status_never_leaks_runtime(self):
        with patch.object(dashboard_server,"UNIFIED_APP",True):
            code,body=self.handler(False).do_GET()
        self.assertEqual(code,401)
        self.assertEqual(body,{"error":"Sign in required"})
    def test_authenticated_default_disabled_and_readonly(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(
             dashboard_server,"STATE_DIR",Path(folder)),patch.object(
             dashboard_server,"UNIFIED_APP",True),patch.dict(
             os.environ,{"AUTO_TRADER_V2_ENABLED":"false"}):
            code,body=self.handler(True).do_GET()
            self.assertEqual(code,200)
            self.assertFalse(body["feature_enabled"])
            self.assertFalse(body["live_order_authority"])
            self.assertEqual(body["execution_mode"],"PAPER_ONLY")
            self.assertFalse(body["cutover_preflight"]["live_order_authority"])
            self.assertFalse(body["cutover_preflight"]["automatic_cutover_allowed"])
            self.assertEqual(len(body["cutover_preflight"]["accounts"]),4)
            self.assertTrue(all(not a["ready_for_v2_live"]
                for a in body["cutover_preflight"]["accounts"]))
            self.assertFalse((Path(folder)/"v2").exists())
    def test_enabled_flag_only_exposes_status_not_live_broker_authority(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(
             dashboard_server,"STATE_DIR",Path(folder)),patch.object(
             dashboard_server,"UNIFIED_APP",True),patch.dict(
             os.environ,{"AUTO_TRADER_V2_ENABLED":"true","AUTO_TRADER_V2_LIVE":"true"}):
            code,body=self.handler(True).do_GET()
            self.assertEqual(code,200)
            self.assertTrue(body["feature_enabled"])
            self.assertFalse(body["live_order_authority"])
            self.assertEqual(body["store"],"NOT_INITIALIZED")

if __name__=="__main__":unittest.main()
