"""Signed Webull USD cash settlement evidence, read-only and fail-closed.

A signed cash balance, buying power or margin limit is NOT settled funds.
Missing held/frozen details cannot silently become a zero liability.
"""
from decimal import Decimal,InvalidOperation


def _cash(value):
    if type(value) not in (str,int,Decimal):
        return None
    try:
        n=Decimal(str(value))
    except (TypeError,ValueError,InvalidOperation):
        return None
    return n if n.is_finite() and n>=0 and n.adjusted()<15 else None


def signed_settled_cash_budget(payload):
    """Return conservative verified spendable settled USD or None.

    This is a budget observation, never evidence of broker order acceptance.
    Account permissions, margin class, market session and writer ownership
    are separately validated by the trading pipeline.
    """
    if not isinstance(payload,dict) or payload.get("total_asset_currency")!="USD":
        return None
    assets=payload.get("account_currency_assets")
    if not isinstance(assets,list):
        return None
    usd=[row for row in assets if isinstance(row,dict) and row.get("currency")=="USD"]
    if len(usd)!=1:
        return None
    row=usd[0]
    values=[_cash(payload.get("total_cash_balance"))]
    values.extend(_cash(row.get(key)) for key in (
        "cash_balance","settled_cash","held_amount","frozen_amount"))
    if any(n is None for n in values):
        return None
    total,cash,settled,held,frozen=values
    if settled>cash or cash>total+Decimal("0.01"):
        return None
    if payload.get("open_margin_calls") not in (None,"","[]",[]):
        return None
    for key in ("used_margin","used_margin_for_open_order","margin_debit"):
        value=payload.get(key)
        if value not in (None,""):
            used=_cash(value)
            if used is None or used!=0:
                return None
    budget=max(Decimal("0"),min(total,cash,settled)-held-frozen)
    for field in ("buying_power","available_withdrawal"):
        value=row.get(field)
        if value not in (None,""):
            cap=_cash(value)
            if cap is None:
                return None
            budget=min(budget,cap)
    return max(Decimal("0"),budget)
