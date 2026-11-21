"""Offline signed Robinhood V2 adapter tests. Network and live POST are mocked."""
from datetime import datetime,timezone,timedelta
from decimal import Decimal as D
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase,main
from trader_v2.models import AssetClass,OrderIntent,OrderSide,Candidate,RiskPolicy
from trader_v2.risk import evaluate_risk
from trader_v2.robinhood_live_adapter import RobinhoodLiveAdapter
from trader_v2.robinhood_signed_receipts import (
    BrokerEvidenceUnavailable,client_id,
)

class SignedFixture:
    def __init__(self,now):
        self.now=now;self.posts=[];self.orders_list=[]
        self.accounts=[{"account_number":"account123","status":"active",
            "is_api_tradable":True,"buying_power_currency":"USD",
            "buying_power":"100"}]
        self.holdings=[{"asset_code":"BTC","total_quantity":"1"}]
        self.pairs=[{"symbol":"BTC-USD","is_api_tradable":True,
            "asset_increment":"0.003","min_order_amount":"1",
            "max_order_size":"100"}]
        self.quote_rows={"BTC-USD":{
            "results":[{"symbol":"BTC-USD","quote_timestamp":now.isoformat(),
            "bid":"10.00","ask":"10.01","last":"10.005"}]}}
    def list_accounts(self):return self.accounts
    def trading_pairs(self):return self.pairs
    def positions(self,account):
        assert account=="account123"
        return self.holdings
    def quote(self,symbol):return self.quote_rows[symbol]
    def orders(self,account):
        assert account=="account123"
        return self.orders_list
    def submit_order(self,account,intent):
        self.posts.append((account,intent))
        return {"id":"signed-broker-order-1"}

