"""Broker gateway tests using only fake tokens and local mocks."""
import json
import unittest
from decimal import Decimal
from unittest.mock import patch

from schwab_gateway import (
    API_HOST, BrokerUnavailable, LiveOrderIntent,
    SchwabBrokerGateway, LiveRiskEnvelope, authorization_url, exchange_authorization_code,
    parse_settled_cash,
)


class SchwabGatewayTests(unittest.TestCase):
    def setUp(self):
        self.account_hash="fake_account_hash_12345"
        self.token="fake-access-token-123456789"
        self.order=LiveOrderIntent(
            "F",2,Decimal("12.50"),self.account_hash,Decimal("100.00"))

    def test_cash_only_limit_order(self):
        self.assertEqual(self.order.validate(),Decimal("25.00"))
        payload=self.order.payload()
        self.assertEqual(payload["orderType"],"LIMIT")
        self.assertEqual(payload["duration"],"DAY")
        self.assertEqual(payload["orderLegCollection"][0]["instruction"],"BUY")
        self.assertEqual(payload["orderLegCollection"][0]["quantity"],2)

    def test_reject_oversized_order(self):
        with self.assertRaisesRegex(ValueError,"cap"):
            LiveOrderIntent("F",10,Decimal("11.00"),self.account_hash).validate()

    def test_reject_fraudulent_order_fields(self):
        for symbol,qty,price in [
            ("F;DROP",1,Decimal("10.00")),
            ("f",1,Decimal("10.00")),
            ("F",-1,Decimal("10.00")),
            ("F",1,Decimal("-1.00")),
            ("F",1,Decimal("1.009")),
        ]:
            with self.assertRaises(ValueError):
                LiveOrderIntent(symbol,qty,price,self.account_hash).validate()

    def test_cap_cannot_be_raised_above_100(self):
        with self.assertRaises(ValueError):
            LiveOrderIntent("F",1,Decimal("10"),self.account_hash,
                            Decimal("100.01")).validate()

    def test_unarmed_broker_never_submits(self):
        broker=SchwabBrokerGateway(self.token,self.account_hash)
        with patch("schwab_gateway._http") as network:
            with self.assertRaisesRegex(BrokerUnavailable,"not armed"):
                broker.place_order(self.order)
            network.assert_not_called()

    def test_even_armed_gateway_cannot_submit_without_reconciliation(self):
        broker=SchwabBrokerGateway(self.token,self.account_hash,live_armed=True)
        with patch("schwab_gateway._http") as network:
            with self.assertRaisesRegex(BrokerUnavailable,"remains locked"):
                broker.place_order(self.order)
            network.assert_not_called()

    def test_oauth_authorization_url(self):
        url=authorization_url(
            "fake-app-key-1234","https://127.0.0.1","state-1234567890123456")
        self.assertTrue(url.startswith(API_HOST+"/v1/oauth/authorize?"))
        self.assertIn("response_type=code",url)
        self.assertIn("state=",url)
        with self.assertRaises(ValueError):
            authorization_url("fake-app-key-1234","http://attacker.test",
                              "state-1234567890123456")

    def test_oauth_token_exchange_payload(self):
        response={
            "access_token":"fake-access-token-123456",
            "refresh_token":"fake-refresh-token-123456",
            "expires_in":1800,
        }
        with patch("schwab_gateway._http",return_value=(200,response,{})) as network:
            got=exchange_authorization_code(
                "fake-app-key-12345","fake-app-secret-123456",
                "https://127.0.0.1","fake-authorization-code-123")
        self.assertEqual(got["expires_in"],1800)
        self.assertEqual(network.call_args.args[0],API_HOST+"/v1/oauth/token")
        self.assertNotIn("fake-app-secret-123456",str(network.call_args.args[2]))

    def test_balance_missing_fails_closed(self):
        for account in [
            {}, {"securitiesAccount":{"currentBalances":{"buyingPower":5000}}},
            {"securitiesAccount":{"currentBalances":{"cashAvailableForTrading":-1}}},
        ]:
            with self.assertRaises(BrokerUnavailable):
                parse_settled_cash(account)

    def test_account_lookup_is_read_only(self):
        broker=SchwabBrokerGateway(self.token,self.account_hash)
        with patch("schwab_gateway._http",return_value=(200,[],{})) as network:
            self.assertEqual(broker.accounts(),[])
        self.assertEqual(network.call_args.args[1],"GET")

    def test_mock_quote_is_read_only(self):
        broker=SchwabBrokerGateway(self.token,self.account_hash)
        with patch("schwab_gateway._http",return_value=(
            200,{"F":{"quote":{"lastPrice":12.5}}},{}
        )) as network:
            quote=broker.quote("F")
        self.assertEqual(quote["quote"]["lastPrice"],12.5)
        self.assertEqual(network.call_args.args[1],"GET")


    def test_reconciled_broker_cap_permits_exactly_100_total(self):
        risk=LiveRiskEnvelope()
        actual=risk.check_candidate(
            self.order,
            broker_settled_cash=Decimal("25.00"),
            aggregate_open_exposure=Decimal("50.00"),
            aggregate_pending_buy_notional=Decimal("25.00"),
            current_daily_drawdown=Decimal("0"),
            open_position_count=1,
            broker_account_reconciled=True,
            normal_market_session=True,
        )
        self.assertEqual(actual,Decimal("25.00"))

    def test_reject_aggregate_over_100_even_with_settled_cash(self):
        risk=LiveRiskEnvelope()
        with self.assertRaisesRegex(BrokerUnavailable,"Aggregate"):
            risk.check_candidate(
                self.order,
                broker_settled_cash=Decimal("500.00"),
                aggregate_open_exposure=Decimal("60.00"),
                aggregate_pending_buy_notional=Decimal("20.00"),
                current_daily_drawdown=Decimal("0"),
                open_position_count=1,
                broker_account_reconciled=True,
                normal_market_session=True,
            )

    def test_no_market_session_or_reconciliation_is_blocked(self):
        risk=LiveRiskEnvelope()
        baseline={
            "broker_settled_cash":Decimal("100.00"),
            "aggregate_open_exposure":Decimal("0"),
            "aggregate_pending_buy_notional":Decimal("0"),
            "current_daily_drawdown":Decimal("0"),
            "open_position_count":0,
            "broker_account_reconciled":True,
            "normal_market_session":True,
        }
        for altered in (
            {"broker_account_reconciled":False},
            {"normal_market_session":False},
            {"current_daily_drawdown":Decimal("5")},
            {"broker_settled_cash":Decimal("20")},
        ):
            inputs={**baseline,**altered}
            with self.assertRaises(BrokerUnavailable):
                risk.check_candidate(self.order,**inputs)


if __name__=="__main__":
    unittest.main(verbosity=2)
