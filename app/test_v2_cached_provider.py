"""Cached read-only quote/candle provider contract tests."""
import json,tempfile,unittest
from datetime import datetime,timezone,timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
from trader_v2.cached_provider import CachedMarketDataProvider
from trader_v2.contracts import MarketDataProvider
from trader_v2.market_sources import MarketSourceError
from trader_v2.models import AssetClass

class CachedProviderContract(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
  self.root=Path(self.temp.name)
  self.now=datetime.now(timezone.utc).replace(microsecond=0)
  self.ts=self.now.isoformat()
  self.provider=CachedMarketDataProvider(self.root)
 def write(self,path,data):
  p=self.root/path;p.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
  p.write_text(json.dumps(data));p.chmod(0o600)
 def test_protocol_and_unauthorized_quote_do_not_fetch_or_guess(self):
  self.assertTrue(isinstance(self.provider,MarketDataProvider))
  with self.assertRaises(MarketSourceError):
   self.provider.snapshot("SOFI",AssetClass.STOCK)
 def test_schwab_quote_is_inert_even_with_fresh_last_trade(self):
  self.write("live/broker_market_snapshot.json",{
   "schema":1,"source":"schwab_broker_quotes","observed_at":self.ts,
   "symbols":{"SOFI":{"bid":9.98,"ask":10.01,"last":10,
      "tradable":True,"quote_timestamp":self.ts}}})
  with patch("trader_v2.cached_provider.datetime") as clock:
   clock.now.return_value=self.now
   clock.side_effect=datetime
   q=self.provider.quote("SOFI",AssetClass.STOCK)
   snapshot=self.provider.snapshot("SOFI",AssetClass.STOCK)
  self.assertEqual(q.bid,Decimal("9.98"))
  self.assertFalse(snapshot.market_open)
 def test_crypto_external_midpoint_cannot_enable_execution(self):
  self.write("robinhood/coinbase_market.json",{
   "quotes":{"BTC-USD":{"at":self.ts,
        "bid":"60000","ask":"60020","mid":"60010"}}})
  with patch("trader_v2.cached_provider.datetime") as clock:
   clock.now.return_value=self.now
   clock.side_effect=datetime
   quote=self.provider.quote("BTC-USD",AssetClass.CRYPTO)
   with self.assertRaisesRegex(MarketSourceError,"TRADE_LAST_UNVERIFIED"):
    self.provider.snapshot("BTC-USD",AssetClass.CRYPTO)
  self.assertFalse(quote.broker_executable)
 def test_replay_candles_are_explicitly_configured(self):
  with self.assertRaisesRegex(MarketSourceError,"PAPER_REPLAY_NOT_CONFIGURED"):
   self.provider.candles("SPY",AssetClass.STOCK,5)
  path=self.root/"archive.csv"
  path.write_text("timestamp,symbol,price\n"+
     (self.now-timedelta(minutes=4)).isoformat()+",SPY,100\n")
  provider=CachedMarketDataProvider(self.root,replay_csv=path)
  with patch("trader_v2.cached_provider.paper_candles_csv") as reader:
   reader.return_value=["verified"]
   self.assertEqual(provider.candles("SPY",AssetClass.STOCK,5),["verified"])
   reader.assert_called_once_with(path,"SPY",count=5)

if __name__=="__main__":unittest.main()
