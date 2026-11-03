import unittest
from datetime import datetime,timezone
import tempfile,json
from datetime import timedelta
from coinbase_market_feed import ticker,CoinbaseFeed,read_snapshot

class CoinbaseFeedTests(unittest.TestCase):
 def setUp(self):self.now=datetime(2026,11,3,0,tzinfo=timezone.utc)
 def msg(self,seconds=0):
  return {"type":"ticker","product_id":"BTC-USD","best_bid":"100","best_ask":"100.1",
    "price":"100.05","time":(self.now-timedelta(seconds=seconds)).isoformat()}
 def test_good_ticker(self):
  assert ticker(self.msg(),{"BTC-USD"},self.now)
 def test_stale_or_unsubscribed_rejected(self):
  assert ticker(self.msg(100),{"BTC-USD"},self.now) is None
  assert ticker(self.msg(),{"ETH-USD"},self.now) is None
