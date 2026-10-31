"""Research-only forecasting service. All computation stays on the Windows AI host.
No Schwab credentials, trading privileges, or order endpoints. Estimates are NOT calibrated probabilities.
"""
from __future__ import annotations
import json, math, os, pathlib, statistics, threading, time, traceback
from datetime import datetime, timedelta, timezone, time as clocktime
from urllib.parse import quote
from urllib.request import Request, urlopen
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from zoneinfo import ZoneInfo
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

ROOT=pathlib.Path(os.environ.get("AUTOTRADER_AI_HOME",str(pathlib.Path(__file__).resolve().parent)))
os.environ["HF_HOME"]=str(ROOT/"cache"/"huggingface")
os.environ["HF_HUB_DISABLE_TELEMETRY"]="1"
os.environ["TOKENIZERS_PARALLELISM"]="false"
STATE=ROOT/"state"
STATE.mkdir(parents=True,exist_ok=True)
CACHE=STATE/"forecast.json"
NY=ZoneInfo("America/New_York")
SYMBOLS=("F","T","PFE","AAL","CCL","SOFI","SNAP","NU","WBD","NIO","NOK","VALE","UAA","PLUG","RIG","LUMN","KGC","AG","CLF","BTG","BBD","HIMS","GOLD","ACHR")
COMPANIES={"F":"Ford Motor Company","T":"AT&T","PFE":"Pfizer","AAL":"American Airlines","CCL":"Carnival Corporation","SOFI":"SoFi Technologies","SNAP":"Snap","NU":"Nu Holdings","WBD":"Warner Bros Discovery","NIO":"NIO","NOK":"Nokia","VALE":"Vale","UAA":"Under Armour","PLUG":"Plug Power","RIG":"Transocean","LUMN":"Lumen Technologies","KGC":"Kinross Gold","AG":"First Majestic Silver","CLF":"Cleveland-Cliffs","BTG":"B2Gold","BBD":"Banco Bradesco","HIMS":"Hims & Hers Health","GOLD":"Barrick Mining","ACHR":"Archer Aviation"}
HEADERS={"User-Agent":"Mozilla/5.0 (compatible; AutoTraderResearch/1.0)","Accept":"application/json, text/xml, */*"}
status={"phase":"starting","last_error":None,"last_refresh":None}
mutex=threading.Lock()
_models={}
_last_key=None

def request(url, limit=500000, timeout=12):
    with urlopen(Request(url,headers=HEADERS),timeout=timeout) as r:
        data=r.read(limit+1)
    if len(data)>limit: raise ValueError("Response size exceeded")
    return data

def history(symbol):
    url="https://query1.finance.yahoo.com/v8/finance/chart/"+quote(symbol)+"?range=2y&interval=1d"
    raw=json.loads(request(url,1600000))
    item=(raw.get("chart",{}).get("result") or [None])[0]
    if not item:raise ValueError("Price history missing")
    q=item["indicators"]["quote"][0]
    rows=[]
    for ts,cl,hi,lo,vol in zip(item["timestamp"],q["close"],q["high"],q["low"],q["volume"]):
        if any(v is None for v in (cl,hi,lo,vol)):continue
        if cl<=0 or hi<=0 or lo<=0 or vol<0:continue
        at=datetime.fromtimestamp(ts,timezone.utc).astimezone(NY).date()
        rows.append({"date":at.isoformat(),"close":float(cl),"high":float(hi),"low":float(lo),"volume":float(vol)})
    if len(rows)<180:raise ValueError("Insufficient history")
    return rows, url

def indicators(rows, i):
    import numpy as np
    if i<65:return None
    c=np.asarray([r["close"] for r in rows[:i+1]],dtype=float)
    v=np.asarray([r["volume"] for r in rows[:i+1]],dtype=float)
    ret=np.diff(np.log(c))
    if len(ret)<50 or np.any(~np.isfinite(ret)):return None
    m5=c[-5:].mean();m20=c[-20:].mean();m50=c[-50:].mean()
    vol20=max(v[-20:].mean(),1.0)
    return [float(ret[-1]),float(sum(ret[-3:])),float(sum(ret[-5:])),
            float(c[-1]/m5-1),float(c[-1]/m20-1),float(m20/m50-1),
            float(np.std(ret[-10:])),float(np.std(ret[-30:])),
            float(math.log1p(v[-1])/math.log1p(vol20)-1),
            float(c[-1]/max(c[-20:].max(),1e-9)-1)]

