"""Built-in, read-only NAS research.

No specialized model or AI computer is required. Uses actual dated daily bars,
bounded price/volume heuristics, and an OPTIONAL configured Ollama/OAuth provider
for qualitative headline review. The model never supplies prices, scores,
quantiles, account identifiers or orders.
"""
from __future__ import annotations
import csv,io,json,math,os,statistics,threading,time,tempfile
from concurrent.futures import ThreadPoolExecutor,as_completed
from datetime import datetime,timezone,timedelta
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request,urlopen
from urllib.error import HTTPError,URLError
from zoneinfo import ZoneInfo
from technical_indicators import calculate as calculate_indicators

SYMBOLS=("F","T","PFE","AAL","CCL","SOFI","SNAP","NU","WBD","NIO","NOK","VALE",
         "UAA","PLUG","RIG","LUMN","KGC","AG","CLF","BTG","BBD","HIMS","GOLD","ACHR")
NY=ZoneInfo("America/New_York")
LOCK=threading.Lock()
RUNNING=False
CACHE_SECONDS=4*3600
RETRY_SECONDS=600
BARS_TIMEOUT=7

class MarketHistoryUnavailable(ValueError):pass

def _valid_bar(day,c,v):
    if not (isinstance(day,str) and len(day)==10 and
            all(isinstance(x,(float,int)) and not isinstance(x,bool) and math.isfinite(x) for x in (c,v))):
        return None
    if not 0.01<c<100000 and v>=0:return None
    try:datetime.fromisoformat(day)
    except ValueError:return None
    return {"date":day,"close":float(c),"volume":float(v)}

def yahoo_rows(sym,opener=urlopen):
    url="https://query1.finance.yahoo.com/v8/finance/chart/"+quote(sym)+"?range=2y&interval=1d"
    req=Request(url,headers={"User-Agent":"Mozilla/5.0 (compatible; AutoTraderResearch/1.0)","Accept":"application/json"})
    with opener(req,timeout=BARS_TIMEOUT) as resp:
        raw=resp.read(700001)
    if len(raw)>700000:raise MarketHistoryUnavailable("Historical feed too large")
    doc=json.loads(raw)
    entry=(doc.get("chart",{}).get("result") or [None])[0]
    if not isinstance(entry,dict):raise MarketHistoryUnavailable("Historical series unavailable")
    quotes=entry.get("indicators",{}).get("quote",[])
    q=quotes[0] if quotes else {}
    timestamps=entry.get("timestamp",[])
    prices=q.get("close",[])
    volume=q.get("volume",[])
    result={}
    for stamp,close,vol in zip(timestamps,prices,volume):
        if stamp is None:continue
        day=datetime.fromtimestamp(stamp,timezone.utc).astimezone(NY).date().isoformat()
        row=_valid_bar(day,close,vol)
        if row:result[day]=row
    return sorted(result.values(),key=lambda x:x["date"]), "Yahoo Finance historical daily chart"

def stooq_rows(sym,opener=urlopen):
    url="https://stooq.com/q/d/l/?s="+quote(sym.lower()+".us")+"&i=d&d1="+(
       datetime.now(timezone.utc)-timedelta(days=730)).strftime("%Y%m%d")
    req=Request(url,headers={"User-Agent":"AutoTraderResearch/1.0"})
    with opener(req,timeout=BARS_TIMEOUT) as resp:
        raw=resp.read(300001)
    if len(raw)>300000:raise MarketHistoryUnavailable("Historical CSV too large")
    rows=[]
    for item in csv.DictReader(io.StringIO(raw.decode("utf-8"))):
        try:r=_valid_bar(item["Date"],float(item["Close"]),float(item["Volume"]))
        except (ValueError,TypeError,KeyError):r=None
        if r:rows.append(r)
    return sorted(rows,key=lambda x:x["date"]), "Stooq daily CSV"

