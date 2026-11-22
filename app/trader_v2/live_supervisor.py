"""Supervised, account-scoped V2 migration standby coordinator.

This process NEVER loads brokerage SDKs, credentials, account IDs or trading
adapters. It NEVER transfers the account writer, places or cancels orders.
Only a separately attested and explicitly armed V2 execution controller can
do so. Standby heartbeat proves observation, not order authorization.
"""
from __future__ import annotations
from datetime import datetime,timezone
from pathlib import Path
import argparse,os,signal,time

from .launch_gates import BROKERS, launch_status
from .models import utc
from .readonly_adapters import private_json
from .recorded_replay import _atomic_json

_STOP=False
POLL_SECONDS=30
WORKER_TTL_SECONDS=180
SUPPORTED_WORKER_STATES={
    "schwab":("live/worker_heartbeat.json","at","mode"),
    "webull":("webull/worker_status.json","updated_at","worker"),
    "robinhood_crypto":("robinhood/worker_status.json","updated_at","worker"),
}

def _recent(raw, now, ttl):
    if not isinstance(raw,str):return False
    try:
        dt=datetime.fromisoformat(raw.replace("Z","+00:00"))
        if dt.tzinfo is None:return False
        age=(now-dt.astimezone(timezone.utc)).total_seconds()
        return -2<=age<=ttl
    except (TypeError,ValueError,OverflowError):
        return False

def _worker_readonly(root,broker,now):
    # A timestamped worker report shows activity only. It cannot prove a
    # currently running PID or an exclusive account lock.
    path,date_key,state_key=SUPPORTED_WORKER_STATES[broker]
    doc=private_json(root/path,maximum=500000) or {}
    if not isinstance(doc,dict) or not _recent(doc.get(date_key),now,WORKER_TTL_SECONDS):
        return {"state":"STALE_OR_UNAVAILABLE","recent":False}
    field=doc.get(state_key)
    active=(doc.get("mode")=="running" if broker=="schwab" else
            field in ("RUNNING","monitoring","monitoring_degraded"))
    return {"state":"RECENT_V1_TELEMETRY" if active else "RECENT_NOT_RUNNING",
            "recent":True,
            "observed_state":str(field)[:50] if isinstance(field,str) else "NOT_VERIFIED"}

def assess(root,*,now=None):
    """Read only broker migration evidence, no owner-state change."""
    now=utc(now or datetime.now(timezone.utc))
    root=Path(root)
    accounts=[]
    for broker in BROKERS:
        launch=launch_status(root,broker,now=now)
        gates=launch["gates"]
        accounts.append({
            "broker":broker,
            "v1_worker":_worker_readonly(root,broker,now),
            "signed_preflight_fresh":launch["signed_observation_fresh"],
            "verified_gate_count":sum(g["verified"] is True for g in gates),
            "total_gate_count":len(gates),
            "first_blocker":launch["first_blocker"],
            "cutover_ready":False,
            "v2_live_order_authority":False,
            "reconciliation_state":"V2_ACCOUNT_EXECUTION_RECONCILIATION_NOT_ACCEPTED",
        })
    return {
        "schema":1,"checked_at":now.isoformat(),
        "supervisor_state":"READ_ONLY_STANDBY",
        "supervisor_registered":True,
        "replacement_live_worker_registered":False,
        "v2_live_order_authority":False,
        "v2_orders_submitted":0,
        "cutover_accounts":0,
        "accounts":accounts,
    }

def write_status(state_dir,*,now=None):
    """Persist only redacted diagnostics under an owner-only directory."""
    root=Path(state_dir)
    parent=root/"v2"
    target=parent/"live_supervisor"
    if parent.is_symlink() or target.is_symlink():
        raise PermissionError("V2_SUPERVISOR_DIRECTORY_SYMLINK")
    parent.mkdir(mode=0o700,exist_ok=True)
    target.mkdir(mode=0o700,exist_ok=True)
    if parent.stat().st_mode&0o077 or target.stat().st_mode&0o077:
        raise PermissionError("V2_SUPERVISOR_DIRECTORY_UNSAFE")
    doc=assess(root,now=now)
    _atomic_json(target/"health.json",doc)
    return doc

def public_status(state_dir,*,now=None):
    """Status API may not present a stale heartbeat as live supervision."""
    now=utc(now or datetime.now(timezone.utc))
    doc=private_json(Path(state_dir)/"v2/live_supervisor/health.json",maximum=12000)
    if (not isinstance(doc,dict) or doc.get("schema")!=1 or
        doc.get("supervisor_state")!="READ_ONLY_STANDBY" or
        doc.get("v2_live_order_authority") is not False or
        doc.get("v2_orders_submitted")!=0 or
        not _recent(doc.get("checked_at"),now,120)):
        return {"state":"OFFLINE_OR_STALE","v2_live_order_authority":False,
                "cutover_accounts":0,"accounts":[]}
    # Rebuild a bounded public subset instead of trusting arbitrary JSON
    # values or exposing account metadata.
    rows=doc.get("accounts")
    if not isinstance(rows,list) or len(rows)!=len(BROKERS):
        return {"state":"INVALID_REPORT","v2_live_order_authority":False,
                "cutover_accounts":0,"accounts":[]}
    safe=[]
    for broker in BROKERS:
        found=[row for row in rows if isinstance(row,dict) and row.get("broker")==broker]
        if len(found)!=1:return {"state":"INVALID_REPORT",
             "v2_live_order_authority":False,"cutover_accounts":0,"accounts":[]}
        row=found[0]
        count=row.get("verified_gate_count")
        total=row.get("total_gate_count")
        if (type(count) is not int or type(total) is not int or
                not 0<=count<=total<=20 or
                row.get("v2_live_order_authority") is not False):
            return {"state":"INVALID_REPORT","v2_live_order_authority":False,
                    "cutover_accounts":0,"accounts":[]}
        worker=row.get("v1_worker")
        safe.append({"broker":broker,"verified_gates":count,
                     "total_gates":total,
                     "v1_telemetry_recent":isinstance(worker,dict) and
                          worker.get("recent") is True,
                     "first_blocker":str(row.get("first_blocker") or "NOT_VERIFIED")[:100]})
    return {"state":"READ_ONLY_STANDBY","checked_at":doc["checked_at"],
            "v2_live_order_authority":False,"cutover_accounts":0,"accounts":safe}

def _terminate(_sig,_frame):
    global _STOP
    _STOP=True

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--state-dir",default=os.getenv("STATE_DIR","/state"))
    args=parser.parse_args()
    signal.signal(signal.SIGTERM,_terminate)
    signal.signal(signal.SIGINT,_terminate)
    while not _STOP:
        try:
            write_status(args.state_dir)
        except Exception:
            # Read-only migration telemetry failure must NEVER change broker
            # workers or throw away their original order/reconciliation state.
            print("V2 standby status unavailable; order authority remains V1",
                  flush=True)
        for _ in range(POLL_SECONDS):
            if _STOP:break
            time.sleep(1)

if __name__=="__main__":
    main()
