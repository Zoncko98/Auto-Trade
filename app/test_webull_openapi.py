"""Webull credential and fail-closed checks; no live orders."""
import os
import sys
import json
import tempfile
import unittest
from types import ModuleType
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

class WebullSdkInitTests(unittest.TestCase):
    def test_sdk_trade_client_has_logging_before_initialization_and_no_relative_log(self):
        from unittest.mock import patch
        import sys
        import logging
        import webull_openapi
        calls=[]
        class FakeApi:
            def __init__(self,key,secret,region):
                self._stream_logger_set=False
                self.key=key
            def add_endpoint(self,region,url):
                self.endpoint=url
            def set_token_dir(self,path):
                self.token_dir=path
            def set_stream_logger(self,**kwargs):
                self._stream_logger_set=True
                calls.append(kwargs)
                logger=logging.getLogger("webull.core")
                logger.addHandler(logging.StreamHandler(kwargs["stream"]))
        class FakeTrade:
            def __init__(self,api):
                if not api._stream_logger_set:
                    Path("webull_trade_sdk.log").write_text("Default file log")
                assert api._stream_logger_set
                assert api.token_dir
        modules={"webull":ModuleType("webull"),
                 "webull.core":ModuleType("webull.core"),
                 "webull.core.client":ModuleType("webull.core.client"),
                 "webull.trade":ModuleType("webull.trade"),
                 "webull.trade.trade_client":ModuleType("webull.trade.trade_client")}
        modules["webull.core.client"].ApiClient=FakeApi
        modules["webull.trade.trade_client"].TradeClient=FakeTrade
        with tempfile.TemporaryDirectory() as td:
            with patch.dict(sys.modules,modules):
                with patch.object(webull_openapi,"_load",return_value={
                     "app_key":"dummy-api-key","app_secret":"dummy-secret","environment":"sandbox"}):
                    with patch("os.getcwd",return_value=td):
                        client,env=webull_openapi._client(td)
                        client2,env2=webull_openapi._client(td)
            self.assertEqual(env,"sandbox")
            self.assertEqual(env2,"sandbox")
            self.assertFalse((Path(td)/"webull_trade_sdk.log").exists())
            self.assertEqual(len(calls),2)
            self.assertTrue(all(x["log_level"]==logging.WARNING for x in calls))
            self.assertEqual(len([h for h in logging.getLogger("webull.core").handlers
                 if h is webull_openapi._sdk_stream_handler]),1)
        logger=logging.getLogger("webull.core")
        if webull_openapi._sdk_stream_handler is not None:
            logger.removeHandler(webull_openapi._sdk_stream_handler)
            webull_openapi._sdk_stream_handler.close()
            webull_openapi._sdk_stream_handler=None

class WebullRealSdkTests(unittest.TestCase):
    def test_official_sdk_initializes_without_writing_to_readonly_workdir(self):
        import os
        from unittest.mock import patch
        from pathlib import Path
        try:
            from webull.core.client import ApiClient
            from webull.trade.trade_client import TradeClient
        except ImportError:
            self.skipTest("Official SDK not installed in host Python")
        import webull_openapi
        with tempfile.TemporaryDirectory() as td:
            readonly=Path(td)/"readonly"
            readonly.mkdir()
            readonly.chmod(0o555)
            previous=os.getcwd()
            try:
                os.chdir(readonly)
                with patch.object(webull_openapi,"_load",return_value={
                        "app_key":"test-dummy-api-key","app_secret":"test-dummy-secret","environment":"sandbox"}):
                    client,env=webull_openapi._client(td)
                self.assertIsInstance(client,TradeClient)
                self.assertEqual(env,"sandbox")
                self.assertFalse((readonly/"webull_trade_sdk.log").exists())
            finally:
                os.chdir(previous)
                readonly.chmod(0o700)

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
