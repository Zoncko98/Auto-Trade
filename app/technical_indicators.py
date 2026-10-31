"""Deterministic advisory indicators from complete historical daily bars.

This module has no execution or position-sizing authority.
"""
from __future__ import annotations
import math
import statistics

def _ema(values, period):
    seed=sum(values[:period])/period
    alpha=2/(period+1)
    out=[None]*(period-1)+[seed]
    for value in values[period:]:
        out.append(alpha*value+(1-alpha)*out[-1])
    return out

def calculate(rows):
    """Use positive closing prices and nonnegative volumes; return JSON-safe values."""
    if len(rows)<60:
        raise ValueError("At least 60 bars required")
    close=[float(row["close"]) for row in rows]
    volume=[float(row["volume"]) for row in rows]
    if any(not math.isfinite(v) or v<=0 for v in close) or any(
        not math.isfinite(v) or v<0 for v in volume):
        raise ValueError("Invalid market bar")
    diffs=[close[i]-close[i-1] for i in range(1,len(close))]
    gains=[max(v,0) for v in diffs]
    losses=[max(-v,0) for v in diffs]
    avg_gain=sum(gains[:14])/14
    avg_loss=sum(losses[:14])/14
    for gain,loss in zip(gains[14:],losses[14:]):
        avg_gain=(avg_gain*13+gain)/14
        avg_loss=(avg_loss*13+loss)/14
    rsi=100 if avg_loss==0 and avg_gain>0 else 50 if avg_loss==avg_gain==0 else 100-100/(1+avg_gain/avg_loss)
    fast=_ema(close,12)
    slow=_ema(close,26)
    macd=[a-b for a,b in zip(fast[25:],slow[25:])]
    signal=_ema(macd,9)[-1]
    tr=[abs(v) for v in diffs]
    atr=sum(tr[:14])/14
    for value in tr[14:]:
        atr=(atr*13+value)/14
    relative=volume[-1]/max(statistics.mean(volume[-21:-1]),1)
    volatility=statistics.stdev([math.log(close[i]/close[i-1]) for i in range(len(close)-20,len(close))])
    trend=(close[-1]-statistics.mean(close[-20:]))/statistics.mean(close[-20:])
    regime="volatile" if volatility>=0.04 else "trending" if abs(trend)>=0.03 else "ranging"
    return {"rsi14":round(rsi,3),"macd_12_26":round(macd[-1],5),
        "macd_signal9":round(signal,5),"macd_histogram":round(macd[-1]-signal,5),
        "atr14_close_only_proxy":round(atr,5),
        "relative_volume_vs_previous_20":round(relative,3),
        "market_regime_proxy":regime,
        "regime_scope":"Symbol-only daily price history; not a broad-market index regime",
        "advisory_only":True}
