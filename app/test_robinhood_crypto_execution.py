import base64
import json
import unittest
import uuid
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PrivateFormat, NoEncryption
from robinhood_crypto_gateway import RobinhoodUnavailable
from robinhood_crypto_execution import RobinhoodCryptoTradingAdapter

class ExecutionTests(unittest.TestCase):
    def setUp(self):
        self.signer = Ed25519PrivateKey.generate()
        encoded = base64.b64encode(self.signer.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())).decode()
        self.calls = []
        def read(path, headers):
            return {"results": [{"account_number": "1234", "status": "active", "is_api_tradable": True}]}
        def write(path, body, headers):
            self.calls.append((path, body, headers))
            return {"id": "mock-order"}
        self.credentials = dict(api_key="test-key", private_key_b64=encoded, transport=read, write_transport=write,
                                clock=lambda: 123, allowed_accounts=["1234"])
        self.intent = {"side": "buy", "type": "limit", "symbol": "BTC-USD",
                       "client_order_id": str(uuid.uuid4()), "asset_quantity": "0.001",
                       "limit_price": "10000", "risk_approved": True, "operator_approved": True}

    def test_disabled_by_default(self):
        client = RobinhoodCryptoTradingAdapter(**self.credentials)
        with self.assertRaises(RobinhoodUnavailable):
            client.submit_order("1234", self.intent)
        self.assertFalse(self.calls)

    def test_signed_approved_order(self):
        client = RobinhoodCryptoTradingAdapter(**self.credentials, live_enabled=True)
        client.submit_order("1234", self.intent)
        self.assertEqual(len(self.calls), 1)
        path, body, headers = self.calls[0]
        self.assertEqual(path, "/api/v2/crypto/trading/orders/?account_number=1234")
        self.assertEqual(json.loads(body)["symbol"], "BTC-USD")
        self.signer.public_key().verify(base64.b64decode(headers["x-signature"]),
            ("test-key123" + path + "POST" + body).encode())

    def test_cross_account_rejected(self):
        client = RobinhoodCryptoTradingAdapter(**self.credentials, live_enabled=True)
        with self.assertRaises(RobinhoodUnavailable):
            client.submit_order("other", self.intent)
        self.assertFalse(self.calls)

    def test_limit_rejected(self):
        client = RobinhoodCryptoTradingAdapter(**self.credentials, live_enabled=True)
        self.intent["asset_quantity"] = "100"
        with self.assertRaises(RobinhoodUnavailable):
            client.submit_order("1234", self.intent)
        self.assertFalse(self.calls)

    def test_missing_approval_rejected(self):
        client = RobinhoodCryptoTradingAdapter(**self.credentials, live_enabled=True)
        self.intent["operator_approved"] = False
        with self.assertRaises(RobinhoodUnavailable):
            client.submit_order("1234", self.intent)
        self.assertFalse(self.calls)

    def test_cancel_signing(self):
        client = RobinhoodCryptoTradingAdapter(**self.credentials, live_enabled=True)
        uid = str(uuid.uuid4())
        client.cancel_order("1234", uid)
        self.assertEqual(self.calls[0][0], f"/api/v2/crypto/trading/orders/{uid}/cancel/")
        self.assertEqual(self.calls[0][1], "")

if __name__ == "__main__":
    unittest.main()
