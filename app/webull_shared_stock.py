"""Use Schwab's existing five-minute crossover/continuation selector with Webull market data.

This module contains no broker order calls, no AI, and no account state.
Quotes and prices remain broker-sourced. Webull-specific 0.5% spread and
90-second freshness checks run before the shared Schwab ranking code.
"""
import re
from datetime import datetime,timezone
from decimal import Decimal
from autonomous_selector import UNIVERSE,ranked_candidates,choose_entry
from live_order_safety import LiveBlocked
from webull_broker import positive,WebullError
from webull_signals import _quote,_time,core_stock_session,WebullSignalError

SHARED_STOCK_SOURCE="WEBULL_SHARED_SCHWAB_M5"
STOCK_SCAN_SYMBOLS=UNIVERSE

def _safe_data_reason(exc):
    # Webull SDK errors can embed signed headers. Only expose codes/classes.
    if isinstance(exc,(WebullError,WebullSignalError)) or type(exc).__name__=="ServerException":
        match=re.search(r"HTTP (?:Status: )?([45]\d\d)",str(exc))
        if match:return "MARKET_DATA_WEBULL_HTTP_"+match.group(1)
        if isinstance(exc,WebullSignalError):
            upper=re.sub(r"[^A-Z0-9]+","_",str(exc).upper()).strip("_")[:78]
            return "MARKET_DATA_SIGNAL_"+upper
    return "MARKET_DATA_"+type(exc).__name__.upper()[:64]

def _convert_quote(symbol, depth, snapshot, now):
    if not isinstance(snapshot,dict) or snapshot.get("symbol")!=symbol:
        raise WebullSignalError("Webull stock snapshot symbol mismatch")
    bid,ask,spread=_quote(depth,now)
    # Verify Webull's data provider reported real liquidity; do not infer volume
    # or current prices from another broker. Snapshot ratio is a fraction.
    volume=positive(snapshot.get("volume"))
    ratio=Decimal(str(snapshot.get("change_ratio")))
    if not ratio.is_finite() or abs(ratio)>Decimal("1"):
        raise WebullSignalError("Webull daily change invalid")
    raw_time=depth.get("quote_time") or depth.get("time") or depth.get("timestamp")
    when=_time(raw_time)
    row={"assetMainType":"EQUITY","quote":{
        "bidPrice":str(bid),"askPrice":str(ask),
        "quoteTime":int(when.timestamp()*1000),
        "totalVolume":str(volume),"netPercentChange":str(ratio*100)}}
    return row,float(spread)

def _convert_bars(rows,now):
    if not isinstance(rows,list):
        raise WebullSignalError("Webull five-minute bar history missing")
    result=[]
    seen=set()
    for row in rows:
        if not isinstance(row,dict):continue
        if row.get("trading_sessions") not in (None,"RTH"):
            continue
        try:
            stamp=_time(row["time"])
            close=positive(row["close"])
        except (KeyError,ValueError,TypeError,WebullError,OverflowError):
            continue
        epoch=int(stamp.timestamp()*1000)
        if epoch in seen:
            raise WebullSignalError("Duplicate Webull five-minute bar")
        seen.add(epoch)
        result.append({"datetime":epoch,"close":str(close)})
    result.sort(key=lambda x:x["datetime"])
    if len(result)>150:result=result[-150:]
    return result

def scan_shared_stock(broker,symbols,now=None):
    """Return per-symbol diagnostics and at most one Schwab-selected entry.

    Calls the actual, existing ranked_candidates/choose_entry used by Schwab,
    never a new approximation of the moving-average crossover.
    """
    now=now or datetime.now(timezone.utc)
    if not core_stock_session(now):
        return ([{"symbol":s,"asset":"EQUITY","source":SHARED_STOCK_SOURCE,
                  "technical_approved":False,
                  "reason":"Outside conservative US core stock session"}
                 for s in symbols],None)
    quoted={}
    spreads={}
    reasons={}
    for symbol in symbols:
        try:
            depth=broker.quote(symbol,"EQUITY")
            snapshot=broker.stock_snapshot(symbol)
            quoted[symbol],spreads[symbol]=_convert_quote(symbol,depth,snapshot,now)
        except Exception as exc:
            reasons[symbol]=_safe_data_reason(exc)
    ranked=ranked_candidates(quoted,now,universe=symbols)
    eligible={sym for _,sym,_,_ in ranked}
    for sym in symbols:
        if sym in quoted and sym not in eligible:
            reasons[sym]="SHARED_SCHWAB_PRICE_VOLUME_OR_SPREAD_GATE"
    candles={}
    for _,sym,_,_ in ranked:
        try:
            candles[sym]=_convert_bars(broker.bars(sym,"EQUITY",period="M5"),now)
        except Exception as exc:
            reasons[sym]=_safe_data_reason(exc)
    def lookup(sym):
        if sym not in candles:raise LiveBlocked("Webull M5 bars unavailable")
        return candles[sym]
    selected=choose_entry(ranked,lookup,now,can_buy=True)
    diagnostics=[]
    signal=None
    for sym in symbols:
        chosen=selected is not None and sym==selected.symbol
        if chosen:
            bid,ask=selected.bid,selected.ask
            source_at=quoted[sym]["quote"]["quoteTime"]
            signal={"symbol":sym,"asset":"EQUITY","source":SHARED_STOCK_SOURCE,
                    "at":now.isoformat(),"technical_approved":True,
                    "technical_exit":False,"ai_approved":False,
                    "bid":str(bid),"ask":str(ask),"mid":str((bid+ask)/2),
                    "spread_pct":round(spreads[sym],4),
                    "momentum_pct":0.0,
                    "bars":len(candles[sym]),"reason":selected.reason,
                    "shared_candle":selected.candle}
        diagnostics.append({"symbol":sym,"asset":"EQUITY","source":SHARED_STOCK_SOURCE,
            "technical_approved":chosen,
            "spread_pct":round(spreads[sym],4) if sym in spreads else None,
            "reason":(selected.reason if chosen else reasons.get(sym,
                      "SHARED_SCHWAB_NO_M5_ENTRY"))})
    return diagnostics,signal

def revalidate_shared_stock(broker,symbol,now=None):
    diag,signal=scan_shared_stock(broker,(symbol,),now)
    if signal is None:
        raise WebullSignalError("Shared stock crossover no longer valid")
    return signal
