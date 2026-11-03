import unittest
from datetime import datetime,timezone
import tempfile,json
from pathlib import Path
from datetime import timedelta
from coinbase_market_feed import ticker,CoinbaseFeed,read_snapshot,online_products

class CoinbaseFeedTests(unittest.TestCase):
 def setUp(self):self.now=datetime(2026,11,3,0,tzinfo=timezone.utc)
 def msg(self,seconds=0):
  return {"type":"ticker","product_id":"BTC-USD","best_bid":"100","best_ask":"100.1",
    "price":"100.05","time":(self.now-timedelta(seconds=seconds)).isoformat()}
 def test_online_products_filters_status_catalogue(self):
  msg={"type":"status","products":[
    {"id":"BTC-USD","status":"online"},
    {"id":"PENGU-USD","status":"offline"},
    {"id":"BAD/PAIR","status":"online"}]}
  self.assertEqual(online_products(msg),{"BTC-USD"})
 def test_snapshot_distinguishes_live_socket_from_recent_cache(self):
  with tempfile.TemporaryDirectory() as root:
   p=Path(root)/"robinhood";p.mkdir()
   base={"updated_at":self.now.isoformat(),"subscribed":1,
    "quotes":{"BTC-USD":{"symbol":"BTC-USD","at":self.now.isoformat(),
      "mid":"100.05","bid":"100","ask":"100.1"}},
    "history":{"BTC-USD":[{"symbol":"BTC-USD","at":self.now.isoformat(),"mid":"100.05"}]}}
   (p/"coinbase_market.json").write_text(json.dumps(dict(base,connected=True)))
   self.assertEqual(read_snapshot(root,self.now)["state"],"LIVE")
   (p/"coinbase_market.json").write_text(json.dumps(dict(base,connected=False)))
   cached=read_snapshot(root,self.now)
   self.assertEqual(cached["state"],"RECENT_CACHE")
   self.assertFalse(cached["connected"])
 def test_good_ticker(self):
  assert ticker(self.msg(),{"BTC-USD"},self.now)
 def test_stale_or_unsubscribed_rejected(self):
  assert ticker(self.msg(100),{"BTC-USD"},self.now) is None
  assert ticker(self.msg(),{"ETH-USD"},self.now) is None