def history(sym,fetchers=(yahoo_rows,stooq_rows)):
    for method in fetchers:
        try:
            rows,source=method(sym)
            if len(rows)>=100:return rows,source
        except (MarketHistoryUnavailable,HTTPError,URLError,TimeoutError,OSError,
                ValueError,KeyError,TypeError,UnicodeError):pass
    raise MarketHistoryUnavailable("No sufficiently complete historical feed")

def analyze(sym,rows,source,now=None):
    """Deterministic evidence, not a trained price predictor."""
    when=now or datetime.now(timezone.utc)
    if sym not in SYMBOLS or len(rows)<100: return None
    last=rows[-1]
    try: age=(when.astimezone(NY).date()-datetime.fromisoformat(last["date"]).date()).days
    except (ValueError,TypeError,KeyError):return None
    if age<0 or age>6:return None
    p=[x["close"] for x in rows]
    vol=[x["volume"] for x in rows]
    if not 5<=p[-1]<=25 or statistics.mean(vol[-20:])<200000:return None
    if any(x<=0 for x in p[-60:]):return None
    close=p[-1];sma5=statistics.mean(p[-5:]);sma20=statistics.mean(p[-20:]);sma50=statistics.mean(p[-50:])
    ret5=close/p[-6]-1;ret20=close/p[-21]-1
    returns=[math.log(p[i]/p[i-1]) for i in range(len(p)-20,len(p))]
    vol20=statistics.stdev(returns)
    relvolume=vol[-1]/max(statistics.mean(vol[-20:]),1)
    high=max(p[-11:-1]);low=min(p[-11:-1])
    # Deterministic, transparent bounded heuristic, NOT a probability.
    trend=(1 if close>sma20 else -1)+(1 if sma20>sma50 else -1)
    score=round(max(-100,min(100,100*(0.38*max(-0.2,min(0.2,ret20))+
              0.24*max(-0.1,min(0.1,ret5))+
              0.07*trend+0.04*max(-1,min(2,relvolume-1))-
              1.8*vol20))),4)
    # +/-1 historical daily sigma scenario is descriptive, NOT a model quantile.
    scenario=[round(close*math.exp(-vol20),4),round(close,4),
              round(close*math.exp(vol20),4)]
    unmet=[]
    if close<=sma20:unmet.append("Latest daily close not above 20-session moving average")
    if sma20<=sma50:unmet.append("20-session moving average not above 50-session trend")
    if relvolume<1:unmet.append("Latest volume below 20-session average")
    if age>=4:unmet.append("Historical data may be stale")
    if vol20>0.06:unmet.append("Recent daily volatility elevated")
    return {"ticker":sym,"as_of":last["date"],"reference_close":round(close,4),
       "historical_source":source,"ranking_score":score,
       "technical":{"above_sma20":close>sma20,
          "sma20":round(sma20,4),"sma50":round(sma50,4),
          "return_5d_pct":round(ret5*100,2),"return_20d_pct":round(ret20*100,2),
          "volatility_20d_pct":round(vol20*100,2),
          "relative_volume":round(relvolume,3),
          "advisory_indicators":calculate_indicators(rows)},
       "historical_volatility_scenario":{"close_range":scenario,
          "method":"Latest historical close +/- one observed 20-session daily log-return standard deviation",
          "calibrated_probability":None},
       "entry_scenario":{"reference_breakout":round(high,4),
           "risk_invalidation":round(low,4),
           "illustrative_2R_exit":round(high+2*max(high-low,0),4),
           "execution_authorized":False},
       "confirmation_unmet":unmet,
       "news":[],"ai_review":None}

def _save(path,data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix=".builtin-forecast-",dir=path.parent)
    try:
        with os.fdopen(fd,"w") as handle:
            os.fchmod(handle.fileno(),0o600)
            json.dump(data,handle,allow_nan=False)
            handle.flush();os.fsync(handle.fileno())
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)

def _load(path):
    try:
        p=Path(path)
        if p.stat().st_size>250000:raise ValueError()
        data=json.loads(p.read_text())
        if isinstance(data,dict) and data.get("engine")=="built_in":return data
    except (OSError,TypeError,ValueError):pass
    return None

