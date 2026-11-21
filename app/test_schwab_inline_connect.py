"""Schwab unified in-dashboard OAuth: new sessions, repeated backups, guarded POST."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase,main
from unittest.mock import patch
from types import SimpleNamespace,ModuleType
import json,sys,time
from unified_config import DEFAULTS,atomic_save
from schwab_web_oauth import begin,finish
import dashboard_server

class SchwabInlineConnectionTests(TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.state=Path(self.temp.name)
        atomic_save(self.state/"config"/"integrations.json",{
            **DEFAULTS,"ai_provider":"none","schwab_app_key":"synthetic-key",
            "schwab_callback_url":"https://127.0.0.1:8182"})
        atomic_save(self.state/"config"/"credentials.json",
                    {"schwab_app_secret":"fake-credential-only"})
        self.seq=0
        root=ModuleType("schwab")
        auth=ModuleType("schwab.auth")
        def get_auth_context(_key,callback):
            self.seq+=1
            return SimpleNamespace(state="unique-state-of-sufficient-size-"+str(self.seq),
                authorization_url="https://api.schwabapi.com/v1/oauth/authorize?test="+str(self.seq))
        def exchange(_key,_secret,ctx,url,write_token,**kw):
            self.assertIn("code=fixture-code",url)
            write_token({"access_token":"NEW-SYNTHETIC","refresh_token":"FAKE"})
        def from_candidate(_path,_key,_secret):
            response=SimpleNamespace(status_code=200,
                json=lambda:[{"accountNumber":"XXXX1234","hashValue":"VERIFIED_HASH_12345"}])
            return SimpleNamespace(get_account_numbers=lambda:response)
        auth.get_auth_context=get_auth_context
        auth.client_from_received_url=exchange
        auth.client_from_token_file=from_candidate
        auth.AuthContext=lambda callback,url,state:SimpleNamespace(
            callback_url=callback,authorization_url=url,state=state)
        root.auth=auth
        patcher=patch.dict(sys.modules,{"schwab":root,"schwab.auth":auth})
        patcher.start();self.addCleanup(patcher.stop)

    def _token(self):
        token=self.state/"schwab_token.json"
        atomic_save(token,{"refresh_token":"OLD-SYNTHETIC"})
        return token

    def test_one_action_auto_connects_and_reuses_pending_session(self):
        first=begin(self.state,reconnect=None)
        second=begin(self.state,reconnect=None)
        self.assertFalse(first["automatic_callback"])
        self.assertEqual(first["authorization_url"],second["authorization_url"])
        self.assertTrue(second["resumed"])
        self.assertEqual(self.seq,1)
        self.assertFalse(json.loads((self.state/"schwab_oauth_pending.json").read_text())["reconnect"])

    def test_saved_revoked_token_auto_switches_to_reconnect_and_reuses_session(self):
        old=self._token().read_bytes()
        first=begin(self.state,reconnect=None)
        self.assertTrue(json.loads((self.state/"schwab_oauth_pending.json").read_text())["reconnect"])
        self.assertEqual(first["authorization_url"],begin(self.state,reconnect=None)["authorization_url"])
        self.assertEqual(self._token().read_bytes(),old)
        self.assertEqual(self.seq,1)

    def test_expired_pending_creates_new_state_without_touching_old_token(self):
        self._token()
        first=begin(self.state,reconnect=None)
        pending=self.state/"schwab_oauth_pending.json"
        doc=json.loads(pending.read_text());doc["created"]=time.time()-700
        atomic_save(pending,doc)
        second=begin(self.state,reconnect=None)
        self.assertNotEqual(first["authorization_url"],second["authorization_url"])
        self.assertEqual(self.seq,2)

    def test_explicit_restart_replaces_only_pending_oauth_state(self):
        old=self._token().read_bytes()
        first=begin(self.state,reconnect=None)
        second=begin(self.state,reconnect=None,restart=True)
        self.assertNotEqual(first["authorization_url"],second["authorization_url"])
        self.assertEqual((self.state/"schwab_token.json").read_bytes(),old)

    def test_corrupted_pending_expiry_does_not_crash_or_reuse(self):
        first=begin(self.state,reconnect=None)
        pending=self.state/"schwab_oauth_pending.json"
        saved=json.loads(pending.read_text());saved["created"]="invalid"
        atomic_save(pending,saved)
        second=begin(self.state,reconnect=None)
        self.assertNotEqual(first["authorization_url"],second["authorization_url"])

    def test_existing_legacy_backup_does_not_block_verified_replacement(self):
        old=self._token().read_bytes()
        backup=self.state/"schwab_token_pre_reconnect.json"
        backup.write_bytes(b'{"stale":"backup"}');backup.chmod(0o600)
        begin(self.state,reconnect=None)
        pending=json.loads((self.state/"schwab_oauth_pending.json").read_text())
        url="https://127.0.0.1:8182/?code=fixture-code&state="+pending["state"]
        result=finish(self.state,url)
        self.assertTrue(result["accounts_verified"])
        self.assertNotEqual((self.state/"schwab_token.json").read_bytes(),old)
        self.assertEqual(backup.read_bytes(),b'{"stale":"backup"}')
        rotated=list(self.state.glob("schwab_token_pre_reconnect_*.json"))
        self.assertEqual(len(rotated),1)
        self.assertEqual(rotated[0].read_bytes(),old)
        self.assertEqual(rotated[0].stat().st_mode&0o077,0)
        self.assertFalse((self.state/"schwab_oauth_pending.json").exists())

    def test_wrong_callback_state_does_not_replace_existing_token(self):
        old=self._token().read_bytes()
        begin(self.state,reconnect=None)
        with self.assertRaises(ValueError):
            finish(self.state,"https://127.0.0.1:8182/?code=fixture-code&state=INVALID")
        self.assertEqual(self._token().read_bytes(),old)

    def test_connect_route_is_authenticated_and_csrf_protected(self):
        def handler(ok=True,csrf=True,origin=True):
            h=dashboard_server.Handler.__new__(dashboard_server.Handler)
            h.path="/api/schwab/connect"
            h._same_origin=lambda:origin
            h._csrf_ok=lambda:ok and csrf
            h._body=lambda:{}
            h._json=lambda code,body,other=None:(code,body)
            return h
        with patch.object(dashboard_server,"UNIFIED_APP",True),patch.object(
                dashboard_server,"STATE_DIR",self.state):
            for options in ({"ok":False},{"csrf":False},{"origin":False}):
                with self.subTest(options=options):
                    code,_=handler(**options).do_POST()
                    self.assertEqual(code,403)
            self.assertFalse((self.state/"schwab_oauth_pending.json").exists())
            code,doc=handler().do_POST()
            self.assertEqual(code,200)
            self.assertTrue(doc["authorization_url"].startswith("https://api.schwabapi.com/"))
            self.assertEqual(self.seq,1)

if __name__=="__main__":main()
