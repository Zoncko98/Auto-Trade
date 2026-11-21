"""Strict Ollama transport tests: local mocks, never network or broker calls."""
import json
import unittest
from unittest.mock import patch
from trader_v2.ollama_transport import OllamaReviewTransport

class _Response:
    status = 200
    def __init__(self, payload):
        self.payload = payload
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def read(self, count):
        return self.payload[:count]

class OllamaReviewTransportTests(unittest.TestCase):
    def test_structured_bounded_payload(self):
        api = OllamaReviewTransport("http://localhost:11434", "qwen3.5:4b")
        reply = json.dumps({"message": {"content": '{"symbol":"DEMO","state":"PASS","reason":"ok"}'}}).encode()
        with patch("trader_v2.ollama_transport.urlopen", return_value=_Response(reply)) as mock:
            result = api('{"candidate":{"symbol":"DEMO"}}', 6)
            self.assertIn('"PASS"', result)
            req = mock.call_args.args[0]
            sent = json.loads(req.data)
            self.assertFalse(sent["stream"])
            self.assertEqual(sent["format"]["type"], "object")
            self.assertCountEqual(sent["format"]["required"],
                                  ["symbol","state","reason"])
            self.assertEqual(sent["format"]["properties"]["state"]["enum"],
                             ["PASS","VETO"])
            self.assertFalse(sent["format"]["additionalProperties"])
            self.assertFalse(sent["think"])
            self.assertEqual(sent["options"]["num_predict"],90)
            self.assertEqual(sent["options"]["num_ctx"],2048)
            self.assertEqual(sent["model"], "qwen3.5:4b")
            self.assertEqual(mock.call_args.kwargs["timeout"], 6)
            self.assertEqual(req.full_url, "http://localhost:11434/api/chat")
    def test_fail_on_large_reply(self):
        api = OllamaReviewTransport("http://localhost:11434", "model")
        with patch("trader_v2.ollama_transport.urlopen", return_value=_Response(b"x"*16385)):
            with self.assertRaises(ValueError):
                api("{}", 5)
    def test_invalid_endpoint(self):
        for url in ("file:///etc/passwd", "ftp://localhost", "http://user:pass@host", "https://host?key=abc"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                OllamaReviewTransport(url, "model")
    def test_no_broker_authority(self):
        import trader_v2.ollama_transport as module
        from pathlib import Path
        source = Path(module.__file__).read_text(encoding="utf-8")
        self.assertNotIn("broker.submit", source)
        self.assertNotIn("place_order", source)
