import base64
import unittest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PrivateFormat, NoEncryption
from robinhood_crypto_gateway import RobinhoodCryptoAdapter, RobinhoodUnavailable

def sample_key():
    return base64.b64encode(Ed25519PrivateKey.generate().private_bytes(
        Encoding.Raw, PrivateFormat.Raw, NoEncryption())).decode()

class RobinhoodTests(unittest.TestCase):
    def setUp(self):
        self.paths = []
        def transport(path, headers):
            self.paths.append((path, headers))
            if path.endswith("/accounts/"):
                return {"results": [{"account_number": "12345", "buying_power": "100"}]}
            return {"results": []}
        self.adapter = RobinhoodCryptoAdapter("api-id", sample_key(), transport=transport, clock=lambda: 100)

    def test_list_accounts_signed(self):
        self.assertEqual(self.adapter.list_accounts()[0]["account_number"], "12345")
        self.assertTrue(self.paths[0][1]["x-signature"])

    def test_balance(self):
        self.assertEqual(self.adapter.balances("12345")["buying_power"], "100")

    def test_fail_closed(self):
        with self.assertRaises(RobinhoodUnavailable):
            self.adapter.submit_order("12345", {"symbol": "BTC-USD"})
        with self.assertRaises(RobinhoodUnavailable):
            self.adapter.cancel_order("12345", "order")

    def test_invalid_symbol(self):
        with self.assertRaises(ValueError):
            self.adapter.quote("../secret")

if __name__ == "__main__":
    unittest.main()
