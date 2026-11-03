"""Webull credential and fail-closed checks; no live orders."""
import os
import sys
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent))
import webull_openapi as w

class WebullTests(unittest.TestCase):
    def test_credentials_input_and_storage_permissions(self):
        with tempfile.TemporaryDirectory() as td:
            state=Path(td)
            payload={"app_key":"webull-key-1234","app_secret":"some-secret-value","environment":"sandbox"}
            self.assertFalse(w.status(state)["connected"])
            result=w.store_credentials(state,payload)
            self.assertTrue(result["saved"])
            self.assertFalse(result["authenticated"])
            target=state/"config"/"webull_openapi.json"
            self.assertEqual(target.stat().st_mode & 0o077,0)
            self.assertNotIn(payload["app_secret"],str(w.status(state)))
            self.assertEqual(w._load(state),payload)
            for bad in ("dev","https://evil.com","production/../../"):
                with self.assertRaises(ValueError):
                    w.store_credentials(state,dict(payload,environment=bad))
            with self.assertRaises(ValueError):
                w.store_credentials(state,dict(payload,extra="unexpected"))
    def test_account_response_validation(self):
        self.assertEqual(w._accounts([{"account_id":"a"}]),[{"account_id":"a"}])
        self.assertEqual(w._accounts({"data":[{"account_id":"a"}]}),[{"account_id":"a"}])
        with self.assertRaises(w.WebullError):w._accounts({"unexpected":"shape"})
    def test_no_secret_in_status_on_sdk_failure(self):
        with tempfile.TemporaryDirectory() as td:
            w.store_credentials(td,{"app_key":"testkey-123456","app_secret":"secretvalue12345","environment":"sandbox"})
            with patch.object(w,"_client",side_effect=w.WebullError("Service unavailable")):
                result=w.status(td)
            self.assertFalse(result["connected"])
            self.assertFalse(result["execution_enabled"])
            self.assertNotIn("secretvalue",json.dumps(result))

class WebullRiskTests(unittest.TestCase):
    def test_risk_plan_isolated_and_disarmed(self):
        import webull_risk
        with tempfile.TemporaryDirectory() as td:
            self.assertFalse(webull_risk.read(td)["execution_enabled"])
            values={"max_position_pct":5.0,"max_order_usd":100.0,
                    "max_daily_loss_usd":25.0,"max_open_positions":3}
            result=webull_risk.save(td,values)
            self.assertTrue(result["saved"])
            self.assertFalse(result["execution_enabled"])
            self.assertEqual(webull_risk.read(td)["max_open_positions"],3)
            self.assertEqual((Path(td)/"webull"/"risk_plan.json").stat().st_mode & 0o077,0)
            with self.assertRaises(ValueError):
                webull_risk.save(td,dict(values,max_order_usd=float("nan")))
            with self.assertRaises(ValueError):
                webull_risk.save(td,dict(values,max_open_positions=0))
            with self.assertRaises(ValueError):
                webull_risk.save(td,dict(values,execution_enabled=True))
if __name__=="__main__":unittest.main()
