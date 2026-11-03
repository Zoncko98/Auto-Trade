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
    momentum=None
    if len(fresh)>=4 and max(a for a,_ in fresh)>=300:
        old=fresh[0][1]
        momentum=(mid/old-1)*100
        signal=("MOMENTUM_CANDIDATE" if Decimal("0.5")<=momentum<=Decimal("2")
                and spread<=Decimal("0.5") and
                all(fresh[i][1]>fresh[i-1][1] for i in range(1,len(fresh)))
                else "NO_SIGNAL")
    exit_candidate=(len(fresh)>=4 and max(a for a,_ in fresh)>=300
        and momentum is not None and Decimal("-2")<=momentum<=Decimal("-0.5")
        and spread<=Decimal("0.5") and
        all(fresh[i][1]<fresh[i-1][1] for i in range(1,len(fresh))))
    return {"at":now.isoformat(),"symbol":symbol,"mid":str(mid),
            "technical_exit":exit_candidate,
            "spread_pct":round(float(spread),4),"momentum_pct":round(float(momentum),4) if momentum is not None else None,
            "signal":signal,"technical_approved":signal=="MOMENTUM_CANDIDATE",
            "ai_approved":False,"execution_eligible":False}
