"""Webull risk planning configuration. Does not activate order execution."""
import json
import os
import secrets
import stat
import math
from pathlib import Path
DEFAULT={"max_position_pct":5.0,"max_order_usd":100.0,
         "max_daily_loss_usd":25.0,"max_open_positions":3}
def _path(state):return Path(state)/"webull"/"risk_plan.json"
def read(state):
    target=_path(state)
    if not target.exists():return dict(DEFAULT,saved=False,execution_enabled=False)
    info=target.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_size>4096:
        raise ValueError("Unsafe Webull risk plan permissions")
    obj=json.loads(target.read_text())
    validated=validate(obj)
    return dict(validated,saved=True,execution_enabled=False)
def validate(payload):
    if not isinstance(payload,dict) or set(payload)!=set(DEFAULT):
        raise ValueError("Webull risk fields are incomplete")
    clean={}
    for field in ("max_position_pct","max_order_usd","max_daily_loss_usd"):
        val=payload[field]
        if isinstance(val,bool) or not isinstance(val,(float,int)) or not math.isfinite(val):
            raise ValueError("Invalid risk value")
        lo,hi=(0.1,25) if field=="max_position_pct" else (1,100000)
        if val<lo or val>hi:raise ValueError("Risk setting outside allowed bounds")
        clean[field]=round(float(val),2)
    count=payload["max_open_positions"]
    if isinstance(count,bool) or not isinstance(count,int) or count<1 or count>20:
        raise ValueError("Maximum positions must be 1–20")
    clean["max_open_positions"]=count
    return clean
def save(state,payload):
    plan=validate(payload)
    target=_path(state)
    target.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    if target.parent.stat().st_mode & 0o077:raise ValueError("Unsafe Webull storage permissions")
    tmp=target.parent/(".webull-risk-"+secrets.token_hex(8))
    fd=os.open(str(tmp),os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    try:
        with os.fdopen(fd,"w") as stream:
            json.dump(plan,stream)
            stream.flush();os.fsync(stream.fileno())
        os.replace(tmp,target)
    finally:
        if tmp.exists():tmp.unlink()
    return dict(plan,saved=True,execution_enabled=False)
