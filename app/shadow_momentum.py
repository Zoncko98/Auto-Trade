"""Read-only short-term momentum experiment; never constructs or submits orders."""
from decimal import Decimal, InvalidOperation
from autonomous_selector import ranked_candidates
from live_order_safety import LiveBlocked

# Research hypotheses, not execution assumptions or profit guarantees.
GROSS_TARGET_PCT=Decimal("1.50")
ROUND_TRIP_COST_PCT=Decimal("0.35")
MIN_NET_TARGET_PCT=Decimal("0.60")
MAX_SPREAD_PCT=Decimal("0.005")
MIN_MOMENTUM_PCT=Decimal("0.30")
MAX_MOMENTUM_PCT=Decimal("2.50")

def shadow_scan(quotes, candle_provider, now, excluded=()):
    """Describe a hypothetical entry without ever touching the account."""
    exclusions=set(excluded)
    screened=ranked_candidates(quotes, now)
    tally={"ranked":len(screened),"checked":0,"wide_spread":0,
           "stale_candles":0,"no_momentum":0,"cost_gate":0}
    best=None
    for score,symbol,bid,ask in screened:
        if symbol in exclusions: continue
        tally["checked"]+=1
        if (ask-bid)/ask>MAX_SPREAD_PCT:
            tally["wide_spread"]+=1
            continue
        try:
            bars=sorted(candle_provider(symbol),key=lambda b:b["datetime"])
            cutoff=int(now.timestamp()*1000)-60000
            recent=[(int(b["datetime"]),Decimal(str(b["close"]))) for b in bars
                    if int(b["datetime"])+300000<=cutoff]
            if len(recent)<4 or recent[-1][0]+300000<int(now.timestamp()*1000)-720000:
                tally["stale_candles"]+=1
                continue
            closes=[x[1] for x in recent[-4:]]
            if min(closes)<=0:
                tally["stale_candles"]+=1
                continue
            momentum=(closes[-1]/closes[-4]-1)*100
            if not (MIN_MOMENTUM_PCT<=momentum<=MAX_MOMENTUM_PCT) or not (closes[-1]>closes[-2]>closes[-3]):
                tally["no_momentum"]+=1
                continue
            spread_pct=(ask-bid)/ask*100
            projected_net=GROSS_TARGET_PCT-ROUND_TRIP_COST_PCT-spread_pct
            if projected_net<MIN_NET_TARGET_PCT:
                tally["cost_gate"]+=1
                continue
            row={"symbol":symbol,"momentum_pct":round(float(momentum),3),
                 "spread_pct":round(float(spread_pct),3),
                 "hypothetical_net_target_pct":round(float(projected_net),3),
                 "candle":recent[-1][0]}
            if best is None or row["momentum_pct"]>best["momentum_pct"]:best=row
        except (LiveBlocked,ValueError,TypeError,KeyError,ArithmeticError,InvalidOperation):
            tally["stale_candles"]+=1
    return {"mode":"SHADOW_ONLY","candidate":best,"filters":tally,
            "assumed_round_trip_cost_pct":float(ROUND_TRIP_COST_PCT),
            "gross_target_pct":float(GROSS_TARGET_PCT),
            "simulated_orders":0}
