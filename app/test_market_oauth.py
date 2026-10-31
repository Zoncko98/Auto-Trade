import json,os,sys,tempfile,unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent))
import broker_market_data as broker
import oauth_ai_gateway as oauth

class FakeResponse:
 def __init__(self,payload):self.bytes=json.dumps(payload).encode()
 def __enter__(self):return self
 def __exit__(self,*args):return False
 def read(self,limit):return self.bytes[:limit]

class MarketFeedTests(unittest.TestCase):
 def test_sanitizes_out_account_details(self):
  now=datetime(2026,10,30,tzinfo=timezone.utc)
  payload={"SOFI":{"quote":{"bidPrice":10.2,"askPrice":10.3,"lastPrice":10.25,
         "totalVolume":1234567,"quoteTime":1793376000000},
         "isTradable":True,"accountHash":"secret-should-not-appear"},
         "AAL":{"quote":{"bidPrice":15,"askPrice":14,"lastPrice":14.5}}}
  doc=broker.normalized_quotes(payload,requested=("SOFI","AAL"),now=now)
  self.assertIn("SOFI",doc["symbols"])
  self.assertNotIn("AAL",doc["symbols"])
  self.assertNotIn("secret-should-not-appear",json.dumps(doc))
  with tempfile.TemporaryDirectory() as td:
   broker.write_snapshot(td,doc)
   self.assertEqual((Path(td)/broker.FILENAME).stat().st_mode & 0o777,0o600)
   fresh=broker.read_snapshot(td,now=now+timedelta(seconds=20))
   self.assertEqual(fresh["status"],"fresh")
   old=broker.read_snapshot(td,now=now+timedelta(minutes=4))
   self.assertEqual(old["status"],"stale")
   self.assertNotIn("symbols",old)
 def test_rejects_bogus_broker_response(self):
  with self.assertRaises(broker.MarketDataUnavailable):
   broker.normalized_quotes([1,2])

class OAuthBridgeTests(unittest.TestCase):
 def settings(self,provider):
  return {"AI_PROVIDER":provider,"OAUTH_AI_URL":"http://192.168.1.100:8767",
          "OAUTH_AI_BRIDGE_TOKEN":"example-long-bridge-secret-123456",
          "OAUTH_AI_MODEL":"gpt-6" if provider=="chatgpt-oauth" else "gemini-2.5-flash"}
 def test_only_private_connection(self):
  for provider in ("chatgpt-oauth","gemini-oauth"):
   p,url,token,model=oauth._settings(self.settings(provider))
   self.assertEqual(p,provider)
  settings=self.settings("chatgpt-oauth")
  settings["OAUTH_AI_URL"]="http://8.8.8.8:8767"
  with self.assertRaises(oauth.OAuthAIUnavailable):oauth._settings(settings)
 def test_accepted_response_is_strict(self):
  env=self.settings("chatgpt-oauth")
  valid={"provider":"chatgpt-oauth","ticker":"SOFI","sentiment":1,"impact":1,
         "catalyst":"Quarterly report","downside_risk":"Rate risk"}
  class FakeOpener:
   def __call__(self,req,timeout=0):
    self.assert_placeholder=True
    return FakeResponse(valid)
  with patch.dict(os.environ,env,clear=False):
   result=oauth.classify_news("SOFI",[{"title":"News","source":"Paper",
                                      "published_at":"2026-10-30T12:00:00Z"}],
                                opener=FakeOpener())
  self.assertEqual(result["sentiment"],1)
  self.assertIsNone(result["calibrated_win_probability"])
  valid["sentiment"]=True
  with patch.dict(os.environ,env,clear=False):
   with self.assertRaises(oauth.OAuthAIUnavailable):
    oauth.classify_news("SOFI",[{"title":"News","source":"Paper",
                                      "published_at":"2026-10-30T12:00:00Z"}],
                                opener=FakeOpener())
if __name__=="__main__":unittest.main()
