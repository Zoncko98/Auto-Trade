"""V2 normalized read-only market evidence and replay tests."""
import json,tempfile,unittest
from datetime import datetime,timezone,timedelta
from decimal import Decimal as D
from pathlib import Path
from trader_v2.models import AssetClass
from trader_v2.market_sources import (
 MarketSourceError,schwab_market_quote,webull_market_quote,
 robinhood_market_quote,coinbase_cached_quote,paper_candles_csv,
 cached_market_status)

class MarketProviderTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
  self.root=Path(self.temp.name)
  self.now=datetime.now(timezone.utc).replace(microsecond=0)
  self.at=self.now.isoformat()
 def schwab(self):
  return {"schema":1,"source":"schwab_broker_quotes","observed_at":self.at,
    "symbols":{"SOFI":{"bid":9.98,"ask":10,"last":9.99,
      "tradable":True,"quote_timestamp":self.at}}}
 def write(self,path,data):
  p=self.root/path;p.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
  p.write_text(json.dumps(data));p.chmod(0o600)
  return p
 def test_schwab_quotes_are_readonly_with_real_exchange_timestamps(self):
  q=schwab_market_quote(self.schwab(),"SOFI",now=self.now)
  self.assertEqual(q.bid,D("9.98"))
  self.assertFalse(q.broker_executable)
  self.assertFalse(q.to_inert_snapshot().market_open)
 def test_schwab_stale_exchange_timestamp_rejected_despite_fresh_file(self):
  doc=self.schwab();doc["symbols"]["SOFI"]["quote_timestamp"]=(self.now-timedelta(minutes=10)).isoformat()
  with self.assertRaisesRegex(MarketSourceError,"EXCHANGE_QUOTE_STALE"):
   schwab_market_quote(doc,"SOFI",now=self.now)
 def test_schwab_missing_exchange_timestamp_cannot_use_collection_time(self):
  doc=self.schwab();doc["symbols"]["SOFI"]["quote_timestamp"]=None
  with self.assertRaisesRegex(MarketSourceError,"QUOTE_TIMESTAMP_INVALID"):
   schwab_market_quote(doc,"SOFI",now=self.now)
 def test_schwab_no_entitlement_inferred_from_tradable_flag(self):
  doc=self.schwab();doc["realtime_entitlement_unverified"]=True
  self.assertFalse(schwab_market_quote(doc,"SOFI",now=self.now).to_inert_snapshot().market_open)
 def test_webull_bid_ask_from_real_market_response(self):
  doc={"symbol":"SOFI","quote_time":self.at,"bids":[{"price":"9.99"}],
    "asks":[{"price":"10"}],"last":"10"}
  q=webull_market_quote(doc,"SOFI",now=self.now)
  self.assertEqual(q.source,"webull_openapi");self.assertEqual(q.last,D("10"))
  with self.assertRaisesRegex(MarketSourceError,"WEBULL_SYMBOL_UNVERIFIED"):
   webull_market_quote(doc,"AAPL",now=self.now)
 def test_webull_no_last_cannot_fake_executable_market_snapshot(self):
  doc={"symbol":"SOFI","quote_time":self.at,"bid":"9.9","ask":"10"}
  q=webull_market_quote(doc,"SOFI",now=self.now)
  self.assertIsNone(q.last)
  with self.assertRaisesRegex(MarketSourceError,"TRADE_LAST_UNVERIFIED"):
   q.to_inert_snapshot()
 def test_signed_robinhood_quote_requires_venue_time(self):
  doc={"results":[{"symbol":"BTC-USD","bid":"60000","ask":"60010"}]}
  with self.assertRaisesRegex(MarketSourceError,"QUOTE_TIMESTAMP_INVALID"):
   robinhood_market_quote(doc,"BTC-USD",now=self.now)
  doc["results"][0]["timestamp"]=self.at
  q=robinhood_market_quote(doc,"BTC-USD",now=self.now)
  self.assertFalse(q.broker_executable)
  self.assertEqual(q.asset_class,AssetClass.CRYPTO)
 def test_coinbase_midpoint_not_presented_as_last_trade(self):
  doc={"quotes":{"BTC-USD":{"at":self.at,"mid":"60005",
    "bid":"60000","ask":"60010"}}}
  q=coinbase_cached_quote(doc,"BTC-USD",now=self.now)
  self.assertIsNone(q.last)
  with self.assertRaisesRegex(MarketSourceError,"TRADE_LAST_UNVERIFIED"):
   q.to_inert_snapshot()
 def test_future_quotes_and_crossed_market_are_rejected(self):
  doc={"symbol":"AAPL","quote_time":self.at,"bid":"10.1",
       "ask":"10","last":"10"}
  with self.assertRaises(ValueError):
   webull_market_quote(doc,"AAPL",now=self.now)
  doc["bid"]="9.9"
  doc["quote_time"]=(self.now+timedelta(minutes=10)).isoformat()
  with self.assertRaisesRegex(MarketSourceError,"EXCHANGE_QUOTE_STALE"):
   webull_market_quote(doc,"AAPL",now=self.now)
 def test_paper_replay_uses_only_closed_one_minute_bars(self):
  p=self.root/"public-paper.csv"
  p.write_text("timestamp,symbol,price\n"+
    (self.now-timedelta(minutes=5)).isoformat()+",SPY,500\n"+
    (self.now-timedelta(seconds=20)).isoformat()+",SPY,999\n")
  result=paper_candles_csv(p,"SPY",now=self.now)
  self.assertEqual(len(result),1)
  self.assertEqual(result[0].observed_at,self.now-timedelta(minutes=4))
  self.assertEqual(result[0].close,D("500"))
  self.assertTrue(result[0].closed)
 def test_duplicate_replay_candles_rejected(self):
  p=self.root/"public-paper.csv"
  row=(self.now-timedelta(minutes=4)).isoformat()+",SPY,500\n"
  p.write_text("timestamp,symbol,price\n"+row+row)
  with self.assertRaisesRegex(MarketSourceError,"DUPLICATE_CANDLE"):
   paper_candles_csv(p,"SPY",now=self.now)
 def test_cached_source_coverage_avoids_network_calls_and_invented_quotes(self):
  self.write("live/broker_market_snapshot.json",self.schwab())
  self.write("robinhood/coinbase_market.json",{
   "quotes":{"BTC-USD":{"at":self.at,"bid":"1","ask":"1.01","mid":"1.005"}}})
  self.write("webull/stock_api_probe.json",{
   "checked_at":self.at,"state":"ALL_STOCK_ENDPOINTS_AUTHORIZED"})
  status=cached_market_status(self.root,now=self.now)
  self.assertEqual(status["schwab"]["symbols"],1)
  self.assertEqual(status["robinhood_crypto"]["symbols"],1)
  self.assertEqual(status["webull"]["state"],"BROKER_ENDPOINTS_AUTHORIZED_NO_QUOTE_CACHE")
 def test_empty_cache_must_report_zero_coverage(self):
  counts=cached_market_status(self.root,now=self.now)
  for broker in ("schwab","robinhood_crypto","webull"):
   self.assertEqual(counts[broker]["symbols"],0)

if __name__=="__main__":unittest.main()