class RobinhoodV2AdapterTest(TestCase):
    def setUp(self):
        self.now=datetime.now(timezone.utc).replace(microsecond=0)
        self.client=SignedFixture(self.now)
        self.policy={"enabled":True,"account":"account123","max_order_usd":"25"}
        self.adapter=RobinhoodLiveAdapter(
            self.client,"account123",self.policy,"BTC-USD",clock=lambda:self.now)
    def intent(self,qty="0.300",price="10.02"):
        return OrderIntent("v2_trade_1","account123","crypto_sma",
            "BTC-USD",AssetClass.CRYPTO,OrderSide.BUY,D(qty),D(price),self.now)

    def test_signed_account_holding_and_spendable_usd(self):
        account=self.adapter.account("account123")
        self.assertEqual(account.cash,D("100"))
        self.assertEqual(account.positions,{})  # External holdings aren't bot-owned
        self.assertEqual(account.equity,D("110.01"))
        self.assertEqual(account.capability.quantity_increment,D("0.003"))
        self.assertEqual(account.capability.min_notional,D("1"))

    def test_fresh_signed_executable_snapshot(self):
        quote=self.adapter.quote(now=self.now)
        self.assertTrue(quote.market_open)
        self.assertEqual(quote.source,"robinhood_signed")
        self.assertEqual(quote.bid,D("10"))
        self.assertEqual(quote.ask,D("10.01"))

    def test_high_precision_external_holdings_count_toward_exposure(self):
        self.client.holdings=[{"asset_code":"BTC",
            "total_quantity":"1.123456789012345678"}]
        account=self.adapter.account("account123")
        self.assertEqual(account.positions,{}) # Still NOT bot-owned inventory
        self.assertGreaterEqual(account.market_exposure,D("11.24"))
        self.assertGreaterEqual(account.market_exposure,
                                D("1.123456789012345678")*D("10"))
        self.assertLessEqual(account.equity,D("111.245"))

    def test_signed_18_place_pair_increment_clamped_conservatively(self):
        self.client.pairs[0]["asset_increment"]="0.000000000000000001"
        rules=self.adapter._pair()
        self.assertEqual(rules["asset_increment"],D("0.000000000001"))
        account=self.adapter.account("account123")
        self.assertEqual(account.capability.quantity_increment,D("0.000000000001"))

    def test_missing_quote_timestamp_never_grants_execution(self):
        self.client.quote_rows["BTC-USD"]["results"][0].pop("quote_timestamp")
        with self.assertRaises(BrokerEvidenceUnavailable):
            self.adapter.quote()
        self.assertEqual(self.client.posts,[])

    def test_missing_last_trade_never_fills_in_midpoint(self):
        self.client.quote_rows["BTC-USD"]["results"][0].pop("last")
        with self.assertRaises(BrokerEvidenceUnavailable):
            self.adapter.quote()
        self.assertEqual(self.client.posts,[])

    def test_crossed_market_and_stale_broker_quotes_block(self):
        row=self.client.quote_rows["BTC-USD"]["results"][0]
        row["bid"]="11";row["ask"]="10"
        with self.assertRaises(BrokerEvidenceUnavailable):
            self.adapter.quote()
        row["bid"]="10";row["ask"]="10.01"
        row["quote_timestamp"]=(self.now-timedelta(minutes=5)).isoformat()
        with self.assertRaises(BrokerEvidenceUnavailable):
            self.adapter.quote()

    def test_policy_disabled_cross_account_wrong_pair_block(self):
        with self.assertRaises(ValueError):
            RobinhoodLiveAdapter(self.client,"account123",
                {"enabled":False,"account":"account123"},"BTC-USD")
        with self.assertRaises(ValueError):
            RobinhoodLiveAdapter(self.client,"account123",
                {"enabled":True,"account":"different"},"BTC-USD")
        with self.assertRaises(BrokerEvidenceUnavailable):
            self.adapter.account("unselected")

    def test_duplicate_holdings_must_not_be_counted_as_zero(self):
        self.client.holdings.append({"asset_code":"BTC","total_quantity":"0.1"})
        with self.assertRaises(BrokerEvidenceUnavailable):
            self.adapter.account("account123")

    def test_broker_increment_preflight_happens_before_any_post(self):
        with self.assertRaises(BrokerEvidenceUnavailable):
            self.adapter.submit(self.intent(qty="0.302"))
        self.assertEqual(self.client.posts,[])

    def test_excess_order_amount_blocks(self):
        with self.assertRaises(BrokerEvidenceUnavailable):
            self.adapter.submit(self.intent(qty="3"))
        self.assertEqual(self.client.posts,[])

    def test_buy_quote_drift_blocks_without_a_post(self):
        with self.assertRaises(BrokerEvidenceUnavailable):
            self.adapter.submit(self.intent(price="12"))
        self.assertEqual(self.client.posts,[])

    def test_signed_limit_order_preserves_stable_uuid(self):
        result=self.adapter.submit(self.intent())
        self.assertEqual(result.state,"BROKER_ACCEPTED")
        self.assertEqual(result.broker_order_id,"signed-broker-order-1")
        self.assertEqual(len(self.client.posts),1)
        account,payload=self.client.posts[0]
        self.assertEqual(account,"account123")
        self.assertEqual(payload["client_order_id"],client_id("v2_trade_1","account123"))
        self.assertEqual(payload["limit_price"],"10.02")
        self.assertTrue(payload["operator_approved"])
        self.assertTrue(payload["risk_approved"])

    def test_missing_broker_ack_keeps_order_unverified(self):
        self.client.submit_order=lambda *args,**kw:{"status":"accepted"}
        with self.assertRaises(BrokerEvidenceUnavailable):
            self.adapter.submit(self.intent())
    def test_only_verified_bot_inventory_is_available_to_sell(self):
        adapter=RobinhoodLiveAdapter(self.client,"account123",self.policy,
            "BTC-USD",clock=lambda:self.now,
            verified_managed_positions={"BTC-USD":D("0.5")})
        account=adapter.account("account123")
        self.assertEqual(account.positions["BTC-USD"],D("0.5"))
        self.assertEqual(account.market_exposure,D("10.01"))
        adapter=RobinhoodLiveAdapter(self.client,"account123",self.policy,
            "BTC-USD",clock=lambda:self.now,
            verified_managed_positions={"BTC-USD":D("1.5")})
        with self.assertRaises(BrokerEvidenceUnavailable):
            adapter.account("account123")

    def test_signed_exact_order_lookup(self):
        key="v2_trade_1"
        self.client.orders_list=[{
            "client_order_id":client_id(key,"account123"),
            "account_number":"account123","id":"signed-id",
            "state":"filled","filled_asset_quantity":"0.3",
            "average_price":"10.01","fee_charged":"0.03"}]
        outcome=self.adapter.find_order(key)
        self.assertEqual(outcome.state,"FILLED")
        self.assertEqual(outcome.filled_quantity,D("0.3"))

    def test_missing_order_not_an_inferred_rejection(self):
        self.assertIsNone(self.adapter.find_order("v2_trade_1"))

    def test_risk_uses_provider_quantity_increment(self):
        account=self.adapter.account("account123")
        quote=self.adapter.quote()
        candidate=Candidate("crypto_sma","migrate","account123","BTC-USD",
             AssetClass.CRYPTO,OrderSide.BUY,self.now,{"indicator":"test"})
        risk=evaluate_risk(account,candidate,quote,
            RiskPolicy(max_order_notional=D("10"),
              max_total_exposure=D("30"),max_position_fraction=D("0.5")),
            now=self.now)
        self.assertEqual(risk.code,"PASS")
        self.assertEqual(risk.quantity%account.capability.quantity_increment,0)
        self.assertLessEqual(risk.quantity*risk.limit_price,D("10"))

if __name__=="__main__": main()
