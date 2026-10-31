"""Regression tests for improved first-run setup, callback and live confirm."""
import io,json,sys,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
from contextlib import redirect_stdout
sys.path.insert(0,str(Path(__file__).resolve().parent))
from unified_config import DEFAULTS,validate,SetupError,atomic_save,settings,save
from live_access import toggle
from live_dashboard import operator_mode
from dashboard_server import Handler
import update_status
from schwab_web_oauth import finish

class SetupRegression(unittest.TestCase):
 def test_optional_broker_modules_do_not_block_install(self):
  opts={"ai_provider":"none","market_enabled":True}
  result,secret=validate(opts,dict(DEFAULTS),{})
  self.assertTrue(result["market_enabled"])
  self.assertEqual(secret,{})
 def test_private_nas_callback_and_loopback(self):
  opts={"ai_provider":"none","schwab_callback_url":"https://192.168.1.43:8768/schwab/callback"}
  self.assertEqual(validate(opts,dict(DEFAULTS),{})[0]["schwab_callback_url"],opts["schwab_callback_url"])
  opts["schwab_callback_url"]="https://127.0.0.1:8182"
  validate(opts,dict(DEFAULTS),{})
  opts["schwab_callback_url"]="https://8.8.8.8:8768/schwab/callback"
  with self.assertRaises(SetupError):validate(opts,dict(DEFAULTS),{})
 def test_enable_requires_confirmation_and_known_account(self):
  with tempfile.TemporaryDirectory() as td:
   state=Path(td)
   saved=dict(DEFAULTS,ai_provider="none")
   atomic_save(state/"config"/"integrations.json",saved)
   request={"enable":True,"confirmed":False,"account_hash":"mock_verified_account"}
   lookup=lambda _state:{"accounts":[{"hash":"mock_verified_account","label":"Schwab account ending 1234"}]}
   with self.assertRaises(SetupError):toggle(state,request,account_lookup=lookup)
   request["confirmed"]=True
   with self.assertRaises(SetupError):
    toggle(state,request,account_lookup=lambda _state:{"accounts":[]})
   enabled=toggle(state,request,account_lookup=lookup)
   self.assertTrue(enabled["live_enabled"])
   self.assertEqual(operator_mode(state),"running")
   changed=save(state,{"ai_provider":"none","paper_enabled":True})
   self.assertTrue(changed["live_enabled"])
   self.assertTrue(changed["paper_enabled"])
   disabled=toggle(state,{"enable":False,"confirmed":True,"account_hash":""},account_lookup=lookup)
   self.assertFalse(disabled["live_enabled"])
   self.assertEqual(operator_mode(state),"paused")
 def test_never_log_oauth_query(self):
  h=Handler.__new__(Handler)
  h.client_address=("192.168.1.99",5555);h.command="GET"
  output=io.StringIO()
  with redirect_stdout(output):h.log_message("%s","GET /schwab/callback?code=private_secret&state=foo")
  self.assertNotIn("private_secret",output.getvalue())
  self.assertNotIn("state=foo",output.getvalue())
 def test_mocked_callback_checks_state_and_saves_token(self):
  import types
  with tempfile.TemporaryDirectory() as td:
   state=Path(td)
   atomic_save(state/"config"/"integrations.json",
     dict(DEFAULTS,ai_provider="none",schwab_app_key="fake-key",
          schwab_callback_url="https://192.168.1.43:8768/schwab/callback"))
   atomic_save(state/"config"/"credentials.json",{"schwab_app_secret":"dummy-not-real"})
   auth=state/"schwab_oauth_pending.json"
   atomic_save(auth,{"callback":"https://192.168.1.43:8768/schwab/callback",
       "state":"random-nonce","authorization_url":"https://api.schwabapi.com/example",
       "created":time.time()})
   import types,collections
   fake_root=types.ModuleType("schwab")
   module=types.ModuleType("schwab.auth")
   module.AuthContext=collections.namedtuple("AuthContext",["callback_url","authorization_url","state"])
   def fake_exchange(_key,_secret,_ctx,returned,writer,**kw):
    self.assertIn("code=fake-code",returned)
    writer({"access_token":"FAKE_TEST_ONLY"})
   good="https://192.168.1.43:8768/schwab/callback?code=fake-code&state=random-nonce"
   module.client_from_received_url=fake_exchange
   fake_root.auth=module
   with patch.dict(sys.modules,{"schwab":fake_root,"schwab.auth":module}):
    with self.assertRaises(SetupError):finish(state,good.replace("random-nonce","wrong"))
    self.assertEqual(finish(state,good),{"connected":True})
   self.assertTrue((state/"schwab_token.json").exists())
   self.assertEqual((state/"schwab_token.json").stat().st_mode & 0o777,0o600)
   self.assertFalse(auth.exists())
 def test_loopback_root_slash_is_accepted_without_relaxing_host_or_state(self):
  from schwab_web_oauth import _url_matches_registered_callback
  from urllib.parse import urlparse
  target=urlparse("https://127.0.0.1:8182")
  self.assertTrue(_url_matches_registered_callback(target,
    urlparse("https://127.0.0.1:8182/?code=PRIVATE&state=RANDOM")))
  self.assertTrue(_url_matches_registered_callback(urlparse("https://127.0.0.1:8182/"),
    urlparse("https://127.0.0.1:8182?code=PRIVATE&state=RANDOM")))
  for bad in ("https://localhost:8182/?code=PRIVATE","https://127.0.0.1:8183/?code=PRIVATE",
              "http://127.0.0.1:8182/?code=PRIVATE",
              "https://127.0.0.1:8182/evil?code=PRIVATE",
              "https://127.0.0.1:8182/?code=PRIVATE#fragment"):
   self.assertFalse(_url_matches_registered_callback(target,urlparse(bad)))
 def test_actual_loopback_redirect_exchanges_when_browser_adds_slash(self):
  import types,collections
  with tempfile.TemporaryDirectory() as td:
   state=Path(td)
   atomic_save(state/"config"/"integrations.json",
    dict(DEFAULTS,ai_provider="none",schwab_app_key="dummy-test-key",
         schwab_callback_url="https://127.0.0.1:8182"))
   atomic_save(state/"config"/"credentials.json",{"schwab_app_secret":"synthetic-fake"})
   atomic_save(state/"schwab_oauth_pending.json",{
     "callback":"https://127.0.0.1:8182","state":"unique-state",
     "authorization_url":"https://api.schwabapi.com/oauth/authorize?dummy=1","created":time.time()})
   stub=types.ModuleType("schwab")
   auth=types.ModuleType("schwab.auth")
   auth.AuthContext=collections.namedtuple("AuthContext",["callback_url","authorization_url","state"])
   def mock_exchange(_key,_secret,context,received_url,writer,**kwargs):
    self.assertEqual(context.callback_url,"https://127.0.0.1:8182")
    self.assertIn("/?code=fake-code",received_url)
    writer({"access_token":"DUMMY-NOT-A-REAL-TOKEN"})
   auth.client_from_received_url=mock_exchange
   stub.auth=auth
   with patch.dict(sys.modules,{"schwab":stub,"schwab.auth":auth}):
    self.assertEqual(finish(state,
      " https://127.0.0.1:8182/?code=fake-code&state=unique-state "),
      {"connected":True})
   self.assertTrue((state/"schwab_token.json").is_file())
 def test_public_update_lookup(self):
  latest=json.dumps([{"name":"v1.0.7"},{"name":"v0.9.0-beta"},{"name":"v1.0.6"}]).encode()
  class Resp:
   def __enter__(self):return self
   def __exit__(self,*args):pass
   def read(self,_):return latest
  with tempfile.TemporaryDirectory() as td:
   Path(td,"VERSION").write_text("1.0.6\n")
   update_status._public_cache=None
   doc=update_status.public_update_information(td,opener=lambda req,timeout:Resp())
   self.assertTrue(doc["update_available"])
   self.assertEqual(doc["latest"],"1.0.7")
   self.assertIn("github.com",doc["source_url"])

if __name__=="__main__":unittest.main()
