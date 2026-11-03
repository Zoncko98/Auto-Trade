"""Conservative, evidence-based Robinhood sell-side fee reserve.

The user-configured fee buffer is a minimum. Verified recent broker fills can
raise the effective estimate; no broker fee is modified or collected here.
"""
from decimal import Decimal,InvalidOperation

def _valid(value,allow_zero=False):
    try:
        x=Decimal(str(value))
        if x.is_finite() and (x>=0 if allow_zero else x>0):
            return x
    except (TypeError,ValueError,InvalidOperation):pass
    return None

def effective_sell_fee_pct(policy,journal):
    account=policy.get("account")
    floor=_valid(policy.get("fee_buffer_pct","0.25"),allow_zero=True)
    if floor is None or floor>Decimal("2"):
        raise ValueError("Configured sell fee buffer invalid")
    rows=journal.load().get("orders",[])
    verified=[]
    # Prefer the most recent cost-bearing fills. Fees on early sub-dollar
    # test transactions are not representative of normal live order sizes.
    for row in reversed(rows):
        if not isinstance(row,dict) or row.get("account")!=account:
            continue
        if row.get("status")!="filled" or row.get("side") not in ("buy","sell"):
            continue
        if row.get("fee_verified") is False:continue
        qty=_valid(row.get("filled_quantity"))
        price=_valid(row.get("average_fill_price"))
        fee=_valid(row.get("fee_charged"),allow_zero=True)
        if qty is None or price is None or fee is None:continue
        notional=qty*price
        if notional<Decimal("1"):continue
        observed=(fee/notional)*Decimal("100")
        if observed>Decimal("10"):
            # implausible/untrusted fee data cannot decrease the reserve
            continue
        verified.append(observed)
        if len(verified)>=8:break
    if not verified:
        return floor,"configured"
    # Margin covers moderate variation between filled buy/sell commissions.
    observed_ceiling=max(verified)*Decimal("1.05")
    return max(floor,observed_ceiling),"broker_fill_history"
