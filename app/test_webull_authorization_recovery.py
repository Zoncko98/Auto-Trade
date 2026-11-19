"""Webull live-policy API must not crash on official SDK HTTP 429."""
import unittest
from unittest.mock import patch
from dashboard_server import Handler
import dashboard_server

class AuthorizationHandlerTests(unittest.TestCase):
 def make_handler(self,policy):
  handler=Handler.__new__(Handler)
  handler.path="/api/webull/trader"
  handler._body=lambda:{"policy":policy,"confirmation":"ENABLE_WEBULL_LIVE"}
  handler._same_origin=lambda:True
  handler._csrf_ok=lambda:True
  handler._json=lambda code,body,more=None:(code,body)
  return handler
 def test_fresh_worker_auth_is_only_used_to_save_permission(self):
  policy={"enabled":True,"trade_stocks":True,"trade_crypto":False,
          "stock_account":"example","crypto_account":""}
  h=self.make_handler(policy)
  with patch.object(dashboard_server,"UNIFIED_APP",True),patch(
      "webull_openapi._load",return_value={"environment":"production"}),patch(
      "webull_openapi._verified_worker_accounts",return_value=(
         [{"account_id":"example","account_type":"INDIVIDUAL_MARGIN"}],"2026-11-19T04:00:00+00:00")),patch(
      "webull_broker.WebullBroker",side_effect=AssertionError("Broker client should not be constructed")),patch(
      "webull_account_preferences.read",return_value={"allow_margin_accounts":True}),patch(
      "webull_worker._can_trade_account",return_value=True),patch(
      "webull_trade_config.save",return_value=policy) as saved:
   code,body=h.do_POST()
  self.assertEqual(code,200)
  self.assertTrue(body["enabled"])
  self.assertEqual(saved.call_args.args[2][0]["account_id"],"example")
  self.assertEqual(saved.call_args.args[3],"ENABLE_WEBULL_LIVE")
 def test_sdk_initialization_429_returns_controlled_503_no_permission_change(self):
  policy={"enabled":True,"trade_stocks":True,"trade_crypto":False,
          "stock_account":"example","crypto_account":""}
  h=self.make_handler(policy)
  with patch.object(dashboard_server,"UNIFIED_APP",True),patch(
      "webull_openapi._load",return_value={"environment":"production"}),patch(
      "webull_openapi._verified_worker_accounts",return_value=None),patch(
      "webull_broker.WebullBroker",side_effect=RuntimeError("HTTP Status: 429")),patch(
      "webull_trade_config.save") as saved:
   code,body=h.do_POST()
  self.assertEqual(code,503)
  self.assertIn("rate-limited",body["error"])
  saved.assert_not_called()

if __name__=="__main__":unittest.main()
