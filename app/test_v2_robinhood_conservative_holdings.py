"""Crossed signed Robinhood book can conservatively mark external exposure.

Never use that crossed source to approve an actual buy/sell limit price.
"""
from datetime import datetime,timezone,timedelta
from decimal import Decimal as D
from unittest import TestCase
from trader_v2.models import MarketSnapshot,AssetClass
from trader_v2.robinhood_live_adapter import RobinhoodLiveAdapter
from trader_v2.robinhood_signed_receipts import BrokerEvidenceUnavailable

def public(*,price="100",age=1):
 now=datetime.now(timezone.utc)
 return MarketSnapshot("BTCUSD",AssetClass.CRYPTO,"coinbase_public_paper",
     now-timedelta(seconds=age),now,
     D(price)-D("0.1"),D(price)+D("0.1"),D(price),True)

class SignedBroker:
 def __init__(self,bid="100.01",ask="100",timestamp=None):
  self.bid=bid;self.ask=ask;self.timestamp=timestamp
 def quote(self,symbol):
  data={"symbol":symbol,"bid":self.bid,"ask":self.ask}
  if self.timestamp is not None:data["timestamp"]=self.timestamp
  return {"results":[data]}
 def list_accounts(self):
  return [{"account_number":"acct","status":"active",
           "is_api_tradable":True,"buying_power_currency":"USD",
           "buying_power":"200"}]
 def positions(self,account):
  return [{"asset_code":"BTC","total_quantity":"0.5"}]
 def trading_pairs(self):
  return [{"symbol":"BTC-USD","is_api_tradable":True,"asset_increment":"0.001",
    "min_order_amount":"1","max_order_size":"10"}]

class ConservativeHoldingsQuoteTests(TestCase):
 def adapter(self,client=None,feed=None):
  return RobinhoodLiveAdapter(client or SignedBroker(),"acct",
      {"enabled":True,"account":"acct","max_order_usd":"10"},
      "BTC-USD",public_trade_feed=feed or (lambda _:public()))
 def test_small_crossed_broker_book_uses_higher_signed_price_only_as_exposure(self):
  reading=self.adapter()
  self.assertEqual(reading._signed_holding_ask("BTC-USD"),D("100.01"))
  account=reading.account("acct")
  self.assertEqual(account.account_id,"acct")
  self.assertEqual(account.positions,{})
  self.assertGreater(account.equity,account.cash)
 def test_crossed_exposure_mark_does_not_become_a_tradable_quote(self):
  with self.assertRaises(BrokerEvidenceUnavailable):
   self.adapter().quote()
 def test_large_crossed_book_is_unusable_even_for_exposure(self):
  with self.assertRaises(BrokerEvidenceUnavailable) as exc:
   self.adapter(SignedBroker("105","100"))._signed_holding_ask("BTC-USD")
  self.assertEqual(exc.exception.code,"SIGNED_HOLDING_MARK_SPREAD_UNVERIFIED")
 def test_far_away_public_trade_cannot_justify_broker_holdings_mark(self):
  with self.assertRaises(BrokerEvidenceUnavailable) as exc:
   self.adapter(feed=lambda _:public(price="150"))._signed_holding_ask("BTC-USD")
  self.assertEqual(exc.exception.code,"SIGNED_HOLDING_BROKER_PUBLIC_PRICE_DIFFERENCE")
 def test_old_public_trade_cannot_justify_broker_holdings_mark(self):
  with self.assertRaises(BrokerEvidenceUnavailable) as exc:
   self.adapter(feed=lambda _:public(age=40))._signed_holding_ask("BTC-USD")
  self.assertEqual(exc.exception.code,"SIGNED_HOLDING_EXTERNAL_LAST_STALE")
 def test_stale_provider_timestamp_is_not_ignored(self):
  stamp=(datetime.now(timezone.utc)-timedelta(minutes=5)).isoformat()
  with self.assertRaises(BrokerEvidenceUnavailable) as exc:
   self.adapter(SignedBroker(timestamp=stamp))._signed_holding_ask("BTC-USD")
  self.assertEqual(exc.exception.code,"SIGNED_HOLDING_BROKER_PRICE_UNVERIFIED")
 def test_missing_independent_feed_denies_marking(self):
  reading=self.adapter()
  reading.public_trade_feed=None
  with self.assertRaises(BrokerEvidenceUnavailable):
   reading._signed_holding_ask("BTC-USD")
 def test_unallowlisted_external_asset_still_blocks_exposure_mark(self):
  with self.assertRaises(BrokerEvidenceUnavailable):
   self.adapter()._signed_holding_ask("DOGE-USD")
