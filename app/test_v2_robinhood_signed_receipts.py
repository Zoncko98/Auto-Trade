"""Offline signed Robinhood V2 order receipt identity/recovery tests."""
from decimal import Decimal as D
from unittest import TestCase, main
from uuid import UUID
from trader_v2.robinhood_signed_receipts import (
    client_id,normalize_order,RobinhoodReadOnlyReceiptAdapter,
    BrokerEvidenceUnavailable,signed_holding_quantity,
)

ACCOUNT="account123"
KEY="v2_crypto_42"

def order(**kwargs):
    base={"client_order_id":client_id(KEY,ACCOUNT),
          "account_number":ACCOUNT,"id":"broker-uuid-abc",
          "state":"open","filled_asset_quantity":"0"}
    base.update(kwargs)
    return base

class BrokerReads:
    def __init__(self,orders):
        self.response=orders
        self.calls=0
    def orders(self,account):
        assert account==ACCOUNT
        self.calls+=1
        return self.response

class SignedReceiptTests(TestCase):
    def test_client_id_stable_uuid_and_account_scoped(self):
        uid=client_id(KEY,ACCOUNT)
        self.assertEqual(str(UUID(uid)),uid)
        self.assertEqual(client_id(KEY,ACCOUNT),uid)
        self.assertNotEqual(uid,client_id(KEY,"second_account"))
        self.assertNotEqual(uid,client_id("different_key",ACCOUNT))

    def test_no_exact_match_is_not_a_cancellation(self):
        c=BrokerReads([order(client_order_id=client_id("other_key",ACCOUNT))])
        broker=RobinhoodReadOnlyReceiptAdapter(c,ACCOUNT)
        self.assertIsNone(broker.find_order(KEY))
        self.assertEqual(c.calls,1)

    def test_open_ack_without_fill_uses_zero(self):
        receipt=normalize_order(KEY,ACCOUNT,order())
        self.assertEqual(receipt.state,"BROKER_ACCEPTED")
        self.assertEqual(receipt.filled_quantity,D("0"))
        self.assertEqual(receipt.fees,D("0"))

    def test_partial_orders_require_all_economics(self):
        result=normalize_order(KEY,ACCOUNT,order(
            state="partially_filled",filled_asset_quantity="0.1",
            average_price="10.10",fee_charged="0.02"))
        self.assertEqual(result.state,"PARTIALLY_FILLED")
        self.assertEqual(result.filled_quantity,D("0.1"))
        self.assertEqual(result.fees,D("0.02"))

    def test_open_with_cumulative_fill_is_partial_not_open(self):
        result=normalize_order(KEY,ACCOUNT,order(
            state="open",filled_asset_quantity="1",
            average_price="10",fee_charged="0"))
        self.assertEqual(result.state,"PARTIALLY_FILLED")

    def test_filled_with_verified_exec_price_and_fee(self):
        result=normalize_order(KEY,ACCOUNT,order(
            state="filled",filled_asset_quantity="2",
            executions=[{"quantity":"1","effective_price":"12"},
                        {"quantity":"1","effective_price":"10"}],
            fee_charged="0.10"))
        self.assertEqual(result.state,"FILLED")
        self.assertEqual(result.average_price,D("11"))
        self.assertEqual(result.fees,D("0.10"))

    def test_canceled_with_partial_fill_preserves_economics(self):
        result=normalize_order(KEY,ACCOUNT,order(
            state="canceled",filled_asset_quantity="0.1",
            average_price="9",fee_charged="0.01"))
        self.assertEqual(result.state,"CANCELED")
        self.assertEqual(result.filled_quantity,D("0.1"))
        self.assertEqual(result.average_price,D("9"))

    def test_broker_billing_must_never_default_missing_fees_to_zero(self):
        for raw in (None,"NaN","-0.1"):
            with self.subTest(raw=raw),self.assertRaises(BrokerEvidenceUnavailable):
                normalize_order(KEY,ACCOUNT,order(
                    state="filled",filled_asset_quantity="1",
                    average_price="10",fee_charged=raw))

    def test_partial_without_price_and_mismatched_execution_fails(self):
        for row in [
            order(state="partially_filled",filled_asset_quantity="0.2",fee_charged="0"),
            order(state="filled",filled_asset_quantity="2",
                  executions=[{"quantity":"1","effective_price":"10"}],
                  fee_charged="0")
        ]:
            with self.assertRaises(BrokerEvidenceUnavailable):
                normalize_order(KEY,ACCOUNT,row)

    def test_final_state_without_cumulative_quantity_is_unverified(self):
        for state in ("filled","partially_filled","cancelled","rejected"):
            with self.subTest(state=state),self.assertRaises(BrokerEvidenceUnavailable):
                normalize_order(KEY,ACCOUNT,order(
                    state=state,filled_asset_quantity=None))

    def test_duplicate_client_ids_cross_account_and_unknown_states_fail(self):
        duplicate=[order(),order(id="different")]
        with self.assertRaises(BrokerEvidenceUnavailable):
            RobinhoodReadOnlyReceiptAdapter(BrokerReads(duplicate),ACCOUNT).find_order(KEY)
        for bogus in (order(account_number="other"),order(state="finished"),
                      order(client_order_id="wrong"),order(id="")):
            with self.assertRaises(BrokerEvidenceUnavailable):
                normalize_order(KEY,ACCOUNT,bogus)

    def test_adapter_cannot_post_live_orders(self):
        broker=RobinhoodReadOnlyReceiptAdapter(BrokerReads([]),ACCOUNT)
        with self.assertRaises(BrokerEvidenceUnavailable):
            broker.submit({"key":KEY})

    def test_readonly_signed_holdings_accept_high_precision_without_order_permission(self):
        self.assertEqual(signed_holding_quantity("0E-18"),D("0"))
        self.assertEqual(signed_holding_quantity("1.123456789012345678"),
                         D("1.123456789012345678"))
        self.assertEqual(signed_holding_quantity("0.000000000000000001"),
                         D("0.000000000000000001"))
        for raw in (None,False,0.1,"NaN","Infinity","-0.1","1E-30"):
            with self.subTest(raw=raw),self.assertRaises(BrokerEvidenceUnavailable):
                signed_holding_quantity(raw)
    def test_history_unavailable_not_empty(self):
        broker=RobinhoodReadOnlyReceiptAdapter(BrokerReads(None),ACCOUNT)
        with self.assertRaises(BrokerEvidenceUnavailable):
            broker.find_order(KEY)

    def test_malformed_numeric_types_fail_closed(self):
        for n in (0.1,True,"Infinity","-3"):
            with self.subTest(number=n),self.assertRaises(BrokerEvidenceUnavailable):
                normalize_order(KEY,ACCOUNT,order(
                    state="filled",filled_asset_quantity=n,
                    average_price="10",fee_charged="0"))

if __name__=="__main__":
    main()
