"""Read-only sampled-price crypto momentum observations; no AI authorization."""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

PAIRS=("BTC-USD","ETH-USD","SOL-USD","DOGE-USD")
def _decimal(value):
    try: d=Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):raise ValueError("Invalid quote") from None
    if not d.is_finite() or d<=0:raise ValueError("Invalid quote")
    return d

def observe(history,symbol,quote,now=None):
    now=now or datetime.now(timezone.utc)
    if not isinstance(symbol,str) or not symbol.endswith("-USD") or not symbol[:-4].isalnum() or len(symbol)>20:
        raise ValueError("Unsupported pair")
    rows=quote.get("results") if isinstance(quote,dict) else None
    matches=[r for r in rows if isinstance(r,dict) and r.get("symbol")==symbol] if isinstance(rows,list) else []
    if len(matches)!=1:raise ValueError("Missing broker quote")
    bid=_decimal(matches[0].get("bid"));ask=_decimal(matches[0].get("ask"))
    if ask<bid:raise ValueError("Crossed quote")
    spread=(ask-bid)/ask*100
    points=[r for r in history if isinstance(r,dict) and r.get("symbol")==symbol]
    points=[r for r in points if isinstance(r.get("at"),str) and r.get("mid") is not None]
    fresh=[]
    for row in points[-24:]:
        try:
            age=(now-datetime.fromisoformat(row["at"].replace("Z","+00:00"))).total_seconds()
            mid=_decimal(row["mid"])
            if 0<=age<=3600:fresh.append((age,mid))
        except (ValueError,TypeError,AttributeError):continue
    mid=(bid+ask)/2
    fresh.append((0,mid))
    # Need genuine historical observations spanning at least 5 minutes.
    signal="INSUFFICIENT_HISTORY"
    reason="Need at least 4 samples spanning 5 minutes"
    momentum=None
    span=max((a for a,_ in fresh),default=0)
    trend_up=False;trend_down=False
    checks=[]
    if len(fresh)>=4 and span>=300:
        signal="NO_SIGNAL"
        fresh.sort(key=lambda point:-point[0])
        checks=[fresh[int(i*(len(fresh)-1)/3)][1] for i in range(4)]
        old=checks[0]
        momentum=(mid/old-1)*100
        trend_up=all(checks[i]>checks[i-1] for i in range(1,4))
        trend_down=all(checks[i]<checks[i-1] for i in range(1,4))
        if spread>Decimal("0.5"):
            reason="Spread exceeds 0.5% entry ceiling"
        elif momentum<Decimal("0.5"):
            reason="Momentum below +0.5% entry floor"
        elif momentum>Decimal("2"):
            reason="Momentum above +2.0% entry ceiling"
        elif not trend_up:
            reason="Four checkpoint prices are not strictly rising"
        else:
            signal="MOMENTUM_CANDIDATE"
            reason="Qualified +0.5% to +2.0% rising momentum with acceptable spread"
    exit_candidate=(len(fresh)>=4 and span>=300
        and momentum is not None and Decimal("-2")<=momentum<=Decimal("-0.5")
        and spread<=Decimal("0.5") and trend_down)
    return {"at":now.isoformat(),"symbol":symbol,"mid":str(mid),
            "technical_exit":exit_candidate,
            "spread_pct":round(float(spread),4),"momentum_pct":round(float(momentum),4) if momentum is not None else None,
            "history_points":len(fresh),"history_span_seconds":round(float(span),1),
            "trend_up":trend_up,"trend_down":trend_down,"signal_reason":reason,
            "signal":signal,"technical_approved":signal=="MOMENTUM_CANDIDATE",
            "ai_approved":False,"execution_eligible":False}
