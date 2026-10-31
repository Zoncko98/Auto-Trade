"""Contract tests for the model-veto layer; all HTTP responses are mocked."""
import json
import unittest
from unittest.mock import patch
from urllib.error import URLError

from ai_review import OllamaReviewer


class FakeHTTP:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, _limit):
        return self.payload


def ollama_response(decision, reason="Model reviewed available evidence", flags=None):
    body = {"decision": decision, "reason": reason, "risk_flags": flags or []}
    return FakeHTTP(json.dumps({"done": True, "response": json.dumps(body)}).encode())


class AIReviewTests(unittest.TestCase):
    def setUp(self):
        self.reviewer = OllamaReviewer("http://127.0.0.1:11434/api/generate",
                                       "sample-model", timeout_seconds=2)
        self.candidate = {
            "trade_type": "PAPER_BUY", "symbol": "SPY", "price": 10.0,
            "quantity": 2.0, "max_position_pct": 25.0, "last_prices": [10, 9, 8, 9, 11]
        }

    def test_valid_approval(self):
        with patch("ai_review.urlopen", return_value=ollama_response("APPROVE")) as urlopen:
            result = self.reviewer.review(self.candidate)
        self.assertTrue(result.approved)
        self.assertEqual(result.model, "sample-model")
        req = urlopen.call_args.args[0]
        body = json.loads(req.data)
        self.assertEqual(body["stream"], False)
        self.assertEqual(body["options"]["temperature"], 0)
        self.assertIn("format", body)
        self.assertNotIn("authorization", req.headers)

    def test_authenticated_open_webui_proxy(self):
        reviewer = OllamaReviewer("http://192.168.1.43:31028/ollama/api/generate",
                                  "local-model", token="mock-secret-token")
        with patch("ai_review.urlopen", return_value=ollama_response("REJECT")) as call:
            result = reviewer.review(self.candidate)
        self.assertFalse(result.approved)
        req = call.call_args.args[0]
        self.assertEqual(req.headers["Authorization"], "Bearer mock-secret-token")
        self.assertNotIn("mock-secret-token", result.reason)

    def test_explicit_veto(self):
        with patch("ai_review.urlopen", return_value=ollama_response("REJECT")):
            self.assertFalse(self.reviewer.review(self.candidate).approved)

    def test_risk_flags_override_approval(self):
        with patch("ai_review.urlopen",
                   return_value=ollama_response("APPROVE", flags=["insufficient evidence"])):
            result = self.reviewer.review(self.candidate)
        self.assertFalse(result.approved)

    def test_malformed_response_fails_closed(self):
        with patch("ai_review.urlopen", return_value=FakeHTTP(b'{"done":true,"response":"{}"}')):
            self.assertFalse(self.reviewer.review(self.candidate).approved)

    def test_missing_endpoint_fails_closed(self):
        self.assertFalse(OllamaReviewer().review(self.candidate).approved)

    def test_http_outage_fails_closed(self):
        with patch("ai_review.urlopen", side_effect=URLError("offline")):
            result = self.reviewer.review(self.candidate)
        self.assertFalse(result.approved)
        self.assertIn("unavailable", result.reason)

    def test_incomplete_generation_fails_closed(self):
        with patch("ai_review.urlopen",
                   return_value=FakeHTTP(b'{"done":false,"response":"{}"}')):
            self.assertFalse(self.reviewer.review(self.candidate).approved)

    def test_external_endpoint_rejected(self):
        with self.assertRaises(ValueError):
            OllamaReviewer("https://example.com/api/generate", "model")

    def test_unsafe_url_credentials_rejected(self):
        with self.assertRaises(ValueError):
            OllamaReviewer("http://user:pass@127.0.0.1:11434/api/generate", "model")


if __name__ == "__main__":
    unittest.main(verbosity=2)
