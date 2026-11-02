import unittest
from ai_research import approve_entry,COMPANIES
from datetime import datetime,timezone
class SharedCryptoAI(unittest.TestCase):
 def test_crypto_universe_uses_shared_research(self):
  for pair in ("BTC-USD","ETH-USD","SOL-USD","DOGE-USD"):
   self.assertIn(pair,COMPANIES)
 def test_crypto_approval_is_validated_and_not_inferred(self):
  now=datetime(2026,11,2,21,tzinfo=timezone.utc)
  headlines=lambda symbol,now:[{"title":"real news","source":"publisher","published_at":now.isoformat()}]
  model=lambda symbol,news:{"ticker":symbol,"model":"local:qwen3.5:4b",
     "sentiment":1,"impact":2,"catalyst":"milestone","downside_risk":"competition"}
  passed,reason=approve_entry("BTC-USD",now,get_headlines=headlines,classifier=model)
  self.assertTrue(passed)
  self.assertIn("sentiment=1",reason)
  denied,_=approve_entry("ETH-USD",now,get_headlines=headlines,
     classifier=lambda s,n:dict(model(s,n),sentiment=0))
  self.assertFalse(denied)
