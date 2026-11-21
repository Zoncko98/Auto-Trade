"""Fail-closed V2 receipt checks at the simulated-to-broker execution boundary.

This validates evidence from a broker lookup/submit, not authorization to trade.
The existing PaperPipeline remains the only write-capable V2 executor.
"""
from __future__ import annotations

import json
from .contracts import BrokerExecution
from .models import OrderSide, amount


def receipt_failure(key: str, receipt: BrokerExecution, document: str, events: list[dict]) -> str | None:
    """Return a bounded reason code, or None for a consistent cumulative receipt."""
    if not isinstance(receipt, BrokerExecution) or receipt.key != key:
        return "BROKER_ORDER_KEY_MISMATCH"
    try:
        intent = json.loads(document)
        if not isinstance(intent, dict) or intent.get("key") != key:
            return "PERSISTED_INTENT_INVALID"
        requested = amount(intent["quantity"], "requested quantity", False)
        limit = amount(intent["limit_price"], "requested limit", False)
        side = OrderSide(intent["side"])
    except (ValueError, TypeError, KeyError, json.JSONDecodeError):
        return "PERSISTED_INTENT_INVALID"

    filled, price, fees = receipt.filled_quantity, receipt.average_price, receipt.fees
    if filled > requested:
        return "BROKER_OVERFILL_UNVERIFIED"
    if receipt.state == "FILLED" and filled != requested:
        return "BROKER_FULL_FILL_QUANTITY_MISMATCH"
    if receipt.state == "PARTIALLY_FILLED" and not (0 < filled < requested):
        return "BROKER_PARTIAL_FILL_QUANTITY_INVALID"
    if receipt.state == "BROKER_ACCEPTED" and filled != 0:
        return "BROKER_ACCEPTED_WITH_UNREPORTED_FILL"
    if filled == 0 and (price != 0 or fees != 0):
        return "BROKER_ZERO_FILL_COST_MISMATCH"
    if filled > 0 and (price <= 0 or
            (side is OrderSide.BUY and price > limit) or
            (side is OrderSide.SELL and price < limit)):
        return "BROKER_FILL_PRICE_VIOLATES_LIMIT"

    if not isinstance(events, list):
        return "BROKER_HISTORY_INVALID"
    old_id = None
    highest = 0
    try:
        for event in events:
            evidence = event["evidence"]
            if not isinstance(evidence, dict):
                return "BROKER_HISTORY_INVALID"
            recorded_id = evidence.get("broker_order_id")
            if recorded_id is not None:
                if not isinstance(recorded_id, str) or not recorded_id:
                    return "BROKER_HISTORY_INVALID"
                if old_id is not None and old_id != recorded_id:
                    return "PERSISTED_BROKER_ID_CONFLICT"
                old_id = recorded_id
            if "filled_quantity" in evidence:
                cumulative = amount(evidence["filled_quantity"], "historical fill")
                if cumulative > requested:
                    return "PERSISTED_OVERFILL"
                highest = max(highest, cumulative)
    except (KeyError, ValueError, TypeError):
        return "BROKER_HISTORY_INVALID"
    if old_id is not None and receipt.broker_order_id != old_id:
        return "BROKER_ORDER_ID_CHANGED"
    if filled < highest:
        return "BROKER_CUMULATIVE_FILL_REGRESSION"
    if highest > 0 and receipt.state == "BROKER_ACCEPTED":
        return "BROKER_PARTIAL_FILL_STATUS_REGRESSION"
    return None
