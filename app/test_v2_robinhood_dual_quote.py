"""Robinhood signed top-of-book + independently timestamped last (no network)."""
from datetime import datetime, timezone, timedelta
from decimal import Decimal as D
from unittest import TestCase, main

from trader_v2.models import AssetClass, MarketSnapshot
from trader_v2.robinhood_dual_quote import attest_quote, DualQuoteUnavailable

NOW=datetime(2026,11,21,19,57,0,tzinfo=timezone.utc)

def signed(**kw):
    body={"symbol":"BTC-USD","bid":"989.5","ask":"990.5"}
    body.update(kw)
    return {"results":[body]}

def coinbase(*, age=2, symbol="BTCUSD", price="990", source="coinbase_public_paper"):
    return MarketSnapshot(symbol,AssetClass.CRYPTO,source,
        NOW-timedelta(seconds=age),NOW+timedelta(seconds=max(0,-age)),D("989.7"),D("990.3"),
        D(price),True)

def check(payload=None, public=None, *, started=0, finished=0, now=NOW):
    return attest_quote(
        payload if payload is not None else signed(),
        public if public is not None else coinbase(),
        "BTC-USD",
        request_started_at=NOW+timedelta(seconds=started),
        request_completed_at=NOW+timedelta(seconds=finished),
        examined_at=now)

class RobinhoodDualQuoteTests(TestCase):
    def test_actual_v2_three_field_schema_is_accepted_without_fake_last_or_time(self):
        item=check()
        self.assertEqual(item.signed_bid,D("989.5"))
        self.assertEqual(item.signed_ask,D("990.5"))
        self.assertEqual(item.external_last,D("990"))
        self.assertFalse(item.public["broker_venue_timestamp_provided"])
        self.assertFalse(item.public["broker_executable_quote_certified"])
        self.assertFalse(item.public["v2_order_authorized"])
        self.assertTrue(item.public["independent_trade_timestamp_verified"])

    def test_signed_identity_must_be_exactly_one(self):
        for bad in ({"results":[]}, {"results":[signed()["results"][0]]*2},
                    {"results":[{"symbol":"ETH-USD","bid":"10","ask":"11"}]},
                    {"results":"not-a-list"}, None):
            with self.subTest(bad=bad),self.assertRaises(DualQuoteUnavailable):
                check(payload=bad if bad is not None else [])

    def test_signed_prices_never_invented_from_public_mid(self):
        for field in ("bid","ask"):
            body=signed()["results"][0]
            body.pop(field)
            with self.assertRaises(DualQuoteUnavailable):
                check({"results":[body]})
        for row in (signed(bid="-1"),signed(ask="NaN"),signed(bid="999"),
                    signed(bid="900"),signed(bid=990.0)):
            with self.subTest(row=row),self.assertRaises(DualQuoteUnavailable):
                check(row)

    def test_public_venue_identity_and_fresh_timestamp(self):
        for doc in (coinbase(age=21),coinbase(age=-3),
                    coinbase(source="any_exchange"),coinbase(symbol="ETHUSD")):
            with self.subTest(doc=doc.source),self.assertRaises(DualQuoteUnavailable):
                check(public=doc)

    def test_public_trade_cross_price_disagreement_blocks(self):
        for n in ("970","1011"):
            with self.subTest(last=n),self.assertRaises(DualQuoteUnavailable):
                check(public=coinbase(price=n))

    def test_broker_get_must_complete_in_bounded_time(self):
        for start,end,now in ((0,4,NOW+timedelta(seconds=4)),
                              (1,0,NOW),
                              (0,1,NOW+timedelta(seconds=7))):
            with self.subTest(start=start,end=end),self.assertRaises(DualQuoteUnavailable):
                check(started=start,finished=end,now=now)

    def test_signed_timestamp_present_and_recent_is_checked_not_ignored(self):
        recent=NOW.isoformat()
        result=check(signed(timestamp=recent))
        self.assertEqual(result.signed_bid,D("989.5"))
        with self.assertRaises(DualQuoteUnavailable) as found:
            check(signed(timestamp=(NOW-timedelta(seconds=35)).isoformat()))
        self.assertEqual(found.exception.code,
                         "SIGNED_BROKER_TIMESTAMP_INVALID_OR_STALE")
        with self.assertRaises(DualQuoteUnavailable):
            check(signed(timestamp="not-a-timestamp"))

    def test_nonallowlisted_coin_does_not_inherit_trust(self):
        with self.assertRaises(DualQuoteUnavailable):
            attest_quote({"results":[{"symbol":"VIRTUAL-USD","bid":"1","ask":"1.01"}]},
                coinbase(), "VIRTUAL-USD",
                request_started_at=NOW,request_completed_at=NOW,examined_at=NOW)

if __name__=="__main__":
    main()
