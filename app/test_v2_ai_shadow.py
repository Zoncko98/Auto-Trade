"""Shared Ollama shadow AI: typed evidence only, never order authority."""
from datetime import datetime,timedelta,timezone
from decimal import Decimal
from unittest.mock import patch
import unittest

from trader_v2.ai_shadow import shadow_review
from trader_v2.models import AssetClass,MarketSnapshot,Candidate,OrderSide
from trader_v2.public_crypto import SOURCE

class ShadowAITests(unittest.TestCase):
    def setUp(self):
        self.now=datetime.now(timezone.utc)
        self.quote=MarketSnapshot("BTCUSD",AssetClass.CRYPTO,SOURCE,
            self.now-timedelta(seconds=1),self.now,
            Decimal("9990"),Decimal("10000"),Decimal("9999"),True)
        self.candidate=Candidate("crypto_sma","baseline-1","v2-paper-btcusd",
            "BTCUSD",AssetClass.CRYPTO,OrderSide.BUY,
            self.now-timedelta(seconds=5),{"indicator":"SMA_CROSS"})

    def test_unconfigured_model_is_explicit_and_no_network(self):
        with patch("trader_v2.ai_shadow.OllamaReviewTransport") as net:
            result=shadow_review(self.candidate,self.quote,env={})
        self.assertEqual(result["state"],"NOT_CONFIGURED")
        self.assertFalse(result["changed_order_authority"])
        net.assert_not_called()

    def test_model_pass_is_typed_and_time_bounded(self):
        response='{"symbol":"BTCUSD","state":"PASS","reason":"qualified pattern"}'
        with patch("trader_v2.ai_shadow.OllamaReviewTransport",
                   return_value=lambda request,timeout:response):
            result=shadow_review(self.candidate,self.quote,
                                 env={"AI_MODEL":"synthetic-llm",
                                      "AI_OLLAMA_URL":"http://localhost:11434"})
        self.assertEqual(result["state"],"PASS")
        self.assertEqual(result["model"],"synthetic-llm")
        self.assertIn("reviewed_at",result)
        self.assertFalse(result["changed_order_authority"])

    def test_model_veto_and_wrong_symbol_are_distinct(self):
        for reply,expected in [
           ('{"symbol":"BTCUSD","state":"VETO","reason":"no event"}',"VETO"),
           ('{"symbol":"ETHUSD","state":"PASS","reason":"wrong"}',"UNAVAILABLE"),
           ('{"symbol":"BTCUSD","state":"ORDER","reason":"unsafe"}',"UNAVAILABLE"),
           ("not JSON","UNAVAILABLE")]:
            with self.subTest(reply=reply):
                with patch("trader_v2.ai_shadow.OllamaReviewTransport",
                           return_value=lambda req,timeout,doc=reply:doc):
                    result=shadow_review(self.candidate,self.quote,
                        env={"AI_MODEL":"synthetic-llm",
                             "AI_OLLAMA_URL":"http://localhost:11434"})
                self.assertEqual(result["state"],expected)
                self.assertFalse(result["changed_order_authority"])

    def test_transport_failure_is_explicit_unavailable(self):
        def transport(req,timeout):raise TimeoutError("test")
        with patch("trader_v2.ai_shadow.OllamaReviewTransport",
                   return_value=transport):
            result=shadow_review(self.candidate,self.quote,
                     env={"AI_MODEL":"synthetic-llm",
                          "AI_OLLAMA_URL":"http://localhost:11434"})
        self.assertEqual(result["state"],"UNAVAILABLE")
        self.assertEqual(result["reason"],"MODEL_TIMEOUT")
        self.assertFalse(result["changed_order_authority"])

if __name__=="__main__":unittest.main()
