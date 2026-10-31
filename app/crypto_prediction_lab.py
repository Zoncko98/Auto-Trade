"""Isolated crypto forward-prediction evaluator. Never imports a broker or places orders.

Only explicit predictions, recorded before outcomes, are eligible for scoring.
Paper P/L is hypothetical and never changes live account balances.
"""
from __future__ import annotations
import argparse
import json
import math
import os
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.request import Request, urlopen

PAIRS={"BTC/USD":"XBTUSD","ETH/USD":"ETHUSD"}
HORIZONS={1,4,24}
FEE_BPS=20
SLIPPAGE_BPS=10

def _utc(value):
    stamp=datetime.fromisoformat(value.replace("Z","+00:00"))
    if stamp.tzinfo is None:raise ValueError("Timezone required")
    return stamp.astimezone(timezone.utc)

def candles(pair, opener=urlopen):
    """Public Kraken OHLC, one-hour bars; discard newest, potentially incomplete bar."""
    if pair not in PAIRS:raise ValueError("Unsupported pair")
    req=Request("https://api.kraken.com/0/public/OHLC?pair="+PAIRS[pair]+"&interval=60",
                headers={"User-Agent":"AutoTraderCryptoResearch/1.1"})
    with opener(req,timeout=12) as response:body=response.read(350001)
    if len(body)>350000:raise ValueError("Oversize market response")
    doc=json.loads(body)
    if doc.get("error"):raise ValueError("Exchange feed error")
    data=doc.get("result",{})
    key=next((k for k in data if k!="last"),None)
    if not key or not isinstance(data[key],list):raise ValueError("Missing OHLC data")
    result=[]
    for row in data[key][:-1]:
        if len(row)<7:continue
        t=int(row[0]);close=float(row[4])
        if t>0 and math.isfinite(close) and close>0:
            result.append({"timestamp":datetime.fromtimestamp(t,timezone.utc).isoformat(),"close":close})
    result=sorted({x["timestamp"]:x for x in result}.values(),key=lambda x:x["timestamp"])
    if len(result)<26:raise ValueError("Insufficient historical observations")
    return result

def _write(path, records):
    path=Path(path);path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    fd,name=tempfile.mkstemp(dir=path.parent,prefix=".crypto-audit-")
    try:
        with os.fdopen(fd,"w") as stream:
            os.fchmod(stream.fileno(),0o600)
            json.dump(records,stream,indent=2,allow_nan=False)
            stream.flush();os.fsync(stream.fileno())
        os.replace(name,path)
    finally:
        if os.path.exists(name):os.unlink(name)

def load(path):
    try:
        path=Path(path)
        if path.stat().st_size>2000000:raise ValueError("Audit too large")
        data=json.loads(path.read_text())
        if not isinstance(data,list):raise ValueError("Invalid audit")
        return data
    except FileNotFoundError:return []

def record(path, pair, horizon_hours, direction, observed_at, reference_close,
           evidence, source="external_ai", now=None):
    """Lock a new forecast before the future observation is available."""
    now=(now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    seen=_utc(observed_at)
    if pair not in PAIRS or horizon_hours not in HORIZONS:raise ValueError("Invalid market/horizon")
    if direction not in ("UP","DOWN","FLAT"):raise ValueError("Invalid direction")
    if source not in ("external_ai","local_ai","baseline"):raise ValueError("Invalid source")
    if seen>now or now-seen>timedelta(hours=2):raise ValueError("Stale or future observation")
    if not isinstance(reference_close,(int,float)) or not math.isfinite(reference_close) or reference_close<=0:
        raise ValueError("Invalid reference")
    if not isinstance(evidence,str) or not 1<=len(evidence)<=400:raise ValueError("Reason required")
    rows=load(path)
    identifier=f"{pair}:{horizon_hours}:{seen.isoformat()}:{source}"
    if any(x.get("id")==identifier for x in rows):raise ValueError("Duplicate forecast")
    row={"id":identifier,"pair":pair,"horizon_hours":horizon_hours,"direction":direction,
         "observed_at":seen.isoformat(),"recorded_at":now.isoformat(),"reference_close":reference_close,
         "source":source,"evidence":evidence,"outcome":None}
    rows.append(row);_write(path,rows)
    return row

def resolve(path, observed_bars, now=None):
    """Score future bars only after horizon closes, preserving original predictions."""
    now=(now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    rows=load(path)
    bar_map={}
    for pair,bars in observed_bars.items():
        if pair not in PAIRS:continue
        bar_map[pair]=sorted([(_utc(b["timestamp"]),float(b["close"])) for b in bars],
                             key=lambda x:x[0])
    changed=0
    for row in rows:
        if row.get("outcome") is not None:continue
        due=_utc(row["observed_at"])+timedelta(hours=row["horizon_hours"])
        if now<due+timedelta(hours=1):continue
        eligible=[(at,price) for at,price in bar_map.get(row["pair"],[])
                  if due<=at<=due+timedelta(hours=2) and at+timedelta(hours=1)<=now
                  and math.isfinite(price) and price>0]
        if not eligible:continue
        at,price=eligible[0]
        change=(price/row["reference_close"]-1)
        correct=(change>0 and row["direction"]=="UP") or (change<0 and row["direction"]=="DOWN") or (change==0 and row["direction"]=="FLAT")
        direction=row["direction"]
        gross=change if direction=="UP" else -change if direction=="DOWN" else 0
        # Illustrative round-trip paper trade with $100 notional. No actual orders.
        net=100*(gross-2*(FEE_BPS+SLIPPAGE_BPS)/10000) if direction!="FLAT" else 0
        row["outcome"]={"closed_at":at.isoformat(),"close":price,
                       "actual_return_pct":round(change*100,5),"direction_correct":correct,
                       "hypothetical_net_usd":round(net,4),"notional_usd":100,
                       "round_trip_fee_and_slippage_bps":2*(FEE_BPS+SLIPPAGE_BPS)}
        changed+=1
    if changed:_write(path,rows)
    return changed

def summary(path):
    rows=load(path);settled=[r for r in rows if r.get("outcome") is not None]
    return {"predictions":len(rows),"settled":len(settled),
            "accuracy":round(sum(r["outcome"]["direction_correct"] for r in settled)/len(settled),4) if settled else None,
            "hypothetical_net_usd":round(sum(r["outcome"]["hypothetical_net_usd"] for r in settled),4),
            "live_trades":0,"paper_is_fallback":False}

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("action",choices=("summary","settle"))
    parser.add_argument("--file",default=os.environ.get("CRYPTO_LAB_FILE","/state/crypto-research/predictions.json"))
    args=parser.parse_args()
    if args.action=="settle":
        bars={pair:candles(pair) for pair in PAIRS}
        print(json.dumps({"settled_new":resolve(args.file,bars)}))
    print(json.dumps(summary(args.file),indent=2))
