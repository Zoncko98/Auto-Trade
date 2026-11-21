from datetime import datetime,timezone,timedelta
from decimal import Decimal as D
from tempfile import TemporaryDirectory
from pathlib import Path
from unittest import TestCase, main
from trader_v2.models import AssetClass, MarketSnapshot
from trader_v2.migration_probe import _probe
from test_v2_migration_probe import FakeSignedClient

class SignedRobinhoodDualPreflightTests(TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.now=datetime.now(timezone.utc).replace(microsecond=0)
        self.broker=FakeSignedClient(self.now)
        self.broker.quotes["BTC-USD"]={"results":[{
          "symbol":"BTC-USD","bid":"99.9","ask":"100.1"}]}
        self.policy={"enabled":True,"account":"acc1"}
    def feed(self, symbol, age=0, last="100"):
        self.assertEqual(symbol,"BTCUSD")
        moment=datetime.now(timezone.utc)
        return MarketSnapshot("BTCUSD",AssetClass.CRYPTO,"coinbase_public_paper",
            moment-timedelta(seconds=age),moment,
            D("99.9"),D("100.1"),D(last),True)

    def test_real_robinhood_v2_schema_crosschecks_without_fake_venue_timestamp(self):
        result=_probe(self.root,self.broker,self.policy,now=self.now,
                      public_feed=lambda symbol:self.feed(symbol))
        self.assertTrue(result["account_verified"])
        self.assertTrue(result["local_journal_matched"])
        self.assertTrue(result["broker_history_verified"])
        self.assertEqual(result["quote_timestamp_verified_symbols"],0)
        self.assertEqual(result["independent_trade_crosscheck_symbols"],1)
        self.assertFalse(result["independent_broker_venue_timestamp_verified"])
        self.assertEqual(result["first_blocker"],
                         "V1_WRITER_HANDOFF_AND_BROKER_SESSION_REQUIRED")
        self.assertFalse(result["v2_live_order_authority"])
        self.assertFalse(result["cutover_ready"])
        self.assertFalse(result["settled_cash_verified"])
        self.assertFalse(result["broker_session_verified"])

    def test_stale_or_divergent_external_last_never_passes(self):
        for age,last in ((21,"100"),(0,"104"),(0,"1")):
            with self.subTest(age=age,last=last):
                result=_probe(self.root,self.broker,self.policy,now=self.now,
                         public_feed=lambda symbol:self.feed(symbol,age=age,last=last))
                self.assertEqual(result["independent_trade_crosscheck_symbols"],0)
                self.assertEqual(result["first_blocker"],
                                 "BROKER_QUOTE_TIMESTAMP_OR_LAST_TRADE_UNVERIFIED")

    def test_live_public_get_completes_before_signed_broker_quote(self):
        order=[]
        original=self.broker.quote
        def spy_quote(symbol):
            order.append("signed")
            return original(symbol)
        self.broker.quote=spy_quote
        def public(symbol):
            order.append("public")
            return self.feed(symbol)
        result=_probe(self.root,self.broker,self.policy,now=self.now,
                      public_feed=public)
        self.assertEqual(order[:2],["public","signed"])
        self.assertEqual(result["independent_trade_crosscheck_symbols"],1)
        self.assertEqual(result["quote_validation_failures"],{})
        self.assertFalse(result["v2_live_order_authority"])

    def test_signed_timestamp_stale_cannot_be_overridden_by_fresh_coinbase(self):
        self.broker.quotes["BTC-USD"]["results"][0]["timestamp"]=(
            datetime.now(timezone.utc)-timedelta(minutes=4)).isoformat()
        result=_probe(self.root,self.broker,self.policy,now=self.now,
                      public_feed=lambda symbol:self.feed(symbol))
        self.assertEqual(result["independent_trade_crosscheck_symbols"],0)
        self.assertEqual(result["quote_validation_failures"]["BTC-USD"],
                         "SIGNED_BROKER_TIMESTAMP_INVALID_OR_STALE")
        self.assertFalse(result["cutover_ready"])

    def test_public_data_failure_is_explicit_and_never_grants_authority(self):
        def missing(symbol):
            raise TimeoutError("do not log token or private data")
        result=_probe(self.root,self.broker,self.policy,now=self.now,
                      public_feed=missing)
        self.assertEqual(result["quote_validation_failures"]["BTC-USD"],
                         "PUBLIC_TRADE_GET_UNAVAILABLE")
        self.assertNotIn("do not log token",str(result))
        self.assertFalse(result["cutover_ready"])

    def test_missing_external_trade_never_authorizes_v2(self):
        result=_probe(self.root,self.broker,self.policy,now=self.now)
        self.assertEqual(result["independent_trade_crosscheck_symbols"],0)
        self.assertFalse(result["cutover_ready"])

if __name__=="__main__":main()
