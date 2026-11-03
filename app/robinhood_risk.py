"""Isolated crypto account risk preflight; never places orders."""
from decimal import Decimal,InvalidOperation

class RiskDenied(ValueError):pass

def money(value):
    try: number=Decimal(str(value))
    except (ValueError,TypeError,InvalidOperation):
        raise RiskDenied("Invalid monetary amount") from None
    if not number.is_finite() or number<0:raise RiskDenied("Invalid nonnegative amount")
    return number

def preflight(account,policy,symbol,ask,spread_pct,pending_orders=0):
    if policy.get("enabled") is not True:raise RiskDenied("Account live execution not enabled")
    if policy.get("account")!=account.get("account_number"):
        raise RiskDenied("Account not explicitly selected")
    if account.get("status")!="active" or account.get("is_api_tradable") is not True:
        raise RiskDenied("Account cannot trade through API")
    if account.get("buying_power_currency")!="USD":raise RiskDenied("Buying power not USD")
    if pending_orders:raise RiskDenied("Unreconciled orders")
    from robinhood_crypto_gateway import PAIR
    if not isinstance(symbol,str) or not PAIR.fullmatch(symbol):
        raise RiskDenied("Invalid USD trading pair")
    cash=money(account.get("buying_power"))
    maximum=money(policy.get("max_order_usd",0))
    minimum=money(policy.get("verified_broker_minimum_usd",0))
    price=money(ask)
    spread=money(spread_pct)
    if maximum<=0 or maximum>Decimal("25"):
        raise RiskDenied("Per-order limit unavailable or excessive")
    if price<=0 or spread>Decimal("0.5"):
        raise RiskDenied("Quote or spread unacceptable")
    if minimum<=0:raise RiskDenied("Broker minimum has not been verified")
    budget=min(maximum,cash*Decimal("0.25"))
    if budget<minimum:raise RiskDenied("Buying power insufficient for verified minimum")
    return {"budget_usd":str(budget),"pair":symbol}
