from decimal import Decimal as D
from unittest import TestCase, main
from trader_v2.webull_signed_receipts import (
    WebullReceiptUnverified, WebullReadOnlyReceiptAdapter, client_order_id,
    normalize_webull_order,
)

ACCOUNT = "signed-webull-account"
KEY = "v2_webull_order_8"


def row(**changes):
    item = {
        "client_order_id": client_order_id(KEY, ACCOUNT),
        "account_id": ACCOUNT, "order_id": "webull-broker-order-123",
        "status": "SUBMITTED", "filled_quantity": "0",
    }
    item.update(changes)
    return item


class SignedBroker:
    def __init__(self, value):
        self.value = value
        self.lookups = []
    def order_detail(self, account, client):
        self.lookups.append((account, client))
        return self.value


class WebullSignedReceiptTests(TestCase):
    def test_deterministic_account_bound_order_id(self):
        v = client_order_id(KEY, ACCOUNT)
        self.assertEqual(len(v), 32)
        self.assertTrue(all(c in "0123456789abcdef" for c in v))
        self.assertEqual(client_order_id(KEY, ACCOUNT), v)
        self.assertNotEqual(client_order_id(KEY, "other-account"), v)

    def test_signed_read_only_lookup(self):
        broker = SignedBroker({"orders": [row()]})
        receipt = WebullReadOnlyReceiptAdapter(broker, ACCOUNT).find_order(KEY)
        self.assertEqual(receipt.state, "BROKER_ACCEPTED")
        self.assertEqual(receipt.filled_quantity, D("0"))
        self.assertEqual(broker.lookups, [(ACCOUNT, client_order_id(KEY, ACCOUNT))])

    def test_legacy_combo_requires_unique_exact_client_identity(self):
        for data in ({"orders": []}, {"orders": [row(), row()]},
                     {"orders": [row(client_order_id="not_requested")]},
                     {"orders": ["malformed"]}):
            with self.subTest(data=data), self.assertRaises(WebullReceiptUnverified):
                normalize_webull_order(KEY, ACCOUNT, data)

    def test_full_fill_has_source_fee_price_and_time(self):
        receipt = normalize_webull_order(KEY, ACCOUNT, row(
            status="FILLED", filled_quantity="2", filled_price="15.05",
            fee_charged="0.06", filled_time_at="2026-11-21T15:01:00Z"))
        self.assertEqual(receipt.state, "FILLED")
        self.assertEqual(receipt.average_price, D("15.05"))
        self.assertEqual(receipt.fees, D("0.06"))

    def test_partial_cancel_retains_verified_economics(self):
        receipt = normalize_webull_order(KEY, ACCOUNT, row(
            status="CANCELLED", filled_quantity="0.25", filled_price="10.02",
            fee_charged="0.02", filled_time_at="2026-11-21T15:01:00+00:00"))
        self.assertEqual(receipt.state, "CANCELED")
        self.assertEqual(receipt.filled_quantity, D("0.25"))

    def test_signed_pending_with_partial_quantity_is_partial(self):
        receipt = normalize_webull_order(KEY, ACCOUNT, row(
            status="SUBMITTED", filled_quantity="1", filled_price="10",
            fee_charged="0.01", filled_time_at="2026-11-21T15:01:00Z"))
        self.assertEqual(receipt.state, "PARTIALLY_FILLED")

    def test_invalid_fee_price_timestamp_rejects_fills(self):
        changes = (
            {"fee_charged": None},
            {"fee_charged": "NaN"},
            {"fee_charged": "-0.01"},
            {"filled_price": None},
            {"filled_price": "-10"},
            {"filled_time_at": None},
            {"filled_time_at": "2026-11-21T15:00:00"},
        )
        for change in changes:
            with self.subTest(change=change), self.assertRaises(WebullReceiptUnverified):
                normalize_webull_order(KEY, ACCOUNT, row(**{
                    **dict(status="FILLED", filled_quantity="1", filled_price="10",
                    fee_charged="0", filled_time_at="2026-11-21T15:01:00Z"), **change}))

    def test_unsupported_provider_states_and_broker_id_fail_closed(self):
        for change in ({"status":"UNKNOWN_FILLED"}, {"order_id":None},
                       {"account_id":"other-account"}, {"filled_quantity":"-2"},
                       {"filled_quantity":0.2}):
            with self.subTest(change=change), self.assertRaises(WebullReceiptUnverified):
                normalize_webull_order(KEY, ACCOUNT, row(**change))

    def test_zero_filled_final_must_include_signed_quantity(self):
        for status in ("FILLED", "CANCELLED", "FAILED", "PARTIAL_FILLED"):
            with self.subTest(status=status), self.assertRaises(WebullReceiptUnverified):
                normalize_webull_order(KEY, ACCOUNT, row(
                    status=status, filled_quantity=None))

    def test_missing_signed_order_is_not_a_negative_fill(self):
        with self.assertRaises(WebullReceiptUnverified):
            WebullReadOnlyReceiptAdapter(SignedBroker({"orders":[]}),ACCOUNT).find_order(KEY)

    def test_cannot_place_live_order(self):
        with self.assertRaises(WebullReceiptUnverified):
            WebullReadOnlyReceiptAdapter(SignedBroker({}),ACCOUNT).submit({})


if __name__=="__main__":
    main()