def compute_lgbm(series):
    import numpy as np
    import lightgbm as lgb
    X=[];y=[];dated=[];recent={}
    for sym,rows in series.items():
        for i in range(65,len(rows)-1):
            features=indicators(rows,i)
            if features is None:continue
            X.append(features)
            y.append(math.log(rows[i+1]["close"]/rows[i]["close"]))
            dated.append(rows[i+1]["date"])
        recent[sym]=indicators(rows,len(rows)-1)
    if len(X)<400:raise ValueError("Training history too short")
    X=np.asarray(X);y=np.asarray(y); dated=np.asarray(dated)
    unique_dates=sorted(set(dated))
    if len(unique_dates)<65:raise ValueError("Too few independent observation dates")
    cutoff=unique_dates[-31]
    train=dated<cutoff
    validate=dated>=cutoff
    if train.sum()<300 or validate.sum()<35:raise ValueError("Insufficient chronological holdout")
    kwargs={"n_estimators":110,"max_depth":3,"num_leaves":9,"learning_rate":0.035,
            "min_child_samples":60,"reg_lambda":5.0,"n_jobs":2,"verbosity":-1,"random_state":42}
    m=lgb.LGBMRegressor(**kwargs)
    m.fit(X[train],y[train])
    pred=m.predict(X[validate]);truth=y[validate]
    mae=float(np.mean(np.abs(pred-truth)))
    baseline=float(np.mean(np.abs(truth)))
    valid=bool(mae<baseline)
    final=lgb.LGBMRegressor(**kwargs)
    final.fit(X,y)
    forecasts={sym:float(final.predict([features])[0]) for sym,features in recent.items() if features is not None}
    return forecasts,{"holdout_rows":int(validate.sum()),"holdout_start":cutoff,
                      "mae_log_return":round(mae,6),"zero_return_baseline_mae":round(baseline,6),
                      "beats_zero_return_baseline":valid,"status":"experimental" if valid else "unvalidated"}

