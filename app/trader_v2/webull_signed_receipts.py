"""Read-only Webull V2 signed order receipt translation.

Never calls order placement. A missing or ambiguous signed order is NOT proof
that an earlier broker POST failed; the canonical intent must remain locked.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from hashlib import sha256
from datetime import datetime
from .contracts import BrokerExecution
from .models import valid_id


class WebullReceiptUnverified(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


_STATES = {
    "PENDING": "BROKER_ACCEPTED",
    "SUBMITTED": "BROKER_ACCEPTED",
    "PARTIAL_FILLED": "PARTIALLY_FILLED",
    "FILLED": "FILLED",
    "CANCELLED": "CANCELED",
    "CANCELED": "CANCELED",
    "FAILED": "REJECTED",
}


def client_order_id(key: str, account: str) -> str:
    """Stable 32-hex Webull v3 ID, namespaced by account and V2 intent key."""
    valid_id(key)
    if not isinstance(account, str) or not 1 <= len(account) <= 80:
        raise WebullReceiptUnverified("WEBULL_ACCOUNT_INVALID")
    return sha256(("auto-trader-v2|webull|" + account + "|" + key).encode()).hexdigest()[:32]


def _nonnegative(value, field, positive=False):
    if type(value) not in (str, int, Decimal):
        raise WebullReceiptUnverified("WEBULL_" + field + "_INVALID")
    try:
        result = Decimal(str(value))
    except (TypeError, ValueError, InvalidOperation):
        raise WebullReceiptUnverified("WEBULL_" + field + "_INVALID") from None
    if (not result.is_finite() or result < 0 or (positive and result == 0)
            or result.adjusted() > 14):
        raise WebullReceiptUnverified("WEBULL_" + field + "_INVALID")
    return result


def _signed_detail(payload, key, account):
    if not isinstance(payload, dict):
        raise WebullReceiptUnverified("WEBULL_ORDER_DETAIL_UNVERIFIED")
    rows = payload.get("orders") if isinstance(payload.get("orders"), list) else [payload]
    identity = client_order_id(key, account)
    if not rows or any(not isinstance(row, dict) for row in rows):
        raise WebullReceiptUnverified("WEBULL_ORDER_LOOKUP_INCOMPLETE")
    matches = [row for row in rows if row.get("client_order_id") == identity]
    if len(matches) != 1:
        raise WebullReceiptUnverified("WEBULL_ORDER_IDENTITY_MISSING_OR_AMBIGUOUS")
    row = matches[0]
    if row.get("account_id") not in (None, account):
        raise WebullReceiptUnverified("WEBULL_BROKER_ACCOUNT_MISMATCH")
    return row


def normalize_webull_order(key, account, payload):
    row = _signed_detail(payload, key, account)
    state = row.get("status")
    if not isinstance(state, str) or state.upper() not in _STATES:
        raise WebullReceiptUnverified("WEBULL_ORDER_STATE_UNVERIFIED")
    state = state.upper()
    order_id = row.get("order_id")
    if not isinstance(order_id, str) or not order_id or len(order_id) > 160:
        raise WebullReceiptUnverified("WEBULL_BROKER_ORDER_ID_UNVERIFIED")
    raw_qty = row.get("filled_quantity")
    # An acknowledged but unfilled order may omit cumulative fills; terminal
    # and partially filled statuses require an explicit signed number.
    if raw_qty is None and state in ("PENDING", "SUBMITTED"):
        qty = Decimal("0")
    else:
        qty = _nonnegative(raw_qty, "FILLED_QUANTITY")
    if state == "FILLED" and qty == 0:
        raise WebullReceiptUnverified("WEBULL_FILLED_ORDER_ZERO_QUANTITY")
    if state == "PARTIAL_FILLED" and qty == 0:
        raise WebullReceiptUnverified("WEBULL_PARTIAL_ORDER_ZERO_QUANTITY")
    if qty:
        price = _nonnegative(row.get("filled_price"), "FILLED_PRICE", positive=True)
        fee = _nonnegative(row.get("fee_charged"), "FEE")
        timestamp = row.get("filled_time_at")
        if not isinstance(timestamp, str):
            raise WebullReceiptUnverified("WEBULL_EXECUTION_TIME_UNVERIFIED")
        try:
            observed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            if observed.tzinfo is None:
                raise ValueError("naive timestamp")
        except ValueError:
            raise WebullReceiptUnverified("WEBULL_EXECUTION_TIME_UNVERIFIED") from None
    else:
        price, fee = Decimal("0"), Decimal("0")
        if row.get("fee_charged") not in (None, "0", 0, "0.0"):
            raise WebullReceiptUnverified("WEBULL_ZERO_FILL_FEE_CONFLICT")
    normalized = _STATES[state]
    if qty > 0 and normalized == "BROKER_ACCEPTED":
        normalized = "PARTIALLY_FILLED"
    try:
        return BrokerExecution(key, normalized, order_id, qty, price, fee)
    except (ValueError, TypeError):
        raise WebullReceiptUnverified("WEBULL_RECEIPT_CONTRACT_INVALID") from None


class WebullReadOnlyReceiptAdapter:
    provider_id = "webull"

    def __init__(self, signed_broker, account_id):
        if not isinstance(account_id, str) or not 1 <= len(account_id) <= 80:
            raise ValueError("Account selection required")
        self.broker = signed_broker
        self.account_id = account_id

    def find_order(self, key):
        # Signed account verification and throttling are performed by WebullBroker.
        identity = client_order_id(key, self.account_id)
        payload = self.broker.order_detail(self.account_id, identity)
        return normalize_webull_order(key, self.account_id, payload)

    def submit(self, *_args, **_kwargs):
        raise WebullReceiptUnverified("WEBULL_V2_LIVE_WRITER_NOT_CUT_OVER")
