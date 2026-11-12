"""Conservative Robinhood entry-quality gate. Read-only; never authorizes an order."""
from datetime import datetime, timezone, timedelta
from decimal import Decimal, InvalidOperation
from robinhood_fee_estimates import effective_sell_fee_pct

class EntryQualityBlocked(ValueError):
    pass

def _number(value):
    try:
        v=Decimal(str(value))
    except (ValueError, TypeError, InvalidOperation):
        raise EntryQualityBlocked("Invalid entry quality input") from None
    if not v.is_finite() or v<0:
        raise EntryQualityBlocked("Invalid entry quality input")
    return v

def _fill_time(value):
    if not isinstance(value,str):
        return None
    try:
        when=datetime.fromisoformat(value.replace("Z","+00:00"))
        return when.astimezone(timezone.utc) if when.tzinfo else None
    except (TypeError,ValueError,OverflowError):
        return None

def verify_entry(policy,signal,broker_spread,journal,now=None):
    """Fail closed on friction or repeated verified losses; exits are unaffected."""
    now=now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise EntryQualityBlocked("Quality check requires timezone-aware time")
    spread=_number(broker_spread)
    if spread>Decimal("0.20"):
        raise EntryQualityBlocked("Entry blocked: broker bid-ask spread above 0.20%")
    try:
        fee,_=effective_sell_fee_pct(policy,journal)
    except (ValueError,TypeError,KeyError):
        raise EntryQualityBlocked("Broker fee estimate unavailable") from None
    take_profit=_number(policy.get("take_profit_pct","3"))
    min_profit=_number(policy.get("min_profit_pct","1"))
    friction=spread+fee*2
    if take_profit-friction<min_profit:
        raise EntryQualityBlocked("Entry blocked: estimated round-trip costs leave inadequate net target")
    # Only qualify real live market observations, never fabricate history.
    if signal.get("source") in ("COINBASE_WS","COINBASE_RECENT_CACHE","ROBINHOOD_POLL_FALLBACK"):
        momentum=_number(signal.get("momentum_pct"))
        span=_number(signal.get("history_span_seconds"))
        try:
            points=int(signal.get("history_points",0))
        except (ValueError,TypeError,OverflowError):
            raise EntryQualityBlocked("Entry blocked: price history invalid") from None
        if not (Decimal("0.8")<=momentum<=Decimal("1.6")
                and span>=Decimal("600")
                and signal.get("trend_up") is True
                and points>=4):
            raise EntryQualityBlocked("Entry blocked: insufficient confirmed trend or late momentum")
        if signal.get("source")=="COINBASE_RECENT_CACHE":
            raise EntryQualityBlocked("Entry blocked: cached cross-venue quotes are not live")
    rows=journal.load().get("orders",[])
    if not isinstance(rows,list):
        raise EntryQualityBlocked("Broker journal invalid")
    # Historic journal shows 384 buys in roughly ten days. Limit churn independently
    # of the USD loss stop, but leave existing-position exit handling unchanged.
    recent_buys=0
    for row in rows:
        if not isinstance(row,dict) or row.get("account")!=policy.get("account"):
            continue
        if row.get("side")=="buy" and row.get("status")=="filled":
            t=_fill_time(row.get("filled_at"))
            if t is not None and now-timedelta(hours=24)<=t<=now:
                recent_buys+=1
    if recent_buys>=6:
        raise EntryQualityBlocked("Entry blocked: six filled buys in trailing 24 hours")
    closed=[]
    for row in rows:
        if not isinstance(row,dict) or row.get("account")!=policy.get("account"):
            continue
        if row.get("side")!="sell" or row.get("status")!="filled":
            continue
        t=_fill_time(row.get("filled_at"))
        if t is None or t>now or t<now-timedelta(hours=48):
            continue
        try:
            pnl=Decimal(str(row.get("realized_pnl_usd")))
        except (TypeError,ValueError,InvalidOperation):
            continue
        if not pnl.is_finite():
            continue
        closed.append((t,row.get("symbol"),pnl))
    symbol=signal.get("symbol")
    same_asset=[x for x in closed if x[1]==symbol]
    if sum(x[2]<0 for x in same_asset)>=2:
        raise EntryQualityBlocked("Entry blocked: asset has two verified losing exits in 48 hours")
    recent=sorted((x for x in closed if x[0]>=now-timedelta(hours=6)),
                  key=lambda x:x[0],reverse=True)
    if len(recent)>=4 and all(x[2]<0 for x in recent[:4]):
        raise EntryQualityBlocked("Entry blocked: four consecutive verified losses in six hours")
    return {"broker_spread_pct":str(spread),"estimated_round_trip_cost_pct":str(friction),
            "target_net_after_cost_pct":str(take_profit-friction),"fee_source":"recent_fills_or_policy"}
