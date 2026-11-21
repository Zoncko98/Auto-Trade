"""Schwab Start Trading: revoked OAuth cannot become an order-arming action."""
from datetime import datetime,timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase,main
from unittest.mock import patch
import json
import dashboard_server
import live_dashboard
from schwab_auth_health import mark_reauth_required

class SchwabStartOauthGuardTests(TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.state=Path(self.temp.name)
        live=self.state/"live"
        live.mkdir(mode=0o755)
        token=self.state/"schwab_token.json"
        token.write_text("synthetic-revoked-token-fixture",encoding="utf-8")
        token.chmod(0o600)
        self.assertTrue(mark_reauth_required(live,token))
        (live/"worker_heartbeat.json").write_text(json.dumps({
          "at":datetime.now(timezone.utc).isoformat(),
          "armed":True
        }),encoding="utf-8")
        (live/"supervisor_status.json").write_text(json.dumps({
          "state":"REAUTH_REQUIRED","reason":"SCHWAB_OAUTH_REAUTH_REQUIRED"
        }),encoding="utf-8")

    def handler(self,*,authorized=True,valid_origin=True,valid_csrf=True,body=None):
        h=dashboard_server.Handler.__new__(dashboard_server.Handler)
        h.path="/api/live/mode"
        h._same_origin=lambda:valid_origin
        h._csrf_ok=lambda:authorized and valid_csrf
        h._nonce=lambda:"synthetic-session" if authorized else None
        h._body=lambda:body if body is not None else {"mode":"running"}
        h._json=lambda code,payload,headers=None:(code,payload)
        return h

    def test_revoked_token_overrides_recent_armed_heartbeat(self):
        doc=live_dashboard.live_state(self.state)
        self.assertTrue(doc["worker_online"])
        self.assertFalse(doc["armed"])
        self.assertEqual(doc["auth_state"],"REAUTH_REQUIRED")
        self.assertEqual(doc["auth_reason"],"SCHWAB_REFRESH_TOKEN_REJECTED")
        self.assertEqual(doc["worker_supervisor"]["state"],"REAUTH_REQUIRED")

    def test_server_refuses_start_without_modifying_operator_mode(self):
        with patch.object(dashboard_server,"STATE_DIR",self.state),patch.object(
                dashboard_server,"set_operator_mode") as write:
            status,body=self.handler().do_POST()
            self.assertEqual(status,400)
            self.assertIn("OAuth reauthorization required",body["error"])
            write.assert_not_called()

    def test_server_rejects_invalid_csrf_and_origin(self):
        with patch.object(dashboard_server,"STATE_DIR",self.state),patch.object(
                dashboard_server,"set_operator_mode") as write:
            for opts in ({"authorized":False},{"valid_csrf":False},
                         {"valid_origin":False}):
                with self.subTest(opts=opts):
                    status,_=self.handler(**opts).do_POST()
                    self.assertEqual(status,403)
            write.assert_not_called()

    def test_pausing_remains_accessible_with_revoked_token(self):
        with patch.object(dashboard_server,"STATE_DIR",self.state),patch.object(
                dashboard_server,"set_operator_mode",return_value={"mode":"paused"}) as write:
            status,body=self.handler(body={"mode":"paused"}).do_POST()
            self.assertEqual(status,200)
            self.assertTrue(body["ok"])
            write.assert_called_once()

    def test_token_change_clears_marker_identity_not_operator_permissions(self):
        token=self.state/"schwab_token.json"
        token.write_text("synthetic-new-token-fixture-new-bytes",encoding="utf-8")
        token.chmod(0o600)
        doc=live_dashboard.live_state(self.state)
        self.assertEqual(doc["auth_state"],"AWAITING_WORKER_VERIFICATION")
        self.assertFalse(doc["armed"])
        # The worker itself still must independently validate the replacement
        # with a signed account lookup before it may handle an order.
        self.assertTrue(doc["worker_online"])

if __name__=="__main__":
    main()
