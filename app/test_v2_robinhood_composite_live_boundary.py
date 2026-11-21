from datetime import datetime,timezone,timedelta
from decimal import Decimal as D
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, main

from trader_v2.models import AssetClass,MarketSnapshot,Candidate,OrderSide,RiskPolicy
from trader_v2.robinhood_live_adapter import RobinhoodLiveAdapter
from trader_v2.robinhood_signed_receipts import BrokerEvidenceUnavailable
from trader_v2.live_pipeline import LivePipeline
from trader_v2.store import EventStore
from test_v2_robinhood_live_adapter import SignedFixture

class RobinhoodCompositeLiveBoundaryTests(TestCase):
    def setUp(self):
        self.now=datetime.now(timezone.utc).replace(microsecond=0)
        self.client=SignedFixture(self.now)
        self.client.quote_rows["BTC-USD"]={
            "results":[{"symbol":"BTC-USD","bid":"10","ask":"10.01"}]}
        self.policy={"enabled":True,"account":"account123","max_order_usd":"25"}
        self.public_calls=[]
    def fresh(self,symbol,*,age=0,last="10.005"):
        self.public_calls.append(symbol)
        at=datetime.now(timezone.utc)
        return MarketSnapshot("BTCUSD",AssetClass.CRYPTO,
            "coinbase_public_paper",at-timedelta(seconds=age),at,
            D("10.00"),D("10.01"),D(last),True)
    def adapter(self,feed=None):
        return RobinhoodLiveAdapter(self.client,"account123",self.policy,
            "BTC-USD",clock=lambda:self.now,
            public_trade_feed=feed if feed is not None else self.fresh)

    def test_native_three_field_bid_ask_and_public_last_are_not_relabelled(self):
        adapter=self.adapter()
        quote=adapter.quote()
        self.assertEqual(quote.source,"robinhood_dual_attested")
        self.assertEqual(quote.bid,D("10"))
        self.assertEqual(quote.ask,D("10.01"))
        self.assertEqual(quote.last,D("10.005"))
        self.assertTrue(self.public_calls)
        self.assertEqual(self.public_calls[-1],"BTCUSD")
        account=adapter.account("account123")
        self.assertEqual(account.market_exposure,D("10.01"))
        self.assertEqual(self.client.posts,[])

    def test_external_venue_time_or_price_missing_blocks(self):
        for feed in (lambda s:self.fresh(s,age=25),
                     lambda s:self.fresh(s,last="11")):
            with self.subTest(feed=feed):
                with self.assertRaises(BrokerEvidenceUnavailable):
                    self.adapter(feed).quote()
                self.assertEqual(self.client.posts,[])

    def test_non_coinbase_held_asset_never_drops_off_risk_book(self):
        self.client.holdings.append({
          "asset_code":"VIRTUAL","total_quantity":"0.123"})
        self.client.quote_rows["VIRTUAL-USD"]={
          "results":[{"symbol":"VIRTUAL-USD","bid":"1","ask":"1.01"}]}
        with self.assertRaises(BrokerEvidenceUnavailable):
            self.adapter().account("account123")
        self.assertEqual(self.client.posts,[])

    def test_no_handoff_means_no_live_order_even_with_dual_source(self):
        adapter=self.adapter()
        quote=adapter.quote()
        with TemporaryDirectory() as tmp:
            pipe=LivePipeline(adapter,EventStore(Path(tmp)/"v2.sqlite3"),
                              lambda:None,ownership_root=Path(tmp))
            candidate=Candidate("crypto_sma","migrate","account123",
                  "BTC-USD",AssetClass.CRYPTO,OrderSide.BUY,self.now,
                  {"indicator":"test"})
            outcome=pipe.evaluate(candidate,quote,RiskPolicy(),now=self.now)
        self.assertEqual(outcome.code,"BLOCKED")
        self.assertEqual(outcome.reason,
                        "V1_TO_V2_SINGLE_WRITER_HANDOFF_UNVERIFIED")
        self.assertEqual(self.client.posts,[])

if __name__=="__main__":main()