def _review(candidate,config,secrets,reviewer):
    if not reviewer or config.get("ai_provider","none")=="none":
        candidate["ai_review_status"]="not_configured";return
    try:
        from ai_research import fetch_headlines
        news=fetch_headlines(candidate["ticker"],datetime.now(timezone.utc))
        candidate["news"]=news[:6]
        candidate["ai_review"]=reviewer(candidate["ticker"],news,config,secrets)
        candidate["ai_review_status"]="completed"
    except Exception:
        candidate["ai_review_status"]="unavailable"
    # A provider cannot alter historical measures, score or eligibility.

def build(now=None,fetcher=history,reviewer=None,config=None,secrets=None,
          universe=SYMBOLS):
    now=now or datetime.now(timezone.utc)
    eligible=[]
    errors={}
    def one(sym):
        rows,source=fetcher(sym)
        return analyze(sym,rows,source,now)
    with ThreadPoolExecutor(max_workers=6) as executor:
        jobs={executor.submit(one,sym):sym for sym in universe}
        for future in as_completed(jobs):
            sym=jobs[future]
            try:
                candidate=future.result()
                if candidate:eligible.append(candidate)
                else:errors[sym]="Not eligible, insufficient or stale daily data"
            except Exception:
                errors[sym]="Historical market data unavailable"
    eligible.sort(key=lambda x:(-x["ranking_score"],x["ticker"]))
    chosen=eligible[:5]
    if reviewer and config and config.get("ai_provider") not in (None,"none"):
        # Limit provider calls; separate budget from the market-data fetch.
        for candidate in chosen[:3]:_review(candidate,config,secrets or {},reviewer)
        for candidate in chosen[3:]:candidate["ai_review_status"]="not_requested"
    else:
        for candidate in chosen:candidate["ai_review_status"]="not_configured"
    return {"engine":"built_in","version":1,"mode":"research_only",
       "generated_at":now.isoformat(),"target_session_open":None,
       "next_session_label":"Next regular session; check exchange calendar",
       "ranking_method":"Transparent technical momentum / volatility / liquidity heuristic, NOT a calibrated predictive model",
       "universe_size":len(universe),"symbols_with_data":len(eligible),
       "data_failures":errors,"candidates":chosen,
       "models":{"technical":"built_in","specialized":"not_required",
                 "ai_provider":(config or {}).get("ai_provider","none")},
       "lightgbm_validation":None,"model_calibration":None,
       "research_only":True,"live_order_integration":False,
       "note":"No calibrated price or profit probabilities. AI comments use public dated headlines only."}

def status(state,max_age=CACHE_SECONDS):
    data=_load(Path(state)/"built_in_forecast.json")
    if not data:return {"status":"pending","message":"Building first NAS-native market analysis"}
    try:age=(datetime.now(timezone.utc)-datetime.fromisoformat(data["generated_at"])).total_seconds()
    except (KeyError,ValueError,TypeError):age=10**9
    data["snapshot_age_seconds"]=max(0,round(age))
    data["snapshot_stale"]=age>max_age
    return data

def refresh(state,config,secrets,reviewer=None):
    global RUNNING
    path=Path(state)/"built_in_forecast.json"
    try:
        doc=build(config=config,secrets=secrets,reviewer=reviewer)
        if doc["symbols_with_data"]>0:_save(path,doc)
        else:
            previous=_load(path)
            if previous is None:_save(path,doc)
    finally:
        with LOCK:RUNNING=False

def get(state,config,secrets,reviewer=None):
    global RUNNING
    path=Path(state)/"built_in_forecast.json"
    current=status(state)
    stale=(current.get("snapshot_stale") or current.get("status")=="pending")
    with LOCK:
        if stale and not RUNNING:
            RUNNING=True
            worker=threading.Thread(target=refresh,args=(state,config,secrets,reviewer),daemon=True)
            worker.start()
    return current
