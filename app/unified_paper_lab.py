import json,math,threading
from datetime import datetime,timezone,timedelta
from urllib.request import Request,urlopen
from crypto_prediction_lab import candles,load,_write,_utc
from crypto_ai_agent import infer
ASSETS={"BTC/USD":"crypto","ETH/USD":"crypto","SPY":"equity","QQQ":"equity","AAPL":"equity","MSFT":"equity"}
lock=threading.RLock()
def stock_bars(symbol,opener=urlopen):
    if ASSETS.get(symbol)!="equity":raise ValueError("Unsupported market")
    req=Request("https://query1.finance.yahoo.com/v8/finance/chart/"+symbol+"?interval=1h&range=1mo",headers={"User-Agent":"Mozilla/5.0"})
    with opener(req,timeout=12) as resp:raw=resp.read(350001)
    if len(raw)>350000:raise ValueError("Oversized market data")
    data=json.loads(raw)["chart"]["result"][0]
    now=datetime.now(timezone.utc)
    rows=[{"timestamp":datetime.fromtimestamp(t,timezone.utc).isoformat(),"close":float(v)}
        for t,v in zip(data["timestamp"],data["indicators"]["quote"][0]["close"])
        if v is not None and math.isfinite(float(v)) and v>0
        and datetime.fromtimestamp(t,timezone.utc)+timedelta(hours=1)<=now]
    if len(rows)<26:raise ValueError("Insufficient data")
    return rows
def fetch(symbol):return candles(symbol) if ASSETS[symbol]=="crypto" else stock_bars(symbol)
def report(path):
    with lock:rows=load(path)
    accounts={}
    for market in ("equity","crypto"):
        records=[r for r in rows if r["market"]==market]
        completed=[r for r in records if r.get("outcome")]
        pnl=sum(r["outcome"]["net"] for r in completed)
        accounts[market]={"predictions":len(records),"settled":len(completed),
            "accuracy":round(sum(r["outcome"]["correct"] for r in completed)/len(completed),4) if completed else None,
            "paper_net":round(pnl,4),"virtual_equity":round(100+pnl,4)}
    return {"accounts":accounts,"records":rows[-50:][::-1],"paper_only":True}
def cycle(path,get_bars=fetch,predict=infer,now=None):
    now=now or datetime.now(timezone.utc)
    with lock:
        records=load(path);observed={};errors={};added=[]
        for symbol in ASSETS:
            try:
                bars=get_bars(symbol)
                if len(bars)<26:raise ValueError("Insufficient bars")
                t=_utc(bars[-1]["timestamp"])
                if t+timedelta(hours=1)>now or now-t>timedelta(hours=72):raise ValueError("Stale candle")
                observed[symbol]=bars
            except Exception:errors[symbol]="Market feed unavailable"
        settled=0
        for r in records:
            if r.get("outcome"):continue
            due=_utc(r["observed_at"])+timedelta(hours=r["hours"])
            future=[x for x in observed.get(r["symbol"],[]) if _utc(x["timestamp"])>=due and _utc(x["timestamp"])+timedelta(hours=1)<=now]
            if not future:continue
            price=future[0]["close"];delta=price/r["price"]-1
            correct=delta>0 if r["direction"]=="UP" else delta<0 if r["direction"]=="DOWN" else abs(delta)<0.001
            cost=0.006 if r["market"]=="crypto" else 0.002
            net=100*(delta-cost) if r["direction"]=="UP" else 0
            r["outcome"]={"at":future[0]["timestamp"],"correct":correct,"net":round(net,4),"change_pct":round(delta*100,4)}
            settled+=1
        for symbol,bars in observed.items():
            timestamp=bars[-1]["timestamp"]
            if any(r["symbol"]==symbol and r["observed_at"]==timestamp for r in records):continue
            try:
                result,source=predict(symbol,bars)
                if result["direction"] not in ("UP","DOWN","FLAT") or result["horizon_hours"] not in (1,4,24):raise ValueError
                records.append({"symbol":symbol,"market":ASSETS[symbol],"observed_at":timestamp,
                    "recorded_at":now.isoformat(),"price":bars[-1]["close"],"direction":result["direction"],
                    "hours":result["horizon_hours"],"reason":result["reason"][:400],"source":source,"outcome":None})
                added.append(symbol)
            except Exception:errors[symbol]="AI unavailable or invalid"
        if added or settled:_write(path,records)
        return {"added":added,"settled":settled,"errors":errors,"report":report(path)}
