"""Official-source closed bars for V2 stock/crypto, no market synthesis."""
from datetime import datetime,timezone,timedelta
from tempfile import TemporaryDirectory
from pathlib import Path
from decimal import Decimal as D
from unittest import TestCase,main
from unittest.mock import patch
import sqlite3
from trader_v2.signed_live_candles import (
 _stock_rows,coinbase_recorded_candles,schwab_signed_candles,
 webull_signed_candles,SignedCandleUnavailable)
NOW=datetime(2026,11,23,17,35,0,tzinfo=timezone.utc)

def stock_rows(source):
 end=NOW-timedelta(minutes=15)
 # Whole UTC five-minute boundaries, completed >= 60 seconds ago.
 start=end-timedelta(minutes=25)
 rows=[]
 for i in range(6):
  at=start+timedelta(minutes=i*5)
  if source=="schwab":
   rows.append({"datetime":int(at.timestamp()*1000),"close":"10"})
  else:
   rows.append({"time":at.isoformat(),"close":"10"})
 return rows

class SignedLiveCandleTests(TestCase):
 def test_schwab_official_completed_5_minute_bars(self):
  rows=stock_rows("schwab")
  candles=_stock_rows(rows,"F",NOW,source="schwab")
  self.assertEqual(len(candles),6)
  self.assertTrue(all(c.closed for c in candles))
  self.assertEqual(candles[0].close,D("10"))
  with patch("live_worker.recent_candles",return_value=rows):
   self.assertEqual(len(schwab_signed_candles(object(),"F",now=NOW)),6)
 def test_webull_signed_5m_bars(self):
  rows=stock_rows("webull")
  class Broker:
   def bars(self,symbol,asset,period=None):
    assert (symbol,asset,period)==("F","EQUITY","M5")
    return rows
  self.assertEqual(len(webull_signed_candles(Broker(),"F",now=NOW)),6)
 def test_future_or_duplicate_stock_history_never_becomes_trade_signal(self):
  rows=stock_rows("schwab")
  rows[4]=dict(rows[3])
  with self.assertRaises(SignedCandleUnavailable):
   _stock_rows(rows,"F",NOW,source="schwab")
  rows=stock_rows("schwab")
  rows[-1]["datetime"]=int((NOW+timedelta(minutes=15)).timestamp()*1000)
  with self.assertRaises(SignedCandleUnavailable):
   _stock_rows(rows,"F",NOW,source="schwab")
 def test_current_open_bar_excluded_from_stock_m5(self):
  rows=stock_rows("schwab")
  rows.append({"datetime":int((NOW-timedelta(minutes=1)).timestamp()*1000),
               "close":"11"})
  # Time not on 5m boundary -> rejected; provider must use bucket alignment.
  with self.assertRaises(SignedCandleUnavailable):
   _stock_rows(rows,"F",NOW,source="schwab")
 def test_coinbase_persistent_source_closed_ticks_no_forwardfill(self):
  with TemporaryDirectory() as tmp:
   target=Path(tmp)/"v2/fresh_paper"
   target.mkdir(mode=0o700,parents=True)
   path=target/"tick_bars.sqlite3"
   with sqlite3.connect(path) as db:
    db.execute("CREATE TABLE tick_bars(symbol TEXT,minute_start INTEGER,quote_at TEXT,close TEXT)")
    end=NOW-timedelta(minutes=11)
    for i in range(10):
     at=end+timedelta(minutes=i)
     db.execute("INSERT INTO tick_bars VALUES(?,?,?,?)",
       ("BTCUSD",int(at.timestamp()),at.isoformat(),str(10+i)))
   path.chmod(0o600)
   candles=coinbase_recorded_candles(tmp,"BTC-USD",now=NOW)
   self.assertEqual(len(candles),10)
   self.assertTrue(all(c.symbol=="BTC-USD" for c in candles))
   self.assertEqual(candles[-1].close,D("19"))
   self.assertFalse((target/"fake.csv").exists())
 def test_missing_or_public_crypto_not_allowlisted_refused(self):
  with TemporaryDirectory() as tmp:
   for symbol in ("BTC-USD","VIRTUAL-USD"):
    with self.assertRaises(SignedCandleUnavailable):
     coinbase_recorded_candles(tmp,symbol,now=NOW)

if __name__=="__main__":main()
