"""Crypto adverse catalyst guard never makes broker order decisions on its own."""
import unittest
from datetime import datetime,timezone
from ai_research import crypto_adverse_catalyst,approve_entry

NOW=datetime(2026,11,3,21,0,tzinfo=timezone.utc)
class AdverseCatalystTests(unittest.TestCase):
 def test_hacker_dump_is_adverse(self):
  self.assertTrue(crypto_adverse_catalyst("Binance hacker dumps 2% PEPE"))
  self.assertTrue(crypto_adverse_catalyst("Hackers offload stolen assets"))
  self.assertFalse(crypto_adverse_catalyst("Bitcoin ETF approval sends inflows higher"))
 def test_bullish_classifier_cannot_approve_hacker_dump(self):
  def headlines(symbol,when):
   return [{"title":"Binance hacker dumps 2% PEPE crypto token",
            "published_at":when.isoformat(),"source":"Simulated"}]
  def classifier(symbol,news):
   return {"ticker":symbol,"sentiment":1,"impact":1,
           "catalyst":"Binance hacker dumps 2% PEPE",
           "downside_risk":"Possible token liquidity reduction",
           "model":"local:fake"}
  approved,reason=approve_entry("PEPE-USD",NOW,headlines,classifier)
  self.assertFalse(approved)
  self.assertIn("material adverse crypto catalyst",reason)
  self.assertIn("NO TRADE",reason)
 def test_positive_catalyst_with_named_downside_risk_still_classifies(self):
  def headlines(symbol,when):
   return [{"title":"PEPE token exchange support expands",
            "published_at":when.isoformat(),"source":"Simulated"}]
  def classifier(symbol,news):
   return {"ticker":symbol,"sentiment":1,"impact":1,
           "catalyst":"PEPE exchange support expands",
           "downside_risk":"Hackers may still cause liquidity concerns",
           "model":"local:fake"}
  approved,reason=approve_entry("PEPE-USD",NOW,headlines,classifier)
  self.assertTrue(approved)
  self.assertIn("PASS",reason)
if __name__=="__main__":unittest.main()
