"""Read-only Schwab quote collector for on-premises forecast monitoring.

This process only calls Schwab quote endpoints; it has NO order submission
logic, no discretionary trading decisions and no account data exports.
It writes sanitized, timestamped quotes to a shared volume used by dashboard.
Requires separately user-authorized Schwab OAuth token. Polling does not promise
real-time streaming or exchange entitlements.
"""
import json,math,os,re,tempfile,time
from datetime import datetime,timezone
from pathlib import Path

SYMBOLS=("F","T","PFE","AAL","CCL","SOFI","SNAP","NU","WBD","NIO","NOK","VALE","UAA",
         "PLUG","RIG","LUMN","KGC","AG","CLF","BTG","BBD","HIMS","GOLD","ACHR")
FILENAME="broker_market_snapshot.json"
class MarketDataUnavailable(RuntimeError):pass

def normalized_quotes(payload,requested=SYMBOLS,now=None):
    if not isinstance(payload,dict):raise MarketDataUnavailable("Broker response not a mapping")
    current=now or datetime.now(timezone.utc)
    stocks={}
    for symbol in requested:
        if not re.fullmatch(r"[A-Z]{1,8}",symbol):continue
        quote=payload.get(symbol)
        if not isinstance(quote,dict):continue
        record=quote.get("quote",{})
        if not isinstance(record,dict):continue
        values={}
        for raw,label in (("bidPrice","bid"),("askPrice","ask"),("lastPrice","last"),
                          ("totalVolume","volume"),("mark","mark")):
            value=record.get(raw)
            if isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(float(value)) and value>=0:
                values[label]=float(value)
        if not values:continue
        if values.get("bid",0)>0 and values.get("ask",0)>0 and values["bid"]>values["ask"]:
            continue
        ts=record.get("quoteTime") or quote.get("quoteTime")
        if isinstance(ts,(int,float)) and ts>1_000_000_000_000:
            values["quote_timestamp"]=datetime.fromtimestamp(ts/1000,timezone.utc).isoformat()
        else:
            values["quote_timestamp"]=None
        values["tradable"]=bool(quote.get("isTradable",False))
        stocks[symbol]=values
    return {"schema":1,"source":"schwab_broker_quotes","observed_at":current.isoformat(),
            "symbols":stocks,"realtime_entitlement_unverified":True}

def write_snapshot(state_path,payload):
    root=Path(state_path)
    root.mkdir(parents=True,exist_ok=True)
    content=json.dumps(payload,allow_nan=False,sort_keys=True).encode("utf-8")
    if len(content)>30000:raise MarketDataUnavailable("Snapshot too large")
    fd,path=tempfile.mkstemp(prefix=".broker-quotes-",dir=root)
    try:
        with os.fdopen(fd,"wb") as f:
            os.fchmod(f.fileno(),0o600);f.write(content);f.flush();os.fsync(f.fileno())
        os.replace(path,root/FILENAME)
        os.chmod(root/FILENAME,0o600)
    finally:
        if os.path.exists(path):os.unlink(path)

def read_snapshot(state_path,max_age_seconds=60,now=None):
    file=Path(state_path)/FILENAME
    try:
        if not 10<=file.stat().st_size<=30000:
            return {"status":"unavailable","source":"schwab"}
        data=json.loads(file.read_text(encoding="utf-8"))
        age=(now or datetime.now(timezone.utc))-datetime.fromisoformat(data["observed_at"])
        if data.get("schema")!=1 or data.get("source")!="schwab_broker_quotes" or not isinstance(data.get("symbols"),dict):
            raise ValueError
        if age.total_seconds()<0 or age.total_seconds()>max_age_seconds:
            return {"status":"stale","source":"schwab","observed_at":data["observed_at"],"age_seconds":round(age.total_seconds())}
        return {"status":"fresh","source":"schwab","observed_at":data["observed_at"],"symbols":data["symbols"],
                "quote_age_warning":"Quote exchange timing/entitlements may vary"}
    except (OSError,ValueError,TypeError,KeyError):
        return {"status":"unavailable","source":"schwab"}

def run():
    from schwab.auth import client_from_token_file
    env_path=Path(os.getenv("SCHWAB_ENV_FILE","/run/secrets/schwab.env"))
    values={}
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            a,b=line.split("=",1);values[a.strip()]=b.strip()
    app_key=values.get("SCHWAB_APP_KEY")
    secret=values.get("SCHWAB_APP_SECRET")
    token_path=os.getenv("SCHWAB_TOKEN_FILE","/state/schwab_token.json")
    if not (app_key and secret and Path(token_path).stat().st_size>0):
        raise MarketDataUnavailable("Schwab developer OAuth must be connected first")
    client=client_from_token_file(token_path,app_key,secret)
    interval=max(10,min(int(os.getenv("BROKER_MARKET_POLL_SECONDS","20")),120))
    state_dir=os.getenv("BROKER_MARKET_STATE_DIR","/state/live")
    while True:
        try:
            response=client.get_quotes(list(SYMBOLS))
            if response.status_code==200:
                normalized=normalized_quotes(response.json())
                write_snapshot(state_dir,normalized)
            else:
                # Do not fabricate or re-date old prices.
                print("Broker quote request unavailable",flush=True)
        except Exception as exc:
            # Never print underlying token, account identifiers or response bodies.
            print("Broker quote poll failed: "+type(exc).__name__,flush=True)
        time.sleep(interval)

if __name__=="__main__":
    run()
