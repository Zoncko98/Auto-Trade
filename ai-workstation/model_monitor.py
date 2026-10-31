"""Out-of-sample next-session forecast error tracking.

Do not use this scorecard to place broker orders. Each dated prediction is
persisted before observing a future bar. Once a later daily close is present,
measure absolute log-return error and 10–90% interval coverage. A small sample
does not establish statistically calibrated probabilities.
"""
from __future__ import annotations
import json,math,os,tempfile
from datetime import datetime
from pathlib import Path
FILENAME="forecast_scorecard.json"

def _safe_load(path):
    try:
        raw=json.loads(Path(path).read_text(encoding="utf-8"))
        if isinstance(raw,list):return raw[-1500:]
    except (OSError,ValueError):pass
    return []

def _atomic(path,obj):
    p=Path(path);p.parent.mkdir(parents=True,exist_ok=True)
    fd,name=tempfile.mkstemp(dir=p.parent,prefix=".forecast-score-")
    try:
        with os.fdopen(fd,"w",encoding="utf-8") as f:
            os.fchmod(f.fileno(),0o600)
            json.dump(obj,f,allow_nan=False,separators=(",",":"))
            f.flush();os.fsync(f.fileno())
        os.replace(name,p)
    finally:
        if os.path.exists(name):os.unlink(name)

def update_scorecard(state,series,selected,now,session_open):
    path=Path(state)/FILENAME
    records=_safe_load(path)
    pending=[]
    for old in records:
        if old.get("actual") is None:
            sym=old.get("ticker")
            rows=series.get(sym,[])
            # Compare target next trading day's CLOSE to the close before forecast.
            matches=[r for r in rows if isinstance(r,dict) and r.get("date")==old.get("target_day")]
            if matches and matches[0].get("close",0)>0 and old.get("reference_close",0)>0:
                actual=math.log(matches[0]["close"]/old["reference_close"])
                old["actual"]=round(actual,7)
                old["abs_error"]=round(abs(actual-old["median"]),7) if isinstance(old.get("median"),(float,int)) else None
                if isinstance(old.get("lo"),(float,int)) and isinstance(old.get("hi"),(float,int)):
                    old["interval_covered"]=(old["lo"]<=actual<=old["hi"])
        pending.append(old)
    day=session_open[:10]
    for item in selected:
        chronos=item.get("chronos_bolt",{})
        values=chronos.get("log_return_quantiles")
        if not isinstance(values,list) or len(values)!=3:continue
        sym=item.get("ticker")
        ref=item.get("reference_close")
        asof=item.get("as_of")
        if sym not in series or not isinstance(ref,(float,int)) or ref<=0:continue
        key=(sym,day,asof)
        if any((r.get("ticker"),r.get("target_day"),r.get("as_of"))==key for r in pending):continue
        pending.append({"ticker":sym,"as_of":asof,"target_day":day,
                        "reference_close":ref,
                        "lo":values[0],"median":values[1],"hi":values[2],
                        "actual":None,"abs_error":None})
    pending=pending[-1500:]
    _atomic(path,pending)
    scored=[r for r in pending if isinstance(r.get("actual"),(float,int)) and isinstance(r.get("abs_error"),(float,int))]
    n=len(scored)
    return {"scored_predictions":n,
            "status":"calibration_monitoring" if n>=20 else "insufficient_sample",
            "median_absolute_log_return_error":round(sorted(r["abs_error"] for r in scored)[n//2],6) if n else None,
            "mean_absolute_log_return_error":round(sum(r["abs_error"] for r in scored)/n,6) if n else None,
            "quantile_interval_coverage":round(sum(bool(r.get("interval_covered")) for r in scored)/n,4) if n else None,
            "expected_interval_coverage":0.8,
            "note":"Retrospective daily-bar scorecard; not evidence of profitable or calibrated trades"}
