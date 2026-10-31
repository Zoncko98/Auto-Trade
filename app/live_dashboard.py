"""Read-only live Schwab dashboard and local-model selector.

This module never connects to Schwab or Docker. Reads the live worker's
deliberately de-identified state files, and the installed Ollama model tags.
The only writes are validated operator-mode and model-selection documents.
"""
from __future__ import annotations
import json
import os
import re
import ipaddress
from urllib.parse import urlparse
import ipaddress
from urllib.parse import urlparse
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen
from urllib.error import URLError
from live_extension import (read_decisions, read_live_risk, rows_from_live)

MODEL_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,95}$")
MAX_MODEL_SIZE = int(os.getenv("OLLAMA_MAX_MODEL_BYTES","7000000000"))
MAX_DOCUMENT_BYTES = 2_000_000
DEFAULT_MODEL = "qwen3.5:4b"


def _load(path: Path, default=None, limit=MAX_DOCUMENT_BYTES):
    try:
        if not path.is_file() or not 0 < path.stat().st_size <= limit:
            return default
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError, TypeError):
        return default


def installed_models(opener=urlopen):
    """Only actual local Ollama downloads; never the cloud WebUI catalog."""
    url=os.getenv("DASHBOARD_LOCAL_AI_URL","http://local-ai:11434").rstrip("/")
    if os.getenv("AUTO_UNIFIED_APP","false").lower()=="true":
        from unified_config import settings
        url=settings(os.getenv("STATE_DIR","/state")).get("ollama_url","").rstrip("/")
        if not url:raise ValueError("Configure your Ollama endpoint in Integrations first")
    parsed=urlparse(url)
    if parsed.scheme not in ("http","https") or not parsed.hostname or not parsed.port or parsed.username or parsed.password or parsed.path not in ("","/"):
        raise ValueError("Invalid local model endpoint")
    try:
        addr=ipaddress.ip_address(parsed.hostname)
        valid=addr.is_private or addr.is_loopback
    except ValueError:
        valid=parsed.hostname in ("localhost","local-ai","host.docker.internal") or parsed.hostname.endswith(".local")
    if not valid:
        raise ValueError("Ollama must use a private LAN endpoint")
    try:
        with opener(url+"/api/tags", timeout=4) as response:
            raw=response.read(131073)
        if len(raw)>131072:
            raise ValueError("Local model listing too large")
        obj=json.loads(raw)
    except (OSError,URLError,TimeoutError,ValueError,TypeError):
        raise ValueError("Local inference server unavailable") from None
    if not isinstance(obj,dict) or not isinstance(obj.get("models"),list):
        raise ValueError("Invalid local model catalog")
    output=[]
    for item in obj["models"][:50]:
        if not isinstance(item,dict):
            continue
        name,size=item.get("name"),item.get("size")
        if not isinstance(name,str) or not MODEL_PATTERN.fullmatch(name):
            continue
        if type(size) is not int or size<=0:
            continue
        details=item.get("details") or {}
        if not isinstance(details,dict):
            details={}
        output.append({
            "name":name,
            "size_mb":int(round(size/1_000_000)),
            "parameters":str(details.get("parameter_size",""))[:30],
            "selectable":size <= MAX_MODEL_SIZE
        })
    return sorted(output,key=lambda row:row["name"])


def _model_file(state_dir):
    return Path(state_dir)/"live"/"model_selection.json"


def current_model(state_dir):
    obj=_load(_model_file(state_dir),{})
    if not isinstance(obj,dict):
        obj={}
    name=obj.get("model",DEFAULT_MODEL)
    return name if isinstance(name,str) and MODEL_PATTERN.fullmatch(name) else DEFAULT_MODEL


def set_model(state_dir, name, models, atomic_writer):
    if not isinstance(name,str) or not MODEL_PATTERN.fullmatch(name):
        raise ValueError("Invalid model identifier")
    if not any(m.get("name")==name and m.get("selectable") is True for m in models):
        raise ValueError("Model is not installed or exceeds local hardware budget")
    payload={"version":1,"model":name,"updated_at":datetime.now(timezone.utc).isoformat()}
    atomic_writer(_model_file(state_dir),payload)
    return payload


def _operator_file(state_dir):
    return Path(state_dir)/"live"/"operator.json"


def operator_mode(state_dir):
    doc=_load(_operator_file(state_dir),{})
    if not isinstance(doc,dict):
        return "paused"
    return doc.get("mode") if doc.get("mode") in ("running","paused") else "paused"


def set_operator_mode(state_dir, mode, atomic_writer):
    if mode not in ("running","paused"):
        raise ValueError("Order permission must be running or paused")
    doc={"version":1,"mode":mode,"updated_at":datetime.now(timezone.utc).isoformat()}
    atomic_writer(_operator_file(state_dir),doc)
    return doc


def live_state(state_dir):
    root=Path(state_dir)/"live"
    heartbeat=_load(root/"worker_heartbeat.json",{})
    snapshot=_load(root/"account_snapshot.json",{})
    journal=_load(root/"orders.json",{})
    if not isinstance(heartbeat,dict): heartbeat={}
    if not isinstance(snapshot,dict): snapshot={}
    if not isinstance(journal,dict): journal={}
    orders=journal.get("orders",[])
    if not isinstance(orders,list): orders=[]
    trade_rows=rows_from_live(journal)
    formatted=trade_rows[-100:][::-1]
    decisions=read_decisions(state_dir,125)
    try:
        risk=read_live_risk(state_dir)
        risk_error=""
    except (ValueError,TypeError,OSError,KeyError) as exc:
        risk={"version":1,"revision":-1,"settings":{}}
        risk_error=str(exc)[:160]
    age=None
    try:
        at=datetime.fromisoformat(str(heartbeat.get("at","")).replace("Z","+00:00"))
        if at.tzinfo:
            age=max(0,int((datetime.now(timezone.utc)-at).total_seconds()))
    except (TypeError,ValueError,OverflowError):
        pass
    online=age is not None and age<=120
    # Offline and unverified statuses must not appear as 'live' just because
    # a stale heartbeat reported an armed worker.
    armed=online and heartbeat.get("armed") is True
    account={}
    for key in ("at","cash","equity","exposure","positions"):
        if key in snapshot:
            account[key]=snapshot[key]
    if not isinstance(account.get("positions",{}),dict):
        account["positions"]={}
    return {
        "worker_online":online,
        "heartbeat_age_sec":age,
        "armed":armed,
        "order_permission":operator_mode(state_dir),
        "last_model":str(heartbeat.get("model",""))[:96] if online else "",
        "account":account,
        "order_count":len(orders),
        "orders":formatted,
        "decisions":decisions,
        "risk":risk,
        "risk_error":risk_error,
        "journal_halted":journal.get("halted") is True,
        "halt_reason":str(journal.get("halt_reason",""))[:180] if journal.get("halted") else "",
        "selected_model":current_model(state_dir),
    }
