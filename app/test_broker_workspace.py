"""Broker-agnostic workspace and fail-closed broker adapter contract tests."""
import tempfile,unittest,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from broker_workspace import (
    providers,workspace_summary,UnavailableBrokerAdapter,BrokerNotAvailable)

class BrokerWorkspaceTests(unittest.TestCase):
    def test_no_broker_connection_claims_without_authorization(self):
        with tempfile.TemporaryDirectory() as folder:
            doc=workspace_summary(folder)
            self.assertEqual(doc["schema"],1)
            self.assertEqual(doc["live_execution_broker"],"schwab")
            ids=[b["id"] for b in doc["brokers"]]
            self.assertEqual(len(set(ids)),len(ids))
            self.assertEqual(set(ids),{
                "schwab","webull","alpaca","robinhood_crypto","interactive_brokers"})
            for broker in doc["brokers"]:
                self.assertFalse(broker["app_account_connected"])
                self.assertFalse(broker["app_orders_supported"])
                self.assertIn("https://",broker["docs_url"])
    def test_stored_token_does_not_enable_other_brokers(self):
        with tempfile.TemporaryDirectory() as folder:
            state=Path(folder)
            (state/"schwab_token.json").write_text('{"synthetic_test_secret":"NEVER_SHOW_TEST_TOKEN"}')
            doc=workspace_summary(state)
            schwab=next(b for b in doc["brokers"] if b["id"]=="schwab")
            self.assertTrue(schwab["app_account_connected"])
            self.assertTrue(schwab["app_orders_supported"])
            self.assertIn("authorization file saved",schwab["setup_requirement"].lower())
            self.assertNotIn("NEVER_SHOW_TEST_TOKEN",str(doc))
            for provider in doc["brokers"]:
                if provider["id"]!="schwab":
                    self.assertFalse(provider["app_orders_supported"])
                    self.assertFalse(provider["app_account_connected"])
    def test_unsupported_brokers_fail_closed(self):
        for name in ("webull","alpaca","robinhood_crypto","interactive_brokers"):
            adapter=UnavailableBrokerAdapter(name)
            for method,params in (
                ("list_accounts",()),("balances",("account",)),
                ("positions",("account",)),("quote",("SOFI",)),
                ("orders",("account",)),
                ("submit_order",("account",{"symbol":"SOFI","qty":1})),
                ("cancel_order",("account","order123"))):
                with self.subTest(provider=name,method=method),self.assertRaises(BrokerNotAvailable):
                    getattr(adapter,method)(*params)
    def test_unknown_provider_never_gets_adapter(self):
        with self.assertRaises(ValueError):
            UnavailableBrokerAdapter("unverified-broker")
    def test_robinhood_official_stock_orders_not_misrepresented(self):
        with tempfile.TemporaryDirectory() as folder:
            providers_by_id={p["id"]:p for p in providers(folder)}
            self.assertEqual(providers_by_id["robinhood_crypto"]["assets"],("crypto",))
            self.assertFalse(providers_by_id["robinhood_crypto"]["app_orders_supported"])
            self.assertFalse(providers_by_id["webull"]["app_orders_supported"])
            self.assertFalse(providers_by_id["alpaca"]["app_orders_supported"])

if __name__=="__main__":unittest.main()
