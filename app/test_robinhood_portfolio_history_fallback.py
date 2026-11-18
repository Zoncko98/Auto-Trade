import unittest
from unittest.mock import patch
from broker_workspace import robinhood_portfolio
from robinhood_crypto_gateway import RobinhoodUnavailable

class PortfolioHistoryFallback(unittest.TestCase):
    def test_broker_history_failure_preserves_cash_and_holdings(self):
        class Broker:
            def list_accounts(self):
                return [{"account_number":"a","buying_power":"91.21","buying_power_currency":"USD"}]
            def orders(self, account):
                raise RobinhoodUnavailable("history pagination unavailable")
            def positions(self, account):
                return [{"asset_code":"XPL","total_quantity":"100","quantity_available_for_trading":"100"}]
            def quote(self, symbol):
                return {"results":[{"symbol":symbol,"bid":"0.045","ask":"0.047"}]}
        with patch("broker_workspace._robinhood_client",return_value=Broker()):
            result=robinhood_portfolio("/nonexistent")
        self.assertTrue(result["available"])
        self.assertEqual(result["cash_usd"],"91.21")
        self.assertEqual(result["position_count"],1)
        self.assertEqual(result["holdings"][0]["market_value_usd"],"4.600")
        self.assertIsNone(result["holdings"][0]["average_cost_usd"])
        self.assertFalse(result["order_history_complete"])
        self.assertIsNone(result["order_count"])

if __name__=="__main__":
    unittest.main()
