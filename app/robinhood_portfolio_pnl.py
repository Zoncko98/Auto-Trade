"""Read-only estimated average acquisition cost from accessible Robinhood crypto orders.

Robinhood Crypto v2 holdings contain quantities but not Robinhood app average
cost. This approximation uses broker-reported fills only (excluding buy fees,
following the app's displayed average-cost reference) and is deliberately
unavailable when historical fills cannot reproduce current holding quantity.
Never use this UI estimate as a live trading risk or tax cost-basis input.
"""
from datetime import datetime,timezone
from decimal import Decimal,InvalidOperation

def nonnegative(value, positive=False):
    if value is None or isinstance(value,bool):
        return None
    try:
        n=Decimal(str(value))
    except (InvalidOperation,ValueError,TypeError):
        return None
    return n if n.is_finite() and n>=0 and (not positive or n>0) else None

def _time(raw):
    if not isinstance(raw,str):
        return None
    try:
        d=datetime.fromisoformat(raw.replace("Z","+00:00"))
        return d.astimezone(timezone.utc) if d.tzinfo is not None else None
    except (ValueError,OverflowError):
        return None

def _fill(order):
    """(quantity, execution-weighted price); never treat intended limit as fill."""
    qty=nonnegative(order.get("filled_asset_quantity"),positive=True)
    price=nonnegative(order.get("average_price"),positive=True)
    executions=order.get("executions")
    if isinstance(executions,list) and executions:
        valid=[]
        for x in executions:
            if not isinstance(x,dict):
                continue
            q=nonnegative(x.get("quantity"),positive=True)
            p=nonnegative(x.get("effective_price"),positive=True)
            if q is not None and p is not None:
                valid.append((q,p))
        if valid:
            if qty is None:
                qty=sum((q for q,_ in valid),Decimal("0"))
            if price is None:
                total=sum((q*p for q,p in valid),Decimal("0"))
                count=sum((q for q,_ in valid),Decimal("0"))
                price=total/count if count>0 else None
    return qty,price

def estimated_acquisition_cost(symbol, held_quantity, orders):
    """Return (avg cost USD, why unavailable). Reconciles every broker fill."""
    held=nonnegative(held_quantity,positive=True)
    if held is None:
        return None,"Invalid or zero holding quantity"
    events=[]
    incomplete=False
    for order in orders:
        if not isinstance(order,dict) or order.get("symbol")!=symbol:
            continue
        side=str(order.get("side","")).lower()
        if side not in ("buy","sell"):
            continue
        qty,price=_fill(order)
        if qty is None:
            if str(order.get("state","")).lower()=="filled":
                incomplete=True
            continue
        moment=_time(order.get("created_at"))
        if moment is None or price is None:
            incomplete=True
            continue
        events.append((moment,side,qty,price))
    if incomplete:
        return None,"Broker fill prices or timestamps are incomplete"
    if not events:
        return None,"No matching broker purchase fills available"
    events.sort(key=lambda row:row[0])
    owned=Decimal("0")
    acquisition=Decimal("0")
    for _,side,qty,price in events:
        if side=="buy":
            owned+=qty
            acquisition+=qty*price
        else:
            if qty>owned:
                return None,"Broker history does not account for earlier holdings"
            if owned>0:
                acquisition-=acquisition/owned*qty
                owned-=qty
            if owned==0:
                acquisition=Decimal("0")
    tolerance=max(Decimal("0.00000001"),held*Decimal("0.000001"))
    if owned<=0 or abs(held-owned)>tolerance:
        return None,"Broker fills do not reconcile to held quantity (transfers/rewards or missing history)"
    return acquisition/owned,None

def position_return(held_quantity, mark_price, average_cost):
    qty=nonnegative(held_quantity,positive=True)
    mark=nonnegative(mark_price,positive=True)
    cost=nonnegative(average_cost,positive=True)
    if qty is None or mark is None or cost is None:
        return None,None
    pnl=qty*(mark-cost)
    percent=(mark/cost-1)*Decimal("100")
    return pnl,percent
