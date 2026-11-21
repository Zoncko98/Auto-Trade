"""V1 Schwab quote -> V2 normalized non-executable stock feed regression."""
from pathlib import Path
from tempfile import TemporaryDirectory
from datetime import datetime,timedelta,timezone
from unittest import TestCase,main
from unittest.mock import patch,Mock
import json,stat
import live_worker
from trader_v2.market_sources import schwab_market_quote,MarketSourceError
from trader_v2.cached_provider import CachedMarketDataProvider
from trader_v2.models import AssetClass

class StockBridgeTests(TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.state=Path(self.temp.name)
        self.live=self.state/"live"
        self.live.mkdir(mode=0o700)
        self.now=datetime.now(timezone.utc).replace(microsecond=0)
        self.calls=[]
    def quote(self,at):
        return {"AAPL":{"quote":{"quoteTime":int(at.timestamp()*1000),
            "bidPrice":150.00,"askPrice":150.02,"lastPrice":150.01,
            "mark":150.01,"totalVolume":3000},"isTradable":True}}
    def scanner(self,payload,*,fail_write=False,selected=None):
        def fetch(symbols):
            self.calls.append(tuple(symbols))
            return payload
        client=Mock()
        client.get_quotes.side_effect=fetch
        with (patch.object(live_worker,"STATE_DIR",self.live),
              patch.object(live_worker,"UNIVERSE",("AAPL",)),
              patch.object(live_worker,"result",side_effect=lambda result,name:result),
              patch.object(live_worker,"select_entry",return_value=(selected,[])),
              patch.object(live_worker,"comparisons",return_value=[]),
              patch("broker_market_data.write_snapshot",
                    side_effect=OSError("synthetic disk issue") if fail_write else
                    __import__("broker_market_data").write_snapshot)):
            result=live_worker.scan_entries(client,self.now)
        return result
    def test_same_v1_sdk_quote_published_as_inert_v2_stock_observation(self):
        result=self.scanner(self.quote(self.now))
        self.assertIsNone(result)
        self.assertEqual(self.calls,[("AAPL",)])
        path=self.live/"broker_market_snapshot.json"
        self.assertTrue(path.is_file())
        self.assertEqual(path.stat().st_mode&0o077,0)
        doc=json.loads(path.read_text())
        self.assertEqual(doc["source"],"schwab_broker_quotes")
        self.assertEqual(doc["schema"],1)
        source=schwab_market_quote(doc,"AAPL",now=self.now)
        self.assertFalse(source.broker_executable)
        self.assertFalse(source.to_inert_snapshot().market_open)
        read=CachedMarketDataProvider(self.state).quote("AAPL",AssetClass.STOCK,now=self.now)
        self.assertEqual(read.symbol,"AAPL")
        self.assertEqual(str(read.last),"150.01")
    def test_stale_exchange_quote_does_not_become_current_from_new_file_time(self):
        self.scanner(self.quote(self.now-timedelta(minutes=7)))
        doc=json.loads((self.live/"broker_market_snapshot.json").read_text())
        self.assertEqual(doc["observed_at"],self.now.isoformat())
        with self.assertRaises(MarketSourceError) as exc:
            schwab_market_quote(doc,"AAPL",now=self.now)
        self.assertEqual(str(exc.exception),"EXCHANGE_QUOTE_STALE_OR_FUTURE")
    def test_diagnostic_storage_failure_cannot_block_v1_stock_scanner(self):
        result=self.scanner(self.quote(self.now),fail_write=True)
        self.assertIsNone(result)
        self.assertEqual(self.calls,[("AAPL",)])
        self.assertFalse((self.live/"broker_market_snapshot.json").exists())
    def test_storage_failure_preserves_original_v1_candidate(self):
        from types import SimpleNamespace
        candidate=SimpleNamespace(symbol="AAPL")
        result=self.scanner(self.quote(self.now),fail_write=True,selected=candidate)
        self.assertIs(result,candidate)
        self.assertEqual(self.calls,[("AAPL",)])
        self.assertFalse((self.live/"broker_market_snapshot.json").exists())

    def test_empty_or_unverified_quote_does_not_replace_cached_data(self):
        self.scanner(self.quote(self.now))
        target=self.live/"broker_market_snapshot.json"
        before=target.read_bytes()
        self.scanner({"AAPL":{"quote":{"isTradable":True}}})
        self.assertEqual(target.read_bytes(),before)

if __name__=="__main__":main()
