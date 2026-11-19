import json,time,unittest
from unittest.mock import patch
from decimal import Decimal
from robinhood_portfolio_quotes import _parse_usdc_response,get_display_only_mark
from broker_workspace import robinhood_portfolio
from robinhood_crypto_gateway import RobinhoodUnavailable

class ExternalUsdCoinMarkTests(unittest.TestCase):
 def data(self,usd="0.99975",offset=-20,now=1800000000):
  return json.dumps({"usd-coin":{"usd":usd,"last_updated_at":now+offset}})
 def test_current_canonical_usdc_is_allowed(self):
  quote=get_display_only_mark("USDC-USD",fetch=lambda:self.data(),now=1800000000)
  self.assertEqual(quote["price"],Decimal("0.99975"))
  self.assertEqual(quote["source"],"CoinGecko USDC/USD indicative")
 def test_other_symbols_never_receive_a_fallback(self):
  for symbol in ("USDT-USD","BTC-USD","USDC-EUR","FAKEUSDC-USD"):
   self.assertIsNone(get_display_only_mark(symbol,fetch=lambda: (_ for _ in ()).throw(AssertionError("network called")),now=1800000000))
 def test_invalid_prices_and_timestamps_refused(self):
  for data in [self.data(usd="NaN"),self.data(usd="-1"),self.data(usd="0"),
               self.data(usd="9999"),self.data(offset=-301),self.data(offset=10),
               "{}","not-json",self.data().replace('"last_updated_at":','"last_updated_at": "')]:
   self.assertIsNone(get_display_only_mark("USDC-USD",fetch=lambda d=data:d,now=1800000000))
 def test_large_payload_and_network_failure_are_safe(self):
  self.assertIsNone(_parse_usdc_response("x"*4097,1800000000))
  def unavailable():raise OSError("offline")
  self.assertIsNone(get_display_only_mark("USDC-USD",fetch=unavailable,now=1800000000))
 def test_broker_quote_failure_still_prices_only_usdc(self):
  class Broker:
   def list_accounts(self):return [{"account_number":"demo","buying_power":"20.00","buying_power_currency":"USD"}]
   def orders(self,ref):return []
   def positions(self,ref):return [{"asset_code":"USDC","total_quantity":"12.5","quantity_available_for_trading":"12.5"}]
   def quote(self,symbol):raise RobinhoodUnavailable("broker has no quote")
  mark={"price":Decimal("0.99975"),"source":"CoinGecko USDC/USD indicative","as_of":"2026-11-19T03:50:00+00:00"}
  with patch("broker_workspace._robinhood_client",return_value=Broker()),patch("robinhood_portfolio_quotes.get_display_only_mark",return_value=mark):
   out=robinhood_portfolio("/state")
  self.assertTrue(out["available"])
  self.assertEqual(out["holdings"][0]["market_value_usd"],"12.496875")
  self.assertEqual(out["holdings"][0]["valuation"],"coingecko_usdc_usd_indicative")
  self.assertEqual(out["valuation_coverage"]["externally_marked"],1)
  self.assertEqual(out["estimated_crypto_account_value_usd"],"32.496875")
  self.assertIsNone(out["unrealized_pnl_usd"])
 def test_no_external_price_does_not_claim_zero_value(self):
  class Broker:
   def list_accounts(self):return [{"account_number":"demo","buying_power":"1","buying_power_currency":"USD"}]
   def orders(self,ref):return []
   def positions(self,ref):return [{"asset_code":"USDC","total_quantity":"2"}]
   def quote(self,symbol):raise RobinhoodUnavailable("broker has no quote")
  with patch("broker_workspace._robinhood_client",return_value=Broker()),patch("robinhood_portfolio_quotes.get_display_only_mark",return_value=None):
   out=robinhood_portfolio("/state")
  self.assertIsNone(out["estimated_crypto_account_value_usd"])
  self.assertEqual(out["valuation_coverage"]["priced"],0)
  self.assertEqual(out["unpriced_holdings"],["USDC-USD"])

if __name__=="__main__":unittest.main()