def chronos_for(rows):
    import torch
    from chronos import BaseChronosPipeline
    if "chronos" not in _models:
        _models["chronos"]=BaseChronosPipeline.from_pretrained(
            "amazon/chronos-bolt-tiny",device_map="cpu",torch_dtype=torch.float32)
    values=[math.log(rows[i]["close"]/rows[i-1]["close"]) for i in range(1,len(rows))]
    values=values[-256:]
    with torch.inference_mode():
        result=_models["chronos"].predict(torch.tensor(values,dtype=torch.float32),prediction_length=1)
    q=result.detach().cpu().numpy().reshape(-1).tolist()
    if len(q)<3:raise ValueError("Chronos returned insufficient quantiles")
    lo,mid,hi=float(q[0]),float(q[len(q)//2]),float(q[-1])
    return [lo,mid,hi]

def finbert_for(titles):
    if not titles:return {"label":"unknown","scores":{},"headlines":0}
    if "finbert" not in _models:
        from transformers import pipeline
        _models["finbert"]=pipeline("text-classification",model="ProsusAI/finbert",device=-1)
    results=_models["finbert"](titles[:6],truncation=True,max_length=256,top_k=None)
    positive=negative=neutral=0.0
    for result in results:
        scores={r["label"].lower():r["score"] for r in result}
        positive+=scores.get("positive",0)
        negative+=scores.get("negative",0)
        neutral+=scores.get("neutral",0)
    n=len(results)
    scores={"positive":round(positive/n,4),"negative":round(negative/n,4),"neutral":round(neutral/n,4)}
    return {"label":max(scores,key=scores.get),"scores":scores,"headlines":n}

def news_for(symbol):
    term=COMPANIES.get(symbol,symbol)+" stock when:4d"
    url="https://news.google.com/rss/search?q="+quote(term)+"&hl=en-US&gl=US&ceid=US%3Aen"
    try:
        root=ET.fromstring(request(url,150000,timeout=10))
        news=[]
        cutoff=datetime.now(timezone.utc)-timedelta(days=4)
        for x in root.findall("./channel/item"):
            title=(x.findtext("title") or "").strip()[:200]
            source=(x.findtext("source") or "").strip()[:80]
            link=(x.findtext("link") or "").strip()
            try:date=parsedate_to_datetime(x.findtext("pubDate")).astimezone(timezone.utc)
            except (TypeError,ValueError,AttributeError):continue
            if title and source and link.startswith("https://news.google.com/") and cutoff<=date<=datetime.now(timezone.utc):
                news.append({"title":title,"source":source,"published_at":date.isoformat(),"url":link[:550]})
            if len(news)>=6:break
        return news
    except Exception:return []

def next_session(now):
    # Exchange schedule handles weekends and US stock-market holidays.
    import pandas_market_calendars as mcal
    cal=mcal.get_calendar("NYSE")
    schedule=cal.schedule(start_date=now.date().isoformat(),end_date=(now+timedelta(days=14)).date().isoformat())
    for _,row in schedule.iterrows():
        opens=row["market_open"].to_pydatetime().astimezone(timezone.utc)
        if opens>now.astimezone(timezone.utc):
            return opens.astimezone(NY).isoformat()
    raise ValueError("No upcoming market session")

def rank_candidate(sym,rows,price_url,estimate,validation):
    # No actual bid/ask, spread or tradable limit price is assumed.
    last=rows[-1];cls=last["close"]
    ret=estimate
    vol=statistics.stdev([math.log(rows[i]["close"]/rows[i-1]["close"]) for i in range(len(rows)-19,len(rows))])
    condition=cls>sum(x["close"] for x in rows[-20:])/20
    # An unvalidated LightGBM prediction must never drive candidate rankings.
    sma20=sum(x["close"] for x in rows[-20:])/20
    score=(ret/max(vol,0.001) if validation["beats_zero_return_baseline"] else (cls/sma20-1)/max(vol,0.001))+(0.08 if condition else -0.08)
    return {"ticker":sym,"as_of":last["date"],"reference_close":round(cls,4),
            "market_data":{"source":"Yahoo Finance historical chart","url":"https://finance.yahoo.com/quote/"+sym+"/history/",
                           "api_url":price_url,"latest_bar":last,
                           "last_20d_average_volume":round(sum(x["volume"] for x in rows[-20:])/20)},
            "lightgbm":{"expected_log_return":round(ret,6),"status":validation["status"]},
            "ranking_score":round(score,5),"technical":{"above_sma20":condition,
                 "prior_session_high":round(last["high"],4),"prior_session_low":round(last["low"],4)},
            "confirmation_unmet":["Fresh next-session bid/ask spread not verified",
                                 "Next-session opening liquidity not verified",
                                 "Three-of-five-bar upward crossover not confirmed",
                                 "No live broker order checks performed"]}

def refresh():
    global _last_key
    if not mutex.acquire(blocking=False):return
    try:
        status.update(phase="retrieving_data",last_error=None)
        now=datetime.now(timezone.utc)
        series={};sources={};errors={}
        for symbol in SYMBOLS:
            try:
                rows,src=history(symbol)
                if (now.astimezone(NY).date()-datetime.fromisoformat(rows[-1]["date"]).date()).days>5:
                    raise ValueError("Historical bars stale")
                if not 5.0<=rows[-1]["close"]<=25.0:
                    raise ValueError("Outside live-trader share-price guardrail ($5-$25)")
                if sum(x["volume"] for x in rows[-20:])/20 < 200000:
                    raise ValueError("Average volume below 200,000")
                series[symbol]=rows;sources[symbol]=src
            except Exception as ex:errors[symbol]=str(ex)[:90]
        if len(series)<5:raise ValueError("Fewer than five current market-data series")
        status["phase"]="lightgbm"
        predictions,validation=compute_lgbm(series)
        ranked=[rank_candidate(sym,series[sym],sources[sym],predictions[sym],validation)
                for sym in predictions]
        ranked.sort(key=lambda x:(-x["ranking_score"],x["ticker"]))
        chosen=ranked[:5]
        status["phase"]="chronos_finbert"
        for candidate in chosen:
            sym=candidate["ticker"];ref=candidate["reference_close"]
            try:
                lo,mid,hi=chronos_for(series[sym])
                candidate["chronos_bolt"]={"model":"amazon/chronos-bolt-tiny","log_return_quantiles":[round(lo,6),round(mid,6),round(hi,6)],
                    "scenario_close_range":[round(ref*math.exp(lo),4),round(ref*math.exp(mid),4),round(ref*math.exp(hi),4)],
                    "note":"Uncalibrated experimental model quantiles, not expected executable prices"}
            except Exception as ex:candidate["chronos_bolt"]={"error":str(ex)[:140]}
            news=news_for(sym);candidate["news"]=news
            try:candidate["finbert"]=finbert_for([n["title"] for n in news])
            except Exception as ex:candidate["finbert"]={"error":str(ex)[:140]}
            if not news:candidate["confirmation_unmet"].append("Recent source-linked news not verified")
            if candidate["lightgbm"]["status"]=="unvalidated":
                candidate["confirmation_unmet"].append("LightGBM did not beat zero-return holdout baseline")
            # Scenario planning only; no market order or brokerage instructions.
            entry=candidate["technical"]["prior_session_high"]
            stop=candidate["technical"]["prior_session_low"]
            candidate["entry_scenario"]={"trigger":"Observe a live break above the prior session high with acceptable spread and volume",
                 "reference_breakout":entry,"risk_invalidation":stop,
                 "illustrative_2R_exit":round(entry+2*max(entry-stop,0),4),
                 "note":"Illustrative planning levels only; no bid/ask, slippage or executable order confirmed",
                 "execution_authorized":False}
        result={"version":1,"generated_at":now.isoformat(),
                "target_session_open":next_session(now),"research_only":True,
                "live_order_integration":False,
                "ranking_method":("Validated LightGBM + risk-normalized trend" if validation["beats_zero_return_baseline"] else "Rule-based 20-session trend / volatility; LightGBM unvalidated and excluded from rank")+"; Chronos and sentiment shown separately",
                "universe_size":len(SYMBOLS),"symbols_with_data":len(series),
                "models":{"ollama":"http://127.0.0.1:11434","lightgbm":"4.7.0",
                          "chronos":"amazon/chronos-bolt-tiny","finbert":"ProsusAI/finbert"},
                "lightgbm_validation":validation,
                "data_failures":errors,"candidates":chosen}
        tmp=CACHE.with_suffix(".tmp")
        tmp.write_text(json.dumps(result,indent=2,allow_nan=False),encoding="utf-8")
        tmp.replace(CACHE)
        status.update(phase="ready",last_refresh=datetime.now(timezone.utc).isoformat())
    except Exception as exc:
        status.update(phase="error",last_error=type(exc).__name__+": "+str(exc)[:180])
        traceback.print_exc()
    finally:mutex.release()

def read_cache():
    if CACHE.is_file():
        try:return json.loads(CACHE.read_text(encoding="utf-8"))
        except (OSError,ValueError):pass
    return {"status":"pending","message":"No completed forecast yet"}

def scheduled():
    # Execute the first refresh and then after 16:20 ET on trading weekdays;
    # on Mondays, refresh at/after 08:45 ET before the NYSE opening bell.
    refresh()
    completed=set()
    while True:
        try:
            now=datetime.now(NY)
            if now.weekday()<5:
                slot="close" if now.time()>=clocktime(16,20) else "monday" if now.weekday()==0 and now.time()>=clocktime(8,45) else None
                if slot:
                    key=now.date().isoformat()+":"+slot
                    if key not in completed and (slot!="monday" or now.time()<clocktime(9,30)):
                        completed.add(key);refresh()
            if len(completed)>30:completed=set(sorted(completed)[-15:])
        except Exception as exc:status["last_error"]=str(exc)[:180]
        time.sleep(60)

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def response(self,obj,code=200):
        data=json.dumps(obj,allow_nan=False).encode()
        self.send_response(code)
        self.send_header("Content-Type","application/json; charset=utf-8")
        self.send_header("Cache-Control","no-store")
        self.send_header("X-Content-Type-Options","nosniff")
        self.send_header("Content-Length",str(len(data)))
        self.end_headers();self.wfile.write(data)
    def do_GET(self):
        route=self.path.split("?")[0]
        if route=="/health":
            return self.response({"status":status.copy(),"version":1,"mode":"research_only"})
        if route=="/api/models":
            try:
                raw=json.loads(request("http://127.0.0.1:11434/api/tags",80000,timeout=4))
                ollama=[x.get("name") for x in raw.get("models",[]) if isinstance(x,dict)]
            except Exception:ollama=[]
            return self.response({"ollama":ollama,"lightgbm":"installed","chronos_bolt":"installed","finbert":"installed"})
        if route=="/api/forecast":return self.response(read_cache())
        return self.response({"error":"Unknown read-only route"},404)
    def do_POST(self):
        if self.path=="/api/refresh" and self.client_address[0] in ("127.0.0.1","::1"):
            threading.Thread(target=refresh,daemon=True).start()
            return self.response({"queued":True,"mode":"research_only"},202)
        return self.response({"error":"Refresh allowed only from this computer"},403)

if __name__=="__main__":
    print("AutoTraderAI starting read-only service",os.getenv("AUTOTRADER_AI_BIND","127.0.0.1"),os.getenv("AUTOTRADER_AI_PORT","8766"),flush=True)
    threading.Thread(target=scheduled,daemon=True).start()
    ThreadingHTTPServer((os.getenv("AUTOTRADER_AI_BIND","127.0.0.1"),int(os.getenv("AUTOTRADER_AI_PORT","8766"))),Handler).serve_forever()