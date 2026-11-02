import base64
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PrivateFormat, NoEncryption
from broker_workspace import install_robinhood_credentials, robinhood_status
from robinhood_crypto_gateway import RobinhoodCryptoAdapter

class RobinhoodCredentialTests(unittest.TestCase):
    def test_installer_uses_private_file_and_returns_no_secret(self):
        with tempfile.TemporaryDirectory() as temp:
            key=Ed25519PrivateKey.generate()
            encoded=base64.b64encode(key.private_bytes(Encoding.Raw,PrivateFormat.Raw,NoEncryption())).decode()
            out=install_robinhood_credentials(temp,{"api_key":"rh-api-example","private_key_b64":encoded})
            path=Path(temp)/"config"/"robinhood_crypto.json"
            self.assertTrue(path.is_file())
            self.assertFalse(path.stat().st_mode & 0o077)
            self.assertNotIn(encoded,json.dumps(out))
            self.assertNotIn("rh-api-example",json.dumps(out))
            self.assertEqual(RobinhoodCryptoAdapter.from_state(temp)._api_key,"rh-api-example")
            self.assertEqual(out["connected"],False)

    def test_missing_credentials_no_account_data(self):
        with tempfile.TemporaryDirectory() as temp:
            result=robinhood_status(temp)
            self.assertFalse(result["connected"])
            self.assertFalse(result["order_execution_enabled"])

    def test_rejects_malformed_key(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(ValueError):
                install_robinhood_credentials(temp,{"api_key":"x","private_key_b64":"x"})
            self.assertFalse((Path(temp)/"config"/"robinhood_crypto.json").exists())

if __name__=="__main__":
    unittest.main()
