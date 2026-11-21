"""No-network V2 fresh Coinbase paper worker tests and time-based integration."""
from datetime import datetime,timedelta,timezone
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import sqlite3
import unittest
from unittest.mock import patch

from trader_v2.models import AssetClass,MarketSnapshot
from trader_v2.public_crypto import PRODUCTS,normalize_ticker,fetch_ticker,PublicFeedError
from trader_v2.fresh_paper import run_once,status,_record_and_closed_bars

class FakeResponse:
    status=200
    def __init__(self,data):
        self.raw=json.dumps(data).encode("utf-8")
    def __enter__(self):return self
    def __exit__(self,*args):return False
    def read(self,n):return self.raw[:n]

class FreshPaperTests(unittest.TestCase):
    def setUp(self):
        self.folder=TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root=Path(self.folder.name)
        self.start=datetime(2026,11,20,12,0,tzinfo=timezone.utc)
        self.prices=[10,10,10,10,10,10,10,10,10,11,12,13,
                     12,11,10,9,8,9,10,11,12,13,12,11]

    def quote(self,symbol,price,now):
        val=Decimal(str(price))
        return MarketSnapshot(symbol,AssetClass.CRYPTO,
            "coinbase_public_paper",now-timedelta(seconds=2),now,
            val*Decimal("0.9995"),val*Decimal("1.0005"),val,True)
    def run_tape(self,shadow=None):
        reports=[]
        ai=shadow or (lambda candidate,quote,now:
            {"state":"NOT_CONFIGURED","changed_order_authority":False})
        for i,price in enumerate(self.prices):
            now=self.start+timedelta(minutes=i,seconds=10)
            record=run_once(self.root,"BTCUSD",now=now,
                fetch=lambda symbol,now,price=price:self.quote(symbol,price,now),
                shadow=ai)
            reports.append(record)
        return reports

    def test_real_ticker_normalization_rejects_stale_future_crossed_and_invalid(self):
        now=self.start+timedelta(seconds=15)
        row={"time":(now-timedelta(seconds=1)).isoformat().replace("+00:00","Z"),
             "bid":"99","ask":"100","price":"99.5"}
        quote=normalize_ticker(row,"BTCUSD",now=now)
        self.assertTrue(quote.market_open)
        self.assertEqual(quote.source,"coinbase_public_paper")
        self.assertEqual(quote.bid,Decimal("99"))
        with self.assertRaises(PublicFeedError):
            normalize_ticker({**row,"bid":"101"}, "BTCUSD",now=now)
        with self.assertRaises(PublicFeedError):
            normalize_ticker({**row,"time":(now-timedelta(minutes=3)).isoformat().replace("+00:00","Z")}, "BTCUSD",now=now)
        with self.assertRaises(PublicFeedError):
            normalize_ticker({**row,"price":"NaN"}, "BTCUSD",now=now)
        with self.assertRaises(PublicFeedError):
            normalize_ticker(row,"MYSTERY",now=now)

    def test_http_client_uses_allowlisted_https_and_bounded_timeout(self):
        now=self.start+timedelta(seconds=10)
        row={"time":now.isoformat().replace("+00:00","Z"),
             "bid":"100","ask":"101","price":"100.5"}
        calls=[]
        def opener(request,timeout):
            calls.append((request.full_url,request.get_method(),timeout))
            return FakeResponse(row)
        quote=fetch_ticker("ETHUSD",now=now,opener=opener)
        self.assertEqual(quote.symbol,"ETHUSD")
        self.assertEqual(calls,[
            ("https://api.exchange.coinbase.com/products/ETH-USD/ticker","GET",8)])
        with self.assertRaises(PublicFeedError):
            fetch_ticker("NOT_ALLOWED",now=now,opener=opener)
        self.assertEqual(len(calls),1)

    def test_warm_up_then_real_paper_signal_and_durable_broker_fills(self):
        reports=self.run_tape()
        self.assertEqual(reports[0]["scan_state"],"WARMING_UP")
        self.assertEqual(reports[0]["closed_bars"],0)
        self.assertGreater(reports[-1]["closed_bars"],8)
        filled=[r for r in reports if r["scan_state"]=="FILLED"]
        self.assertGreater(len(filled),0)
        self.assertEqual(reports[-1]["ai_mode"],"OFF_BASELINE")
        self.assertEqual(reports[-1]["live_orders_submitted"],0)
        self.assertEqual(reports[-1]["source"],"COINBASE_PUBLIC_TICKER_ONLY")
        self.assertGreaterEqual(reports[-1]["journal"]["intents"],1)
        paper_dir=self.root/"v2"/"fresh_paper"
        for name in ("tick_bars.sqlite3","sim.sqlite3","intents.sqlite3","btcusd.json"):
            self.assertTrue((paper_dir/name).exists())
            self.assertEqual((paper_dir/name).stat().st_mode&0o077,0)
        self.assertFalse((self.root/"schwab_token.json").exists())
        self.assertFalse((self.root/"robinhood").exists())
        self.assertEqual(status(self.root)["live_orders_authorized"],False)

    def test_ai_shadow_veto_does_not_change_baseline_order_authority(self):
        seen=[]
        def veto(candidate,quote,now):
            seen.append((candidate.symbol,candidate.side.value))
            return {"state":"VETO","model":"fixture","reason":"diagnostic only",
                    "changed_order_authority":False}
        reports=self.run_tape(shadow=veto)
        self.assertGreater(len(seen),0)
        self.assertGreater(len([r for r in reports if r["scan_state"]=="FILLED"]),0)
        reviewed=[r["ai_shadow"] for r in reports if r.get("signal")]
        self.assertTrue(all(x["state"]=="VETO" and
                            not x["changed_order_authority"] for x in reviewed))
        self.assertTrue(all(r["live_orders_submitted"]==0 for r in reports))

    def test_repeated_same_scan_no_duplicate_fill_or_entry(self):
        reports=self.run_tape()
        latest=reports[-1]
        now=self.start+timedelta(minutes=len(self.prices)-1,seconds=10)
        before=latest["journal"]
        again=run_once(self.root,"BTCUSD",now=now,
            fetch=lambda sym,now:self.quote(sym,self.prices[-1],now))
        self.assertEqual(again["journal"]["intents"],before["intents"])
        self.assertEqual(again["journal"]["events"],before["events"])
        self.assertEqual(again["virtual_cash"],latest["virtual_cash"])

    def test_stale_public_quote_cannot_fill_or_create_candles(self):
        now=self.start
        with self.assertRaises(ValueError):
            run_once(self.root,"FORBIDDEN",now=now)
        report=run_once(self.root,"BTCUSD",now=now,
            fetch=lambda sym,now:self.quote(sym,10,now-timedelta(minutes=5)))
        self.assertEqual(report["scan_state"],"DATA_UNAVAILABLE")
        self.assertEqual(report["journal"] if "journal" in report else None,None)
        self.assertFalse((self.root/"v2"/"fresh_paper"/"intents.sqlite3").exists())

    def test_network_fetch_clock_is_measured_after_response(self):
        received=[]
        def delayed_fetch(symbol,now):
            received.append(now)
            current=datetime.now(timezone.utc)
            return self.quote(symbol,10,current)
        report=run_once(self.root,"BTCUSD",fetch=delayed_fetch)
        self.assertEqual(received,[None])
        self.assertEqual(report["scan_state"],"WARMING_UP")

    def test_worker_status_is_readonly_before_first_scan(self):
        self.assertEqual(status(self.root)["reports"][0]["scan_state"],"NOT_SCANNED")
        self.assertFalse((self.root/"v2").exists())

    def test_separate_crypto_accounts_and_no_cross_broker_activity(self):
        btc_now=self.start+timedelta(seconds=10)
        run_once(self.root,"BTCUSD",now=btc_now,
                 fetch=lambda sym,now:self.quote(sym,10,now))
        run_once(self.root,"ETHUSD",now=btc_now,
                 fetch=lambda sym,now:self.quote(sym,100,now))
        with sqlite3.connect(self.root/"v2"/"fresh_paper"/"sim.sqlite3") as db:
            accounts=[x[0] for x in db.execute("SELECT account_id FROM sim_accounts").fetchall()]
        self.assertCountEqual(accounts,["v2-paper-btcusd","v2-paper-ethusd"])
        self.assertEqual(len(status(self.root)["reports"]),2)

if __name__=="__main__":unittest.main()
