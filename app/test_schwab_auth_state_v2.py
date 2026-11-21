"""No-network Schwab authorization-revocation and supervisor gate tests."""
import json
from pathlib import Path
import os
import tempfile
import unittest
from unittest.mock import patch
from schwab_auth_health import (
    is_revoked_refresh_error,mark_reauth_required,reauth_required,
    clear_verified_reauth,
)
from trader_v2.readonly_adapters import _schwab
from trader_v2.models import AuthState

class OAuthError(Exception):
    pass

class SchwabAuthStateTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.live=self.root/"live";self.live.mkdir(mode=0o700)
        self.token=self.root/"schwab_token.json"
        self.token.write_text("synthetic-only-no-real-credentials")
        self.token.chmod(0o600)

    def test_detect_revoked_not_transient_auth_errors(self):
        self.assertTrue(is_revoked_refresh_error(
            OAuthError('unsupported_token_type: {"error":"invalid_grant"}')))
        self.assertTrue(is_revoked_refresh_error(
            OAuthError("Refresh token is invalid, expired or revoked")))
        self.assertFalse(is_revoked_refresh_error(OAuthError("server_error 500")))
        self.assertFalse(is_revoked_refresh_error(RuntimeError("invalid_grant")))

    def test_persistent_fingerprint_blocks_until_token_rotated(self):
        self.assertTrue(mark_reauth_required(self.live,self.token))
        path=self.live/"auth_health.json"
        self.assertEqual(path.stat().st_mode&0o077,0)
        raw=path.read_text()
        self.assertNotIn("synthetic-only",raw)
        self.assertTrue(reauth_required(self.root))
        self.token.write_text("replacement-token-not-real")
        os.utime(self.token,ns=(self.token.stat().st_atime_ns,
                                 self.token.stat().st_mtime_ns+10000000))
        self.assertFalse(reauth_required(self.root))

    def test_existing_truenas_directory_755_keeps_marker_private(self):
        self.live.chmod(0o755)
        self.assertTrue(mark_reauth_required(self.live,self.token))
        self.assertEqual((self.live/"auth_health.json").stat().st_mode&0o077,0)
        self.assertTrue(reauth_required(self.root))
        self.live.chmod(0o777)
        self.assertFalse(mark_reauth_required(self.live,self.token))

    def test_only_successful_account_lookup_clears_marker(self):
        mark_reauth_required(self.live,self.token)
        self.assertTrue(reauth_required(self.root))
        clear_verified_reauth(self.live)
        self.assertFalse(reauth_required(self.root))
        self.assertFalse((self.live/"auth_health.json").exists())

    def test_untrusted_or_insecure_token_is_not_proven_revoked(self):
        self.token.chmod(0o644)
        self.assertFalse(mark_reauth_required(self.live,self.token))
        self.assertFalse(reauth_required(self.root))

    def test_read_only_broker_status_reports_reauth_required(self):
        supervisor=self.live/"supervisor_status.json"
        supervisor.write_text(json.dumps({
            "state":"REAUTH_REQUIRED","reason":"SCHWAB_OAUTH_REAUTH_REQUIRED"}))
        supervisor.chmod(0o600)
        from datetime import datetime,timezone
        row=_schwab(self.root,datetime.now(timezone.utc))
        self.assertEqual(row.auth,AuthState.REAUTH_REQUIRED)
        self.assertEqual(row.worker_state,"OFFLINE")
        self.assertEqual(row.reason_code,"BROKER_OAUTH_REAUTH_REQUIRED")
        self.assertFalse(row.read_verified)

    def test_supervisor_checks_existing_marker_before_start_and_restart(self):
        from pathlib import Path
        import unified_runtime
        code=Path(unified_runtime.__file__).read_text(encoding="utf-8")
        self.assertGreaterEqual(code.count("reauth_required(STATE)"),2)
        self.assertIn('live_supervisor_event("REAUTH_REQUIRED"',code)

if __name__=="__main__":
    unittest.main()
