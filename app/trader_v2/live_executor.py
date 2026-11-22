"""Durable V2 account execution process in the original TrueNAS app.

An online process is NOT a live-order permit. A real broker-scanner is invoked
only when signed account acceptance, independent strategy parity, exclusive V2
owner and a fresh account-specific broker handoff are ALL verified. Production
defaults refuse any adapter absent those independent dependencies.
"""
from __future__ import annotations
import argparse,fcntl,os,signal,stat,time
from datetime import datetime,timezone
from pathlib import Path
from .launch_gates import BROKERS,launch_status
from .live_pipeline import WriterHandoff
from .writer_ownership import inspect_ownership
from .models import utc
from .readonly_adapters import private_json
from .recorded_replay import _atomic_json
from .v1_order_inheritance import read_inherited

STOP=False
SIGNED_GATES=frozenset(("SIGNED_PREFLIGHT_FRESH","SIGNED_ACCOUNT",
 "SIGNED_HOLDINGS","SIGNED_ORDER_HISTORY","NO_OPEN_OR_UNRESOLVED_ORDERS",
 "BROKER_PRODUCT_PERMISSIONS","EXECUTABLE_BROKER_QUOTE",
 "V1_SAVED_NUMERIC_RISK","SIGNED_SETTLED_FUNDING","SIGNED_MARKET_SESSION"))
REASONS=frozenset(("ACCOUNT_NOT_ARMED_OR_SELECTED","V1_RETAINS_ORDER_WRITER",
 "SIGNED_BROKER_ACCOUNT_PREFLIGHT_BLOCKED","V1_HISTORY_NOT_INHERITED",
 "V1_STRATEGY_AND_EXIT_PARITY_REQUIRED","TRUSTED_BROKER_EXECUTOR_NOT_WIRED",
 "V2_HANDOFF_PROOF_INVALID","V2_EXECUTOR_ADAPTER_UNVERIFIED",
 "V2_SCAN_RESPONSE_UNVERIFIED","ACCOUNT_EXECUTION_NOT_VERIFIED"))

def _selected(root,broker):
    if broker=="schwab":
        from unified_config import settings
        return settings(root).get("live_account_hash")
    if broker=="webull":
        from webull_trade_config import read
        p=read(root)
        return p.get("stock_account") if (
             p.get("enabled") is True and p.get("trade_stocks") is True) else None
    from robinhood_policy import read_policy
    p=read_policy(root)
    return p.get("account") if p.get("enabled") is True else None

def _blocked(broker,reason):
    return {"broker":broker,"state":"BLOCKED","reason":reason}

def account_cycle(root,broker,*,now=None,grant_provider=None,scanner_factory=None,
                  strategy_parity=None):
    """The only point where a V2 signed scanner may be invoked."""
    if broker not in BROKERS:raise ValueError("Unknown broker")
    now=utc(now or datetime.now(timezone.utc))
    root=Path(root)
    try:
        account=_selected(root,broker)
        if not isinstance(account,str) or not account:
            return _blocked(broker,"ACCOUNT_NOT_ARMED_OR_SELECTED")
        owner=inspect_ownership(root,broker,account)
        if not isinstance(owner,dict) or owner.get("owner")!="V2":
            return _blocked(broker,"V1_RETAINS_ORDER_WRITER")
        report=launch_status(root,broker,now=now)
        verified={g["name"] for g in report["gates"] if g.get("verified") is True}
        if not SIGNED_GATES.issubset(verified):
            return _blocked(broker,"SIGNED_BROKER_ACCOUNT_PREFLIGHT_BLOCKED")
        inherited=read_inherited(root,broker,account,now=now)
        if (inherited.local_journal_terminal is not True or
            inherited.signed_broker_history_fresh is not True):
            return _blocked(broker,"V1_HISTORY_NOT_INHERITED")
        if not callable(strategy_parity) or strategy_parity(broker,account) is not True:
            return _blocked(broker,"V1_STRATEGY_AND_EXIT_PARITY_REQUIRED")
        if not callable(grant_provider) or not callable(scanner_factory):
            return _blocked(broker,"TRUSTED_BROKER_EXECUTOR_NOT_WIRED")
        proof=grant_provider(broker,account)
        canonical=(__import__("trader_v2.schwab_stock_live_adapter",
                   fromlist=["account_alias"]).account_alias(account)
                   if broker=="schwab" else account)
        if (not isinstance(proof,WriterHandoff) or
            not proof.verified(broker,canonical,now) or
            proof.generation!=owner.get("generation")):
            return _blocked(broker,"V2_HANDOFF_PROOF_INVALID")
        scan=scanner_factory(broker,account,proof)
        if not callable(getattr(scan,"run_once",None)):
            return _blocked(broker,"V2_EXECUTOR_ADAPTER_UNVERIFIED")
        out=scan.run_once()
        if not isinstance(out,dict) or out.get("broker")!=broker:
            return _blocked(broker,"V2_SCAN_RESPONSE_UNVERIFIED")
        # Output is redacted; broker fills must be verified by a separate
        # signed broker receipt, never from this generic worker heartbeat.
        return {"broker":broker,"state":"SCANNED","reason":"SIGNED_SCAN_COMPLETED"}
    except Exception:
        return _blocked(broker,"ACCOUNT_EXECUTION_NOT_VERIFIED")

