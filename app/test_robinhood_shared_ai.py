import unittest
from ai_research import approve_entry,COMPANIES,crypto_headline_relevant
from datetime import datetime,timezone
class SharedCryptoAI(unittest.TestCase):
 def test_crypto_universe_uses_shared_research(self):
  for pair in ("BTC-USD","ETH-USD","SOL-USD","DOGE-USD"):
   self.assertIn(pair,COMPANIES)
 def test_crypto_approval_is_validated_and_not_inferred(self):
  now=datetime(2026,11,2,21,tzinfo=timezone.utc)
  headlines=lambda symbol,now:[{"title":"Bitcoin blockchain network upgrade confirmed","source":"publisher","published_at":now.isoformat()}]
  model=lambda symbol,news:{"ticker":symbol,"model":"local:qwen3.5:4b",
     "sentiment":1,"impact":2,"catalyst":"milestone","downside_risk":"competition"}
  passed,reason=approve_entry("BTC-USD",now,get_headlines=headlines,classifier=model)
  self.assertTrue(passed)
  self.assertIn("sentiment=1",reason)
  eth_news=lambda symbol,now:[{"title":"Ethereum blockchain network upgrade",
      "source":"publisher","published_at":now.isoformat()}]
  denied,_=approve_entry("ETH-USD",now,get_headlines=eth_news,
     classifier=lambda s,n:dict(model(s,n),sentiment=0))
  self.assertFalse(denied)


class CryptoRelevanceGate(unittest.TestCase):
 def test_chip_hardware_headline_not_crypto_evidence(self):
  now=datetime(2026,11,3,0,tzinfo=timezone.utc)
  news=lambda s,n:[{"title":"Strong iPhone 18 Pro sales help Apple chip suppliers",
                    "source":"News","published_at":now.isoformat()}]
  def prohibited_classifier(s,rows):
   raise AssertionError("No AI approval should be requested for unrelated headlines")
  passed,reason=approve_entry("CHIP-USD",now,get_headlines=news,classifier=prohibited_classifier)
  self.assertFalse(passed)
  self.assertIn("No headlines explicitly tied",reason)
 def test_ticker_with_crypto_context(self):
  self.assertTrue(crypto_headline_relevant("CHIP-USD",
     {"title":"CHIP token launches on cryptocurrency exchange"}))
  self.assertFalse(crypto_headline_relevant("CHIP-USD",
     {"title":"CHIP semiconductor production boosts Apple sales"}))
 def test_crypto_alias(self):
  self.assertTrue(crypto_headline_relevant("BTC-USD",
     {"title":"Bitcoin blockchain miners announce upgrade"}))
