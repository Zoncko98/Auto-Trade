"""Broker-confirmed, asset-specific Webull technical candidates.

Uses fresh Webull executable bid/ask and completed one-minute OHLCV bars.
No AI inference or order submission is performed here.
"""
from datetime import datetime,timezone,time as dtime
from decimal import Decimal,InvalidOperation
from zoneinfo import ZoneInfo
from webull_broker import positive
class WebullSignalError(ValueError):pass

def _time(raw):
    if isinstance(raw,(int,float)) and not isinstance(raw,bool):
        v=float(raw)
        if v>100000000000:v/=1000
        return datetime.fromtimestamp(v,timezone.utc)
    if isinstance(raw,str):
        if raw.isdigit():return _time(int(raw))
        try:
            d=datetime.fromisoformat(raw.replace("Z","+00:00"))
            if d.tzinfo is not None:return d.astimezone(timezone.utc)
        except ValueError:pass
    raise WebullSignalError("Market observation timestamp invalid")

def _first_price(quote,*keys):
    for key in keys:
        raw=quote.get(key)
        if isinstance(raw,list) and raw:
            raw=raw[0]
        if isinstance(raw,dict):raw=raw.get("price")
        if raw is not None:
            try:return positive(raw)
            except Exception:continue
    raise WebullSignalError("No executable broker bid/ask")

def _quote(quote,now):
    if not isinstance(quote,dict):raise WebullSignalError("Missing broker quote")
    bid=_first_price(quote,"bid","bid_price","bids","bid_list")
    ask=_first_price(quote,"ask","ask_price","asks","ask_list")
    if bid>ask:raise WebullSignalError("Broker quote crossed")
    stamp=quote.get("quote_time") or quote.get("time") or quote.get("timestamp")
    if stamp is None:raise WebullSignalError("Broker quote timestamp unavailable")
    age=(now-_time(stamp)).total_seconds()
    if not 0<=age<=90:raise WebullSignalError("Broker quote stale")
    spread=(ask-bid)/ask*100
    if spread>Decimal("0.5"):raise WebullSignalError("Broker spread above 0.5%")
    return bid,ask,spread

def core_stock_session(now):
    et=now.astimezone(ZoneInfo("America/New_York"))
    return et.weekday()<5 and dtime(9,35)<=et.time().replace(tzinfo=None)<dtime(15,50)

def evaluate(symbol,asset,quote,bars,now=None):
    now=now or datetime.now(timezone.utc)
    if now.tzinfo is None:raise WebullSignalError("Time zone required")
    if asset not in ("EQUITY","CRYPTO"):raise WebullSignalError("Unsupported market")
    if asset=="EQUITY" and not core_stock_session(now):
        return {"symbol":symbol,"asset":asset,"technical_approved":False,
                "technical_exit":False,"reason":"Outside conservative US core stock session",
                "at":now.isoformat(),"source":"WEBULL_M1"}
    bid,ask,spread=_quote(quote,now)
    if not isinstance(bars,list):raise WebullSignalError("Missing M1 bar history")
    valid={}
    for item in bars:
        if not isinstance(item,dict):continue
        try:
            at=_time(item["time"])
            close=positive(item["close"])
            age=(now-at).total_seconds()
            if not 60<=age<=1200:continue  # Completed and fresh bars only.
            valid[at]=close
        except (ValueError,TypeError,KeyError,OverflowError):continue
    points=sorted(valid.items())
    if len(points)<6 or (points[-1][0]-points[0][0]).total_seconds()<300:
        return {"symbol":symbol,"asset":asset,"technical_approved":False,
                "technical_exit":False,"reason":"Need six recent completed 1-minute bars spanning 5 minutes",
                "at":now.isoformat(),"source":"WEBULL_M1","spread_pct":float(spread)}
    if (now-points[-1][0]).total_seconds()>180:
        raise WebullSignalError("Last completed price bar stale")
    mid=(bid+ask)/2
    levels=[points[int(i*(len(points)-1)/3)][1] for i in range(4)]
    momentum=(mid/levels[0]-1)*100
    rising=all(levels[i]>levels[i-1] for i in range(1,4))
    declining=all(levels[i]<levels[i-1] for i in range(1,4))
    approved=Decimal("0.5")<=momentum<=Decimal("2") and rising
    exit_signal=Decimal("-2")<=momentum<=Decimal("-0.5") and declining
    return {"symbol":symbol,"asset":asset,"technical_approved":approved,
            "technical_exit":exit_signal,"source":"WEBULL_M1",
            "at":now.isoformat(),"bid":str(bid),"ask":str(ask),
            "mid":str(mid),"spread_pct":round(float(spread),4),
            "momentum_pct":round(float(momentum),4),
            "reason":("Qualified rising momentum" if approved else
                      "Declining momentum" if exit_signal else "No qualifying momentum"),
            "bars":len(points),"ai_approved":False}