def snapshot(root,*,now=None,grant_provider=None,scanner_factory=None,
             strategy_parity=None):
    now=utc(now or datetime.now(timezone.utc))
    rows=[account_cycle(root,b,now=now,grant_provider=grant_provider,
         scanner_factory=scanner_factory,strategy_parity=strategy_parity)
         for b in BROKERS]
    return {"schema":1,"checked_at":now.isoformat(),
            "mode":"REGISTERED_GATED_EXECUTION_COORDINATOR",
            "accounts":rows}

def write_status(root,*,now=None,grant_provider=None,scanner_factory=None,
                 strategy_parity=None):
    root=Path(root)
    parent=root/"v2";target=parent/"live_executor"
    if parent.is_symlink() or target.is_symlink():
        raise PermissionError("EXECUTOR_PATH_SYMLINK")
    parent.mkdir(mode=0o700,exist_ok=True)
    target.mkdir(mode=0o700,exist_ok=True)
    if parent.stat().st_mode&0o077 or target.stat().st_mode&0o077:
        raise PermissionError("EXECUTOR_PRIVATE_DIR_REQUIRED")
    doc=snapshot(root,now=now,grant_provider=grant_provider,
                 scanner_factory=scanner_factory,strategy_parity=strategy_parity)
    _atomic_json(target/"health.json",doc)
    return doc

def public_status(root,*,now=None):
    now=utc(now or datetime.now(timezone.utc))
    doc=private_json(Path(root)/"v2/live_executor/health.json",maximum=6000)
    offline={"state":"OFFLINE_OR_STALE","registered":False,"accounts":[]}
    if not isinstance(doc,dict) or doc.get("schema")!=1 or (
         doc.get("mode")!="REGISTERED_GATED_EXECUTION_COORDINATOR"):
        return offline
    try:
        t=utc(datetime.fromisoformat(doc["checked_at"]))
        if not -2<=(now-t).total_seconds()<=75:raise ValueError
        rows=doc["accounts"]
        if not isinstance(rows,list) or len(rows)!=len(BROKERS):raise ValueError
        clean=[]
        for broker in BROKERS:
            found=[r for r in rows if isinstance(r,dict) and r.get("broker")==broker]
            if len(found)!=1:raise ValueError
            r=found[0]
            if r.get("state")=="BLOCKED" and r.get("reason") in REASONS:
                clean.append({"broker":broker,"state":"BLOCKED","reason":r["reason"]})
            elif r.get("state")=="SCANNED" and r.get("reason")=="SIGNED_SCAN_COMPLETED":
                clean.append({"broker":broker,"state":"SCANNED","reason":"SIGNED_SCAN_COMPLETED"})
            else:raise ValueError
        return {"state":"REGISTERED_GATED_EXECUTION_COORDINATOR",
                "registered":True,"checked_at":doc["checked_at"],"accounts":clean}
    except Exception:return offline

def _stop(*_):
    global STOP
    STOP=True

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--state-dir",default=os.getenv("STATE_DIR","/state"))
    args=parser.parse_args()
    signal.signal(signal.SIGTERM,_stop);signal.signal(signal.SIGINT,_stop)
    parent=Path(args.state_dir)/"v2"
    target=parent/"live_executor"
    if parent.is_symlink() or target.is_symlink():
        raise PermissionError("EXECUTOR_PATH_SYMLINK")
    parent.mkdir(mode=0o700,exist_ok=True)
    target.mkdir(mode=0o700,exist_ok=True)
    if parent.stat().st_mode&0o077 or target.stat().st_mode&0o077:
        raise PermissionError("EXECUTOR_PRIVATE_DIR_REQUIRED")
    f=os.open(target/"worker.lock",os.O_CREAT|os.O_RDWR|getattr(os,"O_NOFOLLOW",0),0o600)
    try:
        if not stat.S_ISREG(os.fstat(f).st_mode) or os.fstat(f).st_mode&0o077:
            raise PermissionError("EXECUTOR_LOCK_UNSAFE")
        fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
        while not STOP:
            try:write_status(args.state_dir)
            except Exception:print("V2_EXECUTOR_STATUS_UNAVAILABLE",flush=True)
            for _ in range(20):
                if STOP:break
                time.sleep(1)
    finally:os.close(f)

if __name__=="__main__":main()
